import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QDropEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.support import write_color_video
from videocutter.geometry import TRACK_HEIGHT, row_top
from videocutter.main_window import MainWindow, format_export_progress, format_export_result
from videocutter.output_settings_dialog import OutputSettingsDialog
from videocutter.media import MEDIA_MIME
from videocutter.project import project_output_path
from videocutter.source_panel import remove_mark_rect


ROOT = Path(__file__).resolve().parents[1]


def test_window_has_source_preview_and_timeline(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    splitter = window.centralWidget()
    assert splitter.count() == 2
    assert splitter.widget(0) is window.source_panel
    right = splitter.widget(1)
    assert right.widget(0) is window.preview
    assert right.widget(1) is window.timeline_host
    assert window.source_panel.add_button.text() == "+"
    panel = window.source_panel
    header = panel.layout().itemAt(0).layout()
    margins = panel.layout().contentsMargins()
    assert panel.minimumSizeHint().width() == header.minimumSize().width() + margins.left() + margins.right()
    for button, tooltip in (
        (window.source_panel.open_button, "打开工程"),
        (window.source_panel.save_button, "保存工程"),
        (window.source_panel.settings_button, "设置"),
        (window.source_panel.export_button, "导出"),
    ):
        assert button.text() == ""
        assert button.toolTip() == tooltip
        assert button.icon().isNull() is False
        assert button.size().width() == 32
        assert button.size().height() == 32
    assert window.output_settings.fps_mode == "min"
    assert window.output_settings.bitrate_mode == "min"
    assert window.preview.isVisible()
    assert window.timeline.isVisible()
    assert window.statusBar().isVisible()
    window._export_video()
    assert window.statusBar().currentMessage() == "轨道上没有可以输出的视频"
    window.close()


def test_output_settings_dialog_keeps_the_chosen_rates(qapp):
    window = MainWindow()
    dialog = OutputSettingsDialog(window.output_settings, window)
    assert dialog.fps_min.isChecked()
    assert dialog.bitrate_min.isChecked()
    assert dialog.fps_specified.isChecked() is False
    assert dialog.bitrate_specified.isChecked() is False
    assert dialog.fps_spin.isEnabled() is False
    assert dialog.bitrate_spin.isEnabled() is False
    style = window.styleSheet()
    assert "QRadioButton::indicator:checked" in style
    assert "QSpinBox:disabled" in style
    assert "QDoubleSpinBox:disabled" in style
    dialog.fps_specified.setChecked(True)
    dialog.fps_spin.setValue(24)
    dialog.bitrate_max.setChecked(True)
    assert dialog.fps_spin.isEnabled() is True
    window.output_settings = dialog.result_settings()
    assert window.output_settings.fps_mode == "specified"
    assert window.output_settings.fps_value == pytest.approx(24)
    assert window.output_settings.bitrate_mode == "max"
    window.show()
    dialog.show()
    qapp.processEvents()
    assert dialog.fps_min.font().pixelSize() == 13
    assert dialog.ok_button.font().pixelSize() == 13
    assert dialog.cancel_button.font().pixelSize() == 13
    window.close()


def test_delete_and_backspace_remove_the_selected_media(qapp, tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"clip{index}.avi"
        write_color_video(path, frame_count=4, fps=10, size=(160, 90), red_base=index * 20)
        paths.append(path)
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(path) for path in paths])
    file_list = window.source_panel.file_list
    viewport = file_list.viewport()
    kept_id = file_list.item(2).data(Qt.ItemDataRole.UserRole)
    removed_id = file_list.item(0).data(Qt.ItemDataRole.UserRole)
    assert _drop_media(window, removed_id, row_top(0) + TRACK_HEIGHT / 2)
    QTest.mouseClick(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        file_list.visualItemRect(file_list.item(0)).center(),
    )
    QTest.mouseClick(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        file_list.visualItemRect(file_list.item(1)).center(),
    )
    file_list.setFocus()
    qapp.processEvents()
    QTest.keyClick(file_list, Qt.Key.Key_Delete)
    assert list(window.document.media) == [kept_id]
    assert window.document.all_segments() == []
    assert file_list.count() == 1

    extra = tmp_path / "extra.avi"
    write_color_video(extra, frame_count=4, fps=10, size=(160, 90), red_base=90)
    window.source_panel.add_paths([str(extra)])
    extra_id = _media_id(window, extra)
    QTest.mouseClick(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        file_list.visualItemRect(file_list.item(1)).center(),
    )
    file_list.setFocus()
    qapp.processEvents()
    QTest.keyClick(file_list, Qt.Key.Key_Backspace)
    assert list(window.document.media) == [kept_id]
    assert extra_id not in window.document.media

    assert _drop_media(window, kept_id, row_top(0) + TRACK_HEIGHT / 2)
    window.document.select_segment(window.document.all_segments()[0].segment_id)
    window.timeline.setFocus()
    qapp.processEvents()
    QTest.keyClick(window.timeline, Qt.Key.Key_Delete)
    assert window.document.all_segments() == []
    assert list(window.document.media) == [kept_id]
    window.close()


