# Reven 内容发布工作台 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Reven 重建为一个单用户内容发布工作台：Notion 稿件进入“待发布”后，系统按上海时间自动发布博客、生成微信公众号草稿，并通过飞书报告结果。

**Architecture:** 前后端代码分离、统一部署。React 工作台只调用 FastAPI；FastAPI 内部运行数据库驱动的同步器、调度器和发布执行器，所有状态持久化到 Supabase Postgres，不拆独立 Worker，不引入 Redis、对象存储或微服务。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、React、TypeScript、Vite、shadcn/ui、Tailwind CSS 4、pnpm、Doocs Markdown、Jekyll、Docker、Caddy。

---

## 0. 实施约束

### 0.1 分支与提交

- 从当前已包含设计文档和本计划的分支创建 `feat/editorial-publishing-mvp`。
- 不直接修改或推送 `main`。
- 每个任务结束时运行该任务列出的验证命令并创建一个原子 Commit。
- 最终通过 PR 合并到 `main`。

### 0.2 清空边界

用户已经确认现有 ERP/Excel 导入项目可以推倒重来。实施时：

- 删除旧 `bot/`、`packages/`、`poc/`、`server/`、`infra/` 和旧产品文档。
- 删除旧 `.importlinter`、`uv.lock`，重建依赖锁。
- 保留 `.git/`、`.github/`、`.gitignore`。
- 保留 `docs/superpowers/specs/2026-07-29-editorial-publishing-mvp-design.md`。
- 保留本计划 `docs/superpowers/plans/2026-07-29-editorial-publishing-mvp.md`。
- 所有删除都通过 Git 记录，可从历史恢复。

### 0.3 外部系统基线

- Notion API：`2026-03-11`。
- Notion Data Source：`4f7889bf-0a2c-4e3d-ac28-d9beac5cb239`。
- Notion Database：`3301a325-8142-4ba2-9d77-2d8fc96e59b0`。
- Doocs Markdown：固定上游提交 `c37c1d6cc0e0a259de20305b9e4c3b59c7029da7`。
- 博客仓库：`wangyiyang/wangyiyang.github.io`，默认分支从 GitHub API 获取，当前为 `master`。
- Reven 域名：`dev.wangyiyang.cc`。
- 云服务器 SSH：`kk@dev.wangyiyang.cc`。
- 生产端口：Caddy 使用 80/443；保留现有 3000 端口服务；Reven 只暴露 Docker 内网 8000。

### 0.4 最终文件结构

```text
Reven/
├── .github/workflows/ci.yml          # 后端、前端、渲染器、迁移和镜像检查
├── docs/
│   ├── runbook.md                    # 配置、部署、回滚与验收
│   └── superpowers/                  # 设计与实施计划
├── server/
│   ├── pyproject.toml
│   ├── migrations/
│   ├── src/reven/
│   │   ├── api/                      # HTTP 路由和 API Schema
│   │   ├── articles/                 # 稿件模型、仓储与查询
│   │   ├── integrations/             # Notion/GitHub/微信/飞书客户端
│   │   ├── jobs/                     # 发布任务、租约、重试与状态
│   │   ├── publishing/               # 快照、校验、博客、微信、编排
│   │   ├── security/                 # Secret 加密与脱敏
│   │   ├── app.py                    # FastAPI 工厂与 lifespan
│   │   ├── config.py                 # 基础设施环境变量
│   │   └── db.py                     # Async Engine 与 Session
│   └── tests/
├── web/
│   ├── src/components/               # shadcn/ui 与业务组件
│   ├── src/features/articles/        # 稿件列表和详情
│   ├── src/features/integrations/    # 集成设置
│   ├── src/lib/                      # API、剪贴板和时间格式
│   └── src/routes/                   # 三个页面路由
├── renderer/
│   ├── src/cli.ts                    # stdin JSON → stdout JSON
│   ├── src/render.ts                 # Doocs 渲染与 CSS 内联
│   └── tests/
├── vendor/doocs-md/                  # 固定版本的必要上游源码及许可证
├── infra/
│   ├── caddy/Caddyfile
│   ├── compose/docker-compose.yml
│   ├── docker/Dockerfile
│   ├── docker/entrypoint.sh
│   └── test/docker-compose.yml
├── .env.example
├── package.json
├── pnpm-workspace.yaml
└── pyproject.toml
```

单个函数保持在 50 行以内；单个业务文件接近 500 行时，按上面的职责边界继续拆分。

## Task 1：清理旧产品并建立最小可运行骨架

**Files:**

- Delete: `bot/`
- Delete: `packages/`
- Delete: `poc/`
- Delete: `server/`
- Delete: `infra/`
- Delete: `.importlinter`
- Delete: `docs/adr/`
- Delete: `docs/independent-research/`
- Delete: `docs/README.md`
- Delete: `docs/erp-platform-spec.md`
- Delete: `docs/flexible-excel-import-design.md`
- Delete: `docs/future-product-roadmap.md`
- Delete: `docs/prd.md`
- Delete: `docs/product-storyline.md`
- Delete: `docs/workspace-analysis.md`
- Delete: `docs/yonyou-replacement-architecture.md`
- Modify: `.gitignore`
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`
- Create: `server/pyproject.toml`
- Create: `server/src/reven/__init__.py`
- Create: `server/src/reven/app.py`
- Create: `server/tests/test_health.py`
- Create: `.env.example`

- [ ] **Step 1: 创建实施分支并精确删除旧产品文件**

```bash
git switch -c feat/editorial-publishing-mvp
git rm -r bot packages poc server infra .importlinter docs/adr docs/independent-research
git rm docs/README.md docs/erp-platform-spec.md docs/flexible-excel-import-design.md
git rm docs/future-product-roadmap.md docs/prd.md docs/product-storyline.md
git rm docs/workspace-analysis.md docs/yonyou-replacement-architecture.md uv.lock
```

Expected: `git status --short` 只显示上述删除和后续新骨架文件，不删除 `docs/superpowers/`。

- [ ] **Step 2: 写最小后端依赖和测试配置**

`pyproject.toml`：

```toml
[project]
name = "reven"
version = "0.1.0"
requires-python = ">=3.12"

[tool.uv.workspace]
members = ["server"]

[dependency-groups]
dev = [
  "mypy>=1.17,<2",
  "pytest>=8.4,<9",
  "pytest-cov>=6.2,<7",
  "respx>=0.22,<1",
  "ruff>=0.12,<1",
]

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["reven"]

[tool.pytest.ini_options]
testpaths = ["server/tests"]
pythonpath = ["server/src"]
addopts = "-q"
```

`server/pyproject.toml`：

```toml
[project]
name = "reven-server"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "alembic>=1.16,<2",
  "asyncpg>=0.30,<1",
  "beautifulsoup4>=4.13,<5",
  "cryptography>=45,<46",
  "fastapi>=0.116,<1",
  "httpx>=0.28,<1",
  "markdown-it-py>=3,<4",
  "pydantic-settings>=2.10,<3",
  "pyyaml>=6,<7",
  "sqlalchemy[asyncio]>=2.0.41,<3",
  "uvicorn[standard]>=0.35,<1",
]

[tool.uv]
package = true

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Run:

```bash
uv lock
uv sync --all-packages
```

Expected: 新 `uv.lock` 生成且 `uv sync` 退出码为 0。

- [ ] **Step 3: 先写失败的健康检查测试**

`server/tests/test_health.py`：

```python
from fastapi.testclient import TestClient

from reven.app import create_app


def test_health_returns_service_status() -> None:
    with TestClient(create_app(start_background_tasks=False)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"service": "reven", "status": "ok"}
```

Run:

```bash
uv run pytest server/tests/test_health.py -q
```

Expected: FAIL，原因是 `reven.app` 尚不存在。

- [ ] **Step 4: 实现最小 FastAPI 工厂**

`server/src/reven/__init__.py`：

```python
"""Reven editorial publishing workbench."""
```

`server/src/reven/app.py`：

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


