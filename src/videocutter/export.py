import math
from pathlib import Path

import cv2
import numpy as np

from videocutter.media import open_capture, read_frame
from videocutter.model import TIME_EPSILON, MediaItem, TimelineDocument


# 对话框里的顺序就是列表顺序。第一项是默认格式，编码是 H.264。
EXPORT_CHOICES = (
    ("MP4 视频 (*.mp4)", ".mp4", "avc1"),
    ("MOV 视频 (*.mov)", ".mov", "avc1"),
    ("AVI 视频 (*.avi)", ".avi", "MJPG"),
    ("WebM 视频 (*.webm)", ".webm", "VP90"),
)


def export_filter_string() -> str:
    return ";;".join(label for label, _suffix, _fourcc in EXPORT_CHOICES)


def default_export_filter() -> str:
    return EXPORT_CHOICES[0][0]


def suffix_for_filter(selected_filter: str) -> str:
    for label, suffix, _fourcc in EXPORT_CHOICES:
        if selected_filter == label:
            return suffix
    raise ValueError(f"unknown export filter: {selected_filter}")


def fourcc_for_suffix(suffix: str) -> str:
    lowered = suffix.lower()
    for _label, item_suffix, fourcc in EXPORT_CHOICES:
        if item_suffix == lowered:
            return fourcc
    raise ValueError(f"unsupported export suffix: {suffix}")


def output_path_for_filter(path: str, selected_filter: str) -> str:
    return str(Path(path).with_suffix(suffix_for_filter(selected_filter)))


def export_timeline(document: TimelineDocument, path: str, on_progress, should_stop) -> bool:
    reference = document.reference_media()
    segments = document.all_segments()
    if reference is None or not segments:
        raise RuntimeError("timeline has no video to export")
    duration = max(segment.timeline_end for segment in segments)
    frame_count = int(math.floor(duration * reference.fps + TIME_EPSILON))
    if frame_count <= 0:
        raise RuntimeError(f"export frame count must be positive, got {frame_count}")
    writer = cv2.VideoWriter(
        path,
        cv2.VideoWriter_fourcc(*fourcc_for_suffix(Path(path).suffix)),
        reference.fps,
        (reference.width, reference.height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to create video: {path}")
    captures: dict[str, cv2.VideoCapture] = {}
    cancelled = False
    try:
        on_progress(0, frame_count)
        if should_stop():
            cancelled = True
            return False
        for index in range(frame_count):
            writer.write(_frame_at(document, reference, captures, index / reference.fps))
            on_progress(index + 1, frame_count)
            if should_stop():
                cancelled = True
                return False
        return True
    finally:
        writer.release()
        for capture in captures.values():
            capture.release()
        if cancelled:
            Path(path).unlink()


def _frame_at(
    document: TimelineDocument,
    reference: MediaItem,
    captures: dict[str, cv2.VideoCapture],
    time_sec: float,
) -> np.ndarray:
    segment = document.top_segment_at(time_sec)
    if segment is None:
        return np.zeros((reference.height, reference.width, 3), dtype=np.uint8)
    media = document.media[segment.media_id]
    source_time = segment.source_in + (time_sec - segment.timeline_start)
    capture = captures.get(media.path)
    if capture is None:
        capture = open_capture(media.path)
        captures[media.path] = capture
    frame = read_frame(capture, media.fps, media.frame_count, source_time)
    if frame.shape[0] != reference.height or frame.shape[1] != reference.width:
        raise RuntimeError(
            f"frame size {frame.shape[1]}x{frame.shape[0]} does not match "
            f"output size {reference.width}x{reference.height}"
        )
    return frame
