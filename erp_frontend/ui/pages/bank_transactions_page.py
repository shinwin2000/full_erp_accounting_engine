"""
ui/pages/bank_transactions_page.py
=====================================
Halaman modul "Transaksi Bank/Kas" (Kas & Bank).

Endpoint backend : /bank-cash/bank-cash/transactions
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
# Kolom tabel daftar Transaksi Bank/Kas
# ---------------------------------------------------------------------------
COLUMNS = [
    ("transaction_date", "Tanggal"),
    ("amount", "Jumlah"),
    ("description", "Keterangan"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Transaksi Bank/Kas
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("transaction_date", "Tanggal", FieldType.DATE, required=True),
    FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
    FieldSpec("description", "Keterangan", FieldType.TEXTAREA, required=True),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="bank_transactions",
    label="Transaksi Bank/Kas",
    category="Kas & Bank",
    icon="💵",
    base_path="/bank-cash/bank-cash",
    list_path="/transactions",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class BankTransactionsPage(GenericListPage):
    """Halaman Transaksi Bank/Kas."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
