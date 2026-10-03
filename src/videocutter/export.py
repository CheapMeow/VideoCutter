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

# 往后跳过的帧数不超过这个值时继续顺序解码，超过时重新定位到关键帧
_SEEK_AHEAD_FRAMES = 240
# 把角换算成时间戳时，补偿浮点误差，避免刚好落在帧边界上时少算一帧
_PTS_TICK_EPSILON = 1e-6

_ENCODER_OPTIONS = {
    "h264_nvenc": {"preset": "p1"},
}

# 导出音频统一重采样到这个采样率，多段素材混排时各段的音频参数保持一致
_AUDIO_RATE = 48000
_AUDIO_LAYOUT = "stereo"
# AAC/Opus 用平面浮点格式，PCM 用交错有符号 16 位格式
_AUDIO_FORMAT_FLOAT = "fltp"
_AUDIO_FORMAT_S16 = "s16"
_AUDIO_CHANNELS = 2
# AAC 编码器单次编码的采样点数由编码器决定，写满这个长度的帧再交给编码器
_AUDIO_SAMPLES_PER_FRAME = 1024


def _mux(container, stream, frame=None) -> None:
    packets = stream.encode() if frame is None else stream.encode(frame)
    for packet in packets:
        container.mux(packet)

def codec_for_suffix(suffix: str) -> str:
    lowered = suffix.lower()
    if lowered in (".mp4", ".mov"):
        return "h264_nvenc"
    if lowered == ".avi":
        return "mjpeg"
    if lowered == ".webm":
        return "libvpx-vp9"
    raise ValueError(f"unsupported export suffix: {suffix}")

def _open_source(path: str) -> av.container.InputContainer:
    container = av.open(path)
    if not container.streams.video:
        container.close()
        raise RuntimeError(f"no video stream: {path}")
    return container

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
    suffix = Path(path).suffix.lower()
    container = av.open(path, mode="w")
    stream = container.add_stream(codec, rate=rate)
    stream.width = reference.width
    stream.height = reference.height
    stream.pix_fmt = pix_fmt
    stream.bit_rate = int(round(bitrate_kbps * 1000))
    stream.options = _ENCODER_OPTIONS.get(codec, {})
    # AVI 容器写入 AAC 音频会让视频流声明帧数偏多、pts 出现空洞（FFmpeg AVI muxer 的
    # 副作用），导致按帧号 seek 的播放器读错帧；AVI 原生音频格式是 PCM，没有这个问题。
    # webm 容器不支持 AAC，使用 Opus。
    if suffix == ".avi":
        audio_codec = "pcm_s16le"
        audio_format = _AUDIO_FORMAT_S16
    elif suffix == ".webm":
        audio_codec = "libopus"
        audio_format = _AUDIO_FORMAT_FLOAT
    else:
        audio_codec = "aac"
        audio_format = _AUDIO_FORMAT_FLOAT
    audio_stream = container.add_stream(audio_codec, rate=_AUDIO_RATE)
    audio_stream.layout = _AUDIO_LAYOUT
    audio_stream.bit_rate = 128_000
    audio_sources = _AudioSources(document, duration)
    audio_stream.codec_context.sample_rate = _AUDIO_RATE
    black = av.VideoFrame.from_ndarray(
        np.zeros((reference.height, reference.width, 3), dtype=np.uint8), format="bgr24"
    ).reformat(format=pix_fmt)
    readers: dict[str, _SourceReader] = {}
    audio_reader: _AudioReader | None = None
    audio_writer: _AudioWriter | None = None
    completed = False
    try:
        on_progress(0, frame_count)
        if should_stop():
            return False
        if audio_sources.segments:
            audio_reader = _AudioReader(audio_sources, _AUDIO_RATE)
            audio_writer = _AudioWriter(audio_stream, container, audio_format)
        for index in range(frame_count):
            frame = _encoder_frame(
                _frame_at(document, reference, readers, black, index / output_fps),
                pix_fmt,
            )
            # 解码帧带着原素材的帧类型，不清除的话编码器会在原素材的关键帧处强制插入关键帧
            frame.pict_type = av.video.frame.PictureType.NONE
            frame.time_base = frame_time_base
            frame.pts = index
            _mux(container, stream, frame)
            on_progress(index + 1, frame_count)
            if should_stop():
                return False
        if audio_writer is not None:
            audio_writer.drain(audio_reader)
        _mux(container, stream)
        if audio_writer is not None:
            audio_writer.flush()
        completed = True
        return True
    finally:
        container.close()
        for reader in readers.values():
            reader.close()
        if audio_reader is not None:
            audio_reader.close()
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

