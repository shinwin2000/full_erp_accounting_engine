# tests/compliance/legal/test_legal_obligation_calendar.py
"""
Comprehensive unit tests for compliance/legal/legal_obligation_calendar.py.
Covers all enums, exceptions, data classes, and calendar logic with mocks.
"""

import json
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from compliance.legal.legal_obligation_calendar import (
    HAS_ICAL,
    LegalObligation,
    LegalObligationCalendar,
    ObligationCalendarError,
    ObligationFrequency,
    ObligationInstance,
    ObligationNotFoundError,
    ObligationStatus,
    ReminderType,
)

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_DATE = date(2026, 7, 23)
FIXED_DATETIME = datetime(2026, 7, 23, 12, 0, 0)
FIXED_YEAR = 2026


@pytest.fixture(autouse=True)
def mock_date_today():
    with patch("compliance.legal.legal_obligation_calendar.date") as mock_date:
        mock_date.today.return_value = FIXED_DATE
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        yield mock_date


@pytest.fixture(autouse=True)
def mock_datetime_utcnow():
    with patch("compliance.legal.legal_obligation_calendar.datetime") as mock_dt:
        mock_dt.utcnow.return_value = FIXED_DATETIME
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


# ============================================================================
# Sample data fixtures
# ============================================================================

@pytest.fixture
def sample_obligation():
    return LegalObligation(
        obligation_id=uuid4(),
        title="SPT Masa PPN",
        description="Laporan PPN bulanan",
        jurisdiction="ID",
        regulatory_body="DJP",
        frequency=ObligationFrequency.MONTHLY,
        due_day=20,
        due_month_offset=0,
        lead_time_days=5,
        is_mandatory=True,
        penalty_for_late="Denda 2%",
        responsible_party="Tax Manager",
        external_reference="PMK-68",
    )


@pytest.fixture
def sample_instance():
    return ObligationInstance(
        instance_id=uuid4(),
        obligation_id=uuid4(),
        due_date=FIXED_DATE,
        period="2026-07",
        status=ObligationStatus.PENDING,
        submitted_date=None,
        reference_number=None,
        notes="",
    )


# ============================================================================
# Enum tests
# ============================================================================

class TestObligationFrequency:
    def test_members(self):
        assert ObligationFrequency.ONE_TIME.value == "one_time"
        assert ObligationFrequency.MONTHLY.value == "monthly"
        assert ObligationFrequency.QUARTERLY.value == "quarterly"
        assert ObligationFrequency.SEMI_ANNUAL.value == "semi_annual"
        assert ObligationFrequency.ANNUAL.value == "annual"
        assert ObligationFrequency.BIENNIAL.value == "biennial"


class TestObligationStatus:
    def test_members(self):
        assert ObligationStatus.PENDING.value == "pending"
        assert ObligationStatus.IN_PROGRESS.value == "in_progress"
        assert ObligationStatus.SUBMITTED.value == "submitted"
        assert ObligationStatus.COMPLETED.value == "completed"
        assert ObligationStatus.WAIVED.value == "waived"
        assert ObligationStatus.OVERDUE.value == "overdue"


class TestReminderType:
    def test_members(self):
        assert ReminderType.EMAIL.value == "email"
        assert ReminderType.SMS.value == "sms"
        assert ReminderType.PUSH.value == "push"
        assert ReminderType.WEBHOOK.value == "webhook"


# ============================================================================
# Exception tests
# ============================================================================

class TestExceptions:
    def test_obligation_calendar_error(self):
        with pytest.raises(ObligationCalendarError):
            raise ObligationCalendarError("test")

    def test_obligation_not_found_error(self):
        with pytest.raises(ObligationNotFoundError):
            raise ObligationNotFoundError("test")


# ============================================================================
# LegalObligation tests
# ============================================================================

