"""
ui/pages/forex_workspace_page.py
===================================
Melengkapi gap di modul Currency Exchange & Forex (dua router backend
yang strukturnya identik, jadi dipakai 1 widget yang dikonfigurasi mirip
pola invoice_workspace.py untuk AR/AP). Menambahkan Revaluasi kurs,
Dashboard, Posisi Forex, dan Master Data Mata Uang.

Endpoint backend:
  GET/POST /currencies                — master data mata uang
  POST     /revaluation               — jalankan revaluasi kurs & posting ke ledger
  GET      /revaluation/{id}          — detail hasil revaluasi
  POST     /revaluation/{id}/reverse  — reverse revaluasi
  GET      /position                  — posisi eksposur forex saat ini
  GET      /dashboard                 — ringkasan
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFormLayout,
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
from core.formatting import extract_list, format_money
from core.workers import run_task
from ui.widgets.kpi_card import KpiCard


class ForexWorkspaceConfig:
    def __init__(self, base_path: str, label: str, icon: str):
        self.base_path = base_path
        self.label = label
        self.icon = icon


CURRENCY_EXCHANGE_CONFIG = ForexWorkspaceConfig(
    base_path="/currency-exchange/currency-exchange", label="Currency Exchange", icon="💱"
)
FOREX_CONFIG = ForexWorkspaceConfig(base_path="/forex/forex", label="Forex", icon="🌐")


class ForexWorkspacePage(QWidget):
    def __init__(self, config: ForexWorkspaceConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel(f"{self.config.icon}  {self.config.label} — Revaluasi, Dashboard & Posisi")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(CurrencyMasterTab(self.config), "Master Mata Uang")
        self.tabs.addTab(RevaluationTab(self.config), "Revaluasi")
        self.tabs.addTab(PositionTab(self.config), "Posisi Forex")
        self.tabs.addTab(DashboardTab(self.config), "Dashboard")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class CurrencyMasterTab(QWidget):
    def __init__(self, config: ForexWorkspaceConfig):
        super().__init__()
        self.config = config
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

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Kode", "Nama", "Simbol"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Tambah Mata Uang Baru</b>"))
        form = QFormLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("mis. USD, EUR, JPY")
        form.addRow("Kode", self.code_edit)
        self.name_edit = QLineEdit()
        form.addRow("Nama", self.name_edit)
        self.symbol_edit = QLineEdit()
        form.addRow("Simbol", self.symbol_edit)
        outer.addLayout(form)
        add_btn = QPushButton("+ Tambah")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self._add)
        outer.addWidget(add_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{self.config.base_path}/currencies")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            values = [str(c.get("code", "")), c.get("name", ""), c.get("symbol", "")]
            for col, v in enumerate(values):
                self.table.setItem(r, col, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} mata uang terdaftar.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _add(self) -> None:
        if not (self.code_edit.text().strip() and self.name_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Kode & nama wajib diisi.")
            return
        payload = {
            "code": self.code_edit.text().strip().upper(),
            "name": self.name_edit.text().strip(),
            "symbol": self.symbol_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self._after("Mata uang ditambahkan."),
                  on_error=self._on_error, path=f"{self.config.base_path}/currencies", json_body=payload)

    def _after(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.refresh()


# ==========================================================================
class RevaluationTab(QWidget):
    def __init__(self, config: ForexWorkspaceConfig):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Jalankan Revaluasi Kurs (Akhir Bulan)</b><br>"
            "<span style='color:#6B7280;'>Menghitung selisih kurs atas seluruh saldo mata uang asing "
            "dan (opsional) posting otomatis ke Ledger.</span>"
        ))
        form = QFormLayout()
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Revaluasi", self.date_edit)
        self.post_check = QCheckBox("Posting otomatis ke Ledger")
        form.addRow("", self.post_check)
        self.gain_account_edit = QLineEdit()
        self.gain_account_edit.setPlaceholderText("mis. 7-1100 (Laba Selisih Kurs)")
        form.addRow("Akun Laba Kurs", self.gain_account_edit)
        self.loss_account_edit = QLineEdit()
        self.loss_account_edit.setPlaceholderText("mis. 8-1100 (Rugi Selisih Kurs)")
        form.addRow("Akun Rugi Kurs", self.loss_account_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        run_btn = QPushButton("▶ Jalankan Revaluasi")
        run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(self._run)
        outer.addWidget(run_btn)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        outer.addWidget(self.result_text, stretch=1)

        reverse_row = QHBoxLayout()
        self.reverse_id_edit = QLineEdit()
        self.reverse_id_edit.setPlaceholderText("ID hasil revaluasi untuk direverse")
        reverse_row.addWidget(self.reverse_id_edit)
        reverse_btn = QPushButton("✘ Reverse")
        reverse_btn.setProperty("class", "danger")
        reverse_btn.clicked.connect(self._reverse)
        reverse_row.addWidget(reverse_btn)
        outer.addLayout(reverse_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _run(self) -> None:
        if self.post_check.isChecked() and not (self.gain_account_edit.text().strip() and self.loss_account_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Akun laba/rugi kurs wajib diisi jika posting otomatis diaktifkan.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Jalankan revaluasi kurs untuk tanggal ini?")
        if confirm != QMessageBox.Yes:
            return
        payload = {
            "revaluation_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "post_to_ledger": self.post_check.isChecked(),
            "gain_account_code": self.gain_account_edit.text().strip() or None,
            "loss_account_code": self.loss_account_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_result, on_error=self._on_error,
                  path=f"{self.config.base_path}/revaluation", json_body=payload)

    def _on_result(self, data: Any) -> None:
        data = data or {}
        rid = data.get("revaluation_id", data.get("id", ""))
        if rid:
            self.reverse_id_edit.setText(str(rid))
        lines = [
            f"ID Revaluasi: {rid}",
            f"Total Gain: {format_money(data.get('total_gain'))}",
            f"Total Loss: {format_money(data.get('total_loss'))}",
            f"Net Impact: {format_money(data.get('net_impact'))}",
            f"Jumlah Item Direvaluasi: {data.get('items_revalued', 0)}",
        ]
        self.result_text.setPlainText("\n".join(lines))
        self.status_label.setText("Revaluasi selesai.")

    def _reverse(self) -> None:
        rid = self.reverse_id_edit.text().strip()
        if not rid:
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Reverse hasil revaluasi ini?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Revaluasi di-reverse."),
                  on_error=self._on_error, path=f"{self.config.base_path}/revaluation/{rid}/reverse")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class PositionTab(QWidget):
    def __init__(self, config: ForexWorkspaceConfig):
        super().__init__()
        self.config = config
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
            ["Mata Uang", "Saldo Asing", "Kurs Saat Ini", "Nilai (IDR)", "Unrealized Gain/Loss"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{self.config.base_path}/position")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            values = [
                str(p.get("currency_code", "")),
                str(p.get("foreign_balance", "")),
                str(p.get("current_rate", "")),
                format_money(p.get("idr_value")),
                format_money(p.get("unrealized_gain_loss")),
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} posisi mata uang.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class DashboardTab(QWidget):
    def __init__(self, config: ForexWorkspaceConfig):
        super().__init__()
        self.config = config
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

        cards = QHBoxLayout()
        self.card_exposure = KpiCard("Total Eksposur (IDR)", icon="🌐", color="#2563EB")
        self.card_unrealized = KpiCard("Unrealized G/L", icon="📊", color="#7C3AED")
        self.card_realized = KpiCard("Realized G/L (Bulan Ini)", icon="✅", color="#059669")
        cards.addWidget(self.card_exposure)
        cards.addWidget(self.card_unrealized)
        cards.addWidget(self.card_realized)
        outer.addLayout(cards)
        outer.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{self.config.base_path}/dashboard")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        self.card_exposure.set_value(format_money(data.get("total_exposure")))
        self.card_unrealized.set_value(format_money(data.get("unrealized_gain_loss")))
        self.card_realized.set_value(format_money(data.get("realized_gain_loss_mtd")))
        self.status_label.setText("Dashboard dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
