"""
ui/pages/employees_page.py
=============================
Halaman modul "Karyawan" (Master Data).

Endpoint backend : /employees/employees
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
# Kolom tabel daftar Karyawan
# ---------------------------------------------------------------------------
COLUMNS = [
    ("employee_code", "Kode"),
    ("full_name", "Nama"),
    ("nik", "NIK"),
    ("basic_salary", "Gaji Pokok"),
    ("is_active", "Aktif"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Karyawan
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("employee_code", "Kode Karyawan", required=True),
    FieldSpec("full_name", "Nama Lengkap", required=True),
    FieldSpec("npwp", "NPWP"),
    FieldSpec("nik", "NIK", required=True),
    FieldSpec("dependents", "Jumlah Tanggungan", FieldType.NUMBER, default=0),
    FieldSpec("basic_salary", "Gaji Pokok", FieldType.DECIMAL, required=True),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="employees",
    label="Karyawan",
    category="Master Data",
    icon="👷",
    base_path="/employees",
    list_path="/employees",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
    edit_http_method="PATCH",
)


class EmployeesPage(GenericListPage):
    """Halaman Karyawan."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
