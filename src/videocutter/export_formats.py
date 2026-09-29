from pathlib import Path


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


def fourcc_for_suffix(suffix: str) -> str:
    lowered = suffix.lower()
    for _label, item_suffix, fourcc in EXPORT_CHOICES:
        if item_suffix == lowered:
            return fourcc
    raise ValueError(f"unsupported export suffix: {suffix}")


def output_path_for_filter(path: str, selected_filter: str) -> str:
    return str(Path(path).with_suffix(suffix_for_filter(selected_filter)))
