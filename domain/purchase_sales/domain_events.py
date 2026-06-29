#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Event: PurchaseOrderCreated, SalesOrderApproved, etc.
               Mendefinisikan semua domain events yang dihasilkan oleh
               Purchase & Sales aggregates. Event ini digunakan untuk
               komunikasi antar bounded context, event sourcing, dan
               proyeksi read model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.purchase_sales.goods_receipt_note_entity import GoodsReceiptNoteEntity
from domain.purchase_sales.purchase_invoice_entity import PurchaseInvoiceEntity
from domain.purchase_sales.purchase_order_entity import PurchaseOrderEntity
from domain.purchase_sales.sales_delivery_note_entity import SalesDeliveryNoteEntity
from domain.purchase_sales.sales_invoice_entity import SalesInvoiceEntity
from domain.purchase_sales.sales_order_entity import SalesOrderEntity


# === 1. DOMAIN EVENT TYPE ===

class DomainEventType(Enum):
    """Tipe domain event untuk Purchase & Sales."""

    # Purchase Order events
    PURCHASE_ORDER_CREATED = "purchase_order_created"
    PURCHASE_ORDER_APPROVED = "purchase_order_approved"
    PURCHASE_ORDER_CANCELLED = "purchase_order_cancelled"
    PURCHASE_ORDER_RECEIVED = "purchase_order_received"

    # Sales Order events
    SALES_ORDER_CREATED = "sales_order_created"
    SALES_ORDER_APPROVED = "sales_order_approved"
    SALES_ORDER_CANCELLED = "sales_order_cancelled"
    SALES_ORDER_DELIVERED = "sales_order_delivered"
    SALES_ORDER_INVOICED = "sales_order_invoiced"

    # Goods Receipt events
    GOODS_RECEIPT_CREATED = "goods_receipt_created"
    GOODS_RECEIPT_CONFIRMED = "goods_receipt_confirmed"

    # Delivery Note events
    DELIVERY_NOTE_CREATED = "delivery_note_created"
    DELIVERY_NOTE_SHIPPED = "delivery_note_shipped"
    DELIVERY_NOTE_DELIVERED = "delivery_note_delivered"

    # Invoice events (generic)
    INVOICE_CREATED = "invoice_created"
    INVOICE_ISSUED = "invoice_issued"
    INVOICE_APPROVED = "invoice_approved"
    INVOICE_CANCELLED = "invoice_cancelled"
    INVOICE_PAID = "invoice_paid"
    INVOICE_PARTIALLY_PAID = "invoice_partially_paid"
    INVOICE_DISPUTED = "invoice_disputed"
    INVOICE_VERIFIED = "invoice_verified"
    INVOICE_RECEIVED = "invoice_received"
    INVOICE_WRITTEN_OFF = "invoice_written_off"

    # Purchase Invoice events
    PURCHASE_INVOICE_RECEIVED = "purchase_invoice_received"
    PURCHASE_INVOICE_APPROVED = "purchase_invoice_approved"
    PURCHASE_INVOICE_PAID = "purchase_invoice_paid"

    # Sales Invoice events
    SALES_INVOICE_ISSUED = "sales_invoice_issued"
    SALES_INVOICE_PAID = "sales_invoice_paid"

    # Credit Note events
    CREDIT_NOTE_ISSUED = "credit_note_issued"
    CREDIT_NOTE_RECEIVED = "credit_note_received"
    CREDIT_NOTE_APPLIED = "credit_note_applied"

    # Debit Note events
    DEBIT_NOTE_ISSUED = "debit_note_issued"
    DEBIT_NOTE_APPLIED = "debit_note_applied"
    DEBIT_NOTE_ISSUED_SERVICE = "debit_note_issued_service"

    # Return events
    PURCHASE_RETURN_CREATED = "purchase_return_created"
    SALES_RETURN_CREATED = "sales_return_created"


# === 2. BASE DOMAIN EVENT ===

@dataclass
class DomainEvent:
    """Base class untuk semua domain events Purchase & Sales."""

    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": str(self.event_id),
                "event_type": self.event_type.value,
                "aggregate_id": str(self.aggregate_id),
                "aggregate_version": self.aggregate_version,
                "occurred_at": self.occurred_at.isoformat(),
                "user_id": self.user_id,
                "correlation_id": self.correlation_id,
                "event_data": self.event_data,
            },
            default=str,
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        data = json.loads(json_str)
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
        )


# === 3. CONCRETE DOMAIN EVENTS ===

# --- 3a. Purchase Order Events ---

@dataclass
class PurchaseOrderCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        purchase_order: PurchaseOrderEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "po_id": str(purchase_order.po_id),
            "po_number": purchase_order.po_number,
            "supplier_id": str(purchase_order.supplier_id),
            "supplier_name": purchase_order.supplier_name,
            "total_amount": str(purchase_order.total_amount),
            "currency": purchase_order.currency,
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PURCHASE_ORDER_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PurchaseOrderApprovedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        purchase_order: PurchaseOrderEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "po_id": str(purchase_order.po_id),
            "po_number": purchase_order.po_number,
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PURCHASE_ORDER_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# --- 3b. Sales Order Events ---

