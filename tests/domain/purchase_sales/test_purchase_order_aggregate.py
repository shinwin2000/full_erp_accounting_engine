# test_purchase_order_aggregate.py
# =================================
# Comprehensive tests for domain/purchase_sales/purchase_order_aggregate.py.
# Covers all public methods, edge cases, decimal precision, and event sourcing.

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.purchase_sales.domain_events import (
    GoodsReceiptCreatedEvent,
    PurchaseOrderApprovedEvent,
    PurchaseOrderCreatedEvent,
)
from domain.purchase_sales.goods_receipt_note_entity import (
    GoodsReceiptNoteEntity,
    GRNItem,
    GRNStatus,
)
from domain.purchase_sales.purchase_order_aggregate import (
    PurchaseOrderAggregate,
    PurchaseOrderRepository,
)
from domain.purchase_sales.purchase_order_entity import POStatus, PurchaseOrderEntity

# =============================================================================
# FALLBACK: Define POLine locally if not available in module
# =============================================================================
try:
    from domain.purchase_sales.purchase_order_entity import POLine
except ImportError:
    from dataclasses import dataclass

    @dataclass
    class POLine:
        line_id: UUID
        item_id: UUID
        item_code: str
        item_name: str
        quantity: Decimal
        unit_price: Decimal
        received_quantity: Decimal
        currency: str
        expected_delivery_date: datetime
        notes: str | None = None
        tax_rate: Decimal = Decimal("0")
        discount: Decimal = Decimal("0")
        total_amount: Decimal | None = None

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def po_id() -> UUID:
    return uuid4()


@pytest.fixture
def item_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_po_line(item_id) -> POLine:
    return POLine(
        line_id=uuid4(),
        item_id=item_id,
        item_code="ITEM-001",
        item_name="Test Item",
        quantity=Decimal("10"),
        unit_price=Decimal("1000"),
        received_quantity=Decimal("0"),
        currency="IDR",
        expected_delivery_date=datetime(2025, 1, 15, tzinfo=UTC),
    )


@pytest.fixture
def sample_po(sample_po_line, po_id, legal_entity_id) -> PurchaseOrderEntity:
    return PurchaseOrderEntity(
        po_id=po_id,
        po_number="PO-001",
        legal_entity_id=legal_entity_id,
        supplier_id=uuid4(),
        supplier_name="Supplier X",
        order_date=date(2025, 1, 1),
        expected_delivery_date=date(2025, 1, 15),
        currency="IDR",
        status=POStatus.DRAFT,
        lines=[sample_po_line],
        created_by="tester",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        version=1,
    )


@pytest.fixture
def sample_grn(sample_po, item_id) -> GoodsReceiptNoteEntity:
    grn_item = GRNItem(
        item_id=item_id,
        item_code="ITEM-001",
        item_name="Test Item",
        quantity=Decimal("5"),
        unit_cost=Decimal("1000"),
        description="Test receipt",
    )
    return GoodsReceiptNoteEntity(
        grn_id=uuid4(),
        grn_number="GRN-001",
        po_id=sample_po.po_id,
        po_number=sample_po.po_number,
        receipt_date=date(2025, 1, 5),
        items=[grn_item],
        status=GRNStatus.CONFIRMED,
        received_by=uuid4(),
        legal_entity_id=sample_po.legal_entity_id,
        created_by="tester",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        version=1,
    )


