#!/usr/bin/env python3
"""Unit test untuk immutability axiom."""

from __future__ import annotations

from uuid import uuid4

import pytest

from axioms.immutability import (
    CorrectionMethod,
    DataState,
    ImmutabilityAxiom,
    ImmutabilityViolationError,
    ImmutableRecordType,
    create_immutable_record,
)


class TestImmutabilityAxiom:
    """Test suite untuk ImmutabilityAxiom."""

    @pytest.fixture
    def axiom(self) -> ImmutabilityAxiom:
        """Fresh instance of ImmutabilityAxiom."""
        axiom = ImmutabilityAxiom()
        axiom.reset()  # Clear any previous state
        return axiom

        @pytest.fixture
        def posted_aggregate_id(self, axiom) -> uuid4:
            """Create an aggregate that has been posted (immutable)."""
            aggregate_id = uuid4()
            # Set state directly to POSTED (simulating a posted journal)
            axiom.set_aggregate_state(aggregate_id, DataState.POSTED)
            # Register an immutable record for this aggregate
            record_id = uuid4()
            record = create_immutable_record(
                record_id=record_id,
                record_type=ImmutableRecordType.JOURNAL,
                aggregate_id=aggregate_id,
                version=1,
                data={"description": "Test journal"},
                previous_hash=None,
                created_by="test_user",
                signature="test_signature",
            )
            axiom.register_immutable_record(record, verify_hash_chain=False)
            return aggregate_id

            def test_new_event_passes(self, axiom):
                """Test bahwa data baru (draft) dapat dimodifikasi tanpa error."""
                aggregate_id = uuid4()
                # Initially state is DRAFT (default)
                assert axiom.get_aggregate_state(aggregate_id) == DataState.DRAFT

                # UPDATE operation on DRAFT should be allowed
                is_allowed, violation = axiom.enforce_operation(
                    aggregate_id=aggregate_id,
                    operation="UPDATE",
                    record_id=uuid4(),
                    user_id="test_user",
                    module="test",
                    raise_on_violation=False,
                )
                assert is_allowed is True
                assert violation is None

                # Also can transition from DRAFT to SUBMITTED
                is_valid, violation = axiom.enforce_state_transition(
                    aggregate_id=aggregate_id,
                    from_state=DataState.DRAFT,
                    to_state=DataState.SUBMITTED,
                    record_id=uuid4(),
                    user_id="test_user",
                    module="test",
                    require_approval=False,
                    raise_on_violation=False,
                )
                assert is_valid is True
                assert violation is None

                def test_modifying_existing_event_fails(self, axiom, posted_aggregate_id):
                    """Test bahwa data yang sudah diposting (immutable) tidak dapat dimodifikasi."""
                    # Attempt to UPDATE a posted aggregate
                    is_allowed, violation = axiom.enforce_operation(
                        aggregate_id=posted_aggregate_id,
                        operation="UPDATE",
                        record_id=uuid4(),
                        user_id="test_user",
                        module="test",
                        is_correction=False,
                        raise_on_violation=False,
                    )
                    assert is_allowed is False
                    assert violation is not None
                    assert (
                        "immutable" in violation.message.lower()
                        or "posted" in violation.message.lower()
                    )

                    # Attempt to DELETE a posted aggregate (should also fail)
                    is_allowed, violation = axiom.enforce_operation(
                        aggregate_id=posted_aggregate_id,
                        operation="DELETE",
                        record_id=uuid4(),
                        user_id="test_user",
                        module="test",
                        raise_on_violation=False,
                    )
                    assert is_allowed is False
                    assert violation is not None

                    # Attempt invalid state transition from POSTED to DRAFT (should be catastrophic)
                    is_valid, violation = axiom.enforce_state_transition(
                        aggregate_id=posted_aggregate_id,
                        from_state=DataState.POSTED,
                        to_state=DataState.DRAFT,
                        record_id=uuid4(),
                        user_id="test_user",
                        module="test",
                        require_approval=False,
                        raise_on_violation=False,
                    )
                    assert is_valid is False
                    assert violation is not None
                    assert violation.severity.value >= 80  # CRITICAL or CATASTROPHIC

                    def test_correction_with_authorization(self, axiom, posted_aggregate_id):
                        """Test bahwa koreksi dengan otorisasi diperbolehkan."""
                        original_record_id = uuid4()
                        # Simulate a posted record
                        axiom.set_aggregate_state(posted_aggregate_id, DataState.POSTED)
                        record = create_immutable_record(
                            record_id=original_record_id,
                            record_type=ImmutableRecordType.JOURNAL,
                            aggregate_id=posted_aggregate_id,
                            version=1,
                            data={"amount": 1000},
                            previous_hash=None,
                            created_by="user1",
                            signature="sig",
                        )
                        axiom.register_immutable_record(record, verify_hash_chain=False)

                        # Now perform a reversal (allowed correction)
                        reversal_record_id = uuid4()
                        is_allowed, violation = axiom.enforce_operation(
                            aggregate_id=posted_aggregate_id,
                            operation="REVERSE",
                            record_id=original_record_id,
                            user_id="finance_manager",
                            module="test",
                            is_correction=True,
                            correction_method=CorrectionMethod.REVERSAL_JOURNAL,
                            bypass_authorization=["finance_manager"],
                            raise_on_violation=False,
                        )
                        assert is_allowed is True
                        assert violation is None

                        # Record the correction
                        correction = axiom.record_correction(
                            original_record_id=original_record_id,
                            correction_method=CorrectionMethod.REVERSAL_JOURNAL,
                            correction_record_id=reversal_record_id,
                            reason="Error in amount",
                            authorized_by="finance_manager",
                            approved_by=["finance_manager", "controller"],
                            audit_reference="AUD-2025-001",
                        )
                        assert correction is not None
                        assert correction.original_record_id == original_record_id
                        assert correction.correction_record_id == reversal_record_id

                        # Verify original record is now inactive
                        original = axiom.get_immutable_record(original_record_id)
                        assert original is not None
                        assert original.is_active is False

                        def test_raise_on_violation(self, axiom, posted_aggregate_id):
                            """Test bahwa violation dengan severity tinggi akan raise exception."""
                            with pytest.raises(ImmutabilityViolationError, match="immutable"):
                                axiom.enforce_operation(
                                    aggregate_id=posted_aggregate_id,
                                    operation="UPDATE",
                                    record_id=uuid4(),
                                    user_id="test_user",
                                    module="test",
                                    raise_on_violation=True,
                                )

                                if __name__ == "__main__":
                                    pytest.main([__file__])
