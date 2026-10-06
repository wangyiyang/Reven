"""Fixed talents mutation failures, independent of transport adapters."""


class InvalidRatePairError(ValueError):
    pass


class InvalidDateRangeError(ValueError):
    pass


class InvalidProfileImportError(ValueError):
    """talent_import_profile 载荷校验失败（消息已含条目序号与原因）。"""


class DuplicateTalentNameError(LookupError):
    """talent_import_profile 按姓名精确匹配到多个同名人才，无法确定更新目标。"""
