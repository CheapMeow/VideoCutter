import math

import cv2
import numpy as np

from videocutter.media import open_capture, read_frame
from videocutter.model import TIME_EPSILON, MediaItem, TimelineDocument


def export_timeline(document: TimelineDocument, path: str) -> None:
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
        cv2.VideoWriter_fourcc(*"MJPG"),
        reference.fps,
        (reference.width, reference.height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to create video: {path}")
    captures: dict[str, cv2.VideoCapture] = {}
    try:
        for index in range(frame_count):
            writer.write(_frame_at(document, reference, captures, index / reference.fps))
    finally:
        writer.release()
        for capture in captures.values():
            capture.release()


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
