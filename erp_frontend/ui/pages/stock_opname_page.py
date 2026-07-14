"""
ui/pages/stock_opname_page.py
================================
Melengkapi gap kritis modul Inventory: Stock Opname (hitung fisik),
Stock Card (kartu stok per item), Valuasi Persediaan, dan Alert Stok
Menipis — semuanya tidak ada UI di frontend lama.

Endpoint backend (base: /inventory/inventory):
  GET  /stock-card/{item_id}          - kartu stok (mutasi + saldo berjalan)
  POST /stock-opname                  - buat stock opname (hitung fisik)
  POST /stock-opname/{id}/approve     - approve & posting selisih opname
  GET  /valuation/{item_id}           - valuasi 1 item (FIFO/LIFO/AVG layers)
  GET  /valuation                     - valuasi semua item
  GET  /alerts/low-stock              - daftar item di bawah reorder point
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
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
from core.formatting import extract_list, format_date, format_datetime, format_money
from core.workers import run_task

BASE = "/inventory/inventory"


class StockOpnamePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("📋  Stock Opname, Kartu Stok & Valuasi")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(StockOpnameTab(), "Stock Opname")
        self.tabs.addTab(StockCardTab(), "Kartu Stok")
        self.tabs.addTab(ValuationTab(), "Valuasi Persediaan")
        self.tabs.addTab(LowStockAlertTab(), "Alert Stok Menipis")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class StockOpnameTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Buat sesi hitung fisik untuk 1 gudang. Tambahkan baris per item "
            "(qty sistem vs qty fisik), selisihnya akan otomatis di-posting "
            "sebagai penyesuaian stok setelah di-approve."
        ))

        header_row = QHBoxLayout()
        self.warehouse_edit = QLineEdit()
        self.warehouse_edit.setPlaceholderText("UUID gudang")
        header_row.addWidget(QLabel("Gudang:"))
        header_row.addWidget(self.warehouse_edit)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        header_row.addWidget(QLabel("Tanggal:"))
        header_row.addWidget(self.date_edit)
        outer.addLayout(header_row)

        self.line_table = QTableWidget(0, 3)
        self.line_table.setHorizontalHeaderLabels(["Item ID (UUID)", "Qty Sistem", "Qty Fisik"])
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
        self.notes_edit.setFixedHeight(60)
        self.notes_edit.setPlaceholderText("Catatan opname (opsional)")
        outer.addWidget(self.notes_edit)

        submit_row = QHBoxLayout()
        submit_btn = QPushButton("+ Simpan Stock Opname")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        submit_row.addWidget(submit_btn)
        submit_row.addStretch()
        submit_row.addWidget(QLabel("Approve opname (ID):"))
        self.approve_id_edit = QLineEdit()
        self.approve_id_edit.setMaximumWidth(280)
        submit_row.addWidget(self.approve_id_edit)
        approve_btn = QPushButton("✔ Approve & Posting Selisih")
        approve_btn.setProperty("class", "success")
        approve_btn.clicked.connect(self._approve)
        submit_row.addWidget(approve_btn)
        outer.addLayout(submit_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _add_line(self) -> None:
        row = self.line_table.rowCount()
        self.line_table.insertRow(row)
        for col, default in enumerate(["", "0", "0"]):
            self.line_table.setItem(row, col, QTableWidgetItem(default))

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _submit(self) -> None:
        warehouse_id = self.warehouse_edit.text().strip()
        if not warehouse_id:
            QMessageBox.warning(self, "Validasi", "ID gudang wajib diisi.")
            return
        lines = []
        for row in range(self.line_table.rowCount()):
            item_id = self._cell(row, 0).strip()
            if not item_id:
                continue
            try:
                system_qty = Decimal(self._cell(row, 1) or "0")
                physical_qty = Decimal(self._cell(row, 2) or "0")
            except InvalidOperation:
                QMessageBox.warning(self, "Validasi", f"Qty di baris {row + 1} bukan angka valid.")
                return
            lines.append({
                "item_id": item_id,
                "system_quantity": float(system_qty),
                "physical_quantity": float(physical_qty),
            })
        if not lines:
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris item diperlukan.")
            return
        payload = {
            "warehouse_id": warehouse_id,
            "opname_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "lines": lines,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_success, on_error=self._on_error,
                  path=f"{BASE}/stock-opname", json_body=payload)

    def _approve(self) -> None:
        opname_id = self.approve_id_edit.text().strip()
        if not opname_id:
            QMessageBox.information(self, "Info", "Masukkan ID stock opname yang mau di-approve.")
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi",
            "Approve stock opname ini? Selisih qty akan otomatis diposting sebagai penyesuaian stok."
        )
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=self._on_success, on_error=self._on_error,
                  path=f"{BASE}/stock-opname/{opname_id}/approve")

    def _on_success(self, result: Any) -> None:
        opname_id = (result or {}).get("id", "") if isinstance(result, dict) else ""
        msg = "Berhasil." + (f" ID: {opname_id}" if opname_id else "")
        self.status_label.setText(msg)

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class StockCardTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        self.item_id_edit = QLineEdit()
        self.item_id_edit.setPlaceholderText("UUID item")
        row.addWidget(QLabel("Item:"))
        row.addWidget(self.item_id_edit)
        load_btn = QPushButton("⟳ Tampilkan Kartu Stok")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Tanggal", "Tipe Mutasi", "Masuk", "Keluar", "Saldo", "Referensi"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        item_id = self.item_id_edit.text().strip()
        if not item_id:
            QMessageBox.information(self, "Info", "Masukkan ID item.")
            return
        self.status_label.setText("Memuat kartu stok...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/stock-card/{item_id}")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            qty = rec.get("quantity", 0) or 0
            is_in = str(rec.get("movement_type", "")).lower() in ("receipt", "in", "adjustment_in")
            values = [
                format_date(rec.get("movement_date") or rec.get("date")),
                str(rec.get("movement_type", "")),
                str(qty) if is_in else "-",
                "-" if is_in else str(qty),
                str(rec.get("running_balance", rec.get("balance", ""))),
                str(rec.get("reference_number", rec.get("reference", "")) or "-"),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} baris mutasi ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class ValuationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        load_all_btn = QPushButton("⟳ Muat Valuasi Semua Item")
        load_all_btn.setObjectName("primaryButton")
        load_all_btn.clicked.connect(self._load_all)
        row.addWidget(load_all_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Kode Item", "Nama Item", "Metode", "Total Qty", "Total Nilai", "Rata-rata Tertimbang"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load_all(self) -> None:
        self.status_label.setText("Memuat valuasi...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/valuation")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            values = [
                rec.get("item_code", ""),
                rec.get("item_name", ""),
                str(rec.get("valuation_method", "")),
                str(rec.get("total_quantity", "")),
                format_money(rec.get("total_value")),
                format_money(rec.get("weighted_average_cost")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} item dinilai.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class LowStockAlertTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Kode Item", "Nama Item", "Stok Saat Ini", "Reorder Point", "Kekurangan"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        self.status_label.setText("Memuat alert stok menipis...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/alerts/low-stock")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            values = [
                rec.get("item_code", ""),
                rec.get("item_name", ""),
                str(rec.get("current_stock", "")),
                str(rec.get("reorder_point", "")),
                str(rec.get("shortage", "")),
            ]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c == 4:
                    item.setForeground(QColor("#DC2626"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} item di bawah titik reorder.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
