#!/usr/bin/env python3
"""
Module: test_purchase_order.py
Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Purchase Order aggregate root.
    Menguji pembuatan PO, approval, penerimaan barang, dan perubahan status.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.purchase_sales.purchase_order_aggregate import PurchaseOrderAggregate
from domain.purchase_sales.purchase_order_entity import (
    POItem as PurchaseOrderLine,
)
from domain.purchase_sales.purchase_order_entity import (
    POStatus as PurchaseOrderStatus,
)
from domain.purchase_sales.purchase_order_entity import (
    POType as PurchaseOrderType,
)
from domain.purchase_sales.purchase_order_entity import (
    PurchaseOrderEntity as PurchaseOrder,
)
from domain.shared_value_objects.document_number_vo import DocumentNumber


class TestPurchaseOrderAggregate:
    """Test suite untuk Purchase Order aggregate."""

    @pytest.fixture
    def valid_po_lines(self) -> list[PurchaseOrderLine]:
        return [
            PurchaseOrderLine(
                id=uuid4(),
                product_id=uuid4(),
                product_code="PROD-001",
                product_name="Produk A",
                quantity=Decimal("10"),
                unit_price=Decimal("50000"),
                total_price=Decimal("500000"),
                received_quantity=Decimal("0"),
                tax_rate=Decimal("0.11"),
                tax_amount=Decimal("55000"),
                discount_percent=Decimal("0"),
                discount_amount=Decimal("0"),
                line_total=Decimal("555000"),
            ),
            PurchaseOrderLine(
                id=uuid4(),
                product_id=uuid4(),
                product_code="PROD-002",
                product_name="Produk B",
                quantity=Decimal("5"),
                unit_price=Decimal("100000"),
                total_price=Decimal("500000"),
                received_quantity=Decimal("0"),
                tax_rate=Decimal("0.11"),
                tax_amount=Decimal("55000"),
                discount_percent=Decimal("0"),
                discount_amount=Decimal("0"),
                line_total=Decimal("555000"),
            ),
        ]

    @pytest.fixture
    def valid_po(self, valid_po_lines) -> PurchaseOrder:
        return PurchaseOrder(
            id=uuid4(),
            legal_entity_id=uuid4(),
            po_number=DocumentNumber("PO-2025-00001"),
            supplier_id=uuid4(),
            supplier_name="PT Supplier",
            order_date=date(2025, 3, 1),
            expected_delivery_date=date(2025, 3, 15),
            status=PurchaseOrderStatus.DRAFT,
            po_type=PurchaseOrderType.STANDARD,
            lines=valid_po_lines,
            total_amount=Decimal("1000000"),
            tax_total=Decimal("110000"),
            grand_total=Decimal("1110000"),
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )

    def test_create_po_success(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, user_id=uuid4())
        assert aggregate.po.id == valid_po.id
        assert aggregate.po.status == PurchaseOrderStatus.DRAFT
        assert aggregate.version == 1
        events = aggregate.get_events()
        assert len(events) == 1
        assert events[0].po_id == valid_po.id

    def test_submit_po_for_approval(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        aggregate.submit(user_id=uuid4())
        assert aggregate.po.status == PurchaseOrderStatus.PENDING_APPROVAL

    def test_approve_po(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        aggregate.submit(uuid4())
        aggregate.approve(approver_id=uuid4())
        assert aggregate.po.status == PurchaseOrderStatus.APPROVED

    def test_reject_po(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        aggregate.submit(uuid4())
        aggregate.reject(reason="Budget not available", user_id=uuid4())
        assert aggregate.po.status == PurchaseOrderStatus.REJECTED

    def test_receive_goods_partial(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        aggregate.approve(uuid4())
        aggregate.receive_goods(
            line_id=valid_po.lines[0].id, quantity=Decimal("5"), user_id=uuid4()
        )
        assert valid_po.lines[0].received_quantity == Decimal("5")
        assert aggregate.po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED

    def test_receive_goods_complete(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        aggregate.approve(uuid4())
        for line in valid_po.lines:
            aggregate.receive_goods(line.id, line.quantity, uuid4())
        assert aggregate.po.status == PurchaseOrderStatus.FULLY_RECEIVED

    def test_cannot_receive_more_than_ordered(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        aggregate.approve(uuid4())
        with pytest.raises(ValueError, match="exceeds ordered quantity"):
            aggregate.receive_goods(valid_po.lines[0].id, Decimal("20"), uuid4())

    def test_cancel_po_before_approval(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        aggregate.cancel(reason="Change of mind", user_id=uuid4())
        assert aggregate.po.status == PurchaseOrderStatus.CANCELLED

    def test_cannot_cancel_approved_po_with_receipt(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        aggregate.approve(uuid4())
        aggregate.receive_goods(valid_po.lines[0].id, Decimal("1"), uuid4())
        with pytest.raises(ValueError, match="Cannot cancel PO with existing receipts"):
            aggregate.cancel("Reason", uuid4())

    def test_version_increment(self, valid_po):
        aggregate = PurchaseOrderAggregate.create(valid_po, uuid4())
        assert aggregate.version == 1
        aggregate.submit(uuid4())
        assert aggregate.version == 2
        aggregate.approve(uuid4())
        assert aggregate.version == 3
