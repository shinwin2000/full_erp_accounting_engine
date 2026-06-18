#!/usr/bin/env python3
"""
Package: kernel.guards
Layer: 4 - Kernel / Guards

Responsibility: Pre-condition guards yang dieksekusi sebelum command
               melewati kernel gate. Guard memeriksa kondisi-kondisi
               spesifik seperti ketersediaan saldo, periode tutup,
               validasi mata uang, otorisasi, dll.

Dependencies:
    - constitution
    - axioms
    - kernel.kernel_exceptions

Audit: Setiap pelanggaran guard dictat.
"""

from __future__ import annotations

__version__ = "1.0.0"


# Lazy imports untuk menghindari circular import
def __getattr__(name):
    if name == "GuardException" or name == "GuardViolationError":
        from kernel.guards.guard_exceptions import GuardException, GuardViolationError

        return GuardException if name == "GuardException" else GuardViolationError
    if name == "BalanceChecker":
        from kernel.guards.balance_checker import BalanceChecker

        return BalanceChecker
    if name == "get_balance_checker":
        from kernel.guards.balance_checker import get_balance_checker

        return get_balance_checker
    if name == "PeriodLockGuard":
        from kernel.guards.period_lock import PeriodLockGuard

        return PeriodLockGuard
    if name == "get_period_lock_guard":
        from kernel.guards.period_lock import get_period_lock_guard

        return get_period_lock_guard
    if name == "CurrencyValidator":
        from kernel.guards.currency_validator import CurrencyValidator

        return CurrencyValidator
    if name == "get_currency_validator":
        from kernel.guards.currency_validator import get_currency_validator

        return get_currency_validator
    if name == "LegalEntityBoundaryGuard":
        from kernel.guards.legal_entity_boundary import LegalEntityBoundaryGuard

        return LegalEntityBoundaryGuard
    if name == "get_legal_entity_boundary_guard":
        from kernel.guards.legal_entity_boundary import get_legal_entity_boundary_guard

        return get_legal_entity_boundary_guard
    if name == "AuthorityMatrixGuard":
        from kernel.guards.authority_matrix import AuthorityMatrixGuard

        return AuthorityMatrixGuard
    if name == "get_authority_matrix_guard":
        from kernel.guards.authority_matrix import get_authority_matrix_guard

        return get_authority_matrix_guard
    if name == "EvidenceAttacher":
        from kernel.guards.evidence_attacher import EvidenceAttacher

        return EvidenceAttacher
    if name == "get_evidence_attacher":
        from kernel.guards.evidence_attacher import get_evidence_attacher

        return get_evidence_attacher
    if name == "RegulatoryComplianceGuard":
        from kernel.guards.regulatory_compliance import RegulatoryComplianceGuard

        return RegulatoryComplianceGuard
    if name == "get_regulatory_compliance_guard":
        from kernel.guards.regulatory_compliance import get_regulatory_compliance_guard

        return get_regulatory_compliance_guard
    if name == "TemporalConsistencyGuard":
        from kernel.guards.temporal_consistency import TemporalConsistencyGuard

        return TemporalConsistencyGuard
    if name == "get_temporal_consistency_guard":
        from kernel.guards.temporal_consistency import get_temporal_consistency_guard

        return get_temporal_consistency_guard
    if name == "EmergencyFreezeGuard":
        from kernel.guards.emergency_freeze import EmergencyFreezeGuard

        return EmergencyFreezeGuard
    if name == "get_emergency_freeze_guard":
        from kernel.guards.emergency_freeze import get_emergency_freeze_guard

        return get_emergency_freeze_guard
    if name == "CoretaxFormatValidator":
        from kernel.guards.coretax_format_validator import CoretaxFormatValidator

        return CoretaxFormatValidator
    if name == "get_coretax_format_validator":
        from kernel.guards.coretax_format_validator import get_coretax_format_validator

        return get_coretax_format_validator
    if name == "SodEnforcer":
        from kernel.guards.sod_enforcer import SodEnforcer

        return SodEnforcer
    if name == "get_sod_enforcer":
        from kernel.guards.sod_enforcer import get_sod_enforcer

        return get_sod_enforcer
    if name == "BudgetAvailabilityGuard":
        from kernel.guards.budget_availability import BudgetAvailabilityGuard

        return BudgetAvailabilityGuard
    if name == "get_budget_availability_guard":
        from kernel.guards.budget_availability import get_budget_availability_guard

        return get_budget_availability_guard
    if name == "CreditLimitEnforcer":
        from kernel.guards.credit_limit_enforcer import CreditLimitEnforcer

        return CreditLimitEnforcer
    if name == "get_credit_limit_enforcer":
        from kernel.guards.credit_limit_enforcer import get_credit_limit_enforcer

        return get_credit_limit_enforcer
    raise AttributeError(f"module {__name__} has no attribute {name}")


__all__ = [
    "AuthorityMatrixGuard",
    "BalanceChecker",
    "BudgetAvailabilityGuard",
    "CoretaxFormatValidator",
    "CreditLimitEnforcer",
    "CurrencyValidator",
    "EmergencyFreezeGuard",
    "EvidenceAttacher",
    "GuardException",
    "GuardViolationError",
    "LegalEntityBoundaryGuard",
    "PeriodLockGuard",
    "RegulatoryComplianceGuard",
    "SodEnforcer",
    "TemporalConsistencyGuard",
    "__version__",
    "get_authority_matrix_guard",
    "get_balance_checker",
    "get_budget_availability_guard",
    "get_coretax_format_validator",
    "get_credit_limit_enforcer",
    "get_currency_validator",
    "get_emergency_freeze_guard",
    "get_evidence_attacher",
    "get_legal_entity_boundary_guard",
    "get_period_lock_guard",
    "get_regulatory_compliance_guard",
    "get_sod_enforcer",
    "get_temporal_consistency_guard",
]
