import math
import time
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction

import av
import cv2
import numpy as np
from av.codec.hwaccel import HWAccel

from benchmarks.source import FPS, OUTPUT_DIR, SOURCE_BITRATE, ensure_source

SEEK_SAMPLE = 120


def report(label: str, frames: int, elapsed: float, extra: str = "") -> None:
    print(f"{label:<48} {frames / elapsed:8.1f} fps  {elapsed:6.2f} s  {extra}")


def timed(label: str, work) -> None:
    start = time.perf_counter()
    frames = work()
    report(label, frames, time.perf_counter() - start)


def cv2_seek_each() -> int:
    capture = cv2.VideoCapture(str(ensure_source()))
    for index in range(SEEK_SAMPLE):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, _frame = capture.read()
        if not ok:
            raise RuntimeError(f"failed to read frame {index}")
    capture.release()
    return SEEK_SAMPLE


def cv2_sequential() -> int:
    capture = cv2.VideoCapture(str(ensure_source()))
    count = 0
    while True:
        ok, _frame = capture.read()
        if not ok:
            break
        count += 1
    capture.release()
    return count


def pyav_decode(device: str | None, to_bgr: bool) -> int:
    hwaccel = HWAccel(device_type=device) if device is not None else None
    container = av.open(str(ensure_source()), hwaccel=hwaccel)
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    count = 0
    for frame in container.decode(stream):
        if to_bgr:
            frame.to_ndarray(format="bgr24")
        count += 1
    container.close()
    return count


def source_bgr() -> list[np.ndarray]:
    container = av.open(str(ensure_source()))
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    images = [frame.to_ndarray(format="bgr24") for frame in container.decode(stream)]
    container.close()
    return images


def convert_bgr_to_yuv(images: list[np.ndarray]) -> int:
    for image in images:
        av.VideoFrame.from_ndarray(image, format="bgr24").reformat(format="yuv420p")
    return len(images)


def open_encoder(name: str, codec: str, options: dict, width: int, height: int):
    container = av.open(str(OUTPUT_DIR / name), mode="w")
    stream = container.add_stream(codec, rate=Fraction(FPS))
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.bit_rate = SOURCE_BITRATE
    stream.options = options
    return container, stream


def finish(container, stream) -> None:
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def encode_bgr(images: list[np.ndarray], codec: str, options: dict, name: str) -> int:
    height, width = images[0].shape[:2]
    container, stream = open_encoder(name, codec, options, width, height)
    for index, image in enumerate(images):
        frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        frame.pts = index
        for packet in stream.encode(frame):
            container.mux(packet)
    finish(container, stream)
    return len(images)


def transcode_yuv(codec: str, options: dict, name: str, start: int, stop: int) -> int:
    source = av.open(str(ensure_source()))
    stream_in = source.streams.video[0]
    stream_in.thread_type = "AUTO"
    container, stream = open_encoder(name, codec, options, stream_in.width, stream_in.height)
    written = 0
    for index, frame in enumerate(source.decode(stream_in)):
        if index < start:
            continue
        if index >= stop:
            break
        frame.pts = written
        frame.time_base = Fraction(1, FPS)
        frame.pict_type = av.video.frame.PictureType.NONE
        for packet in stream.encode(frame):
            container.mux(packet)
        written += 1
    finish(container, stream)
    source.close()
    return written


def luma_psnr(name: str) -> float:
    source = av.open(str(ensure_source()))
    encoded = av.open(str(OUTPUT_DIR / name))
    total = 0.0
    count = 0
    for original, result in zip(source.decode(video=0), encoded.decode(video=0)):
        a = original.to_ndarray(format="gray").astype(np.float64)
        b = result.to_ndarray(format="gray").astype(np.float64)
        total += float(np.mean((a - b) ** 2))
        count += 1
    source.close()
    encoded.close()
    return 10 * math.log10(255.0 * 255.0 / (total / count))


def yuv_passthrough(label: str, codec: str, options: dict, name: str, frames: int) -> None:
    start = time.perf_counter()
    written = transcode_yuv(codec, options, name, 0, frames)
    elapsed = time.perf_counter() - start
    size_mib = (OUTPUT_DIR / name).stat().st_size / (1024 * 1024)
    report(label, written, elapsed, f"{size_mib:5.1f} MiB  Y PSNR {luma_psnr(name):5.2f} dB")


def parallel_yuv(codec: str, options: dict, workers: int, frames: int) -> int:
    chunk = frames // workers
    with ProcessPoolExecutor(workers) as pool:
        futures = [
            pool.submit(
                transcode_yuv,
                codec,
                options,
                f"part_{codec}_{index}.mp4",
                index * chunk,
                (index + 1) * chunk,
            )
            for index in range(workers)
        ]
        return sum(future.result() for future in futures)


def main() -> None:
    source = ensure_source()
    frames = cv2_sequential()
    print(f"source {source.name}  {frames} frames")
    timed("decode: OpenCV, seek before every frame", cv2_seek_each)
    timed("decode: OpenCV, sequential", cv2_sequential)
    timed("decode: PyAV threads, keep YUV", lambda: pyav_decode(None, False))
    timed("decode: PyAV threads, to BGR", lambda: pyav_decode(None, True))
    timed("decode: PyAV CUDA, keep YUV", lambda: pyav_decode("cuda", False))
    timed("decode: PyAV CUDA, to BGR", lambda: pyav_decode("cuda", True))
    images = source_bgr()
    timed("convert: BGR to yuv420p", lambda: convert_bgr_to_yuv(images))
    timed("encode from BGR: libx264 medium", lambda: encode_bgr(images, "libx264", {}, "bgr_x264.mp4"))
    timed(
        "encode from BGR: h264_nvenc p4",
        lambda: encode_bgr(images, "h264_nvenc", {"preset": "p4"}, "bgr_nvenc_p4.mp4"),
    )
    del images
    yuv_passthrough("YUV pipeline: libx264 medium", "libx264", {}, "yuv_x264_medium.mp4", frames)
    yuv_passthrough(
        "YUV pipeline: libx264 veryfast", "libx264", {"preset": "veryfast"}, "yuv_x264_veryfast.mp4", frames
    )
    for preset in ("p1", "p4", "p7"):
        yuv_passthrough(
            f"YUV pipeline: h264_nvenc {preset}",
            "h264_nvenc",
            {"preset": preset},
            f"yuv_nvenc_{preset}.mp4",
            frames,
        )
    for workers in (2, 4):
        timed(
            f"YUV pipeline, {workers} processes: libx264 medium",
            lambda: parallel_yuv("libx264", {}, workers, frames),
        )
    timed(
        "YUV pipeline, 3 processes: h264_nvenc p4",
        lambda: parallel_yuv("h264_nvenc", {"preset": "p4"}, 3, frames),
    )


if __name__ == "__main__":
    main()
