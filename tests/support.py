import math
from fractions import Fraction

import av
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

def write_tone_video(path, frame_count: int, fps: int, rate: int = 48000, frequency_hz: float = 1000.0):
    container = av.open(str(path), mode="w")
    stream = container.add_stream("libx264", rate=fps)
    stream.width = 160
    stream.height = 90
    stream.pix_fmt = "yuv420p"
    audio_stream = container.add_stream("aac", rate=rate)
    audio_stream.layout = "stereo"
    samples_per_frame = 1024
    total_samples = frame_count / fps * rate
    total_samples = int(math.ceil(total_samples / samples_per_frame) * samples_per_frame)
    emitted = 0
    audio_pts = 0
    while emitted < total_samples:
        take = min(samples_per_frame, total_samples - emitted)
        angle = 2 * math.pi * frequency_hz * np.arange(emitted, emitted + take) / rate
        wave = (0.8 * np.sin(angle)).astype(np.float32)
        audio_frame = av.AudioFrame.from_ndarray(
            np.stack([wave, wave]), format="fltp", layout="stereo"
        )
        audio_frame.sample_rate = rate
        audio_frame.pts = audio_pts
        for packet in audio_stream.encode(audio_frame):
            container.mux(packet)
        audio_pts += take
        emitted += take
    for index in range(frame_count):
        image = np.full((90, 160, 3), (index % 16) * 16, dtype=np.uint8)
        video_frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        video_frame.pts = index
        video_frame.time_base = Fraction(1, fps)
        for packet in stream.encode(video_frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    for packet in audio_stream.encode():
        container.mux(packet)
    container.close()