class _AudioSources:
    def __init__(self, document: TimelineDocument, duration: float) -> None:
        self.duration = duration
        # 按开始时间排序后做相邻去重，两段素材同刻相接时只保留前一段的结束边界
        ordered = sorted(document.all_segments(), key=lambda item: (item.timeline_start, item.source_in))
        self.segments: list[_AudioSourceSegment] = []
        for segment in ordered:
            start = max(0.0, segment.timeline_start)
            end = min(self.duration, segment.timeline_end)
            if end - start <= TIME_EPSILON:
                continue
            if self.segments and end - self.segments[-1].end <= TIME_EPSILON:
                self.segments[-1].end = end
                continue
            media = document.media[segment.media_id]
            self.segments.append(
                _AudioSourceSegment(
                    path=media.path,
                    source_start=segment.source_in + (start - segment.timeline_start),
                    start=start,
                    end=end,
                )
            )

class _AudioSourceSegment:
    def __init__(self, path: str, source_start: float, start: float, end: float) -> None:
        self.path = path
        self.source_start = source_start
        self.start = start
        self.end = end

class _AudioReader:
    def __init__(self, sources: _AudioSources, output_rate: int) -> None:
        self._sources = sources.segments
        self._duration = sources.duration
        self._output_rate = output_rate
        self._resampler = av.AudioResampler(format=_AUDIO_FORMAT_FLOAT, layout=_AUDIO_LAYOUT, rate=output_rate)
        self._source_index = 0
        self._next_output_pos = 0.0
        self._container: av.container.InputContainer | None = None
        self._stream: av.audio.stream.AudioStream | None = None
        self._frames = None
        self._exhausted = True
        self._current_has_no_audio = False

    def close(self) -> None:
        if self._container is not None:
            self._container.close()
            self._container = None
            self._stream = None

    def _seek_source(self, path: str, source_time: float, output_pos: float) -> bool:
        self.close()
        self._next_output_pos = output_pos
        try:
            self._container = _open_source(path)
        except RuntimeError:
            return False
        audio_streams = list(self._container.streams.audio)
        if not audio_streams:
            self.close()
            return False
        self._stream = audio_streams[0]
        self._resampler = av.AudioResampler(format=_AUDIO_FORMAT_FLOAT, layout=_AUDIO_LAYOUT, rate=self._output_rate)
        try:
            self._container.seek(
                int(source_time / self._stream.time_base),
                stream=self._stream,
                backward=True,
                any_frame=False,
            )
        except av.AVError:
            self.close()
            return False
        self._frames = self._container.decode(self._stream)
        self._exhausted = False
        return True

    def samples(self, count: int) -> list[av.AudioFrame]:
        if count <= 0:
            raise RuntimeError(f"sample count must be positive, got {count}")
        collected: list[av.AudioFrame] = []
        remaining = count
        while remaining > 0:
            if self._source_index >= len(self._sources):
                rest = int(math.ceil((self._duration - self._next_output_pos) * self._output_rate - 1e-6))
                if rest <= 0:
                    break
                take = min(remaining, rest)
                collected.append(_silence_frame(take))
                self._next_output_pos += take / self._output_rate
                remaining -= take
                continue
            source = self._sources[self._source_index]
            if self._next_output_pos + TIME_EPSILON < source.start:
                # 轨道上的空隙：输出静音补齐，保证音画对齐
                gap = int(math.ceil((source.start - self._next_output_pos) * self._output_rate - 1e-6))
                take = min(remaining, max(gap, 1))
                collected.append(_silence_frame(take))
                self._next_output_pos += take / self._output_rate
                remaining -= take
                continue
            if self._next_output_pos + TIME_EPSILON >= source.end:
                self._advance_source()
                continue
            if self._current_has_no_audio:
                rest = int(math.ceil((source.end - self._next_output_pos) * self._output_rate - 1e-6))
                take = min(remaining, max(rest, 1))
                collected.append(_silence_frame(take))
                self._next_output_pos += take / self._output_rate
                remaining -= take
                continue
            if self._exhausted and not self._seek_source(
                source.path,
                source.source_start + max(0.0, self._next_output_pos - source.start),
                self._next_output_pos,
            ):
                self._current_has_no_audio = True
                continue
            resampled = self._pull_resampled()
            if resampled is None:
                # 当前源解码耗尽：这段素材的音频到此为止，推进下一段
                self._advance_source()
                continue
            sample_count = resampled.samples
            keep_start = max(
                0, int(math.floor((source.start - self._next_output_pos) * self._output_rate + 1e-6))
            )
            keep_end = sample_count
            if keep_end <= keep_start:
                self._advance_source()
                continue
            if keep_start > 0 or keep_end < sample_count:
                resampled = _trim_audio_frame(resampled, keep_start, keep_end)
                sample_count = resampled.samples
            collected.append(resampled)
            self._next_output_pos += sample_count / self._output_rate
            remaining -= sample_count
        return collected

    def _advance_source(self) -> None:
        self._source_index += 1
        self._current_has_no_audio = False
        self._exhausted = True

    def _pull_resampled(self) -> av.AudioFrame | None:
        while True:
            if self._exhausted or self._frames is None:
                return None
            decoded = next(self._frames, None)
            if decoded is None:
                self._exhausted = True
                flushed = self._resampler.resample(None)
                frames = flushed if isinstance(flushed, list) else [flushed]
                if not frames:
                    return None
                merged = frames[0]
                if len(frames) > 1:
                    merged = _concat_audio_frames(frames)
                return _sanitize_audio_frame(merged)
            if decoded.pts is None:
                continue
            output = self._resampler.resample(decoded)
            frames = output if isinstance(output, list) else [output]
            if not frames:
                continue
            merged = frames[0]
            if len(frames) > 1:
                merged = _concat_audio_frames(frames)
            return _sanitize_audio_frame(merged)

