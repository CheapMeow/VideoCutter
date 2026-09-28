import math

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainterPath, QTransform

from videocutter.icons import (
    _ARROW_GAP,
    _ARROW_RADIUS,
    _ARROW_TURN,
    _BODY,
    _arrow_frame_transform,
    _arrow_layout,
    _disk_shape,
    _draw_export,
    _draw_open_project,
    _draw_save_project,
    _draw_settings,
    _draw_stop_export,
    _head_shape,
    _paint,
    export_icon,
    open_project_icon,
    save_project_icon,
    settings_icon,
    stop_export_icon,
)


def _distance(first: QPointF, second: QPointF) -> float:
    return math.hypot(first.x() - second.x(), first.y() - second.y())


def _dot(first: QPointF, second: QPointF) -> float:
    return first.x() * second.x() + first.y() * second.y()


def _alpha_image(draw) -> QImage:
    return _paint(draw).toImage().convertToFormat(QImage.Format.Format_ARGB32)


def _ink_box(image: QImage) -> tuple[int, int, int, int]:
    xs = []
    ys = []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 80:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise RuntimeError("icon has no ink")
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


_FLATTEN_SCALE = 64.0


def _shape_polygons(path: QPainterPath):
    return path.toSubpathPolygons(QTransform.fromScale(_FLATTEN_SCALE, _FLATTEN_SCALE))


def _distance_to_shape(point: QPointF, polygons) -> float:
    point = point * _FLATTEN_SCALE
    return _distance_to_polygons(point, polygons) / _FLATTEN_SCALE


def _distance_to_polygons(point: QPointF, polygons) -> float:
    best = math.inf
    for polygon in polygons:
        for index in range(polygon.count() - 1):
            start = polygon.at(index)
            end = polygon.at(index + 1)
            segment = end - start
            length = _dot(segment, segment)
            if length == 0:
                best = min(best, _distance(point, start))
                continue
            t = max(0.0, min(1.0, _dot(point - start, segment) / length))
            best = min(best, _distance(point, start + segment * t))
    return best


def test_inward_tip_is_the_disk_center_and_tail_is_the_outward_tip():
    layout = _arrow_layout()
    assert _distance(layout["inward"]["tip"], _BODY.center()) < 1e-6
    assert _distance(layout["outward"]["tail"], _BODY.center()) < 1e-6
    assert _distance(layout["inward"]["tail"], layout["outward"]["tip"]) < 1e-6


def test_both_arcs_share_radius_and_turn():
    layout = _arrow_layout()
    for arrow in (layout["outward"], layout["inward"]):
        center = arrow["center"]
        assert abs(_distance(arrow["tail"], center) - _ARROW_RADIUS) < 1e-6
        assert abs(_distance(arrow["junction"], center) - _ARROW_RADIUS) < 1e-6
        tail = arrow["tail"] - center
        junction = arrow["junction"] - center
        cosine = _dot(tail, junction) / (_ARROW_RADIUS * _ARROW_RADIUS)
        assert abs(math.degrees(math.acos(cosine)) - _ARROW_TURN) < 1e-4


def test_head_base_is_perpendicular_to_the_arc_at_the_join():
    layout = _arrow_layout()
    for arrow in (layout["outward"], layout["inward"]):
        direction = arrow["direction"]
        assert abs(math.hypot(direction.x(), direction.y()) - 1) < 1e-6
        radial = arrow["junction"] - arrow["center"]
        assert abs(_dot(direction, radial)) < 1e-6
        head = _head_shape(arrow["junction"], direction)
        tip = QPointF(head.elementAt(0).x, head.elementAt(0).y)
        left = QPointF(head.elementAt(1).x, head.elementAt(1).y)
        right = QPointF(head.elementAt(2).x, head.elementAt(2).y)
        assert _distance(tip, arrow["tip"]) < 1e-6
        assert abs(_dot(left - right, direction)) < 1e-6
        assert _distance((left + right) / 2, arrow["junction"]) < 1e-6


def test_mask_is_the_arrow_expanded_by_one_gap_on_every_side():
    layout = _arrow_layout()
    for arrow in (layout["outward"], layout["inward"]):
        shape = arrow["shape"]
        polygons = _shape_polygons(shape)
        box = shape.boundingRect().adjusted(-3, -3, 3, 3)
        step = 0.4
        y = box.top()
        checked = 0
        while y < box.bottom():
            x = box.left()
            while x < box.right():
                point = QPointF(x, y)
                if not shape.contains(point):
                    distance = _distance_to_shape(point, polygons)
                    if distance < _ARROW_GAP - 0.1:
                        assert arrow["mask"].contains(point)
                        checked += 1
                    elif distance > _ARROW_GAP + 0.1:
                        assert not arrow["mask"].contains(point)
                x += step
            y += step
        assert checked > 100


def test_body_is_erased_inside_the_mask_ring(qapp):
    layout = _arrow_layout()
    for draw, arrow in ((_draw_open_project, layout["inward"]), (_draw_save_project, layout["outward"])):
        image = _alpha_image(draw)
        inverse, invertible = _arrow_frame_transform(_disk_shape(), arrow).inverted()
        assert invertible
        body = _disk_shape()
        polygons = _shape_polygons(arrow["shape"])
        ratio = image.devicePixelRatio()
        erased = 0
        for py in range(image.height()):
            for px in range(image.width()):
                point = inverse.map(QPointF((px + 0.5) / ratio, (py + 0.5) / ratio))
                if arrow["shape"].contains(point) or not body.contains(point):
                    continue
                distance = _distance_to_shape(point, polygons)
                if 0.6 < distance < _ARROW_GAP - 0.6:
                    assert image.pixelColor(px, py).alpha() < 40
                    erased += 1
        assert erased > 0


def test_every_icon_has_the_same_outer_size(qapp):
    boxes = [
        _ink_box(_alpha_image(draw))
        for draw in (_draw_open_project, _draw_save_project, _draw_settings, _draw_export, _draw_stop_export)
    ]
    sizes = [max(right - left, bottom - top) for left, top, right, bottom in boxes]
    assert max(sizes) - min(sizes) <= 1
    for left, top, right, bottom in boxes:
        assert abs((left + right) / 2 - 32) <= 1
        assert abs((top + bottom) / 2 - 32) <= 1


def test_toolbar_icons_render_distinct_shapes(qapp):
    images = [
        icon.pixmap(32, 32).toImage().convertToFormat(QImage.Format.Format_ARGB32)
        for icon in (open_project_icon(), save_project_icon(), settings_icon(), export_icon(), stop_export_icon())
    ]
    signatures = {
        tuple(image.pixelColor(x, y).alpha() for y in range(image.height()) for x in range(image.width()))
        for image in images
    }
    assert len(signatures) == len(images)
    settings = _alpha_image(_draw_settings)
    assert settings.pixelColor(32, 32).alpha() < 20
    stop = _alpha_image(_draw_stop_export)
    assert stop.pixelColor(32, 32).alpha() > 200
