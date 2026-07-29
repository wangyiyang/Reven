from pathlib import Path

import pytest
from reven.publishing.sandbox import SandboxUnavailableError, bubblewrap_command


def test_bubblewrap_command_is_networkless_and_binds_only_workspace_writable(tmp_path: Path) -> None:
    executable = tmp_path / "bwrap"
    executable.touch()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    command = bubblewrap_command(executable, ["jekyll", "build"], writable_path=workspace)

    assert "--unshare-all" in command
    assert "--share-net" not in command
    assert ["--ro-bind", "/", "/"] != command[command.index("--ro-bind") : command.index("--ro-bind") + 3]
    assert "--proc" not in command
    assert command[command.index("/proc") - 1] == "--tmpfs"
    assert ["--bind", str(workspace), str(workspace)] == command[command.index("--bind") : command.index("--bind") + 3]
    assert command[-3:] == ["--", "jekyll", "build"]


def test_bubblewrap_command_fails_closed_when_binary_is_missing(tmp_path: Path) -> None:
    with pytest.raises(SandboxUnavailableError, match="沙箱不可用"):
        bubblewrap_command(tmp_path / "missing", ["true"])


def test_bubblewrap_allows_network_only_when_explicitly_requested(tmp_path: Path) -> None:
    executable = tmp_path / "bwrap"
    executable.touch()

    command = bubblewrap_command(executable, ["bundle", "install"], network=True)

    assert "--share-net" in command
