"""Small, explicit retry policy for publishing attempts."""

from reven.jobs.errors import PublishError, TransientPublishError

RETRY_DELAYS = {1: 30, 2: 120}


def retry_delay_seconds(error: PublishError, attempt: int) -> int | None:
    if not isinstance(error, TransientPublishError):
        return None
    return RETRY_DELAYS.get(attempt)
