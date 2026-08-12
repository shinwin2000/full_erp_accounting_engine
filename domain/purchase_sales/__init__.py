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
    "DeliveryItem",
    "DeliveryNoteInvariants",
    "DeliveryNoteShippedEvent",
    "DeliveryStatus",
    "DomainEvent",
    "DomainEventPublisher",
    # Domain Events
    "DomainEventType",
    "GRNItem",
    "GRNStatus",
    "GoodsReceiptCreatedEvent",
    "GoodsReceiptInvariants",
    # Goods Receipt Note
    "GoodsReceiptNoteEntity",
    "GoodsReceiptNoteRepository",
    # Invariants
    "InvariantResult",
    "InvoiceInvariants",
    "POItem",
    "POStatus",
    "POType",
    # Purchase Invoice
    "PurchaseInvoiceEntity",
    "PurchaseInvoiceItem",
    "PurchaseInvoiceReceivedEvent",
    "PurchaseInvoiceRepository",
    "PurchaseInvoiceStatus",
    "PurchaseInvoiceType",
    # Aggregates
    "PurchaseOrderAggregate",
    "PurchaseOrderApprovedEvent",
    "PurchaseOrderCreatedEvent",
    # Purchase Order
    "PurchaseOrderEntity",
    "PurchaseOrderEntityRepository",
    "PurchaseOrderInvariants",
    "PurchaseOrderRepository",
    # Purchase Return
    "PurchaseReturnEntity",
    "PurchaseReturnItem",
    "PurchaseReturnReason",
    "PurchaseReturnRepository",
    "PurchaseReturnStatus",
    "PurchaseSalesInvariantEnforcer",
    "PurchaseSalesInvariantsValidator",
    "SOItem",
    "SOStatus",
    "SOType",
    # Sales Delivery Note
    "SalesDeliveryNoteEntity",
    "SalesDeliveryNoteRepository",
    # Sales Invoice
    "SalesInvoiceEntity",
    "SalesInvoiceIssuedEvent",
    "SalesInvoiceItem",
    "SalesInvoicePaidEvent",
    "SalesInvoiceRepository",
    "SalesInvoiceStatus",
    "SalesInvoiceType",
    "SalesOrderAggregate",
    "SalesOrderApprovedEvent",
    "SalesOrderCreatedEvent",
    # Sales Order
    "SalesOrderEntity",
    "SalesOrderEntityRepository",
    "SalesOrderInvariants",
    "SalesOrderRepository",
    # Sales Return
    "SalesReturnEntity",
    "SalesReturnItem",
    "SalesReturnReason",
    "SalesReturnRepository",
    "SalesReturnStatus",
]
