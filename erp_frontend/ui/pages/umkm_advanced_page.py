"""
ui/pages/umkm_advanced_page.py
=================================
Melengkapi gap di modul UMKM: sebelumnya cuma jurnal sederhana.
Menambahkan Profil Usaha, Bagan Akun Sederhana (read-only), Kepatuhan
Pajak PPh Final 0.5%, dan Laporan Sederhana (Laba Rugi/Neraca/Arus Kas).

Endpoint backend (base: /umkm/umkm):
  GET/PUT /profile
  GET     /accounts
  GET     /tax-compliance?period_year=&period_month=
  GET     /reports/income-statement, /reports/balance-sheet, /reports/cash-flow
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from ui.widgets.kpi_card import KpiCard

BASE = "/umkm/umkm"


class UmkmAdvancedPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🏪  Profil UMKM, Bagan Akun & Kepatuhan Pajak")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(ProfileTab(), "Profil Usaha")
        self.tabs.addTab(AccountsTab(), "Bagan Akun Sederhana")
        self.tabs.addTab(TaxComplianceTab(), "Kepatuhan Pajak (PPh Final)")
        self.tabs.addTab(ReportsTab(), "Laporan Sederhana")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class ProfileTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.business_name_edit = QLineEdit()
        form.addRow("Nama Usaha", self.business_name_edit)
        self.business_type_edit = QLineEdit()
        self.business_type_edit.setPlaceholderText("mis. Perdagangan, Jasa, Manufaktur")
        form.addRow("Jenis Usaha", self.business_type_edit)
        self.npwp_edit = QLineEdit()
        form.addRow("NPWP", self.npwp_edit)
        self.industry_edit = QLineEdit()
        form.addRow("Industri", self.industry_edit)
        self.uses_final_tax_check = QCheckBox("Menggunakan PPh Final 0.5% (PP 23/2018)")
        self.uses_final_tax_check.setChecked(True)
        form.addRow("", self.uses_final_tax_check)
        self.accounting_method_combo = QComboBox()
        self.accounting_method_combo.addItems(["cash_basis", "accrual_basis"])
        form.addRow("Metode Akuntansi", self.accounting_method_combo)
        self.fiscal_year_start_edit = QSpinBox()
        self.fiscal_year_start_edit.setRange(1, 12)
        self.fiscal_year_start_edit.setValue(1)
        form.addRow("Awal Tahun Fiskal (bulan)", self.fiscal_year_start_edit)
        self.reminder_days_edit = QSpinBox()
        self.reminder_days_edit.setRange(0, 30)
        self.reminder_days_edit.setValue(7)
        form.addRow("Reminder Pajak (hari sebelum)", self.reminder_days_edit)
        outer.addLayout(form)

        save_btn = QPushButton("💾 Simpan Profil")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save)
        outer.addWidget(save_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/profile")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        self.business_name_edit.setText(data.get("business_name", ""))
        self.business_type_edit.setText(data.get("business_type", ""))
        self.npwp_edit.setText(data.get("npwp") or "")
        self.industry_edit.setText(data.get("industry") or "")
        self.uses_final_tax_check.setChecked(bool(data.get("uses_final_tax", True)))
        idx = self.accounting_method_combo.findText(data.get("accounting_method", "cash_basis"))
        if idx >= 0:
            self.accounting_method_combo.setCurrentIndex(idx)
        self.fiscal_year_start_edit.setValue(data.get("fiscal_year_start", 1))
        self.reminder_days_edit.setValue(data.get("tax_submission_reminder_days", 7))
        self.status_label.setText("Profil dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Profil belum ada / gagal dimuat: {message}")

    def _save(self) -> None:
        if not (self.business_name_edit.text().strip() and self.business_type_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Nama & jenis usaha wajib diisi.")
            return
        payload = {
            "business_name": self.business_name_edit.text().strip(),
            "business_type": self.business_type_edit.text().strip(),
            "npwp": self.npwp_edit.text().strip() or None,
            "industry": self.industry_edit.text().strip() or None,
            "uses_final_tax": self.uses_final_tax_check.isChecked(),
            "accounting_method": self.accounting_method_combo.currentText(),
            "fiscal_year_start": self.fiscal_year_start_edit.value(),
            "tax_submission_reminder_days": self.reminder_days_edit.value(),
        }
        run_task(api_client.put, on_success=lambda _r: self.status_label.setText("Profil disimpan."),
                  on_error=self._on_write_error, path=f"{BASE}/profile", json_body=payload)

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class AccountsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.addItems(["Semua", "ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"])
        self.type_filter.currentTextChanged.connect(lambda _t: self.refresh())
        row.addWidget(self.type_filter)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Kode Akun", "Nama Akun", "Tipe"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        params = {}
        if self.type_filter.currentText() != "Semua":
            params["account_type"] = self.type_filter.currentText()
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/accounts", params=params)

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload) or (payload if isinstance(payload, list) else [])
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            values = [a.get("account_code", ""), a.get("account_name", ""), a.get("account_type", "")]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} akun ditampilkan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class TaxComplianceTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.year_edit = QSpinBox()
        self.year_edit.setRange(2024, 2100)
        self.year_edit.setValue(QDate.currentDate().year())
        row.addWidget(QLabel("Tahun:"))
        row.addWidget(self.year_edit)
        self.month_edit = QSpinBox()
        self.month_edit.setRange(1, 12)
        self.month_edit.setValue(QDate.currentDate().month())
        row.addWidget(QLabel("Bulan:"))
        row.addWidget(self.month_edit)
        load_btn = QPushButton("⟳ Cek Kepatuhan Pajak")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        outer.addLayout(row)

        cards = QHBoxLayout()
        self.card_revenue_period = KpiCard("Omzet Bulan Ini", icon="💰", color="#2563EB")
        self.card_revenue_ytd = KpiCard("Omzet YTD", icon="📊", color="#059669")
        self.card_pph = KpiCard("Estimasi PPh Final (0.5%)", icon="🧾", color="#D97706")
        cards.addWidget(self.card_revenue_period)
        cards.addWidget(self.card_revenue_ytd)
        cards.addWidget(self.card_pph)
        outer.addLayout(cards)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        outer.addWidget(self.info_label)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        params = {"period_year": self.year_edit.value(), "period_month": self.month_edit.value()}
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/tax-compliance", params=params)

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        self.card_revenue_period.set_value(format_money(data.get("total_revenue_period")))
        self.card_revenue_ytd.set_value(format_money(data.get("total_revenue_ytd")))
        self.card_pph.set_value(format_money(data.get("estimated_pph_final")))
        required = "WAJIB LAPOR" if data.get("is_required_to_file") else "Tidak wajib lapor periode ini"
        self.info_label.setText(
            f"<b>Status:</b> {required}<br>"
            f"<b>Batas Waktu Setor:</b> {format_date(data.get('submission_deadline'))}<br>"
            f"<b>Reminder:</b> {data.get('tax_due_reminder', '-')}<br>"
            f"<b>Catatan:</b> {data.get('notes') or '-'}"
        )
        self.status_label.setText("Data kepatuhan pajak dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class ReportsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.report_combo = QComboBox()
        self.report_combo.addItems(["Laba Rugi", "Neraca", "Arus Kas"])
        row.addWidget(self.report_combo)
        load_btn = QPushButton("⟳ Tampilkan")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Keterangan", "Jumlah"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        endpoint_map = {
            "Laba Rugi": "reports/income-statement",
            "Neraca": "reports/balance-sheet",
            "Arus Kas": "reports/cash-flow",
        }
        endpoint = endpoint_map[self.report_combo.currentText()]
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/{endpoint}")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        rows = []

        def walk(d: dict, prefix: str = ""):
            for k, v in d.items():
                if isinstance(v, dict):
                    walk(v, f"{prefix}{k} - ")
                elif isinstance(v, list):
                    continue
                else:
                    rows.append((f"{prefix}{k}".replace("_", " ").title(), v))

        walk(data)
        self.table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(k))
            val_str = format_money(v) if isinstance(v, (int, float)) else str(v)
            self.table.setItem(r, 1, QTableWidgetItem(val_str))
        self.table.resizeColumnsToContents()
        self.status_label.setText("Laporan dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
