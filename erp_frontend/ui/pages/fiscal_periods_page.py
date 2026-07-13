"""
ui/pages/fiscal_periods_page.py
==================================
Halaman modul "Periode Fiskal" (Akuntansi Inti).

Endpoint backend : /fiscal-periods/periods
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
# Kolom tabel daftar Periode Fiskal
# ---------------------------------------------------------------------------
COLUMNS = [
    ("year", "Tahun"),
    ("month", "Bulan"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Periode Fiskal
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("year", "Tahun", FieldType.NUMBER, required=True),
    FieldSpec("month", "Bulan", FieldType.NUMBER, required=True),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("close", "Close Period", path_suffix="/close", style="danger"),
    ActionSpec("lock", "Lock Period", path_suffix="/lock"),
    ActionSpec("reopen", "Reopen Period", path_suffix="/reopen", style="primary"),
]

CONFIG = ModuleConfig(
    key="fiscal_periods",
    label="Periode Fiskal",
    category="Akuntansi Inti",
    icon="🗓️",
    base_path="/fiscal-periods",
    list_path="/periods",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=False,
    search_param="search",
)


class FiscalPeriodsPage(GenericListPage):
    """Halaman Periode Fiskal."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
