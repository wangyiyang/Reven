"""Tests for LLM matcher, cache, and confirmation queue."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from reven.importing.config import (
    ColumnMapping,
    ParsingConfig,
    ParsingConfigSchema,
    ColumnMappingSchema,
)
from reven.importing.fingerprint import SheetFingerprint, RowProfile


# ═══════════════════════════════════════════════════════════
# ParsingConfig Pydantic schema
# ═══════════════════════════════════════════════════════════


def test_parsing_config_schema_valid():
    """Pydantic schema 接受合法输入。"""
    raw = """{
        "template_id": "my_template",
        "template_family": "test",
        "confidence": 0.85,
        "header_row": 5,
        "data_start_row": 6,
        "data_start_col": 2,
        "column_mappings": [
            {"target": "date", "source_name": "日期", "dtype": "date"},
            {"target": "amount", "source_name": "金额", "dtype": "amount"}
        ],
        "skip_patterns": ["合[计计]", "第\\\\s*\\\\d+\\\\s*页"],
        "merge_strategy": "none",
        "validate_total": true
    }"""
    schema = ParsingConfigSchema.model_validate_json(raw)
    assert schema.template_id == "my_template"
    assert schema.confidence == 0.85
    assert len(schema.column_mappings) == 2
    assert schema.merge_strategy == "none"
    assert schema.validate_total is True


def test_parsing_config_schema_invalid_confidence():
    """置信度越界时自动截断。"""
    raw = '{"template_id": "t", "header_row": 1, "confidence": 1.5}'
    schema = ParsingConfigSchema.model_validate_json(raw)
    assert schema.confidence == 1.0


def test_parsing_config_schema_invalid_merge_strategy():
    """无效 merge_strategy 抛出错误。"""
    raw = '{"template_id": "t", "header_row": 1, "merge_strategy": "invalid"}'
    with pytest.raises(Exception):
        ParsingConfigSchema.model_validate_json(raw)


def test_parsing_config_schema_to_parsing_config():
    """Pydantic schema → dataclass ParsingConfig 转换。"""
    raw = """{
        "template_id": "t1",
        "template_family": "sales_order",
        "confidence": 0.8,
        "header_row": 5,
        "column_mappings": [
            {"target": "date", "source_name": "日期", "dtype": "date"}
        ]
    }"""
    schema = ParsingConfigSchema.model_validate_json(raw)
    cfg = schema.to_parsing_config()
    assert cfg.template_id == "t1"
    assert cfg.source == "llm"
    assert cfg.confidence == 0.8
    assert len(cfg.column_mappings) == 1
    assert cfg.column_mappings[0].target == "date"


def test_column_mapping_schema_valid():
    """ColumnMappingSchema 接受合法输入。"""
    raw = '{"target": "amount", "source_name": "金额", "dtype": "amount"}'
    schema = ColumnMappingSchema.model_validate_json(raw)
    assert schema.target == "amount"
    assert schema.dtype == "amount"


def test_column_mapping_schema_empty_target():
    """空 target 抛出错误。"""
    raw = '{"target": "  ", "source_name": "金额"}'
    with pytest.raises(Exception):
        ColumnMappingSchema.model_validate_json(raw)


# ═══════════════════════════════════════════════════════════
# source 字段
# ═══════════════════════════════════════════════════════════


def test_parsing_config_source_default():
    """ParsingConfig 默认 source='rule'。"""
    cfg = ParsingConfig(
        template_id="test",
        template_family="test",
        header_row=1,
    )
    assert cfg.source == "rule"


def test_parsing_config_source_llm():
    """设置 source='llm' 可序列化/反序列化。"""
    cfg = ParsingConfig(
        template_id="t",
        template_family="f",
        header_row=1,
        source="llm",
    )
    d = cfg.to_dict()
    assert d["source"] == "llm"
    restored = ParsingConfig.from_dict(d)
    assert restored.source == "llm"


# ═══════════════════════════════════════════════════════════
# Template cache
# ═══════════════════════════════════════════════════════════


def _make_fingerprint(header_names: list[str]) -> SheetFingerprint:
    """创建测试用的 SheetFingerprint。"""
    return SheetFingerprint(
        index=0,
        name="test_sheet",
        total_rows=100,
        total_cols=len(header_names),
        header_signature=header_names,
        header_candidates=[
            RowProfile(index=5, non_empty_count=3, total_cells=3, is_header_like=True, sample_values=header_names)
        ],
        data_region={"start_row": 6, "end_row": 100, "start_col": 1, "end_col": len(header_names)},
    )


def test_cache_put_and_get(tmp_path):
    """存入缓存后可以取出。"""
    from reven.intelligence.cache import TemplateCache

    db_path = str(tmp_path / "test_cache.db")
    cache = TemplateCache(db_path=db_path)

    cfg = ParsingConfig(
        template_id="t1",
        template_family="test",
        header_row=5,
        confidence=0.95,
        source="confirmed",
        column_mappings=[
            ColumnMapping(target="date", source_name="日期", dtype="date"),
        ],
    )
    cache.put(cfg, header_signature=["日期"])

    fp = _make_fingerprint(["日期"])
    result = cache.get(fp)
    assert result is not None
    assert result.template_id == "t1"
    assert result.source == "cache"
    assert result.confidence == 0.95  # cache 返回原始置信度


def test_cache_miss(tmp_path):
    """未缓存的签名返回 None。"""
    from reven.intelligence.cache import TemplateCache

    db_path = str(tmp_path / "test_cache.db")
    cache = TemplateCache(db_path=db_path)

    fp = _make_fingerprint(["未缓存列名"])
    result = cache.get(fp)
    assert result is None


def test_cache_hit_count_increments(tmp_path):
    """缓存命中次数递增。"""
    from reven.intelligence.cache import TemplateCache

    db_path = str(tmp_path / "test_cache.db")
    cache = TemplateCache(db_path=db_path)

    cfg = ParsingConfig(
        template_id="t1",
        template_family="test",
        header_row=5,
        column_mappings=[ColumnMapping(target="name", source_name="名称", dtype="string")],
    )
    cache.put(cfg, header_signature=["名称"])

    fp = _make_fingerprint(["名称"])
    cache.get(fp)
    cache.get(fp)

    entries = cache.list_entries()
    assert len(entries) == 1
    assert entries[0]["hit_count"] >= 2


def test_cache_list_entries(tmp_path):
    """list_entries 返回所有条目。"""
    from reven.intelligence.cache import TemplateCache

    db_path = str(tmp_path / "test_cache.db")
    cache = TemplateCache(db_path=db_path)

    cfg = ParsingConfig(
        template_id="t1",
        template_family="test",
        header_row=5,
        column_mappings=[ColumnMapping(target="a", source_name="A", dtype="string")],
    )
    cache.put(cfg, header_signature=["A"])

    entries = cache.list_entries()
    assert len(entries) == 1
    assert entries[0]["header_signature"] is not None


# ═══════════════════════════════════════════════════════════
# Confirmation queue
# ═══════════════════════════════════════════════════════════


def test_confirmation_queue_enqueue_list(tmp_path):
    """入队后可在 pending 列表中看到。"""
    from reven.intelligence.confirmation import ConfirmationQueue

    db_path = str(tmp_path / "test_confirm.db")
    queue = ConfirmationQueue(db_path=db_path)

    queue.enqueue(
        file_path="test.xlsx",
        header_signature=["日期", "金额"],
        config_dict={"template_id": "t1"},
        confidence=0.5,
    )
    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0]["file_path"] == "test.xlsx"
    assert pending[0]["confidence"] == 0.5


def test_confirmation_queue_approve(tmp_path):
    """批准后条目不再在 pending 中。"""
    from reven.intelligence.confirmation import ConfirmationQueue

    db_path = str(tmp_path / "test_confirm.db")
    queue = ConfirmationQueue(db_path=db_path)

    item_id = queue.enqueue(
        file_path="test.xlsx",
        header_signature=["A"],
        config_dict={"template_id": "t1"},
        confidence=0.4,
    )
    assert queue.approve(item_id, "人工确认通过")

    pending = queue.list_pending()
    assert len(pending) == 0


def test_confirmation_queue_reject(tmp_path):
    """驳回后状态为 rejected。"""
    from reven.intelligence.confirmation import ConfirmationQueue

    db_path = str(tmp_path / "test_confirm.db")
    queue = ConfirmationQueue(db_path=db_path)

    item_id = queue.enqueue(
        file_path="test.xlsx",
        header_signature=["A"],
        config_dict={"template_id": "t1"},
        confidence=0.3,
    )
    assert queue.reject(item_id, "格式不对")

    stats = queue.stats()
    assert stats["rejected"] == 1


def test_confirmation_queue_stats(tmp_path):
    """stats 返回各状态计数。"""
    from reven.intelligence.confirmation import ConfirmationQueue

    db_path = str(tmp_path / "test_confirm.db")
    queue = ConfirmationQueue(db_path=db_path)

    queue.enqueue(file_path="a.xlsx", header_signature=["A"], config_dict=None, confidence=0.0)
    queue.enqueue(file_path="b.xlsx", header_signature=["B"], config_dict=None, confidence=0.1)

    stats = queue.stats()
    assert stats["pending"] == 2
    assert stats["approved"] == 0
    assert stats["rejected"] == 0


# ═══════════════════════════════════════════════════════════
# LLM matcher (mocked)
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def sample_fingerprint() -> SheetFingerprint:
    """构造一个不命中任何规则匹配器的测试指纹。"""
    return SheetFingerprint(
        index=0,
        name="unknown_format",
        total_rows=50,
        total_cols=5,
        header_signature=["日期", "商品", "数量", "单价", "金额"],
        header_candidates=[
            RowProfile(
                index=3,
                non_empty_count=5,
                total_cells=5,
                is_header_like=True,
                sample_values=["日期", "商品", "数量", "单价", "金额"],
            ),
            RowProfile(
                index=4,
                non_empty_count=5,
                total_cells=5,
                is_header_like=False,
                sample_values=["2026-01-01", "商品A", "10", "100", "1000"],
            ),
        ],
        data_region={"start_row": 3, "end_row": 50, "start_col": 1, "end_col": 5},
        column_density=[90, 85, 80, 75, 70],
    )


@pytest.fixture(autouse=True)
def _clear_llm_state():
    """每个测试前清除 LLM matcher 的全局缓存和队列。"""
    from reven.intelligence.llm_matcher import _cache, _queue

    if _cache is not None:
        _cache.clear()
    import reven.intelligence.llm_matcher as lm

    lm._cache = None  # type: ignore[misc]
    lm._queue = None  # type: ignore[misc]


def _mock_openai_response(content: str) -> MagicMock:
    """模拟 OpenAI 响应的工具函数。"""
    mock_choice = MagicMock()
    mock_choice.message.content = content

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50

    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = mock_usage
    return mock_resp


def test_llm_matcher_success(sample_fingerprint, monkeypatch):
    """LLM 匹配器成功返回配置。"""
    from reven.intelligence.llm_matcher import llm_matcher

    mock_resp = _mock_openai_response(json.dumps({
        "template_id": "custom_order",
        "template_family": "sales_order",
        "confidence": 0.85,
        "header_row": 3,
        "data_start_row": 4,
        "data_start_col": 1,
        "column_mappings": [
            {"target": "date", "source_name": "日期", "dtype": "date"},
            {"target": "product", "source_name": "商品", "dtype": "string"},
            {"target": "quantity", "source_name": "数量", "dtype": "numeric"},
            {"target": "unit_price", "source_name": "单价", "dtype": "amount"},
            {"target": "amount", "source_name": "金额", "dtype": "amount"},
        ],
        "skip_patterns": ["合[计计]", "第\\\\s*\\\\d+\\\\s*页"],
        "merge_strategy": "none",
        "validate_total": True,
    }))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")

    with patch("reven.intelligence.llm_matcher.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        MockOpenAI.return_value = mock_client

        cfg = llm_matcher(sample_fingerprint)

    assert cfg is not None
    assert cfg.template_id == "custom_order"
    assert cfg.source == "llm"
    assert cfg.confidence <= 0.8  # 被封顶
    assert len(cfg.column_mappings) == 5
    assert cfg.validate_total is True


def test_llm_matcher_no_api_key(sample_fingerprint, monkeypatch):
    """未配置 API key 时返回 None。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # 重新加载模块级单例
    import reven.intelligence.llm_matcher as lm
    lm._cache = None
    lm._queue = None

    from reven.intelligence.llm_matcher import llm_matcher

    cfg = llm_matcher(sample_fingerprint)
    assert cfg is None


