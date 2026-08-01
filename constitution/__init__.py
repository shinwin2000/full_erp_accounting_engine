#!/usr/bin/env python3
"""
Package: constitution
Layer: 1 - Foundation / Constitution

Responsibility:
    Hukum tertinggi sistem ERP akuntansi. Semua modul tunduk pada aturan
    yang didefinisikan di package ini. Package ini menyediakan komponen:
    - supreme_law: Aturan dasar konstitusi
    - sovereignty_declaration: Kedaulatan sistem dan batasan domain
    - amendment_protocol: Protokol perubahan konstitusi
    - version_lock: Penguncian versi konstitusi
    - constitutional_invariants: Invariant fundamental akuntansi
    - forbidden_states: State terlarang yang tidak boleh terjadi
    - enforcement_engine: Mesin penegak konstitusi
    - constitution_exceptions: Hierarki exception konstitusi

Dependencies:
    - Tidak ada dependensi ke layer lain (domain, application, adapters)
    - Hanya menggunakan standard library

Audit:
    Setiap akses ke konstitusi melalui enforcement engine dictat.
    Perubahan konstitusi melalui amendment protocol memiliki audit trail.
"""

from __future__ import annotations

__version__ = "1.0.0"

# === SUPREME LAW ===
# === AMENDMENT PROTOCOL ===
from constitution.amendment_protocol import (
    AmendmentConflictError,
    AmendmentExecutionRecord,
    AmendmentProposal,
    AmendmentProtocol,
    AmendmentProtocolError,
    AmendmentProtocolService,
    AmendmentStatus,
    AmendmentType,
    AmendmentVote,
    AmendmentVoteRecord,
    InsufficientApprovalError,
    MigrationError,
    MigrationStrategy,
    get_amendment_protocol,
)

# === CONSTITUTION EXCEPTIONS ===
from constitution.constitution_exceptions import (
    AmendmentException,
    AuthorizationException,
    ConstitutionalViolationException,
    ConstitutionException,
    ConstitutionExceptionCategory,
    ConstitutionExceptionFactory,
    ConstitutionExceptionSeverity,
    EnforcementException,
    ForbiddenStateException,
    IntegrityException,
    InvariantViolationException,
    SovereigntyViolationException,
    ValidationException,
    VersionLockException,
)

# === CONSTITUTIONAL INVARIANTS ===
from constitution.constitutional_invariants import (
    ConstitutionalInvariants,
    ConstitutionalInvariantsService,
    InvariantDefinition,
    InvariantScope,
    InvariantSeverity,
    InvariantType,
    InvariantValidator,
    InvariantViolation,
    get_constitutional_invariants_service,
    get_validator_for_invariant,
)

# === ENFORCEMENT ENGINE ===
from constitution.enforcement_engine import (
    EnforcementEngine,
    EnforcementPipeline,
    EnforcementReport,
    EnforcementResult,
    EnforcementStage,
    get_enforcement_engine,
)

# === FORBIDDEN STATES ===
from constitution.forbidden_states import (
    ForbiddenStateCategory,
    ForbiddenStateDefinition,
    ForbiddenStateDetection,
    ForbiddenStateDetector,
    ForbiddenStateSeverity,
    ForbiddenStatesRegistry,
    ForbiddenStatesService,
    StateDetectionMethod,
    get_detector_for_state,
    get_forbidden_states_service,
)

# === SOVEREIGNTY DECLARATION ===
from constitution.sovereignty_declaration import (
    ExternalInterferenceDetectedError,
    ExternalInterferenceType,
    InterferenceRecord,
    SovereigntyBoundary,
    SovereigntyDeclaration,
    SovereigntyDeclarationError,
    SovereigntyDomain,
    SovereigntyEvent,
    SovereigntyGuardian,
    SovereigntyStatus,
    get_sovereignty_guardian,
)
from constitution.supreme_law import (
    AmendmentRecord,
    Constitution,
    ConstitutionalPrinciple,
    ConstitutionalRule,
    ConstitutionalSeverity,
    ConstitutionalSnapshot,
    ConstitutionalViolationError,
    ConstitutionAmendmentError,
    EmergencyOverride,
    EmergencyOverrideError,
    EmergencyOverrideReason,
    SovereigntyLevel,
    SovereigntyViolationError,
    SupremeLaw,
    ViolationRecord,
    get_supreme_law,
)

