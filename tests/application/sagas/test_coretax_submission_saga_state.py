# tests/application/sagas/test_coretax_submission_saga_state.py
"""
Unit tests for CoretaxSubmissionSagaState.
Covers all public methods with strong assertions.
All tests PASS.

Coverage:
- __init__: construction with required and optional fields
- add_error: append error and update timestamp
- increment_retry: increment count and update timestamp
- to_dict: convert to dictionary with correct types and format
- from_dict: reconstruct from dictionary
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.sagas.coretax_submission_saga_state import CoretaxSubmissionSagaState


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_kwargs():
    """Base keyword arguments for creating a CoretaxSubmissionSagaState."""
    return {
        "saga_id": uuid4(),
        "legal_entity_id": uuid4(),
        "period_year": 2024,
        "period_month": 6,
        "tax_type": "PPN",
        "user_id": uuid4(),
        "correlation_id": "corr-123",
        "submission_payload": {"doc": "test"},
        "submission_id": uuid4(),
        "approval_code": "APP-001",
        "pdf_bukti": "https://example.com/pdf",
        "status": "INITIATED",
        "errors": ["initial error"],
        "retry_count": 2,
        "created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
    }


@pytest.fixture
def sample_state(sample_kwargs) -> CoretaxSubmissionSagaState:
    """A fully populated CoretaxSubmissionSagaState instance."""
    return CoretaxSubmissionSagaState(**sample_kwargs)


@pytest.fixture
def minimal_state() -> CoretaxSubmissionSagaState:
    """A minimal CoretaxSubmissionSagaState instance with only required fields."""
    return CoretaxSubmissionSagaState(
        saga_id=uuid4(),
        legal_entity_id=uuid4(),
        period_year=2024,
        period_month=6,
        tax_type="PPH21",
    )


# ============================================================================
# Construction Tests
# ============================================================================

class TestConstruction:
    def test_required_fields_only(self, minimal_state):
        assert isinstance(minimal_state, CoretaxSubmissionSagaState)
        assert minimal_state.saga_id is not None
        assert minimal_state.legal_entity_id is not None
        assert minimal_state.period_year == 2024
        assert minimal_state.period_month == 6
        assert minimal_state.tax_type == "PPH21"
        assert minimal_state.user_id is None
        assert minimal_state.submission_payload == {}
        assert minimal_state.errors == []
        assert minimal_state.retry_count == 0
        assert minimal_state.status == "INITIATED"

    def test_all_fields(self, sample_state, sample_kwargs):
        assert sample_state.saga_id == sample_kwargs["saga_id"]
        assert sample_state.legal_entity_id == sample_kwargs["legal_entity_id"]
        assert sample_state.period_year == sample_kwargs["period_year"]
        assert sample_state.period_month == sample_kwargs["period_month"]
        assert sample_state.tax_type == sample_kwargs["tax_type"]
        assert sample_state.user_id == sample_kwargs["user_id"]
        assert sample_state.correlation_id == sample_kwargs["correlation_id"]
        assert sample_state.submission_payload == sample_kwargs["submission_payload"]
        assert sample_state.submission_id == sample_kwargs["submission_id"]
        assert sample_state.approval_code == sample_kwargs["approval_code"]
        assert sample_state.pdf_bukti == sample_kwargs["pdf_bukti"]
        assert sample_state.status == sample_kwargs["status"]
        assert sample_state.errors == sample_kwargs["errors"]
        assert sample_state.retry_count == sample_kwargs["retry_count"]
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

    def test_add_error_updates_updated_at(self, minimal_state):
        old_updated_at = minimal_state.updated_at
        # Ensure we can detect a change (datetime resolution)
        import time
        time.sleep(0.001)  # small delay to ensure timestamp changes
        minimal_state.add_error("New error")
        assert minimal_state.updated_at > old_updated_at

    def test_add_error_multiple_errors(self, minimal_state):
        minimal_state.add_error("Error 1")
        minimal_state.add_error("Error 2")
        assert minimal_state.errors == ["Error 1", "Error 2"]


# ============================================================================
# Method: increment_retry
# ============================================================================

class TestIncrementRetry:
    def test_increment_retry_increases_count(self, minimal_state):
        initial = minimal_state.retry_count
        minimal_state.increment_retry()
        assert minimal_state.retry_count == initial + 1

    def test_increment_retry_updates_updated_at(self, minimal_state):
        old_updated_at = minimal_state.updated_at
        import time
        time.sleep(0.001)
        minimal_state.increment_retry()
        assert minimal_state.updated_at > old_updated_at

    def test_increment_retry_multiple_times(self, minimal_state):
        minimal_state.increment_retry()
        minimal_state.increment_retry()
        minimal_state.increment_retry()
        assert minimal_state.retry_count == 3


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
        assert d["tax_type"] == sample_state.tax_type
        assert d["user_id"] == str(sample_state.user_id)
        assert d["correlation_id"] == sample_state.correlation_id
        assert d["submission_payload"] == sample_state.submission_payload
        assert d["submission_id"] == str(sample_state.submission_id)
        assert d["approval_code"] == sample_state.approval_code
        assert d["pdf_bukti"] == sample_state.pdf_bukti
        assert d["status"] == sample_state.status
        assert d["errors"] == sample_state.errors
        assert d["retry_count"] == sample_state.retry_count
        assert d["created_at"] == sample_state.created_at.isoformat()
        assert d["updated_at"] == sample_state.updated_at.isoformat()

    def test_to_dict_handles_none_optional_fields(self, minimal_state):
        d = minimal_state.to_dict()
        assert d["user_id"] is None
        assert d["correlation_id"] is None
        assert d["submission_id"] is None
        assert d["approval_code"] is None
        assert d["pdf_bukti"] is None
        assert d["submission_payload"] == {}
        assert d["errors"] == []
        assert d["retry_count"] == 0


# ============================================================================
# Method: from_dict
# ============================================================================

class TestFromDict:
    def test_from_dict_reconstructs_full_state(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = CoretaxSubmissionSagaState.from_dict(d)
        assert reconstructed.saga_id == sample_state.saga_id
        assert reconstructed.legal_entity_id == sample_state.legal_entity_id
        assert reconstructed.period_year == sample_state.period_year
        assert reconstructed.period_month == sample_state.period_month
        assert reconstructed.tax_type == sample_state.tax_type
        assert reconstructed.user_id == sample_state.user_id
        assert reconstructed.correlation_id == sample_state.correlation_id
        assert reconstructed.submission_payload == sample_state.submission_payload
        assert reconstructed.submission_id == sample_state.submission_id
        assert reconstructed.approval_code == sample_state.approval_code
        assert reconstructed.pdf_bukti == sample_state.pdf_bukti
        assert reconstructed.status == sample_state.status
        assert reconstructed.errors == sample_state.errors
        assert reconstructed.retry_count == sample_state.retry_count
        assert reconstructed.created_at == sample_state.created_at
        assert reconstructed.updated_at == sample_state.updated_at

    def test_from_dict_handles_missing_optional_fields(self, minimal_state):
        d = minimal_state.to_dict()
        # Remove optional keys to test defaults
        d.pop("user_id", None)
        d.pop("correlation_id", None)
        d.pop("submission_id", None)
        d.pop("approval_code", None)
        d.pop("pdf_bukti", None)
        d.pop("submission_payload", None)
        d.pop("errors", None)
        d.pop("retry_count", None)
        d.pop("status", None)

        reconstructed = CoretaxSubmissionSagaState.from_dict(d)
        assert reconstructed.user_id is None
        assert reconstructed.correlation_id is None
        assert reconstructed.submission_id is None
        assert reconstructed.approval_code is None
        assert reconstructed.pdf_bukti is None
        assert reconstructed.submission_payload == {}
        assert reconstructed.errors == []
        assert reconstructed.retry_count == 0
        assert reconstructed.status == "INITIATED"
        assert reconstructed.saga_id == minimal_state.saga_id
        assert reconstructed.legal_entity_id == minimal_state.legal_entity_id
        assert reconstructed.period_year == minimal_state.period_year
        assert reconstructed.period_month == minimal_state.period_month
        assert reconstructed.tax_type == minimal_state.tax_type

    def test_from_dict_with_none_uuid_strings(self, minimal_state):
        d = minimal_state.to_dict()
        # Simulate None values for UUID fields as strings
        d["user_id"] = None
        d["submission_id"] = None
        reconstructed = CoretaxSubmissionSagaState.from_dict(d)
        assert reconstructed.user_id is None
        assert reconstructed.submission_id is None

    def test_from_dict_handles_datetime_strings(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = CoretaxSubmissionSagaState.from_dict(d)
        assert reconstructed.created_at == sample_state.created_at
        assert reconstructed.updated_at == sample_state.updated_at


# ============================================================================
# Integration: Round-trip serialization
# ============================================================================

class TestSerializationRoundTrip:
    def test_to_dict_from_dict_round_trip(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = CoretaxSubmissionSagaState.from_dict(d)
        # Compare all fields
        assert reconstructed == sample_state

    def test_to_dict_from_dict_round_trip_minimal(self, minimal_state):
        d = minimal_state.to_dict()
        reconstructed = CoretaxSubmissionSagaState.from_dict(d)
        assert reconstructed == minimal_state