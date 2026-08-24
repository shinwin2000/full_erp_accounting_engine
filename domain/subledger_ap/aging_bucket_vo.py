#!/usr/bin/env python3
"""
Module: aging_bucket_vo.py
Layer: 6 - Domain / Subledger AP
Responsibility: Pengelompokan umur hutang (1-30, 31-60, >90 hari).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


class AgingBucket(Enum):
    CURRENT = "current"
    DAYS_1_30 = "1_30_days"
    DAYS_31_60 = "31_60_days"
    DAYS_61_90 = "61_90_days"
    OVER_90 = "over_90_days"

    @classmethod
    def from_string(cls, value: str) -> AgingBucket:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.CURRENT

    def get_days_range(self) -> tuple[int, int]:
        ranges = {
            AgingBucket.CURRENT: (0, 0),
            AgingBucket.DAYS_1_30: (1, 30),
            AgingBucket.DAYS_31_60: (31, 60),
            AgingBucket.DAYS_61_90: (61, 90),
            AgingBucket.OVER_90: (91, 999999),
        }
        return ranges.get(self, (0, 0))

    def get_display_name(self) -> str:
        names = {
            AgingBucket.CURRENT: "Current (0 days)",
            AgingBucket.DAYS_1_30: "1-30 days overdue",
            AgingBucket.DAYS_31_60: "31-60 days overdue",
            AgingBucket.DAYS_61_90: "61-90 days overdue",
            AgingBucket.OVER_90: "Over 90 days overdue",
        }
        return names.get(self, self.value)


@dataclass(frozen=True)
class AgingBucketVO:
    bucket: AgingBucket
    amount: Decimal
    currency: str = "IDR"

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative: {self.amount}")
        if len(self.currency) != 3:
            raise ValueError(f"Currency must be ISO 4217 code: {self.currency}")

    def add(self, other: AgingBucketVO) -> AgingBucketVO:
        if self.bucket != other.bucket:
            raise ValueError(
                f"Cannot add different buckets: {self.bucket.value} vs {other.bucket.value}"
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket.value,
            "bucket_display": self.bucket.get_display_name(),
            "days_range": self.bucket.get_days_range(),
            "amount": str(self.amount),
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgingBucketVO:
        return cls(
            bucket=AgingBucket.from_string(data["bucket"]),
            amount=Decimal(data["amount"]),
            currency=data.get("currency", "IDR"),
        )

    def __str__(self) -> str:
        return f"{self.bucket.get_display_name()}: {self.amount:,.2f} {self.currency}"


@dataclass
class AgingSummary:
    as_of_date: datetime
    buckets: dict[AgingBucket, AgingBucketVO]
    total_outstanding: Decimal
    currency: str = "IDR"

    def __post_init__(self) -> None:
        if self.as_of_date.tzinfo is None:
            object.__setattr__(self, "as_of_date", self.as_of_date.replace(tzinfo=UTC))
        if self.total_outstanding < 0:
            raise ValueError(f"Total outstanding cannot be negative: {self.total_outstanding}")
        if len(self.currency) != 3:
            raise ValueError(f"Currency must be ISO 4217 code: {self.currency}")

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
        if check_date.tzinfo is None:
            check_date = check_date.replace(tzinfo=UTC)

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

        return AgingSummary(
            as_of_date=self.as_of_date,
            buckets=new_buckets,
            total_outstanding=new_total,
            currency=self.currency,
        )

    def get_bucket_amount(self, bucket: AgingBucket) -> Decimal:
        return self.buckets.get(bucket, AgingBucketVO(bucket, Decimal(0), self.currency)).amount

    def get_percentage_by_bucket(self) -> dict[str, Decimal]:
        """
        Return percentage distribution per bucket as Decimal (presisi 2 desimal).
        Bukan nilai moneter, tetapi untuk presisi numerik digunakan Decimal.
        """
        if self.total_outstanding == 0:
            return {k.value: Decimal("0.00") for k in self.buckets}
        result = {}
        for k, v in self.buckets.items():
            pct = (v.amount / self.total_outstanding) * Decimal("100")
            pct = pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            result[k.value] = pct
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "currency": self.currency,
            "total_outstanding": str(self.total_outstanding),
            "buckets": {k.value: v.to_dict() for k, v in self.buckets.items()},
            "percentages": {k: str(v) for k, v in self.get_percentage_by_bucket().items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgingSummary:
        buckets = {}
        for bucket_key, bucket_data in data.get("buckets", {}).items():
            bucket = AgingBucket.from_string(bucket_key)
            buckets[bucket] = AgingBucketVO.from_dict(bucket_data)
        return cls(
            as_of_date=datetime.fromisoformat(data["as_of_date"]),
            buckets=buckets,
            total_outstanding=Decimal(data["total_outstanding"]),
            currency=data.get("currency", "IDR"),
        )


class AgingCalculator:
    @staticmethod
    def calculate_bucket(due_date: datetime, as_of_date: datetime | None = None) -> AgingBucket:
        if as_of_date is None:
            as_of_date = datetime.now(UTC)
        if as_of_date.tzinfo is None:
            as_of_date = as_of_date.replace(tzinfo=UTC)
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=UTC)

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
    def calculate_days_overdue(due_date: datetime, as_of_date: datetime | None = None) -> int:
        if as_of_date is None:
            as_of_date = datetime.now(UTC)
        if as_of_date.tzinfo is None:
            as_of_date = as_of_date.replace(tzinfo=UTC)
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=UTC)

        if due_date >= as_of_date:
            return 0
        return (as_of_date - due_date).days


APAgingBucketCalculator = AgingCalculator

__all__ = [
    "APAgingBucketCalculator",
    "AgingBucket",
    "AgingBucketVO",
    "AgingCalculator",
    "AgingSummary",
]
