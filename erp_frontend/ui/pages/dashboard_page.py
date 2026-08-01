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

TAMPILAN (colorful theme):
  - Banner ungu gradasi di bagian atas dengan jam berjalan.
  - 8 kartu KPI dengan gradasi warna berbeda-beda (bukan putih polos).
  - Baris "Quick Actions" dengan tombol warna-warni yang langsung
    berpindah ke modul terkait (dipancarkan lewat sinyal navigate_requested
    yang ditangkap oleh MainWindow).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from core.api_client import api_client
from core.config import APP_VERSION
from core.formatting import extract_list, format_money
from core.session import session
from core.workers import run_task
from PySide6.QtCore import QDateTime, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
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
    # (kind, key, title) — ditangkap MainWindow._open_page untuk pindah modul
    navigate_requested = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        greeting = QLabel(f"Selamat datang, {session.display_name} 👋")
        greeting.setStyleSheet("font-size:20px; font-weight:700; color:#1E1B4B;")
        header.addWidget(greeting)
        header.addStretch()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setProperty("class", "primary")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        sub = QLabel(f"Ringkasan posisi keuangan per {date.today().strftime('%d %B %Y')}.")
        sub.setStyleSheet("color:#6B7280; margin-bottom:2px;")
        outer.addWidget(sub)

        # ---------- Banner ungu gradasi ----------
        outer.addWidget(self._build_banner())

        # ---------- Scroll area: kartu KPI ----------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        stats_label = QLabel("📊 Enterprise Overview Statistics")
        stats_label.setStyleSheet("font-size:14px; font-weight:700; color:#1E1B4B;")
        content_layout.addWidget(stats_label)

        grid = QGridLayout()
        grid.setSpacing(14)

        self.card_ar = KpiCard("Piutang Belum Lunas (AR)", icon="💰", gradient="green")
        self.card_ap = KpiCard("Utang Belum Lunas (AP)", icon="💳", gradient="rose")
        self.card_cash = KpiCard("Posisi Kas & Bank", icon="🏦", gradient="orange")
        self.card_budget = KpiCard("Realisasi Budget", icon="📅", gradient="maroon")
        self.card_overdue_ar = KpiCard("AR Jatuh Tempo", icon="⚠️", gradient="violet")
        self.card_overdue_ap = KpiCard("AP Jatuh Tempo (Vendor)", icon="⚠️", gradient="teal")
        self.card_dso = KpiCard("DSO (Days Sales Outstanding)", icon="📆", gradient="blue")
        self.card_budget_variance = KpiCard("Variance Budget", icon="📊", gradient="indigo")

        for i, card in enumerate([
            self.card_ar, self.card_ap, self.card_cash, self.card_budget,
            self.card_overdue_ar, self.card_overdue_ap, self.card_dso, self.card_budget_variance,
        ]):
            grid.addWidget(card, i // 4, i % 4)

        content_layout.addLayout(grid)
        content_layout.addWidget(self._build_quick_actions())
        content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------
    def _build_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("dashboardBanner")
        banner.setStyleSheet(
            "QFrame#dashboardBanner {"
            "  background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            "      stop:0 #7C3AED, stop:1 #4338CA);"
            "  border-radius: 14px;"
            "}"
        )
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(22, 18, 22, 18)

        text_col = QVBoxLayout()
        title = QLabel(f"🎯 {session.display_name or 'ERP'} Dashboard")
        title.setStyleSheet("color:white; font-size:18px; font-weight:700; background:transparent;")
        text_col.addWidget(title)
        subtitle = QLabel(f"Complete Enterprise Management System · v{APP_VERSION}")
        subtitle.setStyleSheet("color:rgba(255,255,255,0.85); font-size:12px; background:transparent;")
        text_col.addWidget(subtitle)
        layout.addLayout(text_col)
        layout.addStretch()

        chip_col = QVBoxLayout()
        chip_col.setSpacing(6)
        self.banner_date_label = QLabel("")
        self.banner_date_label.setStyleSheet(
            "color:white; background-color:rgba(255,255,255,0.16);"
            " border-radius:10px; padding:5px 12px; font-size:12px;"
        )
        self.banner_time_label = QLabel("")
        self.banner_time_label.setStyleSheet(
            "color:white; background-color:rgba(255,255,255,0.16);"
            " border-radius:10px; padding:5px 12px; font-size:12px;"
        )
        chip_col.addWidget(self.banner_date_label)
        chip_col.addWidget(self.banner_time_label)
        layout.addLayout(chip_col)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

        return banner

    def _tick_clock(self) -> None:
        now = QDateTime.currentDateTime()
        self.banner_date_label.setText("📅 " + now.toString("dd MMMM yyyy"))
        self.banner_time_label.setText("🕐 " + now.toString("HH:mm:ss"))

    def _build_quick_actions(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        title = QLabel("🚀 Quick Actions")
        title.setStyleSheet("font-size:14px; font-weight:700; color:#1E1B4B; border:none;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)
        actions = [
            ("🛒 Input Pembelian", "success", "purchase_orders", "Purchase Orders"),
            ("💵 Input Penjualan", "accent", "sales_orders", "Sales Orders"),
            ("🏭 Input Produksi", "info", "work_orders", "Work Orders"),
            ("🧾 Input Biaya", "warning", "payments", "Payments"),
            ("📘 Lihat Jurnal", "primary", "journals", "Jurnal Umum"),
        ]
        for label, css_class, module_key, title_text in actions:
            btn = QPushButton(label)
            btn.setProperty("class", css_class)
            btn.setMinimumHeight(38)
            btn.clicked.connect(
                lambda _checked=False, k=module_key, t=title_text: self.navigate_requested.emit("module", k, t)
            )
            row.addWidget(btn)
        layout.addLayout(row)
        return panel

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
