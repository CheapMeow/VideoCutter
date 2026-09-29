import math
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMainWindow, QSplitter

from videocutter.export import (
    default_export_filter,
    export_filter_string,
    export_timeline,
    output_path_for_filter,
)
from videocutter.model import TimelineDocument
from videocutter.output_settings import OutputSettings, output_rate_status
from videocutter.output_settings_dialog import OutputSettingsDialog
from videocutter.preview_widget import PreviewWidget
from videocutter.project import PROJECT_FILTER, load_project, project_output_path, save_project
from videocutter.source_panel import SourcePanel
from videocutter.timeline_widget import TimelineHost, TimelineWidget


def format_hms(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"clock time must be finite and non-negative, got {seconds}")
    whole = int(math.floor(seconds + 0.5))
    hours, remain = divmod(whole, 3600)
    minutes, secs = divmod(remain, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


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
QRubberBand {
    background: rgba(0, 120, 215, 50);
    border: 1px solid #0078d7;
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
QPushButton#dialogButton {
    font-size: 13px;
    padding: 0 12px;
}
QPushButton#exportButton, QPushButton#openButton, QPushButton#saveButton, QPushButton#settingsButton {
    padding: 0;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
}
QRadioButton::indicator:unchecked {
    border: 2px solid #d0d0d0;
    border-radius: 8px;
    background: #1e1e1e;
}
QRadioButton::indicator:checked {
    border: 2px solid #d0d0d0;
    border-radius: 8px;
    background: qradialgradient(
        cx: 0.5, cy: 0.5, radius: 0.45, fx: 0.5, fy: 0.5,
        stop: 0 #ffffff, stop: 0.55 #ffffff, stop: 0.62 #1e1e1e, stop: 1 #1e1e1e
    );
}
QSpinBox, QDoubleSpinBox {
    background: #252526;
    color: #e6e6e6;
    border: 1px solid #5a5a5a;
    padding: 2px 6px;
}
QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: #2a2a2a;
    color: #6a6a6a;
    border: 1px solid #3c3c3c;
}
QRadioButton {
    spacing: 8px;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
}
QRadioButton::indicator:unchecked {
    border: 1px solid #9a9a9a;
    border-radius: 7px;
    background: #2a2a2a;
}
QRadioButton::indicator:checked {
    border: 4px solid #4da3ff;
    border-radius: 7px;
    background: #e6e6e6;
}
QSpinBox, QDoubleSpinBox {
    color: #e6e6e6;
    background: #2d2d2d;
    border: 1px solid #5a5a5a;
    padding: 2px 4px;
    font-size: 13px;
}
QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #6e6e6e;
    background: #2a2a2a;
    border: 1px solid #3a3a3a;
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
        self.output_settings = OutputSettings()
        self._export_stop = False
        self._exporting = False
        self.setWindowTitle("VideoCutter")
        self.resize(1280, 760)
        self.source_panel = SourcePanel(
            self.document,
            self.refresh_views,
            self._open_project,
            self._save_project,
            self._edit_output_settings,
        )
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
        splitter.setSizes([480, 800])
        self.setCentralWidget(splitter)
        self.setStyleSheet(STYLESHEET)

    def refresh_views(self) -> None:
        self.preview.refresh()
        self.timeline_host.sync()
        self.timeline.update()

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _open_project(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "打开工程",
            "",
            PROJECT_FILTER,
        )
        if not path:
            return
        self._open_project_from_path(path)

    def _open_project_from_path(self, path: str) -> None:
        document = load_project(path)
        self._replace_document(document)
        self.show_status(f"已打开工程：{path}")

    def _save_project(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "保存工程",
            "",
            PROJECT_FILTER,
        )
        if not path:
            return
        self._save_project_to_path(project_output_path(path))

    def _save_project_to_path(self, path: str) -> None:
        save_project(self.document, path)
        self.show_status(f"已保存工程：{path}")

    def _replace_document(self, document: TimelineDocument) -> None:
        self.timeline.discard_gesture()
        self.preview.release()
        self.document = document
        self.source_panel.document = document
        self.preview.document = document
        self.timeline.document = document
        self.timeline.view_origin = 0.0
        self.source_panel.reload_media_list()
        self.refresh_views()

    def _edit_output_settings(self) -> None:
        dialog = OutputSettingsDialog(self.output_settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.output_settings = dialog.result_settings()

    def _export_video(self) -> None:
        if self._exporting:
            self._export_stop = True
            return
        if self.document.reference_media() is None or not self.document.all_segments():
            self.show_status("轨道上没有可以输出的视频")
            return
        message = output_rate_status(self.document, self.output_settings)
        if message is not None:
            self.show_status(message)
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
        self._exporting = True
        self.source_panel.set_exporting(True)
        self.preview.setEnabled(False)
        self.timeline.setEnabled(False)
        self._export_started = time.perf_counter()
        try:
            finished = export_timeline(
                self.document,
                path,
                self._report_export_progress,
                self._export_should_stop,
                self.output_settings,
            )
        except Exception as error:
            self.show_status(f"输出视频失败：{error}")
            return
        finally:
            self._exporting = False
            self.source_panel.set_exporting(False)
            self.preview.setEnabled(True)
            self.timeline.setEnabled(True)
        if not finished:
            if not self.isVisible():
                QApplication.quit()
                return
            self.show_status("已终止导出")
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
