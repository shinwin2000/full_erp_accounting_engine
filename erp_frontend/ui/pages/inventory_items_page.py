"""
ui/pages/inventory_items_page.py
===================================
Halaman modul "Barang / Item" (Inventori).

Endpoint backend : /inventory/inventory/items
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
# Kolom tabel daftar Barang / Item
# ---------------------------------------------------------------------------
COLUMNS = [
    ("item_code", "Kode"),
    ("item_name", "Nama Barang"),
    ("category", "Kategori"),
    ("standard_cost", "HPP Standar"),
    ("selling_price", "Harga Jual"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Barang / Item
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("item_code", "Kode Barang", required=True),
    FieldSpec("item_name", "Nama Barang", required=True),
    FieldSpec("item_type", "Tipe", FieldType.SELECT, choices=("raw_material", "finished_good", "service", "trading",)),
    FieldSpec("unit_of_measure", "Satuan", required=True),
    FieldSpec("category", "Kategori"),
    FieldSpec("brand", "Merek"),
    FieldSpec("reorder_point", "Titik Reorder", FieldType.NUMBER),
    FieldSpec("reorder_quantity", "Jumlah Reorder", FieldType.NUMBER),
    FieldSpec("standard_cost", "HPP Standar", FieldType.DECIMAL),
    FieldSpec("selling_price", "Harga Jual", FieldType.DECIMAL),
    FieldSpec("valuation_method", "Metode Valuasi", FieldType.SELECT, choices=("FIFO", "LIFO", "AVERAGE", "STANDARD",)),
    FieldSpec("min_stock", "Stok Minimum", FieldType.NUMBER),
    FieldSpec("max_stock", "Stok Maksimum", FieldType.NUMBER),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="inventory_items",
    label="Barang / Item",
    category="Inventori",
    icon="📦",
    base_path="/inventory/inventory",
    list_path="/items",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class InventoryItemsPage(GenericListPage):
    """Halaman Barang / Item."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
