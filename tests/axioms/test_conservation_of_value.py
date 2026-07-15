#!/usr/bin/env python3
"""
tests/unit/test_conservation_of_value.py
Test untuk axioms/conservation_of_value.py
Mencakup: ValueNode, ValueFlow, ConservationRecord,
ConservationOfValueValidator, ConservationOfValueAxiom, helper functions
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from axioms.conservation_of_value import (
    ConservationOfValueAxiom,
    ConservationOfValueValidator,
    ConservationRecord,
    ConservationViolationError,
    ConservationViolationSeverity,
    InvalidValueFlowError,
    ValueCategory,
    ValueFlow,
    ValueFlowType,
    ValueNode,
    create_journal_line_dict,
    create_value_node,
    get_conservation_axiom,
)


# ============================================================================
# Helper Functions
# ============================================================================

def create_test_node(
    category: ValueCategory = ValueCategory.ASSET,
    amount: Decimal = Decimal("1000"),
    currency: str = "IDR",
    account_code: str = "1100",
) -> ValueNode:
    return ValueNode(
        node_id=uuid.uuid4(),
        category=category,
        legal_entity_id=uuid.uuid4(),
        account_code=account_code,
        amount=amount,
        currency=currency,
        description="Test node",
        cost_center="CC001",
        department="DEPT01",
        project_id=uuid.uuid4(),
    )


def create_test_flow(
    sources: list[ValueNode] | None = None,
    destinations: list[ValueNode] | None = None,
    transaction_fee: Decimal = Decimal("0"),
    fee_currency: str = "IDR",
) -> ValueFlow:
    if sources is None:
        sources = [create_test_node(amount=Decimal("500")), create_test_node(amount=Decimal("500"))]
    if destinations is None:
        destinations = [create_test_node(amount=Decimal("1000"), category=ValueCategory.LIABILITY)]
    return ValueFlow(
        flow_id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        sources=sources,
        destinations=destinations,
        transaction_fee=transaction_fee,
        fee_currency=fee_currency,
        effective_date=datetime.now(UTC),
        description="Test flow",
        created_by="tester",
        created_at=datetime.now(UTC),
        flow_type=ValueFlowType.SOURCE_TO_DESTINATION,
    )


def create_test_record(is_conserved: bool = True) -> ConservationRecord:
    return ConservationRecord(
        record_id=uuid.uuid4(),
        flow_id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        verified_at=datetime.now(UTC),
        verified_by="tester",
        is_conserved=is_conserved,
        source_total=Decimal("1000"),
        destination_total=Decimal("1000"),
        fee=Decimal("0"),
        difference=Decimal("0"),
        tolerance=Decimal("0.01"),
        severity=ConservationViolationSeverity.INFO,
        violation_message=None,
        auto_corrected=False,
        auto_correction_applied=None,
        forensic_hash="",
    )


# ============================================================================
# Tests for ValueNode
# ============================================================================

class TestValueNode:
    def test_create_valid_node(self):
        node = create_test_node()
        assert node.node_id is not None
        assert node.category == ValueCategory.ASSET
        assert node.amount == Decimal("1000")
        assert node.currency == "IDR"
        assert node.version == 1
        assert node.cryptographic_hash != ""

    def test_validate_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            ValueNode(
                node_id=uuid.uuid4(),
                category=ValueCategory.ASSET,
                legal_entity_id=uuid.uuid4(),
                account_code="1100",
                amount=Decimal("-100"),
                currency="IDR",
                description="test",
            )

    def test_validate_invalid_currency_raises(self):
        with pytest.raises(ValueError, match="Invalid currency"):
            ValueNode(
                node_id=uuid.uuid4(),
                category=ValueCategory.ASSET,
                legal_entity_id=uuid.uuid4(),
                account_code="1100",
                amount=Decimal("100"),
                currency="INVALID",
                description="test",
            )

    def test_validate_empty_account_code_raises(self):
        with pytest.raises(ValueError, match="Account code required"):
            ValueNode(
                node_id=uuid.uuid4(),
                category=ValueCategory.ASSET,
                legal_entity_id=uuid.uuid4(),
                account_code="",
                amount=Decimal("100"),
                currency="IDR",
                description="test",
            )

    def test_update_creates_new_version(self):
        node = create_test_node()
        updated = node.update("admin", amount=Decimal("2000"))
        assert updated.amount == Decimal("2000")
        assert updated.version == node.version + 1

    def test_delete_marks_deleted(self):
        node = create_test_node()
        deleted = node.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == node.version + 1

    def test_restore_recovers_deleted(self):
        node = create_test_node()
        deleted = node.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        node = create_test_node()
        with pytest.raises(ValueError, match="Node not deleted"):
            node.restore("admin")

    def test_activate_returns_self(self):
        node = create_test_node()
        activated = node.activate("admin")
        assert activated is node

    def test_deactivate_returns_self(self):
        node = create_test_node()
        deactivated = node.deactivate("admin")
        assert deactivated is node

    def test_lock_returns_self(self):
        node = create_test_node()
        locked = node.lock("admin", "test")
        assert locked is node

    def test_unlock_returns_self(self):
        node = create_test_node()
        unlocked = node.unlock("admin")
        assert unlocked is node

    def test_validate_returns_valid(self):
        node = create_test_node()
        result = node.validate()
        assert result["is_valid"] is True
        assert result["node_id"] == str(node.node_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        node = create_test_node()
        object.__setattr__(node, "cryptographic_hash", "fake")
        result = node.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        node = create_test_node()
        d = node.to_dict()
        assert d["category"] == "ASSET"
        assert d["amount"] == "1000"
        assert d["currency"] == "IDR"
        assert "node_id" in d

    def test_from_dict_reconstructs(self):
        node = create_test_node()
        d = node.to_dict()
        reconstructed = ValueNode.from_dict(d)
        assert reconstructed.node_id == node.node_id
        assert reconstructed.category == node.category
        assert reconstructed.amount == node.amount
        assert reconstructed.currency == node.currency

    def test_clone_creates_new_id(self):
        node = create_test_node()
        cloned = node.clone()
        assert cloned.node_id != node.node_id
        assert cloned.category == node.category
        assert cloned.amount == node.amount
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        node = create_test_node()
        snap = node.snapshot()
        assert snap["node_id"] == str(node.node_id)
        assert snap["amount"] == str(node.amount)

    def test_get_version(self):
        node = create_test_node()
        assert node.get_version() == 1

    def test_audit_trail_records(self):
        node = create_test_node()
        assert len(node.audit_trail()) >= 1
        node.touch("toucher")
        trail = node.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        node = create_test_node()
        touched = node.touch("toucher")
        assert touched.version == node.version + 1


# ============================================================================
# Tests for ValueFlow
# ============================================================================

class TestValueFlow:
    def test_create_valid_flow(self):
        flow = create_test_flow()
        assert flow.flow_id is not None
        assert len(flow.sources) == 2
        assert len(flow.destinations) == 1
        assert flow.total_source_value == Decimal("1000")
        assert flow.total_destination_value == Decimal("1000")
        assert flow.net_value_change == Decimal("0")
        assert flow.version == 1
        assert flow.cryptographic_hash != ""

    def test_validate_multiple_currencies_raises(self):
        source1 = create_test_node(currency="IDR")
        source2 = create_test_node(currency="USD")
        dest = create_test_node(currency="IDR")
        with pytest.raises(InvalidValueFlowError, match="Multiple currencies"):
            ValueFlow(
                flow_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                sources=[source1, source2],
                destinations=[dest],
                transaction_fee=Decimal(0),
                fee_currency="IDR",
                effective_date=datetime.now(UTC),
                description="test",
                created_by="tester",
                created_at=datetime.now(UTC),
            )

    def test_validate_negative_fee_raises(self):
        with pytest.raises(InvalidValueFlowError, match="Fee cannot be negative"):
            create_test_flow(transaction_fee=Decimal("-10"))

    def test_is_conserved_within_tolerance(self):
        flow = create_test_flow()
        is_conserved, diff = flow.is_conserved(Decimal("0.01"))
        assert is_conserved is True
        assert diff == Decimal("0")

    def test_is_conserved_outside_tolerance(self):
        sources = [create_test_node(amount=Decimal("1000"))]
        destinations = [create_test_node(amount=Decimal("900"), category=ValueCategory.LIABILITY)]
        flow = create_test_flow(sources=sources, destinations=destinations)
        is_conserved, diff = flow.is_conserved(Decimal("0.01"))
        assert is_conserved is False
        assert diff == Decimal("100")

    def test_update_creates_new_version(self):
        flow = create_test_flow()
        updated = flow.update("admin", description="Updated description")
        assert updated.description == "Updated description"
        assert updated.version == flow.version + 1

    def test_delete_marks_deleted(self):
        flow = create_test_flow()
        deleted = flow.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == flow.version + 1

    def test_restore_recovers_deleted(self):
        flow = create_test_flow()
        deleted = flow.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        flow = create_test_flow()
        with pytest.raises(ValueError, match="Flow not deleted"):
            flow.restore("admin")

    def test_activate_returns_self(self):
        flow = create_test_flow()
        activated = flow.activate("admin")
        assert activated is flow

    def test_deactivate_returns_self(self):
        flow = create_test_flow()
        deactivated = flow.deactivate("admin")
        assert deactivated is flow

    def test_lock_returns_self(self):
        flow = create_test_flow()
        locked = flow.lock("admin", "test")
        assert locked is flow

    def test_unlock_returns_self(self):
        flow = create_test_flow()
        unlocked = flow.unlock("admin")
        assert unlocked is flow

    def test_validate_returns_valid(self):
        flow = create_test_flow()
        result = flow.validate()
        assert result["is_valid"] is True
        assert result["flow_id"] == str(flow.flow_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        flow = create_test_flow()
        object.__setattr__(flow, "cryptographic_hash", "fake")
        result = flow.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        flow = create_test_flow()
        d = flow.to_dict()
        assert d["total_source"] == "1000"
        assert d["total_destination"] == "1000"
        assert d["transaction_fee"] == "0"
        assert d["description"] == "Test flow"

    def test_from_dict_reconstructs(self):
        flow = create_test_flow()
        d = flow.to_dict()
        reconstructed = ValueFlow.from_dict(d)
        assert reconstructed.flow_id == flow.flow_id
        assert reconstructed.transaction_id == flow.transaction_id
        assert reconstructed.total_source_value == flow.total_source_value
        assert reconstructed.total_destination_value == flow.total_destination_value

    def test_clone_creates_new_instance(self):
        flow = create_test_flow()
        cloned = flow.clone()
        assert cloned.flow_id != flow.flow_id
        assert cloned.transaction_id == flow.transaction_id
        assert cloned.total_source_value == flow.total_source_value
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        flow = create_test_flow()
        snap = flow.snapshot()
        assert snap["flow_id"] == str(flow.flow_id)
        assert snap["total_source"] == str(flow.total_source_value)

    def test_get_version(self):
        flow = create_test_flow()
        assert flow.get_version() == 1

    def test_audit_trail_records(self):
        flow = create_test_flow()
        assert len(flow.audit_trail()) >= 1
        flow.touch("toucher")
        trail = flow.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        flow = create_test_flow()
        touched = flow.touch("toucher")
        assert touched.version == flow.version + 1


# ============================================================================
# Tests for ConservationRecord
# ============================================================================

class TestConservationRecord:
    def test_create_valid_record(self):
        record = create_test_record()
        assert record.record_id is not None
        assert record.flow_id is not None
        assert record.is_conserved is True
        assert record.source_total == Decimal("1000")
        assert record.destination_total == Decimal("1000")
        assert record.severity == ConservationViolationSeverity.INFO
        assert record.version == 1
        assert record.forensic_hash != ""

    def test_update_raises(self):
        record = create_test_record()
        with pytest.raises(AttributeError):
            record.update("admin", is_conserved=False)

    def test_delete_raises(self):
        record = create_test_record()
        with pytest.raises(AttributeError):
            record.delete("admin")

    def test_restore_raises(self):
        record = create_test_record()
        with pytest.raises(AttributeError):
            record.restore("admin")

    def test_activate_returns_self(self):
        record = create_test_record()
        activated = record.activate("admin")
        assert activated is record

    def test_deactivate_returns_self(self):
        record = create_test_record()
        deactivated = record.deactivate("admin")
        assert deactivated is record

    def test_lock_returns_self(self):
        record = create_test_record()
        locked = record.lock("admin", "test")
        assert locked is record

    def test_unlock_returns_self(self):
        record = create_test_record()
        unlocked = record.unlock("admin")
        assert unlocked is record

    def test_validate_returns_valid(self):
        record = create_test_record()
        result = record.validate()
        assert result["is_valid"] is True
        assert result["record_id"] == str(record.record_id)

    def test_validate_returns_errors_on_forensic_hash_mismatch(self):
        record = create_test_record()
        object.__setattr__(record, "forensic_hash", "fake")
        result = record.validate()
        assert result["is_valid"] is False
        assert "Forensic hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        record = create_test_record()
        d = record.to_dict()
        assert d["is_conserved"] is True
        assert d["source_total"] == "1000"
        assert d["destination_total"] == "1000"
        assert d["severity"] == "INFO"

    def test_from_dict_reconstructs(self):
        record = create_test_record()
        d = record.to_dict()
        reconstructed = ConservationRecord.from_dict(d)
        assert reconstructed.record_id == record.record_id
        assert reconstructed.flow_id == record.flow_id
        assert reconstructed.is_conserved == record.is_conserved

    def test_clone_creates_new_instance(self):
        record = create_test_record()
        cloned = record.clone()
        assert cloned.record_id != record.record_id
        assert cloned.flow_id == record.flow_id
        assert cloned.is_conserved == record.is_conserved
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        record = create_test_record()
        snap = record.snapshot()
        assert snap["record_id"] == str(record.record_id)
        assert snap["is_conserved"] == record.is_conserved

    def test_get_version(self):
        record = create_test_record()
        assert record.get_version() == 1

    def test_audit_trail_records(self):
        record = create_test_record()
        assert len(record.audit_trail()) >= 1
        record.touch("toucher")
        trail = record.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for ConservationOfValueValidator
# ============================================================================

class TestConservationOfValueValidator:
    def test_validate_flow_conserved(self):
        flow = create_test_flow()
        is_conserved, record, hint = ConservationOfValueValidator.validate_flow(flow)
        assert is_conserved is True
        assert record is not None
        assert record.is_conserved is True
        assert hint is None

    def test_validate_flow_not_conserved(self):
        sources = [create_test_node(amount=Decimal("1000"))]
        destinations = [create_test_node(amount=Decimal("900"), category=ValueCategory.LIABILITY)]
        flow = create_test_flow(sources=sources, destinations=destinations)
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record, hint = ConservationOfValueValidator.validate_flow(flow)
        assert is_conserved is False
        assert record is not None
        assert record.is_conserved is False
        assert "difference" in record.violation_message

    def test_validate_flow_auto_correct_low_severity(self):
        sources = [create_test_node(amount=Decimal("1000"))]
        destinations = [create_test_node(amount=Decimal("999.95"), category=ValueCategory.LIABILITY)]
        flow = create_test_flow(sources=sources, destinations=destinations)
        # Small diff, should be low severity and auto-correct
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record, hint = ConservationOfValueValidator.validate_flow(
                flow, tolerance=Decimal("0.01"), auto_correct=True
            )
        assert is_conserved is False
        assert record is not None
        assert record.severity == ConservationViolationSeverity.LOW
        assert record.auto_corrected is True
        assert hint is not None

    def test_validate_transaction_balanced(self):
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("1000")),
        ]
        is_conserved, record, flow, hint = ConservationOfValueValidator.validate_transaction(
            transaction_id=uuid.uuid4(),
            journal_lines=lines,
        )
        assert is_conserved is True
        assert record is not None
        assert flow is not None
        assert flow.total_source_value == Decimal("1000")
        assert flow.total_destination_value == Decimal("1000")

    def test_validate_transaction_unbalanced(self):
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("800")),
        ]
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record, flow, hint = ConservationOfValueValidator.validate_transaction(
                transaction_id=uuid.uuid4(),
                journal_lines=lines,
            )
        assert is_conserved is False
        assert record is not None
        assert flow is not None
        assert record.difference == Decimal("200")

    def test_validate_transaction_with_fee(self):
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("990")),
        ]
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record, flow, hint = ConservationOfValueValidator.validate_transaction(
                transaction_id=uuid.uuid4(),
                journal_lines=lines,
                transaction_fee=Decimal("10"),
            )
        # Fee 10 -> total sources 1000, dest 990 + fee 10 = 1000, so balanced
        assert is_conserved is True
        assert record is not None
        assert flow is not None


# ============================================================================
# Tests for ConservationOfValueAxiom
# ============================================================================

class TestConservationOfValueAxiom:
    def test_singleton(self):
        axiom1 = ConservationOfValueAxiom()
        axiom2 = ConservationOfValueAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_flow(self):
        axiom = ConservationOfValueAxiom()
        flow = create_test_flow()
        axiom.save_flow(flow)
        retrieved = axiom.get_flow(flow.flow_id)
        assert retrieved is not None
        assert retrieved.flow_id == flow.flow_id

    def test_get_all_flows(self):
        axiom = ConservationOfValueAxiom()
        flow1 = create_test_flow()
        flow2 = create_test_flow()
        axiom.save_flow(flow1)
        axiom.save_flow(flow2)
        flows = axiom.get_all_flows()
        assert len(flows) >= 2

    def test_delete_flow(self):
        axiom = ConservationOfValueAxiom()
        flow = create_test_flow()
        axiom.save_flow(flow)
        result = axiom.delete_flow(flow.flow_id)
        assert result is True
        assert axiom.get_flow(flow.flow_id) is None

    def test_save_record_and_get_records(self):
        axiom = ConservationOfValueAxiom()
        record = create_test_record()
        axiom.save_record(record)
        records = axiom.get_records()
        assert len(records) >= 1
        found = next((r for r in records if r.record_id == record.record_id), None)
        assert found is not None

    def test_get_records_only_violations(self):
        axiom = ConservationOfValueAxiom()
        rec1 = create_test_record(is_conserved=True)
        rec2 = create_test_record(is_conserved=False)
        axiom.save_record(rec1)
        axiom.save_record(rec2)
        violations = axiom.get_records(only_violations=True)
        assert all(not r.is_conserved for r in violations)

    def test_create_flow(self):
        axiom = ConservationOfValueAxiom()
        sources = [create_test_node()]
        destinations = [create_test_node(category=ValueCategory.LIABILITY)]
        flow = axiom.create_flow(
            transaction_id=uuid.uuid4(),
            sources=sources,
            destinations=destinations,
            description="Created by axiom",
        )
        assert flow is not None
        assert flow.description == "Created by axiom"
        assert flow.cryptographic_hash != ""
        assert axiom.get_flow(flow.flow_id) is not None

    def test_enforce_passes(self):
        axiom = ConservationOfValueAxiom()
        flow = create_test_flow()
        is_conserved, record = axiom.enforce(flow, raise_on_violation=False)
        assert is_conserved is True
        assert record is not None
        assert record.is_conserved is True

    def test_enforce_fails(self):
        axiom = ConservationOfValueAxiom()
        sources = [create_test_node(amount=Decimal("1000"))]
        destinations = [create_test_node(amount=Decimal("900"), category=ValueCategory.LIABILITY)]
        flow = create_test_flow(sources=sources, destinations=destinations)
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record = axiom.enforce(flow, raise_on_violation=False)
        assert is_conserved is False
        assert record is not None
        assert record.is_conserved is False

    def test_enforce_raises(self):
        axiom = ConservationOfValueAxiom()
        sources = [create_test_node(amount=Decimal("1000"))]
        destinations = [create_test_node(amount=Decimal("900"), category=ValueCategory.LIABILITY)]
        flow = create_test_flow(sources=sources, destinations=destinations)
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            with pytest.raises(ConservationViolationError):
                axiom.enforce(flow, raise_on_violation=True)

    def test_enforce_transaction_balanced(self):
        axiom = ConservationOfValueAxiom()
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("1000")),
        ]
        is_conserved, record, flow = axiom.enforce_transaction(
            transaction_id=uuid.uuid4(),
            journal_lines=lines,
            raise_on_violation=False,
        )
        assert is_conserved is True
        assert record is not None
        assert flow is not None
        assert flow.total_source_value == Decimal("1000")

    def test_enforce_transaction_unbalanced(self):
        axiom = ConservationOfValueAxiom()
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("800")),
        ]
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record, flow = axiom.enforce_transaction(
                transaction_id=uuid.uuid4(),
                journal_lines=lines,
                raise_on_violation=False,
            )
        assert is_conserved is False
        assert record is not None
        assert flow is not None
        assert record.difference == Decimal("200")

    def test_get_flows_by_transaction(self):
        axiom = ConservationOfValueAxiom()
        tx_id = uuid.uuid4()
        flow1 = create_test_flow()
        flow1.transaction_id = tx_id
        flow2 = create_test_flow()
        flow2.transaction_id = tx_id
        axiom.save_flow(flow1)
        axiom.save_flow(flow2)
        flows = axiom.get_flows_by_transaction(tx_id)
        assert len(flows) == 2
        assert all(f.transaction_id == tx_id for f in flows)

    def test_get_statistics(self):
        axiom = ConservationOfValueAxiom()
        flow = create_test_flow()
        axiom.save_flow(flow)
        rec = create_test_record()
        axiom.save_record(rec)
        stats = axiom.get_statistics()
        assert stats["total_flows"] >= 1
        assert stats["total_validations"] >= 1
        assert "violation_count" in stats
        assert "compliance_rate" in stats
        assert "auto_corrected_violations" in stats

    def test_reset(self):
        axiom = ConservationOfValueAxiom()
        flow = create_test_flow()
        axiom.save_flow(flow)
        rec = create_test_record()
        axiom.save_record(rec)
        axiom.reset()
        assert len(axiom._flows) == 0
        assert len(axiom._records) == 0
        assert len(axiom._violation_history) == 0


# ============================================================================
# Tests for Helper Functions
# ============================================================================

class TestHelpers:
    def test_create_value_node(self):
        le_id = uuid.uuid4()
        proj_id = uuid.uuid4()
        node = create_value_node(
            category=ValueCategory.EXPENSE,
            legal_entity_id=le_id,
            account_code="5100",
            amount=Decimal("500"),
            currency="USD",
            description="Test expense",
            cost_center="CC001",
            department="DEPT02",
            project_id=proj_id,
        )
        assert node.category == ValueCategory.EXPENSE
        assert node.legal_entity_id == le_id
        assert node.account_code == "5100"
        assert node.amount == Decimal("500")
        assert node.currency == "USD"
        assert node.project_id == proj_id

    def test_create_journal_line_dict(self):
        le_id = uuid.uuid4()
        proj_id = uuid.uuid4()
        line = create_journal_line_dict(
            account_code="1100",
            debit=Decimal("1000"),
            credit=Decimal("0"),
            currency="IDR",
            legal_entity_id=le_id,
            description="Test",
            cost_center="CC001",
            department="DEPT01",
            project_id=proj_id,
        )
        assert line["account_code"] == "1100"
        assert line["debit"] == Decimal("1000")
        assert line["credit"] == Decimal("0")
        assert line["legal_entity_id"] == le_id
        assert line["project_id"] == proj_id

    def test_get_conservation_axiom_singleton(self):
        axiom1 = get_conservation_axiom()
        axiom2 = get_conservation_axiom()
        assert axiom1 is axiom2

# ============================================================================
# ADDITIONAL TESTS UNTUK MENUTUPI METHOD YANG BELUM TERCOVER
# ============================================================================

class TestValueNodeAdditional:
    def test_create_returns_self(self):
        node = create_test_node()
        result = node.create("admin")
        assert result is node

    def test_deactivate_returns_self(self):
        node = create_test_node()
        result = node.deactivate("admin", "test")
        assert result is node

    def test_lock_returns_self(self):
        node = create_test_node()
        result = node.lock("admin", "test")
        assert result is node

    def test_unlock_returns_self(self):
        node = create_test_node()
        result = node.unlock("admin")
        assert result is node

    def test_validate_with_hash_mismatch_returns_false(self):
        node = create_test_node()
        object.__setattr__(node, "cryptographic_hash", "fake")
        result = node.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_delete_with_reason(self):
        node = create_test_node()
        deleted = node.delete("admin", "reason")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == node.version + 1

    def test_clone_preserves_all_fields_except_id_and_version(self):
        node = create_test_node()
        cloned = node.clone()
        assert cloned.category == node.category
        assert cloned.amount == node.amount
        assert cloned.currency == node.currency
        assert cloned.account_code == node.account_code
        assert cloned.legal_entity_id == node.legal_entity_id
        assert cloned.cost_center == node.cost_center


class TestValueFlowAdditional:
    def test_create_returns_self(self):
        flow = create_test_flow()
        result = flow.create("admin")
        assert result is flow

    def test_deactivate_returns_self(self):
        flow = create_test_flow()
        result = flow.deactivate("admin", "test")
        assert result is flow

    def test_validate_with_hash_mismatch_returns_false(self):
        flow = create_test_flow()
        object.__setattr__(flow, "cryptographic_hash", "fake")
        result = flow.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_clone_creates_new_flow_with_deep_copies(self):
        flow = create_test_flow()
        cloned = flow.clone()
        assert cloned.flow_id != flow.flow_id
        assert cloned.transaction_id == flow.transaction_id
        assert cloned.total_source_value == flow.total_source_value
        assert cloned.total_destination_value == flow.total_destination_value
        assert len(cloned.sources) == len(flow.sources)
        assert len(cloned.destinations) == len(flow.destinations)

    def test_net_value_change_calculation(self):
        sources = [create_test_node(amount=Decimal("500")), create_test_node(amount=Decimal("300"))]
        dest = [create_test_node(amount=Decimal("700"), category=ValueCategory.LIABILITY)]
        flow = create_test_flow(sources=sources, destinations=dest, transaction_fee=Decimal("100"))
        assert flow.net_value_change == Decimal("0")  # 800 - 700 - 100 = 0

    def test_validate_with_mixed_currencies_raises(self):
        source1 = create_test_node(currency="IDR")
        source2 = create_test_node(currency="USD")
        dest = create_test_node(currency="IDR")
        with pytest.raises(InvalidValueFlowError, match="Multiple currencies"):
            ValueFlow(
                flow_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                sources=[source1, source2],
                destinations=[dest],
                transaction_fee=Decimal(0),
                fee_currency="IDR",
                effective_date=datetime.now(UTC),
                description="test",
                created_by="tester",
                created_at=datetime.now(UTC),
            )

    def test_validate_with_negative_fee_raises(self):
        with pytest.raises(InvalidValueFlowError, match="Fee cannot be negative"):
            create_test_flow(transaction_fee=Decimal("-5"))


class TestConservationRecordAdditional:
    def test_create_returns_self(self):
        record = create_test_record()
        result = record.create("admin")
        assert result is record

    def test_activate_returns_self(self):
        record = create_test_record()
        result = record.activate("admin")
        assert result is record

    def test_deactivate_returns_self(self):
        record = create_test_record()
        result = record.deactivate("admin", "test")
        assert result is record

    def test_lock_returns_self(self):
        record = create_test_record()
        result = record.lock("admin", "test")
        assert result is record

    def test_unlock_returns_self(self):
        record = create_test_record()
        result = record.unlock("admin")
        assert result is record

    def test_validate_with_forensic_hash_mismatch(self):
        record = create_test_record()
        object.__setattr__(record, "forensic_hash", "fake")
        result = record.validate()
        assert result["is_valid"] is False
        assert "Forensic hash mismatch" in result["errors"]

    def test_clone_preserves_data(self):
        record = create_test_record()
        cloned = record.clone()
        assert cloned.record_id != record.record_id
        assert cloned.flow_id == record.flow_id
        assert cloned.transaction_id == record.transaction_id
        assert cloned.is_conserved == record.is_conserved
        assert cloned.source_total == record.source_total


class TestConservationOfValueValidatorAdditional:
    def test_determine_severity_catastrophic(self):
        # ratio > 5%
        severity = ConservationOfValueValidator._determine_severity(
            difference=Decimal("100"),
            total_value=Decimal("1000"),
            tolerance=Decimal("0.01")
        )
        assert severity == ConservationViolationSeverity.CATASTROPHIC

    def test_determine_severity_critical(self):
        # ratio > 1% but <= 5%
        severity = ConservationOfValueValidator._determine_severity(
            difference=Decimal("20"),
            total_value=Decimal("1000"),
            tolerance=Decimal("0.01")
        )
        assert severity == ConservationViolationSeverity.CRITICAL

    def test_determine_severity_high(self):
        # ratio > 0.1% but <= 1%
        severity = ConservationOfValueValidator._determine_severity(
            difference=Decimal("5"),
            total_value=Decimal("1000"),
            tolerance=Decimal("0.01")
        )
        assert severity == ConservationViolationSeverity.HIGH

    def test_determine_severity_medium(self):
        # ratio > 0.01% but <= 0.1%
        severity = ConservationOfValueValidator._determine_severity(
            difference=Decimal("0.5"),
            total_value=Decimal("1000"),
            tolerance=Decimal("0.01")
        )
        assert severity == ConservationViolationSeverity.MEDIUM

    def test_determine_severity_low(self):
        # ratio > tolerance*10 but <= 0.01%
        severity = ConservationOfValueValidator._determine_severity(
            difference=Decimal("0.02"),
            total_value=Decimal("1000"),
            tolerance=Decimal("0.01")
        )
        # 0.02/1000 = 0.00002 = 0.002%, tolerance*10 = 0.1, so ratio > 0.0001?
        # Actually we test the logic: we just ensure it returns LOW
        assert severity == ConservationViolationSeverity.LOW

    def test_determine_severity_info(self):
        severity = ConservationOfValueValidator._determine_severity(
            difference=Decimal("0.0001"),
            total_value=Decimal("1000"),
            tolerance=Decimal("0.01")
        )
        assert severity == ConservationViolationSeverity.INFO

    def test_validate_transaction_with_empty_lines(self):
        is_conserved, record, flow, hint = ConservationOfValueValidator.validate_transaction(
            transaction_id=uuid.uuid4(),
            journal_lines=[],
        )
        assert is_conserved is True
        assert record is not None
        assert flow is not None
        assert flow.total_source_value == Decimal("0")
        assert flow.total_destination_value == Decimal("0")

    def test_validate_transaction_with_mixed_currencies(self):
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000"), currency="IDR"),
            create_journal_line_dict(account_code="2100", credit=Decimal("1000"), currency="USD"),
        ]
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record, flow, hint = ConservationOfValueValidator.validate_transaction(
                transaction_id=uuid.uuid4(),
                journal_lines=lines,
            )
        # Should fail due to currency mismatch
        assert is_conserved is False
        assert record is not None
        assert flow is not None

    def test_validate_transaction_with_debit_and_credit_in_same_line(self):
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000"), credit=Decimal("500")),
        ]
        is_conserved, record, flow, hint = ConservationOfValueValidator.validate_transaction(
            transaction_id=uuid.uuid4(),
            journal_lines=lines,
        )
        # Source from debit, destination from credit, so 1000 vs 500 -> diff 500
        assert is_conserved is False
        assert record is not None


class TestConservationOfValueAxiomAdditional:
    def test_create_flow_with_fee(self):
        axiom = ConservationOfValueAxiom()
        sources = [create_test_node(amount=Decimal("1000"))]
        destinations = [create_test_node(amount=Decimal("900"), category=ValueCategory.LIABILITY)]
        flow = axiom.create_flow(
            transaction_id=uuid.uuid4(),
            sources=sources,
            destinations=destinations,
            transaction_fee=Decimal("100"),
            fee_currency="IDR",
            flow_type=ValueFlowType.TRANSFER,
        )
        assert flow is not None
        assert flow.transaction_fee == Decimal("100")
        assert flow.fee_currency == "IDR"
        assert flow.flow_type == ValueFlowType.TRANSFER

    def test_enforce_with_auto_correct(self):
        axiom = ConservationOfValueAxiom()
        sources = [create_test_node(amount=Decimal("1000"))]
        destinations = [create_test_node(amount=Decimal("999.95"), category=ValueCategory.LIABILITY)]
        flow = create_test_flow(sources=sources, destinations=destinations)
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record = axiom.enforce(flow, auto_correct=True, raise_on_violation=False)
        assert is_conserved is False
        assert record is not None
        assert record.auto_corrected is True

    def test_enforce_transaction_with_auto_correct(self):
        axiom = ConservationOfValueAxiom()
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("999.95")),
        ]
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record, flow = axiom.enforce_transaction(
                transaction_id=uuid.uuid4(),
                journal_lines=lines,
                auto_correct=True,
                raise_on_violation=False,
            )
        assert is_conserved is False
        assert record is not None
        assert record.auto_corrected is True

    def test_enforce_transaction_raises_on_high_severity(self):
        axiom = ConservationOfValueAxiom()
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("500")),
        ]
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            with pytest.raises(ConservationViolationError):
                axiom.enforce_transaction(
                    transaction_id=uuid.uuid4(),
                    journal_lines=lines,
                    raise_on_violation=True,
                )

    def test_get_statistics_with_no_data(self):
        axiom = ConservationOfValueAxiom()
        stats = axiom.get_statistics()
        assert stats["total_flows"] == 0
        assert stats["total_validations"] == 0
        assert stats["compliance_rate"] == 1.0

    def test_get_statistics_with_violations(self):
        axiom = ConservationOfValueAxiom()
        # Add a violation record
        record = create_test_record(is_conserved=False)
        axiom.save_record(record)
        stats = axiom.get_statistics()
        assert stats["violation_count"] >= 1
        assert "by_severity" in stats

    def test_reset_clears_data(self):
        axiom = ConservationOfValueAxiom()
        flow = create_test_flow()
        axiom.save_flow(flow)
        record = create_test_record()
        axiom.save_record(record)
        axiom.reset()
        assert len(axiom.get_all_flows()) == 0
        assert len(axiom.get_records()) == 0


# ============================================================================
# ADDITIONAL TESTS UNTUK INTEGRATION
# ============================================================================

class TestConservationOfValueIntegration:
    def test_full_workflow_with_balanced_transaction(self):
        axiom = ConservationOfValueAxiom()
        tx_id = uuid.uuid4()
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("1000")),
        ]
        is_conserved, record, flow = axiom.enforce_transaction(
            transaction_id=tx_id,
            journal_lines=lines,
            raise_on_violation=False,
        )
        assert is_conserved is True
        assert record is not None
        assert flow is not None
        # Check flow saved
        retrieved = axiom.get_flow(flow.flow_id)
        assert retrieved is not None
        # Check statistics updated
        stats = axiom.get_statistics()
        assert stats["total_flows"] >= 1
        assert stats["total_validations"] >= 1
        assert stats["violation_count"] == 0

    def test_full_workflow_with_unbalanced_transaction(self):
        axiom = ConservationOfValueAxiom()
        tx_id = uuid.uuid4()
        lines = [
            create_journal_line_dict(account_code="1100", debit=Decimal("1000")),
            create_journal_line_dict(account_code="2100", credit=Decimal("800")),
        ]
        with patch("axioms.conservation_of_value.ConservationOfValueValidator._notify_constitution"):
            is_conserved, record, flow = axiom.enforce_transaction(
                transaction_id=tx_id,
                journal_lines=lines,
                raise_on_violation=False,
            )
        assert is_conserved is False
        assert record is not None
        assert flow is not None
        # Check violation recorded
        stats = axiom.get_statistics()
        assert stats["violation_count"] >= 1

    def test_multiple_flows_for_same_transaction(self):
        axiom = ConservationOfValueAxiom()
        tx_id = uuid.uuid4()
        flow1 = create_test_flow()
        flow1.transaction_id = tx_id
        flow2 = create_test_flow()
        flow2.transaction_id = tx_id
        axiom.save_flow(flow1)
        axiom.save_flow(flow2)
        flows = axiom.get_flows_by_transaction(tx_id)
        assert len(flows) == 2