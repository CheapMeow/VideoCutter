import cv2
import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest

from videocutter.main_window import MainWindow
from videocutter.model import TimelineDocument
from tests.support import write_color_video
from tests.test_playback import add_clip, wait_until


class VisibilityEvents(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.events = []
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Show):
            self.events.append(event.type())
        return False


@pytest.fixture(params=[(160, 90), (2560, 1440)])
def playing_preview(qapp, tmp_path, request):
    path = tmp_path / "pause.avi"
    write_color_video(path, 12, 5, size=request.param)
    window = MainWindow()
    add_clip(window, path)
    window.show()
    qapp.processEvents()
    window._toggle_playback()
    wait_until(lambda: window.document.playhead > 0.4)
    wait_until(lambda: window.preview.video_widget.videoSink().videoFrame().isValid())
    yield window
    window.close()


def test_pause_keeps_the_displayed_video_surface_and_frame(playing_preview):
    window = playing_preview
    preview = window.preview
    video = preview.video_widget
    events = VisibilityEvents(video)
    capture = next(iter(preview._captures.values()))
    position = capture.get(cv2.CAP_PROP_POS_FRAMES)
    before = video.videoSink().videoFrame().toImage()
    playhead = window.document.playhead
    window.pause_playback()
    assert video.isVisible()
    assert events.events == []
    assert capture.get(cv2.CAP_PROP_POS_FRAMES) == position
    assert preview.frame_pixmap().toImage() == before
    assert window._playback.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    QTest.qWait(150)
    window.refresh_views()
    window.pause_playback()
    window.resize(window.width() + 100, window.height() + 50)
    QTest.qWait(50)
    assert video.isVisible()
    assert events.events == []
    assert video.videoSink().videoFrame().toImage() == before
    assert preview.frame_pixmap().toImage() == before
    assert capture.get(cv2.CAP_PROP_POS_FRAMES) == position
    assert window.document.playhead == playhead
    assert not window._play_timer.isActive()


def test_paused_preview_scrubs_to_an_exact_frame(playing_preview):
    window = playing_preview
    window.pause_playback()
    window.document.set_playhead(1.2)
    window.refresh_views()
    assert not window.preview.video_widget.isVisible()
    image = window.preview.frame_pixmap().toImage()
    assert image.pixelColor(0, 0).red() == pytest.approx(120, abs=12)
    window.document.set_playhead(3.0)
    window.refresh_views()
    assert not window.preview.video_widget.isVisible()
    assert window.preview.frame_pixmap() is None


def test_repeated_pause_resume_preserves_the_video_output(playing_preview):
    window = playing_preview
    video = window.preview.video_widget
    capture = next(iter(window.preview._captures.values()))
    position = capture.get(cv2.CAP_PROP_POS_FRAMES)
    for _ in range(3):
        window.pause_playback()
        assert video.isVisible()
        previous_time = video.videoSink().videoFrame().startTime()
        assert capture.get(cv2.CAP_PROP_POS_FRAMES) == position
        window._toggle_playback()
        wait_until(lambda: video.videoSink().videoFrame().startTime() > previous_time)
        assert window._playback.player.videoOutput() is video
    window.pause_playback()
    assert video.isVisible()


def test_paused_frame_clears_when_its_segment_is_removed(playing_preview):
    window = playing_preview
    window.pause_playback()
    segment = window.document.all_segments()[0]
    window.document.delete_segment(segment.segment_id)
    window.refresh_views()
    assert not window.preview.video_widget.isVisible()
    assert window.preview.frame_pixmap() is None


def test_paused_frame_clears_when_project_is_replaced(playing_preview):
    window = playing_preview
    window.pause_playback()
    window._replace_document(TimelineDocument())
    assert not window.preview.video_widget.isVisible()
    assert window.preview.frame_pixmap() is None
    assert window._playback.player.source().isEmpty()


def test_pause_in_a_gap_and_before_first_frame_has_no_stale_image(qapp, tmp_path):
    path = tmp_path / "gap.avi"
    write_color_video(path, 8, 5)
    window = MainWindow()
    add_clip(window, path, start=0.5)
    window.show()
    qapp.processEvents()
    try:
        window._toggle_playback()
        window.pause_playback()
        assert not window.preview.video_widget.isVisible()
        assert window.preview.frame_pixmap() is None
        window.document.set_playhead(0.7)
        window._toggle_playback()
        window.pause_playback()
        assert not window.is_playing()
        assert window.preview.frame_pixmap() is not None
        assert window._playback.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    finally:
        window.close()