@dataclass
class SalesOrderCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        sales_order: SalesOrderEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "so_id": str(sales_order.so_id),
            "so_number": sales_order.so_number,
            "customer_id": str(sales_order.customer_id),
            "customer_name": sales_order.customer_name,
            "total_amount": str(sales_order.total_amount),
            "currency": sales_order.currency,
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SALES_ORDER_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SalesOrderApprovedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        sales_order: SalesOrderEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "so_id": str(sales_order.so_id),
            "so_number": sales_order.so_number,
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SALES_ORDER_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# --- 3c. Goods Receipt ---

@dataclass
class GoodsReceiptCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        grn: GoodsReceiptNoteEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "grn_id": str(grn.grn_id),
            "grn_number": grn.grn_number,
            "po_id": str(grn.po_id),
            "po_number": grn.po_number,
            "supplier_id": str(grn.supplier_id),
            "supplier_name": grn.supplier_name,
            "receipt_date": grn.receipt_date.isoformat(),
            "total_amount": str(grn.total_amount),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.GOODS_RECEIPT_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# --- 3d. Delivery Note ---

@dataclass
class DeliveryNoteShippedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        delivery: SalesDeliveryNoteEntity,
        shipped_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "delivery_id": str(delivery.delivery_id),
            "delivery_number": delivery.delivery_number,
            "so_id": str(delivery.so_id),
            "so_number": delivery.so_number,
            "customer_id": str(delivery.customer_id),
            "customer_name": delivery.customer_name,
            "shipped_by": shipped_by,
            "tracking_number": delivery.tracking_number,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DELIVERY_NOTE_SHIPPED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# --- 3e. Sales Invoice Events ---

@dataclass
class SalesInvoiceIssuedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: SalesInvoiceEntity,
        issued_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "customer_id": str(invoice.customer_id),
            "customer_name": invoice.customer_name,
            "invoice_date": invoice.invoice_date.isoformat(),
            "due_date": invoice.due_date.isoformat(),
            "total_amount": str(invoice.total_amount),
            "currency": invoice.currency,
            "issued_by": issued_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SALES_INVOICE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class SalesInvoicePaidEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: SalesInvoiceEntity,
        payment_amount: Decimal,
        paid_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "payment_amount": str(payment_amount),
            "total_paid": str(invoice.paid_amount),
            "paid_by": paid_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SALES_INVOICE_PAID,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# --- 3f. Purchase Invoice Events ---

@dataclass
class PurchaseInvoiceReceivedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: PurchaseInvoiceEntity,
        received_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "supplier_id": str(invoice.supplier_id),
            "supplier_name": invoice.supplier_name,
            "invoice_date": invoice.invoice_date.isoformat(),
            "due_date": invoice.due_date.isoformat(),
            "total_amount": str(invoice.total_amount),
            "currency": invoice.currency,
            "received_by": received_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PURCHASE_INVOICE_RECEIVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PurchaseInvoiceApprovedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: PurchaseInvoiceEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "supplier_id": str(invoice.supplier_id),
            "supplier_name": invoice.supplier_name,
            "total_amount": str(invoice.total_amount),
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PURCHASE_INVOICE_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PurchaseInvoicePaidEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: PurchaseInvoiceEntity,
        payment_amount: Decimal,
        paid_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "supplier_id": str(invoice.supplier_id),
            "supplier_name": invoice.supplier_name,
            "payment_amount": str(payment_amount),
            "paid_by": paid_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PURCHASE_INVOICE_PAID,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# --- 3g. Generic Invoice Events (digunakan oleh service_purchase_sales) ---

@dataclass
class InvoiceCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        total_amount: Decimal,
        created_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "total_amount": str(total_amount),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or created_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceIssuedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        total_amount: Decimal,
        issued_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "total_amount": str(total_amount),
            "issued_by": issued_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or issued_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceApprovedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        approved_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or approved_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceCancelledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        reason: str | None = None,
        cancelled_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "reason": reason,
            "cancelled_by": cancelled_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or cancelled_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoicePaidEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        payment_amount: Decimal,
        paid_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "payment_amount": str(payment_amount),
            "paid_by": paid_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_PAID,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or paid_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoicePartiallyPaidEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        paid_amount: Decimal,
        total_amount: Decimal,
        paid_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "paid_amount": str(paid_amount),
            "total_amount": str(total_amount),
            "paid_by": paid_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_PARTIALLY_PAID,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or paid_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceDisputedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        reason: str | None = None,
        disputed_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "reason": reason,
            "disputed_by": disputed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_DISPUTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or disputed_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceVerifiedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        verified_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "verified_by": verified_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_VERIFIED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or verified_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceReceivedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        received_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "received_by": received_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_RECEIVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or received_by,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceWrittenOffEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        invoice_type: str,
        reason: str | None = None,
        written_off_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "invoice_type": invoice_type,
            "reason": reason,
            "written_off_by": written_off_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_WRITTEN_OFF,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or written_off_by,
            correlation_id=correlation_id,
        )


