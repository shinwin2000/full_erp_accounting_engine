"""
ui/pages/documents_page.py
=============================
Halaman modul "Manajemen Dokumen" (Umum).

Endpoint backend : /documents/documents/
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
# Kolom tabel daftar Manajemen Dokumen
# ---------------------------------------------------------------------------
COLUMNS = [
    ("filename", "Nama File"),
    ("document_type", "Tipe"),
    ("entity_type", "Terkait"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Manajemen Dokumen
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("entity_type", "Tipe Entitas Terkait"),
    FieldSpec("entity_id", "ID Entitas Terkait (UUID)", FieldType.UUID),
    FieldSpec("document_type", "Tipe Dokumen"),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="documents",
    label="Manajemen Dokumen",
    category="Umum",
    icon="📎",
    base_path="/documents/documents",
    list_path="/",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=False,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class DocumentsPage(GenericListPage):
    """Halaman Manajemen Dokumen."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
