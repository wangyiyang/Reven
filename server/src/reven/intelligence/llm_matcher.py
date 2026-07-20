"""LLM 匹配器 — 通过 DeepSeek API 为未见过的格式生成 ParsingConfig。

实现了 MatcherFn 签名：
    llm_matcher(fp: SheetFingerprint) -> ParsingConfig | None

工作流：
    结构指纹 → build_prompt → DeepSeek API（JSON mode）→ Pydantic 校验 → ParsingConfig
                          ↕ 重试最多 3 次（含空响应 / schema 校验失败反馈）

遵守核心原则：数据本身不经过模型。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openai import OpenAI

from reven.intelligence.prompt import build_prompt
from reven.intelligence.cache import TemplateCache
from reven.intelligence.confirmation import ConfirmationQueue
from reven.intelligence.settings import (
    DEEPSEEK_BASE_URL,
    LLM_CONFIDENCE_CAP,
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_MODEL_DEFAULT,
    LLM_MODEL_FALLBACK,
    LLM_TEMPERATURE,
    CONFIRMATION_THRESHOLD,
)
from reven.importing.config import ParsingConfigSchema

if TYPE_CHECKING:
    from reven.importing.fingerprint import SheetFingerprint
    from reven.importing.config import ParsingConfig

log = logging.getLogger(__name__)

# ── 全局缓存 & 确认队列（模块级单例） ───────────────
_cache: TemplateCache | None = None
_queue: ConfirmationQueue | None = None


def _get_cache() -> TemplateCache:
    global _cache
    if _cache is None:
        _cache = TemplateCache()
    return _cache


def _get_queue() -> ConfirmationQueue:
    global _queue
    if _queue is None:
        _queue = ConfirmationQueue()
    return _queue


def _get_client() -> OpenAI | None:
    """创建 DeepSeek API 客户端。

    每次获取 API key 时从环境变量读取（而非模块加载时），
    以支持测试中动态设置。
    未配置 API_KEY 时不报错（返回 None），允许无 LLM 模式运行。
    """
    import os

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        log.warning("DEEPSEEK_API_KEY 未设置，LLM 匹配器不可用")
        return None
    return OpenAI(
        base_url=f"{os.environ.get('DEEPSEEK_BASE_URL', DEEPSEEK_BASE_URL).rstrip('/')}/v1",
        api_key=api_key,
    )


# ═══════════════════════════════════════════════════════════
# LLM 匹配器（MatcherFn 签名）
# ═══════════════════════════════════════════════════════════


def llm_matcher(fp: SheetFingerprint) -> ParsingConfig | None:
    """通过 DeepSeek API 为未见过的格式生成 ParsingConfig。

    匹配顺序（由调用方控制 — 规则匹配器全部未命中后才调用此函数）：
        1. 检查模板配置缓存是否命中
        2. 调用 LLM 生成配置（最多重试 MAX_RETRIES 次）
        3. Pydantic 校验通过后封顶置信度
        4. 置信度低于阈值则入人工确认队列
        5. 返回 ParsingConfig

    Args:
        fp: 单个 sheet 的结构指纹（仅含结构元数据，不含全量数据）。

    Returns:
        若 LLM 成功生成有效配置则返回 ParsingConfig（含封顶置信度），
        否则返回 None（由调用方决定是否进入人工确认队列）。
    """
    # 1. 检查缓存
    cache = _get_cache()
    cached = cache.get(fp)
    if cached is not None:
        log.info("LLM 缓存命中: header_signature=%s", fp.header_signature[:3])
        cached.source = "cache"
        return cached

    # 2. 检查 API 可用性
    client = _get_client()
    if client is None:
        return None

    # 3. 构建 prompt 并调用 LLM
    prompt = build_prompt(fp)
    last_error: str | None = None

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        log.info("LLM 匹配尝试 %d/%d: sheet=%s", attempt, LLM_MAX_RETRIES, fp.name)
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL_DEFAULT,
                response_format={"type": "json_object"},
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
                messages=[
                    {"role": "user", "content": prompt},
                ],
            )
            raw = resp.choices[0].message.content
        except Exception as e:
            log.warning("LLM API 调用失败(attempt %d): %s", attempt, e)
            last_error = str(e)
            continue

        if not raw or not raw.strip():
            log.warning("LLM 返回空响应(attempt %d)", attempt)
            last_error = "empty_response"
            continue

        # 4. Pydantic 校验
        try:
            schema = ParsingConfigSchema.model_validate_json(raw)
        except Exception as e:
            log.warning("LLM 输出 schema 校验失败(attempt %d): %s", attempt, e)
            last_error = f"schema_validation: {e}"
            # 带反馈重试：将错误信息追加到 prompt
            prompt += f"\n\n## 上次输出校验失败\n错误: {e}\n请确保输出是合法的 JSON 并按 schema 要求重新输出。"
            continue

        # 5. 校验通过 — 封顶置信度，转换输出
        cfg = schema.to_parsing_config()
        cfg.confidence = min(cfg.confidence, LLM_CONFIDENCE_CAP)
        cfg.source = "llm"

        log.info(
            "LLM 匹配成功: template=%s, confidence=%.2f",
            cfg.template_id,
            cfg.confidence,
        )

        # 6. 低置信度 → 入人工确认队列
        if cfg.confidence < CONFIRMATION_THRESHOLD:
            queue = _get_queue()
            queue.enqueue(
                file_path=fp.name,
                header_signature=list(fp.header_signature),
                config_dict=cfg.to_dict(),
                confidence=cfg.confidence,
            )
            log.info("LLM 产出置信度 %.2f 低于阈值 %.2f，已入人工确认队列", cfg.confidence, CONFIRMATION_THRESHOLD)

        return cfg

    # 7. 所有重试失败 → 入人工确认队列
    log.warning("LLM 匹配全部失败（%d次）: last_error=%s", LLM_MAX_RETRIES, last_error)
    queue = _get_queue()
    queue.enqueue(
        file_path=fp.name,
        header_signature=list(fp.header_signature),
        config_dict=None,
        confidence=0.0,
        error=last_error,
    )
    return None


def llm_matcher_fallback(fp: SheetFingerprint) -> ParsingConfig | None:
    """二级兜底：flash 失败时用 pro 模型重试。

    由调用方在首次 llm_matcher 失败后选择性调用。
    """
    import os

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None

    prompt = build_prompt(fp)
    client = _get_client()
    if client is None:
        return None

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL_FALLBACK,
                response_format={"type": "json_object"},
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content
            if not raw:
                continue
            schema = ParsingConfigSchema.model_validate_json(raw)
            cfg = schema.to_parsing_config()
            cfg.confidence = min(cfg.confidence, LLM_CONFIDENCE_CAP - 0.05)
            cfg.source = "llm"
            return cfg
        except Exception as e:
            log.warning("LLM fallback 失败(attempt %d): %s", attempt, e)
            prompt += f"\n\n## 上次输出校验失败\n错误: {e}"
    return None