def create_app(*, start_background_tasks: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _ = start_background_tasks
        yield

    app = FastAPI(title="Reven", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"service": "reven", "status": "ok"}

    return app


app = create_app()
```

同时将 `.gitignore` 中旧 POC 规则替换为：

```gitignore
.DS_Store
.env
.env.*
!.env.example
.venv/
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
node_modules/
dist/
coverage/
htmlcov/
.vite/
.data/
```

`.env.example`：

```dotenv
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/postgres?ssl=require
REVEN_MASTER_KEY=base64-encoded-32-byte-key
```

同时把 `.github/workflows/ci.yml` 暂时收敛为只检查当前可运行的后端骨架：

```yaml
name: CI

on:
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv python install 3.12
      - run: uv sync --frozen --all-packages
      - run: uv run ruff check server
      - run: uv run ruff format --check server
      - run: uv run mypy server/src
      - run: uv run pytest server/tests
```

- [ ] **Step 5: 验证骨架并提交**

Run:

```bash
uv run pytest server/tests/test_health.py -q
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
git diff --check
```

Expected: 全部退出码为 0，Pytest 显示 `1 passed`。

```bash
git add -A
git commit -m "chore: rebuild reven project skeleton"
```

## Task 2：定义配置、领域状态、渠道和上海时间规则

**Files:**

- Create: `server/src/reven/config.py`
- Create: `server/src/reven/domain.py`
- Create: `server/src/reven/scheduling.py`
- Create: `server/tests/test_config.py`
- Create: `server/tests/test_domain.py`
- Create: `server/tests/test_scheduling.py`
- Modify: `.env.example`

- [ ] **Step 1: 写配置和领域规则的失败测试**

`server/tests/test_domain.py`：

```python
import pytest

from reven.domain import TargetChannel, parse_target_channels


def test_empty_channels_default_to_blog_and_wechat() -> None:
    result = parse_target_channels([])
    assert result.channels == frozenset({TargetChannel.BLOG, TargetChannel.WECHAT})
    assert result.used_default is True


def test_unsupported_channel_is_explicit() -> None:
    result = parse_target_channels(["个人博客", "掘金"])
    assert result.channels == frozenset({TargetChannel.BLOG})
    assert result.unsupported == ("掘金",)


@pytest.mark.parametrize("raw", [["微信公众号"], ["个人博客", "微信公众号"]])
def test_supported_channels_are_preserved(raw: list[str]) -> None:
    assert parse_target_channels(raw).unsupported == ()
```

`server/tests/test_scheduling.py`：

```python
from datetime import UTC, datetime

from reven.scheduling import resolve_scheduled_at


def test_date_only_defaults_to_0801_shanghai() -> None:
    assert resolve_scheduled_at("2026-08-01") == datetime(2026, 8, 1, 0, 1, tzinfo=UTC)


def test_datetime_uses_explicit_offset() -> None:
    assert resolve_scheduled_at("2026-08-01T09:30:00+08:00") == datetime(
        2026, 8, 1, 1, 30, tzinfo=UTC
    )


def test_missing_plan_runs_now() -> None:
    now = datetime(2026, 7, 29, 7, 0, tzinfo=UTC)
    assert resolve_scheduled_at(None, now=now) == now
```

Run:

```bash
uv run pytest server/tests/test_domain.py server/tests/test_scheduling.py -q
```

Expected: FAIL，原因是模块尚不存在。

- [ ] **Step 2: 实现明确的领域枚举与渠道解析**

`server/src/reven/domain.py`：

```python
from dataclasses import dataclass
from enum import StrEnum


class TargetChannel(StrEnum):
    BLOG = "个人博客"
    WECHAT = "微信公众号"


class AutomationStatus(StrEnum):
    NOT_STARTED = "未开始"
    WAITING = "等待中"
    PROCESSING = "处理中"
    BLOCKED = "阻塞"
    FAILED = "失败"
    COMPLETED = "已完成"


class BlogStage(StrEnum):
    PENDING = "待处理"
    CONVERTING = "转换中"
    BUILDING = "构建中"
    PR_CREATED = "PR 已创建"
    WAITING_CI = "等待 CI"
    MERGING = "合并中"
    ONLINE = "已上线"
    FAILED = "失败"


class WechatStage(StrEnum):
    PENDING = "待处理"
    RENDERING = "渲染中"
    UPLOADING_IMAGES = "上传图片"
    UPLOADING_COVER = "上传封面"
    CREATING_DRAFT = "创建草稿"
    DRAFT_CREATED = "草稿已生成"
    FAILED = "失败"


class JobStatus(StrEnum):
    WAITING = "等待中"
    PROCESSING = "处理中"
    BLOCKED = "阻塞"
    FAILED = "失败"
    COMPLETED = "已完成"
    CANCELLED = "已取消"


@dataclass(frozen=True)
class ChannelSelection:
    channels: frozenset[TargetChannel]
    unsupported: tuple[str, ...]
    used_default: bool


def parse_target_channels(raw_channels: list[str]) -> ChannelSelection:
    if not raw_channels:
        return ChannelSelection(
            channels=frozenset({TargetChannel.BLOG, TargetChannel.WECHAT}),
            unsupported=(),
            used_default=True,
        )
    supported: set[TargetChannel] = set()
    unsupported: list[str] = []
    for raw in raw_channels:
        try:
            supported.add(TargetChannel(raw))
        except ValueError:
            unsupported.append(raw)
    return ChannelSelection(frozenset(supported), tuple(unsupported), False)
```

- [ ] **Step 3: 实现 UTC 存储和上海时间计算**

`server/src/reven/scheduling.py`：

```python
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_LOCAL_TIME = time(hour=8, minute=1)


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def resolve_scheduled_at(raw: str | None, *, now: datetime | None = None) -> datetime:
    current = now or utc_now()
    if raw is None:
        return current.astimezone(UTC)
    if "T" not in raw:
        local = datetime.combine(date.fromisoformat(raw), DEFAULT_LOCAL_TIME, tzinfo=SHANGHAI)
        return local.astimezone(UTC)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(UTC)
```

- [ ] **Step 4: 实现只承载基础设施 Secret 的环境配置**

`server/src/reven/config.py`：

```python
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    reven_master_key: SecretStr
    public_base_url: str = "https://dev.wangyiyang.cc"
    sync_interval_seconds: int = 60
    scheduler_interval_seconds: int = 5
    job_lease_seconds: int = 120
    job_data_dir: str = "/data/jobs"
    renderer_command: str = "node /app/renderer/dist/cli.mjs"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

`server/tests/test_config.py`：

```python
from reven.config import Settings


def test_settings_read_only_infrastructure_secrets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")
    assert settings.public_base_url == "https://dev.wangyiyang.cc"
    assert "notion" not in Settings.model_fields
    assert "wechat_app_secret" not in Settings.model_fields
```

`.env.example` 只列名称和生成方法，不包含真实值：

```dotenv
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/postgres?ssl=require
REVEN_MASTER_KEY=base64-encoded-32-byte-key
PUBLIC_BASE_URL=https://dev.wangyiyang.cc
SYNC_INTERVAL_SECONDS=60
SCHEDULER_INTERVAL_SECONDS=5
JOB_LEASE_SECONDS=120
JOB_DATA_DIR=/data/jobs
RENDERER_COMMAND=node /app/renderer/dist/cli.mjs
REVEN_BASIC_AUTH_USER=replace-me
CADDY_BASIC_AUTH_HASH=replace-with-caddy-hash-password-output
```

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/test_domain.py server/tests/test_scheduling.py -q
uv run ruff check server
uv run mypy server/src
```

Expected: Pytest 显示全部通过，静态检查退出码为 0。

```bash
git add .env.example server
git commit -m "feat: add publishing domain and schedule rules"
```

## Task 3：建立 PostgreSQL 模型、迁移与任务租约

**Files:**

- Create: `server/src/reven/db.py`
- Create: `server/src/reven/articles/models.py`
- Create: `server/src/reven/articles/repository.py`
- Create: `server/src/reven/jobs/models.py`
- Create: `server/src/reven/jobs/repository.py`
- Create: `server/src/reven/integrations/models.py`
- Create: `server/src/reven/integrations/repository.py`
- Create: `server/src/reven/system/models.py`
- Create: `server/migrations/alembic.ini`
- Create: `server/migrations/env.py`
- Create: `server/migrations/versions/0001_initial.py`
- Create: `infra/test/docker-compose.yml`
- Create: `server/tests/conftest.py`
- Create: `server/tests/integration/test_job_repository.py`

- [ ] **Step 1: 建立隔离的测试 PostgreSQL 并写失败的租约测试**

`infra/test/docker-compose.yml`：

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: reven_test
      POSTGRES_USER: reven_test
      POSTGRES_PASSWORD: reven_test
    ports:
      - "127.0.0.1:55432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U reven_test -d reven_test"]
      interval: 2s
      timeout: 2s
      retries: 20
```

`server/tests/integration/test_job_repository.py`：

```python
from datetime import UTC, datetime, timedelta

import pytest

from reven.articles.models import Article
from reven.domain import JobStatus
from reven.jobs.repository import JobRepository


@pytest.mark.anyio
async def test_claim_due_job_sets_processing_lease(db_session) -> None:  # type: ignore[no-untyped-def]
    article = Article(
        notion_page_id="11111111-1111-1111-1111-111111111111",
        notion_url="https://www.notion.so/11111111111111111111111111111111",
        title="测试稿件",
        notion_status="待发布",
        automation_status="等待中",
        notion_last_edited_at=datetime.now(tz=UTC),
        last_synced_at=datetime.now(tz=UTC),
    )
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="a" * 64,
        target_channels=["个人博客"],
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    await db_session.commit()

    claimed = await repository.claim_next(lease_seconds=120)

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.overall_status == JobStatus.PROCESSING
    assert claimed.lease_expires_at is not None
```

Run:

```bash
docker compose -f infra/test/docker-compose.yml up -d --wait
TEST_DATABASE_URL=postgresql+asyncpg://reven_test:reven_test@127.0.0.1:55432/reven_test \
  uv run pytest server/tests/integration/test_job_repository.py -q
```

Expected: FAIL，原因是模型、Fixture 和 Repository 尚不存在。

- [ ] **Step 2: 实现 Async Engine 和可替换 Session**

`server/src/reven/db.py`：

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from reven.config import Settings


class Base(DeclarativeBase):
    pass


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
```

- [ ] **Step 3: 实现四个核心模型**

模型使用 UUID 主键、`TIMESTAMP WITH TIME ZONE`、PostgreSQL `JSONB`。关键约束：

```python
class PublicationJob(Base):
    __tablename__ = "publication_jobs"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "content_hash",
            "target_channels_hash",
            name="uq_job_article_version_channels",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id"))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    target_channels: Mapped[list[str]] = mapped_column(JSONB)
    target_channels_hash: Mapped[str] = mapped_column(String(64))
    source_markdown: Mapped[str | None] = mapped_column(Text)
    snapshot_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    wechat_html: Mapped[str | None] = mapped_column(Text)
    overall_status: Mapped[str] = mapped_column(String(32), index=True)
    blog_status: Mapped[str] = mapped_column(String(32))
    wechat_status: Mapped[str] = mapped_column(String(32))
    blog_result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    wechat_result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    notification_state: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    attempt_count: Mapped[int] = mapped_column(default=0)
    blog_attempt_count: Mapped[int] = mapped_column(default=0)
    wechat_attempt_count: Mapped[int] = mapped_column(default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

Job 分两阶段：

- 计划阶段：`content_hash/source_markdown` 为空，可调整计划时间或取消。
- 执行阶段：到期后重新读取 Notion，校验成功才冻结快照并写入哈希。

迁移增加一个 PostgreSQL partial unique index，确保每篇稿件最多只有一个未冻结的活动计划：

```python
Index(
    "uq_one_unfrozen_job_per_article",
    "article_id",
    unique=True,
    postgresql_where=text(
        "content_hash IS NULL AND overall_status IN ('等待中', '处理中', '阻塞')"
    ),
)
```

`Article` 的字段固定为：

```python
class Article(Base):
    __tablename__ = "articles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    notion_page_id: Mapped[str] = mapped_column(String(36), unique=True)
    notion_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    notion_status: Mapped[str] = mapped_column(String(32), index=True)
    automation_status: Mapped[str] = mapped_column(
        String(32), index=True, default="未开始"
    )
    target_channels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cover_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    notion_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    notion_last_edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
```

`PublicationJob` 还必须包含：

```python
blog_error: Mapped[str | None] = mapped_column(Text)
wechat_error: Mapped[str | None] = mapped_column(Text)
started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), default=utc_now, onupdate=utc_now
)
```

集成和系统状态字段固定为：

```python
class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), unique=True)
    public_config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    connection_status: Mapped[str] = mapped_column(String(32), default="未测试")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
```

- [ ] **Step 4: 实现原子任务领取和首个 Alembic 迁移**

`JobRepository.claim_next()` 必须在一个事务中使用 PostgreSQL 行锁：

```python
async def claim_next(self, *, lease_seconds: int) -> PublicationJob | None:
    now = datetime.now(tz=UTC)
    statement = (
        select(PublicationJob)
        .where(
            PublicationJob.overall_status.in_(["等待中", "处理中"]),
            PublicationJob.scheduled_at <= now,
            or_(
                PublicationJob.lease_expires_at.is_(None),
                PublicationJob.lease_expires_at < now,
            ),
        )
        .order_by(PublicationJob.scheduled_at, PublicationJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = await self.session.scalar(statement)
    if job is None:
        return None
    job.overall_status = "处理中"
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    await self.session.flush()
    return job
```

`0001_initial.py` 创建四张表、唯一键和到期任务索引。测试 Fixture 每次测试前运行迁移、每次测试后清理数据，不用生产 Supabase。

`server/tests/conftest.py` 为集成测试提供真实异步事务：

```python
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    database_url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE publication_jobs, articles, integrations, system_state "
                "RESTART IDENTITY CASCADE"
            )
        )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
```

- [ ] **Step 5: 验证迁移、并发领取与提交**

Run:

```bash
DATABASE_URL=postgresql+asyncpg://reven_test:reven_test@127.0.0.1:55432/reven_test \
  uv run alembic -c server/migrations/alembic.ini upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://reven_test:reven_test@127.0.0.1:55432/reven_test \
  uv run pytest server/tests/integration -q
uv run ruff check server
uv run mypy server/src
```

Expected: 迁移成功；两个并发领取者不能拿到同一任务；全部测试通过。

```bash
git add server infra/test
git commit -m "feat: add publishing persistence and job leases"
```

## Task 4：实现 Secret 加密、脱敏和集成设置 API

**Files:**

- Create: `server/src/reven/security/secrets.py`
- Create: `server/src/reven/security/redaction.py`
- Create: `server/src/reven/integrations/service.py`
- Create: `server/src/reven/api/schemas/integrations.py`
- Create: `server/src/reven/api/routes/integrations.py`
- Create: `server/tests/security/test_secrets.py`
- Create: `server/tests/api/test_integrations.py`

- [ ] **Step 1: 写 AES-256-GCM 和 API 不回传明文的失败测试**

```python
import base64


def test_secret_box_round_trip_and_random_nonce() -> None:
    master_key = base64.urlsafe_b64encode(b"k" * 32).decode()
    box = SecretBox.from_base64(master_key)
    first = box.encrypt({"token": "notion-secret"})
    second = box.encrypt({"token": "notion-secret"})

    assert first != second
    assert box.decrypt(first) == {"token": "notion-secret"}


def test_integration_response_never_contains_secret(client) -> None:  # type: ignore[no-untyped-def]
    response = client.put(
        "/api/integrations/notion",
        json={
            "public_config": {"data_source_id": "source-id"},
            "secret": {"token": "notion-secret"},
        },
    )

    body = response.json()
    assert body["secret_configured"] is True
    assert "notion-secret" not in response.text
    assert "encrypted_secret" not in body
```

Run:

```bash
uv run pytest server/tests/security/test_secrets.py server/tests/api/test_integrations.py -q
```

Expected: FAIL，原因是 `SecretBox` 和 API 尚不存在。

- [ ] **Step 2: 实现版本化 AES-256-GCM 信封**

`server/src/reven/security/secrets.py`：

```python
import base64
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class SecretBox:
    key: bytes

    @classmethod
    def from_base64(cls, encoded: str) -> "SecretBox":
        key = base64.urlsafe_b64decode(encoded)
        if len(key) != 32:
            raise ValueError("REVEN_MASTER_KEY 必须解码为 32 字节")
        return cls(key)

    def encrypt(self, value: dict[str, str]) -> str:
        nonce = os.urandom(12)
        plaintext = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext, b"reven:v1")
        envelope = base64.urlsafe_b64encode(nonce + ciphertext).decode()
        return f"v1:{envelope}"

    def decrypt(self, envelope: str) -> dict[str, str]:
        version, encoded = envelope.split(":", maxsplit=1)
        if version != "v1":
            raise ValueError("不支持的 Secret 密文版本")
        payload = base64.urlsafe_b64decode(encoded)
        plaintext = AESGCM(self.key).decrypt(payload[:12], payload[12:], b"reven:v1")
        decoded = json.loads(plaintext)
        return {str(key): str(value) for key, value in decoded.items()}
```

- [ ] **Step 3: 实现统一脱敏**

`redact()` 递归处理字典、列表和异常文本，键名命中 `token`、`secret`、`password`、`authorization`、`webhook` 时替换为 `***`；文本中命中已知 Secret 值时也替换。

```python
SENSITIVE_KEYS = frozenset({"token", "secret", "password", "authorization", "webhook_url"})


def redact_mapping(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "***" if key.lower() in SENSITIVE_KEYS else redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    return value
```

- [ ] **Step 4: 实现写入、替换、删除但不读取 Secret 的 API**

路由：

```text
GET    /api/integrations
GET    /api/integrations/{provider}
PUT    /api/integrations/{provider}
DELETE /api/integrations/{provider}/secret
POST   /api/integrations/{provider}/test
```

`PUT` 语义：

- `secret` 缺省：保留现有密文。
- `secret` 为对象：加密并替换。
- 删除必须调用独立 DELETE。
- 响应只返回 `secret_configured` 和形如 `已配置 · ****abcd` 的不可逆提示。
- 公共配置或 Secret 变化后，将 `connection_status` 重置为 `未测试`。
- `provider` 只允许 `notion`、`github`、`wechat`、`feishu`。
- 每个 provider 使用独立 Pydantic Schema 且 `extra="forbid"`：Notion ID 必须是 UUID，GitHub owner/repo 必须匹配仓库 slug，AppID 和文本长度受限，Webhook 必须是飞书 HTTPS 地址。
- 连接测试通过注册表分发；具体适配器在后续任务注入。

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/security server/tests/api/test_integrations.py -q
uv run ruff check server
uv run mypy server/src
```

Expected: 加密随机 nonce、篡改检测、删除语义和不泄密测试全部通过。

```bash
git add server
git commit -m "feat: secure integration credentials"
```

## Task 5：实现 Notion 客户端、字段初始化和页面映射

**Files:**

- Create: `server/src/reven/integrations/notion/client.py`
- Create: `server/src/reven/integrations/notion/models.py`
- Create: `server/src/reven/integrations/notion/mapper.py`
- Create: `server/src/reven/integrations/notion/schema.py`
- Create: `server/tests/fixtures/notion/data_source.json`
- Create: `server/tests/fixtures/notion/page.json`
- Create: `server/tests/integrations/notion/test_client.py`
- Create: `server/tests/integrations/notion/test_mapper.py`
- Create: `server/tests/integrations/notion/test_schema.py`

- [ ] **Step 1: 用脱敏固定响应写失败的契约测试**

```python
def test_page_mapper_reads_editorial_fields(load_fixture) -> None:  # type: ignore[no-untyped-def]
    page = load_fixture("notion/page.json")
    mapped = map_notion_page(page)

    assert mapped.page_id == "11111111-1111-1111-1111-111111111111"
    assert mapped.title == "测试稿件"
    assert mapped.status == "待发布"
    assert mapped.target_channels == ["个人博客", "微信公众号"]
    assert mapped.planned_raw == "2026-08-01"
    assert mapped.cover.url == "https://files.example.test/cover.png"
```

客户端契约测试用 `respx` 验证：

```python
assert request.headers["Notion-Version"] == "2026-03-11"
assert request.url.path == f"/v1/data_sources/{data_source_id}/query"
```

Run:

```bash
uv run pytest server/tests/integrations/notion -q
```

Expected: FAIL，原因是 Notion 模块尚不存在。

- [ ] **Step 2: 实现只通过 HTTPS 访问的 NotionClient**

```python
class NotionClient:
    API_VERSION = "2026-03-11"

    def __init__(self, token: str, http: httpx.AsyncClient) -> None:
        self.http = http
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    async def query_data_source(
        self,
        data_source_id: str,
        *,
        start_cursor: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"page_size": 100, "result_type": "page"}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return await self._request(
            "POST",
            f"/v1/data_sources/{data_source_id}/query",
            json=payload,
        )

    async def retrieve_page_markdown(self, page_id: str) -> str:
        result = await self._request("GET", f"/v1/pages/{page_id}/markdown")
        return str(result["markdown"])
```

`_request()` 对 429 使用 `Retry-After`，对 401/403/404 返回明确的配置错误，对超时和 5xx 返回临时错误；响应正文必须先脱敏再记录。

- [ ] **Step 3: 实现字段映射与严格校验**

`MappedNotionPage` 是不可变 dataclass，字段包括：

```python
@dataclass(frozen=True)
class MappedNotionPage:
    page_id: str
    url: str
    title: str
    status: str
    automation_status: str | None
    target_channels: list[str]
    planned_raw: str | None
    categories: list[str]
    summary: str
    cover: NotionFile | None
    last_edited_at: datetime
```

映射器按属性 `type` 读取，不依赖属性数组位置；缺少可选属性返回空值；字段类型不符时返回包含字段名的 `NotionSchemaError`。

- [ ] **Step 4: 实现显式、幂等的 Notion 字段初始化**

新增有副作用的端点：

```text
POST /api/integrations/notion/bootstrap-schema
```

调用 `PATCH /v1/data_sources/{data_source_id}`，请求只增加或补齐：

```json
{
  "properties": {
    "封面": {"files": {}},
    "自动化状态": {
      "select": {
        "options": [
          {"name": "未开始", "color": "gray"},
          {"name": "等待中", "color": "blue"},
          {"name": "处理中", "color": "yellow"},
          {"name": "阻塞", "color": "orange"},
          {"name": "失败", "color": "red"},
          {"name": "已完成", "color": "green"}
        ]
      }
    },
    "失败原因": {"rich_text": {}}
  }
}
```

同时读取现有 `状态` Status 配置，仅在缺失时追加 `待发布` 和 `已交付`；绝不删除、重命名或重新着色现有选项。连接测试仍只调用 Retrieve Data Source，不调用初始化。

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/integrations/notion -q
uv run ruff check server
uv run mypy server/src
```

Expected: 分页、字段映射、状态追加幂等和错误分类测试全部通过。

```bash
git add server
git commit -m "feat: add notion editorial integration"
```

## Task 6：实现 Notion 同步、稿件索引和自动解除阻塞

**Files:**

- Create: `server/src/reven/articles/service.py`
- Create: `server/src/reven/integrations/notion/sync.py`
- Create: `server/tests/articles/test_service.py`
- Create: `server/tests/integrations/notion/test_sync.py`

- [ ] **Step 1: 写分页 Upsert 和取消等待任务的失败测试**

```python
@pytest.mark.anyio
async def test_sync_upserts_articles_and_cancels_waiting_job_when_status_changes(
    sync_service,
    notion_pages,
) -> None:  # type: ignore[no-untyped-def]
    notion_pages.set_status("待发布")
    await sync_service.sync_once()
    assert await sync_service.count_articles() == 1
    assert await sync_service.count_waiting_jobs() == 1

    notion_pages.set_status("撰写中")
    await sync_service.sync_once()

    article = await sync_service.get_article()
    assert article.notion_status == "撰写中"
    assert await sync_service.count_cancelled_jobs() == 1
```

Run:

```bash
uv run pytest server/tests/integrations/notion/test_sync.py -q
```

Expected: FAIL，原因是同步服务尚不存在。

- [ ] **Step 2: 实现 ArticleRepository 的幂等 Upsert**

Upsert 唯一键为 `notion_page_id`；每次同步只更新 Notion 索引字段，不覆盖已成功的渠道结果。`last_synced_at` 使用 UTC。

```python
async def upsert_from_notion(self, page: MappedNotionPage) -> Article:
    article = await self.get_by_notion_page_id(page.page_id)
    if article is None:
        article = Article(notion_page_id=page.page_id)
        self.session.add(article)
    article.title = page.title
    article.notion_status = page.status
    article.target_channels = page.target_channels
    article.planned_at = (
        resolve_scheduled_at(page.planned_raw) if page.planned_raw else None
    )
    article.cover_metadata = asdict(page.cover) if page.cover else {}
    article.notion_last_edited_at = page.last_edited_at
    article.last_synced_at = utc_now()
    await self.session.flush()
    return article
```

- [ ] **Step 3: 实现全量分页同步和单页同步**

`NotionSyncService`：

- 遍历全部 `has_more/next_cursor`。
- 每页在独立数据库事务中 Upsert，避免长事务。
- `待发布` 稿件创建或更新一个未冻结计划 Job；此时不读取正文、不生成内容哈希。
- 仅 `等待中` 的未冻结 Job 允许让 `scheduled_at` 和渠道跟随 Notion 更新；`处理中` 的 Job 不再被同步器修改。
- 没有计划日期时，首次创建 Job 使用当时的 `now`；后续同步不反复向后移动该执行时间。
- 稿件存在 `等待中/处理中/阻塞/失败` 的活动 Job 时禁止再创建计划；修复后继续原 Job。
- 仍处于 `待发布` 的阻塞 Job 在后续同步中回到一次“等待校验”；校验仍失败时保持阻塞，通知指纹不变则不重复发送。
- 未开始且离开 `待发布` 的任务标记 `已取消`。
- `阻塞` 稿件仍处于 `待发布` 时重新校验，允许自动恢复。
- 同步游标和最后成功时间写入 `system_state`。
- 单条页面异常只记录该条错误并继续，认证或数据源级错误终止本轮。

- [ ] **Step 4: 将立即同步作为 API 命令**

```text
POST /api/sync/notion
POST /api/articles/{article_id}/sync
```

API 只触发一次同步并返回统计，不执行发布长任务：

```json
{"created": 1, "updated": 55, "failed": 0, "duration_ms": 842}
```

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/articles server/tests/integrations/notion/test_sync.py -q
uv run ruff check server
uv run mypy server/src
```

Expected: 分页、Upsert、取消和单条错误隔离全部通过。

```bash
git add server
git commit -m "feat: synchronize notion editorial articles"
```

## Task 7：实现内容快照、发布前校验和幂等任务冻结

**Files:**

- Create: `server/src/reven/publishing/snapshot.py`
- Create: `server/src/reven/publishing/assets.py`
- Create: `server/src/reven/publishing/validation.py`
- Create: `server/src/reven/jobs/service.py`
- Create: `server/tests/publishing/test_snapshot.py`
- Create: `server/tests/publishing/test_assets.py`
- Create: `server/tests/publishing/test_validation.py`
- Create: `server/tests/jobs/test_service.py`

- [ ] **Step 1: 写签名图片 URL 不影响内容哈希的失败测试**

```python
def test_signed_image_query_does_not_change_content_hash() -> None:
    first = "正文\n![图](https://files.notion.so/a.png?X-Amz-Signature=one)"
    second = "正文\n![图](https://files.notion.so/a.png?X-Amz-Signature=two)"

    first_snapshot = build_snapshot(
        first,
        image_sha256=("a" * 64,),
        cover_sha256="b" * 64,
    )
    second_snapshot = build_snapshot(
        second,
        image_sha256=("a" * 64,),
        cover_sha256="b" * 64,
    )

    assert first_snapshot.markdown == "正文\n![图](reven-asset://image/1)"
    assert first_snapshot.content_hash == second_snapshot.content_hash
```

再写校验测试：

```python
def test_missing_cover_blocks_all_channels(valid_candidate) -> None:  # type: ignore[no-untyped-def]
    candidate = replace(valid_candidate, cover=None)
    result = validate_candidate(candidate)
    assert result.is_valid is False
    assert result.errors[0].code == "cover_missing"
```

Run:

```bash
uv run pytest server/tests/publishing server/tests/jobs/test_service.py -q
```

Expected: FAIL，原因是快照和校验服务尚不存在。

- [ ] **Step 2: 实现稳定的 Markdown 快照**

`AssetMaterializer` 先把正文图片和第一张封面下载到 `/data/jobs/{job_id}/snapshot/`，对每个文件计算 SHA-256。下载器必须：

- 只允许 `https`。
- DNS 解析后拒绝回环、私网和链路本地地址；每次重定向后重新校验。
- 单文件不超过 10 MB，单 Job 不超过 50 MB。
- 校验 MIME 和真实文件头。
- 只生成顺序文件名，不采用外部文件名或路径。
- 任一正文图片或封面下载失败时返回阻塞错误，不能生成不完整快照。

`build_snapshot()` 使用 `markdown-it-py` token 定位图片，按出现顺序替换为 `reven-asset://image/{n}`，并保存图片顺序、原始 URL、文件路径和 SHA-256。内容哈希输入包括：

```python
hash_payload = {
    "title": title.strip(),
    "summary": summary.strip(),
    "categories": sorted(categories),
    "markdown": canonical_markdown.replace("\r\n", "\n").strip(),
    "image_sha256": list(image_sha256),
    "cover_sha256": cover_sha256,
}
content_hash = sha256(
    json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode()
).hexdigest()
```

禁止把 Notion 签名参数、执行时间、临时路径或随机 ID 放入哈希。相同文件的新签名 URL 不改变哈希；正文图片或封面文件内容变化必须改变哈希。

- [ ] **Step 3: 实现结构化发布前校验**

校验器返回 `ValidationResult(errors: tuple[ValidationError, ...])`，一次报告全部问题：

- 标题、正文非空。
- 封面存在且能通过安全下载器完整下载。
- 每张正文图片都能通过安全下载器完整下载。
- 渠道只含博客/微信。
- 对应集成已配置且最近连接测试成功。
- 微信标题、作者、摘要和正文满足当前接口限制。
- 飞书异常只产生 warning，不产生 blocking error。

错误包含稳定 `code`、用户可读 `message` 和 `field`，不包含 Secret 或完整外部响应。

- [ ] **Step 4: 实现任务创建唯一键和阻塞回写**

`PublicationJobService.prepare(job_id)`：

1. 重新获取最新 Notion page + markdown。
2. 映射、解析渠道和计划时间。
3. 安全下载正文图片和封面，执行校验。
4. 校验失败：将当前计划 Job 标为阻塞，更新 Article 和 Notion 的 `自动化状态=阻塞`、`失败原因`。
5. 校验成功：生成快照。
6. 对排序后的渠道 JSON 求 `target_channels_hash`。
7. 将内容哈希、渠道哈希和快照原子写入当前 Job，任务从“计划阶段”进入“执行阶段”。
8. 如果唯一键已存在，取消当前未冻结 Job 并返回已有 Job，不重复发布。
9. 冻结成功后把 Notion `自动化状态` 更新为 `处理中`。

数据库唯一冲突必须捕获后重新查询已有 Job，不能返回 500。任务开始后不再因 Notion 的计划时间或渠道变化修改当前快照。

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/publishing server/tests/jobs -q
uv run ruff check server
uv run mypy server/src
```

Expected: 内容哈希、校验聚合、默认渠道、唯一冲突和脱敏错误测试全部通过。

```bash
git add server
git commit -m "feat: freeze validated publication snapshots"
```

## Task 8：实现单进程调度器、退避重试和重启恢复

**Files:**

- Create: `server/src/reven/jobs/errors.py`
- Create: `server/src/reven/jobs/retry.py`
- Create: `server/src/reven/jobs/runner.py`
- Modify: `server/src/reven/app.py`
- Create: `server/tests/jobs/test_retry.py`
- Create: `server/tests/jobs/test_runner.py`
- Modify: `server/tests/test_health.py`

- [ ] **Step 1: 写错误分类、三次重试和取消 lifespan 的失败测试**

```python
@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 30), (2, 120), (3, None)],
)
def test_transient_retry_schedule(attempt: int, expected: int | None) -> None:
    assert retry_delay_seconds(TransientPublishError("timeout"), attempt) == expected


