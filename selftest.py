"""无需 GUI 的核心逻辑自测：python selftest.py"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE / "libs") not in sys.path:
    sys.path.insert(0, str(_HERE / "libs"))

from ephemeral import EphemeralStore
from repository import Repository
from sensitive import DROP, MASK, RECORD, classify
from store import Store
from vaultcrypto import VaultCrypto, load_or_create_master_key

FAILURES: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("  ok   " if condition else "  FAIL ") + name)
    if not condition:
        FAILURES.append(name)


def main() -> int:
    print("[1] 敏感内容识别")
    check("私钥 -> 丢弃", classify("-----BEGIN RSA PRIVATE KEY-----") == DROP)
    check("6 位验证码 -> 临时保留", classify("483920") == MASK)
    check("普通文本 -> 正常记录", classify("数学分析第三章笔记") == RECORD)
    check("合法卡号 -> 临时保留", classify("4111 1111 1111 1111") == MASK)
    check("非法卡号不误判", classify("4111 1111 1111 1112") == RECORD)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        master = load_or_create_master_key(base / "k.bin")
        crypto = VaultCrypto(master)
        store = Store(base / "v.db", crypto)
        eph = EphemeralStore()
        repo = Repository(store, eph)

        print("[2] 加密与盲索引")
        blob = crypto.encrypt("机密内容")
        check("加解密往返", crypto.decrypt(blob) == "机密内容")
        check("密文不含明文", "机密".encode("utf-8") not in blob)
        check("盲索引稳定", crypto.blind("abc") == crypto.blind("abc"))
        check("盲索引不泄露原文", "abc" not in crypto.blind("abc"))

        print("[3] 采集与去重")
        check("普通内容入库", repo.capture("数学期末复习") == "stored")
        check("敏感内容进内存", repo.capture("483920") == "ephemeral")
        check("数据库 1 条", store.count() == 1)
        check("内存 1 条", eph.count() == 1)
        repo.capture("数学期末复习")
        check("重复复制不新增", store.count() == 1)

        print("[4] 收藏敏感内容")
        mem_key = "mem:" + eph.items()[0].eid
        check("收藏成功", repo.favorite(mem_key) == "favorited")
        check("进入数据库", store.count() == 2)
        check("移出内存", eph.count() == 0)
        favorites = repo.list_items(favorites_only=True)
        check("收藏列表 1 条", len(favorites) == 1)
        check("收藏条目保留倒计时", favorites[0].expires_at is not None)

        print("[5] 计时内取消收藏 -> 继承剩余时间")
        check("退回内存", repo.unfavorite(favorites[0].key) == "reverted")
        check("内存又出现 1 条", eph.count() == 1)
        check("数据库中已移除", store.count() == 1)

        print("[6] 计时结束后取消收藏 -> 立即删除")
        mem_key = "mem:" + eph.items()[0].eid
        repo.favorite(mem_key)
        fav = repo.list_items(favorites_only=True)[0]
        store._conn.execute(
            "UPDATE items SET sensitive_expires_at = ? WHERE blind = ?",
            (time.time() - 1, crypto.blind(fav.text)),
        )
        store._conn.commit()
        check("识别为已过期收藏", repo.is_expired_favorite(fav.key))
        check("取消即删除", repo.unfavorite(fav.key) == "deleted")
        check("删除完成", store.count() == 1)

        print("[7] 关闭隐私模式 -> 全部转永久")
        check("新敏感内容进内存", repo.capture("654321") == "ephemeral")
        migrated = repo.set_privacy(False)
        check("迁移 1 条", migrated == 1)
        check("内存清空", eph.count() == 0)
        row = [r for r in store.list_items() if r["text"] == "654321"]
        check("转永久后无倒计时", bool(row) and row[0]["sensitive_expires_at"] is None)
        repo.set_privacy(True)

        print("[8] 定期自动清除")
        repo.store.set_setting("auto_clear_on", True)
        repo.capture("很久以前的记录")
        old = [r for r in store.list_items() if r["text"] == "很久以前的记录"][0]
        store._conn.execute(
            "UPDATE items SET last_used_at = ? WHERE id = ?",
            (time.time() - 40 * 86400, old["id"]),
        )
        store._conn.commit()
        check("清掉 1 条 40 天前的记录", repo.auto_cleanup() == 1)

        print("[9] 收藏豁免清理")
        repo.capture("会被收藏的旧记录")
        target = [r for r in store.list_items() if r["text"] == "会被收藏的旧记录"][0]
        store.set_favorite(target["id"], time.time())
        store._conn.execute(
            "UPDATE items SET last_used_at = ? WHERE id = ?",
            (time.time() - 400 * 86400, target["id"]),
        )
        store._conn.commit()
        repo.auto_cleanup()
        check(
            "收藏内容未被清理",
            any(r["text"] == "会被收藏的旧记录" for r in store.list_items()),
        )

        print("[10] 搜索")
        found = repo.list_items(query="数学")
        check("搜到 1 条含'数学'的记录", len(found) == 1)

        store.close()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        for name in FAILURES:
            print("  -", name)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
