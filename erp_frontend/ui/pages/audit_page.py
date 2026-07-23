"""
ui/pages/audit_page.py
=========================
Halaman modul "Audit & Forensik" (Umum).

Endpoint backend : /audit/audit/findings

REGENERASI OTOMATIS dari registry/module_registry.py (sumber kebenaran
tunggal) supaya field/kolom/aksi SELALU sinkron dengan hasil audit
terhadap schema backend asli — sebelumnya file mandiri ini py bisa jadi
kadaluarsa dibanding registry.py setelah audit, karena keduanya sempat
didefinisikan terpisah. Kalau perlu ubah field modul ini, ubah di
registry.py lalu jalankan ulang skrip regenerasi, JANGAN edit file ini
langsung supaya tidak2 desinkron lagi.
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
    edit_http_method="PUT",
)


class AuditPage(GenericListPage):
    """Halaman Audit & Forensik."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
