import os

import pytest
from ci_gate import is_test_database_missing_in_ci


def test_ci_gate_rejects_missing_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    assert is_test_database_missing_in_ci(dict(os.environ)) is True
