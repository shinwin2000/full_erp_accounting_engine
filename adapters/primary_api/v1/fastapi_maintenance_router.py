#!/usr/bin/env python3
"""
Module: fastapi_maintenance_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan endpoint administratif untuk maintenance sistem:
               cache flushing, outbox processing, health checks terperinci,
               maintenance mode, reload konfigurasi, task monitoring,
               database maintenance, event store management, backup & restore,
               dan system diagnostics.

Method Standards (ERP):
- enable_maintenance_mode() / disable_maintenance_mode()
- get_maintenance_status() / get_system_health()
- flush_cache() / clear_all_caches() / get_cache_stats()
- process_outbox() / retry_failed_outbox() / get_outbox_stats()
- reload_configuration() / get_configuration_status()
- get_active_tasks() / cancel_task() / revoke_task()
- run_database_maintenance() / vacuum_database() / analyze_database()
- rebuild_projections() / refresh_materialized_views()
- create_backup() / restore_backup() / get_backup_status()
- get_system_metrics() / get_performance_stats()
- get_event_store_stats() / compact_event_store() / replay_events()
- run_diagnostics() / get_system_info()
- audit_trail_maintenance() / get_maintenance_history()
- register_maintenance_event() / get_maintenance_events()
- version_maintenance_record()
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class MaintenanceAction(str, Enum):
    """Jenis action maintenance."""

    CACHE_FLUSH = "cache_flush"
    OUTBOX_PROCESS = "outbox_process"
    OUTBOX_RETRY = "outbox_retry"
    CONFIG_RELOAD = "config_reload"
    DB_VACUUM = "db_vacuum"
    DB_ANALYZE = "db_analyze"
    DB_REINDEX = "db_reindex"
    PROJECTION_REBUILD = "projection_rebuild"
    BACKUP_CREATE = "backup_create"
    BACKUP_RESTORE = "backup_restore"
    MAINTENANCE_MODE_ON = "maintenance_mode_on"
    MAINTENANCE_MODE_OFF = "maintenance_mode_off"
    TASK_CANCEL = "task_cancel"
    HEALTH_CHECK = "health_check"
    EVENT_STORE_COMPACT = "event_store_compact"
    EVENT_STORE_REPLAY = "event_store_replay"
    SYSTEM_DIAGNOSTICS = "system_diagnostics"


class MaintenanceStatus(str, Enum):
    """Status maintenance."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackupType(str, Enum):
    """Jenis backup."""

    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"
    SCHEMA_ONLY = "schema_only"
    DATA_ONLY = "data_only"


class BackupFormat(str, Enum):
    """Format backup."""

    SQL = "sql"
    DUMP = "dump"
    TAR = "tar"
    JSON = "json"


class DiagnosticLevel(str, Enum):
    """Level diagnostic."""

    BASIC = "basic"
    STANDARD = "standard"
    DETAILED = "detailed"
    FULL = "full"


# Default maintenance settings
DEFAULT_CACHE_PATTERNS = ["*"]
DEFAULT_OUTBOX_BATCH_SIZE = 100
DEFAULT_BACKUP_RETENTION_DAYS = 30
HEALTH_CHECK_TIMEOUT_SECONDS = 30
DIAGNOSTIC_TIMEOUT_SECONDS = 60


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class MaintenanceModeSchema(BaseModel):
    """Schema untuk maintenance mode."""

    model_config = ConfigDict(from_attributes=True)

    enabled: bool = Field(..., description="Enable or disable maintenance mode")
    message: str | None = Field(None, max_length=500, description="Message to display")
    estimated_duration_minutes: int | None = Field(
        None, ge=1, le=1440, description="Estimated duration"
    )
    allow_ips: list[str] | None = Field(None, description="Allowed IPs during maintenance")
    allow_roles: list[str] | None = Field(None, description="Allowed roles during maintenance")


class MaintenanceStatusSchema(BaseModel):
    """Response status maintenance."""

    model_config = ConfigDict(from_attributes=True)

    maintenance_mode: bool
    started_at: datetime | None
    message: str | None
    estimated_end_at: datetime | None
    allow_ips: list[str] | None
    allow_roles: list[str] | None
    active_tasks: int
    pending_maintenances: int


class HealthDetailSchema(BaseModel):
    """Response detail health check."""

    model_config = ConfigDict(from_attributes=True)

    component: str
    status: str  # healthy, degraded, unhealthy
    latency_ms: float | None
    details: dict[str, Any] | None
    checked_at: datetime = Field(default_factory=datetime.now)


class CacheFlushSchema(BaseModel):
    """Schema untuk flush cache."""

    model_config = ConfigDict(from_attributes=True)

    pattern: str | None = Field(None, description="Key pattern to flush (e.g., 'journal:*')")
    dry_run: bool = Field(False, description="Only count keys, don't delete")


class CacheFlushResponseSchema(BaseModel):
    """Response flush cache."""

    model_config = ConfigDict(from_attributes=True)

    keys_deleted: int
    patterns_used: list[str]
    duration_ms: float
    dry_run: bool


