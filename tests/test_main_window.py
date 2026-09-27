import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

from tests.support import write_color_video
from videocutter.geometry import TRACK_HEIGHT, row_top
from videocutter.main_window import MainWindow
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
    assert window.preview.isVisible()
    assert window.timeline.isVisible()
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
