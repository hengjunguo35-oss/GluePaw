"""GluePaw 入口。"""
from __future__ import annotations

import logging
import os
import sys

# 依赖装在项目内的 libs 目录，避免污染系统 Python
_LIBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.insert(0, _LIBS)

import config


def _setup_logging() -> None:
    logging.basicConfig(
        filename=str(config.LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )


def main() -> int:
    _setup_logging()
    log = logging.getLogger("gluepaw")

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
    except ImportError:
        print("缺少依赖：请先运行 install.bat")
        return 1

    from PySide6.QtCore import QLockFile

    # 让 Windows 把通知和任务栏归到 GluePaw，而不是 "Python"
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GluePaw.Clipboard.1")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 10))

    lock = QLockFile(str(config.APP_DIR / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        print("GluePaw 已经在运行中。")
        return 0
    app._instance_lock = lock  # 防止被回收

    import theme

    app.setStyleSheet(theme.qss(theme.system_is_dark()))

    from app import Vault

    try:
        vault = Vault(app)
    except Exception:
        log.exception("启动失败")
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(
            None,
            "GluePaw 启动失败",
            "无法初始化数据库或加密密钥。\n详情见日志：\n" + str(config.LOG_PATH),
        )
        return 1

    vault.start()
    code = app.exec()
    vault.shutdown()
    log.info("GluePaw exited")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
