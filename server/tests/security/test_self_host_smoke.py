"""Failure-path checks for the isolated self-host validation runner."""

import importlib
import json
import shutil
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[3]


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("self_host_smoke")


@pytest.mark.parametrize(
    "failure", ["up", "assert_runtime", "assert_persistence", "assert_https", "assert_production", "ps", "down"]
)
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
        **{
            name: stage(name)
            for name in ("up", "assert_runtime", "assert_persistence", "assert_https", "assert_production")
        },
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


def test_production_stage_keeps_real_routes_and_isolates_compose(
    smoke, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose CLI required for config validation; no daemon needed")
    deployment = smoke.Deployment(tmp_path)
    calls = []
    compose = deployment.compose

    def fixture_compose(*args, **kwargs):
        calls.append(args)
        return compose(*args, **kwargs) if args[0] == "config" else ""

    monkeypatch.setattr(deployment, "compose", fixture_compose)
    monkeypatch.setattr(deployment, "up", lambda: None)
    browser = SimpleNamespace(
        assert_production_routes=lambda digest: None,
        login=lambda password: "unused-test-token",
        logout=lambda token: None,
        request=lambda *args, **kwargs: (b"{}", _headers("application/json")),
    )
    clients = []
    monkeypatch.setattr(smoke, "Browser", lambda *args, **kwargs: clients.append((args, kwargs)) or browser)
    monkeypatch.setattr(deployment, "assert_static_mounts", lambda: None)
    monkeypatch.setattr(deployment, "static_index_digest", lambda: "test-index-digest")
    deployment.assert_production()
    assert calls[1] == ("down", "--timeout", "30")
    assert clients == [(("https://localhost:8443",), {"ca_file": tmp_path / "root.crt"})]
    assert deployment.files[-2:] == [ROOT / "infra/compose/docker-compose.yml", tmp_path / "production-tls.yml"]
    source = (ROOT / "infra/caddy/Caddyfile").read_text()
    temporary = (tmp_path / "Caddyfile").read_text()
    assert source.split("\nreven.wangyiyang.cc {")[0] == temporary.split("\nhttps://localhost:8443 {")[0]
    assert "\ttls internal\n" in temporary
    override = (tmp_path / "production-tls.yml").read_text()
    assert "env_file: !override []" in override and "ports: !override" in override
    assert (tmp_path / "production-tls.yml").stat().st_mode & 0o777 == 0o600
    configuration = json.loads(smoke.Deployment.compose(deployment, "config", "--format", "json", capture=True))
    _assert_isolated_production(configuration, deployment.project)


def _assert_isolated_production(configuration: dict, project: str) -> None:
    services = configuration["services"]
    reven, caddy = services["reven"], services["caddy"]
    assert reven["image"] == "reven:test" and reven["pull_policy"] == "never"
    assert not reven.get("env_file")
    assert "@postgres:5432/reven" in reven["environment"]["DATABASE_URL"]
    assert set(caddy["environment"]) == {"REVEN_PUBLIC_BASE_URL"}
    assert not reven.get("ports") and not services["postgres"].get("ports")
    assert len(caddy["ports"]) == 1
    port = caddy["ports"][0]
    assert (port["host_ip"], port["published"], port["target"]) == ("127.0.0.1", "8443", 8443)
    mounts = [
        next(mount for mount in service["volumes"] if mount["target"] == "/srv/reven") for service in (reven, caddy)
    ]
    assert mounts[0]["source"] == mounts[1]["source"] == "reven-static"
    assert not mounts[0].get("read_only", False) and mounts[1]["read_only"]
    assert all(volume["name"].startswith(project + "_") for volume in configuration["volumes"].values())
    for service in (reven, caddy):
        assert service["read_only"] and service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"] and not service.get("privileged")
        assert service["environment"]["REVEN_PUBLIC_BASE_URL"] == "https://localhost:8443"
    assert not reven.get("cap_add") and caddy["cap_add"] == ["NET_BIND_SERVICE"]


@pytest.mark.parametrize("failure", [None, "writable_caddy", "different_volume"])
def test_runtime_static_volume_validation_checks_actual_mounts(
    smoke, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    deployment = smoke.Deployment(tmp_path)
    mount = {"Destination": "/srv/reven", "Type": "volume", "Name": "isolated_static", "Source": "/volumes/static"}
    mounts = {"reven": [{**mount, "RW": True}], "caddy": [{**mount, "RW": False}]}
    if failure == "writable_caddy":
        mounts["caddy"][0]["RW"] = True
    if failure == "different_volume":
        mounts["caddy"][0]["Source"] = "/volumes/different"
    monkeypatch.setattr(deployment, "compose", lambda *args, **kwargs: args[-1])
    monkeypatch.setattr(smoke, "run", lambda *args, **kwargs: json.dumps(mounts[args[-1]]))
    if failure:
        with pytest.raises(AssertionError):
            deployment.assert_static_mounts()
    else:
        deployment.assert_static_mounts()


def _headers(content_type: str = "text/javascript") -> Message:
    headers = Message()
    for name, value in {
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Security-Policy": "default-src 'self'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Frame-Options": "SAMEORIGIN",
    }.items():
        headers[name] = value
    return headers


@pytest.mark.parametrize("failure", [None, "html_asset", "missing_immutable", "duplicate_security_header"])
def test_built_assets_require_correct_mime_cache_and_single_security_headers(
    smoke, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    index = b'<html><script src="/assets/built.js"></script><link href="/assets/built.css" rel="stylesheet"></html>'
    browser = smoke.Browser("https://localhost:8443")
    requested = []

    def request(path):
        requested.append(path)
        headers = _headers("text/css" if path.endswith(".css") else "text/javascript")
        if failure == "html_asset":
            headers.replace_header("Content-Type", "text/html")
        elif failure == "missing_immutable":
            headers.replace_header("Cache-Control", "public, max-age=31536000")
        elif failure == "duplicate_security_header":
            headers["X-Frame-Options"] = "SAMEORIGIN"
        return b"built asset content", headers

    monkeypatch.setattr(browser, "request", request)
    if failure:
        with pytest.raises(AssertionError):
            browser.assert_assets(index)
    else:
        browser.assert_assets(index)
        assert set(requested) == {"/assets/built.js", "/assets/built.css"}


def test_production_routes_reject_a_stale_index_from_another_image(smoke, monkeypatch: pytest.MonkeyPatch) -> None:
    browser = smoke.Browser("https://localhost:8443")
    monkeypatch.setattr(browser, "request", lambda path: (b"<html>old release</html>", _headers("text/html")))
    with pytest.raises(AssertionError):
        browser.assert_production_routes("0" * 64)
