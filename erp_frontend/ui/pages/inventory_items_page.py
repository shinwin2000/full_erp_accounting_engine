"""
ui/pages/inventory_items_page.py
===================================
Halaman modul "Barang / Item" (Inventori).

Endpoint backend : /inventory/inventory/items

REGENERASI OTOMATIS dari registry/module_registry.py (sumber kebenaran
tunggal) supaya field/kolom/aksi SELALU sinkron dengan hasil audit
terhadap schema backend asli — sebelumnya file mandiri ini py bisa jadi
kadaluarsa dibanding registry.py setelah audit, karena keduanya sempat
didefinisikan terpisah. Kalau perlu ubah field modul ini, ubah di
registry.py lalu jalankan ulang skrip regenerasi, JANGAN edit file ini
langsung supaya tidak2 desinkron lagi.
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
    FieldSpec("item_code", "Kode Barang (min. 3 karakter)", required=True),
    FieldSpec("item_name", "Nama Barang (min. 3 karakter)", required=True),
    FieldSpec("item_type", "Tipe", FieldType.SELECT, choices=("raw_material", "work_in_process", "finished_good", "trading", "consumable", "service",), default="trading"),
    FieldSpec("unit_of_measure", "Satuan", default="pcs"),
    FieldSpec("category", "Kategori"),
    FieldSpec("brand", "Merek"),
    FieldSpec("reorder_point", "Titik Reorder", FieldType.DECIMAL, default=0),
    FieldSpec("reorder_quantity", "Jumlah Reorder", FieldType.DECIMAL, default=0),
    FieldSpec("standard_cost", "HPP Standar", FieldType.DECIMAL, default=0),
    FieldSpec("selling_price", "Harga Jual", FieldType.DECIMAL, default=0),
    FieldSpec("valuation_method", "Metode Valuasi", FieldType.SELECT, choices=("FIFO", "LIFO", "AVERAGE", "STANDARD",), default="FIFO"),
    FieldSpec("warehouse_id", "Gudang Default (UUID, opsional)", FieldType.UUID),
    FieldSpec("min_stock", "Stok Minimum", FieldType.DECIMAL, default=0),
    FieldSpec("max_stock", "Stok Maksimum", FieldType.DECIMAL, default=0),
    FieldSpec("tax_rate_purchase", "Tarif Pajak Pembelian (%)", FieldType.DECIMAL, default=11),
    FieldSpec("tax_rate_sales", "Tarif Pajak Penjualan (%)", FieldType.DECIMAL, default=11),
    FieldSpec("is_lot_tracked", "Lacak per Batch/Lot", FieldType.BOOL, default=False),
    FieldSpec("is_serial_tracked", "Lacak per Serial Number", FieldType.BOOL, default=False),
    FieldSpec("is_expiry_tracked", "Lacak Tanggal Kadaluarsa", FieldType.BOOL, default=False),
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
    edit_http_method="PUT",
)


class InventoryItemsPage(GenericListPage):
    """Halaman Barang / Item."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
