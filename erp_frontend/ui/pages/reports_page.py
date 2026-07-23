"""
ui/pages/reports_page.py
===========================
Halaman modul "Report Terjadwal" (Umum).

Endpoint backend : /reports/reports/

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
    edit_http_method="PUT",
)


class ReportsPage(GenericListPage):
    """Halaman Report Terjadwal."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
