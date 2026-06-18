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
from typing import Any

__version__ = "1.0.0"

logger = logging.getLogger(__name__)

# ============================================================================
# Import semua modul secara statis (tanpa __import__) untuk menghindari
# dynamic import warning. Circular dependencies telah diatasi dengan memisahkan
# IntentType ke file terpisah dan menggunakan forward references di TYPE_CHECKING.
# ============================================================================

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

# ============================================================================
# Ekspor semua simbol
# ============================================================================

__all__ = [
    # approval_workflow
    "ApprovalLevel",
    "ApprovalAction",
    "ApprovalStatus",
    "ApprovalRule",
    "ApprovalRecord",
    "ApprovalWorkflow",
    "get_approval_workflow",
    # audit_trail_writer
    "IntentAuditAction",
    "IntentAuditSeverity",
    "IntentAuditRecord",
    "AuditTrailWriter",
    "get_audit_trail_writer",
    # capture_service
    "IntentType",
    "CapturedIntent",
    "IntentCaptureService",
    "get_intent_capture_service",
    # immutable_record
    "IntentStatus",
    "IntentSource",
    "ImmutableIntentRecord",
    "ImmutableIntentRecordService",
    "get_immutable_intent_record_service",
    # cryptographic_signer
    "CryptographicSigner",
    "get_cryptographic_signer",
    "CRYPTO_AVAILABLE",
    # context_enricher
    "EnrichedContext",
    "ContextEnricher",
    "get_context_enricher",
    # outcome_link_tracker
    "LinkStatus",
    "LinkType",
    "IntentOutcomeLink",
    "OutcomeLinkTracker",
    "get_outcome_link_tracker",
    # forensic_query_engine
    "ForensicQueryType",
    "ForensicSortOrder",
    "ForensicQueryResult",
    "ForensicQueryEngine",
    "get_forensic_query_engine",
    # revision_logger
    "RevisionChangeType",
    "RevisionChange",
    "IntentRevision",
    "RevisionLogger",
    "get_revision_logger",
    # risk_assessor
    "RiskCategory",
    "RiskLevel",
    "RiskAssessmentStatus",
    "RiskFactor",
    "RiskAssessment",
    "RiskAssessor",
    "get_risk_assessor",
    # materiality_evaluator
    "MaterialityLevel",
    "MaterialityDimension",
    "MaterialityThreshold",
    "MaterialityEvaluation",
    "MaterialityEvaluator",
    "get_materiality_evaluator",
    # void_processor
    "VoidReason",
    "VoidScope",
    "VoidRecord",
    "VoidProcessor",
    "get_void_processor",
    # intent_exceptions
    "IntentErrorCode",
    "IntentSeverity",
    "IntentError",
    "IntentNotFoundError",
    "IntentInvalidStatusError",
    "IntentAlreadySubmittedError",
    "IntentAlreadyApprovedError",
    "IntentAlreadyExecutedError",
    "IntentAlreadyCancelledError",
    "IntentValidationFailedError",
    "IntentDataIncompleteError",
    "IntentApprovalInsufficientError",
    "IntentApprovalLevelInvalidError",
    "IntentRiskTooHighError",
    "IntentCannotVoidError",
    "IntentWorkflowInvalidTransitionError",
    "IntentExceptionFactory",
    "__version__",
]
