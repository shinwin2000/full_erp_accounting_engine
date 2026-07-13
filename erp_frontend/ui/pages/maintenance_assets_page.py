"""
ui/pages/maintenance_assets_page.py
======================================
Halaman modul "Aset Maintenance" (Aset).

Endpoint backend : /maintenance/maintenance/assets
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
    FieldSpec("asset_category", "Kategori"),
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
)


class MaintenanceAssetsPage(GenericListPage):
    """Halaman Aset Maintenance."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
