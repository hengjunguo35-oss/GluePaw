"""敏感内容的临时暂存区：只存在于内存，进程退出即消失。

为什么不落盘
------------
「保存几分钟再删除」如果实现成「先加密写库、到点再删」，会留下三类痕迹：
SSD 磨损均衡无法保证物理覆写、SQLite 的 WAL/journal 里仍有副本、备份软件
可能已经抓取过。所以敏感内容从生成到过期全程不接触磁盘，进程结束即彻底销毁。

计时方式
--------
使用 time.monotonic() 而不是墙钟时间：用户改系统时间、时区或夏令时都不会
让倒计时跳变或提前到期。只有把条目迁移进数据库（收藏、关闭隐私模式）时，
才会换算成墙钟时间戳。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

from vaultcrypto import SessionCipher


@dataclass
class EphemeralItem:
    eid: str
    created_at: float          # 墙钟时间，仅用于显示
    deadline: float            # time.monotonic()，用于倒计时
    ttl: float
    auto_clear_months: Optional[int]
    blob: bytes
    last_used_at: float


class EphemeralStore:
    def __init__(self) -> None:
        self._cipher = SessionCipher()
        self._items: dict[str, EphemeralItem] = {}

    def add(
        self,
        text: str,
        ttl: float,
        auto_clear_months: Optional[int] = None,
        created_at: Optional[float] = None,
        last_used_at: Optional[float] = None,
    ) -> EphemeralItem:
        now = time.time()
        item = EphemeralItem(
            eid=uuid.uuid4().hex[:12],
            created_at=created_at if created_at is not None else now,
            deadline=time.monotonic() + float(ttl),
            ttl=float(ttl),
            auto_clear_months=auto_clear_months,
            blob=self._cipher.encrypt(text),
            last_used_at=last_used_at if last_used_at is not None else now,
        )
        self._items[item.eid] = item
        return item

    def get(self, eid: str) -> Optional[EphemeralItem]:
        return self._items.get(eid)

    def reveal(self, eid: str) -> Optional[str]:
        item = self._items.get(eid)
        if item is None:
            return None
        try:
            return self._cipher.decrypt(item.blob)
        except Exception:
            return None

    def remaining(self, item: EphemeralItem) -> float:
        return max(0.0, item.deadline - time.monotonic())

    def touch(self, eid: str) -> None:
        item = self._items.get(eid)
        if item is not None:
            item.last_used_at = time.time()

    def find_text(self, text: str) -> Optional[EphemeralItem]:
        for item in self._items.values():
            if self.reveal(item.eid) == text:
                return item
        return None

    def refresh_text(self, text: str, ttl: float) -> bool:
        item = self.find_text(text)
        if item is None:
            return False
        item.deadline = time.monotonic() + float(ttl)
        item.last_used_at = time.time()
        return True

    def sweep(self) -> list[tuple[str, str]]:
        """移除已到期的条目并返回 (eid, 明文)，供上层同步清理剪贴板。"""
        now = time.monotonic()
        doomed = [i for i in self._items.values() if i.deadline <= now]
        removed: list[tuple[str, str]] = []
        for item in doomed:
            text = self.reveal(item.eid)
            self._items.pop(item.eid, None)
            if text is not None:
                removed.append((item.eid, text))
        return removed

    def remove(self, eid: str) -> Optional[EphemeralItem]:
        return self._items.pop(eid, None)

    def clear(self) -> None:
        self._items.clear()

    def items(self) -> list[EphemeralItem]:
        return list(self._items.values())

    def count(self) -> int:
        return len(self._items)
