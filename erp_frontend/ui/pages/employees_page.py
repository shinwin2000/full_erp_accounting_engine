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

(regenerasi 2026-08-07: field diselaraskan ulang dengan
adapters/primary_api/v1/fastapi_employee_router.py setelah EmployeeService
disambungkan ke database sungguhan - lihat catatan di module_registry.py
untuk daftar field lengkap dan alasan position_allowance/transport_allowance/
meal_allowance/overtime_rate digabung jadi allowances+overtime_rate_multiplier.)
"""
from __future__ import annotations

from registry.module_registry import FieldSpec, FieldType, ModuleConfig
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
# Field form tambah/ubah Karyawan
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    # --- Identitas ---
    FieldSpec("employee_code", "Kode Karyawan", required=True),
    FieldSpec("full_name", "Nama Lengkap", required=True),
    FieldSpec("nik", "NIK (KTP)"),
    FieldSpec("npwp", "NPWP"),
    FieldSpec("gender", "Jenis Kelamin", FieldType.SELECT, choices=("M", "F", "O",)),
    FieldSpec("birth_place", "Tempat Lahir"),
    FieldSpec("birth_date", "Tanggal Lahir", FieldType.DATE),
    FieldSpec("marital_status", "Status Pernikahan", FieldType.SELECT, choices=("single", "married", "divorced", "widowed",), default="single"),
    FieldSpec("dependents", "Jumlah Tanggungan (PTKP)", FieldType.NUMBER, default=0, help_text="Dipakai untuk menghitung status PTKP (mis. TK/0, K/1) secara otomatis"),
    FieldSpec("religion", "Agama"),
    # --- Kontak & Alamat ---
    FieldSpec("email", "Email"),
    FieldSpec("phone", "Telepon"),
    FieldSpec("mobile", "HP"),
    FieldSpec("address", "Alamat", FieldType.TEXTAREA),
    FieldSpec("city", "Kota"),
    FieldSpec("postal_code", "Kode Pos"),
    # --- Kepegawaian ---
    FieldSpec("department", "Departemen"),
    FieldSpec("division", "Divisi"),
    FieldSpec("position", "Jabatan"),
    FieldSpec("job_level", "Level/Grade"),
    FieldSpec("cost_center", "Cost Center"),
    FieldSpec("manager_id", "ID Manager/Atasan", FieldType.UUID),
    FieldSpec("join_date", "Tanggal Bergabung", FieldType.DATE),
    # --- Payroll ---
    FieldSpec("basic_salary", "Gaji Pokok", FieldType.DECIMAL, default=0),
    FieldSpec("allowances", "Total Tunjangan", FieldType.DECIMAL, default=0, help_text="Gabungan tunjangan jabatan/transport/makan dsb (satu angka total)"),
    FieldSpec("overtime_rate_multiplier", "Pengali Tarif Lembur", FieldType.DECIMAL, default=1.5),
    FieldSpec("bpjs_kesehatan_number", "No. BPJS Kesehatan"),
    FieldSpec("bpjs_ketenagakerjaan_number", "No. BPJS Ketenagakerjaan"),
    FieldSpec("bank_name", "Nama Bank"),
    FieldSpec("bank_account_number", "No. Rekening"),
    FieldSpec("bank_account_name", "Nama Pemilik Rekening"),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
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
