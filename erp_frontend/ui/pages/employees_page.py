"""
ui/pages/employees_page.py
=============================
Halaman modul "Karyawan" (Master Data).

Endpoint backend : /employees/employees

Fitur (2026-10-13):
- Kode karyawan otomatis (EMP-001, EMP-002, dst) saat klik "+ Baru".
- Form Tambah/Ubah pakai ModernFormDialog (kartu per section, header ungu).
- Tombol 💰 Struktur Gaji — ubah gaji pokok / tunjangan / pengali lembur.
- Tombol 📋 Detail — dialog 3 tab (tanggungan, foto, dokumen).
- Tombol Aksi dropdown — Aktifkan/Nonaktifkan.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QPushButton
from core.api_client import api_client
from core.workers import run_task
from registry.module_registry import (
    ActionSpec,
    FieldSpec,
    FieldType,
    ModuleConfig,
)
from ui.pages.employee_detail_dialog import EmployeeDetailDialog
from ui.widgets.generic_list_page import GenericListPage
from ui.widgets.modern_form_dialog import ModernFormDialog

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
    FieldSpec(
        "employee_code",
        "Kode Karyawan",
        help_text="Kosongkan untuk auto-generate (EMP-001, EMP-002, dst)",
        section="Identitas",
    ),
    FieldSpec("full_name", "Nama Lengkap", required=True, section="Identitas"),
    FieldSpec("nik", "NIK (KTP)", section="Identitas"),
    FieldSpec("npwp", "NPWP", section="Identitas"),
    FieldSpec(
        "gender",
        "Jenis Kelamin",
        FieldType.SELECT,
        choices=("M", "F", "O"),
        section="Identitas",
    ),
    FieldSpec("birth_place", "Tempat Lahir", section="Identitas"),
    FieldSpec(
        "birth_date", "Tanggal Lahir", FieldType.DATE, section="Identitas"
    ),
    FieldSpec(
        "marital_status",
        "Status Pernikahan",
        FieldType.SELECT,
        choices=("single", "married", "divorced", "widowed"),
        default="single",
        section="Identitas",
    ),
    FieldSpec(
        "dependents",
        "Jumlah Tanggungan (PTKP)",
        FieldType.NUMBER,
        default=0,
        help_text=(
            "Dipakai untuk menghitung status PTKP "
            "(mis. TK/0, K/1) secara otomatis"
        ),
        section="Identitas",
    ),
    FieldSpec("religion", "Agama", section="Identitas"),
    # --- Kontak & Alamat ---
    FieldSpec("email", "Email", section="Kontak & Alamat"),
    FieldSpec("phone", "Telepon", section="Kontak & Alamat"),
    FieldSpec("mobile", "HP", section="Kontak & Alamat"),
    FieldSpec("city", "Kota", section="Kontak & Alamat"),
    FieldSpec("postal_code", "Kode Pos", section="Kontak & Alamat"),
    FieldSpec(
        "address", "Alamat", FieldType.TEXTAREA, section="Kontak & Alamat"
    ),
    # --- Kepegawaian ---
    FieldSpec("department", "Departemen", section="Kepegawaian"),
    FieldSpec("division", "Divisi", section="Kepegawaian"),
    FieldSpec("position", "Jabatan", section="Kepegawaian"),
    FieldSpec("job_level", "Level/Grade", section="Kepegawaian"),
    FieldSpec("cost_center", "Cost Center", section="Kepegawaian"),
    FieldSpec(
        "manager_id",
        "ID Manager/Atasan",
        FieldType.UUID,
        section="Kepegawaian",
    ),
    FieldSpec(
        "join_date",
        "Tanggal Bergabung",
        FieldType.DATE,
        section="Kepegawaian",
    ),
    # --- Payroll & BPJS ---
    FieldSpec(
        "basic_salary",
        "Gaji Pokok",
        FieldType.DECIMAL,
        default=0,
        section="Payroll & BPJS",
    ),
    FieldSpec(
        "allowances",
        "Total Tunjangan",
        FieldType.DECIMAL,
        default=0,
        help_text=(
            "Gabungan tunjangan jabatan/transport/makan dsb "
            "(satu angka total)"
        ),
        section="Payroll & BPJS",
    ),
    FieldSpec(
        "overtime_rate_multiplier",
        "Pengali Tarif Lembur",
        FieldType.DECIMAL,
        default=1.5,
        section="Payroll & BPJS",
    ),
    FieldSpec(
        "bpjs_kesehatan_number",
        "No. BPJS Kesehatan",
        section="Payroll & BPJS",
    ),
    FieldSpec(
        "bpjs_ketenagakerjaan_number",
        "No. BPJS Ketenagakerjaan",
        section="Payroll & BPJS",
    ),
    FieldSpec("bank_name", "Nama Bank", section="Payroll & BPJS"),
    FieldSpec(
        "bank_account_number", "No. Rekening", section="Payroll & BPJS"
    ),
    FieldSpec(
        "bank_account_name",
        "Nama Pemilik Rekening",
        section="Payroll & BPJS",
    ),
    # --- Lainnya ---
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA, section="Lainnya"),
]

# ---------------------------------------------------------------------------
# Aksi workflow
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec(
        "deactivate",
        "Nonaktifkan",
        path_suffix="/deactivate",
        style="danger",
    ),
    ActionSpec(
        "activate", "Aktifkan", path_suffix="/activate", style="success"
    ),
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
    """Halaman Karyawan, + tombol Struktur Gaji & Detail."""

    button_permissions = (
        ("new_btn", "employee:create"),
        ("edit_btn", "employee:update"),
        ("action_btn", "employee:update"),
        ("delete_btn", "employee:delete"),
        ("import_btn", "employee:import"),
        ("salary_btn", "employee:update"),
    )

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
        self._add_salary_button()
        self._add_detail_button()
        self._apply_permission_gates()

    # ------------------------------------------------------------------
    # Form Tambah/Ubah memakai tampilan modern (kartu per section).
    # ------------------------------------------------------------------
    def _make_form_dialog(self, title, fields, initial=None):
        if initial:
            # Mode EDIT: kode readonly, kirim field kosong sebagai null.
            code = initial.get("employee_code") or ""
            name = initial.get("full_name") or ""
            subtitle = (
                " • ".join(x for x in (code, name) if x)
                or "Perbarui data karyawan."
            )
            title, icon = "Ubah Data Karyawan", "✏️"
            return ModernFormDialog(
                title,
                fields,
                initial=initial,
                parent=self,
                icon=icon,
                subtitle=subtitle,
                columns=2,
                readonly_fields=("employee_code",),
                send_empty_as_null=True,
            )
        else:
            # Mode CREATE: kode editable (auto-generate tapi bisa diubah manual).
            code_pre = (initial or {}).get("employee_code") if initial else None
            if code_pre:
                subtitle = (
                    f"Kode karyawan dibuat otomatis: {code_pre}. "
                    "Bisa diedit jika perlu."
                )
            else:
                subtitle = "Isi data karyawan baru."
            return ModernFormDialog(
                "Tambah Karyawan Baru",
                fields,
                initial=initial,
                parent=self,
                icon="👷",
                subtitle=subtitle,
                columns=2,
                send_empty_as_null=False,
            )

    # ------------------------------------------------------------------
    # TOMBOL STRUKTUR GAJI
    # ------------------------------------------------------------------
    def _add_salary_button(self) -> None:
        self.salary_btn = QPushButton("💰 Struktur Gaji")
        self.salary_btn.setToolTip(
            "Ubah gaji pokok, tunjangan, dan pengali lembur karyawan terpilih"
        )
        self.salary_btn.clicked.connect(self._change_salary_structure)
        toolbar_layout = self.layout().itemAt(1).layout()
        insert_at = (
            toolbar_layout.count() - 1
            if self.config.can_create
            else toolbar_layout.count()
        )
        toolbar_layout.insertWidget(insert_at, self.salary_btn)
        if hasattr(self, "_write_buttons"):
            self._write_buttons.append(self.salary_btn)

    def _change_salary_structure(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(
                self, "Info", "Pilih baris karyawan terlebih dahulu."
            )
            return
        employee_id = record.get(self.config.id_field)
        try:
            current_basic = float(record.get("basic_salary") or 0)
        except (TypeError, ValueError):
            current_basic = 0.0
        try:
            current_allow = float(record.get("allowances") or 0)
        except (TypeError, ValueError):
            current_allow = 0.0
        try:
            current_mult = float(
                record.get("overtime_rate_multiplier") or 1.5
            )
        except (TypeError, ValueError):
            current_mult = 1.5
        code = record.get("employee_code") or ""
        name = record.get("full_name") or ""

        fields = [
            FieldSpec(
                "basic_salary",
                "Gaji Pokok",
                FieldType.DECIMAL,
                required=True,
                min_value=0,
                section="Struktur Gaji",
            ),
            FieldSpec(
                "allowances",
                "Total Tunjangan",
                FieldType.DECIMAL,
                required=True,
                min_value=0,
                section="Struktur Gaji",
            ),
            FieldSpec(
                "overtime_rate_multiplier",
                "Pengali Tarif Lembur",
                FieldType.DECIMAL,
                required=True,
                min_value=1,
                section="Struktur Gaji",
            ),
        ]
        dlg = ModernFormDialog(
            "Ubah Struktur Gaji",
            fields,
            initial={
                "basic_salary": current_basic,
                "allowances": current_allow,
                "overtime_rate_multiplier": current_mult,
            },
            parent=self,
            icon="💰",
            columns=1,
            subtitle=(
                f"{code} • {name}  |  "
                f"Gaji pokok saat ini: Rp {current_basic:,.2f}"
            ),
        )
        if not dlg.exec():
            return
        payload = dlg.result_payload()
        self.status_label.setText("Menyimpan struktur gaji...")
        self._set_write_buttons_enabled(False)
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(
                "Struktur gaji diperbarui."
            ),
            on_error=self._on_write_error,
            path=(
                f"{self.config.base_path}"
                f"{self.config.list_path.rstrip('/')}/{employee_id}"
                f"/salary-structure"
            ),
            json_body=payload,
        )

    # ------------------------------------------------------------------
    # TOMBOL DETAIL
    # ------------------------------------------------------------------
    def _add_detail_button(self) -> None:
        self.detail_btn = QPushButton("📋 Detail")
        self.detail_btn.clicked.connect(self._open_detail)
        toolbar_layout = self.layout().itemAt(1).layout()
        insert_at = (
            toolbar_layout.count() - 1
            if self.config.can_create
            else toolbar_layout.count()
        )
        toolbar_layout.insertWidget(insert_at, self.detail_btn)

    def _open_detail(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(
                self, "Info", "Pilih baris karyawan terlebih dahulu."
            )
            return
        employee_id = record.get(self.config.id_field)
        label = (
            record.get("full_name")
            or record.get("employee_code")
            or str(employee_id)
        )
        dlg = EmployeeDetailDialog(str(employee_id), str(label), parent=self)
        dlg.exec()
        self.refresh()

    # ------------------------------------------------------------------
    # AUTO-GENERATE KODE saat tombol "+ Baru" diklik
    # ------------------------------------------------------------------
    def _create_new(self) -> None:
        if not self.config.form_fields:
            QMessageBox.information(
                self,
                "Info",
                "Form untuk modul ini belum dikonfigurasi.",
            )
            return
        self.status_label.setText("Menyiapkan kode karyawan...")
        run_task(
            api_client.get,
            on_success=self._open_create_dialog_with_next_code,
            on_error=self._on_next_code_error,
            path=f"{self.config.base_path}/next-code",
        )

    def _open_create_dialog_with_next_code(self, response) -> None:
        self.status_label.setText("")
        next_code = ""
        if isinstance(response, dict):
            next_code = response.get("employee_code", "") or ""
        initial = {"employee_code": next_code} if next_code else None
        self._show_create_dialog(initial)

    def _on_next_code_error(self, message: str) -> None:
        self.status_label.setText("")
        # Fallback: buka form kosong (user isi kode manual).
        self._show_create_dialog(None)

    def _show_create_dialog(self, initial: dict | None) -> None:
        dlg = self._make_form_dialog(
            f"Tambah {self.config.label}",
            self.config.form_fields,
            initial=initial,
        )
        if dlg.exec():
            payload = dlg.result_payload()
            create_path = self.config.base_path + self.config.list_path
            self.status_label.setText("Menyimpan...")
            self._set_write_buttons_enabled(False)
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write(
                    "Karyawan berhasil ditambahkan."
                ),
                on_error=self._on_write_error,
                path=create_path,
                json_body=payload,
            )
            