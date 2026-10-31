from PySide6.QtCore import QElapsedTimer, QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from videocutter.model import TimelineDocument


class TimelinePlayback(QObject):
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(QMediaDevices.defaultAudioOutput(), self)
        self.audio_output.setVolume(1.0)
        self.player.setAudioOutput(self.audio_output)
        self.player.errorOccurred.connect(self._error)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self._segment_key = None
        self._pending_position: int | None = None
        self._source_position = 0
        self._position_clock = QElapsedTimer()
        self._timeline_offset = 0.0
        self._segment_end = 0.0
        self._running = False

    def sync(self, document: TimelineDocument) -> None:
        segment = document.top_segment_at_playhead()
        if segment is None:
            self.pause()
            return
        media = document.media[segment.media_id]
        key = (
            segment.segment_id, media.path, segment.timeline_start,
            segment.source_in, segment.source_out,
        )
        if self._running and self._segment_key == key:
            return
        url = QUrl.fromLocalFile(media.path)
        source_changed = self.player.source() != url
        self._running = False
        self._pending_position = None
        if source_changed:
            self.player.stop()
        else:
            self.player.pause()
        self._running = True
        self._segment_key = key
        self._timeline_offset = segment.timeline_start - segment.source_in
        self._segment_end = segment.timeline_end
        position = round((document.playhead - self._timeline_offset) * 1000)
        self._source_position = position
        self._position_clock.invalidate()
        self._pending_position = position
        if source_changed:
            self.player.setSource(url)
        elif self.player.mediaStatus() != QMediaPlayer.MediaStatus.LoadingMedia:
            self._start_pending()

    def timeline_position(self, elapsed_position: float) -> float:
        if not self._running:
            return elapsed_position
        if self._pending_position is not None:
            return self._timeline_offset + self._pending_position / 1000.0
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            return self._segment_end
        position = self.player.position()
        if position != self._source_position:
            self._source_position = position
            self._position_clock.start()
        extra = 0
        if (
            self._position_clock.isValid()
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and self.player.mediaStatus() == QMediaPlayer.MediaStatus.BufferedMedia
        ):
            extra = min(100, self._position_clock.elapsed())
        return min(self._segment_end, self._timeline_offset + (position + extra) / 1000.0)

    def pause(self) -> None:
        self._running = False
        self._pending_position = None
        self._segment_key = None
        self._position_clock.invalidate()
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadingMedia:
            self.player.stop()
        else:
            self.player.pause()

    def release(self) -> None:
        self.pause()
        self.player.stop()
        self.player.setSource(QUrl())

    def _start_pending(self) -> None:
        if not self._running or self._pending_position is None:
            return
        position = self._pending_position
        self._pending_position = None
        self.player.setPosition(position)
        self.player.play()
        self._position_clock.start()

    def _media_status_changed(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._start_pending()

    def _error(self, error, message: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            self.pause()
            self.failed.emit(message)
