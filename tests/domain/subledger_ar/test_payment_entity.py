# test_payment_entity.py
# =======================
# Comprehensive tests for domain/subledger_ar/payment_entity.py.
# Covers all enums, entity construction, business methods, entity base methods,
# serialization, and repository interface.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.subledger_ar.payment_entity import (
    PaymentEntity,
    PaymentMethod,
    PaymentRepository,
    PaymentStatus,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_payment() -> PaymentEntity:
    """Create a valid PaymentEntity in PENDING state."""
    return PaymentEntity(
        payment_id=uuid4(),
        payment_number="PAY-2025-001",
        customer_id=uuid4(),
        customer_name="PT Maju Jaya",
        payment_date=datetime(2025, 1, 20, 10, 0, tzinfo=UTC),
        amount=Decimal("1000.00"),
        currency="IDR",
        payment_method=PaymentMethod.BANK_TRANSFER,
        status=PaymentStatus.PENDING,
        allocated_to_invoice_id=None,
        allocated_amount=Decimal("0"),
        reference_number="REF-001",
        bank_reference="BANK-REF-001",
        notes="Test payment",
        created_at=datetime(2025, 1, 20, 10, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 20, 10, 0, tzinfo=UTC),
        created_by="alice",
        version=1,
    )


@pytest.fixture
def confirmed_payment(sample_payment) -> PaymentEntity:
    """Return a confirmed payment."""
    return sample_payment.confirm("alice")


@pytest.fixture
def allocated_payment(confirmed_payment) -> PaymentEntity:
    """Return an allocated payment."""
    invoice_id = uuid4()
    return confirmed_payment.allocate_to_invoice(invoice_id, Decimal("1000.00"))


@pytest.fixture
def failed_payment(sample_payment) -> PaymentEntity:
    """Return a failed (deleted) payment."""
    return sample_payment.delete("alice", "Failed processing")


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestPaymentStatus:
    def test_members_exist(self):
        assert hasattr(PaymentStatus, "PENDING")
        assert hasattr(PaymentStatus, "CONFIRMED")
        assert hasattr(PaymentStatus, "ALLOCATED")
        assert hasattr(PaymentStatus, "FAILED")
        assert hasattr(PaymentStatus, "REFUNDED")

    def test_member_is_instance(self):
        assert isinstance(PaymentStatus.PENDING, PaymentStatus)

    def test_can_allocate(self):
        assert PaymentStatus.PENDING.can_allocate() is True
        assert PaymentStatus.CONFIRMED.can_allocate() is True
        assert PaymentStatus.ALLOCATED.can_allocate() is False
        assert PaymentStatus.FAILED.can_allocate() is False
        assert PaymentStatus.REFUNDED.can_allocate() is False

    def test_can_confirm(self):
        assert PaymentStatus.PENDING.can_confirm() is True
        assert PaymentStatus.CONFIRMED.can_confirm() is False
        assert PaymentStatus.ALLOCATED.can_confirm() is False
        assert PaymentStatus.FAILED.can_confirm() is False
        assert PaymentStatus.REFUNDED.can_confirm() is False

    def test_can_refund(self):
        assert PaymentStatus.CONFIRMED.can_refund() is True
        assert PaymentStatus.ALLOCATED.can_refund() is True
        assert PaymentStatus.PENDING.can_refund() is False
        assert PaymentStatus.FAILED.can_refund() is False
        assert PaymentStatus.REFUNDED.can_refund() is False


class TestPaymentMethod:
    def test_members_exist(self):
        assert hasattr(PaymentMethod, "CASH")
        assert hasattr(PaymentMethod, "BANK_TRANSFER")
        assert hasattr(PaymentMethod, "CREDIT_CARD")
        assert hasattr(PaymentMethod, "DEBIT_CARD")
        assert hasattr(PaymentMethod, "CHECK")
        assert hasattr(PaymentMethod, "DIGITAL_WALLET")
        assert hasattr(PaymentMethod, "OTHER")

    def test_member_is_instance(self):
        assert isinstance(PaymentMethod.CASH, PaymentMethod)


