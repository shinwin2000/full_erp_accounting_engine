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

FIX (audit 2026-09-15): field lama (goodwill_name, goodwill_type,
acquisition_cost, useful_life_years, amortization_method) tidak pernah
cocok dengan backend - lihat catatan lengkap di
application/service_layer/service_goodwill.py. Goodwill tidak
diamortisasi (PSAK 22/IFRS 3, impairment-only).
"""
from __future__ import annotations

from registry.module_registry import ActionSpec, FieldSpec, FieldType, ModuleConfig
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar Goodwill
# ---------------------------------------------------------------------------
COLUMNS = [
    ("goodwill_code", "Kode"),
    ("name", "Nama"),
    ("acquiree_name", "Entitas Diakuisisi"),
    ("goodwill_initial", "Nilai Goodwill Awal"),
    ("carrying_amount", "Nilai Tercatat"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Goodwill
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("goodwill_code", "Kode", required=True),
    FieldSpec("name", "Nama", required=True),
    FieldSpec("acquisition_date", "Tanggal Akuisisi", FieldType.DATE, required=True),
    FieldSpec("acquiree_name", "Nama Entitas yang Diakuisisi", required=True),
    FieldSpec("acquiree_tax_id", "NPWP Entitas yang Diakuisisi"),
    FieldSpec("purchase_price", "Harga Akuisisi", FieldType.DECIMAL, required=True),
    FieldSpec("fair_value_identifiable_net_assets", "Nilai Wajar Aset Bersih Teridentifikasi",
              FieldType.DECIMAL, required=True),
    FieldSpec("cash_generating_unit", "Cash Generating Unit"),
    FieldSpec("allocated_to_segment", "Segmen"),
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
    can_delete=False,
    search_param="search",
    edit_http_method="PUT",
)


class GoodwillPage(GenericListPage):
    """Halaman Goodwill."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
