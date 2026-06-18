#!/usr/bin/env python3
"""
Module: legal_opinion_document_store.py
Layer: Compliance / Legal

Responsibility:
    Penyimpanan dokumen opini hukum (legal opinions) yang diterbitkan oleh
    kantor hukum eksternal atau internal. Mendukung metadata opini (judul,
    penulis, kantor hukum, tanggal terbit, subjek, yurisdiksi, status,
    lampiran), pencarian berdasarkan subjek, yurisdiksi, kata kunci,
    versi opini, serta integrasi dengan audit trail.

Dependencies:
    - datetime, uuid, typing, hashlib, json, logging, pathlib

Audit:
    Setiap penambahan, pembaruan, atau penghapusan opini dicatat dengan hash.
    Opini dapat ditandatangani secara digital (placeholder untuk implementasi).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class LegalOpinionStatus(Enum):
    DRAFT = "draft"
    FINAL = "final"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class LegalOpinionConfidentiality(Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    ATTORNEY_CLIENT = "attorney_client_privilege"


# ============================================================================
# Exceptions
# ============================================================================
class LegalOpinionError(Exception):
    pass


class LegalOpinionNotFoundError(LegalOpinionError):
    pass


# ============================================================================
# Data Classes
# ============================================================================
class LegalOpinionAttachment:
    """Lampiran opini hukum (file, URL, atau referensi)."""

    def __init__(
        self,
        attachment_id: UUID,
        filename: str,
        file_url: str,
        file_hash: str | None = None,
        file_size_bytes: int | None = None,
        description: str = "",
    ):
        self.id = attachment_id
        self.filename = filename
        self.file_url = file_url
        self.file_hash = file_hash
        self.file_size_bytes = file_size_bytes
        self.description = description
        self.uploaded_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "attachment_id": str(self.id),
            "filename": self.filename,
            "file_url": self.file_url,
            "file_hash": self.file_hash,
            "file_size_bytes": self.file_size_bytes,
            "description": self.description,
            "uploaded_at": self.uploaded_at.isoformat(),
        }


class LegalOpinion:
    """Opini hukum yang diterbitkan."""

    def __init__(
        self,
        opinion_id: UUID,
        title: str,
        author: str,
        law_firm: str,
        date_issued: date,
        subject: str,
        content: str,
        jurisdiction: str,
        status: LegalOpinionStatus = LegalOpinionStatus.FINAL,
        confidentiality: LegalOpinionConfidentiality = LegalOpinionConfidentiality.CONFIDENTIAL,
        version: int = 1,
        supersedes_opinion_id: UUID | None = None,
        reviewed_by: str | None = None,
        approved_by: str | None = None,
        tags: list[str] | None = None,
    ):
        self.id = opinion_id
        self.title = title
        self.author = author
        self.law_firm = law_firm
        self.date_issued = date_issued
        self.subject = subject
        self.content = content
        self.jurisdiction = jurisdiction
        self.status = status
        self.confidentiality = confidentiality
        self.version = version
        self.supersedes_opinion_id = supersedes_opinion_id
        self.reviewed_by = reviewed_by
        self.approved_by = approved_by
        self.tags = tags or []
        self.attachments: list[LegalOpinionAttachment] = []
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "title": self.title,
            "author": self.author,
            "date_issued": self.date_issued.isoformat(),
            "jurisdiction": self.jurisdiction,
            "version": self.version,
            "status": self.status.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_attachment(self, attachment: LegalOpinionAttachment) -> None:
        self.attachments.append(attachment)
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def update_status(self, new_status: LegalOpinionStatus, updated_by: str) -> None:
        self.status = new_status
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Opinion {self.id} status changed to {new_status.value} by {updated_by}")

    def create_new_version(
        self, new_content: str, new_author: str, new_date: date, notes: str = ""
    ) -> LegalOpinion:
        """Membuat versi baru dari opini ini (supersede)."""
        new_id = uuid4()
        new_opinion = LegalOpinion(
            opinion_id=new_id,
            title=self.title,
            author=new_author,
            law_firm=self.law_firm,
            date_issued=new_date,
            subject=self.subject,
            content=new_content,
            jurisdiction=self.jurisdiction,
            status=LegalOpinionStatus.FINAL,
            confidentiality=self.confidentiality,
            version=self.version + 1,
            supersedes_opinion_id=self.id,
            tags=self.tags.copy(),
        )
        # Mark current as superseded
        self.update_status(LegalOpinionStatus.SUPERSEDED, "system")
        return new_opinion

    def is_expired(self, expiry_days: int = 365) -> bool:
        """Cek apakah opini sudah kadaluarsa (misal > 1 tahun)."""
        expiry_date = self.date_issued.replace(year=self.date_issued.year + 1)
        return date.today() > expiry_date

    def to_dict(self, include_attachments: bool = True) -> dict:
        result = {
            "opinion_id": str(self.id),
            "title": self.title,
            "author": self.author,
            "law_firm": self.law_firm,
            "date_issued": self.date_issued.isoformat(),
            "subject": self.subject,
            "content": self.content[:500] + "..." if len(self.content) > 500 else self.content,
            "jurisdiction": self.jurisdiction,
            "status": self.status.value,
            "confidentiality": self.confidentiality.value,
            "version": self.version,
            "supersedes_opinion_id": str(self.supersedes_opinion_id)
            if self.supersedes_opinion_id
            else None,
            "reviewed_by": self.reviewed_by,
            "approved_by": self.approved_by,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "hash": self._hash,
        }
        if include_attachments:
            result["attachments"] = [a.to_dict() for a in self.attachments]
        return result


# ============================================================================
# LegalOpinionDocumentStore Core
# ============================================================================
class LegalOpinionDocumentStore:
    """
    Penyimpanan dokumen opini hukum dengan pencarian dan manajemen versi.
    """

    def __init__(self, storage_path: Path | None = None):
        self._opinions: dict[UUID, LegalOpinion] = {}
        self._subject_index: dict[str, list[UUID]] = {}  # keyword -> list of ids
        self._jurisdiction_index: dict[str, list[UUID]] = {}
        self._tag_index: dict[str, list[UUID]] = {}
        self._storage_path = storage_path

    def add_opinion(self, opinion: LegalOpinion) -> UUID:
        self._opinions[opinion.id] = opinion
        self._index_opinion(opinion)
        logger.info(f"Legal opinion added: {opinion.id} - {opinion.title}")
        return opinion.id

    def _index_opinion(self, opinion: LegalOpinion) -> None:
        # Subject index (by keywords in subject)
        for word in opinion.subject.lower().split():
            if len(word) > 3:
                self._subject_index.setdefault(word, []).append(opinion.id)
        # Jurisdiction index
        self._jurisdiction_index.setdefault(opinion.jurisdiction, []).append(opinion.id)
        # Tags index
        for tag in opinion.tags:
            self._tag_index.setdefault(tag.lower(), []).append(opinion.id)

    def get_opinion(self, opinion_id: UUID) -> LegalOpinion | None:
        return self._opinions.get(opinion_id)

    def update_opinion(self, opinion_id: UUID, **kwargs) -> bool:
        opinion = self.get_opinion(opinion_id)
        if not opinion:
            return False
        for key, value in kwargs.items():
            if hasattr(opinion, key):
                setattr(opinion, key, value)
        opinion.updated_at = datetime.utcnow()
        opinion._hash = opinion._compute_hash()
        return True

    def delete_opinion(self, opinion_id: UUID) -> bool:
        if opinion_id in self._opinions:
            del self._opinions[opinion_id]
            # Note: indexes not cleaned for simplicity (acceptable for small scale)
            logger.info(f"Opinion {opinion_id} deleted")
            return True
        return False

    def find_by_subject(self, subject_keyword: str) -> list[LegalOpinion]:
        keyword_lower = subject_keyword.lower()
        matching_ids = set()
        for word in keyword_lower.split():
            if word in self._subject_index:
                matching_ids.update(self._subject_index[word])
        # Also direct subject matching
        result = []
        for oid in matching_ids:
            opinion = self._opinions.get(oid)
            if opinion and keyword_lower in opinion.subject.lower():
                result.append(opinion)
        return result

    def find_by_jurisdiction(self, jurisdiction: str) -> list[LegalOpinion]:
        ids = self._jurisdiction_index.get(jurisdiction, [])
        return [self._opinions[oid] for oid in ids if oid in self._opinions]

    def find_by_tag(self, tag: str) -> list[LegalOpinion]:
        ids = self._tag_index.get(tag.lower(), [])
        return [self._opinions[oid] for oid in ids if oid in self._opinions]

    def find_by_date_range(self, start_date: date, end_date: date) -> list[LegalOpinion]:
        return [o for o in self._opinions.values() if start_date <= o.date_issued <= end_date]

    def find_by_law_firm(self, law_firm: str) -> list[LegalOpinion]:
        return [o for o in self._opinions.values() if o.law_firm.lower() == law_firm.lower()]

    def get_latest_version(self, opinion_id: UUID) -> LegalOpinion | None:
        """Mendapatkan versi terbaru dari opini (termasuk yang supersede)."""
        current = self.get_opinion(opinion_id)
        if not current:
            return None
        # Find if there is newer version that supersedes this
        for o in self._opinions.values():
            if o.supersedes_opinion_id == opinion_id:
                return self.get_latest_version(o.id)
        return current

    def get_all_active(self) -> list[LegalOpinion]:
        return [o for o in self._opinions.values() if o.status == LegalOpinionStatus.FINAL]

    def generate_report(self) -> dict:
        total = len(self._opinions)
        active = len(self.get_all_active())
        by_jurisdiction = {
            j: len(self.find_by_jurisdiction(j))
            for j in set(o.jurisdiction for o in self._opinions.values())
        }
        by_status = {
            s.value: sum(1 for o in self._opinions.values() if o.status == s)
            for s in LegalOpinionStatus
        }
        return {
            "total_opinions": total,
            "active_opinions": active,
            "by_jurisdiction": by_jurisdiction,
            "by_status": by_status,
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "opinions": [o.to_dict() for o in self._opinions.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def save_attachment(
        self, opinion_id: UUID, filename: str, file_content: bytes, description: str = ""
    ) -> UUID | None:
        """Simpan file attachment ke storage (jika storage_path diatur)."""
        opinion = self.get_opinion(opinion_id)
        if not opinion:
            return None
        if not self._storage_path:
            raise LegalOpinionError("Storage path not configured")
        self._storage_path.mkdir(parents=True, exist_ok=True)
        # Generate unique filename
        ext = Path(filename).suffix
        safe_name = f"{opinion_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"
        file_path = self._storage_path / safe_name
        file_path.write_bytes(file_content)
        # Compute hash
        file_hash = hashlib.sha256(file_content).hexdigest()
        attachment = LegalOpinionAttachment(
            attachment_id=uuid4(),
            filename=filename,
            file_url=str(file_path),
            file_hash=file_hash,
            file_size_bytes=len(file_content),
            description=description,
        )
        opinion.add_attachment(attachment)
        return attachment.id


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    store = LegalOpinionDocumentStore()
    op1 = LegalOpinion(
        opinion_id=uuid4(),
        title="Tax Treatment of Cross-Border Payments",
        author="John Doe, Partner",
        law_firm="Law Firm A",
        date_issued=date(2025, 3, 15),
        subject="Withholding tax on software royalties",
        content="Based on Indonesia-Singapore tax treaty, the withholding tax rate is reduced to 10%...",
        jurisdiction="ID",
        tags=["tax", "withholding", "royalty", "treaty"],
    )
    store.add_opinion(op1)
    print("Opinions found by 'tax':", len(store.find_by_subject("tax")))
    print("Active opinions:", len(store.get_all_active()))
    store.export_to_json("legal_opinions.json")
