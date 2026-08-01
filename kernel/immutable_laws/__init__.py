#!/usr/bin/env python3
"""
Package: kernel.immutable_laws
Layer: 4 - Kernel / Immutable Laws

Responsibility: Hukum-hukum immutable yang tidak boleh dilanggar dalam sistem
               akuntansi. Hukum ini bersifat mutlak dan tidak dapat diubah
               kecuali melalui amendment protocol dengan persetujuan tertinggi.

Dependencies:
    - standard library
    - kernel.context_holder
    - kernel.immutable_laws.law_violation_exceptions

Audit: Setiap pelanggaran immutable law dictat dan dilaporkan.
"""

from __future__ import annotations

__version__ = "1.0.0"

# ============================================================================
# Direct imports from the monolithic implementation file
# ============================================================================

from .immutable_laws import (
    # Enforcers and their corresponding errors
    AssetExistenceEnforcer,
    AssetExistenceError,
    AuditTrailCompletenessEnforcer,
    AuditTrailCompletenessError,
    BaseEnforcer,
    DualApprovalEnforcer,
    DualApprovalError,
    EvidenceMandateEnforcer,
    EvidenceMandateError,
    FairValueMeasurementEnforcer,
    FairValueMeasurementError,
    GLSupremacyEnforcer,
    GLSupremacyError,
    ImmutabilityEnforcer,
    ImmutabilityError,
    NoRetroactivePolicyEnforcer,
    NoRetroactivePolicyError,
    PeriodClosureEnforcer,
    PeriodClosureError,
    ReversalConstraintEnforcer,
    ReversalConstraintError,
    SegregationOfDutiesEnforcer,
    SegregationOfDutiesError,
    TraceabilityEnforcer,
    TraceabilityError,
)

# ============================================================================
# Lazy imports for auxiliary types and getter functions
# (These are not defined in the monolithic file, but reside in separate
# submodules to keep the kernel clean.)
# ============================================================================


