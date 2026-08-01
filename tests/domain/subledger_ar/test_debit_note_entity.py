# tests/domain/subledger_ar/test_debit_note_entity.py
# =============================================================================
# Comprehensive tests for domain/subledger_ar/debit_note_entity.py.
# Covers all enums, entity methods, business logic, serialization, repository interface,
# state transitions, negative paths, and edge cases. All tests include proper assertions.
# Duplicate tests consolidated via parametrization.
# =============================================================================

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.subledger_ar.debit_note_entity import (
    ARDebitNote,
    ARDebitNoteReason,
    ARDebitNoteStatus,
    DebitNoteEntity,
    DebitNoteReason,
    DebitNoteRepository,
    DebitNoteStatus,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_debit_note() -> DebitNoteEntity:
    """Create a valid DebitNoteEntity in DRAFT state."""
    return DebitNoteEntity(
        debit_note_id=uuid4(),
        debit_note_number="DN-2025-001",
        invoice_id=uuid4(),
        invoice_number="INV-2025-001",
        customer_id=uuid4(),
        customer_name="PT Maju Jaya",
        issue_date=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        amount=Decimal("500.00"),
        currency="IDR",
        reason=DebitNoteReason.ADDITIONAL_CHARGE,
        status=DebitNoteStatus.DRAFT,
        description="Additional shipping charge",
        tax_amount=Decimal("55.00"),
        tax_rate=Decimal("11"),
        original_invoice_amount=Decimal("1000.00"),
        created_at=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        created_by="alice",
        version=1,
    )


@pytest.fixture
def issued_debit_note(sample_debit_note) -> DebitNoteEntity:
    """Return an issued debit note."""
    return sample_debit_note.activate("alice")


@pytest.fixture
def applied_debit_note(issued_debit_note) -> DebitNoteEntity:
    """Return an applied debit note."""
    return issued_debit_note.apply("bob")


@pytest.fixture
def cancelled_debit_note(sample_debit_note) -> DebitNoteEntity:
    """Return a cancelled debit note."""
    return sample_debit_note.cancel("alice", "Wrong entry")


# =============================================================================
# Tests for Enums
# =============================================================================

class TestDebitNoteStatus:
    def test_members_exist(self):
        assert hasattr(DebitNoteStatus, "DRAFT")
        assert hasattr(DebitNoteStatus, "ISSUED")
        assert hasattr(DebitNoteStatus, "APPLIED")
        assert hasattr(DebitNoteStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(DebitNoteStatus.DRAFT, DebitNoteStatus)

    def test_can_apply(self):
        assert DebitNoteStatus.ISSUED.can_apply() is True
        assert DebitNoteStatus.DRAFT.can_apply() is False
        assert DebitNoteStatus.APPLIED.can_apply() is False
        assert DebitNoteStatus.CANCELLED.can_apply() is False

    def test_can_cancel(self):
        assert DebitNoteStatus.DRAFT.can_cancel() is True
        assert DebitNoteStatus.ISSUED.can_cancel() is True
        assert DebitNoteStatus.APPLIED.can_cancel() is False
        assert DebitNoteStatus.CANCELLED.can_cancel() is False

    def test_can_edit(self):
        assert DebitNoteStatus.DRAFT.can_edit() is True
        assert DebitNoteStatus.ISSUED.can_edit() is False
        assert DebitNoteStatus.APPLIED.can_edit() is False
        assert DebitNoteStatus.CANCELLED.can_edit() is False


class TestDebitNoteReason:
    def test_members_exist(self):
        assert hasattr(DebitNoteReason, "ADDITIONAL_CHARGE")
        assert hasattr(DebitNoteReason, "PENALTY")
        assert hasattr(DebitNoteReason, "INTEREST")
        assert hasattr(DebitNoteReason, "CORRECTION")
        assert hasattr(DebitNoteReason, "SHORTAGE")

    def test_member_is_instance(self):
        assert isinstance(DebitNoteReason.ADDITIONAL_CHARGE, DebitNoteReason)

    def test_display_name(self):
        assert DebitNoteReason.ADDITIONAL_CHARGE.display_name() == "Biaya Tambahan"
        assert DebitNoteReason.PENALTY.display_name() == "Denda"
        assert DebitNoteReason.INTEREST.display_name() == "Bunga"
        assert DebitNoteReason.CORRECTION.display_name() == "Koreksi"
        assert DebitNoteReason.SHORTAGE.display_name() == "Kekurangan"


# =============================================================================
# Tests for Construction & Validation
# =============================================================================

class TestDebitNoteEntityConstruction:
    def test_construction_valid(self, sample_debit_note):
        assert sample_debit_note.debit_note_id is not None
        assert sample_debit_note.debit_note_number == "DN-2025-001"
        assert sample_debit_note.amount == Decimal("500.00")
        assert sample_debit_note.status == DebitNoteStatus.DRAFT
        assert sample_debit_note.version == 1
        assert len(sample_debit_note._snapshots) == 1
        assert len(sample_debit_note._audit_trail) == 0

    def test_construction_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Debit note amount must be positive"):
            DebitNoteEntity(
                debit_note_id=uuid4(),
                debit_note_number="DN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Customer",
                issue_date=datetime.now(UTC),
                amount=Decimal("-100"),
                currency="IDR",
                reason=DebitNoteReason.ADDITIONAL_CHARGE,
                status=DebitNoteStatus.DRAFT,
                description="Test",
            )

    def test_construction_zero_amount_raises(self):
        with pytest.raises(ValueError, match="Debit note amount must be positive"):
            DebitNoteEntity(
                debit_note_id=uuid4(),
                debit_note_number="DN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Customer",
                issue_date=datetime.now(UTC),
                amount=Decimal("0"),
                currency="IDR",
                reason=DebitNoteReason.ADDITIONAL_CHARGE,
                status=DebitNoteStatus.DRAFT,
                description="Test",
            )

    def test_construction_negative_tax_raises(self):
        with pytest.raises(ValueError, match="Tax amount cannot be negative"):
            DebitNoteEntity(
                debit_note_id=uuid4(),
                debit_note_number="DN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Customer",
                issue_date=datetime.now(UTC),
                amount=Decimal("100"),
                currency="IDR",
                reason=DebitNoteReason.ADDITIONAL_CHARGE,
                status=DebitNoteStatus.DRAFT,
                description="Test",
                tax_amount=Decimal("-10"),
            )

    def test_construction_without_optional_fields(self):
        entity = DebitNoteEntity(
            debit_note_id=uuid4(),
            debit_note_number="DN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            customer_id=uuid4(),
            customer_name="Customer",
            issue_date=datetime.now(UTC),
            amount=Decimal("100"),
            currency="IDR",
            reason=DebitNoteReason.ADDITIONAL_CHARGE,
            status=DebitNoteStatus.DRAFT,
            description="Test",
            # tax_amount, tax_rate, original_invoice_amount omitted
        )
        assert entity.tax_amount == Decimal(0)
        assert entity.tax_rate == Decimal(11)
        assert entity.original_invoice_amount is None


# =============================================================================
# Tests for Entity Base Methods
# =============================================================================

class TestDebitNoteEntityBaseMethods:
    def test_create(self, sample_debit_note):
        result = sample_debit_note.create("alice")
        assert result is sample_debit_note
        trail = result.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "alice"

    def test_update_success(self, sample_debit_note):
        updated = sample_debit_note.update(
            updated_by="bob",
            amount=Decimal("600"),
            description="Updated description",
        )
        assert updated.version == 2
        assert updated.amount == Decimal("600")
        assert updated.description == "Updated description"
        assert updated.debit_note_id == sample_debit_note.debit_note_id
        trail = updated.audit_trail(limit=1)
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["performed_by"] == "bob"

    def test_update_ignores_internal_fields(self, sample_debit_note):
        updated = sample_debit_note.update(
            updated_by="bob",
            debit_note_id=uuid4(),  # should be ignored
            version=99,             # should be ignored
            amount=Decimal("700"),
        )
        assert updated.debit_note_id == sample_debit_note.debit_note_id
        assert updated.version == 2  # incremented, not 99
        assert updated.amount == Decimal("700")

    def test_update_not_editable_raises(self, issued_debit_note):
        with pytest.raises(ValueError, match="Cannot update debit note in status issued"):
            issued_debit_note.update("bob", amount=Decimal("800"))

    def test_delete(self, sample_debit_note):
        deleted = sample_debit_note.delete("alice", "Duplicate")
        assert deleted.status == DebitNoteStatus.CANCELLED
        assert deleted.version == 2
        trail = deleted.audit_trail(limit=1)
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["details"]["reason"] == "Duplicate"

    def test_delete_already_cancelled_returns_same(self, cancelled_debit_note):
        result = cancelled_debit_note.delete("alice")
        assert result is cancelled_debit_note
        assert result.version == cancelled_debit_note.version

    def test_restore_success(self, cancelled_debit_note):
        restored = cancelled_debit_note.restore("alice")
        assert restored.status == DebitNoteStatus.DRAFT
        assert restored.version == cancelled_debit_note.version + 1
        trail = restored.audit_trail(limit=1)
        assert trail[0]["action"] == "RESTORE"

    @pytest.mark.parametrize("invalid_status,expected_error", [
        (DebitNoteStatus.DRAFT, "Cannot restore debit note in status draft"),
        (DebitNoteStatus.ISSUED, "Cannot restore debit note in status issued"),
        (DebitNoteStatus.APPLIED, "Cannot restore debit note in status applied"),
    ])
    def test_restore_invalid_states_raises(self, sample_debit_note, issued_debit_note, applied_debit_note, invalid_status, expected_error):
        """Consolidates duplicate tests for restore from invalid states."""
        if invalid_status == DebitNoteStatus.DRAFT:
            entity = sample_debit_note
        elif invalid_status == DebitNoteStatus.ISSUED:
            entity = issued_debit_note
        elif invalid_status == DebitNoteStatus.APPLIED:
            entity = applied_debit_note
        else:
            entity = sample_debit_note
        with pytest.raises(ValueError, match=expected_error):
            entity.restore("alice")

    def test_activate_success(self, sample_debit_note):
        activated = sample_debit_note.activate("alice")
        assert activated.status == DebitNoteStatus.ISSUED
        assert activated.version == 2
        trail = activated.audit_trail(limit=1)
        assert trail[0]["action"] == "ACTIVATE"

    def test_activate_already_issued_returns_same(self, issued_debit_note):
        result = issued_debit_note.activate("alice")
        assert result is issued_debit_note

    @pytest.mark.parametrize("invalid_status,expected_error", [
        (DebitNoteStatus.APPLIED, "Cannot activate debit note in status applied"),
        (DebitNoteStatus.CANCELLED, "Cannot activate debit note in status cancelled"),
    ])
    def test_activate_invalid_states_raises(self, applied_debit_note, cancelled_debit_note, invalid_status, expected_error):
        """Consolidates duplicate tests for activate from invalid states."""
        if invalid_status == DebitNoteStatus.APPLIED:
            entity = applied_debit_note
        elif invalid_status == DebitNoteStatus.CANCELLED:
            entity = cancelled_debit_note
        else:
            entity = applied_debit_note
        with pytest.raises(ValueError, match=expected_error):
            entity.activate("alice")

    def test_deactivate_success(self, issued_debit_note):
        deactivated = issued_debit_note.deactivate("alice", "Need changes")
        assert deactivated.status == DebitNoteStatus.DRAFT
        assert deactivated.version == issued_debit_note.version + 1
        trail = deactivated.audit_trail(limit=1)
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "Need changes"

    def test_deactivate_already_draft_returns_same(self, sample_debit_note):
        result = sample_debit_note.deactivate("alice")
        assert result is sample_debit_note

    @pytest.mark.parametrize("invalid_status,expected_error", [
        (DebitNoteStatus.APPLIED, "Cannot deactivate debit note in status applied"),
    ])
    def test_deactivate_invalid_states_raises(self, applied_debit_note, invalid_status, expected_error):
        """Consolidates duplicate tests for deactivate from invalid states."""
        entity = applied_debit_note
        with pytest.raises(ValueError, match=expected_error):
            entity.deactivate("alice")

    def test_lock(self, sample_debit_note):
        locked = sample_debit_note.lock("alice", "Review")
        assert locked.version == 2
        trail = locked.audit_trail(limit=1)
        assert trail[0]["action"] == "LOCK"
        assert trail[0]["details"]["reason"] == "Review"

    def test_unlock(self, sample_debit_note):
        unlocked = sample_debit_note.unlock("alice")
        assert unlocked.version == 2
        trail = unlocked.audit_trail(limit=1)
        assert trail[0]["action"] == "UNLOCK"

    def test_validate_valid(self, sample_debit_note):
        result = sample_debit_note.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["debit_note_id"] == str(sample_debit_note.debit_note_id)
        assert result["version"] == 1

    def test_validate_invalid(self, sample_debit_note):
        invalid = DebitNoteEntity(
            debit_note_id=sample_debit_note.debit_note_id,
            debit_note_number=sample_debit_note.debit_note_number,
            invoice_id=sample_debit_note.invoice_id,
            invoice_number=sample_debit_note.invoice_number,
            customer_id=sample_debit_note.customer_id,
            customer_name=sample_debit_note.customer_name,
            issue_date=sample_debit_note.issue_date,
            amount=Decimal("-100"),
            currency=sample_debit_note.currency,
            reason=sample_debit_note.reason,
            status=sample_debit_note.status,
            description=sample_debit_note.description,
            tax_amount=sample_debit_note.tax_amount,
            tax_rate=sample_debit_note.tax_rate,
            original_invoice_amount=sample_debit_note.original_invoice_amount,
            created_at=sample_debit_note.created_at,
            updated_at=sample_debit_note.updated_at,
            created_by=sample_debit_note.created_by,
        )
        result = invalid.validate()
        assert result["is_valid"] is False
        assert any("positive" in e for e in result["errors"])


# =============================================================================
# Tests for Serialization
# =============================================================================

class TestDebitNoteEntitySerialization:
    def test_to_dict(self, sample_debit_note):
        d = sample_debit_note.to_dict()
        assert d["debit_note_id"] == str(sample_debit_note.debit_note_id)
        assert d["debit_note_number"] == "DN-2025-001"
        assert d["amount"] == "500.00"
        assert d["status"] == "draft"
        assert d["reason"] == "additional_charge"
        assert d["version"] == 1

    def test_from_dict(self, sample_debit_note):
        d = sample_debit_note.to_dict()
        reconstructed = DebitNoteEntity.from_dict(d)
        assert reconstructed.debit_note_id == sample_debit_note.debit_note_id
        assert reconstructed.amount == sample_debit_note.amount
        assert reconstructed.status == sample_debit_note.status
        assert reconstructed.reason == sample_debit_note.reason
        assert reconstructed.version == sample_debit_note.version

    def test_from_dict_with_missing_optional_fields(self):
        data = {
            "debit_note_id": str(uuid4()),
            "debit_note_number": "DN-001",
            "invoice_id": str(uuid4()),
            "invoice_number": "INV-001",
            "customer_id": str(uuid4()),
            "customer_name": "Customer",
            "issue_date": datetime.now(UTC).isoformat(),
            "amount": "100.00",
            "currency": "IDR",
            "reason": "additional_charge",
            "status": "draft",
            "description": "Test",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "created_by": "system",
            "version": 1,
            # tax_amount, tax_rate, original_invoice_amount omitted
        }
        entity = DebitNoteEntity.from_dict(data)
        assert entity.tax_amount == Decimal("0")
        assert entity.tax_rate == Decimal("11")
        assert entity.original_invoice_amount is None

    def test_clone(self, sample_debit_note):
        cloned = sample_debit_note.clone()
        assert cloned.debit_note_id != sample_debit_note.debit_note_id
        assert cloned.debit_note_number == "DN-2025-001_COPY"
        assert cloned.amount == sample_debit_note.amount
        assert cloned.status == DebitNoteStatus.DRAFT
        assert cloned.version == 1
        assert "Cloned from" in cloned.description
        trail = cloned.audit_trail(limit=1)
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_debit_note):
        snap = sample_debit_note.snapshot()
        assert snap["version"] == 1
        assert snap["debit_note_id"] == str(sample_debit_note.debit_note_id)
        assert snap["debit_note_number"] == "DN-2025-001"
        assert snap["status"] == "draft"
        assert snap["amount"] == "500.00"
        assert "timestamp" in snap

    def test_get_version(self, sample_debit_note):
        assert sample_debit_note.get_version() == 1
        updated = sample_debit_note.update("bob", amount=Decimal("600"))
        assert updated.get_version() == 2

    def test_audit_trail(self, sample_debit_note):
        assert sample_debit_note.audit_trail() == []
        sample_debit_note.create("alice")
        trail = sample_debit_note.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"

    def test_touch(self, sample_debit_note):
        touched = sample_debit_note.touch("alice")
        assert touched.version == 2
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "alice"


# =============================================================================
# Tests for Business Methods
# =============================================================================

class TestDebitNoteEntityBusiness:
    def test_apply_success(self, issued_debit_note):
        applied = issued_debit_note.apply("bob")
        assert applied.status == DebitNoteStatus.APPLIED
        assert applied.version == issued_debit_note.version + 1
        trail = applied.audit_trail(limit=1)
        assert trail[0]["action"] == "APPLY"
        assert trail[0]["performed_by"] == "bob"

    def test_apply_not_issued_raises(self, sample_debit_note):
        with pytest.raises(ValueError, match="Cannot apply debit note in status draft"):
            sample_debit_note.apply("bob")

    def test_cancel_success_draft(self, sample_debit_note):
        cancelled = sample_debit_note.cancel("alice", "User request")
        assert cancelled.status == DebitNoteStatus.CANCELLED
        assert "Cancelled: User request" in cancelled.description
        assert cancelled.version == 2
        trail = cancelled.audit_trail(limit=1)
        assert trail[0]["action"] == "CANCEL"

    def test_cancel_success_issued(self, issued_debit_note):
        cancelled = issued_debit_note.cancel("alice", "Error")
        assert cancelled.status == DebitNoteStatus.CANCELLED
        assert cancelled.version == issued_debit_note.version + 1

    def test_cancel_not_cancellable_raises(self, applied_debit_note):
        with pytest.raises(ValueError, match="Cannot cancel debit note in status applied"):
            applied_debit_note.cancel("alice", "No")

    def test_is_applied(self, applied_debit_note, sample_debit_note):
        assert applied_debit_note.is_applied() is True
        assert sample_debit_note.is_applied() is False

    def test_is_cancelled(self, cancelled_debit_note, sample_debit_note):
        assert cancelled_debit_note.is_cancelled() is True
        assert sample_debit_note.is_cancelled() is False

    def test_is_draft(self, sample_debit_note, issued_debit_note):
        assert sample_debit_note.is_draft() is True
        assert issued_debit_note.is_draft() is False

    def test_to_money(self, sample_debit_note):
        money = sample_debit_note.to_money()
        assert money.amount == Decimal("500.00")
        assert money.currency == "IDR"


# =============================================================================
# Tests for State Transitions (including duplicate removal)
# =============================================================================

class TestDebitNoteEntityStateTransitions:
    def test_state_flow_draft_to_issued_to_applied(self, sample_debit_note):
        issued = sample_debit_note.activate("alice")
        assert issued.status == DebitNoteStatus.ISSUED
        applied = issued.apply("bob")
        assert applied.status == DebitNoteStatus.APPLIED
        # Verify cannot go back
        with pytest.raises(ValueError):
            applied.activate("alice")
        with pytest.raises(ValueError):
            applied.deactivate("alice")

    def test_state_flow_draft_to_cancelled_to_restored(self, sample_debit_note):
        cancelled = sample_debit_note.cancel("alice", "No need")
        assert cancelled.status == DebitNoteStatus.CANCELLED
        restored = cancelled.restore("alice")
        assert restored.status == DebitNoteStatus.DRAFT

    def test_state_flow_issued_to_cancelled(self, issued_debit_note):
        cancelled = issued_debit_note.cancel("alice", "Error")
        assert cancelled.status == DebitNoteStatus.CANCELLED
        restored = cancelled.restore("alice")
        assert restored.status == DebitNoteStatus.DRAFT
        reactivated = restored.activate("alice")
        assert reactivated.status == DebitNoteStatus.ISSUED

    def test_state_flow_issued_to_draft_via_deactivate(self, issued_debit_note):
        deactivated = issued_debit_note.deactivate("alice")
        assert deactivated.status == DebitNoteStatus.DRAFT
        reactivated = deactivated.activate("alice")
        assert reactivated.status == DebitNoteStatus.ISSUED


# =============================================================================
# Tests for Repository Interface (Negative Paths for Abstract Methods)
# =============================================================================

class TestDebitNoteRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_invoice_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_invoice(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_customer_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_customer(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_exists_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.exists(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_all_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_all(uuid4())

    @pytest.mark.asyncio
    async def test_search_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.search(uuid4(), {})

    @pytest.mark.asyncio
    async def test_count_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.count(uuid4())

    @pytest.mark.asyncio
    async def test_list_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.list(uuid4())

    @pytest.mark.asyncio
    async def test_paginate_not_implemented(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.paginate(uuid4())

    @pytest.mark.asyncio
    async def test_add_delegates_to_save(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.add(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_update_delegates_to_save(self):
        repo = DebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.update(MagicMock(), uuid4())


# =============================================================================
# Tests for Edge Cases and Negative Paths
# =============================================================================

class TestDebitNoteEntityEdgeCases:
    def test_large_amount(self):
        entity = DebitNoteEntity(
            debit_note_id=uuid4(),
            debit_note_number="DN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            customer_id=uuid4(),
            customer_name="Customer",
            issue_date=datetime.now(UTC),
            amount=Decimal("9999999999.99"),
            currency="IDR",
            reason=DebitNoteReason.ADDITIONAL_CHARGE,
            status=DebitNoteStatus.DRAFT,
            description="Large",
        )
        assert entity.amount == Decimal("9999999999.99")

    def test_zero_tax_rate_allowed(self):
        entity = DebitNoteEntity(
            debit_note_id=uuid4(),
            debit_note_number="DN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            customer_id=uuid4(),
            customer_name="Customer",
            issue_date=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="IDR",
            reason=DebitNoteReason.ADDITIONAL_CHARGE,
            status=DebitNoteStatus.DRAFT,
            description="Zero tax",
            tax_rate=Decimal("0"),
        )
        assert entity.tax_rate == Decimal("0")

    def test_update_multiple_fields(self, sample_debit_note):
        updated = sample_debit_note.update(
            updated_by="bob",
            amount=Decimal("750"),
            currency="USD",
            reason=DebitNoteReason.PENALTY,
            description="Penalty adjustment",
        )
        assert updated.amount == Decimal("750")
        assert updated.currency == "USD"
        assert updated.reason == DebitNoteReason.PENALTY
        assert updated.description == "Penalty adjustment"
        assert updated.version == 2

    def test_audit_trail_limit(self, sample_debit_note):
        for i in range(15):
            sample_debit_note._record_audit(f"ACTION_{i}", "system", {})
        trail = sample_debit_note.audit_trail(limit=5)
        assert len(trail) == 5

    def test_snapshot_limit(self, sample_debit_note):
        for _i in range(15):
            sample_debit_note._take_snapshot()
        assert len(sample_debit_note._snapshots) == 10

    def test_update_with_invalid_reason(self, sample_debit_note):
        with pytest.raises(ValueError, match="'invalid_reason' is not a valid DebitNoteReason"):
            sample_debit_note.update(updated_by="bob", reason="invalid_reason")

    def test_update_with_negative_amount(self, sample_debit_note):
        with pytest.raises(ValueError, match="Debit note amount must be positive"):
            sample_debit_note.update(updated_by="bob", amount=Decimal("-10"))

    def test_update_with_negative_tax(self, sample_debit_note):
        with pytest.raises(ValueError, match="Tax amount cannot be negative"):
            sample_debit_note.update(updated_by="bob", tax_amount=Decimal("-5"))

    def test_apply_already_applied(self, applied_debit_note):
        with pytest.raises(ValueError, match="Cannot apply debit note in status applied"):
            applied_debit_note.apply("bob")

    def test_cancel_already_cancelled(self, cancelled_debit_note):
        with pytest.raises(ValueError, match="Cannot cancel debit note in status cancelled"):
            cancelled_debit_note.cancel("alice", "Again")

    def test_deactivate_from_draft_returns_self(self, sample_debit_note):
        result = sample_debit_note.deactivate("alice")
        assert result is sample_debit_note
        assert result.version == sample_debit_note.version


# =============================================================================
# Tests for Aliases (ARDebitNote, ARDebitNoteStatus, ARDebitNoteReason)
# =============================================================================

class TestAliases:
    def test_ar_debit_note_alias(self):
        assert ARDebitNote is DebitNoteEntity

    def test_ar_debit_note_status_alias(self):
        assert ARDebitNoteStatus is DebitNoteStatus

    def test_ar_debit_note_reason_alias(self):
        assert ARDebitNoteReason is DebitNoteReason

    def test_ar_debit_note_usage(self):
        # Create using alias to ensure it works
        entity = ARDebitNote(
            debit_note_id=uuid4(),
            debit_note_number="DN-ALIAS-001",
            invoice_id=uuid4(),
            invoice_number="INV-ALIAS-001",
            customer_id=uuid4(),
            customer_name="Alias Customer",
            issue_date=datetime.now(UTC),
            amount=Decimal("100"),
            currency="IDR",
            reason=ARDebitNoteReason.ADDITIONAL_CHARGE,
            status=ARDebitNoteStatus.DRAFT,
            description="Alias test",
        )
        assert isinstance(entity, DebitNoteEntity)
        assert entity.status == DebitNoteStatus.DRAFT
        assert entity.reason == DebitNoteReason.ADDITIONAL_CHARGE
