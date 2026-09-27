from PySide6.QtGui import QImage

from videocutter.icons import export_icon, open_project_icon, save_project_icon, settings_icon, stop_export_icon


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


def test_toolbar_icons_share_one_stroke_style(qapp):
    opened = _image(open_project_icon())
    saved = _image(save_project_icon())
    settings = _image(settings_icon())
    exported = _image(export_icon())
    assert _signature(opened) != _signature(saved)
    assert _signature(opened) != _signature(exported)
    assert _signature(saved) != _signature(exported)
    assert _signature(settings) != _signature(exported)
    assert _opaque(opened, 11, 22)
    assert _opaque(opened, 6, 18)
    assert _opaque(opened, 18, 8)
    assert _opaque(saved, 11, 22)
    assert _opaque(saved, 24, 7)
    assert _opaque(settings, 16, 6)
    assert settings.pixelColor(16, 16).alpha() < 20
    assert _opaque(exported, 8, 20)
    assert _opaque(exported, 10, 18)
    assert _opaque(exported, 24, 6)
    stopped = _image(stop_export_icon())
    assert _signature(stopped) != _signature(exported)
    assert stopped.pixelColor(16, 16).alpha() > 200
    assert _opaque(stopped, 2, 2) is False
