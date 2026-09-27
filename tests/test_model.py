import pytest

from videocutter.model import MediaItem, TimelineDocument, resolve_timeline_start


def sample_media(
    media_id: str,
    duration: float = 4.0,
    width: int = 16,
    height: int = 16,
) -> MediaItem:
    return MediaItem(
        media_id=media_id,
        path=f"{media_id}.mp4",
        duration_sec=duration,
        fps=10.0,
        frame_count=int(duration * 10),
        width=width,
        height=height,
        bitrate_kbps=1000.0,
    )


def assert_no_overlap(track):
    ordered = sorted(track, key=lambda segment: segment.timeline_start)
    for left, right in zip(ordered, ordered[1:]):
        assert left.timeline_end <= right.timeline_start + 1e-6


def test_move_stops_at_zero():
    document = TimelineDocument()
    document.add_media(sample_media("a", 2))
    segment = document.place_new_segment("a", -3, 0, True, 0)
    assert segment.timeline_start == 0


def test_same_track_cannot_overlap():
    document = TimelineDocument()
    document.add_media(sample_media("a", 2))
    document.add_media(sample_media("b", 2))
    document.place_new_segment("a", 0, 0, True, 0)
    moved = document.place_new_segment("b", 1, 0, False, 0)
    assert moved.timeline_start == pytest.approx(2)
    assert_no_overlap(document.tracks[0])


def test_many_desired_positions_stay_disjoint_and_non_negative():
    document = TimelineDocument()
    document.add_media(sample_media("blocker", 5))
    document.place_new_segment("blocker", 0, 0, True, 0)
    blockers = list(document.tracks[0])
    for desired in (-1, 0, 0.5, 1, 2, 4.9, 5, 7, 100):
        start = resolve_timeline_start(2, desired, blockers, None, 0, blockers)
        assert start >= 0
        assert start >= 5 - 1e-6 or start + 2 <= 1e-6


def test_snap_joins_head_to_tail_and_tail_to_head():
    document = TimelineDocument()
    document.add_media(sample_media("a", 2))
    document.add_media(sample_media("b", 2))
    left = document.place_new_segment("a", 0, 0, True, 0)
    right = document.place_new_segment("b", 5, 0, False, 0)
    snapped = resolve_timeline_start(
        right.duration,
        left.timeline_end + 0.05,
        [left],
        right.segment_id,
        0.2,
        [left],
    )
    assert snapped == pytest.approx(left.timeline_end)
    snapped_tail = resolve_timeline_start(
        left.duration,
        right.timeline_start - left.duration - 0.05,
        [right],
        left.segment_id,
        0.2,
        [right],
    )
    assert snapped_tail == pytest.approx(right.timeline_start - left.duration)


def test_snap_does_not_enter_another_segment():
    document = TimelineDocument()
    document.add_media(sample_media("a", 2))
    document.add_media(sample_media("b", 2))
    document.add_media(sample_media("c", 2))
    first = document.place_new_segment("a", 0, 0, True, 0)
    second = document.place_new_segment("b", 2, 0, False, 0)
    start = resolve_timeline_start(
        2,
        first.timeline_end - 0.05,
        [first, second],
        "moving",
        0.2,
        [first, second],
    )
    assert start == pytest.approx(second.timeline_end)


def test_split_keeps_source_ranges_and_ignores_edges():
    document = TimelineDocument()
    document.add_media(sample_media("a", 4))
    segment = document.place_new_segment("a", 0, 0, True, 0)
    document.select_segment(segment.segment_id)
    document.set_playhead(0)
    assert document.split_selected() is None
    document.set_playhead(segment.timeline_end)
    assert document.split_selected() is None
    document.set_playhead(1.5)
    pair = document.split_selected()
    assert pair is not None
    left, right = pair
    assert left.timeline_start == pytest.approx(0)
    assert left.timeline_end == pytest.approx(1.5)
    assert left.source_in == pytest.approx(0)
    assert left.source_out == pytest.approx(1.5)
    assert right.timeline_start == pytest.approx(1.5)
    assert right.source_in == pytest.approx(1.5)
    assert right.source_out == pytest.approx(4)
    assert len(document.tracks[0]) == 2


def test_split_only_the_selected_segment():
    document = TimelineDocument()
    document.add_media(sample_media("a", 4))
    document.add_media(sample_media("b", 4))
    selected = document.place_new_segment("a", 0, 0, True, 0)
    other = document.place_new_segment("b", 0, 1, True, 0)
    document.set_playhead(2)
    assert document.split_selected() is None
    assert len(document.tracks[0]) == 1
    assert len(document.tracks[1]) == 1
    document.select_segment(selected.segment_id)
    document.set_playhead(0)
    assert document.split_selected() is None
    document.set_playhead(5)
    assert document.split_selected() is None
    document.set_playhead(2)
    pair = document.split_selected()
    assert pair is not None
    assert pair[0].segment_id == selected.segment_id
    assert len(document.tracks[0]) == 2
    assert len(document.tracks[1]) == 1
    assert document.tracks[1][0].segment_id == other.segment_id


