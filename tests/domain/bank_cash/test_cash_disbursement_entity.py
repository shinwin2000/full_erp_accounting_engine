# test_cash_disbursement_entity.py
# Comprehensive tests for cash_disbursement_entity.py
# Covering all domain methods and edge cases.

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.bank_cash.cash_disbursement_entity import (
    ApprovalHistoryEntry,
    ApprovalLevel,
    BankAccountInfo,
    CashDisbursementEntity,
    CashDisbursementRepository,
    CashDisbursementStatus,
    CashDisbursementType,
    DisbursementSignature,
    PaymentAllocation,
    PaymentMethod,
    TaxWithholdingInfo,
)


# -----------------------------------------------------------------------------
# Helper functions and fixtures
# -----------------------------------------------------------------------------

def make_valid_disbursement(
    status: CashDisbursementStatus = CashDisbursementStatus.DRAFT,
    amount: Decimal = Decimal("1000.00"),
    currency: str = "IDR",
    **kwargs,
) -> CashDisbursementEntity:
    """Create a minimal valid CashDisbursementEntity for testing."""
    now = datetime.now(UTC)
    return CashDisbursementEntity(
        disbursement_id=uuid4(),
        disbursement_number="DISB-001",
        disbursement_type=CashDisbursementType.OPERATING_EXPENSE,
        disbursement_date=now - timedelta(days=1),
        amount=amount,
        currency=currency,
        status=status,
        payment_method=PaymentMethod.BANK_TRANSFER,
        description="Test disbursement",
        created_by="tester",
        **kwargs,
    )


def make_approval_history_entry() -> ApprovalHistoryEntry:
    return ApprovalHistoryEntry(
        level=ApprovalLevel.LEVEL_1,
        approver_id=uuid4(),
        approver_name="Approver One",
        action="APPROVED",
        comment="ok",
        timestamp=datetime.now(UTC),
        previous_status="submitted",
    )


def make_bank_account_info() -> BankAccountInfo:
    return BankAccountInfo(
        bank_name="BCA",
        bank_code="014",
        account_number="1234567890",
        account_name="Supplier PT",
        branch_name="Jakarta",
        swift_code="BCAIDJA",
        iban="ID123",
    )


@pytest.fixture
def valid_disbursement() -> CashDisbursementEntity:
    return make_valid_disbursement()


@pytest.fixture
def disbursement_with_tax() -> CashDisbursementEntity:
    disb = make_valid_disbursement(amount=Decimal("2000.00"))
    disb = disb.add_tax_withholding("PPH23", Decimal("0.02"), Decimal("40.00"))
    return disb


# -----------------------------------------------------------------------------
# Enum tests (already present, keep minimal)
# -----------------------------------------------------------------------------

class TestEnums:
    def test_cash_disbursement_status_members(self):
        assert CashDisbursementStatus.DRAFT.value == "draft"
        assert CashDisbursementStatus.PAID.value == "paid"

    def test_cash_disbursement_type_members(self):
        assert CashDisbursementType.SUPPLIER_PAYMENT.value == "supplier_payment"

    def test_payment_method_members(self):
        assert PaymentMethod.BANK_TRANSFER.value == "bank_transfer"

    def test_approval_level_members(self):
        assert ApprovalLevel.LEVEL_1.value == 1


# -----------------------------------------------------------------------------
# Value Objects tests
# -----------------------------------------------------------------------------

class TestApprovalHistoryEntry:
    def test_to_dict(self):
        entry = make_approval_history_entry()
        d = entry.to_dict()
        assert d["level"] == 1
        assert d["action"] == "APPROVED"
        assert d["approver_name"] == "Approver One"

    def test_construction(self):
        entry = make_approval_history_entry()
        assert isinstance(entry, ApprovalHistoryEntry)


