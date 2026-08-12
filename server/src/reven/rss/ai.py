"""SiliconFlow chat adapter for RSS translation and optional boundary review."""

import json
import math
from collections.abc import Sequence
from typing import Any

import httpx

from reven.rss.discovery import FeedEntry, LocalizedEntry
from reven.rss.screening import ModelJudgement, ScreeningDocument

MAX_RESPONSE_BYTES = 1024 * 1024
LOCALIZE_BATCH_SIZE = 5


class SiliconFlowChatClient:
    def __init__(self, api_key: str, *, model: str, http: httpx.AsyncClient) -> None:
        if not api_key or not model:
            raise ValueError("SiliconFlow API Key 与 Chat 模型不能为空")
        if http.base_url.scheme != "https" or http.base_url.host != "api.siliconflow.cn":
            raise ValueError("SiliconFlow 客户端必须使用官方 HTTPS API")
        self._api_key = api_key
        self._model = model
        self._http = http

    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        localized: list[LocalizedEntry] = []
        for start in range(0, len(entries), LOCALIZE_BATCH_SIZE):
            batch = entries[start : start + LOCALIZE_BATCH_SIZE]
            content = await self._complete_json(_localize_messages(batch))
            translations = _parse_translations(content, len(batch))
            localized.extend(
                LocalizedEntry(entry, title_zh, summary_zh)
                for entry, (title_zh, summary_zh) in zip(batch, translations, strict=True)
            )
        return tuple(localized)

    async def judge(self, document: ScreeningDocument, evidence: dict[str, object]) -> ModelJudgement:
        content = await self._complete_json(_judge_messages(document, evidence))
        if not isinstance(content, dict):
            raise RuntimeError("SiliconFlow 判断响应格式无效")
        recommended = content.get("recommended")
        score = content.get("score")
        reason = content.get("reason")
        if (
            not isinstance(recommended, bool)
            or not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
            or not 0 <= score <= 1
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise RuntimeError("SiliconFlow 判断响应格式无效")
        return ModelJudgement(recommended, float(score), reason.strip()[:500])

    async def _complete_json(self, messages: list[dict[str, str]]) -> Any:
        try:
            async with self._http.stream(
                "POST",
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "enable_thinking": False,
                    "temperature": 0,
                },
            ) as response:
                body = await _bounded_body(response)
                status = response.status_code
        except httpx.HTTPError as exc:
            raise RuntimeError("SiliconFlow Chat 网络请求失败") from exc
        if not 200 <= status < 300:
            raise RuntimeError(f"SiliconFlow Chat 请求失败（HTTP {status}）")
        try:
            payload = json.loads(body)
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
            return json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("SiliconFlow Chat 响应格式无效") from exc


def _localize_messages(entries: Sequence[FeedEntry]) -> list[dict[str, str]]:
    input_items = [
        {"index": index, "title": entry.title[:2000], "summary": entry.summary[:6000]}
        for index, entry in enumerate(entries)
    ]
    return [
        {
            "role": "system",
            "content": (
                "你是中文科技编辑。将输入标题和摘要准确翻译或改写为简体中文；专有名词保留。"
                "只返回 JSON 对象，顶层 items 为数组；每项必须含 index、title_zh、summary_zh，不得添加 Markdown。"
            ),
        },
        {"role": "user", "content": json.dumps(input_items, ensure_ascii=False)},
    ]


def _judge_messages(document: ScreeningDocument, evidence: dict[str, object]) -> list[dict[str, str]]:
    payload = {
        "title": document.title[:2000],
        "summary": document.summary[:6000],
        "evidence": evidence,
    }
    return [
        {
            "role": "system",
            "content": (
                "你是科技素材筛选复核员。只依据内容与给定证据判断是否值得人工审阅。"
                "只返回 JSON 对象：recommended(boolean)、score(0到1)、reason(简短中文)。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _parse_translations(value: object, expected: int) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or set(value) != {"items"}:
        raise RuntimeError("SiliconFlow 翻译响应格式无效")
    items = value["items"]
    if not isinstance(items, list) or len(items) != expected:
        raise RuntimeError("SiliconFlow 翻译响应格式无效")
    ordered: list[tuple[str, str] | None] = [None] * expected
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("SiliconFlow 翻译响应格式无效")
        index = item.get("index")
        title = item.get("title_zh")
        summary = item.get("summary_zh")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < expected
            or ordered[index] is not None
            or not isinstance(title, str)
            or not title.strip()
            or not isinstance(summary, str)
        ):
            raise RuntimeError("SiliconFlow 翻译响应格式无效")
        ordered[index] = (title.strip()[:2000], summary.strip()[:6000])
    if any(item is None for item in ordered):
        raise RuntimeError("SiliconFlow 翻译响应格式无效")
    return tuple(item for item in ordered if item is not None)


async def _bounded_body(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise RuntimeError("SiliconFlow Chat 响应超过大小限制")
        chunks.append(chunk)
    return b"".join(chunks)
