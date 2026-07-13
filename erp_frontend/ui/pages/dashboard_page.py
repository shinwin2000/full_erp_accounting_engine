"""
ui/pages/dashboard_page.py
============================
Dashboard eksekutif: menarik ringkasan dari beberapa endpoint read-only
(/ledger/ledger/summary, /ar/ar/dashboard, /ap/ap/aging, /budget/budget/dashboard)
dan menampilkannya sebagai kartu KPI + tabel ringkas.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import format_money
from core.session import session
from core.workers import run_task
from ui.widgets.kpi_card import KpiCard


class DashboardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        greeting = QLabel(f"Selamat datang, {session.display_name} 👋")
        greeting.setStyleSheet("font-size:20px; font-weight:700;")
        header.addWidget(greeting)
        header.addStretch()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        sub = QLabel("Ringkasan posisi keuangan perusahaan saat ini.")
        sub.setStyleSheet("color:#6B7280; margin-bottom:8px;")
        outer.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setSpacing(14)

        self.card_ar = KpiCard("Piutang Belum Lunas (AR)", icon="💰", color="#2563EB")
        self.card_ap = KpiCard("Utang Belum Lunas (AP)", icon="💳", color="#D97706")
        self.card_cash = KpiCard("Posisi Kas & Bank", icon="🏦", color="#059669")
        self.card_budget = KpiCard("Realisasi Budget", icon="📅", color="#7C3AED")
        self.card_overdue_ar = KpiCard("AR Jatuh Tempo", icon="⚠️", color="#DC2626")
        self.card_overdue_ap = KpiCard("AP Jatuh Tempo", icon="⚠️", color="#DC2626")

        for i, card in enumerate(
            [self.card_ar, self.card_ap, self.card_cash, self.card_budget, self.card_overdue_ar, self.card_overdue_ap]
        ):
            grid.addWidget(card, i // 3, i % 3)

        outer.addWidget(scroll, stretch=1)
        scroll.setWidget(content)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.status_label.setText("Memuat dashboard...")
        run_task(api_client.get, on_success=self._on_ar, on_error=self._on_error, path="/ar/ar/dashboard")
        run_task(api_client.get, on_success=self._on_ap, on_error=self._on_error, path="/ap/ap/aging")
        run_task(api_client.get, on_success=self._on_cash, on_error=self._on_error, path="/bank-cash/bank-cash/daily-position")
        run_task(api_client.get, on_success=self._on_budget, on_error=self._on_error, path="/budget/budget/dashboard")

    def _on_ar(self, data: Any) -> None:
        data = data or {}
        total = data.get("total_outstanding") or data.get("total_receivable") or data.get("total")
        overdue = data.get("total_overdue") or data.get("overdue_amount")
        if total is not None:
            self.card_ar.set_value(format_money(total))
        if overdue is not None:
            self.card_overdue_ar.set_value(format_money(overdue))
        self.status_label.setText("Dashboard dimuat.")

    def _on_ap(self, data: Any) -> None:
        data = data or {}
        total = data.get("total_outstanding") or data.get("total_payable") or data.get("total")
        overdue = data.get("total_overdue") or data.get("overdue_amount")
        if total is not None:
            self.card_ap.set_value(format_money(total))
        if overdue is not None:
            self.card_overdue_ap.set_value(format_money(overdue))

    def _on_cash(self, data: Any) -> None:
        data = data or {}
        total = data.get("total_balance") or data.get("total_position") or data.get("total")
        if total is not None:
            self.card_cash.set_value(format_money(total))
        else:
            self.card_cash.set_value("-", "Data tidak tersedia")

    def _on_budget(self, data: Any) -> None:
        data = data or {}
        realized = data.get("realization_percent") or data.get("percent_used")
        if realized is not None:
            self.card_budget.set_value(f"{realized}%")
        else:
            self.card_budget.set_value("-", "Data tidak tersedia")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Sebagian data gagal dimuat: {message}")
