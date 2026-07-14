"""
ui/pages/documents_page.py
=============================
Menggantikan versi generik lama yang can_create=False (upload benar-benar
tidak berfungsi). Sekarang mendukung upload file asli (multipart), download,
approve/reject/archive/lock.

Endpoint backend (base: /documents/documents):
  POST /upload                         - upload 1 file (multipart/form-data)
  GET  /                                - daftar dokumen
  GET  /{id}/download                   - download file
  POST /{id}/approve | /reject | /archive | /lock | /unlock
"""
from __future__ import annotations

import os
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list, format_datetime, status_color
from core.workers import run_task

BASE = "/documents/documents"


class DocumentsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("📎  Manajemen Dokumen")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        outer.addLayout(header)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()

        self.action_btn = QToolButton()
        self.action_btn.setText("Aksi ▾")
        self.action_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.action_btn)
        for name, label in [("approve", "Approve"), ("reject", "Reject"), ("archive", "Archive"),
                             ("lock", "Lock"), ("unlock", "Unlock")]:
            act = menu.addAction(label)
            act.triggered.connect(lambda checked=False, n=name: self._run_action(n))
        self.action_btn.setMenu(menu)
        toolbar.addWidget(self.action_btn)

        download_btn = QPushButton("⬇ Download")
        download_btn.clicked.connect(self._download_selected)
        toolbar.addWidget(download_btn)

        upload_btn = QPushButton("⬆ Upload Dokumen")
        upload_btn.setObjectName("primaryButton")
        upload_btn.clicked.connect(self._upload_document)
        toolbar.addWidget(upload_btn)
        outer.addLayout(toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Nama File", "Tipe Entitas", "Terkait ID", "Diunggah Oleh", "Tanggal Upload", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.status_label.setText("Memuat daftar dokumen...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=BASE)

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            values = [
                rec.get("original_filename", rec.get("filename", "")),
                rec.get("entity_type") or "-",
                str(rec.get("entity_id") or "-"),
                rec.get("uploaded_by_name") or str(rec.get("uploaded_by", "")),
                format_datetime(rec.get("uploaded_at")),
                str(rec.get("status", "")),
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col == 5:
                    item.setForeground(QColor(status_color(val)))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} dokumen dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _selected_record(self) -> Optional[dict[str, Any]]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    # ------------------------------------------------------------------
    def _upload_document(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Pilih File untuk Diunggah")
        if not file_path:
            return
        dlg = UploadMetadataDialog(file_path, parent=self)
        if dlg.exec():
            form_fields = dlg.build_form_fields()
            self.status_label.setText("Mengunggah file...")
            run_task(
                api_client.upload_file,
                on_success=lambda _r: self._after_write("Dokumen berhasil diunggah."),
                on_error=self._on_write_error,
                path=f"{BASE}/upload",
                file_path=file_path,
                form_fields=form_fields,
            )

    def _download_selected(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih dokumen terlebih dahulu.")
            return
        doc_id = record.get("id")
        filename = record.get("original_filename", record.get("filename", "downloaded_file"))
        save_path, _ = QFileDialog.getSaveFileName(self, "Simpan Sebagai", filename)
        if not save_path:
            return
        self.status_label.setText("Mengunduh file...")
        run_task(
            api_client.download_file,
            on_success=lambda p: self._after_write(f"File disimpan ke {p}"),
            on_error=self._on_write_error,
            path=f"{BASE}/{doc_id}/download",
            save_path=save_path,
        )

    def _run_action(self, action_name: str) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih dokumen terlebih dahulu.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", f"Jalankan aksi '{action_name}'?")
        if confirm != QMessageBox.Yes:
            return
        doc_id = record.get("id")
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Aksi '{action_name}' berhasil."),
            on_error=self._on_write_error,
            path=f"{BASE}/{doc_id}/{action_name}",
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


class UploadMetadataDialog(QDialog):
    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detail Upload Dokumen")
        self.resize(420, 280)
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel(f"File: <b>{os.path.basename(file_path)}</b>"))

        form = QFormLayout()
        self.entity_type_edit = QLineEdit()
        self.entity_type_edit.setPlaceholderText("mis. journal, ar_invoice, ap_invoice (opsional)")
        form.addRow("Tipe Entitas Terkait", self.entity_type_edit)

        self.entity_id_edit = QLineEdit()
        self.entity_id_edit.setPlaceholderText("UUID entitas terkait (opsional)")
        form.addRow("ID Entitas Terkait", self.entity_id_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tag1, tag2, tag3 (opsional)")
        form.addRow("Tags", self.tags_edit)

        self.description_edit = QLineEdit()
        form.addRow("Deskripsi", self.description_edit)

        self.retention_edit = QLineEdit()
        self.retention_edit.setPlaceholderText("opsional, dalam hari")
        form.addRow("Masa Retensi (hari)", self.retention_edit)

        outer.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Upload")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def build_form_fields(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type_edit.text().strip() or None,
            "entity_id": self.entity_id_edit.text().strip() or None,
            "tags": self.tags_edit.text().strip() or None,
            "description": self.description_edit.text().strip() or None,
            "retention_days": self.retention_edit.text().strip() or None,
        }
