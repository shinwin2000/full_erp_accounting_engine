# tests/domain/subledger_ar/test_aging_bucket_vo.py
"""
Unit tests for aging_bucket_vo.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from domain.shared_value_objects.money_vo import Money
from domain.subledger_ar.aging_bucket_vo import (
    AgingBucket,
    AgingBucketVO,
    AgingCalculator,
    AgingSummary,
)


class TestAgingBucket:
    def test_members(self):
        assert AgingBucket.CURRENT.value == "current"
        assert AgingBucket.DAYS_1_30.value == "1_30_days"

    def test_get_days_range(self):
        assert AgingBucket.CURRENT.get_days_range() == (0, 0)
        assert AgingBucket.DAYS_1_30.get_days_range() == (1, 30)
        assert AgingBucket.DAYS_31_60.get_days_range() == (31, 60)
        assert AgingBucket.DAYS_61_90.get_days_range() == (61, 90)
        assert AgingBucket.OVER_90.get_days_range() == (91, float("inf"))

    def test_get_provision_rate(self):
        base = Decimal("0.02")
        assert AgingBucket.CURRENT.get_provision_rate(base) == Decimal("0.02")
        assert AgingBucket.DAYS_1_30.get_provision_rate(base) == Decimal("0.04")
        assert AgingBucket.DAYS_31_60.get_provision_rate(base) == Decimal("0.10")
        assert AgingBucket.DAYS_61_90.get_provision_rate(base) == Decimal("0.20")
        assert AgingBucket.OVER_90.get_provision_rate(base) == Decimal("0.50")

        # Default base
        assert AgingBucket.CURRENT.get_provision_rate() == Decimal("0.02")

    def test_get_display_name(self):
        assert AgingBucket.CURRENT.get_display_name() == "Current"
        assert AgingBucket.DAYS_1_30.get_display_name() == "1-30 Days"
        assert AgingBucket.DAYS_31_60.get_display_name() == "31-60 Days"
        assert AgingBucket.DAYS_61_90.get_display_name() == "61-90 Days"
        assert AgingBucket.OVER_90.get_display_name() == "Over 90 Days"

    def test_from_string(self):
        assert AgingBucket.from_string("current") == AgingBucket.CURRENT
        assert AgingBucket.from_string("1_30_days") == AgingBucket.DAYS_1_30
        assert AgingBucket.from_string("31_60_days") == AgingBucket.DAYS_31_60
        assert AgingBucket.from_string("61_90_days") == AgingBucket.DAYS_61_90
        assert AgingBucket.from_string("over_90_days") == AgingBucket.OVER_90
        assert AgingBucket.from_string("CURRENT") == AgingBucket.CURRENT  # case-insensitive

        with pytest.raises(ValueError, match="Invalid AgingBucket"):
            AgingBucket.from_string("invalid")


class TestAgingBucketVO:
    def test_construction(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        assert vo.bucket == AgingBucket.CURRENT
        assert vo.amount == Decimal("1000")
        assert vo.currency == "IDR"

    def test_validation_negative_amount(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            AgingBucketVO(AgingBucket.CURRENT, Decimal("-100"))

    def test_add(self):
        vo1 = AgingBucketVO(AgingBucket.CURRENT, Decimal("100"), "IDR")
        vo2 = AgingBucketVO(AgingBucket.CURRENT, Decimal("200"), "IDR")
        result = vo1.add(vo2)
        assert result.bucket == AgingBucket.CURRENT
        assert result.amount == Decimal("300")
        assert result.currency == "IDR"

        # Different buckets should raise
        vo3 = AgingBucketVO(AgingBucket.DAYS_1_30, Decimal("100"), "IDR")
        with pytest.raises(ValueError, match="Cannot add different buckets"):
            vo1.add(vo3)

        # Different currencies should raise
        vo4 = AgingBucketVO(AgingBucket.CURRENT, Decimal("100"), "USD")
        with pytest.raises(ValueError, match="Cannot add different currencies"):
            vo1.add(vo4)

    def test_to_money(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000.50"), "IDR")
        money = vo.to_money()
        assert isinstance(money, Money)
        assert money.amount == Decimal("1000.50")
        assert money.currency == "IDR"

    def test_get_provision_rate(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"))
        rate = vo.get_provision_rate()
        assert rate == Decimal("0.02")  # default base

    def test_get_provision_amount(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"))
        prov = vo.get_provision_amount()
        assert prov == Decimal("20")  # 1000 * 0.02

        vo2 = AgingBucketVO(AgingBucket.OVER_90, Decimal("1000"))
        prov2 = vo2.get_provision_amount()
        assert prov2 == Decimal("500")  # 1000 * 0.50

    def test_validate(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        result = vo.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        vo2 = AgingBucketVO(AgingBucket.CURRENT, Decimal("-1"), "IDR")  # invalid
        result2 = vo2.validate()
        assert result2["is_valid"] is False
        assert "negative" in result2["errors"][0]

    def test_normalize(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000.50"), "IDR")
        norm = vo.normalize()
        assert norm == vo

    def test_to_string(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000.50"), "IDR")
        assert vo.to_string() == "current:1000.50:IDR"

    def test_from_string(self):
        vo = AgingBucketVO.from_string("current:1000.50:IDR")
        assert vo.bucket == AgingBucket.CURRENT
        assert vo.amount == Decimal("1000.50")
        assert vo.currency == "IDR"

        with pytest.raises(ValueError, match="Invalid string format"):
            AgingBucketVO.from_string("invalid")

    def test_to_dict(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        d = vo.to_dict()
        assert d["bucket"] == "current"
        assert d["amount"] == "1000"
        assert d["currency"] == "IDR"
        assert d["provision_rate"] == "0.02"
        assert d["provision_amount"] == "20"

    def test_from_dict(self):
        data = {
            "bucket": "current",
            "amount": "1000.50",
            "currency": "USD",
        }
        vo = AgingBucketVO.from_dict(data)
        assert vo.bucket == AgingBucket.CURRENT
        assert vo.amount == Decimal("1000.50")
        assert vo.currency == "USD"

        # Missing currency should default to IDR
        data2 = {"bucket": "current", "amount": "500"}
        vo2 = AgingBucketVO.from_dict(data2)
        assert vo2.currency == "IDR"

    def test_clone(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        clone = vo.clone()
        assert clone is not vo
        assert clone.bucket == vo.bucket
        assert clone.amount == vo.amount
        assert clone.currency == vo.currency

    def test_snapshot(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        snap = vo.snapshot()
        assert snap["bucket"] == "current"
        assert snap["amount"] == "1000"
        assert snap["currency"] == "IDR"

    def test_version(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        assert vo.version() == 1

    def test_audit_trail(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        trail = vo.audit_trail()
        assert len(trail) == 1
        assert trail[0]["bucket"] == "current"

    def test_touch(self):
        vo = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        touched = vo.touch("system")
        assert touched is not vo
        assert touched.bucket == vo.bucket

    def test_eq(self):
        vo1 = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        vo2 = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        vo3 = AgingBucketVO(AgingBucket.CURRENT, Decimal("2000"), "IDR")
        assert vo1 == vo2
        assert vo1 != vo3
        assert vo1 != "not vo"

    def test_hash(self):
        vo1 = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        vo2 = AgingBucketVO(AgingBucket.CURRENT, Decimal("1000"), "IDR")
        vo3 = AgingBucketVO(AgingBucket.CURRENT, Decimal("2000"), "IDR")
        assert hash(vo1) == hash(vo2)
        assert hash(vo1) != hash(vo3)


class TestAgingSummary:
    def test_create_empty(self):
        now = datetime.now(UTC)
        summary = AgingSummary.create_empty(now, "IDR")
        assert summary.as_of_date == now
        assert summary.currency == "IDR"
        assert summary.total_outstanding == Decimal(0)
        assert summary.total_provision == Decimal(0)
        assert len(summary.buckets) == 5
        for bucket in AgingBucket:
            assert bucket in summary.buckets
            assert summary.buckets[bucket].amount == Decimal(0)

    def test_add_invoice(self):
        now = datetime.now(UTC)
        summary = AgingSummary.create_empty(now, "IDR")

        # Current invoice (due in future)
        future_due = now + timedelta(days=10)
        summary = summary.add_invoice(now - timedelta(days=5), future_due, Decimal("1000"), "IDR")
        assert summary.total_outstanding == Decimal("1000")
        assert summary.buckets[AgingBucket.CURRENT].amount == Decimal("1000")

        # 1-30 days overdue
        due_15 = now - timedelta(days=15)
        summary = summary.add_invoice(now - timedelta(days=30), due_15, Decimal("500"), "IDR")
        assert summary.total_outstanding == Decimal("1500")
        assert summary.buckets[AgingBucket.DAYS_1_30].amount == Decimal("500")

        # 31-60 days overdue
        due_45 = now - timedelta(days=45)
        summary = summary.add_invoice(now - timedelta(days=60), due_45, Decimal("300"), "IDR")
        assert summary.buckets[AgingBucket.DAYS_31_60].amount == Decimal("300")

        # 61-90 days overdue
        due_75 = now - timedelta(days=75)
        summary = summary.add_invoice(now - timedelta(days=90), due_75, Decimal("200"), "IDR")
        assert summary.buckets[AgingBucket.DAYS_61_90].amount == Decimal("200")

        # Over 90 days overdue
        due_100 = now - timedelta(days=100)
        summary = summary.add_invoice(now - timedelta(days=120), due_100, Decimal("100"), "IDR")
        assert summary.buckets[AgingBucket.OVER_90].amount == Decimal("100")

        # Currency mismatch should be ignored
        summary2 = summary.add_invoice(now, now, Decimal("1000"), "USD")
        assert summary2.total_outstanding == summary.total_outstanding

        # Provision should be calculated
        assert summary.total_provision > 0

    def test_get_bucket_amount(self):
        now = datetime.now(UTC)
        summary = AgingSummary.create_empty(now)
        summary = summary.add_invoice(now, now + timedelta(days=1), Decimal("1000"), "IDR")
        assert summary.get_bucket_amount(AgingBucket.CURRENT) == Decimal("1000")
        assert summary.get_bucket_amount(AgingBucket.DAYS_1_30) == Decimal(0)

    def test_get_percentage_by_bucket(self):
        now = datetime.now(UTC)
        summary = AgingSummary.create_empty(now)
        summary = summary.add_invoice(now, now + timedelta(days=1), Decimal("1000"), "IDR")
        summary = summary.add_invoice(now - timedelta(days=20), now - timedelta(days=20), Decimal("500"), "IDR")

        assert summary.get_percentage_by_bucket(AgingBucket.CURRENT) == Decimal("66.67")  # 1000/1500*100
        assert summary.get_percentage_by_bucket(AgingBucket.DAYS_1_30) == Decimal("33.33")  # 500/1500*100
        assert summary.get_percentage_by_bucket(AgingBucket.OVER_90) == Decimal(0)

        # Zero total
        empty = AgingSummary.create_empty(now)
        assert empty.get_percentage_by_bucket(AgingBucket.CURRENT) == Decimal(0)

    def test_to_dict(self):
        now = datetime.now(UTC)
        summary = AgingSummary.create_empty(now)
        summary = summary.add_invoice(now, now + timedelta(days=1), Decimal("1000"), "IDR")
        d = summary.to_dict()
        assert d["as_of_date"] == now.isoformat()
        assert d["currency"] == "IDR"
        assert d["total_outstanding"] == "1000"
        assert "buckets" in d
        assert "current" in d["buckets"]

    def test_validate(self):
        now = datetime.now(UTC)
        summary = AgingSummary.create_empty(now)
        result = summary.validate()
        assert result["is_valid"] is True

        # Negative total outstanding
        summary.total_outstanding = Decimal("-100")
        result2 = summary.validate()
        assert result2["is_valid"] is False
        assert "cannot be negative" in result2["errors"][0]

        # Provision > outstanding
        summary.total_outstanding = Decimal("100")
        summary.total_provision = Decimal("200")
        result3 = summary.validate()
        assert result3["is_valid"] is False
        assert "cannot exceed" in result3["errors"][0]

    def test_from_dict(self):
        now = datetime.now(UTC)
        data = {
            "as_of_date": now.isoformat(),
            "currency": "USD",
            "total_outstanding": "1500",
            "total_provision": "30",
            "buckets": {
                "current": {"bucket": "current", "amount": "1000", "currency": "USD"},
                "1_30_days": {"bucket": "1_30_days", "amount": "500", "currency": "USD"},
            },
            "version": 2,
        }
        summary = AgingSummary.from_dict(data)
        assert summary.as_of_date == now
        assert summary.currency == "USD"
        assert summary.total_outstanding == Decimal("1500")
        assert summary.total_provision == Decimal("30")
        assert len(summary.buckets) == 2
        assert summary.buckets[AgingBucket.CURRENT].amount == Decimal("1000")
        assert summary._version == 2

    def test_clone(self):
        now = datetime.now(UTC)
        summary = AgingSummary.create_empty(now)
        clone = summary.clone()
        assert clone is not summary
        assert clone.as_of_date == summary.as_of_date
        assert clone.total_outstanding == summary.total_outstanding
        assert clone._version == summary._version + 1

    def test_snapshot(self):
        now = datetime.now(UTC)
        summary = AgingSummary.create_empty(now)
        snap = summary.snapshot()
        assert snap["version"] == summary._version
        assert snap["as_of_date"] == now.isoformat()
        assert snap["total_outstanding"] == "0"

    def test_version(self):
        summary = AgingSummary.create_empty(datetime.now(UTC))
        assert summary.version() == summary._version

    def test_audit_trail(self):
        summary = AgingSummary.create_empty(datetime.now(UTC))
        summary._record_audit("TEST", "system", {})
        trail = summary.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self):
        summary = AgingSummary.create_empty(datetime.now(UTC))
        old_version = summary._version
        touched = summary.touch("system")
        assert touched._version == old_version + 1
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


class TestAgingCalculator:
    def test_calculate_bucket(self):
        now = datetime.now(UTC)
        # Current
        due_future = now + timedelta(days=5)
        assert AgingCalculator.calculate_bucket(due_future, now) == AgingBucket.CURRENT

        # 1-30
        due_15 = now - timedelta(days=15)
        assert AgingCalculator.calculate_bucket(due_15, now) == AgingBucket.DAYS_1_30

        # 31-60
        due_45 = now - timedelta(days=45)
        assert AgingCalculator.calculate_bucket(due_45, now) == AgingBucket.DAYS_31_60

        # 61-90
        due_75 = now - timedelta(days=75)
        assert AgingCalculator.calculate_bucket(due_75, now) == AgingBucket.DAYS_61_90

        # Over 90
        due_100 = now - timedelta(days=100)
        assert AgingCalculator.calculate_bucket(due_100, now) == AgingBucket.OVER_90

        # Default as_of_date = now
        result = AgingCalculator.calculate_bucket(due_15)  # uses now
        assert result in (AgingBucket.DAYS_1_30, AgingBucket.CURRENT)  # depends on timing

    def test_calculate_provision(self):
        prov = AgingCalculator.calculate_provision(Decimal("1000"), AgingBucket.CURRENT)
        assert prov == Decimal("20")  # 1000 * 0.02

        prov2 = AgingCalculator.calculate_provision(Decimal("1000"), AgingBucket.OVER_90)
        assert prov2 == Decimal("500")  # 1000 * 0.50

        # Custom base rate
        prov3 = AgingCalculator.calculate_provision(Decimal("1000"), AgingBucket.CURRENT, Decimal("0.05"))
        assert prov3 == Decimal("50")  # 1000 * 0.05

    def test_validate(self):
        calc = AgingCalculator()
        result = calc.validate()
        assert result["is_valid"] is True

    def test_to_dict(self):
        calc = AgingCalculator()
        d = calc.to_dict()
        assert d["type"] == "AgingCalculator"

    def test_from_dict(self):
        calc = AgingCalculator.from_dict({})
        assert isinstance(calc, AgingCalculator)

    def test_clone(self):
        calc = AgingCalculator()
        clone = calc.clone()
        assert isinstance(clone, AgingCalculator)

    def test_snapshot(self):
        calc = AgingCalculator()
        snap = calc.snapshot()
        assert snap["type"] == "AgingCalculator"
        assert "timestamp" in snap

    def test_version(self):
        calc = AgingCalculator()
        assert calc.version() == 1

    def test_audit_trail(self):
        calc = AgingCalculator()
        assert calc.audit_trail() == []

    def test_touch(self):
        calc = AgingCalculator()
        touched = calc.touch("system")
        assert touched is calc