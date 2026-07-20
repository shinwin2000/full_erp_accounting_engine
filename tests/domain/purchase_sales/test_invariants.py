# domain/purchase_sales/test_invariants.py
"""
Comprehensive unit tests for Purchase & Sales invariants.

Covers:
- InvariantResult
- PurchaseOrderInvariants
- SalesOrderInvariants
- InvoiceInvariants
- GoodsReceiptInvariants
- DeliveryNoteInvariants
- PurchaseSalesInvariantEnforcer (async)
- PurchaseSalesInvariantsValidator (sync)
"""

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.purchase_sales.goods_receipt_note_entity import GoodsReceiptNoteEntity, GRNStatus
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
from domain.purchase_sales.purchase_invoice_entity import PurchaseInvoiceStatus
from domain.purchase_sales.purchase_order_entity import POStatus, PurchaseOrderEntity
from domain.purchase_sales.sales_delivery_note_entity import DeliveryStatus, SalesDeliveryNoteEntity
from domain.purchase_sales.sales_invoice_entity import SalesInvoiceStatus
from domain.purchase_sales.sales_order_entity import SalesOrderEntity, SOStatus

# =============================================================================
# Fixtures & helpers
# =============================================================================

@pytest.fixture
def sample_po():
    """Create a minimal PurchaseOrderEntity with one item."""
    po = MagicMock(spec=PurchaseOrderEntity)
    po.po_number = "PO-001"
    item = MagicMock()
    item.item_id = uuid4()
    item.item_code = "ITEM-01"
    item.quantity = Decimal("10")
    item.remaining_quantity = Decimal("10")
    po.items = [item]
    po.get_item = lambda item_id: item if item_id == item.item_id else None
    return po


@pytest.fixture
def sample_so():
    """Create a minimal SalesOrderEntity with one item."""
    so = MagicMock(spec=SalesOrderEntity)
    so.so_number = "SO-001"
    item = MagicMock()
    item.item_id = uuid4()
    item.item_code = "ITEM-02"
    item.quantity = Decimal("5")
    item.remaining_quantity = Decimal("5")
    so.items = [item]
    so.get_item = lambda item_id: item if item_id == item.item_id else None
    return so


@pytest.fixture
def sample_grn():
    """Create a minimal GoodsReceiptNoteEntity with one item."""
    grn = MagicMock(spec=GoodsReceiptNoteEntity)
    item = MagicMock()
    item.item_id = uuid4()
    item.quantity = Decimal("3")
    grn.items = [item]
    return grn


@pytest.fixture
def sample_delivery():
    """Create a minimal SalesDeliveryNoteEntity with one item."""
    delivery = MagicMock(spec=SalesDeliveryNoteEntity)
    item = MagicMock()
    item.item_id = uuid4()
    item.quantity = Decimal("2")
    delivery.items = [item]
    return delivery


# =============================================================================
# Tests for InvariantResult
# =============================================================================