@pytest.fixture
def aggregate(legal_entity_id) -> PurchaseOrderAggregate:
    return PurchaseOrderAggregate.create(legal_entity_id, "tester")


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - Construction & Factory Methods
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregateConstruction:
    def test_create_success(self, legal_entity_id):
        agg = PurchaseOrderAggregate.create(legal_entity_id, "tester")
        assert agg.aggregate_id is not None
        assert agg.legal_entity_id == legal_entity_id
        assert agg.version == 1
        assert agg.is_locked is False
        assert agg.purchase_orders == {}
        assert agg.goods_receipts == {}
        assert len(agg.get_audit_trail()) == 1
        audit = agg.get_audit_trail()[0]
        assert audit["action"] == "CREATE"

    def test_validation_version_zero_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            PurchaseOrderAggregate(
                aggregate_id=uuid4(),
                legal_entity_id=legal_entity_id,
                version=0,
            )

    def test_validation_naive_timestamps_raises(self, legal_entity_id):
        naive = datetime(2025, 1, 1, 10, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            PurchaseOrderAggregate(
                aggregate_id=uuid4(),
                legal_entity_id=legal_entity_id,
                created_at=naive,
                updated_at=naive,
            )


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - Event Management
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregateEvents:
    def test_add_event_and_get_events(self, aggregate):
        event = MagicMock(spec=PurchaseOrderCreatedEvent)
        event.event_type = MagicMock()
        event.event_type.value = "test_event"
        aggregate._add_event(event)
        events = aggregate.get_events()
        assert len(events) == 1
        assert events[0] is event
        assert len(aggregate._audit_trail) == 2

    def test_clear_events(self, aggregate):
        event = MagicMock()
        aggregate._add_event(event)
        assert len(aggregate.get_events()) == 1
        aggregate.clear_events()
        assert len(aggregate.get_events()) == 0
        assert len(aggregate._audit_trail) == 3

    def test_pop_events(self, aggregate):
        e1 = MagicMock()
        e2 = MagicMock()
        aggregate._add_event(e1)
        aggregate._add_event(e2)
        popped = aggregate.pop_events()
        assert len(popped) == 2
        assert popped[0] is e1
        assert popped[1] is e2
        assert len(aggregate.get_events()) == 0

    def test_pull_events(self, aggregate):
        e1 = MagicMock()
        aggregate._add_event(e1)
        pulled = aggregate.pull_events()
        assert len(pulled) == 1
        assert pulled[0] is e1
        assert len(aggregate.get_events()) == 0

    def test_register_event(self, aggregate):
        event = MagicMock()
        aggregate.register_event(event)
        events = aggregate.get_events()
        assert len(events) == 1
        assert events[0] is event

    def test_apply_event(self, aggregate):
        event = MagicMock()
        aggregate.apply(event)
        events = aggregate.get_events()
        assert len(events) == 1
        assert events[0] is event


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - Event Sourcing (from_events, replay)
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregateEventSourcing:
    def test_from_events(self, sample_po, legal_entity_id):
        agg_id = uuid4()
        event = PurchaseOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            purchase_order=sample_po,
            created_by="tester",
        )
        agg = PurchaseOrderAggregate.from_events(agg_id, legal_entity_id, [event])
        assert agg.aggregate_id == agg_id
        assert agg.legal_entity_id == legal_entity_id
        assert agg.version == 2
        assert len(agg.get_events()) == 1

    def test_replay_events(self, aggregate, sample_po):
        agg_id = aggregate.aggregate_id
        event = PurchaseOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            purchase_order=sample_po,
            created_by="tester",
        )
        aggregate.replay_events([event])
        assert aggregate.version == 2
        assert len(aggregate.get_events()) == 1
        audit = aggregate.get_audit_trail()
        assert any(a["action"] == "REPLAY_EVENTS" for a in audit)

    def test_replay(self, aggregate, sample_po):
        agg_id = aggregate.aggregate_id
        event = PurchaseOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            purchase_order=sample_po,
            created_by="tester",
        )
        aggregate.replay([event])
        assert aggregate.version == 2
        assert len(aggregate.get_events()) == 1


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - Lock/Unlock
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregateLock:
    def test_lock_success(self, aggregate):
        user = "alice"
        agg = aggregate.lock(user, "audit reason")
        assert agg.is_locked is True
        assert agg._locked_by == user
        assert agg._locked_at is not None
        audit = agg.get_audit_trail()
        assert any(a["action"] == "locked" for a in audit)

    def test_lock_already_locked_raises(self, aggregate):
        aggregate.lock("alice")
        with pytest.raises(ValueError, match="already locked"):
            aggregate.lock("bob")

    def test_unlock_success(self, aggregate):
        aggregate.lock("alice")
        agg = aggregate.unlock("alice")
        assert agg.is_locked is False
        assert agg._locked_by is None
        assert agg._locked_at is None
        audit = agg.get_audit_trail()
        assert any(a["action"] == "unlocked" for a in audit)

    def test_unlock_not_locked_raises(self, aggregate):
        with pytest.raises(ValueError, match="not locked"):
            aggregate.unlock("alice")

    def test_unlock_wrong_user_raises(self, aggregate):
        aggregate.lock("alice")
        with pytest.raises(ValueError, match="locked by alice"):
            aggregate.unlock("bob")


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - Snapshot & Audit Trail
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregateAudit:
    def test_snapshot(self, aggregate):
        snap = aggregate.snapshot()
        assert snap["aggregate_id"] == str(aggregate.aggregate_id)
        assert snap["aggregate_type"] == "PurchaseOrderAggregate"
        assert snap["version"] == aggregate.version
        assert "timestamp" in snap
        assert "state" in snap
        assert snap["state"]["legal_entity_id"] == str(aggregate.legal_entity_id)
        assert snap["hash"] is not None
        assert len(aggregate._snapshots) == 1
        audit = aggregate.get_audit_trail()
        assert any(a["action"] == "snapshot_created" for a in audit)

    def test_get_audit_trail(self, aggregate):
        aggregate._record_audit("TEST", {"key": "value"})
        trail = aggregate.get_audit_trail()
        assert len(trail) == 2
        assert trail[-1]["action"] == "TEST"
        assert trail[-1]["details"] == {"key": "value"}

    def test_increment_version(self, aggregate):
        old_version = aggregate.version
        old_updated = aggregate.updated_at
        aggregate.increment_version()
        assert aggregate.version == old_version + 1
        assert aggregate.updated_at > old_updated


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - Purchase Order Management
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregatePO:
    def test_add_purchase_order_success(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        assert sample_po.po_id in agg.purchase_orders
        assert agg.purchase_orders[sample_po.po_id] is sample_po
        assert agg.version == 2
        events = agg.get_events()
        assert len(events) == 1
        assert isinstance(events[0], PurchaseOrderCreatedEvent)
        assert events[0].purchase_order is sample_po
        audit = agg.get_audit_trail()
        assert any(a["action"] == "ADD_PURCHASE_ORDER" for a in audit)

    def test_add_purchase_order_duplicate_id_raises(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        with pytest.raises(ValueError, match="already exists"):
            agg.add_purchase_order(sample_po, "tester")

    def test_add_purchase_order_duplicate_number_raises(self, aggregate, sample_po):
        po2 = PurchaseOrderEntity(
            po_id=uuid4(),
            po_number="PO-001",
            legal_entity_id=sample_po.legal_entity_id,
            supplier_id=uuid4(),
            supplier_name="Supplier Y",
            order_date=date.today(),
            currency="IDR",
            status=POStatus.DRAFT,
            lines=[],
            created_by="tester",
        )
        agg = aggregate.add_purchase_order(sample_po, "tester")
        with pytest.raises(ValueError, match="already exists"):
            agg.add_purchase_order(po2, "tester")

    def test_add_purchase_order_locked_raises(self, aggregate, sample_po):
        agg = aggregate.lock("alice")
        with pytest.raises(ValueError, match="Cannot add PO to locked aggregate"):
            agg.add_purchase_order(sample_po, "tester")

    def test_update_purchase_order_success(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        updated_po = sample_po.update_notes("New notes", "updater")
        agg2 = agg.update_purchase_order(updated_po, "updater")
        assert agg2.purchase_orders[sample_po.po_id] is updated_po
        assert agg2.version == 3
        audit = agg2.get_audit_trail()
        assert any(a["action"] == "UPDATE_PURCHASE_ORDER" for a in audit)

    def test_update_purchase_order_not_found_raises(self, aggregate, sample_po):
        with pytest.raises(ValueError, match="not found"):
            aggregate.update_purchase_order(sample_po, "tester")

    def test_update_purchase_order_locked_raises(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester").lock("alice")
        with pytest.raises(ValueError, match="Cannot update PO in locked aggregate"):
            agg.update_purchase_order(sample_po, "tester")

    def test_approve_purchase_order_success(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg2 = agg.approve_purchase_order(sample_po.po_id, "approver")
        approved_po = agg2.purchase_orders[sample_po.po_id]
        assert approved_po.status == POStatus.APPROVED
        assert agg2.version == 3
        events = agg2.get_events()
        assert len(events) == 2
        assert isinstance(events[-1], PurchaseOrderApprovedEvent)
        assert events[-1].purchase_order is approved_po
        audit = agg2.get_audit_trail()
        assert any(a["action"] == "APPROVE_PURCHASE_ORDER" for a in audit)

    def test_approve_purchase_order_not_found_raises(self, aggregate):
        with pytest.raises(ValueError, match="not found"):
            aggregate.approve_purchase_order(uuid4(), "approver")

    def test_approve_purchase_order_locked_raises(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester").lock("alice")
        with pytest.raises(ValueError, match="Cannot approve PO in locked aggregate"):
            agg.approve_purchase_order(sample_po.po_id, "approver")

    def test_cancel_purchase_order_success(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg2 = agg.cancel_purchase_order(sample_po.po_id, "No need", "canceller")
        cancelled_po = agg2.purchase_orders[sample_po.po_id]
        assert cancelled_po.status == POStatus.CANCELLED
        assert agg2.version == 3
        audit = agg2.get_audit_trail()
        assert any(a["action"] == "CANCEL_PURCHASE_ORDER" for a in audit)

    def test_cancel_purchase_order_not_found_raises(self, aggregate):
        with pytest.raises(ValueError, match="not found"):
            aggregate.cancel_purchase_order(uuid4(), "reason", "user")

    def test_cancel_purchase_order_locked_raises(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester").lock("alice")
        with pytest.raises(ValueError, match="Cannot cancel PO in locked aggregate"):
            agg.cancel_purchase_order(sample_po.po_id, "reason", "user")

    def test_get_purchase_order(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        assert agg.get_purchase_order(sample_po.po_id) is sample_po
        assert agg.get_purchase_order(uuid4()) is None

    def test_get_purchase_order_by_number(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        found = agg.get_purchase_order_by_number("PO-001")
        assert found is sample_po
        assert agg.get_purchase_order_by_number("NONEXISTENT") is None

    def test_get_open_purchase_orders(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        open_pos = agg.get_open_purchase_orders()
        assert len(open_pos) == 0
        agg2 = agg.approve_purchase_order(sample_po.po_id, "approver")
        open_pos = agg2.get_open_purchase_orders()
        assert len(open_pos) == 1
        assert open_pos[0].po_id == sample_po.po_id

    def test_get_overdue_purchase_orders(self, aggregate, sample_po):
        past_po = PurchaseOrderEntity(
            po_id=uuid4(),
            po_number="PO-OVERDUE",
            legal_entity_id=sample_po.legal_entity_id,
            supplier_id=uuid4(),
            supplier_name="Supplier",
            order_date=date(2024, 12, 1),
            expected_delivery_date=date(2024, 12, 31),
            currency="IDR",
            status=POStatus.APPROVED,
            lines=[sample_po.lines[0]],
            created_by="tester",
        )
        agg = aggregate.add_purchase_order(past_po, "tester")
        agg = agg.approve_purchase_order(past_po.po_id, "approver")
        overdue = agg.get_overdue_purchase_orders()
        assert len(overdue) == 1
        assert overdue[0].po_id == past_po.po_id

        future_po = PurchaseOrderEntity(
            po_id=uuid4(),
            po_number="PO-FUTURE",
            legal_entity_id=sample_po.legal_entity_id,
            supplier_id=uuid4(),
            supplier_name="Supplier",
            order_date=date(2025, 1, 1),
            expected_delivery_date=date(2025, 2, 1),
            currency="IDR",
            status=POStatus.APPROVED,
            lines=[sample_po.lines[0]],
            created_by="tester",
        )
        agg2 = agg.add_purchase_order(future_po, "tester")
        agg2 = agg2.approve_purchase_order(future_po.po_id, "approver")
        overdue2 = agg2.get_overdue_purchase_orders(as_of=datetime(2025, 1, 15, tzinfo=UTC))
        assert len(overdue2) == 1
        assert overdue2[0].po_id == past_po.po_id


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - Goods Receipt Management
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregateGRN:
    def test_add_goods_receipt_success(self, aggregate, sample_po, sample_grn):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg = agg.approve_purchase_order(sample_po.po_id, "approver")
        agg2 = agg.add_goods_receipt(sample_grn, "tester")
        assert sample_grn.grn_id in agg2.goods_receipts
        assert agg2.goods_receipts[sample_grn.grn_id] is sample_grn
        updated_po = agg2.purchase_orders[sample_po.po_id]
        assert updated_po.status == POStatus.PARTIALLY_RECEIVED
        line = updated_po.lines[0]
        assert line.received_quantity == Decimal("5")
        assert agg2.version == 4
        events = agg2.get_events()
        assert len(events) == 3
        assert isinstance(events[-1], GoodsReceiptCreatedEvent)
        audit = agg2.get_audit_trail()
        assert any(a["action"] == "ADD_GOODS_RECEIPT" for a in audit)

    def test_add_goods_receipt_po_not_found_raises(self, aggregate, sample_grn):
        with pytest.raises(ValueError, match="PO .* not found"):
            aggregate.add_goods_receipt(sample_grn, "tester")

    def test_add_goods_receipt_item_not_in_po_raises(self, aggregate, sample_po, sample_grn):
        bad_item = GRNItem(
            item_id=uuid4(),
            item_code="BAD-ITEM",
            item_name="Bad Item",
            quantity=Decimal("1"),
            unit_cost=Decimal("100"),
            description="Bad",
        )
        bad_grn = GoodsReceiptNoteEntity(
            grn_id=uuid4(),
            grn_number="GRN-BAD",
            po_id=sample_po.po_id,
            po_number=sample_po.po_number,
            receipt_date=date.today(),
            items=[bad_item],
            status=GRNStatus.CONFIRMED,
            received_by=uuid4(),
            legal_entity_id=sample_po.legal_entity_id,
            created_by="tester",
        )
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg = agg.approve_purchase_order(sample_po.po_id, "approver")
        with pytest.raises(ValueError, match="not found in PO"):
            agg.add_goods_receipt(bad_grn, "tester")

    def test_add_goods_receipt_exceeds_po_quantity_raises(self, aggregate, sample_po, sample_grn):
        grn_item = GRNItem(
            item_id=sample_po.lines[0].item_id,
            item_code="ITEM-001",
            item_name="Test Item",
            quantity=Decimal("15"),
            unit_cost=Decimal("1000"),
            description="Test",
        )
        bad_grn = GoodsReceiptNoteEntity(
            grn_id=uuid4(),
            grn_number="GRN-EXCEED",
            po_id=sample_po.po_id,
            po_number=sample_po.po_number,
            receipt_date=date.today(),
            items=[grn_item],
            status=GRNStatus.CONFIRMED,
            received_by=uuid4(),
            legal_entity_id=sample_po.legal_entity_id,
            created_by="tester",
        )
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg = agg.approve_purchase_order(sample_po.po_id, "approver")
        with pytest.raises(ValueError, match="exceeds PO quantity"):
            agg.add_goods_receipt(bad_grn, "tester")

    def test_add_goods_receipt_locked_raises(self, aggregate, sample_po, sample_grn):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg = agg.lock("alice")
        with pytest.raises(ValueError, match="Cannot add GRN to locked aggregate"):
            agg.add_goods_receipt(sample_grn, "tester")

    def test_get_total_received_quantity(self, aggregate, sample_po, sample_grn):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg = agg.approve_purchase_order(sample_po.po_id, "approver")
        agg2 = agg.add_goods_receipt(sample_grn, "tester")
        item_id = sample_po.lines[0].item_id
        total = agg2.get_total_received_quantity(sample_po.po_id, item_id)
        assert total == Decimal("5")

        grn2_item = GRNItem(
            item_id=item_id,
            item_code="ITEM-001",
            item_name="Test Item",
            quantity=Decimal("3"),
            unit_cost=Decimal("1000"),
            description="Second receipt",
        )
        grn2 = GoodsReceiptNoteEntity(
            grn_id=uuid4(),
            grn_number="GRN-002",
            po_id=sample_po.po_id,
            po_number=sample_po.po_number,
            receipt_date=date.today(),
            items=[grn2_item],
            status=GRNStatus.CONFIRMED,
            received_by=uuid4(),
            legal_entity_id=sample_po.legal_entity_id,
            created_by="tester",
        )
        agg3 = agg2.add_goods_receipt(grn2, "tester")
        total2 = agg3.get_total_received_quantity(sample_po.po_id, item_id)
        assert total2 == Decimal("8")

        grn3_item = GRNItem(
            item_id=item_id,
            item_code="ITEM-001",
            item_name="Test Item",
            quantity=Decimal("0.33"),
            unit_cost=Decimal("1000"),
            description="Partial",
        )
        grn3 = GoodsReceiptNoteEntity(
            grn_id=uuid4(),
            grn_number="GRN-003",
            po_id=sample_po.po_id,
            po_number=sample_po.po_number,
            receipt_date=date.today(),
            items=[grn3_item],
            status=GRNStatus.CONFIRMED,
            received_by=uuid4(),
            legal_entity_id=sample_po.legal_entity_id,
            created_by="tester",
        )
        agg4 = agg3.add_goods_receipt(grn3, "tester")
        total3 = agg4.get_total_received_quantity(sample_po.po_id, item_id)
        assert total3 == Decimal("8.33")

    def test_get_goods_receipt(self, aggregate, sample_po, sample_grn):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg = agg.approve_purchase_order(sample_po.po_id, "approver")
        agg2 = agg.add_goods_receipt(sample_grn, "tester")
        assert agg2.get_goods_receipt(sample_grn.grn_id) is sample_grn
        assert agg2.get_goods_receipt(uuid4()) is None

    def test_get_grns_by_po(self, aggregate, sample_po, sample_grn):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg = agg.approve_purchase_order(sample_po.po_id, "approver")
        agg2 = agg.add_goods_receipt(sample_grn, "tester")
        grns = agg2.get_grns_by_po(sample_po.po_id)
        assert len(grns) == 1
        assert grns[0] is sample_grn

        grn2 = GoodsReceiptNoteEntity(
            grn_id=uuid4(),
            grn_number="GRN-002",
            po_id=sample_po.po_id,
            po_number=sample_po.po_number,
            receipt_date=date.today(),
            items=[],
            status=GRNStatus.CONFIRMED,
            received_by=uuid4(),
            legal_entity_id=sample_po.legal_entity_id,
            created_by="tester",
        )
        agg3 = agg2.add_goods_receipt(grn2, "tester")
        grns2 = agg3.get_grns_by_po(sample_po.po_id)
        assert len(grns2) == 2

    def test_is_po_fully_received_true(self, aggregate, sample_po, sample_grn):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        agg = agg.approve_purchase_order(sample_po.po_id, "approver")
        agg2 = agg.add_goods_receipt(sample_grn, "tester")
        assert agg2.is_po_fully_received(sample_po.po_id) is False

        grn2_item = GRNItem(
            item_id=sample_po.lines[0].item_id,
            item_code="ITEM-001",
            item_name="Test Item",
            quantity=Decimal("5"),
            unit_cost=Decimal("1000"),
            description="Final",
        )
        grn2 = GoodsReceiptNoteEntity(
            grn_id=uuid4(),
            grn_number="GRN-002",
            po_id=sample_po.po_id,
            po_number=sample_po.po_number,
            receipt_date=date.today(),
            items=[grn2_item],
            status=GRNStatus.CONFIRMED,
            received_by=uuid4(),
            legal_entity_id=sample_po.legal_entity_id,
            created_by="tester",
        )
        agg3 = agg2.add_goods_receipt(grn2, "tester")
        assert agg3.is_po_fully_received(sample_po.po_id) is True

    def test_is_po_fully_received_po_not_found_returns_false(self, aggregate):
        assert aggregate.is_po_fully_received(uuid4()) is False


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - Reconstruct
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregateReconstruct:
    def test_reconstruct(self, sample_po, sample_grn, legal_entity_id):
        agg_id = uuid4()
        pos = {sample_po.po_id: sample_po}
        grns = {sample_grn.grn_id: sample_grn}
        created_at = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
        updated_at = datetime(2025, 1, 2, 10, 0, tzinfo=UTC)
        agg = PurchaseOrderAggregate.reconstruct(
            aggregate_id=agg_id,
            legal_entity_id=legal_entity_id,
            purchase_orders=pos,
            goods_receipts=grns,
            created_at=created_at,
            updated_at=updated_at,
            version=5,
            is_locked=True,
        )
        assert agg.aggregate_id == agg_id
        assert agg.legal_entity_id == legal_entity_id
        assert agg.purchase_orders == pos
        assert agg.goods_receipts == grns
        assert agg.created_at == created_at
        assert agg.updated_at == updated_at
        assert agg.version == 5
        assert agg.is_locked is True


# ----------------------------------------------------------------------
# PurchaseOrderAggregate - to_dict
# ----------------------------------------------------------------------
class TestPurchaseOrderAggregateToDict:
    def test_to_dict(self, aggregate, sample_po):
        agg = aggregate.add_purchase_order(sample_po, "tester")
        d = agg.to_dict()
        assert d["aggregate_id"] == str(agg.aggregate_id)
        assert d["legal_entity_id"] == str(agg.legal_entity_id)
        assert d["total_pos"] == 1
        assert d["open_pos"] == 0
        assert d["overdue_pos"] == 0
        assert d["total_grns"] == 0
        assert "created_at" in d
        assert "updated_at" in d
        assert d["version"] == 2
        assert d["is_locked"] is False


# ----------------------------------------------------------------------
# PurchaseOrderRepository (Interface)
# ----------------------------------------------------------------------
class TestPurchaseOrderRepository:
    @pytest.mark.asyncio
    async def test_get_by_legal_entity_not_implemented(self):
        repo = PurchaseOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_legal_entity(uuid4())

    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = PurchaseOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = PurchaseOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = PurchaseOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())
