"""
ui/pages/ledger_page.py
========================
General Ledger & Laporan Keuangan (standar PSAK/SAK Indonesia).

7 tab laporan (read-only, endpoint /ledger/ledger/*):
    1. Neraca Saldo (Trial Balance)
    2. Neraca (Balance Sheet) — Lancar/Tidak Lancar, Periode Lalu, Δ
    3. Laba Rugi — multiple-step, Periode Lalu, Δ
    4. Arus Kas — metode tidak langsung
    5. GL Entries — filter akun (dropdown COA), rentang tanggal, export CSV
    6. Perubahan Ekuitas — per komponen
    7. Rasio Keuangan — Likuiditas/Solvabilitas/Profitabilitas/Aktivitas

KONVENSI
    - QTreeWidget: grup = parent (bold), akun = child.
    - Angka negatif dalam tanda kurung: (1.234.567).
    - Kolom "Periode Lalu" & "Δ" tersedia di Neraca & Laba Rugi.

FIX v2 (default tanggal):
    Sebelumnya default tanggal = "1 bulan terakhir" (mis. 12 Sep - 12 Okt).
    Akibatnya jurnal yang diposting setelah tanggal tersebut (mis. 25-30 Okt)
    tidak muncul di Laba Rugi — user lihat "Beban Operasional Rp 0" padahal
    data ada di DB. Sekarang default tanggal = "1 Jan tahun ini s/d hari ini",
    cukup luas untuk menangkap semua transaksi tahun berjalan. Semua tab
    (Neraca, Laba Rugi, Arus Kas, Ekuitas, Rasio, GL Entries) memakai default
    yang SAMA agar laporan konsisten.
"""
from __future__ import annotations

import csv
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

BASE = "/ledger/ledger"

GROUP_BG = QColor("#EDE9FE")
GROUP_FG = QColor("#4C1D95")
TOTAL_BG = QColor("#F5F3FF")
NEG_FG = QColor("#B91C1C")


# ==========================================================================
# Default tanggal (konsisten di semua tab)
# ==========================================================================
def _default_start_date() -> QDate:
    """Awal tahun berjalan (1 Januari)."""
    today = QDate.currentDate()
    return QDate(today.year(), 1, 1)


def _default_end_date() -> QDate:
    """Hari ini."""
    return QDate.currentDate()


# ==========================================================================
# Helper
# ==========================================================================
def _money_or_dash(value: Any, currency: str = "IDR") -> str:
    if value in (None, "", 0, "0"):
        return "-"
    return format_money(value, currency)


def _money_paren(value: Any, currency: str = "IDR") -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    if num == 0:
        return "-"
    if num < 0:
        return f"({format_money(abs(num), currency).replace('Rp ', '').strip()})"
    return format_money(num, currency)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _style_group_item(item: QTreeWidgetItem, cols: int) -> None:
    font = QFont()
    font.setBold(True)
    for c in range(cols):
        item.setBackground(c, GROUP_BG)
        item.setForeground(c, GROUP_FG)
        item.setFont(c, font)


def _style_total_item(item: QTreeWidgetItem, cols: int) -> None:
    font = QFont()
    font.setBold(True)
    for c in range(cols):
        item.setBackground(c, TOTAL_BG)
        item.setFont(c, font)


