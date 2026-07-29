"""
ui/pages/legal_entities_page.py
==================================
Halaman modul "Entitas Legal" (Master Data).

Endpoint backend : /legal-entities/legal-entities/

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
# Kolom tabel daftar Entitas Legal
# ---------------------------------------------------------------------------
COLUMNS = [
    ("legal_name", "Nama Legal"),
    ("trade_name", "Nama Dagang"),
    ("entity_type", "Tipe"),
    ("npwp", "NPWP"),
    ("city", "Kota"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Entitas Legal
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("legal_name", "Nama Legal (min. 3 karakter)", required=True),
    FieldSpec("trade_name", "Nama Dagang"),
    FieldSpec("entity_type", "Tipe Entitas", FieldType.SELECT, required=True, choices=("corporation", "branch", "representative_office", "partnership", "sole_proprietorship", "cooperative", "foundation", "consolidation_group",), help_text="corporation=PT, partnership=CV/Firma, sole_proprietorship=UD, cooperative=Koperasi, foundation=Yayasan"),
    FieldSpec("registration_number", "No. Registrasi (NIB)"),
    FieldSpec("npwp", "NPWP (harus 15 digit angka)", help_text="15 digit angka tanpa titik/strip"),
    FieldSpec("nppp", "NPPP (untuk PKP)"),
    FieldSpec("address", "Alamat", FieldType.TEXTAREA),
    FieldSpec("city", "Kota"),
    FieldSpec("postal_code", "Kode Pos"),
    FieldSpec("province", "Provinsi"),
    FieldSpec("country", "Negara (kode ISO 2 huruf)", default="ID"),
    FieldSpec("phone", "Telepon"),
    FieldSpec("email", "Email"),
    FieldSpec("website", "Website"),
    FieldSpec("fiscal_year_start", "Bulan Awal Tahun Fiskal (1-12)", FieldType.NUMBER, default=1),
    FieldSpec("fiscal_year_end", "Bulan Akhir Tahun Fiskal (1-12)", FieldType.NUMBER, default=12),
    FieldSpec("base_currency", "Mata Uang Dasar (3 huruf)", default="IDR"),
    FieldSpec("functional_currency", "Mata Uang Fungsional (3 huruf)", default="IDR"),
    FieldSpec("is_taxable", "PKP (Pengusaha Kena Pajak)", FieldType.BOOL, default=True),
    FieldSpec("is_withholding_agent", "Pemotong Pajak", FieldType.BOOL, default=True),
    FieldSpec("parent_company_id", "Perusahaan Induk (UUID, opsional)", FieldType.UUID),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="legal_entities",
    label="Entitas Legal",
    category="Master Data",
    icon="🏢",
    base_path="/legal-entities/legal-entities",
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


class LegalEntitiesPage(GenericListPage):
    """Halaman Entitas Legal."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
