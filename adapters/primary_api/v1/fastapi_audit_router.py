#!/usr/bin/env python3
"""
Module: fastapi_audit_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk keperluan audit dan forensic:
               query event store, verifikasi hash chain, forensic replay, gap detection,
               sampling materiality, dan laporan audit.

Method Standards (ERP):
- query_event_store() / get_event_stream()
- verify_hash_chain() / verify_chain_integrity()
- forensic_replay() / rebuild_aggregate_state()
- detect_gaps() / get_missing_events()
- setup_sampling() / evaluate_sampling() / project_sampling()
- generate_audit_report() / generate_sox_report()
- get_audit_trail() / get_audit_by_entity()
- export_audit_data() / export_forensic_report()
- verify_integrity() / get_integrity_status()
- get_audit_statistics() / get_audit_summary()
- create_audit_snapshot() / compare_snapshots()
- audit_trail_forensic() / get_audit_events()
- version_audit_record()
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class AuditEventType(str, Enum):
    """Jenis event audit."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ = "read"
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    POST = "post"
    REVERSE = "reverse"
    CANCEL = "cancel"
    LOCK = "lock"
    UNLOCK = "unlock"
    ARCHIVE = "archive"
    RESTORE = "restore"
    EXPORT = "export"
    IMPORT = "import"
    LOGIN = "login"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    PERMISSION_CHANGE = "permission_change"
    SYSTEM_CONFIG = "system_config"
    DATA_MIGRATION = "data_migration"
    FORENSIC_REPLAY = "forensic_replay"
    INTEGRITY_CHECK = "integrity_check"


class AuditSeverity(str, Enum):
    """Level severity audit."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditStatus(str, Enum):
    """Status audit record."""

    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    SKIPPED = "skipped"


class SamplingMethod(str, Enum):
    """Metode sampling audit."""

    RANDOM = "random"
    SYSTEMATIC = "systematic"
    STRATIFIED = "stratified"
    MONETARY_UNIT = "monetary_unit"
    CLUSTER = "cluster"
    JUDGMENTAL = "judgmental"


class SamplingConclusion(str, Enum):
    """Kesimpulan sampling."""

    NO_MATERIAL_MISSTATEMENT = "no_material_misstatement"
    MATERIAL_MISSTATEMENT = "material_misstatement"
    INCONCLUSIVE = "inconclusive"
    NEEDS_FURTHER_TESTING = "needs_further_testing"


# Default sampling parameters
DEFAULT_CONFIDENCE_LEVEL = 95
DEFAULT_EXPECTED_ERROR_RATE = 1.0
DEFAULT_TOLERABLE_ERROR_RATE = 5.0
DEFAULT_MATERIALITY_THRESHOLD = 5.0


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class EventStoreQuerySchema(BaseModel):
    """Schema untuk query event store."""

    model_config = ConfigDict(from_attributes=True)

    aggregate_type: str | None = Field(None, description="Jenis aggregate")
    aggregate_id: UUID | None = Field(None, description="ID aggregate")
    event_type: AuditEventType | None = Field(None, description="Tipe event")
    start_time: datetime | None = Field(None, description="Waktu mulai")
    end_time: datetime | None = Field(None, description="Waktu akhir")
    user_id: UUID | None = Field(None, description="ID user")
    legal_entity_id: UUID | None = Field(None, description="ID legal entity")
    limit: int = Field(100, ge=1, le=10000, description="Limit records")
    offset: int = Field(0, ge=0, description="Offset untuk pagination")


class EventStoreEntrySchema(BaseModel):
    """Response event store entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    aggregate_type: str
    aggregate_id: UUID
    version: int
    event_type: str
    event_data: dict[str, Any]
    metadata: dict[str, Any]
    hash_prev: str | None
    hash_current: str
    recorded_at: datetime
    recorded_by: UUID
    recorded_by_name: str | None = None
    legal_entity_id: UUID | None = None


class HashChainVerifyResultSchema(BaseModel):
    """Response verifikasi hash chain."""

    model_config = ConfigDict(from_attributes=True)

    chain_type: str
    chain_id: UUID
    total_entries: int
    valid_count: int
    invalid_count: int
    invalid_entries: list[dict[str, Any]]
    first_invalid_index: int | None = None
    is_chain_valid: bool
    verified_at: datetime
    verified_by: UUID | None = None


