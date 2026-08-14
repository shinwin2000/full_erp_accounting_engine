"""
ui/pages/fixed_assets_page.py
================================
Halaman modul "Aset Tetap" (Aset).

Endpoint backend : /fixed-assets/fixed-assets/assets

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
    FieldSpec("asset_category", "Kategori", FieldType.SELECT, required=True, choices=("building", "land", "machinery", "vehicle", "equipment", "furniture", "computer", "software", "leasehold", "other",)),
    FieldSpec("acquisition_date", "Tanggal Perolehan", FieldType.DATE, required=True),
    FieldSpec("acquisition_cost", "Harga Perolehan (harus > 0)", FieldType.DECIMAL, required=True),
    FieldSpec("residual_value", "Nilai Residu/Salvage (default 0)", FieldType.DECIMAL, default=0),
    FieldSpec("useful_life_years", "Umur Manfaat (tahun, harus > 0)", FieldType.NUMBER, required=True),
    FieldSpec("depreciation_method", "Metode Depresiasi", FieldType.SELECT, choices=("straight_line", "declining_balance", "double_declining", "sum_of_years", "units_of_production",), default="straight_line"),
    FieldSpec("depreciation_rate", "Tarif Depresiasi (%)", FieldType.DECIMAL),
    FieldSpec("location", "Lokasi"),
    FieldSpec("responsible_party", "Penanggung Jawab"),
    FieldSpec("serial_number", "No. Seri"),
    FieldSpec("supplier_id", "ID Supplier"),
    FieldSpec("invoice_number", "No. Faktur"),
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
    edit_http_method="PUT",
)


class FixedAssetsPage(GenericListPage):
    """Halaman Aset Tetap."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)