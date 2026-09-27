import pytest

from videocutter.geometry import (
    RULER_HEIGHT,
    TRACK_GAP,
    TRACK_HEIGHT,
    row_top,
    snap_threshold_seconds,
    track_target_at_y,
)


def test_track_target_zones():
    assert track_target_at_y(0, 0) == (True, 0)
    assert track_target_at_y(RULER_HEIGHT - 1, 2) == (True, 0)
    body = row_top(0) + TRACK_HEIGHT / 2
    assert track_target_at_y(body, 2) == (False, 0)
    gap = row_top(0) + TRACK_HEIGHT + TRACK_GAP / 2
    assert track_target_at_y(gap, 2) == (True, 1)
    second = row_top(1) + 8
    assert track_target_at_y(second, 2) == (False, 1)
    below = row_top(1) + TRACK_HEIGHT + TRACK_GAP + 20
    assert track_target_at_y(below, 2) == (True, 2)


def test_snap_threshold_scales_with_zoom():
    assert snap_threshold_seconds(100) == pytest.approx(0.12)
    assert snap_threshold_seconds(200) == pytest.approx(0.06)


def test_row_top_rejects_negative_index():
    with pytest.raises(ValueError):
        row_top(-1)
