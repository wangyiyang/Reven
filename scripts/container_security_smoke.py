"""Exercise the real production blog workspace against an adversarial fixture."""

import asyncio
import shutil
import socket
import time
from dataclasses import replace
from pathlib import Path

from reven.publishing.blog.factory import create_blog_workspace
from reven.publishing.blog.workspace import BlogWorkspace
from reven.publishing.commands import CommandError, CommandRunner
from reven.publishing.sandbox import BLOG_RESOURCE_PROFILE, SandboxResourceProfile


async def main() -> None:
    jobs_root = Path("/data/jobs")
    fixture = Path("/fixture")
    Path("/data/secret").write_text("must stay hidden", encoding="utf-8")
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(0.1)
    runner = CommandRunner(timeout=300)
    workspace = create_blog_workspace(jobs_root, runner)
    assert workspace.root == jobs_root
    assert not (jobs_root / "jobs").exists()
    attempt = workspace.create_attempt("security-smoke")
    repository = attempt / "build"
    shutil.copytree(fixture, repository)
    (repository / ".attack-port").write_text(str(listener.getsockname()[1]), encoding="ascii")
    try:
        await _initialize_repository(runner, repository)
        await workspace.prepare(repository, "reven/security-smoke")
        await workspace.build(repository)
        await _assert_resource_behavior(workspace, repository)
        _assert_container_limits()
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


async def _assert_resource_behavior(workspace: BlogWorkspace, repository: Path) -> None:
    memory_probe = """
begin
  "x" * (2 * 1024 * 1024 * 1024)
  abort "address-space limit missing"
rescue NoMemoryError
end
"""
    file_probe = """
chunk = "x" * (1024 * 1024)
File.open("oversized.bin", "wb") { |file| 65.times { file.write(chunk) } }
abort "file-size limit missing"
"""
    await _assert_fork_limit(workspace, repository)
    await _run_probe(workspace, repository, memory_probe)
    try:
        await _run_probe(workspace, repository, file_probe, must_fail=True)
    finally:
        (repository / "oversized.bin").unlink(missing_ok=True)

    cpu_profile = replace(BLOG_RESOURCE_PROFILE, cpu_seconds=1)
    started = time.monotonic()
    await _run_probe(
        workspace,
        repository,
        "loop {}",
        must_fail=True,
        resource_profile=cpu_profile,
    )
    assert time.monotonic() - started < 6


async def _assert_fork_limit(workspace: BlogWorkspace, repository: Path) -> None:
    source = repository / "nproc-probe.c"
    executable = repository / "nproc-probe"
    source.write_text(
        """
#include <errno.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

int main(void) {
    pid_t children[80];
    int count = 0;
    int limited = 0;
    for (int i = 0; i < 80; i++) {
        pid_t child = fork();
        if (child == -1) {
            limited = errno == EAGAIN;
            break;
        }
        if (child == 0) {
            pause();
            _exit(0);
        }
        children[count++] = child;
    }
    for (int i = 0; i < count; i++) kill(children[i], SIGKILL);
    for (int i = 0; i < count; i++) {
        while (waitpid(children[i], 0, 0) == -1 && errno == EINTR) {}
    }
    return limited ? 0 : 2;
}
""",
        encoding="utf-8",
    )
    try:
        async with CommandRunner(timeout=15) as runner:
            await runner.run(["gcc", "-O2", "-o", str(executable), str(source)], cwd=repository)
        await _run_command_probe(workspace, repository, ["./nproc-probe"])
    finally:
        executable.unlink(missing_ok=True)
        source.unlink(missing_ok=True)


async def _run_probe(
    workspace: BlogWorkspace,
    repository: Path,
    ruby: str,
    *,
    must_fail: bool = False,
    resource_profile: SandboxResourceProfile | None = None,
) -> None:
    await _run_command_probe(
        workspace,
        repository,
        ["ruby", "-e", ruby],
        must_fail=must_fail,
        resource_profile=resource_profile,
    )


async def _run_command_probe(
    workspace: BlogWorkspace,
    repository: Path,
    argv: list[str],
    *,
    must_fail: bool = False,
    resource_profile: SandboxResourceProfile | None = None,
) -> None:
    command = workspace.sandbox_command(
        repository,
        argv,
        resource_profile=resource_profile,
    )
    async with CommandRunner(timeout=5) as runner:
        try:
            await runner.run(command, cwd=repository)
        except CommandError as exc:
            assert must_fail and "超时" not in str(exc)
        else:
            assert not must_fail


def _assert_container_limits() -> None:
    assert Path("/sys/fs/cgroup/pids.max").read_text().strip() == "128"
    assert Path("/sys/fs/cgroup/memory.max").read_text().strip() == str(2 * 1024 * 1024 * 1024)
    quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
    assert quota != "max" and int(quota) / int(period) == 2


def _assert_listener_unused(listener: socket.socket) -> None:
    try:
        connection, _address = listener.accept()
    except TimeoutError:
        return
    connection.close()
    raise AssertionError("sandbox reached the host loopback listener")


if __name__ == "__main__":
    asyncio.run(main())
