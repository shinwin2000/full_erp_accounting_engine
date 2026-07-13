"""
ui/pages/journal_page.py
==========================
Jurnal Umum — jantung sistem akuntansi double-entry. Terdiri dari:
  - Daftar jurnal (kiri/atas) dengan filter status
  - Form entry baris debit/kredit dengan validasi balance real-time
  - Tombol workflow: Submit -> Approve/Reject -> Post -> Reverse

Endpoint dasar: /api/v1/journals/journals/
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QMenu,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QDate

from core.api_client import api_client
from core.formatting import extract_list, extract_total, format_date, format_money, status_color
from core.workers import run_task

BASE = "/journals/journals"

STATUS_FILTERS = ["Semua", "draft", "submitted", "approved", "posted", "rejected", "reversed"]


class JournalPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.page = 1
        self._records: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("📒  Jurnal Umum")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()

        self.status_filter = QComboBox()
        self.status_filter.addItems(STATUS_FILTERS)
        self.status_filter.currentTextChanged.connect(lambda _t: self.refresh())
        header.addWidget(self.status_filter)

        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)

        new_btn = QPushButton("+ Jurnal Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._open_new_journal)
        header.addWidget(new_btn)
        outer.addLayout(header)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["No. Jurnal", "Tanggal", "Deskripsi", "Tipe", "Total Debit", "Total Kredit", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda *_: self._open_detail())
        outer.addWidget(self.table, stretch=1)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self.action_btn = QToolButton()
        self.action_btn.setText("Aksi Workflow ▾")
        self.action_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.action_btn)
        for name, label in [
            ("submit", "Submit untuk Approval"),
            ("approve", "Approve"),
            ("reject", "Reject"),
            ("post", "Post ke Ledger"),
            ("reverse", "Reverse (Jurnal Balik)"),
            ("unpost", "Unpost"),
            ("lock", "Lock"),
            ("unlock", "Unlock"),
        ]:
            act = menu.addAction(label)
            act.triggered.connect(lambda checked=False, n=name: self._run_workflow(n))
        self.action_btn.setMenu(menu)
        action_row.addWidget(self.action_btn)

        detail_btn = QPushButton("🔍 Lihat Detail")
        detail_btn.clicked.connect(self._open_detail)
        action_row.addWidget(detail_btn)
        outer.addLayout(action_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        params: dict[str, Any] = {"page": self.page, "page_size": 100}
        status = self.status_filter.currentText()
        if status != "Semua":
            params["status"] = status
        self.status_label.setText("Memuat jurnal...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/", params=params)

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            values = [
                rec.get("journal_number", ""),
                format_date(rec.get("journal_date")),
                rec.get("description", ""),
                str(rec.get("journal_type", "")),
                format_money(rec.get("total_debit")),
                format_money(rec.get("total_credit")),
                str(rec.get("status", "")),
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col in (4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 6:
                    from PySide6.QtGui import QColor
                    item.setForeground(QColor(status_color(val)))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} jurnal dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    # ------------------------------------------------------------------
    def _selected_record(self) -> Optional[dict[str, Any]]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    def _open_new_journal(self) -> None:
        dlg = JournalEntryDialog(parent=self)
        if dlg.exec():
            payload = dlg.build_payload()
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Jurnal berhasil dibuat (draft)."),
                on_error=self._on_write_error,
                path=f"{BASE}/",
                json_body=payload,
            )

    def _open_detail(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih jurnal terlebih dahulu.")
            return
        journal_id = record.get("id")
        run_task(api_client.get, on_success=self._show_detail_dialog, on_error=self._on_error,
                  path=f"{BASE}/{journal_id}")

    def _show_detail_dialog(self, data: dict[str, Any]) -> None:
        dlg = JournalEntryDialog(existing=data, parent=self, read_only=True)
        dlg.exec()

    def _run_workflow(self, action_name: str) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih jurnal terlebih dahulu.")
            return
        journal_id = record.get("id")
        body: dict[str, Any] = {}

        if action_name == "reject":
            reason, ok = _prompt_text(self, "Alasan Reject", "Masukkan alasan penolakan (min. 5 karakter):")
            if not ok or len(reason) < 5:
                return
            body = {"reason": reason}
        elif action_name == "reverse":
            reason, ok = _prompt_text(self, "Alasan Reverse", "Masukkan alasan pembalikan jurnal:")
            if not ok or len(reason) < 5:
                return
            body = {"reason": reason, "post_immediately": True}
        else:
            confirm = QMessageBox.question(self, "Konfirmasi", f"Jalankan aksi '{action_name}' pada jurnal ini?")
            if confirm != QMessageBox.Yes:
                return

        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Aksi '{action_name}' berhasil."),
            on_error=self._on_write_error,
            path=f"{BASE}/{journal_id}/{action_name}",
            json_body=body,
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


def _prompt_text(parent, title: str, label: str) -> tuple[str, bool]:
    from PySide6.QtWidgets import QInputDialog
    text, ok = QInputDialog.getMultiLineText(parent, title, label)
    return text.strip(), ok


# ==========================================================================
# Dialog entry jurnal (baris debit/kredit dengan validasi balance)
# ==========================================================================
LINE_COLUMNS = ["Kode Akun", "Debit", "Kredit", "Cost Center", "Departemen", "Keterangan"]


class JournalEntryDialog(QDialog):
    def __init__(self, existing: Optional[dict[str, Any]] = None, parent=None, read_only: bool = False):
        super().__init__(parent)
        self.existing = existing or {}
        self.read_only = read_only
        self.setWindowTitle("Detail Jurnal" if read_only else "Jurnal Baru")
        self.resize(760, 560)
        self._build_ui()
        if existing:
            self._load_existing()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        form = QFormLayout()
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Jurnal", self.date_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Deskripsi jurnal (min. 3 karakter)")
        form.addRow("Deskripsi", self.desc_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["general", "adjusting", "closing", "reversing", "opening"])
        form.addRow("Tipe Jurnal", self.type_combo)

        self.ref_edit = QLineEdit()
        form.addRow("No. Referensi", self.ref_edit)

        outer.addLayout(form)

        outer.addWidget(QLabel("Baris Jurnal (total debit harus sama dengan total kredit):"))
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
        outer.addLayout(line_btns)

        balance_row = QHBoxLayout()
        self.total_debit_label = QLabel("Total Debit: Rp 0")
        self.total_credit_label = QLabel("Total Kredit: Rp 0")
        self.balance_label = QLabel("")
        self.balance_label.setStyleSheet("font-weight:700;")
        balance_row.addWidget(self.total_debit_label)
        balance_row.addWidget(self.total_credit_label)
        balance_row.addStretch()
        balance_row.addWidget(self.balance_label)
        outer.addLayout(balance_row)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Catatan tambahan (opsional)")
        self.notes_edit.setFixedHeight(50)
        outer.addWidget(self.notes_edit)

        if self.read_only:
            self.status_summary = QLabel("")
            self.status_summary.setWordWrap(True)
            outer.addWidget(self.status_summary)
            for w in (self.date_edit, self.desc_edit, self.type_combo, self.ref_edit, self.notes_edit):
                w.setEnabled(False)
            self.line_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.reject)
            buttons.accepted.connect(self.accept)
        else:
            self._add_line()
            self._add_line()
            buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Save).setText("Simpan sebagai Draft")
            buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
            buttons.button(QDialogButtonBox.Cancel).setText("Batal")
            buttons.accepted.connect(self._on_save)
            buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _add_line(self, data: Optional[dict[str, Any]] = None) -> None:
        row = self.line_table.rowCount()
        self.line_table.insertRow(row)
        data = data or {}
        values = [
            str(data.get("account_code", "")),
            str(data.get("debit_amount", "") or ""),
            str(data.get("credit_amount", "") or ""),
            str(data.get("cost_center", "") or ""),
            str(data.get("department", "") or ""),
            str(data.get("description", "") or ""),
        ]
        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            self.line_table.setItem(row, col, item)
        self.line_table.itemChanged.connect(self._recalc_balance)
        self._recalc_balance()

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)
            self._recalc_balance()

    def _recalc_balance(self, *_args) -> None:
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for row in range(self.line_table.rowCount()):
            total_debit += _to_decimal(self._cell(row, 1))
            total_credit += _to_decimal(self._cell(row, 2))
        self.total_debit_label.setText(f"Total Debit: {format_money(total_debit)}")
        self.total_credit_label.setText(f"Total Kredit: {format_money(total_credit)}")
        diff = abs(total_debit - total_credit)
        if diff <= Decimal("0.01") and total_debit > 0:
            self.balance_label.setText("✅ Balance")
            self.balance_label.setStyleSheet("font-weight:700; color:#059669;")
        else:
            self.balance_label.setText(f"⚠️ Selisih {format_money(diff)}")
            self.balance_label.setStyleSheet("font-weight:700; color:#DC2626;")

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def build_payload(self) -> dict[str, Any]:
        lines = []
        for row in range(self.line_table.rowCount()):
            account_code = self._cell(row, 0).strip()
            if not account_code:
                continue
            lines.append({
                "account_code": account_code,
                "debit_amount": float(_to_decimal(self._cell(row, 1))),
                "credit_amount": float(_to_decimal(self._cell(row, 2))),
                "cost_center": self._cell(row, 3).strip() or None,
                "department": self._cell(row, 4).strip() or None,
                "description": self._cell(row, 5).strip() or None,
            })
        return {
            "journal_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "description": self.desc_edit.text().strip(),
            "journal_type": self.type_combo.currentText(),
            "lines": lines,
            "reference_number": self.ref_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }

    def _on_save(self) -> None:
        desc = self.desc_edit.text().strip()
        if len(desc) < 3:
            QMessageBox.warning(self, "Validasi", "Deskripsi minimal 3 karakter.")
            return
        lines = [row for row in range(self.line_table.rowCount()) if self._cell(row, 0).strip()]
        if len(lines) < 2:
            QMessageBox.warning(self, "Validasi", "Minimal 2 baris jurnal diperlukan.")
            return
        total_debit = sum(_to_decimal(self._cell(r, 1)) for r in range(self.line_table.rowCount()))
        total_credit = sum(_to_decimal(self._cell(r, 2)) for r in range(self.line_table.rowCount()))
        if abs(total_debit - total_credit) > Decimal("0.01"):
            QMessageBox.warning(self, "Validasi", "Total debit harus sama dengan total kredit.")
            return
        self.accept()

    def _load_existing(self) -> None:
        data = self.existing
        try:
            y, m, d = str(data.get("journal_date", "")).split("-")[:3]
            self.date_edit.setDate(QDate(int(y), int(m), int(d[:2])))
        except (ValueError, IndexError):
            pass
        self.desc_edit.setText(data.get("description", ""))
        idx = self.type_combo.findText(str(data.get("journal_type", "")))
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.ref_edit.setText(data.get("reference_number") or "")
        self.notes_edit.setPlainText(data.get("notes") or "")

        self.line_table.setRowCount(0)
        for line in data.get("lines", []):
            self._add_line(line)

        summary = (
            f"No. Jurnal: <b>{data.get('journal_number')}</b> &nbsp;|&nbsp; "
            f"Status: <b style='color:{status_color(str(data.get('status')))}'>{data.get('status')}</b><br>"
            f"Dibuat oleh: {data.get('created_by_name') or data.get('created_by')} "
            f"pada {format_date(data.get('created_at'))}<br>"
        )
        if data.get("approved_by_name"):
            summary += f"Disetujui oleh: {data.get('approved_by_name')} pada {format_date(data.get('approved_at'))}<br>"
        if data.get("posted_by_name"):
            summary += f"Diposting oleh: {data.get('posted_by_name')} pada {format_date(data.get('posted_at'))}<br>"
        if data.get("rejection_reason"):
            summary += f"<span style='color:#DC2626;'>Alasan reject: {data.get('rejection_reason')}</span><br>"
        self.status_summary.setText(summary)


def _to_decimal(text: str) -> Decimal:
    text = (text or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")
