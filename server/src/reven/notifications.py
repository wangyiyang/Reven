"""Shared notification contract. 生产投递实现（FeishuNotifier）见 provider_clients.py。"""

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
