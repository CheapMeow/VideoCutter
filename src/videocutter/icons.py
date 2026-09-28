import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


ICON_COLOR = QColor("#e6e6e6")
_HEAD_LENGTH = 4.6
_SYMBOL = QRectF(2.2, 12.4, 16.2, 15.2)
_ARROW_SWEEP = 125.0


def open_project_icon() -> QIcon:
    return QIcon(_paint(_draw_open_project))


def save_project_icon() -> QIcon:
    return QIcon(_paint(_draw_save_project))


def settings_icon() -> QIcon:
    return QIcon(_paint(_draw_settings))


def export_icon() -> QIcon:
    return QIcon(_paint(_draw_export))


def stop_export_icon() -> QIcon:
    return QIcon(_paint(_draw_stop_export))


def _paint(draw) -> QPixmap:
    pixmap = QPixmap(64, 64)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(ICON_COLOR)
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter)
    painter.end()
    return pixmap


def _draw_disk(painter: QPainter) -> None:
    painter.drawRoundedRect(_SYMBOL, 2.0, 2.0)
    painter.drawEllipse(_SYMBOL.center(), 3.1, 3.1)


def _draw_window(painter: QPainter) -> None:
    painter.drawRoundedRect(_SYMBOL, 1.6, 1.6)
    bar_y = _SYMBOL.top() + 4.0
    painter.drawLine(QPointF(_SYMBOL.left() + 1.5, bar_y), QPointF(_SYMBOL.right() - 1.5, bar_y))


def _outside_tip(rect: QRectF) -> QPointF:
    return QPointF(rect.right() + 2.4, rect.top() - 2.6)


def _draw_open_project(painter: QPainter) -> None:
    _draw_disk(painter)
    _draw_arc_arrow(painter, _outside_tip(_SYMBOL), _SYMBOL.center(), _ARROW_SWEEP)


def _draw_save_project(painter: QPainter) -> None:
    _draw_disk(painter)
    _draw_arc_arrow(painter, _SYMBOL.center(), _outside_tip(_SYMBOL), -_ARROW_SWEEP)


def _draw_settings(painter: QPainter) -> None:
    center = QPointF(16.0, 16.0)
    teeth = 8
    outer = 11.0
    root = 7.6
    span = 2 * math.pi / teeth
    path = QPainterPath()
    for index in range(teeth):
        base = index * span - math.pi / 2
        points = (
            (root, base + span * 0.08),
            (outer, base + span * 0.28),
            (outer, base + span * 0.52),
            (root, base + span * 0.72),
        )
        for radius, angle in points:
            point = QPointF(center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle))
            if index == 0 and radius == root and angle == points[0][1]:
                path.moveTo(point)
            else:
                path.lineTo(point)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawEllipse(center, 3.1, 3.1)


def _draw_export(painter: QPainter) -> None:
    _draw_window(painter)
    _draw_arc_arrow(painter, _SYMBOL.center(), _outside_tip(_SYMBOL), -_ARROW_SWEEP)


def _draw_stop_export(painter: QPainter) -> None:
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ICON_COLOR)
    painter.drawRoundedRect(QRectF(8.2, 8.2, 15.6, 15.6), 2.2, 2.2)
    painter.restore()


def _draw_arc_arrow(painter: QPainter, tail: QPointF, tip: QPointF, sweep_deg: float) -> None:
    chord_x = tip.x() - tail.x()
    chord_y = tip.y() - tail.y()
    distance = math.hypot(chord_x, chord_y)
    if distance <= 0:
        raise RuntimeError("arrow length is zero")
    half = math.radians(sweep_deg) / 2
    if abs(math.sin(half)) < 1e-3:
        raise RuntimeError("arrow sweep is too small")
    radius = (distance / 2) / abs(math.sin(half))
    mid_x = (tail.x() + tip.x()) / 2
    mid_y = (tail.y() + tip.y()) / 2
    unit_x = chord_x / distance
    unit_y = chord_y / distance
    left_x = unit_y
    left_y = -unit_x
    center_offset = radius * math.cos(abs(half))
    if sweep_deg < 0:
        center_offset = -center_offset
    center_x = mid_x + left_x * center_offset
    center_y = mid_y + left_y * center_offset
    start_deg = math.degrees(math.atan2(center_y - tail.y(), tail.x() - center_x))
    head_deg = math.degrees(_HEAD_LENGTH / radius)
    if abs(sweep_deg) <= head_deg + 20:
        raise RuntimeError("arrow head leaves no visible arc")
    span_deg = sweep_deg - head_deg if sweep_deg > 0 else sweep_deg + head_deg
    rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)
    painter.drawArc(rect, int(round(start_deg * 16)), int(round(span_deg * 16)))
    end_rad = math.radians(start_deg + sweep_deg)
    tangent_x = -math.sin(end_rad)
    tangent_y = -math.cos(end_rad)
    if sweep_deg < 0:
        tangent_x = -tangent_x
        tangent_y = -tangent_y
    _draw_arrow_head(painter, tip, tangent_x, tangent_y)


def _draw_arrow_head(painter: QPainter, tip: QPointF, unit_x: float, unit_y: float) -> None:
    side_x = -unit_y
    side_y = unit_x
    base = QPointF(tip.x() - unit_x * _HEAD_LENGTH, tip.y() - unit_y * _HEAD_LENGTH)
    half = 2.7
    left = QPointF(base.x() + side_x * half, base.y() + side_y * half)
    right = QPointF(base.x() - side_x * half, base.y() - side_y * half)
    path = QPainterPath()
    path.moveTo(tip)
    path.lineTo(left)
    path.lineTo(right)
    path.closeSubpath()
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ICON_COLOR)
    painter.drawPath(path)
    painter.restore()
