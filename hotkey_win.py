"""Windows 全局热键：独立线程 RegisterHotKey + 消息循环。

事件先放进队列，由主线程的 QTimer 轮询取出，避免跨线程信号的各种坑。
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
from ctypes import wintypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_V = 0x56

HOTKEY_ID = 0xB001


class GlobalHotkey:
    def __init__(self, name: str = "Ctrl+Alt+V", modifiers: int = MOD_CONTROL | MOD_ALT, vk: int = VK_V) -> None:
        self.name = name
        self.modifiers = modifiers
        self.vk = vk
        self.events: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def start(self) -> None:
        if sys.platform != "win32":
            self.events.put("unsupported")
            return
        self._thread = threading.Thread(target=self._run, name="GluePawHotkey", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, HOTKEY_ID, self.modifiers | MOD_NOREPEAT, self.vk):
            self.events.put("failed")
            return
        self.events.put("ok")
        try:
            msg = wintypes.MSG()
            while not self._stop.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                if msg.message == WM_HOTKEY:
                    self.events.put("hotkey")
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def poll(self) -> str | None:
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._stop.set()
        if sys.platform != "win32" or not self._thread_id:
            return
        try:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        except Exception:
            pass
