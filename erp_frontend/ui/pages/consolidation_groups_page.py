"""
ui/pages/consolidation_groups_page.py
========================================
Halaman modul "Grup Konsolidasi" (Treasury).

Endpoint backend : /consolidation/consolidation/groups
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
# Kolom tabel daftar Grup Konsolidasi
# ---------------------------------------------------------------------------
COLUMNS = [
    ("group_code", "Kode"),
    ("group_name", "Nama Grup"),
    ("functional_currency", "Mata Uang Fungsional"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Grup Konsolidasi
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("group_code", "Kode Grup", required=True),
    FieldSpec("group_name", "Nama Grup", required=True),
    FieldSpec("parent_entity_id", "Entitas Induk (UUID)", FieldType.UUID, required=True),
    FieldSpec("functional_currency", "Mata Uang Fungsional", required=True, default="IDR"),
    FieldSpec("fiscal_year_start", "Awal Tahun Fiskal", FieldType.DATE),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="consolidation_groups",
    label="Grup Konsolidasi",
    category="Treasury",
    icon="🧩",
    base_path="/consolidation/consolidation",
    list_path="/groups",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class ConsolidationGroupsPage(GenericListPage):
    """Halaman Grup Konsolidasi."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
