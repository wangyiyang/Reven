from pathlib import Path

import pytest
from reven.publishing.blog.workspace import BlogWorkspace


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    async def run(self, argv, *, cwd=None, env=None, secrets=()):  # type: ignore[no-untyped-def]
        self.calls.append((list(argv), cwd, env))
        return type("Result", (), {"stdout": "ruby-platform"})()


@pytest.mark.anyio
async def test_workspace_auth_is_only_in_temporary_git_environment(tmp_path: Path) -> None:
    runner = Recorder()
    workspace = BlogWorkspace(tmp_path, runner)  # type: ignore[arg-type]
    path = await workspace.clone("job-id", "https://github.com/acme/blog.git", "token")
    argv, _, env = runner.calls[0]
    assert argv == ["git", "clone", "https://github.com/acme/blog.git", str(path)]
    assert "token" not in " ".join(argv)
    assert env == {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": "Authorization: Basic eC1hY2Nlc3MtdG9rZW46dG9rZW4=",
    }