def test_shift_click_selects_the_inclusive_media_range(qapp, tmp_path):
    paths = []
    for index in range(4):
        path = tmp_path / f"clip{index}.avi"
        write_color_video(path, frame_count=4, fps=10, size=(160, 90), red_base=index * 20)
        paths.append(path)
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(path) for path in paths])
    file_list = window.source_panel.file_list
    viewport = file_list.viewport()

    def click_row(row: int, modifiers) -> None:
        point = file_list.visualItemRect(file_list.item(row)).center()
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, modifiers, point)

    click_row(0, Qt.KeyboardModifier.NoModifier)
    click_row(2, Qt.KeyboardModifier.ShiftModifier)
    selected = [
        row for row in range(file_list.count()) if file_list.item(row).isSelected()
    ]
    assert selected == [0, 1, 2]
    click_row(3, Qt.KeyboardModifier.NoModifier)
    click_row(1, Qt.KeyboardModifier.ShiftModifier)
    selected = [
        row for row in range(file_list.count()) if file_list.item(row).isSelected()
    ]
    assert selected == [1, 2, 3]
    window.close()


def test_rubber_band_selects_the_covered_media(qapp, tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"clip{index}.avi"
        write_color_video(path, frame_count=4, fps=10, size=(160, 90), red_base=index * 20)
        paths.append(path)
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(path) for path in paths])
    file_list = window.source_panel.file_list
    viewport = file_list.viewport()
    assert viewport.height() > file_list.visualItemRect(file_list.item(2)).bottom() + 8
    start = QPoint(12, viewport.height() - 4)
    target = file_list.visualItemRect(file_list.item(1)).center()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(viewport, target)
    assert file_list._rubber_band.isVisible()
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
    assert not file_list._rubber_band.isVisible()
    selected = [
        file_list.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(file_list.count())
        if file_list.item(row).isSelected()
    ]
    assert selected == [
        file_list.item(1).data(Qt.ItemDataRole.UserRole),
        file_list.item(2).data(Qt.ItemDataRole.UserRole),
    ]
    assert "QRubberBand" in window.styleSheet()
    window.close()


def test_remove_mark_deletes_the_media_record(qapp, tmp_path):
    first = tmp_path / "first.avi"
    second = tmp_path / "second.avi"
    write_color_video(first, frame_count=4, fps=10, size=(160, 90))
    write_color_video(second, frame_count=4, fps=10, size=(160, 90), red_base=40)
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(first), str(second)])
    first_id = _media_id(window, first)
    second_id = _media_id(window, second)
    assert _drop_media(window, first_id, row_top(0) + TRACK_HEIGHT / 2)
    file_list = window.source_panel.file_list
    item = file_list.item(0)
    assert item.data(Qt.ItemDataRole.UserRole) == first_id
    mark = remove_mark_rect(file_list.visualItemRect(item))
    QTest.mouseClick(file_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, mark.center())
    assert first_id not in window.document.media
    assert window.document.all_segments() == []
    assert window.document.reference_media_id is None
    assert file_list.count() == 1
    assert file_list.item(0).data(Qt.ItemDataRole.UserRole) == second_id
    window.close()


