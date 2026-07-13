"""
ui/pages/reports_page.py
===========================
Halaman modul "Report Terjadwal" (Umum).

Endpoint backend : /reports/reports/
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
# Kolom tabel daftar Report Terjadwal
# ---------------------------------------------------------------------------
COLUMNS = [
    ("report_type", "Tipe Laporan"),
    ("schedule_name", "Nama Jadwal"),
    ("schedule_frequency", "Frekuensi"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Report Terjadwal
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("report_type", "Tipe Laporan", required=True),
    FieldSpec("schedule_name", "Nama Jadwal", required=True),
    FieldSpec("schedule_frequency", "Frekuensi", FieldType.SELECT, choices=("daily", "weekly", "monthly", "quarterly",)),
    FieldSpec("schedule_time", "Jam Jalan"),
    FieldSpec("report_format", "Format", FieldType.SELECT, choices=("pdf", "xlsx", "csv",)),
    FieldSpec("is_active", "Aktif", FieldType.BOOL, default=True),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="reports",
    label="Report Terjadwal",
    category="Umum",
    icon="🗂️",
    base_path="/reports/reports",
    list_path="/",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class ReportsPage(GenericListPage):
    """Halaman Report Terjadwal."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
