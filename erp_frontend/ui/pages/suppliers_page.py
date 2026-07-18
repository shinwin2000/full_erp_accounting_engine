"""
ui/pages/suppliers_page.py
=============================
Halaman modul "Pemasok (Supplier)" (Master Data).

Endpoint backend : /suppliers/suppliers
Router asal      : lihat adapters/primary_api/v1/fastapi_*_router.py terkait

Kolom tabel, field form, dan aksi workflow modul ini didefinisikan LANGSUNG
di file ini (bukan dirujuk dari file lain) supaya isi file mencerminkan
struktur data modul backend secara langsung dan mudah dibaca/diaudit per
modul, tanpa perlu membuka file lain untuk memahami field apa saja yang
dipakai. Widget tabel + form generik (GenericListPage) tetap dipakai
bersama supaya perilaku CRUD & workflow-nya konsisten antar modul.
"""
from __future__ import annotations

from registry.module_registry import ActionSpec, FieldSpec, FieldType, ModuleConfig
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar Pemasok (Supplier)
# ---------------------------------------------------------------------------
COLUMNS = [
    ("supplier_code", "Kode"),
    ("name", "Nama"),
    ("city", "Kota"),
    ("payment_terms_days", "Termin (hari)"),
    ("is_active", "Aktif"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Pemasok (Supplier)
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("supplier_code", "Kode Supplier", required=True),
    FieldSpec("name", "Nama", required=True),
    FieldSpec("npwp", "NPWP"),
    FieldSpec("address", "Alamat", FieldType.TEXTAREA),
    FieldSpec("city", "Kota"),
    FieldSpec("country", "Negara", default="Indonesia"),
    FieldSpec("phone", "Telepon"),
    FieldSpec("email", "Email"),
    FieldSpec("contact_person", "Contact Person"),
    FieldSpec("payment_terms_days", "Termin Pembayaran (hari)", FieldType.NUMBER),
    FieldSpec("credit_limit", "Limit Kredit", FieldType.DECIMAL),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

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