# ==========================================================================
# Basis tab laporan
# ==========================================================================
class _ReportTabBase(QWidget):
    def __init__(self, needs_range: bool = False, tree_columns: list[str] | None = None):
        super().__init__()
        self.needs_range = needs_range
        self._currency = "IDR"
        self._tree_columns = tree_columns or ["Akun", "Jumlah"]
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        filter_row = QHBoxLayout()
        if self.needs_range:
            filter_row.addWidget(QLabel("Dari:"))
            self.start_date = QDateEdit(_default_start_date())
            self.start_date.setCalendarPopup(True)
            self.start_date.setDisplayFormat("dd/MM/yyyy")
            filter_row.addWidget(self.start_date)
            filter_row.addWidget(QLabel("Sampai:"))
            self.end_date = QDateEdit(_default_end_date())
            self.end_date.setCalendarPopup(True)
            self.end_date.setDisplayFormat("dd/MM/yyyy")
            filter_row.addWidget(self.end_date)
        else:
            filter_row.addWidget(QLabel("Per Tanggal:"))
            self.as_of_date = QDateEdit(_default_end_date())
            self.as_of_date.setCalendarPopup(True)
            self.as_of_date.setDisplayFormat("dd/MM/yyyy")
            filter_row.addWidget(self.as_of_date)

        gen_btn = QPushButton("Tampilkan")
        gen_btn.setObjectName("primaryButton")
        gen_btn.clicked.connect(self.generate)
        filter_row.addWidget(gen_btn)

        self.compare_check = None
        if self._supports_compare():
            self.compare_check = QCheckBox("Bandingkan periode lalu")
            self.compare_check.stateChanged.connect(lambda _s: self.generate())
            filter_row.addWidget(self.compare_check)

        filter_row.addStretch()

        self.export_btn = QPushButton("⬇ Export CSV")
        self.export_btn.clicked.connect(self._export_csv)
        filter_row.addWidget(self.export_btn)
        outer.addLayout(filter_row)

        self.summary_frame = QFrame()
        self.summary_frame.setStyleSheet(
            "QFrame { background:#F9FAFB; border:1px solid #E5E7EB; border-radius:8px; }"
        )
        summary_layout = QHBoxLayout(self.summary_frame)
        summary_layout.setContentsMargins(12, 6, 12, 6)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("border:none; font-weight:600; color:#374151;")
        summary_layout.addWidget(self.summary_label)
        summary_layout.addStretch()
        outer.addWidget(self.summary_frame)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self._tree_columns))
        self.tree.setHeaderLabels(self._tree_columns)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(self._tree_columns)):
            hdr.setSectionResizeMode(c, QHeaderView.Interactive)
            self.tree.setColumnWidth(c, 160)
        self.tree.setStyleSheet(
            "QTreeWidget::item { padding:4px 2px; }"
            "QTreeWidget::item:hover { background:#F3F4F6; }"
            "QTreeWidget::item:selected { background:#7C3AED; color:white; }"
        )
        outer.addWidget(self.tree, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _supports_compare(self) -> bool:
        return False

    def _params(self) -> dict[str, Any]:
        if self.needs_range:
            return {
                "start_date": self.start_date.date().toString("yyyy-MM-dd"),
                "end_date": self.end_date.date().toString("yyyy-MM-dd"),
            }
        return {"as_of_date": self.as_of_date.date().toString("yyyy-MM-dd")}

    def generate(self) -> None:
        raise NotImplementedError

    def _clear(self) -> None:
        self.tree.clear()

    def _add_group(self, label: str, values: list[str] | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label] + (values or [""] * (len(self._tree_columns) - 1)))
        _style_group_item(item, len(self._tree_columns))
        self.tree.addTopLevelItem(item)
        return item

    def _add_line(self, parent: QTreeWidgetItem | None, label: str,
                  values: list[str]) -> QTreeWidgetItem:
        row = [label] + values
        item = QTreeWidgetItem(row) if parent is None else QTreeWidgetItem(parent, row)
        for c in range(1, len(self._tree_columns)):
            item.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            txt = values[c - 1] if c - 1 < len(values) else ""
            if txt.startswith("("):
                item.setForeground(c, NEG_FG)
        if parent is None:
            self.tree.addTopLevelItem(item)
        return item

    def _add_total(self, label: str, values: list[str],
                   parent: QTreeWidgetItem | None = None) -> QTreeWidgetItem:
        row = [label] + values
        item = QTreeWidgetItem(parent, row) if parent else QTreeWidgetItem(row)
        _style_total_item(item, len(self._tree_columns))
        for c in range(1, len(self._tree_columns)):
            item.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            txt = values[c - 1] if c - 1 < len(values) else ""
            if txt.startswith("("):
                item.setForeground(c, NEG_FG)
        if not parent:
            self.tree.addTopLevelItem(item)
        return item

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _export_csv(self) -> None:
        if self.tree.topLevelItemCount() == 0:
            QMessageBox.information(self, "Info", "Belum ada data untuk diexport.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan CSV", f"{self.__class__.__name__}.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([self.tree.headerItem().text(c) for c in range(self.tree.columnCount())])

                def _walk(item: QTreeWidgetItem, depth: int) -> None:
                    row = ["  " * depth + item.text(0)] + [
                        item.text(c) for c in range(1, self.tree.columnCount())
                    ]
                    w.writerow(row)
                    for i in range(item.childCount()):
                        _walk(item.child(i), depth + 1)

                for i in range(self.tree.topLevelItemCount()):
                    _walk(self.tree.topLevelItem(i), 0)
            self.status_label.setText(f"Export ke {path}")
        except OSError as exc:
            QMessageBox.warning(self, "Gagal Export", str(exc))


# ==========================================================================
# 1. TRIAL BALANCE
# ==========================================================================
class TrialBalanceTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=False,
                         tree_columns=["Kode / Nama Akun", "Debit", "Kredit"])

    def generate(self) -> None:
        self.status_label.setText("Memuat neraca saldo...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/trial-balance", params=self._params())

    def _on_data(self, data: dict[str, Any]) -> None:
        self._clear()
        data = data or {}
        lines = data.get("lines", [])
        for line in lines:
            self._add_line(
                None,
                f"{line.get('account_code', '')} — {line.get('account_name', '')}",
                [_money_or_dash(line.get("closing_balance_debit")),
                 _money_or_dash(line.get("closing_balance_credit"))],
            )
        self._add_total("TOTAL", [
            format_money(data.get("total_debit", 0)),
            format_money(data.get("total_credit", 0)),
        ])
        balanced = data.get("is_balanced")
        status = "✅ Balance" if balanced else "⚠️ Tidak balance"
        color = "#059669" if balanced else "#B91C1C"
        self.summary_label.setText(
            f"Total Debit: <b>{format_money(data.get('total_debit', 0))}</b> &nbsp;|&nbsp; "
            f"Total Kredit: <b>{format_money(data.get('total_credit', 0))}</b> &nbsp;|&nbsp; "
            f"<span style='color:{color}'>{status}</span>"
        )
        self.status_label.setText(f"{len(lines)} akun.")


