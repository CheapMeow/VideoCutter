import math
from pathlib import Path

import cv2
import numpy as np


MEDIA_MIME = "application/x-videocutter-media"

VIDEO_SUFFIXES = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
        ".m4v",
        ".wmv",
        ".flv",
        ".mpg",
        ".mpeg",
        ".ts",
    }
)


def format_duration(seconds: float) -> str:
    if seconds < 0:
        raise ValueError(f"duration must be non-negative, got {seconds}")
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def probe_video(path: str) -> dict[str, float | int]:
    file_path = Path(path)
    if not file_path.is_file():
        raise RuntimeError(f"not a file: {path}")
    capture = cv2.VideoCapture(str(file_path))
    if not capture.isOpened():
        raise RuntimeError(f"failed to open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    bitrate_kbps = float(capture.get(cv2.CAP_PROP_BITRATE))
    capture.release()
    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise RuntimeError(f"invalid video metadata: {path}")
    if not math.isfinite(bitrate_kbps) or bitrate_kbps < 0:
        raise RuntimeError(f"invalid video bitrate: {path}")
    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_sec": frame_count / fps,
        "bitrate_kbps": bitrate_kbps,
    }


def open_capture(path: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise RuntimeError(f"failed to open video: {path}")
    return capture


def read_frame(
    capture: cv2.VideoCapture,
    fps: float,
    frame_count: int,
    source_time_sec: float,
) -> np.ndarray:
    if fps <= 0:
        raise RuntimeError(f"invalid fps: {fps}")
    if frame_count <= 0:
        raise RuntimeError(f"invalid frame count: {frame_count}")
    if source_time_sec < 0:
        raise RuntimeError(f"source time must be non-negative, got {source_time_sec}")
    frame_index = int(source_time_sec * fps)
    if frame_index == frame_count:
        frame_index = frame_count - 1
    if frame_index < 0 or frame_index >= frame_count:
        raise RuntimeError(
            f"frame index {frame_index} outside 0..{frame_count - 1} at {source_time_sec}"
        )
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"failed to read frame {frame_index}")
    return frame
