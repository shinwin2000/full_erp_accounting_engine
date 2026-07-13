"""
ui/pages/fixed_assets_page.py
================================
Halaman modul "Aset Tetap" (Aset).

Endpoint backend : /fixed-assets/fixed-assets/assets
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
# Kolom tabel daftar Aset Tetap
# ---------------------------------------------------------------------------
COLUMNS = [
    ("asset_code", "Kode"),
    ("asset_name", "Nama Aset"),
    ("asset_category", "Kategori"),
    ("acquisition_cost", "Harga Perolehan"),
    ("depreciation_method", "Metode Depresiasi"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Aset Tetap
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("asset_code", "Kode Aset", required=True),
    FieldSpec("asset_name", "Nama Aset", required=True),
    FieldSpec("asset_category", "Kategori", required=True),
    FieldSpec("acquisition_date", "Tanggal Perolehan", FieldType.DATE, required=True),
    FieldSpec("acquisition_cost", "Harga Perolehan", FieldType.DECIMAL, required=True),
    FieldSpec("residual_value", "Nilai Residu", FieldType.DECIMAL, default=0),
    FieldSpec("useful_life_years", "Umur Manfaat (tahun)", FieldType.NUMBER, required=True),
    FieldSpec("depreciation_method", "Metode Depresiasi", FieldType.SELECT, choices=("straight_line", "declining_balance", "units_of_production", "sum_of_years",)),
    FieldSpec("depreciation_rate", "Tarif Depresiasi (%)", FieldType.DECIMAL),
    FieldSpec("location", "Lokasi"),
    FieldSpec("responsible_party", "Penanggung Jawab"),
    FieldSpec("serial_number", "No. Seri"),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("run-depreciation", "Jalankan Depresiasi", path_suffix="/depreciate", style="primary"),
    ActionSpec("dispose", "Dispose Asset", path_suffix="/dispose", style="danger"),
]

CONFIG = ModuleConfig(
    key="fixed_assets",
    label="Aset Tetap",
    category="Aset",
    icon="🏗️",
    base_path="/fixed-assets/fixed-assets",
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


class FixedAssetsPage(GenericListPage):
    """Halaman Aset Tetap."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
