"""
ui/pages/intercompany_page.py
================================
Halaman modul "Transaksi Intercompany" (Treasury).

Endpoint backend : /consolidation/consolidation/intercompany

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
# Kolom tabel daftar Transaksi Intercompany
# ---------------------------------------------------------------------------
COLUMNS = [
    ("transaction_date", "Tanggal"),
    ("amount", "Jumlah"),
    ("transaction_type", "Tipe"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Transaksi Intercompany
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("from_legal_entity_id", "Dari Entitas (UUID)", FieldType.UUID, required=True),
    FieldSpec("to_legal_entity_id", "Ke Entitas (UUID)", FieldType.UUID, required=True),
    FieldSpec("transaction_date", "Tanggal", FieldType.DATE, required=True),
    FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
    FieldSpec("currency", "Mata Uang", default="IDR"),
    FieldSpec("exchange_rate", "Kurs", FieldType.DECIMAL, default=1),
    FieldSpec("transaction_type", "Tipe Transaksi", FieldType.SELECT, required=True, choices=("sales", "service", "loan", "interest", "dividend", "fund_transfer",)),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="intercompany",
    label="Transaksi Intercompany",
    category="Treasury",
    icon="🔀",
    base_path="/consolidation/consolidation",
    list_path="/intercompany",
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


class IntercompanyPage(GenericListPage):
    """Halaman Transaksi Intercompany."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
