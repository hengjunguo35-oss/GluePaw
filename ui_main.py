"""主窗口：搜索、双 Tab 列表、卡片、设置页容器。

结构
----
MainWindow（QStackedWidget）
  ├── 列表页：搜索框 / 标签栏 / 卡片滚动区 / 底部状态栏
  └── 设置页：SettingsPage

两种特殊模式
------------
- 多选模式：卡片左侧出现复选框，底部换成批量操作栏，搜索框暂时禁用
- 置顶模式：窗口加 WindowStaysOnTopHint，并关闭「失焦自动隐藏」

卡片 ClipCard 只负责展示与交互，所有动作（复制 / 收藏 / 敏感标记 / 删除）
都通过 Signal 抛给 MainWindow，再由 Vault 统一处理业务逻辑与确认框。
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import config
from icons import (
    close_icon,
    gear_icon,
    pin_icon,
    select_icon,
    shield_icon,
    star_icon,
    trash_icon,
)
from ui_settings import SettingsPage


def _human_time(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M")


def _date_label(day: date) -> str:
    today = date.today()
    if day == today:
        return "今天"
    if day == today - timedelta(days=1):
        return "昨天"
    if day.year == today.year:
        return day.strftime("%m月%d日")
    return day.strftime("%Y年%m月%d日")


def _mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


class ClipCard(QFrame):
    favorite_clicked = Signal(str)
    copy_clicked = Signal(str)
    sensitivity_toggled = Signal(str)
    delete_clicked = Signal(str)
    selection_toggled = Signal(str)

    def __init__(
        self,
        item,
        pal: dict,
        select_mode: bool = False,
        selected: bool = False,
        query: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self.pal = pal
        self.select_mode = select_mode
        self._selected = selected
        self.query = query
        self._revealed = False
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("selected", "true" if selected else "false")
        self.setCursor(Qt.PointingHandCursor if select_mode else Qt.ArrowCursor)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(int(pal.get("shadow_blur", 10)))
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, int(pal.get("shadow_alpha", 18))))
        self.setGraphicsEffect(shadow)

        self._build()
        self.update_tick()

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(11, 9, 11, 8)
        root.setSpacing(8)

        if self.select_mode:
            self.checkbox = QCheckBox()
            self.checkbox.setChecked(self._selected)
            self.checkbox.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            root.addWidget(self.checkbox, 0, Qt.AlignVCenter)

        column = QVBoxLayout()
        column.setSpacing(3)

        self.preview = QLabel()
        self.preview.setObjectName("Preview")
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.PlainText)
        self.preview.setMaximumHeight(56)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        column.addWidget(self.preview)

        row = QHBoxLayout()
        row.setSpacing(6)

        self.badge = QLabel()
        self.badge.setObjectName("Badge")
        self.meta = QLabel()
        self.meta.setObjectName("Meta")
        row.addWidget(self.badge)
        row.addWidget(self.meta)
        row.addStretch(1)

        if not self.select_mode:
            self.shield = QToolButton()
            self.shield.setObjectName("IconBtn")
            self.shield.setIconSize(QSize(15, 15))
            self.shield.setIcon(
                shield_icon(
                    self.item.sensitive,
                    self.pal.get("warn", "#B45309")
                    if self.item.sensitive
                    else self.pal.get("outline", "#9CA3AF"),
                )
            )
            self.shield.setToolTip(
                "标记为非敏感信息" if self.item.sensitive else "标记为敏感信息"
            )
            self.shield.clicked.connect(
                lambda: self.sensitivity_toggled.emit(self.item.key)
            )
            row.addWidget(self.shield, 0, Qt.AlignVCenter)

            if self.item.sensitive:
                self.eye = QToolButton()
                self.eye.setObjectName("IconBtn")
                self.eye.setText("显示")
                self.eye.setToolTip("临时显示 10 秒")
                self.eye.clicked.connect(self._toggle_reveal)
                row.addWidget(self.eye, 0, Qt.AlignVCenter)

            self.star = QToolButton()
            self.star.setObjectName("IconBtn")
            self.star.setIconSize(QSize(16, 16))
            self.star.setToolTip("收藏" if not self.item.favorite else "取消收藏")
            self.star.clicked.connect(
                lambda: self.favorite_clicked.emit(self.item.key)
            )
            row.addWidget(self.star, 0, Qt.AlignVCenter)

            self.trash = QToolButton()
            self.trash.setObjectName("IconBtn")
            self.trash.setIconSize(QSize(15, 15))
            self.trash.setIcon(trash_icon(self.pal.get("sub", "#6B7280")))
            self.trash.setToolTip("删除这条记录")
            self.trash.clicked.connect(lambda: self.delete_clicked.emit(self.item.key))
            row.addWidget(self.trash, 0, Qt.AlignVCenter)

            self.copy_btn = QToolButton()
            self.copy_btn.setObjectName("IconBtn")
            self.copy_btn.setText("复制")
            self.copy_btn.setToolTip("复制到剪贴板")
            self.copy_btn.clicked.connect(self._on_copy)
            row.addWidget(self.copy_btn, 0, Qt.AlignVCenter)

        column.addLayout(row)
        root.addLayout(column, 1)
        self._render()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.select_mode and event.button() == Qt.LeftButton:
            self.selection_toggled.emit(self.item.key)
            return
        super().mousePressEvent(event)

    # ---------- 渲染 ----------

    def _render(self) -> None:
        if not self.select_mode:
            color = self.pal.get("gold") if self.item.favorite else self.pal.get("outline")
            self.star.setIcon(star_icon(self.item.favorite, color=color))
        self._render_text()
        self.meta.setText(f"复制于 {_human_time(self.item.last_used_at)}")

    def _render_text(self) -> None:
        if self.item.sensitive and not self._revealed:
            self.preview.setTextFormat(Qt.PlainText)
            self.preview.setText("••••••••••••  （敏感内容，点“显示”查看）")
            self.preview.setStyleSheet(f"color: {self.pal.get('warn')};")
            return
        self.preview.setStyleSheet("")
        text = self.item.text.strip()
        if len(text) > config.PREVIEW_CHARS:
            text = text[: config.PREVIEW_CHARS] + " …"

        query = self.query.strip()
        if query:
            bg = self.pal.get("highlight_bg", "#DBEAFE")
            fg = self.pal.get("highlight_text", "#1E3A8A")
            escaped = html.escape(text).replace("\n", "<br>")
            try:
                pattern = re.compile(re.escape(html.escape(query)), re.IGNORECASE)
            except re.error:
                pattern = None
            if pattern is not None:
                escaped = pattern.sub(
                    lambda m: f'<span style="background-color:{bg};color:{fg};">{m.group(0)}</span>',
                    escaped,
                )
            self.preview.setTextFormat(Qt.RichText)
            self.preview.setText(escaped)
        else:
            self.preview.setTextFormat(Qt.PlainText)
            self.preview.setText(text)

    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self.eye.setText("隐藏" if self._revealed else "显示")
        self._render_text()
        if self._revealed:
            QTimer.singleShot(10_000, self._remask)

    def _remask(self) -> None:
        if self._revealed:
            self._revealed = False
            self.eye.setText("显示")
            self._render_text()

    def _on_copy(self) -> None:
        self.copy_btn.setText("已复制")
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("复制"))
        self.copy_clicked.emit(self.item.key)

    def update_tick(self) -> None:
        badge = ""
        danger = False
        remaining = self.item.remaining()
        if remaining is not None:
            if remaining <= 0:
                if self.item.favorite:
                    badge = "已过期，取消收藏即删除"
                    danger = True
                else:
                    badge = "正在清除…"
                    danger = True
            else:
                badge = f"还剩 {_mmss(remaining)}"
        elif self.item.favorite:
            badge = "已收藏"

        self.badge.setText(badge)
        self.badge.setObjectName("BadgeDanger" if danger else "Badge")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)


class MainWindow(QWidget):
    copy_requested = Signal(str)
    favorite_requested = Signal(str)
    sensitivity_requested = Signal(str)
    delete_requested = Signal(list)
    theme_mode_requested = Signal(str)

    def __init__(self, repo, pal: dict, pinned: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo = repo
        self.pal = pal
        self._pinned = pinned
        self._cards: list[ClipCard] = []
        self._tab = "history"
        self._settings_open = False
        self._auto_hide = True
        self._select_mode = False
        self._selected: set[str] = set()

        flags = Qt.Window | Qt.FramelessWindowHint
        if self._pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._apply_default_size()

        self._build()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self.refresh)

    # ---------- 构建 ----------

    def _apply_default_size(self) -> None:
        """9:16 竖版窗口；屏幕不够高时等比缩小。"""
        height = 747
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry().height() - 80
            height = max(520, min(747, available))
        self.setFixedSize(int(height * 9 / 16), height)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(8)

        self.header_bar = QWidget()
        header = QHBoxLayout(self.header_bar)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索历史内容…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self.search.returnPressed.connect(self.copy_first)
        header.addWidget(self.search, 1)

        self.gear = QToolButton()
        self.gear.setObjectName("IconBtn")
        self.gear.setIcon(gear_icon(self.pal.get("icon", "#4B5563")))
        self.gear.setIconSize(QSize(18, 18))
        self.gear.setToolTip("设置")
        self.gear.clicked.connect(self.open_settings)
        header.addWidget(self.gear)

        self.select_btn = QToolButton()
        self.select_btn.setObjectName("IconBtn")
        self.select_btn.setIcon(select_icon(self.pal.get("icon", "#4B5563")))
        self.select_btn.setIconSize(QSize(17, 17))
        self.select_btn.setToolTip("多选")
        self.select_btn.clicked.connect(self.enter_select_mode)
        header.addWidget(self.select_btn)

        self.pin_btn = QToolButton()
        self.pin_btn.setObjectName("IconBtn")
        self.pin_btn.setIconSize(QSize(16, 16))
        self.pin_btn.setIcon(
            pin_icon(
                self._pinned,
                self.pal.get("accent") if self._pinned else self.pal.get("icon", "#4B5563"),
            )
        )
        self.pin_btn.setToolTip("取消置顶" if self._pinned else "置顶窗口")
        self.pin_btn.clicked.connect(self.toggle_pin)
        header.addWidget(self.pin_btn)

        self.close_btn = QToolButton()
        self.close_btn.setObjectName("IconBtn")
        self.close_btn.setIcon(close_icon(self.pal.get("icon", "#4B5563")))
        self.close_btn.setIconSize(QSize(12, 12))
        self.close_btn.setToolTip("关闭窗口（后台继续运行）")
        self.close_btn.clicked.connect(self.hide)
        header.addWidget(self.close_btn)
        outer.addWidget(self.header_bar)

        self.tab_bar = QFrame()
        self.tab_bar.setObjectName("TabBar")
        tabs = QHBoxLayout(self.tab_bar)
        tabs.setContentsMargins(3, 3, 3, 3)
        tabs.setSpacing(2)
        self.tab_history = QPushButton("历史记录")
        self.tab_history.setObjectName("Tab")
        self.tab_history.setCheckable(True)
        self.tab_history.setChecked(True)
        self.tab_history.clicked.connect(lambda: self._switch_tab("history"))
        self.tab_fav = QPushButton("收藏")
        self.tab_fav.setObjectName("Tab")
        self.tab_fav.setCheckable(True)
        self.tab_fav.clicked.connect(lambda: self._switch_tab("fav"))
        tabs.addWidget(self.tab_history)
        tabs.addWidget(self.tab_fav)
        outer.addWidget(self.tab_bar, 0, Qt.AlignLeft)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        list_page = QWidget()
        lp = QVBoxLayout(list_page)
        lp.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.list_container = QWidget()
        self.list_container.setAttribute(Qt.WA_StyledBackground, False)
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 2, 4, 2)
        self.list_layout.setSpacing(9)
        self.scroll.setWidget(self.list_container)
        lp.addWidget(self.scroll)
        self.stack.addWidget(list_page)
        self.list_page = list_page

        self.settings_page = SettingsPage(self.repo, self.pal)
        self.stack.addWidget(self.settings_page)
        self.settings_page.back_requested.connect(self.close_settings)
        self.settings_page.close_requested.connect(self.hide)
        self.settings_page.clear_all_requested.connect(self._request_clear_all)
        self.settings_page.privacy_toggle_requested.connect(self._request_privacy)
        self.settings_page.auto_clear_toggle_requested.connect(self._request_auto_clear)
        self.settings_page.ttl_changed.connect(self._apply_ttl)
        self.settings_page.auto_clear_months_changed.connect(self._apply_months)
        self.settings_page.theme_mode_changed.connect(self.theme_mode_requested.emit)

        self.footer_widget = QWidget()
        footer = QHBoxLayout(self.footer_widget)
        footer.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel()
        self.status.setObjectName("Meta")
        hint = QLabel(f"{config.HOTKEY_NAME} 唤出 · Esc 关闭")
        hint.setObjectName("Hint")
        footer.addWidget(self.status)
        footer.addStretch(1)
        footer.addWidget(hint)
        outer.addWidget(self.footer_widget)

        self.selection_bar = QWidget()
        sel = QHBoxLayout(self.selection_bar)
        sel.setContentsMargins(0, 0, 0, 0)
        self.sel_label = QLabel("已选 0 项")
        self.sel_label.setObjectName("Meta")
        self.sel_all = QPushButton("全选")
        self.sel_all.setObjectName("SmallAction")
        self.sel_all.clicked.connect(self.select_all)
        self.sel_delete = QPushButton("删除")
        self.sel_delete.setObjectName("SmallDanger")
        self.sel_delete.clicked.connect(self._request_delete_selected)
        self.sel_cancel = QPushButton("取消")
        self.sel_cancel.setObjectName("SmallAction")
        self.sel_cancel.clicked.connect(self.exit_select_mode)
        sel.addWidget(self.sel_label)
        sel.addStretch(1)
        sel.addWidget(self.sel_all)
        sel.addWidget(self.sel_delete)
        sel.addWidget(self.sel_cancel)
        self.selection_bar.setVisible(False)
        outer.addWidget(self.selection_bar)

        self.refresh()

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, QColor(self.pal.get("bg", "#F6F7F9")))
        painter.setPen(QPen(QColor(self.pal.get("border", "#E5E7EB")), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    # ---------- 列表 ----------

    def _clear_list(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()

    def refresh(self) -> None:
        if self._settings_open:
            return
        items = self.repo.list_items(
            query=self.search.text(), favorites_only=(self._tab == "fav")
        )
        self._clear_list()

        groups: dict[date, list] = {}
        order: list[date] = []
        for item in items[: config.MAX_VISIBLE_ITEMS]:
            day = datetime.fromtimestamp(item.last_used_at).date()
            if day not in groups:
                groups[day] = []
                order.append(day)
            groups[day].append(item)

        for day in order:
            label = QLabel(_date_label(day))
            label.setObjectName("Section")
            self.list_layout.addWidget(label)
            for item in groups[day]:
                card = ClipCard(
                    item,
                    self.pal,
                    select_mode=self._select_mode,
                    selected=item.key in self._selected,
                    query=self.search.text(),
                )
                card.favorite_clicked.connect(self.favorite_requested.emit)
                card.copy_clicked.connect(self.copy_requested.emit)
                card.sensitivity_toggled.connect(self.sensitivity_requested.emit)
                card.delete_clicked.connect(
                    lambda key: self.delete_requested.emit([key])
                )
                card.selection_toggled.connect(self._toggle_selection)
                self.list_layout.addWidget(card)
                self._cards.append(card)

        if not items:
            empty = QLabel("暂无记录" if self._tab == "history" else "还没有收藏任何内容")
            empty.setObjectName("Hint")
            empty.setAlignment(Qt.AlignCenter)
            self.list_layout.addSpacing(40)
            self.list_layout.addWidget(empty)

        self.list_layout.addStretch(1)
        self.status.setText(f"共 {len(items)} 条")

    def tick(self) -> None:
        for card in self._cards:
            card.update_tick()

    def flash_status(self, text: str, msec: int = 1800) -> None:
        """在底部状态栏短暂显示一条反馈，不弹系统通知。"""
        self.status.setText(text)
        QTimer.singleShot(msec, self._restore_status)

    def _restore_status(self) -> None:
        if self._settings_open:
            self.status.setText("")
        else:
            self.status.setText(f"共 {len(self._cards)} 条")

    def _switch_tab(self, tab: str) -> None:
        self._tab = tab
        self.tab_history.setChecked(tab == "history")
        self.tab_fav.setChecked(tab == "fav")
        self.refresh()

    def copy_first(self) -> None:
        if self._select_mode:
            return
        if self._cards:
            self._cards[0]._on_copy()

    # ---------- 多选 ----------

    def enter_select_mode(self) -> None:
        if self._settings_open or self._select_mode:
            return
        self._select_mode = True
        self._selected.clear()
        self.select_btn.setVisible(False)
        self.search.setEnabled(False)
        self.footer_widget.setVisible(False)
        self.selection_bar.setVisible(True)
        self._update_selection_bar()
        self.refresh()

    def exit_select_mode(self) -> None:
        if not self._select_mode:
            return
        self._select_mode = False
        self._selected.clear()
        self.select_btn.setVisible(True)
        self.search.setEnabled(True)
        self.footer_widget.setVisible(True)
        self.selection_bar.setVisible(False)
        self.refresh()

    def _toggle_selection(self, key: str) -> None:
        if key in self._selected:
            self._selected.discard(key)
        else:
            self._selected.add(key)
        self._update_selection_bar()
        self.refresh()

    def select_all(self) -> None:
        keys = {card.item.key for card in self._cards}
        if keys and self._selected >= keys:
            self._selected.clear()
        else:
            self._selected = keys
        self._update_selection_bar()
        self.refresh()

    def _update_selection_bar(self) -> None:
        count = len(self._selected)
        self.sel_label.setText(f"已选 {count} 项")
        self.sel_delete.setEnabled(count > 0)
        all_selected = bool(self._cards) and count == len(self._cards)
        self.sel_all.setText("取消全选" if all_selected else "全选")

    def _request_delete_selected(self) -> None:
        if self._selected:
            self.delete_requested.emit(list(self._selected))

    # ---------- 设置页 ----------

    def open_settings(self) -> None:
        if self._select_mode:
            self.exit_select_mode()
        self._settings_open = True
        self.header_bar.setVisible(False)
        self.tab_bar.setVisible(False)
        self.status.setText("")
        self.settings_page.reload()
        self.stack.setCurrentWidget(self.settings_page)

    def close_settings(self) -> None:
        self._settings_open = False
        self.header_bar.setVisible(True)
        self.tab_bar.setVisible(True)
        self.stack.setCurrentWidget(self.list_page)
        self.refresh()

    def _request_privacy(self, desired: bool) -> None:
        # 由 app 层弹确认框；这里只转发
        if hasattr(self, "privacy_request_handler"):
            self.privacy_request_handler(desired)
        else:
            self.settings_page.set_privacy_state(self.repo.privacy_on)

    def _request_auto_clear(self, desired: bool) -> None:
        if hasattr(self, "auto_clear_request_handler"):
            self.auto_clear_request_handler(desired)
        else:
            self.settings_page.set_auto_clear_state(self.repo.auto_clear_on)

    def _request_clear_all(self) -> None:
        if hasattr(self, "clear_all_request_handler"):
            self.clear_all_request_handler()

    def _apply_ttl(self, seconds: int) -> None:
        self.repo.store.set_setting("ttl_seconds", int(seconds))

    def _apply_months(self, months: int) -> None:
        self.repo.store.set_setting("auto_clear_months", int(months))

    # ---------- 主题 ----------

    def apply_theme(self, pal: dict) -> None:
        self.pal = pal
        self.gear.setIcon(gear_icon(pal.get("icon", "#4B5563")))
        self.close_btn.setIcon(close_icon(pal.get("icon", "#4B5563")))
        self.settings_page.apply_theme(pal)
        self.refresh()
        self.update()

    # ---------- 置顶 ----------

    def toggle_pin(self) -> None:
        self.set_pinned(not self._pinned)

    def set_pinned(self, pinned: bool) -> None:
        if pinned == self._pinned:
            return
        visible = self.isVisible()
        pos = self.pos()
        self._pinned = pinned
        self.repo.store.set_setting("pin_on_top", pinned)

        flags = self.windowFlags()
        if pinned:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.move(pos)

        self.pin_btn.setIcon(
            pin_icon(
                pinned,
                self.pal.get("accent") if pinned else self.pal.get("icon", "#4B5563"),
            )
        )
        self.pin_btn.setToolTip("取消置顶" if pinned else "置顶窗口")

        if visible:
            self.show()
            self.raise_()
            self.activateWindow()

    # ---------- 显示与隐藏 ----------

    def show_centered(self) -> None:
        if self._select_mode:
            self.exit_select_mode()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + max(12, (geo.height() - self.height()) // 2)
            y = min(y, geo.y() + max(0, geo.height() - self.height() - 12))
            self.move(QPoint(x, y))
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()
        self.search.selectAll()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowDeactivate and self._auto_hide and not self._settings_open:
            QTimer.singleShot(120, self._maybe_hide)
        super().changeEvent(event)

    def _maybe_hide(self) -> None:
        if self._pinned:
            return
        if not self.isVisible() or self._settings_open:
            return
        if QApplication.activeModalWidget() is not None:
            return
        if QApplication.activePopupWidget() is not None:
            return
        self.hide()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            if self._select_mode:
                self.exit_select_mode()
            elif self._settings_open:
                self.close_settings()
            else:
                self.hide()
            return
        super().keyPressEvent(event)
