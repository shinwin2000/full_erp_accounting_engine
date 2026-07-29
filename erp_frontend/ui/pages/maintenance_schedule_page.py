"""
ui/pages/maintenance_schedule_page.py
========================================
Melengkapi gap di modul Maintenance: sebelumnya cuma Assets & Work Order.
Menambahkan Jadwal Maintenance Preventif dan pemakaian Spare Parts.

Endpoint backend (base: /maintenance/maintenance):
  GET/POST /schedules, PUT /schedules/{id}
  POST     /spare-parts/usage
  GET      /cost-summary
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

BASE = "/maintenance/maintenance"

MAINTENANCE_TYPES = ["preventive", "corrective", "predictive", "emergency", "routine"]
FREQUENCIES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semi_annual", "annual"]


class MaintenanceSchedulePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🔧  Jadwal Maintenance & Spare Parts")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(ScheduleTab(), "Jadwal Maintenance")
        self.tabs.addTab(SparePartsTab(), "Pemakaian Spare Parts")
        self.tabs.addTab(CostSummaryTab(), "Ringkasan Biaya")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class ScheduleTab(QWidget):
    def __init__(self):
        super().__init__()
        self._records: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Kode Jadwal", "Nama", "Tipe", "Frekuensi", "Jatuh Tempo Berikutnya", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Buat Jadwal Maintenance Baru</b>"))
        form = QFormLayout()
        self.asset_id_edit = QLineEdit()
        self.asset_id_edit.setPlaceholderText("UUID aset maintenance")
        form.addRow("Aset", self.asset_id_edit)
        self.code_edit = QLineEdit()
        form.addRow("Kode Jadwal", self.code_edit)
        self.name_edit = QLineEdit()
        form.addRow("Nama Jadwal", self.name_edit)
        self.type_combo = QComboBox()
        self.type_combo.addItems(MAINTENANCE_TYPES)
        form.addRow("Tipe Maintenance", self.type_combo)
        self.frequency_combo = QComboBox()
        self.frequency_combo.addItems(FREQUENCIES)
        form.addRow("Frekuensi", self.frequency_combo)
        self.custom_interval_edit = QSpinBox()
        self.custom_interval_edit.setRange(0, 3650)
        self.custom_interval_edit.setSpecialValueText("(tidak dipakai)")
        form.addRow("Interval Kustom (hari, opsional)", self.custom_interval_edit)
        self.start_date_edit = QDateEdit(QDate.currentDate())
        self.start_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Mulai", self.start_date_edit)
        self.duration_edit = QLineEdit()
        self.duration_edit.setPlaceholderText("estimasi durasi (jam), opsional")
        form.addRow("Estimasi Durasi (jam)", self.duration_edit)
        self.team_edit = QLineEdit()
        form.addRow("Tim Ditugaskan", self.team_edit)
        outer.addLayout(form)

        create_btn = QPushButton("+ Buat Jadwal")
        create_btn.setObjectName("primaryButton")
        create_btn.clicked.connect(self._create)
        outer.addWidget(create_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/schedules")

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for r, s in enumerate(self._records):
            values = [
                s.get("schedule_code", ""),
                s.get("schedule_name", ""),
                str(s.get("maintenance_type", "")),
                str(s.get("frequency", "")),
                format_date(s.get("next_due_date")),
                str(s.get("status", "")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} jadwal dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _create(self) -> None:
        if not all([self.asset_id_edit.text().strip(), self.code_edit.text().strip(), self.name_edit.text().strip()]):
            QMessageBox.warning(self, "Validasi", "Aset, kode, dan nama jadwal wajib diisi.")
            return
        payload = {
            "asset_id": self.asset_id_edit.text().strip(),
            "schedule_code": self.code_edit.text().strip(),
            "schedule_name": self.name_edit.text().strip(),
            "maintenance_type": self.type_combo.currentText(),
            "frequency": self.frequency_combo.currentText(),
            "custom_interval_days": self.custom_interval_edit.value() or None,
            "start_date": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "assigned_team": self.team_edit.text().strip() or None,
            "is_active": True,
        }
        if self.duration_edit.text().strip():
            try:
                payload["estimated_duration_hours"] = float(Decimal(self.duration_edit.text().strip()))
            except InvalidOperation:
                QMessageBox.warning(self, "Validasi", "Durasi harus angka.")
                return
        run_task(api_client.post, on_success=lambda _r: self._after("Jadwal maintenance dibuat."),
                  on_error=self._on_write_error, path=f"{BASE}/schedules", json_body=payload)

    def _after(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class SparePartsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Catat Pemakaian Spare Part pada Work Order</b>"))
        form = QFormLayout()
        self.item_id_edit = QLineEdit()
        self.item_id_edit.setPlaceholderText("UUID item spare part")
        form.addRow("Spare Part (Item)", self.item_id_edit)
        self.work_order_id_edit = QLineEdit()
        self.work_order_id_edit.setPlaceholderText("UUID work order maintenance")
        form.addRow("Work Order", self.work_order_id_edit)
        self.quantity_edit = QLineEdit()
        form.addRow("Qty Dipakai", self.quantity_edit)
        self.unit_cost_edit = QLineEdit()
        form.addRow("Biaya Satuan", self.unit_cost_edit)
        self.issued_date_edit = QDateEdit(QDate.currentDate())
        self.issued_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Keluar", self.issued_date_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Catat Pemakaian")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            qty = Decimal(self.quantity_edit.text().strip())
            unit_cost = Decimal(self.unit_cost_edit.text().strip())
            if qty <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Qty dan biaya satuan harus angka valid.")
            return
        if not (self.item_id_edit.text().strip() and self.work_order_id_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Item dan work order wajib diisi.")
            return
        payload = {
            "item_id": self.item_id_edit.text().strip(),
            "quantity": float(qty),
            "unit_cost": float(unit_cost),
            "work_order_id": self.work_order_id_edit.text().strip(),
            "issued_date": self.issued_date_edit.date().toString("yyyy-MM-dd"),
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Pemakaian spare part dicatat."),
                  on_error=self._on_error, path=f"{BASE}/spare-parts/usage", json_body=payload)

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class CostSummaryTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.start_date_edit = QDateEdit(QDate.currentDate().addMonths(-1))
        self.start_date_edit.setCalendarPopup(True)
        row.addWidget(QLabel("Dari:"))
        row.addWidget(self.start_date_edit)
        self.end_date_edit = QDateEdit(QDate.currentDate())
        self.end_date_edit.setCalendarPopup(True)
        row.addWidget(QLabel("Sampai:"))
        row.addWidget(self.end_date_edit)
        load_btn = QPushButton("⟳ Tampilkan")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Kategori Biaya", "Jumlah"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        params = {
            "start_date": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date_edit.date().toString("yyyy-MM-dd"),
        }
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/cost-summary", params=params)

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        rows = [(k.replace("_", " ").title(), v) for k, v in data.items()]
        self.table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(k))
            self.table.setItem(r, 1, QTableWidgetItem(format_money(v) if isinstance(v, (int, float)) else str(v)))
        self.table.resizeColumnsToContents()
        self.status_label.setText("Ringkasan biaya dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