class TestPaymentAllocation:
    def test_to_dict(self):
        alloc = PaymentAllocation(
            allocation_id=uuid4(),
            invoice_id=uuid4(),
            invoice_number="INV-001",
            allocated_amount=Decimal("500.00"),
            remaining_invoice_amount=Decimal("200.00"),
        )
        d = alloc.to_dict()
        assert d["invoice_number"] == "INV-001"
        assert d["allocated_amount"] == "500.00"

    def test_update_allocation(self):
        alloc = PaymentAllocation(
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


class TestDisbursementSignature:
    def test_create_and_verify(self, valid_disbursement):
        sig = DisbursementSignature.create(valid_disbursement, "tester")
        assert sig.signed_by == "tester"
        assert sig.disbursement_id == valid_disbursement.disbursement_id
        assert sig.version == valid_disbursement.version
        assert sig.verify(valid_disbursement) is True

        # tamper with disbursement
        tampered = valid_disbursement.update_amount(Decimal("999.00"), "hacker", "fraud")
        assert sig.verify(tampered) is False


class TestBankAccountInfo:
    def test_to_dict(self):
        info = make_bank_account_info()
        d = info.to_dict()
        assert d["bank_name"] == "BCA"
        assert d["account_number"] == "1234567890"


class TestTaxWithholdingInfo:
    def test_to_dict(self):
        tax = TaxWithholdingInfo(
            tax_type="PPH23",
            tax_rate=Decimal("0.02"),
            tax_amount=Decimal("40.00"),
            tax_id="TAX-001",
            certificate_number="CERT-123",
        )
        d = tax.to_dict()
        assert d["tax_type"] == "PPH23"
        assert d["tax_amount"] == "40.00"


# -----------------------------------------------------------------------------
# CashDisbursementEntity Tests
# -----------------------------------------------------------------------------

class TestCashDisbursementEntityConstruction:
    def test_validation_passes_with_minimal_data(self):
        disb = make_valid_disbursement()
        assert disb.disbursement_id is not None
        assert disb.amount == Decimal("1000.00")
        assert disb.status == CashDisbursementStatus.DRAFT

    def test_validation_raises_on_negative_amount(self):
        with pytest.raises(ValueError, match="Disbursement amount must be positive"):
            make_valid_disbursement(amount=Decimal("-100"))

    def test_validation_raises_on_short_number(self):
        with pytest.raises(ValueError, match="Disbursement number must be at least 3 characters"):
            make_valid_disbursement(disbursement_number="AB")

    def test_validation_raises_on_future_date(self):
        with pytest.raises(ValueError, match="Disbursement date cannot be in the future"):
            make_valid_disbursement(disbursement_date=datetime.now(UTC) + timedelta(days=10))

    def test_validation_raises_on_paid_amount_exceeds_total(self):
        with pytest.raises(ValueError, match="Paid amount .* exceeds total amount"):
            make_valid_disbursement(paid_amount=Decimal("2000.00"))

    def test_validation_raises_on_tax_exceeds_amount(self):
        with pytest.raises(ValueError, match="Total tax withheld .* exceeds amount"):
            make_valid_disbursement(
                amount=Decimal("1000"),
                tax_withholdings=[
                    TaxWithholdingInfo("PPH23", Decimal("0.1"), Decimal("1200.00"))
                ],
            )


class TestCashDisbursementEntityLifecycle:
    def test_create_records_audit(self):
        disb = make_valid_disbursement()
        assert len(disb._audit_trail) == 1
        assert disb._audit_trail[0]["action"] == "CREATE"

    def test_update(self, valid_disbursement):
        updated = valid_disbursement.update("updater", description="new desc")
        assert updated.version == 2
        assert updated.description == "new desc"
        assert updated.updated_at > valid_disbursement.updated_at
        assert len(updated._audit_trail) == 2
        assert updated._audit_trail[-1]["action"] == "UPDATE"

    def test_update_raises_if_not_editable(self, valid_disbursement):
        disb = valid_disbursement.submit("submitter")
        with pytest.raises(ValueError, match="Cannot update disbursement in status submitted"):
            disb.update("updater", description="cannot")

    def test_delete_sets_cancelled(self, valid_disbursement):
        deleted = valid_disbursement.delete("deleter", "no longer needed")
        assert deleted.status == CashDisbursementStatus.CANCELLED
        assert deleted.deleted_at is not None
        assert deleted.version == 2

    def test_delete_raises_if_paid(self, valid_disbursement):
        disb = valid_disbursement.submit("submitter")
        disb = disb.approve(1, uuid4(), "approver")
        disb = disb.mark_ready_for_payment("maker")
        disb = disb.mark_processing("processor")
        disb = disb.mark_paid("payer", Decimal("1000.00"))
        with pytest.raises(ValueError, match="Cannot delete disbursement in status paid"):
            disb.delete("deleter")

    def test_restore(self, valid_disbursement):
        deleted = valid_disbursement.delete("deleter")
        restored = deleted.restore("restorer")
        assert restored.status == CashDisbursementStatus.DRAFT
        assert restored.deleted_at is None
        assert restored.version == 3

    def test_activate(self, valid_disbursement):
        activated = valid_disbursement.activate("activator")
        assert activated.status == CashDisbursementStatus.SUBMITTED
        assert activated.submitted_by == "activator"
        assert activated.submitted_at is not None
        assert activated.version == 2

    def test_deactivate(self):
        disb = make_valid_disbursement(status=CashDisbursementStatus.SUBMITTED)
        deactivated = disb.deactivate("deactivator", "wrong")
        assert deactivated.status == CashDisbursementStatus.DRAFT
        assert deactivated.submitted_by is None
        assert deactivated.version == 2

    def test_lock_unlock(self, valid_disbursement):
        disb = valid_disbursement.submit("submitter")
        disb = disb.lock("locker", "need review")
        assert disb.status == CashDisbursementStatus.ON_HOLD
        assert disb.hold_reason == "need review"
        unlocked = disb.unlock("unlocker")
        assert unlocked.status == CashDisbursementStatus.PENDING_APPROVAL
        assert unlocked.hold_reason is None

    def test_validate_method(self, valid_disbursement):
        result = valid_disbursement.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        # create invalid case
        bad = make_valid_disbursement(amount=Decimal("1000"), paid_amount=Decimal("500"))
        bad.status = CashDisbursementStatus.PAID
        result = bad.validate()
        assert result["is_valid"] is False
        assert any("PAID but has remaining amount" in e for e in result["errors"])

    def test_to_dict_from_dict_roundtrip(self, valid_disbursement):
        d = valid_disbursement.to_dict()
        reconstructed = CashDisbursementEntity.from_dict(d)
        assert reconstructed.disbursement_id == valid_disbursement.disbursement_id
        assert reconstructed.amount == valid_disbursement.amount
        assert reconstructed.status == valid_disbursement.status
        # check nested objects
        assert reconstructed.supplier_bank_account is None  # not set

        # include bank account
        disb_with_bank = make_valid_disbursement(
            supplier_bank_account=make_bank_account_info()
        )
        d2 = disb_with_bank.to_dict()
        reconstructed2 = CashDisbursementEntity.from_dict(d2)
        assert reconstructed2.supplier_bank_account.bank_name == "BCA"

    def test_clone(self, valid_disbursement):
        cloned = valid_disbursement.clone()
        assert cloned.disbursement_id != valid_disbursement.disbursement_id
        assert cloned.disbursement_number.startswith(valid_disbursement.disbursement_number)
        assert cloned.status == CashDisbursementStatus.DRAFT
        assert cloned.paid_amount == Decimal(0)
        assert cloned.version == 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, valid_disbursement):
        snap = valid_disbursement.snapshot()
        assert snap["disbursement_id"] == str(valid_disbursement.disbursement_id)
        assert snap["amount"] == str(valid_disbursement.amount)
        assert snap["version"] == valid_disbursement.version

    def test_audit_trail(self, valid_disbursement):
        # after some actions
        disb = valid_disbursement
        disb = disb.update("u", description="x")
        disb = disb.submit("s")
        trail = disb.audit_trail(limit=2)
        assert len(trail) == 3  # CREATE + UPDATE + SUBMIT
        assert trail[-1]["action"] == "SUBMIT"

    def test_touch(self, valid_disbursement):
        touched = valid_disbursement.touch("toucher")
        assert touched.version == 2
        assert touched.updated_at > valid_disbursement.updated_at
        assert touched._audit_trail[-1]["action"] == "TOUCH"


