"""
ui/pages/intercompany_page.py
================================
Halaman modul "Transaksi Intercompany" (Treasury).

Endpoint backend : /consolidation/consolidation/intercompany
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
    FieldSpec("transaction_type", "Tipe Transaksi"),
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
)


class IntercompanyPage(GenericListPage):
    """Halaman Transaksi Intercompany."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
