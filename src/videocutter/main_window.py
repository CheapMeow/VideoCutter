from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter

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
QSplitter::handle {
    background: #111111;
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
        self.preview = PreviewWidget(self.document)
        self.timeline = TimelineWidget(self.document, self.refresh_views)
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_views()

    def closeEvent(self, event) -> None:
        self.preview.release()
        super().closeEvent(event)
