from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from videocutter.model import MediaItem, Segment, TimelineDocument


@dataclass
class EditState:
    media: dict[str, MediaItem]
    tracks: list[list[Segment]]
    reference_media_id: str | None
    selected_segment_id: str | None
    playhead: float

    def same_content(self, other: EditState) -> bool:
        return (
            self.media == other.media
            and self.tracks == other.tracks
            and self.reference_media_id == other.reference_media_id
        )


@dataclass
class Edit:
    before: EditState
    after: EditState


def record_edit(method):
    @wraps(method)
    def recorded(document, *args, **kwargs):
        with document.edit_group():
            return method(document, *args, **kwargs)

    return recorded


class EditHistory:
    LIMIT = 100

    def __init__(self, document: TimelineDocument) -> None:
        self.document = document
        self._undo: list[Edit] = []
        self._redo: list[Edit] = []
        self._depth = 0

    def capture(self) -> EditState:
        document = self.document
        return EditState(
            copy.deepcopy(document.media),
            copy.deepcopy(document.tracks),
            document.reference_media_id,
            document.selected_segment_id,
            document.playhead,
        )

    def restore(self, state: EditState) -> None:
        document = self.document
        document.media = copy.deepcopy(state.media)
        document.tracks = copy.deepcopy(state.tracks)
        document.reference_media_id = state.reference_media_id
        document.selected_segment_id = state.selected_segment_id
        document.playhead = state.playhead

    def record(self, before: EditState) -> None:
        after = self.capture()
        if before.same_content(after):
            return
        self._undo.append(Edit(before, after))
        del self._undo[:-self.LIMIT]
        self._redo.clear()

    @contextmanager
    def group(self):
        if self.document.drag_base_track_count() is not None:
            raise RuntimeError("cannot edit while dragging a segment")
        outermost = self._depth == 0
        before = self.capture() if outermost else None
        self._depth += 1
        completed = False
        try:
            yield
            completed = True
        finally:
            self._depth -= 1
            if outermost:
                if completed:
                    self.record(before)
                else:
                    self.restore(before)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def _require_idle(self) -> None:
        if self._depth or self.document.drag_base_track_count() is not None:
            raise RuntimeError("cannot change history during an edit")

    def undo(self) -> bool:
        self._require_idle()
        if not self._undo:
            return False
        edit = self._undo.pop()
        self.restore(edit.before)
        self._redo.append(edit)
        return True

    def redo(self) -> bool:
        self._require_idle()
        if not self._redo:
            return False
        edit = self._redo.pop()
        self.restore(edit.after)
        self._undo.append(edit)
        return True

    def clear(self) -> None:
        self._require_idle()
        self._undo.clear()
        self._redo.clear()