class TestStatusCheckers:
    def test_status_methods(self):
        disb = make_valid_disbursement(status=CashDisbursementStatus.DRAFT)
        assert disb.is_draft() is True
        assert disb.is_submitted() is False
        assert disb.can_edit() is True

        disb = disb.activate("a")
        assert disb.is_submitted() is True
        assert disb.can_edit() is False
        assert disb.can_submit() is False

        disb = disb.lock("l", "hold")
        assert disb.is_on_hold() is True
        assert disb.can_hold() is False

        disb = disb.unlock("u")
        assert disb.is_pending_approval() is True
        assert disb.can_approve(level=1) is True

        disb = disb.approve(1, uuid4(), "app")
        assert disb.is_approved() is True
        assert disb.is_ready_for_payment() is False

        disb = disb.mark_ready_for_payment("r")
        assert disb.is_ready_for_payment() is True
        disb = disb.mark_processing("p")
        assert disb.is_processing() is True
        disb = disb.mark_paid("payer", Decimal("1000.00"))
        assert disb.is_paid() is True
        assert disb.is_fully_paid() is True

        # partial pay
        disb2 = make_valid_disbursement(amount=Decimal("2000.00"))
        disb2 = disb2.submit("s").approve(1, uuid4(), "a").mark_ready_for_payment("r").mark_processing("p")
        disb2 = disb2.mark_paid("payer", Decimal("500.00"))
        assert disb2.is_partially_paid() is True
        assert disb2.is_paid() is False
        assert disb2.get_remaining_amount() == Decimal("1500.00")

        disb2 = disb2.mark_paid("payer", Decimal("1500.00"))
        assert disb2.is_paid() is True
        assert disb2.get_remaining_amount() == Decimal("0.00")

        # failed
        disb_fail = make_valid_disbursement(status=CashDisbursementStatus.PROCESSING)
        disb_fail = disb_fail.mark_failed("f", "timeout")
        assert disb_fail.is_failed() is True

        # can_pay check
        disb_pay = make_valid_disbursement(status=CashDisbursementStatus.PROCESSING)
        assert disb_pay.can_pay() is True
        disb_pay = disb_pay.mark_paid("payer", disb_pay.amount)
        assert disb_pay.can_pay() is False

    def test_can_cancel(self):
        disb = make_valid_disbursement(status=CashDisbursementStatus.APPROVED)
        assert disb.can_cancel() is True
        disb = disb.mark_ready_for_payment("r").mark_processing("p")
        assert disb.can_cancel() is False  # PROCESSING cannot cancel
        disb = disb.mark_paid("payer", disb.amount)
        assert disb.can_cancel() is False  # PAID cannot cancel

        disb2 = make_valid_disbursement(status=CashDisbursementStatus.DRAFT)
        cancelled = disb2.cancel("c", "reason")
        assert cancelled.status == CashDisbursementStatus.CANCELLED


