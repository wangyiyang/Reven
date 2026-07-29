import asyncio
import json
import os
import resource
import sys
from pathlib import Path
from typing import Any

from reven.publishing.sandbox import bubblewrap_command


class RendererError(RuntimeError):
    """A safely classified renderer process failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class WechatRenderer:
    def __init__(
        self,
        executable: str = "node",
        cli_path: Path | str = Path("renderer/dist/cli.mjs"),
        timeout_seconds: float = 30,
        max_output_bytes: int = 4 * 1024 * 1024,
        sandbox_executable: Path | None = None,
    ) -> None:
        self._executable = executable
        self._cli_path = str(cli_path)
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes
        self._sandbox_executable = sandbox_executable

    async def render(self, markdown: str) -> str:
        argv = [self._executable, self._cli_path]
        if self._sandbox_executable is not None:
            argv = bubblewrap_command(
                self._sandbox_executable,
                argv,
                readable_paths=(Path(self._cli_path).resolve().parent,),
            )
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_renderer_environment(),
            start_new_session=True,
            preexec_fn=_limit_resources if sys.platform == "linux" else None,
        )
        try:
            stdout = await asyncio.wait_for(
                self._exchange(process, markdown),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            await self._terminate(process)
            raise RendererError("timeout") from error
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        if process.returncode != 0:
            raise RendererError("process_failed")
        return self._parse_response(stdout)

    async def _exchange(self, process: asyncio.subprocess.Process, markdown: str) -> bytes:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            await self._terminate(process)
            raise RendererError("process_failed")
        process.stdin.write(json.dumps({"markdown": markdown}).encode())
        await process.stdin.drain()
        process.stdin.close()
        stdout_task = asyncio.create_task(self._read_limited(process.stdout))
        stderr_task = asyncio.create_task(self._drain(process.stderr))
        stdout, _stderr, _returncode = await asyncio.gather(stdout_task, stderr_task, process.wait())
        return stdout

    async def _drain(self, stream: asyncio.StreamReader) -> None:
        while await stream.read(64 * 1024):
            pass

    async def _read_limited(self, stream: asyncio.StreamReader) -> bytes:
        chunks: list[bytes] = []
        size = 0
        oversized = False
        while chunk := await stream.read(64 * 1024):
            size += len(chunk)
            if size <= self._max_output_bytes:
                chunks.append(chunk)
            else:
                oversized = True
        if oversized:
            raise RendererError("output_too_large")
        return b"".join(chunks)

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            os.killpg(process.pid, 9)
        await process.wait()

    def _parse_response(self, stdout: bytes) -> str:
        try:
            response: Any = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RendererError("invalid_response") from error
        if not isinstance(response, dict):
            raise RendererError("invalid_response")
        if response.get("ok") is False:
            raise RendererError("render_failed")
        html = response.get("html")
        if response.get("ok") is not True or not isinstance(html, str):
            raise RendererError("invalid_response")
        return html


def _renderer_environment() -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
    return {key: os.environ[key] for key in allowed if os.environ.get(key)}


def _limit_resources() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
