#!/usr/bin/env python3
"""
Module: tax_exceptions.py
Layer: 7 - Policy Engine & Standards / Tax Indonesia
Responsibility: Exception terkait perpajakan Indonesia.
               Mendefinisikan hierarchy exception untuk semua error yang
               terjadi di layer perpajakan, termasuk kesalahan perhitungan,
               tarif tidak valid, dan kepatuhan.

Dependencies:
- standard library (enum, typing)

Audit: Setiap exception perpajakan dictat.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

# === 1. CONSTANTS & ENUMS ===


class TaxErrorCode(Enum):
    """Kode error untuk perpajakan."""

    # PPN errors
    PPN_TARIFF_NOT_FOUND = auto()
    PPN_CALCULATION_ERROR = auto()
    PPN_INVALID_DPP = auto()
    PPN_CREDIT_NOT_ALLOWED = auto()

    # PPh errors
    PPH_TARIFF_NOT_FOUND = auto()
    PPH_CALCULATION_ERROR = auto()
    PPH_PTKP_INVALID = auto()
    PPH_TAX_BRACKET_ERROR = auto()
    PPH_WITHHOLDING_ERROR = auto()

    # NPWP errors
    NPWP_INVALID = auto()
    NPWP_NOT_FOUND = auto()
    NPWP_VERIFICATION_FAILED = auto()

    # Compliance errors
    TAX_RETURN_LATE = auto()
    TAX_PAYMENT_LATE = auto()
    TAX_UNDERPAYMENT = auto()
    TAX_CORRECTION_REQUIRED = auto()

    # Rate registry errors
    RATE_NOT_FOUND = auto()
    RATE_EXPIRED = auto()
    RATE_INVALID = auto()

    # General
    TAX_NOT_CALCULABLE = auto()
    TAX_DATA_INCOMPLETE = auto()
    TAX_REGULATION_CHANGED = auto()


class TaxSeverity(Enum):
    """Severity untuk tax error."""

    CRITICAL = 80  # Error fatal, transaksi ditolak
    HIGH = 60  # Error serius, perlu koreksi
    MEDIUM = 40  # Error yang dapat direcovery
    LOW = 20  # Warning
    INFO = 0  # Informasi


# === 2. BASE EXCEPTION ===


class TaxError(Exception):
    """
    Base exception untuk semua error di layer perpajakan.

    Business context: Exception yang terjadi di layer perpajakan
    harus mewarisi kelas ini untuk konsistensi handling.
    """

    def __init__(
        self,
        message: str,
        error_code: TaxErrorCode,
        severity: TaxSeverity = TaxSeverity.MEDIUM,
        component: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        self.error_code = error_code
        self.severity = severity
        self.component = component
        self.details = details or {}
        self.cause = cause

        full_message = f"[{severity.name}][{error_code.name}] {message}"
        if component:
            full_message = f"[{component}] {full_message}"
        super().__init__(full_message)
        self._original_message = message

    @property
    def original_message(self) -> str:
        return self._original_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "error_code": self.error_code.name,
            "severity": self.severity.name,
            "message": self._original_message,
            "component": self.component,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }

    def is_critical(self) -> bool:
        return self.severity == TaxSeverity.CRITICAL


# === 3. CONCRETE EXCEPTIONS ===


class PPNTariffNotFoundError(TaxError):
    """Tarif PPN tidak ditemukan untuk periode tertentu."""

    def __init__(self, effective_date: str, **kwargs):
        super().__init__(
            message=f"PPN tariff not found for effective date: {effective_date}",
            error_code=TaxErrorCode.PPN_TARIFF_NOT_FOUND,
            severity=TaxSeverity.HIGH,
            component="ppn_calculator",
            details={"effective_date": effective_date},
            **kwargs,
        )
        self.effective_date = effective_date


class PPNCalculationError(TaxError):
    """Error dalam perhitungan PPN."""

    def __init__(self, dpp: str, tariff: str, reason: str, **kwargs):
        super().__init__(
            message=f"PPN calculation error for DPP {dpp} with tariff {tariff}: {reason}",
            error_code=TaxErrorCode.PPN_CALCULATION_ERROR,
            severity=TaxSeverity.HIGH,
            component="ppn_calculator",
            details={"dpp": dpp, "tariff": tariff, "reason": reason},
            **kwargs,
        )
        self.dpp = dpp


class PPhTariffNotFoundError(TaxError):
    """Tarif PPh tidak ditemukan."""

    def __init__(self, pph_type: str, year: int, **kwargs):
        super().__init__(
            message=f"PPh {pph_type} tariff not found for year {year}",
            error_code=TaxErrorCode.PPH_TARIFF_NOT_FOUND,
            severity=TaxSeverity.HIGH,
            component="pph_calculator",
            details={"pph_type": pph_type, "year": year},
            **kwargs,
        )
        self.pph_type = pph_type


class PPhPTKPInvalidError(TaxError):
    """Status PTKP tidak valid."""

    def __init__(self, ptkp_status: str, **kwargs):
        super().__init__(
            message=f"Invalid PTKP status: {ptkp_status}",
            error_code=TaxErrorCode.PPH_PTKP_INVALID,
            severity=TaxSeverity.MEDIUM,
            component="pph_calculator",
            details={"ptkp_status": ptkp_status},
            **kwargs,
        )
        self.ptkp_status = ptkp_status


class NPWPInvalidError(TaxError):
    """NPWP tidak valid."""

    def __init__(self, npwp: str, reason: str, **kwargs):
        super().__init__(
            message=f"Invalid NPWP {npwp}: {reason}",
            error_code=TaxErrorCode.NPWP_INVALID,
            severity=TaxSeverity.HIGH,
            component="tax_validator",
            details={"npwp": npwp, "reason": reason},
            **kwargs,
        )
        self.npwp = npwp


class TaxReturnLateError(TaxError):
    """SPT dilaporkan terlambat."""

    def __init__(self, due_date: str, filing_date: str, days_late: int, **kwargs):
        super().__init__(
            message=f"Tax return filed {days_late} days late. Due: {due_date}, Filed: {filing_date}",
            error_code=TaxErrorCode.TAX_RETURN_LATE,
            severity=TaxSeverity.MEDIUM,
            component="compliance",
            details={"due_date": due_date, "filing_date": filing_date, "days_late": days_late},
            **kwargs,
        )
        self.due_date = due_date


class TaxUnderpaymentError(TaxError):
    """Kekurangan pembayaran pajak."""

    def __init__(self, tax_type: str, underpayment: str, **kwargs):
        super().__init__(
            message=f"Tax underpayment detected for {tax_type}: {underpayment}",
            error_code=TaxErrorCode.TAX_UNDERPAYMENT,
            severity=TaxSeverity.HIGH,
            component="compliance",
            details={"tax_type": tax_type, "underpayment": underpayment},
            **kwargs,
        )
        self.tax_type = tax_type


class RateNotFoundError(TaxError):
    """Tarif pajak tidak ditemukan dalam registry."""

    def __init__(self, tax_type: str, effective_date: str, **kwargs):
        super().__init__(
            message=f"Rate not found for {tax_type} effective {effective_date}",
            error_code=TaxErrorCode.RATE_NOT_FOUND,
            severity=TaxSeverity.CRITICAL,
            component="rate_registry",
            details={"tax_type": tax_type, "effective_date": effective_date},
            **kwargs,
        )
        self.tax_type = tax_type


class RateExpiredError(TaxError):
    """Tarif pajak sudah kadaluarsa."""

    def __init__(self, rate_id: str, expiry_date: str, **kwargs):
        super().__init__(
            message=f"Tax rate {rate_id} expired on {expiry_date}",
            error_code=TaxErrorCode.RATE_EXPIRED,
            severity=TaxSeverity.HIGH,
            component="rate_registry",
            details={"rate_id": rate_id, "expiry_date": expiry_date},
            **kwargs,
        )
        self.rate_id = rate_id


class TaxDataIncompleteError(TaxError):
    """Data untuk perhitungan pajak tidak lengkap."""

    def __init__(self, missing_fields: list, **kwargs):
        super().__init__(
            message=f"Tax calculation data incomplete. Missing: {', '.join(missing_fields)}",
            error_code=TaxErrorCode.TAX_DATA_INCOMPLETE,
            severity=TaxSeverity.HIGH,
            component="tax_calculator",
            details={"missing_fields": missing_fields},
            **kwargs,
        )
        self.missing_fields = missing_fields


class TaxRegulationChangedError(TaxError):
    """Regulasi perpajakan berubah."""

    def __init__(self, regulation: str, effective_date: str, **kwargs):
        super().__init__(
            message=f"Tax regulation {regulation} changed effective {effective_date}",
            error_code=TaxErrorCode.TAX_REGULATION_CHANGED,
            severity=TaxSeverity.MEDIUM,
            component="compliance",
            details={"regulation": regulation, "effective_date": effective_date},
            **kwargs,
        )
        self.regulation = regulation


# === 4. EXCEPTION FACTORY ===


class TaxExceptionFactory:
    """
    Factory untuk membuat tax exceptions dengan konsistensi.
    """

    @staticmethod
    def ppn_tariff_not_found(effective_date: str, **kwargs) -> PPNTariffNotFoundError:
        return PPNTariffNotFoundError(effective_date=effective_date, **kwargs)

    @staticmethod
    def ppn_calculation_error(dpp: str, tariff: str, reason: str, **kwargs) -> PPNCalculationError:
        return PPNCalculationError(dpp=dpp, tariff=tariff, reason=reason, **kwargs)

    @staticmethod
    def pph_tariff_not_found(pph_type: str, year: int, **kwargs) -> PPhTariffNotFoundError:
        return PPhTariffNotFoundError(pph_type=pph_type, year=year, **kwargs)

    @staticmethod
    def npwp_invalid(npwp: str, reason: str, **kwargs) -> NPWPInvalidError:
        return NPWPInvalidError(npwp=npwp, reason=reason, **kwargs)

    @staticmethod
    def tax_return_late(
        due_date: str, filing_date: str, days_late: int, **kwargs
    ) -> TaxReturnLateError:
        return TaxReturnLateError(
            due_date=due_date, filing_date=filing_date, days_late=days_late, **kwargs
        )

    @staticmethod
    def tax_underpayment(tax_type: str, underpayment: str, **kwargs) -> TaxUnderpaymentError:
        return TaxUnderpaymentError(tax_type=tax_type, underpayment=underpayment, **kwargs)

    @staticmethod
    def rate_not_found(tax_type: str, effective_date: str, **kwargs) -> RateNotFoundError:
        return RateNotFoundError(tax_type=tax_type, effective_date=effective_date, **kwargs)

    @staticmethod
    def data_incomplete(missing_fields: list, **kwargs) -> TaxDataIncompleteError:
        return TaxDataIncompleteError(missing_fields=missing_fields, **kwargs)


# === 5. EXPORTS ===

__all__ = [
    "NPWPInvalidError",
    "PPNCalculationError",
    "PPNTariffNotFoundError",
    "PPhPTKPInvalidError",
    "PPhTariffNotFoundError",
    "RateExpiredError",
    "RateNotFoundError",
    "TaxDataIncompleteError",
    "TaxError",
    "TaxErrorCode",
    "TaxExceptionFactory",
    "TaxRegulationChangedError",
    "TaxReturnLateError",
    "TaxSeverity",
    "TaxUnderpaymentError",
]
