import asyncio
import base64
import os
import sys
import time
from pathlib import Path

import pytest
from reven.publishing.commands import CommandError, CommandRunner


@pytest.mark.anyio
async def test_command_runner_uses_argv_and_bounds_redacted_output() -> None:
    secret = "super-secret"
    result = await CommandRunner(max_output_bytes=8).run(
        [sys.executable, "-c", "print('abcdefghijklmnop')"],
        secrets=(secret,),
    )
    assert result.stdout == "abcdefgh"
    assert result.truncated
    assert secret not in repr(result)


@pytest.mark.anyio
async def test_command_runner_times_out_and_reaps_process() -> None:
    with pytest.raises(CommandError, match="超时"):
        await CommandRunner(timeout=0.01).run([sys.executable, "-c", "import time; time.sleep(10)"])


@pytest.mark.anyio
async def test_command_runner_redacts_git_auth_derived_from_token() -> None:
    token = "top-secret"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    header = f"Authorization: Basic {encoded}"
    with pytest.raises(CommandError) as caught:
        await CommandRunner().run(
            [sys.executable, "-c", f"import sys; sys.stderr.write({header!r}); sys.exit(1)"],
            secrets=(token,),
        )
    assert token not in str(caught.value)
    assert encoded not in str(caught.value)


@pytest.mark.anyio
async def test_timeout_kills_spawned_child_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid));"
        "time.sleep(30)"
    )
    with pytest.raises(CommandError, match="超时"):
        await CommandRunner(timeout=0.1).run([sys.executable, "-c", script])
    child_pid = int(pid_file.read_text())
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    else:
        pytest.fail("spawned child survived command timeout")


@pytest.mark.anyio
async def test_cancellation_kills_spawned_child_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "cancel-child.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid));"
        "time.sleep(30)"
    )
    task = asyncio.create_task(CommandRunner().run([sys.executable, "-c", script]))
    for _ in range(100):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    child_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


@pytest.mark.anyio
async def test_command_environment_excludes_service_and_cloud_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = {
        "DATABASE_URL": "postgres-secret",
        "TEST_DATABASE_URL": "test-secret",
        "REVEN_MASTER_KEY": "master-secret",
        "GITHUB_TOKEN": "github-secret",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
    }
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)
    result = await CommandRunner().run([sys.executable, "-c", "import json,os; print(json.dumps(dict(os.environ)))"])
    assert all(value not in result.stdout for value in secrets.values())
    assert "HOME" in result.stdout
    assert "TMPDIR" in result.stdout


@pytest.mark.anyio
async def test_large_dual_pipe_output_is_retained_with_fixed_bounds() -> None:
    script = "import os;chunk=b'x'*65536;[(os.write(1,chunk),os.write(2,chunk)) for _ in range(64)]"
    result = await CommandRunner(max_output_bytes=1024, timeout=5).run([sys.executable, "-c", script])
    assert len(result.stdout.encode()) <= 1024
    assert len(result.stderr.encode()) <= 1024
    assert result.truncated
