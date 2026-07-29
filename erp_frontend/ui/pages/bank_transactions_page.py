"""
ui/pages/bank_transactions_page.py
=====================================
Halaman modul "Transaksi Bank/Kas" (Kas & Bank).

Endpoint backend : /bank-cash/bank-cash/transactions

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
    edit_http_method="PUT",
)


class BankTransactionsPage(GenericListPage):
    """Halaman Transaksi Bank/Kas."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
