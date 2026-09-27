import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QDropEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

from tests.support import write_color_video
from videocutter.geometry import TRACK_HEIGHT, row_top
from videocutter.main_window import MainWindow, format_export_progress, format_export_result
from videocutter.media import MEDIA_MIME


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
    assert window.source_panel.export_button.text() == "导出"
    assert window.preview.isVisible()
    assert window.timeline.isVisible()
    assert window.statusBar().isVisible()
    window._export_video()
    assert window.statusBar().currentMessage() == "轨道上没有可以输出的视频"
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
