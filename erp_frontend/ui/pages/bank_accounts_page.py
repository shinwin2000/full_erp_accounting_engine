"""
ui/pages/bank_accounts_page.py
=================================
Halaman modul "Rekening Bank & Kas" (Kas & Bank).

Endpoint backend : /bank-cash/bank-cash/bank-accounts
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
# Kolom tabel daftar Rekening Bank & Kas
# ---------------------------------------------------------------------------
COLUMNS = [
    ("account_number", "No. Rekening"),
    ("account_name", "Nama Rekening"),
    ("bank_name", "Bank"),
    ("currency_code", "Mata Uang"),
    ("opening_balance", "Saldo Awal"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Rekening Bank & Kas
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("account_number", "No. Rekening", required=True),
    FieldSpec("account_name", "Nama Rekening", required=True),
    FieldSpec("bank_name", "Nama Bank", required=True),
    FieldSpec("bank_code", "Kode Bank"),
    FieldSpec("currency_code", "Mata Uang", required=True, default="IDR"),
    FieldSpec("account_type", "Tipe Akun", FieldType.SELECT, choices=("checking", "savings", "cash", "petty_cash",)),
    FieldSpec("opening_balance", "Saldo Awal", FieldType.DECIMAL, default=0),
    FieldSpec("opening_balance_date", "Tanggal Saldo Awal", FieldType.DATE),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("activate", "Activate", path_suffix="/activate", style="success"),
    ActionSpec("lock", "Lock", path_suffix="/lock"),
    ActionSpec("unlock", "Unlock", path_suffix="/unlock"),
]

CONFIG = ModuleConfig(
    key="bank_accounts",
    label="Rekening Bank & Kas",
    category="Kas & Bank",
    icon="🏦",
    base_path="/bank-cash/bank-cash",
    list_path="/bank-accounts",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class BankAccountsPage(GenericListPage):
    """Halaman Rekening Bank & Kas."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
