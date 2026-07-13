"""
ui/pages/time_entries_page.py
================================
Halaman modul "Timesheet" (Pembelian & Penjualan).

Endpoint backend : /projects/projects/time-entries
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
# Kolom tabel daftar Timesheet
# ---------------------------------------------------------------------------
COLUMNS = [
    ("work_date", "Tanggal"),
    ("hours", "Jam"),
    ("is_billable", "Billable"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Timesheet
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("project_id", "Proyek (UUID)", FieldType.UUID, required=True),
    FieldSpec("work_date", "Tanggal Kerja", FieldType.DATE, required=True),
    FieldSpec("hours", "Jam Kerja", FieldType.DECIMAL, required=True),
    FieldSpec("hourly_rate", "Tarif per Jam", FieldType.DECIMAL),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
    FieldSpec("is_billable", "Billable", FieldType.BOOL, default=True),
    FieldSpec("task_code", "Kode Task"),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="time_entries",
    label="Timesheet",
    category="Pembelian & Penjualan",
    icon="⏱️",
    base_path="/projects/projects",
    list_path="/time-entries",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class TimeEntriesPage(GenericListPage):
    """Halaman Timesheet."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
