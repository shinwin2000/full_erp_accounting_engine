"""
ui/pages/payroll_runs_page.py
================================
Halaman modul "Payroll Run" (SDM & Payroll).

Endpoint backend : /payroll/runs
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
)


class PayrollRunsPage(GenericListPage):
    """Halaman Payroll Run."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
