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


@pytest.mark.anyio
async def test_workspace_commands_use_isolated_home_tmp_and_bundle(tmp_path: Path) -> None:
    runner = Recorder()
    workspace = BlogWorkspace(tmp_path, runner)  # type: ignore[arg-type]
    path = workspace.path("job-id")
    path.mkdir(parents=True)
    await workspace.prepare(path, "reven/11111111-aaaaaaaaaaaa")
    environments = [env for _argv, _cwd, env in runner.calls]
    assert all(env is not None and env["HOME"].startswith(str(path)) for env in environments)
    assert all(env is not None and env["BUNDLE_PATH"].startswith(str(path)) for env in environments)


def test_workspace_cleanup_removes_only_safe_blog_path(tmp_path: Path) -> None:
    workspace = BlogWorkspace(tmp_path, Recorder())  # type: ignore[arg-type]
    path = workspace.path("job-id")
    path.mkdir(parents=True)
    (path / "artifact").write_text("x")
    snapshot = path.parent / "snapshot"
    snapshot.mkdir()
    workspace.cleanup("job-id")
    assert not path.exists()
    assert snapshot.exists()
