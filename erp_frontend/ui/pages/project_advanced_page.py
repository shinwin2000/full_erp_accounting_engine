"""
ui/pages/project_advanced_page.py
====================================
Melengkapi gap di modul Project: sebelumnya cuma Projects & Timesheet.
Menambahkan Retainer Contract (kontrak jasa bulanan), Pengakuan Pendapatan
(revenue recognition — penting untuk PSAK 72/percentage of completion),
Dashboard, dan Utilisasi tim.

Endpoint backend (base: /projects/projects):
  GET/POST /retainers
  POST     /recognize-revenue
  GET      /dashboard, /utilization
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_money
from core.workers import run_task
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from ui.widgets.kpi_card import KpiCard

BASE = "/projects/projects"


class ProjectAdvancedPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("📁  Retainer, Pengakuan Pendapatan & Dashboard Proyek")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(DashboardTab(), "Dashboard")
        self.tabs.addTab(RetainerTab(), "Retainer Contract")
        self.tabs.addTab(RevenueRecognitionTab(), "Pengakuan Pendapatan")
        self.tabs.addTab(UtilizationTab(), "Utilisasi Tim")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class DashboardTab(QWidget):
    def __init__(self):
        super().__init__()
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

        cards = QHBoxLayout()
        self.card_active = KpiCard("Proyek Aktif", icon="📁", color="#2563EB")
        self.card_revenue = KpiCard("Total Nilai Kontrak", icon="💰", color="#059669")
        self.card_unbilled = KpiCard("Unbilled Revenue", icon="⏳", color="#D97706")
        self.card_margin = KpiCard("Margin Rata-rata", icon="📊", color="#7C3AED")
        cards.addWidget(self.card_active)
        cards.addWidget(self.card_revenue)
        cards.addWidget(self.card_unbilled)
        cards.addWidget(self.card_margin)
        outer.addLayout(cards)
        outer.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/dashboard")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        self.card_active.set_value(str(data.get("active_projects_count", "-")))
        self.card_revenue.set_value(format_money(data.get("total_contract_value")))
        self.card_unbilled.set_value(format_money(data.get("total_unbilled_revenue")))
        margin = data.get("average_margin_percent")
        self.card_margin.set_value(f"{margin}%" if margin is not None else "-")
        self.status_label.setText("Dashboard dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class RetainerTab(QWidget):
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
            ["No. Kontrak", "Fee Bulanan", "Status", "Jam Terpakai", "Sisa Jam", "Total Ditagih"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Buat Retainer Contract Baru</b>"))
        form = QFormLayout()
        self.customer_id_edit = QLineEdit()
        self.customer_id_edit.setPlaceholderText("UUID customer")
        form.addRow("Customer", self.customer_id_edit)
        self.contract_number_edit = QLineEdit()
        form.addRow("No. Kontrak", self.contract_number_edit)
        self.monthly_fee_edit = QLineEdit()
        form.addRow("Fee Bulanan", self.monthly_fee_edit)
        self.start_date_edit = QDateEdit(QDate.currentDate())
        self.start_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Mulai", self.start_date_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        create_btn = QPushButton("+ Buat Retainer Contract")
        create_btn.setObjectName("primaryButton")
        create_btn.clicked.connect(self._create)
        outer.addWidget(create_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/retainers")

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for r, c in enumerate(self._records):
            values = [
                c.get("contract_number", ""),
                format_money(c.get("monthly_fee")),
                str(c.get("status", "")),
                str(c.get("total_hours_used", "")),
                str(c.get("remaining_hours", "") or "-"),
                format_money(c.get("total_invoiced")),
            ]
            for col, v in enumerate(values):
                self.table.setItem(r, col, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} kontrak retainer dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _create(self) -> None:
        try:
            fee = Decimal(self.monthly_fee_edit.text().strip())
            if fee <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Fee bulanan harus > 0.")
            return
        if not (self.customer_id_edit.text().strip() and self.contract_number_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Customer & no. kontrak wajib diisi.")
            return
        payload = {
            "customer_id": self.customer_id_edit.text().strip(),
            "contract_number": self.contract_number_edit.text().strip(),
            "monthly_fee": float(fee),
            "start_date": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self._after("Retainer contract dibuat."),
                  on_error=self._on_write_error, path=f"{BASE}/retainers", json_body=payload)

    def _after(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class RevenueRecognitionTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Hitung & Akui Pendapatan Proyek (PSAK 72 — Percentage of Completion)</b><br>"
            "<span style='color:#6B7280;'>Centang 'Hanya Hitung' untuk simulasi tanpa posting ke ledger.</span>"
        ))
        form = QFormLayout()
        self.period_end_edit = QDateEdit(QDate.currentDate())
        self.period_end_edit.setCalendarPopup(True)
        form.addRow("Akhir Periode", self.period_end_edit)
        self.project_ids_edit = QLineEdit()
        self.project_ids_edit.setPlaceholderText("kosongkan untuk SEMUA proyek, atau UUID dipisah koma")
        form.addRow("Proyek Spesifik (opsional)", self.project_ids_edit)
        self.calculate_only_check = QCheckBox("Hanya Hitung (simulasi, tidak posting)")
        self.calculate_only_check.setChecked(True)
        form.addRow("", self.calculate_only_check)
        outer.addLayout(form)

        run_btn = QPushButton("▶ Hitung Pengakuan Pendapatan")
        run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(self._run)
        outer.addWidget(run_btn)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Proyek", "Sudah Diakui Sebelumnya", "Diakui Periode Ini", "Total Diakui", "Sisa Pendapatan"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _run(self) -> None:
        project_ids = [x.strip() for x in self.project_ids_edit.text().split(",") if x.strip()]
        payload = {
            "period_end_date": self.period_end_edit.date().toString("yyyy-MM-dd"),
            "project_ids": project_ids or None,
            "calculate_only": self.calculate_only_check.isChecked(),
        }
        run_task(api_client.post, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/recognize-revenue", json_body=payload)

    def _on_result(self, payload: Any) -> None:
        rows = extract_list(payload) or (payload if isinstance(payload, list) else [])
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            values = [
                rec.get("project_name", ""),
                format_money(rec.get("previous_recognized")),
                format_money(rec.get("current_recognized")),
                format_money(rec.get("total_recognized")),
                format_money(rec.get("remaining_revenue")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(
            f"{len(rows)} proyek diproses." + (" (SIMULASI, belum diposting)" if self.calculate_only_check.isChecked() else " (sudah diposting)")
        )

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class UtilizationTab(QWidget):
    def __init__(self):
        super().__init__()
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

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Karyawan", "Jam Billable", "Jam Non-Billable", "% Utilisasi"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/utilization")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, u in enumerate(rows):
            values = [
                u.get("employee_name", ""),
                str(u.get("billable_hours", "")),
                str(u.get("non_billable_hours", "")),
                f"{u.get('utilization_percent', 0)}%",
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} karyawan ditampilkan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
