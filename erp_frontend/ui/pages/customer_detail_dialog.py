"""
ui/pages/customer_detail_dialog.py
====================================
Dialog "Detail Pelanggan" -- menampilkan seluruh data anak satu Customer
yang tidak muat di grid utama (lihat lampiran struktur tabel ERP):

    Tab 1 Alamat           -> customer_addresses  (billing/shipping/warehouse)
    Tab 2 Contact Person    -> customer_contacts    (banyak PIC)
    Tab 3 Attachment        -> customer_attachments (NPWP/SIUP/KTP/kontrak/foto)
    Tab 4 Catatan           -> customer_notes
    Tab 5 Tag               -> customer_tags
    Tab 6 Riwayat Kredit    -> customer_credit_history (read-only)
    Tab 7 Riwayat Saldo     -> customer_balance_history (read-only)

Dibuka lewat tombol "📋 Detail" di CustomersPage (ui/pages/customers_page.py)
untuk baris Customer yang sedang dipilih.
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

CUSTOMER_BASE = "/customers/customers"

_DETAIL_QSS = """
QDialog#customerDetail { background: #F5F5FB; }
QFrame#cdHeader {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C3AED, stop:1 #4338CA);
    border-radius: 12px;
}
QLabel#cdAvatar {
    background: rgba(255,255,255,0.22); color: #FFFFFF; border-radius: 24px;
    min-width: 48px; max-width: 48px; min-height: 48px; max-height: 48px;
    font-size: 20px; font-weight: 700;
}
QLabel#cdName { color: #FFFFFF; font-size: 18px; font-weight: 700; background: transparent; }
QLabel#cdSub { color: #E0E7FF; font-size: 12px; background: transparent; }
QTabWidget::pane {
    border: 1px solid #E6E8F0; border-radius: 10px; background: #FFFFFF; top: -1px;
}
QTabBar::tab {
    background: transparent; color: #6B7280; padding: 9px 16px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600;
}
QTabBar::tab:selected {
    color: #6D28D9; background: #FFFFFF; border: 1px solid #E6E8F0; border-bottom-color: #FFFFFF;
}
QTabBar::tab:hover:!selected { background: #EDE9FE; color: #5B21B6; }
"""


class CustomerDetailDialog(QDialog):
    def __init__(self, customer_id: str, customer_label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.customer_id = customer_id
        self.setWindowTitle(f"Detail Pelanggan — {customer_label}")
        self.setObjectName("customerDetail")
        self.setStyleSheet(_DETAIL_QSS)
        self._customer_label = customer_label
        self.setMinimumSize(860, 560)
        self.resize(1040, 660)
        # BUG FIX (diminta user): QDialog secara default cuma punya tombol
        # close di title bar - tidak ada minimize/maximize. Ditambahkan
        # eksplisit lewat window flags, plus WindowSystemMenuHint supaya
        # klik-kanan title bar juga dapat opsi resize/move standar Windows.
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowSystemMenuHint
        )
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        layout.addWidget(self._build_header())

        tabs = QTabWidget()
        # Tab banyak: jangan dipotong/di-scroll ("Riw..."), tampilkan utuh.
        tabs.setUsesScrollButtons(False)
        tabs.setElideMode(Qt.ElideNone)
        tabs.tabBar().setExpanding(False)
        base = f"{CUSTOMER_BASE}/{self.customer_id}"

        tabs.addTab(self._addresses_tab(base), "📍 Alamat")
        tabs.addTab(self._contacts_tab(base), "👤 Contact Person")
        tabs.addTab(self._attachments_tab(base), "📎 Attachment")
        tabs.addTab(self._notes_tab(base), "📝 Catatan")
        tabs.addTab(self._tags_tab(base), "🏷 Tag")
        tabs.addTab(self._credit_history_tab(base), "💳 Riwayat Kredit")
        tabs.addTab(self._balance_history_tab(base), "💰 Riwayat Saldo")

        layout.addWidget(tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("cdHeader")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(14)
        avatar = QLabel((self._customer_label.strip()[:1] or "?").upper())
        avatar.setObjectName("cdAvatar")
        avatar.setAlignment(Qt.AlignCenter)
        lay.addWidget(avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(self._customer_label)
        name.setObjectName("cdName")
        sub = QLabel("Detail pelanggan: alamat, contact person, dokumen, catatan, tag, dan riwayat.")
        sub.setObjectName("cdSub")
        col.addWidget(name)
        col.addWidget(sub)
        lay.addLayout(col, stretch=1)
        return header

    # ------------------------------------------------------------------
    def _addresses_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/addresses",
            columns=[("address_type", "Tipe"), ("label", "Label"), ("address_line", "Alamat"),
                     ("city", "Kota"), ("province", "Provinsi"), ("postal_code", "Kode Pos"),
                     ("is_primary", "Utama")],
            form_fields=[
                FieldSpec("address_type", "Tipe Alamat", FieldType.SELECT,
                          choices=("billing", "shipping", "warehouse", "other"), default="other"),
                FieldSpec("label", "Label"),
                FieldSpec("address_line", "Alamat Lengkap", FieldType.TEXTAREA, required=True),
                FieldSpec("city", "Kota"),
                FieldSpec("province", "Provinsi"),
                FieldSpec("district", "Kecamatan"),
                FieldSpec("postal_code", "Kode Pos"),
                FieldSpec("country", "Negara (ISO 2)", default="ID"),
                FieldSpec("is_primary", "Alamat Utama", FieldType.BOOL),
            ],
            can_edit=True,
            empty_label="Belum ada alamat. Klik \"+ Tambah\" untuk menambahkan.",
            dialog_factory=modern_factory(icon="📍", entity="Alamat", columns=2),
            entity_label="Alamat",
            parent=self,
        )

    def _contacts_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/contacts",
            columns=[("name", "Nama"), ("position", "Jabatan"), ("phone", "Telepon"),
                     ("mobile", "HP"), ("email", "Email"), ("is_primary", "Utama")],
            form_fields=[
                FieldSpec("name", "Nama", required=True),
                FieldSpec("position", "Jabatan"),
                FieldSpec("phone", "Telepon"),
                FieldSpec("mobile", "HP"),
                FieldSpec("email", "Email"),
                FieldSpec("whatsapp", "WhatsApp"),
                FieldSpec("is_primary", "PIC Utama", FieldType.BOOL),
            ],
            can_edit=True,
            empty_label="Belum ada contact person.",
            dialog_factory=modern_factory(icon="👤", entity="Contact Person", columns=2),
            entity_label="Contact Person",
            parent=self,
        )

    def _attachments_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/attachments",
            columns=[("document_type", "Jenis"), ("file_name", "Nama File"),
                     ("mime_type", "Tipe"), ("created_at", "Diunggah")],
            form_fields=[
                FieldSpec("document_type", "Jenis Dokumen", FieldType.SELECT,
                          choices=("npwp", "siup", "ktp", "kontrak", "foto", "other"), default="other"),
                FieldSpec("file_name", "Nama File", required=True),
                FieldSpec("file_path", "Path/URL File", required=True,
                          help_text="Lokasi penyimpanan file (upload biner dilakukan terpisah)"),
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

    def _tags_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/tags",
            columns=[("tag", "Tag")],
            form_fields=[FieldSpec("tag", "Tag", required=True,
                                    help_text="mis. Retail, Distributor, VIP, Export")],
            empty_label="Belum ada tag.",
            dialog_factory=modern_factory(icon="🏷", entity="Tag", columns=1),
            entity_label="Tag",
            parent=self,
        )

    def _credit_history_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/credit-limit/history",
            columns=[("old_limit", "Limit Lama"), ("new_limit", "Limit Baru"),
                     ("reason", "Alasan"), ("created_at", "Tanggal")],
            read_only=True,
            empty_label="Belum ada perubahan limit kredit.",
            parent=self,
        )

    def _balance_history_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/balance/history",
            columns=[("old_balance", "Saldo Lama"), ("new_balance", "Saldo Baru"),
                     ("delta", "Perubahan"), ("source", "Sumber"), ("created_at", "Tanggal")],
            read_only=True,
            empty_label="Belum ada perubahan saldo.",
            parent=self,
        )
