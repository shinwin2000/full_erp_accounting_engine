"""
ui/pages/audit_forensic_page.py
==================================
Melengkapi gap di modul Audit: sebelumnya cuma daftar temuan (findings).
Menambahkan verifikasi hash-chain integrity, uji kontrol SOX, deteksi gap
event, dan generate laporan audit — fitur compliance/forensik paling
penting untuk audit trail bank-grade.

Endpoint backend (base: /audit/audit):
  POST /hash-chain/verify, GET /hash-chain/status, GET /integrity/verify-all
  POST /gap-detection
  POST /sox/control-test, GET /sox/controls
  POST /report, GET /report/{id}/download
  GET  /trail/{entity_type}/{entity_id}
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, QDateTime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDateTimeEdit,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list
from core.workers import run_task

BASE = "/audit/audit"


class AuditForensicPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🕵️  Audit Forensik & Kepatuhan (Hash-chain, SOX)")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(HashChainTab(), "Hash-chain Integrity")
        self.tabs.addTab(GapDetectionTab(), "Deteksi Gap Event")
        self.tabs.addTab(SoxTab(), "Kontrol SOX")
        self.tabs.addTab(AuditTrailTab(), "Audit Trail")
        self.tabs.addTab(ReportGenerationTab(), "Generate Laporan Audit")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class HashChainTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_status()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        self.status_summary = QLabel("Memuat status hash-chain...")
        self.status_summary.setStyleSheet("font-weight:600;")
        outer.addWidget(self.status_summary)

        self.chain_table = QTableWidget(0, 3)
        self.chain_table.setHorizontalHeaderLabels(["Chain Type", "Chain ID", "Status"])
        self.chain_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.chain_table, stretch=1)

        refresh_btn = QPushButton("⟳ Refresh Status")
        refresh_btn.clicked.connect(self._load_status)
        outer.addWidget(refresh_btn)

        outer.addWidget(QLabel("<b>Verifikasi Manual 1 Chain</b>"))
        form = QFormLayout()
        self.chain_type_edit = QLineEdit()
        self.chain_type_edit.setPlaceholderText("audit / event / snapshot")
        form.addRow("Tipe Chain", self.chain_type_edit)
        self.chain_id_edit = QLineEdit()
        self.chain_id_edit.setPlaceholderText("UUID chain")
        form.addRow("Chain ID", self.chain_id_edit)
        outer.addLayout(form)
        verify_btn = QPushButton("🔒 Verifikasi Chain Ini")
        verify_btn.setObjectName("primaryButton")
        verify_btn.clicked.connect(self._verify_one)
        outer.addWidget(verify_btn)

        verify_all_btn = QPushButton("🔒 Verifikasi SEMUA Chain")
        verify_all_btn.setProperty("class", "danger")
        verify_all_btn.clicked.connect(self._verify_all)
        outer.addWidget(verify_all_btn)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFixedHeight(140)
        outer.addWidget(self.result_text)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load_status(self) -> None:
        run_task(api_client.get, on_success=self._on_status, on_error=self._on_error,
                  path=f"{BASE}/hash-chain/status")

    def _on_status(self, data: Any) -> None:
        data = data or {}
        self.status_summary.setText(
            f"Total chain: {data.get('total_chains', 0)}  |  "
            f"Valid: {data.get('valid_chains', 0)}  |  "
            f"Invalid: {data.get('invalid_chains', 0)}"
        )
        chains = data.get("chains", []) or []
        self.chain_table.setRowCount(len(chains))
        for r, c in enumerate(chains):
            is_valid = c.get("is_valid", True)
            values = [str(c.get("chain_type", "")), str(c.get("chain_id", "")), "VALID" if is_valid else "INVALID"]
            for col, v in enumerate(values):
                item = QTableWidgetItem(v)
                if col == 2:
                    item.setForeground(QColor("#059669" if is_valid else "#DC2626"))
                self.chain_table.setItem(r, col, item)
        self.chain_table.resizeColumnsToContents()

    def _verify_one(self) -> None:
        if not (self.chain_type_edit.text().strip() and self.chain_id_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Tipe & ID chain wajib diisi.")
            return
        payload = {"chain_type": self.chain_type_edit.text().strip(), "chain_id": self.chain_id_edit.text().strip()}
        run_task(api_client.post, on_success=self._on_verify_result, on_error=self._on_error,
                  path=f"{BASE}/hash-chain/verify", json_body=payload)

    def _on_verify_result(self, data: Any) -> None:
        data = data or {}
        lines = [
            f"Valid: {data.get('is_chain_valid')}",
            f"Total Entries: {data.get('total_entries')}",
            f"Valid Count: {data.get('valid_count')}",
            f"Invalid Count: {data.get('invalid_count')}",
            f"First Invalid Index: {data.get('first_invalid_index')}",
        ]
        self.result_text.setPlainText("\n".join(lines))
        self.status_label.setText("Verifikasi selesai.")

    def _verify_all(self) -> None:
        confirm = QMessageBox.question(self, "Konfirmasi", "Verifikasi SEMUA hash-chain? Proses ini bisa memakan waktu.")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.get, on_success=self._on_verify_all_result, on_error=self._on_error,
                  path=f"{BASE}/integrity/verify-all")

    def _on_verify_all_result(self, data: Any) -> None:
        data = data or {}
        self.result_text.setPlainText(
            f"Total: {data.get('total_chains')}  Valid: {data.get('valid_chains')}  "
            f"Invalid: {data.get('invalid_chains')}\nVerified at: {data.get('verified_at')}"
        )
        self._load_status()

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal: {message}")


# ==========================================================================
class GapDetectionTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Deteksi celah/kehilangan event dalam sequence (mengindikasikan potensi manipulasi data)."))
        form = QFormLayout()
        self.aggregate_type_edit = QLineEdit()
        self.aggregate_type_edit.setPlaceholderText("mis. journal, ar_invoice")
        form.addRow("Tipe Aggregate", self.aggregate_type_edit)
        self.start_time_edit = QDateTimeEdit(QDateTime.currentDateTime().addDays(-7))
        self.start_time_edit.setCalendarPopup(True)
        form.addRow("Dari", self.start_time_edit)
        self.end_time_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_time_edit.setCalendarPopup(True)
        form.addRow("Sampai", self.end_time_edit)
        outer.addLayout(form)

        detect_btn = QPushButton("🔍 Deteksi Gap")
        detect_btn.setObjectName("primaryButton")
        detect_btn.clicked.connect(self._detect)
        outer.addWidget(detect_btn)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Mulai Gap", "Selesai Gap", "Durasi (detik)", "Expected/Actual Count"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _detect(self) -> None:
        if not self.aggregate_type_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Tipe aggregate wajib diisi.")
            return
        payload = {
            "aggregate_type": self.aggregate_type_edit.text().strip(),
            "start_time": self.start_time_edit.dateTime().toString("yyyy-MM-ddTHH:mm:ss"),
            "end_time": self.end_time_edit.dateTime().toString("yyyy-MM-ddTHH:mm:ss"),
        }
        run_task(api_client.post, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/gap-detection", json_body=payload)

    def _on_result(self, payload: Any) -> None:
        rows = extract_list(payload) or (payload if isinstance(payload, list) else [])
        self.table.setRowCount(len(rows))
        for r, g in enumerate(rows):
            values = [
                str(g.get("gap_start", "")),
                str(g.get("gap_end", "")),
                str(g.get("gap_duration_seconds", "")),
                f"{g.get('expected_count', '')}/{g.get('actual_count', '')}",
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} gap ditemukan." if rows else "Tidak ada gap ditemukan (baik).")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal: {message}")


# ==========================================================================
class SoxTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Status Kontrol SOX</b>"))
        row = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)
        self.effective_only_check = QCheckBox("Hanya tampilkan yang efektif")
        self.effective_only_check.stateChanged.connect(lambda _s: self.refresh())
        row.addWidget(self.effective_only_check)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Kontrol", "Kategori", "Efektif", "Tanggal Test Terakhir"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Uji Kontrol SOX Baru</b>"))
        form = QFormLayout()
        self.control_id_edit = QLineEdit()
        form.addRow("ID Kontrol", self.control_id_edit)
        self.control_name_edit = QLineEdit()
        form.addRow("Nama Kontrol", self.control_name_edit)
        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("mis. revenue, disbursement, financial_reporting")
        form.addRow("Kategori", self.category_edit)
        self.period_start_edit = QDateEdit(QDate.currentDate().addMonths(-1))
        self.period_start_edit.setCalendarPopup(True)
        form.addRow("Periode Test Mulai", self.period_start_edit)
        self.period_end_edit = QDateEdit(QDate.currentDate())
        self.period_end_edit.setCalendarPopup(True)
        form.addRow("Periode Test Selesai", self.period_end_edit)
        self.sample_size_edit = QSpinBox()
        self.sample_size_edit.setRange(1, 100000)
        self.sample_size_edit.setValue(25)
        form.addRow("Sample Size", self.sample_size_edit)
        self.deviations_edit = QSpinBox()
        self.deviations_edit.setRange(0, 100000)
        form.addRow("Jumlah Deviasi", self.deviations_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        test_btn = QPushButton("🧪 Uji Kontrol")
        test_btn.setObjectName("primaryButton")
        test_btn.clicked.connect(self._test_control)
        outer.addWidget(test_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/sox/controls",
                  params={"effective_only": self.effective_only_check.isChecked()})

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload) or (payload if isinstance(payload, list) else [])
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            values = [
                c.get("control_name", ""),
                c.get("control_category", ""),
                "Ya" if c.get("is_effective") else "Tidak",
                str(c.get("tested_at", ""))[:10],
            ]
            for col, v in enumerate(values):
                item = QTableWidgetItem(v)
                if col == 2:
                    item.setForeground(QColor("#059669" if c.get("is_effective") else "#DC2626"))
                self.table.setItem(r, col, item)
        self.table.resizeColumnsToContents()

    def _test_control(self) -> None:
        if not all([self.control_id_edit.text().strip(), self.control_name_edit.text().strip(),
                    self.category_edit.text().strip()]):
            QMessageBox.warning(self, "Validasi", "ID, nama, dan kategori kontrol wajib diisi.")
            return
        payload = {
            "control_id": self.control_id_edit.text().strip(),
            "control_name": self.control_name_edit.text().strip(),
            "control_category": self.category_edit.text().strip(),
            "test_period_start": self.period_start_edit.date().toString("yyyy-MM-dd"),
            "test_period_end": self.period_end_edit.date().toString("yyyy-MM-dd"),
            "sample_size": self.sample_size_edit.value(),
            "deviations": self.deviations_edit.value(),
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_test_result, on_error=self._on_error,
                  path=f"{BASE}/sox/control-test", json_body=payload)

    def _on_test_result(self, data: Any) -> None:
        data = data or {}
        is_eff = data.get("is_effective")
        self.status_label.setText(
            f"Hasil: {'EFEKTIF' if is_eff else 'TIDAK EFEKTIF'} — deviation rate {data.get('deviation_rate', '-')}%. "
            f"{data.get('conclusion', '')}"
        )
        self.refresh()

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal: {message}")


# ==========================================================================
class AuditTrailTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Telusuri seluruh riwayat perubahan (create/update/delete) untuk 1 entitas spesifik."))
        row = QHBoxLayout()
        self.entity_type_edit = QLineEdit()
        self.entity_type_edit.setPlaceholderText("mis. journal, ar_invoice")
        row.addWidget(QLabel("Tipe:"))
        row.addWidget(self.entity_type_edit)
        self.entity_id_edit = QLineEdit()
        self.entity_id_edit.setPlaceholderText("UUID entitas")
        row.addWidget(QLabel("ID:"))
        row.addWidget(self.entity_id_edit)
        load_btn = QPushButton("⟳ Tampilkan Trail")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Waktu", "Aksi", "Pengguna", "Detail Perubahan"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        etype = self.entity_type_edit.text().strip()
        eid = self.entity_id_edit.text().strip()
        if not etype or not eid:
            QMessageBox.warning(self, "Validasi", "Tipe dan ID entitas wajib diisi.")
            return
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/trail/{etype}/{eid}")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            values = [
                str(rec.get("timestamp", rec.get("created_at", ""))),
                str(rec.get("action", "")),
                rec.get("user_name") or str(rec.get("user_id", "")),
                str(rec.get("changes", rec.get("diff", "")))[:200],
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} entri riwayat ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal: {message}")


# ==========================================================================
class ReportGenerationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Generate Laporan Audit Komprehensif</b>"))
        form = QFormLayout()
        self.start_date_edit = QDateEdit(QDate.currentDate().addMonths(-1))
        self.start_date_edit.setCalendarPopup(True)
        form.addRow("Dari Tanggal", self.start_date_edit)
        self.end_date_edit = QDateEdit(QDate.currentDate())
        self.end_date_edit.setCalendarPopup(True)
        form.addRow("Sampai Tanggal", self.end_date_edit)
        self.include_hash_check = QCheckBox("Sertakan verifikasi hash-chain")
        self.include_hash_check.setChecked(True)
        form.addRow("", self.include_hash_check)
        self.include_gap_check = QCheckBox("Sertakan deteksi gap")
        form.addRow("", self.include_gap_check)
        self.include_sampling_check = QCheckBox("Sertakan hasil sampling")
        form.addRow("", self.include_sampling_check)
        self.format_edit = QLineEdit("pdf")
        form.addRow("Format", self.format_edit)
        outer.addLayout(form)

        generate_btn = QPushButton("📄 Generate Laporan")
        generate_btn.setObjectName("primaryButton")
        generate_btn.clicked.connect(self._generate)
        outer.addWidget(generate_btn)

        download_row = QHBoxLayout()
        self.report_id_edit = QLineEdit()
        self.report_id_edit.setPlaceholderText("ID laporan untuk didownload")
        download_row.addWidget(self.report_id_edit)
        download_btn = QPushButton("⬇ Download")
        download_btn.clicked.connect(self._download)
        download_row.addWidget(download_btn)
        outer.addLayout(download_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _generate(self) -> None:
        payload = {
            "start_date": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date_edit.date().toString("yyyy-MM-dd"),
            "include_hash_chain_verification": self.include_hash_check.isChecked(),
            "include_gap_detection": self.include_gap_check.isChecked(),
            "include_sampling_results": self.include_sampling_check.isChecked(),
            "report_format": self.format_edit.text().strip() or "pdf",
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/report", json_body=payload)

    def _on_created(self, result: Any) -> None:
        rid = (result or {}).get("report_id", "") if isinstance(result, dict) else ""
        if rid:
            self.report_id_edit.setText(str(rid))
        self.status_label.setText(f"Laporan sedang diproses. ID: {rid}")

    def _download(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        rid = self.report_id_edit.text().strip()
        if not rid:
            QMessageBox.information(self, "Info", "Isi ID laporan dulu.")
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Simpan Laporan Audit", f"audit_report_{rid}.pdf")
        if not save_path:
            return
        run_task(api_client.download_file, on_success=lambda p: self.status_label.setText(f"Disimpan ke {p}"),
                  on_error=self._on_error, path=f"{BASE}/report/{rid}/download", save_path=save_path)

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")
