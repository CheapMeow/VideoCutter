import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


ICON_COLOR = QColor("#e6e6e6")
_SYMBOL = QRectF(8.2, 9.2, 15.6, 13.6)
_SYMBOL_STROKE = 2.3
_ARROW_WIDTH = 3.5
_ARROW_GAP = 1.9
_ARROW_SWEEP = 118.0
_HEAD_LENGTH = 6.8
_HEAD_HALF = 4.6


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
    _apply_pen(painter, _SYMBOL_STROKE, ICON_COLOR)
    painter.drawRoundedRect(_SYMBOL, 2.2, 2.2)
    painter.drawEllipse(_SYMBOL.center(), 4.4, 4.4)


def _draw_window(painter: QPainter) -> None:
    _apply_pen(painter, _SYMBOL_STROKE, ICON_COLOR)
    painter.drawRoundedRect(_SYMBOL, 1.8, 1.8)
    bar_y = _SYMBOL.top() + 3.8
    painter.drawLine(QPointF(_SYMBOL.left() + 1.6, bar_y), QPointF(_SYMBOL.right() - 1.6, bar_y))


def _outside_tip(rect: QRectF) -> QPointF:
    return QPointF(rect.right() + 1.5, rect.top() - 2.0)


def _draw_open_project(painter: QPainter) -> None:
    _draw_disk(painter)
    _draw_arc_arrow(painter, inward=True)


def _draw_save_project(painter: QPainter) -> None:
    _draw_disk(painter)
    _draw_arc_arrow(painter, inward=False)


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
    _draw_arc_arrow(painter, inward=False)


def _draw_stop_export(painter: QPainter) -> None:
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ICON_COLOR)
    painter.drawRoundedRect(QRectF(8.2, 8.2, 15.6, 15.6), 2.2, 2.2)
    painter.restore()


def _draw_arc_arrow(painter: QPainter, inward: bool) -> None:
    geometry = _shared_arrow_geometry()
    if inward:
        head_tip = geometry["tail"]
        tangent_x = geometry["inward_tangent_x"]
        tangent_y = geometry["inward_tangent_y"]
    else:
        head_tip = geometry["tip"]
        tangent_x = geometry["outward_tangent_x"]
        tangent_y = geometry["outward_tangent_y"]
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    _stroke_shaft(painter, geometry, _ARROW_WIDTH + _ARROW_GAP * 2)
    _stroke_head(painter, head_tip, tangent_x, tangent_y, _ARROW_GAP)
    painter.restore()
    _stroke_shaft(painter, geometry, _ARROW_WIDTH)
    if inward:
        _erase_head_cap(painter, head_tip, _ARROW_WIDTH)
    _stroke_head(painter, head_tip, tangent_x, tangent_y, 0.0)


def _shared_arrow_geometry() -> dict:
    tail = _SYMBOL.center()
    tip = _outside_tip(_SYMBOL)
    sweep_deg = -_ARROW_SWEEP
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
    if abs(sweep_deg) <= head_deg + 24:
        raise RuntimeError("arrow head leaves no visible arc")
    shaft_start = start_deg
    shaft_span = sweep_deg + head_deg
    outward_tangent_x, outward_tangent_y = _sweep_tangent(start_deg + sweep_deg, sweep_deg)
    inward_tangent_x, inward_tangent_y = _sweep_tangent(start_deg, -sweep_deg)
    return {
        "center_x": center_x,
        "center_y": center_y,
        "radius": radius,
        "shaft_start": shaft_start,
        "shaft_span": shaft_span,
        "tail": tail,
        "tip": tip,
        "outward_tangent_x": outward_tangent_x,
        "outward_tangent_y": outward_tangent_y,
        "inward_tangent_x": inward_tangent_x,
        "inward_tangent_y": inward_tangent_y,
    }


def _sweep_tangent(angle_deg: float, sweep_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    tangent_x = -math.sin(rad)
    tangent_y = -math.cos(rad)
    if sweep_deg < 0:
        tangent_x = -tangent_x
        tangent_y = -tangent_y
    return tangent_x, tangent_y


def _stroke_shaft(painter: QPainter, geometry: dict, width: float) -> None:
    _apply_pen(painter, width, ICON_COLOR)
    pen = painter.pen()
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    rect = QRectF(
        geometry["center_x"] - geometry["radius"],
        geometry["center_y"] - geometry["radius"],
        geometry["radius"] * 2,
        geometry["radius"] * 2,
    )
    painter.drawArc(
        rect,
        int(round(geometry["shaft_start"] * 16)),
        int(round(geometry["shaft_span"] * 16)),
    )


def _erase_head_cap(painter: QPainter, tip: QPointF, width: float) -> None:
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ICON_COLOR)
    radius = width / 2
    painter.drawEllipse(QRectF(tip.x() - radius, tip.y() - radius, width, width))
    painter.restore()


def _stroke_head(
    painter: QPainter,
    tip: QPointF,
    tangent_x: float,
    tangent_y: float,
    head_extra: float,
) -> None:
    grown_tip = QPointF(tip.x() + tangent_x * head_extra, tip.y() + tangent_y * head_extra)
    _draw_arrow_head(
        painter,
        grown_tip,
        tangent_x,
        tangent_y,
        _HEAD_LENGTH + head_extra * 2,
        _HEAD_HALF + head_extra,
    )


def _draw_arrow_head(
    painter: QPainter,
    tip: QPointF,
    unit_x: float,
    unit_y: float,
    length: float,
    half: float,
) -> None:
    side_x = -unit_y
    side_y = unit_x
    base = QPointF(tip.x() - unit_x * length, tip.y() - unit_y * length)
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


def _apply_pen(painter: QPainter, width: float, color: QColor) -> None:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