class TestWorkflowActions:
    def test_submit_without_approval(self):
        # If approval_level_required=0, submit should go to APPROVED
        disb = make_valid_disbursement(approval_level_required=0)
        submitted = disb.submit("s")
        assert submitted.status == CashDisbursementStatus.APPROVED
        assert submitted.submitted_by == "s"

    def test_approve_workflow(self):
        disb = make_valid_disbursement(approval_level_required=2)
        disb = disb.submit("s")
        # level 1 approval
        disb = disb.approve(1, uuid4(), "app1")
        assert disb.status == CashDisbursementStatus.PENDING_APPROVAL
        assert disb.current_approval_level == 1
        # level 2 approval
        disb = disb.approve(2, uuid4(), "app2")
        assert disb.status == CashDisbursementStatus.APPROVED
        assert disb.current_approval_level == 2
        assert disb.approved_by == "app2"
        assert disb.approved_at is not None

    def test_approve_raises_invalid_level(self):
        disb = make_valid_disbursement(approval_level_required=2)
        disb = disb.submit("s")
        with pytest.raises(ValueError, match="Cannot approve at level 2"):
            disb.approve(2, uuid4(), "app2")  # should be level1 first

    def test_reject(self):
        disb = make_valid_disbursement()
        disb = disb.submit("s")
        rejected = disb.reject("rejector", "not ok")
        assert rejected.status == CashDisbursementStatus.REJECTED
        assert rejected.rejection_reason == "not ok"
        assert len(rejected.approval_history) == 1
        assert rejected.approval_history[0].action == "REJECTED"

    def test_hold_release(self):
        disb = make_valid_disbursement(status=CashDisbursementStatus.PENDING_APPROVAL)
        held = disb.hold("holder", "waiting")
        assert held.status == CashDisbursementStatus.ON_HOLD
        released = held.release_hold("releaser")
        assert released.status == CashDisbursementStatus.PENDING_APPROVAL

    def test_ready_processing_pay_flow(self):
        disb = make_valid_disbursement()
        disb = disb.submit("s").approve(1, uuid4(), "a")
        ready = disb.mark_ready_for_payment("r")
        assert ready.status == CashDisbursementStatus.READY_FOR_PAYMENT
        processing = ready.mark_processing("p")
        assert processing.status == CashDisbursementStatus.PROCESSING
        paid = processing.mark_paid("payer", Decimal("1000.00"))
        assert paid.status == CashDisbursementStatus.PAID

    def test_mark_failed(self):
        disb = make_valid_disbursement(status=CashDisbursementStatus.PROCESSING)
        failed = disb.mark_failed("f", "error", "E001")
        assert failed.status == CashDisbursementStatus.FAILED

    def test_cancel(self):
        disb = make_valid_disbursement(status=CashDisbursementStatus.APPROVED)
        cancelled = disb.cancel("c", "no longer needed")
        assert cancelled.status == CashDisbursementStatus.CANCELLED
        assert "[CANCELLED] no longer needed" in cancelled.description