def _sanitize_audio_frame(frame: av.AudioFrame) -> av.AudioFrame:
    data = frame.to_ndarray()
    if not np.isfinite(data).all() or float(np.abs(data).max(initial=0.0)) > 1.0:
        data = np.where(np.isfinite(data) & (np.abs(data) <= 1.0), data, 0.0).astype(np.float32)
    clean = av.AudioFrame.from_ndarray(np.ascontiguousarray(data), format=frame.format.name, layout=frame.layout.name)
    clean.sample_rate = frame.sample_rate
    return clean

def _silence_frame(samples: int) -> av.AudioFrame:
    frame = av.AudioFrame(samples=samples, layout=_AUDIO_LAYOUT, format=_AUDIO_FORMAT_FLOAT)
    frame.sample_rate = _AUDIO_RATE
    # AudioFrame 构造出的缓冲区未初始化，必须显式清零
    for plane in frame.planes:
        plane.update(bytes(plane.buffer_size))
    return frame

def _trim_audio_frame(frame: av.AudioFrame, start: int, end: int) -> av.AudioFrame:
    rate = frame.sample_rate
    data = frame.to_ndarray()  # shape: (channels, samples)，fltp 平面格式
    trimmed = np.ascontiguousarray(data[:, start:end])
    trimmed_frame = av.AudioFrame.from_ndarray(trimmed, format=frame.format.name, layout=frame.layout.name)
    trimmed_frame.sample_rate = rate
    return trimmed_frame

def _concat_audio_frames(frames: list[av.AudioFrame]) -> av.AudioFrame:
    arrays = [frame.to_ndarray() for frame in frames]
    data = np.concatenate(arrays, axis=1)
    merged = av.AudioFrame.from_ndarray(data, format=frames[0].format.name, layout=frames[0].layout.name)
    merged.sample_rate = frames[0].sample_rate
    return merged

class _AudioWriter:
    def __init__(
        self,
        stream: av.audio.stream.AudioStream,
        container,
        sample_format: str,
    ) -> None:
        self._stream = stream
        self._container = container
        self._sample_format = sample_format
        self._pts = 0

    def _make_frame(self, samples: int) -> av.AudioFrame:
        frame = av.AudioFrame(samples=samples, layout=_AUDIO_LAYOUT, format=self._sample_format)
        frame.sample_rate = _AUDIO_RATE
        return frame

    def write(self, frames: list[av.AudioFrame]) -> None:
        pending = list(frames)
        while pending:
            frame = pending.pop(0)
            # 一律重建输出帧：输入帧可能来自重采样器（pts 为 None），
            # pts 必须由写入器的连续计数器独占管理
            data = frame.to_ndarray()  # 平面格式 shape: (channels, samples)；s16 交错 shape: (1, samples*channels)
            if data.ndim == 1 or data.shape[0] == 1:
                data = data.reshape(-1, _AUDIO_CHANNELS).T
            if self._sample_format == _AUDIO_FORMAT_S16:
                # 重采样器输出浮点采样，PCM s16 需要转换成 int16
                data = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
            offset = 0
            while offset < frame.samples:
                take = min(_AUDIO_SAMPLES_PER_FRAME, frame.samples - offset)
                out = self._make_frame(take)
                if self._sample_format == _AUDIO_FORMAT_S16:
                    # s16 是交错格式只有单个 plane：按 L,R,L,R 交错写满整个缓冲区
                    interleaved = np.ascontiguousarray(data[:, offset : offset + take].T.reshape(-1))
                    out.planes[0].update(interleaved.tobytes())
                else:
                    for channel in range(_AUDIO_CHANNELS):
                        out.planes[channel].update(
                            np.ascontiguousarray(data[channel, offset : offset + take]).tobytes()
                        )
                self._emit(out)
                offset += take

    def _emit(self, frame: av.AudioFrame) -> None:
        frame.pts = self._pts
        self._pts += frame.samples
        _mux(self._container, self._stream, frame)

    def drain(self, reader: _AudioReader) -> None:
        while True:
            frames = reader.samples(_AUDIO_SAMPLES_PER_FRAME)
            if not frames:
                return
            self.write(frames)

    def flush(self) -> None:
        _mux(self._container, self._stream)

class _SourceReader:
    def __init__(self, media: MediaItem) -> None:
        self._path = media.path
        self._fps = media.fps
        self._container = _open_source(media.path)
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