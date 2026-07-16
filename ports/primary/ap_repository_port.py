#!/usr/bin/env python3
"""
Module: ap_repository_port.py
Layer: Ports (Primary)
Responsibility: Port (interface) untuk Account Payable Invoice repository.
Implementasi in-memory disediakan sebagai InMemoryAPRepository.

Fitur: siklus hidup invoice (draft, submitted, approved, paid, cancelled, disputed),
aging buckets, payment scheduling, three-way matching, credit/debit notes,
vendor balance, due date tracking, audit trail, import/export CSV, dan statistik.
Audit: Setiap perubahan status invoice tercatat.

Perbaikan presisi:
    - Semua konversi float() pada nilai moneter diubah menjadi str() untuk menghindari
      kehilangan presisi dan memenuhi aturan MNY-003.
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


class APInvoiceStatus(Enum):
    """Status invoice AP."""

    DRAFT = "draft"  # Input awal, masih bisa diedit
    SUBMITTED = "submitted"  # Diajukan untuk approval
    APPROVED = "approved"  # Disetujui, menunggu pembayaran
    PARTIALLY_PAID = "partially_paid"  # Sebagian dibayar
    PAID = "paid"  # Lunas
    CANCELLED = "cancelled"  # Dibatalkan
    DISPUTED = "disputed"  # Dalam sengketa dengan vendor
    OVERDUE = "overdue"  # Jatuh tempo belum dibayar


class MatchingStatus(Enum):
    """Status three-way matching."""

    NOT_APPLICABLE = "not_applicable"
    MATCHED = "matched"
    PARTIAL_MATCH = "partial_match"
    MISMATCH = "mismatch"
    PENDING = "pending"


@dataclass
class APInvoice:
    """
    Aggregate Root AP Invoice.
    """

    id: UUID
    invoice_number: str  # Nomor invoice dari vendor
    vendor_id: UUID
    legal_entity_id: UUID
    purchase_order_id: UUID | None  # PO terkait (opsional)
    goods_receipt_id: UUID | None  # GRN terkait
    invoice_date: date
    due_date: date
    total_amount: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    currency_code: str = "IDR"
    exchange_rate: Decimal = Decimal(1)
    status: APInvoiceStatus = APInvoiceStatus.DRAFT
    matching_status: MatchingStatus = MatchingStatus.PENDING
    description: str | None = None
    payment_terms: str = "NET30"  # Misal: NET30, N20, EOM
    payment_schedule_date: date | None = None
    payment_run_id: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    cancelled_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    disputed_reason: str | None = None
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
            "vendor_id": str(self.vendor_id),
            "legal_entity_id": str(self.legal_entity_id),
            "purchase_order_id": str(self.purchase_order_id) if self.purchase_order_id else None,
            "goods_receipt_id": str(self.goods_receipt_id) if self.goods_receipt_id else None,
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
            "matching_status": self.matching_status.value,
            "description": self.description,
            "payment_terms": self.payment_terms,
            "payment_schedule_date": self.payment_schedule_date.isoformat()
            if self.payment_schedule_date
            else None,
            "payment_run_id": str(self.payment_run_id) if self.payment_run_id else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "cancelled_by": str(self.cancelled_by) if self.cancelled_by else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancellation_reason": self.cancellation_reason,
            "disputed_reason": self.disputed_reason,
            "attachment_urls": self.attachment_urls,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
        }


@dataclass
class CreditNoteAP:
    """Nota kredit dari vendor (pengurang hutang)."""

    id: UUID
    credit_note_number: str
    vendor_id: UUID
    legal_entity_id: UUID
    original_invoice_id: UUID
    credit_date: date
    amount: Decimal
    reason: str
    created_at: datetime
    created_by: UUID


# ============================================================================
# PORT INTERFACE (Abstract Base Class)
# ============================================================================

class APRepositoryPort(ABC):
    """
    Port (interface) untuk repository Account Payable.
    Semua metode wajib diimplementasikan oleh repository concrete.
    """

    @abstractmethod
    async def add(self, invoice: APInvoice) -> None:
        """Menambahkan invoice AP baru."""
        pass

    @abstractmethod
    async def get_by_id(self, invoice_id: UUID) -> APInvoice | None:
        """Mengambil invoice berdasarkan ID."""
        pass

    @abstractmethod
    async def get_by_invoice_number(self, invoice_number: str, vendor_id: UUID) -> APInvoice | None:
        """Mengambil invoice berdasarkan nomor invoice dan vendor."""
        pass

    @abstractmethod
    async def update(self, invoice: APInvoice) -> None:
        """Memperbarui invoice yang sudah ada."""
        pass

    @abstractmethod
    async def delete(self, invoice_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Soft delete atau permanent delete invoice."""
        pass

    # Workflow actions
    @abstractmethod
    async def submit_for_approval(self, invoice_id: UUID, user_id: UUID) -> bool:
        """Submit invoice untuk approval."""
        pass

    @abstractmethod
    async def approve(self, invoice_id: UUID, approver_id: UUID) -> bool:
        """Menyetujui invoice."""
        pass

    @abstractmethod
    async def mark_as_paid(
        self,
        invoice_id: UUID,
        payment_id: UUID,
        paid_amount: Decimal,
        paid_date: date,
        user_id: UUID,
    ) -> bool:
        """Menandai invoice sebagai sudah dibayar (sebagian atau penuh)."""
        pass

    @abstractmethod
    async def cancel(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        """Membatalkan invoice."""
        pass

    @abstractmethod
    async def dispute(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        """Menandai invoice sebagai disputed."""
        pass

    # Credit note
    @abstractmethod
    async def add_credit_note(self, credit_note: CreditNoteAP) -> None:
        """Menambahkan credit note dan mengupdate outstanding."""
        pass

    # Queries
    @abstractmethod
    async def find_by_vendor(
        self, vendor_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[APInvoice]:
        """Mencari invoice berdasarkan vendor."""
        pass

    @abstractmethod
    async def find_due_for_payment(
        self, as_of_date: date, legal_entity_id: UUID
    ) -> list[APInvoice]:
        """Mencari invoice yang jatuh tempo pada tanggal tertentu."""
        pass

    @abstractmethod
    async def get_outstanding_balance(self, vendor_id: UUID, as_of_date: date) -> Decimal:
        """Menghitung outstanding balance vendor per tanggal."""
        pass

    @abstractmethod
    async def find_by_payment_run(self, payment_run_id: UUID) -> list[APInvoice]:
        """Mencari invoice dalam payment run tertentu."""
        pass

    @abstractmethod
    async def find_by_status(
        self, status: APInvoiceStatus, legal_entity_id: UUID
    ) -> list[APInvoice]:
        """Mencari invoice berdasarkan status."""
        pass

    @abstractmethod
    async def find_by_date_range(
        self, start_date: date, end_date: date, legal_entity_id: UUID
    ) -> list[APInvoice]:
        """Mencari invoice berdasarkan rentang tanggal invoice."""
        pass

    @abstractmethod
    async def get_aging_buckets(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> dict[str, Decimal]:
        """Mendapatkan aging buckets."""
        pass

    @abstractmethod
    async def get_vendor_balance_history(
        self, vendor_id: UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Riwayat saldo vendor per bulan."""
        pass

    # Three-way matching
    @abstractmethod
    async def perform_three_way_match(
        self, invoice_id: UUID, po_total: Decimal, grn_total: Decimal
    ) -> MatchingStatus:
        """Melakukan three-way matching antara invoice, PO, dan GRN."""
        pass

    # Import/Export
    @abstractmethod
    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        """Ekspor invoice ke CSV."""
        pass

    @abstractmethod
    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        """Impor invoice dari CSV."""
        pass

    # Statistics & Audit
    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Statistik AP."""
        pass

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Audit log AP."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check repository."""
        pass


# ============================================================================
# IMPLEMENTASI KONKRET (In-Memory)
# ============================================================================

class InMemoryAPRepository(APRepositoryPort):
    """
    Implementasi in-memory repository untuk Account Payable.
    """

    def __init__(self):
        self._storage: dict[UUID, APInvoice] = {}
        self._vendor_index: dict[UUID, list[UUID]] = {}
        self._status_index: dict[APInvoiceStatus, list[UUID]] = {}
        self._po_index: dict[UUID, list[UUID]] = {}  # purchase_order_id -> invoice ids
        self._payment_run_index: dict[UUID, list[UUID]] = {}
        self._credit_notes: dict[UUID, CreditNoteAP] = {}
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
        logger.info(f"AP AUDIT: {action} on invoice {invoice_id} by {user_id}")

    async def _recompute_outstanding(self, invoice: APInvoice):
        """Hitung outstanding = total - paid - credit_notes."""
        total_credit = Decimal(0)
        for cn in self._credit_notes.values():
            if cn.original_invoice_id == invoice.id:
                total_credit += cn.amount
        invoice.outstanding_amount = invoice.total_amount - invoice.paid_amount - total_credit
        if invoice.outstanding_amount < 0:
            invoice.outstanding_amount = Decimal(0)
        # Update status berdasarkan outstanding
        if invoice.outstanding_amount == 0 and invoice.status not in (
            APInvoiceStatus.CANCELLED,
            APInvoiceStatus.DISPUTED,
        ):
            invoice.status = APInvoiceStatus.PAID
        elif invoice.outstanding_amount < invoice.total_amount and invoice.outstanding_amount > 0:
            invoice.status = APInvoiceStatus.PARTIALLY_PAID

    async def _update_indices(self, invoice: APInvoice, is_insert: bool = True):
        if is_insert:
            # Vendor index
            if invoice.vendor_id not in self._vendor_index:
                self._vendor_index[invoice.vendor_id] = []
            if invoice.id not in self._vendor_index[invoice.vendor_id]:
                self._vendor_index[invoice.vendor_id].append(invoice.id)
            # Status index
            if invoice.status not in self._status_index:
                self._status_index[invoice.status] = []
            if invoice.id not in self._status_index[invoice.status]:
                self._status_index[invoice.status].append(invoice.id)
            # PO index
            if invoice.purchase_order_id:
                if invoice.purchase_order_id not in self._po_index:
                    self._po_index[invoice.purchase_order_id] = []
                if invoice.id not in self._po_index[invoice.purchase_order_id]:
                    self._po_index[invoice.purchase_order_id].append(invoice.id)
            # Payment run index
            if invoice.payment_run_id:
                if invoice.payment_run_id not in self._payment_run_index:
                    self._payment_run_index[invoice.payment_run_id] = []
                if invoice.id not in self._payment_run_index[invoice.payment_run_id]:
                    self._payment_run_index[invoice.payment_run_id].append(invoice.id)
        else:
            # For update, we need to handle status change - will be done in update method
            pass

    # ==================== CRUD ====================

    async def add(self, invoice: APInvoice) -> None:
        if invoice.id in self._storage:
            raise ValueError(f"Invoice {invoice.id} already exists")
        # Validate due date >= invoice date
        if invoice.due_date < invoice.invoice_date:
            raise ValueError("Due date cannot be before invoice date")
        invoice.outstanding_amount = invoice.total_amount - invoice.paid_amount
        invoice.created_at = datetime.now(UTC)
        invoice.updated_at = invoice.created_at
        invoice.version = 1
        async with self._lock:
            self._storage[invoice.id] = invoice
            await self._update_indices(invoice, is_insert=True)
        await self._log_audit(
            "ADD",
            invoice.id,
            invoice.created_by,
            {
                "invoice_number": invoice.invoice_number,
                "vendor_id": str(invoice.vendor_id),
                "amount": str(invoice.total_amount),
            },
        )

    async def get_by_id(self, invoice_id: UUID) -> APInvoice | None:
        return self._storage.get(invoice_id)

    async def get_by_invoice_number(self, invoice_number: str, vendor_id: UUID) -> APInvoice | None:
        for inv in self._storage.values():
            if inv.invoice_number == invoice_number and inv.vendor_id == vendor_id:
                return inv
        return None

    async def update(self, invoice: APInvoice) -> None:
        if invoice.id not in self._storage:
            raise ValueError(f"Invoice {invoice.id} not found")
        old = self._storage[invoice.id]
        # Only draft invoices can be updated directly
        if old.status != APInvoiceStatus.DRAFT and invoice.status == old.status:
            raise ValueError(
                f"Cannot update invoice with status {old.status.value}. Only DRAFT allowed."
            )
        # Update indices if vendor changed
        if old.vendor_id != invoice.vendor_id:
            # Remove from old vendor index
            if old.vendor_id in self._vendor_index and old.id in self._vendor_index[old.vendor_id]:
                self._vendor_index[old.vendor_id].remove(old.id)
            # Add to new
            if invoice.vendor_id not in self._vendor_index:
                self._vendor_index[invoice.vendor_id] = []
            if invoice.id not in self._vendor_index[invoice.vendor_id]:
                self._vendor_index[invoice.vendor_id].append(invoice.id)
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
        # Preserve timestamps
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
        if invoice.status not in (APInvoiceStatus.DRAFT, APInvoiceStatus.CANCELLED):
            raise ValueError(f"Cannot delete invoice with status {invoice.status.value}")
        if permanent:
            # Remove from all indices
            if (
                invoice.vendor_id in self._vendor_index
                and invoice.id in self._vendor_index[invoice.vendor_id]
            ):
                self._vendor_index[invoice.vendor_id].remove(invoice.id)
            if (
                invoice.status in self._status_index
                and invoice.id in self._status_index[invoice.status]
            ):
                self._status_index[invoice.status].remove(invoice.id)
            if invoice.purchase_order_id and invoice.purchase_order_id in self._po_index:
                if invoice.id in self._po_index[invoice.purchase_order_id]:
                    self._po_index[invoice.purchase_order_id].remove(invoice.id)
            del self._storage[invoice_id]
            await self._log_audit("DELETE_PERMANENT", invoice_id, user_id, {})
        else:
            # Soft delete: set status cancelled
            invoice.status = APInvoiceStatus.CANCELLED
            invoice.cancelled_at = datetime.now(UTC)
            invoice.cancelled_by = user_id
            invoice.updated_at = invoice.cancelled_at
            invoice.version += 1
            await self.update(invoice)
        return True

    # ==================== WORKFLOW ACTIONS ====================

    async def submit_for_approval(self, invoice_id: UUID, user_id: UUID) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status != APInvoiceStatus.DRAFT:
            return False
        invoice.status = APInvoiceStatus.SUBMITTED
        invoice.updated_by = user_id
        await self.update(invoice)
        await self._log_audit("SUBMIT", invoice_id, user_id, {})
        return True

    async def approve(self, invoice_id: UUID, approver_id: UUID) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status != APInvoiceStatus.SUBMITTED:
            return False
        invoice.status = APInvoiceStatus.APPROVED
        invoice.approved_by = approver_id
        invoice.approved_at = datetime.now(UTC)
        invoice.updated_by = approver_id
        await self.update(invoice)
        await self._log_audit("APPROVE", invoice_id, approver_id, {})
        return True

    async def mark_as_paid(
        self,
        invoice_id: UUID,
        payment_id: UUID,
        paid_amount: Decimal,
        paid_date: date,
        user_id: UUID,
    ) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice:
            return False
        if invoice.status not in (APInvoiceStatus.APPROVED, APInvoiceStatus.PARTIALLY_PAID):
            return False
        invoice.paid_amount += paid_amount
        invoice.payment_run_id = payment_id
        invoice.updated_by = user_id
        await self._recompute_outstanding(invoice)
        await self.update(invoice)
        await self._log_audit(
            "MARK_PAID",
            invoice_id,
            user_id,
            {
                "amount": str(paid_amount),
                "payment_id": str(payment_id),
            },
        )
        return True

    async def cancel(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status == APInvoiceStatus.PAID:
            return False
        invoice.status = APInvoiceStatus.CANCELLED
        invoice.cancellation_reason = reason
        invoice.cancelled_by = user_id
        invoice.cancelled_at = datetime.now(UTC)
        invoice.updated_by = user_id
        await self.update(invoice)
        await self._log_audit("CANCEL", invoice_id, user_id, {"reason": reason})
        return True

    async def dispute(self, invoice_id: UUID, reason: str, user_id: UUID) -> bool:
        invoice = await self.get_by_id(invoice_id)
        if not invoice or invoice.status == APInvoiceStatus.PAID:
            return False
        invoice.status = APInvoiceStatus.DISPUTED
        invoice.disputed_reason = reason
        invoice.updated_by = user_id
        await self.update(invoice)
        await self._log_audit("DISPUTE", invoice_id, user_id, {"reason": reason})
        return True

    # ==================== CREDIT NOTE ====================

    async def add_credit_note(self, credit_note: CreditNoteAP) -> None:
        self._credit_notes[credit_note.id] = credit_note
        # Update outstanding invoice
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

    # ==================== QUERY ====================

    async def find_by_vendor(
        self, vendor_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[APInvoice]:
        ids = self._vendor_index.get(vendor_id, [])
        invoices = [self._storage[iid] for iid in ids if iid in self._storage]
        invoices.sort(key=lambda x: x.due_date)
        return invoices[offset : offset + limit]

    async def find_due_for_payment(
        self, as_of_date: date, legal_entity_id: UUID
    ) -> list[APInvoice]:
        result = []
        for inv in self._storage.values():
            if inv.legal_entity_id == legal_entity_id and inv.status == APInvoiceStatus.APPROVED:
                if inv.due_date <= as_of_date:
                    result.append(inv)
        return sorted(result, key=lambda x: x.due_date)

    async def get_outstanding_balance(self, vendor_id: UUID, as_of_date: date) -> Decimal:
        total = Decimal(0)
        for inv in self._storage.values():
            if inv.vendor_id == vendor_id and inv.due_date <= as_of_date:
                if inv.status in (APInvoiceStatus.APPROVED, APInvoiceStatus.PARTIALLY_PAID):
                    total += inv.outstanding_amount
        return total

    async def find_by_payment_run(self, payment_run_id: UUID) -> list[APInvoice]:
        ids = self._payment_run_index.get(payment_run_id, [])
        return [self._storage[iid] for iid in ids if iid in self._storage]

    async def find_by_status(
        self, status: APInvoiceStatus, legal_entity_id: UUID
    ) -> list[APInvoice]:
        ids = self._status_index.get(status, [])
        return [
            self._storage[iid]
            for iid in ids
            if iid in self._storage and self._storage[iid].legal_entity_id == legal_entity_id
        ]

    async def find_by_date_range(
        self, start_date: date, end_date: date, legal_entity_id: UUID
    ) -> list[APInvoice]:
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
        """Aging buckets: current, 1-30, 31-60, 61-90, 90+ days overdue."""
        buckets = {
            "current": Decimal(0),
            "1_30": Decimal(0),
            "31_60": Decimal(0),
            "61_90": Decimal(0),
            "90_plus": Decimal(0),
        }
        for inv in self._storage.values():
            if inv.legal_entity_id == legal_entity_id and inv.status in (
                APInvoiceStatus.APPROVED,
                APInvoiceStatus.PARTIALLY_PAID,
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

    async def get_vendor_balance_history(
        self, vendor_id: UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Monthly balance for vendor."""
        result = []
        current_date = start_date
        while current_date <= end_date:
            month_end = date(current_date.year, current_date.month, 1) + timedelta(days=32)
            month_end = date(month_end.year, month_end.month, 1) - timedelta(days=1)
            balance = await self.get_outstanding_balance(vendor_id, month_end)
            result.append({"period": month_end.strftime("%Y-%m"), "balance": str(balance)})
            current_date = (
                date(current_date.year, current_date.month + 1, 1)
                if current_date.month < 12
                else date(current_date.year + 1, 1, 1)
            )
        return result

    # ==================== THREE-WAY MATCHING ====================

    async def perform_three_way_match(
        self, invoice_id: UUID, po_total: Decimal, grn_total: Decimal
    ) -> MatchingStatus:
        invoice = await self.get_by_id(invoice_id)
        if not invoice:
            raise ValueError("Invoice not found")
        if invoice.purchase_order_id is None or invoice.goods_receipt_id is None:
            invoice.matching_status = MatchingStatus.NOT_APPLICABLE
            return invoice.matching_status
        if (
            invoice.total_amount == po_total == grn_total
            or (invoice.total_amount <= po_total and invoice.total_amount <= grn_total)
            or (
                abs(invoice.total_amount - po_total) < Decimal(0.01)
                and abs(invoice.total_amount - grn_total) < Decimal(0.01)
            )
        ):
            invoice.matching_status = MatchingStatus.MATCHED
        elif invoice.total_amount > po_total or invoice.total_amount > grn_total:
            invoice.matching_status = MatchingStatus.MISMATCH
        else:
            invoice.matching_status = MatchingStatus.PARTIAL_MATCH
        await self.update(invoice)
        return invoice.matching_status

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
                "vendor_id",
                "invoice_date",
                "due_date",
                "total_amount",
                "paid_amount",
                "outstanding",
                "status",
                "currency",
            ]
        )
        for inv in invoices:
            writer.writerow(
                [
                    inv.invoice_number,
                    str(inv.vendor_id),
                    inv.invoice_date.isoformat(),
                    inv.due_date.isoformat(),
                    str(inv.total_amount),
                    str(inv.paid_amount),
                    str(inv.outstanding_amount),
                    inv.status.value,
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
                inv = APInvoice(
                    id=uuid4(),
                    invoice_number=row["invoice_number"],
                    vendor_id=UUID(row["vendor_id"]),
                    legal_entity_id=legal_entity_id,
                    purchase_order_id=None,
                    goods_receipt_id=None,
                    invoice_date=date.fromisoformat(row["invoice_date"]),
                    due_date=date.fromisoformat(row["due_date"]),
                    total_amount=Decimal(row["total_amount"]),
                    tax_amount=Decimal(0),
                    discount_amount=Decimal(0),
                    paid_amount=Decimal(0),
                    outstanding_amount=Decimal(row["total_amount"]),
                    currency_code=row.get("currency", "IDR"),
                    status=APInvoiceStatus(row.get("status", "draft")),
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
        paid_count = sum(1 for inv in invoices if inv.status == APInvoiceStatus.PAID)
        overdue_count = sum(
            1
            for inv in invoices
            if inv.status == APInvoiceStatus.APPROVED and inv.due_date < date.today()
        )
        return {
            "total_invoices": total_invoices,
            "total_amount": str(total_amount),
            "total_outstanding": str(total_outstanding),
            "paid_count": paid_count,
            "overdue_count": overdue_count,
            "by_status": {
                s.value: sum(1 for inv in invoices if inv.status == s) for s in APInvoiceStatus
            },
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_invoices": len(self._storage),
            "total_credit_notes": len(self._credit_notes),
            "audit_log_size": len(self._audit_log),
        }

    # ==================== ADDITIONAL METHODS FOR DI CONTRACT ====================

    async def save_invoice(self, invoice: APInvoice) -> None:
        """Alias untuk add(), sesuai ekspektasi container."""
        await self.add(invoice)

    async def find_invoice_by_id(self, invoice_id: UUID) -> APInvoice | None:
        """Alias untuk get_by_id()."""
        return await self.get_by_id(invoice_id)

    async def find_invoices_by_vendor(self, vendor_id: UUID) -> list[APInvoice]:
        """
        Mencari semua invoice milik vendor tertentu (tanpa parameter limit/offset).
        Menggunakan indeks vendor yang sudah ada.
        """
        ids = self._vendor_index.get(vendor_id, [])
        return [self._storage[iid] for iid in ids if iid in self._storage]


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS (FIXED)
# ============================================================================

# Untuk backward compatibility: aliases di-prefix underscore agar tidak ter-discard sebagai port.
# Jika digunakan di test, import secara eksplisit atau gunakan InMemoryAPRepository langsung.
_APRepository = InMemoryAPRepository

# Alias untuk test compatibility
ApRepositoryPort = APRepositoryPort

# Alias untuk kepatuhan terhadap nama yang diharapkan DI container
APRepositoryPortImpl = InMemoryAPRepository


__all__ = [
    "APInvoice",
    "APInvoiceStatus",
    "APRepository",
    "APRepositoryPort",
    "ApRepositoryPort",
    "APRepositoryPortImpl",   
    "CreditNoteAP",
    "InMemoryAPRepository",
    "MatchingStatus",
]