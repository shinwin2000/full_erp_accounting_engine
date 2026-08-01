# tests/domain/purchase_sales/test_sales_return_entity.py
"""
Comprehensive unit tests for Sales Return Entity.

Covers:
- SalesReturnItem value object (construction, validation, properties, serialization)
- SalesReturnEntity (construction, validation, item management, status transitions, serialization)
- Repository protocol (abstract methods)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from domain.purchase_sales.sales_return_entity import (
    SalesReturnEntity,
    SalesReturnItem,
    SalesReturnReason,
    SalesReturnRepository,
    SalesReturnStatus,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def valid_item_kwargs() -> dict[str, Any]:
    """Valid arguments for creating a SalesReturnItem."""
    return {
        "item_id": uuid4(),
        "item_code": "ITEM-001",
        "item_name": "Test Product",
        "invoice_id": uuid4(),
        "invoice_item_id": uuid4(),
        "quantity": Decimal("5.000"),
        "unit_price": Decimal("100.00"),
        "reason": SalesReturnReason.DEFECTIVE,
        "condition": "RETURNED",
        "notes": "Defective batch",
    }


@pytest.fixture
def valid_item(valid_item_kwargs) -> SalesReturnItem:
    return SalesReturnItem(**valid_item_kwargs)


@pytest.fixture
def valid_return_kwargs(valid_item) -> dict[str, Any]:
    """Valid arguments for creating a SalesReturnEntity."""
    now = datetime.now(UTC)
    total = valid_item.total_amount  # 5 * 100 = 500
    return {
        "return_id": uuid4(),
        "return_number": "SR-2026-001",
        "invoice_id": uuid4(),
        "invoice_number": "INV-2026-001",
        "customer_id": uuid4(),
        "customer_name": "Customer ABC",
        "return_date": now,
        "status": SalesReturnStatus.DRAFT,
        "items": [valid_item],
        "total_amount": total,
        "credit_note_number": None,
        "approved_by": None,
        "approved_at": None,
        "completed_by": None,
        "completed_at": None,
        "notes": "Initial return",
        "created_at": now,
        "updated_at": now,
        "created_by": "tester",
        "version": 1,
    }


@pytest.fixture
def valid_return(valid_return_kwargs) -> SalesReturnEntity:
    return SalesReturnEntity(**valid_return_kwargs)


@pytest.fixture
def another_item() -> SalesReturnItem:
    return SalesReturnItem(
        item_id=uuid4(),
        item_code="ITEM-002",
        item_name="Another Product",
        invoice_id=uuid4(),
        invoice_item_id=uuid4(),
        quantity=Decimal("3.000"),
        unit_price=Decimal("200.00"),
        reason=SalesReturnReason.DAMAGED,
        condition="DAMAGED",
        notes="Damaged during transit",
    )


# -----------------------------------------------------------------------------
# Tests for SalesReturnItem (Value Object)
# -----------------------------------------------------------------------------

class TestSalesReturnItem:
    """Test the SalesReturnItem immutable value object."""

    def test_construction_success(self, valid_item_kwargs):
        item = SalesReturnItem(**valid_item_kwargs)
        assert isinstance(item, SalesReturnItem)
        assert item.item_id == valid_item_kwargs["item_id"]
        assert item.total_amount == Decimal("500.00")

    @pytest.mark.parametrize(
        "field, value, expected_error",
        [
            ("quantity", Decimal("0"), "Quantity must be positive"),
            ("quantity", Decimal("-1"), "Quantity must be positive"),
            ("unit_price", Decimal("-5"), "Unit price cannot be negative"),
            ("condition", "INVALID", "Invalid condition"),
        ],
    )
    def test_validation_raises(self, valid_item_kwargs, field, value, expected_error):
        kwargs = valid_item_kwargs.copy()
        kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            SalesReturnItem(**kwargs)

    def test_to_dict(self, valid_item):
        d = valid_item.to_dict()
        assert d["item_id"] == str(valid_item.item_id)
        assert d["item_code"] == valid_item.item_code
        assert d["quantity"] == str(valid_item.quantity)
        assert d["total_amount"] == str(valid_item.total_amount)
        assert d["reason"] == valid_item.reason.value
        assert d["condition"] == valid_item.condition


# -----------------------------------------------------------------------------
# Tests for SalesReturnEntity
# -----------------------------------------------------------------------------

class TestSalesReturnEntity:
    """Test the SalesReturnEntity aggregate."""

    def test_construction_success(self, valid_return_kwargs):
        entity = SalesReturnEntity(**valid_return_kwargs)
        assert entity.return_id == valid_return_kwargs["return_id"]
        assert entity.status == SalesReturnStatus.DRAFT
        assert entity.total_amount == Decimal("500.00")
        assert len(entity.items) == 1
        assert entity.version == 1

    @pytest.mark.parametrize(
        "field, value, expected_error",
        [
            ("return_number", "AB", "Return number must be at least 3"),
            ("return_date", None, "return_date must be timezone-aware"),
            ("total_amount", Decimal("-10"), "Total amount cannot be negative"),
            ("version", 0, "Version must be >= 1"),
        ],
    )
    def test_validation_raises(self, valid_return_kwargs, field, value, expected_error):
        kwargs = valid_return_kwargs.copy()
        if field == "return_date":
            kwargs["return_date"] = datetime.now()  # naive
            with pytest.raises(ValueError, match="return_date must be timezone-aware"):
                SalesReturnEntity(**kwargs)
            return
        kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            SalesReturnEntity(**kwargs)

    def test_total_amount_mismatch_raises(self, valid_return_kwargs, valid_item):
        # Set total_amount to a value that does not match items sum
        kwargs = valid_return_kwargs.copy()
        kwargs["total_amount"] = Decimal("999.00")  # but items sum is 500
        with pytest.raises(ValueError, match="Total amount .* does not match items total"):
            SalesReturnEntity(**kwargs)

    def test_timezone_aware_required(self, valid_return_kwargs):
        # approved_at naive
        kwargs = valid_return_kwargs.copy()
        kwargs["approved_at"] = datetime.now()
        with pytest.raises(ValueError, match="approved_at must be timezone-aware"):
            SalesReturnEntity(**kwargs)

        # completed_at naive
        kwargs = valid_return_kwargs.copy()
        kwargs["completed_at"] = datetime.now()
        with pytest.raises(ValueError, match="completed_at must be timezone-aware"):
            SalesReturnEntity(**kwargs)

    # ---- Item management ----

    def test_add_item(self, valid_return, another_item):
        old_total = valid_return.total_amount
        entity2 = valid_return.add_item(another_item, "tester")
        assert len(entity2.items) == len(valid_return.items) + 1
        assert entity2.items[-1] == another_item
        assert entity2.total_amount == old_total + another_item.total_amount
        assert entity2.version == valid_return.version + 1
        assert entity2.updated_at > valid_return.updated_at
        assert entity2.created_by == "tester"

    def test_remove_item(self, valid_return):
        """Test removal of an item - previously untested."""
        item_id = valid_return.items[0].item_id
        entity2 = valid_return.remove_item(item_id, "remover")
        assert len(entity2.items) == 0
        assert entity2.total_amount == Decimal(0)
        assert entity2.version == valid_return.version + 1
        assert entity2.created_by == "remover"

        # Removing non-existent item should do nothing (item not found -> no change)
        entity3 = valid_return.remove_item(uuid4(), "remover")
        assert entity3 is not valid_return
        assert len(entity3.items) == len(valid_return.items)
        assert entity3.total_amount == valid_return.total_amount
        assert entity3.version == valid_return.version + 1  # still increments version

    # ---- Status transitions ----

    def test_approve(self, valid_return):
        entity2 = valid_return.approve("approver")
        assert entity2.status == SalesReturnStatus.APPROVED
        assert entity2.approved_by == "approver"
        assert entity2.approved_at is not None
        assert entity2.version == valid_return.version + 1
        # Cannot approve twice
        with pytest.raises(ValueError, match="Cannot approve return in status approved"):
            entity2.approve("another")

    def test_complete(self, valid_return):
        # First approve
        approved = valid_return.approve("approver")
        entity2 = approved.complete("completer", "CN-2026-001")
        assert entity2.status == SalesReturnStatus.COMPLETED
        assert entity2.completed_by == "completer"
        assert entity2.completed_at is not None
        assert entity2.credit_note_number == "CN-2026-001"
        assert entity2.version == approved.version + 1
        # Cannot complete from DRAFT
        with pytest.raises(ValueError, match="Cannot complete return in status draft"):
            valid_return.complete("completer")

    def test_complete_without_credit_note(self, valid_return):
        approved = valid_return.approve("approver")
        entity2 = approved.complete("completer")
        assert entity2.credit_note_number is None

    def test_cancel(self, valid_return):
        # Cancel from DRAFT
        entity2 = valid_return.cancel("canceller", "Test reason")
        assert entity2.status == SalesReturnStatus.CANCELLED
        assert "Cancelled: Test reason" in entity2.notes
        assert entity2.version == valid_return.version + 1

        # Cannot cancel from COMPLETED
        approved = valid_return.approve("approver")
        completed = approved.complete("completer")
        with pytest.raises(ValueError, match="Cannot cancel return in status completed"):
            completed.cancel("canceller", "reason")

        # Cannot cancel from CANCELLED
        with pytest.raises(ValueError, match="Cannot cancel return in status cancelled"):
            entity2.cancel("canceller", "again")

    # ---- Serialization ----

    def test_to_dict(self, valid_return):
        d = valid_return.to_dict()
        assert d["return_id"] == str(valid_return.return_id)
        assert d["return_number"] == valid_return.return_number
        assert d["status"] == valid_return.status.value
        assert d["total_amount"] == str(valid_return.total_amount)
        assert len(d["items"]) == 1
        assert d["version"] == valid_return.version
        # Check timestamps
        assert "created_at" in d
        assert "updated_at" in d


# -----------------------------------------------------------------------------
# Tests for Repository Protocol
# -----------------------------------------------------------------------------

class TestSalesReturnRepository:
    """Test the abstract repository protocol."""

    def test_methods_raise_not_implemented(self):
        repo = SalesReturnRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("SR-123", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_invoice(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_customer(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
