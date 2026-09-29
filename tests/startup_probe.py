import sys
import threading

from PySide6.QtWidgets import QApplication

from videocutter.app import preload_media_libraries, start_after_first_paint
from videocutter.main_window import MainWindow

MEDIA_LIBRARIES = ("cv2", "av", "numpy")


def loaded_media_libraries() -> str:
    return ",".join(name for name in MEDIA_LIBRARIES if name in sys.modules)


done = threading.Event()


def preload_and_report() -> None:
    print("painted", loaded_media_libraries())
    preload_media_libraries()
    print("preloaded", loaded_media_libraries())
    done.set()


app = QApplication(sys.argv)
window = MainWindow()
start_after_first_paint(window, preload_and_report)
window.show()
while not done.is_set():
    app.processEvents()
window.close()
