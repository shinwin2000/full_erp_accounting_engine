# test_debit_note_entity.py
# ==========================
# Comprehensive tests for domain/subledger_ap/debit_note_entity.py.
# Covers all enums, entity methods, audit trail, state transitions, and serialization.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.subledger_ap.debit_note_entity import (
    APDebitNote,
    APDebitNoteEntity,
    APDebitNoteReason,
    APDebitNoteRepository,
    APDebitNoteStatus,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_debit_note() -> APDebitNoteEntity:
    """Create a valid APDebitNoteEntity in DRAFT state."""
    now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    return APDebitNoteEntity.create(
        debit_note_number="DN-001",
        invoice_id=uuid4(),
        invoice_number="INV-001",
        vendor_id=uuid4(),
        vendor_name="PT Supplier",
        issue_date=now,
        amount=Decimal("150.00"),
        currency="IDR",
        reason=APDebitNoteReason.ADDITIONAL_CHARGE,
        created_by="tester",
        description="Additional shipping charge",
        tax_amount=Decimal("16.50"),
        original_invoice_amount=Decimal("1000.00"),
    )


# ----------------------------------------------------------------------
# APDebitNoteStatus Enum
# ----------------------------------------------------------------------
class TestAPDebitNoteStatus:
    def test_members_exist(self):
        assert hasattr(APDebitNoteStatus, "DRAFT")
        assert hasattr(APDebitNoteStatus, "ISSUED")
        assert hasattr(APDebitNoteStatus, "APPLIED")
        assert hasattr(APDebitNoteStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(APDebitNoteStatus.DRAFT, APDebitNoteStatus)

    def test_from_string_valid(self):
        assert APDebitNoteStatus.from_string("draft") == APDebitNoteStatus.DRAFT
        assert APDebitNoteStatus.from_string("DRAFT") == APDebitNoteStatus.DRAFT
        assert APDebitNoteStatus.from_string("issued") == APDebitNoteStatus.ISSUED
        assert APDebitNoteStatus.from_string("applied") == APDebitNoteStatus.APPLIED
        assert APDebitNoteStatus.from_string("cancelled") == APDebitNoteStatus.CANCELLED

    def test_from_string_invalid_defaults_draft(self):
        assert APDebitNoteStatus.from_string("unknown") == APDebitNoteStatus.DRAFT
        assert APDebitNoteStatus.from_string("") == APDebitNoteStatus.DRAFT


# ----------------------------------------------------------------------
# APDebitNoteReason Enum
# ----------------------------------------------------------------------
class TestAPDebitNoteReason:
    def test_members_exist(self):
        assert hasattr(APDebitNoteReason, "ADDITIONAL_CHARGE")
        assert hasattr(APDebitNoteReason, "PENALTY")
        assert hasattr(APDebitNoteReason, "INTEREST")
        assert hasattr(APDebitNoteReason, "CORRECTION")
        assert hasattr(APDebitNoteReason, "SHORTAGE")
        assert hasattr(APDebitNoteReason, "DAMAGE")

    def test_member_is_instance(self):
        assert isinstance(APDebitNoteReason.ADDITIONAL_CHARGE, APDebitNoteReason)

    def test_from_string_valid(self):
        assert APDebitNoteReason.from_string("additional_charge") == APDebitNoteReason.ADDITIONAL_CHARGE
        assert APDebitNoteReason.from_string("ADDITIONAL_CHARGE") == APDebitNoteReason.ADDITIONAL_CHARGE
        assert APDebitNoteReason.from_string("penalty") == APDebitNoteReason.PENALTY
        assert APDebitNoteReason.from_string("interest") == APDebitNoteReason.INTEREST
        assert APDebitNoteReason.from_string("correction") == APDebitNoteReason.CORRECTION
        assert APDebitNoteReason.from_string("shortage") == APDebitNoteReason.SHORTAGE
        assert APDebitNoteReason.from_string("damage") == APDebitNoteReason.DAMAGE

    def test_from_string_invalid_defaults_correction(self):
        assert APDebitNoteReason.from_string("unknown") == APDebitNoteReason.CORRECTION
        assert APDebitNoteReason.from_string("") == APDebitNoteReason.CORRECTION


# ----------------------------------------------------------------------
# APDebitNoteEntity - Construction & Validation
# ----------------------------------------------------------------------
class TestAPDebitNoteEntityConstruction:
    def test_create_success(self, sample_debit_note):
        assert sample_debit_note.debit_note_id is not None
        assert sample_debit_note.debit_note_number == "DN-001"
        assert sample_debit_note.invoice_id is not None
        assert sample_debit_note.invoice_number == "INV-001"
        assert sample_debit_note.vendor_name == "PT Supplier"
        assert sample_debit_note.amount == Decimal("150.00")
        assert sample_debit_note.currency == "IDR"
        assert sample_debit_note.reason == APDebitNoteReason.ADDITIONAL_CHARGE
        assert sample_debit_note.status == APDebitNoteStatus.DRAFT
        assert sample_debit_note.description == "Additional shipping charge"
        assert sample_debit_note.tax_amount == Decimal("16.50")
        assert sample_debit_note.original_invoice_amount == Decimal("1000.00")
        assert sample_debit_note.version == 1
        assert sample_debit_note.created_at.tzinfo == UTC
        assert sample_debit_note.updated_at.tzinfo == UTC
        assert sample_debit_note.total_debit == Decimal(0)
        assert sample_debit_note.total_credit == Decimal(0)

    def test_validation_amount_zero_raises(self):
        with pytest.raises(ValueError, match="Debit note amount must be positive"):
            APDebitNoteEntity.create(
                debit_note_number="DN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                issue_date=datetime.now(UTC),
                amount=Decimal("0"),
                currency="IDR",
                reason=APDebitNoteReason.ADDITIONAL_CHARGE,
                created_by="tester",
            )

    def test_validation_amount_negative_raises(self):
        with pytest.raises(ValueError, match="Debit note amount must be positive"):
            APDebitNoteEntity.create(
                debit_note_number="DN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                issue_date=datetime.now(UTC),
                amount=Decimal("-100"),
                currency="IDR",
                reason=APDebitNoteReason.ADDITIONAL_CHARGE,
                created_by="tester",
            )

    def test_validation_naive_date_auto_utc(self):
        naive = datetime(2025, 1, 15, 10, 0)
        note = APDebitNoteEntity.create(
            debit_note_number="DN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            issue_date=naive,
            amount=Decimal("100"),
            currency="IDR",
            reason=APDebitNoteReason.ADDITIONAL_CHARGE,
            created_by="tester",
        )
        assert note.issue_date.tzinfo == UTC
        assert note.created_at.tzinfo == UTC
        assert note.updated_at.tzinfo == UTC

    def test_validation_version_zero_raises(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            APDebitNoteEntity(
                debit_note_id=uuid4(),
                debit_note_number="DN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                issue_date=datetime.now(UTC),
                amount=Decimal("100"),
                currency="IDR",
                reason=APDebitNoteReason.ADDITIONAL_CHARGE,
                status=APDebitNoteStatus.DRAFT,
                description="Test",
                created_by="system",
                version=0,
            )


# ----------------------------------------------------------------------
# APDebitNoteEntity - Audit Trail
# ----------------------------------------------------------------------
class TestAPDebitNoteEntityAudit:
    def test_audit_trail_initial_empty(self, sample_debit_note):
        trail = sample_debit_note.get_audit_trail()
        assert trail == []

    def test_audit_trail_appends_on_issue(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        trail = issued.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "issued"
        assert trail[0]["user_id"] == "alice"
        assert trail[0]["version"] == 2

    def test_audit_trail_appends_on_apply(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        applied = issued.apply("bob")
        trail = applied.get_audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "issued"
        assert trail[1]["action"] == "applied"
        assert trail[1]["user_id"] == "bob"
        assert trail[1]["details"]["invoice_id"] == str(sample_debit_note.invoice_id)

    def test_audit_trail_appends_on_cancel(self, sample_debit_note):
        cancelled = sample_debit_note.cancel("carol", "No longer needed")
        trail = cancelled.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "cancelled"
        assert trail[0]["user_id"] == "carol"
        assert trail[0]["details"]["reason"] == "No longer needed"


# ----------------------------------------------------------------------
# APDebitNoteEntity - Business Methods (issue, apply, cancel)
# ----------------------------------------------------------------------
class TestAPDebitNoteEntityBusiness:
    def test_issue_success(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        assert issued.status == APDebitNoteStatus.ISSUED
        assert issued.version == sample_debit_note.version + 1
        assert issued.created_by == "alice"
        assert issued.updated_at > sample_debit_note.updated_at

    def test_issue_not_draft_raises(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        with pytest.raises(ValueError, match="Cannot issue debit note in status issued"):
            issued.issue("bob")

    def test_apply_success(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        applied = issued.apply("bob")
        assert applied.status == APDebitNoteStatus.APPLIED
        assert applied.version == issued.version + 1
        assert applied.created_by == "bob"

    def test_apply_not_issued_raises(self, sample_debit_note):
        with pytest.raises(ValueError, match="Cannot apply debit note in status draft"):
            sample_debit_note.apply("bob")

    def test_cancel_draft_success(self, sample_debit_note):
        cancelled = sample_debit_note.cancel("carol", "User request")
        assert cancelled.status == APDebitNoteStatus.CANCELLED
        assert "User request" in cancelled.description
        assert cancelled.version == sample_debit_note.version + 1
        assert cancelled.created_by == "carol"

    def test_cancel_issued_success(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        cancelled = issued.cancel("carol", "After issue")
        assert cancelled.status == APDebitNoteStatus.CANCELLED

    def test_cancel_applied_raises(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        applied = issued.apply("bob")
        with pytest.raises(ValueError, match="Cannot cancel debit note in status applied"):
            applied.cancel("carol", "No")

    def test_cancel_cancelled_raises(self, sample_debit_note):
        cancelled = sample_debit_note.cancel("carol", "First")
        with pytest.raises(ValueError, match="Cannot cancel debit note in status cancelled"):
            cancelled.cancel("carol", "Again")


# ----------------------------------------------------------------------
# APDebitNoteEntity - State Transitions
# ----------------------------------------------------------------------
class TestAPDebitNoteEntityStateTransitions:
    def test_state_flow_draft_to_issued_to_applied(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        assert issued.status == APDebitNoteStatus.ISSUED
        applied = issued.apply("bob")
        assert applied.status == APDebitNoteStatus.APPLIED
        with pytest.raises(ValueError):
            applied.issue("carol")

    def test_state_flow_draft_to_cancelled(self, sample_debit_note):
        cancelled = sample_debit_note.cancel("carol", "No need")
        assert cancelled.status == APDebitNoteStatus.CANCELLED

    def test_state_flow_issued_to_cancelled(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        cancelled = issued.cancel("carol", "Cancel after issue")
        assert cancelled.status == APDebitNoteStatus.CANCELLED


# ----------------------------------------------------------------------
# APDebitNoteEntity - Serialization
# ----------------------------------------------------------------------
class TestAPDebitNoteEntitySerialization:
    def test_to_dict(self, sample_debit_note):
        d = sample_debit_note.to_dict()
        assert d["debit_note_id"] == str(sample_debit_note.debit_note_id)
        assert d["debit_note_number"] == "DN-001"
        assert d["invoice_id"] == str(sample_debit_note.invoice_id)
        assert d["invoice_number"] == "INV-001"
        assert d["vendor_id"] == str(sample_debit_note.vendor_id)
        assert d["vendor_name"] == "PT Supplier"
        assert d["amount"] == "150.00"
        assert d["currency"] == "IDR"
        assert d["reason"] == "additional_charge"
        assert d["status"] == "draft"
        assert d["description"] == "Additional shipping charge"
        assert d["tax_amount"] == "16.50"
        assert d["original_invoice_amount"] == "1000.00"
        assert d["version"] == 1
        assert d["total_debit"] == "0"
        assert d["total_credit"] == "0"

    def test_to_dict_after_issue(self, sample_debit_note):
        issued = sample_debit_note.issue("alice")
        d = issued.to_dict()
        assert d["status"] == "issued"
        assert d["version"] == 2

    def test_from_dict(self, sample_debit_note):
        d = sample_debit_note.to_dict()
        reconstructed = APDebitNoteEntity.from_dict(d)
        assert reconstructed.debit_note_id == sample_debit_note.debit_note_id
        assert reconstructed.debit_note_number == sample_debit_note.debit_note_number
        assert reconstructed.invoice_id == sample_debit_note.invoice_id
        assert reconstructed.invoice_number == sample_debit_note.invoice_number
        assert reconstructed.vendor_id == sample_debit_note.vendor_id
        assert reconstructed.vendor_name == sample_debit_note.vendor_name
        assert reconstructed.amount == sample_debit_note.amount
        assert reconstructed.currency == sample_debit_note.currency
        assert reconstructed.reason == sample_debit_note.reason
        assert reconstructed.status == sample_debit_note.status
        assert reconstructed.description == sample_debit_note.description
        assert reconstructed.tax_amount == sample_debit_note.tax_amount
        assert reconstructed.original_invoice_amount == sample_debit_note.original_invoice_amount
        assert reconstructed.version == sample_debit_note.version
        assert reconstructed.total_debit == Decimal(0)
        assert reconstructed.total_credit == Decimal(0)

    def test_from_dict_with_missing_fields_uses_defaults(self):
        data = {
            "debit_note_id": str(uuid4()),
            "debit_note_number": "DN-001",
            "invoice_id": str(uuid4()),
            "invoice_number": "INV-001",
            "vendor_id": str(uuid4()),
            "vendor_name": "Vendor",
            "issue_date": datetime.now(UTC).isoformat(),
            "amount": "100",
            "currency": "IDR",
            "reason": "additional_charge",
            "status": "draft",
            "description": "Test",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        note = APDebitNoteEntity.from_dict(data)
        assert note.tax_amount == Decimal(0)
        assert note.tax_rate == Decimal(11)
        assert note.original_invoice_amount is None
        assert note.created_by == "system"
        assert note.version == 1


# ----------------------------------------------------------------------
# APDebitNoteRepository (Interface)
# ----------------------------------------------------------------------
class TestAPDebitNoteRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = APDebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_invoice_not_implemented(self):
        repo = APDebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_invoice(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_vendor_not_implemented(self):
        repo = APDebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_vendor(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = APDebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = APDebitNoteRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ----------------------------------------------------------------------
# Edge Cases & Decimal Precision
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_large_amount(self):
        huge = Decimal("9999999999.99")
        note = APDebitNoteEntity.create(
            debit_note_number="DN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            issue_date=datetime.now(UTC),
            amount=huge,
            currency="IDR",
            reason=APDebitNoteReason.ADDITIONAL_CHARGE,
            created_by="tester",
        )
        assert note.amount == huge

    def test_zero_tax_amount(self):
        note = APDebitNoteEntity.create(
            debit_note_number="DN-001",
            invoice_id=uuid4(),
            invoice_number="INV-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            issue_date=datetime.now(UTC),
            amount=Decimal("100"),
            currency="IDR",
            reason=APDebitNoteReason.ADDITIONAL_CHARGE,
            created_by="tester",
            tax_amount=Decimal("0"),
        )
        assert note.tax_amount == Decimal("0")

    def test_alias_ap_debit_note(self):
        assert APDebitNote is APDebitNoteEntity

    def test_dummy_double_entry_fields(self, sample_debit_note):
        assert hasattr(sample_debit_note, "total_debit")
        assert hasattr(sample_debit_note, "total_credit")
        assert sample_debit_note.total_debit == Decimal(0)
        assert sample_debit_note.total_credit == Decimal(0)
