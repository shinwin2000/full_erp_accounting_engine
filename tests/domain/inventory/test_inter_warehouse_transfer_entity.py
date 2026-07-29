# tests/domain/inventory/test_inter_warehouse_transfer_entity.py
"""
Comprehensive unit tests for Inter Warehouse Transfer Entity.

Covers:
- Enums: TransferStatus, TransferPriority (members, from_string)
- TransferItem: construction, to_dict, dummy fields
- InterWarehouseTransferEntity: factory (create), properties (id, from_warehouse, to_warehouse),
  item management (add_item, remove_item), status transitions (submit, approve, reject, ship, receive, complete, cancel),
  audit trail, validation, serialization (to_dict, from_dict)
- Repository protocol (abstract methods)
- Private methods: _recalculate_denorm, _validate_item_exists, _validate_warehouse_different
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.inventory.inter_warehouse_transfer_entity import (
    InterWarehouseTransferEntity,
    InterWarehouseTransferRepository,
    TransferItem,
    TransferPriority,
    TransferStatus,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def source_warehouse_id() -> UUID:
    return uuid4()


@pytest.fixture
def dest_warehouse_id() -> UUID:
    return uuid4()


@pytest.fixture
def requested_by() -> UUID:
    return uuid4()


@pytest.fixture
def transfer_date() -> date:
    return date(2026, 1, 15)


@pytest.fixture
def sample_item_kwargs() -> dict[str, Any]:
    return {
        "item_id": uuid4(),
        "item_sku": "SKU-001",
        "item_name": "Test Item",
        "quantity": Decimal("10.00"),
        "unit_cost": Decimal("50.00"),
        "batch_number": "BATCH-001",
        "expiry_date": date(2027, 12, 31),
    }


@pytest.fixture
def transfer_kwargs(
    source_warehouse_id,
    dest_warehouse_id,
    requested_by,
    transfer_date,
    legal_entity_id,
) -> dict[str, Any]:
    return {
        "transfer_id": uuid4(),
        "transfer_number": "TR-2026-001",
        "source_warehouse_id": source_warehouse_id,
        "source_warehouse_name": "Source WH",
        "destination_warehouse_id": dest_warehouse_id,
        "destination_warehouse_name": "Dest WH",
        "transfer_date": transfer_date,
        "priority": TransferPriority.NORMAL,
        "status": TransferStatus.DRAFT,
        "items": [],
        "requested_by": requested_by,
        "requested_at": datetime.now(UTC),
        "approved_by": None,
        "approved_at": None,
        "rejected_by": None,
        "rejected_at": None,
        "rejected_reason": None,
        "shipped_by": None,
        "shipped_at": None,
        "received_by": None,
        "received_at": None,
        "completed_by": None,
        "completed_at": None,
        "reason": "Test transfer",
        "notes": "",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "created_by": requested_by,
        "version": 1,
        "legal_entity_id": legal_entity_id,
    }


@pytest.fixture
def transfer(transfer_kwargs) -> InterWarehouseTransferEntity:
    """A DRAFT transfer with no items."""
    return InterWarehouseTransferEntity(**transfer_kwargs)


@pytest.fixture
def transfer_with_items(transfer, sample_item_kwargs) -> InterWarehouseTransferEntity:
    """A DRAFT transfer with one item added."""
    return transfer.add_item(
        item_id=sample_item_kwargs["item_id"],
        item_sku=sample_item_kwargs["item_sku"],
        item_name=sample_item_kwargs["item_name"],
        quantity=sample_item_kwargs["quantity"],
        unit_cost=sample_item_kwargs["unit_cost"],
        batch_number=sample_item_kwargs["batch_number"],
        expiry_date=sample_item_kwargs["expiry_date"],
    )


@pytest.fixture
def submitted_transfer(transfer_with_items) -> InterWarehouseTransferEntity:
    """Transfer in PENDING state."""
    return transfer_with_items.submit()


@pytest.fixture
def approved_transfer(submitted_transfer) -> InterWarehouseTransferEntity:
    """Transfer in APPROVED state."""
    return submitted_transfer.approve(requested_by=uuid4())


@pytest.fixture
def shipped_transfer(approved_transfer) -> InterWarehouseTransferEntity:
    """Transfer in IN_TRANSIT state."""
    return approved_transfer.ship(shipped_by=uuid4(), source_stock=Decimal("100"))


@pytest.fixture
def received_transfer(shipped_transfer) -> InterWarehouseTransferEntity:
    """Transfer in RECEIVED state."""
    return shipped_transfer.receive(received_by=uuid4())


# -----------------------------------------------------------------------------
# Tests for Enums
# -----------------------------------------------------------------------------

class TestTransferStatus:
    def test_members(self):
        assert TransferStatus.DRAFT.value == "draft"
        assert TransferStatus.PENDING.value == "pending"
        assert TransferStatus.APPROVED.value == "approved"
        assert TransferStatus.IN_TRANSIT.value == "in_transit"
        assert TransferStatus.RECEIVED.value == "received"
        assert TransferStatus.COMPLETED.value == "completed"
        assert TransferStatus.CANCELLED.value == "cancelled"
        assert TransferStatus.REJECTED.value == "rejected"

    def test_from_string(self):
        assert TransferStatus.from_string("pending") == TransferStatus.PENDING
        assert TransferStatus.from_string("APPROVED") == TransferStatus.APPROVED
        assert TransferStatus.from_string("in_transit") == TransferStatus.IN_TRANSIT
        assert TransferStatus.from_string("unknown") == TransferStatus.DRAFT  # fallback


class TestTransferPriority:
    def test_members(self):
        assert TransferPriority.LOW.value == "low"
        assert TransferPriority.NORMAL.value == "normal"
        assert TransferPriority.HIGH.value == "high"
        assert TransferPriority.URGENT.value == "urgent"

    def test_from_string(self):
        assert TransferPriority.from_string("high") == TransferPriority.HIGH
        assert TransferPriority.from_string("URGENT") == TransferPriority.URGENT
        assert TransferPriority.from_string("unknown") == TransferPriority.NORMAL  # fallback


# -----------------------------------------------------------------------------
# Tests for TransferItem (Value Object)
# -----------------------------------------------------------------------------

class TestTransferItem:
    def test_construction(self, sample_item_kwargs):
        item = TransferItem(**sample_item_kwargs)
        assert item.item_id == sample_item_kwargs["item_id"]
        assert item.quantity == sample_item_kwargs["quantity"]
        assert item.total_value == sample_item_kwargs["quantity"] * sample_item_kwargs["unit_cost"]
        assert item.reorder_point == Decimal(0)  # default
        assert item.safety_stock == Decimal(0)

    def test_to_dict(self, sample_item_kwargs):
        item = TransferItem(**sample_item_kwargs)
        d = item.to_dict()
        assert d["item_id"] == str(item.item_id)
        assert d["item_sku"] == item.item_sku
        assert d["quantity"] == str(item.quantity)
        assert d["unit_cost"] == str(item.unit_cost)
        assert d["total_value"] == str(item.total_value)
        assert d["batch_number"] == item.batch_number
        assert d["expiry_date"] == item.expiry_date.isoformat()
        assert d["reorder_point"] == "0"
        assert d["safety_stock"] == "0"


# -----------------------------------------------------------------------------
# Tests for InterWarehouseTransferEntity
# -----------------------------------------------------------------------------

class TestInterWarehouseTransferEntity:
    def test_construction_success(self, transfer):
        assert transfer.transfer_id is not None
        assert transfer.transfer_number == "TR-2026-001"
        assert transfer.status == TransferStatus.DRAFT
        assert transfer.version == 1
        assert transfer.quantity == Decimal(0)
        assert transfer.total_value == Decimal(0)
        assert transfer.unit_cost == Decimal(0)

    def test_id_property(self, transfer):
        assert transfer.id == transfer.transfer_id

    def test_from_warehouse_property(self, transfer):
        assert transfer.from_warehouse == transfer.source_warehouse_name

    def test_to_warehouse_property(self, transfer):
        assert transfer.to_warehouse == transfer.destination_warehouse_name

    # ---- Factory method ----

    def test_create_factory(
        self,
        source_warehouse_id,
        dest_warehouse_id,
        requested_by,
        transfer_date,
        legal_entity_id,
    ):
        entity = InterWarehouseTransferEntity.create(
            transfer_number="TR-2026-002",
            source_warehouse_id=source_warehouse_id,
            source_warehouse_name="Src",
            destination_warehouse_id=dest_warehouse_id,
            destination_warehouse_name="Dst",
            transfer_date=transfer_date,
            requested_by=requested_by,
            created_by=uuid4(),
            legal_entity_id=legal_entity_id,
            priority=TransferPriority.URGENT,
            reason="Urgent transfer",
        )
        assert entity.transfer_id is not None
        assert entity.transfer_number == "TR-2026-002"
        assert entity.status == TransferStatus.DRAFT
        assert entity.priority == TransferPriority.URGENT
        assert entity.requested_by == requested_by
        assert entity.legal_entity_id == legal_entity_id
        assert entity.reason == "Urgent transfer"
        assert entity.version == 1

    # ---- Item management ----

    def test_add_item(self, transfer, sample_item_kwargs):
        entity2 = transfer.add_item(
            item_id=sample_item_kwargs["item_id"],
            item_sku=sample_item_kwargs["item_sku"],
            item_name=sample_item_kwargs["item_name"],
            quantity=sample_item_kwargs["quantity"],
            unit_cost=sample_item_kwargs["unit_cost"],
            batch_number=sample_item_kwargs["batch_number"],
            expiry_date=sample_item_kwargs["expiry_date"],
        )
        assert len(entity2.items) == 1
        item = entity2.items[0]
        assert item.item_sku == sample_item_kwargs["item_sku"]
        assert item.quantity == sample_item_kwargs["quantity"]
        assert item.total_value == sample_item_kwargs["quantity"] * sample_item_kwargs["unit_cost"]
        # Check denorm fields
        assert entity2.quantity == sample_item_kwargs["quantity"]
        assert entity2.total_value == item.total_value
        assert entity2.unit_cost == sample_item_kwargs["unit_cost"]
        assert entity2.version == transfer.version + 1
        # Audit trail
        assert len(entity2._audit_trail) >= 1
        assert entity2._audit_trail[-1]["action"] == "add_item"

    def test_add_item_raises_if_not_draft_or_pending(self, transfer_with_items):
        submitted = transfer_with_items.submit()
        # Still PENDING? Actually submit sets to PENDING, but we cannot add to PENDING? The code allows DRAFT or PENDING.
        # So add_item allowed on PENDING. But if status is APPROVED, it should fail.
        approved = submitted.approve(approved_by=uuid4())
        with pytest.raises(ValueError, match="Cannot add item to transfer in status approved"):
            approved.add_item(
                item_id=uuid4(),
                item_sku="SKU-002",
                item_name="New",
                quantity=Decimal(5),
                unit_cost=Decimal(100),
            )

    def test_add_item_raises_for_same_warehouse(self, transfer, sample_item_kwargs):
        # Modify transfer to have same warehouse IDs
        bad_transfer = InterWarehouseTransferEntity(
            transfer_id=uuid4(),
            transfer_number="BAD",
            source_warehouse_id=transfer.source_warehouse_id,
            source_warehouse_name="Src",
            destination_warehouse_id=transfer.source_warehouse_id,  # same
            destination_warehouse_name="Dst",
            transfer_date=date.today(),
            priority=TransferPriority.NORMAL,
            status=TransferStatus.DRAFT,
            requested_by=uuid4(),
        )
        with pytest.raises(ValueError, match="Source and destination warehouses cannot be the same"):
            bad_transfer.add_item(
                item_id=sample_item_kwargs["item_id"],
                item_sku=sample_item_kwargs["item_sku"],
                item_name=sample_item_kwargs["item_name"],
                quantity=sample_item_kwargs["quantity"],
                unit_cost=sample_item_kwargs["unit_cost"],
            )

    def test_add_item_raises_for_zero_quantity(self, transfer, sample_item_kwargs):
        with pytest.raises(ValueError, match="Transfer quantity must be positive"):
            transfer.add_item(
                item_id=sample_item_kwargs["item_id"],
                item_sku=sample_item_kwargs["item_sku"],
                item_name=sample_item_kwargs["item_name"],
                quantity=Decimal(0),
                unit_cost=sample_item_kwargs["unit_cost"],
            )

    def test_remove_item(self, transfer_with_items):
        item_id = transfer_with_items.items[0].item_id
        entity2 = transfer_with_items.remove_item(item_id)
        assert len(entity2.items) == 0
        assert entity2.quantity == Decimal(0)
        assert entity2.total_value == Decimal(0)
        assert entity2.unit_cost == Decimal(0)
        assert entity2.version == transfer_with_items.version + 1
        # Audit
        assert entity2._audit_trail[-1]["action"] == "remove_item"

    def test_remove_item_raises_if_not_found(self, transfer_with_items):
        with pytest.raises(ValueError, match="Item .* not found in transfer"):
            transfer_with_items.remove_item(uuid4())

    def test_remove_item_raises_if_not_draft_or_pending(self, transfer_with_items):
        submitted = transfer_with_items.submit()
        approved = submitted.approve(approved_by=uuid4())
        with pytest.raises(ValueError, match="Cannot remove item from transfer in status approved"):
            approved.remove_item(approved.items[0].item_id)

    # ---- Status transitions ----

    def test_submit(self, transfer_with_items):
        submitted = transfer_with_items.submit()
        assert submitted.status == TransferStatus.PENDING
        assert submitted.version == transfer_with_items.version + 1
        assert submitted.updated_at > transfer_with_items.updated_at
        assert submitted._audit_trail[-1]["action"] == "submit"

    def test_submit_raises_if_no_items(self, transfer):
        with pytest.raises(ValueError, match="Cannot submit transfer with no items"):
            transfer.submit()

    def test_submit_raises_if_not_draft(self, transfer_with_items):
        submitted = transfer_with_items.submit()
        with pytest.raises(ValueError, match="Cannot submit transfer in status pending"):
            submitted.submit()

    def test_approve(self, submitted_transfer):
        approved_by = uuid4()
        approved = submitted_transfer.approve(approved_by)
        assert approved.status == TransferStatus.APPROVED
        assert approved.approved_by == approved_by
        assert approved.approved_at is not None
        assert approved.version == submitted_transfer.version + 1
        assert approved._audit_trail[-1]["action"] == "approve"

    def test_approve_raises_if_not_pending(self, transfer):
        with pytest.raises(ValueError, match="Cannot approve transfer in status draft"):
            transfer.approve(approved_by=uuid4())

    def test_reject(self, submitted_transfer):
        rejected_by = uuid4()
        reason = "Not needed"
        rejected = submitted_transfer.reject(rejected_by, reason)
        assert rejected.status == TransferStatus.REJECTED
        assert rejected.rejected_by == rejected_by
        assert rejected.rejected_at is not None
        assert rejected.rejected_reason == reason
        assert "Rejected: Not needed" in rejected.notes
        assert rejected.version == submitted_transfer.version + 1
        assert rejected._audit_trail[-1]["action"] == "reject"

    def test_reject_raises_if_not_pending(self, transfer):
        with pytest.raises(ValueError, match="Cannot reject transfer in status draft"):
            transfer.reject(rejected_by=uuid4(), reason="No")

    def test_ship(self, approved_transfer):
        shipped_by = uuid4()
        source_stock = Decimal("100")
        shipped = approved_transfer.ship(shipped_by, source_stock)
        assert shipped.status == TransferStatus.IN_TRANSIT
        assert shipped.shipped_by == shipped_by
        assert shipped.shipped_at is not None
        assert shipped.version == approved_transfer.version + 1
        assert shipped._audit_trail[-1]["action"] == "ship"

    def test_ship_raises_if_not_approved(self, submitted_transfer):
        with pytest.raises(ValueError, match="Cannot ship transfer in status pending"):
            submitted_transfer.ship(shipped_by=uuid4())

    def test_ship_raises_if_insufficient_stock(self, approved_transfer):
        # total quantity = 10 from sample_item_kwargs
        with pytest.raises(ValueError, match="Insufficient stock at source warehouse"):
            approved_transfer.ship(shipped_by=uuid4(), source_stock=Decimal("5"))

    def test_ship_raises_if_no_items(self, transfer):
        approved = transfer.add_item(
            item_id=uuid4(),
            item_sku="SKU",
            item_name="Name",
            quantity=Decimal(10),
            unit_cost=Decimal(100),
        ).approve(approved_by=uuid4())
        # Should not raise if items exist.
        # To test no items, we can create an approved transfer with no items (but that would fail validation anyway).
        # The code checks if not self.items, so we need to test that.
        # We'll create an approved transfer with no items by directly constructing.
        empty_approved = InterWarehouseTransferEntity(
            transfer_id=uuid4(),
            transfer_number="EMPTY",
            source_warehouse_id=approved.source_warehouse_id,
            source_warehouse_name="Src",
            destination_warehouse_id=approved.destination_warehouse_id,
            destination_warehouse_name="Dst",
            transfer_date=date.today(),
            priority=TransferPriority.NORMAL,
            status=TransferStatus.APPROVED,
            items=[],
            requested_by=uuid4(),
        )
        with pytest.raises(ValueError, match="Cannot ship transfer with no items"):
            empty_approved.ship(shipped_by=uuid4())

    def test_receive(self, shipped_transfer):
        received_by = uuid4()
        received = shipped_transfer.receive(received_by)
        assert received.status == TransferStatus.RECEIVED
        assert received.received_by == received_by
        assert received.received_at is not None
        assert received.version == shipped_transfer.version + 1
        assert received._audit_trail[-1]["action"] == "receive"

    def test_receive_raises_if_not_in_transit(self, approved_transfer):
        with pytest.raises(ValueError, match="Cannot receive transfer in status approved"):
            approved_transfer.receive(received_by=uuid4())

    def test_receive_raises_if_no_items(self, transfer):
        # similar to ship, we create a transfer in IN_TRANSIT with no items
        empty_transit = InterWarehouseTransferEntity(
            transfer_id=uuid4(),
            transfer_number="EMPTY",
            source_warehouse_id=transfer.source_warehouse_id,
            source_warehouse_name="Src",
            destination_warehouse_id=transfer.destination_warehouse_id,
            destination_warehouse_name="Dst",
            transfer_date=date.today(),
            priority=TransferPriority.NORMAL,
            status=TransferStatus.IN_TRANSIT,
            items=[],
            requested_by=uuid4(),
        )
        with pytest.raises(ValueError, match="Cannot receive transfer with no items"):
            empty_transit.receive(received_by=uuid4())

    def test_complete(self, received_transfer):
        completed_by = uuid4()
        completed = received_transfer.complete(completed_by)
        assert completed.status == TransferStatus.COMPLETED
        assert completed.completed_by == completed_by
        assert completed.completed_at is not None
        assert completed.version == received_transfer.version + 1
        assert completed._audit_trail[-1]["action"] == "complete"

    def test_complete_raises_if_not_received(self, approved_transfer):
        with pytest.raises(ValueError, match="Cannot complete transfer in status approved"):
            approved_transfer.complete(completed_by=uuid4())

    def test_cancel(self, transfer_with_items):
        cancelled_by = uuid4()
        reason = "Cancelled due to stock change"
        cancelled = transfer_with_items.cancel(cancelled_by, reason)
        assert cancelled.status == TransferStatus.CANCELLED
        assert "Cancelled: Cancelled due to stock change" in cancelled.reason
        assert cancelled.version == transfer_with_items.version + 1
        assert cancelled.created_by == cancelled_by  # created_by becomes cancelled_by
        assert cancelled._audit_trail[-1]["action"] == "cancel"

    def test_cancel_raises_if_completed(self, received_transfer):
        completed = received_transfer.complete(completed_by=uuid4())
        with pytest.raises(ValueError, match="Cannot cancel transfer in status completed"):
            completed.cancel(cancelled_by=uuid4(), reason="Too late")

    def test_cancel_raises_if_already_cancelled(self, transfer_with_items):
        cancelled = transfer_with_items.cancel(cancelled_by=uuid4(), reason="Test")
        with pytest.raises(ValueError, match="Cannot cancel transfer in status cancelled"):
            cancelled.cancel(cancelled_by=uuid4(), reason="Again")

    # ---- Audit trail ----

    def test_audit_trail(self, transfer_with_items):
        # Multiple actions
        entity = transfer_with_items
        entity = entity.submit()
        entity = entity.approve(approved_by=uuid4())
        entity = entity.ship(shipped_by=uuid4(), source_stock=Decimal("100"))
        entity = entity.receive(received_by=uuid4())
        entity = entity.complete(completed_by=uuid4())
        trail = entity._audit_trail
        actions = [entry["action"] for entry in trail]
        assert "add_item" in actions
        assert "submit" in actions
        assert "approve" in actions
        assert "ship" in actions
        assert "receive" in actions
        assert "complete" in actions
        # Each action should have timestamp and performed_by

    # ---- Validation ----

    def test_validate(self, transfer_with_items):
        errors = transfer_with_items.validate()
        assert errors == []

        # Invalid: zero quantity
        bad_item = TransferItem(
            item_id=uuid4(),
            item_sku="BAD",
            item_name="Bad",
            quantity=Decimal(0),
            unit_cost=Decimal(100),
            total_value=Decimal(0),
        )
        bad_transfer = InterWarehouseTransferEntity(
            transfer_id=uuid4(),
            transfer_number="BAD",
            source_warehouse_id=uuid4(),
            source_warehouse_name="Src",
            destination_warehouse_id=uuid4(),
            destination_warehouse_name="Dst",
            transfer_date=date.today(),
            priority=TransferPriority.NORMAL,
            status=TransferStatus.DRAFT,
            items=[bad_item],
            requested_by=uuid4(),
        )
        errors = bad_transfer.validate()
        assert any("invalid quantity" in e for e in errors)

        # Negative unit cost
        bad_item2 = TransferItem(
            item_id=uuid4(),
            item_sku="BAD2",
            item_name="Bad2",
            quantity=Decimal(10),
            unit_cost=Decimal(-5),
            total_value=Decimal(-50),
        )
        bad_transfer2 = InterWarehouseTransferEntity(
            transfer_id=uuid4(),
            transfer_number="BAD2",
            source_warehouse_id=uuid4(),
            source_warehouse_name="Src",
            destination_warehouse_id=uuid4(),
            destination_warehouse_name="Dst",
            transfer_date=date.today(),
            priority=TransferPriority.NORMAL,
            status=TransferStatus.DRAFT,
            items=[bad_item2],
            requested_by=uuid4(),
        )
        errors = bad_transfer2.validate()
        assert any("negative unit cost" in e for e in errors)

        # Same warehouse
        bad_transfer3 = InterWarehouseTransferEntity(
            transfer_id=uuid4(),
            transfer_number="BAD3",
            source_warehouse_id=uuid4(),
            source_warehouse_name="Src",
            destination_warehouse_id=uuid4(),  # different from source but we set same
            destination_warehouse_name="Dst",
            transfer_date=date.today(),
            priority=TransferPriority.NORMAL,
            status=TransferStatus.DRAFT,
            items=[TransferItem(
                item_id=uuid4(),
                item_sku="SKU",
                item_name="Name",
                quantity=Decimal(10),
                unit_cost=Decimal(100),
                total_value=Decimal(1000),
            )],
            requested_by=uuid4(),
        )
        # Set same warehouse
        object.__setattr__(bad_transfer3, "source_warehouse_id", bad_transfer3.destination_warehouse_id)
        errors = bad_transfer3.validate()
        assert any("cannot be the same" in e for e in errors)

    # ---- Serialization ----

    def test_to_dict(self, transfer_with_items):
        d = transfer_with_items.to_dict()
        assert d["transfer_id"] == str(transfer_with_items.transfer_id)
        assert d["transfer_number"] == transfer_with_items.transfer_number
        assert d["status"] == transfer_with_items.status.value
        assert d["quantity"] == str(transfer_with_items.quantity)
        assert d["total_value"] == str(transfer_with_items.total_value)
        assert len(d["items"]) == 1
        assert "created_at" in d
        assert "version" in d

    def test_from_dict_round_trip(self, transfer_with_items):
        d = transfer_with_items.to_dict()
        restored = InterWarehouseTransferEntity.from_dict(d)
        assert restored.transfer_id == transfer_with_items.transfer_id
        assert restored.transfer_number == transfer_with_items.transfer_number
        assert restored.status == transfer_with_items.status
        assert restored.quantity == transfer_with_items.quantity
        assert restored.total_value == transfer_with_items.total_value
        assert len(restored.items) == len(transfer_with_items.items)
        assert restored.created_at == transfer_with_items.created_at
        assert restored.version == transfer_with_items.version
        # Check one item
        original_item = transfer_with_items.items[0]
        restored_item = restored.items[0]
        assert original_item.item_id == restored_item.item_id
        assert original_item.quantity == restored_item.quantity
        assert original_item.total_value == restored_item.total_value


# -----------------------------------------------------------------------------
# Tests for Private Methods (explicit coverage)
# -----------------------------------------------------------------------------

class TestPrivateMethods:
    def test_recalculate_denorm(self, transfer, sample_item_kwargs):
        # Create a transfer with items directly (not via add_item to avoid calling _recalculate_denorm inside add_item)
        # Actually add_item calls _recalculate_denorm internally, so we need to test it separately.
        # We'll create a transfer with items set, then manually call _recalculate_denorm and check denorm fields.
        item = TransferItem(
            item_id=sample_item_kwargs["item_id"],
            item_sku=sample_item_kwargs["item_sku"],
            item_name=sample_item_kwargs["item_name"],
            quantity=sample_item_kwargs["quantity"],
            unit_cost=sample_item_kwargs["unit_cost"],
            total_value=sample_item_kwargs["quantity"] * sample_item_kwargs["unit_cost"],
            batch_number=sample_item_kwargs["batch_number"],
            expiry_date=sample_item_kwargs["expiry_date"],
        )
        # Manually set items (bypassing add_item)
        object.__setattr__(transfer, "items", [item])
        # Initially denorm fields are zero (from construction)
        assert transfer.quantity == Decimal(0)
        assert transfer.total_value == Decimal(0)
        assert transfer.unit_cost == Decimal(0)

        # Call private method
        transfer._recalculate_denorm()

        # Verify denorm fields updated
        assert transfer.quantity == sample_item_kwargs["quantity"]
        assert transfer.total_value == sample_item_kwargs["quantity"] * sample_item_kwargs["unit_cost"]
        assert transfer.unit_cost == sample_item_kwargs["unit_cost"]

    def test_validate_item_exists_existing(self, transfer_with_items):
        item_id = transfer_with_items.items[0].item_id
        # Should not raise
        try:
            transfer_with_items._validate_item_exists(item_id)
        except Exception:
            pytest.fail("_validate_item_exists raised an exception when item exists")
        assert True

    def test_validate_item_exists_non_existing(self, transfer_with_items):
        with pytest.raises(ValueError, match="not found in transfer"):
            transfer_with_items._validate_item_exists(uuid4())

    def test_validate_warehouse_different_valid(self, transfer):
        # Source and destination are different (fixture)
        try:
            transfer._validate_warehouse_different()
        except Exception:
            pytest.fail("_validate_warehouse_different raised an exception when warehouses are different")
        assert True

    def test_validate_warehouse_different_same_raises(self, transfer):
        # Set same warehouse
        object.__setattr__(transfer, "destination_warehouse_id", transfer.source_warehouse_id)
        with pytest.raises(ValueError, match="cannot be the same"):
            transfer._validate_warehouse_different()


# -----------------------------------------------------------------------------
# Tests for Repository Protocol
# -----------------------------------------------------------------------------

class TestInterWarehouseTransferRepository:
    def test_methods_raise_not_implemented(self):
        repo = InterWarehouseTransferRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("TR-123", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_source_warehouse(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_destination_warehouse(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_pending(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
