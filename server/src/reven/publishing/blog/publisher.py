"""GitHub Flow invariants shared by the blog publisher."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from reven.integrations.github.client import (
    GitHubBlockedError,
    GitHubPermanentError,
    GitHubTransientError,
)
from reven.jobs.errors import BlockedPublishError, PermanentPublishError, TransientPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.blog.converter import BlogArticle, BlogBrandFields, BlogConverter
from reven.publishing.blog.ports import (
    BlogPublishResult,
    BlogWorkspacePort,
    GitHubApi,
    ResultStore,
)
from reven.publishing.blog.ports import RequiredCheck as RequiredCheck
from reven.publishing.snapshot import build_snapshot
from reven.publishing.wechat.publisher import LeaseLost, load_snapshot_assets

T = TypeVar("T")


class BlogPublisher:
    def __init__(
        self,
        client: GitHubApi,
        workspace: BlogWorkspacePort,
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
        attempt = self.workspace.create_attempt(str(claim.job_id))
        try:
            context = _context(raw)
            default = await self._persist_value(claim, result, "default_branch", self.client.default_branch)
            branch = release_branch(context.page_id, context.content_hash, default)
            await self._save(claim, result, {"branch": branch})
            commit_sha, article_path, post_path = await self._ensure_branch(claim, result, context, branch, attempt)
            pr = await self._ensure_pull_request(claim, result, context.title, post_path, branch, default)
            pr_number = _integer(pr.get("number"), "PR number")
            await self._wait_checks(default, commit_sha)
            merge_sha = await self._ensure_merge(claim, result, pr_number, commit_sha, branch, default)
            await self._wait_pages(claim, result, merge_sha)
            article_url = await self._external(self.client.verify_article(article_path, context.title))
            await self._save(claim, result, {"article_url": article_url})
            return BlogPublishResult(article_url, pr_number, merge_sha)
        finally:
            self.workspace.cleanup_attempt(attempt)

    async def _ensure_branch(
        self,
        claim: JobClaim,
        result: dict[str, object],
        context: "_PublishContext",
        branch: str,
        attempt: Path,
    ) -> tuple[str, str, str]:
        remote = await self._external(self.client.branch(branch))
        persisted_path = result.get("article_path")
        persisted_sha = result.get("commit_sha")
        if remote is not None:
            if not isinstance(persisted_sha, str):
                raise BlockedPublishError("远程发布分支存在但本地 commit SHA 未持久化")
            sha = verify_remote_branch(persisted_sha, remote)
            if not isinstance(persisted_path, str):
                raise BlockedPublishError("远程发布分支存在但文章路径未持久化，请人工核验")
            await self._recover_operation(claim, result, "push")
            return sha, persisted_path, str(result.get("post_path", ""))
        marker = result.get("operation")
        if isinstance(marker, dict) and marker.get("phase") == "push":
            raise BlockedPublishError("Git push 结果无法确认且远程分支不存在，请人工核验")
        await self._assert_lease(claim)
        build_path = await self.workspace.clone_at(attempt / "build", self.remote_url, self.token)
        await self.workspace.prepare(build_path, branch)
        converted = self.converter.write(
            build_path, BlogArticle(context.page_id, context.snapshot, context.assets, context.brand)
        )
        trusted = self.workspace.capture_artifacts(build_path, converted.manifest)
        await self.workspace.build(build_path)
        self.workspace.verify_artifacts(build_path, trusted)
        self.workspace.cleanup_repository(build_path)
        path = await self.workspace.clone_at(attempt / "push", self.remote_url, self.token)
        await self.workspace.switch(path, branch)
        self.workspace.restore_artifacts(path, trusted)
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
            recovered = await self._external(self.client.branch(branch))
            if recovered is None:
                raise BlockedPublishError("Git push 结果不确定，请人工核验") from exc
            verify_remote_branch(sha, recovered)
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
        pulls = await self._external(self.client.pull_requests(branch, base=default))
        existing = select_pull_request(pulls)
        if existing is not None:
            pr = existing
            await self._recover_operation(claim, result, "create_pr")
        else:
            template = await self._external(self.client.pull_request_template(default))
            await self._operation(claim, result, "create_pr")
            try:
                pr = await self._external(
                    self.client.create_pull_request(
                        title=f"feat: publish {' '.join(title.split())[:120]}",
                        head=branch,
                        base=default,
                        body=pull_request_body(template, post_path),
                    )
                )
            except Exception as exc:
                recovered = await self._external(self.client.pull_requests(branch, base=default))
                selected = select_pull_request(recovered)
                if selected is None:
                    raise BlockedPublishError("PR 创建结果不确定，请人工核验") from exc
                pr = selected
            await self._clear_operation(claim, result)
        number = _integer(pr.get("number"), "PR number")
        await self._save(
            claim,
            result,
            {
                "pull_request_number": number,
                "pull_request_url": _pull_request_url(pr, self.remote_url, number),
            },
        )
        return pr

    async def _wait_checks(self, default: str, sha: str) -> None:
        required = await self._external(self.client.required_contexts(default))
        if not required:
            checks_state(required, [], [])
        for _ in range(self.max_polls):
            runs = await self._external(self.client.check_runs(sha))
            statuses = await self._external(self.client.status_contexts(sha))
            state = checks_state(required, runs, statuses)
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
        default: str,
    ) -> str:
        existing = result.get("merge_sha")
        if isinstance(existing, str) and existing:
            await self._recover_operation(claim, result, "merge")
            return existing
        del branch, default
        current = await self._external(self.client.get_pull(number))
        recovered_sha = _merged_pull_sha(current, number)
        if recovered_sha is not None:
            merge_sha = recovered_sha
            await self._save(claim, result, {"merge_sha": merge_sha})
            await self._recover_operation(claim, result, "merge")
            return merge_sha
        await self._operation(claim, result, "merge")
        try:
            merged = await self._external(self.client.merge(number, sha))
            merge_sha = _git_sha(merged.get("sha"), "merge SHA")
        except Exception as exc:
            current = await self._external(self.client.get_pull(number))
            recovered_sha = _merged_pull_sha(current, number)
            if recovered_sha is None:
                raise BlockedPublishError("PR 合并结果不确定，请人工核验") from exc
            merge_sha = recovered_sha
        await self._save(claim, result, {"merge_sha": merge_sha})
        await self._clear_operation(claim, result)
        return merge_sha

    async def _wait_pages(self, claim: JobClaim, result: dict[str, object], merge_sha: str) -> None:
        for _ in range(self.max_polls):
            build = target_pages_build(await self._external(self.client.pages_builds()), merge_sha)
            if build is None:
                await self.sleep(self.poll_interval)
                continue
            state = pages_state(build, merge_sha)
            if state == "success":
                await self._save(claim, result, {"pages_build_id": build.get("id")})
                return
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
        value = await self._external(loader())
        await self._save(claim, result, {key: value})
        return value

    async def _operation(self, claim: JobClaim, result: dict[str, object], phase: str) -> None:
        marker = result.get("operation")
        if isinstance(marker, dict):
            raise BlockedPublishError(f"{marker.get('phase', '外部写')}结果不确定，请人工核验")
        operation_id = await self.store.begin_operation_if_absent(claim, phase)
        if operation_id is None:
            raise BlockedPublishError(f"{phase} 已由其他 worker 发起，等待远端证据恢复")
        result["operation"] = {"id": operation_id, "phase": phase}

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

    @staticmethod
    async def _external(operation: Awaitable[T]) -> T:
        try:
            return await operation
        except GitHubTransientError as exc:
            error = TransientPublishError("GitHub 暂时不可用，请稍后重试")
            setattr(error, "outcome_uncertain", exc.uncertain)
            raise error from exc
        except GitHubBlockedError as exc:
            raise BlockedPublishError("GitHub 权限配置阻塞发布，请检查集成权限") from exc
        except GitHubPermanentError as exc:
            raise PermanentPublishError("GitHub 请求被拒绝，请检查仓库配置") from exc


def release_branch(page_id: str, content_hash: str, default_branch: str) -> str:
    del default_branch
    page = re.sub(r"[^0-9A-Fa-f]", "", page_id)[:8].lower()
    digest = re.fullmatch(r"[0-9a-fA-F]{64}", content_hash)
    if len(page) != 8 or digest is None:
        raise ValueError("page_id 或 content_hash 无效")
    return f"reven/{page}-{content_hash[:12].lower()}"


def checks_state(
    required: tuple[RequiredCheck, ...],
    check_runs: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
) -> str:
    if not required:
        raise BlockedPublishError("默认分支未配置 required check，禁止自动合并")
    values: dict[RequiredCheck, tuple[tuple[str, int, int], str]] = {}
    for index, run in enumerate(check_runs):
        name = run.get("name")
        if isinstance(name, str):
            status = run.get("status")
            app = _dict(run.get("app"))
            app_id = app.get("id") if isinstance(app.get("id"), int) else None
            value = str(run.get("conclusion")) if status == "completed" else "pending"
            order = _event_order(run, index)
            _latest(values, RequiredCheck(name, app_id), order, value)
            _latest(values, RequiredCheck(name), order, value)
    for index, status in enumerate(statuses):
        context = status.get("context")
        if isinstance(context, str):
            order = _event_order(status, index)
            _latest(values, RequiredCheck(context), order, str(status.get("state")))
    relevant = {identity: values.get(identity, (("", 0, 0), "pending"))[1] for identity in required}
    failed = {"failure", "failed", "cancelled", "timed_out", "action_required", "error"}
    if any(value in failed for value in relevant.values()):
        raise BlockedPublishError("required check 失败，禁止自动合并")
    return "success" if all(value == "success" for value in relevant.values()) else "pending"


def _latest(
    values: dict[RequiredCheck, tuple[tuple[str, int, int], str]],
    identity: RequiredCheck,
    order: tuple[str, int, int],
    value: str,
) -> None:
    if order >= values.get(identity, (("", -1, -1), ""))[0]:
        values[identity] = (order, value)


def _event_order(event: dict[str, Any], index: int) -> tuple[str, int, int]:
    timestamp = next(
        (
            value
            for key in ("completed_at", "created_at", "started_at", "updated_at")
            if isinstance(value := event.get(key), str)
        ),
        "",
    )
    event_id = event.get("id")
    return timestamp, event_id if isinstance(event_id, int) else 0, index


def select_pull_request(pulls: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((item for item in pulls if item.get("state") == "open"), None) or next(
        (item for item in pulls if item.get("merged_at")), None
    )


def verify_remote_branch(local_sha: str, branch: dict[str, Any]) -> str:
    remote_sha = _string(_dict(branch.get("commit")).get("sha"), "远程分支 SHA")
    if remote_sha != local_sha:
        raise BlockedPublishError("同名远程分支 commit SHA 冲突，请人工核验")
    return remote_sha


def pages_state(build: dict[str, Any], merge_sha: str) -> str:
    if build.get("commit") != merge_sha:
        return "pending"
    if build.get("status") in {"errored", "cancelled"}:
        raise BlockedPublishError("GitHub Pages 最新构建失败")
    if build.get("status") == "built":
        return "success"
    return "pending"


def target_pages_build(builds: list[dict[str, Any]], merge_sha: str) -> dict[str, Any] | None:
    matches = [build for build in builds if build.get("commit") == merge_sha]
    if not matches:
        return None

    def build_id(build: dict[str, Any]) -> int:
        value = build.get("id")
        return value if isinstance(value, int) else 0

    return max(matches, key=build_id)


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
    brand: BlogBrandFields | None


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
    return _PublishContext(
        page_id, title, content_hash, snapshot, load_snapshot_assets(metadata), _blog_brand(metadata)
    )


def _blog_brand(metadata: dict[str, Any]) -> BlogBrandFields | None:
    fields = metadata.get("blog_fields")
    if not isinstance(fields, dict):
        return None
    author = fields.get("author")
    og_image = fields.get("og_image_url")
    return BlogBrandFields(
        author=author if isinstance(author, str) else "",
        og_image_url=og_image if isinstance(og_image, str) and og_image else None,
    )


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


def _git_sha(value: object, field: str) -> str:
    sha = _string(value, field)
    if re.fullmatch(r"[0-9a-fA-F]{40}", sha) is None:
        raise BlockedPublishError(f"{field} 无效")
    return sha.lower()


def _merged_pull_sha(pull: dict[str, Any], number: int) -> str | None:
    if pull.get("number") != number:
        raise BlockedPublishError("GitHub 返回了错误的 PR")
    if not pull.get("merged_at"):
        return None
    return _git_sha(pull.get("merge_commit_sha"), "merge SHA")


def _pull_request_url(pr: dict[str, Any], remote_url: str, number: int) -> str:
    value = pr.get("html_url")
    if isinstance(value, str) and re.fullmatch(r"https://github\.com/[^/]+/[^/]+/pull/\d+", value):
        return value
    match = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+)\.git", remote_url)
    if match is None:
        raise BlockedPublishError("GitHub remote URL 无效")
    return f"https://github.com/{match.group(1)}/{match.group(2)}/pull/{number}"


def _result(result: dict[str, object]) -> BlogPublishResult:
    return BlogPublishResult(
        _string(result.get("article_url"), "article URL"),
        _integer(result.get("pull_request_number"), "PR number"),
        _string(result.get("merge_sha"), "merge SHA"),
    )
