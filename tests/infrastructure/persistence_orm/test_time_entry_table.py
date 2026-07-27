# tests/infrastructure/persistence_orm/test_time_entry_table.py
# Comprehensive tests for TimeEntryTable ORM model

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from infrastructure.persistence_orm.time_entry_table import TimeEntryTable


class TestTimeEntryTable:
    """Tests for the TimeEntryTable ORM table model."""

    def test_tablename_defined(self):
        """ORM model declares a table name."""
        assert hasattr(TimeEntryTable, "__tablename__")
        assert isinstance(TimeEntryTable.__tablename__, str)
        assert len(TimeEntryTable.__tablename__) > 0

    def test_instantiation(self):
        """ORM model can be instantiated in-memory (without a DB session)."""
        instance = TimeEntryTable(
            id=uuid4(),
            employee_id=uuid4(),
            project_id=uuid4(),
            entry_date=date.today(),
            hours=Decimal("8.0"),
            hourly_rate=Decimal("150000"),
            total_cost=Decimal("1200000"),
            currency="IDR",
            description="Test entry",
            status="draft",
        )
        assert isinstance(instance, TimeEntryTable)
        assert instance.hours == Decimal("8.0")
        assert instance.hourly_rate == Decimal("150000")

    # -------------------- Property Tests --------------------
    def test_is_approved(self):
        entry = TimeEntryTable(status="approved")
        assert entry.is_approved is True
        entry.status = "draft"
        assert entry.is_approved is False

    def test_is_submitted(self):
        entry = TimeEntryTable(status="submitted")
        assert entry.is_submitted is True
        entry.status = "draft"
        assert entry.is_submitted is False

    def test_is_draft(self):
        entry = TimeEntryTable(status="draft")
        assert entry.is_draft is True
        entry.status = "submitted"
        assert entry.is_draft is False

    def test_is_rejected(self):
        entry = TimeEntryTable(status="rejected")
        assert entry.is_rejected is True
        entry.status = "draft"
        assert entry.is_rejected is False

    def test_is_billed(self):
        entry = TimeEntryTable(status="billed")
        assert entry.is_billed is True
        entry.status = "draft"
        assert entry.is_billed is False

    def test_effective_hourly_rate_no_overtime(self):
        entry = TimeEntryTable(
            hourly_rate=Decimal("100000"),
            overtime_multiplier=Decimal("1.5"),
            is_overtime=False,
        )
        assert entry.effective_hourly_rate == Decimal("100000")

    def test_effective_hourly_rate_with_overtime(self):
        entry = TimeEntryTable(
            hourly_rate=Decimal("100000"),
            overtime_multiplier=Decimal("1.5"),
            is_overtime=True,
        )
        assert entry.effective_hourly_rate == Decimal("150000")

    def test_effective_total_cost_no_overtime(self):
        entry = TimeEntryTable(
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            overtime_multiplier=Decimal("1.5"),
            is_overtime=False,
        )
        assert entry.effective_total_cost == Decimal("800000")

    def test_effective_total_cost_with_overtime(self):
        entry = TimeEntryTable(
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            overtime_multiplier=Decimal("1.5"),
            is_overtime=True,
        )
        assert entry.effective_total_cost == Decimal("1200000")

    def test_billable_amount_non_billable(self):
        entry = TimeEntryTable(
            is_billable=False,
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            billing_rate=Decimal("200000"),
        )
        assert entry.billable_amount == Decimal(0)

    def test_billable_amount_with_billing_rate(self):
        entry = TimeEntryTable(
            is_billable=True,
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            billing_rate=Decimal("200000"),
        )
        assert entry.billable_amount == Decimal("1600000")

    def test_billable_amount_without_billing_rate(self):
        entry = TimeEntryTable(
            is_billable=True,
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            billing_rate=None,
        )
        assert entry.billable_amount == Decimal("800000")

    def test_billable_amount_with_overtime(self):
        entry = TimeEntryTable(
            is_billable=True,
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            billing_rate=None,
            is_overtime=True,
            overtime_multiplier=Decimal("1.5"),
        )
        # effective hourly rate = 150000, so billable = 8 * 150000 = 1,200,000
        assert entry.billable_amount == Decimal("1200000")

    # -------------------- Method Tests --------------------
    def test_submit_from_draft(self):
        entry = TimeEntryTable(status="draft")
        entry.submit()
        assert entry.status == "submitted"
        assert entry.submitted_at is not None
        assert entry.version == 2  # assuming version starts at 1

    def test_submit_from_invalid_status_raises(self):
        entry = TimeEntryTable(status="submitted")
        with pytest.raises(ValueError, match="Cannot submit time entry with status submitted"):
            entry.submit()

    def test_approve_from_submitted(self):
        entry = TimeEntryTable(
            status="submitted",
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            is_overtime=False,
        )
        approver_id = uuid4()
        entry.approve(approver_id)
        assert entry.status == "approved"
        assert entry.approved_by == approver_id
        assert entry.approved_at is not None
        # Check that total_cost is recalculated
        assert entry.total_cost == Decimal("800000")
        assert entry.version == 2

    def test_approve_from_invalid_status_raises(self):
        entry = TimeEntryTable(status="draft")
        with pytest.raises(ValueError, match="Cannot approve time entry with status draft"):
            entry.approve(uuid4())

    def test_reject_from_submitted(self):
        entry = TimeEntryTable(status="submitted")
        reason = "Insufficient detail"
        entry.reject(reason)
        assert entry.status == "rejected"
        assert entry.rejection_reason == reason
        assert entry.version == 2

    def test_reject_from_invalid_status_raises(self):
        entry = TimeEntryTable(status="draft")
        with pytest.raises(ValueError, match="Cannot reject time entry with status draft"):
            entry.reject("reason")

    def test_mark_billed_from_approved(self):
        entry = TimeEntryTable(
            status="approved",
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
        )
        invoice_id = uuid4()
        billed_amount = Decimal("800000")
        entry.mark_billed(invoice_id, billed_amount)
        assert entry.status == "billed"
        assert entry.invoice_id == invoice_id
        assert entry.billed_amount == billed_amount
        assert entry.version == 2

    def test_mark_billed_from_invalid_status_raises(self):
        entry = TimeEntryTable(status="submitted")
        with pytest.raises(ValueError, match="Cannot bill time entry with status submitted"):
            entry.mark_billed(uuid4(), Decimal(0))

    def test_recalculate_cost(self):
        entry = TimeEntryTable(
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            is_overtime=False,
        )
        # Set total_cost to a wrong value
        entry.total_cost = Decimal("0")
        version_before = entry.version
        entry.recalculate_cost()
        assert entry.total_cost == Decimal("800000")
        assert entry.version == version_before + 1

    def test_recalculate_cost_with_overtime(self):
        entry = TimeEntryTable(
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
            is_overtime=True,
            overtime_multiplier=Decimal("1.5"),
        )
        entry.total_cost = Decimal("0")
        entry.recalculate_cost()
        assert entry.total_cost == Decimal("1200000")

    def test_is_owner_true(self):
        emp_id = uuid4()
        entry = TimeEntryTable(employee_id=emp_id)
        assert entry.is_owner(emp_id) is True

    def test_is_owner_false(self):
        emp_id = uuid4()
        other_id = uuid4()
        entry = TimeEntryTable(employee_id=emp_id)
        assert entry.is_owner(other_id) is False

    # -------------------- Edge Cases and Integration-like Tests --------------------
    def test_submit_sets_submitted_at(self):
        fixed_now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)
        with patch("infrastructure.persistence_orm.time_entry_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            # Because datetime.utcnow returns naive, we use it as is.
            # We'll simulate by using datetime.utcnow directly.
            # Actually, we can patch datetime.datetime.utcnow
            with patch("datetime.datetime") as mock_datetime:
                mock_datetime.utcnow.return_value = fixed_now.replace(tzinfo=None)
                entry = TimeEntryTable(status="draft")
                entry.submit()
                assert entry.submitted_at == fixed_now.replace(tzinfo=None)

    def test_approve_sets_approved_at(self):
        fixed_now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)
        with patch("infrastructure.persistence_orm.time_entry_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_now.replace(tzinfo=None)
            entry = TimeEntryTable(status="submitted")
            entry.approve(uuid4())
            assert entry.approved_at == fixed_now.replace(tzinfo=None)

    def test_status_transition_chain(self):
        """Test full workflow: draft -> submit -> approve -> bill."""
        entry = TimeEntryTable(
            status="draft",
            hours=Decimal("8.0"),
            hourly_rate=Decimal("100000"),
        )
        entry.submit()
        assert entry.status == "submitted"
        entry.approve(uuid4())
        assert entry.status == "approved"
        invoice_id = uuid4()
        entry.mark_billed(invoice_id, Decimal("800000"))
        assert entry.status == "billed"
        assert entry.invoice_id == invoice_id

    def test_version_increment_on_status_change(self):
        entry = TimeEntryTable(version=1)
        entry.submit()
        assert entry.version == 2
        entry.approve(uuid4())
        assert entry.version == 3
        entry.recalculate_cost()
        assert entry.version == 4

    def test_billable_amount_with_high_precision(self):
        entry = TimeEntryTable(
            is_billable=True,
            hours=Decimal("7.5"),
            hourly_rate=Decimal("120000"),
            billing_rate=Decimal("130000"),
        )
        # 7.5 * 130000 = 975000
        assert entry.billable_amount == Decimal("975000")

    def test_effective_hourly_rate_zero_multiplier(self):
        entry = TimeEntryTable(
            hourly_rate=Decimal("100000"),
            overtime_multiplier=Decimal("0"),
            is_overtime=True,
        )
        assert entry.effective_hourly_rate == Decimal(0)

    def test_effective_total_cost_zero_hours(self):
        entry = TimeEntryTable(hours=Decimal("0"), hourly_rate=Decimal("100000"))
        assert entry.effective_total_cost == Decimal(0)