def test_validation_error_never_retries() -> None:
    assert retry_delay_seconds(BlockedPublishError("缺少封面"), 1) is None
```

Runner 测试使用 fake repository，断言 shutdown 后后台 task 已取消并 await，不遗留 pending task。

Run:

```bash
uv run pytest server/tests/jobs/test_retry.py server/tests/jobs/test_runner.py -q
```

Expected: FAIL，原因是 runner 尚不存在。

- [ ] **Step 2: 实现显式错误分类和退避**

```python
class PublishError(Exception):
    pass


class BlockedPublishError(PublishError):
    pass


class TransientPublishError(PublishError):
    pass


class PermanentPublishError(PublishError):
    pass


RETRY_DELAYS = {1: 30, 2: 120}


def retry_delay_seconds(error: PublishError, attempt: int) -> int | None:
    if not isinstance(error, TransientPublishError):
        return None
    return RETRY_DELAYS.get(attempt)
```

- [ ] **Step 3: 实现两个轻量循环**

`BackgroundRunner` 只维护：

- Notion 同步循环：默认 60 秒。
- Job 领取循环：默认 5 秒。

每次循环捕获异常、脱敏记录并继续；`CancelledError` 必须重新抛出。Job 执行期间每 30 秒续租，结束或失败时清空租约。

临时失败且仍有自动重试次数时，Job 回到 `等待中`，并把 `scheduled_at` 更新为退避后的 UTC 时间；永久失败或重试耗尽时保持 `失败`，只能由人工 Retry API 改回 `等待中`。因此领取查询不直接领取所有 `失败` Job。

`attempt_count` 记录总执行次数，`blog_attempt_count/wechat_attempt_count` 分别控制各渠道最多三次尝试。计数只在快照校验成功、即将调用对应渠道 Publisher 时增加；单纯领取、等待配置或封面修复不消耗重试次数。

- [ ] **Step 4: 使用 FastAPI lifespan 启停后台任务**

`create_app()` 使用 `asynccontextmanager`：

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runner = app.state.container.background_runner
    if start_background_tasks:
        await runner.start()
    try:
        yield
    finally:
        if start_background_tasks:
            await runner.stop()
```

