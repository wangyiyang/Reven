import pytest
from reven.jobs.errors import BlockedPublishError, PermanentPublishError, TransientPublishError
from reven.jobs.retry import retry_delay_seconds


@pytest.mark.parametrize(("attempt", "expected"), [(1, 30), (2, 120), (3, None)])
def test_transient_retry_schedule(attempt: int, expected: int | None) -> None:
    assert retry_delay_seconds(TransientPublishError("timeout"), attempt) == expected


@pytest.mark.parametrize(
    "error",
    [BlockedPublishError("缺少封面"), PermanentPublishError("鉴权失败")],
)
def test_non_transient_error_never_retries(error: Exception) -> None:
    assert retry_delay_seconds(error, 1) is None
