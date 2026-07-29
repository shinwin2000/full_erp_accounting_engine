# test_salary_component_entity.py
# Comprehensive tests for salary_component_entity.py

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.payroll.salary_component_entity import (
    ComponentFrequency,
    ComponentType,
    SalaryComponent,
    SalaryComponentEntity,
    SalaryComponentRepository,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_component():
    """Create a valid SalaryComponentEntity."""
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Basic Salary",
        component_type=ComponentType.BASIC,
        amount=Decimal("5000000"),
        currency="IDR",
        frequency=ComponentFrequency.MONTHLY,
        description="Monthly basic salary",
        is_taxable=True,
        is_mandatory=True,
        effective_date=now,
        expiry_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        created_at=now,
        updated_at=now,
        created_by="system",
        version=1,
    )


@pytest.fixture
def allowance_component():
    """Allowance component."""
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Transport Allowance",
        component_type=ComponentType.ALLOWANCE,
        amount=Decimal("500000"),
        currency="IDR",
        frequency=ComponentFrequency.MONTHLY,
        description="Monthly transport",
        is_taxable=True,
        is_mandatory=False,
        created_at=now,
        updated_at=now,
        created_by="system",
        version=1,
    )


@pytest.fixture
def deduction_component():
    """Deduction component (negative amount)."""
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    return SalaryComponentEntity(
        component_id=uuid4(),
        component_name="Health Insurance",
        component_type=ComponentType.DEDUCTION,
        amount=Decimal("-200000"),
        currency="IDR",
        frequency=ComponentFrequency.MONTHLY,
        description="Monthly health premium",
        is_taxable=False,
        is_mandatory=True,
        created_at=now,
        updated_at=now,
        created_by="system",
        version=1,
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestComponentType:
    def test_members(self):
        assert ComponentType.BASIC.value == "basic"
        assert ComponentType.ALLOWANCE.value == "allowance"
        assert ComponentType.DEDUCTION.value == "deduction"
        assert ComponentType.TAX.value == "tax"
        assert ComponentType.BONUS.value == "bonus"
        assert ComponentType.OVERTIME.value == "overtime"

    def test_from_string(self):
        assert ComponentType.from_string("basic") == ComponentType.BASIC
        assert ComponentType.from_string("BASIC") == ComponentType.BASIC
        assert ComponentType.from_string("allowance") == ComponentType.ALLOWANCE
        assert ComponentType.from_string("unknown") == ComponentType.ALLOWANCE  # default


class TestComponentFrequency:
    def test_members(self):
        assert ComponentFrequency.MONTHLY.value == "monthly"
        assert ComponentFrequency.ANNUAL.value == "annual"
        assert ComponentFrequency.ONE_TIME.value == "one_time"

    def test_from_string(self):
        assert ComponentFrequency.from_string("monthly") == ComponentFrequency.MONTHLY
        assert ComponentFrequency.from_string("MONTHLY") == ComponentFrequency.MONTHLY
        assert ComponentFrequency.from_string("annual") == ComponentFrequency.ANNUAL
        assert ComponentFrequency.from_string("unknown") == ComponentFrequency.MONTHLY  # default


# ============================================================================
# Tests for SalaryComponentEntity
# ============================================================================

class TestSalaryComponentEntityConstruction:
    def test_construction_valid(self, valid_component):
        assert valid_component.component_name == "Basic Salary"
        assert valid_component.amount == Decimal("5000000")
        assert valid_component.component_type == ComponentType.BASIC
        assert valid_component.currency == "IDR"
        assert valid_component.frequency == ComponentFrequency.MONTHLY
        assert valid_component.is_taxable is True
        assert valid_component.is_mandatory is True
        assert valid_component.version == 1

    def test_validation_name_too_short(self):
        with pytest.raises(ValueError, match="at least 2 characters"):
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="A",
                component_type=ComponentType.BASIC,
                amount=Decimal("1000"),
                currency="IDR",
                frequency=ComponentFrequency.MONTHLY,
            )

    def test_validation_amount_zero(self):
        with pytest.raises(ValueError, match="cannot be zero"):
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="Zero",
                component_type=ComponentType.BASIC,
                amount=Decimal("0"),
                currency="IDR",
                frequency=ComponentFrequency.MONTHLY,
            )

    def test_validation_currency_unsupported(self):
        with pytest.raises(ValueError, match="Unsupported currency"):
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="Invalid",
                component_type=ComponentType.BASIC,
                amount=Decimal("1000"),
                currency="XXX",
                frequency=ComponentFrequency.MONTHLY,
            )

    def test_validation_version(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="Version",
                component_type=ComponentType.BASIC,
                amount=Decimal("1000"),
                currency="IDR",
                frequency=ComponentFrequency.MONTHLY,
                version=0,
            )

    def test_validation_naive_created_at(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="Naive",
                component_type=ComponentType.BASIC,
                amount=Decimal("1000"),
                currency="IDR",
                frequency=ComponentFrequency.MONTHLY,
                created_at=naive,
                updated_at=datetime.now(UTC),
            )

    def test_validation_naive_effective_date(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="effective_date must be timezone-aware"):
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="Effective",
                component_type=ComponentType.BASIC,
                amount=Decimal("1000"),
                currency="IDR",
                frequency=ComponentFrequency.MONTHLY,
                effective_date=naive,
            )

    def test_validation_naive_expiry_date(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="expiry_date must be timezone-aware"):
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="Expiry",
                component_type=ComponentType.BASIC,
                amount=Decimal("1000"),
                currency="IDR",
                frequency=ComponentFrequency.MONTHLY,
                expiry_date=naive,
            )

    def test_validation_expiry_before_effective(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        effective = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        expiry = datetime(2025, 12, 31, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="expiry_date must be after effective_date"):
            SalaryComponentEntity(
                component_id=uuid4(),
                component_name="Date",
                component_type=ComponentType.BASIC,
                amount=Decimal("1000"),
                currency="IDR",
                frequency=ComponentFrequency.MONTHLY,
                effective_date=effective,
                expiry_date=expiry,
            )


class TestSalaryComponentEntityMethods:
    def test_is_positive(self, valid_component, deduction_component):
        assert valid_component.is_positive() is True
        assert deduction_component.is_positive() is False

    def test_is_negative(self, valid_component, deduction_component):
        assert valid_component.is_negative() is False
        assert deduction_component.is_negative() is True

    def test_is_active_at(self, valid_component):
        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        # Active: between effective (2025-01-01) and expiry (2026-01-01)
        assert valid_component.is_active_at(now) is True
        assert valid_component.is_active_at(datetime(2024, 12, 31, 12, 0, 0, tzinfo=UTC)) is False
        assert valid_component.is_active_at(datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)) is False

        # Component without dates should be active always
        comp_no_dates = SalaryComponentEntity(
            component_id=uuid4(),
            component_name="No Dates",
            component_type=ComponentType.BASIC,
            amount=Decimal("1000"),
            currency="IDR",
            frequency=ComponentFrequency.MONTHLY,
        )
        assert comp_no_dates.is_active_at(now) is True
        assert comp_no_dates.is_active_at(datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)) is True


