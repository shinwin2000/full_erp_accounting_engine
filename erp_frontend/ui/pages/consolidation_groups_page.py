"""
ui/pages/consolidation_groups_page.py
========================================
Halaman modul "Grup Konsolidasi" (Treasury).

Endpoint backend : /consolidation/consolidation/groups

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
    FieldSpec("group_code", "Kode Grup (min. 3 karakter)", required=True),
    FieldSpec("group_name", "Nama Grup (min. 3 karakter)", required=True),
    FieldSpec("parent_entity_id", "Entitas Induk (UUID, opsional)", FieldType.UUID),
    FieldSpec("functional_currency", "Mata Uang Fungsional (3 huruf)", default="IDR"),
    FieldSpec("fiscal_year_start", "Bulan Awal Tahun Fiskal (1-12)", FieldType.NUMBER, default=1),
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
    edit_http_method="PUT",
)


class ConsolidationGroupsPage(GenericListPage):
    """Halaman Grup Konsolidasi."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
