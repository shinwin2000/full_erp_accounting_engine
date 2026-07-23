"""
ui/pages/iam_users_page.py
=============================
Halaman modul "Pengguna & Role" (Master Data).

Endpoint backend : /iam/iam/users

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
# Kolom tabel daftar Pengguna & Role
# ---------------------------------------------------------------------------
COLUMNS = [
    ("username", "Username"),
    ("email", "Email"),
    ("full_name", "Nama"),
    ("department", "Departemen"),
    ("is_active", "Aktif"),
    ("is_locked", "Terkunci"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Pengguna & Role
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("username", "Username", required=True),
    FieldSpec("email", "Email", required=True),
    FieldSpec("full_name", "Nama Lengkap", required=True),
    FieldSpec("password", "Password", required=True),
    FieldSpec("department", "Departemen"),
    FieldSpec("job_title", "Jabatan"),
    FieldSpec("phone_number", "No. Telepon"),
    FieldSpec("must_change_password", "Wajib Ganti Password", FieldType.BOOL, default=True),
    FieldSpec("is_superuser", "Superuser", FieldType.BOOL, default=False),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("lock", "Lock User", path_suffix="/lock", style="danger"),
    ActionSpec("unlock", "Unlock User", path_suffix="/unlock", style="success"),
    ActionSpec("reset-password", "Reset Password", path_suffix="/reset-password"),
]

CONFIG = ModuleConfig(
    key="iam_users",
    label="Pengguna & Role",
    category="Master Data",
    icon="🔐",
    base_path="/iam/iam",
    list_path="/users",
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


class IamUsersPage(GenericListPage):
    """Halaman Pengguna & Role."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
