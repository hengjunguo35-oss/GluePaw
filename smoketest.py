"""无界面冒烟测试：用临时数据库装配整个应用，确认 Qt 层不报错。

    python smoketest.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "libs"))

import config

_TMP = Path(tempfile.mkdtemp(prefix="gluepaw-smoke-"))
config.APP_DIR = _TMP
config.DB_PATH = _TMP / "v.db"
config.KEY_PATH = _TMP / "k.bin"
config.LOG_PATH = _TMP / "app.log"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import theme
from app import Vault


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss(theme.system_is_dark()))
    vault = Vault(app)
    vault.start()

    # 走一遍真实流程
    vault.repo.capture("数学分析第三章：极限与连续")
    vault.repo.capture("483920")          # 验证码 -> 内存暂存
    vault.window.refresh()
    vault.window.open_settings()
    vault.window.settings_page.reload()
    vault.window.close_settings()
    vault.window.tick()

    favorites = vault.repo.list_items(favorites_only=True)
    assert isinstance(favorites, list)

    QTimer.singleShot(600, app.quit)
    app.exec()
    total = vault.repo.count()
    vault.shutdown()
    print("SMOKE_OK items=", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
