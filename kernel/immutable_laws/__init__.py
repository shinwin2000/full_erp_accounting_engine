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

# === LAZY IMPORTS untuk menghindari circular import ===


def __getattr__(name):
    # Asset Existence Enforcer
    if name == "AssetType":
        from kernel.immutable_laws.asset_existence_enforcer import AssetType

        return AssetType
    if name == "VerificationMethod":
        from kernel.immutable_laws.asset_existence_enforcer import VerificationMethod

        return VerificationMethod
    if name == "AssetExistenceEnforcer":
        from kernel.immutable_laws.asset_existence_enforcer import AssetExistenceEnforcer

        return AssetExistenceEnforcer
    if name == "get_asset_existence_enforcer":
        from kernel.immutable_laws.asset_existence_enforcer import get_asset_existence_enforcer

        return get_asset_existence_enforcer

    # Audit Trail Completeness Enforcer
    if name == "AuditTrailCompletenessEnforcer":
        from kernel.immutable_laws.audit_trail_completeness_enforcer import (
            AuditTrailCompletenessEnforcer,
        )

        return AuditTrailCompletenessEnforcer
    if name == "get_audit_trail_completeness_enforcer":
        from kernel.immutable_laws.audit_trail_completeness_enforcer import (
            get_audit_trail_completeness_enforcer,
        )

        return get_audit_trail_completeness_enforcer

    # Dual Approval Enforcer
    if name == "DualApprovalEnforcer":
        from kernel.immutable_laws.dual_approval_enforcer import DualApprovalEnforcer

        return DualApprovalEnforcer
    if name == "get_dual_approval_enforcer":
        from kernel.immutable_laws.dual_approval_enforcer import get_dual_approval_enforcer

        return get_dual_approval_enforcer

    # Evidence Mandate Enforcer
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
    if name == "EvidenceMandateEnforcer":
        from kernel.immutable_laws.evidence_mandate_enforcer import EvidenceMandateEnforcer

        return EvidenceMandateEnforcer
    if name == "get_evidence_mandate_enforcer":
        from kernel.immutable_laws.evidence_mandate_enforcer import get_evidence_mandate_enforcer

        return get_evidence_mandate_enforcer

    # Fair Value Measurement Enforcer
    if name == "FairValueHierarchy":
        from kernel.immutable_laws.fair_value_measurement_enforcer import FairValueHierarchy

        return FairValueHierarchy
    if name == "ValuationTechnique":
        from kernel.immutable_laws.fair_value_measurement_enforcer import ValuationTechnique

        return ValuationTechnique
    if name == "FairValueMeasurementEnforcer":
        from kernel.immutable_laws.fair_value_measurement_enforcer import (
            FairValueMeasurementEnforcer,
        )

        return FairValueMeasurementEnforcer
    if name == "get_fair_value_measurement_enforcer":
        from kernel.immutable_laws.fair_value_measurement_enforcer import (
            get_fair_value_measurement_enforcer,
        )

        return get_fair_value_measurement_enforcer

    # GL Supremacy Enforcer
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
    if name == "GLSupremacyEnforcer":
        from kernel.immutable_laws.gl_supremacy_enforcer import GLSupremacyEnforcer

        return GLSupremacyEnforcer
    if name == "get_gl_supremacy_enforcer":
        from kernel.immutable_laws.gl_supremacy_enforcer import get_gl_supremacy_enforcer

        return get_gl_supremacy_enforcer

    # Immutability Enforcer
    if name == "ImmutabilityEnforcer":
        from kernel.immutable_laws.immutability_enforcer import ImmutabilityEnforcer

        return ImmutabilityEnforcer
    if name == "get_immutability_enforcer":
        from kernel.immutable_laws.immutability_enforcer import get_immutability_enforcer

        return get_immutability_enforcer

    # Law Violation Exceptions
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

    # No Retroactive Policy Enforcer
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
    if name == "NoRetroactivePolicyEnforcer":
        from kernel.immutable_laws.no_retroactive_policy_enforcer import NoRetroactivePolicyEnforcer

        return NoRetroactivePolicyEnforcer
    if name == "get_no_retroactive_policy_enforcer":
        from kernel.immutable_laws.no_retroactive_policy_enforcer import (
            get_no_retroactive_policy_enforcer,
        )

        return get_no_retroactive_policy_enforcer

    # Period Closure Enforcer
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
    if name == "PeriodClosureEnforcer":
        from kernel.immutable_laws.period_closure_enforcer import PeriodClosureEnforcer

        return PeriodClosureEnforcer
    if name == "get_period_closure_enforcer":
        from kernel.immutable_laws.period_closure_enforcer import get_period_closure_enforcer

        return get_period_closure_enforcer

    # Reversal Constraint Enforcer
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
    if name == "ReversalConstraintEnforcer":
        from kernel.immutable_laws.reversal_constraint_enforcer import ReversalConstraintEnforcer

        return ReversalConstraintEnforcer
    if name == "get_reversal_constraint_enforcer":
        from kernel.immutable_laws.reversal_constraint_enforcer import (
            get_reversal_constraint_enforcer,
        )

        return get_reversal_constraint_enforcer

    # Segregation of Duties Enforcer
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
    if name == "SegregationOfDutiesEnforcer":
        from kernel.immutable_laws.segregation_of_duties_enforcer import SegregationOfDutiesEnforcer

        return SegregationOfDutiesEnforcer
    if name == "get_segregation_of_duties_enforcer":
        from kernel.immutable_laws.segregation_of_duties_enforcer import (
            get_segregation_of_duties_enforcer,
        )

        return get_segregation_of_duties_enforcer

    # Traceability Enforcer
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
    if name == "TraceabilityEnforcer":
        from kernel.immutable_laws.traceability_enforcer import TraceabilityEnforcer

        return TraceabilityEnforcer
    if name == "get_traceability_enforcer":
        from kernel.immutable_laws.traceability_enforcer import get_traceability_enforcer

        return get_traceability_enforcer

    raise AttributeError(f"module {__name__} has no attribute {name}")


