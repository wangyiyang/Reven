"""独立进程加载 Alembic 元数据，避免应用导入掩盖遗漏的 ORM 模型。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]


def test_migrated_schema_matches_standalone_alembic_metadata() -> None:
    if "TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TEST_DATABASE_URL is not set")
    command = [sys.executable, "-m", "alembic", "-c", str(ROOT / "server/migrations/alembic.ini")]
    for arguments in (("upgrade", "head"), ("check",)):
        result = subprocess.run(
            [*command, *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
