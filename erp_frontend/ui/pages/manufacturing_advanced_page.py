"""
ui/pages/manufacturing_advanced_page.py
==========================================
Melengkapi gap di modul Manufacturing: sebelumnya cuma BOM/Routing/Work
Order. Menambahkan WIP (Work in Process), Cost Card produksi, Analisis
Varians, dan Close HPP bulanan.

Endpoint backend (base: /manufacturing/manufacturing):
  GET  /wip
  GET/POST /cost-cards
  GET  /variance-analysis/{work_order_id}
  POST /close-hpp?fiscal_year=&period=
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_money
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from ui.widgets.kpi_card import KpiCard

BASE = "/manufacturing/manufacturing"


class ManufacturingAdvancedPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("⚙️  WIP, Cost Card, Varians & Close HPP")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(WipTab(), "Work in Process (WIP)")
        self.tabs.addTab(CostCardTab(), "Cost Card")
        self.tabs.addTab(VarianceTab(), "Analisis Varians")
        self.tabs.addTab(CloseHppTab(), "Close HPP Bulanan")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class WipTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.wo_filter_edit = QLineEdit()
        self.wo_filter_edit.setPlaceholderText("Filter: UUID work order (opsional)")
        row.addWidget(self.wo_filter_edit)
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setObjectName("primaryButton")
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)
        outer.addLayout(row)

        cards = QHBoxLayout()
        self.card_total_wip = KpiCard("Total Nilai WIP", icon="⚙️", color="#2563EB")
        self.card_count = KpiCard("Jumlah WO Aktif", icon="🔢", color="#059669")
        cards.addWidget(self.card_total_wip)
        cards.addWidget(self.card_count)
        outer.addLayout(cards)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["No. WO", "Produk", "Qty Mulai", "Sisa Qty", "% Selesai", "Biaya Material",
             "Biaya Tenaga Kerja", "Total Biaya"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        params = {}
        if self.wo_filter_edit.text().strip():
            params["work_order_id"] = self.wo_filter_edit.text().strip()
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/wip", params=params)

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload) or (payload if isinstance(payload, list) else [])
        total_wip = sum(float(w.get("total_cost", 0) or 0) for w in rows)
        self.card_total_wip.set_value(format_money(total_wip))
        self.card_count.set_value(str(len(rows)))

        self.table.setRowCount(len(rows))
        for r, w in enumerate(rows):
            values = [
                w.get("work_order_number", ""),
                w.get("product_name", ""),
                str(w.get("quantity_started", "")),
                str(w.get("quantity_remaining", "")),
                f"{w.get('completion_percent', 0)}%",
                format_money(w.get("material_cost")),
                format_money(w.get("labor_cost")),
                format_money(w.get("total_cost")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} WIP item dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class CostCardTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Buat Cost Card Produk</b>"))
        form = QFormLayout()
        self.code_edit = QLineEdit()
        form.addRow("Kode Cost Card", self.code_edit)
        self.product_id_edit = QLineEdit()
        self.product_id_edit.setPlaceholderText("UUID produk")
        form.addRow("Produk", self.product_id_edit)
        self.effective_date_edit = QDateEdit(QDate.currentDate())
        self.effective_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Efektif", self.effective_date_edit)
        self.material_cost_edit = QLineEdit("0")
        form.addRow("Biaya Material", self.material_cost_edit)
        self.labor_cost_edit = QLineEdit("0")
        form.addRow("Biaya Tenaga Kerja", self.labor_cost_edit)
        self.overhead_cost_edit = QLineEdit("0")
        form.addRow("Biaya Overhead", self.overhead_cost_edit)
        self.other_cost_edit = QLineEdit("0")
        form.addRow("Biaya Lain-lain", self.other_cost_edit)
        self.quantity_base_edit = QLineEdit("1")
        form.addRow("Qty Basis", self.quantity_base_edit)
        self.uom_edit = QLineEdit()
        form.addRow("Satuan", self.uom_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Buat Cost Card")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFixedHeight(100)
        outer.addWidget(self.result_text)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _dec(self, edit: QLineEdit, label: str) -> Decimal | None:
        try:
            return Decimal(edit.text().strip() or "0")
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", f"{label} harus angka.")
            return None

    def _submit(self) -> None:
        if not (self.code_edit.text().strip() and self.product_id_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Kode & produk wajib diisi.")
            return
        material = self._dec(self.material_cost_edit, "Biaya material")
        labor = self._dec(self.labor_cost_edit, "Biaya tenaga kerja")
        overhead = self._dec(self.overhead_cost_edit, "Biaya overhead")
        other = self._dec(self.other_cost_edit, "Biaya lain-lain")
        qty_base = self._dec(self.quantity_base_edit, "Qty basis")
        if None in (material, labor, overhead, other, qty_base):
            return
        payload = {
            "cost_card_code": self.code_edit.text().strip(),
            "product_id": self.product_id_edit.text().strip(),
            "effective_date": self.effective_date_edit.date().toString("yyyy-MM-dd"),
            "material_cost": float(material),
            "labor_cost": float(labor),
            "overhead_cost": float(overhead),
            "other_cost": float(other),
            "quantity_base": float(qty_base),
            "unit_of_measure": self.uom_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_created, on_error=self._on_error,
                  path=f"{BASE}/cost-cards", json_body=payload)

    def _on_created(self, result: Any) -> None:
        data = result or {}
        total = data.get("total_cost")
        self.result_text.setPlainText(
            f"Cost Card dibuat.\nTotal Cost per Unit Basis: {format_money(total)}"
        )
        self.status_label.setText("Berhasil.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class VarianceTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.wo_id_edit = QLineEdit()
        self.wo_id_edit.setPlaceholderText("UUID work order")
        row.addWidget(self.wo_id_edit)
        load_btn = QPushButton("⟳ Analisis Varians")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Komponen", "Standar", "Aktual", "Varians"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        wo_id = self.wo_id_edit.text().strip()
        if not wo_id:
            QMessageBox.information(self, "Info", "Masukkan ID work order.")
            return
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/variance-analysis/{wo_id}")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        components = [
            ("Material", data.get("standard_material_cost"), data.get("actual_material_cost"), data.get("material_variance")),
            ("Tenaga Kerja", data.get("standard_labor_cost"), data.get("actual_labor_cost"), data.get("labor_variance")),
            ("Overhead", data.get("standard_overhead_cost"), data.get("actual_overhead_cost"), data.get("overhead_variance")),
            ("Total", data.get("standard_total_cost"), data.get("actual_total_cost"), data.get("total_variance")),
        ]
        self.table.setRowCount(len(components))
        for r, (label, std, act, var) in enumerate(components):
            values = [label, format_money(std), format_money(act), format_money(var)]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText("Analisis varians dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class CloseHppTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Tutup HPP Bulanan (Hitung COGS dari Produksi)</b><br>"
            "<span style='color:#DC2626;'>Aksi ini menutup periode produksi & menghitung HPP final — "
            "pastikan semua WO bulan tersebut sudah selesai/completed.</span>"
        ))
        form = QFormLayout()
        self.year_edit = QSpinBox()
        self.year_edit.setRange(2000, 2100)
        self.year_edit.setValue(QDate.currentDate().year())
        form.addRow("Tahun Fiskal", self.year_edit)
        self.period_edit = QSpinBox()
        self.period_edit.setRange(1, 12)
        self.period_edit.setValue(QDate.currentDate().month())
        form.addRow("Periode (Bulan)", self.period_edit)
        outer.addLayout(form)

        close_btn = QPushButton("🔒 Tutup HPP Periode Ini")
        close_btn.setProperty("class", "danger")
        close_btn.clicked.connect(self._close)
        outer.addWidget(close_btn)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        outer.addWidget(self.result_text, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _close(self) -> None:
        confirm = QMessageBox.question(
            self, "Konfirmasi",
            f"Tutup HPP untuk periode {self.period_edit.value()}/{self.year_edit.value()}? Aksi ini final."
        )
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=self._on_result, on_error=self._on_error,
                  path=f"{BASE}/close-hpp",
                  params={"fiscal_year": self.year_edit.value(), "period": self.period_edit.value()})

    def _on_result(self, data: Any) -> None:
        data = data or {}
        lines = [
            f"Total HPP: {format_money(data.get('total_hpp'))}",
            f"Jumlah Work Order Ditutup: {data.get('work_orders_closed', 0)}",
            f"Status: {data.get('status', '-')}",
        ]
        self.result_text.setPlainText("\n".join(lines))
        self.status_label.setText("Periode HPP ditutup.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")
