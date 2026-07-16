#!/usr/bin/env python3
"""
Module: ar_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk Account Receivable Invoice repository.

Fitur: siklus hidup invoice (draft, submitted, approved, partially_paid, paid,
cancelled, disputed, written_off), aging buckets, collection status,
credit limit monitoring, dunning letters, payment scheduling, credit/debit notes,
customer balance, due date tracking, audit trail, import/export CSV, dan statistik.

Perbaikan presisi:
  - Semua nilai moneter disimpan sebagai Decimal.
  - Tidak ada konversi ke float pada nilai moneter (diganti dengan str() untuk output).
"""

from __future__ import annotations

import asyncio
import csv
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class ARInvoiceStatus(Enum):
    """Status invoice AR."""

    DRAFT = "draft"  # Input awal, masih bisa diedit
    SUBMITTED = "submitted"  # Diajukan untuk approval
    APPROVED = "approved"  # Disetujui, menunggu pembayaran
    PARTIALLY_PAID = "partially_paid"  # Sebagian dibayar
    PAID = "paid"  # Lunas
    CANCELLED = "cancelled"  # Dibatalkan
    DISPUTED = "disputed"  # Dalam sengketa dengan customer
    OVERDUE = "overdue"  # Jatuh tempo belum dibayar
    WRITTEN_OFF = "written_off"  # Dihapuskan (bad debt)


class CollectionStatus(Enum):
    """Status penagihan."""

    NOT_DUE = "not_due"  # Belum jatuh tempo
    DUE = "due"  # Jatuh tempo hari ini
    OVERDUE_1_30 = "overdue_1_30"  # Lewat 1-30 hari
    OVERDUE_31_60 = "overdue_31_60"  # Lewat 31-60 hari
    OVERDUE_61_90 = "overdue_61_90"  # Lewat 61-90 hari
    OVERDUE_90_PLUS = "overdue_90_plus"  # Lewat >90 hari
    IN_COLLECTION = "in_collection"  # Dalam proses penagihan intensif
    LEGAL = "legal"  # Proses hukum


@dataclass
class ARInvoice:
    """
    Aggregate Root AR Invoice.
    """

    id: UUID
    invoice_number: str
    customer_id: UUID
    legal_entity_id: UUID
    sales_order_id: UUID | None
    invoice_date: date
    due_date: date
    total_amount: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    currency_code: str = "IDR"
    exchange_rate: Decimal = Decimal(1)
    status: ARInvoiceStatus = ARInvoiceStatus.DRAFT
    collection_status: CollectionStatus = CollectionStatus.NOT_DUE
    description: str | None = None
    payment_terms: str = "NET30"  # NET30, N20, EOM
    payment_schedule_date: date | None = None
    payment_received_date: date | None = None
    last_payment_amount: Decimal = Decimal(0)
    last_payment_date: date | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    cancelled_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    disputed_reason: str | None = None
    write_off_amount: Decimal = Decimal(0)
    write_off_date: date | None = None
    write_off_reason: str | None = None
    dunning_level: int = 0  # 0 = no dunning, 1-5 = tingkat surat tagihan
    last_dunning_date: date | None = None
    attachment_urls: list[str] = field(default_factory=list)
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_number": self.invoice_number,
            "customer_id": str(self.customer_id),
            "legal_entity_id": str(self.legal_entity_id),
            "sales_order_id": str(self.sales_order_id) if self.sales_order_id else None,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "total_amount": str(self.total_amount),
            "tax_amount": str(self.tax_amount),
            "discount_amount": str(self.discount_amount),
            "paid_amount": str(self.paid_amount),
            "outstanding_amount": str(self.outstanding_amount),
            "currency_code": self.currency_code,
            "exchange_rate": str(self.exchange_rate),
            "status": self.status.value,
            "collection_status": self.collection_status.value,
            "description": self.description,
            "payment_terms": self.payment_terms,
            "payment_schedule_date": self.payment_schedule_date.isoformat()
            if self.payment_schedule_date
            else None,
            "payment_received_date": self.payment_received_date.isoformat()
            if self.payment_received_date
            else None,
            "last_payment_amount": str(self.last_payment_amount),
            "last_payment_date": self.last_payment_date.isoformat()
            if self.last_payment_date
            else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "cancelled_by": str(self.cancelled_by) if self.cancelled_by else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancellation_reason": self.cancellation_reason,
            "disputed_reason": self.disputed_reason,
            "write_off_amount": str(self.write_off_amount),
            "write_off_date": self.write_off_date.isoformat() if self.write_off_date else None,
            "write_off_reason": self.write_off_reason,
            "dunning_level": self.dunning_level,
            "last_dunning_date": self.last_dunning_date.isoformat()
            if self.last_dunning_date
            else None,
            "attachment_urls": self.attachment_urls,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
        }


