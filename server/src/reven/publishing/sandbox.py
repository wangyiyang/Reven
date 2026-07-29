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
    readable_paths: Sequence[Path] = (),
    network: bool = False,
) -> list[str]:
    if not executable.is_file():
        raise SandboxUnavailableError("OS 沙箱不可用")
    command = [
        str(executable),
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
    ]
    for path in _system_paths():
        command.extend(["--ro-bind", str(path), str(path)])
    for path in readable_paths:
        resolved = path.resolve()
        command.extend(["--ro-bind", str(resolved), str(resolved)])
    command.extend(
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
        command.append("--share-net")
    if writable_path is not None:
        resolved = writable_path.resolve()
        command.extend(["--bind", str(resolved), str(resolved), "--chdir", str(resolved)])
    return [*command, "--", *argv]


def _system_paths() -> tuple[Path, ...]:
    candidates = (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"), Path("/etc"))
    return tuple(path for path in candidates if path.exists())