生产命令固定单 Uvicorn worker，避免一个容器内创建多个调度循环。数据库租约仍保证异常重启后的任务恢复。

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/jobs server/tests/test_health.py -q
uv run ruff check server
uv run mypy server/src
```

Expected: 重试次数、租约恢复、取消清理和循环异常隔离全部通过。

```bash
git add server
git commit -m "feat: run recoverable in-process publishing jobs"
```

## Task 9：固定并适配 Doocs Markdown 渲染器

**Files:**

- Create: `scripts/vendor_doocs.sh`
- Create: `vendor/doocs-md/UPSTREAM.md`
- Create: `vendor/doocs-md/LICENSE`
- Create: `vendor/doocs-md/packages/core/`
- Create: `vendor/doocs-md/packages/shared/`
- Create: `vendor/doocs-md/packages/config/`
- Create: `vendor/doocs-md/patches/juice@11.1.1.patch`
- Modify: `pnpm-workspace.yaml`
- Create: `package.json`
- Create: `renderer/package.json`
- Create: `renderer/tsconfig.json`
- Create: `renderer/vite.config.ts`
- Create: `renderer/src/render.ts`
- Create: `renderer/src/cli.ts`
- Create: `renderer/tests/render.test.ts`
- Create: `server/src/reven/publishing/wechat/renderer.py`
- Create: `server/tests/publishing/wechat/test_renderer.py`

- [ ] **Step 1: 添加可复现的上游同步脚本**

`scripts/vendor_doocs.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

