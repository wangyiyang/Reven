"""rss_candidates 绑定探针单测：字段校验与四阶段失败分支（stub api，零网络）。"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from reven.integrations.feishu_bot.bitable import (
    RSS_CANDIDATES_REQUIRED_FIELDS,
    probe_rss_candidates_binding,
    validate_required_fields,
)
from reven.integrations.feishu_bot.client import (
    BitableField,
    BitableRecord,
    BitableRecordPage,
    BitableRecordWrite,
    FeishuBotApiError,
)

VALID_FIELDS = tuple(
    BitableField(field_id=f"fld_{index}", name=name, type=field_type)
    for index, (name, field_type) in enumerate(RSS_CANDIDATES_REQUIRED_FIELDS)
)


@dataclass
class _StubBitableApi:
    """模拟 FeishuBotApiClient 的 Bitable 方法；记录 create/delete 入参。"""

    fields: tuple[BitableField, ...] = VALID_FIELDS
    fields_error: FeishuBotApiError | None = None
    search_error: FeishuBotApiError | None = None
    create_error: FeishuBotApiError | None = None
    delete_error: FeishuBotApiError | None = None
    created: list[BitableRecordWrite] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)

    async def list_fields(self, app_token: str, table_id: str) -> tuple[BitableField, ...]:
        if self.fields_error is not None:
            raise self.fields_error
        return self.fields

    async def search_records(self, app_token: str, table_id: str, **kwargs: Any) -> BitableRecordPage:
        if self.search_error is not None:
            raise self.search_error
        return BitableRecordPage(records=(), page_token=None, has_more=False)

    async def batch_create_records(
        self, app_token: str, table_id: str, records: list[BitableRecordWrite]
    ) -> tuple[BitableRecord, ...]:
        if self.create_error is not None:
            raise self.create_error
        self.created.extend(records)
        return tuple(
            BitableRecord(record_id=f"rec_probe_{index}", fields=record.fields) for index, record in enumerate(records)
        )

    async def batch_delete_records(self, app_token: str, table_id: str, record_ids: list[str]) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted_ids.extend(record_ids)


@pytest.mark.anyio
async def test_probe_success_runs_all_stages_and_deletes_created_record() -> None:
    api = _StubBitableApi()

    result = await probe_rss_candidates_binding(api, app_token="app", table_id="tbl")  # type: ignore[arg-type]

    assert result.success is True
    assert result.failed_stage is None
    assert [stage.stage for stage in result.stages] == ["fields", "search", "create", "delete"]
    assert all(stage.success for stage in result.stages)
    assert len(api.created) == 1
    assert api.deleted_ids == ["rec_probe_0"]
    # 探针记录不依赖「状态」单选选项（选项可能未配置），其余固定字段全部写入
    assert "状态" not in api.created[0].fields
    assert api.created[0].fields["去重键"] == api.created[0].client_token


@pytest.mark.anyio
async def test_probe_fields_api_failure_stops_at_fields_stage() -> None:
    api = _StubBitableApi(fields_error=FeishuBotApiError("飞书多维表格字段查询失败（code=1254043）", code=1254043))

    result = await probe_rss_candidates_binding(api, app_token="app", table_id="tbl")  # type: ignore[arg-type]

    assert result.success is False
    assert result.failed_stage == "fields"
    assert [stage.stage for stage in result.stages] == ["fields"]
    assert "code=1254043" in (result.stages[0].message or "")


@pytest.mark.anyio
async def test_probe_missing_field_fails_fields_stage() -> None:
    fields = tuple(field for field in VALID_FIELDS if field.name != "去重键")
    result = await probe_rss_candidates_binding(_StubBitableApi(fields=fields), app_token="app", table_id="tbl")  # type: ignore[arg-type]

    assert result.failed_stage == "fields"
    assert "缺少字段「去重键」" in (result.stages[-1].message or "")


@pytest.mark.anyio
async def test_probe_field_type_mismatch_fails_fields_stage() -> None:
    fields = tuple(
        BitableField(field_id=field.field_id, name=field.name, type=1 if field.name == "发布时间" else field.type)
        for field in VALID_FIELDS
    )
    result = await probe_rss_candidates_binding(_StubBitableApi(fields=fields), app_token="app", table_id="tbl")  # type: ignore[arg-type]

    assert result.failed_stage == "fields"
    assert "「发布时间」应为日期" in (result.stages[0].message or "")


@pytest.mark.anyio
async def test_probe_search_failure_stops_before_create() -> None:
    api = _StubBitableApi(search_error=FeishuBotApiError("飞书多维表格记录查询失败（code=1254290）"))

    result = await probe_rss_candidates_binding(api, app_token="app", table_id="tbl")  # type: ignore[arg-type]

    assert result.failed_stage == "search"
    assert [stage.stage for stage in result.stages] == ["fields", "search"]
    assert api.created == []


@pytest.mark.anyio
async def test_probe_create_failure_stops_before_delete() -> None:
    api = _StubBitableApi(create_error=FeishuBotApiError("飞书多维表格记录创建失败（code=1254607）"))

    result = await probe_rss_candidates_binding(api, app_token="app", table_id="tbl")  # type: ignore[arg-type]

    assert result.failed_stage == "create"
    assert [stage.stage for stage in result.stages] == ["fields", "search", "create"]
    assert api.deleted_ids == []


@pytest.mark.anyio
async def test_probe_delete_failure_marks_delete_stage_failed() -> None:
    """外部同步表不支持删除：整体判失败且提示人工清理。"""
    api = _StubBitableApi(delete_error=FeishuBotApiError("飞书多维表格记录删除失败（code=1254061）"))

    result = await probe_rss_candidates_binding(api, app_token="app", table_id="tbl")  # type: ignore[arg-type]

    assert result.success is False
    assert result.failed_stage == "delete"
    assert [stage.stage for stage in result.stages] == ["fields", "search", "create", "delete"]
    assert "外部同步表" in (result.stages[-1].message or "")


def test_validate_required_fields_passes_on_exact_match() -> None:
    assert validate_required_fields(VALID_FIELDS) is None


def test_validate_required_fields_reports_all_missing_names() -> None:
    message = validate_required_fields(())
    assert message is not None
    assert "缺少字段" in message
    for name, _ in RSS_CANDIDATES_REQUIRED_FIELDS:
        assert f"「{name}」" in message
