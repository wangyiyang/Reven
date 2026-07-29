from dataclasses import dataclass


class WeChatError(Exception):
    """只包含固定分类信息的微信请求错误。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{message}（code={code}）")


class WeChatBlockedError(WeChatError):
    """配置、白名单或权限需要人工修复。"""


class WeChatTransientError(WeChatError):
    """网络、限流或服务端临时故障。"""


class WeChatPermanentError(WeChatError):
    """确定性的请求或响应错误。"""


@dataclass(frozen=True)
class WeChatPublishResult:
    media_id: str
    content: str | None = None
