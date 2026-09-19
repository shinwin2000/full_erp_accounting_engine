"""
ui/pages/budget_advanced_page.py
===================================
Melengkapi gap di modul Budget: sebelumnya cuma CRUD budget dasar.
Menambahkan Dashboard, Alert budget, Transfer anggaran antar akun,
Rolling Forecast, Versioning, dan laporan Budget vs Actual.

Endpoint backend (base: /budget/budget):
  GET  /dashboard, /alerts
  POST /transfer, /rolling-forecast
  GET  /versions/{budget_code}, /{id}/vs-actual, /{id}/vs-actual-ytd
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from PySide6.QtCore import QDate as _QDate
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from ui.widgets.kpi_card import KpiCard

BASE = "/budget/budget"


class BudgetAdvancedPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("📅  Budget Advanced: Alert, Transfer, Forecast & vs-Actual")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(DashboardTab(), "Dashboard")
        self.tabs.addTab(AlertsTab(), "Alert Budget")
        self.tabs.addTab(TransferTab(), "Transfer Anggaran")
        self.tabs.addTab(RollingForecastTab(), "Rolling Forecast")
        self.tabs.addTab(VersionsTab(), "Versi Budget")
        self.tabs.addTab(VsActualTab(), "Budget vs Actual")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class DashboardTab(QWidget):
    def __init__(self):
        super().__init__()
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
        self.card_total_budget = KpiCard("Total Anggaran", icon="📅", color="#2563EB")
        self.card_total_actual = KpiCard("Total Realisasi", icon="💰", color="#059669")
        self.card_variance = KpiCard("Variance", icon="📊", color="#D97706")
        self.card_pct = KpiCard("% Terpakai", icon="📈", color="#7C3AED")
        cards.addWidget(self.card_total_budget)
        cards.addWidget(self.card_total_actual)
        cards.addWidget(self.card_variance)
        cards.addWidget(self.card_pct)
        outer.addLayout(cards)
        outer.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        # [FIX] Sebelumnya tidak mengirim as_of_date sama sekali, cocok dengan
        # log backend yang selalu 422 "Field required: as_of_date". Backend
        # sekarang sudah default ke hari ini kalau parameter ini kosong, tapi
        # tetap dikirim eksplisit di sini supaya jelas dan tidak bergantung
        # semata-mata pada default sisi server.
        from datetime import date
        run_task(
            api_client.get, on_success=self._on_loaded, on_error=self._on_error,
            path=f"{BASE}/dashboard", params={"as_of_date": date.today().isoformat()},
        )

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        self.card_total_budget.set_value(format_money(data.get("total_budget")))
        self.card_total_actual.set_value(format_money(data.get("total_actual")))
        self.card_variance.set_value(format_money(data.get("total_variance")))
        pct = data.get("consumption_percent")
        self.card_pct.set_value(f"{pct}%" if pct is not None else "-")
        self.status_label.setText("Dashboard dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class AlertsTab(QWidget):
    def __init__(self):
        super().__init__()
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

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Budget", "Akun", "Anggaran", "Realisasi", "% Terpakai", "Tingkat"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/alerts")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            severity = str(a.get("severity", ""))
            values = [
                a.get("budget_name", ""),
                f"{a.get('account_code', '')} — {a.get('account_name', '')}",
                format_money(a.get("budget_amount")),
                format_money(a.get("actual_amount")),
                f"{a.get('consumption_percent', 0):.1f}%",
                severity.upper(),
            ]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c == 5:
                    item.setForeground(QColor("#DC2626" if severity == "critical" else "#D97706"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} alert ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class TransferTab(QWidget):
    def __init__(self):
        super().__init__()
        self._accounts: list[dict[str, str]] = []
        self._build_ui()
        self._load_accounts()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Transfer Anggaran Antar Akun</b>"))
        info = QLabel(
            "Catatan: transfer hanya berhasil kalau kedua akun ada di baris "
            "budget yang SAMA (satu budget), berstatus approved/active, "
            "pada fiscal year yang dipilih."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#6B7280; font-size:11px;")
        outer.addWidget(info)

        form = QFormLayout()
        self.fiscal_year_spin = QSpinBox()
        self.fiscal_year_spin.setRange(2000, 2100)
        self.fiscal_year_spin.setValue(_QDate.currentDate().year())
        form.addRow("Fiscal Year", self.fiscal_year_spin)

        # [FIX] Sebelumnya input UUID akun mentah (rawan salah ketik) --
        # sekarang dropdown akun dari Bagan Akun, konsisten dengan dialog
        # Tambah Budget.
        self.from_account_combo = self._make_account_combo()
        form.addRow("Dari Akun", self.from_account_combo)
        self.to_account_combo = self._make_account_combo()
        form.addRow("Ke Akun", self.to_account_combo)

        self.amount_edit = QLineEdit()
        form.addRow("Jumlah", self.amount_edit)
        self.reason_edit = QLineEdit()
        form.addRow("Alasan", self.reason_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Transfer Anggaran")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _make_account_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        combo.completer().setFilterMode(Qt.MatchContains)
        combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        combo.addItem("— pilih akun —", None)
        return combo

    def _load_accounts(self) -> None:
        run_task(
            api_client.get, on_success=self._on_accounts_loaded, on_error=lambda _m: None,
            path="/coa/chart-of-accounts/accounts", params={"page_size": 1000, "limit": 1000},
        )

    def _on_accounts_loaded(self, payload: Any) -> None:
        accounts = extract_list(payload)
        self._accounts = sorted(
            (
                {"code": str(a.get("account_code", "")), "name": str(a.get("account_name", "")), "id": str(a.get("id"))}
                for a in accounts if a.get("account_code") and a.get("id")
            ),
            key=lambda a: a["code"],
        )
        for combo in (self.from_account_combo, self.to_account_combo):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— pilih akun —", None)
            for acc in self._accounts:
                combo.addItem(f"{acc['code']} — {acc['name']}", acc["id"])
            idx = combo.findData(current) if current else -1
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def _submit(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus > 0.")
            return
        from_account_id = self.from_account_combo.currentData()
        to_account_id = self.to_account_combo.currentData()
        if not from_account_id or not to_account_id:
            QMessageBox.warning(self, "Validasi", "Pilih akun asal dan tujuan dari daftar.")
            return
        if from_account_id == to_account_id:
            QMessageBox.warning(self, "Validasi", "Akun asal dan tujuan tidak boleh sama.")
            return
        if not self.reason_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Alasan wajib diisi.")
            return
        payload = {
            "from_account_id": from_account_id,
            "to_account_id": to_account_id,
            "amount": float(amount),
            "reason": self.reason_edit.text().strip(),
            "fiscal_year": self.fiscal_year_spin.value(),
        }
        run_task(api_client.post, on_success=self._on_ok, on_error=self._on_error,
                  path=f"{BASE}/transfer", json_body=payload)

    def _on_ok(self, result: Any) -> None:
        result = result or {}
        self.status_label.setText(
            f"Transfer berhasil pada budget {result.get('budget_code', '')}. "
            f"Saldo akun asal: {format_money(result.get('from_account_new_balance'))}, "
            f"saldo akun tujuan: {format_money(result.get('to_account_new_balance'))}."
        )
        self.amount_edit.clear()
        self.reason_edit.clear()

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class RollingForecastTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_budgets()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Buat Rolling Forecast dari Budget yang Sudah Ada</b>"))
        form = QFormLayout()
        # [FIX] Sebelumnya input UUID budget mentah -- sekarang dropdown
        # berisi daftar budget yang ada.
        self.base_budget_combo = QComboBox()
        self.base_budget_combo.setEditable(True)
        self.base_budget_combo.setInsertPolicy(QComboBox.NoInsert)
        self.base_budget_combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.base_budget_combo.completer().setFilterMode(Qt.MatchContains)
        self.base_budget_combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.base_budget_combo.addItem("— pilih budget dasar —", None)
        form.addRow("Budget Dasar", self.base_budget_combo)
        self.months_edit = QSpinBox()
        self.months_edit.setRange(1, 36)
        self.months_edit.setValue(12)
        form.addRow("Jumlah Bulan Forecast", self.months_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Buat Rolling Forecast")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load_budgets(self) -> None:
        run_task(
            api_client.get, on_success=self._on_budgets_loaded, on_error=lambda _m: None,
            path=f"{BASE}/", params={"page": 1, "page_size": 200, "limit": 200},
        )

    def _on_budgets_loaded(self, payload: Any) -> None:
        budgets = extract_list(payload)
        self.base_budget_combo.blockSignals(True)
        self.base_budget_combo.clear()
        self.base_budget_combo.addItem("— pilih budget dasar —", None)
        for b in sorted(budgets, key=lambda x: x.get("budget_code", "")):
            label = f"{b.get('budget_code', '')} — {b.get('budget_name', '')} ({b.get('fiscal_year', '')})"
            self.base_budget_combo.addItem(label, str(b.get("id")))
        self.base_budget_combo.blockSignals(False)

    def _submit(self) -> None:
        base_budget_id = self.base_budget_combo.currentData()
        if not base_budget_id:
            QMessageBox.warning(self, "Validasi", "Pilih budget dasar dari daftar.")
            return
        payload = {
            "base_budget_id": base_budget_id,
            "forecast_months": self.months_edit.value(),
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=self._on_ok,
                  on_error=self._on_error, path=f"{BASE}/rolling-forecast", json_body=payload)

    def _on_ok(self, result: Any) -> None:
        result = result or {}
        self.status_label.setText(
            f"Rolling forecast berhasil dibuat: {result.get('budget_code', '')} "
            f"({result.get('fiscal_year', '')})."
        )
        self.notes_edit.clear()

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class VersionsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Kode budget")
        row.addWidget(self.code_edit)
        load_btn = QPushButton("⟳ Lihat Riwayat Versi")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Versi", "Status", "Total Anggaran", "Tanggal Efektif", "Perubahan"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        code = self.code_edit.text().strip()
        if not code:
            QMessageBox.information(self, "Info", "Masukkan kode budget.")
            return
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/versions/{code}")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            values = [
                v.get("version", ""),
                str(v.get("status", "")),
                format_money(v.get("total_amount")),
                format_date(v.get("effective_date")),
                str(v.get("change_type", "")),
            ]
            for c, val in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} versi ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")


# ==========================================================================
class VsActualTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        self.budget_id_edit = QLineEdit()
        self.budget_id_edit.setPlaceholderText("UUID budget")
        row.addWidget(self.budget_id_edit)
        # [FIX] Endpoint asli mewajibkan query param period (vs-actual) /
        # as_of_month (vs-actual-ytd), 1-12 -- sebelumnya tidak pernah dikirim
        # sama sekali sehingga request selalu gagal validasi.
        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 12)
        self.period_spin.setValue(_QDate.currentDate().month())
        self.period_spin.setPrefix("Bulan ")
        row.addWidget(self.period_spin)
        load_btn = QPushButton("⟳ Lihat Budget vs Actual")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        load_ytd_btn = QPushButton("⟳ Lihat vs Actual (YTD)")
        load_ytd_btn.clicked.connect(self._load_ytd)
        row.addWidget(load_ytd_btn)
        outer.addLayout(row)

        summary = QHBoxLayout()
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight:600;")
        summary.addWidget(self.summary_label)
        summary.addStretch()
        outer.addLayout(summary)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Akun", "Anggaran", "Realisasi", "Variance", "% Variance"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        bid = self.budget_id_edit.text().strip()
        if not bid:
            QMessageBox.information(self, "Info", "Masukkan ID budget.")
            return
        # [FIX] Path asli: /{budget_id}/vs-actual (bukan /vs-actual/{budget_id}),
        # plus wajib query param `period`.
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/{bid}/vs-actual", params={"period": self.period_spin.value()})

    def _load_ytd(self) -> None:
        bid = self.budget_id_edit.text().strip()
        if not bid:
            QMessageBox.information(self, "Info", "Masukkan ID budget.")
            return
        # [FIX] Path asli: /{budget_id}/vs-actual-ytd, plus wajib query
        # param `as_of_month`.
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/{bid}/vs-actual-ytd", params={"as_of_month": self.period_spin.value()})

    def _on_loaded(self, payload: Any) -> None:
        # [FIX] Response endpoint ini adalah SATU objek (BudgetVsActualResponse)
        # berisi ringkasan + `lines`, bukan list mentah -- sebelumnya
        # `extract_list(payload)` langsung dipakai di payload top-level,
        # yang untuk dict non-list akan selalu menghasilkan list kosong.
        payload = payload or {}
        rows = payload.get("lines") or []
        self.summary_label.setText(
            f"{payload.get('period_name', '')}  |  "
            f"Total Anggaran: {format_money(payload.get('total_budget'))}  |  "
            f"Total Realisasi: {format_money(payload.get('total_actual'))}  |  "
            f"Variance: {format_money(payload.get('total_variance'))} "
            f"({payload.get('variance_percent', 0):.1f}%)"
        )
        self.table.setRowCount(len(rows))
        for r, line in enumerate(rows):
            values = [
                f"{line.get('account_code', '')} — {line.get('account_name', '')}",
                format_money(line.get("budget_amount")),
                format_money(line.get("actual_amount")),
                # [FIX] Field aslinya `variance_amount`, bukan `variance`.
                format_money(line.get("variance_amount")),
                f"{line.get('variance_percent', 0):.1f}%",
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} akun ditampilkan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
