#!/usr/bin/env python3
"""
Module: test_sales_order.py
Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Sales Order aggregate root.
    Menguji pembuatan SO, approval, delivery, dan invoicing.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.purchase_sales.sales_order_aggregate import SalesOrderAggregate
from domain.purchase_sales.sales_order_entity import (
    SalesOrderEntity as SalesOrder,
)
from domain.purchase_sales.sales_order_entity import (
    SOItem as SalesOrderLine,
)
from domain.purchase_sales.sales_order_entity import (
    SOStatus as SalesOrderStatus,
)
from domain.purchase_sales.sales_order_entity import (
    SOType as SalesOrderType,
)
from domain.shared_value_objects.document_number_vo import DocumentNumber


class TestSalesOrderAggregate:
    """Test suite untuk Sales Order aggregate."""

    @pytest.fixture
    def valid_so_lines(self) -> list[SalesOrderLine]:
        return [
            SalesOrderLine(
                id=uuid4(),
                product_id=uuid4(),
                product_code="PROD-001",
                product_name="Produk A",
                quantity=Decimal("10"),
                unit_price=Decimal("75000"),
                total_price=Decimal("750000"),
                delivered_quantity=Decimal("0"),
                tax_rate=Decimal("0.11"),
                tax_amount=Decimal("82500"),
                discount_percent=Decimal("0"),
                discount_amount=Decimal("0"),
                line_total=Decimal("832500"),
            ),
        ]

    @pytest.fixture
    def valid_so(self, valid_so_lines) -> SalesOrder:
        return SalesOrder(
            id=uuid4(),
            legal_entity_id=uuid4(),
            so_number=DocumentNumber("SO-2025-00001"),
            customer_id=uuid4(),
            customer_name="PT Customer",
            order_date=date(2025, 3, 1),
            requested_delivery_date=date(2025, 3, 10),
            status=SalesOrderStatus.DRAFT,
            so_type=SalesOrderType.STANDARD,
            lines=valid_so_lines,
            total_amount=Decimal("750000"),
            tax_total=Decimal("82500"),
            grand_total=Decimal("832500"),
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )

    def test_create_so_success(self, valid_so):
        aggregate = SalesOrderAggregate.create(valid_so, user_id=uuid4())
        assert aggregate.so.id == valid_so.id
        assert aggregate.so.status == SalesOrderStatus.DRAFT
        events = aggregate.get_events()
        assert len(events) == 1

    def test_submit_so(self, valid_so):
        aggregate = SalesOrderAggregate.create(valid_so, uuid4())
        aggregate.submit(uuid4())
        assert aggregate.so.status == SalesOrderStatus.PENDING_APPROVAL

    def test_approve_so(self, valid_so):
        aggregate = SalesOrderAggregate.create(valid_so, uuid4())
        aggregate.submit(uuid4())
        aggregate.approve(approver_id=uuid4())
        assert aggregate.so.status == SalesOrderStatus.APPROVED

    def test_deliver_goods_partial(self, valid_so):
        aggregate = SalesOrderAggregate.create(valid_so, uuid4())
        aggregate.approve(uuid4())
        aggregate.deliver(line_id=valid_so.lines[0].id, quantity=Decimal("5"), user_id=uuid4())
        assert valid_so.lines[0].delivered_quantity == Decimal("5")
        assert aggregate.so.status == SalesOrderStatus.PARTIALLY_DELIVERED

    def test_deliver_goods_complete(self, valid_so):
        aggregate = SalesOrderAggregate.create(valid_so, uuid4())
        aggregate.approve(uuid4())
        aggregate.deliver(valid_so.lines[0].id, Decimal("10"), uuid4())
        assert aggregate.so.status == SalesOrderStatus.FULLY_DELIVERED

    def test_cannot_deliver_more_than_ordered(self, valid_so):
        aggregate = SalesOrderAggregate.create(valid_so, uuid4())
        aggregate.approve(uuid4())
        with pytest.raises(ValueError, match="exceeds ordered quantity"):
            aggregate.deliver(valid_so.lines[0].id, Decimal("15"), uuid4())

    def test_cancel_so_before_approval(self, valid_so):
        aggregate = SalesOrderAggregate.create(valid_so, uuid4())
        aggregate.cancel(reason="Customer request", user_id=uuid4())
        assert aggregate.so.status == SalesOrderStatus.CANCELLED

    def test_invoice_generation_flag(self, valid_so):
        aggregate = SalesOrderAggregate.create(valid_so, uuid4())
        aggregate.approve(uuid4())
        aggregate.deliver(valid_so.lines[0].id, Decimal("10"), uuid4())
        assert aggregate.can_invoice() is True
        aggregate.mark_invoiced(invoice_id=uuid4())
        assert aggregate.so.invoiced is True
