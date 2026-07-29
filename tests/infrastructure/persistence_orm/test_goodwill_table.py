# tests/infrastructure/persistence_orm/test_goodwill_table.py
"""
Comprehensive unit tests for infrastructure/persistence_orm/goodwill_table.py.
Covers all properties and methods of GoodwillTable, including edge cases.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.goodwill_table import GoodwillTable

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_impairments():
    """Create a list of mock impairment objects."""
    imp1 = MagicMock()
    imp1.impairment_loss = Decimal("1000")
    imp2 = MagicMock()
    imp2.impairment_loss = Decimal("500")
    return [imp1, imp2]


@pytest.fixture
def goodwill_table(mock_impairments):
    """Create a GoodwillTable instance with sample data."""
    with patch("infrastructure.persistence_orm.goodwill_table.datetime") as mock_dt:
        mock_dt.utcnow.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        obj = GoodwillTable(
            id=uuid4(),
            goodwill_code="GW-001",
            name="Test Goodwill",
            description="Test description",
            acquisition_date=date(2025, 1, 1),
            acquiree_name="Acquiree Corp",
            acquiree_tax_id="1234567890",
            purchase_price=Decimal("1000000"),
            fair_value_identifiable_net_assets=Decimal("800000"),
            goodwill_initial=Decimal("200000"),
            carrying_amount=Decimal("180000"),
            currency="IDR",
            exchange_rate_at_acquisition=Decimal("1.0"),
            cash_generating_unit="CGU-A",
            allocated_to_segment="Segment A",
            status="active",
            is_active=True,
            acquisition_transaction_id=uuid4(),
            last_impairment_date=None,
            last_impairment_loss=None,
            created_by=uuid4(),
            approved_by=None,
            approved_at=None,
            legal_entity_id=uuid4(),
            version=1,
            # Relationship will be set later
        )
        # Manually set impairments relationship
        obj.impairments = mock_impairments
        # Mock increment_version to avoid side effects
        obj.increment_version = MagicMock()
        return obj


# ============================================================================
# Table metadata tests
# ============================================================================

class TestGoodwillTableMetadata:
    def test_tablename_defined(self):
        assert hasattr(GoodwillTable, "__tablename__")
        assert isinstance(GoodwillTable.__tablename__, str)
        assert GoodwillTable.__tablename__ == "goodwill"

    def test_table_args_defined(self):
        assert hasattr(GoodwillTable, "__table_args__")
        args = GoodwillTable.__table_args__
        assert isinstance(args, tuple)
        # Check for constraints and indexes
        constraints = [arg for arg in args if hasattr(arg, "name")]
        assert len(constraints) > 0


# ============================================================================
# Property tests
# ============================================================================

class TestGoodwillTableProperties:
    def test_impairment_accumulated(self, goodwill_table):
        """impairment_accumulated should sum all impairment losses."""
        # Given two impairments of 1000 and 500
        assert goodwill_table.impairment_accumulated == Decimal("1500")

    def test_impairment_accumulated_empty(self, goodwill_table):
        """impairment_accumulated returns 0 when no impairments."""
        goodwill_table.impairments = []
        assert goodwill_table.impairment_accumulated == Decimal("0")

    def test_net_carrying_amount(self, goodwill_table):
        """net_carrying_amount = carrying_amount - impairment_accumulated."""
        assert goodwill_table.net_carrying_amount == Decimal("180000") - Decimal("1500") == Decimal("178500")

    def test_impairment_percentage(self, goodwill_table):
        """impairment_percentage = impairment_accumulated / goodwill_initial * 100."""
        expected = (Decimal("1500") / Decimal("200000")) * 100
        assert goodwill_table.impairment_percentage == expected

    def test_impairment_percentage_zero_initial(self, goodwill_table):
        """impairment_percentage returns 0 when initial goodwill is 0."""
        goodwill_table.goodwill_initial = Decimal("0")
        assert goodwill_table.impairment_percentage == Decimal("0")

    def test_is_fully_impaired_true_by_status(self, goodwill_table):
        """is_fully_impaired returns True if status is 'fully_impaired'."""
        goodwill_table.status = "fully_impaired"
        assert goodwill_table.is_fully_impaired is True

    def test_is_fully_impaired_true_by_net_zero(self, goodwill_table):
        """is_fully_impaired returns True if net_carrying_amount <= 0."""
        # Make impairments exceed carrying amount
        goodwill_table.carrying_amount = Decimal("1000")
        goodwill_table.impairments = [MagicMock(impairment_loss=Decimal("2000"))]
        assert goodwill_table.is_fully_impaired is True

    def test_is_fully_impaired_false(self, goodwill_table):
        """is_fully_impaired returns False when net > 0 and status not fully_impaired."""
        goodwill_table.carrying_amount = Decimal("1000")
        goodwill_table.impairments = [MagicMock(impairment_loss=Decimal("500"))]
        goodwill_table.status = "active"
        assert goodwill_table.is_fully_impaired is False

    def test_is_partially_impaired_true(self, goodwill_table):
        """is_partially_impaired returns True when impairment_accumulated > 0 and not fully impaired."""
        goodwill_table.impairments = [MagicMock(impairment_loss=Decimal("100"))]
        goodwill_table.carrying_amount = Decimal("1000")
        goodwill_table.status = "active"
        assert goodwill_table.is_partially_impaired is True

    def test_is_partially_impaired_false_no_impairment(self, goodwill_table):
        """is_partially_impaired returns False when no impairment."""
        goodwill_table.impairments = []
        assert goodwill_table.is_partially_impaired is False

    def test_is_partially_impaired_false_fully_impaired(self, goodwill_table):
        """is_partially_impaired returns False when fully impaired."""
        goodwill_table.status = "fully_impaired"
        goodwill_table.impairments = [MagicMock(impairment_loss=Decimal("100"))]
        assert goodwill_table.is_partially_impaired is False


# ============================================================================
# Method tests
# ============================================================================

class TestGoodwillTableMethods:
    def test_record_impairment_valid(self, goodwill_table):
        """record_impairment should reduce carrying_amount and update status."""
        initial_carrying = goodwill_table.carrying_amount
        impairment_loss = Decimal("30000")
        test_date = date(2026, 6, 1)
        recoverable_amount = Decimal("150000")

        goodwill_table.record_impairment(impairment_loss, test_date, recoverable_amount)

        assert goodwill_table.carrying_amount == initial_carrying - impairment_loss
        assert goodwill_table.last_impairment_date == test_date
        assert goodwill_table.last_impairment_loss == impairment_loss
        # Since carrying_amount is now 150000 (180000-30000), still > 0, status becomes partially_impaired
        assert goodwill_table.status == "partially_impaired"
        goodwill_table.increment_version.assert_called_once()

    def test_record_impairment_exceeds_carrying(self, goodwill_table):
        """record_impairment should cap loss at carrying_amount if loss exceeds it."""
        initial_carrying = goodwill_table.carrying_amount
        impairment_loss = Decimal("200000")  # > carrying
        test_date = date(2026, 6, 1)
        recoverable_amount = Decimal("0")

        goodwill_table.record_impairment(impairment_loss, test_date, recoverable_amount)

        assert goodwill_table.carrying_amount == 0
        assert goodwill_table.last_impairment_loss == initial_carrying
        assert goodwill_table.status == "fully_impaired"

    def test_record_impairment_negative_loss_raises(self, goodwill_table):
        """record_impairment should raise ValueError for negative loss."""
        with pytest.raises(ValueError, match="Impairment loss cannot be negative"):
            goodwill_table.record_impairment(Decimal("-100"), date.today(), Decimal("100"))

    def test_recover_impairment_valid(self, goodwill_table):
        """recover_impairment should increase carrying_amount and update status."""
        # Set initial state: partially impaired, carrying=1000, initial=2000, impairments=500
        goodwill_table.goodwill_initial = Decimal("2000")
        goodwill_table.carrying_amount = Decimal("1000")
        goodwill_table.impairments = [MagicMock(impairment_loss=Decimal("500"))]
        goodwill_table.status = "partially_impaired"
        recovery_amount = Decimal("500")
        reversal_date = date(2026, 6, 1)

        goodwill_table.recover_impairment(recovery_amount, reversal_date)

        assert goodwill_table.carrying_amount == Decimal("1500")
        # Status becomes active if impairment_accumulated > 0? Actually recover_impairment sets status based on impairment_accumulated.
        # Since impairment_accumulated is 500 (>0), status should be "partially_impaired"
        assert goodwill_table.status == "partially_impaired"
        goodwill_table.increment_version.assert_called_once()

    def test_recover_impairment_restores_to_active(self, goodwill_table):
        """recover_impairment sets status to 'active' if impairment_accumulated becomes 0."""
        goodwill_table.goodwill_initial = Decimal("2000")
        goodwill_table.carrying_amount = Decimal("1500")
        goodwill_table.impairments = []  # no impairments
        goodwill_table.status = "active"  # already active, but test
        recovery_amount = Decimal("500")
        reversal_date = date(2026, 6, 1)

        goodwill_table.recover_impairment(recovery_amount, reversal_date)

        assert goodwill_table.carrying_amount == Decimal("2000")
        assert goodwill_table.status == "active"

    def test_recover_impairment_raises_negative(self, goodwill_table):
        """recover_impairment raises ValueError for non-positive recovery."""
        with pytest.raises(ValueError, match="Recovery amount must be positive"):
            goodwill_table.recover_impairment(Decimal("-100"), date.today())

    def test_recover_impairment_raises_exceeds_original(self, goodwill_table):
        """recover_impairment raises ValueError if reversal exceeds original goodwill."""
        goodwill_table.goodwill_initial = Decimal("2000")
        goodwill_table.carrying_amount = Decimal("1500")
        with pytest.raises(ValueError, match="Reversal cannot exceed original goodwill"):
            goodwill_table.recover_impairment(Decimal("600"), date.today())

    def test_dispose(self, goodwill_table):
        """dispose should set status to 'disposed' and is_active False."""
        goodwill_table.dispose(disposal_date=date(2026, 1, 1))
        assert goodwill_table.status == "disposed"
        assert goodwill_table.is_active is False
        goodwill_table.increment_version.assert_called_once()

    def test_approve(self, goodwill_table):
        """approve should set approved_by and approved_at."""
        approver_id = uuid4()
        with patch("infrastructure.persistence_orm.goodwill_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
            goodwill_table.approve(approver_id)
        assert goodwill_table.approved_by == approver_id
        assert goodwill_table.approved_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        goodwill_table.increment_version.assert_called_once()

    def test_to_dict(self, goodwill_table):
        """to_dict should return a dictionary representation."""
        d = goodwill_table.to_dict()
        assert d["goodwill_code"] == "GW-001"
        assert d["name"] == "Test Goodwill"
        assert d["description"] == "Test description"
        assert d["acquisition_date"] == "2025-01-01"
        assert d["purchase_price"] == float(Decimal("1000000"))
        assert d["goodwill_initial"] == float(Decimal("200000"))
        assert d["carrying_amount"] == float(Decimal("180000"))
        assert d["status"] == "active"
        assert d["impairment_accumulated"] == float(Decimal("1500"))
        assert d["net_carrying_amount"] == float(Decimal("178500"))
        assert d["version"] == 1
        assert "id" in d
        assert "legal_entity_id" in d


# ============================================================================
# Edge cases
# ============================================================================

class TestGoodwillTableEdgeCases:
    def test_impairment_percentage_with_initial_zero(self, goodwill_table):
        goodwill_table.goodwill_initial = Decimal("0")
        assert goodwill_table.impairment_percentage == Decimal("0")

    def test_record_impairment_with_zero_loss(self, goodwill_table):
        """record_impairment with zero loss should not change carrying amount."""
        initial = goodwill_table.carrying_amount
        goodwill_table.record_impairment(Decimal("0"), date.today(), Decimal("100"))
        assert goodwill_table.carrying_amount == initial
        assert goodwill_table.status == "active"  # unchanged

    def test_recover_impairment_with_carrying_equal_original(self, goodwill_table):
        """recover_impairment should not exceed original."""
        goodwill_table.goodwill_initial = Decimal("2000")
        goodwill_table.carrying_amount = Decimal("2000")  # already at original
        with pytest.raises(ValueError, match="Reversal cannot exceed original goodwill"):
            goodwill_table.recover_impairment(Decimal("100"), date.today())

    def test_approve_with_existing_approver(self, goodwill_table):
        """approve should override previous approver."""
        prev = uuid4()
        goodwill_table.approved_by = prev
        new = uuid4()
        with patch("infrastructure.persistence_orm.goodwill_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
            goodwill_table.approve(new)
        assert goodwill_table.approved_by == new
        assert goodwill_table.approved_at is not None
