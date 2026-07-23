"""
ui/pages/work_orders_page.py
===============================
Halaman modul "Work Order Produksi" (Manufaktur).

Endpoint backend : /manufacturing/manufacturing/work-orders

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
# Kolom tabel daftar Work Order Produksi
# ---------------------------------------------------------------------------
COLUMNS = [
    ("work_order_number", "No. WO"),
    ("product_id", "Produk"),
    ("planned_quantity", "Qty"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Work Order Produksi
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("work_order_number", "No. Work Order", required=True),
    FieldSpec("product_id", "Produk (UUID)", FieldType.UUID, required=True),
    FieldSpec("planned_quantity", "Qty Rencana (harus > 0)", FieldType.DECIMAL, required=True),
    FieldSpec("planned_start_date", "Rencana Mulai", FieldType.DATE, required=True),
    FieldSpec("planned_end_date", "Rencana Selesai", FieldType.DATE, required=True),
    FieldSpec("bom_id", "BOM (UUID, opsional)", FieldType.UUID),
    FieldSpec("routing_id", "Routing (UUID, opsional)", FieldType.UUID),
    FieldSpec("cost_center", "Cost Center"),
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
    edit_http_method="PUT",
)


class WorkOrdersPage(GenericListPage):
    """Halaman Work Order Produksi."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
