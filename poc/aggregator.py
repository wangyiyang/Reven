"""
SessionAggregator — 消息配对聚合器

将同一会话 (chat_id) 同一发送者在 N 秒窗口内的
text 消息与 file/image 消息聚合为一次请求。

核心机制：feed 方法只负责缓存，tick() 负责统一派发。
这样所有路径都通过窗口超时触发，行为可预测。
"""

import threading
import time
from typing import Optional


class AggregatedSession:
    """一次聚合会话的结果"""

    def __init__(self, chat_id: str, sender_id: str):
        self.chat_id = chat_id
        self.sender_id = sender_id
        self.text: Optional[str] = None
        self.text_message_id: Optional[str] = None
        self.files: list[dict] = []
        self.first_event_time: float = 0.0
        self.last_event_time: float = 0.0

    @property
    def has_text(self) -> bool:
        return self.text is not None

    @property
    def has_files(self) -> bool:
        return len(self.files) > 0

    def add_text(self, message_id: str, text: str, timestamp: float):
        if not self.has_text:
            self.text = text
            self.text_message_id = message_id
        if self.first_event_time == 0:
            self.first_event_time = timestamp
        self.last_event_time = timestamp

    def add_file(self, message_id: str, file_key: str, file_name: str,
                 msg_type: str, timestamp: float):
        self.files.append({
            "message_id": message_id,
            "file_key": file_key,
            "file_name": file_name,
            "msg_type": msg_type,
        })
        if self.first_event_time == 0:
            self.first_event_time = timestamp
        self.last_event_time = timestamp

    def reset(self):
        self.text = None
        self.text_message_id = None
        self.files.clear()
        self.first_event_time = 0.0
        self.last_event_time = 0.0


class SessionAggregator:
    """
    消息配对聚合器。

    feed_text / feed_file 只缓存消息、绝不阻塞。
    tick() 定时扫描，返回超时会话（距 last_event 超过 window_seconds）。

    覆盖路径：
    - 先文字后文件 → 窗口到期后聚合
    - 先文件后文字 → 窗口到期后聚合
    - 只有文字 → 窗口到期后成一次请求
    - 只有文件 → 窗口到期后按"无指令附件"处理
    - 窗口内多文件 → 聚合为同一请求的多附件
    """

    def __init__(self, window_seconds: float = 15.0):
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._sessions: dict[tuple[str, str], AggregatedSession] = {}
        self._processed_ids: set[str] = set()

    def is_duplicate(self, message_id: str) -> bool:
        return message_id in self._processed_ids

    def mark_processed(self, message_id: str):
        self._processed_ids.add(message_id)

    def feed_text(self, chat_id: str, sender_id: str,
                  message_id: str, text: str,
                  timestamp: Optional[float] = None) -> Optional[AggregatedSession]:
        """
        缓存一条文字消息。

        如果该会话已有文字（即新的独立消息），
        返回旧会话以立即处理，同时用新文字创建新会话。

        Returns:
            None — 继续等待配对
            AggregatedSession — 旧会话需立即处理
        """
        ts = timestamp or time.time()
        key = (chat_id, sender_id)

        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = AggregatedSession(chat_id, sender_id)

            session = self._sessions[key]

            # 已有不同文字 → 旧会话超时，新会话开始
            if session.has_text and session.text_message_id != message_id:
                old = session
                self._sessions[key] = AggregatedSession(chat_id, sender_id)
                self._sessions[key].add_text(message_id, text, ts)
                return old

            session.add_text(message_id, text, ts)
            return None

    def feed_file(self, chat_id: str, sender_id: str,
                  message_id: str, file_key: str, file_name: str,
                  msg_type: str,
                  timestamp: Optional[float] = None) -> None:
        """
        缓存一条文件/图片消息，等待配对或超时。
        从不立即返回会话——统一由 tick() 派发。
        """
        ts = timestamp or time.time()
        key = (chat_id, sender_id)

        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = AggregatedSession(chat_id, sender_id)

            session = self._sessions[key]
            session.add_file(message_id, file_key, file_name, msg_type, ts)

    def tick(self, timestamp: Optional[float] = None) -> list[AggregatedSession]:
        """
        时钟驱动：返回所有超时会话（距 last_event 超过 window_seconds）。
        """
        ts = timestamp or time.time()
        expired: list[AggregatedSession] = []

        with self._lock:
            expired_keys = [
                k for k, s in self._sessions.items()
                if (ts - s.last_event_time) >= self.window_seconds
            ]
            for k in expired_keys:
                expired.append(self._sessions.pop(k))

        return expired

    def session_count(self) -> int:
        """当前缓存的会话数"""
        with self._lock:
            return len(self._sessions)

    def cleanup_processed(self, max_size: int = 10000):
        """清理去重集合，防止内存泄漏"""
        if len(self._processed_ids) > max_size:
            self._processed_ids.clear()
