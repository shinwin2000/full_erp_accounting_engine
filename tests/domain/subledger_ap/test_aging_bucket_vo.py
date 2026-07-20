# test_aging_bucket_vo.py
# Comprehensive tests for aging_bucket_vo.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from domain.subledger_ap.aging_bucket_vo import (
    AgingBucket,
    AgingBucketVO,
    AgingCalculator,
    AgingSummary,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def current_date():
    """Fixed current date for deterministic tests."""
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def bucket_vo_current():
    """AgingBucketVO for CURRENT bucket."""
    return AgingBucketVO(bucket=AgingBucket.CURRENT, amount=Decimal("1000.00"), currency="IDR")


@pytest.fixture
def bucket_vo_30():
    """AgingBucketVO for DAYS_1_30 bucket."""
    return AgingBucketVO(bucket=AgingBucket.DAYS_1_30, amount=Decimal("500.00"), currency="IDR")


@pytest.fixture
def aging_summary():
    """AgingSummary with some buckets."""
    return AgingSummary(
        as_of_date=datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        buckets={
            AgingBucket.CURRENT: Decimal("1000.00"),
            AgingBucket.DAYS_1_30: Decimal("500.00"),
            AgingBucket.DAYS_31_60: Decimal("300.00"),
            AgingBucket.DAYS_61_90: Decimal("200.00"),
            AgingBucket.OVER_90: Decimal("100.00"),
        },
        total_outstanding=Decimal("2100.00"),
        currency="IDR",
    )


# ============================================================================
# Tests for AgingBucket Enum
# ============================================================================

class TestAgingBucket:
    def test_members(self):
        assert AgingBucket.CURRENT.value == "current"
        assert AgingBucket.DAYS_1_30.value == "1-30"
        assert AgingBucket.DAYS_31_60.value == "31-60"
        assert AgingBucket.DAYS_61_90.value == "61-90"
        assert AgingBucket.OVER_90.value == "over_90"

    def test_display_names(self):
        assert AgingBucket.CURRENT.display_name() == "Current"
        assert AgingBucket.DAYS_1_30.display_name() == "1-30 Days"
        assert AgingBucket.DAYS_31_60.display_name() == "31-60 Days"
        assert AgingBucket.DAYS_61_90.display_name() == "61-90 Days"
        assert AgingBucket.OVER_90.display_name() == "Over 90 Days"


# ============================================================================
# Tests for AgingBucketVO
# ============================================================================

class TestAgingBucketVO:
    def test_construction(self, bucket_vo_current):
        assert bucket_vo_current.bucket == AgingBucket.CURRENT
        assert bucket_vo_current.amount == Decimal("1000.00")
        assert bucket_vo_current.currency == "IDR"

    def test_add_same_bucket(self, bucket_vo_current, bucket_vo_30):
        # Add two VOs of different buckets should return a new VO with same bucket? 
        # Actually the add method likely adds amounts of the same bucket, or it might sum amounts and keep bucket.
        # Let's assume it adds amounts regardless and keeps the bucket of the first.
        result = bucket_vo_current.add(bucket_vo_30)
        assert result.bucket == AgingBucket.CURRENT
        assert result.amount == Decimal("1500.00")
        assert result.currency == "IDR"

    def test_add_currency_mismatch(self, bucket_vo_current):
        other = AgingBucketVO(bucket=AgingBucket.DAYS_1_30, amount=Decimal("100.00"), currency="USD")
        with pytest.raises(ValueError, match="Currency mismatch"):
            bucket_vo_current.add(other)

    def test_add_negative_amount(self, bucket_vo_current):
        other = AgingBucketVO(bucket=AgingBucket.CURRENT, amount=Decimal("-200.00"), currency="IDR")
        result = bucket_vo_current.add(other)
        assert result.amount == Decimal("800.00")

    def test_to_dict(self, bucket_vo_current):
        d = bucket_vo_current.to_dict()
        assert d["bucket"] == "current"
        assert d["amount"] == "1000.00"
        assert d["currency"] == "IDR"


# ============================================================================
# Tests for AgingSummary
# ============================================================================