def __getattr__(name):
    # Asset Existence auxiliary types & getter
    if name == "AssetType":
        from kernel.immutable_laws.asset_existence_enforcer import AssetType
        return AssetType
    if name == "VerificationMethod":
        from kernel.immutable_laws.asset_existence_enforcer import VerificationMethod
        return VerificationMethod
    if name == "get_asset_existence_enforcer":
        from kernel.immutable_laws.asset_existence_enforcer import get_asset_existence_enforcer
        return get_asset_existence_enforcer

    # Audit Trail Completeness getter
    if name == "get_audit_trail_completeness_enforcer":
        from kernel.immutable_laws.audit_trail_completeness_enforcer import (
            get_audit_trail_completeness_enforcer,
        )
        return get_audit_trail_completeness_enforcer

    # Dual Approval getter
    if name == "get_dual_approval_enforcer":
        from kernel.immutable_laws.dual_approval_enforcer import get_dual_approval_enforcer
        return get_dual_approval_enforcer

    # Evidence Mandate auxiliary types & getter
    if name == "EvidenceType":
        from kernel.immutable_laws.evidence_mandate_enforcer import EvidenceType
        return EvidenceType
    if name == "EvidenceQuality":
        from kernel.immutable_laws.evidence_mandate_enforcer import EvidenceQuality
        return EvidenceQuality
    if name == "Evidence":
        from kernel.immutable_laws.evidence_mandate_enforcer import Evidence
        return Evidence
    if name == "EvidenceRequirement":
        from kernel.immutable_laws.evidence_mandate_enforcer import EvidenceRequirement
        return EvidenceRequirement
    if name == "get_evidence_mandate_enforcer":
        from kernel.immutable_laws.evidence_mandate_enforcer import get_evidence_mandate_enforcer
        return get_evidence_mandate_enforcer

    # Fair Value auxiliary types & getter
    if name == "FairValueHierarchy":
        from kernel.immutable_laws.fair_value_measurement_enforcer import FairValueHierarchy
        return FairValueHierarchy
    if name == "ValuationTechnique":
        from kernel.immutable_laws.fair_value_measurement_enforcer import ValuationTechnique
        return ValuationTechnique
    if name == "get_fair_value_measurement_enforcer":
        from kernel.immutable_laws.fair_value_measurement_enforcer import (
            get_fair_value_measurement_enforcer,
        )
        return get_fair_value_measurement_enforcer

    # GL Supremacy auxiliary types & getter
    if name == "SubledgerType":
        from kernel.immutable_laws.gl_supremacy_enforcer import SubledgerType
        return SubledgerType
    if name == "ReconciliationStatus":
        from kernel.immutable_laws.gl_supremacy_enforcer import ReconciliationStatus
        return ReconciliationStatus
    if name == "ReconciliationResult":
        from kernel.immutable_laws.gl_supremacy_enforcer import ReconciliationResult
        return ReconciliationResult
    if name == "ReconciliationHistory":
        from kernel.immutable_laws.gl_supremacy_enforcer import ReconciliationHistory
        return ReconciliationHistory
    if name == "get_gl_supremacy_enforcer":
        from kernel.immutable_laws.gl_supremacy_enforcer import get_gl_supremacy_enforcer
        return get_gl_supremacy_enforcer

    # Immutability getter
    if name == "get_immutability_enforcer":
        from kernel.immutable_laws.immutability_enforcer import get_immutability_enforcer
        return get_immutability_enforcer

    # Law Violation Exceptions (already imported directly, but keep for completeness)
    if name == "LawViolationSeverity":
        from kernel.immutable_laws.law_violation_exceptions import LawViolationSeverity
        return LawViolationSeverity
    if name == "LawCode":
        from kernel.immutable_laws.law_violation_exceptions import LawCode
        return LawCode
    if name == "ImmutableLawViolationError":
        from kernel.immutable_laws.law_violation_exceptions import ImmutableLawViolationError
        return ImmutableLawViolationError
    if name == "ImmutabilityLawViolation":
        from kernel.immutable_laws.law_violation_exceptions import ImmutabilityLawViolation
        return ImmutabilityLawViolation
    if name == "EvidenceMandateViolation":
        from kernel.immutable_laws.law_violation_exceptions import EvidenceMandateViolation
        return EvidenceMandateViolation
    if name == "DualApprovalViolation":
        from kernel.immutable_laws.law_violation_exceptions import DualApprovalViolation
        return DualApprovalViolation
    if name == "ReversalConstraintViolation":
        from kernel.immutable_laws.law_violation_exceptions import ReversalConstraintViolation
        return ReversalConstraintViolation
    if name == "TraceabilityViolation":
        from kernel.immutable_laws.law_violation_exceptions import TraceabilityViolation
        return TraceabilityViolation
    if name == "PeriodClosureViolation":
        from kernel.immutable_laws.law_violation_exceptions import PeriodClosureViolation
        return PeriodClosureViolation
    if name == "GLSupremacyViolation":
        from kernel.immutable_laws.law_violation_exceptions import GLSupremacyViolation
        return GLSupremacyViolation
    if name == "SegregationOfDutiesViolation":
        from kernel.immutable_laws.law_violation_exceptions import SegregationOfDutiesViolation
        return SegregationOfDutiesViolation
    if name == "NoRetroactivePolicyViolation":
        from kernel.immutable_laws.law_violation_exceptions import NoRetroactivePolicyViolation
        return NoRetroactivePolicyViolation
    if name == "AuditTrailCompletenessViolation":
        from kernel.immutable_laws.law_violation_exceptions import AuditTrailCompletenessViolation
        return AuditTrailCompletenessViolation
    if name == "AssetExistenceViolation":
        from kernel.immutable_laws.law_violation_exceptions import AssetExistenceViolation
        return AssetExistenceViolation
    if name == "FairValueMeasurementViolation":
        from kernel.immutable_laws.law_violation_exceptions import FairValueMeasurementViolation
        return FairValueMeasurementViolation
    if name == "LawViolationExceptionFactory":
        from kernel.immutable_laws.law_violation_exceptions import LawViolationExceptionFactory
        return LawViolationExceptionFactory

    # No Retroactive Policy auxiliary types & getter
    if name == "RetroactiveReason":
        from kernel.immutable_laws.no_retroactive_policy_enforcer import RetroactiveReason
        return RetroactiveReason
    if name == "PolicyType":
        from kernel.immutable_laws.no_retroactive_policy_enforcer import PolicyType
        return PolicyType
    if name == "AccountingPolicy":
        from kernel.immutable_laws.no_retroactive_policy_enforcer import AccountingPolicy
        return AccountingPolicy
    if name == "RetroactiveApplicationRecord":
        from kernel.immutable_laws.no_retroactive_policy_enforcer import (
            RetroactiveApplicationRecord,
        )
        return RetroactiveApplicationRecord
    if name == "get_no_retroactive_policy_enforcer":
        from kernel.immutable_laws.no_retroactive_policy_enforcer import (
            get_no_retroactive_policy_enforcer,
        )
        return get_no_retroactive_policy_enforcer

    # Period Closure auxiliary types & getter
    if name == "PeriodStatus":
        from kernel.immutable_laws.period_closure_enforcer import PeriodStatus
        return PeriodStatus
    if name == "PeriodClosureSeverity":
        from kernel.immutable_laws.period_closure_enforcer import PeriodClosureSeverity
        return PeriodClosureSeverity
    if name == "FiscalPeriod":
        from kernel.immutable_laws.period_closure_enforcer import FiscalPeriod
        return FiscalPeriod
    if name == "PeriodClosureCheckResult":
        from kernel.immutable_laws.period_closure_enforcer import PeriodClosureCheckResult
        return PeriodClosureCheckResult
    if name == "get_period_closure_enforcer":
        from kernel.immutable_laws.period_closure_enforcer import get_period_closure_enforcer
        return get_period_closure_enforcer

    # Reversal Constraint auxiliary types & getter
    if name == "ReversalReason":
        from kernel.immutable_laws.reversal_constraint_enforcer import ReversalReason
        return ReversalReason
    if name == "ReversalSeverity":
        from kernel.immutable_laws.reversal_constraint_enforcer import ReversalSeverity
        return ReversalSeverity
    if name == "ReversalRecord":
        from kernel.immutable_laws.reversal_constraint_enforcer import ReversalRecord
        return ReversalRecord
    if name == "ReversalCheckResult":
        from kernel.immutable_laws.reversal_constraint_enforcer import ReversalCheckResult
        return ReversalCheckResult
    if name == "get_reversal_constraint_enforcer":
        from kernel.immutable_laws.reversal_constraint_enforcer import (
            get_reversal_constraint_enforcer,
        )
        return get_reversal_constraint_enforcer

    # Segregation of Duties auxiliary types & getter
    if name == "SODRuleType":
        from kernel.immutable_laws.segregation_of_duties_enforcer import SODRuleType
        return SODRuleType
    if name == "SODViolationSeverity":
        from kernel.immutable_laws.segregation_of_duties_enforcer import SODViolationSeverity
        return SODViolationSeverity
    if name == "SODRule":
        from kernel.immutable_laws.segregation_of_duties_enforcer import SODRule
        return SODRule
    if name == "SODViolationRecord":
        from kernel.immutable_laws.segregation_of_duties_enforcer import SODViolationRecord
        return SODViolationRecord
    if name == "get_segregation_of_duties_enforcer":
        from kernel.immutable_laws.segregation_of_duties_enforcer import (
            get_segregation_of_duties_enforcer,
        )
        return get_segregation_of_duties_enforcer

    # Traceability auxiliary types & getter
    if name == "SourceType":
        from kernel.immutable_laws.traceability_enforcer import SourceType
        return SourceType
    if name == "TraceabilitySeverity":
        from kernel.immutable_laws.traceability_enforcer import TraceabilitySeverity
        return TraceabilitySeverity
    if name == "TraceabilityRecord":
        from kernel.immutable_laws.traceability_enforcer import TraceabilityRecord
        return TraceabilityRecord
    if name == "TraceabilityCheckResult":
        from kernel.immutable_laws.traceability_enforcer import TraceabilityCheckResult
        return TraceabilityCheckResult
    if name == "get_traceability_enforcer":
        from kernel.immutable_laws.traceability_enforcer import get_traceability_enforcer
        return get_traceability_enforcer

    raise AttributeError(f"module {__name__} has no attribute {name}")