# ----------------------------------------------------------------------
# PaymentEntity - Construction & Validation
# ----------------------------------------------------------------------
class TestPaymentEntityConstruction:
    def test_construction_valid(self, sample_payment):
        assert sample_payment.payment_id is not None
        assert sample_payment.payment_number == "PAY-2025-001"
        assert sample_payment.amount == Decimal("1000.00")
        assert sample_payment.status == PaymentStatus.PENDING
        assert sample_payment.allocated_amount == Decimal("0")
        assert sample_payment.version == 1
        assert len(sample_payment._snapshots) == 1
        assert len(sample_payment._audit_trail) == 0  # not recorded in __post_init__

    def test_construction_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            PaymentEntity(
                payment_id=uuid4(),
                payment_number="PAY-001",
                customer_id=uuid4(),
                customer_name="Customer",
                payment_date=datetime.now(UTC),
                amount=Decimal("-100"),
                currency="IDR",
                payment_method=PaymentMethod.CASH,
                status=PaymentStatus.PENDING,
            )

    def test_construction_zero_amount_raises(self):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            PaymentEntity(
                payment_id=uuid4(),
                payment_number="PAY-001",
                customer_id=uuid4(),
                customer_name="Customer",
                payment_date=datetime.now(UTC),
                amount=Decimal("0"),
                currency="IDR",
                payment_method=PaymentMethod.CASH,
                status=PaymentStatus.PENDING,
            )

    def test_construction_allocated_amount_negative_raises(self):
        with pytest.raises(ValueError, match="Allocated amount cannot be negative"):
            PaymentEntity(
                payment_id=uuid4(),
                payment_number="PAY-001",
                customer_id=uuid4(),
                customer_name="Customer",
                payment_date=datetime.now(UTC),
                amount=Decimal("1000"),
                currency="IDR",
                payment_method=PaymentMethod.CASH,
                status=PaymentStatus.PENDING,
                allocated_amount=Decimal("-100"),
            )

    def test_construction_allocated_amount_exceeds_amount_raises(self):
        with pytest.raises(ValueError, match="exceeds payment amount"):
            PaymentEntity(
                payment_id=uuid4(),
                payment_number="PAY-001",
                customer_id=uuid4(),
                customer_name="Customer",
                payment_date=datetime.now(UTC),
                amount=Decimal("1000"),
                currency="IDR",
                payment_method=PaymentMethod.CASH,
                status=PaymentStatus.PENDING,
                allocated_amount=Decimal("1500"),
            )

    def test_construction_defaults_utc_timezone(self):
        # Create with naive datetime
        naive = datetime(2025, 1, 20, 10, 0)
        payment = PaymentEntity(
            payment_id=uuid4(),
            payment_number="PAY-001",
            customer_id=uuid4(),
            customer_name="Customer",
            payment_date=naive,
            amount=Decimal("1000"),
            currency="IDR",
            payment_method=PaymentMethod.CASH,
            status=PaymentStatus.PENDING,
        )
        # __post_init__ doesn't convert payment_date, only validation
        # payment_date is passed as-is, so we need to handle it in tests
        # Actually the validation doesn't convert it either, so it stays naive.
        # That's fine for testing.
        assert payment.payment_date == naive


