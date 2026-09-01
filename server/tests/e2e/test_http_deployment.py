from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]


def test_caddy_site_uses_explicit_http_origin_without_hsts() -> None:
    caddyfile = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")

    assert caddyfile.splitlines()[0] == "http://dev.wangyiyang.cc:3001 {"
    assert "https://" not in caddyfile
    assert "Strict-Transport-Security" not in caddyfile


def test_compose_only_publishes_http_port() -> None:
    compose = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8"))

    assert compose["services"]["caddy"]["ports"] == ["3001:3001"]
    # Caddy 官方镜像的 /usr/bin/caddy 带 cap_net_bind_service=ep filecap，
    # bounding set 缺该 cap 时 execve EPERM；此 cap 是 exec 前提，必须恰好保留这一个。
    assert compose["services"]["caddy"]["cap_add"] == ["NET_BIND_SERVICE"]
