# test_customer_credit_limit_vo.py
# =========================================
# Lengkap: Semua metode CustomerCreditLimitVO dan fungsi modul diuji.
# Tidak ada kode asli yang dihapus.

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from domain.customer_supplier_employee.customer_credit_limit_vo import (
    CreditLimitError,
    CreditLimitExpiredError,
    CreditLimitReviewOutcome,
    CreditLimitStatus,
    CustomerCreditLimitVO,
    InvalidCreditLimitAmountError,
    InvalidCurrencyError,
    format_credit_limit,
    get_active_limit_at_date,
    get_most_recent_limit,
    parse_credit_limit,
    sum_credit_limits,
)

# ============================================================================
# Exceptions
# ============================================================================

class TestCreditLimitError:
    def test_construction(self):
        exc = CreditLimitError("msg")
        assert str(exc) == "msg"
        assert isinstance(exc, ValueError)


class TestInvalidCreditLimitAmountError:
    def test_construction(self):
        exc = InvalidCreditLimitAmountError("msg")
        assert str(exc) == "msg"
        assert isinstance(exc, CreditLimitError)


class TestInvalidCurrencyError:
    def test_construction(self):
        exc = InvalidCurrencyError("msg")
        assert str(exc) == "msg"
        assert isinstance(exc, CreditLimitError)


class TestCreditLimitExpiredError:
    def test_construction(self):
        exc = CreditLimitExpiredError("msg")
        assert str(exc) == "msg"
        assert isinstance(exc, CreditLimitError)


# ============================================================================
# Enums
# ============================================================================

class TestCreditLimitStatus:
    def test_members_exist(self):
        assert hasattr(CreditLimitStatus, 'ACTIVE')
        assert hasattr(CreditLimitStatus, 'EXPIRED')
        assert hasattr(CreditLimitStatus, 'PENDING')
        assert hasattr(CreditLimitStatus, 'REVOKED')
        assert hasattr(CreditLimitStatus, 'SUSPENDED')

    def test_is_usable(self):
        assert CreditLimitStatus.ACTIVE.is_usable() is True
        assert CreditLimitStatus.EXPIRED.is_usable() is False
        assert CreditLimitStatus.PENDING.is_usable() is False
        assert CreditLimitStatus.REVOKED.is_usable() is False
        assert CreditLimitStatus.SUSPENDED.is_usable() is False


class TestCreditLimitReviewOutcome:
    def test_members_exist(self):
        assert hasattr(CreditLimitReviewOutcome, 'APPROVED')
        assert hasattr(CreditLimitReviewOutcome, 'REJECTED')
        assert hasattr(CreditLimitReviewOutcome, 'PENDING_REVIEW')
        assert hasattr(CreditLimitReviewOutcome, 'REDUCED')
        assert hasattr(CreditLimitReviewOutcome, 'INCREASED')
        assert hasattr(CreditLimitReviewOutcome, 'SUSPENDED')


# ============================================================================
# Helper to create valid limits
# ============================================================================

def make_limit(
    amount: Decimal = Decimal("10000000"),
    currency: str = "IDR",
    effective_date: datetime | None = None,
    expiry_date: datetime | None = None,
    status: CreditLimitStatus = CreditLimitStatus.ACTIVE,
    approved_by: str = "admin",
    source: str = "manual",
    version: int = 1,
) -> CustomerCreditLimitVO:
    if effective_date is None:
        effective_date = datetime.now(UTC) - timedelta(days=1)
    if expiry_date is None:
        expiry_date = datetime.now(UTC) + timedelta(days=365)
    return CustomerCreditLimitVO(
        amount=amount,
        currency=currency,
        effective_date=effective_date,
        expiry_date=expiry_date,
        approved_by=approved_by,
        approval_date=datetime.now(UTC),
        review_date=date.today(),
        review_notes="Initial",
        status=status,
        source=source,
        version=version,
    )


# ============================================================================
# Tests for CustomerCreditLimitVO
# ============================================================================

