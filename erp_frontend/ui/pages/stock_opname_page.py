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

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
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

BASE = "/inventory/inventory"


# ==========================================================================
# Helper dropdown gudang/item (fix "jangan pakai UUID mentah") - dipakai
# StockOpnameTab & StockCardTab di bawah supaya user memilih gudang/item
# dari data asli (kode + nama) alih-alih mengetik/copy-paste UUID.
# ==========================================================================
def _populate_warehouse_combo(combo: QComboBox) -> None:
    combo.clear()
    combo.addItem("Memuat...", None)
    combo.setEnabled(False)

    def _on_loaded(payload: Any) -> None:
        try:
            combo.clear()
            rows = extract_list(payload)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = row.get("warehouse_code", "")
                name = row.get("warehouse_name", "")
                label = f"{code} - {name}" if name else code
                combo.addItem(label, row.get("id"))
            if combo.count() == 0:
                combo.addItem("(belum ada gudang)", None)
            combo.setEnabled(True)
        except RuntimeError:
            pass

    def _on_error(message: str) -> None:
        try:
            combo.clear()
            # FIX: pesan error asli sebelumnya dibuang - diganti generik
            # "(gagal memuat gudang)" tanpa keterangan apapun, sehingga
            # penyebab sebenarnya (401/422/koneksi putus/dll) mustahil
            # didiagnosis. Sekarang ditampilkan apa adanya.
            short = (message or "tidak diketahui").strip()
            if len(short) > 60:
                short = short[:57] + "..."
            combo.addItem(f"(gagal memuat gudang: {short})", None)
            combo.setEnabled(False)
        except RuntimeError:
            pass

    run_task(api_client.get, on_success=_on_loaded, on_error=_on_error,
              path=f"{BASE}/warehouses")


def _populate_item_combo(combo: QComboBox) -> None:
    combo.clear()
    combo.addItem("Memuat...", None)
    combo.setEnabled(False)

    def _on_loaded(payload: Any) -> None:
        try:
            combo.clear()
            rows = extract_list(payload)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = row.get("item_code", "")
                name = row.get("item_name", "")
                label = f"{code} - {name}" if name else code
                combo.addItem(label, row.get("id"))
            if combo.count() == 0:
                combo.addItem("(belum ada item)", None)
            combo.setEnabled(True)
        except RuntimeError:
            pass

    def _on_error(message: str) -> None:
        try:
            combo.clear()
            short = (message or "tidak diketahui").strip()
            if len(short) > 60:
                short = short[:57] + "..."
            combo.addItem(f"(gagal memuat item: {short})", None)
            combo.setEnabled(False)
        except RuntimeError:
            pass

    run_task(api_client.get, on_success=_on_loaded, on_error=_on_error,
              path=f"{BASE}/items", params={"page": 1, "page_size": 200, "limit": 200})


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


