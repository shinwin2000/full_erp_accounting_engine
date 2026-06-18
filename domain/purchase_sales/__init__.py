#!/usr/bin/env python3
"""
Module: __init__.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Package initializer for purchase & sales domain.

Exports all public components from the purchase & sales domain layer.
"""

from domain.purchase_sales.domain_events import (
    DeliveryNoteShippedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    GoodsReceiptCreatedEvent,
    PurchaseInvoiceReceivedEvent,
    PurchaseOrderApprovedEvent,
    PurchaseOrderCreatedEvent,
    SalesInvoiceIssuedEvent,
    SalesInvoicePaidEvent,
    SalesOrderApprovedEvent,
    SalesOrderCreatedEvent,
)
from domain.purchase_sales.goods_receipt_note_entity import (
    GoodsReceiptNoteEntity,
    GoodsReceiptNoteRepository,
    GRNItem,
    GRNStatus,
)
from domain.purchase_sales.invariants import (
    DeliveryNoteInvariants,
    GoodsReceiptInvariants,
    InvariantResult,
    InvoiceInvariants,
    PurchaseOrderInvariants,
    PurchaseSalesInvariantEnforcer,
    PurchaseSalesInvariantsValidator,
    SalesOrderInvariants,
)
from domain.purchase_sales.purchase_invoice_entity import (
    PurchaseInvoiceEntity,
    PurchaseInvoiceItem,
    PurchaseInvoiceRepository,
    PurchaseInvoiceStatus,
    PurchaseInvoiceType,
)
from domain.purchase_sales.purchase_order_aggregate import (
    PurchaseOrderAggregate,
    PurchaseOrderRepository,
)
from domain.purchase_sales.purchase_order_entity import (
    POItem,
    POStatus,
    POType,
    PurchaseOrderEntity,
    PurchaseOrderEntityRepository,
)
from domain.purchase_sales.purchase_return_entity import (
    PurchaseReturnEntity,
    PurchaseReturnItem,
    PurchaseReturnReason,
    PurchaseReturnRepository,
    PurchaseReturnStatus,
)
from domain.purchase_sales.sales_delivery_note_entity import (
    DeliveryItem,
    DeliveryStatus,
    SalesDeliveryNoteEntity,
    SalesDeliveryNoteRepository,
)
from domain.purchase_sales.sales_invoice_entity import (
    SalesInvoiceEntity,
    SalesInvoiceItem,
    SalesInvoiceRepository,
    SalesInvoiceStatus,
    SalesInvoiceType,
)
from domain.purchase_sales.sales_order_aggregate import (
    SalesOrderAggregate,
    SalesOrderRepository,
)
from domain.purchase_sales.sales_order_entity import (
    SalesOrderEntity,
    SalesOrderEntityRepository,
    SOItem,
    SOStatus,
    SOType,
)
from domain.purchase_sales.sales_return_entity import (
    SalesReturnEntity,
    SalesReturnItem,
    SalesReturnReason,
    SalesReturnRepository,
    SalesReturnStatus,
)

__all__ = [
    # Purchase Order
    "PurchaseOrderEntity",
    "POItem",
    "POStatus",
    "POType",
    "PurchaseOrderEntityRepository",
    # Sales Order
    "SalesOrderEntity",
    "SOItem",
    "SOStatus",
    "SOType",
    "SalesOrderEntityRepository",
    # Goods Receipt Note
    "GoodsReceiptNoteEntity",
    "GRNItem",
    "GRNStatus",
    "GoodsReceiptNoteRepository",
    # Sales Delivery Note
    "SalesDeliveryNoteEntity",
    "DeliveryItem",
    "DeliveryStatus",
    "SalesDeliveryNoteRepository",
    # Purchase Invoice
    "PurchaseInvoiceEntity",
    "PurchaseInvoiceItem",
    "PurchaseInvoiceStatus",
    "PurchaseInvoiceType",
    "PurchaseInvoiceRepository",
    # Sales Invoice
    "SalesInvoiceEntity",
    "SalesInvoiceItem",
    "SalesInvoiceStatus",
    "SalesInvoiceType",
    "SalesInvoiceRepository",
    # Purchase Return
    "PurchaseReturnEntity",
    "PurchaseReturnItem",
    "PurchaseReturnStatus",
    "PurchaseReturnReason",
    "PurchaseReturnRepository",
    # Sales Return
    "SalesReturnEntity",
    "SalesReturnItem",
    "SalesReturnStatus",
    "SalesReturnReason",
    "SalesReturnRepository",
    # Aggregates
    "PurchaseOrderAggregate",
    "PurchaseOrderRepository",
    "SalesOrderAggregate",
    "SalesOrderRepository",
    # Domain Events
    "DomainEventType",
    "DomainEvent",
    "PurchaseOrderCreatedEvent",
    "PurchaseOrderApprovedEvent",
    "SalesOrderCreatedEvent",
    "SalesOrderApprovedEvent",
    "GoodsReceiptCreatedEvent",
    "DeliveryNoteShippedEvent",
    "SalesInvoiceIssuedEvent",
    "SalesInvoicePaidEvent",
    "PurchaseInvoiceReceivedEvent",
    "DomainEventPublisher",
    # Invariants
    "InvariantResult",
    "PurchaseOrderInvariants",
    "SalesOrderInvariants",
    "InvoiceInvariants",
    "GoodsReceiptInvariants",
    "DeliveryNoteInvariants",
    "PurchaseSalesInvariantEnforcer",
    "PurchaseSalesInvariantsValidator",
]
