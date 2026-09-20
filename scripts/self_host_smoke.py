"""Validate a local reven:test image with the documented Compose security settings.

Run on a native Linux AMD64 Docker host, optionally with the documented named
AppArmor profile. This never builds, pulls, publishes or changes global host
policy; dependency images and any profile must be installed beforehand.
"""

import argparse
import base64
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from self_host_http_smoke import Browser

ROOT = Path(__file__).resolve().parents[1]
SENTINELS = ("/data/jobs/self-host-smoke", "/data/dsh/self-host-smoke", "/srv/reven/.self-host-smoke")


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
    def __init__(self, temporary: Path, *, apparmor: bool = False) -> None:
        self.apparmor = apparmor
        self.project = f"reven-ci-self-host-{secrets.token_hex(6)}"
        self.temporary = temporary
        self.password = secrets.token_hex(24)
        environment = temporary / ".env"
        environment.write_text(
            f"POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
            f"REVEN_MASTER_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}\n"
            f"REVEN_ADMIN_PASSWORD={self.password}\n"
            "REVEN_PUBLIC_BASE_URL=https://localhost:8443\n",
            encoding="utf-8",
        )
        environment.chmod(0o600)
        self.fixture = temporary / "fixture.yml"
        fixture_mounts = [
            f"{ROOT / 'server/tests/fixtures/blog'}:/fixture:ro",
            f"{ROOT / 'scripts/container_security_smoke.py'}:/smoke.py:ro",
        ]
        self.fixture.write_text(
            json.dumps(
                {
                    "services": {
                        "reven": {
                            "image": "reven:test",
                            "pull_policy": "never",
                            "volumes": fixture_mounts,
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
        if apparmor:
            self.files.append(ROOT / "infra/self-host/compose.apparmor.yml")
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
        if self.apparmor:
            assert (
                run("docker", "inspect", "--format", "{{.AppArmorProfile}}", container, capture=True)
                == "reven-self-host"
            )
        self.compose(
            "exec",
            "-T",
            "reven",
            "python",
            "-c",
            "\n".join(
                [
                    "from pathlib import Path",
                    "root = Path('/opt/reven-licenses')",
                    "assert (root / 'LICENSE').read_text()",
                    "assert (root / 'THIRD_PARTY_NOTICES.md').read_text()",
                    "for name in ('node', 'doocs', 'javascript', 'python', 'ruby', 'system'):",
                    "    assert any(path.is_file() and path.stat().st_size for path in (root / name).rglob('*')), name",
                    "assert not Path('/opt/reven-release/infra/self-host/.env').exists()",
                ]
            ),
        )

    def assert_persistence(self, browser: Browser) -> None:
        token = browser.login(self.password)
        source_id = browser.create_disabled_source()
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
        self.compose("down", "--timeout", "30")
        caddyfile = self.temporary / "Caddyfile"
        caddyfile.write_text(
            (ROOT / "infra/self-host/Caddyfile").read_text().replace("{\n", "{\n\ttls internal\n", 1),
            encoding="utf-8",
        )
        override = self.temporary / "tls.yml"
        override.write_text(
            "services:\n  reven:\n    environment:\n      REVEN_PUBLIC_BASE_URL: https://localhost:8443\n"
            "  caddy:\n    environment:\n      REVEN_PUBLIC_BASE_URL: https://localhost:8443\n"
            "    ports: !override\n      - '127.0.0.1:8443:8443'\n"
            f"    volumes:\n      - {json.dumps(str(caddyfile) + ':/etc/caddy/Caddyfile:ro')}\n",
            encoding="utf-8",
        )
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
        browser = Browser("https://localhost:8443", ca_file=ca_file)
        token = browser.login(self.password)
        browser.logout(token)

    def assert_sandboxes(self) -> None:
        self.compose(
            "exec",
            "-T",
            "reven",
            "python",
            "-c",
            "\n".join(
                [
                    "import subprocess, sys",
                    "from pathlib import Path",
                    "from reven.publishing.sandbox import bubblewrap_command",
                    "profile = Path('/proc/self/attr/current')",
                    "try: active_profile = profile.read_text().strip()",
                    "except OSError: active_profile = 'not enabled'",
                    "print('Sandbox profile:', active_profile)",
                    f"assert not {self.apparmor!r} or active_profile == 'reven-self-host (enforce)'",
                    "probe = subprocess.run(bubblewrap_command(Path('/usr/bin/bwrap'), ['/bin/true']),",
                    "    env={'PATH': '/usr/local/bin:/usr/bin:/bin'}, capture_output=True, text=True)",
                    "if probe.returncode:",
                    "    print('Fixed sandbox probe failed:', probe.stderr[:4096], file=sys.stderr)",
                    "    raise SystemExit(probe.returncode)",
                ]
            ),
        )
        self.compose(
            "exec",
            "-T",
            "reven",
            "python",
            "-c",
            "\n".join(
                [
                    "import asyncio",
                    "from pathlib import Path",
                    "from reven.publishing.wechat.renderer import WechatRenderer",
                    "asyncio.run(WechatRenderer('node', Path('/app/renderer/dist/cli.mjs'),",
                    "    sandbox_executable=Path('/usr/bin/bwrap')).render('# self-host sandbox'))",
                ]
            ),
        )
        self.compose("exec", "-T", "reven", "python", "/smoke.py")


def exercise(deployment: Deployment) -> None:
    try:
        deployment.up()
        deployment.assert_runtime()
        deployment.assert_persistence(Browser("http://localhost:8080"))
        print("Self-host HTTP, authentication, named-volume persistence and licenses passed.", flush=True)
        deployment.assert_https()
        print("Self-host HTTPS passed with an explicitly trusted test CA and Secure session cookies.", flush=True)
        deployment.assert_sandboxes()
        print("Self-host renderer/blog sandboxes passed with the documented Compose security options.", flush=True)
    finally:
        try:
            deployment.compose("ps", "--all")
        finally:
            deployment.compose("down", "--volumes", "--remove-orphans", "--timeout", "30")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apparmor", action="store_true", help="Use the installed reven-self-host AppArmor profile")
    args = parser.parse_args()
    architecture = run("docker", "info", "--format", "{{.OSType}}/{{.Architecture}}", capture=True)
    if architecture not in {"linux/x86_64", "linux/amd64"}:
        raise SystemExit(f"Native Linux AMD64 host required; found {architecture}")
    assert (
        run("docker", "image", "inspect", "reven:test", "--format", "{{.Os}}/{{.Architecture}}", capture=True)
        == "linux/amd64"
    )
    restrictions = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    restriction = restrictions.read_text().strip() if restrictions.exists() else "absent"
    print(f"Host unprivileged-userns restriction: {restriction}")
    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(143))
    with tempfile.TemporaryDirectory(prefix="reven-self-host-smoke-") as directory:
        exercise(Deployment(Path(directory), apparmor=args.apparmor))


if __name__ == "__main__":
    main()
