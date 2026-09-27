import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


ICON_COLOR = QColor("#e6e6e6")
_HEAD_LENGTH = 6.0


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
    body = QRectF(3.2, 15.2, 15.6, 12.6)
    painter.drawRoundedRect(body, 2.0, 2.0)
    painter.drawEllipse(QPointF(11.0, 21.6), 3.5, 3.5)


def _draw_window(painter: QPainter) -> None:
    frame = QRectF(3.2, 14.6, 15.2, 13.2)
    painter.drawRoundedRect(frame, 1.6, 1.6)
    bar_y = frame.top() + 4.0
    painter.drawLine(QPointF(frame.left() + 1.4, bar_y), QPointF(frame.right() - 1.4, bar_y))


def _draw_open_project(painter: QPainter) -> None:
    _draw_disk(painter)
    _draw_curved_arrow(painter, QPointF(26.6, 3.2), QPointF(23.2, 6.4), QPointF(16.6, 14.0))


def _draw_save_project(painter: QPainter) -> None:
    _draw_disk(painter)
    _draw_curved_arrow(painter, QPointF(17.2, 13.2), QPointF(24.5, 10.0), QPointF(27.2, 3.4))


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
    _draw_curved_arrow(painter, QPointF(17.0, 12.4), QPointF(24.8, 9.2), QPointF(27.2, 3.2))


def _draw_stop_export(painter: QPainter) -> None:
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ICON_COLOR)
    painter.drawRoundedRect(QRectF(8.2, 8.2, 15.6, 15.6), 2.2, 2.2)
    painter.restore()


def _draw_curved_arrow(painter: QPainter, start: QPointF, control: QPointF, tip: QPointF) -> None:
    direction = QPointF(tip.x() - control.x(), tip.y() - control.y())
    length = math.hypot(direction.x(), direction.y())
    if length <= 0:
        raise RuntimeError("arrow direction has zero length")
    unit_x = direction.x() / length
    unit_y = direction.y() / length
    stem_end = QPointF(tip.x() - unit_x * _HEAD_LENGTH, tip.y() - unit_y * _HEAD_LENGTH)
    path = QPainterPath(start)
    path.quadTo(control, stem_end)
    painter.drawPath(path)
    _draw_arrow_head(painter, tip, unit_x, unit_y)


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
