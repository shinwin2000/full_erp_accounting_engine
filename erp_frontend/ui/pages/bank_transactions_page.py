"""
ui/pages/bank_transactions_page.py
=====================================
Halaman modul "Transaksi Bank/Kas" (Kas & Bank).

Endpoint backend : /bank-cash/bank-cash/transactions

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
# Kolom tabel daftar Transaksi Bank/Kas
# ---------------------------------------------------------------------------
COLUMNS = [
    ("transaction_date", "Tanggal"),
    ("transaction_type", "Tipe"),
    ("amount", "Jumlah"),
    ("description", "Keterangan"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Transaksi Bank/Kas
#
# PENTING (fix): sebelumnya `bank_account_id` dan `transaction_type` TIDAK
# ada di sini, padahal keduanya wajib menurut schema backend
# `BankTransactionCreateSchema` (adapters/primary_api/v1/
# fastapi_bank_cash_router.py). Akibatnya setiap submit selalu gagal 422
# "bank_account_id: Field required; transaction_type: Field required".
# Pilihan transaction_type disamakan persis dengan enum backend
# (domain/bank_cash/bank_transaction_entity.py: TransactionType).
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("bank_account_id", "Rekening Bank", FieldType.LOOKUP, required=True,
              lookup_path="/bank-cash/bank-cash/bank-accounts",
              lookup_value_field="id",
              lookup_label_fields=("account_number", "account_name", "bank_name")),
    FieldSpec("transaction_date", "Tanggal", FieldType.DATE, required=True),
    FieldSpec("transaction_type", "Tipe Transaksi", FieldType.SELECT,
              choices=("deposit", "withdrawal", "transfer_in", "transfer_out",
                       "fee", "interest", "cheque", "adjustment"), required=True),
    FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
    FieldSpec("description", "Keterangan", FieldType.TEXTAREA, required=True),
]

# ---------------------------------------------------------------------------
# Field KHUSUS untuk form "Ubah" (fix: sengaja berbeda dari FORM_FIELDS di
# atas, dipakai saat "+ Baru").
#
# Backend (application/service_layer/service_bank_cash.py:
# update_transaction) SENGAJA hanya mendukung update description,
# reference_number, dan status - TIDAK bank_account_id/transaction_date/
# transaction_type/amount. Ini praktik standar akuntansi: transaksi yang
# sudah tercatat (apalagi sudah mempengaruhi saldo) tidak boleh diubah
# nilainya langsung supaya jejak audit tetap utuh; koreksi nilai
# semestinya lewat transaksi pembalik (reversal), bukan edit langsung.
#
# Sebelumnya form Ubah memakai FORM_FIELDS yang sama dengan "+ Baru",
# sehingga user bisa mengetik jumlah baru di form tapi backend diam-diam
# mengabaikannya - field itu memang tidak pernah benar-benar tersimpan.
# ---------------------------------------------------------------------------
EDIT_FORM_FIELDS = [
    FieldSpec("reference_number", "No. Referensi", FieldType.TEXT),
    FieldSpec("status", "Status", FieldType.SELECT,
              choices=("pending", "completed", "cleared", "rejected",
                       "cancelled", "reconciled"), required=True),
    FieldSpec("description", "Keterangan", FieldType.TEXTAREA, required=True),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
#
# FIX: sebelumnya modul ini memakai tombol "Hapus" bawaan (can_delete=True)
# yang mengirim DELETE /transactions/{id} - padahal endpoint itu TIDAK
# PERNAH ada di backend (selalu gagal 405 Method Not Allowed). Backend
# memang sengaja tidak mendukung hapus permanen untuk transaksi yang
# sudah tercatat (demi jejak audit) - yang ada cuma endpoint
# POST /transactions/{id}/reverse untuk membalikkan/membatalkan
# transaksi. Tombol "Hapus" diganti aksi "Batalkan (Reverse)" di bawah.
# ---------------------------------------------------------------------------
ACTIONS = [
    ActionSpec(
        name="reverse",
        label="Batalkan (Reverse)",
        method="POST",
        path_suffix="/reverse",
        confirm=True,
        style="danger",
        needs_reason=True,
        reason_min_length=5,
        reason_in_body=True,
    ),
]

CONFIG = ModuleConfig(
    key="bank_transactions",
    label="Transaksi Bank/Kas",
    category="Kas & Bank",
    icon="💵",
    base_path="/bank-cash/bank-cash",
    list_path="/transactions",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    edit_form_fields=EDIT_FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=False,
    search_param="search",
    edit_http_method="PUT",
)


class BankTransactionsPage(GenericListPage):
    """Halaman Transaksi Bank/Kas."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