class TestTaxMethods:
    def test_add_tax_withholding(self, valid_disbursement):
        disb = valid_disbursement
        new_disb = disb.add_tax_withholding("PPH23", Decimal("0.02"), Decimal("20.00"), "TAX-001")
        assert len(new_disb.tax_withholdings) == 1
        assert new_disb.total_tax_withheld == Decimal("20.00")
        assert new_disb.version == 2
        assert new_disb._audit_trail[-1]["action"] == "ADD_TAX"

    def test_add_tax_withholding_exceeds_amount(self, valid_disbursement):
        disb = valid_disbursement  # amount 1000
        with pytest.raises(ValueError, match="Total tax withheld .* exceeds amount"):
            disb.add_tax_withholding("PPH23", Decimal("0.5"), Decimal("2000.00"))

    def test_remove_tax_withholding(self, valid_disbursement):
        disb = valid_disbursement.add_tax_withholding("PPH23", Decimal("0.02"), Decimal("20.00"))
        disb = disb.add_tax_withholding("PPH4", Decimal("0.01"), Decimal("10.00"))
        assert len(disb.tax_withholdings) == 2
        new_disb = disb.remove_tax_withholding(0, "remover")
        assert len(new_disb.tax_withholdings) == 1
        assert new_disb.total_tax_withheld == Decimal("10.00")
        assert new_disb.version == 3

    def test_remove_tax_withholding_out_of_range(self, valid_disbursement):
        disb = valid_disbursement.add_tax_withholding("PPH23", Decimal("0.02"), Decimal("20.00"))
        with pytest.raises(ValueError, match="Tax withholding index 5 out of range"):
            disb.remove_tax_withholding(5, "remover")

    def test_get_net_amount(self, disbursement_with_tax):
        assert disbursement_with_tax.get_net_amount() == Decimal("1960.00")

    def test_update_amount_proportional_tax(self, valid_disbursement):
        disb = valid_disbursement.add_tax_withholding("PPH23", Decimal("0.02"), Decimal("20.00"))
        # total amount 1000, tax 20
        new_disb = disb.update_amount(Decimal("2000.00"), "updater", "increase")
        assert new_disb.amount == Decimal("2000.00")
        assert new_disb.total_tax_withheld == Decimal("40.00")  # proportional
        assert new_disb.tax_withholdings[0].tax_amount == Decimal("40.00")


