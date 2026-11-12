"""GluePaw 全局配置、路径与默认值。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "GluePaw"
APP_VERSION = "1.0.0"

# 隐私模式
DEFAULT_PRIVACY_ON = True
DEFAULT_TTL_SECONDS = 180          # 默认 3 分钟
TTL_PRESETS = (60, 180, 300)       # 1 / 3 / 5 分钟
TTL_MIN_MINUTES = 1
TTL_MAX_MINUTES = 1440             # 自定义上限 24 小时

# 定期自动清除
DEFAULT_AUTO_CLEAR_ON = False
DEFAULT_AUTO_CLEAR_MONTHS = 1
AUTO_CLEAR_PRESETS = (1, 3, 6, 12)

# 限制
MAX_ITEM_CHARS = 1_000_000
PREVIEW_CHARS = 400
MAX_VISIBLE_ITEMS = 300

HOTKEY_NAME = "Ctrl+Alt+V"


def app_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


APP_DIR = app_dir()
DB_PATH = APP_DIR / "vault.db"
KEY_PATH = APP_DIR / "key.bin"
LOG_PATH = APP_DIR / "app.log"

# 已知云同步目录：库文件绝不能放进去
SYNC_HINTS = (
    "onedrive", "dropbox", "icloud", "google drive", "googledrive",
    "nutstore", "坚果云", "baidunetdisk", "百度网盘", "weiyun", "微云",
)
