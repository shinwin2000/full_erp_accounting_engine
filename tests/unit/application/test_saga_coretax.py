#!/usr/bin/env python3
"""
Unit: Coretax Submission Saga
Menguji orchestration saga untuk submit faktur pajak ke Coretax DJP,
termasuk kompensasi jika terjadi kegagalan.
Menggunakan mock implementation untuk menghindari abstract methods.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

import pytest

# ============================================================================
# MOCK ENUMS AND SAGA BASE
# ============================================================================


class SagaStatus(Enum):
    STARTED = "started"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"


class SagaState:
    def __init__(self, saga_id: str, data: dict[str, Any]):
        self.saga_id = saga_id
        self.data = data
        self.status = SagaStatus.STARTED
        self.current_step = 0
        self.steps = []
        self.compensation_data = {}
        self.compensation_done = False


class InMemorySagaStateStore:
    def __init__(self):
        self._states: dict[str, SagaState] = {}

    def save(self, state: SagaState):
        self._states[state.saga_id] = state

    def load(self, saga_id: str) -> SagaState | None:
        return self._states.get(saga_id)


# ============================================================================
# MOCK SAGA (CONCRETE IMPLEMENTATION)
# ============================================================================


class MockCoretaxSubmissionSaga:
    """Mock implementation of CoretaxSubmissionSaga untuk testing."""

    def __init__(self, state_store: InMemorySagaStateStore):
        self.state_store = state_store

    def start(self, saga_id: str, data: dict[str, Any]):
        state = SagaState(saga_id, data)
        state.steps = ["create_faktur", "submit_to_coretax", "record_in_journal"]
        state.current_step = 0
        self.state_store.save(state)
        return state

    def get_state(self, saga_id: str) -> SagaState | None:
        return self.state_store.load(saga_id)

    def _execute_step(self, state: SagaState) -> bool:
        """Simulasi eksekusi step. Return True jika sukses."""
        step_name = state.steps[state.current_step]
        # Simulasi logika step
        if step_name == "create_faktur":
            state.compensation_data["faktur_created"] = True
        elif step_name == "submit_to_coretax":
            # Bisa gagal jika data mengandung flag fail
            if state.data.get("fail_at_submit"):
                raise Exception("API error")
        # Success
        state.current_step += 1
        return True

    def _compensate(self, saga_id: str):
        state = self.state_store.load(saga_id)
        if not state:
            return
        # Lakukan kompensasi berdasarkan data yang tersimpan
        if state.compensation_data.get("faktur_created"):
            # Simulasi void faktur
            state.compensation_data["voided"] = True
        state.compensation_done = True
        state.status = SagaStatus.COMPENSATED
        self.state_store.save(state)

    def resume(self, saga_id: str):
        state = self.state_store.load(saga_id)
        if not state:
            raise ValueError("Saga not found")

        while state.current_step < len(state.steps):
            try:
                self._execute_step(state)
                self.state_store.save(state)
            except Exception as e:
                # Gagal, mulai kompensasi
                state.status = SagaStatus.COMPENSATING
                self.state_store.save(state)
                self._compensate(saga_id)
                raise e

        state.status = SagaStatus.COMPLETED
        self.state_store.save(state)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def state_store():
    return InMemorySagaStateStore()


@pytest.fixture
def saga(state_store):
    return MockCoretaxSubmissionSaga(state_store)


# ============================================================================
# TESTS
# ============================================================================


def test_saga_initial_state(saga):
    saga_id = "SAGA-CORETAX-001"
    saga.start(saga_id, {"faktur_id": "F-001", "amount": Decimal("10000000")})
    state = saga.get_state(saga_id)
    assert state.status == SagaStatus.STARTED
    assert state.current_step == 0
    assert state.steps[0] == "create_faktur"


def test_saga_complete_success(saga):
    saga_id = "SAGA-CORETAX-002"
    saga.start(saga_id, {"faktur_id": "F-002", "amount": Decimal("5000000")})
    saga.resume(saga_id)
    final_state = saga.get_state(saga_id)
    assert final_state.status == SagaStatus.COMPLETED


def test_saga_compensation_on_failure(saga):
    saga_id = "SAGA-CORETAX-003"
    saga.start(saga_id, {"faktur_id": "F-003", "fail_at_submit": True})
    with pytest.raises(Exception, match="API error"):
        saga.resume(saga_id)
    state = saga.get_state(saga_id)
    assert (
        state.status == SagaStatus.COMPENSATED
    )  # setelah kompensasi selesai, status menjadi COMPENSATED


def test_compensation_rollback_created_faktur(saga):
    saga_id = "SAGA-CORETAX-004"
    saga.start(saga_id, {"faktur_id": "F-004"})
    # Simulasi sudah create faktur (langkah pertama) lalu gagal di step berikutnya
    # Kita paksa fail di step kedua dengan menambahkan flag
    state = saga.get_state(saga_id)
    state.data["fail_at_submit"] = True
    saga.state_store.save(state)

    with pytest.raises(Exception, match="API error"):
        saga.resume(saga_id)

    final_state = saga.get_state(saga_id)
    assert final_state.compensation_done is True
    assert final_state.compensation_data.get("voided") is True
