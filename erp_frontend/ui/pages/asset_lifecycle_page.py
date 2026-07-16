"""
ui/pages/asset_lifecycle_page.py
===================================
Melengkapi gap di modul Fixed Asset, Intangible Asset, dan Goodwill:
sebelumnya cuma ada tombol aksi tanpa bisa lihat hasil/jadwalnya.
Menambahkan Jadwal Depresiasi, Jadwal Amortisasi, dan Uji Impairment
Goodwill lengkap dengan riwayat.

Endpoint backend:
  GET  /fixed-assets/fixed-assets/assets/{id}/depreciation-schedule
  POST /fixed-assets/fixed-assets/depreciation/run
  POST /fixed-assets/fixed-assets/depreciation/{id}/reverse
  GET  /intangible-assets/intangible-assets/{id}/amortization-schedule
  POST /intangible-assets/intangible-assets/amortization/run
  POST /intangible-assets/intangible-assets/amortization/{id}/reverse
  POST /goodwill/goodwill/{id}/impairment-test
  GET  /goodwill/goodwill/{id}/impairment-tests
  POST /goodwill/goodwill/impairment-tests/{id}/recognize
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task

FA_BASE = "/fixed-assets/fixed-assets"
IA_BASE = "/intangible-assets/intangible-assets"
GW_BASE = "/goodwill/goodwill"


class AssetLifecyclePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🏗️  Depresiasi, Amortisasi & Uji Impairment")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(DepreciationTab(), "Depresiasi Aset Tetap")
        self.tabs.addTab(AmortizationTab(), "Amortisasi Aset Tak Berwujud")
        self.tabs.addTab(ImpairmentTab(), "Uji Impairment Goodwill")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class DepreciationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Lihat Jadwal Depresiasi 1 Aset</b>"))
        row = QHBoxLayout()
        self.asset_id_edit = QLineEdit()
        self.asset_id_edit.setPlaceholderText("UUID aset")
        row.addWidget(self.asset_id_edit)
        load_btn = QPushButton("⟳ Tampilkan Jadwal")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load_schedule)
        row.addWidget(load_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Periode", "Beban Depresiasi", "Akumulasi Depresiasi", "Nilai Buku", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Jalankan Depresiasi Batch (Semua Aset atau yang Dipilih)</b>"))
        run_form = QFormLayout()
        self.as_of_date_edit = QDateEdit(QDate.currentDate())
        self.as_of_date_edit.setCalendarPopup(True)
        run_form.addRow("Per Tanggal", self.as_of_date_edit)
        self.asset_ids_edit = QLineEdit()
        self.asset_ids_edit.setPlaceholderText("kosongkan untuk SEMUA aset, atau isi UUID dipisah koma")
        run_form.addRow("Aset Spesifik (opsional)", self.asset_ids_edit)
        self.post_check = QCheckBox("Posting otomatis ke Ledger")
        run_form.addRow("", self.post_check)
        outer.addLayout(run_form)

        run_btn = QPushButton("▶ Jalankan Depresiasi")
        run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(self._run_depreciation)
        outer.addWidget(run_btn)

        reverse_row = QHBoxLayout()
        self.reverse_id_edit = QLineEdit()
        self.reverse_id_edit.setPlaceholderText("ID hasil depresiasi untuk direverse")
        reverse_row.addWidget(self.reverse_id_edit)
        reverse_btn = QPushButton("✘ Reverse")
        reverse_btn.setProperty("class", "danger")
        reverse_btn.clicked.connect(self._reverse)
        reverse_row.addWidget(reverse_btn)
        outer.addLayout(reverse_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load_schedule(self) -> None:
        aid = self.asset_id_edit.text().strip()
        if not aid:
            QMessageBox.information(self, "Info", "Masukkan ID aset.")
            return
        run_task(api_client.get, on_success=self._on_schedule, on_error=self._on_error,
                  path=f"{FA_BASE}/assets/{aid}/depreciation-schedule")

    def _on_schedule(self, data: Any) -> None:
        lines = extract_list(data.get("lines") if isinstance(data, dict) else data)
        self.table.setRowCount(len(lines))
        for r, line in enumerate(lines):
            values = [
                str(line.get("period", "")),
                format_money(line.get("depreciation_expense")),
                format_money(line.get("accumulated_depreciation")),
                format_money(line.get("book_value")),
                str(line.get("status", "")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(lines)} periode ditampilkan.")

    def _run_depreciation(self) -> None:
        confirm = QMessageBox.question(self, "Konfirmasi", "Jalankan depresiasi untuk periode ini?")
        if confirm != QMessageBox.Yes:
            return
        asset_ids = [x.strip() for x in self.asset_ids_edit.text().split(",") if x.strip()]
        payload = {
            "as_of_date": self.as_of_date_edit.date().toString("yyyy-MM-dd"),
            "asset_ids": asset_ids or None,
            "post_to_ledger": self.post_check.isChecked(),
        }
        run_task(api_client.post, on_success=self._on_run_result, on_error=self._on_error,
                  path=f"{FA_BASE}/depreciation/run", json_body=payload)

    def _on_run_result(self, result: Any) -> None:
        data = result or {}
        did = data.get("depreciation_id", data.get("id", ""))
        if did:
            self.reverse_id_edit.setText(str(did))
        self.status_label.setText(
            f"Depresiasi berhasil dijalankan. {data.get('assets_processed', 0)} aset diproses, "
            f"total beban {format_money(data.get('total_depreciation_expense'))}."
        )

    def _reverse(self) -> None:
        did = self.reverse_id_edit.text().strip()
        if not did:
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Reverse hasil depresiasi ini?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Depresiasi di-reverse."),
                  on_error=self._on_error, path=f"{FA_BASE}/depreciation/{did}/reverse")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class AmortizationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Lihat Jadwal Amortisasi 1 Aset</b>"))
        row = QHBoxLayout()
        self.asset_id_edit = QLineEdit()
        self.asset_id_edit.setPlaceholderText("UUID aset")
        row.addWidget(self.asset_id_edit)
        load_btn = QPushButton("⟳ Tampilkan Jadwal")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load_schedule)
        row.addWidget(load_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Periode", "Beban Amortisasi", "Akumulasi Amortisasi", "Nilai Buku", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Jalankan Amortisasi Batch</b>"))
        run_form = QFormLayout()
        self.as_of_date_edit = QDateEdit(QDate.currentDate())
        self.as_of_date_edit.setCalendarPopup(True)
        run_form.addRow("Per Tanggal", self.as_of_date_edit)
        self.asset_ids_edit = QLineEdit()
        self.asset_ids_edit.setPlaceholderText("kosongkan untuk SEMUA aset, atau isi UUID dipisah koma")
        run_form.addRow("Aset Spesifik (opsional)", self.asset_ids_edit)
        self.post_check = QCheckBox("Posting otomatis ke Ledger")
        run_form.addRow("", self.post_check)
        outer.addLayout(run_form)

        run_btn = QPushButton("▶ Jalankan Amortisasi")
        run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(self._run_amortization)
        outer.addWidget(run_btn)

        reverse_row = QHBoxLayout()
        self.reverse_id_edit = QLineEdit()
        self.reverse_id_edit.setPlaceholderText("ID hasil amortisasi untuk direverse")
        reverse_row.addWidget(self.reverse_id_edit)
        reverse_btn = QPushButton("✘ Reverse")
        reverse_btn.setProperty("class", "danger")
        reverse_btn.clicked.connect(self._reverse)
        reverse_row.addWidget(reverse_btn)
        outer.addLayout(reverse_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load_schedule(self) -> None:
        aid = self.asset_id_edit.text().strip()
        if not aid:
            QMessageBox.information(self, "Info", "Masukkan ID aset.")
            return
        run_task(api_client.get, on_success=self._on_schedule, on_error=self._on_error,
                  path=f"{IA_BASE}/{aid}/amortization-schedule")

    def _on_schedule(self, data: Any) -> None:
        lines = extract_list(data.get("lines") if isinstance(data, dict) else data)
        self.table.setRowCount(len(lines))
        for r, line in enumerate(lines):
            values = [
                str(line.get("period", "")),
                format_money(line.get("amortization_expense")),
                format_money(line.get("accumulated_amortization")),
                format_money(line.get("book_value")),
                str(line.get("status", "")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(lines)} periode ditampilkan.")

    def _run_amortization(self) -> None:
        confirm = QMessageBox.question(self, "Konfirmasi", "Jalankan amortisasi untuk periode ini?")
        if confirm != QMessageBox.Yes:
            return
        asset_ids = [x.strip() for x in self.asset_ids_edit.text().split(",") if x.strip()]
        payload = {
            "as_of_date": self.as_of_date_edit.date().toString("yyyy-MM-dd"),
            "asset_ids": asset_ids or None,
            "post_to_ledger": self.post_check.isChecked(),
        }
        run_task(api_client.post, on_success=self._on_run_result, on_error=self._on_error,
                  path=f"{IA_BASE}/amortization/run", json_body=payload)

    def _on_run_result(self, result: Any) -> None:
        data = result or {}
        aid = data.get("amortization_id", data.get("id", ""))
        if aid:
            self.reverse_id_edit.setText(str(aid))
        self.status_label.setText(
            f"Amortisasi berhasil dijalankan. {data.get('assets_processed', 0)} aset diproses."
        )

    def _reverse(self) -> None:
        aid = self.reverse_id_edit.text().strip()
        if not aid:
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Reverse hasil amortisasi ini?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Amortisasi di-reverse."),
                  on_error=self._on_error, path=f"{IA_BASE}/amortization/{aid}/reverse")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class ImpairmentTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Riwayat Uji Impairment Goodwill</b>"))
        row = QHBoxLayout()
        self.goodwill_id_edit = QLineEdit()
        self.goodwill_id_edit.setPlaceholderText("UUID goodwill")
        row.addWidget(self.goodwill_id_edit)
        load_btn = QPushButton("⟳ Lihat Riwayat")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load_history)
        row.addWidget(load_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Tanggal Test", "Nilai Tercatat", "Value in Use", "Rugi Impairment", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Lakukan Uji Impairment Baru</b>"))
        form = QFormLayout()
        self.test_date_edit = QDateEdit(QDate.currentDate())
        self.test_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Test", self.test_date_edit)
        self.value_in_use_edit = QLineEdit()
        self.value_in_use_edit.setPlaceholderText("opsional, nilai pakai (recoverable amount)")
        form.addRow("Value in Use", self.value_in_use_edit)
        self.reason_edit = QLineEdit()
        form.addRow("Alasan Uji", self.reason_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        test_btn = QPushButton("🧪 Lakukan Uji Impairment")
        test_btn.setObjectName("primaryButton")
        test_btn.clicked.connect(self._run_test)
        outer.addWidget(test_btn)

        recognize_row = QHBoxLayout()
        self.recognize_id_edit = QLineEdit()
        self.recognize_id_edit.setPlaceholderText("ID hasil test untuk diakui (posting)")
        recognize_row.addWidget(self.recognize_id_edit)
        recognize_btn = QPushButton("📮 Akui Rugi Impairment")
        recognize_btn.setProperty("class", "danger")
        recognize_btn.clicked.connect(self._recognize)
        recognize_row.addWidget(recognize_btn)
        outer.addLayout(recognize_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load_history(self) -> None:
        gid = self.goodwill_id_edit.text().strip()
        if not gid:
            QMessageBox.information(self, "Info", "Masukkan ID goodwill.")
            return
        run_task(api_client.get, on_success=self._on_history, on_error=self._on_error,
                  path=f"{GW_BASE}/{gid}/impairment-tests")

    def _on_history(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, t in enumerate(rows):
            values = [
                format_date(t.get("test_date")),
                format_money(t.get("carrying_amount")),
                format_money(t.get("value_in_use")),
                format_money(t.get("impairment_loss")),
                str(t.get("status", "")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} riwayat test ditemukan.")

    def _run_test(self) -> None:
        gid = self.goodwill_id_edit.text().strip()
        if not gid:
            QMessageBox.warning(self, "Validasi", "Masukkan ID goodwill dulu.")
            return
        payload = {
            "test_date": self.test_date_edit.date().toString("yyyy-MM-dd"),
            "value_in_use": None,
            "reason": self.reason_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
        }
        if self.value_in_use_edit.text().strip():
            try:
                payload["value_in_use"] = float(Decimal(self.value_in_use_edit.text().strip()))
            except InvalidOperation:
                QMessageBox.warning(self, "Validasi", "Value in use harus angka.")
                return
        run_task(api_client.post, on_success=self._on_test_result, on_error=self._on_error,
                  path=f"{GW_BASE}/{gid}/impairment-test", json_body=payload)

    def _on_test_result(self, result: Any) -> None:
        data = result or {}
        tid = data.get("test_id", data.get("id", ""))
        if tid:
            self.recognize_id_edit.setText(str(tid))
        loss = data.get("impairment_loss")
        self.status_label.setText(
            f"Uji selesai. Rugi impairment: {format_money(loss) if loss else 'Tidak ada penurunan nilai'}."
        )
        self._load_history()

    def _recognize(self) -> None:
        tid = self.recognize_id_edit.text().strip()
        if not tid:
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Akui & posting rugi impairment ini ke ledger?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Rugi impairment diakui & diposting."),
                  on_error=self._on_error, path=f"{GW_BASE}/impairment-tests/{tid}/recognize")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")
