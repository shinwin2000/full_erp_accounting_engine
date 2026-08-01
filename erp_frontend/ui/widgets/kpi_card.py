"""
ui/widgets/kpi_card.py
=======================
Kartu KPI kecil dipakai di Dashboard & halaman ringkasan modul (AR aging,
Budget dashboard, dsb).

Mendukung dua gaya tampilan:
  - polos (default lama): latar putih, teks berwarna.
  - gradient: latar gradasi warna-warni (mis. hijau, merah muda, oranye,
    ungu...) dengan teks putih — dipakai di Dashboard supaya tampilan
    lebih "colorful".
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
from ui.theme import GRADIENTS


class KpiCard(QFrame):
    def __init__(
        self,
        title: str,
        value: str = "-",
        icon: str = "📊",
        color: str = "#1E3A8A",
        gradient: str | tuple[str, str] | None = None,
    ):
        super().__init__()
        self.setProperty("class", "card")
        self.setObjectName("kpiCard")
        self.setMinimumHeight(96)

        if gradient is not None:
            start, end = GRADIENTS[gradient] if isinstance(gradient, str) else gradient
            self.setStyleSheet(
                "QFrame#kpiCard {"
                f"  background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
                f"      stop:0 {start}, stop:1 {end});"
                "   border: none;"
                "   border-radius: 14px;"
                "}"
            )
            title_color = "rgba(255,255,255,0.92)"
            value_color = "white"
            sub_color = "rgba(255,255,255,0.80)"
        else:
            self.setStyleSheet(
                "QFrame#kpiCard { background:white; border:1px solid #E9D5FF; border-radius:14px; }"
            )
            title_color = "#6B7280"
            value_color = color
            sub_color = "#9CA3AF"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        top = QLabel(f"{icon}  {title}")
        top.setStyleSheet(f"color:{title_color}; font-size:12px; font-weight:600; border:none; background:transparent;")
        layout.addWidget(top)

        self.value_label = QLabel(value)
        self.value_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self.value_label.setStyleSheet(f"color:{value_color}; border:none; background:transparent;")
        layout.addWidget(self.value_label)

        self.sub_label = QLabel("")
        self.sub_label.setStyleSheet(f"color:{sub_color}; font-size:11px; border:none; background:transparent;")
        layout.addWidget(self.sub_label)

    def set_value(self, value: str, sub: str = "") -> None:
        self.value_label.setText(value)
        self.sub_label.setText(sub)
        self.sub_label.setVisible(bool(sub))