def test_upper_track_supplies_the_current_frame():
    document = TimelineDocument()
    document.add_media(sample_media("lower", 4))
    document.add_media(sample_media("upper", 4))
    document.place_new_segment("lower", 0, 0, True, 0)
    document.place_new_segment("upper", 0, 0, True, 0)
    document.set_playhead(1)
    located = document.source_time_at_playhead()
    assert located is not None
    media, source_time = located
    assert media.media_id == "upper"
    assert source_time == pytest.approx(1)


def test_trimmed_segment_maps_playhead_back_to_source_time():
    document = TimelineDocument()
    document.add_media(sample_media("a", 4))
    segment = document.place_new_segment("a", 0, 0, True, 0)
    document.select_segment(segment.segment_id)
    document.set_playhead(1)
    document.split_selected()
    document.set_playhead(2.5)
    located = document.source_time_at_playhead()
    assert located is not None
    _media, source_time = located
    assert source_time == pytest.approx(2.5)


def test_vertical_drag_inserts_a_track_and_commit_drops_empty_tracks():
    document = TimelineDocument()
    document.add_media(sample_media("a", 1))
    document.add_media(sample_media("c", 1))
    document.add_media(sample_media("b", 1))
    first = document.place_new_segment("a", 0, 0, True, 0)
    document.place_new_segment("c", 3, 0, False, 0)
    document.place_new_segment("b", 0, 1, True, 0)
    document.begin_segment_drag(first.segment_id)
    document.update_segment_drag(0, 2, True, 0)
    assert len(document.tracks) == 3
    assert document.tracks[0] == [] or document.tracks[0][0].media_id == "c"
    document.end_segment_drag()
    assert [track[0].media_id for track in document.tracks] == ["c", "b", "a"]
    assert document.drag_base_track_count() is None


def test_drag_cancel_restores_the_original_track():
    document = TimelineDocument()
    document.add_media(sample_media("a", 2))
    segment = document.place_new_segment("a", 1, 0, True, 0)
    document.begin_segment_drag(segment.segment_id)
    document.update_segment_drag(4, 1, True, 0)
    document.cancel_segment_drag()
    restored_index, restored = document.find_segment(segment.segment_id)
    assert restored_index == 0
    assert restored.timeline_start == pytest.approx(1)
    assert len(document.tracks) == 1


def test_latest_material_time_uses_source_duration_and_segment_end():
    document = TimelineDocument()
    document.add_media(sample_media("long", 7200))
    assert document.latest_material_time() == pytest.approx(7200)
    document.add_media(sample_media("short", 2))
    placed = document.place_new_segment("short", 8000, 0, True, 0)
    assert document.latest_material_time() == pytest.approx(placed.timeline_end)


def test_delete_segment_removes_only_that_segment_and_empty_tracks():
    document = TimelineDocument()
    document.add_media(sample_media("a", 2))
    document.add_media(sample_media("b", 2))
    first = document.place_new_segment("a", 0, 0, True, 0)
    second = document.place_new_segment("b", 0, 1, True, 0)
    document.select_segment(first.segment_id)
    document.delete_segment(first.segment_id)
    assert document.selected_segment_id is None
    assert [segment.segment_id for segment in document.all_segments()] == [second.segment_id]
    assert len(document.tracks) == 1
    assert "a" in document.media
    with pytest.raises(KeyError):
        document.delete_segment(first.segment_id)


def test_delete_segment_rejects_an_active_drag():
    document = TimelineDocument()
    document.add_media(sample_media("a", 2))
    segment = document.place_new_segment("a", 0, 0, True, 0)
    document.begin_segment_drag(segment.segment_id)
    with pytest.raises(RuntimeError):
        document.delete_segment(segment.segment_id)
    document.cancel_segment_drag()


def test_negative_playhead_is_clamped():
    document = TimelineDocument()
    document.set_playhead(-2)
    assert document.playhead == 0


def test_output_size_follows_the_first_placed_media():
    document = TimelineDocument()
    document.add_media(sample_media("first", 2, width=160, height=90))
    document.add_media(sample_media("same", 2, width=160, height=90))
    document.add_media(sample_media("other", 2, width=80, height=60))
    placed = document.place_new_segment("first", 0, 0, True, 0)
    assert document.reference_media() is not None
    assert document.reference_media().media_id == "first"
    document.place_new_segment("same", 0, 1, True, 0)
    with pytest.raises(ValueError, match="80x60"):
        document.place_new_segment("other", 0, 2, True, 0)
    assert [segment.media_id for segment in document.all_segments()] == ["first", "same"]
    document.delete_segment(placed.segment_id)
    assert document.reference_media() is not None
    assert document.reference_media().media_id == "first"
    document.delete_segment(document.all_segments()[0].segment_id)
    assert document.reference_media() is None
    again = document.place_new_segment("other", 0, 0, True, 0)
    assert again.media_id == "other"
    assert document.reference_media() is not None
    assert document.reference_media().width == 80
    assert document.reference_media().height == 60
