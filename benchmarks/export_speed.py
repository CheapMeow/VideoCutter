import sys
import time

from benchmarks.source import OUTPUT_DIR, ensure_source
from videocutter.export import export_timeline
from videocutter.media import probe_video
from videocutter.model import MediaItem, Segment, TimelineDocument, new_id
from videocutter.output_settings import OutputSettings


def timeline(path: str) -> TimelineDocument:
    # 两个片段各 6 秒，分别取素材的 2~8 秒和 12~18 秒，中间有一次跳转
    probed = probe_video(path)
    item = MediaItem(
        media_id=new_id(),
        path=path,
        duration_sec=float(probed["duration_sec"]),
        fps=float(probed["fps"]),
        frame_count=int(probed["frame_count"]),
        width=int(probed["width"]),
        height=int(probed["height"]),
        bitrate_kbps=float(probed["bitrate_kbps"]),
    )
    document = TimelineDocument()
    document.add_media(item)
    document.tracks = [
        [
            Segment(new_id(), item.media_id, 0.0, 2.0, 8.0),
            Segment(new_id(), item.media_id, 6.0, 12.0, 18.0),
        ]
    ]
    document.reference_media_id = item.media_id
    return document


def main(suffixes: list[str]) -> None:
    source = ensure_source()
    document = timeline(str(source))
    for suffix in suffixes:
        output = OUTPUT_DIR / f"export{suffix}"
        progress = [0, 0]

        def record(written: int, total: int) -> None:
            progress[0] = written
            progress[1] = total

        start = time.perf_counter()
        finished = export_timeline(document, str(output), record, lambda: False, OutputSettings())
        elapsed = time.perf_counter() - start
        if not finished or progress[0] != progress[1]:
            raise RuntimeError(f"export did not finish: {progress}")
        size_mib = output.stat().st_size / (1024 * 1024)
        print(
            f"{suffix:<6} {progress[1]} frames  {elapsed:7.2f} s  "
            f"{progress[1] / elapsed:7.1f} fps  {size_mib:6.1f} MiB"
        )


if __name__ == "__main__":
    main(sys.argv[1:] or [".mp4", ".mov", ".avi", ".webm"])