class OutboxProcessSchema(BaseModel):
    """Schema untuk proses outbox."""

    model_config = ConfigDict(from_attributes=True)

    batch_size: int = Field(DEFAULT_OUTBOX_BATCH_SIZE, ge=1, le=1000, description="Batch size")
    max_retries: int = Field(3, ge=1, le=10, description="Max retry attempts")
    dry_run: bool = Field(False, description="Only simulate, don't actually process")


class OutboxStatsSchema(BaseModel):
    """Response stats outbox."""

    model_config = ConfigDict(from_attributes=True)

    pending_count: int
    processing_count: int
    failed_count: int
    dead_letter_count: int
    processed_last_hour: int
    processed_last_24h: int
    average_latency_ms: float
    last_successful_run: datetime | None
    last_failed_run: datetime | None


class OutboxProcessResponseSchema(BaseModel):
    """Response proses outbox."""

    model_config = ConfigDict(from_attributes=True)

    processed_count: int
    success_count: int
    failed_count: int
    duration_ms: float
    errors: list[dict[str, Any]] = []


class DatabaseMaintenanceSchema(BaseModel):
    """Schema untuk database maintenance."""

    model_config = ConfigDict(from_attributes=True)

    vacuum: bool = Field(True, description="Run VACUUM")
    analyze: bool = Field(True, description="Run ANALYZE")
    reindex: bool = Field(False, description="Run REINDEX")
    tables: list[str] | None = Field(None, description="Specific tables (empty = all)")
    full_vacuum: bool = Field(False, description="Full VACUUM (requires more locks)")


class DatabaseMaintenanceResponseSchema(BaseModel):
    """Response database maintenance."""

    model_config = ConfigDict(from_attributes=True)

    vacuum_completed: bool
    analyze_completed: bool
    reindex_completed: bool
    tables_processed: list[str]
    duration_ms: float
    details: dict[str, Any] | None


class BackupCreateSchema(BaseModel):
    """Schema untuk membuat backup."""

    model_config = ConfigDict(from_attributes=True)

    backup_type: BackupType = Field(BackupType.FULL, description="Jenis backup")
    backup_format: BackupFormat = Field(BackupFormat.DUMP, description="Format backup")
    include_blobs: bool = Field(True, description="Include blob storage")
    compress: bool = Field(True, description="Compress backup")
    tables: list[str] | None = Field(None, description="Specific tables (empty = all)")
    notes: str | None = Field(None, max_length=500)


class BackupResponseSchema(BaseModel):
    """Response backup."""

    model_config = ConfigDict(from_attributes=True)

    backup_id: UUID
    backup_number: str
    backup_type: BackupType
    backup_format: BackupFormat
    file_size_bytes: int
    file_path: str
    includes_blobs: bool
    is_compressed: bool
    status: str
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    expiry_date: datetime | None = None


class BackupListResponseSchema(BaseModel):
    """Response list backup."""

    model_config = ConfigDict(from_attributes=True)

    items: list[BackupResponseSchema]
    total: int
    total_size_bytes: int
    page: int
    page_size: int


class RestoreBackupSchema(BaseModel):
    """Schema untuk restore backup."""

    model_config = ConfigDict(from_attributes=True)

    backup_id: UUID = Field(..., description="Backup ID to restore")
    restore_blobs: bool = Field(True, description="Restore blob storage")
    drop_existing: bool = Field(False, description="Drop existing data before restore")
    dry_run: bool = Field(False, description="Only validate, don't actually restore")


class RestoreBackupResponseSchema(BaseModel):
    """Response restore backup."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    backup_id: UUID
    restored_at: datetime
    restored_by: UUID
    tables_restored: int
    blobs_restored: int
    duration_ms: float
    message: str


class ProjectionRebuildSchema(BaseModel):
    """Schema untuk rebuild projection."""

    model_config = ConfigDict(from_attributes=True)

    projection_name: str | None = Field(None, description="Specific projection name (empty = all)")
    from_scratch: bool = Field(False, description="Rebuild from scratch (clear first)")
    batch_size: int = Field(1000, ge=100, le=10000, description="Batch size")
    parallel_workers: int = Field(4, ge=1, le=16, description="Parallel workers")


class ProjectionRebuildResponseSchema(BaseModel):
    """Response rebuild projection."""

    model_config = ConfigDict(from_attributes=True)

    projection_name: str
    events_processed: int
    records_created: int
    records_updated: int
    duration_ms: float
    status: str
    errors: list[str] = []


class SystemMetricsResponseSchema(BaseModel):
    """Response system metrics."""

    model_config = ConfigDict(from_attributes=True)

    cpu_usage_percent: float
    memory_usage_percent: float
    disk_usage_percent: float
    database_connections: int
    redis_connections: int
    kafka_lag: int
    active_workers: int
    queue_size: int
    uptime_seconds: float
    version: str
    timestamp: datetime


class ActiveTaskSchema(BaseModel):
    """Response active task."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    task_name: str
    started_at: datetime
    running_for_seconds: float
    status: str
    progress_percent: float | None
    details: dict[str, Any] | None


