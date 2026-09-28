import math

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage

from videocutter.icons import (
    _ARROW_GAP,
    _HEAD_HALF,
    _HEAD_LENGTH,
    _HEAD_OVERLAP,
    _arrow_head_path,
    _dilate_path,
    _draw_arc_arrow,
    _inward_layout,
    _paint,
    _shared_arrow_geometry,
    export_icon,
    open_project_icon,
    save_project_icon,
    settings_icon,
    stop_export_icon,
)


def _image(icon) -> QImage:
    image = icon.pixmap(32, 32).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    if image.width() != 32 or image.height() != 32:
        image = image.scaled(32, 32)
    return image


def _opaque(image: QImage, x: int, y: int) -> bool:
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            px = x + dx
            py = y + dy
            if px < 0 or py < 0 or px >= image.width() or py >= image.height():
                continue
            if image.pixelColor(px, py).alpha() > 80:
                return True
    return False


def _signature(image: QImage) -> tuple[int, ...]:
    values = []
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            color = image.pixelColor(x, y)
            values.append(color.alpha())
    return tuple(values)


def _centroid(image: QImage) -> tuple[float, float]:
    total = 0
    sum_x = 0
    sum_y = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() <= 80:
                continue
            sum_x += x
            sum_y += y
            total += 1
    if total == 0:
        raise RuntimeError("icon has no ink")
    return sum_x / total, sum_y / total


def _ink(image: QImage, x: int, y: int) -> int:
    count = 0
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            px = x + dx
            py = y + dy
            if px < 0 or py < 0 or px >= image.width() or py >= image.height():
                continue
            if image.pixelColor(px, py).alpha() > 80:
                count += 1
    return count


def _near_ink(pixels: set[tuple[int, int]], x: float, y: float) -> bool:
    for px, py in pixels:
        if math.hypot(px - x, py - y) <= 1.6:
            return True
    return False


