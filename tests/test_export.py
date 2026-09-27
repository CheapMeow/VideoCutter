from pathlib import Path

import numpy as np
import pytest

from tests.support import write_color_video
import cv2

from videocutter.export import (
    default_export_filter,
    export_timeline,
    fourcc_for_suffix,
    output_path_for_filter,
)
from videocutter.output_settings import RATE_MAX, RATE_MIN, RATE_SPECIFIED, OutputSettings
from videocutter.media import open_capture, probe_video, read_frame
from videocutter.model import MediaItem, TimelineDocument, new_id


def add_video(
    document: TimelineDocument,
    path: Path,
    red_base: int,
    size,
    frame_count: int = 8,
    fps: float = 10,
):
    write_color_video(path, frame_count=frame_count, fps=fps, size=size, red_base=red_base)
    probed = probe_video(str(path))
    item = MediaItem(
        media_id=new_id(),
        path=str(path),
        duration_sec=float(probed["duration_sec"]),
        fps=float(probed["fps"]),
        frame_count=int(probed["frame_count"]),
        width=int(probed["width"]),
        height=int(probed["height"]),
        bitrate_kbps=float(probed["bitrate_kbps"]),
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
    progress: list[tuple[int, int]] = []

    def record(written: int, total: int) -> None:
        progress.append((written, total))

    export_timeline(document, str(output), record, lambda: False, OutputSettings())
    probed = probe_video(str(output))
    assert probed["width"] == 160
    assert probed["height"] == 90
    assert probed["fps"] == pytest.approx(10)
    assert probed["frame_count"] == 12
    assert progress == [(index, 12) for index in range(13)]
    capture = open_capture(str(output))
    gap = read_frame(capture, probed["fps"], probed["frame_count"], 0.0)
    covered = read_frame(capture, probed["fps"], probed["frame_count"], 0.4)
    later = read_frame(capture, probed["fps"], probed["frame_count"], 1.0)
    capture.release()
    np.testing.assert_allclose(gap[40, 80], (0, 0, 0), atol=12)
    np.testing.assert_allclose(covered[40, 80], (20, 40, 0), atol=12)
    np.testing.assert_allclose(later[40, 80], (20, 40, 120), atol=12)


def test_default_export_is_h264_and_other_suffixes_use_their_codecs(tmp_path):
    assert default_export_filter() == "MP4 视频 (*.mp4)"
    assert fourcc_for_suffix(".mp4") == "avc1"
    assert fourcc_for_suffix(".mov") == "avc1"
    assert output_path_for_filter(r"D:\clips\out", default_export_filter()) == r"D:\clips\out.mp4"
    assert output_path_for_filter(r"D:\clips\out.avi", "AVI 视频 (*.avi)") == r"D:\clips\out.avi"
    document = TimelineDocument()
    clip = add_video(document, tmp_path / "clip.avi", 0, (160, 90), frame_count=4)
    document.place_new_segment(clip.media_id, 0, 0, True, 0)
    expected = {
        "out.mp4": "h264",
        "out.mov": "h264",
        "out.webm": "VP90",
    }
    for name, codec in expected.items():
        output = tmp_path / name
        finished = export_timeline(
            document,
            str(output),
            lambda _written, _total: None,
            lambda: False,
            OutputSettings(),
        )
        assert finished is True
        capture = cv2.VideoCapture(str(output))
        raw = int(capture.get(cv2.CAP_PROP_FOURCC))
        read_codec = "".join(chr((raw >> (8 * index)) & 0xFF) for index in range(4))
        ok, frame = capture.read()
        capture.release()
        assert read_codec == codec
        assert ok
        np.testing.assert_allclose(frame[40, 80], (20, 40, 0), atol=16)


def test_stop_during_export_removes_the_partial_file(tmp_path):
    document = TimelineDocument()
    clip = add_video(document, tmp_path / "clip.avi", 0, (160, 90), frame_count=8)
    document.place_new_segment(clip.media_id, 0, 0, True, 0)
    output = tmp_path / "out.avi"
    progress: list[tuple[int, int]] = []

    def record(written: int, total: int) -> None:
        progress.append((written, total))

    def should_stop() -> bool:
        return bool(progress) and progress[-1][0] >= 1

    finished = export_timeline(document, str(output), record, should_stop, OutputSettings())
    assert finished is False
    assert progress == [(0, 8), (1, 8)]
    assert not output.exists()


def test_export_fps_follows_the_selected_segment_rate(tmp_path):
    document = TimelineDocument()
    slow = add_video(document, tmp_path / "slow.avi", 0, (160, 90), frame_count=8, fps=10)
    fast = add_video(document, tmp_path / "fast.avi", 40, (160, 90), frame_count=8, fps=30)
    document.place_new_segment(slow.media_id, 0, 0, True, 0)
    document.place_new_segment(fast.media_id, 0, 1, True, 0)
    minimum = tmp_path / "min.mp4"
    maximum = tmp_path / "max.mp4"
    chosen = tmp_path / "chosen.mp4"
    export_timeline(
        document,
        str(minimum),
        lambda _written, _total: None,
        lambda: False,
        OutputSettings(fps_mode=RATE_MIN),
    )
    export_timeline(
        document,
        str(maximum),
        lambda _written, _total: None,
        lambda: False,
        OutputSettings(fps_mode=RATE_MAX),
    )
    export_timeline(
        document,
        str(chosen),
        lambda _written, _total: None,
        lambda: False,
        OutputSettings(fps_mode=RATE_SPECIFIED, fps_value=15),
    )
    assert probe_video(str(minimum))["fps"] == pytest.approx(10)
    assert probe_video(str(minimum))["frame_count"] == 8
    assert probe_video(str(maximum))["fps"] == pytest.approx(30)
    assert probe_video(str(maximum))["frame_count"] == 24
    assert probe_video(str(chosen))["fps"] == pytest.approx(15)
    assert probe_video(str(chosen))["frame_count"] == 12


def test_specified_bitrate_changes_the_file_size(tmp_path):
    path = tmp_path / "noise.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 90))
    if not writer.isOpened():
        raise RuntimeError(f"failed to create video: {path}")
    generator = np.random.default_rng(1)
    for _index in range(20):
        writer.write(generator.integers(0, 256, (90, 160, 3), dtype=np.uint8))
    writer.release()
    document = TimelineDocument()
    probed = probe_video(str(path))
    item = MediaItem(
        media_id=new_id(),
        path=str(path),
        duration_sec=float(probed["duration_sec"]),
        fps=float(probed["fps"]),
        frame_count=int(probed["frame_count"]),
        width=int(probed["width"]),
        height=int(probed["height"]),
        bitrate_kbps=float(probed["bitrate_kbps"]),
    )
    document.add_media(item)
    document.place_new_segment(item.media_id, 0, 0, True, 0)
    low = tmp_path / "low.mp4"
    high = tmp_path / "high.mp4"
    export_timeline(
        document,
        str(low),
        lambda _written, _total: None,
        lambda: False,
        OutputSettings(bitrate_mode=RATE_SPECIFIED, bitrate_kbps=200),
    )
    export_timeline(
        document,
        str(high),
        lambda _written, _total: None,
        lambda: False,
        OutputSettings(bitrate_mode=RATE_SPECIFIED, bitrate_kbps=4000),
    )
    assert high.stat().st_size > low.stat().st_size * 4
