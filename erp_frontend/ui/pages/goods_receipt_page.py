"""
ui/pages/goods_receipt_page.py
=================================
Melengkapi gap KRITIS di modul Purchase/Sales: siklus PO -> terima barang
(Goods Receipt) dan siklus SO -> kirim barang (Delivery Order) sebelumnya
tidak ada UI sama sekali, padahal itu bagian tengah dari alur pembelian &
penjualan (tanpa ini PO/SO cuma dokumen kertas yang tidak pernah "closed"
secara fisik).

Endpoint backend (base: /purchase-sales/purchase-sales):
  POST /goods-receipt                    - catat penerimaan barang dari PO
  POST /goods-receipt/{id}/confirm       - konfirmasi & update stok
  POST /delivery-orders                  - catat pengiriman barang dari SO
  POST /delivery-orders/{id}/confirm     - konfirmasi pengiriman
  POST /delivery-orders/{id}/ship        - tandai barang sudah dikirim (dengan tracking)
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.workers import run_task
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
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

BASE = "/purchase-sales/purchase-sales"


class GoodsReceiptPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("📥  Goods Receipt & Delivery Order")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(GoodsReceiptTab(), "Goods Receipt (Terima Barang)")
        self.tabs.addTab(DeliveryOrderTab(), "Delivery Order (Kirim Barang)")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
GRN_LINE_COLS = ["PO Line ID (UUID)", "Item ID (UUID)", "Qty Ditolak", "Alasan Tolak", "No. Batch", "Tgl Kadaluarsa"]


class GoodsReceiptTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Catat penerimaan barang fisik terhadap Purchase Order. Stok akan bertambah "
            "otomatis setelah GRN di-confirm."
        ))

        form = QFormLayout()
        self.grn_number_edit = QLineEdit()
        form.addRow("No. GRN", self.grn_number_edit)
        self.grn_date_edit = QDateEdit(QDate.currentDate())
        self.grn_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal GRN", self.grn_date_edit)
        self.po_id_edit = QLineEdit()
        self.po_id_edit.setPlaceholderText("UUID Purchase Order")
        form.addRow("Purchase Order", self.po_id_edit)
        self.warehouse_edit = QLineEdit()
        self.warehouse_edit.setPlaceholderText("UUID gudang penerima")
        form.addRow("Gudang", self.warehouse_edit)
        outer.addLayout(form)

        outer.addWidget(QLabel("Baris penerimaan (isi hanya jika ada barang ditolak/reject; qty diterima "
                                 "otomatis mengikuti PO line):"))
        self.line_table = QTableWidget(0, len(GRN_LINE_COLS))
        self.line_table.setHorizontalHeaderLabels(GRN_LINE_COLS)
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

        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(50)
        self.notes_edit.setPlaceholderText("Catatan (opsional)")
        outer.addWidget(self.notes_edit)

        submit_row = QHBoxLayout()
        submit_btn = QPushButton("+ Simpan Goods Receipt")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        submit_row.addWidget(submit_btn)
        submit_row.addStretch()
        submit_row.addWidget(QLabel("Konfirmasi GRN (ID):"))
        self.confirm_id_edit = QLineEdit()
        self.confirm_id_edit.setMaximumWidth(260)
        submit_row.addWidget(self.confirm_id_edit)
        confirm_btn = QPushButton("✔ Confirm & Update Stok")
        confirm_btn.setProperty("class", "success")
        confirm_btn.clicked.connect(self._confirm)
        submit_row.addWidget(confirm_btn)
        outer.addLayout(submit_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _add_line(self) -> None:
        row = self.line_table.rowCount()
        self.line_table.insertRow(row)
        for col in range(len(GRN_LINE_COLS)):
            self.line_table.setItem(row, col, QTableWidgetItem(""))

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _submit(self) -> None:
        if not (self.grn_number_edit.text().strip() and self.po_id_edit.text().strip()
                and self.warehouse_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "No. GRN, Purchase Order, dan Gudang wajib diisi.")
            return
        lines = []
        for row in range(self.line_table.rowCount()):
            po_line_id = self._cell(row, 0).strip()
            item_id = self._cell(row, 1).strip()
            if not po_line_id or not item_id:
                continue
            try:
                qty_rejected = Decimal(self._cell(row, 2) or "0")
            except InvalidOperation:
                QMessageBox.warning(self, "Validasi", f"Qty ditolak baris {row + 1} bukan angka.")
                return
            lines.append({
                "purchase_order_line_id": po_line_id,
                "item_id": item_id,
                "quantity_rejected": float(qty_rejected),
                "rejection_reason": self._cell(row, 3).strip() or None,
                "batch_number": self._cell(row, 4).strip() or None,
                "expiry_date": self._cell(row, 5).strip() or None,
            })
        if not lines:
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris item diperlukan (isi PO Line ID & Item ID).")
            return
        payload = {
            "grn_number": self.grn_number_edit.text().strip(),
            "grn_date": self.grn_date_edit.date().toString("yyyy-MM-dd"),
            "purchase_order_id": self.po_id_edit.text().strip(),
            "warehouse_id": self.warehouse_edit.text().strip(),
            "lines": lines,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/goods-receipt", json_body=payload)

    def _on_created(self, result: Any) -> None:
        gid = (result or {}).get("id", "") if isinstance(result, dict) else ""
        if gid:
            self.confirm_id_edit.setText(str(gid))
        self.status_label.setText(f"Goods Receipt disimpan. ID: {gid}")

    def _confirm(self) -> None:
        gid = self.confirm_id_edit.text().strip()
        if not gid:
            QMessageBox.information(self, "Info", "Isi ID GRN dulu.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Confirm GRN ini? Stok gudang akan bertambah otomatis.")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("GRN dikonfirmasi, stok diperbarui."),
                  on_error=self._on_error, path=f"{BASE}/goods-receipt/{gid}/confirm")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
DO_LINE_COLS = ["SO Line ID (UUID)", "Item ID (UUID)", "Qty Dikirim", "No. Batch", "No. Seri (pisah koma)"]


class DeliveryOrderTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Catat pengiriman barang fisik terhadap Sales Order."))

        form = QFormLayout()
        self.do_number_edit = QLineEdit()
        form.addRow("No. DO", self.do_number_edit)
        self.do_date_edit = QDateEdit(QDate.currentDate())
        self.do_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal DO", self.do_date_edit)
        self.so_id_edit = QLineEdit()
        self.so_id_edit.setPlaceholderText("UUID Sales Order")
        form.addRow("Sales Order", self.so_id_edit)
        self.warehouse_edit = QLineEdit()
        self.warehouse_edit.setPlaceholderText("UUID gudang pengirim")
        form.addRow("Gudang", self.warehouse_edit)
        self.shipping_address_edit = QLineEdit()
        form.addRow("Alamat Pengiriman", self.shipping_address_edit)
        self.carrier_edit = QLineEdit()
        form.addRow("Kurir/Ekspedisi", self.carrier_edit)
        self.tracking_edit = QLineEdit()
        form.addRow("No. Resi", self.tracking_edit)
        outer.addLayout(form)

        self.line_table = QTableWidget(0, len(DO_LINE_COLS))
        self.line_table.setHorizontalHeaderLabels(DO_LINE_COLS)
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

        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(50)
        self.notes_edit.setPlaceholderText("Catatan (opsional)")
        outer.addWidget(self.notes_edit)

        submit_row = QHBoxLayout()
        submit_btn = QPushButton("+ Simpan Delivery Order")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        submit_row.addWidget(submit_btn)
        submit_row.addStretch()
        outer.addLayout(submit_row)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("Aksi lanjutan (ID DO):"))
        self.action_id_edit = QLineEdit()
        self.action_id_edit.setMaximumWidth(260)
        action_row.addWidget(self.action_id_edit)
        confirm_btn = QPushButton("✔ Confirm")
        confirm_btn.setProperty("class", "success")
        confirm_btn.clicked.connect(self._confirm)
        action_row.addWidget(confirm_btn)
        ship_btn = QPushButton("🚚 Tandai Terkirim (Ship)")
        ship_btn.setObjectName("primaryButton")
        ship_btn.clicked.connect(self._ship)
        action_row.addWidget(ship_btn)
        outer.addLayout(action_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _add_line(self) -> None:
        row = self.line_table.rowCount()
        self.line_table.insertRow(row)
        for col in range(len(DO_LINE_COLS)):
            self.line_table.setItem(row, col, QTableWidgetItem(""))

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _submit(self) -> None:
        if not (self.do_number_edit.text().strip() and self.so_id_edit.text().strip()
                and self.warehouse_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "No. DO, Sales Order, dan Gudang wajib diisi.")
            return
        lines = []
        for row in range(self.line_table.rowCount()):
            so_line_id = self._cell(row, 0).strip()
            item_id = self._cell(row, 1).strip()
            if not so_line_id or not item_id:
                continue
            try:
                qty_shipped = Decimal(self._cell(row, 2) or "0")
                if qty_shipped <= 0:
                    raise InvalidOperation
            except InvalidOperation:
                QMessageBox.warning(self, "Validasi", f"Qty dikirim baris {row + 1} harus angka > 0.")
                return
            serials = [s.strip() for s in self._cell(row, 4).split(",") if s.strip()]
            lines.append({
                "sales_order_line_id": so_line_id,
                "item_id": item_id,
                "quantity_shipped": float(qty_shipped),
                "batch_number": self._cell(row, 3).strip() or None,
                "serial_numbers": serials or None,
            })
        if not lines:
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris item dengan qty > 0 diperlukan.")
            return
        payload = {
            "do_number": self.do_number_edit.text().strip(),
            "do_date": self.do_date_edit.date().toString("yyyy-MM-dd"),
            "sales_order_id": self.so_id_edit.text().strip(),
            "warehouse_id": self.warehouse_edit.text().strip(),
            "shipping_address": self.shipping_address_edit.text().strip() or None,
            "tracking_number": self.tracking_edit.text().strip() or None,
            "carrier": self.carrier_edit.text().strip() or None,
            "lines": lines,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/delivery-orders", json_body=payload)

    def _on_created(self, result: Any) -> None:
        did = (result or {}).get("id", "") if isinstance(result, dict) else ""
        if did:
            self.action_id_edit.setText(str(did))
        self.status_label.setText(f"Delivery Order disimpan. ID: {did}")

    def _confirm(self) -> None:
        did = self.action_id_edit.text().strip()
        if not did:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("DO dikonfirmasi."),
                  on_error=self._on_error, path=f"{BASE}/delivery-orders/{did}/confirm")

    def _ship(self) -> None:
        did = self.action_id_edit.text().strip()
        if not did:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("DO ditandai terkirim."),
                  on_error=self._on_error, path=f"{BASE}/delivery-orders/{did}/ship")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")
