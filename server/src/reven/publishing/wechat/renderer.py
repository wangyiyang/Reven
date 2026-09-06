import asyncio
import json
import os
import re
import resource
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reven.publishing.sandbox import bubblewrap_command


class RendererError(RuntimeError):
    """A safely classified renderer process failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FONT_FORBIDDEN = re.compile(r"[{};<>\\\n\r]")


@dataclass(frozen=True)
class WechatTheme:
    """渲染器主题参数；构造即校验，非法值直接拒绝（不进入子进程）。"""

    primary_color: str
    font_family: str
    font_size: int

    def __post_init__(self) -> None:
        if not _COLOR_PATTERN.fullmatch(self.primary_color):
            raise ValueError("主题主色必须是 #RRGGBB 形式")
        if not self.font_family or len(self.font_family) > 200 or _FONT_FORBIDDEN.search(self.font_family):
            raise ValueError("主题字体无效")
        if not 12 <= self.font_size <= 24:
            raise ValueError("主题字号超出 12-24 范围")

    def to_payload(self) -> dict[str, object]:
        return {
            "primaryColor": self.primary_color,
            "fontFamily": self.font_family,
            "fontSize": self.font_size,
        }


def theme_from_params(raw: dict[str, object]) -> WechatTheme | None:
    """从品牌解析参数构造主题；全空时返回 None（legacy 路径）。"""
    primary = raw.get("primaryColor")
    family = raw.get("fontFamily")
    size = raw.get("fontSize")
    if not isinstance(primary, str) or not isinstance(family, str) or not family:
        return None
    if not isinstance(size, int):
        return None
    return WechatTheme(primary, family, size)


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

    async def render(self, markdown: str, theme: WechatTheme | None = None) -> str:
        argv = _renderer_argv(self._executable, self._cli_path)
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
                self._exchange(process, markdown, theme),
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

    async def _exchange(self, process: asyncio.subprocess.Process, markdown: str, theme: WechatTheme | None) -> bytes:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            await self._terminate(process)
            raise RendererError("process_failed")
        payload: dict[str, Any] = {"markdown": markdown}
        if theme is not None:
            payload["theme"] = theme.to_payload()
        process.stdin.write(json.dumps(payload).encode())
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
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))


def _renderer_argv(executable: str, cli_path: str) -> list[str]:
    if Path(executable).name == "node":
        return [executable, "--max-old-space-size=384", cli_path]
    return [executable, cli_path]
