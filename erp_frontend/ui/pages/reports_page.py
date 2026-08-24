"""
ui/pages/reports_page.py
===========================
Halaman modul "Report Terjadwal" (Umum).

Endpoint backend : /reports/schedule

REGENERASI OTOMATIS dari registry/module_registry.py (sumber kebenaran
tunggal) supaya field/kolom/aksi SELALU sinkron dengan hasil audit
terhadap schema backend asli — sebelumnya file mandiri ini py bisa jadi
kadaluarsa dibanding registry.py setelah audit, karena keduanya sempat
didefinisikan terpisah. Kalau perlu ubah field modul ini, ubah di
registry.py lalu jalankan ulang skrip regenerasi, JANGAN edit file ini
langsung supaya tidak2 desinkron lagi.

CATATAN (fix 2026-08-20, dikoreksi 2026-08-21): base_path/list_path
sebelumnya salah dua kali berturut-turut - pertama menunjuk ke
"/reports/reports" + "/" (endpoint LAPORAN AD-HOC yang sudah di-generate,
list_reports di fastapi_report_router.py, BUKAN endpoint jadwal), lalu
percobaan perbaikan pertama (2026-08-20) salah asumsi base_path cukup
"/reports" tanpa duplikasi.

FAKTA SEBENARNYA: fastapi_report_router.py dideklarasikan dengan
`APIRouter(prefix="/reports", ...)` DAN di-mount lagi secara eksternal di
app/main.py dengan prefix "/api/v1/reports" - pola yang SAMA di SEMUA
router modul ini (bandingkan fastapi_umkm_router.py: `prefix="/umkm"` +
mount "/api/v1/umkm", makanya UMKM juga pakai base_path="/umkm/umkm").
Jadi path asli endpoint /schedule adalah /api/v1/reports/reports/schedule
(dobel "reports"), BUKAN /api/v1/reports/schedule. base_path yang benar
tetap "/reports/reports" - yang salah HANYA list_path-nya (harus
"/schedule", bukan "/" yang menunjuk ke laporan ad-hoc) dan id_field
(harus "schedule_id" sesuai ReportScheduleResponseSchema, bukan default
"id").
"""
from __future__ import annotations

from registry.module_registry import FieldSpec, FieldType, ModuleConfig
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar Report Terjadwal
# ---------------------------------------------------------------------------
COLUMNS = [
    ("schedule_name", "Nama Jadwal"),
    ("report_type", "Tipe Laporan"),
    ("schedule_frequency", "Frekuensi"),
    ("next_run_at", "Jalan Berikutnya"),
    ("is_active", "Aktif"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Report Terjadwal
#
# Pilihan report_type sengaja dibatasi ke 12 jenis yang sudah punya
# implementasi generate_* nyata di ReportService - menjadwalkan jenis lain
# akan tersimpan tapi tidak akan pernah berhasil digenerate saat jadwalnya
# jalan.
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("schedule_name", "Nama Jadwal", required=True, help_text="Minimal 3 karakter"),
    FieldSpec("report_type", "Tipe Laporan", FieldType.SELECT, required=True, choices=(
        "balance_sheet", "income_statement", "cash_flow", "equity_statement",
        "trial_balance", "general_ledger", "ar_aging", "ap_aging",
        "stock_card", "tax_summary", "financial_ratios", "budget_vs_actual",
    )),
    FieldSpec("schedule_frequency", "Frekuensi", FieldType.SELECT, required=True, choices=(
        "daily", "weekly", "monthly", "quarterly", "semi_annually", "yearly", "custom",
    )),
    FieldSpec("schedule_time", "Jam Jalan (HH:MM)", help_text="Opsional, mis. 08:00"),
    FieldSpec("report_format", "Format", FieldType.SELECT,
              choices=("pdf", "xlsx", "csv", "html", "json", "xml"), required=True),
    FieldSpec("is_active", "Aktif", FieldType.BOOL, default=True),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
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
    list_path="/schedule",
    id_field="schedule_id",
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