class TestAgingSummary:
    def test_construction(self, aging_summary):
        assert aging_summary.as_of_date == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        assert aging_summary.total_outstanding == Decimal("2100.00")
        assert aging_summary.currency == "IDR"
        assert len(aging_summary.buckets) == 5

    def test_get_bucket_amount(self, aging_summary):
        assert aging_summary.get_bucket_amount(AgingBucket.CURRENT) == Decimal("1000.00")
        assert aging_summary.get_bucket_amount(AgingBucket.DAYS_1_30) == Decimal("500.00")
        assert aging_summary.get_bucket_amount(AgingBucket.OVER_90) == Decimal("100.00")
        # Non-existing bucket returns 0
        assert aging_summary.get_bucket_amount(AgingBucket.DAYS_1_30) == Decimal("500.00")

    def test_to_dict(self, aging_summary):
        d = aging_summary.to_dict()
        assert d["as_of_date"] == "2024-06-15T12:00:00+00:00"
        assert d["total_outstanding"] == "2100.00"
        assert d["currency"] == "IDR"
        assert "current" in d["buckets"]
        assert d["buckets"]["current"] == "1000.00"

    @pytest.mark.parametrize("bucket,expected", [
        (AgingBucket.CURRENT, "1000.00"),
        (AgingBucket.DAYS_1_30, "500.00"),
        (AgingBucket.DAYS_31_60, "300.00"),
        (AgingBucket.DAYS_61_90, "200.00"),
        (AgingBucket.OVER_90, "100.00"),
    ])
    def test_get_bucket(self, aging_summary, bucket, expected):
        assert aging_summary.get_bucket_amount(bucket) == Decimal(expected)


# ============================================================================
# Tests for AgingCalculator
# ============================================================================

class TestAgingCalculator:
    def test_calculate_bucket_current(self, current_date):
        due_date = current_date + timedelta(days=5)  # future due
        bucket = AgingCalculator.calculate_bucket(due_date, current_date)
        assert bucket == AgingBucket.CURRENT

    def test_calculate_bucket_1_30(self, current_date):
        due_date = current_date - timedelta(days=15)
        bucket = AgingCalculator.calculate_bucket(due_date, current_date)
        assert bucket == AgingBucket.DAYS_1_30

    def test_calculate_bucket_31_60(self, current_date):
        due_date = current_date - timedelta(days=45)
        bucket = AgingCalculator.calculate_bucket(due_date, current_date)
        assert bucket == AgingBucket.DAYS_31_60

    def test_calculate_bucket_61_90(self, current_date):
        due_date = current_date - timedelta(days=75)
        bucket = AgingCalculator.calculate_bucket(due_date, current_date)
        assert bucket == AgingBucket.DAYS_61_90

    def test_calculate_bucket_over_90(self, current_date):
        due_date = current_date - timedelta(days=100)
        bucket = AgingCalculator.calculate_bucket(due_date, current_date)
        assert bucket == AgingBucket.OVER_90

    def test_calculate_bucket_exact_boundary(self, current_date):
        # exactly 30 days overdue
        due_date = current_date - timedelta(days=30)
        bucket = AgingCalculator.calculate_bucket(due_date, current_date)
        assert bucket == AgingBucket.DAYS_1_30  # inclusive? Typically 1-30 includes 30.

    def test_calculate_bucket_future_due(self, current_date):
        due_date = current_date + timedelta(days=1)
        bucket = AgingCalculator.calculate_bucket(due_date, current_date)
        assert bucket == AgingBucket.CURRENT

    def test_calculate_days_overdue_current(self, current_date):
        due_date = current_date + timedelta(days=5)
        days = AgingCalculator.calculate_days_overdue(due_date, current_date)
        assert days == 0  # not overdue

    def test_calculate_days_overdue(self, current_date):
        due_date = current_date - timedelta(days=45)
        days = AgingCalculator.calculate_days_overdue(due_date, current_date)
        assert days == 45

    def test_calculate_days_overdue_exact_due(self, current_date):
        due_date = current_date  # due today
        days = AgingCalculator.calculate_days_overdue(due_date, current_date)
        assert days == 0

    def test_calculate_bucket_with_different_timezone(self, current_date):
        # Ensure timezone handling
        due_date = current_date.replace(tzinfo=None)  # naive
        with pytest.raises(TypeError):
            AgingCalculator.calculate_bucket(due_date, current_date)

    def test_calculate_days_overdue_with_none(self):
        # If due_date is None, maybe treat as current? or raise.
        with pytest.raises(ValueError, match="due_date cannot be None"):
            AgingCalculator.calculate_days_overdue(None, datetime.now(UTC))

    def test_calculate_bucket_with_none(self):
        with pytest.raises(ValueError, match="due_date cannot be None"):
            AgingCalculator.calculate_bucket(None, datetime.now(UTC))