class TestAllocationMethods:
    def test_add_allocation(self, valid_disbursement):
        disb = valid_disbursement
        inv_id = uuid4()
        new_disb = disb.add_allocation(inv_id, "INV-001", Decimal("300.00"), Decimal("700.00"))
        assert len(new_disb.allocations) == 1
        assert new_disb.allocations[0].invoice_number == "INV-001"
        assert new_disb.allocations[0].allocated_amount == Decimal("300.00")
        assert new_disb.version == 2

    def test_add_allocation_exceeds_total(self, valid_disbursement):
        disb = valid_disbursement
        disb = disb.add_allocation(uuid4(), "INV-001", Decimal("600.00"), Decimal("400.00"))
        with pytest.raises(ValueError, match="Total allocated 1100.00 exceeds disbursement amount 1000.00"):
            disb.add_allocation(uuid4(), "INV-002", Decimal("500.00"), Decimal("500.00"))

    def test_remove_allocation(self, valid_disbursement):
        inv1 = uuid4()
        disb = valid_disbursement.add_allocation(inv1, "INV-001", Decimal("300.00"), Decimal("700.00"))
        disb = disb.add_allocation(uuid4(), "INV-002", Decimal("200.00"), Decimal("800.00"))
        removal_id = disb.allocations[0].allocation_id
        new_disb = disb.remove_allocation(removal_id, "remover")
        assert len(new_disb.allocations) == 1
        assert new_disb.allocations[0].invoice_number == "INV-002"
        assert new_disb.version == 3

    def test_remove_allocation_not_found(self, valid_disbursement):
        disb = valid_disbursement.add_allocation(uuid4(), "INV-001", Decimal("300.00"), Decimal("700.00"))
        with pytest.raises(ValueError, match="Allocation .* not found"):
            disb.remove_allocation(uuid4(), "remover")

    def test_payment_updates_allocations(self):
        disb = make_valid_disbursement(amount=Decimal("1000.00"))
        inv1 = uuid4()
        disb = disb.add_allocation(inv1, "INV-001", Decimal("0.00"), Decimal("500.00"))
        disb = disb.add_allocation(uuid4(), "INV-002", Decimal("0.00"), Decimal("500.00"))
        # submit/approve/ready/processing
        disb = disb.submit("s").approve(1, uuid4(), "a").mark_ready_for_payment("r").mark_processing("p")
        # pay 600
        paid = disb.mark_paid("payer", Decimal("600.00"))
        # allocation should be updated: first invoice gets 500, second gets 100
        assert paid.allocations[0].allocated_amount == Decimal("500.00")
        assert paid.allocations[1].allocated_amount == Decimal("100.00")
        assert paid.paid_amount == Decimal("600.00")
        assert paid.status == CashDisbursementStatus.PARTIALLY_PAID

        # pay rest
        paid2 = paid.mark_paid("payer", Decimal("400.00"))
        assert paid2.allocations[0].allocated_amount == Decimal("500.00")
        assert paid2.allocations[1].allocated_amount == Decimal("500.00")
        assert paid2.status == CashDisbursementStatus.PAID


class TestAttachmentAndUrgency:
    def test_attach_file(self, valid_disbursement):
        disb = valid_disbursement
        new_disb = disb.attach_file("http://file.pdf", "uploader", is_supporting=False)
        assert "http://file.pdf" in new_disb.attachment_urls
        assert new_disb.version == 2

        new_disb2 = disb.attach_file("http://support.pdf", "uploader", is_supporting=True)
        assert "http://support.pdf" in new_disb2.supporting_documents

    def test_remove_attachment(self, valid_disbursement):
        disb = valid_disbursement.attach_file("http://file1.pdf", "u")
        disb = disb.attach_file("http://file2.pdf", "u")
        new_disb = disb.remove_attachment("http://file1.pdf", "remover", is_supporting=False)
        assert "http://file1.pdf" not in new_disb.attachment_urls
        assert "http://file2.pdf" in new_disb.attachment_urls

    def test_mark_unmark_urgent(self, valid_disbursement):
        disb = valid_disbursement
        urgent = disb.mark_urgent("u", "due tomorrow")
        assert urgent.is_urgent is True
        assert urgent.urgency_reason == "due tomorrow"
        normal = urgent.unmark_urgent("u")
        assert normal.is_urgent is False
        assert normal.urgency_reason is None


