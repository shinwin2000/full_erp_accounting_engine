"""
ui/pages/forex_page.py
=========================
Halaman modul "Forex & Revaluasi" (Treasury).

Endpoint backend : /forex/forex/rates

REGENERASI OTOMATIS dari registry/module_registry.py (sumber kebenaran
tunggal) supaya field/kolom/aksi SELALU sinkron dengan hasil audit
terhadap schema backend asli — sebelumnya file mandiri ini py bisa jadi
kadaluarsa dibanding registry.py setelah audit, karena keduanya sempat
didefinisikan terpisah. Kalau perlu ubah field modul ini, ubah di
registry.py lalu jalankan ulang skrip regenerasi, JANGAN edit file ini
langsung supaya tidak2 desinkron lagi.
"""
from __future__ import annotations

from registry.module_registry import FieldSpec, FieldType, ModuleConfig
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar Forex & Revaluasi
# ---------------------------------------------------------------------------
COLUMNS = [
    ("from_currency", "Dari"),
    ("to_currency", "Ke"),
    ("rate", "Kurs"),
    ("effective_date", "Tanggal"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Forex & Revaluasi
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("from_currency", "Dari Mata Uang", required=True),
    FieldSpec("to_currency", "Ke Mata Uang", required=True),
    FieldSpec("rate", "Kurs", FieldType.DECIMAL, required=True),
    FieldSpec("effective_date", "Tanggal Berlaku", FieldType.DATE, required=True),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="forex",
    label="Forex & Revaluasi",
    category="Treasury",
    icon="🌐",
    base_path="/forex/forex",
    list_path="/rates",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=False,
    can_delete=True,
    search_param="search",
    edit_http_method="PUT",
)


class ForexPage(GenericListPage):
    """Halaman Forex & Revaluasi."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
