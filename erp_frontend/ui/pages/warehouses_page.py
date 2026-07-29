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

from registry.module_registry import FieldSpec, ModuleConfig
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
    edit_http_method="PUT",
)


class WarehousesPage(GenericListPage):
    """Halaman Gudang."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
