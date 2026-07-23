"""
ui/pages/maintenance_work_orders_page.py
===========================================
Halaman modul "Work Order Maintenance" (Aset).

Endpoint backend : /maintenance/maintenance/work-orders

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
# Kolom tabel daftar Work Order Maintenance
# ---------------------------------------------------------------------------
COLUMNS = [
    ("wo_number", "No. WO"),
    ("asset_id", "Aset"),
    ("maintenance_type", "Tipe"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Work Order Maintenance
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("wo_number", "No. Work Order", required=True),
    FieldSpec("asset_id", "Aset (UUID)", FieldType.UUID, required=True),
    FieldSpec("schedule_id", "Jadwal (UUID, opsional)", FieldType.UUID),
    FieldSpec("maintenance_type", "Tipe Maintenance", FieldType.SELECT, required=True, choices=("preventive", "corrective", "predictive", "emergency", "routine",)),
    FieldSpec("priority", "Prioritas", FieldType.SELECT, choices=("low", "medium", "high", "critical",), default="medium"),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA, required=True),
    FieldSpec("requested_by", "Diminta Oleh (UUID)", FieldType.UUID, required=True),
    FieldSpec("planned_start_date", "Rencana Mulai", FieldType.DATE, required=True),
    FieldSpec("planned_end_date", "Rencana Selesai (harus setelah mulai)", FieldType.DATE, required=True),
    FieldSpec("estimated_cost", "Estimasi Biaya", FieldType.DECIMAL, default=0),
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
    edit_http_method="PUT",
)


class MaintenanceWorkOrdersPage(GenericListPage):
    """Halaman Work Order Maintenance."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
