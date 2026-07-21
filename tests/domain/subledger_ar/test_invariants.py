# tests/domain/subledger_ar/test_invariants.py
# Perbaikan:
# - Semua async test diberi @pytest.mark.asyncio
# - Duplikasi struktural dihilangkan dengan parametrize
# - Semua assertion bermakna
# - Semua entity base methods tercover

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from domain.subledger_ar.invariants import (
    ARInvariantEnforcer,
    ARInvariants,
    ARInvariantsValidator,
    InvariantResult,
)


# ============================================================================
# InvariantResult tests
# ============================================================================
class TestInvariantResult:
    def test_construction_valid(self):
        result = InvariantResult(is_valid=True, errors=None)
        assert result.is_valid is True
        assert result.errors == []

    def test_construction_invalid(self):
        result = InvariantResult(is_valid=False, errors=["err1"])
        assert result.is_valid is False
        assert result.errors == ["err1"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("test error")
        assert result.is_valid is False
        assert result.errors == ["test error"]

    def test_merge(self):
        result = InvariantResult()
        other = InvariantResult(is_valid=False, errors=["err1", "err2"])
        result.merge(other)
        assert result.is_valid is False
        assert result.errors == ["err1", "err2"]

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(is_valid=False)) is False

    def test_validate_valid(self):
        result = InvariantResult()
        validation = result.validate()
        assert validation["is_valid"] is True
        assert validation["errors"] == []

    def test_validate_invalid_type(self):
        result = InvariantResult()
        result.is_valid = "not_bool"
        validation = result.validate()
        assert validation["is_valid"] is False
        assert "is_valid must be boolean" in validation["errors"]

    def test_to_dict(self):
        result = InvariantResult(is_valid=False, errors=["err"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["err"]
        assert "version" in d

    def test_from_dict(self):
        data = {"is_valid": False, "errors": ["err"], "version": 5}
        result = InvariantResult.from_dict(data)
        assert result.is_valid is False
        assert result.errors == ["err"]
        assert result.version() == 5

    def test_clone(self):
        result = InvariantResult(is_valid=False, errors=["err"])
        cloned = result.clone()
        assert cloned is not result
        assert cloned.is_valid == result.is_valid
        assert cloned.errors == result.errors
        assert cloned.version() == result.version() + 1

    def test_snapshot(self):
        result = InvariantResult(is_valid=False, errors=["e1", "e2"])
        snap = result.snapshot()
        assert snap["is_valid"] is False
        assert snap["error_count"] == 2
        assert "timestamp" in snap

    def test_version(self):
        result = InvariantResult()
        assert result.version() == 1

    def test_audit_trail(self):
        result = InvariantResult()
        result.add_error("err")
        # add_error records audit
        audit = result.audit_trail()
        assert len(audit) == 1
        assert audit[0]["action"] == "ADD_ERROR"
        assert audit[0]["details"]["error"] == "err"

        result.touch("user")
        audit = result.audit_trail()
        assert len(audit) == 2
        assert audit[1]["action"] == "TOUCH"
        assert audit[1]["performed_by"] == "user"

    def test_touch(self):
        result = InvariantResult()
        old_version = result.version()
        result.touch("user")
        assert result.version() == old_version + 1
        audit = result.audit_trail()
        assert audit[-1]["action"] == "TOUCH"


# ============================================================================
# ARInvariants tests (static methods) - parametrized untuk menghilangkan duplikasi
# ============================================================================
class TestARInvariants:
    # --- validate_invoice_amount ---
    @pytest.mark.parametrize("amount, expected_valid, expected_error_substr", [
        (Decimal("100"), True, None),
        (Decimal("-10"), False, "must be positive"),
        (Decimal("0"), False, "must be positive"),
    ])
    def test_validate_invoice_amount(self, amount, expected_valid, expected_error_substr):
        invoice = MagicMock()
        invoice.amount = amount
        invoice.invoice_number = "INV001"
        result = ARInvariants.validate_invoice_amount(invoice)
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)

    # --- validate_payment_amount ---
    @pytest.mark.parametrize("amount, outstanding, expected_valid, expected_error_substr", [
        (Decimal("50"), None, True, None),
        (Decimal("-5"), None, False, "must be positive"),
        (Decimal("200"), Decimal("100"), False, "exceeds invoice outstanding"),
        (Decimal("50"), Decimal("100"), True, None),
    ])
    def test_validate_payment_amount(self, amount, outstanding, expected_valid, expected_error_substr):
        payment = MagicMock()
        payment.amount = amount
        payment.payment_number = "PAY001"
        invoice = None
        if outstanding is not None:
            invoice = MagicMock()
            invoice.outstanding_amount = outstanding
        result = ARInvariants.validate_payment_amount(payment, invoice)
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)

    # --- validate_credit_note_amount ---
    @pytest.mark.parametrize("amount, outstanding, expected_valid, expected_error_substr", [
        (Decimal("50"), None, True, None),
        (Decimal("-5"), None, False, "must be positive"),
        (Decimal("200"), Decimal("100"), False, "exceeds invoice outstanding"),
        (Decimal("50"), Decimal("100"), True, None),
    ])
    def test_validate_credit_note_amount(self, amount, outstanding, expected_valid, expected_error_substr):
        credit_note = MagicMock()
        credit_note.amount = amount
        credit_note.credit_note_number = "CN001"
        invoice = None
        if outstanding is not None:
            invoice = MagicMock()
            invoice.outstanding_amount = outstanding
        result = ARInvariants.validate_credit_note_amount(credit_note, invoice)
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)

    # --- validate_customer_credit_limit ---
    @pytest.mark.parametrize("requested, current, limit, expected_valid, expected_error_substr", [
        (Decimal("50"), Decimal("100"), Decimal("200"), True, None),
        (Decimal("50"), Decimal("100"), Decimal("0"), True, None),  # no limit
        (Decimal("150"), Decimal("100"), Decimal("200"), False, "credit limit exceeded"),
    ])
    def test_validate_customer_credit_limit(self, requested, current, limit, expected_valid, expected_error_substr):
        customer_id = uuid4()
        result = ARInvariants.validate_customer_credit_limit(
            customer_id, requested, current, limit
        )
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)

    # --- validate_invoice_cancellation ---
    @pytest.mark.parametrize("status_value, expected_valid", [
        ("draft", True),
        ("partially_paid", False),
        ("fully_paid", False),
    ])
    def test_validate_invoice_cancellation(self, status_value, expected_valid):
        from domain.subledger_ar.invoice_entity import InvoiceStatus
        invoice = MagicMock()
        # map status values
        if status_value == "draft":
            invoice.status = InvoiceStatus.DRAFT
        elif status_value == "partially_paid":
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        else:
            invoice.status = InvoiceStatus.FULLY_PAID
        invoice.invoice_number = "INV001"
        result = ARInvariants.validate_invoice_cancellation(invoice)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any("Cannot cancel" in e for e in result.errors)

    # --- validate_payment_refund ---
    @pytest.mark.parametrize("status_value, expected_valid, expected_error_substr", [
        ("completed", True, None),
        ("refunded", False, "already refunded"),
        ("failed", False, "already failed"),
    ])
    def test_validate_payment_refund(self, status_value, expected_valid, expected_error_substr):
        payment = MagicMock()
        payment.status = MagicMock()
        payment.status.value = status_value
        payment.payment_number = "PAY001"
        result = ARInvariants.validate_payment_refund(payment)
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)

    # --- validate_duplicate_invoice_number ---
    def test_validate_duplicate_invoice_number_valid(self):
        result = ARInvariants.validate_duplicate_invoice_number("INV001", {"INV002"})
        assert result.is_valid is True

    def test_validate_duplicate_invoice_number_invalid(self):
        result = ARInvariants.validate_duplicate_invoice_number("INV001", {"INV001", "INV002"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    # --- validate_negative_balance ---
    @pytest.mark.parametrize("balance, expected_valid, expected_error_substr", [
        (Decimal("100"), True, None),
        (Decimal("-5"), False, "cannot be negative"),
    ])
    def test_validate_negative_balance(self, balance, expected_valid, expected_error_substr):
        result = ARInvariants.validate_negative_balance(balance, "AR")
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)

    # --- validate_payment_allocation ---
    @pytest.mark.parametrize("allocated, payment_allocated, outstanding, expected_valid, expected_error_substr", [
        (Decimal("40"), Decimal("30"), Decimal("50"), True, None),
        (Decimal("0"), Decimal("30"), Decimal("50"), False, "must be positive"),
        (Decimal("80"), Decimal("30"), Decimal("50"), False, "exceeds remaining payment"),
        (Decimal("60"), Decimal("0"), Decimal("50"), False, "exceeds invoice outstanding"),
    ])
    def test_validate_payment_allocation(self, allocated, payment_allocated, outstanding,
                                         expected_valid, expected_error_substr):
        payment = MagicMock()
        payment.amount = Decimal("100")
        payment.allocated_amount = payment_allocated
        payment.payment_number = "PAY001"
        invoice = MagicMock()
        invoice.outstanding_amount = outstanding
        result = ARInvariants.validate_payment_allocation(payment, invoice, allocated)
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)


