"""Database behavior through the complete CRM mutation interface."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from reven.crm.errors import ContactNotFoundError, CustomerNotFoundError, FollowUpNotFoundError, InvalidActionPairError
from reven.crm.inputs import (
    ContactCreate,
    ContactUpdate,
    CustomerCreate,
    CustomerUpdate,
    FollowUpCreate,
    FollowUpUpdate,
)
from reven.crm.repository import CrmRepository
from reven.crm.service import CrmService
from reven.scheduling import SHANGHAI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def service(db_session: AsyncSession) -> CrmService:
    return CrmService(db_session)


@pytest.fixture
def commits(db_session: AsyncSession) -> Iterator[list[None]]:
    observed: list[None] = []

    def record_commit(_session: object) -> None:
        observed.append(None)

    event.listen(db_session.sync_session, "after_commit", record_commit)
    yield observed
    event.remove(db_session.sync_session, "after_commit", record_commit)


@pytest.fixture
def today() -> date:
    return datetime.now(SHANGHAI).date()


@pytest.fixture
def history_input(today: date) -> FollowUpCreate:
    return FollowUpCreate(kind="会议", occurred_on=today, summary="需求访谈")


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["update", "delete", "create_contact", "create_follow_up"])
async def test_missing_customer_is_rejected_without_commit(
    service: CrmService, db_session: AsyncSession, commits: list[None], history_input: FollowUpCreate, operation: str
) -> None:
    customer_id = uuid4()
    with pytest.raises(CustomerNotFoundError) as error:
        if operation == "update":
            await service.update_customer(customer_id, CustomerUpdate(name="改名"))
        elif operation == "delete":
            await service.delete_customer(customer_id)
        elif operation == "create_contact":
            await service.create_contact(customer_id, ContactCreate(name="王经理", is_primary=True))
        else:
            await service.create_follow_up(customer_id, history_input)

    assert error.value.args == (customer_id,)
    assert commits == []
    assert (
        await CrmRepository(db_session).list_customers(
            status=None, due=None, query=None, today=history_input.occurred_on
        )
        == []
    )


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["update_contact", "delete_contact", "update_follow_up", "delete_follow_up"])
@pytest.mark.parametrize("scope", ["missing", "another_customer"])
async def test_nested_mutations_enforce_scope_before_changes(
    service: CrmService,
    db_session: AsyncSession,
    commits: list[None],
    history_input: FollowUpCreate,
    operation: str,
    scope: str,
) -> None:
    customer = await service.create_customer(CustomerCreate(name="目标客户"))
    other = await service.create_customer(CustomerCreate(name="另一客户"))
    _, contact = await service.create_contact(other.id, ContactCreate(name="王经理", is_primary=True))
    _, history = await service.create_follow_up(other.id, history_input)
    resource_id = uuid4() if scope == "missing" else contact.id if operation.endswith("contact") else history.id
    commits.clear()
    expected_error = ContactNotFoundError if operation.endswith("contact") else FollowUpNotFoundError

    with pytest.raises(expected_error) as error:
        if operation == "update_contact":
            await service.update_contact(customer.id, resource_id, ContactUpdate(name="越权改名", is_primary=True))
        elif operation == "delete_contact":
            await service.delete_contact(customer.id, resource_id)
        elif operation == "update_follow_up":
            await service.update_follow_up(customer.id, resource_id, FollowUpUpdate(summary="越权修改"))
        else:
            await service.delete_follow_up(customer.id, resource_id)

    assert error.value.args == (resource_id,)
    assert commits == []
    await db_session.refresh(contact)
    await db_session.refresh(history)
    assert contact.name == "王经理" and contact.is_primary
    assert history.summary == "需求访谈"


@pytest.mark.anyio
async def test_customer_partial_updates_preserve_explicit_clear(
    service: CrmService, db_session: AsyncSession, commits: list[None]
) -> None:
    customer = await service.create_customer(CustomerCreate(name=" 示例科技 ", source=" 介绍 ", notes="备注"))
    assert customer.name == "示例科技" and customer.source == "介绍" and customer.notes == "备注"
    plan = await CrmRepository(db_session).get_customer_plan(customer.id)
    assert plan is not None and plan.next_action is None and plan.next_due_on is None

    await service.update_customer(customer.id, CustomerUpdate(notes=None))
    assert customer.notes is None and customer.source == "介绍"
    await service.update_customer(customer.id, CustomerUpdate(source=" ", name="新名称"))
    assert customer.source is None and customer.name == "新名称"
    await service.update_customer(customer.id, CustomerUpdate(status="跟进中"))
    assert customer.status == "跟进中"
    assert commits != []


@pytest.mark.anyio
async def test_follow_up_plan_update_merges_and_moves_derived_plan(
    service: CrmService, db_session: AsyncSession, commits: list[None], today: date
) -> None:
    customer = await service.create_customer(CustomerCreate(name="示例科技"))
    _, history = await service.create_follow_up(
        customer.id,
        FollowUpCreate(kind="电话", occurred_on=today, summary="回访", next_action="历史约定", next_due_on=today),
    )

    async def derived_plan() -> tuple[str | None, date | None]:
        plan = await CrmRepository(db_session).get_customer_plan(customer.id)
        assert plan is not None
        return plan.next_action, plan.next_due_on

    await service.update_follow_up(customer.id, history.id, FollowUpUpdate(next_due_on=today + timedelta(days=1)))
    assert history.next_action == "历史约定" and history.next_due_on == today + timedelta(days=1)
    # 派生计划随最新跟进即时变化，无任何客户表写入
    assert await derived_plan() == ("历史约定", today + timedelta(days=1))
    commits.clear()

    with pytest.raises(InvalidActionPairError):
        await service.update_follow_up(customer.id, history.id, FollowUpUpdate(next_action=None))
    assert commits == []
    await db_session.refresh(history)
    assert history.next_action == "历史约定" and history.next_due_on == today + timedelta(days=1)

    await service.update_follow_up(customer.id, history.id, FollowUpUpdate(next_action="", next_due_on=None))
    assert history.next_action is None and history.next_due_on is None
    assert await derived_plan() == (None, None)


@pytest.mark.anyio
async def test_follow_up_create_commits_once_and_failed_contact_leaves_no_partial_write(
    service: CrmService, db_session: AsyncSession, commits: list[None], today: date
) -> None:
    customer = await service.create_customer(CustomerCreate(name="示例科技"))
    other = await service.create_customer(CustomerCreate(name="另一客户"))
    _, other_contact = await service.create_contact(other.id, ContactCreate(name="其他联系人"))
    payload = FollowUpCreate(
        kind="会议",
        occurred_on=today,
        summary="访谈",
        next_action="发送方案",
        next_due_on=today,
    )
    commits.clear()
    invalid = payload.model_copy(update={"contact_id": other_contact.id})
    with pytest.raises(ContactNotFoundError):
        await service.create_follow_up(customer.id, invalid)
    assert commits == []
    assert await CrmRepository(db_session).list_follow_ups(customer.id) == []
    plan = await CrmRepository(db_session).get_customer_plan(customer.id)
    assert plan is not None and plan.next_action is None and plan.next_due_on is None

    commits.clear()
    result_customer, history = await service.create_follow_up(customer.id, payload)
    assert len(commits) == 1
    assert result_customer.id == customer.id
    plan = await CrmRepository(db_session).get_customer_plan(customer.id)
    assert plan is not None and plan.next_action == "发送方案" and plan.next_due_on == today

    await service.update_follow_up(customer.id, history.id, FollowUpUpdate(next_action="历史补充"))
    await service.delete_follow_up(customer.id, history.id)
    plan = await CrmRepository(db_session).get_customer_plan(customer.id)
    assert plan is not None and plan.next_action is None and plan.next_due_on is None


@pytest.mark.anyio
async def test_primary_switch_and_contact_deletion_preserve_history_snapshot(
    service: CrmService, db_session: AsyncSession, commits: list[None], today: date
) -> None:
    customer = await service.create_customer(CustomerCreate(name="示例科技"))
    _, first = await service.create_contact(customer.id, ContactCreate(name="王经理", is_primary=True))
    _, second = await service.create_contact(customer.id, ContactCreate(name="李助理", is_primary=True))
    await db_session.refresh(first)
    assert not first.is_primary and second.is_primary
    commits.clear()

    await service.update_contact(customer.id, first.id, ContactUpdate(is_primary=True))
    assert len(commits) == 1
    await db_session.refresh(second)
    assert first.is_primary and not second.is_primary
    _, history = await service.create_follow_up(
        customer.id, FollowUpCreate(contact_id=first.id, kind="会议", occurred_on=today, summary="访谈")
    )
    await service.update_contact(customer.id, first.id, ContactUpdate(name="王先生"))
    deleted = await service.delete_contact(customer.id, first.id)
    assert deleted.name == "王先生"
    await db_session.refresh(history)
    assert history.contact_id is None and history.contact_name_snapshot == "王经理"
    assert await CrmRepository(db_session).get_contact(customer.id, first.id) is None


@pytest.mark.anyio
async def test_follow_up_contact_scope_failure_preserves_history(
    service: CrmService, db_session: AsyncSession, commits: list[None], history_input: FollowUpCreate
) -> None:
    customer = await service.create_customer(CustomerCreate(name="示例科技"))
    other = await service.create_customer(CustomerCreate(name="另一客户"))
    _, own_contact = await service.create_contact(customer.id, ContactCreate(name="王经理"))
    _, other_contact = await service.create_contact(other.id, ContactCreate(name="李助理"))
    _, history = await service.create_follow_up(
        customer.id, history_input.model_copy(update={"contact_id": own_contact.id})
    )
    commits.clear()

    with pytest.raises(ContactNotFoundError):
        await service.update_follow_up(
            customer.id, history.id, FollowUpUpdate(contact_id=other_contact.id, summary="不应写入")
        )
    assert commits == []
    await db_session.refresh(history)
    assert history.summary == "需求访谈" and history.contact_id == own_contact.id
    assert history.contact_name_snapshot == "王经理"