class TestSummaryMethods:
    def test_get_approval_summary(self, valid_disbursement):
        disb = make_valid_disbursement(approval_level_required=2)
        disb = disb.submit("s")
        disb = disb.approve(1, uuid4(), "app1")
        summary = disb.get_approval_summary()
        assert summary["required_level"] == 2
        assert summary["current_level"] == 1
        assert summary["completed"] is False
        assert summary["next_required_level"] == 2
        assert len(summary["history"]) == 1

    def test_get_payment_summary(self, disbursement_with_tax):
        disb = disbursement_with_tax.add_allocation(uuid4(), "INV-001", Decimal("500.00"), Decimal("500.00"))
        summary = disb.get_payment_summary()
        assert summary["total_amount"] == "2000.00"
        assert summary["paid_amount"] == "0.00"
        assert summary["net_amount"] == "1960.00"
        assert summary["total_tax_withheld"] == "40.00"
        assert summary["allocation_summary"]["total_allocated"] == "500.00"


class TestSignature:
    def test_sign_and_verify(self, valid_disbursement):
        signed = valid_disbursement.sign("signer")
        assert signed.signature is not None
        assert signed.signature.signed_by == "signer"
        assert signed.verify_signature() is True

        # tamper
        tampered = signed.update("hacker", amount=Decimal("999.00"))
        assert tampered.verify_signature() is False


class TestPrivateMethods:
    def test_calculate_signature(self, valid_disbursement):
        sig = valid_disbursement._calculate_signature()
        assert isinstance(sig, DisbursementSignature)
        assert sig.disbursement_id == valid_disbursement.disbursement_id

    def test_record_audit(self, valid_disbursement):
        # already tested via actions
        pass

    def test_copy(self, valid_disbursement):
        copy_obj = valid_disbursement._copy()
        assert copy_obj.disbursement_id == valid_disbursement.disbursement_id
        assert copy_obj.version == valid_disbursement.version
        # ensure it's a new object
        assert copy_obj is not valid_disbursement


