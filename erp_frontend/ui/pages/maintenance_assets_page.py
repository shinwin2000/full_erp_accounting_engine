"""
ui/pages/maintenance_assets_page.py
======================================
Halaman modul "Aset Maintenance" (Aset).

Endpoint backend : /maintenance/maintenance/assets

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
# Kolom tabel daftar Aset Maintenance
# ---------------------------------------------------------------------------
COLUMNS = [
    ("asset_code", "Kode"),
    ("asset_name", "Nama"),
    ("location", "Lokasi"),
    ("manufacturer", "Pabrikan"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Aset Maintenance
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("asset_code", "Kode Aset", required=True),
    FieldSpec("asset_name", "Nama Aset", required=True),
    FieldSpec("asset_category", "Kategori (min. karakter bebas)", required=True),
    FieldSpec("location", "Lokasi"),
    FieldSpec("serial_number", "No. Seri"),
    FieldSpec("manufacturer", "Pabrikan"),
    FieldSpec("model", "Model"),
    FieldSpec("purchase_date", "Tanggal Pembelian", FieldType.DATE),
    FieldSpec("warranty_expiry_date", "Garansi s/d", FieldType.DATE),
    FieldSpec("maintenance_interval_days", "Interval Maintenance (hari)", FieldType.NUMBER),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="maintenance_assets",
    label="Aset Maintenance",
    category="Aset",
    icon="🔧",
    base_path="/maintenance/maintenance",
    list_path="/assets",
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


class MaintenanceAssetsPage(GenericListPage):
    """Halaman Aset Maintenance."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
