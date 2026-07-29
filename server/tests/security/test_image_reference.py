import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
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


def test_accepts_immutable_ghcr_digest() -> None:
    valid_images = [
        f"ghcr.io/owner-name/repo_name.v2@sha256:{VALID_DIGEST}",
        f"ghcr.io/owner/.github@sha256:{VALID_DIGEST}",
    ]

    assert all(_validate(image).returncode == 0 for image in valid_images)


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/owner/repo:latest",
        f"ghcr.io/owner/repo:latest@sha256:{VALID_DIGEST}",
        f"ghcr.io//repo@sha256:{VALID_DIGEST}",
        f"ghcr.io/owner/@sha256:{VALID_DIGEST}",
        f"ghcr.io/owner!/repo@sha256:{VALID_DIGEST}",
        f"ghcr.io/owner/repo?bad@sha256:{VALID_DIGEST}",
        f"ghcr.io/owner/repo@sha256:{'A' * 64}",
        f"ghcr.io/owner/repo@sha256:{'a' * 63}",
        f"ghcr.io/owner/repo@sha256:{'a' * 65}",
        f"ghcr.io/owner/repo@@sha256:{VALID_DIGEST}",
        f"ghcr.io/owner/../repo@sha256:{VALID_DIGEST}",
        f"ghcr.io/owner/..@sha256:{VALID_DIGEST}",
    ],
)
def test_rejects_mutable_or_malformed_image_references(image: str) -> None:
    result = _validate(image)

    assert result.returncode != 0
    assert "REVEN_IMAGE must be" in result.stderr
