# test_tax_compliance_helper.py
# ==============================
# Comprehensive tests for domain/umkm_simplified/tax_compliance_helper.py.
# Covers all enums, value objects, business methods, and entity base methods.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from domain.umkm_simplified.simplified_journal_entity import (
    SimplifiedJournalEntity,
    TransactionType,
)
from domain.umkm_simplified.tax_compliance_helper import (
    TaxCalculationResult,
    TaxComplianceHelper,
    UMKMStatus,
    UMKMTaxRegime,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_transactions():
    """Create sample SimplifiedJournalEntity transactions."""
    txs = []
    # Income transactions in January
    for i in range(3):
        txs.append(
            SimplifiedJournalEntity(
                journal_id=MagicMock(),
                transaction_date=datetime(2025, 1, 5 + i, 12, 0, tzinfo=UTC),
                description=f"Income {i+1}",
                amount=Decimal("1000000"),
                transaction_type=TransactionType.INCOME,
                category="Sales",
            )
        )
    # Expense transactions (should be ignored for revenue)
    txs.append(
        SimplifiedJournalEntity(
            journal_id=MagicMock(),
            transaction_date=datetime(2025, 1, 10, 12, 0, tzinfo=UTC),
            description="Expense",
            amount=Decimal("500000"),
            transaction_type=TransactionType.EXPENSE,
            category="Supplies",
        )
    )
    # Another income in February (should be excluded for monthly Jan)
    txs.append(
        SimplifiedJournalEntity(
            journal_id=MagicMock(),
            transaction_date=datetime(2025, 2, 1, 12, 0, tzinfo=UTC),
            description="Feb income",
            amount=Decimal("2000000"),
            transaction_type=TransactionType.INCOME,
            category="Sales",
        )
    )
    return txs


@pytest.fixture
def helper():
    """Fresh TaxComplianceHelper."""
    return TaxComplianceHelper()


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestUMKMTaxRegime:
    def test_members_exist(self):
        assert hasattr(UMKMTaxRegime, "FINAL_0_5_PERCENT")
        assert hasattr(UMKMTaxRegime, "GENERAL_RATE")
        assert hasattr(UMKMTaxRegime, "NOT_REGISTERED")

    def test_member_is_instance(self):
        assert isinstance(UMKMTaxRegime.FINAL_0_5_PERCENT, UMKMTaxRegime)

    def test_display_name(self):
        assert UMKMTaxRegime.FINAL_0_5_PERCENT.display_name() == "PP 23 (0.5%)"
        assert UMKMTaxRegime.GENERAL_RATE.display_name() == "Tarif Umum"
        assert UMKMTaxRegime.NOT_REGISTERED.display_name() == "Belum Terdaftar"


class TestUMKMStatus:
    def test_members_exist(self):
        assert hasattr(UMKMStatus, "MSME")
        assert hasattr(UMKMStatus, "STARTUP")
        assert hasattr(UMKMStatus, "GROWING")
        assert hasattr(UMKMStatus, "ESTABLISHED")

    def test_member_is_instance(self):
        assert isinstance(UMKMStatus.MSME, UMKMStatus)


# ----------------------------------------------------------------------
# TaxCalculationResult
# ----------------------------------------------------------------------
class TestTaxCalculationResult:
    @pytest.fixture
    def result(self):
        return TaxCalculationResult(
            period="2025-01",
            total_revenue=Decimal("3000000"),
            taxable_revenue=Decimal("3000000"),
            tax_rate=Decimal("0.5"),
            tax_amount=Decimal("15000"),
            tax_regime=UMKMTaxRegime.FINAL_0_5_PERCENT,
            notes="Test",
        )

    def test_construction(self, result):
        assert result.period == "2025-01"
        assert result.total_revenue == Decimal("3000000")
        assert result.taxable_revenue == Decimal("3000000")
        assert result.tax_rate == Decimal("0.5")
        assert result.tax_amount == Decimal("15000")
        assert result.tax_regime == UMKMTaxRegime.FINAL_0_5_PERCENT
        assert result.notes == "Test"
        assert result._version == 1
        assert len(result._snapshots) == 1
        assert len(result._audit_trail) == 0  # no audit recorded by default

    def test_validate_valid(self, result):
        validation = result.validate()
        assert validation["is_valid"] is True
        assert validation["errors"] == []

    def test_validate_negative_revenue(self):
        invalid = TaxCalculationResult(
            period="2025-01",
            total_revenue=Decimal("-1000"),
            taxable_revenue=Decimal("-1000"),
            tax_rate=Decimal("0.5"),
            tax_amount=Decimal("-5"),
            tax_regime=UMKMTaxRegime.FINAL_0_5_PERCENT,
        )
        validation = invalid.validate()
        assert validation["is_valid"] is False
        assert "Total revenue cannot be negative" in validation["errors"]
        assert "Taxable revenue cannot be negative" in validation["errors"]
        assert "Tax amount cannot be negative" in validation["errors"]

    def test_validate_invalid_tax_rate(self):
        invalid = TaxCalculationResult(
            period="2025-01",
            total_revenue=Decimal("1000"),
            taxable_revenue=Decimal("1000"),
            tax_rate=Decimal("101"),
            tax_amount=Decimal("100"),
            tax_regime=UMKMTaxRegime.FINAL_0_5_PERCENT,
        )
        validation = invalid.validate()
        assert validation["is_valid"] is False
        assert "Tax rate must be between 0 and 100" in validation["errors"]

    def test_to_dict(self, result):
        d = result.to_dict()
        assert d["period"] == "2025-01"
        assert d["total_revenue"] == "3000000"
        assert d["taxable_revenue"] == "3000000"
        assert d["tax_rate"] == "0.5"
        assert d["tax_amount"] == "15000"
        assert d["tax_regime"] == "final_0.5"
        assert d["notes"] == "Test"
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "period": "2025-02",
            "total_revenue": "2000000",
            "taxable_revenue": "2000000",
            "tax_rate": "0.5",
            "tax_amount": "10000",
            "tax_regime": "final_0.5",
            "notes": "From dict",
            "version": 2,
        }
        result = TaxCalculationResult.from_dict(data)
        assert result.period == "2025-02"
        assert result.total_revenue == Decimal("2000000")
        assert result.taxable_revenue == Decimal("2000000")
        assert result.tax_rate == Decimal("0.5")
        assert result.tax_amount == Decimal("10000")
        assert result.tax_regime == UMKMTaxRegime.FINAL_0_5_PERCENT
        assert result.notes == "From dict"
        assert result._version == 2

    def test_clone(self, result):
        cloned = result.clone()
        assert cloned.period == result.period
        assert cloned.total_revenue == result.total_revenue
        assert cloned.tax_amount == result.tax_amount
        assert cloned._version == result._version + 1
        assert cloned is not result
        # Snapshots and audit trail should be separate
        assert cloned._snapshots != result._snapshots
        assert cloned._audit_trail != result._audit_trail

    def test_snapshot(self, result):
        snap = result.snapshot()
        assert snap["version"] == 1
        assert snap["period"] == "2025-01"
        assert snap["tax_amount"] == "15000"
        assert "timestamp" in snap

    def test_version(self, result):
        assert result.version() == 1

    def test_audit_trail(self, result):
        # Initially empty
        assert result.audit_trail() == []
        # Record an audit
        result._record_audit("TEST", "system", {"key": "value"})
        trail = result.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "system"

    def test_touch(self, result):
        touched = result.touch("admin")
        assert touched.period == result.period
        assert touched._version == result._version + 1
        trail = touched.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "admin"


