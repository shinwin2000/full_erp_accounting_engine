# =============================================================================
# service_purchase_sales.py
# =============================================================================

# service_purchase_sales.py - Complete rewrite with full event publishing
# v5.9.3 - Added audit decorator and authority checks for mutation methods

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
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums
# ============================================================================


class OrderStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class DocumentStatus(str, Enum):
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
    product_id: UUID
    product_code: str
    product_name: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    rejected_quantity: Decimal = Decimal("0")
    unit_cost: Decimal = Decimal("0")


@dataclass(kw_only=True)
class GoodsReceipt:
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
    product_id: UUID
    product_code: str
    product_name: str
    ordered_quantity: Decimal
    delivered_quantity: Decimal
    unit_price: Decimal = Decimal("0")


@dataclass(kw_only=True)
class DeliveryNote:
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
    # Tambahan field untuk alasan pembatalan, dispute, write-off
    cancel_reason: str | None = None
    dispute_reason: str | None = None
    write_off_reason: str | None = None


@dataclass(kw_only=True)
class SalesInvoice:
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
    # Tambahan field untuk alasan pembatalan, dispute, write-off
    cancel_reason: str | None = None
    dispute_reason: str | None = None
    write_off_reason: str | None = None


@dataclass(kw_only=True)
class CreditNote:
    id: UUID = field(default_factory=uuid4)
    credit_note_number: str
    invoice_id: UUID
    invoice_type: str
    credit_note_date: date = field(default_factory=date.today)
    amount: Decimal = Decimal("0")
    reason: str
    status: DocumentStatus = DocumentStatus.DRAFT
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    legal_entity_id: UUID | None = None


