#!/usr/bin/env python3
"""
Module: evidence_attacher.py
Layer: 4 - Kernel / Guards
Responsibility: Memastikan setiap transaksi memiliki bukti pendukung (dokumen).
               Guard ini memvalidasi bahwa transaksi yang memerlukan bukti
               (seperti jurnal penyesuaian, pengeluaran kas, penghapusan aset)
               memiliki dokumen pendukung yang sah sebelum diproses.

Dependencies:
- standard library (logging, hashlib, base64, datetime, typing, uuid, mimetypes)
- kernel.context_holder (get_current_user, get_current_legal_entity)
- kernel.guards.guard_exceptions (GuardViolationError, EvidenceAttacherError, GuardSeverity)

Audit: Setiap bukti yang dilampirkan dictat dengan hash untuk integritas.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_legal_entity, get_current_user
from kernel.guards.guard_exceptions import (
    EvidenceAttacherError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK FILE STORAGE (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackFileStorage:
    """
    Fallback file storage jika infrastructure belum tersedia.
    Menyimpan file dalam memory dengan metadata lengkap.
    Tidak mengimpor apapun dari adapters atau infrastructure.
    """

    def __init__(self):
        self._storage: dict[str, bytes] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._max_size_bytes = 100 * 1024 * 1024  # 100 MB limit
        self._total_used_bytes = 0

    async def upload(self, path: str, content: bytes, mime_type: str) -> bool:
        """Upload file ke storage."""
        if len(content) > self._max_size_bytes:
            logger.error(f"File too large: {len(content)} bytes, max {self._max_size_bytes}")
            return False
        self._storage[path] = content
        self._total_used_bytes += len(content)
        self._metadata[path] = {
            "size": len(content),
            "mime_type": mime_type,
            "uploaded_at": datetime.now(UTC).isoformat(),
            "last_accessed": None,
            "hash": hashlib.sha256(content).hexdigest(),
        }
        return True

    async def download(self, path: str) -> bytes | None:
        """Download file dari storage."""
        if path in self._storage:
            # Update last accessed
            if path in self._metadata:
                self._metadata[path]["last_accessed"] = datetime.now(UTC).isoformat()
            return self._storage[path]
        return None

    async def delete(self, path: str) -> bool:
        """Delete file dari storage."""
        if path in self._storage:
            size = len(self._storage[path])
            self._total_used_bytes -= size
            del self._storage[path]
            if path in self._metadata:
                del self._metadata[path]
            return True
        return False

    async def get_metadata(self, path: str) -> dict[str, Any] | None:
        """Mendapatkan metadata file."""
        return self._metadata.get(path)

    async def exists(self, path: str) -> bool:
        """Cek apakah file ada."""
        return path in self._storage

    async def get_size(self, path: str) -> int | None:
        """Mendapatkan ukuran file."""
        meta = await self.get_metadata(path)
        return meta.get("size") if meta else None

    async def list_files(self, prefix: str = "") -> list[str]:
        """List file dengan prefix tertentu."""
        return [p for p in self._storage.keys() if p.startswith(prefix)]

    async def get_total_used_bytes(self) -> int:
        """Total bytes yang digunakan."""
        return self._total_used_bytes

    async def clear(self) -> None:
        """Clear semua file (untuk testing)."""
        self._storage.clear()
        self._metadata.clear()
        self._total_used_bytes = 0


# === 2. CONSTANTS & ENUMS ===


class EvidenceRequirement(Enum):
    """Tingkat kebutuhan bukti."""

    MANDATORY = auto()  # Wajib ada bukti
    OPTIONAL = auto()  # Opsional, tapi direkomendasikan
    CONDITIONAL = auto()  # Tergantung jumlah atau kondisi
    NONE = auto()  # Tidak perlu bukti


class EvidenceType(Enum):
    """Jenis bukti pendukung."""

    INVOICE = "invoice"
    RECEIPT = "receipt"
    CONTRACT = "contract"
    DELIVERY_NOTE = "delivery_note"
    BANK_STATEMENT = "bank_statement"
    APPROVAL_FORM = "approval_form"
    PHOTO = "photo"
    SIGNED_DOCUMENT = "signed_document"
    TAX_INVOICE = "tax_invoice"
    OTHER = "other"


class EvidenceVerificationStatus(Enum):
    """Status verifikasi bukti."""

    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass
class Evidence:
    """Representasi bukti pendukung."""

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
    verification_status: EvidenceVerificationStatus = EvidenceVerificationStatus.PENDING
    verified_at: datetime | None = None
    verified_by: str | None = None
    transaction_id: UUID | None = None
    legal_entity_id: UUID | None = None
    expiry_date: datetime | None = None
    tags: list[str] = field(default_factory=list)
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        """Menghitung hash kriptografis untuk integritas record."""
        content = (
            f"{self.evidence_id}|{self.filename}|{self.file_hash}|{self.file_size}|"
            f"{self.mime_type}|{self.evidence_type.value}|{self.uploaded_by}|"
            f"{self.storage_path}|{self.verification_status.value}|{self.transaction_id}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def is_expired(self) -> bool:
        """Cek apakah bukti sudah expired."""
        if self.expiry_date:
            return datetime.now(UTC) > self.expiry_date
        return False

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary untuk serialisasi."""
        return {
            "evidence_id": str(self.evidence_id),
            "filename": self.filename,
            "file_hash": self.file_hash[:16] + "...",
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "evidence_type": self.evidence_type.value,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at.isoformat(),
            "description": self.description[:100] if self.description else None,
            "verification_status": self.verification_status.value,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "tags": self.tags,
            "is_expired": self.is_expired(),
            "hash": self.cryptographic_hash[:16] + "...",
        }


