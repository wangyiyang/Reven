"""Check the rendered deployment boundary without starting containers."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[3]
SELF_HOST = ROOT / "infra/self-host"


@pytest.fixture
def compose_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in os.environ:
        if name.startswith(("REVEN_", "POSTGRES_", "COS_", "SILICONFLOW_", "RSS_", "COMPOSE_", "AGENT_")):
            monkeypatch.delenv(name)
    env = tmp_path / ".env"
    env.write_text(
        "POSTGRES_PASSWORD=test-only-database-password\n"
        "REVEN_MASTER_KEY=dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHQ=\n"
        "REVEN_ADMIN_PASSWORD=test-only-admin-password\n"
        "REVEN_PUBLIC_BASE_URL=https://reven.example.com\n",
        encoding="utf-8",
    )
    return env


def render_compose(env: Path, *, local: bool = False) -> dict[str, Any]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI required for config validation; no daemon needed")
    args = [docker, "compose", "-p", "reven-self-host-test", "--env-file", str(env)]
    args.extend(["-f", str(SELF_HOST / "docker-compose.yml")])
    if local:
        args.extend(["-f", str(SELF_HOST / "compose.local.yml")])
    result = subprocess.run(args + ["config", "--format", "json"], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_source_build_keeps_application_and_database_private(compose_env: Path) -> None:
    services = render_compose(compose_env)["services"]
    reven, postgres, caddy = (services[name] for name in ("reven", "postgres", "caddy"))
    assert "image" not in reven
    assert Path(reven["build"]["context"]) == ROOT
    assert reven["build"]["dockerfile"] == "infra/docker/Dockerfile"
    assert "ports" not in reven and "ports" not in postgres
    assert {port["published"] for port in caddy["ports"]} == {"80", "443"}
    assert reven["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert caddy["depends_on"]["reven"]["condition"] == "service_healthy"
    assert postgres["image"].startswith("postgres:17-alpine@sha256:")
    assert set(caddy["environment"]) == {"REVEN_PUBLIC_BASE_URL"}
    assert all(service["platform"] == "linux/amd64" for service in services.values())
    assert reven["read_only"] and reven["cap_drop"] == ["ALL"]
    assert reven["security_opt"] == ["no-new-privileges:true"]
    assert "privileged" not in reven and "cap_add" not in reven
    assert reven["mem_limit"] and reven["pids_limit"]
    assert caddy["cap_add"] == ["NET_BIND_SERVICE"]


def test_local_override_removes_all_public_bindings(compose_env: Path) -> None:
    services = render_compose(compose_env, local=True)["services"]
    ports = services["caddy"]["ports"]
    assert len(ports) == 1
    assert (ports[0]["host_ip"], ports[0]["published"], ports[0]["target"]) == ("127.0.0.1", "8080", 8080)
    for name in ("reven", "caddy"):
        assert services[name]["environment"]["REVEN_PUBLIC_BASE_URL"] == "http://localhost:8080"
    assert "ports" not in services["reven"] and "ports" not in services["postgres"]


def test_optional_integration_values_are_forwarded_only_to_application(compose_env: Path) -> None:
    assert render_compose(compose_env)["services"]["reven"]["environment"]["SILICONFLOW_API_KEY"] is None
    with compose_env.open("a", encoding="utf-8") as stream:
        stream.write("SILICONFLOW_API_KEY=test-only-placeholder\nCOS_BUCKET=test-bucket\n")
    services = render_compose(compose_env)["services"]
    assert services["reven"]["environment"]["SILICONFLOW_API_KEY"] == "test-only-placeholder"
    assert services["reven"]["environment"]["COS_BUCKET"] == "test-bucket"
    assert "SILICONFLOW_API_KEY" not in services["caddy"]["environment"]
    assert "SILICONFLOW_API_KEY" not in services["postgres"]["environment"]


def test_caddy_only_proxies_browser_api_and_retains_cache_policy() -> None:
    caddyfile = (SELF_HOST / "Caddyfile").read_text(encoding="utf-8")
    assert caddyfile.startswith("{$REVEN_PUBLIC_BASE_URL} {")
    assert "handle /api/* {\n\t\treverse_proxy reven:8000\n\t}" in caddyfile
    assert caddyfile.count("reverse_proxy") == 1
    assert "handle /agent/* {\n\t\trespond 404\n\t}" in caddyfile
    assert "try_files {path} /index.html" in caddyfile
    assert 'Cache-Control "no-cache"' in caddyfile
    assert 'Cache-Control "public, max-age=31536000, immutable"' in caddyfile


def test_sensitive_configuration_is_required_and_volumes_remain_persistent() -> None:
    compose = yaml.safe_load((SELF_HOST / "docker-compose.yml").read_text(encoding="utf-8"))
    env = compose["services"]["reven"]["environment"]
    for name in ("REVEN_MASTER_KEY", "REVEN_ADMIN_PASSWORD", "REVEN_PUBLIC_BASE_URL"):
        assert env[name].startswith("${" + name + ":?")
    assert "${POSTGRES_PASSWORD:?" in env["DATABASE_URL"]
    assert "env_file" not in compose["services"]["caddy"]
    assert set(compose["volumes"]) == {
        "postgres-data",
        "reven-data",
        "reven-static",
        "caddy-data",
        "caddy-config",
    }
    assert "DSH_HOME" not in env and "HOME" not in env
    assert not any(volume.endswith(":/data/dsh") for volume in compose["services"]["reven"]["volumes"])


def test_retired_publishing_host_profiles_are_not_distributed() -> None:
    assert not (SELF_HOST / "compose.apparmor.yml").exists()
    assert not (SELF_HOST / "apparmor").exists()
