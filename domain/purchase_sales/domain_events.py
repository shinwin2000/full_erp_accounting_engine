#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Event: PurchaseOrderCreated, SalesOrderApproved, etc.
               Mendefinisikan semua domain events yang dihasilkan oleh
               Purchase & Sales aggregates. Event ini digunakan untuk
               komunikasi antar bounded context, event sourcing, dan
               proyeksi read model.

Dependencies:
- standard library (uuid, datetime, dataclass, json)
- domain.purchase_sales.purchase_order_entity (PurchaseOrderEntity)
- domain.purchase_sales.sales_order_entity (SalesOrderEntity)
- domain.purchase_sales.purchase_invoice_entity (PurchaseInvoiceEntity)
- domain.purchase_sales.sales_invoice_entity (SalesInvoiceEntity)

Audit: Setiap event domain purchase & sales dictat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.purchase_sales.goods_receipt_note_entity import GoodsReceiptNoteEntity
from domain.purchase_sales.purchase_invoice_entity import (
    PurchaseInvoiceEntity,
)
from domain.purchase_sales.purchase_order_entity import PurchaseOrderEntity
from domain.purchase_sales.sales_delivery_note_entity import SalesDeliveryNoteEntity
from domain.purchase_sales.sales_invoice_entity import SalesInvoiceEntity
from domain.purchase_sales.sales_order_entity import SalesOrderEntity

# === 1. DOMAIN EVENT BASE ===


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

    # Invoice events
    PURCHASE_INVOICE_RECEIVED = "purchase_invoice_received"
    PURCHASE_INVOICE_APPROVED = "purchase_invoice_approved"
    PURCHASE_INVOICE_PAID = "purchase_invoice_paid"
    SALES_INVOICE_ISSUED = "sales_invoice_issued"
    SALES_INVOICE_PAID = "sales_invoice_paid"

    # Return events
    PURCHASE_RETURN_CREATED = "purchase_return_created"
    SALES_RETURN_CREATED = "sales_return_created"


@dataclass
class DomainEvent:
    """
    Base class untuk semua domain events Purchase & Sales.
    """

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


# === 2. CONCRETE DOMAIN EVENTS ===


@dataclass
class PurchaseOrderCreatedEvent(DomainEvent):
    """Event ketika Purchase Order baru dibuat."""

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
    """Event ketika Purchase Order disetujui."""

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


@dataclass
class SalesOrderCreatedEvent(DomainEvent):
    """Event ketika Sales Order baru dibuat."""

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
    """Event ketika Sales Order disetujui."""

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


@dataclass
class GoodsReceiptCreatedEvent(DomainEvent):
    """Event ketika Goods Receipt Note dibuat."""

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


@dataclass
class DeliveryNoteShippedEvent(DomainEvent):
    """Event ketika Delivery Note dikirim."""

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


@dataclass
class SalesInvoiceIssuedEvent(DomainEvent):
    """Event ketika Sales Invoice diterbitkan."""

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
    """Event ketika Sales Invoice dibayar."""

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


@dataclass
class PurchaseInvoiceReceivedEvent(DomainEvent):
    """Event ketika Purchase Invoice diterima dari supplier."""

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


# === 3. DOMAIN EVENT PUBLISHER PROTOCOL ===


class DomainEventPublisher:
    """
    Protocol untuk publish domain events Purchase & Sales.
    """

    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)


# === 4. EXPORTS ===

__all__ = [
    "DeliveryNoteShippedEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "GoodsReceiptCreatedEvent",
    "PurchaseInvoiceReceivedEvent",
    "PurchaseOrderApprovedEvent",
    "PurchaseOrderCreatedEvent",
    "SalesInvoiceIssuedEvent",
    "SalesInvoicePaidEvent",
    "SalesOrderApprovedEvent",
    "SalesOrderCreatedEvent",
]
