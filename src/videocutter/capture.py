import math
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap

from videocutter.media import frame_index_at


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
    frame_index = frame_index_at(fps, frame_count, source_time_sec)
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"failed to read frame {frame_index}")
    return frame


def frame_to_pixmap(frame: np.ndarray) -> QPixmap:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise RuntimeError(f"expected a BGR frame, got shape {frame.shape}")
    rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    height, width, channels = rgb.shape
    image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())
