# service_purchase_sales.py - Complete rewrite with full event publishing

#!/usr/bin/env python3
"""
Module: service_purchase_sales.py
Layer: Application / Service Layer
Responsibility: Menyediakan service untuk mengelola purchase order, goods receipt,
               sales order, delivery note, dan invoice terkait.
               Dilengkapi dengan event publishing untuk setiap perubahan status.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

# Import domain events
from domain.purchase_sales.domain_events import (
    CreditNoteAppliedEvent,
    CreditNoteIssuedEvent,
    CreditNoteReceivedEvent,
    DebitNoteAppliedEvent,
    DebitNoteIssuedEvent,
    DebitNoteIssuedServiceEvent,
    DeliveryNoteShippedEvent,
    GoodsReceiptCreatedEvent,
    InvoiceApprovedEvent,
    InvoiceCancelledEvent,
    InvoiceCreatedEvent,
    InvoiceDisputedEvent,
    InvoiceIssuedEvent,
    InvoicePaidEvent,
    InvoicePartiallyPaidEvent,
    InvoiceReceivedEvent,
    InvoiceVerifiedEvent,
    InvoiceWrittenOffEvent,
    PurchaseInvoiceApprovedEvent,
    PurchaseInvoicePaidEvent,
    PurchaseInvoiceReceivedEvent,
    PurchaseOrderApprovedEvent,
    PurchaseOrderCreatedEvent,
    SalesInvoiceIssuedEvent,
    SalesInvoicePaidEvent,
    SalesOrderApprovedEvent,
    SalesOrderCreatedEvent,
)
from ports.primary.event_publisher_port import EventPublisherPort

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class OrderStatus(str, Enum):
    """Status for orders."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class DocumentStatus(str, Enum):
    """Status for documents."""

    DRAFT = "draft"
    ISSUED = "issued"
    RECEIVED = "received"
    APPROVED = "approved"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"
    VERIFIED = "verified"
    WRITTEN_OFF = "written_off"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class PurchaseOrderLine:
    """Purchase order line item."""

    product_id: UUID
    product_code: str
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percentage: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("11")

    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def discount_amount(self) -> Decimal:
        return self.subtotal * self.discount_percentage / Decimal("100")

    @property
    def net_amount(self) -> Decimal:
        return self.subtotal - self.discount_amount

    @property
    def tax_amount(self) -> Decimal:
        return self.net_amount * self.tax_rate / Decimal("100")

    @property
    def total_amount(self) -> Decimal:
        return self.net_amount + self.tax_amount


@dataclass(kw_only=True)
class PurchaseOrder:
    """Purchase order model."""

    id: UUID = field(default_factory=uuid4)
    po_number: str
    supplier_id: UUID
    supplier_name: str
    order_date: date = field(default_factory=date.today)
    expected_delivery_date: date | None = None
    status: OrderStatus = OrderStatus.DRAFT
    total_amount: Decimal = Decimal("0")
    currency: str = "IDR"
    lines: list[PurchaseOrderLine] = field(default_factory=list)
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None

    def calculate_total(self) -> Decimal:
        total = sum(line.total_amount for line in self.lines)
        self.total_amount = total
        return total


@dataclass(kw_only=True)
class SalesOrderLine:
    """Sales order line item."""

    product_id: UUID
    product_code: str
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percentage: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("11")

    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def discount_amount(self) -> Decimal:
        return self.subtotal * self.discount_percentage / Decimal("100")

    @property
    def net_amount(self) -> Decimal:
        return self.subtotal - self.discount_amount

    @property
    def tax_amount(self) -> Decimal:
        return self.net_amount * self.tax_rate / Decimal("100")

    @property
    def total_amount(self) -> Decimal:
        return self.net_amount + self.tax_amount


@dataclass(kw_only=True)
class SalesOrder:
    """Sales order model."""

    id: UUID = field(default_factory=uuid4)
    so_number: str
    customer_id: UUID
    customer_name: str
    order_date: date = field(default_factory=date.today)
    requested_delivery_date: date | None = None
    status: OrderStatus = OrderStatus.DRAFT
    total_amount: Decimal = Decimal("0")
    currency: str = "IDR"
    lines: list[SalesOrderLine] = field(default_factory=list)
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None

    def calculate_total(self) -> Decimal:
        total = sum(line.total_amount for line in self.lines)
        self.total_amount = total
        return total


@dataclass(kw_only=True)
class GoodsReceiptLine:
    """Goods receipt line item."""

    product_id: UUID
    product_code: str
    product_name: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    rejected_quantity: Decimal = Decimal("0")
    unit_cost: Decimal = Decimal("0")


@dataclass(kw_only=True)
class GoodsReceipt:
    """Goods receipt note model."""

    id: UUID = field(default_factory=uuid4)
    grn_number: str
    purchase_order_id: UUID
    po_number: str
    receipt_date: date = field(default_factory=date.today)
    lines: list[GoodsReceiptLine] = field(default_factory=list)
    status: DocumentStatus = DocumentStatus.DRAFT
    received_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None


@dataclass(kw_only=True)
class DeliveryNoteLine:
    """Delivery note line item."""

    product_id: UUID
    product_code: str
    product_name: str
    ordered_quantity: Decimal
    delivered_quantity: Decimal
    unit_price: Decimal = Decimal("0")


@dataclass(kw_only=True)
class DeliveryNote:
    """Delivery note model."""

    id: UUID = field(default_factory=uuid4)
    dn_number: str
    sales_order_id: UUID
    so_number: str
    delivery_date: date = field(default_factory=date.today)
    lines: list[DeliveryNoteLine] = field(default_factory=list)
    status: DocumentStatus = DocumentStatus.DRAFT
    delivered_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None


@dataclass(kw_only=True)
class InvoiceLine:
    """Invoice line item."""

    product_id: UUID
    product_code: str
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percentage: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("11")
    total_amount: Decimal = Decimal("0")


