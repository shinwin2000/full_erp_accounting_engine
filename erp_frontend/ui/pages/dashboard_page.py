"""
ui/pages/dashboard_page.py
============================
Dashboard eksekutif — menarik ringkasan dari 4 endpoint read-only.

PERBAIKAN PENTING (setelah verifikasi ulang terhadap schema backend):
  1. /ar/ar/dashboard, /ap/ap/aging, dan /budget/budget/dashboard SEMUA
     mewajibkan query param `as_of_date` (Query(...) tanpa default) —
     versi sebelumnya tidak mengirim param ini sama sekali, yang akan
     selalu gagal 422 di backend sungguhan.
  2. /ap/ap/aging mengembalikan LIST per-vendor (bukan 1 objek ringkasan)
     — perlu dijumlahkan di sisi client.
  3. /bank-cash/bank-cash/daily-position mengembalikan LIST per-rekening
     — juga perlu dijumlahkan.
  4. Nama field diperbaiki sesuai schema asli:
     - AR: `overdue_amount` (bukan `total_overdue`)
     - Budget: `total_actual_ytd`/`overall_consumption_rate`
       (bukan `realization_percent`/`percent_used`)
"""
from __future__ import annotations

from datetime import date
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_money
from core.session import session
from core.workers import run_task
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
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

        sub = QLabel(f"Ringkasan posisi keuangan per {date.today().strftime('%d %B %Y')}.")
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
        self.card_overdue_ap = KpiCard("AP Jatuh Tempo (Vendor)", icon="⚠️", color="#DC2626")
        self.card_dso = KpiCard("DSO (Days Sales Outstanding)", icon="📆", color="#0891B2")
        self.card_budget_variance = KpiCard("Variance Budget", icon="📊", color="#EA580C")

        for i, card in enumerate([
            self.card_ar, self.card_ap, self.card_cash, self.card_budget,
            self.card_overdue_ar, self.card_overdue_ap, self.card_dso, self.card_budget_variance,
        ]):
            grid.addWidget(card, i // 4, i % 4)

        outer.addWidget(scroll, stretch=1)
        scroll.setWidget(content)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.status_label.setText("Memuat dashboard...")
        today = date.today().isoformat()
        run_task(api_client.get, on_success=self._on_ar, on_error=self._on_error,
                  path="/ar/ar/dashboard", params={"as_of_date": today})
        run_task(api_client.get, on_success=self._on_ap, on_error=self._on_error,
                  path="/ap/ap/aging", params={"as_of_date": today})
        run_task(api_client.get, on_success=self._on_cash, on_error=self._on_error,
                  path="/bank-cash/bank-cash/daily-position", params={"as_of_date": today})
        run_task(api_client.get, on_success=self._on_budget, on_error=self._on_error,
                  path="/budget/budget/dashboard", params={"as_of_date": today})

    def _on_ar(self, data: Any) -> None:
        data = data or {}
        self.card_ar.set_value(format_money(data.get("total_outstanding")))
        self.card_overdue_ar.set_value(
            format_money(data.get("overdue_amount")),
            f"{data.get('overdue_percentage', 0):.1f}% dari total" if data.get("overdue_percentage") is not None else "",
        )
        dso = data.get("dso_days")
        self.card_dso.set_value(f"{dso:.0f} hari" if dso is not None else "-")
        self.status_label.setText("Dashboard dimuat.")

    def _on_ap(self, payload: Any) -> None:
        # /ap/ap/aging mengembalikan list per-vendor, harus dijumlahkan.
        rows = extract_list(payload) or (payload if isinstance(payload, list) else [])
        total_outstanding = sum(float(r.get("total_outstanding", 0) or 0) for r in rows)
        total_overdue = 0.0
        for r in rows:
            for bucket in (r.get("buckets") or []):
                # bucket non-"current" dianggap overdue; nama field bucket
                # bisa bervariasi (label/bucket_label/days_range), jadi cek
                # beberapa kemungkinan supaya tetap toleran terhadap variasi.
                label = str(bucket.get("label") or bucket.get("bucket_label") or bucket.get("days_range") or "").lower()
                if "current" not in label and "0-30" not in label:
                    try:
                        total_overdue += float(bucket.get("amount", 0) or 0)
                    except (TypeError, ValueError):
                        pass
        self.card_ap.set_value(format_money(total_outstanding))
        self.card_overdue_ap.set_value(f"{len(rows)} vendor", f"Overdue: {format_money(total_overdue)}" if total_overdue else "")

    def _on_cash(self, payload: Any) -> None:
        # /bank-cash/.../daily-position mengembalikan list per-rekening.
        rows = extract_list(payload) or (payload if isinstance(payload, list) else [])
        total = sum(float(r.get("balance", 0) or 0) for r in rows)
        self.card_cash.set_value(format_money(total), f"{len(rows)} rekening" if rows else "Data tidak tersedia")

    def _on_budget(self, data: Any) -> None:
        data = data or {}
        actual_ytd = data.get("total_actual_ytd")
        budget_amt = data.get("total_budget_amount")
        rate = data.get("overall_consumption_rate")
        if budget_amt:
            self.card_budget.set_value(f"{rate:.1f}%" if rate is not None else "-",
                                        f"{format_money(actual_ytd)} / {format_money(budget_amt)}")
        else:
            self.card_budget.set_value("-", "Belum ada budget aktif")
        self.card_budget_variance.set_value(format_money(data.get("total_variance")))

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Sebagian data gagal dimuat: {message}")