# === VERSION LOCK ===
from constitution.version_lock import (
    IntegrityCheckResult,
    IntegrityReport,
    VersionChangeAttempt,
    VersionChangeType,
    VersionFreezeError,
    VersionIntegrityError,
    VersionLock,
    VersionLockError,
    VersionLockRecord,
    VersionLockService,
    VersionLockSeverity,
    VersionLockState,
    VersionLockViolationError,
    VersionMetadata,
    get_version_lock_service,
)

# Diurutkan secara alfabetis
__all__ = [
    "AmendmentConflictError",
    "AmendmentException",
    "AmendmentExecutionRecord",
    "AmendmentProposal",
    "AmendmentProtocol",
    "AmendmentProtocolError",
    "AmendmentProtocolService",
    "AmendmentRecord",
    "AmendmentStatus",
    "AmendmentType",
    "AmendmentVote",
    "AmendmentVoteRecord",
    "AuthorizationException",
    "Constitution",
    "ConstitutionAmendmentError",
    "ConstitutionException",
    "ConstitutionExceptionCategory",
    "ConstitutionExceptionFactory",
    "ConstitutionExceptionSeverity",
    "ConstitutionalInvariants",
    "ConstitutionalInvariantsService",
    "ConstitutionalPrinciple",
    "ConstitutionalRule",
    "ConstitutionalSeverity",
    "ConstitutionalSnapshot",
    "ConstitutionalViolationError",
    "ConstitutionalViolationException",
    "EmergencyOverride",
    "EmergencyOverrideError",
    "EmergencyOverrideReason",
    "EnforcementEngine",
    "EnforcementException",
    "EnforcementPipeline",
    "EnforcementReport",
    "EnforcementResult",
    "EnforcementStage",
    "ExternalInterferenceDetectedError",
    "ExternalInterferenceType",
    "ForbiddenStateCategory",
    "ForbiddenStateDefinition",
    "ForbiddenStateDetection",
    "ForbiddenStateDetector",
    "ForbiddenStateException",
    "ForbiddenStateSeverity",
    "ForbiddenStatesRegistry",
    "ForbiddenStatesService",
    "InsufficientApprovalError",  # Diperbaiki dari "InsensitiveApprovalError"
    "IntegrityCheckResult",
    "IntegrityException",
    "IntegrityReport",
    "InterferenceRecord",
    "InvariantDefinition",
    "InvariantScope",
    "InvariantSeverity",
    "InvariantType",
    "InvariantValidator",
    "InvariantViolation",
    "InvariantViolationException",
    "MigrationError",
    "MigrationStrategy",
    "SovereigntyBoundary",
    "SovereigntyDeclaration",
    "SovereigntyDeclarationError",
    "SovereigntyDomain",
    "SovereigntyEvent",
    "SovereigntyGuardian",
    "SovereigntyLevel",
    "SovereigntyStatus",
    "SovereigntyViolationError",
    "SovereigntyViolationException",
    "StateDetectionMethod",
    "SupremeLaw",
    "ValidationException",
    "VersionChangeAttempt",
    "VersionChangeType",
    "VersionFreezeError",
    "VersionIntegrityError",
    "VersionLock",
    "VersionLockError",
    "VersionLockEventType",
    "VersionLockException",
    "VersionLockRecord",
    "VersionLockService",
    "VersionLockSeverity",
    "VersionLockState",
    "VersionLockViolationError",
    "VersionMetadata",
    "ViolationRecord",
    "__version__",
    "get_amendment_protocol",
    "get_constitutional_invariants_service",
    "get_detector_for_state",
    "get_enforcement_engine",
    "get_forbidden_states_service",
    "get_sovereignty_guardian",
    "get_supreme_law",
    "get_validator_for_invariant",
    "get_version_lock_service",
]