@dataclass(kw_only=True)
class PurchaseInvoice:
    """Purchase invoice model."""

    id: UUID = field(default_factory=uuid4)
    invoice_number: str
    purchase_order_id: UUID
    goods_receipt_id: UUID | None = None
    invoice_date: date = field(default_factory=date.today)
    due_date: date | None = None
    total_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    status: DocumentStatus = DocumentStatus.DRAFT
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None
    lines: list[InvoiceLine] = field(default_factory=list)


@dataclass(kw_only=True)
class SalesInvoice:
    """Sales invoice model."""

    id: UUID = field(default_factory=uuid4)
    invoice_number: str
    sales_order_id: UUID
    delivery_note_id: UUID | None = None
    invoice_date: date = field(default_factory=date.today)
    due_date: date | None = None
    total_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    status: DocumentStatus = DocumentStatus.DRAFT
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None
    lines: list[InvoiceLine] = field(default_factory=list)


@dataclass(kw_only=True)
class CreditNote:
    """Credit note model."""

    id: UUID = field(default_factory=uuid4)
    credit_note_number: str
    invoice_id: UUID
    invoice_type: str  # "purchase" or "sales"
    credit_note_date: date = field(default_factory=date.today)
    amount: Decimal = Decimal("0")
    reason: str
    status: DocumentStatus = DocumentStatus.DRAFT
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None


@dataclass(kw_only=True)
class DebitNote:
    """Debit note model."""

    id: UUID = field(default_factory=uuid4)
    debit_note_number: str
    invoice_id: UUID
    invoice_type: str  # "purchase" or "sales"
    debit_note_date: date = field(default_factory=date.today)
    amount: Decimal = Decimal("0")
    reason: str
    status: DocumentStatus = DocumentStatus.DRAFT
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None


# ============================================================================
# Exceptions
# ============================================================================


class PurchaseSalesServiceError(Exception):
    pass


class PurchaseOrderNotFoundError(PurchaseSalesServiceError):
    pass


class SalesOrderNotFoundError(PurchaseSalesServiceError):
    pass


class GoodsReceiptNotFoundError(PurchaseSalesServiceError):
    pass


class DeliveryNoteNotFoundError(PurchaseSalesServiceError):
    pass


class PurchaseInvoiceNotFoundError(PurchaseSalesServiceError):
    pass


