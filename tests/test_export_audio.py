import math

import av
import numpy as np
import pytest

from tests.support import write_tone_video
import cv2

from videocutter.export import export_timeline
from videocutter.output_settings import RATE_SPECIFIED, OutputSettings
from videocutter.model import TIME_EPSILON, MediaItem, Segment, TimelineDocument, new_id


def add_tone_video(document: TimelineDocument, path, frame_count: int, fps: int, frequency_hz: float):
    write_tone_video(path, frame_count=frame_count, fps=fps, frequency_hz=frequency_hz)
    probe = av.open(str(path))
    video_stream = probe.streams.video[0]
    audio_stream = probe.streams.audio[0]
    item = MediaItem(
        media_id=new_id(),
        path=str(path),
        duration_sec=frame_count / fps,
        fps=float(video_stream.average_rate),
        frame_count=frame_count,
        width=160,
        height=90,
        bitrate_kbps=8000.0,
    )
    document.add_media(item)
    probe.close()
    return item, float(audio_stream.rate), frequency_hz


def read_rms_series(path, segment: Segment, hop_sec: float = 0.02):
    container = av.open(str(path))
    audio_stream = container.streams.audio[0]
    rate = audio_stream.sample_rate
    frames = []
    for frame in container.decode(audio=0):
        frames.append(frame.to_ndarray())
    container.close()
    data = np.concatenate(frames, axis=1)
    samples = []
    positions = np.arange(segment.timeline_start + hop_sec / 2, segment.timeline_end, hop_sec)
    for position in positions:
        start = int(position * rate)
        window = data[:, start : start + int(hop_sec * rate)]
        samples.append(float(np.sqrt(np.mean(window.astype(np.float64) ** 2))))
    return positions, np.array(samples)


def dominant_frequency(path, start_sec: float, end_sec: float) -> float:
    container = av.open(str(path))
    audio_stream = container.streams.audio[0]
    rate = audio_stream.sample_rate
    frames = []
    for frame in container.decode(audio=0):
        frames.append(frame.to_ndarray())
    container.close()
    data = np.concatenate(frames, axis=1)
    window = data[0, int(start_sec * rate) : int(end_sec * rate)]
    spectrum = np.abs(np.fft.rfft(window))
    frequency = float(np.argmax(spectrum)) * rate / len(window)
    return frequency


def test_export_writes_audio_from_the_top_segment(tmp_path):
    document = TimelineDocument()
    clip, _rate, frequency_hz = add_tone_video(document, tmp_path / "clip.mp4", 8, 10, 440.0)
    document.place_new_segment(clip.media_id, 0, 0, True, 0)
    output = tmp_path / "out.mp4"
    assert export_timeline(
        document,
        str(output),
        lambda _written, _total: None,
        lambda: False,
        OutputSettings(),
    )
    container = av.open(str(output))
    audio_streams = list(container.streams.audio)
    audio_codec = audio_streams[0].codec_context.name if audio_streams else None
    container.close()
    assert len(audio_streams) == 1
    assert audio_codec == "aac"
    positions, rms = read_rms_series(
        output, Segment(new_id(), clip.media_id, 0.0, 0.0, clip.duration_sec)
    )
    assert len(rms) == len(positions)
    assert float(np.max(rms)) > 0.1
    assert float(np.mean(rms)) > 0.1
    measured = dominant_frequency(output, 0.1, 0.7)
    assert measured == pytest.approx(frequency_hz, rel=0.05)


def test_export_audio_follows_segment_cuts_and_gaps(tmp_path):
    document = TimelineDocument()
    clip, _rate, _frequency = add_tone_video(document, tmp_path / "clip.mp4", 40, 10, 440.0)
    document.tracks = [
        [
            Segment(new_id(), clip.media_id, 0.0, 0.0, 1.0),
            Segment(new_id(), clip.media_id, 2.0, 2.0, 3.0),
        ]
    ]
    document.reference_media_id = clip.media_id
    output = tmp_path / "out.mp4"
    settings = OutputSettings(
        fps_mode=RATE_SPECIFIED,
        fps_value=10,
        bitrate_mode=RATE_SPECIFIED,
        bitrate_kbps=8000,
    )
    assert export_timeline(
        document,
        str(output),
        lambda _written, _total: None,
        lambda: False,
        settings,
    )
    positions, rms = read_rms_series(output, Segment(new_id(), clip.media_id, 0.0, 0.0, 3.0))
    voice = rms[positions < 1.0 - 1e-6]
    silent = rms[(positions > 1.2) & (positions < 1.8)]
    restored = rms[positions > 2.2]
    assert float(np.max(voice)) > 0.1
    assert float(np.max(silent)) < 0.005
    assert float(np.max(restored)) > 0.1
    assert math.ceil(3.0 * 48000) <= 48000 * 3 + 2048


def test_export_audio_without_any_audio_sources_still_writes_silence(tmp_path):
    document = TimelineDocument()
    clip = tmp_path / "silent.mp4"
    write_tone_video(clip, frame_count=8, fps=10, frequency_hz=440.0)
    container = av.open(str(clip))
    has_source_audio = bool(list(container.streams.audio))
    container.close()
    item = MediaItem(
        media_id=new_id(),
        path=str(clip),
        duration_sec=0.8,
        fps=10.0,
        frame_count=8,
        width=160,
        height=90,
        bitrate_kbps=8000.0,
    )
    document.add_media(item)
    document.tracks = [[Segment(new_id(), item.media_id, 0.0, 0.0, 0.8)]]
    document.reference_media_id = item.media_id
    assert has_source_audio
    output = tmp_path / "out.mp4"
    assert export_timeline(
        document,
        str(output),
        lambda _written, _total: None,
        lambda: False,
        OutputSettings(),
    )
    container = av.open(str(output))
    audio_streams = list(container.streams.audio)
    container.close()
    assert len(audio_streams) == 1
