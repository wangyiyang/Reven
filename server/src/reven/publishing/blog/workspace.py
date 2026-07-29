"""Isolated local Git/Jekyll workspace lifecycle."""

import base64
import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from reven.publishing.commands import CommandResult, CommandRunner

_JOB_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


@dataclass(frozen=True)
class TrustedArtifact:
    relative: Path
    content: bytes
    digest: bytes


class BlogWorkspace:
    def __init__(self, jobs_root: Path, runner: CommandRunner) -> None:
        self.root = jobs_root.resolve()
        self.runner = runner

    async def clone(self, job_id: str, remote_url: str, token: str) -> Path:
        path = self.path(job_id)
        if path.exists():
            shutil.rmtree(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.runner.run(
            ["git", "clone", remote_url, str(path)],
            env=_git_auth_env(remote_url, token),
            secrets=(token,),
        )
        return path

    def create_attempt(self, job_id: str) -> Path:
        base = self.path(job_id)
        attempt = base / str(uuid4())
        attempt.mkdir(parents=True, mode=0o700)
        return attempt

    async def clone_at(self, path: Path, remote_url: str, token: str) -> Path:
        self._assert_attempt_child(path)
        await self.runner.run(
            ["git", "-c", "submodule.recurse=false", "clone", "--no-recurse-submodules", remote_url, str(path)],
            env=_git_auth_env(remote_url, token),
            secrets=(token,),
        )
        return path

    async def prepare(self, path: Path, branch: str) -> None:
        self._assert_cwd(path)
        environment = _workspace_env(path)
        await self.runner.run(["git", "switch", "-c", branch], cwd=path, env=environment)
        platform = (
            await self.runner.run(
                ["ruby", "-e", "print Gem::Platform.local"],
                cwd=path,
                env=environment,
            )
        ).stdout.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", platform):
            raise ValueError("Ruby platform 输出无效")
        await self.runner.run(["bundle", "lock", "--add-platform", platform], cwd=path, env=environment)
        await self.runner.run(["bundle", "install"], cwd=path, env=environment)

    async def switch(self, path: Path, branch: str) -> None:
        self._assert_cwd(path)
        await self.runner.run(
            ["git", "switch", "-c", branch],
            cwd=path,
            env=_workspace_env(path),
        )

    async def build(self, path: Path) -> None:
        self._assert_cwd(path)
        await self.runner.run(["bundle", "exec", "jekyll", "build"], cwd=path, env=_workspace_env(path))

    async def commit(self, path: Path, manifest: tuple[Path, ...], title: str) -> str:
        self._assert_cwd(path)
        paths = [item.as_posix() for item in manifest]
        if not paths or any(item.startswith("/") or ".." in Path(item).parts for item in paths):
            raise ValueError("Git manifest 无效")
        environment = _workspace_env(path)
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
        self._assert_attempt_child(path)
        if not branch.startswith("reven/"):
            raise ValueError("只允许推送 Reven 发布分支")
        return await self.runner.run(
            [
                "git",
                "-c",
                f"core.hooksPath={path / '.reven' / 'empty-hooks'}",
                "-c",
                "credential.helper=",
                "-c",
                "protocol.ext.allow=never",
                "push",
                remote_url,
                f"HEAD:refs/heads/{branch}",
            ],
            cwd=path,
            env={**_workspace_env(path), **_git_auth_env(remote_url, token)},
            secrets=(token,),
        )

    def path(self, job_id: str) -> Path:
        if _JOB_ID.fullmatch(job_id) is None:
            raise ValueError("job_id 无效")
        return self.root / job_id / "blog"

    def capture_artifacts(self, repo: Path, manifest: tuple[Path, ...]) -> tuple[TrustedArtifact, ...]:
        trusted = []
        for relative in manifest:
            content = (repo / relative).read_bytes()
            trusted.append(TrustedArtifact(relative, content, hashlib.sha256(content).digest()))
        return tuple(trusted)

    def restore_artifacts(self, repo: Path, trusted: tuple[TrustedArtifact, ...]) -> None:
        for artifact in trusted:
            destination = repo / artifact.relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(artifact.content)

    def verify_artifacts(self, repo: Path, trusted: tuple[TrustedArtifact, ...]) -> None:
        for artifact in trusted:
            candidate = repo / artifact.relative
            if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).digest() != artifact.digest:
                raise ValueError("Jekyll 构建篡改了发布 manifest")

    def _assert_cwd(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or "blog" not in resolved.parts:
            raise ValueError("命令工作目录越界")

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

    def _assert_attempt_child(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or "blog" not in resolved.parts:
            raise ValueError("attempt 工作目录越界")


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


def _workspace_env(path: Path) -> dict[str, str]:
    isolated = path / ".reven"
    directories = {
        "HOME": isolated / "home",
        "TMPDIR": isolated / "tmp",
        "BUNDLE_USER_HOME": isolated / "bundle",
        "BUNDLE_PATH": isolated / "bundle" / "path",
        "GEM_HOME": isolated / "gem",
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return {key: str(value) for key, value in directories.items()}
