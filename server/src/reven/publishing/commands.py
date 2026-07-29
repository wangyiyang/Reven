"""Bounded subprocess execution without a shell."""

import asyncio
import base64
import os
import signal
import tempfile
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
        isolated = Path(tempfile.mkdtemp(prefix="reven-command-"))
        (isolated / "home").mkdir(mode=0o700)
        (isolated / "tmp").mkdir(mode=0o700)
        self.base_env = _base_environment(isolated)

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
            env={**self.base_env, **(env or {})},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("子进程管道初始化失败")
        stdout_task = asyncio.create_task(_read_bounded(process.stdout, self.max_output_bytes))
        stderr_task = asyncio.create_task(_read_bounded(process.stderr, self.max_output_bytes))
        wait_task = asyncio.create_task(process.wait())
        tasks = (wait_task, stdout_task, stderr_task)
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), self.timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            _kill_process_group(process)
            await process.wait()
            await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise CommandError("命令执行超时") from exc
        stdout, stdout_truncated = stdout_task.result()
        stderr, stderr_truncated = stderr_task.result()
        truncated = stdout_truncated or stderr_truncated
        stdout_text = _safe_text(stdout, secrets)
        stderr_text = _safe_text(stderr, secrets)
        result = CommandResult(stdout_text, stderr_text, process.returncode or 0, truncated)
        if process.returncode:
            _kill_process_group(process)
            raise CommandError(f"命令失败({process.returncode}): {stderr_text}")
        return result


def _safe_text(raw: bytes, secrets: Sequence[str]) -> str:
    text = raw.decode("utf-8", errors="replace")
    for secret in _secret_variants(secrets):
        text = text.replace(secret, "***")
    return text


def _secret_variants(secrets: Sequence[str]) -> tuple[str, ...]:
    variants: set[str] = set()
    for secret in secrets:
        if not secret:
            continue
        encoded = base64.b64encode(f"x-access-token:{secret}".encode()).decode()
        variants.update({secret, encoded, f"Basic {encoded}", f"Authorization: Basic {encoded}"})
    return tuple(sorted(variants, key=len, reverse=True))


def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.getpgid(process.pid) != process.pid:
            return
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


async def _read_bounded(
    stream: asyncio.StreamReader,
    limit: int,
) -> tuple[bytes, bool]:
    retained = bytearray()
    truncated = False
    while chunk := await stream.read(64 * 1024):
        remaining = max(0, limit - len(retained))
        retained.extend(chunk[:remaining])
        truncated = truncated or len(chunk) > remaining
    return bytes(retained), truncated


def _base_environment(isolated: Path) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "SSL_CERT_FILE", "SSL_CERT_DIR")
    environment = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    environment.update(
        {
            "HOME": str(isolated / "home"),
            "TMPDIR": str(isolated / "tmp"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment
