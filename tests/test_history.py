import pytest

from videocutter.model import TimelineDocument
from tests.test_model import sample_media


def document_with_segment():
    document = TimelineDocument()
    document.add_media(sample_media("a"))
    segment = document.place_new_segment("a", 0, 0, True, 0)
    document.select_segment(segment.segment_id)
    return document, segment


def test_import_and_placement_restore_media_reference_and_identifiers():
    document = TimelineDocument()
    assert not document.undo()
    assert not document.redo()
    document.add_media(sample_media("a"))
    segment = document.place_new_segment("a", 2, 0, True, 0)
    placed = document._history.capture()
    assert document.undo()
    assert document.media.keys() == {"a"}
    assert document.tracks == []
    assert document.reference_media_id is None
    assert document.undo()
    assert document.media == {}
    assert not document.can_undo()
    assert document.redo()
    assert document.redo()
    assert document._history.capture() == placed
    assert document.all_segments()[0].segment_id == segment.segment_id


def test_split_delete_and_redo_restore_exact_source_ranges_and_selection():
    document, segment = document_with_segment()
    document.set_playhead(1.25)
    before = document._history.capture()
    pair = document.split_selected()
    split = document._history.capture()
    right_id = pair[1].segment_id
    document.select_segment(right_id)
    selected = document._history.capture()
    document.delete_segment(right_id)
    assert len(document.all_segments()) == 1
    assert document.undo()
    assert document._history.capture() == selected
    assert document.undo()
    assert document._history.capture() == before
    assert document.redo()
    assert document._history.capture() == split
    assert document.redo()
    assert len(document.all_segments()) == 1
    assert document.all_segments()[0].segment_id == segment.segment_id
    assert document.all_segments()[0].source_out == pytest.approx(1.25)


def test_remove_media_restores_every_track_and_output_reference():
    document, segment = document_with_segment()
    document.add_media(sample_media("b"))
    document.place_new_segment("a", 5, 1, True, 0)
    document.place_new_segment("b", 10, 2, True, 0)
    before = document._history.capture()
    document.delete_media("a")
    assert document.reference_media_id == "b"
    assert document.selected_segment_id is None
    assert len(document.tracks) == 1
    assert document.undo()
    assert document._history.capture() == before
    assert document.find_segment(segment.segment_id)[0] == 0
    assert document.redo()
    assert "a" not in document.media
    assert all(s.media_id == "b" for s in document.all_segments())


def test_drag_records_one_edit_and_restores_track_order():
    document, segment = document_with_segment()
    document.add_media(sample_media("b"))
    document.place_new_segment("b", 0, 1, True, 0)
    document.clear_history()
    before = document._history.capture()
    document.begin_segment_drag(segment.segment_id)
    for start in range(1, 15):
        document.update_segment_drag(start, 2, True, 0)
    document.end_segment_drag()
    after = document._history.capture()
    assert after.tracks[1][0].segment_id == segment.segment_id
    assert document.undo()
    assert document._history.capture() == before
    assert not document.can_undo()
    assert document.redo()
    assert document._history.capture() == after
    assert document.drag_base_track_count() is None


def test_cancelled_and_stationary_drags_do_not_add_history():
    document, segment = document_with_segment()
    document.clear_history()
    before = document._history.capture()
    document.begin_segment_drag(segment.segment_id)
    document.update_segment_drag(10, 1, True, 0)
    with pytest.raises(RuntimeError):
        document.undo()
    document.cancel_segment_drag()
    assert document._history.capture() == before
    assert not document.can_undo()
    document.begin_segment_drag(segment.segment_id)
    document.update_segment_drag(0, 0, False, 0)
    document.end_segment_drag()
    assert not document.can_undo()


def test_navigation_and_no_op_splits_preserve_redo():
    document, segment = document_with_segment()
    document.set_playhead(2)
    document.split_selected()
    assert document.undo()
    document.set_playhead(0)
    document.select_segment(segment.segment_id)
    assert document.split_selected() is None
    assert document.can_redo()
    document.set_playhead(3)
    assert document.redo()
    assert len(document.all_segments()) == 2
    assert document.playhead == 2


def test_new_edit_after_undo_discards_redo():
    document, segment = document_with_segment()
    document.set_playhead(1)
    document.split_selected()
    document.undo()
    document.delete_segment(segment.segment_id)
    assert not document.can_redo()
    assert not document.redo()
    assert document.tracks == []


def test_batch_import_and_delete_each_form_one_edit():
    document = TimelineDocument()
    with document.edit_group():
        document.add_media(sample_media("a"))
        document.add_media(sample_media("b"))
    assert document.undo()
    assert document.media == {}
    assert not document.can_undo()
    assert document.redo()
    with document.edit_group():
        document.delete_media("a")
        document.delete_media("b")
    assert document.undo()
    assert document.media.keys() == {"a", "b"}
    assert document.redo()
    assert document.media == {}


def test_failed_edit_is_atomic_and_preserves_redo():
    document, segment = document_with_segment()
    document.delete_segment(segment.segment_id)
    document.undo()
    before = document._history.capture()
    with pytest.raises(ValueError):
        with document.edit_group():
            document.delete_media("a")
            document.add_media(sample_media("b"))
            document.add_media(sample_media("b"))
    assert document._history.capture() == before
    assert document.can_redo()
    with pytest.raises(ValueError):
        document.place_new_segment("a", float("nan"), 0, True, 0)
    assert document._history.capture() == before
    assert document.can_redo()


def test_history_snapshots_are_independent_of_later_changes():
    document, segment = document_with_segment()
    document.set_playhead(1)
    document.split_selected()
    document.undo()
    document.all_segments()[0].source_out = 3
    document.redo()
    assert document.all_segments()[-1].source_out == 4
    document.undo()
    assert document.all_segments()[0].source_out == 4


def test_history_keeps_a_bounded_number_of_edits():
    document = TimelineDocument()
    for index in range(document._history.LIMIT + 5):
        document.add_media(sample_media(str(index)))
    count = 0
    while document.undo():
        count += 1
    assert count == document._history.LIMIT
    assert len(document.media) == 5
    document.clear_history()
    assert not document.can_undo()
    assert not document.can_redo()
