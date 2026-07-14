"""
ui/pages/approval_matrix_page.py
===================================
Melengkapi gap KRITIS di modul Approval: sebelumnya cuma ada Approval
Inbox (proses tugas yang masuk), tapi admin tidak bisa mengatur ATURAN
approval-nya sendiri (siapa yang approve level berapa, batas nominal
berapa) — jadi matrix approval hanya bisa diatur lewat database langsung.

Endpoint backend (base: /approval/approvals):
  GET/POST /matrices                      - lihat/buat approval matrix
  PUT      /matrices/{id}                 - ubah matrix
  GET/POST /delegations                   - lihat/buat delegasi approval
  GET      /statistics                    - statistik approval
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list, format_date, format_money
from core.workers import run_task
from ui.widgets.kpi_card import KpiCard

BASE = "/approval/approvals"

ENTITY_TYPES = [
    "journal", "ap_invoice", "ar_invoice", "purchase_order", "sales_order",
    "credit_note", "debit_note", "payment",
]
APPROVAL_LEVELS = ["level_1", "level_2", "level_3", "level_4", "level_5", "executive", "cfo", "ceo"]


class ApprovalMatrixPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🧭  Approval Matrix & Delegasi")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(MatrixTab(), "Approval Matrix")
        self.tabs.addTab(DelegationTab(), "Delegasi")
        self.tabs.addTab(StatisticsTab(), "Statistik Approval")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class MatrixTab(QWidget):
    def __init__(self):
        super().__init__()
        self._records: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Kode Matrix", "Nama", "Tipe Entitas", "Jumlah Rule", "Aktif"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Buat Approval Matrix Baru</b>"))
        form = QFormLayout()
        self.code_edit = QLineEdit()
        form.addRow("Kode Matrix", self.code_edit)
        self.name_edit = QLineEdit()
        form.addRow("Nama Matrix", self.name_edit)
        self.entity_combo = QComboBox()
        self.entity_combo.addItems(ENTITY_TYPES)
        form.addRow("Tipe Entitas", self.entity_combo)
        self.currency_edit = QLineEdit("IDR")
        form.addRow("Mata Uang", self.currency_edit)
        self.notes_edit = QLineEdit()
        form.addRow("Catatan", self.notes_edit)
        outer.addLayout(form)

        outer.addWidget(QLabel(
            "Rule per level (satu baris = satu level approval). Format per baris:\n"
            "level|min_amount|max_amount|min_approvers|is_final(y/n)\n"
            "Contoh:\n"
            "level_1|0|50000000|1|n\n"
            "level_2|50000001|500000000|1|n\n"
            "cfo|500000001||1|y"
        ))
        self.rules_edit = QTextEdit()
        self.rules_edit.setPlaceholderText("level_1|0|50000000|1|n")
        self.rules_edit.setFixedHeight(90)
        outer.addWidget(self.rules_edit)

        create_btn = QPushButton("+ Buat Approval Matrix")
        create_btn.setObjectName("primaryButton")
        create_btn.clicked.connect(self._create)
        outer.addWidget(create_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/matrices")

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            values = [
                rec.get("matrix_code", ""),
                rec.get("matrix_name", ""),
                str(rec.get("entity_type", "")),
                str(len(rec.get("rules", []) or [])),
                "Ya" if rec.get("is_active") else "Tidak",
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} matrix dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _parse_rules(self) -> list[dict[str, Any]] | None:
        rules = []
        for line in self.rules_edit.toPlainText().strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 5:
                QMessageBox.warning(self, "Validasi", f"Format baris rule salah: '{line}'")
                return None
            level, min_amt, max_amt, min_approvers, is_final = parts[:5]
            if level.strip() not in APPROVAL_LEVELS:
                QMessageBox.warning(self, "Validasi", f"Level tidak valid: '{level}'. Pilih dari: {', '.join(APPROVAL_LEVELS)}")
                return None
            try:
                rule = {
                    "level": level.strip(),
                    "min_amount": float(Decimal(min_amt)) if min_amt.strip() else None,
                    "max_amount": float(Decimal(max_amt)) if max_amt.strip() else None,
                    "min_approvers": int(min_approvers) if min_approvers.strip() else 1,
                    "is_final": is_final.strip().lower() in ("y", "yes", "true", "1"),
                }
            except (InvalidOperation, ValueError):
                QMessageBox.warning(self, "Validasi", f"Nilai angka tidak valid di baris: '{line}'")
                return None
            rules.append(rule)
        return rules

    def _create(self) -> None:
        if not (self.code_edit.text().strip() and self.name_edit.text().strip()):
            QMessageBox.warning(self, "Validasi", "Kode & nama matrix wajib diisi.")
            return
        rules = self._parse_rules()
        if rules is None:
            return
        if not rules:
            QMessageBox.warning(self, "Validasi", "Minimal 1 rule level approval diperlukan.")
            return
        payload = {
            "matrix_code": self.code_edit.text().strip(),
            "matrix_name": self.name_edit.text().strip(),
            "entity_type": self.entity_combo.currentText(),
            "currency": self.currency_edit.text().strip() or "IDR",
            "rules": rules,
            "is_active": True,
            "notes": self.notes_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self._after_write("Matrix berhasil dibuat."),
                  on_error=self._on_write_error, path=f"{BASE}/matrices", json_body=payload)

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class DelegationTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Delegasi Ke", "Mulai", "Selesai", "Alasan", "Aktif"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table, stretch=1)

        outer.addWidget(QLabel("<b>Delegasikan Wewenang Approval Saya</b>"))
        form = QFormLayout()
        self.delegate_to_edit = QLineEdit()
        self.delegate_to_edit.setPlaceholderText("UUID user penerima delegasi")
        form.addRow("Delegasikan Ke", self.delegate_to_edit)
        self.start_date_edit = QDateEdit(QDate.currentDate())
        self.start_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Mulai", self.start_date_edit)
        self.end_date_edit = QDateEdit(QDate.currentDate().addDays(7))
        self.end_date_edit.setCalendarPopup(True)
        form.addRow("Tanggal Selesai", self.end_date_edit)
        self.reason_edit = QLineEdit()
        form.addRow("Alasan", self.reason_edit)
        outer.addLayout(form)

        create_btn = QPushButton("+ Buat Delegasi")
        create_btn.setObjectName("primaryButton")
        create_btn.clicked.connect(self._create)
        outer.addWidget(create_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/delegations")

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            values = [
                rec.get("delegate_to_name") or str(rec.get("delegate_to_id", "")),
                format_date(rec.get("start_date")),
                format_date(rec.get("end_date")),
                rec.get("reason", ""),
                "Ya" if rec.get("is_active") else "Tidak",
            ]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} delegasi dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _create(self) -> None:
        if not self.delegate_to_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "User penerima delegasi wajib diisi.")
            return
        if len(self.reason_edit.text().strip()) < 3:
            QMessageBox.warning(self, "Validasi", "Alasan wajib diisi.")
            return
        payload = {
            "delegate_to_user_id": self.delegate_to_edit.text().strip(),
            "start_date": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date_edit.date().toString("yyyy-MM-dd"),
            "reason": self.reason_edit.text().strip(),
        }
        run_task(api_client.post, on_success=lambda _r: self._after_write("Delegasi berhasil dibuat."),
                  on_error=self._on_write_error, path=f"{BASE}/delegations", json_body=payload)

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class StatisticsTab(QWidget):
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
        self.card_pending = KpiCard("Pending", icon="⏳", color="#D97706")
        self.card_approved = KpiCard("Approved (30 hari)", icon="✅", color="#059669")
        self.card_rejected = KpiCard("Rejected (30 hari)", icon="✘", color="#DC2626")
        self.card_avg_time = KpiCard("Rata-rata Waktu Approval", icon="⏱️", color="#2563EB")
        cards.addWidget(self.card_pending)
        cards.addWidget(self.card_approved)
        cards.addWidget(self.card_rejected)
        cards.addWidget(self.card_avg_time)
        outer.addLayout(cards)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/statistics")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        self.card_pending.set_value(str(data.get("pending_count", "-")))
        self.card_approved.set_value(str(data.get("approved_count", "-")))
        self.card_rejected.set_value(str(data.get("rejected_count", "-")))
        avg = data.get("average_approval_time_hours")
        self.card_avg_time.set_value(f"{avg:.1f} jam" if isinstance(avg, (int, float)) else "-")
        self.status_label.setText("Statistik dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
