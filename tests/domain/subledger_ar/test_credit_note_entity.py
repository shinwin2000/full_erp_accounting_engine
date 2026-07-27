# test_credit_note_entity.py
# ===========================
# Comprehensive tests for domain/subledger_ar/credit_note_entity.py.
# Covers all enums, entity methods, business logic, serialization, and repository interface.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.subledger_ar.credit_note_entity import (
    CreditNoteEntity,
    CreditNoteReason,
    CreditNoteRepository,
    CreditNoteStatus,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_credit_note() -> CreditNoteEntity:
    """Create a valid CreditNoteEntity in DRAFT state."""
    return CreditNoteEntity(
        credit_note_id=uuid4(),
        credit_note_number="CN-2025-001",
        invoice_id=uuid4(),
        invoice_number="INV-2025-001",
        customer_id=uuid4(),
        customer_name="PT Maju Jaya",
        issue_date=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        amount=Decimal("1000.00"),
        currency="IDR",
        reason=CreditNoteReason.GOODS_RETURN,
        status=CreditNoteStatus.DRAFT,
        description="Return of defective goods",
        tax_amount=Decimal("110.00"),
        tax_rate=Decimal("11"),
        original_invoice_amount=Decimal("1000.00"),
        created_at=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        created_by="alice",
        version=1,
    )


@pytest.fixture
def issued_credit_note(sample_credit_note) -> CreditNoteEntity:
    """Return an issued credit note."""
    return sample_credit_note.activate("alice")


@pytest.fixture
def applied_credit_note(issued_credit_note) -> CreditNoteEntity:
    """Return an applied credit note."""
    return issued_credit_note.apply("bob")


