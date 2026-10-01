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
