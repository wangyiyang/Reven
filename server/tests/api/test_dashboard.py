"""GET /api/dashboard/summary 聚合端点测试。

覆盖：空库、各模块有数据、财务逾期计算（due_on < 今日未收）、
missing providers 差集（含 secret_configured=false）、cos_configured、
无 RSS run 时 latest_run=null。
"""

import asyncio
import hashlib
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from pydantic import SecretStr
from reven.crm.models import Customer, FollowUp
from reven.finance.models import FinanceEntry
from reven.integrations.models import Integration
from reven.integrations.providers import SUPPORTED_INTEGRATION_PROVIDERS
from reven.projects.models import Project
from reven.rss.models import RssDiscoveryRun, RssItem
from reven.scheduling import SHANGHAI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Factory = async_sessionmaker[AsyncSession]


def today_shanghai() -> date:
    return datetime.now(SHANGHAI).date()


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def finance_entry(**overrides: object) -> FinanceEntry:
    values: dict[str, object] = {
        "kind": "income",
        "name": "款项",
        "amount_cents": 10000,
        "category": None,
        "occurred_on": date(2026, 1, 1),
        "due_on": None,
        "recurrence": None,
        "source": None,
        "status": "应收",
        "notes": None,
    }
    values.update(overrides)
    return FinanceEntry(**values)


def rss_item(run_id, status: str, key: str) -> RssItem:  # type: ignore[no-untyped-def]
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    return RssItem(
        first_seen_run_id=run_id,
        source_name="Example",
        url_key=digest(f"url-{key}"),
        guid_key=digest(f"guid-{key}"),
        title_key=digest(f"title-{key}"),
        title=f"标题 {key}",
        title_zh=f"标题 {key}",
        published_at=datetime(2026, 9, 1, tzinfo=UTC),
        status=status,
    )


def test_dashboard_summary_empty_database(workbench: tuple[TestClient, Factory]) -> None:
    client, _factory = workbench

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    assert response.json() == {
        "finance": {
            "receivable_cents": 0,
            "receivable_count": 0,
            "overdue_receivable_cents": 0,
            "overdue_receivable_count": 0,
        },
        "rss": {"candidate_count": 0, "saved_count": 0, "latest_run": None},
        "crm": {"overdue_count": 0, "today_count": 0, "due_items": []},
        "projects": {"active_count": 0, "items": []},
        "integrations": {
            "missing_providers": list(SUPPORTED_INTEGRATION_PROVIDERS),
            "cos_configured": False,
        },
    }