def test_drop_file_drag_to_timeline_and_show_the_frame(qapp, tmp_path):
    path = tmp_path / "colors.avi"
    write_color_video(path, frame_count=8, fps=10)
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()

    file_mime = QMimeData()
    file_mime.setUrls([QUrl.fromLocalFile(str(path))])
    file_drop = QDropEvent(
        QPointF(20, 20),
        Qt.DropAction.CopyAction,
        file_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    handled = window.source_panel.file_list.eventFilter(
        window.source_panel.file_list.viewport(),
        file_drop,
    )
    assert handled
    assert len(window.document.media) == 1
    media_id = next(iter(window.document.media))

    clip_mime = QMimeData()
    clip_mime.setData(MEDIA_MIME, media_id.encode("utf-8"))
    clip_drop = QDropEvent(
        QPointF(0, row_top(0) + TRACK_HEIGHT / 2),
        Qt.DropAction.CopyAction,
        clip_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert window.timeline.event(clip_drop)
    assert len(window.document.all_segments()) == 1
    assert window.document.all_segments()[0].timeline_start == pytest.approx(0)

    window.document.set_playhead(0.3)
    window.refresh_views()
    pixmap = window.preview.frame_pixmap()
    assert pixmap is not None
    color = pixmap.toImage().pixelColor(0, 0)
    assert color.red() == pytest.approx(60, abs=12)
    assert color.green() == pytest.approx(40, abs=12)
    assert color.blue() == pytest.approx(20, abs=12)

    window.document.set_playhead(0.4)
    window.document.select_segment(window.document.all_segments()[0].segment_id)
    window.activateWindow()
    window.timeline.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    assert window.timeline.hasFocus()
    QApplication.sendEvent(
        window.timeline,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_S, Qt.KeyboardModifier.NoModifier),
    )
    assert len(window.document.tracks[0]) == 2
    window.close()


def test_different_frame_size_is_reported_on_the_status_bar(qapp, tmp_path):
    first_path = tmp_path / "first.avi"
    second_path = tmp_path / "second.avi"
    write_color_video(first_path, frame_count=4, fps=10, size=(160, 90))
    write_color_video(second_path, frame_count=4, fps=10, size=(80, 60))
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(first_path), str(second_path)])
    first_id = _media_id(window, first_path)
    second_id = _media_id(window, second_path)
    assert _drop_media(window, first_id, row_top(0) + TRACK_HEIGHT / 2)
    assert len(window.document.all_segments()) == 1
    assert window.document.reference_media().width == 160
    assert window.document.reference_media().height == 90
    dropped = _drop_media(window, second_id, row_top(1) + TRACK_HEIGHT / 2)
    assert dropped is False
    assert window.statusBar().currentMessage() == "无法放入轨道：素材尺寸为 80×60，轨道输出尺寸为 160×90"
    assert len(window.document.all_segments()) == 1
    window.close()


def test_export_status_shows_progress_and_elapsed_time(qapp, tmp_path):
    path = tmp_path / "clip.avi"
    write_color_video(path, frame_count=4, fps=10, size=(160, 90))
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(path)])
    media_id = _media_id(window, path)
    assert _drop_media(window, media_id, row_top(0) + TRACK_HEIGHT / 2)
    output = tmp_path / "exported.avi"
    window._export_to_path(str(output))
    assert output.is_file()
    assert window.export_written == 4
    assert window.export_total == 4
    worked_text, estimated_text = window.export_progress_message.split("，", 1)[1].split("/")
    assert window.export_progress_message.startswith("正在输出视频：4/4（100%），")
    assert worked_text == estimated_text
    assert len(worked_text.split(":")) == 3
    assert window.source_panel.isEnabled()
    assert window.timeline.isEnabled()
    message = window.statusBar().currentMessage()
    prefix = f"已输出视频：{output}，用时 "
    assert message.startswith(prefix)
    assert message.endswith(" 秒")
    elapsed = float(message[len(prefix) : -len(" 秒")])
    assert elapsed >= 0
    assert format_export_progress(0, 4, 0.0, None) == "正在输出视频：0/4（0%），00:00:00/—"
    assert format_export_progress(1, 4, 0.5, 2.0) == "正在输出视频：1/4（25%），00:00:01/00:00:02"
    assert format_export_progress(1, 4, 3661.2, 7322.6) == "正在输出视频：1/4（25%），01:01:01/02:02:03"
    assert format_export_result(str(output), 1.2) == f"已输出视频：{output}，用时 1.20 秒"
    window._export_started = time.perf_counter() - 1.0
    window._report_export_progress(1, 4)
    shown = window.statusBar().currentMessage()
    assert shown.startswith("正在输出视频：1/4（25%），")
    worked = _clock_seconds(shown.split("，", 1)[1].split("/")[0])
    estimated = _clock_seconds(shown.split("，", 1)[1].split("/")[1])
    assert worked >= 1
    assert estimated == pytest.approx(worked * 4, abs=2)
    window.close()