__all__ = [
    # Asset Existence
    "AssetType",
    "VerificationMethod",
    "AssetExistenceEnforcer",
    "get_asset_existence_enforcer",
    # Audit Trail Completeness
    "AuditTrailCompletenessEnforcer",
    "get_audit_trail_completeness_enforcer",
    # Dual Approval
    "DualApprovalEnforcer",
    "get_dual_approval_enforcer",
    # Evidence Mandate
    "EvidenceType",
    "EvidenceQuality",
    "Evidence",
    "EvidenceRequirement",
    "EvidenceMandateEnforcer",
    "get_evidence_mandate_enforcer",
    # Fair Value
    "FairValueHierarchy",
    "ValuationTechnique",
    "FairValueMeasurementEnforcer",
    "get_fair_value_measurement_enforcer",
    # GL Supremacy
    "SubledgerType",
    "ReconciliationStatus",
    "ReconciliationResult",
    "ReconciliationHistory",
    "GLSupremacyEnforcer",
    "get_gl_supremacy_enforcer",
    # Immutability
    "ImmutabilityEnforcer",
    "get_immutability_enforcer",
    # Exceptions
    "LawViolationSeverity",
    "LawCode",
    "ImmutableLawViolationError",
    "ImmutabilityLawViolation",
    "EvidenceMandateViolation",
    "DualApprovalViolation",
    "ReversalConstraintViolation",
    "TraceabilityViolation",
    "PeriodClosureViolation",
    "GLSupremacyViolation",
    "SegregationOfDutiesViolation",
    "NoRetroactivePolicyViolation",
    "AuditTrailCompletenessViolation",
    "AssetExistenceViolation",
    "FairValueMeasurementViolation",
    "LawViolationExceptionFactory",
    # No Retroactive
    "RetroactiveReason",
    "PolicyType",
    "AccountingPolicy",
    "RetroactiveApplicationRecord",
    "NoRetroactivePolicyEnforcer",
    "get_no_retroactive_policy_enforcer",
    # Period Closure
    "PeriodStatus",
    "PeriodClosureSeverity",
    "FiscalPeriod",
    "PeriodClosureCheckResult",
    "PeriodClosureEnforcer",
    "get_period_closure_enforcer",
    # Reversal Constraint
    "ReversalReason",
    "ReversalSeverity",
    "ReversalRecord",
    "ReversalCheckResult",
    "ReversalConstraintEnforcer",
    "get_reversal_constraint_enforcer",
    # Segregation of Duties
    "SODRuleType",
    "SODViolationSeverity",
    "SODRule",
    "SODViolationRecord",
    "SegregationOfDutiesEnforcer",
    "get_segregation_of_duties_enforcer",
    # Traceability
    "SourceType",
    "TraceabilitySeverity",
    "TraceabilityRecord",
    "TraceabilityCheckResult",
    "TraceabilityEnforcer",
    "get_traceability_enforcer",
    "__version__",
]