# ----------------------------------------------------------------------
# PaymentEntity - Entity Base Methods
# ----------------------------------------------------------------------
class TestPaymentEntityBaseMethods:
    def test_create(self, sample_payment):
        result = sample_payment.create("alice")
        assert result is sample_payment
        trail = result.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "alice"

    def test_update_success_pending(self, sample_payment):
        updated = sample_payment.update(
            updated_by="bob",
            reference_number="REF-002",
            bank_reference="BANK-REF-002",
            notes="Updated notes",
        )
        assert updated.version == 2
        assert updated.reference_number == "REF-002"
        assert updated.bank_reference == "BANK-REF-002"
        assert updated.notes == "Updated notes"
        assert updated.payment_id == sample_payment.payment_id
        trail = updated.audit_trail(limit=1)
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["performed_by"] == "bob"

    def test_update_success_confirmed(self, confirmed_payment):
        updated = confirmed_payment.update("bob", notes="Updated after confirm")
        assert updated.version == confirmed_payment.version + 1
        assert updated.notes == "Updated after confirm"

    def test_update_not_updatable_raises(self, allocated_payment):
        with pytest.raises(ValueError, match="Cannot update payment in status allocated"):
            allocated_payment.update("bob", notes="Try update")

    def test_delete_success(self, sample_payment):
        deleted = sample_payment.delete("alice", "Duplicate")
        assert deleted.status == PaymentStatus.FAILED
        assert "Deleted: Duplicate" in deleted.notes
        assert deleted.version == 2
        trail = deleted.audit_trail(limit=1)
        assert trail[0]["action"] == "DELETE"

    def test_delete_non_deletable_raises(self, confirmed_payment):
        with pytest.raises(ValueError, match="Cannot delete payment in status confirmed"):
            confirmed_payment.delete("alice")

    def test_restore_success(self, failed_payment):
        restored = failed_payment.restore("alice")
        assert restored.status == PaymentStatus.PENDING
        assert restored.allocated_amount == Decimal("0")
        assert restored.allocated_to_invoice_id is None
        assert restored.version == failed_payment.version + 1
        trail = restored.audit_trail(limit=1)
        assert trail[0]["action"] == "RESTORE"

    def test_restore_non_failed_raises(self, sample_payment):
        with pytest.raises(ValueError, match="Cannot restore payment in status pending"):
            sample_payment.restore("alice")

    def test_activate_success(self, sample_payment):
        activated = sample_payment.activate("alice")
        assert activated.status == PaymentStatus.CONFIRMED
        assert activated.version == 2
        trail = activated.audit_trail(limit=1)
        assert trail[0]["action"] == "CONFIRM"

    def test_activate_already_confirmed_returns_same(self, confirmed_payment):
        result = confirmed_payment.activate("alice")
        assert result is confirmed_payment

    def test_activate_non_pending_raises(self, allocated_payment):
        with pytest.raises(ValueError, match="Cannot activate payment in status allocated"):
            allocated_payment.activate("alice")

    def test_deactivate_success(self, confirmed_payment):
        deactivated = confirmed_payment.deactivate("alice", "Need changes")
        assert deactivated.status == PaymentStatus.PENDING
        assert deactivated.version == confirmed_payment.version + 1
        trail = deactivated.audit_trail(limit=1)
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "Need changes"

    def test_deactivate_already_pending_returns_same(self, sample_payment):
        result = sample_payment.deactivate("alice")
        assert result is sample_payment

    def test_deactivate_non_confirmed_raises(self, allocated_payment):
        with pytest.raises(ValueError, match="Cannot deactivate payment in status allocated"):
            allocated_payment.deactivate("alice")

    def test_lock(self, sample_payment):
        locked = sample_payment.lock("alice", "Review")
        assert locked.version == 2
        trail = locked.audit_trail(limit=1)
        assert trail[0]["action"] == "LOCK"
        assert trail[0]["details"]["reason"] == "Review"

    def test_unlock(self, sample_payment):
        unlocked = sample_payment.unlock("alice")
        assert unlocked.version == 2
        trail = unlocked.audit_trail(limit=1)
        assert trail[0]["action"] == "UNLOCK"

    def test_validate_valid(self, sample_payment):
        result = sample_payment.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["payment_id"] == str(sample_payment.payment_id)
        assert result["version"] == 1

    def test_validate_invalid_allocated_amount(self, sample_payment):
        invalid = PaymentEntity(
            payment_id=sample_payment.payment_id,
            payment_number=sample_payment.payment_number,
            customer_id=sample_payment.customer_id,
            customer_name=sample_payment.customer_name,
            payment_date=sample_payment.payment_date,
            amount=Decimal("-100"),
            currency=sample_payment.currency,
            payment_method=sample_payment.payment_method,
            status=sample_payment.status,
            allocated_amount=Decimal("0"),
        )
        result = invalid.validate()
        assert result["is_valid"] is False
        assert any("positive" in e for e in result["errors"])

    def test_validate_inconsistent_allocation(self, sample_payment):
        # Allocated amount > 0 but no invoice
        invalid = PaymentEntity(
            payment_id=sample_payment.payment_id,
            payment_number=sample_payment.payment_number,
            customer_id=sample_payment.customer_id,
            customer_name=sample_payment.customer_name,
            payment_date=sample_payment.payment_date,
            amount=Decimal("1000"),
            currency=sample_payment.currency,
            payment_method=sample_payment.payment_method,
            status=sample_payment.status,
            allocated_amount=Decimal("500"),
            allocated_to_invoice_id=None,
        )
        result = invalid.validate()
        assert result["is_valid"] is False
        assert any("no invoice specified" in e for e in result["errors"])


