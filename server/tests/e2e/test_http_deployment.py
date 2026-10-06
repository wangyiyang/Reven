import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]


def test_caddy_tls_main_site_and_explicit_http_transition() -> None:
    caddyfile = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")

    # HTTPS 主站：裸域名站点地址，Caddy 自动签发证书（#175 全站 TLS 化）
    assert "dev.wangyiyang.cc {\n\timport site_common\n}" in caddyfile
    # 过渡期 :3001 保留显式 http:// 入口，禁止隐式升级 TLS
    assert "http://dev.wangyiyang.cc:3001 {\n\timport site_common\n}" in caddyfile
    # 过渡期仍存在 HTTP 入口，全站不得下发 HSTS，否则浏览器被锁死在 HTTPS
    assert "Strict-Transport-Security" not in caddyfile


def test_compose_publishes_tls_and_transitional_http_ports() -> None:
    compose = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8"))

    # 3001：过渡期 HTTP；80：ACME 签发与 HTTP→HTTPS 跳转；443(+udp)：HTTPS 主站（含 HTTP/3）
    assert compose["services"]["caddy"]["ports"] == ["3001:3001", "80:80", "443:443", "443:443/udp"]
    # Caddy 官方镜像的 /usr/bin/caddy 带 cap_net_bind_service=ep filecap，
    # bounding set 缺该 cap 时 execve EPERM；此 cap 是 exec 前提，必须恰好保留这一个。
    assert compose["services"]["caddy"]["cap_add"] == ["NET_BIND_SERVICE"]


def test_caddy_keeps_api_and_internal_agent_outside_spa_fallback() -> None:
    caddyfile = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")

    assert "handle /api/* {\n\t\treverse_proxy reven:8000\n\t}" in caddyfile
    assert "handle /agent/* {\n\t\trespond 404\n\t}" in caddyfile


def test_caddy_static_assets_and_spa_have_separate_cache_policies() -> None:
    caddyfile = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")
    assets = caddyfile.split("\thandle /assets/* {\n", 1)[1].split("\n\t}", 1)[0]
    pages = caddyfile.split("\thandle {\n", 1)[1].split("\n\t}", 1)[0]

    assert 'header Cache-Control "public, max-age=31536000, immutable"' in assets
    assert "root * /srv/reven/current" in assets
    assert "file_server" in assets
    # 缺失静态资源必须返回 404，不能重写成 index.html。
    assert "try_files" not in assets
    assert 'header Cache-Control "no-cache"' in pages
    assert "root * /srv/reven/current" in pages
    assert "try_files {path} /index.html" in pages
    assert "file_server" in pages


def test_compose_shares_static_volume_read_only_with_caddy() -> None:
    compose = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8"))

    assert "reven-static:/srv/reven:ro" in compose["services"]["caddy"]["volumes"]
    assert "reven-static:/srv/reven" in compose["services"]["reven"]["volumes"]


def test_vercel_retains_fallback_rewrites_without_git_deployments() -> None:
    config = json.loads((ROOT / "web/vercel.json").read_text(encoding="utf-8"))

    assert config["git"]["deploymentEnabled"] is False
    assert config["rewrites"] == [
        {"source": "/api/(.*)", "destination": "https://dev.wangyiyang.cc/api/$1"},
        {"source": "/(.*)", "destination": "/index.html"},
    ]
