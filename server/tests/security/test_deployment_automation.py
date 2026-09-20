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

    for job in ("backend", "migration", "frontend", "renderer"):
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
    container = workflow.split("\n  container:\n", 1)[1]

    assert "COPY infra/ /opt/reven-release/infra/" in dockerfile
    assert "docker build --pull --no-cache -f infra/docker/Dockerfile -t reven:test ." in container
    assert 'docker cp "$export_container:/opt/reven-release/infra/."' in container
    assert 'diff -ru infra "$exported_infra"' in container
    assert "sh scripts/test_deploy_reven.sh" in container
    assert "Verify non-root runtime and renderer sandbox" in container
    assert "Verify production blog sandbox and resource limits" in container
    assert "--format cyclonedx --output /work/reven-sbom.cdx.json reven:test" in container
    assert "--exit-code 1 --ignore-unfixed --severity CRITICAL reven:test" in container
    assert "name: reven-container-sbom" in container


def test_full_ci_can_be_requested_manually_without_a_release() -> None:
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    events = workflow.get("on", workflow.get(True))
    assert events["workflow_dispatch"]["inputs"]["full"] == {
        "description": "Run all checks, including isolated self-host containers (no deployment)",
        "required": False,
        "type": "boolean",
        "default": False,
    }
    assert workflow["jobs"]["container"]["if"] == "inputs.full"
    assert workflow["jobs"]["container"]["runs-on"] == "ubuntu-22.04"
    assert "deploy" not in workflow["jobs"]
    assert "environment: production" not in str(workflow)


def test_self_host_smoke_precedes_legacy_host_relaxation() -> None:
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["container"]["steps"]
    runs = [step.get("run", "") for step in steps]
    smoke_index = runs.index("python3 scripts/self_host_smoke.py --apparmor")
    relaxation_index = next(i for i, run in enumerate(runs) if "sudo sysctl" in run)
    build_index = next(i for i, run in enumerate(runs) if "docker build --pull" in run)
    assert build_index < smoke_index < relaxation_index
    profile_index = runs.index("sudo apparmor_parser -r infra/self-host/apparmor/reven-self-host")
    assert profile_index < smoke_index
    assert "sudo journalctl --dmesg --no-pager -n 100" in "\n".join(runs)
    assert steps[smoke_index].get("continue-on-error", False) is False


def test_self_host_changes_select_backend_regressions_without_enabling_container() -> None:
    from fnmatch import fnmatchcase

    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    filter_step = next(step for step in workflow["jobs"]["changes"]["steps"] if step.get("id") == "filter")
    filters = yaml.safe_load(filter_step["with"]["filters"])
    for changed_path in (
        "infra/self-host/docker-compose.yml",
        "infra/self-host/Caddyfile",
        "infra/docker/Dockerfile.dockerignore",
        "scripts/self_host_smoke.py",
        "scripts/self_host_http_smoke.py",
    ):
        assert any(fnmatchcase(changed_path, pattern) for pattern in filters["backend"]), changed_path
    assert workflow["jobs"]["container"]["if"] == "inputs.full"
