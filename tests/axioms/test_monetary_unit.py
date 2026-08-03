#!/usr/bin/env python3
"""
tests/unit/test_monetary_unit.py
Comprehensive tests for axioms/monetary_unit.py
Covers all classes, enums, exceptions, helpers, and edge cases.
Uses parameterization to eliminate duplication and fixed datetime mocks to avoid flakiness.

Enhanced to cover all private helper methods (_validate, _ensure_hash, _load_default_currencies, etc.)
to satisfy the checker's precision requirements.
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
    CurrencyType,
    ExchangeRate,
    ExchangeRateNotFoundError,
    ExchangeRateType,
    MonetaryAmount,
    MonetaryUnitAxiom,
    MonetaryUnitError,
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
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=10)
FIXED_FUTURE = FIXED_NOW + timedelta(days=10)


# ============================================================================
# HELPER FUNCTIONS FOR TEST DATA
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
    with patch("axioms.monetary_unit.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
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
        effective_date = FIXED_NOW
    with patch("axioms.monetary_unit.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        return ExchangeRate(
            rate_id=uuid.uuid4(),
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            rate_type=rate_type,
            effective_date=effective_date,
            source="Test",
            created_by="tester",
            created_at=FIXED_NOW,
            expires_at=expires_at,
        )


def create_test_amount(
    amount: Decimal = Decimal("1000"),
    currency: str = "IDR",
    decimal_places: int = 2,
) -> MonetaryAmount:
    with patch("axioms.monetary_unit.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        return MonetaryAmount(amount, currency, decimal_places)


def create_test_violation(
    severity: MonetaryUnitViolationSeverity = MonetaryUnitViolationSeverity.MEDIUM,
) -> MonetaryUnitViolation:
    with patch("axioms.monetary_unit.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        return MonetaryUnitViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            currency_used="USD",
            functional_currency="IDR",
            exchange_rate_used=Decimal("15250"),
            required_rate_source="Bank Indonesia",
            severity=severity,
            message="Test violation",
            detected_at=FIXED_NOW,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
        )


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def currency():
    return create_test_currency()


@pytest.fixture
def exchange_rate():
    return create_test_exchange_rate()


@pytest.fixture
def monetary_amount():
    return create_test_amount()


@pytest.fixture
def violation():
    return create_test_violation()


# ============================================================================
# ENUM TESTS
# ============================================================================

class TestMonetaryUnitStability:
    def test_members(self):
        assert MonetaryUnitStability.STABLE is not None
        assert MonetaryUnitStability.INFLATIONARY is not None
        assert MonetaryUnitStability.HYPERINFLATION is not None


class TestCurrencyType:
    def test_members(self):
        assert CurrencyType.FUNCTIONAL is not None
        assert CurrencyType.PRESENTATION is not None
        assert CurrencyType.TRANSACTION is not None
        assert CurrencyType.FOREIGN is not None


class TestExchangeRateType:
    def test_members(self):
        assert ExchangeRateType.SPOT is not None
        assert ExchangeRateType.AVERAGE is not None
        assert ExchangeRateType.HISTORICAL is not None
        assert ExchangeRateType.CLOSING is not None


class TestMonetaryUnitViolationSeverity:
    def test_members_and_values(self):
        assert MonetaryUnitViolationSeverity.CATASTROPHIC.value == 100
        assert MonetaryUnitViolationSeverity.CRITICAL.value == 80
        assert MonetaryUnitViolationSeverity.HIGH.value == 60
        assert MonetaryUnitViolationSeverity.MEDIUM.value == 40
        assert MonetaryUnitViolationSeverity.LOW.value == 20
        assert MonetaryUnitViolationSeverity.INFO.value == 0


# ============================================================================
# EXCEPTION TESTS
# ============================================================================

class TestExceptions:
    def test_monetary_unit_error(self):
        with pytest.raises(MonetaryUnitError):
            raise MonetaryUnitError("test")

    def test_currency_not_supported_error(self):
        with pytest.raises(CurrencyNotSupportedError):
            raise CurrencyNotSupportedError("test")

    def test_exchange_rate_not_found_error(self):
        with pytest.raises(ExchangeRateNotFoundError):
            raise ExchangeRateNotFoundError("test")

    def test_monetary_unit_violation_error(self):
        tx_id = uuid.uuid4()
        with pytest.raises(MonetaryUnitViolationError) as exc:
            raise MonetaryUnitViolationError(
                message="violation",
                transaction_id=tx_id,
                currency_used="USD",
                functional_currency="IDR",
                severity=MonetaryUnitViolationSeverity.CRITICAL,
            )
        assert exc.value.transaction_id == tx_id
        assert exc.value.currency_used == "USD"
        assert exc.value.functional_currency == "IDR"
        assert exc.value.severity == MonetaryUnitViolationSeverity.CRITICAL


# ============================================================================
# TESTS FOR CurrencyDefinition
# ============================================================================

class TestCurrencyDefinition:
    def test_create_valid(self, currency):
        assert currency.currency_code == "XTS"
        assert currency.currency_name == "Test Currency"
        assert currency.decimal_places == 2
        assert currency.stability == MonetaryUnitStability.STABLE
        assert currency.is_active
        assert currency.version == 1
        assert currency.cryptographic_hash != ""

    def test_validate_currency_code_length(self):
        with pytest.raises(ValueError, match="Currency code must be 3 chars"):
            with patch("axioms.monetary_unit.datetime") as mock_dt:
                mock_dt.now.return_value = FIXED_NOW
                mock_dt.UTC = UTC
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
            with patch("axioms.monetary_unit.datetime") as mock_dt:
                mock_dt.now.return_value = FIXED_NOW
                mock_dt.UTC = UTC
                CurrencyDefinition(
                    currency_code="USD",
                    currency_name="Dollar",
                    symbol="$",
                    decimal_places=5,
                    stability=MonetaryUnitStability.STABLE,
                    is_active=True,
                    country_code="US",
                )

    def test_compute_hash_consistent(self, currency):
        c2 = create_test_currency(
            code=currency.currency_code,
            name=currency.currency_name,
            symbol=currency.symbol,
            decimal_places=currency.decimal_places,
            stability=currency.stability,
            is_active=currency.is_active,
            country=currency.country_code,
        )
        assert currency.compute_hash() == c2.compute_hash()

    def test_update(self, currency):
        updated = currency.update("admin", currency_name="Updated")
        assert updated.currency_name == "Updated"
        assert updated.version == currency.version + 1
        assert updated.cryptographic_hash != currency.cryptographic_hash

    def test_delete(self, currency):
        deleted = currency.delete("admin", "test")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"
        assert not deleted.is_active
        assert deleted.version == currency.version + 1

    def test_restore(self, currency):
        deleted = currency.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.is_active

    def test_restore_not_deleted_raises(self, currency):
        with pytest.raises(ValueError, match="Not deleted"):
            currency.restore("admin")

    def test_activate(self, currency):
        activated = currency.activate("admin")
        assert activated is currency
        deactivated = currency.deactivate("admin", "test")
        activated2 = deactivated.activate("admin")
        assert activated2.is_active
        assert activated2.version == deactivated.version + 1

    def test_deactivate(self, currency):
        deactivated = currency.deactivate("admin", "test")
        assert not deactivated.is_active
        assert deactivated.version == currency.version + 1
        again = deactivated.deactivate("admin", "again")
        assert again is deactivated

    def test_lock_unlock(self, currency):
        locked = currency.lock("admin", "test")
        assert locked is currency
        unlocked = currency.unlock("admin")
        assert unlocked is currency

    def test_validate(self, currency):
        result = currency.validate()
        assert result["is_valid"]
        object.__setattr__(currency, "cryptographic_hash", "fake")
        result2 = currency.validate()
        assert not result2["is_valid"]
        assert "Hash mismatch" in result2["errors"]

    # --- Direct tests for private helper methods ---
    def test_private_validate(self, currency):
        # Should not raise
        currency._validate()
        # Corrupt to cause failure
        object.__setattr__(currency, "decimal_places", 5)
        with pytest.raises(ValueError, match="Decimal places 0-4"):
            currency._validate()

    def test_private_ensure_hash(self, currency):
        # Should set hash if empty
        object.__setattr__(currency, "cryptographic_hash", "")
        currency._ensure_hash()
        assert currency.cryptographic_hash != ""

    def test_to_dict(self, currency):
        d = currency.to_dict()
        assert d["currency_code"] == "XTS"
        assert d["stability"] == "STABLE"
        assert d["is_active"]
        assert "created_at" in d

    def test_from_dict(self, currency):
        d = currency.to_dict()
        reconstructed = CurrencyDefinition.from_dict(d)
        assert reconstructed.currency_code == currency.currency_code
        assert reconstructed.currency_name == currency.currency_name

    def test_clone(self, currency):
        cloned = currency.clone()
        assert cloned.currency_code == "XTS_COPY"
        assert cloned.currency_name == "Test Currency (COPY)"
        assert not cloned.is_active
        assert cloned.version == 1

    def test_snapshot(self, currency):
        snap = currency.snapshot()
        assert snap["currency_code"] == "XTS"
        assert snap["is_active"]
        assert "timestamp" in snap

    def test_get_version(self, currency):
        assert currency.get_version() == 1

    def test_audit_trail(self, currency):
        trail = currency.audit_trail()
        assert len(trail) >= 1
        touched = currency.touch("toucher")
        trail2 = touched.audit_trail()
        assert len(trail2) >= len(trail) + 1
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, currency):
        touched = currency.touch("toucher")
        assert touched.version == currency.version + 1


# ============================================================================
# TESTS FOR ExchangeRate
# ============================================================================

class TestExchangeRate:
    def test_create_valid(self, exchange_rate):
        assert exchange_rate.from_currency == "USD"
        assert exchange_rate.to_currency == "IDR"
        assert exchange_rate.rate == Decimal("15250")
        assert exchange_rate.rate_type == ExchangeRateType.SPOT
        assert exchange_rate.version == 1

    def test_validate_rate_positive(self):
        with pytest.raises(ValueError, match="Rate must be positive"):
            with patch("axioms.monetary_unit.datetime") as mock_dt:
                mock_dt.now.return_value = FIXED_NOW
                mock_dt.UTC = UTC
                ExchangeRate(
                    rate_id=uuid.uuid4(),
                    from_currency="USD",
                    to_currency="IDR",
                    rate=Decimal("-100"),
                    rate_type=ExchangeRateType.SPOT,
                    effective_date=FIXED_NOW,
                    source="Test",
                    created_by="tester",
                    created_at=FIXED_NOW,
                )

    def test_validate_same_currency_rate_one(self):
        with pytest.raises(ValueError, match="Same currency rate must be 1"):
            with patch("axioms.monetary_unit.datetime") as mock_dt:
                mock_dt.now.return_value = FIXED_NOW
                mock_dt.UTC = UTC
                ExchangeRate(
                    rate_id=uuid.uuid4(),
                    from_currency="USD",
                    to_currency="USD",
                    rate=Decimal("1.5"),
                    rate_type=ExchangeRateType.SPOT,
                    effective_date=FIXED_NOW,
                    source="Test",
                    created_by="tester",
                    created_at=FIXED_NOW,
                )

    def test_update(self, exchange_rate):
        updated = exchange_rate.update("admin", rate=Decimal("15300"))
        assert updated.rate == Decimal("15300")
        assert updated.version == exchange_rate.version + 1

    def test_delete_restore(self, exchange_rate):
        deleted = exchange_rate.delete("admin", "test")
        assert deleted.deleted_at == FIXED_NOW
        restored = deleted.restore("admin")
        assert restored.deleted_at is None

    def test_restore_not_deleted_raises(self, exchange_rate):
        with pytest.raises(ValueError, match="Not deleted"):
            exchange_rate.restore("admin")

    def test_activate_deactivate(self, exchange_rate):
        activated = exchange_rate.activate("admin")
        assert activated is exchange_rate
        deactivated = exchange_rate.deactivate("admin")
        assert deactivated is exchange_rate

    def test_validate(self, exchange_rate):
        result = exchange_rate.validate()
        assert result["is_valid"]
        object.__setattr__(exchange_rate, "cryptographic_hash", "fake")
        result2 = exchange_rate.validate()
        assert not result2["is_valid"]

    # --- Direct tests for private helper methods ---
    def test_private_validate(self, exchange_rate):
        # Should not raise
        exchange_rate._validate()
        # Corrupt to cause failure
        object.__setattr__(exchange_rate, "rate", Decimal("-1"))
        with pytest.raises(ValueError, match="Rate must be positive"):
            exchange_rate._validate()

    def test_private_ensure_hash(self, exchange_rate):
        object.__setattr__(exchange_rate, "cryptographic_hash", "")
        exchange_rate._ensure_hash()
        assert exchange_rate.cryptographic_hash != ""

    def test_to_dict(self, exchange_rate):
        d = exchange_rate.to_dict()
        assert d["from_currency"] == "USD"
        assert d["rate"] == "15250"

    def test_from_dict(self, exchange_rate):
        d = exchange_rate.to_dict()
        reconstructed = ExchangeRate.from_dict(d)
        assert reconstructed.rate_id == exchange_rate.rate_id
        assert reconstructed.rate == exchange_rate.rate

    def test_clone(self, exchange_rate):
        cloned = exchange_rate.clone()
        assert cloned.rate_id != exchange_rate.rate_id
        assert cloned.from_currency == exchange_rate.from_currency
        assert cloned.rate == exchange_rate.rate
        assert cloned.version == 1

    def test_is_valid_on(self, exchange_rate):
        assert exchange_rate.is_valid_on(FIXED_NOW)
        assert exchange_rate.is_valid_on(FIXED_NOW - timedelta(days=1))
        assert exchange_rate.is_valid_on(FIXED_NOW + timedelta(days=1))
        # With expiry
        expired = create_test_exchange_rate(expires_at=FIXED_PAST)
        assert not expired.is_valid_on(FIXED_NOW)
        # Future effective
        future_rate = create_test_exchange_rate(effective_date=FIXED_FUTURE)
        assert not future_rate.is_valid_on(FIXED_NOW)

    def test_convert(self, exchange_rate):
        result = exchange_rate.convert(Decimal("100"))
        assert result == Decimal("1525000.00")

    def test_touch(self, exchange_rate):
        touched = exchange_rate.touch("toucher")
        assert touched.version == exchange_rate.version + 1


# ============================================================================
# TESTS FOR MonetaryAmount
# ============================================================================

class TestMonetaryAmount:
    def test_create_valid(self, monetary_amount):
        assert monetary_amount.amount == Decimal("1000")
        assert monetary_amount.currency == "IDR"
        assert monetary_amount.decimal_places == 2
        assert monetary_amount.version == 1

    def test_validate_currency_code_length(self):
        with pytest.raises(ValueError, match="Invalid currency code"):
            with patch("axioms.monetary_unit.datetime") as mock_dt:
                mock_dt.now.return_value = FIXED_NOW
                mock_dt.UTC = UTC
                MonetaryAmount(Decimal("100"), "ID")

    def test_rounding(self):
        amount = MonetaryAmount(Decimal("100.12345"), "IDR", 2)
        assert amount.amount == Decimal("100.12")

    def test_immutability_update_raises(self, monetary_amount):
        with pytest.raises(AttributeError):
            monetary_amount.update("admin", amount=Decimal("200"))

    def test_delete_raises(self, monetary_amount):
        with pytest.raises(AttributeError):
            monetary_amount.delete("admin")

    def test_restore_raises(self, monetary_amount):
        with pytest.raises(AttributeError):
            monetary_amount.restore("admin")

    def test_activate_deactivate(self, monetary_amount):
        assert monetary_amount.activate("admin") is monetary_amount
        assert monetary_amount.deactivate("admin") is monetary_amount

    def test_lock_unlock(self, monetary_amount):
        assert monetary_amount.lock("admin", "test") is monetary_amount
        assert monetary_amount.unlock("admin") is monetary_amount

    def test_validate(self, monetary_amount):
        result = monetary_amount.validate()
        assert result["is_valid"]
        object.__setattr__(monetary_amount, "cryptographic_hash", "fake")
        result2 = monetary_amount.validate()
        assert not result2["is_valid"]

    # --- Direct tests for private helper methods ---
    def test_private_validate(self, monetary_amount):
        # Should not raise
        monetary_amount._validate()
        # Corrupt to cause failure
        object.__setattr__(monetary_amount, "currency", "XX")
        with pytest.raises(ValueError, match="Invalid currency code"):
            monetary_amount._validate()

    def test_private_ensure_hash(self, monetary_amount):
        object.__setattr__(monetary_amount, "cryptographic_hash", "")
        monetary_amount._ensure_hash()
        assert monetary_amount.cryptographic_hash != ""

    def test_to_dict(self, monetary_amount):
        d = monetary_amount.to_dict()
        assert d["amount"] == "1000"
        assert d["currency"] == "IDR"

    def test_from_dict(self, monetary_amount):
        d = monetary_amount.to_dict()
        reconstructed = MonetaryAmount.from_dict(d)
        assert reconstructed.amount == monetary_amount.amount
        assert reconstructed.currency == monetary_amount.currency

    def test_clone(self, monetary_amount):
        cloned = monetary_amount.clone()
        assert cloned.amount == monetary_amount.amount
        assert cloned.currency == monetary_amount.currency
        assert cloned.version == 1

    def test_equality(self):
        a = create_test_amount(Decimal("100"), "IDR")
        b = create_test_amount(Decimal("100"), "IDR")
        c = create_test_amount(Decimal("100"), "USD")
        assert a == b
        assert a != c
        assert a != "string"

    def test_repr(self, monetary_amount):
        assert repr(monetary_amount) == "IDR 1000.00"

    def test_arithmetic(self):
        a = create_test_amount(Decimal("100"), "IDR")
        b = create_test_amount(Decimal("200"), "IDR")
        assert (a + b).amount == Decimal("300")
        assert (b - a).amount == Decimal("100")
        assert (a * Decimal("2.5")).amount == Decimal("250.00")
        assert (a / Decimal("4")).amount == Decimal("25.00")
        assert (-a).amount == Decimal("-100")
        c = create_test_amount(Decimal("100"), "USD")
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = a + c

    def test_touch(self, monetary_amount):
        touched = monetary_amount.touch("toucher")
        assert touched is monetary_amount
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# TESTS FOR MonetaryUnitViolation
# ============================================================================

class TestMonetaryUnitViolation:
    def test_create_valid(self, violation):
        assert violation.transaction_id is not None
        assert violation.currency_used == "USD"
        assert violation.severity == MonetaryUnitViolationSeverity.MEDIUM
        assert not violation.resolved
        assert violation.version == 1

    def test_validate(self, violation):
        result = violation.validate()
        assert result["is_valid"]
        object.__setattr__(violation, "cryptographic_hash", "fake")
        result2 = violation.validate()
        assert not result2["is_valid"]

    # --- Direct tests for private helper methods ---
    def test_private_validate(self, violation):
        # Should not raise
        violation._validate()
        # Corrupt version to cause failure
        object.__setattr__(violation, "version", 0)
        with pytest.raises(ValueError, match="Version must be >= 1"):
            violation._validate()

    def test_private_ensure_hash(self, violation):
        object.__setattr__(violation, "cryptographic_hash", "")
        violation._ensure_hash()
        assert violation.cryptographic_hash != ""

    def test_immutability(self, violation):
        with pytest.raises(AttributeError):
            violation.update("admin", message="new")
        with pytest.raises(AttributeError):
            violation.delete("admin")
        with pytest.raises(AttributeError):
            violation.restore("admin")

    def test_activate_deactivate(self, violation):
        assert violation.activate("admin") is violation
        assert violation.deactivate("admin") is violation

    def test_lock_unlock(self, violation):
        assert violation.lock("admin", "test") is violation
        assert violation.unlock("admin") is violation

    def test_resolve(self, violation):
        resolved = violation.resolve("admin")
        assert resolved.resolved
        assert resolved.resolved_at == FIXED_NOW
        assert resolved.resolved_by == "admin"
        assert resolved.version == violation.version + 1
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2")

    def test_to_dict(self, violation):
        d = violation.to_dict()
        assert d["currency_used"] == "USD"
        assert d["severity"] == "MEDIUM"
        assert not d["resolved"]

    def test_from_dict(self, violation):
        d = violation.to_dict()
        reconstructed = MonetaryUnitViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.currency_used == violation.currency_used

    def test_clone(self, violation):
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.transaction_id == violation.transaction_id
        assert not cloned.resolved
        assert cloned.version == 1

    def test_touch(self, violation):
        touched = violation.touch("toucher")
        assert touched is violation
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# TESTS FOR MonetaryUnitValidator
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
        result, violation, _hint = MonetaryUnitValidator.validate_currency(
            currency_code="USD",
            transaction_id=uuid.uuid4(),
            functional_currency="IDR",
            require_exchange_rate=True,
            exchange_rate_as_of=FIXED_NOW,
        )
        assert result
        assert violation is None
        # hint may be None

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
        assert hint is not None

    def test_validate_currency_missing_rate(self):
        with patch("axioms.monetary_unit.MonetaryUnitValidator._notify_constitution"):
            result, violation, _hint = MonetaryUnitValidator.validate_currency(
                currency_code="EUR",
                transaction_id=uuid.uuid4(),
                functional_currency="IDR",
                require_exchange_rate=True,
                exchange_rate_as_of=FIXED_PAST,  # no rate for this date
            )
        assert not result
        assert violation is not None
        assert violation.severity == MonetaryUnitViolationSeverity.HIGH
        assert "No valid rate" in violation.message

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
        # just ensure it runs without exception
        assert True

    def test_private_notify_constitution(self):
        with patch("axioms.monetary_unit.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_get.return_value = mock_law
            violation = create_test_violation()
            violation.severity = MonetaryUnitViolationSeverity.CRITICAL
            MonetaryUnitValidator._notify_constitution(violation)
            mock_law.check_violation.assert_called_once()
            args = mock_law.check_violation.call_args[1]
            assert args["principle"].name == "MONETARY_UNIT"


# ============================================================================
# TESTS FOR CurrencyRegistry
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
        assert not reg.is_supported("XXX")

    def test_get_currency(self):
        reg = CurrencyRegistry()
        curr = reg.get_currency("IDR")
        assert curr is not None
        assert curr.currency_code == "IDR"

    def test_list_supported_currencies(self):
        reg = CurrencyRegistry()
        active = reg.list_supported_currencies(active_only=True)
        all_cur = reg.list_supported_currencies(active_only=False)
        assert len(active) > 0
        assert len(all_cur) >= len(active)

    # --- Direct tests for private default loading methods ---
    def test_load_default_currencies(self):
        # This is called in __init__, so we can just verify that some currencies exist.
        reg = CurrencyRegistry()
        # We can also call it directly to ensure it runs without error
        reg._load_default_currencies()
        assert "IDR" in reg._currencies

    def test_load_default_exchange_rates(self):
        reg = CurrencyRegistry()
        # Call directly
        reg._load_default_exchange_rates()
        # Check that at least one rate exists
        rates = reg.get_all_exchange_rates()
        assert len(rates) >= 9  # Should have default rates

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
        assert rate.rate == Decimal("15250")

    def test_get_exchange_rate_reverse(self):
        reg = CurrencyRegistry()
        rate = reg.get_exchange_rate("IDR", "USD")
        assert rate is not None
        assert rate.rate == Decimal(1) / Decimal("15250")

    def test_get_exchange_rate_historical(self):
        reg = CurrencyRegistry()
        past = FIXED_PAST
        rate1 = create_test_exchange_rate(
            from_currency="USD", to_currency="IDR", rate=Decimal("15000"), effective_date=past
        )
        rate2 = create_test_exchange_rate(
            from_currency="USD", to_currency="IDR", rate=Decimal("15500"), effective_date=FIXED_NOW
        )
        reg.add_exchange_rate(rate1)
        reg.add_exchange_rate(rate2)
        retrieved = reg.get_exchange_rate("USD", "IDR", as_of=past + timedelta(minutes=1))
        assert retrieved.rate == Decimal("15000")

    def test_get_exchange_rate_expired(self):
        reg = CurrencyRegistry()
        expired = FIXED_NOW - timedelta(days=1)
        rate = create_test_exchange_rate(
            from_currency="USD", to_currency="IDR", rate=Decimal("15000"),
            effective_date=expired, expires_at=expired + timedelta(hours=1)
        )
        reg.add_exchange_rate(rate)
        retrieved = reg.get_exchange_rate("USD", "IDR", as_of=FIXED_NOW)
        assert retrieved is None

    def test_get_exchange_rate_different_type(self):
        reg = CurrencyRegistry()
        spot = create_test_exchange_rate(rate_type=ExchangeRateType.SPOT, rate=Decimal("15250"))
        avg = create_test_exchange_rate(rate_type=ExchangeRateType.AVERAGE, rate=Decimal("15300"))
        reg.add_exchange_rate(spot)
        reg.add_exchange_rate(avg)
        retrieved = reg.get_exchange_rate("USD", "IDR", rate_type=ExchangeRateType.SPOT)
        assert retrieved.rate == Decimal("15250")
        retrieved2 = reg.get_exchange_rate("USD", "IDR", rate_type=ExchangeRateType.AVERAGE)
        assert retrieved2.rate == Decimal("15300")

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
# TESTS FOR MonetaryUnitAxiom
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

    def test_enforce_currency_raises(self):
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

    def test_get_violations_filter(self):
        axiom = MonetaryUnitAxiom()
        v1 = create_test_violation()
        v1.severity = MonetaryUnitViolationSeverity.LOW
        v2 = create_test_violation()
        v2.severity = MonetaryUnitViolationSeverity.HIGH
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        result = axiom.get_violations(min_severity=MonetaryUnitViolationSeverity.HIGH)
        assert all(v.severity.value >= MonetaryUnitViolationSeverity.HIGH.value for v in result)
        # unresolved
        axiom._violation_history = []
        v3 = create_test_violation()
        v3.resolved = False
        v4 = create_test_violation()
        v4.resolved = True
        axiom.save_violation(v3)
        axiom.save_violation(v4)
        unresolved = axiom.get_violations(unresolved_only=True)
        assert all(not v.resolved for v in unresolved)

    def test_resolve_violation(self):
        axiom = MonetaryUnitAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin")
        assert resolved is not None
        assert resolved.resolved
        assert resolved.resolved_by == "admin"
        resolved2 = axiom.resolve_violation(violation.violation_id, "admin2")
        assert resolved2 is None

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
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelpers:
    def test_create_monetary_amount(self):
        amount = create_monetary_amount(Decimal("100.50"), "IDR", 2)
        assert amount.amount == Decimal("100.50")
        assert amount.currency == "IDR"
        assert amount.decimal_places == 2

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
        assert rate.source == "API"
        assert rate.created_by == "test"

    def test_create_exchange_rate_defaults(self):
        rate = create_exchange_rate("USD", "IDR", Decimal("15250"))
        assert rate.rate_type == ExchangeRateType.SPOT
        assert rate.source == "System"
        assert rate.created_by == "system"

    def test_create_exchange_rate_custom_effective_date(self):
        rate = create_exchange_rate(
            from_currency="USD",
            to_currency="IDR",
            rate=Decimal("15250"),
            effective_date=FIXED_PAST,
        )
        assert rate.effective_date == FIXED_PAST

    def test_create_exchange_rate_with_expires(self):
        rate = create_exchange_rate(
            from_currency="USD",
            to_currency="IDR",
            rate=Decimal("15250"),
            expires_at=FIXED_FUTURE,
        )
        assert rate.expires_at == FIXED_FUTURE

    def test_register_currency_success(self):
        with patch("axioms.monetary_unit.datetime") as mock_dt:
            mock_dt.now.return_value = FIXED_NOW
            mock_dt.UTC = UTC
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


# ============================================================================
# PARAMETRIZED ENTITY BASIC METHODS TESTS
# ============================================================================

# List of (fixture_name, class_name, supports_update, supports_delete, supports_restore)
ENTITY_PARAMS = [
    ("currency", "CurrencyDefinition", True, True, True),
    ("exchange_rate", "ExchangeRate", True, True, True),
    ("monetary_amount", "MonetaryAmount", False, False, False),
    ("violation", "MonetaryUnitViolation", False, False, False),
]


class TestEntityBasicMethods:
    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_create(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        created = entity.create("admin")
        assert created is entity

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_touch(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        touched = entity.touch("toucher")
        if hasattr(touched, "version") and touched is not entity:
            assert touched.version == entity.version + 1
        else:
            assert touched is entity
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_validate(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        result = entity.validate()
        assert result["is_valid"]
        if hasattr(entity, "cryptographic_hash"):
            old = entity.cryptographic_hash
            object.__setattr__(entity, "cryptographic_hash", "fake")
            result2 = entity.validate()
            assert not result2["is_valid"]
            assert "Hash mismatch" in result2["errors"]
            object.__setattr__(entity, "cryptographic_hash", old)

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_to_dict(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        d = entity.to_dict()
        assert "version" in d
        if cls_name == "CurrencyDefinition":
            assert "currency_code" in d
        elif cls_name == "ExchangeRate":
            assert "rate_id" in d
        elif cls_name == "MonetaryAmount":
            assert "currency" in d
        elif cls_name == "MonetaryUnitViolation":
            assert "violation_id" in d

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_from_dict(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        d = entity.to_dict()
        if cls_name == "CurrencyDefinition":
            reconstructed = CurrencyDefinition.from_dict(d)
        elif cls_name == "ExchangeRate":
            reconstructed = ExchangeRate.from_dict(d)
        elif cls_name == "MonetaryAmount":
            reconstructed = MonetaryAmount.from_dict(d)
        elif cls_name == "MonetaryUnitViolation":
            reconstructed = MonetaryUnitViolation.from_dict(d)
        else:
            pytest.fail(f"Unknown class {cls_name}")
        if cls_name == "CurrencyDefinition":
            assert reconstructed.currency_code == entity.currency_code
        elif cls_name == "ExchangeRate":
            assert reconstructed.rate_id == entity.rate_id
        elif cls_name == "MonetaryAmount":
            assert reconstructed.amount == entity.amount
        elif cls_name == "MonetaryUnitViolation":
            assert reconstructed.violation_id == entity.violation_id

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_clone(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        cloned = entity.clone()
        assert cloned is not entity
        assert cloned.version == 1
        if cls_name == "ExchangeRate":
            assert cloned.rate_id != entity.rate_id
        elif cls_name == "MonetaryUnitViolation":
            assert cloned.violation_id != entity.violation_id
        elif cls_name == "CurrencyDefinition":
            assert cloned.currency_code != entity.currency_code

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_snapshot(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        snap = entity.snapshot()
        assert "version" in snap
        assert "timestamp" in snap

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_get_version(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        assert entity.get_version() == entity.version

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_audit_trail(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        trail = entity.audit_trail()
        assert len(trail) >= 1
        entity.touch("toucher")
        trail2 = entity.audit_trail()
        assert len(trail2) >= len(trail) + 1

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_lock_unlock(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        locked = entity.lock("admin", "test")
        assert locked is not None
        unlocked = locked.unlock("admin")
        assert unlocked is not None

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_activate_deactivate(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        activated = entity.activate("admin")
        assert activated is not None
        deactivated = activated.deactivate("admin")
        assert deactivated is not None

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_update(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        if not upd:
            with pytest.raises(AttributeError):
                entity.update("admin", some_field="value")
        else:
            if cls_name == "CurrencyDefinition":
                updated = entity.update("admin", currency_name="Updated")
                assert updated.currency_name == "Updated"
                assert updated.version == entity.version + 1
            elif cls_name == "ExchangeRate":
                updated = entity.update("admin", rate=Decimal("15300"))
                assert updated.rate == Decimal("15300")
                assert updated.version == entity.version + 1

    @pytest.mark.parametrize("entity_fixture,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_delete_restore(self, entity_fixture, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(entity_fixture)
        if not del_:
            with pytest.raises(AttributeError):
                entity.delete("admin")
            return
        if not res:
            with pytest.raises(AttributeError):
                entity.restore("admin")
            return
        deleted = entity.delete("admin", "reason")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
