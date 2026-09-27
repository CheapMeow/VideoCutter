import math
from dataclasses import dataclass

from videocutter.model import TimelineDocument


RATE_SPECIFIED = "specified"
RATE_MAX = "max"
RATE_MIN = "min"


@dataclass
class OutputSettings:
    fps_mode: str = RATE_MIN
    fps_value: float = 30.0
    bitrate_mode: str = RATE_MIN
    bitrate_kbps: float = 8000.0


def resolve_output_fps(document: TimelineDocument, settings: OutputSettings) -> float:
    values = [document.media[segment.media_id].fps for segment in document.all_segments()]
    return _select_rate(settings.fps_mode, settings.fps_value, values, "fps")


def resolve_output_bitrate_kbps(document: TimelineDocument, settings: OutputSettings) -> float:
    values = [
        document.media[segment.media_id].bitrate_kbps for segment in document.all_segments()
    ]
    return _select_rate(settings.bitrate_mode, settings.bitrate_kbps, values, "bitrate")


def output_rate_status(document: TimelineDocument, settings: OutputSettings) -> str | None:
    if settings.bitrate_mode == RATE_SPECIFIED:
        return None
    for segment in document.all_segments():
        bitrate = document.media[segment.media_id].bitrate_kbps
        if not math.isfinite(bitrate) or bitrate <= 0:
            return "无法输出视频：有的轨道片段读不到码率"
    return None


def _select_rate(mode: str, specified: float, values: list[float], name: str) -> float:
    if mode == RATE_SPECIFIED:
        return _require_positive(name, specified)
    if mode not in (RATE_MIN, RATE_MAX):
        raise ValueError(f"unknown {name} mode: {mode}")
    if not values:
        raise RuntimeError("timeline has no video to export")
    checked = [_require_positive(name, value) for value in values]
    if mode == RATE_MIN:
        return min(checked)
    return max(checked)


def _require_positive(name: str, value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value