readonly DOOCS_REPOSITORY="https://github.com/doocs/md.git"
readonly DOOCS_COMMIT="c37c1d6cc0e0a259de20305b9e4c3b59c7029da7"
readonly VENDOR_TARGET="vendor/doocs-md"
vendor_temp_dir="$(mktemp -d)"
trap 'rm -rf "${vendor_temp_dir}"' EXIT

git clone --filter=blob:none --no-checkout "${DOOCS_REPOSITORY}" "${vendor_temp_dir}/md"
git -C "${vendor_temp_dir}/md" sparse-checkout set \
  packages/core packages/shared packages/config patches/juice@11.1.1.patch LICENSE
git -C "${vendor_temp_dir}/md" checkout "${DOOCS_COMMIT}"
rm -rf "${VENDOR_TARGET}"
mkdir -p "${VENDOR_TARGET}/packages"
cp "${vendor_temp_dir}/md/LICENSE" "${VENDOR_TARGET}/LICENSE"
cp -R "${vendor_temp_dir}/md/packages/core" "${VENDOR_TARGET}/packages/core"
cp -R "${vendor_temp_dir}/md/packages/shared" "${VENDOR_TARGET}/packages/shared"
cp -R "${vendor_temp_dir}/md/packages/config" "${VENDOR_TARGET}/packages/config"
mkdir -p "${VENDOR_TARGET}/patches"
cp "${vendor_temp_dir}/md/patches/juice@11.1.1.patch" "${VENDOR_TARGET}/patches/"
```

`UPSTREAM.md` 记录仓库、Commit、同步日期、许可证和本地适配边界。执行脚本后先检查 `git diff --stat`，不得混入 Doocs Web/Vue 应用。

- [ ] **Step 2: 配置 pnpm workspace 并写失败的渲染测试**

`pnpm-workspace.yaml`：

```yaml
packages:
  - web
  - renderer
  - vendor/doocs-md/packages/core
  - vendor/doocs-md/packages/shared
  - vendor/doocs-md/packages/config

patchedDependencies:
  juice@11.1.1: vendor/doocs-md/patches/juice@11.1.1.patch
```

`package.json`：

```json
{
  "name": "reven",
  "private": true,
  "packageManager": "pnpm@10.13.1",
  "engines": {"node": ">=22.22.2"},
  "scripts": {
    "build": "pnpm --filter @reven/renderer build && pnpm --filter @reven/web build",
    "test": "pnpm -r test"
  }
}
```

`renderer/package.json`：

```json
{
  "name": "@reven/renderer",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "@md/core": "workspace:*",
    "@md/shared": "workspace:*",
    "juice": "11.1.1"
  },
  "devDependencies": {
    "@types/juice": "^8.0.4",
    "@types/node": "^24.0.0",
    "typescript": "^5.8.0",
    "vite": "^7.0.0",
    "vitest": "^3.2.0"
  }
}
```

`renderer/vite.config.ts`：

```typescript
import { defineConfig } from "vitest/config"

export default defineConfig({
  build: {
    ssr: "src/cli.ts",
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: "cli.mjs" } },
  },
  ssr: {
    noExternal: true,
  },
  test: {
    environment: "node",
  },
})
```

`renderer/tests/render.test.ts`：

```typescript
import { describe, expect, it } from "vitest"

import { renderWechatHtml } from "../src/render"

describe("renderWechatHtml", () => {
  it("renders Doocs markup with inline styles and preserves asset placeholders", async () => {
    const html = await renderWechatHtml("# 标题\n\n![图](reven-asset://image/1)")

    expect(html).toContain("<h1")
    expect(html).toContain('src="reven-asset://image/1"')
    expect(html).toMatch(/style="[^"]+"/)
    expect(html).not.toContain("<script")
  })
})
```

Run:

```bash
pnpm install
pnpm --filter @reven/renderer test
```

Expected: FAIL，原因是 renderer 尚未实现。

- [ ] **Step 3: 实现 Doocs 渲染和 CSS 内联**

`renderer/src/render.ts`：

```typescript
import { initRenderer, modifyHtmlContent } from "@md/core"
import { baseCSSContent, themeMap } from "@md/shared/configs"
import juice from "juice"

export async function renderWechatHtml(markdown: string): Promise<string> {
  const renderer = initRenderer({
    citeStatus: true,
    countStatus: false,
    isMacCodeBlock: true,
    isShowLineNumber: false,
    legend: "alt-title",
    themeMode: "light",
  })
  const body = modifyHtmlContent(markdown, renderer)
  const document = `<style>${baseCSSContent}\n${themeMap.default}</style>${body}`
  return juice(document, {
    applyStyleTags: true,
    removeStyleTags: true,
    preserveMediaQueries: false,
    resolveCSSVariables: false,
  })
}
```

Vite 使用 SSR build 处理上游 `?raw` CSS 导入，输出单个 `dist/cli.mjs`。

- [ ] **Step 4: 实现严格的 stdin/stdout JSON 协议和 Python 适配器**

输入：

```json
{"markdown":"# 标题"}
```

成功输出：

```json
{"ok":true,"html":"<section><h1>标题</h1></section>"}
```

失败输出：

```json
{"ok":false,"error":"render_failed"}
```

`renderer/src/cli.ts`：

```typescript
import process from "node:process"

import { renderWechatHtml } from "./render"

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = []
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.from(chunk))
  }
  return Buffer.concat(chunks).toString("utf8")
}

async function main(): Promise<void> {
  try {
    const input = JSON.parse(await readStdin()) as { markdown?: unknown }
    if (typeof input.markdown !== "string") {
      throw new TypeError("markdown must be a string")
    }
    const html = await renderWechatHtml(input.markdown)
    process.stdout.write(JSON.stringify({ ok: true, html }))
  }
  catch {
    process.stdout.write(JSON.stringify({ ok: false, error: "render_failed" }))
    process.exitCode = 1
  }
}

await main()
```

Python 端使用 `asyncio.create_subprocess_exec()`，设置 30 秒超时，只解析 stdout JSON；stderr 经脱敏后记录。测试使用临时假 CLI 验证超时、非零退出码和无效 JSON 都显式失败。

- [ ] **Step 5: 验证并提交**

Run:

```bash
pnpm --filter @reven/renderer test
pnpm --filter @reven/renderer build
uv run pytest server/tests/publishing/wechat/test_renderer.py -q
git diff --check
```

Expected: Node 渲染测试、Python 协议测试和构建全部通过。

```bash
git add package.json pnpm-workspace.yaml pnpm-lock.yaml scripts renderer vendor server
git commit -m "feat: adapt doocs wechat renderer"
```

## Task 10：实现微信 Token、图片、封面和草稿发布

**Files:**

- Create: `server/src/reven/integrations/wechat/client.py`
- Create: `server/src/reven/integrations/wechat/models.py`
- Create: `server/src/reven/publishing/wechat/images.py`
- Create: `server/src/reven/publishing/wechat/publisher.py`
- Create: `server/tests/fixtures/wechat/`
- Create: `server/tests/integrations/wechat/test_client.py`
- Create: `server/tests/publishing/wechat/test_publisher.py`

- [ ] **Step 1: 写微信请求契约和图片替换失败测试**

```python
@pytest.mark.anyio
async def test_publish_uploads_body_images_before_creating_draft(
    wechat_publisher,
    fake_wechat,
    prepared_job,
) -> None:  # type: ignore[no-untyped-def]
    result = await wechat_publisher.publish(prepared_job)

    assert fake_wechat.calls == [
        "get_token",
        "upload_body_image",
        "upload_cover_material",
        "create_draft",
    ]
    assert "reven-asset://" not in fake_wechat.draft_content
    assert "mmbiz.qpic.cn" in fake_wechat.draft_content
    assert result.media_id == "draft-media-id"
```

Run:

```bash
uv run pytest server/tests/integrations/wechat server/tests/publishing/wechat -q
```

Expected: FAIL，原因是微信客户端和 Publisher 尚不存在。

- [ ] **Step 2: 实现 WeChatClient 和 Token 缓存**

客户端只实现 MVP 所需接口：

```text
GET  /cgi-bin/token
POST /cgi-bin/media/uploadimg
POST /cgi-bin/material/add_material?type=image
POST /cgi-bin/draft/add
```

Token 缓存到内存并在过期前 5 分钟刷新；收到微信“Token 失效”业务码时只强制刷新并重放一次。微信返回 HTTP 200 但 JSON `errcode != 0` 时也必须抛出分类错误。认证/IP 白名单/权限错误归类为阻塞，限流和 5xx 归类为临时失败。

- [ ] **Step 3: 实现安全的临时素材恢复**

复用 Task 7 的 `AssetMaterializer`。当前临时目录缺失时，重新获取 Notion Markdown 和素材；只有重新生成的 canonical Markdown、正文图片 SHA-256、封面 SHA-256 与 Job 快照全部一致才恢复素材，否则阻塞旧任务。恢复过程沿用同一套 SSRF、大小和 MIME 校验。

- [ ] **Step 4: 实现 HTML 图片替换、封面上传和幂等草稿创建**

流程：

1. 调用 Doocs renderer 得到 HTML。
2. 用 BeautifulSoup 查找 `img[src^="reven-asset://"]`。
3. 逐张调用 `uploadimg`；每获得一个微信 URL，就按素材 SHA-256 写入 `wechat_result.uploaded_images` 并提交，然后替换 HTML。
4. 下载 Notion `封面` 第一张图片。
5. 调用永久素材接口取得 `thumb_media_id`，立即写入 `wechat_result.thumb_media_id` 并提交。
6. 组装单篇 `articles` 数组并调用 `draft/add`。
7. 收到 `media_id` 后立即提交数据库事务。
8. 重试时复用已持久化的图片 URL 和 `thumb_media_id`；Job 已有 `wechat_result.media_id` 时直接返回，禁止再次创建草稿。

草稿内容只使用微信托管图片 URL，不使用 Supabase Storage 或 Reven 域名。

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/integrations/wechat server/tests/publishing/wechat -q
uv run ruff check server
uv run mypy server/src
```

