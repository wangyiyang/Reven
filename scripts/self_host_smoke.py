"""Validate a local reven:test image with the documented Compose security settings.

Run on a native Linux AMD64 Docker host. This never builds, pulls, publishes or
changes host security policy; dependency images must be pulled beforehand.
"""

import base64
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from self_host_http_smoke import Browser

ROOT = Path(__file__).resolve().parents[1]
SENTINELS = ("/data/self-host-smoke", "/data/dsh/self-host-smoke", "/srv/reven/.self-host-smoke")


def run(*args: str, capture: bool = False) -> str:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("REVEN_", "POSTGRES_", "COS_", "SILICONFLOW_", "RSS_", "COMPOSE_", "AGENT_"))
    }
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=environment,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


class Deployment:
    def __init__(self, temporary: Path) -> None:
        self.project = f"reven-ci-self-host-{secrets.token_hex(6)}"
        self.temporary = temporary
        self.password = secrets.token_hex(24)
        environment = temporary / ".env"
        environment.write_text(
            f"POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
            f"REVEN_MASTER_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}\n"
            f"REVEN_ADMIN_PASSWORD={self.password}\n"
            "REVEN_PUBLIC_BASE_URL=https://localhost:8443\n"
            f"REVEN_IMAGE=registry.cn-hangzhou.aliyuncs.com/reven-smoke/reven@sha256:{'0' * 64}\n",
            encoding="utf-8",
        )
        environment.chmod(0o600)
        self.fixture = temporary / "fixture.yml"
        self.fixture.write_text(
            json.dumps(
                {
                    "services": {
                        "reven": {
                            "image": "reven:test",
                            "pull_policy": "never",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.files = [
            ROOT / "infra/self-host/docker-compose.yml",
            ROOT / "infra/self-host/compose.local.yml",
            self.fixture,
        ]
        self.base = ["docker", "compose", "-p", self.project, "--env-file", str(environment)]

    def compose(self, *args: str, capture: bool = False) -> str:
        files = [value for path in self.files for value in ("-f", str(path))]
        return run(*self.base, *files, *args, capture=capture)

    def up(self) -> None:
        self.compose("up", "-d", "--wait", "--wait-timeout", "180", "--no-build", "--pull", "never")

    def assert_runtime(self) -> None:
        assert self.compose("exec", "-T", "reven", "id", "-u", capture=True) == "10001"
        container = self.compose("ps", "-q", "reven", capture=True)
        config = json.loads(run("docker", "inspect", "--format", "{{json .HostConfig}}", container, capture=True))
        assert config["ReadonlyRootfs"] and not config["Privileged"]
        assert config["CapDrop"] == ["ALL"] and not config["CapAdd"]
        assert config["Memory"] == 2 * 1024**3 and config["PidsLimit"] == 128
        assert not any("unconfined" in option for option in config["SecurityOpt"])
        assert config["SecurityOpt"] == ["no-new-privileges:true"]
        self.assert_licenses()

    def assert_licenses(self) -> None:
        self.compose(
            "exec",
            "-T",
            "reven",
            "python",
            "-c",
            "\n".join(
                [
                    "import hashlib, json, re",
                    "from pathlib import Path",
                    "root = Path('/opt/reven-licenses')",
                    "assert (root / 'LICENSE').read_text()",
                    "assert (root / 'THIRD_PARTY_NOTICES.md').read_text()",
                    "for name in ('javascript', 'python', 'system'):",
                    "    assert any(path.is_file() and path.stat().st_size for path in (root / name).rglob('*')), name",
                    "inventories = []",
                    "for directory in (root / 'javascript', Path('/app/web-dist/licenses/javascript')):",
                    "    assert not any(directory.rglob('package.json')), directory",
                    "    raw = (directory / 'inventory.json').read_bytes()",
                    "    inventories.append(raw)",
                    "    inventory = json.loads(raw)",
                    "    assert inventory['packages']",
                    "    assert re.fullmatch('[0-9a-f]{64}', inventory['lockfile']['sha256'])",
                    "    for package in inventory['packages']:",
                    "        assert {'name', 'version', 'license', 'source', 'evidence'} <= package.keys()",
                    "        assert re.fullmatch('[0-9a-f]{64}', package['manifest_sha256'])",
                    "        for evidence in package['evidence']:",
                    "            text = (directory / evidence['path']).read_bytes()",
                    "            assert hashlib.sha256(text).hexdigest() == evidence['sha256']",
                    "assert inventories[0] == inventories[1]",
                    "assert not Path('/opt/reven-release/infra/self-host/.env').exists()",
                ]
            ),
        )

    def seed_candidate(self, source_id: str) -> str:
        """Seed only the isolated database; the disabled source is never fetched."""
        return self.compose(
            "exec",
            "-T",
            "reven",
            "python",
            "-c",
            "\n".join(
                [
                    "import asyncio, hashlib",
                    "from datetime import date",
                    "from uuid import UUID",
                    "from reven.config import Settings",
                    "from reven.db import create_session_factory",
                    "from reven.rss.models import RssDiscoveryRun, RssItem",
                    "async def seed():",
                    "    async with create_session_factory(Settings()).begin() as session:",
                    "        run = RssDiscoveryRun(run_date=date(2000, 1, 1), status='completed')",
                    "        session.add(run)",
                    "        await session.flush()",
                    "        item = RssItem(",
                    f"            source_id=UUID({source_id!r}), first_seen_run_id=run.id,",
                    "            source_name='self-host smoke', title='Local smoke candidate',",
                    "            title_zh='本地验收候选', summary='Deterministic local fixture',",
                    "            summary_zh='本地确定性测试素材', status='candidate',",
                    "            title_key=hashlib.sha256(b'self-host-smoke-candidate').hexdigest(),",
                    "            embedding_status='skipped', model_status='skipped')",
                    "        session.add(item)",
                    "        await session.flush()",
                    "        print(item.id)",
                    "asyncio.run(seed())",
                ]
            ),
            capture=True,
        )

    def assert_persistence(self, browser: Browser) -> None:
        token = browser.login(self.password)
        source_id = browser.create_disabled_source()
        saved = browser.save_candidate(self.seed_candidate(source_id))
        self.compose(
            "exec",
            "-T",
            "reven",
            "python",
            "-c",
            "\n".join(
                [
                    "from pathlib import Path",
                    f"for name in {SENTINELS!r}:",
                    "    Path(name).write_text('persistent-smoke-marker')",
                ]
            ),
        )
        self.compose("down", "--timeout", "30")
        self.up()
        browser.assert_persisted_source(source_id)
        browser.assert_saved_candidate(saved)
        self.compose(
            "exec",
            "-T",
            "reven",
            "python",
            "-c",
            "\n".join(
                [
                    "from pathlib import Path",
                    f"for name in {SENTINELS!r}:",
                    "    assert Path(name).read_text() == 'persistent-smoke-marker'",
                ]
            ),
        )
        browser.logout(token)

    def assert_https(self) -> None:
        source = (ROOT / "infra/self-host/Caddyfile").read_text().replace("{\n", "{\n\ttls internal\n", 1)
        browser = self.https_browser(source)
        token = browser.login(self.password)
        browser.logout(token)

    def assert_production(self) -> None:
        source = (ROOT / "infra/caddy/Caddyfile").read_text()
        source = source.replace("\nreven.wangyiyang.cc {\n", "\nhttps://localhost:8443 {\n\ttls internal\n", 1)
        assert "reven.wangyiyang.cc" not in source and "tls internal" in source
        browser = self.https_browser(source, production=True)
        self.assert_static_mounts()
        index_digest = self.static_index_digest()
        browser.assert_production_routes(index_digest)
        token = browser.login(self.password)
        body, headers = browser.request("/api/__reven_smoke_missing__", expected=404)
        assert headers.get_content_type() == "application/json" and isinstance(json.loads(body), dict)
        browser.logout(token)

    def assert_static_mounts(self) -> None:
        mounts = []
        for service in ("reven", "caddy"):
            container = self.compose("ps", "-q", service, capture=True)
            configuration = json.loads(
                run("docker", "inspect", "--format", "{{json .Mounts}}", container, capture=True)
            )
            mounts.append(next(mount for mount in configuration if mount["Destination"] == "/srv/reven"))
        application, caddy = mounts
        assert application["Type"] == caddy["Type"] == "volume"
        assert application["Name"] == caddy["Name"] and application["Source"] == caddy["Source"]
        assert application["RW"] is True and caddy["RW"] is False

    def static_index_digest(self) -> str:
        return self.compose(
            "exec",
            "-T",
            "reven",
            "python",
            "-c",
            "\n".join(
                [
                    "import hashlib",
                    "from pathlib import Path",
                    "image = Path('/app/web-dist')",
                    "current = Path('/srv/reven/current')",
                    "release = (image / '.release').read_text().strip()",
                    "assert (current / '.release').read_text().strip() == release",
                    "assert current.resolve().name == release",
                    "assert (current / 'index.html').read_bytes() == (image / 'index.html').read_bytes()",
                    "print(hashlib.sha256((image / 'index.html').read_bytes()).hexdigest())",
                ]
            ),
            capture=True,
        )

    def https_browser(self, source: str, *, production: bool = False) -> Browser:
        isolated = (
            json.loads(self.compose("config", "--format", "json", capture=True))["services"] if production else None
        )
        self.compose("down", "--timeout", "30")
        caddyfile = self.temporary / "Caddyfile"
        caddyfile.write_text(source, encoding="utf-8")
        override = self.write_tls_override(caddyfile, isolated)
        if production:
            self.files = [ROOT / "infra/compose/docker-compose.yml"]
        self.files.append(override)
        self.up()
        self.compose(
            "exec",
            "-T",
            "caddy",
            "sh",
            "-c",
            "for attempt in $(seq 1 30); do "
            "test -r /data/caddy/pki/authorities/local/root.crt && exit 0; sleep 1; done; exit 1",
        )
        ca_file = self.temporary / "root.crt"
        self.compose("cp", "caddy:/data/caddy/pki/authorities/local/root.crt", str(ca_file))
        return Browser("https://localhost:8443", ca_file=ca_file)

    def write_tls_override(self, caddyfile: Path, isolated: dict[str, dict[str, Any]] | None) -> Path:
        override = self.temporary / ("production-tls.yml" if isolated else "tls.yml")
        postgres = ""
        reven = "    environment:\n      REVEN_PUBLIC_BASE_URL: https://localhost:8443\n"
        if isolated:
            postgres = f"  postgres: {json.dumps(isolated['postgres'])}\n"
            environment = {**isolated["reven"]["environment"], "REVEN_PUBLIC_BASE_URL": "https://localhost:8443"}
            reven = (
                "    image: reven:test\n    pull_policy: never\n    platform: linux/amd64\n"
                "    env_file: !override []\n"
                f"    environment: {json.dumps(environment)}\n"
                f"    depends_on: {json.dumps(isolated['reven']['depends_on'])}\n"
            )
        override.write_text(
            "services:\n"
            + postgres
            + "  reven:\n"
            + reven
            + "  caddy:\n    environment:\n      REVEN_PUBLIC_BASE_URL: https://localhost:8443\n"
            "    ports: !override\n      - '127.0.0.1:8443:8443'\n"
            f"    volumes:\n      - {json.dumps(str(caddyfile) + ':/etc/caddy/Caddyfile:ro')}\n"
            + ("volumes:\n  postgres-data:\n" if isolated else ""),
            encoding="utf-8",
        )
        override.chmod(0o600)
        return override


def exercise(deployment: Deployment) -> None:
    try:
        deployment.up()
        deployment.assert_runtime()
        deployment.assert_persistence(Browser("http://localhost:8080"))
        print("Self-host HTTP, authentication, saved RSS materials, volumes and licenses passed.", flush=True)
        deployment.assert_https()
        print("Self-host HTTPS passed with an explicitly trusted test CA and Secure session cookies.", flush=True)
        deployment.assert_production()
        print(
            "Production Caddy routes, image assets, read-only shared volume and same-origin HTTPS passed.", flush=True
        )
    finally:
        try:
            deployment.compose("ps", "--all")
        finally:
            deployment.compose("down", "--volumes", "--remove-orphans", "--timeout", "30")


def main() -> None:
    architecture = run("docker", "info", "--format", "{{.OSType}}/{{.Architecture}}", capture=True)
    if architecture not in {"linux/x86_64", "linux/amd64"}:
        raise SystemExit(f"Native Linux AMD64 host required; found {architecture}")
    assert (
        run("docker", "image", "inspect", "reven:test", "--format", "{{.Os}}/{{.Architecture}}", capture=True)
        == "linux/amd64"
    )
    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(143))
    with tempfile.TemporaryDirectory(prefix="reven-self-host-smoke-") as directory:
        exercise(Deployment(Path(directory)))


if __name__ == "__main__":
    main()
