from pathlib import Path

import numpy as np
import pytest

from tests.support import write_color_video
from videocutter.export import export_timeline
from videocutter.media import open_capture, probe_video, read_frame
from videocutter.model import MediaItem, TimelineDocument, new_id


def add_video(document: TimelineDocument, path: Path, red_base: int, size, frame_count: int = 8):
    write_color_video(path, frame_count=frame_count, fps=10, size=size, red_base=red_base)
    probed = probe_video(str(path))
    item = MediaItem(
        media_id=new_id(),
        path=str(path),
        duration_sec=float(probed["duration_sec"]),
        fps=float(probed["fps"]),
        frame_count=int(probed["frame_count"]),
        width=int(probed["width"]),
        height=int(probed["height"]),
    )
    document.add_media(item)
    return item


def test_export_uses_the_first_size_and_the_top_track(tmp_path):
    document = TimelineDocument()
    lower = add_video(document, tmp_path / "lower.avi", 100, (160, 90))
    upper = add_video(document, tmp_path / "upper.avi", 0, (160, 90))
    document.place_new_segment(lower.media_id, 0.4, 0, True, 0)
    document.place_new_segment(upper.media_id, 0.4, 0, True, 0)
    output = tmp_path / "out.avi"
    export_timeline(document, str(output))
    probed = probe_video(str(output))
    assert probed["width"] == 160
    assert probed["height"] == 90
    assert probed["fps"] == pytest.approx(10)
    assert probed["frame_count"] == 12
    capture = open_capture(str(output))
    gap = read_frame(capture, probed["fps"], probed["frame_count"], 0.0)
    covered = read_frame(capture, probed["fps"], probed["frame_count"], 0.4)
    later = read_frame(capture, probed["fps"], probed["frame_count"], 1.0)
    capture.release()
    np.testing.assert_allclose(gap[40, 80], (0, 0, 0), atol=12)
    np.testing.assert_allclose(covered[40, 80], (20, 40, 0), atol=12)
    np.testing.assert_allclose(later[40, 80], (20, 40, 120), atol=12)
