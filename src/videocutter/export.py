import math
from fractions import Fraction
from pathlib import Path

import av
import av.video.frame
import numpy as np

from videocutter.model import TIME_EPSILON, MediaItem, TimelineDocument
from videocutter.output_settings import (
    OutputSettings,
    resolve_output_bitrate_kbps,
    resolve_output_fps,
)


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


# 往后跳过的帧数不超过这个值时继续顺序解码，超过时重新定位到关键帧
_SEEK_AHEAD_FRAMES = 240
# 把秒换算成时间戳时，补偿浮点误差，避免刚好落在帧边界上时少算一格
_PTS_TICK_EPSILON = 1e-6

_ENCODER_OPTIONS = {
    "h264_nvenc": {"preset": "p1"},
}


def codec_for_suffix(suffix: str) -> str:
    lowered = suffix.lower()
    if lowered in (".mp4", ".mov"):
        return "h264_nvenc"
    if lowered == ".avi":
        return "mjpeg"
    if lowered == ".webm":
        return "libvpx-vp9"
    raise ValueError(f"unsupported export suffix: {suffix}")


def fourcc_for_suffix(suffix: str) -> str:
    lowered = suffix.lower()
    for _label, item_suffix, fourcc in EXPORT_CHOICES:
        if item_suffix == lowered:
            return fourcc
    raise ValueError(f"unsupported export suffix: {suffix}")


def output_path_for_filter(path: str, selected_filter: str) -> str:
    return str(Path(path).with_suffix(suffix_for_filter(selected_filter)))


def export_timeline(
    document: TimelineDocument,
    path: str,
    on_progress,
    should_stop,
    settings: OutputSettings,
) -> bool:
    reference = document.reference_media()
    segments = document.all_segments()
    if reference is None or not segments:
        raise RuntimeError("timeline has no video to export")
    output_fps = resolve_output_fps(document, settings)
    bitrate_kbps = resolve_output_bitrate_kbps(document, settings)
    duration = max(segment.timeline_end for segment in segments)
    frame_count = int(math.floor(duration * output_fps + TIME_EPSILON))
    if frame_count <= 0:
        raise RuntimeError(f"export frame count must be positive, got {frame_count}")
    codec = codec_for_suffix(Path(path).suffix)
    pix_fmt = "yuvj420p" if codec == "mjpeg" else "yuv420p"
    rate = Fraction(output_fps).limit_denominator(1_000_000)
    frame_time_base = 1 / rate
    container = av.open(path, mode="w")
    stream = container.add_stream(codec, rate=rate)
    stream.width = reference.width
    stream.height = reference.height
    stream.pix_fmt = pix_fmt
    stream.bit_rate = int(round(bitrate_kbps * 1000))
    stream.options = _ENCODER_OPTIONS.get(codec, {})
    black = av.VideoFrame.from_ndarray(
        np.zeros((reference.height, reference.width, 3), dtype=np.uint8), format="bgr24"
    ).reformat(format=pix_fmt)
    readers: dict[str, _SourceReader] = {}
    completed = False
    try:
        on_progress(0, frame_count)
        if should_stop():
            return False
        for index in range(frame_count):
            frame = _encoder_frame(
                _frame_at(document, reference, readers, black, index / output_fps),
                pix_fmt,
            )
            # 解码帧带着原素材的帧类型，不清除的话编码器会在原素材的关键帧处强制插入关键帧
            frame.pict_type = av.video.frame.PictureType.NONE
            frame.time_base = frame_time_base
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
            on_progress(index + 1, frame_count)
            if should_stop():
                return False
        for packet in stream.encode():
            container.mux(packet)
        completed = True
        return True
    finally:
        container.close()
        for reader in readers.values():
            reader.close()
        if not completed:
            Path(path).unlink(missing_ok=True)


def _frame_at(
    document: TimelineDocument,
    reference: MediaItem,
    readers: dict[str, "_SourceReader"],
    black: av.VideoFrame,
    time_sec: float,
) -> av.VideoFrame:
    segment = document.top_segment_at(time_sec)
    if segment is None:
        return black
    media = document.media[segment.media_id]
    source_time = segment.source_in + (time_sec - segment.timeline_start)
    reader = readers.get(media.path)
    if reader is None:
        reader = _SourceReader(media)
        readers[media.path] = reader
    frame = reader.frame_at(source_time)
    if frame.height != reference.height or frame.width != reference.width:
        raise RuntimeError(
            f"frame size {frame.width}x{frame.height} does not match "
            f"output size {reference.width}x{reference.height}"
        )
    return frame


