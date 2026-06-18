#!/usr/bin/env python3
"""
Module: invariants.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Business invariants for Purchase & Sales domain.

Defines all invariants that must be satisfied by the Purchase & Sales aggregates.
Ensures data consistency for purchase orders, sales orders, invoices, returns,
goods receipts, and delivery notes.

Dependencies:
- Python standard library (logging, decimal, datetime)
- domain.purchase_sales.purchase_order_entity (PurchaseOrderEntity, POStatus)
- domain.purchase_sales.sales_order_entity (SalesOrderEntity, SOStatus)
- domain.purchase_sales.purchase_invoice_entity (PurchaseInvoiceEntity, PurchaseInvoiceStatus)
- domain.purchase_sales.sales_invoice_entity (SalesInvoiceEntity, SalesInvoiceStatus)
- domain.purchase_sales.goods_receipt_note_entity (GoodsReceiptNoteEntity, GRNStatus)
- domain.purchase_sales.sales_delivery_note_entity (SalesDeliveryNoteEntity, DeliveryStatus)

Audit: Every invariant violation is logged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

from domain.purchase_sales.goods_receipt_note_entity import GoodsReceiptNoteEntity, GRNStatus
from domain.purchase_sales.purchase_invoice_entity import (
    PurchaseInvoiceStatus,
)
from domain.purchase_sales.purchase_order_entity import POStatus, PurchaseOrderEntity
from domain.purchase_sales.sales_delivery_note_entity import DeliveryStatus, SalesDeliveryNoteEntity
from domain.purchase_sales.sales_invoice_entity import SalesInvoiceStatus
from domain.purchase_sales.sales_order_entity import SalesOrderEntity, SOStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Invariant Validation Result
# ============================================================================


class InvariantResult:
    """Result of invariant validation."""

    def __init__(self, is_valid: bool = True, errors: list[str] = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False
        logger.warning(f"Invariant violation: {error}")

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"is_valid": self.is_valid, "errors": self.errors, "error_count": len(self.errors)}

    def __bool__(self) -> bool:
        return self.is_valid


# ============================================================================
# Purchase Order Invariants
# ============================================================================


class PurchaseOrderInvariants:
    """Collection of static invariant validation methods for Purchase Orders."""

    @staticmethod
    def validate_po_number_unique(po_number: str, existing_numbers: set[str]) -> InvariantResult:
        result = InvariantResult(True)
        if po_number in existing_numbers:
            result.add_error(f"PO number '{po_number}' already exists")
        return result

    @staticmethod
    def validate_po_quantity(po: PurchaseOrderEntity) -> InvariantResult:
        result = InvariantResult(True)
        for item in po.items:
            if item.quantity <= 0:
                result.add_error(
                    f"Item {item.item_code} quantity must be positive: {item.quantity}"
                )
        return result

    @staticmethod
    def validate_receipt_quantity(
        po: PurchaseOrderEntity, item_id: UUID, received_qty: Decimal
    ) -> InvariantResult:
        result = InvariantResult(True)
        item = po.get_item(item_id)
        if item:
            if received_qty <= 0:
                result.add_error(f"Receipt quantity must be positive: {received_qty}")
            elif received_qty > item.remaining_quantity:
                result.add_error(
                    f"Receipt quantity {received_qty} exceeds remaining PO quantity {item.remaining_quantity}"
                )
        else:
            result.add_error(f"Item {item_id} not found in PO")
        return result

    @staticmethod
    def validate_po_status_transition(current: POStatus, new: POStatus) -> InvariantResult:
        valid = {
            POStatus.DRAFT: [POStatus.SUBMITTED, POStatus.CANCELLED],
            POStatus.SUBMITTED: [POStatus.APPROVED, POStatus.CANCELLED],
            POStatus.APPROVED: [
                POStatus.PARTIALLY_RECEIVED,
                POStatus.FULLY_RECEIVED,
                POStatus.CANCELLED,
            ],
            POStatus.PARTIALLY_RECEIVED: [POStatus.FULLY_RECEIVED, POStatus.CANCELLED],
            POStatus.FULLY_RECEIVED: [POStatus.CLOSED],
            POStatus.CLOSED: [],
            POStatus.CANCELLED: [],
        }
        result = InvariantResult(True)
        if new not in valid.get(current, []):
            result.add_error(f"Invalid PO status transition from {current.value} to {new.value}")
        return result


# ============================================================================
# Sales Order Invariants
# ============================================================================


class SalesOrderInvariants:
    """Collection of static invariant validation methods for Sales Orders."""

    @staticmethod
    def validate_so_number_unique(so_number: str, existing_numbers: set[str]) -> InvariantResult:
        result = InvariantResult(True)
        if so_number in existing_numbers:
            result.add_error(f"SO number '{so_number}' already exists")
        return result

    @staticmethod
    def validate_so_quantity(so: SalesOrderEntity) -> InvariantResult:
        result = InvariantResult(True)
        for item in so.items:
            if item.quantity <= 0:
                result.add_error(
                    f"Item {item.item_code} quantity must be positive: {item.quantity}"
                )
        return result

    @staticmethod
    def validate_delivery_quantity(
        so: SalesOrderEntity, item_id: UUID, delivered_qty: Decimal
    ) -> InvariantResult:
        result = InvariantResult(True)
        item = so.get_item(item_id)
        if item:
            if delivered_qty <= 0:
                result.add_error(f"Delivery quantity must be positive: {delivered_qty}")
            elif delivered_qty > item.remaining_quantity:
                result.add_error(
                    f"Delivery quantity {delivered_qty} exceeds remaining SO quantity {item.remaining_quantity}"
                )
        else:
            result.add_error(f"Item {item_id} not found in SO")
        return result

    @staticmethod
    def validate_so_status_transition(current: SOStatus, new: SOStatus) -> InvariantResult:
        valid = {
            SOStatus.DRAFT: [SOStatus.APPROVED, SOStatus.CANCELLED],
            SOStatus.APPROVED: [
                SOStatus.PARTIALLY_DELIVERED,
                SOStatus.FULLY_DELIVERED,
                SOStatus.CANCELLED,
            ],
            SOStatus.PARTIALLY_DELIVERED: [SOStatus.FULLY_DELIVERED, SOStatus.CANCELLED],
            SOStatus.FULLY_DELIVERED: [SOStatus.INVOICED],
            SOStatus.INVOICED: [SOStatus.CLOSED],
            SOStatus.CLOSED: [],
            SOStatus.CANCELLED: [],
        }
        result = InvariantResult(True)
        if new not in valid.get(current, []):
            result.add_error(f"Invalid SO status transition from {current.value} to {new.value}")
        return result


# ============================================================================
# Invoice Invariants (Purchase & Sales)
# ============================================================================


class InvoiceInvariants:
    """Collection of static invariant validation methods for invoices."""

    @staticmethod
    def validate_invoice_number_unique(
        invoice_number: str, existing_numbers: set[str]
    ) -> InvariantResult:
        result = InvariantResult(True)
        if invoice_number in existing_numbers:
            result.add_error(f"Invoice number '{invoice_number}' already exists")
        return result

    @staticmethod
    def validate_invoice_amount(total_amount: Decimal, items_total: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if abs(total_amount - items_total) > Decimal("0.01"):
            result.add_error(
                f"Invoice total {total_amount} does not match items total {items_total}"
            )
        return result

    @staticmethod
    def validate_payment_amount(paid_amount: Decimal, total_amount: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if paid_amount < 0:
            result.add_error(f"Paid amount cannot be negative: {paid_amount}")
        if paid_amount > total_amount:
            result.add_error(f"Paid amount {paid_amount} exceeds total amount {total_amount}")
        return result

    @staticmethod
    def validate_purchase_invoice_status_transition(
        current: PurchaseInvoiceStatus, new: PurchaseInvoiceStatus
    ) -> InvariantResult:
        valid = {
            PurchaseInvoiceStatus.DRAFT: [
                PurchaseInvoiceStatus.RECEIVED,
                PurchaseInvoiceStatus.CANCELLED,
            ],
            PurchaseInvoiceStatus.RECEIVED: [
                PurchaseInvoiceStatus.VERIFIED,
                PurchaseInvoiceStatus.DISPUTED,
                PurchaseInvoiceStatus.CANCELLED,
            ],
            PurchaseInvoiceStatus.VERIFIED: [
                PurchaseInvoiceStatus.APPROVED,
                PurchaseInvoiceStatus.CANCELLED,
            ],
            PurchaseInvoiceStatus.APPROVED: [
                PurchaseInvoiceStatus.PAID,
                PurchaseInvoiceStatus.CANCELLED,
            ],
            PurchaseInvoiceStatus.PAID: [],
            PurchaseInvoiceStatus.CANCELLED: [],
            PurchaseInvoiceStatus.DISPUTED: [
                PurchaseInvoiceStatus.VERIFIED,
                PurchaseInvoiceStatus.CANCELLED,
            ],
        }
        result = InvariantResult(True)
        if new not in valid.get(current, []):
            result.add_error(
                f"Invalid purchase invoice status transition from {current.value} to {new.value}"
            )
        return result

    @staticmethod
    def validate_sales_invoice_status_transition(
        current: SalesInvoiceStatus, new: SalesInvoiceStatus
    ) -> InvariantResult:
        valid = {
            SalesInvoiceStatus.DRAFT: [SalesInvoiceStatus.ISSUED, SalesInvoiceStatus.CANCELLED],
            SalesInvoiceStatus.ISSUED: [SalesInvoiceStatus.SENT, SalesInvoiceStatus.CANCELLED],
            SalesInvoiceStatus.SENT: [
                SalesInvoiceStatus.PARTIALLY_PAID,
                SalesInvoiceStatus.FULLY_PAID,
                SalesInvoiceStatus.OVERDUE,
                SalesInvoiceStatus.CANCELLED,
            ],
            SalesInvoiceStatus.PARTIALLY_PAID: [
                SalesInvoiceStatus.FULLY_PAID,
                SalesInvoiceStatus.OVERDUE,
                SalesInvoiceStatus.CANCELLED,
            ],
            SalesInvoiceStatus.FULLY_PAID: [],
            SalesInvoiceStatus.OVERDUE: [
                SalesInvoiceStatus.PARTIALLY_PAID,
                SalesInvoiceStatus.FULLY_PAID,
                SalesInvoiceStatus.CANCELLED,
            ],
            SalesInvoiceStatus.CANCELLED: [],
        }
        result = InvariantResult(True)
        if new not in valid.get(current, []):
            result.add_error(
                f"Invalid sales invoice status transition from {current.value} to {new.value}"
            )
        return result


# ============================================================================
# Goods Receipt Invariants
# ============================================================================


class GoodsReceiptInvariants:
    """Collection of static invariant validation methods for Goods Receipt Notes."""

    @staticmethod
    def validate_grn_quantity(
        grn: GoodsReceiptNoteEntity, po: PurchaseOrderEntity
    ) -> InvariantResult:
        result = InvariantResult(True)
        for grn_item in grn.items:
            po_item = po.get_item(grn_item.item_id)
            if not po_item:
                result.add_error(f"Item {grn_item.item_id} not found in PO {po.po_number}")
            else:
                # Get total already received from previous GRNs (not just this one)
                # This is aggregate-level check; here we only check single GRN item
                # against PO quantity, but should be done in enforcer with aggregate state.
                if grn_item.quantity > po_item.quantity:
                    result.add_error(
                        f"GRN quantity {grn_item.quantity} exceeds PO quantity {po_item.quantity}"
                    )
        return result

    @staticmethod
    def validate_grn_status_transition(current: GRNStatus, new: GRNStatus) -> InvariantResult:
        valid = {
            GRNStatus.DRAFT: [GRNStatus.CONFIRMED, GRNStatus.CANCELLED],
            GRNStatus.CONFIRMED: [],
            GRNStatus.CANCELLED: [],
        }
        result = InvariantResult(True)
        if new not in valid.get(current, []):
            result.add_error(f"Invalid GRN status transition from {current.value} to {new.value}")
        return result


# ============================================================================
# Delivery Note Invariants
# ============================================================================


class DeliveryNoteInvariants:
    """Collection of static invariant validation methods for Delivery Notes."""

    @staticmethod
    def validate_delivery_quantity(
        delivery: SalesDeliveryNoteEntity, so: SalesOrderEntity
    ) -> InvariantResult:
        result = InvariantResult(True)
        for delivery_item in delivery.items:
            so_item = so.get_item(delivery_item.item_id)
            if not so_item:
                result.add_error(f"Item {delivery_item.item_id} not found in SO {so.so_number}")
            else:
                if delivery_item.quantity > so_item.quantity:
                    result.add_error(
                        f"Delivery quantity {delivery_item.quantity} exceeds SO quantity {so_item.quantity}"
                    )
        return result

    @staticmethod
    def validate_delivery_status_transition(
        current: DeliveryStatus, new: DeliveryStatus
    ) -> InvariantResult:
        valid = {
            DeliveryStatus.DRAFT: [DeliveryStatus.CONFIRMED, DeliveryStatus.CANCELLED],
            DeliveryStatus.CONFIRMED: [DeliveryStatus.SHIPPED, DeliveryStatus.CANCELLED],
            DeliveryStatus.SHIPPED: [DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED],
            DeliveryStatus.DELIVERED: [],
            DeliveryStatus.CANCELLED: [],
        }
        result = InvariantResult(True)
        if new not in valid.get(current, []):
            result.add_error(
                f"Invalid delivery status transition from {current.value} to {new.value}"
            )
        return result


# ============================================================================
# Purchase & Sales Invariant Enforcer (Async)
# ============================================================================


class PurchaseSalesInvariantEnforcer:
    """
    Enforcer for all Purchase & Sales invariants with async dependencies.

    This class coordinates invariant checks that may require external lookups
    (e.g., checking number uniqueness across the aggregate).
    """

    def __init__(
        self,
        po_number_checker: Callable[[], set[str]] | None = None,
        so_number_checker: Callable[[], set[str]] | None = None,
        purchase_invoice_number_checker: Callable[[], set[str]] | None = None,
        sales_invoice_number_checker: Callable[[], set[str]] | None = None,
        grn_number_checker: Callable[[], set[str]] | None = None,
        delivery_number_checker: Callable[[], set[str]] | None = None,
    ):
        self._po_number_checker = po_number_checker
        self._so_number_checker = so_number_checker
        self._purchase_invoice_number_checker = purchase_invoice_number_checker
        self._sales_invoice_number_checker = sales_invoice_number_checker
        self._grn_number_checker = grn_number_checker
        self._delivery_number_checker = delivery_number_checker

        self._po_invariants = PurchaseOrderInvariants()
        self._so_invariants = SalesOrderInvariants()
        self._invoice_invariants = InvoiceInvariants()
        self._grn_invariants = GoodsReceiptInvariants()
        self._delivery_invariants = DeliveryNoteInvariants()

    # ------------------------------------------------------------------------
    # PO enforcement
    # ------------------------------------------------------------------------

    async def enforce_po_create(self, po_number: str) -> InvariantResult:
        existing = await self._po_number_checker() if self._po_number_checker else set()
        return self._po_invariants.validate_po_number_unique(po_number, existing)

    async def enforce_po_quantity(self, po: PurchaseOrderEntity) -> InvariantResult:
        return self._po_invariants.validate_po_quantity(po)

    async def enforce_po_receipt(
        self, po: PurchaseOrderEntity, item_id: UUID, received_qty: Decimal
    ) -> InvariantResult:
        return self._po_invariants.validate_receipt_quantity(po, item_id, received_qty)

    async def enforce_po_status_transition(
        self, current: POStatus, new: POStatus
    ) -> InvariantResult:
        return self._po_invariants.validate_po_status_transition(current, new)

    # ------------------------------------------------------------------------
    # SO enforcement
    # ------------------------------------------------------------------------

    async def enforce_so_create(self, so_number: str) -> InvariantResult:
        existing = await self._so_number_checker() if self._so_number_checker else set()
        return self._so_invariants.validate_so_number_unique(so_number, existing)

    async def enforce_so_quantity(self, so: SalesOrderEntity) -> InvariantResult:
        return self._so_invariants.validate_so_quantity(so)

    async def enforce_so_delivery(
        self, so: SalesOrderEntity, item_id: UUID, delivered_qty: Decimal
    ) -> InvariantResult:
        return self._so_invariants.validate_delivery_quantity(so, item_id, delivered_qty)

    async def enforce_so_status_transition(
        self, current: SOStatus, new: SOStatus
    ) -> InvariantResult:
        return self._so_invariants.validate_so_status_transition(current, new)

    # ------------------------------------------------------------------------
    # Invoice enforcement
    # ------------------------------------------------------------------------

    async def enforce_purchase_invoice_create(self, invoice_number: str) -> InvariantResult:
        existing = (
            await self._purchase_invoice_number_checker()
            if self._purchase_invoice_number_checker
            else set()
        )
        return self._invoice_invariants.validate_invoice_number_unique(invoice_number, existing)

    async def enforce_sales_invoice_create(self, invoice_number: str) -> InvariantResult:
        existing = (
            await self._sales_invoice_number_checker()
            if self._sales_invoice_number_checker
            else set()
        )
        return self._invoice_invariants.validate_invoice_number_unique(invoice_number, existing)

    async def enforce_invoice_amount(
        self, total_amount: Decimal, items_total: Decimal
    ) -> InvariantResult:
        return self._invoice_invariants.validate_invoice_amount(total_amount, items_total)

    async def enforce_payment_amount(
        self, paid_amount: Decimal, total_amount: Decimal
    ) -> InvariantResult:
        return self._invoice_invariants.validate_payment_amount(paid_amount, total_amount)

    async def enforce_purchase_invoice_status_transition(
        self, current: PurchaseInvoiceStatus, new: PurchaseInvoiceStatus
    ) -> InvariantResult:
        return self._invoice_invariants.validate_purchase_invoice_status_transition(current, new)

    async def enforce_sales_invoice_status_transition(
        self, current: SalesInvoiceStatus, new: SalesInvoiceStatus
    ) -> InvariantResult:
        return self._invoice_invariants.validate_sales_invoice_status_transition(current, new)

    # ------------------------------------------------------------------------
    # GRN enforcement
    # ------------------------------------------------------------------------

    async def enforce_grn_create(self, grn_number: str) -> InvariantResult:
        existing = await self._grn_number_checker() if self._grn_number_checker else set()
        # For simplicity, reuse the same unique check pattern
        result = InvariantResult(True)
        if grn_number in existing:
            result.add_error(f"GRN number '{grn_number}' already exists")
        return result

    async def enforce_grn_quantity(
        self, grn: GoodsReceiptNoteEntity, po: PurchaseOrderEntity
    ) -> InvariantResult:
        return self._grn_invariants.validate_grn_quantity(grn, po)

    async def enforce_grn_status_transition(
        self, current: GRNStatus, new: GRNStatus
    ) -> InvariantResult:
        return self._grn_invariants.validate_grn_status_transition(current, new)

    # ------------------------------------------------------------------------
    # Delivery enforcement
    # ------------------------------------------------------------------------

    async def enforce_delivery_create(self, delivery_number: str) -> InvariantResult:
        existing = await self._delivery_number_checker() if self._delivery_number_checker else set()
        result = InvariantResult(True)
        if delivery_number in existing:
            result.add_error(f"Delivery number '{delivery_number}' already exists")
        return result

    async def enforce_delivery_quantity(
        self, delivery: SalesDeliveryNoteEntity, so: SalesOrderEntity
    ) -> InvariantResult:
        return self._delivery_invariants.validate_delivery_quantity(delivery, so)

    async def enforce_delivery_status_transition(
        self, current: DeliveryStatus, new: DeliveryStatus
    ) -> InvariantResult:
        return self._delivery_invariants.validate_delivery_status_transition(current, new)


# ============================================================================
# Compatibility Class for Service Layer
# ============================================================================


class PurchaseSalesInvariantsValidator:
    """Simple synchronous validator for compatibility with service layer."""

    def __init__(self):
        self.po_invariants = PurchaseOrderInvariants()
        self.so_invariants = SalesOrderInvariants()
        self.invoice_invariants = InvoiceInvariants()
        self.grn_invariants = GoodsReceiptInvariants()
        self.delivery_invariants = DeliveryNoteInvariants()

    def validate_po_number_unique(self, po_number: str, existing: set[str]) -> InvariantResult:
        return self.po_invariants.validate_po_number_unique(po_number, existing)

    def validate_po_quantity(self, po: PurchaseOrderEntity) -> InvariantResult:
        return self.po_invariants.validate_po_quantity(po)

    def validate_po_receipt(
        self, po: PurchaseOrderEntity, item_id: UUID, received_qty: Decimal
    ) -> InvariantResult:
        return self.po_invariants.validate_receipt_quantity(po, item_id, received_qty)

    def validate_so_number_unique(self, so_number: str, existing: set[str]) -> InvariantResult:
        return self.so_invariants.validate_so_number_unique(so_number, existing)

    def validate_so_quantity(self, so: SalesOrderEntity) -> InvariantResult:
        return self.so_invariants.validate_so_quantity(so)

    def validate_so_delivery(
        self, so: SalesOrderEntity, item_id: UUID, delivered_qty: Decimal
    ) -> InvariantResult:
        return self.so_invariants.validate_delivery_quantity(so, item_id, delivered_qty)

    def validate_invoice_number_unique(
        self, invoice_number: str, existing: set[str]
    ) -> InvariantResult:
        return self.invoice_invariants.validate_invoice_number_unique(invoice_number, existing)

    def validate_invoice_amount(
        self, total_amount: Decimal, items_total: Decimal
    ) -> InvariantResult:
        return self.invoice_invariants.validate_invoice_amount(total_amount, items_total)

    def validate_payment_amount(
        self, paid_amount: Decimal, total_amount: Decimal
    ) -> InvariantResult:
        return self.invoice_invariants.validate_payment_amount(paid_amount, total_amount)

    def validate_grn_quantity(
        self, grn: GoodsReceiptNoteEntity, po: PurchaseOrderEntity
    ) -> InvariantResult:
        return self.grn_invariants.validate_grn_quantity(grn, po)

    def validate_delivery_quantity(
        self, delivery: SalesDeliveryNoteEntity, so: SalesOrderEntity
    ) -> InvariantResult:
        return self.delivery_invariants.validate_delivery_quantity(delivery, so)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DeliveryNoteInvariants",
    "GoodsReceiptInvariants",
    "InvariantResult",
    "InvoiceInvariants",
    "PurchaseOrderInvariants",
    "PurchaseSalesInvariantEnforcer",
    "PurchaseSalesInvariantsValidator",
    "SalesOrderInvariants",
]
