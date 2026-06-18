#!/usr/bin/env python3
"""
Module: ethics_exceptions.py
Layer: Compliance / Ethics

Responsibility:
    Exception khusus untuk modul etika dan kepatuhan internal.
    Mendukung error codes, detail konteks, serialisasi JSON,
    registry untuk audit trail, dan decorator untuk handling.

Dependencies:
    - datetime, uuid, json, hashlib, logging, traceback

Audit:
    Setiap exception yang di-raise (kecuali yang di-handle internal)
    dicatat dalam registry dengan hash integrity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import traceback
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Error Code Registry
# ============================================================================
class EthicsErrorCode:
    """Kode error standar untuk etika."""

    # Base errors
    GENERIC = "ETH-0001"
    VALIDATION = "ETH-0002"
    PERMISSION = "ETH-0003"
    NOT_FOUND = "ETH-0004"
    DUPLICATE = "ETH-0005"

    # Conflict of Interest
    COI_DECLARATION_MISSING = "ETH-COI-001"
    COI_ACTIVE_CONFLICT = "ETH-COI-002"
    COI_RESOLUTION_FAILED = "ETH-COI-003"

    # Professional Judgment
    PJ_MISSING_DOCUMENTATION = "ETH-PJ-001"
    PJ_UNAPPROVED = "ETH-PJ-002"
    PJ_INVALID_ASSUMPTION = "ETH-PJ-003"

    # Ethics Violation
    EV_FRAUD = "ETH-EV-001"
    EV_BRIBERY = "ETH-EV-002"
    EV_INSIDER_TRADING = "ETH-EV-003"
    EV_DATA_PRIVACY = "ETH-EV-004"

    # Whistleblower
    WB_ANONYMOUS_NOT_ALLOWED = "ETH-WB-001"
    WB_RETALIATION_DETECTED = "ETH-WB-002"
    WB_CASE_ALREADY_EXISTS = "ETH-WB-003"


# ============================================================================
# Base Ethics Exception
# ============================================================================
class EthicsError(Exception):
    """
    Base exception untuk semua error etika.
    Mendukung pencatatan detail, error code, timestamp, dan hash.
    """

    def __init__(
        self,
        message: str,
        error_code: str = EthicsErrorCode.GENERIC,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
        user_id: UUID | None = None,
        entity_id: UUID | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause
        self.user_id = user_id
        self.entity_id = entity_id
        self.timestamp = datetime.utcnow()
        self.exception_id = uuid4()
        self._hash = self._compute_hash()

        # Log otomatis
        logger.error(f"[{error_code}] {message} (id={self.exception_id})")

    def _compute_hash(self) -> str:
        data = {
            "exception_id": str(self.exception_id),
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "details": self.details,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "exception_id": str(self.exception_id),
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "details": self.details,
            "hash": self._hash,
            "traceback": traceback.format_exc() if self.cause else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ============================================================================
# Specific Exceptions
# ============================================================================
class ConflictOfInterestError(EthicsError):
    """Konflik kepentingan tidak dideklarasikan atau tidak ditangani."""

    def __init__(
        self,
        message: str,
        declarant_id: UUID | None = None,
        related_party: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(
            message=message,
            error_code=EthicsErrorCode.COI_ACTIVE_CONFLICT,
            details=details,
            user_id=declarant_id,
        )
        self.related_party = related_party


class ProfessionalJudgmentError(EthicsError):
    """Kesalahan dalam judgment profesional."""

    def __init__(
        self,
        message: str,
        standard: str | None = None,
        assumptions: list[str] | None = None,
        details: dict | None = None,
    ):
        super().__init__(
            message=message,
            error_code=EthicsErrorCode.PJ_MISSING_DOCUMENTATION,
            details=details,
        )
        self.standard = standard
        self.assumptions = assumptions or []


class EthicsViolationError(EthicsError):
    """Pelanggaran kode etik."""

    def __init__(
        self,
        message: str,
        violation_type: str = "unknown",
        reported_by: UUID | None = None,
        evidence: list[str] | None = None,
        details: dict | None = None,
    ):
        error_code_map = {
            "fraud": EthicsErrorCode.EV_FRAUD,
            "bribery": EthicsErrorCode.EV_BRIBERY,
            "insider_trading": EthicsErrorCode.EV_INSIDER_TRADING,
            "data_privacy": EthicsErrorCode.EV_DATA_PRIVACY,
        }
        code = error_code_map.get(violation_type.lower(), EthicsErrorCode.GENERIC)
        super().__init__(
            message=message,
            error_code=code,
            details=details,
            user_id=reported_by,
        )
        self.violation_type = violation_type
        self.evidence = evidence or []


class WhistleblowerError(EthicsError):
    """Error dalam sistem whistleblower."""

    def __init__(
        self,
        message: str,
        case_id: UUID | None = None,
        reporter_identity: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(
            message=message,
            error_code=EthicsErrorCode.WB_ANONYMOUS_NOT_ALLOWED,
            details=details,
            entity_id=case_id,
        )
        self.reporter_identity = reporter_identity


# ============================================================================
# Exception Registry (Audit Trail)
# ============================================================================
class EthicsExceptionRegistry:
    """Registry untuk mencatat semua exception yang terjadi (audit trail)."""

    _instance = None
    _exceptions: list[dict] = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, error: EthicsError) -> None:
        """Catat exception ke registry."""
        self._exceptions.append(error.to_dict())

    def get_all(self, limit: int = 100) -> list[dict]:
        return self._exceptions[-limit:]

    def get_by_code(self, error_code: str) -> list[dict]:
        return [e for e in self._exceptions if e.get("error_code") == error_code]

    def get_by_user(self, user_id: UUID) -> list[dict]:
        return [e for e in self._exceptions if e.get("user_id") == str(user_id)]

    def clear(self) -> None:
        self._exceptions.clear()

    def get_summary(self) -> dict:
        from collections import Counter

        codes = Counter(e.get("error_code") for e in self._exceptions)
        return {
            "total": len(self._exceptions),
            "by_error_code": dict(codes),
            "last_exception": self._exceptions[-1] if self._exceptions else None,
        }


# ============================================================================
# Helper Functions
# ============================================================================
def handle_ethics_exceptions(
    func: Callable | None = None,
    *,
    reraise: bool = True,
    log_level: str = "error",
    default_return: Any = None,
) -> Callable:
    """
    Decorator untuk menangani exception etika.
    """

    def decorator(f: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except EthicsError as e:
                registry = EthicsExceptionRegistry()
                registry.register(e)
                log_func = getattr(logger, log_level, logger.error)
                log_func(f"Ethics exception in {f.__name__}: {e.message} [{e.error_code}]")
                if reraise:
                    raise
                return default_return
            except Exception as e:
                logger.exception(f"Unexpected error in {f.__name__}: {e}")
                if reraise:
                    raise
                return default_return

        return wrapper

    return decorator(func) if func else decorator


def raise_conflict_of_interest(
    declarant_name: str,
    related_party: str,
    nature: str,
    declarant_id: UUID | None = None,
) -> None:
    """Raise exception dengan detail konflik kepentingan."""
    raise ConflictOfInterestError(
        message=f"Conflict of interest: {declarant_name} has undeclared relationship with {related_party}. Nature: {nature}",
        declarant_id=declarant_id,
        related_party=related_party,
        details={"declarant_name": declarant_name, "nature": nature},
    )


def raise_professional_judgment_error(
    standard: str,
    issue: str,
    assumptions: list[str],
) -> None:
    """Raise exception untuk judgment profesional yang tidak valid."""
    raise ProfessionalJudgmentError(
        message=f"Professional judgment error under {standard}: {issue}",
        standard=standard,
        assumptions=assumptions,
        details={"issue": issue},
    )


def raise_ethics_violation(
    violation_type: str,
    description: str,
    reported_by: UUID,
    evidence: list[str] | None = None,
) -> None:
    """Raise exception untuk pelanggaran etik."""
    raise EthicsViolationError(
        message=f"Ethics violation detected: {description}",
        violation_type=violation_type,
        reported_by=reported_by,
        evidence=evidence,
        details={"description": description},
    )


def raise_whistleblower_error(
    message: str,
    case_id: UUID | None = None,
    reporter_identity: str | None = None,
) -> None:
    """Raise exception untuk whistleblower system error."""
    raise WhistleblowerError(
        message=message,
        case_id=case_id,
        reporter_identity=reporter_identity,
    )


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    registry = EthicsExceptionRegistry()

    try:
        raise_conflict_of_interest(
            declarant_name="John Doe",
            related_party="PT XYZ",
            nature="Family business",
            declarant_id=uuid4(),
        )
    except ConflictOfInterestError as e:
        print(e.to_json())
        registry.register(e)

    try:
        raise_ethics_violation(
            violation_type="insider_trading",
            description="Employee traded based on non-public financial results",
            reported_by=uuid4(),
            evidence=["email_evidence.pdf"],
        )
    except EthicsViolationError as e:
        print(e.to_json())
        registry.register(e)

    print("\nRegistry Summary:")
    print(registry.get_summary())
