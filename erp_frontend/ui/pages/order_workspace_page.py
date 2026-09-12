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
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money, status_color
from core.workers import run_task
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
            # Endpoint master data supplier -- lihat registry/module_registry.py
            # key="suppliers" (base_path="/suppliers", list_path="/suppliers").
            self.party_api_path = "/suppliers/suppliers"
            self.party_code_field = "supplier_code"
            self.party_name_field = "name"
            self.item_price_field = "standard_cost"
            self.item_tax_field = "tax_rate_purchase"
        else:
            self.list_path = "/sales-orders"
            self.number_field = "so_number"
            self.date_field = "so_date"
            self.party_field = "customer_id"
            self.party_label = "Customer"
            # Endpoint master data customer -- lihat registry/module_registry.py
            # key="customers" (base_path="/customers", list_path="/customers").
            self.party_api_path = "/customers/customers"
            self.party_code_field = "customer_code"
            self.party_name_field = "customer_name"
            self.item_price_field = "selling_price"
            self.item_tax_field = "tax_rate_sales"


# Endpoint master data Barang/Item -- lihat registry/module_registry.py
# key="inventory_items" (base_path="/inventory/inventory", list_path="/items").
ITEM_API_PATH = "/inventory/inventory/items"


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

    def _selected_record(self) -> dict[str, Any] | None:
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
# Kolom tabel baris item -- lengkap sesuai permintaan: No. Bon, Nama
# {Supplier/Customer}, Nama Bahan, Keterangan, Qty (kg), Harga, Disc%,
# Pajak%, Total.
#
# CATATAN: backend (POLineSchema/SOLineSchema di
# fastapi_purchase_sales_router.py) hanya punya field item_id, quantity,
# unit_price, discount_percent, tax_rate, expected_delivery_date, dan
# description per baris -- TIDAK ADA field "no_bon" atau "supplier"
# tersendiri per baris (supplier/customer memang satu untuk seluruh
# order, disimpan di header). Supaya "No. Bon" tidak hilang begitu saja,
# nilainya digabung ke dalam field `description` saat disimpan (lihat
# _line_payload()). Kolom "Nama Supplier/Customer" & "Total" murni
# tampilan (auto-sync dari header / hasil hitung), tidak dikirim ke API.
COL_BON, COL_PARTY, COL_ITEM, COL_DESC, COL_QTY, COL_PRICE, COL_DISC, COL_TAX, COL_TOTAL = range(9)


