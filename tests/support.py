import cv2
import numpy as np


def write_color_video(path, frame_count: int, fps: float, size=(160, 90), red_base: int = 0):
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        size,
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to create video: {path}")
    colors = []
    for index in range(frame_count):
        red = red_base + index * 20
        color_bgr = (20, 40, red)
        colors.append(color_bgr)
        frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        frame[:, :] = color_bgr
        writer.write(frame)
    writer.release()
    return colors