def test_llm_matcher_retry_on_empty(sample_fingerprint, monkeypatch):
    """空响应触发重试，最终成功。"""
    from reven.intelligence.llm_matcher import llm_matcher

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")

    # 第一次空响应，第二次有效
    empty_resp = _mock_openai_response("")
    valid_resp = _mock_openai_response(json.dumps({
        "template_id": "t1",
        "template_family": "test",
        "confidence": 0.75,
        "header_row": 3,
        "data_start_row": 4,
        "column_mappings": [{"target": "date", "source_name": "日期", "dtype": "date"}],
    }))

    call_count = 0

    def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return empty_resp if call_count == 1 else valid_resp

    with patch("reven.intelligence.llm_matcher.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _side_effect
        MockOpenAI.return_value = mock_client

        cfg = llm_matcher(sample_fingerprint)

    assert cfg is not None
    assert cfg.template_id == "t1"


def test_llm_matcher_all_retries_fail(sample_fingerprint, monkeypatch):
    """所有重试都失败后返回 None 并入队列。"""
    from reven.intelligence.llm_matcher import llm_matcher

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")

    empty_resp = _mock_openai_response("")

    with patch("reven.intelligence.llm_matcher.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = empty_resp
        MockOpenAI.return_value = mock_client

        cfg = llm_matcher(sample_fingerprint)

    assert cfg is None

    # 验证入人工队列
    from reven.intelligence.llm_matcher import _get_queue

    q = _get_queue()
    pending = q.list_pending()
    assert len(pending) >= 1
    assert pending[0]["error"] is not None


def test_llm_matcher_cached(sample_fingerprint, monkeypatch, tmp_path):
    """第二次匹配同签名时命中缓存。"""
    from reven.intelligence.llm_matcher import llm_matcher, _get_cache

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")

    # 预先写入缓存（使用模块级缓存单例）
    cache = _get_cache()
    cache.clear()

    from reven.importing.config import ParsingConfig, ColumnMapping

    cached_cfg = ParsingConfig(
        template_id="cached_template",
        template_family="sales_order",
        header_row=3,
        confidence=0.95,
        source="confirmed",
        column_mappings=[
            ColumnMapping(target="date", source_name="日期", dtype="date"),
        ],
    )
    # 用 sample_fingerprint 的完整 header_signature 作为缓存键
    cache.put(cached_cfg, header_signature=sample_fingerprint.header_signature)

    # 现在调用 llm_matcher 应命中缓存（不调用 OpenAI）
    with patch("reven.intelligence.llm_matcher.OpenAI") as MockOpenAI:
        cfg = llm_matcher(sample_fingerprint)
        MockOpenAI.assert_not_called()

    assert cfg is not None
    assert cfg.template_id == "cached_template"
    assert cfg.source == "cache"


def test_template_registry_llm_wired():
    """default_registry 包含 LLM 匹配器。"""
    from reven.importing.template import default_registry

    registry = default_registry()
    names = [name for name, _ in registry.matchers]
    assert "llm" in names
    assert names[-1] == "llm"  # 排最后


def test_llm_matcher_low_confidence_enqueues(sample_fingerprint, monkeypatch):
    """低置信度 LLM 配置入人工确认队列。"""
    from reven.intelligence.llm_matcher import llm_matcher, _get_queue

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")
    monkeypatch.setenv("CONFIRMATION_THRESHOLD", "0.9")  # 设得比 0.8 封顶高，必然触发

    mock_resp = _mock_openai_response(json.dumps({
        "template_id": "low_conf",
        "template_family": "test",
        "confidence": 0.5,
        "header_row": 3,
        "data_start_row": 4,
        "column_mappings": [{"target": "date", "source_name": "日期", "dtype": "date"}],
    }))

    with patch("reven.intelligence.llm_matcher.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        MockOpenAI.return_value = mock_client

        _ = llm_matcher(sample_fingerprint)

    q = _get_queue()
    pending = q.list_pending()
    assert len(pending) >= 1
