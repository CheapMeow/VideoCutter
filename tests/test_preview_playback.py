import time

import cv2
import pytest
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest

from videocutter.main_window import MainWindow
from tests.support import write_tone_video
from tests.test_playback import add_clip, wait_until


def test_native_preview_delivers_high_fps_without_gui_frame_seeks(qapp, tmp_path):
    path = tmp_path / "sixty-fps.mp4"
    write_tone_video(path, 240, 60)
    window = MainWindow()
    add_clip(window, path)
    window.show()
    qapp.processEvents()
    capture = window.preview._captures[str(path.resolve())]
    capture_position = capture.get(cv2.CAP_PROP_POS_FRAMES)
    frames = []
    try:
        window._toggle_playback()

        def received(frame):
            if frame.isValid():
                frames.append((time.monotonic(), frame.startTime()))

        window.preview.video_widget.videoSink().videoFrameChanged.connect(received)
        wait_until(lambda: len(frames) >= 90)
        rate = (len(frames[10:]) - 1) / (frames[-1][0] - frames[10][0])
        assert rate > 40
        assert frames[-1][1] > frames[0][1]
        assert capture.get(cv2.CAP_PROP_POS_FRAMES) == capture_position
        assert window._playback.player.videoOutput() is window.preview.video_widget
        assert window.preview.video_widget.isVisible()
        assert window.preview.frame_pixmap() is not None
        assert window._playback.player.error() == QMediaPlayer.Error.NoError
        window.pause_playback()
        assert window.preview.video_widget.isVisible()
        assert window.preview.frame_pixmap() is not None
        assert capture.get(cv2.CAP_PROP_POS_FRAMES) == capture_position
    finally:
        window.close()


def test_native_preview_hides_gaps_and_restarts_at_a_trimmed_segment(qapp, tmp_path):
    path = tmp_path / "clips.mp4"
    write_tone_video(path, 90, 30)
    window = MainWindow()
    segment = add_clip(window, path, start=0.2)
    segment.source_in = 1.0
    segment.source_out = 1.6
    window.show()
    qapp.processEvents()
    try:
        window._toggle_playback()
        assert not window.preview.video_widget.isVisible()
        assert window.preview.frame_pixmap() is None
        wait_until(lambda: window.document.playhead > 0.3)
        assert window.preview.video_widget.isVisible()
        wait_until(lambda: window.preview.video_widget.videoSink().videoFrame().isValid())
        frame_time = window.preview.video_widget.videoSink().videoFrame().startTime() / 1_000_000
        assert frame_time >= 0.95
        wait_until(lambda: not window.is_playing())
        assert window.document.playhead == pytest.approx(0.8)
        assert not window.preview.video_widget.isVisible()
        assert window.preview.frame_pixmap() is None
        window.document.set_playhead(0.35)
        window.refresh_views()
        assert window.preview.frame_pixmap() is not None
        window._toggle_playback()
        QTest.qWait(50)
        window.close()
        assert window._playback.player.source().isEmpty()
    finally:
        window.close()
