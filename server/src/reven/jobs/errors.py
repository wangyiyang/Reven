"""Publishing error categories used by retry policy and orchestration."""


class PublishError(Exception):
    """Base class for safe, user-facing publishing failures."""


class BlockedPublishError(PublishError):
    """Human input or configuration must be repaired before retrying."""


class TransientPublishError(PublishError):
    """A temporary external failure that may be retried automatically."""


class PermanentPublishError(PublishError):
    """A non-retryable publishing failure."""
