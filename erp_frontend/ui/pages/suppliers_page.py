"""
ui/pages/suppliers_page.py
=============================
Halaman modul "Pemasok (Supplier)" (Master Data).

Endpoint backend : /suppliers/suppliers  (prefix /api/v1 ditambahkan oleh api_client)

REGENERASI OTOMATIS dari registry/module_registry.py (sumber kebenaran
tunggal) supaya field/kolom/aksi SELALU sinkron dengan hasil audit
terhadap schema backend asli. Kalau perlu ubah field modul ini, ubah di
registry.py lalu salin ulang COLUMNS/FORM_FIELDS/ACTIONS ke bawah ini
(tidak ada skrip regenerasi otomatis di repo ini), JANGAN biarkan
keduanya berbeda lagi.

CATATAN SINKRONISASI (refactor Supplier/Vendor 2026-08):
    Field di bawah ini disinkronkan 1:1 dengan skema Pydantic
    `CreateSupplierRequest` / `UpdateSupplierRequest` /
    `SupplierResponseModel` di
    backend/adapters/primary_api/v1/fastapi_supplier_router.py, yang pada
    gilirannya dipetakan ke kolom tabel `supplier` di database oleh
    backend/adapters/secondary_impl/sqlalchemy_supplier_repository_impl.py.
    Field baru: company_name, tax_name, mobile, province, credit_limit,
    opening_balance, opening_balance_date, remarks, status, withholding_category.
"""
from __future__ import annotations

from core.api_client import api_client
from core.workers import run_task
from PySide6.QtWidgets import QMessageBox
from registry.module_registry import ActionSpec, FieldSpec, FieldType, ModuleConfig
from ui.widgets.form_dialog import FormDialog
from ui.widgets.generic_list_page import GenericListPage

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
    FieldSpec("supplier_code", "Kode Supplier", required=True,
              help_text="Kode unik supplier, mis. SUP-0001"),
    FieldSpec("name", "Nama Supplier", required=True),
    FieldSpec("company_name", "Nama Perusahaan"),
    FieldSpec("supplier_type", "Jenis Supplier", FieldType.SELECT,
              choices=("individual", "company", "government", "non_profit"),
              default="company",
              help_text="individual=perorangan, company=perusahaan, government=pemerintah, non_profit=nirlaba"),
    FieldSpec("withholding_category", "Kategori PPh", FieldType.SELECT,
              choices=("none", "pph23", "pph26", "both"), default="none"),
    # --- Pajak ---
    FieldSpec("npwp", "NPWP"),
    FieldSpec("tax_name", "Nama Wajib Pajak"),
    # --- Kontak ---
    FieldSpec("contact_person", "PIC (Contact Person)"),
    FieldSpec("email", "Email"),
    FieldSpec("phone", "Telepon"),
    FieldSpec("mobile", "HP"),
    FieldSpec("website", "Website"),
    # --- Alamat ---
    FieldSpec("address", "Alamat", FieldType.TEXTAREA),
    FieldSpec("city", "Kota"),
    FieldSpec("province", "Provinsi"),
    FieldSpec("postal_code", "Kode Pos"),
    FieldSpec("country", "Negara (kode ISO 2 huruf)", default="ID"),
    # --- Bank ---
    FieldSpec("bank_name", "Nama Bank"),
    FieldSpec("bank_account_number", "Nomor Rekening"),
    FieldSpec("bank_account_name", "Nama Pemilik Rekening"),
    # --- Keuangan ---
    FieldSpec("payment_terms_days", "Termin Pembayaran (hari)", FieldType.NUMBER, default=30),
    FieldSpec("credit_limit", "Limit Kredit", FieldType.DECIMAL, default=0),
    FieldSpec("opening_balance", "Saldo Awal", FieldType.DECIMAL, default=0),
    FieldSpec("opening_balance_date", "Tanggal Saldo Awal", FieldType.DATE),
    # --- Lainnya ---
    FieldSpec("status", "Status", FieldType.SELECT,
              choices=("active", "inactive", "blocked", "suspended"), default="active"),
    FieldSpec("remarks", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("activate", "Aktifkan", path_suffix="/activate", style="success"),
    ActionSpec("deactivate", "Nonaktifkan", path_suffix="/deactivate", style="danger"),
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
    """Halaman Pemasok (Supplier)."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)

    # ------------------------------------------------------------------
    # Auto-generate Kode Supplier saat tombol "Tambah" diklik.
    #
    # Alurnya: klik "Tambah" -> panggil GET /suppliers/next-code dulu di
    # background thread -> begitu dapat kodenya (mis. "SUP-004"), baru
    # form Tambah Supplier dibuka dengan field "Kode Supplier" sudah
    # otomatis terisi (masih bisa diedit manual kalau perlu).
    #
    # Kalau pengambilan kode gagal (mis. server lagi sibuk), form tetap
    # dibuka kosong seperti biasa supaya user tidak terblokir.
    # ------------------------------------------------------------------
    def _create_new(self) -> None:
        if not self.config.form_fields:
            QMessageBox.information(self, "Info", "Form untuk modul ini belum dikonfigurasi.")
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
        dlg = FormDialog(f"Tambah {self.config.label}", self.config.form_fields, initial=initial, parent=self)
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
