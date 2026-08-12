#!/usr/bin/env python3
"""
Module: invariants.py
Layer: Domain / Tax Transaction
Responsibility: Invariant validation rules for tax transactions.

Metode yang ditambahkan:
- InvariantResult dengan metode entity dasar.
- TaxInvariants dengan berbagai validasi.
- TaxInvariantEnforcer dengan enforcer methods.

All datetime.now() replaced with datetime.now(UTC) for timezone awareness.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


# === 1. INVARIANT RESULT (dengan entity dasar) ===
class InvariantResult:
    def __init__(self, is_valid: bool = True, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False
        self._record_audit("ADD_ERROR", "system", {"error": error})

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def __bool__(self) -> bool:
        return self.is_valid

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"is_valid": self.is_valid, "errors": self.errors, "version": self._version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvariantResult:
        instance = cls(data.get("is_valid", True), data.get("errors", []))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> InvariantResult:
        new = InvariantResult(self.is_valid, self.errors.copy())
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InvariantResult:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

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


# === 2. TAX INVARIANTS ===
class TaxInvariants:
    @staticmethod
    def validate_faktur_date(
        faktur_date: date, current_date: date | None = None
    ) -> InvariantResult:
        if current_date is None:
            current_date = date.today()
        result = InvariantResult(True)
        if faktur_date > current_date:
            result.add_error(f"Faktur date {faktur_date} cannot be in the future")
        return result

    @staticmethod
    def validate_npwp_format(npwp: str) -> InvariantResult:
        result = InvariantResult(True)
        cleaned = npwp.replace(".", "").replace(" ", "").replace("-", "")
        if len(cleaned) != 15:
            result.add_error(f"NPWP must be 15 digits, got {len(cleaned)}")
        if not cleaned.isdigit():
            result.add_error("NPWP must contain only digits")
        return result

    @staticmethod
    def validate_nsfp_format(nsfp: str) -> InvariantResult:
        result = InvariantResult(True)
        if not nsfp.isdigit():
            result.add_error("NSFP must be numeric")
        if len(nsfp) != 16:
            result.add_error(f"NSFP must be 16 digits, got {len(nsfp)}")
        return result

    @staticmethod
    def validate_faktur_unique_number(
        faktur_number: str, existing_numbers: set[str]
    ) -> InvariantResult:
        result = InvariantResult(True)
        if faktur_number in existing_numbers:
            result.add_error(f"Faktur number {faktur_number} already exists")
        return result

    @staticmethod
    def validate_spt_period(tahun: int, bulan: int | None) -> InvariantResult:
        result = InvariantResult(True)
        if tahun < 2000 or tahun > 2100:
            result.add_error(f"Invalid tax year: {tahun}")
        if bulan is not None and (bulan < 1 or bulan > 12):
            result.add_error(f"Invalid month: {bulan}")
        return result

    @staticmethod
    def validate_tax_amount(
        dpp: Decimal, ppn: Decimal, rate: Decimal = Decimal("11.0")
    ) -> InvariantResult:
        """
        Validate tax amount with Decimal precision.

        Args:
            dpp: Dasar Pengenaan Pajak (Decimal)
            ppn: PPN amount (Decimal)
            rate: Tax rate in percentage (Decimal), default 11.0%

        Returns:
            InvariantResult with validation errors if any.
        """
        result = InvariantResult(True)
        expected_ppn = dpp * (rate / Decimal("100"))
        tolerance = Decimal("0.01")
        if abs(ppn - expected_ppn) > tolerance:
            result.add_error(
                f"PPN calculation mismatch: expected {expected_ppn:.2f}, got {ppn:.2f}"
            )
        return result


# === 3. TAX INVARIANT ENFORCER ===
class TaxInvariantEnforcer:
    def __init__(self, faktur_number_checker: Callable | None = None):
        self._faktur_number_checker = faktur_number_checker or (lambda: set())
        self._invariants = TaxInvariants()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    async def enforce_faktur_create(
        self,
        faktur_number: str,
        faktur_date: date,
        npwp_penjual: str,
        npwp_pembeli: str,
        nsfp: str,
        dpp: Decimal,
        ppn: Decimal,
    ) -> InvariantResult:
        """
        Enforce faktur creation invariants with Decimal precision.

        Args:
            faktur_number: Faktur number string.
            faktur_date: Faktur date.
            npwp_penjual: Seller NPWP.
            npwp_pembeli: Buyer NPWP.
            nsfp: NSFP number.
            dpp: Dasar Pengenaan Pajak (Decimal).
            ppn: PPN amount (Decimal).

        Returns:
            InvariantResult with validation result.
        """
        result = InvariantResult(True)
        result.merge(self._invariants.validate_faktur_date(faktur_date))
        result.merge(self._invariants.validate_npwp_format(npwp_penjual))
        result.merge(self._invariants.validate_npwp_format(npwp_pembeli))
        result.merge(self._invariants.validate_nsfp_format(nsfp))
        result.merge(self._invariants.validate_tax_amount(dpp, ppn))
        existing_numbers = await self._faktur_number_checker()
        result.merge(
            self._invariants.validate_faktur_unique_number(faktur_number, existing_numbers)
        )
        self._record_audit("ENFORCE_FAKTUR_CREATE", "system", {"faktur_number": faktur_number})
        return result

    async def enforce_spt_submit(self, tahun: int, bulan: int | None) -> InvariantResult:
        result = self._invariants.validate_spt_period(tahun, bulan)
        self._record_audit("ENFORCE_SPT_SUBMIT", "system", {"tahun": tahun, "bulan": bulan})
        return result

    def validate_faktur_date(self, faktur_date: date) -> InvariantResult:
        return self._invariants.validate_faktur_date(faktur_date)

    def validate_npwp(self, npwp: str) -> InvariantResult:
        return self._invariants.validate_npwp_format(npwp)

    def validate_nsfp(self, nsfp: str) -> InvariantResult:
        return self._invariants.validate_nsfp_format(nsfp)

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

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"version": self._version, "type": "TaxInvariantEnforcer"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaxInvariantEnforcer:
        instance = cls()
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TaxInvariantEnforcer:
        new = TaxInvariantEnforcer(self._faktur_number_checker)
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {"version": self._version, "type": "TaxInvariantEnforcer"}

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TaxInvariantEnforcer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._version = 1
        self._audit_trail = []


__all__ = [
    "InvariantResult",
    "TaxInvariantEnforcer",
    "TaxInvariants",
]
