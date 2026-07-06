#!/usr/bin/env python3
"""
Module: monetary_unit.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: pencatatan hanya dalam satuan uang yang stabil.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, getcontext
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    get_supreme_law,
)

logger = logging.getLogger(__name__)

getcontext().prec = 28


# === 1. ENUMS ===


class MonetaryUnitStability(Enum):
    STABLE = auto()
    INFLATIONARY = auto()
    HYPERINFLATION = auto()


class CurrencyType(Enum):
    FUNCTIONAL = auto()
    PRESENTATION = auto()
    TRANSACTION = auto()
    FOREIGN = auto()


class ExchangeRateType(Enum):
    SPOT = auto()
    AVERAGE = auto()
    HISTORICAL = auto()
    CLOSING = auto()


class MonetaryUnitViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


# === 2. EXCEPTIONS ===


class MonetaryUnitError(Exception):
    pass


class CurrencyNotSupportedError(MonetaryUnitError):
    pass


class ExchangeRateNotFoundError(MonetaryUnitError):
    pass


class MonetaryUnitViolationError(Exception):
    def __init__(
        self,
        message: str,
        transaction_id: UUID,
        currency_used: str,
        functional_currency: str,
        severity: MonetaryUnitViolationSeverity,
    ):
        self.transaction_id = transaction_id
        self.currency_used = currency_used
        self.functional_currency = functional_currency
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | TX: {transaction_id}, Cur: {currency_used}, Func: {functional_currency}"
        )


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class CurrencyDefinition:
    currency_code: str
    currency_name: str
    symbol: str
    decimal_places: int
    stability: MonetaryUnitStability
    is_active: bool
    country_code: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if len(self.currency_code) != 3:
            raise ValueError(f"Currency code must be 3 chars: {self.currency_code}")
        if self.decimal_places < 0 or self.decimal_places > 4:
            raise ValueError(f"Decimal places 0-4: {self.decimal_places}")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.currency_code}|{self.currency_name}|{self.symbol}|{self.decimal_places}|{self.stability.value}|{self.is_active}|{self.country_code}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "currency_code": self.currency_code,
                "is_active": self.is_active,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "currency_code": self.currency_code,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> CurrencyDefinition:
        return self

    def update(self, updated_by: str, **kwargs) -> CurrencyDefinition:
        new_cur = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_cur, key) and key not in ("currency_code", "created_at", "version"):
                setattr(new_cur, key, value)
        new_cur.version = self.version + 1
        new_cur._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_cur

    def delete(self, deleted_by: str, reason: str | None = None) -> CurrencyDefinition:
        new_cur = self._copy()
        new_cur.deleted_at = datetime.now(UTC)
        new_cur.deleted_by = deleted_by
        new_cur.is_active = False
        new_cur.version = self.version + 1
        new_cur._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_cur

    def restore(self, restored_by: str) -> CurrencyDefinition:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_cur = self._copy()
        new_cur.deleted_at = None
        new_cur.deleted_by = None
        new_cur.is_active = True
        new_cur.version = self.version + 1
        new_cur._record_audit("RESTORE", restored_by, {})
        return new_cur

    def activate(self, activated_by: str) -> CurrencyDefinition:
        if self.is_active:
            return self
        new_cur = self._copy()
        new_cur.is_active = True
        new_cur.version = self.version + 1
        new_cur._record_audit("ACTIVATE", activated_by, {})
        return new_cur

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CurrencyDefinition:
        if not self.is_active:
            return self
        new_cur = self._copy()
        new_cur.is_active = False
        new_cur.version = self.version + 1
        new_cur._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_cur

    def lock(self, locked_by: str, reason: str) -> CurrencyDefinition:
        return self

    def unlock(self, unlocked_by: str) -> CurrencyDefinition:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "currency_code": self.currency_code,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency_code": self.currency_code,
            "currency_name": self.currency_name,
            "symbol": self.symbol,
            "decimal_places": self.decimal_places,
            "stability": self.stability.name,
            "is_active": self.is_active,
            "country_code": self.country_code,
            "created_at": self.created_at.isoformat(),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurrencyDefinition:
        return cls(
            currency_code=data["currency_code"],
            currency_name=data["currency_name"],
            symbol=data["symbol"],
            decimal_places=data["decimal_places"],
            stability=MonetaryUnitStability[data["stability"]],
            is_active=data["is_active"],
            country_code=data["country_code"],
            created_at=datetime.fromisoformat(data["created_at"]),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> CurrencyDefinition:
        return CurrencyDefinition(
            currency_code=f"{self.currency_code}_COPY",
            currency_name=f"{self.currency_name} (COPY)",
            symbol=self.symbol,
            decimal_places=self.decimal_places,
            stability=self.stability,
            is_active=False,
            country_code=self.country_code,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "currency_code": self.currency_code,
            "is_active": self.is_active,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CurrencyDefinition:
        new_cur = self._copy()
        new_cur.version = self.version + 1
        new_cur._record_audit("TOUCH", touched_by, {})
        return new_cur

    def _copy(self) -> CurrencyDefinition:
        return CurrencyDefinition(
            currency_code=self.currency_code,
            currency_name=self.currency_name,
            symbol=self.symbol,
            decimal_places=self.decimal_places,
            stability=self.stability,
            is_active=self.is_active,
            country_code=self.country_code,
            created_at=self.created_at,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class ExchangeRate:
    rate_id: UUID
    from_currency: str
    to_currency: str
    rate: Decimal
    rate_type: ExchangeRateType
    effective_date: datetime
    source: str
    created_by: str
    created_at: datetime
    expires_at: datetime | None = None
    cryptographic_hash: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.rate <= 0:
            raise ValueError(f"Rate must be positive: {self.rate}")
        if self.from_currency == self.to_currency and self.rate != Decimal(1):
            raise ValueError("Same currency rate must be 1")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.rate_id}|{self.from_currency}|{self.to_currency}|{self.rate}|{self.rate_type.value}|{self.effective_date.isoformat()}|{self.source}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "rate_id": str(self.rate_id),
                "rate": str(self.rate),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "rate_id": str(self.rate_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ExchangeRate:
        return self

    def update(self, updated_by: str, **kwargs) -> ExchangeRate:
        new_rate = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_rate, key) and key not in (
                "rate_id",
                "created_at",
                "created_by",
                "version",
            ):
                setattr(new_rate, key, value)
        new_rate.version = self.version + 1
        new_rate._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_rate

    def delete(self, deleted_by: str, reason: str | None = None) -> ExchangeRate:
        new_rate = self._copy()
        new_rate.deleted_at = datetime.now(UTC)
        new_rate.deleted_by = deleted_by
        new_rate.version = self.version + 1
        new_rate._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_rate

    def restore(self, restored_by: str) -> ExchangeRate:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_rate = self._copy()
        new_rate.deleted_at = None
        new_rate.deleted_by = None
        new_rate.version = self.version + 1
        new_rate._record_audit("RESTORE", restored_by, {})
        return new_rate

    def activate(self, activated_by: str) -> ExchangeRate:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ExchangeRate:
        return self

    def lock(self, locked_by: str, reason: str) -> ExchangeRate:
        return self

    def unlock(self, unlocked_by: str) -> ExchangeRate:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "rate_id": str(self.rate_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate_id": str(self.rate_id),
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "rate": str(self.rate),
            "rate_type": self.rate_type.name,
            "effective_date": self.effective_date.isoformat(),
            "source": self.source,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExchangeRate:
        return cls(
            rate_id=UUID(data["rate_id"]),
            from_currency=data["from_currency"],
            to_currency=data["to_currency"],
            rate=Decimal(data["rate"]),
            rate_type=ExchangeRateType[data["rate_type"]],
            effective_date=datetime.fromisoformat(data["effective_date"]),
            source=data["source"],
            created_by=data["created_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> ExchangeRate:
        new_id = uuid4()
        return ExchangeRate(
            rate_id=new_id,
            from_currency=self.from_currency,
            to_currency=self.to_currency,
            rate=self.rate,
            rate_type=self.rate_type,
            effective_date=self.effective_date,
            source=self.source,
            created_by=self.created_by,
            created_at=datetime.now(UTC),
            expires_at=self.expires_at,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "rate_id": str(self.rate_id),
            "rate": str(self.rate),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ExchangeRate:
        new_rate = self._copy()
        new_rate.version = self.version + 1
        new_rate._record_audit("TOUCH", touched_by, {})
        return new_rate

    def is_valid_on(self, date: datetime) -> bool:
        dt = date if date.tzinfo else date.replace(tzinfo=UTC)
        eff = (
            self.effective_date
            if self.effective_date.tzinfo
            else self.effective_date.replace(tzinfo=UTC)
        )
        if dt < eff:
            return False
        if self.expires_at:
            exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
            if dt > exp:
                return False
        return True

    def convert(self, amount: Decimal) -> Decimal:
        result = amount * self.rate
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def _copy(self) -> ExchangeRate:
        return ExchangeRate(
            rate_id=self.rate_id,
            from_currency=self.from_currency,
            to_currency=self.to_currency,
            rate=self.rate,
            rate_type=self.rate_type,
            effective_date=self.effective_date,
            source=self.source,
            created_by=self.created_by,
            created_at=self.created_at,
            expires_at=self.expires_at,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class MonetaryAmount:
    amount: Decimal
    currency: str
    decimal_places: int = 2
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if len(self.currency) != 3:
            raise ValueError(f"Invalid currency code: {self.currency}")
        quant = f"0.{'0' * self.decimal_places}"
        object.__setattr__(
            self, "amount", self.amount.quantize(Decimal(quant), rounding=ROUND_HALF_EVEN)
        )
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        return hashlib.sha3_256(
            f"{self.amount}|{self.currency}|{self.decimal_places}".encode()
        ).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "amount": str(self.amount),
                "currency": self.currency,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> MonetaryAmount:
        return self

    def update(self, updated_by: str, **kwargs) -> MonetaryAmount:
        raise AttributeError("MonetaryAmount is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> MonetaryAmount:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> MonetaryAmount:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> MonetaryAmount:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> MonetaryAmount:
        return self

    def lock(self, locked_by: str, reason: str) -> MonetaryAmount:
        return self

    def unlock(self, unlocked_by: str) -> MonetaryAmount:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "currency": self.currency,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": str(self.amount),
            "currency": self.currency,
            "decimal_places": self.decimal_places,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MonetaryAmount:
        return cls(
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            decimal_places=data.get("decimal_places", 2),
            version=data.get("version", 1),
        )

    def clone(self) -> MonetaryAmount:
        return MonetaryAmount(self.amount, self.currency, self.decimal_places, version=1)

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "amount": str(self.amount),
            "currency": self.currency,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> MonetaryAmount:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def __add__(self, other: object) -> MonetaryAmount:
        if not isinstance(other, MonetaryAmount):
            raise TypeError(f"Cannot add {type(other)}")
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return MonetaryAmount(self.amount + other.amount, self.currency, self.decimal_places)

    def __sub__(self, other: object) -> MonetaryAmount:
        if not isinstance(other, MonetaryAmount):
            raise TypeError(f"Cannot subtract {type(other)}")
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return MonetaryAmount(self.amount - other.amount, self.currency, self.decimal_places)

    def __mul__(self, factor: Decimal) -> MonetaryAmount:
        return MonetaryAmount(self.amount * factor, self.currency, self.decimal_places)

    def __truediv__(self, divisor: Decimal) -> MonetaryAmount:
        return MonetaryAmount(self.amount / divisor, self.currency, self.decimal_places)

    def __neg__(self) -> MonetaryAmount:
        return MonetaryAmount(-self.amount, self.currency, self.decimal_places)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MonetaryAmount):
            return False
        return self.currency == other.currency and self.amount == other.amount

    def __repr__(self) -> str:
        return f"{self.currency} {self.amount:.{self.decimal_places}f}"


@dataclass(kw_only=True)
class MonetaryUnitViolation:
    violation_id: UUID
    transaction_id: UUID
    currency_used: str
    functional_currency: str
    exchange_rate_used: Decimal | None
    required_rate_source: str
    severity: MonetaryUnitViolationSeverity
    message: str
    detected_at: datetime
    detected_by: str
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.detected_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.violation_id}|{self.transaction_id}|{self.currency_used}|{self.severity.value}|{self.message[:100]}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "violation_id": str(self.violation_id),
                "severity": self.severity.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "violation_id": str(self.violation_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> MonetaryUnitViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> MonetaryUnitViolation:
        raise AttributeError("MonetaryUnitViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> MonetaryUnitViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> MonetaryUnitViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> MonetaryUnitViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> MonetaryUnitViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> MonetaryUnitViolation:
        return self

    def unlock(self, unlocked_by: str) -> MonetaryUnitViolation:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "violation_id": str(self.violation_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "transaction_id": str(self.transaction_id),
            "currency_used": self.currency_used,
            "functional_currency": self.functional_currency,
            "exchange_rate_used": str(self.exchange_rate_used) if self.exchange_rate_used else None,
            "required_rate_source": self.required_rate_source,
            "severity": self.severity.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "detected_by": self.detected_by,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MonetaryUnitViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            transaction_id=UUID(data["transaction_id"]),
            currency_used=data["currency_used"],
            functional_currency=data["functional_currency"],
            exchange_rate_used=Decimal(data["exchange_rate_used"])
            if data.get("exchange_rate_used")
            else None,
            required_rate_source=data["required_rate_source"],
            severity=MonetaryUnitViolationSeverity[data["severity"]],
            message=data["message"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            detected_by=data["detected_by"],
            resolved=data["resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            version=data.get("version", 1),
        )

    def clone(self) -> MonetaryUnitViolation:
        new_id = uuid4()
        return MonetaryUnitViolation(
            violation_id=new_id,
            transaction_id=self.transaction_id,
            currency_used=self.currency_used,
            functional_currency=self.functional_currency,
            exchange_rate_used=self.exchange_rate_used,
            required_rate_source=self.required_rate_source,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> MonetaryUnitViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def resolve(self, by: str) -> MonetaryUnitViolation:
        if self.resolved:
            raise ValueError("Already resolved")
        new_violation = self._copy()
        new_violation.resolved = True
        new_violation.resolved_at = datetime.now(UTC)
        new_violation.resolved_by = by
        new_violation.version = self.version + 1
        new_violation._record_audit("RESOLVE", by, {})
        return new_violation

    def _copy(self) -> MonetaryUnitViolation:
        return MonetaryUnitViolation(
            violation_id=self.violation_id,
            transaction_id=self.transaction_id,
            currency_used=self.currency_used,
            functional_currency=self.functional_currency,
            exchange_rate_used=self.exchange_rate_used,
            required_rate_source=self.required_rate_source,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=self.resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# === 4. CURRENCY REGISTRY ===


class CurrencyRegistry:
    _instance: CurrencyRegistry | None = None
    _currencies: dict[str, CurrencyDefinition] = {}
    _exchange_rates: dict[tuple[str, str], list[ExchangeRate]] = {}
    _lock = threading.Lock()

    def __new__(cls) -> CurrencyRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._load_default_currencies()
        self._load_default_exchange_rates()

    def _load_default_currencies(self) -> None:
        now = datetime.now(UTC)
        defaults = [
            ("IDR", "Indonesian Rupiah", "Rp", 2, MonetaryUnitStability.STABLE, True, "ID"),
            ("USD", "US Dollar", "$", 2, MonetaryUnitStability.STABLE, True, "US"),
            ("EUR", "Euro", "€", 2, MonetaryUnitStability.STABLE, True, "EU"),
            ("JPY", "Japanese Yen", "¥", 0, MonetaryUnitStability.STABLE, True, "JP"),
            ("SGD", "Singapore Dollar", "S$", 2, MonetaryUnitStability.STABLE, True, "SG"),
            ("MYR", "Malaysian Ringgit", "RM", 2, MonetaryUnitStability.STABLE, True, "MY"),
            ("CNY", "Chinese Yuan", "¥", 2, MonetaryUnitStability.STABLE, True, "CN"),
            ("GBP", "British Pound", "£", 2, MonetaryUnitStability.STABLE, True, "GB"),
            ("AUD", "Australian Dollar", "A$", 2, MonetaryUnitStability.STABLE, True, "AU"),
            ("THB", "Thai Baht", "฿", 2, MonetaryUnitStability.STABLE, True, "TH"),
        ]
        for code, name, sym, dec, stab, active, cc in defaults:
            curr = CurrencyDefinition(
                currency_code=code,
                currency_name=name,
                symbol=sym,
                decimal_places=dec,
                stability=stab,
                is_active=active,
                country_code=cc,
                created_at=now,
            )
            self._currencies[code] = curr

    def _load_default_exchange_rates(self) -> None:
        now = datetime.now(UTC)
        rates = [
            ("USD", "IDR", Decimal("15250")),
            ("EUR", "IDR", Decimal("16500")),
            ("JPY", "IDR", Decimal("105")),
            ("SGD", "IDR", Decimal("11300")),
            ("MYR", "IDR", Decimal("3400")),
            ("CNY", "IDR", Decimal("2100")),
            ("GBP", "IDR", Decimal("19500")),
            ("AUD", "IDR", Decimal("10000")),
            ("THB", "IDR", Decimal("425")),
        ]
        for frm, to, rate_val in rates:
            rate = ExchangeRate(
                rate_id=uuid4(),
                from_currency=frm,
                to_currency=to,
                rate=rate_val,
                rate_type=ExchangeRateType.SPOT,
                effective_date=now,
                source="System",
                created_by="system",
                created_at=now,
            )
            key = (frm, to)
            if key not in self._exchange_rates:
                self._exchange_rates[key] = []
            self._exchange_rates[key].append(rate)

    def get_currency(self, currency_code: str) -> CurrencyDefinition | None:
        return self._currencies.get(currency_code.upper())

    def is_supported(self, currency_code: str) -> bool:
        return currency_code.upper() in self._currencies

    def list_supported_currencies(self, active_only: bool = True) -> list[CurrencyDefinition]:
        result = list(self._currencies.values())
        if active_only:
            result = [c for c in result if c.is_active and c.deleted_at is None]
        return result

    def get_exchange_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: datetime | None = None,
        rate_type: ExchangeRateType = ExchangeRateType.SPOT,
    ) -> ExchangeRate | None:
        frm = from_currency.upper()
        to = to_currency.upper()
        if frm == to:
            return ExchangeRate(
                rate_id=uuid4(),
                from_currency=frm,
                to_currency=to,
                rate=Decimal(1),
                rate_type=rate_type,
                effective_date=datetime(1970, 1, 1, tzinfo=UTC),
                source="System",
                created_by="system",
                created_at=datetime.now(UTC),
            )
        as_of = as_of or datetime.now(UTC)
        key = (frm, to)
        rates = self._exchange_rates.get(key, [])
        valid = [r for r in rates if r.is_valid_on(as_of) and r.rate_type == rate_type]
        if valid:
            valid.sort(key=lambda x: x.effective_date, reverse=True)
            return valid[0]
        reverse_key = (to, frm)
        rev_rates = self._exchange_rates.get(reverse_key, [])
        rev_valid = [r for r in rev_rates if r.is_valid_on(as_of) and r.rate_type == rate_type]
        if rev_valid:
            rev_valid.sort(key=lambda x: x.effective_date, reverse=True)
            r = rev_valid[0]
            return ExchangeRate(
                rate_id=uuid4(),
                from_currency=frm,
                to_currency=to,
                rate=Decimal(1) / r.rate,
                rate_type=rate_type,
                effective_date=r.effective_date,
                source=r.source,
                created_by=r.created_by,
                created_at=r.created_at,
                expires_at=r.expires_at,
            )
        return None

    def add_exchange_rate(self, rate: ExchangeRate) -> None:
        with self._lock:
            key = (rate.from_currency, rate.to_currency)
            if key not in self._exchange_rates:
                self._exchange_rates[key] = []
            self._exchange_rates[key].append(rate)

    def get_all_exchange_rates(self) -> list[ExchangeRate]:
        result = []
        for rates in self._exchange_rates.values():
            result.extend(rates)
        return result


# === 5. VALIDATOR ===


class MonetaryUnitValidator:
    @classmethod
    def validate_currency(
        cls,
        currency_code: str,
        transaction_id: UUID,
        functional_currency: str,
        require_exchange_rate: bool = True,
        exchange_rate_as_of: datetime | None = None,
        auto_correct: bool = False,
    ) -> tuple[bool, MonetaryUnitViolation | None, str | None]:
        registry = CurrencyRegistry()
        if not registry.is_supported(currency_code):
            violation = cls._create_violation(
                transaction_id,
                currency_code,
                functional_currency,
                None,
                "Currency registry",
                MonetaryUnitViolationSeverity.CRITICAL,
                f"Currency {currency_code} not supported",
                "validator",
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return False, violation, "Use supported currency or register new"
        if require_exchange_rate and currency_code != functional_currency:
            rate = registry.get_exchange_rate(
                currency_code, functional_currency, exchange_rate_as_of
            )
            if not rate:
                violation = cls._create_violation(
                    transaction_id,
                    currency_code,
                    functional_currency,
                    None,
                    f"Exchange rate as of {exchange_rate_as_of or 'today'}",
                    MonetaryUnitViolationSeverity.HIGH,
                    f"No valid rate from {currency_code} to {functional_currency}",
                    "validator",
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation, "Add exchange rate or use functional currency"
        return True, None, None

    @classmethod
    def _create_violation(
        cls,
        transaction_id: UUID,
        currency_used: str,
        functional_currency: str,
        exchange_rate_used: Decimal | None,
        required_source: str,
        severity: MonetaryUnitViolationSeverity,
        message: str,
        detected_by: str,
    ) -> MonetaryUnitViolation:
        return MonetaryUnitViolation(
            violation_id=uuid4(),
            transaction_id=transaction_id,
            currency_used=currency_used,
            functional_currency=functional_currency,
            exchange_rate_used=exchange_rate_used,
            required_rate_source=required_source,
            severity=severity,
            message=message,
            detected_at=datetime.now(UTC),
            detected_by=detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
        )

    @classmethod
    def _log_violation(cls, violation: MonetaryUnitViolation) -> None:
        log_msg = f"[{violation.severity.name}] Monetary unit violation: {violation.message}"
        if violation.severity.value >= MonetaryUnitViolationSeverity.CRITICAL.value:
            logger.critical(log_msg)
        elif violation.severity.value >= MonetaryUnitViolationSeverity.HIGH.value:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(cls, violation: MonetaryUnitViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            const_severity = {
                MonetaryUnitViolationSeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                MonetaryUnitViolationSeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                MonetaryUnitViolationSeverity.HIGH: ConstitutionalSeverity.HIGH,
                MonetaryUnitViolationSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                MonetaryUnitViolationSeverity.LOW: ConstitutionalSeverity.LOW,
            }.get(violation.severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.MONETARY_UNIT,
                offending_module="monetary_unit_validator",
                message=violation.message,
                offending_command_id=violation.transaction_id,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")


# === 6. AXIOM SERVICE ===


class MonetaryUnitAxiom:
    _instance: MonetaryUnitAxiom | None = None
    _validator = MonetaryUnitValidator
    _registry = CurrencyRegistry()
    _violation_history: list[MonetaryUnitViolation] = []
    _lock = threading.Lock()

    def __new__(cls) -> MonetaryUnitAxiom:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._violation_history = []

    # ==================== REPOSITORY METHODS ====================
    def save_violation(self, violation: MonetaryUnitViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)

    def get_violations(
        self,
        limit: int = 100,
        min_severity: MonetaryUnitViolationSeverity | None = None,
        transaction_id: UUID | None = None,
        unresolved_only: bool = False,
    ) -> list[MonetaryUnitViolation]:
        result = self._violation_history[-limit:]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if transaction_id:
            result = [v for v in result if v.transaction_id == transaction_id]
        if unresolved_only:
            result = [v for v in result if not v.resolved]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str
    ) -> MonetaryUnitViolation | None:
        with self._lock:
            for i, v in enumerate(self._violation_history):
                if v.violation_id == violation_id and not v.resolved:
                    resolved = v.resolve(resolved_by)
                    self._violation_history[i] = resolved
                    return resolved
            return None

    # ==================== BUSINESS METHODS ====================
    def is_supported(self, currency_code: str) -> bool:
        return self._registry.is_supported(currency_code)

    def get_currency_definition(self, currency_code: str) -> CurrencyDefinition | None:
        return self._registry.get_currency(currency_code)

    def get_supported_currencies(self, active_only: bool = True) -> list[CurrencyDefinition]:
        return self._registry.list_supported_currencies(active_only)

    def get_exchange_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: datetime | None = None,
        rate_type: ExchangeRateType = ExchangeRateType.SPOT,
    ) -> ExchangeRate | None:
        return self._registry.get_exchange_rate(from_currency, to_currency, as_of, rate_type)

    def add_exchange_rate(self, rate: ExchangeRate) -> None:
        self._registry.add_exchange_rate(rate)

    def convert_currency(
        self,
        amount: MonetaryAmount,
        target_currency: str,
        as_of: datetime | None = None,
        rate_type: ExchangeRateType = ExchangeRateType.SPOT,
        transaction_id: UUID | None = None,
        raise_on_error: bool = True,
    ) -> MonetaryAmount | None:
        if amount.currency == target_currency:
            return amount
        rate = self.get_exchange_rate(amount.currency, target_currency, as_of, rate_type)
        if not rate:
            if transaction_id and raise_on_error:
                violation = self._validator._create_violation(
                    transaction_id,
                    amount.currency,
                    target_currency,
                    None,
                    f"Exchange rate as of {as_of or 'today'}",
                    MonetaryUnitViolationSeverity.HIGH,
                    f"Cannot convert {amount.currency} to {target_currency}",
                    "axiom",
                )
                self.save_violation(violation)
                raise ExchangeRateNotFoundError(
                    f"No rate from {amount.currency} to {target_currency}"
                )
            return None
        converted = rate.convert(amount.amount)
        target_def = self.get_currency_definition(target_currency)
        decimals = target_def.decimal_places if target_def else 2
        return MonetaryAmount(converted, target_currency, decimals)

    def enforce_currency(
        self,
        amount: MonetaryAmount,
        functional_currency: str,
        transaction_id: UUID,
        exchange_rate_as_of: datetime | None = None,
        auto_correct: bool = True,
        raise_on_violation: bool = True,
    ) -> tuple[bool, MonetaryUnitViolation | None]:
        is_valid, violation, hint = self._validator.validate_currency(
            amount.currency,
            transaction_id,
            functional_currency,
            True,
            exchange_rate_as_of,
            auto_correct,
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= MonetaryUnitViolationSeverity.HIGH.value
            ):
                raise MonetaryUnitViolationError(
                    violation.message,
                    transaction_id,
                    amount.currency,
                    functional_currency,
                    violation.severity,
                )
        return is_valid, violation

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_currencies = len(self._registry.list_supported_currencies(active_only=False))
            active_currencies = len(self._registry.list_supported_currencies(active_only=True))
            total_rates = len(self._registry.get_all_exchange_rates())
            total_violations = len(self._violation_history)
            unresolved = len([v for v in self._violation_history if not v.resolved])
            return {
                "supported_currencies": total_currencies,
                "active_currencies": active_currencies,
                "total_exchange_rates": total_rates,
                "total_violations": total_violations,
                "unresolved_violations": unresolved,
            }

    def reset(self) -> None:
        with self._lock:
            self._violation_history = []


# === 7. SINGLETON ACCESSOR ===

_monetary_unit_axiom_instance: MonetaryUnitAxiom | None = None


def get_monetary_unit_axiom() -> MonetaryUnitAxiom:
    global _monetary_unit_axiom_instance
    if _monetary_unit_axiom_instance is None:
        _monetary_unit_axiom_instance = MonetaryUnitAxiom()
    return _monetary_unit_axiom_instance


# === 8. HELPER FUNCTIONS ===


def create_monetary_amount(
    amount: Decimal, currency: str, decimal_places: int = 2
) -> MonetaryAmount:
    return MonetaryAmount(amount, currency.upper(), decimal_places)


def create_exchange_rate(
    from_currency: str,
    to_currency: str,
    rate: Decimal,
    rate_type: ExchangeRateType = ExchangeRateType.SPOT,
    effective_date: datetime | None = None,
    source: str = "System",
    created_by: str = "system",
    expires_at: datetime | None = None,
) -> ExchangeRate:
    effective_date = effective_date or datetime.now(UTC)
    return ExchangeRate(
        rate_id=uuid4(),
        from_currency=from_currency.upper(),
        to_currency=to_currency.upper(),
        rate=rate,
        rate_type=rate_type,
        effective_date=effective_date,
        source=source,
        created_by=created_by,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    )


def register_currency(
    currency_code: str,
    currency_name: str,
    symbol: str,
    decimal_places: int,
    stability: MonetaryUnitStability,
    country_code: str,
    is_active: bool = True,
) -> CurrencyDefinition:
    registry = CurrencyRegistry()
    if registry.is_supported(currency_code):
        raise CurrencyNotSupportedError(f"Currency {currency_code} already registered")
    curr = CurrencyDefinition(
        currency_code=currency_code.upper(),
        currency_name=currency_name,
        symbol=symbol,
        decimal_places=decimal_places,
        stability=stability,
        is_active=is_active,
        country_code=country_code.upper(),
    )
    registry._currencies[curr.currency_code] = curr
    return curr


__all__ = [
    "CurrencyDefinition",
    "CurrencyNotSupportedError",
    "CurrencyRegistry",
    "CurrencyType",
    "ExchangeRate",
    "ExchangeRateNotFoundError",
    "ExchangeRateType",
    "MonetaryAmount",
    "MonetaryUnitAxiom",
    "MonetaryUnitError",
    "MonetaryUnitStability",
    "MonetaryUnitValidator",
    "MonetaryUnitViolation",
    "MonetaryUnitViolationError",
    "MonetaryUnitViolationSeverity",
    "create_exchange_rate",
    "create_monetary_amount",
    "get_monetary_unit_axiom",
    "register_currency",
]