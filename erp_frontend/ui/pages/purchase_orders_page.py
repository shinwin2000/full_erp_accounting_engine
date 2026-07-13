"""
ui/pages/purchase_orders_page.py
===================================
Halaman modul "Purchase Order" (Pembelian & Penjualan).

Endpoint backend : /purchase-sales/purchase-sales/purchase-orders
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
# Kolom tabel daftar Purchase Order
# ---------------------------------------------------------------------------
COLUMNS = [
    ("po_number", "No. PO"),
    ("po_date", "Tanggal"),
    ("supplier_id", "Supplier"),
    ("status", "Status"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Purchase Order
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("po_number", "No. PO", required=True),
    FieldSpec("po_date", "Tanggal PO", FieldType.DATE, required=True),
    FieldSpec("supplier_id", "Supplier (UUID)", FieldType.UUID, required=True),
    FieldSpec("expected_delivery_date", "Estimasi Kirim", FieldType.DATE),
    FieldSpec("delivery_term_days", "Termin Kirim (hari)", FieldType.NUMBER),
    FieldSpec("payment_term_days", "Termin Bayar (hari)", FieldType.NUMBER),
    FieldSpec("incoterm", "Incoterm"),
    FieldSpec("order_type", "Tipe Order"),
    FieldSpec("reference_number", "No. Referensi"),
    FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("submit", "Submit", path_suffix="/submit", style="primary"),
    ActionSpec("approve", "Approve", path_suffix="/approve", style="success"),
    ActionSpec("reject", "Reject", path_suffix="/reject", style="danger"),
    ActionSpec("post", "Post", path_suffix="/post", style="primary"),
    ActionSpec("reverse", "Reverse", path_suffix="/reverse", style="danger"),
]

CONFIG = ModuleConfig(
    key="purchase_orders",
    label="Purchase Order",
    category="Pembelian & Penjualan",
    icon="🛒",
    base_path="/purchase-sales/purchase-sales",
    list_path="/purchase-orders",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class PurchaseOrdersPage(GenericListPage):
    """Halaman Purchase Order."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
