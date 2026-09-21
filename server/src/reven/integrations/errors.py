"""Errors shared by configured integration consumers."""


class IntegrationConfigurationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
