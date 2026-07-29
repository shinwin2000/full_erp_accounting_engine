# tests/infrastructure/persistence_orm/test_retainer_contract_table.py
# Comprehensive tests for infrastructure/persistence_orm/retainer_contract_table.py

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.retainer_contract_table import RetainerContractTable


class TestRetainerContractTable:
    """Tests for the RetainerContractTable ORM model."""

    def test_tablename_defined(self):
        assert hasattr(RetainerContractTable, "__tablename__")
        assert isinstance(RetainerContractTable.__tablename__, str)
        assert len(RetainerContractTable.__tablename__) > 0

    def test_instantiation(self):
        instance = RetainerContractTable(
            contract_number="RC-001",
            contract_name="Retainer A",
            customer_id=uuid4(),
            project_id=uuid4(),
            contract_value=Decimal("10000000"),
            remaining_amount=Decimal("10000000"),
            billed_amount=Decimal("0"),
            used_amount=Decimal("0"),
            currency="IDR",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            next_billing_date=date(2026, 1, 1),
            billing_frequency="monthly",
            billing_amount=Decimal("1000000"),
            auto_billing=True,
            status="draft",
        )
        assert isinstance(instance, RetainerContractTable)
        assert instance.contract_number == "RC-001"

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def draft_contract(self):
        return RetainerContractTable(
            contract_number="RC-001",
            contract_name="Retainer A",
            customer_id=uuid4(),
            contract_value=Decimal("12000000"),
            remaining_amount=Decimal("12000000"),
            billed_amount=Decimal("0"),
            used_amount=Decimal("0"),
            currency="IDR",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            next_billing_date=date(2026, 1, 1),
            last_billing_date=None,
            billing_frequency="monthly",
            billing_amount=Decimal("1000000"),
            auto_billing=True,
            status="draft",
            version=1,
        )

    @pytest.fixture
    def active_contract(self):
        return RetainerContractTable(
            contract_number="RC-002",
            contract_name="Retainer B",
            customer_id=uuid4(),
            contract_value=Decimal("24000000"),
            remaining_amount=Decimal("18000000"),
            billed_amount=Decimal("6000000"),
            used_amount=Decimal("0"),
            currency="IDR",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            next_billing_date=date(2026, 2, 1),
            last_billing_date=date(2026, 1, 1),
            billing_frequency="monthly",
            billing_amount=Decimal("1000000"),
            auto_billing=True,
            status="active",
            version=1,
        )

    @pytest.fixture
    def contract_with_usage(self):
        return RetainerContractTable(
            contract_number="RC-003",
            contract_name="Retainer C",
            customer_id=uuid4(),
            contract_value=Decimal("10000000"),
            remaining_amount=Decimal("7000000"),
            billed_amount=Decimal("2000000"),
            used_amount=Decimal("3000000"),
            currency="IDR",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 30),
            next_billing_date=date(2026, 3, 1),
            billing_frequency="monthly",
            billing_amount=Decimal("1000000"),
            auto_billing=True,
            status="active",
            version=1,
        )

    # -------------------- Property Tests --------------------
    def test_available_amount(self, contract_with_usage):
        # remaining 7,000,000 - used 3,000,000 = 4,000,000
        assert contract_with_usage.available_amount == Decimal("4000000")

    def test_available_amount_min_zero(self):
        contract = RetainerContractTable(
            remaining_amount=Decimal("5000000"),
            used_amount=Decimal("7000000"),
        )
        assert contract.available_amount == Decimal(0)

    def test_utilization_percentage(self, contract_with_usage):
        # used 3,000,000 / contract_value 10,000,000 * 100 = 30.0
        assert contract_with_usage.utilization_percentage == 30.0

    def test_utilization_percentage_zero_value(self):
        contract = RetainerContractTable(
            contract_value=Decimal(0),
            used_amount=Decimal(0),
        )
        assert contract.utilization_percentage == 0.0

    def test_is_active_contract(self, active_contract, draft_contract):
        assert active_contract.is_active_contract is True
        assert draft_contract.is_active_contract is False

    def test_is_expired_true(self, active_contract):
        with patch("infrastructure.persistence_orm.retainer_contract_table.date") as mock_date:
            mock_date.today.return_value = date(2027, 1, 1)
            assert active_contract.is_expired is True

    def test_is_expired_false(self, active_contract):
        with patch("infrastructure.persistence_orm.retainer_contract_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 6, 15)
            assert active_contract.is_expired is False

    def test_is_expired_no_end_date(self):
        contract = RetainerContractTable(end_date=None)
        assert contract.is_expired is False

    def test_needs_billing_true(self, active_contract):
        # active, available > 0, next_billing_date <= today
        with patch("infrastructure.persistence_orm.retainer_contract_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 2, 1)
            assert active_contract.needs_billing is True

    def test_needs_billing_false_not_active(self, draft_contract):
        assert draft_contract.needs_billing is False

    def test_needs_billing_false_no_available(self):
        contract = RetainerContractTable(
            status="active",
            remaining_amount=Decimal("1000000"),
            used_amount=Decimal("1000000"),  # available = 0
            next_billing_date=date.today(),
        )
        assert contract.needs_billing is False

    def test_needs_billing_false_no_next_billing_date(self):
        contract = RetainerContractTable(
            status="active",
            remaining_amount=Decimal("1000000"),
            used_amount=Decimal("0"),
            next_billing_date=None,
        )
        assert contract.needs_billing is False

    def test_needs_billing_false_future_date(self):
        contract = RetainerContractTable(
            status="active",
            remaining_amount=Decimal("1000000"),
            used_amount=Decimal("0"),
            next_billing_date=date(2026, 3, 1),
        )
        with patch("infrastructure.persistence_orm.retainer_contract_table.date") as mock_date:
            mock_date.today.return_value = date(2026, 2, 1)
            assert contract.needs_billing is False

    # -------------------- Method Tests --------------------
    def test_activate_from_draft(self, draft_contract):
        draft_contract.activate()
        assert draft_contract.status == "active"
        assert draft_contract.next_billing_date == draft_contract.start_date
        assert draft_contract.version == 2

    def test_activate_from_invalid_status_raises(self, active_contract):
        with pytest.raises(ValueError, match="Cannot activate contract with status active"):
            active_contract.activate()

    def test_suspend_from_active(self, active_contract):
        active_contract.suspend()
        assert active_contract.status == "suspended"
        assert active_contract.version == 2

    def test_suspend_from_invalid_status_raises(self, draft_contract):
        with pytest.raises(ValueError, match="Cannot suspend contract with status draft"):
            draft_contract.suspend()

    def test_complete_from_active(self, active_contract):
        active_contract.complete()
        assert active_contract.status == "completed"
        assert active_contract.version == 2

    def test_complete_from_suspended(self):
        contract = RetainerContractTable(status="suspended")
        contract.complete()
        assert contract.status == "completed"

    def test_complete_from_invalid_status_raises(self, draft_contract):
        with pytest.raises(ValueError, match="Cannot complete contract with status draft"):
            draft_contract.complete()

    def test_cancel_from_draft(self, draft_contract):
        draft_contract.cancel()
        assert draft_contract.status == "cancelled"

    def test_cancel_from_active(self, active_contract):
        active_contract.cancel()
        assert active_contract.status == "cancelled"

    def test_cancel_from_suspended(self):
        contract = RetainerContractTable(status="suspended")
        contract.cancel()
        assert contract.status == "cancelled"

    def test_cancel_from_invalid_status_raises(self):
        contract = RetainerContractTable(status="completed")
        with pytest.raises(ValueError, match="Cannot cancel contract with status completed"):
            contract.cancel()

    def test_record_billing_valid(self, active_contract):
        billing_date = date(2026, 2, 1)
        amount = Decimal("1000000")
        old_version = active_contract.version

        active_contract.record_billing(amount, billing_date)

        assert active_contract.billed_amount == Decimal("7000000")  # was 6,000,000
        assert active_contract.remaining_amount == Decimal("17000000")  # was 18,000,000
        assert active_contract.last_billing_date == billing_date
        # next billing date should be 30 days later (monthly)
        assert active_contract.next_billing_date == billing_date + timedelta(days=30)
        assert active_contract.version == old_version + 1

    def test_record_billing_zero_amount_raises(self, active_contract):
        with pytest.raises(ValueError, match="Billing amount must be positive"):
            active_contract.record_billing(Decimal(0), date.today())

    def test_record_billing_negative_amount_raises(self, active_contract):
        with pytest.raises(ValueError, match="Billing amount must be positive"):
            active_contract.record_billing(Decimal("-1000"), date.today())

    def test_record_billing_exceeds_available_raises(self, active_contract):
        # available = remaining - used = 18,000,000 - 0 = 18,000,000
        # try to bill 19,000,000
        with pytest.raises(ValueError, match="exceeds available retainer"):
            active_contract.record_billing(Decimal("19000000"), date.today())

    def test_record_billing_quarterly(self, active_contract):
        active_contract.billing_frequency = "quarterly"
        billing_date = date(2026, 2, 1)
        active_contract.record_billing(Decimal("1000000"), billing_date)
        assert active_contract.next_billing_date == billing_date + timedelta(days=90)

    def test_record_billing_semi_annual(self, active_contract):
        active_contract.billing_frequency = "semi_annual"
        billing_date = date(2026, 2, 1)
        active_contract.record_billing(Decimal("1000000"), billing_date)
        assert active_contract.next_billing_date == billing_date + timedelta(days=180)

    def test_record_billing_annual(self, active_contract):
        active_contract.billing_frequency = "annual"
        billing_date = date(2026, 2, 1)
        active_contract.record_billing(Decimal("1000000"), billing_date)
        assert active_contract.next_billing_date == billing_date + timedelta(days=365)

    def test_record_billing_one_time(self, active_contract):
        active_contract.billing_frequency = "one_time"
        billing_date = date(2026, 2, 1)
        active_contract.record_billing(Decimal("1000000"), billing_date)
        assert active_contract.next_billing_date is None

    def test_record_usage_valid(self, contract_with_usage):
        amount = Decimal("2000000")
        old_version = contract_with_usage.version
        contract_with_usage.record_usage(amount, "Services rendered")

        assert contract_with_usage.used_amount == Decimal("5000000")  # was 3,000,000
        assert contract_with_usage.remaining_amount == Decimal("5000000")  # was 7,000,000
        assert contract_with_usage.status == "active"  # still active because remaining > 0
        assert contract_with_usage.version == old_version + 1

    def test_record_usage_zero_amount_raises(self, contract_with_usage):
        with pytest.raises(ValueError, match="Usage amount must be positive"):
            contract_with_usage.record_usage(Decimal(0))

    def test_record_usage_exceeds_remaining_raises(self, contract_with_usage):
        # remaining = 7,000,000, try to use 8,000,000
        with pytest.raises(ValueError, match="exceeds remaining retainer"):
            contract_with_usage.record_usage(Decimal("8000000"))

    def test_record_usage_completes_contract(self, contract_with_usage):
        # remaining is 7,000,000, use exactly that
        contract_with_usage.record_usage(Decimal("7000000"))
        assert contract_with_usage.remaining_amount == Decimal(0)
        assert contract_with_usage.status == "completed"

    def test_add_funds_valid(self, active_contract):
        old_version = active_contract.version
        amount = Decimal("5000000")
        active_contract.add_funds(amount)

        assert active_contract.contract_value == Decimal("29000000")  # was 24,000,000
        assert active_contract.remaining_amount == Decimal("23000000")  # was 18,000,000
        assert active_contract.version == old_version + 1

    def test_add_funds_zero_amount_raises(self, active_contract):
        with pytest.raises(ValueError, match="Amount must be positive"):
            active_contract.add_funds(Decimal(0))

    def test_add_funds_to_draft_raises(self, draft_contract):
        with pytest.raises(ValueError, match="Cannot add funds to contract with status draft"):
            draft_contract.add_funds(Decimal("1000000"))

    def test_extend_end_date_valid(self, active_contract):
        new_end = date(2027, 12, 31)
        old_version = active_contract.version
        active_contract.extend_end_date(new_end)
        assert active_contract.end_date == new_end
        assert active_contract.version == old_version + 1

    def test_extend_end_date_from_draft_raises(self, draft_contract):
        with pytest.raises(ValueError, match="Cannot extend contract with status draft"):
            draft_contract.extend_end_date(date(2027, 1, 1))

    def test_extend_end_date_to_past_date(self, active_contract):
        # Should still work (no validation preventing past date)
        past_date = date(2020, 1, 1)
        active_contract.extend_end_date(past_date)
        assert active_contract.end_date == past_date

    def test_record_billing_and_usage_combination(self, active_contract):
        # Simulate a full cycle: bill, then use, then bill again
        # Initial: remaining 18M, used 0, billed 6M
        active_contract.record_billing(Decimal("2000000"), date(2026, 2, 1))
        # Now remaining 16M, billed 8M
        active_contract.record_usage(Decimal("5000000"), "Service")
        # Now used 5M, remaining 11M
        assert active_contract.used_amount == Decimal("5000000")
        assert active_contract.remaining_amount == Decimal("16000000") - Decimal("5000000")  # 11M
        assert active_contract.available_amount == Decimal("11000000")
