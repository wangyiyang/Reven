"""GitHub Flow invariants shared by the blog publisher."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from reven.jobs.errors import BlockedPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.blog.converter import BlogArticle, BlogConverter
from reven.publishing.blog.workspace import BlogWorkspace
from reven.publishing.snapshot import build_snapshot
from reven.publishing.wechat.publisher import LeaseLost, load_snapshot_assets


class GitHubApi(Protocol):
    async def default_branch(self) -> str: ...
    async def branch(self, name: str) -> dict[str, Any] | None: ...
    async def pull_requests(self, head: str, *, state: str = "all") -> list[dict[str, Any]]: ...
    async def pull_request_template(self, default_branch: str) -> str | None: ...
    async def create_pull_request(self, *, title: str, head: str, base: str, body: str) -> dict[str, Any]: ...
    async def required_contexts(self, branch: str) -> tuple[str, ...]: ...
    async def check_runs(self, sha: str) -> list[dict[str, Any]]: ...
    async def status_contexts(self, sha: str) -> list[dict[str, Any]]: ...
    async def merge(self, number: int, sha: str) -> dict[str, Any]: ...
    async def pages_builds(self) -> list[dict[str, Any]]: ...
    async def verify_article(self, path: str, title: str) -> str: ...


class ResultStore(Protocol):
    async def load(self, claim: JobClaim) -> dict[str, object]: ...
    async def assert_lease(self, claim: JobClaim) -> bool: ...
    async def save_result(self, claim: JobClaim, patch: dict[str, object]) -> bool: ...
    async def clear_operation(self, claim: JobClaim, operation_id: str) -> bool: ...


@dataclass(frozen=True)
class BlogPublishResult:
    article_url: str
    pull_request_number: int
    merge_sha: str


class BlogPublisher:
    def __init__(
        self,
        client: GitHubApi,
        workspace: BlogWorkspace,
        converter: BlogConverter,
        store: ResultStore,
        *,
        remote_url: str,
        token: str,
        poll_interval: float = 5,
        max_polls: int = 120,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client, self.workspace, self.converter, self.store = client, workspace, converter, store
        self.remote_url, self.token = remote_url, token
        self.poll_interval, self.max_polls, self.sleep = poll_interval, max_polls, sleep

    async def publish(self, claim: JobClaim) -> BlogPublishResult:
        raw = await self.store.load(claim)
        result = _dict(raw.get("blog_result"))
        existing_url = result.get("article_url")
        if isinstance(existing_url, str) and existing_url:
            return _result(result)
        context = _context(raw)
        default = await self._persist_value(claim, result, "default_branch", self.client.default_branch)
        branch = release_branch(context.page_id, context.content_hash, default)
        await self._save(claim, result, {"branch": branch})
        commit_sha, article_path, post_path = await self._ensure_branch(claim, result, context, branch)
        pr = await self._ensure_pull_request(claim, result, context.title, post_path, branch, default)
        pr_number = _integer(pr.get("number"), "PR number")
        await self._wait_checks(default, commit_sha)
        merge_sha = await self._ensure_merge(claim, result, pr_number, commit_sha, branch)
        await self._wait_pages(claim, result, merge_sha)
        article_url = await self.client.verify_article(article_path, context.title)
        await self._save(claim, result, {"article_url": article_url})
        return BlogPublishResult(article_url, pr_number, merge_sha)

    async def _ensure_branch(
        self,
        claim: JobClaim,
        result: dict[str, object],
        context: "_PublishContext",
        branch: str,
    ) -> tuple[str, str, str]:
        remote = await self.client.branch(branch)
        persisted_path = result.get("article_path")
        if remote is not None:
            commit = _dict(remote.get("commit"))
            sha = _string(commit.get("sha"), "远程分支 SHA")
            if not isinstance(persisted_path, str):
                raise BlockedPublishError("远程发布分支存在但文章路径未持久化，请人工核验")
            await self._recover_operation(claim, result, "push")
            return sha, persisted_path, str(result.get("post_path", ""))
        await self._assert_lease(claim)
        path = await self.workspace.clone(str(claim.job_id), self.remote_url, self.token)
        await self.workspace.prepare(path, branch)
        converted = self.converter.write(path, BlogArticle(context.page_id, context.snapshot, context.assets))
        await self.workspace.build(path)
        sha = await self.workspace.commit(path, converted.manifest, context.title)
        patch: dict[str, object] = {
            "commit_sha": sha,
            "article_path": converted.article_path,
            "post_path": converted.manifest[0].as_posix(),
        }
        await self._save(claim, result, patch)
        await self._operation(claim, result, "push")
        try:
            await self.workspace.push(path, self.remote_url, branch, self.token)
        except Exception as exc:
            recovered = await self.client.branch(branch)
            if recovered is None:
                raise BlockedPublishError("Git push 结果不确定，请人工核验") from exc
        await self._clear_operation(claim, result)
        return sha, converted.article_path, converted.manifest[0].as_posix()

    async def _ensure_pull_request(
        self,
        claim: JobClaim,
        result: dict[str, object],
        title: str,
        post_path: str,
        branch: str,
        default: str,
    ) -> dict[str, Any]:
        pulls = await self.client.pull_requests(branch)
        if pulls:
            pr = pulls[0]
            await self._recover_operation(claim, result, "create_pr")
        else:
            template = await self.client.pull_request_template(default)
            await self._operation(claim, result, "create_pr")
            try:
                pr = await self.client.create_pull_request(
                    title=f"feat: publish {' '.join(title.split())[:120]}",
                    head=branch,
                    base=default,
                    body=pull_request_body(template, post_path),
                )
            except Exception as exc:
                recovered = await self.client.pull_requests(branch)
                if not recovered:
                    raise BlockedPublishError("PR 创建结果不确定，请人工核验") from exc
                pr = recovered[0]
            await self._clear_operation(claim, result)
        await self._save(claim, result, {"pull_request_number": _integer(pr.get("number"), "PR number")})
        return pr

    async def _wait_checks(self, default: str, sha: str) -> None:
        required = await self.client.required_contexts(default)
        if not required:
            checks_state(required, [], [])
        for _ in range(self.max_polls):
            state = checks_state(required, await self.client.check_runs(sha), await self.client.status_contexts(sha))
            if state == "success":
                return
            await self.sleep(self.poll_interval)
        raise BlockedPublishError("required checks 等待超时")

    async def _ensure_merge(
        self,
        claim: JobClaim,
        result: dict[str, object],
        number: int,
        sha: str,
        branch: str,
    ) -> str:
        existing = result.get("merge_sha")
        if isinstance(existing, str) and existing:
            return existing
        pulls = await self.client.pull_requests(branch)
        merged_pr = next((item for item in pulls if item.get("merged_at")), None)
        if merged_pr is not None:
            merge_sha = _string(merged_pr.get("merge_commit_sha"), "merge SHA")
            await self._save(claim, result, {"merge_sha": merge_sha})
            await self._recover_operation(claim, result, "merge")
            return merge_sha
        await self._operation(claim, result, "merge")
        try:
            merged = await self.client.merge(number, sha)
            merge_sha = _string(merged.get("sha"), "merge SHA")
        except Exception as exc:
            pulls = await self.client.pull_requests(branch)
            merged_pr = next((item for item in pulls if item.get("merged_at")), None)
            if merged_pr is None:
                raise BlockedPublishError("PR 合并结果不确定，请人工核验") from exc
            merge_sha = _string(merged_pr.get("merge_commit_sha"), "merge SHA")
        await self._save(claim, result, {"merge_sha": merge_sha})
        await self._clear_operation(claim, result)
        return merge_sha

    async def _wait_pages(self, claim: JobClaim, result: dict[str, object], merge_sha: str) -> None:
        for _ in range(self.max_polls):
            builds = await self.client.pages_builds()
            build = next((item for item in builds if item.get("commit") == merge_sha), None)
            if build is not None and build.get("status") == "built":
                await self._save(claim, result, {"pages_build_id": build.get("id")})
                return
            if build is not None and build.get("status") in {"errored", "cancelled"}:
                raise BlockedPublishError("GitHub Pages 构建失败")
            await self.sleep(self.poll_interval)
        raise BlockedPublishError("GitHub Pages 未部署本次 merge SHA")

    async def _persist_value(
        self,
        claim: JobClaim,
        result: dict[str, object],
        key: str,
        loader: Callable[[], Awaitable[str]],
    ) -> str:
        current = result.get(key)
        if isinstance(current, str) and current:
            return current
        value = await loader()
        await self._save(claim, result, {key: value})
        return value

    async def _operation(self, claim: JobClaim, result: dict[str, object], phase: str) -> None:
        marker = result.get("operation")
        if isinstance(marker, dict):
            raise BlockedPublishError(f"{marker.get('phase', '外部写')}结果不确定，请人工核验")
        await self._save(claim, result, {"operation": {"id": str(uuid4()), "phase": phase}})

    async def _clear_operation(self, claim: JobClaim, result: dict[str, object]) -> None:
        marker = _dict(result.get("operation"))
        operation_id = _string(marker.get("id"), "operation id")
        if not await self.store.clear_operation(claim, operation_id):
            raise LeaseLost("publication lease lost")
        result.pop("operation", None)

    async def _recover_operation(self, claim: JobClaim, result: dict[str, object], phase: str) -> None:
        marker = result.get("operation")
        if not isinstance(marker, dict) or marker.get("phase") != phase:
            return
        await self._clear_operation(claim, result)

    async def _assert_lease(self, claim: JobClaim) -> None:
        if not await self.store.assert_lease(claim):
            raise LeaseLost("publication lease lost")

    async def _save(self, claim: JobClaim, result: dict[str, object], patch: dict[str, object]) -> None:
        if not await self.store.save_result(claim, patch):
            raise LeaseLost("publication lease lost")
        result.update(patch)


def release_branch(page_id: str, content_hash: str, default_branch: str) -> str:
    del default_branch
    page = re.sub(r"[^0-9A-Fa-f]", "", page_id)[:8].lower()
    digest = re.fullmatch(r"[0-9a-fA-F]{64}", content_hash)
    if len(page) != 8 or digest is None:
        raise ValueError("page_id 或 content_hash 无效")
    return f"reven/{page}-{content_hash[:12].lower()}"


def checks_state(
    required: tuple[str, ...],
    check_runs: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
) -> str:
    if not required:
        raise BlockedPublishError("默认分支未配置 required check，禁止自动合并")
    values: dict[str, str] = {}
    for run in check_runs:
        name = run.get("name")
        if isinstance(name, str):
            status = run.get("status")
            values[name] = str(run.get("conclusion")) if status == "completed" else "pending"
    for status in statuses:
        context = status.get("context")
        if isinstance(context, str):
            values[context] = str(status.get("state"))
    relevant = {name: values.get(name, "pending") for name in required}
    failed = {"failure", "failed", "cancelled", "timed_out", "action_required", "error"}
    if any(value in failed for value in relevant.values()):
        raise BlockedPublishError("required check 失败，禁止自动合并")
    return "success" if all(value == "success" for value in relevant.values()) else "pending"


def pull_request_body(template: str | None, post_path: str) -> str:
    if template and template.strip():
        return template
    return (
        "## 目的\n\n通过 Reven 发布已冻结并完成审核的文章。\n\n"
        f"## 改动\n\n- 新增 `{post_path}` 及其冻结图片素材。\n\n"
        "## 验证\n\n- [x] 本地 `bundle exec jekyll build`\n"
        "- [ ] Required checks\n"
    )


@dataclass(frozen=True)
class _PublishContext:
    page_id: str
    title: str
    content_hash: str
    snapshot: Any
    assets: Any


def _context(raw: dict[str, object]) -> _PublishContext:
    markdown = _string(raw.get("source_markdown"), "冻结正文")
    page_id = _string(raw.get("page_id"), "Notion page id")
    content_hash = _string(raw.get("content_hash"), "content hash")
    metadata = _dict(raw.get("snapshot_metadata"))
    title = _string(raw.get("title"), "title")
    images = metadata.get("images")
    if not isinstance(images, list):
        raise BlockedPublishError("博客素材冻结清单无效")
    image_sha: list[str] = []
    image_paths: list[Path] = []
    for item in images:
        entry = _dict(item)
        image_sha.append(_string(entry.get("sha256"), "image sha256"))
        image_paths.append(Path(_string(entry.get("path"), "image path")))
    snapshot = build_snapshot(
        markdown,
        image_sha256=tuple(image_sha),
        cover_sha256=str(metadata.get("cover_sha256", "")),
        title=title,
        summary=str(metadata.get("summary", "")),
        categories=tuple(item for item in metadata.get("categories", []) if isinstance(item, str)),
        image_paths=tuple(image_paths),
    )
    return _PublishContext(page_id, title, content_hash, snapshot, load_snapshot_assets(metadata))


def _dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise BlockedPublishError(f"{field} 无效")
    return value


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int):
        raise BlockedPublishError(f"{field} 无效")
    return value


def _result(result: dict[str, object]) -> BlogPublishResult:
    return BlogPublishResult(
        _string(result.get("article_url"), "article URL"),
        _integer(result.get("pull_request_number"), "PR number"),
        _string(result.get("merge_sha"), "merge SHA"),
    )
