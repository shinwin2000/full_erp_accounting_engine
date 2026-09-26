"""
ui/pages/employee_detail_dialog.py
====================================
Dialog "Detail Karyawan" -- data tambahan satu Karyawan yang tidak muat
di grid utama, mengikuti pola yang sama seperti CustomerDetailDialog
(ui/pages/customer_detail_dialog.py):

    Tab 1 Tanggungan/Keluarga -> employee_dependents (pasangan/anak/dll -
                                 relevan untuk status PTKP)
    Tab 2 Foto                -> foto profil karyawan (upload/ganti/hapus)

Dibuka lewat tombol "📋 Detail" di EmployeesPage (ui/pages/employees_page.py)
untuk baris Karyawan yang sedang dipilih.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api_client import api_client
from core.workers import run_task
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from registry.module_registry import FieldSpec, FieldType
from ui.widgets.child_record_panel import ChildRecordPanel

EMPLOYEE_BASE = "/employees/employees"

PHOTO_SIZE = 220


class EmployeePhotoTab(QWidget):
    """Tab foto profil - satu foto per karyawan, bisa upload/ganti/hapus."""

    def __init__(self, employee_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.employee_id = employee_id
        self.photo_path = f"{EMPLOYEE_BASE}/{employee_id}/photo"
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        self.preview = QLabel("Memuat...")
        self.preview.setFixedSize(PHOTO_SIZE, PHOTO_SIZE)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(
            "border: 1px solid #ccc; border-radius: 6px; background: #fafafa;"
        )
        self.preview.setScaledContents(False)
        layout.addWidget(self.preview, alignment=Qt.AlignLeft)

        btn_row = QHBoxLayout()
        self.upload_btn = QPushButton("📤 Upload/Ganti Foto")
        self.upload_btn.clicked.connect(self._upload)
        btn_row.addWidget(self.upload_btn)

        self.delete_btn = QPushButton("🗑 Hapus Foto")
        self.delete_btn.clicked.connect(self._delete)
        btn_row.addWidget(self.delete_btn)

        btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addLayout(btn_row)

        hint = QLabel("Format: JPG/PNG, maksimal 5 MB.")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        layout.addItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.preview.setText("Memuat...")
        run_task(
            lambda: api_client.request("GET", self.photo_path, raw=True, retry_on_401=True),
            on_success=self._on_photo_loaded,
            on_error=self._on_photo_missing,
        )

    def _on_photo_loaded(self, resp: Any) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(resp.content):
            scaled = pixmap.scaled(
                PHOTO_SIZE, PHOTO_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.preview.setPixmap(scaled)
        else:
            self.preview.setText("Gagal menampilkan foto")

    def _on_photo_missing(self, message: str) -> None:
        # 404 dengan detail "Foto tidak ditemukan" (teks yang kita set
        # sendiri di router) adalah kondisi normal (belum pernah upload) -
        # tampilkan placeholder tanpa popup. AUTH_REQUIRED ditangani secara
        # global (lihat pola serupa di ChildRecordPanel._on_error) - jangan
        # ditampilkan sebagai warning di sini. Error lain (koneksi gagal,
        # dst) tetap ditampilkan sebagai warning supaya tidak menyesatkan
        # seolah-olah "memang belum ada foto".
        self.preview.setPixmap(QPixmap())
        if message == "Foto tidak ditemukan":
            self.preview.setText("Belum ada foto")
        elif message == "AUTH_REQUIRED":
            self.preview.setText("")
        else:
            self.preview.setText("Gagal memuat foto")
            QMessageBox.warning(self, "Gagal memuat foto", message)

    # ------------------------------------------------------------------
    def _upload(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Pilih Foto Karyawan", "", "Gambar (*.jpg *.jpeg *.png)"
        )
        if not file_path:
            return
        if Path(file_path).stat().st_size > 5 * 1024 * 1024:
            QMessageBox.warning(self, "Terlalu besar", "Ukuran foto maksimal 5 MB.")
            return
        self.upload_btn.setEnabled(False)
        run_task(
            api_client.upload_file,
            on_success=lambda _r: self._on_upload_success(),
            on_error=self._on_write_error,
            path=self.photo_path,
            file_path=file_path,
        )

    def _on_upload_success(self) -> None:
        self.upload_btn.setEnabled(True)
        self.refresh()

    def _delete(self) -> None:
        confirm = QMessageBox.question(self, "Konfirmasi", "Hapus foto karyawan ini?")
        if confirm != QMessageBox.Yes:
            return
        self.delete_btn.setEnabled(False)
        run_task(
            api_client.delete,
            on_success=lambda _r: self._on_delete_success(),
            on_error=self._on_write_error,
            path=self.photo_path,
        )

    def _on_delete_success(self) -> None:
        self.delete_btn.setEnabled(True)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        self.upload_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        if message != "AUTH_REQUIRED":
            QMessageBox.warning(self, "Gagal", message)


class EmployeeDetailDialog(QDialog):
    def __init__(self, employee_id: str, employee_label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.employee_id = employee_id
        self.setWindowTitle(f"Detail Karyawan — {employee_label}")
        self.setMinimumSize(700, 520)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMinMaxButtonsHint | Qt.WindowSystemMenuHint
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel(f"<b>{self.windowTitle()}</b>")
        header.setStyleSheet("font-size:14px;")
        layout.addWidget(header)

        tabs = QTabWidget()
        base = f"{EMPLOYEE_BASE}/{self.employee_id}"

        tabs.addTab(self._dependents_tab(base), "👨‍👩‍👧 Tanggungan/Keluarga")
        tabs.addTab(EmployeePhotoTab(self.employee_id), "📷 Foto")

        layout.addWidget(tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    def _dependents_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/dependents",
            columns=[
                ("full_name", "Nama"),
                ("relationship_type", "Hubungan"),
                ("birth_date", "Tgl Lahir"),
                ("occupation", "Pekerjaan"),
                ("is_ptkp_dependent", "Tanggungan PTKP"),
            ],
            form_fields=[
                FieldSpec("full_name", "Nama Lengkap", required=True),
                FieldSpec(
                    "relationship_type", "Hubungan", FieldType.SELECT,
                    choices=("spouse", "child", "parent", "other"), required=True,
                ),
                FieldSpec("birth_date", "Tanggal Lahir", FieldType.DATE),
                FieldSpec("occupation", "Pekerjaan"),
                FieldSpec("is_ptkp_dependent", "Tanggungan PTKP", FieldType.BOOL, default=True),
                FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
            ],
            can_edit=True,
            empty_label="Belum ada data tanggungan/keluarga.",
        )


__all__ = ["EmployeeDetailDialog"]
