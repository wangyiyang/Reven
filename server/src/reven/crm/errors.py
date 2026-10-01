"""Fixed CRM mutation failures, independent of transport adapters."""


class CustomerNotFoundError(LookupError):
    pass


class ContactNotFoundError(LookupError):
    pass


class FollowUpNotFoundError(LookupError):
    pass


class InvalidActionPairError(ValueError):
    pass