Expected: Token 缓存、微信业务错误、SSRF、防超限、图片替换和草稿幂等测试全部通过。

```bash
git add server
git commit -m "feat: publish articles to wechat drafts"
```

## Task 11：实现 Jekyll 转换、GitHub Flow 和线上验证

**Files:**

- Create: `server/src/reven/integrations/github/client.py`
- Create: `server/src/reven/publishing/commands.py`
- Create: `server/src/reven/publishing/blog/converter.py`
- Create: `server/src/reven/publishing/blog/workspace.py`
- Create: `server/src/reven/publishing/blog/publisher.py`
- Create: `server/tests/integrations/github/test_client.py`
- Create: `server/tests/publishing/blog/test_converter.py`
- Create: `server/tests/publishing/blog/test_publisher.py`
- Create: `infra/blog/verify.yml`

- [ ] **Step 1: 写 Front Matter 和“绝不直推默认分支”的失败测试**

```python
def test_converter_matches_blog_contract(tmp_path, snapshot, article) -> None:  # type: ignore[no-untyped-def]
    output = BlogConverter(site_url="https://www.wangyiyang.cc").write(
        root=tmp_path,
        article=article,
        snapshot=snapshot,
    )

    text = output.post_path.read_text()
    assert text.startswith("---\nlayout: post\n")
    assert 'title: "测试稿件"' in text
    assert "categories:" in text
    assert output.post_path.name.startswith("2026-08-01-")


@pytest.mark.anyio
async def test_publisher_pushes_release_branch_not_default(fake_git, publisher) -> None:  # type: ignore[no-untyped-def]
    await publisher.publish(prepared_job)
    assert fake_git.pushed_refs == ["reven/11111111-aaaaaaaaaaaa"]
    assert "master" not in fake_git.pushed_refs
```

Run:

```bash
uv run pytest server/tests/integrations/github server/tests/publishing/blog -q
```

Expected: FAIL，原因是博客模块尚不存在。

- [ ] **Step 2: 把 notion-to-blog 经验拆成纯转换模块**

`BlogConverter` 吸收现有 skill 的有效规则：

- `<callout>` 转引用。
- `<empty-block/>` 转空行。
- 引用块后补空行。
- 从 Task 7 的冻结素材复制图片到 `images/posts/{date}-{slug}/01.ext`，不再次下载外部 URL。
- 正文图片替换为 `https://www.wangyiyang.cc/images/posts/2026-08-01-notion-11111111/01.png` 这一确定格式。
- Front Matter 精确匹配博客 `AGENTS.md`。
- 中文标题无 ASCII 单词时使用 `notion-{page_id前8位}`，避免全部退化为 `post`。
- 只写 `_posts/` 和对应图片目录，不碰 `_site/`、主题或其他文章。

转换器不执行 Git、Jekyll 或网络操作，便于单元测试。

- [ ] **Step 3: 实现无 shell 注入的命令执行和 Git 工作区**

所有命令使用参数数组且 `shell=False`：

```python
await command_runner.run(["git", "clone", remote_url, str(workspace)])
await command_runner.run(["git", "switch", "-c", release_branch], cwd=workspace)
platform = (
    await command_runner.run(["ruby", "-e", "print Gem::Platform.local"])
).stdout
await command_runner.run(["bundle", "lock", "--add-platform", platform], cwd=workspace)
await command_runner.run(["bundle", "install"], cwd=workspace)
await command_runner.run(["bundle", "exec", "jekyll", "build"], cwd=workspace)
```

GitHub Token 不出现在 URL、参数或日志中；通过 subprocess 环境中的 `GIT_CONFIG_COUNT/GIT_CONFIG_KEY_0/GIT_CONFIG_VALUE_0` 注入 Authorization Header。日志只记录命令名和已脱敏参数。

- [ ] **Step 4: 实现 GitHub Flow 状态机**

流程和可恢复检查：

1. GET Repository 获取 `default_branch`，禁止硬编码 `master`。
2. 分支名 `reven/{page_id前8位}-{content_hash前12位}`。
3. 重试前查询同名远程分支和已有 open/merged PR。
4. 本地 Jekyll build 通过后，只 `git add` 新文章和该文章图片。
5. Conventional Commit：`feat: publish {title}`。
6. 推送发布分支。
7. 查询仓库中的 PR Template；存在时按模板生成描述，不存在时使用 Reven 的“目的/改动/验证”描述，然后创建 PR。
8. 轮询该 SHA 的 required checks；失败或没有配置 required check 时阻塞并给出动作。
9. Checks 通过后调用 Merge API。
10. 轮询 GitHub Pages latest build，要求其 Commit SHA 等于本次合并 SHA，不能把其他部署误认为成功。
11. 请求预期文章 URL，要求 2xx 且 HTML 包含标题。
12. 持久化 branch、PR、commit、deployment 和 article URL。

每得到 branch、commit SHA、PR number、merge SHA、Pages build ID 或 article URL，都立即写入 `blog_result` 并提交；重启后从已持久化的最后一步继续，不重新创建分支或 PR。

`infra/blog/verify.yml` 提供一次性安装到博客仓库的 Jekyll CI 模板；部署 Runbook 要求先用独立 PR 安装并设为 required check，不能由 Reven 直推博客默认分支。

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/integrations/github server/tests/publishing/blog -q
uv run ruff check server
uv run mypy server/src
```

Expected: 转换、重复分支/PR 恢复、CI 失败、合并、Pages 等待和线上标题验证全部通过。

```bash
git add server infra/blog
git commit -m "feat: publish blog posts through github flow"
```

## Task 12：实现飞书通知与跨渠道交付编排

**Files:**

- Create: `server/src/reven/integrations/feishu/client.py`
- Create: `server/src/reven/publishing/orchestrator.py`
- Create: `server/tests/integrations/feishu/test_client.py`
- Create: `server/tests/publishing/test_orchestrator.py`

- [ ] **Step 1: 写单渠道失败不重做成功渠道的失败测试**

```python
@pytest.mark.anyio
async def test_retry_only_runs_failed_channel(orchestrator, blog, wechat, job) -> None:  # type: ignore[no-untyped-def]
    blog.result = {"article_url": "https://www.wangyiyang.cc/post"}
    job.blog_status = "已上线"
    wechat.fail_once()

    await orchestrator.execute(job.id)
    await orchestrator.execute(job.id)

    assert blog.call_count == 0
    assert wechat.call_count == 2
    assert job.overall_status == "已完成"
