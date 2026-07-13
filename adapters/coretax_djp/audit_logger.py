#!/usr/bin/env python3
"""
Module: audit_logger.py
Layer: Adapters (Coretax DJP)
Responsibility: Mencatat semua aktivitas terkait Coretax DJP ke dalam immutable audit log.
Tidak menggunakan SQLAlchemy untuk menghindari error 'metadata' reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from functools import wraps
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

AUDIT_RETENTION_DAYS = 365 * 7
MAX_AUDIT_RECORDS_PER_REQUEST = 1000
HASH_ALGORITHM = "sha256"
GENESIS_HASH = "0" * 64


# ============================================================================
# ENUMS
# ============================================================================

class AuditEventType(str, Enum):
    API_REQUEST = "coretax.api.request"
    API_RESPONSE = "coretax.api.response"
    API_ERROR = "coretax.api.error"
    WEBHOOK_RECEIVED = "coretax.webhook.received"
    WEBHOOK_PROCESSED = "coretax.webhook.processed"
    WEBHOOK_FAILED = "coretax.webhook.failed"
    FAKTUR_SUBMITTED = "coretax.faktur.submitted"
    FAKTUR_STATUS_CHANGED = "coretax.faktur.status_changed"
    FAKTUR_APPROVED = "coretax.faktur.approved"
    FAKTUR_REJECTED = "coretax.faktur.rejected"
    FAKTUR_CANCELLED = "coretax.faktur.cancelled"
    FAKTUR_VOID = "coretax.faktur.void"
    FAKTUR_POSTED = "coretax.faktur.posted"
    SPT_SUBMITTED = "coretax.spt.submitted"
    SPT_STATUS_CHANGED = "coretax.spt.status_changed"
    SPT_APPROVED = "coretax.spt.approved"
    SPT_REJECTED = "coretax.spt.rejected"
    SPT_CANCELLED = "coretax.spt.cancelled"
    BUPOT_SUBMITTED = "coretax.bupot.submitted"
    BUPOT_STATUS_CHANGED = "coretax.bupot.status_changed"
    BUPOT_APPROVED = "coretax.bupot.approved"
    BUPOT_REJECTED = "coretax.bupot.rejected"
    BUPOT_CANCELLED = "coretax.bupot.cancelled"
    EMETERAI_VALIDATED = "coretax.emeterai.validated"
    EMETERAI_PURCHASED = "coretax.emeterai.purchased"
    EMETERAI_USED = "coretax.emeterai.used"
    EMETERAI_REVOKED = "coretax.emeterai.revoked"
    EMETERAI_EXPIRED = "coretax.emeterai.expired"
    NSFP_REQUESTED = "coretax.nsfp.requested"
    NSFP_ALLOCATED = "coretax.nsfp.allocated"
    NSFP_RELEASED = "coretax.nsfp.released"
    NSFP_USED = "coretax.nsfp.used"
    NTPN_VALIDATED = "coretax.ntpn.validated"
    NTPN_INVALID = "coretax.ntpn.invalid"
    TOKEN_REFRESHED = "coretax.token.refreshed"
    TOKEN_FAILED = "coretax.token.failed"
    ADMIN_ACTION = "coretax.admin.action"
    SYSTEM_EVENT = "coretax.system.event"
    DATA_CHANGE = "coretax.data.change"
    INTEGRITY_CHECK = "coretax.integrity.check"
    RETRY_ATTEMPT = "coretax.retry.attempt"
    CIRCUIT_BREAKER_TRIP = "coretax.circuit_breaker.trip"
    RATE_LIMIT_HIT = "coretax.rate_limit.hit"


class AuditSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    DEBUG = "DEBUG"


class AuditStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    RETRY = "retry"


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class AuditRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_type: AuditEventType
    severity: AuditSeverity = AuditSeverity.INFO
    status: AuditStatus = AuditStatus.SUCCESS
    correlation_id: str
    user_id: UUID | None = None
    legal_entity_id: UUID | None = None
    endpoint: str | None = None
    method: str | None = None
    request_body_hash: str | None = None
    response_status: int | None = None
    response_body_hash: str | None = None
    latency_ms: float | None = None
    error_message: str | None = None
    extra_data: dict[str, Any] | None = None
    source_ip: str | None = None
    user_agent: str | None = None
    previous_hash: str = GENESIS_HASH
    hash: str = ""
    signature: str | None = None
    retention_until: datetime | None = None

    def compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "correlation_id": self.correlation_id,
            "user_id": str(self.user_id) if self.user_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "endpoint": self.endpoint,
            "method": self.method,
            "request_body_hash": self.request_body_hash,
            "response_status": self.response_status,
            "response_body_hash": self.response_body_hash,
            "latency_ms": self.latency_ms,
            "error_message": self.error_message,
            "extra_data": self.extra_data,
            "source_ip": self.source_ip,
            "user_agent": self.user_agent,
            "previous_hash": self.previous_hash,
        }
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "correlation_id": self.correlation_id,
            "user_id": str(self.user_id) if self.user_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "endpoint": self.endpoint,
            "method": self.method,
            "request_body_hash": self.request_body_hash,
            "response_status": self.response_status,
            "response_body_hash": self.response_body_hash,
            "latency_ms": self.latency_ms,
            "error_message": self.error_message,
            "extra_data": self.extra_data,
            "source_ip": self.source_ip,
            "user_agent": self.user_agent,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
            "signature": self.signature,
            "retention_until": self.retention_until.isoformat() if self.retention_until else None,
        }


class AuditSearchCriteria(BaseModel):
    event_types: list[AuditEventType] | None = None
    severities: list[AuditSeverity] | None = None
    statuses: list[AuditStatus] | None = None
    user_id: UUID | None = None
    legal_entity_id: UUID | None = None
    correlation_id: str | None = None
    endpoint: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    min_latency_ms: float | None = None
    max_latency_ms: float | None = None
    has_error: bool | None = None


class AuditStats(BaseModel):
    total_records: int
    by_event_type: dict[str, int]
    by_severity: dict[str, int]
    by_status: dict[str, int]
    by_hour: dict[str, int]
    average_latency_ms: float
    error_rate: float
    time_range_days: float
    hash_chain_integrity: bool


# ============================================================================
# AUDIT LOGGER (No SQLAlchemy)
# ============================================================================

class CoretaxAuditLogger:
    """Logger untuk aktivitas Coretax yang immutable (in-memory + file log)."""

    def __init__(self):
        self._in_memory: list[AuditRecord] = []
        self._last_hash = GENESIS_HASH
        self._lock = asyncio.Lock()

    async def _get_last_hash(self) -> str:
        return self._last_hash

    def _compute_body_hash(self, body: dict | None) -> str | None:
        if body is None:
            return None
        return hashlib.sha256(json.dumps(body, default=str).encode()).hexdigest()

    async def log(self, record: AuditRecord) -> None:
        """Simpan audit record ke memory dan log."""
        record.hash = record.compute_hash()
        record.retention_until = datetime.utcnow() + timedelta(days=AUDIT_RETENTION_DAYS)
        record.previous_hash = self._last_hash

        self._last_hash = record.hash

        async with self._lock:
            self._in_memory.append(record)

        # Log ke JSON logger
        logger.info(
            f"Audit: {record.event_type.value} - {record.status.value}",
            extra={"audit": record.to_dict()},
        )

    async def log_batch(self, records: list[AuditRecord]) -> None:
        for record in records:
            await self.log(record)

    async def log_api_request(
        self,
        endpoint: str,
        method: str,
        request_body: dict | None = None,
        user_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        record = AuditRecord(
            event_type=AuditEventType.API_REQUEST,
            severity=AuditSeverity.INFO,
            status=AuditStatus.PENDING,
            correlation_id=str(uuid4()),
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            endpoint=endpoint,
            method=method,
            request_body_hash=self._compute_body_hash(request_body),
            source_ip=source_ip,
            user_agent=user_agent,
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)
        return str(record.id)

    async def log_api_response(
        self,
        request_log_id: str,
        endpoint: str,
        status_code: int,
        response_body: dict | None = None,
        latency_ms: float | None = None,
        user_id: UUID | None = None,
    ) -> None:
        severity = AuditSeverity.ERROR if status_code >= 400 else AuditSeverity.INFO
        status = AuditStatus.SUCCESS if status_code < 400 else AuditStatus.FAILURE

        record = AuditRecord(
            event_type=AuditEventType.API_RESPONSE,
            severity=severity,
            status=status,
            correlation_id=str(uuid4()),
            user_id=user_id,
            endpoint=endpoint,
            response_status=status_code,
            response_body_hash=self._compute_body_hash(response_body),
            latency_ms=latency_ms,
            extra_data={"request_log_id": request_log_id},
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_api_error(
        self,
        endpoint: str,
        method: str,
        error: Exception,
        user_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        latency_ms: float | None = None,
    ) -> None:
        record = AuditRecord(
            event_type=AuditEventType.API_ERROR,
            severity=AuditSeverity.ERROR,
            status=AuditStatus.FAILURE,
            correlation_id=str(uuid4()),
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            endpoint=endpoint,
            method=method,
            error_message=str(error),
            latency_ms=latency_ms,
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_webhook(
        self,
        webhook_type: str,
        payload: dict,
        signature_valid: bool,
        status: AuditStatus,
        user_id: UUID | None = None,
        error: str | None = None,
    ) -> None:
        severity = AuditSeverity.WARNING if not signature_valid else AuditSeverity.INFO
        record = AuditRecord(
            event_type=AuditEventType.WEBHOOK_RECEIVED,
            severity=severity,
            status=status,
            correlation_id=str(uuid4()),
            user_id=user_id,
            endpoint=f"/webhook/{webhook_type}",
            request_body_hash=self._compute_body_hash(payload),
            error_message=error,
            extra_data={"webhook_type": webhook_type, "signature_valid": signature_valid},
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_status_change(
        self,
        event_type: AuditEventType,
        entity_type: str,
        entity_id: str,
        old_status: str,
        new_status: str,
        reason: str | None = None,
        user_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> None:
        severity = AuditSeverity.WARNING if new_status in ["rejected", "cancelled", "void"] else AuditSeverity.INFO
        record = AuditRecord(
            event_type=event_type,
            severity=severity,
            status=AuditStatus.SUCCESS,
            correlation_id=str(uuid4()),
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            extra_data={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "old_status": old_status,
                "new_status": new_status,
                "reason": reason,
            },
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_faktur_status_change(
        self,
        faktur_number: str,
        old_status: str,
        new_status: str,
        reason: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
        await self.log_status_change(
            event_type=AuditEventType.FAKTUR_STATUS_CHANGED,
            entity_type="faktur",
            entity_id=faktur_number,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            user_id=user_id,
        )

    async def log_spt_status_change(
        self,
        spt_number: str,
        old_status: str,
        new_status: str,
        reason: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
        await self.log_status_change(
            event_type=AuditEventType.SPT_STATUS_CHANGED,
            entity_type="spt",
            entity_id=spt_number,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            user_id=user_id,
        )

    async def log_bupot_status_change(
        self,
        bupot_number: str,
        old_status: str,
        new_status: str,
        reason: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
        await self.log_status_change(
            event_type=AuditEventType.BUPOT_STATUS_CHANGED,
            entity_type="bupot",
            entity_id=bupot_number,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            user_id=user_id,
        )

    async def log_nsfp_request(
        self,
        npwp: str,
        tahun: int,
        bulan: int,
        jumlah: int,
        success: bool,
        response: dict | None = None,
        user_id: UUID | None = None,
    ) -> None:
        severity = AuditSeverity.ERROR if not success else AuditSeverity.INFO
        status = AuditStatus.SUCCESS if success else AuditStatus.FAILURE
        record = AuditRecord(
            event_type=AuditEventType.NSFP_REQUESTED,
            severity=severity,
            status=status,
            correlation_id=str(uuid4()),
            user_id=user_id,
            extra_data={
                "npwp": npwp,
                "tahun": tahun,
                "bulan": bulan,
                "jumlah": jumlah,
                "success": success,
                "response": response,
            },
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_nsfp_allocation(
        self,
        nsfp: str,
        npwp: str,
        faktur_id: UUID,
        allocated_by: UUID,
    ) -> None:
        record = AuditRecord(
            event_type=AuditEventType.NSFP_ALLOCATED,
            severity=AuditSeverity.INFO,
            status=AuditStatus.SUCCESS,
            correlation_id=str(uuid4()),
            user_id=allocated_by,
            extra_data={
                "nsfp": nsfp,
                "npwp": npwp,
                "faktur_id": str(faktur_id),
            },
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_emeterai_purchase(
        self,
        npwp: str,
        quantity: int,
        success: bool,
        transaction_id: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
        severity = AuditSeverity.ERROR if not success else AuditSeverity.INFO
        status = AuditStatus.SUCCESS if success else AuditStatus.FAILURE
        record = AuditRecord(
            event_type=AuditEventType.EMETERAI_PURCHASED,
            severity=severity,
            status=status,
            correlation_id=str(uuid4()),
            user_id=user_id,
            extra_data={
                "npwp": npwp,
                "quantity": quantity,
                "transaction_id": transaction_id,
                "success": success,
            },
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_emeterai_used(
        self,
        meterai_code: str,
        document_id: str,
        document_type: str,
        used_by: UUID,
    ) -> None:
        record = AuditRecord(
            event_type=AuditEventType.EMETERAI_USED,
            severity=AuditSeverity.INFO,
            status=AuditStatus.SUCCESS,
            correlation_id=str(uuid4()),
            user_id=used_by,
            extra_data={
                "meterai_code": meterai_code[:8] + "..." if len(meterai_code) > 8 else meterai_code,
                "document_id": document_id,
                "document_type": document_type,
            },
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_admin_action(
        self,
        action: str,
        details: dict,
        user_id: UUID,
        legal_entity_id: UUID | None = None,
    ) -> None:
        record = AuditRecord(
            event_type=AuditEventType.ADMIN_ACTION,
            severity=AuditSeverity.INFO,
            status=AuditStatus.SUCCESS,
            correlation_id=str(uuid4()),
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            extra_data={"action": action, "details": details},
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_ntpn_validation(
        self,
        ntpn: str,
        amount: Decimal,
        is_valid: bool,
        message: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
        event_type = AuditEventType.NTPN_VALIDATED if is_valid else AuditEventType.NTPN_INVALID
        severity = AuditSeverity.WARNING if not is_valid else AuditSeverity.INFO
        record = AuditRecord(
            event_type=event_type,
            severity=severity,
            status=AuditStatus.SUCCESS if is_valid else AuditStatus.FAILURE,
            correlation_id=str(uuid4()),
            user_id=user_id,
            extra_data={
                "ntpn": ntpn[:8] + "..." if len(ntpn) > 8 else ntpn,
                "amount": str(amount),
                "is_valid": is_valid,
                "message": message,
            },
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_token_event(
        self,
        event_type: AuditEventType,
        success: bool,
        message: str | None = None,
    ) -> None:
        severity = AuditSeverity.ERROR if not success else AuditSeverity.INFO
        status = AuditStatus.SUCCESS if success else AuditStatus.FAILURE
        record = AuditRecord(
            event_type=event_type,
            severity=severity,
            status=status,
            correlation_id=str(uuid4()),
            extra_data={"message": message},
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    async def log_integrity_check(
        self,
        check_id: str,
        status: AuditStatus,
        details: dict,
    ) -> None:
        record = AuditRecord(
            event_type=AuditEventType.INTEGRITY_CHECK,
            severity=AuditSeverity.INFO,
            status=status,
            correlation_id=check_id,
            extra_data=details,
            previous_hash=await self._get_last_hash(),
        )
        await self.log(record)

    # ========================================================================
    # QUERY METHODS (in-memory only)
    # ========================================================================

    async def get_audit_by_id(self, audit_id: UUID) -> AuditRecord | None:
        async with self._lock:
            for r in self._in_memory:
                if r.id == audit_id:
                    return r
        return None

    async def get_audit_by_correlation_id(self, correlation_id: str) -> list[AuditRecord]:
        result = []
        async with self._lock:
            for r in self._in_memory:
                if r.correlation_id == correlation_id:
                    result.append(r)
        return result[:MAX_AUDIT_RECORDS_PER_REQUEST]

    async def get_audit_by_event_type(
        self,
        event_type: AuditEventType,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditRecord]:
        result = []
        async with self._lock:
            for r in self._in_memory:
                if r.event_type == event_type:
                    result.append(r)
        return result[offset:offset+limit]

    async def get_audit_by_date_range(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditRecord]:
        result = []
        async with self._lock:
            for r in self._in_memory:
                if start_time <= r.timestamp <= end_time:
                    result.append(r)
        return result[offset:offset+limit]

    async def search_audit(
        self,
        criteria: AuditSearchCriteria,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditRecord]:
        result = []
        async with self._lock:
            for r in self._in_memory:
                match = True
                if criteria.event_types and r.event_type not in criteria.event_types:
                    match = False
                if criteria.severities and r.severity not in criteria.severities:
                    match = False
                if criteria.statuses and r.status not in criteria.statuses:
                    match = False
                if criteria.user_id and r.user_id != criteria.user_id:
                    match = False
                if criteria.legal_entity_id and r.legal_entity_id != criteria.legal_entity_id:
                    match = False
                if criteria.correlation_id and r.correlation_id != criteria.correlation_id:
                    match = False
                if criteria.endpoint and (not r.endpoint or criteria.endpoint not in r.endpoint):
                    match = False
                if criteria.start_time and r.timestamp < criteria.start_time:
                    match = False
                if criteria.end_time and r.timestamp > criteria.end_time:
                    match = False
                if criteria.min_latency_ms and (r.latency_ms is None or r.latency_ms < criteria.min_latency_ms):
                    match = False
                if criteria.max_latency_ms and (r.latency_ms is None or r.latency_ms > criteria.max_latency_ms):
                    match = False
                if criteria.has_error and (r.error_message is None):
                    match = False
                if match:
                    result.append(r)
        return result[offset:offset+limit]

    async def get_audit_trail(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 100,
    ) -> list[AuditRecord]:
        result = []
        async with self._lock:
            for r in self._in_memory:
                if r.extra_data and r.extra_data.get("entity_type") == entity_type and r.extra_data.get("entity_id") == entity_id:
                    result.append(r)
        return result[:limit]

    async def get_stats(self) -> AuditStats:
        async with self._lock:
            total = len(self._in_memory)
            by_event = {}
            by_severity = {}
            by_status = {}
            by_hour = {}
            total_latency = 0.0
            error_count = 0
            for r in self._in_memory:
                by_event[r.event_type.value] = by_event.get(r.event_type.value, 0) + 1
                by_severity[r.severity.value] = by_severity.get(r.severity.value, 0) + 1
                by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
                hour_key = r.timestamp.strftime("%Y-%m-%d %H:00")
                by_hour[hour_key] = by_hour.get(hour_key, 0) + 1
                if r.latency_ms:
                    total_latency += r.latency_ms
                if r.status == AuditStatus.FAILURE:
                    error_count += 1
            avg_latency = total_latency / total if total > 0 else 0
            error_rate = error_count / total if total > 0 else 0
            # Verifikasi hash chain sederhana
            integrity_ok = await self.verify_hash_chain()
            return AuditStats(
                total_records=total,
                by_event_type=by_event,
                by_severity=by_severity,
                by_status=by_status,
                by_hour=by_hour,
                average_latency_ms=avg_latency,
                error_rate=error_rate,
                time_range_days=30.0,
                hash_chain_integrity=integrity_ok,
            )

    async def verify_hash_chain(self, limit: int = 1000) -> bool:
        async with self._lock:
            records = self._in_memory[-limit:]
            if not records:
                return True
            prev = GENESIS_HASH
            for r in records:
                if r.previous_hash != prev:
                    return False
                if r.hash != r.compute_hash():
                    return False
                prev = r.hash
            return True

    async def export_audit(self, start_time: datetime, end_time: datetime, format: str = "json") -> bytes:
        records = await self.get_audit_by_date_range(start_time, end_time, limit=100000)
        if format == "json":
            data = [r.to_dict() for r in records]
            return json.dumps(data, default=str, indent=2).encode("utf-8")
        elif format == "csv":
            import csv
            from io import StringIO
            output = StringIO()
            if records:
                writer = csv.DictWriter(output, fieldnames=records[0].to_dict().keys())
                writer.writeheader()
                for r in records:
                    writer.writerow(r.to_dict())
            return output.getvalue().encode("utf-8")
        else:
            raise ValueError(f"Unsupported export format: {format}")

    async def create_snapshot(self) -> dict[str, Any]:
        stats = await self.get_stats()
        return {
            "snapshot_id": str(uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "total_records": stats.total_records,
            "last_hash": self._last_hash,
            "hash_chain_integrity": stats.hash_chain_integrity,
            "stats": stats.dict(),
        }

    async def prune_old_audits(self, retention_days: int = AUDIT_RETENTION_DAYS) -> int:
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        deleted = 0
        async with self._lock:
            new_list = []
            for r in self._in_memory:
                if r.timestamp < cutoff:
                    deleted += 1
                else:
                    new_list.append(r)
            self._in_memory = new_list
        logger.info("Pruned %d audit records older than %d days", deleted, retention_days)
        return deleted

    async def flush_buffer(self) -> None:
        # Tidak ada buffer karena langsung log
        pass


# ============================================================================
# DECORATOR
# ============================================================================

def audit_coretax_call(event_type: AuditEventType, severity: AuditSeverity = AuditSeverity.INFO):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger_instance = await get_coretax_audit_logger()
            start_time = time.time()
            endpoint = getattr(args[0], "endpoint", None) if args else None
            method = getattr(func, "__name__", "unknown")
            try:
                result = await func(*args, **kwargs)
                latency_ms = (time.time() - start_time) * 1000
                await logger_instance.log_api_response(
                    request_log_id="",
                    endpoint=endpoint or method,
                    status_code=200,
                    latency_ms=latency_ms,
                )
                return result
            except Exception as e:
                await logger_instance.log_api_error(
                    endpoint=endpoint or method,
                    method=method,
                    error=e,
                )
                raise
        return wrapper
    return decorator


# ============================================================================
# SINGLETON
# ============================================================================

_audit_logger: CoretaxAuditLogger | None = None


async def get_coretax_audit_logger() -> CoretaxAuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = CoretaxAuditLogger()
    return _audit_logger


async def shutdown_audit_logger():
    global _audit_logger
    if _audit_logger:
        await _audit_logger.flush_buffer()


__all__ = [
    "AuditEventType",
    "AuditRecord",
    "AuditSearchCriteria",
    "AuditSeverity",
    "AuditStats",
    "AuditStatus",
    "CoretaxAuditLogger",
    "audit_coretax_call",
    "get_coretax_audit_logger",
    "shutdown_audit_logger",
]
