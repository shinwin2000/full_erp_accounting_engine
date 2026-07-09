#!/usr/bin/env python3
"""
Unit: Payroll Processing Saga
Menguji saga untuk memproses payroll bulanan: hitung gaji, potong PPh 21, buat jurnal, transfer bank.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# --------------------------------------------------------------------------
# Patch modul yang bermasalah SEBELUM import PayrollSaga
# --------------------------------------------------------------------------
mock_coretax_port = MagicMock()
mock_coretax_port.CoreTaxPort = MagicMock()
sys.modules["ports.primary.tax_authority_coretax_port"] = mock_coretax_port

# Sekarang import aman
from application.sagas.payroll_saga import PayrollSaga


# ============================================================================
# In-Memory State Store (helper untuk test)
# ============================================================================
class InMemorySagaStateStore:
    """Simple in-memory store for saga states."""

    def __init__(self):
        self._states = {}

    def save(self, saga_id: str, state: dict) -> None:
        self._states[saga_id] = state

    def load(self, saga_id: str) -> dict | None:
        return self._states.get(saga_id)


# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def state_store():
    return InMemorySagaStateStore()


@pytest.fixture
def saga(state_store):
    return PayrollSaga(state_store)


# ============================================================================
# Test Cases
# ============================================================================
def test_payroll_saga_start(saga):
    """Saga dapat dimulai dengan data yang benar."""
    saga_id = "SAGA-PAYROLL-2026-05"
    data = {
        "period": date(2026, 5, 31),
        "employee_ids": ["EMP-001", "EMP-002"],
        "total_gross": Decimal("20000000"),
    }
    saga.start(saga_id, data)
    state = saga.get_state(saga_id)

    assert state.status == "STARTED"
    assert state.current_step == "calculate_salary"


def test_payroll_saga_complete_success(saga):
    """Saga selesai dengan sukses jika semua langkah berhasil."""
    saga_id = "SAGA-PAYROLL-002"
    saga.start(saga_id, {"period": date(2026, 5, 31)})

    with (
        patch.object(saga, "_step_calculate_salary", return_value=True),
        patch.object(saga, "_step_calculate_tax", return_value=True),
        patch.object(saga, "_step_create_journal", return_value=True),
        patch.object(saga, "_step_bank_transfer", return_value=True),
    ):
        saga.resume(saga_id)
        final_state = saga.get_state(saga_id)
        assert final_state.status == "COMPLETED"


def test_payroll_saga_compensation_on_bank_failure(saga):
    """Jika langkah bank gagal, saga harus masuk ke mode kompensasi."""
    saga_id = "SAGA-PAYROLL-003"
    saga.start(saga_id, {"period": date(2026, 5, 31)})

    with (
        patch.object(saga, "_step_calculate_salary", return_value=True),
        patch.object(saga, "_step_calculate_tax", return_value=True),
        patch.object(saga, "_step_create_journal", return_value=True),
        patch.object(saga, "_step_bank_transfer", side_effect=Exception("Bank offline")),
    ):
        # Asumsikan saga.resume akan melempar exception atau menangani internal
        # Di sini kita tangkap exception agar test tidak berhenti
        with pytest.raises(Exception):
            saga.resume(saga_id)

        state = saga.get_state(saga_id)
        assert state.status == "COMPENSATING"
        # Pastikan kompensasi membatalkan jurnal
        assert state.compensation_data.get("journal_reversed") is True


# Jika dijalankan langsung
if __name__ == "__main__":
    pytest.main([__file__])