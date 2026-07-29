"""Isolated local Git/Jekyll workspace lifecycle."""

import base64
import hashlib
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from reven.publishing.commands import CommandResult, CommandRunner
from reven.publishing.sandbox import bubblewrap_command
from reven.publishing.secure_fs import ensure_directory, verify_directory

_JOB_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


@dataclass(frozen=True)
class TrustedArtifact:
    relative: Path
    content: bytes
    digest: bytes


class BlogWorkspace:
    def __init__(
        self,
        jobs_root: Path,
        runner: CommandRunner,
        sandbox_executable: Path | None = None,
        bundle_root: Path = Path("/opt/reven-blog"),
    ) -> None:
        self.root = jobs_root.absolute()
        self.runner = runner
        self.sandbox_executable = sandbox_executable
        self.bundle_root = bundle_root
        verify_directory(self.root.parent, self.root)

    async def clone(self, job_id: str, remote_url: str, token: str) -> Path:
        path = self.path(job_id)
        if path.exists():
            self._assert_cwd(path)
            shutil.rmtree(path)
        ensure_directory(self.root, path.parent)
        await self.runner.run(
            ["git", "clone", remote_url, str(path)],
            env=_git_auth_env(remote_url, token),
            secrets=(token,),
        )
        self._verify_repository(path)
        return path

    def create_attempt(self, job_id: str) -> Path:
        base = self.path(job_id)
        attempt = base / str(uuid4())
        ensure_directory(self.root, attempt)
        ensure_directory(self.root, attempt / ".reven-runtime")
        return attempt

    async def clone_at(self, path: Path, remote_url: str, token: str) -> Path:
        self._assert_attempt_parent(path)
        await self.runner.run(
            ["git", "-c", "submodule.recurse=false", "clone", "--no-recurse-submodules", remote_url, str(path)],
            env=_git_auth_env(remote_url, token),
            secrets=(token,),
        )
        self._verify_repository(path)
        return path

    async def prepare(self, path: Path, branch: str) -> None:
        self._verify_repository(path)
        environment = self._workspace_env(path)
        await self.runner.run(["git", "switch", "-c", branch], cwd=path, env=environment)
        await self.runner.run(
            self._sandbox_command(path, ["bundle", "check"]),
            cwd=path,
            env=environment,
        )
        self._verify_repository(path)

    async def switch(self, path: Path, branch: str) -> None:
        self._verify_repository(path)
        await self.runner.run(
            ["git", "switch", "-c", branch],
            cwd=path,
            env=self._workspace_env(path),
        )

    async def build(self, path: Path) -> None:
        self._verify_repository(path)
        argv = ["bundle", "exec", "jekyll", "build"]
        if self.sandbox_executable is not None:
            argv = self._sandbox_command(path, argv)
        await self.runner.run(argv, cwd=path, env=self._workspace_env(path))
        self._verify_repository(path)

    def _sandbox_command(self, path: Path, argv: list[str]) -> list[str]:
        if self.sandbox_executable is None:
            return argv
        return bubblewrap_command(
            self.sandbox_executable,
            argv,
            writable_path=path,
            writable_paths=(self._runtime_root(path),),
            readable_paths=(self.bundle_root,),
            resource_profile="blog",
        )

    async def commit(self, path: Path, manifest: tuple[Path, ...], title: str) -> str:
        self._verify_repository(path)
        paths = [item.as_posix() for item in manifest]
        if not paths or any(item.startswith("/") or ".." in Path(item).parts for item in paths):
            raise ValueError("Git manifest 无效")
        environment = self._workspace_env(path)
        await self.runner.run(["git", "add", "--", *paths], cwd=path, env=environment)
        safe_title = " ".join(title.replace("\0", "").split())[:120]
        await self.runner.run(
            ["git", "commit", "-m", f"feat: publish {safe_title}"],
            cwd=path,
            env=environment,
        )
        result = await self.runner.run(["git", "rev-parse", "HEAD"], cwd=path, env=environment)
        return result.stdout.strip()

    async def push(self, path: Path, remote_url: str, branch: str, token: str) -> CommandResult:
        self._verify_repository(path)
        if not branch.startswith("reven/"):
            raise ValueError("只允许推送 Reven 发布分支")
        return await self.runner.run(
            [
                "git",
                "-c",
                f"core.hooksPath={self._runtime_root(path) / 'empty-hooks'}",
                "-c",
                "credential.helper=",
                "-c",
                "protocol.ext.allow=never",
                "push",
                remote_url,
                f"HEAD:refs/heads/{branch}",
            ],
            cwd=path,
            env={**self._workspace_env(path), **_git_auth_env(remote_url, token)},
            secrets=(token,),
        )

    def path(self, job_id: str) -> Path:
        if _JOB_ID.fullmatch(job_id) is None:
            raise ValueError("job_id 无效")
        return self.root / job_id / "blog"

    def capture_artifacts(self, repo: Path, manifest: tuple[Path, ...]) -> tuple[TrustedArtifact, ...]:
        self._verify_repository(repo)
        trusted = []
        for relative in manifest:
            content = (repo / relative).read_bytes()
            trusted.append(TrustedArtifact(relative, content, hashlib.sha256(content).digest()))
        return tuple(trusted)

    def restore_artifacts(self, repo: Path, trusted: tuple[TrustedArtifact, ...]) -> None:
        self._verify_repository(repo)
        for artifact in trusted:
            destination = repo / artifact.relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(artifact.content)

    def verify_artifacts(self, repo: Path, trusted: tuple[TrustedArtifact, ...]) -> None:
        self._verify_repository(repo)
        for artifact in trusted:
            candidate = repo / artifact.relative
            if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).digest() != artifact.digest:
                raise ValueError("Jekyll 构建篡改了发布 manifest")

    def _assert_cwd(self, path: Path) -> None:
        absolute = path.absolute()
        if not absolute.is_relative_to(self.root) or "blog" not in absolute.parts:
            raise ValueError("命令工作目录越界")
        verify_directory(self.root, absolute)

    def cleanup(self, job_id: str) -> None:
        path = self.path(job_id)
        if path.is_symlink():
            raise ValueError("拒绝清理符号链接工作区")
        self._assert_cwd(path)
        if path.exists():
            shutil.rmtree(path)

    def cleanup_attempt(self, attempt: Path) -> None:
        self._assert_attempt_child(attempt)
        if attempt.is_symlink():
            raise ValueError("拒绝清理符号链接工作区")
        shutil.rmtree(attempt, ignore_errors=True)

    def cleanup_repository(self, path: Path) -> None:
        self._assert_cwd(path)
        shutil.rmtree(path)

    def _assert_attempt_child(self, path: Path) -> None:
        absolute = path.absolute()
        if not absolute.is_relative_to(self.root) or "blog" not in absolute.parts:
            raise ValueError("attempt 工作目录越界")
        verify_directory(self.root, absolute)

    def _assert_attempt_parent(self, path: Path) -> None:
        self._assert_attempt_child(path.parent)
        if path.exists() or path.is_symlink():
            raise ValueError("clone 目标必须不存在")

    def _verify_repository(self, path: Path) -> None:
        self._assert_cwd(path)
        _reject_symlinks(path)

    def _runtime_root(self, path: Path) -> Path:
        runtime = path.parent / ".reven-runtime" / path.name
        return ensure_directory(self.root, runtime)

    def _workspace_env(self, path: Path) -> dict[str, str]:
        runtime = self._runtime_root(path)
        directories = {
            "HOME": runtime / "home",
            "TMPDIR": runtime / "tmp",
            "BUNDLE_USER_HOME": runtime / "bundle-user",
        }
        for directory in directories.values():
            ensure_directory(self.root, directory)
        return {
            **{key: str(value) for key, value in directories.items()},
            "BUNDLE_FROZEN": "true",
            "BUNDLE_GEMFILE": str(self.bundle_root / "Gemfile"),
            "BUNDLE_PATH": str(self.bundle_root / "vendor" / "bundle"),
        }


def _git_auth_env(remote_url: str, token: str) -> dict[str, str]:
    parsed = urlsplit(remote_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
        raise ValueError("Git remote 必须是 github.com HTTPS URL")
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {encoded}",
    }


def _reject_symlinks(root: Path) -> None:
    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            candidate = Path(current) / name
            if stat.S_ISLNK(candidate.lstat().st_mode):
                raise ValueError("博客仓库包含不允许的符号链接")