class TestSalaryComponentEntityNormalize:
    def test_normalize(self, valid_component):
        # Create a component with non-normalized fields
        dirty = SalaryComponentEntity(
            component_id=valid_component.component_id,
            component_name="  basic salary  ",
            component_type=valid_component.component_type,
            amount=Decimal("5000000.123"),
            currency=" idr ",
            frequency=valid_component.frequency,
            description="  monthly basic  ",
            is_taxable=valid_component.is_taxable,
            is_mandatory=valid_component.is_mandatory,
            effective_date=valid_component.effective_date,
            expiry_date=valid_component.expiry_date,
            created_at=valid_component.created_at,
            updated_at=valid_component.updated_at,
            created_by=valid_component.created_by,
            version=valid_component.version,
        )
        normalized = dirty.normalize()
        assert normalized.component_name == "Basic Salary"
        assert normalized.amount == Decimal("5000000.12")  # quantized
        assert normalized.currency == "IDR"
        assert normalized.description == "Monthly Basic"
        assert normalized.version == dirty.version + 1
        assert normalized.updated_at > dirty.updated_at


class TestSalaryComponentEntityUpdateMethods:
    def test_update_amount(self, valid_component):
        new_amount = Decimal("6000000")
        updated = valid_component.update_amount(new_amount, "hr")
        assert updated.amount == new_amount
        assert updated.version == valid_component.version + 1
        assert updated.created_by == "hr"
        assert updated.updated_at > valid_component.updated_at

    def test_update_amount_zero(self, valid_component):
        with pytest.raises(ValueError, match="cannot be zero"):
            valid_component.update_amount(Decimal("0"), "hr")

    def test_update_description(self, valid_component):
        new_desc = "Updated basic salary description"
        updated = valid_component.update_description(new_desc, "hr")
        assert updated.description == new_desc
        assert updated.version == valid_component.version + 1
        assert updated.created_by == "hr"

    def test_update_effective_date(self, valid_component):
        new_date = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        updated = valid_component.update_effective_date(new_date, "hr")
        assert updated.effective_date == new_date
        assert updated.version == valid_component.version + 1
        assert updated.created_by == "hr"