def test_dashboard_summary_aggregates_all_modules(workbench: tuple[TestClient, Factory]) -> None:
    client, factory = workbench
    today = today_shanghai()

    async def seed() -> None:
        async with factory.begin() as session:
            session.add_all(
                [
                    finance_entry(name="逾期尾款", amount_cents=50000, due_on=today - timedelta(days=3)),
                    finance_entry(name="今日到期款", amount_cents=30000, due_on=today),
                    finance_entry(name="未来款", amount_cents=20000, due_on=today + timedelta(days=10)),
                    finance_entry(name="已收尾款", amount_cents=99000, status="已收", due_on=today - timedelta(days=5)),
                    finance_entry(
                        name="待付采购",
                        kind="expense",
                        status="应付",
                        amount_cents=70000,
                        due_on=today - timedelta(days=2),
                    ),
                ]
            )
            run_ = RssDiscoveryRun(
                run_date=today,
                status="partial",
                failure_count=2,
                finished_at=datetime(2026, 10, 5, 6, 0, tzinfo=UTC),
            )
            session.add(run_)
            await session.flush()
            session.add_all(
                [
                    rss_item(run_.id, "candidate", "c1"),
                    rss_item(run_.id, "candidate", "c2"),
                    rss_item(run_.id, "saved", "s1"),
                    rss_item(run_.id, "ignored", "i1"),
                ]
            )
            customers = [
                Customer(name="逾期客户"),
                Customer(name="今日客户"),
                Customer(name="未来客户"),
                Customer(name="无计划客户"),
            ]
            session.add_all(customers)
            await session.flush()
            overdue_customer, today_customer, future_customer, _no_plan = customers
            # 客户计划派生自最新跟进记录：种子数据按「建客户 → 建跟进」两步写入
            session.add_all(
                [
                    FollowUp(
                        customer_id=overdue_customer.id,
                        kind="电话",
                        occurred_on=today,
                        summary="回访",
                        next_action="电话回访",
                        next_due_on=today - timedelta(days=4),
                    ),
                    FollowUp(
                        customer_id=today_customer.id,
                        kind="电话",
                        occurred_on=today,
                        summary="回访",
                        next_action="发报价",
                        next_due_on=today,
                    ),
                    FollowUp(
                        customer_id=future_customer.id,
                        kind="电话",
                        occurred_on=today,
                        summary="回访",
                        next_action="约演示",
                        next_due_on=today + timedelta(days=3),
                    ),
                ]
            )
            session.add_all(
                [
                    Project(name="进行中甲", status="进行中", due_on=today + timedelta(days=5)),
                    Project(name="进行中乙", status="进行中", due_on=today - timedelta(days=1)),
                    Project(name="无到期项目", status="进行中", due_on=None),
                    Project(name="已交付项目", status="已交付", due_on=today - timedelta(days=1)),
                ]
            )
            session.add(Integration(provider="feishu_bot", public_config={}, encrypted_secret="cipher"))

    run(seed())

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["finance"] == {
        "receivable_cents": 100000,
        "receivable_count": 3,
        "overdue_receivable_cents": 50000,
        "overdue_receivable_count": 1,
    }
    assert body["rss"]["candidate_count"] == 2
    assert body["rss"]["saved_count"] == 1
    assert body["rss"]["latest_run"] == {
        "status": "partial",
        "failure_count": 2,
        "finished_at": "2026-10-05T06:00:00Z",
    }
    assert body["crm"]["overdue_count"] == 1
    assert body["crm"]["today_count"] == 1
    assert [(item["name"], item["overdue_days"]) for item in body["crm"]["due_items"]] == [
        ("逾期客户", 4),
        ("今日客户", 0),
    ]
    overdue_item = body["crm"]["due_items"][0]
    assert overdue_item["next_action"] == "电话回访"
    assert overdue_item["next_due_on"] == str(today - timedelta(days=4))
    assert overdue_item["customer_id"]
    assert body["projects"]["active_count"] == 3
    assert [(item["name"], item["overdue"]) for item in body["projects"]["items"]] == [
        ("进行中乙", True),
        ("进行中甲", False),
        ("无到期项目", False),
    ]
    expected_missing = [provider for provider in SUPPORTED_INTEGRATION_PROVIDERS if provider != "feishu_bot"]
    assert body["integrations"]["missing_providers"] == expected_missing
    assert body["integrations"]["cos_configured"] is False


def test_dashboard_finance_overdue_counts_only_unsettled_receivables(workbench: tuple[TestClient, Factory]) -> None:
    """逾期 = status=应收 且 due_on < 今日；今日到期、已收、应付均不计入逾期。"""
    client, factory = workbench
    today = today_shanghai()

    async def seed() -> None:
        async with factory.begin() as session:
            session.add_all(
                [
                    finance_entry(name="昨日到期应收", amount_cents=11111, due_on=today - timedelta(days=1)),
                    finance_entry(name="今日到期应收", amount_cents=22222, due_on=today),
                    finance_entry(name="无到期应收", amount_cents=33333, due_on=None),
                    finance_entry(
                        name="昨日到期已收", amount_cents=44444, status="已收", due_on=today - timedelta(days=1)
                    ),
                    finance_entry(
                        name="昨日到期应付",
                        kind="expense",
                        status="应付",
                        amount_cents=55555,
                        due_on=today - timedelta(days=1),
                    ),
                    finance_entry(
                        name="昨日到期已记录", status="已记录", amount_cents=66666, due_on=today - timedelta(days=1)
                    ),
                ]
            )

    run(seed())

    body = client.get("/api/dashboard/summary").json()
    assert body["finance"] == {
        "receivable_cents": 11111 + 22222 + 33333,
        "receivable_count": 3,
        "overdue_receivable_cents": 11111,
        "overdue_receivable_count": 1,
    }


