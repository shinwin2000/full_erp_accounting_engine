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
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("item_id", "Item (UUID)", FieldType.UUID, required=True),
    FieldSpec("movement_type", "Tipe Mutasi", FieldType.SELECT, required=True, choices=("IN", "OUT", "ADJUSTMENT", "TRANSFER_IN", "TRANSFER_OUT", "RETURN_IN", "RETURN_OUT", "SCRAP",)),
    FieldSpec("quantity", "Qty (harus > 0)", FieldType.DECIMAL, required=True),
    FieldSpec("unit_cost", "Harga Satuan", FieldType.DECIMAL),
    FieldSpec("movement_date", "Tanggal", FieldType.DATE, required=True),
    FieldSpec("reference_type", "Tipe Referensi", required=True, help_text="mis. purchase_order, sales_order, production, adjustment"),
    FieldSpec("reference_id", "ID Referensi (UUID, opsional)", FieldType.UUID),
    FieldSpec("warehouse_id", "Gudang Asal (UUID)", FieldType.UUID, required=True),
    FieldSpec("to_warehouse_id", "Gudang Tujuan (UUID, wajib jika TRANSFER_IN/OUT)", FieldType.UUID),
    FieldSpec("batch_number", "No. Batch"),
    FieldSpec("serial_number", "No. Serial"),
    FieldSpec("expiry_date", "Tanggal Kadaluarsa", FieldType.DATE),
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
    edit_http_method="PUT",
)


class StockMovementsPage(GenericListPage):
    """Halaman Mutasi Stok."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
