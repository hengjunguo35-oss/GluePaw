"""业务层：把「内存暂存区」和「加密数据库」合成统一的行为。

状态机
------
一条记录只有两种存放位置：
  mem  内存暂存区（敏感、未收藏、隐私模式开启）—— 有倒计时，到点删除
  db   加密数据库 —— 永久保存（除非被自动清理或手动删除）

关键规则
--------
- 敏感 + 未收藏        → 内存；倒计时结束即删除，并清空匹配的系统剪贴板
- 敏感 + 已收藏        → 数据库；倒计时照走，但到点不删
- 计时内取消收藏        → 退回内存，继承剩余时间
- 计时后取消收藏        → 立即删除
- 普通 + 已收藏        → 永久保存，任何自动清理都豁免
- 关闭隐私模式          → 内存内容全部转存数据库并取消倒计时
- 重新标记为敏感        → 以「此刻」的保留时长重新计时（策略快照）
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import config
from ephemeral import EphemeralStore
from sensitive import DROP, MASK, classify
from store import Store


@dataclass
class ViewItem:
    key: str
    text: str
    created_at: float
    last_used_at: float
    favorite: bool
    sensitive: bool
    expires_at: Optional[float]     # 墙钟时间；None 表示没有倒计时
    ttl: Optional[float]
    source: str                     # "db" | "mem"
    use_count: int = 1

    def remaining(self) -> Optional[float]:
        if self.expires_at is None:
            return None
        return max(0.0, self.expires_at - time.time())


class Repository:
    def __init__(self, store: Store, ephemeral: EphemeralStore) -> None:
        self.store = store
        self.ephemeral = ephemeral

    # ---------- 设置 ----------

    @property
    def privacy_on(self) -> bool:
        return bool(self.store.get_setting("privacy_on", config.DEFAULT_PRIVACY_ON))

    @property
    def theme_mode(self) -> str:
        value = self.store.get_setting("theme_mode", "system")
        return value if value in ("system", "light", "dark") else "system"

    @property
    def pin_on_top(self) -> bool:
        return bool(self.store.get_setting("pin_on_top", False))

    @property
    def ttl(self) -> float:
        value = self.store.get_setting("ttl_seconds", config.DEFAULT_TTL_SECONDS)
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            seconds = float(config.DEFAULT_TTL_SECONDS)
        low = config.TTL_MIN_MINUTES * 60
        high = config.TTL_MAX_MINUTES * 60
        return max(low, min(high, seconds))

    @property
    def auto_clear_on(self) -> bool:
        return bool(self.store.get_setting("auto_clear_on", config.DEFAULT_AUTO_CLEAR_ON))

    @property
    def auto_clear_months(self) -> int:
        value = self.store.get_setting("auto_clear_months", config.DEFAULT_AUTO_CLEAR_MONTHS)
        try:
            months = int(value)
        except (TypeError, ValueError):
            months = config.DEFAULT_AUTO_CLEAR_MONTHS
        if months not in config.AUTO_CLEAR_PRESETS:
            months = config.DEFAULT_AUTO_CLEAR_MONTHS
        return months

    def _auto_clear_snapshot(self) -> Optional[int]:
        return self.auto_clear_months if self.auto_clear_on else None

    # ---------- 采集 ----------

    def capture(self, text: str) -> str:
        """剪贴板监听到新内容后的统一入口。

        返回值供上层决定是否提示：
          empty / too_large  忽略
          dropped            命中「绝不记录」规则（私钥等），静默丢弃
          ephemeral          进入内存暂存区，开始倒计时
          stored             写入加密数据库
        """
        # 空白内容与超大内容直接忽略，避免污染历史、撑爆数据库
        if not text or not text.strip():
            return "empty"
        if len(text) > config.MAX_ITEM_CHARS:
            return "too_large"

        # 三级判定：drop 完全不记 / mask 敏感 / record 普通
        verdict = classify(text)
        if verdict == DROP:
            return "dropped"

        if self.privacy_on and verdict == MASK:
            # 已经被收藏（在数据库里）的敏感内容，再次复制只更新使用时间
            existing = self.store.lookup(text)
            if existing is not None:
                self.store.touch(int(existing["id"]))
                return "stored"
            # 同一敏感内容重复复制：重置倒计时，而不是产生多条
            if self.ephemeral.refresh_text(text, self.ttl):
                return "ephemeral"
            self.ephemeral.add(text, self.ttl, self._auto_clear_snapshot())
            return "ephemeral"

        self.store.upsert(
            text,
            sensitive=(verdict == MASK),
            ttl_snapshot=None,
            auto_clear_months=self._auto_clear_snapshot(),
            sensitive_expires_at=None,
            favorite_at=None,
        )
        return "stored"

    # ---------- 查询 ----------

    def list_items(self, query: str = "", favorites_only: bool = False) -> list[ViewItem]:
        now_wall = time.time()
        now_mono = time.monotonic()
        items: list[ViewItem] = []

        for row in self.store.list_items():
            favorite = row["favorite_at"] is not None
            if favorites_only and not favorite:
                continue
            items.append(
                ViewItem(
                    key=f"db:{row['id']}",
                    text=row["text"],
                    created_at=row["created_at"],
                    last_used_at=row["last_used_at"],
                    favorite=favorite,
                    sensitive=row["sensitive"],
                    expires_at=row["sensitive_expires_at"],
                    ttl=row["ttl_snapshot"],
                    source="db",
                    use_count=row["use_count"],
                )
            )

        if not favorites_only:
            for item in self.ephemeral.items():
                text = self.ephemeral.reveal(item.eid)
                if text is None:
                    continue
                remaining = max(0.0, item.deadline - now_mono)
                items.append(
                    ViewItem(
                        key=f"mem:{item.eid}",
                        text=text,
                        created_at=item.created_at,
                        last_used_at=item.last_used_at,
                        favorite=False,
                        sensitive=True,
                        expires_at=now_wall + remaining,
                        ttl=item.ttl,
                        source="mem",
                    )
                )

        needle = query.strip().lower()
        if needle:
            items = [i for i in items if needle in i.text.lower()]

        items.sort(key=lambda i: i.last_used_at, reverse=True)
        return items

    def find(self, key: str) -> Optional[ViewItem]:
        if key.startswith("mem:"):
            eid = key[4:]
            item = self.ephemeral.get(eid)
            if item is None:
                return None
            text = self.ephemeral.reveal(eid) or ""
            return ViewItem(
                key=key,
                text=text,
                created_at=item.created_at,
                last_used_at=item.last_used_at,
                favorite=False,
                sensitive=True,
                expires_at=time.time() + self.ephemeral.remaining(item),
                ttl=item.ttl,
                source="mem",
            )
        try:
            item_id = int(key.split(":", 1)[1])
        except (IndexError, ValueError):
            return None
        row = self.store.get(item_id)
        if row is None:
            return None
        return ViewItem(
            key=key,
            text=row["text"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            favorite=row["favorite_at"] is not None,
            sensitive=row["sensitive"],
            expires_at=row["sensitive_expires_at"],
            ttl=row["ttl_snapshot"],
            source="db",
        )

    # ---------- 操作 ----------

    def touch(self, key: str) -> None:
        if key.startswith("mem:"):
            self.ephemeral.touch(key[4:])
        else:
            try:
                self.store.touch(int(key.split(":", 1)[1]))
            except (IndexError, ValueError):
                pass

    def favorite(self, key: str) -> str:
        """收藏一条记录。

        - 内存条目：先加密写入数据库（把剩余倒计时一并带过去），再从内存移除
        - 数据库条目：只更新 favorite_at

        注意：收藏只负责「拦住删除」，不暂停敏感倒计时。
        """
        if key.startswith("mem:"):
            eid = key[4:]
            item = self.ephemeral.get(eid)
            if item is None:
                return "missing"
            text = self.ephemeral.reveal(eid)
            if text is None:
                return "missing"
            remaining = max(0.0, item.deadline - time.monotonic())
            now = time.time()
            self.store.upsert(
                text,
                sensitive=True,
                ttl_snapshot=item.ttl,
                auto_clear_months=item.auto_clear_months,
                sensitive_expires_at=now + remaining,
                favorite_at=now,
            )
            self.ephemeral.remove(eid)
            return "favorited"

        try:
            item_id = int(key.split(":", 1)[1])
        except (IndexError, ValueError):
            return "missing"
        self.store.set_favorite(item_id, time.time())
        return "favorited"

    def unfavorite(self, key: str) -> str:
        """取消收藏，行为取决于敏感倒计时是否已经走完。

        reverted    计时未结束 → 退回内存，继承剩余时间（不重置）
        deleted     计时已结束 → 立即删除，不可恢复
        unfavorited 普通内容   → 只清除收藏标记
        """
        if key.startswith("mem:"):
            return "not_favorited"
        try:
            item_id = int(key.split(":", 1)[1])
        except (IndexError, ValueError):
            return "missing"
        row = self.store.get(item_id)
        if row is None:
            return "missing"

        now = time.time()
        if row["sensitive"] and row["sensitive_expires_at"]:
            expires = float(row["sensitive_expires_at"])
            if now >= expires:
                self.store.delete(item_id)
                return "deleted"
            # 计时未结束：退回内存，继承剩余时间
            self.ephemeral.add(
                row["text"],
                ttl=max(1.0, expires - now),
                auto_clear_months=row["auto_clear_months"],
                created_at=row["created_at"],
                last_used_at=row["last_used_at"],
            )
            self.store.delete(item_id)
            return "reverted"

        self.store.set_favorite(item_id, None)
        return "unfavorited"

    def delete(self, key: str) -> bool:
        """删除单条记录（内存或数据库）。"""
        if key.startswith("mem:"):
            return self.ephemeral.remove(key[4:]) is not None
        try:
            item_id = int(key.split(":", 1)[1])
        except (IndexError, ValueError):
            return False
        if self.store.get(item_id) is None:
            return False
        self.store.delete(item_id)
        return True

    def set_sensitive(self, key: str, sensitive: bool) -> str:
        """手动切换敏感标记，规则如下：

        敏感 → 普通：
          内存条目   → 写入数据库，作为普通记录长期保存
          数据库条目 → 清除敏感标记与倒计时
        普通 → 敏感：
          隐私模式关 → 只打标记（显示时打码），不设倒计时
          已收藏     → 保留在数据库，但按当前设置重新开始倒计时
          未收藏     → 移入内存暂存区，重新计时（不落盘）

        「重新计时」严格使用点击这一刻的保留时长，而不是记录创建时的设置。
        """
        if key.startswith("mem:"):
            eid = key[4:]
            item = self.ephemeral.get(eid)
            if item is None:
                return "missing"
            if sensitive:
                return "noop"
            text = self.ephemeral.reveal(eid)
            if text is None:
                return "missing"
            self.store.upsert(
                text,
                sensitive=False,
                ttl_snapshot=None,
                auto_clear_months=self._auto_clear_snapshot(),
                sensitive_expires_at=None,
                favorite_at=None,
            )
            self.ephemeral.remove(eid)
            return "stored"

        try:
            item_id = int(key.split(":", 1)[1])
        except (IndexError, ValueError):
            return "missing"
        row = self.store.get(item_id)
        if row is None:
            return "missing"
        if bool(row["sensitive"]) == sensitive:
            return "noop"

        if not sensitive:
            self.store.set_sensitivity(item_id, False, None, None)
            return "normal"

        if not self.privacy_on:
            self.store.set_sensitivity(item_id, True, None, None)
            return "sensitive"

        ttl = self.ttl
        now = time.time()
        if row["favorite_at"] is not None:
            # 收藏条目永久保存，但敏感计时照走
            self.store.set_sensitivity(item_id, True, now + ttl, ttl)
            return "sensitive"

        # 未收藏且隐私模式开启：转入内存，重新开始计时
        self.store.delete(item_id)
        self.ephemeral.add(row["text"], ttl, self._auto_clear_snapshot())
        return "ephemeral"

    def is_expired_favorite(self, key: str) -> bool:
        if key.startswith("mem:"):
            return False
        try:
            item_id = int(key.split(":", 1)[1])
        except (IndexError, ValueError):
            return False
        row = self.store.get(item_id)
        if row is None:
            return False
        if not row["sensitive"] or not row["sensitive_expires_at"]:
            return False
        return time.time() >= float(row["sensitive_expires_at"])

    # ---------- 隐私模式 ----------

    def set_privacy(self, on: bool) -> int:
        """开关隐私模式。

        关闭时把内存暂存区里的所有条目转存进加密数据库，并取消倒计时，
        返回迁移条数（用于提示用户「N 条内容已永久保存」）。
        开启时不做任何迁移：新复制的敏感内容才会走临时保留。
        """
        self.store.set_setting("privacy_on", bool(on))
        if on:
            return 0
        migrated = 0
        for item in list(self.ephemeral.items()):
            text = self.ephemeral.reveal(item.eid)
            if text is None:
                continue
            self.store.upsert(
                text,
                sensitive=True,
                ttl_snapshot=None,
                auto_clear_months=None,
                sensitive_expires_at=None,
                favorite_at=None,
            )
            self.ephemeral.remove(item.eid)
            migrated += 1
        return migrated

    # ---------- 清理 ----------

    def sweep(self) -> list[str]:
        return [text for _, text in self.ephemeral.sweep()]

    def auto_cleanup(self) -> int:
        return self.store.purge_auto_clear()

    def clear_all(self) -> int:
        self.ephemeral.clear()
        return self.store.clear_all()

    def count(self) -> int:
        return self.store.count() + self.ephemeral.count()
