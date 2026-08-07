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

from registry.module_registry import FieldSpec, FieldType
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTabWidget, QVBoxLayout, QWidget
from ui.widgets.child_record_panel import ChildRecordPanel

CUSTOMER_BASE = "/customers/customers"


class CustomerDetailDialog(QDialog):
    def __init__(self, customer_id: str, customer_label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.customer_id = customer_id
        self.setWindowTitle(f"Detail Pelanggan — {customer_label}")
        self.setMinimumSize(760, 560)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel(f"<b>{self.windowTitle()}</b>")
        header.setStyleSheet("font-size:14px;")
        layout.addWidget(header)

        tabs = QTabWidget()
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
            parent=self,
        )

    def _notes_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/notes",
            columns=[("note", "Catatan"), ("created_at", "Tanggal")],
            form_fields=[FieldSpec("note", "Catatan", FieldType.TEXTAREA, required=True)],
            parent=self,
        )

    def _tags_tab(self, base: str) -> ChildRecordPanel:
        return ChildRecordPanel(
            base_path=f"{base}/tags",
            columns=[("tag", "Tag")],
            form_fields=[FieldSpec("tag", "Tag", required=True,
                                    help_text="mis. Retail, Distributor, VIP, Export")],
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