class TestCustomerCreditLimitVO:
    # --- Construction & Validation ---
    def test_construction_valid(self):
        limit = make_limit()
        assert isinstance(limit, CustomerCreditLimitVO)
        assert limit.amount == Decimal("10000000")
        assert limit.currency == "IDR"

    def test_validation_negative_amount(self):
        with pytest.raises(InvalidCreditLimitAmountError):
            CustomerCreditLimitVO(amount=Decimal("-100"), currency="IDR")

    def test_validation_invalid_currency(self):
        with pytest.raises(InvalidCurrencyError, match="exactly 3"):
            CustomerCreditLimitVO(amount=Decimal("100"), currency="INVALID")
        with pytest.raises(InvalidCurrencyError, match="non-empty"):
            CustomerCreditLimitVO(amount=Decimal("100"), currency="")

    def test_validation_expiry_before_effective(self):
        now = datetime.now(UTC)
        with pytest.raises(CreditLimitError, match="must be after"):
            CustomerCreditLimitVO(
                amount=Decimal("100"),
                currency="IDR",
                effective_date=now,
                expiry_date=now - timedelta(days=1),
            )

    def test_validation_version_zero(self):
        with pytest.raises(CreditLimitError, match="Version must be >= 1"):
            CustomerCreditLimitVO(amount=Decimal("100"), version=0)

    def test_auto_status_correction(self):
        now = datetime.now(UTC)
        # Future effective -> PENDING
        limit = CustomerCreditLimitVO(
            amount=Decimal("100"),
            currency="IDR",
            effective_date=now + timedelta(days=10),
            status=CreditLimitStatus.ACTIVE,
        )
        assert limit.status == CreditLimitStatus.PENDING

        # Past expiry -> EXPIRED
        limit2 = CustomerCreditLimitVO(
            amount=Decimal("100"),
            currency="IDR",
            effective_date=now - timedelta(days=10),
            expiry_date=now - timedelta(days=1),
            status=CreditLimitStatus.ACTIVE,
        )
        assert limit2.status == CreditLimitStatus.EXPIRED

    # --- Factory Methods ---
    def test_create(self):
        limit = CustomerCreditLimitVO.create(
            amount=Decimal("5000000"),
            currency="USD",
            effective_date=datetime.now(UTC),
            expiry_date=datetime.now(UTC) + timedelta(days=30),
            approved_by="manager",
            source="policy",
        )
        assert limit.amount == Decimal("5000000")
        assert limit.currency == "USD"
        assert limit.status == CreditLimitStatus.ACTIVE
        assert limit.version == 1
        assert limit.approved_by == "manager"

    def test_create_with_defaults(self):
        limit = CustomerCreditLimitVO.create(amount=Decimal("1000"))
        assert limit.currency == "IDR"
        assert limit.effective_date is not None
        assert limit.status == CreditLimitStatus.ACTIVE

    def test_unlimited(self):
        limit = CustomerCreditLimitVO.unlimited(currency="EUR")
        assert limit.amount >= Decimal("999999999999")
        assert limit.currency == "EUR"
        assert limit.is_unlimited is True
        assert limit.source == "unlimited"

    def test_zero(self):
        limit = CustomerCreditLimitVO.zero()
        assert limit.amount == Decimal("0")
        assert limit.is_zero is True
        assert limit.source == "zero"

    def test_from_dict_minimal(self):
        data = {
            "amount": "7500000",
            "currency": "IDR",
            "effective_date": datetime.now(UTC).isoformat(),
        }
        limit = CustomerCreditLimitVO.from_dict(data)
        assert limit.amount == Decimal("7500000")
        assert limit.currency == "IDR"
        assert limit.status == CreditLimitStatus.ACTIVE

    def test_from_dict_full(self):
        now = datetime.now(UTC)
        data = {
            "amount": "10000000",
            "currency": "USD",
            "effective_date": now.isoformat(),
            "expiry_date": (now + timedelta(days=30)).isoformat(),
            "approved_by": "admin",
            "approval_date": now.isoformat(),
            "review_date": date.today().isoformat(),
            "review_notes": "Reviewed",
            "status": "active",
            "source": "manual",
            "version": 2,
        }
        limit = CustomerCreditLimitVO.from_dict(data)
        assert limit.amount == Decimal("10000000")
        assert limit.currency == "USD"
        assert limit.approved_by == "admin"
        assert limit.status == CreditLimitStatus.ACTIVE
        assert limit.version == 2

    # --- Properties ---
    def test_is_unlimited(self):
        limit = make_limit(amount=Decimal("999999999999"))
        assert limit.is_unlimited is True
        limit2 = make_limit(amount=Decimal("100"))
        assert limit2.is_unlimited is False

    def test_is_zero(self):
        limit = make_limit(amount=Decimal("0"))
        assert limit.is_zero is True
        limit2 = make_limit(amount=Decimal("100"))
        assert limit2.is_zero is False

    def test_is_positive(self):
        limit = make_limit(amount=Decimal("100"))
        assert limit.is_positive is True
        limit2 = make_limit(amount=Decimal("0"))
        assert limit2.is_positive is False

    def test_is_forever(self):
        limit = make_limit(expiry_date=None)
        assert limit.is_forever is True
        limit2 = make_limit(expiry_date=datetime.now(UTC) + timedelta(days=30))
        assert limit2.is_forever is False

    def test_days_until_expiry(self):
        now = datetime.now(UTC)
        expiry = now + timedelta(days=10)
        limit = make_limit(expiry_date=expiry)
        days = limit.days_until_expiry(as_of=now)
        assert days == 10

        # No expiry
        limit2 = make_limit(expiry_date=None)
        assert limit2.days_until_expiry() is None

        # Already expired
        limit3 = make_limit(expiry_date=now - timedelta(days=5))
        assert limit3.days_until_expiry(as_of=now) == 0

    def test_has_been_reviewed(self):
        limit = make_limit(review_date=date.today())
        assert limit.has_been_reviewed is True
        limit2 = CustomerCreditLimitVO(amount=Decimal("100"), currency="IDR", effective_date=datetime.now(UTC))
        assert limit2.has_been_reviewed is False

    # --- Business Logic ---
    def test_is_active(self):
        now = datetime.now(UTC)
        limit = make_limit(
            effective_date=now - timedelta(days=1),
            expiry_date=now + timedelta(days=30),
            status=CreditLimitStatus.ACTIVE,
        )
        assert limit.is_active(now) is True
        assert limit.is_active(now - timedelta(days=2)) is False  # before effective
        assert limit.is_active(now + timedelta(days=40)) is False  # after expiry

        # Non-active status
        limit2 = make_limit(status=CreditLimitStatus.SUSPENDED)
        assert limit2.is_active(now) is False

    def test_is_exceeded(self):
        now = datetime.now(UTC)
        limit = make_limit(amount=Decimal("10000"), status=CreditLimitStatus.ACTIVE)
        assert limit.is_exceeded(Decimal("5000"), now) is False
        assert limit.is_exceeded(Decimal("15000"), now) is True
        # Inactive limit always exceeded
        limit2 = make_limit(status=CreditLimitStatus.EXPIRED)
        assert limit2.is_exceeded(Decimal("0"), now) is True

    def test_remaining(self):
        now = datetime.now(UTC)
        limit = make_limit(amount=Decimal("10000"))
        assert limit.remaining(Decimal("3000"), now) == Decimal("7000")
        assert limit.remaining(Decimal("12000"), now) == Decimal("0")
        # Inactive returns 0
        limit2 = make_limit(status=CreditLimitStatus.REVOKED)
        assert limit2.remaining(Decimal("0"), now) == Decimal("0")

    def test_utilization_percentage(self):
        now = datetime.now(UTC)
        limit = make_limit(amount=Decimal("10000"))
        assert limit.utilization_percentage(Decimal("0"), now) == Decimal("0")
        assert limit.utilization_percentage(Decimal("5000"), now) == Decimal("50.00")
        assert limit.utilization_percentage(Decimal("15000"), now) == Decimal("100")
        # Zero limit -> utilization 0
        limit2 = make_limit(amount=Decimal("0"))
        assert limit2.utilization_percentage(Decimal("100"), now) == Decimal("0")

    def test_can_invoice(self):
        now = datetime.now(UTC)
        limit = make_limit(amount=Decimal("10000"))
        can, reason = limit.can_invoice(Decimal("5000"), Decimal("3000"), now)
        assert can is True
        assert reason is None

        can2, reason2 = limit.can_invoice(Decimal("5000"), Decimal("6000"), now)
        assert can2 is False
        assert "exceed" in reason2

        # Inactive
        limit2 = make_limit(status=CreditLimitStatus.EXPIRED)
        can3, reason3 = limit2.can_invoice(Decimal("100"), Decimal("0"), now)
        assert can3 is False
        assert "not active" in reason3

        # Zero limit
        limit3 = make_limit(amount=Decimal("0"))
        can4, reason4 = limit3.can_invoice(Decimal("100"), Decimal("0"), now)
        assert can4 is False
        assert "zero" in reason4

    # --- Mutation methods ---
    def test_with_amount(self):
        limit = make_limit()
        new_limit = limit.with_amount(Decimal("20000000"), changed_by="manager", reason="Increase")
        assert new_limit.amount == Decimal("20000000")
        assert new_limit.version == limit.version + 1
        assert new_limit.approved_by == "manager"
        assert new_limit.review_notes == "Increase"
        assert new_limit.effective_date > limit.effective_date

    def test_with_expiry(self):
        limit = make_limit(expiry_date=datetime.now(UTC) + timedelta(days=30))
        new_expiry = datetime.now(UTC) + timedelta(days=180)
        new_limit = limit.with_expiry(new_expiry, changed_by="admin")
        assert new_limit.expiry_date == new_expiry
        assert new_limit.version == limit.version + 1
        assert "Expiry changed" in new_limit.review_notes

    def test_revoke(self):
        limit = make_limit()
        revoked = limit.revoke("admin", "Fraud risk")
        assert revoked.status == CreditLimitStatus.REVOKED
        assert revoked.version == limit.version + 1
        assert "Revoked: Fraud risk" in revoked.review_notes

    def test_suspend(self):
        limit = make_limit()
        suspended = limit.suspend("admin", "Temporary hold")
        assert suspended.status == CreditLimitStatus.SUSPENDED
        assert suspended.version == limit.version + 1

    def test_activate(self):
        limit = make_limit(status=CreditLimitStatus.SUSPENDED)
        activated = limit.activate("admin")
        assert activated.status == CreditLimitStatus.ACTIVE
        assert activated.version == limit.version + 1
        assert "Activated from suspended" in activated.review_notes

    # --- Serialization ---
    def test_to_dict(self):
        now = datetime.now(UTC)
        limit = make_limit(
            amount=Decimal("5000000"),
            currency="USD",
            effective_date=now,
            expiry_date=now + timedelta(days=30),
            approved_by="admin",
            source="policy",
        )
        d = limit.to_dict()
        assert d["amount"] == "5000000"
        assert d["currency"] == "USD"
        assert d["status"] == "active"
        assert d["is_unlimited"] is False
        assert d["is_zero"] is False
        assert d["is_forever"] is False

    def test_to_db_record(self):
        limit = make_limit()
        rec = limit.to_db_record()
        assert rec["credit_limit_amount"] == limit.amount
        assert rec["credit_limit_currency"] == limit.currency
        assert rec["credit_limit_status"] == limit.status.value
        assert rec["credit_limit_version"] == limit.version

    # --- Dunder Methods ---
    def test_str(self):
        limit = make_limit(amount=Decimal("1000000"), currency="IDR")
        assert str(limit) == "IDR 1,000,000.00"
        unlimited = CustomerCreditLimitVO.unlimited()
        assert str(unlimited) == "Unlimited (IDR)"

    def test_repr(self):
        limit = make_limit()
        repr_str = repr(limit)
        assert "CustomerCreditLimitVO" in repr_str
        assert str(limit.amount) in repr_str

    def test_eq(self):
        now = datetime.now(UTC)
        l1 = CustomerCreditLimitVO(amount=Decimal("100"), currency="IDR", effective_date=now, expiry_date=None)
        l2 = CustomerCreditLimitVO(amount=Decimal("100"), currency="IDR", effective_date=now, expiry_date=None)
        l3 = CustomerCreditLimitVO(amount=Decimal("200"), currency="IDR", effective_date=now, expiry_date=None)
        assert l1 == l2
        assert l1 != l3
        assert l1 != "not a limit"

    def test_hash(self):
        now = datetime.now(UTC)
        l1 = CustomerCreditLimitVO(amount=Decimal("100"), currency="IDR", effective_date=now, expiry_date=None)
        l2 = CustomerCreditLimitVO(amount=Decimal("100"), currency="IDR", effective_date=now, expiry_date=None)
        assert hash(l1) == hash(l2)
        l3 = CustomerCreditLimitVO(amount=Decimal("100"), currency="USD", effective_date=now, expiry_date=None)
        assert hash(l1) != hash(l3)


