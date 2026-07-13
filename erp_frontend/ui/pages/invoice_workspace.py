"""
ui/pages/invoice_workspace.py
===============================
Workspace generik untuk Piutang (AR) dan Utang (AP) — dua modul ini
sangat mirip secara struktur (invoice header + lines, payment, aging,
approval workflow), jadi dibuat satu widget yang dikonfigurasi lewat
`InvoiceWorkspaceConfig` untuk menghindari duplikasi kode.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money, status_color
from core.workers import run_task
from ui.widgets.kpi_card import KpiCard


class InvoiceWorkspaceConfig:
    def __init__(
        self,
        base_path: str,
        label: str,
        icon: str,
        party_code_field: str,   # "customer_code" | "vendor_code"
        party_label: str,        # "Customer" | "Vendor"
        invoice_number_field: str,  # "invoice_number" | "invoice_number_vendor"
        account_hint: str,       # akun default lawan transaksi (revenue/expense)
    ):
        self.base_path = base_path
        self.label = label
        self.icon = icon
        self.party_code_field = party_code_field
        self.party_label = party_label
        self.invoice_number_field = invoice_number_field
        self.account_hint = account_hint


AR_CONFIG = InvoiceWorkspaceConfig(
    base_path="/ar/ar", label="Piutang (Account Receivable)", icon="💰",
    party_code_field="customer_code", party_label="Customer",
    invoice_number_field="invoice_number", account_hint="Akun Pendapatan (mis. 4-1100)",
)
AP_CONFIG = InvoiceWorkspaceConfig(
    base_path="/ap/ap", label="Utang (Account Payable)", icon="💳",
    party_code_field="vendor_code", party_label="Vendor",
    invoice_number_field="invoice_number_vendor", account_hint="Akun Beban (mis. 5-1100)",
)

STATUS_FILTERS = ["Semua", "draft", "submitted", "approved", "posted", "paid", "partially_paid", "rejected", "cancelled"]


class InvoiceWorkspacePage(QWidget):
    def __init__(self, config: InvoiceWorkspaceConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._records: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel(f"{self.config.icon}  {self.config.label}")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        outer.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_invoice_tab(), "Daftar Invoice")
        self.tabs.addTab(self._build_aging_tab(), "Aging Report")
        outer.addWidget(self.tabs, stretch=1)

    def _build_invoice_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        toolbar = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(STATUS_FILTERS)
        self.status_filter.currentTextChanged.connect(lambda _t: self.refresh())
        toolbar.addWidget(self.status_filter)

        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()

        self.action_btn = QToolButton()
        self.action_btn.setText("Aksi Workflow ▾")
        self.action_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.action_btn)
        for name, label in [
            ("submit", "Submit"), ("approve", "Approve"), ("reject", "Reject"),
            ("post", "Post"), ("reverse", "Reverse"),
        ]:
            act = menu.addAction(label)
            act.triggered.connect(lambda checked=False, n=name: self._run_workflow(n))
        self.action_btn.setMenu(menu)
        toolbar.addWidget(self.action_btn)

        pay_btn = QPushButton("💵 Catat Pembayaran")
        pay_btn.clicked.connect(self._record_payment)
        toolbar.addWidget(pay_btn)

        new_btn = QPushButton("+ Invoice Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_invoice)
        toolbar.addWidget(new_btn)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["No. Invoice", "Tanggal", f"{self.config.party_label}", "Total", "Terbayar", "Sisa", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        layout.addWidget(self.status_label)
        return tab

    def _build_aging_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("⟳ Muat Aging Report")
        load_btn.clicked.connect(self._load_aging)
        btn_row.addWidget(load_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        cards_row = QHBoxLayout()
        self.aging_cards = {
            "current": KpiCard("Belum Jatuh Tempo", color="#059669"),
            "1_30": KpiCard("1-30 Hari", color="#D97706"),
            "31_60": KpiCard("31-60 Hari", color="#EA580C"),
            "61_90": KpiCard("61-90 Hari", color="#DC2626"),
            "over_90": KpiCard(">90 Hari", color="#991B1B"),
        }
        for card in self.aging_cards.values():
            cards_row.addWidget(card)
        layout.addLayout(cards_row)

        self.aging_table = QTableWidget(0, 6)
        self.aging_table.setHorizontalHeaderLabels(
            [self.config.party_label, "Current", "1-30", "31-60", "61-90", ">90"]
        )
        self.aging_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.aging_table, stretch=1)
        return tab

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        params: dict[str, Any] = {"page": 1, "page_size": 100}
        status = self.status_filter.currentText()
        if status != "Semua":
            params["status"] = status
        self.status_label.setText("Memuat invoice...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{self.config.base_path}/invoices", params=params)

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            party_name = rec.get("customer_name") or rec.get("vendor_name") or rec.get("supplier_name") or "-"
            values = [
                rec.get(self.config.invoice_number_field, rec.get("invoice_number", "")),
                format_date(rec.get("invoice_date")),
                party_name,
                format_money(rec.get("total_amount")),
                format_money(rec.get("paid_amount")),
                format_money(rec.get("outstanding_amount")),
                str(rec.get("status", "")),
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col in (3, 4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 6:
                    item.setForeground(QColor(status_color(val)))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} invoice dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _load_aging(self) -> None:
        run_task(api_client.get, on_success=self._on_aging_loaded, on_error=self._on_error,
                  path=f"{self.config.base_path}/aging")

    def _on_aging_loaded(self, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else {}
        buckets = data.get("summary") or data.get("buckets") or {}
        mapping = {
            "current": buckets.get("current") or buckets.get("not_due"),
            "1_30": buckets.get("1_30") or buckets.get("days_1_30"),
            "31_60": buckets.get("31_60") or buckets.get("days_31_60"),
            "61_90": buckets.get("61_90") or buckets.get("days_61_90"),
            "over_90": buckets.get("over_90") or buckets.get("days_over_90"),
        }
        for key, card in self.aging_cards.items():
            val = mapping.get(key)
            card.set_value(format_money(val) if val is not None else "-")

        rows = extract_list(data.get("details") or data.get("by_party") or [])
        self.aging_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            party = item.get("customer_name") or item.get("vendor_name") or item.get("name", "-")
            vals = [
                party,
                format_money(item.get("current", 0)),
                format_money(item.get("days_1_30", item.get("1_30", 0))),
                format_money(item.get("days_31_60", item.get("31_60", 0))),
                format_money(item.get("days_61_90", item.get("61_90", 0))),
                format_money(item.get("days_over_90", item.get("over_90", 0))),
            ]
            for c, v in enumerate(vals):
                self.aging_table.setItem(r, c, QTableWidgetItem(v))
        self.aging_table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    def _selected_record(self) -> Optional[dict[str, Any]]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    def _new_invoice(self) -> None:
        dlg = InvoiceFormDialog(self.config, parent=self)
        if dlg.exec():
            payload = dlg.build_payload()
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Invoice berhasil dibuat."),
                on_error=self._on_write_error,
                path=f"{self.config.base_path}/invoices",
                json_body=payload,
            )

    def _record_payment(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih invoice terlebih dahulu.")
            return
        dlg = PaymentFormDialog(record, parent=self)
        if dlg.exec():
            payload = dlg.build_payload()
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Pembayaran dicatat."),
                on_error=self._on_write_error,
                path=f"{self.config.base_path}/payments",
                json_body=payload,
            )

    def _run_workflow(self, action_name: str) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih invoice terlebih dahulu.")
            return
        invoice_id = record.get("id")
        body: dict[str, Any] = {}
        if action_name == "reject":
            from PySide6.QtWidgets import QInputDialog
            reason, ok = QInputDialog.getMultiLineText(self, "Alasan Reject", "Alasan penolakan:")
            if not ok or len(reason.strip()) < 5:
                return
            body = {"reason": reason.strip()}
        elif action_name == "reverse":
            from PySide6.QtWidgets import QInputDialog
            reason, ok = QInputDialog.getMultiLineText(self, "Alasan Reverse", "Alasan pembalikan:")
            if not ok or len(reason.strip()) < 5:
                return
            body = {"reason": reason.strip()}
        else:
            confirm = QMessageBox.question(self, "Konfirmasi", f"Jalankan aksi '{action_name}'?")
            if confirm != QMessageBox.Yes:
                return
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Aksi '{action_name}' berhasil."),
            on_error=self._on_write_error,
            path=f"{self.config.base_path}/invoices/{invoice_id}/{action_name}",
            json_body=body,
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class InvoiceFormDialog(QDialog):
    LINE_COLS = ["Deskripsi", "Qty", "Harga Satuan", "Diskon %", "Pajak %", "Kode Akun"]

    def __init__(self, config: InvoiceWorkspaceConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(f"Invoice {config.party_label} Baru")
        self.resize(720, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        form = QFormLayout()

        self.party_edit = QLineEdit()
        self.party_edit.setPlaceholderText(f"Kode {self.config.party_label} (mis. CUST-0001)")
        form.addRow(f"Kode {self.config.party_label}", self.party_edit)

        self.invoice_no_edit = QLineEdit()
        form.addRow("No. Invoice", self.invoice_no_edit)

        self.invoice_date = QDateEdit(QDate.currentDate())
        self.invoice_date.setCalendarPopup(True)
        form.addRow("Tanggal Invoice", self.invoice_date)

        self.due_date = QDateEdit(QDate.currentDate().addDays(30))
        self.due_date.setCalendarPopup(True)
        form.addRow("Tanggal Jatuh Tempo", self.due_date)

        self.desc_edit = QLineEdit()
        form.addRow("Deskripsi", self.desc_edit)

        self.ref_edit = QLineEdit()
        form.addRow("No. Referensi", self.ref_edit)

        outer.addLayout(form)
        outer.addWidget(QLabel(f"Baris Invoice ({self.config.account_hint}):"))

        self.line_table = QTableWidget(0, len(self.LINE_COLS))
        self.line_table.setHorizontalHeaderLabels(self.LINE_COLS)
        self.line_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.line_table, stretch=1)

        line_btns = QHBoxLayout()
        add_btn = QPushButton("+ Baris")
        add_btn.clicked.connect(lambda: self._add_line())
        remove_btn = QPushButton("- Hapus Baris")
        remove_btn.clicked.connect(self._remove_line)
        line_btns.addWidget(add_btn)
        line_btns.addWidget(remove_btn)
        line_btns.addStretch()
        outer.addLayout(line_btns)
        self._add_line()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Cancel).setText("Batal")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _add_line(self) -> None:
        row = self.line_table.rowCount()
        self.line_table.insertRow(row)
        defaults = ["", "1", "0", "0", "11", ""]
        for col, val in enumerate(defaults):
            self.line_table.setItem(row, col, QTableWidgetItem(val))

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)

    def build_payload(self) -> dict[str, Any]:
        lines = []
        for row in range(self.line_table.rowCount()):
            desc = self._cell(row, 0).strip()
            if not desc:
                continue
            lines.append({
                "description": desc,
                "quantity": float(_to_decimal(self._cell(row, 1)) or 1),
                "unit_price": float(_to_decimal(self._cell(row, 2))),
                "discount_percent": float(_to_decimal(self._cell(row, 3))),
                "tax_rate": float(_to_decimal(self._cell(row, 4))),
                "account_code": self._cell(row, 5).strip(),
            })
        payload = {
            self.config.party_code_field: self.party_edit.text().strip(),
            "invoice_date": self.invoice_date.date().toString("yyyy-MM-dd"),
            "due_date": self.due_date.date().toString("yyyy-MM-dd"),
            self.config.invoice_number_field: self.invoice_no_edit.text().strip(),
            "lines": lines,
            "description": self.desc_edit.text().strip(),
            "reference_number": self.ref_edit.text().strip() or None,
            "use_tax": True,
        }
        return payload

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _on_save(self) -> None:
        if not self.party_edit.text().strip():
            QMessageBox.warning(self, "Validasi", f"Kode {self.config.party_label} wajib diisi.")
            return
        if not self.invoice_no_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "No. invoice wajib diisi.")
            return
        if self.line_table.rowCount() == 0 or not self._cell(0, 0).strip():
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris invoice diperlukan.")
            return
        self.accept()


class PaymentFormDialog(QDialog):
    def __init__(self, invoice: dict[str, Any], parent=None):
        super().__init__(parent)
        self.invoice = invoice
        self.setWindowTitle(f"Catat Pembayaran — {invoice.get('invoice_number', '')}")
        self.resize(400, 300)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        info = QLabel(
            f"Invoice: <b>{self.invoice.get('invoice_number', self.invoice.get('invoice_number_vendor', ''))}</b><br>"
            f"Sisa Tagihan: <b>{format_money(self.invoice.get('outstanding_amount'))}</b>"
        )
        outer.addWidget(info)

        form = QFormLayout()
        self.amount_edit = QLineEdit(str(self.invoice.get("outstanding_amount", "") or ""))
        form.addRow("Jumlah Bayar", self.amount_edit)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Bayar", self.date_edit)

        self.method_combo = QComboBox()
        self.method_combo.addItems(["transfer", "cash", "check", "credit_card", "other"])
        form.addRow("Metode", self.method_combo)

        self.ref_edit = QLineEdit()
        form.addRow("No. Referensi", self.ref_edit)

        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)

        outer.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_save(self) -> None:
        try:
            amt = Decimal(self.amount_edit.text().strip())
            if amt <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah bayar harus > 0.")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        return {
            "invoice_id": self.invoice.get("id"),
            "payment_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "amount": float(Decimal(self.amount_edit.text().strip())),
            "payment_method": self.method_combo.currentText(),
            "reference_number": self.ref_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
        }


def _to_decimal(text: str) -> Decimal:
    text = (text or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")
