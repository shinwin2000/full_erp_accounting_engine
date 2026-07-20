# test_cash_receipt_entity.py
# Comprehensive tests for cash_receipt_entity.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.cash_receipt_entity import (
    CashReceiptEntity,
    CashReceiptRepository,
    CashReceiptStatus,
    CashReceiptType,
    PaymentMethod,
    ReceiptAllocation,
    ReceiptSignature,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_storage():
    """Reset in-memory repository storage before each test."""
    CashReceiptRepository._storage = {}
    CashReceiptRepository._storage_by_number = {}
    yield
    CashReceiptRepository._storage = {}
    CashReceiptRepository._storage_by_number = {}


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def valid_receipt_data(legal_entity_id):
    return {
        "receipt_id": uuid4(),
        "receipt_number": "CR-001",
        "receipt_type": CashReceiptType.CUSTOMER_PAYMENT,
        "receipt_date": datetime.now(UTC),
        "amount": Decimal("1000.00"),
        "currency": "IDR",
        "status": CashReceiptStatus.DRAFT,
        "customer_id": uuid4(),
        "customer_name": "Customer A",
        "invoice_id": uuid4(),
        "invoice_number": "INV-001",
        "payment_method": PaymentMethod.BANK_TRANSFER,
        "payment_reference": "REF123",
        "received_by": "receiver1",
        "created_by": "system",
    }


@pytest.fixture
def valid_receipt(valid_receipt_data):
    return CashReceiptEntity(**valid_receipt_data)


@pytest.fixture
def submitted_receipt(valid_receipt):
    return valid_receipt.submit("submitted_by")


@pytest.fixture
def verified_receipt(valid_receipt):
    # Need to go through workflow: submit, then manually set to PENDING_VERIFICATION, then verify
    submitted = valid_receipt.submit("submitter")
    data = submitted.to_dict()
    data["status"] = CashReceiptStatus.PENDING_VERIFICATION.value
    pending = CashReceiptEntity.from_dict(data)
    return pending.verify("verifier", "Verified")


@pytest.fixture
def confirmed_receipt(verified_receipt):
    return verified_receipt.confirm("confirmer")


@pytest.fixture
def cancelled_receipt(valid_receipt):
    return valid_receipt.cancel("canceller", "Test cancel")


@pytest.fixture
def rejected_receipt(submitted_receipt):
    return submitted_receipt.reject("rejecter", "Reject reason")


