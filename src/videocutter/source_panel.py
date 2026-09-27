from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QRect, QSize, Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QIcon, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRubberBand,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from videocutter.icons import export_icon, open_project_icon, save_project_icon, settings_icon
from videocutter.media import MEDIA_MIME, VIDEO_SUFFIXES, format_duration, probe_video
from videocutter.model import MediaItem, TimelineDocument, new_id


REMOVE_MARK_WIDTH = 28
_ICON_BUTTON_SIZE = 32


def _icon_button(icon: QIcon, tooltip: str, object_name: str) -> QPushButton:
    button = QPushButton()
    button.setObjectName(object_name)
    button.setIcon(icon)
    button.setIconSize(QSize(_ICON_BUTTON_SIZE - 8, _ICON_BUTTON_SIZE - 8))
    button.setFixedSize(_ICON_BUTTON_SIZE, _ICON_BUTTON_SIZE)
    button.setToolTip(tooltip)
    return button


class MediaItemDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        full = QRect(view_option.rect)
        view_option.rect = full.adjusted(0, 0, -REMOVE_MARK_WIDTH, 0)
        widget = view_option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, view_option, painter, widget)
        painter.save()
        painter.setPen(QColor("#e6e6e6"))
        painter.drawText(remove_mark_rect(full), Qt.AlignmentFlag.AlignCenter, "×")
        painter.restore()


def remove_mark_rect(item_rect: QRect) -> QRect:
    return QRect(
        item_rect.right() - REMOVE_MARK_WIDTH + 1,
        item_rect.top(),
        REMOVE_MARK_WIDTH,
        item_rect.height(),
    )


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
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)
        self._item_delegate = MediaItemDelegate(self)
        self.setItemDelegate(self._item_delegate)
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self._rubber_origin = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None and remove_mark_rect(self.visualItemRect(item)).contains(
                event.position().toPoint()
            ):
                media_id = item.data(Qt.ItemDataRole.UserRole)
                if not isinstance(media_id, str) or not media_id:
                    raise RuntimeError("media item is missing an id")
                self._panel.remove_media(media_id)
                return
            if item is None:
                self._rubber_origin = event.position().toPoint()
                self._rubber_band.setGeometry(QRect(self._rubber_origin, self._rubber_origin))
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._delete_key(event):
            self._panel.remove_selected_media()
            event.accept()
            return
        super().keyPressEvent(event)

    def _delete_key(self, event: QKeyEvent) -> bool:
        if event.key() not in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            return False
        if event.isAutoRepeat() or not self.hasFocus():
            return False
        blocked = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        return not (event.modifiers() & blocked)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._rubber_origin is not None:
            rect = QRect(self._rubber_origin, event.position().toPoint()).normalized()
            self._rubber_band.setGeometry(rect)
            self._rubber_band.show()
            self._select_items_in_rect(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._rubber_origin is not None:
            rect = QRect(self._rubber_origin, event.position().toPoint()).normalized()
            self._rubber_band.hide()
            self._rubber_origin = None
            self._select_items_in_rect(rect)
            return
        super().mouseReleaseEvent(event)

    def _select_items_in_rect(self, rect: QRect) -> None:
        for row in range(self.count()):
            item = self.item(row)
            item.setSelected(self.visualItemRect(item).intersects(rect))

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
    def __init__(
        self,
        document: TimelineDocument,
        on_changed,
        on_open_project,
        on_save_project,
        on_edit_output_settings,
    ) -> None:
        super().__init__()
        self.document = document
        self._on_changed = on_changed
        self.setAcceptDrops(True)
        self.setMinimumWidth(460)
        self.add_button = QPushButton("+")
        self.add_button.setFixedSize(32, 32)
        self.add_button.setToolTip("添加视频")
        self.add_button.clicked.connect(self._pick_files)
        self.open_button = _icon_button(open_project_icon(), "打开工程", "openButton")
        self.open_button.clicked.connect(on_open_project)
        self.save_button = _icon_button(save_project_icon(), "保存工程", "saveButton")
        self.save_button.clicked.connect(on_save_project)
        self.settings_button = _icon_button(settings_icon(), "设置", "settingsButton")
        self.settings_button.clicked.connect(on_edit_output_settings)
        self.export_button = _icon_button(export_icon(), "导出", "exportButton")
        title = QLabel("素材")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.open_button)
        header.addWidget(self.save_button)
        header.addWidget(self.settings_button)
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
            bitrate_kbps=float(probed["bitrate_kbps"]),
        )
        self.document.add_media(item)
        self._append_media_row(item)

    def remove_media(self, media_id: str) -> None:
        self.document.delete_media(media_id)
        self.reload_media_list()
        self._on_changed()

    def remove_selected_media(self) -> None:
        media_ids = []
        for item in self.file_list.selectedItems():
            media_id = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(media_id, str) or not media_id:
                raise RuntimeError("media item is missing an id")
            media_ids.append(media_id)
        for media_id in media_ids:
            self.document.delete_media(media_id)
        if media_ids:
            self.reload_media_list()
            self._on_changed()

    def reload_media_list(self) -> None:
        self.file_list.clear()
        for item in self.document.media.values():
            self._append_media_row(item)

    def _append_media_row(self, item: MediaItem) -> None:
        row = QListWidgetItem(f"{Path(item.path).name}  ({format_duration(item.duration_sec)})")
        row.setData(Qt.ItemDataRole.UserRole, item.media_id)
        row.setToolTip(item.path)
        self.file_list.addItem(row)
