"""Bounded subprocess execution without a shell."""

import asyncio
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class CommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int
    truncated: bool = False


class CommandRunner:
    def __init__(self, *, timeout: float = 300, max_output_bytes: int = 256_000) -> None:
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        secrets: Sequence[str] = (),
    ) -> CommandResult:
        if not argv or any(not isinstance(item, str) or "\0" in item for item in argv):
            raise ValueError("命令参数无效")
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env={**os.environ, **(env or {})},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self.timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise CommandError("命令执行超时") from exc
        output = stdout + stderr
        truncated = len(output) > self.max_output_bytes
        stdout_text = _safe_text(stdout[: self.max_output_bytes], secrets)
        remaining = max(0, self.max_output_bytes - len(stdout[: self.max_output_bytes]))
        stderr_text = _safe_text(stderr[:remaining], secrets)
        result = CommandResult(stdout_text, stderr_text, process.returncode or 0, truncated)
        if process.returncode:
            raise CommandError(f"命令失败({process.returncode}): {stderr_text}")
        return result


def _safe_text(raw: bytes, secrets: Sequence[str]) -> str:
    text = raw.decode("utf-8", errors="replace")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text
