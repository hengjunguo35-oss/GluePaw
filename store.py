"""SQLite 加密持久化存储。

表结构
------
items     每条剪贴板记录一行。content 是密文 BLOB，blind 是 HMAC 盲索引
          （唯一索引，用于去重）。其余字段保存「出生时的策略快照」：
          是否敏感、敏感倒计时截止时间、自动清理周期。改设置只影响新记录，
          不追溯旧记录。
settings  键值表，保存隐私模式、保留时长、主题、置顶等设置。

设计要点
--------
- WAL 模式：读写不互相阻塞，弹窗查询历史时不会卡住剪贴板的写入。
- secure_delete=ON：删除时覆写页面，避免已删内容残留在数据库文件里。
- 自动清理按每条记录自己的 auto_clear_months 判断，收藏记录永远豁免。
- 去重走 blind 唯一索引：同一条内容重复复制只更新 last_used_at / use_count。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from vaultcrypto import VaultCrypto

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  content              BLOB    NOT NULL,
  blind                TEXT    NOT NULL,
  sensitive            INTEGER NOT NULL DEFAULT 0,
  favorite_at          REAL,
  sensitive_expires_at REAL,
  ttl_snapshot         REAL,
  auto_clear_months    INTEGER,
  source_app           TEXT,
  size                 INTEGER NOT NULL DEFAULT 0,
  created_at           REAL    NOT NULL,
  last_used_at         REAL    NOT NULL,
  use_count            INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_blind ON items(blind);
CREATE INDEX IF NOT EXISTS idx_items_last ON items(last_used_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_fav ON items(favorite_at);
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path, crypto: VaultCrypto) -> None:
        self._crypto = crypto
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------- 条目 ----------

    def upsert(
        self,
        text: str,
        *,
        sensitive: bool,
        ttl_snapshot: Optional[float] = None,
        auto_clear_months: Optional[int] = None,
        sensitive_expires_at: Optional[float] = None,
        favorite_at: Optional[float] = None,
        source_app: Optional[str] = None,
    ) -> tuple[int, bool]:
        """写入或刷新一条记录，返回 (id, 是否新建)。"""
        now = time.time()
        blind = self._crypto.blind(text)
        row = self._conn.execute("SELECT * FROM items WHERE blind = ?", (blind,)).fetchone()
        if row is not None:
            merged_fav = favorite_at if favorite_at is not None else row["favorite_at"]
            expires = (
                sensitive_expires_at
                if sensitive_expires_at is not None
                else row["sensitive_expires_at"]
            )
            self._conn.execute(
                "UPDATE items SET last_used_at = ?, use_count = use_count + 1, sensitive = ?, "
                "sensitive_expires_at = ?, favorite_at = ?, "
                "auto_clear_months = COALESCE(?, auto_clear_months) WHERE id = ?",
                (now, int(sensitive), expires, merged_fav, auto_clear_months, row["id"]),
            )
            self._conn.commit()
            return int(row["id"]), False

        blob = self._crypto.encrypt(text)
        cur = self._conn.execute(
            "INSERT INTO items(content, blind, sensitive, favorite_at, sensitive_expires_at, "
            "ttl_snapshot, auto_clear_months, source_app, size, created_at, last_used_at, use_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                blob,
                blind,
                int(sensitive),
                favorite_at,
                sensitive_expires_at,
                ttl_snapshot,
                auto_clear_months,
                source_app,
                len(text.encode("utf-8")),
                now,
                now,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid), True

    def list_items(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM items ORDER BY last_used_at DESC").fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                text = self._crypto.decrypt(row["content"])
            except Exception:
                continue
            result.append(
                {
                    "id": int(row["id"]),
                    "text": text,
                    "sensitive": bool(row["sensitive"]),
                    "favorite_at": row["favorite_at"],
                    "sensitive_expires_at": row["sensitive_expires_at"],
                    "ttl_snapshot": row["ttl_snapshot"],
                    "auto_clear_months": row["auto_clear_months"],
                    "source_app": row["source_app"],
                    "created_at": row["created_at"],
                    "last_used_at": row["last_used_at"],
                    "use_count": int(row["use_count"]),
                }
            )
        return result

    def get(self, item_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "text": self._crypto.decrypt(row["content"]),
            "sensitive": bool(row["sensitive"]),
            "favorite_at": row["favorite_at"],
            "sensitive_expires_at": row["sensitive_expires_at"],
            "ttl_snapshot": row["ttl_snapshot"],
            "auto_clear_months": row["auto_clear_months"],
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
        }

    def lookup(self, text: str):
        """按内容查找已存在的记录（用盲索引，不比对明文）。"""
        blind = self._crypto.blind(text)
        return self._conn.execute("SELECT * FROM items WHERE blind = ?", (blind,)).fetchone()

    def touch(self, item_id: int) -> None:
        self._conn.execute(
            "UPDATE items SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
            (time.time(), item_id),
        )
        self._conn.commit()

    def set_favorite(self, item_id: int, timestamp: Optional[float]) -> None:
        self._conn.execute(
            "UPDATE items SET favorite_at = ? WHERE id = ?", (timestamp, item_id)
        )
        self._conn.commit()

    def set_sensitivity(
        self,
        item_id: int,
        sensitive: bool,
        expires_at: Optional[float],
        ttl_snapshot: Optional[float],
    ) -> None:
        self._conn.execute(
            "UPDATE items SET sensitive = ?, sensitive_expires_at = ?, ttl_snapshot = ? "
            "WHERE id = ?",
            (int(sensitive), expires_at, ttl_snapshot, item_id),
        )
        self._conn.commit()

    def delete(self, item_id: int) -> None:
        self._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self._conn.commit()

    def clear_all(self) -> int:
        count = self.count()
        self._conn.execute("DELETE FROM items")
        self._conn.commit()
        self._conn.execute("VACUUM")
        return count

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()
        return int(row["c"]) if row else 0

    def purge_auto_clear(self) -> int:
        """按每条记录自己的周期快照清理（收藏的永远豁免）。"""
        now = time.time()
        rows = self._conn.execute(
            "SELECT id, auto_clear_months, last_used_at FROM items "
            "WHERE favorite_at IS NULL AND auto_clear_months IS NOT NULL"
        ).fetchall()
        doomed = [
            int(r["id"])
            for r in rows
            if now - float(r["last_used_at"]) > float(r["auto_clear_months"]) * 30 * 86400
        ]
        if doomed:
            self._conn.executemany("DELETE FROM items WHERE id = ?", [(i,) for i in doomed])
            self._conn.commit()
            self._conn.execute("VACUUM")
        return len(doomed)

    # ---------- 设置 ----------

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return default

    def set_setting(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
        except Exception:
            pass
