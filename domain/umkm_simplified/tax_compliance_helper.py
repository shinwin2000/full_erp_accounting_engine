#!/usr/bin/env python3
"""
Module: tax_compliance_helper.py
Layer: Domain / UMKM Simplified
Responsibility: Bantu hitung pajak UMKM (PP 23).

Metode yang ditambahkan:
- Untuk TaxCalculationResult: validate, to_dict, from_dict, clone, snapshot,
  version, audit_trail, touch.
- Untuk TaxComplianceHelper: validate, to_dict, from_dict, clone, snapshot,
  version, audit_trail, touch, reset, get_calculation_history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from domain.umkm_simplified.simplified_journal_entity import (
    SimplifiedJournalEntity,
    TransactionType,
)

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===
class UMKMTaxRegime(Enum):
    FINAL_0_5_PERCENT = "final_0.5"
    GENERAL_RATE = "general"
    NOT_REGISTERED = "not_registered"

    def display_name(self) -> str:
        names = {
            UMKMTaxRegime.FINAL_0_5_PERCENT: "PP 23 (0.5%)",
            UMKMTaxRegime.GENERAL_RATE: "Tarif Umum",
            UMKMTaxRegime.NOT_REGISTERED: "Belum Terdaftar",
        }
        return names.get(self, self.value)


class UMKMStatus(Enum):
    MSME = "msme"
    STARTUP = "startup"
    GROWING = "growing"
    ESTABLISHED = "established"


# === 2. TAX CALCULATION RESULT (dengan entity dasar) ===
@dataclass
class TaxCalculationResult:
    period: str
    total_revenue: Decimal
    taxable_revenue: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    tax_regime: UMKMTaxRegime
    notes: str = ""

    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "period": self.period,
                "tax_amount": str(self.tax_amount),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "period": self.period,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.total_revenue < 0:
            errors.append("Total revenue cannot be negative")
        if self.taxable_revenue < 0:
            errors.append("Taxable revenue cannot be negative")
        if self.tax_rate < 0 or self.tax_rate > 100:
            errors.append("Tax rate must be between 0 and 100")
        if self.tax_amount < 0:
            errors.append("Tax amount cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "total_revenue": str(self.total_revenue),
            "taxable_revenue": str(self.taxable_revenue),
            "tax_rate": str(self.tax_rate),
            "tax_amount": str(self.tax_amount),
            "tax_regime": self.tax_regime.value,
            "notes": self.notes,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaxCalculationResult:
        instance = cls(
            period=data["period"],
            total_revenue=Decimal(data["total_revenue"]),
            taxable_revenue=Decimal(data["taxable_revenue"]),
            tax_rate=Decimal(data["tax_rate"]),
            tax_amount=Decimal(data["tax_amount"]),
            tax_regime=UMKMTaxRegime(data["tax_regime"]),
            notes=data.get("notes", ""),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TaxCalculationResult:
        new = TaxCalculationResult(
            period=self.period,
            total_revenue=self.total_revenue,
            taxable_revenue=self.taxable_revenue,
            tax_rate=self.tax_rate,
            tax_amount=self.tax_amount,
            tax_regime=self.tax_regime,
            notes=self.notes,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "period": self.period,
            "tax_amount": str(self.tax_amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TaxCalculationResult:
        new = self.clone()
        new._record_audit("TOUCH", touched_by, {})
        return new


# === 3. TAX COMPLIANCE HELPER (dengan entity dasar) ===
class TaxComplianceHelper:
    PP23_THRESHOLD = Decimal("4800000000")
    PP23_RATE = Decimal("0.5")
    GENERAL_RATE = Decimal("22")

    def __init__(self):
        self._calculation_history: list[TaxCalculationResult] = []
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "history_count": len(self._calculation_history),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ==================== BUSINESS METHODS ====================
    def calculate_monthly_tax(
        self,
        transactions: list[SimplifiedJournalEntity],
        year: int,
        month: int,
        ytd_revenue: Decimal | None = None,
        tax_regime: UMKMTaxRegime = UMKMTaxRegime.FINAL_0_5_PERCENT,
    ) -> TaxCalculationResult:
        period_start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            period_end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            period_end = datetime(year, month + 1, 1, tzinfo=UTC)

        monthly_revenue = Decimal(0)
        for trans in transactions:
            if trans.transaction_type == TransactionType.INCOME:
                if period_start <= trans.transaction_date < period_end:
                    monthly_revenue += trans.amount

        total_ytd = (ytd_revenue or Decimal(0)) + monthly_revenue

        if tax_regime == UMKMTaxRegime.FINAL_0_5_PERCENT:
            if total_ytd > self.PP23_THRESHOLD:
                effective_rate = self.GENERAL_RATE
                effective_regime = UMKMTaxRegime.GENERAL_RATE
                notes = f"Omzet YTD {total_ytd:,.0f} exceeds PP23 threshold, using general rate"
            else:
                effective_rate = self.PP23_RATE
                effective_regime = UMKMTaxRegime.FINAL_0_5_PERCENT
                notes = f"Using PP23 final rate {self.PP23_RATE}%"
        else:
            effective_rate = self.GENERAL_RATE
            effective_regime = UMKMTaxRegime.GENERAL_RATE
            notes = "Using general income tax rate"

        tax_amount = monthly_revenue * (effective_rate / Decimal(100))
        result = TaxCalculationResult(
            period=f"{year}-{month:02d}",
            total_revenue=monthly_revenue,
            taxable_revenue=monthly_revenue,
            tax_rate=effective_rate,
            tax_amount=tax_amount,
            tax_regime=effective_regime,
            notes=notes,
        )
        self._calculation_history.append(result)
        self._record_audit(
            "CALCULATE_MONTHLY_TAX",
            "system",
            {"period": f"{year}-{month:02d}", "tax_amount": str(tax_amount)},
        )
        return result

    def calculate_annual_tax(
        self, transactions: list[SimplifiedJournalEntity], year: int
    ) -> TaxCalculationResult:
        period_start = datetime(year, 1, 1, tzinfo=UTC)
        period_end = datetime(year + 1, 1, 1, tzinfo=UTC)

        annual_revenue = Decimal(0)
        for trans in transactions:
            if trans.transaction_type == TransactionType.INCOME:
                if period_start <= trans.transaction_date < period_end:
                    annual_revenue += trans.amount

        if annual_revenue <= self.PP23_THRESHOLD:
            effective_rate = self.PP23_RATE
            effective_regime = UMKMTaxRegime.FINAL_0_5_PERCENT
            notes = f"Annual revenue {annual_revenue:,.0f} within PP23 threshold"
        else:
            effective_rate = self.GENERAL_RATE
            effective_regime = UMKMTaxRegime.GENERAL_RATE
            notes = f"Annual revenue {annual_revenue:,.0f} exceeds PP23 threshold"

        tax_amount = annual_revenue * (effective_rate / Decimal(100))
        result = TaxCalculationResult(
            period=str(year),
            total_revenue=annual_revenue,
            taxable_revenue=annual_revenue,
            tax_rate=effective_rate,
            tax_amount=tax_amount,
            tax_regime=effective_regime,
            notes=notes,
        )
        self._calculation_history.append(result)
        self._record_audit(
            "CALCULATE_ANNUAL_TAX", "system", {"year": year, "tax_amount": str(tax_amount)}
        )
        return result

    def calculate_pph_final(self, monthly_revenue: Decimal, ytd_revenue: Decimal) -> dict[str, Any]:
        if ytd_revenue > self.PP23_THRESHOLD:
            return {
                "applies": False,
                "reason": f"YTD revenue {ytd_revenue:,.0f} exceeds PP23 threshold",
                "suggested_action": "Use general income tax rate",
            }
        tax_amount = monthly_revenue * (self.PP23_RATE / Decimal(100))
        return {
            "applies": True,
            "monthly_revenue": str(monthly_revenue),
            "tax_rate": str(self.PP23_RATE),
            "tax_amount": str(tax_amount),
            "ytd_revenue": str(ytd_revenue),
            "remaining_until_threshold": str(self.PP23_THRESHOLD - ytd_revenue),
        }

    def check_threshold_remaining(self, ytd_revenue: Decimal) -> dict[str, Any]:
        remaining = self.PP23_THRESHOLD - ytd_revenue
        if remaining <= 0:
            status = "EXCEEDED"
            message = "PP23 threshold exceeded. Use general income tax rate."
        elif remaining < self.PP23_THRESHOLD * Decimal("0.1"):
            status = "WARNING"
            message = f"Approaching PP23 threshold. Remaining: {remaining:,.0f}"
        else:
            status = "OK"
            message = f"Within PP23 threshold. Remaining: {remaining:,.0f}"
        return {
            "threshold": str(self.PP23_THRESHOLD),
            "current_ytd": str(ytd_revenue),
            "remaining": str(remaining),
            "status": status,
            "message": message,
        }

    def get_tax_summary(self, year: int) -> dict[str, Any]:
        calculations = [c for c in self._calculation_history if c.period.startswith(str(year))]
        if not calculations:
            return {"year": year, "has_data": False}
        total_revenue = sum(c.total_revenue for c in calculations if c.period != str(year))
        total_tax = sum(c.tax_amount for c in calculations)
        annual_calc = next((c for c in calculations if c.period == str(year)), None)
        return {
            "year": year,
            "has_data": True,
            "total_revenue": str(total_revenue),
            "total_tax": str(total_tax),
            "effective_tax_rate": str(total_tax / total_revenue * 100 if total_revenue > 0 else 0),
            "annual_summary": annual_calc.to_dict() if annual_calc else None,
            "monthly_details": [c.to_dict() for c in calculations if c.period != str(year)],
        }

    def get_calculation_history(self, limit: int = 50) -> list[TaxCalculationResult]:
        return self._calculation_history[-limit:]

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.PP23_THRESHOLD <= 0:
            errors.append("PP23_THRESHOLD must be positive")
        if self.PP23_RATE <= 0 or self.PP23_RATE >= 100:
            errors.append("PP23_RATE must be between 0 and 100")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "pp23_threshold": str(self.PP23_THRESHOLD),
            "pp23_rate": str(self.PP23_RATE),
            "general_rate": str(self.GENERAL_RATE),
            "history_count": len(self._calculation_history),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaxComplianceHelper:
        helper = cls()
        helper._version = data.get("version", 1)
        # History cannot be restored from dict
        return helper

    def clone(self) -> TaxComplianceHelper:
        new = TaxComplianceHelper()
        new._calculation_history = [c.clone() for c in self._calculation_history]
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "history_count": len(self._calculation_history),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TaxComplianceHelper:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._calculation_history = []
        self._version += 1
        self._audit_trail = []
        self._snapshots = []


# === 4. EXPORTS ===
__all__ = [
    "TaxCalculationResult",
    "TaxComplianceHelper",
    "UMKMStatus",
    "UMKMTaxRegime",
]
