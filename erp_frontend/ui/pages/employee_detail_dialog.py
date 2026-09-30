"""
ui/pages/employee_detail_dialog.py
====================================
Dialog "Detail Karyawan" -- data tambahan satu Karyawan yang tidak muat
di grid utama, mengikuti pola yang sama seperti CustomerDetailDialog
(ui/pages/customer_detail_dialog.py):

    Tab 1 Tanggungan/Keluarga -> employee_dependents (pasangan/anak/dll -
                                 relevan untuk status PTKP)
    Tab 2 Foto                -> foto profil karyawan (upload/ganti/hapus)
    Tab 3 Dokumen             -> KTP/KK/BPJS Kesehatan/BPJS Ketenagakerjaan/
                                 NPWP/Ijazah/lainnya (bisa lebih dari satu
                                 dokumen, beda dari foto yang cuma satu)

Dibuka lewat tombol "📋 Detail" di EmployeesPage (ui/pages/employees_page.py)
untuk baris Karyawan yang sedang dipilih.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core.api_client import api_client
from core.workers import run_task
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from registry.module_registry import FieldSpec, FieldType
from ui.widgets.child_record_panel import ChildRecordPanel
from ui.widgets.form_dialog import FormDialog

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


DOCUMENT_TYPE_LABELS = {
    "ktp": "KTP",
    "kk": "Kartu Keluarga (KK)",
    "bpjs_kesehatan": "BPJS Kesehatan",
    "bpjs_ketenagakerjaan": "BPJS Ketenagakerjaan",
    "npwp": "NPWP",
    "ijazah": "Ijazah",
    "other": "Lainnya",
}


class EmployeeDocumentsTab(QWidget):
    """Tab dokumen (KTP/KK/BPJS/dll) - bisa lebih dari satu per karyawan,
    beda dari EmployeePhotoTab yang cuma satu foto."""

    def __init__(self, employee_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.employee_id = employee_id
        self.documents_path = f"{EMPLOYEE_BASE}/{employee_id}/documents"
        self._rows: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("➕ Tambah Dokumen")
        self.add_btn.clicked.connect(self._add_document)
        btn_row.addWidget(self.add_btn)

        self.view_btn = QPushButton("👁 Lihat")
        self.view_btn.clicked.connect(self._view_document)
        btn_row.addWidget(self.view_btn)

        self.download_btn = QPushButton("⬇ Unduh")
        self.download_btn.clicked.connect(self._download_document)
        btn_row.addWidget(self.download_btn)

        self.delete_btn = QPushButton("🗑 Hapus")
        self.delete_btn.clicked.connect(self._delete_document)
        btn_row.addWidget(self.delete_btn)

        btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addLayout(btn_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Tipe", "Label", "Nomor", "Nama File", "Tanggal"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        hint = QLabel("Format: JPG/PNG/PDF, maksimal 5 MB per dokumen.")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        run_task(
            api_client.get,
            on_success=self._on_loaded,
            on_error=self._on_load_error,
            path=self.documents_path,
        )

    def _on_loaded(self, data: Any) -> None:
        self._rows = data if isinstance(data, list) else []
        self.table.setRowCount(len(self._rows))
        for r, doc in enumerate(self._rows):
            type_label = DOCUMENT_TYPE_LABELS.get(doc.get("document_type"), doc.get("document_type"))
            self.table.setItem(r, 0, QTableWidgetItem(type_label))
            self.table.setItem(r, 1, QTableWidgetItem(doc.get("document_label") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(doc.get("document_number") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(doc.get("file_filename") or ""))
            self.table.setItem(r, 4, QTableWidgetItem((doc.get("created_at") or "")[:10]))

    def _on_load_error(self, message: str) -> None:
        if message != "AUTH_REQUIRED":
            QMessageBox.warning(self, "Gagal memuat dokumen", message)

    def _selected_doc(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    # ------------------------------------------------------------------
    def _add_document(self) -> None:
        dlg = FormDialog(
            "Tambah Dokumen",
            [
                FieldSpec(
                    "document_type", "Jenis Dokumen", FieldType.SELECT,
                    choices=tuple(DOCUMENT_TYPE_LABELS.keys()), required=True,
                ),
                FieldSpec("document_label", "Label (wajib jika jenis 'other')"),
                FieldSpec("document_number", "Nomor Dokumen"),
                FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
            ],
            parent=self,
        )
        if not dlg.exec():
            return
        payload = dlg.result_payload()
        if payload.get("document_type") == "other" and not payload.get("document_label"):
            QMessageBox.warning(
                self, "Data belum lengkap", "Label wajib diisi untuk jenis dokumen 'other'."
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Pilih File Dokumen", "", "Dokumen (*.jpg *.jpeg *.png *.pdf)"
        )
        if not file_path:
            return
        if Path(file_path).stat().st_size > 5 * 1024 * 1024:
            QMessageBox.warning(self, "Terlalu besar", "Ukuran file maksimal 5 MB.")
            return

        self.add_btn.setEnabled(False)
        run_task(
            api_client.upload_file,
            on_success=lambda _r: self._on_add_success(),
            on_error=self._on_write_error,
            path=self.documents_path,
            file_path=file_path,
            form_fields=payload,
        )

    def _on_add_success(self) -> None:
        self.add_btn.setEnabled(True)
        self.refresh()

    def _view_document(self) -> None:
        # FIX: sebelumnya tombol ini SELALU memaksa dialog "Simpan Sebagai"
        # (QFileDialog.getSaveFileName) - user harus pilih lokasi simpan
        # dulu baru bisa lihat isinya, padahal maksudnya cuma mau melihat.
        # Sekarang: file diunduh ke lokasi temporer lalu langsung dibuka
        # pakai aplikasi default sistem (foto->image viewer, PDF->PDF
        # reader), tanpa dialog apa pun - "Unduh" (simpan permanen ke
        # lokasi pilihan user) dipisah jadi tombol tersendiri di bawah.
        doc = self._selected_doc()
        if not doc:
            QMessageBox.information(self, "Info", "Pilih dokumen terlebih dahulu.")
            return
        self.view_btn.setEnabled(False)
        run_task(
            lambda: api_client.request(
                "GET", f"{self.documents_path}/{doc['id']}/file", raw=True, retry_on_401=True
            ),
            on_success=lambda resp: self._on_view_loaded(resp, doc["file_filename"]),
            on_error=self._on_write_error,
        )

    def _on_view_loaded(self, resp: Any, filename: str) -> None:
        self.view_btn.setEnabled(True)
        suffix = Path(filename).suffix or ""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(resp.content)
        finally:
            tmp.close()
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(tmp.name))
        if not opened:
            QMessageBox.warning(
                self, "Gagal membuka",
                "Tidak ada aplikasi default untuk membuka file ini di sistem Anda.",
            )

    def _download_document(self) -> None:
        doc = self._selected_doc()
        if not doc:
            QMessageBox.information(self, "Info", "Pilih dokumen terlebih dahulu.")
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Simpan Dokumen", doc["file_filename"])
        if not save_path:
            return
        run_task(
            api_client.download_file,
            on_success=lambda p: QMessageBox.information(self, "Berhasil", f"Dokumen disimpan ke:\n{p}"),
            on_error=self._on_write_error,
            path=f"{self.documents_path}/{doc['id']}/file",
            save_path=save_path,
        )

    def _delete_document(self) -> None:
        doc = self._selected_doc()
        if not doc:
            QMessageBox.information(self, "Info", "Pilih dokumen terlebih dahulu.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", f"Hapus dokumen '{doc['file_filename']}'?")
        if confirm != QMessageBox.Yes:
            return
        self.delete_btn.setEnabled(False)
        run_task(
            api_client.delete,
            on_success=lambda _r: self._on_delete_success(),
            on_error=self._on_write_error,
            path=f"{self.documents_path}/{doc['id']}",
        )

    def _on_delete_success(self) -> None:
        self.delete_btn.setEnabled(True)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        self.add_btn.setEnabled(True)
        self.view_btn.setEnabled(True)
        self.download_btn.setEnabled(True)
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
        tabs.addTab(EmployeeDocumentsTab(self.employee_id), "📄 Dokumen (KTP/KK/BPJS)")

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