@pytest.fixture
def receipt_with_allocation(valid_receipt):
    alloc = ReceiptAllocation(
        allocation_id=uuid4(),
        invoice_id=uuid4(),
        invoice_number="INV-002",
        allocated_amount=Decimal("300.00"),
        remaining_invoice_amount=Decimal("700.00"),
    )
    return valid_receipt.add_allocation(
        invoice_id=alloc.invoice_id,
        invoice_number=alloc.invoice_number,
        allocated_amount=alloc.allocated_amount,
        remaining_invoice=alloc.remaining_invoice_amount,
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestCashReceiptStatus:
    def test_members(self):
        assert CashReceiptStatus.DRAFT.value == "draft"
        assert CashReceiptStatus.SUBMITTED.value == "submitted"
        assert CashReceiptStatus.CONFIRMED.value == "confirmed"
        assert CashReceiptStatus.CANCELLED.value == "cancelled"
        assert CashReceiptStatus.REJECTED.value == "rejected"
        assert CashReceiptStatus.PARTIALLY_CONFIRMED.value == "partially_confirmed"
        assert CashReceiptStatus.PENDING_VERIFICATION.value == "pending_verification"
        assert CashReceiptStatus.VERIFIED.value == "verified"

    def test_can_transition(self):
        # DRAFT -> SUBMITTED, CANCELLED
        assert CashReceiptStatus.can_transition(CashReceiptStatus.DRAFT, CashReceiptStatus.SUBMITTED) is True
        assert CashReceiptStatus.can_transition(CashReceiptStatus.DRAFT, CashReceiptStatus.CANCELLED) is True
        assert CashReceiptStatus.can_transition(CashReceiptStatus.DRAFT, CashReceiptStatus.REJECTED) is False

        # SUBMITTED -> PENDING_VERIFICATION, REJECTED, CANCELLED
        assert CashReceiptStatus.can_transition(CashReceiptStatus.SUBMITTED, CashReceiptStatus.PENDING_VERIFICATION) is True
        assert CashReceiptStatus.can_transition(CashReceiptStatus.SUBMITTED, CashReceiptStatus.REJECTED) is True
        assert CashReceiptStatus.can_transition(CashReceiptStatus.SUBMITTED, CashReceiptStatus.CANCELLED) is True

        # PENDING_VERIFICATION -> VERIFIED, REJECTED
        assert CashReceiptStatus.can_transition(CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.VERIFIED) is True
        assert CashReceiptStatus.can_transition(CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.REJECTED) is True

        # VERIFIED -> CONFIRMED, PARTIALLY_CONFIRMED
        assert CashReceiptStatus.can_transition(CashReceiptStatus.VERIFIED, CashReceiptStatus.CONFIRMED) is True
        assert CashReceiptStatus.can_transition(CashReceiptStatus.VERIFIED, CashReceiptStatus.PARTIALLY_CONFIRMED) is True

        # CONFIRMED -> CANCELLED
        assert CashReceiptStatus.can_transition(CashReceiptStatus.CONFIRMED, CashReceiptStatus.CANCELLED) is True

        # PARTIALLY_CONFIRMED -> CONFIRMED, CANCELLED
        assert CashReceiptStatus.can_transition(CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.CONFIRMED) is True
        assert CashReceiptStatus.can_transition(CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.CANCELLED) is True

        # REJECTED -> DRAFT
        assert CashReceiptStatus.can_transition(CashReceiptStatus.REJECTED, CashReceiptStatus.DRAFT) is True

        # CANCELLED -> none
        assert CashReceiptStatus.can_transition(CashReceiptStatus.CANCELLED, CashReceiptStatus.DRAFT) is False


class TestCashReceiptType:
    def test_members(self):
        assert CashReceiptType.CUSTOMER_PAYMENT.value == "customer_payment"
        assert CashReceiptType.LOAN_RECEIPT.value == "loan_receipt"
        assert CashReceiptType.CAPITAL_CONTRIBUTION.value == "capital_contribution"
        assert CashReceiptType.OTHER_INCOME.value == "other_income"
        assert CashReceiptType.REFUND.value == "refund"
        assert CashReceiptType.INTEREST.value == "interest"
        assert CashReceiptType.DIVIDEND.value == "dividend"
        assert CashReceiptType.TAX_REFUND.value == "tax_refund"
        assert CashReceiptType.INSURANCE_CLAIM.value == "insurance_claim"
        assert CashReceiptType.GRANT.value == "grant"
        assert CashReceiptType.DEPOSIT_RETURN.value == "deposit_return"


class TestPaymentMethod:
    def test_members(self):
        assert PaymentMethod.CASH.value == "cash"
        assert PaymentMethod.BANK_TRANSFER.value == "bank_transfer"
        assert PaymentMethod.CHEQUE.value == "cheque"
        assert PaymentMethod.GIRO.value == "giro"
        assert PaymentMethod.CREDIT_CARD.value == "credit_card"
        assert PaymentMethod.DEBIT_CARD.value == "debit_card"
        assert PaymentMethod.E_WALLET.value == "e_wallet"
        assert PaymentMethod.QRIS.value == "qris"
        assert PaymentMethod.CRYPTO.value == "crypto"
        assert PaymentMethod.OTHER.value == "other"


# ============================================================================
# Tests for ReceiptAllocation
# ============================================================================

class TestReceiptAllocation:
    def test_construction(self):
        alloc = ReceiptAllocation(
            allocation_id=uuid4(),
            invoice_id=uuid4(),
            invoice_number="INV-001",
            allocated_amount=Decimal("500.00"),
            remaining_invoice_amount=Decimal("500.00"),
        )
        assert alloc.allocated_amount == Decimal("500.00")
        assert alloc.remaining_invoice_amount == Decimal("500.00")
        assert alloc.created_at.tzinfo is not None

    def test_update_allocation(self):
        alloc = ReceiptAllocation(
            allocation_id=uuid4(),
            invoice_id=uuid4(),
            invoice_number="INV-001",
            allocated_amount=Decimal("300.00"),
            remaining_invoice_amount=Decimal("700.00"),
        )
        new_alloc = alloc.update_allocation(Decimal("400.00"), Decimal("600.00"))
        assert new_alloc.allocated_amount == Decimal("400.00")
        assert new_alloc.remaining_invoice_amount == Decimal("600.00")
        assert new_alloc.allocation_id == alloc.allocation_id
        assert new_alloc.invoice_id == alloc.invoice_id

    def test_to_dict(self):
        aid = uuid4()
        iid = uuid4()
        now = datetime.now(UTC)
        alloc = ReceiptAllocation(
            allocation_id=aid,
            invoice_id=iid,
            invoice_number="INV-002",
            allocated_amount=Decimal("200.00"),
            remaining_invoice_amount=Decimal("800.00"),
            created_at=now,
        )
        d = alloc.to_dict()
        assert d["allocation_id"] == str(aid)
        assert d["invoice_id"] == str(iid)
        assert d["invoice_number"] == "INV-002"
        assert d["allocated_amount"] == "200.00"
        assert d["remaining_invoice_amount"] == "800.00"
        assert d["created_at"] == now.isoformat()


# ============================================================================
# Tests for ReceiptSignature
# ============================================================================

class TestReceiptSignature:
    def test_create(self, valid_receipt):
        signature = ReceiptSignature.create(valid_receipt, "signer")
        assert signature.receipt_id == valid_receipt.receipt_id
        assert signature.version == valid_receipt.version
        assert signature.signed_by == "signer"
        assert signature.signed_at.tzinfo is not None
        assert signature.hash_value is not None

    def test_verify(self, valid_receipt):
        signature = ReceiptSignature.create(valid_receipt, "signer")
        assert signature.verify(valid_receipt) is True

        # Tamper with receipt
        tampered = valid_receipt.update_amount(Decimal("2000.00"), "tamper", "Test")
        assert signature.verify(tampered) is False

    def test_verify_different_receipt(self, valid_receipt):
        signature = ReceiptSignature.create(valid_receipt, "signer")
        # Create another receipt
        other = valid_receipt.clone()
        assert signature.verify(other) is False


# ============================================================================
# Tests for CashReceiptEntity - Construction and Validation
# ============================================================================

class TestCashReceiptEntityConstruction:
    def test_construction_valid(self, valid_receipt):
        assert valid_receipt.receipt_number == "CR-001"
        assert valid_receipt.amount == Decimal("1000.00")
        assert valid_receipt.status == CashReceiptStatus.DRAFT
        assert valid_receipt.version == 1
        assert valid_receipt._audit_trail is not None

    def test_validation_receipt_number_too_short(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            CashReceiptEntity(
                receipt_id=uuid4(),
                receipt_number="CR",
                receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
                receipt_date=datetime.now(UTC),
                amount=Decimal("1000.00"),
                currency="IDR",
                status=CashReceiptStatus.DRAFT,
            )

    def test_validation_amount_zero_or_negative(self):
        with pytest.raises(ValueError, match="positive"):
            CashReceiptEntity(
                receipt_id=uuid4(),
                receipt_number="CR-001",
                receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
                receipt_date=datetime.now(UTC),
                amount=Decimal("0"),
                currency="IDR",
                status=CashReceiptStatus.DRAFT,
            )
        with pytest.raises(ValueError, match="positive"):
            CashReceiptEntity(
                receipt_id=uuid4(),
                receipt_number="CR-001",
                receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
                receipt_date=datetime.now(UTC),
                amount=Decimal("-100"),
                currency="IDR",
                status=CashReceiptStatus.DRAFT,
            )

    def test_validation_confirmed_amount_negative(self):
        with pytest.raises(ValueError, match="negative"):
            CashReceiptEntity(
                receipt_id=uuid4(),
                receipt_number="CR-001",
                receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
                receipt_date=datetime.now(UTC),
                amount=Decimal("1000.00"),
                currency="IDR",
                status=CashReceiptStatus.DRAFT,
                confirmed_amount=Decimal("-100"),
            )

    def test_validation_confirmed_amount_exceeds_amount(self):
        with pytest.raises(ValueError, match="exceeds total amount"):
            CashReceiptEntity(
                receipt_id=uuid4(),
                receipt_number="CR-001",
                receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
                receipt_date=datetime.now(UTC),
                amount=Decimal("1000.00"),
                currency="IDR",
                status=CashReceiptStatus.DRAFT,
                confirmed_amount=Decimal("1500.00"),
            )

    def test_validation_receipt_date_future(self):
        future = datetime.now(UTC) + timedelta(days=1)
        with pytest.raises(ValueError, match="cannot be in the future"):
            CashReceiptEntity(
                receipt_id=uuid4(),
                receipt_number="CR-001",
                receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
                receipt_date=future,
                amount=Decimal("1000.00"),
                currency="IDR",
                status=CashReceiptStatus.DRAFT,
            )


# ============================================================================
# Tests for Entity Basic Methods
# ============================================================================

class TestCashReceiptEntityBasicMethods:
    def test_create(self, valid_receipt):
        receipt = valid_receipt.create("admin")
        assert receipt is valid_receipt
        trail = receipt.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "admin"
        assert trail[0]["details"]["amount"] == "1000.00"

    def test_update(self, valid_receipt):
        updated = valid_receipt.update(
            updated_by="admin",
            description="Updated description",
            customer_name="New Customer"
        )
        assert updated.description == "Updated description"
        assert updated.customer_name == "New Customer"
        assert updated.version == 2
        trail = updated.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["details"]["changes"] == {"description": "Updated description", "customer_name": "New Customer"}

    def test_update_cannot_edit_confirmed(self, confirmed_receipt):
        with pytest.raises(ValueError, match="Cannot update receipt in status confirmed"):
            confirmed_receipt.update("admin", description="test")

    def test_delete_draft(self, valid_receipt):
        deleted = valid_receipt.delete("admin", "Test delete")
        assert deleted.status == CashReceiptStatus.CANCELLED
        assert deleted.cancelled_by == "admin"
        assert deleted.cancelled_at is not None
        assert deleted.cancellation_reason == "Test delete"
        assert deleted.version == 2
        trail = deleted.audit_trail()
        assert trail[0]["action"] == "DELETE"

    def test_delete_confirmed_raises(self, confirmed_receipt):
        with pytest.raises(ValueError, match="Cannot delete confirmed receipt"):
            confirmed_receipt.delete("admin")

    def test_restore(self, valid_receipt):
        deleted = valid_receipt.delete("admin")
        restored = deleted.restore("admin2")
        assert restored.status == CashReceiptStatus.DRAFT
        assert restored.cancelled_by is None
        assert restored.cancelled_at is None
        assert restored.cancellation_reason is None
        assert restored.deleted_at is None
        assert restored.version == 3
        trail = restored.audit_trail()
        assert trail[0]["action"] == "RESTORE"

    def test_restore_non_cancelled_raises(self, valid_receipt):
        with pytest.raises(ValueError, match="Cannot restore receipt in status draft"):
            valid_receipt.restore("admin")

    def test_activate(self, valid_receipt):
        activated = valid_receipt.activate("activator")
        assert activated.status == CashReceiptStatus.SUBMITTED
        assert activated.submitted_by == "activator"
        assert activated.submitted_at is not None
        assert activated.version == 2
        trail = activated.audit_trail()
        assert trail[0]["action"] == "ACTIVATE"

    def test_activate_non_draft_raises(self, submitted_receipt):
        with pytest.raises(ValueError, match="Cannot activate receipt in status submitted"):
            submitted_receipt.activate("activator")

    def test_deactivate(self, submitted_receipt):
        deactivated = submitted_receipt.deactivate("admin", "Reason")
        assert deactivated.status == CashReceiptStatus.DRAFT
        assert deactivated.submitted_by is None
        assert deactivated.submitted_at is None
        assert deactivated.version == 2
        trail = deactivated.audit_trail()
        assert trail[0]["action"] == "DEACTIVATE"

    def test_deactivate_non_submitted_raises(self, valid_receipt):
        with pytest.raises(ValueError, match="Cannot deactivate receipt in status draft"):
            valid_receipt.deactivate("admin")

    def test_lock(self, valid_receipt):
        locked = valid_receipt.lock("admin", "Lock reason")
        assert locked.requires_verification is True
        assert locked.version == 2
        trail = locked.audit_trail()
        assert trail[0]["action"] == "LOCK"
        assert trail[0]["details"]["reason"] == "Lock reason"

    def test_unlock(self, valid_receipt):
        locked = valid_receipt.lock("admin", "Lock")
        unlocked = locked.unlock("admin")
        assert unlocked.requires_verification is False
        assert unlocked.version == 3
        trail = unlocked.audit_trail()
        assert trail[0]["action"] == "UNLOCK"

    def test_validate(self, valid_receipt):
        result = valid_receipt.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["warnings"] == []

    def test_validate_with_allocation_exceeds(self, valid_receipt):
        # add_allocation prevents exceeding, so we test by directly creating a receipt with allocations
        alloc1 = ReceiptAllocation(
            allocation_id=uuid4(),
            invoice_id=uuid4(),
            invoice_number="INV-001",
            allocated_amount=Decimal("600.00"),
            remaining_invoice_amount=Decimal("400.00"),
        )
        alloc2 = ReceiptAllocation(
            allocation_id=uuid4(),
            invoice_id=uuid4(),
            invoice_number="INV-002",
            allocated_amount=Decimal("500.00"),
            remaining_invoice_amount=Decimal("500.00"),
        )
        # Create receipt with total allocated > amount
        data = valid_receipt.to_dict()
        data["allocations"] = [alloc1, alloc2]
        receipt = CashReceiptEntity.from_dict(data)
        result = receipt.validate()
        assert result["is_valid"] is False
        assert "Total allocated" in result["errors"][0]

    def test_to_dict(self, valid_receipt):
        d = valid_receipt.to_dict()
        assert d["receipt_id"] == str(valid_receipt.receipt_id)
        assert d["receipt_number"] == "CR-001"
        assert d["receipt_type"] == "customer_payment"
        assert d["amount"] == "1000.00"
        assert d["status"] == "draft"
        assert d["version"] == 1
        assert "allocation_summary" in d
        assert "payment_summary" in d

    def test_from_dict(self, valid_receipt):
        data = valid_receipt.to_dict()
        restored = CashReceiptEntity.from_dict(data)
        assert restored.receipt_id == valid_receipt.receipt_id
        assert restored.receipt_number == valid_receipt.receipt_number
        assert restored.amount == valid_receipt.amount
        assert restored.status == valid_receipt.status
        assert restored.version == valid_receipt.version

    def test_clone(self, valid_receipt):
        cloned = valid_receipt.clone()
        assert cloned.receipt_id != valid_receipt.receipt_id
        assert cloned.receipt_number.startswith(valid_receipt.receipt_number + "_COPY_")
        assert cloned.status == CashReceiptStatus.DRAFT
        assert cloned.confirmed_amount == Decimal("0")
        assert cloned.allocations == []
        assert cloned.version == 1
        assert cloned.created_at > valid_receipt.created_at
        trail = cloned.audit_trail()
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, valid_receipt):
        snap = valid_receipt.snapshot()
        assert snap["receipt_id"] == str(valid_receipt.receipt_id)
        assert snap["receipt_number"] == "CR-001"
        assert snap["amount"] == "1000.00"
        assert snap["status"] == "draft"
        assert "timestamp" in snap

    def test_get_version(self, valid_receipt):
        assert valid_receipt.get_version() == 1

    def test_audit_trail(self, valid_receipt):
        valid_receipt.create("admin")
        valid_receipt.update("admin", description="Updated")
        trail = valid_receipt.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "UPDATE"

    def test_touch(self, valid_receipt):
        touched = valid_receipt.touch("toucher")
        assert touched.version == 2
        trail = touched.audit_trail()
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"


# ============================================================================
# Tests for Status Checkers
# ============================================================================

class TestCashReceiptEntityStatusCheckers:
    def test_is_draft(self, valid_receipt, submitted_receipt):
        assert valid_receipt.is_draft() is True
        assert submitted_receipt.is_draft() is False

    def test_is_submitted(self, submitted_receipt, valid_receipt):
        assert submitted_receipt.is_submitted() is True
        assert valid_receipt.is_submitted() is False

    def test_is_confirmed(self, confirmed_receipt, valid_receipt):
        assert confirmed_receipt.is_confirmed() is True
        assert valid_receipt.is_confirmed() is False

    def test_is_cancelled(self, cancelled_receipt, valid_receipt):
        assert cancelled_receipt.is_cancelled() is True
        assert valid_receipt.is_cancelled() is False

    def test_is_rejected(self, rejected_receipt, valid_receipt):
        assert rejected_receipt.is_rejected() is True
        assert valid_receipt.is_rejected() is False

    def test_is_partially_confirmed(self):
        receipt = CashReceiptEntity(
            receipt_id=uuid4(),
            receipt_number="CR-PARTIAL",
            receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
            receipt_date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            currency="IDR",
            status=CashReceiptStatus.PARTIALLY_CONFIRMED,
            confirmed_amount=Decimal("400.00"),
        )
        assert receipt.is_partially_confirmed() is True
        assert receipt.is_confirmed() is False

    def test_is_pending_verification(self):
        receipt = CashReceiptEntity(
            receipt_id=uuid4(),
            receipt_number="CR-PEND",
            receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
            receipt_date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            currency="IDR",
            status=CashReceiptStatus.PENDING_VERIFICATION,
        )
        assert receipt.is_pending_verification() is True

    def test_is_verified(self):
        receipt = CashReceiptEntity(
            receipt_id=uuid4(),
            receipt_number="CR-VER",
            receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
            receipt_date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            currency="IDR",
            status=CashReceiptStatus.VERIFIED,
        )
        assert receipt.is_verified() is True

    def test_can_edit(self, valid_receipt, rejected_receipt, submitted_receipt):
        assert valid_receipt.can_edit() is True
        assert rejected_receipt.can_edit() is True
        assert submitted_receipt.can_edit() is False

    def test_can_submit(self, valid_receipt, submitted_receipt):
        assert valid_receipt.can_submit() is True
        assert submitted_receipt.can_submit() is False

    def test_can_verify(self):
        pending = CashReceiptEntity(
            receipt_id=uuid4(),
            receipt_number="CR-PEND",
            receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
            receipt_date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            currency="IDR",
            status=CashReceiptStatus.PENDING_VERIFICATION,
        )
        assert pending.can_verify() is True
        assert valid_receipt.can_verify() is False

    def test_can_confirm(self, verified_receipt, valid_receipt):
        assert verified_receipt.can_confirm() is True
        assert valid_receipt.can_confirm() is False

    def test_can_cancel(self, valid_receipt, cancelled_receipt, rejected_receipt):
        assert valid_receipt.can_cancel() is True
        assert cancelled_receipt.can_cancel() is False
        assert rejected_receipt.can_cancel() is False

    def test_can_reject(self, submitted_receipt, valid_receipt):
        assert submitted_receipt.can_reject() is True
        assert valid_receipt.can_reject() is False

    def test_is_fully_confirmed(self, confirmed_receipt, valid_receipt):
        assert confirmed_receipt.is_fully_confirmed() is True
        assert valid_receipt.is_fully_confirmed() is False

    def test_get_remaining_to_confirm(self, valid_receipt, confirmed_receipt):
        assert valid_receipt.get_remaining_to_confirm() == Decimal("1000.00")
        assert confirmed_receipt.get_remaining_to_confirm() == Decimal("0.00")

        partial = CashReceiptEntity(
            receipt_id=uuid4(),
            receipt_number="CR-PARTIAL",
            receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
            receipt_date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            currency="IDR",
            status=CashReceiptStatus.PARTIALLY_CONFIRMED,
            confirmed_amount=Decimal("600.00"),
        )
        assert partial.get_remaining_to_confirm() == Decimal("400.00")


# ============================================================================
# Tests for Workflow Actions
# ============================================================================

class TestCashReceiptEntityWorkflow:
    def test_submit(self, valid_receipt):
        submitted = valid_receipt.submit("submitter")
        assert submitted.status == CashReceiptStatus.SUBMITTED
        assert submitted.submitted_by == "submitter"
        assert submitted.submitted_at is not None
        assert submitted.version == 2
        trail = submitted.audit_trail()
        assert trail[0]["action"] == "SUBMIT"

    def test_submit_cannot_from_non_draft(self, submitted_receipt):
        with pytest.raises(ValueError, match="Cannot submit receipt in status submitted"):
            submitted_receipt.submit("submitter")

    def test_verify(self):
        pending = CashReceiptEntity(
            receipt_id=uuid4(),
            receipt_number="CR-PEND",
            receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
            receipt_date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            currency="IDR",
            status=CashReceiptStatus.PENDING_VERIFICATION,
        )
        verified = pending.verify("verifier", "Verified notes")
        assert verified.status == CashReceiptStatus.VERIFIED
        assert verified.verified_by == "verifier"
        assert verified.verified_at is not None
        assert verified.verification_notes == "Verified notes"
        assert verified.version == 2
        trail = verified.audit_trail()
        assert trail[0]["action"] == "VERIFY"

    def test_verify_cannot_from_non_pending(self, valid_receipt):
        with pytest.raises(ValueError, match="Cannot verify receipt in status draft"):
            valid_receipt.verify("verifier")

    def test_confirm_full(self, verified_receipt):
        confirmed = verified_receipt.confirm("confirmer")
        assert confirmed.status == CashReceiptStatus.CONFIRMED
        assert confirmed.confirmed_amount == Decimal("1000.00")
        assert confirmed.confirmed_date is not None
        assert confirmed.confirmed_by == "confirmer"
        assert confirmed.confirmed_at is not None
        assert confirmed.version == verified_receipt.version + 1
        trail = confirmed.audit_trail()
        assert trail[0]["action"] == "CONFIRM"
        assert trail[0]["details"]["amount"] == "1000.00"

    def test_confirm_partial(self, verified_receipt):
        confirmed = verified_receipt.confirm("confirmer", confirmed_amount=Decimal("600.00"))
        assert confirmed.status == CashReceiptStatus.PARTIALLY_CONFIRMED
        assert confirmed.confirmed_amount == Decimal("600.00")
        assert confirmed.get_remaining_to_confirm() == Decimal("400.00")
        assert confirmed.version == verified_receipt.version + 1

    def test_confirm_cannot_from_non_verified(self, valid_receipt):
        with pytest.raises(ValueError, match="Cannot confirm receipt in status draft"):
            valid_receipt.confirm("confirmer")

    def test_confirm_amount_zero(self, verified_receipt):
        with pytest.raises(ValueError, match="Confirm amount must be positive"):
            verified_receipt.confirm("confirmer", confirmed_amount=Decimal("0"))

    def test_confirm_amount_exceeds_remaining(self, verified_receipt):
        with pytest.raises(ValueError, match="exceeds remaining"):
            verified_receipt.confirm("confirmer", confirmed_amount=Decimal("2000.00"))

    def test_reject(self, submitted_receipt):
        rejected = submitted_receipt.reject("rejecter", "Invalid amount")
        assert rejected.status == CashReceiptStatus.REJECTED
        assert rejected.rejected_by == "rejecter"
        assert rejected.rejected_at is not None
        assert rejected.rejection_reason == "Invalid amount"
        assert rejected.version == 2
        trail = rejected.audit_trail()
        assert trail[0]["action"] == "REJECT"
        assert trail[0]["details"]["reason"] == "Invalid amount"

    def test_reject_cannot_from_non_submitted_pending(self, valid_receipt):
        with pytest.raises(ValueError, match="Cannot reject receipt in status draft"):
            valid_receipt.reject("rejecter", "Reason")

    def test_cancel(self, valid_receipt):
        cancelled = valid_receipt.cancel("canceller", "Test")
        assert cancelled.status == CashReceiptStatus.CANCELLED
        assert cancelled.cancelled_by == "canceller"
        assert cancelled.cancelled_at is not None
        assert cancelled.cancellation_reason == "Test"
        assert cancelled.version == 2
        trail = cancelled.audit_trail()
        assert trail[0]["action"] == "CANCEL"

    def test_cancel_cannot_from_cancelled(self, cancelled_receipt):
        with pytest.raises(ValueError, match="Cannot cancel receipt in status cancelled"):
            cancelled_receipt.cancel("canceller", "Again")


# ============================================================================
# Tests for Update Methods
# ============================================================================

class TestCashReceiptEntityUpdateMethods:
    def test_update_description(self, valid_receipt):
        updated = valid_receipt.update_description("New description", "admin")
        assert updated.description == "New description"
        assert updated.version == 2
        trail = updated.audit_trail()
        assert trail[0]["action"] == "UPDATE_DESCRIPTION"

    def test_update_description_cannot_edit_confirmed(self, confirmed_receipt):
        with pytest.raises(ValueError, match="Cannot edit receipt in status confirmed"):
            confirmed_receipt.update_description("test", "admin")

    def test_update_amount(self, valid_receipt):
        updated = valid_receipt.update_amount(Decimal("1500.00"), "admin", "Increase amount")
        assert updated.amount == Decimal("1500.00")
        assert "AMOUNT CHANGE" in updated.description
        assert updated.version == 2
        trail = updated.audit_trail()
        assert trail[0]["action"] == "UPDATE_AMOUNT"
        assert trail[0]["details"]["new_amount"] == "1500.00"
        assert trail[0]["details"]["reason"] == "Increase amount"

    def test_update_amount_cannot_reduce_below_confirmed(self):
        receipt = CashReceiptEntity(
            receipt_id=uuid4(),
            receipt_number="CR-PARTIAL",
            receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
            receipt_date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            currency="IDR",
            status=CashReceiptStatus.PARTIALLY_CONFIRMED,
            confirmed_amount=Decimal("600.00"),
        )
        with pytest.raises(ValueError, match="Cannot reduce amount below already confirmed"):
            receipt.update_amount(Decimal("500.00"), "admin", "Reduce")

    def test_update_amount_cannot_edit_confirmed(self, confirmed_receipt):
        with pytest.raises(ValueError, match="Cannot edit amount in status confirmed"):
            confirmed_receipt.update_amount(Decimal("1500.00"), "admin", "test")

    def test_update_payment_method(self, valid_receipt):
        updated = valid_receipt.update_payment_method(PaymentMethod.E_WALLET, "admin")
        assert updated.payment_method == PaymentMethod.E_WALLET
        assert updated.version == 2
        trail = updated.audit_trail()
        assert trail[0]["action"] == "UPDATE_PAYMENT_METHOD"

    def test_update_payment_method_cannot_edit_confirmed(self, confirmed_receipt):
        with pytest.raises(ValueError, match="Cannot edit payment method in status confirmed"):
            confirmed_receipt.update_payment_method(PaymentMethod.CASH, "admin")

    def test_add_allocation(self, valid_receipt):
        receipt = valid_receipt.add_allocation(
            invoice_id=uuid4(),
            invoice_number="INV-002",
            allocated_amount=Decimal("400.00"),
            remaining_invoice=Decimal("600.00"),
        )
        assert len(receipt.allocations) == 1
        assert receipt.allocations[0].allocated_amount == Decimal("400.00")
        assert receipt.allocations[0].remaining_invoice_amount == Decimal("600.00")
        assert receipt.version == 2
        trail = receipt.audit_trail()
        assert trail[0]["action"] == "ADD_ALLOCATION"
        assert trail[0]["details"]["amount"] == "400.00"

    def test_add_allocation_exceeds_amount(self, valid_receipt):
        with pytest.raises(ValueError, match="Total allocated .* exceeds"):
            valid_receipt.add_allocation(
                invoice_id=uuid4(),
                invoice_number="INV-003",
                allocated_amount=Decimal("1500.00"),
                remaining_invoice=Decimal("0.00"),
            )

    def test_remove_allocation(self, receipt_with_allocation):
        alloc_id = receipt_with_allocation.allocations[0].allocation_id
        removed = receipt_with_allocation.remove_allocation(alloc_id, "admin")
        assert len(removed.allocations) == 0
        assert removed.version == receipt_with_allocation.version + 1
        trail = removed.audit_trail()
        assert trail[0]["action"] == "REMOVE_ALLOCATION"
        assert trail[0]["details"]["allocation_id"] == str(alloc_id)

    def test_remove_allocation_not_found(self, valid_receipt):
        with pytest.raises(ValueError, match="not found"):
            valid_receipt.remove_allocation(uuid4(), "admin")

    def test_attach_file(self, valid_receipt):
        file_url = "https://storage.example.com/file1.pdf"
        updated = valid_receipt.attach_file(file_url, "admin")
        assert file_url in updated.attachment_urls
        assert updated.version == 2
        trail = updated.audit_trail()
        assert trail[0]["action"] == "ATTACH_FILE"

    def test_remove_attachment(self, valid_receipt):
        file_url = "https://storage.example.com/file1.pdf"
        updated = valid_receipt.attach_file(file_url, "admin")
        removed = updated.remove_attachment(file_url, "admin")
        assert file_url not in removed.attachment_urls
        assert removed.version == updated.version + 1
        trail = removed.audit_trail()
        assert trail[0]["action"] == "REMOVE_ATTACHMENT"


# ============================================================================
# Tests for Helper Methods
# ============================================================================

class TestCashReceiptEntityHelperMethods:
    def test_get_allocation_summary(self, receipt_with_allocation):
        summary = receipt_with_allocation.get_allocation_summary()
        assert summary["total_allocated"] == "300.00"
        assert summary["unallocated"] == "700.00"
        assert len(summary["allocations"]) == 1
        assert summary["allocation_percentage"] == 30.0

    def test_get_payment_summary(self, valid_receipt):
        summary = valid_receipt.get_payment_summary()
        assert summary["total_amount"] == "1000.00"
        assert summary["confirmed_amount"] == "0.00"
        assert summary["remaining_to_confirm"] == "1000.00"
        assert summary["confirmation_percentage"] == 0.0
        assert summary["payment_method"] == "bank_transfer"

    def test_get_verification_status(self, valid_receipt):
        status = valid_receipt.get_verification_status()
        assert status["requires_verification"] is False
        assert status["verified"] is False
        assert status["verified_by"] is None
        assert status["submitted_by"] is None

    def test_sign_and_verify_signature(self, valid_receipt):
        signed = valid_receipt.sign("signer")
        assert signed.signature is not None
        assert signed.signature.signed_by == "signer"
        assert signed.verify_signature() is True
        # Tamper
        tampered = signed.update_amount(Decimal("2000.00"), "tamper", "test")
        assert tampered.verify_signature() is False


# ============================================================================
# Tests for CashReceiptRepository
# ============================================================================

class TestCashReceiptRepository:
    async def test_save_and_get_by_id(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        retrieved = await repo.get_by_id(valid_receipt.receipt_id, legal_entity_id)
        assert retrieved == valid_receipt

    async def test_get_by_number(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        retrieved = await repo.get_by_number(valid_receipt.receipt_number, legal_entity_id)
        assert retrieved == valid_receipt

    async def test_get_by_customer(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        retrieved = await repo.get_by_customer(valid_receipt.customer_id, legal_entity_id)
        assert len(retrieved) == 1
        assert retrieved[0] == valid_receipt

        # Add another customer receipt
        other = valid_receipt.clone()
        other.customer_id = uuid4()
        await repo.save(other, legal_entity_id)
        retrieved2 = await repo.get_by_customer(valid_receipt.customer_id, legal_entity_id)
        assert len(retrieved2) == 1

    async def test_get_by_invoice(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        retrieved = await repo.get_by_invoice(valid_receipt.invoice_id, legal_entity_id)
        assert len(retrieved) == 1
        assert retrieved[0] == valid_receipt

    async def test_get_by_cash_book(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        # Set cash_book_id for receipt
        receipt = valid_receipt.update(updated_by="admin", cash_book_id=uuid4())
        await repo.save(receipt, legal_entity_id)
        retrieved = await repo.get_by_cash_book(receipt.cash_book_id, legal_entity_id)
        assert len(retrieved) == 1
        assert retrieved[0].receipt_id == receipt.receipt_id

    async def test_get_by_status(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        draft = await repo.get_by_status(CashReceiptStatus.DRAFT, legal_entity_id)
        assert len(draft) == 1
        # Submit another
        submitted = valid_receipt.clone().submit("submitter")
        await repo.save(submitted, legal_entity_id)
        draft2 = await repo.get_by_status(CashReceiptStatus.DRAFT, legal_entity_id)
        assert len(draft2) == 1  # original only
        submitted_list = await repo.get_by_status(CashReceiptStatus.SUBMITTED, legal_entity_id)
        assert len(submitted_list) == 1

    async def test_get_pending_verification(self, legal_entity_id):
        repo = CashReceiptRepository()
        pending = CashReceiptEntity(
            receipt_id=uuid4(),
            receipt_number="CR-PEND",
            receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
            receipt_date=datetime.now(UTC),
            amount=Decimal("1000.00"),
            currency="IDR",
            status=CashReceiptStatus.PENDING_VERIFICATION,
        )
        await repo.save(pending, legal_entity_id)
        retrieved = await repo.get_pending_verification(legal_entity_id)
        assert len(retrieved) == 1
        assert retrieved[0].receipt_id == pending.receipt_id

    async def test_get_by_date_range(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
        await repo.save(valid_receipt, legal_entity_id)
        results = await repo.get_by_date_range(legal_entity_id, start, end)
        assert len(results) == 1
        # Outside range
        start2 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        results2 = await repo.get_by_date_range(legal_entity_id, start2, end)
        assert len(results2) == 0

    async def test_get_total_by_customer(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        # Save as confirmed
        confirmed = valid_receipt.confirm("confirmer")
        await repo.save(confirmed, legal_entity_id)
        total = await repo.get_total_by_customer(confirmed.customer_id, legal_entity_id)
        assert total == Decimal("1000.00")

        # Add another receipt for same customer
        other = valid_receipt.clone()
        other.customer_id = confirmed.customer_id
        other.amount = Decimal("500.00")
        other.confirmed_amount = Decimal("500.00")
        other.status = CashReceiptStatus.CONFIRMED
        await repo.save(other, legal_entity_id)
        total2 = await repo.get_total_by_customer(confirmed.customer_id, legal_entity_id)
        assert total2 == Decimal("1500.00")

    async def test_count(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        assert await repo.count(legal_entity_id) == 0
        await repo.save(valid_receipt, legal_entity_id)
        assert await repo.count(legal_entity_id) == 1

    async def test_list(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        other = valid_receipt.clone()
        await repo.save(other, legal_entity_id)
        all_receipts = await repo.list(legal_entity_id, limit=1, offset=1)
        assert len(all_receipts) == 1

    async def test_get_all(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        other = valid_receipt.clone()
        await repo.save(other, legal_entity_id)
        all_receipts = await repo.get_all(legal_entity_id)
        assert len(all_receipts) == 2

    async def test_update(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        updated = valid_receipt.update_description("Updated", "admin")
        await repo.update(updated, legal_entity_id)
        retrieved = await repo.get_by_id(valid_receipt.receipt_id, legal_entity_id)
        assert retrieved.description == "Updated"

    async def test_delete(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        await repo.delete(valid_receipt.receipt_id, legal_entity_id)
        retrieved = await repo.get_by_id(valid_receipt.receipt_id, legal_entity_id)
        assert retrieved is None

    async def test_clear(self, valid_receipt, legal_entity_id):
        repo = CashReceiptRepository()
        await repo.save(valid_receipt, legal_entity_id)
        await repo.clear(legal_entity_id)
        all_receipts = await repo.get_all(legal_entity_id)
        assert len(all_receipts) == 0

    async def test_get_by_number_not_found(self, legal_entity_id):
        repo = CashReceiptRepository()
        assert await repo.get_by_number("NONEXISTENT", legal_entity_id) is None

    async def test_delete_non_existent(self, legal_entity_id):
        repo = CashReceiptRepository()
        # Should not raise
        await repo.delete(uuid4(), legal_entity_id)