@dataclass
class CreditNoteAR:
    """Nota kredit untuk customer (pengurang piutang)."""

    id: UUID
    credit_note_number: str
    customer_id: UUID
    legal_entity_id: UUID
    original_invoice_id: UUID
    credit_date: date
    amount: Decimal
    reason: str
    created_at: datetime
    created_by: UUID


@dataclass
class DebitNoteAR:
    """Nota debet untuk customer (penambah piutang)."""

    id: UUID
    debit_note_number: str
    customer_id: UUID
    legal_entity_id: UUID
    original_invoice_id: UUID
    debit_date: date
    amount: Decimal
    reason: str
    created_at: datetime
    created_by: UUID


# ============================================================================
# PORT INTERFACE (Abstract Base Class)
# ============================================================================

class ARRepositoryPort(ABC):
    """
    Port (interface) untuk repository Account Receivable.
    Semua metode wajib diimplementasikan oleh repository concrete.
    """

    # === CRUD ===

    @abstractmethod
    async def add(self, invoice: ARInvoice) -> None:
        """Menambahkan invoice AR baru."""
        pass

    @abstractmethod
    async def get_by_id(self, invoice_id: UUID) -> ARInvoice | None:
        """Mengambil invoice berdasarkan ID."""
        pass

    @abstractmethod
    async def get_by_invoice_number(self, invoice_number: str, legal_entity_id: UUID) -> ARInvoice | None:
        """Mengambil invoice berdasarkan nomor invoice dan legal entity."""
        pass

    @abstractmethod
    async def update(self, invoice: ARInvoice) -> None:
        """Memperbarui invoice yang sudah ada."""
        pass

    @abstractmethod
    async def delete(self, invoice_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Soft delete atau permanent delete invoice."""
        pass

    # === WORKFLOW ACTIONS ===

    @abstractmethod
    async def submit_for_approval(self, invoice_id: UUID, user_id: UUID) -> bool:
        """Submit invoice untuk approval."""
        pass

    @abstractmethod
    async def approve(self, invoice_id: UUID, approver_id: UUID) -> bool:
        """Menyetujui invoice."""
        pass

    @abstractmethod
    async def record_payment(
        self, invoice_id: UUID, amount: Decimal, payment_date: date, user_id: UUID
    ) -> bool:
        """Merekam pembayaran dari customer."""
        pass

    @abstractmethod
    async def cancel(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        """Membatalkan invoice."""
        pass

    @abstractmethod
    async def dispute(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        """Menandai invoice sebagai disputed."""
        pass

    @abstractmethod
    async def write_off(
        self, invoice_id: UUID, amount: Decimal, reason: str, user_id: UUID
    ) -> bool:
        """Menghapuskan piutang (write-off)."""
        pass

    # === CREDIT / DEBIT NOTES ===

    @abstractmethod
    async def add_credit_note(self, credit_note: CreditNoteAR) -> None:
        """Menambahkan credit note dan mengupdate outstanding."""
        pass

    @abstractmethod
    async def add_debit_note(self, debit_note: DebitNoteAR) -> None:
        """Menambahkan debit note dan mengupdate outstanding."""
        pass

    # === QUERY ===

    @abstractmethod
    async def find_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[ARInvoice]:
        """Mencari invoice berdasarkan customer."""
        pass

    @abstractmethod
    async def find_overdue_invoices(
        self, as_of_date: date, legal_entity_id: UUID
    ) -> list[ARInvoice]:
        """Mencari invoice yang telah jatuh tempo."""
        pass

    @abstractmethod
    async def get_outstanding_balance(self, customer_id: UUID, as_of_date: date) -> Decimal:
        """Menghitung outstanding balance customer per tanggal."""
        pass

    @abstractmethod
    async def find_by_status(
        self, status: ARInvoiceStatus, legal_entity_id: UUID
    ) -> list[ARInvoice]:
        """Mencari invoice berdasarkan status."""
        pass

    @abstractmethod
    async def find_by_date_range(
        self, start_date: date, end_date: date, legal_entity_id: UUID
    ) -> list[ARInvoice]:
        """Mencari invoice berdasarkan rentang tanggal invoice."""
        pass

    @abstractmethod
    async def get_aging_buckets(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> dict[str, Decimal]:
        """Mendapatkan aging buckets piutang."""
        pass

    @abstractmethod
    async def get_dunning_candidates(
        self, legal_entity_id: UUID, min_overdue_days: int = 30
    ) -> list[ARInvoice]:
        """Mendapatkan invoice yang perlu dikirimi surat tagihan."""
        pass

    @abstractmethod
    async def increment_dunning_level(self, invoice_id: UUID, user_id: UUID) -> int:
        """Menaikkan level dunning untuk invoice."""
        pass

    @abstractmethod
    async def get_customer_balance_history(
        self, customer_id: UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Riwayat saldo customer per bulan."""
        pass

    # === CREDIT LIMIT ===

    @abstractmethod
    async def get_total_outstanding_for_customer(self, customer_id: UUID) -> Decimal:
        """Total outstanding customer saat ini."""
        pass

    @abstractmethod
    async def is_credit_limit_exceeded(
        self, customer_id: UUID, credit_limit: Decimal, additional_amount: Decimal = Decimal(0)
    ) -> bool:
        """Cek apakah credit limit sudah terlampaui."""
        pass

    # === IMPORT / EXPORT ===

    @abstractmethod
    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        """Ekspor invoice ke CSV."""
        pass

    @abstractmethod
    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        """Impor invoice dari CSV."""
        pass

    # === STATISTICS & AUDIT ===

    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Statistik AR."""
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Audit log AR."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check repository."""
        pass


# ============================================================================
# IMPLEMENTASI KONKRET (In-Memory)
# ============================================================================

class InMemoryARRepository(ARRepositoryPort):
    """
    Implementasi in-memory repository untuk Account Receivable.
    """

    def __init__(self):
        self._storage: dict[UUID, ARInvoice] = {}
        self._customer_index: dict[UUID, list[UUID]] = {}
        self._status_index: dict[ARInvoiceStatus, list[UUID]] = {}
        self._so_index: dict[UUID, list[UUID]] = {}  # sales_order_id -> invoice ids
        self._credit_notes: dict[UUID, CreditNoteAR] = {}
        self._debit_notes: dict[UUID, DebitNoteAR] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ==================== HELPER ====================

    async def _log_audit(
        self, action: str, invoice_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "invoice_id": str(invoice_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"AR AUDIT: {action} on invoice {invoice_id} by {user_id}")

    async def _recompute_outstanding(self, invoice: ARInvoice):
        """Hitung outstanding = total - paid - credit_notes + debit_notes."""
        total_credit = Decimal(0)
        total_debit = Decimal(0)
        for cn in self._credit_notes.values():
            if cn.original_invoice_id == invoice.id:
                total_credit += cn.amount
        for dn in self._debit_notes.values():
            if dn.original_invoice_id == invoice.id:
                total_debit += dn.amount
        invoice.outstanding_amount = (
            invoice.total_amount - invoice.paid_amount - total_credit + total_debit
        )
        if invoice.outstanding_amount < 0:
            invoice.outstanding_amount = Decimal(0)
        # Update status berdasarkan outstanding
        if invoice.outstanding_amount == 0 and invoice.status not in (
            ARInvoiceStatus.CANCELLED,
            ARInvoiceStatus.DISPUTED,
            ARInvoiceStatus.WRITTEN_OFF,
        ):
            invoice.status = ARInvoiceStatus.PAID
            invoice.payment_received_date = date.today()
        elif invoice.outstanding_amount < invoice.total_amount and invoice.outstanding_amount > 0:
            invoice.status = ARInvoiceStatus.PARTIALLY_PAID
        # Update collection status berdasarkan due date
        await self._update_collection_status(invoice)

    async def _update_collection_status(self, invoice: ARInvoice):
        """Update collection status based on due date and outstanding."""
        if invoice.outstanding_amount == 0:
            invoice.collection_status = CollectionStatus.NOT_DUE
            return
        today = date.today()
        if invoice.due_date > today:
            invoice.collection_status = CollectionStatus.NOT_DUE
        elif invoice.due_date == today:
            invoice.collection_status = CollectionStatus.DUE
        else:
            days_overdue = (today - invoice.due_date).days
            if days_overdue <= 30:
                invoice.collection_status = CollectionStatus.OVERDUE_1_30
            elif days_overdue <= 60:
                invoice.collection_status = CollectionStatus.OVERDUE_31_60
            elif days_overdue <= 90:
                invoice.collection_status = CollectionStatus.OVERDUE_61_90
            else:
                invoice.collection_status = CollectionStatus.OVERDUE_90_PLUS
            if invoice.dunning_level >= 3:
                invoice.collection_status = CollectionStatus.IN_COLLECTION
            elif invoice.dunning_level >= 5:
                invoice.collection_status = CollectionStatus.LEGAL

    async def _update_indices(self, invoice: ARInvoice, is_insert: bool = True):
        if is_insert:
            # Customer index
            if invoice.customer_id not in self._customer_index:
                self._customer_index[invoice.customer_id] = []
            if invoice.id not in self._customer_index[invoice.customer_id]:
                self._customer_index[invoice.customer_id].append(invoice.id)
            # Status index
            if invoice.status not in self._status_index:
                self._status_index[invoice.status] = []
            if invoice.id not in self._status_index[invoice.status]:
                self._status_index[invoice.status].append(invoice.id)
            # Sales order index
            if invoice.sales_order_id:
                if invoice.sales_order_id not in self._so_index:
                    self._so_index[invoice.sales_order_id] = []
                if invoice.id not in self._so_index[invoice.sales_order_id]:
                    self._so_index[invoice.sales_order_id].append(invoice.id)

    # ==================== CRUD ====================

    async def add(self, invoice: ARInvoice) -> None:
        if invoice.id in self._storage:
            raise ValueError(f"Invoice {invoice.id} already exists")
        if invoice.due_date < invoice.invoice_date:
            raise ValueError("Due date cannot be before invoice date")
        invoice.outstanding_amount = invoice.total_amount - invoice.paid_amount
        invoice.created_at = datetime.now(UTC)
        invoice.updated_at = invoice.created_at
        invoice.version = 1
        await self._update_collection_status(invoice)
        async with self._lock:
            self._storage[invoice.id] = invoice
            await self._update_indices(invoice, is_insert=True)
        await self._log_audit(
            "ADD",
            invoice.id,
            invoice.created_by,
            {
                "invoice_number": invoice.invoice_number,
                "customer_id": str(invoice.customer_id),
                "amount": str(invoice.total_amount),
            },
        )

    async def get_by_id(self, invoice_id: UUID) -> ARInvoice | None:
        return self._storage.get(invoice_id)

    async def get_by_invoice_number(
        self, invoice_number: str, legal_entity_id: UUID
    ) -> ARInvoice | None:
        for inv in self._storage.values():
            if inv.invoice_number == invoice_number and inv.legal_entity_id == legal_entity_id:
                return inv
        return None

    async def update(self, invoice: ARInvoice) -> None:
        if invoice.id not in self._storage:
            raise ValueError(f"Invoice {invoice.id} not found")
        old = self._storage[invoice.id]
        # Only draft invoices can be updated directly
        if old.status != ARInvoiceStatus.DRAFT and invoice.status == old.status:
            raise ValueError(
                f"Cannot update invoice with status {old.status.value}. Only DRAFT allowed."
            )
        # Update indices if customer changed
        if old.customer_id != invoice.customer_id:
            if (
                old.customer_id in self._customer_index
                and old.id in self._customer_index[old.customer_id]
            ):
                self._customer_index[old.customer_id].remove(old.id)
            if invoice.customer_id not in self._customer_index:
                self._customer_index[invoice.customer_id] = []
            if invoice.id not in self._customer_index[invoice.customer_id]:
                self._customer_index[invoice.customer_id].append(invoice.id)
        # Update status index if status changed
        if old.status != invoice.status:
            if old.status in self._status_index and old.id in self._status_index[old.status]:
                self._status_index[old.status].remove(old.id)
            if invoice.status not in self._status_index:
                self._status_index[invoice.status] = []
            if invoice.id not in self._status_index[invoice.status]:
                self._status_index[invoice.status].append(invoice.id)
        invoice.updated_at = datetime.now(UTC)
        invoice.version = old.version + 1
        invoice.created_at = old.created_at
        invoice.created_by = old.created_by
        await self._recompute_outstanding(invoice)
        async with self._lock:
            self._storage[invoice.id] = invoice
        await self._log_audit(
            "UPDATE",
            invoice.id,
            invoice.updated_by,
            {
                "status_change": f"{old.status.value} -> {invoice.status.value}",
            },
        )

    async def delete(self, invoice_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        invoice = self._storage.get(invoice_id)
        if not invoice:
            return False
        if invoice.status not in (ARInvoiceStatus.DRAFT, ARInvoiceStatus.CANCELLED):
            raise ValueError(f"Cannot delete invoice with status {invoice.status.value}")
        if permanent:
            if (
                invoice.customer_id in self._customer_index
                and invoice.id in self._customer_index[invoice.customer_id]
            ):
                self._customer_index[invoice.customer_id].remove(invoice.id)
            if (
                invoice.status in self._status_index
                and invoice.id in self._status_index[invoice.status]
            ):
                self._status_index[invoice.status].remove(invoice.id)
            if invoice.sales_order_id and invoice.sales_order_id in self._so_index:
                if invoice.id in self._so_index[invoice.sales_order_id]:
                    self._so_index[invoice.sales_order_id].remove(invoice.id)
            del self._storage[invoice_id]
            await self._log_audit("DELETE_PERMANENT", invoice_id, user_id, {})
        else:
            invoice.status = ARInvoiceStatus.CANCELLED
            invoice.cancelled_at = datetime.now(UTC)
            invoice.cancelled_by = user_id
            invoice.updated_at = invoice.cancelled_at
            invoice.version += 1
            await self.update(invoice)
        return True

    # ==================== WORKFLOW ACTIONS ====================

    async def submit_for_approval(self, invoice_id: UUID, user_id: UUID) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status != ARInvoiceStatus.DRAFT:
            return False
        invoice.status = ARInvoiceStatus.SUBMITTED
        invoice.updated_by = user_id
        await self.update(invoice)
        await self._log_audit("SUBMIT", invoice_id, user_id, {})
        return True

    async def approve(self, invoice_id: UUID, approver_id: UUID) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status != ARInvoiceStatus.SUBMITTED:
            return False
        invoice.status = ARInvoiceStatus.APPROVED
        invoice.approved_by = approver_id
        invoice.approved_at = datetime.now(UTC)
        invoice.updated_by = approver_id
        await self.update(invoice)
        await self._log_audit("APPROVE", invoice_id, approver_id, {})
        return True

    async def record_payment(
        self, invoice_id: UUID, amount: Decimal, payment_date: date, user_id: UUID
    ) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status not in (
            ARInvoiceStatus.APPROVED,
            ARInvoiceStatus.PARTIALLY_PAID,
        ):
            return False
        if amount <= 0:
            return False
        if amount > invoice.outstanding_amount:
            amount = invoice.outstanding_amount
        invoice.paid_amount += amount
        invoice.last_payment_amount = amount
        invoice.last_payment_date = payment_date
        invoice.updated_by = user_id
        await self._recompute_outstanding(invoice)
        await self.update(invoice)
        await self._log_audit(
            "RECORD_PAYMENT",
            invoice_id,
            user_id,
            {
                "amount": str(amount),
                "payment_date": payment_date.isoformat(),
            },
        )
        return True

    async def cancel(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status == ARInvoiceStatus.PAID:
            return False
        invoice.status = ARInvoiceStatus.CANCELLED
        invoice.cancellation_reason = reason
        invoice.cancelled_by = user_id
        invoice.cancelled_at = datetime.now(UTC)
        invoice.updated_by = user_id
        await self.update(invoice)
        await self._log_audit("CANCEL", invoice_id, user_id, {"reason": reason})
        return True

    async def dispute(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status == ARInvoiceStatus.PAID:
            return False
        invoice.status = ARInvoiceStatus.DISPUTED
        invoice.disputed_reason = reason
        invoice.updated_by = user_id
        await self.update(invoice)
        await self._log_audit("DISPUTE", invoice_id, user_id, {"reason": reason})
        return True

    async def write_off(
        self, invoice_id: UUID, amount: Decimal, reason: str, user_id: UUID
    ) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.outstanding_amount == 0:
            return False
        if amount > invoice.outstanding_amount:
            amount = invoice.outstanding_amount
        invoice.write_off_amount = amount
        invoice.write_off_date = date.today()
        invoice.write_off_reason = reason
        invoice.paid_amount += amount  # treat as reduction
        invoice.status = ARInvoiceStatus.WRITTEN_OFF
        invoice.updated_by = user_id
        await self._recompute_outstanding(invoice)
        await self.update(invoice)
        await self._log_audit(
            "WRITE_OFF",
            invoice_id,
            user_id,
            {
                "amount": str(amount),
                "reason": reason,
            },
        )
        return True

    # ==================== CREDIT/DEBIT NOTES ====================

    async def add_credit_note(self, credit_note: CreditNoteAR) -> None:
        self._credit_notes[credit_note.id] = credit_note
        invoice = await self.get_by_id(credit_note.original_invoice_id)
        if invoice:
            await self._recompute_outstanding(invoice)
            await self.update(invoice)
        await self._log_audit(
            "CREDIT_NOTE",
            credit_note.original_invoice_id,
            credit_note.created_by,
            {
                "credit_note_id": str(credit_note.id),
                "amount": str(credit_note.amount),
            },
        )

    async def add_debit_note(self, debit_note: DebitNoteAR) -> None:
        self._debit_notes[debit_note.id] = debit_note
        invoice = await self.get_by_id(debit_note.original_invoice_id)
        if invoice:
            await self._recompute_outstanding(invoice)
            await self.update(invoice)
        await self._log_audit(
            "DEBIT_NOTE",
            debit_note.original_invoice_id,
            debit_note.created_by,
            {
                "debit_note_id": str(debit_note.id),
                "amount": str(debit_note.amount),
            },
        )

    # ==================== QUERY ====================

    async def find_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[ARInvoice]:
        ids = self._customer_index.get(customer_id, [])
        invoices = [
            self._storage[iid]
            for iid in ids
            if iid in self._storage and self._storage[iid].legal_entity_id == legal_entity_id
        ]
        invoices.sort(key=lambda x: x.due_date)
        return invoices[offset : offset + limit]

    async def find_overdue_invoices(
        self, as_of_date: date, legal_entity_id: UUID
    ) -> list[ARInvoice]:
        result = []
        for inv in self._storage.values():
            if inv.legal_entity_id == legal_entity_id and inv.status in (
                ARInvoiceStatus.APPROVED,
                ARInvoiceStatus.PARTIALLY_PAID,
            ):
                if inv.due_date < as_of_date and inv.outstanding_amount > 0:
                    result.append(inv)
        return sorted(result, key=lambda x: x.due_date)

    async def get_outstanding_balance(self, customer_id: UUID, as_of_date: date) -> Decimal:
        total = Decimal(0)
        for inv in self._storage.values():
            if inv.customer_id == customer_id:
                if inv.status in (
                    ARInvoiceStatus.APPROVED,
                    ARInvoiceStatus.PARTIALLY_PAID,
                    ARInvoiceStatus.DISPUTED,
                ):
                    if inv.due_date <= as_of_date:
                        total += inv.outstanding_amount
        return total

    async def find_by_status(
        self, status: ARInvoiceStatus, legal_entity_id: UUID
    ) -> list[ARInvoice]:
        ids = self._status_index.get(status, [])
        return [
            self._storage[iid]
            for iid in ids
            if iid in self._storage and self._storage[iid].legal_entity_id == legal_entity_id
        ]

    async def find_by_date_range(
        self, start_date: date, end_date: date, legal_entity_id: UUID
    ) -> list[ARInvoice]:
        result = []
        for inv in self._storage.values():
            if (
                inv.legal_entity_id == legal_entity_id
                and start_date <= inv.invoice_date <= end_date
            ):
                result.append(inv)
        return sorted(result, key=lambda x: x.invoice_date)

    async def get_aging_buckets(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> dict[str, Decimal]:
        """Aging buckets untuk piutang."""
        buckets = {
            "current": Decimal(0),
            "1_30": Decimal(0),
            "31_60": Decimal(0),
            "61_90": Decimal(0),
            "90_plus": Decimal(0),
        }
        for inv in self._storage.values():
            if inv.legal_entity_id == legal_entity_id and inv.status in (
                ARInvoiceStatus.APPROVED,
                ARInvoiceStatus.PARTIALLY_PAID,
                ARInvoiceStatus.DISPUTED,
            ):
                days_diff = (as_of_date - inv.due_date).days
                if days_diff <= 0:
                    buckets["current"] += inv.outstanding_amount
                elif 1 <= days_diff <= 30:
                    buckets["1_30"] += inv.outstanding_amount
                elif 31 <= days_diff <= 60:
                    buckets["31_60"] += inv.outstanding_amount
                elif 61 <= days_diff <= 90:
                    buckets["61_90"] += inv.outstanding_amount
                else:
                    buckets["90_plus"] += inv.outstanding_amount
        return buckets

    async def get_dunning_candidates(
        self, legal_entity_id: UUID, min_overdue_days: int = 30
    ) -> list[ARInvoice]:
        """Invoice yang perlu dikirimi surat tagihan."""
        today = date.today()
        result = []
        for inv in self._storage.values():
            if inv.legal_entity_id == legal_entity_id and inv.status == ARInvoiceStatus.APPROVED:
                days_overdue = (today - inv.due_date).days
                if days_overdue >= min_overdue_days and inv.outstanding_amount > 0:
                    result.append(inv)
        return sorted(result, key=lambda x: (today - x.due_date).days, reverse=True)

    async def increment_dunning_level(self, invoice_id: UUID, user_id: UUID) -> int:
        invoice = await self.get_by_id(invoice_id)
        if not invoice:
            raise ValueError("Invoice not found")
        invoice.dunning_level += 1
        invoice.last_dunning_date = date.today()
        invoice.updated_by = user_id
        await self._update_collection_status(invoice)
        await self.update(invoice)
        await self._log_audit("DUNNING", invoice_id, user_id, {"level": invoice.dunning_level})
        return invoice.dunning_level

    async def get_customer_balance_history(
        self, customer_id: UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Monthly balance for customer."""
        result = []
        current_date = start_date
        while current_date <= end_date:
            month_end = date(current_date.year, current_date.month, 1) + timedelta(days=32)
            month_end = date(month_end.year, month_end.month, 1) - timedelta(days=1)
            balance = await self.get_outstanding_balance(customer_id, month_end)
            result.append({"period": month_end.strftime("%Y-%m"), "balance": str(balance)})
            if current_date.month == 12:
                current_date = date(current_date.year + 1, 1, 1)
            else:
                current_date = date(current_date.year, current_date.month + 1, 1)
        return result

    # ==================== CREDIT LIMIT ====================

    async def get_total_outstanding_for_customer(self, customer_id: UUID) -> Decimal:
        total = Decimal(0)
        for inv in self._storage.values():
            if inv.customer_id == customer_id and inv.status in (
                ARInvoiceStatus.APPROVED,
                ARInvoiceStatus.PARTIALLY_PAID,
            ):
                total += inv.outstanding_amount
        return total

    async def is_credit_limit_exceeded(
        self, customer_id: UUID, credit_limit: Decimal, additional_amount: Decimal = Decimal(0)
    ) -> bool:
        current = await self.get_total_outstanding_for_customer(customer_id)
        return (current + additional_amount) > credit_limit

    # ==================== IMPORT/EXPORT ====================

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        invoices = await self.find_by_date_range(
            date(1900, 1, 1), date(2100, 12, 31), legal_entity_id
        )
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "invoice_number",
                "customer_id",
                "invoice_date",
                "due_date",
                "total_amount",
                "paid_amount",
                "outstanding",
                "status",
                "collection_status",
                "currency",
            ]
        )
        for inv in invoices:
            writer.writerow(
                [
                    inv.invoice_number,
                    str(inv.customer_id),
                    inv.invoice_date.isoformat(),
                    inv.due_date.isoformat(),
                    str(inv.total_amount),
                    str(inv.paid_amount),
                    str(inv.outstanding_amount),
                    inv.status.value,
                    inv.collection_status.value,
                    inv.currency_code,
                ]
            )
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        import io

        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                inv = ARInvoice(
                    id=uuid4(),
                    invoice_number=row["invoice_number"],
                    customer_id=UUID(row["customer_id"]),
                    legal_entity_id=legal_entity_id,
                    sales_order_id=None,
                    invoice_date=date.fromisoformat(row["invoice_date"]),
                    due_date=date.fromisoformat(row["due_date"]),
                    total_amount=Decimal(row["total_amount"]),
                    tax_amount=Decimal(0),
                    discount_amount=Decimal(0),
                    paid_amount=Decimal(0),
                    outstanding_amount=Decimal(row["total_amount"]),
                    currency_code=row.get("currency", "IDR"),
                    status=ARInvoiceStatus(row.get("status", "draft")),
                    description=None,
                    created_by=user_id,
                    updated_by=user_id,
                )
                await self.add(inv)
                count += 1
            except Exception as e:
                logger.warning(f"Import failed: {e}")
        return count

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        invoices = [inv for inv in self._storage.values() if inv.legal_entity_id == legal_entity_id]
        total_invoices = len(invoices)
        total_amount = sum(inv.total_amount for inv in invoices)
        total_outstanding = sum(inv.outstanding_amount for inv in invoices)
        paid_count = sum(1 for inv in invoices if inv.status == ARInvoiceStatus.PAID)
        overdue_count = sum(
            1
            for inv in invoices
            if inv.status in (ARInvoiceStatus.APPROVED, ARInvoiceStatus.PARTIALLY_PAID)
            and inv.due_date < date.today()
        )
        written_off = sum(1 for inv in invoices if inv.status == ARInvoiceStatus.WRITTEN_OFF)
        return {
            "total_invoices": total_invoices,
            "total_amount": str(total_amount),
            "total_outstanding": str(total_outstanding),
            "paid_count": paid_count,
            "overdue_count": overdue_count,
            "written_off_count": written_off,
            "by_status": {
                s.value: sum(1 for inv in invoices if inv.status == s) for s in ARInvoiceStatus
            },
            "by_collection": {
                c.value: sum(1 for inv in invoices if inv.collection_status == c)
                for c in CollectionStatus
            },
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_invoices": len(self._storage),
            "total_credit_notes": len(self._credit_notes),
            "total_debit_notes": len(self._debit_notes),
            "audit_log_size": len(self._audit_log),
        }

    # ==================== ADDITIONAL METHODS FOR DI CONTRACT ====================

    async def save_invoice(self, invoice: ARInvoice) -> None:
        """Alias untuk add(), sesuai ekspektasi container."""
        await self.add(invoice)

    async def find_invoice_by_id(self, invoice_id: UUID) -> ARInvoice | None:
        """Alias untuk get_by_id()."""
        return await self.get_by_id(invoice_id)

    async def find_invoices_by_customer(self, customer_id: UUID) -> list[ARInvoice]:
        """
        Mencari semua invoice milik customer tertentu (tanpa filter legal_entity_id).
        Menggunakan indeks customer yang sudah ada.
        """
        ids = self._customer_index.get(customer_id, [])
        return [self._storage[iid] for iid in ids if iid in self._storage]


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS (FIXED)
# ============================================================================

# Untuk backward compatibility: aliases di-prefix underscore agar tidak ter-discard sebagai port.
# Jika digunakan di test, import secara eksplisit atau gunakan InMemoryARRepository langsung.
_ARRepository = InMemoryARRepository

# Alias untuk test compatibility
ArRepositoryPort = ARRepositoryPort

# Alias untuk kepatuhan terhadap nama yang diharapkan DI container
ARRepositoryPortImpl = InMemoryARRepository


__all__ = [
    "ARInvoice",
    "ARInvoiceStatus",
    "ARRepository",
    "ARRepositoryPort",
    "ArRepositoryPort",
    "ARRepositoryPortImpl",   
    "CollectionStatus",
    "CreditNoteAR",
    "DebitNoteAR",
    "InMemoryARRepository",
]