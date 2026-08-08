"""
ui/widgets/form_dialog.py
==========================
Dialog form generik yang dirender otomatis dari `list[FieldSpec]`
(lihat registry/module_registry.py). Dipakai oleh generic_list_page dan
oleh layar-layar khusus untuk sub-form (mis. baris jurnal).

REDESIGN: sebelumnya semua field ditumpuk 1 kolom vertikal di dalam
QScrollArea -- untuk form dengan banyak field (mis. Customer, ~24 field)
ini jadi panjang sekali dan selalu perlu scroll. Sekarang field disusun
dalam grid 2 kolom (kiri-kanan) supaya dialog lebih lebar & lebih pendek,
biasanya muat dalam satu layar tanpa scroll. TEXTAREA selalu full-width
(1 baris penuh) karena secara visual lebih enak dibaca lebar daripada
sempit. Scroll area hanya dipasang sebagai fallback kalau kontennya
tetap lebih tinggi dari layar yang tersedia (form yang sangat panjang).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from registry.module_registry import FieldSpec, FieldType

# Field bertipe ini lebih enak dibaca full-width daripada dipepetkan
# ke satu kolom sempit.
_FULL_WIDTH_TYPES = (FieldType.TEXTAREA,)

# Banyak field -> pakai 2 kolom biar dialog lebar-pendek, bukan
# sempit-panjang. Sedikit field -> 1 kolom saja sudah cukup rapi.
_TWO_COLUMN_THRESHOLD = 6

_INPUT_MIN_HEIGHT = 34

_DIALOG_QSS = """
QDialog {
    background: #fbfbfd;
}
QLabel#formDialogTitle {
    font-size: 16px;
    font-weight: 600;
    color: #1f2430;
    padding-bottom: 4px;
}
QLabel#formFieldLabel {
    color: #3c4257;
    font-size: 12.5px;
    font-weight: 500;
}
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit {
    border: 1px solid #d7dae2;
    border-radius: 6px;
    padding: 6px 10px;
    background: #ffffff;
    selection-background-color: #6C5CE7;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {
    border: 1.5px solid #6C5CE7;
}
QPushButton#primaryButton {
    background: #6C5CE7;
    color: white;
    border-radius: 6px;
    padding: 8px 22px;
    font-weight: 600;
    border: none;
}
QPushButton#primaryButton:hover {
    background: #5b4bd6;
}
QPushButton#secondaryButton {
    background: transparent;
    color: #3c4257;
    border: 1px solid #d7dae2;
    border-radius: 6px;
    padding: 8px 22px;
}
QPushButton#secondaryButton:hover {
    background: #f0f0f4;
}
"""


class FormDialog(QDialog):
    """Form auto-generate untuk create/edit satu record, layout grid rapi."""

    def __init__(
        self,
        title: str,
        fields: list[FieldSpec],
        initial: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.fields = fields
        self.initial = initial or {}
        self._inputs: dict[str, QWidget] = {}
        self.setStyleSheet(_DIALOG_QSS)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        num_columns = 2 if len(self.fields) > _TWO_COLUMN_THRESHOLD else 1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 20)
        outer.setSpacing(14)

        title_label = QLabel(self.windowTitle())
        title_label.setObjectName("formDialogTitle")
        outer.addWidget(title_label)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)
        if num_columns == 2:
            grid.setColumnStretch(3, 1)

        row = 0
        col = 0
        for spec in self.fields:
            widget = self._create_input(spec)
            self._inputs[spec.name] = widget

            label = QLabel(spec.label + (" *" if spec.required else ""))
            label.setObjectName("formFieldLabel")

            if spec.type in _FULL_WIDTH_TYPES:
                if col != 0:
                    row += 1
                    col = 0
                grid.addWidget(label, row, 0, Qt.AlignTop | Qt.AlignRight)
                span = (num_columns * 2) - 1
                grid.addWidget(widget, row, 1, 1, span)
                row += 1
            else:
                base = col * 2
                grid.addWidget(label, row, base, Qt.AlignRight | Qt.AlignVCenter)
                grid.addWidget(widget, row, base + 1)
                col += 1
                if col >= num_columns:
                    col = 0
                    row += 1

        # Lebar dialog: cukup lebar utk 2 kolom biar tetap terasa lega,
        # tapi tidak berlebihan utk form pendek 1 kolom.
        self.setMinimumWidth(720 if num_columns == 2 else 460)

        # Kalau kontennya tetap lebih tinggi dari layar yang tersedia
        # (form sangat panjang), baru pasang scroll sebagai fallback --
        # bukan default seperti sebelumnya.
        content_height = grid_host.sizeHint().height()
        screen = QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 900
        max_content_height = int(available_height * 0.7)

        if content_height > max_content_height:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setMaximumHeight(max_content_height)
            scroll.setWidget(grid_host)
            outer.addWidget(scroll)
        else:
            outer.addWidget(grid_host)

        outer.addSpacing(4)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_btn = buttons.button(QDialogButtonBox.Save)
        save_btn.setText("Simpan")
        save_btn.setObjectName("primaryButton")
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        cancel_btn.setText("Batal")
        cancel_btn.setObjectName("secondaryButton")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------
    def _create_input(self, spec: FieldSpec) -> QWidget:
        value = self.initial.get(spec.name, spec.default)

        if spec.type == FieldType.TEXTAREA:
            w = QTextEdit()
            w.setFixedHeight(72)
            if value:
                w.setPlainText(str(value))
            return w

        if spec.type == FieldType.BOOL:
            w = QCheckBox()
            w.setChecked(bool(value) if value is not None else False)
            return w

        if spec.type == FieldType.SELECT:
            w = QComboBox()
            w.setEditable(True)
            w.setMinimumHeight(_INPUT_MIN_HEIGHT)
            w.addItems([str(c) for c in spec.choices])
            if value is not None:
                idx = w.findText(str(value))
                if idx >= 0:
                    w.setCurrentIndex(idx)
                else:
                    w.setCurrentText(str(value))
            return w

        if spec.type == FieldType.NUMBER:
            w = QSpinBox()
            w.setMinimumHeight(_INPUT_MIN_HEIGHT)
            w.setRange(-2_147_483_648, 2_147_483_647)
            w.setGroupSeparatorShown(True)
            if value is not None:
                try:
                    w.setValue(int(value))
                except (TypeError, ValueError):
                    pass
            return w

        if spec.type == FieldType.DECIMAL:
            w = QDoubleSpinBox()
            w.setMinimumHeight(_INPUT_MIN_HEIGHT)
            w.setRange(-1_000_000_000_000, 1_000_000_000_000)
            w.setDecimals(2)
            w.setGroupSeparatorShown(True)
            if value is not None:
                try:
                    w.setValue(float(value))
                except (TypeError, ValueError):
                    pass
            return w

        if spec.type in (FieldType.DATE, FieldType.DATETIME):
            w = QDateEdit()
            w.setMinimumHeight(_INPUT_MIN_HEIGHT)
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            if isinstance(value, str) and value:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    w.setDate(QDate(parsed.year, parsed.month, parsed.day))
                except ValueError:
                    w.setDate(QDate.currentDate())
            else:
                w.setDate(QDate.currentDate())
            return w

        # TEXT / UUID / default
        w = QLineEdit()
        w.setMinimumHeight(_INPUT_MIN_HEIGHT)
        if value is not None:
            w.setText(str(value))
        if spec.help_text:
            w.setPlaceholderText(spec.help_text)
        return w

    # ------------------------------------------------------------------
    def _on_accept(self) -> None:
        payload, error = self.collect()
        if error:
            QMessageBox.warning(self, "Data belum lengkap", error)
            return
        self._payload = payload
        self.accept()

    def collect(self) -> tuple[dict[str, Any], str]:
        payload: dict[str, Any] = {}
        for spec in self.fields:
            widget = self._inputs[spec.name]
            value = _extract_value(spec, widget)
            if spec.required and (value is None or value == ""):
                return {}, f"Field '{spec.label}' wajib diisi."
            if value is not None and value != "":
                payload[spec.name] = value
        return payload, ""

    def result_payload(self) -> dict[str, Any]:
        return getattr(self, "_payload", {})


def _extract_value(spec: FieldSpec, widget: QWidget) -> Any:
    if spec.type == FieldType.TEXTAREA:
        text = widget.toPlainText().strip()
        return text or None
    if spec.type == FieldType.BOOL:
        return widget.isChecked()
    if spec.type == FieldType.SELECT:
        text = widget.currentText().strip()
        return text or None
    if spec.type == FieldType.NUMBER:
        return widget.value()
    if spec.type == FieldType.DECIMAL:
        return round(widget.value(), 2)
    if spec.type in (FieldType.DATE, FieldType.DATETIME):
        qd = widget.date()
        return date(qd.year(), qd.month(), qd.day()).isoformat()
    text = widget.text().strip()
    return text or None
