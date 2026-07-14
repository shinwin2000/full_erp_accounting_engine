"""
ui/pages/bank_reconciliation_page.py
======================================
Melengkapi gap kritis modul Bank & Kas: Rekonsiliasi Bank, Transfer Antar
Rekening, Petty Cash, dan Cash Book — semuanya sebelumnya tidak ada UI
sama sekali (frontend lama cuma kelola bank_accounts & transactions).

Endpoint backend (base: /bank-cash/bank-cash):
  POST /reconciliations                          - buat rekonsiliasi baru
  GET  /reconciliations/{bank_account_id}         - riwayat rekonsiliasi akun
  POST /reconciliations/{id}/close                - tutup/selesaikan rekonsiliasi
  POST /transfers                                 - transfer antar rekening
  POST /transfers/{id}/approve                    - approve transfer
  POST /transfers/{id}/process                    - proses/eksekusi transfer
  GET  /transfers/{id}                            - detail transfer
  GET/POST /cash-books                            - buku kas per mata uang
  GET  /cash-books/{id}/balance                   - saldo buku kas
  GET/POST /petty-cash                            - dana kas kecil
  POST /petty-cash/{id}/reimburse                 - reimbursement kas kecil
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
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

BASE = "/bank-cash/bank-cash"


class BankReconciliationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🏦  Rekonsiliasi Bank & Kas")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(ReconciliationTab(), "Rekonsiliasi Bank")
        self.tabs.addTab(TransferTab(), "Transfer Antar Rekening")
        self.tabs.addTab(PettyCashTab(), "Petty Cash")
        self.tabs.addTab(CashBookTab(), "Cash Book")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class ReconciliationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("ID Rekening Bank (UUID):"))
        self.account_id_edit = QLineEdit()
        self.account_id_edit.setPlaceholderText("tempel UUID rekening di sini")
        row.addWidget(self.account_id_edit)
        load_btn = QPushButton("⟳ Muat Riwayat")
        load_btn.clicked.connect(self._load_history)
        row.addWidget(load_btn)
        new_btn = QPushButton("+ Rekonsiliasi Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_reconciliation)
        row.addWidget(new_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Tanggal Statement", "Saldo Statement", "Saldo Buku", "Selisih", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        action_row = QHBoxLayout()
        close_btn = QPushButton("✔ Tutup Rekonsiliasi Terpilih")
        close_btn.clicked.connect(self._close_reconciliation)
        action_row.addWidget(close_btn)
        action_row.addStretch()
        outer.addLayout(action_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

        self._records: list[dict[str, Any]] = []

    def _load_history(self) -> None:
        account_id = self.account_id_edit.text().strip()
        if not account_id:
            QMessageBox.information(self, "Info", "Masukkan ID rekening bank dulu.")
            return
        self.status_label.setText("Memuat riwayat rekonsiliasi...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/reconciliations/{account_id}")

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            values = [
                format_date(rec.get("statement_date")),
                format_money(rec.get("statement_balance")),
                format_money(rec.get("book_balance")),
                format_money(rec.get("difference", 0)),
                str(rec.get("status", "")),
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} rekonsiliasi dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _new_reconciliation(self) -> None:
        account_id = self.account_id_edit.text().strip()
        if not account_id:
            QMessageBox.information(self, "Info", "Masukkan ID rekening bank dulu.")
            return
        dlg = ReconciliationFormDialog(account_id, parent=self)
        if dlg.exec():
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Rekonsiliasi dibuat."),
                on_error=self._on_write_error,
                path=f"{BASE}/reconciliations",
                json_body=dlg.build_payload(),
            )

    def _close_reconciliation(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            QMessageBox.information(self, "Info", "Pilih rekonsiliasi terlebih dahulu.")
            return
        rec_id = self._records[row].get("id")
        confirm = QMessageBox.question(self, "Konfirmasi", "Tutup rekonsiliasi ini? Aksi tidak bisa dibatalkan.")
        if confirm != QMessageBox.Yes:
            return
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write("Rekonsiliasi ditutup."),
            on_error=self._on_write_error,
            path=f"{BASE}/reconciliations/{rec_id}/close",
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self._load_history()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


class ReconciliationFormDialog(QDialog):
    def __init__(self, bank_account_id: str, parent=None):
        super().__init__(parent)
        self.bank_account_id = bank_account_id
        self.setWindowTitle("Rekonsiliasi Bank Baru")
        self.resize(400, 220)
        outer = QVBoxLayout(self)
        form = QFormLayout()

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Statement", self.date_edit)

        self.balance_edit = QLineEdit()
        self.balance_edit.setPlaceholderText("Saldo menurut rekening koran")
        form.addRow("Saldo Statement", self.balance_edit)

        self.threshold_edit = QLineEdit("1")
        form.addRow("Toleransi Auto-Match", self.threshold_edit)

        outer.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_save(self) -> None:
        try:
            Decimal(self.balance_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Saldo statement harus angka.")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        return {
            "bank_account_id": self.bank_account_id,
            "statement_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "statement_balance": float(Decimal(self.balance_edit.text().strip())),
            "auto_match_threshold": float(Decimal(self.threshold_edit.text().strip() or "1")),
        }


# ==========================================================================
class TransferTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Transfer dana antar rekening bank/kas perusahaan."))

        form = QFormLayout()
        self.from_edit = QLineEdit()
        self.from_edit.setPlaceholderText("UUID rekening asal")
        form.addRow("Dari Rekening", self.from_edit)

        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText("UUID rekening tujuan")
        form.addRow("Ke Rekening", self.to_edit)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Transfer", self.date_edit)

        self.amount_edit = QLineEdit()
        form.addRow("Jumlah", self.amount_edit)

        self.desc_edit = QLineEdit()
        form.addRow("Keterangan", self.desc_edit)
        outer.addLayout(form)

        btn_row = QHBoxLayout()
        submit_btn = QPushButton("+ Buat Transfer")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._create_transfer)
        btn_row.addWidget(submit_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        outer.addWidget(QLabel("Aksi lanjutan pada transfer yang sudah dibuat:"))
        action_row = QHBoxLayout()
        self.transfer_id_edit = QLineEdit()
        self.transfer_id_edit.setPlaceholderText("UUID transfer")
        action_row.addWidget(self.transfer_id_edit)
        approve_btn = QPushButton("✔ Approve")
        approve_btn.clicked.connect(self._approve_transfer)
        action_row.addWidget(approve_btn)
        process_btn = QPushButton("⚙ Proses/Eksekusi")
        process_btn.clicked.connect(self._process_transfer)
        action_row.addWidget(process_btn)
        outer.addLayout(action_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _create_transfer(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus angka > 0.")
            return
        if not (self.from_edit.text().strip() and self.to_edit.text().strip() and self.desc_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Rekening asal, tujuan, dan keterangan wajib diisi.")
            return
        payload = {
            "from_bank_account_id": self.from_edit.text().strip(),
            "to_bank_account_id": self.to_edit.text().strip(),
            "transfer_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "amount": float(amount),
            "description": self.desc_edit.text().strip(),
        }
        run_task(api_client.post, on_success=self._on_success, on_error=self._on_error,
                  path=f"{BASE}/transfers", json_body=payload)

    def _approve_transfer(self) -> None:
        tid = self.transfer_id_edit.text().strip()
        if not tid:
            QMessageBox.information(self, "Info", "Masukkan ID transfer.")
            return
        run_task(api_client.post, on_success=self._on_success, on_error=self._on_error,
                  path=f"{BASE}/transfers/{tid}/approve")

    def _process_transfer(self) -> None:
        tid = self.transfer_id_edit.text().strip()
        if not tid:
            QMessageBox.information(self, "Info", "Masukkan ID transfer.")
            return
        run_task(api_client.post, on_success=self._on_success, on_error=self._on_error,
                  path=f"{BASE}/transfers/{tid}/process")

    def _on_success(self, _result: Any) -> None:
        self.status_label.setText("Berhasil.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class PettyCashTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        new_btn = QPushButton("+ Dana Petty Cash Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._create_fund)
        toolbar.addWidget(new_btn)
        reimburse_btn = QPushButton("💵 Reimbursement")
        reimburse_btn.clicked.connect(self._reimburse)
        toolbar.addWidget(reimburse_btn)
        outer.addLayout(toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nama Dana", "Mata Uang", "Saldo Awal", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

        self._records: list[dict[str, Any]] = []

    def refresh(self) -> None:
        self.status_label.setText("Memuat petty cash...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/petty-cash")

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            values = [
                rec.get("fund_name", ""),
                rec.get("currency_code", "IDR"),
                format_money(rec.get("initial_amount")),
                str(rec.get("status", "")),
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} dana petty cash dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _create_fund(self) -> None:
        dlg = PettyCashFormDialog(parent=self)
        if dlg.exec():
            run_task(api_client.post, on_success=lambda _r: self._after_write("Dana petty cash dibuat."),
                      on_error=self._on_write_error, path=f"{BASE}/petty-cash", json_body=dlg.build_payload())

    def _reimburse(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            QMessageBox.information(self, "Info", "Pilih dana petty cash terlebih dahulu.")
            return
        fund_id = self._records[row].get("id")
        dlg = ReimbursementFormDialog(parent=self)
        if dlg.exec():
            run_task(api_client.post, on_success=lambda _r: self._after_write("Reimbursement berhasil."),
                      on_error=self._on_write_error, path=f"{BASE}/petty-cash/{fund_id}/reimburse",
                      json_body=dlg.build_payload())

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


class PettyCashFormDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dana Petty Cash Baru")
        self.resize(400, 260)
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow("Nama Dana", self.name_edit)
        self.currency_edit = QLineEdit("IDR")
        form.addRow("Mata Uang", self.currency_edit)
        self.amount_edit = QLineEdit()
        form.addRow("Saldo Awal", self.amount_edit)
        self.custodian_edit = QLineEdit()
        self.custodian_edit.setPlaceholderText("UUID penanggung jawab (opsional)")
        form.addRow("Custodian", self.custodian_edit)
        self.threshold_edit = QLineEdit()
        self.threshold_edit.setPlaceholderText("Batas reimbursement (opsional)")
        form.addRow("Threshold Reimburse", self.threshold_edit)
        outer.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_save(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Nama dana wajib diisi.")
            return
        try:
            Decimal(self.amount_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Saldo awal harus angka.")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        payload = {
            "fund_name": self.name_edit.text().strip(),
            "currency_code": self.currency_edit.text().strip() or "IDR",
            "initial_amount": float(Decimal(self.amount_edit.text().strip())),
        }
        if self.custodian_edit.text().strip():
            payload["custodian_id"] = self.custodian_edit.text().strip()
        if self.threshold_edit.text().strip():
            payload["reimbursement_threshold"] = float(Decimal(self.threshold_edit.text().strip()))
        return payload


class ReimbursementFormDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reimbursement Petty Cash")
        self.resize(380, 220)
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal", self.date_edit)
        self.amount_edit = QLineEdit()
        form.addRow("Jumlah", self.amount_edit)
        self.bank_account_edit = QLineEdit()
        self.bank_account_edit.setPlaceholderText("UUID rekening sumber dana (opsional)")
        form.addRow("Rekening Sumber", self.bank_account_edit)
        self.desc_edit = QLineEdit()
        form.addRow("Keterangan", self.desc_edit)
        outer.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_save(self) -> None:
        try:
            Decimal(self.amount_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus angka.")
            return
        if not self.desc_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Keterangan wajib diisi.")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        payload = {
            "reimbursement_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "amount": float(Decimal(self.amount_edit.text().strip())),
            "description": self.desc_edit.text().strip(),
        }
        if self.bank_account_edit.text().strip():
            payload["bank_account_id"] = self.bank_account_edit.text().strip()
        return payload


# ==========================================================================
class CashBookTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        new_btn = QPushButton("+ Cash Book Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._create_book)
        toolbar.addWidget(new_btn)
        outer.addLayout(toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nama", "Mata Uang", "Saldo Awal", "Saldo Minimum"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        self.status_label.setText("Memuat cash book...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/cash-books")

    def _on_loaded(self, payload: Any) -> None:
        records = extract_list(payload)
        self.table.setRowCount(len(records))
        for row, rec in enumerate(records):
            values = [
                rec.get("name", ""),
                rec.get("currency_code", "IDR"),
                format_money(rec.get("opening_balance")),
                format_money(rec.get("min_balance", 0)),
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(records)} cash book dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _create_book(self) -> None:
        dlg = CashBookFormDialog(parent=self)
        if dlg.exec():
            run_task(api_client.post, on_success=lambda _r: self._after_write("Cash book dibuat."),
                      on_error=lambda m: QMessageBox.warning(self, "Gagal", m),
                      path=f"{BASE}/cash-books", json_body=dlg.build_payload())

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()


class CashBookFormDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cash Book Baru")
        self.resize(380, 260)
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow("Nama", self.name_edit)
        self.currency_edit = QLineEdit("IDR")
        form.addRow("Mata Uang", self.currency_edit)
        self.opening_edit = QLineEdit("0")
        form.addRow("Saldo Awal", self.opening_edit)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Saldo Awal", self.date_edit)
        self.min_balance_edit = QLineEdit()
        self.min_balance_edit.setPlaceholderText("opsional")
        form.addRow("Saldo Minimum", self.min_balance_edit)
        outer.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_save(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Nama wajib diisi.")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        payload = {
            "name": self.name_edit.text().strip(),
            "currency_code": self.currency_edit.text().strip() or "IDR",
            "opening_balance": float(Decimal(self.opening_edit.text().strip() or "0")),
            "opening_balance_date": self.date_edit.date().toString("yyyy-MM-dd"),
        }
        if self.min_balance_edit.text().strip():
            payload["min_balance"] = float(Decimal(self.min_balance_edit.text().strip()))
        return payload