class TestLegalObligation:
    def test_construction(self, sample_obligation):
        assert sample_obligation.id is not None
        assert sample_obligation.title == "SPT Masa PPN"
        assert sample_obligation.jurisdiction == "ID"
        assert sample_obligation.frequency == ObligationFrequency.MONTHLY
        assert sample_obligation.due_day == 20
        assert sample_obligation.lead_time_days == 5
        assert sample_obligation.is_mandatory is True
        assert sample_obligation._hash is not None
        assert len(sample_obligation._hash) == 64

    def test_compute_hash_consistency(self, sample_obligation):
        h1 = sample_obligation._hash
        # Change something that should affect hash
        sample_obligation.title = "Changed"
        h2 = sample_obligation._compute_hash()
        assert h1 != h2

    def test_to_dict(self, sample_obligation):
        d = sample_obligation.to_dict()
        assert d["obligation_id"] == str(sample_obligation.id)
        assert d["title"] == "SPT Masa PPN"
        assert d["jurisdiction"] == "ID"
        assert d["frequency"] == "monthly"
        assert d["due_day"] == 20
        assert "hash" in d


# ============================================================================
# ObligationInstance tests
# ============================================================================

class TestObligationInstance:
    def test_construction(self):
        instance = ObligationInstance(
            instance_id=uuid4(),
            obligation_id=uuid4(),
            due_date=FIXED_DATE,
            period="2026-07",
            status=ObligationStatus.PENDING,
        )
        assert instance.id is not None
        assert instance.due_date == FIXED_DATE
        assert instance.period == "2026-07"
        assert instance.status == ObligationStatus.PENDING
        assert instance.submitted_date is None
        assert instance.reference_number is None
        assert instance._hash is not None
        assert len(instance._hash) == 64

    def test_mark_completed(self, sample_instance):
        submitted = FIXED_DATE + timedelta(days=5)
        sample_instance.mark_completed(submitted, "REF-001")
        assert sample_instance.status == ObligationStatus.COMPLETED
        assert sample_instance.submitted_date == submitted
        assert sample_instance.reference_number == "REF-001"
        # Hash should change
        old_hash = sample_instance._hash
        sample_instance._compute_hash()
        assert sample_instance._hash != old_hash

    def test_mark_completed_without_reference(self, sample_instance):
        sample_instance.mark_completed(FIXED_DATE)
        assert sample_instance.reference_number is None

    def test_mark_overdue_when_pending(self, sample_instance):
        sample_instance.status = ObligationStatus.PENDING
        sample_instance.mark_overdue()
        assert sample_instance.status == ObligationStatus.OVERDUE

    def test_mark_overdue_when_completed_does_nothing(self, sample_instance):
        sample_instance.status = ObligationStatus.COMPLETED
        old_hash = sample_instance._hash
        sample_instance.mark_overdue()
        assert sample_instance.status == ObligationStatus.COMPLETED
        # Hash should not change
        assert sample_instance._hash == old_hash

    def test_mark_overdue_when_waived_does_nothing(self, sample_instance):
        sample_instance.status = ObligationStatus.WAIVED
        sample_instance.mark_overdue()
        assert sample_instance.status == ObligationStatus.WAIVED

    def test_to_dict(self, sample_instance):
        d = sample_instance.to_dict()
        assert d["instance_id"] == str(sample_instance.id)
        assert d["obligation_id"] == str(sample_instance.obligation_id)
        assert d["due_date"] == FIXED_DATE.isoformat()
        assert d["period"] == "2026-07"
        assert d["status"] == "pending"
        assert d["submitted_date"] is None
        assert d["reference_number"] is None
        assert "hash" in d


# ============================================================================
# LegalObligationCalendar tests
# ============================================================================

