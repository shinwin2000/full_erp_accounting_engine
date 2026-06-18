#!/usr/bin/env python3
"""
Package: domain.reality
Layer: 5 - Reality, Intent, Causality / Reality

Responsibility: Mencerminkan realitas ekonomi dunia nyata: economic events,
               hak keuangan (entitlements), kewajiban keuangan (obligations),
               validasi keberadaan aset, dan pemetaan ke akuntansi.

Dependencies:
    - domain.shared_value_objects
    - kernel.context_holder
    - ports (untuk repository)

Audit: Setiap economic event dan pemetaannya dictat.
"""

from __future__ import annotations

__version__ = "1.0.0"


# Lazy imports untuk menghindari circular import
def __getattr__(name):
    # asset_existence_validator
    if name == "AssetExistenceStatus":
        from domain.reality.asset_existence_validator import AssetExistenceStatus

        return AssetExistenceStatus
    if name == "VerificationMethod":
        from domain.reality.asset_existence_validator import VerificationMethod

        return VerificationMethod
    if name == "AssetExistenceRecord":
        from domain.reality.asset_existence_validator import AssetExistenceRecord

        return AssetExistenceRecord
    if name == "AssetExistenceValidator":
        from domain.reality.asset_existence_validator import AssetExistenceValidator

        return AssetExistenceValidator
    if name == "get_asset_existence_validator":
        from domain.reality.asset_existence_validator import get_asset_existence_validator

        return get_asset_existence_validator

    # economic_event_immutable
    if name == "EconomicEventType":
        from domain.reality.economic_event_immutable import EconomicEventType

        return EconomicEventType
    if name == "EconomicEventStatus":
        from domain.reality.economic_event_immutable import EconomicEventStatus

        return EconomicEventStatus
    if name == "EconomicEvent":
        from domain.reality.economic_event_immutable import EconomicEvent

        return EconomicEvent
    if name == "EconomicEventService":
        from domain.reality.economic_event_immutable import EconomicEventService

        return EconomicEventService
    if name == "get_economic_event_service":
        from domain.reality.economic_event_immutable import get_economic_event_service

        return get_economic_event_service

    # effective_date_vo
    if name == "EffectiveDateType":
        from domain.reality.effective_date_vo import EffectiveDateType

        return EffectiveDateType
    if name == "EffectiveDateConstraint":
        from domain.reality.effective_date_vo import EffectiveDateConstraint

        return EffectiveDateConstraint
    if name == "EffectiveDate":
        from domain.reality.effective_date_vo import EffectiveDate

        return EffectiveDate
    if name == "EffectiveDateFactory":
        from domain.reality.effective_date_vo import EffectiveDateFactory

        return EffectiveDateFactory

    # financial_entitlement
    if name == "EntitlementType":
        from domain.reality.financial_entitlement import EntitlementType

        return EntitlementType
    if name == "EntitlementStatus":
        from domain.reality.financial_entitlement import EntitlementStatus

        return EntitlementStatus
    if name == "CollectionRisk":
        from domain.reality.financial_entitlement import CollectionRisk

        return CollectionRisk
    if name == "FinancialEntitlement":
        from domain.reality.financial_entitlement import FinancialEntitlement

        return FinancialEntitlement
    if name == "FinancialEntitlementService":
        from domain.reality.financial_entitlement import FinancialEntitlementService

        return FinancialEntitlementService
    if name == "get_financial_entitlement_service":
        from domain.reality.financial_entitlement import get_financial_entitlement_service

        return get_financial_entitlement_service

    # financial_obligation
    if name == "ObligationType":
        from domain.reality.financial_obligation import ObligationType

        return ObligationType
    if name == "ObligationStatus":
        from domain.reality.financial_obligation import ObligationStatus

        return ObligationStatus
    if name == "PaymentSchedule":
        from domain.reality.financial_obligation import PaymentSchedule

        return PaymentSchedule
    if name == "FinancialObligation":
        from domain.reality.financial_obligation import FinancialObligation

        return FinancialObligation
    if name == "FinancialObligationService":
        from domain.reality.financial_obligation import FinancialObligationService

        return FinancialObligationService
    if name == "get_financial_obligation_service":
        from domain.reality.financial_obligation import get_financial_obligation_service

        return get_financial_obligation_service

    # reality_exceptions
    if name == "RealityErrorCode":
        from domain.reality.reality_exceptions import RealityErrorCode

        return RealityErrorCode
    if name == "RealitySeverity":
        from domain.reality.reality_exceptions import RealitySeverity

        return RealitySeverity
    if name == "RealityError":
        from domain.reality.reality_exceptions import RealityError

        return RealityError
    if name == "EconomicEventNotFoundError":
        from domain.reality.reality_exceptions import EconomicEventNotFoundError

        return EconomicEventNotFoundError
    if name == "EconomicEventInvalidStatusError":
        from domain.reality.reality_exceptions import EconomicEventInvalidStatusError

        return EconomicEventInvalidStatusError
    if name == "EventAlreadyMappedError":
        from domain.reality.reality_exceptions import EventAlreadyMappedError

        return EventAlreadyMappedError
    if name == "ValidationFailedError":
        from domain.reality.reality_exceptions import ValidationFailedError

        return ValidationFailedError
    if name == "MappingNotFoundError":
        from domain.reality.reality_exceptions import MappingNotFoundError

        return MappingNotFoundError
    if name == "AccountNotFoundError":
        from domain.reality.reality_exceptions import AccountNotFoundError

        return AccountNotFoundError
    if name == "AssetNotFoundError":
        from domain.reality.reality_exceptions import AssetNotFoundError

        return AssetNotFoundError
    if name == "AssetVerificationFailedError":
        from domain.reality.reality_exceptions import AssetVerificationFailedError

        return AssetVerificationFailedError
    if name == "AssetDuplicateError":
        from domain.reality.reality_exceptions import AssetDuplicateError

        return AssetDuplicateError
    if name == "PaymentExceedsBalanceError":
        from domain.reality.reality_exceptions import PaymentExceedsBalanceError

        return PaymentExceedsBalanceError
    if name == "CollectionExceedsBalanceError":
        from domain.reality.reality_exceptions import CollectionExceedsBalanceError

        return CollectionExceedsBalanceError
    if name == "RealityExceptionFactory":
        from domain.reality.reality_exceptions import RealityExceptionFactory

        return RealityExceptionFactory

    # reality_to_accounting_mapper
    if name == "AccountingMapping":
        from domain.reality.reality_to_accounting_mapper import AccountingMapping

        return AccountingMapping
    if name == "RealityToAccountingMapper":
        from domain.reality.reality_to_accounting_mapper import RealityToAccountingMapper

        return RealityToAccountingMapper
    if name == "get_reality_to_accounting_mapper":
        from domain.reality.reality_to_accounting_mapper import get_reality_to_accounting_mapper

        return get_reality_to_accounting_mapper

    # reality_validation_service
    if name == "ValidationSeverity":
        from domain.reality.reality_validation_service import ValidationSeverity

        return ValidationSeverity
    if name == "ValidationIssue":
        from domain.reality.reality_validation_service import ValidationIssue

        return ValidationIssue
    if name == "ValidationResult":
        from domain.reality.reality_validation_service import ValidationResult

        return ValidationResult
    if name == "RealityValidationService":
        from domain.reality.reality_validation_service import RealityValidationService

        return RealityValidationService
    if name == "get_reality_validation_service":
        from domain.reality.reality_validation_service import get_reality_validation_service

        return get_reality_validation_service

    raise AttributeError(f"module {__name__} has no attribute {name}")


