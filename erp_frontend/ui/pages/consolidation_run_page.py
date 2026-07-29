"""
ui/pages/consolidation_run_page.py
=====================================
Melengkapi gap KRITIS di modul Consolidation: sebelumnya cuma bisa kelola
Grup & Intercompany, padahal fitur INTI-nya (menjalankan konsolidasi,
eliminasi, hitung NCI, lihat laporan konsolidasi) tidak ada UI sama sekali.

Endpoint backend (base: /consolidation/consolidation):
  POST /run                                          - jalankan proses konsolidasi
  POST /eliminate                                     - buat entry eliminasi
  POST /elimination/{id}/post                         - posting eliminasi
  POST /nci/calculate                                 - hitung Non-Controlling Interest
  GET  /report/{consolidation_id}                     - laporan konsolidasi lengkap
  GET  /report/balance-sheet/{consolidation_id}       - neraca konsolidasi
  GET  /report/income-statement/{consolidation_id}    - laba rugi konsolidasi
  POST /consolidation/{id}/reverse                    - reverse hasil konsolidasi
"""
from __future__ import annotations

from typing import Any

from core.api_client import api_client
from core.formatting import format_money
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

BASE = "/consolidation/consolidation"


class ConsolidationRunPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🧩  Jalankan Konsolidasi, Eliminasi & NCI")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(RunConsolidationTab(), "Jalankan Konsolidasi")
        self.tabs.addTab(EliminationTab(), "Eliminasi")
        self.tabs.addTab(NciTab(), "Hitung NCI")
        self.tabs.addTab(ConsolidationReportTab(), "Laporan Konsolidasi")
        outer.addWidget(self.tabs, stretch=1)


def _period_fields(form: QFormLayout) -> tuple[QSpinBox, QSpinBox]:
    fiscal_year = QSpinBox()
    fiscal_year.setRange(2000, 2100)
    fiscal_year.setValue(QDate.currentDate().year())
    form.addRow("Tahun Fiskal", fiscal_year)
    period = QSpinBox()
    period.setRange(1, 12)
    period.setValue(QDate.currentDate().month())
    form.addRow("Periode (Bulan)", period)
    return fiscal_year, period


