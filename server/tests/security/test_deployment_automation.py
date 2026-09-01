from pathlib import Path

ROOT = Path(__file__).parents[3]
REPOSITORY = "registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven"


def test_release_workflow_builds_and_deploys_version_tags_with_immutable_acr_image() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "tags: ['v*']" in workflow
    assert "workflow_dispatch:" in workflow
    assert "${GITHUB_REF_NAME}" in workflow
    assert "${IMAGE}:latest" in workflow
    assert REPOSITORY in workflow
    assert "environment: production" in workflow
    assert "concurrency:" in workflow
    assert "REVEN_DEPLOY_SSH_PRIVATE_KEY" in workflow
    assert "REVEN_DEPLOY_KNOWN_HOSTS" in workflow
    assert "FEISHU_DEPLOY_WEBHOOK" in workflow


def test_deploy_script_only_accepts_digests_and_runs_the_required_health_gate() -> None:
    script = (ROOT / "scripts" / "deploy_reven.sh").read_text(encoding="utf-8")

    assert "registry\\.cn-hangzhou\\.aliyuncs\\.com/wangyiyang/reven@sha256:" in script
    assert "docker compose" in script
    assert "pull reven" in script
    assert "up -d --wait" in script
    assert "/api/health" in script
    assert "docker create" in script
    assert "docker cp" in script
    assert "/opt/reven-release/infra" in script
    assert "compose/docker-compose.yml" in script
    assert "caddy/Caddyfile" in script
    assert "docker/seccomp-bwrap.json" in script
    assert "caddy reload" in script
    assert 'sync_infra "$restore_source"' in script
    assert ".last-healthy-image" in script
    assert "rollback" in script
    assert "./scripts/validate_reven_image.sh" not in script
    assert ". .env" not in script
    assert "source .env" not in script


def test_container_ci_verifies_embedded_infra_and_fake_docker_deployments() -> None:
    dockerfile = (ROOT / "infra" / "docker" / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "COPY infra/ /opt/reven-release/infra/" in dockerfile
    assert 'docker cp "$export_container:/opt/reven-release/infra/."' in workflow
    assert 'diff -ru infra "$exported_infra"' in workflow
    assert "sh scripts/test_deploy_reven.sh" in workflow
    assert "- 'scripts/**'" in workflow
