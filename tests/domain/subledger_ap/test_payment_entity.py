# test_payment_entity.py
# =======================
# Comprehensive tests for domain/subledger_ap/payment_entity.py.
# Covers all enums, entity methods, audit trail, state transitions, and serialization.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.subledger_ap.payment_entity import (
    APPayment,
    APPaymentEntity,
    APPaymentMethod,
    APPaymentRepository,
    APPaymentStatus,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_payment() -> APPaymentEntity:
    """Create a valid APPaymentEntity in PENDING state."""
    now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    return APPaymentEntity.create(
        payment_number="PAY-001",
        vendor_id=uuid4(),
        vendor_name="PT Supplier",
        payment_date=now,
        amount=Decimal("1000.00"),
        currency="IDR",
        payment_method=APPaymentMethod.BANK_TRANSFER,
        created_by="tester",
        bank_account_from="ACC-001",
        bank_account_to="SUP-001",
        notes="Test payment",
    )


@pytest.fixture
def approved_payment(sample_payment) -> APPaymentEntity:
    """Return an approved payment."""
    return sample_payment.approve("approver")


@pytest.fixture
def processed_payment(approved_payment) -> APPaymentEntity:
    """Return a processed payment."""
    return approved_payment.process("processor", "REF-001")


@pytest.fixture
def confirmed_payment(processed_payment) -> APPaymentEntity:
    """Return a confirmed payment."""
    return processed_payment.confirm("confirmer", "BANK-REF-001")


