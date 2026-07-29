# tests/domain/project_services/test_retainer_contract_entity.py
"""
Comprehensive unit tests for Retainer Contract Entity.

Covers:
- Entity construction, validation, and serialization
- Factory method `create`
- Status transitions: activate, suspend, resume, terminate, renew
- Computed properties: is_active, is_expired, months_remaining, total_fee
- Billing calculation: calculate_monthly_billing (base, overage)
- Audit trail and utility methods
- Repository protocol (abstract methods)
- Enums: RetainerStatus, BillingPeriod
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from domain.project_services.retainer_contract_entity import (
    BillingPeriod,
    RetainerContractEntity,
    RetainerContractRepository,
    RetainerStatus,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def customer_id() -> UUID:
    return uuid4()


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def contract_kwargs(customer_id, project_id) -> dict[str, Any]:
    """Valid keyword arguments for creating a RetainerContractEntity."""
    now = datetime.now(UTC)
    return {
        "contract_id": uuid4(),
        "contract_number": "RET-2026-001",
        "customer_id": customer_id,
        "customer_name": "Acme Corp",
        "project_id": project_id,
        "project_code": "PROJ-123",
        "start_date": now,
        "end_date": now + timedelta(days=365),
        "monthly_fee": Decimal("5000.00"),
        "currency": "IDR",
        "allocated_hours": Decimal("160.00"),
        "status": RetainerStatus.DRAFT,
        "billing_period": BillingPeriod.MONTHLY,
        "description": "Initial retainer agreement",
        "auto_renew": True,
        "notice_period_days": 30,
        "created_by": "tester",
        "version": 1,
    }


@pytest.fixture
def contract(contract_kwargs) -> RetainerContractEntity:
    """A fully initialized contract in DRAFT state."""
    return RetainerContractEntity(**contract_kwargs)


@pytest.fixture
def active_contract(contract) -> RetainerContractEntity:
    """Contract in ACTIVE state."""
    return contract.activate("activator")


@pytest.fixture
def suspended_contract(active_contract) -> RetainerContractEntity:
    """Contract in SUSPENDED state."""
    return active_contract.suspend("suspender", "Client requested hold")


@pytest.fixture
def terminated_contract(active_contract) -> RetainerContractEntity:
    """Contract in TERMINATED state."""
    return active_contract.terminate("terminator", "Project completed")


# -----------------------------------------------------------------------------
# Tests for Enums
# -----------------------------------------------------------------------------

class TestRetainerStatus:
    def test_members(self):
        assert RetainerStatus.DRAFT.value == "draft"
        assert RetainerStatus.ACTIVE.value == "active"
        assert RetainerStatus.SUSPENDED.value == "suspended"
        assert RetainerStatus.TERMINATED.value == "terminated"
        assert RetainerStatus.EXPIRED.value == "expired"

    def test_from_string(self):
        assert RetainerStatus.from_string("active") == RetainerStatus.ACTIVE
        assert RetainerStatus.from_string("DRAFT") == RetainerStatus.DRAFT
        assert RetainerStatus.from_string("unknown") == RetainerStatus.DRAFT  # fallback


class TestBillingPeriod:
    def test_members(self):
        assert BillingPeriod.MONTHLY.value == "monthly"
        assert BillingPeriod.QUARTERLY.value == "quarterly"
        assert BillingPeriod.ANNUALLY.value == "annually"

    def test_from_string(self):
        assert BillingPeriod.from_string("quarterly") == BillingPeriod.QUARTERLY
        assert BillingPeriod.from_string("MONTHLY") == BillingPeriod.MONTHLY
        assert BillingPeriod.from_string("unknown") == BillingPeriod.MONTHLY  # fallback


# -----------------------------------------------------------------------------
# Tests for RetainerContractEntity
# -----------------------------------------------------------------------------

class TestRetainerContractEntity:
    """Test the retainer contract entity."""

    def test_construction_success(self, contract):
        assert contract.contract_id is not None
        assert contract.contract_number == "RET-2026-001"
        assert contract.status == RetainerStatus.DRAFT
        assert contract.version == 1
        assert contract.start_date.tzinfo is not None
        assert contract.end_date is not None
        assert contract.end_date.tzinfo is not None

    def test_validation_raises_for_short_number(self, contract_kwargs):
        contract_kwargs["contract_number"] = "AB"
        with pytest.raises(ValueError, match="Contract number must be at least 3"):
            RetainerContractEntity(**contract_kwargs)

    def test_validation_raises_for_negative_monthly_fee(self, contract_kwargs):
        contract_kwargs["monthly_fee"] = Decimal("0")
        with pytest.raises(ValueError, match="Monthly fee must be positive"):
            RetainerContractEntity(**contract_kwargs)

    def test_validation_raises_for_non_positive_allocated_hours(self, contract_kwargs):
        contract_kwargs["allocated_hours"] = Decimal("0")
        with pytest.raises(ValueError, match="Allocated hours must be positive"):
            RetainerContractEntity(**contract_kwargs)

    def test_validation_raises_for_end_date_before_start(self, contract_kwargs):
        contract_kwargs["end_date"] = contract_kwargs["start_date"] - timedelta(days=1)
        with pytest.raises(ValueError, match="End date must be after start date"):
            RetainerContractEntity(**contract_kwargs)

    def test_validation_raises_for_naive_datetime(self, contract_kwargs):
        contract_kwargs["start_date"] = datetime.now()  # naive
        with pytest.raises(ValueError, match="start_date must be timezone-aware"):
            RetainerContractEntity(**contract_kwargs)

        # end_date naive
        contract_kwargs["start_date"] = datetime.now(UTC)
        contract_kwargs["end_date"] = datetime.now()  # naive
        with pytest.raises(ValueError, match="end_date must be timezone-aware"):
            RetainerContractEntity(**contract_kwargs)

    def test_validation_raises_for_version_zero(self, contract_kwargs):
        contract_kwargs["version"] = 0
        with pytest.raises(ValueError, match="Version must be >= 1"):
            RetainerContractEntity(**contract_kwargs)

    # ---- Audit trail ----

    def test_audit_trail(self, contract):
        # Initially empty
        assert contract.get_audit_trail() == []

        # Perform some actions
        contract._record_audit("test_action", "tester", {"key": "value"})
        trail = contract.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test_action"
        assert trail[0]["user_id"] == "tester"
        assert trail[0]["details"] == {"key": "value"}
        assert trail[0]["version"] == contract.version

    # ---- Status and computed properties ----

    def test_is_active(self, contract, active_contract, suspended_contract, terminated_contract):
        # Draft is not active
        assert contract.is_active() is False

        # Active with end date in future
        assert active_contract.is_active() is True

        # Suspended is not active
        assert suspended_contract.is_active() is False

        # Terminated is not active
        assert terminated_contract.is_active() is False

        # Active but expired: we need to patch the datetime for test
        # Create a contract with end date in the past
        past_end = datetime.now(UTC) - timedelta(days=1)
        expired_active = RetainerContractEntity(
            contract_id=uuid4(),
            contract_number="EXP-001",
            customer_id=uuid4(),
            customer_name="Test",
            start_date=datetime.now(UTC) - timedelta(days=30),
            end_date=past_end,
            monthly_fee=Decimal("1000"),
            currency="IDR",
            allocated_hours=Decimal("100"),
            status=RetainerStatus.ACTIVE,
            billing_period=BillingPeriod.MONTHLY,
            created_by="tester",
        )
        assert expired_active.is_active() is False

    def test_is_expired(self, contract, active_contract, terminated_contract):
        # Contract with no end date not expired
        no_end = RetainerContractEntity(
            contract_id=uuid4(),
            contract_number="NO-END",
            customer_id=uuid4(),
            customer_name="Test",
            start_date=datetime.now(UTC),
            end_date=None,
            monthly_fee=Decimal("1000"),
            currency="IDR",
            allocated_hours=Decimal("100"),
            status=RetainerStatus.ACTIVE,
            billing_period=BillingPeriod.MONTHLY,
            created_by="tester",
        )
        assert no_end.is_expired() is False

        # Active with future end not expired
        assert active_contract.is_expired() is False

        # Past end -> expired
        past_end = datetime.now(UTC) - timedelta(days=1)
        expired_contract = RetainerContractEntity(
            contract_id=uuid4(),
            contract_number="EXP-002",
            customer_id=uuid4(),
            customer_name="Test",
            start_date=datetime.now(UTC) - timedelta(days=30),
            end_date=past_end,
            monthly_fee=Decimal("1000"),
            currency="IDR",
            allocated_hours=Decimal("100"),
            status=RetainerStatus.ACTIVE,
            billing_period=BillingPeriod.MONTHLY,
            created_by="tester",
        )
        assert expired_contract.is_expired() is True

    def test_get_months_remaining(self, contract, active_contract):
        # No end date -> 999
        no_end = RetainerContractEntity(
            contract_id=uuid4(),
            contract_number="NO-END",
            customer_id=uuid4(),
            customer_name="Test",
            start_date=datetime.now(UTC),
            end_date=None,
            monthly_fee=Decimal("1000"),
            currency="IDR",
            allocated_hours=Decimal("100"),
            status=RetainerStatus.ACTIVE,
            billing_period=BillingPeriod.MONTHLY,
            created_by="tester",
        )
        assert no_end.get_months_remaining() == 999

        # Active with future end: at least 1 if end > now
        # We can't test exact month count because of variable date, but ensure it's > 0
        assert active_contract.get_months_remaining() > 0

        # Expired -> 0
        past_end = datetime.now(UTC) - timedelta(days=1)
        expired_contract = RetainerContractEntity(
            contract_id=uuid4(),
            contract_number="EXP-003",
            customer_id=uuid4(),
            customer_name="Test",
            start_date=datetime.now(UTC) - timedelta(days=30),
            end_date=past_end,
            monthly_fee=Decimal("1000"),
            currency="IDR",
            allocated_hours=Decimal("100"),
            status=RetainerStatus.ACTIVE,
            billing_period=BillingPeriod.MONTHLY,
            created_by="tester",
        )
        assert expired_contract.get_months_remaining() == 0

    def test_get_total_fee(self, contract, active_contract):
        # No end date -> 0
        no_end = RetainerContractEntity(
            contract_id=uuid4(),
            contract_number="NO-END",
            customer_id=uuid4(),
            customer_name="Test",
            start_date=datetime.now(UTC),
            end_date=None,
            monthly_fee=Decimal("5000"),
            currency="IDR",
            allocated_hours=Decimal("100"),
            status=RetainerStatus.ACTIVE,
            billing_period=BillingPeriod.MONTHLY,
            created_by="tester",
        )
        assert no_end.get_total_fee() == Decimal(0)

        # For a 12-month contract, total = monthly_fee * 12
        # We'll test with a fixed period
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        fixed_contract = RetainerContractEntity(
            contract_id=uuid4(),
            contract_number="FIXED",
            customer_id=uuid4(),
            customer_name="Test",
            start_date=start,
            end_date=end,
            monthly_fee=Decimal("5000"),
            currency="IDR",
            allocated_hours=Decimal("100"),
            status=RetainerStatus.ACTIVE,
            billing_period=BillingPeriod.MONTHLY,
            created_by="tester",
        )
        # Months remaining from 2026-01-01 to 2026-12-31 = 12 months? Actually months_remaining returns max(0, (end.year - now.year)*12 + (end.month - now.month))
        # If now is 2026-01-01, months_remaining = (2026-2026)*12 + (12-1) = 11? Actually it returns 11, but total_fee uses months_remaining+1 => 12.
        # We'll just test that total_fee is monthly_fee * (months_remaining + 1)
        months = fixed_contract.get_months_remaining()
        expected_total = fixed_contract.monthly_fee * (months + 1)
        assert fixed_contract.get_total_fee() == expected_total

    # ---- Status transitions ----

    def test_activate(self, contract):
        activated = contract.activate("activator")
        assert activated.status == RetainerStatus.ACTIVE
        assert activated.version == contract.version + 1
        assert activated.updated_at > contract.updated_at
        assert activated.created_by == "activator"
        # Audit trail
        trail = activated.get_audit_trail()
        assert any(entry["action"] == "activated" for entry in trail)

    def test_activate_raises_if_not_draft(self, active_contract):
        with pytest.raises(ValueError, match="Cannot activate contract in status active"):
            active_contract.activate("activator")

    def test_suspend(self, active_contract):
        suspended = active_contract.suspend("suspender", "Client request")
        assert suspended.status == RetainerStatus.SUSPENDED
        assert suspended.description.endswith("Suspended: Client request")
        assert suspended.version == active_contract.version + 1
        trail = suspended.get_audit_trail()
        assert any(entry["action"] == "suspended" for entry in trail)

    def test_suspend_raises_if_not_active(self, contract):
        with pytest.raises(ValueError, match="Cannot suspend contract in status draft"):
            contract.suspend("suspender", "reason")

    def test_resume(self, suspended_contract):
        resumed = suspended_contract.resume("resumer")
        assert resumed.status == RetainerStatus.ACTIVE
        assert "Resumed:" in resumed.description
        assert resumed.version == suspended_contract.version + 1
        trail = resumed.get_audit_trail()
        assert any(entry["action"] == "resumed" for entry in trail)

    def test_resume_raises_if_not_suspended(self, active_contract):
        with pytest.raises(ValueError, match="Cannot resume contract in status active"):
            active_contract.resume("resumer")

    def test_terminate(self, active_contract):
        terminated = active_contract.terminate("terminator", "Project done")
        assert terminated.status == RetainerStatus.TERMINATED
        assert terminated.end_date is not None  # set to now if not provided
        assert "Terminated: Project done" in terminated.description
        assert terminated.version == active_contract.version + 1
        trail = terminated.get_audit_trail()
        assert any(entry["action"] == "terminated" for entry in trail)

    def test_terminate_raises_if_already_terminated(self, terminated_contract):
        with pytest.raises(ValueError, match="Cannot terminate contract in status terminated"):
            terminated_contract.terminate("tester", "again")

    def test_terminate_with_effective_date(self, active_contract):
        future_date = datetime.now(UTC) + timedelta(days=5)
        terminated = active_contract.terminate("tester", "reason", effective_date=future_date)
        assert terminated.end_date == future_date

    def test_renew(self, active_contract):
        old_end = active_contract.end_date
        renewed = active_contract.renew("renewer")
        # By default, extends by 365 days
        expected_new_end = old_end + timedelta(days=365)
        assert renewed.end_date == expected_new_end
        assert renewed.status == RetainerStatus.ACTIVE  # unchanged
        assert renewed.version == active_contract.version + 1
        trail = renewed.get_audit_trail()
        assert any(entry["action"] == "renewed" for entry in trail)

    def test_renew_with_custom_end_date(self, active_contract):
        new_end = datetime.now(UTC) + timedelta(days=100)
        renewed = active_contract.renew("renewer", new_end_date=new_end)
        assert renewed.end_date == new_end

    def test_renew_raises_if_not_active_or_suspended(self, contract):
        with pytest.raises(ValueError, match="Cannot renew contract in status draft"):
            contract.renew("renewer")

    def test_renew_on_suspended(self, suspended_contract):
        old_end = suspended_contract.end_date
        renewed = suspended_contract.renew("renewer")
        assert renewed.status == RetainerStatus.SUSPENDED  # status preserved
        assert renewed.end_date == old_end + timedelta(days=365)

    def test_renew_without_end_date(self):
        # Create contract with no end_date
        no_end = RetainerContractEntity(
            contract_id=uuid4(),
            contract_number="NO-END",
            customer_id=uuid4(),
            customer_name="Test",
            start_date=datetime.now(UTC),
            end_date=None,
            monthly_fee=Decimal("1000"),
            currency="IDR",
            allocated_hours=Decimal("100"),
            status=RetainerStatus.ACTIVE,
            billing_period=BillingPeriod.MONTHLY,
            created_by="tester",
        )
        renewed = no_end.renew("renewer")
        # Should set end_date to now + 365 days
        expected = datetime.now(UTC) + timedelta(days=365)
        # Allow small time difference
        assert abs((renewed.end_date - expected).total_seconds()) < 1

    # ---- Billing calculation ----

    def test_calculate_monthly_billing_within_allocated(self, contract):
        result = contract.calculate_monthly_billing(Decimal("100.00"))
        assert result["base_fee"] == Decimal("5000.00")
        assert result["overage_hours"] == Decimal(0)
        assert result["overage_fee"] == Decimal(0)
        assert result["total"] == Decimal("5000.00")

    def test_calculate_monthly_billing_with_overage(self, contract):
        actual = Decimal("200.00")  # 40 hours over
        result = contract.calculate_monthly_billing(actual)
        expected_overage = actual - contract.allocated_hours  # 40
        overage_rate = contract.monthly_fee / contract.allocated_hours  # 5000/160 = 31.25
        expected_overage_fee = (expected_overage * overage_rate).quantize(Decimal("0.01"))
        assert result["overage_hours"] == expected_overage
        assert result["overage_fee"] == expected_overage_fee
        assert result["total"] == contract.monthly_fee + expected_overage_fee

    # ---- Factory method ----

    def test_create_factory(self, customer_id):
        now = datetime.now(UTC)
        contract = RetainerContractEntity.create(
            contract_number="RET-2026-002",
            customer_id=customer_id,
            customer_name="Test Corp",
            start_date=now,
            monthly_fee=Decimal("7500"),
            currency="USD",
            allocated_hours=Decimal("120"),
            created_by="creator",
            end_date=now + timedelta(days=180),
            project_id=uuid4(),
            project_code="PRJ-456",
            billing_period=BillingPeriod.QUARTERLY,
        )
        assert contract.contract_id is not None
        assert contract.contract_number == "RET-2026-002"
        assert contract.status == RetainerStatus.DRAFT
        assert contract.billing_period == BillingPeriod.QUARTERLY
        assert contract.created_by == "creator"
        assert contract.version == 1

    # ---- Serialization ----

    def test_to_dict(self, contract):
        d = contract.to_dict()
        assert d["contract_id"] == str(contract.contract_id)
        assert d["contract_number"] == contract.contract_number
        assert d["status"] == contract.status.value
        assert d["monthly_fee"] == str(contract.monthly_fee)
        assert d["is_active"] == contract.is_active()
        assert d["is_expired"] == contract.is_expired()
        assert "months_remaining" in d
        assert "total_fee" in d

    def test_from_dict(self, contract):
        d = contract.to_dict()
        restored = RetainerContractEntity.from_dict(d)
        assert restored.contract_id == contract.contract_id
        assert restored.contract_number == contract.contract_number
        assert restored.status == contract.status
        assert restored.monthly_fee == contract.monthly_fee
        assert restored.created_at == contract.created_at
        assert restored.version == contract.version

    def test_from_dict_with_defaults(self, contract_kwargs):
        # Test missing optional fields
        data = {
            "contract_id": str(uuid4()),
            "contract_number": "TEST",
            "customer_id": str(uuid4()),
            "customer_name": "Test",
            "start_date": datetime.now(UTC).isoformat(),
            "monthly_fee": "1000",
            "currency": "IDR",
            "allocated_hours": "80",
            "status": "draft",
            "billing_period": "monthly",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        restored = RetainerContractEntity.from_dict(data)
        assert restored.description == ""
        assert restored.auto_renew is False
        assert restored.notice_period_days == 30
        assert restored.version == 1
        assert restored.created_by == "system"


# -----------------------------------------------------------------------------
# Tests for Repository Protocol
# -----------------------------------------------------------------------------

class TestRetainerContractRepository:
    """Test the abstract repository protocol."""

    def test_methods_raise_not_implemented(self):
        repo = RetainerContractRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("C-123", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_customer(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_active(uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_expiring_soon(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
