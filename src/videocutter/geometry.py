RULER_HEIGHT = 32
TRACK_HEIGHT = 56
TRACK_GAP = 16
SNAP_THRESHOLD_PX = 12.0


def track_stride() -> int:
    return TRACK_HEIGHT + TRACK_GAP


def row_top(index: int) -> int:
    if index < 0:
        raise ValueError(f"track index must be non-negative, got {index}")
    return RULER_HEIGHT + index * track_stride()


def snap_threshold_seconds(pixels_per_second: float) -> float:
    if pixels_per_second <= 0:
        raise ValueError(f"pixels per second must be positive, got {pixels_per_second}")
    return SNAP_THRESHOLD_PX / pixels_per_second


def track_target_at_y(y: float, track_count: int) -> tuple[bool, int]:
    # 返回 (是否在该位置新增轨道, 轨道序号)。
    # 指针落在轨道画面内时进入该轨道；落在轨道之间、第一条上方或最后一条下方时新增轨道。
    if track_count < 0:
        raise ValueError(f"track count must be non-negative, got {track_count}")
    if track_count == 0:
        return True, 0
    if y < row_top(0):
        return True, 0
    for index in range(track_count):
        top = row_top(index)
        bottom = top + TRACK_HEIGHT
        if top <= y < bottom:
            return False, index
        gap_bottom = bottom + TRACK_GAP
        if bottom <= y < gap_bottom:
            return True, index + 1
    return True, track_count
