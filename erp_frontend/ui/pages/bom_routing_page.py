"""
ui/pages/bom_routing_page.py
===============================
Bill of Materials & Routing Produksi — SEBELUMNYA terdaftar sebagai modul
generic CRUD, padahal `BOMCreateSchema` mewajibkan `lines` (komponen,
minimal 1) dan `RoutingCreateSchema` mewajibkan `steps` (minimal 1), yang
tidak bisa direpresentasikan form generik berbasis field datar. Sama
seperti kasus Purchase/Sales Order — diganti halaman khusus dengan tabel.

Endpoint backend (base: /manufacturing/manufacturing):
  GET/POST /bom
  GET/POST /routing
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_date
from core.workers import run_task
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

BASE = "/manufacturing/manufacturing"


class BomRoutingPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("📐  Bill of Materials & Routing Produksi")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(BomTab(), "Bill of Materials")
        self.tabs.addTab(RoutingTab(), "Routing Produksi")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class BomTab(QWidget):
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
        new_btn = QPushButton("+ BOM Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_bom)
        row.addWidget(new_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Kode BOM", "Nama", "Versi", "Berlaku Sejak", "Default"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/bom")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, b in enumerate(rows):
            values = [
                b.get("bom_code", ""), b.get("bom_name", ""), str(b.get("bom_version", "")),
                format_date(b.get("effective_date")), "Ya" if b.get("is_default") else "Tidak",
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} BOM dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _new_bom(self) -> None:
        dlg = BomFormDialog(parent=self)
        if dlg.exec():
            run_task(api_client.post, on_success=lambda _r: self._after("BOM berhasil dibuat."),
                      on_error=self._on_write_error, path=f"{BASE}/bom", json_body=dlg.build_payload())

    def _after(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


BOM_LINE_COLS = ["Item Komponen (UUID)", "Qty (>0)", "Scrap %", "Satuan", "Biaya Alokasi"]


class BomFormDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BOM Baru")
        self.resize(680, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.code_edit = QLineEdit()
        form.addRow("Kode BOM (min. 3 karakter)", self.code_edit)
        self.name_edit = QLineEdit()
        form.addRow("Nama BOM (min. 3 karakter)", self.name_edit)
        self.product_id_edit = QLineEdit()
        self.product_id_edit.setPlaceholderText("UUID produk jadi")
        form.addRow("Produk", self.product_id_edit)
        self.version_edit = QSpinBox()
        self.version_edit.setRange(1, 999)
        form.addRow("Versi", self.version_edit)
        self.effective_date_edit = QDateEdit(QDate.currentDate())
        self.effective_date_edit.setCalendarPopup(True)
        form.addRow("Berlaku Sejak", self.effective_date_edit)
        self.is_default_check = QCheckBox("Jadikan BOM Default untuk produk ini")
        form.addRow("", self.is_default_check)
        outer.addLayout(form)

        outer.addWidget(QLabel("Komponen (minimal 1 baris):"))
        self.line_table = QTableWidget(0, len(BOM_LINE_COLS))
        self.line_table.setHorizontalHeaderLabels(BOM_LINE_COLS)
        self.line_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.line_table, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Baris")
        add_btn.clicked.connect(self._add_line)
        remove_btn = QPushButton("- Hapus Baris")
        remove_btn.clicked.connect(self._remove_line)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)
        self._add_line()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _add_line(self) -> None:
        row = self.line_table.rowCount()
        self.line_table.insertRow(row)
        for col, default in enumerate(["", "1", "0", "pcs", "0"]):
            self.line_table.setItem(row, col, QTableWidgetItem(default))

    def _remove_line(self) -> None:
        row = self.line_table.currentRow()
        if row >= 0:
            self.line_table.removeRow(row)

    def _cell(self, row: int, col: int) -> str:
        item = self.line_table.item(row, col)
        return item.text() if item else ""

    def _on_save(self) -> None:
        if len(self.code_edit.text().strip()) < 3 or len(self.name_edit.text().strip()) < 3:
            QMessageBox.warning(self, "Validasi", "Kode & nama BOM minimal 3 karakter.")
            return
        if not self.product_id_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Produk wajib diisi.")
            return
        filled = [r for r in range(self.line_table.rowCount()) if self._cell(r, 0).strip()]
        if not filled:
            QMessageBox.warning(self, "Validasi", "Minimal 1 baris komponen diperlukan.")
            return
        for row in filled:
            qty = _to_decimal(self._cell(row, 1))
            scrap = _to_decimal(self._cell(row, 2))
            if qty <= 0:
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Qty harus > 0.")
                return
            if not (0 <= scrap <= 100):
                QMessageBox.warning(self, "Validasi", f"Baris {row + 1}: Scrap % harus 0-100.")
                return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        lines = []
        for row in range(self.line_table.rowCount()):
            comp_id = self._cell(row, 0).strip()
            if not comp_id:
                continue
            lines.append({
                "component_item_id": comp_id,
                "quantity": float(_to_decimal(self._cell(row, 1))),
                "scrap_percent": float(_to_decimal(self._cell(row, 2))),
                "unit_of_measure": self._cell(row, 3).strip() or "pcs",
                "cost_allocated": float(_to_decimal(self._cell(row, 4))),
            })
        return {
            "bom_code": self.code_edit.text().strip(),
            "bom_name": self.name_edit.text().strip(),
            "product_id": self.product_id_edit.text().strip(),
            "bom_version": self.version_edit.value(),
            "effective_date": self.effective_date_edit.date().toString("yyyy-MM-dd"),
            "is_default": self.is_default_check.isChecked(),
            "lines": lines,
        }


# ==========================================================================
class RoutingTab(QWidget):
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
        new_btn = QPushButton("+ Routing Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_routing)
        row.addWidget(new_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Kode Routing", "Nama", "Versi", "Berlaku Sejak"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/routing")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            values = [item.get("routing_code", ""), item.get("routing_name", ""),
                      str(item.get("routing_version", "")), format_date(item.get("effective_date"))]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} routing dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _new_routing(self) -> None:
        dlg = RoutingFormDialog(parent=self)
        if dlg.exec():
            run_task(api_client.post, on_success=lambda _r: self._after("Routing berhasil dibuat."),
                      on_error=self._on_write_error, path=f"{BASE}/routing", json_body=dlg.build_payload())

    def _after(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


STEP_COLS = ["No. Urut", "Work Center", "Deskripsi", "Setup (jam)", "Proses (jam)", "Mesin (jam)", "Tenaga Kerja (jam)"]


class RoutingFormDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Routing Baru")
        self.resize(760, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.code_edit = QLineEdit()
        form.addRow("Kode Routing (min. 3 karakter)", self.code_edit)
        self.name_edit = QLineEdit()
        form.addRow("Nama Routing (min. 3 karakter)", self.name_edit)
        self.product_id_edit = QLineEdit()
        self.product_id_edit.setPlaceholderText("UUID produk")
        form.addRow("Produk", self.product_id_edit)
        self.version_edit = QSpinBox()
        self.version_edit.setRange(1, 999)
        form.addRow("Versi", self.version_edit)
        self.effective_date_edit = QDateEdit(QDate.currentDate())
        self.effective_date_edit.setCalendarPopup(True)
        form.addRow("Berlaku Sejak", self.effective_date_edit)
        self.is_default_check = QCheckBox("Jadikan Routing Default untuk produk ini")
        form.addRow("", self.is_default_check)
        outer.addLayout(form)

        outer.addWidget(QLabel("Langkah Produksi (minimal 1 step, urut No. Urut mulai dari 1):"))
        self.step_table = QTableWidget(0, len(STEP_COLS))
        self.step_table.setHorizontalHeaderLabels(STEP_COLS)
        self.step_table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.step_table, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Step")
        add_btn.clicked.connect(self._add_step)
        remove_btn = QPushButton("- Hapus Step")
        remove_btn.clicked.connect(self._remove_step)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)
        self._add_step()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _add_step(self) -> None:
        row = self.step_table.rowCount()
        self.step_table.insertRow(row)
        defaults = [str(row + 1), "", "", "0", "1", "0", "1"]
        for col, val in enumerate(defaults):
            self.step_table.setItem(row, col, QTableWidgetItem(val))

    def _remove_step(self) -> None:
        row = self.step_table.currentRow()
        if row >= 0:
            self.step_table.removeRow(row)

    def _cell(self, row: int, col: int) -> str:
        item = self.step_table.item(row, col)
        return item.text() if item else ""

    def _on_save(self) -> None:
        if len(self.code_edit.text().strip()) < 3 or len(self.name_edit.text().strip()) < 3:
            QMessageBox.warning(self, "Validasi", "Kode & nama Routing minimal 3 karakter.")
            return
        if not self.product_id_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Produk wajib diisi.")
            return
        filled = [r for r in range(self.step_table.rowCount()) if self._cell(r, 1).strip()]
        if not filled:
            QMessageBox.warning(self, "Validasi", "Minimal 1 step dengan Work Center diperlukan.")
            return
        self.accept()

    def build_payload(self) -> dict[str, Any]:
        steps = []
        for row in range(self.step_table.rowCount()):
            work_center = self._cell(row, 1).strip()
            if not work_center:
                continue
            steps.append({
                "step_number": int(_to_decimal(self._cell(row, 0)) or (row + 1)),
                "work_center": work_center,
                "description": self._cell(row, 2).strip() or None,
                "setup_time_hours": float(_to_decimal(self._cell(row, 3))),
                "run_time_hours": float(_to_decimal(self._cell(row, 4))),
                "machine_hours": float(_to_decimal(self._cell(row, 5))),
                "labor_hours": float(_to_decimal(self._cell(row, 6))),
            })
        return {
            "routing_code": self.code_edit.text().strip(),
            "routing_name": self.name_edit.text().strip(),
            "product_id": self.product_id_edit.text().strip(),
            "routing_version": self.version_edit.value(),
            "effective_date": self.effective_date_edit.date().toString("yyyy-MM-dd"),
            "is_default": self.is_default_check.isChecked(),
            "steps": steps,
        }


def _to_decimal(text: str) -> Decimal:
    text = (text or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")
