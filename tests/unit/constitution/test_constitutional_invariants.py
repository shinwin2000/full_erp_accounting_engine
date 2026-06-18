#!/usr/bin/env python3
"""Unit test untuk constitutional invariants."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from constitution.constitutional_invariants import (
    InvariantType,
    InvariantViolationError,  # Correct exception from same module
    get_constitutional_invariants_service,
)


class TestConstitutionalInvariants:
    """Test suite untuk ConstitutionalInvariants."""

    def test_invariant_double_entry(self):
        """Test bahwa double entry invariant lulus jika debit = credit."""
        service = get_constitutional_invariants_service()
        context = {
            "total_debit": Decimal("1000"),
            "total_credit": Decimal("1000"),
        }
        is_valid, violation = service.validate(
            invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
            context=context,
        )
        assert is_valid is True
        assert violation is None

        def test_invariant_double_entry_fails(self):
            """Test bahwa double entry invariant gagal jika debit != credit."""
            service = get_constitutional_invariants_service()
            context = {
                "total_debit": Decimal("1000"),
                "total_credit": Decimal("900"),
            }
            is_valid, violation = service.validate(
                invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
                context=context,
            )
            assert is_valid is False
            assert violation is not None
            assert "debit" in violation.message.lower() or "balance" in violation.message.lower()

            # Test CATASTROPHIC invariant (ACCOUNTING_EQUATION) raises exception
            context_eq = {
                "total_assets": Decimal("1000"),
                "total_liabilities": Decimal("500"),
                "total_equity": Decimal("400"),  # not balanced
            }
            with pytest.raises(InvariantViolationError, match="ACCOUNTING_EQUATION"):
                service.validate(
                    invariant_type=InvariantType.ACCOUNTING_EQUATION,
                    context=context_eq,
                )

                def test_invariant_immutability_via_hash_chain(self):
                    """
                    Test immutability menggunakan hash chain consistency.
                    HASH_CHAIN_CONSISTENCY adalah CATASTROPHIC, jadi violation akan raise exception.
                    """
                    service = get_constitutional_invariants_service()
                    content = "test data"
                    # Validator menggunakan hashlib.sha3_256
                    computed = hashlib.sha3_256(content.encode()).hexdigest()
                    context_valid = {
                        "content_to_hash": content,
                        "current_hash": computed,
                    }
                    is_valid, _violation = service.validate(
                        invariant_type=InvariantType.HASH_CHAIN_CONSISTENCY,
                        context=context_valid,
                    )
                    assert is_valid is True

                    # Context dengan hash yang salah (tampering) - raises exception karena CATASTROPHIC
                    context_invalid = {
                        "content_to_hash": content,
                        "current_hash": "wronghash",
                    }
                    with pytest.raises(InvariantViolationError, match="HASH_CHAIN_CONSISTENCY"):
                        service.validate(
                            invariant_type=InvariantType.HASH_CHAIN_CONSISTENCY,
                            context=context_invalid,
                        )

                        if __name__ == "__main__":
                            pytest.main([__file__])
