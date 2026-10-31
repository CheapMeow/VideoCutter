import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    application = QApplication.instance()
    if application is None:
        application = QApplication(["videocutter-tests", "-platform", "offscreen"])
    if application.platformName() != "offscreen":
        raise RuntimeError("GUI tests require the offscreen platform")
    return application