```

再覆盖默认渠道通知、阻塞、博客成功、微信成功、全部完成和通知去重。

Run:

```bash
uv run pytest server/tests/integrations/feishu server/tests/publishing/test_orchestrator.py -q
```

Expected: FAIL，原因是编排器尚不存在。

- [ ] **Step 2: 实现飞书 Webhook 客户端**

客户端发送 `msg_type=interactive` 卡片，内容只含：

- 稿件标题。
- 当前阶段。
- 可操作的脱敏摘要。
- Notion、Reven、PR 或博客链接。

飞书失败只记录 warning，不改变内容发布结果。只有用户点击“测试飞书”时，连接测试才真正发送测试消息。

- [ ] **Step 3: 实现 Job 内持久化的通知去重**

去重键：

```python
fingerprint = sha256(
    f"{job.id}:{event}:{error_code or ''}:{channel or ''}".encode()
).hexdigest()
```

成功发送后写入 `job.notification_state[fingerprint]`；相同状态不再发送。状态变化或人工重试产生新的 event revision，允许再次通知。

- [ ] **Step 4: 实现跨渠道编排和 Notion 完成交付**

`PublicationOrchestrator.execute(job_id)`：

1. 读取持久化渠道状态。
2. 只执行目标渠道中未完成的渠道。
3. 一个渠道失败不回滚另一个。
4. 临时错误按 Task 8 退避重试。
5. 阻塞/永久错误更新 Article 和 Notion `自动化状态/失败原因`。
6. 所有目标渠道完成后更新 Notion：
   - `状态=已交付`
   - `自动化状态=已完成`
   - `失败原因=""`
   - 博客成功时 `链接={article_url}`
7. 发送交付摘要。
8. 数据库完成状态提交成功后清理 `/data/jobs/{job_id}`。

如果更新 Notion 失败，渠道结果保持成功，重试只补 Notion 回写，不重复发布。

- [ ] **Step 5: 验证并提交**

Run:

```bash
uv run pytest server/tests/integrations/feishu server/tests/publishing/test_orchestrator.py -q
uv run ruff check server
uv run mypy server/src
```

Expected: 部分失败恢复、通知去重、Notion 回写恢复和清理顺序全部通过。

```bash
git add server
git commit -m "feat: orchestrate delivery and feishu notifications"
```

## Task 13：完成稿件、任务、预览、重试和系统 API

**Files:**

- Create: `server/src/reven/api/dependencies.py`
- Create: `server/src/reven/api/schemas/articles.py`
- Create: `server/src/reven/api/routes/articles.py`
- Create: `server/src/reven/api/routes/system.py`
- Modify: `server/src/reven/app.py`
- Create: `server/tests/api/test_articles.py`
- Create: `server/tests/api/test_actions.py`

- [ ] **Step 1: 写列表筛选、详情和动作权限边界的失败测试**

```python
def test_list_articles_supports_status_channel_and_title(client, seeded_articles) -> None:  # type: ignore[no-untyped-def]
    response = client.get(
        "/api/articles",
        params={"status": "待发布", "channel": "微信公众号", "query": "测试"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_retry_rejects_successful_channel(client, completed_job) -> None:  # type: ignore[no-untyped-def]
    response = client.post(
        f"/api/articles/{completed_job.article_id}/jobs/{completed_job.id}/retry",
        json={"channels": ["个人博客"]},
    )
    assert response.status_code == 409
```

Run:

```bash
uv run pytest server/tests/api/test_articles.py server/tests/api/test_actions.py -q
```

Expected: FAIL，原因是路由尚不存在。

- [ ] **Step 2: 实现只读稿件 API**

```text
GET /api/articles?page=1&page_size=20&status=&channel=&query=
GET /api/articles/{article_id}
GET /api/articles/{article_id}/jobs/{job_id}
```

列表默认按计划时间空值最后、最近编辑时间倒序。详情返回：

- Notion 元数据和链接。
- 校验 errors/warnings。
- 内容 hash。
- Blog/WeChat 状态和脱敏错误。
- PR、Commit、文章 URL、微信 media_id。
- `wechat_html` 只在详情接口返回。

- [ ] **Step 3: 实现有状态动作 API**

```text
POST /api/articles/{id}/sync
POST /api/articles/{id}/preview/wechat
POST /api/articles/{id}/jobs/{job_id}/retry
POST /api/articles/{id}/jobs/{job_id}/cancel
```

- 预览只获取最新页面并渲染；将 `reven-asset://` 临时替换为本次请求拿到的 Notion 签名图片 URL，便于浏览器查看，但不上传微信、不创建草稿、不修改 Notion 状态。
- Retry 只允许失败/阻塞修复后的目标渠道。
- Cancel 只允许未开始的等待任务。
- 所有请求使用 UUID 校验，非法状态返回 409 和明确错误码。

- [ ] **Step 4: 实现系统信息 API**

```text
GET /api/system/status
GET /api/system/egress-ip
```

`status` 返回同步心跳、调度心跳和数据库连接状态。`egress-ip` 通过一个可注入的 HTTPS IP provider 获取云服务器出口 IP，设置 3 秒超时和短缓存；失败时返回 `available=false`，不伪造地址。

- [ ] **Step 5: 验证 OpenAPI 和提交**

Run:

```bash
uv run pytest server/tests/api -q
uv run python -c "from reven.app import create_app; assert '/api/articles' in create_app(start_background_tasks=False).openapi()['paths']"
uv run ruff check server
uv run mypy server/src
```

Expected: API 测试、OpenAPI 路径检查和静态检查全部通过。

```bash
git add server
git commit -m "feat: expose editorial workbench api"
```

## Task 14：建立 React、shadcn/ui、Tailwind 工作台和集成设置

**Files:**

- Modify: `package.json`
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/components.json`
- Create: `web/src/index.css`
- Create: `web/src/main.tsx`
- Create: `web/src/app.tsx`
- Create: `web/src/components/app-shell.tsx`
- Create: `web/src/components/ui/`
- Create: `web/src/lib/api.ts`
- Create: `web/src/lib/query-client.ts`
- Create: `web/src/features/integrations/integrations-page.tsx`
- Create: `web/src/features/integrations/integration-card.tsx`
- Create: `web/src/features/integrations/integrations-page.test.tsx`

- [ ] **Step 1: 用当前 Vite + Tailwind 4 方式建立前端**

Run:

```bash
pnpm create vite web --template react-ts
cd web
pnpm add @tanstack/react-query react-router-dom lucide-react sonner
pnpm add -D @tailwindcss/vite tailwindcss vitest jsdom \
  @testing-library/react @testing-library/jest-dom @testing-library/user-event msw
pnpm dlx shadcn@latest init -d
pnpm dlx shadcn@latest add -y badge button card dialog input label select \
  separator skeleton table tabs textarea tooltip
cd ..
```

Expected: `web/components.json` 使用 `rsc: false`，TypeScript alias 为 `@/* -> ./src/*`，`src/index.css` 包含 `@import "tailwindcss";`。

`web/vite.config.ts` 明确启用 Tailwind 4 和开发代理：

```typescript
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import path from "node:path"
import { defineConfig } from "vitest/config"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
})
```

- [ ] **Step 2: 先写集成 Secret 不回填的失败测试**

```tsx
it("shows configured state without putting the secret into the input", async () => {
  server.use(
    http.get("/api/integrations", () =>
      HttpResponse.json([
        {
          provider: "wechat",
          public_config: { app_id: "wx123" },
          secret_configured: true,
          secret_hint: "已配置 · ****9f2a",
        },
      ]),
    ),
  )

  render(<IntegrationsPage />)

  expect(await screen.findByText("已配置 · ****9f2a")).toBeInTheDocument()
  expect(screen.getByLabelText("AppSecret")).toHaveValue("")
})
```

Run:

```bash
pnpm --filter @reven/web test --run
```

Expected: FAIL，原因是页面尚未实现。

- [ ] **Step 3: 实现 API Client、Query 和工作台壳层**

`api.ts` 使用原生 `fetch`：

```typescript
export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(response.status, body?.code ?? "request_failed", body?.message)
  }
  return body as T
}
```

壳层只包含三处导航：稿件、集成设置、系统状态。桌面为左侧导航，窄屏为顶部导航，不增加仪表盘、用户或分析页面。

- [ ] **Step 4: 实现四张集成卡片**

每张卡片展示公共配置、Secret 状态、最近测试和错误：

- Notion：Database ID、Data Source ID、Token、测试连接、初始化字段。
- GitHub：Owner、Repo、默认分支策略、Token、测试连接。
- 微信：AppID、作者、AppSecret、出口 IP、测试连接。
- 飞书：通知名称、Webhook、主动发送测试消息。

保存时空 Secret 表示保留；替换和删除必须是独立动作。危险操作用 Dialog 明确确认。

- [ ] **Step 5: 验证并提交**

Run:

```bash
pnpm --filter @reven/web test --run
pnpm --filter @reven/web exec tsc -b
pnpm --filter @reven/web build
```

Expected: 前端测试、类型检查和生产构建全部通过。

```bash
git add package.json pnpm-workspace.yaml pnpm-lock.yaml web
git commit -m "feat: add react integration settings workbench"
```

## Task 15：实现稿件列表、稿件详情、微信预览与富文本复制

**Files:**

- Create: `web/src/features/articles/types.ts`
- Create: `web/src/features/articles/articles-page.tsx`
- Create: `web/src/features/articles/article-filters.tsx`
- Create: `web/src/features/articles/article-status.tsx`
- Create: `web/src/features/articles/article-detail-page.tsx`
- Create: `web/src/features/articles/channel-timeline.tsx`
- Create: `web/src/features/articles/wechat-preview.tsx`
- Create: `web/src/lib/clipboard.ts`
- Create: `web/src/features/articles/articles-page.test.tsx`
- Create: `web/src/features/articles/article-detail-page.test.tsx`
- Create: `web/src/lib/clipboard.test.ts`
- Modify: `web/src/app.tsx`

- [ ] **Step 1: 写列表筛选和富文本剪贴板失败测试**

```tsx
it("filters articles by status and channel", async () => {
  render(<ArticlesPage />)
  await userEvent.click(await screen.findByRole("combobox", { name: "状态" }))
  await userEvent.click(screen.getByText("待发布"))
  expect(await screen.findByText("测试稿件")).toBeInTheDocument()
})
```

```typescript
it("writes text/html and text/plain clipboard flavors", async () => {
  await copyRichHtml("<h1>标题</h1>", "标题")

  const item = clipboardWrite.mock.calls[0][0][0]
  expect(item.types).toContain("text/html")
  expect(item.types).toContain("text/plain")
})
```

Run:

```bash
pnpm --filter @reven/web test --run
```

Expected: FAIL，原因是稿件页面和剪贴板模块尚不存在。

- [ ] **Step 2: 实现稿件列表**

列表展示设计规格中的九列；小屏将次要列收进详情摘要。筛选状态写入 URL Search Params，刷新后保持。操作包括打开 Notion、立即同步和打开任务详情。

状态颜色必须统一：

- 等待：中性蓝。
- 处理中：琥珀。
- 阻塞/失败：红橙。
- 完成：绿色。

颜色之外同时显示文字和图标，不能只靠颜色表达。

- [ ] **Step 3: 实现稿件详情和渠道时间线**

详情分为：

1. Notion 元数据和封面校验。
2. 发布前 errors/warnings。
3. 博客与微信独立状态时间线。
4. PR、Commit、文章 URL、media_id。
5. 脱敏错误和可操作建议。

“重试”只对失败渠道显示；“取消”只对等待任务显示。

- [ ] **Step 4: 实现无副作用预览和安全富文本复制**

预览调用 `/articles/{id}/preview/wechat`，用 `iframe srcDoc` 加 `sandbox=""` 展示，不在主 DOM 执行返回 HTML。

`copyRichHtml()`：

```typescript
export async function copyRichHtml(html: string, plainText: string): Promise<void> {
  if (!window.isSecureContext || !navigator.clipboard?.write) {
    throw new Error("富文本复制需要 HTTPS 和现代浏览器剪贴板权限")
  }
  const item = new ClipboardItem({
    "text/html": new Blob([html], { type: "text/html" }),
    "text/plain": new Blob([plainText], { type: "text/plain" }),
  })
  await navigator.clipboard.write([item])
}
```

失败时显示明确 Toast，不静默降级为可能丢样式的复制。

- [ ] **Step 5: 验证并提交**

Run:

```bash
pnpm --filter @reven/web test --run
pnpm --filter @reven/web exec tsc -b
pnpm --filter @reven/web build
```

Expected: 列表、筛选、详情、操作可见性、预览 sandbox 和剪贴板测试全部通过。

```bash
git add web
git commit -m "feat: add article delivery workbench"
```

## Task 16：完成容器、Caddy、CI 和部署运行手册

**Files:**

- Create: `infra/docker/Dockerfile`
- Create: `infra/docker/entrypoint.sh`
- Create: `infra/caddy/Caddyfile`
- Create: `infra/compose/docker-compose.yml`
- Modify: `.github/workflows/ci.yml`
- Create: `docs/runbook.md`
- Create: `README.md`

- [ ] **Step 1: 写容器 Smoke Test 脚本**

在 CI 中使用：

```bash
docker build -f infra/docker/Dockerfile -t reven:test .
docker run --rm reven:test node /app/renderer/dist/cli.mjs <<<'{"markdown":"# smoke"}'
docker run --rm reven:test ruby --version
docker run --rm reven:test bundle --version
```

Expected before implementation: Docker build FAIL，因为 Dockerfile 尚不存在。

- [ ] **Step 2: 实现一个 Reven 运行容器**

Dockerfile 使用多阶段构建：

1. Node 22 + pnpm 构建 `web/dist` 和 `renderer/dist/cli.mjs`。
2. Python 3.12 + uv 安装冻结依赖。
3. 最终 Python 3.12 slim 安装 Node 22 runtime、Ruby、Bundler、Git 和 Jekyll 编译依赖。
4. 复制 Python venv、前端静态文件和 renderer。

`infra/docker/Dockerfile`：

```dockerfile
FROM node:22.22.2-bookworm-slim AS node-build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY renderer/package.json renderer/package.json
COPY web/package.json web/package.json
COPY vendor/doocs-md/ vendor/doocs-md/
RUN pnpm install --frozen-lockfile
COPY renderer/ renderer/
COPY web/ web/
RUN pnpm --filter @reven/renderer build \
    && pnpm --filter @reven/web build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS python-build
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY server/pyproject.toml server/pyproject.toml
RUN uv sync --frozen --no-dev --all-packages

FROM python:3.12-slim-trixie AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential git ruby-full \
    && gem install bundler -v 2.5.22 --no-document \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 reven \
    && mkdir -p /app /data/jobs /srv/reven \
    && chown -R reven:reven /app /data /srv/reven
WORKDIR /app
COPY --from=python-build --chown=reven:reven /app/.venv /app/.venv
COPY --from=node-build /usr/local/bin/node /usr/local/bin/node
COPY --from=node-build --chown=reven:reven /app/renderer/dist /app/renderer/dist
COPY --from=node-build --chown=reven:reven /app/web/dist /app/web-dist
COPY --chown=reven:reven server/ /app/server/
COPY --chown=reven:reven infra/docker/entrypoint.sh /app/entrypoint.sh
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/server/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER reven
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
```

`entrypoint.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

mkdir -p /srv/reven
cp -a /app/web-dist/. /srv/reven/
/app/.venv/bin/alembic -c /app/server/migrations/alembic.ini upgrade head
exec /app/.venv/bin/uvicorn reven.app:app --host 0.0.0.0 --port 8000 --workers 1
```

只运行一个 Uvicorn worker。

- [ ] **Step 3: 实现 Caddy 静态站点、Basic Auth 和 API 代理**

`infra/caddy/Caddyfile`：

```caddyfile
dev.wangyiyang.cc {
    basic_auth {
        {$REVEN_BASIC_AUTH_USER} {$CADDY_BASIC_AUTH_HASH}
    }

    handle /api/* {
        reverse_proxy reven:8000
    }

    handle {
        root * /srv/reven
        try_files {path} /index.html
        file_server
    }
}
```

Compose 只定义：

- `reven`
- `caddy`
- `reven-data` 本地持久卷
- `reven-static` 静态文件共享卷
- `caddy-data/config` 证书卷

不定义 PostgreSQL、MinIO、Redis、Worker 或端口 3000。`reven:8000` 不映射到宿主机。

`infra/compose/docker-compose.yml`：

```yaml
services:
  reven:
    build:
      context: ../..
      dockerfile: infra/docker/Dockerfile
    restart: unless-stopped
    env_file:
      - ../../.env
    volumes:
      - reven-data:/data
      - reven-static:/srv/reven
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
      interval: 10s
      timeout: 5s
      retries: 12

  caddy:
    image: caddy:2.10-alpine
    restart: unless-stopped
    env_file:
      - ../../.env
    depends_on:
      reven:
        condition: service_healthy
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ../caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - reven-static:/srv/reven:ro
      - caddy-data:/data
      - caddy-config:/config

volumes:
  reven-data:
  reven-static:
  caddy-data:
  caddy-config:
```

- [ ] **Step 4: 更新 CI**

CI 必须包含：

```text
backend:
  ruff check
  ruff format --check
  mypy
  pytest（PostgreSQL service）
frontend:
  pnpm test
  tsc -b
  pnpm build
renderer:
  pnpm test
  pnpm build
migration:
  alembic upgrade head
container:
  docker build
```

锁文件必须使用 `uv sync --frozen` 和 `pnpm install --frozen-lockfile`。

- [ ] **Step 5: 编写可执行 Runbook**

`docs/runbook.md` 顺序：

1. 在 Supabase 获取 Pooler 的 IPv4/Session `DATABASE_URL`，开启 SSL。
2. 生成 `REVEN_MASTER_KEY`，只写服务器 `.env`。
3. 用 `caddy hash-password` 生成独立 Basic Auth 哈希。
4. 在博客仓库用 PR 安装 `infra/blog/verify.yml` 并设为 required check。
5. 在微信平台把 `/api/system/egress-ip` 展示的出口 IP 加入白名单。
6. `ssh kk@dev.wangyiyang.cc` 后在独立目录部署 Compose。
7. 验证 3000 端口服务未变化。
8. 验证 HTTP 自动跳 HTTPS、Basic Auth、`/api/health`。
9. 回滚到上一镜像 Tag；数据库只使用向后兼容迁移。

文档中的所有 Secret 使用占位符。

- [ ] **Step 6: 验证并提交**

Run:

```bash
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
uv run pytest server/tests -q
pnpm --filter @reven/renderer test
pnpm --filter @reven/renderer build
pnpm --filter @reven/web test --run
pnpm --filter @reven/web exec tsc -b
pnpm --filter @reven/web build
docker build -f infra/docker/Dockerfile -t reven:test .
git diff --check
```

Expected: 全部退出码为 0。

```bash
git add .github infra docs/runbook.md README.md
git commit -m "chore: add production deployment and ci"
```

## Task 17：完成端到端契约、真实验收门禁和 PR

**Files:**

- Create: `server/tests/e2e/test_delivery_flow.py`
- Create: `server/tests/e2e/fakes.py`
- Create: `scripts/smoke.sh`
- Modify: `docs/runbook.md`

- [ ] **Step 1: 写完整闭环的离线 E2E 测试**

```python
@pytest.mark.anyio
async def test_notion_to_blog_and_wechat_delivery(e2e_system) -> None:  # type: ignore[no-untyped-def]
    await e2e_system.notion.set_page(
        status="待发布",
        channels=[],
        planned_at=None,
        has_cover=True,
    )

    await e2e_system.sync_once()
    await e2e_system.run_until_idle()

    article = await e2e_system.get_article()
    job = await e2e_system.get_job()
    assert job.blog_status == "已上线"
    assert job.wechat_status == "草稿已生成"
    assert job.wechat_result["media_id"] == "draft-media-id"
    assert article.automation_status == "已完成"
    assert e2e_system.notion.updated_status == "已交付"
    assert e2e_system.feishu.events == [
        "default_channels",
        "blog_succeeded",
        "wechat_succeeded",
        "delivery_completed",
    ]
```

Fakes 必须实现和真实 Client 相同的 Protocol，不得在 E2E 中调用真实外部写接口。

- [ ] **Step 2: 增加阻塞、恢复、幂等和重启 E2E**

至少覆盖：

- 无封面 → 阻塞 → 补封面 → 自动恢复。
- 日期无时间 → 上海时间 08:01。
- 博客成功、微信临时失败 → 只重试微信。
- 任务执行中租约过期 → 新 runner 恢复。
- 同一稿件版本重复同步 → 只有一个 Job、一个 PR、一个微信草稿。
- Notion 在任务启动后改变 → 当前快照不混入新内容。
- Notion 回写临时失败 → 不重复渠道发布。

- [ ] **Step 3: 增加服务器 Smoke Script**

`scripts/smoke.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

readonly BASE_URL="${REVEN_BASE_URL:-https://dev.wangyiyang.cc}"
curl --fail --silent --show-error \
  --user "${REVEN_BASIC_AUTH_USER:?}:${REVEN_BASIC_AUTH_PASSWORD:?}" \
  "${BASE_URL}/api/health" |
  grep --fixed-strings '"status":"ok"'
```

脚本只验证只读健康检查，不触发发布。

- [ ] **Step 4: 运行全量验证**

Run:

```bash
docker compose -f infra/test/docker-compose.yml up -d --wait
TEST_DATABASE_URL=postgresql+asyncpg://reven_test:reven_test@127.0.0.1:55432/reven_test \
  uv run pytest server/tests --cov=reven --cov-report=term-missing
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
pnpm --filter @reven/renderer test
pnpm --filter @reven/renderer build
pnpm --filter @reven/web test --run
pnpm --filter @reven/web exec tsc -b
pnpm --filter @reven/web build
docker build -f infra/docker/Dockerfile -t reven:test .
git diff --check
```

Expected: 所有命令退出码为 0；覆盖率报告无未解释的核心状态分支缺口。

- [ ] **Step 5: 执行需要用户凭据的真实验收**

严格按 Runbook 使用一篇专门测试稿：

1. 配置并测试四个集成。
2. 显式初始化 Notion 字段。
3. 缺封面验证阻塞和飞书通知。
4. 补封面后验证自动恢复。
5. 验证未来时间调度。
6. 验证博客 PR、required CI、自动合并和线上标题。
7. 用户主动确认后创建一篇微信测试草稿。
8. 验证最终 HTML、正文图片、封面和 `media_id`。
9. 验证 Notion 变为 `已交付`，不是 `已发布`。
10. 重试和重启验证不产生重复发布。

任何真实写操作都只针对测试稿、测试分支或微信草稿箱；不调用微信公开发布接口。

- [ ] **Step 6: 提交验收资产并创建 PR**

```bash
git add server/tests/e2e scripts/smoke.sh docs/runbook.md
git commit -m "test: verify editorial publishing workflow"
git status --short
git log --oneline main..HEAD
```

Expected: 工作区干净；提交历史由可审查的 Conventional Commits 组成。

创建 PR 前：

1. 查找 `.github/PULL_REQUEST_TEMPLATE*`。
2. PR 描述按“目的/背景/改动/风险/验证”组织。
3. 不自动合并 Reven 自身 PR，等待用户审查。

## 18. 规格覆盖矩阵

| 规格能力 | 实施任务 |
| --- | --- |
| React + shadcn/ui + Tailwind | Task 14、15 |
| FastAPI 模块化单体、单进程后台任务 | Task 1、8 |
| Supabase Postgres、无 Redis/对象存储 | Task 3、16 |
| Notion Data Source、字段初始化、待发布 | Task 5、6 |
| 上海时间、日期默认 08:01 | Task 2 |
| 封面阻止全部发布 | Task 7 |
| 默认博客+微信、未支持渠道阻塞 | Task 2、7 |
| 内容快照和幂等任务 | Task 7 |
| 租约、三次尝试、重启恢复 | Task 3、8 |
| 博客转换、PR、CI、合并、Pages 验证 | Task 11 |
| Doocs HTML、图片上传、封面、微信草稿 | Task 9、10 |
| 飞书通知和去重 | Task 12 |
| Notion 已交付回写 | Task 12 |
| 稿件列表、详情、HTML 预览与复制 | Task 13、15 |
| 四个集成设置和 Secret 加密 | Task 4、14 |
| HTTPS、Basic Auth、保留 3000 | Task 16 |
| 离线测试与真实验收 | Task 17 |

## 19. 明确不实施

本计划不创建以下内容：

- OpenClaw/RSS 接口和线索页面。
- Supabase Storage、MinIO、Redis、独立 Worker。
- 微信公众号公开发布。
- 掘金/CSDN 发布。
- AI 写稿、自动封面、多用户、权限系统和分析仪表盘。

这些需求必须在 MVP 验收通过后另写设计和实施计划。
