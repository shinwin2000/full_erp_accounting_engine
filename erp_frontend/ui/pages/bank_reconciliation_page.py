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
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

BASE = "/bank-cash/bank-cash"


class LookupCombo(QComboBox):
    """ComboBox yang mengisi dirinya sendiri secara async dari endpoint API
    (pola sama seperti FieldType.LOOKUP di form_dialog.py), dipakai untuk
    field UUID (rekening bank, custodian/karyawan, akun COA) di halaman
    ini supaya user MEMILIH dari daftar bernama, bukan mengetik UUID
    manual - sebelumnya semua field ini QLineEdit polos yang gampang
    salah ketik dan tidak ada cara melihat pilihan yang valid."""

    def __init__(
        self,
        path: str,
        value_field: str,
        label_fields: tuple,
        params: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._path = path
        self._value_field = value_field
        self._label_fields = label_fields
        self._params = params or {"page": 1, "page_size": 500, "limit": 500}
        self.setEditable(False)
        self.addItem("Memuat...", None)
        self.setEnabled(False)
        run_task(
            api_client.get, on_success=self._on_loaded, on_error=self._on_error,
            path=self._path, params=self._params,
        )

    def _on_loaded(self, payload: Any) -> None:
        try:
            self.clear()
            rows = extract_list(payload)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                val = row.get(self._value_field)
                parts = [str(row.get(f, "")) for f in self._label_fields if row.get(f) not in (None, "")]
                text = " - ".join(parts) if parts else str(val)
                self.addItem(text, val)
            if self.count() == 0:
                self.addItem("(tidak ada data)", None)
            self.setEnabled(True)
        except RuntimeError:
            pass

    def _on_error(self, _message: str) -> None:
        try:
            self.clear()
            self.addItem("(gagal memuat data)", None)
        except RuntimeError:
            pass

    def selected_id(self) -> str | None:
        val = self.currentData()
        return str(val) if val else None


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
        self.tabs.addTab(ImportStatementTab(), "Import Rekening Koran")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class ReconciliationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Rekening Bank:"))
        # PENTING (fix): sebelumnya QLineEdit UUID manual - sekarang
        # dropdown otomatis dari daftar rekening bank yang sudah ada.
        self.account_combo = LookupCombo(
            f"{BASE}/bank-accounts", "id", ("account_number", "account_name", "bank_name")
        )
        row.addWidget(self.account_combo, stretch=1)
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
        account_id = self.account_combo.selected_id()
        if not account_id:
            QMessageBox.information(self, "Info", "Pilih rekening bank dulu.")
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
        account_id = self.account_combo.selected_id()
        if not account_id:
            QMessageBox.information(self, "Info", "Pilih rekening bank dulu.")
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
        self.resize(560, 480)
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

        # ------------------------------------------------------------
        # PENTING (fix): backend (BankReconciliationCreateSchema) mewajibkan
        # field `statement_transactions` (daftar mutasi dari rekening koran
        # untuk dicocokkan dengan pembukuan) - sebelumnya field ini TIDAK
        # ADA SAMA SEKALI di form ini, jadi setiap submit selalu gagal 422
        # "statement_transactions: Field required". Tambahkan minimal satu
        # baris transaksi statement di bawah supaya rekonsiliasi bisa
        # dibuat. Kalau Anda sudah punya file mutasi bank, pertimbangkan
        # pakai tab "Import Rekening Koran" saja daripada isi manual di
        # sini satu-satu.
        # ------------------------------------------------------------
        outer.addWidget(QLabel("Transaksi menurut Rekening Koran (wajib minimal 1 baris):"))
        self.tx_table = QTableWidget(0, 4)
        self.tx_table.setHorizontalHeaderLabels(["Tanggal", "Jumlah", "Keterangan", "No. Referensi"])
        self.tx_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.tx_table, stretch=1)

        tx_btn_row = QHBoxLayout()
        add_row_btn = QPushButton("+ Tambah Baris")
        add_row_btn.clicked.connect(self._add_tx_row)
        tx_btn_row.addWidget(add_row_btn)
        remove_row_btn = QPushButton("- Hapus Baris Terpilih")
        remove_row_btn.clicked.connect(self._remove_tx_row)
        tx_btn_row.addWidget(remove_row_btn)
        tx_btn_row.addStretch()
        outer.addLayout(tx_btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._add_tx_row()  # mulai dengan 1 baris kosong biar jelas formatnya

    def _add_tx_row(self) -> None:
        row = self.tx_table.rowCount()
        self.tx_table.insertRow(row)
        date_edit = QDateEdit(QDate.currentDate())
        date_edit.setCalendarPopup(True)
        self.tx_table.setCellWidget(row, 0, date_edit)
        self.tx_table.setItem(row, 1, QTableWidgetItem(""))
        self.tx_table.setItem(row, 2, QTableWidgetItem(""))
        self.tx_table.setItem(row, 3, QTableWidgetItem(""))

    def _remove_tx_row(self) -> None:
        row = self.tx_table.currentRow()
        if row >= 0:
            self.tx_table.removeRow(row)

    def _on_save(self) -> None:
        try:
            Decimal(self.balance_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Saldo statement harus angka.")
            return
        if self.tx_table.rowCount() == 0:
            QMessageBox.warning(self, "Validasi", "Tambahkan minimal 1 baris transaksi statement.")
            return
        for row in range(self.tx_table.rowCount()):
            amount_item = self.tx_table.item(row, 1)
            try:
                Decimal((amount_item.text() if amount_item else "").strip())
            except InvalidOperation:
                QMessageBox.warning(self, "Validasi", f"Jumlah pada baris {row + 1} harus angka.")
                return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        statement_transactions = []
        for row in range(self.tx_table.rowCount()):
            date_widget = self.tx_table.cellWidget(row, 0)
            amount_item = self.tx_table.item(row, 1)
            desc_item = self.tx_table.item(row, 2)
            ref_item = self.tx_table.item(row, 3)
            statement_transactions.append({
                "date": date_widget.date().toString("yyyy-MM-dd") if date_widget else "",
                "amount": float(Decimal((amount_item.text() if amount_item else "0").strip() or "0")),
                "description": (desc_item.text() if desc_item else "").strip(),
                "reference_number": (ref_item.text() if ref_item else "").strip(),
            })
        return {
            "bank_account_id": self.bank_account_id,
            "statement_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "statement_balance": float(Decimal(self.balance_edit.text().strip())),
            "statement_transactions": statement_transactions,
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
        # PENTING (fix): sebelumnya field ini QLineEdit UUID manual, tidak
        # ada cara melihat rekening mana yang valid. Sekarang dropdown
        # otomatis dari daftar rekening bank.
        self.from_combo = LookupCombo(
            f"{BASE}/bank-accounts", "id", ("account_number", "account_name", "bank_name")
        )
        form.addRow("Dari Rekening", self.from_combo)

        self.to_combo = LookupCombo(
            f"{BASE}/bank-accounts", "id", ("account_number", "account_name", "bank_name")
        )
        form.addRow("Ke Rekening", self.to_combo)

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
        reject_btn = QPushButton("✘ Tolak")
        reject_btn.clicked.connect(self._reject_transfer)
        action_row.addWidget(reject_btn)
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
        from_id = self.from_combo.selected_id()
        to_id = self.to_combo.selected_id()
        if not (from_id and to_id and self.desc_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Rekening asal, tujuan, dan keterangan wajib diisi.")
            return
        if from_id == to_id:
            QMessageBox.warning(self, "Validasi", "Rekening asal dan tujuan tidak boleh sama.")
            return
        payload = {
            "from_bank_account_id": from_id,
            "to_bank_account_id": to_id,
            "transfer_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "amount": float(amount),
            "description": self.desc_edit.text().strip(),
        }
        run_task(api_client.post, on_success=self._on_success, on_error=self._on_error,
                  path=f"{BASE}/transfers", json_body=payload)

    def _approve_transfer(self) -> None:
        self._respond_transfer(approved=True)

    def _reject_transfer(self) -> None:
        self._respond_transfer(approved=False)

    def _respond_transfer(self, approved: bool) -> None:
        tid = self.transfer_id_edit.text().strip()
        if not tid:
            QMessageBox.information(self, "Info", "Masukkan ID transfer.")
            return
        # PENTING (fix): endpoint /transfers/{id}/approve mewajibkan JSON
        # body {"approved": bool} (BankTransferApproveSchema) - sebelumnya
        # dikirim tanpa body sama sekali, selalu gagal 422.
        run_task(api_client.post, on_success=self._on_success, on_error=self._on_error,
                  path=f"{BASE}/transfers/{tid}/approve", json_body={"approved": approved})

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
        self.resize(420, 320)
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow("Nama Dana", self.name_edit)
        self.currency_edit = QLineEdit("IDR")
        form.addRow("Mata Uang", self.currency_edit)
        self.amount_edit = QLineEdit()
        form.addRow("Saldo Awal", self.amount_edit)
        # PENTING (fix): backend (PettyCashCreateSchema) mewajibkan
        # custodian_id (UUID karyawan penanggung jawab) - sebelumnya field
        # ini ditandai "opsional" di form padahal WAJIB di backend, jadi
        # kalau dikosongkan selalu gagal 422. Sekarang wajib pilih dari
        # daftar karyawan.
        self.custodian_combo = LookupCombo(
            "/employees/employees", "id", ("employee_code", "full_name")
        )
        form.addRow("Custodian *", self.custodian_combo)
        # PENTING (fix): gl_petty_cash_account_id juga wajib di backend,
        # tapi sebelumnya TIDAK ADA SAMA SEKALI di form ini - salah satu
        # penyebab 422 "gl_petty_cash_account_id: Field required".
        self.gl_account_combo = LookupCombo(
            "/coa/chart-of-accounts/accounts", "id", ("account_code", "account_name"),
            params={"page_size": 5000, "include_inactive": False},
        )
        form.addRow("Akun GL Kas Kecil *", self.gl_account_combo)
        self.threshold_edit = QLineEdit()
        self.threshold_edit.setPlaceholderText("Default: 1.000.000 kalau dikosongkan")
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
            amount = Decimal(self.amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Saldo awal harus angka > 0.")
            return
        if not self.custodian_combo.selected_id():
            QMessageBox.warning(self, "Validasi", "Custodian wajib dipilih.")
            return
        if not self.gl_account_combo.selected_id():
            QMessageBox.warning(self, "Validasi", "Akun GL Kas Kecil wajib dipilih.")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        payload = {
            "fund_name": self.name_edit.text().strip(),
            "currency_code": self.currency_edit.text().strip() or "IDR",
            "initial_amount": float(Decimal(self.amount_edit.text().strip())),
            "custodian_id": self.custodian_combo.selected_id(),
            "gl_petty_cash_account_id": self.gl_account_combo.selected_id(),
        }
        if self.threshold_edit.text().strip():
            payload["reimbursement_threshold"] = float(Decimal(self.threshold_edit.text().strip()))
        return payload


class ReimbursementFormDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reimbursement Petty Cash")
        self.resize(420, 240)
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal", self.date_edit)
        self.amount_edit = QLineEdit()
        form.addRow("Jumlah", self.amount_edit)
        # PENTING (fix): backend (PettyCashReimbursementSchema) mewajibkan
        # bank_account_id - sebelumnya field ini ditandai "opsional" di
        # form padahal WAJIB (rekening sumber dana pengisian ulang kas
        # kecil), jadi kalau dikosongkan selalu gagal 422.
        self.bank_account_combo = LookupCombo(
            f"{BASE}/bank-accounts", "id", ("account_number", "account_name", "bank_name")
        )
        form.addRow("Rekening Sumber *", self.bank_account_combo)
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
            amount = Decimal(self.amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus angka > 0.")
            return
        if not self.desc_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Keterangan wajib diisi.")
            return
        if not self.bank_account_combo.selected_id():
            QMessageBox.warning(self, "Validasi", "Rekening sumber wajib dipilih.")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        return {
            "reimbursement_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "amount": float(Decimal(self.amount_edit.text().strip())),
            "description": self.desc_edit.text().strip(),
            "bank_account_id": self.bank_account_combo.selected_id(),
        }


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
        self.table.setHorizontalHeaderLabels(["Mata Uang", "Saldo Awal", "Saldo Sekarang", "Status"])
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
                rec.get("currency_code", "IDR"),
                format_money(rec.get("opening_balance")),
                format_money(rec.get("current_balance", rec.get("opening_balance"))),
                "Ditutup" if rec.get("is_closed") else "Aktif",
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
        self.resize(420, 300)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Catatan: satu Cash Book mewakili satu mata uang, bukan diberi\n"
            "nama bebas - backend tidak punya kolom nama/saldo minimum."
        ))
        form = QFormLayout()
        # PENTING (fix): field "Nama" dan "Saldo Minimum" DIHAPUS dari
        # form ini - backend (CashBookCreateSchema) memang sengaja tidak
        # punya kolom untuk keduanya sama sekali (lihat catatan di schema
        # backend), jadi sebelumnya apapun yang diketik user di dua field
        # itu diam-diam DIBUANG tanpa pemberitahuan apapun (request tetap
        # sukses 201, tapi data itu hilang) - membingungkan karena
        # terlihat berhasil padahal sebagian input tidak tersimpan.
        self.currency_edit = QLineEdit("IDR")
        form.addRow("Mata Uang", self.currency_edit)
        self.opening_edit = QLineEdit("0")
        form.addRow("Saldo Awal", self.opening_edit)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Saldo Awal", self.date_edit)
        # Field opsional yang MEMANG didukung backend (sebelumnya tidak
        # ada sama sekali di form ini):
        self.gl_cash_combo = LookupCombo(
            "/coa/chart-of-accounts/accounts", "id", ("account_code", "account_name"),
            params={"page_size": 5000, "include_inactive": False},
        )
        form.addRow("Akun GL Kas (opsional)", self.gl_cash_combo)
        self.gl_bank_combo = LookupCombo(
            "/coa/chart-of-accounts/accounts", "id", ("account_code", "account_name"),
            params={"page_size": 5000, "include_inactive": False},
        )
        form.addRow("Akun GL Bank (opsional)", self.gl_bank_combo)
        outer.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_save(self) -> None:
        try:
            Decimal(self.opening_edit.text().strip() or "0")
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Saldo awal harus angka.")
            return
        if len(self.currency_edit.text().strip()) != 3:
            QMessageBox.warning(self, "Validasi", "Kode mata uang harus 3 huruf (mis. IDR, USD).")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        payload = {
            "currency_code": self.currency_edit.text().strip().upper() or "IDR",
            "opening_balance": float(Decimal(self.opening_edit.text().strip() or "0")),
            "opening_balance_date": self.date_edit.date().toString("yyyy-MM-dd"),
        }
        gl_cash = self.gl_cash_combo.selected_id()
        if gl_cash:
            payload["gl_cash_account_id"] = gl_cash
        gl_bank = self.gl_bank_combo.selected_id()
        if gl_bank:
            payload["gl_bank_account_id"] = gl_bank
        return payload


# ==========================================================================
class ImportStatementTab(QWidget):
    def __init__(self):
        super().__init__()
        self._file_path = ""
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Import file rekening koran (mutasi bank) untuk mempercepat proses rekonsiliasi. "
            "Format yang didukung tergantung konfigurasi backend (umumnya MT940/CSV)."
        ))

        file_row = QHBoxLayout()
        self.file_label = QLabel("Belum ada file dipilih.")
        file_row.addWidget(self.file_label, stretch=1)
        browse_btn = QPushButton("📁 Pilih File")
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(browse_btn)
        outer.addLayout(file_row)

        form = QFormLayout()
        self.account_combo = LookupCombo(
            f"{BASE}/bank-accounts", "id", ("account_number", "account_name", "bank_name")
        )
        form.addRow("Rekening Bank", self.account_combo)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Statement", self.date_edit)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["mt940", "csv", "ofx", "camt053"])
        form.addRow("Format File", self.format_combo)
        outer.addLayout(form)

        upload_btn = QPushButton("⬆ Import Statement")
        upload_btn.setObjectName("primaryButton")
        upload_btn.clicked.connect(self._upload)
        outer.addWidget(upload_btn)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        outer.addWidget(self.result_text, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Pilih File Rekening Koran")
        if path:
            self._file_path = path
            self.file_label.setText(path.split("/")[-1].split("\\")[-1])

    def _upload(self) -> None:
        if not self._file_path:
            QMessageBox.warning(self, "Validasi", "Pilih file dulu.")
            return
        account_id = self.account_combo.selected_id()
        if not account_id:
            QMessageBox.warning(self, "Validasi", "Rekening bank wajib dipilih.")
            return
        form_fields = {
            "bank_account_id": account_id,
            "statement_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "file_format": self.format_combo.currentText(),
        }
        self.status_label.setText("Mengunggah & memproses statement...")
        run_task(
            api_client.upload_file,
            on_success=self._on_uploaded,
            on_error=self._on_error,
            path=f"{BASE}/import-statement",
            file_path=self._file_path,
            form_fields=form_fields,
        )

    def _on_uploaded(self, result: Any) -> None:
        data = result or {}
        lines = [
            f"Transaksi diimpor: {data.get('transactions_imported', 0)}",
            f"Transaksi cocok otomatis: {data.get('auto_matched', 0)}",
            f"Perlu review manual: {data.get('needs_review', 0)}",
        ]
        self.result_text.setPlainText("\n".join(lines))
        self.status_label.setText("Import selesai.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")
