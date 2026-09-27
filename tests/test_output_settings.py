import pytest

from videocutter.model import MediaItem, TimelineDocument
from videocutter.output_settings import (
    RATE_MAX,
    RATE_MIN,
    RATE_SPECIFIED,
    OutputSettings,
    output_rate_status,
    resolve_output_bitrate_kbps,
    resolve_output_fps,
)


def test_default_output_rates_use_the_minimum_segment():
    document = _document()
    settings = OutputSettings()
    assert settings.fps_mode == RATE_MIN
    assert settings.bitrate_mode == RATE_MIN
    assert resolve_output_fps(document, settings) == pytest.approx(10)
    assert resolve_output_bitrate_kbps(document, settings) == pytest.approx(1000)


def test_output_rates_can_use_the_maximum_or_a_specified_value():
    document = _document()
    maximum = OutputSettings(fps_mode=RATE_MAX, bitrate_mode=RATE_MAX)
    assert resolve_output_fps(document, maximum) == pytest.approx(30)
    assert resolve_output_bitrate_kbps(document, maximum) == pytest.approx(8000)
    specified = OutputSettings(
        fps_mode=RATE_SPECIFIED,
        fps_value=24,
        bitrate_mode=RATE_SPECIFIED,
        bitrate_kbps=2500,
    )
    assert resolve_output_fps(document, specified) == pytest.approx(24)
    assert resolve_output_bitrate_kbps(document, specified) == pytest.approx(2500)


def test_missing_segment_bitrate_is_reported_for_min_and_max():
    document = TimelineDocument()
    document.add_media(_media("blank", 10, 0))
    document.place_new_segment("blank", 0, 0, True, 0)
    assert output_rate_status(document, OutputSettings(bitrate_mode=RATE_MIN)) == (
        "无法输出视频：有的轨道片段读不到码率"
    )
    assert output_rate_status(document, OutputSettings(bitrate_mode=RATE_MAX)) == (
        "无法输出视频：有的轨道片段读不到码率"
    )
    assert (
        output_rate_status(document, OutputSettings(bitrate_mode=RATE_SPECIFIED, bitrate_kbps=1500))
        is None
    )
    with pytest.raises(ValueError, match="bitrate"):
        resolve_output_bitrate_kbps(document, OutputSettings(bitrate_mode=RATE_MIN))


def _document() -> TimelineDocument:
    document = TimelineDocument()
    document.add_media(_media("slow", 10, 1000))
    document.add_media(_media("fast", 30, 8000))
    document.add_media(_media("unused", 60, 500))
    document.place_new_segment("slow", 0, 0, True, 0)
    document.place_new_segment("fast", 0, 1, True, 0)
    return document


def _media(media_id: str, fps: float, bitrate_kbps: float) -> MediaItem:
    return MediaItem(
        media_id=media_id,
        path=f"{media_id}.mp4",
        duration_sec=2,
        fps=fps,
        frame_count=int(2 * fps),
        width=16,
        height=16,
        bitrate_kbps=bitrate_kbps,
    )
