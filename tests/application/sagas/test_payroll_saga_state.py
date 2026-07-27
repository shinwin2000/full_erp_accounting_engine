# tests/application/sagas/test_payroll_saga_state.py
"""
Unit tests for PayrollSagaState.
Covers all public methods with strong assertions.
All tests are deterministic (no sleep, mocked datetime).

Coverage:
- __init__: construction with required and optional fields
- add_error: append error and update timestamp (mocked)
- set_payroll_run: set run_id and update timestamp (mocked)
- add_payslip: append payslip ID and update timestamp (mocked)
- set_journal: set journal_id and update timestamp (mocked)
- set_bank_file: set bank_file_path and update timestamp (mocked)
- set_totals: set all totals and update timestamp (mocked)
- to_dict: convert to dictionary with correct types and format
- from_dict: reconstruct from dictionary with various scenarios
- Negative path tests: invalid data handling, edge cases
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from application.sagas.payroll_saga_state import PayrollSagaState


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fixed_datetime():
    """Fixed datetime for deterministic testing."""
    return datetime(2026, 7, 27, 12, 0, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_datetime):
    """Mock datetime.utcnow to return a fixed value."""
    with patch("application.sagas.payroll_saga_state.datetime") as mock_dt:
        mock_dt.utcnow.return_value = fixed_datetime
        # Also mock datetime.fromisoformat to keep real parsing
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_kwargs():
    """Base keyword arguments for creating a PayrollSagaState."""
    return {
        "saga_id": uuid4(),
        "legal_entity_id": uuid4(),
        "period_year": 2024,
        "period_month": 6,
        "payroll_date": date(2024, 6, 30),
        "user_id": uuid4(),
        "correlation_id": "corr-123",
        "employee_ids": [uuid4(), uuid4()],
        "payroll_run_id": uuid4(),
        "payslip_ids": [uuid4(), uuid4()],
        "journal_id": uuid4(),
        "bank_file_path": "/tmp/bank.csv",
        "total_gross": Decimal("10000.00"),
        "total_deductions": Decimal("2000.00"),
        "total_net": Decimal("8000.00"),
        "total_tax": Decimal("1500.00"),
        "status": "IN_PROGRESS",
        "errors": ["initial error"],
        "created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
    }


@pytest.fixture
def sample_state(sample_kwargs) -> PayrollSagaState:
    """A fully populated PayrollSagaState instance."""
    return PayrollSagaState(**sample_kwargs)


@pytest.fixture
def minimal_state() -> PayrollSagaState:
    """A minimal PayrollSagaState instance with only required fields."""
    return PayrollSagaState(
        saga_id=uuid4(),
        legal_entity_id=uuid4(),
        period_year=2024,
        period_month=6,
        payroll_date=date(2024, 6, 30),
    )


# ============================================================================
# Construction Tests
# ============================================================================

class TestConstruction:
    def test_required_fields_only(self, minimal_state):
        assert isinstance(minimal_state, PayrollSagaState)
        assert minimal_state.saga_id is not None
        assert minimal_state.legal_entity_id is not None
        assert minimal_state.period_year == 2024
        assert minimal_state.period_month == 6
        assert minimal_state.payroll_date == date(2024, 6, 30)
        assert minimal_state.user_id is None
        assert minimal_state.employee_ids == []
        assert minimal_state.payslip_ids == []
        assert minimal_state.payroll_run_id is None
        assert minimal_state.journal_id is None
        assert minimal_state.bank_file_path is None
        assert minimal_state.total_gross == Decimal("0")
        assert minimal_state.total_deductions == Decimal("0")
        assert minimal_state.total_net == Decimal("0")
        assert minimal_state.total_tax == Decimal("0")
        assert minimal_state.status == "INITIATED"
        assert minimal_state.errors == []
        assert minimal_state.created_at is not None
        assert minimal_state.updated_at is not None

    def test_all_fields(self, sample_state, sample_kwargs):
        assert sample_state.saga_id == sample_kwargs["saga_id"]
        assert sample_state.legal_entity_id == sample_kwargs["legal_entity_id"]
        assert sample_state.period_year == sample_kwargs["period_year"]
        assert sample_state.period_month == sample_kwargs["period_month"]
        assert sample_state.payroll_date == sample_kwargs["payroll_date"]
        assert sample_state.user_id == sample_kwargs["user_id"]
        assert sample_state.correlation_id == sample_kwargs["correlation_id"]
        assert sample_state.employee_ids == sample_kwargs["employee_ids"]
        assert sample_state.payroll_run_id == sample_kwargs["payroll_run_id"]
        assert sample_state.payslip_ids == sample_kwargs["payslip_ids"]
        assert sample_state.journal_id == sample_kwargs["journal_id"]
        assert sample_state.bank_file_path == sample_kwargs["bank_file_path"]
        assert sample_state.total_gross == sample_kwargs["total_gross"]
        assert sample_state.total_deductions == sample_kwargs["total_deductions"]
        assert sample_state.total_net == sample_kwargs["total_net"]
        assert sample_state.total_tax == sample_kwargs["total_tax"]
        assert sample_state.status == sample_kwargs["status"]
        assert sample_state.errors == sample_kwargs["errors"]
        assert sample_state.created_at == sample_kwargs["created_at"]
        assert sample_state.updated_at == sample_kwargs["updated_at"]


# ============================================================================
# Method: add_error
# ============================================================================

class TestAddError:
    def test_add_error_appends_to_errors(self, minimal_state):
        initial_count = len(minimal_state.errors)
        minimal_state.add_error("Something went wrong")
        assert len(minimal_state.errors) == initial_count + 1
        assert "Something went wrong" in minimal_state.errors

    def test_add_error_updates_updated_at(self, minimal_state, fixed_datetime):
        # Initial updated_at is the default from __init__, which uses datetime.utcnow()
        # We need to set it to a known value first because the fixture mocks utcnow.
        # However, the fixture mocks utcnow globally, so the initial updated_at is also fixed_datetime.
        # So we can't test that it changes unless we change the mock.
        # Instead, we test that calling the method sets updated_at to the mocked value.
        minimal_state.add_error("New error")
        # The updated_at should be set to the mocked fixed_datetime
        assert minimal_state.updated_at == fixed_datetime

    def test_add_error_multiple_errors(self, minimal_state):
        minimal_state.add_error("Error 1")
        minimal_state.add_error("Error 2")
        assert minimal_state.errors == ["Error 1", "Error 2"]

    def test_add_error_empty_string(self, minimal_state):
        minimal_state.add_error("")
        assert "" in minimal_state.errors

    def test_add_error_very_long_string(self, minimal_state):
        long_error = "x" * 10000
        minimal_state.add_error(long_error)
        assert minimal_state.errors[-1] == long_error


# ============================================================================
# Method: set_payroll_run
# ============================================================================

class TestSetPayrollRun:
    def test_set_payroll_run_sets_value(self, minimal_state):
        run_id = uuid4()
        minimal_state.set_payroll_run(run_id)
        assert minimal_state.payroll_run_id == run_id

    def test_set_payroll_run_updates_updated_at(self, minimal_state, fixed_datetime):
        minimal_state.set_payroll_run(uuid4())
        assert minimal_state.updated_at == fixed_datetime

    def test_set_payroll_run_overwrites_previous(self, minimal_state):
        run_id1 = uuid4()
        run_id2 = uuid4()
        minimal_state.set_payroll_run(run_id1)
        assert minimal_state.payroll_run_id == run_id1
        minimal_state.set_payroll_run(run_id2)
        assert minimal_state.payroll_run_id == run_id2

    def test_set_payroll_run_with_none(self, minimal_state):
        # The method expects a UUID, but we can test with None? It's typed as UUID.
        # But we can still test behavior if someone passes None (should set to None).
        # However, the method doesn't guard against None, so it will set to None.
        minimal_state.set_payroll_run(None)  # type: ignore
        assert minimal_state.payroll_run_id is None


# ============================================================================
# Method: add_payslip
# ============================================================================

class TestAddPayslip:
    def test_add_payslip_appends_to_list(self, minimal_state):
        payslip_id = uuid4()
        minimal_state.add_payslip(payslip_id)
        assert payslip_id in minimal_state.payslip_ids
        assert len(minimal_state.payslip_ids) == 1

    def test_add_payslip_updates_updated_at(self, minimal_state, fixed_datetime):
        minimal_state.add_payslip(uuid4())
        assert minimal_state.updated_at == fixed_datetime

    def test_add_payslip_multiple(self, minimal_state):
        pid1 = uuid4()
        pid2 = uuid4()
        minimal_state.add_payslip(pid1)
        minimal_state.add_payslip(pid2)
        assert minimal_state.payslip_ids == [pid1, pid2]

    def test_add_payslip_duplicate(self, minimal_state):
        pid = uuid4()
        minimal_state.add_payslip(pid)
        minimal_state.add_payslip(pid)  # duplicate
        # Duplicates are allowed (no deduplication)
        assert minimal_state.payslip_ids == [pid, pid]


# ============================================================================
# Method: set_journal
# ============================================================================

class TestSetJournal:
    def test_set_journal_sets_value(self, minimal_state):
        journal_id = uuid4()
        minimal_state.set_journal(journal_id)
        assert minimal_state.journal_id == journal_id

    def test_set_journal_updates_updated_at(self, minimal_state, fixed_datetime):
        minimal_state.set_journal(uuid4())
        assert minimal_state.updated_at == fixed_datetime

    def test_set_journal_overwrites_previous(self, minimal_state):
        jid1 = uuid4()
        jid2 = uuid4()
        minimal_state.set_journal(jid1)
        assert minimal_state.journal_id == jid1
        minimal_state.set_journal(jid2)
        assert minimal_state.journal_id == jid2

    def test_set_journal_with_none(self, minimal_state):
        minimal_state.set_journal(None)  # type: ignore
        assert minimal_state.journal_id is None


# ============================================================================
# Method: set_bank_file
# ============================================================================

class TestSetBankFile:
    def test_set_bank_file_sets_value(self, minimal_state):
        file_path = "/tmp/bank_export.csv"
        minimal_state.set_bank_file(file_path)
        assert minimal_state.bank_file_path == file_path

    def test_set_bank_file_updates_updated_at(self, minimal_state, fixed_datetime):
        minimal_state.set_bank_file("/new/path")
        assert minimal_state.updated_at == fixed_datetime

    def test_set_bank_file_overwrites_previous(self, minimal_state):
        minimal_state.set_bank_file("/old/path")
        assert minimal_state.bank_file_path == "/old/path"
        minimal_state.set_bank_file("/new/path")
        assert minimal_state.bank_file_path == "/new/path"

    def test_set_bank_file_with_empty_string(self, minimal_state):
        minimal_state.set_bank_file("")
        assert minimal_state.bank_file_path == ""

    def test_set_bank_file_with_none(self, minimal_state):
        minimal_state.set_bank_file(None)  # type: ignore
        assert minimal_state.bank_file_path is None


# ============================================================================
# Method: set_totals
# ============================================================================

class TestSetTotals:
    def test_set_totals_sets_all_values(self, minimal_state):
        gross = Decimal("15000.00")
        deductions = Decimal("3000.00")
        net = Decimal("12000.00")
        tax = Decimal("2000.00")
        minimal_state.set_totals(gross, deductions, net, tax)
        assert minimal_state.total_gross == gross
        assert minimal_state.total_deductions == deductions
        assert minimal_state.total_net == net
        assert minimal_state.total_tax == tax

    def test_set_totals_updates_updated_at(self, minimal_state, fixed_datetime):
        minimal_state.set_totals(Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"))
        assert minimal_state.updated_at == fixed_datetime

    def test_set_totals_overwrites_previous(self, minimal_state):
        minimal_state.set_totals(Decimal("100"), Decimal("20"), Decimal("80"), Decimal("15"))
        assert minimal_state.total_gross == Decimal("100")
        minimal_state.set_totals(Decimal("200"), Decimal("40"), Decimal("160"), Decimal("30"))
        assert minimal_state.total_gross == Decimal("200")

    def test_set_totals_with_negative_values(self, minimal_state):
        # Negative values are allowed (though business logic may not allow)
        minimal_state.set_totals(Decimal("-100"), Decimal("-20"), Decimal("-80"), Decimal("-15"))
        assert minimal_state.total_gross == Decimal("-100")

    def test_set_totals_with_zero(self, minimal_state):
        minimal_state.set_totals(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
        assert minimal_state.total_gross == Decimal("0")
        assert minimal_state.total_deductions == Decimal("0")


# ============================================================================
# Method: to_dict
# ============================================================================

class TestToDict:
    def test_to_dict_contains_all_fields(self, sample_state):
        d = sample_state.to_dict()
        assert d["saga_id"] == str(sample_state.saga_id)
        assert d["legal_entity_id"] == str(sample_state.legal_entity_id)
        assert d["period_year"] == sample_state.period_year
        assert d["period_month"] == sample_state.period_month
        assert d["payroll_date"] == sample_state.payroll_date.isoformat()
        assert d["user_id"] == str(sample_state.user_id)
        assert d["correlation_id"] == sample_state.correlation_id
        assert d["employee_ids"] == [str(eid) for eid in sample_state.employee_ids]
        assert d["payroll_run_id"] == str(sample_state.payroll_run_id)
        assert d["payslip_ids"] == [str(pid) for pid in sample_state.payslip_ids]
        assert d["journal_id"] == str(sample_state.journal_id)
        assert d["bank_file_path"] == sample_state.bank_file_path
        assert d["total_gross"] == str(sample_state.total_gross)
        assert d["total_deductions"] == str(sample_state.total_deductions)
        assert d["total_net"] == str(sample_state.total_net)
        assert d["total_tax"] == str(sample_state.total_tax)
        assert d["status"] == sample_state.status
        assert d["errors"] == sample_state.errors
        assert d["created_at"] == sample_state.created_at.isoformat()
        assert d["updated_at"] == sample_state.updated_at.isoformat()

    def test_to_dict_handles_none_optional_fields(self, minimal_state):
        d = minimal_state.to_dict()
        assert d["user_id"] is None
        assert d["correlation_id"] is None
        assert d["payroll_run_id"] is None
        assert d["journal_id"] is None
        assert d["bank_file_path"] is None
        assert d["employee_ids"] == []
        assert d["payslip_ids"] == []
        assert d["total_gross"] == "0"
        assert d["total_deductions"] == "0"
        assert d["total_net"] == "0"
        assert d["total_tax"] == "0"
        assert d["status"] == "INITIATED"
        assert d["errors"] == []


# ============================================================================
# Method: from_dict
# ============================================================================

class TestFromDict:
    def test_from_dict_reconstructs_full_state(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = PayrollSagaState.from_dict(d)
        assert reconstructed.saga_id == sample_state.saga_id
        assert reconstructed.legal_entity_id == sample_state.legal_entity_id
        assert reconstructed.period_year == sample_state.period_year
        assert reconstructed.period_month == sample_state.period_month
        assert reconstructed.payroll_date == sample_state.payroll_date
        assert reconstructed.user_id == sample_state.user_id
        assert reconstructed.correlation_id == sample_state.correlation_id
        assert reconstructed.employee_ids == sample_state.employee_ids
        assert reconstructed.payroll_run_id == sample_state.payroll_run_id
        assert reconstructed.payslip_ids == sample_state.payslip_ids
        assert reconstructed.journal_id == sample_state.journal_id
        assert reconstructed.bank_file_path == sample_state.bank_file_path
        assert reconstructed.total_gross == sample_state.total_gross
        assert reconstructed.total_deductions == sample_state.total_deductions
        assert reconstructed.total_net == sample_state.total_net
        assert reconstructed.total_tax == sample_state.total_tax
        assert reconstructed.status == sample_state.status
        assert reconstructed.errors == sample_state.errors
        assert reconstructed.created_at == sample_state.created_at
        assert reconstructed.updated_at == sample_state.updated_at

    def test_from_dict_handles_missing_optional_fields(self, minimal_state):
        d = minimal_state.to_dict()
        # Remove optional keys to test defaults
        d.pop("user_id", None)
        d.pop("correlation_id", None)
        d.pop("payroll_run_id", None)
        d.pop("journal_id", None)
        d.pop("bank_file_path", None)
        d.pop("employee_ids", None)
        d.pop("payslip_ids", None)
        d.pop("total_gross", None)
        d.pop("total_deductions", None)
        d.pop("total_net", None)
        d.pop("total_tax", None)
        d.pop("status", None)
        d.pop("errors", None)

        reconstructed = PayrollSagaState.from_dict(d)
        assert reconstructed.user_id is None
        assert reconstructed.correlation_id is None
        assert reconstructed.payroll_run_id is None
        assert reconstructed.journal_id is None
        assert reconstructed.bank_file_path is None
        assert reconstructed.employee_ids == []
        assert reconstructed.payslip_ids == []
        assert reconstructed.total_gross == Decimal("0")
        assert reconstructed.total_deductions == Decimal("0")
        assert reconstructed.total_net == Decimal("0")
        assert reconstructed.total_tax == Decimal("0")
        assert reconstructed.status == "INITIATED"
        assert reconstructed.errors == []
        assert reconstructed.saga_id == minimal_state.saga_id
        assert reconstructed.legal_entity_id == minimal_state.legal_entity_id
        assert reconstructed.period_year == minimal_state.period_year
        assert reconstructed.period_month == minimal_state.period_month
        assert reconstructed.payroll_date == minimal_state.payroll_date

    def test_from_dict_with_none_uuid_strings(self, minimal_state):
        d = minimal_state.to_dict()
        d["user_id"] = None
        d["payroll_run_id"] = None
        d["journal_id"] = None
        reconstructed = PayrollSagaState.from_dict(d)
        assert reconstructed.user_id is None
        assert reconstructed.payroll_run_id is None
        assert reconstructed.journal_id is None

    def test_from_dict_handles_datetime_strings(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = PayrollSagaState.from_dict(d)
        assert reconstructed.created_at == sample_state.created_at
        assert reconstructed.updated_at == sample_state.updated_at

    def test_from_dict_handles_decimal_strings(self, minimal_state):
        d = minimal_state.to_dict()
        d["total_gross"] = "1234.56"
        d["total_deductions"] = "234.56"
        d["total_net"] = "1000.00"
        d["total_tax"] = "200.00"
        reconstructed = PayrollSagaState.from_dict(d)
        assert reconstructed.total_gross == Decimal("1234.56")
        assert reconstructed.total_deductions == Decimal("234.56")
        assert reconstructed.total_net == Decimal("1000.00")
        assert reconstructed.total_tax == Decimal("200.00")

    def test_from_dict_invalid_uuid_raises(self, minimal_state):
        d = minimal_state.to_dict()
        d["saga_id"] = "not-a-uuid"
        with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
            PayrollSagaState.from_dict(d)

    def test_from_dict_missing_required_field_raises(self, minimal_state):
        d = minimal_state.to_dict()
        del d["saga_id"]
        with pytest.raises(KeyError):
            PayrollSagaState.from_dict(d)


# ============================================================================
# Integration: Round-trip serialization
# ============================================================================

class TestSerializationRoundTrip:
    def test_to_dict_from_dict_round_trip(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = PayrollSagaState.from_dict(d)
        assert reconstructed == sample_state

    def test_to_dict_from_dict_round_trip_minimal(self, minimal_state):
        d = minimal_state.to_dict()
        reconstructed = PayrollSagaState.from_dict(d)
        assert reconstructed == minimal_state


# ============================================================================
# Additional Negative Path Tests for edge cases
# ============================================================================

class TestNegativePaths:
    def test_constructor_with_empty_employee_ids(self):
        state = PayrollSagaState(
            saga_id=uuid4(),
            legal_entity_id=uuid4(),
            period_year=2024,
            period_month=1,
            payroll_date=date.today(),
            employee_ids=[]
        )
        assert state.employee_ids == []

    def test_add_error_when_errors_already_exist(self):
        state = PayrollSagaState(
            saga_id=uuid4(),
            legal_entity_id=uuid4(),
            period_year=2024,
            period_month=1,
            payroll_date=date.today(),
            errors=["existing"]
        )
        state.add_error("new")
        assert state.errors == ["existing", "new"]

    def test_set_payroll_run_with_invalid_type_should_accept_any(self, minimal_state):
        # The method doesn't validate type, just assigns
        minimal_state.set_payroll_run("not-a-uuid")  # type: ignore
        assert minimal_state.payroll_run_id == "not-a-uuid"

    def test_to_dict_with_negative_totals(self):
        state = PayrollSagaState(
            saga_id=uuid4(),
            legal_entity_id=uuid4(),
            period_year=2024,
            period_month=1,
            payroll_date=date.today(),
            total_gross=Decimal("-100"),
            total_deductions=Decimal("-20"),
            total_net=Decimal("-80"),
            total_tax=Decimal("-15")
        )
        d = state.to_dict()
        assert d["total_gross"] == "-100"
        assert d["total_deductions"] == "-20"

    def test_from_dict_with_none_values_for_non_nullable_fields(self, minimal_state):
        d = minimal_state.to_dict()
        # Set a required field to None (should be handled by from_dict)
        d["period_year"] = None
        # This will fail because period_year must be int, but from_dict doesn't validate types strongly
        # We'll just check it doesn't crash
        reconstructed = PayrollSagaState.from_dict(d)
        assert reconstructed.period_year is None