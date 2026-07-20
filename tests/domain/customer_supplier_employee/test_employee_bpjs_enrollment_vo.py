# test_employee_bpjs_enrollment_vo.py
# Comprehensive tests for employee_bpjs_enrollment_vo.py

from datetime import date, timedelta
from decimal import Decimal

import pytest

from domain.customer_supplier_employee.employee_bpjs_enrollment_vo import (
    BPJSEmploymentProgram,
    BPJSError,
    BPJSHealthClass,
    BPJSType,
    EmployeeBPJSEnrollmentVO,
    InvalidBPJSMembershipNumberError,
    InvalidBPJSProgramError,
    calculate_employment_contribution,
    calculate_health_contribution,
    validate_bpjs_membership_number,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_health_enrollment():
    """Create a valid HEALTH enrollment instance."""
    return EmployeeBPJSEnrollmentVO.create_health(
        membership_number="1234567890123456",  # 16 digits
        health_class=BPJSHealthClass.CLASS_1,
        enrollment_date=date(2024, 1, 1),
        notes="Initial enrollment"
    )


@pytest.fixture
def valid_employment_enrollment():
    """Create a valid EMPLOYMENT enrollment instance."""
    return EmployeeBPJSEnrollmentVO.create_employment(
        membership_number="123456789012",  # 12 digits
        programs=[BPJSEmploymentProgram.JKK, BPJSEmploymentProgram.JHT],
        enrollment_date=date(2024, 1, 1),
        risk_level=3,
        notes="Employment enrollment"
    )


@pytest.fixture
def terminated_health_enrollment(valid_health_enrollment):
    """Return a terminated HEALTH enrollment."""
    return valid_health_enrollment.terminate(termination_date=date(2024, 6, 1), reason="Resignation")


@pytest.fixture
def terminated_employment_enrollment(valid_employment_enrollment):
    """Return a terminated EMPLOYMENT enrollment."""
    return valid_employment_enrollment.terminate(termination_date=date(2024, 6, 1), reason="Resignation")


# ============================================================================
# Tests for Enums
# ============================================================================

class TestBPJSType:
    def test_display_name(self):
        assert BPJSType.HEALTH.display_name() == "BPJS Kesehatan"
        assert BPJSType.EMPLOYMENT.display_name() == "BPJS Ketenagakerjaan"

    def test_from_string(self):
        assert BPJSType.from_string("health") == BPJSType.HEALTH
        assert BPJSType.from_string("kesehatan") == BPJSType.HEALTH
        assert BPJSType.from_string("employment") == BPJSType.EMPLOYMENT
        assert BPJSType.from_string("ketenagakerjaan") == BPJSType.EMPLOYMENT
        assert BPJSType.from_string("tenagakerja") == BPJSType.EMPLOYMENT
        assert BPJSType.from_string("unknown") is None


class TestBPJSHealthClass:
    def test_monthly_premium(self):
        assert BPJSHealthClass.CLASS_1.monthly_premium() == Decimal("150000")
        assert BPJSHealthClass.CLASS_2.monthly_premium() == Decimal("100000")
        assert BPJSHealthClass.CLASS_3.monthly_premium() == Decimal("42000")

    def test_display_name(self):
        assert BPJSHealthClass.CLASS_1.display_name() == "Kelas 1"

    def test_from_int(self):
        assert BPJSHealthClass.from_int(1) == BPJSHealthClass.CLASS_1
        assert BPJSHealthClass.from_int(2) == BPJSHealthClass.CLASS_2
        assert BPJSHealthClass.from_int(3) == BPJSHealthClass.CLASS_3
        assert BPJSHealthClass.from_int(4) is None


class TestBPJSEmploymentProgram:
    def test_display_name(self):
        assert BPJSEmploymentProgram.JKK.display_name() == "JKK (Jaminan Kecelakaan Kerja)"
        assert BPJSEmploymentProgram.JKM.display_name() == "JKM (Jaminan Kematian)"
        assert BPJSEmploymentProgram.JHT.display_name() == "JHT (Jaminan Hari Tua)"
        assert BPJSEmploymentProgram.JP.display_name() == "JP (Jaminan Pensiun)"

    def test_employee_rate(self):
        assert BPJSEmploymentProgram.JKK.employee_rate() == Decimal("0")
        assert BPJSEmploymentProgram.JKM.employee_rate() == Decimal("0")
        assert BPJSEmploymentProgram.JHT.employee_rate() == Decimal("2")
        assert BPJSEmploymentProgram.JP.employee_rate() == Decimal("1")

    def test_employer_rate(self):
        assert BPJSEmploymentProgram.JKK.employer_rate() == Decimal("0.54")
        assert BPJSEmploymentProgram.JKM.employer_rate() == Decimal("0.30")
        assert BPJSEmploymentProgram.JHT.employer_rate() == Decimal("3.7")
        assert BPJSEmploymentProgram.JP.employer_rate() == Decimal("2")

    def test_from_string(self):
        assert BPJSEmploymentProgram.from_string("jkk") == BPJSEmploymentProgram.JKK
        assert BPJSEmploymentProgram.from_string("JKK") == BPJSEmploymentProgram.JKK
        assert BPJSEmploymentProgram.from_string("jkm") == BPJSEmploymentProgram.JKM
        assert BPJSEmploymentProgram.from_string("jht") == BPJSEmploymentProgram.JHT
        assert BPJSEmploymentProgram.from_string("jp") == BPJSEmploymentProgram.JP
        assert BPJSEmploymentProgram.from_string("unknown") is None


# ============================================================================
# Tests for Exceptions
# ============================================================================

def test_bpjs_error_is_value_error():
    assert issubclass(BPJSError, ValueError)


def test_invalid_bpjs_membership_number_error_is_bpjs_error():
    assert issubclass(InvalidBPJSMembershipNumberError, BPJSError)


def test_invalid_bpjs_program_error_is_bpjs_error():
    assert issubclass(InvalidBPJSProgramError, BPJSError)


# ============================================================================
# Tests for EmployeeBPJSEnrollmentVO - Validation
# ============================================================================

def test_health_enrollment_requires_health_class():
    with pytest.raises(BPJSError, match="health_class is required for HEALTH BPJS type"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.HEALTH,
            membership_number="1234567890123456",
        )


def test_health_enrollment_membership_number_must_be_16_digits():
    with pytest.raises(InvalidBPJSMembershipNumberError, match="Health BPJS membership number must be 16 digits"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.HEALTH,
            membership_number="1234567890",  # too short
            health_class=BPJSHealthClass.CLASS_1,
        )


def test_employment_enrollment_membership_number_must_be_10_to_12_digits():
    with pytest.raises(InvalidBPJSMembershipNumberError, match="Employment BPJS membership number must be 10-12 digits"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.EMPLOYMENT,
            membership_number="123456789",  # 9 digits
            employment_programs=[BPJSEmploymentProgram.JKK],
        )


def test_health_enrollment_cannot_have_employment_programs():
    with pytest.raises(BPJSError, match="employment_programs should be None for HEALTH BPJS type"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.HEALTH,
            membership_number="1234567890123456",
            health_class=BPJSHealthClass.CLASS_1,
            employment_programs=[BPJSEmploymentProgram.JKK],
        )


def test_employment_enrollment_cannot_have_health_class():
    with pytest.raises(BPJSError, match="health_class should be None for EMPLOYMENT BPJS type"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.EMPLOYMENT,
            membership_number="123456789012",
            employment_programs=[BPJSEmploymentProgram.JKK],
            health_class=BPJSHealthClass.CLASS_1,
        )


def test_employment_enrollment_requires_programs():
    with pytest.raises(BPJSError, match="employment_programs is required for EMPLOYMENT BPJS type"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.EMPLOYMENT,
            membership_number="123456789012",
            employment_programs=[],
        )


def test_termination_date_must_be_after_enrollment_date():
    with pytest.raises(BPJSError, match="Termination date must be after enrollment date"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.HEALTH,
            membership_number="1234567890123456",
            health_class=BPJSHealthClass.CLASS_1,
            enrollment_date=date(2024, 1, 1),
            termination_date=date(2023, 12, 31),
        )


def test_termination_date_consistency_with_is_active():
    # If termination_date is set, is_active must be True (because termination date means the enrollment is active until that date)
    # The __post_init__ raises if is_active is False and termination_date is set
    with pytest.raises(BPJSError, match="Termination date set but is_active is False"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.HEALTH,
            membership_number="1234567890123456",
            health_class=BPJSHealthClass.CLASS_1,
            enrollment_date=date(2024, 1, 1),
            termination_date=date(2024, 6, 1),
            is_active=False,
        )


def test_risk_level_must_be_between_1_and_5():
    with pytest.raises(BPJSError, match="Risk level must be 1-5"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.EMPLOYMENT,
            membership_number="123456789012",
            employment_programs=[BPJSEmploymentProgram.JKK],
            risk_level=6,
        )


def test_negative_contributions_raise_error():
    with pytest.raises(BPJSError, match="Employee contribution cannot be negative"):
        EmployeeBPJSEnrollmentVO(
            bpjs_type=BPJSType.HEALTH,
            membership_number="1234567890123456",
            health_class=BPJSHealthClass.CLASS_1,
            employee_contribution=Decimal("-1"),
        )


# ============================================================================
# Tests for Factory Methods
# ============================================================================

def test_create_health_default_contributions():
    # CLASS_1: total 150k, employee 75k, employer 75k (50-50)
    enrollment = EmployeeBPJSEnrollmentVO.create_health(
        membership_number="1234567890123456",
        health_class=BPJSHealthClass.CLASS_1,
        enrollment_date=date(2024, 1, 1),
    )
    assert enrollment.bpjs_type == BPJSType.HEALTH
    assert enrollment.membership_number == "1234567890123456"
    assert enrollment.health_class == BPJSHealthClass.CLASS_1
    assert enrollment.employee_contribution == Decimal("75000")
    assert enrollment.employer_contribution == Decimal("75000")

    # CLASS_3: total 42k, employee 35k, employer 7k
    enrollment3 = EmployeeBPJSEnrollmentVO.create_health(
        membership_number="1234567890123456",
        health_class=BPJSHealthClass.CLASS_3,
    )
    assert enrollment3.employee_contribution == Decimal("35000")
    assert enrollment3.employer_contribution == Decimal("7000")  # 42000 - 35000


def test_create_health_custom_contributions():
    enrollment = EmployeeBPJSEnrollmentVO.create_health(
        membership_number="1234567890123456",
        health_class=BPJSHealthClass.CLASS_2,
        employee_contribution=Decimal("20000"),
        employer_contribution=Decimal("80000"),
    )
    assert enrollment.employee_contribution == Decimal("20000")
    assert enrollment.employer_contribution == Decimal("80000")


def test_create_employment():
    enrollment = EmployeeBPJSEnrollmentVO.create_employment(
        membership_number="123456789012",
        programs=[BPJSEmploymentProgram.JKK, BPJSEmploymentProgram.JHT],
        enrollment_date=date(2024, 1, 1),
        risk_level=2,
        notes="Test"
    )
    assert enrollment.bpjs_type == BPJSType.EMPLOYMENT
    assert enrollment.membership_number == "123456789012"
    assert enrollment.employment_programs == [BPJSEmploymentProgram.JKK, BPJSEmploymentProgram.JHT]
    assert enrollment.risk_level == 2
    assert enrollment.employee_contribution == Decimal("0")
    assert enrollment.employer_contribution == Decimal("0")


# ============================================================================
# Tests for from_dict
# ============================================================================

def test_from_dict_health():
    data = {
        "bpjs_type": "health",
        "membership_number": "1234567890123456",
        "is_active": True,
        "enrollment_date": "2024-01-01",
        "health_class": 1,
        "employee_contribution": "75000",
        "employer_contribution": "75000",
        "risk_level": 3,
        "notes": "test",
    }
    enrollment = EmployeeBPJSEnrollmentVO.from_dict(data)
    assert enrollment.bpjs_type == BPJSType.HEALTH
    assert enrollment.membership_number == "1234567890123456"
    assert enrollment.health_class == BPJSHealthClass.CLASS_1
    assert enrollment.enrollment_date == date(2024, 1, 1)


def test_from_dict_employment():
    data = {
        "bpjs_type": "employment",
        "membership_number": "123456789012",
        "is_active": True,
        "enrollment_date": "2024-01-01",
        "employment_programs": ["jkk", "jht"],
        "employee_contribution": "0",
        "employer_contribution": "0",
        "risk_level": 3,
    }
    enrollment = EmployeeBPJSEnrollmentVO.from_dict(data)
    assert enrollment.bpjs_type == BPJSType.EMPLOYMENT
    assert enrollment.employment_programs == [BPJSEmploymentProgram.JKK, BPJSEmploymentProgram.JHT]


def test_from_dict_invalid_type():
    with pytest.raises(BPJSError, match="Invalid bpjs_type"):
        EmployeeBPJSEnrollmentVO.from_dict({"bpjs_type": "invalid"})


# ============================================================================
# Tests for Properties
# ============================================================================

def test_is_terminated(valid_health_enrollment, terminated_health_enrollment):
    assert valid_health_enrollment.is_terminated is False
    assert terminated_health_enrollment.is_terminated is True


def test_masked_membership_number():
    enrollment = EmployeeBPJSEnrollmentVO.create_health(
        membership_number="1234567890123456",
        health_class=BPJSHealthClass.CLASS_1,
    )
    # 16-digit number: 12 asterisks + last 4
    assert enrollment.masked_membership_number == "************3456"

    # For short numbers (though validation prevents short numbers, we can test the fallback)
    # We'll test the property logic directly on a valid 10-digit employment number
    emp = EmployeeBPJSEnrollmentVO.create_employment(
        membership_number="1234567890",  # 10 digits
        programs=[BPJSEmploymentProgram.JKK]
    )
    # 10 digits -> 6 asterisks + 7890
    assert emp.masked_membership_number == "******7890"


def test_health_class_display(valid_health_enrollment):
    assert valid_health_enrollment.health_class_display == "Kelas 1"


def test_health_class_display_none_for_employment(valid_employment_enrollment):
    assert valid_employment_enrollment.health_class_display is None


def test_employment_programs_display(valid_employment_enrollment):
    assert valid_employment_enrollment.employment_programs_display == [
        "JKK (Jaminan Kecelakaan Kerja)",
        "JHT (Jaminan Hari Tua)",
    ]


def test_total_contribution(valid_health_enrollment):
    assert valid_health_enrollment.total_contribution == Decimal("150000")  # 75k+75k


# ============================================================================
# Tests for Calculation Methods
# ============================================================================

def test_calculate_contributions_health(valid_health_enrollment):
    # HEALTH contributions are fixed, ignore salary
    emp, er = valid_health_enrollment.calculate_contributions(Decimal("10000000"))
    assert emp == Decimal("75000")
    assert er == Decimal("75000")


def test_calculate_contributions_employment(valid_employment_enrollment):
    # Programs: JKK (risk=3 -> 0.89%), JHT (2% employee, 3.7% employer)
    salary = Decimal("10000000")
    emp, er = valid_employment_enrollment.calculate_contributions(salary)
    # JKK: 10,000,000 * 0.89% = 89,000 (employer)
    # JHT: employee 2% = 200,000, employer 3.7% = 370,000
    # Total employee = 200,000, employer = 89,000 + 370,000 = 459,000
    assert emp == Decimal("200000")
    assert er == Decimal("459000")


def test_calculate_contributions_employment_with_override_risk(valid_employment_enrollment):
    salary = Decimal("10000000")
    emp, er = valid_employment_enrollment.calculate_contributions(salary, risk_level=1)
    # JKK rate for risk 1: 0.24% => 24,000
    # JHT: emp 200,000, er 370,000
    assert er == Decimal("394000")  # 24,000 + 370,000


def test_get_monthly_contribution(valid_employment_enrollment):
    salary = Decimal("10000000")
    total = valid_employment_enrollment.get_monthly_contribution(salary)
    assert total == Decimal("659000")  # 200,000 + 459,000


# ============================================================================
# Tests for is_active_on_date
# ============================================================================

def test_is_active_on_date(valid_health_enrollment):
    # Active from 2024-01-01, no termination
    assert valid_health_enrollment.is_active_on_date(date(2024, 1, 1)) is True
    assert valid_health_enrollment.is_active_on_date(date(2024, 6, 1)) is True
    assert valid_health_enrollment.is_active_on_date(date(2023, 12, 31)) is False  # before enrollment


def test_is_active_on_date_terminated(terminated_health_enrollment):
    # Terminated on 2024-06-01
    assert terminated_health_enrollment.is_active_on_date(date(2024, 5, 31)) is True
    assert terminated_health_enrollment.is_active_on_date(date(2024, 6, 1)) is True  # still active on termination date? The check uses > termination_date, so on exact date is active.
    assert terminated_health_enrollment.is_active_on_date(date(2024, 6, 2)) is False
    assert terminated_health_enrollment.is_active_on_date(date(2023, 12, 31)) is False  # before enrollment


def test_is_active_on_date_with_inactive_flag(terminated_health_enrollment):
    # Already terminated, is_active = False
    assert terminated_health_enrollment.is_active_on_date(date(2024, 5, 31)) is False  # is_active False overrides


# ============================================================================
# Tests for terminate and reactivate
# ============================================================================

def test_terminate_active_enrollment(valid_health_enrollment):
    terminated = valid_health_enrollment.terminate(termination_date=date(2024, 6, 1), reason="Quit")
    assert terminated.is_active is False
    assert terminated.termination_date == date(2024, 6, 1)
    assert "Terminated on 2024-06-01: Quit" in terminated.notes


def test_terminate_already_terminated(terminated_health_enrollment):
    with pytest.raises(BPJSError, match="Enrollment already terminated"):
        terminated_health_enrollment.terminate()


def test_terminate_with_date_before_enrollment(valid_health_enrollment):
    with pytest.raises(BPJSError, match="Termination date cannot be before enrollment date"):
        valid_health_enrollment.terminate(termination_date=date(2023, 12, 31))


def test_reactivate_terminated_enrollment(terminated_health_enrollment):
    reactivated = terminated_health_enrollment.reactivate(reactivation_date=date(2024, 7, 1), reason="Rehired")
    assert reactivated.is_active is True
    assert reactivated.termination_date is None
    assert reactivated.enrollment_date == date(2024, 7, 1)  # new enrollment date
    assert "Reactivated on 2024-07-01: Rehired" in reactivated.notes


def test_reactivate_already_active(valid_health_enrollment):
    with pytest.raises(BPJSError, match="Enrollment is already active"):
        valid_health_enrollment.reactivate()


def test_reactivate_date_before_termination(terminated_health_enrollment):
    with pytest.raises(BPJSError, match="Reactivation date must be after termination date"):
        terminated_health_enrollment.reactivate(reactivation_date=date(2024, 5, 31))  # before termination


# ============================================================================
# Tests for update_membership_number
# ============================================================================

def test_update_membership_number(valid_health_enrollment):
    updated = valid_health_enrollment.update_membership_number("9999999999999999")
    assert updated.membership_number == "9999999999999999"
    assert "Membership changed from 1234567890123456 to 9999999999999999" in updated.notes
    # Other fields preserved
    assert updated.bpjs_type == valid_health_enrollment.bpjs_type
    assert updated.health_class == valid_health_enrollment.health_class


# ============================================================================
# Tests for Serialization
# ============================================================================

def test_to_dict(valid_health_enrollment):
    d = valid_health_enrollment.to_dict()
    assert d["bpjs_type"] == "health"
    assert d["membership_number"] == "1234567890123456"
    assert d["masked_membership_number"] == "************3456"
    assert d["is_active"] is True
    assert d["enrollment_date"] == "2024-01-01"
    assert d["health_class"] == 1
    assert d["employee_contribution"] == "75000"
    assert d["employer_contribution"] == "75000"
    assert d["total_contribution"] == "150000"


def test_to_db_record(valid_health_enrollment):
    rec = valid_health_enrollment.to_db_record()
    assert rec["bpjs_type"] == "health"
    assert rec["bpjs_membership_number"] == "1234567890123456"
    assert rec["bpjs_is_active"] is True
    assert rec["bpjs_enrollment_date"] == date(2024, 1, 1)
    assert rec["bpjs_health_class"] == 1
    assert rec["bpjs_employment_programs"] == []
    assert rec["bpjs_employee_contribution"] == Decimal("75000")
    assert rec["bpjs_employer_contribution"] == Decimal("75000")


# ============================================================================
# Tests for Dunder Methods
# ============================================================================

def test_str(valid_health_enrollment):
    assert str(valid_health_enrollment) == "BPJS Kesehatan: ************3456"


def test_repr(valid_health_enrollment):
    assert repr(valid_health_enrollment) == "EmployeeBPJSEnrollmentVO(type=health, membership=************3456, active=True)"


def test_equality(valid_health_enrollment):
    same = EmployeeBPJSEnrollmentVO.create_health(
        membership_number="1234567890123456",
        health_class=BPJSHealthClass.CLASS_1,
        enrollment_date=date(2024, 1, 1),
    )
    assert valid_health_enrollment == same
    different = EmployeeBPJSEnrollmentVO.create_health(
        membership_number="9999999999999999",
        health_class=BPJSHealthClass.CLASS_1,
        enrollment_date=date(2024, 1, 1),
    )
    assert valid_health_enrollment != different


def test_hash(valid_health_enrollment):
    assert hash(valid_health_enrollment) == hash((BPJSType.HEALTH, "1234567890123456", date(2024, 1, 1)))


# ============================================================================
# Tests for Helper Functions
# ============================================================================

def test_calculate_health_contribution():
    # Class 1
    emp, er = calculate_health_contribution(BPJSHealthClass.CLASS_1)
    assert emp == Decimal("75000")
    assert er == Decimal("75000")
    # Class 3
    emp, er = calculate_health_contribution(BPJSHealthClass.CLASS_3)
    assert emp == Decimal("35000")
    assert er == Decimal("7000")


def test_calculate_employment_contribution():
    salary = Decimal("10000000")
    programs = [BPJSEmploymentProgram.JKK, BPJSEmploymentProgram.JHT]
    emp, er = calculate_employment_contribution(salary, programs, risk_level=3)
    assert emp == Decimal("200000")
    assert er == Decimal("459000")


def test_validate_bpjs_membership_number():
    assert validate_bpjs_membership_number("1234567890123456", BPJSType.HEALTH) is True
    assert validate_bpjs_membership_number("123456789012345", BPJSType.HEALTH) is False
    assert validate_bpjs_membership_number("123456789012", BPJSType.EMPLOYMENT) is True
    assert validate_bpjs_membership_number("12345678901", BPJSType.EMPLOYMENT) is True  # 11 digits
    assert validate_bpjs_membership_number("123456789", BPJSType.EMPLOYMENT) is False