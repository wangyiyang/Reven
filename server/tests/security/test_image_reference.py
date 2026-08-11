import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
REVEN_REPOSITORY = "registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven"
VALID_DIGEST = "a" * 64


def _validate(image: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "REVEN_IMAGE": image}
    return subprocess.run(
        [str(ROOT / "scripts" / "validate_reven_image.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_accepts_immutable_reven_acr_digest() -> None:
    image = f"{REVEN_REPOSITORY}@sha256:{VALID_DIGEST}"

    assert _validate(image).returncode == 0


@pytest.mark.parametrize(
    "image",
    [
        f"{REVEN_REPOSITORY}:latest",
        f"{REVEN_REPOSITORY}:latest@sha256:{VALID_DIGEST}",
        f"{REVEN_REPOSITORY}@sha256:{'A' * 64}",
        f"{REVEN_REPOSITORY}@sha256:{'a' * 63}",
        f"{REVEN_REPOSITORY}@sha256:{'a' * 65}",
        f"{REVEN_REPOSITORY}@@sha256:{VALID_DIGEST}",
        f"registry.cn-hangzhou.aliyuncs.com/wangyiyang/other@sha256:{VALID_DIGEST}",
        f"ghcr.io/wangyiyang/reven@sha256:{VALID_DIGEST}",
    ],
)
def test_rejects_mutable_or_malformed_image_references(image: str) -> None:
    result = _validate(image)

    assert result.returncode != 0
    assert "REVEN_IMAGE must be" in result.stderr


def test_container_ci_never_executes_dotenv_as_shell() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert ". ./.env" not in workflow
    assert f"REVEN_IMAGE={REVEN_REPOSITORY}@sha256:" in workflow
    assert "./scripts/validate_reven_image.sh" in workflow
