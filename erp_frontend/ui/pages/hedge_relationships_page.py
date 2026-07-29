"""
ui/pages/hedge_relationships_page.py
=======================================
Halaman modul "Hedge Relationship" (Treasury).

Endpoint backend : /hedge/hedge/relationships

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
# Kolom tabel daftar Hedge Relationship
# ---------------------------------------------------------------------------
COLUMNS = [
    ("hedge_type", "Tipe"),
    ("hedged_item", "Item Dihedge"),
    ("hedge_ratio", "Rasio"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Hedge Relationship
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("hedge_type", "Tipe Hedge", FieldType.SELECT, choices=("fair_value", "cash_flow", "net_investment",)),
    FieldSpec("hedged_item", "Item Dihedge", required=True),
    FieldSpec("derivative_id", "Derivatif (UUID)", FieldType.UUID, required=True),
    FieldSpec("hedge_ratio", "Rasio Hedge", FieldType.DECIMAL, default=1),
    FieldSpec("designation_date", "Tanggal Penunjukan", FieldType.DATE, required=True),
    FieldSpec("effective_start_date", "Efektif Mulai", FieldType.DATE),
    FieldSpec("effective_end_date", "Efektif Sampai", FieldType.DATE),
    FieldSpec("risk_management_objective", "Tujuan Manajemen Risiko", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="hedge_relationships",
    label="Hedge Relationship",
    category="Treasury",
    icon="🔗",
    base_path="/hedge/hedge",
    list_path="/relationships",
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


class HedgeRelationshipsPage(GenericListPage):
    """Halaman Hedge Relationship."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