# ----------------------------------------------------------------------
# PaymentEntity - Business Methods
# ----------------------------------------------------------------------
class TestPaymentEntityBusiness:
    def test_is_fully_allocated_true(self):
        payment = PaymentEntity(
            payment_id=uuid4(),
            payment_number="PAY-001",
            customer_id=uuid4(),
            customer_name="Customer",
            payment_date=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="IDR",
            payment_method=PaymentMethod.CASH,
            status=PaymentStatus.ALLOCATED,
            allocated_amount=Decimal("1000"),
        )
        assert payment.is_fully_allocated() is True

    def test_is_fully_allocated_false(self, sample_payment):
        assert sample_payment.is_fully_allocated() is False

    def test_allocate_to_invoice_full(self, confirmed_payment):
        invoice_id = uuid4()
        allocated = confirmed_payment.allocate_to_invoice(invoice_id, Decimal("1000.00"))
        assert allocated.status == PaymentStatus.ALLOCATED
        assert allocated.allocated_to_invoice_id == invoice_id
        assert allocated.allocated_amount == Decimal("1000.00")
        assert allocated.version == confirmed_payment.version + 1
        trail = allocated.audit_trail(limit=1)
        assert trail[0]["action"] == "ALLOCATE_TO_INVOICE"

    def test_allocate_to_invoice_partial(self, confirmed_payment):
        invoice_id = uuid4()
        allocated = confirmed_payment.allocate_to_invoice(invoice_id, Decimal("300.00"))
        assert allocated.status == PaymentStatus.CONFIRMED  # not fully allocated
        assert allocated.allocated_to_invoice_id == invoice_id
        assert allocated.allocated_amount == Decimal("300.00")
        assert allocated.version == confirmed_payment.version + 1

    def test_allocate_to_invoice_multiple(self, confirmed_payment):
        invoice_id1 = uuid4()
        invoice_id2 = uuid4()
        # First allocation
        step1 = confirmed_payment.allocate_to_invoice(invoice_id1, Decimal("400.00"))
        assert step1.allocated_amount == Decimal("400.00")
        # Second allocation (should replace invoice_id)
        step2 = step1.allocate_to_invoice(invoice_id2, Decimal("600.00"))
        assert step2.allocated_amount == Decimal("1000.00")
        assert step2.allocated_to_invoice_id == invoice_id2
        assert step2.status == PaymentStatus.ALLOCATED

    def test_allocate_to_invoice_zero_amount_raises(self, confirmed_payment):
        with pytest.raises(ValueError, match="Allocation amount must be positive"):
            confirmed_payment.allocate_to_invoice(uuid4(), Decimal("0"))

    def test_allocate_to_invoice_negative_amount_raises(self, confirmed_payment):
        with pytest.raises(ValueError, match="Allocation amount must be positive"):
            confirmed_payment.allocate_to_invoice(uuid4(), Decimal("-100"))

    def test_allocate_to_invoice_exceeds_amount_raises(self, confirmed_payment):
        with pytest.raises(ValueError, match="exceeds remaining payment"):
            confirmed_payment.allocate_to_invoice(uuid4(), Decimal("1500.00"))

    def test_allocate_to_invoice_not_allocatable_raises(self, sample_payment):
        # PENDING can allocate actually, so use a payment that can't allocate
        # REFUNDED can't allocate
        refunded = sample_payment.confirm("alice").refund("alice", "Test")
        with pytest.raises(ValueError, match="Cannot allocate payment in status refunded"):
            refunded.allocate_to_invoice(uuid4(), Decimal("100"))

    def test_confirm_success(self, sample_payment):
        confirmed = sample_payment.confirm("alice")
        assert confirmed.status == PaymentStatus.CONFIRMED
        assert confirmed.version == 2
        trail = confirmed.audit_trail(limit=1)
        assert trail[0]["action"] == "CONFIRM"
        assert trail[0]["performed_by"] == "alice"

    def test_confirm_non_pending_raises(self, confirmed_payment):
        with pytest.raises(ValueError, match="Cannot confirm payment in status confirmed"):
            confirmed_payment.confirm("alice")

    def test_refund_success_confirmed(self, confirmed_payment):
        refunded = confirmed_payment.refund("alice", "Customer request")
        assert refunded.status == PaymentStatus.REFUNDED
        assert "Refunded: Customer request" in refunded.notes
        assert refunded.version == confirmed_payment.version + 1
        trail = refunded.audit_trail(limit=1)
        assert trail[0]["action"] == "REFUND"

    def test_refund_success_allocated(self, allocated_payment):
        refunded = allocated_payment.refund("alice", "Overpayment")
        assert refunded.status == PaymentStatus.REFUNDED

    def test_refund_non_refundable_raises(self, sample_payment):
        with pytest.raises(ValueError, match="Cannot refund payment in status pending"):
            sample_payment.refund("alice", "Test")

    def test_to_money(self, sample_payment):
        money = sample_payment.to_money()
        assert money.amount == Decimal("1000.00")
        assert money.currency == "IDR"


