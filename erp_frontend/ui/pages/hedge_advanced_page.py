"""
ui/pages/hedge_advanced_page.py
==================================
Melengkapi gap di modul Hedge: sebelumnya cuma CRUD derivatif & hedge
relationship. Menambahkan pengukuran Fair Value (IFRS 13), pengakuan
ketidakefektifan hedge (hedge ineffectiveness), dan dashboard.

Endpoint backend (base: /hedge/hedge):
  POST /fair-value                        - catat pengukuran fair value instrumen
  GET  /fair-value/{instrument_id}        - riwayat fair value instrumen
  POST /ineffectiveness/recognize         - akui & posting ketidakefektifan hedge
  GET  /dashboard                         - ringkasan hedge portfolio
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from ui.widgets.kpi_card import KpiCard

BASE = "/hedge/hedge"
FAIR_VALUE_LEVELS = ["level_1", "level_2", "level_3"]


class HedgeAdvancedPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("📈  Fair Value, Ketidakefektifan Hedge & Dashboard")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(FairValueTab(), "Pengukuran Fair Value")
        self.tabs.addTab(IneffectivenessTab(), "Ketidakefektifan Hedge")
        self.tabs.addTab(DashboardTab(), "Dashboard")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class FairValueTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Riwayat Pengukuran Fair Value</b>"))
        row = QHBoxLayout()
        self.instrument_id_edit = QLineEdit()
        self.instrument_id_edit.setPlaceholderText("UUID instrumen derivatif")
        row.addWidget(self.instrument_id_edit)
        load_btn = QPushButton("⟳ Lihat Riwayat")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load_history)
        row.addWidget(load_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tanggal Pengukuran", "Fair Value", "Level Input", "Teknik Penilaian"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Catat Pengukuran Fair Value Baru (IFRS 13)</b>"))
        form = QFormLayout()
        self.instrument_type_edit = QLineEdit()
        self.instrument_type_edit.setPlaceholderText("mis. forward, option, swap")
        form.addRow("Tipe Instrumen", self.instrument_type_edit)
        self.measurement_date_edit = QDateEdit(QDate.currentDate())
        self.measurement_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Pengukuran", self.measurement_date_edit)
        self.fair_value_edit = QLineEdit()
        form.addRow("Fair Value", self.fair_value_edit)
        self.level_combo = QComboBox()
        self.level_combo.addItems(FAIR_VALUE_LEVELS)
        form.addRow("Level Input (Hierarki IFRS 13)", self.level_combo)
        self.technique_edit = QLineEdit()
        self.technique_edit.setPlaceholderText("mis. discounted cash flow, Black-Scholes")
        form.addRow("Teknik Penilaian", self.technique_edit)
        self.valuer_edit = QLineEdit()
        form.addRow("Penilai", self.valuer_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Catat Pengukuran")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load_history(self) -> None:
        iid = self.instrument_id_edit.text().strip()
        if not iid:
            QMessageBox.information(self, "Info", "Masukkan ID instrumen.")
            return
        run_task(api_client.get, on_success=self._on_history, on_error=self._on_error,
                  path=f"{BASE}/fair-value/{iid}")

    def _on_history(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, fv in enumerate(rows):
            values = [
                format_date(fv.get("measurement_date")),
                format_money(fv.get("fair_value")),
                str(fv.get("level_input", "")),
                fv.get("valuation_technique", "") or "-",
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} pengukuran ditemukan.")

    def _submit(self) -> None:
        iid = self.instrument_id_edit.text().strip()
        if not iid:
            QMessageBox.warning(self, "Validasi", "ID instrumen wajib diisi (di kolom atas).")
            return
        try:
            fv = Decimal(self.fair_value_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Fair value harus angka.")
            return
        if not self.instrument_type_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Tipe instrumen wajib diisi.")
            return
        payload = {
            "instrument_id": iid,
            "instrument_type": self.instrument_type_edit.text().strip(),
            "measurement_date": self.measurement_date_edit.date().toString("yyyy-MM-dd"),
            "fair_value": float(fv),
            "level_input": self.level_combo.currentText(),
            "valuation_technique": self.technique_edit.text().strip() or None,
            "valuer_name": self.valuer_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self._after("Pengukuran fair value dicatat."),
                  on_error=self._on_error, path=f"{BASE}/fair-value", json_body=payload)

    def _after(self, msg: str) -> None:
        self.status_label.setText(msg)
        self._load_history()

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class IneffectivenessTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Akui Ketidakefektifan Hedge</b><br>"
            "<span style='color:#6B7280;'>Bagian dari perubahan nilai wajar instrumen hedge yang tidak "
            "efektif harus diakui langsung ke laba rugi (bukan OCI) sesuai PSAK 71/IFRS 9.</span>"
        ))
        form = QFormLayout()
        self.period_end_edit = QDateEdit(QDate.currentDate())
        self.period_end_edit.setCalendarPopup(True)
        form.addRow("Akhir Periode", self.period_end_edit)
        self.post_check = QCheckBox("Posting otomatis ke Ledger")
        form.addRow("", self.post_check)
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(60)
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("📮 Akui Ketidakefektifan")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        outer.addWidget(self.result_text, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        confirm = QMessageBox.question(self, "Konfirmasi", "Akui ketidakefektifan hedge untuk periode ini?")
        if confirm != QMessageBox.Yes:
            return
        payload = {
            "period_end_date": self.period_end_edit.date().toString("yyyy-MM-dd"),
            "post_to_ledger": self.post_check.isChecked(),
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/ineffectiveness/recognize", json_body=payload)

    def _on_result(self, data: Any) -> None:
        data = data or {}
        lines = [
            f"Total Ketidakefektifan Diakui: {format_money(data.get('total_ineffectiveness'))}",
            f"Jumlah Hedge Relationship Diproses: {data.get('relationships_processed', 0)}",
        ]
        self.result_text.setPlainText("\n".join(lines))
        self.status_label.setText("Berhasil diakui.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


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
        self.card_notional = KpiCard("Total Notional", icon="📈", color="#2563EB")
        self.card_fair_value = KpiCard("Total Fair Value", icon="💰", color="#059669")
        self.card_effective = KpiCard("Hedge Efektif", icon="✅", color="#059669")
        self.card_ineffective = KpiCard("Hedge Tidak Efektif", icon="⚠️", color="#DC2626")
        cards.addWidget(self.card_notional)
        cards.addWidget(self.card_fair_value)
        cards.addWidget(self.card_effective)
        cards.addWidget(self.card_ineffective)
        outer.addLayout(cards)
        outer.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/dashboard")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        self.card_notional.set_value(format_money(data.get("total_notional")))
        self.card_fair_value.set_value(format_money(data.get("total_fair_value")))
        self.card_effective.set_value(str(data.get("effective_count", "-")))
        self.card_ineffective.set_value(str(data.get("ineffective_count", "-")))
        self.status_label.setText("Dashboard dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
