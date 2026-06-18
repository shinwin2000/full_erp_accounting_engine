#!/usr/bin/env python3
"""
Module: evidence_mandate_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: setiap jurnal wajib memiliki evidence.
               Memastikan bahwa setiap jurnal yang diposting memiliki bukti
               pendukung yang sah (dokumen sumber, kontrak, faktur, dll).
               Tanpa bukti, jurnal tidak dapat diposting.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, EvidenceMandateViolation)

Audit: Setiap jurnal tanpa evidence dictat sebagai pelanggaran hukum.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    EvidenceMandateViolation,
    LawViolationSeverity,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackEvidenceRepository:
    """Fallback evidence repository dengan in-memory storage."""

    def __init__(self):
        self._evidences: dict[UUID, dict[str, Any]] = {}
        self._journal_links: dict[UUID, list[UUID]] = {}
        self._evidence_by_type: dict[str, list[UUID]] = {}
        self._evidence_by_user: dict[str, list[UUID]] = {}

    async def get_by_id(self, evidence_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        ev = self._evidences.get(evidence_id)
        if ev and ev.get("legal_entity_id") == legal_entity_id:
            return ev
        return None

    async def get_by_journal(self, journal_id: UUID, legal_entity_id: UUID) -> list[Any]:
        evidence_ids = self._journal_links.get(journal_id, [])
        result = []
        for eid in evidence_ids:
            ev = self._evidences.get(eid)
            if ev and ev.get("legal_entity_id") == legal_entity_id:
                result.append(_EvidenceProxy(ev))
        return result

    async def get_by_type(self, evidence_type: str, legal_entity_id: UUID) -> list[Any]:
        evidence_ids = self._evidence_by_type.get(evidence_type, [])
        result = []
        for eid in evidence_ids:
            ev = self._evidences.get(eid)
            if ev and ev.get("legal_entity_id") == legal_entity_id:
                result.append(_EvidenceProxy(ev))
        return result

    async def get_by_uploader(self, uploaded_by: str, legal_entity_id: UUID) -> list[Any]:
        evidence_ids = self._evidence_by_user.get(uploaded_by, [])
        result = []
        for eid in evidence_ids:
            ev = self._evidences.get(eid)
            if ev and ev.get("legal_entity_id") == legal_entity_id:
                result.append(_EvidenceProxy(ev))
        return result

    async def get_by_time_range(
        self,
        legal_entity_id: UUID,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Any]:
        result = []
        for ev in self._evidences.values():
            if ev.get("legal_entity_id") != legal_entity_id:
                continue
            uploaded_at = ev.get("uploaded_at")
            if uploaded_at and from_date <= uploaded_at <= to_date:
                result.append(_EvidenceProxy(ev))
        return result

    async def attach_to_journal(
        self,
        evidence_id: UUID,
        journal_id: UUID,
        legal_entity_id: UUID,
        attached_by: str,
        attached_at: datetime,
    ) -> bool:
        # Verify evidence belongs to legal entity
        ev = self._evidences.get(evidence_id)
        if not ev or ev.get("legal_entity_id") != legal_entity_id:
            return False
        self._journal_links.setdefault(journal_id, []).append(evidence_id)
        logger.info(f"Evidence {evidence_id} attached to journal {journal_id} by {attached_by}")
        return True

    async def detach_from_journal(
        self,
        evidence_id: UUID,
        journal_id: UUID,
        legal_entity_id: UUID,
        detached_by: str,
    ) -> bool:
        if journal_id in self._journal_links:
            if evidence_id in self._journal_links[journal_id]:
                self._journal_links[journal_id].remove(evidence_id)
                logger.info(
                    f"Evidence {evidence_id} detached from journal {journal_id} by {detached_by}"
                )
                return True
        return False

    async def add_evidence(
        self,
        evidence_id: UUID,
        legal_entity_id: UUID,
        filename: str,
        file_hash: str,
        file_size: int,
        mime_type: str,
        evidence_type: str,
        uploaded_by: str,
        uploaded_at: datetime,
        storage_path: str,
        description: str | None,
        quality: str,
    ) -> None:
        evidence = {
            "evidence_id": evidence_id,
            "legal_entity_id": legal_entity_id,
            "filename": filename,
            "file_hash": file_hash,
            "file_size": file_size,
            "mime_type": mime_type,
            "evidence_type": evidence_type,
            "uploaded_by": uploaded_by,
            "uploaded_at": uploaded_at,
            "storage_path": storage_path,
            "description": description,
            "quality": quality,
            "verification_status": "PENDING",
            "verified_at": None,
            "verified_by": None,
            "expiry_date": None,
        }
        self._evidences[evidence_id] = evidence
        self._evidence_by_type.setdefault(evidence_type, []).append(evidence_id)
        self._evidence_by_user.setdefault(uploaded_by, []).append(evidence_id)

    async def update_verification_status(
        self,
        evidence_id: UUID,
        legal_entity_id: UUID,
        status: str,
        verified_by: str,
        verified_at: datetime,
    ) -> bool:
        ev = self._evidences.get(evidence_id)
        if not ev or ev.get("legal_entity_id") != legal_entity_id:
            return False
        ev["verification_status"] = status
        ev["verified_by"] = verified_by
        ev["verified_at"] = verified_at
        return True

    async def set_expiry(
        self,
        evidence_id: UUID,
        legal_entity_id: UUID,
        expiry_date: datetime,
    ) -> bool:
        ev = self._evidences.get(evidence_id)
        if not ev or ev.get("legal_entity_id") != legal_entity_id:
            return False
        ev["expiry_date"] = expiry_date
        return True

    def clear(self) -> None:
        self._evidences.clear()
        self._journal_links.clear()
        self._evidence_by_type.clear()
        self._evidence_by_user.clear()


class _EvidenceProxy:
    def __init__(self, data: dict[str, Any]):
        self.evidence_id = data.get("evidence_id")
        self.filename = data.get("filename", "")
        self.file_size = data.get("file_size", 0)
        self.mime_type = data.get("mime_type", "")
        self.file_hash = data.get("file_hash", "")
        self.uploaded_by = data.get("uploaded_by", "")
        self.uploaded_at = data.get("uploaded_at", datetime.now(UTC))
        self.description = data.get("description", "")
        self.storage_path = data.get("storage_path", "")
        self.evidence_type = data.get("evidence_type", "")
        self.quality = data.get("quality", "medium")
        self.verification_status = data.get("verification_status", "PENDING")
        self.verified_by = data.get("verified_by")
        self.verified_at = data.get("verified_at")
        self.expiry_date = data.get("expiry_date")

    def is_expired(self) -> bool:
        if self.expiry_date:
            return datetime.now(UTC) > self.expiry_date
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": str(self.evidence_id),
            "filename": self.filename,
            "file_hash": self.file_hash[:16] + "...",
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "evidence_type": self.evidence_type,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at.isoformat(),
            "quality": self.quality,
            "verification_status": self.verification_status,
            "description": self.description[:100] if self.description else None,
            "is_expired": self.is_expired(),
        }


class _FallbackJournalRepository:
    def __init__(self):
        self._journals: dict[UUID, dict[str, Any]] = {}

    async def get_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        journal = self._journals.get(journal_id)
        if journal and journal.get("legal_entity_id") == legal_entity_id:
            return journal
        return None

    async def update_status(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        new_status: str,
        updated_by: str,
    ) -> bool:
        journal = self._journals.get(journal_id)
        if journal and journal.get("legal_entity_id") == legal_entity_id:
            journal["status"] = new_status
            journal["updated_by"] = updated_by
            journal["updated_at"] = datetime.now(UTC)
            return True
        return False

    def add_journal(
        self, journal_id: UUID, legal_entity_id: UUID, journal_type: str, status: str = "DRAFT"
    ) -> None:
        self._journals[journal_id] = {
            "journal_id": journal_id,
            "legal_entity_id": legal_entity_id,
            "journal_type": journal_type,
            "status": status,
            "created_at": datetime.now(UTC),
        }


# === 2. CONSTANTS & ENUMS ===


class EvidenceType(Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    CONTRACT = "contract"
    DELIVERY_NOTE = "delivery_note"
    BANK_STATEMENT = "bank_statement"
    APPROVAL_FORM = "approval_form"
    PHOTO = "photo"
    CALCULATION = "calculation"
    OTHER = "other"


class EvidenceQuality(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class EvidenceVerificationStatus(Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class Evidence:
    evidence_id: UUID
    filename: str
    file_hash: str
    file_size: int
    mime_type: str
    evidence_type: EvidenceType
    uploaded_by: str
    uploaded_at: datetime
    storage_path: str
    description: str | None = None
    quality: EvidenceQuality = EvidenceQuality.MEDIUM
    verification_status: EvidenceVerificationStatus = EvidenceVerificationStatus.PENDING
    verified_by: str | None = None
    verified_at: datetime | None = None
    expiry_date: datetime | None = None
    legal_entity_id: UUID | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.evidence_id}|{self.filename}|{self.file_hash}|{self.file_size}|"
            f"{self.mime_type}|{self.evidence_type.value}|{self.uploaded_by}|{self.storage_path}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def is_expired(self) -> bool:
        if self.expiry_date:
            return datetime.now(UTC) > self.expiry_date
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": str(self.evidence_id),
            "filename": self.filename,
            "file_hash": self.file_hash[:16] + "...",
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "evidence_type": self.evidence_type.value,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at.isoformat(),
            "quality": self.quality.value,
            "verification_status": self.verification_status.value,
            "description": self.description[:100] if self.description else None,
            "is_expired": self.is_expired(),
        }


@dataclass
class EvidenceRequirement:
    journal_type: str
    is_mandatory: bool
    min_evidence_count: int
    required_types: list[EvidenceType]
    amount_threshold: Decimal | None = None
    quality_required: EvidenceQuality = EvidenceQuality.MEDIUM
    requires_verification: bool = True
    expiry_days: int | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_type": self.journal_type,
            "is_mandatory": self.is_mandatory,
            "min_evidence_count": self.min_evidence_count,
            "required_types": [t.value for t in self.required_types],
            "amount_threshold": str(self.amount_threshold) if self.amount_threshold else None,
            "quality_required": self.quality_required.value,
            "requires_verification": self.requires_verification,
            "expiry_days": self.expiry_days,
            "description": self.description[:100],
        }


# === 3. DEFAULT EVIDENCE REQUIREMENTS ===

DEFAULT_EVIDENCE_REQUIREMENTS: dict[str, EvidenceRequirement] = {
    "ADJUSTING_JOURNAL": EvidenceRequirement(
        journal_type="ADJUSTING_JOURNAL",
        is_mandatory=True,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM, EvidenceType.CONTRACT],
        quality_required=EvidenceQuality.HIGH,
        requires_verification=True,
        description="Adjusting journals require approval form and supporting document",
    ),
    "CORRECTION_JOURNAL": EvidenceRequirement(
        journal_type="CORRECTION_JOURNAL",
        is_mandatory=True,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM],
        quality_required=EvidenceQuality.HIGH,
        requires_verification=True,
        description="Correction journals require approval form",
    ),
    "REVERSAL_JOURNAL": EvidenceRequirement(
        journal_type="REVERSAL_JOURNAL",
        is_mandatory=True,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM],
        quality_required=EvidenceQuality.HIGH,
        requires_verification=True,
        description="Reversal journals require approval form",
    ),
    "ASSET_DISPOSAL": EvidenceRequirement(
        journal_type="ASSET_DISPOSAL",
        is_mandatory=True,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM, EvidenceType.CONTRACT],
        quality_required=EvidenceQuality.HIGH,
        requires_verification=True,
        description="Asset disposal requires approval and contract/documentation",
    ),
    "BAD_DEBT_WRITE_OFF": EvidenceRequirement(
        journal_type="BAD_DEBT_WRITE_OFF",
        is_mandatory=True,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM],
        quality_required=EvidenceQuality.HIGH,
        requires_verification=True,
        description="Bad debt write-off requires management approval",
    ),
    "JOURNAL_POST": EvidenceRequirement(
        journal_type="JOURNAL_POST",
        is_mandatory=False,
        min_evidence_count=0,
        required_types=[],
        quality_required=EvidenceQuality.MEDIUM,
        requires_verification=False,
        description="Regular journal posts are optional but recommended",
    ),
    "CLOSING_JOURNAL": EvidenceRequirement(
        journal_type="CLOSING_JOURNAL",
        is_mandatory=False,
        min_evidence_count=0,
        required_types=[EvidenceType.APPROVAL_FORM],
        amount_threshold=Decimal("100000000"),
        quality_required=EvidenceQuality.MEDIUM,
        requires_verification=True,
        description="Closing journals require approval if above threshold",
    ),
    "DEPRECIATION_JOURNAL": EvidenceRequirement(
        journal_type="DEPRECIATION_JOURNAL",
        is_mandatory=False,
        min_evidence_count=0,
        required_types=[EvidenceType.CALCULATION],
        quality_required=EvidenceQuality.MEDIUM,
        requires_verification=False,
        description="Depreciation journals should have calculation sheet",
    ),
    "ACCRUAL_JOURNAL": EvidenceRequirement(
        journal_type="ACCRUAL_JOURNAL",
        is_mandatory=False,
        min_evidence_count=0,
        required_types=[EvidenceType.CONTRACT],
        amount_threshold=Decimal("50000000"),
        quality_required=EvidenceQuality.MEDIUM,
        requires_verification=True,
        description="Accruals above threshold require contract",
    ),
    "INTERCOMPANY_JOURNAL": EvidenceRequirement(
        journal_type="INTERCOMPANY_JOURNAL",
        is_mandatory=True,
        min_evidence_count=1,
        required_types=[EvidenceType.CONTRACT, EvidenceType.APPROVAL_FORM],
        quality_required=EvidenceQuality.HIGH,
        requires_verification=True,
        description="Intercompany journals require contract and approval",
    ),
    "PAYMENT_JOURNAL": EvidenceRequirement(
        journal_type="PAYMENT_JOURNAL",
        is_mandatory=True,
        min_evidence_count=1,
        required_types=[EvidenceType.INVOICE, EvidenceType.RECEIPT],
        quality_required=EvidenceQuality.MEDIUM,
        requires_verification=True,
        description="Payment journals require invoice or receipt",
    ),
    "RECEIPT_JOURNAL": EvidenceRequirement(
        journal_type="RECEIPT_JOURNAL",
        is_mandatory=True,
        min_evidence_count=1,
        required_types=[EvidenceType.RECEIPT],
        quality_required=EvidenceQuality.MEDIUM,
        requires_verification=True,
        description="Receipt journals require receipt document",
    ),
}


# === 4. EVIDENCE MANDATE ENFORCER ===


class EvidenceMandateEnforcer:
    """
    Enforcer untuk hukum evidence mandate.

    Business context: Setiap jurnal wajib memiliki bukti pendukung
    untuk memastikan akuntabilitas dan auditability.
    """

    def __init__(
        self,
        journal_repository: Any | None = None,
        evidence_repository: Any | None = None,
    ):
        self._journal_repo = journal_repository or _FallbackJournalRepository()
        self._evidence_repo = evidence_repository or _FallbackEvidenceRepository()
        self._requirements = DEFAULT_EVIDENCE_REQUIREMENTS.copy()
        self._violation_history: list[EvidenceMandateViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._strict_mode = True

    def enable(self, enabled: bool = True) -> None:
        self._enabled = enabled
        logger.info(f"Evidence mandate enforcer enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        self._strict_mode = strict
        logger.info(f"Evidence mandate enforcer strict mode: {strict}")

    def register_requirement(self, requirement: EvidenceRequirement) -> None:
        with self._lock:
            self._requirements[requirement.journal_type] = requirement
        logger.info(f"Registered evidence requirement for {requirement.journal_type}")

    def get_requirement(self, journal_type: str) -> EvidenceRequirement | None:
        return self._requirements.get(journal_type)

    def get_all_requirements(self) -> dict[str, EvidenceRequirement]:
        return self._requirements.copy()

    async def enforce_evidence_mandate(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        journal_type: str,
        amount: Decimal | None = None,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, EvidenceMandateViolation | None]:
        if not self._enabled:
            return True, None

        if user_id is None:
            user_id = get_current_user() or "unknown"

        requirement = self._requirements.get(journal_type)
        if not requirement:
            return True, None

        effective_mandatory = requirement.is_mandatory
        if not effective_mandatory and requirement.amount_threshold and amount:
            if amount >= requirement.amount_threshold:
                effective_mandatory = True

        if not effective_mandatory:
            return True, None

        evidence_list = await self._evidence_repo.get_by_journal(journal_id, legal_entity_id)
        evidence_objects = []
        for ev in evidence_list:
            expiry = getattr(ev, "expiry_date", None)
            is_expired = (expiry and datetime.now(UTC) > expiry) if expiry else False
            if is_expired:
                continue
            evidence_objects.append(ev)

        if len(evidence_objects) < requirement.min_evidence_count:
            violation = EvidenceMandateViolation(
                message=(
                    f"Journal type {journal_type} requires at least {requirement.min_evidence_count} "
                    f"supporting evidence(s). Found {len(evidence_objects)}."
                ),
                journal_id=str(journal_id),
                journal_type=journal_type,
                severity=LawViolationSeverity.CRITICAL,
                details={
                    "journal_id": str(journal_id),
                    "journal_type": journal_type,
                    "required_count": requirement.min_evidence_count,
                    "actual_count": len(evidence_objects),
                    "amount": str(amount) if amount else None,
                },
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise violation
            return False, violation

        if requirement.required_types:
            evidence_types = [getattr(e, "evidence_type", "") for e in evidence_objects]
            missing_types = [t for t in requirement.required_types if t.value not in evidence_types]
            if missing_types:
                violation = EvidenceMandateViolation(
                    message=(
                        f"Journal type {journal_type} requires evidence of type(s): "
                        f"{[t.value for t in missing_types]}. Missing: {[t.value for t in missing_types]}"
                    ),
                    journal_id=str(journal_id),
                    journal_type=journal_type,
                    severity=LawViolationSeverity.HIGH,
                    details={
                        "journal_id": str(journal_id),
                        "journal_type": journal_type,
                        "required_types": [t.value for t in requirement.required_types],
                        "missing_types": [t.value for t in missing_types],
                    },
                )
                self._record_violation(violation)
                if raise_on_violation:
                    raise violation
                return False, violation

        if requirement.requires_verification:
            for ev in evidence_objects:
                status = getattr(ev, "verification_status", "PENDING")
                if status != "VERIFIED":
                    violation = EvidenceMandateViolation(
                        message=(
                            f"Evidence {getattr(ev, 'evidence_id', 'unknown')} not verified "
                            f"(status: {status})"
                        ),
                        journal_id=str(journal_id),
                        journal_type=journal_type,
                        severity=LawViolationSeverity.HIGH,
                        details={
                            "evidence_id": str(getattr(ev, "evidence_id", "")),
                            "status": status,
                        },
                    )
                    self._record_violation(violation)
                    if raise_on_violation:
                        raise violation
                    return False, violation

        if requirement.quality_required != EvidenceQuality.INSUFFICIENT:
            for ev in evidence_objects:
                quality = getattr(ev, "quality", "medium")
                required_quality = requirement.quality_required.value
                quality_order = {"high": 3, "medium": 2, "low": 1, "insufficient": 0}
                if quality_order.get(quality, 0) < quality_order.get(required_quality, 0):
                    if self._strict_mode:
                        violation = EvidenceMandateViolation(
                            message=(
                                f"Evidence {getattr(ev, 'evidence_id', 'unknown')} quality {quality} "
                                f"is below required {required_quality}"
                            ),
                            journal_id=str(journal_id),
                            journal_type=journal_type,
                            severity=LawViolationSeverity.MEDIUM,
                            details={
                                "evidence_id": str(getattr(ev, "evidence_id", "")),
                                "quality": quality,
                                "required_quality": required_quality,
                            },
                        )
                        self._record_violation(violation)
                        if raise_on_violation:
                            raise violation
                        return False, violation
                    else:
                        logger.warning(
                            f"Evidence quality {quality} below required {required_quality}"
                        )

        return True, None

    async def validate_evidence_quality(
        self,
        evidence_id: UUID,
        legal_entity_id: UUID,
    ) -> tuple[EvidenceQuality, list[str]]:
        evidence = await self._evidence_repo.get_by_id(evidence_id, legal_entity_id)
        if not evidence:
            return EvidenceQuality.INSUFFICIENT, ["Evidence not found"]

        issues = []
        quality = EvidenceQuality.HIGH

        if evidence.get("file_size", 0) > 50 * 1024 * 1024:
            issues.append("File size exceeds 50MB limit")
            quality = EvidenceQuality.LOW

        allowed_mime = [
            "application/pdf",
            "image/jpeg",
            "image/png",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ]
        mime = evidence.get("mime_type", "")
        if mime not in allowed_mime:
            issues.append(f"MIME type {mime} not allowed")
            quality = EvidenceQuality.LOW

        if not evidence.get("description"):
            issues.append("Missing description")
            quality = EvidenceQuality.MEDIUM

        uploaded_by = evidence.get("uploaded_by", "")
        if uploaded_by == "unknown" or uploaded_by == "system":
            issues.append("Uploaded by unknown/system, low accountability")
            quality = EvidenceQuality.MEDIUM

        return quality, issues

    async def create_evidence(
        self,
        filename: str,
        file_content: bytes,
        mime_type: str,
        evidence_type: EvidenceType,
        legal_entity_id: UUID,
        description: str | None = None,
        uploaded_by: str | None = None,
        quality: EvidenceQuality | None = None,
        expiry_days: int | None = None,
    ) -> Evidence:
        if uploaded_by is None:
            uploaded_by = get_current_user() or "system"

        file_hash = hashlib.sha256(file_content).hexdigest()
        file_size = len(file_content)

        storage_path = f"evidence/{evidence_type.value}/{uuid4()}/{filename}"
        evidence_id = uuid4()

        expiry_date = None
        if expiry_days:
            expiry_date = datetime.now(UTC) + timedelta(days=expiry_days)

        evidence = Evidence(
            evidence_id=evidence_id,
            filename=filename,
            file_hash=file_hash,
            file_size=file_size,
            mime_type=mime_type,
            evidence_type=evidence_type,
            uploaded_by=uploaded_by,
            uploaded_at=datetime.now(UTC),
            storage_path=storage_path,
            description=description,
            quality=quality or EvidenceQuality.MEDIUM,
            verification_status=EvidenceVerificationStatus.PENDING,
            expiry_date=expiry_date,
            legal_entity_id=legal_entity_id,
            cryptographic_hash="",
        )
        evidence.cryptographic_hash = evidence.compute_hash()

        await self._evidence_repo.add_evidence(
            evidence_id=evidence_id,
            legal_entity_id=legal_entity_id,
            filename=filename,
            file_hash=file_hash,
            file_size=file_size,
            mime_type=mime_type,
            evidence_type=evidence_type.value,
            uploaded_by=uploaded_by,
            uploaded_at=evidence.uploaded_at,
            storage_path=storage_path,
            description=description,
            quality=evidence.quality.value,
        )

        logger.info(f"Evidence created: {evidence_id} - {filename} by {uploaded_by}")
        return evidence

    async def attach_evidence_to_journal(
        self,
        journal_id: UUID,
        evidence_id: UUID,
        legal_entity_id: UUID,
        attached_by: str | None = None,
    ) -> bool:
        if attached_by is None:
            attached_by = get_current_user() or "system"

        success = await self._evidence_repo.attach_to_journal(
            evidence_id=evidence_id,
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            attached_by=attached_by,
            attached_at=datetime.now(UTC),
        )
        if success:
            logger.info(f"Evidence {evidence_id} attached to journal {journal_id} by {attached_by}")
        return success

    async def detach_evidence_from_journal(
        self,
        journal_id: UUID,
        evidence_id: UUID,
        legal_entity_id: UUID,
        detached_by: str | None = None,
    ) -> bool:
        if detached_by is None:
            detached_by = get_current_user() or "system"

        success = await self._evidence_repo.detach_from_journal(
            evidence_id=evidence_id,
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            detached_by=detached_by,
        )
        if success:
            logger.info(
                f"Evidence {evidence_id} detached from journal {journal_id} by {detached_by}"
            )
        return success

    async def verify_evidence(
        self,
        evidence_id: UUID,
        legal_entity_id: UUID,
        verified_by: str,
        status: EvidenceVerificationStatus = EvidenceVerificationStatus.VERIFIED,
        notes: str | None = None,
    ) -> bool:
        success = await self._evidence_repo.update_verification_status(
            evidence_id=evidence_id,
            legal_entity_id=legal_entity_id,
            status=status.value,
            verified_by=verified_by,
            verified_at=datetime.now(UTC),
        )
        if success:
            logger.info(
                f"Evidence {evidence_id} verification status set to {status.value} by {verified_by}"
            )
        return success

    async def get_evidence_summary(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
    ) -> dict[str, Any]:
        evidence_list = await self._evidence_repo.get_by_journal(journal_id, legal_entity_id)
        return {
            "journal_id": str(journal_id),
            "evidence_count": len(evidence_list),
            "evidence": [ev.to_dict() for ev in evidence_list],
        }

    async def get_evidence_by_id(
        self,
        evidence_id: UUID,
        legal_entity_id: UUID,
    ) -> Evidence | None:
        ev_data = await self._evidence_repo.get_by_id(evidence_id, legal_entity_id)
        if not ev_data:
            return None
        return Evidence(
            evidence_id=ev_data["evidence_id"],
            filename=ev_data["filename"],
            file_hash=ev_data["file_hash"],
            file_size=ev_data["file_size"],
            mime_type=ev_data["mime_type"],
            evidence_type=EvidenceType(ev_data["evidence_type"]),
            uploaded_by=ev_data["uploaded_by"],
            uploaded_at=ev_data["uploaded_at"],
            storage_path=ev_data["storage_path"],
            description=ev_data.get("description"),
            quality=EvidenceQuality(ev_data.get("quality", "medium")),
            verification_status=EvidenceVerificationStatus(
                ev_data.get("verification_status", "PENDING")
            ),
            verified_by=ev_data.get("verified_by"),
            verified_at=ev_data.get("verified_at"),
            expiry_date=ev_data.get("expiry_date"),
            legal_entity_id=ev_data.get("legal_entity_id"),
            cryptographic_hash="",
        )

    def _record_violation(self, violation: EvidenceMandateViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)
            if len(self._violation_history) > self._max_history:
                self._violation_history = self._violation_history[-self._max_history :]

    def get_violations(
        self,
        limit: int = 100,
        journal_type: str | None = None,
        unresolved_only: bool = False,
    ) -> list[EvidenceMandateViolation]:
        with self._lock:
            result = self._violation_history[-limit:]
        if journal_type:
            result = [v for v in result if v.journal_type == journal_type]
        if unresolved_only:
            result = [v for v in result if not getattr(v, "is_resolved", False)]
        return result

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._violation_history)
            if total == 0:
                return {
                    "total_violations": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                }

            by_journal_type = {}
            for v in self._violation_history:
                jt = v.journal_type
                by_journal_type[jt] = by_journal_type.get(jt, 0) + 1

            by_severity = {}
            for v in self._violation_history:
                by_severity[v.severity.name] = by_severity.get(v.severity.name, 0) + 1

            return {
                "total_violations": total,
                "by_journal_type": by_journal_type,
                "by_severity": by_severity,
                "active_requirements": len(self._requirements),
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "latest_violation": self._violation_history[-1].timestamp.isoformat()
                if self._violation_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._violation_history = []
            self._requirements = DEFAULT_EVIDENCE_REQUIREMENTS.copy()
            self._enabled = True
            self._strict_mode = True


# === 5. SINGLETON ACCESSOR ===

_evidence_mandate_enforcer_instance: EvidenceMandateEnforcer | None = None
_lock_instance = threading.Lock()


def get_evidence_mandate_enforcer() -> EvidenceMandateEnforcer:
    global _evidence_mandate_enforcer_instance
    if _evidence_mandate_enforcer_instance is None:
        with _lock_instance:
            if _evidence_mandate_enforcer_instance is None:
                _evidence_mandate_enforcer_instance = EvidenceMandateEnforcer()
    return _evidence_mandate_enforcer_instance


# === 6. EXPORTS ===

__all__ = [
    "Evidence",
    "EvidenceMandateEnforcer",
    "EvidenceQuality",
    "EvidenceRequirement",
    "EvidenceType",
    "EvidenceVerificationStatus",
    "get_evidence_mandate_enforcer",
]
