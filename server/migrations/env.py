"""Alembic environment targeting the Reven metadata, URL from DATABASE_URL."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from reven.articles.models import Article  # noqa: F401
from reven.brand.models import BrandAsset, BrandImportRun, BrandVersion, ChannelTemplateVersion  # noqa: F401
from reven.content_sync.models import ContentSnapshot, ContentSyncRun, SnapshotAsset  # noqa: F401
from reven.crm.models import Contact, Customer, FollowUp  # noqa: F401
from reven.db import Base
from reven.finance.models import FinanceEntry  # noqa: F401
from reven.integrations.models import Integration  # noqa: F401
from reven.jobs.models import PublicationJob  # noqa: F401
from reven.jobs.notification_outbox import NotificationOutbox  # noqa: F401
from reven.projects.models import Project  # noqa: F401
from reven.rss.models import RssDiscoveryRun, RssItem, RssKeyword, RssSource  # noqa: F401
from reven.sops.models import Sop  # noqa: F401
from reven.system.models import SystemState  # noqa: F401
from reven.talents.models import Talent, TalentInteraction  # noqa: F401
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=os.environ["DATABASE_URL"],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(os.environ["DATABASE_URL"])
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