class MaintenanceHistorySchema(BaseModel):
    """Response history maintenance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action: MaintenanceAction
    status: MaintenanceStatus
    started_at: datetime
    completed_at: datetime | None
    duration_ms: float | None
    details: dict[str, Any] | None
    error: str | None
    performed_by: UUID
    performed_by_name: str | None = None


class EventStoreStatsSchema(BaseModel):
    """Response event store statistics."""

    model_config = ConfigDict(from_attributes=True)

    total_events: int
    total_streams: int
    total_size_bytes: int
    average_event_size_bytes: float
    oldest_event_at: datetime | None
    newest_event_at: datetime | None
    events_by_type: dict[str, int]
    events_by_hour: dict[str, int]
    storage_engine: str


class EventStoreReplaySchema(BaseModel):
    """Schema untuk replay event store."""

    model_config = ConfigDict(from_attributes=True)

    stream_name: str | None = Field(None, description="Specific stream to replay")
    start_time: datetime | None = Field(None, description="Start time")
    end_time: datetime | None = Field(None, description="End time")
    target_handler: str = Field("all", description="Target handler for replay")
    dry_run: bool = Field(False, description="Only simulate")


class EventStoreReplayResponseSchema(BaseModel):
    """Response replay event store."""

    model_config = ConfigDict(from_attributes=True)

    events_replayed: int
    events_skipped: int
    handlers_triggered: int
    duration_ms: float
    status: str
    errors: list[str] = []


class SystemDiagnosticsSchema(BaseModel):
    """Response system diagnostics."""

    model_config = ConfigDict(from_attributes=True)

    system_info: dict[str, Any]
    python_info: dict[str, Any]
    dependencies: dict[str, str]
    configuration: dict[str, Any]
    connections: dict[str, Any]
    performance: dict[str, Any]
    warnings: list[str]
    errors: list[str]
    generated_at: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_maintenance_service() -> Any:
    """Get Maintenance Service instance."""
    from application.service_layer.service_maintenance import MaintenanceService

    from infrastructure.dependency_container.ioc_container import get_container

    container = get_container()
    return container.resolve(MaintenanceService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/admin", tags=["Administration"])

# In-memory maintenance mode flag (bisa juga disimpan di Redis)
_maintenance_mode = False
_maintenance_started_at = None
_maintenance_message = None
_maintenance_allow_ips = None
_maintenance_allow_roles = None
_maintenance_estimated_end_at = None


# ----------------------------------------------------------------------------
# MAINTENANCE MODE
# ----------------------------------------------------------------------------


@router.get(
    "/maintenance",
    response_model=MaintenanceStatusSchema,
    summary="Get maintenance mode status",
    operation_id="get_maintenance_status",
)
async def get_maintenance_status(
    _permission: None = Depends(require_permission("admin:maintenance")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> MaintenanceStatusSchema:
    """Get current maintenance mode status."""
    try:
        status = await maintenance_service.get_maintenance_status()

        return MaintenanceStatusSchema(
            maintenance_mode=status.maintenance_mode,
            started_at=status.started_at,
            message=status.message,
            estimated_end_at=status.estimated_end_at,
            allow_ips=status.allow_ips,
            allow_roles=status.allow_roles,
            active_tasks=status.active_tasks,
            pending_maintenances=status.pending_maintenances,
        )
    except Exception as e:
        logger.exception(f"Failed to get maintenance status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/maintenance",
    response_model=MaintenanceStatusSchema,
    summary="Enable or disable maintenance mode",
    operation_id="set_maintenance_mode",
)
async def set_maintenance_mode(
    request: MaintenanceModeSchema,
    _permission: None = Depends(require_permission("admin:maintenance")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> MaintenanceStatusSchema:
    """Enable or disable maintenance mode."""
    try:
        if request.enabled:
            result = await maintenance_service.enable_maintenance_mode(
                message=request.message,
                estimated_duration_minutes=request.estimated_duration_minutes,
                allow_ips=request.allow_ips,
                allow_roles=request.allow_roles,
                enabled_by=current_user.user_id,
            )
            logger.warning(f"Maintenance mode enabled by {current_user.username}")
        else:
            result = await maintenance_service.disable_maintenance_mode(
                disabled_by=current_user.user_id,
            )
            logger.warning(f"Maintenance mode disabled by {current_user.username}")

        return MaintenanceStatusSchema(
            maintenance_mode=result.maintenance_mode,
            started_at=result.started_at,
            message=result.message,
            estimated_end_at=result.estimated_end_at,
            allow_ips=result.allow_ips,
            allow_roles=result.allow_roles,
            active_tasks=result.active_tasks,
            pending_maintenances=result.pending_maintenances,
        )
    except Exception as e:
        logger.exception(f"Failed to set maintenance mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------------
# HEALTH CHECK DETAILED
# ----------------------------------------------------------------------------


@router.get(
    "/health/detailed",
    response_model=list[HealthDetailSchema],
    summary="Detailed health check of all components",
    operation_id="detailed_health_check",
)
async def detailed_health_check(
    _permission: None = Depends(require_permission("admin:health")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> list[HealthDetailSchema]:
    """Check health of all system components."""
    try:
        results = await maintenance_service.detailed_health_check()

        return [
            HealthDetailSchema(
                component=r.component,
                status=r.status,
                latency_ms=r.latency_ms,
                details=r.details,
                checked_at=r.checked_at,
            )
            for r in results
        ]
    except Exception as e:
        logger.exception(f"Failed to get detailed health: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/health/readiness",
    response_model=dict[str, Any],
    summary="Readiness probe",
    operation_id="readiness_probe",
)
async def readiness_probe(
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Kubernetes readiness probe."""
    try:
        is_ready = await maintenance_service.is_ready()

        if not is_ready:
            raise HTTPException(status_code=503, detail="System not ready")

        return {
            "status": "ready",
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Readiness probe failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@router.get(
    "/health/liveness",
    response_model=dict[str, Any],
    summary="Liveness probe",
    operation_id="liveness_probe",
)
async def liveness_probe() -> dict[str, Any]:
    """Kubernetes liveness probe."""
    return {
        "status": "alive",
        "timestamp": datetime.now().isoformat(),
    }


@router.get(
    "/health/startup",
    response_model=dict[str, Any],
    summary="Startup probe",
    operation_id="startup_probe",
)
async def startup_probe(
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Kubernetes startup probe."""
    try:
        is_started = await maintenance_service.is_started()

        if not is_started:
            raise HTTPException(status_code=503, detail="System not fully started")

        return {
            "status": "started",
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Startup probe failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


# ----------------------------------------------------------------------------
# CACHE MANAGEMENT
# ----------------------------------------------------------------------------


@router.post(
    "/cache/flush",
    response_model=CacheFlushResponseSchema,
    summary="Flush cache",
    operation_id="flush_cache",
)
async def flush_cache(
    request: CacheFlushSchema,
    _permission: None = Depends(require_permission("admin:cache")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> CacheFlushResponseSchema:
    """Flush Redis cache (by pattern or all)."""
    try:
        start_time = time.time()

        result = await maintenance_service.flush_cache(
            pattern=request.pattern,
            dry_run=request.dry_run,
            performed_by=current_user.user_id,
        )

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Cache flush completed: {result.keys_deleted} keys deleted by {current_user.username}"
        )

        return CacheFlushResponseSchema(
            keys_deleted=result.keys_deleted,
            patterns_used=result.patterns_used,
            duration_ms=duration_ms,
            dry_run=request.dry_run,
        )
    except Exception as e:
        logger.exception(f"Failed to flush cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/cache/stats",
    response_model=dict[str, Any],
    summary="Get cache statistics",
    operation_id="get_cache_stats",
)
async def get_cache_stats(
    _permission: None = Depends(require_permission("admin:cache")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Get Redis cache statistics."""
    try:
        stats = await maintenance_service.get_cache_stats()

        return {
            "total_keys": stats.total_keys,
            "memory_usage_bytes": stats.memory_usage_bytes,
            "hit_rate": stats.hit_rate,
            "miss_rate": stats.miss_rate,
            "evicted_keys": stats.evicted_keys,
            "expired_keys": stats.expired_keys,
            "connected_clients": stats.connected_clients,
            "uptime_seconds": stats.uptime_seconds,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.exception(f"Failed to get cache stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# OUTBOX MANAGEMENT
# ----------------------------------------------------------------------------


@router.get(
    "/outbox/stats",
    response_model=OutboxStatsSchema,
    summary="Get outbox processing statistics",
    operation_id="get_outbox_stats",
)
async def get_outbox_stats(
    _permission: None = Depends(require_permission("admin:outbox")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> OutboxStatsSchema:
    """Get outbox processing statistics."""
    try:
        stats = await maintenance_service.get_outbox_stats()

        return OutboxStatsSchema(
            pending_count=stats.pending_count,
            processing_count=stats.processing_count,
            failed_count=stats.failed_count,
            dead_letter_count=stats.dead_letter_count,
            processed_last_hour=stats.processed_last_hour,
            processed_last_24h=stats.processed_last_24h,
            average_latency_ms=stats.average_latency_ms,
            last_successful_run=stats.last_successful_run,
            last_failed_run=stats.last_failed_run,
        )
    except Exception as e:
        logger.exception(f"Failed to get outbox stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/outbox/process",
    response_model=OutboxProcessResponseSchema,
    summary="Process outbox messages",
    operation_id="process_outbox",
)
async def process_outbox(
    request: OutboxProcessSchema,
    _permission: None = Depends(require_permission("admin:outbox")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> OutboxProcessResponseSchema:
    """Process pending outbox messages."""
    try:
        start_time = time.time()

        result = await maintenance_service.process_outbox(
            batch_size=request.batch_size,
            max_retries=request.max_retries,
            dry_run=request.dry_run,
            performed_by=current_user.user_id,
        )

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Outbox processed: {result.processed_count} messages by {current_user.username}"
        )

        return OutboxProcessResponseSchema(
            processed_count=result.processed_count,
            success_count=result.success_count,
            failed_count=result.failed_count,
            duration_ms=duration_ms,
            errors=result.errors,
        )
    except Exception as e:
        logger.exception(f"Failed to process outbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/outbox/retry-failed",
    response_model=OutboxProcessResponseSchema,
    summary="Retry failed outbox messages",
    operation_id="retry_failed_outbox",
)
async def retry_failed_outbox(
    max_retries: int = Query(3, ge=1, le=10, description="Max retry attempts"),
    _permission: None = Depends(require_permission("admin:outbox")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> OutboxProcessResponseSchema:
    """Retry failed outbox messages."""
    try:
        start_time = time.time()

        result = await maintenance_service.retry_failed_outbox(
            max_retries=max_retries,
            performed_by=current_user.user_id,
        )

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Failed outbox retry: {result.processed_count} messages by {current_user.username}"
        )

        return OutboxProcessResponseSchema(
            processed_count=result.processed_count,
            success_count=result.success_count,
            failed_count=result.failed_count,
            duration_ms=duration_ms,
            errors=result.errors,
        )
    except Exception as e:
        logger.exception(f"Failed to retry outbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------------
# CONFIGURATION MANAGEMENT
# ----------------------------------------------------------------------------


@router.post(
    "/config/reload",
    response_model=dict[str, Any],
    summary="Reload configuration from YAML",
    operation_id="reload_config",
)
async def reload_configuration(
    _permission: None = Depends(require_permission("admin:config")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Reload configuration from YAML files."""
    try:
        result = await maintenance_service.reload_configuration(
            reloaded_by=current_user.user_id,
        )

        logger.info(f"Configuration reloaded by {current_user.username}")

        return {
            "success": result.success,
            "files_reloaded": result.files_reloaded,
            "errors": result.errors,
            "message": "Configuration reloaded successfully",
        }
    except Exception as e:
        logger.exception(f"Failed to reload configuration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/config/status",
    response_model=dict[str, Any],
    summary="Get configuration status",
    operation_id="get_config_status",
)
async def get_config_status(
    _permission: None = Depends(require_permission("admin:config")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Get configuration status and versions."""
    try:
        status = await maintenance_service.get_config_status()

        return {
            "config_version": status.config_version,
            "last_loaded_at": status.last_loaded_at.isoformat() if status.last_loaded_at else None,
            "last_reloaded_at": status.last_reloaded_at.isoformat()
            if status.last_reloaded_at
            else None,
            "files": status.files,
            "environment": status.environment,
            "is_dirty": status.is_dirty,
        }
    except Exception as e:
        logger.exception(f"Failed to get config status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# DATABASE MAINTENANCE
# ----------------------------------------------------------------------------


@router.post(
    "/database/maintenance",
    response_model=DatabaseMaintenanceResponseSchema,
    summary="Run database maintenance",
    operation_id="run_db_maintenance",
)
async def run_database_maintenance(
    request: DatabaseMaintenanceSchema,
    _permission: None = Depends(require_permission("admin:database")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> DatabaseMaintenanceResponseSchema:
    """Run database maintenance (VACUUM, ANALYZE, REINDEX)."""
    try:
        start_time = time.time()

        result = await maintenance_service.run_database_maintenance(
            vacuum=request.vacuum,
            analyze=request.analyze,
            reindex=request.reindex,
            tables=request.tables,
            full_vacuum=request.full_vacuum,
            performed_by=current_user.user_id,
        )

        duration_ms = (time.time() - start_time) * 1000

        logger.info(f"Database maintenance completed by {current_user.username}")

        return DatabaseMaintenanceResponseSchema(
            vacuum_completed=result.vacuum_completed,
            analyze_completed=result.analyze_completed,
            reindex_completed=result.reindex_completed,
            tables_processed=result.tables_processed,
            duration_ms=duration_ms,
            details=result.details,
        )
    except Exception as e:
        logger.exception(f"Failed to run database maintenance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/database/stats",
    response_model=dict[str, Any],
    summary="Get database statistics",
    operation_id="get_db_stats",
)
async def get_database_stats(
    _permission: None = Depends(require_permission("admin:database")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Get database statistics (size, connections, etc.)."""
    try:
        stats = await maintenance_service.get_database_stats()

        return {
            "database_size_bytes": stats.database_size_bytes,
            "database_size_human": stats.database_size_human,
            "total_tables": stats.total_tables,
            "total_indexes": stats.total_indexes,
            "total_sequences": stats.total_sequences,
            "active_connections": stats.active_connections,
            "idle_connections": stats.idle_connections,
            "cache_hit_ratio": stats.cache_hit_ratio,
            "tup_inserted": stats.tup_inserted,
            "tup_updated": stats.tup_updated,
            "tup_deleted": stats.tup_deleted,
            "tup_returned": stats.tup_returned,
            "tup_fetched": stats.tup_fetched,
            "deadlocks": stats.deadlocks,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.exception(f"Failed to get database stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PROJECTION MANAGEMENT
# ----------------------------------------------------------------------------


@router.post(
    "/projections/rebuild",
    response_model=list[ProjectionRebuildResponseSchema],
    summary="Rebuild CQRS projections",
    operation_id="rebuild_projections",
)
async def rebuild_projections(
    request: ProjectionRebuildSchema,
    _permission: None = Depends(require_permission("admin:projections")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> list[ProjectionRebuildResponseSchema]:
    """Rebuild CQRS projections from event store."""
    try:
        results = await maintenance_service.rebuild_projections(
            projection_name=request.projection_name,
            from_scratch=request.from_scratch,
            batch_size=request.batch_size,
            parallel_workers=request.parallel_workers,
            performed_by=current_user.user_id,
        )

        logger.info(
            f"Projections rebuilt by {current_user.username}: {len(results)} projections"
        )

        return [
            ProjectionRebuildResponseSchema(
                projection_name=r.projection_name,
                events_processed=r.events_processed,
                records_created=r.records_created,
                records_updated=r.records_updated,
                duration_ms=r.duration_ms,
                status=r.status,
                errors=r.errors,
            )
            for r in results
        ]
    except Exception as e:
        logger.exception(f"Failed to rebuild projections: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/projections/status",
    response_model=list[dict[str, Any]],
    summary="Get projection status",
    operation_id="get_projection_status",
)
async def get_projection_status(
    _permission: None = Depends(require_permission("admin:projections")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> list[dict[str, Any]]:
    """Get status of all CQRS projections."""
    try:
        statuses = await maintenance_service.get_projection_status()

        return [
            {
                "name": s.name,
                "status": s.status,
                "last_processed_event_id": str(s.last_processed_event_id)
                if s.last_processed_event_id
                else None,
                "last_processed_at": s.last_processed_at.isoformat()
                if s.last_processed_at
                else None,
                "events_behind": s.events_behind,
                "lag_seconds": s.lag_seconds,
                "error_count": s.error_count,
                "last_error": s.last_error,
            }
            for s in statuses
        ]
    except Exception as e:
        logger.exception(f"Failed to get projection status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BACKUP MANAGEMENT
# ----------------------------------------------------------------------------


@router.post(
    "/backup",
    response_model=BackupResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create database backup",
    operation_id="create_backup",
)
async def create_backup(
    request: BackupCreateSchema,
    _permission: None = Depends(require_permission("admin:backup")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> BackupResponseSchema:
    """Create a database backup."""
    try:
        result = await maintenance_service.create_backup(
            backup_type=request.backup_type.value,
            backup_format=request.backup_format.value,
            include_blobs=request.include_blobs,
            compress=request.compress,
            tables=request.tables,
            notes=request.notes,
            created_by=current_user.user_id,
        )

        logger.info(f"Backup created by {current_user.username}: {result.backup_number}")

        return BackupResponseSchema(
            backup_id=result.backup_id,
            backup_number=result.backup_number,
            backup_type=BackupType(result.backup_type),
            backup_format=BackupFormat(result.backup_format),
            file_size_bytes=result.file_size_bytes,
            file_path=result.file_path,
            includes_blobs=result.includes_blobs,
            is_compressed=result.is_compressed,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            expiry_date=result.expiry_date,
        )
    except Exception as e:
        logger.exception(f"Failed to create backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/backup",
    response_model=BackupListResponseSchema,
    summary="List backups",
    operation_id="list_backups",
)
async def list_backups(
    backup_type: BackupType | None = Query(None, description="Filter by type"),
    start_date: datetime | None = Query(None, description="Start date"),
    end_date: datetime | None = Query(None, description="End date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _permission: None = Depends(require_permission("admin:backup")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> BackupListResponseSchema:
    """List database backups."""
    try:
        result = await maintenance_service.list_backups(
            backup_type=backup_type.value if backup_type else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return BackupListResponseSchema(
            items=[
                BackupResponseSchema(
                    backup_id=b.id,
                    backup_number=b.backup_number,
                    backup_type=BackupType(b.backup_type),
                    backup_format=BackupFormat(b.backup_format),
                    file_size_bytes=b.file_size_bytes,
                    file_path=b.file_path,
                    includes_blobs=b.includes_blobs,
                    is_compressed=b.is_compressed,
                    status=b.status,
                    created_at=b.created_at,
                    created_by=b.created_by,
                    created_by_name=b.created_by_name,
                    expiry_date=b.expiry_date,
                )
                for b in result.items
            ],
            total=result.total,
            total_size_bytes=result.total_size_bytes,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.exception(f"Failed to list backups: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/backup/{backup_id}",
    response_model=BackupResponseSchema,
    summary="Get backup by ID",
    operation_id="get_backup",
)
async def get_backup(
    backup_id: UUID,
    _permission: None = Depends(require_permission("admin:backup")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> BackupResponseSchema:
    """Get backup by ID."""
    try:
        backup = await maintenance_service.get_backup_by_id(backup_id)

        if not backup:
            raise HTTPException(status_code=404, detail="Backup not found")

        return BackupResponseSchema(
            backup_id=backup.id,
            backup_number=backup.backup_number,
            backup_type=BackupType(backup.backup_type),
            backup_format=BackupFormat(backup.backup_format),
            file_size_bytes=backup.file_size_bytes,
            file_path=backup.file_path,
            includes_blobs=backup.includes_blobs,
            is_compressed=backup.is_compressed,
            status=backup.status,
            created_at=backup.created_at,
            created_by=backup.created_by,
            created_by_name=backup.created_by_name,
            expiry_date=backup.expiry_date,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get backup: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/backup/restore",
    response_model=RestoreBackupResponseSchema,
    summary="Restore from backup",
    operation_id="restore_backup",
)
async def restore_backup(
    request: RestoreBackupSchema,
    _permission: None = Depends(require_permission("admin:backup")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> RestoreBackupResponseSchema:
    """Restore database from backup."""
    try:
        start_time = time.time()

        result = await maintenance_service.restore_backup(
            backup_id=request.backup_id,
            restore_blobs=request.restore_blobs,
            drop_existing=request.drop_existing,
            dry_run=request.dry_run,
            restored_by=current_user.user_id,
        )

        duration_ms = (time.time() - start_time) * 1000

        logger.warning(
            f"Backup restored by {current_user.username}: {result.backup_id}"
        )

        return RestoreBackupResponseSchema(
            success=result.success,
            backup_id=request.backup_id,
            restored_at=datetime.now(),
            restored_by=current_user.user_id,
            tables_restored=result.tables_restored,
            blobs_restored=result.blobs_restored,
            duration_ms=duration_ms,
            message=result.message,
        )
    except Exception as e:
        logger.exception(f"Failed to restore backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/backup/{backup_id}",
    response_model=dict[str, Any],
    summary="Delete backup",
    operation_id="delete_backup",
)
async def delete_backup(
    backup_id: UUID,
    _permission: None = Depends(require_permission("admin:backup")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Delete a backup file."""
    try:
        result = await maintenance_service.delete_backup(
            backup_id=backup_id,
            deleted_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Backup not found")

        logger.info(f"Backup deleted by {current_user.username}: {backup_id}")

        return {
            "backup_id": str(backup_id),
            "deleted": True,
            "message": "Backup deleted successfully",
        }
    except Exception as e:
        logger.exception(f"Failed to delete backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------------
# EVENT STORE MANAGEMENT
# ----------------------------------------------------------------------------


@router.get(
    "/event-store/stats",
    response_model=EventStoreStatsSchema,
    summary="Get event store statistics",
    operation_id="get_event_store_stats",
)
async def get_event_store_stats(
    _permission: None = Depends(require_permission("admin:event_store")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> EventStoreStatsSchema:
    """Get event store statistics."""
    try:
        stats = await maintenance_service.get_event_store_stats()

        return EventStoreStatsSchema(
            total_events=stats.total_events,
            total_streams=stats.total_streams,
            total_size_bytes=stats.total_size_bytes,
            average_event_size_bytes=stats.average_event_size_bytes,
            oldest_event_at=stats.oldest_event_at,
            newest_event_at=stats.newest_event_at,
            events_by_type=stats.events_by_type,
            events_by_hour=stats.events_by_hour,
            storage_engine=stats.storage_engine,
        )
    except Exception as e:
        logger.exception(f"Failed to get event store stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/event-store/compact",
    response_model=dict[str, Any],
    summary="Compact event store",
    operation_id="compact_event_store",
)
async def compact_event_store(
    _permission: None = Depends(require_permission("admin:event_store")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Compact event store (remove old snapshots, merge events)."""
    try:
        result = await maintenance_service.compact_event_store(
            performed_by=current_user.user_id,
        )

        logger.info(f"Event store compacted by {current_user.username}")

        return {
            "snapshots_removed": result.snapshots_removed,
            "events_merged": result.events_merged,
            "space_saved_bytes": result.space_saved_bytes,
            "duration_ms": result.duration_ms,
            "message": "Event store compacted successfully",
        }
    except Exception as e:
        logger.exception(f"Failed to compact event store: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/event-store/replay",
    response_model=EventStoreReplayResponseSchema,
    summary="Replay events",
    operation_id="replay_events",
)
async def replay_events(
    request: EventStoreReplaySchema,
    _permission: None = Depends(require_permission("admin:event_store")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> EventStoreReplayResponseSchema:
    """Replay events from event store."""
    try:
        start_time = time.time()

        result = await maintenance_service.replay_events(
            stream_name=request.stream_name,
            start_time=request.start_time,
            end_time=request.end_time,
            target_handler=request.target_handler,
            dry_run=request.dry_run,
            performed_by=current_user.user_id,
        )

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Events replayed by {current_user.username}: {result.events_replayed} events"
        )

        return EventStoreReplayResponseSchema(
            events_replayed=result.events_replayed,
            events_skipped=result.events_skipped,
            handlers_triggered=result.handlers_triggered,
            duration_ms=duration_ms,
            status=result.status,
            errors=result.errors,
        )
    except Exception as e:
        logger.exception(f"Failed to replay events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------------
# SYSTEM DIAGNOSTICS
# ----------------------------------------------------------------------------


@router.post(
    "/diagnostics",
    response_model=SystemDiagnosticsSchema,
    summary="Run system diagnostics",
    operation_id="run_diagnostics",
)
async def run_diagnostics(
    level: DiagnosticLevel = Query(DiagnosticLevel.STANDARD, description="Diagnostic level"),
    _permission: None = Depends(require_permission("admin:diagnostics")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> SystemDiagnosticsSchema:
    """Run comprehensive system diagnostics."""
    try:
        result = await maintenance_service.run_diagnostics(
            level=level.value,
            performed_by=current_user.user_id,
        )

        logger.info(
            f"System diagnostics run by {current_user.username} (level: {level.value})"
        )

        return SystemDiagnosticsSchema(
            system_info=result.system_info,
            python_info=result.python_info,
            dependencies=result.dependencies,
            configuration=result.configuration,
            connections=result.connections,
            performance=result.performance,
            warnings=result.warnings,
            errors=result.errors,
            generated_at=result.generated_at,
        )
    except Exception as e:
        logger.exception(f"Failed to run diagnostics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------------
# SYSTEM METRICS
# ----------------------------------------------------------------------------


@router.get(
    "/metrics/system",
    response_model=SystemMetricsResponseSchema,
    summary="Get system metrics",
    operation_id="get_system_metrics",
)
async def get_system_metrics(
    _permission: None = Depends(require_permission("admin:metrics")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> SystemMetricsResponseSchema:
    """Get system metrics (CPU, memory, disk, etc.)."""
    try:
        metrics = await maintenance_service.get_system_metrics()

        return SystemMetricsResponseSchema(
            cpu_usage_percent=metrics.cpu_usage_percent,
            memory_usage_percent=metrics.memory_usage_percent,
            disk_usage_percent=metrics.disk_usage_percent,
            database_connections=metrics.database_connections,
            redis_connections=metrics.redis_connections,
            kafka_lag=metrics.kafka_lag,
            active_workers=metrics.active_workers,
            queue_size=metrics.queue_size,
            uptime_seconds=metrics.uptime_seconds,
            version=metrics.version,
            timestamp=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get system metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/metrics/export",
    summary="Export metrics (Prometheus format)",
    operation_id="export_metrics",
)
async def export_metrics(
    _permission: None = Depends(require_permission("admin:metrics")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> Response:
    """Export metrics in Prometheus format."""
    try:
        metrics_data = await maintenance_service.export_prometheus_metrics()

        return Response(
            content=metrics_data,
            media_type="text/plain",
            headers={"Content-Type": "text/plain"},
        )
    except Exception as e:
        logger.exception(f"Failed to export metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TASK MANAGEMENT
# ----------------------------------------------------------------------------


@router.get(
    "/tasks/active",
    response_model=list[ActiveTaskSchema],
    summary="Get active background tasks",
    operation_id="get_active_tasks",
)
async def get_active_tasks(
    _permission: None = Depends(require_permission("admin:tasks")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> list[ActiveTaskSchema]:
    """Get all active background tasks."""
    try:
        tasks = await maintenance_service.get_active_tasks()

        return [
            ActiveTaskSchema(
                task_id=t.task_id,
                task_name=t.task_name,
                started_at=t.started_at,
                running_for_seconds=t.running_for_seconds,
                status=t.status,
                progress_percent=t.progress_percent,
                details=t.details,
            )
            for t in tasks
        ]
    except Exception as e:
        logger.exception(f"Failed to get active tasks: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=dict[str, Any],
    summary="Cancel a background task",
    operation_id="cancel_task",
)
async def cancel_task(
    task_id: str,
    _permission: None = Depends(require_permission("admin:tasks")),
    current_user: TokenPayload = Depends(get_current_user),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Cancel a running background task."""
    try:
        result = await maintenance_service.cancel_task(
            task_id=task_id,
            cancelled_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Task not found")

        logger.info(f"Task {task_id} cancelled by {current_user.username}")

        return {
            "task_id": task_id,
            "cancelled": True,
            "message": "Task cancelled successfully",
        }
    except Exception as e:
        logger.exception(f"Failed to cancel task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------------
# MAINTENANCE HISTORY
# ----------------------------------------------------------------------------


@router.get(
    "/history",
    response_model=list[MaintenanceHistorySchema],
    summary="Get maintenance history",
    operation_id="get_maintenance_history",
)
async def get_maintenance_history(
    action: MaintenanceAction | None = Query(None, description="Filter by action"),
    start_date: datetime | None = Query(None, description="Start date"),
    end_date: datetime | None = Query(None, description="End date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _permission: None = Depends(require_permission("admin:audit")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> list[MaintenanceHistorySchema]:
    """Get maintenance action history."""
    try:
        history = await maintenance_service.get_maintenance_history(
            action=action.value if action else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            MaintenanceHistorySchema(
                id=h.id,
                action=MaintenanceAction(h.action),
                status=MaintenanceStatus(h.status),
                started_at=h.started_at,
                completed_at=h.completed_at,
                duration_ms=h.duration_ms,
                details=h.details,
                error=h.error,
                performed_by=h.performed_by,
                performed_by_name=h.performed_by_name,
            )
            for h in history
        ]
    except Exception as e:
        logger.exception(f"Failed to get maintenance history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SYSTEM INFORMATION
# ----------------------------------------------------------------------------


@router.get(
    "/info",
    response_model=dict[str, Any],
    summary="Get system information",
    operation_id="get_system_info",
)
async def get_system_info(
    _permission: None = Depends(require_permission("admin:read")),
    maintenance_service: Any = Depends(get_maintenance_service),
) -> dict[str, Any]:
    """Get basic system information."""
    try:
        info = await maintenance_service.get_system_info()

        return {
            "hostname": info.hostname,
            "platform": info.platform,
            "python_version": info.python_version,
            "environment": info.environment,
            "deployment_id": info.deployment_id,
            "version": info.version,
            "build_date": info.build_date.isoformat() if info.build_date else None,
            "uptime_seconds": info.uptime_seconds,
            "timezone": info.timezone,
        }
    except Exception as e:
        logger.exception(f"Failed to get system info: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
