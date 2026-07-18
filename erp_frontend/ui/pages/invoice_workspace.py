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
    QCheckBox,
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
        has_write_off: bool = False,
        has_collection: bool = False,
        has_payment_run: bool = False,
        has_three_way_match: bool = False,
    ):
        self.base_path = base_path
        self.label = label
        self.icon = icon
        self.party_code_field = party_code_field
        self.party_label = party_label
        self.invoice_number_field = invoice_number_field
        self.account_hint = account_hint
        self.has_write_off = has_write_off
        self.has_collection = has_collection
        self.has_payment_run = has_payment_run
        self.has_three_way_match = has_three_way_match


AR_CONFIG = InvoiceWorkspaceConfig(
    base_path="/ar/ar", label="Piutang (Account Receivable)", icon="💰",
    party_code_field="customer_code", party_label="Customer",
    invoice_number_field="invoice_number", account_hint="Akun Pendapatan (mis. 4-1100)",
    has_write_off=True, has_collection=True,
)
AP_CONFIG = InvoiceWorkspaceConfig(
    base_path="/ap/ap", label="Utang (Account Payable)", icon="💳",
    party_code_field="vendor_code", party_label="Vendor",
    invoice_number_field="invoice_number_vendor", account_hint="Akun Beban (mis. 5-1100)",
    has_payment_run=True, has_three_way_match=True,
)

STATUS_FILTERS = ["Semua", "draft", "submitted", "approved", "posted", "paid", "partially_paid", "rejected", "cancelled"]


