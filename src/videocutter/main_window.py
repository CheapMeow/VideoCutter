from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QSplitter

from videocutter.export import export_timeline
from videocutter.model import TimelineDocument
from videocutter.preview_widget import PreviewWidget
from videocutter.source_panel import SourcePanel
from videocutter.timeline_widget import TimelineHost, TimelineWidget


STYLESHEET = """
QMainWindow, QWidget {
    background: #1e1e1e;
    color: #e6e6e6;
    font-size: 13px;
}
QListWidget {
    background: #252526;
    border: 1px solid #3c3c3c;
    outline: none;
}
QListWidget::item {
    padding: 6px 8px;
}
QListWidget::item:selected {
    background: #094771;
}
QPushButton {
    background: #3a3a3a;
    border: 1px solid #5a5a5a;
    border-radius: 4px;
    font-size: 18px;
}
QPushButton:hover {
    background: #4a4a4a;
}
QPushButton#exportButton {
    font-size: 13px;
    padding: 0 12px;
}
QSplitter::handle {
    background: #111111;
}
QStatusBar {
    background: #141414;
    color: #ffcc88;
    border-top: 1px solid #3c3c3c;
}
QScrollBar:vertical {
    background: #1e1e1e;
    width: 12px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.document = TimelineDocument()
        self.setWindowTitle("VideoCutter")
        self.resize(1280, 760)
        self.source_panel = SourcePanel(self.document, self.refresh_views)
        self.source_panel.export_button.clicked.connect(self._export_video)
        self.preview = PreviewWidget(self.document)
        self.timeline = TimelineWidget(self.document, self.refresh_views, self.show_status)
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        status.setMinimumHeight(28)
        self.timeline_host = TimelineHost(self.timeline)
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.preview)
        right.addWidget(self.timeline_host)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 1)
        right.setSizes([340, 380])
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.source_panel)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 1000])
        self.setCentralWidget(splitter)
        self.setStyleSheet(STYLESHEET)

    def refresh_views(self) -> None:
        self.preview.refresh()
        self.timeline_host.sync()
        self.timeline.update()

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _export_video(self) -> None:
        if self.document.reference_media() is None or not self.document.all_segments():
            self.show_status("轨道上没有可以输出的视频")
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "输出视频",
            "",
            "AVI 视频 (*.avi)",
        )
        if not path:
            return
        if Path(path).suffix.lower() != ".avi":
            path = str(Path(path).with_suffix(".avi"))
        self.show_status("正在输出视频")
        QApplication.processEvents()
        export_timeline(self.document, path)
        self.show_status(f"已输出视频：{path}")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_views()

    def closeEvent(self, event) -> None:
        self.preview.release()
        super().closeEvent(event)
