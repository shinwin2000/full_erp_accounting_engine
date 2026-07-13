"""
ui/pages/stock_movements_page.py
===================================
Halaman modul "Mutasi Stok" (Inventori).

Endpoint backend : /inventory/inventory/movements
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
# Kolom tabel daftar Mutasi Stok
# ---------------------------------------------------------------------------
COLUMNS = [
    ("movement_date", "Tanggal"),
    ("movement_type", "Tipe"),
    ("quantity", "Qty"),
    ("unit_cost", "Harga Satuan"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Mutasi Stok
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("item_id", "Item (UUID)", FieldType.UUID, required=True),
    FieldSpec("movement_type", "Tipe Mutasi", FieldType.SELECT, required=True, choices=("receipt", "issue", "transfer", "adjustment",)),
    FieldSpec("quantity", "Qty", FieldType.DECIMAL, required=True),
    FieldSpec("unit_cost", "Harga Satuan", FieldType.DECIMAL),
    FieldSpec("movement_date", "Tanggal", FieldType.DATE, required=True),
    FieldSpec("warehouse_id", "Gudang (UUID)", FieldType.UUID),
    FieldSpec("to_warehouse_id", "Gudang Tujuan (UUID)", FieldType.UUID),
    FieldSpec("batch_number", "No. Batch"),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="stock_movements",
    label="Mutasi Stok",
    category="Inventori",
    icon="🔄",
    base_path="/inventory/inventory",
    list_path="/movements",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=False,
    can_delete=True,
    search_param="search",
)


class StockMovementsPage(GenericListPage):
    """Halaman Mutasi Stok."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
