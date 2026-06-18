#!/usr/bin/env python3
"""
Module: bad_debt_provision_engine.py
Layer: Domain / Subledger AR
Responsibility: Perhitungan penyisihan piutang tak tertagih.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_provision_summary(), calculate_provision_by_bucket(), set_rate(), set_method()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from domain.subledger_ar.aging_bucket_vo import AgingBucket, AgingCalculator
from domain.subledger_ar.invoice_entity import InvoiceEntity, InvoiceStatus

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===
class ProvisionMethod(Enum):
    AGING_PERCENTAGE = "aging_percentage"
    PERCENTAGE_OF_SALES = "percentage_sales"
    INDIVIDUAL_ASSESSMENT = "individual"
    HYBRID = "hybrid"


class ProvisionCategory(Enum):
    SPECIFIC = "specific"
    GENERAL = "general"
    PORTFOLIO = "portfolio"


@dataclass
class ProvisionRate:
    bucket: AgingBucket
    rate: Decimal

    def __post_init__(self):
        if self.rate < 0 or self.rate > 100:
            raise ValueError(f"Rate must be between 0 and 100: {self.rate}")

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.rate < 0 or self.rate > 100:
            errors.append("Rate must be between 0 and 100")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {"bucket": self.bucket.value, "rate": str(self.rate)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvisionRate:
        return cls(
            bucket=AgingBucket(data["bucket"]),
            rate=Decimal(data["rate"]),
        )

    def clone(self) -> ProvisionRate:
        return ProvisionRate(bucket=self.bucket, rate=self.rate)

    def snapshot(self) -> dict[str, Any]:
        return {"bucket": self.bucket.value, "rate": str(self.rate)}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> ProvisionRate:
        return self.clone()


# === 2. DEFAULT PROVISION RATES ===
DEFAULT_PROVISION_RATES = [
    ProvisionRate(AgingBucket.CURRENT, Decimal("1")),
    ProvisionRate(AgingBucket.DAYS_1_30, Decimal("2")),
    ProvisionRate(AgingBucket.DAYS_31_60, Decimal("5")),
    ProvisionRate(AgingBucket.DAYS_61_90, Decimal("10")),
    ProvisionRate(AgingBucket.OVER_90, Decimal("25")),
]


# === 3. BAD DEBT PROVISION ENGINE ===
@dataclass
class BadDebtProvisionEngine:
    rates: list[ProvisionRate] = field(default_factory=lambda: DEFAULT_PROVISION_RATES.copy())
    method: ProvisionMethod = ProvisionMethod.AGING_PERCENTAGE
    historical_loss_rate: Decimal = Decimal("2")

    # Fields untuk entity dasar
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._version,
            "method": self.method.value,
            "historical_loss_rate": str(self.historical_loss_rate),
            "rates_count": len(self.rates),
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

    # ==================== BUSINESS METHODS (Original) ====================
    def calculate_provision(
        self, invoices: list[InvoiceEntity], as_of_date: datetime | None = None
    ) -> Decimal:
        if self.method == ProvisionMethod.AGING_PERCENTAGE:
            return self._calculate_by_aging(invoices, as_of_date)
        elif self.method == ProvisionMethod.INDIVIDUAL_ASSESSMENT:
            return self._calculate_individual(invoices, as_of_date)
        elif self.method == ProvisionMethod.HYBRID:
            return self._calculate_hybrid(invoices, as_of_date)
        else:
            return self._calculate_by_percentage(invoices, as_of_date)

    def _calculate_by_aging(
        self, invoices: list[InvoiceEntity], as_of_date: datetime | None = None
    ) -> Decimal:
        if as_of_date is None:
            as_of_date = datetime.now(UTC)
        rate_map = {r.bucket: r.rate for r in self.rates}
        total_provision = Decimal(0)
        for invoice in invoices:
            if invoice.status in (InvoiceStatus.FULLY_PAID, InvoiceStatus.WRITTEN_OFF):
                continue
            bucket = AgingCalculator.calculate_bucket(invoice.due_date, as_of_date)
            rate = rate_map.get(bucket, Decimal(0))
            provision = invoice.outstanding_amount * (rate / Decimal(100))
            total_provision += provision
        return total_provision

    def _calculate_individual(
        self, invoices: list[InvoiceEntity], as_of_date: datetime | None = None
    ) -> Decimal:
        if as_of_date is None:
            as_of_date = datetime.now(UTC)
        total_provision = Decimal(0)
        for invoice in invoices:
            if invoice.status in (InvoiceStatus.FULLY_PAID, InvoiceStatus.WRITTEN_OFF):
                continue
            days_overdue = invoice.days_overdue(as_of_date)
            if days_overdue > 180:
                provision = invoice.outstanding_amount
            elif days_overdue > 90:
                provision = invoice.outstanding_amount * Decimal("0.5")
            elif days_overdue > 60:
                provision = invoice.outstanding_amount * Decimal("0.25")
            elif days_overdue > 30:
                provision = invoice.outstanding_amount * Decimal("0.1")
            else:
                provision = invoice.outstanding_amount * (self.historical_loss_rate / Decimal(100))
            total_provision += provision
        return total_provision

    def _calculate_by_percentage(
        self, invoices: list[InvoiceEntity], as_of_date: datetime | None = None
    ) -> Decimal:
        total_outstanding = sum(inv.outstanding_amount for inv in invoices)
        return total_outstanding * (self.historical_loss_rate / Decimal(100))

    def _calculate_hybrid(
        self, invoices: list[InvoiceEntity], as_of_date: datetime | None = None
    ) -> Decimal:
        if as_of_date is None:
            as_of_date = datetime.now(UTC)
        high_risk_provision = Decimal(0)
        aging_provision = Decimal(0)
        rate_map = {r.bucket: r.rate for r in self.rates}
        for invoice in invoices:
            if invoice.status in (InvoiceStatus.FULLY_PAID, InvoiceStatus.WRITTEN_OFF):
                continue
            if invoice.days_overdue(as_of_date) > 90 or invoice.amount > Decimal("1000000000"):
                provision = invoice.outstanding_amount * Decimal("0.5")
                high_risk_provision += provision
            else:
                bucket = AgingCalculator.calculate_bucket(invoice.due_date, as_of_date)
                rate = rate_map.get(bucket, Decimal(0))
                provision = invoice.outstanding_amount * (rate / Decimal(100))
                aging_provision += provision
        return high_risk_provision + aging_provision

    def calculate_provision_by_bucket(
        self, invoices: list[InvoiceEntity], as_of_date: datetime | None = None
    ) -> dict[AgingBucket, Decimal]:
        if as_of_date is None:
            as_of_date = datetime.now(UTC)
        rate_map = {r.bucket: r.rate for r in self.rates}
        provisions = {bucket: Decimal(0) for bucket in AgingBucket}
        for invoice in invoices:
            if invoice.status in (InvoiceStatus.FULLY_PAID, InvoiceStatus.WRITTEN_OFF):
                continue
            bucket = AgingCalculator.calculate_bucket(invoice.due_date, as_of_date)
            rate = rate_map.get(bucket, Decimal(0))
            provision = invoice.outstanding_amount * (rate / Decimal(100))
            provisions[bucket] = provisions.get(bucket, Decimal(0)) + provision
        return provisions

    def get_provision_summary(
        self, invoices: list[InvoiceEntity], as_of_date: datetime | None = None
    ) -> dict[str, Any]:
        if as_of_date is None:
            as_of_date = datetime.now(UTC)
        total_outstanding = sum(inv.outstanding_amount for inv in invoices)
        total_provision = self.calculate_provision(invoices, as_of_date)
        provisions_by_bucket = self.calculate_provision_by_bucket(invoices, as_of_date)
        return {
            "as_of_date": as_of_date.isoformat(),
            "method": self.method.value,
            "total_outstanding": str(total_outstanding),
            "total_provision": str(total_provision),
            "coverage_ratio": str(
                total_provision / total_outstanding * 100 if total_outstanding > 0 else 0
            ),
            "provisions_by_bucket": {
                bucket.value: str(amount) for bucket, amount in provisions_by_bucket.items()
            },
            "historical_loss_rate": str(self.historical_loss_rate),
        }

    def set_rate(self, bucket: AgingBucket, rate: Decimal) -> None:
        for i, r in enumerate(self.rates):
            if r.bucket == bucket:
                self.rates[i] = ProvisionRate(bucket, rate)
                self._record_audit(
                    "SET_RATE", "system", {"bucket": bucket.value, "rate": str(rate)}
                )
                return
        self.rates.append(ProvisionRate(bucket, rate))
        logger.info(f"Provision rate for {bucket.value} set to {rate}%")

    def set_method(self, method: ProvisionMethod) -> None:
        self.method = method
        self._record_audit("SET_METHOD", "system", {"method": method.value})
        logger.info(f"Provision method set to {method.value}")

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.historical_loss_rate < 0 or self.historical_loss_rate > 100:
            errors.append("historical_loss_rate must be between 0 and 100")
        for r in self.rates:
            res = r.validate()
            if not res["is_valid"]:
                errors.extend([f"Rate for {r.bucket.value}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "historical_loss_rate": str(self.historical_loss_rate),
            "rates": [r.to_dict() for r in self.rates],
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BadDebtProvisionEngine:
        rates = [ProvisionRate.from_dict(r) for r in data.get("rates", [])]
        instance = cls(
            rates=rates,
            method=ProvisionMethod(data.get("method", "aging_percentage")),
            historical_loss_rate=Decimal(data.get("historical_loss_rate", "2")),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> BadDebtProvisionEngine:
        new_rates = [r.clone() for r in self.rates]
        new = BadDebtProvisionEngine(
            rates=new_rates,
            method=self.method,
            historical_loss_rate=self.historical_loss_rate,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "method": self.method.value,
            "historical_loss_rate": str(self.historical_loss_rate),
            "rates_count": len(self.rates),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BadDebtProvisionEngine:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. EXPORTS ===
__all__ = [
    "DEFAULT_PROVISION_RATES",
    "BadDebtProvisionEngine",
    "ProvisionCategory",
    "ProvisionMethod",
    "ProvisionRate",
]
