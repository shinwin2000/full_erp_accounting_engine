"""
ui/pages/goodwill_page.py
============================
Halaman modul "Goodwill" (Aset).

Endpoint backend : /goodwill/goodwill/
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
# Kolom tabel daftar Goodwill
# ---------------------------------------------------------------------------
COLUMNS = [
    ("goodwill_code", "Kode"),
    ("goodwill_name", "Nama"),
    ("acquisition_cost", "Nilai Perolehan"),
    ("useful_life_years", "Umur Manfaat"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Goodwill
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("goodwill_code", "Kode", required=True),
    FieldSpec("goodwill_name", "Nama", required=True),
    FieldSpec("goodwill_type", "Tipe"),
    FieldSpec("acquisition_date", "Tanggal Akuisisi", FieldType.DATE, required=True),
    FieldSpec("acquisition_cost", "Nilai Perolehan", FieldType.DECIMAL, required=True),
    FieldSpec("cash_generating_unit", "Cash Generating Unit"),
    FieldSpec("useful_life_years", "Umur Manfaat (tahun)", FieldType.NUMBER),
    FieldSpec("amortization_method", "Metode Amortisasi"),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("impairment-test", "Uji Penurunan Nilai", path_suffix="/impairment-tests", style="primary"),
]

CONFIG = ModuleConfig(
    key="goodwill",
    label="Goodwill",
    category="Aset",
    icon="⭐",
    base_path="/goodwill/goodwill",
    list_path="/",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class GoodwillPage(GenericListPage):
    """Halaman Goodwill."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
