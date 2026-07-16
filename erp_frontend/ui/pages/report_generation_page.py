"""
ui/pages/report_generation_page.py
=====================================
Melengkapi gap PENTING di modul Report: sebelumnya cuma kelola JADWAL
laporan, tidak bisa generate laporan ad-hoc kapan saja. Menambahkan
generate laporan on-demand (Financial, Ledger, Subledger, Inventory,
Tax, Analytics, Budget) dengan pilihan format PDF/Excel/CSV/HTML, lalu
download hasilnya.

Endpoint backend (base: /reports/reports):
  POST /financial/balance-sheet, /financial/income-statement,
       /financial/cash-flow, /financial/equity-statement
  POST /ledger/trial-balance, /ledger/general-ledger
  POST /subledger/ar-aging, /subledger/ap-aging
  POST /inventory/stock-card
  POST /tax/summary
  POST /analytics/financial-ratios
  POST /budget/vs-actual
  GET  /{id}, /{id}/download, /{id}/status, /{id}/history
  POST /{id}/send
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
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

from core.api_client import api_client
from core.formatting import extract_list, format_datetime
from core.workers import run_task

BASE = "/reports/reports"

REPORT_TYPES = {
    "Neraca (Balance Sheet)": ("financial/balance-sheet", "as_of", "BALANCE_SHEET"),
    "Laba Rugi (Income Statement)": ("financial/income-statement", "range", "INCOME_STATEMENT"),
    "Arus Kas (Cash Flow)": ("financial/cash-flow", "range", "CASH_FLOW"),
    "Perubahan Ekuitas": ("financial/equity-statement", "range", "EQUITY_STATEMENT"),
    "Neraca Saldo (Trial Balance)": ("ledger/trial-balance", "as_of", "TRIAL_BALANCE"),
    "General Ledger": ("ledger/general-ledger", "range", "GENERAL_LEDGER"),
    "AR Aging": ("subledger/ar-aging", "as_of", "AR_AGING"),
    "AP Aging": ("subledger/ap-aging", "as_of", "AP_AGING"),
    "Kartu Stok": ("inventory/stock-card", "range", "STOCK_CARD"),
    "Ringkasan Pajak": ("tax/summary", "range", "TAX_SUMMARY"),
    "Rasio Keuangan": ("analytics/financial-ratios", "as_of", "FINANCIAL_RATIOS"),
    "Budget vs Actual": ("budget/vs-actual", "range", "BUDGET_VS_ACTUAL"),
}
FORMATS = ["pdf", "xlsx", "csv", "html"]


class ReportGenerationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🗂️  Generate Laporan Ad-hoc")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(GenerateTab(), "Generate Laporan")
        self.tabs.addTab(HistoryTab(), "Riwayat Laporan")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class GenerateTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        form = QFormLayout()

        self.report_combo = QComboBox()
        self.report_combo.addItems(list(REPORT_TYPES.keys()))
        self.report_combo.currentTextChanged.connect(self._on_type_changed)
        form.addRow("Jenis Laporan", self.report_combo)

        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS)
        form.addRow("Format", self.format_combo)

        self.as_of_date_edit = QDateEdit(QDate.currentDate())
        self.as_of_date_edit.setCalendarPopup(True)
        form.addRow("Per Tanggal", self.as_of_date_edit)

        self.start_date_edit = QDateEdit(QDate.currentDate().addMonths(-1))
        self.start_date_edit.setCalendarPopup(True)
        form.addRow("Dari Tanggal", self.start_date_edit)

        self.end_date_edit = QDateEdit(QDate.currentDate())
        self.end_date_edit.setCalendarPopup(True)
        form.addRow("Sampai Tanggal", self.end_date_edit)

        self.include_details_check = QCheckBox("Sertakan Detail")
        self.include_details_check.setChecked(True)
        form.addRow("", self.include_details_check)

        self.compare_check = QCheckBox("Bandingkan dengan Periode Sebelumnya")
        form.addRow("", self.compare_check)

        self.currency_edit = QLineEdit("IDR")
        form.addRow("Mata Uang", self.currency_edit)

        outer.addLayout(form)
        self._on_type_changed(self.report_combo.currentText())

        generate_btn = QPushButton("📄 Generate Laporan")
        generate_btn.setObjectName("primaryButton")
        generate_btn.clicked.connect(self._generate)
        outer.addWidget(generate_btn)

        result_row = QHBoxLayout()
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        result_row.addWidget(self.result_label, stretch=1)
        outer.addLayout(result_row)

        download_row = QHBoxLayout()
        self.report_id_edit = QLineEdit()
        self.report_id_edit.setPlaceholderText("ID laporan untuk didownload")
        download_row.addWidget(self.report_id_edit)
        download_btn = QPushButton("⬇ Download")
        download_btn.clicked.connect(self._download)
        download_row.addWidget(download_btn)
        send_btn = QPushButton("✉ Kirim via Email")
        send_btn.clicked.connect(self._send)
        download_row.addWidget(send_btn)
        outer.addLayout(download_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _on_type_changed(self, report_name: str) -> None:
        _, mode, _ = REPORT_TYPES[report_name]
        is_range = mode == "range"
        self.start_date_edit.setVisible(is_range)
        self.end_date_edit.setVisible(is_range)
        self.as_of_date_edit.setVisible(not is_range)

    def _generate(self) -> None:
        report_name = self.report_combo.currentText()
        endpoint, mode, report_type = REPORT_TYPES[report_name]
        payload = {
            "report_type": report_type,
            "report_format": self.format_combo.currentText(),
            "include_details": self.include_details_check.isChecked(),
            "compare_with_previous": self.compare_check.isChecked(),
            "currency": self.currency_edit.text().strip() or "IDR",
        }
        if mode == "as_of":
            payload["as_of_date"] = self.as_of_date_edit.date().toString("yyyy-MM-dd")
        else:
            payload["start_date"] = self.start_date_edit.date().toString("yyyy-MM-dd")
            payload["end_date"] = self.end_date_edit.date().toString("yyyy-MM-dd")

        self.status_label.setText("Sedang generate laporan...")
        run_task(api_client.post, on_success=self._on_generated, on_error=self._on_error,
                  path=f"{BASE}/{endpoint}", json_body=payload)

    def _on_generated(self, data: Any) -> None:
        data = data or {}
        rid = data.get("report_id", "")
        if rid:
            self.report_id_edit.setText(str(rid))
        self.result_label.setText(
            f"<b>No. Laporan:</b> {data.get('report_number', '-')}<br>"
            f"<b>Status:</b> {data.get('status', '-')}<br>"
            f"<b>Ukuran File:</b> {data.get('file_size_bytes', '-')} bytes"
        )
        self.status_label.setText("Laporan berhasil digenerate.")

    def _download(self) -> None:
        rid = self.report_id_edit.text().strip()
        if not rid:
            QMessageBox.information(self, "Info", "Isi ID laporan dulu (otomatis terisi setelah generate).")
            return
        ext = self.format_combo.currentText()
        save_path, _ = QFileDialog.getSaveFileName(self, "Simpan Laporan", f"report_{rid}.{ext}")
        if not save_path:
            return
        run_task(api_client.download_file, on_success=lambda p: self.status_label.setText(f"Disimpan ke {p}"),
                  on_error=self._on_error, path=f"{BASE}/{rid}/download", save_path=save_path)

    def _send(self) -> None:
        rid = self.report_id_edit.text().strip()
        if not rid:
            QMessageBox.information(self, "Info", "Isi ID laporan dulu.")
            return
        from PySide6.QtWidgets import QInputDialog
        email, ok = QInputDialog.getText(self, "Kirim Laporan", "Email tujuan:")
        if not ok or not email.strip():
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Laporan terkirim."),
                  on_error=self._on_error, path=f"{BASE}/{rid}/send", json_body={"email": email.strip()})

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class HistoryTab(QWidget):
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

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["No. Laporan", "Tipe", "Format", "Status", "Digenerate Pada"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=BASE, params={"page_size": 100})

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            values = [
                rec.get("report_number", ""),
                str(rec.get("report_type", "")),
                str(rec.get("report_format", "")),
                str(rec.get("status", "")),
                format_datetime(rec.get("generated_at")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} laporan ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
