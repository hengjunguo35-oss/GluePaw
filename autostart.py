"""开机自启动：读写 HKCU Run 注册表项。

Windows 10/11 的「设置 → 应用 → 启动」直接读取这个键，
在这里注册后，系统设置里也能看到并开关 GluePaw。
状态以注册表为准，不额外落盘。
"""
from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "GluePaw"


def _pythonw_path() -> str:
    """源码运行时优先使用 pythonw.exe，避免开机弹出控制台窗口。"""
    exe = sys.executable
    if getattr(sys, "frozen", False):
        return exe
    base, name = os.path.split(exe)
    candidate = os.path.join(base, "pythonw.exe")
    if os.path.isfile(candidate):
        return candidate
    return exe


def build_command() -> str:
    """根据当前运行方式生成自启动命令。

    - 打包后的 exe：直接指向 exe 本身
    - 源码运行：指向 pythonw.exe + main.py
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return f'"{_pythonw_path()}" "{main_py}"'


def enabled() -> bool:
    """Run 键里是否存在 GluePaw 条目（存在即视为已开启）。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(enable: bool) -> bool:
    """开启：写入当前命令；关闭：删除条目。返回是否成功。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enable:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, build_command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
