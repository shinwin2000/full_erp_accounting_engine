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
"""
from __future__ import annotations

from registry.module_registry import FieldSpec, FieldType, ModuleConfig
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar UMKM Simplified
# ---------------------------------------------------------------------------
COLUMNS = [
    ("transaction_date", "Tanggal"),
    ("description", "Keterangan"),
    ("amount", "Jumlah"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah UMKM Simplified
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("transaction_date", "Tanggal", FieldType.DATE, required=True),
    FieldSpec("description", "Keterangan", required=True),
    FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
    FieldSpec("transaction_type", "Tipe", FieldType.SELECT, choices=("income", "expense",)),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

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
