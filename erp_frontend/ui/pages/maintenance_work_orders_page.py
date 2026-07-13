"""
ui/pages/maintenance_work_orders_page.py
===========================================
Halaman modul "Work Order Maintenance" (Aset).

Endpoint backend : /maintenance/maintenance/work-orders
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
# Kolom tabel daftar Work Order Maintenance
# ---------------------------------------------------------------------------
COLUMNS = [
    ("work_order_number", "No. WO"),
    ("asset_id", "Aset"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Work Order Maintenance
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("asset_id", "Aset (UUID)", FieldType.UUID, required=True),
    FieldSpec("schedule_id", "Jadwal (UUID)", FieldType.UUID),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA, required=True),
    FieldSpec("priority", "Prioritas", FieldType.SELECT, choices=("low", "medium", "high", "critical",)),
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
    key="maintenance_work_orders",
    label="Work Order Maintenance",
    category="Aset",
    icon="🛠️",
    base_path="/maintenance/maintenance",
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


class MaintenanceWorkOrdersPage(GenericListPage):
    """Halaman Work Order Maintenance."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
