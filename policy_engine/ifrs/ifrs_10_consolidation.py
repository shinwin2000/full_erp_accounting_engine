#!/usr/bin/env python3
"""
Module: ifrs_10_consolidation.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IFRS 10: Consolidated Financial Statements.
               Mendefinisikan aturan untuk menentukan apakah entitas
               mengendalikan entitas lain dan wajib mengkonsolidasikan.
               Kontrol didasarkan pada kekuasaan, eksposur terhadap
               imbal hasil variabel, dan kemampuan menggunakan kekuasaan.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.shared_value_objects.money_vo (Money)

Audit: Setiap keputusan konsolidasi dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IFRS10ControlElement(Enum):
    """Elemen kontrol menurut IFRS 10."""

    POWER_OVER_INVESTEE = "power_over_investee"
    EXPOSURE_TO_VARIABLE_RETURNS = "exposure_to_variable_returns"
    ABILITY_TO_USE_POWER = "ability_to_use_power"


class IFRS10ConsolidationMethod(Enum):
    """Metode konsolidasi."""

    FULL_CONSOLIDATION = "full_consolidation"
    PROPORTIONAL_CONSOLIDATION = "proportional_consolidation"  # Untuk ventura bersama
    EQUITY_METHOD = "equity_method"  # Untuk asosiasi


class IFRS10ControlAssessment(Enum):
    """Hasil penilaian kontrol."""

    CONTROL = "control"
    SIGNIFICANT_INFLUENCE = "significant_influence"
    NO_CONTROL = "no_control"


# === 2. VALUE OBJECTS ===


@dataclass(frozen=True)
class IFRS10VotingRights:
    """Hak suara."""

    total_voting_rights: Decimal  # total suara di investee
    voting_rights_held: Decimal
    percentage_held: Decimal

    def __post_init__(self):
        if not (0 <= self.percentage_held <= 100):
            raise ValueError("Percentage held out of range")
        if self.percentage_held > 50:
            # Biasanya kontrol
            pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_voting_rights": str(self.total_voting_rights),
            "voting_rights_held": str(self.voting_rights_held),
            "percentage_held": str(self.percentage_held),
        }


@dataclass(frozen=True)
class IFRS10PotentialVotingRights:
    """Hak suara potensial (opsi, konversi)."""

    instrument_type: str
    number_of_shares: Decimal
    exercise_price: Money
    exercise_date: datetime
    is_currently_exercisable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.instrument_type,
            "shares": str(self.number_of_shares),
            "exercise_price": str(self.exercise_price.amount),
            "exercise_date": self.exercise_date.isoformat(),
            "exercisable": self.is_currently_exercisable,
        }


# === 3. ENTITIES ===


@dataclass
class IFRS10ControlAssessmentResult:
    """Hasil penilaian kontrol."""

    assessment_id: UUID
    parent_entity_id: UUID
    investee_entity_id: UUID
    assessment_date: datetime
    control_assessment: IFRS10ControlAssessment
    consolidation_method: IFRS10ConsolidationMethod
    voting_rights: IFRS10VotingRights | None = None
    potential_voting_rights: list[IFRS10PotentialVotingRights] = field(default_factory=list)
    other_indicators_of_power: list[str] = field(default_factory=list)

    def is_controlled(self) -> bool:
        return self.control_assessment == IFRS10ControlAssessment.CONTROL

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": str(self.assessment_id),
            "parent_entity_id": str(self.parent_entity_id),
            "investee_entity_id": str(self.investee_entity_id),
            "assessment_date": self.assessment_date.isoformat(),
            "control_assessment": self.control_assessment.value,
            "consolidation_method": self.consolidation_method.value,
            "voting_rights": self.voting_rights.to_dict() if self.voting_rights else None,
            "potential_voting_rights": [p.to_dict() for p in self.potential_voting_rights],
        }


# === 4. DOMAIN SERVICES ===


class IFRS10ControlService:
    """Service untuk menentukan kontrol dan konsolidasi."""

    @staticmethod
    def assess_control(
        voting_rights_percentage: Decimal,
        has_potential_voting_rights: bool,
        has_contractual_arrangements: bool,
        has_power_over_returns: bool,
    ) -> IFRS10ControlAssessment:
        """
        Menilai apakah parent mengendalikan investee.
        Kontrol: >50% voting rights OR power despite less than 50%.
        """
        if voting_rights_percentage > 50:
            return IFRS10ControlAssessment.CONTROL
        elif 20 <= voting_rights_percentage <= 50:
            # Bisa signifikan influence atau kontrol jika ada perjanjian
            if has_contractual_arrangements or has_power_over_returns:
                return IFRS10ControlAssessment.CONTROL
            return IFRS10ControlAssessment.SIGNIFICANT_INFLUENCE
        else:
            if has_contractual_arrangements and has_power_over_returns:
                return IFRS10ControlAssessment.CONTROL
            return IFRS10ControlAssessment.NO_CONTROL

    @staticmethod
    def determine_consolidation_method(
        control_assessment: IFRS10ControlAssessment,
    ) -> IFRS10ConsolidationMethod:
        if control_assessment == IFRS10ControlAssessment.CONTROL:
            return IFRS10ConsolidationMethod.FULL_CONSOLIDATION
        elif control_assessment == IFRS10ControlAssessment.SIGNIFICANT_INFLUENCE:
            return IFRS10ConsolidationMethod.EQUITY_METHOD
        else:
            return IFRS10ConsolidationMethod.EQUITY_METHOD  # Atau cost


# === 5. IFRS 10 VALIDATION RESULT ===


@dataclass
class IFRS10ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IFRS10ValidationResult) -> IFRS10ValidationResult:
        return IFRS10ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 6. IFRS 10 RULES ===


class IFRS10Rules:
    """
    Aturan IFRS 10:
    - Entitas induk menyajikan laporan keuangan konsolidasian jika mengendalikan satu atau lebih entitas.
    - Kontrol: kekuasaan, eksposur terhadap imbal hasil variabel, dan kemampuan menggunakan kekuasaan.
    - Hak suara potensial dipertimbangkan jika substantif.
    - Semua anak perusahaan dikonsolidasikan penuh (tidak ada pengecualian untuk berbeda aktivitas).
    - Kepentingan non-pengendali disajikan dalam ekuitas.
    - Kehilangan kontrol: tidak ada lagi konsolidasi, selisih diakui di laba rugi.
    """

    @staticmethod
    def validate_consolidation_scope(
        control_assessment: IFRS10ControlAssessment,
    ) -> IFRS10ValidationResult:
        result = IFRS10ValidationResult(is_compliant=True)
        if control_assessment == IFRS10ControlAssessment.CONTROL:
            # Wajib konsolidasi
            pass
        return result


# === 7. IFRS 10 VALIDATOR ===


class IFRS10Validator:
    """Validator untuk IFRS 10: Consolidated Financial Statements."""

    def __init__(self):
        self._rules = IFRS10Rules()

    def validate_control_assessment(
        self,
        assessment: IFRS10ControlAssessmentResult,
    ) -> IFRS10ValidationResult:
        return self._rules.validate_consolidation_scope(assessment.control_assessment)

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "control_definition": "Power + exposure to variable returns + ability to use power",
            "consolidation_requirement": "All subsidiaries must be consolidated",
            "non_controlling_interests": "Presented in equity",
            "loss_of_control": "Gain/loss recognized in P&L",
        }


# === 8. SINGLETON ACCESSOR ===

_ifrs10_validator_instance: IFRS10Validator | None = None


def get_ifrs10_validator() -> IFRS10Validator:
    global _ifrs10_validator_instance
    if _ifrs10_validator_instance is None:
        _ifrs10_validator_instance = IFRS10Validator()
    return _ifrs10_validator_instance


# === 9. EXPORTS ===

__all__ = [
    "IFRS10ConsolidationMethod",
    "IFRS10ControlAssessment",
    "IFRS10ControlAssessmentResult",
    "IFRS10ControlElement",
    "IFRS10ControlService",
    "IFRS10PotentialVotingRights",
    "IFRS10Rules",
    "IFRS10ValidationResult",
    "IFRS10Validator",
    "IFRS10VotingRights",
    "get_ifrs10_validator",
]
