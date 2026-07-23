"""
ui/pages/payroll_runs_page.py
================================
Halaman modul "Payroll Run" (SDM & Payroll).

Endpoint backend : /payroll/runs

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
# Kolom tabel daftar Payroll Run
# ---------------------------------------------------------------------------
COLUMNS = [
    ("period", "Periode"),
    ("status", "Status"),
    ("total_amount", "Total"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Payroll Run
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("period_year", "Tahun", FieldType.NUMBER, required=True),
    FieldSpec("period_month", "Bulan", FieldType.NUMBER, required=True),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("submit", "Submit", path_suffix="/submit", style="primary"),
    ActionSpec("approve", "Approve", path_suffix="/approve", style="success"),
    ActionSpec("reject", "Reject", path_suffix="/reject", style="danger"),
    ActionSpec("finalize", "Finalize", path_suffix="/finalize", style="success"),
]

CONFIG = ModuleConfig(
    key="payroll_runs",
    label="Payroll Run",
    category="SDM & Payroll",
    icon="🧮",
    base_path="/payroll",
    list_path="/runs",
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


class PayrollRunsPage(GenericListPage):
    """Halaman Payroll Run."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
