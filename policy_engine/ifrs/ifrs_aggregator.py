#!/usr/bin/env python3
"""
Module: ifrs_aggregator.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: Menggabungkan semua aturan IFRS untuk evaluasi.
               Menyediakan antarmuka terpusat untuk mengakses semua
               validator IFRS dan mengevaluasi kepatuhan secara keseluruhan.

Dependencies:
- standard library (logging, dataclass, typing)
- policy_engine.ifrs.ifrs_15_revenue (IFRS15Validator)
- policy_engine.ifrs.ifrs_16_leases (IFRS16Validator)
- policy_engine.ifrs.ifrs_9_financial_instruments (IFRS9Validator)

Audit: Setiap evaluasi kepatuhan IFRS dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from policy_engine.ifrs.ifrs_9_financial_instruments import get_ifrs9_validator
from policy_engine.ifrs.ifrs_15_revenue import get_ifrs15_validator
from policy_engine.ifrs.ifrs_16_leases import get_ifrs16_validator

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IFRSStandard(Enum):
    """Standar IFRS yang tersedia."""

    IFRS_9 = "IFRS 9"
    IFRS_15 = "IFRS 15"
    IFRS_16 = "IFRS 16"


class IFRSComplianceLevel(Enum):
    """Tingkat kepatuhan IFRS."""

    FULLY_COMPLIANT = "fully_compliant"
    SUBSTANTIALLY_COMPLIANT = "substantially_compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"


# === 2. IFRS COMPLIANCE REPORT ===


@dataclass
class IFRSComplianceReport:
    """Laporan kepatuhan IFRS."""

    report_id: str
    entity_id: UUID
    entity_name: str
    reporting_period: str
    assessed_at: datetime
    overall_compliance: IFRSComplianceLevel
    standards_assessed: list[IFRSStandard]
    results: dict[str, Any]
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_period": self.reporting_period,
            "assessed_at": self.assessed_at.isoformat(),
            "overall_compliance": self.overall_compliance.value,
            "standards_assessed": [s.value for s in self.standards_assessed],
            "recommendations": self.recommendations,
        }


# === 3. IFRS AGGREGATOR ===


class IFRSAggregator:
    """
    Aggregator untuk semua validator IFRS.

    Business context: Menyediakan antarmuka terpusat untuk mengevaluasi
    kepatuhan laporan keuangan terhadap standar IFRS.

    Design pattern: Singleton with lazy initialization.
    """

    _instance: IFRSAggregator | None = None

    def __new__(cls) -> IFRSAggregator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # Initialize all validators
        self._ifrs9 = get_ifrs9_validator()
        self._ifrs15 = get_ifrs15_validator()
        self._ifrs16 = get_ifrs16_validator()

        self._validators = {
            IFRSStandard.IFRS_9: self._ifrs9,
            IFRSStandard.IFRS_15: self._ifrs15,
            IFRSStandard.IFRS_16: self._ifrs16,
        }

    def get_validator(self, standard: IFRSStandard):
        """Mendapatkan validator untuk standar IFRS tertentu."""
        return self._validators.get(standard)

    def get_all_validators(self) -> dict[IFRSStandard, Any]:
        """Mendapatkan semua validator."""
        return self._validators.copy()

    def get_requirements_summary(self) -> dict[str, Any]:
        """Mendapatkan ringkasan persyaratan semua standar IFRS."""
        return {
            "IFRS_9": self._ifrs9.get_requirements_summary(),
            "IFRS_15": self._ifrs15.get_requirements_summary(),
            "IFRS_16": self._ifrs16.get_requirements_summary(),
        }

    def assess_compliance(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_period: str,
        standards: list[IFRSStandard] | None = None,
        **kwargs,
    ) -> IFRSComplianceReport:
        """
        Menilai kepatuhan terhadap standar IFRS.

        Args:
            entity_id: ID entitas
            entity_name: Nama entitas
            reporting_period: Periode pelaporan
            standards: Daftar standar yang dinilai (default: semua)
            **kwargs: Parameter untuk masing-masing validator

        Returns:
            IFRSComplianceReport
        """
        if standards is None:
            standards = list(IFRSStandard)

        results = {}
        has_error = False
        has_warning = False
        recommendations = []

        for standard in standards:
            validator = self._validators.get(standard)
            if not validator:
                continue

            if standard == IFRSStandard.IFRS_9:
                # IFRS 9 assessment
                result = self._assess_ifrs9(kwargs)
            elif standard == IFRSStandard.IFRS_15:
                result = self._assess_ifrs15(kwargs)
            elif standard == IFRSStandard.IFRS_16:
                result = self._assess_ifrs16(kwargs)
            else:
                continue

            results[standard.value] = result

            if hasattr(result, "errors") and result.errors:
                has_error = True
                recommendations.append(f"{standard.value}: {', '.join(result.errors[:3])}")
            elif hasattr(result, "warnings") and result.warnings:
                has_warning = True
                recommendations.append(f"{standard.value}: {', '.join(result.warnings[:2])}")

        # Determine overall compliance level
        if has_error:
            overall = IFRSComplianceLevel.NON_COMPLIANT
        elif has_warning:
            overall = IFRSComplianceLevel.PARTIALLY_COMPLIANT
        else:
            overall = IFRSComplianceLevel.FULLY_COMPLIANT

        return IFRSComplianceReport(
            report_id=f"IFRS_COMP_{int(datetime.now(UTC).timestamp())}",
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_period=reporting_period,
            assessed_at=datetime.now(UTC),
            overall_compliance=overall,
            standards_assessed=standards,
            results=results,
            recommendations=recommendations,
        )

    def _assess_ifrs9(self, kwargs: dict) -> Any:
        """Menilai kepatuhan IFRS 9."""
        hedge = kwargs.get("hedging_relationship")
        if hedge:
            return self._ifrs9.validate_hedge_effectiveness(hedge)
        # Return a simple compliance result
        from policy_engine.psak.psak_71_financial_instruments_ifrs9 import PSAK71ValidationResult

        return PSAK71ValidationResult(is_compliant=True)

    def _assess_ifrs15(self, kwargs: dict) -> Any:
        """Menilai kepatuhan IFRS 15."""
        contract = kwargs.get("contract")
        if contract:
            return self._ifrs15.validate_contract_compliance(contract)
        from policy_engine.psak.psak_72_revenue import PSAK72ValidationResult

        return PSAK72ValidationResult(is_compliant=True)

    def _assess_ifrs16(self, kwargs: dict) -> Any:
        """Menilai kepatuhan IFRS 16."""
        lease = kwargs.get("lease")
        fair_value = kwargs.get("fair_value")
        if lease:
            return self._ifrs16.validate_lease_compliance(lease, fair_value)
        from policy_engine.psak.psak_73_leases import PSAK73ValidationResult

        return PSAK73ValidationResult(is_compliant=True)

    def get_supported_standards(self) -> list[str]:
        """Mendapatkan daftar standar IFRS yang didukung."""
        return [s.value for s in IFRSStandard]

    def reset(self) -> None:
        """Reset aggregator (untuk testing)."""
        self._ifrs9 = get_ifrs9_validator()
        self._ifrs15 = get_ifrs15_validator()
        self._ifrs16 = get_ifrs16_validator()
        self._validators = {
            IFRSStandard.IFRS_9: self._ifrs9,
            IFRSStandard.IFRS_15: self._ifrs15,
            IFRSStandard.IFRS_16: self._ifrs16,
        }


# === 4. SINGLETON ACCESSOR ===

_ifrs_aggregator_instance: IFRSAggregator | None = None


def get_ifrs_aggregator() -> IFRSAggregator:
    """Mendapatkan instance singleton IFRSAggregator."""
    global _ifrs_aggregator_instance
    if _ifrs_aggregator_instance is None:
        _ifrs_aggregator_instance = IFRSAggregator()
    return _ifrs_aggregator_instance


# === 5. EXPORTS ===

__all__ = [
    "IFRSAggregator",
    "IFRSComplianceLevel",
    "IFRSComplianceReport",
    "IFRSStandard",
    "get_ifrs_aggregator",
]
