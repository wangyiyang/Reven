import shlex
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import public_config_without_hint
from reven.integrations.wechat.client import WeChatClient
from reven.jobs.errors import BlockedPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.wechat.publisher import WeChatPublisher
from reven.publishing.wechat.renderer import WechatRenderer
from reven.publishing.wechat.store import SqlAlchemyWeChatResultStore
from reven.security.secrets import SecretBox, SecretBoxError


@dataclass(frozen=True)
class _Configuration:
    app_id: str
    app_secret: str
    author: str


class ConfiguredWeChatPublisher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        data_root: Path,
        renderer_command: str,
        *,
        wechat_transport: httpx.AsyncBaseTransport | None = None,
        sandbox_executable: Path | None = Path("/usr/bin/bwrap"),
    ) -> None:
        self.session_factory = session_factory
        self.secret_box = secret_box
        self.data_root = data_root
        self.renderer_command = renderer_command
        self.wechat_transport = wechat_transport
        self.sandbox_executable = sandbox_executable

    async def publish(self, claim: JobClaim):  # type: ignore[no-untyped-def]
        config = await self._load_configuration()
        async with httpx.AsyncClient(
            base_url="https://api.weixin.qq.com",
            transport=self.wechat_transport,
            trust_env=False,
        ) as wechat_http:
            executable, cli_path = _renderer_parts(self.renderer_command)
            publisher = WeChatPublisher(
                WeChatClient(config.app_id, config.app_secret, wechat_http),
                WechatRenderer(executable, cli_path, sandbox_executable=self.sandbox_executable),
                SqlAlchemyWeChatResultStore(
                    self.session_factory,
                    author=config.author,
                ),
            )
            return await publisher.publish(claim)

    async def _load_configuration(self) -> _Configuration:
        async with self.session_factory() as session:
            repository = IntegrationRepository(session)
            wechat = await repository.get_by_provider("wechat")
        if wechat is None or wechat.encrypted_secret is None:
            raise BlockedPublishError("微信集成尚未配置")
        try:
            wechat_secret = self.secret_box.decrypt(wechat.encrypted_secret)
        except SecretBoxError as exc:
            raise BlockedPublishError("集成 Secret 无法解密，请重新配置") from exc
        public = public_config_without_hint(wechat)
        app_id = public.get("app_id")
        if not isinstance(app_id, str) or not app_id:
            raise BlockedPublishError("微信 AppID 尚未配置")
        app_secret = wechat_secret.get("app_secret")
        if not app_secret:
            raise BlockedPublishError("微信 Secret 尚未配置")
        return _Configuration(
            app_id,
            app_secret,
            str(public.get("author", "")),
        )


class ConfiguredWeChatPublisherFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        data_root: Path,
        renderer_command: str,
    ) -> None:
        self.session_factory = session_factory
        self.secret_box = secret_box
        self.data_root = data_root
        self.renderer_command = renderer_command

    def build(self) -> ConfiguredWeChatPublisher:
        return ConfiguredWeChatPublisher(
            self.session_factory,
            self.secret_box,
            self.data_root,
            self.renderer_command,
        )


def _renderer_parts(command: str) -> tuple[str, str]:
    parts = shlex.split(command)
    if len(parts) != 2:
        raise BlockedPublishError("微信渲染器命令配置无效")
    return parts[0], parts[1]
