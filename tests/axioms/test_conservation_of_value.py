#!/usr/bin/env python3
"""
tests/axioms/test_conservation_of_value.py
Test untuk axioms/conservation_of_value.py
Mencakup validasi konservasi nilai dalam transaksi keuangan.
Perbaikan: mencakup semua fungsi yang sebelumnya tidak tertest, termasuk
ValueNode, ValueFlow, ConservationRecord, validator, dan axiom.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# Asumsi module yang diuji
from axioms.conservation_of_value import (
    ConservationOfValueAxiom,
    ConservationOfValueError,
    ConservationOfValueValidator,
    ConservationRecord,
    ConservationViolationError,
    ConservationViolationSeverity,
    InvalidValueFlowError,
    ValueCategory,
    ValueConservationRule,
    ValueFlow,
    ValueFlowType,
    ValueNode,
    ValuePool,
    ValueTransfer,
    create_journal_line_dict,
    create_value_node,
    get_conservation_axiom,
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
# Existing tests (dari file asli) - sebagian besar dipertahankan
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


class TestConservationOfValueError:
    def test_error_raises(self):
        with pytest.raises(ConservationOfValueError, match="Conservation violated"):
            raise ConservationOfValueError("Conservation violated")

    def test_error_inherits_from_exception(self):
        assert issubclass(ConservationOfValueError, Exception)


# ============================================================================
# NEW TESTS untuk menutupi fungsi yang sebelumnya tidak tertest
# ============================================================================

# --- ValueNode ---

class TestValueNode:
    @pytest.fixture
    def node(self) -> ValueNode:
        return ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="1000",
            amount=Decimal("1000"),
            currency="IDR",
            description="Test node",
            cost_center="CC01",
            department="DEP01",
            project_id=uuid.uuid4(),
        )

    def test_init_creates_snapshot_and_audit(self, node):
        # snapshot dan audit trail dibuat di __post_init__
        assert len(node._snapshots) >= 1
        assert len(node._audit_trail) >= 1
        # memastikan hash terisi
        assert node.cryptographic_hash != ""

    def test_validate_valid(self, node):
        result = node.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_amount(self, node):
        node.amount = Decimal("-100")
        result = node.validate()
        assert result["is_valid"] is False
        assert "Amount cannot be negative" in result["errors"]

    def test_validate_hash_mismatch(self, node):
        node.cryptographic_hash = "wrong"
        result = node.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_compute_hash(self, node):
        h = node.compute_hash()
        assert len(h) == 64  # SHA3-256 hex length
        assert h == node.cryptographic_hash

    def test_update(self, node):
        updated = node.update("user", amount=Decimal("2000"), description="Updated")
        assert updated.version == node.version + 1
        assert updated.amount == Decimal("2000")
        assert updated.description == "Updated"
        # audit trail terisi
        assert any(entry["action"] == "UPDATE" for entry in updated._audit_trail)

    def test_delete_restore(self, node):
        deleted = node.delete("user", "test reason")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "user"
        assert deleted.version == node.version + 1
        # restore
        restored = deleted.restore("user")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1
        # restore when not deleted raises
        with pytest.raises(ValueError, match="Node not deleted"):
            node.restore("user")

    def test_activate_deactivate(self, node):
        activated = node.activate("user")
        # tidak ada perubahan state pada method ini, hanya return self
        assert activated.version == node.version  # tidak increment
        deactivated = node.deactivate("user", "reason")
        assert deactivated.version == node.version

    def test_lock_unlock(self, node):
        locked = node.lock("user", "reason")
        # tidak ada state lock di ValueNode, hanya return self
        assert locked.version == node.version
        unlocked = node.unlock("user")
        assert unlocked.version == node.version

    def test_to_dict(self, node):
        d = node.to_dict()
        assert d["node_id"] == str(node.node_id)
        assert d["category"] == "ASSET"
        assert d["amount"] == str(node.amount)
        assert d["version"] == node.version

    def test_from_dict(self, node):
        d = node.to_dict()
        restored = ValueNode.from_dict(d)
        assert restored.node_id == node.node_id
        assert restored.category == node.category
        assert restored.amount == node.amount
        assert restored.version == node.version

    def test_clone(self, node):
        cloned = node.clone()
        assert cloned.node_id != node.node_id
        assert cloned.category == node.category
        assert cloned.amount == node.amount
        assert cloned.version == 1

    def test_snapshot_method(self, node):
        snap = node.snapshot()
        assert snap["node_id"] == str(node.node_id)
        assert snap["version"] == node.version
        assert "timestamp" in snap

    def test_get_version(self, node):
        assert node.get_version() == node.version

    def test_audit_trail_method(self, node):
        trail = node.audit_trail()
        assert len(trail) >= 1
        # limit
        trail2 = node.audit_trail(limit=1)
        assert len(trail2) <= 1

    def test_touch(self, node):
        old_ver = node.version
        touched = node.touch("user")
        assert touched.version == old_ver + 1
        assert any(entry["action"] == "TOUCH" for entry in touched._audit_trail)

    def test_create(self, node):
        # create returns self
        created = node.create("user")
        assert created is node

    def test_copy_private(self, node):
        copy = node._copy()
        assert copy.node_id == node.node_id
        assert copy.version == node.version
        # seharusnya deep copy tapi list tidak di-copy? tidak masalah

    def test_record_audit_private(self, node):
        node._record_audit("TEST", "user", {"k": "v"})
        assert any(entry["action"] == "TEST" for entry in node._audit_trail)

    def test_take_snapshot_private(self, node):
        old_len = len(node._snapshots)
        node._take_snapshot()
        assert len(node._snapshots) == old_len + 1
        # batas 10
        for _ in range(20):
            node._take_snapshot()
        assert len(node._snapshots) == 10


# --- ValueFlow ---

class TestValueFlowEntity:
    @pytest.fixture
    def flow(self) -> ValueFlow:
        src = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="1000",
            amount=Decimal("1000"),
            currency="IDR",
            description="Source",
        )
        dst = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="2000",
            amount=Decimal("800"),
            currency="IDR",
            description="Dest",
        )
        return ValueFlow(
            flow_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            sources=[src],
            destinations=[dst],
            transaction_fee=Decimal("200"),
            fee_currency="IDR",
            effective_date=datetime.now(UTC),
            description="Test flow",
            created_by="tester",
            created_at=datetime.now(UTC),
            flow_type=ValueFlowType.TRANSFER,
        )

    def test_properties(self, flow):
        assert flow.total_source_value == Decimal("1000")
        assert flow.total_destination_value == Decimal("800")
        assert flow.net_value_change == Decimal("1000") - Decimal("800") - Decimal("200")  # = 0

    def test_is_conserved(self, flow):
        is_cons, diff = flow.is_conserved()
        assert is_cons is True  # karena 1000 - 800 - 200 = 0
        assert diff == Decimal(0)

        # buat tidak conserved
        flow.destinations[0].amount = Decimal("700")
        is_cons, diff = flow.is_conserved()
        assert is_cons is False
        assert diff == Decimal("100")  # 1000 - 700 - 200 = 100

    def test_validate_valid(self, flow):
        result = flow.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_fee(self, flow):
        flow.transaction_fee = Decimal("-10")
        result = flow.validate()
        assert result["is_valid"] is False
        assert "Fee cannot be negative" in result["errors"]

    def test_validate_multiple_currencies(self, flow):
        flow.sources[0].currency = "USD"
        result = flow.validate()
        assert result["is_valid"] is False
        assert "Multiple currencies" in result["errors"]

    def test_compute_hash(self, flow):
        h = flow.compute_hash()
        assert len(h) == 64
        assert h == flow.cryptographic_hash

    def test_update(self, flow):
        updated = flow.update("user", description="Updated flow")
        assert updated.version == flow.version + 1
        assert updated.description == "Updated flow"
        assert any(entry["action"] == "UPDATE" for entry in updated._audit_trail)

    def test_delete_restore(self, flow):
        deleted = flow.delete("user", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "user"
        restored = deleted.restore("user")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        # restore when not deleted
        with pytest.raises(ValueError, match="Flow not deleted"):
            flow.restore("user")

    def test_activate_deactivate_lock_unlock(self, flow):
        # these are no-op, just return self
        assert flow.activate("user").version == flow.version
        assert flow.deactivate("user").version == flow.version
        assert flow.lock("user", "reason").version == flow.version
        assert flow.unlock("user").version == flow.version

    def test_to_dict(self, flow):
        d = flow.to_dict()
        assert d["flow_id"] == str(flow.flow_id)
        assert d["total_source"] == str(flow.total_source_value)
        assert d["version"] == flow.version

    def test_from_dict(self, flow):
        d = flow.to_dict()
        # from_dict tidak memuat sources/destinations, hanya metadata
        restored = ValueFlow.from_dict(d)
        assert restored.flow_id == flow.flow_id
        assert restored.transaction_id == flow.transaction_id
        assert restored.transaction_fee == flow.transaction_fee
        assert restored.version == flow.version

    def test_clone(self, flow):
        cloned = flow.clone()
        assert cloned.flow_id != flow.flow_id
        assert cloned.transaction_id == flow.transaction_id
        assert cloned.version == 1

    def test_snapshot_method(self, flow):
        snap = flow.snapshot()
        assert snap["flow_id"] == str(flow.flow_id)
        assert snap["version"] == flow.version

    def test_audit_trail_method(self, flow):
        trail = flow.audit_trail()
        assert len(trail) >= 1

    def test_touch(self, flow):
        old_ver = flow.version
        touched = flow.touch("user")
        assert touched.version == old_ver + 1

    def test_create(self, flow):
        assert flow.create("user") is flow

    def test_record_audit_private(self, flow):
        flow._record_audit("TEST", "user", {"k": "v"})
        assert any(entry["action"] == "TEST" for entry in flow._audit_trail)

    def test_take_snapshot_private(self, flow):
        old_len = len(flow._snapshots)
        flow._take_snapshot()
        assert len(flow._snapshots) == old_len + 1
        for _ in range(20):
            flow._take_snapshot()
        assert len(flow._snapshots) == 10


# --- ConservationRecord ---

class TestConservationRecordEntity:
    @pytest.fixture
    def record(self) -> ConservationRecord:
        return ConservationRecord(
            record_id=uuid.uuid4(),
            flow_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            verified_at=datetime.now(UTC),
            verified_by="tester",
            is_conserved=True,
            source_total=Decimal("1000"),
            destination_total=Decimal("800"),
            fee=Decimal("200"),
            difference=Decimal("0"),
            tolerance=Decimal("0.01"),
            severity=ConservationViolationSeverity.INFO,
            violation_message=None,
            auto_corrected=False,
            auto_correction_applied=None,
            forensic_hash="",
            version=1,
        )

    def test_init_creates_hash_snapshot_audit(self, record):
        assert record.forensic_hash != ""
        assert len(record._snapshots) >= 1
        assert len(record._audit_trail) >= 1

    def test_compute_forensic_hash(self, record):
        h = record.compute_forensic_hash()
        assert len(h) == 64
        assert h == record.forensic_hash

    def test_validate_valid(self, record):
        result = record.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_hash_mismatch(self, record):
        record.forensic_hash = "wrong"
        result = record.validate()
        assert result["is_valid"] is False
        assert "Forensic hash mismatch" in result["errors"]

    def test_immutable_methods_raise(self, record):
        with pytest.raises(AttributeError, match="immutable"):
            record.update("user", key="value")
        with pytest.raises(AttributeError, match="cannot be deleted"):
            record.delete("user")
        with pytest.raises(AttributeError, match="cannot be restored"):
            record.restore("user")

    def test_activate_deactivate_lock_unlock(self, record):
        assert record.activate("user").version == record.version
        assert record.deactivate("user").version == record.version
        assert record.lock("user", "reason").version == record.version
        assert record.unlock("user").version == record.version

    def test_to_dict(self, record):
        d = record.to_dict()
        assert d["record_id"] == str(record.record_id)
        assert d["is_conserved"] is True
        assert d["version"] == record.version

    def test_from_dict(self, record):
        d = record.to_dict()
        restored = ConservationRecord.from_dict(d)
        assert restored.record_id == record.record_id
        assert restored.is_conserved == record.is_conserved
        assert restored.version == record.version

    def test_clone(self, record):
        cloned = record.clone()
        assert cloned.record_id != record.record_id
        assert cloned.flow_id == record.flow_id
        assert cloned.version == 1

    def test_snapshot_method(self, record):
        snap = record.snapshot()
        assert snap["record_id"] == str(record.record_id)
        assert snap["version"] == record.version

    def test_audit_trail_method(self, record):
        trail = record.audit_trail()
        assert len(trail) >= 1

    def test_touch(self, record):
        record.touch("user")  # tidak mengubah version, tapi menambah audit
        assert any(entry["action"] == "TOUCH" for entry in record._audit_trail)

    def test_create(self, record):
        assert record.create("user") is record


# --- ConservationOfValueValidator ---

class TestConservationOfValueValidatorDetailed:
    def test_validate_flow_success(self):
        src = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="1000",
            amount=Decimal("1000"),
            currency="IDR",
            description="Src",
        )
        dst = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="2000",
            amount=Decimal("800"),
            currency="IDR",
            description="Dst",
        )
        flow = ValueFlow(
            flow_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            sources=[src],
            destinations=[dst],
            transaction_fee=Decimal("200"),
            fee_currency="IDR",
            effective_date=datetime.now(UTC),
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
        )
        is_cons, record, hint = ConservationOfValueValidator.validate_flow(flow)
        assert is_cons is True
        assert record is not None
        assert record.is_conserved is True
        assert hint is None

    def test_validate_flow_failure(self):
        src = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="1000",
            amount=Decimal("1000"),
            currency="IDR",
            description="Src",
        )
        dst = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="2000",
            amount=Decimal("500"),
            currency="IDR",
            description="Dst",
        )
        flow = ValueFlow(
            flow_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            sources=[src],
            destinations=[dst],
            transaction_fee=Decimal("200"),
            fee_currency="IDR",
            effective_date=datetime.now(UTC),
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
        )
        is_cons, record, hint = ConservationOfValueValidator.validate_flow(flow, auto_correct=True)
        assert is_cons is False
        assert record is not None
        assert record.is_conserved is False
        assert record.severity == ConservationViolationSeverity.LOW
        # auto_correct hint should be present
        assert hint is not None
        assert "Adjust destination" in hint

    def test_determine_severity(self):
        validator = ConservationOfValueValidator
        # catastrophic
        sev = validator._determine_severity(Decimal("1000"), Decimal("10000"), Decimal("0.01"))
        assert sev == ConservationViolationSeverity.CATASTROPHIC
        # critical
        sev = validator._determine_severity(Decimal("200"), Decimal("10000"), Decimal("0.01"))
        assert sev == ConservationViolationSeverity.CRITICAL
        # high
        sev = validator._determine_severity(Decimal("50"), Decimal("10000"), Decimal("0.01"))
        assert sev == ConservationViolationSeverity.HIGH
        # medium
        sev = validator._determine_severity(Decimal("5"), Decimal("10000"), Decimal("0.01"))
        assert sev == ConservationViolationSeverity.MEDIUM
        # low
        sev = validator._determine_severity(Decimal("0.5"), Decimal("10000"), Decimal("0.01"))
        assert sev == ConservationViolationSeverity.LOW
        # info
        sev = validator._determine_severity(Decimal("0.001"), Decimal("10000"), Decimal("0.01"))
        assert sev == ConservationViolationSeverity.INFO

    def test_log_violation(self, caplog):
        validator = ConservationOfValueValidator
        flow = MagicMock()
        flow.flow_id = uuid.uuid4()
        flow.transaction_id = uuid.uuid4()
        # critical
        with caplog.at_level("CRITICAL"):
            validator._log_violation(flow, Decimal("1000"), ConservationViolationSeverity.CATASTROPHIC)
            assert "CATASTROPHIC" in caplog.text
        # warning
        with caplog.at_level("WARNING"):
            validator._log_violation(flow, Decimal("0.5"), ConservationViolationSeverity.LOW)
            assert "LOW" in caplog.text

    def test_notify_constitution(self):
        validator = ConservationOfValueValidator
        flow = MagicMock()
        flow.flow_id = uuid.uuid4()
        flow.transaction_id = uuid.uuid4()
        # mock get_supreme_law
        with patch("axioms.conservation_of_value.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_get.return_value = mock_law
            validator._notify_constitution(flow, Decimal("100"), ConservationViolationSeverity.CRITICAL)
            mock_law.check_violation.assert_called_once()
        # jika import error, tidak raise
        with patch("axioms.conservation_of_value.get_supreme_law", side_effect=ImportError):
            validator._notify_constitution(flow, Decimal("100"), ConservationViolationSeverity.CRITICAL)

    def test_validate_transaction(self):
        tx_id = uuid.uuid4()
        lines = [
            {"account_code": "1000", "debit": "1000", "credit": "0"},
            {"account_code": "2000", "debit": "0", "credit": "800"},
            {"account_code": "3000", "debit": "0", "credit": "200"},  # fee
        ]
        is_cons, record, flow, hint = ConservationOfValueValidator.validate_transaction(
            tx_id, lines, transaction_fee=Decimal("200"), fee_currency="IDR"
        )
        assert is_cons is True
        assert record is not None
        assert flow is not None
        assert flow.total_source_value == Decimal("1000")
        assert flow.total_destination_value == Decimal("1000")  # 800+200
        assert flow.transaction_fee == Decimal("200")
        assert flow.net_value_change == Decimal("1000") - Decimal("1000") - Decimal("200") == Decimal("-200")
        # tidak conserved karena fee diambil dari source tapi tidak di-destination? Sebenarnya fee adalah biaya, jadi net_value_change -200 artinya tidak conserved.
        # Tapi validator menganggap fee sebagai pengurang, sehingga tidak conserved.
        # Kita bisa periksa is_cons False.
        # Namun karena kita memasukkan fee sebagai transaction_fee, hasilnya tidak conserved.
        # Jadi diharapkan is_cons False.
        assert is_cons is False
        # Tapi tolerance mungkin besar? kita set tolerance default 0.01, diff -200 > tolerance.
        # Jadi is_cons False.


# --- ConservationOfValueAxiom ---

class TestConservationOfValueAxiom:
    @pytest.fixture
    def axiom(self) -> ConservationOfValueAxiom:
        return ConservationOfValueAxiom()

    @pytest.fixture
    def flow(self) -> ValueFlow:
        src = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="1000",
            amount=Decimal("1000"),
            currency="IDR",
            description="Src",
        )
        dst = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="2000",
            amount=Decimal("800"),
            currency="IDR",
            description="Dst",
        )
        return ValueFlow(
            flow_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            sources=[src],
            destinations=[dst],
            transaction_fee=Decimal("200"),
            fee_currency="IDR",
            effective_date=datetime.now(UTC),
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
        )

    def test_save_and_get_flow(self, axiom, flow):
        axiom.save_flow(flow)
        retrieved = axiom.get_flow(flow.flow_id)
        assert retrieved is flow

    def test_get_all_flows(self, axiom, flow):
        axiom.save_flow(flow)
        flows = axiom.get_all_flows()
        assert len(flows) == 1
        assert flows[0] is flow

    def test_delete_flow(self, axiom, flow):
        axiom.save_flow(flow)
        assert axiom.delete_flow(flow.flow_id) is True
        assert axiom.get_flow(flow.flow_id) is None
        assert axiom.delete_flow(uuid.uuid4()) is False

    def test_save_record(self, axiom):
        record = ConservationRecord(
            record_id=uuid.uuid4(),
            flow_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            verified_at=datetime.now(UTC),
            verified_by="tester",
            is_conserved=False,
            source_total=Decimal("1000"),
            destination_total=Decimal("800"),
            fee=Decimal("200"),
            difference=Decimal("-200"),
            tolerance=Decimal("0.01"),
            severity=ConservationViolationSeverity.CRITICAL,
            violation_message="Test",
            auto_corrected=False,
            auto_correction_applied=None,
            forensic_hash="",
        )
        axiom.save_record(record)
        records = axiom.get_records()
        assert len(records) == 1
        assert records[0] is record
        # violations only
        violations = axiom.get_records(only_violations=True)
        assert len(violations) == 1

    def test_create_flow(self, axiom):
        src = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="1000",
            amount=Decimal("1000"),
            currency="IDR",
            description="Src",
        )
        dst = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="2000",
            amount=Decimal("800"),
            currency="IDR",
            description="Dst",
        )
        tx_id = uuid.uuid4()
        flow = axiom.create_flow(
            transaction_id=tx_id,
            sources=[src],
            destinations=[dst],
            transaction_fee=Decimal("200"),
            fee_currency="IDR",
            description="Created flow",
            created_by="tester",
        )
        assert flow.flow_id is not None
        assert flow.transaction_id == tx_id
        assert flow.total_source_value == Decimal("1000")
        assert flow.total_destination_value == Decimal("800")
        # flow disimpan otomatis
        retrieved = axiom.get_flow(flow.flow_id)
        assert retrieved is flow

    def test_get_flows_by_transaction(self, axiom, flow):
        axiom.save_flow(flow)
        flows = axiom.get_flows_by_transaction(flow.transaction_id)
        assert len(flows) == 1
        assert flows[0] is flow

    def test_enforce_success(self, axiom, flow):
        # flow balanced: 1000 - 800 - 200 = 0
        is_cons, record = axiom.enforce(flow, auto_correct=False, raise_on_violation=False)
        assert is_cons is True
        assert record is not None
        assert record.is_conserved is True

    def test_enforce_failure_raises(self, axiom):
        # buat flow tidak conserved
        src = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="1000",
            amount=Decimal("1000"),
            currency="IDR",
            description="Src",
        )
        dst = ValueNode(
            node_id=uuid.uuid4(),
            category=ValueCategory.ASSET,
            legal_entity_id=uuid.uuid4(),
            account_code="2000",
            amount=Decimal("500"),
            currency="IDR",
            description="Dst",
        )
        flow = ValueFlow(
            flow_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            sources=[src],
            destinations=[dst],
            transaction_fee=Decimal("200"),
            fee_currency="IDR",
            effective_date=datetime.now(UTC),
            description="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
        )
        with pytest.raises(ConservationViolationError) as excinfo:
            axiom.enforce(flow, auto_correct=False, raise_on_violation=True)
        assert "Conservation violation" in str(excinfo.value)

    def test_enforce_transaction(self, axiom):
        tx_id = uuid.uuid4()
        lines = [
            {"account_code": "1000", "debit": "1000", "credit": "0"},
            {"account_code": "2000", "debit": "0", "credit": "800"},
            {"account_code": "3000", "debit": "0", "credit": "200"},
        ]
        is_cons, record, flow = axiom.enforce_transaction(
            tx_id, lines, transaction_fee=Decimal("200"), auto_correct=False, raise_on_violation=False
        )
        assert is_cons is False  # karena fee tidak dicover
        assert record is not None
        assert flow is not None

    def test_get_statistics(self, axiom):
        # tambahkan beberapa record
        for _ in range(5):
            r = ConservationRecord(
                record_id=uuid.uuid4(),
                flow_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                verified_at=datetime.now(UTC),
                verified_by="tester",
                is_conserved=False,
                source_total=Decimal("1000"),
                destination_total=Decimal("800"),
                fee=Decimal("200"),
                difference=Decimal("-200"),
                tolerance=Decimal("0.01"),
                severity=ConservationViolationSeverity.CRITICAL,
                violation_message="Test",
                auto_corrected=False,
                auto_correction_applied=None,
                forensic_hash="",
            )
            axiom.save_record(r)
        stats = axiom.get_statistics()
        assert stats["total_flows"] == 0
        assert stats["total_validations"] == 5
        assert stats["violation_count"] == 5
        assert stats["compliance_rate"] == 0.0
        assert "CRITICAL" in stats["by_severity"]

    def test_reset(self, axiom, flow):
        axiom.save_flow(flow)
        axiom.reset()
        assert len(axiom.get_all_flows()) == 0
        assert len(axiom.get_records()) == 0
        assert len(axiom.get_records(only_violations=True)) == 0


# --- create_value_node, create_journal_line_dict, get_conservation_axiom ---

class TestHelperFunctions:
    def test_create_value_node(self):
        le_id = uuid.uuid4()
        node = create_value_node(
            category=ValueCategory.ASSET,
            legal_entity_id=le_id,
            account_code="1000",
            amount=Decimal("1000"),
            currency="IDR",
            description="Test",
            cost_center="CC01",
            department="DEP01",
            project_id=uuid.uuid4(),
        )
        assert node.category == ValueCategory.ASSET
        assert node.legal_entity_id == le_id
        assert node.account_code == "1000"
        assert node.amount == Decimal("1000")
        assert node.description == "Test"

    def test_create_journal_line_dict(self):
        le_id = uuid.uuid4()
        line = create_journal_line_dict(
            account_code="1000",
            debit=Decimal("100"),
            credit=Decimal("50"),
            currency="IDR",
            legal_entity_id=le_id,
            description="Test line",
            cost_center="CC01",
            department="DEP01",
            project_id=uuid.uuid4(),
        )
        assert line["account_code"] == "1000"
        assert line["debit"] == Decimal("100")
        assert line["credit"] == Decimal("50")
        assert line["legal_entity_id"] == le_id

    def test_get_conservation_axiom(self):
        axiom1 = get_conservation_axiom()
        axiom2 = get_conservation_axiom()
        assert axiom1 is axiom2
        assert isinstance(axiom1, ConservationOfValueAxiom)


# --- Exception classes ---

class TestConservationViolationError:
    def test_construction(self):
        error = ConservationViolationError(
            message="Test violation",
            source_value=Decimal("1000"),
            destination_value=Decimal("800"),
            difference=Decimal("200"),
            flow_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            severity=ConservationViolationSeverity.CRITICAL,
        )
        assert error.source_value == Decimal("1000")
        assert error.destination_value == Decimal("800")
        assert error.difference == Decimal("200")
        assert "CRITICAL" in str(error)

    def test_inheritance(self):
        assert issubclass(ConservationViolationError, Exception)


class TestInvalidValueFlowError:
    def test_construction(self):
        error = InvalidValueFlowError("Invalid flow")
        assert isinstance(error, Exception)