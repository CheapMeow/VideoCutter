MEDIA_MIME = "application/x-videocutter-media"

VIDEO_SUFFIXES = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
        ".m4v",
        ".wmv",
        ".flv",
        ".mpg",
        ".mpeg",
        ".ts",
    }
)


def format_duration(seconds: float) -> str:
    if seconds < 0:
        raise ValueError(f"duration must be non-negative, got {seconds}")
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def frame_index_at(fps: float, frame_count: int, source_time_sec: float) -> int:
    if fps <= 0:
        raise RuntimeError(f"invalid fps: {fps}")
    if frame_count <= 0:
        raise RuntimeError(f"invalid frame count: {frame_count}")
    if source_time_sec < 0:
        raise RuntimeError(f"source time must be non-negative, got {source_time_sec}")
    frame_index = int(source_time_sec * fps)
    if frame_index == frame_count:
        frame_index = frame_count - 1
    if frame_index < 0 or frame_index >= frame_count:
        raise RuntimeError(
            f"frame index {frame_index} outside 0..{frame_count - 1} at {source_time_sec}"
        )
    return frame_index
