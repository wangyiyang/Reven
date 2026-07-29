"""Exercise the real production blog workspace against an adversarial fixture."""

import asyncio
import json
import shutil
import socket
from pathlib import Path

from reven.publishing.blog.workspace import BlogWorkspace
from reven.publishing.commands import CommandRunner
from reven.publishing.sandbox import bubblewrap_command


async def main() -> None:
    jobs_root = Path("/data/jobs")
    fixture = Path("/fixture")
    Path("/data/secret").write_text("must stay hidden", encoding="utf-8")
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(0.1)
    runner = CommandRunner(timeout=300)
    workspace = BlogWorkspace(jobs_root, runner, sandbox_executable=Path("/usr/bin/bwrap"))
    attempt = workspace.create_attempt("security-smoke")
    repository = attempt / "build"
    shutil.copytree(fixture, repository)
    (repository / ".attack-port").write_text(str(listener.getsockname()[1]), encoding="ascii")
    try:
        await _initialize_repository(runner, repository)
        await workspace.prepare(repository, "reven/security-smoke")
        await workspace.build(repository)
        await _assert_resource_limits(runner, repository)
        _assert_listener_unused(listener)
        assert (repository / "_site/index.html").is_file()
    finally:
        listener.close()
        workspace.cleanup_attempt(attempt)
        await runner.close()


async def _initialize_repository(runner: CommandRunner, repository: Path) -> None:
    await runner.run(["git", "init"], cwd=repository)
    await runner.run(["git", "config", "user.name", "Reven CI"], cwd=repository)
    await runner.run(["git", "config", "user.email", "ci@example.invalid"], cwd=repository)
    await runner.run(["git", "add", "."], cwd=repository)
    await runner.run(["git", "commit", "-m", "fixture"], cwd=repository)


async def _assert_resource_limits(runner: CommandRunner, repository: Path) -> None:
    ruby = (
        'require "json"; puts JSON.generate({'
        "cpu: Process.getrlimit(:CPU)[0], "
        "nofile: Process.getrlimit(:NOFILE)[0], "
        "nproc: Process.getrlimit(:NPROC)[0], "
        "fsize: Process.getrlimit(:FSIZE)[0], "
        "as: Process.getrlimit(:AS)[0]})"
    )
    command = bubblewrap_command(
        Path("/usr/bin/bwrap"),
        ["ruby", "-e", ruby],
        writable_path=repository,
        resource_profile="blog",
    )
    result = await runner.run(command, cwd=repository)
    limits = json.loads(result.stdout)
    assert limits == {
        "cpu": 240,
        "nofile": 256,
        "nproc": 64,
        "fsize": 67_108_864,
        "as": 1_610_612_736,
    }


def _assert_listener_unused(listener: socket.socket) -> None:
    try:
        connection, _address = listener.accept()
    except TimeoutError:
        return
    connection.close()
    raise AssertionError("sandbox reached the host loopback listener")


if __name__ == "__main__":
    asyncio.run(main())
