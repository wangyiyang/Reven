"""Template config cache — SQLite 缓存固化后的 ParsingConfig。

以 header_signature（表头列名集指纹）为键，避免同一格式重复调用 LLM。
缓存命中后按规则匹配器同等置信度对待。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from reven.intelligence.settings import CACHE_DB_PATH
from reven.importing.config import ParsingConfig


class TemplateCache:
    """模板配置缓存。

    键：header_signature 的稳定字符串表示（列名拼接）。
    值：ParsingConfig 的 JSON 序列化 + 确认时间 + 来源标记。

    线程安全（单文件 SQLite, WAL 模式）。
    """

    def __init__(self, db_path: str = CACHE_DB_PATH) -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接。"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """初始化表结构。"""
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS template_cache (
                signature_hash TEXT PRIMARY KEY,
                header_signature TEXT NOT NULL,
                config_json TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'confirmed',
                confirmed_at TEXT NOT NULL DEFAULT (datetime('now')),
                hit_count INTEGER NOT NULL DEFAULT 1,
                last_hit_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()

    @staticmethod
    def _signature_key(header_signature: list[str]) -> str:
        """将 header_signature 转为稳定哈希键。

        使用列名集合的排序后 SHA-256 前缀（16 位），与 fingerprint 的 content_hash 风格一致。
        """
        import hashlib

        canonical = "||".join(sorted(header_signature))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def get(self, fp: Any) -> ParsingConfig | None:
        """根据结构指纹查找缓存。

        Args:
            fp: SheetFingerprint 对象（需有 header_signature 属性）。

        Returns:
            命中则返回 ParsingConfig（source="cache"），否则返回 None。
        """
        sig = fp.header_signature
        if not sig:
            return None
        key = self._signature_key(sig)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT config_json, hit_count FROM template_cache WHERE signature_hash = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None

        # 更新命中统计
        conn.execute(
            "UPDATE template_cache SET hit_count = ?, last_hit_at = datetime('now') WHERE signature_hash = ?",
            (row["hit_count"] + 1, key),
        )
        conn.commit()

        config_dict = json.loads(row["config_json"])
        config_dict["source"] = "cache"
        return ParsingConfig.from_dict(config_dict)

    def put(self, config: ParsingConfig, header_signature: list[str] | None = None) -> None:
        """写入缓存条目。

        Args:
            config: 已通过人工确认的 ParsingConfig。
            header_signature: 表头列名签名（用于缓存键）。
                如果为 None，则从 config 的 column_mappings 提取 source_name。
                建议传入完整的 header_signature 以确保键一致性。
        """
        if header_signature is None:
            sig = [cm.source_name or "" for cm in config.column_mappings if cm.source_name]
        else:
            sig = header_signature
        if not sig:
            return
        key = self._signature_key(sig)
        config_json = json.dumps(config.to_dict(), ensure_ascii=False)

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO template_cache (signature_hash, header_signature, config_json, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(signature_hash) DO UPDATE SET
                config_json = excluded.config_json,
                source = excluded.source,
                confirmed_at = datetime('now')
            """,
            (key, json.dumps(sig, ensure_ascii=False), config_json, config.source),
        )
        conn.commit()

    def list_entries(self) -> list[dict[str, Any]]:
        """列出所有缓存条目（用于管理界面）。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT signature_hash, header_signature, source, confirmed_at, hit_count FROM template_cache ORDER BY hit_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def clear(self) -> None:
        """清空缓存（用于测试 / 管理）。"""
        conn = self._get_conn()
        conn.execute("DELETE FROM template_cache")
        conn.commit()
