"""
ui/pages/supplier_detail_dialog.py
====================================
Dialog "Detail Pemasok" — menampilkan data anak supplier yang tidak muat
di grid utama.

    Tab 1 Attachment    -> supplier_attachments (NPWP/SIUP/KTP/kontrak/foto)
    Tab 2 Catatan       -> supplier_notes

Dibuka lewat tombol "📋 Detail" di SuppliersPage
(ui/pages/suppliers_page.py) untuk baris supplier yang sedang dipilih.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from registry.module_registry import FieldSpec, FieldType
from ui.widgets.child_record_panel import ChildRecordPanel
from ui.widgets.modern_form_dialog import modern_factory

SUPPLIER_BASE = "/suppliers/suppliers"

_DETAIL_QSS = """
QDialog#supplierDetail { background: #F5F5FB; }
QFrame#sdHeader {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0891B2, stop:1 #0E7490);
    border-radius: 12px;
}
QLabel#sdAvatar {
    background: rgba(255,255,255,0.22); color: #FFFFFF; border-radius: 24px;
    min-width: 48px; max-width: 48px; min-height: 48px; max-height: 48px;
    font-size: 20px; font-weight: 700;
}
QLabel#sdName { color: #FFFFFF; font-size: 18px; font-weight: 700; background: transparent; }
QLabel#sdSub { color: #CFFAFE; font-size: 12px; background: transparent; }
QTabWidget::pane {
    border: 1px solid #E6E8F0; border-radius: 10px; background: #FFFFFF; top: -1px;
}
QTabBar::tab {
    background: transparent; color: #6B7280; padding: 9px 16px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600;
}
QTabBar::tab:selected {
    color: #0E7490; background: #FFFFFF; border: 1px solid #E6E8F0;
    border-bottom-color: #FFFFFF;
}
QTabBar::tab:hover:!selected { background: #CFFAFE; color: #155E75; }
"""


class SupplierDetailDialog(QDialog):
    def __init__(self, supplier_id: str, supplier_label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.supplier_id = supplier_id
        self.setWindowTitle(f"Detail Pemasok — {supplier_label}")
        self.setObjectName("supplierDetail")
        self.setStyleSheet(_DETAIL_QSS)
        self._supplier_label = supplier_label
        self.setMinimumSize(860, 560)
        self.resize(1040, 660)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowSystemMenuHint
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        layout.addWidget(self._build_header())

        tabs = QTabWidget()
        tabs.setUsesScrollButtons(False)
        tabs.setElideMode(Qt.ElideNone)
        tabs.tabBar().setExpanding(False)
        base = f"{SUPPLIER_BASE}/{self.supplier_id}"

        tabs.addTab(self._attachments_tab(base), "📎 Attachment")
        tabs.addTab(self._notes_tab(base), "📝 Catatan")

        layout.addWidget(tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("sdHeader")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(14)
        avatar = QLabel((self._supplier_label.strip()[:1] or "?").upper())
        avatar.setObjectName("sdAvatar")
        avatar.setAlignment(Qt.AlignCenter)
        lay.addWidget(avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(self._supplier_label)
        name.setObjectName("sdName")
        sub = QLabel("Detail pemasok: dokumen pendukung dan catatan internal.")
        sub.setObjectName("sdSub")
        col.addWidget(name)
        col.addWidget(sub)
        lay.addLayout(col, stretch=1)
        return header

    def _attachments_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/attachments",
            columns=[
                ("document_type", "Jenis"),
                ("file_name", "Nama File"),
                ("mime_type", "Tipe"),
                ("created_at", "Diunggah"),
            ],
            form_fields=[
                FieldSpec("document_type", "Jenis Dokumen", FieldType.SELECT,
                          choices=("npwp", "siup", "ktp", "kontrak", "foto", "other"),
                          default="other"),
                FieldSpec("file_name", "Nama File", required=True),
                FieldSpec("file_path", "Path/URL File", required=True,
                          help_text="Lokasi penyimpanan file (upload biner dilakukan terpisah)"),
                FieldSpec("file_size_bytes", "Ukuran (bytes)", FieldType.NUMBER),
                FieldSpec("mime_type", "MIME Type"),
                FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
            ],
            empty_label="Belum ada dokumen.",
            dialog_factory=modern_factory(icon="📎", entity="Dokumen", columns=1),
            entity_label="Dokumen",
            parent=self,
        )

    def _notes_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/notes",
            columns=[("note", "Catatan"), ("created_at", "Tanggal")],
            form_fields=[FieldSpec("note", "Catatan", FieldType.TEXTAREA, required=True)],
            empty_label="Belum ada catatan.",
            dialog_factory=modern_factory(icon="📝", entity="Catatan", columns=1),
            entity_label="Catatan",
            parent=self,
        )
    