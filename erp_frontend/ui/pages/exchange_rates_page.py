"""
ui/pages/exchange_rates_page.py
==================================
Halaman modul "Kurs Mata Uang" (Treasury).

Endpoint backend : /currency-exchange/currency-exchange/rates
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
    FieldSpec("rate_type", "Tipe Kurs", FieldType.SELECT, choices=("spot", "middle", "buy", "sell", "kmk",)),
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
)


class ExchangeRatesPage(GenericListPage):
    """Halaman Kurs Mata Uang."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
