from pathlib import Path

ROOT = Path(__file__).parents[3]
REPOSITORY = "registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven"


def test_container_ci_only_runs_when_full_checks_are_requested() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\njobs:\n", 1)[0]
    container = workflow.split("\n  container:\n", 1)[1]

    assert "  workflow_call:\n    inputs:\n      full:\n" in triggers
    assert "        required: false\n        type: boolean\n        default: false\n" in triggers
    assert "  pull_request:\n    branches: [main]\n" in triggers
    assert "  push:\n    branches: [main]\n" in triggers
    assert container.startswith("    if: inputs.full\n")
    assert "steps.filter.outputs.container" not in workflow
    assert "needs.changes.outputs.container" not in workflow
    assert "\n            container:\n" not in workflow


def test_regular_ci_checks_keep_path_filters_and_full_override() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for job in ("backend", "migration", "frontend"):
        assert f"\n  {job}:\n    if: inputs.full || needs.changes.outputs.{job} == 'true'\n" in workflow
        assert f"      {job}: ${{{{ steps.filter.outputs.{job} }}}}\n" in workflow
        assert f"\n            {job}:\n" in workflow


def test_release_image_requires_full_ci_and_manual_deploy_skips_builds() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\npermissions:\n", 1)[0]
    quality_gate = workflow.split("\n  quality-gate:\n", 1)[1].split("\n  image:\n", 1)[0]
    image = workflow.split("\n  image:\n", 1)[1].split("\n  deploy:\n", 1)[0]

    assert "  push:\n    tags: ['v*']\n" in triggers
    assert "  workflow_dispatch:\n" in triggers
    assert "  release:\n" not in triggers
    assert quality_gate.startswith("    if: github.event_name == 'push'\n")
    assert "    uses: ./.github/workflows/ci.yml\n    with:\n      full: true\n" in quality_gate
    assert image.startswith("    if: github.event_name == 'push'\n    needs: quality-gate\n")


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
    assert "docker/seccomp-bwrap.json" not in script
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
    container = workflow.split("\n  container:\n", 1)[1]

    assert "COPY infra/ /opt/reven-release/infra/" in dockerfile
    assert "docker build --pull --no-cache -f infra/docker/Dockerfile -t reven:test ." in container
    assert 'docker cp "$export_container:/opt/reven-release/infra/."' in container
    assert 'diff -ru infra "$exported_infra"' in container
    assert "sh scripts/test_deploy_reven.sh" in container
    assert "Verify non-root runtime and embedded agent" in container
    assert "dsh --version" in container
    assert "renderer/dist" not in dockerfile
    assert "ruby-full" not in dockerfile
    assert "bubblewrap" not in dockerfile
    assert "--format cyclonedx --output /work/reven-sbom.cdx.json reven:test" in container
    assert "--exit-code 1 --ignore-unfixed --severity CRITICAL reven:test" in container
    assert "name: reven-container-sbom" in container