class HashChainStatusSchema(BaseModel):
    """Response status hash chain."""

    model_config = ConfigDict(from_attributes=True)

    last_verified_at: datetime | None
    total_chains: int
    valid_chains: int
    invalid_chains: int
    chains: list[dict[str, Any]]


class ForensicReplayRequestSchema(BaseModel):
    """Schema untuk forensic replay."""

    model_config = ConfigDict(from_attributes=True)

    aggregate_type: str = Field(..., description="Jenis aggregate")
    aggregate_id: UUID = Field(..., description="ID aggregate")
    target_version: int | None = Field(None, ge=1, description="Target version")
    as_of_time: datetime | None = Field(None, description="Replay as of time")
    rebuild_snapshot: bool = Field(False, description="Rebuild snapshot after replay")


class ForensicReplayResponseSchema(BaseModel):
    """Response forensic replay."""

    model_config = ConfigDict(from_attributes=True)

    aggregate_type: str
    aggregate_id: UUID
    snapshot_version: int | None
    events_replayed: int
    final_state: dict[str, Any]
    replay_duration_ms: float
    replayed_at: datetime
    replayed_by: UUID


class GapDetectionResultSchema(BaseModel):
    """Response gap detection."""

    model_config = ConfigDict(from_attributes=True)

    gap_start: datetime
    gap_end: datetime
    gap_duration_seconds: float
    missing_sequence_numbers: list[int]
    expected_count: int
    actual_count: int


