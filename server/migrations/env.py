"""Alembic env — 支持离线生成与在线执行。"""

import asyncio
from logging.config import fileConfig

# 导入所有模型以保证 Base.metadata 完整
import reven.importing.models  # noqa: F401
from alembic import context
from reven.kernel.models.base import Base
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 按模块前缀逐步开放的表白名单
_ACTIVE_TABLES = {
    "importing_source_file",
    "importing_import_batch",
    "importing_raw_row",
    "importing_job",
    # 后续模块在此追加
}


def include_object(obj, name, type_, reflected, compare_to):
    """只迁移白名单内的表。"""
    if type_ == "table":
        return name in _ACTIVE_TABLES or name.startswith("alembic_")
    return True


def run_migrations_offline() -> None:
    """离线模式 — 生成 SQL 脚本。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramtype": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online_sync() -> None:
    """同步引擎在线迁移（upgrade / downgrade / autogenerate 兜底）。"""
    # 使用同步 URL 用于连接
    sync_url = config.get_main_option("sqlalchemy.url").replace(
        "postgresql+asyncpg", "postgresql"
    )
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        url=sync_url,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


async def run_migrations_online_async() -> None:
    """异步引擎在线迁移。"""
    url = config.get_main_option("sqlalchemy.url")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    try:
        asyncio.run(run_migrations_online_async())
    except Exception:
        # 降级到同步引擎（本地无 asyncpg 驱动时）
        run_migrations_online_sync()