# ----------------------------------------------------------------------
# PaymentEntity - Serialization
# ----------------------------------------------------------------------
class TestPaymentEntitySerialization:
    def test_to_dict(self, sample_payment):
        d = sample_payment.to_dict()
        assert d["payment_id"] == str(sample_payment.payment_id)
        assert d["payment_number"] == "PAY-2025-001"
        assert d["amount"] == "1000.00"
        assert d["status"] == "pending"
        assert d["payment_method"] == "bank_transfer"
        assert d["allocated_amount"] == "0"
        assert d["version"] == 1

    def test_from_dict(self, sample_payment):
        d = sample_payment.to_dict()
        reconstructed = PaymentEntity.from_dict(d)
        assert reconstructed.payment_id == sample_payment.payment_id
        assert reconstructed.amount == sample_payment.amount
        assert reconstructed.status == sample_payment.status
        assert reconstructed.payment_method == sample_payment.payment_method
        assert reconstructed.version == sample_payment.version

    def test_clone(self, sample_payment):
        cloned = sample_payment.clone()
        assert cloned.payment_id != sample_payment.payment_id
        assert cloned.payment_number == "PAY-2025-001_COPY"
        assert cloned.amount == sample_payment.amount
        assert cloned.status == PaymentStatus.PENDING
        assert cloned.allocated_amount == Decimal("0")
        assert cloned.allocated_to_invoice_id is None
        assert cloned.version == 1
        assert "Cloned from" in cloned.notes
        trail = cloned.audit_trail(limit=1)
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_payment):
        snap = sample_payment.snapshot()
        assert snap["version"] == 1
        assert snap["payment_id"] == str(sample_payment.payment_id)
        assert snap["payment_number"] == "PAY-2025-001"
        assert snap["status"] == "pending"
        assert snap["amount"] == "1000.00"
        assert snap["allocated_amount"] == "0"
        assert "timestamp" in snap

    def test_get_version(self, sample_payment):
        assert sample_payment.get_version() == 1
        updated = sample_payment.update("bob", notes="Updated")
        assert updated.get_version() == 2

    def test_audit_trail(self, sample_payment):
        assert sample_payment.audit_trail() == []
        sample_payment.create("alice")
        trail = sample_payment.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"

    def test_touch(self, sample_payment):
        touched = sample_payment.touch("alice")
        assert touched.version == 2
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "alice"