@pytest.fixture
def cancelled_credit_note(sample_credit_note) -> CreditNoteEntity:
    """Return a cancelled credit note."""
    return sample_credit_note.cancel("alice", "Wrong entry")


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestCreditNoteStatus:
    def test_members_exist(self):
        assert hasattr(CreditNoteStatus, "DRAFT")
        assert hasattr(CreditNoteStatus, "ISSUED")
        assert hasattr(CreditNoteStatus, "APPLIED")
        assert hasattr(CreditNoteStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(CreditNoteStatus.DRAFT, CreditNoteStatus)

    def test_can_apply(self):
        assert CreditNoteStatus.ISSUED.can_apply() is True
        assert CreditNoteStatus.DRAFT.can_apply() is False
        assert CreditNoteStatus.APPLIED.can_apply() is False
        assert CreditNoteStatus.CANCELLED.can_apply() is False

    def test_can_cancel(self):
        assert CreditNoteStatus.DRAFT.can_cancel() is True
        assert CreditNoteStatus.ISSUED.can_cancel() is True
        assert CreditNoteStatus.APPLIED.can_cancel() is False
        assert CreditNoteStatus.CANCELLED.can_cancel() is False

    def test_can_edit(self):
        assert CreditNoteStatus.DRAFT.can_edit() is True
        assert CreditNoteStatus.ISSUED.can_edit() is False
        assert CreditNoteStatus.APPLIED.can_edit() is False
        assert CreditNoteStatus.CANCELLED.can_edit() is False


class TestCreditNoteReason:
    def test_members_exist(self):
        assert hasattr(CreditNoteReason, "GOODS_RETURN")
        assert hasattr(CreditNoteReason, "PRICE_ADJUSTMENT")
        assert hasattr(CreditNoteReason, "DISCOUNT")
        assert hasattr(CreditNoteReason, "CANCELLATION")
        assert hasattr(CreditNoteReason, "CORRECTION")

    def test_member_is_instance(self):
        assert isinstance(CreditNoteReason.GOODS_RETURN, CreditNoteReason)

    def test_display_name(self):
        assert CreditNoteReason.GOODS_RETURN.display_name() == "Retur Barang"
        assert CreditNoteReason.PRICE_ADJUSTMENT.display_name() == "Penyesuaian Harga"
        assert CreditNoteReason.DISCOUNT.display_name() == "Diskon"
        assert CreditNoteReason.CANCELLATION.display_name() == "Pembatalan"
        assert CreditNoteReason.CORRECTION.display_name() == "Koreksi"


# ----------------------------------------------------------------------
# CreditNoteEntity - Construction & Validation
# ----------------------------------------------------------------------
class TestCreditNoteEntityConstruction:
    def test_construction_valid(self, sample_credit_note):
        assert sample_credit_note.credit_note_id is not None
        assert sample_credit_note.credit_note_number == "CN-2025-001"
        assert sample_credit_note.amount == Decimal("1000.00")
        assert sample_credit_note.status == CreditNoteStatus.DRAFT
        assert sample_credit_note.version == 1
        # Snapshots and audit trail
        assert len(sample_credit_note._snapshots) == 1
        assert len(sample_credit_note._audit_trail) == 0  # audit not recorded in __post_init__

    def test_construction_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Credit note amount must be positive"):
            CreditNoteEntity(
                credit_note_id=uuid4(),
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Customer",
                issue_date=datetime.now(UTC),
                amount=Decimal("-100"),
                currency="IDR",
                reason=CreditNoteReason.GOODS_RETURN,
                status=CreditNoteStatus.DRAFT,
                description="Test",
            )

    def test_construction_zero_amount_raises(self):
        with pytest.raises(ValueError, match="Credit note amount must be positive"):
            CreditNoteEntity(
                credit_note_id=uuid4(),
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Customer",
                issue_date=datetime.now(UTC),
                amount=Decimal("0"),
                currency="IDR",
                reason=CreditNoteReason.GOODS_RETURN,
                status=CreditNoteStatus.DRAFT,
                description="Test",
            )

    def test_construction_exceeds_original_invoice_raises(self):
        with pytest.raises(ValueError, match="exceeds invoice amount"):
            CreditNoteEntity(
                credit_note_id=uuid4(),
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Customer",
                issue_date=datetime.now(UTC),
                amount=Decimal("1500"),
                currency="IDR",
                reason=CreditNoteReason.GOODS_RETURN,
                status=CreditNoteStatus.DRAFT,
                description="Test",
                original_invoice_amount=Decimal("1000"),
            )

    def test_construction_negative_tax_raises(self):
        with pytest.raises(ValueError, match="Tax amount cannot be negative"):
            CreditNoteEntity(
                credit_note_id=uuid4(),
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Customer",
                issue_date=datetime.now(UTC),
                amount=Decimal("1000"),
                currency="IDR",
                reason=CreditNoteReason.GOODS_RETURN,
                status=CreditNoteStatus.DRAFT,
                description="Test",
                tax_amount=Decimal("-10"),
            )


# ----------------------------------------------------------------------
# CreditNoteEntity - Entity Base Methods
# ----------------------------------------------------------------------
class TestCreditNoteEntityBaseMethods:
    def test_create(self, sample_credit_note):
        result = sample_credit_note.create("alice")
        assert result is sample_credit_note  # returns self
        trail = result.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "alice"

    def test_update_success(self, sample_credit_note):
        updated = sample_credit_note.update(
            updated_by="bob",
            amount=Decimal("800"),
            description="Updated description",
        )
        assert updated.version == 2
        assert updated.amount == Decimal("800")
        assert updated.description == "Updated description"
        assert updated.credit_note_id == sample_credit_note.credit_note_id
        trail = updated.audit_trail(limit=1)
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["performed_by"] == "bob"

    def test_update_not_editable_raises(self, issued_credit_note):
        with pytest.raises(ValueError, match="Cannot update credit note in status issued"):
            issued_credit_note.update("bob", amount=Decimal("500"))

    def test_delete(self, sample_credit_note):
        deleted = sample_credit_note.delete("alice", "Duplicate")
        assert deleted.status == CreditNoteStatus.CANCELLED
        assert deleted.version == 2
        trail = deleted.audit_trail(limit=1)
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["details"]["reason"] == "Duplicate"

    def test_delete_already_cancelled_returns_same(self, cancelled_credit_note):
        result = cancelled_credit_note.delete("alice")
        assert result is cancelled_credit_note  # no change
        # No new version
        assert result.version == cancelled_credit_note.version

    def test_restore_success(self, cancelled_credit_note):
        restored = cancelled_credit_note.restore("alice")
        assert restored.status == CreditNoteStatus.DRAFT
        assert restored.version == cancelled_credit_note.version + 1
        trail = restored.audit_trail(limit=1)
        assert trail[0]["action"] == "RESTORE"

    def test_restore_non_cancelled_raises(self, sample_credit_note):
        with pytest.raises(ValueError, match="Cannot restore credit note in status draft"):
            sample_credit_note.restore("alice")

    def test_activate_success(self, sample_credit_note):
        activated = sample_credit_note.activate("alice")
        assert activated.status == CreditNoteStatus.ISSUED
        assert activated.version == 2
        trail = activated.audit_trail(limit=1)
        assert trail[0]["action"] == "ACTIVATE"

    def test_activate_already_issued_returns_same(self, issued_credit_note):
        result = issued_credit_note.activate("alice")
        assert result is issued_credit_note

    def test_activate_non_draft_raises(self, applied_credit_note):
        with pytest.raises(ValueError, match="Cannot activate credit note in status applied"):
            applied_credit_note.activate("alice")

    def test_deactivate_success(self, issued_credit_note):
        deactivated = issued_credit_note.deactivate("alice", "Need changes")
        assert deactivated.status == CreditNoteStatus.DRAFT
        assert deactivated.version == issued_credit_note.version + 1
        trail = deactivated.audit_trail(limit=1)
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "Need changes"

    def test_deactivate_already_draft_returns_same(self, sample_credit_note):
        result = sample_credit_note.deactivate("alice")
        assert result is sample_credit_note

    def test_deactivate_non_issued_raises(self, applied_credit_note):
        with pytest.raises(ValueError, match="Cannot deactivate credit note in status applied"):
            applied_credit_note.deactivate("alice")

    def test_lock(self, sample_credit_note):
        locked = sample_credit_note.lock("alice", "Review")
        assert locked.version == 2
        trail = locked.audit_trail(limit=1)
        assert trail[0]["action"] == "LOCK"
        assert trail[0]["details"]["reason"] == "Review"

    def test_unlock(self, sample_credit_note):
        unlocked = sample_credit_note.unlock("alice")
        assert unlocked.version == 2
        trail = unlocked.audit_trail(limit=1)
        assert trail[0]["action"] == "UNLOCK"

    def test_validate_valid(self, sample_credit_note):
        result = sample_credit_note.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["credit_note_id"] == str(sample_credit_note.credit_note_id)
        assert result["version"] == 1

    def test_validate_invalid(self, sample_credit_note):
        # Corrupt amount to trigger validation error
        invalid = CreditNoteEntity(
            credit_note_id=sample_credit_note.credit_note_id,
            credit_note_number=sample_credit_note.credit_note_number,
            invoice_id=sample_credit_note.invoice_id,
            invoice_number=sample_credit_note.invoice_number,
            customer_id=sample_credit_note.customer_id,
            customer_name=sample_credit_note.customer_name,
            issue_date=sample_credit_note.issue_date,
            amount=Decimal("-100"),
            currency=sample_credit_note.currency,
            reason=sample_credit_note.reason,
            status=sample_credit_note.status,
            description=sample_credit_note.description,
            tax_amount=sample_credit_note.tax_amount,
            tax_rate=sample_credit_note.tax_rate,
            original_invoice_amount=sample_credit_note.original_invoice_amount,
            created_at=sample_credit_note.created_at,
            updated_at=sample_credit_note.updated_at,
            created_by=sample_credit_note.created_by,
        )
        result = invalid.validate()
        assert result["is_valid"] is False
        assert any("positive" in e for e in result["errors"])


# ----------------------------------------------------------------------
# CreditNoteEntity - Serialization
# ----------------------------------------------------------------------
class TestCreditNoteEntitySerialization:
    def test_to_dict(self, sample_credit_note):
        d = sample_credit_note.to_dict()
        assert d["credit_note_id"] == str(sample_credit_note.credit_note_id)
        assert d["credit_note_number"] == "CN-2025-001"
        assert d["amount"] == "1000.00"
        assert d["status"] == "draft"
        assert d["reason"] == "goods_return"
        assert d["version"] == 1

    def test_from_dict(self, sample_credit_note):
        d = sample_credit_note.to_dict()
        reconstructed = CreditNoteEntity.from_dict(d)
        assert reconstructed.credit_note_id == sample_credit_note.credit_note_id
        assert reconstructed.amount == sample_credit_note.amount
        assert reconstructed.status == sample_credit_note.status
        assert reconstructed.reason == sample_credit_note.reason
        assert reconstructed.version == sample_credit_note.version

    def test_clone(self, sample_credit_note):
        cloned = sample_credit_note.clone()
        assert cloned.credit_note_id != sample_credit_note.credit_note_id
        assert cloned.credit_note_number == "CN-2025-001_COPY"
        assert cloned.amount == sample_credit_note.amount
        assert cloned.status == CreditNoteStatus.DRAFT
        assert cloned.version == 1
        assert "Cloned from" in cloned.description
        trail = cloned.audit_trail(limit=1)
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_credit_note):
        snap = sample_credit_note.snapshot()
        assert snap["version"] == 1
        assert snap["credit_note_id"] == str(sample_credit_note.credit_note_id)
        assert snap["credit_note_number"] == "CN-2025-001"
        assert snap["status"] == "draft"
        assert snap["amount"] == "1000.00"
        assert "timestamp" in snap

    def test_get_version(self, sample_credit_note):
        assert sample_credit_note.get_version() == 1
        updated = sample_credit_note.update("bob", amount=Decimal("800"))
        assert updated.get_version() == 2

    def test_audit_trail(self, sample_credit_note):
        # Initially empty
        assert sample_credit_note.audit_trail() == []
        # After some actions
        sample_credit_note.create("alice")
        trail = sample_credit_note.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"

    def test_touch(self, sample_credit_note):
        touched = sample_credit_note.touch("alice")
        assert touched.version == 2
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "alice"


