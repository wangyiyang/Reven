from pathlib import Path

import pytest
from reven.publishing.secure_fs import ensure_directory, verify_directory


def test_secure_directory_creation_never_follows_intermediate_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    base = tmp_path / "base"
    base.mkdir()
    (base / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        ensure_directory(base, base / "link" / "created")

    assert not (outside / "created").exists()


def test_secure_directory_verification_rejects_replaced_component(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    base = tmp_path / "base"
    target = base / "attempt" / "repo"
    target.mkdir(parents=True)
    target.rmdir()
    (base / "attempt" / "repo").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        verify_directory(base, target)