def _ink_pixels(draw) -> set[tuple[int, int]]:
    image = _paint(draw).toImage()
    step = int(image.devicePixelRatio())
    pixels = set()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            if image.pixelColor(x, y).alpha() > 80:
                pixels.add((x // step, y // step))
    return pixels


def test_inward_arrow_reverses_the_outward_arrow_ends(qapp):
    geometry = _shared_arrow_geometry()
    layout = _inward_layout(geometry)
    center = geometry["inward_junction"]
    assert math.hypot(layout["tip"].x() - center.x(), layout["tip"].y() - center.y()) < 1e-4
    assert abs(layout["arc_span"] - geometry["shaft_span"]) < 1e-9
    assert abs(layout["radius"] - geometry["radius"]) < 1e-9
    start = math.radians(layout["arc_start"])
    travel_x = math.sin(start) if layout["arc_span"] < 0 else -math.sin(start)
    travel_y = math.cos(start) if layout["arc_span"] < 0 else -math.cos(start)
    assert abs(layout["axis_x"] + travel_x) < 1e-4
    assert abs(layout["axis_y"] + travel_y) < 1e-4
    outward_tip_x = geometry["outward_junction"].x() + geometry["outward_tangent_x"] * _HEAD_LENGTH
    outward_tip_y = geometry["outward_junction"].y() + geometry["outward_tangent_y"] * _HEAD_LENGTH
    assert math.hypot(layout["tail"].x() - outward_tip_x, layout["tail"].y() - outward_tip_y) < 1e-4
    inward = _ink_pixels(lambda painter: _draw_arc_arrow(painter, inward=True))
    outward = _ink_pixels(lambda painter: _draw_arc_arrow(painter, inward=False))
    assert _near_ink(inward, layout["tip"].x(), layout["tip"].y())
    assert _near_ink(inward, layout["tail"].x(), layout["tail"].y())
    assert _near_ink(outward, outward_tip_x, outward_tip_y)
    assert inward - outward
    assert outward - inward


def test_inward_mask_uses_the_same_expansion_radius(qapp):
    geometry = _shared_arrow_geometry()
    layout = _inward_layout(geometry)
    mask = _dilate_path(
        _arrow_head_path(
            layout["base"],
            layout["axis_x"],
            layout["axis_y"],
            layout["axis_length"],
            _HEAD_HALF,
            _HEAD_OVERLAP,
        ),
        _ARROW_GAP,
    )
    axis_x = layout["axis_x"]
    axis_y = layout["axis_y"]
    side_x = -axis_y
    side_y = axis_x
    tip = layout["tip"]
    left_x = layout["base"].x() - axis_x * _HEAD_OVERLAP + side_x * _HEAD_HALF
    left_y = layout["base"].y() - axis_y * _HEAD_OVERLAP + side_y * _HEAD_HALF
    mid_x = (tip.x() + left_x) / 2
    mid_y = (tip.y() + left_y) / 2
    edge_x = left_x - tip.x()
    edge_y = left_y - tip.y()
    normal_x = -edge_y
    normal_y = edge_x
    if normal_x * side_x + normal_y * side_y < 0:
        normal_x = -normal_x
        normal_y = -normal_y
    normal_length = math.hypot(normal_x, normal_y)
    normal_x /= normal_length
    normal_y /= normal_length
    inside = QPointF(mid_x + normal_x * _ARROW_GAP * 0.5, mid_y + normal_y * _ARROW_GAP * 0.5)
    outside = QPointF(mid_x + normal_x * _ARROW_GAP * 1.35, mid_y + normal_y * _ARROW_GAP * 1.35)
    assert mask.contains(inside)
    assert mask.contains(outside) is False
    past_tip = QPointF(tip.x() + axis_x * _ARROW_GAP * 0.5, tip.y() + axis_y * _ARROW_GAP * 0.5)
    beyond_tip = QPointF(tip.x() + axis_x * _ARROW_GAP * 1.35, tip.y() + axis_y * _ARROW_GAP * 1.35)
    assert mask.contains(past_tip)
    assert mask.contains(beyond_tip) is False


def test_arrowhead_base_is_perpendicular_to_the_arc(qapp):
    geometry = _shared_arrow_geometry()
    end = math.radians(geometry["shaft_start"] + geometry["shaft_span"])
    assert abs(geometry["outward_tangent_x"] - math.sin(end)) < 1e-6
    assert abs(geometry["outward_tangent_y"] - math.cos(end)) < 1e-6
    start = math.radians(geometry["shaft_start"])
    assert abs(geometry["inward_tangent_x"] + math.sin(start)) < 1e-6
    assert abs(geometry["inward_tangent_y"] + math.cos(start)) < 1e-6


def test_toolbar_icons_share_one_stroke_style(qapp):
    opened = _image(open_project_icon())
    saved = _image(save_project_icon())
    settings = _image(settings_icon())
    exported = _image(export_icon())
    assert _signature(opened) != _signature(saved)
    assert _signature(opened) != _signature(exported)
    assert _signature(saved) != _signature(exported)
    assert _signature(settings) != _signature(exported)
    for image in (opened, saved, exported):
        center_x, center_y = _centroid(image)
        assert abs(center_x - 16) < 3
        assert abs(center_y - 16) < 3
    assert _opaque(opened, 16, 22)
    assert _opaque(opened, 20, 6)
    assert _ink(opened, 18, 8) >= 8
    assert _opaque(saved, 16, 22)
    assert _opaque(saved, 21, 4)
    assert _ink(saved, 16, 12) >= 8
    assert _opaque(saved, 30, 1) is False
    assert _opaque(settings, 16, 6)
    assert settings.pixelColor(16, 16).alpha() < 20
    assert _opaque(exported, 16, 22)
    assert _opaque(exported, 21, 4)
    assert _ink(exported, 16, 12) >= 8
    assert _opaque(exported, 30, 1) is False
    stopped = _image(stop_export_icon())
    assert _signature(stopped) != _signature(exported)
    assert stopped.pixelColor(16, 16).alpha() > 200
    assert _opaque(stopped, 2, 2) is False