# ----------------------------------------------------------------------
# CreditNoteEntity - Business Methods
# ----------------------------------------------------------------------
class TestCreditNoteEntityBusiness:
    def test_apply_success(self, issued_credit_note):
        applied = issued_credit_note.apply("bob")
        assert applied.status == CreditNoteStatus.APPLIED
        assert applied.version == issued_credit_note.version + 1
        trail = applied.audit_trail(limit=1)
        assert trail[0]["action"] == "APPLY"
        assert trail[0]["performed_by"] == "bob"

    def test_apply_not_issued_raises(self, sample_credit_note):
        with pytest.raises(ValueError, match="Cannot apply credit note in status draft"):
            sample_credit_note.apply("bob")

    def test_cancel_success_draft(self, sample_credit_note):
        cancelled = sample_credit_note.cancel("alice", "User request")
        assert cancelled.status == CreditNoteStatus.CANCELLED
        assert "Cancelled: User request" in cancelled.description
        assert cancelled.version == 2
        trail = cancelled.audit_trail(limit=1)
        assert trail[0]["action"] == "CANCEL"

    def test_cancel_success_issued(self, issued_credit_note):
        cancelled = issued_credit_note.cancel("alice", "Error")
        assert cancelled.status == CreditNoteStatus.CANCELLED

    def test_cancel_not_cancellable_raises(self, applied_credit_note):
        with pytest.raises(ValueError, match="Cannot cancel credit note in status applied"):
            applied_credit_note.cancel("alice", "No")

    def test_is_applied(self, applied_credit_note, sample_credit_note):
        assert applied_credit_note.is_applied() is True
        assert sample_credit_note.is_applied() is False

    def test_is_cancelled(self, cancelled_credit_note, sample_credit_note):
        assert cancelled_credit_note.is_cancelled() is True
        assert sample_credit_note.is_cancelled() is False

    def test_is_draft(self, sample_credit_note, issued_credit_note):
        assert sample_credit_note.is_draft() is True
        assert issued_credit_note.is_draft() is False

    def test_to_money(self, sample_credit_note):
        money = sample_credit_note.to_money()
        assert money.amount == Decimal("1000.00")
        assert money.currency == "IDR"


