#!/usr/bin/env python3
"""
Package: domain.intent
Layer: 5 - Reality, Intent, Causality / Intent

Responsibility: Menangkap dan mengelola maksud pengguna (intent) sebelum
               dieksekusi menjadi economic events. Intent bersifat draft,
               dapat diedit, disetujui, dan ditandatangani secara digital
               sebelum menjadi immutable record.

Dependencies:
    - domain.intent.immutable_record (ImmutableIntentRecord, IntentStatus)
    - domain.intent.audit_trail_writer (AuditTrailWriter)
    - kernel.context_holder (optional, fallback provided)
    - infrastructure.event_store.append_only_store (optional)

Audit: Setiap perubahan intent dictat dalam immutable audit trail.
"""

from __future__ import annotations

import logging

# approval_workflow
from domain.intent.approval_workflow import (
    ApprovalAction,
    ApprovalLevel,
    ApprovalRecord,
    ApprovalRule,
    ApprovalStatus,
    ApprovalWorkflow,
    get_approval_workflow,
)

# audit_trail_writer
from domain.intent.audit_trail_writer import (
    AuditTrailWriter,
    IntentAuditAction,
    IntentAuditRecord,
    IntentAuditSeverity,
    get_audit_trail_writer,
)

# capture_service
from domain.intent.capture_service import (
    CapturedIntent,
    IntentCaptureService,
    IntentType,
    get_intent_capture_service,
)

# context_enricher
from domain.intent.context_enricher import (
    ContextEnricher,
    EnrichedContext,
    get_context_enricher,
)

# cryptographic_signer
from domain.intent.cryptographic_signer import (
    CRYPTO_AVAILABLE,
    CryptographicSigner,
    get_cryptographic_signer,
)

# forensic_query_engine
from domain.intent.forensic_query_engine import (
    ForensicQueryEngine,
    ForensicQueryResult,
    ForensicQueryType,
    ForensicSortOrder,
    get_forensic_query_engine,
)

# immutable_record
from domain.intent.immutable_record import (
    ImmutableIntentRecord,
    ImmutableIntentRecordService,
    IntentSource,
    IntentStatus,
    get_immutable_intent_record_service,
)

# intent_exceptions
from domain.intent.intent_exceptions import (
    IntentAlreadyApprovedError,
    IntentAlreadyCancelledError,
    IntentAlreadyExecutedError,
    IntentAlreadySubmittedError,
    IntentApprovalInsufficientError,
    IntentApprovalLevelInvalidError,
    IntentCannotVoidError,
    IntentDataIncompleteError,
    IntentError,
    IntentErrorCode,
    IntentExceptionFactory,
    IntentInvalidStatusError,
    IntentNotFoundError,
    IntentRiskTooHighError,
    IntentSeverity,
    IntentValidationFailedError,
    IntentWorkflowInvalidTransitionError,
)

# materiality_evaluator
from domain.intent.materiality_evaluator import (
    MaterialityDimension,
    MaterialityEvaluation,
    MaterialityEvaluator,
    MaterialityLevel,
    MaterialityThreshold,
    get_materiality_evaluator,
)

# outcome_link_tracker
from domain.intent.outcome_link_tracker import (
    IntentOutcomeLink,
    LinkStatus,
    LinkType,
    OutcomeLinkTracker,
    get_outcome_link_tracker,
)

# revision_logger
from domain.intent.revision_logger import (
    IntentRevision,
    RevisionChange,
    RevisionChangeType,
    RevisionLogger,
    get_revision_logger,
)

# risk_assessor
from domain.intent.risk_assessor import (
    RiskAssessment,
    RiskAssessmentStatus,
    RiskAssessor,
    RiskCategory,
    RiskFactor,
    RiskLevel,
    get_risk_assessor,
)

# void_processor
from domain.intent.void_processor import (
    VoidProcessor,
    VoidReason,
    VoidRecord,
    VoidScope,
    get_void_processor,
)

__version__ = "1.0.0"

logger = logging.getLogger(__name__)

# ============================================================================
# Ekspor semua simbol
# ============================================================================

__all__ = [
    # cryptographic_signer
    "CRYPTO_AVAILABLE",
    # approval_workflow
    "ApprovalAction",
    "ApprovalLevel",
    "ApprovalRecord",
    "ApprovalRule",
    "ApprovalStatus",
    "ApprovalWorkflow",
    # audit_trail_writer
    "AuditTrailWriter",
    # capture_service
    "CapturedIntent",
    # context_enricher
    "ContextEnricher",
    "CryptographicSigner",
    "EnrichedContext",
    # forensic_query_engine
    "ForensicQueryEngine",
    "ForensicQueryResult",
    "ForensicQueryType",
    "ForensicSortOrder",
    # immutable_record
    "ImmutableIntentRecord",
    "ImmutableIntentRecordService",
    # intent_exceptions
    "IntentAlreadyApprovedError",
    "IntentAlreadyCancelledError",
    "IntentAlreadyExecutedError",
    "IntentAlreadySubmittedError",
    "IntentApprovalInsufficientError",
    "IntentApprovalLevelInvalidError",
    "IntentAuditAction",
    "IntentAuditRecord",
    "IntentAuditSeverity",
    "IntentCannotVoidError",
    "IntentCaptureService",
    "IntentDataIncompleteError",
    "IntentError",
    "IntentErrorCode",
    "IntentExceptionFactory",
    "IntentInvalidStatusError",
    "IntentNotFoundError",
    # outcome_link_tracker
    "IntentOutcomeLink",
    # revision_logger
    "IntentRevision",
    "IntentRiskTooHighError",
    "IntentSeverity",
    "IntentSource",
    "IntentStatus",
    "IntentType",
    "IntentValidationFailedError",
    "IntentWorkflowInvalidTransitionError",
    "LinkStatus",
    "LinkType",
    # materiality_evaluator
    "MaterialityDimension",
    "MaterialityEvaluation",
    "MaterialityEvaluator",
    "MaterialityLevel",
    "MaterialityThreshold",
    "OutcomeLinkTracker",
    "RevisionChange",
    "RevisionChangeType",
    "RevisionLogger",
    # risk_assessor
    "RiskAssessment",
    "RiskAssessmentStatus",
    "RiskAssessor",
    "RiskCategory",
    "RiskFactor",
    "RiskLevel",
    # void_processor
    "VoidProcessor",
    "VoidReason",
    "VoidRecord",
    "VoidScope",
    "__version__",
    "get_approval_workflow",
    "get_audit_trail_writer",
    "get_context_enricher",
    "get_cryptographic_signer",
    "get_forensic_query_engine",
    "get_immutable_intent_record_service",
    "get_intent_capture_service",
    "get_materiality_evaluator",
    "get_outcome_link_tracker",
    "get_revision_logger",
    "get_risk_assessor",
    "get_void_processor",
]