@dataclass
class TransactionEvidenceRequirement:
    """Requirement bukti untuk tipe transaksi."""

    transaction_type: str
    requirement: EvidenceRequirement
    min_evidence_count: int = 1
    required_types: list[EvidenceType] = field(default_factory=list)
    amount_threshold: Decimal | None = None  # Conditional above this amount
    description: str = ""
    requires_verification: bool = True
    expiry_days: int | None = None  # Jika tidak None, bukti akan expired setelah X hari


# === 3. DEFAULT REQUIREMENTS ===

DEFAULT_EVIDENCE_REQUIREMENTS: dict[str, TransactionEvidenceRequirement] = {
    "JOURNAL_POST": TransactionEvidenceRequirement(
        transaction_type="JOURNAL_POST",
        requirement=EvidenceRequirement.OPTIONAL,
        min_evidence_count=0,
        description="General journal entry may have supporting documents",
    ),
    "ADJUSTING_JOURNAL": TransactionEvidenceRequirement(
        transaction_type="ADJUSTING_JOURNAL",
        requirement=EvidenceRequirement.MANDATORY,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM],
        description="Adjusting journal requires approval form",
        requires_verification=True,
    ),
    "CASH_DISBURSEMENT": TransactionEvidenceRequirement(
        transaction_type="CASH_DISBURSEMENT",
        requirement=EvidenceRequirement.CONDITIONAL,
        min_evidence_count=1,
        required_types=[EvidenceType.RECEIPT, EvidenceType.INVOICE],
        amount_threshold=Decimal("1000000"),  # 1 juta
        description="Cash disbursement above 1M requires receipt/invoice",
    ),
    "CASH_RECEIPT": TransactionEvidenceRequirement(
        transaction_type="CASH_RECEIPT",
        requirement=EvidenceRequirement.CONDITIONAL,
        min_evidence_count=1,
        required_types=[EvidenceType.RECEIPT],
        amount_threshold=Decimal("1000000"),
        description="Cash receipt above 1M requires receipt",
    ),
    "ASSET_DISPOSAL": TransactionEvidenceRequirement(
        transaction_type="ASSET_DISPOSAL",
        requirement=EvidenceRequirement.MANDATORY,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM, EvidenceType.CONTRACT],
        description="Asset disposal requires approval form and contract",
        requires_verification=True,
    ),
    "BAD_DEBT_WRITE_OFF": TransactionEvidenceRequirement(
        transaction_type="BAD_DEBT_WRITE_OFF",
        requirement=EvidenceRequirement.MANDATORY,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM],
        description="Bad debt write-off requires approval form",
        requires_verification=True,
    ),
    "PERIOD_CLOSE": TransactionEvidenceRequirement(
        transaction_type="PERIOD_CLOSE",
        requirement=EvidenceRequirement.MANDATORY,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM],
        description="Period close requires approval form",
        requires_verification=True,
    ),
    "INVENTORY_ADJUSTMENT": TransactionEvidenceRequirement(
        transaction_type="INVENTORY_ADJUSTMENT",
        requirement=EvidenceRequirement.MANDATORY,
        min_evidence_count=1,
        required_types=[EvidenceType.APPROVAL_FORM],
        description="Inventory adjustment requires approval form",
        requires_verification=True,
    ),
    "FIXED_ASSET_ACQUISITION": TransactionEvidenceRequirement(
        transaction_type="FIXED_ASSET_ACQUISITION",
        requirement=EvidenceRequirement.MANDATORY,
        min_evidence_count=1,
        required_types=[EvidenceType.INVOICE, EvidenceType.CONTRACT],
        description="Fixed asset acquisition requires invoice/contract",
    ),
    "TAX_PAYMENT": TransactionEvidenceRequirement(
        transaction_type="TAX_PAYMENT",
        requirement=EvidenceRequirement.MANDATORY,
        min_evidence_count=1,
        required_types=[EvidenceType.TAX_INVOICE, EvidenceType.RECEIPT],
        description="Tax payment requires tax invoice or receipt",
    ),
    "INTERCOMPANY_TRANSFER": TransactionEvidenceRequirement(
        transaction_type="INTERCOMPANY_TRANSFER",
        requirement=EvidenceRequirement.MANDATORY,
        min_evidence_count=1,
        required_types=[EvidenceType.CONTRACT, EvidenceType.APPROVAL_FORM],
        description="Intercompany transfer requires contract and approval",
        requires_verification=True,
    ),
}


