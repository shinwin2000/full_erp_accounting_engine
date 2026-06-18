#!/usr/bin/env python3
"""
Module: legal_exceptions.py
Layer: Compliance / Legal

Responsibility:
    Exception khusus untuk modul legal dengan dukungan error codes,
    konteks tambahan (yurisdiksi, regulation, filing ID), serialization,
    dan registry untuk audit trail. Memudahkan debugging dan pelacakan
    akar masalah dalam proses kepatuhan legal.

Dependencies:
    - datetime, uuid, hashlib, json, logging, traceback

Audit:
    Setiap exception yang di-raise (kecuali internal handling) dapat
    dicatat ke registry dengan hash integrity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import traceback
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Error Code Registry
# ============================================================================
class LegalErrorCode:
    """Kode error standar untuk modul legal."""

    # Base / Umum
    GENERIC = "LEG-0001"
    INVALID_INPUT = "LEG-0002"
    NOT_FOUND = "LEG-0003"
    DUPLICATE = "LEG-0004"
    PERMISSION_DENIED = "LEG-0005"

    # Jurisdiction
    JURISDICTION_UNSUPPORTED = "LEG-JUR-001"
    JURISDICTION_MISMATCH = "LEG-JUR-002"
    JURISDICTION_CONFLICT = "LEG-JUR-003"

    # Regulatory Filing
    FILING_DEADLINE_MISSED = "LEG-FIL-001"
    FILING_REJECTED = "LEG-FIL-002"
    FILING_INCOMPLETE = "LEG-FIL-003"
    FILING_ACKNOWLEDGEMENT_FAILED = "LEG-FIL-004"

    # Sanction List
    SANCTION_LIST_HIT = "LEG-SAN-001"
    SANCTION_LIST_UNAVAILABLE = "LEG-SAN-002"

    # Sovereignty / Cross-border
    SOVEREIGNTY_VIOLATION = "LEG-SOV-001"
    DATA_TRANSFER_NOT_ALLOWED = "LEG-SOV-002"

    # Legal Opinion
    OPINION_NOT_FOUND = "LEG-OPN-001"
    OPINION_EXPIRED = "LEG-OPN-002"

    # Override
    OVERRIDE_NOT_ALLOWED = "LEG-OVR-001"
    OVERRIDE_EXPIRED = "LEG-OVR-002"


# ============================================================================
# Base Legal Exception
# ============================================================================
class LegalError(Exception):
    """
    Base exception untuk semua error legal.
    Mendukung detail error code, konteks, dan hash untuk audit trail.
    """

    def __init__(
        self,
        message: str,
        error_code: str = LegalErrorCode.GENERIC,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
        self.cause = cause
        self.timestamp = datetime.utcnow()
        self.exception_id = uuid4()
        self._hash = self._compute_hash()
        logger.error(f"[{error_code}] {message} (id={self.exception_id})")

    def _compute_hash(self) -> str:
        data = {
            "exception_id": str(self.exception_id),
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "exception_id": str(self.exception_id),
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "hash": self._hash,
            "traceback": traceback.format_exc() if self.cause else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ============================================================================
# Specific Exceptions (dengan convenience constructors)
# ============================================================================
class JurisdictionError(LegalError):
    """Error terkait yurisdiksi (tidak dikenali, tidak didukung)."""

    def __init__(
        self,
        message: str,
        jurisdiction_code: str | None = None,
        context: dict | None = None,
    ):
        full_context = {"jurisdiction_code": jurisdiction_code, **(context or {})}
        super().__init__(
            message=message,
            error_code=LegalErrorCode.JURISDICTION_UNSUPPORTED,
            context=full_context,
        )
        self.jurisdiction_code = jurisdiction_code


class RegulatoryFilingError(LegalError):
    """Error saat melakukan filing ke regulator."""

    def __init__(
        self,
        message: str,
        filing_id: UUID | None = None,
        regulatory_body: str | None = None,
        reason: str | None = None,
        context: dict | None = None,
    ):
        full_context = {
            "filing_id": str(filing_id) if filing_id else None,
            "regulatory_body": regulatory_body,
            "reason": reason,
            **(context or {}),
        }
        super().__init__(
            message=message,
            error_code=LegalErrorCode.FILING_REJECTED,
            context=full_context,
        )
        self.filing_id = filing_id
        self.regulatory_body = regulatory_body
        self.reason = reason


class SanctionListHitError(LegalError):
    """Error karena pihak yang bertransaksi masuk daftar sanksi."""

    def __init__(
        self,
        message: str,
        party_name: str,
        sanction_list: str,
        context: dict | None = None,
    ):
        full_context = {
            "party_name": party_name,
            "sanction_list": sanction_list,
            **(context or {}),
        }
        super().__init__(
            message=message,
            error_code=LegalErrorCode.SANCTION_LIST_HIT,
            context=full_context,
        )
        self.party_name = party_name
        self.sanction_list = sanction_list


class SovereigntyViolationError(LegalError):
    """Violasi batas kedaulatan data atau yurisdiksi."""

    def __init__(
        self,
        message: str,
        source_jurisdiction: str | None = None,
        target_jurisdiction: str | None = None,
        data_type: str | None = None,
        context: dict | None = None,
    ):
        full_context = {
            "source_jurisdiction": source_jurisdiction,
            "target_jurisdiction": target_jurisdiction,
            "data_type": data_type,
            **(context or {}),
        }
        super().__init__(
            message=message,
            error_code=LegalErrorCode.SOVEREIGNTY_VIOLATION,
            context=full_context,
        )
        self.source_jurisdiction = source_jurisdiction
        self.target_jurisdiction = target_jurisdiction


class LegalOpinionNotFoundError(LegalError):
    """Opini hukum tidak ditemukan atau kadaluarsa."""

    def __init__(
        self,
        message: str,
        opinion_id: UUID | None = None,
        subject: str | None = None,
        context: dict | None = None,
    ):
        full_context = {
            "opinion_id": str(opinion_id) if opinion_id else None,
            "subject": subject,
            **(context or {}),
        }
        super().__init__(
            message=message,
            error_code=LegalErrorCode.OPINION_NOT_FOUND,
            context=full_context,
        )


class OverrideNotAllowedError(LegalError):
    """Override tidak diizinkan karena alasan legal."""

    def __init__(
        self,
        message: str,
        rule_id: str | None = None,
        legal_citation: str | None = None,
        context: dict | None = None,
    ):
        full_context = {
            "rule_id": rule_id,
            "legal_citation": legal_citation,
            **(context or {}),
        }
        super().__init__(
            message=message,
            error_code=LegalErrorCode.OVERRIDE_NOT_ALLOWED,
            context=full_context,
        )


# ============================================================================
# Exception Registry (for audit)
# ============================================================================
class LegalExceptionRegistry:
    """Registry untuk mencatat semua exception yang terjadi di modul legal."""

    _instance = None
    _exceptions: list[dict] = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, error: LegalError) -> None:
        self._exceptions.append(error.to_dict())
        logger.debug(f"Exception registered: {error.exception_id}")

    def get_all(self, limit: int = 100) -> list[dict]:
        return self._exceptions[-limit:]

    def get_by_code(self, error_code: str) -> list[dict]:
        return [e for e in self._exceptions if e.get("error_code") == error_code]

    def clear(self) -> None:
        self._exceptions.clear()

    def get_summary(self) -> dict:
        from collections import Counter

        codes = Counter(e.get("error_code") for e in self._exceptions)
        return {
            "total": len(self._exceptions),
            "by_error_code": dict(codes),
            "last_error": self._exceptions[-1] if self._exceptions else None,
        }


# ============================================================================
# Helper Functions (convenience raises)
# ============================================================================
def raise_jurisdiction_not_supported(jurisdiction_code: str) -> None:
    raise JurisdictionError(
        message=f"Jurisdiction '{jurisdiction_code}' is not supported",
        jurisdiction_code=jurisdiction_code,
    )


def raise_sanction_hit(party_name: str, sanction_list: str) -> None:
    raise SanctionListHitError(
        message=f"Party '{party_name}' is listed in {sanction_list}",
        party_name=party_name,
        sanction_list=sanction_list,
    )


def raise_filing_rejected(filing_id: UUID, regulatory_body: str, reason: str) -> None:
    raise RegulatoryFilingError(
        message=f"Filing {filing_id} to {regulatory_body} rejected: {reason}",
        filing_id=filing_id,
        regulatory_body=regulatory_body,
        reason=reason,
    )


def raise_sovereignty_violation(source: str, target: str, data_type: str) -> None:
    raise SovereigntyViolationError(
        message=f"Data transfer from {source} to {target} is not allowed for {data_type}",
        source_jurisdiction=source,
        target_jurisdiction=target,
        data_type=data_type,
    )


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    registry = LegalExceptionRegistry()

    try:
        raise_jurisdiction_not_supported("XY")
    except JurisdictionError as e:
        print(e.to_json())
        registry.register(e)

    try:
        raise_sanction_hit("Bad Guy", "OFAC SDN")
    except SanctionListHitError as e:
        print(e.to_json())
        registry.register(e)

    print("\nRegistry Summary:")
    print(registry.get_summary())
