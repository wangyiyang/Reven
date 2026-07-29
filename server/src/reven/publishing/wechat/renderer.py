import asyncio
import json
from pathlib import Path
from typing import Any


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
    ) -> None:
        self._executable = executable
        self._cli_path = str(cli_path)
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes

    async def render(self, markdown: str) -> str:
        process = await asyncio.create_subprocess_exec(
            self._executable,
            self._cli_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
            process.kill()
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
