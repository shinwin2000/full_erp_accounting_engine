"""
ui/pages/exchange_rates_page.py
==================================
Halaman modul "Kurs Mata Uang" (Treasury).

Endpoint backend : /currency-exchange/currency-exchange/rates

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
# Kolom tabel daftar Kurs Mata Uang
# ---------------------------------------------------------------------------
COLUMNS = [
    ("from_currency", "Dari"),
    ("to_currency", "Ke"),
    ("rate", "Kurs"),
    ("effective_date", "Tanggal Berlaku"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Kurs Mata Uang
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("from_currency", "Dari Mata Uang", required=True),
    FieldSpec("to_currency", "Ke Mata Uang", required=True),
    FieldSpec("rate", "Kurs", FieldType.DECIMAL, required=True),
    FieldSpec("rate_type", "Tipe Kurs", FieldType.SELECT, choices=("mid", "buy", "sell", "spot", "forward", "swap",), default="mid"),
    FieldSpec("effective_date", "Tanggal Berlaku", FieldType.DATE, required=True),
    FieldSpec("provider", "Sumber"),
    FieldSpec("bid_rate", "Bid Rate", FieldType.DECIMAL),
    FieldSpec("ask_rate", "Ask Rate", FieldType.DECIMAL),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="exchange_rates",
    label="Kurs Mata Uang",
    category="Treasury",
    icon="💱",
    base_path="/currency-exchange/currency-exchange",
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


class ExchangeRatesPage(GenericListPage):
    """Halaman Kurs Mata Uang."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
