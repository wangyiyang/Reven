"""Dashboard aggregate endpoint."""

from fastapi import APIRouter

from reven.api.dependencies import SessionDep, SettingsDep
from reven.api.schemas.dashboard import (
    DashboardCrmDueItem,
    DashboardCrmSummary,
    DashboardFinanceSummary,
    DashboardIntegrationSummary,
    DashboardProjectItem,
    DashboardProjectSummary,
    DashboardRssRun,
    DashboardRssSummary,
    DashboardSummary,
)
from reven.dashboard.service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(session: SessionDep, settings: SettingsDep) -> DashboardSummary:
    aggregate = await DashboardService(session, settings).build_summary()
    return DashboardSummary(
        finance=DashboardFinanceSummary(
            receivable_cents=aggregate.finance.receivable_cents,
            receivable_count=aggregate.finance.receivable_count,
            overdue_receivable_cents=aggregate.finance.overdue_receivable_cents,
            overdue_receivable_count=aggregate.finance.overdue_receivable_count,
        ),
        rss=DashboardRssSummary(
            candidate_count=aggregate.rss.candidate_count,
            saved_count=aggregate.rss.saved_count,
            latest_run=None
            if aggregate.rss.latest_run is None
            else DashboardRssRun(
                status=aggregate.rss.latest_run.status,
                failure_count=aggregate.rss.latest_run.failure_count,
                finished_at=aggregate.rss.latest_run.finished_at,
            ),
        ),
        crm=DashboardCrmSummary(
            overdue_count=aggregate.crm.overdue_count,
            today_count=aggregate.crm.today_count,
            due_items=[
                DashboardCrmDueItem(
                    customer_id=item.customer_id,
                    name=item.name,
                    next_action=item.next_action,
                    next_due_on=item.next_due_on,
                    overdue_days=item.overdue_days,
                )
                for item in aggregate.crm.due_items
            ],
        ),
        projects=DashboardProjectSummary(
            active_count=aggregate.projects.active_count,
            items=[
                DashboardProjectItem(
                    id=item.id,
                    name=item.name,
                    due_on=item.due_on,
                    overdue=item.overdue,
                )
                for item in aggregate.projects.items
            ],
        ),
        integrations=DashboardIntegrationSummary(
            missing_providers=aggregate.integrations.missing_providers,
            cos_configured=aggregate.integrations.cos_configured,
        ),
    )
