import math
from fractions import Fraction
from pathlib import Path

import av
import av.video.frame
import numpy as np

from videocutter.media import frame_index_at
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
    cancelled = False
    try:
        on_progress(0, frame_count)
        if should_stop():
            cancelled = True
            return False
        for index in range(frame_count):
            frame = _frame_at(document, reference, readers, black, index / output_fps)
            if frame.format.name != pix_fmt:
                frame = frame.reformat(format=pix_fmt)
            # 解码帧带着原素材的帧类型，不清除的话编码器会在原素材的关键帧处强制插入关键帧
            frame.pict_type = av.video.frame.PictureType.NONE
            frame.time_base = frame_time_base
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
            on_progress(index + 1, frame_count)
            if should_stop():
                cancelled = True
                return False
        for packet in stream.encode():
            container.mux(packet)
        return True
    finally:
        container.close()
        for reader in readers.values():
            reader.close()
        if cancelled:
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
    frame = reader.frame(frame_index_at(media.fps, media.frame_count, source_time))
    if frame.height != reference.height or frame.width != reference.width:
        raise RuntimeError(
            f"frame size {frame.width}x{frame.height} does not match "
            f"output size {reference.width}x{reference.height}"
        )
    return frame


class _SourceReader:
    def __init__(self, media: MediaItem) -> None:
        self._path = media.path
        self._fps = media.fps
        self._frame_count = media.frame_count
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
        self._current_index = -1

    def close(self) -> None:
        self._container.close()

    def frame(self, index: int) -> av.VideoFrame:
        if index < 0 or index >= self._frame_count:
            raise RuntimeError(f"frame index {index} outside 0..{self._frame_count - 1}: {self._path}")
        if self._current is not None and index == self._current_index:
            return self._current
        if (
            self._frames is None
            or index < self._current_index
            or index - self._current_index > _SEEK_AHEAD_FRAMES
        ):
            self._seek(index)
        while self._current_index < index:
            decoded = next(self._frames, None)
            if decoded is None:
                raise RuntimeError(f"video ended before frame {index}: {self._path}")
            self._current = decoded
            self._current_index = self._index_of(decoded)
        if self._current_index != index:
            raise RuntimeError(
                f"decoder skipped from frame {index} to {self._current_index}: {self._path}"
            )
        return self._current

    def _seek(self, index: int) -> None:
        offset = self._start + int(math.floor(index / self._fps / self._stream.time_base))
        self._container.seek(offset, stream=self._stream, backward=True)
        self._frames = self._container.decode(self._stream)
        self._current = None
        self._current_index = -1

    def _index_of(self, frame: av.VideoFrame) -> int:
        if frame.pts is None:
            raise RuntimeError(f"decoded frame has no timestamp: {self._path}")
        seconds = float((frame.pts - self._start) * self._stream.time_base)
        return int(round(seconds * self._fps))