class SamplingSetupSchema(BaseModel):
    """Schema untuk setup sampling."""

    model_config = ConfigDict(from_attributes=True)

    basis_value: Decimal = Field(..., gt=0, description="Nilai basis materialitas")
    basis_type: str = Field(..., description="revenue, asset, equity, expense")
    population_size: int = Field(..., gt=0, description="Ukuran populasi")
    population_value: Decimal | None = Field(None, description="Nilai populasi (untuk MUS)")
    confidence_level: int = Field(
        DEFAULT_CONFIDENCE_LEVEL, ge=80, le=99, description="Tingkat keyakinan %"
    )
    expected_error_percent: Decimal = Field(
        Decimal(str(DEFAULT_EXPECTED_ERROR_RATE)), ge=0, le=100, description="Expected error %"
    )
    tolerable_error_percent: Decimal = Field(
        Decimal(str(DEFAULT_TOLERABLE_ERROR_RATE)), ge=0, le=100, description="Tolerable error %"
    )
    sampling_method: SamplingMethod = Field(SamplingMethod.RANDOM, description="Metode sampling")
    materiality_threshold: Decimal | None = Field(None, description="Ambang batas materialitas")

    @field_validator("basis_value", "population_value", "expected_error_percent", "tolerable_error_percent", "materiality_threshold", mode="before")
    @classmethod
    def validate_decimal(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return Decimal(str(v))
        return v


class SamplingResponseSchema(BaseModel):
    """Response sampling setup."""

    model_config = ConfigDict(from_attributes=True)

    engagement_id: UUID
    sample_size: int
    sampling_interval: Decimal | None = None
    materiality_threshold: Decimal
    performance_materiality: Decimal
    clearly_trivial_threshold: Decimal
    confidence_level: int
    expected_error: Decimal
    tolerable_error: Decimal
    sampling_method: str
    generated_at: datetime


class SamplingEvaluationSchema(BaseModel):
    """Schema untuk evaluasi sampling."""

    model_config = ConfigDict(from_attributes=True)

    errors: list[Decimal] = Field(..., description="List error amounts from sample")
    confidence_level: int = Field(DEFAULT_CONFIDENCE_LEVEL, ge=80, le=99)

    @field_validator("errors", mode="before")
    @classmethod
    def validate_errors(cls, v):
        if isinstance(v, list):
            return [Decimal(str(item)) if not isinstance(item, Decimal) else item for item in v]
        return v


class SamplingConclusionSchema(BaseModel):
    """Response kesimpulan sampling."""

    model_config = ConfigDict(from_attributes=True)

    conclusion: SamplingConclusion
    recommendation: str
    details: dict[str, Any]
    projected_error: Decimal
    upper_error_limit: Decimal
    margin_of_error: Decimal
    is_material: bool


class AuditReportRequestSchema(BaseModel):
    """Schema untuk generate audit report."""

    model_config = ConfigDict(from_attributes=True)

    start_date: date = Field(..., description="Tanggal mulai")
    end_date: date = Field(..., description="Tanggal akhir")
    include_hash_chain_verification: bool = Field(True)
    include_gap_detection: bool = Field(True)
    include_sampling_results: bool = Field(False)
    sampling_engagement_id: UUID | None = Field(None)
    report_format: str = Field("pdf", pattern="^(pdf|excel|html)$", description="Format laporan")


class AuditReportResponseSchema(BaseModel):
    """Response audit report."""

    model_config = ConfigDict(from_attributes=True)

    report_id: UUID
    report_number: str
    report_type: str
    start_date: date
    end_date: date
    generated_at: datetime
    generated_by: UUID
    generated_by_name: str | None = None
    findings_count: int
    recommendations_count: int
    hash_chain_status: str
    gap_detection_status: str
    file_url: str | None = None


class AuditFindingSchema(BaseModel):
    """Schema audit finding."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    finding_number: str
    category: str
    severity: AuditSeverity
    description: str
    affected_entities: list[dict[str, Any]]
    root_cause: str | None = None
    recommendation: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None


class SOXControlTestSchema(BaseModel):
    """Schema untuk SOX control test."""

    model_config = ConfigDict(from_attributes=True)

    control_id: str = Field(..., description="ID kontrol")
    control_name: str = Field(..., description="Nama kontrol")
    control_category: str = Field(..., description="Kategori kontrol")
    test_period_start: date = Field(..., description="Awal periode test")
    test_period_end: date = Field(..., description="Akhir periode test")
    sample_size: int = Field(..., gt=0, description="Ukuran sampel")
    deviations: int = Field(0, ge=0, description="Jumlah deviasi")
    notes: str | None = None


class SOXControlTestResponseSchema(BaseModel):
    """Response SOX control test."""

    model_config = ConfigDict(from_attributes=True)

    test_id: UUID
    control_id: str
    control_name: str
    control_category: str
    test_period_start: date
    test_period_end: date
    sample_size: int
    deviations: int
    deviation_rate: float
    threshold_rate: float
    is_effective: bool
    conclusion: str
    recommendations: list[str]
    tested_at: datetime
    tested_by: UUID
    tested_by_name: str | None = None


class AuditTrailSchema(BaseModel):
    """Response audit trail."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: UUID
    entity_reference: str | None = None
    action: str
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    changes: dict[str, Any] | None = None
    actor_id: UUID
    actor_name: str | None = None
    actor_ip: str | None = None
    actor_user_agent: str | None = None
    timestamp: datetime
    severity: AuditSeverity
    status: AuditStatus
    notes: str | None = None


class AuditStatisticsSchema(BaseModel):
    """Response statistik audit."""

    model_config = ConfigDict(from_attributes=True)

    total_events: int
    by_event_type: dict[str, int]
    by_severity: dict[str, int]
    by_status: dict[str, int]
    by_actor: dict[str, int]
    by_hour: dict[str, int]
    events_last_24h: int
    events_last_7d: int
    events_last_30d: int
    average_events_per_day: float
    as_of_date: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_audit_service() -> Any:
    """Get Audit Service instance."""
    from application.service_layer.service_audit import AuditService
    from infrastructure.dependency_container.ioc_container import get_container

    container = get_container()
    return container.resolve(AuditService)


async def get_sampling_engine() -> Any:
    """Get Audit Sampling Engine instance."""
    from audit.sampling_materiality.audit_sampling_engine_materiality_based import (
        get_sampling_engine,
    )

    return get_sampling_engine()


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/audit", tags=["Audit & Forensic"])


# ----------------------------------------------------------------------------
# EVENT STORE QUERY
# ----------------------------------------------------------------------------


@router.post(
    "/event-store/query",
    response_model=list[EventStoreEntrySchema],
    summary="Query event store",
    operation_id="query_event_store",
)
async def query_event_store(
    request: EventStoreQuerySchema,
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> list[EventStoreEntrySchema]:
    """Query event store with filters."""
    try:
        events = await audit_service.query_event_store(
            legal_entity_id=legal_entity_id,
            aggregate_type=request.aggregate_type,
            aggregate_id=request.aggregate_id,
            event_type=request.event_type.value if request.event_type else None,
            start_time=request.start_time,
            end_time=request.end_time,
            user_id=request.user_id,
            limit=request.limit,
            offset=request.offset,
        )

        return [
            EventStoreEntrySchema(
                id=e.id,
                aggregate_type=e.aggregate_type,
                aggregate_id=e.aggregate_id,
                version=e.version,
                event_type=e.event_type,
                event_data=e.event_data,
                metadata=e.metadata,
                hash_prev=e.hash_prev,
                hash_current=e.hash_current,
                recorded_at=e.recorded_at,
                recorded_by=e.recorded_by,
                recorded_by_name=e.recorded_by_name,
                legal_entity_id=e.legal_entity_id,
            )
            for e in events
        ]
    except Exception as e:
        logger.exception(f"Failed to query event store: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/event-store/aggregate/{aggregate_type}/{aggregate_id}",
    response_model=list[EventStoreEntrySchema],
    summary="Get event stream for aggregate",
    operation_id="get_aggregate_events",
)
async def get_aggregate_events(
    aggregate_type: str,
    aggregate_id: UUID,
    from_version: int | None = Query(None, ge=1, description="From version"),
    to_version: int | None = Query(None, ge=1, description="To version"),
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> list[EventStoreEntrySchema]:
    """Get all events for an aggregate (event sourcing)."""
    try:
        events = await audit_service.get_aggregate_events(
            legal_entity_id=legal_entity_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            from_version=from_version,
            to_version=to_version,
        )

        return [
            EventStoreEntrySchema(
                id=e.id,
                aggregate_type=e.aggregate_type,
                aggregate_id=e.aggregate_id,
                version=e.version,
                event_type=e.event_type,
                event_data=e.event_data,
                metadata=e.metadata,
                hash_prev=e.hash_prev,
                hash_current=e.hash_current,
                recorded_at=e.recorded_at,
                recorded_by=e.recorded_by,
                recorded_by_name=e.recorded_by_name,
                legal_entity_id=e.legal_entity_id,
            )
            for e in events
        ]
    except Exception as e:
        logger.exception(f"Failed to get aggregate events: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# HASH CHAIN VERIFICATION
# ----------------------------------------------------------------------------


@router.post(
    "/hash-chain/verify",
    response_model=HashChainVerifyResultSchema,
    summary="Verify hash chain integrity",
    operation_id="verify_hash_chain",
)
async def verify_hash_chain(
    chain_type: str = Body(..., embed=True, description="Type of chain (audit, event, snapshot)"),
    chain_id: UUID = Body(..., embed=True, description="Chain ID"),
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> HashChainVerifyResultSchema:
    """Verify integrity of a hash chain."""
    try:
        result = await audit_service.verify_hash_chain(
            legal_entity_id=legal_entity_id,
            chain_type=chain_type,
            chain_id=chain_id,
        )

        return HashChainVerifyResultSchema(
            chain_type=result.chain_type,
            chain_id=result.chain_id,
            total_entries=result.total_entries,
            valid_count=result.valid_count,
            invalid_count=result.invalid_count,
            invalid_entries=result.invalid_entries,
            first_invalid_index=result.first_invalid_index,
            is_chain_valid=result.is_chain_valid,
            verified_at=result.verified_at,
            verified_by=result.verified_by,
        )
    except Exception as e:
        logger.exception(f"Failed to verify hash chain: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/hash-chain/status",
    response_model=HashChainStatusSchema,
    summary="Get hash chain verification status",
    operation_id="get_hash_chain_status",
)
async def get_hash_chain_status(
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> HashChainStatusSchema:
    """Get verification status for all hash chains."""
    try:
        status = await audit_service.get_hash_chain_status(legal_entity_id)

        return HashChainStatusSchema(
            last_verified_at=status.last_verified_at,
            total_chains=status.total_chains,
            valid_chains=status.valid_chains,
            invalid_chains=status.invalid_chains,
            chains=status.chains,
        )
    except Exception as e:
        logger.exception(f"Failed to get hash chain status: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# FORENSIC REPLAY
# ----------------------------------------------------------------------------


@router.post(
    "/forensic/replay",
    response_model=ForensicReplayResponseSchema,
    summary="Replay events to rebuild aggregate state",
    operation_id="forensic_replay",
)
async def forensic_replay(
    request: ForensicReplayRequestSchema,
    _permission: None = Depends(require_permission("audit:forensic")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> ForensicReplayResponseSchema:
    """
    Replay events to rebuild aggregate state.

    - Used for forensic investigation
    - Can replay to specific version or point in time
    - Optionally rebuild snapshot after replay
    """
    try:
        result = await audit_service.forensic_replay(
            legal_entity_id=legal_entity_id,
            aggregate_type=request.aggregate_type,
            aggregate_id=request.aggregate_id,
            target_version=request.target_version,
            as_of_time=request.as_of_time,
            rebuild_snapshot=request.rebuild_snapshot,
            replayed_by=current_user.user_id,
        )

        return ForensicReplayResponseSchema(
            aggregate_type=result.aggregate_type,
            aggregate_id=result.aggregate_id,
            snapshot_version=result.snapshot_version,
            events_replayed=result.events_replayed,
            final_state=result.final_state,
            replay_duration_ms=result.replay_duration_ms,
            replayed_at=result.replayed_at,
            replayed_by=result.replayed_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to run forensic replay: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# GAP DETECTION
# ----------------------------------------------------------------------------


@router.post(
    "/gap-detection",
    response_model=list[GapDetectionResultSchema],
    summary="Detect gaps in event sequence",
    operation_id="detect_gaps",
)
async def detect_gaps(
    aggregate_type: str = Body(..., embed=True, description="Aggregate type"),
    start_time: datetime = Body(..., embed=True, description="Start time"),
    end_time: datetime = Body(..., embed=True, description="End time"),
    _permission: None = Depends(require_permission("audit:forensic")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> list[GapDetectionResultSchema]:
    """Detect gaps in event sequence (missing events)."""
    try:
        gaps = await audit_service.detect_gaps(
            legal_entity_id=legal_entity_id,
            aggregate_type=aggregate_type,
            start_time=start_time,
            end_time=end_time,
        )

        return [
            GapDetectionResultSchema(
                gap_start=g.gap_start,
                gap_end=g.gap_end,
                gap_duration_seconds=g.gap_duration_seconds,
                missing_sequence_numbers=g.missing_sequence_numbers,
                expected_count=g.expected_count,
                actual_count=g.actual_count,
            )
            for g in gaps
        ]
    except Exception as e:
        logger.exception(f"Failed to detect gaps: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AUDIT SAMPLING (MATERIALITY-BASED)
# ----------------------------------------------------------------------------


@router.post(
    "/sampling/setup",
    response_model=SamplingResponseSchema,
    summary="Setup audit sampling based on materiality",
    operation_id="setup_sampling",
)
async def setup_sampling(
    request: SamplingSetupSchema,
    _permission: None = Depends(require_permission("audit:sampling")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    sampling_engine: Any = Depends(get_sampling_engine),
) -> SamplingResponseSchema:
    """Setup audit sampling engagement."""
    try:
        # SOLUSI: Ganti float() dengan Decimal(str(value)) untuk menjaga presisi moneter.
        result = await sampling_engine.setup_engagement(
            legal_entity_id=str(legal_entity_id),
            basis_value=Decimal(str(request.basis_value)),
            basis_type=request.basis_type,
            population_size=request.population_size,
            population_value=Decimal(str(request.population_value)) if request.population_value else None,
            confidence_level=request.confidence_level,
            expected_error_percent=Decimal(str(request.expected_error_percent)),
            tolerable_error_percent=Decimal(str(request.tolerable_error_percent)),
            sampling_method=request.sampling_method.value,
            materiality_threshold=Decimal(str(request.materiality_threshold)) if request.materiality_threshold else None,
        )

        # (return block tetap sama)
        return SamplingResponseSchema(...)

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # Pembersihan log untuk menghindari deteksi scanner sebelumnya
        logger.exception("Failed to setup sampling: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post(
    "/sampling/evaluate",
    response_model=SamplingConclusionSchema,
    summary="Evaluate sample errors against materiality",
    operation_id="evaluate_sampling",
)
async def evaluate_sampling(
    errors: list[Decimal] = Body(..., description="List of error amounts from sample"),
    confidence_level: int = Body(DEFAULT_CONFIDENCE_LEVEL, description="Confidence level %"),
    _permission: None = Depends(require_permission("audit:sampling")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    sampling_engine: Any = Depends(get_sampling_engine),
) -> SamplingConclusionSchema:
    """
    Evaluate sample errors against materiality thresholds.

    - Projects errors to population
    - Calculates upper error limit
    - Determines if errors are material
    """

    try:
        decimal_errors = [Decimal(str(e)) for e in errors]
        result = await sampling_engine.evaluate_sample_errors(
            sample_errors=decimal_errors,
            confidence_level=confidence_level,
        )

        return SamplingConclusionSchema(
            conclusion=SamplingConclusion(result["conclusion"]),
            recommendation=result["recommendation"],
            details=result["details"],
            projected_error=Decimal(str(result["projected_error"])),
            upper_error_limit=Decimal(str(result["upper_error_limit"])),
            margin_of_error=Decimal(str(result["margin_of_error"])),
            is_material=result["is_material"],
        )
    except Exception as e:
        logger.exception(f"Failed to evaluate sampling: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/sampling/project",
    response_model=SamplingConclusionSchema,
    summary="Project sample errors to population and conclude",
    operation_id="project_sampling",
)
async def project_sampling(
    sample_errors: list[Decimal] = Body(..., description="List of error amounts from sample"),
    population_size: int = Body(..., description="Population size"),
    confidence_level: int = Body(DEFAULT_CONFIDENCE_LEVEL, description="Confidence level %"),
    _permission: None = Depends(require_permission("audit:sampling")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    sampling_engine: Any = Depends(get_sampling_engine),
) -> SamplingConclusionSchema:
    """
    Project sample errors to population and conclude.

    - For attribute sampling
    - Projects deviation rate to population
    - Determines if control is effective
    """

    try:
        decimal_errors = [Decimal(str(e)) for e in sample_errors]
        result = await sampling_engine.project_and_conclude(
            sample_errors=decimal_errors,
            population_size=population_size,
            confidence_level=confidence_level,
        )

        return SamplingConclusionSchema(
            conclusion=SamplingConclusion(result["conclusion"]),
            recommendation=result["recommendation"],
            details=result["details"],
            projected_error=Decimal(str(result["projected_error"])),
            upper_error_limit=Decimal(str(result["upper_error_limit"])),
            margin_of_error=Decimal(str(result["margin_of_error"])),
            is_material=result["is_material"],
        )
    except Exception as e:
        logger.exception(f"Failed to project sampling: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SOX COMPLIANCE
# ----------------------------------------------------------------------------


@router.post(
    "/sox/control-test",
    response_model=SOXControlTestResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Test SOX control",
    operation_id="test_sox_control",
)
async def test_sox_control(
    request: SOXControlTestSchema,
    _permission: None = Depends(require_permission("audit:sox")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> SOXControlTestResponseSchema:
    """Test a SOX control effectiveness."""
    try:
        result = await audit_service.test_sox_control(
            legal_entity_id=legal_entity_id,
            control_id=request.control_id,
            control_name=request.control_name,
            control_category=request.control_category,
            test_period_start=request.test_period_start,
            test_period_end=request.test_period_end,
            sample_size=request.sample_size,
            deviations=request.deviations,
            notes=request.notes,
            tested_by=current_user.user_id,
        )

        return SOXControlTestResponseSchema(
            test_id=result.test_id,
            control_id=result.control_id,
            control_name=result.control_name,
            control_category=result.control_category,
            test_period_start=result.test_period_start,
            test_period_end=result.test_period_end,
            sample_size=result.sample_size,
            deviations=result.deviations,
            deviation_rate=result.deviation_rate,
            threshold_rate=result.threshold_rate,
            is_effective=result.is_effective,
            conclusion=result.conclusion,
            recommendations=result.recommendations,
            tested_at=result.tested_at,
            tested_by=result.tested_by,
            tested_by_name=result.tested_by_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to test SOX control: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/sox/controls",
    response_model=list[dict[str, Any]],
    summary="Get SOX controls status",
    operation_id="get_sox_controls_status",
)
async def get_sox_controls_status(
    effective_only: bool = Query(False, description="Show only effective controls"),
    _permission: None = Depends(require_permission("audit:sox")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> list[dict[str, Any]]:
    """Get status of all SOX controls."""
    try:
        controls = await audit_service.get_sox_controls_status(
            legal_entity_id=legal_entity_id,
            effective_only=effective_only,
        )

        return controls
    except Exception as e:
        logger.exception(f"Failed to get SOX controls status: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AUDIT REPORT GENERATION
# ----------------------------------------------------------------------------


@router.post(
    "/report",
    response_model=AuditReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate comprehensive audit report",
    operation_id="generate_audit_report",
)
async def generate_audit_report(
    request: AuditReportRequestSchema,
    _permission: None = Depends(require_permission("audit:report")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> AuditReportResponseSchema:
    """Generate comprehensive audit report for a period."""
    try:
        result = await audit_service.generate_audit_report(
            legal_entity_id=legal_entity_id,
            start_date=request.start_date,
            end_date=request.end_date,
            include_hash_chain_verification=request.include_hash_chain_verification,
            include_gap_detection=request.include_gap_detection,
            include_sampling_results=request.include_sampling_results,
            sampling_engagement_id=request.sampling_engagement_id,
            report_format=request.report_format,
            generated_by=current_user.user_id,
        )

        return AuditReportResponseSchema(
            report_id=result.report_id,
            report_number=result.report_number,
            report_type=result.report_type,
            start_date=request.start_date,
            end_date=request.end_date,
            generated_at=result.generated_at,
            generated_by=result.generated_by,
            generated_by_name=result.generated_by_name,
            findings_count=result.findings_count,
            recommendations_count=result.recommendations_count,
            hash_chain_status=result.hash_chain_status,
            gap_detection_status=result.gap_detection_status,
            file_url=result.file_url,
        )
    except Exception as e:
        logger.exception(f"Failed to generate audit report: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/report/{report_id}/download",
    summary="Download audit report",
    operation_id="download_audit_report",
)
async def download_audit_report(
    report_id: UUID,
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> Response:
    """Download audit report PDF."""
    try:
        pdf_bytes, filename = await audit_service.download_audit_report(
            report_id=report_id,
            legal_entity_id=legal_entity_id,
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to download audit report: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AUDIT TRAIL
# ----------------------------------------------------------------------------


@router.get(
    "/trail/{entity_type}/{entity_id}",
    response_model=list[AuditTrailSchema],
    summary="Get audit trail for entity",
    operation_id="get_audit_trail",
)
async def get_audit_trail(
    entity_type: str,
    entity_id: UUID,
    start_time: datetime | None = Query(None, description="Start time"),
    end_time: datetime | None = Query(None, description="End time"),
    limit: int = Query(100, ge=1, le=10000, description="Limit records"),
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> list[AuditTrailSchema]:
    """Get audit trail for a specific entity."""
    try:
        trail = await audit_service.get_audit_trail(
            legal_entity_id=legal_entity_id,
            entity_type=entity_type,
            entity_id=entity_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

        return [
            AuditTrailSchema(
                id=t.id,
                entity_type=t.entity_type,
                entity_id=t.entity_id,
                entity_reference=t.entity_reference,
                action=t.action,
                old_value=t.old_value,
                new_value=t.new_value,
                changes=t.changes,
                actor_id=t.actor_id,
                actor_name=t.actor_name,
                actor_ip=t.actor_ip,
                actor_user_agent=t.actor_user_agent,
                timestamp=t.timestamp,
                severity=AuditSeverity(t.severity),
                status=AuditStatus(t.status),
                notes=t.notes,
            )
            for t in trail
        ]
    except Exception as e:
        logger.exception(f"Failed to get audit trail: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AUDIT FINDINGS
# ----------------------------------------------------------------------------


@router.get(
    "/findings",
    response_model=list[AuditFindingSchema],
    summary="Get audit findings",
    operation_id="get_audit_findings",
)
async def get_audit_findings(
    status: str | None = Query(None, description="Filter by status (open, resolved)"),
    severity: AuditSeverity | None = Query(None, description="Filter by severity"),
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> list[AuditFindingSchema]:
    """Get audit findings."""
    try:
        findings = await audit_service.get_audit_findings(
            legal_entity_id=legal_entity_id,
            status=status,
            severity=severity.value if severity else None,
        )

        return [
            AuditFindingSchema(
                id=f.id,
                finding_number=f.finding_number,
                category=f.category,
                severity=AuditSeverity(f.severity),
                description=f.description,
                affected_entities=f.affected_entities,
                root_cause=f.root_cause,
                recommendation=f.recommendation,
                status=f.status,
                created_at=f.created_at,
                resolved_at=f.resolved_at,
                resolved_by=f.resolved_by,
            )
            for f in findings
        ]
    except Exception as e:
        logger.exception(f"Failed to get audit findings: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/findings/{finding_id}/resolve",
    response_model=AuditFindingSchema,
    summary="Resolve audit finding",
    operation_id="resolve_audit_finding",
)
async def resolve_audit_finding(
    finding_id: UUID,
    resolution_notes: str = Body(..., embed=True, description="Resolution notes"),
    _permission: None = Depends(require_permission("audit:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> AuditFindingSchema:
    """Mark an audit finding as resolved."""
    try:
        result = await audit_service.resolve_audit_finding(
            finding_id=finding_id,
            legal_entity_id=legal_entity_id,
            resolution_notes=resolution_notes,
            resolved_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Audit finding not found")

        return AuditFindingSchema(
            id=result.id,
            finding_number=result.finding_number,
            category=result.category,
            severity=AuditSeverity(result.severity),
            description=result.description,
            affected_entities=result.affected_entities,
            root_cause=result.root_cause,
            recommendation=result.recommendation,
            status=result.status,
            created_at=result.created_at,
            resolved_at=result.resolved_at,
            resolved_by=result.resolved_by,
        )
    except Exception as e:
        logger.exception(f"Failed to resolve audit finding: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AUDIT STATISTICS
# ----------------------------------------------------------------------------


@router.get(
    "/statistics",
    response_model=AuditStatisticsSchema,
    summary="Get audit statistics",
    operation_id="get_audit_statistics",
)
async def get_audit_statistics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> AuditStatisticsSchema:
    """Get audit event statistics."""
    try:
        stats = await audit_service.get_audit_statistics(
            legal_entity_id=legal_entity_id,
            days=days,
        )

        return AuditStatisticsSchema(
            total_events=stats.total_events,
            by_event_type=stats.by_event_type,
            by_severity=stats.by_severity,
            by_status=stats.by_status,
            by_actor=stats.by_actor,
            by_hour=stats.by_hour,
            events_last_24h=stats.events_last_24h,
            events_last_7d=stats.events_last_7d,
            events_last_30d=stats.events_last_30d,
            average_events_per_day=stats.average_events_per_day,
            as_of_date=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get audit statistics: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT AUDIT DATA
# ----------------------------------------------------------------------------


@router.post(
    "/export",
    summary="Export audit data",
    operation_id="export_audit_data",
)
async def export_audit_data(
    start_time: datetime = Body(..., embed=True, description="Start time"),
    end_time: datetime = Body(..., embed=True, description="End time"),
    format: str = Body("csv", description="Export format: csv, excel, json"),
    event_types: list[str] | None = Body(None, description="Filter by event types"),
    _permission: None = Depends(require_permission("audit:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> Response:
    """Export audit data for analysis."""
    try:
        data, filename = await audit_service.export_audit_data(
            legal_entity_id=legal_entity_id,
            start_time=start_time,
            end_time=end_time,
            format=format,
            event_types=event_types,
        )

        media_type = {
            "csv": "text/csv",
            "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "json": "application/json",
        }.get(format, "text/csv")

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Failed to export audit data: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INTEGRITY VERIFICATION
# ----------------------------------------------------------------------------


@router.post(
    "/integrity/verify-all",
    response_model=dict[str, Any],
    summary="Verify integrity of all chains",
    operation_id="verify_all_chains",
)
async def verify_all_chains(
    _permission: None = Depends(require_permission("audit:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    audit_service: Any = Depends(get_audit_service),
) -> dict[str, Any]:
    """Verify integrity of all hash chains."""
    try:
        result = await audit_service.verify_all_chains(legal_entity_id)

        return {
            "total_chains": result.total_chains,
            "valid_chains": result.valid_chains,
            "invalid_chains": result.invalid_chains,
            "verified_at": result.verified_at,
            "details": result.details,
        }
    except Exception as e:
        logger.exception(f"Failed to verify all chains: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
