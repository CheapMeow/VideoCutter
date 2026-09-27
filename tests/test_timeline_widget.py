import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDropEvent, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from videocutter.geometry import TRACK_HEIGHT, row_top
from videocutter.media import MEDIA_MIME
from videocutter.model import MediaItem, TimelineDocument
from videocutter.timeline_widget import TimelineWidget


def media(media_id: str, duration: float) -> MediaItem:
    return MediaItem(
        media_id=media_id,
        path=f"{media_id}.mp4",
        duration_sec=duration,
        fps=10,
        frame_count=int(duration * 10),
        width=16,
        height=16,
    )


def lane_y(index: int = 0) -> int:
    return row_top(index) + TRACK_HEIGHT // 2


def show_timeline(qapp, document: TimelineDocument | None = None) -> TimelineWidget:
    widget = TimelineWidget(document or TimelineDocument(), lambda: None)
    widget.resize(900, 480)
    widget.show()
    qapp.processEvents()
    return widget


def send_mouse(widget: TimelineWidget, kind: str, x: float, y: float) -> None:
    if kind == "press":
        event_type = QEvent.Type.MouseButtonPress
        button = Qt.MouseButton.LeftButton
    elif kind == "move":
        event_type = QEvent.Type.MouseMove
        button = Qt.MouseButton.NoButton
    elif kind == "release":
        event_type = QEvent.Type.MouseButtonRelease
        button = Qt.MouseButton.LeftButton
    else:
        raise ValueError(kind)
    local = QPointF(x, y)
    event = QMouseEvent(
        event_type,
        local,
        local,
        button,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def test_click_empty_seeks_and_click_on_segment_does_not_leave_a_drag(qapp):
    document = TimelineDocument()
    document.add_media(media("a", 2))
    segment = document.place_new_segment("a", 0, 0, True, 0)
    widget = show_timeline(qapp, document)
    send_mouse(widget, "press", 250, 10)
    send_mouse(widget, "release", 250, 10)
    assert document.playhead == pytest.approx(2.5)
    send_mouse(widget, "press", 50, lane_y())
    send_mouse(widget, "release", 50, lane_y())
    assert document.playhead == pytest.approx(0.5)
    assert document.drag_base_track_count() is None
    _index, found = document.find_segment(segment.segment_id)
    assert found.timeline_start == pytest.approx(0)


def test_drag_empty_pans_the_timeline(qapp):
    widget = show_timeline(qapp)
    send_mouse(widget, "press", 300, lane_y())
    send_mouse(widget, "move", 100, lane_y())
    send_mouse(widget, "release", 100, lane_y())
    assert widget.view_origin == pytest.approx(2.0)
    assert widget.document.playhead == 0


def test_ruler_drag_scrubs_the_playhead_outside_the_widget(qapp):
    widget = show_timeline(qapp)
    widget.view_origin = 1.0
    send_mouse(widget, "press", 200, 8)
    assert widget.document.playhead == pytest.approx(widget.time_at_x(200))
    send_mouse(widget, "move", 450, 500)
    assert widget.document.playhead == pytest.approx(widget.time_at_x(450))
    assert widget.view_origin == pytest.approx(1.0)
    send_mouse(widget, "move", -40, -120)
    assert widget.document.playhead == pytest.approx(widget.time_at_x(-40))
    send_mouse(widget, "release", widget.width() + 80, 240)
    assert widget.document.playhead == pytest.approx(widget.time_at_x(widget.width() + 80))
    assert widget.view_origin == pytest.approx(1.0)


def test_zoom_out_reaches_several_times_the_latest_frame(qapp):
    document = TimelineDocument()
    document.add_media(media("long", 3600))
    document.place_new_segment("long", 1200, 0, True, 0)
    widget = show_timeline(qapp, document)
    qapp.processEvents()
    for _ in range(80):
        widget.zoom_at(100, 1 / widget.ZOOM_FACTOR)
    latest = document.latest_material_time()
    visible = widget.width() / widget.pixels_per_second
    assert latest == pytest.approx(4800)
    assert visible == pytest.approx(latest * widget.ZOOM_OUT_SPAN_MULTIPLIER)


def test_short_material_can_still_zoom_out_to_the_pixel_floor(qapp):
    document = TimelineDocument()
    document.add_media(media("short", 5))
    document.place_new_segment("short", 0, 0, True, 0)
    widget = show_timeline(qapp, document)
    qapp.processEvents()
    for _ in range(40):
        widget.zoom_at(100, 1 / widget.ZOOM_FACTOR)
    assert widget.pixels_per_second == pytest.approx(widget.MIN_PIXELS_PER_SECOND)
    assert widget.width() / widget.pixels_per_second > document.latest_material_time() * widget.ZOOM_OUT_SPAN_MULTIPLIER


def test_wheel_zooms_around_the_cursor(qapp):
    widget = show_timeline(qapp)
    widget.pixels_per_second = 100
    widget.view_origin = 0
    anchor = widget.time_at_x(200)
    event = QWheelEvent(
        QPointF(200, 10),
        QPointF(200, 10),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    assert widget.pixels_per_second == pytest.approx(115)
    assert widget.time_at_x(200) == pytest.approx(anchor)


def test_drag_segment_moves_and_cannot_cross_zero_or_another_segment(qapp):
    document = TimelineDocument()
    document.add_media(media("a", 2))
    document.add_media(media("b", 2))
    left = document.place_new_segment("a", 0, 0, True, 0)
    right = document.place_new_segment("b", 5, 0, False, 0)
    widget = show_timeline(qapp, document)
    send_mouse(widget, "press", 520, lane_y())
    send_mouse(widget, "move", 20, lane_y())
    send_mouse(widget, "release", 20, lane_y())
    ordered = sorted(document.tracks[0], key=lambda item: item.timeline_start)
    assert [item.segment_id for item in ordered] == [left.segment_id, right.segment_id]
    assert ordered[0].timeline_start == pytest.approx(0)
    assert ordered[1].timeline_start == pytest.approx(2)


def test_drag_segment_snaps_to_the_previous_tail(qapp):
    document = TimelineDocument()
    document.add_media(media("a", 2))
    document.add_media(media("b", 2))
    document.place_new_segment("a", 0, 0, True, 0)
    right = document.place_new_segment("b", 4, 0, False, 0)
    widget = show_timeline(qapp, document)
    send_mouse(widget, "press", 400, lane_y())
    send_mouse(widget, "move", 205, lane_y())
    send_mouse(widget, "release", 205, lane_y())
    _index, placed = document.find_segment(right.segment_id)
    assert placed.timeline_start == pytest.approx(2)


def test_vertical_drag_creates_a_track_and_drops_the_empty_one(qapp):
    document = TimelineDocument()
    document.add_media(media("solo", 2))
    segment = document.place_new_segment("solo", 0, 0, True, 0)
    widget = show_timeline(qapp, document)
    y = row_top(0) + TRACK_HEIGHT + 40
    send_mouse(widget, "press", 40, lane_y())
    send_mouse(widget, "move", 40, y)
    assert len(document.tracks) == 2
    assert document.tracks[0] == []
    send_mouse(widget, "release", 40, y)
    assert len(document.tracks) == 1
    assert document.tracks[0][0].segment_id == segment.segment_id


def test_vertical_drag_inserts_below_existing_tracks(qapp):
    document = TimelineDocument()
    document.add_media(media("a", 1))
    document.add_media(media("c", 1))
    document.add_media(media("b", 1))
    top = document.place_new_segment("a", 0, 0, True, 0)
    document.place_new_segment("c", 3, 0, False, 0)
    document.place_new_segment("b", 0, 1, True, 0)
    widget = show_timeline(qapp, document)
    y = row_top(1) + TRACK_HEIGHT + 40
    send_mouse(widget, "press", 20, lane_y(0))
    send_mouse(widget, "move", 20, y)
    send_mouse(widget, "release", 20, y)
    assert [track[0].media_id for track in document.tracks] == ["c", "b", "a"]
    assert document.tracks[2][0].segment_id == top.segment_id


def test_delete_key_removes_the_clicked_segment(qapp):
    document = TimelineDocument()
    document.add_media(media("a", 2))
    document.add_media(media("b", 2))
    first = document.place_new_segment("a", 0, 0, True, 0)
    second = document.place_new_segment("b", 4, 0, False, 0)
    widget = show_timeline(qapp, document)
    send_mouse(widget, "press", 40, lane_y())
    send_mouse(widget, "release", 40, lane_y())
    assert document.selected_segment_id == first.segment_id
    widget.setFocus()
    qapp.processEvents()
    QTest.keyClick(widget, Qt.Key.Key_Delete)
    assert document.selected_segment_id is None
    assert [segment.segment_id for segment in document.all_segments()] == [second.segment_id]
    assert "a" in document.media
    send_mouse(widget, "press", 10, 10)
    send_mouse(widget, "release", 10, 10)
    QTest.keyClick(widget, Qt.Key.Key_Delete)
    assert [segment.segment_id for segment in document.all_segments()] == [second.segment_id]


def test_split_with_s_only_the_selected_segment(qapp):
    document = TimelineDocument()
    document.add_media(media("a", 4))
    document.add_media(media("b", 4))
    selected = document.place_new_segment("a", 0, 0, True, 0)
    other = document.place_new_segment("b", 0, 1, True, 0)
    widget = show_timeline(qapp, document)
    send_mouse(widget, "press", 150, lane_y(0))
    send_mouse(widget, "release", 150, lane_y(0))
    assert document.selected_segment_id == selected.segment_id
    assert document.playhead == pytest.approx(1.5)
    qapp.processEvents()
    assert widget.hasFocus()
    QTest.keyClick(widget, Qt.Key.Key_S)
    assert document.tracks[0][0].timeline_end == pytest.approx(1.5)
    assert document.tracks[0][1].timeline_start == pytest.approx(1.5)
    assert len(document.tracks[1]) == 1
    assert document.tracks[1][0].segment_id == other.segment_id
    document.select_segment(None)
    document.set_playhead(1)
    QTest.keyClick(widget, Qt.Key.Key_S)
    assert len(document.tracks[1]) == 1
    assert len(document.tracks[0]) == 2


def test_edge_scroll_follows_the_pointer_past_either_side(qapp):
    document = TimelineDocument()
    document.add_media(media("a", 2))
    segment = document.place_new_segment("a", 1, 0, True, 0)
    widget = show_timeline(qapp, document)
    send_mouse(widget, "press", 200, lane_y())
    widget._moved = True
    widget._last_pos = QPointF(widget.width() + 80, lane_y())
    widget._on_edge_scroll()
    assert widget.view_origin == pytest.approx(80 * widget.EDGE_SCROLL_GAIN / widget.pixels_per_second)
    assert document.find_segment(segment.segment_id)[1].timeline_start > 1
    widget.view_origin = 5
    widget._last_pos = QPointF(-50, lane_y())
    widget._on_edge_scroll()
    assert widget.view_origin < 5
    assert document.find_segment(segment.segment_id)[1].timeline_start >= 0
    widget.view_origin = 0
    widget._last_pos = QPointF(-50, lane_y())
    widget._on_edge_scroll()
    assert widget.view_origin == 0
    assert document.find_segment(segment.segment_id)[1].timeline_start >= 0
    send_mouse(widget, "release", 200, lane_y())
    assert document.drag_base_track_count() is None


def test_drop_media_places_a_segment(qapp):
    document = TimelineDocument()
    document.add_media(media("clip", 3))
    widget = show_timeline(qapp, document)
    mime = QMimeData()
    mime.setData(MEDIA_MIME, b"clip")
    event = QDropEvent(
        QPointF(0, lane_y()),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert widget.event(event)
    assert len(document.all_segments()) == 1
    assert document.all_segments()[0].timeline_start == pytest.approx(0)
