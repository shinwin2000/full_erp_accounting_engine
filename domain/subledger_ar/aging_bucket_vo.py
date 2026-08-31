#!/usr/bin/env python3
"""
Module: aging_bucket_vo.py
Layer: 6 - Domain / Subledger AR
Responsibility: Pengelompokan umur piutang (1-30, 31-60, >90 hari).
               Mendefinisikan value object untuk mengelompokkan piutang
               berdasarkan umur tagihan, yang digunakan untuk analisis
               kualitas piutang dan perhitungan penyisihan piutang tak tertagih.

Metode yang ditambahkan (v2):
- AgingBucket.from_string(), AgingBucket.get_display_name()
- AgingSummary.get_bucket_amount(), AgingSummary.get_percentage_by_bucket()
- Perbaikan to_dict/from_dict untuk konsistensi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# === 1. AGING BUCKET ENUM ===
class AgingBucket(Enum):
    CURRENT = "current"
    DAYS_1_30 = "1_30_days"
    DAYS_31_60 = "31_60_days"
    DAYS_61_90 = "61_90_days"
    OVER_90 = "over_90_days"

    def get_days_range(self) -> tuple[int, int | float]:
        ranges = {
            AgingBucket.CURRENT: (0, 0),
            AgingBucket.DAYS_1_30: (1, 30),
            AgingBucket.DAYS_31_60: (31, 60),
            AgingBucket.DAYS_61_90: (61, 90),
            AgingBucket.OVER_90: (91, float("inf")),
        }
        return ranges.get(self, (0, 0))

    def get_provision_rate(self, base_rate: Decimal = Decimal("0.02")) -> Decimal:
        rates = {
            AgingBucket.CURRENT: base_rate,
            AgingBucket.DAYS_1_30: base_rate * Decimal(2),
            AgingBucket.DAYS_31_60: base_rate * Decimal(5),
            AgingBucket.DAYS_61_90: base_rate * Decimal(10),
            AgingBucket.OVER_90: base_rate * Decimal(25),
        }
        return rates.get(self, base_rate)

    def get_display_name(self) -> str:
        """Return human-readable name for the bucket."""
        names = {
            AgingBucket.CURRENT: "Current",
            AgingBucket.DAYS_1_30: "1-30 Days",
            AgingBucket.DAYS_31_60: "31-60 Days",
            AgingBucket.DAYS_61_90: "61-90 Days",
            AgingBucket.OVER_90: "Over 90 Days",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> AgingBucket:
        """Create enum from string value (case-insensitive)."""
        for member in cls:
            if member.value == value.lower():
                return member
        raise ValueError(f"Invalid AgingBucket value: {value}")


# === 2. AGING BUCKET VALUE OBJECT ===
@dataclass(frozen=True)
class AgingBucketVO:
    bucket: AgingBucket
    amount: Decimal
    currency: str = "IDR"

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative: {self.amount}")

    def add(self, other: AgingBucketVO) -> AgingBucketVO:
        if self.bucket != other.bucket:
            raise ValueError(
                f"Cannot add different buckets: {self.bucket.name} vs {other.bucket.name}"
            )
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot add different currencies: {self.currency} vs {other.currency}"
            )
        return AgingBucketVO(
            bucket=self.bucket,
            amount=self.amount + other.amount,
            currency=self.currency,
        )

    def to_money(self) -> Money:
        return Money(self.amount, self.currency)

    def get_provision_rate(self) -> Decimal:
        return self.bucket.get_provision_rate()

    def get_provision_amount(self) -> Decimal:
        return self.amount * self.get_provision_rate()

    # ==================== METODA VALUE OBJECT ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.amount < 0:
            errors.append("Amount cannot be negative")
        if not self.currency:
            errors.append("Currency is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def normalize(self) -> AgingBucketVO:
        # Nothing to normalize
        return self

    def to_string(self) -> str:
        return f"{self.bucket.value}:{self.amount}:{self.currency}"

    @classmethod
    def from_string(cls, value: str) -> AgingBucketVO:
        parts = value.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid string format for AgingBucketVO: {value}")
        bucket = AgingBucket.from_string(parts[0])
        amount = Decimal(parts[1])
        currency = parts[2]
        return cls(bucket=bucket, amount=amount, currency=currency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket.value,
            "amount": str(self.amount),
            "currency": self.currency,
            "provision_rate": str(self.get_provision_rate()),
            "provision_amount": str(self.get_provision_amount()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgingBucketVO:
        return cls(
            bucket=AgingBucket.from_string(data["bucket"]),
            amount=Decimal(data["amount"]),
            currency=data.get("currency", "IDR"),
        )

    def clone(self) -> AgingBucketVO:
        return AgingBucketVO(
            bucket=self.bucket,
            amount=self.amount,
            currency=self.currency,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket.value,
            "amount": str(self.amount),
            "currency": self.currency,
        }

    def version(self) -> int:
        return 1  # VO is immutable

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> AgingBucketVO:
        return self.clone()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AgingBucketVO):
            return False
        return (
            self.bucket == other.bucket
            and self.amount == other.amount
            and self.currency == other.currency
        )

    def __hash__(self) -> int:
        return hash((self.bucket, self.amount, self.currency))


# === 3. AGING SUMMARY ===
@dataclass
class AgingSummary:
    as_of_date: datetime
    buckets: dict[AgingBucket, AgingBucketVO]
    total_outstanding: Decimal
    total_provision: Decimal
    currency: str = "IDR"

    # Fields untuk entity dasar
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._version,
            "as_of_date": self.as_of_date.isoformat(),
            "total_outstanding": str(self.total_outstanding),
            "total_provision": str(self.total_provision),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    @classmethod
    def create_empty(cls, as_of_date: datetime, currency: str = "IDR") -> AgingSummary:
        buckets = {
            AgingBucket.CURRENT: AgingBucketVO(AgingBucket.CURRENT, Decimal(0), currency),
            AgingBucket.DAYS_1_30: AgingBucketVO(AgingBucket.DAYS_1_30, Decimal(0), currency),
            AgingBucket.DAYS_31_60: AgingBucketVO(AgingBucket.DAYS_31_60, Decimal(0), currency),
            AgingBucket.DAYS_61_90: AgingBucketVO(AgingBucket.DAYS_61_90, Decimal(0), currency),
            AgingBucket.OVER_90: AgingBucketVO(AgingBucket.OVER_90, Decimal(0), currency),
        }
        return cls(
            as_of_date=as_of_date,
            buckets=buckets,
            total_outstanding=Decimal(0),
            total_provision=Decimal(0),
            currency=currency,
        )

    def add_invoice(
        self,
        invoice_date: datetime,
        due_date: datetime,
        amount: Decimal,
        currency: str,
        as_of_date: datetime | None = None,
    ) -> AgingSummary:
        if currency != self.currency:
            return self
        check_date = as_of_date or self.as_of_date
        days_overdue = 0
        if due_date < check_date:
            days_overdue = (check_date - due_date).days
        if days_overdue <= 0:
            bucket_type = AgingBucket.CURRENT
        elif days_overdue <= 30:
            bucket_type = AgingBucket.DAYS_1_30
        elif days_overdue <= 60:
            bucket_type = AgingBucket.DAYS_31_60
        elif days_overdue <= 90:
            bucket_type = AgingBucket.DAYS_61_90
        else:
            bucket_type = AgingBucket.OVER_90
        new_buckets = self.buckets.copy()
        current = new_buckets.get(bucket_type)
        if current:
            new_buckets[bucket_type] = current.add(AgingBucketVO(bucket_type, amount, currency))
        new_total = self.total_outstanding + amount
        new_provision = sum((b.get_provision_amount() for b in new_buckets.values()), Decimal("0"))
        return AgingSummary(
            as_of_date=self.as_of_date,
            buckets=new_buckets,
            total_outstanding=new_total,
            total_provision=new_provision,
            currency=self.currency,
        )

    def get_bucket_amount(self, bucket: AgingBucket) -> Decimal:
        """Return the amount in the specified bucket."""
        vo = self.buckets.get(bucket)
        return vo.amount if vo else Decimal(0)

    def get_percentage_by_bucket(self, bucket: AgingBucket) -> Decimal:
        """Return the percentage of total outstanding in this bucket."""
        if self.total_outstanding == 0:
            return Decimal(0)
        amount = self.get_bucket_amount(bucket)
        return (amount / self.total_outstanding) * Decimal(100)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "currency": self.currency,
            "total_outstanding": str(self.total_outstanding),
            "total_provision": str(self.total_provision),
            "net_receivable": str(self.total_outstanding - self.total_provision),
            "buckets": {k.value: v.to_dict() for k, v in self.buckets.items()},
            "version": self._version,
        }

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.total_outstanding < 0:
            errors.append("total_outstanding cannot be negative")
        if self.total_provision < 0:
            errors.append("total_provision cannot be negative")
        if self.total_provision > self.total_outstanding:
            errors.append("total_provision cannot exceed total_outstanding")
        for bucket, vo in self.buckets.items():
            res = vo.validate()
            if not res["is_valid"]:
                errors.extend([f"{bucket.value}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgingSummary:
        buckets = {}
        for bucket_val, bucket_data in data.get("buckets", {}).items():
            bucket = AgingBucket.from_string(bucket_val)
            buckets[bucket] = AgingBucketVO.from_dict(bucket_data)
        instance = cls(
            as_of_date=datetime.fromisoformat(data["as_of_date"]),
            buckets=buckets,
            total_outstanding=Decimal(data["total_outstanding"]),
            total_provision=Decimal(data["total_provision"]),
            currency=data.get("currency", "IDR"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> AgingSummary:
        new_buckets = {k: v.clone() for k, v in self.buckets.items()}
        new = AgingSummary(
            as_of_date=self.as_of_date,
            buckets=new_buckets,
            total_outstanding=self.total_outstanding,
            total_provision=self.total_provision,
            currency=self.currency,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "as_of_date": self.as_of_date.isoformat(),
            "total_outstanding": str(self.total_outstanding),
            "total_provision": str(self.total_provision),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AgingSummary:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. AGING CALCULATOR ===
class AgingCalculator:
    @staticmethod
    def calculate_bucket(due_date: datetime, as_of_date: datetime | None = None) -> AgingBucket:
        if as_of_date is None:
            as_of_date = datetime.now(UTC)
        if due_date >= as_of_date:
            return AgingBucket.CURRENT
        days_overdue = (as_of_date - due_date).days
        if days_overdue <= 30:
            return AgingBucket.DAYS_1_30
        elif days_overdue <= 60:
            return AgingBucket.DAYS_31_60
        elif days_overdue <= 90:
            return AgingBucket.DAYS_61_90
        else:
            return AgingBucket.OVER_90

    @staticmethod
    def calculate_provision(
        amount: Decimal, bucket: AgingBucket, base_rate: Decimal = Decimal("0.02")
    ) -> Decimal:
        rate = bucket.get_provision_rate(base_rate)
        return amount * rate

    # ==================== METODA ENTITY DASAR UNTUK KONSISTENSI ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"type": "AgingCalculator"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgingCalculator:
        return cls()

    def clone(self) -> AgingCalculator:
        return AgingCalculator()

    def snapshot(self) -> dict[str, Any]:
        return {"type": "AgingCalculator", "timestamp": datetime.now(UTC).isoformat()}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def touch(self, touched_by: str) -> AgingCalculator:
        return self


# === ALIAS UNTUK KOMPATIBILITAS ===
ARAgingBucketCalculator = AgingCalculator


# === 5. EXPORTS ===
__all__ = [
    "ARAgingBucketCalculator",
    "AgingBucket",
    "AgingBucketVO",
    "AgingCalculator",
    "AgingSummary",
]
