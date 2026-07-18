"""
ui/pages/payments_page.py
============================
Halaman modul "Pembayaran (Umum)" (Umum).

Endpoint backend : /payments/payments
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
# Kolom tabel daftar Pembayaran (Umum)
# ---------------------------------------------------------------------------
COLUMNS = [
    ("payment_number", "No. Pembayaran"),
    ("amount", "Jumlah"),
    ("reference_number", "Referensi"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Pembayaran (Umum)
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("payment_number", "No. Pembayaran", required=True),
    FieldSpec("counterparty_id", "Counterparty (UUID)", FieldType.UUID, required=True),
    FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
    FieldSpec("reference_number", "No. Referensi"),
    FieldSpec("description", "Keterangan", FieldType.TEXTAREA),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec("approve", "Approve", path_suffix="/approve", style="success"),
    ActionSpec("process", "Process", path_suffix="/process", style="primary"),
]

CONFIG = ModuleConfig(
    key="payments",
    label="Pembayaran (Umum)",
    category="Umum",
    icon="💸",
    base_path="/payments",
    list_path="/payments",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
    edit_http_method="PATCH",
)


class PaymentsPage(GenericListPage):
    """Halaman Pembayaran (Umum)."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
