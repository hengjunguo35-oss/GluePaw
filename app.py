"""应用装配：剪贴板监听、托盘、全局热键、倒计时与清理调度。

线程模型
--------
- 主线程：Qt 事件循环，负责 UI、剪贴板读写、数据库访问
- 热键线程：RegisterHotKey + GetMessage 阻塞等待，只往队列投递事件，
  由主线程的 QTimer 轮询取出，避免跨线程操作 Qt 对象
- 数据库只在主线程访问，因此不需要额外加锁

关键流程
--------
剪贴板变化 → _on_clipboard → 过滤「别记录」标记 → Repository.capture
  → 敏感且隐私模式开启：进内存 + 倒计时
  → 其他：加密入库
每秒一次 _tick → 扫描过期条目 → 删除；若系统剪贴板仍是它，一并清空
"""
from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

import config
import theme
from ephemeral import EphemeralStore
from hotkey_win import GlobalHotkey
from repository import Repository
from sensitive import is_private_marked
from store import Store
from ui_main import MainWindow
from vaultcrypto import VaultCrypto, load_or_create_master_key

log = logging.getLogger("gluepaw")


def _has_private_flag() -> bool:
    """Windows 剪贴板里的"别记录"标记（密码管理器会写）。"""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        for name in (
            "ExcludeClipboardContentFromMonitorProcessing",
            "Clipboard Viewer Ignore",
        ):
            fmt = user32.RegisterClipboardFormatW(name)
            if fmt and user32.IsClipboardFormatAvailable(fmt):
                return True
    except Exception:
        return False
    return False


