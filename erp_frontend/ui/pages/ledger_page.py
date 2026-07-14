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
    QAbstractItemView,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
        self.tabs.addTab(GlEntriesTab(), "GL Entries (Drill-down)")
        self.tabs.addTab(EquityStatementTab(), "Perubahan Ekuitas")
        self.tabs.addTab(FinancialRatiosTab(), "Rasio Keuangan")
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


# ==========================================================================
# GL Entries drill-down — sebelumnya tidak ada, padahal penting untuk
# menelusuri detail transaksi di balik angka laporan keuangan.
# ==========================================================================
class GlEntriesTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Akun (UUID, opsional):"))
        self.account_edit = QLineEdit()
        self.account_edit.setMaximumWidth(280)
        filter_row.addWidget(self.account_edit)
        filter_row.addWidget(QLabel("Dari:"))
        self.start_date = QDateEdit(QDate.currentDate().addMonths(-1))
        self.start_date.setCalendarPopup(True)
        filter_row.addWidget(self.start_date)
        filter_row.addWidget(QLabel("Sampai:"))
        self.end_date = QDateEdit(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        filter_row.addWidget(self.end_date)
        load_btn = QPushButton("Tampilkan")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        filter_row.addWidget(load_btn)
        filter_row.addStretch()
        outer.addLayout(filter_row)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Tgl Posting", "No. Jurnal", "Akun", "Debit", "Kredit", "Deskripsi", "Cost Center", "Referensi"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        params = {
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date.date().toString("yyyy-MM-dd"),
            "page_size": 500,
        }
        if self.account_edit.text().strip():
            params["account_id"] = self.account_edit.text().strip()
        self.status_label.setText("Memuat GL entries...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/entries", params=params)

    def _on_data(self, payload) -> None:
        from core.formatting import extract_list
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            values = [
                format_date(e.get("posting_date", "")),
                e.get("journal_number", ""),
                f"{e.get('account_code', '')} — {e.get('account_name', '')}",
                format_money(e.get("debit_amount", 0)) if e.get("debit_amount") else "-",
                format_money(e.get("credit_amount", 0)) if e.get("credit_amount") else "-",
                e.get("description", "") or "-",
                e.get("cost_center", "") or "-",
                e.get("reference_number", "") or "-",
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} baris entry ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class EquityStatementTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=True)

    def generate(self) -> None:
        self.status_label.setText("Memuat laporan perubahan ekuitas...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/equity-statement", params=self._params())

    def _on_data(self, data) -> None:
        rows = []
        for line in data.get("lines", []):
            rows.append([
                line.get("component", ""),
                format_money(line.get("closing_balance")),
            ])
        self._set_table(["Komponen Ekuitas", "Saldo Akhir"], rows)
        self.summary_label.setText(
            f"Ekuitas Awal: {format_money(data.get('opening_total_equity'))}   |   "
            f"Laba Bersih: {format_money(data.get('net_income'))}   |   "
            f"Dividen: {format_money(data.get('dividends_declared'))}   |   "
            f"Ekuitas Akhir: {format_money(data.get('closing_total_equity'))}"
        )
        self.status_label.setText("Laporan perubahan ekuitas dimuat.")


# ==========================================================================
class FinancialRatiosTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Per Tanggal:"))
        self.as_of_date = QDateEdit(QDate.currentDate())
        self.as_of_date.setCalendarPopup(True)
        row.addWidget(self.as_of_date)
        load_btn = QPushButton("Hitung Rasio")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Rasio", "Nilai"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        self.status_label.setText("Menghitung rasio keuangan...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/financial-ratios",
                  params={"as_of_date": self.as_of_date.date().toString("yyyy-MM-dd")})

    def _on_data(self, data) -> None:
        labels = {
            "current_ratio": "Current Ratio (Likuiditas)",
            "quick_ratio": "Quick Ratio (Acid Test)",
            "cash_ratio": "Cash Ratio",
            "debt_to_equity": "Debt to Equity",
            "debt_to_assets": "Debt to Assets",
            "interest_coverage": "Interest Coverage",
            "gross_margin": "Gross Margin (%)",
            "operating_margin": "Operating Margin (%)",
            "net_margin": "Net Margin (%)",
            "return_on_assets": "Return on Assets (ROA)",
            "return_on_equity": "Return on Equity (ROE)",
            "asset_turnover": "Asset Turnover",
            "inventory_turnover": "Inventory Turnover",
            "receivable_turnover": "Receivable Turnover",
            "payable_turnover": "Payable Turnover",
        }
        rows = []
        for key, label in labels.items():
            val = data.get(key)
            if val is not None:
                rows.append([label, f"{val:.2f}" if isinstance(val, (int, float)) else str(val)])
        self.table.setRowCount(len(rows))
        for r, (label, val) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(label))
            self.table.setItem(r, 1, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self.status_label.setText("Rasio keuangan dihitung.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
