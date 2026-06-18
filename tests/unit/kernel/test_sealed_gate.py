#!/usr/bin/env python3
"""
Module: test_sealed_gate.py
Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk sealed gate (enforcement of constitutional invariants).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest

from kernel.sealed_gate import GateViolationError, SealedGate


class TestSealedGate:
    @pytest.fixture
    def gate(self):
        return SealedGate()

    def test_gate_allows_authorized_command(self, gate):
        command = {"type": "POST_JOURNAL", "user": "admin", "amount": Decimal("1000")}
        # Tidak ada error jika command diizinkan
        gate.enforce(command)  # should not raise

    def test_gate_blocks_mutation_of_immutable_data(self, gate):
        # Coba ubah data yang immutable
        immutable_record = {"id": 1, "hash": "abc123", "data": "original"}
        with pytest.raises(GateViolationError, match="immutable"):
            gate.enforce_mutation(immutable_record)

    def test_gate_requires_dual_control_for_sensitive_action(self, gate):
        context = {"action": "CLOSE_PERIOD", "approvals": [{"approver": "user1"}]}
        with pytest.raises(GateViolationError, match="dual control"):
            gate.enforce_sensitive_action(context)

    def test_gate_requires_evidence_for_write_off(self, gate):
        context = {"action": "WRITE_OFF", "attachments": []}
        with pytest.raises(GateViolationError, match="evidence"):
            gate.enforce_write_off(context)

    def test_gate_allows_write_off_with_evidence(self, gate):
        context = {"action": "WRITE_OFF", "attachments": ["doc.pdf"]}
        gate.enforce_write_off(context)  # should not raise

    def test_gate_prevents_retroactive_period_change(self, gate):
        context = {"period": "2024-12", "current_period": "2025-03", "action": "CHANGE"}
        with pytest.raises(GateViolationError, match="retroactive"):
            gate.enforce_period_change(context)

    def test_gate_requires_hash_chain_verification(self, gate):
        gate.set_hash_chain_verifier(Mock(return_value=False))
        context = {"event_id": 123}
        with pytest.raises(GateViolationError, match="hash chain"):
            gate.enforce_integrity(context)


if __name__ == "__main__":
    pytest.main([__file__])
