"""
ui/pages/projects_page.py
============================
Halaman modul "Proyek & Jasa" (Pembelian & Penjualan).

Endpoint backend : /projects/projects/

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
# Kolom tabel daftar Proyek & Jasa
# ---------------------------------------------------------------------------
COLUMNS = [
    ("project_code", "Kode"),
    ("project_name", "Nama Proyek"),
    ("contract_value", "Nilai Kontrak"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Proyek & Jasa
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("project_code", "Kode Proyek", required=True),
    FieldSpec("project_name", "Nama Proyek", required=True),
    FieldSpec("customer_id", "Customer (UUID)", FieldType.UUID),
    FieldSpec("start_date", "Tanggal Mulai", FieldType.DATE, required=True),
    FieldSpec("end_date", "Tanggal Selesai", FieldType.DATE),
    FieldSpec("contract_type", "Tipe Kontrak", FieldType.SELECT, choices=("fixed_price", "time_material", "retainer", "cost_plus", "milestone",)),
    FieldSpec("contract_value", "Nilai Kontrak", FieldType.DECIMAL),
    FieldSpec("budget_total", "Total Budget", FieldType.DECIMAL),
    FieldSpec("revenue_recognition_method", "Metode Pengakuan Pendapatan", FieldType.SELECT, choices=("percentage_completion", "completed_contract", "straight_line", "milestone", "input_method", "output_method",)),
    FieldSpec("billing_cycle_days", "Siklus Billing (hari)", FieldType.NUMBER),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="projects",
    label="Proyek & Jasa",
    category="Pembelian & Penjualan",
    icon="📁",
    base_path="/projects/projects",
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


class ProjectsPage(GenericListPage):
    """Halaman Proyek & Jasa."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
