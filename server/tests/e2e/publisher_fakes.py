from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from reven.jobs.errors import TransientPublishError
from reven.publishing.blog.publisher import RequiredCheck
from reven.publishing.blog.workspace import TrustedArtifact
from reven.publishing.commands import CommandResult


class ContractBlogWorkspace:
    """只替代 git/Jekyll 命令传输，文件转换仍由生产 Converter 完成。"""

    def __init__(self, root: Path, github: ContractGitHub) -> None:
        self.root = root
        self.github = github
        self.pushes = 0
        self.captured: dict[str, bytes] = {}

    def create_attempt(self, job_id: str) -> Path:
        attempt = self.root / job_id / "blog" / "attempt"
        attempt.mkdir(parents=True)
        return attempt

    async def clone_at(self, path: Path, remote_url: str, token: str) -> Path:
        assert remote_url == "https://github.com/example/blog.git"
        assert token == "contract-token"
        path.mkdir(parents=True)
        (path / ".git").mkdir()
        return path

    async def prepare(self, path: Path, branch: str) -> None:
        assert path.is_dir() and branch.startswith("reven/")

    async def switch(self, path: Path, branch: str) -> None:
        assert path.is_dir() and branch.startswith("reven/")

    async def build(self, path: Path) -> None:
        assert tuple((path / "_posts").glob("*.md"))

    def capture_artifacts(self, root: Path, manifest: tuple[Path, ...]) -> tuple[TrustedArtifact, ...]:
        artifacts = tuple(TrustedArtifact(relative, (root / relative).read_bytes(), b"") for relative in manifest)
        self.captured = {item.relative.as_posix(): item.content for item in artifacts}
        return artifacts

    def verify_artifacts(self, root: Path, trusted: tuple[TrustedArtifact, ...]) -> None:
        assert all((root / item.relative).read_bytes() == item.content for item in trusted)

    def restore_artifacts(self, root: Path, trusted: tuple[TrustedArtifact, ...]) -> None:
        for item in trusted:
            destination = root / item.relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(item.content)

    def cleanup_repository(self, path: Path) -> None:
        shutil.rmtree(path)

    async def commit(self, path: Path, manifest: tuple[Path, ...], title: str) -> str:
        assert title and all((path / item).is_file() for item in manifest)
        return "a" * 40

    async def push(self, path: Path, remote_url: str, branch: str, token: str) -> CommandResult:
        del path, remote_url, token
        self.pushes += 1
        self.github.pushed_branch = branch
        return CommandResult("", "", 0)

    def cleanup_attempt(self, attempt: Path) -> None:
        shutil.rmtree(attempt, ignore_errors=True)


class ContractGitHub:
    def __init__(self) -> None:
        self.pushed_branch: str | None = None
        self.pull: dict[str, Any] | None = None
        self.pr_creations = 0

    async def default_branch(self) -> str:
        return "main"

    async def branch(self, name: str) -> dict[str, Any] | None:
        if name == self.pushed_branch:
            return {"commit": {"sha": "a" * 40}}
        return None

    async def pull_requests(self, head: str, *, base: str, state: str = "all") -> list[dict[str, Any]]:
        assert base == "main" and state == "all"
        return [self.pull] if self.pull is not None and head == self.pushed_branch else []

    async def pull_request_template(self, default_branch: str) -> str | None:
        assert default_branch == "main"
        return None

    async def create_pull_request(self, *, title: str, head: str, base: str, body: str) -> dict[str, Any]:
        assert title.startswith("feat:") and head == self.pushed_branch and base == "main" and "## 目的" in body
        self.pr_creations += 1
        self.pull = {"number": 7, "state": "open", "html_url": "https://github.com/example/blog/pull/7"}
        return self.pull

    async def get_pull(self, number: int) -> dict[str, Any]:
        assert number == 7 and self.pull is not None
        return self.pull

    async def required_contexts(self, branch: str) -> tuple[RequiredCheck, ...]:
        assert branch == "main"
        return (RequiredCheck("Jekyll build"),)

    async def check_runs(self, sha: str) -> list[dict[str, Any]]:
        assert sha == "a" * 40
        return [{"name": "Jekyll build", "status": "completed", "conclusion": "success"}]

    async def status_contexts(self, sha: str) -> list[dict[str, Any]]:
        assert sha == "a" * 40
        return []

    async def merge(self, number: int, sha: str) -> dict[str, Any]:
        assert number == 7 and sha == "a" * 40
        assert self.pull is not None
        self.pull = {**self.pull, "state": "closed", "merged_at": "now", "merge_commit_sha": "b" * 40}
        return {"sha": "b" * 40}

    async def pages_builds(self) -> list[dict[str, Any]]:
        return [{"id": 9, "commit": "b" * 40, "status": "built"}]

    async def verify_article(self, path: str, title: str) -> str:
        assert path.startswith("/") and title
        return f"https://blog.example{path}"


class ContractRenderer:
    def __init__(self) -> None:
        self.markdown: list[str] = []

    async def render(self, markdown: str) -> str:
        self.markdown.append(markdown)
        return f"<section><p>{markdown}</p></section>"


class ContractWeChat:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.payloads: list[dict[str, object]] = []
        self.transient_drafts = 0

    async def get_token(self) -> str:
        self.calls.append("get_token")
        return "access-token"

    async def upload_body_image(self, path: Path) -> str:
        self.calls.append("upload_body_image")
        assert path.is_file()
        return "https://mmbiz.qpic.cn/body"

    async def upload_cover_material(self, path: Path) -> str:
        self.calls.append("upload_cover_material")
        assert path.is_file()
        return "thumb-media-id"

    async def create_draft(self, payload: dict[str, object]) -> str:
        self.calls.append("create_draft")
        self.payloads.append(payload)
        if self.transient_drafts:
            self.transient_drafts -= 1
            raise TransientPublishError("contract transient")
        return "draft-media-id"
