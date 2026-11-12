"""设置页（第二级界面）。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import config
from icons import back_icon, close_icon
from theme import repolish


def _set_switch(button: QPushButton, on: bool) -> None:
    button.setChecked(on)
    button.setText("已开启" if on else "已关闭")
    button.setProperty("on", "true" if on else "false")
    repolish(button)


class SettingsPage(QWidget):
    back_requested = Signal()
    close_requested = Signal()
    privacy_toggle_requested = Signal(bool)
    ttl_changed = Signal(int)
    auto_clear_toggle_requested = Signal(bool)
    auto_clear_months_changed = Signal(int)
    theme_mode_changed = Signal(str)
    clear_all_requested = Signal()

    def __init__(self, repo, pal: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo = repo
        self.pal = pal
        self._loading = False
        self._build()
        self.reload()

    # ---------- 构建 ----------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        head = QHBoxLayout()
        self.back_btn = QToolButton()
        self.back_btn.setObjectName("IconBtn")
        self.back_btn.setIcon(back_icon(self.pal.get("icon", "#4B5563")))
        self.back_btn.setIconSize(QSize(15, 15))
        self.back_btn.setToolTip("返回")
        self.back_btn.clicked.connect(self.back_requested.emit)
        title = QLabel("设置")
        title.setObjectName("Title")
        head.addWidget(self.back_btn)
        head.addWidget(title)
        head.addStretch(1)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("IconBtn")
        self.close_btn.setIcon(close_icon(self.pal.get("icon", "#4B5563")))
        self.close_btn.setIconSize(QSize(12, 12))
        self.close_btn.setToolTip("关闭窗口（后台继续运行）")
        self.close_btn.clicked.connect(self.close_requested.emit)
        head.addWidget(self.close_btn)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setAttribute(Qt.WA_StyledBackground, False)
        col = QVBoxLayout(content)
        col.setContentsMargins(2, 2, 8, 8)
        col.setSpacing(10)

        # ---- 隐私模式 ----
        row = QHBoxLayout()
        row.addWidget(self._title("隐私模式"))
        row.addStretch(1)
        self.privacy_switch = QPushButton()
        self.privacy_switch.setObjectName("Switch")
        self.privacy_switch.setCheckable(True)
        self.privacy_switch.clicked.connect(
            lambda: self.privacy_toggle_requested.emit(self.privacy_switch.isChecked())
        )
        row.addWidget(self.privacy_switch)
        col.addLayout(row)

        col.addWidget(
            self._hint("敏感内容只临时保留在内存中，到点自动删除，不写入磁盘。")
        )

        self.ttl_group = QButtonGroup(self)
        ttl_row = QHBoxLayout()
        ttl_row.setSpacing(14)
        for idx, seconds in enumerate(config.TTL_PRESETS):
            radio = QRadioButton(f"{seconds // 60} 分钟")
            self.ttl_group.addButton(radio, idx)
            ttl_row.addWidget(radio)
        self.custom_radio = QRadioButton("自定义")
        self.ttl_group.addButton(self.custom_radio, 3)
        ttl_row.addWidget(self.custom_radio)
        ttl_row.addStretch(1)
        col.addLayout(ttl_row)
        self.ttl_group.idClicked.connect(self._on_ttl_clicked)

        self.custom_row = QHBoxLayout()
        self.custom_spin = QSpinBox()
        self.custom_spin.setRange(config.TTL_MIN_MINUTES, config.TTL_MAX_MINUTES)
        self.custom_spin.setValue(10)
        self.custom_spin.setSuffix(" 分钟")
        self.custom_spin.valueChanged.connect(self._on_custom_changed)
        self.custom_row.addWidget(self.custom_spin)
        self.custom_row.addWidget(
            self._hint(f"范围 {config.TTL_MIN_MINUTES} ~ {config.TTL_MAX_MINUTES} 分钟")
        )
        self.custom_row.addStretch(1)
        col.addLayout(self.custom_row)

        col.addWidget(self._divider())

        # ---- 定期自动清除 ----
        row2 = QHBoxLayout()
        row2.addWidget(self._title("定期自动清除"))
        row2.addStretch(1)
        self.auto_switch = QPushButton()
        self.auto_switch.setObjectName("Switch")
        self.auto_switch.setCheckable(True)
        self.auto_switch.clicked.connect(
            lambda: self.auto_clear_toggle_requested.emit(self.auto_switch.isChecked())
        )
        row2.addWidget(self.auto_switch)
        col.addLayout(row2)

        col.addWidget(self._hint("按周期清理较早的历史记录；收藏的内容永远不受影响。"))

        self.month_group = QButtonGroup(self)
        month_row = QHBoxLayout()
        month_row.setSpacing(14)
        for idx, months in enumerate(config.AUTO_CLEAR_PRESETS):
            text = "1 年" if months == 12 else f"{months} 个月"
            radio = QRadioButton(text)
            self.month_group.addButton(radio, idx)
            month_row.addWidget(radio)
        month_row.addStretch(1)
        col.addLayout(month_row)
        self.month_group.idClicked.connect(self._on_month_clicked)

        col.addWidget(self._divider())

        # ---- 外观 ----
        col.addWidget(self._title("外观"))
        col.addWidget(self._hint("选择界面配色，或跟随系统的浅色 / 深色设置。"))

        self._theme_modes = ("system", "light", "dark")
        self.theme_group = QButtonGroup(self)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(14)
        for idx, text in enumerate(("跟随系统", "浅色", "深色")):
            radio = QRadioButton(text)
            self.theme_group.addButton(radio, idx)
            theme_row.addWidget(radio)
        theme_row.addStretch(1)
        col.addLayout(theme_row)
        self.theme_group.idClicked.connect(self._on_theme_clicked)

        col.addWidget(self._divider())

        # ---- 危险操作 ----
        danger_row = QHBoxLayout()
        clear_btn = QPushButton("清空全部记录")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self.clear_all_requested.emit)
        danger_row.addWidget(clear_btn)
        danger_row.addStretch(1)
        col.addLayout(danger_row)
        col.addWidget(self._hint("不会影响系统剪贴板中的当前内容。"))

        col.addStretch(1)
        col.addWidget(self._hint(f"GluePaw {config.APP_VERSION} · 数据仅保存在本机"))
        col.addWidget(self._hint(str(config.APP_DIR)))

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    def _title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def apply_theme(self, pal: dict) -> None:
        self.pal = pal
        self.back_btn.setIcon(back_icon(pal.get("icon", "#4B5563")))
        self.close_btn.setIcon(close_icon(pal.get("icon", "#4B5563")))

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Hint")
        label.setWordWrap(True)
        return label

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        return line

    # ---------- 交互 ----------

    def _on_ttl_clicked(self, index: int) -> None:
        if self._loading:
            return
        is_custom = index == 3
        self.custom_spin.setVisible(is_custom)
        if is_custom:
            self.ttl_changed.emit(self.custom_spin.value() * 60)
        else:
            self.ttl_changed.emit(config.TTL_PRESETS[index])

    def _on_custom_changed(self, value: int) -> None:
        if self._loading:
            return
        if self.custom_radio.isChecked():
            self.ttl_changed.emit(value * 60)

    def _on_month_clicked(self, index: int) -> None:
        if self._loading:
            return
        self.auto_clear_months_changed.emit(config.AUTO_CLEAR_PRESETS[index])

    def _on_theme_clicked(self, index: int) -> None:
        if self._loading:
            return
        self.theme_mode_changed.emit(self._theme_modes[index])

    # ---------- 状态 ----------

    def set_privacy_state(self, on: bool) -> None:
        _set_switch(self.privacy_switch, on)
        self._set_ttl_enabled(on)

    def set_auto_clear_state(self, on: bool) -> None:
        _set_switch(self.auto_switch, on)
        self._set_months_enabled(on)

    def _set_ttl_enabled(self, enabled: bool) -> None:
        for button in self.ttl_group.buttons():
            button.setEnabled(enabled)
        self.custom_spin.setEnabled(enabled)

    def _set_months_enabled(self, enabled: bool) -> None:
        for button in self.month_group.buttons():
            button.setEnabled(enabled)

    def reload(self) -> None:
        self._loading = True
        try:
            _set_switch(self.privacy_switch, self.repo.privacy_on)
            _set_switch(self.auto_switch, self.repo.auto_clear_on)

            ttl = int(self.repo.ttl)
            if ttl in config.TTL_PRESETS:
                index = config.TTL_PRESETS.index(ttl)
                button = self.ttl_group.button(index)
                if button is not None:
                    button.setChecked(True)
                self.custom_spin.setVisible(False)
            else:
                self.custom_radio.setChecked(True)
                self.custom_spin.setValue(max(1, round(ttl / 60)))
                self.custom_spin.setVisible(True)

            months = self.repo.auto_clear_months
            if months in config.AUTO_CLEAR_PRESETS:
                index = config.AUTO_CLEAR_PRESETS.index(months)
                button = self.month_group.button(index)
                if button is not None:
                    button.setChecked(True)

            self._set_ttl_enabled(self.repo.privacy_on)
            self._set_months_enabled(self.repo.auto_clear_on)

            mode = self.repo.theme_mode
            if mode in self._theme_modes:
                button = self.theme_group.button(self._theme_modes.index(mode))
                if button is not None:
                    button.setChecked(True)
        finally:
            self._loading = False
