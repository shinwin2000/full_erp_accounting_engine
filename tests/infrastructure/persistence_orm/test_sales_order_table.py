# tests/infrastructure/persistence_orm/test_sales_order_table.py
"""
Comprehensive unit tests for infrastructure/persistence_orm/sales_order_table.py.
Covers all properties, methods, state transitions, and edge cases.
Uses direct instantiation without a DB session for testing model logic.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.sales_order_table import SalesOrderTable

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_sales_order():
    """Create a SalesOrderTable instance with default values."""
    return SalesOrderTable(
        id=uuid4(),
        so_number="SO-2026-001",
        so_date=date(2026, 1, 1),
        customer_id=uuid4(),
        total_amount=Decimal("1000000"),
        shipped_amount=Decimal("0"),
        invoiced_amount=Decimal("0"),
        paid_amount=Decimal("0"),
        tax_amount=Decimal("110000"),
        discount_amount=Decimal("0"),
        currency="IDR",
        expected_ship_date=date(2026, 1, 15),
        actual_ship_date=None,
        status="draft",
        description="Test sales order",
        approved_by=None,
        approved_at=None,
        shipping_term_days=7,
        payment_term_days=30,
        incoterm="FOB",
        reference_number="REF-001",
        notes="Test notes",
        created_by=uuid4(),
        legal_entity_id=uuid4(),
        version=1,
    )


@pytest.fixture
def sample_submitted_order(sample_sales_order):
    """Return a submitted sales order."""
    order = sample_sales_order
    order.status = "submitted"
    return order


@pytest.fixture
def sample_approved_order(sample_sales_order):
    """Return an approved sales order."""
    order = sample_sales_order
    order.status = "approved"
    order.approved_by = uuid4()
    order.approved_at = datetime.now(UTC)
    return order


# ============================================================================
# TABLE METADATA TESTS
# ============================================================================

class TestSalesOrderTableMetadata:
    def test_tablename_defined(self):
        assert hasattr(SalesOrderTable, "__tablename__")
        assert SalesOrderTable.__tablename__ == "sales_order"

    def test_table_args_defined(self):
        assert hasattr(SalesOrderTable, "__table_args__")
        args = SalesOrderTable.__table_args__
        assert isinstance(args, tuple)
        # Check for constraints and indexes
        constraints = [arg for arg in args if hasattr(arg, "name")]
        assert len(constraints) > 0


# ============================================================================
# INSTANTIATION TESTS
# ============================================================================

class TestSalesOrderTableInstantiation:
    def test_instantiation(self, sample_sales_order):
        assert isinstance(sample_sales_order, SalesOrderTable)
        assert sample_sales_order.so_number == "SO-2026-001"
        assert sample_sales_order.total_amount == Decimal("1000000")
        assert sample_sales_order.status == "draft"
        assert sample_sales_order.version == 1

    def test_instantiation_with_defaults(self):
        order = SalesOrderTable(
            so_number="SO-001",
            so_date=date.today(),
            customer_id=uuid4(),
            total_amount=Decimal("0"),
        )
        assert order.shipped_amount == Decimal("0")
        assert order.invoiced_amount == Decimal("0")
        assert order.paid_amount == Decimal("0")
        assert order.currency == "IDR"
        assert order.status == "draft"


# ============================================================================
# PROPERTY TESTS
# ============================================================================

class TestSalesOrderTableProperties:
    def test_outstanding_amount(self, sample_sales_order):
        assert sample_sales_order.outstanding_amount == Decimal("1000000") - Decimal("0")
        sample_sales_order.shipped_amount = Decimal("600000")
        assert sample_sales_order.outstanding_amount == Decimal("400000")

    def test_is_fully_shipped_when_status_fully_shipped(self, sample_sales_order):
        sample_sales_order.status = "fully_shipped"
        assert sample_sales_order.is_fully_shipped is True

    def test_is_fully_shipped_when_outstanding_zero(self, sample_sales_order):
        sample_sales_order.shipped_amount = sample_sales_order.total_amount
        sample_sales_order.status = "partially_shipped"  # status might be partially_shipped
        # is_fully_shipped returns True if status == fully_shipped OR outstanding <= 0
        assert sample_sales_order.is_fully_shipped is True

    def test_is_fully_shipped_false(self, sample_sales_order):
        sample_sales_order.shipped_amount = Decimal("500000")
        sample_sales_order.status = "partially_shipped"
        assert sample_sales_order.is_fully_shipped is False

    def test_is_approved_when_status_approved(self, sample_approved_order):
        assert sample_approved_order.is_approved is True

    def test_is_approved_false(self, sample_sales_order):
        assert sample_sales_order.is_approved is False

    def test_is_cancelled_when_status_cancelled(self, sample_sales_order):
        sample_sales_order.status = "cancelled"
        assert sample_sales_order.is_cancelled is True

    def test_is_cancelled_false(self, sample_sales_order):
        assert sample_sales_order.is_cancelled is False

    @patch("infrastructure.persistence_orm.sales_order_table.date")
    def test_days_to_expected_ship(self, mock_date, sample_sales_order):
        # Set today to 2026-01-10, expected_ship_date is 2026-01-15 => 5 days
        mock_date.today.return_value = date(2026, 1, 10)
        assert sample_sales_order.days_to_expected_ship == 5

        # Set today to 2026-01-20 (after expected) => returns 0 (max(0, delta))
        mock_date.today.return_value = date(2026, 1, 20)
        assert sample_sales_order.days_to_expected_ship == 0

    @patch("infrastructure.persistence_orm.sales_order_table.date")
    def test_days_to_expected_ship_none(self, mock_date, sample_sales_order):
        sample_sales_order.expected_ship_date = None
        assert sample_sales_order.days_to_expected_ship is None

    @patch("infrastructure.persistence_orm.sales_order_table.date")
    def test_is_overdue_shipment(self, mock_date, sample_sales_order):
        # Not overdue when expected_ship_date is None
        sample_sales_order.expected_ship_date = None
        assert sample_sales_order.is_overdue_shipment is False

        # Not overdue when status is fully_shipped or closed
        sample_sales_order.expected_ship_date = date(2026, 1, 15)
        sample_sales_order.status = "fully_shipped"
        assert sample_sales_order.is_overdue_shipment is False

        # Overdue when today > expected_ship_date and status not fully_shipped/closed
        mock_date.today.return_value = date(2026, 1, 20)
        sample_sales_order.status = "partially_shipped"
        assert sample_sales_order.is_overdue_shipment is True

        # Not overdue when today <= expected_ship_date
        mock_date.today.return_value = date(2026, 1, 10)
        assert sample_sales_order.is_overdue_shipment is False

    def test_remaining_to_invoice(self, sample_sales_order):
        sample_sales_order.shipped_amount = Decimal("300000")
        sample_sales_order.invoiced_amount = Decimal("100000")
        assert sample_sales_order.remaining_to_invoice == Decimal("200000")

        # If invoiced > shipped (shouldn't happen normally, but test formula)
        sample_sales_order.invoiced_amount = Decimal("500000")
        assert sample_sales_order.remaining_to_invoice == Decimal("-200000")


# ============================================================================
# METHOD TESTS
# ============================================================================

class TestSalesOrderTableMethods:
    def test_submit_success(self, sample_sales_order):
        sample_sales_order.submit()
        assert sample_sales_order.status == "submitted"
        assert sample_sales_order.version == 2

    def test_submit_invalid_state(self, sample_sales_order):
        sample_sales_order.status = "approved"
        with pytest.raises(ValueError, match="Cannot submit SO with status approved"):
            sample_sales_order.submit()

    def test_approve_success(self, sample_submitted_order):
        approver = uuid4()
        with patch("infrastructure.persistence_orm.sales_order_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
            sample_submitted_order.approve(approver)
        assert sample_submitted_order.status == "approved"
        assert sample_submitted_order.approved_by == approver
        assert sample_submitted_order.approved_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert sample_submitted_order.version == 2

    def test_approve_invalid_state(self, sample_sales_order):
        sample_sales_order.status = "draft"
        with pytest.raises(ValueError, match="Cannot approve SO with status draft"):
            sample_sales_order.approve(uuid4())

    def test_reject_success(self, sample_submitted_order):
        sample_submitted_order.reject()
        assert sample_submitted_order.status == "draft"
        assert sample_submitted_order.version == 2

    def test_reject_invalid_state(self, sample_sales_order):
        sample_sales_order.status = "approved"
        with pytest.raises(ValueError, match="Cannot reject SO with status approved"):
            sample_sales_order.reject()

    @patch("infrastructure.persistence_orm.sales_order_table.date")
    def test_record_shipment_partial(self, mock_date, sample_sales_order):
        mock_date.today.return_value = date(2026, 1, 10)
        sample_sales_order.record_shipment(Decimal("300000"))
        assert sample_sales_order.shipped_amount == Decimal("300000")
        assert sample_sales_order.status == "partially_shipped"
        assert sample_sales_order.actual_ship_date == date(2026, 1, 10)
        assert sample_sales_order.version == 2

    @patch("infrastructure.persistence_orm.sales_order_table.date")
    def test_record_shipment_full(self, mock_date, sample_sales_order):
        mock_date.today.return_value = date(2026, 1, 10)
        sample_sales_order.record_shipment(Decimal("1000000"))
        assert sample_sales_order.shipped_amount == Decimal("1000000")
        assert sample_sales_order.status == "fully_shipped"
        assert sample_sales_order.actual_ship_date == date(2026, 1, 10)

    @patch("infrastructure.persistence_orm.sales_order_table.date")
    def test_record_shipment_exceeds_total(self, mock_date, sample_sales_order):
        # If amount exceeds total, it should cap at total and set fully_shipped
        mock_date.today.return_value = date(2026, 1, 10)
        sample_sales_order.record_shipment(Decimal("1500000"))
        assert sample_sales_order.shipped_amount == Decimal("1000000")
        assert sample_sales_order.status == "fully_shipped"

    def test_record_shipment_negative_amount(self, sample_sales_order):
        with pytest.raises(ValueError, match="Shipment amount must be positive"):
            sample_sales_order.record_shipment(Decimal("-100"))

    def test_record_shipment_zero_amount(self, sample_sales_order):
        with pytest.raises(ValueError, match="Shipment amount must be positive"):
            sample_sales_order.record_shipment(Decimal("0"))

    def test_record_invoice_success(self, sample_sales_order):
        sample_sales_order.record_invoice(Decimal("500000"))
        assert sample_sales_order.invoiced_amount == Decimal("500000")
        assert sample_sales_order.version == 2

    def test_record_invoice_negative_amount(self, sample_sales_order):
        with pytest.raises(ValueError, match="Invoice amount must be positive"):
            sample_sales_order.record_invoice(Decimal("-100"))

    def test_record_invoice_zero_amount(self, sample_sales_order):
        with pytest.raises(ValueError, match="Invoice amount must be positive"):
            sample_sales_order.record_invoice(Decimal("0"))

    def test_record_payment_success(self, sample_sales_order):
        sample_sales_order.record_payment(Decimal("200000"))
        assert sample_sales_order.paid_amount == Decimal("200000")
        assert sample_sales_order.version == 2

    def test_record_payment_negative_amount(self, sample_sales_order):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            sample_sales_order.record_payment(Decimal("-50"))

    def test_record_payment_zero_amount(self, sample_sales_order):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            sample_sales_order.record_payment(Decimal("0"))

    def test_cancel_success(self, sample_sales_order):
        sample_sales_order.cancel()
        assert sample_sales_order.status == "cancelled"
        assert sample_sales_order.version == 2

    def test_cancel_already_cancelled(self, sample_sales_order):
        sample_sales_order.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot cancel SO with status cancelled"):
            sample_sales_order.cancel()

    def test_cancel_already_closed(self, sample_sales_order):
        sample_sales_order.status = "closed"
        with pytest.raises(ValueError, match="Cannot cancel SO with status closed"):
            sample_sales_order.cancel()

    def test_close_success(self, sample_sales_order):
        sample_sales_order.status = "fully_shipped"
        sample_sales_order.close()
        assert sample_sales_order.status == "closed"
        assert sample_sales_order.version == 2

    def test_close_invalid_state(self, sample_sales_order):
        sample_sales_order.status = "partially_shipped"
        with pytest.raises(ValueError, match="Cannot close SO with status partially_shipped"):
            sample_sales_order.close()


# ============================================================================
# EDGE CASES & NEGATIVE PATHS
# ============================================================================

class TestSalesOrderTableEdgeCases:
    def test_approve_with_none_uuid(self, sample_submitted_order):
        # The method expects UUID; passing None may be allowed if not type-checked.
        # We test that it stores the value as is (could be None).
        sample_submitted_order.approve(None)
        assert sample_submitted_order.approved_by is None
        # But it should not set approved_at if no approver? Actually the method doesn't validate.
        # The method sets approved_by and approved_at regardless.
        with patch("infrastructure.persistence_orm.sales_order_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
            sample_submitted_order.approve(None)
            assert sample_submitted_order.approved_at is not None  # it still sets datetime

    def test_record_shipment_exact_total(self, sample_sales_order):
        sample_sales_order.record_shipment(Decimal("1000000"))
        assert sample_sales_order.shipped_amount == Decimal("1000000")
        assert sample_sales_order.status == "fully_shipped"

    def test_record_multiple_shipments(self, sample_sales_order):
        sample_sales_order.record_shipment(Decimal("300000"))
        sample_sales_order.record_shipment(Decimal("400000"))
        assert sample_sales_order.shipped_amount == Decimal("700000")
        assert sample_sales_order.status == "partially_shipped"
        sample_sales_order.record_shipment(Decimal("300000"))
        assert sample_sales_order.shipped_amount == Decimal("1000000")
        assert sample_sales_order.status == "fully_shipped"

    def test_record_invoice_with_large_amount(self, sample_sales_order):
        sample_sales_order.record_invoice(Decimal("999999999999"))
        assert sample_sales_order.invoiced_amount == Decimal("999999999999")

    def test_record_payment_accumulation(self, sample_sales_order):
        sample_sales_order.record_payment(Decimal("100000"))
        sample_sales_order.record_payment(Decimal("200000"))
        assert sample_sales_order.paid_amount == Decimal("300000")

    def test_version_increment_on_each_operation(self, sample_sales_order):
        assert sample_sales_order.version == 1
        sample_sales_order.submit()
        assert sample_sales_order.version == 2
        sample_sales_order.reject()
        assert sample_sales_order.version == 3
        sample_sales_order.record_shipment(Decimal("100"))
        assert sample_sales_order.version == 4

    def test_remaining_to_invoice_when_no_shipment(self, sample_sales_order):
        assert sample_sales_order.remaining_to_invoice == Decimal("0")

    def test_is_overdue_shipment_with_expected_date_equal_today(self, sample_sales_order):
        with patch("infrastructure.persistence_orm.sales_order_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 15)
            sample_sales_order.expected_ship_date = date(2026, 1, 15)
            sample_sales_order.status = "partially_shipped"
            assert sample_sales_order.is_overdue_shipment is False

    def test_is_overdue_shipment_with_expected_date_past_but_closed(self, sample_sales_order):
        with patch("infrastructure.persistence_orm.sales_order_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 20)
            sample_sales_order.expected_ship_date = date(2026, 1, 15)
            sample_sales_order.status = "closed"
            assert sample_sales_order.is_overdue_shipment is False

    def test_days_to_expected_ship_with_expected_date_today(self, sample_sales_order):
        with patch("infrastructure.persistence_orm.sales_order_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 15)
            sample_sales_order.expected_ship_date = date(2026, 1, 15)
            assert sample_sales_order.days_to_expected_ship == 0

    def test_outstanding_amount_after_shipment_exceeds_total(self, sample_sales_order):
        sample_sales_order.record_shipment(Decimal("1500000"))
        assert sample_sales_order.outstanding_amount == Decimal("0")