# ----------------------------------------------------------------------
# APPaymentStatus Enum
# ----------------------------------------------------------------------
class TestAPPaymentStatus:
    def test_members_exist(self):
        assert hasattr(APPaymentStatus, "PENDING")
        assert hasattr(APPaymentStatus, "APPROVED")
        assert hasattr(APPaymentStatus, "PROCESSED")
        assert hasattr(APPaymentStatus, "CONFIRMED")
        assert hasattr(APPaymentStatus, "FAILED")
        assert hasattr(APPaymentStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(APPaymentStatus.PENDING, APPaymentStatus)

    def test_from_string_valid(self):
        assert APPaymentStatus.from_string("pending") == APPaymentStatus.PENDING
        assert APPaymentStatus.from_string("PENDING") == APPaymentStatus.PENDING
        assert APPaymentStatus.from_string("approved") == APPaymentStatus.APPROVED
        assert APPaymentStatus.from_string("processed") == APPaymentStatus.PROCESSED
        assert APPaymentStatus.from_string("confirmed") == APPaymentStatus.CONFIRMED
        assert APPaymentStatus.from_string("failed") == APPaymentStatus.FAILED
        assert APPaymentStatus.from_string("cancelled") == APPaymentStatus.CANCELLED

    def test_from_string_invalid_defaults_pending(self):
        assert APPaymentStatus.from_string("unknown") == APPaymentStatus.PENDING
        assert APPaymentStatus.from_string("") == APPaymentStatus.PENDING


# ----------------------------------------------------------------------
# APPaymentMethod Enum
# ----------------------------------------------------------------------
class TestAPPaymentMethod:
    def test_members_exist(self):
        assert hasattr(APPaymentMethod, "BANK_TRANSFER")
        assert hasattr(APPaymentMethod, "CASH")
        assert hasattr(APPaymentMethod, "CHECK")
        assert hasattr(APPaymentMethod, "GIRO")
        assert hasattr(APPaymentMethod, "WIRE_TRANSFER")
        assert hasattr(APPaymentMethod, "ONLINE_PAYMENT")

    def test_member_is_instance(self):
        assert isinstance(APPaymentMethod.BANK_TRANSFER, APPaymentMethod)

    def test_from_string_valid(self):
        assert APPaymentMethod.from_string("bank_transfer") == APPaymentMethod.BANK_TRANSFER
        assert APPaymentMethod.from_string("BANK_TRANSFER") == APPaymentMethod.BANK_TRANSFER
        assert APPaymentMethod.from_string("cash") == APPaymentMethod.CASH
        assert APPaymentMethod.from_string("check") == APPaymentMethod.CHECK
        assert APPaymentMethod.from_string("giro") == APPaymentMethod.GIRO
        assert APPaymentMethod.from_string("wire_transfer") == APPaymentMethod.WIRE_TRANSFER
        assert APPaymentMethod.from_string("online_payment") == APPaymentMethod.ONLINE_PAYMENT

    def test_from_string_invalid_defaults_bank_transfer(self):
        assert APPaymentMethod.from_string("unknown") == APPaymentMethod.BANK_TRANSFER
        assert APPaymentMethod.from_string("") == APPaymentMethod.BANK_TRANSFER


# ----------------------------------------------------------------------
# APPaymentEntity - Construction & Validation
# ----------------------------------------------------------------------
class TestAPPaymentEntityConstruction:
    def test_create_success(self, sample_payment):
        assert sample_payment.payment_id is not None
        assert sample_payment.payment_number == "PAY-001"
        assert sample_payment.vendor_name == "PT Supplier"
        assert sample_payment.amount == Decimal("1000.00")
        assert sample_payment.currency == "IDR"
        assert sample_payment.payment_method == APPaymentMethod.BANK_TRANSFER
        assert sample_payment.status == APPaymentStatus.PENDING
        assert sample_payment.allocated_amount == Decimal("0")
        assert sample_payment.reference_number is None
        assert sample_payment.bank_account_from == "ACC-001"
        assert sample_payment.bank_account_to == "SUP-001"
        assert sample_payment.notes == "Test payment"
        assert sample_payment.approved_by is None
        assert sample_payment.approved_at is None
        assert sample_payment.processed_by is None
        assert sample_payment.processed_at is None
        assert sample_payment.version == 1
        assert sample_payment.created_at.tzinfo == UTC
        assert sample_payment.updated_at.tzinfo == UTC

    def test_validation_amount_zero_raises(self):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            APPaymentEntity.create(
                payment_number="PAY-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                payment_date=datetime.now(UTC),
                amount=Decimal("0"),
                currency="IDR",
                payment_method=APPaymentMethod.BANK_TRANSFER,
                created_by="tester",
            )

    def test_validation_amount_negative_raises(self):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            APPaymentEntity.create(
                payment_number="PAY-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                payment_date=datetime.now(UTC),
                amount=Decimal("-100"),
                currency="IDR",
                payment_method=APPaymentMethod.BANK_TRANSFER,
                created_by="tester",
            )

    def test_validation_allocated_amount_negative_raises(self):
        with pytest.raises(ValueError, match="Allocated amount cannot be negative"):
            APPaymentEntity(
                payment_id=uuid4(),
                payment_number="PAY-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                payment_date=datetime.now(UTC),
                amount=Decimal("1000"),
                currency="IDR",
                payment_method=APPaymentMethod.BANK_TRANSFER,
                status=APPaymentStatus.PENDING,
                allocated_amount=Decimal("-100"),
                created_by="system",
            )

    def test_validation_allocated_amount_exceeds_raises(self):
        with pytest.raises(ValueError, match="exceeds payment amount"):
            APPaymentEntity(
                payment_id=uuid4(),
                payment_number="PAY-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                payment_date=datetime.now(UTC),
                amount=Decimal("1000"),
                currency="IDR",
                payment_method=APPaymentMethod.BANK_TRANSFER,
                status=APPaymentStatus.PENDING,
                allocated_amount=Decimal("1500"),
                created_by="system",
            )

    def test_validation_naive_date_auto_utc(self):
        naive = datetime(2025, 1, 15, 10, 0)
        payment = APPaymentEntity.create(
            payment_number="PAY-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            payment_date=naive,
            amount=Decimal("100"),
            currency="IDR",
            payment_method=APPaymentMethod.BANK_TRANSFER,
            created_by="tester",
        )
        assert payment.payment_date.tzinfo == UTC
        assert payment.created_at.tzinfo == UTC
        assert payment.updated_at.tzinfo == UTC

    def test_validation_version_zero_raises(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            APPaymentEntity(
                payment_id=uuid4(),
                payment_number="PAY-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                payment_date=datetime.now(UTC),
                amount=Decimal("100"),
                currency="IDR",
                payment_method=APPaymentMethod.BANK_TRANSFER,
                status=APPaymentStatus.PENDING,
                created_by="system",
                version=0,
            )


# ----------------------------------------------------------------------
# APPaymentEntity - Audit Trail
# ----------------------------------------------------------------------
class TestAPPaymentEntityAudit:
    def test_audit_trail_initial_empty(self, sample_payment):
        trail = sample_payment.get_audit_trail()
        assert trail == []

    def test_audit_trail_appends_on_approve(self, sample_payment):
        approved = sample_payment.approve("alice")
        trail = approved.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "approved"
        assert trail[0]["user_id"] == "alice"
        assert trail[0]["version"] == 2

    def test_audit_trail_appends_on_process(self, sample_payment):
        approved = sample_payment.approve("alice")
        processed = approved.process("bob", "REF-001")
        trail = processed.get_audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "approved"
        assert trail[1]["action"] == "processed"
        assert trail[1]["user_id"] == "bob"
        assert trail[1]["details"]["reference"] == "REF-001"

    def test_audit_trail_appends_on_confirm(self, sample_payment):
        approved = sample_payment.approve("alice")
        processed = approved.process("bob", "REF-001")
        confirmed = processed.confirm("carol", "BANK-REF")
        trail = confirmed.get_audit_trail()
        assert len(trail) == 3
        assert trail[2]["action"] == "confirmed"
        assert trail[2]["user_id"] == "carol"
        assert trail[2]["details"]["bank_reference"] == "BANK-REF"

    def test_audit_trail_appends_on_allocate(self, sample_payment):
        invoice_id = uuid4()
        allocated = sample_payment.allocate_to_invoice(invoice_id, Decimal("500"))
        trail = allocated.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "allocated"
        assert trail[0]["details"]["invoice_id"] == str(invoice_id)
        assert trail[0]["details"]["amount"] == "500"

    def test_audit_trail_appends_on_fail(self, sample_payment):
        failed = sample_payment.fail("dave", "Bank error")
        trail = failed.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "failed"
        assert trail[0]["user_id"] == "dave"
        assert trail[0]["details"]["reason"] == "Bank error"

    def test_audit_trail_appends_on_cancel(self, sample_payment):
        cancelled = sample_payment.cancel("eve", "No longer needed")
        trail = cancelled.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "cancelled"
        assert trail[0]["user_id"] == "eve"
        assert trail[0]["details"]["reason"] == "No longer needed"


# ----------------------------------------------------------------------
# APPaymentEntity - Business Methods
# ----------------------------------------------------------------------
class TestAPPaymentEntityBusiness:
    def test_allocate_to_invoice_partial(self, sample_payment):
        invoice_id = uuid4()
        allocated = sample_payment.allocate_to_invoice(invoice_id, Decimal("300"))
        assert allocated.allocated_amount == Decimal("300")
        assert allocated.allocated_to_invoice_id == invoice_id
        assert allocated.status == APPaymentStatus.PENDING
        assert allocated.version == sample_payment.version + 1

    def test_allocate_to_invoice_full(self, sample_payment):
        invoice_id = uuid4()
        allocated = sample_payment.allocate_to_invoice(invoice_id, Decimal("1000"))
        assert allocated.allocated_amount == Decimal("1000")
        assert allocated.allocated_to_invoice_id == invoice_id
        assert allocated.status == APPaymentStatus.PENDING
        assert allocated.version == sample_payment.version + 1

    def test_allocate_to_invoice_zero_amount_raises(self, sample_payment):
        with pytest.raises(ValueError, match="Allocation amount must be positive"):
            sample_payment.allocate_to_invoice(uuid4(), Decimal("0"))

    def test_allocate_to_invoice_negative_amount_raises(self, sample_payment):
        with pytest.raises(ValueError, match="Allocation amount must be positive"):
            sample_payment.allocate_to_invoice(uuid4(), Decimal("-100"))

    def test_allocate_to_invoice_exceeds_remaining_raises(self, sample_payment):
        with pytest.raises(ValueError, match="exceeds remaining payment"):
            sample_payment.allocate_to_invoice(uuid4(), Decimal("1500"))

    def test_approve_success(self, sample_payment):
        approved = sample_payment.approve("alice")
        assert approved.status == APPaymentStatus.APPROVED
        assert approved.approved_by == "alice"
        assert approved.approved_at is not None
        assert approved.version == sample_payment.version + 1

    def test_approve_not_pending_raises(self, approved_payment):
        with pytest.raises(ValueError, match="Cannot approve payment in status approved"):
            approved_payment.approve("alice")

    def test_process_success(self, approved_payment):
        processed = approved_payment.process("bob", "REF-001")
        assert processed.status == APPaymentStatus.PROCESSED
        assert processed.processed_by == "bob"
        assert processed.processed_at is not None
        assert processed.reference_number == "REF-001"
        assert processed.version == approved_payment.version + 1

    def test_process_not_approved_raises(self, sample_payment):
        with pytest.raises(ValueError, match="Cannot process payment in status pending"):
            sample_payment.process("bob", "REF")

    def test_confirm_success(self, processed_payment):
        confirmed = processed_payment.confirm("carol", "BANK-REF-123")
        assert confirmed.status == APPaymentStatus.CONFIRMED
        assert confirmed.reference_number == "BANK-REF-123"
        assert confirmed.version == processed_payment.version + 1

    def test_confirm_not_processed_raises(self, approved_payment):
        with pytest.raises(ValueError, match="Cannot confirm payment in status approved"):
            approved_payment.confirm("carol", "REF")

    def test_fail_from_pending(self, sample_payment):
        failed = sample_payment.fail("dave", "Insufficient funds")
        assert failed.status == APPaymentStatus.FAILED
        assert "Insufficient funds" in failed.notes
        assert failed.version == sample_payment.version + 1

    def test_fail_from_approved(self, approved_payment):
        failed = approved_payment.fail("dave", "Vendor rejected")
        assert failed.status == APPaymentStatus.FAILED

    def test_fail_from_processed(self, processed_payment):
        failed = processed_payment.fail("dave", "Bank timeout")
        assert failed.status == APPaymentStatus.FAILED

    def test_fail_from_confirmed_raises(self, confirmed_payment):
        with pytest.raises(ValueError, match="Cannot fail payment in status confirmed"):
            confirmed_payment.fail("dave", "Reason")

    def test_cancel_from_pending(self, sample_payment):
        cancelled = sample_payment.cancel("eve", "User request")
        assert cancelled.status == APPaymentStatus.CANCELLED
        assert "User request" in cancelled.notes
        assert cancelled.version == sample_payment.version + 1

    def test_cancel_from_approved(self, approved_payment):
        cancelled = approved_payment.cancel("eve", "After approval")
        assert cancelled.status == APPaymentStatus.CANCELLED

    def test_cancel_from_processed_raises(self, processed_payment):
        with pytest.raises(ValueError, match="Cannot cancel payment in status processed"):
            processed_payment.cancel("eve", "Reason")

    def test_is_fully_allocated_true(self):
        payment = APPaymentEntity(
            payment_id=uuid4(),
            payment_number="PAY-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            payment_date=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="IDR",
            payment_method=APPaymentMethod.BANK_TRANSFER,
            status=APPaymentStatus.PENDING,
            allocated_amount=Decimal("1000"),
            created_by="system",
        )
        assert payment.is_fully_allocated() is True

    def test_is_fully_allocated_false(self, sample_payment):
        assert sample_payment.is_fully_allocated() is False

    def test_get_remaining_amount(self, sample_payment):
        assert sample_payment.get_remaining_amount() == Decimal("1000")
        allocated = sample_payment.allocate_to_invoice(uuid4(), Decimal("300"))
        assert allocated.get_remaining_amount() == Decimal("700")


# ----------------------------------------------------------------------
# APPaymentEntity - State Transitions
# ----------------------------------------------------------------------
class TestAPPaymentEntityStateTransitions:
    def test_full_workflow(self, sample_payment):
        # PENDING -> APPROVED
        approved = sample_payment.approve("alice")
        assert approved.status == APPaymentStatus.APPROVED
        # APPROVED -> PROCESSED
        processed = approved.process("bob", "REF")
        assert processed.status == APPaymentStatus.PROCESSED
        # PROCESSED -> CONFIRMED
        confirmed = processed.confirm("carol", "BANK-REF")
        assert confirmed.status == APPaymentStatus.CONFIRMED

    def test_workflow_fail_from_pending(self, sample_payment):
        failed = sample_payment.fail("dave", "Error")
        assert failed.status == APPaymentStatus.FAILED

    def test_workflow_fail_from_approved(self, sample_payment):
        approved = sample_payment.approve("alice")
        failed = approved.fail("dave", "Error")
        assert failed.status == APPaymentStatus.FAILED

    def test_workflow_cancel_from_pending(self, sample_payment):
        cancelled = sample_payment.cancel("eve", "No need")
        assert cancelled.status == APPaymentStatus.CANCELLED

    def test_workflow_cancel_from_approved(self, sample_payment):
        approved = sample_payment.approve("alice")
        cancelled = approved.cancel("eve", "No need")
        assert cancelled.status == APPaymentStatus.CANCELLED

    def test_allocated_then_approve(self, sample_payment):
        allocated = sample_payment.allocate_to_invoice(uuid4(), Decimal("500"))
        approved = allocated.approve("alice")
        assert approved.status == APPaymentStatus.APPROVED
        assert approved.allocated_amount == Decimal("500")


# ----------------------------------------------------------------------
# APPaymentEntity - Serialization
# ----------------------------------------------------------------------
class TestAPPaymentEntitySerialization:
    def test_to_dict(self, sample_payment):
        d = sample_payment.to_dict()
        assert d["payment_id"] == str(sample_payment.payment_id)
        assert d["payment_number"] == "PAY-001"
        assert d["vendor_id"] == str(sample_payment.vendor_id)
        assert d["vendor_name"] == "PT Supplier"
        assert d["amount"] == "1000.00"
        assert d["currency"] == "IDR"
        assert d["payment_method"] == "bank_transfer"
        assert d["status"] == "pending"
        assert d["allocated_amount"] == "0"
        assert d["remaining_amount"] == "1000.00"
        assert d["is_fully_allocated"] is False
        assert d["reference_number"] is None
        assert d["bank_account_from"] == "ACC-001"
        assert d["bank_account_to"] == "SUP-001"
        assert d["version"] == 1

    def test_to_dict_after_approve(self, sample_payment):
        approved = sample_payment.approve("alice")
        d = approved.to_dict()
        assert d["status"] == "approved"
        assert d["approved_by"] == "alice"
        assert d["approved_at"] is not None

    def test_from_dict(self, sample_payment):
        d = sample_payment.to_dict()
        reconstructed = APPaymentEntity.from_dict(d)
        assert reconstructed.payment_id == sample_payment.payment_id
        assert reconstructed.payment_number == sample_payment.payment_number
        assert reconstructed.vendor_id == sample_payment.vendor_id
        assert reconstructed.vendor_name == sample_payment.vendor_name
        assert reconstructed.amount == sample_payment.amount
        assert reconstructed.currency == sample_payment.currency
        assert reconstructed.payment_method == sample_payment.payment_method
        assert reconstructed.status == sample_payment.status
        assert reconstructed.allocated_amount == sample_payment.allocated_amount
        assert reconstructed.reference_number == sample_payment.reference_number
        assert reconstructed.bank_account_from == sample_payment.bank_account_from
        assert reconstructed.bank_account_to == sample_payment.bank_account_to
        assert reconstructed.notes == sample_payment.notes
        assert reconstructed.version == sample_payment.version

    def test_from_dict_with_none_values(self):
        data = {
            "payment_id": str(uuid4()),
            "payment_number": "PAY-001",
            "vendor_id": str(uuid4()),
            "vendor_name": "Vendor",
            "payment_date": datetime.now(UTC).isoformat(),
            "amount": "100",
            "currency": "IDR",
            "payment_method": "bank_transfer",
            "status": "pending",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        payment = APPaymentEntity.from_dict(data)
        assert payment.allocated_to_invoice_id is None
        assert payment.allocated_amount == Decimal(0)
        assert payment.reference_number is None
        assert payment.bank_account_from is None
        assert payment.bank_account_to is None
        assert payment.approved_by is None
        assert payment.processed_by is None
        assert payment.created_by == "system"
        assert payment.version == 1


# ----------------------------------------------------------------------
# APPaymentRepository (Interface)
# ----------------------------------------------------------------------
class TestAPPaymentRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = APPaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_number_not_implemented(self):
        repo = APPaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_number("PAY-001", uuid4())

    @pytest.mark.asyncio
    async def test_get_by_vendor_not_implemented(self):
        repo = APPaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_vendor(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_pending_approval_not_implemented(self):
        repo = APPaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_pending_approval(uuid4())

    @pytest.mark.asyncio
    async def test_get_by_date_range_not_implemented(self):
        repo = APPaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_date_range(uuid4(), datetime.now(UTC), datetime.now(UTC))

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = APPaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = APPaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ----------------------------------------------------------------------
# Edge Cases & Decimal Precision
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_large_amount(self):
        huge = Decimal("9999999999.99")
        payment = APPaymentEntity.create(
            payment_number="PAY-001",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            payment_date=datetime.now(UTC),
            amount=huge,
            currency="IDR",
            payment_method=APPaymentMethod.BANK_TRANSFER,
            created_by="tester",
        )
        assert payment.amount == huge

    def test_allocation_precision(self, sample_payment):
        # Test allocation with repeating decimals
        amount = Decimal("1000")
        allocation1 = Decimal("333.33")
        allocation2 = Decimal("333.33")
        allocation3 = Decimal("333.34")
        payment = sample_payment.allocate_to_invoice(uuid4(), allocation1)
        payment = payment.allocate_to_invoice(uuid4(), allocation2)
        payment = payment.allocate_to_invoice(uuid4(), allocation3)
        assert payment.allocated_amount == amount
        assert payment.is_fully_allocated() is True

    def test_alias_ap_payment(self):
        assert APPayment is APPaymentEntity

    def test_remaining_amount_after_allocations(self, sample_payment):
        payment = sample_payment.allocate_to_invoice(uuid4(), Decimal("300"))
        assert payment.get_remaining_amount() == Decimal("700")
        payment = payment.allocate_to_invoice(uuid4(), Decimal("700"))
        assert payment.get_remaining_amount() == Decimal("0")
        assert payment.is_fully_allocated() is True
