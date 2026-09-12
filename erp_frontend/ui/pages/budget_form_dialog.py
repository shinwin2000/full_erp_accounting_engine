"""
ui/pages/budget_form_dialog.py
=================================
Dialog "Tambah Budget" dengan editor baris anggaran (line items).

LATAR BELAKANG (bug yang diperbaiki):
    Sebelumnya `budgets_page.py` memakai form generik (`FieldSpec`/`FormDialog`)
    yang hanya mengisi field header budget. Tapi endpoint
    `POST /api/v1/budget/budget/` mewajibkan `lines` (minimal 1 baris, masing-
    masing butuh `account_id` + `account_code` + `amount`) -- field yang sama
    sekali tidak ada di form generik. Akibatnya membuat budget baru lewat UI
    SELALU gagal 422 "Field required: lines" (persis seperti di log backend).

    Dialog ini meniru pola yang sudah terbukti dipakai di `journal_page.py`
    (`JournalEntryDialog`): tabel baris + tombol tambah/hapus baris. Kolom
    "Kode Akun" berupa dropdown (QComboBox) berisi daftar akun dari Bagan
    Akun (COA) -- bukan input teks bebas -- supaya pengguna tinggal pilih
    dan `account_id` selalu valid (tidak mungkin salah ketik / akun tidak
    ditemukan).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import format_money
from core.workers import run_task
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

LINE_COLUMNS = ["Kode Akun", "Jumlah", "Catatan"]

BUDGET_TYPES = [
    "operational", "capital", "cash", "project", "department",
    "fixed_asset", "sales", "production", "labor",
]
BUDGET_PERIODS = ["monthly", "quarterly", "yearly"]


def _to_decimal(text: str) -> Decimal:
    text = (text or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


class BudgetFormDialog(QDialog):
    """Dialog Tambah Budget: header + baris anggaran (line items)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accounts: list[dict[str, str]] = []  # [{"code":..., "name":..., "id":...}, ...]
        self.setWindowTitle("Tambah Budget / Anggaran")
        self.resize(760, 620)
        self._build_ui()
        self._add_line()
        self._load_account_codes()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        form = QFormLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("mis. OPX-2026-001 (min. 3 karakter)")
        form.addRow("Kode Budget", self.code_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("mis. Anggaran Operasional 2026")
        form.addRow("Nama Budget", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(BUDGET_TYPES)
        form.addRow("Tipe Budget", self.type_combo)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(QDate.currentDate().year())
        form.addRow("Tahun Fiskal", self.year_spin)

        self.period_combo = QComboBox()
        self.period_combo.addItems(BUDGET_PERIODS)
        form.addRow("Periode", self.period_combo)

        self.version_edit = QLineEdit("1.0")
        form.addRow("Versi", self.version_edit)

        self.effective_date_edit = QDateEdit(QDate.currentDate())
        self.effective_date_edit.setCalendarPopup(True)
        form.addRow("Berlaku Sejak", self.effective_date_edit)

        expiry_row = QHBoxLayout()
        self.has_expiry_check = QCheckBox("Isi tanggal akhir")
        self.expiry_date_edit = QDateEdit(QDate.currentDate().addYears(1))
        self.expiry_date_edit.setCalendarPopup(True)
        self.expiry_date_edit.setEnabled(False)
        self.has_expiry_check.toggled.connect(self.expiry_date_edit.setEnabled)
        expiry_row.addWidget(self.has_expiry_check)
        expiry_row.addWidget(self.expiry_date_edit)
        form.addRow("Berlaku Sampai", expiry_row)

        self.currency_edit = QLineEdit("IDR")
        form.addRow("Mata Uang", self.currency_edit)

        outer.addLayout(form)

        outer.addWidget(QLabel("Baris Anggaran (minimal 1 baris):"))
        self.line_table = QTableWidget(0, len(LINE_COLUMNS))
        self.line_table.setHorizontalHeaderLabels(LINE_COLUMNS)
        self.line_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.line_table, stretch=1)

        line_btns = QHBoxLayout()
        add_btn = QPushButton("+ Tambah Baris")
        add_btn.clicked.connect(lambda: self._add_line())
        remove_btn = QPushButton("- Hapus Baris")
        remove_btn.clicked.connect(self._remove_line)
        line_btns.addWidget(add_btn)
        line_btns.addWidget(remove_btn)
        line_btns.addStretch()
        self.total_label = QLabel("Total: Rp 0")
        self.total_label.setStyleSheet("font-weight:700;")
        line_btns.addWidget(self.total_label)
        outer.addLayout(line_btns)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Catatan tambahan (opsional)")
        self.notes_edit.setFixedHeight(50)
        outer.addWidget(self.notes_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Cancel).setText("Batal")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------
    def _make_account_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        combo.completer().setFilterMode(Qt.MatchContains)
        combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self._populate_combo(combo)
        combo.currentIndexChanged.connect(self._recalc_total)
        return combo

    def _populate_combo(self, combo: QComboBox) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— pilih akun —", None)
        for acc in self._accounts:
            combo.addItem(f"{acc['code']} — {acc['name']}", (acc["code"], acc["id"]))
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _add_line(self) -> None:
        row = self.line_table.rowCount()
        self.line_table.insertRow(row)
        combo = self._make_account_combo()
        self.line_table.setCellWidget(row, 0, combo)
        for col in (1, 2):
            self.line_table.setItem(row, col, QTableWidgetItem(""))
        self.line_table.itemChanged.connect(self._recalc_total)

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)
            self._recalc_total()

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _line_account(self, row: int) -> tuple[str, str] | None:
        """Kembalikan (account_code, account_id) yang dipilih di baris, atau None."""
        combo = self.line_table.cellWidget(row, 0)
        if not isinstance(combo, QComboBox):
            return None
        return combo.currentData()

    def _recalc_total(self, *_args) -> None:
        total = sum(_to_decimal(self._cell(r, 1)) for r in range(self.line_table.rowCount()))
        self.total_label.setText(f"Total: {format_money(total)}")

    # ------------------------------------------------------------------
    def _load_account_codes(self) -> None:
        """Muat daftar akun COA (non-blocking) untuk mengisi dropdown akun."""
        run_task(
            api_client.get, on_success=self._on_accounts_loaded, on_error=lambda _m: None,
            path="/coa/chart-of-accounts/accounts", params={"page_size": 1000, "limit": 1000},
        )

    def _on_accounts_loaded(self, payload: Any) -> None:
        from core.formatting import extract_list
        accounts = extract_list(payload)
        self._accounts = sorted(
            (
                {"code": str(a.get("account_code", "")), "name": str(a.get("account_name", "")), "id": str(a.get("id"))}
                for a in accounts if a.get("account_code") and a.get("id")
            ),
            key=lambda a: a["code"],
        )
        # Isi ulang dropdown yang sudah terlanjur dibuat (mis. baris pertama
        # yang ditambahkan sebelum daftar akun ini selesai dimuat).
        for row in range(self.line_table.rowCount()):
            combo = self.line_table.cellWidget(row, 0)
            if isinstance(combo, QComboBox):
                current = combo.currentData()
                self._populate_combo(combo)
                if current:
                    idx = combo.findData(current)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    def _on_save(self) -> None:
        code = self.code_edit.text().strip()
        name = self.name_edit.text().strip()
        if len(code) < 3:
            QMessageBox.warning(self, "Validasi", "Kode budget minimal 3 karakter.")
            return
        if len(name) < 3:
            QMessageBox.warning(self, "Validasi", "Nama budget minimal 3 karakter.")
            return

        if not self._accounts:
            QMessageBox.warning(
                self, "Data Akun Belum Siap",
                "Daftar akun COA belum berhasil dimuat. Coba lagi sebentar lalu ulangi simpan.",
            )
            return

        lines: list[dict[str, Any]] = []
        empty_account_rows: list[int] = []
        for row in range(self.line_table.rowCount()):
            selected = self._line_account(row)
            amount_text = self._cell(row, 1).strip()
            note_text = self._cell(row, 2).strip()
            if selected is None:
                if amount_text or note_text:
                    empty_account_rows.append(row + 1)
                continue  # baris kosong sepenuhnya -> lewati

            account_code, account_id = selected
            amount = _to_decimal(amount_text)
            if amount < 0:
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: jumlah tidak boleh negatif.")
                return
            lines.append({
                "account_id": account_id,
                "account_code": account_code,
                "amount": float(amount),
                "note": note_text or None,
            })

        if empty_account_rows:
            listing = ", ".join(str(r) for r in empty_account_rows)
            QMessageBox.warning(
                self, "Validasi",
                f"Baris {listing}: pilih akun terlebih dahulu (dropdown Kode Akun masih kosong).",
            )
            return

        if not lines:
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris anggaran diperlukan.")
            return

        self._payload = {
            "budget_code": code,
            "budget_name": name,
            "budget_type": self.type_combo.currentText(),
            "fiscal_year": self.year_spin.value(),
            "period": self.period_combo.currentText(),
            "version": self.version_edit.text().strip() or "1.0",
            "effective_date": self.effective_date_edit.date().toString("yyyy-MM-dd"),
            "expiry_date": (
                self.expiry_date_edit.date().toString("yyyy-MM-dd")
                if self.has_expiry_check.isChecked() else None
            ),
            "currency": self.currency_edit.text().strip() or "IDR",
            "lines": lines,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
        self.accept()

    def result_payload(self) -> dict[str, Any]:
        return self._payload
