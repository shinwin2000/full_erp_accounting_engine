"""
ui/pages/audit_page.py
=========================
Halaman modul "Audit & Forensik" (Umum).

Endpoint backend : /audit/audit/findings
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
# Kolom tabel daftar Audit & Forensik
# ---------------------------------------------------------------------------
COLUMNS = [
    ("finding_type", "Tipe Temuan"),
    ("severity", "Tingkat"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Audit & Forensik
# ---------------------------------------------------------------------------
FORM_FIELDS = []

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="audit",
    label="Audit & Forensik",
    category="Umum",
    icon="🕵️",
    base_path="/audit/audit",
    list_path="/findings",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=False,
    can_edit=False,
    can_delete=False,
    search_param="search",
)


class AuditPage(GenericListPage):
    """Halaman Audit & Forensik."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
