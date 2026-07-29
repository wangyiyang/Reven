import sys

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