class SalesInvoiceNotFoundError(PurchaseSalesServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class PurchaseSalesService:
    """
    Service layer untuk operasi purchase dan sales.
    Mempublikasikan event untuk setiap perubahan status.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._purchase_orders: dict[UUID, PurchaseOrder] = {}
        self._sales_orders: dict[UUID, SalesOrder] = {}
        self._goods_receipts: dict[UUID, GoodsReceipt] = {}
        self._delivery_notes: dict[UUID, DeliveryNote] = {}
        self._purchase_invoices: dict[UUID, PurchaseInvoice] = {}
        self._sales_invoices: dict[UUID, SalesInvoice] = {}
        self._credit_notes: dict[UUID, CreditNote] = {}
        self._debit_notes: dict[UUID, DebitNote] = {}
        self._stats = {
            "po_created": 0,
            "so_created": 0,
            "grn_created": 0,
            "dn_created": 0,
            "purchase_invoices": 0,
            "sales_invoices": 0,
            "credit_notes": 0,
            "debit_notes": 0,
        }
        self._event_publisher = event_publisher

        logger.info("PurchaseSalesService initialized")

    # ========================================================================
    # Purchase Order
    # ========================================================================

    async def create_purchase_order(
        self,
        po_number: str,
        supplier_id: UUID,
        supplier_name: str,
        lines: list[dict[str, Any]],
        order_date: date | None = None,
        expected_delivery_date: date | None = None,
        currency: str = "IDR",
        notes: str | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseOrder:
        """Create new purchase order."""
        logger.info(f"Creating purchase order: {po_number}")

        po_lines = []
        for line in lines:
            po_lines.append(
                PurchaseOrderLine(
                    product_id=UUID(line["product_id"]),
                    product_code=line.get("product_code", ""),
                    product_name=line.get("product_name", ""),
                    quantity=Decimal(str(line["quantity"])),
                    unit_price=Decimal(str(line["unit_price"])),
                    discount_percentage=Decimal(str(line.get("discount_percentage", 0))),
                    tax_rate=Decimal(str(line.get("tax_rate", 11))),
                )
            )

        po = PurchaseOrder(
            po_number=po_number,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            order_date=order_date or date.today(),
            expected_delivery_date=expected_delivery_date,
            currency=currency,
            lines=po_lines,
            notes=notes,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
        )
        po.calculate_total()

        self._purchase_orders[po.id] = po
        self._stats["po_created"] += 1

        # Publish event
        if self._event_publisher:
            try:
                event = PurchaseOrderCreatedEvent(
                    aggregate_id=po.id,
                    aggregate_version=1,
                    purchase_order=po,
                    created_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published PurchaseOrderCreatedEvent for {po.po_number}")
            except Exception as e:
                logger.warning(f"Failed to publish PurchaseOrderCreatedEvent: {e}")

        return po

    async def get_purchase_order(self, po_id: UUID) -> PurchaseOrder | None:
        return self._purchase_orders.get(po_id)

    async def list_purchase_orders(
        self,
        supplier_id: UUID | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        legal_entity_id: UUID | None = None,
    ) -> list[PurchaseOrder]:
        result = list(self._purchase_orders.values())
        if supplier_id:
            result = [po for po in result if po.supplier_id == supplier_id]
        if status:
            result = [po for po in result if po.status.value == status]
        if start_date:
            result = [po for po in result if po.order_date >= start_date]
        if end_date:
            result = [po for po in result if po.order_date <= end_date]
        if legal_entity_id:
            result = [po for po in result if po.legal_entity_id == legal_entity_id]
        return result

    async def update_purchase_order(
        self,
        po_id: UUID,
        expected_delivery_date: date | None = None,
        notes: str | None = None,
        status: str | None = None,
    ) -> PurchaseOrder | None:
        po = self._purchase_orders.get(po_id)
        if not po:
            raise PurchaseOrderNotFoundError(f"Purchase order {po_id} not found")
        if expected_delivery_date:
            po.expected_delivery_date = expected_delivery_date
        if notes:
            po.notes = notes
        if status:
            po.status = OrderStatus(status)
        po.updated_at = datetime.now(UTC)
        self._purchase_orders[po_id] = po
        return po

    async def submit_purchase_order(self, po_id: UUID, submitted_by: UUID) -> bool:
        po = self._purchase_orders.get(po_id)
        if not po:
            return False
        if po.status == OrderStatus.DRAFT:
            po.status = OrderStatus.SUBMITTED
            po.updated_at = datetime.now(UTC)
            self._purchase_orders[po_id] = po
            return True
        return False

    async def approve_purchase_order(
        self,
        po_id: UUID,
        approved_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        po = self._purchase_orders.get(po_id)
        if not po:
            return False
        if po.status == OrderStatus.SUBMITTED:
            po.status = OrderStatus.APPROVED
            po.updated_at = datetime.now(UTC)
            self._purchase_orders[po_id] = po

            if self._event_publisher:
                try:
                    event = PurchaseOrderApprovedEvent(
                        aggregate_id=po.id,
                        aggregate_version=1,
                        purchase_order=po,
                        approved_by=str(approved_by) if approved_by else "system",
                        user_id=str(approved_by) if approved_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published PurchaseOrderApprovedEvent for {po.po_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish PurchaseOrderApprovedEvent: {e}")
            return True
        return False

    # ========================================================================
    # Goods Receipt
    # ========================================================================

    async def create_goods_receipt(
        self,
        purchase_order_id: UUID,
        po_number: str,
        lines: list[dict[str, Any]],
        receipt_date: date | None = None,
        received_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> GoodsReceipt:
        logger.info(f"Creating goods receipt for PO {po_number}")

        grn_number = f"GRN-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:8]}"

        gr_lines = []
        for line in lines:
            gr_lines.append(
                GoodsReceiptLine(
                    product_id=UUID(line["product_id"]),
                    product_code=line.get("product_code", ""),
                    product_name=line.get("product_name", ""),
                    ordered_quantity=Decimal(str(line.get("ordered_quantity", 0))),
                    received_quantity=Decimal(str(line["received_quantity"])),
                    rejected_quantity=Decimal(str(line.get("rejected_quantity", 0))),
                    unit_cost=Decimal(str(line.get("unit_cost", 0))),
                )
            )

        grn = GoodsReceipt(
            grn_number=grn_number,
            purchase_order_id=purchase_order_id,
            po_number=po_number,
            receipt_date=receipt_date or date.today(),
            lines=gr_lines,
            received_by=received_by,
            legal_entity_id=legal_entity_id,
        )

        self._goods_receipts[grn.id] = grn
        self._stats["grn_created"] += 1

        if self._event_publisher:
            try:
                event = GoodsReceiptCreatedEvent(
                    aggregate_id=grn.id,
                    aggregate_version=1,
                    grn=grn,
                    created_by=str(received_by) if received_by else "system",
                    user_id=str(received_by) if received_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published GoodsReceiptCreatedEvent for {grn.grn_number}")
            except Exception as e:
                logger.warning(f"Failed to publish GoodsReceiptCreatedEvent: {e}")

        return grn

    async def get_goods_receipt(self, grn_id: UUID) -> GoodsReceipt | None:
        return self._goods_receipts.get(grn_id)

    async def list_goods_receipts(
        self, purchase_order_id: UUID | None = None, status: str | None = None
    ) -> list[GoodsReceipt]:
        result = list(self._goods_receipts.values())
        if purchase_order_id:
            result = [grn for grn in result if grn.purchase_order_id == purchase_order_id]
        if status:
            result = [grn for grn in result if grn.status.value == status]
        return result

    # ========================================================================
    # Purchase Invoice
    # ========================================================================

    async def create_purchase_invoice(
        self,
        invoice_number: str,
        purchase_order_id: UUID,
        total_amount: Decimal,
        lines: list[dict[str, Any]] | None = None,
        invoice_date: date | None = None,
        due_date: date | None = None,
        goods_receipt_id: UUID | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice:
        logger.info(f"Creating purchase invoice {invoice_number}")

        invoice_lines = []
        if lines:
            for line in lines:
                invoice_lines.append(
                    InvoiceLine(
                        product_id=UUID(line["product_id"]),
                        product_code=line.get("product_code", ""),
                        product_name=line.get("product_name", ""),
                        quantity=Decimal(str(line.get("quantity", 0))),
                        unit_price=Decimal(str(line.get("unit_price", 0))),
                        discount_percentage=Decimal(str(line.get("discount_percentage", 0))),
                        tax_rate=Decimal(str(line.get("tax_rate", 11))),
                        total_amount=Decimal(str(line.get("total_amount", 0))),
                    )
                )

        invoice = PurchaseInvoice(
            invoice_number=invoice_number,
            purchase_order_id=purchase_order_id,
            goods_receipt_id=goods_receipt_id,
            invoice_date=invoice_date or date.today(),
            due_date=due_date,
            total_amount=total_amount,
            lines=invoice_lines,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
        )

        self._purchase_invoices[invoice.id] = invoice
        self._stats["purchase_invoices"] += 1

        # Publish InvoiceCreatedEvent (generic)
        if self._event_publisher:
            try:
                event = InvoiceCreatedEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="purchase",
                    total_amount=invoice.total_amount,
                    created_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published InvoiceCreatedEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceCreatedEvent: {e}")

        return invoice

    async def receive_purchase_invoice(
        self,
        invoice_id: UUID,
        received_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status == DocumentStatus.DRAFT:
            invoice.status = DocumentStatus.RECEIVED
            invoice.updated_at = datetime.now(UTC)
            self._purchase_invoices[invoice_id] = invoice

            if self._event_publisher:
                try:
                    event = InvoiceReceivedEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice_id=invoice.id,
                        invoice_number=invoice.invoice_number,
                        invoice_type="purchase",
                        received_by=str(received_by) if received_by else "system",
                        user_id=str(received_by) if received_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published InvoiceReceivedEvent for {invoice.invoice_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish InvoiceReceivedEvent: {e}")

            # Also publish PurchaseInvoiceReceivedEvent for backward compatibility
            if self._event_publisher:
                try:
                    event2 = PurchaseInvoiceReceivedEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice=invoice,
                        received_by=str(received_by) if received_by else "system",
                        user_id=str(received_by) if received_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event2)
                except Exception:
                    pass

            return invoice
        return None

    async def approve_purchase_invoice(
        self,
        invoice_id: UUID,
        approved_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.RECEIVED, DocumentStatus.DRAFT):
            invoice.status = DocumentStatus.APPROVED
            invoice.updated_at = datetime.now(UTC)
            self._purchase_invoices[invoice_id] = invoice

            if self._event_publisher:
                try:
                    event = InvoiceApprovedEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice_id=invoice.id,
                        invoice_number=invoice.invoice_number,
                        invoice_type="purchase",
                        approved_by=str(approved_by) if approved_by else "system",
                        user_id=str(approved_by) if approved_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published InvoiceApprovedEvent for {invoice.invoice_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish InvoiceApprovedEvent: {e}")

            # Also publish PurchaseInvoiceApprovedEvent
            if self._event_publisher:
                try:
                    event2 = PurchaseInvoiceApprovedEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice=invoice,
                        approved_by=str(approved_by) if approved_by else "system",
                        user_id=str(approved_by) if approved_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event2)
                except Exception:
                    pass

            return invoice
        return None

    async def verify_purchase_invoice(
        self,
        invoice_id: UUID,
        verified_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.APPROVED, DocumentStatus.RECEIVED):
            invoice.status = DocumentStatus.VERIFIED
            invoice.updated_at = datetime.now(UTC)
            self._purchase_invoices[invoice_id] = invoice

            if self._event_publisher:
                try:
                    event = InvoiceVerifiedEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice_id=invoice.id,
                        invoice_number=invoice.invoice_number,
                        invoice_type="purchase",
                        verified_by=str(verified_by) if verified_by else "system",
                        user_id=str(verified_by) if verified_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published InvoiceVerifiedEvent for {invoice.invoice_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish InvoiceVerifiedEvent: {e}")

            return invoice
        return None

    async def pay_purchase_invoice(
        self,
        invoice_id: UUID,
        payment_amount: Decimal,
        paid_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.APPROVED, DocumentStatus.VERIFIED):
            invoice.paid_amount += payment_amount
            if invoice.paid_amount >= invoice.total_amount:
                invoice.status = DocumentStatus.PAID
            else:
                invoice.status = DocumentStatus.PARTIALLY_PAID
            invoice.updated_at = datetime.now(UTC)
            self._purchase_invoices[invoice_id] = invoice

            if self._event_publisher:
                try:
                    event = InvoicePaidEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice_id=invoice.id,
                        invoice_number=invoice.invoice_number,
                        invoice_type="purchase",
                        payment_amount=payment_amount,
                        paid_by=str(paid_by) if paid_by else "system",
                        user_id=str(paid_by) if paid_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published InvoicePaidEvent for {invoice.invoice_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish InvoicePaidEvent: {e}")

            if invoice.status == DocumentStatus.PARTIALLY_PAID:
                if self._event_publisher:
                    try:
                        event2 = InvoicePartiallyPaidEvent(
                            aggregate_id=invoice.id,
                            aggregate_version=1,
                            invoice_id=invoice.id,
                            invoice_number=invoice.invoice_number,
                            invoice_type="purchase",
                            paid_amount=invoice.paid_amount,
                            total_amount=invoice.total_amount,
                            paid_by=str(paid_by) if paid_by else "system",
                            user_id=str(paid_by) if paid_by else None,
                            correlation_id=correlation_id,
                        )
                        await self._event_publisher.publish(event2)
                    except Exception:
                        pass

            # Also publish PurchaseInvoicePaidEvent
            if self._event_publisher:
                try:
                    event3 = PurchaseInvoicePaidEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice=invoice,
                        payment_amount=payment_amount,
                        paid_by=str(paid_by) if paid_by else "system",
                        user_id=str(paid_by) if paid_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event3)
                except Exception:
                    pass

            return invoice
        return None

    async def cancel_purchase_invoice(
        self,
        invoice_id: UUID,
        cancelled_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status == DocumentStatus.PAID:
            raise PurchaseSalesServiceError("Cannot cancel a paid invoice")

        invoice.status = DocumentStatus.CANCELLED
        invoice.updated_at = datetime.now(UTC)
        invoice.cancel_reason = reason
        self._purchase_invoices[invoice_id] = invoice

        if self._event_publisher:
            try:
                event = InvoiceCancelledEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="purchase",
                    reason=reason,
                    cancelled_by=str(cancelled_by) if cancelled_by else "system",
                    user_id=str(cancelled_by) if cancelled_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published InvoiceCancelledEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceCancelledEvent: {e}")

        return invoice

    async def dispute_purchase_invoice(
        self,
        invoice_id: UUID,
        disputed_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.PAID, DocumentStatus.CANCELLED):
            raise PurchaseSalesServiceError(
                f"Cannot dispute invoice in status {invoice.status.value}"
            )

        invoice.status = DocumentStatus.DISPUTED
        invoice.updated_at = datetime.now(UTC)
        invoice.dispute_reason = reason
        self._purchase_invoices[invoice_id] = invoice

        if self._event_publisher:
            try:
                event = InvoiceDisputedEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="purchase",
                    reason=reason,
                    disputed_by=str(disputed_by) if disputed_by else "system",
                    user_id=str(disputed_by) if disputed_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published InvoiceDisputedEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceDisputedEvent: {e}")

        return invoice

    async def write_off_purchase_invoice(
        self,
        invoice_id: UUID,
        written_off_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        invoice.status = DocumentStatus.WRITTEN_OFF
        invoice.updated_at = datetime.now(UTC)
        invoice.write_off_reason = reason
        self._purchase_invoices[invoice_id] = invoice

        if self._event_publisher:
            try:
                event = InvoiceWrittenOffEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="purchase",
                    reason=reason,
                    written_off_by=str(written_off_by) if written_off_by else "system",
                    user_id=str(written_off_by) if written_off_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published InvoiceWrittenOffEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceWrittenOffEvent: {e}")

        return invoice

    # ========================================================================
    # Sales Order
    # ========================================================================

    async def create_sales_order(
        self,
        so_number: str,
        customer_id: UUID,
        customer_name: str,
        lines: list[dict[str, Any]],
        order_date: date | None = None,
        requested_delivery_date: date | None = None,
        currency: str = "IDR",
        notes: str | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> SalesOrder:
        logger.info(f"Creating sales order: {so_number}")

        so_lines = []
        for line in lines:
            so_lines.append(
                SalesOrderLine(
                    product_id=UUID(line["product_id"]),
                    product_code=line.get("product_code", ""),
                    product_name=line.get("product_name", ""),
                    quantity=Decimal(str(line["quantity"])),
                    unit_price=Decimal(str(line["unit_price"])),
                    discount_percentage=Decimal(str(line.get("discount_percentage", 0))),
                    tax_rate=Decimal(str(line.get("tax_rate", 11))),
                )
            )

        so = SalesOrder(
            so_number=so_number,
            customer_id=customer_id,
            customer_name=customer_name,
            order_date=order_date or date.today(),
            requested_delivery_date=requested_delivery_date,
            currency=currency,
            lines=so_lines,
            notes=notes,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
        )
        so.calculate_total()

        self._sales_orders[so.id] = so
        self._stats["so_created"] += 1

        if self._event_publisher:
            try:
                event = SalesOrderCreatedEvent(
                    aggregate_id=so.id,
                    aggregate_version=1,
                    sales_order=so,
                    created_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published SalesOrderCreatedEvent for {so.so_number}")
            except Exception as e:
                logger.warning(f"Failed to publish SalesOrderCreatedEvent: {e}")

        return so

    async def get_sales_order(self, so_id: UUID) -> SalesOrder | None:
        return self._sales_orders.get(so_id)

    async def list_sales_orders(
        self,
        customer_id: UUID | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        legal_entity_id: UUID | None = None,
    ) -> list[SalesOrder]:
        result = list(self._sales_orders.values())
        if customer_id:
            result = [so for so in result if so.customer_id == customer_id]
        if status:
            result = [so for so in result if so.status.value == status]
        if start_date:
            result = [so for so in result if so.order_date >= start_date]
        if end_date:
            result = [so for so in result if so.order_date <= end_date]
        if legal_entity_id:
            result = [so for so in result if so.legal_entity_id == legal_entity_id]
        return result

    async def update_sales_order(
        self,
        so_id: UUID,
        requested_delivery_date: date | None = None,
        notes: str | None = None,
        status: str | None = None,
    ) -> SalesOrder | None:
        so = self._sales_orders.get(so_id)
        if not so:
            raise SalesOrderNotFoundError(f"Sales order {so_id} not found")
        if requested_delivery_date:
            so.requested_delivery_date = requested_delivery_date
        if notes:
            so.notes = notes
        if status:
            so.status = OrderStatus(status)
        so.updated_at = datetime.now(UTC)
        self._sales_orders[so_id] = so
        return so

    async def submit_sales_order(self, so_id: UUID, submitted_by: UUID) -> bool:
        so = self._sales_orders.get(so_id)
        if not so:
            return False
        if so.status == OrderStatus.DRAFT:
            so.status = OrderStatus.SUBMITTED
            so.updated_at = datetime.now(UTC)
            self._sales_orders[so_id] = so
            return True
        return False

    async def approve_sales_order(
        self,
        so_id: UUID,
        approved_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        so = self._sales_orders.get(so_id)
        if not so:
            return False
        if so.status == OrderStatus.SUBMITTED:
            so.status = OrderStatus.APPROVED
            so.updated_at = datetime.now(UTC)
            self._sales_orders[so_id] = so

            if self._event_publisher:
                try:
                    event = SalesOrderApprovedEvent(
                        aggregate_id=so.id,
                        aggregate_version=1,
                        sales_order=so,
                        approved_by=str(approved_by) if approved_by else "system",
                        user_id=str(approved_by) if approved_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published SalesOrderApprovedEvent for {so.so_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish SalesOrderApprovedEvent: {e}")
            return True
        return False

    # ========================================================================
    # Delivery Note
    # ========================================================================

    async def create_delivery_note(
        self,
        sales_order_id: UUID,
        so_number: str,
        lines: list[dict[str, Any]],
        delivery_date: date | None = None,
        delivered_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> DeliveryNote:
        logger.info(f"Creating delivery note for SO {so_number}")

        dn_number = f"DN-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:8]}"

        dn_lines = []
        for line in lines:
            dn_lines.append(
                DeliveryNoteLine(
                    product_id=UUID(line["product_id"]),
                    product_code=line.get("product_code", ""),
                    product_name=line.get("product_name", ""),
                    ordered_quantity=Decimal(str(line.get("ordered_quantity", 0))),
                    delivered_quantity=Decimal(str(line["delivered_quantity"])),
                    unit_price=Decimal(str(line.get("unit_price", 0))),
                )
            )

        dn = DeliveryNote(
            dn_number=dn_number,
            sales_order_id=sales_order_id,
            so_number=so_number,
            delivery_date=delivery_date or date.today(),
            lines=dn_lines,
            delivered_by=delivered_by,
            legal_entity_id=legal_entity_id,
        )

        self._delivery_notes[dn.id] = dn
        self._stats["dn_created"] += 1

        if self._event_publisher:
            try:
                event = DeliveryNoteShippedEvent(
                    aggregate_id=dn.id,
                    aggregate_version=1,
                    delivery=dn,
                    shipped_by=str(delivered_by) if delivered_by else "system",
                    user_id=str(delivered_by) if delivered_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published DeliveryNoteShippedEvent for {dn.dn_number}")
            except Exception as e:
                logger.warning(f"Failed to publish DeliveryNoteShippedEvent: {e}")

        return dn

    async def get_delivery_note(self, dn_id: UUID) -> DeliveryNote | None:
        return self._delivery_notes.get(dn_id)

    async def list_delivery_notes(
        self, sales_order_id: UUID | None = None, status: str | None = None
    ) -> list[DeliveryNote]:
        result = list(self._delivery_notes.values())
        if sales_order_id:
            result = [dn for dn in result if dn.sales_order_id == sales_order_id]
        if status:
            result = [dn for dn in result if dn.status.value == status]
        return result

    # ========================================================================
    # Sales Invoice
    # ========================================================================

    async def create_sales_invoice(
        self,
        invoice_number: str,
        sales_order_id: UUID,
        total_amount: Decimal,
        lines: list[dict[str, Any]] | None = None,
        invoice_date: date | None = None,
        due_date: date | None = None,
        delivery_note_id: UUID | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> SalesInvoice:
        logger.info(f"Creating sales invoice {invoice_number}")

        invoice_lines = []
        if lines:
            for line in lines:
                invoice_lines.append(
                    InvoiceLine(
                        product_id=UUID(line["product_id"]),
                        product_code=line.get("product_code", ""),
                        product_name=line.get("product_name", ""),
                        quantity=Decimal(str(line.get("quantity", 0))),
                        unit_price=Decimal(str(line.get("unit_price", 0))),
                        discount_percentage=Decimal(str(line.get("discount_percentage", 0))),
                        tax_rate=Decimal(str(line.get("tax_rate", 11))),
                        total_amount=Decimal(str(line.get("total_amount", 0))),
                    )
                )

        invoice = SalesInvoice(
            invoice_number=invoice_number,
            sales_order_id=sales_order_id,
            delivery_note_id=delivery_note_id,
            invoice_date=invoice_date or date.today(),
            due_date=due_date,
            total_amount=total_amount,
            lines=invoice_lines,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
        )

        self._sales_invoices[invoice.id] = invoice
        self._stats["sales_invoices"] += 1

        # Publish InvoiceCreatedEvent (generic)
        if self._event_publisher:
            try:
                event = InvoiceCreatedEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="sales",
                    total_amount=invoice.total_amount,
                    created_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published InvoiceCreatedEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceCreatedEvent: {e}")

        # Publish InvoiceIssuedEvent (specific)
        if self._event_publisher:
            try:
                event2 = InvoiceIssuedEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="sales",
                    total_amount=invoice.total_amount,
                    issued_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event2)
                logger.debug(f"Published InvoiceIssuedEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceIssuedEvent: {e}")

        # Also publish SalesInvoiceIssuedEvent
        if self._event_publisher:
            try:
                event3 = SalesInvoiceIssuedEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice=invoice,
                    issued_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event3)
            except Exception:
                pass

        return invoice

    async def get_sales_invoice(self, invoice_id: UUID) -> SalesInvoice | None:
        return self._sales_invoices.get(invoice_id)

    async def list_sales_invoices(
        self, sales_order_id: UUID | None = None, status: str | None = None
    ) -> list[SalesInvoice]:
        result = list(self._sales_invoices.values())
        if sales_order_id:
            result = [inv for inv in result if inv.sales_order_id == sales_order_id]
        if status:
            result = [inv for inv in result if inv.status.value == status]
        return result

    async def approve_sales_invoice(
        self,
        invoice_id: UUID,
        approved_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        if invoice.status == DocumentStatus.ISSUED:
            invoice.status = DocumentStatus.APPROVED
            invoice.updated_at = datetime.now(UTC)
            self._sales_invoices[invoice_id] = invoice

            if self._event_publisher:
                try:
                    event = InvoiceApprovedEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice_id=invoice.id,
                        invoice_number=invoice.invoice_number,
                        invoice_type="sales",
                        approved_by=str(approved_by) if approved_by else "system",
                        user_id=str(approved_by) if approved_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published InvoiceApprovedEvent for {invoice.invoice_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish InvoiceApprovedEvent: {e}")

            return invoice
        return None

    async def verify_sales_invoice(
        self,
        invoice_id: UUID,
        verified_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.ISSUED, DocumentStatus.APPROVED):
            invoice.status = DocumentStatus.VERIFIED
            invoice.updated_at = datetime.now(UTC)
            self._sales_invoices[invoice_id] = invoice

            if self._event_publisher:
                try:
                    event = InvoiceVerifiedEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice_id=invoice.id,
                        invoice_number=invoice.invoice_number,
                        invoice_type="sales",
                        verified_by=str(verified_by) if verified_by else "system",
                        user_id=str(verified_by) if verified_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published InvoiceVerifiedEvent for {invoice.invoice_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish InvoiceVerifiedEvent: {e}")

            return invoice
        return None

    async def pay_sales_invoice(
        self,
        invoice_id: UUID,
        payment_amount: Decimal,
        paid_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.ISSUED, DocumentStatus.APPROVED, DocumentStatus.VERIFIED):
            invoice.paid_amount += payment_amount
            if invoice.paid_amount >= invoice.total_amount:
                invoice.status = DocumentStatus.PAID
            else:
                invoice.status = DocumentStatus.PARTIALLY_PAID
            invoice.updated_at = datetime.now(UTC)
            self._sales_invoices[invoice_id] = invoice

            if self._event_publisher:
                try:
                    event = InvoicePaidEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice_id=invoice.id,
                        invoice_number=invoice.invoice_number,
                        invoice_type="sales",
                        payment_amount=payment_amount,
                        paid_by=str(paid_by) if paid_by else "system",
                        user_id=str(paid_by) if paid_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                    logger.debug(f"Published InvoicePaidEvent for {invoice.invoice_number}")
                except Exception as e:
                    logger.warning(f"Failed to publish InvoicePaidEvent: {e}")

            if invoice.status == DocumentStatus.PARTIALLY_PAID:
                if self._event_publisher:
                    try:
                        event2 = InvoicePartiallyPaidEvent(
                            aggregate_id=invoice.id,
                            aggregate_version=1,
                            invoice_id=invoice.id,
                            invoice_number=invoice.invoice_number,
                            invoice_type="sales",
                            paid_amount=invoice.paid_amount,
                            total_amount=invoice.total_amount,
                            paid_by=str(paid_by) if paid_by else "system",
                            user_id=str(paid_by) if paid_by else None,
                            correlation_id=correlation_id,
                        )
                        await self._event_publisher.publish(event2)
                    except Exception:
                        pass

            # Also publish SalesInvoicePaidEvent
            if self._event_publisher:
                try:
                    event3 = SalesInvoicePaidEvent(
                        aggregate_id=invoice.id,
                        aggregate_version=1,
                        invoice=invoice,
                        payment_amount=payment_amount,
                        paid_by=str(paid_by) if paid_by else "system",
                        user_id=str(paid_by) if paid_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event3)
                except Exception:
                    pass

            return invoice
        return None

    async def cancel_sales_invoice(
        self,
        invoice_id: UUID,
        cancelled_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        if invoice.status == DocumentStatus.PAID:
            raise PurchaseSalesServiceError("Cannot cancel a paid invoice")

        invoice.status = DocumentStatus.CANCELLED
        invoice.updated_at = datetime.now(UTC)
        invoice.cancel_reason = reason
        self._sales_invoices[invoice_id] = invoice

        if self._event_publisher:
            try:
                event = InvoiceCancelledEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="sales",
                    reason=reason,
                    cancelled_by=str(cancelled_by) if cancelled_by else "system",
                    user_id=str(cancelled_by) if cancelled_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published InvoiceCancelledEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceCancelledEvent: {e}")

        return invoice

    async def dispute_sales_invoice(
        self,
        invoice_id: UUID,
        disputed_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.PAID, DocumentStatus.CANCELLED):
            raise PurchaseSalesServiceError(
                f"Cannot dispute invoice in status {invoice.status.value}"
            )

        invoice.status = DocumentStatus.DISPUTED
        invoice.updated_at = datetime.now(UTC)
        invoice.dispute_reason = reason
        self._sales_invoices[invoice_id] = invoice

        if self._event_publisher:
            try:
                event = InvoiceDisputedEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="sales",
                    reason=reason,
                    disputed_by=str(disputed_by) if disputed_by else "system",
                    user_id=str(disputed_by) if disputed_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published InvoiceDisputedEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceDisputedEvent: {e}")

        return invoice

    async def write_off_sales_invoice(
        self,
        invoice_id: UUID,
        written_off_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        invoice.status = DocumentStatus.WRITTEN_OFF
        invoice.updated_at = datetime.now(UTC)
        invoice.write_off_reason = reason
        self._sales_invoices[invoice_id] = invoice

        if self._event_publisher:
            try:
                event = InvoiceWrittenOffEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    invoice_type="sales",
                    reason=reason,
                    written_off_by=str(written_off_by) if written_off_by else "system",
                    user_id=str(written_off_by) if written_off_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published InvoiceWrittenOffEvent for {invoice.invoice_number}")
            except Exception as e:
                logger.warning(f"Failed to publish InvoiceWrittenOffEvent: {e}")

        return invoice

    # ========================================================================
    # Credit Note
    # ========================================================================

    async def create_credit_note(
        self,
        invoice_id: UUID,
        invoice_type: str,
        amount: Decimal,
        reason: str,
        credit_note_date: date | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CreditNote:
        logger.info(f"Creating credit note for invoice {invoice_id}")

        credit_note_number = f"CN-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:8]}"

        credit_note = CreditNote(
            credit_note_number=credit_note_number,
            invoice_id=invoice_id,
            invoice_type=invoice_type,
            credit_note_date=credit_note_date or date.today(),
            amount=amount,
            reason=reason,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
        )

        self._credit_notes[credit_note.id] = credit_note
        self._stats["credit_notes"] += 1

        # Publish CreditNoteIssuedEvent
        if self._event_publisher:
            try:
                event = CreditNoteIssuedEvent(
                    aggregate_id=credit_note.id,
                    aggregate_version=1,
                    credit_note_id=credit_note.id,
                    credit_note_number=credit_note.credit_note_number,
                    invoice_id=invoice_id,
                    invoice_type=invoice_type,
                    amount=amount,
                    reason=reason,
                    issued_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published CreditNoteIssuedEvent for {credit_note.credit_note_number}")
            except Exception as e:
                logger.warning(f"Failed to publish CreditNoteIssuedEvent: {e}")

        return credit_note

    async def receive_credit_note(
        self,
        credit_note_id: UUID,
        received_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CreditNote | None:
        credit_note = self._credit_notes.get(credit_note_id)
        if not credit_note:
            raise PurchaseSalesServiceError(f"Credit note {credit_note_id} not found")

        credit_note.status = DocumentStatus.RECEIVED
        credit_note.updated_at = datetime.now(UTC)
        self._credit_notes[credit_note_id] = credit_note

        if self._event_publisher:
            try:
                event = CreditNoteReceivedEvent(
                    aggregate_id=credit_note.id,
                    aggregate_version=1,
                    credit_note_id=credit_note.id,
                    credit_note_number=credit_note.credit_note_number,
                    invoice_id=credit_note.invoice_id,
                    invoice_type=credit_note.invoice_type,
                    amount=credit_note.amount,
                    received_by=str(received_by) if received_by else "system",
                    user_id=str(received_by) if received_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published CreditNoteReceivedEvent for {credit_note.credit_note_number}")
            except Exception as e:
                logger.warning(f"Failed to publish CreditNoteReceivedEvent: {e}")

        return credit_note

    async def apply_credit_note(
        self,
        credit_note_id: UUID,
        applied_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CreditNote | None:
        credit_note = self._credit_notes.get(credit_note_id)
        if not credit_note:
            raise PurchaseSalesServiceError(f"Credit note {credit_note_id} not found")

        credit_note.status = DocumentStatus.APPROVED
        credit_note.updated_at = datetime.now(UTC)
        self._credit_notes[credit_note_id] = credit_note

        if self._event_publisher:
            try:
                event = CreditNoteAppliedEvent(
                    aggregate_id=credit_note.id,
                    aggregate_version=1,
                    credit_note_id=credit_note.id,
                    credit_note_number=credit_note.credit_note_number,
                    invoice_id=credit_note.invoice_id,
                    invoice_type=credit_note.invoice_type,
                    amount=credit_note.amount,
                    applied_by=str(applied_by) if applied_by else "system",
                    user_id=str(applied_by) if applied_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published CreditNoteAppliedEvent for {credit_note.credit_note_number}")
            except Exception as e:
                logger.warning(f"Failed to publish CreditNoteAppliedEvent: {e}")

        return credit_note

    # ========================================================================
    # Debit Note
    # ========================================================================

    async def create_debit_note(
        self,
        invoice_id: UUID,
        invoice_type: str,
        amount: Decimal,
        reason: str,
        debit_note_date: date | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
        is_service: bool = False,
    ) -> DebitNote:
        logger.info(f"Creating debit note for invoice {invoice_id}")

        debit_note_number = f"DN-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:8]}"

        debit_note = DebitNote(
            debit_note_number=debit_note_number,
            invoice_id=invoice_id,
            invoice_type=invoice_type,
            debit_note_date=debit_note_date or date.today(),
            amount=amount,
            reason=reason,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
        )

        self._debit_notes[debit_note.id] = debit_note
        self._stats["debit_notes"] += 1

        # Publish event (DebitNoteIssuedEvent or DebitNoteIssuedServiceEvent)
        if self._event_publisher:
            try:
                if is_service:
                    event = DebitNoteIssuedServiceEvent(
                        aggregate_id=debit_note.id,
                        aggregate_version=1,
                        debit_note_id=debit_note.id,
                        debit_note_number=debit_note.debit_note_number,
                        invoice_id=invoice_id,
                        invoice_type=invoice_type,
                        amount=amount,
                        reason=reason,
                        issued_by=str(created_by) if created_by else "system",
                        user_id=str(created_by) if created_by else None,
                        correlation_id=correlation_id,
                    )
                else:
                    event = DebitNoteIssuedEvent(
                        aggregate_id=debit_note.id,
                        aggregate_version=1,
                        debit_note_id=debit_note.id,
                        debit_note_number=debit_note.debit_note_number,
                        invoice_id=invoice_id,
                        invoice_type=invoice_type,
                        amount=amount,
                        reason=reason,
                        issued_by=str(created_by) if created_by else "system",
                        user_id=str(created_by) if created_by else None,
                        correlation_id=correlation_id,
                    )
                await self._event_publisher.publish(event)
                logger.debug(f"Published DebitNoteIssuedEvent for {debit_note.debit_note_number}")
            except Exception as e:
                logger.warning(f"Failed to publish DebitNoteIssuedEvent: {e}")

        return debit_note

    async def apply_debit_note(
        self,
        debit_note_id: UUID,
        applied_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> DebitNote | None:
        debit_note = self._debit_notes.get(debit_note_id)
        if not debit_note:
            raise PurchaseSalesServiceError(f"Debit note {debit_note_id} not found")

        debit_note.status = DocumentStatus.APPROVED
        debit_note.updated_at = datetime.now(UTC)
        self._debit_notes[debit_note_id] = debit_note

        if self._event_publisher:
            try:
                event = DebitNoteAppliedEvent(
                    aggregate_id=debit_note.id,
                    aggregate_version=1,
                    debit_note_id=debit_note.id,
                    debit_note_number=debit_note.debit_note_number,
                    invoice_id=debit_note.invoice_id,
                    invoice_type=debit_note.invoice_type,
                    amount=debit_note.amount,
                    applied_by=str(applied_by) if applied_by else "system",
                    user_id=str(applied_by) if applied_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)
                logger.debug(f"Published DebitNoteAppliedEvent for {debit_note.debit_note_number}")
            except Exception as e:
                logger.warning(f"Failed to publish DebitNoteAppliedEvent: {e}")

        return debit_note

    # ========================================================================
    # Helpers
    # ========================================================================

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_purchase_sales_service(
    event_publisher: EventPublisherPort | None = None,
) -> PurchaseSalesService:
    return PurchaseSalesService(event_publisher=event_publisher)


__all__ = [
    "DeliveryNote",
    "DeliveryNoteNotFoundError",
    "DocumentStatus",
    "GoodsReceipt",
    "GoodsReceiptNotFoundError",
    "OrderStatus",
    "PurchaseInvoice",
    "PurchaseInvoiceNotFoundError",
    "PurchaseOrder",
    "PurchaseOrderNotFoundError",
    "PurchaseSalesService",
    "PurchaseSalesServiceError",
    "SalesInvoice",
    "SalesInvoiceNotFoundError",
    "SalesOrder",
    "SalesOrderNotFoundError",
    "CreditNote",
    "DebitNote",
    "create_purchase_sales_service",
]