# === 4. EVIDENCE ATTACHER GUARD ===


class EvidenceAttacherGuard:
    """
    Guard untuk memastikan bukti pendukung transaksi.

    Business context: Mencegah transaksi tanpa bukti yang sah,
    terutama untuk transaksi material atau penyesuaian.
    """

    def __init__(self, file_storage: Any | None = None):
        self._file_storage = file_storage or _FallbackFileStorage()
        self._requirements = DEFAULT_EVIDENCE_REQUIREMENTS.copy()
        self._evidences: dict[UUID, Evidence] = {}
        self._transaction_evidence: dict[
            UUID, list[UUID]
        ] = {}  # transaction_id -> list of evidence_ids
        self._check_history: list[dict[str, Any]] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._auto_verify_on_upload = False

    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan guard."""
        self._enabled = enabled
        logger.info(f"Evidence attacher guard enabled: {enabled}")

    def set_auto_verify(self, auto_verify: bool = True) -> None:
        """Set apakah bukti otomatis diverifikasi setelah upload."""
        self._auto_verify_on_upload = auto_verify
        logger.info(f"Auto-verify on upload: {auto_verify}")

    def register_requirement(self, requirement: TransactionEvidenceRequirement) -> None:
        """Mendaftarkan requirement untuk tipe transaksi baru."""
        with self._lock:
            self._requirements[requirement.transaction_type] = requirement
        logger.info(f"Registered evidence requirement for {requirement.transaction_type}")

    def get_requirement(self, transaction_type: str) -> TransactionEvidenceRequirement | None:
        """Mendapatkan requirement untuk tipe transaksi."""
        return self._requirements.get(transaction_type)

    async def validate_evidence(
        self,
        transaction_type: str,
        evidence_ids: list[UUID],
        amount: Decimal | None = None,
        user_id: str | None = None,
        check_expiry: bool = True,
    ) -> tuple[bool, str | None, list[str]]:
        """
        Memvalidasi apakah bukti mencukupi untuk transaksi.

        Args:
            transaction_type: Tipe transaksi
            evidence_ids: Daftar ID bukti yang dilampirkan
            amount: Jumlah transaksi (untuk conditional requirement)
            user_id: User ID (untuk audit)
            check_expiry: Apakah memeriksa expiry date

        Returns:
            (is_valid, error_message, warnings)
        """
        if not self._enabled:
            return True, None, []

        requirement = self._requirements.get(transaction_type)
        if not requirement:
            # No specific requirement, allow by default
            return True, None, []

        warnings = []
        evidences = []
        for eid in evidence_ids:
            ev = self._evidences.get(eid)
            if ev:
                # Check expiry
                if check_expiry and ev.is_expired():
                    warnings.append(f"Evidence {eid} ({ev.filename}) has expired")
                evidences.append(ev)
            else:
                warnings.append(f"Evidence {eid} not found")

        # Check conditional based on amount
        if requirement.requirement == EvidenceRequirement.CONDITIONAL:
            if (
                amount is not None
                and requirement.amount_threshold is not None
                and amount <= requirement.amount_threshold
            ):
                # Below threshold, no evidence needed
                return True, None, warnings
            # Above threshold, treat as mandatory
            effective_requirement = EvidenceRequirement.MANDATORY
        else:
            effective_requirement = requirement.requirement

        if effective_requirement == EvidenceRequirement.NONE:
            return True, None, warnings

        if effective_requirement == EvidenceRequirement.OPTIONAL:
            if len(evidences) < requirement.min_evidence_count:
                warnings.append(
                    f"Optional: Transaction type {transaction_type} recommends at least {requirement.min_evidence_count} evidence(s)"
                )
            return True, None, warnings

        if effective_requirement == EvidenceRequirement.MANDATORY:
            # Check minimum count
            if len(evidences) < requirement.min_evidence_count:
                return (
                    False,
                    f"Transaction requires at least {requirement.min_evidence_count} evidence(s), got {len(evidences)}",
                    warnings,
                )

            # Check required types if specified
            if requirement.required_types:
                has_required = any(e.evidence_type in requirement.required_types for e in evidences)
                if not has_required:
                    required_names = [t.value for t in requirement.required_types]
                    return (
                        False,
                        f"Transaction requires evidence of type(s): {required_names}",
                        warnings,
                    )

            # Check verification status if required
            if requirement.requires_verification:
                unverified = [
                    e
                    for e in evidences
                    if e.verification_status != EvidenceVerificationStatus.VERIFIED
                ]
                if unverified:
                    return (
                        False,
                        f"Some evidence(s) not verified: {[e.filename for e in unverified]}",
                        warnings,
                    )

            # Check for expired
            if check_expiry:
                expired = [e for e in evidences if e.is_expired()]
                if expired:
                    return (
                        False,
                        f"Some evidence(s) expired: {[e.filename for e in expired]}",
                        warnings,
                    )

        return True, None, warnings

    async def upload_evidence(
        self,
        file_content: bytes,
        filename: str,
        mime_type: str | None,
        evidence_type: EvidenceType,
        transaction_id: UUID | None = None,
        description: str | None = None,
        user_id: str | None = None,
        legal_entity_id: UUID | None = None,
        tags: list[str] | None = None,
        expiry_days: int | None = None,
    ) -> Evidence:
        """
        Mengupload bukti ke storage dan membuat record.

        Args:
            file_content: Konten file
            filename: Nama file
            mime_type: MIME type (auto-detect jika None)
            evidence_type: Jenis bukti
            transaction_id: ID transaksi (optional)
            description: Deskripsi
            user_id: User ID (default dari context)
            legal_entity_id: Entitas hukum (default dari context)
            tags: Tag untuk kategorisasi
            expiry_days: Masa berlaku dalam hari (None = tidak expired)

        Returns:
            Evidence object
        """
        if not self._enabled:
            raise EvidenceAttacherError(
                "Evidence attacher is disabled",
                transaction_type="UPLOAD",
                severity=GuardSeverity.MEDIUM,
            )

        if user_id is None:
            user_id = get_current_user() or "system"
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()

        if mime_type is None:
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Compute file hash for integrity
        file_hash = hashlib.sha256(file_content).hexdigest()
        file_size = len(file_content)

        # Generate storage path
        evidence_id = uuid4()
        storage_path = f"evidence/{legal_entity_id}/{evidence_type.value}/{evidence_id}/{filename}"

        # Upload to storage
        success = await self._file_storage.upload(storage_path, file_content, mime_type)
        if not success:
            raise EvidenceAttacherError(
                f"Failed to upload evidence file: {filename}",
                transaction_type="UPLOAD",
                severity=GuardSeverity.HIGH,
            )

        # Calculate expiry date
        expiry_date = None
        if expiry_days is not None:
            expiry_date = datetime.now(UTC) + timedelta(days=expiry_days)

        evidence = Evidence(
            evidence_id=evidence_id,
            filename=filename,
            file_hash=file_hash,
            file_size=file_size,
            mime_type=mime_type,
            evidence_type=evidence_type,
            uploaded_by=user_id,
            uploaded_at=datetime.now(UTC),
            storage_path=storage_path,
            description=description,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            expiry_date=expiry_date,
            tags=tags or [],
            verification_status=EvidenceVerificationStatus.PENDING,
            cryptographic_hash="",
        )
        evidence = Evidence(
            evidence_id=evidence.evidence_id,
            filename=evidence.filename,
            file_hash=evidence.file_hash,
            file_size=evidence.file_size,
            mime_type=evidence.mime_type,
            evidence_type=evidence.evidence_type,
            uploaded_by=evidence.uploaded_by,
            uploaded_at=evidence.uploaded_at,
            storage_path=evidence.storage_path,
            description=evidence.description,
            verification_status=evidence.verification_status,
            verified_at=evidence.verified_at,
            verified_by=evidence.verified_by,
            transaction_id=evidence.transaction_id,
            legal_entity_id=evidence.legal_entity_id,
            expiry_date=evidence.expiry_date,
            tags=evidence.tags,
            cryptographic_hash=evidence.compute_hash(),
        )

        with self._lock:
            self._evidences[evidence_id] = evidence
            if transaction_id:
                if transaction_id not in self._transaction_evidence:
                    self._transaction_evidence[transaction_id] = []
                self._transaction_evidence[transaction_id].append(evidence_id)

        # Auto-verify if configured
        if self._auto_verify_on_upload:
            await self.verify_evidence(evidence_id, user_id, EvidenceVerificationStatus.VERIFIED)

        logger.info(
            f"Evidence uploaded: {filename} ({file_size} bytes) by {user_id}, id={evidence_id}"
        )
        return evidence

    async def get_evidence(self, evidence_id: UUID) -> Evidence | None:
        """Mendapatkan evidence berdasarkan ID."""
        return self._evidences.get(evidence_id)

    async def get_evidences_for_transaction(self, transaction_id: UUID) -> list[Evidence]:
        """Mendapatkan semua bukti untuk suatu transaksi."""
        evidence_ids = self._transaction_evidence.get(transaction_id, [])
        return [self._evidences[eid] for eid in evidence_ids if eid in self._evidences]

    async def get_evidences_by_type(self, evidence_type: EvidenceType) -> list[Evidence]:
        """Mendapatkan semua bukti dengan tipe tertentu."""
        with self._lock:
            return [e for e in self._evidences.values() if e.evidence_type == evidence_type]

    async def get_evidences_by_user(self, user_id: str) -> list[Evidence]:
        """Mendapatkan semua bukti yang diupload oleh user tertentu."""
        with self._lock:
            return [e for e in self._evidences.values() if e.uploaded_by == user_id]

    async def download_evidence(self, evidence: Evidence) -> bytes | None:
        """Mendownload file bukti."""
        return await self._file_storage.download(evidence.storage_path)

    async def verify_integrity(self, evidence: Evidence) -> bool:
        """Memverifikasi integritas file bukti dengan hash."""
        file_content = await self.download_evidence(evidence)
        if not file_content:
            return False
        computed_hash = hashlib.sha256(file_content).hexdigest()
        return computed_hash == evidence.file_hash

    async def verify_evidence(
        self,
        evidence_id: UUID,
        verified_by: str,
        status: EvidenceVerificationStatus = EvidenceVerificationStatus.VERIFIED,
        rejection_reason: str | None = None,
    ) -> Evidence | None:
        """
        Memverifikasi bukti (menandai sebagai verified/failed/rejected).

        Args:
            evidence_id: ID bukti
            verified_by: User yang melakukan verifikasi
            status: Status verifikasi baru
            rejection_reason: Alasan penolakan (jika status REJECTED)

        Returns:
            Evidence yang sudah diupdate, atau None jika tidak ditemukan
        """
        with self._lock:
            evidence = self._evidences.get(evidence_id)
            if not evidence:
                return None

            # Check integrity before marking as verified
            integrity_ok = True
            if status == EvidenceVerificationStatus.VERIFIED:
                integrity_ok = await self.verify_integrity(evidence)
                if not integrity_ok:
                    status = EvidenceVerificationStatus.FAILED
                    logger.warning(f"Evidence {evidence_id} integrity check failed")

            # Update description with rejection reason if needed
            description = evidence.description
            if status == EvidenceVerificationStatus.REJECTED and rejection_reason:
                description = f"{evidence.description or ''} [REJECTED: {rejection_reason}]"

            updated = Evidence(
                evidence_id=evidence.evidence_id,
                filename=evidence.filename,
                file_hash=evidence.file_hash,
                file_size=evidence.file_size,
                mime_type=evidence.mime_type,
                evidence_type=evidence.evidence_type,
                uploaded_by=evidence.uploaded_by,
                uploaded_at=evidence.uploaded_at,
                storage_path=evidence.storage_path,
                description=description,
                verification_status=status,
                verified_at=datetime.now(UTC),
                verified_by=verified_by,
                transaction_id=evidence.transaction_id,
                legal_entity_id=evidence.legal_entity_id,
                expiry_date=evidence.expiry_date,
                tags=evidence.tags,
                cryptographic_hash=evidence.cryptographic_hash,
            )
            self._evidences[evidence_id] = updated
            logger.info(
                f"Evidence {evidence_id} verification status set to {status.value} by {verified_by}"
            )
            return updated

    async def attach_to_transaction(
        self,
        evidence_id: UUID,
        transaction_id: UUID,
        user_id: str | None = None,
    ) -> bool:
        """
        Menghubungkan evidence ke transaksi.

        Args:
            evidence_id: ID bukti
            transaction_id: ID transaksi
            user_id: User ID (untuk audit)

        Returns:
            True jika berhasil
        """
        with self._lock:
            evidence = self._evidences.get(evidence_id)
            if not evidence:
                logger.warning(
                    f"Cannot attach evidence {evidence_id} to transaction {transaction_id}: evidence not found"
                )
                return False

            # Update evidence with transaction_id
            updated = Evidence(
                evidence_id=evidence.evidence_id,
                filename=evidence.filename,
                file_hash=evidence.file_hash,
                file_size=evidence.file_size,
                mime_type=evidence.mime_type,
                evidence_type=evidence.evidence_type,
                uploaded_by=evidence.uploaded_by,
                uploaded_at=evidence.uploaded_at,
                storage_path=evidence.storage_path,
                description=evidence.description,
                verification_status=evidence.verification_status,
                verified_at=evidence.verified_at,
                verified_by=evidence.verified_by,
                transaction_id=transaction_id,
                legal_entity_id=evidence.legal_entity_id,
                expiry_date=evidence.expiry_date,
                tags=evidence.tags,
                cryptographic_hash=evidence.cryptographic_hash,
            )
            self._evidences[evidence_id] = updated

            if transaction_id not in self._transaction_evidence:
                self._transaction_evidence[transaction_id] = []
            if evidence_id not in self._transaction_evidence[transaction_id]:
                self._transaction_evidence[transaction_id].append(evidence_id)

            logger.info(f"Attached evidence {evidence_id} to transaction {transaction_id}")
            return True

    async def detach_from_transaction(
        self,
        evidence_id: UUID,
        transaction_id: UUID,
        user_id: str | None = None,
    ) -> bool:
        """Memutuskan hubungan evidence dari transaksi."""
        with self._lock:
            evidence = self._evidences.get(evidence_id)
            if not evidence:
                return False

            if evidence.transaction_id == transaction_id:
                updated = Evidence(
                    evidence_id=evidence.evidence_id,
                    filename=evidence.filename,
                    file_hash=evidence.file_hash,
                    file_size=evidence.file_size,
                    mime_type=evidence.mime_type,
                    evidence_type=evidence.evidence_type,
                    uploaded_by=evidence.uploaded_by,
                    uploaded_at=evidence.uploaded_at,
                    storage_path=evidence.storage_path,
                    description=evidence.description,
                    verification_status=evidence.verification_status,
                    verified_at=evidence.verified_at,
                    verified_by=evidence.verified_by,
                    transaction_id=None,
                    legal_entity_id=evidence.legal_entity_id,
                    expiry_date=evidence.expiry_date,
                    tags=evidence.tags,
                    cryptographic_hash=evidence.cryptographic_hash,
                )
                self._evidences[evidence_id] = updated

            if transaction_id in self._transaction_evidence:
                if evidence_id in self._transaction_evidence[transaction_id]:
                    self._transaction_evidence[transaction_id].remove(evidence_id)
                    logger.info(
                        f"Detached evidence {evidence_id} from transaction {transaction_id}"
                    )
                    return True
            return False

    async def delete_evidence(
        self, evidence_id: UUID, deleted_by: str, force: bool = False
    ) -> bool:
        """
        Menghapus bukti (soft delete dengan status, atau hard delete jika belum terikat).

        Args:
            evidence_id: ID bukti
            deleted_by: User yang menghapus
            force: Jika True, hard delete meskipun sudah terikat

        Returns:
            True jika berhasil dihapus
        """
        with self._lock:
            evidence = self._evidences.get(evidence_id)
            if not evidence:
                return False

            # Hard delete if not attached to any transaction or force=True
            if evidence.transaction_id is None or force:
                # Delete from storage
                await self._file_storage.delete(evidence.storage_path)
                del self._evidences[evidence_id]
                # Remove from transaction mapping
                for tx_id, ev_ids in self._transaction_evidence.items():
                    if evidence_id in ev_ids:
                        ev_ids.remove(evidence_id)
                logger.info(f"Evidence {evidence_id} hard deleted by {deleted_by}")
                return True
            else:
                # Soft delete - mark as expired
                updated = Evidence(
                    evidence_id=evidence.evidence_id,
                    filename=evidence.filename,
                    file_hash=evidence.file_hash,
                    file_size=evidence.file_size,
                    mime_type=evidence.mime_type,
                    evidence_type=evidence.evidence_type,
                    uploaded_by=evidence.uploaded_by,
                    uploaded_at=evidence.uploaded_at,
                    storage_path=evidence.storage_path,
                    description=evidence.description,
                    verification_status=EvidenceVerificationStatus.EXPIRED,
                    verified_at=datetime.now(UTC),
                    verified_by=deleted_by,
                    transaction_id=evidence.transaction_id,
                    legal_entity_id=evidence.legal_entity_id,
                    expiry_date=evidence.expiry_date,
                    tags=evidence.tags,
                    cryptographic_hash=evidence.cryptographic_hash,
                )
                self._evidences[evidence_id] = updated
                logger.info(f"Evidence {evidence_id} soft deleted (expired) by {deleted_by}")
                return True

    async def enforce(
        self,
        transaction_type: str,
        evidence_ids: list[UUID],
        amount: Decimal | None = None,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[str]]:
        """
        Menegakkan requirement bukti, raise exception jika tidak terpenuhi.

        Args:
            transaction_type: Tipe transaksi
            evidence_ids: Daftar ID bukti
            amount: Jumlah transaksi
            user_id: User ID
            raise_on_violation: Raise exception jika violation

        Returns:
            (is_valid, warnings)

        Raises:
            EvidenceAttacherError: Jika evidence tidak mencukupi
        """
        is_valid, error_msg, warnings = await self.validate_evidence(
            transaction_type=transaction_type,
            evidence_ids=evidence_ids,
            amount=amount,
            user_id=user_id,
        )

        # Record check
        self._record_check(transaction_type, evidence_ids, amount, is_valid, error_msg, warnings)

        if not is_valid and raise_on_violation:
            raise EvidenceAttacherError(
                message=error_msg or "Evidence requirement not met",
                transaction_type=transaction_type,
                severity=GuardSeverity.HIGH,
                details={
                    "transaction_type": transaction_type,
                    "evidence_count": len(evidence_ids),
                    "amount": str(amount) if amount else None,
                },
            )

        return is_valid, warnings

    def _record_check(
        self,
        transaction_type: str,
        evidence_ids: list[UUID],
        amount: Decimal | None,
        is_valid: bool,
        error_msg: str | None,
        warnings: list[str],
    ) -> None:
        """Record evidence check untuk audit."""
        with self._lock:
            record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "transaction_type": transaction_type,
                "evidence_count": len(evidence_ids),
                "evidence_ids": [str(eid) for eid in evidence_ids],
                "amount": str(amount) if amount else None,
                "is_valid": is_valid,
                "error_msg": error_msg,
                "warnings": warnings,
            }
            self._check_history.append(record)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

    def get_requirements(self) -> dict[str, TransactionEvidenceRequirement]:
        """Mendapatkan semua requirement yang terdaftar."""
        return self._requirements.copy()

    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        transaction_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Mendapatkan history pemeriksaan bukti."""
        with self._lock:
            result = self._check_history[-limit:]

        if only_violations:
            result = [r for r in result if not r["is_valid"]]
        if transaction_type:
            result = [r for r in result if r["transaction_type"] == transaction_type]
        if start_date:
            result = [r for r in result if datetime.fromisoformat(r["timestamp"]) >= start_date]
        if end_date:
            result = [r for r in result if datetime.fromisoformat(r["timestamp"]) <= end_date]

        return result

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik evidence attacher."""
        with self._lock:
            total_evidences = len(self._evidences)
            total_checks = len(self._check_history)

            if total_checks == 0:
                return {
                    "total_evidences": total_evidences,
                    "total_checks": 0,
                    "enabled": self._enabled,
                }

            violations = [r for r in self._check_history if not r["is_valid"]]
            by_type: dict[str, int] = {}
            for r in self._check_history:
                by_type[r["transaction_type"]] = by_type.get(r["transaction_type"], 0) + 1

            by_verification: dict[str, int] = {}
            for e in self._evidences.values():
                by_verification[e.verification_status.value] = (
                    by_verification.get(e.verification_status.value, 0) + 1
                )

            by_evidence_type: dict[str, int] = {}
            for e in self._evidences.values():
                by_evidence_type[e.evidence_type.value] = (
                    by_evidence_type.get(e.evidence_type.value, 0) + 1
                )

            return {
                "total_evidences": total_evidences,
                "total_checks": total_checks,
                "violation_count": len(violations),
                "violation_rate": len(violations) / total_checks if total_checks > 0 else 0,
                "by_transaction_type": by_type,
                "by_verification_status": by_verification,
                "by_evidence_type": by_evidence_type,
                "enabled": self._enabled,
                "auto_verify": self._auto_verify_on_upload,
                "latest_check": self._check_history[-1]["timestamp"]
                if self._check_history
                else None,
            }

    def reset(self) -> None:
        """Reset guard (untuk testing)."""
        with self._lock:
            self._evidences.clear()
            self._transaction_evidence.clear()
            self._check_history.clear()
            self._requirements = DEFAULT_EVIDENCE_REQUIREMENTS.copy()


# === 5. SINGLETON ACCESSOR ===

_evidence_attacher_guard_instance: EvidenceAttacherGuard | None = None
_lock_instance = threading.Lock()


def get_evidence_attacher_guard() -> EvidenceAttacherGuard:
    """Mendapatkan instance singleton EvidenceAttacherGuard."""
    global _evidence_attacher_guard_instance
    if _evidence_attacher_guard_instance is None:
        with _lock_instance:
            if _evidence_attacher_guard_instance is None:
                _evidence_attacher_guard_instance = EvidenceAttacherGuard()
    return _evidence_attacher_guard_instance


# === 6. EXPORTS ===

__all__ = [
    "Evidence",
    "EvidenceAttacherGuard",
    "EvidenceRequirement",
    "EvidenceType",
    "EvidenceVerificationStatus",
    "TransactionEvidenceRequirement",
    "get_evidence_attacher_guard",
]
