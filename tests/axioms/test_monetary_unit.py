#!/usr/bin/env python3
"""
tests/unit/test_monetary_unit.py
Test untuk axioms/monetary_unit.py
Mencakup semua kelas dan metode (termasuk private) secara exhaustive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext
from unittest.mock import MagicMock, patch

import pytest

from axioms.monetary_unit import (
    CurrencyDefinition,
    CurrencyNotSupportedError,
    CurrencyRegistry,
    ExchangeRate,
    ExchangeRateNotFoundError,
    ExchangeRateType,
    MonetaryAmount,
    MonetaryUnitAxiom,
    MonetaryUnitStability,
    MonetaryUnitValidator,
    MonetaryUnitViolation,
    MonetaryUnitViolationError,
    MonetaryUnitViolationSeverity,
    create_exchange_rate,
    create_monetary_amount,
    get_monetary_unit_axiom,
    register_currency,
)

getcontext().prec = 28


# ============================================================================
# Helper functions untuk membuat objek test
# ============================================================================

def create_test_currency(
    code: str = "XTS",
    name: str = "Test Currency",
    symbol: str = "T$",
    decimal_places: int = 2,
    stability: MonetaryUnitStability = MonetaryUnitStability.STABLE,
    is_active: bool = True,
    country: str = "XX",
) -> CurrencyDefinition:
    return CurrencyDefinition(
        currency_code=code,
        currency_name=name,
        symbol=symbol,
        decimal_places=decimal_places,
        stability=stability,
        is_active=is_active,
        country_code=country,
    )


def create_test_exchange_rate(
    from_currency: str = "USD",
    to_currency: str = "IDR",
    rate: Decimal = Decimal("15250"),
    rate_type: ExchangeRateType = ExchangeRateType.SPOT,
    effective_date: datetime | None = None,
    expires_at: datetime | None = None,
) -> ExchangeRate:
    if effective_date is None:
        effective_date = datetime.now(UTC)
    return ExchangeRate(
        rate_id=uuid.uuid4(),
        from_currency=from_currency,
        to_currency=to_currency,
        rate=rate,
        rate_type=rate_type,
        effective_date=effective_date,
        source="Test",
        created_by="tester",
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    )


def create_test_amount(
    amount: Decimal = Decimal("1000"),
    currency: str = "IDR",
    decimal_places: int = 2,
) -> MonetaryAmount:
    return MonetaryAmount(amount, currency, decimal_places)


def create_test_violation() -> MonetaryUnitViolation:
    return MonetaryUnitViolation(
        violation_id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        currency_used="USD",
        functional_currency="IDR",
        exchange_rate_used=Decimal("15250"),
        required_rate_source="Bank Indonesia",
        severity=MonetaryUnitViolationSeverity.MEDIUM,
        message="Test violation",
        detected_at=datetime.now(UTC),
        detected_by="tester",
        resolved=False,
        resolved_at=None,
        resolved_by=None,
    )


# ============================================================================
# TESTS UNTUK CurrencyDefinition (semua metode publik + private)
# ============================================================================

class TestCurrencyDefinition:
    def test_create_valid_currency(self):
        curr = create_test_currency()
        assert curr.currency_code == "XTS"
        assert curr.currency_name == "Test Currency"
        assert curr.symbol == "T$"
        assert curr.decimal_places == 2
        assert curr.stability == MonetaryUnitStability.STABLE
        assert curr.is_active
        assert curr.country_code == "XX"
        assert curr.version == 1
        assert curr.cryptographic_hash != ""

    def test_validate_currency_code_length(self):
        with pytest.raises(ValueError, match="Currency code must be 3 chars"):
            CurrencyDefinition(
                currency_code="US",
                currency_name="Dollar",
                symbol="$",
                decimal_places=2,
                stability=MonetaryUnitStability.STABLE,
                is_active=True,
                country_code="US",
            )

    def test_validate_decimal_places_range(self):
        with pytest.raises(ValueError, match="Decimal places 0-4"):
            CurrencyDefinition(
                currency_code="USD",
                currency_name="Dollar",
                symbol="$",
                decimal_places=5,
                stability=MonetaryUnitStability.STABLE,
                is_active=True,
                country_code="US",
            )

    def test_validate_version_positive(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            CurrencyDefinition(
                currency_code="USD",
                currency_name="Dollar",
                symbol="$",
                decimal_places=2,
                stability=MonetaryUnitStability.STABLE,
                is_active=True,
                country_code="US",
                version=0,
            )

    def test_private_validate_called(self):
        curr = create_test_currency()
        result = curr.validate()
        assert result["is_valid"]

    def test_private_ensure_hash_called(self):
        curr = create_test_currency()
        assert curr.cryptographic_hash != ""

    def test_private_take_snapshot_called(self):
        curr = create_test_currency()
        assert len(curr._snapshots) == 1

    def test_private_record_audit_called(self):
        curr = create_test_currency()
        assert len(curr._audit_trail) == 1

    def test_private_copy_called(self):
        curr = create_test_currency()
        updated = curr.update("admin", currency_name="New")
        assert updated.currency_name == "New"

    def test_compute_hash_consistent(self):
        c1 = create_test_currency()
        c2 = CurrencyDefinition(
            currency_code=c1.currency_code,
            currency_name=c1.currency_name,
            symbol=c1.symbol,
            decimal_places=c1.decimal_places,
            stability=c1.stability,
            is_active=c1.is_active,
            country_code=c1.country_code,
            created_at=c1.created_at,
        )
        assert c1.compute_hash() == c2.compute_hash()

    def test_update_creates_new_version(self):
        curr = create_test_currency()
        updated = curr.update("admin", currency_name="Updated Name")
        assert updated.currency_name == "Updated Name"
        assert updated.version == curr.version + 1

    def test_update_cannot_change_code_and_created_at(self):
        curr = create_test_currency()
        original_code = curr.currency_code
        original_created = curr.created_at
        updated = curr.update("admin", currency_code="XXX", created_at=datetime(2000, 1, 1, tzinfo=UTC))
        assert updated.currency_code == original_code
        assert updated.created_at == original_created

    def test_delete_marks_deleted_and_inactive(self):
        curr = create_test_currency()
        deleted = curr.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert not deleted.is_active
        assert deleted.version == curr.version + 1

    def test_restore_recovers_deleted_currency(self):
        curr = create_test_currency()
        deleted = curr.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.is_active

    def test_restore_not_deleted_raises(self):
        curr = create_test_currency()
        with pytest.raises(ValueError, match="Not deleted"):
            curr.restore("admin")

    def test_activate_does_nothing_if_active(self):
        curr = create_test_currency()
        activated = curr.activate("admin")
        assert activated is curr

    def test_activate_activates_inactive(self):
        curr = create_test_currency()
        deactivated = curr.deactivate("admin", "test")
        activated = deactivated.activate("admin")
        assert activated.is_active
        assert activated.version == deactivated.version + 1

    def test_deactivate_does_nothing_if_inactive(self):
        curr = create_test_currency()
        deactivated = curr.deactivate("admin", "test")
        again = deactivated.deactivate("admin", "again")
        assert again is deactivated

    def test_lock_returns_self(self):
        curr = create_test_currency()
        locked = curr.lock("admin", "test")
        assert locked is curr

    def test_unlock_returns_self(self):
        curr = create_test_currency()
        unlocked = curr.unlock("admin")
        assert unlocked is curr

    def test_create_returns_self(self):
        curr = create_test_currency()
        result = curr.create("admin")
        assert result is curr

    def test_validate_returns_valid(self):
        curr = create_test_currency()
        result = curr.validate()
        assert result["is_valid"]
        assert result["currency_code"] == curr.currency_code

    def test_validate_returns_errors_on_hash_mismatch(self):
        curr = create_test_currency()
        object.__setattr__(curr, "cryptographic_hash", "fake")
        result = curr.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_all_fields(self):
        curr = create_test_currency()
        d = curr.to_dict()
        assert d["currency_code"] == "XTS"
        assert d["currency_name"] == "Test Currency"
        assert d["symbol"] == "T$"
        assert d["stability"] == "STABLE"
        assert d["is_active"]
        assert "created_at" in d
        assert d["version"] == 1

    def test_from_dict_reconstructs(self):
        curr = create_test_currency()
        d = curr.to_dict()
        reconstructed = CurrencyDefinition.from_dict(d)
        assert reconstructed.currency_code == curr.currency_code
        assert reconstructed.currency_name == curr.currency_name
        assert reconstructed.symbol == curr.symbol
        assert reconstructed.stability == curr.stability
        assert reconstructed.is_active == curr.is_active

    def test_clone_creates_new_currency(self):
        curr = create_test_currency()
        cloned = curr.clone()
        assert cloned.currency_code == curr.currency_code + "_COPY"
        assert cloned.currency_name == curr.currency_name + " (COPY)"
        assert not cloned.is_active
        assert cloned.version == 1
        assert cloned.stability == curr.stability

    def test_snapshot_returns_summary(self):
        curr = create_test_currency()
        snap = curr.snapshot()
        assert snap["currency_code"] == curr.currency_code
        assert snap["is_active"] == curr.is_active
        assert "timestamp" in snap

    def test_get_version(self):
        curr = create_test_currency()
        assert curr.get_version() == 1

    def test_audit_trail_records(self):
        curr = create_test_currency()
        assert len(curr.audit_trail()) >= 1
        curr.touch("toucher")
        trail = curr.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"

    def test_touch_increments_version(self):
        curr = create_test_currency()
        touched = curr.touch("toucher")
        assert touched.version == curr.version + 1

    def test_audit_trail_limit(self):
        curr = create_test_currency()
        for _ in range(15):
            curr = curr.touch("tester")
        trail = curr.audit_trail(limit=5)
        assert len(trail) == 5


# ============================================================================
# TESTS UNTUK ExchangeRate (semua metode)
# ============================================================================

class TestExchangeRate:
    def test_create_valid_rate(self):
        rate = create_test_exchange_rate()
        assert rate.from_currency == "USD"
        assert rate.to_currency == "IDR"
        assert rate.rate == Decimal("15250")
        assert rate.rate_type == ExchangeRateType.SPOT
        assert rate.version == 1
        assert rate.cryptographic_hash != ""

    def test_validate_rate_positive(self):
        with pytest.raises(ValueError, match="Rate must be positive"):
            ExchangeRate(
                rate_id=uuid.uuid4(),
                from_currency="USD",
                to_currency="IDR",
                rate=Decimal("-100"),
                rate_type=ExchangeRateType.SPOT,
                effective_date=datetime.now(UTC),
                source="Test",
                created_by="tester",
                created_at=datetime.now(UTC),
            )

    def test_validate_same_currency_rate_one(self):
        with pytest.raises(ValueError, match="Same currency rate must be 1"):
            ExchangeRate(
                rate_id=uuid.uuid4(),
                from_currency="USD",
                to_currency="USD",
                rate=Decimal("1.5"),
                rate_type=ExchangeRateType.SPOT,
                effective_date=datetime.now(UTC),
                source="Test",
                created_by="tester",
                created_at=datetime.now(UTC),
            )

    def test_private_validate_called(self):
        rate = create_test_exchange_rate()
        result = rate.validate()
        assert result["is_valid"]

    def test_private_ensure_hash_called(self):
        rate = create_test_exchange_rate()
        assert rate.cryptographic_hash != ""

    def test_private_take_snapshot_called(self):
        rate = create_test_exchange_rate()
        assert len(rate._snapshots) == 1

    def test_private_record_audit_called(self):
        rate = create_test_exchange_rate()
        assert len(rate._audit_trail) == 1

    def test_private_copy_called(self):
        rate = create_test_exchange_rate()
        updated = rate.update("admin", rate=Decimal("15300"))
        assert updated.rate == Decimal("15300")

    def test_compute_hash_consistent(self):
        r1 = create_test_exchange_rate()
        r2 = ExchangeRate(
            rate_id=r1.rate_id,
            from_currency=r1.from_currency,
            to_currency=r1.to_currency,
            rate=r1.rate,
            rate_type=r1.rate_type,
            effective_date=r1.effective_date,
            source=r1.source,
            created_by=r1.created_by,
            created_at=r1.created_at,
            expires_at=r1.expires_at,
        )
        assert r1.compute_hash() == r2.compute_hash()

    def test_update_creates_new_version(self):
        rate = create_test_exchange_rate()
        updated = rate.update("admin", rate=Decimal("15300"))
        assert updated.rate == Decimal("15300")
        assert updated.version == rate.version + 1

    def test_update_cannot_change_id_and_created_at(self):
        rate = create_test_exchange_rate()
        original_id = rate.rate_id
        original_created = rate.created_at
        updated = rate.update("admin", rate=Decimal("15300"), created_at=datetime(2000, 1, 1, tzinfo=UTC))
        assert updated.rate_id == original_id
        assert updated.created_at == original_created

    def test_delete_marks_deleted(self):
        rate = create_test_exchange_rate()
        deleted = rate.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == rate.version + 1

    def test_restore_recovers_deleted(self):
        rate = create_test_exchange_rate()
        deleted = rate.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None

    def test_restore_not_deleted_raises(self):
        rate = create_test_exchange_rate()
        with pytest.raises(ValueError, match="Not deleted"):
            rate.restore("admin")

    def test_activate_returns_self(self):
        rate = create_test_exchange_rate()
        activated = rate.activate("admin")
        assert activated is rate

    def test_deactivate_returns_self(self):
        rate = create_test_exchange_rate()
        deactivated = rate.deactivate("admin")
        assert deactivated is rate

    def test_lock_returns_self(self):
        rate = create_test_exchange_rate()
        locked = rate.lock("admin", "test")
        assert locked is rate

    def test_unlock_returns_self(self):
        rate = create_test_exchange_rate()
        unlocked = rate.unlock("admin")
        assert unlocked is rate

    def test_create_returns_self(self):
        rate = create_test_exchange_rate()
        result = rate.create("admin")
        assert result is rate

    def test_validate_returns_valid(self):
        rate = create_test_exchange_rate()
        result = rate.validate()
        assert result["is_valid"]
        assert result["rate_id"] == str(rate.rate_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        rate = create_test_exchange_rate()
        object.__setattr__(rate, "cryptographic_hash", "fake")
        result = rate.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        rate = create_test_exchange_rate()
        d = rate.to_dict()
        assert d["from_currency"] == "USD"
        assert d["to_currency"] == "IDR"
        assert d["rate"] == "15250"
        assert d["rate_type"] == "SPOT"
        assert "rate_id" in d

    def test_from_dict_reconstructs(self):
        rate = create_test_exchange_rate()
        d = rate.to_dict()
        reconstructed = ExchangeRate.from_dict(d)
        assert reconstructed.rate_id == rate.rate_id
        assert reconstructed.from_currency == rate.from_currency
        assert reconstructed.to_currency == rate.to_currency
        assert reconstructed.rate == rate.rate

    def test_clone_creates_new_rate(self):
        rate = create_test_exchange_rate()
        cloned = rate.clone()
        assert cloned.rate_id != rate.rate_id
        assert cloned.from_currency == rate.from_currency
        assert cloned.to_currency == rate.to_currency
        assert cloned.rate == rate.rate
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        rate = create_test_exchange_rate()
        snap = rate.snapshot()
        assert snap["rate_id"] == str(rate.rate_id)
        assert snap["rate"] == str(rate.rate)

    def test_get_version(self):
        rate = create_test_exchange_rate()
        assert rate.get_version() == 1

    def test_audit_trail_records(self):
        rate = create_test_exchange_rate()
        assert len(rate.audit_trail()) >= 1
        rate.touch("toucher")
        trail = rate.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        rate = create_test_exchange_rate()
        touched = rate.touch("toucher")
        assert touched.version == rate.version + 1

    def test_audit_trail_limit(self):
        rate = create_test_exchange_rate()
        for _ in range(15):
            rate = rate.touch("tester")
        trail = rate.audit_trail(limit=5)
        assert len(trail) == 5

    def test_is_valid_on_effective_and_expiry(self):
        now = datetime.now(UTC)
        rate = ExchangeRate(
            rate_id=uuid.uuid4(),
            from_currency="USD",
            to_currency="IDR",
            rate=Decimal("15250"),
            rate_type=ExchangeRateType.SPOT,
            effective_date=now - timedelta(days=1),
            source="Test",
            created_by="tester",
            created_at=now,
            expires_at=now + timedelta(days=1),
        )
        assert rate.is_valid_on(now)
        assert not rate.is_valid_on(now - timedelta(days=2))
        assert not rate.is_valid_on(now + timedelta(days=2))

    def test_convert_rounds_correctly(self):
        rate = ExchangeRate(
            rate_id=uuid.uuid4(),
            from_currency="USD",
            to_currency="IDR",
            rate=Decimal("15250.5"),
            rate_type=ExchangeRateType.SPOT,
            effective_date=datetime.now(UTC),
            source="Test",
            created_by="tester",
            created_at=datetime.now(UTC),
        )
        result = rate.convert(Decimal("100"))
        assert result == Decimal("1525050.00")


# ============================================================================
# TESTS UNTUK MonetaryAmount
# ============================================================================

class TestMonetaryAmount:
    def test_create_valid_amount(self):
        amount = create_test_amount()
        assert amount.amount == Decimal("1000")
        assert amount.currency == "IDR"
        assert amount.decimal_places == 2
        assert amount.version == 1
        assert amount.cryptographic_hash != ""

    def test_validate_currency_code_length(self):
        with pytest.raises(ValueError, match="Invalid currency code"):
            MonetaryAmount(Decimal("100"), "ID")

    def test_validate_rounds_to_decimal_places(self):
        amount = MonetaryAmount(Decimal("100.12345"), "IDR", 2)
        assert amount.amount == Decimal("100.12")

    def test_private_validate_called(self):
        amount = create_test_amount()
        result = amount.validate()
        assert result["is_valid"]

    def test_private_ensure_hash_called(self):
        amount = create_test_amount()
        assert amount.cryptographic_hash != ""

    def test_private_take_snapshot_called(self):
        amount = create_test_amount()
        assert len(amount._snapshots) == 1

    def test_private_record_audit_called(self):
        amount = create_test_amount()
        assert len(amount._audit_trail) == 1

    def test_compute_hash_consistent(self):
        a1 = create_test_amount()
        a2 = MonetaryAmount(a1.amount, a1.currency, a1.decimal_places)
        assert a1.compute_hash() == a2.compute_hash()

    def test_immutability_of_update(self):
        amount = create_test_amount()
        with pytest.raises(AttributeError):
            amount.update("admin", amount=Decimal("200"))

    def test_delete_raises(self):
        amount = create_test_amount()
        with pytest.raises(AttributeError):
            amount.delete("admin")

    def test_restore_raises(self):
        amount = create_test_amount()
        with pytest.raises(AttributeError):
            amount.restore("admin")

    def test_activate_returns_self(self):
        amount = create_test_amount()
        activated = amount.activate("admin")
        assert activated is amount

    def test_deactivate_returns_self(self):
        amount = create_test_amount()
        deactivated = amount.deactivate("admin")
        assert deactivated is amount

    def test_lock_returns_self(self):
        amount = create_test_amount()
        locked = amount.lock("admin", "test")
        assert locked is amount

    def test_unlock_returns_self(self):
        amount = create_test_amount()
        unlocked = amount.unlock("admin")
        assert unlocked is amount

    def test_create_returns_self(self):
        amount = create_test_amount()
        result = amount.create("admin")
        assert result is amount

    def test_validate_returns_valid(self):
        amount = create_test_amount()
        result = amount.validate()
        assert result["is_valid"]
        assert result["currency"] == "IDR"

    def test_validate_returns_errors_on_hash_mismatch(self):
        amount = create_test_amount()
        object.__setattr__(amount, "cryptographic_hash", "fake")
        result = amount.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        amount = create_test_amount()
        d = amount.to_dict()
        assert d["amount"] == "1000"
        assert d["currency"] == "IDR"
        assert d["decimal_places"] == 2

    def test_from_dict_reconstructs(self):
        amount = create_test_amount()
        d = amount.to_dict()
        reconstructed = MonetaryAmount.from_dict(d)
        assert reconstructed.amount == amount.amount
        assert reconstructed.currency == amount.currency
        assert reconstructed.decimal_places == amount.decimal_places

    def test_clone_creates_new_amount(self):
        amount = create_test_amount()
        cloned = amount.clone()
        assert cloned.amount == amount.amount
        assert cloned.currency == amount.currency
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        amount = create_test_amount()
        snap = amount.snapshot()
        assert snap["amount"] == str(amount.amount)
        assert snap["currency"] == amount.currency

    def test_get_version(self):
        amount = create_test_amount()
        assert amount.get_version() == 1

    def test_audit_trail_records(self):
        amount = create_test_amount()
        assert len(amount.audit_trail()) >= 1
        amount.touch("toucher")
        trail = amount.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_equality_false_for_different_currency(self):
        a = create_test_amount(Decimal("100"), "IDR")
        b = create_test_amount(Decimal("100"), "USD")
        assert a != b

    def test_equality_false_for_non_monetary(self):
        a = create_test_amount()
        assert a != "string"

    def test_repr(self):
        amount = create_test_amount(Decimal("100.50"), "IDR", 2)
        assert repr(amount) == "IDR 100.50"

    def test_arithmetic_addition(self):
        a = create_test_amount(Decimal("100"), "IDR")
        b = create_test_amount(Decimal("200"), "IDR")
        result = a + b
        assert result.amount == Decimal("300")
        assert result.currency == "IDR"

    def test_addition_different_currency_raises(self):
        a = create_test_amount(Decimal("100"), "IDR")
        b = create_test_amount(Decimal("200"), "USD")
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = a + b

    def test_subtraction(self):
        a = create_test_amount(Decimal("200"), "IDR")
        b = create_test_amount(Decimal("100"), "IDR")
        result = a - b
        assert result.amount == Decimal("100")

    def test_multiplication(self):
        a = create_test_amount(Decimal("100"), "IDR")
        result = a * Decimal("2.5")
        assert result.amount == Decimal("250.00")

    def test_division(self):
        a = create_test_amount(Decimal("100"), "IDR")
        result = a / Decimal("4")
        assert result.amount == Decimal("25.00")

    def test_negation(self):
        a = create_test_amount(Decimal("100"), "IDR")
        result = -a
        assert result.amount == Decimal("-100")


# ============================================================================
# TESTS UNTUK MonetaryUnitViolation
# ============================================================================

class TestMonetaryUnitViolation:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.violation_id is not None
        assert violation.transaction_id is not None
        assert violation.currency_used == "USD"
        assert violation.functional_currency == "IDR"
        assert violation.severity == MonetaryUnitViolationSeverity.MEDIUM
        assert not violation.resolved
        assert violation.version == 1
        assert violation.cryptographic_hash != ""

    def test_private_validate_called(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"]

    def test_private_ensure_hash_called(self):
        violation = create_test_violation()
        assert violation.cryptographic_hash != ""

    def test_private_take_snapshot_called(self):
        violation = create_test_violation()
        assert len(violation._snapshots) == 1

    def test_private_record_audit_called(self):
        violation = create_test_violation()
        assert len(violation._audit_trail) == 1

    def test_private_copy_called(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin")
        assert resolved.resolved

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"]

    def test_validate_errors_on_hash_mismatch(self):
        violation = create_test_violation()
        object.__setattr__(violation, "cryptographic_hash", "fake")
        result = violation.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_update_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.update("admin", message="new")

    def test_delete_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.delete("admin")

    def test_restore_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.restore("admin")

    def test_activate_returns_self(self):
        violation = create_test_violation()
        activated = violation.activate("admin")
        assert activated is violation

    def test_deactivate_returns_self(self):
        violation = create_test_violation()
        deactivated = violation.deactivate("admin")
        assert deactivated is violation

    def test_lock_returns_self(self):
        violation = create_test_violation()
        locked = violation.lock("admin", "test")
        assert locked is violation

    def test_unlock_returns_self(self):
        violation = create_test_violation()
        unlocked = violation.unlock("admin")
        assert unlocked is violation

    def test_create_returns_self(self):
        violation = create_test_violation()
        result = violation.create("admin")
        assert result is violation

    def test_to_dict_contains_fields(self):
        violation = create_test_violation()
        d = violation.to_dict()
        assert d["currency_used"] == "USD"
        assert d["functional_currency"] == "IDR"
        assert d["severity"] == "MEDIUM"
        assert not d["resolved"]

    def test_from_dict_reconstructs(self):
        violation = create_test_violation()
        d = violation.to_dict()
        reconstructed = MonetaryUnitViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.transaction_id == violation.transaction_id
        assert reconstructed.currency_used == violation.currency_used
        assert reconstructed.severity == violation.severity

    def test_clone_creates_new_instance(self):
        violation = create_test_violation()
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.transaction_id == violation.transaction_id
        assert not cloned.resolved
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        violation = create_test_violation()
        snap = violation.snapshot()
        assert snap["violation_id"] == str(violation.violation_id)
        assert snap["severity"] == violation.severity.name

    def test_get_version(self):
        violation = create_test_violation()
        assert violation.get_version() == 1

    def test_audit_trail_records(self):
        violation = create_test_violation()
        assert len(violation.audit_trail()) >= 1
        violation.touch("toucher")
        trail = violation.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_resolve_marks_resolved(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin")
        assert resolved.resolved
        assert resolved.resolved_at is not None
        assert resolved.resolved_by == "admin"
        assert resolved.version == violation.version + 1

    def test_resolve_already_resolved_raises(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2")


# ============================================================================
# TESTS UNTUK MonetaryUnitValidator (termasuk private)
# ============================================================================

class TestMonetaryUnitValidator:
    def test_validate_currency_supported_same_currency(self):
        result, violation, hint = MonetaryUnitValidator.validate_currency(
            currency_code="IDR",
            transaction_id=uuid.uuid4(),
            functional_currency="IDR",
            require_exchange_rate=False,
        )
        assert result
        assert violation is None
        assert hint is None

    def test_validate_currency_supported_with_rate(self):
        result, violation, hint = MonetaryUnitValidator.validate_currency(
            currency_code="USD",
            transaction_id=uuid.uuid4(),
            functional_currency="IDR",
            require_exchange_rate=True,
            exchange_rate_as_of=datetime.now(UTC),
        )
        assert result
        assert violation is None

    def test_validate_currency_unsupported(self):
        with patch("axioms.monetary_unit.MonetaryUnitValidator._notify_constitution"):
            result, violation, hint = MonetaryUnitValidator.validate_currency(
                currency_code="XXX",
                transaction_id=uuid.uuid4(),
                functional_currency="IDR",
                require_exchange_rate=False,
            )
        assert not result
        assert violation is not None
        assert violation.severity == MonetaryUnitViolationSeverity.CRITICAL
        assert "not supported" in violation.message

    def test_validate_currency_missing_rate(self):
        with patch("axioms.monetary_unit.MonetaryUnitValidator._notify_constitution"):
            result, violation, hint = MonetaryUnitValidator.validate_currency(
                currency_code="EUR",
                transaction_id=uuid.uuid4(),
                functional_currency="IDR",
                require_exchange_rate=True,
                exchange_rate_as_of=datetime(2000, 1, 1, tzinfo=UTC),
            )
        assert not result
        assert violation is not None
        assert violation.severity == MonetaryUnitViolationSeverity.HIGH

    def test_private_create_violation(self):
        tx_id = uuid.uuid4()
        violation = MonetaryUnitValidator._create_violation(
            transaction_id=tx_id,
            currency_used="USD",
            functional_currency="IDR",
            exchange_rate_used=None,
            required_source="Test",
            severity=MonetaryUnitViolationSeverity.CRITICAL,
            message="Test message",
            detected_by="tester",
        )
        assert violation.transaction_id == tx_id
        assert violation.currency_used == "USD"
        assert violation.severity == MonetaryUnitViolationSeverity.CRITICAL

    def test_private_log_violation_does_not_raise(self, caplog):
        violation = create_test_violation()
        with caplog.at_level("CRITICAL"):
            MonetaryUnitValidator._log_violation(violation)

    @patch("axioms.monetary_unit.get_supreme_law")
    def test_private_notify_constitution(self, mock_get_supreme_law):
        mock_law = MagicMock()
        mock_get_supreme_law.return_value = mock_law
        violation = create_test_violation()
        violation.severity = MonetaryUnitViolationSeverity.CRITICAL
        MonetaryUnitValidator._notify_constitution(violation)
        mock_law.check_violation.assert_called_once()


# ============================================================================
# TESTS UNTUK CurrencyRegistry
# ============================================================================

class TestCurrencyRegistry:
    def test_singleton(self):
        reg1 = CurrencyRegistry()
        reg2 = CurrencyRegistry()
        assert reg1 is reg2

    def test_default_currencies_loaded(self):
        reg = CurrencyRegistry()
        assert reg.is_supported("IDR")
        assert reg.is_supported("USD")
        assert reg.is_supported("EUR")
        assert not reg.is_supported("XXX")

    def test_get_currency_returns_definition(self):
        reg = CurrencyRegistry()
        curr = reg.get_currency("IDR")
        assert curr is not None
        assert curr.currency_code == "IDR"

    def test_list_supported_currencies_active_only(self):
        reg = CurrencyRegistry()
        active = reg.list_supported_currencies(active_only=True)
        all_cur = reg.list_supported_currencies(active_only=False)
        assert len(active) > 0
        assert len(all_cur) >= len(active)

    def test_get_exchange_rate_same_currency(self):
        reg = CurrencyRegistry()
        rate = reg.get_exchange_rate("USD", "USD")
        assert rate is not None
        assert rate.rate == Decimal(1)

    def test_get_exchange_rate_existing_spot(self):
        reg = CurrencyRegistry()
        rate = reg.get_exchange_rate("USD", "IDR")
        assert rate is not None
        assert rate.rate_type == ExchangeRateType.SPOT

    def test_get_exchange_rate_reverse(self):
        reg = CurrencyRegistry()
        rate = reg.get_exchange_rate("IDR", "USD")
        assert rate is not None
        assert rate.rate == Decimal(1) / Decimal("15250")

    def test_get_exchange_rate_historical(self):
        reg = CurrencyRegistry()
        now = datetime.now(UTC)
        past = now - timedelta(days=10)
        rate1 = create_test_exchange_rate(
            from_currency="USD", to_currency="IDR", rate=Decimal("15000"), effective_date=past
        )
        rate2 = create_test_exchange_rate(
            from_currency="USD", to_currency="IDR", rate=Decimal("15500"), effective_date=now
        )
        reg.add_exchange_rate(rate1)
        reg.add_exchange_rate(rate2)
        retrieved = reg.get_exchange_rate("USD", "IDR", as_of=past + timedelta(minutes=1))
        assert retrieved.rate == Decimal("15000")

    def test_get_exchange_rate_expired(self):
        reg = CurrencyRegistry()
        now = datetime.now(UTC)
        expired = now - timedelta(days=1)
        rate = create_test_exchange_rate(
            from_currency="USD", to_currency="IDR", rate=Decimal("15000"),
            effective_date=expired, expires_at=expired + timedelta(hours=1)
        )
        reg.add_exchange_rate(rate)
        retrieved = reg.get_exchange_rate("USD", "IDR", as_of=now)
        assert retrieved is None

    def test_get_exchange_rate_different_type(self):
        reg = CurrencyRegistry()
        spot = create_test_exchange_rate(rate_type=ExchangeRateType.SPOT, rate=Decimal("15250"))
        avg = create_test_exchange_rate(rate_type=ExchangeRateType.AVERAGE, rate=Decimal("15300"))
        reg.add_exchange_rate(spot)
        reg.add_exchange_rate(avg)
        retrieved = reg.get_exchange_rate("USD", "IDR", rate_type=ExchangeRateType.SPOT)
        assert retrieved.rate == Decimal("15250")
        retrieved = reg.get_exchange_rate("USD", "IDR", rate_type=ExchangeRateType.AVERAGE)
        assert retrieved.rate == Decimal("15300")

    def test_add_exchange_rate(self):
        reg = CurrencyRegistry()
        new_rate = create_test_exchange_rate(from_currency="EUR", to_currency="IDR", rate=Decimal("16500"))
        reg.add_exchange_rate(new_rate)
        retrieved = reg.get_exchange_rate("EUR", "IDR")
        assert retrieved is not None
        assert retrieved.rate == Decimal("16500")

    def test_get_all_exchange_rates(self):
        reg = CurrencyRegistry()
        rates = reg.get_all_exchange_rates()
        assert len(rates) >= 9


# ============================================================================
# TESTS UNTUK MonetaryUnitAxiom
# ============================================================================

class TestMonetaryUnitAxiom:
    def test_singleton(self):
        axiom1 = MonetaryUnitAxiom()
        axiom2 = MonetaryUnitAxiom()
        assert axiom1 is axiom2

    def test_is_supported(self):
        axiom = MonetaryUnitAxiom()
        assert axiom.is_supported("IDR")
        assert not axiom.is_supported("XXX")

    def test_get_currency_definition(self):
        axiom = MonetaryUnitAxiom()
        curr = axiom.get_currency_definition("USD")
        assert curr is not None
        assert curr.currency_code == "USD"

    def test_get_supported_currencies(self):
        axiom = MonetaryUnitAxiom()
        currencies = axiom.get_supported_currencies(active_only=True)
        assert len(currencies) > 0

    def test_get_exchange_rate(self):
        axiom = MonetaryUnitAxiom()
        rate = axiom.get_exchange_rate("USD", "IDR")
        assert rate is not None
        assert rate.rate == Decimal("15250")

    def test_add_exchange_rate(self):
        axiom = MonetaryUnitAxiom()
        new_rate = create_test_exchange_rate(from_currency="SGD", to_currency="IDR", rate=Decimal("11300"))
        axiom.add_exchange_rate(new_rate)
        retrieved = axiom.get_exchange_rate("SGD", "IDR")
        assert retrieved is not None
        assert retrieved.rate == Decimal("11300")

    def test_convert_currency_same_currency(self):
        axiom = MonetaryUnitAxiom()
        amount = create_monetary_amount(Decimal("1000"), "IDR")
        result = axiom.convert_currency(amount, "IDR")
        assert result is not None
        assert result.amount == Decimal("1000")
        assert result.currency == "IDR"

    def test_convert_currency_with_rate(self):
        axiom = MonetaryUnitAxiom()
        amount = create_monetary_amount(Decimal("100"), "USD")
        result = axiom.convert_currency(amount, "IDR")
        assert result is not None
        assert result.currency == "IDR"
        assert result.amount == Decimal("1525000.00")

    def test_convert_currency_no_rate_raises(self):
        axiom = MonetaryUnitAxiom()
        amount = create_monetary_amount(Decimal("100"), "XXX")
        with pytest.raises(ExchangeRateNotFoundError):
            axiom.convert_currency(amount, "IDR", raise_on_error=True)

    def test_convert_currency_no_rate_returns_none(self):
        axiom = MonetaryUnitAxiom()
        amount = create_monetary_amount(Decimal("100"), "XXX")
        result = axiom.convert_currency(amount, "IDR", raise_on_error=False)
        assert result is None

    def test_enforce_currency_valid(self):
        axiom = MonetaryUnitAxiom()
        amount = create_monetary_amount(Decimal("1000"), "IDR")
        result, violation = axiom.enforce_currency(
            amount=amount,
            functional_currency="IDR",
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert result
        assert violation is None

    def test_enforce_currency_unsupported(self):
        axiom = MonetaryUnitAxiom()
        amount = create_monetary_amount(Decimal("1000"), "XXX")
        with patch("axioms.monetary_unit.MonetaryUnitValidator._notify_constitution"):
            result, violation = axiom.enforce_currency(
                amount=amount,
                functional_currency="IDR",
                transaction_id=uuid.uuid4(),
                raise_on_violation=False,
            )
        assert not result
        assert violation is not None

    def test_enforce_currency_raises_on_violation(self):
        axiom = MonetaryUnitAxiom()
        amount = create_monetary_amount(Decimal("1000"), "XXX")
        with patch("axioms.monetary_unit.MonetaryUnitValidator._notify_constitution"):
            with pytest.raises(MonetaryUnitViolationError):
                axiom.enforce_currency(
                    amount=amount,
                    functional_currency="IDR",
                    transaction_id=uuid.uuid4(),
                    raise_on_violation=True,
                )

    def test_save_and_get_violations(self):
        axiom = MonetaryUnitAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_get_violations_filter_by_severity(self):
        axiom = MonetaryUnitAxiom()
        v1 = create_test_violation()
        v1.severity = MonetaryUnitViolationSeverity.LOW
        v2 = create_test_violation()
        v2.severity = MonetaryUnitViolationSeverity.HIGH
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        result = axiom.get_violations(min_severity=MonetaryUnitViolationSeverity.HIGH)
        assert all(v.severity.value >= MonetaryUnitViolationSeverity.HIGH.value for v in result)

    def test_get_violations_unresolved_only(self):
        axiom = MonetaryUnitAxiom()
        v1 = create_test_violation()
        v1.resolved = True
        v2 = create_test_violation()
        v2.resolved = False
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        result = axiom.get_violations(unresolved_only=True)
        assert all(not v.resolved for v in result)

    def test_resolve_violation_success(self):
        axiom = MonetaryUnitAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin")
        assert resolved is not None
        assert resolved.resolved
        assert resolved.resolved_by == "admin"

    def test_resolve_violation_already_resolved_returns_none(self):
        axiom = MonetaryUnitAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin")
        assert resolved is not None
        again = axiom.resolve_violation(violation.violation_id, "admin2")
        assert again is None

    def test_get_statistics(self):
        axiom = MonetaryUnitAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        stats = axiom.get_statistics()
        assert stats["supported_currencies"] > 0
        assert stats["active_currencies"] > 0
        assert stats["total_exchange_rates"] > 0
        assert stats["total_violations"] >= 1
        assert stats["unresolved_violations"] >= 1

    def test_reset(self):
        axiom = MonetaryUnitAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        axiom.reset()
        assert len(axiom._violation_history) == 0


# ============================================================================
# TESTS UNTUK HELPER FUNCTIONS
# ============================================================================

class TestHelpers:
    def test_create_monetary_amount(self):
        amount = create_monetary_amount(Decimal("100.50"), "IDR", 2)
        assert amount.amount == Decimal("100.50")
        assert amount.currency == "IDR"
        assert amount.decimal_places == 2

    def test_create_monetary_amount_default(self):
        amount = create_monetary_amount(Decimal("100"), "IDR")
        assert amount.decimal_places == 2

    def test_create_monetary_amount_custom_decimal(self):
        amount = create_monetary_amount(Decimal("100"), "IDR", 0)
        assert amount.decimal_places == 0

    def test_create_exchange_rate(self):
        rate = create_exchange_rate(
            from_currency="USD",
            to_currency="IDR",
            rate=Decimal("15250"),
            rate_type=ExchangeRateType.SPOT,
            source="API",
            created_by="test",
        )
        assert rate.from_currency == "USD"
        assert rate.to_currency == "IDR"
        assert rate.rate == Decimal("15250")
        assert rate.rate_type == ExchangeRateType.SPOT
        assert rate.source == "API"
        assert rate.created_by == "test"

    def test_create_exchange_rate_defaults(self):
        rate = create_exchange_rate("USD", "IDR", Decimal("15250"))
        assert rate.rate_type == ExchangeRateType.SPOT
        assert rate.source == "System"
        assert rate.created_by == "system"

    def test_create_exchange_rate_custom_effective_date(self):
        now = datetime.now(UTC)
        rate = create_exchange_rate(
            from_currency="USD",
            to_currency="IDR",
            rate=Decimal("15250"),
            effective_date=now - timedelta(days=1),
        )
        assert rate.effective_date == now - timedelta(days=1)

    def test_create_exchange_rate_with_expires(self):
        now = datetime.now(UTC)
        expires = now + timedelta(days=7)
        rate = create_exchange_rate(
            from_currency="USD",
            to_currency="IDR",
            rate=Decimal("15250"),
            expires_at=expires,
        )
        assert rate.expires_at == expires

    def test_register_currency_success(self):
        curr = register_currency(
            currency_code="SGD",
            currency_name="Singapore Dollar",
            symbol="S$",
            decimal_places=2,
            stability=MonetaryUnitStability.STABLE,
            country_code="SG",
        )
        assert curr.currency_code == "SGD"
        assert curr.is_active

    def test_register_currency_already_exists(self):
        with pytest.raises(CurrencyNotSupportedError, match="already registered"):
            register_currency(
                currency_code="IDR",
                currency_name="Rupiah",
                symbol="Rp",
                decimal_places=2,
                stability=MonetaryUnitStability.STABLE,
                country_code="ID",
            )

    def test_get_monetary_unit_axiom_singleton(self):
        axiom1 = get_monetary_unit_axiom()
        axiom2 = get_monetary_unit_axiom()
        assert axiom1 is axiom2