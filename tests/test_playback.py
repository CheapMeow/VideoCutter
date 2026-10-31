import time

import numpy as np
import pytest
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QMediaPlayer
from PySide6.QtTest import QTest

from videocutter.main_window import MainWindow
from videocutter.model import TimelineDocument
from videocutter.playback import TimelinePlayback
from tests.support import write_color_video, write_tone_video


def wait_until(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "media playback timed out"
        QTest.qWait(10)


def add_clip(window, path, start=0.0, track=0):
    window.source_panel.add_paths([str(path)])
    media_id = next(reversed(window.document.media))
    return window.document.place_new_segment(media_id, start, track, True, 0)


def test_playback_decodes_audible_samples_and_connects_output(qapp, tmp_path):
    path = tmp_path / "tone.mp4"
    write_tone_video(path, 90, 30)
    window = MainWindow()
    segment = add_clip(window, path)
    segment.source_in = 0.5
    segment.source_out = 2.5
    window.document.set_playhead(0.2)
    playback = TimelinePlayback(window)
    audio_format = QAudioFormat()
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Float)
    audio_format.setSampleRate(48000)
    audio_format.setChannelCount(2)
    buffers = QAudioBufferOutput(audio_format, playback)
    playback.player.setAudioBufferOutput(buffers)
    levels = []
    timestamps = []

    def received(buffer):
        if buffer.isValid():
            samples = np.frombuffer(buffer.constData(), dtype=np.float32)
            levels.append(float(np.max(np.abs(samples))))
            timestamps.append(buffer.startTime() / 1_000_000)

    buffers.audioBufferReceived.connect(received)
    errors = []
    playback.failed.connect(errors.append)
    try:
        playback.sync(window.document)
        wait_until(lambda: len(levels) >= 4 or errors)
        assert not errors
        assert playback.player.hasAudio()
        assert playback.player.audioOutput() is playback.audio_output
        assert not playback.audio_output.device().isNull()
        assert not playback.audio_output.isMuted()
        assert playback.audio_output.volume() == pytest.approx(1.0)
        assert max(levels) > 0.1
        assert timestamps[0] >= 0.65
        assert playback.timeline_position(0.0) >= 0.2
        playback.pause()
        assert playback.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
        position = playback.player.position()
        QTest.qWait(150)
        assert playback.player.position() == position
        window.document.set_playhead(0.8)
        playback.sync(window.document)
        wait_until(lambda: playback.player.position() >= 1300)
        playback.release()
        assert playback.player.source().isEmpty()
    finally:
        playback.release()
        window.close()


def test_audio_follows_top_track_trim_gap_and_source_switch(qapp, tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    write_tone_video(first, 90, 30, frequency_hz=440)
    write_tone_video(second, 90, 30, frequency_hz=880)
    window = MainWindow()
    bottom = add_clip(window, first, start=0.0)
    top = add_clip(window, second, start=0.4)
    top.source_in = 1.0
    top.source_out = 2.0
    playback = TimelinePlayback(window)
    try:
        window.document.set_playhead(0.6)
        playback.sync(window.document)
        wait_until(lambda: playback.player.position() >= 1200)
        assert playback.player.source().toLocalFile() == second.as_posix()
        window.document.set_playhead(1.5)
        playback.sync(window.document)
        wait_until(lambda: playback.player.position() >= 1500)
        assert playback.player.source().toLocalFile() == first.as_posix()
        window.document.set_playhead(bottom.timeline_end + 0.5)
        playback.sync(window.document)
        assert playback.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        assert playback.timeline_position(3.7) == 3.7
    finally:
        playback.release()
        window.close()


def test_space_playback_advances_and_stops_audio_at_timeline_end(qapp, tmp_path):
    path = tmp_path / "short.mp4"
    write_tone_video(path, 30, 30)
    window = MainWindow()
    segment = add_clip(window, path)
    segment.source_in = 0.2
    segment.source_out = 0.7
    try:
        window._toggle_playback()
        wait_until(lambda: not window.is_playing())
        assert window.document.playhead == pytest.approx(0.5)
        assert window._playback.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        window._toggle_playback()
        wait_until(lambda: window.document.playhead > 0.1)
        window._replace_document(TimelineDocument())
        assert not window.is_playing()
        assert window._playback.player.source().isEmpty()
    finally:
        window.close()


def test_video_without_audio_still_plays(qapp, tmp_path):
    path = tmp_path / "silent.avi"
    write_color_video(path, 8, 10)
    window = MainWindow()
    add_clip(window, path)
    try:
        window._toggle_playback()
        wait_until(lambda: not window.is_playing())
        assert window.document.playhead == pytest.approx(0.8)
        assert not window._playback.player.hasAudio()
        assert window._playback.player.error() == QMediaPlayer.Error.NoError
    finally:
        window.close()
