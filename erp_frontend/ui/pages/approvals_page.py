"""
ui/pages/approvals_page.py
=============================
Approval Inbox — daftar tugas approval yang menunggu keputusan user
saat ini (GET /approval/approvals/my-tasks), dengan aksi approve/reject/
escalate/delegate (POST /approval/approvals/requests/{id}/action).
"""
from __future__ import annotations

from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_datetime, status_color
from core.workers import run_task
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

BASE = "/approval/approvals"


class ApprovalsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("✅  Approval Inbox — Tugas Saya")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["No. Request", "Tipe Entitas", "Diajukan Oleh", "Tanggal", "Level", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        action_row = QHBoxLayout()
        approve_btn = QPushButton("✔ Approve")
        approve_btn.setProperty("class", "success")
        approve_btn.clicked.connect(lambda: self._take_action("approve"))
        reject_btn = QPushButton("✘ Reject")
        reject_btn.setProperty("class", "danger")
        reject_btn.clicked.connect(lambda: self._take_action("reject"))
        escalate_btn = QPushButton("⬆ Escalate")
        escalate_btn.clicked.connect(lambda: self._take_action("escalate"))
        action_row.addWidget(approve_btn)
        action_row.addWidget(reject_btn)
        action_row.addWidget(escalate_btn)
        action_row.addStretch()
        outer.addLayout(action_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        self.status_label.setText("Memuat tugas approval...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/my-tasks")

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            values = [
                rec.get("request_number", ""),
                str(rec.get("entity_type", "")),
                rec.get("requested_by_name") or str(rec.get("requested_by", "")),
                format_datetime(rec.get("created_at")),
                str(rec.get("current_level", rec.get("level", ""))),
                str(rec.get("status", "")),
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col == 5:
                    item.setForeground(QColor(status_color(val)))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} tugas menunggu keputusan Anda.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _selected_record(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    def _take_action(self, action: str) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih request terlebih dahulu.")
            return
        notes = ""
        if action == "reject":
            notes, ok = QInputDialog.getMultiLineText(self, "Alasan Reject", "Alasan penolakan:")
            if not ok:
                return
        else:
            confirm = QMessageBox.question(self, "Konfirmasi", f"Jalankan aksi '{action}' untuk request ini?")
            if confirm != QMessageBox.Yes:
                return
        request_id = record.get("id")
        body = {"action": action, "notes": notes or None}
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Aksi '{action}' berhasil dijalankan."),
            on_error=self._on_write_error,
            path=f"{BASE}/requests/{request_id}/action",
            json_body=body,
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
