"""
ui/pages/umkm_page.py
========================
Halaman modul "UMKM Simplified" (Umum).

Endpoint backend : /umkm/umkm/journals

REGENERASI OTOMATIS dari registry/module_registry.py (sumber kebenaran
tunggal) supaya field/kolom/aksi SELALU sinkron dengan hasil audit
terhadap schema backend asli — sebelumnya file mandiri ini py bisa jadi
kadaluarsa dibanding registry.py setelah audit, karena keduanya sempat
didefinisikan terpisah. Kalau perlu ubah field modul ini, ubah di
registry.py lalu jalankan ulang skrip regenerasi, JANGAN edit file ini
langsung supaya tidak2 desinkron lagi.

CATATAN (fix 2026-08-18): field sebelumnya (transaction_date,
transaction_type, tanpa akun debit/kredit) adalah sisa desain versi awal
modul UMKM (pencatatan income/expense sederhana per kategori). Backend
sudah diaudit ulang total - endpoint /umkm/umkm/journals sekarang adalah
jurnal double-entry penuh (SimplifiedJournalEntrySchema di
fastapi_umkm_router.py), field lama menyebabkan setiap POST/PUT gagal
422 "field required" untuk debit_account_code/credit_account_code.
"""
from __future__ import annotations

from registry.module_registry import (
    UMKM_ACCOUNT_CHOICES,
    UMKM_CATEGORY_CHOICES,
    ActionSpec,
    FieldSpec,
    FieldType,
    ModuleConfig,
)
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar UMKM Simplified
# ---------------------------------------------------------------------------
COLUMNS = [
    ("journal_number", "No. Jurnal"),
    ("journal_date", "Tanggal"),
    ("description", "Keterangan"),
    ("debit_account_code", "Akun Debit"),
    ("credit_account_code", "Akun Kredit"),
    ("amount", "Jumlah"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah UMKM Simplified
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("journal_date", "Tanggal", FieldType.DATE, required=True),
    FieldSpec("description", "Keterangan", required=True, help_text="Minimal 3 karakter"),
    FieldSpec(
        "debit_account_code", "Akun Debit", FieldType.SELECT,
        choices=UMKM_ACCOUNT_CHOICES, required=True,
        help_text="Akun yang bertambah nilainya (sisi debit)",
    ),
    FieldSpec(
        "credit_account_code", "Akun Kredit", FieldType.SELECT,
        choices=UMKM_ACCOUNT_CHOICES, required=True,
        help_text="Akun yang berkurang nilainya (sisi kredit) - harus beda dari akun debit",
    ),
    FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
    FieldSpec(
        "category", "Kategori Laporan", FieldType.SELECT,
        choices=UMKM_CATEGORY_CHOICES,
        help_text="Opsional - dipakai untuk Laba Rugi/Neraca/Arus Kas",
    ),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("post", "Post ke Buku Besar", path_suffix="/post", style="primary"),
    ActionSpec(
        "reverse", "Reverse (Balik Jurnal)", path_suffix="/reverse", style="danger",
        needs_reason=True, reason_min_length=5,
    ),
]

CONFIG = ModuleConfig(
    key="umkm",
    label="UMKM Simplified",
    category="Umum",
    icon="🏪",
    base_path="/umkm/umkm",
    list_path="/journals",
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


class UmkmPage(GenericListPage):
    """Halaman UMKM Simplified."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