def _populate_pending_opname_combo(combo: QComboBox) -> None:
    """Isi dropdown dengan stock opname berstatus draft/pending, supaya user
    memilih dari daftar nyata alih-alih mengetik ID sendiri (sebelumnya tidak
    ada endpoint list sama sekali - lihat catatan di router)."""
    combo.clear()
    combo.addItem("Memuat...", None)
    combo.setEnabled(False)

    def _on_loaded(payload: Any) -> None:
        try:
            combo.clear()
            rows = extract_list(payload)
            pending = [
                r for r in rows
                if isinstance(r, dict) and str(r.get("status", "")).lower() in ("draft", "pending", "open")
            ]
            for row in pending:
                number = row.get("opname_number", "")
                opname_date = row.get("opname_date", "")
                label = f"{number} ({opname_date})" if opname_date else number
                combo.addItem(label, row.get("id"))
            if combo.count() == 0:
                combo.addItem("(tidak ada opname yang menunggu approval)", None)
            combo.setEnabled(True)
        except RuntimeError:
            pass

    def _on_error(message: str) -> None:
        try:
            combo.clear()
            short = (message or "tidak diketahui").strip()
            if len(short) > 60:
                short = short[:57] + "..."
            combo.addItem(f"(gagal memuat daftar opname: {short})", None)
            combo.setEnabled(False)
        except RuntimeError:
            pass

    run_task(api_client.get, on_success=_on_loaded, on_error=_on_error,
              path=f"{BASE}/stock-opname", params={"page": 1, "page_size": 100})


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
        self.warehouse_combo = QComboBox()
        self.warehouse_combo.setMinimumWidth(240)
        _populate_warehouse_combo(self.warehouse_combo)
        header_row.addWidget(QLabel("Gudang:"))
        header_row.addWidget(self.warehouse_combo)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        header_row.addWidget(QLabel("Tanggal:"))
        header_row.addWidget(self.date_edit)
        outer.addLayout(header_row)

        self.line_table = QTableWidget(0, 3)
        self.line_table.setHorizontalHeaderLabels(["Item", "Qty Sistem", "Qty Fisik"])
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
        submit_row.addWidget(QLabel("Approve opname:"))
        self.approve_combo = QComboBox()
        self.approve_combo.setMinimumWidth(220)
        _populate_pending_opname_combo(self.approve_combo)
        submit_row.addWidget(self.approve_combo)
        refresh_approve_btn = QPushButton("⟳")
        refresh_approve_btn.setToolTip("Muat ulang daftar opname")
        refresh_approve_btn.clicked.connect(lambda: _populate_pending_opname_combo(self.approve_combo))
        submit_row.addWidget(refresh_approve_btn)
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
        item_combo = QComboBox()
        _populate_item_combo(item_combo)
        self.line_table.setCellWidget(row, 0, item_combo)
        for col, default in ((1, "0"), (2, "0")):
            self.line_table.setItem(row, col, QTableWidgetItem(default))

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _item_id_at(self, row: int) -> str:
        combo = self.line_table.cellWidget(row, 0)
        if isinstance(combo, QComboBox):
            data = combo.currentData()
            return str(data) if data else ""
        return ""

    def _submit(self) -> None:
        warehouse_id = self.warehouse_combo.currentData()
        if not warehouse_id:
            QMessageBox.warning(self, "Validasi", "Gudang wajib dipilih.")
            return
        lines = []
        for row in range(self.line_table.rowCount()):
            item_id = self._item_id_at(row)
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
            "warehouse_id": str(warehouse_id),
            "opname_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "lines": lines,
            "notes": self.notes_edit.toPlainText().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_success, on_error=self._on_error,
                  path=f"{BASE}/stock-opname", json_body=payload)

    def _approve(self) -> None:
        opname_id = self.approve_combo.currentData()
        if not opname_id:
            QMessageBox.information(self, "Info", "Pilih stock opname yang mau di-approve.")
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi",
            "Approve stock opname ini? Selisih qty akan otomatis diposting sebagai penyesuaian stok."
        )
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=self._on_approve_success, on_error=self._on_error,
                  path=f"{BASE}/stock-opname/{opname_id}/approve")

    def _on_approve_success(self, result: Any) -> None:
        self._on_success(result)
        # Opname yang barusan di-approve tidak lagi berstatus pending, jadi
        # daftar dropdown dimuat ulang supaya tidak bisa dipilih dua kali.
        _populate_pending_opname_combo(self.approve_combo)

    def _on_success(self, result: Any) -> None:
        opname_id = (result or {}).get("id", "") if isinstance(result, dict) else ""
        msg = "Berhasil." + (f" ID: {opname_id}" if opname_id else "")
        self.status_label.setText(msg)
        _populate_pending_opname_combo(self.approve_combo)

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
        self.item_combo = QComboBox()
        self.item_combo.setMinimumWidth(260)
        _populate_item_combo(self.item_combo)
        row.addWidget(QLabel("Item:"))
        row.addWidget(self.item_combo)
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
        item_id = self.item_combo.currentData()
        if not item_id:
            QMessageBox.information(self, "Info", "Pilih item terlebih dahulu.")
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
