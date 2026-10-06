import asyncio
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp.exceptions import ToolError
from reven.agent.executor import ToolExecutor
from reven.agent.models import AgentOperation
from reven.agent.tool_definition import ToolDefinition
from reven.agent.tool_errors import AgentOperationConflictError, AgentToolContextError
from reven.agent.tool_registry import ToolRegistry
from reven.crm.models import Customer, FollowUp
from reven.rss.models import RssKeyword
from reven.talents.models import TalentEducation, TalentExperience
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tool_execution_support import ToolRig, build_tool_rig
from tool_execution_support import tool_rig as tool_rig


async def _followup_args(rig: ToolRig) -> dict[str, object]:
    await rig.execute("crm_customer_create", {"name": "事务客户"}, "customer")
    return {
        "customer_id": str(await rig.entity_id("customer")),
        "kind": "电话",
        "occurred_on": "2026-10-06",
        "summary": "确认需求",
    }


async def _count(rig: ToolRig, model: Any) -> int:
    async with rig.factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.anyio
async def test_followup_concurrent_replay_has_one_business_row_and_saved_receipt(tool_rig: ToolRig) -> None:
    args = await _followup_args(tool_rig)
    first, duplicate = await asyncio.gather(
        tool_rig.execute("crm_follow_up_create", args, "followup"),
        tool_rig.execute("crm_follow_up_create", args, "followup"),
    )
    assert first == duplicate
    assert await _count(tool_rig, FollowUp) == 1
    operation = await tool_rig.operation("followup")
    assert operation is not None
    assert operation.result["output"] == first
    assert operation.result["entities"]["records"] == [
        {"table": "crm_follow_ups", "id": str(await tool_rig.entity_id("followup"))}
    ]
    assert operation.args["contact_id"] is None
    assert operation.args["next_due_on"] is None


@pytest.mark.anyio
async def test_same_call_cannot_change_name_or_arguments(tool_rig: ToolRig) -> None:
    args = await _followup_args(tool_rig)
    await tool_rig.execute("crm_follow_up_create", args, "followup")
    with pytest.raises(AgentOperationConflictError):
        await tool_rig.execute("crm_follow_up_create", {**args, "summary": "伪造新内容"}, "followup")
    with pytest.raises(AgentOperationConflictError):
        await tool_rig.execute("crm_customer_create", {"name": "其他客户"}, "followup")
    assert await _count(tool_rig, FollowUp) == 1
    assert await _count(tool_rig, Customer) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["owner_id", "session_id", "run_id"])
async def test_write_context_must_belong_to_run(tool_rig: ToolRig, field: str) -> None:
    context = replace(tool_rig.context, **{field: "other-user" if field == "owner_id" else uuid4()})
    with pytest.raises(AgentToolContextError):
        await tool_rig.registry.execute("crm_customer_create", {"name": "不能写入"}, context, "bad-context")
    assert await _count(tool_rig, Customer) == 0
    assert await _count(tool_rig, AgentOperation) == 0


@pytest.mark.anyio
async def test_failure_after_domain_flush_rolls_back_business_and_receipt(
    tool_rig: ToolRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ToolDefinition.invoke

    async def fail_after_flush(
        self: ToolDefinition, arguments: dict[str, object], *, session: AsyncSession | None = None
    ):
        await original(self, arguments, session=session)
        raise RuntimeError("业务写入后、账本写入前中断")

    monkeypatch.setattr(ToolDefinition, "invoke", fail_after_flush)
    with pytest.raises(RuntimeError, match="账本写入前"):
        await tool_rig.execute("crm_customer_create", {"name": "应回滚"}, "rollback")
    assert await _count(tool_rig, Customer) == 0
    assert await _count(tool_rig, AgentOperation) == 0


@pytest.mark.anyio
async def test_committed_response_loss_replays_without_second_followup(
    tool_rig: ToolRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = await _followup_args(tool_rig)
    original = ToolExecutor._write
    fail_once = True

    async def lose_response(self: ToolExecutor, *values: Any, **kwargs: Any):
        nonlocal fail_once
        result = await original(self, *values, **kwargs)
        if fail_once:
            fail_once = False
            raise ConnectionError("提交成功后响应丢失")
        return result

    monkeypatch.setattr(ToolExecutor, "_write", lose_response)
    with pytest.raises(ConnectionError, match="响应丢失"):
        await tool_rig.execute("crm_follow_up_create", args, "committed")
    saved = await tool_rig.operation("committed")
    assert saved is not None
    rebuilt = ToolRegistry(tool_rig.factory)
    replay = await rebuilt.execute("crm_follow_up_create", args, tool_rig.context, "committed")
    assert replay == saved.result["output"]
    assert await _count(tool_rig, FollowUp) == 1


@pytest.mark.anyio
async def test_import_replay_is_idempotent_but_new_call_appends_profile_children(tool_rig: ToolRig) -> None:
    args: dict[str, object] = {
        "name": "简历人才",
        "experiences": [{"company": "设计公司", "title": "设计师", "start_on": "2023-01-01"}],
        "educations": [{"school": "设计学院", "start_on": "2018-09-01"}],
    }
    result = await tool_rig.execute("talent_import_profile", args, "import-first")
    assert await tool_rig.execute("talent_import_profile", args, "import-first") == result
    assert await _count(tool_rig, TalentExperience) == 1
    assert await _count(tool_rig, TalentEducation) == 1
    await tool_rig.execute("talent_import_profile", args, "import-new")
    assert await _count(tool_rig, TalentExperience) == 2
    assert await _count(tool_rig, TalentEducation) == 2
    assert await tool_rig.entity_id("import-first") == await tool_rig.entity_id("import-new")


class RecoverableEmbedding:
    def __init__(self) -> None:
        self.rig: ToolRig | None = None
        self.available = False
        self.visible_rows: list[int] = []

    async def refresh(self, *, force: bool = False) -> int:
        assert self.rig is not None
        self.visible_rows.append(await _count(self.rig, RssKeyword))
        if not self.available:
            raise RuntimeError("暂时不可用")
        return 1

    async def estimate_hits(self, keyword_id: UUID) -> int | None:
        return 7


@pytest.mark.anyio
async def test_rss_embedding_runs_after_commit_and_pending_replay_only_refreshes(db_session: AsyncSession) -> None:
    embedding = RecoverableEmbedding()
    rig = await build_tool_rig(db_session, embedding_refresher=embedding)
    embedding.rig = rig
    args = {"term": "供应链", "kind": "positive"}
    first = await rig.execute("rss_keyword_create", args, "keyword")
    assert isinstance(first, dict) and first["embedding_status"] == "pending"
    assert embedding.visible_rows == [1]
    embedding.available = True
    second = await rig.execute("rss_keyword_create", args, "keyword")
    assert isinstance(second, dict) and second["embedding_status"] == "ready" and second["hit_count"] == 7
    assert embedding.visible_rows == [1, 1]
    saved = await rig.operation("keyword")
    assert saved is not None and saved.result["output"] == second
    assert await _count(rig, RssKeyword) == 1
    assert await rig.execute("rss_keyword_create", args, "keyword") == second
    assert embedding.visible_rows == [1, 1]


@pytest.mark.anyio
async def test_invalid_business_input_does_not_save_operation(tool_rig: ToolRig) -> None:
    args = await _followup_args(tool_rig)
    with pytest.raises(ToolError):
        await tool_rig.execute("crm_follow_up_create", {**args, "next_due_on": "2026-10-07"}, "invalid")
    assert await _count(tool_rig, FollowUp) == 0
    assert await tool_rig.operation("invalid") is None
