"""
ui/pages/tax_spt_page.py
===========================
Melengkapi gap KRITIS di modul Pajak: sebelumnya hanya Faktur Pajak yang
ada UI-nya. Modul ini menambahkan SPT Masa PPN, SPT Masa PPh 21/23, SPT
Tahunan Badan, e-Bupot, e-Meterai, dan permintaan NSFP.

Endpoint backend (base: /tax/coretax/tax):
  POST /spt/ppn, /spt/pph21, /spt/pph23, /spt/tahunan-badan
  POST /e-bupot, POST /e-bupot/{id}/cancel
  POST /e-meterai/validate, /e-meterai/purchase
  POST /nsfp/request, GET /nsfp/quota
  GET  /dashboard, /filing-status, /due-dates
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from ui.widgets.kpi_card import KpiCard

BASE = "/tax/coretax/tax"


class TaxSptPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🧾  SPT, e-Bupot, e-Meterai & Kepatuhan Pajak")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(DashboardTab(), "Dashboard Pajak")
        self.tabs.addTab(SptPpnTab(), "SPT Masa PPN")
        self.tabs.addTab(SptPph21Tab(), "SPT Masa PPh 21")
        self.tabs.addTab(SptPph23Tab(), "SPT Masa PPh 23")
        self.tabs.addTab(SptTahunanTab(), "SPT Tahunan Badan")
        self.tabs.addTab(EBupotTab(), "e-Bupot")
        self.tabs.addTab(EMeteraiTab(), "e-Meterai")
        self.tabs.addTab(NsfpTab(), "Permintaan NSFP")
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
        self.card_pending = KpiCard("Filing Pending", icon="⏳", color="#D97706")
        self.card_overdue = KpiCard("Jatuh Tempo Terlewat", icon="⚠️", color="#DC2626")
        self.card_paid = KpiCard("Total Sudah Dibayar (Bulan Ini)", icon="✅", color="#059669")
        cards.addWidget(self.card_pending)
        cards.addWidget(self.card_overdue)
        cards.addWidget(self.card_paid)
        outer.addLayout(cards)

        outer.addWidget(QLabel("<b>Jatuh Tempo Terdekat</b>"))
        self.due_table = QTableWidget(0, 3)
        self.due_table.setHorizontalHeaderLabels(["Jenis Pajak", "Periode", "Tanggal Jatuh Tempo"])
        self.due_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.due_table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_dashboard, on_error=self._on_error, path=f"{BASE}/dashboard")
        run_task(api_client.get, on_success=self._on_due_dates, on_error=self._on_error, path=f"{BASE}/due-dates")

    def _on_dashboard(self, data: Any) -> None:
        data = data or {}
        self.card_pending.set_value(str(data.get("pending_filings", "-")))
        self.card_overdue.set_value(str(data.get("overdue_count", "-")))
        self.card_paid.set_value(format_money(data.get("paid_this_month", 0)))
        self.status_label.setText("Dashboard dimuat.")

    def _on_due_dates(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.due_table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            values = [rec.get("tax_type", ""), rec.get("period", ""), format_date(rec.get("due_date"))]
            for c, v in enumerate(values):
                self.due_table.setItem(r, c, QTableWidgetItem(v))
        self.due_table.resizeColumnsToContents()

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Sebagian data gagal dimuat: {message}")


def _period_form(form: QFormLayout) -> tuple[QSpinBox, QSpinBox]:
    bulan = QSpinBox()
    bulan.setRange(1, 12)
    bulan.setValue(QDate.currentDate().month())
    form.addRow("Masa Pajak (Bulan)", bulan)
    tahun = QSpinBox()
    tahun.setRange(2000, 2100)
    tahun.setValue(QDate.currentDate().year())
    form.addRow("Tahun Pajak", tahun)
    return bulan, tahun


# ==========================================================================
class SptPpnTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Lapor SPT Masa PPN</b>"))
        form = QFormLayout()
        self.bulan, self.tahun = _period_form(form)
        self.penyerahan_edit = QLineEdit("0")
        form.addRow("Total Penyerahan (DPP)", self.penyerahan_edit)
        self.ppn_keluaran_edit = QLineEdit("0")
        form.addRow("PPN Keluaran", self.ppn_keluaran_edit)
        self.ppn_masukan_edit = QLineEdit("0")
        form.addRow("PPN Masukan", self.ppn_masukan_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Lapor SPT Masa PPN")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)
        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            penyerahan = Decimal(self.penyerahan_edit.text().strip() or "0")
            keluaran = Decimal(self.ppn_keluaran_edit.text().strip() or "0")
            masukan = Decimal(self.ppn_masukan_edit.text().strip() or "0")
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Semua nilai harus angka.")
            return
        selisih = keluaran - masukan
        payload = {
            "masa_pajak": self.bulan.value(),
            "tahun_pajak": self.tahun.value(),
            "total_penyerahan": float(penyerahan),
            "total_ppn_keluaran": float(keluaran),
            "total_ppn_masukan": float(masukan),
            "ppn_kurang_bayar": float(selisih) if selisih > 0 else 0,
            "ppn_lebih_bayar": float(-selisih) if selisih < 0 else 0,
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/spt/ppn", json_body=payload)

    def _on_ok(self, result: Any) -> None:
        self.status_label.setText("SPT Masa PPN berhasil dilaporkan.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class SptPph21Tab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Lapor SPT Masa PPh 21</b>"))
        form = QFormLayout()
        self.bulan, self.tahun = _period_form(form)
        self.bruto_edit = QLineEdit()
        form.addRow("Total Bruto", self.bruto_edit)
        self.bayar_edit = QLineEdit()
        form.addRow("Jumlah Dibayar", self.bayar_edit)
        self.ntpn_edit = QLineEdit()
        self.ntpn_edit.setPlaceholderText("opsional, isi setelah bayar")
        form.addRow("NTPN", self.ntpn_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Lapor SPT Masa PPh 21")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)
        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            bruto = Decimal(self.bruto_edit.text().strip())
            bayar = Decimal(self.bayar_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Total bruto & jumlah bayar wajib diisi angka.")
            return
        payload = {
            "masa_pajak": self.bulan.value(),
            "tahun_pajak": self.tahun.value(),
            "total_bruto": float(bruto),
            "jumlah_bayar": float(bayar),
            "ntpn": self.ntpn_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/spt/pph21", json_body=payload)

    def _on_ok(self, _r: Any) -> None:
        self.status_label.setText("SPT Masa PPh 21 berhasil dilaporkan.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class SptPph23Tab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Lapor SPT Masa PPh 23</b>"))
        form = QFormLayout()
        self.bulan, self.tahun = _period_form(form)
        self.jenis_combo = QComboBox()
        self.jenis_combo.setEditable(True)
        self.jenis_combo.addItems(["jasa", "sewa", "royalti", "dividen", "bunga"])
        form.addRow("Jenis Pajak", self.jenis_combo)
        self.dpp_edit = QLineEdit()
        form.addRow("Total DPP", self.dpp_edit)
        self.bayar_edit = QLineEdit()
        form.addRow("Total Bayar", self.bayar_edit)
        self.kompensasi_edit = QLineEdit("0")
        form.addRow("Kompensasi", self.kompensasi_edit)
        self.ntpn_edit = QLineEdit()
        form.addRow("NTPN", self.ntpn_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Lapor SPT Masa PPh 23")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)
        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            dpp = Decimal(self.dpp_edit.text().strip())
            bayar = Decimal(self.bayar_edit.text().strip())
            kompensasi = Decimal(self.kompensasi_edit.text().strip() or "0")
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "DPP dan jumlah bayar wajib diisi angka.")
            return
        payload = {
            "masa_pajak": self.bulan.value(),
            "tahun_pajak": self.tahun.value(),
            "jenis_pajak": self.jenis_combo.currentText(),
            "total_dpp": float(dpp),
            "total_bayar": float(bayar),
            "kompensasi": float(kompensasi),
            "ntpn": self.ntpn_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/spt/pph23", json_body=payload)

    def _on_ok(self, _r: Any) -> None:
        self.status_label.setText("SPT Masa PPh 23 berhasil dilaporkan.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class SptTahunanTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Lapor SPT Tahunan Badan</b>"))
        form = QFormLayout()
        self.tahun_edit = QSpinBox()
        self.tahun_edit.setRange(2000, 2100)
        self.tahun_edit.setValue(QDate.currentDate().year() - 1)
        form.addRow("Tahun Pajak", self.tahun_edit)
        self.neto_komersial_edit = QLineEdit()
        form.addRow("Penghasilan Neto Komersial", self.neto_komersial_edit)
        self.neto_fiskal_edit = QLineEdit()
        form.addRow("Penghasilan Neto Fiskal", self.neto_fiskal_edit)
        self.kompensasi_rugi_edit = QLineEdit("0")
        form.addRow("Kompensasi Kerugian", self.kompensasi_rugi_edit)
        self.pkp_edit = QLineEdit()
        form.addRow("Penghasilan Kena Pajak", self.pkp_edit)
        self.pph_terutang_edit = QLineEdit()
        form.addRow("PPh Terutang", self.pph_terutang_edit)
        self.kredit_pajak_edit = QLineEdit("0")
        form.addRow("Total Kredit Pajak", self.kredit_pajak_edit)
        self.ntpn_edit = QLineEdit()
        form.addRow("NTPN", self.ntpn_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Lapor SPT Tahunan Badan")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)
        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            neto_komersial = Decimal(self.neto_komersial_edit.text().strip())
            neto_fiskal = Decimal(self.neto_fiskal_edit.text().strip())
            kompensasi = Decimal(self.kompensasi_rugi_edit.text().strip() or "0")
            pkp = Decimal(self.pkp_edit.text().strip())
            pph_terutang = Decimal(self.pph_terutang_edit.text().strip())
            kredit_pajak = Decimal(self.kredit_pajak_edit.text().strip() or "0")
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Semua field angka wajib diisi dengan benar.")
            return
        selisih = pph_terutang - kredit_pajak
        payload = {
            "tahun_pajak": self.tahun_edit.value(),
            "penghasilan_neto_komersial": float(neto_komersial),
            "penghasilan_neto_fiskal": float(neto_fiskal),
            "kompensasi_kerugian": float(kompensasi),
            "penghasilan_kena_pajak": float(pkp),
            "pph_terutang": float(pph_terutang),
            "total_kredit_pajak": float(kredit_pajak),
            "kurang_bayar": float(selisih) if selisih > 0 else 0,
            "lebih_bayar": float(-selisih) if selisih < 0 else 0,
            "ntpn": self.ntpn_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/spt/tahunan-badan", json_body=payload)

    def _on_ok(self, _r: Any) -> None:
        self.status_label.setText("SPT Tahunan Badan berhasil dilaporkan.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class EBupotTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Terbitkan Bukti Potong Elektronik (e-Bupot)</b>"))
        form = QFormLayout()
        self.bulan, self.tahun = _period_form(form)
        self.npwp_pemotong_edit = QLineEdit()
        form.addRow("NPWP Pemotong", self.npwp_pemotong_edit)
        self.npwp_penerima_edit = QLineEdit()
        form.addRow("NPWP Penerima", self.npwp_penerima_edit)
        self.nama_penerima_edit = QLineEdit()
        form.addRow("Nama Penerima", self.nama_penerima_edit)
        self.alamat_penerima_edit = QLineEdit()
        form.addRow("Alamat Penerima", self.alamat_penerima_edit)
        self.jenis_pajak_edit = QLineEdit()
        self.jenis_pajak_edit.setPlaceholderText("mis. PPh 23")
        form.addRow("Jenis Pajak", self.jenis_pajak_edit)
        self.jenis_penghasilan_edit = QLineEdit()
        form.addRow("Kode Jenis Penghasilan", self.jenis_penghasilan_edit)
        self.dpp_edit = QLineEdit()
        form.addRow("DPP", self.dpp_edit)
        self.tarif_edit = QLineEdit()
        form.addRow("Tarif (%)", self.tarif_edit)
        self.tgl_potong_edit = QDateEdit(QDate.currentDate())
        self.tgl_potong_edit.setCalendarPopup(True)
        form.addRow("Tanggal Pemotongan", self.tgl_potong_edit)
        self.invoice_ref_edit = QLineEdit()
        form.addRow("Referensi Invoice", self.invoice_ref_edit)
        self.keterangan_edit = QLineEdit()
        form.addRow("Keterangan", self.keterangan_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Terbitkan e-Bupot")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        cancel_row = QHBoxLayout()
        self.cancel_id_edit = QLineEdit()
        self.cancel_id_edit.setPlaceholderText("ID e-Bupot untuk dibatalkan")
        cancel_row.addWidget(self.cancel_id_edit)
        cancel_btn = QPushButton("✘ Batalkan e-Bupot")
        cancel_btn.setProperty("class", "danger")
        cancel_btn.clicked.connect(self._cancel)
        cancel_row.addWidget(cancel_btn)
        outer.addLayout(cancel_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            dpp = Decimal(self.dpp_edit.text().strip())
            tarif = Decimal(self.tarif_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "DPP & tarif wajib diisi angka.")
            return
        required = [self.npwp_pemotong_edit, self.npwp_penerima_edit, self.nama_penerima_edit]
        if not all(f.text().strip() for f in required):
            QMessageBox.warning(self, "Validasi", "NPWP pemotong/penerima & nama penerima wajib diisi.")
            return
        payload = {
            "masa_pajak": self.bulan.value(),
            "tahun_pajak": self.tahun.value(),
            "npwp_pemotong": self.npwp_pemotong_edit.text().strip(),
            "npwp_penerima": self.npwp_penerima_edit.text().strip(),
            "nama_penerima": self.nama_penerima_edit.text().strip(),
            "alamat_penerima": self.alamat_penerima_edit.text().strip() or None,
            "jenis_pajak": self.jenis_pajak_edit.text().strip() or None,
            "jenis_penghasilan_code": self.jenis_penghasilan_edit.text().strip() or None,
            "dpp": float(dpp),
            "tarif": float(tarif),
            "tanggal_pemotongan": self.tgl_potong_edit.date().toString("yyyy-MM-dd"),
            "invoice_reference": self.invoice_ref_edit.text().strip() or None,
            "keterangan": self.keterangan_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/e-bupot", json_body=payload)

    def _on_created(self, result: Any) -> None:
        bid = (result or {}).get("id", "") if isinstance(result, dict) else ""
        if bid:
            self.cancel_id_edit.setText(str(bid))
        self.status_label.setText(f"e-Bupot berhasil diterbitkan. ID: {bid}")

    def _cancel(self) -> None:
        bid = self.cancel_id_edit.text().strip()
        if not bid:
            QMessageBox.information(self, "Info", "Isi ID e-Bupot dulu.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Batalkan e-Bupot ini?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("e-Bupot dibatalkan."),
                  on_error=self._on_error, path=f"{BASE}/e-bupot/{bid}/cancel")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class EMeteraiTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Validasi Kode e-Meterai</b>"))
        validate_form = QFormLayout()
        self.meterai_code_edit = QLineEdit()
        validate_form.addRow("Kode e-Meterai", self.meterai_code_edit)
        self.document_id_edit = QLineEdit()
        self.document_id_edit.setPlaceholderText("opsional")
        validate_form.addRow("ID Dokumen", self.document_id_edit)
        outer.addLayout(validate_form)
        validate_btn = QPushButton("Validasi")
        validate_btn.clicked.connect(self._validate)
        outer.addWidget(validate_btn)

        outer.addWidget(QLabel("<b>Beli e-Meterai</b>"))
        purchase_form = QFormLayout()
        self.qty_edit = QSpinBox()
        self.qty_edit.setRange(1, 10000)
        self.qty_edit.setValue(1)
        purchase_form.addRow("Jumlah", self.qty_edit)
        self.npwp_edit = QLineEdit()
        purchase_form.addRow("NPWP Pembeli", self.npwp_edit)
        self.purpose_edit = QLineEdit()
        purchase_form.addRow("Tujuan Penggunaan", self.purpose_edit)
        outer.addLayout(purchase_form)
        purchase_btn = QPushButton("+ Beli e-Meterai")
        purchase_btn.setObjectName("primaryButton")
        purchase_btn.clicked.connect(self._purchase)
        outer.addWidget(purchase_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _validate(self) -> None:
        if not self.meterai_code_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Kode e-Meterai wajib diisi.")
            return
        payload = {
            "meterai_code": self.meterai_code_edit.text().strip(),
            "document_id": self.document_id_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_validate_result, on_error=self._on_error,
                  path=f"{BASE}/e-meterai/validate", json_body=payload)

    def _on_validate_result(self, result: Any) -> None:
        is_valid = (result or {}).get("is_valid") if isinstance(result, dict) else None
        self.status_label.setText("Kode VALID." if is_valid else "Hasil validasi diterima.")

    def _purchase(self) -> None:
        if not self.npwp_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "NPWP pembeli wajib diisi.")
            return
        payload = {
            "quantity": self.qty_edit.value(),
            "npwp": self.npwp_edit.text().strip(),
            "purpose": self.purpose_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("e-Meterai berhasil dibeli."),
                  on_error=self._on_error, path=f"{BASE}/e-meterai/purchase", json_body=payload)

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class NsfpTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_quota()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Kuota NSFP (Nomor Seri Faktur Pajak)</b>"))
        self.quota_label = QLabel("Memuat kuota...")
        outer.addWidget(self.quota_label)
        refresh_btn = QPushButton("⟳ Refresh Kuota")
        refresh_btn.clicked.connect(self._load_quota)
        outer.addWidget(refresh_btn)

        outer.addWidget(QLabel("<b>Minta NSFP Baru</b>"))
        form = QFormLayout()
        self.tahun_edit = QSpinBox()
        self.tahun_edit.setRange(2000, 2100)
        self.tahun_edit.setValue(QDate.currentDate().year())
        form.addRow("Tahun", self.tahun_edit)
        self.bulan_edit = QSpinBox()
        self.bulan_edit.setRange(1, 12)
        self.bulan_edit.setValue(QDate.currentDate().month())
        form.addRow("Bulan", self.bulan_edit)
        self.jumlah_edit = QSpinBox()
        self.jumlah_edit.setRange(1, 100000)
        self.jumlah_edit.setValue(10)
        form.addRow("Jumlah NSFP Diminta", self.jumlah_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Minta NSFP")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._request)
        outer.addWidget(submit_btn)

        outer.addWidget(QLabel("<b>NSFP Diterima:</b>"))
        self.nsfp_result = QTextEdit()
        self.nsfp_result.setReadOnly(True)
        self.nsfp_result.setFixedHeight(120)
        outer.addWidget(self.nsfp_result)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load_quota(self) -> None:
        run_task(api_client.get, on_success=self._on_quota, on_error=self._on_error, path=f"{BASE}/nsfp/quota")

    def _on_quota(self, data: Any) -> None:
        data = data or {}
        remaining = data.get("remaining_quota", data.get("remaining", "-"))
        self.quota_label.setText(f"Sisa kuota NSFP: <b>{remaining}</b>")

    def _request(self) -> None:
        payload = {
            "tahun": self.tahun_edit.value(),
            "bulan": self.bulan_edit.value(),
            "jumlah": self.jumlah_edit.value(),
        }
        run_task(api_client.post, on_success=self._on_requested, on_error=self._on_error,
                  path=f"{BASE}/nsfp/request", json_body=payload)

    def _on_requested(self, result: Any) -> None:
        data = result or {}
        nsfp_list = data.get("nsfp_list", [])
        self.nsfp_result.setPlainText("\n".join(nsfp_list) if nsfp_list else str(data))
        self.status_label.setText(f"{len(nsfp_list)} NSFP diterima.")
        self._load_quota()

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")
