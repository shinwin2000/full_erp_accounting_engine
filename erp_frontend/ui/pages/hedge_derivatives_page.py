"""
ui/pages/hedge_derivatives_page.py
=====================================
Halaman modul "Instrumen Derivatif" (Treasury).

Endpoint backend : /hedge/hedge/derivatives

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
# Kolom tabel daftar Instrumen Derivatif
# ---------------------------------------------------------------------------
COLUMNS = [
    ("instrument_code", "Kode"),
    ("derivative_type", "Tipe"),
    ("notional_amount", "Notional"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Instrumen Derivatif
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("instrument_code", "Kode Instrumen", required=True),
    FieldSpec("instrument_name", "Nama Instrumen", required=True),
    FieldSpec("derivative_type", "Tipe Derivatif", FieldType.SELECT, choices=("forward", "futures", "option_call", "option_put", "swap_irs", "swap_ccs", "swap_cds", "warrant", "structured",)),
    FieldSpec("counterparty_id", "Counterparty (UUID)", FieldType.UUID),
    FieldSpec("underlying_asset", "Underlying Asset"),
    FieldSpec("notional_amount", "Notional Amount", FieldType.DECIMAL, required=True),
    FieldSpec("currency_code", "Mata Uang", required=True),
    FieldSpec("contract_date", "Tanggal Kontrak", FieldType.DATE, required=True),
    FieldSpec("settlement_date", "Tanggal Settlement", FieldType.DATE),
    FieldSpec("maturity_date", "Tanggal Jatuh Tempo", FieldType.DATE),
    FieldSpec("strike_price", "Strike Price", FieldType.DECIMAL),
    FieldSpec("premium_paid", "Premium Dibayar", FieldType.DECIMAL),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="hedge_derivatives",
    label="Instrumen Derivatif",
    category="Treasury",
    icon="📈",
    base_path="/hedge/hedge",
    list_path="/derivatives",
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


class HedgeDerivativesPage(GenericListPage):
    """Halaman Instrumen Derivatif."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