# ==========================================================================
# 2. BALANCE SHEET
# ==========================================================================
class BalanceSheetTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=False,
                         tree_columns=["Akun", "Periode Ini", "Periode Lalu", "Δ"])

    def _supports_compare(self) -> bool:
        return True

    def _params(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.date().toString("yyyy-MM-dd"),
            "include_comparatives": bool(self.compare_check and self.compare_check.isChecked()),
        }

    def generate(self) -> None:
        self.status_label.setText("Memuat neraca...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/balance-sheet", params=self._params())

    def _on_data(self, data: dict[str, Any]) -> None:
        self._clear()
        data = data or {}

        self._render_section(data.get("assets", {}), "ASET", ["current", "fixed", "other"])
        self._render_section(data.get("liabilities", {}), "KEWAJIBAN", ["current", "long_term"])
        self._render_section(data.get("equity", {}), "EKUITAS", ["equity"])

        ta = _safe_float(data.get("total_assets"))
        tle = _safe_float(data.get("total_liabilities_equity"))
        diff = ta - tle
        balanced = abs(diff) < 0.01
        status = "✅ Balance" if balanced else f"⚠️ Selisih {format_money(diff)}"
        color = "#059669" if balanced else "#B91C1C"
        self.summary_label.setText(
            f"Total Aset: <b>{format_money(ta)}</b> &nbsp;|&nbsp; "
            f"Kewajiban + Ekuitas: <b>{format_money(tle)}</b> &nbsp;|&nbsp; "
            f"<span style='color:{color}'>{status}</span>"
        )
        self.status_label.setText("Neraca dimuat.")

    def _render_section(self, section: dict[str, Any], label: str,
                        klass_order: list[str]) -> None:
        root = self._add_group(f"— {label} —")
        lines = section.get("lines", []) or []
        # Kelompokkan per klasifikasi
        buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in klass_order}
        for line in lines:
            k = line.get("classification", klass_order[0])
            buckets.setdefault(k, []).append(line)

        klass_labels = {
            "current": "Aset Lancar" if label == "ASET" else "Kewajiban Jangka Pendek",
            "fixed": "Aset Tetap",
            "other": "Aset Lain-lain",
            "long_term": "Kewajiban Jangka Panjang",
            "equity": "Ekuitas",
        }
        for k in klass_order:
            items = buckets.get(k, [])
            if not items:
                continue
            sub = QTreeWidgetItem(root, [klass_labels.get(k, k), "", "", ""])
            _style_group_item(sub, len(self._tree_columns))
            subtotal_cur = 0.0
            subtotal_prev = 0.0
            for line in items:
                cur = _safe_float(line.get("amount"))
                prev = _safe_float(line.get("amount_previous"))
                subtotal_cur += cur
                subtotal_prev += prev
                self._add_line(sub, line.get("account_name", ""), [
                    _money_paren(cur), _money_paren(prev), _money_paren(cur - prev),
                ])
            self._add_total(f"Subtotal {klass_labels.get(k, k)}", [
                format_money(subtotal_cur), format_money(subtotal_prev),
                _money_paren(subtotal_cur - subtotal_prev),
            ], parent=sub)
            sub.setExpanded(True)

        total_cur = _safe_float(section.get("total"))
        self._add_total(f"Total {label.title()}", [
            format_money(total_cur), "-", "-",
        ], parent=root)
        root.setExpanded(True)


