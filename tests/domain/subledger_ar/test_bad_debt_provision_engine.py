# tests/domain/subledger_ar/test_bad_debt_provision_engine.py
"""
Comprehensive unit tests for bad_debt_provision_engine.py.
Covers all public and private methods with strong assertions.
All datetime usage is mocked to avoid flakiness.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.subledger_ar.aging_bucket_vo import AgingBucket
from domain.subledger_ar.bad_debt_provision_engine import (
    DEFAULT_PROVISION_RATES,
    BadDebtProvisionEngine,
    ProvisionCategory,
    ProvisionMethod,
    ProvisionRate,
)
from domain.subledger_ar.invoice_entity import InvoiceEntity, InvoiceStatus

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=10)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("domain.subledger_ar.bad_debt_provision_engine.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Helper fixtures
# ============================================================================

@pytest.fixture
def sample_invoices():
    now = FIXED_NOW
    return [
        InvoiceEntity(
            id=uuid4(),
            invoice_number="INV-001",
            amount=Decimal("1000000"),
            outstanding_amount=Decimal("1000000"),
            due_date=now + timedelta(days=10),
            status=InvoiceStatus.ISSUED,
            legal_entity_id=uuid4(),
            customer_id=uuid4(),
            issue_date=now - timedelta(days=5),
        ),
        InvoiceEntity(
            id=uuid4(),
            invoice_number="INV-002",
            amount=Decimal("500000"),
            outstanding_amount=Decimal("500000"),
            due_date=now - timedelta(days=20),
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
            due_date=now - timedelta(days=50),
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
            due_date=now - timedelta(days=80),
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
            due_date=now - timedelta(days=120),
            status=InvoiceStatus.ISSUED,
            legal_entity_id=uuid4(),
            customer_id=uuid4(),
            issue_date=now - timedelta(days=100),
        ),
        InvoiceEntity(
            id=uuid4(),
            invoice_number="INV-006",
            amount=Decimal("50000"),
            outstanding_amount=Decimal("0"),
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
            due_date=now - timedelta(days=200),
            status=InvoiceStatus.WRITTEN_OFF,
            legal_entity_id=uuid4(),
            customer_id=uuid4(),
            issue_date=now - timedelta(days=180),
        ),
    ]


# ============================================================================
# Tests for ProvisionMethod enum
# ============================================================================

class TestProvisionMethod:
    def test_members(self):
        assert ProvisionMethod.AGING_PERCENTAGE.value == "aging_percentage"
        assert ProvisionMethod.PERCENTAGE_OF_SALES.value == "percentage_sales"
        assert ProvisionMethod.INDIVIDUAL_ASSESSMENT.value == "individual"
        assert ProvisionMethod.HYBRID.value == "hybrid"


# ============================================================================
# Tests for ProvisionCategory enum
# ============================================================================

class TestProvisionCategory:
    def test_members(self):
        assert ProvisionCategory.SPECIFIC.value == "specific"
        assert ProvisionCategory.GENERAL.value == "general"
        assert ProvisionCategory.PORTFOLIO.value == "portfolio"


# ============================================================================
# Tests for ProvisionRate
# ============================================================================

class TestProvisionRate:
    def test_construction_valid(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("5"))
        assert rate.bucket == AgingBucket.CURRENT
        assert rate.rate == Decimal("5")

    def test_validation_negative_rate(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("-1"))

    def test_validation_rate_too_high(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("101"))

    def test_validate_valid(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("5"))
        result = rate.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("150"))
        result = rate.validate()
        assert result["is_valid"] is False
        assert "between 0 and 100" in result["errors"][0]

    def test_to_dict(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("5"))
        d = rate.to_dict()
        assert d["bucket"] == "current"
        assert d["rate"] == "5"

    def test_from_dict(self):
        data = {"bucket": "current", "rate": "7.5"}
        rate = ProvisionRate.from_dict(data)
        assert rate.bucket == AgingBucket.CURRENT
        assert rate.rate == Decimal("7.5")

    def test_clone(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("5"))
        clone = rate.clone()
        assert clone is not rate
        assert clone.bucket == rate.bucket
        assert clone.rate == rate.rate

    def test_snapshot(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("5"))
        snap = rate.snapshot()
        assert snap["bucket"] == "current"
        assert snap["rate"] == "5"

    def test_version(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("5"))
        assert rate.version() == 1

    def test_audit_trail(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("5"))
        trail = rate.audit_trail()
        assert len(trail) == 1
        assert trail[0]["bucket"] == "current"
        assert trail[0]["rate"] == "5"

    def test_touch(self):
        rate = ProvisionRate(bucket=AgingBucket.CURRENT, rate=Decimal("5"))
        touched = rate.touch("system")
        assert touched is not rate
        assert touched.bucket == rate.bucket
        assert touched.rate == rate.rate


# ============================================================================
# Tests for BadDebtProvisionEngine
# ============================================================================

class TestBadDebtProvisionEngine:
    @pytest.fixture
    def engine(self):
        return BadDebtProvisionEngine()

    def test_default_rates(self, engine):
        assert len(engine.rates) == 5
        assert engine.rates[0].bucket == AgingBucket.CURRENT
        assert engine.rates[0].rate == Decimal("1")
        assert engine.rates[-1].bucket == AgingBucket.OVER_90
        assert engine.rates[-1].rate == Decimal("25")
        assert engine.method == ProvisionMethod.AGING_PERCENTAGE
        assert engine.historical_loss_rate == Decimal("2")

    # ---- Public calculate_provision ----
    def test_calculate_provision_aging_percentage(self, engine, sample_invoices):
        provision = engine.calculate_provision(sample_invoices, FIXED_NOW)
        # INV-001: current (1%) = 1000000 * 0.01 = 10000
        # INV-002: 1-30 (2%) = 500000 * 0.02 = 10000
        # INV-003: 31-60 (5%) = 300000 * 0.05 = 15000
        # INV-004: 61-90 (10%) = 200000 * 0.10 = 20000
        # INV-005: over 90 (25%) = 100000 * 0.25 = 25000
        # INV-006: fully paid -> 0
        # INV-007: written off -> 0
        # Total = 80000
        assert provision == Decimal("80000")

    def test_calculate_provision_individual(self, engine, sample_invoices):
        engine.set_method(ProvisionMethod.INDIVIDUAL_ASSESSMENT)
        provision = engine.calculate_provision(sample_invoices, FIXED_NOW)
        # INV-001: current -> historical_loss_rate 2% = 1000000 * 0.02 = 20000
        # INV-002: 20 days overdue -> 10% = 500000 * 0.10 = 50000
        # INV-003: 50 days -> 25% = 300000 * 0.25 = 75000
        # INV-004: 80 days -> 50% = 200000 * 0.50 = 100000
        # INV-005: 120 days -> 100% = 100000
        # INV-006: paid -> 0
        # INV-007: written off -> 0
        # Total = 345000
        assert provision == Decimal("345000")

    def test_calculate_provision_percentage_of_sales(self, engine, sample_invoices):
        engine.set_method(ProvisionMethod.PERCENTAGE_OF_SALES)
        provision = engine.calculate_provision(sample_invoices, FIXED_NOW)
        # total outstanding = 1000000+500000+300000+200000+100000 = 2100000
        # historical_loss_rate 2% -> 2100000 * 0.02 = 42000
        assert provision == Decimal("42000")

    def test_calculate_provision_hybrid(self, engine, sample_invoices):
        engine.set_method(ProvisionMethod.HYBRID)
        provision = engine.calculate_provision(sample_invoices, FIXED_NOW)
        # INV-005: over 90 -> high risk = 100000 * 0.5 = 50000
        # Others aging: INV-001 10000, INV-002 10000, INV-003 15000, INV-004 20000
        # Total = 50000 + 55000 = 105000
        assert provision == Decimal("105000")

    # ---- Private methods directly tested ----
    def test__calculate_by_aging(self, engine, sample_invoices):
        result = engine._calculate_by_aging(sample_invoices, FIXED_NOW)
        assert result == Decimal("80000")

    def test__calculate_individual(self, engine, sample_invoices):
        result = engine._calculate_individual(sample_invoices, FIXED_NOW)
        assert result == Decimal("345000")

    def test__calculate_by_percentage(self, engine, sample_invoices):
        result = engine._calculate_by_percentage(sample_invoices, FIXED_NOW)
        assert result == Decimal("42000")

    def test__calculate_hybrid(self, engine, sample_invoices):
        result = engine._calculate_hybrid(sample_invoices, FIXED_NOW)
        assert result == Decimal("105000")

    # ---- calculate_provision_by_bucket ----
    def test_calculate_provision_by_bucket(self, engine, sample_invoices):
        provisions = engine.calculate_provision_by_bucket(sample_invoices, FIXED_NOW)
        assert provisions[AgingBucket.CURRENT] == Decimal("10000")
        assert provisions[AgingBucket.DAYS_1_30] == Decimal("10000")
        assert provisions[AgingBucket.DAYS_31_60] == Decimal("15000")
        assert provisions[AgingBucket.DAYS_61_90] == Decimal("20000")
        assert provisions[AgingBucket.OVER_90] == Decimal("25000")

    # ---- get_provision_summary ----
    def test_get_provision_summary(self, engine, sample_invoices):
        summary = engine.get_provision_summary(sample_invoices, FIXED_NOW)
        assert summary["method"] == "aging_percentage"
        assert Decimal(summary["total_outstanding"]) == Decimal("2100000")
        assert Decimal(summary["total_provision"]) == Decimal("80000")
        # coverage_ratio = 80000/2100000*100 = 3.8095...
        assert Decimal(summary["coverage_ratio"]).quantize(Decimal("0.01")) == Decimal("3.81")
        assert "provisions_by_bucket" in summary
        assert summary["historical_loss_rate"] == "2"

    # ---- set_rate ----
    def test_set_rate_update(self, engine):
        engine.set_rate(AgingBucket.CURRENT, Decimal("5"))
        rate = next(r for r in engine.rates if r.bucket == AgingBucket.CURRENT)
        assert rate.rate == Decimal("5")
        # Audit trail
        trail = engine.audit_trail()
        assert any(entry["action"] == "SET_RATE" for entry in trail)

    def test_set_rate_add_new(self, engine):
        # Remove current bucket first
        engine.rates = [r for r in engine.rates if r.bucket != AgingBucket.CURRENT]
        engine.set_rate(AgingBucket.CURRENT, Decimal("7"))
        rate = next(r for r in engine.rates if r.bucket == AgingBucket.CURRENT)
        assert rate.rate == Decimal("7")

    # ---- set_method ----
    def test_set_method(self, engine):
        engine.set_method(ProvisionMethod.INDIVIDUAL_ASSESSMENT)
        assert engine.method == ProvisionMethod.INDIVIDUAL_ASSESSMENT
        trail = engine.audit_trail()
        assert any(entry["action"] == "SET_METHOD" for entry in trail)

    # ---- validate ----
    def test_validate_valid(self, engine):
        result = engine.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_historical_rate(self, engine):
        engine.historical_loss_rate = Decimal("150")
        result = engine.validate()
        assert result["is_valid"] is False
        assert any("historical_loss_rate" in e for e in result["errors"])

    def test_validate_invalid_rate(self, engine):
        engine.rates[0].rate = Decimal("150")
        result = engine.validate()
        assert result["is_valid"] is False
        assert any("Rate for current" in e for e in result["errors"])

    # ---- to_dict ----
    def test_to_dict(self, engine):
        d = engine.to_dict()
        assert d["method"] == "aging_percentage"
        assert d["historical_loss_rate"] == "2"
        assert len(d["rates"]) == 5
        assert d["version"] == 1

    # ---- from_dict ----
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
        assert engine.rates[0].bucket == AgingBucket.CURRENT
        assert engine.rates[0].rate == Decimal("2.5")
        assert engine._version == 3

    # ---- clone ----
    def test_clone(self, engine):
        clone = engine.clone()
        assert clone is not engine
        assert clone.method == engine.method
        assert clone.historical_loss_rate == engine.historical_loss_rate
        assert len(clone.rates) == len(engine.rates)
        assert clone._version == engine._version + 1

    # ---- snapshot ----
    def test_snapshot(self, engine):
        snap = engine.snapshot()
        assert snap["method"] == "aging_percentage"
        assert snap["historical_loss_rate"] == "2"
        assert snap["rates_count"] == 5
        assert "timestamp" in snap

    # ---- version ----
    def test_version(self, engine):
        assert engine.version() == engine._version

    # ---- audit_trail ----
    def test_audit_trail(self, engine):
        engine.set_method(ProvisionMethod.INDIVIDUAL_ASSESSMENT)
        trail = engine.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "SET_METHOD"

    # ---- touch ----
    def test_touch(self, engine):
        old_version = engine._version
        touched = engine.touch("system")
        assert touched._version == old_version + 1
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    # ---- Edge cases ----
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

    def test_default_as_of_date_uses_now(self, engine, sample_invoices):
        # When as_of_date is None, it should use datetime.now(UTC) (mocked to FIXED_NOW)
        provision = engine.calculate_provision(sample_invoices)
        # Should match the calculation with FIXED_NOW
        assert provision == Decimal("80000")

    def test_historical_loss_rate_change_affects_calculation(self, engine, sample_invoices):
        engine.historical_loss_rate = Decimal("5")
        engine.set_method(ProvisionMethod.PERCENTAGE_OF_SALES)
        provision = engine.calculate_provision(sample_invoices)
        # total outstanding 2100000 * 0.05 = 105000
        assert provision == Decimal("105000")