# ============================================================================
# Public API - all names that should be importable from this package
# ============================================================================

# Diurutkan secara alfabetis sesuai saran RUF022 dan I001
__all__ = [
    "AccountingPolicy",
    "AssetExistenceEnforcer",
    "AssetExistenceError",
    "AssetExistenceViolation",
    "AssetType",
    "AuditTrailCompletenessEnforcer",
    "AuditTrailCompletenessError",
    "AuditTrailCompletenessViolation",
    "BaseEnforcer",
    "DualApprovalEnforcer",
    "DualApprovalError",
    "DualApprovalViolation",
    "Evidence",
    "EvidenceMandateEnforcer",
    "EvidenceMandateError",
    "EvidenceMandateViolation",
    "EvidenceQuality",
    "EvidenceRequirement",
    "EvidenceType",
    "FairValueHierarchy",
    "FairValueMeasurementEnforcer",
    "FairValueMeasurementError",
    "FairValueMeasurementViolation",
    "FiscalPeriod",
    "GLSupremacyEnforcer",
    "GLSupremacyError",
    "GLSupremacyViolation",
    "ImmutabilityEnforcer",
    "ImmutabilityError",
    "ImmutabilityLawViolation",
    "ImmutableLawViolationError",
    "LawCode",
    "LawViolationExceptionFactory",
    "LawViolationSeverity",
    "NoRetroactivePolicyEnforcer",
    "NoRetroactivePolicyError",
    "NoRetroactivePolicyViolation",
    "PeriodClosureCheckResult",
    "PeriodClosureEnforcer",
    "PeriodClosureError",
    "PeriodClosureSeverity",
    "PeriodClosureViolation",
    "PeriodStatus",
    "PolicyType",
    "ReconciliationHistory",
    "ReconciliationResult",
    "ReconciliationStatus",
    "RetroactiveApplicationRecord",
    "RetroactiveReason",
    "ReversalCheckResult",
    "ReversalConstraintEnforcer",
    "ReversalConstraintError",
    "ReversalConstraintViolation",
    "ReversalReason",
    "ReversalRecord",
    "ReversalSeverity",
    "SODRule",
    "SODRuleType",
    "SODViolationRecord",
    "SODViolationSeverity",
    "SegregationOfDutiesEnforcer",
    "SegregationOfDutiesError",
    "SegregationOfDutiesViolation",
    "SourceType",
    "SubledgerType",
    "TraceabilityCheckResult",
    "TraceabilityEnforcer",
    "TraceabilityError",
    "TraceabilityRecord",
    "TraceabilitySeverity",
    "TraceabilityViolation",
    "ValuationTechnique",
    "VerificationMethod",
    "__version__",
    "get_asset_existence_enforcer",
    "get_audit_trail_completeness_enforcer",
    "get_dual_approval_enforcer",
    "get_evidence_mandate_enforcer",
    "get_fair_value_measurement_enforcer",
    "get_gl_supremacy_enforcer",
    "get_immutability_enforcer",
    "get_no_retroactive_policy_enforcer",
    "get_period_closure_enforcer",
    "get_reversal_constraint_enforcer",
    "get_segregation_of_duties_enforcer",
    "get_traceability_enforcer",
]