class OrderFormDialog(QDialog):
    def __init__(self, config: OrderWorkspaceConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._parties: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []
        self._items_loaded = False
        self._suspend_recalc = False
        self.setWindowTitle(f"{config.label} Baru")
        # Tambahkan tombol minimize & maximize di title bar (bawaan Qt
        # untuk QDialog cuma tombol close), plus dialog dibuat resizable
        # (bukan fixed size) supaya tombol maximize itu benar-benar
        # berguna.
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        )
        self.setSizeGripEnabled(True)
        self.resize(960, 640)
        self._build_ui()
        self._load_parties()
        self._load_items()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        maximize_btn = QPushButton("⛶ Tampilkan Penuh")
        maximize_btn.setToolTip("Maximize / kembalikan ukuran jendela")
        maximize_btn.clicked.connect(self._toggle_maximize)
        top_bar.addWidget(maximize_btn)
        outer.addLayout(top_bar)

        form = QFormLayout()

        self.number_edit = QLineEdit()
        form.addRow(f"No. {self.config.label}", self.number_edit)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal", self.date_edit)

        # Dropdown Supplier/Customer (sebelumnya kotak isian UUID manual) --
        # diisi dari data master lewat _load_parties(), tampilkan
        # "Kode — Nama" dan simpan UUID-nya sebagai data item combo.
        self.party_combo = QComboBox()
        self.party_combo.setEnabled(False)
        self.party_combo.addItem(f"Memuat daftar {self.config.party_label.lower()}...", None)
        self.party_combo.currentIndexChanged.connect(self._sync_party_column)
        form.addRow(self.config.party_label, self.party_combo)

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

        line_headers = [
            "No. Bon",
            f"Nama {self.config.party_label}",
            "Nama Bahan",
            "Keterangan",
            "Qty (kg)",
            "Harga Satuan",
            "Diskon %",
            "Pajak %",
            "Total",
        ]
        self.line_table = QTableWidget(0, len(line_headers))
        self.line_table.setHorizontalHeaderLabels(line_headers)
        self.line_table.horizontalHeader().setStretchLastSection(True)
        self.line_table.itemChanged.connect(self._on_line_item_changed)
        outer.addWidget(self.line_table, stretch=1)

        line_btns = QHBoxLayout()
        add_btn = QPushButton("+ Baris")
        add_btn.clicked.connect(self._add_line)
        remove_btn = QPushButton("- Hapus Baris")
        remove_btn.clicked.connect(self._remove_line)
        line_btns.addWidget(add_btn)
        line_btns.addWidget(remove_btn)
        line_btns.addStretch()
        self.line_total_label = QLabel("Total keseluruhan: Rp 0")
        self.line_total_label.setStyleSheet("font-weight:600;")
        line_btns.addWidget(self.line_total_label)
        outer.addLayout(line_btns)
        self._add_line()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Cancel).setText("Batal")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ------------------------------------------------------------------
    # Muat data master Supplier/Customer & Barang dari API, untuk dropdown.
    def _load_parties(self) -> None:
        run_task(
            api_client.get,
            on_success=self._on_parties_loaded,
            on_error=self._on_parties_error,
            path=self.config.party_api_path,
            params={"page_size": 1000},
        )

    def _on_parties_loaded(self, payload: Any) -> None:
        self._parties = extract_list(payload)
        self.party_combo.blockSignals(True)
        self.party_combo.clear()
        self.party_combo.addItem(f"— Pilih {self.config.party_label} —", None)
        for rec in sorted(self._parties, key=lambda r: str(r.get(self.config.party_name_field, ""))):
            code = rec.get(self.config.party_code_field, "")
            name = rec.get(self.config.party_name_field, "")
            display = f"{code} — {name}" if code else name
            self.party_combo.addItem(display, rec.get("id"))
        self.party_combo.blockSignals(False)
        self.party_combo.setEnabled(True)
        # blockSignals di atas mencegah currentIndexChanged terpicu, jadi
        # kolom "Nama Supplier/Customer" di baris yang sudah ada (mis.
        # baris pertama yang dibuat sebelum data ini selesai dimuat)
        # perlu disinkronkan manual sekali di sini.
        self._sync_party_column()
        if not self._parties:
            QMessageBox.warning(
                self, "Perhatian",
                f"Data {self.config.party_label} masih kosong. Tambahkan dulu di menu Master Data.",
            )
    def _on_parties_error(self, message: str) -> None:
        self.party_combo.clear()
        self.party_combo.addItem(f"Gagal memuat {self.config.party_label.lower()} (lihat pesan error)", None)
        QMessageBox.warning(
            self, "Gagal Memuat",
            f"Tidak bisa memuat daftar {self.config.party_label}: {message}\n\n"
            "Tutup dan buka lagi form ini untuk mencoba ulang.",
        )

    # Endpoint /inventory/inventory/items membatasi page_size maksimum 200
    # (lihat fastapi_inventory_router.py: `Query(20, ge=1, le=200)`).
    # Sebelumnya kode ini minta page_size=2000 sekaligus -> selalu ditolak
    # backend dengan 422 Unprocessable Entity, jadi dropdown "Nama Bahan"
    # tidak pernah berisi apa-apa. Diperbaiki jadi ambil per halaman 200
    # item, lanjut ke halaman berikutnya sampai habis, supaya katalog
    # barang yang lebih dari 200 item tetap muncul lengkap di dropdown.
    ITEM_PAGE_SIZE = 200

    def _load_items(self) -> None:
        self._items = []
        self._load_items_page(1)

    def _load_items_page(self, page: int) -> None:
        run_task(
            api_client.get,
            on_success=lambda payload, p=page: self._on_items_page_loaded(payload, p),
            on_error=self._on_items_error,
            path=ITEM_API_PATH,
            params={"page": page, "page_size": self.ITEM_PAGE_SIZE, "include_inactive": False},
        )

    def _on_items_page_loaded(self, payload: Any, page: int) -> None:
        batch = extract_list(payload)
        self._items.extend(batch)
        if len(batch) == self.ITEM_PAGE_SIZE:
            # Halaman penuh -> kemungkinan masih ada data di halaman
            # berikutnya, lanjut ambil.
            self._load_items_page(page + 1)
            return
        # Halaman terakhir (kurang dari page_size, atau kosong) -> selesai.
        self._items.sort(key=lambda r: str(r.get("item_name", "")))
        self._items_loaded = True
        # Isi ulang dropdown Nama Bahan di semua baris yang sudah kadung
        # dibuat sebelum data barang ini selesai dimuat (mis. baris
        # pertama yang otomatis ditambahkan saat dialog dibuka).
        for row in range(self.line_table.rowCount()):
            combo = self.line_table.cellWidget(row, COL_ITEM)
            if combo is not None:
                self._populate_item_combo(combo)

    def _on_items_error(self, message: str) -> None:
        QMessageBox.warning(
            self, "Gagal Memuat",
            f"Tidak bisa memuat daftar Barang/Item: {message}\n\n"
            "Tutup dan buka lagi form ini untuk mencoba ulang.",
        )

    # ------------------------------------------------------------------
    def _populate_item_combo(self, combo: QComboBox) -> None:
        combo.blockSignals(True)
        current_id = combo.currentData()
        combo.clear()
        if not self._items_loaded:
            combo.addItem("Memuat daftar barang...", None)
            combo.blockSignals(False)
            return
        combo.addItem("— Pilih Bahan —", None)
        restore_index = 0
        for rec in self._items:
            code = rec.get("item_code", "")
            name = rec.get("item_name", "")
            uom = rec.get("unit_of_measure", "")
            label = f"{code} — {name}" + (f" ({uom})" if uom else "")
            combo.addItem(label, rec)
            if current_id is not None and rec.get("id") == current_id:
                restore_index = combo.count() - 1
        combo.setCurrentIndex(restore_index)
        combo.blockSignals(False)

    def _sync_party_column(self) -> None:
        """Update kolom 'Nama Supplier/Customer' di semua baris begitu
        pilihan di header berubah -- kolom ini murni tampilan (auto-sync),
        supaya setiap baris jelas terlihat untuk supplier/customer mana."""
        name = self.party_combo.currentText()
        if name.startswith("—") or name.startswith("Memuat") or name.startswith("Gagal"):
            name = ""
        self._suspend_recalc = True
        for row in range(self.line_table.rowCount()):
            item = self.line_table.item(row, COL_PARTY)
            if item is not None:
                item.setText(name)
        self._suspend_recalc = False

    # ------------------------------------------------------------------
    def _add_line(self) -> None:
        row = self.line_table.rowCount()
        self.line_table.insertRow(row)

        self._suspend_recalc = True

        bon_item = QTableWidgetItem("")
        self.line_table.setItem(row, COL_BON, bon_item)

        party_name = self.party_combo.currentText()
        if party_name.startswith("—") or party_name.startswith("Memuat") or party_name.startswith("Gagal"):
            party_name = ""
        party_item = QTableWidgetItem(party_name)
        party_item.setFlags(party_item.flags() & ~Qt.ItemIsEditable)
        self.line_table.setItem(row, COL_PARTY, party_item)

        item_combo = QComboBox()
        self._populate_item_combo(item_combo)
        item_combo.currentIndexChanged.connect(lambda _idx, c=item_combo: self._on_item_selected(c))
        self.line_table.setCellWidget(row, COL_ITEM, item_combo)

        self.line_table.setItem(row, COL_DESC, QTableWidgetItem(""))
        self.line_table.setItem(row, COL_QTY, QTableWidgetItem("1"))
        self.line_table.setItem(row, COL_PRICE, QTableWidgetItem("0"))
        self.line_table.setItem(row, COL_DISC, QTableWidgetItem("0"))
        self.line_table.setItem(row, COL_TAX, QTableWidgetItem("11"))

        total_item = QTableWidgetItem("0")
        total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        self.line_table.setItem(row, COL_TOTAL, total_item)

        self._suspend_recalc = False
        self._recalc_row(row)

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)
            self._recalc_grand_total()

    def _row_of_combo(self, combo: QComboBox) -> int:
        for row in range(self.line_table.rowCount()):
            if self.line_table.cellWidget(row, COL_ITEM) is combo:
                return row
        return -1

    def _on_item_selected(self, combo: QComboBox) -> None:
        row = self._row_of_combo(combo)
        if row < 0:
            return
        rec = combo.currentData()
        if not isinstance(rec, dict):
            return
        # Isi otomatis Harga Satuan & Pajak dari data barang, TAPI cuma
        # kalau selnya masih nilai default (belum diubah manual oleh
        # user) supaya tidak menimpa harga yang sudah diketik sendiri.
        price_item = self.line_table.item(row, COL_PRICE)
        if price_item is not None and price_item.text().strip() in ("", "0"):
            price = rec.get(self.config.item_price_field)
            if price:
                price_item.setText(str(price))
        tax_item = self.line_table.item(row, COL_TAX)
        if tax_item is not None and tax_item.text().strip() in ("", "0", "11"):
            tax = rec.get(self.config.item_tax_field)
            if tax is not None:
                tax_item.setText(str(tax))
        self._recalc_row(row)

    # ------------------------------------------------------------------
    def _on_line_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suspend_recalc:
            return
        if item.column() in (COL_QTY, COL_PRICE, COL_DISC, COL_TAX):
            self._recalc_row(item.row())

    def _recalc_row(self, row: int) -> None:
        qty = _to_decimal(self._cell(row, COL_QTY))
        price = _to_decimal(self._cell(row, COL_PRICE))
        discount = _to_decimal(self._cell(row, COL_DISC))
        tax = _to_decimal(self._cell(row, COL_TAX))
        net = qty * price * (1 - discount / 100)
        total = net + (net * tax / 100)
        self._suspend_recalc = True
        total_item = self.line_table.item(row, COL_TOTAL)
        if total_item is not None:
            total_item.setText(f"{total.quantize(Decimal('0.01'))}")
        self._suspend_recalc = False
        self._recalc_grand_total()

    def _recalc_grand_total(self) -> None:
        grand_total = sum(
            (_to_decimal(self._cell(row, COL_TOTAL)) for row in range(self.line_table.rowCount())),
            Decimal("0"),
        )
        self.line_total_label.setText(f"Total keseluruhan: {format_money(grand_total)}")

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _item_record(self, row: int) -> dict[str, Any] | None:
        combo = self.line_table.cellWidget(row, COL_ITEM)
        if combo is None:
            return None
        rec = combo.currentData()
        return rec if isinstance(rec, dict) else None

    def _filled_rows(self) -> list[int]:
        return [r for r in range(self.line_table.rowCount()) if self._item_record(r) is not None]

    # ------------------------------------------------------------------
    def _on_save(self) -> None:
        if not self.number_edit.text().strip():
            QMessageBox.warning(self, "Validasi", f"No. {self.config.label} wajib diisi.")
            return
        if self.party_combo.currentData() is None:
            QMessageBox.warning(self, "Validasi", f"{self.config.party_label} wajib dipilih.")
            return
        filled_rows = self._filled_rows()
        if not filled_rows:
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris item (Nama Bahan wajib dipilih) diperlukan.")
            return
        for row in filled_rows:
            qty = _to_decimal(self._cell(row, COL_QTY))
            price = _to_decimal(self._cell(row, COL_PRICE))
            discount = _to_decimal(self._cell(row, COL_DISC))
            tax = _to_decimal(self._cell(row, COL_TAX))
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

    def _line_description(self, row: int) -> str | None:
        """Gabungkan 'No. Bon' + 'Keterangan' jadi satu field `description`
        (backend belum punya kolom No. Bon tersendiri per baris)."""
        bon = self._cell(row, COL_BON).strip()
        keterangan = self._cell(row, COL_DESC).strip()
        if bon and keterangan:
            return f"[Bon {bon}] {keterangan}"
        if bon:
            return f"[Bon {bon}]"
        if keterangan:
            return keterangan
        return None

    def build_payload(self) -> dict[str, Any]:
        lines = []
        for row in self._filled_rows():
            rec = self._item_record(row)
            lines.append({
                "item_id": rec.get("id"),
                "quantity": float(_to_decimal(self._cell(row, COL_QTY))),
                "unit_price": float(_to_decimal(self._cell(row, COL_PRICE))),
                "discount_percent": float(_to_decimal(self._cell(row, COL_DISC))),
                "tax_rate": float(_to_decimal(self._cell(row, COL_TAX))),
                "description": self._line_description(row),
            })
        payload = {
            self.config.number_field: self.number_edit.text().strip(),
            self.config.date_field: self.date_edit.date().toString("yyyy-MM-dd"),
            self.config.party_field: self.party_combo.currentData(),
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
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        )
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
