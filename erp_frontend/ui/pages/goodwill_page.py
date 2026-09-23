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
# Field form KHUSUS untuk "Ubah" - field penentu nilai goodwill (harga
# akuisisi, nilai wajar aset bersih, tanggal, kode, entitas diakuisisi)
# dikunci sejak pengakuan awal (standar akuntansi), backend memang tidak
# menerima perubahan itu lewat update - lihat catatan di registry.py.
# ---------------------------------------------------------------------------
EDIT_FORM_FIELDS = [
    FieldSpec("name", "Nama", required=True),
    FieldSpec("cash_generating_unit", "Cash Generating Unit"),
    FieldSpec("allocated_to_segment", "Segmen"),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec(
        "impairment-test", "Uji Penurunan Nilai", path_suffix="/impairment-tests", style="primary",
        confirm=False,
        action_fields=[
            FieldSpec("test_date", "Tanggal Uji", FieldType.DATE, required=True),
            FieldSpec("recoverable_amount", "Jumlah Terpulihkan (Recoverable Amount)",
                      FieldType.DECIMAL, required=True),
            FieldSpec("valuation_method", "Metode Valuasi", FieldType.SELECT,
                      choices=("fair_value_less_cost", "value_in_use"),
                      default="fair_value_less_cost"),
            FieldSpec("discount_rate", "Tingkat Diskonto (0-1, opsional)", FieldType.DECIMAL, min_value=0),
            FieldSpec("growth_rate", "Tingkat Pertumbuhan (opsional)", FieldType.DECIMAL),
            FieldSpec("impairment_source", "Sumber Uji", FieldType.SELECT,
                      choices=("annual_test", "trigger_based", "disposal", "reversal"),
                      default="annual_test"),
            FieldSpec("description", "Keterangan", FieldType.TEXTAREA),
        ],
    ),
    # PENTING: reversal impairment goodwill DILARANG oleh IFRS/PSAK kecuali
    # untuk koreksi kesalahan input - lihat peringatan di
    # GoodwillService.reverse_impairment (service_goodwill.py).
    ActionSpec(
        "reverse-impairment", "Batalkan Penurunan Nilai (Reversal)",
        path_suffix="/reverse-impairment", style="danger",
        confirm=False,
        action_fields=[
            FieldSpec("reversal_date", "Tanggal Reversal", FieldType.DATE, required=True),
            FieldSpec("reversal_amount", "Jumlah Reversal", FieldType.DECIMAL, required=True),
            FieldSpec("reason", "Alasan (wajib, koreksi kesalahan input saja)",
                      FieldType.TEXTAREA, required=True),
        ],
    ),
    ActionSpec(
        "dispose", "Lepas Goodwill (Dispose)", path_suffix="/dispose", style="danger",
        confirm=False,
        action_fields=[
            FieldSpec("disposal_date", "Tanggal Pelepasan", FieldType.DATE, required=True),
            FieldSpec("proceeds", "Hasil Pelepasan (jika ada)", FieldType.DECIMAL, default=0),
            FieldSpec("reason", "Alasan", FieldType.TEXTAREA),
        ],
    ),
    ActionSpec(
        "impairment-history", "Riwayat Uji Impairment", method="GET",
        path_suffix="/impairment-tests", style="default", confirm=False,
    ),
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
    edit_form_fields=EDIT_FORM_FIELDS,
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
