#!/usr/bin/env python3
"""
tests/unit/test_axiom_violation.py
Test untuk axioms/axiom_violation.py
Mencakup: enum, value objects, exception classes, handler, dan module-level functions.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from axioms.axiom_violation import (
    AccrualBasisViolation,
    AxiomType,
    AxiomViolationError,
    AxiomViolationHandler,
    AxiomViolationRecord,
    AxiomViolationSeverity,
    CausalityChainViolation,
    ConservationOfValueViolation,
    DoubleEntryViolation,
    EntityIsolationViolation,
    GoingConcernViolation,
    ImmutabilityViolation,
    MaterialityViolation,
    MonetaryUnitViolation,
    PeriodBoundViolation,
    SubstanceOverFormViolation,
    TimeIrreversibilityViolation,
    get_axiom_violation_handler,
    handle_axiom_violation,
    raise_conservation_violation,
    raise_double_entry_violation,
)

# ============================================================================
# TESTS FOR ENUMS
# ============================================================================

class TestAxiomType:
    def test_members_exist(self):
        assert hasattr(AxiomType, 'CONSERVATION_OF_VALUE')
        assert hasattr(AxiomType, 'DOUBLE_ENTRY')
        assert hasattr(AxiomType, 'TIME_IRREVERSIBILITY')
        assert hasattr(AxiomType, 'IMMUTABILITY')
        assert hasattr(AxiomType, 'CAUSALITY_CHAIN')
        assert hasattr(AxiomType, 'MONETARY_UNIT')
        assert hasattr(AxiomType, 'ENTITY_ISOLATION')
        assert hasattr(AxiomType, 'PERIOD_BOUND')
        assert hasattr(AxiomType, 'GOING_CONCERN')
        assert hasattr(AxiomType, 'ACCRUAL_BASIS')
        assert hasattr(AxiomType, 'MATERIALITY')
        assert hasattr(AxiomType, 'SUBSTANCE_OVER_FORM')

    def test_member_is_instance(self):
        assert isinstance(AxiomType.CONSERVATION_OF_VALUE, AxiomType)


class TestAxiomViolationSeverity:
    def test_members_exist(self):
        assert hasattr(AxiomViolationSeverity, 'CATASTROPHIC')
        assert hasattr(AxiomViolationSeverity, 'CRITICAL')
        assert hasattr(AxiomViolationSeverity, 'HIGH')
        assert hasattr(AxiomViolationSeverity, 'MEDIUM')
        assert hasattr(AxiomViolationSeverity, 'LOW')
        assert hasattr(AxiomViolationSeverity, 'INFO')

    def test_member_is_instance(self):
        assert isinstance(AxiomViolationSeverity.CATASTROPHIC, AxiomViolationSeverity)


# ============================================================================
# TESTS FOR VALUE OBJECTS
# ============================================================================

class TestAxiomViolationRecord:
    def test_construction_success(self):
        now = datetime.now(UTC)
        record_id = uuid4()
        transaction_id = uuid4()
        legal_entity_id = uuid4()
        kwargs = {
            "record_id": record_id,
            "axiom_type": AxiomType.CONSERVATION_OF_VALUE,
            "axiom_name": "Conservation of Value",
            "transaction_id": transaction_id,
            "legal_entity_id": legal_entity_id,
            "user_id": "tester",
            "module": "test_module",
            "severity": AxiomViolationSeverity.HIGH,
            "original_severity_value": 5,
            "message": "Test violation",
            "context": {"key": "value"},
            "stack_trace": "Traceback...",
            "detected_at": now,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "resolution_note": None,
            "cryptographic_hash": "",
            "version": 1,
            "_snapshots": None,
            "_audit_trail": None,
        }
        instance = AxiomViolationRecord(**kwargs)
        assert isinstance(instance, AxiomViolationRecord)
        assert instance.record_id == record_id
        assert instance.axiom_type == AxiomType.CONSERVATION_OF_VALUE
        assert instance.transaction_id == transaction_id
        assert instance.legal_entity_id == legal_entity_id
        assert instance.severity == AxiomViolationSeverity.HIGH
        assert instance.resolved is False
        assert instance.cryptographic_hash != ""


# ============================================================================
# TESTS FOR EXCEPTION CLASSES
# ============================================================================

class TestAxiomViolationError:
    def test_construction(self):
        now = datetime.now(UTC)
        instance = AxiomViolationError(
            message="Test error",
            axiom_type=AxiomType.CONSERVATION_OF_VALUE,
            severity=AxiomViolationSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="tester",
            module="test_module",
            context={"detail": "info"},
            original_severity_value=10,
        )
        assert isinstance(instance, AxiomViolationError)
        assert isinstance(instance, Exception)
        assert instance.message == "Test error"
        assert instance.axiom_type == AxiomType.CONSERVATION_OF_VALUE

    def test_original_message_returns_string(self):
        instance = AxiomViolationError(
            message="Test error",
            axiom_type=AxiomType.CONSERVATION_OF_VALUE,
            severity=AxiomViolationSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="tester",
            module="test_module",
            context={},
            original_severity_value=1,
        )
        result = instance.original_message()
        assert isinstance(result, str)
        assert result == "Test error"

    def test_to_record_returns_record(self):
        transaction_id = uuid4()
        legal_entity_id = uuid4()
        instance = AxiomViolationError(
            message="Test error",
            axiom_type=AxiomType.DOUBLE_ENTRY,
            severity=AxiomViolationSeverity.HIGH,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            user_id="tester",
            module="test_module",
            context={"detail": "info"},
            original_severity_value=5,
        )
        record = instance.to_record()
        assert isinstance(record, AxiomViolationRecord)
        assert record.transaction_id == transaction_id
        assert record.legal_entity_id == legal_entity_id
        assert record.axiom_type == AxiomType.DOUBLE_ENTRY
        assert record.severity == AxiomViolationSeverity.HIGH
        assert record.message == "Test error"
        assert record.module == "test_module"

    def test_to_dict_returns_dict(self):
        instance = AxiomViolationError(
            message="Test error",
            axiom_type=AxiomType.CONSERVATION_OF_VALUE,
            severity=AxiomViolationSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="tester",
            module="test_module",
            context={"detail": "info"},
            original_severity_value=1,
        )
        result = instance.to_dict()
        assert isinstance(result, dict)
        assert result["message"] == "Test error"
        assert result["axiom_type"] == "CONSERVATION_OF_VALUE"
        assert result["severity"] == "CRITICAL"


# ============================================================================
# TESTS FOR VIOLATION SUBCLASSES
# ============================================================================

class TestConservationOfValueViolation:
    def test_construction(self):
        instance = ConservationOfValueViolation(
            message="Value mismatch",
            source_value=Decimal("100.00"),
            destination_value=Decimal("90.00"),
            difference=Decimal("10.00"),
            transaction_id=uuid4(),
            severity=AxiomViolationSeverity.CRITICAL,
        )
        assert isinstance(instance, ConservationOfValueViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.source_value == Decimal("100.00")
        assert instance.destination_value == Decimal("90.00")
        assert instance.difference == Decimal("10.00")


class TestDoubleEntryViolation:
    def test_construction(self):
        instance = DoubleEntryViolation(
            message="Debit/credit mismatch",
            total_debit=Decimal("100.00"),
            total_credit=Decimal("80.00"),
            difference=Decimal("20.00"),
            journal_id=uuid4(),
            severity=AxiomViolationSeverity.HIGH,
        )
        assert isinstance(instance, DoubleEntryViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.total_debit == Decimal("100.00")
        assert instance.total_credit == Decimal("80.00")
        assert instance.difference == Decimal("20.00")


class TestTimeIrreversibilityViolation:
    def test_construction(self):
        now = datetime.now(UTC)
        instance = TimeIrreversibilityViolation(
            message="Backdating violation",
            attempted_date=now,
            current_period_start=now - timedelta(days=30),
            backdate_days=10,
            severity=AxiomViolationSeverity.MEDIUM,
        )
        assert isinstance(instance, TimeIrreversibilityViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.backdate_days == 10


class TestImmutabilityViolation:
    def test_construction(self):
        record_id = uuid4()
        instance = ImmutabilityViolation(
            message="Immutability violation",
            target_record_id=record_id,
            attempted_operation="UPDATE",
            severity=AxiomViolationSeverity.CRITICAL,
        )
        assert isinstance(instance, ImmutabilityViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.target_record_id == record_id
        assert instance.attempted_operation == "UPDATE"


class TestCausalityChainViolation:
    def test_construction(self):
        instance = CausalityChainViolation(
            message="Missing evidence",
            missing_evidence=["doc1.pdf", "doc2.pdf"],
            incomplete_chain=True,
            severity=AxiomViolationSeverity.HIGH,
        )
        assert isinstance(instance, CausalityChainViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.missing_evidence == ["doc1.pdf", "doc2.pdf"]
        assert instance.incomplete_chain is True


class TestMonetaryUnitViolation:
    def test_construction(self):
        instance = MonetaryUnitViolation(
            message="Currency mismatch",
            currency_used="USD",
            functional_currency="IDR",
            severity=AxiomViolationSeverity.MEDIUM,
        )
        assert isinstance(instance, MonetaryUnitViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.currency_used == "USD"
        assert instance.functional_currency == "IDR"


class TestEntityIsolationViolation:
    def test_construction(self):
        source_id = uuid4()
        target_id = uuid4()
        instance = EntityIsolationViolation(
            message="Entity isolation violation",
            source_entity_id=source_id,
            target_entity_id=target_id,
            attempted_operation="READ",
            severity=AxiomViolationSeverity.HIGH,
        )
        assert isinstance(instance, EntityIsolationViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.source_entity_id == source_id
        assert instance.target_entity_id == target_id
        assert instance.attempted_operation == "READ"


class TestPeriodBoundViolation:
    def test_construction(self):
        now = datetime.now(UTC)
        instance = PeriodBoundViolation(
            message="Period closed",
            transaction_date=now,
            period_status="CLOSED",
            severity=AxiomViolationSeverity.CRITICAL,
        )
        assert isinstance(instance, PeriodBoundViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.transaction_date == now
        assert instance.period_status == "CLOSED"


class TestGoingConcernViolation:
    def test_construction(self):
        instance = GoingConcernViolation(
            message="Going concern issue",
            assessment_status="UNCERTAIN",
            severity=AxiomViolationSeverity.HIGH,
        )
        assert isinstance(instance, GoingConcernViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.assessment_status == "UNCERTAIN"


class TestAccrualBasisViolation:
    def test_construction(self):
        now = datetime.now(UTC)
        instance = AccrualBasisViolation(
            message="Accrual timing violation",
            recognition_date=now,
            cash_flow_date=now - timedelta(days=5),
            difference_days=5,
            severity=AxiomViolationSeverity.MEDIUM,
        )
        assert isinstance(instance, AccrualBasisViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.difference_days == 5


class TestMaterialityViolation:
    def test_construction(self):
        instance = MaterialityViolation(
            message="Materiality violation",
            item_amount=Decimal("5000000"),
            threshold=Decimal("1000000"),
            failure_type="NON_DISCLOSURE",
            severity=AxiomViolationSeverity.HIGH,
        )
        assert isinstance(instance, MaterialityViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.item_amount == Decimal("5000000")
        assert instance.threshold == Decimal("1000000")
        assert instance.failure_type == "NON_DISCLOSURE"


class TestSubstanceOverFormViolation:
    def test_construction(self):
        instance = SubstanceOverFormViolation(
            message="Substance over form violation",
            legal_form_summary="Operating lease",
            proper_treatment="Finance lease",
            severity=AxiomViolationSeverity.HIGH,
        )
        assert isinstance(instance, SubstanceOverFormViolation)
        assert isinstance(instance, AxiomViolationError)
        assert instance.legal_form_summary == "Operating lease"
        assert instance.proper_treatment == "Finance lease"


# ============================================================================
# TESTS FOR AXIOM VIOLATION HANDLER
# ============================================================================

class TestAxiomViolationHandler:
    def test_construction(self):
        instance = AxiomViolationHandler()
        assert isinstance(instance, AxiomViolationHandler)

    def test_handle_returns_record(self):
        handler = AxiomViolationHandler()
        exception = AxiomViolationError(
            message="Test error",
            axiom_type=AxiomType.CONSERVATION_OF_VALUE,
            severity=AxiomViolationSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="tester",
            module="test_module",
            context={},
            original_severity_value=1,
        )
        with patch.object(handler, 'save_violation', return_value=MagicMock(spec=AxiomViolationRecord)) as mock_save:
            result = handler.handle(exception=exception, record=True, notify=False)
            mock_save.assert_called_once()
            assert result is not None

    def test_handle_without_record_returns_none(self):
        handler = AxiomViolationHandler()
        exception = AxiomViolationError(
            message="Test error",
            axiom_type=AxiomType.CONSERVATION_OF_VALUE,
            severity=AxiomViolationSeverity.CRITICAL,
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            user_id="tester",
            module="test_module",
            context={},
            original_severity_value=1,
        )
        result = handler.handle(exception=exception, record=False, notify=False)
        assert result is None

    def test_save_violation_returns_record(self):
        handler = AxiomViolationHandler()
        record = MagicMock(spec=AxiomViolationRecord)
        record.record_id = uuid4()
        result = handler.save_violation(record=record)
        # Assuming save_violation returns True or the record
        assert result is not None

    def test_get_violations_returns_list(self):
        handler = AxiomViolationHandler()
        # Mock _violations store
        record1 = MagicMock(spec=AxiomViolationRecord)
        record1.record_id = uuid4()
        record1.axiom_type = AxiomType.CONSERVATION_OF_VALUE
        record1.severity = AxiomViolationSeverity.HIGH
        record1.resolved = False
        record2 = MagicMock(spec=AxiomViolationRecord)
        record2.record_id = uuid4()
        record2.axiom_type = AxiomType.DOUBLE_ENTRY
        record2.severity = AxiomViolationSeverity.LOW
        record2.resolved = True
        handler._violations = {record1.record_id: record1, record2.record_id: record2}

        result = handler.get_violations(axiom_type=AxiomType.CONSERVATION_OF_VALUE)
        assert len(result) == 1
        assert result[0].record_id == record1.record_id

        result = handler.get_violations(min_severity=AxiomViolationSeverity.HIGH)
        assert len(result) == 1
        assert result[0].record_id == record1.record_id

        result = handler.get_violations(unresolved_only=True)
        assert len(result) == 1
        assert result[0].resolved is False

    def test_get_violation_found(self):
        handler = AxiomViolationHandler()
        record_id = uuid4()
        record = MagicMock(spec=AxiomViolationRecord)
        record.record_id = record_id
        handler._violations = {record_id: record}
        result = handler.get_violation(record_id=record_id)
        assert result is not None
        assert result.record_id == record_id

    def test_get_violation_not_found(self):
        handler = AxiomViolationHandler()
        result = handler.get_violation(record_id=uuid4())
        assert result is None


# ============================================================================
# TESTS FOR MODULE-LEVEL FUNCTIONS
# ============================================================================

def test_get_axiom_violation_handler_returns_singleton():
    handler1 = get_axiom_violation_handler()
    handler2 = get_axiom_violation_handler()
    assert handler1 is handler2
    assert isinstance(handler1, AxiomViolationHandler)


def test_raise_conservation_violation_raises_exception():
    with pytest.raises(ConservationOfValueViolation) as exc_info:
        raise_conservation_violation(
            message="Value mismatch",
            source_value=Decimal("100.00"),
            destination_value=Decimal("90.00"),
            difference=Decimal("10.00"),
            transaction_id=uuid4(),
        )
    assert isinstance(exc_info.value, ConservationOfValueViolation)
    assert exc_info.value.source_value == Decimal("100.00")
    assert exc_info.value.destination_value == Decimal("90.00")
    assert exc_info.value.difference == Decimal("10.00")


def test_raise_double_entry_violation_raises_exception():
    journal_id = uuid4()
    with pytest.raises(DoubleEntryViolation) as exc_info:
        raise_double_entry_violation(
            message="Debit/credit mismatch",
            total_debit=Decimal("100.00"),
            total_credit=Decimal("80.00"),
            difference=Decimal("20.00"),
            journal_id=journal_id,
        )
    assert isinstance(exc_info.value, DoubleEntryViolation)
    assert exc_info.value.total_debit == Decimal("100.00")
    assert exc_info.value.total_credit == Decimal("80.00")
    assert exc_info.value.difference == Decimal("20.00")
    assert exc_info.value.journal_id == journal_id


def test_handle_axiom_violation_calls_handler():
    exception = AxiomViolationError(
        message="Test error",
        axiom_type=AxiomType.CONSERVATION_OF_VALUE,
        severity=AxiomViolationSeverity.CRITICAL,
        transaction_id=uuid4(),
        legal_entity_id=uuid4(),
        user_id="tester",
        module="test_module",
        context={},
        original_severity_value=1,
    )
    with patch("axioms.axiom_violation.get_axiom_violation_handler") as mock_get_handler:
        mock_handler = MagicMock()
        mock_handler.handle.return_value = MagicMock(spec=AxiomViolationRecord)
        mock_get_handler.return_value = mock_handler
        result = handle_axiom_violation(exc=exception)
        mock_handler.handle.assert_called_once_with(exception=exception, record=True, notify=True)
        assert result is not None
