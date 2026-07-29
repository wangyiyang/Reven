"""Fail-closed Linux process sandbox argument construction."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class SandboxUnavailableError(RuntimeError):
    """The required OS sandbox is not available."""


@dataclass(frozen=True)
class SandboxResourceProfile:
    cpu_seconds: int
    nofile: int
    nproc: int
    file_size_bytes: int
    address_space_bytes: int


BLOG_RESOURCE_PROFILE = SandboxResourceProfile(
    cpu_seconds=240,
    nofile=256,
    nproc=64,
    file_size_bytes=64 * 1024 * 1024,
    address_space_bytes=1536 * 1024 * 1024,
)


def bubblewrap_command(
    executable: Path,
    argv: list[str],
    *,
    writable_path: Path | None = None,
    writable_paths: Sequence[Path] = (),
    readable_paths: Sequence[Path] = (),
    network: bool = False,
    resource_profile: SandboxResourceProfile | None = None,
) -> list[str]:
    if not executable.is_file():
        raise SandboxUnavailableError("OS 沙箱不可用")
    sandbox = [
        str(executable),
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop",
        "ALL",
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
    if resource_profile is not None:
        return ["/usr/bin/prlimit", *_resource_limits(resource_profile), "--", *command]
    return command


def _system_paths() -> tuple[Path, ...]:
    candidates = (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"), Path("/etc"))
    return tuple(path for path in candidates if path.exists())


def _resource_limits(profile: SandboxResourceProfile) -> tuple[str, ...]:
    return (
        f"--cpu={profile.cpu_seconds}",
        f"--nofile={profile.nofile}",
        f"--nproc={profile.nproc}",
        f"--fsize={profile.file_size_bytes}",
        f"--as={profile.address_space_bytes}",
    )
