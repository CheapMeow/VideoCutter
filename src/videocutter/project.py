import json
import math
from pathlib import Path

from videocutter.model import TIME_EPSILON, MediaItem, Segment, TimelineDocument, new_id


PROJECT_FORMAT = "videocutter"
PROJECT_VERSION = 1
PROJECT_SUFFIX = ".vcproj"
PROJECT_FILTER = "VideoCutter 工程 (*.vcproj)"


def project_output_path(path: str) -> str:
    return str(Path(path).with_suffix(PROJECT_SUFFIX))


def save_project(document: TimelineDocument, path: str) -> None:
    destination = Path(path)
    if destination.suffix.lower() != PROJECT_SUFFIX:
        raise ValueError(f"project path must end with {PROJECT_SUFFIX}, got {path}")
    if document.drag_base_track_count() is not None:
        raise RuntimeError("cannot save a project while a segment is being dragged")
    used_ids: list[str] = []
    seen: set[str] = set()
    for track in document.tracks:
        for segment in track:
            if segment.media_id not in seen:
                seen.add(segment.media_id)
                used_ids.append(segment.media_id)
    if document.reference_media_id is not None and document.reference_media_id not in seen:
        raise RuntimeError("output reference media is not used by the timeline")
    if document.all_segments() and document.reference_media_id is None:
        raise RuntimeError("timeline segments exist without an output size")
    media_entries = []
    for media_id in used_ids:
        item = document.media[media_id]
        file_path = Path(item.path)
        if not file_path.is_absolute():
            raise ValueError(f"media path must be absolute: {item.path}")
        media_entries.append({"id": media_id, "path": str(file_path)})
    tracks = []
    for track in document.tracks:
        clips = []
        for segment in track:
            clips.append(
                {
                    "media": segment.media_id,
                    "position": segment.timeline_start,
                    "duration": segment.duration,
                    "source_in": segment.source_in,
                }
            )
        tracks.append(clips)
    payload = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "media": media_entries,
        "reference": document.reference_media_id,
        "tracks": tracks,
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_project(path: str) -> TimelineDocument:
    # cv2 启动时不加载，窗口显示后由 videocutter.app 在后台预先导入
    from videocutter.capture import probe_video

    file_path = Path(path)
    if file_path.suffix.lower() != PROJECT_SUFFIX:
        raise ValueError(f"project path must end with {PROJECT_SUFFIX}, got {path}")
    if not file_path.is_file():
        raise RuntimeError(f"not a file: {path}")
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    root = _as_dict(payload, "project")
    _require_fields(root, {"format", "version", "media", "reference", "tracks"}, "project")
    if root["format"] != PROJECT_FORMAT:
        raise ValueError(f"unknown project format: {root['format']!r}")
    if root["version"] != PROJECT_VERSION:
        raise ValueError(f"unsupported project version: {root['version']!r}")
    media_entries = _as_list(root["media"], "media")
    track_entries = _as_list(root["tracks"], "tracks")
    reference = root["reference"]
    if reference is not None and not isinstance(reference, str):
        raise ValueError(f"reference must be a media id or null, got {reference!r}")
    document = TimelineDocument()
    seen_ids: set[str] = set()
    for index, entry in enumerate(media_entries):
        item = _as_dict(entry, f"media[{index}]")
        _require_fields(item, {"id", "path"}, f"media[{index}]")
        media_id = _as_text(item["id"], f"media[{index}].id")
        media_path = _as_text(item["path"], f"media[{index}].path")
        if media_id in seen_ids:
            raise ValueError(f"duplicate media id: {media_id}")
        seen_ids.add(media_id)
        if not Path(media_path).is_absolute():
            raise ValueError(f"media path must be absolute: {media_path}")
        probed = probe_video(media_path)
        document.add_media(
            MediaItem(
                media_id=media_id,
                path=media_path,
                duration_sec=float(probed["duration_sec"]),
                fps=float(probed["fps"]),
                frame_count=int(probed["frame_count"]),
                width=int(probed["width"]),
                height=int(probed["height"]),
                bitrate_kbps=float(probed["bitrate_kbps"]),
            )
        )
    used_ids: set[str] = set()
    tracks: list[list[Segment]] = []
    for track_index, entry in enumerate(track_entries):
        clip_entries = _as_list(entry, f"tracks[{track_index}]")
        if not clip_entries:
            raise ValueError(f"tracks[{track_index}] is empty")
        clips: list[Segment] = []
        for clip_index, clip_entry in enumerate(clip_entries):
            clip = _as_dict(clip_entry, f"tracks[{track_index}][{clip_index}]")
            _require_fields(
                clip,
                {"media", "position", "duration", "source_in"},
                f"tracks[{track_index}][{clip_index}]",
            )
            media_id = _as_text(clip["media"], f"tracks[{track_index}][{clip_index}].media")
            if media_id not in document.media:
                raise ValueError(f"unknown media id: {media_id}")
            position = _as_number(clip["position"], f"tracks[{track_index}][{clip_index}].position")
            duration = _as_number(clip["duration"], f"tracks[{track_index}][{clip_index}].duration")
            source_in = _as_number(clip["source_in"], f"tracks[{track_index}][{clip_index}].source_in")
            if position < 0:
                raise ValueError(f"segment position must be non-negative, got {position}")
            if duration <= 0:
                raise ValueError(f"segment duration must be positive, got {duration}")
            if source_in < 0:
                raise ValueError(f"segment source start must be non-negative, got {source_in}")
            item = document.media[media_id]
            source_out = source_in + duration
            if source_out > item.duration_sec + TIME_EPSILON:
                raise ValueError(
                    f"segment extends past media duration: {source_out} > {item.duration_sec}"
                )
            used_ids.add(media_id)
            clips.append(
                Segment(
                    segment_id=new_id(),
                    media_id=media_id,
                    timeline_start=position,
                    source_in=source_in,
                    source_out=source_out,
                )
            )
        clips.sort(key=lambda segment: segment.timeline_start)
        previous_end = 0.0
        for segment in clips:
            if segment.timeline_start < previous_end - TIME_EPSILON:
                raise ValueError(
                    f"segments overlap on track {track_index} at {segment.timeline_start}"
                )
            previous_end = segment.timeline_end
        tracks.append(clips)
    if used_ids != seen_ids:
        raise ValueError("project media must all be used by the timeline")
    if tracks and reference is None:
        raise ValueError("project with tracks is missing an output reference")
    if not tracks and reference is not None:
        raise ValueError("empty project must not set an output reference")
    if reference is not None and reference not in document.media:
        raise ValueError(f"unknown reference media id: {reference}")
    document.tracks = tracks
    document.reference_media_id = reference
    if reference is not None:
        output = document.media[reference]
        for item in document.media.values():
            if item.width != output.width or item.height != output.height:
                raise ValueError(
                    f"media size {item.width}x{item.height} does not match "
                    f"output size {output.width}x{output.height}"
                )
    return document


def _as_dict(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _as_list(value, name: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _as_text(value, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _as_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _require_fields(value: dict, fields: set[str], name: str) -> None:
    missing = sorted(fields - value.keys())
    extra = sorted(value.keys() - fields)
    if missing:
        raise ValueError(f"{name} is missing {missing}")
    if extra:
        raise ValueError(f"{name} has unknown fields {extra}")
