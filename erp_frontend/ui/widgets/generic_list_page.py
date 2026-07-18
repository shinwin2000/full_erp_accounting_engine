"""
ui/widgets/generic_list_page.py
================================
Halaman CRUD generik yang men-drive SEMUA modul yang tidak memiliki
layar khusus (lihat registry/module_registry.py -> custom_page=False).
Satu widget ini menggantikan puluhan ribu baris kode UI berulang: ia
membaca `ModuleConfig` dan otomatis menyediakan tabel + form + aksi
workflow yang sesuai untuk modul tsb.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.api_client import ApiError, api_client
from core.formatting import extract_list, extract_total
from core.workers import run_task
from registry.module_registry import ModuleConfig
from ui.widgets.form_dialog import FormDialog
from ui.widgets.generic_table_model import GenericTableModel

PAGE_SIZE = 50


class GenericListPage(QWidget):
    def __init__(self, config: ModuleConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self.page = 1
        self.total_rows = 0
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(f"{self.config.icon}  {self.config.label}")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cari...")
        self.search_edit.setMaximumWidth(280)
        self.search_edit.returnPressed.connect(self.refresh)
        toolbar.addWidget(self.search_edit)

        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        toolbar.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        if self.config.actions:
            self.action_btn = QToolButton()
            self.action_btn.setText("Aksi ▾")
            self.action_btn.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(self.action_btn)
            for action in self.config.actions:
                act = menu.addAction(action.label)
                act.triggered.connect(lambda checked=False, a=action: self._run_action(a))
            self.action_btn.setMenu(menu)
            toolbar.addWidget(self.action_btn)

        if self.config.can_delete:
            self.delete_btn = QPushButton("🗑 Hapus")
            self.delete_btn.clicked.connect(self._delete_selected)
            toolbar.addWidget(self.delete_btn)

        self.export_btn = QPushButton("⬇ Export")
        self.export_btn.clicked.connect(self._export)
        toolbar.addWidget(self.export_btn)

        if self.config.can_edit:
            self.edit_btn = QPushButton("✎ Ubah")
            self.edit_btn.clicked.connect(self._edit_selected)
            toolbar.addWidget(self.edit_btn)

        if self.config.can_create:
            self.new_btn = QPushButton("+ Baru")
            self.new_btn.setObjectName("primaryButton")
            self.new_btn.clicked.connect(self._create_new)
            toolbar.addWidget(self.new_btn)

        layout.addLayout(toolbar)

        columns = self.config.columns or [("id", "ID")]
        self.model = GenericTableModel(columns)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda *_: self._edit_selected())
        layout.addWidget(self.table, stretch=1)

        pager = QHBoxLayout()
        self.pager_label = QLabel("")
        self.pager_label.setStyleSheet("color:#6B7280;")
        pager.addWidget(self.pager_label)
        pager.addStretch()
        self.prev_btn = QPushButton("‹ Sebelumnya")
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = QPushButton("Berikutnya ›")
        self.next_btn.clicked.connect(self._next_page)
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.next_btn)
        layout.addLayout(pager)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        layout.addWidget(self.status_label)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if not self.config.list_path:
            self.status_label.setText("Modul ini tidak memiliki endpoint daftar (list).")
            return
        params: dict[str, Any] = {"page": self.page, "page_size": PAGE_SIZE, "limit": PAGE_SIZE}
        search = self.search_edit.text().strip()
        if search:
            params[self.config.search_param] = search
        self.status_label.setText("Memuat data...")
        path = self.config.base_path + self.config.list_path
        run_task(
            api_client.get,
            on_success=self._on_data_loaded,
            on_error=self._on_error,
            path=path,
            params=params,
        )

    def _on_data_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.total_rows = extract_total(payload, len(rows))
        self.model.set_rows(rows)
        self.table.resizeColumnsToContents()
        start = (self.page - 1) * PAGE_SIZE + 1 if rows else 0
        end = start + len(rows) - 1 if rows else 0
        self.pager_label.setText(f"Menampilkan {start}-{end}" + (f" dari {self.total_rows}" if self.total_rows else ""))
        self.status_label.setText(f"{len(rows)} baris dimuat.")
        self.prev_btn.setEnabled(self.page > 1)
        self.next_btn.setEnabled(len(rows) == PAGE_SIZE)

    def _on_error(self, message: str) -> None:
        if message == "AUTH_REQUIRED":
            self.status_label.setText("Sesi berakhir. Silakan login kembali.")
            return
        self.status_label.setText(f"Gagal memuat: {message}")

    def _prev_page(self) -> None:
        if self.page > 1:
            self.page -= 1
            self.refresh()

    def _next_page(self) -> None:
        self.page += 1
        self.refresh()

    # ------------------------------------------------------------------
    def _selected_record(self) -> Optional[dict[str, Any]]:
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        return self.model.record_at(idx.row())

    def _create_new(self) -> None:
        if not self.config.form_fields:
            QMessageBox.information(self, "Info", "Form untuk modul ini belum dikonfigurasi.")
            return
        dlg = FormDialog(f"Tambah {self.config.label}", self.config.form_fields, parent=self)
        if dlg.exec():
            payload = dlg.result_payload()
            create_path = self.config.base_path + self.config.list_path
            self.status_label.setText("Menyimpan...")
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Data berhasil ditambahkan."),
                on_error=self._on_write_error,
                path=create_path,
                json_body=payload,
            )

    def _edit_selected(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih baris terlebih dahulu.")
            return
        if not self.config.form_fields:
            QMessageBox.information(self, "Info", "Form untuk modul ini belum dikonfigurasi.")
            return
        dlg = FormDialog(f"Ubah {self.config.label}", self.config.form_fields, initial=record, parent=self)
        if dlg.exec():
            payload = dlg.result_payload()
            rec_id = record.get(self.config.id_field)
            path = f"{self.config.base_path}{self.config.list_path.rstrip('/')}/{rec_id}"
            self.status_label.setText("Menyimpan perubahan...")
            edit_fn = api_client.patch if self.config.edit_http_method.upper() == "PATCH" else api_client.put
            run_task(
                edit_fn,
                on_success=lambda _r: self._after_write("Perubahan disimpan."),
                on_error=self._on_write_error,
                path=path,
                json_body=payload,
            )

    def _delete_selected(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih baris terlebih dahulu.")
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi Hapus",
            f"Hapus data ini secara permanen?\n{record.get(self.config.id_field, '')}",
        )
        if confirm != QMessageBox.Yes:
            return
        rec_id = record.get(self.config.id_field)
        path = f"{self.config.base_path}{self.config.list_path.rstrip('/')}/{rec_id}"
        run_task(
            api_client.delete,
            on_success=lambda _r: self._after_write("Data dihapus."),
            on_error=self._on_write_error,
            path=path,
        )

    def _run_action(self, action) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih baris terlebih dahulu.")
            return
        if action.confirm:
            confirm = QMessageBox.question(self, "Konfirmasi", f"Jalankan aksi '{action.label}'?")
            if confirm != QMessageBox.Yes:
                return
        rec_id = record.get(self.config.id_field)
        path = f"{self.config.base_path}{self.config.list_path.rstrip('/')}/{rec_id}{action.path_suffix}"
        run_task(
            api_client.request,
            on_success=lambda _r: self._after_write(f"Aksi '{action.label}' berhasil."),
            on_error=self._on_write_error,
            method=action.method,
            path=path,
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal menyimpan.")

    def _export(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        fmt, ok = QInputDialog.getItem(self, "Export Data", "Format:", ["csv", "excel", "json"], 0, False)
        if not ok:
            return
        ext = {"csv": "csv", "excel": "xlsx", "json": "json"}.get(fmt, "csv")
        save_path, _ = QFileDialog.getSaveFileName(self, "Simpan Export", f"{self.config.key}_export.{ext}")
        if not save_path:
            return
        export_path = f"{self.config.base_path}/export"
        params: dict[str, Any] = {"format": fmt}
        search = self.search_edit.text().strip()
        if search:
            params[self.config.search_param] = search
        self.status_label.setText("Mengekspor data...")
        run_task(
            api_client.download_file,
            on_success=lambda p: self._after_write(f"Data diekspor ke {p}"),
            on_error=self._on_write_error,
            path=export_path,
            save_path=save_path,
            params=params,
        )
