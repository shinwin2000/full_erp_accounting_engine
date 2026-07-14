"""
ui/pages/capital_page.py
===========================
Modal & Dividen — versi lengkap. Versi sebelumnya HANYA mengimplementasikan
kontribusi modal padahal judul halamannya menjanjikan "Modal & Dividen".
Sekarang mencakup semua sub-modul Capital:

Endpoint backend (base: /capital):
  POST /contributions, /contributions/approve|post|cancel
  POST /withdrawals, /withdrawals/approve|post|cancel
  POST /dividends, /dividends/approve|pay|cancel
  POST /retained-earnings/adjust|transfer|update
  GET  /stats

Catatan: modul ini action-oriented (tidak ada GET list di backend), jadi
UI-nya berbentuk form + ID tracking manual (ID hasil create dipakai untuk
approve/post/cancel berikutnya) — bukan tabel CRUD biasa.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import format_money
from core.session import session
from core.workers import run_task
from ui.widgets.kpi_card import KpiCard

BASE = "/capital"


class CapitalPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh_stats()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("🏦  Modal & Dividen")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("⟳ Refresh Statistik")
        refresh_btn.clicked.connect(self.refresh_stats)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        cards_row = QHBoxLayout()
        self.card_total = KpiCard("Total Setoran Modal", icon="💵", color="#059669")
        self.card_count = KpiCard("Jumlah Transaksi", icon="🔢", color="#2563EB")
        cards_row.addWidget(self.card_total)
        cards_row.addWidget(self.card_count)
        outer.addLayout(cards_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(ContributionTab(), "Kontribusi Modal")
        self.tabs.addTab(WithdrawalTab(), "Withdrawal Modal")
        self.tabs.addTab(DividendTab(), "Dividen")
        self.tabs.addTab(RetainedEarningsTab(), "Retained Earnings")
        outer.addWidget(self.tabs, stretch=1)

    def refresh_stats(self) -> None:
        run_task(api_client.get, on_success=self._on_stats, on_error=self._on_error, path=f"{BASE}/stats")

    def _on_stats(self, data: Any) -> None:
        data = data or {}
        total = data.get("total_contributions") or data.get("total_amount")
        count = data.get("count") or data.get("total_count")
        self.card_total.set_value(format_money(total) if total is not None else "-")
        self.card_count.set_value(str(count) if count is not None else "-")

    def _on_error(self, message: str) -> None:
        pass  # stats gagal dimuat tidak fatal, biarkan kartu tetap "-"


def _current_legal_entity_field(form: QFormLayout) -> QLineEdit:
    """Field legal_entity_id pra-isi dari session aktif, tapi tetap bisa diubah."""
    edit = QLineEdit(str(session.legal_entity_id or ""))
    edit.setPlaceholderText("UUID legal entity")
    form.addRow("Legal Entity", edit)
    return edit


# ==========================================================================
class ContributionTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Catat Setoran Modal Baru</b>"))
        form = QFormLayout()
        self.entity_edit = _current_legal_entity_field(form)
        self.amount_edit = QLineEdit()
        form.addRow("Jumlah Setoran", self.amount_edit)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal", self.date_edit)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["cash", "asset", "receivable_conversion"])
        form.addRow("Tipe Kontribusi", self.type_combo)
        self.contributor_edit = QLineEdit()
        self.contributor_edit.setPlaceholderText("UUID kontributor (opsional)")
        form.addRow("Kontributor", self.contributor_edit)
        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(60)
        form.addRow("Deskripsi", self.desc_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Catat Setoran Modal")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addWidget(QLabel("<b>Aksi Lanjutan (approve / post / cancel)</b>"))
        action_form = QFormLayout()
        self.contribution_id_edit = QLineEdit()
        self.contribution_id_edit.setPlaceholderText("ID hasil pencatatan di atas")
        action_form.addRow("ID Kontribusi", self.contribution_id_edit)
        self.cancel_reason_edit = QLineEdit()
        self.cancel_reason_edit.setPlaceholderText("wajib diisi untuk aksi Cancel")
        action_form.addRow("Alasan (untuk Cancel)", self.cancel_reason_edit)
        outer.addLayout(action_form)

        action_row = QHBoxLayout()
        approve_btn = QPushButton("✔ Approve")
        approve_btn.setProperty("class", "success")
        approve_btn.clicked.connect(self._approve)
        action_row.addWidget(approve_btn)
        post_btn = QPushButton("📮 Post ke Ledger")
        post_btn.setObjectName("primaryButton")
        post_btn.clicked.connect(self._post)
        action_row.addWidget(post_btn)
        cancel_btn = QPushButton("✘ Cancel")
        cancel_btn.setProperty("class", "danger")
        cancel_btn.clicked.connect(self._cancel)
        action_row.addWidget(cancel_btn)
        outer.addLayout(action_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip().replace(",", ""))
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah setoran harus > 0.")
            return
        if not self.entity_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Legal Entity wajib diisi.")
            return
        payload = {
            "legal_entity_id": self.entity_edit.text().strip(),
            "amount": float(amount),
            "contribution_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "description": self.desc_edit.toPlainText().strip() or None,
            "contributor_id": self.contributor_edit.text().strip() or None,
            "contribution_type": self.type_combo.currentText(),
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/contributions", json_body=payload)

    def _on_created(self, result: Any) -> None:
        cid = (result or {}).get("contribution_id", "")
        if cid:
            self.contribution_id_edit.setText(str(cid))
        self.status_label.setText(f"Berhasil dicatat. ID: {cid}")

    def _approve(self) -> None:
        cid = self.contribution_id_edit.text().strip()
        if not cid:
            QMessageBox.information(self, "Info", "Isi ID kontribusi dulu.")
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/contributions/approve", json_body={"contribution_id": cid})

    def _post(self) -> None:
        cid = self.contribution_id_edit.text().strip()
        if not cid:
            QMessageBox.information(self, "Info", "Isi ID kontribusi dulu.")
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/contributions/post", json_body={"contribution_id": cid})

    def _cancel(self) -> None:
        cid = self.contribution_id_edit.text().strip()
        reason = self.cancel_reason_edit.text().strip()
        if not cid or not reason:
            QMessageBox.information(self, "Info", "ID kontribusi & alasan wajib diisi untuk cancel.")
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/contributions/cancel", json_body={"contribution_id": cid, "reason": reason})

    def _on_action_ok(self, _r: Any) -> None:
        self.status_label.setText("Aksi berhasil.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class WithdrawalTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Catat Withdrawal Modal Baru</b>"))
        form = QFormLayout()
        self.entity_edit = _current_legal_entity_field(form)
        self.amount_edit = QLineEdit()
        form.addRow("Jumlah Withdrawal", self.amount_edit)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal", self.date_edit)
        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(60)
        form.addRow("Deskripsi", self.desc_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Catat Withdrawal")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addWidget(QLabel("<b>Aksi Lanjutan</b>"))
        action_form = QFormLayout()
        self.withdrawal_id_edit = QLineEdit()
        self.withdrawal_id_edit.setPlaceholderText("ID hasil pencatatan di atas")
        action_form.addRow("ID Withdrawal", self.withdrawal_id_edit)
        self.cancel_reason_edit = QLineEdit()
        self.cancel_reason_edit.setPlaceholderText("wajib diisi untuk aksi Cancel")
        action_form.addRow("Alasan (untuk Cancel)", self.cancel_reason_edit)
        outer.addLayout(action_form)

        action_row = QHBoxLayout()
        approve_btn = QPushButton("✔ Approve")
        approve_btn.setProperty("class", "success")
        approve_btn.clicked.connect(self._approve)
        action_row.addWidget(approve_btn)
        post_btn = QPushButton("📮 Post ke Ledger")
        post_btn.setObjectName("primaryButton")
        post_btn.clicked.connect(self._post)
        action_row.addWidget(post_btn)
        cancel_btn = QPushButton("✘ Cancel")
        cancel_btn.setProperty("class", "danger")
        cancel_btn.clicked.connect(self._cancel)
        action_row.addWidget(cancel_btn)
        outer.addLayout(action_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip().replace(",", ""))
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus > 0.")
            return
        payload = {
            "legal_entity_id": self.entity_edit.text().strip(),
            "amount": float(amount),
            "withdrawal_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "description": self.desc_edit.toPlainText().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/withdrawals", json_body=payload)

    def _on_created(self, result: Any) -> None:
        wid = (result or {}).get("withdrawal_id", "")
        if wid:
            self.withdrawal_id_edit.setText(str(wid))
        self.status_label.setText(f"Berhasil dicatat. ID: {wid}")

    def _approve(self) -> None:
        wid = self.withdrawal_id_edit.text().strip()
        if not wid:
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/withdrawals/approve", json_body={"withdrawal_id": wid})

    def _post(self) -> None:
        wid = self.withdrawal_id_edit.text().strip()
        if not wid:
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/withdrawals/post", json_body={"withdrawal_id": wid})

    def _cancel(self) -> None:
        wid = self.withdrawal_id_edit.text().strip()
        reason = self.cancel_reason_edit.text().strip()
        if not wid or not reason:
            QMessageBox.information(self, "Info", "ID & alasan wajib diisi.")
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/withdrawals/cancel", json_body={"withdrawal_id": wid, "reason": reason})

    def _on_action_ok(self, _r: Any) -> None:
        self.status_label.setText("Aksi berhasil.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class DividendTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Deklarasi Dividen Baru</b>"))
        form = QFormLayout()
        self.entity_edit = _current_legal_entity_field(form)
        self.amount_edit = QLineEdit()
        form.addRow("Total Dividen", self.amount_edit)
        self.decl_date_edit = QDateEdit(QDate.currentDate())
        self.decl_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Deklarasi", self.decl_date_edit)
        self.pay_date_edit = QDateEdit(QDate.currentDate().addDays(30))
        self.pay_date_edit.setCalendarPopup(True)
        form.addRow("Rencana Tanggal Bayar", self.pay_date_edit)
        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(60)
        form.addRow("Deskripsi", self.desc_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Deklarasikan Dividen")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addWidget(QLabel("<b>Aksi Lanjutan</b>"))
        action_form = QFormLayout()
        self.dividend_id_edit = QLineEdit()
        self.dividend_id_edit.setPlaceholderText("ID hasil deklarasi di atas")
        action_form.addRow("ID Dividen", self.dividend_id_edit)
        self.pay_amount_edit = QLineEdit()
        self.pay_amount_edit.setPlaceholderText("jumlah dibayar (untuk aksi Pay)")
        action_form.addRow("Jumlah Bayar", self.pay_amount_edit)
        self.is_full_check = QCheckBox("Pelunasan penuh (is_full)")
        self.is_full_check.setChecked(True)
        action_form.addRow("", self.is_full_check)
        self.cancel_reason_edit = QLineEdit()
        self.cancel_reason_edit.setPlaceholderText("wajib diisi untuk aksi Cancel")
        action_form.addRow("Alasan (untuk Cancel)", self.cancel_reason_edit)
        outer.addLayout(action_form)

        action_row = QHBoxLayout()
        approve_btn = QPushButton("✔ Approve")
        approve_btn.setProperty("class", "success")
        approve_btn.clicked.connect(self._approve)
        action_row.addWidget(approve_btn)
        pay_btn = QPushButton("💵 Bayar Dividen")
        pay_btn.setObjectName("primaryButton")
        pay_btn.clicked.connect(self._pay)
        action_row.addWidget(pay_btn)
        cancel_btn = QPushButton("✘ Cancel")
        cancel_btn.setProperty("class", "danger")
        cancel_btn.clicked.connect(self._cancel)
        action_row.addWidget(cancel_btn)
        outer.addLayout(action_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip().replace(",", ""))
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus > 0.")
            return
        payload = {
            "legal_entity_id": self.entity_edit.text().strip(),
            "total_amount": float(amount),
            "declaration_date": self.decl_date_edit.date().toString("yyyy-MM-dd"),
            "payment_date": self.pay_date_edit.date().toString("yyyy-MM-dd"),
            "description": self.desc_edit.toPlainText().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/dividends", json_body=payload)

    def _on_created(self, result: Any) -> None:
        did = (result or {}).get("dividend_id", "")
        if did:
            self.dividend_id_edit.setText(str(did))
        self.status_label.setText(f"Dividen dideklarasikan. ID: {did}")

    def _approve(self) -> None:
        did = self.dividend_id_edit.text().strip()
        if not did:
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/dividends/approve", json_body={"dividend_id": did})

    def _pay(self) -> None:
        did = self.dividend_id_edit.text().strip()
        try:
            amount = Decimal(self.pay_amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah bayar harus > 0.")
            return
        if not did:
            QMessageBox.information(self, "Info", "Isi ID dividen dulu.")
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/dividends/pay",
                  json_body={"dividend_id": did, "amount": float(amount), "is_full": self.is_full_check.isChecked()})

    def _cancel(self) -> None:
        did = self.dividend_id_edit.text().strip()
        reason = self.cancel_reason_edit.text().strip()
        if not did or not reason:
            QMessageBox.information(self, "Info", "ID & alasan wajib diisi.")
            return
        run_task(api_client.post, on_success=self._on_action_ok, on_error=self._on_error,
                  path=f"{BASE}/dividends/cancel", json_body={"dividend_id": did, "reason": reason})

    def _on_action_ok(self, _r: Any) -> None:
        self.status_label.setText("Aksi berhasil.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class RetainedEarningsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Penyesuaian Saldo Laba Ditahan</b>"))
        adjust_form = QFormLayout()
        self.adj_entity_edit = _current_legal_entity_field(adjust_form)
        self.adj_amount_edit = QLineEdit()
        adjust_form.addRow("Jumlah Penyesuaian (+/-)", self.adj_amount_edit)
        self.adj_date_edit = QDateEdit(QDate.currentDate())
        self.adj_date_edit.setCalendarPopup(True)
        adjust_form.addRow("Tanggal", self.adj_date_edit)
        self.adj_desc_edit = QLineEdit()
        adjust_form.addRow("Deskripsi", self.adj_desc_edit)
        outer.addLayout(adjust_form)
        adj_btn = QPushButton("Simpan Penyesuaian")
        adj_btn.clicked.connect(self._adjust)
        outer.addWidget(adj_btn)

        outer.addWidget(QLabel("<b>Transfer Laba Ditahan Antar Entitas</b>"))
        transfer_form = QFormLayout()
        self.from_entity_edit = QLineEdit()
        self.from_entity_edit.setPlaceholderText("UUID entitas asal")
        transfer_form.addRow("Dari Entitas", self.from_entity_edit)
        self.to_entity_edit = QLineEdit()
        self.to_entity_edit.setPlaceholderText("UUID entitas tujuan")
        transfer_form.addRow("Ke Entitas", self.to_entity_edit)
        self.transfer_amount_edit = QLineEdit()
        transfer_form.addRow("Jumlah", self.transfer_amount_edit)
        self.transfer_date_edit = QDateEdit(QDate.currentDate())
        self.transfer_date_edit.setCalendarPopup(True)
        transfer_form.addRow("Tanggal", self.transfer_date_edit)
        outer.addLayout(transfer_form)
        transfer_btn = QPushButton("Transfer")
        transfer_btn.clicked.connect(self._transfer)
        outer.addWidget(transfer_btn)

        outer.addWidget(QLabel("<b>Update Saldo Laba Ditahan (set ulang saldo)</b>"))
        update_form = QFormLayout()
        self.upd_entity_edit = _current_legal_entity_field(update_form)
        self.new_balance_edit = QLineEdit()
        update_form.addRow("Saldo Baru", self.new_balance_edit)
        self.as_of_date_edit = QDateEdit(QDate.currentDate())
        self.as_of_date_edit.setCalendarPopup(True)
        update_form.addRow("Per Tanggal", self.as_of_date_edit)
        outer.addLayout(update_form)
        upd_btn = QPushButton("Update Saldo")
        upd_btn.setProperty("class", "danger")
        upd_btn.clicked.connect(self._update_balance)
        outer.addWidget(upd_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _adjust(self) -> None:
        try:
            amount = Decimal(self.adj_amount_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus angka.")
            return
        if not self.adj_desc_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Deskripsi wajib diisi.")
            return
        payload = {
            "legal_entity_id": self.adj_entity_edit.text().strip(),
            "amount": float(amount),
            "adjustment_date": self.adj_date_edit.date().toString("yyyy-MM-dd"),
            "description": self.adj_desc_edit.text().strip(),
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/retained-earnings/adjust", json_body=payload)

    def _transfer(self) -> None:
        try:
            amount = Decimal(self.transfer_amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus > 0.")
            return
        payload = {
            "from_legal_entity_id": self.from_entity_edit.text().strip(),
            "to_legal_entity_id": self.to_entity_edit.text().strip(),
            "amount": float(amount),
            "transfer_date": self.transfer_date_edit.date().toString("yyyy-MM-dd"),
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/retained-earnings/transfer", json_body=payload)

    def _update_balance(self) -> None:
        try:
            balance = Decimal(self.new_balance_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Saldo baru harus angka.")
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi",
            "Update saldo laba ditahan secara langsung? Aksi ini berisiko tinggi dan sebaiknya "
            "hanya dipakai untuk koreksi data awal (migrasi)."
        )
        if confirm != QMessageBox.Yes:
            return
        payload = {
            "legal_entity_id": self.upd_entity_edit.text().strip(),
            "new_balance": float(balance),
            "as_of_date": self.as_of_date_edit.date().toString("yyyy-MM-dd"),
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/retained-earnings/update", json_body=payload)

    def _on_ok(self, _r: Any) -> None:
        self.status_label.setText("Berhasil disimpan.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")
