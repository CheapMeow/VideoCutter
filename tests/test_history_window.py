import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest

from videocutter.geometry import TRACK_HEIGHT, row_top
from videocutter.main_window import MainWindow
from videocutter.project import load_project
from tests.support import write_color_video
from tests.test_playback import wait_until


@pytest.fixture
def edit_window(qapp, tmp_path):
    paths = [tmp_path / "first.avi", tmp_path / "second.avi"]
    for path in paths:
        write_color_video(path, 8, 10)
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    window.activateWindow()
    qapp.processEvents()
    window.source_panel.add_paths([str(path) for path in paths])
    yield window
    window.close()


def press_history(window, key, widget=None):
    target = widget if widget is not None else window.timeline
    window.activateWindow()
    target.setFocus()
    QTest.qWait(20)
    QTest.keyClick(target, key, Qt.KeyboardModifier.ControlModifier)


def place_first(window):
    media_id = next(iter(window.document.media))
    segment = window.document.place_new_segment(media_id, 0, 0, True, 0)
    window.document.select_segment(segment.segment_id)
    window.refresh_views()
    return segment


def test_shortcuts_work_from_media_panel_and_batch_import_is_one_edit(edit_window):
    window = edit_window
    assert window.source_panel.file_list.count() == 2
    media_ids = list(window.document.media)
    press_history(window, Qt.Key.Key_Z, window.source_panel.file_list)
    assert window.source_panel.file_list.count() == 0
    assert window.document.media == {}
    press_history(window, Qt.Key.Key_Y, window.source_panel.file_list)
    assert window.source_panel.file_list.count() == 2
    assert list(window.document.media) == media_ids
    assert window.statusBar().currentMessage() == "已重做"


def test_keyboard_split_delete_undo_redo_update_preview_and_selection(edit_window):
    window = edit_window
    segment = place_first(window)
    window.document.set_playhead(0.3)
    window.timeline.setFocus()
    QTest.qWait(20)
    QTest.keyClick(window.timeline, Qt.Key.Key_S)
    assert len(window.document.all_segments()) == 2
    right_id = window.document.all_segments()[1].segment_id
    press_history(window, Qt.Key.Key_Z)
    assert [s.segment_id for s in window.document.all_segments()] == [segment.segment_id]
    assert window.document.selected_segment_id == segment.segment_id
    assert window.preview.frame_pixmap() is not None
    press_history(window, Qt.Key.Key_Y)
    assert window.document.all_segments()[1].segment_id == right_id
    window.document.select_segment(right_id)
    QTest.keyClick(window.timeline, Qt.Key.Key_Delete)
    assert len(window.document.all_segments()) == 1
    press_history(window, Qt.Key.Key_Z)
    assert window.document.selected_segment_id == right_id
    assert len(window.document.all_segments()) == 2


def test_multi_selection_delete_restores_media_and_associated_segments(edit_window):
    window = edit_window
    place_first(window)
    media_ids = list(window.document.media)
    window.document.place_new_segment(media_ids[1], 0, 1, True, 0)
    before = window.document._history.capture()
    window.source_panel.file_list.selectAll()
    window.source_panel.remove_selected_media()
    assert window.document.media == {}
    assert window.document.tracks == []
    press_history(window, Qt.Key.Key_Z)
    assert window.document._history.capture() == before
    assert window.source_panel.file_list.count() == 2
    assert window.preview.frame_pixmap() is not None
    press_history(window, Qt.Key.Key_Y)
    assert window.source_panel.file_list.count() == 0
    assert window.preview.frame_pixmap() is None


def test_undo_during_drag_cancels_the_gesture_without_consuming_history(edit_window):
    window = edit_window
    segment = place_first(window)
    before = window.document._history.capture()
    start = QPoint(20, int(row_top(0) + TRACK_HEIGHT / 2))
    target = QPoint(250, int(row_top(1) + TRACK_HEIGHT / 2))
    QTest.mousePress(window.timeline, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.timeline, target)
    assert window.document.drag_base_track_count() is not None
    press_history(window, Qt.Key.Key_Z)
    assert window.document._history.capture() == before
    assert window.timeline._mode is None
    assert not window.timeline._scroll_timer.isActive()
    QTest.mouseRelease(window.timeline, Qt.MouseButton.LeftButton, pos=target)
    assert window.document.find_segment(segment.segment_id)[1].timeline_start == 0
    press_history(window, Qt.Key.Key_Z)
    assert window.document.all_segments() == []
    press_history(window, Qt.Key.Key_Y)
    assert window.document.all_segments()[0].segment_id == segment.segment_id


def test_undo_pauses_playback_and_releases_old_media(edit_window):
    window = edit_window
    place_first(window)
    window._toggle_playback()
    wait_until(lambda: window.document.playhead > 0.1)
    press_history(window, Qt.Key.Key_Z)
    assert not window.is_playing()
    assert window.document.all_segments() == []
    assert window._playback.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    assert window._playback.player.source().isEmpty()
    assert not window.preview.video_widget.isVisible()
    press_history(window, Qt.Key.Key_Y)
    assert len(window.document.all_segments()) == 1
    window._toggle_playback()
    wait_until(lambda: window.document.playhead > 0.1)
    assert window.is_playing()


def test_opening_project_starts_fresh_history(edit_window, tmp_path):
    window = edit_window
    place_first(window)
    project = tmp_path / "saved.vcproj"
    window._save_project_to_path(str(project))
    assert window.document.can_undo()
    loaded = load_project(str(project))
    assert not loaded.can_undo()
    assert not loaded.can_redo()
    window._open_project_from_path(str(project))
    before = window.document._history.capture()
    press_history(window, Qt.Key.Key_Z)
    press_history(window, Qt.Key.Key_Y)
    assert window.document._history.capture() == before


def test_history_keys_do_not_modify_document_during_real_export(edit_window, tmp_path):
    window = edit_window
    place_first(window)
    before = window.document._history.capture()
    checked = []

    def attempt_history():
        assert window._exporting
        window.undo_edit()
        window.redo_edit()
        checked.append(window.document._history.capture() == before)

    QTimer.singleShot(0, attempt_history)
    output = tmp_path / "export.avi"
    window._export_to_path(str(output))
    assert output.is_file()
    assert checked == [True]
    assert window.document._history.capture() == before


def test_failed_batch_import_leaves_media_list_and_history_unchanged(edit_window, tmp_path):
    window = edit_window
    valid = tmp_path / "valid.avi"
    write_color_video(valid, 8, 10)
    before = window.document._history.capture()
    with pytest.raises(RuntimeError):
        window.source_panel.add_paths([str(valid), str(tmp_path / "missing.avi")])
    assert window.document._history.capture() == before
    assert window.source_panel.file_list.count() == 2