# ==========================================================================
class RunConsolidationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Menjalankan proses konsolidasi laporan keuangan seluruh anggota grup: agregasi, "
            "eliminasi otomatis, dan perhitungan NCI."
        ))
        form = QFormLayout()
        self.group_id_edit = QLineEdit()
        self.group_id_edit.setPlaceholderText("UUID grup konsolidasi")
        form.addRow("Grup Konsolidasi", self.group_id_edit)
        self.fiscal_year, self.period = _period_fields(form)
        self.as_of_date_edit = QDateEdit(QDate.currentDate())
        self.as_of_date_edit.setCalendarPopup(True)
        form.addRow("Per Tanggal", self.as_of_date_edit)
        self.include_nci_check = QCheckBox("Sertakan perhitungan NCI")
        self.include_nci_check.setChecked(True)
        form.addRow("", self.include_nci_check)
        self.post_elim_check = QCheckBox("Posting eliminasi otomatis")
        self.post_elim_check.setChecked(False)
        form.addRow("", self.post_elim_check)
        outer.addLayout(form)

        run_btn = QPushButton("▶ Jalankan Konsolidasi")
        run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(self._run)
        outer.addWidget(run_btn)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        outer.addWidget(self.result_text, stretch=1)

        reverse_row = QHBoxLayout()
        self.reverse_id_edit = QLineEdit()
        self.reverse_id_edit.setPlaceholderText("ID hasil konsolidasi untuk di-reverse")
        reverse_row.addWidget(self.reverse_id_edit)
        reverse_btn = QPushButton("✘ Reverse Hasil Konsolidasi")
        reverse_btn.setProperty("class", "danger")
        reverse_btn.clicked.connect(self._reverse)
        reverse_row.addWidget(reverse_btn)
        outer.addLayout(reverse_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _run(self) -> None:
        if not self.group_id_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Grup konsolidasi wajib diisi.")
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi",
            "Jalankan proses konsolidasi? Untuk grup & periode besar proses ini bisa memakan waktu."
        )
        if confirm != QMessageBox.Yes:
            return
        payload = {
            "consolidation_group_id": self.group_id_edit.text().strip(),
            "fiscal_year": self.fiscal_year.value(),
            "period": self.period.value(),
            "include_nci": self.include_nci_check.isChecked(),
            "as_of_date": self.as_of_date_edit.date().toString("yyyy-MM-dd"),
            "post_eliminations": self.post_elim_check.isChecked(),
        }
        self.status_label.setText("Menjalankan konsolidasi...")
        run_task(api_client.post, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/run", json_body=payload)

    def _on_result(self, data: Any) -> None:
        data = data or {}
        cid = data.get("consolidation_id", "")
        if cid:
            self.reverse_id_edit.setText(str(cid))
        lines = [
            f"ID Konsolidasi: {cid}",
            f"No. Konsolidasi: {data.get('consolidation_number', '-')}",
            f"Status: {data.get('status', '-')}",
            f"Total Aset: {format_money(data.get('total_assets'))}",
            f"Total Kewajiban: {format_money(data.get('total_liabilities'))}",
            f"Total Ekuitas: {format_money(data.get('total_equity'))}",
            f"Laba Bersih: {format_money(data.get('net_income'))}",
            f"NCI: {format_money(data.get('nci_amount'))}",
            f"Ekuitas Attributable to Parent: {format_money(data.get('equity_attributable_to_parent'))}",
            f"Jumlah Entry Eliminasi: {data.get('elimination_entries_count', 0)}",
            f"Jumlah Transaksi Intercompany: {data.get('intercompany_transactions_count', 0)}",
        ]
        self.result_text.setPlainText("\n".join(lines))
        self.status_label.setText("Konsolidasi selesai.")

    def _reverse(self) -> None:
        cid = self.reverse_id_edit.text().strip()
        if not cid:
            QMessageBox.information(self, "Info", "Isi ID konsolidasi dulu.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Reverse hasil konsolidasi ini?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Konsolidasi di-reverse."),
                  on_error=self._on_error, path=f"{BASE}/consolidation/{cid}/reverse")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class EliminationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Buat Entry Eliminasi</b>"))
        form = QFormLayout()
        self.group_id_edit = QLineEdit()
        self.group_id_edit.setPlaceholderText("UUID grup konsolidasi")
        form.addRow("Grup Konsolidasi", self.group_id_edit)
        self.fiscal_year, self.period = _period_fields(form)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        create_btn = QPushButton("+ Buat Eliminasi")
        create_btn.setObjectName("primaryButton")
        create_btn.clicked.connect(self._create)
        outer.addWidget(create_btn)

        post_row = QHBoxLayout()
        self.elim_id_edit = QLineEdit()
        self.elim_id_edit.setPlaceholderText("ID eliminasi untuk diposting")
        post_row.addWidget(self.elim_id_edit)
        post_btn = QPushButton("📮 Posting Eliminasi")
        post_btn.setProperty("class", "success")
        post_btn.clicked.connect(self._post)
        post_row.addWidget(post_btn)
        outer.addLayout(post_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _create(self) -> None:
        if not self.group_id_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Grup konsolidasi wajib diisi.")
            return
        payload = {
            "consolidation_group_id": self.group_id_edit.text().strip(),
            "fiscal_year": self.fiscal_year.value(),
            "period": self.period.value(),
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/eliminate", json_body=payload)

    def _on_created(self, result: Any) -> None:
        eid = (result or {}).get("id", "") if isinstance(result, dict) else ""
        if eid:
            self.elim_id_edit.setText(str(eid))
        self.status_label.setText(f"Entry eliminasi dibuat. ID: {eid}")

    def _post(self) -> None:
        eid = self.elim_id_edit.text().strip()
        if not eid:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Eliminasi diposting."),
                  on_error=self._on_error, path=f"{BASE}/elimination/{eid}/post")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class NciTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Hitung Non-Controlling Interest (Kepentingan Non-Pengendali)</b>"))
        form = QFormLayout()
        self.group_id_edit = QLineEdit()
        self.group_id_edit.setPlaceholderText("UUID grup konsolidasi")
        form.addRow("Grup Konsolidasi", self.group_id_edit)
        self.fiscal_year, self.period = _period_fields(form)
        self.net_income_edit = QLineEdit()
        self.net_income_edit.setPlaceholderText("opsional, kosongkan untuk hitung otomatis")
        form.addRow("Laba Bersih (opsional)", self.net_income_edit)
        outer.addLayout(form)

        calc_btn = QPushButton("🧮 Hitung NCI")
        calc_btn.setObjectName("primaryButton")
        calc_btn.clicked.connect(self._calculate)
        outer.addWidget(calc_btn)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Entitas", "% Kepemilikan", "NCI Laba Bersih", "NCI OCI", "NCI Dividen", "Saldo NCI Akhir"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _calculate(self) -> None:
        if not self.group_id_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Grup konsolidasi wajib diisi.")
            return
        payload = {
            "consolidation_group_id": self.group_id_edit.text().strip(),
            "fiscal_year": self.fiscal_year.value(),
            "period": self.period.value(),
        }
        if self.net_income_edit.text().strip():
            try:
                from decimal import Decimal
                payload["net_income"] = float(Decimal(self.net_income_edit.text().strip()))
            except Exception:
                QMessageBox.warning(self, "Validasi", "Laba bersih harus angka.")
                return
        run_task(api_client.post, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/nci/calculate", json_body=payload)

    def _on_result(self, result: Any) -> None:
        from core.formatting import extract_list
        rows = extract_list(result) if isinstance(result, (list, dict)) else []
        if not rows and isinstance(result, dict):
            rows = [result]
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            values = [
                rec.get("legal_entity_name", ""),
                f"{rec.get('ownership_percentage', 0)}%",
                format_money(rec.get("nci_share_net_income")),
                format_money(rec.get("nci_share_oci")),
                format_money(rec.get("nci_share_dividends")),
                format_money(rec.get("ending_nci_balance")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} entitas dihitung.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class ConsolidationReportTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        self.consolidation_id_edit = QLineEdit()
        self.consolidation_id_edit.setPlaceholderText("UUID hasil konsolidasi")
        row.addWidget(self.consolidation_id_edit)
        load_btn = QPushButton("⟳ Tampilkan Laporan Lengkap")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load_full)
        row.addWidget(load_btn)
        bs_btn = QPushButton("Neraca")
        bs_btn.clicked.connect(self._load_bs)
        row.addWidget(bs_btn)
        is_btn = QPushButton("Laba Rugi")
        is_btn.clicked.connect(self._load_is)
        row.addWidget(is_btn)
        outer.addLayout(row)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        outer.addWidget(self.result_text, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _cid(self) -> str:
        cid = self.consolidation_id_edit.text().strip()
        if not cid:
            QMessageBox.information(self, "Info", "Masukkan ID konsolidasi dulu.")
        return cid

    def _load_full(self) -> None:
        cid = self._cid()
        if not cid:
            return
        run_task(api_client.get, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/report/{cid}")

    def _load_bs(self) -> None:
        cid = self._cid()
        if not cid:
            return
        run_task(api_client.get, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/report/balance-sheet/{cid}")

    def _load_is(self) -> None:
        cid = self._cid()
        if not cid:
            return
        run_task(api_client.get, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/report/income-statement/{cid}")

    def _on_result(self, data: Any) -> None:
        import json
        try:
            self.result_text.setPlainText(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        except Exception:
            self.result_text.setPlainText(str(data))
        self.status_label.setText("Laporan dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
