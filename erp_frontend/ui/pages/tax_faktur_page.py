"""
ui/pages/tax_faktur_page.py
==============================
Halaman modul "Faktur Pajak (Coretax)" (Pajak).

Endpoint backend : /tax/coretax/tax/faktur-pajak

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
    FieldSpec("reference_id", "ID Referensi Invoice (UUID)", FieldType.UUID, required=True),
    FieldSpec("faktur_date", "Tanggal Faktur", FieldType.DATE, required=True),
    FieldSpec("npwp_pembeli", "NPWP Pembeli (15 digit angka)", required=True),
    FieldSpec("nama_pembeli", "Nama Pembeli", required=True),
    FieldSpec("alamat_pembeli", "Alamat Pembeli", FieldType.TEXTAREA),
    FieldSpec("dpp", "DPP (harus > 0)", FieldType.DECIMAL, required=True),
    FieldSpec("ppn_rate", "Tarif PPN (%)", FieldType.DECIMAL, default=11),
    FieldSpec("is_ppn_bm", "Kena PPnBM", FieldType.BOOL, default=False),
    FieldSpec("ppn_bm_rate", "Tarif PPnBM (%, jika kena PPnBM)", FieldType.DECIMAL, default=0),
    FieldSpec("note_type", "Tipe Faktur", FieldType.SELECT, choices=("normal", "correction", "replacement",), default="normal"),
    FieldSpec("correction_sequence", "No. Urut Pembetulan (0 jika normal)", FieldType.NUMBER, default=0),
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
    edit_http_method="PUT",
)


class TaxFakturPage(GenericListPage):
    """Halaman Faktur Pajak (Coretax)."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
