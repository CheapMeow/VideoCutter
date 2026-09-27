from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from videocutter.output_settings import RATE_MAX, RATE_MIN, RATE_SPECIFIED, OutputSettings


class OutputSettingsDialog(QDialog):
    def __init__(self, settings: OutputSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("输出设置")
        self.fps_specified = QRadioButton("指定值")
        self.fps_max = QRadioButton("轨道片段的最大值")
        self.fps_min = QRadioButton("轨道片段的最小值")
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(1, 1000)
        self.fps_spin.setDecimals(3)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.setValue(settings.fps_value)
        self.bitrate_specified = QRadioButton("指定值")
        self.bitrate_max = QRadioButton("轨道片段的最大值")
        self.bitrate_min = QRadioButton("轨道片段的最小值")
        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(1, 500000)
        self.bitrate_spin.setSuffix(" kbps")
        self.bitrate_spin.setValue(int(settings.bitrate_kbps))
        fps_group = QButtonGroup(self)
        bitrate_group = QButtonGroup(self)
        for button in (self.fps_specified, self.fps_max, self.fps_min):
            fps_group.addButton(button)
        for button in (self.bitrate_specified, self.bitrate_max, self.bitrate_min):
            bitrate_group.addButton(button)
        self._check_mode(settings.fps_mode, self.fps_specified, self.fps_max, self.fps_min)
        self._check_mode(
            settings.bitrate_mode,
            self.bitrate_specified,
            self.bitrate_max,
            self.bitrate_min,
        )
        self.fps_specified.toggled.connect(self.fps_spin.setEnabled)
        self.bitrate_specified.toggled.connect(self.bitrate_spin.setEnabled)
        self.fps_spin.setEnabled(self.fps_specified.isChecked())
        self.bitrate_spin.setEnabled(self.bitrate_specified.isChecked())
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("输出帧率"))
        layout.addLayout(self._specified_row(self.fps_specified, self.fps_spin))
        layout.addWidget(self.fps_max)
        layout.addWidget(self.fps_min)
        layout.addWidget(QLabel("输出码率"))
        layout.addLayout(self._specified_row(self.bitrate_specified, self.bitrate_spin))
        layout.addWidget(self.bitrate_max)
        layout.addWidget(self.bitrate_min)
        layout.addWidget(buttons)

    def result_settings(self) -> OutputSettings:
        return OutputSettings(
            fps_mode=self._selected_mode(self.fps_specified, self.fps_max, self.fps_min),
            fps_value=float(self.fps_spin.value()),
            bitrate_mode=self._selected_mode(
                self.bitrate_specified,
                self.bitrate_max,
                self.bitrate_min,
            ),
            bitrate_kbps=float(self.bitrate_spin.value()),
        )

    def _check_mode(
        self,
        mode: str,
        specified: QRadioButton,
        maximum: QRadioButton,
        minimum: QRadioButton,
    ) -> None:
        if mode == RATE_SPECIFIED:
            specified.setChecked(True)
        elif mode == RATE_MAX:
            maximum.setChecked(True)
        elif mode == RATE_MIN:
            minimum.setChecked(True)
        else:
            raise ValueError(f"unknown output rate mode: {mode}")

    def _selected_mode(
        self,
        specified: QRadioButton,
        maximum: QRadioButton,
        minimum: QRadioButton,
    ) -> str:
        if specified.isChecked():
            return RATE_SPECIFIED
        if maximum.isChecked():
            return RATE_MAX
        if minimum.isChecked():
            return RATE_MIN
        raise RuntimeError("output rate mode is not selected")

    def _specified_row(self, button: QRadioButton, spin) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(button)
        row.addWidget(spin)
        row.addStretch(1)
        return row