# ==========================================================================
# 3. INCOME STATEMENT
# ==========================================================================
class IncomeStatementTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=True,
                         tree_columns=["Akun", "Periode Ini", "Periode Lalu", "Δ"])

    def _supports_compare(self) -> bool:
        return True

    def _params(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date.date().toString("yyyy-MM-dd"),
            "period": "custom",
            "comparison": "previous_period" if (self.compare_check and self.compare_check.isChecked()) else "none",
        }

    def generate(self) -> None:
        self.status_label.setText("Memuat laporan laba rugi...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/income-statement", params=self._params())

    def _render_lines(self, parent: QTreeWidgetItem, lines: list[dict[str, Any]],
                      sign: int = 1) -> None:
        for line in lines or []:
            cur = _safe_float(line.get("current_period")) * sign
            prev = _safe_float(line.get("prior_period")) * sign
            self._add_line(parent, line.get("account_name", ""), [
                _money_paren(cur), _money_paren(prev), _money_paren(cur - prev),
            ])

    def _on_data(self, data: dict[str, Any]) -> None:
        self._clear()
        data = data or {}

        # Pendapatan
        rev_root = self._add_group("— PENDAPATAN —")
        self._render_lines(rev_root, data.get("revenues", []))
        self._add_total("Total Pendapatan", [
            format_money(sum(_safe_float(r.get("current_period")) for r in data.get("revenues", []) or [])),
            "-", "-",
        ], parent=rev_root)
        rev_root.setExpanded(True)

        # HPP
        cogs_root = self._add_group("— HARGA POKOK PENJUALAN —")
        self._render_lines(cogs_root, data.get("cost_of_goods_sold", []))
        self._add_total("Total HPP", [
            format_money(sum(_safe_float(r.get("current_period")) for r in data.get("cost_of_goods_sold", []) or [])),
            "-", "-",
        ], parent=cogs_root)
        cogs_root.setExpanded(True)

        # Laba Kotor
        self._add_total("LABA KOTOR", [format_money(data.get("gross_profit", 0)), "-", "-"])

        # Beban Operasional
        opex_root = self._add_group("— BEBAN OPERASIONAL —")
        self._render_lines(opex_root, data.get("operating_expenses", []))
        self._add_total("Total Beban Operasional", [
            format_money(sum(_safe_float(r.get("current_period")) for r in data.get("operating_expenses", []) or [])),
            "-", "-",
        ], parent=opex_root)
        opex_root.setExpanded(True)

        # Laba Operasi
        self._add_total("LABA OPERASI", [format_money(data.get("operating_income", 0)), "-", "-"])

        # Lain-lain
        other_root = self._add_group("— PENDAPATAN / BEBAN LAIN-LAIN —")
        self._render_lines(other_root, data.get("other_income", []), sign=1)
        self._render_lines(other_root, data.get("other_expenses", []), sign=-1)
        other_root.setExpanded(True)

        # Laba Sebelum Pajak
        self._add_total("LABA SEBELUM PAJAK",
                        [format_money(data.get("income_before_tax", 0)), "-", "-"])

        # Pajak
        tax = _safe_float(data.get("tax_expense"))
        if tax:
            self._add_line(None, "Beban Pajak Penghasilan",
                           [format_money(tax), "-", "-"])

        # Laba Bersih
        self._add_total("LABA BERSIH", [format_money(data.get("net_income", 0)), "-", "-"])

        # EBITDA
        ebitda = data.get("ebitda")
        if ebitda is not None:
            self._add_line(None, "EBITDA", [format_money(ebitda), "-", "-"])

        # Summary
        gp = data.get("gross_profit", 0)
        oi = data.get("operating_income", 0)
        ni = data.get("net_income", 0)
        gm = data.get("gross_margin")
        om = data.get("operating_margin")
        nm = data.get("net_margin")
        self.summary_label.setText(
            f"Laba Kotor: <b>{format_money(gp)}</b> ({gm if gm is not None else '-'}%) &nbsp;|&nbsp; "
            f"Laba Operasi: <b>{format_money(oi)}</b> ({om if om is not None else '-'}%) &nbsp;|&nbsp; "
            f"Laba Bersih: <b>{format_money(ni)}</b> ({nm if nm is not None else '-'}%)"
        )
        self.status_label.setText("Laporan laba rugi dimuat.")