def _encoder_frame(frame: av.VideoFrame, pix_fmt: str) -> av.VideoFrame:
    # 像素格式不同时，reformat 会生成新帧。格式相同则它返回原帧，编码器改写时间戳会碰到解码器还要复用的那一帧。
    if frame.format.name != pix_fmt:
        return frame.reformat(format=pix_fmt)
    owned = av.VideoFrame(frame.width, frame.height, pix_fmt)
    owned.colorspace = frame.colorspace
    owned.color_range = frame.color_range
    owned.color_trc = frame.color_trc
    owned.color_primaries = frame.color_primaries
    for source, target in zip(frame.planes, owned.planes, strict=True):
        _copy_plane(source, target)
    return owned


def _copy_plane(source, target) -> None:
    if source.height != target.height:
        raise RuntimeError(f"plane height {source.height} does not match destination {target.height}")
    if source.buffer_size == target.buffer_size:
        target.update(source)
        return
    row_bytes = min(source.line_size, target.line_size)
    if row_bytes <= 0:
        raise RuntimeError(f"plane row size must be positive, got {row_bytes}")
    source_view = memoryview(source).cast("B")
    target_view = memoryview(target).cast("B")
    for row in range(source.height):
        source_start = row * source.line_size
        target_start = row * target.line_size
        target_view[target_start : target_start + row_bytes] = source_view[
            source_start : source_start + row_bytes
        ]


class _SourceReader:
    def __init__(self, media: MediaItem) -> None:
        self._path = media.path
        self._fps = media.fps
        self._container = av.open(media.path)
        if not self._container.streams.video:
            self._container.close()
            raise RuntimeError(f"no video stream: {media.path}")
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"
        if self._stream.time_base is None:
            self._container.close()
            raise RuntimeError(f"video stream has no time base: {media.path}")
        self._start = self._stream.start_time or 0
        self._frames = None
        self._current: av.VideoFrame | None = None
        self._current_pts: int | None = None
        self._upcoming: av.VideoFrame | None = None
        self._upcoming_pts: int | None = None
        self._exhausted = False

    def close(self) -> None:
        self._container.close()

    def frame_at(self, time_sec: float) -> av.VideoFrame:
        # 这一时刻画面上的帧，是时间戳不晚于该时刻的最后一帧。录像的帧间隔不均匀时，不能按平均帧率换算帧号。
        target = self._pts_for(time_sec)
        if self._must_seek(target):
            self._seek(target)
        return self._advance_to(target)

    def _pts_for(self, time_sec: float) -> int:
        if time_sec < 0:
            raise RuntimeError(f"source time must be non-negative, got {time_sec}: {self._path}")
        base = self._stream.time_base
        ticks = time_sec * base.denominator / base.numerator
        return self._start + int(math.floor(ticks + _PTS_TICK_EPSILON))

    def _must_seek(self, target: int) -> bool:
        if self._frames is None or self._current_pts is None:
            return True
        if target < self._current_pts:
            return True
        gap_sec = (target - self._current_pts) * float(self._stream.time_base)
        return gap_sec * self._fps > _SEEK_AHEAD_FRAMES

    def _seek(self, target: int) -> None:
        self._container.seek(target, stream=self._stream, backward=True)
        self._frames = self._container.decode(self._stream)
        self._current = None
        self._current_pts = None
        self._upcoming = None
        self._upcoming_pts = None
        self._exhausted = False

    def _advance_to(self, target: int) -> av.VideoFrame:
        while True:
            self._pull()
            if self._upcoming is None or self._upcoming_pts > target:
                break
            self._current = self._upcoming
            self._current_pts = self._upcoming_pts
            self._upcoming = None
            self._upcoming_pts = None
        if self._current is None:
            if self._upcoming is None:
                raise RuntimeError(f"no frame at timestamp {target}: {self._path}")
            self._current = self._upcoming
            self._current_pts = self._upcoming_pts
            self._upcoming = None
            self._upcoming_pts = None
        return self._current

    def _pull(self) -> None:
        if self._upcoming is not None or self._exhausted:
            return
        decoded = next(self._frames, None)
        if decoded is None:
            self._exhausted = True
            return
        if decoded.pts is None:
            raise RuntimeError(f"decoded frame has no timestamp: {self._path}")
        if self._current_pts is not None and decoded.pts < self._current_pts:
            raise RuntimeError(
                f"decoded frame timestamp went backwards to {decoded.pts}: {self._path}"
            )
        self._upcoming = decoded
        self._upcoming_pts = decoded.pts
