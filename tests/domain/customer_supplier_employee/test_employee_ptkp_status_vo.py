# test_employee_ptkp_status_vo.py
# Comprehensive tests for employee_ptkp_status_vo.py

from datetime import date
from decimal import Decimal

import pytest

from domain.customer_supplier_employee.employee_ptkp_status_vo import (
    EmployeePTKPStatusVO,
    InvalidDependentsError,
    InvalidMaritalStatusError,
    MaritalStatus,
    PTKPCategory,
    PTKPError,
    calculate_ptkp_deduction,
    get_max_dependents_for_marital,
    get_ptkp_category_from_code,
    is_valid_ptkp_code,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def single_tk0():
    """Single with 0 dependents."""
    return EmployeePTKPStatusVO.create_single(dependents=0, effective_date=date(2024, 1, 1))


@pytest.fixture
def single_tk2():
    """Single with 2 dependents."""
    return EmployeePTKPStatusVO.create_single(dependents=2, effective_date=date(2024, 1, 1))


@pytest.fixture
def married_k0():
    """Married (not combined) with 0 dependents."""
    return EmployeePTKPStatusVO.create_married(dependents=0, combined=False, effective_date=date(2024, 1, 1))


@pytest.fixture
def married_combined_kb1():
    """Married combined with 1 dependent."""
    return EmployeePTKPStatusVO.create_married(dependents=1, combined=True, effective_date=date(2024, 1, 1))


# ============================================================================
# Tests for Enums
# ============================================================================

class TestMaritalStatus:
    def test_display_name(self):
        assert MaritalStatus.SINGLE.display_name() == "Tidak Kawin"
        assert MaritalStatus.MARRIED.display_name() == "Kawin"
        assert MaritalStatus.MARRIED_COMBINED.display_name() == "Kawin (Penghasilan Digabung)"

    def test_from_string(self):
        assert MaritalStatus.from_string("TK") == MaritalStatus.SINGLE
        assert MaritalStatus.from_string("single") == MaritalStatus.SINGLE
        assert MaritalStatus.from_string("tidak kawin") == MaritalStatus.SINGLE
        assert MaritalStatus.from_string("K") == MaritalStatus.MARRIED
        assert MaritalStatus.from_string("married") == MaritalStatus.MARRIED
        assert MaritalStatus.from_string("kawin") == MaritalStatus.MARRIED
        assert MaritalStatus.from_string("KB") == MaritalStatus.MARRIED_COMBINED
        assert MaritalStatus.from_string("combined") == MaritalStatus.MARRIED_COMBINED
        assert MaritalStatus.from_string("digabung") == MaritalStatus.MARRIED_COMBINED
        assert MaritalStatus.from_string("invalid") is None


class TestPTKPCategory:
    def test_get_marital_status(self):
        assert PTKPCategory.TK0.get_marital_status() == MaritalStatus.SINGLE
        assert PTKPCategory.TK1.get_marital_status() == MaritalStatus.SINGLE
        assert PTKPCategory.K0.get_marital_status() == MaritalStatus.MARRIED
        assert PTKPCategory.KB0.get_marital_status() == MaritalStatus.MARRIED_COMBINED

    def test_get_dependents(self):
        assert PTKPCategory.TK0.get_dependents() == 0
        assert PTKPCategory.TK1.get_dependents() == 1
        assert PTKPCategory.TK2.get_dependents() == 2
        assert PTKPCategory.TK3.get_dependents() == 3
        assert PTKPCategory.K0.get_dependents() == 0
        assert PTKPCategory.KB3.get_dependents() == 3

    def test_display_name(self):
        assert PTKPCategory.TK0.display_name() == "TK/0 (Tidak Kawin, 0 tanggungan)"
        assert PTKPCategory.KB3.display_name() == "KB/3 (Kawin digabung, 3 tanggungan)"

    def test_from_marital_and_dependents_valid(self):
        assert PTKPCategory.from_marital_and_dependents(MaritalStatus.SINGLE, 0) == PTKPCategory.TK0
        assert PTKPCategory.from_marital_and_dependents(MaritalStatus.SINGLE, 2) == PTKPCategory.TK2
        assert PTKPCategory.from_marital_and_dependents(MaritalStatus.MARRIED, 0) == PTKPCategory.K0
        assert PTKPCategory.from_marital_and_dependents(MaritalStatus.MARRIED, 3) == PTKPCategory.K3
        assert PTKPCategory.from_marital_and_dependents(MaritalStatus.MARRIED_COMBINED, 1) == PTKPCategory.KB1

    def test_from_marital_and_dependents_invalid(self):
        with pytest.raises(ValueError, match="Dependents must be 0-3"):
            PTKPCategory.from_marital_and_dependents(MaritalStatus.SINGLE, -1)
        with pytest.raises(ValueError, match="Dependents must be 0-3"):
            PTKPCategory.from_marital_and_dependents(MaritalStatus.MARRIED, 4)


# ============================================================================
# Tests for Exceptions
# ============================================================================

def test_ptkp_error_is_value_error():
    assert issubclass(PTKPError, ValueError)


def test_invalid_dependents_error_is_ptkp_error():
    assert issubclass(InvalidDependentsError, PTKPError)


def test_invalid_marital_status_error_is_ptkp_error():
    assert issubclass(InvalidMaritalStatusError, PTKPError)


# ============================================================================
# Tests for EmployeePTKPStatusVO
# ============================================================================

class TestEmployeePTKPStatusVOConstruction:
    def test_valid_construction(self, single_tk0):
        assert single_tk0.marital_status == MaritalStatus.SINGLE
        assert single_tk0.dependents == 0
        assert single_tk0.spouse_income_combined is False
        assert single_tk0.effective_date == date(2024, 1, 1)
        assert single_tk0.notes == ""

    def test_invalid_dependents_negative(self):
        with pytest.raises(InvalidDependentsError, match="Dependents must be between 0 and 3"):
            EmployeePTKPStatusVO(MaritalStatus.SINGLE, dependents=-1)

    def test_invalid_dependents_too_high(self):
        with pytest.raises(InvalidDependentsError, match="Dependents must be between 0 and 3"):
            EmployeePTKPStatusVO(MaritalStatus.SINGLE, dependents=4)

    def test_invalid_marital_status_type(self):
        with pytest.raises(PTKPError, match="Invalid marital_status"):
            EmployeePTKPStatusVO("invalid", dependents=0)  # type: ignore

    def test_single_with_combined_raises(self):
        with pytest.raises(PTKPError, match="Spouse income combined cannot be true for single status"):
            EmployeePTKPStatusVO(MaritalStatus.SINGLE, spouse_income_combined=True)

    def test_combined_marital_auto_corrects_spouse_combined(self):
        # If MARRIED_COMBINED with spouse_income_combined=False, auto-correct to True
        vo = EmployeePTKPStatusVO(MaritalStatus.MARRIED_COMBINED, dependents=1, spouse_income_combined=False)
        assert vo.spouse_income_combined is True

    def test_effective_date_default(self):
        vo = EmployeePTKPStatusVO(MaritalStatus.SINGLE)
        assert vo.effective_date == date.today()

    def test_notes_stripped(self):
        vo = EmployeePTKPStatusVO(MaritalStatus.SINGLE, notes="  test  ")
        assert vo.notes == "test"


class TestEmployeePTKPStatusVOFactoryMethods:
    def test_create_single(self):
        vo = EmployeePTKPStatusVO.create_single(dependents=2, effective_date=date(2025, 1, 1))
        assert vo.marital_status == MaritalStatus.SINGLE
        assert vo.dependents == 2
        assert vo.spouse_income_combined is False
        assert vo.effective_date == date(2025, 1, 1)

    def test_create_single_default_date(self):
        vo = EmployeePTKPStatusVO.create_single(dependents=1)
        assert vo.effective_date == date.today()

    def test_create_married_combined_false(self):
        vo = EmployeePTKPStatusVO.create_married(dependents=2, combined=False)
        assert vo.marital_status == MaritalStatus.MARRIED
        assert vo.spouse_income_combined is False
        assert vo.dependents == 2

    def test_create_married_combined_true(self):
        vo = EmployeePTKPStatusVO.create_married(dependents=1, combined=True)
        assert vo.marital_status == MaritalStatus.MARRIED_COMBINED
        assert vo.spouse_income_combined is True

    def test_from_category_tk0(self):
        vo = EmployeePTKPStatusVO.from_category(PTKPCategory.TK0, effective_date=date(2024, 6, 1))
        assert vo.marital_status == MaritalStatus.SINGLE
        assert vo.dependents == 0
        assert vo.spouse_income_combined is False
        assert vo.effective_date == date(2024, 6, 1)

    def test_from_category_kb2(self):
        vo = EmployeePTKPStatusVO.from_category(PTKPCategory.KB2)
        assert vo.marital_status == MaritalStatus.MARRIED_COMBINED
        assert vo.dependents == 2
        assert vo.spouse_income_combined is True

    def test_from_dict_valid(self):
        data = {
            "marital_status": "married",
            "dependents": 2,
            "spouse_income_combined": False,
            "effective_date": "2024-02-01",
            "notes": "test",
        }
        vo = EmployeePTKPStatusVO.from_dict(data)
        assert vo.marital_status == MaritalStatus.MARRIED
        assert vo.dependents == 2
        assert vo.spouse_income_combined is False
        assert vo.effective_date == date(2024, 2, 1)
        assert vo.notes == "test"

    def test_from_dict_invalid_marital(self):
        with pytest.raises(PTKPError, match="Invalid marital_status"):
            EmployeePTKPStatusVO.from_dict({"marital_status": "invalid"})


class TestEmployeePTKPStatusVOProperties:
    def test_category(self, single_tk0, single_tk2, married_k0, married_combined_kb1):
        assert single_tk0.category == PTKPCategory.TK0
        assert single_tk2.category == PTKPCategory.TK2
        assert married_k0.category == PTKPCategory.K0
        assert married_combined_kb1.category == PTKPCategory.KB1

    def test_category_display(self, single_tk0):
        assert single_tk0.category_display == "TK/0 (Tidak Kawin, 0 tanggungan)"

    def test_status_code(self, single_tk2):
        assert single_tk2.status_code == "TK/2"

    def test_is_single(self, single_tk0, married_k0):
        assert single_tk0.is_single is True
        assert married_k0.is_single is False

    def test_is_married(self, married_k0, married_combined_kb1):
        assert married_k0.is_married is True
        assert married_combined_kb1.is_married is False

    def test_is_combined(self, married_combined_kb1, married_k0):
        assert married_combined_kb1.is_combined is True
        assert married_k0.is_combined is False

    def test_has_dependents(self, single_tk0, single_tk2):
        assert single_tk0.has_dependents is False
        assert single_tk2.has_dependents is True


class TestEmployeePTKPStatusVOCalculations:
    def test_get_ptkp_amount(self, single_tk0, single_tk2, married_k0, married_combined_kb1):
        # Based on PTKP_ANNUAL_AMOUNTS
        assert single_tk0.get_ptkp_amount() == 54_000_000
        assert single_tk2.get_ptkp_amount() == 63_000_000
        assert married_k0.get_ptkp_amount() == 58_500_000
        assert married_combined_kb1.get_ptkp_amount() == 67_500_000

    def test_get_ptkp_amount_with_tax_year(self, single_tk0):
        # For tax_year before 2024, should use 2024 rate
        assert single_tk0.get_ptkp_amount(tax_year=2023) == 54_000_000
        assert single_tk0.get_ptkp_amount(tax_year=2024) == 54_000_000
        assert single_tk0.get_ptkp_amount(tax_year=2025) == 54_000_000

    def test_get_monthly_ptkp(self, single_tk0):
        # 54,000,000 / 12 = 4,500,000
        assert single_tk0.get_monthly_ptkp() == Decimal("4500000")

    def test_get_daily_ptkp(self, single_tk0):
        # 54,000,000 / 360 = 150,000
        assert single_tk0.get_daily_ptkp() == Decimal("150000")

    def test_get_additional_for_spouse(self, married_k0, married_combined_kb1, single_tk0):
        # married_k0: is_married and not combined -> additional 4,500,000
        assert married_k0.get_additional_for_spouse() == 4_500_000
        # married_combined_kb1: is_combined -> no additional
        assert married_combined_kb1.get_additional_for_spouse() == 0
        # single -> no additional
        assert single_tk0.get_additional_for_spouse() == 0

    def test_get_total_annual_ptkp(self, married_k0, married_combined_kb1):
        # married_k0: base K0 = 58,500,000 + spouse additional 4,500,000 = 63,000,000
        assert married_k0.get_total_annual_ptkp() == 63_000_000
        # married_combined_kb1: base KB1 = 67,500,000 + 0 = 67,500,000
        assert married_combined_kb1.get_total_annual_ptkp() == 67_500_000


class TestEmployeePTKPStatusVOValidation:
    def test_is_valid_for_year(self, single_tk0):
        assert single_tk0.is_valid_for_year(2016) is True
        assert single_tk0.is_valid_for_year(2015) is False
        assert single_tk0.is_valid_for_year(2024) is True

    def test_can_upgrade_dependents(self, single_tk0):
        assert single_tk0.can_upgrade_dependents(1) is True
        assert single_tk0.can_upgrade_dependents(3) is True
        assert single_tk0.can_upgrade_dependents(0) is True  # same
        assert single_tk0.can_upgrade_dependents(4) is False
        assert single_tk0.can_upgrade_dependents(-1) is False

    def test_can_downgrade_dependents(self, single_tk2):
        assert single_tk2.can_downgrade_dependents(1) is True
        assert single_tk2.can_downgrade_dependents(0) is True
        assert single_tk2.can_downgrade_dependents(2) is True  # same
        assert single_tk2.can_downgrade_dependents(3) is False
        assert single_tk2.can_downgrade_dependents(-1) is False

    def test_requires_spouse_income_verification(self, married_k0, married_combined_kb1, single_tk0):
        assert married_k0.requires_spouse_income_verification() is True
        assert married_combined_kb1.requires_spouse_income_verification() is False
        assert single_tk0.requires_spouse_income_verification() is False


class TestEmployeePTKPStatusVOTransformations:
    def test_with_marital_status(self, single_tk0):
        # Single -> Married (not combined)
        new_vo = single_tk0.with_marital_status(MaritalStatus.MARRIED)
        assert new_vo.marital_status == MaritalStatus.MARRIED
        assert new_vo.spouse_income_combined is False  # stays False
        assert new_vo.dependents == 0
        assert "Marital changed to K" in new_vo.notes

        # Single -> Married Combined
        new_vo2 = single_tk0.with_marital_status(MaritalStatus.MARRIED_COMBINED)
        assert new_vo2.marital_status == MaritalStatus.MARRIED_COMBINED
        assert new_vo2.spouse_income_combined is True

        # Married -> Single
        married_vo = single_tk0.with_marital_status(MaritalStatus.MARRIED)
        single_again = married_vo.with_marital_status(MaritalStatus.SINGLE)
        assert single_again.marital_status == MaritalStatus.SINGLE
        assert single_again.spouse_income_combined is False

    def test_with_dependents_valid(self, single_tk0):
        new_vo = single_tk0.with_dependents(2)
        assert new_vo.dependents == 2
        assert "Dependents changed to 2" in new_vo.notes

    def test_with_dependents_invalid(self, single_tk0):
        with pytest.raises(InvalidDependentsError, match="Dependents must be 0-3"):
            single_tk0.with_dependents(4)

    def test_with_combined_single_raises(self, single_tk0):
        with pytest.raises(InvalidMaritalStatusError, match="Cannot set combined for single status"):
            single_tk0.with_combined(True)

    def test_with_combined_married(self, married_k0):
        # toggle to combined
        combined = married_k0.with_combined(True)
        assert combined.marital_status == MaritalStatus.MARRIED_COMBINED
        assert combined.spouse_income_combined is True
        assert "Spouse income combined set to True" in combined.notes

        # toggle back
        not_combined = combined.with_combined(False)
        assert not_combined.marital_status == MaritalStatus.MARRIED
        assert not_combined.spouse_income_combined is False

    def test_effective_from(self, single_tk0):
        new_date = date(2025, 1, 1)
        new_vo = single_tk0.effective_from(new_date)
        assert new_vo.effective_date == new_date
        assert new_vo.marital_status == single_tk0.marital_status
        assert new_vo.dependents == single_tk0.dependents


class TestEmployeePTKPStatusVOSerialization:
    def test_to_dict(self, single_tk2, married_k0):
        d = single_tk2.to_dict()
        assert d["marital_status"] == "TK"
        assert d["marital_status_display"] == "Tidak Kawin"
        assert d["dependents"] == 2
        assert d["spouse_income_combined"] is False
        assert d["status_code"] == "TK/2"
        assert d["category_display"] == "TK/2 (Tidak Kawin, 2 tanggungan)"
        assert d["effective_date"] == "2024-01-01"
        assert d["annual_ptkp"] == 63_000_000
        assert d["monthly_ptkp"] == "5250000"
        assert d["total_annual_ptkp"] == 63_000_000

        d2 = married_k0.to_dict()
        assert d2["total_annual_ptkp"] == 63_000_000  # base + spouse additional

    def test_to_db_record(self, single_tk2):
        rec = single_tk2.to_db_record()
        assert rec["ptkp_marital_status"] == "TK"
        assert rec["ptkp_dependents"] == 2
        assert rec["ptkp_spouse_income_combined"] is False
        assert rec["ptkp_status_code"] == "TK/2"
        assert rec["ptkp_effective_date"] == date(2024, 1, 1)
        assert rec["ptkp_notes"] == ""


class TestEmployeePTKPStatusVODunder:
    def test_str(self, single_tk2):
        assert str(single_tk2) == "TK/2"

    def test_repr(self, single_tk2):
        assert repr(single_tk2) == "EmployeePTKPStatusVO(TK/2, effective=2024-01-01)"

    def test_equality(self, single_tk0):
        same = EmployeePTKPStatusVO(MaritalStatus.SINGLE, dependents=0)
        assert single_tk0 == same
        different = EmployeePTKPStatusVO(MaritalStatus.MARRIED, dependents=0)
        assert single_tk0 != different
        assert single_tk0 != "not a vo"

    def test_hash(self, single_tk0):
        expected_hash = hash((MaritalStatus.SINGLE, 0, False))
        assert hash(single_tk0) == expected_hash


# ============================================================================
# Tests for Helper Functions
# ============================================================================

def test_calculate_ptkp_deduction(single_tk0):
    # Returns annual PTKP as Decimal
    result = calculate_ptkp_deduction(single_tk0, monthly_salary=Decimal("10000000"), tax_year=2024)
    assert result == Decimal("54000000")

def test_get_ptkp_category_from_code():
    assert get_ptkp_category_from_code("TK/0") == PTKPCategory.TK0
    assert get_ptkp_category_from_code("K/2") == PTKPCategory.K2
    assert get_ptkp_category_from_code("KB/3") == PTKPCategory.KB3
    assert get_ptkp_category_from_code("invalid") is None

def test_is_valid_ptkp_code():
    assert is_valid_ptkp_code("TK/0") is True
    assert is_valid_ptkp_code("K/2") is True
    assert is_valid_ptkp_code("KB/3") is True
    assert is_valid_ptkp_code("invalid") is False

def test_get_max_dependents_for_marital():
    # All statuses allow up to 3
    assert get_max_dependents_for_marital(MaritalStatus.SINGLE) == 3
    assert get_max_dependents_for_marital(MaritalStatus.MARRIED) == 3
    assert get_max_dependents_for_marital(MaritalStatus.MARRIED_COMBINED) == 3