# --- 3h. Credit Note Events ---

@dataclass
class CreditNoteIssuedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        credit_note_id: UUID,
        credit_note_number: str,
        invoice_id: UUID,
        invoice_type: str,
        amount: Decimal,
        reason: str,
        issued_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "credit_note_id": str(credit_note_id),
            "credit_note_number": credit_note_number,
            "invoice_id": str(invoice_id),
            "invoice_type": invoice_type,
            "amount": str(amount),
            "reason": reason,
            "issued_by": issued_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CREDIT_NOTE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or issued_by,
            correlation_id=correlation_id,
        )


@dataclass
class CreditNoteReceivedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        credit_note_id: UUID,
        credit_note_number: str,
        invoice_id: UUID,
        invoice_type: str,
        amount: Decimal,
        received_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "credit_note_id": str(credit_note_id),
            "credit_note_number": credit_note_number,
            "invoice_id": str(invoice_id),
            "invoice_type": invoice_type,
            "amount": str(amount),
            "received_by": received_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CREDIT_NOTE_RECEIVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or received_by,
            correlation_id=correlation_id,
        )


@dataclass
class CreditNoteAppliedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        credit_note_id: UUID,
        credit_note_number: str,
        invoice_id: UUID,
        invoice_type: str,
        amount: Decimal,
        applied_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "credit_note_id": str(credit_note_id),
            "credit_note_number": credit_note_number,
            "invoice_id": str(invoice_id),
            "invoice_type": invoice_type,
            "amount": str(amount),
            "applied_by": applied_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CREDIT_NOTE_APPLIED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or applied_by,
            correlation_id=correlation_id,
        )


# --- 3i. Debit Note Events ---

@dataclass
class DebitNoteIssuedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        debit_note_id: UUID,
        debit_note_number: str,
        invoice_id: UUID,
        invoice_type: str,
        amount: Decimal,
        reason: str,
        issued_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "debit_note_id": str(debit_note_id),
            "debit_note_number": debit_note_number,
            "invoice_id": str(invoice_id),
            "invoice_type": invoice_type,
            "amount": str(amount),
            "reason": reason,
            "issued_by": issued_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DEBIT_NOTE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or issued_by,
            correlation_id=correlation_id,
        )


@dataclass
class DebitNoteAppliedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        debit_note_id: UUID,
        debit_note_number: str,
        invoice_id: UUID,
        invoice_type: str,
        amount: Decimal,
        applied_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "debit_note_id": str(debit_note_id),
            "debit_note_number": debit_note_number,
            "invoice_id": str(invoice_id),
            "invoice_type": invoice_type,
            "amount": str(amount),
            "applied_by": applied_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DEBIT_NOTE_APPLIED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or applied_by,
            correlation_id=correlation_id,
        )


@dataclass
class DebitNoteIssuedServiceEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        debit_note_id: UUID,
        debit_note_number: str,
        invoice_id: UUID,
        invoice_type: str,
        amount: Decimal,
        reason: str,
        service_type: str = "service",
        issued_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "debit_note_id": str(debit_note_id),
            "debit_note_number": debit_note_number,
            "invoice_id": str(invoice_id),
            "invoice_type": invoice_type,
            "amount": str(amount),
            "reason": reason,
            "service_type": service_type,
            "issued_by": issued_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DEBIT_NOTE_ISSUED_SERVICE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or issued_by,
            correlation_id=correlation_id,
        )


# === 4. DOMAIN EVENT PUBLISHER PROTOCOL ===

class DomainEventPublisher:
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)


# === 5. EXPORTS ===

__all__ = [
    # Base
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",

    # Purchase Order
    "PurchaseOrderCreatedEvent",
    "PurchaseOrderApprovedEvent",

    # Sales Order
    "SalesOrderCreatedEvent",
    "SalesOrderApprovedEvent",

    # Goods Receipt
    "GoodsReceiptCreatedEvent",

    # Delivery Note
    "DeliveryNoteShippedEvent",

    # Sales Invoice
    "SalesInvoiceIssuedEvent",
    "SalesInvoicePaidEvent",

    # Purchase Invoice
    "PurchaseInvoiceReceivedEvent",
    "PurchaseInvoiceApprovedEvent",
    "PurchaseInvoicePaidEvent",

    # Generic Invoice events
    "InvoiceCreatedEvent",
    "InvoiceIssuedEvent",
    "InvoiceApprovedEvent",
    "InvoiceCancelledEvent",
    "InvoicePaidEvent",
    "InvoicePartiallyPaidEvent",
    "InvoiceDisputedEvent",
    "InvoiceVerifiedEvent",
    "InvoiceReceivedEvent",
    "InvoiceWrittenOffEvent",

    # Credit Note
    "CreditNoteIssuedEvent",
    "CreditNoteReceivedEvent",
    "CreditNoteAppliedEvent",

    # Debit Note
    "DebitNoteIssuedEvent",
    "DebitNoteAppliedEvent",
    "DebitNoteIssuedServiceEvent",
]