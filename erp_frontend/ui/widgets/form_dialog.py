"""
ui/widgets/form_dialog.py
==========================
Dialog form generik yang dirender otomatis dari `list[FieldSpec]`
(lihat registry/module_registry.py). Dipakai oleh generic_list_page dan
oleh layar-layar khusus untuk sub-form (mis. baris jurnal).

FITUR:
- Field dikelompokkan per `section` (jika ada) dengan judul dan garis pemisah.
- Grid 2 kolom (atau 1 kolom jika section sedikit), TEXTAREA full-width.
- Scroll area hanya jika konten melebihi 70% tinggi layar.
- Tampilan dengan stylesheet modern.
- **Tombol minimize, maximize, close** selalu aktif seperti window biasa.
- Opsi `maximized=True` membuat dialog langsung full-screen saat muncul.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
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

# Field bertipe ini selalu full-width (2 kolom penuh)
_FULL_WIDTH_TYPES = (FieldType.TEXTAREA,)

# Minimum tinggi untuk input widget agar seragam
_INPUT_MIN_HEIGHT = 34

# Stylesheet untuk dialog
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
    """Form auto-generate untuk create/edit satu record, dengan kontrol window."""

    def __init__(
        self,
        title: str,
        fields: list[FieldSpec],
        initial: dict[str, Any] | None = None,
        parent: QWidget | None = None,
        maximized: bool = False,  # True = tampil full-screen
    ):
        super().__init__(parent)

        # --- Buat dialog sebagai window biasa dengan tombol min, max, close ---
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.ApplicationModal)  # tetap modal

        self.setWindowTitle(title)
        self.fields = fields
        self.initial = initial or {}
        self._inputs: dict[str, QWidget] = {}
        self._maximized = maximized

        self.setStyleSheet(_DIALOG_QSS)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 20)
        outer.setSpacing(14)

        title_label = QLabel(self.windowTitle())
        title_label.setObjectName("formDialogTitle")
        outer.addWidget(title_label)

        # Group fields by section
        groups = self._group_by_section()
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(18)

        for section_title, section_fields in groups.items():
            container_layout.addWidget(self._build_section(section_title, section_fields))

        container_layout.addStretch()

        # Tentukan apakah perlu scroll
        content_height = container.sizeHint().height()
        screen = QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 900
        max_content_height = int(available_height * 0.7)

        if content_height > max_content_height:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setMaximumHeight(max_content_height)
            scroll.setWidget(container)
            outer.addWidget(scroll)
        else:
            outer.addWidget(container)

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

        # Lebar minimal berdasarkan jumlah kolom
        max_cols = max(self._section_columns(section_fields) for section_fields in groups.values())
        min_width = 720 if max_cols == 2 else 460
        self.setMinimumWidth(min_width)

    # ------------------------------------------------------------------
    def _group_by_section(self) -> OrderedDict[str, list[FieldSpec]]:
        groups: OrderedDict[str, list[FieldSpec]] = OrderedDict()
        for spec in self.fields:
            key = spec.section or ""
            groups.setdefault(key, []).append(spec)
        return groups

    def _section_columns(self, fields: list[FieldSpec]) -> int:
        if any(f.type in _FULL_WIDTH_TYPES for f in fields):
            return 2
        return 1 if len(fields) <= 3 else 2

    def _build_section(self, title: str, specs: list[FieldSpec]) -> QWidget:
        section_widget = QWidget()
        section_layout = QVBoxLayout(section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)

        if title:
            label = QLabel(title)
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            label.setFont(font)
            label.setStyleSheet("color:#4C1D95; padding-top:2px;")
            section_layout.addWidget(label)

            divider = QFrame()
            divider.setFrameShape(QFrame.HLine)
            divider.setStyleSheet("color:#E5E7EB;")
            section_layout.addWidget(divider)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        num_columns = self._section_columns(specs)
        row = 0
        col = 0
        for spec in specs:
            widget = self._create_input(spec)
            self._inputs[spec.name] = widget

            label_text = spec.label + (" *" if spec.required else "")
            field_label = QLabel(label_text)
            field_label.setObjectName("formFieldLabel")

            if spec.type in _FULL_WIDTH_TYPES:
                if col != 0:
                    row += 1
                    col = 0
                span = (num_columns * 2) - 1
                grid.addWidget(field_label, row, 0, Qt.AlignTop | Qt.AlignRight)
                grid.addWidget(widget, row, 1, 1, span)
                row += 1
            else:
                base = col * 2
                grid.addWidget(field_label, row, base, Qt.AlignRight | Qt.AlignVCenter)
                grid.addWidget(widget, row, base + 1)
                col += 1
                if col >= num_columns:
                    col = 0
                    row += 1

        section_layout.addLayout(grid)
        return section_widget

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

    # ------------------------------------------------------------------
    def showEvent(self, event):
        """Jika maximized=True, tampilkan dalam keadaan maximize."""
        super().showEvent(event)
        if self._maximized:
            self.showMaximized()


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