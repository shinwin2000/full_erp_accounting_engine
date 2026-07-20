"""
ui/pages/order_workspace_page.py
===================================
Purchase Order & Sales Order — SEBELUMNYA terdaftar sebagai modul generic
CRUD, padahal `PurchaseOrderCreateSchema`/`SalesOrderCreateSchema` backend
mewajibkan `lines` (baris item, minimal 1) yang TIDAK BISA direpresentasikan
oleh form generik berbasis field datar. Akibatnya PO/SO tidak akan pernah
bisa dibuat lewat form generik lama — diganti halaman khusus dengan tabel
baris item, mengikuti pola yang sama dengan invoice_workspace.py (AR/AP).

Endpoint backend:
  GET/POST /purchase-sales/purchase-sales/purchase-orders
  GET/POST /purchase-sales/purchase-sales/sales-orders
  POST     .../{id}/submit|approve|reject|post|reverse (workflow standar)
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
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money, status_color
from core.workers import run_task

ORDER_TYPES = ("standard", "rush", "backorder", "consignment", "dropship")
INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")
STATUS_FILTERS = ["Semua", "draft", "submitted", "approved", "posted", "closed", "cancelled", "rejected"]


class OrderWorkspaceConfig:
    def __init__(self, base_path: str, label: str, icon: str, order_kind: str):
        self.base_path = base_path
        self.label = label
        self.icon = icon
        self.order_kind = order_kind  # "purchase" | "sales"
        if order_kind == "purchase":
            self.list_path = "/purchase-orders"
            self.number_field = "po_number"
            self.date_field = "po_date"
            self.party_field = "supplier_id"
            self.party_label = "Supplier"
        else:
            self.list_path = "/sales-orders"
            self.number_field = "so_number"
            self.date_field = "so_date"
            self.party_field = "customer_id"
            self.party_label = "Customer"


PO_CONFIG = OrderWorkspaceConfig("/purchase-sales/purchase-sales", "Purchase Order", "🛒", "purchase")
SO_CONFIG = OrderWorkspaceConfig("/purchase-sales/purchase-sales", "Sales Order", "🧾", "sales")


class OrderWorkspacePage(QWidget):
    def __init__(self, config: OrderWorkspaceConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.page = 1
        self._records: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel(f"{self.config.icon}  {self.config.label}")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        outer.addLayout(header)

        toolbar = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(STATUS_FILTERS)
        self.status_filter.currentTextChanged.connect(lambda _t: self._reset_and_refresh())
        toolbar.addWidget(self.status_filter)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(f"Cari no. {self.config.label}...")
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
        for name, label in [("submit", "Submit"), ("approve", "Approve"), ("reject", "Reject"),
                             ("post", "Post"), ("reverse", "Reverse")]:
            act = menu.addAction(label)
            act.triggered.connect(lambda checked=False, n=name: self._run_workflow(n))
        self.action_btn.setMenu(menu)
        toolbar.addWidget(self.action_btn)

        new_btn = QPushButton(f"+ {self.config.label} Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_order)
        toolbar.addWidget(new_btn)
        outer.addLayout(toolbar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["No. Order", "Tanggal", self.config.party_label, "Tipe", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda *_: self._view_detail())
        outer.addWidget(self.table, stretch=1)

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
        outer.addLayout(pager_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

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
        self.status_label.setText("Memuat data...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{self.config.base_path}{self.config.list_path}", params=params)

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            party_name = rec.get("supplier_name") or rec.get("customer_name") or "-"
            status = str(rec.get("status", ""))
            values = [
                rec.get(self.config.number_field, ""),
                format_date(rec.get(self.config.date_field)),
                party_name,
                str(rec.get("order_type", "")),
                status,
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col == 4:
                    item.setForeground(QColor(status_color(val)))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        start = (self.page - 1) * self.PAGE_SIZE + 1 if self._records else 0
        end = start + len(self._records) - 1 if self._records else 0
        self.pager_label.setText(f"Menampilkan {start}-{end}")
        self.prev_btn.setEnabled(self.page > 1)
        self.next_btn.setEnabled(len(self._records) == self.PAGE_SIZE)
        self.status_label.setText(f"{len(self._records)} order dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _prev_page(self) -> None:
        if self.page > 1:
            self.page -= 1
            self.refresh()

    def _next_page(self) -> None:
        self.page += 1
        self.refresh()

    def _selected_record(self) -> Optional[dict[str, Any]]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    # ------------------------------------------------------------------
    def _new_order(self) -> None:
        dlg = OrderFormDialog(self.config, parent=self)
        if dlg.exec():
            run_task(api_client.post, on_success=lambda _r: self._after_write(f"{self.config.label} berhasil dibuat."),
                      on_error=self._on_write_error,
                      path=f"{self.config.base_path}{self.config.list_path}", json_body=dlg.build_payload())

    def _view_detail(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih order terlebih dahulu.")
            return
        order_id = record.get("id")
        run_task(api_client.get, on_success=self._show_detail, on_error=self._on_error,
                  path=f"{self.config.base_path}{self.config.list_path}/{order_id}")

    def _show_detail(self, data: dict[str, Any]) -> None:
        dlg = OrderDetailDialog(self.config, data, parent=self)
        dlg.exec()

    def _run_workflow(self, action_name: str) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih order terlebih dahulu.")
            return
        order_id = record.get("id")
        body: dict[str, Any] = {}
        if action_name in ("reject", "reverse"):
            from PySide6.QtWidgets import QInputDialog
            reason, ok = QInputDialog.getMultiLineText(self, f"Alasan {action_name.title()}", "Alasan:")
            if not ok or len(reason.strip()) < 5:
                return
            body = {"reason": reason.strip()}
        else:
            confirm = QMessageBox.question(self, "Konfirmasi", f"Jalankan aksi '{action_name}'?")
            if confirm != QMessageBox.Yes:
                return
        run_task(api_client.post, on_success=lambda _r: self._after_write(f"Aksi '{action_name}' berhasil."),
                  on_error=self._on_write_error,
                  path=f"{self.config.base_path}{self.config.list_path}/{order_id}/{action_name}", json_body=body)

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
LINE_COLS = ["Item ID (UUID)", "Qty", "Harga Satuan", "Diskon %", "Pajak %"]


class OrderFormDialog(QDialog):
    def __init__(self, config: OrderWorkspaceConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(f"{config.label} Baru")
        self.resize(720, 560)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        form = QFormLayout()

        self.number_edit = QLineEdit()
        form.addRow(f"No. {self.config.label}", self.number_edit)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal", self.date_edit)

        self.party_edit = QLineEdit()
        self.party_edit.setPlaceholderText(f"UUID {self.config.party_label}")
        form.addRow(self.config.party_label, self.party_edit)

        self.expected_date_edit = QDateEdit(QDate.currentDate().addDays(14))
        self.expected_date_edit.setCalendarPopup(True)
        label = "Estimasi Kirim" if self.config.order_kind == "purchase" else "Estimasi Kirim ke Customer"
        form.addRow(label, self.expected_date_edit)

        self.term_days_edit = QSpinBox()
        self.term_days_edit.setRange(0, 365)
        self.term_days_edit.setValue(30 if self.config.order_kind == "purchase" else 7)
        form.addRow("Term Pengiriman (hari)", self.term_days_edit)

        self.payment_term_edit = QSpinBox()
        self.payment_term_edit.setRange(0, 365)
        self.payment_term_edit.setValue(30)
        form.addRow("Term Pembayaran (hari)", self.payment_term_edit)

        self.incoterm_combo = QComboBox()
        self.incoterm_combo.addItems(INCOTERMS)
        form.addRow("Incoterm", self.incoterm_combo)

        self.order_type_combo = QComboBox()
        self.order_type_combo.addItems(ORDER_TYPES)
        form.addRow("Tipe Order", self.order_type_combo)

        self.ref_edit = QLineEdit()
        form.addRow("No. Referensi", self.ref_edit)

        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)

        outer.addLayout(form)
        outer.addWidget(QLabel("Baris Item (qty & harga harus > 0):"))

        self.line_table = QTableWidget(0, len(LINE_COLS))
        self.line_table.setHorizontalHeaderLabels(LINE_COLS)
        self.line_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.line_table, stretch=1)

        line_btns = QHBoxLayout()
        add_btn = QPushButton("+ Baris")
        add_btn.clicked.connect(self._add_line)
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
        defaults = ["", "1", "0", "0", "11"]
        for col, val in enumerate(defaults):
            self.line_table.setItem(row, col, QTableWidgetItem(val))

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _on_save(self) -> None:
        if not self.number_edit.text().strip():
            QMessageBox.warning(self, "Validasi", f"No. {self.config.label} wajib diisi.")
            return
        if not self.party_edit.text().strip():
            QMessageBox.warning(self, "Validasi", f"{self.config.party_label} wajib diisi.")
            return
        filled_rows = [r for r in range(self.line_table.rowCount()) if self._cell(r, 0).strip()]
        if not filled_rows:
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris item diperlukan.")
            return
        for row in filled_rows:
            qty = _to_decimal(self._cell(row, 1))
            price = _to_decimal(self._cell(row, 2))
            discount = _to_decimal(self._cell(row, 3))
            tax = _to_decimal(self._cell(row, 4))
            if qty <= 0:
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Qty harus > 0.")
                return
            if price <= 0:
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Harga satuan harus > 0.")
                return
            if not (0 <= discount <= 100) or not (0 <= tax <= 100):
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Diskon/pajak harus 0-100%.")
                return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        lines = []
        for row in range(self.line_table.rowCount()):
            item_id = self._cell(row, 0).strip()
            if not item_id:
                continue
            lines.append({
                "item_id": item_id,
                "quantity": float(_to_decimal(self._cell(row, 1))),
                "unit_price": float(_to_decimal(self._cell(row, 2))),
                "discount_percent": float(_to_decimal(self._cell(row, 3))),
                "tax_rate": float(_to_decimal(self._cell(row, 4))),
            })
        payload = {
            self.config.number_field: self.number_edit.text().strip(),
            self.config.date_field: self.date_edit.date().toString("yyyy-MM-dd"),
            self.config.party_field: self.party_edit.text().strip(),
            "lines": lines,
            "payment_term_days": self.payment_term_edit.value(),
            "incoterm": self.incoterm_combo.currentText(),
            "order_type": self.order_type_combo.currentText(),
            "reference_number": self.ref_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
        }
        if self.config.order_kind == "purchase":
            payload["expected_delivery_date"] = self.expected_date_edit.date().toString("yyyy-MM-dd")
            payload["delivery_term_days"] = self.term_days_edit.value()
        else:
            payload["expected_ship_date"] = self.expected_date_edit.date().toString("yyyy-MM-dd")
            payload["shipping_term_days"] = self.term_days_edit.value()
        return payload


class OrderDetailDialog(QDialog):
    def __init__(self, config: OrderWorkspaceConfig, data: dict[str, Any], parent=None):
        super().__init__(parent)
        self.config = config
        self.data = data
        self.setWindowTitle(f"Detail {config.label} — {data.get(config.number_field, '')}")
        self.resize(680, 500)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        data = self.data
        party_name = data.get("supplier_name") or data.get("customer_name") or "-"
        header = QLabel(
            f"<b>No. {self.config.label}:</b> {data.get(self.config.number_field, '')} &nbsp;|&nbsp; "
            f"<b>Status:</b> <span style='color:{status_color(str(data.get('status')))}'>{data.get('status')}</span><br>"
            f"<b>{self.config.party_label}:</b> {party_name} &nbsp;|&nbsp; "
            f"<b>Tanggal:</b> {format_date(data.get(self.config.date_field))}<br>"
            f"<b>Incoterm:</b> {data.get('incoterm', '-')} &nbsp;|&nbsp; <b>Tipe:</b> {data.get('order_type', '-')}<br>"
            f"<b>Catatan:</b> {data.get('notes') or '-'}"
        )
        header.setWordWrap(True)
        outer.addWidget(header)

        outer.addWidget(QLabel("<b>Baris Item:</b>"))
        lines = data.get("lines", []) or []
        table = QTableWidget(len(lines), 5)
        table.setHorizontalHeaderLabels(["Item", "Qty", "Harga Satuan", "Diskon%", "Subtotal"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r, line in enumerate(lines):
            values = [
                line.get("item_name", line.get("item_id", "")),
                str(line.get("quantity", "")),
                format_money(line.get("unit_price")),
                str(line.get("discount_percent", 0)),
                format_money(line.get("subtotal", line.get("line_total"))),
            ]
            for c, v in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(str(v)))
        table.resizeColumnsToContents()
        outer.addWidget(table, stretch=1)

        summary = QLabel(f"<b>Total:</b> {format_money(data.get('total_amount'))}")
        outer.addWidget(summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)


def _to_decimal(text: str) -> Decimal:
    text = (text or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")
