from PySide6.QtGui import QImage

from videocutter.icons import (
    _draw_arc_arrow,
    _paint,
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


def test_open_and_save_arrows_follow_the_same_arc(qapp):
    def ink(inward: bool) -> set[tuple[int, int]]:
        image = _paint(lambda painter: _draw_arc_arrow(painter, inward=inward)).toImage()
        step = int(image.devicePixelRatio())
        pixels = set()
        for y in range(0, image.height(), step):
            for x in range(0, image.width(), step):
                if image.pixelColor(x, y).alpha() > 80:
                    pixels.add((x // step, y // step))
        return pixels

    outward = ink(False)
    inward = ink(True)
    shared = outward & inward
    assert len(shared) > len(outward - inward)
    assert len(shared) > len(inward - outward)


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
