"""程序内绘制的矢量图标，避免依赖 emoji / 特殊符号字体。"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _base(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    return pixmap


def shield_icon(active: bool, color: str = "#B45309", size: int = 64) -> QIcon:
    """盾牌：实心表示当前是敏感内容，描边表示普通内容。"""
    pixmap = _base(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    path = QPainterPath()
    path.moveTo(size * 0.50, size * 0.12)
    path.lineTo(size * 0.82, size * 0.26)
    path.lineTo(size * 0.82, size * 0.52)
    path.cubicTo(size * 0.82, size * 0.74, size * 0.66, size * 0.86, size * 0.50, size * 0.92)
    path.cubicTo(size * 0.34, size * 0.86, size * 0.18, size * 0.74, size * 0.18, size * 0.52)
    path.lineTo(size * 0.18, size * 0.26)
    path.closeSubpath()

    if active:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawPath(path)
    else:
        painter.setPen(
            QPen(QColor(color), size * 0.07, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    painter.end()
    return QIcon(pixmap)


def pin_icon(active: bool, color: str = "#4B5563", size: int = 64) -> QIcon:
    """图钉：实心表示已置顶。"""
    pixmap = _base(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(size / 2, size / 2)
    painter.rotate(45)
    painter.setPen(
        QPen(QColor(color), size * 0.07, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    )

    # 钉帽
    painter.setBrush(QColor(color) if active else Qt.NoBrush)
    painter.drawRoundedRect(
        QRectF(-size * 0.26, -size * 0.36, size * 0.52, size * 0.13),
        size * 0.05,
        size * 0.05,
    )

    # 钉身
    painter.setBrush(Qt.NoBrush)
    body = QPainterPath()
    body.moveTo(-size * 0.15, -size * 0.22)
    body.lineTo(-size * 0.07, size * 0.02)
    body.lineTo(size * 0.07, size * 0.02)
    body.lineTo(size * 0.15, -size * 0.22)
    painter.drawPath(body)

    # 针尖
    painter.drawLine(QPointF(0, size * 0.02), QPointF(0, size * 0.34))

    painter.end()
    return QIcon(pixmap)


def trash_icon(color: str = "#6B7280", size: int = 64) -> QIcon:
    pixmap = _base(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(
        QPen(QColor(color), size * 0.065, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    )
    painter.setBrush(Qt.NoBrush)

    # 盖子与提手
    painter.drawLine(QPointF(size * 0.24, size * 0.28), QPointF(size * 0.76, size * 0.28))
    painter.drawLine(QPointF(size * 0.40, size * 0.28), QPointF(size * 0.40, size * 0.20))
    painter.drawLine(QPointF(size * 0.40, size * 0.20), QPointF(size * 0.60, size * 0.20))
    painter.drawLine(QPointF(size * 0.60, size * 0.20), QPointF(size * 0.60, size * 0.28))

    # 桶身
    body = QPainterPath()
    body.moveTo(size * 0.31, size * 0.31)
    body.lineTo(size * 0.69, size * 0.31)
    body.lineTo(size * 0.655, size * 0.78)
    body.quadTo(size * 0.65, size * 0.85, size * 0.59, size * 0.85)
    body.lineTo(size * 0.41, size * 0.85)
    body.quadTo(size * 0.35, size * 0.85, size * 0.345, size * 0.78)
    body.closeSubpath()
    painter.drawPath(body)

    # 内部竖线
    painter.drawLine(QPointF(size * 0.43, size * 0.40), QPointF(size * 0.44, size * 0.76))
    painter.drawLine(QPointF(size * 0.57, size * 0.40), QPointF(size * 0.56, size * 0.76))

    painter.end()
    return QIcon(pixmap)


def select_icon(color: str = "#6B7280", size: int = 64) -> QIcon:
    pixmap = _base(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(
        QPen(QColor(color), size * 0.065, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    )
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(
        QRectF(size * 0.18, size * 0.18, size * 0.64, size * 0.64),
        size * 0.14,
        size * 0.14,
    )
    check = QPainterPath()
    check.moveTo(size * 0.32, size * 0.52)
    check.lineTo(size * 0.45, size * 0.65)
    check.lineTo(size * 0.70, size * 0.36)
    painter.drawPath(check)
    painter.end()
    return QIcon(pixmap)


def back_icon(color: str = "#4B5563", size: int = 48) -> QIcon:
    pixmap = _base(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(color), size * 0.12, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawLine(QPointF(size * 0.60, size * 0.26), QPointF(size * 0.36, size * 0.50))
    painter.drawLine(QPointF(size * 0.36, size * 0.50), QPointF(size * 0.60, size * 0.74))
    painter.end()
    return QIcon(pixmap)


def close_icon(color: str = "#475569", size: int = 48) -> QIcon:
    pixmap = _base(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(color), size * 0.13, Qt.SolidLine, Qt.RoundCap))
    margin = size * 0.31
    painter.drawLine(QPointF(margin, margin), QPointF(size - margin, size - margin))
    painter.drawLine(QPointF(size - margin, margin), QPointF(margin, size - margin))
    painter.end()
    return QIcon(pixmap)


def gear_icon(color: str = "#9aa0b0", size: int = 64) -> QIcon:
    pixmap = _base(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(size / 2, size / 2)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))

    # 八颗齿
    for i in range(8):
        painter.save()
        painter.rotate(i * 45)
        painter.drawRoundedRect(
            QRectF(-size * 0.062, -size * 0.44, size * 0.124, size * 0.17),
            size * 0.03,
            size * 0.03,
        )
        painter.restore()

    # 齿圈 + 中心孔
    ring = QPainterPath()
    ring.addEllipse(QPointF(0, 0), size * 0.34, size * 0.34)
    hole = QPainterPath()
    hole.addEllipse(QPointF(0, 0), size * 0.135, size * 0.135)
    painter.drawPath(ring.subtracted(hole))
    painter.end()
    return QIcon(pixmap)


def star_icon(filled: bool, color: str | None = None, size: int = 64) -> QIcon:
    pixmap = _base(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    path = QPainterPath()
    center = size / 2
    outer = size * 0.44
    inner = size * 0.185
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(-90 + i * 36)
        point = QPointF(center + radius * math.cos(angle), center + radius * math.sin(angle))
        if i == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()

    if filled:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color or "#f59e0b"))
        painter.drawPath(path)
    else:
        painter.setPen(
            QPen(QColor(color or "#94a3b8"), size * 0.07, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    painter.end()
    return QIcon(pixmap)
