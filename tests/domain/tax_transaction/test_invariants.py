# test_invariants.py
# ==================
# Comprehensive tests for domain/tax_transaction/invariants.py.
# Covers all classes, methods, edge cases, and decimal precision.

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from domain.tax_transaction.invariants import InvariantResult, TaxInvariantEnforcer, TaxInvariants


# ----------------------------------------------------------------------
# InvariantResult
# ----------------------------------------------------------------------
class TestInvariantResult:
    def test_construction_default(self):
        result = InvariantResult()
        assert result.is_valid is True
        assert result.errors == []
        assert result._version == 1
        assert len(result._audit_trail) == 0

    def test_construction_with_errors(self):
        result = InvariantResult(False, ["error1", "error2"])
        assert result.is_valid is False
        assert result.errors == ["error1", "error2"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("test error")
        assert result.is_valid is False
        assert result.errors == ["test error"]
        assert len(result._audit_trail) == 1
        audit = result._audit_trail[0]
        assert audit["action"] == "ADD_ERROR"
        assert audit["details"]["error"] == "test error"

    def test_add_error_multiple(self):
        result = InvariantResult()
        result.add_error("error1")
        result.add_error("error2")
        assert result.errors == ["error1", "error2"]
        assert len(result._audit_trail) == 2

    def test_merge_valid(self):
        result1 = InvariantResult()
        result2 = InvariantResult()
        result1.merge(result2)
        assert result1.is_valid is True
        assert result1.errors == []

    def test_merge_with_errors(self):
        result1 = InvariantResult()
        result2 = InvariantResult(False, ["err1"])
        result1.merge(result2)
        assert result1.is_valid is False
        assert result1.errors == ["err1"]

    def test_merge_multiple_errors(self):
        result1 = InvariantResult()
        result2 = InvariantResult(False, ["err1", "err2"])
        result1.merge(result2)
        assert result1.is_valid is False
        assert result1.errors == ["err1", "err2"]

    def test_bool_true_when_valid(self):
        result = InvariantResult()
        assert bool(result) is True

    def test_bool_false_when_invalid(self):
        result = InvariantResult(False, ["error"])
        assert bool(result) is False

    def test_validate(self):
        result = InvariantResult()
        validation = result.validate()
        assert validation["is_valid"] is True
        assert validation["errors"] == []

    def test_to_dict(self):
        result = InvariantResult(False, ["err1"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["err1"]
        assert d["version"] == 1

    def test_from_dict(self):
        data = {"is_valid": False, "errors": ["a", "b"], "version": 3}
        result = InvariantResult.from_dict(data)
        assert result.is_valid is False
        assert result.errors == ["a", "b"]
        assert result._version == 3

    def test_clone(self):
        original = InvariantResult(False, ["err"])
        original._version = 5
        cloned = original.clone()
        assert cloned.is_valid is False
        assert cloned.errors == ["err"]
        assert cloned._version == 6
        assert cloned is not original

    def test_snapshot(self):
        result = InvariantResult(False, ["err1", "err2"])
        result._version = 2
        snap = result.snapshot()
        assert snap["version"] == 2
        assert snap["is_valid"] is False
        assert snap["error_count"] == 2

    def test_version(self):
        result = InvariantResult()
        assert result.version() == 1

    def test_audit_trail_limit(self):
        result = InvariantResult()
        for i in range(15):
            result._record_audit(f"ACTION_{i}", "system", {"idx": i})
        trail = result.audit_trail(limit=5)
        assert len(trail) == 5
        # Should be the latest 5
        assert trail[0]["action"] == "ACTION_14"
        assert trail[-1]["action"] == "ACTION_10"

    def test_touch(self):
        result = InvariantResult()
        old_version = result._version
        touched = result.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1
        audit = touched._audit_trail[0]
        assert audit["action"] == "TOUCH"
        assert audit["performed_by"] == "tester"
        assert touched is result  # returns self


# ----------------------------------------------------------------------
# TaxInvariants - Static Methods
# ----------------------------------------------------------------------
class TestTaxInvariants:
    # ---- validate_faktur_date ----
    def test_validate_faktur_date_valid(self):
        today = date.today()
        result = TaxInvariants.validate_faktur_date(today, today)
        assert result.is_valid is True
        assert result.errors == []

    def test_validate_faktur_date_future(self):
        today = date.today()
        future = date(today.year + 1, 1, 1)
        result = TaxInvariants.validate_faktur_date(future, today)
        assert result.is_valid is False
        assert "cannot be in the future" in result.errors[0]

    def test_validate_faktur_date_default_today(self):
        # Without current_date, uses date.today()
        # We'll just test that it doesn't raise and handles valid date
        result = TaxInvariants.validate_faktur_date(date.today())
        assert result.is_valid is True

    # ---- validate_npwp_format ----
    def test_validate_npwp_format_valid(self):
        # 15 digits (with dots and dashes stripped)
        valid_npwp = "12.345.678.9-012.345"
        result = TaxInvariants.validate_npwp_format(valid_npwp)
        assert result.is_valid is True

    def test_validate_npwp_format_valid_without_formatting(self):
        result = TaxInvariants.validate_npwp_format("123456789012345")
        assert result.is_valid is True

    def test_validate_npwp_format_too_short(self):
        result = TaxInvariants.validate_npwp_format("12345")
        assert result.is_valid is False
        assert "15 digits" in result.errors[0]

    def test_validate_npwp_format_too_long(self):
        result = TaxInvariants.validate_npwp_format("1234567890123456")
        assert result.is_valid is False
        assert "15 digits" in result.errors[0]

    def test_validate_npwp_format_non_digit(self):
        result = TaxInvariants.validate_npwp_format("12345abcde12345")
        assert result.is_valid is False
        assert "only digits" in result.errors[0]

    def test_validate_npwp_format_with_spaces_and_dots(self):
        result = TaxInvariants.validate_npwp_format("12.345.678.9-012.345")
        assert result.is_valid is True

    # ---- validate_nsfp_format ----
    def test_validate_nsfp_format_valid(self):
        result = TaxInvariants.validate_nsfp_format("1234567890123456")
        assert result.is_valid is True

    def test_validate_nsfp_format_too_short(self):
        result = TaxInvariants.validate_nsfp_format("123456789012345")
        assert result.is_valid is False
        assert "16 digits" in result.errors[0]

    def test_validate_nsfp_format_too_long(self):
        result = TaxInvariants.validate_nsfp_format("12345678901234567")
        assert result.is_valid is False
        assert "16 digits" in result.errors[0]

    def test_validate_nsfp_format_non_numeric(self):
        result = TaxInvariants.validate_nsfp_format("1234abcd12345678")
        assert result.is_valid is False
        assert "numeric" in result.errors[0]

    # ---- validate_faktur_unique_number ----
    def test_validate_faktur_unique_number_new(self):
        existing = {"FAK-001", "FAK-002"}
        result = TaxInvariants.validate_faktur_unique_number("FAK-003", existing)
        assert result.is_valid is True

    def test_validate_faktur_unique_number_duplicate(self):
        existing = {"FAK-001", "FAK-002"}
        result = TaxInvariants.validate_faktur_unique_number("FAK-001", existing)
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_faktur_unique_number_empty_set(self):
        result = TaxInvariants.validate_faktur_unique_number("FAK-001", set())
        assert result.is_valid is True

    # ---- validate_spt_period ----
    def test_validate_spt_period_valid_annual(self):
        result = TaxInvariants.validate_spt_period(2025, None)
        assert result.is_valid is True

    def test_validate_spt_period_valid_monthly(self):
        result = TaxInvariants.validate_spt_period(2025, 6)
        assert result.is_valid is True

    def test_validate_spt_period_invalid_year_too_low(self):
        result = TaxInvariants.validate_spt_period(1999, None)
        assert result.is_valid is False
        assert "Invalid tax year" in result.errors[0]

    def test_validate_spt_period_invalid_year_too_high(self):
        result = TaxInvariants.validate_spt_period(2101, None)
        assert result.is_valid is False
        assert "Invalid tax year" in result.errors[0]

    def test_validate_spt_period_invalid_month_zero(self):
        result = TaxInvariants.validate_spt_period(2025, 0)
        assert result.is_valid is False
        assert "Invalid month" in result.errors[0]

    def test_validate_spt_period_invalid_month_13(self):
        result = TaxInvariants.validate_spt_period(2025, 13)
        assert result.is_valid is False
        assert "Invalid month" in result.errors[0]

    # ---- validate_tax_amount (decimal precision) ----
    def test_validate_tax_amount_valid(self):
        dpp = Decimal("1000000")
        ppn = Decimal("110000")  # 11% of 1,000,000 = 110,000
        result = TaxInvariants.validate_tax_amount(dpp, ppn)
        assert result.is_valid is True

    def test_validate_tax_amount_valid_with_rounding(self):
        dpp = Decimal("1000000.50")
        dpp * Decimal("0.11")  # 110000.055 -> rounded in calculation
        # In code, expected_ppn is computed as dpp * (rate / 100) exactly, not rounded.
        # So expected_ppn = 110000.055, but ppn can be 110000.06, difference 0.005 <= 0.01 => valid.
        ppn = Decimal("110000.06")
        result = TaxInvariants.validate_tax_amount(dpp, ppn)
        assert result.is_valid is True

    def test_validate_tax_amount_valid_with_tolerance(self):
        dpp = Decimal("1000000")
        # 11% = 110000, tolerance 0.01
        ppn = Decimal("110000.005")
        result = TaxInvariants.validate_tax_amount(dpp, ppn)
        assert result.is_valid is True

    def test_validate_tax_amount_invalid_mismatch(self):
        dpp = Decimal("1000000")
        ppn = Decimal("120000")  # should be 110000
        result = TaxInvariants.validate_tax_amount(dpp, ppn)
        assert result.is_valid is False
        assert "PPN calculation mismatch" in result.errors[0]

    def test_validate_tax_amount_with_custom_rate(self):
        dpp = Decimal("1000000")
        ppn = Decimal("100000")  # 10% of 1,000,000 = 100,000
        result = TaxInvariants.validate_tax_amount(dpp, ppn, Decimal("10.0"))
        assert result.is_valid is True

    def test_validate_tax_amount_with_custom_rate_mismatch(self):
        dpp = Decimal("1000000")
        ppn = Decimal("110000")
        result = TaxInvariants.validate_tax_amount(dpp, ppn, Decimal("10.0"))
        assert result.is_valid is False
        assert "PPN calculation mismatch" in result.errors[0]

    def test_validate_tax_amount_zero_dpp(self):
        dpp = Decimal("0")
        ppn = Decimal("0")
        result = TaxInvariants.validate_tax_amount(dpp, ppn)
        assert result.is_valid is True

    def test_validate_tax_amount_negative_dpp(self):
        dpp = Decimal("-1000000")
        ppn = Decimal("-110000")
        result = TaxInvariants.validate_tax_amount(dpp, ppn)
        # Code calculates expected = dpp * (rate/100), so negative * positive = negative
        # ppn negative matches, so valid
        assert result.is_valid is True

    def test_validate_tax_amount_small_numbers(self):
        dpp = Decimal("0.01")
        ppn = Decimal("0.0011")
        result = TaxInvariants.validate_tax_amount(dpp, ppn)
        # 0.01 * 0.11 = 0.0011, tolerance 0.01 => valid
        assert result.is_valid is True


# ----------------------------------------------------------------------
# TaxInvariantEnforcer
# ----------------------------------------------------------------------
class TestTaxInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        return TaxInvariantEnforcer()

    @pytest.fixture
    def async_checker(self):
        async def checker():
            return {"FAK-001", "FAK-002"}
        return checker

    # ---- __init__ ----
    def test_init_default(self):
        enforcer = TaxInvariantEnforcer()
        assert enforcer._faktur_number_checker is not None
        # check that it's callable
        assert callable(enforcer._faktur_number_checker)

    def test_init_with_checker(self):
        def custom():
            return {"X"}
        enforcer = TaxInvariantEnforcer(custom)
        assert enforcer._faktur_number_checker is custom

    # ---- enforce_faktur_create ----
    @pytest.mark.asyncio
    async def test_enforce_faktur_create_valid(self):
        # Use async checker returning set
        checker = AsyncMock(return_value=set())
        enforcer = TaxInvariantEnforcer(checker)
        result = await enforcer.enforce_faktur_create(
            faktur_number="FAK-001",
            faktur_date=date.today(),
            npwp_penjual="123456789012345",
            npwp_pembeli="123456789012346",
            nsfp="1234567890123456",
            dpp=Decimal("1000000"),
            ppn=Decimal("110000"),
        )
        assert result.is_valid is True
        assert result.errors == []
        # Check audit trail
        assert len(enforcer._audit_trail) == 1
        assert enforcer._audit_trail[0]["action"] == "ENFORCE_FAKTUR_CREATE"

    @pytest.mark.asyncio
    async def test_enforce_faktur_create_invalid_date(self):
        checker = AsyncMock(return_value=set())
        enforcer = TaxInvariantEnforcer(checker)
        future = date.today().replace(year=date.today().year + 1)
        result = await enforcer.enforce_faktur_create(
            faktur_number="FAK-001",
            faktur_date=future,
            npwp_penjual="123456789012345",
            npwp_pembeli="123456789012346",
            nsfp="1234567890123456",
            dpp=Decimal("1000000"),
            ppn=Decimal("110000"),
        )
        assert result.is_valid is False
        assert "cannot be in the future" in result.errors[0]

    @pytest.mark.asyncio
    async def test_enforce_faktur_create_invalid_npwp(self):
        checker = AsyncMock(return_value=set())
        enforcer = TaxInvariantEnforcer(checker)
        result = await enforcer.enforce_faktur_create(
            faktur_number="FAK-001",
            faktur_date=date.today(),
            npwp_penjual="12345",  # invalid
            npwp_pembeli="123456789012346",
            nsfp="1234567890123456",
            dpp=Decimal("1000000"),
            ppn=Decimal("110000"),
        )
        assert result.is_valid is False
        assert any("15 digits" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_enforce_faktur_create_invalid_nsfp(self):
        checker = AsyncMock(return_value=set())
        enforcer = TaxInvariantEnforcer(checker)
        result = await enforcer.enforce_faktur_create(
            faktur_number="FAK-001",
            faktur_date=date.today(),
            npwp_penjual="123456789012345",
            npwp_pembeli="123456789012346",
            nsfp="1234",  # invalid
            dpp=Decimal("1000000"),
            ppn=Decimal("110000"),
        )
        assert result.is_valid is False
        assert any("16 digits" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_enforce_faktur_create_duplicate(self):
        checker = AsyncMock(return_value={"FAK-001"})
        enforcer = TaxInvariantEnforcer(checker)
        result = await enforcer.enforce_faktur_create(
            faktur_number="FAK-001",
            faktur_date=date.today(),
            npwp_penjual="123456789012345",
            npwp_pembeli="123456789012346",
            nsfp="1234567890123456",
            dpp=Decimal("1000000"),
            ppn=Decimal("110000"),
        )
        assert result.is_valid is False
        assert any("already exists" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_enforce_faktur_create_tax_amount_mismatch(self):
        checker = AsyncMock(return_value=set())
        enforcer = TaxInvariantEnforcer(checker)
        result = await enforcer.enforce_faktur_create(
            faktur_number="FAK-001",
            faktur_date=date.today(),
            npwp_penjual="123456789012345",
            npwp_pembeli="123456789012346",
            nsfp="1234567890123456",
            dpp=Decimal("1000000"),
            ppn=Decimal("200000"),  # wrong
        )
        assert result.is_valid is False
        assert any("PPN calculation mismatch" in e for e in result.errors)

    # ---- enforce_spt_submit ----
    @pytest.mark.asyncio
    async def test_enforce_spt_submit_valid(self):
        enforcer = TaxInvariantEnforcer()
        result = await enforcer.enforce_spt_submit(2025, 6)
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_spt_submit_invalid_year(self):
        enforcer = TaxInvariantEnforcer()
        result = await enforcer.enforce_spt_submit(1999, None)
        assert result.is_valid is False
        assert "Invalid tax year" in result.errors[0]

    @pytest.mark.asyncio
    async def test_enforce_spt_submit_invalid_month(self):
        enforcer = TaxInvariantEnforcer()
        result = await enforcer.enforce_spt_submit(2025, 13)
        assert result.is_valid is False
        assert "Invalid month" in result.errors[0]

    @pytest.mark.asyncio
    async def test_enforce_spt_submit_audit(self):
        enforcer = TaxInvariantEnforcer()
        await enforcer.enforce_spt_submit(2025, 6)
        assert len(enforcer._audit_trail) == 1
        audit = enforcer._audit_trail[0]
        assert audit["action"] == "ENFORCE_SPT_SUBMIT"
        assert audit["details"]["tahun"] == 2025
        assert audit["details"]["bulan"] == 6

    # ---- validate_faktur_date ----
    def test_validate_faktur_date(self, enforcer):
        result = enforcer.validate_faktur_date(date.today())
        assert result.is_valid is True

        future = date.today().replace(year=date.today().year + 1)
        result2 = enforcer.validate_faktur_date(future)
        assert result2.is_valid is False

    # ---- validate_npwp ----
    def test_validate_npwp_valid(self, enforcer):
        result = enforcer.validate_npwp("123456789012345")
        assert result.is_valid is True

    def test_validate_npwp_invalid(self, enforcer):
        result = enforcer.validate_npwp("12345")
        assert result.is_valid is False

    # ---- validate_nsfp ----
    def test_validate_nsfp_valid(self, enforcer):
        result = enforcer.validate_nsfp("1234567890123456")
        assert result.is_valid is True

    def test_validate_nsfp_invalid(self, enforcer):
        result = enforcer.validate_nsfp("1234")
        assert result.is_valid is False

    # ---- entity base methods ----
    def test_validate(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert d["version"] == 1
        assert d["type"] == "TaxInvariantEnforcer"

    def test_from_dict(self):
        data = {"version": 5}
        enforcer = TaxInvariantEnforcer.from_dict(data)
        assert enforcer._version == 5

    def test_clone(self, enforcer):
        enforcer._version = 3
        cloned = enforcer.clone()
        assert cloned is not enforcer
        assert cloned._version == 4
        # _faktur_number_checker should be the same function
        assert cloned._faktur_number_checker is enforcer._faktur_number_checker

    def test_snapshot(self, enforcer):
        enforcer._version = 2
        snap = enforcer.snapshot()
        assert snap["version"] == 2
        assert snap["type"] == "TaxInvariantEnforcer"

    def test_version(self, enforcer):
        assert enforcer.version() == 1

    def test_audit_trail(self, enforcer):
        enforcer._record_audit("TEST", "system", {"key": "value"})
        trail = enforcer.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "system"

    def test_audit_trail_limit(self, enforcer):
        for i in range(15):
            enforcer._record_audit(f"ACTION_{i}", "system", {"idx": i})
        trail = enforcer.audit_trail(limit=5)
        assert len(trail) == 5
        assert trail[0]["action"] == "ACTION_14"

    def test_touch(self, enforcer):
        old_version = enforcer._version
        touched = enforcer.touch("tester")
        assert touched is enforcer
        assert enforcer._version == old_version + 1
        trail = enforcer.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"

    def test_reset(self, enforcer):
        enforcer._version = 5
        enforcer._record_audit("TEST", "system", {})
        enforcer.reset()
        assert enforcer._version == 1
        assert enforcer._audit_trail == []
