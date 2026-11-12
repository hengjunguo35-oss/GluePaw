"""扁平化主题：明/暗双色板，跟随系统。

QSS 里用 @token 占位，运行时按当前色板替换：
    QLineEdit#Search { background: @surface; border: 1px solid @border; }
切主题时重新生成整份样式表并 setStyleSheet，不需要维护两份 QSS。

色板之外还有几个供代码直接使用的键：
    shadow_alpha / shadow_blur 卡片阴影
    highlight_bg / highlight_text 搜索关键词高亮
    gold / warn / outline 图标颜色
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

LIGHT = {
    "bg": "#F6F7F9",
    "surface": "#FFFFFF",
    "card_hover": "#FCFCFD",
    "border": "#E5E7EB",
    "border_hover": "#D1D5DB",
    "text": "#111827",
    "sub": "#6B7280",
    "muted": "#9CA3AF",
    "accent": "#2563EB",
    "selection": "#BFDBFE",
    "hover": "#F3F4F6",
    "pressed": "#E5E7EB",
    "divider": "#E5E7EB",
    "scroll": "#D1D5DB",
    "scroll_hover": "#9CA3AF",
    "switch_off": "#E5E7EB",
    "switch_off_text": "#4B5563",
    "danger": "#DC2626",
    "danger_soft": "#FEF2F2",
    "danger_hover": "#FEE2E2",
    "danger_border": "#FECACA",
    "warn": "#B45309",
    "gold": "#F59E0B",
    "outline": "#9CA3AF",
    "radio_border": "#D1D5DB",
    "disabled": "#C4CAD3",
    "menu_sel": "#F3F4F6",
    "highlight_bg": "#93C5FD",
    "highlight_text": "#1E3A8A",
    "shadow_alpha": 18,
    "shadow_blur": 10,
    "icon": "#4B5563",
}

DARK = {
    "bg": "#14161B",
    "surface": "#1E2128",
    "card_hover": "#242832",
    "border": "#2C313B",
    "border_hover": "#3C4350",
    "text": "#E8EAEF",
    "sub": "#9AA1AF",
    "muted": "#6B7280",
    "accent": "#4B8BF5",
    "selection": "#2F4A7A",
    "hover": "#262B34",
    "pressed": "#2F3541",
    "divider": "#2C313B",
    "scroll": "#3A414D",
    "scroll_hover": "#4A5262",
    "switch_off": "#2C313B",
    "switch_off_text": "#9AA1AF",
    "danger": "#F87171",
    "danger_soft": "#2A1D1D",
    "danger_hover": "#352424",
    "danger_border": "#4A2C2B",
    "warn": "#F0B95A",
    "gold": "#FBBF24",
    "outline": "#7A8290",
    "radio_border": "#3A414D",
    "disabled": "#565D6A",
    "menu_sel": "#262B34",
    "highlight_bg": "#3B82F6",
    "highlight_text": "#FFFFFF",
    "shadow_alpha": 90,
    "shadow_blur": 10,
    "icon": "#9AA1AF",
}

_TEMPLATE = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
    outline: none;
}
QWidget#Root { background: transparent; }

/* ---------- 搜索框 ---------- */
QLineEdit#Search {
    background: @surface;
    border: 1px solid @border;
    border-radius: 9px;
    padding: 9px 13px;
    color: @text;
    selection-background-color: @selection;
}
QLineEdit#Search:focus { border: 1px solid @accent; }

/* ---------- 图标按钮 ---------- */
QToolButton#IconBtn {
    background: transparent;
    border: none;
    border-radius: 6px;
    color: @sub;
    padding: 5px 8px;
    font-size: 12px;
}
QToolButton#IconBtn:hover { background: @hover; color: @text; }
QToolButton#IconBtn:pressed { background: @pressed; }

/* ---------- 标签页 ---------- */
QFrame#TabBar { background: transparent; border: none; }
QPushButton#Tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: @sub;
    padding: 6px 10px;
}
QPushButton#Tab:hover { color: @text; }
QPushButton#Tab:checked {
    color: @text;
    border-bottom: 2px solid @accent;
    font-weight: 600;
}

/* ---------- 内容卡片 ---------- */
QFrame#Card {
    background: @surface;
    border: 1px solid @border;
    border-radius: 10px;
}
QFrame#Card:hover { border: 1px solid @border_hover; background: @card_hover; }
QFrame#Card[selected="true"] { border: 1px solid @accent; }

QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid @radio_border;
    background: @surface;
}
QCheckBox::indicator:checked { background: @accent; border: 1px solid @accent; }

QPushButton#SmallAction {
    background: transparent;
    border: none;
    border-radius: 6px;
    color: @sub;
    padding: 4px 10px;
}
QPushButton#SmallAction:hover { background: @hover; color: @text; }
QPushButton#SmallDanger {
    background: transparent;
    border: none;
    border-radius: 6px;
    color: @danger;
    padding: 4px 10px;
}
QPushButton#SmallDanger:hover { background: @danger_soft; }

/* ---------- 文字 ---------- */
QLabel#Preview { color: @text; }
QLabel#Meta { color: @sub; font-size: 11px; }
QLabel#Section { color: @sub; font-size: 11px; font-weight: 600; padding: 6px 2px 2px 2px; }
QLabel#SectionTitle { color: @text; font-size: 13px; font-weight: 600; }
QLabel#Badge { color: @warn; font-size: 11px; }
QLabel#BadgeDanger { color: @danger; font-size: 11px; }
QLabel#Hint { color: @muted; font-size: 11px; }
QLabel#Title { color: @text; font-size: 15px; font-weight: 600; }

/* ---------- 滚动区 ---------- */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget { background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QStackedWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: @scroll_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

/* ---------- 开关 ---------- */
QPushButton#Switch {
    border-radius: 11px;
    background: @switch_off;
    border: none;
    color: @switch_off_text;
    padding: 4px 14px;
    min-width: 52px;
}
QPushButton#Switch[on="true"] { background: @accent; color: #FFFFFF; }

/* ---------- 危险按钮 ---------- */
QPushButton#Danger {
    background: @danger_soft;
    border: 1px solid @danger_border;
    color: @danger;
    border-radius: 8px;
    padding: 7px 16px;
}
QPushButton#Danger:hover { background: @danger_hover; }

/* ---------- 单选与输入 ---------- */
QRadioButton { color: @text; spacing: 7px; }
QRadioButton::indicator {
    width: 13px; height: 13px; border-radius: 7px;
    border: 1px solid @radio_border;
    background: @surface;
}
QRadioButton::indicator:checked { background: @accent; border: 1px solid @accent; }
QRadioButton:disabled { color: @disabled; }

QSpinBox {
    background: @surface;
    border: 1px solid @border;
    border-radius: 7px;
    padding: 4px 8px;
    color: @text;
    min-width: 64px;
}
QSpinBox:focus { border: 1px solid @accent; }
QSpinBox:disabled { color: @disabled; }

/* ---------- 其它 ---------- */
QFrame#Divider { background: @divider; max-height: 1px; border: none; }

QMenu {
    background: @surface;
    border: 1px solid @border;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item { padding: 7px 24px 7px 12px; color: @text; border-radius: 5px; }
QMenu::item:selected { background: @menu_sel; }
QMenu::separator { height: 1px; background: @divider; margin: 4px 8px; }

QMessageBox { background: @surface; }
QMessageBox QLabel { color: @text; }

QToolTip {
    background: @surface;
    color: @text;
    border: 1px solid @border;
    padding: 4px 8px;
}
"""

_TOKEN = re.compile(r"@(\w+)")


def palette(dark: bool) -> dict:
    return DARK if dark else LIGHT


def qss(dark: bool) -> str:
    table = palette(dark)
    return _TOKEN.sub(lambda m: table.get(m.group(1), m.group(0)), _TEMPLATE)


def system_is_dark() -> bool:
    forced = os.environ.get("GLUEPAW_THEME", "").strip().lower()
    if forced == "dark":
        return True
    if forced == "light":
        return False
    try:
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception:
        pass
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except Exception:
        return False


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
