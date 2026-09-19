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

from registry.module_registry import FieldSpec, FieldType, ModuleConfig
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar Barang / Item
#
# PENTING (fix): sebelumnya hanya 5 kolom sederhana ditampilkan padahal
# backend (ItemResponseSchema di fastapi_inventory_router.py) sudah
# mengembalikan jauh lebih banyak field berguna (satuan, merek, stok
# berjalan, metode valuasi, status aktif). Ditambahkan di sini supaya
# daftar tidak terlihat "kosong"/simpel dibanding data yang sebenarnya ada.
# ---------------------------------------------------------------------------
COLUMNS = [
    ("item_code", "Kode"),
    ("item_name", "Nama Barang"),
    ("category", "Kategori"),
    ("brand", "Merek"),
    ("unit_of_measure", "Satuan"),
    ("current_stock", "Stok"),
    ("standard_cost", "HPP Standar"),
    ("selling_price", "Harga Jual"),
    ("valuation_method", "Metode Valuasi"),
    ("is_active", "Aktif"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Barang / Item
#
# PENTING (fix): pilihan `item_type` sebelumnya menyertakan
# "work_in_progress" dan "packaging" yang TIDAK ada di enum backend
# (adapters/primary_api/v1/fastapi_inventory_router.py: ItemType hanya
# raw_material/work_in_process/finished_good/trading/consumable/service/
# asset) - kalau user memilih salah satu dari keduanya, submit akan selalu
# gagal 422 "Input should be ...". Pilihan disamakan persis dengan enum
# backend. `warehouse_id` diubah dari input UUID mentah menjadi dropdown
# LOOKUP yang mengambil daftar gudang asli dari /inventory/inventory/
# warehouses, dan ditambahkan field weight_kg/volume_m3/is_active yang
# sebelumnya ada di schema backend tapi belum muncul di form. Field
# dikelompokkan per `section` supaya form besar ini tidak terlihat datar/
# simpel dan lebih mudah dipindai.
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    # -- Identitas --
    FieldSpec("item_code", "Kode Barang (min. 3 karakter)", required=True, section="Identitas"),
    FieldSpec("item_name", "Nama Barang (min. 3 karakter)", required=True, section="Identitas"),
    FieldSpec("item_type", "Tipe", FieldType.SELECT,
              choices=("raw_material", "work_in_process", "finished_good", "trading",
                       "consumable", "service", "asset"),
              default="trading", section="Identitas"),
    FieldSpec("category", "Kategori", section="Identitas"),
    FieldSpec("brand", "Merek", section="Identitas"),
    FieldSpec("unit_of_measure", "Satuan", default="pcs", section="Identitas"),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA, section="Identitas"),

    # -- Gudang & Stok --
    FieldSpec("warehouse_id", "Gudang Default", FieldType.LOOKUP,
              lookup_path="/inventory/inventory/warehouses",
              lookup_value_field="id",
              lookup_label_fields=("warehouse_code", "warehouse_name"),
              section="Gudang & Stok"),
    FieldSpec("reorder_point", "Titik Reorder", FieldType.DECIMAL, default=0, min_value=0, section="Gudang & Stok"),
    FieldSpec("reorder_quantity", "Jumlah Reorder", FieldType.DECIMAL, default=0, min_value=0, section="Gudang & Stok"),
    FieldSpec("min_stock", "Stok Minimum", FieldType.DECIMAL, default=0, min_value=0, section="Gudang & Stok"),
    FieldSpec("max_stock", "Stok Maksimum", FieldType.DECIMAL, default=0, min_value=0, section="Gudang & Stok"),
    FieldSpec("valuation_method", "Metode Valuasi", FieldType.SELECT,
              choices=("FIFO", "LIFO", "AVERAGE", "STANDARD"), default="FIFO", section="Gudang & Stok"),
    FieldSpec("is_lot_tracked", "Lacak per Batch/Lot", FieldType.BOOL, default=False, section="Gudang & Stok"),
    FieldSpec("is_serial_tracked", "Lacak per Serial Number", FieldType.BOOL, default=False, section="Gudang & Stok"),
    FieldSpec("is_expiry_tracked", "Lacak Tanggal Kadaluarsa", FieldType.BOOL, default=False, section="Gudang & Stok"),

    # -- Harga & Pajak --
    FieldSpec("standard_cost", "HPP Standar", FieldType.DECIMAL, default=0, min_value=0, section="Harga & Pajak"),
    FieldSpec("selling_price", "Harga Jual", FieldType.DECIMAL, default=0, min_value=0, section="Harga & Pajak"),
    FieldSpec("tax_rate_purchase", "Tarif Pajak Pembelian (%)", FieldType.DECIMAL, default=11, min_value=0, section="Harga & Pajak"),
    FieldSpec("tax_rate_sales", "Tarif Pajak Penjualan (%)", FieldType.DECIMAL, default=11, min_value=0, section="Harga & Pajak"),

    # -- Dimensi & Status --
    FieldSpec("weight_kg", "Berat (kg)", FieldType.DECIMAL, min_value=0, section="Dimensi & Status"),
    FieldSpec("volume_m3", "Volume (m3)", FieldType.DECIMAL, min_value=0, section="Dimensi & Status"),
    FieldSpec("is_active", "Aktif", FieldType.BOOL, default=True, section="Dimensi & Status"),
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