# ==========================================================================
# 4. CASH FLOW
# ==========================================================================
class CashFlowTab(_ReportTabBase):
    def __init__(self):
        super().__init__(needs_range=True, tree_columns=["Keterangan", "Jumlah"])

    def generate(self) -> None:
        self.status_label.setText("Memuat arus kas...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/cash-flow", params=self._params())

    def _on_data(self, data: dict[str, Any]) -> None:
        self._clear()
        data = data or {}

        # Operasi
        op_root = self._add_group("— AKTIVITAS OPERASI —")
        for line in data.get("operating_activities", []) or []:
            self._add_line(op_root, line.get("description", ""),
                           [_money_paren(line.get("amount"))])
        self._add_total("Kas Neto dari Aktivitas Operasi",
                        [format_money(data.get("net_cash_operating", 0))], parent=op_root)
        op_root.setExpanded(True)

        # Investasi
        inv_root = self._add_group("— AKTIVITAS INVESTASI —")
        for line in data.get("investing_activities", []) or []:
            self._add_line(inv_root, line.get("description", ""),
                           [_money_paren(line.get("amount"))])
        self._add_total("Kas Neto dari Aktivitas Investasi",
                        [format_money(data.get("net_cash_investing", 0))], parent=inv_root)
        inv_root.setExpanded(True)

        # Pendanaan
        fin_root = self._add_group("— AKTIVITAS PENDANAAN —")
        for line in data.get("financing_activities", []) or []:
            self._add_line(fin_root, line.get("description", ""),
                           [_money_paren(line.get("amount"))])
        self._add_total("Kas Neto dari Aktivitas Pendanaan",
                        [format_money(data.get("net_cash_financing", 0))], parent=fin_root)
        fin_root.setExpanded(True)

        # Rekonsiliasi
        recon_root = self._add_group("— REKONSILIASI KAS —")
        begin = _safe_float(data.get("beginning_cash"))
        net_change = _safe_float(data.get("net_increase_decrease"))
        end = _safe_float(data.get("ending_cash"))
        self._add_line(recon_root, "Kas & Setara Kas Awal Periode", [format_money(begin)])
        self._add_line(recon_root, "Kenaikan/(Penurunan) Kas Neto", [_money_paren(net_change)])
        self._add_total("Kas & Setara Kas Akhir Periode",
                        [format_money(end)], parent=recon_root)
        recon_root.setExpanded(True)

        fcf = data.get("free_cash_flow")
        if fcf is not None:
            self._add_line(None, "Free Cash Flow", [format_money(fcf)])

        self.summary_label.setText(
            f"Kas Awal: <b>{format_money(begin)}</b> &nbsp;|&nbsp; "
            f"Perubahan Neto: <b>{format_money(net_change)}</b> &nbsp;|&nbsp; "
            f"Kas Akhir: <b>{format_money(end)}</b>"
        )
        self.status_label.setText("Laporan arus kas dimuat.")


