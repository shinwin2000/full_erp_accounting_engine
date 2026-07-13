"""
ui/pages/capital_page.py
===========================
Modal & Dividen. Modul ini di backend bersifat action-oriented (tidak
ada endpoint list standar) — jadi UI-nya berupa form pencatatan setoran
modal + kartu statistik (GET /capital/stats).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import format_money
from core.workers import run_task
from ui.widgets.kpi_card import KpiCard

BASE = "/capital"


class CapitalPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh_stats()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("🏦  Modal & Dividen")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("⟳ Refresh Statistik")
        refresh_btn.clicked.connect(self.refresh_stats)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        cards_row = QHBoxLayout()
        self.card_total = KpiCard("Total Setoran Modal", icon="💵", color="#059669")
        self.card_count = KpiCard("Jumlah Transaksi", icon="🔢", color="#2563EB")
        cards_row.addWidget(self.card_total)
        cards_row.addWidget(self.card_count)
        outer.addLayout(cards_row)

        outer.addWidget(QLabel("<b>Catat Setoran Modal Baru</b>"))
        form = QFormLayout()
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("mis. 500000000")
        form.addRow("Jumlah Setoran (Rp)", self.amount_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(70)
        self.desc_edit.setPlaceholderText("Keterangan setoran modal...")
        form.addRow("Deskripsi", self.desc_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Catat Setoran Modal")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit_contribution)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh_stats(self) -> None:
        run_task(api_client.get, on_success=self._on_stats, on_error=self._on_error, path=f"{BASE}/stats")

    def _on_stats(self, data: Any) -> None:
        data = data or {}
        total = data.get("total_contributions") or data.get("total_amount")
        count = data.get("count") or data.get("total_count")
        self.card_total.set_value(format_money(total) if total is not None else "-")
        self.card_count.set_value(str(count) if count is not None else "-")
        self.status_label.setText("Statistik dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat statistik: {message}")

    def _submit_contribution(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip().replace(",", ""))
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah setoran harus berupa angka > 0.")
            return
        description = self.desc_edit.toPlainText().strip()
        if not description:
            QMessageBox.warning(self, "Validasi", "Deskripsi wajib diisi.")
            return
        payload = {"amount": float(amount), "description": description}
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write("Setoran modal berhasil dicatat."),
            on_error=self._on_write_error,
            path=f"{BASE}/contributions",
            json_body=payload,
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.amount_edit.clear()
        self.desc_edit.clear()
        self.refresh_stats()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
