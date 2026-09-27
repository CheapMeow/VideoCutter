import math
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QSplitter

from videocutter.export import (
    default_export_filter,
    export_filter_string,
    export_timeline,
    output_path_for_filter,
)
from videocutter.model import TimelineDocument
from videocutter.preview_widget import PreviewWidget
from videocutter.source_panel import SourcePanel
from videocutter.timeline_widget import TimelineHost, TimelineWidget


def format_hms(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"clock time must be finite and non-negative, got {seconds}")
    whole = int(math.floor(seconds + 0.5))
    hours, remain = divmod(whole, 3600)
    minutes, secs = divmod(remain, 60)
    return f"{hours:02d}：{minutes:02d}：{secs:02d}"


def format_export_progress(
    written: int,
    total: int,
    elapsed_sec: float,
    estimated_sec: float | None,
) -> str:
    if total <= 0:
        raise ValueError(f"export frame count must be positive, got {total}")
    if written < 0 or written > total:
        raise ValueError(f"export progress {written} outside 0..{total}")
    if not math.isfinite(elapsed_sec) or elapsed_sec < 0:
        raise ValueError(f"export elapsed time must be finite and non-negative, got {elapsed_sec}")
    if written == 0:
        if estimated_sec is not None:
            raise ValueError("export estimate requires a completed frame")
        clock = f"{format_hms(elapsed_sec)}/—"
    else:
        if estimated_sec is None or not math.isfinite(estimated_sec) or estimated_sec < 0:
            raise ValueError(f"export estimate must be finite and non-negative, got {estimated_sec}")
        clock = f"{format_hms(elapsed_sec)}/{format_hms(estimated_sec)}"
    percent = written * 100 // total
    return f"正在输出视频：{written}/{total}（{percent}%），{clock}"


def format_export_result(path: str, elapsed_sec: float) -> str:
    if not math.isfinite(elapsed_sec) or elapsed_sec < 0:
        raise ValueError(f"export elapsed time must be finite and non-negative, got {elapsed_sec}")
    return f"已输出视频：{path}，用时 {elapsed_sec:.2f} 秒"


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
        self._export_stop = False
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
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "输出视频",
            "",
            export_filter_string(),
            default_export_filter(),
        )
        if not path:
            return
        self._export_to_path(output_path_for_filter(path, selected_filter))

    def _export_to_path(self, path: str) -> None:
        self._export_stop = False
        self.source_panel.setEnabled(False)
        self.preview.setEnabled(False)
        self.timeline.setEnabled(False)
        self._export_started = time.perf_counter()
        try:
            finished = export_timeline(
                self.document,
                path,
                self._report_export_progress,
                self._export_should_stop,
            )
        finally:
            self.source_panel.setEnabled(True)
            self.preview.setEnabled(True)
            self.timeline.setEnabled(True)
        if not finished:
            QApplication.quit()
            return
        elapsed = time.perf_counter() - self._export_started
        self.show_status(format_export_result(path, elapsed))

    def _export_should_stop(self) -> bool:
        return self._export_stop

    def _report_export_progress(self, written: int, total: int) -> None:
        self.export_written = written
        self.export_total = total
        elapsed = time.perf_counter() - self._export_started
        estimated = None if written == 0 else elapsed * total / written
        self.export_progress_message = format_export_progress(written, total, elapsed, estimated)
        self.show_status(self.export_progress_message)
        QApplication.processEvents()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_views()

    def closeEvent(self, event) -> None:
        self._export_stop = True
        self.preview.release()
        super().closeEvent(event)