# ============================================================================
# ARInvariantEnforcer tests
# ============================================================================
class TestARInvariantEnforcer:
    @pytest.fixture
    def mock_invoice_number_checker(self):
        return AsyncMock(return_value={"INV001", "INV002"})

    @pytest.fixture
    def mock_customer_credit_checker(self):
        return AsyncMock(return_value=InvariantResult(True))

    @pytest.fixture
    def enforcer(self, mock_invoice_number_checker, mock_customer_credit_checker):
        return ARInvariantEnforcer(
            invoice_number_checker=mock_invoice_number_checker,
            customer_credit_checker=mock_customer_credit_checker,
        )

    @pytest.mark.asyncio
    async def test_enforce_invoice_create_valid(self, enforcer):
        invoice = MagicMock()
        invoice.amount = Decimal("100")
        invoice.invoice_number = "INV003"
        invoice.customer_id = uuid4()
        result = await enforcer.enforce_invoice_create(invoice)
        assert result.is_valid is True
        audit = enforcer.audit_trail()
        assert len(audit) == 1
        assert audit[0]["action"] == "ENFORCE_INVOICE_CREATE"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario, amount, inv_number, credit_result, expected_valid, expected_error_substr", [
        ("invalid_amount", Decimal("-10"), "INV003", None, False, "must be positive"),
        ("duplicate", Decimal("100"), "INV001", None, False, "already exists"),
        ("credit_limit_fail", Decimal("100"), "INV003", InvariantResult(False, ["credit limit exceeded"]), False, "credit limit exceeded"),
    ])
    async def test_enforce_invoice_create_errors(self, enforcer, mock_customer_credit_checker,
                                                 scenario, amount, inv_number, credit_result,
                                                 expected_valid, expected_error_substr):
        # For credit limit fail, override the checker
        if credit_result is not None:
            mock_customer_credit_checker.return_value = credit_result
        invoice = MagicMock()
        invoice.amount = amount
        invoice.invoice_number = inv_number
        invoice.customer_id = uuid4()
        result = await enforcer.enforce_invoice_create(invoice)
        assert result.is_valid == expected_valid
        assert any(expected_error_substr in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_enforce_payment_create_valid(self, enforcer):
        payment = MagicMock()
        payment.amount = Decimal("50")
        payment.payment_number = "PAY001"
        result = await enforcer.enforce_payment_create(payment)
        assert result.is_valid is True
        audit = enforcer.audit_trail()
        assert audit[0]["action"] == "ENFORCE_PAYMENT_CREATE"

    @pytest.mark.asyncio
    async def test_enforce_payment_create_invalid_amount(self, enforcer):
        payment = MagicMock()
        payment.amount = Decimal("-5")
        payment.payment_number = "PAY001"
        result = await enforcer.enforce_payment_create(payment)
        assert result.is_valid is False
        assert "must be positive" in result.errors[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("allocated, expected_valid, expected_error_substr", [
        (Decimal("40"), True, None),
        (Decimal("80"), False, "exceeds remaining payment"),
        (Decimal("60"), False, "exceeds invoice outstanding"),
    ])
    async def test_enforce_payment_allocation(self, enforcer, allocated, expected_valid, expected_error_substr):
        payment = MagicMock()
        payment.amount = Decimal("100")
        payment.allocated_amount = Decimal("30")
        payment.payment_number = "PAY001"
        invoice = MagicMock()
        invoice.outstanding_amount = Decimal("50")
        result = await enforcer.enforce_payment_allocation(payment, invoice, allocated)
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("amount, outstanding, expected_valid, expected_error_substr", [
        (Decimal("30"), Decimal("100"), True, None),
        (Decimal("200"), Decimal("100"), False, "exceeds invoice outstanding"),
    ])
    async def test_enforce_credit_note_create(self, enforcer, amount, outstanding, expected_valid, expected_error_substr):
        credit_note = MagicMock()
        credit_note.amount = amount
        credit_note.credit_note_number = "CN001"
        invoice = MagicMock()
        invoice.outstanding_amount = outstanding
        result = await enforcer.enforce_credit_note_create(credit_note, invoice)
        assert result.is_valid == expected_valid
        if expected_error_substr:
            assert any(expected_error_substr in e for e in result.errors)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_value, expected_valid", [
        ("draft", True),
        ("partially_paid", False),
    ])
    async def test_enforce_invoice_cancellation(self, enforcer, status_value, expected_valid):
        from domain.subledger_ar.invoice_entity import InvoiceStatus
        invoice = MagicMock()
        if status_value == "draft":
            invoice.status = InvoiceStatus.DRAFT
        else:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        invoice.invoice_number = "INV001"
        result = await enforcer.enforce_invoice_cancellation(invoice)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any("Cannot cancel" in e for e in result.errors)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_value, expected_valid", [
        ("completed", True),
        ("refunded", False),
    ])
    async def test_enforce_payment_refund(self, enforcer, status_value, expected_valid):
        payment = MagicMock()
        payment.status = MagicMock()
        payment.status.value = status_value
        payment.payment_number = "PAY001"
        result = await enforcer.enforce_payment_refund(payment)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any("already" in e for e in result.errors)

    def test_enforce_negative_balance_valid(self, enforcer):
        result = enforcer.enforce_negative_balance(Decimal("100"), "AR")
        assert result.is_valid is True
        audit = enforcer.audit_trail()
        assert audit[0]["action"] == "ENFORCE_NEGATIVE_BALANCE"

    def test_enforce_negative_balance_invalid(self, enforcer):
        result = enforcer.enforce_negative_balance(Decimal("-10"), "AR")
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    # --- Entity base methods ---
    def test_validate(self, enforcer):
        validation = enforcer.validate()
        assert validation["is_valid"] is True
        assert validation["errors"] == []

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert d["version"] == enforcer.version()
        assert d["type"] == "ARInvariantEnforcer"

    def test_from_dict(self):
        data = {"version": 3}
        enforcer = ARInvariantEnforcer.from_dict(data)
        assert enforcer.version() == 3
        assert enforcer._invoice_number_checker() == set()
        assert enforcer._customer_credit_checker(None, None).is_valid is True

    def test_clone(self, enforcer):
        cloned = enforcer.clone()
        assert cloned is not enforcer
        assert cloned.version() == enforcer.version() + 1
        assert cloned._invoice_number_checker == enforcer._invoice_number_checker
        assert cloned._customer_credit_checker == enforcer._customer_credit_checker

    def test_snapshot(self, enforcer):
        snap = enforcer.snapshot()
        assert snap["version"] == enforcer.version()
        assert snap["type"] == "ARInvariantEnforcer"
        assert "timestamp" in snap

    def test_version(self, enforcer):
        assert enforcer.version() == 1
        enforcer.touch("user")
        assert enforcer.version() == 2

    def test_audit_trail(self, enforcer):
        enforcer.touch("user1")
        enforcer.touch("user2")
        audit = enforcer.audit_trail(limit=1)
        assert len(audit) == 1
        assert audit[0]["performed_by"] == "user2"

    def test_reset(self, enforcer):
        enforcer.touch("user")
        enforcer.reset()
        assert enforcer.version() == 1
        assert enforcer.audit_trail() == []

    def test_get_statistics(self, enforcer):
        stats = enforcer.get_statistics()
        assert stats["version"] == 1
        assert stats["audit_count"] == 0
        assert stats["snapshot_count"] == 0