class TestSalaryComponentEntitySerialization:
    def test_to_dict(self, valid_component):
        d = valid_component.to_dict()
        assert d["component_id"] == str(valid_component.component_id)
        assert d["component_name"] == "Basic Salary"
        assert d["component_type"] == "basic"
        assert d["amount"] == "5000000"
        assert d["currency"] == "IDR"
        assert d["frequency"] == "monthly"
        assert d["description"] == "Monthly basic salary"
        assert d["is_taxable"] is True
        assert d["is_mandatory"] is True
        assert d["effective_date"] == "2025-01-01T12:00:00+00:00"
        assert d["expiry_date"] == "2026-01-01T12:00:00+00:00"
        assert d["version"] == 1

    def test_from_dict(self, valid_component):
        data = valid_component.to_dict()
        restored = SalaryComponentEntity.from_dict(data)
        assert restored.component_id == valid_component.component_id
        assert restored.component_name == valid_component.component_name
        assert restored.amount == valid_component.amount
        assert restored.currency == valid_component.currency
        assert restored.frequency == valid_component.frequency
        assert restored.description == valid_component.description
        assert restored.is_taxable == valid_component.is_taxable
        assert restored.is_mandatory == valid_component.is_mandatory
        assert restored.effective_date == valid_component.effective_date
        assert restored.expiry_date == valid_component.expiry_date
        assert restored.version == valid_component.version

    def test_from_dict_missing_optional(self):
        data = {
            "component_id": str(uuid4()),
            "component_name": "Test",
            "component_type": "allowance",
            "amount": "1000",
            "currency": "IDR",
            "frequency": "monthly",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        restored = SalaryComponentEntity.from_dict(data)
        assert restored.description == ""
        assert restored.is_taxable is True
        assert restored.is_mandatory is False
        assert restored.effective_date is None
        assert restored.expiry_date is None


class TestSalaryComponentEntityFactory:
    def test_create(self):
        comp = SalaryComponentEntity.create(
            component_name="Bonus",
            component_type=ComponentType.BONUS,
            amount=Decimal("1000000"),
            currency="IDR",
            frequency=ComponentFrequency.ONE_TIME,
            created_by="hr",
        )
        assert comp.component_id is not None
        assert comp.component_name == "Bonus"
        assert comp.component_type == ComponentType.BONUS
        assert comp.amount == Decimal("1000000")
        assert comp.currency == "IDR"
        assert comp.frequency == ComponentFrequency.ONE_TIME
        assert comp.created_by == "hr"
        assert comp.version == 1


# ============================================================================
# Tests for SalaryComponent (simpler class)
# ============================================================================

class TestSalaryComponent:
    def test_construction(self):
        cid = uuid4()
        eid = uuid4()
        comp = SalaryComponent(
            id=cid,
            employee_id=eid,
            component_type=ComponentType.ALLOWANCE,
            amount=Decimal("100000"),
            description="Test",
        )
        assert comp.id == cid
        assert comp.employee_id == eid
        assert comp.component_type == ComponentType.ALLOWANCE
        assert comp.amount == Decimal("100000")
        assert comp.description == "Test"

    def test_to_dict(self):
        cid = uuid4()
        eid = uuid4()
        comp = SalaryComponent(
            id=cid,
            employee_id=eid,
            component_type=ComponentType.DEDUCTION,
            amount=Decimal("-50000"),
            description="Deduction",
        )
        d = comp.to_dict()
        assert d["id"] == str(cid)
        assert d["employee_id"] == str(eid)
        assert d["component_type"] == "deduction"
        assert d["amount"] == "-50000"
        assert d["description"] == "Deduction"

    def test_from_dict(self):
        cid = uuid4()
        eid = uuid4()
        data = {
            "id": str(cid),
            "employee_id": str(eid),
            "component_type": "bonus",
            "amount": "200000",
            "description": "Performance bonus",
        }
        comp = SalaryComponent.from_dict(data)
        assert comp.id == cid
        assert comp.employee_id == eid
        assert comp.component_type == ComponentType.BONUS
        assert comp.amount == Decimal("200000")
        assert comp.description == "Performance bonus"


# ============================================================================
# Tests for Repository Protocol (abstract)
# ============================================================================

class TestSalaryComponentRepository:
    def test_abstract_methods_raise(self):
        repo = SalaryComponentRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_type(ComponentType.BASIC, uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_active(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
