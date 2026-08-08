"""
ui/pages/employees_page.py
=============================
Halaman modul "Karyawan" (Master Data).

Endpoint backend : /employees/employees

REGENERASI OTOMATIS dari registry/module_registry.py (sumber kebenaran
tunggal) - JANGAN edit file ini langsung, ubah registry.py lalu
regenerasi ulang.

(regenerasi 2026-08-07 #2: field dikelompokkan per section untuk form
grid 2-kolom yang lebih besar dan tidak banyak scroll; ditambah aksi
Aktifkan/Nonaktifkan dan tombol Import CSV, menyusul endpoint backend
baru di fastapi_employee_router.py.)
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
    ("department", "Departemen"),
    ("position", "Jabatan"),
    ("status", "Status"),
    ("email", "Email"),
    ("phone", "Telepon"),
    ("is_active", "Aktif"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Karyawan (dikelompokkan per section)
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    # --- Identitas ---
    FieldSpec("employee_code", "Kode Karyawan", required=True, section="Identitas"),
    FieldSpec("full_name", "Nama Lengkap", required=True, section="Identitas"),
    FieldSpec("nik", "NIK (KTP)", section="Identitas"),
    FieldSpec("npwp", "NPWP", section="Identitas"),
    FieldSpec("gender", "Jenis Kelamin", FieldType.SELECT, choices=("M", "F", "O",), section="Identitas"),
    FieldSpec("birth_place", "Tempat Lahir", section="Identitas"),
    FieldSpec("birth_date", "Tanggal Lahir", FieldType.DATE, section="Identitas"),
    FieldSpec("marital_status", "Status Pernikahan", FieldType.SELECT, choices=("single", "married", "divorced", "widowed",), default="single", section="Identitas"),
    FieldSpec("dependents", "Jumlah Tanggungan (PTKP)", FieldType.NUMBER, default=0, help_text="Dipakai untuk menghitung status PTKP (mis. TK/0, K/1) secara otomatis", section="Identitas"),
    FieldSpec("religion", "Agama", section="Identitas"),
    # --- Kontak & Alamat ---
    FieldSpec("email", "Email", section="Kontak & Alamat"),
    FieldSpec("phone", "Telepon", section="Kontak & Alamat"),
    FieldSpec("mobile", "HP", section="Kontak & Alamat"),
    FieldSpec("city", "Kota", section="Kontak & Alamat"),
    FieldSpec("postal_code", "Kode Pos", section="Kontak & Alamat"),
    FieldSpec("address", "Alamat", FieldType.TEXTAREA, section="Kontak & Alamat"),
    # --- Kepegawaian ---
    FieldSpec("department", "Departemen", section="Kepegawaian"),
    FieldSpec("division", "Divisi", section="Kepegawaian"),
    FieldSpec("position", "Jabatan", section="Kepegawaian"),
    FieldSpec("job_level", "Level/Grade", section="Kepegawaian"),
    FieldSpec("cost_center", "Cost Center", section="Kepegawaian"),
    FieldSpec("manager_id", "ID Manager/Atasan", FieldType.UUID, section="Kepegawaian"),
    FieldSpec("join_date", "Tanggal Bergabung", FieldType.DATE, section="Kepegawaian"),
    # --- Payroll & BPJS ---
    FieldSpec("basic_salary", "Gaji Pokok", FieldType.DECIMAL, default=0, section="Payroll & BPJS"),
    FieldSpec("allowances", "Total Tunjangan", FieldType.DECIMAL, default=0, help_text="Gabungan tunjangan jabatan/transport/makan dsb (satu angka total)", section="Payroll & BPJS"),
    FieldSpec("overtime_rate_multiplier", "Pengali Tarif Lembur", FieldType.DECIMAL, default=1.5, section="Payroll & BPJS"),
    FieldSpec("bpjs_kesehatan_number", "No. BPJS Kesehatan", section="Payroll & BPJS"),
    FieldSpec("bpjs_ketenagakerjaan_number", "No. BPJS Ketenagakerjaan", section="Payroll & BPJS"),
    FieldSpec("bank_name", "Nama Bank", section="Payroll & BPJS"),
    FieldSpec("bank_account_number", "No. Rekening", section="Payroll & BPJS"),
    FieldSpec("bank_account_name", "Nama Pemilik Rekening", section="Payroll & BPJS"),
    # --- Lainnya ---
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA, section="Lainnya"),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di menu "Aksi", POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("deactivate", "Nonaktifkan", path_suffix="/deactivate", style="danger"),
    ActionSpec("activate", "Aktifkan", path_suffix="/activate", style="success"),
]

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
    can_import=True,
    search_param="search",
    edit_http_method="PATCH",
)


class EmployeesPage(GenericListPage):
    """Halaman Karyawan."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
