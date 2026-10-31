from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from videocutter.model import TimelineDocument

if TYPE_CHECKING:
    import cv2


class PreviewWidget(QWidget):
    def __init__(self, document: TimelineDocument) -> None:
        super().__init__()
        self.document = document
        self._captures: dict[str, "cv2.VideoCapture"] = {}
        self._pixmap: QPixmap | None = None
        self._frame_key: tuple[str, int] | None = None
        self._paused_source: tuple[str, float] | None = None
        self.video_widget = None
        self._streaming = False
        self.setMinimumHeight(180)

    def attach_player(self, player) -> None:
        if self.video_widget is None:
            from PySide6.QtMultimediaWidgets import QVideoWidget

            self.video_widget = QVideoWidget(self)
            self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            self.video_widget.setGeometry(self.rect().adjusted(12, 12, -12, -12))
            self.video_widget.hide()
        player.setVideoOutput(self.video_widget)

    def set_streaming(self, streaming: bool) -> None:
        if self._streaming == streaming:
            return
        self._streaming = streaming
        self._frame_key = None
        self._pixmap = None
        self._paused_source = None
        located = self.document.source_time_at_playhead()
        if (
            not streaming
            and located is not None
            and self.video_widget is not None
            and not self.video_widget.isHidden()
            and self.video_widget.videoSink().videoFrame().isValid()
        ):
            # QMediaPlayer 暂停后保留当前视频表面和帧，直到播放头或素材发生变化。
            media, source_time = located
            self._paused_source = (media.media_id, source_time)
            return
        if self.video_widget is not None:
            self.video_widget.setVisible(streaming and located is not None)
        self.update()

    def frame_pixmap(self) -> QPixmap | None:
        if (
            self._streaming or self._paused_source is not None
        ) and self.document.top_segment_at_playhead() is not None:
            frame = self.video_widget.videoSink().videoFrame()
            if frame.isValid():
                return QPixmap.fromImage(frame.toImage())
            return None
        return self._pixmap

    def refresh(self) -> None:
        located = self.document.source_time_at_playhead()
        if self._streaming:
            # 连续播放由 Qt 在解码线程中处理，GUI 线程只负责部件的显示状态。
            self.video_widget.setVisible(located is not None)
            return
        if located is None:
            self._pixmap = None
            self._frame_key = None
            self._paused_source = None
            if self.video_widget is not None:
                self.video_widget.hide()
            self.update()
            return
        media, source_time = located
        if self._paused_source == (media.media_id, source_time):
            return
        frame_index = int(source_time * media.fps)
        if frame_index == media.frame_count:
            frame_index = media.frame_count - 1
        key = (media.media_id, frame_index)
        if key == self._frame_key and self._pixmap is not None:
            return
        # cv2 启动时不加载，窗口显示后由 videocutter.app 在后台预先导入。
        from videocutter.capture import frame_to_pixmap, read_frame

        frame = read_frame(self._capture(media.path), media.fps, media.frame_count, source_time)
        self._pixmap = frame_to_pixmap(frame)
        self._frame_key = key
        self._paused_source = None
        if self.video_widget is not None:
            self.video_widget.hide()
        self.update()

    def release(self) -> None:
        self._streaming = False
        self._paused_source = None
        if self.video_widget is not None:
            self.video_widget.hide()
        for capture in self._captures.values():
            capture.release()
        self._captures.clear()
        self._pixmap = None
        self._frame_key = None
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.video_widget is not None:
            self.video_widget.setGeometry(self.rect().adjusted(12, 12, -12, -12))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111111"))
        if self._pixmap is None:
            if not self._streaming or self.document.top_segment_at_playhead() is None:
                painter.setPen(QColor("#9a9a9a"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "无画面")
            return
        target = self.rect().adjusted(12, 12, -12, -12)
        if target.width() <= 0 or target.height() <= 0:
            return
        size = self._pixmap.size().scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target.setSize(size)
        target.moveCenter(self.rect().center())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self._pixmap)

    def _capture(self, path: str) -> "cv2.VideoCapture":
        capture = self._captures.get(path)
        if capture is None:
            from videocutter.capture import open_capture

            capture = open_capture(path)
            self._captures[path] = capture
        return capture