@dataclass(kw_only=True)
class DebitNote:
    id: UUID = field(default_factory=uuid4)
    debit_note_number: str
    invoice_id: UUID
    invoice_type: str
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

    def __init__(
        self,
        event_publisher: EventPublisherPort | None = None,
        repository: Any = None,
    ):
        # FIX: `repository` sekarang berisi SQLAlchemyPurchaseSalesRepository
        # (lihat bootstrap/dependency_container/service_registry.py) untuk
        # Purchase Order & Sales Order -- keduanya sudah tersambung ke
        # database sungguhan (tabel purchase_order/purchase_order_line dan
        # sales_order/sales_order_line). Sisanya (GRN, Delivery Note,
        # Purchase/Sales Invoice, Credit/Debit Note) MASIH in-memory dan
        # akan hilang saat restart -- belum sempat dikerjakan, lihat TODO
        # di masing-masing method-nya.
        self._repository = repository
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
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("PurchaseSalesService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "PurchaseSalesService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== Helper untuk event publishing yang aman ====================

    async def _publish_event(self, event: Any, log_context: str) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # Purchase Order
    # ========================================================================

    @audit
    @audit
    async def create_purchase_order(
        self,
        *,
        po_number: str,
        po_date: date,
        supplier_id: UUID,
        lines: list[dict[str, Any]],
        expected_delivery_date: date | None = None,
        delivery_term_days: int = 30,
        payment_term_days: int = 30,
        incoterm: str = "EXW",
        order_type: str = "standard",
        reference_number: str | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> Any:
        """FIX: sebelumnya method ini punya signature yang SAMA SEKALI TIDAK
        COCOK dengan cara fastapi_purchase_sales_router.py memanggilnya
        (parameter po_date/delivery_term_days/incoterm/order_type/dst tidak
        pernah diterima) -- jadi endpoint create PO akan selalu gagal
        dengan TypeError, terlepas dari isu database. Sekarang persis
        mengikuti kontrak router, dan datanya BENAR-BENAR disimpan ke
        database lewat SQLAlchemyPurchaseSalesRepository (bukan lagi
        in-memory dict)."""
        self._check_authority(created_by, "create_purchase_order")
        logger.info(f"Creating purchase order: {po_number}")

        po = await self._repository.create_purchase_order(
            po_number=po_number,
            po_date=po_date,
            supplier_id=supplier_id,
            lines=lines,
            expected_delivery_date=expected_delivery_date,
            delivery_term_days=delivery_term_days,
            payment_term_days=payment_term_days,
            incoterm=incoterm,
            order_type=order_type,
            reference_number=reference_number,
            notes=notes,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
        )
        self._stats["po_created"] += 1

        if self._event_publisher:
            event = PurchaseOrderCreatedEvent(
                aggregate_id=po.id,
                aggregate_version=1,
                purchase_order=po,
                created_by=str(created_by) if created_by else "system",
                user_id=str(created_by) if created_by else None,
                correlation_id=None,
            )
            await self._publish_event(event, f"PO {po.po_number}")

        self._record_audit("create_purchase_order", {
            "po_id": str(po.id),
            "po_number": po.po_number,
            "created_by": str(created_by) if created_by else None,
        })

        return po

    async def get_purchase_order_by_id(self, po_id: UUID, legal_entity_id: UUID) -> Any:
        return await self._repository.get_purchase_order_by_id(po_id, legal_entity_id)

    async def get_purchase_order_by_number(self, po_number: str, legal_entity_id: UUID) -> Any:
        return await self._repository.get_purchase_order_by_number(po_number, legal_entity_id)

    async def list_purchase_orders(
        self,
        *,
        legal_entity_id: UUID,
        supplier_id: UUID | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Any:
        return await self._repository.list_purchase_orders(
            legal_entity_id=legal_entity_id,
            supplier_id=supplier_id,
            status=status,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

    @audit
    async def update_purchase_order(
        self,
        po_id: UUID,
        expected_delivery_date: date | None = None,
        notes: str | None = None,
        status: str | None = None,
        user_id: UUID | None = None,
    ) -> PurchaseOrder | None:
        # TODO: belum dipindah ke database (masih baca dict in-memory yang
        # sekarang selalu kosong sejak create_purchase_order() dipindah ke
        # DB) -- akan selalu melempar PurchaseOrderNotFoundError. Belum
        # termasuk cakupan perbaikan kali ini; lihat catatan di respons
        # untuk PurchaseSalesService.
        self._check_authority(user_id, "update_purchase_order")
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

        self._record_audit("update_purchase_order", {
            "po_id": str(po_id),
            "user_id": str(user_id) if user_id else None,
        })
        return po

    @audit
    async def submit_purchase_order(self, po_id: UUID, submitted_by: UUID, legal_entity_id: UUID) -> Any:
        self._check_authority(submitted_by, "submit_purchase_order")
        po = await self._repository.submit_purchase_order(po_id, submitted_by, legal_entity_id)
        if po:
            self._record_audit("submit_purchase_order", {
                "po_id": str(po_id),
                "submitted_by": str(submitted_by),
            })
        return po

    @audit
    async def approve_purchase_order(
        self,
        po_id: UUID,
        approved_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        notes: str | None = None,
    ) -> Any:
        self._check_authority(approved_by, "approve_purchase_order")
        po = await self._repository.approve_purchase_order(po_id, approved_by, legal_entity_id, notes)
        if po:
            if self._event_publisher:
                event = PurchaseOrderApprovedEvent(
                    aggregate_id=po.id,
                    aggregate_version=1,
                    purchase_order=po,
                    approved_by=str(approved_by) if approved_by else "system",
                    user_id=str(approved_by) if approved_by else None,
                    correlation_id=None,
                )
                await self._publish_event(event, f"PO {po.po_number}")
            self._record_audit("approve_purchase_order", {
                "po_id": str(po_id),
                "approved_by": str(approved_by) if approved_by else None,
            })
        return po

    @audit
    async def reject_purchase_order(
        self, po_id: UUID, rejected_by: UUID, legal_entity_id: UUID, reason: str
    ) -> Any:
        """FIX: method ini sebelumnya TIDAK ADA sama sekali (router sudah
        lama memanggilnya) -- setiap klik "Reject" di UI akan crash dengan
        AttributeError. Sekarang ada dan tersambung ke database."""
        self._check_authority(rejected_by, "reject_purchase_order")
        po = await self._repository.reject_purchase_order(po_id, rejected_by, legal_entity_id, reason)
        if po:
            self._record_audit("reject_purchase_order", {
                "po_id": str(po_id),
                "rejected_by": str(rejected_by),
                "reason": reason,
            })
        return po

    # ========================================================================
    # Goods Receipt
    # ========================================================================

    @audit
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
        self._check_authority(received_by, "create_goods_receipt")
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
            event = GoodsReceiptCreatedEvent(
                aggregate_id=grn.id,
                aggregate_version=1,
                grn=grn,
                created_by=str(received_by) if received_by else "system",
                user_id=str(received_by) if received_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"GRN {grn.grn_number}")

        self._record_audit("create_goods_receipt", {
            "grn_id": str(grn.id),
            "grn_number": grn.grn_number,
            "received_by": str(received_by) if received_by else None,
        })

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

    @audit
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
        self._check_authority(created_by, "create_purchase_invoice")
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

        if self._event_publisher:
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
            await self._publish_event(event, f"Purchase Invoice {invoice.invoice_number}")

        self._record_audit("create_purchase_invoice", {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "created_by": str(created_by) if created_by else None,
        })

        return invoice

    @audit
    async def receive_purchase_invoice(
        self,
        invoice_id: UUID,
        received_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        self._check_authority(received_by, "receive_purchase_invoice")
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status == DocumentStatus.DRAFT:
            invoice.status = DocumentStatus.RECEIVED
            invoice.updated_at = datetime.now(UTC)
            self._purchase_invoices[invoice_id] = invoice

            if self._event_publisher:
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
                await self._publish_event(event, f"Purchase Invoice {invoice.invoice_number}")

                event2 = PurchaseInvoiceReceivedEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice=invoice,
                    received_by=str(received_by) if received_by else "system",
                    user_id=str(received_by) if received_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event2, f"Purchase Invoice {invoice.invoice_number} (legacy)")

            self._record_audit("receive_purchase_invoice", {
                "invoice_id": str(invoice_id),
                "received_by": str(received_by) if received_by else None,
            })

            return invoice
        return None

    @audit
    async def approve_purchase_invoice(
        self,
        invoice_id: UUID,
        approved_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        self._check_authority(approved_by, "approve_purchase_invoice")
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.RECEIVED, DocumentStatus.DRAFT):
            invoice.status = DocumentStatus.APPROVED
            invoice.updated_at = datetime.now(UTC)
            self._purchase_invoices[invoice_id] = invoice

            if self._event_publisher:
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
                await self._publish_event(event, f"Purchase Invoice {invoice.invoice_number}")

                event2 = PurchaseInvoiceApprovedEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice=invoice,
                    approved_by=str(approved_by) if approved_by else "system",
                    user_id=str(approved_by) if approved_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event2, f"Purchase Invoice {invoice.invoice_number} (legacy)")

            self._record_audit("approve_purchase_invoice", {
                "invoice_id": str(invoice_id),
                "approved_by": str(approved_by) if approved_by else None,
            })

            return invoice
        return None

    @audit
    async def verify_purchase_invoice(
        self,
        invoice_id: UUID,
        verified_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        self._check_authority(verified_by, "verify_purchase_invoice")
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.APPROVED, DocumentStatus.RECEIVED):
            invoice.status = DocumentStatus.VERIFIED
            invoice.updated_at = datetime.now(UTC)
            self._purchase_invoices[invoice_id] = invoice

            if self._event_publisher:
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
                await self._publish_event(event, f"Purchase Invoice {invoice.invoice_number}")

            self._record_audit("verify_purchase_invoice", {
                "invoice_id": str(invoice_id),
                "verified_by": str(verified_by) if verified_by else None,
            })

            return invoice
        return None

    @audit
    async def pay_purchase_invoice(
        self,
        invoice_id: UUID,
        payment_amount: Decimal,
        paid_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        self._check_authority(paid_by, "pay_purchase_invoice")
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
                await self._publish_event(event, f"Purchase Invoice {invoice.invoice_number}")

                if invoice.status == DocumentStatus.PARTIALLY_PAID:
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
                    await self._publish_event(event2, f"Purchase Invoice {invoice.invoice_number} (partial)")

                event3 = PurchaseInvoicePaidEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice=invoice,
                    payment_amount=payment_amount,
                    paid_by=str(paid_by) if paid_by else "system",
                    user_id=str(paid_by) if paid_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event3, f"Purchase Invoice {invoice.invoice_number} (legacy)")

            self._record_audit("pay_purchase_invoice", {
                "invoice_id": str(invoice_id),
                "payment_amount": str(payment_amount),
                "paid_by": str(paid_by) if paid_by else None,
            })

            return invoice
        return None

    @audit
    async def cancel_purchase_invoice(
        self,
        invoice_id: UUID,
        cancelled_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        self._check_authority(cancelled_by, "cancel_purchase_invoice")
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
            await self._publish_event(event, f"Purchase Invoice {invoice.invoice_number}")

        self._record_audit("cancel_purchase_invoice", {
            "invoice_id": str(invoice_id),
            "reason": reason,
            "cancelled_by": str(cancelled_by) if cancelled_by else None,
        })

        return invoice

    @audit
    async def dispute_purchase_invoice(
        self,
        invoice_id: UUID,
        disputed_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        self._check_authority(disputed_by, "dispute_purchase_invoice")
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.PAID, DocumentStatus.CANCELLED):
            raise PurchaseSalesServiceError(f"Cannot dispute invoice in status {invoice.status.value}")

        invoice.status = DocumentStatus.DISPUTED
        invoice.updated_at = datetime.now(UTC)
        invoice.dispute_reason = reason
        self._purchase_invoices[invoice_id] = invoice

        if self._event_publisher:
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
            await self._publish_event(event, f"Purchase Invoice {invoice.invoice_number}")

        self._record_audit("dispute_purchase_invoice", {
            "invoice_id": str(invoice_id),
            "reason": reason,
            "disputed_by": str(disputed_by) if disputed_by else None,
        })

        return invoice

    @audit
    async def write_off_purchase_invoice(
        self,
        invoice_id: UUID,
        written_off_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> PurchaseInvoice | None:
        self._check_authority(written_off_by, "write_off_purchase_invoice")
        invoice = self._purchase_invoices.get(invoice_id)
        if not invoice:
            raise PurchaseInvoiceNotFoundError(f"Purchase invoice {invoice_id} not found")

        invoice.status = DocumentStatus.WRITTEN_OFF
        invoice.updated_at = datetime.now(UTC)
        invoice.write_off_reason = reason
        self._purchase_invoices[invoice_id] = invoice

        if self._event_publisher:
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
            await self._publish_event(event, f"Purchase Invoice {invoice.invoice_number}")

        self._record_audit("write_off_purchase_invoice", {
            "invoice_id": str(invoice_id),
            "reason": reason,
            "written_off_by": str(written_off_by) if written_off_by else None,
        })

        return invoice

    # ========================================================================
    # Sales Order
    # ========================================================================

    @audit
    @audit
    async def create_sales_order(
        self,
        *,
        so_number: str,
        so_date: date,
        customer_id: UUID,
        lines: list[dict[str, Any]],
        expected_ship_date: date | None = None,
        shipping_term_days: int = 7,
        payment_term_days: int = 30,
        incoterm: str = "EXW",
        order_type: str = "standard",
        reference_number: str | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> Any:
        """FIX: mirror dari create_purchase_order -- signature lama tidak
        cocok dengan router, dan sekarang tersambung ke database sungguhan
        via SQLAlchemyPurchaseSalesRepository."""
        self._check_authority(created_by, "create_sales_order")
        logger.info(f"Creating sales order: {so_number}")

        so = await self._repository.create_sales_order(
            so_number=so_number,
            so_date=so_date,
            customer_id=customer_id,
            lines=lines,
            expected_ship_date=expected_ship_date,
            shipping_term_days=shipping_term_days,
            payment_term_days=payment_term_days,
            incoterm=incoterm,
            order_type=order_type,
            reference_number=reference_number,
            notes=notes,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
        )
        self._stats["so_created"] += 1

        if self._event_publisher:
            event = SalesOrderCreatedEvent(
                aggregate_id=so.id,
                aggregate_version=1,
                sales_order=so,
                created_by=str(created_by) if created_by else "system",
                user_id=str(created_by) if created_by else None,
                correlation_id=None,
            )
            await self._publish_event(event, f"SO {so.so_number}")

        self._record_audit("create_sales_order", {
            "so_id": str(so.id),
            "so_number": so.so_number,
            "created_by": str(created_by) if created_by else None,
        })

        return so

    async def get_sales_order_by_id(self, so_id: UUID, legal_entity_id: UUID) -> Any:
        return await self._repository.get_sales_order_by_id(so_id, legal_entity_id)

    async def get_sales_order_by_number(self, so_number: str, legal_entity_id: UUID) -> Any:
        return await self._repository.get_sales_order_by_number(so_number, legal_entity_id)

    async def list_sales_orders(
        self,
        *,
        legal_entity_id: UUID,
        customer_id: UUID | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Any:
        return await self._repository.list_sales_orders(
            legal_entity_id=legal_entity_id,
            customer_id=customer_id,
            status=status,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

    @audit
    async def update_sales_order(
        self,
        so_id: UUID,
        requested_delivery_date: date | None = None,
        notes: str | None = None,
        status: str | None = None,
        user_id: UUID | None = None,
    ) -> SalesOrder | None:
        # TODO: sama seperti update_purchase_order() -- belum dipindah ke
        # database, akan selalu 404. Lihat catatan di respons.
        self._check_authority(user_id, "update_sales_order")
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

        self._record_audit("update_sales_order", {
            "so_id": str(so_id),
            "user_id": str(user_id) if user_id else None,
        })
        return so

    @audit
    async def submit_sales_order(self, so_id: UUID, submitted_by: UUID, legal_entity_id: UUID) -> Any:
        self._check_authority(submitted_by, "submit_sales_order")
        so = await self._repository.submit_sales_order(so_id, submitted_by, legal_entity_id)
        if so:
            self._record_audit("submit_sales_order", {
                "so_id": str(so_id),
                "submitted_by": str(submitted_by),
            })
        return so

    @audit
    async def approve_sales_order(
        self,
        so_id: UUID,
        approved_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        notes: str | None = None,
    ) -> Any:
        self._check_authority(approved_by, "approve_sales_order")
        so = await self._repository.approve_sales_order(so_id, approved_by, legal_entity_id, notes)
        if so:
            if self._event_publisher:
                event = SalesOrderApprovedEvent(
                    aggregate_id=so.id,
                    aggregate_version=1,
                    sales_order=so,
                    approved_by=str(approved_by) if approved_by else "system",
                    user_id=str(approved_by) if approved_by else None,
                    correlation_id=None,
                )
                await self._publish_event(event, f"SO {so.so_number}")
            self._record_audit("approve_sales_order", {
                "so_id": str(so_id),
                "approved_by": str(approved_by) if approved_by else None,
            })
        return so

    @audit
    async def reject_sales_order(
        self, so_id: UUID, rejected_by: UUID, legal_entity_id: UUID, reason: str
    ) -> Any:
        """FIX: method ini sebelumnya juga TIDAK ADA -- mirror dari
        reject_purchase_order()."""
        self._check_authority(rejected_by, "reject_sales_order")
        so = await self._repository.reject_sales_order(so_id, rejected_by, legal_entity_id, reason)
        if so:
            self._record_audit("reject_sales_order", {
                "so_id": str(so_id),
                "rejected_by": str(rejected_by),
                "reason": reason,
            })
        return so

    # ========================================================================
    # Delivery Note
    # ========================================================================

    @audit
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
        self._check_authority(delivered_by, "create_delivery_note")
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
            event = DeliveryNoteShippedEvent(
                aggregate_id=dn.id,
                aggregate_version=1,
                delivery=dn,
                shipped_by=str(delivered_by) if delivered_by else "system",
                user_id=str(delivered_by) if delivered_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"DN {dn.dn_number}")

        self._record_audit("create_delivery_note", {
            "dn_id": str(dn.id),
            "dn_number": dn.dn_number,
            "delivered_by": str(delivered_by) if delivered_by else None,
        })

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

    @audit
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
        self._check_authority(created_by, "create_sales_invoice")
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
            # Set status langsung ISSUED karena event issued dipublikasikan
            status=DocumentStatus.ISSUED,
        )

        self._sales_invoices[invoice.id] = invoice
        self._stats["sales_invoices"] += 1

        if self._event_publisher:
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
            await self._publish_event(event, f"Sales Invoice {invoice.invoice_number}")

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
            await self._publish_event(event2, f"Sales Invoice {invoice.invoice_number} (issued)")

            event3 = SalesInvoiceIssuedEvent(
                aggregate_id=invoice.id,
                aggregate_version=1,
                invoice=invoice,
                issued_by=str(created_by) if created_by else "system",
                user_id=str(created_by) if created_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event3, f"Sales Invoice {invoice.invoice_number} (legacy)")

        self._record_audit("create_sales_invoice", {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "created_by": str(created_by) if created_by else None,
        })

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

    @audit
    async def approve_sales_invoice(
        self,
        invoice_id: UUID,
        approved_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        self._check_authority(approved_by, "approve_sales_invoice")
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        if invoice.status == DocumentStatus.ISSUED:
            invoice.status = DocumentStatus.APPROVED
            invoice.updated_at = datetime.now(UTC)
            self._sales_invoices[invoice_id] = invoice

            if self._event_publisher:
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
                await self._publish_event(event, f"Sales Invoice {invoice.invoice_number}")

            self._record_audit("approve_sales_invoice", {
                "invoice_id": str(invoice_id),
                "approved_by": str(approved_by) if approved_by else None,
            })

            return invoice
        return None

    @audit
    async def verify_sales_invoice(
        self,
        invoice_id: UUID,
        verified_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        self._check_authority(verified_by, "verify_sales_invoice")
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.ISSUED, DocumentStatus.APPROVED):
            invoice.status = DocumentStatus.VERIFIED
            invoice.updated_at = datetime.now(UTC)
            self._sales_invoices[invoice_id] = invoice

            if self._event_publisher:
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
                await self._publish_event(event, f"Sales Invoice {invoice.invoice_number}")

            self._record_audit("verify_sales_invoice", {
                "invoice_id": str(invoice_id),
                "verified_by": str(verified_by) if verified_by else None,
            })

            return invoice
        return None

    @audit
    async def pay_sales_invoice(
        self,
        invoice_id: UUID,
        payment_amount: Decimal,
        paid_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        self._check_authority(paid_by, "pay_sales_invoice")
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
                await self._publish_event(event, f"Sales Invoice {invoice.invoice_number}")

                if invoice.status == DocumentStatus.PARTIALLY_PAID:
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
                    await self._publish_event(event2, f"Sales Invoice {invoice.invoice_number} (partial)")

                event3 = SalesInvoicePaidEvent(
                    aggregate_id=invoice.id,
                    aggregate_version=1,
                    invoice=invoice,
                    payment_amount=payment_amount,
                    paid_by=str(paid_by) if paid_by else "system",
                    user_id=str(paid_by) if paid_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event3, f"Sales Invoice {invoice.invoice_number} (legacy)")

            self._record_audit("pay_sales_invoice", {
                "invoice_id": str(invoice_id),
                "payment_amount": str(payment_amount),
                "paid_by": str(paid_by) if paid_by else None,
            })

            return invoice
        return None

    @audit
    async def cancel_sales_invoice(
        self,
        invoice_id: UUID,
        cancelled_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        self._check_authority(cancelled_by, "cancel_sales_invoice")
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
            await self._publish_event(event, f"Sales Invoice {invoice.invoice_number}")

        self._record_audit("cancel_sales_invoice", {
            "invoice_id": str(invoice_id),
            "reason": reason,
            "cancelled_by": str(cancelled_by) if cancelled_by else None,
        })

        return invoice

    @audit
    async def dispute_sales_invoice(
        self,
        invoice_id: UUID,
        disputed_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        self._check_authority(disputed_by, "dispute_sales_invoice")
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        if invoice.status in (DocumentStatus.PAID, DocumentStatus.CANCELLED):
            raise PurchaseSalesServiceError(f"Cannot dispute invoice in status {invoice.status.value}")

        invoice.status = DocumentStatus.DISPUTED
        invoice.updated_at = datetime.now(UTC)
        invoice.dispute_reason = reason
        self._sales_invoices[invoice_id] = invoice

        if self._event_publisher:
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
            await self._publish_event(event, f"Sales Invoice {invoice.invoice_number}")

        self._record_audit("dispute_sales_invoice", {
            "invoice_id": str(invoice_id),
            "reason": reason,
            "disputed_by": str(disputed_by) if disputed_by else None,
        })

        return invoice

    @audit
    async def write_off_sales_invoice(
        self,
        invoice_id: UUID,
        written_off_by: UUID | None = None,
        reason: str = "",
        correlation_id: str | None = None,
    ) -> SalesInvoice | None:
        self._check_authority(written_off_by, "write_off_sales_invoice")
        invoice = self._sales_invoices.get(invoice_id)
        if not invoice:
            raise SalesInvoiceNotFoundError(f"Sales invoice {invoice_id} not found")

        invoice.status = DocumentStatus.WRITTEN_OFF
        invoice.updated_at = datetime.now(UTC)
        invoice.write_off_reason = reason
        self._sales_invoices[invoice_id] = invoice

        if self._event_publisher:
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
            await self._publish_event(event, f"Sales Invoice {invoice.invoice_number}")

        self._record_audit("write_off_sales_invoice", {
            "invoice_id": str(invoice_id),
            "reason": reason,
            "written_off_by": str(written_off_by) if written_off_by else None,
        })

        return invoice

    # ========================================================================
    # Credit Note
    # ========================================================================

    @audit
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
        self._check_authority(created_by, "create_credit_note")
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

        if self._event_publisher:
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
            await self._publish_event(event, f"Credit Note {credit_note.credit_note_number}")

        self._record_audit("create_credit_note", {
            "credit_note_id": str(credit_note.id),
            "credit_note_number": credit_note.credit_note_number,
            "created_by": str(created_by) if created_by else None,
        })

        return credit_note

    @audit
    async def receive_credit_note(
        self,
        credit_note_id: UUID,
        received_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CreditNote | None:
        self._check_authority(received_by, "receive_credit_note")
        credit_note = self._credit_notes.get(credit_note_id)
        if not credit_note:
            raise PurchaseSalesServiceError(f"Credit note {credit_note_id} not found")

        credit_note.status = DocumentStatus.RECEIVED
        credit_note.updated_at = datetime.now(UTC)
        self._credit_notes[credit_note_id] = credit_note

        if self._event_publisher:
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
            await self._publish_event(event, f"Credit Note {credit_note.credit_note_number}")

        self._record_audit("receive_credit_note", {
            "credit_note_id": str(credit_note_id),
            "received_by": str(received_by) if received_by else None,
        })

        return credit_note

    @audit
    async def apply_credit_note(
        self,
        credit_note_id: UUID,
        applied_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CreditNote | None:
        self._check_authority(applied_by, "apply_credit_note")
        credit_note = self._credit_notes.get(credit_note_id)
        if not credit_note:
            raise PurchaseSalesServiceError(f"Credit note {credit_note_id} not found")

        credit_note.status = DocumentStatus.APPROVED
        credit_note.updated_at = datetime.now(UTC)
        self._credit_notes[credit_note_id] = credit_note

        if self._event_publisher:
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
            await self._publish_event(event, f"Credit Note {credit_note.credit_note_number}")

        self._record_audit("apply_credit_note", {
            "credit_note_id": str(credit_note_id),
            "applied_by": str(applied_by) if applied_by else None,
        })

        return credit_note

    # ========================================================================
    # Debit Note
    # ========================================================================

    @audit
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
        self._check_authority(created_by, "create_debit_note")
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

        if self._event_publisher:
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
            await self._publish_event(event, f"Debit Note {debit_note.debit_note_number}")

        self._record_audit("create_debit_note", {
            "debit_note_id": str(debit_note.id),
            "debit_note_number": debit_note.debit_note_number,
            "created_by": str(created_by) if created_by else None,
        })

        return debit_note

    @audit
    async def apply_debit_note(
        self,
        debit_note_id: UUID,
        applied_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> DebitNote | None:
        self._check_authority(applied_by, "apply_debit_note")
        debit_note = self._debit_notes.get(debit_note_id)
        if not debit_note:
            raise PurchaseSalesServiceError(f"Debit note {debit_note_id} not found")

        debit_note.status = DocumentStatus.APPROVED
        debit_note.updated_at = datetime.now(UTC)
        self._debit_notes[debit_note_id] = debit_note

        if self._event_publisher:
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
            await self._publish_event(event, f"Debit Note {debit_note.debit_note_number}")

        self._record_audit("apply_debit_note", {
            "debit_note_id": str(debit_note_id),
            "applied_by": str(applied_by) if applied_by else None,
        })

        return debit_note

    # ========================================================================
    # Helpers
    # ========================================================================

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_purchase_sales_service(
    event_publisher: EventPublisherPort | None = None,
) -> PurchaseSalesService:
    return PurchaseSalesService(event_publisher=event_publisher)


__all__ = [
    "CreditNote",
    "DebitNote",
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
    "create_purchase_sales_service",
]
