"""Dashboard 聚合服务：编排各模块只读查询，组装工作台首页摘要。

只做"读 + SQL 计数"，不新增表、不改任何现有接口；CRM 待跟进清单复用
`CrmRepository.list_due_follow_ups`（与飞书每日提醒同源），不新写查询逻辑。
"今日"统一按 Asia/Shanghai 日历日（对齐 CRM repository 的 due 过滤口径）。
返回纯数据 dataclass，响应模型由 API 层拥有（对齐"响应类由 API 拥有"约定）。
"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.config import Settings
from reven.crm.models import Customer
from reven.crm.repository import CrmRepository
from reven.finance.models import FinanceEntry
from reven.integrations.models import Integration
from reven.integrations.providers import SUPPORTED_INTEGRATION_PROVIDERS
from reven.projects.models import Project
from reven.rss.models import RssDiscoveryRun, RssItem
from reven.scheduling import SHANGHAI

DUE_ITEMS_LIMIT = 5
ACTIVE_PROJECTS_LIMIT = 5
ACTIVE_PROJECT_STATUS = "进行中"


@dataclass(frozen=True)
class FinanceAggregate:
    receivable_cents: int
    receivable_count: int
    overdue_receivable_cents: int
    overdue_receivable_count: int


@dataclass(frozen=True)
class RssRunAggregate:
    status: str
    failure_count: int
    finished_at: datetime | None


@dataclass(frozen=True)
class RssAggregate:
    candidate_count: int
    saved_count: int
    latest_run: RssRunAggregate | None


@dataclass(frozen=True)
class CrmDueItemAggregate:
    customer_id: UUID
    name: str
    next_action: str | None
    next_follow_up_on: date
    overdue_days: int


@dataclass(frozen=True)
class CrmAggregate:
    overdue_count: int
    today_count: int
    due_items: list[CrmDueItemAggregate]


@dataclass(frozen=True)
class ProjectItemAggregate:
    id: UUID
    name: str
    due_on: date | None
    overdue: bool


@dataclass(frozen=True)
class ProjectAggregate:
    active_count: int
    items: list[ProjectItemAggregate]


@dataclass(frozen=True)
class IntegrationAggregate:
    missing_providers: list[str]
    cos_configured: bool


@dataclass(frozen=True)
class DashboardAggregate:
    finance: FinanceAggregate
    rss: RssAggregate
    crm: CrmAggregate
    projects: ProjectAggregate
    integrations: IntegrationAggregate


class DashboardService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def build_summary(self, *, today: date | None = None) -> DashboardAggregate:
        """组装四模块聚合数据 + 集成缺失清单；today 可注入以便测试锚定日期。"""
        current = today or datetime.now(SHANGHAI).date()
        return DashboardAggregate(
            finance=await self._finance_summary(current),
            rss=await self._rss_summary(),
            crm=await self._crm_summary(current),
            projects=await self._project_summary(current),
            integrations=await self._integration_summary(),
        )

    async def _finance_summary(self, today: date) -> FinanceAggregate:
        receivable = and_(FinanceEntry.kind == "income", FinanceEntry.status == "应收")
        overdue = and_(receivable, FinanceEntry.due_on < today)
        row = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(case((receivable, FinanceEntry.amount_cents), else_=0)), 0),
                    func.coalesce(func.sum(case((receivable, 1), else_=0)), 0),
                    func.coalesce(func.sum(case((overdue, FinanceEntry.amount_cents), else_=0)), 0),
                    func.coalesce(func.sum(case((overdue, 1), else_=0)), 0),
                )
            )
        ).one()
        return FinanceAggregate(
            receivable_cents=int(row[0]),
            receivable_count=int(row[1]),
            overdue_receivable_cents=int(row[2]),
            overdue_receivable_count=int(row[3]),
        )

    async def _rss_summary(self) -> RssAggregate:
        candidate_count = await self._count_items("candidate")
        saved_count = await self._count_items("saved")
        latest = await self.session.scalar(select(RssDiscoveryRun).order_by(RssDiscoveryRun.run_date.desc()).limit(1))
        return RssAggregate(
            candidate_count=candidate_count,
            saved_count=saved_count,
            latest_run=None
            if latest is None
            else RssRunAggregate(
                status=latest.status,
                failure_count=latest.failure_count,
                finished_at=latest.finished_at,
            ),
        )

    async def _count_items(self, item_status: str) -> int:
        statement = select(func.count()).select_from(RssItem).where(RssItem.status == item_status)
        count = await self.session.scalar(statement)
        return count or 0

    async def _crm_summary(self, today: date) -> CrmAggregate:
        overdue_count = await self._count_follow_ups(today, overdue=True)
        today_count = await self._count_follow_ups(today, overdue=False)
        customers = await CrmRepository(self.session).list_due_follow_ups(today=today, limit=DUE_ITEMS_LIMIT)
        return CrmAggregate(
            overdue_count=overdue_count,
            today_count=today_count,
            due_items=[
                CrmDueItemAggregate(
                    customer_id=customer.id,
                    name=customer.name,
                    next_action=customer.next_action,
                    next_follow_up_on=due_on,
                    overdue_days=(today - due_on).days,
                )
                for customer in customers
                if (due_on := customer.next_follow_up_on) is not None
            ],
        )

    async def _count_follow_ups(self, today: date, *, overdue: bool) -> int:
        condition = Customer.next_follow_up_on < today if overdue else Customer.next_follow_up_on == today
        count = await self.session.scalar(select(func.count()).select_from(Customer).where(condition))
        return count or 0

    async def _project_summary(self, today: date) -> ProjectAggregate:
        active_count = await self.session.scalar(
            select(func.count()).select_from(Project).where(Project.status == ACTIVE_PROJECT_STATUS)
        )
        result = await self.session.scalars(
            select(Project)
            .where(Project.status == ACTIVE_PROJECT_STATUS)
            .order_by(Project.due_on.is_(None), Project.due_on, func.lower(Project.name))
            .limit(ACTIVE_PROJECTS_LIMIT)
        )
        return ProjectAggregate(
            active_count=active_count or 0,
            items=[
                ProjectItemAggregate(
                    id=project.id,
                    name=project.name,
                    due_on=project.due_on,
                    overdue=project.due_on is not None and project.due_on < today,
                )
                for project in result
            ],
        )

    async def _integration_summary(self) -> IntegrationAggregate:
        result = await self.session.scalars(select(Integration))
        secret_configured = {row.provider: row.encrypted_secret is not None for row in result}
        missing = [
            provider for provider in SUPPORTED_INTEGRATION_PROVIDERS if not secret_configured.get(provider, False)
        ]
        return IntegrationAggregate(missing_providers=missing, cos_configured=self._cos_configured())

    def _cos_configured(self) -> bool:
        return all(
            value is not None
            for value in (
                self.settings.cos_bucket,
                self.settings.cos_region,
                self.settings.cos_secret_id,
                self.settings.cos_secret_key,
            )
        )
