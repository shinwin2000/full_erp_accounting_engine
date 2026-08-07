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

from typing import Any

from core.api_client import api_client
from core.workers import run_task
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
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
        layout.addWidget(self.table, stretch=1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
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

    def _on_error(self, message: str) -> None:
        if message != "AUTH_REQUIRED":
            QMessageBox.warning(self, "Gagal memuat", message)

    # ------------------------------------------------------------------
    def _selected_record(self) -> dict[str, Any] | None:
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        return self.model.record_at(idx.row())

    def _add_new(self) -> None:
        if not self.form_fields:
            return
        dlg = FormDialog("Tambah Data", self.form_fields, parent=self)
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
        dlg = FormDialog("Ubah Data", self.form_fields, initial=record, parent=self)
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
