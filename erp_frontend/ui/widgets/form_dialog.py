"""
ui/widgets/form_dialog.py
==========================
Dialog form generik yang dirender otomatis dari `list[FieldSpec]`
(lihat registry/module_registry.py). Dipakai oleh generic_list_page dan
oleh layar-layar khusus untuk sub-form (mis. baris jurnal).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
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


class FormDialog(QDialog):
    """Form auto-generate untuk create/edit satu record."""

    def __init__(
        self,
        title: str,
        fields: list[FieldSpec],
        initial: Optional[dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self.fields = fields
        self.initial = initial or {}
        self._inputs: dict[str, QWidget] = {}
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        container = QWidget()
        form = QFormLayout(container)
        form.setSpacing(10)
        form.setLabelAlignment(Qt_AlignRight())

        for spec in self.fields:
            widget = self._create_input(spec)
            self._inputs[spec.name] = widget
            label_text = spec.label + (" *" if spec.required else "")
            form.addRow(label_text, widget)

        scroll.setWidget(container)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Cancel).setText("Batal")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------
    def _create_input(self, spec: FieldSpec) -> QWidget:
        value = self.initial.get(spec.name, spec.default)

        if spec.type == FieldType.TEXTAREA:
            w = QTextEdit()
            w.setFixedHeight(80)
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


def Qt_AlignRight():
    from PySide6.QtCore import Qt as _Qt
    return _Qt.AlignRight | _Qt.AlignVCenter
