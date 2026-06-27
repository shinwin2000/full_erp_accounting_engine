#!/usr/bin/env python3
"""
Module: forensic_query_engine.py
Layer: 5 - Domain / Intent
Responsibility: Mesin query forensik untuk investigasi intent.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intent.audit_trail_writer import IntentAuditAction, get_audit_trail_writer
from domain.intent.immutable_record import (
    ImmutableIntentRecord,
    IntentStatus,
    get_immutable_intent_record_service,
)

logger = logging.getLogger(__name__)


class ForensicQueryType(Enum):
    BY_USER = auto()
    BY_TIME_RANGE = auto()
    BY_STATUS = auto()
    BY_TYPE = auto()
    BY_AMOUNT = auto()
    BY_PATTERN = auto()
    BY_RELATED_INTENT = auto()
    COMPROMISED = auto()


class ForensicSortOrder(Enum):
    NEWEST_FIRST = auto()
    OLDEST_FIRST = auto()
    LARGEST_AMOUNT = auto()
    SMALLEST_AMOUNT = auto()


@dataclass
class ForensicQueryResult:
    query_id: UUID
    query_type: ForensicQueryType
    executed_at: datetime
    executed_by: str
    total_results: int
    results: list[ImmutableIntentRecord]
    execution_time_ms: float
    criteria: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    cryptographic_hash: str = ""

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.executed_by, {})

    def _validate(self) -> None:
        if not isinstance(self.query_id, UUID):
            raise ValueError("query_id must be UUID")
        if not isinstance(self.query_type, ForensicQueryType):
            raise ValueError("query_type must be ForensicQueryType")
        if not isinstance(self.executed_at, datetime):
            raise ValueError("executed_at must be datetime")
        if not self.executed_by:
            raise ValueError("executed_by cannot be empty")
        if self.total_results < 0:
            raise ValueError("total_results cannot be negative")
        if self.execution_time_ms < 0:
            raise ValueError("execution_time_ms cannot be negative")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        import hashlib
        import json

        content = {
            "query_id": str(self.query_id),
            "query_type": self.query_type.name,
            "executed_by": self.executed_by,
            "executed_at": self.executed_at.isoformat(),
            "total_results": self.total_results,
            "execution_time_ms": self.execution_time_ms,
            "criteria": self.criteria,
            "version": self.version,
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "query_id": str(self.query_id),
            "query_type": self.query_type.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "query_id": str(self.query_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ForensicQueryResult:
        return self

    def update(self, updated_by: str, **kwargs) -> ForensicQueryResult:
        raise AttributeError("ForensicQueryResult is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> ForensicQueryResult:
        raise AttributeError("ForensicQueryResult cannot be deleted")

    def restore(self, restored_by: str) -> ForensicQueryResult:
        raise AttributeError("ForensicQueryResult cannot be restored")

    def activate(self, activated_by: str) -> ForensicQueryResult:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ForensicQueryResult:
        return self

    def lock(self, locked_by: str, reason: str) -> ForensicQueryResult:
        return self

    def unlock(self, unlocked_by: str) -> ForensicQueryResult:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "query_id": str(self.query_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": str(self.query_id),
            "query_type": self.query_type.name,
            "executed_at": self.executed_at.isoformat(),
            "executed_by": self.executed_by,
            "total_results": self.total_results,
            "results_count": len(self.results),
            "execution_time_ms": self.execution_time_ms,
            "criteria": self.criteria,
            "version": self.version,
            "cryptographic_hash": self.cryptographic_hash[:16] + "...",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForensicQueryResult:
        return cls(
            query_id=UUID(data["query_id"]),
            query_type=ForensicQueryType[data["query_type"]],
            executed_at=datetime.fromisoformat(data["executed_at"]),
            executed_by=data["executed_by"],
            total_results=data["total_results"],
            results=[],  # results tidak disimpan dalam dict
            execution_time_ms=data["execution_time_ms"],
            criteria=data.get("criteria", {}),
            version=data.get("version", 1),
            cryptographic_hash=data.get("cryptographic_hash", ""),
        )

    def clone(self) -> ForensicQueryResult:
        return ForensicQueryResult(
            query_id=uuid4(),
            query_type=self.query_type,
            executed_at=datetime.now(UTC),
            executed_by=self.executed_by,
            total_results=0,
            results=[],
            execution_time_ms=0,
            criteria=self.criteria.copy(),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "query_id": str(self.query_id),
            "query_type": self.query_type.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ForensicQueryResult:
        self._record_audit("TOUCH", touched_by, {})
        return self


class ForensicQueryEngine:
    _instance: ForensicQueryEngine | None = None

    def __new__(cls) -> ForensicQueryEngine:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._record_service = get_immutable_intent_record_service()
        self._audit_writer = get_audit_trail_writer()
        self._query_history: list[ForensicQueryResult] = []
        self._max_history = 1000
        self._lock = threading.RLock()

    # ==================== QUERY METHODS ====================
    def _get_all_records(self) -> list[ImmutableIntentRecord]:
        return self._record_service.get_all()

    def _record_query(self, result: ForensicQueryResult) -> None:
        with self._lock:
            self._query_history.append(result)
            if len(self._query_history) > self._max_history:
                self._query_history = self._query_history[-self._max_history :]
        self._audit_writer.write(
            intent_id=UUID(int=0),
            action=IntentAuditAction.EXECUTED,
            changed_by=result.executed_by,
            notes=f"Forensic query: {result.query_type.name} returned {result.total_results} results in {result.execution_time_ms:.2f}ms",
        )

    def query_by_user(
        self,
        user_id: str,
        time_range_days: int | None = None,
        sort_order: ForensicSortOrder = ForensicSortOrder.NEWEST_FIRST,
        executed_by: str = "system",
    ) -> ForensicQueryResult:
        start = time.perf_counter()
        records = [
            r for r in self._get_all_records() if r.created_by == user_id or r.signed_by == user_id
        ]
        if time_range_days:
            cutoff = datetime.now(UTC) - timedelta(days=time_range_days)
            records = [r for r in records if r.created_at >= cutoff]
        if sort_order == ForensicSortOrder.NEWEST_FIRST:
            records.sort(key=lambda r: r.created_at, reverse=True)
        elif sort_order == ForensicSortOrder.OLDEST_FIRST:
            records.sort(key=lambda r: r.created_at)
        elif sort_order == ForensicSortOrder.LARGEST_AMOUNT:
            records.sort(key=lambda r: float(r.data.get("amount", 0)), reverse=True)
        elif sort_order == ForensicSortOrder.SMALLEST_AMOUNT:
            records.sort(key=lambda r: float(r.data.get("amount", 0)))
        elapsed = (time.perf_counter() - start) * 1000
        result = ForensicQueryResult(
            query_id=uuid4(),
            query_type=ForensicQueryType.BY_USER,
            executed_at=datetime.now(UTC),
            executed_by=executed_by,
            total_results=len(records),
            results=records[:1000],
            execution_time_ms=elapsed,
            criteria={"user_id": user_id, "time_range_days": time_range_days},
        )
        self._record_query(result)
        return result

    def query_by_time_range(
        self,
        from_date: datetime,
        to_date: datetime,
        sort_order: ForensicSortOrder = ForensicSortOrder.NEWEST_FIRST,
        executed_by: str = "system",
    ) -> ForensicQueryResult:
        start = time.perf_counter()
        records = [r for r in self._get_all_records() if from_date <= r.created_at <= to_date]
        if sort_order == ForensicSortOrder.NEWEST_FIRST:
            records.sort(key=lambda r: r.created_at, reverse=True)
        elif sort_order == ForensicSortOrder.OLDEST_FIRST:
            records.sort(key=lambda r: r.created_at)
        elapsed = (time.perf_counter() - start) * 1000
        result = ForensicQueryResult(
            query_id=uuid4(),
            query_type=ForensicQueryType.BY_TIME_RANGE,
            executed_at=datetime.now(UTC),
            executed_by=executed_by,
            total_results=len(records),
            results=records[:1000],
            execution_time_ms=elapsed,
            criteria={"from_date": from_date.isoformat(), "to_date": to_date.isoformat()},
        )
        self._record_query(result)
        return result

    def query_by_status(
        self, status: IntentStatus, executed_by: str = "system"
    ) -> ForensicQueryResult:
        start = time.perf_counter()
        records = [r for r in self._get_all_records() if r.status == status]
        records.sort(key=lambda r: r.created_at, reverse=True)
        elapsed = (time.perf_counter() - start) * 1000
        result = ForensicQueryResult(
            query_id=uuid4(),
            query_type=ForensicQueryType.BY_STATUS,
            executed_at=datetime.now(UTC),
            executed_by=executed_by,
            total_results=len(records),
            results=records[:1000],
            execution_time_ms=elapsed,
            criteria={"status": status.name},
        )
        self._record_query(result)
        return result

    def query_by_amount(
        self,
        min_amount: Decimal,
        max_amount: Decimal | None = None,
        executed_by: str = "system",
    ) -> ForensicQueryResult:
        start = time.perf_counter()
        records = []

        # Logika perbandingan menggunakan Decimal secara langsung
        for r in self._get_all_records():
            # Asumsi: r.data.get("amount") dikonversi ke Decimal saat data dimuat
            amt = r.data.get("amount")
            if amt is not None:
                # Pastikan amt adalah Decimal, konversi jika perlu (sebaiknya dilakukan di layer data)
                amt_d = Decimal(str(amt)) if not isinstance(amt, Decimal) else amt

                if amt_d >= min_amount and (max_amount is None or amt_d <= max_amount):
                    records.append(r)

        records.sort(key=lambda r: r.created_at, reverse=True)
        elapsed = (time.perf_counter() - start) * 1000

        result = ForensicQueryResult(
            query_id=uuid4(),
            query_type=ForensicQueryType.BY_AMOUNT,
            executed_at=datetime.now(UTC),
            executed_by=executed_by,
            total_results=len(records),
            results=records[:1000],
            execution_time_ms=elapsed,
            criteria={
                "min_amount": min_amount,
                "max_amount": max_amount,
            },
        )
        self._record_query(result)
        return result

    def query_by_pattern(
        self, pattern: str, fields: list[str], executed_by: str = "system"
    ) -> ForensicQueryResult:
        start = time.perf_counter()
        regex = re.compile(pattern, re.IGNORECASE)
        records = []
        for r in self._get_all_records():
            for field in fields:
                val = r.data.get(field)
                if (val and isinstance(val, str) and regex.search(val)) or (
                    val and isinstance(val, (int, float)) and regex.search(str(val))
                ):
                    records.append(r)
                    break
        records.sort(key=lambda r: r.created_at, reverse=True)
        elapsed = (time.perf_counter() - start) * 1000
        result = ForensicQueryResult(
            query_id=uuid4(),
            query_type=ForensicQueryType.BY_PATTERN,
            executed_at=datetime.now(UTC),
            executed_by=executed_by,
            total_results=len(records),
            results=records[:1000],
            execution_time_ms=elapsed,
            criteria={"pattern": pattern, "fields": fields},
        )
        self._record_query(result)
        return result

    def find_compromised_intents(self, executed_by: str = "system") -> ForensicQueryResult:
        start = time.perf_counter()
        suspicious = []
        user_intents = {}
        for r in self._get_all_records():
            user_intents.setdefault(r.created_by, []).append(r)
        for user_id, intents in user_intents.items():
            rejections = [i for i in intents if i.status == IntentStatus.REJECTED]
            if len(rejections) > 5:
                suspicious.extend(rejections)
            for intent in intents:
                audit = self._audit_writer.get_audit_trail(intent.intent_id, limit=100)
                status_changes = [
                    a
                    for a in audit
                    if a.action
                    in (
                        IntentAuditAction.SUBMITTED,
                        IntentAuditAction.APPROVED,
                        IntentAuditAction.REJECTED,
                    )
                ]
                if len(status_changes) > 3:
                    suspicious.append(intent)
        suspicious = list({i.intent_id: i for i in suspicious}.values())
        elapsed = (time.perf_counter() - start) * 1000
        result = ForensicQueryResult(
            query_id=uuid4(),
            query_type=ForensicQueryType.COMPROMISED,
            executed_at=datetime.now(UTC),
            executed_by=executed_by,
            total_results=len(suspicious),
            results=suspicious[:1000],
            execution_time_ms=elapsed,
            criteria={"reason": "Suspicious pattern detection"},
        )
        self._record_query(result)
        return result

    # ==================== REPOSITORY METHODS ====================
    def save_query(self, result: ForensicQueryResult) -> None:
        with self._lock:
            self._query_history.append(result)
            if len(self._query_history) > self._max_history:
                self._query_history = self._query_history[-self._max_history :]

    def get_query_history(
        self, limit: int = 50, query_type: ForensicQueryType | None = None
    ) -> list[ForensicQueryResult]:
        with self._lock:
            results = self._query_history[-limit:]
            if query_type:
                results = [q for q in results if q.query_type == query_type]
            return results

    def get_query(self, query_id: UUID) -> ForensicQueryResult | None:
        with self._lock:
            for q in self._query_history:
                if q.query_id == query_id:
                    return q
            return None

    def delete_query(self, query_id: UUID) -> bool:
        with self._lock:
            for i, q in enumerate(self._query_history):
                if q.query_id == query_id:
                    self._query_history.pop(i)
                    return True
            return False

    def count_queries(self) -> int:
        with self._lock:
            return len(self._query_history)

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._query_history)
            if total == 0:
                return {"total_queries": 0}
            by_type = {}
            total_time = 0.0
            for q in self._query_history:
                by_type[q.query_type.name] = by_type.get(q.query_type.name, 0) + 1
                total_time += q.execution_time_ms
            return {
                "total_queries": total,
                "by_query_type": by_type,
                "average_execution_time_ms": total_time / total,
            }

    def reset(self) -> None:
        with self._lock:
            self._query_history = []


def get_forensic_query_engine() -> ForensicQueryEngine:
    global _forensic_query_engine_instance
    if _forensic_query_engine_instance is None:
        _forensic_query_engine_instance = ForensicQueryEngine()
    return _forensic_query_engine_instance


_forensic_query_engine_instance: ForensicQueryEngine | None = None

__all__ = [
    "ForensicQueryEngine",
    "ForensicQueryResult",
    "ForensicQueryType",
    "ForensicSortOrder",
    "get_forensic_query_engine",
]
