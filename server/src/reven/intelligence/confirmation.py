"""Manual confirmation queue — 置信度不足时的人工确认队列。

入队条件：
- LLM 三次失败后
- 后验置信度 < 0.6
- weak_pass + LLM 来源

队列形态：SQLite 表（文件路径、指纹、候选配置、状态）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any

from reven.intelligence.settings import CONFIRMATION_DB_PATH


class ConfirmationQueue:
    """人工确认队列。

    每个条目代表一个需要人工确认的解析任务。
    确认结果：
        - approved: 配置写入缓存（TemplateCache.put）
        - rejected: 标注原因（可作为黄金案例入库素材）
    """

    def __init__(self, db_path: str = CONFIRMATION_DB_PATH) -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS confirmation_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                header_signature TEXT NOT NULL,
                config_json TEXT,
                confidence REAL NOT NULL DEFAULT 0.0,
                error TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                resolved_at TEXT,
                resolution TEXT,
                resolution_note TEXT
            )
            """
        )
        conn.commit()

    def enqueue(
        self,
        *,
        file_path: str,
        header_signature: list[str],
        config_dict: dict[str, Any] | None,
        confidence: float,
        error: str | None = None,
    ) -> int:
        """将一条记录加入人工确认队列。

        Returns:
            插入记录的 id。
        """
        conn = self._get_conn()
        cur = conn.execute(
            """
            INSERT INTO confirmation_queue
                (file_path, header_signature, config_json, confidence, error)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                file_path,
                json.dumps(header_signature, ensure_ascii=False),
                json.dumps(config_dict, ensure_ascii=False) if config_dict else None,
                confidence,
                error,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0

    def list_pending(self) -> list[dict[str, Any]]:
        """列出所有待人工确认的条目（按创建时间升序）。"""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT id, file_path, header_signature, config_json, confidence, error, created_at
            FROM confirmation_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC
            """
        ).fetchall()
        result: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            item["header_signature"] = json.loads(r["header_signature"])
            if r["config_json"]:
                item["config"] = json.loads(r["config_json"])
            else:
                item["config"] = None
            del item["config_json"]
            result.append(item)
        return result

    def approve(self, item_id: int, note: str = "") -> bool:
        """批准确认条目（状态 → 'approved'）。"""
        conn = self._get_conn()
        cur = conn.execute(
            """
            UPDATE confirmation_queue
            SET status = 'approved', resolved_at = datetime('now'), resolution = 'approved', resolution_note = ?
            WHERE id = ? AND status = 'pending'
            """,
            (note, item_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def reject(self, item_id: int, reason: str) -> bool:
        """驳回条目（状态 → 'rejected'）。"""
        conn = self._get_conn()
        cur = conn.execute(
            """
            UPDATE confirmation_queue
            SET status = 'rejected', resolved_at = datetime('now'), resolution = 'rejected', resolution_note = ?
            WHERE id = ? AND status = 'pending'
            """,
            (reason, item_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def stats(self) -> dict[str, int]:
        """队列统计。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM confirmation_queue GROUP BY status"
        ).fetchall()
        stats: dict[str, int] = {"pending": 0, "approved": 0, "rejected": 0}
        for r in rows:
            stats[r["status"]] = r["cnt"]
        return stats
