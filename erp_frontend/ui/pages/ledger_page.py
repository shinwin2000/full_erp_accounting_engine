"""
ui/pages/ledger_page.py
=========================
General Ledger & Laporan Keuangan. Menyediakan 4 tab laporan:
Trial Balance, Balance Sheet (Neraca), Income Statement (Laba Rugi),
dan Cash Flow — semuanya read-only, ditarik dari /ledger/ledger/*.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import format_money
from core.workers import run_task

BASE = "/ledger/ledger"


class LedgerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("📊  General Ledger & Laporan Keuangan")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.trial_balance_tab = TrialBalanceTab()
        self.balance_sheet_tab = BalanceSheetTab()
        self.income_statement_tab = IncomeStatementTab()
        self.cash_flow_tab = CashFlowTab()

        self.tabs.addTab(self.trial_balance_tab, "Neraca Saldo")
        self.tabs.addTab(self.balance_sheet_tab, "Neraca (Balance Sheet)")
        self.tabs.addTab(self.income_statement_tab, "Laba Rugi")
        self.tabs.addTab(self.cash_flow_tab, "Arus Kas")
        outer.addWidget(self.tabs, stretch=1)


class _ReportTabBase(QWidget):
    """Kerangka umum: filter tanggal + tombol generate + tabel hasil."""

    def __init__(self, needs_range: bool = False):
        super().__init__()
        self.needs_range = needs_range
        outer = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        if needs_range:
            filter_row.addWidget(QLabel("Dari:"))
            self.start_date = QDateEdit(QDate.currentDate().addMonths(-1))
            self.start_date.setCalendarPopup(True)
            filter_row.addWidget(self.start_date)
            filter_row.addWidget(QLabel("Sampai:"))
            self.end_date = QDateEdit(QDate.currentDate())
            self.end_date.setCalendarPopup(True)
            filter_row.addWidget(self.end_date)
        else:
            filter_row.addWidget(QLabel("Per Tanggal:"))
            self.as_of_date = QDateEdit(QDate.currentDate())
            self.as_of_date.setCalendarPopup(True)
            filter_row.addWidget(self.as_of_date)

        gen_btn = QPushButton("Tampilkan")
        gen_btn.setObjectName("primaryButton")
        gen_btn.clicked.connect(self.generate)
        filter_row.addWidget(gen_btn)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight:600; padding:4px 0;")
        outer.addWidget(self.summary_label)

        self.table = QTableWidget(0, 2)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _params(self) -> dict[str, Any]:
        if self.needs_range:
            return {
                "start_date": self.start_date.date().toString("yyyy-MM-dd"),
                "end_date": self.end_date.date().toString("yyyy-MM-dd"),
            }
        return {"as_of_date": self.as_of_date.date().toString("yyyy-MM-dd")}

    def _set_table(self, headers: list[str], rows: list[list[str]]) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem(val)
                if c > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def generate(self) -> None:  # override
        raise NotImplementedError

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat laporan: {message}")


class TrialBalanceTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=False)

    def generate(self) -> None:
        self.status_label.setText("Memuat neraca saldo...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/trial-balance", params=self._params())

    def _on_data(self, data: dict[str, Any]) -> None:
        lines = data.get("lines", [])
        rows = []
        for line in lines:
            rows.append([
                f"{line.get('account_code')} — {line.get('account_name')}",
                format_money(line.get("closing_balance_debit")),
                format_money(line.get("closing_balance_credit")),
            ])
        self._set_table(["Akun", "Debit", "Kredit"], rows)
        balanced = "✅ Balance" if data.get("is_balanced") else "⚠️ Tidak balance"
        self.summary_label.setText(
            f"Total Debit: {format_money(data.get('total_debit'))}   |   "
            f"Total Kredit: {format_money(data.get('total_credit'))}   |   {balanced}"
        )
        self.status_label.setText(f"{len(lines)} akun ditampilkan.")


class BalanceSheetTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=False)

    def generate(self) -> None:
        self.status_label.setText("Memuat neraca...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/balance-sheet", params=self._params())

    def _on_data(self, data: dict[str, Any]) -> None:
        rows = []
        for section_key, section_label in [("assets", "AKTIVA"), ("liabilities", "KEWAJIBAN"), ("equity", "EKUITAS")]:
            section = data.get(section_key) or {}
            rows.append([f"— {section_label} —", ""])
            for line in section.get("lines", []):
                rows.append([line.get("account_name", ""), format_money(line.get("amount") or line.get("balance"))])
            rows.append([f"Total {section_label}", format_money(section.get("total"))])
        self._set_table(["Akun", "Jumlah"], rows)
        balanced = "✅ Balance" if data.get("is_balanced") else "⚠️ Tidak balance"
        self.summary_label.setText(
            f"Total Aktiva: {format_money(data.get('total_assets'))}   |   "
            f"Total Kewajiban + Ekuitas: {format_money(data.get('total_liabilities_equity'))}   |   {balanced}"
        )
        self.status_label.setText("Neraca dimuat.")


class IncomeStatementTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=True)

    def generate(self) -> None:
        self.status_label.setText("Memuat laporan laba rugi...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/income-statement", params=self._params())

    def _on_data(self, data: dict[str, Any]) -> None:
        rows = []
        sections = [
            ("PENDAPATAN", data.get("revenues", [])),
            ("HARGA POKOK PENJUALAN", data.get("cost_of_goods_sold", [])),
            ("BEBAN OPERASIONAL", data.get("operating_expenses", [])),
            ("PENDAPATAN LAIN-LAIN", data.get("other_income", [])),
            ("BEBAN LAIN-LAIN", data.get("other_expenses", [])),
        ]
        for label, lines in sections:
            if not lines:
                continue
            rows.append([f"— {label} —", ""])
            for line in lines:
                rows.append([line.get("account_name", ""), format_money(line.get("amount"))])
        self._set_table(["Akun", "Jumlah"], rows)
        self.summary_label.setText(
            f"Laba Kotor: {format_money(data.get('gross_profit'))}   |   "
            f"Laba Operasi: {format_money(data.get('operating_income'))}   |   "
            f"Laba Bersih: {format_money(data.get('net_income'))}"
        )
        self.status_label.setText(
            f"Margin kotor {data.get('gross_margin', '-')}%  |  Margin bersih {data.get('net_margin', '-')}%"
        )


class CashFlowTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=True)

    def generate(self) -> None:
        self.status_label.setText("Memuat arus kas...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/cash-flow", params=self._params())

    def _on_data(self, data: dict[str, Any]) -> None:
        rows = []
        for section_key, label in [
            ("operating_activities", "AKTIVITAS OPERASI"),
            ("investing_activities", "AKTIVITAS INVESTASI"),
            ("financing_activities", "AKTIVITAS PENDANAAN"),
        ]:
            lines = data.get(section_key) or []
            if not lines:
                continue
            rows.append([f"— {label} —", ""])
            for line in lines:
                if isinstance(line, dict):
                    rows.append([line.get("description", line.get("account_name", "")), format_money(line.get("amount"))])
        self._set_table(["Keterangan", "Jumlah"], rows)
        self.summary_label.setText(
            f"Kas Awal: {format_money(data.get('beginning_cash'))}   |   "
            f"Kas Akhir: {format_money(data.get('ending_cash'))}   |   "
            f"Perubahan Bersih: {format_money(data.get('net_change_in_cash'))}"
        )
        self.status_label.setText("Laporan arus kas dimuat.")