# ==========================================================================
# 5. GL ENTRIES
# ==========================================================================
class GlEntriesTab(QWidget):
    def __init__(self):
        super().__init__()
        self._accounts: list[dict[str, Any]] = []
        self._entries: list[dict[str, Any]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Akun:"))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(280)
        filter_row.addWidget(self.account_combo)
        filter_row.addWidget(QLabel("Dari:"))
        self.start_date = QDateEdit(_default_start_date())
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("dd/MM/yyyy")
        filter_row.addWidget(self.start_date)
        filter_row.addWidget(QLabel("Sampai:"))
        self.end_date = QDateEdit(_default_end_date())
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("dd/MM/yyyy")
        filter_row.addWidget(self.end_date)
        load_btn = QPushButton("Tampilkan")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load_entries)
        filter_row.addWidget(load_btn)
        filter_row.addStretch()
        export_btn = QPushButton("⬇ Export CSV")
        export_btn.clicked.connect(self._export_csv)
        filter_row.addWidget(export_btn)
        outer.addLayout(filter_row)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("padding:4px 0; color:#374151;")
        outer.addWidget(self.summary_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Tgl Posting", "No. Jurnal", "Akun", "Debit", "Kredit",
             "Deskripsi", "Cost Center", "Referensi"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

        self._load_accounts()

    def _load_accounts(self) -> None:
        run_task(
            api_client.get,
            on_success=self._on_accounts_loaded,
            on_error=lambda m: self.status_label.setText(f"Gagal memuat akun: {m}"),
            path="/coa/chart-of-accounts/accounts",
            params={"page_size": 5000, "include_inactive": True},
        )

    def _on_accounts_loaded(self, payload: Any) -> None:
        self._accounts = extract_list(payload)
        self.account_combo.clear()
        self.account_combo.addItem("— Semua Akun —", "")
        for a in sorted(self._accounts, key=lambda x: str(x.get("account_code", ""))):
            self.account_combo.addItem(
                f"{a.get('account_code', '')} — {a.get('account_name', '')}",
                a.get("id") or "",
            )
        self.status_label.setText(f"{len(self._accounts)} akun tersedia.")

    def _load_entries(self) -> None:
        params = {
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date.date().toString("yyyy-MM-dd"),
            "page_size": 500,
        }
        acc_id = self.account_combo.currentData()
        if acc_id:
            params["account_id"] = acc_id
        self.status_label.setText("Memuat GL entries...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/entries", params=params)

    def _on_data(self, payload: Any) -> None:
        self._entries = extract_list(payload)
        self.table.setRowCount(len(self._entries))
        total_debit = 0.0
        total_credit = 0.0
        for r, e in enumerate(self._entries):
            d = _safe_float(e.get("debit_amount"))
            c = _safe_float(e.get("credit_amount"))
            total_debit += d
            total_credit += c
            values = [
                format_date(e.get("posting_date")),
                e.get("journal_number", ""),
                f"{e.get('account_code', '')} — {e.get('account_name', '')}",
                format_money(d) if d else "-",
                format_money(c) if c else "-",
                e.get("description", "") or "-",
                e.get("cost_center", "") or "-",
                e.get("reference_number", "") or "-",
            ]
            for col, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                if col in (3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, col, item)
        self.table.resizeColumnsToContents()

        self.summary_label.setText(
            f"<b>{len(self._entries)}</b> baris &nbsp;|&nbsp; "
            f"Total Debit: <b>{format_money(total_debit)}</b> &nbsp;|&nbsp; "
            f"Total Kredit: <b>{format_money(total_credit)}</b> &nbsp;|&nbsp; "
            f"Selisih: <b>{format_money(total_debit - total_credit)}</b>"
        )
        self.status_label.setText(f"{len(self._entries)} entry ditemukan.")

    def _export_csv(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "Info", "Belum ada data untuk diexport.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Simpan CSV", "gl_entries.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Tgl Posting", "No. Jurnal", "Akun", "Debit", "Kredit",
                            "Deskripsi", "Cost Center", "Referensi"])
                for e in self._entries:
                    w.writerow([
                        format_date(e.get("posting_date")),
                        e.get("journal_number", ""),
                        f"{e.get('account_code', '')} — {e.get('account_name', '')}",
                        e.get("debit_amount", ""),
                        e.get("credit_amount", ""),
                        e.get("description", ""),
                        e.get("cost_center", ""),
                        e.get("reference_number", ""),
                    ])
            self.status_label.setText(f"Export ke {path}")
        except OSError as exc:
            QMessageBox.warning(self, "Gagal Export", str(exc))

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
# 6. PERUBAHAN EKUITAS
# ==========================================================================
class EquityStatementTab(_ReportTabBase):
    def __init__(self):
        super().__init__(
            needs_range=True,
            tree_columns=[
                "Komponen Ekuitas", "Saldo Awal", "Penambahan",
                "Pengurangan", "Perubahan", "Saldo Akhir",
            ],
        )

    def generate(self) -> None:
        self.status_label.setText("Memuat laporan perubahan ekuitas...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/equity-statement", params=self._params())

    def _on_data(self, data: dict[str, Any]) -> None:
        self._clear()
        data = data or {}

        for line in data.get("lines", []) or []:
            self._add_line(None, line.get("component", ""), [
                _money_paren(line.get("opening_balance")),
                _money_paren(line.get("additions")),
                _money_paren(line.get("deductions")),
                _money_paren(line.get("change")),
                format_money(line.get("closing_balance")),
            ])

        self._add_group("— REKAP PERUBAHAN —")
        self._add_line(None, "Laba Bersih Periode",
                       ["-", "-", "-", format_money(data.get("net_income", 0)),
                        format_money(data.get("net_income", 0))])
        self._add_line(None, "Penghasilan Komprehensif Lain",
                       ["-", "-", "-",
                        format_money(data.get("other_comprehensive_income", 0)),
                        format_money(data.get("other_comprehensive_income", 0))])
        self._add_line(None, "Dividen yang Diumumkan",
                       ["-", "-", "-",
                        f"({format_money(data.get('dividends_declared', 0)).replace('Rp ', '')})",
                        f"({format_money(data.get('dividends_declared', 0)).replace('Rp ', '')})"])
        self._add_line(None, "Perubahan Modal",
                       ["-", format_money(data.get("capital_changes", 0)), "-", "-", "-"])

        self._add_total("TOTAL EKUITAS AWAL", [
            format_money(data.get("opening_total_equity", 0)), "-", "-", "-", "-",
        ])
        self._add_total("TOTAL EKUITAS AKHIR", [
            "-", "-", "-", "-", format_money(data.get("closing_total_equity", 0)),
        ])

        self.summary_label.setText(
            f"Ekuitas Awal: <b>{format_money(data.get('opening_total_equity', 0))}</b> &nbsp;|&nbsp; "
            f"Laba Bersih: <b>{format_money(data.get('net_income', 0))}</b> &nbsp;|&nbsp; "
            f"Dividen: <b>{format_money(data.get('dividends_declared', 0))}</b> &nbsp;|&nbsp; "
            f"Ekuitas Akhir: <b>{format_money(data.get('closing_total_equity', 0))}</b>"
        )
        self.status_label.setText("Laporan perubahan ekuitas dimuat.")


