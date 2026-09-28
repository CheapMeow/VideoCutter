import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPainterPathStroker, QPixmap, QTransform


ICON_COLOR = QColor("#e6e6e6")
_CANVAS = 32.0
_CANVAS_CENTER = QPointF(_CANVAS / 2, _CANVAS / 2)
# 每个 icon 墨迹外框的长边
_ICON_EXTENT = 24.0
# 主体与箭头的设计坐标以主体中心为原点
_BODY = QRectF(-8.0, -7.0, 16.0, 14.0)
_BODY_STROKE = 2.3
_DISK_CORNER = 2.2
_DISK_PLATTER = 4.4
_WINDOW_CORNER = 1.8
_WINDOW_BAR = 3.8
_WINDOW_BAR_INSET = 1.6
_ARROW_WIDTH = 3.5
_ARROW_GAP = 1.9
# 半径、出发方向与转角同时决定打开工程与保存工程两个 icon 的外框长边是否相等
_ARROW_RADIUS = 9.75
# 尾部出发方向，数学角度（0 指向右，逆时针为正）
_ARROW_HEADING = 93.0
# 弧线向右转过的角度
_ARROW_TURN = 73.0
_HEAD_LENGTH = 6.8
_HEAD_HALF = 4.6
_GEAR_TEETH = 8
_GEAR_ROOT = 0.7
_GEAR_HOLE = 0.3
_STOP_CORNER = 2.2


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
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ICON_COLOR)
    draw(painter)
    painter.end()
    return pixmap


def _draw_open_project(painter: QPainter) -> None:
    _draw_arrow_icon(painter, _disk_shape(), _arrow_layout()["inward"])


def _draw_save_project(painter: QPainter) -> None:
    _draw_arrow_icon(painter, _disk_shape(), _arrow_layout()["outward"])


def _draw_export(painter: QPainter) -> None:
    _draw_arrow_icon(painter, _window_shape(), _arrow_layout()["outward"])


def _draw_settings(painter: QPainter) -> None:
    painter.drawPath(_gear_shape())


def _draw_stop_export(painter: QPainter) -> None:
    painter.drawPath(_stop_shape())


def _draw_arrow_icon(painter: QPainter, body: QPainterPath, arrow: dict) -> None:
    painter.setWorldTransform(_arrow_frame_transform(body, arrow), True)
    painter.drawPath(body)
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.drawPath(arrow["mask"])
    painter.restore()
    painter.drawPath(arrow["shape"])


def _arrow_frame_transform(body: QPainterPath, arrow: dict) -> QTransform:
    frame = body.boundingRect().united(arrow["shape"].boundingRect())
    scale = _arrow_frame_scale()
    transform = QTransform()
    transform.translate(_CANVAS_CENTER.x(), _CANVAS_CENTER.y())
    transform.scale(scale, scale)
    transform.translate(-frame.center().x(), -frame.center().y())
    return transform


def _arrow_frame_scale() -> float:
    # 三个带箭头的 icon 共用一个缩放，弧线在三者之间保持同一曲率
    layout = _arrow_layout()
    extent = 0.0
    for body, arrow in (
        (_disk_shape(), layout["inward"]),
        (_disk_shape(), layout["outward"]),
        (_window_shape(), layout["outward"]),
    ):
        frame = body.boundingRect().united(arrow["shape"].boundingRect())
        extent = max(extent, frame.width(), frame.height())
    return _ICON_EXTENT / extent


def _arrow_layout() -> dict:
    heading = math.radians(_ARROW_HEADING)
    tail = QPointF(0.0, 0.0)
    center = QPointF(math.sin(heading) * _ARROW_RADIUS, math.cos(heading) * _ARROW_RADIUS)
    start = _ARROW_HEADING + 90.0
    end = start - _ARROW_TURN
    junction = _circle_point(center, _ARROW_RADIUS, end)
    end_heading = math.radians(_ARROW_HEADING - _ARROW_TURN)
    direction = QPointF(math.cos(end_heading), -math.sin(end_heading))
    tip = junction + direction * _HEAD_LENGTH
    outward = {
        "center": center,
        "start": start,
        "tail": tail,
        "junction": junction,
        "direction": direction,
        "tip": tip,
    }
    outward["shape"] = _arrow_shape(outward)
    outward["mask"] = _dilate(outward["shape"], _ARROW_GAP)
    # 沿尾部与顶点连线的中垂线镜像，两端互换，弧线曲率与凸出方向保持一致
    swap = _swap_ends(tail, tip)
    swapped_direction = swap.map(tip) - swap.map(tip - direction)
    inward = {
        "center": swap.map(center),
        "tail": swap.map(tail),
        "junction": swap.map(junction),
        "direction": swapped_direction,
        "tip": swap.map(tip),
        "shape": swap.map(outward["shape"]),
        "mask": swap.map(outward["mask"]),
    }
    return {"outward": outward, "inward": inward}