# ----------------------------------------------------------------------
# TaxComplianceHelper
# ----------------------------------------------------------------------
class TestTaxComplianceHelper:
    def test_initial_state(self, helper):
        assert Decimal("4800000000") == helper.PP23_THRESHOLD
        assert Decimal("0.5") == helper.PP23_RATE
        assert Decimal("22") == helper.GENERAL_RATE
        assert helper._calculation_history == []
        assert helper._version == 1
        assert helper._audit_trail == []
        assert helper._snapshots == []

    # ---- calculate_monthly_tax ----
    def test_calculate_monthly_tax_pp23(self, helper, sample_transactions):
        result = helper.calculate_monthly_tax(
            transactions=sample_transactions,
            year=2025,
            month=1,
            ytd_revenue=Decimal("0"),
            tax_regime=UMKMTaxRegime.FINAL_0_5_PERCENT,
        )
        # Monthly revenue from Jan incomes: 3 * 1,000,000 = 3,000,000
        assert result.period == "2025-01"
        assert result.total_revenue == Decimal("3000000")
        assert result.taxable_revenue == Decimal("3000000")
        assert result.tax_rate == Decimal("0.5")
        assert result.tax_amount == Decimal("15000")  # 3,000,000 * 0.5%
        assert result.tax_regime == UMKMTaxRegime.FINAL_0_5_PERCENT
        assert "PP23 final rate" in result.notes
        # Check history stored
        assert len(helper._calculation_history) == 1
        assert helper._calculation_history[0] is result
        # Check audit trail
        assert len(helper._audit_trail) == 1
        assert helper._audit_trail[0]["action"] == "CALCULATE_MONTHLY_TAX"

    def test_calculate_monthly_tax_general_when_ytd_exceeds_threshold(self, helper, sample_transactions):
        # YTD already exceeds threshold
        result = helper.calculate_monthly_tax(
            transactions=sample_transactions,
            year=2025,
            month=1,
            ytd_revenue=Decimal("5000000000"),  # above 4.8B
            tax_regime=UMKMTaxRegime.FINAL_0_5_PERCENT,
        )
        assert result.total_revenue == Decimal("3000000")
        assert result.tax_rate == Decimal("22")  # general rate
        assert result.tax_regime == UMKMTaxRegime.GENERAL_RATE
        assert "exceeds PP23 threshold" in result.notes
        assert result.tax_amount == Decimal("660000")  # 3,000,000 * 22%

    def test_calculate_monthly_tax_general_forced(self, helper, sample_transactions):
        result = helper.calculate_monthly_tax(
            transactions=sample_transactions,
            year=2025,
            month=1,
            tax_regime=UMKMTaxRegime.GENERAL_RATE,
        )
        assert result.tax_rate == Decimal("22")
        assert result.tax_regime == UMKMTaxRegime.GENERAL_RATE
        assert "general income tax rate" in result.notes

    def test_calculate_monthly_tax_no_income_transactions(self, helper):
        # Only expense transactions
        txs = [
            SimplifiedJournalEntity(
                journal_id=MagicMock(),
                transaction_date=datetime(2025, 1, 5, 12, 0, tzinfo=UTC),
                description="Expense",
                amount=Decimal("1000"),
                transaction_type=TransactionType.EXPENSE,
            )
        ]
        result = helper.calculate_monthly_tax(txs, 2025, 1)
        assert result.total_revenue == Decimal("0")
        assert result.tax_amount == Decimal("0")

    def test_calculate_monthly_tax_filters_by_date(self, helper, sample_transactions):
        # Feb income should not be included in Jan
        result = helper.calculate_monthly_tax(sample_transactions, 2025, 2)
        # Only one income in Feb: 2,000,000
        assert result.total_revenue == Decimal("2000000")
        assert result.tax_amount == Decimal("10000")  # 2,000,000 * 0.5%

    # ---- calculate_annual_tax ----
    def test_calculate_annual_tax_pp23(self, helper, sample_transactions):
        result = helper.calculate_annual_tax(sample_transactions, 2025)
        # Annual revenue: Jan incomes 3,000,000 + Feb income 2,000,000 = 5,000,000
        assert result.period == "2025"
        assert result.total_revenue == Decimal("5000000")
        assert result.tax_rate == Decimal("0.5")
        assert result.tax_regime == UMKMTaxRegime.FINAL_0_5_PERCENT
        assert result.tax_amount == Decimal("25000")  # 5,000,000 * 0.5%
        assert "within PP23 threshold" in result.notes
        assert len(helper._calculation_history) == 1

    def test_calculate_annual_tax_general_when_exceeds_threshold(self, helper, sample_transactions):
        # Add more income to exceed threshold
        extra = []
        for i in range(5000):  # 5,000 * 1,000,000 = 5,000,000,000
            extra.append(
                SimplifiedJournalEntity(
                    journal_id=MagicMock(),
                    transaction_date=datetime(2025, 1, 5, 12, 0, tzinfo=UTC),
                    description=f"Income {i}",
                    amount=Decimal("1000000"),
                    transaction_type=TransactionType.INCOME,
                )
            )
        all_txs = sample_transactions + extra
        result = helper.calculate_annual_tax(all_txs, 2025)
        # Annual revenue > 4.8B -> general rate
        assert result.tax_rate == Decimal("22")
        assert result.tax_regime == UMKMTaxRegime.GENERAL_RATE
        assert "exceeds PP23 threshold" in result.notes

    # ---- calculate_pph_final ----
    def test_calculate_pph_final_applies(self, helper):
        monthly = Decimal("3000000")
        ytd = Decimal("1000000")
        result = helper.calculate_pph_final(monthly, ytd)
        assert result["applies"] is True
        assert result["monthly_revenue"] == "3000000"
        assert result["tax_rate"] == "0.5"
        assert result["tax_amount"] == "15000"
        assert result["remaining_until_threshold"] == str(helper.PP23_THRESHOLD - ytd)

    def test_calculate_pph_final_not_applies(self, helper):
        monthly = Decimal("3000000")
        ytd = Decimal("5000000000")
        result = helper.calculate_pph_final(monthly, ytd)
        assert result["applies"] is False
        assert "exceeds PP23 threshold" in result["reason"]
        assert result["suggested_action"] == "Use general income tax rate"

    # ---- check_threshold_remaining ----
    def test_check_threshold_remaining_ok(self, helper):
        ytd = Decimal("1000000000")
        result = helper.check_threshold_remaining(ytd)
        assert result["status"] == "OK"
        assert "Within PP23 threshold" in result["message"]
        assert Decimal(result["remaining"]) > 0

    def test_check_threshold_remaining_warning(self, helper):
        ytd = helper.PP23_THRESHOLD * Decimal("0.95")  # 95% of threshold
        result = helper.check_threshold_remaining(ytd)
        assert result["status"] == "WARNING"
        assert "Approaching PP23 threshold" in result["message"]

    def test_check_threshold_remaining_exceeded(self, helper):
        ytd = helper.PP23_THRESHOLD + Decimal("100")
        result = helper.check_threshold_remaining(ytd)
        assert result["status"] == "EXCEEDED"
        assert "Use general income tax rate" in result["message"]

    # ---- get_tax_summary ----
    def test_get_tax_summary_no_data(self, helper):
        summary = helper.get_tax_summary(2025)
        assert summary["year"] == 2025
        assert summary["has_data"] is False

    def test_get_tax_summary_with_data(self, helper, sample_transactions):
        # Add some calculations
        helper.calculate_monthly_tax(sample_transactions, 2025, 1)
        helper.calculate_monthly_tax(sample_transactions, 2025, 2)
        helper.calculate_annual_tax(sample_transactions, 2025)
        summary = helper.get_tax_summary(2025)
        assert summary["has_data"] is True
        # Total revenue should sum monthly revenues (excluding annual)
        # Jan: 3,000,000, Feb: 2,000,000 => total 5,000,000
        assert Decimal(summary["total_revenue"]) == Decimal("5000000")
        # Total tax: Jan 15,000 + Feb 10,000 = 25,000
        assert Decimal(summary["total_tax"]) == Decimal("25000")
        assert summary["annual_summary"] is not None
        assert len(summary["monthly_details"]) == 2

    # ---- get_calculation_history ----
    def test_get_calculation_history(self, helper, sample_transactions):
        helper.calculate_monthly_tax(sample_transactions, 2025, 1)
        helper.calculate_monthly_tax(sample_transactions, 2025, 2)
        history = helper.get_calculation_history(limit=1)
        assert len(history) == 1
        assert history[0].period == "2025-02"  # latest first? Actually history is appended, so latest is last.
        # The method returns [-limit:], so limit=1 gives the last element (Feb).
        assert history[0].period == "2025-02"

        # No limit
        all_history = helper.get_calculation_history()
        assert len(all_history) == 2

    # ---- Entity Base Methods ----
    def test_validate(self, helper):
        validation = helper.validate()
        assert validation["is_valid"] is True
        assert validation["errors"] == []

        # Manipulate constants to test validation
        with patch.object(helper, "PP23_THRESHOLD", Decimal("-1")):
            validation = helper.validate()
            assert validation["is_valid"] is False
            assert "PP23_THRESHOLD must be positive" in validation["errors"]

        with patch.object(helper, "PP23_RATE", Decimal("-0.5")):
            validation = helper.validate()
            assert validation["is_valid"] is False
            assert "PP23_RATE must be between 0 and 100" in validation["errors"]

    def test_to_dict(self, helper):
        d = helper.to_dict()
        assert d["pp23_threshold"] == "4800000000"
        assert d["pp23_rate"] == "0.5"
        assert d["general_rate"] == "22"
        assert d["history_count"] == 0
        assert d["version"] == 1

    def test_from_dict(self):
        data = {"version": 5}
        helper = TaxComplianceHelper.from_dict(data)
        assert helper._version == 5
        assert helper._calculation_history == []

    def test_clone(self, helper, sample_transactions):
        helper.calculate_monthly_tax(sample_transactions, 2025, 1)
        cloned = helper.clone()
        assert cloned is not helper
        assert cloned._version == helper._version + 1
        assert len(cloned._calculation_history) == len(helper._calculation_history)
        # Ensure deep copy of results
        assert cloned._calculation_history[0] is not helper._calculation_history[0]
        assert cloned._calculation_history[0].period == helper._calculation_history[0].period

    def test_snapshot(self, helper):
        # Initially one snapshot from __init__? __init__ doesn't call _take_snapshot.
        # Actually _take_snapshot is not called in __init__, so snapshots are empty.
        # We can call it manually for test.
        helper._take_snapshot()
        snap = helper.snapshot()
        assert snap["version"] == 1
        assert snap["history_count"] == 0
        assert "timestamp" in snap

    def test_version(self, helper):
        assert helper.version() == 1
        helper.touch("admin")
        assert helper.version() == 2

    def test_audit_trail(self, helper):
        assert helper.audit_trail() == []
        helper._record_audit("TEST", "system", {"key": "value"})
        trail = helper.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "system"

    def test_touch(self, helper):
        touched = helper.touch("admin")
        assert touched is helper  # returns self
        assert helper._version == 2
        trail = helper.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "admin"

    def test_reset(self, helper, sample_transactions):
        helper.calculate_monthly_tax(sample_transactions, 2025, 1)
        helper._record_audit("TEST", "system", {})
        helper._take_snapshot()
        assert len(helper._calculation_history) == 1
        assert len(helper._audit_trail) == 2  # one from calculation, one from manual record
        assert len(helper._snapshots) == 1
        old_version = helper._version

        helper.reset()
        assert helper._calculation_history == []
        assert helper._audit_trail == []
        assert helper._snapshots == []
        assert helper._version == old_version + 1
