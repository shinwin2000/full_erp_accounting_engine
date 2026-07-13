"""
ui/pages/projects_page.py
============================
Halaman modul "Proyek & Jasa" (Pembelian & Penjualan).

Endpoint backend : /projects/projects/
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
    FieldSpec("contract_type", "Tipe Kontrak"),
    FieldSpec("contract_value", "Nilai Kontrak", FieldType.DECIMAL),
    FieldSpec("budget_total", "Total Budget", FieldType.DECIMAL),
    FieldSpec("revenue_recognition_method", "Metode Pengakuan Pendapatan", FieldType.SELECT, choices=("percentage_of_completion", "completed_contract",)),
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
)


class ProjectsPage(GenericListPage):
    """Halaman Proyek & Jasa."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