def test_stop_button_cancels_the_export_and_keeps_the_window(qapp, tmp_path):
    path = tmp_path / "clip.avi"
    write_color_video(path, frame_count=8, fps=10, size=(160, 90))
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(path)])
    media_id = _media_id(window, path)
    assert _drop_media(window, media_id, row_top(0) + TRACK_HEIGHT / 2)
    output = tmp_path / "exported.avi"

    def press_stop() -> None:
        button = window.source_panel.export_button
        assert button.toolTip() == "终止导出"
        assert button.isEnabled()
        assert window.source_panel.add_button.isEnabled() is False
        assert window.source_panel.open_button.isEnabled() is False
        assert window.source_panel.save_button.isEnabled() is False
        assert window.source_panel.settings_button.isEnabled() is False
        assert window.source_panel.file_list.isEnabled() is False
        assert window.preview.isEnabled() is False
        assert window.timeline.isEnabled() is False
        button.click()

    QTimer.singleShot(0, press_stop)
    window._export_to_path(str(output))
    assert not output.exists()
    assert window.isVisible()
    assert window.source_panel.export_button.toolTip() == "导出"
    assert window.source_panel.export_button.isEnabled()
    assert window.source_panel.add_button.isEnabled()
    assert window.preview.isEnabled()
    assert window.timeline.isEnabled()
    assert window.statusBar().currentMessage() == "已终止导出"
    window.close()


def test_closing_the_window_stops_the_export(qapp, tmp_path):
    path = tmp_path / "clip.avi"
    write_color_video(path, frame_count=8, fps=10, size=(160, 90))
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(path)])
    media_id = _media_id(window, path)
    assert _drop_media(window, media_id, row_top(0) + TRACK_HEIGHT / 2)
    output = tmp_path / "exported.avi"
    QTimer.singleShot(0, window.close)
    window._export_to_path(str(output))
    assert window.export_written == 0
    assert window.export_total == 8
    assert not output.exists()
    assert not window.isVisible()
    assert "用时" not in window.statusBar().currentMessage()
    assert window.source_panel.isEnabled()


def _clock_seconds(text: str) -> int:
    hours, minutes, secs = text.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(secs)


def _media_id(window: MainWindow, path: Path) -> str:
    resolved = str(path.resolve())
    for item in window.document.media.values():
        if item.path == resolved:
            return item.media_id
    raise RuntimeError(f"media was not added: {path}")


def _drop_media(window: MainWindow, media_id: str, y: float) -> bool:
    mime = QMimeData()
    mime.setData(MEDIA_MIME, media_id.encode("utf-8"))
    event = QDropEvent(
        QPointF(0, y),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.timeline.event(event)
    return event.isAccepted()


def test_save_and_open_project_restores_the_timeline(qapp, tmp_path):
    path = tmp_path / "clip.avi"
    other = tmp_path / "other.avi"
    write_color_video(path, frame_count=8, fps=10, size=(160, 90))
    write_color_video(other, frame_count=4, fps=10, size=(160, 90), red_base=80)
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    qapp.processEvents()
    window.source_panel.add_paths([str(path), str(other)])
    media_id = _media_id(window, path)
    assert _drop_media(window, media_id, row_top(0) + TRACK_HEIGHT / 2)
    window.document.set_playhead(0.3)
    window.document.select_segment(window.document.all_segments()[0].segment_id)
    window.document.split_selected()
    window.timeline.view_origin = 12
    destination = tmp_path / "edit.mp4"
    window._save_project_to_path(project_output_path(str(destination)))
    stored = tmp_path / "edit.vcproj"
    assert stored.is_file()
    assert window.statusBar().currentMessage() == f"已保存工程：{stored}"
    window.document.delete_segment(window.document.tracks[0][0].segment_id)
    window.document.delete_segment(window.document.tracks[0][0].segment_id)
    assert window.document.all_segments() == []
    window._open_project_from_path(str(stored))
    assert window.statusBar().currentMessage() == f"已打开工程：{stored}"
    assert window.timeline.view_origin == 0
    assert window.source_panel.file_list.count() == 1
    assert window.source_panel.file_list.item(0).data(Qt.ItemDataRole.UserRole) == _media_id(window, path)
    assert len(window.document.tracks) == 1
    left, right = window.document.tracks[0]
    assert left.duration == pytest.approx(0.3)
    assert right.timeline_start == pytest.approx(0.3)
    assert right.source_in == pytest.approx(0.3)
    assert window.document.reference_media().path == str(path.resolve())
    window.document.set_playhead(0.1)
    window.refresh_views()
    assert window.preview.frame_pixmap() is not None
    window.close()


def test_process_starts():
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    process = subprocess.Popen(
        [sys.executable, "-m", "videocutter"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    time.sleep(2)
    code = process.poll()
    if code is None:
        process.terminate()
        process.wait(timeout=5)
        return
    stdout, stderr = process.communicate()
    raise RuntimeError(
        stderr.decode("utf-8", errors="replace")
        or stdout.decode("utf-8", errors="replace")
        or f"process exited {code}"
    )
