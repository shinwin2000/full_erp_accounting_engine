#!/usr/bin/env python3
"""
tests/axioms/test_conservation_of_value.py
Test untuk axioms/conservation_of_value.py
Mencakup validasi konservasi nilai dalam transaksi keuangan.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Asumsi module yang diuji
from axioms.conservation_of_value import (
    ConservationOfValueError,
    ConservationOfValueValidator,
    ValueConservationRule,
    ValueFlow,
    ValuePool,
    ValueTransfer,
    validate_conservation_of_value,
    validate_value_flow,
    validate_value_pool,
    validate_value_transfer,
)


# ============================================================================
# Helper Functions
# ============================================================================

def create_value_flow(
    source_id: uuid.UUID = None,
    destination_id: uuid.UUID = None,
    amount: Decimal = Decimal("1000"),
    fee: Decimal = Decimal("0"),
    tax: Decimal = Decimal("0"),
    source_type: str = "cash",
    destination_type: str = "cash",
) -> ValueFlow:
    return ValueFlow(
        flow_id=uuid.uuid4() if source_id is None else source_id,
        source_pool_id=source_id or uuid.uuid4(),
        destination_pool_id=destination_id or uuid.uuid4(),
        amount=amount,
        fee=fee,
        tax=tax,
        source_type=source_type,
        destination_type=destination_type,
        timestamp=None,
        metadata={},
    )


def create_value_pool(
    pool_id: uuid.UUID = None,
    balance: Decimal = Decimal("10000"),
    pool_type: str = "cash",
    currency: str = "IDR",
) -> ValuePool:
    return ValuePool(
        pool_id=pool_id or uuid.uuid4(),
        balance=balance,
        pool_type=pool_type,
        currency=currency,
        metadata={},
    )


# ============================================================================
# Tests for ValueFlow
# ============================================================================

class TestValueFlow:
    def test_create_valid_flow(self):
        flow = create_value_flow()
        assert flow.flow_id is not None
        assert flow.source_pool_id is not None
        assert flow.destination_pool_id is not None
        assert flow.amount == Decimal("1000")
        assert flow.fee == Decimal("0")
        assert flow.tax == Decimal("0")
        assert flow.source_type == "cash"
        assert flow.destination_type == "cash"

    def test_validate_positive_amount(self):
        with pytest.raises(ValueError, match="Amount must be positive"):
            create_value_flow(amount=Decimal("-100"))

    def test_validate_non_negative_fee(self):
        with pytest.raises(ValueError, match="Fee must be non-negative"):
            create_value_flow(fee=Decimal("-10"))

    def test_validate_non_negative_tax(self):
        with pytest.raises(ValueError, match="Tax must be non-negative"):
            create_value_flow(tax=Decimal("-5"))

    def test_total_value_conserved(self):
        flow = create_value_flow(amount=Decimal("1000"), fee=Decimal("50"), tax=Decimal("30"))
        assert flow.source_value == Decimal("1080")  # amount + fee + tax
        assert flow.destination_value == Decimal("1000")
        assert flow.total_value == Decimal("1000") + Decimal("50") + Decimal("30")


# ============================================================================
# Tests for ValuePool
# ============================================================================

class TestValuePool:
    def test_create_valid_pool(self):
        pool = create_value_pool()
        assert pool.pool_id is not None
        assert pool.balance == Decimal("10000")
        assert pool.pool_type == "cash"
        assert pool.currency == "IDR"

    def test_validate_non_negative_balance(self):
        with pytest.raises(ValueError, match="Balance cannot be negative"):
            create_value_pool(balance=Decimal("-500"))

    def test_apply_debit(self):
        pool = create_value_pool(balance=Decimal("10000"))
        result = pool.apply_debit(Decimal("3000"))
        assert result.balance == Decimal("7000")

    def test_apply_debit_insufficient_raises(self):
        pool = create_value_pool(balance=Decimal("10000"))
        with pytest.raises(ValueError, match="Insufficient balance"):
            pool.apply_debit(Decimal("15000"))

    def test_apply_credit(self):
        pool = create_value_pool(balance=Decimal("10000"))
        result = pool.apply_credit(Decimal("2000"))
        assert result.balance == Decimal("12000")

    def test_apply_credit_negative_raises(self):
        pool = create_value_pool(balance=Decimal("10000"))
        with pytest.raises(ValueError, match="Credit amount must be positive"):
            pool.apply_credit(Decimal("-1000"))


# ============================================================================
# Tests for ValueTransfer
# ============================================================================

class TestValueTransfer:
    def test_create_valid_transfer(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(
            source=source,
            destination=dest,
            amount=Decimal("3000"),
            fee=Decimal("100"),
            tax=Decimal("50"),
        )
        assert transfer.source is source
        assert transfer.destination is dest
        assert transfer.amount == Decimal("3000")
        assert transfer.fee == Decimal("100")
        assert transfer.tax == Decimal("50")
        assert not transfer.executed

    def test_execute_transfer(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(
            source=source,
            destination=dest,
            amount=Decimal("3000"),
            fee=Decimal("100"),
            tax=Decimal("50"),
        )
        result = transfer.execute()
        assert result.source.balance == Decimal("6850")  # 10000 - 3000 - 100 - 50
        assert result.destination.balance == Decimal("8000")  # 5000 + 3000
        assert transfer.executed

    def test_execute_already_executed_raises(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(
            source=source,
            destination=dest,
            amount=Decimal("3000"),
        )
        transfer.execute()
        with pytest.raises(ValueError, match="Transfer already executed"):
            transfer.execute()

    def test_execute_insufficient_balance_raises(self):
        source = create_value_pool(balance=Decimal("100"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(
            source=source,
            destination=dest,
            amount=Decimal("3000"),
        )
        with pytest.raises(ValueError, match="Insufficient balance"):
            transfer.execute()

    def test_validate_conservation_holds(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(
            source=source,
            destination=dest,
            amount=Decimal("3000"),
            fee=Decimal("100"),
            tax=Decimal("50"),
        )
        initial_total = source.balance + dest.balance
        transfer.execute()
        final_total = transfer.source.balance + transfer.destination.balance
        assert final_total == initial_total - Decimal("150")  # fee + tax = 150

    def test_reverse_transfer(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(
            source=source,
            destination=dest,
            amount=Decimal("3000"),
        )
        executed = transfer.execute()
        reversed_transfer = executed.reverse()
        assert reversed_transfer.source is dest
        assert reversed_transfer.destination is source
        assert reversed_transfer.amount == Decimal("3000")
        assert not reversed_transfer.executed
        reversed_transfer.execute()
        assert reversed_transfer.source.balance == Decimal("5000")
        assert reversed_transfer.destination.balance == Decimal("10000")


# ============================================================================
# Tests for ConservationOfValueValidator
# ============================================================================

class TestConservationOfValueValidator:
    def test_validate_single_transfer_valid(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(
            source=source,
            destination=dest,
            amount=Decimal("3000"),
        )
        is_valid, violations = ConservationOfValueValidator.validate(transfer)
        assert is_valid
        assert len(violations) == 0

    def test_validate_single_transfer_invalid_insufficient(self):
        source = create_value_pool(balance=Decimal("100"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(
            source=source,
            destination=dest,
            amount=Decimal("3000"),
        )
        is_valid, violations = ConservationOfValueValidator.validate(transfer)
        assert not is_valid
        assert len(violations) == 1
        assert "Insufficient balance" in violations[0]

    def test_validate_multiple_transfers_conserved(self):
        pool_a = create_value_pool(balance=Decimal("10000"), pool_type="cash")
        pool_b = create_value_pool(balance=Decimal("5000"), pool_type="receivable")
        pool_c = create_value_pool(balance=Decimal("2000"), pool_type="inventory")

        transfers = [
            ValueTransfer(pool_a, pool_b, Decimal("3000")),
            ValueTransfer(pool_b, pool_c, Decimal("2000")),
        ]
        is_valid, violations = ConservationOfValueValidator.validate_multiple(transfers)
        assert is_valid
        assert len(violations) == 0

    def test_validate_multiple_transfers_value_leak(self):
        pool_a = create_value_pool(balance=Decimal("10000"), pool_type="cash")
        pool_b = create_value_pool(balance=Decimal("5000"), pool_type="receivable")
        pool_c = create_value_pool(balance=Decimal("2000"), pool_type="inventory")

        transfers = [
            ValueTransfer(pool_a, pool_b, Decimal("3000"), fee=Decimal("500")),  # fee leak
            ValueTransfer(pool_b, pool_c, Decimal("2000")),
        ]
        is_valid, violations = ConservationOfValueValidator.validate_multiple(transfers)
        assert not is_valid
        # Should detect value mismatch (fee taken but not accounted)
        assert len(violations) >= 1
        assert "Value leak" in violations[0] or "conservation" in violations[0].lower()

    def test_check_conservation_rule_valid(self):
        rule = ValueConservationRule(
            name="Test Rule",
            description="Test conservation rule",
            is_active=True,
            tolerance=Decimal("0.01"),
        )
        assert rule.is_active
        assert rule.name == "Test Rule"

    def test_check_conservation_rule_inactive(self):
        rule = ValueConservationRule(
            name="Test Rule",
            description="Test conservation rule",
            is_active=False,
        )
        assert not rule.is_active

    def test_apply_rule_to_transfer(self):
        rule = ValueConservationRule()
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("3000"))
        result = rule.apply(transfer)
        assert result["valid"]
        assert result["violations"] == []

    def test_apply_rule_to_transfer_with_fee(self):
        rule = ValueConservationRule(tolerance=Decimal("0.01"))
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("3000"), fee=Decimal("100"))
        result = rule.apply(transfer)
        # With fee, total value changes, so should be invalid unless accounted
        assert not result["valid"]
        assert "Value leak" in result["violations"][0]

    def test_apply_rule_to_transfer_with_tax(self):
        rule = ValueConservationRule(tolerance=Decimal("0.01"))
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("3000"), tax=Decimal("50"))
        result = rule.apply(transfer)
        assert not result["valid"]
        assert "Value leak" in result["violations"][0]

    def test_apply_rule_to_transfer_with_fee_and_tax_accounted(self):
        # Create a special transfer that accounts for fee and tax in destination
        class AccountedTransfer(ValueTransfer):
            def execute(self):
                # Deduct fee and tax from source, add only amount to destination
                # This simulates fee/tax going to external accounts
                self.source.balance -= self.amount + self.fee + self.tax
                self.destination.balance += self.amount
                self.executed = True
                return self

        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = AccountedTransfer(source, dest, Decimal("3000"), fee=Decimal("100"), tax=Decimal("50"))
        # The validator should consider fee/tax as leaving the system, so conservation fails
        rule = ValueConservationRule(tolerance=Decimal("0.01"))
        result = rule.apply(transfer)
        # Since fee and tax are not accounted in destination, it should fail
        assert not result["valid"]
        # But if we allow external loss (e.g., tax/fee to government), we could adjust rule
        # For this test, we expect failure


# ============================================================================
# Tests for Module-Level Functions
# ============================================================================

class TestModuleFunctions:
    def test_validate_conservation_of_value_valid(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("3000"))
        is_valid, violations = validate_conservation_of_value(transfer)
        assert is_valid
        assert violations == []

    def test_validate_conservation_of_value_invalid(self):
        source = create_value_pool(balance=Decimal("100"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("3000"))
        is_valid, violations = validate_conservation_of_value(transfer)
        assert not is_valid
        assert len(violations) > 0

    def test_validate_value_flow_valid(self):
        flow = create_value_flow(amount=Decimal("1000"), fee=Decimal("100"), tax=Decimal("50"))
        is_valid, violations = validate_value_flow(flow)
        assert is_valid
        assert violations == []

    def test_validate_value_flow_invalid(self):
        flow = create_value_flow(amount=Decimal("1000"), fee=Decimal("-10"))  # negative fee
        is_valid, violations = validate_value_flow(flow)
        assert not is_valid
        assert len(violations) == 1

    def test_validate_value_pool_valid(self):
        pool = create_value_pool(balance=Decimal("10000"))
        is_valid, violations = validate_value_pool(pool)
        assert is_valid
        assert violations == []

    def test_validate_value_pool_invalid(self):
        pool = create_value_pool(balance=Decimal("-500"))  # negative balance
        is_valid, violations = validate_value_pool(pool)
        assert not is_valid
        assert len(violations) == 1

    def test_validate_value_transfer_valid(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("3000"))
        is_valid, violations = validate_value_transfer(transfer)
        assert is_valid
        assert violations == []

    def test_validate_value_transfer_invalid(self):
        source = create_value_pool(balance=Decimal("100"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("3000"))
        is_valid, violations = validate_value_transfer(transfer)
        assert not is_valid
        assert len(violations) == 1


# ============================================================================
# Tests for Edge Cases and Boundary Conditions
# ============================================================================

class TestEdgeCases:
    def test_zero_amount_transfer(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("0"))
        with pytest.raises(ValueError, match="Amount must be positive"):
            transfer.execute()

    def test_very_small_amount(self):
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        transfer = ValueTransfer(source, dest, Decimal("0.0001"))
        result = transfer.execute()
        assert result.source.balance == Decimal("9999.9999")
        assert result.destination.balance == Decimal("5000.0001")

    def test_large_amount(self):
        source = create_value_pool(balance=Decimal("1000000000000"))
        dest = create_value_pool(balance=Decimal("500000000000"))
        transfer = ValueTransfer(source, dest, Decimal("700000000000"))
        result = transfer.execute()
        assert result.source.balance == Decimal("300000000000")
        assert result.destination.balance == Decimal("1200000000000")

    def test_conservation_with_multiple_pools(self):
        pools = {
            "A": create_value_pool(balance=Decimal("1000")),
            "B": create_value_pool(balance=Decimal("2000")),
            "C": create_value_pool(balance=Decimal("3000")),
        }
        transfers = [
            ValueTransfer(pools["A"], pools["B"], Decimal("500")),
            ValueTransfer(pools["B"], pools["C"], Decimal("300")),
            ValueTransfer(pools["C"], pools["A"], Decimal("200")),
        ]
        total_before = sum(p.balance for p in pools.values())
        for t in transfers:
            t.execute()
        total_after = sum(p.balance for p in pools.values())
        assert total_after == total_before

    def test_conservation_with_fee_accounted_separately(self):
        # Simulate fee going to a separate fee pool
        source = create_value_pool(balance=Decimal("10000"))
        dest = create_value_pool(balance=Decimal("5000"))
        fee_pool = create_value_pool(balance=Decimal("0"), pool_type="fee")
        amount = Decimal("3000")
        fee = Decimal("150")
        transfer = ValueTransfer(source, dest, amount, fee=fee)
        transfer.source.balance -= amount + fee
        transfer.destination.balance += amount
        fee_pool.balance += fee
        # Total value conserved if fee_pool included
        total_before = source.balance + dest.balance + fee_pool.balance
        total_after = transfer.source.balance + transfer.destination.balance + fee_pool.balance
        assert total_after == total_before
        # But validator without fee_pool would see leak
        is_valid, violations = validate_conservation_of_value(transfer, include_pools=[fee_pool])
        assert is_valid
        assert violations == []


# ============================================================================
# Tests for ConservationOfValueError
# ============================================================================

class TestConservationOfValueError:
    def test_error_raises(self):
        with pytest.raises(ConservationOfValueError, match="Conservation violated"):
            raise ConservationOfValueError("Conservation violated")

    def test_error_inherits_from_exception(self):
        assert issubclass(ConservationOfValueError, Exception)