class TestLegalObligationCalendar:
    @pytest.fixture
    def calendar(self):
        return LegalObligationCalendar()

    def test_initialization_contains_defaults(self, calendar):
        # Should have default obligations from _init_default_obligations
        obligations = calendar._obligations
        assert len(obligations) > 0
        # Check some known defaults
        titles = [o.title for o in obligations.values()]
        assert "SPT Masa PPN" in titles
        assert "SPT Tahunan Badan" in titles
        assert "Pembayaran Angsuran PPh 25" in titles
        assert "LKPBU (Laporan Keuangan Publik Bulanan)" in titles

    def test_add_obligation(self, calendar, sample_obligation):
        ob_id = calendar.add_obligation(sample_obligation)
        assert ob_id == sample_obligation.id
        assert calendar.get_obligation(ob_id) is sample_obligation
        assert ob_id in calendar._obligation_instances
        assert calendar._obligation_instances[ob_id] == []

    def test_get_obligation(self, calendar):
        # Get existing
        ob = calendar.get_obligation(list(calendar._obligations.keys())[0])
        assert ob is not None
        # Get non-existent
        assert calendar.get_obligation(uuid4()) is None

    def test_get_obligations_by_jurisdiction(self, calendar):
        id_obligations = calendar.get_obligations_by_jurisdiction("ID")
        assert len(id_obligations) > 0
        for ob in id_obligations:
            assert ob.jurisdiction == "ID"
        # Non-existent jurisdiction
        assert len(calendar.get_obligations_by_jurisdiction("XX")) == 0

    def test_get_obligations_by_regulatory_body(self, calendar):
        djp_obligations = calendar.get_obligations_by_regulatory_body("DJP")
        assert len(djp_obligations) > 0
        for ob in djp_obligations:
            assert ob.regulatory_body == "DJP"
        # Non-existent
        assert len(calendar.get_obligations_by_regulatory_body("NON")) == 0

    # ---- calculate_due_date ----
    def test_calculate_due_date_monthly(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.MONTHLY,
            due_day=15,
            due_month_offset=0,
            lead_time_days=0,
        )
        due = calendar.calculate_due_date(ob, 2026, 7)
        assert due == date(2026, 7, 15)
        # December
        due2 = calendar.calculate_due_date(ob, 2026, 12)
        assert due2 == date(2026, 12, 15)

    def test_calculate_due_date_annual(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ANNUAL,
            due_day=30,
            due_month_offset=4,
            lead_time_days=0,
        )
        due = calendar.calculate_due_date(ob, 2026)
        assert due == date(2026, 4, 30)
        # Default month if not set
        ob2 = LegalObligation(
            obligation_id=uuid4(),
            title="test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ANNUAL,
            due_day=15,
            due_month_offset=0,
            lead_time_days=0,
        )
        due2 = calendar.calculate_due_date(ob2, 2026)
        assert due2 == date(2026, 1, 15)

    def test_calculate_due_date_quarterly(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.QUARTERLY,
            due_day=15,
            due_month_offset=0,
            lead_time_days=0,
        )
        # month 1 -> March
        due = calendar.calculate_due_date(ob, 2026, 1)
        assert due == date(2026, 3, 15)
        # month 4 -> June
        due2 = calendar.calculate_due_date(ob, 2026, 4)
        assert due2 == date(2026, 6, 15)
        # month 7 -> September
        due3 = calendar.calculate_due_date(ob, 2026, 7)
        assert due3 == date(2026, 9, 15)
        # month 10 -> December
        due4 = calendar.calculate_due_date(ob, 2026, 10)
        assert due4 == date(2026, 12, 15)

    def test_calculate_due_date_semi_annual(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.SEMI_ANNUAL,
            due_day=10,
            due_month_offset=0,
            lead_time_days=0,
        )
        # month 3 -> June
        due = calendar.calculate_due_date(ob, 2026, 3)
        assert due == date(2026, 6, 10)
        # month 8 -> December
        due2 = calendar.calculate_due_date(ob, 2026, 8)
        assert due2 == date(2026, 12, 10)

    def test_calculate_due_date_one_time(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=25,
            due_month_offset=5,
            lead_time_days=0,
        )
        due = calendar.calculate_due_date(ob, 2026)
        assert due == date(2026, 5, 25)
        # Default month if missing
        ob2 = LegalObligation(
            obligation_id=uuid4(),
            title="test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=1,
            due_month_offset=0,
            lead_time_days=0,
        )
        due2 = calendar.calculate_due_date(ob2, 2026)
        assert due2 == date(2026, 1, 1)

    # ---- generate_instances_for_year ----
    def test_generate_instances_for_year_monthly(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="Monthly",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.MONTHLY,
            due_day=15,
            due_month_offset=0,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        count = calendar.generate_instances_for_year(ob.id, 2026)
        assert count == 12
        instances = calendar.get_instances_by_obligation(ob.id)
        assert len(instances) == 12
        # Check due dates
        for i, inst in enumerate(instances, start=1):
            assert inst.due_date == date(2026, i, 15)
            assert inst.period == f"2026-{i:02d}"
            assert inst.status == ObligationStatus.PENDING

    def test_generate_instances_for_year_annual(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="Annual",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ANNUAL,
            due_day=30,
            due_month_offset=4,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        count = calendar.generate_instances_for_year(ob.id, 2026)
        assert count == 1
        instances = calendar.get_instances_by_obligation(ob.id)
        assert len(instances) == 1
        assert instances[0].due_date == date(2026, 4, 30)
        assert instances[0].period == "2026"

    def test_generate_instances_for_year_quarterly(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="Quarterly",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.QUARTERLY,
            due_day=20,
            due_month_offset=0,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        count = calendar.generate_instances_for_year(ob.id, 2026)
        assert count == 4
        instances = calendar.get_instances_by_obligation(ob.id)
        assert len(instances) == 4
        expected_months = [3, 6, 9, 12]
        for i, inst in enumerate(instances):
            assert inst.due_date == date(2026, expected_months[i], 20)
            assert inst.period == f"2026-Q{i+1}"

    def test_generate_instances_for_year_semi_annual(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="Semi-Annual",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.SEMI_ANNUAL,
            due_day=10,
            due_month_offset=0,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        count = calendar.generate_instances_for_year(ob.id, 2026)
        assert count == 2
        instances = calendar.get_instances_by_obligation(ob.id)
        assert len(instances) == 2
        assert instances[0].due_date == date(2026, 6, 10)
        assert instances[0].period == "2026-H1"
        assert instances[1].due_date == date(2026, 12, 10)
        assert instances[1].period == "2026-H2"

    def test_generate_instances_for_year_one_time(self, calendar):
        ob = LegalObligation(
            obligation_id=uuid4(),
            title="One-Time",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=1,
            due_month_offset=1,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        count = calendar.generate_instances_for_year(ob.id, 2026)
        assert count == 1
        instances = calendar.get_instances_by_obligation(ob.id)
        assert len(instances) == 1
        assert instances[0].due_date == date(2026, 1, 1)

    def test_generate_instances_for_year_obligation_not_found(self, calendar):
        with pytest.raises(ObligationNotFoundError):
            calendar.generate_instances_for_year(uuid4(), 2026)

    # ---- generate_all_instances ----
    def test_generate_all_instances(self, calendar):
        # Calendar has default obligations; we add a few more to ensure count
        # We'll just count after generating
        initial_obligations = len(calendar._obligations)
        total = calendar.generate_all_instances(2026)
        # Each obligation generates some instances
        # We can't know exact count, but it should be > 0
        assert total > 0
        # Check that instances are created
        assert len(calendar._instances) == total

    # ---- get_instance ----
    def test_get_instance(self, calendar):
        # Create an instance manually
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=1,
            due_month_offset=1,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        calendar.generate_instances_for_year(ob_id, 2026)
        instances = calendar.get_instances_by_obligation(ob_id)
        assert len(instances) == 1
        instance = calendar.get_instance(instances[0].id)
        assert instance is not None
        assert instance.id == instances[0].id
        # Non-existent
        assert calendar.get_instance(uuid4()) is None

    # ---- get_instances_by_obligation ----
    def test_get_instances_by_obligation(self, calendar):
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.MONTHLY,
            due_day=1,
            due_month_offset=0,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        calendar.generate_instances_for_year(ob_id, 2026)
        instances = calendar.get_instances_by_obligation(ob_id)
        assert len(instances) == 12
        # Non-existent obligation
        assert len(calendar.get_instances_by_obligation(uuid4())) == 0

    # ---- get_upcoming_instances ----
    def test_get_upcoming_instances(self, calendar):
        # Create an obligation and generate instances for 2026
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Monthly",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.MONTHLY,
            due_day=20,
            due_month_offset=0,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        calendar.generate_instances_for_year(ob_id, 2026)
        # We want instances due in future relative to FIXED_DATE (2026-07-23)
        # Some due dates: 2026-08-20, 2026-09-20, etc.
        upcoming = calendar.get_upcoming_instances(days_ahead=60)
        # Should include August and September
        assert len(upcoming) >= 2
        for inst in upcoming:
            assert inst.due_date >= FIXED_DATE
            assert inst.due_date <= FIXED_DATE + timedelta(days=60)
            assert inst.status not in (ObligationStatus.COMPLETED, ObligationStatus.WAIVED)

        # Filter by jurisdiction
        upcoming_id = calendar.get_upcoming_instances(jurisdiction="ID", days_ahead=60)
        assert len(upcoming_id) == len(upcoming)  # all are ID
        upcoming_xx = calendar.get_upcoming_instances(jurisdiction="XX", days_ahead=60)
        assert len(upcoming_xx) == 0

    # ---- get_overdue_instances ----
    def test_get_overdue_instances(self, calendar):
        # Create an obligation with due date in past
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Past Due",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=1,
            due_month_offset=1,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        # Generate for 2026, but due date is Jan 1, which is before FIXED_DATE (July 23)
        calendar.generate_instances_for_year(ob_id, 2026)
        overdue = calendar.get_overdue_instances()
        # Should include this one
        found = False
        for inst in overdue:
            if inst.obligation_id == ob_id:
                found = True
                break
        assert found is True
        # Mark as completed, then it shouldn't appear
        for inst in calendar.get_instances_by_obligation(ob_id):
            inst.mark_completed(FIXED_DATE)
        overdue2 = calendar.get_overdue_instances()
        assert len(overdue2) == 0

        # Filter by jurisdiction
        overdue_id = calendar.get_overdue_instances(jurisdiction="ID")
        # Should include all overdue because all are ID
        assert len(overdue_id) > 0

    # ---- mark_submitted ----
    def test_mark_submitted_success(self, calendar):
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Test",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=1,
            due_month_offset=1,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        calendar.generate_instances_for_year(ob_id, 2026)
        instance = calendar.get_instances_by_obligation(ob_id)[0]
        submitted_date = FIXED_DATE + timedelta(days=5)
        result = calendar.mark_submitted(instance.id, submitted_date, "REF-001")
        assert result is True
        # Check status
        updated = calendar.get_instance(instance.id)
        assert updated.status == ObligationStatus.COMPLETED
        assert updated.submitted_date == submitted_date
        assert updated.reference_number == "REF-001"

    def test_mark_submitted_not_found(self, calendar):
        result = calendar.mark_submitted(uuid4(), FIXED_DATE)
        assert result is False

    # ---- check_and_update_overdue ----
    def test_check_and_update_overdue(self, calendar):
        # Create a past-due instance
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Past Due",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=1,
            due_month_offset=1,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        calendar.generate_instances_for_year(ob_id, 2026)
        instance = calendar.get_instances_by_obligation(ob_id)[0]
        # It should be pending, and due date is in past
        assert instance.status == ObligationStatus.PENDING
        count = calendar.check_and_update_overdue()
        assert count >= 1  # at least this one
        updated = calendar.get_instance(instance.id)
        assert updated.status == ObligationStatus.OVERDUE

        # Run again, should not count again
        count2 = calendar.check_and_update_overdue()
        assert count2 == 0  # already overdue

        # If completed, not counted
        instance.mark_completed(FIXED_DATE)
        count3 = calendar.check_and_update_overdue()
        assert count3 == 0

    # ---- send_reminders ----
    def test_send_reminders_dry_run(self, calendar):
        # Create an upcoming obligation (due in 5 days)
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Upcoming",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=FIXED_DATE.day + 5,  # 5 days from now
            due_month_offset=FIXED_DATE.month,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        calendar.generate_instances_for_year(ob_id, FIXED_DATE.year)
        instance = calendar.get_instances_by_obligation(ob_id)[0]
        # Ensure due date is in future
        assert instance.due_date > FIXED_DATE
        # Dry run
        reminders = calendar.send_reminders(dry_run=True)
        # Should include this instance
        found = False
        for r in reminders:
            if r["instance_id"] == str(instance.id):
                found = True
                break
        assert found is True
        # Reminder sent_at should not be updated
        assert instance.reminder_sent_at is None

    def test_send_reminders_actual_send(self, calendar):
        # Create an upcoming obligation
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Upcoming",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=FIXED_DATE.day + 3,
            due_month_offset=FIXED_DATE.month,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        calendar.generate_instances_for_year(ob_id, FIXED_DATE.year)
        instance = calendar.get_instances_by_obligation(ob_id)[0]
        # Ensure due date is in future
        assert instance.due_date > FIXED_DATE
        # Send for real (dry_run=False)
        reminders = calendar.send_reminders(dry_run=False)
        # Should include this instance
        found = False
        for r in reminders:
            if r["instance_id"] == str(instance.id):
                found = True
                break
        assert found is True
        # Reminder sent_at should be updated
        updated = calendar.get_instance(instance.id)
        assert updated.reminder_sent_at == FIXED_DATETIME
        # Hash should be updated
        assert updated._hash != instance._hash

    def test_send_reminders_skip_if_already_sent(self, calendar):
        # Create an upcoming obligation
        ob_id = uuid4()
        ob = LegalObligation(
            obligation_id=ob_id,
            title="Upcoming",
            description="",
            jurisdiction="ID",
            regulatory_body="DJP",
            frequency=ObligationFrequency.ONE_TIME,
            due_day=FIXED_DATE.day + 3,
            due_month_offset=FIXED_DATE.month,
            lead_time_days=0,
        )
        calendar.add_obligation(ob)
        calendar.generate_instances_for_year(ob_id, FIXED_DATE.year)
        instance = calendar.get_instances_by_obligation(ob_id)[0]
        # Set reminder_sent_at already
        instance.reminder_sent_at = FIXED_DATETIME
        reminders = calendar.send_reminders(dry_run=False)
        # Should not include this instance
        for r in reminders:
            assert r["instance_id"] != str(instance.id)

    # ---- generate_report ----
    def test_generate_report(self, calendar):
        # Generate some instances
        calendar.generate_all_instances(FIXED_YEAR)
        # Mark some as completed
        for inst in list(calendar._instances.values())[:3]:
            inst.mark_completed(FIXED_DATE)
        report = calendar.generate_report(FIXED_YEAR)
        assert report["year"] == FIXED_YEAR
        assert report["total_obligations"] > 0
        assert report["total_instances_generated"] == len(calendar._instances)
        assert report["completed"] == 3
        assert "overdue_count" in report
        assert "upcoming_count" in report
        # Filter by jurisdiction
        report_id = calendar.generate_report(FIXED_YEAR, jurisdiction="ID")
        assert report_id["jurisdiction_filter"] == "ID"
        # Should have some data
        assert report_id["total_obligations"] > 0

    # ---- export_to_json ----
    def test_export_to_json(self, calendar):
        # Generate some data
        calendar.generate_all_instances(FIXED_YEAR)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            calendar.export_to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert "obligations" in data
            assert "instances" in data
            assert len(data["obligations"]) == len(calendar._obligations)
            assert len(data["instances"]) == len(calendar._instances)
        finally:
            import os
            os.remove(file_path)

    # ---- export_to_ical ----
    def test_export_to_ical(self, calendar):
        if not HAS_ICAL:
            pytest.skip("icalendar not installed, skipping")
        # Generate some instances
        calendar.generate_all_instances(FIXED_YEAR)
        with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as f:
            file_path = f.name
        try:
            result = calendar.export_to_ical(file_path, FIXED_YEAR)
            assert result is True
            # Check file exists and has some content
            with open(file_path, "rb") as f:
                content = f.read()
            assert b"BEGIN:VCALENDAR" in content
            assert b"END:VCALENDAR" in content
            # Should contain events for this year
            assert b"DTSTART" in content
        finally:
            import os
            os.remove(file_path)

    def test_export_to_ical_missing_library(self, calendar):
        # Patch HAS_ICAL to False
        with patch("compliance.legal.legal_obligation_calendar.HAS_ICAL", False):
            result = calendar.export_to_ical("dummy.ics", FIXED_YEAR)
            assert result is False

    # ---- Integration: full flow with default obligations ----
    def test_full_flow(self, calendar):
        # Generate all instances for 2026
        total = calendar.generate_all_instances(FIXED_YEAR)
        assert total > 0
        # Check overdue and upcoming
        overdue = calendar.get_overdue_instances()
        upcoming = calendar.get_upcoming_instances(days_ahead=30)
        # Update overdue
        count = calendar.check_and_update_overdue()
        assert count >= 0
        # Send reminders
        reminders = calendar.send_reminders(dry_run=True)
        assert len(reminders) > 0
        # Mark some as submitted
        for inst in list(calendar._instances.values())[:2]:
            calendar.mark_submitted(inst.id, FIXED_DATE, "REF")
        # Generate report
        report = calendar.generate_report(FIXED_YEAR)
        assert report["completed"] >= 2
        # Export
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = f.name
        try:
            calendar.export_to_json(json_path)
            with open(json_path) as f:
                data = json.load(f)
            assert len(data["instances"]) == total
        finally:
            os.remove(json_path)
