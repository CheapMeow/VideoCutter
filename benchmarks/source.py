from fractions import Fraction
from pathlib import Path

import av
import numpy as np


OUTPUT_DIR = Path(__file__).resolve().parent / "output"
WIDTH = 1920
HEIGHT = 1080
FPS = 60
SECONDS = 20
KEYFRAME_INTERVAL = 120
SOURCE_BITRATE = 12_000_000


def source_path() -> Path:
    return OUTPUT_DIR / f"source_{WIDTH}x{HEIGHT}_{FPS}fps_{SECONDS}s.mp4"


def ensure_source() -> Path:
    # 带运动和噪点的 H.264 画面，关键帧间隔 2 秒，接近游戏录屏
    path = source_path()
    if path.exists():
        return path
    OUTPUT_DIR.mkdir(exist_ok=True)
    generator = np.random.default_rng(0)
    gradient = np.linspace(0, 255, WIDTH, dtype=np.float32)
    container = av.open(str(path), mode="w")
    stream = container.add_stream("libx264", rate=Fraction(FPS))
    stream.width = WIDTH
    stream.height = HEIGHT
    stream.pix_fmt = "yuv420p"
    stream.bit_rate = SOURCE_BITRATE
    stream.options = {"g": str(KEYFRAME_INTERVAL), "preset": "veryfast"}
    for index in range(FPS * SECONDS):
        row = np.roll(gradient, index * 8).astype(np.uint8)
        image = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
        image[:, :, 0] = row
        image[:, :, 1] = row[::-1]
        image[:, :, 2] = (index * 3) % 256
        noise = generator.integers(0, 40, (HEIGHT // 4, WIDTH // 4, 1), dtype=np.uint8)
        image += np.repeat(np.repeat(noise, 4, axis=0), 4, axis=1)
        frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        frame.pts = index
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return path