def _swap_ends(first: QPointF, second: QPointF) -> QTransform:
    chord = second - first
    length = math.hypot(chord.x(), chord.y())
    if length <= 0:
        raise RuntimeError("arrow tail and tip coincide")
    ax = chord.x() / length
    ay = chord.y() / length
    middle = (first + second) / 2
    offset = 2 * (middle.x() * ax + middle.y() * ay)
    return QTransform(
        1 - 2 * ax * ax,
        -2 * ax * ay,
        -2 * ax * ay,
        1 - 2 * ay * ay,
        offset * ax,
        offset * ay,
    )


def _circle_point(center: QPointF, radius: float, angle_deg: float) -> QPointF:
    angle = math.radians(angle_deg)
    return QPointF(center.x() + radius * math.cos(angle), center.y() - radius * math.sin(angle))


def _arrow_shape(arrow: dict) -> QPainterPath:
    center = arrow["center"]
    rect = QRectF(
        center.x() - _ARROW_RADIUS,
        center.y() - _ARROW_RADIUS,
        _ARROW_RADIUS * 2,
        _ARROW_RADIUS * 2,
    )
    line = QPainterPath()
    line.arcMoveTo(rect, arrow["start"])
    line.arcTo(rect, arrow["start"], -_ARROW_TURN)
    shaft = _stroke(line, _ARROW_WIDTH, Qt.PenCapStyle.FlatCap)
    return shaft.united(_head_shape(arrow["junction"], arrow["direction"]))


def _head_shape(junction: QPointF, direction: QPointF) -> QPainterPath:
    side = QPointF(-direction.y(), direction.x())
    path = QPainterPath()
    path.moveTo(junction + direction * _HEAD_LENGTH)
    path.lineTo(junction + side * _HEAD_HALF)
    path.lineTo(junction - side * _HEAD_HALF)
    path.closeSubpath()
    return path


def _stroke(path: QPainterPath, width: float, cap: Qt.PenCapStyle) -> QPainterPath:
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(cap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


def _dilate(path: QPainterPath, radius: float) -> QPainterPath:
    return path.united(_stroke(path, radius * 2, Qt.PenCapStyle.RoundCap))


def _disk_shape() -> QPainterPath:
    case = QPainterPath()
    case.addRoundedRect(_BODY, _DISK_CORNER, _DISK_CORNER)
    platter = QPainterPath()
    platter.addEllipse(_BODY.center(), _DISK_PLATTER, _DISK_PLATTER)
    return _stroke(case, _BODY_STROKE, Qt.PenCapStyle.RoundCap).united(
        _stroke(platter, _BODY_STROKE, Qt.PenCapStyle.RoundCap)
    )


def _window_shape() -> QPainterPath:
    frame = QPainterPath()
    frame.addRoundedRect(_BODY, _WINDOW_CORNER, _WINDOW_CORNER)
    bar_y = _BODY.top() + _WINDOW_BAR
    bar = QPainterPath()
    bar.moveTo(_BODY.left() + _WINDOW_BAR_INSET, bar_y)
    bar.lineTo(_BODY.right() - _WINDOW_BAR_INSET, bar_y)
    return _stroke(frame, _BODY_STROKE, Qt.PenCapStyle.RoundCap).united(
        _stroke(bar, _BODY_STROKE, Qt.PenCapStyle.RoundCap)
    )


def _gear_shape() -> QPainterPath:
    width = _BODY_STROKE * _arrow_frame_scale()
    unit = _gear_outline(1.0)
    unit_extent = max(unit.boundingRect().width(), unit.boundingRect().height())
    # 圆角连接的描边在每个方向都向外扩展半个线宽
    radius = (_ICON_EXTENT - width) / unit_extent
    outline = _gear_outline(radius)
    hole = QPainterPath()
    hole.addEllipse(QPointF(0.0, 0.0), radius * _GEAR_HOLE, radius * _GEAR_HOLE)
    shape = _stroke(outline, width, Qt.PenCapStyle.RoundCap).united(
        _stroke(hole, width, Qt.PenCapStyle.RoundCap)
    )
    offset = _CANVAS_CENTER - shape.boundingRect().center()
    return shape.translated(offset)


def _gear_outline(radius: float) -> QPainterPath:
    span = 2 * math.pi / _GEAR_TEETH
    path = QPainterPath()
    for index in range(_GEAR_TEETH):
        middle = index * span - math.pi / 2
        points = (
            (radius * _GEAR_ROOT, middle - span * 0.36),
            (radius, middle - span * 0.14),
            (radius, middle + span * 0.14),
            (radius * _GEAR_ROOT, middle + span * 0.36),
        )
        for distance, angle in points:
            point = QPointF(distance * math.cos(angle), distance * math.sin(angle))
            if path.elementCount() == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
    path.closeSubpath()
    return path


def _stop_shape() -> QPainterPath:
    corner = _STOP_CORNER * _arrow_frame_scale()
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(
            _CANVAS_CENTER.x() - _ICON_EXTENT / 2,
            _CANVAS_CENTER.y() - _ICON_EXTENT / 2,
            _ICON_EXTENT,
            _ICON_EXTENT,
        ),
        corner,
        corner,
    )
    return path
