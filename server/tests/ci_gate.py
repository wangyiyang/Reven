"""CI-only database test precondition."""

from collections.abc import Mapping


def is_test_database_missing_in_ci(environment: Mapping[str, str]) -> bool:
    return bool(environment.get("CI")) and "TEST_DATABASE_URL" not in environment
