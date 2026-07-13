"""
ui/pages/work_orders_page.py
===============================
Halaman modul "Work Order Produksi" (Manufaktur).

Endpoint backend : /manufacturing/manufacturing/work-orders
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
# Kolom tabel daftar Work Order Produksi
# ---------------------------------------------------------------------------
COLUMNS = [
    ("wo_number", "No. WO"),
    ("product_id", "Produk"),
    ("quantity", "Qty"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Work Order Produksi
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("bom_id", "BOM (UUID)", FieldType.UUID, required=True),
    FieldSpec("routing_id", "Routing (UUID)"),
    FieldSpec("quantity", "Qty Produksi", FieldType.DECIMAL, required=True),
    FieldSpec("planned_start_date", "Rencana Mulai", FieldType.DATE, required=True),
    FieldSpec("planned_end_date", "Rencana Selesai", FieldType.DATE),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("submit", "Submit", path_suffix="/submit", style="primary"),
    ActionSpec("approve", "Approve", path_suffix="/approve", style="success"),
    ActionSpec("reject", "Reject", path_suffix="/reject", style="danger"),
    ActionSpec("complete", "Complete", path_suffix="/complete", style="success"),
]

CONFIG = ModuleConfig(
    key="work_orders",
    label="Work Order Produksi",
    category="Manufaktur",
    icon="⚙️",
    base_path="/manufacturing/manufacturing",
    list_path="/work-orders",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class WorkOrdersPage(GenericListPage):
    """Halaman Work Order Produksi."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
