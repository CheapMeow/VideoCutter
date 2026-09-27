import sys

from PySide6.QtWidgets import QApplication

from videocutter.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("VideoCutter")
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())
