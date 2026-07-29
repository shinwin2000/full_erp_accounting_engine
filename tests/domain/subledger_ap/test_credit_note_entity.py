# test_credit_note_entity.py
# ===========================
# Comprehensive tests for domain/subledger_ap/credit_note_entity.py.
# Covers all enums, entity methods, audit trail, state transitions, and serialization.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.subledger_ap.credit_note_entity import (
    APCreditNote,
    APCreditNoteEntity,
    APCreditNoteReason,
    APCreditNoteRepository,
    APCreditNoteStatus,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_credit_note() -> APCreditNoteEntity:
    """Create a valid APCreditNoteEntity in DRAFT state."""
    now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    return APCreditNoteEntity.create(
        credit_note_number="CN-001",
        invoice_id=uuid4(),
        invoice_number="INV-001",
        vendor_id=uuid4(),
        vendor_name="PT Supplier",
        issue_date=now,
        amount=Decimal("200.00"),
        currency="IDR",
        reason=APCreditNoteReason.GOODS_RETURN,
        created_by="tester",
        description="Return of defective goods",
        tax_amount=Decimal("22.00"),
        original_invoice_amount=Decimal("1000.00"),
    )


# ----------------------------------------------------------------------
# APCreditNoteStatus Enum
# ----------------------------------------------------------------------
class TestAPCreditNoteStatus:
    def test_members_exist(self):
        assert hasattr(APCreditNoteStatus, "DRAFT")
        assert hasattr(APCreditNoteStatus, "RECEIVED")
        assert hasattr(APCreditNoteStatus, "APPLIED")
        assert hasattr(APCreditNoteStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(APCreditNoteStatus.DRAFT, APCreditNoteStatus)

    def test_from_string_valid(self):
        assert APCreditNoteStatus.from_string("draft") == APCreditNoteStatus.DRAFT
        assert APCreditNoteStatus.from_string("DRAFT") == APCreditNoteStatus.DRAFT
        assert APCreditNoteStatus.from_string("received") == APCreditNoteStatus.RECEIVED
        assert APCreditNoteStatus.from_string("applied") == APCreditNoteStatus.APPLIED
        assert APCreditNoteStatus.from_string("cancelled") == APCreditNoteStatus.CANCELLED

    def test_from_string_invalid_defaults_draft(self):
        assert APCreditNoteStatus.from_string("unknown") == APCreditNoteStatus.DRAFT
        assert APCreditNoteStatus.from_string("") == APCreditNoteStatus.DRAFT


# ----------------------------------------------------------------------
# APCreditNoteReason Enum
# ----------------------------------------------------------------------
class TestAPCreditNoteReason:
    def test_members_exist(self):
        assert hasattr(APCreditNoteReason, "GOODS_RETURN")
        assert hasattr(APCreditNoteReason, "PRICE_ADJUSTMENT")
        assert hasattr(APCreditNoteReason, "DISCOUNT")
        assert hasattr(APCreditNoteReason, "CANCELLATION")
        assert hasattr(APCreditNoteReason, "CORRECTION")
        assert hasattr(APCreditNoteReason, "QUALITY_ISSUE")

    def test_member_is_instance(self):
        assert isinstance(APCreditNoteReason.GOODS_RETURN, APCreditNoteReason)

    def test_from_string_valid(self):
        assert APCreditNoteReason.from_string("goods_return") == APCreditNoteReason.GOODS_RETURN
        assert APCreditNoteReason.from_string("GOODS_RETURN") == APCreditNoteReason.GOODS_RETURN
        assert APCreditNoteReason.from_string("price_adjustment") == APCreditNoteReason.PRICE_ADJUSTMENT
        assert APCreditNoteReason.from_string("discount") == APCreditNoteReason.DISCOUNT
        assert APCreditNoteReason.from_string("cancellation") == APCreditNoteReason.CANCELLATION
        assert APCreditNoteReason.from_string("correction") == APCreditNoteReason.CORRECTION
        assert APCreditNoteReason.from_string("quality_issue") == APCreditNoteReason.QUALITY_ISSUE

    def test_from_string_invalid_defaults_correction(self):
        assert APCreditNoteReason.from_string("unknown") == APCreditNoteReason.CORRECTION
        assert APCreditNoteReason.from_string("") == APCreditNoteReason.CORRECTION


# ----------------------------------------------------------------------
# APCreditNoteEntity - Construction & Validation
# ----------------------------------------------------------------------
class TestAPCreditNoteEntityConstruction:
    def test_create_success(self, sample_credit_note):
        assert sample_credit_note.credit_note_id is not None
        assert sample_credit_note.credit_note_number == "CN-001"
        assert sample_credit_note.invoice_id is not None
        assert sample_credit_note.invoice_number == "INV-001"
        assert sample_credit_note.vendor_name == "PT Supplier"
        assert sample_credit_note.amount == Decimal("200.00")
        assert sample_credit_note.currency == "IDR"
        assert sample_credit_note.reason == APCreditNoteReason.GOODS_RETURN
        assert sample_credit_note.status == APCreditNoteStatus.DRAFT
        assert sample_credit_note.description == "Return of defective goods"
        assert sample_credit_note.tax_amount == Decimal("22.00")
        assert sample_credit_note.original_invoice_amount == Decimal("1000.00")
        assert sample_credit_note.version == 1
        assert sample_credit_note.created_at.tzinfo == UTC
        assert sample_credit_note.updated_at.tzinfo == UTC
        # Dummy double-entry fields exist
        assert sample_credit_note.total_debit == Decimal(0)
        assert sample_credit_note.total_credit == Decimal(0)

    def test_validation_amount_zero_raises(self):
        with pytest.raises(ValueError, match="Credit note amount must be positive"):
            APCreditNoteEntity.create(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                issue_date=datetime.now(UTC),
                amount=Decimal("0"),
                currency="IDR",
                reason=APCreditNoteReason.GOODS_RETURN,
                created_by="tester",
            )

    def test_validation_amount_negative_raises(self):
        with pytest.raises(ValueError, match="Credit note amount must be positive"):
            APCreditNoteEntity.create(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                issue_date=datetime.now(UTC),
                amount=Decimal("-100"),
                currency="IDR",
                reason=APCreditNoteReason.GOODS_RETURN,
                created_by="tester",
            )

    def test_validation_amount_exceeds_invoice_raises(self):
        with pytest.raises(ValueError, match="exceeds invoice amount"):
            APCreditNoteEntity.create(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                issue_date=datetime.now(UTC),
                amount=Decimal("1500.00"),
                currency="IDR",
                reason=APCreditNoteReason.GOODS_RETURN,
                created_by="tester",
                original_invoice_amount=Decimal("1000.00"),
            )

    def test_validation_naive_date_auto_utc(self):
        naive = datetime(2025, 1, 15, 10, 0)
        note = APCreditNoteEntity.create(
            credit_note_number="CN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            issue_date=naive,
            amount=Decimal("100"),
            currency="IDR",
            reason=APCreditNoteReason.GOODS_RETURN,
            created_by="tester",
        )
        assert note.issue_date.tzinfo == UTC
        assert note.created_at.tzinfo == UTC
        assert note.updated_at.tzinfo == UTC

    def test_validation_version_zero_raises(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            APCreditNoteEntity(
                credit_note_id=uuid4(),
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                issue_date=datetime.now(UTC),
                amount=Decimal("100"),
                currency="IDR",
                reason=APCreditNoteReason.GOODS_RETURN,
                status=APCreditNoteStatus.DRAFT,
                description="Test",
                created_by="system",
                version=0,
            )


# ----------------------------------------------------------------------
# APCreditNoteEntity - Audit Trail
# ----------------------------------------------------------------------
class TestAPCreditNoteEntityAudit:
    def test_audit_trail_initial_empty(self, sample_credit_note):
        trail = sample_credit_note.get_audit_trail()
        assert trail == []

    def test_audit_trail_appends_on_receive(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        trail = received.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "received"
        assert trail[0]["user_id"] == "alice"
        assert trail[0]["version"] == 2

    def test_audit_trail_appends_on_apply(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        applied = received.apply("bob")
        trail = applied.get_audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "received"
        assert trail[1]["action"] == "applied"
        assert trail[1]["user_id"] == "bob"
        assert trail[1]["details"]["invoice_id"] == str(sample_credit_note.invoice_id)

    def test_audit_trail_appends_on_cancel(self, sample_credit_note):
        cancelled = sample_credit_note.cancel("carol", "No longer needed")
        trail = cancelled.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "cancelled"
        assert trail[0]["user_id"] == "carol"
        assert trail[0]["details"]["reason"] == "No longer needed"


# ----------------------------------------------------------------------
# APCreditNoteEntity - Business Methods (receive, apply, cancel)
# ----------------------------------------------------------------------
class TestAPCreditNoteEntityBusiness:
    def test_receive_success(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        assert received.status == APCreditNoteStatus.RECEIVED
        assert received.version == sample_credit_note.version + 1
        assert received.created_by == "alice"
        assert received.updated_at > sample_credit_note.updated_at

    def test_receive_not_draft_raises(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        with pytest.raises(ValueError, match="Cannot receive credit note in status received"):
            received.receive("bob")

    def test_apply_success(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        applied = received.apply("bob")
        assert applied.status == APCreditNoteStatus.APPLIED
        assert applied.version == received.version + 1
        assert applied.created_by == "bob"

    def test_apply_not_received_raises(self, sample_credit_note):
        with pytest.raises(ValueError, match="Cannot apply credit note in status draft"):
            sample_credit_note.apply("bob")

    def test_cancel_draft_success(self, sample_credit_note):
        cancelled = sample_credit_note.cancel("carol", "User request")
        assert cancelled.status == APCreditNoteStatus.CANCELLED
        assert "User request" in cancelled.description
        assert cancelled.version == sample_credit_note.version + 1
        assert cancelled.created_by == "carol"

    def test_cancel_received_success(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        cancelled = received.cancel("carol", "After receive")
        assert cancelled.status == APCreditNoteStatus.CANCELLED

    def test_cancel_applied_raises(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        applied = received.apply("bob")
        with pytest.raises(ValueError, match="Cannot cancel credit note in status applied"):
            applied.cancel("carol", "No")

    def test_cancel_cancelled_raises(self, sample_credit_note):
        cancelled = sample_credit_note.cancel("carol", "First")
        with pytest.raises(ValueError, match="Cannot cancel credit note in status cancelled"):
            cancelled.cancel("carol", "Again")


# ----------------------------------------------------------------------
# APCreditNoteEntity - State Transitions
# ----------------------------------------------------------------------
class TestAPCreditNoteEntityStateTransitions:
    def test_state_flow_draft_to_received_to_applied(self, sample_credit_note):
        # DRAFT -> RECEIVED
        received = sample_credit_note.receive("alice")
        assert received.status == APCreditNoteStatus.RECEIVED
        # RECEIVED -> APPLIED
        applied = received.apply("bob")
        assert applied.status == APCreditNoteStatus.APPLIED
        # Cannot go back
        with pytest.raises(ValueError):
            applied.receive("carol")

    def test_state_flow_draft_to_cancelled(self, sample_credit_note):
        cancelled = sample_credit_note.cancel("carol", "No need")
        assert cancelled.status == APCreditNoteStatus.CANCELLED

    def test_state_flow_received_to_cancelled(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        cancelled = received.cancel("carol", "Cancel after receive")
        assert cancelled.status == APCreditNoteStatus.CANCELLED


# ----------------------------------------------------------------------
# APCreditNoteEntity - Serialization
# ----------------------------------------------------------------------
class TestAPCreditNoteEntitySerialization:
    def test_to_dict(self, sample_credit_note):
        d = sample_credit_note.to_dict()
        assert d["credit_note_id"] == str(sample_credit_note.credit_note_id)
        assert d["credit_note_number"] == "CN-001"
        assert d["invoice_id"] == str(sample_credit_note.invoice_id)
        assert d["invoice_number"] == "INV-001"
        assert d["vendor_id"] == str(sample_credit_note.vendor_id)
        assert d["vendor_name"] == "PT Supplier"
        assert d["amount"] == "200.00"
        assert d["currency"] == "IDR"
        assert d["reason"] == "goods_return"
        assert d["status"] == "draft"
        assert d["description"] == "Return of defective goods"
        assert d["tax_amount"] == "22.00"
        assert d["original_invoice_amount"] == "1000.00"
        assert d["version"] == 1
        assert d["total_debit"] == "0"
        assert d["total_credit"] == "0"

    def test_to_dict_after_receive(self, sample_credit_note):
        received = sample_credit_note.receive("alice")
        d = received.to_dict()
        assert d["status"] == "received"
        assert d["version"] == 2

    def test_from_dict(self, sample_credit_note):
        d = sample_credit_note.to_dict()
        reconstructed = APCreditNoteEntity.from_dict(d)
        assert reconstructed.credit_note_id == sample_credit_note.credit_note_id
        assert reconstructed.credit_note_number == sample_credit_note.credit_note_number
        assert reconstructed.invoice_id == sample_credit_note.invoice_id
        assert reconstructed.invoice_number == sample_credit_note.invoice_number
        assert reconstructed.vendor_id == sample_credit_note.vendor_id
        assert reconstructed.vendor_name == sample_credit_note.vendor_name
        assert reconstructed.amount == sample_credit_note.amount
        assert reconstructed.currency == sample_credit_note.currency
        assert reconstructed.reason == sample_credit_note.reason
        assert reconstructed.status == sample_credit_note.status
        assert reconstructed.description == sample_credit_note.description
        assert reconstructed.tax_amount == sample_credit_note.tax_amount
        assert reconstructed.original_invoice_amount == sample_credit_note.original_invoice_amount
        assert reconstructed.version == sample_credit_note.version
        assert reconstructed.total_debit == Decimal(0)
        assert reconstructed.total_credit == Decimal(0)

    def test_from_dict_with_missing_fields_uses_defaults(self):
        data = {
            "credit_note_id": str(uuid4()),
            "credit_note_number": "CN-001",
            "invoice_id": str(uuid4()),
            "invoice_number": "INV-001",
            "vendor_id": str(uuid4()),
            "vendor_name": "Vendor",
            "issue_date": datetime.now(UTC).isoformat(),
            "amount": "100",
            "currency": "IDR",
            "reason": "goods_return",
            "status": "draft",
            "description": "Test",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        note = APCreditNoteEntity.from_dict(data)
        assert note.tax_amount == Decimal(0)
        assert note.tax_rate == Decimal(11)
        assert note.original_invoice_amount is None
        assert note.created_by == "system"
        assert note.version == 1


# ----------------------------------------------------------------------
# APCreditNoteRepository (Interface)
# ----------------------------------------------------------------------
class TestAPCreditNoteRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = APCreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_invoice_not_implemented(self):
        repo = APCreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_invoice(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_vendor_not_implemented(self):
        repo = APCreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_vendor(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_date_range_not_implemented(self):
        repo = APCreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_date_range(uuid4(), datetime.now(UTC), datetime.now(UTC))

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = APCreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = APCreditNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ----------------------------------------------------------------------
# Edge Cases & Decimal Precision
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_large_amount(self):
        huge = Decimal("9999999999.99")
        note = APCreditNoteEntity.create(
            credit_note_number="CN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            issue_date=datetime.now(UTC),
            amount=huge,
            currency="IDR",
            reason=APCreditNoteReason.GOODS_RETURN,
            created_by="tester",
        )
        assert note.amount == huge

    def test_zero_tax_amount(self):
        note = APCreditNoteEntity.create(
            credit_note_number="CN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            issue_date=datetime.now(UTC),
            amount=Decimal("100"),
            currency="IDR",
            reason=APCreditNoteReason.GOODS_RETURN,
            created_by="tester",
            tax_amount=Decimal("0"),
        )
        assert note.tax_amount == Decimal("0")

    def test_alias_ap_credit_note(self):
        assert APCreditNote is APCreditNoteEntity

    def test_dummy_double_entry_fields(self, sample_credit_note):
        # The dummy fields exist and are accessible
        assert hasattr(sample_credit_note, "total_debit")
        assert hasattr(sample_credit_note, "total_credit")
        # They are initialized to 0
        assert sample_credit_note.total_debit == Decimal(0)
        assert sample_credit_note.total_credit == Decimal(0)
