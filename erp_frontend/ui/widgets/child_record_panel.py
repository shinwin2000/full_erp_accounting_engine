"""
ui/widgets/child_record_panel.py
=================================
Panel CRUD ringkas untuk data anak (child record) satu parent tertentu,
mis. alamat / contact person / attachment / notes / tags milik satu
Customer. Dipakai di dalam CustomerDetailDialog (satu tab = satu panel).

Beda dengan GenericListPage (widgets/generic_list_page.py):
- Tidak ada pagination/search (jumlah child record per parent biasanya kecil).
- path selalu diawali base_path parent yang sudah include {parent_id}.
- Bisa dibuat read-only (read_only=True) untuk data riwayat/audit
  (credit history, balance history) yang memang tidak boleh diubah dari UI.
"""
from __future__ import annotations

from typing import Any, Callable

from core.api_client import api_client
from core.workers import run_task
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from registry.module_registry import FieldSpec
from ui.widgets.form_dialog import FormDialog
from ui.widgets.generic_table_model import GenericTableModel


class ChildRecordPanel(QWidget):
    def __init__(
        self,
        base_path: str,
        columns: list[tuple[str, str]],
        form_fields: list[FieldSpec] | None = None,
        id_field: str = "id",
        read_only: bool = False,
        can_edit: bool = False,
        empty_label: str = "Belum ada data.",
        parent: QWidget | None = None,
        dialog_factory: Callable[..., Any] | None = None,
        entity_label: str = "Data",
    ):
        """
        base_path: path absolut sudah termasuk id parent,
                   mis. "/customers/customers/{customer_id}/addresses"
        """
        super().__init__(parent)
        self.base_path = base_path
        self.columns = columns
        self.form_fields = form_fields or []
        self.id_field = id_field
        self.read_only = read_only
        self.can_edit = can_edit
        self.empty_label = empty_label
        # dialog_factory(title, fields, initial=None, parent=None) -> dialog.
        # Default FormDialog standar; tab Customer memakai ModernFormDialog.
        self.dialog_factory = dialog_factory
        self.entity_label = entity_label
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        if not self.read_only:
            self.delete_btn = QPushButton("🗑 Hapus")
            self.delete_btn.clicked.connect(self._delete_selected)
            toolbar.addWidget(self.delete_btn)
            if self.can_edit:
                self.edit_btn = QPushButton("✎ Ubah")
                self.edit_btn.clicked.connect(self._edit_selected)
                toolbar.addWidget(self.edit_btn)
            self.add_btn = QPushButton("+ Tambah")
            self.add_btn.setObjectName("primaryButton")
            self.add_btn.clicked.connect(self._add_new)
            toolbar.addWidget(self.add_btn)

        layout.addLayout(toolbar)

        self.model = GenericTableModel(self.columns)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setVisible(False)
        if self.can_edit and not self.read_only:
            self.table.doubleClicked.connect(lambda *_: self._edit_selected())

        # BUG FIX: `empty_label` sebelumnya diterima tapi tidak pernah
        # ditampilkan, jadi tab yang datanya kosong hanya berupa kotak putih
        # polos dan terlihat seperti rusak. Sekarang ada keterangan jelas.
        self.empty_widget = QLabel(f"📭\n\n{self.empty_label}")
        self.empty_widget.setAlignment(Qt.AlignCenter)
        self.empty_widget.setStyleSheet(
            "color:#6B7280; font-size:13.5px; background:#FFFFFF; "
            "border:1px dashed #D8D4F2; border-radius:12px;"
        )
        self.loading_widget = QLabel("⏳  Memuat data...")
        self.loading_widget.setAlignment(Qt.AlignCenter)
        self.loading_widget.setStyleSheet("color:#6B7280; font-size:13px; background:#FFFFFF;")

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)           # 0 = ada data
        self.stack.addWidget(self.empty_widget)    # 1 = kosong
        self.stack.addWidget(self.loading_widget)  # 2 = memuat
        self.stack.setCurrentIndex(2)
        layout.addWidget(self.stack, stretch=1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if self.model.rowCount() == 0:
            self.stack.setCurrentIndex(2)
        run_task(
            api_client.get,
            on_success=self._on_loaded,
            on_error=self._on_error,
            path=self.base_path,
        )

    def _on_loaded(self, payload: Any) -> None:
        rows = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
        self.model.set_rows(rows)
        self.table.resizeColumnsToContents()
        self.stack.setCurrentIndex(0 if rows else 1)

    def _on_error(self, message: str) -> None:
        if self.model.rowCount() == 0:
            self.stack.setCurrentIndex(1)
        if message != "AUTH_REQUIRED":
            QMessageBox.warning(self, "Gagal memuat", message)

    # ------------------------------------------------------------------
    def _selected_record(self) -> dict[str, Any] | None:
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        return self.model.record_at(idx.row())

    def _make_dialog(self, title: str, initial: dict[str, Any] | None = None):
        if self.dialog_factory:
            return self.dialog_factory(title, self.form_fields, initial=initial, parent=self)
        return FormDialog(title, self.form_fields, initial=initial, parent=self)

    def _add_new(self) -> None:
        if not self.form_fields:
            return
        dlg = self._make_dialog(f"Tambah {self.entity_label}")
        if dlg.exec():
            payload = dlg.result_payload()
            run_task(
                api_client.post,
                on_success=lambda _r: self.refresh(),
                on_error=self._on_write_error,
                path=self.base_path,
                json_body=payload,
            )

    def _edit_selected(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih baris terlebih dahulu.")
            return
        dlg = self._make_dialog(f"Ubah {self.entity_label}", initial=record)
        if dlg.exec():
            payload = dlg.result_payload()
            rec_id = record.get(self.id_field)
            run_task(
                api_client.patch,
                on_success=lambda _r: self.refresh(),
                on_error=self._on_write_error,
                path=f"{self.base_path}/{rec_id}",
                json_body=payload,
            )

    def _delete_selected(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih baris terlebih dahulu.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi Hapus", "Hapus data ini?")
        if confirm != QMessageBox.Yes:
            return
        rec_id = record.get(self.id_field)
        run_task(
            api_client.delete,
            on_success=lambda _r: self.refresh(),
            on_error=self._on_write_error,
            path=f"{self.base_path}/{rec_id}",
        )

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
