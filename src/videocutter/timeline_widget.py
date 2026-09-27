from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QScrollArea, QWidget

from videocutter.geometry import (
    RULER_HEIGHT,
    TRACK_GAP,
    TRACK_HEIGHT,
    row_top,
    snap_threshold_seconds,
    track_stride,
    track_target_at_y,
)
from videocutter.media import MEDIA_MIME
from videocutter.model import Segment, TimelineDocument


SEGMENT_COLORS = (
    QColor("#3d7ea6"),
    QColor("#3f8f6b"),
    QColor("#a67c3d"),
    QColor("#7a5ea7"),
    QColor("#a64d5d"),
    QColor("#3d8f8f"),
)


def segment_color(media_id: str) -> QColor:
    return SEGMENT_COLORS[int(media_id[:6], 16) % len(SEGMENT_COLORS)]


def tick_step(pixels_per_second: float) -> float:
    for step in (0.1, 0.2, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600, 86400):
        if step * pixels_per_second >= 80:
            return float(step)
    return 86400.0


def format_tick(seconds: float) -> str:
    if seconds < 60:
        if abs(seconds - round(seconds)) < 1e-6:
            return f"{int(round(seconds))}s"
        return f"{seconds:.1f}s"
    if seconds < 3600:
        minutes = int(seconds // 60)
        remain = seconds - minutes * 60
        return f"{minutes}:{remain:04.1f}"
    hours = int(seconds // 3600)
    remain = seconds - hours * 3600
    minutes = int(remain // 60)
    secs = remain - minutes * 60
    return f"{hours}:{minutes:02d}:{secs:04.1f}"


class TimelineWidget(QWidget):
    EDGE_SCROLL_GAIN = 0.35
    MIN_PIXELS_PER_SECOND = 8.0
    MAX_PIXELS_PER_SECOND = 4000.0
    ZOOM_FACTOR = 1.15
    # 缩到最远时，可见时间长度至少覆盖最晚一帧时间的这个倍数。
    ZOOM_OUT_SPAN_MULTIPLIER = 8.0

    def __init__(self, document: TimelineDocument, on_changed) -> None:
        super().__init__()
        self.document = document
        self._on_changed = on_changed
        self.view_origin = 0.0
        self.pixels_per_second = 100.0
        self.setMinimumHeight(RULER_HEIGHT + TRACK_HEIGHT)
        self.setMinimumWidth(240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(16)
        self._scroll_timer.timeout.connect(self._on_edge_scroll)
        self._mode: str | None = None
        self._moved = False
        self._press_pos = QPointF()
        self._press_view = 0.0
        self._grab_offset = 0.0
        self._last_pos: QPointF | None = None
        self._last_track_index: int | None = None
        self._pressed_segment_id: str | None = None

    def preferred_height(self) -> int:
        count = max(1, len(self.document.tracks))
        return RULER_HEIGHT + count * track_stride() + TRACK_GAP

    def time_at_x(self, x: float) -> float:
        return self.view_origin + x / self.pixels_per_second

    def x_at_time(self, time_sec: float) -> float:
        return (time_sec - self.view_origin) * self.pixels_per_second

    def minimum_pixels_per_second(self) -> float:
        width = self.width()
        if width <= 0:
            raise RuntimeError(f"timeline width must be positive, got {width}")
        latest = self.document.latest_material_time()
        if latest <= 0:
            return self.MIN_PIXELS_PER_SECOND
        content_span = latest * self.ZOOM_OUT_SPAN_MULTIPLIER
        content_scale = width / content_span
        return min(self.MIN_PIXELS_PER_SECOND, content_scale)

    def zoom_at(self, x: float, factor: float) -> None:
        if factor <= 0:
            raise ValueError(f"zoom factor must be positive, got {factor}")
        anchor = self.time_at_x(x)
        new_scale = self.pixels_per_second * factor
        new_scale = min(self.MAX_PIXELS_PER_SECOND, max(self.minimum_pixels_per_second(), new_scale))
        self.pixels_per_second = new_scale
        self.view_origin = max(0.0, anchor - x / new_scale)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#161616"))
        lane_count = max(1, len(self.document.tracks))
        for index in range(lane_count):
            top = row_top(index)
            color = QColor("#2b2b2b") if index % 2 == 0 else QColor("#242424")
            painter.fillRect(QRectF(0, top, self.width(), TRACK_HEIGHT), color)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for track_index, track in enumerate(self.document.tracks):
            for segment in track:
                self._paint_segment(painter, track_index, segment)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(QRectF(0, 0, self.width(), RULER_HEIGHT), QColor("#121212"))
        self._paint_ruler(painter)
        if not self.document.all_segments():
            painter.setPen(QColor("#8d8d8d"))
            area = QRectF(0, RULER_HEIGHT, self.width(), self.height() - RULER_HEIGHT)
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "把素材拖到这里")
        playhead_x = round(self.x_at_time(self.document.playhead))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(playhead_x, 0, playhead_x, self.height())

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        factor = self.ZOOM_FACTOR if delta > 0 else 1 / self.ZOOM_FACTOR
        self.zoom_at(event.position().x(), factor)
        if self._mode == "segment" and self._moved and self._last_pos is not None:
            self._apply_segment_drag(self._last_pos)
        event.accept()
        self._emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        pos = event.position()
        segment = self._segment_at(pos)
        self._press_pos = pos
        self._press_view = self.view_origin
        self._moved = False
        self._last_pos = pos
        self._last_track_index = None
        if pos.y() < RULER_HEIGHT:
            self._mode = "playhead"
            self._pressed_segment_id = None
            self.document.select_segment(None)
            self._scrub_playhead(pos.x())
        elif segment is None:
            self._mode = "empty"
            self._pressed_segment_id = None
        else:
            self._mode = "segment"
            self._pressed_segment_id = segment.segment_id
            self._grab_offset = self.time_at_x(pos.x()) - segment.timeline_start
            self.document.begin_segment_drag(segment.segment_id)
        self.grabMouse()
        if self._mode == "playhead":
            self._emit()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._mode is None:
            return
        pos = event.position()
        if self._mode == "playhead":
            self._scrub_playhead(pos.x())
            self._emit()
            return
        if self._pointer_moved(pos):
            self._moved = True
        if not self._moved:
            return
        self._last_pos = pos
        if self._mode == "empty":
            delta = pos.x() - self._press_pos.x()
            self.view_origin = max(0.0, self._press_view - delta / self.pixels_per_second)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._emit()
            return
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._apply_segment_drag(pos)
        self._update_edge_scroll(pos.x())
        self._emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._mode is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._scroll_timer.stop()
        pos = event.position()
        if self._mode == "playhead":
            self._scrub_playhead(pos.x())
        elif self._mode == "segment":
            if self._moved:
                self._last_pos = pos
                self._apply_segment_drag(pos)
                self.document.end_segment_drag()
            else:
                self.document.cancel_segment_drag()
                self.document.set_playhead(max(0.0, self.time_at_x(pos.x())))
            self.document.select_segment(self._pressed_segment_id)
        elif self._mode == "empty" and not self._moved:
            self.document.set_playhead(max(0.0, self.time_at_x(pos.x())))
            self.document.select_segment(None)
        self._mode = None
        self._moved = False
        self._last_pos = None
        self._last_track_index = None
        self.releaseMouse()
        self.unsetCursor()
        self._emit()

    def keyPressEvent(self, event) -> None:
        if self._plain_key(event, Qt.Key.Key_S):
            self.document.split_at_playhead()
            event.accept()
            self._emit()
            return
        if self._plain_key(event, Qt.Key.Key_Delete) or self._plain_key(event, Qt.Key.Key_Backspace):
            if self.document.selected_segment_id is not None:
                self.document.delete_segment(self.document.selected_segment_id)
            event.accept()
            self._emit()
            return
        super().keyPressEvent(event)

    def _plain_key(self, event, key) -> bool:
        if event.key() != key or event.isAutoRepeat() or not self.hasFocus():
            return False
        blocked = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        return not (event.modifiers() & blocked)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._mode is None and event.mimeData().hasFormat(MEDIA_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._mode is None and event.mimeData().hasFormat(MEDIA_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if self._mode is not None or not event.mimeData().hasFormat(MEDIA_MIME):
            event.ignore()
            return
        media_id = bytes(event.mimeData().data(MEDIA_MIME)).decode("utf-8")
        position = event.position()
        insert_track, track_index = track_target_at_y(position.y(), len(self.document.tracks))
        self.document.place_new_segment(
            media_id,
            self.time_at_x(position.x()),
            track_index,
            insert_track,
            snap_threshold_seconds(self.pixels_per_second),
        )
        event.acceptProposedAction()
        self._emit()

    def _on_edge_scroll(self) -> None:
        if self._mode != "segment" or not self._moved or self._last_pos is None:
            self._scroll_timer.stop()
            return
        x = self._last_pos.x()
        width = self.width()
        if x < 0:
            overflow = x
        elif x > width:
            overflow = x - width
        else:
            self._scroll_timer.stop()
            return
        if overflow < 0 and self.view_origin <= 0:
            self._apply_segment_drag(self._last_pos)
            self._scroll_timer.stop()
            self._emit()
            return
        self.view_origin = max(
            0.0,
            self.view_origin + overflow * self.EDGE_SCROLL_GAIN / self.pixels_per_second,
        )
        self._apply_segment_drag(self._last_pos)
        self._emit()

    def _apply_segment_drag(self, pos: QPointF) -> None:
        base_count = self.document.drag_base_track_count()
        if base_count is None:
            raise RuntimeError("segment drag is not active")
        insert_track, track_index = track_target_at_y(pos.y(), base_count)
        self.document.update_segment_drag(
            self.time_at_x(pos.x()) - self._grab_offset,
            track_index,
            insert_track,
            snap_threshold_seconds(self.pixels_per_second),
        )
        self._last_track_index = track_index

    def _update_edge_scroll(self, x: float) -> None:
        outside = x < 0 or x > self.width()
        if outside:
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
            return
        self._scroll_timer.stop()

    def _emit(self) -> None:
        self._on_changed()
        if self._mode == "segment" and self._last_track_index is not None:
            self._reveal_track(self._last_track_index)
        self.update()

    def _reveal_track(self, index: int) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        host = parent.parentWidget()
        if not isinstance(host, QScrollArea):
            return
        host.ensureVisible(0, row_top(index) + TRACK_HEIGHT // 2, 0, TRACK_HEIGHT // 2)

    def _segment_at(self, pos: QPointF) -> Segment | None:
        for track_index, track in enumerate(self.document.tracks):
            for segment in track:
                if self._segment_rect(track_index, segment).contains(pos):
                    return segment
        return None

    def _segment_rect(self, track_index: int, segment: Segment) -> QRectF:
        x = self.x_at_time(segment.timeline_start)
        width = segment.duration * self.pixels_per_second
        if width <= 0:
            raise RuntimeError(f"segment width must be positive, got {width}")
        return QRectF(x, row_top(track_index) + 4, width, TRACK_HEIGHT - 8)

    def _paint_segment(self, painter: QPainter, track_index: int, segment: Segment) -> None:
        rect = self._segment_rect(track_index, segment)
        color = segment_color(segment.media_id)
        if segment.segment_id == self.document.selected_segment_id:
            painter.setPen(QPen(QColor("#ffffff"), 2))
        else:
            painter.setPen(QPen(color.lighter(130), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 4, 4)
        if rect.width() < 36:
            return
        media = self.document.media[segment.media_id]
        label = Path(media.path).name
        painter.setPen(QColor("#ffffff"))
        text_rect = rect.adjusted(6, 0, -6, 0)
        elided = QFontMetrics(painter.font()).elidedText(
            label,
            Qt.TextElideMode.ElideRight,
            int(text_rect.width()),
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

    def _paint_ruler(self, painter: QPainter) -> None:
        painter.setPen(QColor("#3a3a3a"))
        painter.drawLine(0, RULER_HEIGHT - 1, self.width(), RULER_HEIGHT - 1)
        step = tick_step(self.pixels_per_second)
        start = int(self.view_origin / step) * step
        end = self.time_at_x(self.width()) + step
        painter.setPen(QColor("#c8c8c8"))
        seconds = start
        while seconds <= end + 1e-9:
            if seconds >= 0:
                x = round(self.x_at_time(seconds))
                painter.drawLine(x, RULER_HEIGHT - 10, x, RULER_HEIGHT - 1)
                painter.drawText(x + 4, 16, format_tick(seconds))
            seconds += step

    def _scrub_playhead(self, x: float) -> None:
        self.document.set_playhead(self.time_at_x(x))

    def _pointer_moved(self, pos: QPointF) -> bool:
        return abs(pos.x() - self._press_pos.x()) + abs(pos.y() - self._press_pos.y()) >= 4


class TimelineHost(QScrollArea):
    def __init__(self, timeline: TimelineWidget) -> None:
        super().__init__()
        self.timeline = timeline
        self.setWidget(timeline)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

    def sync(self) -> None:
        width = self.viewport().width()
        if width <= 0:
            return
        height = max(self.viewport().height(), self.timeline.preferred_height())
        if self.timeline.width() != width or self.timeline.height() != height:
            self.timeline.resize(width, height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.sync()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.timeline.wheelEvent(event)
