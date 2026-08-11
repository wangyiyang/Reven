from pathlib import Path

ROOT = Path(__file__).parents[3]
REPOSITORY = "registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven"


def test_release_workflow_builds_and_deploys_main_with_immutable_acr_image() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "branches: [main]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "sha-${GITHUB_SHA}" in workflow
    assert "${IMAGE}:latest" in workflow
    assert REPOSITORY in workflow
    assert "environment: production" in workflow
    assert "concurrency:" in workflow
    assert "REVEN_DEPLOY_SSH_PRIVATE_KEY" in workflow
    assert "REVEN_DEPLOY_KNOWN_HOSTS" in workflow
    assert "FEISHU_DEPLOY_WEBHOOK" in workflow


def test_deploy_script_only_accepts_digests_and_runs_the_required_health_gate() -> None:
    script = (ROOT / "scripts" / "deploy_reven.sh").read_text(encoding="utf-8")

    assert "./scripts/validate_reven_image.sh" in script
    assert "docker compose" in script
    assert "pull reven" in script
    assert "up -d --wait" in script
    assert "/api/health" in script
    assert ".last-healthy-image" in script
    assert "rollback" in script
    assert ". .env" not in script
    assert "source .env" not in script