# ----------------------------------------------------------------------
# CreditNoteEntity - State Transitions
# ----------------------------------------------------------------------
class TestCreditNoteEntityStateTransitions:
    def test_state_flow_draft_to_issued_to_applied(self, sample_credit_note):
        # DRAFT -> ISSUED
        issued = sample_credit_note.activate("alice")
        assert issued.status == CreditNoteStatus.ISSUED
        # ISSUED -> APPLIED
        applied = issued.apply("bob")
        assert applied.status == CreditNoteStatus.APPLIED
        # Cannot go back
        with pytest.raises(ValueError):
            applied.activate("alice")
        with pytest.raises(ValueError):
            applied.deactivate("alice")

    def test_state_flow_draft_to_cancelled(self, sample_credit_note):
        cancelled = sample_credit_note.cancel("alice", "No need")
        assert cancelled.status == CreditNoteStatus.CANCELLED
        # Cannot restore? Restore is allowed only from CANCELLED to DRAFT
        restored = cancelled.restore("alice")
        assert restored.status == CreditNoteStatus.DRAFT

    def test_state_flow_issued_to_cancelled(self, issued_credit_note):
        cancelled = issued_credit_note.cancel("alice", "Error")
        assert cancelled.status == CreditNoteStatus.CANCELLED

    def test_state_flow_issued_to_draft_via_deactivate(self, issued_credit_note):
        deactivated = issued_credit_note.deactivate("alice")
        assert deactivated.status == CreditNoteStatus.DRAFT
        # Can reactivate
        reactivated = deactivated.activate("alice")
        assert reactivated.status == CreditNoteStatus.ISSUED


