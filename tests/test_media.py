import numpy as np

from tests.support import write_color_video
from videocutter.capture import open_capture, probe_video, read_frame
from videocutter.media import format_duration


def test_probe_and_read_frames(tmp_path):
    path = tmp_path / "colors.avi"
    colors = write_color_video(path, frame_count=8, fps=10)
    probed = probe_video(str(path))
    assert probed["frame_count"] == 8
    assert probed["fps"] == 10
    assert probed["width"] == 160
    assert probed["height"] == 90
    assert probed["duration_sec"] == 0.8
    capture = open_capture(str(path))
    later = read_frame(capture, probed["fps"], probed["frame_count"], 0.3)
    first = read_frame(capture, probed["fps"], probed["frame_count"], 0.0)
    capture.release()
    np.testing.assert_allclose(later[45, 80], colors[3], atol=12)
    np.testing.assert_allclose(first[10, 10], colors[0], atol=12)


def test_format_duration():
    assert format_duration(5.2) == "0:05"
    assert format_duration(90.4) == "1:30"
    assert format_duration(3661) == "1:01:01"