# ==========================================================================
# 7. RASIO KEUANGAN
# ==========================================================================
class FinancialRatiosTab(_ReportTabBase):
    RATIO_GROUPS = [
        ("LIKUIDITAS", [
            ("current_ratio", "Current Ratio"),
            ("quick_ratio", "Quick Ratio (Acid Test)"),
            ("cash_ratio", "Cash Ratio"),
        ]),
        ("SOLVABILITAS", [
            ("debt_to_equity", "Debt to Equity (DER)"),
            ("debt_to_assets", "Debt to Assets (DAR)"),
            ("interest_coverage", "Interest Coverage"),
        ]),
        ("PROFITABILITAS", [
            ("gross_margin", "Gross Margin (%)"),
            ("operating_margin", "Operating Margin (%)"),
            ("net_margin", "Net Margin (%)"),
            ("return_on_assets", "Return on Assets (ROA)"),
            ("return_on_equity", "Return on Equity (ROE)"),
        ]),
        ("AKTIVITAS", [
            ("asset_turnover", "Asset Turnover"),
            ("inventory_turnover", "Inventory Turnover"),
            ("receivable_turnover", "Receivable Turnover"),
            ("payable_turnover", "Payable Turnover"),
        ]),
    ]

    def __init__(self):
        super().__init__(needs_range=False,
                         tree_columns=["Rasio", "Nilai", "Interpretasi"])

    def generate(self) -> None:
        self.status_label.setText("Menghitung rasio keuangan...")
        run_task(api_client.get, on_success=self._on_data, on_error=self._on_error,
                  path=f"{BASE}/financial-ratios", params=self._params())

    def _on_data(self, data: Any) -> None:
        self._clear()
        data = data or {}
        for group_label, ratios in self.RATIO_GROUPS:
            group_item = self._add_group(f"— {group_label} —")
            for key, label in ratios:
                val = data.get(key)
                if val is None:
                    continue
                formatted, interp = self._format_ratio(key, val)
                self._add_line(group_item, label, [formatted, interp])
            group_item.setExpanded(True)

        self.summary_label.setText(
            f"Per Tanggal: <b>{self.as_of_date.date().toString('dd/MM/yyyy')}</b> &nbsp;|&nbsp; "
            f"<b>{sum(1 for g, rs in self.RATIO_GROUPS for r, _ in rs if data.get(r) is not None)}</b> "
            "rasio dihitung."
        )
        self.status_label.setText("Rasio keuangan dimuat.")

    @staticmethod
    def _format_ratio(key: str, val: Any) -> tuple[str, str]:
        try:
            num = float(val)
        except (TypeError, ValueError):
            return str(val), ""

        if key in ("gross_margin", "operating_margin", "net_margin"):
            return f"{num:.2f}%", ("Sehat" if num > 10 else "Rendah")
        if key in ("debt_to_equity", "debt_to_assets", "interest_coverage"):
            return f"{num:.2f}x", ("Sehat" if num < 2 else "Berisiko")
        if key in ("current_ratio", "quick_ratio", "cash_ratio"):
            return f"{num:.2f}x", ("Sehat" if num >= 1 else "Kurang")
        if key in ("return_on_assets", "return_on_equity"):
            return f"{num:.2f}%", ("Baik" if num > 5 else "Rendah")
        return f"{num:.2f}", ""


