from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videocutter.media import MEDIA_MIME, VIDEO_SUFFIXES, format_duration, probe_video
from videocutter.model import MediaItem, TimelineDocument, new_id


def local_files_from_mime(mime) -> list[str] | None:
    if not mime.hasUrls():
        return None
    paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
    if not paths:
        return None
    return paths


class MediaList(QListWidget):
    def __init__(self, panel: "SourcePanel") -> None:
        super().__init__()
        self._panel = panel
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)

    def mimeTypes(self) -> list[str]:
        return [MEDIA_MIME]

    def mimeData(self, items):
        if not items:
            raise RuntimeError("drag started without a media item")
        media_id = items[0].data(Qt.ItemDataRole.UserRole)
        if not isinstance(media_id, str) or not media_id:
            raise RuntimeError("media item is missing an id")
        mime = QMimeData()
        mime.setData(MEDIA_MIME, media_id.encode("utf-8"))
        return mime

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            paths = local_files_from_mime(event.mimeData())
            if paths is not None:
                event.acceptProposedAction()
                if event.type() == QEvent.Type.Drop:
                    self._panel.add_paths(paths)
                return True
        return super().eventFilter(watched, event)


class SourcePanel(QWidget):
    def __init__(self, document: TimelineDocument, on_changed) -> None:
        super().__init__()
        self.document = document
        self._on_changed = on_changed
        self.setAcceptDrops(True)
        self.setMinimumWidth(240)
        self.add_button = QPushButton("+")
        self.add_button.setFixedSize(32, 32)
        self.add_button.setToolTip("添加视频")
        self.add_button.clicked.connect(self._pick_files)
        self.export_button = QPushButton("导出")
        self.export_button.setObjectName("exportButton")
        self.export_button.setFixedHeight(32)
        self.export_button.setToolTip("按当前轨道输出视频")
        title = QLabel("素材")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.export_button)
        header.addWidget(self.add_button)
        self.file_list = MediaList(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(header)
        layout.addWidget(self.file_list, 1)

    def add_paths(self, paths: list[str]) -> None:
        for path in paths:
            self._add_path(path)
        self._on_changed()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if local_files_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if local_files_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = local_files_from_mime(event.mimeData())
        if paths is None:
            event.ignore()
            return
        self.add_paths(paths)
        event.acceptProposedAction()

    def _pick_files(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(VIDEO_SUFFIXES))
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "添加视频",
            "",
            f"视频文件 ({patterns})",
        )
        if not paths:
            return
        self.add_paths(paths)

    def _add_path(self, path: str) -> None:
        suffix = Path(path).suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            raise RuntimeError(f"unsupported video file: {path}")
        probed = probe_video(path)
        item = MediaItem(
            media_id=new_id(),
            path=str(Path(path).resolve()),
            duration_sec=float(probed["duration_sec"]),
            fps=float(probed["fps"]),
            frame_count=int(probed["frame_count"]),
            width=int(probed["width"]),
            height=int(probed["height"]),
        )
        self.document.add_media(item)
        row = QListWidgetItem(f"{Path(item.path).name}  ({format_duration(item.duration_sec)})")
        row.setData(Qt.ItemDataRole.UserRole, item.media_id)
        row.setToolTip(item.path)
        self.file_list.addItem(row)