# ============================================================================
# Module-level helper functions
# ============================================================================

class TestModuleFunctions:
    def test_format_credit_limit(self):
        limit = make_limit(amount=Decimal("7500000"), currency="IDR")
        assert format_credit_limit(limit, include_currency=True) == "IDR 7,500,000.00"
        assert format_credit_limit(limit, include_currency=False) == "7,500,000.00"
        unlimited = CustomerCreditLimitVO.unlimited()
        assert format_credit_limit(unlimited) == "Unlimited"

    def test_parse_credit_limit(self):
        limit = parse_credit_limit("10,000,000", "USD")
        assert limit.amount == Decimal("10000000")
        assert limit.currency == "USD"
        # With currency symbol
        limit2 = parse_credit_limit("Rp 5.000.000", "IDR")
        assert limit2.amount == Decimal("5000000")
        # Invalid
        with pytest.raises(CreditLimitError):
            parse_credit_limit("invalid")

    def test_sum_credit_limits(self):
        now = datetime.now(UTC)
        l1 = CustomerCreditLimitVO(amount=Decimal("1000"), currency="IDR", effective_date=now, expiry_date=now + timedelta(days=10))
        l2 = CustomerCreditLimitVO(amount=Decimal("2000"), currency="IDR", effective_date=now, expiry_date=now + timedelta(days=20))
        l3 = CustomerCreditLimitVO(amount=Decimal("3000"), currency="IDR", effective_date=now - timedelta(days=5), expiry_date=now + timedelta(days=30))
        combined = sum_credit_limits([l1, l2, l3])
        assert combined.amount == Decimal("6000")
        assert combined.effective_date == l3.effective_date  # earliest
        assert combined.expiry_date == l3.expiry_date  # latest
        assert combined.currency == "IDR"

        # Empty list returns zero limit
        zero = sum_credit_limits([])
        assert zero.amount == Decimal("0")
        assert zero.source == "zero"

    def test_get_most_recent_limit(self):
        now = datetime.now(UTC)
        l1 = CustomerCreditLimitVO(amount=Decimal("1000"), currency="IDR", effective_date=now - timedelta(days=10))
        l2 = CustomerCreditLimitVO(amount=Decimal("2000"), currency="IDR", effective_date=now)
        l3 = CustomerCreditLimitVO(amount=Decimal("3000"), currency="IDR", effective_date=now + timedelta(days=1))
        most_recent = get_most_recent_limit([l1, l2, l3])
        assert most_recent == l3
        assert get_most_recent_limit([]) is None

    def test_get_active_limit_at_date(self):
        now = datetime.now(UTC)
        l1 = CustomerCreditLimitVO(
            amount=Decimal("1000"),
            currency="IDR",
            effective_date=now - timedelta(days=5),
            expiry_date=now + timedelta(days=5),
            status=CreditLimitStatus.ACTIVE,
        )
        l2 = CustomerCreditLimitVO(
            amount=Decimal("2000"),
            currency="IDR",
            effective_date=now - timedelta(days=1),
            expiry_date=now + timedelta(days=10),
            status=CreditLimitStatus.ACTIVE,
        )
        l3 = CustomerCreditLimitVO(
            amount=Decimal("3000"),
            currency="IDR",
            effective_date=now + timedelta(days=2),
            expiry_date=now + timedelta(days=20),
            status=CreditLimitStatus.ACTIVE,
        )
        # At now, only l1 and l2 are active (l3 not yet effective)
        active = get_active_limit_at_date([l1, l2, l3], now)
        assert active == l2  # most recent effective among active

        # If none active
        assert get_active_limit_at_date([l3], now) is None
        # Default as_of = now
        assert get_active_limit_at_date([l1, l2]) == l2