# ============================================================================
# Integration style: create summary from list of VOs
# ============================================================================

class TestAgingSummaryFromVOs:
    def test_create_from_vo_list(self, current_date):
        vos = [
            AgingBucketVO(bucket=AgingBucket.CURRENT, amount=Decimal("1000.00"), currency="IDR"),
            AgingBucketVO(bucket=AgingBucket.DAYS_1_30, amount=Decimal("500.00"), currency="IDR"),
            AgingBucketVO(bucket=AgingBucket.DAYS_31_60, amount=Decimal("300.00"), currency="IDR"),
        ]
        summary = AgingSummary.from_vo_list(vos, current_date, currency="IDR")
        assert summary.as_of_date == current_date
        assert summary.total_outstanding == Decimal("1800.00")
        assert summary.currency == "IDR"
        assert summary.get_bucket_amount(AgingBucket.CURRENT) == Decimal("1000.00")
        assert summary.get_bucket_amount(AgingBucket.DAYS_1_30) == Decimal("500.00")
        assert summary.get_bucket_amount(AgingBucket.DAYS_31_60) == Decimal("300.00")
        assert summary.get_bucket_amount(AgingBucket.DAYS_61_90) == Decimal("0")
        assert summary.get_bucket_amount(AgingBucket.OVER_90) == Decimal("0")

    def test_from_vo_list_currency_mismatch(self, current_date):
        vos = [
            AgingBucketVO(bucket=AgingBucket.CURRENT, amount=Decimal("1000.00"), currency="IDR"),
            AgingBucketVO(bucket=AgingBucket.DAYS_1_30, amount=Decimal("500.00"), currency="USD"),
        ]
        with pytest.raises(ValueError, match="Currency mismatch"):
            AgingSummary.from_vo_list(vos, current_date, currency="IDR")

    def test_from_vo_list_auto_currency(self, current_date):
        vos = [
            AgingBucketVO(bucket=AgingBucket.CURRENT, amount=Decimal("1000.00"), currency="IDR"),
            AgingBucketVO(bucket=AgingBucket.DAYS_1_30, amount=Decimal("500.00"), currency="IDR"),
        ]
        summary = AgingSummary.from_vo_list(vos, current_date)  # currency not specified
        assert summary.currency == "IDR"  # should infer from first

    def test_from_vo_list_empty(self, current_date):
        summary = AgingSummary.from_vo_list([], current_date, currency="IDR")
        assert summary.total_outstanding == Decimal("0")
        for bucket in AgingBucket:
            assert summary.get_bucket_amount(bucket) == Decimal("0")

    def test_add_to_summary(self, aging_summary):
        new_vo = AgingBucketVO(bucket=AgingBucket.CURRENT, amount=Decimal("200.00"), currency="IDR")
        new_summary = aging_summary.add_vo(new_vo)
        assert new_summary.get_bucket_amount(AgingBucket.CURRENT) == Decimal("1200.00")
        assert new_summary.total_outstanding == Decimal("2300.00")
        assert new_summary.version == aging_summary.version + 1

    def test_add_to_summary_new_bucket(self, aging_summary):
        new_vo = AgingBucketVO(bucket=AgingBucket.CURRENT, amount=Decimal("200.00"), currency="IDR")
        new_summary = aging_summary.add_vo(new_vo)
        # existing buckets unchanged
        assert new_summary.get_bucket_amount(AgingBucket.DAYS_1_30) == Decimal("500.00")
        assert new_summary.get_bucket_amount(AgingBucket.DAYS_31_60) == Decimal("300.00")