def test_dashboard_crm_due_items_top5_most_overdue_first(workbench: tuple[TestClient, Factory]) -> None:
    """Top 5 复用 list_due_follow_ups：派生 next_due_on <= 今日，最逾期在前。"""
    client, factory = workbench
    today = today_shanghai()

    async def seed() -> None:
        async with factory.begin() as session:
            customers = [Customer(name=f"客户{index}") for index in range(7)]
            session.add_all(customers)
            await session.flush()
            session.add_all(
                FollowUp(
                    customer_id=customer.id,
                    kind="电话",
                    occurred_on=today,
                    summary="回访",
                    next_action="跟进",
                    next_due_on=today - timedelta(days=index),
                )
                for index, customer in enumerate(customers)
            )

    run(seed())

    body = client.get("/api/dashboard/summary").json()
    assert body["crm"]["overdue_count"] == 6
    assert body["crm"]["today_count"] == 1
    assert [item["name"] for item in body["crm"]["due_items"]] == [
        "客户6",
        "客户5",
        "客户4",
        "客户3",
        "客户2",
    ]
    assert [item["overdue_days"] for item in body["crm"]["due_items"]] == [6, 5, 4, 3, 2]


def test_dashboard_missing_providers_diff_includes_unconfigured_secret(
    workbench: tuple[TestClient, Factory],
) -> None:
    """DB 行存在但 secret_configured=false（无密文）也算 missing；未知行不影响差集。"""
    client, factory = workbench

    async def seed() -> None:
        async with factory.begin() as session:
            session.add_all(
                [
                    Integration(provider="feishu_bot", public_config={}, encrypted_secret="cipher"),
                    Integration(provider="embedding", public_config={}, encrypted_secret="cipher"),
                    Integration(provider="translate_baidu", public_config={}, encrypted_secret=None),
                    Integration(provider="retired_legacy", public_config={}, encrypted_secret="cipher"),
                ]
            )

    run(seed())

    body = client.get("/api/dashboard/summary").json()
    assert body["integrations"]["missing_providers"] == ["translate_baidu", "translate_aliyun", "agent-llm"]


def test_dashboard_cos_configured_reflects_settings(workbench: tuple[TestClient, Factory]) -> None:
    """cos_* 四个环境值齐备才算 configured；缺任一即 false。"""
    client, _factory = workbench
    settings = client.app.state.settings  # type: ignore[attr-defined]

    assert client.get("/api/dashboard/summary").json()["integrations"]["cos_configured"] is False

    settings.cos_bucket = "assets-1234567"
    settings.cos_region = "ap-shanghai"
    settings.cos_secret_key = SecretStr("secret-key")
    assert client.get("/api/dashboard/summary").json()["integrations"]["cos_configured"] is False

    settings.cos_secret_id = SecretStr("secret-id")
    assert client.get("/api/dashboard/summary").json()["integrations"]["cos_configured"] is True


def test_dashboard_rss_counts_with_run_present(workbench: tuple[TestClient, Factory]) -> None:
    """有运行记录时 latest_run 返回最近一次（按 run_date 降序）。"""
    client, factory = workbench
    today = today_shanghai()

    async def seed() -> None:
        async with factory.begin() as session:
            older = RssDiscoveryRun(run_date=today - timedelta(days=1), status="completed", failure_count=1)
            session.add(older)
            await session.flush()
            session.add(rss_item(older.id, "candidate", "only"))
            session.add(RssDiscoveryRun(run_date=today, status="partial", failure_count=3))

    run(seed())

    body = client.get("/api/dashboard/summary").json()
    assert body["rss"]["candidate_count"] == 1
    assert body["rss"]["latest_run"] == {"status": "partial", "failure_count": 3, "finished_at": None}


def test_dashboard_rss_latest_run_unfinished(workbench: tuple[TestClient, Factory]) -> None:
    """running 中的 run：finished_at=null 原样返回。"""
    client, factory = workbench
    today = today_shanghai()

    async def seed() -> None:
        async with factory.begin() as session:
            session.add(RssDiscoveryRun(run_date=today, status="running", finished_at=None))

    run(seed())

    body = client.get("/api/dashboard/summary").json()
    assert body["rss"]["latest_run"] == {"status": "running", "failure_count": 0, "finished_at": None}


def test_dashboard_projects_top5_due_on_ascending_nulls_last(workbench: tuple[TestClient, Factory]) -> None:
    client, factory = workbench
    today = today_shanghai()

    async def seed() -> None:
        async with factory.begin() as session:
            for index in range(7):
                session.add(
                    Project(
                        name=f"项目{index}",
                        status="进行中",
                        due_on=today + timedelta(days=index) if index < 6 else None,
                    )
                )

    run(seed())

    body = client.get("/api/dashboard/summary").json()
    assert body["projects"]["active_count"] == 7
    assert [item["name"] for item in body["projects"]["items"]] == ["项目0", "项目1", "项目2", "项目3", "项目4"]
    overdue_flag = body["projects"]["items"][0]["overdue"]
    assert overdue_flag is False