class TestInvariantResult:
    def test_initialization_valid(self):
        result = InvariantResult()
        assert result.is_valid is True
        assert result.errors == []

    def test_initialization_with_errors(self):
        result = InvariantResult(is_valid=False, errors=["error1"])
        assert result.is_valid is False
        assert result.errors == ["error1"]

    def test_add_error(self, caplog):
        result = InvariantResult()
        result.add_error("test error")
        assert result.is_valid is False
        assert result.errors == ["test error"]
        assert "Invariant violation: test error" in caplog.text

    def test_merge_valid(self):
        result1 = InvariantResult()
        result2 = InvariantResult()
        merged = result1.merge(result2)
        assert merged.is_valid is True
        assert merged.errors == []

    def test_merge_invalid(self):
        result1 = InvariantResult()
        result2 = InvariantResult(is_valid=False, errors=["error A"])
        merged = result1.merge(result2)
        assert merged.is_valid is False
        assert merged.errors == ["error A"]

    def test_merge_multiple_errors(self):
        result1 = InvariantResult(is_valid=False, errors=["error1"])
        result2 = InvariantResult(is_valid=False, errors=["error2"])
        merged = result1.merge(result2)
        assert merged.is_valid is False
        assert merged.errors == ["error1", "error2"]

    def test_to_dict(self):
        result = InvariantResult(is_valid=False, errors=["e1", "e2"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["e1", "e2"]
        assert d["error_count"] == 2

    def test_bool_true(self):
        result = InvariantResult()
        assert bool(result) is True

    def test_bool_false(self):
        result = InvariantResult(is_valid=False)
        assert bool(result) is False


# =============================================================================
# Tests for PurchaseOrderInvariants
# =============================================================================

class TestPurchaseOrderInvariants:
    def test_validate_po_number_unique_valid(self):
        result = PurchaseOrderInvariants.validate_po_number_unique("PO-123", {"PO-456"})
        assert result.is_valid is True
        assert result.errors == []

    def test_validate_po_number_unique_duplicate(self):
        result = PurchaseOrderInvariants.validate_po_number_unique("PO-123", {"PO-123"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_po_quantity_valid(self, sample_po):
        result = PurchaseOrderInvariants.validate_po_quantity(sample_po)
        assert result.is_valid is True

    def test_validate_po_quantity_invalid_zero(self, sample_po):
        sample_po.items[0].quantity = Decimal("0")
        result = PurchaseOrderInvariants.validate_po_quantity(sample_po)
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_po_quantity_invalid_negative(self, sample_po):
        sample_po.items[0].quantity = Decimal("-5")
        result = PurchaseOrderInvariants.validate_po_quantity(sample_po)
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_receipt_quantity_valid(self, sample_po):
        item_id = sample_po.items[0].item_id
        result = PurchaseOrderInvariants.validate_receipt_quantity(
            sample_po, item_id, Decimal("3")
        )
        assert result.is_valid is True

    def test_validate_receipt_quantity_zero(self, sample_po):
        item_id = sample_po.items[0].item_id
        result = PurchaseOrderInvariants.validate_receipt_quantity(
            sample_po, item_id, Decimal("0")
        )
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_receipt_quantity_exceeds_remaining(self, sample_po):
        item_id = sample_po.items[0].item_id
        result = PurchaseOrderInvariants.validate_receipt_quantity(
            sample_po, item_id, Decimal("15")
        )
        assert result.is_valid is False
        assert "exceeds remaining" in result.errors[0]

    def test_validate_receipt_quantity_item_not_found(self, sample_po):
        unknown_id = uuid4()
        result = PurchaseOrderInvariants.validate_receipt_quantity(
            sample_po, unknown_id, Decimal("1")
        )
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    @pytest.mark.parametrize(
        "current,new,expected_valid",
        [
            (POStatus.DRAFT, POStatus.SUBMITTED, True),
            (POStatus.DRAFT, POStatus.CANCELLED, True),
            (POStatus.DRAFT, POStatus.APPROVED, False),
            (POStatus.SUBMITTED, POStatus.APPROVED, True),
            (POStatus.SUBMITTED, POStatus.CANCELLED, True),
            (POStatus.APPROVED, POStatus.PARTIALLY_RECEIVED, True),
            (POStatus.APPROVED, POStatus.FULLY_RECEIVED, True),
            (POStatus.PARTIALLY_RECEIVED, POStatus.FULLY_RECEIVED, True),
            (POStatus.FULLY_RECEIVED, POStatus.CLOSED, True),
            (POStatus.CLOSED, POStatus.CANCELLED, False),
            (POStatus.CANCELLED, POStatus.DRAFT, False),
        ],
    )
    def test_validate_po_status_transition(self, current, new, expected_valid):
        result = PurchaseOrderInvariants.validate_po_status_transition(current, new)
        assert result.is_valid is expected_valid
        if not expected_valid:
            assert "Invalid PO status transition" in result.errors[0]


# =============================================================================
# Tests for SalesOrderInvariants
# =============================================================================

class TestSalesOrderInvariants:
    def test_validate_so_number_unique_valid(self):
        result = SalesOrderInvariants.validate_so_number_unique("SO-123", {"SO-456"})
        assert result.is_valid is True

    def test_validate_so_number_unique_duplicate(self):
        result = SalesOrderInvariants.validate_so_number_unique("SO-123", {"SO-123"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_so_quantity_valid(self, sample_so):
        result = SalesOrderInvariants.validate_so_quantity(sample_so)
        assert result.is_valid is True

    def test_validate_so_quantity_zero(self, sample_so):
        sample_so.items[0].quantity = Decimal("0")
        result = SalesOrderInvariants.validate_so_quantity(sample_so)
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_delivery_quantity_valid(self, sample_so):
        item_id = sample_so.items[0].item_id
        result = SalesOrderInvariants.validate_delivery_quantity(
            sample_so, item_id, Decimal("2")
        )
        assert result.is_valid is True

    def test_validate_delivery_quantity_zero(self, sample_so):
        item_id = sample_so.items[0].item_id
        result = SalesOrderInvariants.validate_delivery_quantity(
            sample_so, item_id, Decimal("0")
        )
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_delivery_quantity_exceeds_remaining(self, sample_so):
        item_id = sample_so.items[0].item_id
        result = SalesOrderInvariants.validate_delivery_quantity(
            sample_so, item_id, Decimal("10")
        )
        assert result.is_valid is False
        assert "exceeds remaining" in result.errors[0]

    def test_validate_delivery_quantity_item_not_found(self, sample_so):
        unknown_id = uuid4()
        result = SalesOrderInvariants.validate_delivery_quantity(
            sample_so, unknown_id, Decimal("1")
        )
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    @pytest.mark.parametrize(
        "current,new,expected_valid",
        [
            (SOStatus.DRAFT, SOStatus.APPROVED, True),
            (SOStatus.DRAFT, SOStatus.CANCELLED, True),
            (SOStatus.APPROVED, SOStatus.PARTIALLY_DELIVERED, True),
            (SOStatus.APPROVED, SOStatus.FULLY_DELIVERED, True),
            (SOStatus.PARTIALLY_DELIVERED, SOStatus.FULLY_DELIVERED, True),
            (SOStatus.FULLY_DELIVERED, SOStatus.INVOICED, True),
            (SOStatus.INVOICED, SOStatus.CLOSED, True),
            (SOStatus.CLOSED, SOStatus.APPROVED, False),
            (SOStatus.CANCELLED, SOStatus.DRAFT, False),
        ],
    )
    def test_validate_so_status_transition(self, current, new, expected_valid):
        result = SalesOrderInvariants.validate_so_status_transition(current, new)
        assert result.is_valid is expected_valid
        if not expected_valid:
            assert "Invalid SO status transition" in result.errors[0]


# =============================================================================
# Tests for InvoiceInvariants
# =============================================================================

class TestInvoiceInvariants:
    def test_validate_invoice_number_unique_valid(self):
        result = InvoiceInvariants.validate_invoice_number_unique("INV-001", {"INV-002"})
        assert result.is_valid is True

    def test_validate_invoice_number_unique_duplicate(self):
        result = InvoiceInvariants.validate_invoice_number_unique("INV-001", {"INV-001"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_invoice_amount_valid(self):
        result = InvoiceInvariants.validate_invoice_amount(
            Decimal("100.00"), Decimal("100.00")
        )
        assert result.is_valid is True

    def test_validate_invoice_amount_mismatch(self):
        result = InvoiceInvariants.validate_invoice_amount(
            Decimal("100.00"), Decimal("99.99")
        )
        assert result.is_valid is False
        assert "does not match" in result.errors[0]

    def test_validate_invoice_amount_rounding_allowed(self):
        # difference less than 0.01 is allowed
        result = InvoiceInvariants.validate_invoice_amount(
            Decimal("100.00"), Decimal("99.999")  # difference 0.001
        )
        assert result.is_valid is True

    def test_validate_payment_amount_valid(self):
        result = InvoiceInvariants.validate_payment_amount(
            Decimal("50.00"), Decimal("100.00")
        )
        assert result.is_valid is True

    def test_validate_payment_amount_negative(self):
        result = InvoiceInvariants.validate_payment_amount(
            Decimal("-10.00"), Decimal("100.00")
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_payment_amount_exceeds_total(self):
        result = InvoiceInvariants.validate_payment_amount(
            Decimal("150.00"), Decimal("100.00")
        )
        assert result.is_valid is False
        assert "exceeds total" in result.errors[0]

    @pytest.mark.parametrize(
        "current,new,expected_valid",
        [
            (PurchaseInvoiceStatus.DRAFT, PurchaseInvoiceStatus.RECEIVED, True),
            (PurchaseInvoiceStatus.DRAFT, PurchaseInvoiceStatus.CANCELLED, True),
            (PurchaseInvoiceStatus.RECEIVED, PurchaseInvoiceStatus.VERIFIED, True),
            (PurchaseInvoiceStatus.RECEIVED, PurchaseInvoiceStatus.DISPUTED, True),
            (PurchaseInvoiceStatus.VERIFIED, PurchaseInvoiceStatus.APPROVED, True),
            (PurchaseInvoiceStatus.APPROVED, PurchaseInvoiceStatus.PAID, True),
            (PurchaseInvoiceStatus.PAID, PurchaseInvoiceStatus.CANCELLED, False),
            (PurchaseInvoiceStatus.DISPUTED, PurchaseInvoiceStatus.VERIFIED, True),
            (PurchaseInvoiceStatus.CANCELLED, PurchaseInvoiceStatus.DRAFT, False),
        ],
    )
    def test_validate_purchase_invoice_status_transition(self, current, new, expected_valid):
        result = InvoiceInvariants.validate_purchase_invoice_status_transition(current, new)
        assert result.is_valid is expected_valid
        if not expected_valid:
            assert "Invalid purchase invoice status transition" in result.errors[0]

    @pytest.mark.parametrize(
        "current,new,expected_valid",
        [
            (SalesInvoiceStatus.DRAFT, SalesInvoiceStatus.ISSUED, True),
            (SalesInvoiceStatus.DRAFT, SalesInvoiceStatus.CANCELLED, True),
            (SalesInvoiceStatus.ISSUED, SalesInvoiceStatus.SENT, True),
            (SalesInvoiceStatus.SENT, SalesInvoiceStatus.PARTIALLY_PAID, True),
            (SalesInvoiceStatus.SENT, SalesInvoiceStatus.FULLY_PAID, True),
            (SalesInvoiceStatus.PARTIALLY_PAID, SalesInvoiceStatus.FULLY_PAID, True),
            (SalesInvoiceStatus.FULLY_PAID, SalesInvoiceStatus.OVERDUE, False),
            (SalesInvoiceStatus.OVERDUE, SalesInvoiceStatus.PARTIALLY_PAID, True),
            (SalesInvoiceStatus.CANCELLED, SalesInvoiceStatus.DRAFT, False),
        ],
    )
    def test_validate_sales_invoice_status_transition(self, current, new, expected_valid):
        result = InvoiceInvariants.validate_sales_invoice_status_transition(current, new)
        assert result.is_valid is expected_valid
        if not expected_valid:
            assert "Invalid sales invoice status transition" in result.errors[0]


# =============================================================================
# Tests for GoodsReceiptInvariants
# =============================================================================

class TestGoodsReceiptInvariants:
    def test_validate_grn_quantity_valid(self, sample_grn, sample_po):
        # Make sure item_id matches
        grn_item = sample_grn.items[0]
        po_item = sample_po.items[0]
        grn_item.item_id = po_item.item_id
        grn_item.quantity = Decimal("3")
        result = GoodsReceiptInvariants.validate_grn_quantity(sample_grn, sample_po)
        assert result.is_valid is True

    def test_validate_grn_quantity_exceeds_po(self, sample_grn, sample_po):
        grn_item = sample_grn.items[0]
        po_item = sample_po.items[0]
        grn_item.item_id = po_item.item_id
        grn_item.quantity = Decimal("15")
        result = GoodsReceiptInvariants.validate_grn_quantity(sample_grn, sample_po)
        assert result.is_valid is False
        assert "exceeds PO quantity" in result.errors[0]

    def test_validate_grn_quantity_item_not_found(self, sample_grn, sample_po):
        # Different item id
        grn_item = sample_grn.items[0]
        grn_item.item_id = uuid4()
        result = GoodsReceiptInvariants.validate_grn_quantity(sample_grn, sample_po)
        assert result.is_valid is False
        assert "not found in PO" in result.errors[0]

    @pytest.mark.parametrize(
        "current,new,expected_valid",
        [
            (GRNStatus.DRAFT, GRNStatus.CONFIRMED, True),
            (GRNStatus.DRAFT, GRNStatus.CANCELLED, True),
            (GRNStatus.CONFIRMED, GRNStatus.CANCELLED, False),
            (GRNStatus.CANCELLED, GRNStatus.DRAFT, False),
        ],
    )
    def test_validate_grn_status_transition(self, current, new, expected_valid):
        result = GoodsReceiptInvariants.validate_grn_status_transition(current, new)
        assert result.is_valid is expected_valid
        if not expected_valid:
            assert "Invalid GRN status transition" in result.errors[0]


# =============================================================================
# Tests for DeliveryNoteInvariants
# =============================================================================

class TestDeliveryNoteInvariants:
    def test_validate_delivery_quantity_valid(self, sample_delivery, sample_so):
        del_item = sample_delivery.items[0]
        so_item = sample_so.items[0]
        del_item.item_id = so_item.item_id
        del_item.quantity = Decimal("2")
        result = DeliveryNoteInvariants.validate_delivery_quantity(sample_delivery, sample_so)
        assert result.is_valid is True

    def test_validate_delivery_quantity_exceeds_so(self, sample_delivery, sample_so):
        del_item = sample_delivery.items[0]
        so_item = sample_so.items[0]
        del_item.item_id = so_item.item_id
        del_item.quantity = Decimal("10")
        result = DeliveryNoteInvariants.validate_delivery_quantity(sample_delivery, sample_so)
        assert result.is_valid is False
        assert "exceeds SO quantity" in result.errors[0]

    def test_validate_delivery_quantity_item_not_found(self, sample_delivery, sample_so):
        del_item = sample_delivery.items[0]
        del_item.item_id = uuid4()
        result = DeliveryNoteInvariants.validate_delivery_quantity(sample_delivery, sample_so)
        assert result.is_valid is False
        assert "not found in SO" in result.errors[0]

    @pytest.mark.parametrize(
        "current,new,expected_valid",
        [
            (DeliveryStatus.DRAFT, DeliveryStatus.CONFIRMED, True),
            (DeliveryStatus.DRAFT, DeliveryStatus.CANCELLED, True),
            (DeliveryStatus.CONFIRMED, DeliveryStatus.SHIPPED, True),
            (DeliveryStatus.SHIPPED, DeliveryStatus.DELIVERED, True),
            (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED, False),
            (DeliveryStatus.CANCELLED, DeliveryStatus.DRAFT, False),
        ],
    )
    def test_validate_delivery_status_transition(self, current, new, expected_valid):
        result = DeliveryNoteInvariants.validate_delivery_status_transition(current, new)
        assert result.is_valid is expected_valid
        if not expected_valid:
            assert "Invalid delivery status transition" in result.errors[0]


# =============================================================================
# Tests for PurchaseSalesInvariantEnforcer (async)
# =============================================================================

@pytest.mark.asyncio
class TestPurchaseSalesInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        # Provide simple synchronous checkers (they return sets)
        def po_checker():
            return {"PO-001"}
        def so_checker():
            return {"SO-001"}
        def pi_checker():
            return {"PINV-001"}
        def si_checker():
            return {"SINV-001"}
        def grn_checker():
            return {"GRN-001"}
        def del_checker():
            return {"DEL-001"}
        return PurchaseSalesInvariantEnforcer(
            po_number_checker=po_checker,
            so_number_checker=so_checker,
            purchase_invoice_number_checker=pi_checker,
            sales_invoice_number_checker=si_checker,
            grn_number_checker=grn_checker,
            delivery_number_checker=del_checker,
        )

    async def test_enforce_po_create_unique(self, enforcer):
        result = await enforcer.enforce_po_create("PO-002")
        assert result.is_valid is True
        assert result.errors == []

    async def test_enforce_po_create_duplicate(self, enforcer):
        result = await enforcer.enforce_po_create("PO-001")
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_po_quantity_valid(self, enforcer, sample_po):
        result = await enforcer.enforce_po_quantity(sample_po)
        assert result.is_valid is True

    async def test_enforce_po_quantity_invalid(self, enforcer, sample_po):
        sample_po.items[0].quantity = Decimal("-1")
        result = await enforcer.enforce_po_quantity(sample_po)
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    async def test_enforce_po_receipt_valid(self, enforcer, sample_po):
        item_id = sample_po.items[0].item_id
        result = await enforcer.enforce_po_receipt(sample_po, item_id, Decimal("3"))
        assert result.is_valid is True

    async def test_enforce_po_receipt_exceeds(self, enforcer, sample_po):
        item_id = sample_po.items[0].item_id
        result = await enforcer.enforce_po_receipt(sample_po, item_id, Decimal("20"))
        assert result.is_valid is False
        assert "exceeds remaining" in result.errors[0]

    async def test_enforce_po_status_transition_valid(self, enforcer):
        result = await enforcer.enforce_po_status_transition(POStatus.DRAFT, POStatus.SUBMITTED)
        assert result.is_valid is True

    async def test_enforce_po_status_transition_invalid(self, enforcer):
        result = await enforcer.enforce_po_status_transition(POStatus.CLOSED, POStatus.DRAFT)
        assert result.is_valid is False
        assert "Invalid PO status transition" in result.errors[0]

    # Similar tests for SO, invoices, GRN, Delivery...
    # We'll add a few more representative tests.

    async def test_enforce_so_create(self, enforcer):
        result = await enforcer.enforce_so_create("SO-002")
        assert result.is_valid is True
        result = await enforcer.enforce_so_create("SO-001")
        assert result.is_valid is False

    async def test_enforce_purchase_invoice_create(self, enforcer):
        result = await enforcer.enforce_purchase_invoice_create("PINV-002")
        assert result.is_valid is True
        result = await enforcer.enforce_purchase_invoice_create("PINV-001")
        assert result.is_valid is False

    async def test_enforce_sales_invoice_create(self, enforcer):
        result = await enforcer.enforce_sales_invoice_create("SINV-002")
        assert result.is_valid is True
        result = await enforcer.enforce_sales_invoice_create("SINV-001")
        assert result.is_valid is False

    async def test_enforce_grn_create(self, enforcer):
        result = await enforcer.enforce_grn_create("GRN-002")
        assert result.is_valid is True
        result = await enforcer.enforce_grn_create("GRN-001")
        assert result.is_valid is False

    async def test_enforce_delivery_create(self, enforcer):
        result = await enforcer.enforce_delivery_create("DEL-002")
        assert result.is_valid is True
        result = await enforcer.enforce_delivery_create("DEL-001")
        assert result.is_valid is False

    async def test_enforce_grn_quantity_valid(self, enforcer, sample_grn, sample_po):
        grn_item = sample_grn.items[0]
        po_item = sample_po.items[0]
        grn_item.item_id = po_item.item_id
        grn_item.quantity = Decimal("3")
        result = await enforcer.enforce_grn_quantity(sample_grn, sample_po)
        assert result.is_valid is True

    async def test_enforce_delivery_quantity_valid(self, enforcer, sample_delivery, sample_so):
        del_item = sample_delivery.items[0]
        so_item = sample_so.items[0]
        del_item.item_id = so_item.item_id
        del_item.quantity = Decimal("2")
        result = await enforcer.enforce_delivery_quantity(sample_delivery, sample_so)
        assert result.is_valid is True


# =============================================================================
# Tests for PurchaseSalesInvariantsValidator (synchronous)
# =============================================================================

class TestPurchaseSalesInvariantsValidator:
    @pytest.fixture
    def validator(self):
        return PurchaseSalesInvariantsValidator()

    def test_validate_po_number_unique(self, validator):
        result = validator.validate_po_number_unique("PO-123", {"PO-456"})
        assert result.is_valid is True
        result = validator.validate_po_number_unique("PO-123", {"PO-123"})
        assert result.is_valid is False

    def test_validate_po_quantity(self, validator, sample_po):
        result = validator.validate_po_quantity(sample_po)
        assert result.is_valid is True
        sample_po.items[0].quantity = Decimal("0")
        result = validator.validate_po_quantity(sample_po)
        assert result.is_valid is False

    def test_validate_po_receipt(self, validator, sample_po):
        item_id = sample_po.items[0].item_id
        result = validator.validate_po_receipt(sample_po, item_id, Decimal("3"))
        assert result.is_valid is True
        result = validator.validate_po_receipt(sample_po, item_id, Decimal("20"))
        assert result.is_valid is False

    def test_validate_so_number_unique(self, validator):
        result = validator.validate_so_number_unique("SO-123", {"SO-456"})
        assert result.is_valid is True
        result = validator.validate_so_number_unique("SO-123", {"SO-123"})
        assert result.is_valid is False

    def test_validate_so_quantity(self, validator, sample_so):
        result = validator.validate_so_quantity(sample_so)
        assert result.is_valid is True
        sample_so.items[0].quantity = Decimal("-1")
        result = validator.validate_so_quantity(sample_so)
        assert result.is_valid is False

    def test_validate_so_delivery(self, validator, sample_so):
        item_id = sample_so.items[0].item_id
        result = validator.validate_so_delivery(sample_so, item_id, Decimal("2"))
        assert result.is_valid is True
        result = validator.validate_so_delivery(sample_so, item_id, Decimal("10"))
        assert result.is_valid is False

    def test_validate_invoice_number_unique(self, validator):
        result = validator.validate_invoice_number_unique("INV-001", {"INV-002"})
        assert result.is_valid is True
        result = validator.validate_invoice_number_unique("INV-001", {"INV-001"})
        assert result.is_valid is False

    def test_validate_invoice_amount(self, validator):
        result = validator.validate_invoice_amount(Decimal("100"), Decimal("100"))
        assert result.is_valid is True
        result = validator.validate_invoice_amount(Decimal("100"), Decimal("99"))
        assert result.is_valid is False

    def test_validate_payment_amount(self, validator):
        result = validator.validate_payment_amount(Decimal("50"), Decimal("100"))
        assert result.is_valid is True
        result = validator.validate_payment_amount(Decimal("150"), Decimal("100"))
        assert result.is_valid is False

    def test_validate_grn_quantity(self, validator, sample_grn, sample_po):
        grn_item = sample_grn.items[0]
        po_item = sample_po.items[0]
        grn_item.item_id = po_item.item_id
        grn_item.quantity = Decimal("3")
        result = validator.validate_grn_quantity(sample_grn, sample_po)
        assert result.is_valid is True
        grn_item.quantity = Decimal("15")
        result = validator.validate_grn_quantity(sample_grn, sample_po)
        assert result.is_valid is False

    def test_validate_delivery_quantity(self, validator, sample_delivery, sample_so):
        del_item = sample_delivery.items[0]
        so_item = sample_so.items[0]
        del_item.item_id = so_item.item_id
        del_item.quantity = Decimal("2")
        result = validator.validate_delivery_quantity(sample_delivery, sample_so)
        assert result.is_valid is True
        del_item.quantity = Decimal("10")
        result = validator.validate_delivery_quantity(sample_delivery, sample_so)
        assert result.is_valid is False
