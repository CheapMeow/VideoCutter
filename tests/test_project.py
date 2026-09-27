import json
from pathlib import Path

import pytest

from tests.support import write_color_video
from videocutter.media import probe_video
from videocutter.model import MediaItem, TimelineDocument, new_id
from videocutter.project import load_project, project_output_path, save_project


def test_project_output_path_uses_vcproj_suffix(tmp_path):
    assert project_output_path(str(tmp_path / "edit")) == str(tmp_path / "edit.vcproj")
    assert project_output_path(str(tmp_path / "edit.mp4")) == str(tmp_path / "edit.vcproj")
    assert project_output_path(str(tmp_path / "edit.vcproj")) == str(tmp_path / "edit.vcproj")


def test_save_and_load_keep_paths_positions_and_durations(tmp_path):
    first_path = tmp_path / "first.avi"
    second_path = tmp_path / "second.avi"
    unused_path = tmp_path / "unused.avi"
    write_color_video(first_path, frame_count=10, fps=10, size=(160, 90))
    write_color_video(second_path, frame_count=10, fps=5, size=(160, 90), red_base=40)
    write_color_video(unused_path, frame_count=4, fps=10, size=(160, 90))
    document = TimelineDocument()
    first = _add_media(document, first_path)
    second = _add_media(document, second_path)
    _add_media(document, unused_path)
    opening = document.place_new_segment(first.media_id, 0, 0, True, 0)
    document.place_new_segment(second.media_id, 1, 1, True, 0)
    document.select_segment(opening.segment_id)
    document.set_playhead(0.4)
    assert document.split_selected() is not None
    destination = tmp_path / "edit.vcproj"
    save_project(document, str(destination))
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["format"] == "videocutter"
    assert payload["version"] == 1
    assert [item["path"] for item in payload["media"]] == [first.path, second.path]
    assert payload["reference"] == first.media_id
    assert str(unused_path.resolve()) not in destination.read_text(encoding="utf-8")
    loaded = load_project(str(destination))
    assert [item.path for item in loaded.media.values()] == [first.path, second.path]
    assert loaded.reference_media().path == first.path
    assert loaded.reference_media().fps == pytest.approx(10)
    assert len(loaded.tracks) == 2
    left, right = loaded.tracks[0]
    assert left.timeline_start == pytest.approx(0)
    assert left.duration == pytest.approx(0.4)
    assert left.source_in == pytest.approx(0)
    assert right.timeline_start == pytest.approx(0.4)
    assert right.duration == pytest.approx(0.6)
    assert right.source_in == pytest.approx(0.4)
    assert loaded.media[right.media_id].path == first.path
    lower = loaded.tracks[1][0]
    assert loaded.media[lower.media_id].path == second.path
    assert lower.timeline_start == pytest.approx(1)
    assert lower.duration == pytest.approx(2)
    assert lower.source_in == pytest.approx(0)
    assert loaded.playhead == 0
    assert loaded.selected_segment_id is None


def test_empty_project_roundtrip(tmp_path):
    destination = tmp_path / "empty.vcproj"
    save_project(TimelineDocument(), str(destination))
    loaded = load_project(str(destination))
    assert loaded.media == {}
    assert loaded.tracks == []
    assert loaded.reference_media_id is None


def test_save_rejects_a_path_without_the_project_suffix(tmp_path):
    with pytest.raises(ValueError, match="vcproj"):
        save_project(TimelineDocument(), str(tmp_path / "edit.json"))


def test_save_rejects_an_active_drag(tmp_path):
    path = tmp_path / "clip.avi"
    write_color_video(path, frame_count=8, fps=10)
    document = TimelineDocument()
    item = _add_media(document, path)
    segment = document.place_new_segment(item.media_id, 0, 0, True, 0)
    document.begin_segment_drag(segment.segment_id)
    with pytest.raises(RuntimeError, match="drag"):
        save_project(document, str(tmp_path / "edit.vcproj"))


def test_load_rejects_overlap_missing_media_and_size_mismatch(tmp_path):
    wide = tmp_path / "wide.avi"
    narrow = tmp_path / "narrow.avi"
    write_color_video(wide, frame_count=8, fps=10, size=(160, 90))
    write_color_video(narrow, frame_count=8, fps=10, size=(80, 60))
    document = TimelineDocument()
    item = _add_media(document, wide)
    document.place_new_segment(item.media_id, 0, 0, True, 0)
    destination = tmp_path / "edit.vcproj"
    save_project(document, str(destination))
    payload = json.loads(destination.read_text(encoding="utf-8"))
    payload["tracks"][0].append(
        {"media": item.media_id, "position": 0, "duration": 0.4, "source_in": 0.4}
    )
    destination.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="overlap"):
        load_project(str(destination))

    payload = json.loads(destination.read_text(encoding="utf-8"))
    payload["tracks"][0].pop()
    payload["media"][0]["path"] = str(tmp_path / "missing.avi")
    destination.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a file"):
        load_project(str(destination))

    mismatch = {
        "format": "videocutter",
        "version": 1,
        "media": [
            {"id": "wide", "path": str(wide.resolve())},
            {"id": "narrow", "path": str(narrow.resolve())},
        ],
        "reference": "wide",
        "tracks": [
            [{"media": "wide", "position": 0, "duration": 0.4, "source_in": 0}],
            [{"media": "narrow", "position": 0, "duration": 0.4, "source_in": 0}],
        ],
    }
    mismatch_path = tmp_path / "mismatch.vcproj"
    mismatch_path.write_text(json.dumps(mismatch), encoding="utf-8")
    with pytest.raises(ValueError, match="output size"):
        load_project(str(mismatch_path))


def _add_media(document: TimelineDocument, path: Path) -> MediaItem:
    probed = probe_video(str(path))
    item = MediaItem(
        media_id=new_id(),
        path=str(path.resolve()),
        duration_sec=float(probed["duration_sec"]),
        fps=float(probed["fps"]),
        frame_count=int(probed["frame_count"]),
        width=int(probed["width"]),
        height=int(probed["height"]),
        bitrate_kbps=float(probed["bitrate_kbps"]),
    )
    document.add_media(item)
    return item
