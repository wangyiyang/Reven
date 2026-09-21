"""Failure-path checks for the isolated self-host validation runner."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[3]


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("self_host_smoke")


@pytest.mark.parametrize("failure", ["up", "assert_runtime", "assert_persistence", "assert_https", "ps"])
def test_every_failure_still_cleans_only_its_project(smoke, failure: str) -> None:
    calls = []

    def stage(name):
        def invoke(*args):
            calls.append((name, args))
            if name == failure:
                raise RuntimeError(failure)

        return invoke

    def compose(*args):
        calls.append(("compose", args))
        if args[0] == failure:
            raise RuntimeError(failure)

    deployment = SimpleNamespace(
        **{name: stage(name) for name in ("up", "assert_runtime", "assert_persistence", "assert_https")},
        compose=compose,
    )
    with pytest.raises(RuntimeError, match=failure):
        smoke.exercise(deployment)
    assert calls[-1] == ("compose", ("down", "--volumes", "--remove-orphans", "--timeout", "30"))
    assert ("compose", ("ps", "--all")) in calls


def test_smoke_refuses_emulation_as_native_linux_evidence(smoke, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke, "run", lambda *args, **kwargs: "linux/aarch64")
    with pytest.raises(SystemExit, match="Native Linux AMD64 host required"):
        smoke.main()


def test_fixture_uses_unique_project_without_relaxing_container_security(smoke, tmp_path: Path) -> None:
    import json

    deployment = smoke.Deployment(tmp_path)
    assert deployment.project.startswith("reven-ci-self-host-")
    assert "--env-file" in deployment.base
    assert len(deployment.project.removeprefix("reven-ci-self-host-")) == 12
    fixture = json.loads(deployment.fixture.read_text())
    assert set(fixture["services"]["reven"]) == {"image", "pull_policy"}
    assert fixture["services"]["reven"]["image"] == "reven:test"
    assert fixture["services"]["reven"]["pull_policy"] == "never"
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_compose_subprocess_does_not_inherit_live_integration_credentials(
    smoke, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs["env"])
        return SimpleNamespace(stdout="ok\n")

    monkeypatch.setenv("SILICONFLOW_API_KEY", "unused-test-placeholder")
    monkeypatch.setenv("COS_SECRET_KEY", "unused-test-placeholder")
    monkeypatch.setenv("COMPOSE_FILE", "do-not-use.yml")
    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    assert smoke.run("docker", "compose", "config", capture=True) == "ok"
    assert "SILICONFLOW_API_KEY" not in observed
    assert "COS_SECRET_KEY" not in observed
    assert "COMPOSE_FILE" not in observed
