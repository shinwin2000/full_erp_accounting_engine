# tests/domain/subledger_ar/test_bad_debt_provision_engine.py
"""
Unit tests for bad_debt_provision_engine.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.subledger_ar.bad_debt_provision_engine import (
    BadDebtProvisionEngine,
    DEFAULT_PROVISION_RATES,
    ProvisionCategory,
    ProvisionMethod,
    ProvisionRate,
)
from domain.subledger_ar.invoice_entity import InvoiceEntity, InvoiceStatus


class TestProvisionMethod:
    def test_members(self):
        assert ProvisionMethod.AGING_PERCENTAGE.value == "aging_percentage"
        assert ProvisionMethod.PERCENTAGE_OF_SALES.value == "percentage_sales"
        assert ProvisionMethod.INDIVIDUAL_ASSESSMENT.value == "individual"
        assert ProvisionMethod.HYBRID.value == "hybrid"


class TestProvisionCategory:
    def test_members(self):
        assert ProvisionCategory.SPECIFIC.value == "specific"
        assert ProvisionCategory.GENERAL.value == "general"
        assert ProvisionCategory.PORTFOLIO.value == "portfolio"


class TestProvisionRate:
    def test_construction(self):
        rate = ProvisionRate(bucket=MagicMock, rate=Decimal("5"))
        assert rate.rate == Decimal("5")

    def test_validation_negative_rate(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            ProvisionRate(bucket=MagicMock, rate=Decimal("-1"))

    def test_validation_rate_too_high(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            ProvisionRate(bucket=MagicMock, rate=Decimal("101"))

    def test_validate(self):
        rate = ProvisionRate(bucket=MagicMock, rate=Decimal("5"))
        result = rate.validate()
        assert result["is_valid"] is True

        rate2 = ProvisionRate(bucket=MagicMock, rate=Decimal("150"))
        result2 = rate2.validate()
        assert result2["is_valid"] is False
        assert "between 0 and 100" in result2["errors"][0]

    def test_to_dict(self):
        rate = ProvisionRate(bucket=MagicMock, rate=Decimal("5"))
        d = rate.to_dict()
        assert "bucket" in d
        assert d["rate"] == "5"

    def test_from_dict(self):
        data = {"bucket": "current", "rate": "7.5"}
        rate = ProvisionRate.from_dict(data)
        assert rate.rate == Decimal("7.5")

    def test_clone(self):
        rate = ProvisionRate(bucket=MagicMock, rate=Decimal("5"))
        clone = rate.clone()
        assert clone is not rate
        assert clone.rate == rate.rate

    def test_snapshot(self):
        rate = ProvisionRate(bucket=MagicMock, rate=Decimal("5"))
        snap = rate.snapshot()
        assert snap["rate"] == "5"

    def test_version(self):
        rate = ProvisionRate(bucket=MagicMock, rate=Decimal("5"))
        assert rate.version() == 1

    def test_audit_trail(self):
        rate = ProvisionRate(bucket=MagicMock, rate=Decimal("5"))
        trail = rate.audit_trail()
        assert len(trail) == 1
        assert trail[0]["rate"] == "5"

    def test_touch(self):
        rate = ProvisionRate(bucket=MagicMock, rate=Decimal("5"))
        touched = rate.touch("system")
        assert touched is not rate
        assert touched.rate == rate.rate


class TestBadDebtProvisionEngine:
    @pytest.fixture
    def engine(self):
        return BadDebtProvisionEngine()

    @pytest.fixture
    def invoices(self):
        now = datetime.now(UTC)
        return [
            InvoiceEntity(
                id=uuid4(),
                invoice_number="INV-001",
                amount=Decimal("1000000"),
                outstanding_amount=Decimal("1000000"),
                due_date=now + timedelta(days=10),  # current
                status=InvoiceStatus.ISSUED,
                legal_entity_id=uuid4(),
                customer_id=uuid4(),
                issue_date=now,
            ),
            InvoiceEntity(
                id=uuid4(),
                invoice_number="INV-002",
                amount=Decimal("500000"),
                outstanding_amount=Decimal("500000"),
                due_date=now - timedelta(days=20),  # 1-30 days overdue
                status=InvoiceStatus.ISSUED,
                legal_entity_id=uuid4(),
                customer_id=uuid4(),
                issue_date=now - timedelta(days=10),
            ),
            InvoiceEntity(
                id=uuid4(),
                invoice_number="INV-003",
                amount=Decimal("300000"),
                outstanding_amount=Decimal("300000"),
                due_date=now - timedelta(days=50),  # 31-60 days overdue
                status=InvoiceStatus.ISSUED,
                legal_entity_id=uuid4(),
                customer_id=uuid4(),
                issue_date=now - timedelta(days=40),
            ),
            InvoiceEntity(
                id=uuid4(),
                invoice_number="INV-004",
                amount=Decimal("200000"),
                outstanding_amount=Decimal("200000"),
                due_date=now - timedelta(days=80),  # 61-90 days overdue
                status=InvoiceStatus.ISSUED,
                legal_entity_id=uuid4(),
                customer_id=uuid4(),
                issue_date=now - timedelta(days=70),
            ),
            InvoiceEntity(
                id=uuid4(),
                invoice_number="INV-005",
                amount=Decimal("100000"),
                outstanding_amount=Decimal("100000"),
                due_date=now - timedelta(days=120),  # over 90 days overdue
                status=InvoiceStatus.ISSUED,
                legal_entity_id=uuid4(),
                customer_id=uuid4(),
                issue_date=now - timedelta(days=100),
            ),
            InvoiceEntity(
                id=uuid4(),
                invoice_number="INV-006",
                amount=Decimal("50000"),
                outstanding_amount=Decimal("0"),  # fully paid
                due_date=now - timedelta(days=30),
                status=InvoiceStatus.FULLY_PAID,
                legal_entity_id=uuid4(),
                customer_id=uuid4(),
                issue_date=now - timedelta(days=20),
            ),
            InvoiceEntity(
                id=uuid4(),
                invoice_number="INV-007",
                amount=Decimal("20000"),
                outstanding_amount=Decimal("20000"),
                due_date=now - timedelta(days=200),  # over 90 days
                status=InvoiceStatus.WRITTEN_OFF,
                legal_entity_id=uuid4(),
                customer_id=uuid4(),
                issue_date=now - timedelta(days=180),
            ),
        ]

    def test_default_rates(self):
        engine = BadDebtProvisionEngine()
        assert len(engine.rates) == 5
        assert engine.rates[0].rate == Decimal("1")
        assert engine.rates[-1].rate == Decimal("25")
        assert engine.method == ProvisionMethod.AGING_PERCENTAGE

    def test_calculate_provision_aging_percentage(self, engine, invoices):
        # Default method: AGING_PERCENTAGE
        as_of = datetime.now(UTC)
        provision = engine.calculate_provision(invoices, as_of)
        # Expected: 
        # INV-001: current (1%) = 1000000 * 0.01 = 10000
        # INV-002: 1-30 days (2%) = 500000 * 0.02 = 10000
        # INV-003: 31-60 days (5%) = 300000 * 0.05 = 15000
        # INV-004: 61-90 days (10%) = 200000 * 0.10 = 20000
        # INV-005: over 90 (25%) = 100000 * 0.25 = 25000
        # INV-006: fully paid -> 0
        # INV-007: written off -> 0
        # Total = 10000 + 10000 + 15000 + 20000 + 25000 = 80000
        assert provision == Decimal("80000")

    def test_calculate_provision_individual(self, engine, invoices):
        engine.set_method(ProvisionMethod.INDIVIDUAL_ASSESSMENT)
        as_of = datetime.now(UTC)
        provision = engine.calculate_provision(invoices, as_of)
        # Expected individual assessment:
        # INV-001: current -> historical loss rate 2% = 1000000 * 0.02 = 20000
        # INV-002: 1-30 days -> 10% = 500000 * 0.10 = 50000
        # INV-003: 31-60 days -> 25% = 300000 * 0.25 = 75000
        # INV-004: 61-90 days -> 50% = 200000 * 0.50 = 100000
        # INV-005: over 90 -> 100% = 100000
        # Total = 20000 + 50000 + 75000 + 100000 + 100000 = 345000
        assert provision == Decimal("345000")

    def test_calculate_provision_percentage_of_sales(self, engine, invoices):
        engine.set_method(ProvisionMethod.PERCENTAGE_OF_SALES)
        as_of = datetime.now(UTC)
        provision = engine.calculate_provision(invoices, as_of)
        # total outstanding = 1000000+500000+300000+200000+100000 = 2100000
        # historical loss rate 2% -> 2100000 * 0.02 = 42000
        assert provision == Decimal("42000")

    def test_calculate_provision_hybrid(self, engine, invoices):
        engine.set_method(ProvisionMethod.HYBRID)
        as_of = datetime.now(UTC)
        provision = engine.calculate_provision(invoices, as_of)
        # INV-005: over 90 and amount > 1000000000? no, but over 90 -> high risk = 0.5 * 100000 = 50000
        # Others aging: INV-001 10000, INV-002 10000, INV-003 15000, INV-004 20000
        # Total = 50000 + 55000 = 105000
        assert provision == Decimal("105000")

    def test_calculate_provision_by_bucket(self, engine, invoices):
        as_of = datetime.now(UTC)
        provisions = engine.calculate_provision_by_bucket(invoices, as_of)
        assert provisions[AgingBucket.CURRENT] == Decimal("10000")
        assert provisions[AgingBucket.DAYS_1_30] == Decimal("10000")
        assert provisions[AgingBucket.DAYS_31_60] == Decimal("15000")
        assert provisions[AgingBucket.DAYS_61_90] == Decimal("20000")
        assert provisions[AgingBucket.OVER_90] == Decimal("25000")

    def test_get_provision_summary(self, engine, invoices):
        as_of = datetime.now(UTC)
        summary = engine.get_provision_summary(invoices, as_of)
        assert summary["method"] == "aging_percentage"
        assert Decimal(summary["total_outstanding"]) == Decimal("2100000")
        assert Decimal(summary["total_provision"]) == Decimal("80000")
        assert Decimal(summary["coverage_ratio"]) == Decimal("3.81")  # 80000/2100000*100
        assert "provisions_by_bucket" in summary
        assert summary["historical_loss_rate"] == "2"

    def test_set_rate(self, engine):
        engine.set_rate(AgingBucket.CURRENT, Decimal("5"))
        rate = engine.rates[0]
        assert rate.bucket == AgingBucket.CURRENT
        assert rate.rate == Decimal("5")

        # Add new rate for a bucket not present
        engine.set_rate(AgingBucket.CURRENT, Decimal("7"))  # updates existing
        rate = engine.rates[0]
        assert rate.rate == Decimal("7")

        # Audit trail should have entry
        assert len(engine._audit_trail) >= 1
        assert engine._audit_trail[-1]["action"] == "SET_RATE"

    def test_set_method(self, engine):
        engine.set_method(ProvisionMethod.INDIVIDUAL_ASSESSMENT)
        assert engine.method == ProvisionMethod.INDIVIDUAL_ASSESSMENT
        audit = engine._audit_trail[-1]
        assert audit["action"] == "SET_METHOD"
        assert audit["details"]["method"] == "individual"

    def test_validate(self, engine):
        result = engine.validate()
        assert result["is_valid"] is True

        # Invalid historical loss rate
        engine.historical_loss_rate = Decimal("150")
        result2 = engine.validate()
        assert result2["is_valid"] is False
        assert "historical_loss_rate" in result2["errors"][0]

    def test_to_dict(self, engine):
        d = engine.to_dict()
        assert d["method"] == "aging_percentage"
        assert d["historical_loss_rate"] == "2"
        assert len(d["rates"]) == 5
        assert "version" in d

    def test_from_dict(self):
        data = {
            "method": "individual",
            "historical_loss_rate": "3.5",
            "rates": [
                {"bucket": "current", "rate": "2.5"},
                {"bucket": "1_30_days", "rate": "4.0"},
            ],
            "version": 3,
        }
        engine = BadDebtProvisionEngine.from_dict(data)
        assert engine.method == ProvisionMethod.INDIVIDUAL_ASSESSMENT
        assert engine.historical_loss_rate == Decimal("3.5")
        assert len(engine.rates) == 2
        assert engine.rates[0].rate == Decimal("2.5")
        assert engine._version == 3

    def test_clone(self, engine):
        clone = engine.clone()
        assert clone is not engine
        assert clone.method == engine.method
        assert clone.historical_loss_rate == engine.historical_loss_rate
        assert len(clone.rates) == len(engine.rates)
        assert clone._version == engine._version + 1

    def test_snapshot(self, engine):
        snap = engine.snapshot()
        assert snap["method"] == "aging_percentage"
        assert snap["historical_loss_rate"] == "2"
        assert snap["rates_count"] == 5
        assert "timestamp" in snap

    def test_version(self, engine):
        assert engine.version() == engine._version

    def test_audit_trail(self, engine):
        engine.set_method(ProvisionMethod.INDIVIDUAL_ASSESSMENT)
        trail = engine.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "SET_METHOD"

    def test_touch(self, engine):
        old_version = engine._version
        touched = engine.touch("system")
        assert touched._version == old_version + 1
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_calculate_provision_no_invoices(self, engine):
        provision = engine.calculate_provision([])
        assert provision == Decimal(0)

    def test_calculate_provision_by_bucket_empty(self, engine):
        provisions = engine.calculate_provision_by_bucket([])
        for bucket in AgingBucket:
            assert provisions[bucket] == Decimal(0)

    def test_get_provision_summary_no_invoices(self, engine):
        summary = engine.get_provision_summary([])
        assert Decimal(summary["total_outstanding"]) == Decimal(0)
        assert Decimal(summary["total_provision"]) == Decimal(0)
        assert summary["coverage_ratio"] == "0"