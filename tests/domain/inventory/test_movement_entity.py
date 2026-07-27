# test_movement_entity.py
# =========================
# Comprehensive tests for domain/inventory/movement_entity.py.
# Covers all factory methods, business methods, properties, validation, and serialization.

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4, UUID
import pytest

from domain.inventory.movement_entity import (
    InsufficientStockError,
    InvalidMovementError,
    MovementEntity,
    MovementRepository,
    MovementStatus,
    MovementType,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def item_id() -> UUID:
    return uuid4()


@pytest.fixture
def warehouse_id() -> UUID:
    return uuid4()


@pytest.fixture
def other_warehouse_id() -> UUID:
    return uuid4()


@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def movement_date() -> date:
    return date(2025, 1, 15)


@pytest.fixture
def basic_movement(item_id, warehouse_id, movement_date) -> MovementEntity:
    """Create a basic MovementEntity with valid data."""
    return MovementEntity(
        movement_id=uuid4(),
        movement_type=MovementType.PURCHASE_RECEIPT,
        movement_number="RCV-001",
        item_id=item_id,
        item_sku="ITEM-001",
        item_name="Test Item",
        warehouse_id=warehouse_id,
        quantity=Decimal("10"),
        unit_cost=Decimal("100"),
        total_cost=Decimal("1000"),
        movement_date=movement_date,
        status=MovementStatus.CONFIRMED,
        reference_document_type="PURCHASE_ORDER",
        reference_document_id=uuid4(),
        reference_document_number="PO-001",
        created_by="alice",
        created_at=datetime.now(UTC),
        description="Test movement",
        legal_entity_id=uuid4(),
        warehouse_code="WH-001",
        version=1,
    )


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestMovementType:
    def test_members_exist(self):
        assert hasattr(MovementType, "PURCHASE_RECEIPT")
        assert hasattr(MovementType, "PURCHASE_RETURN")
        assert hasattr(MovementType, "PRODUCTION_COMPLETION")
        assert hasattr(MovementType, "PRODUCTION_ISSUE")
        assert hasattr(MovementType, "TRANSFER_IN")
        assert hasattr(MovementType, "TRANSFER_OUT")
        assert hasattr(MovementType, "RETURN_FROM_CUSTOMER")
        assert hasattr(MovementType, "RETURN_TO_SUPPLIER")
        assert hasattr(MovementType, "ADJUSTMENT_IN")
        assert hasattr(MovementType, "ADJUSTMENT_OUT")
        assert hasattr(MovementType, "INITIAL_STOCK")
        assert hasattr(MovementType, "SALES_ISSUE")
        assert hasattr(MovementType, "SALES_RETURN")
        assert hasattr(MovementType, "DAMAGED")
        assert hasattr(MovementType, "EXPIRED")
        assert hasattr(MovementType, "SAMPLE_ISSUE")
        assert hasattr(MovementType, "DONATION")
        assert hasattr(MovementType, "WRITE_OFF")

    def test_member_is_instance(self):
        assert isinstance(MovementType.PURCHASE_RECEIPT, MovementType)

    def test_is_inbound(self):
        assert MovementType.PURCHASE_RECEIPT.is_inbound() is True
        assert MovementType.PRODUCTION_COMPLETION.is_inbound() is True
        assert MovementType.TRANSFER_IN.is_inbound() is True
        assert MovementType.RETURN_FROM_CUSTOMER.is_inbound() is True
        assert MovementType.ADJUSTMENT_IN.is_inbound() is True
        assert MovementType.INITIAL_STOCK.is_inbound() is True
        assert MovementType.SALES_RETURN.is_inbound() is True
        assert MovementType.SALES_ISSUE.is_inbound() is False
        assert MovementType.PURCHASE_RETURN.is_inbound() is False
        assert MovementType.TRANSFER_OUT.is_inbound() is False

    def test_is_outbound(self):
        assert MovementType.SALES_ISSUE.is_outbound() is True
        assert MovementType.PURCHASE_RETURN.is_outbound() is True
        assert MovementType.TRANSFER_OUT.is_outbound() is True
        assert MovementType.ADJUSTMENT_OUT.is_outbound() is True
        assert MovementType.PURCHASE_RECEIPT.is_outbound() is False


class TestMovementStatus:
    def test_members_exist(self):
        assert hasattr(MovementStatus, "DRAFT")
        assert hasattr(MovementStatus, "CONFIRMED")
        assert hasattr(MovementStatus, "CANCELLED")
        assert hasattr(MovementStatus, "REVERSED")
        assert hasattr(MovementStatus, "PENDING")
        assert hasattr(MovementStatus, "COMPLETED")

    def test_member_is_instance(self):
        assert isinstance(MovementStatus.DRAFT, MovementStatus)


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class TestInsufficientStockError:
    def test_construction(self):
        err = InsufficientStockError("Insufficient stock")
        assert isinstance(err, ValueError)
        assert str(err) == "Insufficient stock"


class TestInvalidMovementError:
    def test_construction(self):
        err = InvalidMovementError("Invalid movement")
        assert isinstance(err, ValueError)
        assert str(err) == "Invalid movement"


# ----------------------------------------------------------------------
# MovementEntity - Factory Methods
# ----------------------------------------------------------------------
class TestMovementEntityFactory:
    @pytest.fixture
    def item_id(self) -> UUID:
        return uuid4()

    @pytest.fixture
    def warehouse_id(self) -> UUID:
        return uuid4()

    @pytest.fixture
    def legal_entity_id(self) -> UUID:
        return uuid4()

    @pytest.fixture
    def movement_date(self) -> date:
        return date(2025, 1, 15)

    # ---- create_receipt ----
    def test_create_receipt_success(self, item_id, warehouse_id, legal_entity_id, movement_date):
        ref_id = uuid4()
        movement = MovementEntity.create_receipt(
            item_id=item_id,
            item_sku="ITEM-001",
            item_name="Test Item",
            warehouse_id=warehouse_id,
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            movement_date=movement_date,
            reference_document_type="PURCHASE_ORDER",
            reference_document_id=ref_id,
            reference_document_number="PO-001",
            created_by="alice",
            description="Test receipt",
            batch_number="BATCH-001",
            legal_entity_id=legal_entity_id,
            warehouse_code="WH-001",
            po_line_id=uuid4(),
        )
        assert movement.movement_type == MovementType.PURCHASE_RECEIPT
        assert movement.item_id == item_id
        assert movement.quantity == Decimal("10")
        assert movement.unit_cost == Decimal("100")
        assert movement.total_cost == Decimal("1000")
        assert movement.warehouse_id == warehouse_id
        assert movement.status == MovementStatus.CONFIRMED
        assert movement.batch_number == "BATCH-001"
        assert movement.legal_entity_id == legal_entity_id
        assert len(movement._audit_trail) == 1
        assert movement._audit_trail[0]["action"] == "create_receipt"

    def test_create_receipt_missing_item_id_raises(self, warehouse_id, movement_date):
        with pytest.raises(InvalidMovementError, match="item_id is required"):
            MovementEntity.create_receipt(
                item_id=None,  # type: ignore
                item_sku="ITEM-001",
                item_name="Test",
                warehouse_id=warehouse_id,
                quantity=Decimal("10"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                reference_document_type="PO",
                reference_document_id=uuid4(),
                reference_document_number="PO-001",
            )

    def test_create_receipt_missing_warehouse_raises(self, item_id, movement_date):
        with pytest.raises(InvalidMovementError, match="warehouse_id is required"):
            MovementEntity.create_receipt(
                item_id=item_id,
                item_sku="ITEM-001",
                item_name="Test",
                warehouse_id=None,  # type: ignore
                quantity=Decimal("10"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                reference_document_type="PO",
                reference_document_id=uuid4(),
                reference_document_number="PO-001",
            )

    def test_create_receipt_zero_quantity_raises(self, item_id, warehouse_id, movement_date):
        with pytest.raises(ValueError, match="Receipt quantity must be positive"):
            MovementEntity.create_receipt(
                item_id=item_id,
                item_sku="ITEM-001",
                item_name="Test",
                warehouse_id=warehouse_id,
                quantity=Decimal("0"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                reference_document_type="PO",
                reference_document_id=uuid4(),
                reference_document_number="PO-001",
            )

    # ---- create_issue ----
    def test_create_issue_success(self, item_id, warehouse_id, legal_entity_id, movement_date):
        ref_id = uuid4()
        movement = MovementEntity.create_issue(
            item_id=item_id,
            item_sku="ITEM-001",
            item_name="Test Item",
            warehouse_id=warehouse_id,
            quantity=Decimal("5"),
            unit_cost=Decimal("100"),
            movement_date=movement_date,
            reference_document_type="SALES_ORDER",
            reference_document_id=ref_id,
            reference_document_number="SO-001",
            created_by="bob",
            description="Test issue",
            legal_entity_id=legal_entity_id,
            warehouse_code="WH-001",
            so_line_id=uuid4(),
            available_stock=Decimal("10"),
        )
        assert movement.movement_type == MovementType.SALES_ISSUE
        assert movement.quantity == Decimal("5")
        assert movement.total_cost == Decimal("500")
        assert movement.status == MovementStatus.CONFIRMED
        assert len(movement._audit_trail) == 1

    def test_create_issue_missing_item_id_raises(self, warehouse_id, movement_date):
        with pytest.raises(InvalidMovementError, match="item_id is required"):
            MovementEntity.create_issue(
                item_id=None,  # type: ignore
                item_sku="ITEM-001",
                item_name="Test",
                warehouse_id=warehouse_id,
                quantity=Decimal("5"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                reference_document_type="SO",
                reference_document_id=uuid4(),
                reference_document_number="SO-001",
            )

    def test_create_issue_insufficient_stock_raises(self, item_id, warehouse_id, movement_date):
        with pytest.raises(InsufficientStockError, match="Insufficient stock"):
            MovementEntity.create_issue(
                item_id=item_id,
                item_sku="ITEM-001",
                item_name="Test",
                warehouse_id=warehouse_id,
                quantity=Decimal("15"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                reference_document_type="SO",
                reference_document_id=uuid4(),
                reference_document_number="SO-001",
                available_stock=Decimal("10"),
            )

    # ---- create_transfer ----
    def test_create_transfer_success(self, item_id, warehouse_id, other_warehouse_id, legal_entity_id, movement_date):
        out_movement, in_movement = MovementEntity.create_transfer(
            item_id=item_id,
            item_sku="ITEM-001",
            item_name="Test Item",
            from_warehouse_id=warehouse_id,
            to_warehouse_id=other_warehouse_id,
            quantity=Decimal("5"),
            unit_cost=Decimal("100"),
            movement_date=movement_date,
            reference_document_number="TRF-001",
            created_by="carol",
            description="Transfer test",
            legal_entity_id=legal_entity_id,
            from_warehouse_code="WH-001",
            to_warehouse_code="WH-002",
            available_source_stock=Decimal("10"),
        )
        # Out movement
        assert out_movement.movement_type == MovementType.TRANSFER_OUT
        assert out_movement.quantity == Decimal("5")
        assert out_movement.warehouse_id == warehouse_id
        assert out_movement.destination_warehouse_id == other_warehouse_id
        assert "IN_TRANSIT" in out_movement.description
        assert "IN_TRANSIT" in out_movement.notes
        # In movement
        assert in_movement.movement_type == MovementType.TRANSFER_IN
        assert in_movement.quantity == Decimal("5")
        assert in_movement.warehouse_id == other_warehouse_id
        assert in_movement.source_warehouse_id == warehouse_id
        assert "RECEIVED" in in_movement.description
        assert "RECEIVED" in in_movement.notes
        # Audit trails
        assert len(out_movement._audit_trail) == 1
        assert out_movement._audit_trail[0]["action"] == "create_transfer_out"
        assert in_movement._audit_trail[0]["action"] == "create_transfer_in"

    def test_create_transfer_same_warehouse_raises(self, item_id, warehouse_id, movement_date):
        with pytest.raises(InvalidMovementError, match="cannot be the same"):
            MovementEntity.create_transfer(
                item_id=item_id,
                item_sku="ITEM-001",
                item_name="Test",
                from_warehouse_id=warehouse_id,
                to_warehouse_id=warehouse_id,
                quantity=Decimal("5"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                reference_document_number="TRF-001",
            )

    def test_create_transfer_missing_from_warehouse_raises(self, item_id, other_warehouse_id, movement_date):
        with pytest.raises(InvalidMovementError, match="from_warehouse_id and to_warehouse_id are required"):
            MovementEntity.create_transfer(
                item_id=item_id,
                item_sku="ITEM-001",
                item_name="Test",
                from_warehouse_id=None,  # type: ignore
                to_warehouse_id=other_warehouse_id,
                quantity=Decimal("5"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                reference_document_number="TRF-001",
            )

    def test_create_transfer_insufficient_source_stock_raises(self, item_id, warehouse_id, other_warehouse_id, movement_date):
        with pytest.raises(InsufficientStockError, match="Insufficient stock at source"):
            MovementEntity.create_transfer(
                item_id=item_id,
                item_sku="ITEM-001",
                item_name="Test",
                from_warehouse_id=warehouse_id,
                to_warehouse_id=other_warehouse_id,
                quantity=Decimal("15"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                reference_document_number="TRF-001",
                available_source_stock=Decimal("10"),
            )

    # ---- create_adjustment ----
    def test_create_adjustment_in_success(self, item_id, warehouse_id, legal_entity_id):
        movement = MovementEntity.create_adjustment(
            item_id=item_id,
            warehouse_id=warehouse_id,
            quantity=Decimal("10"),
            reason="Stock correction",
            created_by="dave",
            unit_cost=Decimal("100"),
            legal_entity_id=legal_entity_id,
            warehouse_code="WH-001",
            available_stock=Decimal("50"),
        )
        assert movement.movement_type == MovementType.ADJUSTMENT_IN
        assert movement.quantity == Decimal("10")
        assert movement.total_cost == Decimal("1000")
        assert movement.status == MovementStatus.CONFIRMED
        assert movement.notes == "Stock correction"
        assert len(movement._audit_trail) == 1
        assert movement._audit_trail[0]["action"] == "create_adjustment"

    def test_create_adjustment_out_success(self, item_id, warehouse_id):
        movement = MovementEntity.create_adjustment(
            item_id=item_id,
            warehouse_id=warehouse_id,
            quantity=Decimal("-5"),
            reason="Write-off",
            created_by="dave",
            unit_cost=Decimal("100"),
            available_stock=Decimal("10"),
        )
        assert movement.movement_type == MovementType.ADJUSTMENT_OUT
        assert movement.quantity == Decimal("5")
        assert movement.total_cost == Decimal("500")

    def test_create_adjustment_out_insufficient_stock_raises(self, item_id, warehouse_id):
        with pytest.raises(InsufficientStockError, match="Insufficient stock"):
            MovementEntity.create_adjustment(
                item_id=item_id,
                warehouse_id=warehouse_id,
                quantity=Decimal("-15"),
                reason="Write-off",
                created_by="dave",
                available_stock=Decimal("10"),
            )

    def test_create_adjustment_zero_quantity_raises(self, item_id, warehouse_id):
        with pytest.raises(ValueError, match="Adjustment quantity cannot be zero"):
            MovementEntity.create_adjustment(
                item_id=item_id,
                warehouse_id=warehouse_id,
                quantity=Decimal("0"),
                reason="Zero",
                created_by="dave",
            )

    def test_create_adjustment_missing_item_raises(self, warehouse_id):
        with pytest.raises(InvalidMovementError, match="item_id is required"):
            MovementEntity.create_adjustment(
                item_id=None,  # type: ignore
                warehouse_id=warehouse_id,
                quantity=Decimal("10"),
                reason="Test",
            )

    # ---- create_production_issue ----
    def test_create_production_issue_success(self, item_id, warehouse_id, legal_entity_id, movement_date):
        wo_id = uuid4()
        movement = MovementEntity.create_production_issue(
            item_id=item_id,
            item_sku="ITEM-001",
            item_name="Test Item",
            warehouse_id=warehouse_id,
            quantity=Decimal("5"),
            unit_cost=Decimal("100"),
            movement_date=movement_date,
            work_order_id=wo_id,
            work_order_number="WO-001",
            created_by="eve",
            legal_entity_id=legal_entity_id,
            available_stock=Decimal("10"),
        )
        assert movement.movement_type == MovementType.PRODUCTION_ISSUE
        assert movement.quantity == Decimal("5")
        assert movement.reference_document_number == "WO-001"
        assert movement.wo_line_id == wo_id
        assert len(movement._audit_trail) == 1

    def test_create_production_issue_insufficient_stock_raises(self, item_id, warehouse_id, movement_date):
        with pytest.raises(InsufficientStockError, match="Insufficient stock"):
            MovementEntity.create_production_issue(
                item_id=item_id,
                item_sku="ITEM-001",
                item_name="Test",
                warehouse_id=warehouse_id,
                quantity=Decimal("15"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                work_order_id=uuid4(),
                work_order_number="WO-001",
                available_stock=Decimal("10"),
            )

    # ---- create_production_completion ----
    def test_create_production_completion_success(self, item_id, warehouse_id, legal_entity_id, movement_date):
        wo_id = uuid4()
        movement = MovementEntity.create_production_completion(
            item_id=item_id,
            item_sku="ITEM-001",
            item_name="Test Item",
            warehouse_id=warehouse_id,
            quantity=Decimal("10"),
            unit_cost=Decimal("150"),
            movement_date=movement_date,
            work_order_id=wo_id,
            work_order_number="WO-001",
            created_by="frank",
            legal_entity_id=legal_entity_id,
        )
        assert movement.movement_type == MovementType.PRODUCTION_COMPLETION
        assert movement.quantity == Decimal("10")
        assert movement.total_cost == Decimal("1500")
        assert movement.reference_document_number == "WO-001"
        assert movement.wo_line_id == wo_id

    # ---- create_return_to_supplier ----
    def test_create_return_to_supplier_success(self, item_id, warehouse_id, movement_date):
        po_id = uuid4()
        movement = MovementEntity.create_return_to_supplier(
            item_id=item_id,
            item_sku="ITEM-001",
            item_name="Test Item",
            warehouse_id=warehouse_id,
            quantity=Decimal("3"),
            unit_cost=Decimal("100"),
            movement_date=movement_date,
            purchase_order_id=po_id,
            purchase_order_number="PO-001",
            created_by="grace",
            legal_entity_id=uuid4(),
            available_stock=Decimal("10"),
        )
        assert movement.movement_type == MovementType.RETURN_TO_SUPPLIER
        assert movement.quantity == Decimal("3")
        assert movement.po_line_id == po_id

    def test_create_return_to_supplier_insufficient_stock_raises(self, item_id, warehouse_id, movement_date):
        with pytest.raises(InsufficientStockError, match="Insufficient stock"):
            MovementEntity.create_return_to_supplier(
                item_id=item_id,
                item_sku="ITEM-001",
                item_name="Test",
                warehouse_id=warehouse_id,
                quantity=Decimal("15"),
                unit_cost=Decimal("100"),
                movement_date=movement_date,
                purchase_order_id=uuid4(),
                purchase_order_number="PO-001",
                available_stock=Decimal("10"),
            )

    # ---- create_sales_return ----
    def test_create_sales_return_success(self, item_id, warehouse_id, movement_date):
        so_id = uuid4()
        movement = MovementEntity.create_sales_return(
            item_id=item_id,
            item_sku="ITEM-001",
            item_name="Test Item",
            warehouse_id=warehouse_id,
            quantity=Decimal("2"),
            unit_cost=Decimal("100"),
            movement_date=movement_date,
            sales_order_id=so_id,
            sales_order_number="SO-001",
            created_by="helen",
            legal_entity_id=uuid4(),
        )
        assert movement.movement_type == MovementType.SALES_RETURN
        assert movement.quantity == Decimal("2")
        assert movement.so_line_id == so_id


# ----------------------------------------------------------------------
# MovementEntity - Properties & Business Methods
# ----------------------------------------------------------------------
class TestMovementEntityProperties:
    def test_id_property(self, basic_movement):
        assert basic_movement.id == basic_movement.movement_id

    def test_is_inbound_property(self, basic_movement):
        assert basic_movement.is_inbound is True
        # Create outbound movement
        issue = MovementEntity.create_issue(
            item_id=uuid4(),
            item_sku="ITEM",
            item_name="Test",
            warehouse_id=uuid4(),
            quantity=Decimal("1"),
            unit_cost=Decimal("100"),
            movement_date=date.today(),
            reference_document_type="SO",
            reference_document_id=uuid4(),
            reference_document_number="SO-001",
        )
        assert issue.is_inbound is False

    def test_is_outbound_property(self, basic_movement):
        assert basic_movement.is_outbound is False
        issue = MovementEntity.create_issue(
            item_id=uuid4(),
            item_sku="ITEM",
            item_name="Test",
            warehouse_id=uuid4(),
            quantity=Decimal("1"),
            unit_cost=Decimal("100"),
            movement_date=date.today(),
            reference_document_type="SO",
            reference_document_id=uuid4(),
            reference_document_number="SO-001",
        )
        assert issue.is_outbound is True

    def test_reorder_point_property(self, basic_movement):
        assert basic_movement.reorder_point == Decimal("0")

    def test_safety_stock_property(self, basic_movement):
        assert basic_movement.safety_stock == Decimal("0")

    def test_reconcile_method(self, basic_movement):
        result = basic_movement.reconcile(Decimal("100"), Decimal("120"))
        assert result == Decimal("20")  # physical - system

    def test_calculate_balance_method(self, basic_movement):
        assert basic_movement.calculate_balance() == basic_movement.quantity


# ----------------------------------------------------------------------
# MovementEntity - Business Methods
# ----------------------------------------------------------------------
class TestMovementEntityBusiness:
    def test_confirm_success(self, basic_movement):
        # Create a draft movement first
        draft = MovementEntity(
            movement_id=uuid4(),
            movement_type=MovementType.PURCHASE_RECEIPT,
            movement_number="RCV-001",
            item_id=uuid4(),
            item_sku="ITEM",
            item_name="Test",
            warehouse_id=uuid4(),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            movement_date=date.today(),
            status=MovementStatus.DRAFT,
            reference_document_type="PO",
            reference_document_id=uuid4(),
            reference_document_number="PO-001",
            created_by="alice",
            created_at=datetime.now(UTC),
            version=1,
        )
        confirmed = draft.confirm("alice")
        assert confirmed.status == MovementStatus.CONFIRMED
        assert confirmed.version == draft.version + 1
        assert len(confirmed._audit_trail) == 2  # initial + confirm
        assert confirmed._audit_trail[-1]["action"] == "confirm"
        assert confirmed._audit_trail[-1]["details"]["confirmed_by"] == "alice"

    def test_confirm_non_draft_raises(self, basic_movement):
        with pytest.raises(ValueError, match="Cannot confirm movement in status confirmed"):
            basic_movement.confirm("alice")

    def test_cancel_success_draft(self, basic_movement):
        draft = MovementEntity(
            movement_id=uuid4(),
            movement_type=MovementType.PURCHASE_RECEIPT,
            movement_number="RCV-001",
            item_id=uuid4(),
            item_sku="ITEM",
            item_name="Test",
            warehouse_id=uuid4(),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            movement_date=date.today(),
            status=MovementStatus.DRAFT,
            reference_document_type="PO",
            reference_document_id=uuid4(),
            reference_document_number="PO-001",
            created_by="alice",
            created_at=datetime.now(UTC),
            version=1,
        )
        cancelled = draft.cancel("bob", "User request")
        assert cancelled.status == MovementStatus.CANCELLED
        assert cancelled.version == draft.version + 1
        assert "Cancelled: User request by bob" in cancelled.description
        assert "Cancelled: User request" in cancelled.notes
        assert len(cancelled._audit_trail) == 2

    def test_cancel_success_confirmed(self, basic_movement):
        cancelled = basic_movement.cancel("bob", "Duplicate")
        assert cancelled.status == MovementStatus.CANCELLED
        assert "Cancelled: Duplicate by bob" in cancelled.description

    def test_cancel_cancelled_raises(self, basic_movement):
        cancelled = basic_movement.cancel("bob", "test")
        with pytest.raises(ValueError, match="Cannot cancel movement in status cancelled"):
            cancelled.cancel("bob", "again")

    def test_reverse_success(self, basic_movement):
        reversed_movement = basic_movement.reverse("carol", "Error correction")
        assert reversed_movement.movement_id != basic_movement.movement_id
        assert reversed_movement.movement_type == MovementType.PURCHASE_RETURN  # reversal of receipt
        assert reversed_movement.quantity == basic_movement.quantity
        assert reversed_movement.unit_cost == basic_movement.unit_cost
        assert reversed_movement.reference_document_id == basic_movement.movement_id
        assert "Reversal of RCV-001: Error correction" in reversed_movement.description
        assert reversed_movement.status == MovementStatus.CONFIRMED
        assert len(reversed_movement._audit_trail) == 1

    def test_reverse_non_confirmed_raises(self, basic_movement):
        draft = MovementEntity(
            movement_id=uuid4(),
            movement_type=MovementType.PURCHASE_RECEIPT,
            movement_number="RCV-001",
            item_id=uuid4(),
            item_sku="ITEM",
            item_name="Test",
            warehouse_id=uuid4(),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            movement_date=date.today(),
            status=MovementStatus.DRAFT,
            reference_document_type="PO",
            reference_document_id=uuid4(),
            reference_document_number="PO-001",
            created_by="alice",
            created_at=datetime.now(UTC),
            version=1,
        )
        with pytest.raises(ValueError, match="Cannot reverse movement in status draft"):
            draft.reverse("carol", "test")


# ----------------------------------------------------------------------
# MovementEntity - Serialization
# ----------------------------------------------------------------------
class TestMovementEntitySerialization:
    def test_to_dict(self, basic_movement):
        d = basic_movement.to_dict()
        assert d["movement_id"] == str(basic_movement.movement_id)
        assert d["movement_type"] == "purchase_receipt"
        assert d["movement_number"] == "RCV-001"
        assert d["quantity"] == "10"
        assert d["unit_cost"] == "100"
        assert d["total_cost"] == "1000"
        assert d["status"] == "confirmed"
        assert d["version"] == 1

    def test_from_dict(self, basic_movement):
        d = basic_movement.to_dict()
        # Add created_at for from_dict
        d["created_at"] = basic_movement.created_at.isoformat()
        reconstructed = MovementEntity.from_dict(d)
        assert reconstructed.movement_id == basic_movement.movement_id
        assert reconstructed.movement_type == basic_movement.movement_type
        assert reconstructed.quantity == basic_movement.quantity
        assert reconstructed.unit_cost == basic_movement.unit_cost
        assert reconstructed.status == basic_movement.status

    def test_from_dict_with_none_values(self):
        data = {
            "movement_id": str(uuid4()),
            "movement_type": "purchase_receipt",
            "movement_number": "RCV-001",
            "item_id": str(uuid4()),
            "warehouse_id": str(uuid4()),
            "quantity": "10",
            "unit_cost": "100",
            "status": "confirmed",
            "movement_date": "2025-01-15",
            "created_at": datetime.now(UTC).isoformat(),
        }
        movement = MovementEntity.from_dict(data)
        assert movement.movement_id is not None
        assert movement.item_id is not None
        assert movement.warehouse_id is not None


# ----------------------------------------------------------------------
# MovementEntity - Audit Trail
# ----------------------------------------------------------------------
class TestMovementEntityAudit:
    def test_audit_trail_created_on_factory_methods(self, item_id, warehouse_id):
        movement = MovementEntity.create_receipt(
            item_id=item_id,
            item_sku="ITEM",
            item_name="Test",
            warehouse_id=warehouse_id,
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            movement_date=date.today(),
            reference_document_type="PO",
            reference_document_id=uuid4(),
            reference_document_number="PO-001",
            created_by="alice",
        )
        assert len(movement._audit_trail) == 1
        assert movement._audit_trail[0]["action"] == "create_receipt"

    def test_audit_trail_appends_on_business_methods(self, basic_movement):
        # Confirm adds audit
        confirmed = basic_movement.confirm("alice")  # but basic_movement is already confirmed, so this will raise
        # Instead, create a draft and confirm
        draft = MovementEntity(
            movement_id=uuid4(),
            movement_type=MovementType.PURCHASE_RECEIPT,
            movement_number="RCV-001",
            item_id=uuid4(),
            item_sku="ITEM",
            item_name="Test",
            warehouse_id=uuid4(),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            movement_date=date.today(),
            status=MovementStatus.DRAFT,
            reference_document_type="PO",
            reference_document_id=uuid4(),
            reference_document_number="PO-001",
            created_by="alice",
            created_at=datetime.now(UTC),
            version=1,
        )
        assert len(draft._audit_trail) == 1  # initial
        confirmed = draft.confirm("alice")
        assert len(confirmed._audit_trail) == 2  # initial + confirm


# ----------------------------------------------------------------------
# MovementRepository (Interface)
# ----------------------------------------------------------------------
class TestMovementRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = MovementRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_item_not_implemented(self):
        repo = MovementRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_item(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_reference_not_implemented(self):
        repo = MovementRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_reference("PO", uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_warehouse_not_implemented(self):
        repo = MovementRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_warehouse(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_batch_not_implemented(self):
        repo = MovementRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_batch("BATCH-001", uuid4())

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = MovementRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = MovementRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ----------------------------------------------------------------------
# MovementEntity - Edge Cases
# ----------------------------------------------------------------------
class TestMovementEntityEdgeCases:
    def test_negative_unit_cost_raises(self):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            MovementEntity(
                movement_id=uuid4(),
                movement_type=MovementType.PURCHASE_RECEIPT,
                movement_number="RCV-001",
                item_id=uuid4(),
                item_sku="ITEM",
                item_name="Test",
                warehouse_id=uuid4(),
                quantity=Decimal("10"),
                unit_cost=Decimal("-100"),
                movement_date=date.today(),
                status=MovementStatus.DRAFT,
                reference_document_type="PO",
                reference_document_id=uuid4(),
                reference_document_number="PO-001",
                created_by="alice",
                created_at=datetime.now(UTC),
                version=1,
            )

    def test_movement_type_required(self):
        with pytest.raises(ValueError, match="Movement type is required"):
            MovementEntity(
                movement_id=uuid4(),
                movement_type=None,  # type: ignore
                movement_number="RCV-001",
                item_id=uuid4(),
                item_sku="ITEM",
                item_name="Test",
                warehouse_id=uuid4(),
                quantity=Decimal("10"),
                unit_cost=Decimal("100"),
                movement_date=date.today(),
                status=MovementStatus.DRAFT,
                reference_document_type="PO",
                reference_document_id=uuid4(),
                reference_document_number="PO-001",
                created_by="alice",
                created_at=datetime.now(UTC),
                version=1,
            )

    def test_large_quantity_and_cost(self, item_id, warehouse_id):
        movement = MovementEntity.create_receipt(
            item_id=item_id,
            item_sku="ITEM",
            item_name="Test",
            warehouse_id=warehouse_id,
            quantity=Decimal("999999.999"),
            unit_cost=Decimal("999999.999"),
            movement_date=date.today(),
            reference_document_type="PO",
            reference_document_id=uuid4(),
            reference_document_number="PO-001",
        )
        expected_total = Decimal("999999.999") * Decimal("999999.999")
        assert movement.total_cost == expected_total