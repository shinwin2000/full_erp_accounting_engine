"""
ui/pages/time_entries_page.py
================================
Halaman modul "Timesheet" (Pembelian & Penjualan).

Endpoint backend : /projects/projects/time-entries

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
    edit_http_method="PUT",
)


class TimeEntriesPage(GenericListPage):
    """Halaman Timesheet."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