# -----------------------------------------------------------------------------
# Repository Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCashDisbursementRepository:
    async def test_save_and_get_by_id(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        disb = make_valid_disbursement()
        await repo.save(disb, legal_entity_id)

        retrieved = await repo.get_by_id(disb.disbursement_id, legal_entity_id)
        assert retrieved is not None
        assert retrieved.disbursement_id == disb.disbursement_id

    async def test_get_by_number(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        disb = make_valid_disbursement(disbursement_number="DISB-999")
        await repo.save(disb, legal_entity_id)

        retrieved = await repo.get_by_number("DISB-999", legal_entity_id)
        assert retrieved is not None
        assert retrieved.disbursement_number == "DISB-999"

    async def test_get_by_supplier(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        supplier_id = uuid4()
        disb1 = make_valid_disbursement(supplier_id=supplier_id, supplier_name="Sup1")
        disb2 = make_valid_disbursement(supplier_id=supplier_id, supplier_name="Sup2")
        disb3 = make_valid_disbursement(supplier_id=uuid4(), supplier_name="Sup3")
        await repo.save(disb1, legal_entity_id)
        await repo.save(disb2, legal_entity_id)
        await repo.save(disb3, legal_entity_id)

        results = await repo.get_by_supplier(supplier_id, legal_entity_id)
        assert len(results) == 2
        assert all(d.supplier_id == supplier_id for d in results)

    async def test_get_by_invoice(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        inv_id = uuid4()
        disb1 = make_valid_disbursement(invoice_id=inv_id)
        disb2 = make_valid_disbursement(invoice_id=inv_id)
        disb3 = make_valid_disbursement(invoice_id=uuid4())
        await repo.save(disb1, legal_entity_id)
        await repo.save(disb2, legal_entity_id)
        await repo.save(disb3, legal_entity_id)

        results = await repo.get_by_invoice(inv_id, legal_entity_id)
        assert len(results) == 2

    async def test_get_by_status(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        d1 = make_valid_disbursement(status=CashDisbursementStatus.APPROVED)
        d2 = make_valid_disbursement(status=CashDisbursementStatus.APPROVED)
        d3 = make_valid_disbursement(status=CashDisbursementStatus.DRAFT)
        await repo.save(d1, legal_entity_id)
        await repo.save(d2, legal_entity_id)
        await repo.save(d3, legal_entity_id)

        results = await repo.get_by_status(CashDisbursementStatus.APPROVED, legal_entity_id)
        assert len(results) == 2

    async def test_get_pending_approval(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        d1 = make_valid_disbursement(status=CashDisbursementStatus.PENDING_APPROVAL, current_approval_level=0)
        d2 = make_valid_disbursement(status=CashDisbursementStatus.PENDING_APPROVAL, current_approval_level=1)
        d3 = make_valid_disbursement(status=CashDisbursementStatus.APPROVED)
        await repo.save(d1, legal_entity_id)
        await repo.save(d2, legal_entity_id)
        await repo.save(d3, legal_entity_id)

        results = await repo.get_pending_approval(legal_entity_id)
        assert len(results) == 2
        results_l1 = await repo.get_pending_approval(legal_entity_id, approver_level=2)
        assert len(results_l1) == 1  # only d2 needs level 2? Actually current_approval_level=1 => next is 2
        # d1 current 0 => next level 1, so not included
        assert results_l1[0].disbursement_id == d2.disbursement_id

    async def test_get_by_date_range(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        now = datetime.now(UTC)
        d1 = make_valid_disbursement(disbursement_date=now - timedelta(days=2))
        d2 = make_valid_disbursement(disbursement_date=now - timedelta(days=1))
        d3 = make_valid_disbursement(disbursement_date=now + timedelta(days=1))
        await repo.save(d1, legal_entity_id)
        await repo.save(d2, legal_entity_id)
        await repo.save(d3, legal_entity_id)

        start = now - timedelta(days=2)
        end = now
        results = await repo.get_by_date_range(legal_entity_id, start, end)
        assert len(results) == 2
        assert d1.disbursement_id in [r.disbursement_id for r in results]
        assert d2.disbursement_id in [r.disbursement_id for r in results]

    async def test_get_urgent(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        d1 = make_valid_disbursement(is_urgent=True, status=CashDisbursementStatus.PENDING_APPROVAL)
        d2 = make_valid_disbursement(is_urgent=True, status=CashDisbursementStatus.PAID)
        d3 = make_valid_disbursement(is_urgent=False)
        await repo.save(d1, legal_entity_id)
        await repo.save(d2, legal_entity_id)
        await repo.save(d3, legal_entity_id)

        results = await repo.get_urgent(legal_entity_id)
        assert len(results) == 1
        assert results[0].disbursement_id == d1.disbursement_id

    async def test_get_total_by_supplier(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        supplier = uuid4()
        d1 = make_valid_disbursement(supplier_id=supplier, amount=Decimal("500"), status=CashDisbursementStatus.PAID)
        d2 = make_valid_disbursement(supplier_id=supplier, amount=Decimal("300"), status=CashDisbursementStatus.PAID)
        d3 = make_valid_disbursement(supplier_id=supplier, amount=Decimal("200"), status=CashDisbursementStatus.DRAFT)
        await repo.save(d1, legal_entity_id)
        await repo.save(d2, legal_entity_id)
        await repo.save(d3, legal_entity_id)

        total = await repo.get_total_by_supplier(supplier, legal_entity_id)
        assert total == Decimal("800.00")

    async def test_count_and_list(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        for _ in range(5):
            await repo.save(make_valid_disbursement(), legal_entity_id)

        count = await repo.count(legal_entity_id)
        assert count == 5

        results = await repo.list(legal_entity_id, limit=2, offset=1)
        assert len(results) == 2

    async def test_update_and_delete(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        disb = make_valid_disbursement()
        await repo.save(disb, legal_entity_id)

        updated = disb.update("u", description="new")
        await repo.update(updated, legal_entity_id)
        retrieved = await repo.get_by_id(disb.disbursement_id, legal_entity_id)
        assert retrieved.description == "new"

        await repo.delete(disb.disbursement_id, legal_entity_id)
        retrieved = await repo.get_by_id(disb.disbursement_id, legal_entity_id)
        assert retrieved is None

    async def test_clear(self):
        repo = CashDisbursementRepository()
        legal_entity_id = uuid4()
        await repo.save(make_valid_disbursement(), legal_entity_id)
        await repo.clear(legal_entity_id)
        assert await repo.count(legal_entity_id) == 0


# -----------------------------------------------------------------------------
# Run with: pytest test_cash_disbursement_entity.py -v
# -----------------------------------------------------------------------------