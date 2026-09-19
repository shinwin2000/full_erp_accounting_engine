"""
ui/pages/stock_movements_page.py
===================================
Halaman modul "Mutasi Stok" (Inventori).

Endpoint backend : /inventory/inventory/movements

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
#
# PENTING (fix): `item_id`, `warehouse_id`, dan `to_warehouse_id`
# sebelumnya berupa input teks UUID mentah yang harus diketik manual oleh
# user (harus copy-paste UUID dari tempat lain). Diganti dengan dropdown
# LOOKUP yang mengambil data asli dari /inventory/inventory/items dan
# /inventory/inventory/warehouses, jadi user memilih berdasarkan kode/nama
# yang familiar, bukan UUID. `reference_id` tetap dibiarkan sebagai UUID
# opsional karena bisa merujuk ke berbagai jenis dokumen (PO/SO/dll.)
# tergantung `reference_type`, tidak ada satu tabel tunggal untuk
# dropdown-nya.
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("item_id", "Item", FieldType.LOOKUP, required=True,
              lookup_path="/inventory/inventory/items",
              lookup_value_field="id",
              lookup_label_fields=("item_code", "item_name")),
    FieldSpec("movement_type", "Tipe Mutasi", FieldType.SELECT, required=True, choices=("IN", "OUT", "ADJUSTMENT", "TRANSFER_IN", "TRANSFER_OUT", "RETURN_IN", "RETURN_OUT", "SCRAP", "SAMPLE",)),
    FieldSpec("quantity", "Qty (harus lebih dari 0)", FieldType.DECIMAL, required=True,
              min_value=0.01, omit_if_zero=True),
    FieldSpec("unit_cost", "Harga Satuan (kosongkan jika ikut harga rata-rata)", FieldType.DECIMAL,
              min_value=0.01, omit_if_zero=True),
    FieldSpec("movement_date", "Tanggal", FieldType.DATE, required=True),
    FieldSpec("reference_type", "Tipe Referensi", required=True, help_text="mis. purchase_order, sales_order, production, adjustment"),
    FieldSpec("reference_id", "ID Referensi (UUID, opsional)", FieldType.UUID),
    FieldSpec("warehouse_id", "Gudang Asal", FieldType.LOOKUP, required=True,
              lookup_path="/inventory/inventory/warehouses",
              lookup_value_field="id",
              lookup_label_fields=("warehouse_code", "warehouse_name")),
    FieldSpec("to_warehouse_id", "Gudang Tujuan (wajib jika TRANSFER_IN/OUT)", FieldType.LOOKUP,
              lookup_path="/inventory/inventory/warehouses",
              lookup_value_field="id",
              lookup_label_fields=("warehouse_code", "warehouse_name")),
    FieldSpec("batch_number", "No. Batch"),
    FieldSpec("serial_number", "No. Serial"),
    FieldSpec("expiry_date", "Tanggal Kadaluarsa", FieldType.DATE),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
#
# PENTING (fix): sebelumnya `can_delete=True` padahal backend TIDAK punya
# endpoint DELETE /movements/{id} sama sekali (lihat
# fastapi_inventory_router.py) - tombol "Hapus" pasti berakhir 405 Method
# Not Allowed. Ini memang disengaja di sisi backend: mutasi stok adalah
# catatan akuntansi yang tidak boleh dihapus, melainkan dibalik lewat
# POST /movements/{id}/reverse (yang membuat mutasi lawan sehingga jejak
# audit tetap utuh). Jadi tombol Hapus dimatikan dan diganti aksi
# "Reverse". Endpoint reverse mewajibkan query param `reason` minimal 5
# karakter, jadi needs_reason/reason_min_length diisi.
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("reverse", "Reverse / Batalkan", path_suffix="/reverse", style="danger",
               needs_reason=True, reason_min_length=5),
]

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
    can_delete=False,
    search_param="search",
    edit_http_method="PUT",
)


class StockMovementsPage(GenericListPage):
    """Halaman Mutasi Stok."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
