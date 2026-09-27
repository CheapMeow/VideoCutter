from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass


TIME_EPSILON = 1e-6


@dataclass
class MediaItem:
    media_id: str
    path: str
    duration_sec: float
    fps: float
    frame_count: int
    width: int
    height: int
    bitrate_kbps: float


@dataclass
class Segment:
    segment_id: str
    media_id: str
    timeline_start: float
    source_in: float
    source_out: float

    @property
    def duration(self) -> float:
        return self.source_out - self.source_in

    @property
    def timeline_end(self) -> float:
        return self.timeline_start + self.duration


def new_id() -> str:
    return uuid.uuid4().hex


def _require_finite(name: str, value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    return value


def merged_intervals(segments: list[Segment], exclude_id: str | None) -> list[list[float]]:
    intervals: list[list[float]] = []
    for segment in segments:
        if segment.segment_id == exclude_id:
            continue
        intervals.append([segment.timeline_start, segment.timeline_end])
    intervals.sort(key=lambda item: item[0])
    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + TIME_EPSILON:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def valid_start_ranges(
    duration: float,
    segments: list[Segment],
    exclude_id: str | None,
) -> list[tuple[float, float]]:
    duration = _require_finite("duration", duration)
    if duration <= 0:
        raise ValueError(f"segment duration must be positive, got {duration}")
    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in merged_intervals(segments, exclude_id):
        high = start - duration
        if high + TIME_EPSILON >= cursor:
            ranges.append((cursor, max(cursor, high)))
        cursor = max(cursor, end)
    ranges.append((cursor, math.inf))
    return ranges


def _range_contains(ranges: list[tuple[float, float]], value: float) -> bool:
    for low, high in ranges:
        if low - TIME_EPSILON <= value <= high + TIME_EPSILON:
            return True
    return False


def clamp_start(desired: float, ranges: list[tuple[float, float]]) -> float:
    desired = max(0.0, desired)
    best_value: float | None = None
    best_distance: float | None = None
    for low, high in ranges:
        if low - TIME_EPSILON <= desired <= high + TIME_EPSILON:
            upper = desired if math.isinf(high) else min(desired, high)
            return max(low, upper)
        candidate = low if desired < low else high
        distance = abs(candidate - desired)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_value = candidate
    if best_value is None:
        raise RuntimeError("no valid placement range")
    return max(0.0, best_value)


def resolve_timeline_start(
    duration: float,
    desired_start: float,
    track_segments: list[Segment],
    exclude_id: str | None,
    snap_threshold: float,
    snap_segments: list[Segment],
) -> float:
    desired_start = max(0.0, _require_finite("desired start", desired_start))
    snap_threshold = _require_finite("snap threshold", snap_threshold)
    if snap_threshold < 0:
        raise ValueError(f"snap threshold must be non-negative, got {snap_threshold}")
    ranges = valid_start_ranges(duration, track_segments, exclude_id)
    snapped: float | None = None
    best_distance: float | None = None
    for other in snap_segments:
        if other.segment_id == exclude_id:
            continue
        # 只把正在移动的段落首尾接到其他段落的尾首，使两段贴在一起。
        for target in (other.timeline_end, other.timeline_start - duration):
            if target < -TIME_EPSILON:
                continue
            target = max(0.0, target)
            if not _range_contains(ranges, target):
                continue
            distance = abs(target - desired_start)
            if distance < snap_threshold:
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    snapped = target
    if snapped is not None:
        return snapped
    return clamp_start(desired_start, ranges)


def contains_time(segment: Segment, time_sec: float) -> bool:
    return segment.timeline_start <= time_sec < segment.timeline_end


def split_segment(segment: Segment, time_sec: float) -> tuple[Segment, Segment] | None:
    if not (
        segment.timeline_start + TIME_EPSILON
        < time_sec
        < segment.timeline_end - TIME_EPSILON
    ):
        return None
    offset = time_sec - segment.timeline_start
    left = Segment(
        segment_id=segment.segment_id,
        media_id=segment.media_id,
        timeline_start=segment.timeline_start,
        source_in=segment.source_in,
        source_out=segment.source_in + offset,
    )
    right = Segment(
        segment_id=new_id(),
        media_id=segment.media_id,
        timeline_start=time_sec,
        source_in=segment.source_in + offset,
        source_out=segment.source_out,
    )
    return left, right


class TimelineDocument:
    def __init__(self) -> None:
        self.media: dict[str, MediaItem] = {}
        self.tracks: list[list[Segment]] = []
        self.playhead = 0.0
        self.selected_segment_id: str | None = None
        # 第一个放进轨道的素材。输出视频的宽高用它。
        self.reference_media_id: str | None = None
        self._drag_base: list[list[Segment]] | None = None
        self._drag_original: list[list[Segment]] | None = None
        self._drag_segment: Segment | None = None

    def add_media(self, item: MediaItem) -> None:
        if item.media_id in self.media:
            raise ValueError(f"duplicate media id: {item.media_id}")
        if item.duration_sec <= 0:
            raise ValueError(f"media duration must be positive: {item.path}")
        if item.fps <= 0 or item.frame_count <= 0:
            raise ValueError(f"invalid media metadata: {item.path}")
        if not math.isfinite(item.bitrate_kbps) or item.bitrate_kbps < 0:
            raise ValueError(f"invalid media bitrate: {item.path}")
        self.media[item.media_id] = item

    def all_segments(self) -> list[Segment]:
        result: list[Segment] = []
        for track in self.tracks:
            result.extend(track)
        return result

    def latest_material_time(self) -> float:
        # 素材最后一帧的时间，以及轨道上段落最后一帧所在的时间，取更晚的一个。
        latest = 0.0
        for item in self.media.values():
            latest = max(latest, item.duration_sec)
        for segment in self.all_segments():
            latest = max(latest, segment.timeline_end)
        return latest

    def find_segment(self, segment_id: str) -> tuple[int, Segment]:
        for index, track in enumerate(self.tracks):
            for segment in track:
                if segment.segment_id == segment_id:
                    return index, segment
        raise KeyError(segment_id)

    def drag_base_track_count(self) -> int | None:
        if self._drag_base is None:
            return None
        return len(self._drag_base)

    def place_new_segment(
        self,
        media_id: str,
        desired_start: float,
        track_index: int,
        insert_track: bool,
        snap_threshold: float,
    ) -> Segment:
        if self._drag_segment is not None:
            raise RuntimeError("cannot place a segment while dragging")
        item = self.media[media_id]
        self._require_output_size(item)
        segment = Segment(
            segment_id=new_id(),
            media_id=media_id,
            timeline_start=0.0,
            source_in=0.0,
            source_out=item.duration_sec,
        )
        self._place(segment, desired_start, track_index, insert_track, snap_threshold)
        if self.reference_media_id is None:
            self.reference_media_id = media_id
        return segment

    def begin_segment_drag(self, segment_id: str) -> Segment:
        if self._drag_segment is not None:
            raise RuntimeError("a segment drag is already active")
        track_index, segment = self.find_segment(segment_id)
        self._drag_original = copy.deepcopy(self.tracks)
        self.tracks[track_index] = [
            item for item in self.tracks[track_index] if item.segment_id != segment_id
        ]
        self._drag_base = copy.deepcopy(self.tracks)
        self._drag_segment = segment
        return segment

    def update_segment_drag(
        self,
        desired_start: float,
        track_index: int,
        insert_track: bool,
        snap_threshold: float,
    ) -> None:
        if self._drag_segment is None or self._drag_base is None:
            raise RuntimeError("no segment drag is active")
        segment = copy.deepcopy(self._drag_segment)
        self.tracks = copy.deepcopy(self._drag_base)
        self._place(segment, desired_start, track_index, insert_track, snap_threshold)

    def end_segment_drag(self) -> None:
        if self._drag_segment is None:
            raise RuntimeError("no segment drag is active")
        segment_id = self._drag_segment.segment_id
        self.tracks = [track for track in self.tracks if track]
        self._clear_drag()
        placed = any(
            segment.segment_id == segment_id
            for track in self.tracks
            for segment in track
        )
        if not placed:
            raise RuntimeError(f"drag ended without a placed segment: {segment_id}")

    def cancel_segment_drag(self) -> None:
        if self._drag_original is None:
            raise RuntimeError("no segment drag is active")
        self.tracks = self._drag_original
        self._clear_drag()

    def select_segment(self, segment_id: str | None) -> None:
        if segment_id is not None:
            self.find_segment(segment_id)
        self.selected_segment_id = segment_id

    def delete_segment(self, segment_id: str) -> None:
        if self._drag_segment is not None:
            raise RuntimeError("cannot delete a segment while dragging")
        track_index, _segment = self.find_segment(segment_id)
        self.tracks[track_index] = [
            item for item in self.tracks[track_index] if item.segment_id != segment_id
        ]
        self.tracks = [track for track in self.tracks if track]
        if self.selected_segment_id == segment_id:
            self.selected_segment_id = None
        if not self.all_segments():
            self.reference_media_id = None

    def set_playhead(self, time_sec: float) -> None:
        time_sec = _require_finite("playhead", time_sec)
        self.playhead = max(0.0, time_sec)

    def split_selected(self) -> tuple[Segment, Segment] | None:
        # 只分割当前选中的那一段，并且当前帧必须落在这段内部。
        if self._drag_segment is not None:
            raise RuntimeError("cannot split while dragging a segment")
        if self.selected_segment_id is None:
            return None
        track_index, segment = self.find_segment(self.selected_segment_id)
        pair = split_segment(segment, self.playhead)
        if pair is None:
            return None
        track = self.tracks[track_index]
        index = next(
            item_index
            for item_index, item in enumerate(track)
            if item.segment_id == segment.segment_id
        )
        track[index : index + 1] = [pair[0], pair[1]]
        return pair

    def reference_media(self) -> MediaItem | None:
        if self.reference_media_id is None:
            return None
        return self.media[self.reference_media_id]

    def top_segment_at(self, time_sec: float) -> Segment | None:
        for track in self.tracks:
            for segment in track:
                if contains_time(segment, time_sec):
                    return segment
        return None

    def top_segment_at_playhead(self) -> Segment | None:
        return self.top_segment_at(self.playhead)

    def source_time_at_playhead(self) -> tuple[MediaItem, float] | None:
        segment = self.top_segment_at_playhead()
        if segment is None:
            return None
        source_time = segment.source_in + (self.playhead - segment.timeline_start)
        return self.media[segment.media_id], source_time

    def _require_output_size(self, item: MediaItem) -> None:
        if self.all_segments():
            if self.reference_media_id is None:
                raise RuntimeError("timeline segments exist without an output size")
        elif self.reference_media_id is not None:
            raise RuntimeError("empty timeline still has an output size")
        reference = self.reference_media()
        if reference is None:
            return
        if item.width == reference.width and item.height == reference.height:
            return
        raise ValueError(
            f"media size {item.width}x{item.height} does not match "
            f"output size {reference.width}x{reference.height}"
        )

    def _place(
        self,
        segment: Segment,
        desired_start: float,
        track_index: int,
        insert_track: bool,
        snap_threshold: float,
    ) -> None:
        if track_index < 0:
            raise ValueError(f"track index must be non-negative, got {track_index}")
        if insert_track:
            index = min(track_index, len(self.tracks))
            self.tracks.insert(index, [])
        elif not self.tracks:
            self.tracks.append([])
            index = 0
        else:
            index = min(track_index, len(self.tracks) - 1)
        segment.timeline_start = resolve_timeline_start(
            segment.duration,
            desired_start,
            self.tracks[index],
            segment.segment_id,
            snap_threshold,
            self.all_segments(),
        )
        self.tracks[index].append(segment)
        self.tracks[index].sort(key=lambda item: item.timeline_start)

    def _clear_drag(self) -> None:
        self._drag_segment = None
        self._drag_base = None
        self._drag_original = None
