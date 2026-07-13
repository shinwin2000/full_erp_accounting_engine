"""
ui/pages/bom_page.py
=======================
Halaman modul "Bill of Materials" (Manufaktur).

Endpoint backend : /manufacturing/manufacturing/bom
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
# Kolom tabel daftar Bill of Materials
# ---------------------------------------------------------------------------
COLUMNS = [
    ("bom_code", "Kode BOM"),
    ("bom_name", "Nama"),
    ("bom_version", "Versi"),
    ("is_default", "Default"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Bill of Materials
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("bom_code", "Kode BOM", required=True),
    FieldSpec("bom_name", "Nama BOM", required=True),
    FieldSpec("product_id", "Produk (UUID)", FieldType.UUID, required=True),
    FieldSpec("bom_version", "Versi", default="1.0"),
    FieldSpec("effective_date", "Berlaku Sejak", FieldType.DATE, required=True),
    FieldSpec("expiry_date", "Berlaku Sampai", FieldType.DATE),
    FieldSpec("is_default", "Default", FieldType.BOOL, default=False),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="bom",
    label="Bill of Materials",
    category="Manufaktur",
    icon="📐",
    base_path="/manufacturing/manufacturing",
    list_path="/bom",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class BomPage(GenericListPage):
    """Halaman Bill of Materials."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
