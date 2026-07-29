"""持久化准备阶段终态通知，供恢复 runner 统一投递。"""

import hashlib

from reven.articles.models import Article
from reven.domain import JobStatus
from reven.jobs.models import PublicationJob


def enqueue_preparation_terminal(
    job: PublicationJob,
    article: Article,
    status: JobStatus,
    reason: str,
    event: str,
) -> None:
    marker = f"{event}:{article.notion_last_edited_at.isoformat()}:{reason}"
    if job.notification_state.get("_preparation_terminal_marker") == marker:
        return
    revision = _next_revision(job)
    name = f"{event}:r{revision}"
    pending = {
        "fingerprint": _fingerprint(job, name),
        "event": name,
        "stage": "发布准备阻塞" if status == JobStatus.BLOCKED else "发布准备失败",
        "summary": reason[:1000],
        "error_code": hashlib.sha256(reason.encode()).hexdigest(),
        "channel": None,
    }
    existing = job.snapshot_metadata.get("delivery_notification_events", [])
    events = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    job.snapshot_metadata = {
        **job.snapshot_metadata,
        "delivery_finalization": {
            "final_status": status,
            "reason": reason[:1000],
            "notion_pending": False,
            "cleanup_pending": False,
        },
        "delivery_notification_events": [*events, pending],
    }
    job.notification_state = {**job.notification_state, "_preparation_terminal_marker": marker}


def _next_revision(job: PublicationJob) -> int:
    current = job.notification_state.get("_revision", 0)
    revision = (current if isinstance(current, int) else 0) + 1
    job.notification_state = {**job.notification_state, "_revision": revision}
    return revision


def _fingerprint(job: PublicationJob, event: str) -> str:
    return hashlib.sha256(f"{job.id}:{event}::".encode()).hexdigest()
