"""
ui/pages/payments_page.py
============================
Halaman modul "Pembayaran (Umum)" (Umum).

Endpoint backend : /payments/payments

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
# Kolom tabel daftar Pembayaran (Umum)
# ---------------------------------------------------------------------------
COLUMNS = [
    ("payment_number", "No. Pembayaran"),
    ("payment_type", "Tipe"),
    ("amount", "Jumlah"),
    ("payment_date", "Tanggal"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Pembayaran (Umum)
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("payment_number", "No. Pembayaran", required=True),
    FieldSpec("payment_type", "Tipe Pembayaran", FieldType.SELECT, required=True, choices=("ap", "ar",), help_text="ap = pembayaran ke supplier (utang), ar = penerimaan dari customer (piutang)"),
    FieldSpec("counterparty_id", "Counterparty (UUID)", FieldType.UUID, required=True),
    FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
    FieldSpec("payment_date", "Tanggal Pembayaran", FieldType.DATE, required=True),
    FieldSpec("invoice_id", "Invoice Terkait (UUID, opsional)", FieldType.UUID),
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
