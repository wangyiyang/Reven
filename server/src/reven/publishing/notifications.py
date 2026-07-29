"""跨发布阶段共享的通知契约。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Notification:
    title: str
    stage: str
    summary: str
    links: dict[str, str]


class DeliveryNotifier(Protocol):
    async def send(self, notification: Notification) -> None: ...
