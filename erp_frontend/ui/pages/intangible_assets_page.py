"""
ui/pages/intangible_assets_page.py
=====================================
Halaman modul "Aset Tak Berwujud" (Aset).

Endpoint backend : /intangible-assets/intangible-assets/

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
# Kolom tabel daftar Aset Tak Berwujud
# ---------------------------------------------------------------------------
COLUMNS = [
    ("asset_code", "Kode"),
    ("asset_name", "Nama"),
    ("asset_category", "Kategori"),
    ("acquisition_cost", "Harga Perolehan"),
    ("amortization_method", "Metode Amortisasi"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Aset Tak Berwujud
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("asset_code", "Kode Aset", required=True),
    FieldSpec("asset_name", "Nama Aset", required=True),
    FieldSpec("asset_category", "Kategori", FieldType.SELECT, required=True, choices=("patent", "trademark", "copyright", "software", "license", "franchise", "goodwill", "customer_relationship",)),
    FieldSpec("acquisition_date", "Tanggal Perolehan", FieldType.DATE, required=True),
    FieldSpec("acquisition_cost", "Harga Perolehan", FieldType.DECIMAL, required=True),
    FieldSpec("residual_value", "Nilai Residu", FieldType.DECIMAL, default=0),
    FieldSpec("useful_life_years", "Umur Manfaat (tahun)", FieldType.NUMBER, required=True),
    FieldSpec("amortization_method", "Metode Amortisasi", FieldType.SELECT, choices=("straight_line", "declining_balance", "double_declining", "sum_of_years", "units_of_production",), default="straight_line"),
    FieldSpec("registration_number", "No. Registrasi"),
    FieldSpec("issuing_authority", "Penerbit"),
    FieldSpec("expiry_date", "Tanggal Kadaluarsa", FieldType.DATE),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="intangible_assets",
    label="Aset Tak Berwujud",
    category="Aset",
    icon="💡",
    base_path="/intangible-assets/intangible-assets",
    list_path="/",
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


class IntangibleAssetsPage(GenericListPage):
    """Halaman Aset Tak Berwujud."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
