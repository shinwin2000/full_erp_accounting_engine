"""
ui/pages/goodwill_page.py
============================
Halaman modul "Goodwill" (Aset).

Endpoint backend : /goodwill/goodwill/

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
    FieldSpec("goodwill_type", "Tipe", FieldType.SELECT, choices=("purchase", "bargain", "internal", "consolidation",), default="purchase"),
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
    edit_http_method="PUT",
)


class GoodwillPage(GenericListPage):
    """Halaman Goodwill."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
