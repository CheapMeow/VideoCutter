import sys
import threading
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from videocutter.main_window import MainWindow


def preload_media_libraries() -> None:
    # cv2、av、numpy 的动态库合计约 170 MB，放在启动时加载会让窗口晚出现。窗口显示后在后台导入，打开视频和导出时就不用再等。
    import videocutter.capture  # noqa: F401
    import videocutter.export  # noqa: F401


class _StartAfterFirstPaint(QObject):
    # Windows 加载动态库时持有进程级的加载锁，第一次绘制也要加载 Qt 插件的动态库，后台导入必须等第一次绘制结束后再开始
    def __init__(self, window: QWidget, target: Callable[[], None]) -> None:
        super().__init__(window)
        self._window = window
        self._target = target
        window.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Paint:
            self._window.removeEventFilter(self)
            QTimer.singleShot(0, self._start)
        return False

    def _start(self) -> None:
        threading.Thread(target=self._target, name="preload-media", daemon=True).start()


def start_after_first_paint(window: QWidget, target: Callable[[], None]) -> None:
    _StartAfterFirstPaint(window, target)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("VideoCutter")
    window = MainWindow()
    start_after_first_paint(window, preload_media_libraries)
    window.show()
    raise SystemExit(app.exec())
