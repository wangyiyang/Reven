"""Production blog publisher builder used by the channel orchestrator."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.integrations.github.client import GitHubClient
from reven.integrations.repository import IntegrationRepository
from reven.jobs.errors import BlockedPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.blog.converter import BlogConverter
from reven.publishing.blog.publisher import BlogPublisher
from reven.publishing.blog.store import SqlAlchemyBlogResultStore
from reven.publishing.blog.workspace import BlogWorkspace
from reven.publishing.commands import CommandRunner
from reven.security.secrets import SecretBox, SecretBoxError


@dataclass(frozen=True)
class _Configuration:
    owner: str
    repo: str
    site_url: str
    token: str


class ConfiguredBlogPublisher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        data_root: Path,
    ) -> None:
        self.session_factory = session_factory
        self.secret_box = secret_box
        self.data_root = data_root

    async def publish(self, claim: JobClaim):  # type: ignore[no-untyped-def]
        config = await self._configuration()
        remote = f"https://github.com/{config.owner}/{config.repo}.git"
        runner = CommandRunner()
        workspace = BlogWorkspace(
            self.data_root / "jobs",
            runner,
            sandbox_executable=Path("/usr/bin/bwrap"),
        )
        async with runner, GitHubClient(config.owner, config.repo, config.token, site_url=config.site_url) as client:
            publisher = BlogPublisher(
                client,
                workspace,
                BlogConverter(config.site_url),
                SqlAlchemyBlogResultStore(self.session_factory),
                remote_url=remote,
                token=config.token,
            )
            return await publisher.publish(claim)

    async def _configuration(self) -> _Configuration:
        async with self.session_factory() as session:
            integration = await IntegrationRepository(session).get_by_provider("github")
        if integration is None or integration.encrypted_secret is None:
            raise BlockedPublishError("GitHub 集成尚未配置")
        try:
            secret = self.secret_box.decrypt(integration.encrypted_secret)
        except SecretBoxError as exc:
            raise BlockedPublishError("GitHub Secret 无法解密，请重新配置") from exc
        public = integration.public_config
        owner = _field(public, "owner")
        repo = _field(public, "repo")
        site_url = _field(public, "site_url")
        token = secret.get("token")
        if not token:
            raise BlockedPublishError("GitHub Token 尚未配置")
        return _Configuration(owner, repo, site_url, token)


def _field(config: dict[str, object], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise BlockedPublishError(f"GitHub {key} 尚未配置")
    return value
