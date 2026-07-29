"""Fail-closed Linux process sandbox argument construction."""

from collections.abc import Sequence
from pathlib import Path


class SandboxUnavailableError(RuntimeError):
    """The required OS sandbox is not available."""


def bubblewrap_command(
    executable: Path,
    argv: list[str],
    *,
    writable_path: Path | None = None,
    writable_paths: Sequence[Path] = (),
    readable_paths: Sequence[Path] = (),
    network: bool = False,
    resource_profile: str | None = None,
) -> list[str]:
    if not executable.is_file():
        raise SandboxUnavailableError("OS 沙箱不可用")
    sandbox = [
        str(executable),
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
    ]
    for path in _system_paths():
        sandbox.extend(["--ro-bind", str(path), str(path)])
    for path in readable_paths:
        resolved = path.resolve()
        sandbox.extend(["--ro-bind", str(resolved), str(resolved)])
    sandbox.extend(
        [
            "--dev",
            "/dev",
            "--tmpfs",
            "/proc",
            "--tmpfs",
            "/tmp",
        ]
    )
    if network:
        sandbox.append("--share-net")
    if writable_path is not None:
        resolved = writable_path.resolve()
        sandbox.extend(["--bind", str(resolved), str(resolved), "--chdir", str(resolved)])
    for path in writable_paths:
        resolved = path.resolve()
        sandbox.extend(["--bind", str(resolved), str(resolved)])
    command = [*sandbox, "--", *argv]
    if resource_profile == "blog":
        return ["/usr/bin/prlimit", *_blog_limits(), "--", *command]
    return command


def _system_paths() -> tuple[Path, ...]:
    candidates = (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"), Path("/etc"))
    return tuple(path for path in candidates if path.exists())


def _blog_limits() -> tuple[str, ...]:
    return (
        "--cpu=240",
        "--nofile=256",
        "--nproc=64",
        "--fsize=67108864",
        "--as=1610612736",
    )
