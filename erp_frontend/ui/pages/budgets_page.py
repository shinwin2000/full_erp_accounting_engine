"""
ui/pages/budgets_page.py
===========================
Halaman modul "Budget / Anggaran" (Perencanaan).

Endpoint backend : /budget/budget/

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
# Kolom tabel daftar Budget / Anggaran
# ---------------------------------------------------------------------------
COLUMNS = [
    ("budget_code", "Kode"),
    ("budget_name", "Nama"),
    ("fiscal_year", "Tahun"),
    ("budget_type", "Tipe"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Budget / Anggaran
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("budget_code", "Kode Budget", required=True),
    FieldSpec("budget_name", "Nama Budget", required=True),
    FieldSpec("budget_type", "Tipe Budget", FieldType.SELECT, choices=("operational", "capital", "cash", "project", "department", "fixed_asset", "sales",)),
    FieldSpec("fiscal_year", "Tahun Fiskal", FieldType.NUMBER, required=True),
    FieldSpec("period", "Periode", FieldType.SELECT, choices=("monthly", "quarterly", "yearly",)),
    FieldSpec("version", "Versi", default="1.0"),
    FieldSpec("effective_date", "Berlaku Sejak", FieldType.DATE, required=True),
    FieldSpec("expiry_date", "Berlaku Sampai", FieldType.DATE),
    FieldSpec("currency", "Mata Uang", default="IDR"),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("submit", "Submit", path_suffix="/submit", style="primary"),
    ActionSpec("approve", "Approve", path_suffix="/approve", style="success"),
    ActionSpec("reject", "Reject", path_suffix="/reject", style="danger"),
]

CONFIG = ModuleConfig(
    key="budgets",
    label="Budget / Anggaran",
    category="Perencanaan",
    icon="📅",
    base_path="/budget/budget",
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


class BudgetsPage(GenericListPage):
    """Halaman Budget / Anggaran."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