class InvoiceWorkspacePage(QWidget):
    def __init__(self, config: InvoiceWorkspaceConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.page = 1
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
        self.tabs.addTab(CreditNoteTab(self.config), "Credit Note")
        if self.config.has_write_off:
            self.tabs.addTab(WriteOffTab(self.config), "Write-off")
        if self.config.has_collection:
            self.tabs.addTab(CollectionTab(self.config), "Collection")
        if self.config.has_payment_run:
            self.tabs.addTab(PaymentRunTab(self.config), "Payment Run")
        if self.config.has_three_way_match:
            self.tabs.addTab(ThreeWayMatchTab(self.config), "3-Way Match")
        outer.addWidget(self.tabs, stretch=1)

    def _build_invoice_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        toolbar = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(STATUS_FILTERS)
        self.status_filter.currentTextChanged.connect(lambda _t: self._reset_and_refresh())
        toolbar.addWidget(self.status_filter)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cari no. invoice...")
        self.search_edit.setMaximumWidth(200)
        self.search_edit.returnPressed.connect(self._reset_and_refresh)
        toolbar.addWidget(self.search_edit)

        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()

        detail_btn = QPushButton("🔍 Lihat Detail")
        detail_btn.clicked.connect(self._view_detail)
        toolbar.addWidget(detail_btn)

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
        self.table.doubleClicked.connect(lambda *_: self._view_detail())
        layout.addWidget(self.table, stretch=1)

        pager_row = QHBoxLayout()
        self.pager_label = QLabel("")
        self.pager_label.setStyleSheet("color:#6B7280;")
        pager_row.addWidget(self.pager_label)
        pager_row.addStretch()
        self.prev_btn = QPushButton("‹ Sebelumnya")
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = QPushButton("Berikutnya ›")
        self.next_btn.clicked.connect(self._next_page)
        pager_row.addWidget(self.prev_btn)
        pager_row.addWidget(self.next_btn)
        layout.addLayout(pager_row)

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
    PAGE_SIZE = 50

    def _reset_and_refresh(self) -> None:
        self.page = 1
        self.refresh()

    def refresh(self) -> None:
        params: dict[str, Any] = {"page": self.page, "page_size": self.PAGE_SIZE}
        status = self.status_filter.currentText()
        if status != "Semua":
            params["status"] = status
        search = self.search_edit.text().strip()
        if search:
            params["search"] = search
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
        start = (self.page - 1) * self.PAGE_SIZE + 1 if self._records else 0
        end = start + len(self._records) - 1 if self._records else 0
        self.pager_label.setText(f"Menampilkan {start}-{end}")
        self.prev_btn.setEnabled(self.page > 1)
        self.next_btn.setEnabled(len(self._records) == self.PAGE_SIZE)
        self.status_label.setText(f"{len(self._records)} invoice dimuat.")

    def _prev_page(self) -> None:
        if self.page > 1:
            self.page -= 1
            self.refresh()

    def _next_page(self) -> None:
        self.page += 1
        self.refresh()

    def _view_detail(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih invoice terlebih dahulu.")
            return
        invoice_id = record.get("id")
        run_task(api_client.get, on_success=self._show_detail_dialog, on_error=self._on_error,
                  path=f"{self.config.base_path}/invoices/{invoice_id}")

    def _show_detail_dialog(self, data: dict[str, Any]) -> None:
        dlg = InvoiceDetailDialog(self.config, data, parent=self)
        dlg.exec()

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
        if not self.desc_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Deskripsi invoice wajib diisi (field ini wajib di backend).")
            return
        if self.due_date.date() < self.invoice_date.date():
            QMessageBox.warning(self, "Validasi", "Tanggal jatuh tempo tidak boleh sebelum tanggal invoice.")
            return

        filled_rows = [r for r in range(self.line_table.rowCount()) if self._cell(r, 0).strip()]
        if not filled_rows:
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris invoice diperlukan.")
            return

        for row in filled_rows:
            qty = _to_decimal(self._cell(row, 1))
            unit_price = _to_decimal(self._cell(row, 2))
            discount = _to_decimal(self._cell(row, 3))
            tax = _to_decimal(self._cell(row, 4))
            account_code = self._cell(row, 5).strip()
            if qty <= 0:
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Qty harus > 0.")
                return
            if unit_price <= 0:
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Harga satuan harus > 0.")
                return
            if not (0 <= discount <= 100):
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Diskon harus di antara 0-100%.")
                return
            if not (0 <= tax <= 100):
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Pajak harus di antara 0-100%.")
                return
            if not account_code:
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Kode akun wajib diisi ({self.config.account_hint}).")
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


# ==========================================================================
# Credit Note — dipakai AR maupun AP
# ==========================================================================
class CreditNoteTab(QWidget):
    def __init__(self, config: InvoiceWorkspaceConfig):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(f"<b>Buat Credit Note untuk Invoice {self.config.party_label}</b>"))

        form = QFormLayout()
        self.invoice_id_edit = QLineEdit()
        self.invoice_id_edit.setPlaceholderText("UUID invoice")
        form.addRow("Invoice", self.invoice_id_edit)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Credit Note", self.date_edit)
        self.amount_edit = QLineEdit()
        form.addRow("Jumlah", self.amount_edit)
        self.reason_edit = QLineEdit()
        form.addRow("Alasan", self.reason_edit)
        self.ref_edit = QLineEdit()
        form.addRow("No. Referensi", self.ref_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Buat Credit Note")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        approve_row = QHBoxLayout()
        self.approve_id_edit = QLineEdit()
        self.approve_id_edit.setPlaceholderText("ID Credit Note untuk di-approve")
        approve_row.addWidget(self.approve_id_edit)
        approve_btn = QPushButton("✔ Approve Credit Note")
        approve_btn.setProperty("class", "success")
        approve_btn.clicked.connect(self._approve)
        approve_row.addWidget(approve_btn)
        outer.addLayout(approve_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus > 0.")
            return
        if not (self.invoice_id_edit.text().strip() and self.reason_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Invoice & alasan wajib diisi.")
            return
        payload = {
            "invoice_id": self.invoice_id_edit.text().strip(),
            "credit_note_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "amount": float(amount),
            "reason": self.reason_edit.text().strip(),
            "reference_number": self.ref_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{self.config.base_path}/credit-notes", json_body=payload)

    def _on_created(self, result: Any) -> None:
        cid = (result or {}).get("id", "") if isinstance(result, dict) else ""
        if cid:
            self.approve_id_edit.setText(str(cid))
        self.status_label.setText(f"Credit Note dibuat. ID: {cid}")

    def _approve(self) -> None:
        cid = self.approve_id_edit.text().strip()
        if not cid:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Credit Note di-approve."),
                  on_error=self._on_error, path=f"{self.config.base_path}/credit-notes/{cid}/approve")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
# Write-off — khusus AR
# ==========================================================================
class WriteOffTab(QWidget):
    def __init__(self, config: InvoiceWorkspaceConfig):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Write-off Piutang Tak Tertagih</b><br>"
            "<span style='color:#DC2626;'>Aksi permanen — hanya untuk piutang yang benar-benar sudah "
            "tidak mungkin tertagih.</span>"
        ))
        form = QFormLayout()
        self.invoice_id_edit = QLineEdit()
        self.invoice_id_edit.setPlaceholderText("UUID invoice")
        form.addRow("Invoice", self.invoice_id_edit)
        self.amount_edit = QLineEdit()
        form.addRow("Jumlah Write-off", self.amount_edit)
        self.account_code_edit = QLineEdit()
        self.account_code_edit.setPlaceholderText("mis. 6-2100 (Beban Piutang Tak Tertagih)")
        form.addRow("Kode Akun Beban", self.account_code_edit)
        self.reason_edit = QLineEdit()
        form.addRow("Alasan (min. 5 karakter)", self.reason_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("⚠ Write-off Piutang")
        submit_btn.setProperty("class", "danger")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus > 0.")
            return
        if len(self.reason_edit.text().strip()) < 5:
            QMessageBox.warning(self, "Validasi", "Alasan minimal 5 karakter.")
            return
        if not (self.invoice_id_edit.text().strip() and self.account_code_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Invoice & kode akun wajib diisi.")
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi", "Write-off piutang ini secara permanen? Aksi tidak bisa dibatalkan."
        )
        if confirm != QMessageBox.Yes:
            return
        payload = {
            "invoice_id": self.invoice_id_edit.text().strip(),
            "write_off_amount": float(amount),
            "account_code": self.account_code_edit.text().strip(),
            "reason": self.reason_edit.text().strip(),
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{self.config.base_path}/write-off", json_body=payload)

    def _on_ok(self, result: Any) -> None:
        self.status_label.setText("Piutang berhasil di-write-off.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
# Collection — khusus AR
# ==========================================================================
class CollectionTab(QWidget):
    def __init__(self, config: InvoiceWorkspaceConfig):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Kirim Reminder Penagihan</b>"))
        form = QFormLayout()
        self.invoice_ids_edit = QTextEdit()
        self.invoice_ids_edit.setPlaceholderText("UUID invoice, satu per baris")
        self.invoice_ids_edit.setFixedHeight(60)
        form.addRow("Invoice yang Ditagih", self.invoice_ids_edit)
        self.reminder_type_combo = QComboBox()
        self.reminder_type_combo.addItems(["friendly", "firm", "final_notice"])
        form.addRow("Tipe Reminder", self.reminder_type_combo)
        self.message_edit = QLineEdit()
        form.addRow("Pesan Tambahan", self.message_edit)
        self.send_email_check = QCheckBox("Kirim via Email")
        self.send_email_check.setChecked(True)
        form.addRow("", self.send_email_check)
        self.send_sms_check = QCheckBox("Kirim via SMS")
        form.addRow("", self.send_sms_check)
        outer.addLayout(form)
        send_btn = QPushButton("✉ Kirim Reminder")
        send_btn.setObjectName("primaryButton")
        send_btn.clicked.connect(self._send_reminders)
        outer.addWidget(send_btn)

        outer.addWidget(QLabel("<b>Mulai Workflow Penagihan Otomatis (Semua Invoice Overdue)</b>"))
        start_btn = QPushButton("▶ Mulai Collection Workflow")
        start_btn.clicked.connect(self._start_workflow)
        outer.addWidget(start_btn)

        outer.addWidget(QLabel("<b>Eskalasi Invoice ke Legal/Collection Agency</b>"))
        escalate_form = QFormLayout()
        self.escalate_invoice_edit = QLineEdit()
        self.escalate_invoice_edit.setPlaceholderText("UUID invoice")
        escalate_form.addRow("Invoice", self.escalate_invoice_edit)
        self.escalate_reason_edit = QLineEdit()
        escalate_form.addRow("Alasan (min. 5 karakter)", self.escalate_reason_edit)
        outer.addLayout(escalate_form)
        escalate_btn = QPushButton("⬆ Eskalasi")
        escalate_btn.setProperty("class", "danger")
        escalate_btn.clicked.connect(self._escalate)
        outer.addWidget(escalate_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _send_reminders(self) -> None:
        ids = [x.strip() for x in self.invoice_ids_edit.toPlainText().splitlines() if x.strip()]
        if not ids:
            QMessageBox.warning(self, "Validasi", "Minimal 1 invoice ID diperlukan.")
            return
        payload = {
            "invoice_ids": ids,
            "reminder_type": self.reminder_type_combo.currentText(),
            "message": self.message_edit.text().strip() or None,
            "send_email": self.send_email_check.isChecked(),
            "send_sms": self.send_sms_check.isChecked(),
        }
        run_task(api_client.post, on_success=self._on_reminder_result, on_error=self._on_error,
                  path=f"{self.config.base_path}/collection/send-reminders", json_body=payload)

    def _on_reminder_result(self, result: Any) -> None:
        sent = (result or {}).get("reminders_sent", 0)
        self.status_label.setText(f"{sent} reminder berhasil dikirim.")

    def _start_workflow(self) -> None:
        confirm = QMessageBox.question(
            self, "Konfirmasi", "Mulai proses collection otomatis untuk semua invoice overdue?"
        )
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=self._on_workflow_result, on_error=self._on_error,
                  path=f"{self.config.base_path}/collection/start")

    def _on_workflow_result(self, result: Any) -> None:
        data = result or {}
        self.status_label.setText(
            f"Workflow dimulai. {data.get('invoices_processed', 0)} invoice diproses, "
            f"{data.get('reminders_sent', 0)} reminder terkirim."
        )

    def _escalate(self) -> None:
        invoice_id = self.escalate_invoice_edit.text().strip()
        reason = self.escalate_reason_edit.text().strip()
        if not invoice_id or len(reason) < 5:
            QMessageBox.warning(self, "Validasi", "Invoice ID & alasan (min. 5 karakter) wajib diisi.")
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Invoice dieskalasi."),
                  on_error=self._on_error, path=f"{self.config.base_path}/collection/{invoice_id}/escalate",
                  params={"reason": reason})

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
# Payment Run — khusus AP
# ==========================================================================
class PaymentRunTab(QWidget):
    def __init__(self, config: InvoiceWorkspaceConfig):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Buat Batch Pembayaran (Payment Run)</b><br>"
            "<span style='color:#6B7280;'>Otomatis mengumpulkan semua invoice AP yang jatuh tempo "
            "sampai tanggal tertentu untuk dibayar sekaligus.</span>"
        ))
        form = QFormLayout()
        self.payment_date_edit = QDateEdit(QDate.currentDate())
        self.payment_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Bayar", self.payment_date_edit)
        self.due_up_to_edit = QDateEdit(QDate.currentDate().addDays(7))
        self.due_up_to_edit.setCalendarPopup(True)
        form.addRow("Invoice Jatuh Tempo s/d", self.due_up_to_edit)
        self.bank_account_edit = QLineEdit()
        self.bank_account_edit.setPlaceholderText("UUID rekening bank (opsional)")
        form.addRow("Rekening Bank", self.bank_account_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Buat Payment Run")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._create_run)
        outer.addWidget(submit_btn)

        process_row = QHBoxLayout()
        self.run_id_edit = QLineEdit()
        self.run_id_edit.setPlaceholderText("ID Payment Run untuk diproses")
        process_row.addWidget(self.run_id_edit)
        process_btn = QPushButton("⚙ Proses Payment Run")
        process_btn.setProperty("class", "success")
        process_btn.clicked.connect(self._process_run)
        process_row.addWidget(process_btn)
        outer.addLayout(process_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _create_run(self) -> None:
        payload = {
            "payment_date": self.payment_date_edit.date().toString("yyyy-MM-dd"),
            "due_date_up_to": self.due_up_to_edit.date().toString("yyyy-MM-dd"),
            "bank_account_id": self.bank_account_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{self.config.base_path}/payment-runs", json_body=payload)

    def _on_created(self, result: Any) -> None:
        data = result or {}
        rid = data.get("payment_run_id", "")
        if rid:
            self.run_id_edit.setText(str(rid))
        self.status_label.setText(
            f"Payment Run dibuat. {data.get('number_of_invoices', 0)} invoice, "
            f"total {format_money(data.get('total_amount'))}."
        )

    def _process_run(self) -> None:
        rid = self.run_id_edit.text().strip()
        if not rid:
            QMessageBox.information(self, "Info", "Isi ID Payment Run dulu.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Proses payment run ini? Pembayaran akan dieksekusi.")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Payment Run diproses."),
                  on_error=self._on_error, path=f"{self.config.base_path}/payment-runs/{rid}/process")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
# 3-Way Match — khusus AP (validasi PO vs GRN vs Invoice)
# ==========================================================================
class ThreeWayMatchTab(QWidget):
    def __init__(self, config: InvoiceWorkspaceConfig):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Validasi 3-Way Match</b><br>"
            "<span style='color:#6B7280;'>Mencocokkan Purchase Order, Goods Receipt Note (GRN), dan Invoice "
            "untuk memastikan tidak ada penyimpangan qty/harga sebelum invoice disetujui untuk dibayar.</span>"
        ))
        row = QHBoxLayout()
        self.invoice_id_edit = QLineEdit()
        self.invoice_id_edit.setPlaceholderText("UUID invoice AP")
        row.addWidget(self.invoice_id_edit)
        row.addWidget(QLabel("Toleransi (%):"))
        self.tolerance_edit = QLineEdit("5")
        self.tolerance_edit.setMaximumWidth(60)
        row.addWidget(self.tolerance_edit)
        validate_btn = QPushButton("🔍 Validasi 3-Way Match")
        validate_btn.setObjectName("primaryButton")
        validate_btn.clicked.connect(self._validate)
        row.addWidget(validate_btn)
        outer.addLayout(row)

        self.status_summary = QLabel("")
        self.status_summary.setStyleSheet("font-weight:700; font-size:14px;")
        outer.addWidget(self.status_summary)

        cards = QHBoxLayout()
        self.po_match_label = QLabel("PO Match: -")
        self.grn_match_label = QLabel("GRN Match: -")
        self.qty_match_label = QLabel("Qty Match: -")
        self.price_match_label = QLabel("Price Match: -")
        for lbl in (self.po_match_label, self.grn_match_label, self.qty_match_label, self.price_match_label):
            lbl.setStyleSheet("padding:8px; border:1px solid #E5E7EB; border-radius:6px;")
            cards.addWidget(lbl)
        outer.addLayout(cards)

        outer.addWidget(QLabel("<b>Discrepancy (jika ada):</b>"))
        self.discrepancy_table = QTableWidget(0, 3)
        self.discrepancy_table.setHorizontalHeaderLabels(["Item", "Tipe Selisih", "Detail"])
        self.discrepancy_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.discrepancy_table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _validate(self) -> None:
        invoice_id = self.invoice_id_edit.text().strip()
        if not invoice_id:
            QMessageBox.information(self, "Info", "Masukkan ID invoice AP.")
            return
        try:
            tolerance = float(self.tolerance_edit.text().strip() or "5")
        except ValueError:
            tolerance = 5.0
        run_task(api_client.get, on_success=self._on_result, on_error=self._on_error,
                  path=f"{self.config.base_path}/invoices/{invoice_id}/3way-match",
                  params={"tolerance_percent": tolerance})

    def _on_result(self, data: Any) -> None:
        data = data or {}
        status = str(data.get("match_status", "")).upper()
        color = "#059669" if status == "MATCHED" else ("#D97706" if status == "PARTIAL" else "#DC2626")
        self.status_summary.setText(f"Status: {status}")
        self.status_summary.setStyleSheet(f"font-weight:700; font-size:14px; color:{color};")

        def fmt(label: str, value: bool) -> str:
            return f"{label}: {'✅ Cocok' if value else '❌ Tidak Cocok'}"

        self.po_match_label.setText(fmt("PO Match", data.get("po_match", False)))
        self.grn_match_label.setText(fmt("GRN Match", data.get("grn_match", False)))
        self.qty_match_label.setText(fmt("Qty Match", data.get("quantity_match", False)))
        self.price_match_label.setText(fmt("Price Match", data.get("price_match", False)))

        discrepancies = data.get("discrepancies", []) or []
        self.discrepancy_table.setRowCount(len(discrepancies))
        for r, d in enumerate(discrepancies):
            if isinstance(d, dict):
                values = [d.get("item", d.get("item_name", "")), d.get("type", ""), str(d.get("detail", d))]
            else:
                values = ["-", "-", str(d)]
            for c, v in enumerate(values):
                self.discrepancy_table.setItem(r, c, QTableWidgetItem(v))
        self.discrepancy_table.resizeColumnsToContents()
        self.status_label.setText(f"{len(discrepancies)} discrepancy ditemukan." if discrepancies else "Tidak ada discrepancy.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class InvoiceDetailDialog(QDialog):
    """Menampilkan header + baris invoice yang sudah ada (read-only)."""

    def __init__(self, config: InvoiceWorkspaceConfig, data: dict[str, Any], parent=None):
        super().__init__(parent)
        self.config = config
        self.data = data
        inv_number = data.get(config.invoice_number_field, data.get("invoice_number", ""))
        self.setWindowTitle(f"Detail Invoice — {inv_number}")
        self.resize(700, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        data = self.data

        party_name = data.get("customer_name") or data.get("vendor_name") or data.get("supplier_name") or "-"
        header = QLabel(
            f"<b>No. Invoice:</b> {data.get(self.config.invoice_number_field, data.get('invoice_number', ''))}"
            f" &nbsp;|&nbsp; <b>Status:</b> "
            f"<span style='color:{status_color(str(data.get('status')))}'>{data.get('status')}</span><br>"
            f"<b>{self.config.party_label}:</b> {party_name}<br>"
            f"<b>Tanggal Invoice:</b> {format_date(data.get('invoice_date'))} &nbsp;|&nbsp; "
            f"<b>Jatuh Tempo:</b> {format_date(data.get('due_date'))}<br>"
            f"<b>Deskripsi:</b> {data.get('description', '-')}<br>"
            f"<b>No. Referensi:</b> {data.get('reference_number') or '-'}"
        )
        header.setWordWrap(True)
        outer.addWidget(header)

        outer.addWidget(QLabel("<b>Baris Invoice:</b>"))
        lines = data.get("lines", []) or []
        table = QTableWidget(len(lines), 6)
        table.setHorizontalHeaderLabels(["Deskripsi", "Qty", "Harga Satuan", "Diskon%", "Pajak%", "Subtotal"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for r, line in enumerate(lines):
            values = [
                line.get("description", ""),
                str(line.get("quantity", "")),
                format_money(line.get("unit_price")),
                str(line.get("discount_percent", 0)),
                str(line.get("tax_rate", 0)),
                format_money(line.get("subtotal", line.get("line_total"))),
            ]
            for c, v in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(v))
        table.resizeColumnsToContents()
        outer.addWidget(table, stretch=1)

        summary = QLabel(
            f"<b>Subtotal:</b> {format_money(data.get('subtotal'))} &nbsp;|&nbsp; "
            f"<b>Pajak:</b> {format_money(data.get('tax_amount'))} &nbsp;|&nbsp; "
            f"<b>Total:</b> {format_money(data.get('total_amount'))}<br>"
            f"<b>Terbayar:</b> {format_money(data.get('paid_amount'))} &nbsp;|&nbsp; "
            f"<b>Sisa:</b> {format_money(data.get('outstanding_amount'))}"
        )
        outer.addWidget(summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)
