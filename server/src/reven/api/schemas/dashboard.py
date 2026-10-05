"""Response schemas for the dashboard aggregate endpoint.

纯只读聚合契约：金额一律为分（cents）；日期为 ISO（YYYY-MM-DD），
"今日"与逾期判断按 Asia/Shanghai 日历日（与 CRM due 过滤口径一致）。
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class DashboardFinanceSummary(BaseModel):
    """待收款（kind=income 且 status=应收）总额/笔数与其中逾期部分（due_on < 今日）。"""

    receivable_cents: int
    receivable_count: int
    overdue_receivable_cents: int
    overdue_receivable_count: int


class DashboardRssRun(BaseModel):
    """最近一次 RSS 抓取运行摘要；无运行记录时整个 latest_run 为 null。"""

    status: str
    failure_count: int
    finished_at: datetime | None


class DashboardRssSummary(BaseModel):
    candidate_count: int
    saved_count: int
    latest_run: DashboardRssRun | None


class DashboardCrmDueItem(BaseModel):
    """待跟进客户清单项（与飞书每日提醒同源排序：最逾期在前）。

    next_due_on 为该客户最新一条跟进记录的派生到期日；
    overdue_days = (今日 - next_due_on).days，到期日 <= 今日时恒 >= 0；
    前端按 overdue_days > 0 判定逾期红显。
    """

    customer_id: UUID
    name: str
    next_action: str | None
    next_due_on: date
    overdue_days: int


class DashboardCrmSummary(BaseModel):
    overdue_count: int
    today_count: int
    due_items: list[DashboardCrmDueItem]


class DashboardProjectItem(BaseModel):
    id: UUID
    name: str
    due_on: date | None
    overdue: bool


class DashboardProjectSummary(BaseModel):
    """进行中项目计数与 Top 5 清单（due_on 升序，NULL 排后）。"""

    active_count: int
    items: list[DashboardProjectItem]


class DashboardIntegrationSummary(BaseModel):
    """固定 5 provider 与 DB 行的差集（行缺失或 secret_configured=false 即 missing）；COS 走环境变量四值齐备性。"""

    missing_providers: list[str]
    cos_configured: bool


class DashboardSummary(BaseModel):
    finance: DashboardFinanceSummary
    rss: DashboardRssSummary
    crm: DashboardCrmSummary
    projects: DashboardProjectSummary
    integrations: DashboardIntegrationSummary