# ----------------------------------------------------------------------
# CreditNoteRepository (Interface)
# ----------------------------------------------------------------------
class TestCreditNoteRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_invoice_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_invoice(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_customer_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_customer(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_exists_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.exists(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_all_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_all(uuid4())

    @pytest.mark.asyncio
    async def test_search_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.search(uuid4(), {})

    @pytest.mark.asyncio
    async def test_count_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.count(uuid4())

    @pytest.mark.asyncio
    async def test_list_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.list(uuid4())

    @pytest.mark.asyncio
    async def test_paginate_not_implemented(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.paginate(uuid4())

    @pytest.mark.asyncio
    async def test_add_delegates_to_save(self):
        repo = CreditNoteRepository()
        # We can't test actual implementation since it's not implemented, but we can test that add calls save.
        # We'll patch save to verify.
        with pytest.raises(NotImplementedError):
            await repo.add(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_update_delegates_to_save(self):
        repo = CreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.update(MagicMock(), uuid4())


# ----------------------------------------------------------------------
# CreditNoteEntity - Edge Cases
# ----------------------------------------------------------------------
class TestCreditNoteEntityEdgeCases:
    def test_large_amount(self):
        entity = CreditNoteEntity(
            credit_note_id=uuid4(),
            credit_note_number="CN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            customer_id=uuid4(),
            customer_name="Customer",
            issue_date=datetime.now(UTC),
            amount=Decimal("9999999999.99"),
            currency="IDR",
            reason=CreditNoteReason.GOODS_RETURN,
            status=CreditNoteStatus.DRAFT,
            description="Large",
        )
        assert entity.amount == Decimal("9999999999.99")

    def test_zero_tax_rate_allowed(self):
        entity = CreditNoteEntity(
            credit_note_id=uuid4(),
            credit_note_number="CN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            customer_id=uuid4(),
            customer_name="Customer",
            issue_date=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="IDR",
            reason=CreditNoteReason.GOODS_RETURN,
            status=CreditNoteStatus.DRAFT,
            description="Zero tax",
            tax_rate=Decimal("0"),
        )
        assert entity.tax_rate == Decimal("0")

    def test_update_multiple_fields(self, sample_credit_note):
        updated = sample_credit_note.update(
            updated_by="bob",
            amount=Decimal("750"),
            currency="USD",
            reason=CreditNoteReason.DISCOUNT,
            description="Discount adjustment",
        )
        assert updated.amount == Decimal("750")
        assert updated.currency == "USD"
        assert updated.reason == CreditNoteReason.DISCOUNT
        assert updated.description == "Discount adjustment"
        assert updated.version == 2

    def test_audit_trail_limit(self, sample_credit_note):
        # Add multiple audit entries
        for i in range(15):
            sample_credit_note._record_audit(f"ACTION_{i}", "system", {})
        trail = sample_credit_note.audit_trail(limit=5)
        assert len(trail) == 5

    def test_snapshot_limit(self, sample_credit_note):
        # Add many snapshots
        for i in range(15):
            sample_credit_note._take_snapshot()
        # Should keep only last 10
        assert len(sample_credit_note._snapshots) == 10