__all__ = [
    # Asset Existence Validator
    "AssetExistenceStatus",
    "VerificationMethod",
    "AssetExistenceRecord",
    "AssetExistenceValidator",
    "get_asset_existence_validator",
    # Economic Event
    "EconomicEventType",
    "EconomicEventStatus",
    "EconomicEvent",
    "EconomicEventService",
    "get_economic_event_service",
    # Effective Date
    "EffectiveDateType",
    "EffectiveDateConstraint",
    "EffectiveDate",
    "EffectiveDateFactory",
    # Financial Entitlement
    "EntitlementType",
    "EntitlementStatus",
    "CollectionRisk",
    "FinancialEntitlement",
    "FinancialEntitlementService",
    "get_financial_entitlement_service",
    # Financial Obligation
    "ObligationType",
    "ObligationStatus",
    "PaymentSchedule",
    "FinancialObligation",
    "FinancialObligationService",
    "get_financial_obligation_service",
    # Exceptions
    "RealityErrorCode",
    "RealitySeverity",
    "RealityError",
    "EconomicEventNotFoundError",
    "EconomicEventInvalidStatusError",
    "EventAlreadyMappedError",
    "ValidationFailedError",
    "MappingNotFoundError",
    "AccountNotFoundError",
    "AssetNotFoundError",
    "AssetVerificationFailedError",
    "AssetDuplicateError",
    "PaymentExceedsBalanceError",
    "CollectionExceedsBalanceError",
    "RealityExceptionFactory",
    # Mapper
    "AccountingMapping",
    "RealityToAccountingMapper",
    "get_reality_to_accounting_mapper",
    # Validation Service
    "ValidationSeverity",
    "ValidationIssue",
    "ValidationResult",
    "RealityValidationService",
    "get_reality_validation_service",
    "__version__",
]
