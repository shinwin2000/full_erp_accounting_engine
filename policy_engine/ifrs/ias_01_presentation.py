#!/usr/bin/env python3
"""
Module: ias_01_presentation.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IAS 1: Presentation of Financial Statements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from domain.coa.account_entity import AccountType

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IAS1FinancialStatementComponent(Enum):
    STATEMENT_OF_FINANCIAL_POSITION = "statement_of_financial_position"
    STATEMENT_OF_PROFIT_OR_LOSS = "statement_of_profit_or_loss"
    STATEMENT_OF_OTHER_COMPREHENSIVE_INCOME = "statement_of_other_comprehensive_income"
    STATEMENT_OF_CHANGES_IN_EQUITY = "statement_of_changes_in_equity"
    STATEMENT_OF_CASH_FLOWS = "statement_of_cash_flows"
    NOTES = "notes"


class IAS1PresentationFormat(Enum):
    CLASSIFIED = "classified"
    UNCLASSIFIED = "unclassified"


# Alias untuk kompatibilitas
IAS1PresentationStandard = IAS1FinancialStatementComponent


class IAS1ComplianceLevel(Enum):
    FULL = "full"
    SUBSTANTIAL = "substantial"
    PARTIAL = "partial"
    NON_COMPLIANT = "non_compliant"


# === 2. VALUE OBJECTS ===


@dataclass(frozen=True)
class GoingConcernAssessment:
    is_going_concern_appropriate: bool
    has_material_uncertainty: bool
    disclosure_provided: bool
    assessment_date: datetime
    key_assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_going_concern_appropriate": self.is_going_concern_appropriate,
            "has_material_uncertainty": self.has_material_uncertainty,
            "disclosure_provided": self.disclosure_provided,
            "assessment_date": self.assessment_date.isoformat(),
            "key_assumptions": self.key_assumptions,
        }


# === 3. ENTITIES ===


@dataclass
class IAS1FinancialStatementSet:
    statement_id: UUID
    entity_id: UUID
    reporting_date: datetime
    components_present: list[IAS1FinancialStatementComponent]
    going_concern: GoingConcernAssessment
    presentation_currency: str
    comparative_periods: int
    is_consolidated: bool = False
    parent_entity_id: UUID | None = None

    def __post_init__(self):
        if self.comparative_periods < 1:
            raise ValueError("At least one comparative period required")
        if len(self.presentation_currency) != 3:
            raise ValueError("Invalid presentation currency")

    def missing_components(self) -> list[IAS1FinancialStatementComponent]:
        required = [
            IAS1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
            IAS1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
            IAS1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY,
            IAS1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS,
            IAS1FinancialStatementComponent.NOTES,
        ]
        return [c for c in required if c not in self.components_present]

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement_id": str(self.statement_id),
            "entity_id": str(self.entity_id),
            "reporting_date": self.reporting_date.isoformat(),
            "components_present": [c.value for c in self.components_present],
            "missing_components": [c.value for c in self.missing_components()],
            "going_concern": self.going_concern.to_dict(),
            "presentation_currency": self.presentation_currency,
            "comparative_periods": self.comparative_periods,
            "is_consolidated": self.is_consolidated,
        }


# === 4. DOMAIN SERVICES ===


class IAS1PresentationService:
    @staticmethod
    def validate_completeness(statement_set: IAS1FinancialStatementSet) -> list[str]:
        missing = statement_set.missing_components()
        return [f"Missing component: {c.value}" for c in missing]

    @staticmethod
    def validate_going_concern_disclosure(assessment: GoingConcernAssessment) -> list[str]:
        errors = []
        if assessment.has_material_uncertainty and not assessment.disclosure_provided:
            errors.append("Material uncertainty about going concern must be disclosed")
        return errors

    @staticmethod
    def validate_comparative_info(current_data: bool, prior_data: bool) -> list[str]:
        if current_data and not prior_data:
            return ["Comparative information for prior period not presented"]
        return []

    @staticmethod
    def validate_consistency(current_policies: dict, prior_policies: dict) -> list[str]:
        errors = []
        for key in current_policies:
            if key in prior_policies and current_policies[key] != prior_policies[key]:
                errors.append(
                    f"Change in accounting policy: {key} - must be applied retrospectively"
                )
        return errors


# === 5. IAS 1 VALIDATION RESULT ===


@dataclass
class IAS1ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    compliance_level: IAS1ComplianceLevel = IAS1ComplianceLevel.FULL

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False
        self.compliance_level = IAS1ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == IAS1ComplianceLevel.FULL:
            self.compliance_level = IAS1ComplianceLevel.SUBSTANTIAL

    def merge(self, other: IAS1ValidationResult) -> IAS1ValidationResult:
        new_compliance = self.compliance_level
        if other.compliance_level.value > new_compliance.value:
            new_compliance = other.compliance_level
        return IAS1ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
            compliance_level=new_compliance,
        )


# === 6. IAS 1 RULES ===


class IAS1Rules:
    REQUIRED_COMPONENTS = [
        IAS1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
        IAS1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
        IAS1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY,
        IAS1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS,
        IAS1FinancialStatementComponent.NOTES,
    ]

    @staticmethod
    def assess_going_concern(
        has_net_loss_for_three_years: bool,
        has_debt_default: bool,
        has_negative_operating_cash_flow: bool,
    ) -> GoingConcernAssessment:
        has_uncertainty = any(
            [has_net_loss_for_three_years, has_debt_default, has_negative_operating_cash_flow]
        )
        is_appropriate = not has_uncertainty
        disclosure = not has_uncertainty
        return GoingConcernAssessment(
            is_going_concern_appropriate=is_appropriate,
            has_material_uncertainty=has_uncertainty,
            disclosure_provided=disclosure,
            assessment_date=datetime.now(UTC),
        )

    @staticmethod
    def validate_balance_sheet_classification(
        accounts: list[dict], format_type: IAS1PresentationFormat
    ) -> list[str]:
        errors = []
        if format_type == IAS1PresentationFormat.CLASSIFIED:
            current_assets = [a for a in accounts if a.get("is_current", False)]
            non_current_assets = [
                a
                for a in accounts
                if not a.get("is_current", True) and a.get("account_type") == AccountType.ASSET
            ]
            if not current_assets and non_current_assets:
                errors.append("Current assets not presented under classified balance sheet")
        return errors


# === 7. IAS 1 VALIDATOR ===


class IAS1Validator:
    def __init__(self):
        self._rules = IAS1Rules()

    def validate_financial_statements(
        self,
        statement_set: IAS1FinancialStatementSet,
        balance_sheet_accounts: list[dict],
        presentation_format: IAS1PresentationFormat = IAS1PresentationFormat.CLASSIFIED,
        current_period_data_available: bool = True,
        prior_period_data_available: bool = True,
    ) -> IAS1ValidationResult:
        result = IAS1ValidationResult(is_compliant=True)

        # 1. Completeness
        for err in IAS1PresentationService.validate_completeness(statement_set):
            result.add_error(err)

        # 2. Going concern
        for err in IAS1PresentationService.validate_going_concern_disclosure(
            statement_set.going_concern
        ):
            result.add_error(err)

        # 3. Comparative info
        for err in IAS1PresentationService.validate_comparative_info(
            current_period_data_available, prior_period_data_available
        ):
            result.add_error(err)

        # 4. Balance sheet classification
        for err in self._rules.validate_balance_sheet_classification(
            balance_sheet_accounts, presentation_format
        ):
            result.add_warning(err)

        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "required_components": [c.value for c in self._rules.REQUIRED_COMPONENTS],
            "presentation_formats": [f.value for f in IAS1PresentationFormat],
            "going_concern": "Management must assess ability to continue",
            "comparative_info": "At least one prior period",
        }


# === 8. SINGLETON ACCESSOR ===

_ias1_validator_instance: IAS1Validator | None = None


def get_ias1_validator() -> IAS1Validator:
    global _ias1_validator_instance
    if _ias1_validator_instance is None:
        _ias1_validator_instance = IAS1Validator()
    return _ias1_validator_instance


# === 9. EXPORTS ===

__all__ = [
    "GoingConcernAssessment",
    "IAS1ComplianceLevel",
    "IAS1FinancialStatementComponent",
    "IAS1FinancialStatementSet",
    "IAS1PresentationFormat",
    "IAS1PresentationService",
    "IAS1PresentationStandard",  # alias
    "IAS1Rules",
    "IAS1ValidationResult",
    "IAS1Validator",
    "get_ias1_validator",
]
