"""
ui/pages/employees_page.py
=============================
Halaman modul "Karyawan" (Master Data).

Endpoint backend : /employees/employees

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
    FieldSpec("nik", "NIK (KTP)"),
    FieldSpec("birth_date", "Tanggal Lahir", FieldType.DATE),
    FieldSpec("join_date", "Tanggal Bergabung", FieldType.DATE),
    FieldSpec("marital_status", "Status Pernikahan", FieldType.SELECT, choices=("single", "married", "divorced", "widowed",), default="single"),
    FieldSpec("dependents", "Jumlah Tanggungan (PTKP)", FieldType.NUMBER, default=0),
    FieldSpec("basic_salary", "Gaji Pokok", FieldType.DECIMAL, default=0),
    FieldSpec("position_allowance", "Tunjangan Jabatan", FieldType.DECIMAL, default=0),
    FieldSpec("transport_allowance", "Tunjangan Transport", FieldType.DECIMAL, default=0),
    FieldSpec("meal_allowance", "Tunjangan Makan", FieldType.DECIMAL, default=0),
    FieldSpec("overtime_rate", "Tarif Lembur/Jam", FieldType.DECIMAL, default=0),
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
