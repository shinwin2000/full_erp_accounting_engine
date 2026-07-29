"""
ui/pages/routing_page.py
===========================
Halaman modul "Routing Produksi" (Manufaktur).

Endpoint backend : /manufacturing/manufacturing/routing
Router asal      : lihat adapters/primary_api/v1/fastapi_*_router.py terkait

Kolom tabel, field form, dan aksi workflow modul ini didefinisikan LANGSUNG
di file ini (bukan dirujuk dari file lain) supaya isi file mencerminkan
struktur data modul backend secara langsung dan mudah dibaca/diaudit per
modul, tanpa perlu membuka file lain untuk memahami field apa saja yang
dipakai. Widget tabel + form generik (GenericListPage) tetap dipakai
bersama supaya perilaku CRUD & workflow-nya konsisten antar modul.
"""
from __future__ import annotations

from registry.module_registry import FieldSpec, FieldType, ModuleConfig
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar Routing Produksi
# ---------------------------------------------------------------------------
COLUMNS = [
    ("routing_code", "Kode"),
    ("routing_name", "Nama"),
    ("routing_version", "Versi"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Routing Produksi
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("routing_code", "Kode Routing", required=True),
    FieldSpec("routing_name", "Nama Routing", required=True),
    FieldSpec("product_id", "Produk (UUID)", FieldType.UUID, required=True),
    FieldSpec("routing_version", "Versi", default="1.0"),
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
    key="routing",
    label="Routing Produksi",
    category="Manufaktur",
    icon="🧭",
    base_path="/manufacturing/manufacturing",
    list_path="/routing",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class RoutingPage(GenericListPage):
    """Halaman Routing Produksi."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
