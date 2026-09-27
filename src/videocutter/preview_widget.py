import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from videocutter.media import open_capture, read_frame
from videocutter.model import TimelineDocument


def frame_to_pixmap(frame: np.ndarray) -> QPixmap:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise RuntimeError(f"expected a BGR frame, got shape {frame.shape}")
    rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    height, width, channels = rgb.shape
    image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())


class PreviewWidget(QWidget):
    def __init__(self, document: TimelineDocument) -> None:
        super().__init__()
        self.document = document
        self._captures: dict[str, cv2.VideoCapture] = {}
        self._pixmap: QPixmap | None = None
        self._frame_key: tuple[str, int] | None = None
        self.setMinimumHeight(180)

    def frame_pixmap(self) -> QPixmap | None:
        return self._pixmap

    def refresh(self) -> None:
        located = self.document.source_time_at_playhead()
        if located is None:
            self._pixmap = None
            self._frame_key = None
            self.update()
            return
        media, source_time = located
        frame_index = int(source_time * media.fps)
        if frame_index == media.frame_count:
            frame_index = media.frame_count - 1
        key = (media.media_id, frame_index)
        if key == self._frame_key and self._pixmap is not None:
            return
        frame = read_frame(self._capture(media.path), media.fps, media.frame_count, source_time)
        self._pixmap = frame_to_pixmap(frame)
        self._frame_key = key
        self.update()

    def release(self) -> None:
        for capture in self._captures.values():
            capture.release()
        self._captures.clear()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111111"))
        if self._pixmap is None:
            painter.setPen(QColor("#9a9a9a"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "无画面")
            return
        target = self.rect().adjusted(12, 12, -12, -12)
        if target.width() <= 0 or target.height() <= 0:
            return
        scaled = self._pixmap.scaled(
            target.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = target.x() + (target.width() - scaled.width()) // 2
        y = target.y() + (target.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    def _capture(self, path: str) -> cv2.VideoCapture:
        capture = self._captures.get(path)
        if capture is None:
            capture = open_capture(path)
            self._captures[path] = capture
        return capture
