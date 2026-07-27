# tests/domain/project_services/test_cost_entry_vo.py
"""
Comprehensive unit tests for CostEntryVO value object.

Covers:
- Construction with valid and invalid data
- Validation: amount, project_id, cost_type, created_at timezone
- Serialization: to_dict and from_dict (round-trip, missing fields)
- Immutable update methods: with_amount, with_description, with_cost_type, with_metadata
- Enum handling (CostType)
- Default values (id, created_at, currency, etc.)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from domain.project_services.cost_entry_vo import CostEntryVO, CostType


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def cost_entry_kwargs(project_id) -> dict[str, Any]:
    """Valid keyword arguments for creating a CostEntryVO."""
    return {
        "project_id": project_id,
        "amount": Decimal("1500.50"),
        "currency": "USD",
        "cost_type": CostType.MATERIAL,
        "description": "Raw materials for project",
        "entry_date": date(2026, 1, 15),
        "id": uuid4(),
        "created_at": datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.UTC),
        "created_by": uuid4(),
        "metadata": {"source": "purchase_order", "po_id": "PO-123"},
    }


@pytest.fixture
def cost_entry(cost_entry_kwargs) -> CostEntryVO:
    """A fully initialized CostEntryVO."""
    return CostEntryVO(**cost_entry_kwargs)


# -----------------------------------------------------------------------------
# Tests for CostType Enum
# -----------------------------------------------------------------------------

class TestCostType:
    def test_members(self):
        assert CostType.MATERIAL.value == "material"
        assert CostType.LABOR.value == "labor"
        assert CostType.OVERHEAD.value == "overhead"
        assert CostType.EQUIPMENT.value == "equipment"
        assert CostType.SUBCONTRACT.value == "subcontract"
        assert CostType.OTHER.value == "other"

    def test_str_enum_behavior(self):
        # CostType is a str enum, so it can be compared to strings
        assert CostType("material") == CostType.MATERIAL
        assert str(CostType.MATERIAL) == "material"
        assert CostType.MATERIAL.value == "material"


# -----------------------------------------------------------------------------
# Tests for CostEntryVO
# -----------------------------------------------------------------------------

class TestCostEntryVO:
    """Test the CostEntryVO immutable value object."""

    def test_construction_success(self, cost_entry, cost_entry_kwargs):
        assert cost_entry.project_id == cost_entry_kwargs["project_id"]
        assert cost_entry.amount == cost_entry_kwargs["amount"]
        assert cost_entry.currency == cost_entry_kwargs["currency"]
        assert cost_entry.cost_type == cost_entry_kwargs["cost_type"]
        assert cost_entry.description == cost_entry_kwargs["description"]
        assert cost_entry.entry_date == cost_entry_kwargs["entry_date"]
        assert cost_entry.id == cost_entry_kwargs["id"]
        assert cost_entry.created_at == cost_entry_kwargs["created_at"]
        assert cost_entry.created_by == cost_entry_kwargs["created_by"]
        assert cost_entry.metadata == cost_entry_kwargs["metadata"]

    def test_default_values(self, project_id):
        """Test that default values are set correctly."""
        entry = CostEntryVO(
            project_id=project_id,
            amount=Decimal("100.00"),
        )
        assert entry.currency == "IDR"
        assert entry.cost_type == CostType.OTHER
        assert entry.description == ""
        assert entry.entry_date == date.today()
        assert entry.id is not None
        assert isinstance(entry.id, UUID)
        assert entry.created_at is not None
        assert entry.created_at.tzinfo is not None
        assert entry.created_at.tzinfo == timezone.UTC
        assert entry.created_by is None
        assert entry.metadata == {}

    def test_created_at_timezone_auto_fix(self, project_id):
        """If created_at is naive, __post_init__ converts it to UTC."""
        naive = datetime(2026, 1, 15, 10, 30)  # no tzinfo
        entry = CostEntryVO(
            project_id=project_id,
            amount=Decimal("100"),
            created_at=naive,
        )
        assert entry.created_at.tzinfo is not None
        assert entry.created_at.tzinfo == timezone.UTC
        # The time should be preserved (converted to UTC, not shifted)
        assert entry.created_at == naive.replace(tzinfo=timezone.UTC)

    # ---- Validation ----

    def test_negative_amount_raises(self, project_id):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            CostEntryVO(
                project_id=project_id,
                amount=Decimal("-1"),
            )

    def test_zero_amount_allowed(self, project_id):
        """Amount can be zero (valid)."""
        entry = CostEntryVO(
            project_id=project_id,
            amount=Decimal("0"),
        )
        assert entry.amount == Decimal("0")

    def test_missing_project_id_raises(self):
        with pytest.raises(ValueError, match="project_id is required"):
            CostEntryVO(
                project_id=None,  # type: ignore
                amount=Decimal("100"),
            )

    def test_invalid_cost_type_raises(self, project_id):
        with pytest.raises(ValueError, match="cost_type must be a CostType enum"):
            CostEntryVO(
                project_id=project_id,
                amount=Decimal("100"),
                cost_type="material",  # type: ignore
            )

    # ---- Serialization ----

    def test_to_dict(self, cost_entry):
        d = cost_entry.to_dict()
        assert d["id"] == str(cost_entry.id)
        assert d["project_id"] == str(cost_entry.project_id)
        assert d["amount"] == str(cost_entry.amount)
        assert d["currency"] == cost_entry.currency
        assert d["cost_type"] == cost_entry.cost_type.value
        assert d["description"] == cost_entry.description
        assert d["entry_date"] == cost_entry.entry_date.isoformat()
        assert d["created_at"] == cost_entry.created_at.isoformat()
        assert d["created_by"] == str(cost_entry.created_by)
        assert d["metadata"] == cost_entry.metadata

    def test_from_dict_round_trip(self, cost_entry):
        d = cost_entry.to_dict()
        restored = CostEntryVO.from_dict(d)
        assert restored == cost_entry

    def test_from_dict_with_missing_fields(self, project_id):
        """Test from_dict with only required fields."""
        data = {
            "project_id": str(project_id),
            "amount": "250.75",
        }
        entry = CostEntryVO.from_dict(data)
        assert entry.project_id == project_id
        assert entry.amount == Decimal("250.75")
        assert entry.currency == "IDR"          # default
        assert entry.cost_type == CostType.OTHER  # default
        assert entry.description == ""
        # entry_date defaults to today
        assert entry.entry_date == date.today()
        # id is auto-generated
        assert entry.id is not None
        # created_at is set to now (with tz)
        assert entry.created_at is not None
        assert entry.created_at.tzinfo == timezone.UTC
        assert entry.created_by is None
        assert entry.metadata == {}

    def test_from_dict_with_invalid_cost_type_fallback(self, project_id):
        """If cost_type string is invalid, fallback to CostType.OTHER."""
        data = {
            "project_id": str(project_id),
            "amount": "100",
            "cost_type": "unknown_type",
        }
        entry = CostEntryVO.from_dict(data)
        assert entry.cost_type == CostType.OTHER

    def test_from_dict_with_invalid_created_at_fallback(self, project_id):
        """If created_at is not parseable, fallback to current UTC time."""
        data = {
            "project_id": str(project_id),
            "amount": "100",
            "created_at": "invalid-date",
        }
        entry = CostEntryVO.from_dict(data)
        # Should not raise, and created_at should be set to a valid datetime (now)
        assert entry.created_at is not None
        assert entry.created_at.tzinfo == timezone.UTC

    def test_from_dict_with_missing_id_auto_generates(self, project_id):
        data = {
            "project_id": str(project_id),
            "amount": "100",
        }
        entry = CostEntryVO.from_dict(data)
        assert entry.id is not None
        assert isinstance(entry.id, UUID)

    # ---- Immutable update methods ----

    def test_with_amount(self, cost_entry):
        new_amount = Decimal("2000.00")
        new_entry = cost_entry.with_amount(new_amount)
        assert new_entry is not cost_entry
        assert new_entry.amount == new_amount
        # Other fields unchanged
        assert new_entry.project_id == cost_entry.project_id
        assert new_entry.currency == cost_entry.currency
        assert new_entry.cost_type == cost_entry.cost_type
        assert new_entry.description == cost_entry.description
        assert new_entry.entry_date == cost_entry.entry_date
        assert new_entry.id == cost_entry.id
        assert new_entry.created_at == cost_entry.created_at
        assert new_entry.created_by == cost_entry.created_by
        assert new_entry.metadata == cost_entry.metadata

    def test_with_amount_raises_for_negative(self, cost_entry):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            cost_entry.with_amount(Decimal("-10"))

    def test_with_description(self, cost_entry):
        new_desc = "Updated description"
        new_entry = cost_entry.with_description(new_desc)
        assert new_entry is not cost_entry
        assert new_entry.description == new_desc
        assert new_entry.amount == cost_entry.amount

    def test_with_cost_type(self, cost_entry):
        new_type = CostType.LABOR
        new_entry = cost_entry.with_cost_type(new_type)
        assert new_entry is not cost_entry
        assert new_entry.cost_type == new_type
        assert new_entry.amount == cost_entry.amount

    def test_with_metadata(self, cost_entry):
        extra_meta = {"approval": "approved", "priority": "high"}
        new_entry = cost_entry.with_metadata(extra_meta)
        assert new_entry is not cost_entry
        expected = cost_entry.metadata.copy()
        expected.update(extra_meta)
        assert new_entry.metadata == expected
        # Original unchanged
        assert cost_entry.metadata != expected
        # Other fields unchanged
        assert new_entry.amount == cost_entry.amount

    def test_with_metadata_empty(self, cost_entry):
        new_entry = cost_entry.with_metadata({})
        assert new_entry is not cost_entry
        assert new_entry.metadata == cost_entry.metadata  # unchanged

    # ---- Additional edge cases ----

    def test_equality(self, cost_entry, cost_entry_kwargs):
        """Two instances with same data should be equal."""
        same = CostEntryVO(**cost_entry_kwargs)
        assert cost_entry == same
        # Different amount -> not equal
        diff = cost_entry.with_amount(Decimal("999"))
        assert cost_entry != diff

    def test_immutability(self, cost_entry):
        """Ensure the object is truly frozen (cannot modify attributes)."""
        with pytest.raises(AttributeError):
            cost_entry.amount = Decimal("999")  # type: ignore
        with pytest.raises(AttributeError):
            cost_entry.metadata["new"] = "value"  # type: ignore - metadata is a dict, but frozen prevents assignment to attribute, not mutation of dict.
        # However, metadata is a dict, and we can mutate it, but we shouldn't.
        # In practice, we use with_metadata to update.