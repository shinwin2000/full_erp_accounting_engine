"""
ui/pages/warehouses_page.py
==============================
Halaman modul "Gudang" (Inventori).

Endpoint backend : /inventory/inventory/warehouses
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
# Kolom tabel daftar Gudang
# ---------------------------------------------------------------------------
COLUMNS = [
    ("warehouse_code", "Kode"),
    ("warehouse_name", "Nama"),
    ("location", "Lokasi"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Gudang
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("warehouse_code", "Kode Gudang", required=True),
    FieldSpec("warehouse_name", "Nama Gudang", required=True),
    FieldSpec("location", "Lokasi"),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="warehouses",
    label="Gudang",
    category="Inventori",
    icon="🏬",
    base_path="/inventory/inventory",
    list_path="/warehouses",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class WarehousesPage(GenericListPage):
    """Halaman Gudang."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