# ==========================================================================
# Halaman utama
# ==========================================================================
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

        subtitle = QLabel("Laporan standar PSAK/SAK: Neraca, Laba Rugi, Arus Kas, "
                          "Perubahan Ekuitas, dan Rasio Keuangan.")
        subtitle.setStyleSheet("color:#6B7280; font-size:12px; padding-bottom:6px;")
        outer.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.trial_balance_tab = TrialBalanceTab()
        self.balance_sheet_tab = BalanceSheetTab()
        self.income_statement_tab = IncomeStatementTab()
        self.cash_flow_tab = CashFlowTab()
        self.gl_entries_tab = GlEntriesTab()
        self.equity_statement_tab = EquityStatementTab()
        self.ratios_tab = FinancialRatiosTab()

        self.tabs.addTab(self.trial_balance_tab, "Neraca Saldo")
        self.tabs.addTab(self.balance_sheet_tab, "Neraca (Balance Sheet)")
        self.tabs.addTab(self.income_statement_tab, "Laba Rugi")
        self.tabs.addTab(self.cash_flow_tab, "Arus Kas")
        self.tabs.addTab(self.gl_entries_tab, "GL Entries (Drill-down)")
        self.tabs.addTab(self.equity_statement_tab, "Perubahan Ekuitas")
        self.tabs.addTab(self.ratios_tab, "Rasio Keuangan")
        outer.addWidget(self.tabs, stretch=1)
        