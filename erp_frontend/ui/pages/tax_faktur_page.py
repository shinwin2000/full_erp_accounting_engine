"""
ui/pages/tax_faktur_page.py
==============================
Halaman modul "Faktur Pajak (Coretax)" (Pajak).

Endpoint backend : /tax/coretax/tax/faktur-pajak
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
# Kolom tabel daftar Faktur Pajak (Coretax)
# ---------------------------------------------------------------------------
COLUMNS = [
    ("reference_id", "No. Referensi"),
    ("faktur_date", "Tanggal"),
    ("nama_pembeli", "Pembeli"),
    ("dpp", "DPP"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Faktur Pajak (Coretax)
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("reference_id", "No. Referensi", required=True),
    FieldSpec("faktur_date", "Tanggal Faktur", FieldType.DATE, required=True),
    FieldSpec("npwp_pembeli", "NPWP Pembeli", required=True),
    FieldSpec("nama_pembeli", "Nama Pembeli", required=True),
    FieldSpec("alamat_pembeli", "Alamat Pembeli", FieldType.TEXTAREA),
    FieldSpec("dpp", "DPP", FieldType.DECIMAL, required=True),
    FieldSpec("ppn_rate", "Tarif PPN (%)", FieldType.DECIMAL, default=11),
    FieldSpec("is_ppn_bm", "PPnBM", FieldType.BOOL, default=False),
    FieldSpec("description", "Keterangan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="tax_faktur",
    label="Faktur Pajak (Coretax)",
    category="Pajak",
    icon="🧾",
    base_path="/tax/coretax/tax",
    list_path="/faktur-pajak",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class TaxFakturPage(GenericListPage):
    """Halaman Faktur Pajak (Coretax)."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
