"""
ui/pages/suppliers_page.py
=============================
Halaman modul "Pemasok (Supplier)" (Master Data).

Endpoint backend : /suppliers/suppliers

Tombol:
- 📋 Detail       : buka dialog detail 7 tab (alamat, contact, attachment,
                    catatan, tag, riwayat kredit, riwayat saldo)
- 💳 Limit Kredit : ubah limit kredit supplier (tercatat di Riwayat Kredit)

Form Tambah/Ubah pakai ModernFormDialog (kartu per section, header
gradasi ungu) supaya KONSISTEN dengan modul Customer.
"""
from __future__ import annotations

from core.api_client import api_client
from core.workers import run_task
from PySide6.QtWidgets import QMessageBox, QPushButton
from registry.module_registry import (
    ActionSpec,
    FieldSpec,
    FieldType,
    ModuleConfig,
)
from ui.widgets.form_dialog import FormDialog
from ui.widgets.generic_list_page import GenericListPage
from ui.widgets.modern_form_dialog import ModernFormDialog

# ---------------------------------------------------------------------------
# Kolom tabel daftar Pemasok (Supplier)
# ---------------------------------------------------------------------------
COLUMNS = [
    ("supplier_code", "Kode"),
    ("name", "Nama Supplier"),
    ("company_name", "Perusahaan"),
    ("city", "Kota"),
    ("contact_person", "PIC"),
    ("phone", "Telepon"),
    ("payment_terms_days", "Termin (hari)"),
    ("credit_limit", "Limit Kredit"),
    ("status", "Status"),
    ("is_active", "Aktif"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Pemasok (Supplier)
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    # --- Informasi Umum ---
    FieldSpec(
        "supplier_code",
        "Kode Supplier",
        required=True,
        help_text="Kode unik supplier, mis. SUP-0001",
        section="Informasi Umum",
    ),
    FieldSpec("name", "Nama Supplier", required=True, section="Informasi Umum"),
    FieldSpec("company_name", "Nama Perusahaan", section="Informasi Umum"),
    FieldSpec(
        "supplier_type",
        "Jenis Supplier",
        FieldType.SELECT,
        choices=("individual", "company", "government", "non_profit"),
        default="company",
        help_text=(
            "individual=perorangan, company=perusahaan, "
            "government=pemerintah, non_profit=nirlaba"
        ),
        section="Informasi Umum",
    ),
    FieldSpec(
        "withholding_category",
        "Kategori PPh",
        FieldType.SELECT,
        choices=("none", "pph23", "pph26", "both"),
        default="none",
        section="Informasi Umum",
    ),
    # --- Pajak ---
    FieldSpec("npwp", "NPWP", section="Pajak"),
    FieldSpec("tax_name", "Nama Wajib Pajak", section="Pajak"),
    # --- Kontak & Alamat ---
    FieldSpec("contact_person", "PIC (Contact Person)", section="Kontak & Alamat"),
    FieldSpec("email", "Email", section="Kontak & Alamat"),
    FieldSpec("phone", "Telepon", section="Kontak & Alamat"),
    FieldSpec("mobile", "HP", section="Kontak & Alamat"),
    FieldSpec("website", "Website", section="Kontak & Alamat"),
    FieldSpec("address", "Alamat", FieldType.TEXTAREA, section="Kontak & Alamat"),
    FieldSpec("city", "Kota", section="Kontak & Alamat"),
    FieldSpec("province", "Provinsi", section="Kontak & Alamat"),
    FieldSpec("postal_code", "Kode Pos", section="Kontak & Alamat"),
    FieldSpec(
        "country", "Negara (kode ISO 2 huruf)", default="ID", section="Kontak & Alamat"
    ),
    # --- Bank ---
    FieldSpec("bank_name", "Nama Bank", section="Bank"),
    FieldSpec("bank_account_number", "Nomor Rekening", section="Bank"),
    FieldSpec("bank_account_name", "Nama Pemilik Rekening", section="Bank"),
    # --- Keuangan ---
    FieldSpec(
        "payment_terms_days",
        "Termin Pembayaran (hari)",
        FieldType.NUMBER,
        default=30,
        section="Keuangan",
    ),
    FieldSpec(
        "credit_limit", "Limit Kredit", FieldType.DECIMAL, default=0, section="Keuangan"
    ),
    FieldSpec(
        "opening_balance",
        "Saldo Awal",
        FieldType.DECIMAL,
        default=0,
        section="Keuangan",
    ),
    FieldSpec(
        "opening_balance_date", "Tanggal Saldo Awal", FieldType.DATE, section="Keuangan"
    ),
    # --- Lainnya ---
    FieldSpec(
        "status",
        "Status",
        FieldType.SELECT,
        choices=(
            "active",
            "inactive",
            "blocked",
            "suspended",
            "blacklisted",
            "draft",
        ),
        default="active",
        section="Lainnya",
    ),
    FieldSpec("remarks", "Catatan", FieldType.TEXTAREA, section="Lainnya"),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("activate", "Aktifkan", path_suffix="/activate", style="success"),
    ActionSpec(
        "deactivate", "Nonaktifkan", path_suffix="/deactivate", style="danger"
    ),
]

CONFIG = ModuleConfig(
    key="suppliers",
    label="Pemasok (Supplier)",
    category="Master Data",
    icon="🏭",
    base_path="/suppliers",
    list_path="/suppliers",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
    edit_http_method="PATCH",
)


class SuppliersPage(GenericListPage):
    """Halaman Pemasok (Supplier), + tombol Detail & Limit Kredit."""

    button_permissions = (
        ("new_btn", "supplier:create"),
        ("edit_btn", "supplier:update"),
        ("action_btn", "supplier:update"),
        ("delete_btn", "supplier:delete"),
        ("import_btn", "supplier:import"),
        ("export_btn", "supplier:export"),
        ("credit_btn", "supplier:update"),
    )

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
        self._add_credit_limit_button()
        self._add_detail_button()
        self._apply_permission_gates()

    # ------------------------------------------------------------------
    def _make_form_dialog(self, title, fields, initial=None):
        """Form Tambah/Ubah Pemasok memakai tampilan modern (kartu per section)."""
        if initial:
            code = initial.get("supplier_code") or ""
            name = initial.get("name") or ""
            subtitle = " • ".join(x for x in (code, name) if x) or "Perbarui data pemasok."
            title, icon = "Ubah Pemasok (Supplier)", "✏️"
        else:
            subtitle = (
                "Isi data pemasok baru. Kode supplier dibuat otomatis jika dikosongkan."
            )
            title, icon = "Tambah Pemasok (Supplier) Baru", "🏭"
        return ModernFormDialog(
            title,
            fields,
            initial=initial,
            parent=self,
            icon=icon,
            subtitle=subtitle,
            columns=2,
            readonly_fields=("supplier_code",),
            send_empty_as_null=bool(initial),
        )

    # ------------------------------------------------------------------
    def _add_credit_limit_button(self) -> None:
        self.credit_btn = QPushButton("💳 Limit Kredit")
        self.credit_btn.setToolTip(
            "Ubah limit kredit supplier terpilih (tercatat di Riwayat Kredit)"
        )
        self.credit_btn.clicked.connect(self._change_credit_limit)
        toolbar_layout = self.layout().itemAt(1).layout()
        insert_at = (
            toolbar_layout.count() - 1
            if self.config.can_create
            else toolbar_layout.count()
        )
        toolbar_layout.insertWidget(insert_at, self.credit_btn)
        if hasattr(self, "_write_buttons"):
            self._write_buttons.append(self.credit_btn)

    def _change_credit_limit(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(
                self, "Info", "Pilih baris supplier terlebih dahulu."
            )
            return
        supplier_id = record.get(self.config.id_field)
        try:
            current = float(record.get("credit_limit") or 0)
        except (TypeError, ValueError):
            current = 0.0
        code = record.get("supplier_code") or ""
        name = record.get("name") or ""
        fields = [
            FieldSpec(
                "new_limit",
                "Limit Kredit Baru",
                FieldType.DECIMAL,
                required=True,
                min_value=0,
                section="Limit Kredit",
            ),
            FieldSpec(
                "reason",
                "Alasan Perubahan",
                FieldType.TEXTAREA,
                required=True,
                help_text="mis. Naik limit karena histori pembayaran baik",
                section="Limit Kredit",
            ),
        ]
        dlg = ModernFormDialog(
            "Ubah Limit Kredit",
            fields,
            initial={"new_limit": current},
            parent=self,
            icon="💳",
            columns=1,
            subtitle=f"{code} • {name}  |  Limit saat ini: Rp {current:,.2f}",
        )
        if not dlg.exec():
            return
        payload = dlg.result_payload()
        self.status_label.setText("Menyimpan limit kredit...")
        self._set_write_buttons_enabled(False)
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write("Limit kredit diperbarui."),
            on_error=self._on_write_error,
            path=(
                f"{self.config.base_path}"
                f"{self.config.list_path.rstrip('/')}/{supplier_id}/credit-limit"
            ),
            json_body=payload,
        )

    # ------------------------------------------------------------------
    def _add_detail_button(self) -> None:
        self.detail_btn = QPushButton("📋 Detail")
        self.detail_btn.clicked.connect(self._open_detail)
        toolbar_layout = self.layout().itemAt(1).layout()
        insert_at = (
            toolbar_layout.count() - 1
            if self.config.can_create
            else toolbar_layout.count()
        )
        toolbar_layout.insertWidget(insert_at, self.detail_btn)

    def _open_detail(self) -> None:
        from ui.pages.supplier_detail_dialog import SupplierDetailDialog

        record = self._selected_record()
        if not record:
            QMessageBox.information(
                self, "Info", "Pilih baris supplier terlebih dahulu."
            )
            return
        supplier_id = record.get(self.config.id_field)
        label = record.get("name") or record.get("supplier_code") or str(supplier_id)
        dlg = SupplierDetailDialog(str(supplier_id), str(label), parent=self)
        dlg.exec()
        self.refresh()

    # ------------------------------------------------------------------
    def _create_new(self) -> None:
        if not self.config.form_fields:
            QMessageBox.information(
                self, "Info", "Form untuk modul ini belum dikonfigurasi."
            )
            return
        self.status_label.setText("Menyiapkan kode supplier...")
        run_task(
            api_client.get,
            on_success=self._open_create_dialog_with_next_code,
            on_error=self._on_next_code_error,
            path=f"{self.config.base_path}/next-code",
        )

    def _open_create_dialog_with_next_code(self, response) -> None:
        self.status_label.setText("")
        next_code = ""
        if isinstance(response, dict):
            next_code = response.get("supplier_code", "") or ""
        self._show_create_dialog({"supplier_code": next_code} if next_code else None)

    def _on_next_code_error(self, message: str) -> None:
        self.status_label.setText("")
        self._show_create_dialog(None)

    def _show_create_dialog(self, initial: dict | None) -> None:
        dlg = self._make_form_dialog(
            f"Tambah {self.config.label}", self.config.form_fields, initial=initial
        )
        if dlg.exec():
            payload = dlg.result_payload()
            create_path = self.config.base_path + self.config.list_path
            self.status_label.setText("Menyimpan...")
            self._set_write_buttons_enabled(False)
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write(
                    "Data berhasil ditambahkan."
                ),
                on_error=self._on_write_error,
                path=create_path,
                json_body=payload,
            )
            