def _make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#5b8def"), 4))
    painter.setBrush(QColor("#1e2128"))
    painter.drawRoundedRect(14, 12, 36, 42, 8, 8)
    painter.setBrush(QColor("#5b8def"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(24, 6, 16, 12, 4, 4)
    painter.end()
    return QIcon(pixmap)


class Vault(QObject):
    def __init__(self, qapp: QApplication) -> None:
        super().__init__()
        self.qapp = qapp
        self._suppress = False

        master = load_or_create_master_key(config.KEY_PATH)
        self.store = Store(config.DB_PATH, VaultCrypto(master))
        self.ephemeral = EphemeralStore()
        self.repo = Repository(self.store, self.ephemeral)

        self._theme_mode = self.repo.theme_mode
        if self._theme_mode == "system":
            self._dark = theme.system_is_dark()
        else:
            self._dark = self._theme_mode == "dark"
        self.pal = theme.palette(self._dark)
        self.qapp.setStyleSheet(theme.qss(self._dark))

        self.window = MainWindow(self.repo, self.pal, pinned=self.repo.pin_on_top)
        self.window.copy_requested.connect(self._copy_item)
        self.window.favorite_requested.connect(self._toggle_favorite)
        self.window.sensitivity_requested.connect(self._toggle_sensitivity)
        self.window.delete_requested.connect(self._delete_items)
        self.window.theme_mode_requested.connect(self._apply_theme_mode)
        self.window.privacy_request_handler = self._handle_privacy_toggle
        self.window.auto_clear_request_handler = self._handle_auto_clear_toggle
        self.window.clear_all_request_handler = self._handle_clear_all

        try:
            self.qapp.styleHints().colorSchemeChanged.connect(self._on_scheme_changed)
        except Exception:
            log.warning("colorSchemeChanged unavailable, theme will not follow system")

        self._setup_tray()

        self.hotkey = GlobalHotkey()
        self.hotkey.start()
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.setInterval(60)
        self._hotkey_timer.timeout.connect(self._poll_hotkey)
        self._hotkey_timer.start()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setInterval(6 * 3600 * 1000)
        self._cleanup_timer.timeout.connect(self._run_cleanup)
        self._cleanup_timer.start()

    # ---------- 删除 ----------

    def _delete_items(self, keys: list) -> None:
        keys = list(keys)
        if not keys:
            return
        if len(keys) == 1:
            item = self.repo.find(keys[0])
            if item is not None and item.favorite:
                if not self._confirm(
                    "删除收藏",
                    "这条内容已收藏，删除后无法恢复。\n\n确定删除吗？",
                ):
                    return
        else:
            if not self._confirm(
                "批量删除",
                f"确定删除选中的 {len(keys)} 条记录？\n此操作不可恢复。",
            ):
                return

        removed = sum(1 for key in keys if self.repo.delete(key))
        self.window.exit_select_mode()
        if self.window.isVisible():
            self.window.refresh()
        self._flash(f"已删除 {removed} 条记录")

    # ---------- 敏感标记 ----------

    def _toggle_sensitivity(self, key: str) -> None:
        item = self.repo.find(key)
        if item is None:
            return
        if item.sensitive and not item.favorite:
            if not self._confirm(
                "标记为非敏感信息",
                "这条内容会像普通记录一样长期保存，不再自动删除。\n\n确定吗？",
            ):
                return

        result = self.repo.set_sensitive(key, not item.sensitive)
        messages = {
            "ephemeral": "已标记为敏感信息，重新开始计时",
            "sensitive": "已标记为敏感信息",
            "normal": "已标记为非敏感信息",
            "stored": "已标记为非敏感信息",
        }
        message = messages.get(result)
        if message:
            self._flash(message)
        if self.window.isVisible():
            self.window.refresh()

    # ---------- 主题 ----------

    def _apply_theme_mode(self, mode: str) -> None:
        if mode not in ("system", "light", "dark"):
            mode = "system"
        self._theme_mode = mode
        self.store.set_setting("theme_mode", mode)
        if mode == "system":
            self._dark = theme.system_is_dark()
        else:
            self._dark = mode == "dark"
        self.pal = theme.palette(self._dark)
        self.qapp.setStyleSheet(theme.qss(self._dark))
        self.window.apply_theme(self.pal)

    def _on_scheme_changed(self, scheme) -> None:
        if self._theme_mode != "system":
            return
        dark = scheme == Qt.ColorScheme.Dark
        if dark == self._dark:
            return
        self._dark = dark
        self.pal = theme.palette(dark)
        self.qapp.setStyleSheet(theme.qss(dark))
        self.window.apply_theme(self.pal)

    # ---------- 生命周期 ----------

    def start(self) -> None:
        self.qapp.clipboard().dataChanged.connect(self._on_clipboard)
        QTimer.singleShot(400, self._run_cleanup)
        QTimer.singleShot(800, self._first_show)
        log.info("vault started, db=%s", config.DB_PATH)

    def shutdown(self) -> None:
        try:
            self.hotkey.stop()
            self.store.close()
        except Exception:
            log.exception("shutdown error")

    def _first_show(self) -> None:
        if not self.store.get_setting("welcome_shown", False):
            self.store.set_setting("welcome_shown", True)
            self.window.show_centered()

    # ---------- 剪贴板 ----------

    def _on_clipboard(self) -> None:
        if self._suppress:
            return
        clipboard = self.qapp.clipboard()
        mime = clipboard.mimeData()
        if mime is None:
            return
        if is_private_marked(mime.formats()) or _has_private_flag():
            return
        if not mime.hasText():
            return

        result = self.repo.capture(mime.text())
        if result == "dropped":
            return
        visible = self.window.isVisible()
        if result in ("stored", "ephemeral") and visible:
            self.window.refresh()
        if result == "ephemeral":
            message = f"敏感内容已临时保留 {int(self.repo.ttl // 60)} 分钟"
            if visible:
                self.window.flash_status(message)
            else:
                self._toast(message)

    def _copy_item(self, key: str) -> None:
        item = self.repo.find(key)
        if item is None:
            return
        self._set_clipboard(item.text)
        self.repo.touch(key)

    def _set_clipboard(self, text: str) -> None:
        self._suppress = True
        self.qapp.clipboard().setText(text)
        QTimer.singleShot(200, self._release_suppress)

    def _release_suppress(self) -> None:
        self._suppress = False

    def _clear_clipboard_if_matches(self, text: str) -> None:
        clipboard = self.qapp.clipboard()
        if clipboard.text() == text:
            self._suppress = True
            clipboard.clear()
            QTimer.singleShot(200, self._release_suppress)

    # ---------- 收藏 ----------

    def _toggle_favorite(self, key: str) -> None:
        item = self.repo.find(key)
        if item is None:
            return

        if not item.favorite:
            if item.source == "mem":
                confirmed = self._confirm(
                    "收藏敏感内容",
                    "这条内容是敏感信息。\n"
                    "收藏后会永久保存到本地加密数据库，不再自动删除。\n\n"
                    "确定收藏吗？",
                )
                if not confirmed:
                    return
            self.repo.favorite(key)
            self._flash("已收藏")
        else:
            if self.repo.is_expired_favorite(key):
                confirmed = self._confirm(
                    "删除确认",
                    "该内容的临时保留时间已结束。\n"
                    "取消收藏会立即删除这条记录，且无法恢复。\n\n"
                    "确定删除吗？",
                )
                if not confirmed:
                    return
                self.repo.unfavorite(key)
                self._flash("已删除")
            else:
                result = self.repo.unfavorite(key)
                if result == "reverted":
                    self._flash("已取消收藏，剩余时间继续保留")
                elif result == "deleted":
                    self._flash("已删除")
                else:
                    self._flash("已取消收藏")

        if self.window.isVisible():
            self.window.refresh()

    # ---------- 设置 ----------

    def _handle_privacy_toggle(self, desired: bool) -> None:
        if desired:
            self.repo.set_privacy(True)
            self.window.settings_page.set_privacy_state(True)
            self._flash("隐私模式已开启")
            return

        pending = self.ephemeral.count()
        message = "关闭后，复制的内容会被完整保存，不再自动删除。\n\n"
        if pending:
            message += f"当前 {pending} 条临时保留的敏感内容将被永久写入本地加密数据库。\n\n"
        message += "确定关闭隐私模式吗？"

        if not self._confirm("关闭隐私模式", message):
            self.window.settings_page.set_privacy_state(True)
            return

        migrated = self.repo.set_privacy(False)
        self.window.settings_page.set_privacy_state(False)
        if migrated:
            self._flash(f"已关闭隐私模式，{migrated} 条内容已永久保存")
        else:
            self._flash("已关闭隐私模式")
        if self.window.isVisible():
            self.window.refresh()

    def _handle_auto_clear_toggle(self, desired: bool) -> None:
        if not desired:
            self.repo.store.set_setting("auto_clear_on", False)
            self.window.settings_page.set_auto_clear_state(False)
            self._flash("已关闭定期自动清除")
            return

        confirmed = self._confirm(
            "开启定期自动清除",
            "开启后，较早的历史记录会按所选周期被自动删除。\n"
            "收藏的内容永远不受影响。\n\n"
            "确定开启吗？",
        )
        if not confirmed:
            self.window.settings_page.set_auto_clear_state(False)
            return
        self.repo.store.set_setting("auto_clear_on", True)
        self.window.settings_page.set_auto_clear_state(True)
        self._flash("已开启定期自动清除")

    def _handle_clear_all(self) -> None:
        if not self._confirm(
            "清空全部记录",
            "将删除所有历史记录与收藏，且无法恢复。\n\n确定继续吗？",
        ):
            return
        removed = self.repo.clear_all()
        if self.window.isVisible():
            self.window.refresh()
            self.window.flash_status(f"已清空 {removed} 条记录")

    def _run_cleanup(self) -> None:
        if not self.repo.auto_clear_on:
            return
        removed = self.repo.auto_cleanup()
        if removed:
            message = f"已按周期清理 {removed} 条旧记录"
            if self.window.isVisible():
                self.window.refresh()
                self.window.flash_status(message)
            else:
                self._toast(message)

    # ---------- 计时 ----------

    def _tick(self) -> None:
        expired = self.repo.sweep()
        if expired:
            for text in expired:
                self._clear_clipboard_if_matches(text)
            if self.window.isVisible():
                self.window.refresh()
        else:
            self.window.tick()

    # ---------- 窗口与托盘 ----------

    def _toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.show_centered()

    def _open_settings(self) -> None:
        self.window.show_centered()
        self.window.open_settings()

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(_make_icon(), self)
        self.tray.setToolTip("GluePaw")

        menu = QMenu()
        act_open = QAction("打开剪贴板", menu)
        act_open.triggered.connect(lambda: self.window.show_centered())
        act_settings = QAction("设置", menu)
        act_settings.triggered.connect(self._open_settings)
        act_clear = QAction("清空全部记录", menu)
        act_clear.triggered.connect(self._handle_clear_all)
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self._quit)

        menu.addAction(act_open)
        menu.addAction(act_settings)
        menu.addSeparator()
        menu.addAction(act_clear)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._tray_menu = menu  # 保持引用，防止被回收

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._toggle_window()

    def _poll_hotkey(self) -> None:
        while True:
            event = self.hotkey.poll()
            if event is None:
                return
            if event == "hotkey":
                self._toggle_window()
            elif event == "ok":
                log.info("global hotkey registered: %s", config.HOTKEY_NAME)
            elif event == "failed":
                log.warning("global hotkey register failed: %s", config.HOTKEY_NAME)
                self._toast(f"热键 {config.HOTKEY_NAME} 注册失败，可能被其他程序占用")

    def _confirm(self, title: str, text: str) -> bool:
        # 弹窗期间禁止窗口因失焦自动隐藏，否则模态框会失去宿主、卡住
        self.window._auto_hide = False
        try:
            box = QMessageBox(self.window)
            box.setWindowTitle(title)
            box.setText(text)
            box.setIcon(QMessageBox.Warning)
            if getattr(self.window, "_pinned", False):
                # 主窗口置顶时，确认框也要置顶，否则会被压在下面
                box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            yes = box.addButton("确定", QMessageBox.AcceptRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec()
            return box.clickedButton() is yes
        finally:
            self.window._auto_hide = True

    def _flash(self, text: str) -> None:
        """优先在窗口底部提示，避免系统通知被 Windows 显示成 "Python"。"""
        if self.window.isVisible():
            self.window.flash_status(text)

    def _toast(self, message: str) -> None:
        try:
            self.tray.showMessage("GluePaw", message, QSystemTrayIcon.Information, 2000)
        except Exception:
            pass

    def _quit(self) -> None:
        self.hotkey.stop()
        self.store.close()
        self.tray.hide()
        self.qapp.quit()
