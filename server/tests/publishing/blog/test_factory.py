from pathlib import Path

import pytest
from reven.publishing.blog.factory import create_blog_workspace


class Runner:
    pass


def test_factory_uses_job_data_dir_as_jobs_root(tmp_path: Path) -> None:
    jobs_root = tmp_path / "jobs"

    workspace = create_blog_workspace(jobs_root, Runner())  # type: ignore[arg-type]

    assert workspace.root == jobs_root
    assert jobs_root.is_dir()
    assert not (jobs_root / "jobs").exists()


def test_factory_rejects_jobs_symlink_without_writing_outside(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (data / "jobs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        create_blog_workspace(data / "jobs", Runner())  # type: ignore[arg-type]

    assert list(outside.iterdir()) == []
