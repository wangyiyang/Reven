"""Directory creation and validation without following symbolic links."""

import os
import stat
from pathlib import Path

_OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def ensure_directory(base: Path, target: Path, *, mode: int = 0o700) -> Path:
    base_absolute = base.absolute()
    target_absolute = target.absolute()
    relative = target_absolute.relative_to(base_absolute)
    descriptor = os.open(base_absolute, _OPEN_DIRECTORY)
    try:
        for part in relative.parts:
            descriptor = _open_or_create(descriptor, part, mode)
    finally:
        os.close(descriptor)
    return target_absolute


def verify_directory(base: Path, target: Path) -> Path:
    base_absolute = base.absolute()
    target_absolute = target.absolute()
    relative = target_absolute.relative_to(base_absolute)
    descriptor = os.open(base_absolute, _OPEN_DIRECTORY)
    try:
        for part in relative.parts:
            next_descriptor = os.open(part, _OPEN_DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    finally:
        os.close(descriptor)
    return target_absolute


def _open_or_create(parent: int, name: str, mode: int) -> int:
    if name in {"", ".", ".."}:
        raise ValueError("目录分量无效")
    try:
        os.mkdir(name, mode=mode, dir_fd=parent)
    except FileExistsError:
        pass
    descriptor = os.open(name, _OPEN_DIRECTORY, dir_fd=parent)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise NotADirectoryError(name)
    return _replace_parent(parent, descriptor)


def _replace_parent(parent: int, child: int) -> int:
    os.close(parent)
    return child
