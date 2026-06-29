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

import importlib
import logging
from typing import Any

__version__ = "1.0.0"

_logger = logging.getLogger(__name__)

# Mapping nama atribut ke (module_path, attribute_name)
_LAZY_MAP = {
    "GuardException": ("kernel.guards.guard_exceptions", "GuardException"),
    "GuardViolationError": ("kernel.guards.guard_exceptions", "GuardViolationError"),
    "BalanceChecker": ("kernel.guards.balance_checker", "BalanceChecker"),
    "get_balance_checker": ("kernel.guards.balance_checker", "get_balance_checker"),
    "PeriodLockGuard": ("kernel.guards.period_lock", "PeriodLockGuard"),
    "get_period_lock_guard": ("kernel.guards.period_lock", "get_period_lock_guard"),
    "CurrencyValidator": ("kernel.guards.currency_validator", "CurrencyValidator"),
    "get_currency_validator": ("kernel.guards.currency_validator", "get_currency_validator"),
    "LegalEntityBoundaryGuard": ("kernel.guards.legal_entity_boundary", "LegalEntityBoundaryGuard"),
    "get_legal_entity_boundary_guard": ("kernel.guards.legal_entity_boundary", "get_legal_entity_boundary_guard"),
    "AuthorityMatrixGuard": ("kernel.guards.authority_matrix", "AuthorityMatrixGuard"),
    "get_authority_matrix_guard": ("kernel.guards.authority_matrix", "get_authority_matrix_guard"),
    "EvidenceAttacher": ("kernel.guards.evidence_attacher", "EvidenceAttacher"),
    "get_evidence_attacher": ("kernel.guards.evidence_attacher", "get_evidence_attacher"),
    "RegulatoryComplianceGuard": ("kernel.guards.regulatory_compliance", "RegulatoryComplianceGuard"),
    "get_regulatory_compliance_guard": ("kernel.guards.regulatory_compliance", "get_regulatory_compliance_guard"),
    "TemporalConsistencyGuard": ("kernel.guards.temporal_consistency", "TemporalConsistencyGuard"),
    "get_temporal_consistency_guard": ("kernel.guards.temporal_consistency", "get_temporal_consistency_guard"),
    "EmergencyFreezeGuard": ("kernel.guards.emergency_freeze", "EmergencyFreezeGuard"),
    "get_emergency_freeze_guard": ("kernel.guards.emergency_freeze", "get_emergency_freeze_guard"),
    "CoretaxFormatValidator": ("kernel.guards.coretax_format_validator", "CoretaxFormatValidator"),
    "get_coretax_format_validator": ("kernel.guards.coretax_format_validator", "get_coretax_format_validator"),
    "SodEnforcer": ("kernel.guards.sod_enforcer", "SodEnforcer"),
    "get_sod_enforcer": ("kernel.guards.sod_enforcer", "get_sod_enforcer"),
    "BudgetAvailabilityGuard": ("kernel.guards.budget_availability", "BudgetAvailabilityGuard"),
    "get_budget_availability_guard": ("kernel.guards.budget_availability", "get_budget_availability_guard"),
    "CreditLimitEnforcer": ("kernel.guards.credit_limit_enforcer", "CreditLimitEnforcer"),
    "get_credit_limit_enforcer": ("kernel.guards.credit_limit_enforcer", "get_credit_limit_enforcer"),
}

_cache = {}


def __getattr__(name: str) -> Any:
    """Lazy import guard modules using importlib."""
    if name in _cache:
        return _cache[name]
    if name not in _LAZY_MAP:
        raise AttributeError(f"module {__name__} has no attribute {name}")

    module_path, attr_name = _LAZY_MAP[name]
    try:
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        _cache[name] = value
        return value
    except (ImportError, AttributeError) as e:
        _logger.error(f"Failed to lazy-import {module_path}.{attr_name}: {e}")
        raise AttributeError(f"module {__name__} has no attribute {name}") from e


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