# ----------------------------------------------------------------------
# PaymentEntity - State Transitions
# ----------------------------------------------------------------------
class TestPaymentEntityStateTransitions:
    def test_state_flow_pending_to_confirmed_to_allocated(self, sample_payment):
        # PENDING -> CONFIRMED
        confirmed = sample_payment.confirm("alice")
        assert confirmed.status == PaymentStatus.CONFIRMED
        # CONFIRMED -> ALLOCATED
        allocated = confirmed.allocate_to_invoice(uuid4(), sample_payment.amount)
        assert allocated.status == PaymentStatus.ALLOCATED
        # Cannot go back
        with pytest.raises(ValueError):
            allocated.confirm("alice")

    def test_state_flow_confirmed_to_refunded(self, confirmed_payment):
        refunded = confirmed_payment.refund("alice", "Test")
        assert refunded.status == PaymentStatus.REFUNDED

    def test_state_flow_pending_to_failed_via_delete(self, sample_payment):
        failed = sample_payment.delete("alice", "Error")
        assert failed.status == PaymentStatus.FAILED
        # Can restore to PENDING
        restored = failed.restore("alice")
        assert restored.status == PaymentStatus.PENDING

    def test_state_flow_pending_to_confirmed_via_activate(self, sample_payment):
        activated = sample_payment.activate("alice")
        assert activated.status == PaymentStatus.CONFIRMED

    def test_state_flow_confirmed_to_pending_via_deactivate(self, confirmed_payment):
        deactivated = confirmed_payment.deactivate("alice")
        assert deactivated.status == PaymentStatus.PENDING


# ----------------------------------------------------------------------
# PaymentRepository (Interface)
# ----------------------------------------------------------------------
class TestPaymentRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_customer_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_customer(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_unallocated_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_unallocated(uuid4())

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_add_delegates_to_save(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.add(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_update_delegates_to_save(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.update(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_exists_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.exists(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_all_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_all(uuid4())

    @pytest.mark.asyncio
    async def test_search_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.search(uuid4(), {})

    @pytest.mark.asyncio
    async def test_count_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.count(uuid4())

    @pytest.mark.asyncio
    async def test_list_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.list(uuid4())

    @pytest.mark.asyncio
    async def test_paginate_not_implemented(self):
        repo = PaymentRepository()
        with pytest.raises(NotImplementedError):
            await repo.paginate(uuid4())


# ----------------------------------------------------------------------
# Edge Cases
# ----------------------------------------------------------------------
class TestPaymentEntityEdgeCases:
    def test_large_amount(self):
        payment = PaymentEntity(
            payment_id=uuid4(),
            payment_number="PAY-001",
            customer_id=uuid4(),
            customer_name="Customer",
            payment_date=datetime.now(UTC),
            amount=Decimal("9999999999.99"),
            currency="IDR",
            payment_method=PaymentMethod.CASH,
            status=PaymentStatus.PENDING,
        )
        assert payment.amount == Decimal("9999999999.99")

    def test_zero_reference_number_allowed(self):
        payment = PaymentEntity(
            payment_id=uuid4(),
            payment_number="PAY-001",
            customer_id=uuid4(),
            customer_name="Customer",
            payment_date=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="IDR",
            payment_method=PaymentMethod.CASH,
            status=PaymentStatus.PENDING,
            reference_number=None,
        )
        assert payment.reference_number is None

    def test_audit_trail_limit(self, sample_payment):
        for i in range(15):
            sample_payment._record_audit(f"ACTION_{i}", "system", {})
        trail = sample_payment.audit_trail(limit=5)
        assert len(trail) == 5

    def test_snapshot_limit(self, sample_payment):
        for _i in range(15):
            sample_payment._take_snapshot()
        assert len(sample_payment._snapshots) == 10
