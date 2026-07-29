"""
ui/widgets/kpi_card.py
=======================
Kartu KPI kecil dipakai di Dashboard & halaman ringkasan modul (AR aging,
Budget dashboard, dsb).
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class KpiCard(QFrame):
    def __init__(self, title: str, value: str = "-", icon: str = "📊", color: str = "#1E3A8A"):
        super().__init__()
        self.setProperty("class", "card")
        self.setObjectName("kpiCard")
        self.setMinimumHeight(96)
        self.setStyleSheet(
            "QFrame#kpiCard { background:white; border:1px solid #E5E7EB; border-radius:10px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        top = QLabel(f"{icon}  {title}")
        top.setStyleSheet("color:#6B7280; font-size:12px; font-weight:600; border:none;")
        layout.addWidget(top)

        self.value_label = QLabel(value)
        self.value_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self.value_label.setStyleSheet(f"color:{color}; border:none;")
        layout.addWidget(self.value_label)

        self.sub_label = QLabel("")
        self.sub_label.setStyleSheet("color:#9CA3AF; font-size:11px; border:none;")
        layout.addWidget(self.sub_label)

    def set_value(self, value: str, sub: str = "") -> None:
        self.value_label.setText(value)
        self.sub_label.setText(sub)
        self.sub_label.setVisible(bool(sub))
