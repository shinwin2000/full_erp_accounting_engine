"""
ui/pages/budget_advanced_page.py
===================================
Melengkapi gap di modul Budget: sebelumnya cuma CRUD budget dasar.
Menambahkan Dashboard, Alert budget, Transfer anggaran antar akun,
Rolling Forecast, Versioning, dan laporan Budget vs Actual.

Endpoint backend (base: /budget/budget):
  GET  /dashboard, /alerts
  POST /transfer, /rolling-forecast
  GET  /versions/{budget_code}, /vs-actual/{id}, /vs-actual-ytd/{id}
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from PySide6.QtCore import QDate as _QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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
from ui.widgets.kpi_card import KpiCard

BASE = "/budget/budget"


class BudgetAdvancedPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("📅  Budget Advanced: Alert, Transfer, Forecast & vs-Actual")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(DashboardTab(), "Dashboard")
        self.tabs.addTab(AlertsTab(), "Alert Budget")
        self.tabs.addTab(TransferTab(), "Transfer Anggaran")
        self.tabs.addTab(RollingForecastTab(), "Rolling Forecast")
        self.tabs.addTab(VersionsTab(), "Versi Budget")
        self.tabs.addTab(VsActualTab(), "Budget vs Actual")
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
        self.card_total_budget = KpiCard("Total Anggaran", icon="📅", color="#2563EB")
        self.card_total_actual = KpiCard("Total Realisasi", icon="💰", color="#059669")
        self.card_variance = KpiCard("Variance", icon="📊", color="#D97706")
        self.card_pct = KpiCard("% Terpakai", icon="📈", color="#7C3AED")
        cards.addWidget(self.card_total_budget)
        cards.addWidget(self.card_total_actual)
        cards.addWidget(self.card_variance)
        cards.addWidget(self.card_pct)
        outer.addLayout(cards)
        outer.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/dashboard")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        self.card_total_budget.set_value(format_money(data.get("total_budget")))
        self.card_total_actual.set_value(format_money(data.get("total_actual")))
        self.card_variance.set_value(format_money(data.get("total_variance")))
        pct = data.get("consumption_percent")
        self.card_pct.set_value(f"{pct}%" if pct is not None else "-")
        self.status_label.setText("Dashboard dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class AlertsTab(QWidget):
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

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Budget", "Akun", "Anggaran", "Realisasi", "% Terpakai", "Tingkat"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/alerts")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            severity = str(a.get("severity", ""))
            values = [
                a.get("budget_name", ""),
                f"{a.get('account_code', '')} — {a.get('account_name', '')}",
                format_money(a.get("budget_amount")),
                format_money(a.get("actual_amount")),
                f"{a.get('consumption_percent', 0):.1f}%",
                severity.upper(),
            ]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c == 5:
                    item.setForeground(QColor("#DC2626" if severity == "critical" else "#D97706"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} alert ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class TransferTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Transfer Anggaran Antar Akun</b>"))
        form = QFormLayout()
        self.from_account_edit = QLineEdit()
        self.from_account_edit.setPlaceholderText("UUID akun asal")
        form.addRow("Dari Akun", self.from_account_edit)
        self.to_account_edit = QLineEdit()
        self.to_account_edit.setPlaceholderText("UUID akun tujuan")
        form.addRow("Ke Akun", self.to_account_edit)
        self.amount_edit = QLineEdit()
        form.addRow("Jumlah", self.amount_edit)
        self.reason_edit = QLineEdit()
        form.addRow("Alasan", self.reason_edit)
        self.effective_date_edit = QDateEdit(_QDate.currentDate())
        self.effective_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Efektif", self.effective_date_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Transfer Anggaran")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus > 0.")
            return
        if not all([self.from_account_edit.text().strip(), self.to_account_edit.text().strip(),
                    self.reason_edit.text().strip()]):
            QMessageBox.warning(self, "Validasi", "Akun asal, tujuan, dan alasan wajib diisi.")
            return
        payload = {
            "from_account_id": self.from_account_edit.text().strip(),
            "to_account_id": self.to_account_edit.text().strip(),
            "amount": float(amount),
            "reason": self.reason_edit.text().strip(),
            "effective_date": self.effective_date_edit.date().toString("yyyy-MM-dd"),
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/transfer", json_body=payload)

    def _on_ok(self, _r: Any) -> None:
        self.status_label.setText("Transfer anggaran berhasil.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class RollingForecastTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Buat Rolling Forecast dari Budget yang Sudah Ada</b>"))
        form = QFormLayout()
        self.base_budget_edit = QLineEdit()
        self.base_budget_edit.setPlaceholderText("UUID budget dasar")
        form.addRow("Budget Dasar", self.base_budget_edit)
        self.months_edit = QSpinBox()
        self.months_edit.setRange(1, 36)
        self.months_edit.setValue(12)
        form.addRow("Jumlah Bulan Forecast", self.months_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Buat Rolling Forecast")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        if not self.base_budget_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Budget dasar wajib diisi.")
            return
        payload = {
            "base_budget_id": self.base_budget_edit.text().strip(),
            "forecast_months": self.months_edit.value(),
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Rolling forecast berhasil dibuat."),
                  on_error=self._on_error, path=f"{BASE}/rolling-forecast", json_body=payload)

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class VersionsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Kode budget")
        row.addWidget(self.code_edit)
        load_btn = QPushButton("⟳ Lihat Riwayat Versi")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Versi", "Status", "Total Anggaran", "Tanggal Efektif"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        code = self.code_edit.text().strip()
        if not code:
            QMessageBox.information(self, "Info", "Masukkan kode budget.")
            return
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/versions/{code}")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            values = [
                v.get("version", ""),
                str(v.get("status", "")),
                format_money(v.get("total_amount")),
                format_date(v.get("effective_date")),
            ]
            for c, val in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} versi ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class VsActualTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.budget_id_edit = QLineEdit()
        self.budget_id_edit.setPlaceholderText("UUID budget")
        row.addWidget(self.budget_id_edit)
        load_btn = QPushButton("⟳ Lihat Budget vs Actual")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        load_ytd_btn = QPushButton("⟳ Lihat vs Actual (YTD)")
        load_ytd_btn.clicked.connect(self._load_ytd)
        row.addWidget(load_ytd_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Akun", "Anggaran", "Realisasi", "Variance", "% Variance"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        bid = self.budget_id_edit.text().strip()
        if not bid:
            QMessageBox.information(self, "Info", "Masukkan ID budget.")
            return
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/vs-actual/{bid}")

    def _load_ytd(self) -> None:
        bid = self.budget_id_edit.text().strip()
        if not bid:
            QMessageBox.information(self, "Info", "Masukkan ID budget.")
            return
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/vs-actual-ytd/{bid}")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, line in enumerate(rows):
            values = [
                f"{line.get('account_code', '')} — {line.get('account_name', '')}",
                format_money(line.get("budget_amount")),
                format_money(line.get("actual_amount")),
                format_money(line.get("variance")),
                f"{line.get('variance_percent', 0):.1f}%",
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} akun ditampilkan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
