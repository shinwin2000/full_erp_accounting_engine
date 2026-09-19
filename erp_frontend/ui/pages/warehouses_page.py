"""
ui/pages/warehouses_page.py
==============================
Halaman modul "Gudang" (Inventori).

Endpoint backend : /inventory/inventory/warehouses

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
# Kolom tabel daftar Gudang
# ---------------------------------------------------------------------------
COLUMNS = [
    ("warehouse_code", "Kode"),
    ("warehouse_name", "Nama"),
    ("location", "Lokasi"),
    ("is_default", "Default"),
    ("is_active", "Aktif"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Gudang
#
# PENTING (fix): sebelumnya modul ini TIDAK BISA menyimpan sama sekali -
# backend hanya punya endpoint GET /inventory/inventory/warehouses, tombol
# "+ Baru"/"Ubah"/"Hapus" di halaman ini selalu berakhir 405 Method Not
# Allowed. Endpoint POST/PUT/DELETE /warehouses sudah ditambahkan di
# adapters/primary_api/v1/fastapi_inventory_router.py (create_warehouse/
# update_warehouse/delete_warehouse). Field form dilengkapi supaya cocok
# dengan WarehouseCreateSchema/WarehouseUpdateSchema yang sebenarnya
# (sebelumnya is_active/is_default/notes tidak ada di form sama sekali).
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("warehouse_code", "Kode Gudang", required=True),
    FieldSpec("warehouse_name", "Nama Gudang", required=True),
    FieldSpec("location", "Lokasi"),
    FieldSpec("is_active", "Aktif", FieldType.BOOL, default=True),
    FieldSpec("is_default", "Jadikan Gudang Default", FieldType.BOOL, default=False),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Field KHUSUS untuk form "Ubah" - kode gudang (warehouse_code) sengaja
# tidak bisa diubah lagi setelah dibuat (backend WarehouseUpdateSchema
# tidak menerima warehouse_code sama sekali), supaya kode yang sudah
# dipakai di transaksi/mutasi stok lain tetap konsisten.
# ---------------------------------------------------------------------------
EDIT_FORM_FIELDS = [
    FieldSpec("warehouse_name", "Nama Gudang", required=True),
    FieldSpec("location", "Lokasi"),
    FieldSpec("is_active", "Aktif", FieldType.BOOL, default=True),
    FieldSpec("is_default", "Jadikan Gudang Default", FieldType.BOOL, default=False),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
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
    edit_form_fields=EDIT_FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
    edit_http_method="PUT",
)


class WarehousesPage(GenericListPage):
    """Halaman Gudang."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
