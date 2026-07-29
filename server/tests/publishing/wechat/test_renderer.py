import asyncio
import sys
from pathlib import Path

import pytest
from reven.publishing.wechat.renderer import RendererError, WechatRenderer


def write_cli(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "renderer.py"
    script.write_text(body)
    return script


@pytest.mark.anyio
async def test_renderer_returns_html(tmp_path: Path) -> None:
    script = write_cli(
        tmp_path,
        "import json\nprint(json.dumps({'ok': True, 'html': '<h1>标题</h1>'}))\n",
    )
    renderer = WechatRenderer(executable=sys.executable, cli_path=script)

    assert await renderer.render("# 标题") == "<h1>标题</h1>"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("raise SystemExit(2)\n", "process_failed"),
        ("print('not json')\n", "invalid_response"),
        ("import json\nprint(json.dumps({'ok': False, 'error': 'render_failed'}))\n", "render_failed"),
        ("import json\nprint(json.dumps({'ok': True}))\n", "invalid_response"),
    ],
)
async def test_renderer_classifies_process_failures(tmp_path: Path, body: str, code: str) -> None:
    renderer = WechatRenderer(executable=sys.executable, cli_path=write_cli(tmp_path, body))

    with pytest.raises(RendererError, match=code):
        await renderer.render("正文")


@pytest.mark.anyio
async def test_renderer_times_out_and_reaps_process(tmp_path: Path) -> None:
    script = write_cli(tmp_path, "import time\ntime.sleep(60)\n")
    renderer = WechatRenderer(executable=sys.executable, cli_path=script, timeout_seconds=0.01)

    with pytest.raises(RendererError, match="timeout"):
        await renderer.render("正文")


@pytest.mark.anyio
async def test_renderer_rejects_oversized_output(tmp_path: Path) -> None:
    script = write_cli(tmp_path, "print('x' * 1000)\n")
    renderer = WechatRenderer(executable=sys.executable, cli_path=script, max_output_bytes=100)

    with pytest.raises(RendererError, match="output_too_large"):
        await renderer.render("正文")


@pytest.mark.anyio
async def test_renderer_drains_large_stderr_without_exposing_it(tmp_path: Path) -> None:
    script = write_cli(tmp_path, "import sys\nsys.stderr.write('secret' * 200000)\nraise SystemExit(2)\n")
    renderer = WechatRenderer(executable=sys.executable, cli_path=script, timeout_seconds=1)

    with pytest.raises(RendererError, match="process_failed"):
        await renderer.render("正文")


@pytest.mark.anyio
async def test_renderer_reaps_process_when_cancelled(tmp_path: Path) -> None:
    script = write_cli(tmp_path, "import time\ntime.sleep(60)\n")
    renderer = WechatRenderer(executable=sys.executable, cli_path=script)
    task = asyncio.create_task(renderer.render("正文"))
    await asyncio.sleep(0.02)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