# ============================================================================
# ARInvariantsValidator tests
# ============================================================================
class TestARInvariantsValidator:
    @pytest.fixture
    def validator(self):
        return ARInvariantsValidator()

    def test_validate_invoice_amount(self, validator):
        invoice = MagicMock()
        invoice.amount = Decimal("100")
        result = validator.validate_invoice_amount(invoice)
        assert result.is_valid is True

        invoice.amount = Decimal("-10")
        result = validator.validate_invoice_amount(invoice)
        assert result.is_valid is False

    def test_validate_payment_amount(self, validator):
        payment = MagicMock()
        payment.amount = Decimal("50")
        payment.payment_number = "PAY001"
        result = validator.validate_payment_amount(payment)
        assert result.is_valid is True

        payment.amount = Decimal("-5")
        result = validator.validate_payment_amount(payment)
        assert result.is_valid is False

        # with invoice
        invoice = MagicMock()
        invoice.outstanding_amount = Decimal("30")
        payment.amount = Decimal("40")
        result = validator.validate_payment_amount(payment, invoice)
        assert result.is_valid is False
        assert "exceeds" in result.errors[0]

    def test_validate_credit_note_amount(self, validator):
        credit_note = MagicMock()
        credit_note.amount = Decimal("50")
        credit_note.credit_note_number = "CN001"
        result = validator.validate_credit_note_amount(credit_note)
        assert result.is_valid is True

        credit_note.amount = Decimal("-5")
        result = validator.validate_credit_note_amount(credit_note)
        assert result.is_valid is False

    def test_validate_customer_credit_limit(self, validator):
        result = validator.validate_customer_credit_limit(
            uuid4(), Decimal("50"), Decimal("100"), Decimal("200")
        )
        assert result.is_valid is True

        result = validator.validate_customer_credit_limit(
            uuid4(), Decimal("150"), Decimal("100"), Decimal("200")
        )
        assert result.is_valid is False
        assert "credit limit exceeded" in result.errors[0]

    def test_validate_invoice_cancellation(self, validator):
        invoice = MagicMock()
        invoice.status = MagicMock()
        invoice.status.value = "draft"
        invoice.invoice_number = "INV001"
        result = validator.validate_invoice_cancellation(invoice)
        assert result.is_valid is True

    def test_validate_payment_refund(self, validator):
        payment = MagicMock()
        payment.status = MagicMock()
        payment.status.value = "completed"
        payment.payment_number = "PAY001"
        result = validator.validate_payment_refund(payment)
        assert result.is_valid is True

        payment.status.value = "refunded"
        result = validator.validate_payment_refund(payment)
        assert result.is_valid is False

    def test_validate_duplicate_invoice_number(self, validator):
        result = validator.validate_duplicate_invoice_number("INV001", {"INV002"})
        assert result.is_valid is True
        result = validator.validate_duplicate_invoice_number("INV001", {"INV001"})
        assert result.is_valid is False

    def test_validate_negative_balance(self, validator):
        result = validator.validate_negative_balance(Decimal("100"), "AR")
        assert result.is_valid is True
        result = validator.validate_negative_balance(Decimal("-5"), "AR")
        assert result.is_valid is False

    def test_validate_payment_allocation(self, validator):
        payment = MagicMock()
        payment.amount = Decimal("100")
        payment.allocated_amount = Decimal("30")
        payment.payment_number = "PAY001"
        invoice = MagicMock()
        invoice.outstanding_amount = Decimal("50")
        result = validator.validate_payment_allocation(payment, invoice, Decimal("40"))
        assert result.is_valid is True
        result = validator.validate_payment_allocation(payment, invoice, Decimal("80"))
        assert result.is_valid is False

    def test_validate_all(self, validator):
        invoice = MagicMock()
        invoice.amount = Decimal("100")
        invoice.status = MagicMock()
        invoice.status.value = "draft"
        invoice.invoice_number = "INV001"
        payment = MagicMock()
        payment.amount = Decimal("50")
        payment.payment_number = "PAY001"
        result = validator.validate_all(invoice, payment)
        assert result.is_valid is True

        invoice.amount = Decimal("-10")
        result = validator.validate_all(invoice, payment)
        assert result.is_valid is False
        assert len(result.errors) == 1

    # --- Entity base methods ---
    def test_validate(self, validator):
        validation = validator.validate()
        assert validation["is_valid"] is True
        assert validation["errors"] == []

    def test_to_dict(self, validator):
        d = validator.to_dict()
        assert d["version"] == validator.version()
        assert d["type"] == "ARInvariantsValidator"

    def test_from_dict(self):
        data = {"version": 4}
        validator = ARInvariantsValidator.from_dict(data)
        assert validator.version() == 4

    def test_clone(self, validator):
        cloned = validator.clone()
        assert cloned is not validator
        assert cloned.version() == validator.version() + 1

    def test_snapshot(self, validator):
        snap = validator.snapshot()
        assert snap["version"] == validator.version()
        assert snap["type"] == "ARInvariantsValidator"
        assert "timestamp" in snap

    def test_version(self, validator):
        assert validator.version() == 1
        validator.touch("user")
        assert validator.version() == 2

    def test_audit_trail(self, validator):
        validator.touch("user1")
        validator.touch("user2")
        audit = validator.audit_trail(limit=1)
        assert len(audit) == 1
        assert audit[0]["performed_by"] == "user2"

    def test_reset(self, validator):
        validator.touch("user")
        validator.reset()
        assert validator.version() == 1
        assert validator.audit_trail() == []

    def test_get_statistics(self, validator):
        stats = validator.get_statistics()
        assert stats["version"] == 1
        assert stats["audit_count"] == 0
        assert stats["snapshot_count"] == 0