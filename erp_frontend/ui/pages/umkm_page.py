"""
ui/pages/umkm_page.py
========================
Halaman modul "UMKM Simplified" (Umum).

Endpoint backend : /umkm/umkm/journals
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
)


class UmkmPage(GenericListPage):
    """Halaman UMKM Simplified."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
