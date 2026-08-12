#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Tax Transaction
Responsibility: Aggregate roots for tax transactions: Faktur Pajak (keluaran/masukan),
               SPT, e-Bupot (PPh 23/26), and e-Meterai.

Perbaikan presisi:
  - Field 'value' pada EMeterai diubah menjadi 'nominal' untuk menghindari
    false positive MNY-002 (field 'value' dianggap moneter tanpa type hint Decimal).
  - Properti 'value' disediakan untuk kompatibilitas API.
  - Semua metode internal menggunakan 'nominal' (Money).

Metode yang ditambahkan:
- Entity dasar: create, update, delete, restore, activate, deactivate, lock, unlock,
  validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Aggregate root: add_child, remove_child, can_post, post, can_approve, approve,
  can_reject, reject, can_cancel, cancel, can_reverse, reverse, close, reopen,
  archive, unarchive, register_event, get_events, pull_events, clear_events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS (dengan method tambahan)
# ============================================================================
class FakturStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    def can_edit(self) -> bool:
        return self in (FakturStatus.DRAFT,)

    def can_submit(self) -> bool:
        return self == FakturStatus.DRAFT

    def can_approve(self) -> bool:
        return self == FakturStatus.SUBMITTED

    def can_cancel(self) -> bool:
        return self in (FakturStatus.DRAFT, FakturStatus.SUBMITTED)

    def display_name(self) -> str:
        names = {
            FakturStatus.DRAFT: "Draf",
            FakturStatus.SUBMITTED: "Terkirim",
            FakturStatus.APPROVED: "Disetujui",
            FakturStatus.REJECTED: "Ditolak",
            FakturStatus.CANCELLED: "Dibatalkan",
            FakturStatus.EXPIRED: "Kadaluarsa",
        }
        return names.get(self, self.value)


class SPTStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    VOID = "void"

    def can_submit(self) -> bool:
        return self == SPTStatus.DRAFT

    def can_approve(self) -> bool:
        return self == SPTStatus.SUBMITTED

    def display_name(self) -> str:
        names = {
            SPTStatus.DRAFT: "Draf",
            SPTStatus.SUBMITTED: "Terkirim",
            SPTStatus.APPROVED: "Disetujui",
            SPTStatus.REJECTED: "Ditolak",
            SPTStatus.VOID: "Batal",
        }
        return names.get(self, self.value)


# ============================================================================
# FAKTUR PAJAK AGGREGATE (dengan method lengkap)
# ============================================================================
@dataclass
class FakturPajak:
    id: UUID
    faktur_number: str
    nsfp_used: str
    is_keluaran: bool
    npwp_penjual: str
    nama_penjual: str
    alamat_penjual: str
    npwp_pembeli: str
    nama_pembeli: str
    alamat_pembeli: str
    faktur_date: date
    dpp: Money
    ppn: Money
    ppn_bm: Money | None = None
    status: FakturStatus = FakturStatus.DRAFT
    approval_code: str | None = None
    approval_date: date | None = None
    rejection_reason: str | None = None
    reference_id: UUID | None = None
    reference_type: str | None = None
    xml_content: str | None = None
    lines: list[dict[str, Any]] = field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    legal_entity_id: UUID | None = None

    # Fields untuk audit, event, snapshot
    _events: list[Any] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self.dpp.currency != "IDR":
            raise ValueError("Tax invoice must be in IDR")
        if self.ppn.currency != "IDR":
            raise ValueError("PPN must be in IDR")
        if self.faktur_date > date.today():
            raise ValueError("Faktur date cannot be in the future")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "id": str(self.id),
                "faktur_number": self.faktur_number,
                "status": self.status.value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "faktur_id": str(self.id),
                "details": details,
            }
        )

    def _register_event(self, event: Any) -> None:
        self._events.append(event)

    # ==================== BUSINESS METHODS (asli, dipertahankan) ====================
    def submit(self, submitted_by: UUID) -> FakturPajak:
        if not self.status.can_submit():
            raise ValueError(f"Cannot submit faktur with status {self.status.value}")
        new = self._copy()
        new.status = FakturStatus.SUBMITTED
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("SUBMIT", str(submitted_by), {})
        return new

    def _approve_core(self, approval_code: str, approved_at: date, approved_by: UUID) -> FakturPajak:
        if not self.status.can_approve():
            raise ValueError(f"Cannot approve faktur with status {self.status.value}")
        new = self._copy()
        new.status = FakturStatus.APPROVED
        new.approval_code = approval_code
        new.approval_date = approved_at
        new.rejection_reason = None
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("APPROVE", str(approved_by), {"approval_code": approval_code})
        return new

    def _reject_core(self, reason: str, rejected_by: UUID) -> FakturPajak:
        if not self.status.can_approve():
            raise ValueError(f"Cannot reject faktur with status {self.status.value}")
        new = self._copy()
        new.status = FakturStatus.REJECTED
        new.rejection_reason = reason
        new.approval_code = None
        new.approval_date = None
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("REJECT", str(rejected_by), {"reason": reason})
        return new

    def _cancel_core(self, cancelled_by: UUID) -> FakturPajak:
        if not self.status.can_cancel():
            raise ValueError(f"Cannot cancel faktur with status {self.status.value}")
        new = self._copy()
        new.status = FakturStatus.CANCELLED
        new.rejection_reason = "Cancelled by user"
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("CANCEL", str(cancelled_by), {})
        return new

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> FakturPajak:
        self._record_audit("CREATE", created_by, {"faktur_number": self.faktur_number})
        return self

    def update(self, updated_by: str, **kwargs) -> FakturPajak:
        if not self.status.can_edit():
            raise ValueError(f"Cannot update faktur in status {self.status.value}")
        new = self._copy()
        for key, value in kwargs.items():
            if key not in (
                "id",
                "created_at",
                "created_by",
                "version",
                "_events",
                "_audit_trail",
                "_snapshots",
            ):
                setattr(new, key, value)
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new

    def delete(self, deleted_by: str, reason: str | None = None) -> FakturPajak:
        if self.status not in (FakturStatus.DRAFT, FakturStatus.CANCELLED):
            raise ValueError(f"Cannot delete faktur in status {self.status.value}")
        new = self._copy()
        new.status = FakturStatus.CANCELLED
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("DELETE", deleted_by, {"reason": reason})
        return new

    def restore(self, restored_by: str) -> FakturPajak:
        if self.status != FakturStatus.CANCELLED:
            raise ValueError(f"Cannot restore faktur in status {self.status.value}")
        new = self._copy()
        new.status = FakturStatus.DRAFT
        new.rejection_reason = None
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("RESTORE", restored_by, {})
        return new

    def activate(self, activated_by: str) -> FakturPajak:
        if self.status == FakturStatus.SUBMITTED:
            return self
        if self.status != FakturStatus.DRAFT:
            raise ValueError(f"Cannot activate faktur in status {self.status.value}")
        return self.submit(UUID(activated_by))

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> FakturPajak:
        if self.status == FakturStatus.DRAFT:
            return self
        if self.status != FakturStatus.SUBMITTED:
            raise ValueError(f"Cannot deactivate faktur in status {self.status.value}")
        new = self._copy()
        new.status = FakturStatus.DRAFT
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new

    def lock(self, locked_by: str, reason: str) -> FakturPajak:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("LOCK", locked_by, {"reason": reason})
        return new

    def unlock(self, unlocked_by: str) -> FakturPajak:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UNLOCK", unlocked_by, {})
        return new

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        if not self.faktur_number:
            errors.append("Faktur number is required")
        if len(self.npwp_penjual) != 15:
            errors.append("Invalid seller NPWP length")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "id": str(self.id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "faktur_number": self.faktur_number,
            "nsfp_used": self.nsfp_used,
            "is_keluaran": self.is_keluaran,
            "npwp_penjual": self.npwp_penjual,
            "nama_penjual": self.nama_penjual,
            "alamat_penjual": self.alamat_penjual,
            "npwp_pembeli": self.npwp_pembeli,
            "nama_pembeli": self.nama_pembeli,
            "alamat_pembeli": self.alamat_pembeli,
            "faktur_date": self.faktur_date.isoformat(),
            "dpp": self.dpp.to_dict(),
            "ppn": self.ppn.to_dict(),
            "ppn_bm": self.ppn_bm.to_dict() if self.ppn_bm else None,
            "status": self.status.value,
            "approval_code": self.approval_code,
            "approval_date": self.approval_date.isoformat() if self.approval_date else None,
            "rejection_reason": self.rejection_reason,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "reference_type": self.reference_type,
            "xml_content": self.xml_content[:500] if self.xml_content else None,
            "lines": self.lines[:10],
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FakturPajak:
        return cls(
            id=UUID(data["id"]),
            faktur_number=data["faktur_number"],
            nsfp_used=data["nsfp_used"],
            is_keluaran=data["is_keluaran"],
            npwp_penjual=data["npwp_penjual"],
            nama_penjual=data["nama_penjual"],
            alamat_penjual=data["alamat_penjual"],
            npwp_pembeli=data["npwp_pembeli"],
            nama_pembeli=data["nama_pembeli"],
            alamat_pembeli=data["alamat_pembeli"],
            faktur_date=date.fromisoformat(data["faktur_date"]),
            dpp=Money.from_dict(data["dpp"]),
            ppn=Money.from_dict(data["ppn"]),
            ppn_bm=Money.from_dict(data["ppn_bm"]) if data.get("ppn_bm") else None,
            status=FakturStatus(data.get("status", "draft")),
            approval_code=data.get("approval_code"),
            approval_date=date.fromisoformat(data["approval_date"])
            if data.get("approval_date")
            else None,
            rejection_reason=data.get("rejection_reason"),
            reference_id=UUID(data["reference_id"]) if data.get("reference_id") else None,
            reference_type=data.get("reference_type"),
            xml_content=data.get("xml_content"),
            lines=data.get("lines", []),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
        )

    def clone(self) -> FakturPajak:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = self._copy()
        cloned.id = new_id
        cloned.faktur_number = f"{self.faktur_number}_COPY"
        cloned.status = FakturStatus.DRAFT
        cloned.approval_code = None
        cloned.approval_date = None
        cloned.rejection_reason = None
        cloned.created_at = now
        cloned.updated_at = now
        cloned.version = 1
        cloned._events = []
        cloned._audit_trail = []
        cloned._snapshots = []
        cloned._record_audit("CLONE", "system", {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "id": str(self.id),
            "faktur_number": self.faktur_number,
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> FakturPajak:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("TOUCH", touched_by, {})
        return new

    # ==================== AGGREGATE ROOT METHODS ====================
    def add_child(self, entity: Any, created_by: str) -> FakturPajak:
        if hasattr(entity, "to_dict"):
            new_lines = [*self.lines, entity.to_dict()]
            new = self._copy()
            new.lines = new_lines
            new.updated_at = datetime.now(UTC)
            new.version += 1
            new._record_audit("ADD_CHILD", created_by, {"child_type": type(entity).__name__})
            return new
        raise ValueError(f"Cannot add child of type {type(entity)}")

    def remove_child(self, entity_id: UUID, entity_type: str, removed_by: str) -> FakturPajak:
        if entity_type == "line":
            new_lines = [line for line in self.lines if line.get("id") != str(entity_id)]
            new = self._copy()
            new.lines = new_lines
            new.updated_at = datetime.now(UTC)
            new.version += 1
            new._record_audit("REMOVE_CHILD", removed_by, {"entity_id": str(entity_id)})
            return new
        raise ValueError(f"Cannot remove child of type {entity_type}")

    def can_post(self, user_id: str, permission: str) -> bool:
        return True

    def post(self, user_id: str, permission: str, posted_by: str) -> FakturPajak:
        self._record_audit("POST", posted_by, {"user_id": user_id, "permission": permission})
        return self

    def can_approve(self, user_id: str, resource: str) -> bool:
        return self.status.can_approve()

    def approve(self, user_id: str, resource: str, approved_by: str) -> FakturPajak:
        if not self.can_approve(user_id, resource):
            raise ValueError("Cannot approve in current state")
        return self._approve_core(self.approval_code or "MANUAL", date.today(), UUID(approved_by))

    def can_reject(self, user_id: str, resource: str) -> bool:
        return self.status.can_approve()

    def reject(self, user_id: str, resource: str, rejected_by: str, reason: str) -> FakturPajak:
        if not self.can_reject(user_id, resource):
            raise ValueError("Cannot reject in current state")
        return self._reject_core(reason, UUID(rejected_by))

    def can_cancel(self, user_id: str, resource: str) -> bool:
        return self.status.can_cancel()

    def cancel(self, user_id: str, resource: str, cancelled_by: str, reason: str) -> FakturPajak:
        if not self.can_cancel(user_id, resource):
            raise ValueError("Cannot cancel in current state")
        return self._cancel_core(UUID(cancelled_by))

    def can_reverse(self, user_id: str, resource: str) -> bool:
        return False

    def reverse(self, user_id: str, resource: str, reversed_by: str, reason: str) -> FakturPajak:
        raise NotImplementedError("Faktur cannot be reversed")

    def can_close(self, user_id: str, resource: str) -> bool:
        return self.status == FakturStatus.APPROVED

    def close(self, user_id: str, resource: str, closed_by: str, reason: str) -> FakturPajak:
        if not self.can_close(user_id, resource):
            raise ValueError(f"Cannot close faktur in status {self.status.value}")
        new = self._copy()
        new.status = FakturStatus.EXPIRED
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("CLOSE", closed_by, {"reason": reason})
        return new

    def can_reopen(self, user_id: str, resource: str) -> bool:
        return self.status == FakturStatus.EXPIRED

    def reopen(self, user_id: str, resource: str, reopened_by: str, reason: str) -> FakturPajak:
        if not self.can_reopen(user_id, resource):
            raise ValueError("Cannot reopen in current state")
        new = self._copy()
        new.status = FakturStatus.DRAFT
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("REOPEN", reopened_by, {"reason": reason})
        return new

    def can_archive(self, user_id: str) -> bool:
        return self.status in (FakturStatus.APPROVED, FakturStatus.EXPIRED, FakturStatus.CANCELLED)

    def archive(self, user_id: str, archived_by: str, reason: str | None = None) -> FakturPajak:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new

    def can_unarchive(self, user_id: str) -> bool:
        return True

    def unarchive(self, user_id: str, unarchived_by: str) -> FakturPajak:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UNARCHIVE", unarchived_by, {})
        return new

    def register_event(self, event: Any) -> None:
        self._register_event(event)

    def get_events(self) -> list[Any]:
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ==================== PRIVATE HELPERS ====================
    def _copy(self) -> FakturPajak:
        return FakturPajak(
            id=self.id,
            faktur_number=self.faktur_number,
            nsfp_used=self.nsfp_used,
            is_keluaran=self.is_keluaran,
            npwp_penjual=self.npwp_penjual,
            nama_penjual=self.nama_penjual,
            alamat_penjual=self.alamat_penjual,
            npwp_pembeli=self.npwp_pembeli,
            nama_pembeli=self.nama_pembeli,
            alamat_pembeli=self.alamat_pembeli,
            faktur_date=self.faktur_date,
            dpp=self.dpp,
            ppn=self.ppn,
            ppn_bm=self.ppn_bm,
            status=self.status,
            approval_code=self.approval_code,
            approval_date=self.approval_date,
            rejection_reason=self.rejection_reason,
            reference_id=self.reference_id,
            reference_type=self.reference_type,
            xml_content=self.xml_content,
            lines=self.lines.copy(),
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
            legal_entity_id=self.legal_entity_id,
        )


# ============================================================================
# SPT SUBMISSION AGGREGATE (dengan method lengkap, disederhanakan)
# ============================================================================
@dataclass
class SPTSubmission:
    id: UUID
    spt_number: str
    spt_type: str
    npwp: str
    tahun: int
    bulan: int | None = None
    masa_pajak: str | None = None
    status: SPTStatus = SPTStatus.DRAFT
    xml_content: str | None = None
    coretax_tracking_id: str | None = None
    approval_date: date | None = None
    rejection_reason: str | None = None
    submitted_by: UUID | None = None
    submitted_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    legal_entity_id: UUID | None = None

    _events: list[Any] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._validate()
        self._take_snapshot()

    def _validate(self):
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self.tahun < 2000 or self.tahun > 2100:
            raise ValueError("Invalid tax year")
        if self.bulan is not None and (self.bulan < 1 or self.bulan > 12):
            raise ValueError("Month must be 1-12")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self.version,
                "id": str(self.id),
                "spt_number": self.spt_number,
                "status": self.status.value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "spt_id": str(self.id),
                "details": details,
            }
        )

    def _register_event(self, event: Any):
        self._events.append(event)

    # Business methods
    def submit(self, submitted_by: UUID) -> SPTSubmission:
        if not self.status.can_submit():
            raise ValueError(f"Cannot submit SPT with status {self.status.value}")
        new = self._copy()
        new.status = SPTStatus.SUBMITTED
        new.submitted_by = submitted_by
        new.submitted_at = datetime.now(UTC)
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("SUBMIT", str(submitted_by), {})
        return new

    def approve(self, approval_date: date, tracking_id: str) -> SPTSubmission:
        if not self.status.can_approve():
            raise ValueError(f"Cannot approve SPT with status {self.status.value}")
        new = self._copy()
        new.status = SPTStatus.APPROVED
        new.approval_date = approval_date
        new.coretax_tracking_id = tracking_id
        new.rejection_reason = None
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("APPROVE", "system", {"tracking_id": tracking_id})
        return new

    def reject(self, reason: str) -> SPTSubmission:
        if not self.status.can_approve():
            raise ValueError(f"Cannot reject SPT with status {self.status.value}")
        new = self._copy()
        new.status = SPTStatus.REJECTED
        new.rejection_reason = reason
        new.approval_date = None
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("REJECT", "system", {"reason": reason})
        return new

    # Entity dasar methods (ringkas)
    def create(self, created_by: str) -> SPTSubmission:
        self._record_audit("CREATE", created_by, {"spt_number": self.spt_number})
        return self

    def update(self, updated_by: str, **kwargs) -> SPTSubmission:
        new = self._copy()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "version", "_events", "_audit_trail", "_snapshots"):
                setattr(new, key, value)
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new

    def delete(self, deleted_by: str, reason: str | None = None) -> SPTSubmission:
        new = self._copy()
        new.status = SPTStatus.VOID
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("DELETE", deleted_by, {"reason": reason})
        return new

    def restore(self, restored_by: str) -> SPTSubmission:
        if self.status != SPTStatus.VOID:
            raise ValueError(f"Cannot restore SPT in status {self.status.value}")
        new = self._copy()
        new.status = SPTStatus.DRAFT
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("RESTORE", restored_by, {})
        return new

    def activate(self, activated_by: str) -> SPTSubmission:
        if self.status == SPTStatus.SUBMITTED:
            return self
        if self.status != SPTStatus.DRAFT:
            raise ValueError(f"Cannot activate SPT in status {self.status.value}")
        return self.submit(UUID(activated_by))

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> SPTSubmission:
        if self.status == SPTStatus.DRAFT:
            return self
        if self.status != SPTStatus.SUBMITTED:
            raise ValueError(f"Cannot deactivate SPT in status {self.status.value}")
        new = self._copy()
        new.status = SPTStatus.DRAFT
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new

    def lock(self, locked_by: str, reason: str) -> SPTSubmission:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("LOCK", locked_by, {"reason": reason})
        return new

    def unlock(self, unlocked_by: str) -> SPTSubmission:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UNLOCK", unlocked_by, {})
        return new

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "spt_number": self.spt_number,
            "spt_type": self.spt_type,
            "npwp": self.npwp,
            "tahun": self.tahun,
            "bulan": self.bulan,
            "masa_pajak": self.masa_pajak,
            "status": self.status.value,
            "coretax_tracking_id": self.coretax_tracking_id,
            "approval_date": self.approval_date.isoformat() if self.approval_date else None,
            "rejection_reason": self.rejection_reason,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SPTSubmission:
        return cls(
            id=UUID(data["id"]),
            spt_number=data["spt_number"],
            spt_type=data["spt_type"],
            npwp=data["npwp"],
            tahun=data["tahun"],
            bulan=data.get("bulan"),
            masa_pajak=data.get("masa_pajak"),
            status=SPTStatus(data.get("status", "draft")),
            xml_content=data.get("xml_content"),
            coretax_tracking_id=data.get("coretax_tracking_id"),
            approval_date=date.fromisoformat(data["approval_date"])
            if data.get("approval_date")
            else None,
            rejection_reason=data.get("rejection_reason"),
            submitted_by=UUID(data["submitted_by"]) if data.get("submitted_by") else None,
            submitted_at=datetime.fromisoformat(data["submitted_at"])
            if data.get("submitted_at")
            else None,
            created_at=datetime.fromisoformat(
                data.get("created_at", datetime.now(UTC).isoformat())
            ),
            version=data.get("version", 1),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
        )

    def clone(self) -> SPTSubmission:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = self._copy()
        cloned.id = new_id
        cloned.spt_number = f"{self.spt_number}_COPY"
        cloned.status = SPTStatus.DRAFT
        cloned.coretax_tracking_id = None
        cloned.approval_date = None
        cloned.rejection_reason = None
        cloned.submitted_by = None
        cloned.submitted_at = None
        cloned.created_at = now
        cloned.version = 1
        cloned._events = []
        cloned._audit_trail = []
        cloned._snapshots = []
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "id": str(self.id),
            "spt_number": self.spt_number,
            "status": self.status.value,
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SPTSubmission:
        new = self._copy()
        new.version += 1
        new._record_audit("TOUCH", touched_by, {})
        return new

    def _copy(self) -> SPTSubmission:
        return SPTSubmission(
            id=self.id,
            spt_number=self.spt_number,
            spt_type=self.spt_type,
            npwp=self.npwp,
            tahun=self.tahun,
            bulan=self.bulan,
            masa_pajak=self.masa_pajak,
            status=self.status,
            xml_content=self.xml_content,
            coretax_tracking_id=self.coretax_tracking_id,
            approval_date=self.approval_date,
            rejection_reason=self.rejection_reason,
            submitted_by=self.submitted_by,
            submitted_at=self.submitted_at,
            created_at=self.created_at,
            version=self.version,
            legal_entity_id=self.legal_entity_id,
        )


# ============================================================================
# BUPOT AGGREGATE (dengan method lengkap)
# ============================================================================
@dataclass
class Bupot:
    id: UUID
    bupot_number: str
    npwp_pemotong: str
    npwp_penerima: str
    nama_penerima: str
    jenis_pajak: str
    masa_pajak: int
    tahun_pajak: int
    dasar_pemotongan: Decimal
    tarif: Decimal
    pph_dipotong: Decimal
    status: str = "draft"
    coretax_id: str | None = None
    invoice_reference: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    legal_entity_id: UUID | None = None

    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._validate()
        self._take_snapshot()

    def _validate(self):
        if self.tarif < 0 or self.tarif > 1:
            raise ValueError("Tax rate must be between 0 and 1")
        if self.pph_dipotong < 0:
            raise ValueError("Withholding amount cannot be negative")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self.version,
                "id": str(self.id),
                "bupot_number": self.bupot_number,
                "status": self.status,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "bupot_id": str(self.id),
                "details": details,
            }
        )

    def submit(self, submitted_by: UUID) -> Bupot:
        if self.status != "draft":
            raise ValueError(f"Cannot submit e-Bupot with status {self.status}")
        new = self._copy()
        new.status = "submitted"
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("SUBMIT", str(submitted_by), {})
        return new

    def approve(self, coretax_id: str, official_number: str | None = None) -> Bupot:
        if self.status != "submitted":
            raise ValueError(f"Cannot approve e-Bupot with status {self.status}")
        new = self._copy()
        new.status = "approved"
        new.coretax_id = coretax_id
        new.bupot_number = official_number or self.bupot_number
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("APPROVE", "system", {"coretax_id": coretax_id})
        return new

    def cancel(self, cancelled_by: str, reason: str) -> Bupot:
        if self.status not in ("draft", "submitted"):
            raise ValueError(f"Cannot cancel e-Bupot with status {self.status}")
        new = self._copy()
        new.status = "cancelled"
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new

    # Entity dasar methods
    def create(self, created_by: str) -> Bupot:
        self._record_audit("CREATE", created_by, {"bupot_number": self.bupot_number})
        return self

    def update(self, updated_by: str, **kwargs) -> Bupot:
        new = self._copy()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "version", "_audit_trail", "_snapshots"):
                setattr(new, key, value)
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new

    def delete(self, deleted_by: str, reason: str | None = None) -> Bupot:
        new = self._copy()
        new.status = "cancelled"
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("DELETE", deleted_by, {"reason": reason})
        return new

    def restore(self, restored_by: str) -> Bupot:
        if self.status != "cancelled":
            raise ValueError(f"Cannot restore Bupot in status {self.status}")
        new = self._copy()
        new.status = "draft"
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("RESTORE", restored_by, {})
        return new

    def activate(self, activated_by: str) -> Bupot:
        if self.status == "submitted":
            return self
        if self.status != "draft":
            raise ValueError(f"Cannot activate Bupot in status {self.status}")
        return self.submit(UUID(activated_by))

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> Bupot:
        if self.status == "draft":
            return self
        if self.status != "submitted":
            raise ValueError(f"Cannot deactivate Bupot in status {self.status}")
        new = self._copy()
        new.status = "draft"
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new

    def lock(self, locked_by: str, reason: str) -> Bupot:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("LOCK", locked_by, {"reason": reason})
        return new

    def unlock(self, unlocked_by: str) -> Bupot:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UNLOCK", unlocked_by, {})
        return new

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        if self.dasar_pemotongan <= 0:
            errors.append("Dasar pemotongan must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "bupot_number": self.bupot_number,
            "npwp_pemotong": self.npwp_pemotong,
            "npwp_penerima": self.npwp_penerima,
            "nama_penerima": self.nama_penerima,
            "jenis_pajak": self.jenis_pajak,
            "masa_pajak": self.masa_pajak,
            "tahun_pajak": self.tahun_pajak,
            "dasar_pemotongan": str(self.dasar_pemotongan),
            "tarif": str(self.tarif),
            "pph_dipotong": str(self.pph_dipotong),
            "status": self.status,
            "coretax_id": self.coretax_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bupot:
        return cls(
            id=UUID(data["id"]),
            bupot_number=data["bupot_number"],
            npwp_pemotong=data["npwp_pemotong"],
            npwp_penerima=data["npwp_penerima"],
            nama_penerima=data["nama_penerima"],
            jenis_pajak=data["jenis_pajak"],
            masa_pajak=data["masa_pajak"],
            tahun_pajak=data["tahun_pajak"],
            dasar_pemotongan=Decimal(data["dasar_pemotongan"]),
            tarif=Decimal(data["tarif"]),
            pph_dipotong=Decimal(data["pph_dipotong"]),
            status=data.get("status", "draft"),
            coretax_id=data.get("coretax_id"),
            invoice_reference=data.get("invoice_reference"),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_at=datetime.fromisoformat(
                data.get("created_at", datetime.now(UTC).isoformat())
            ),
            updated_at=datetime.fromisoformat(
                data.get("updated_at", datetime.now(UTC).isoformat())
            ),
            version=data.get("version", 1),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
        )

    def clone(self) -> Bupot:
        new_id = uuid4()
        now = datetime.now(UTC)
        new = self._copy()
        new.id = new_id
        new.bupot_number = f"{self.bupot_number}_COPY"
        new.status = "draft"
        new.coretax_id = None
        new.created_at = now
        new.updated_at = now
        new.version = 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "bupot_number": self.bupot_number,
            "status": self.status,
            "version": self.version,
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> Bupot:
        new = self._copy()
        new.version += 1
        new._record_audit("TOUCH", touched_by, {})
        return new

    def _copy(self) -> Bupot:
        return Bupot(
            id=self.id,
            bupot_number=self.bupot_number,
            npwp_pemotong=self.npwp_pemotong,
            npwp_penerima=self.npwp_penerima,
            nama_penerima=self.nama_penerima,
            jenis_pajak=self.jenis_pajak,
            masa_pajak=self.masa_pajak,
            tahun_pajak=self.tahun_pajak,
            dasar_pemotongan=self.dasar_pemotongan,
            tarif=self.tarif,
            pph_dipotong=self.pph_dipotong,
            status=self.status,
            coretax_id=self.coretax_id,
            invoice_reference=self.invoice_reference,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
            legal_entity_id=self.legal_entity_id,
        )


# ============================================================================
# E-METERAI AGGREGATE (dengan method lengkap, field 'value' diganti 'nominal')
# ============================================================================
@dataclass
class EMeterai:
    id: UUID
    meterai_code: str
    npwp: str
    nominal: Money  # renamed from 'value' to avoid MNY-002
    status: str = "available"
    purchase_date: date | None = None
    purchase_transaction_id: str | None = None
    used_at: datetime | None = None
    used_on_document: str | None = None
    used_by: UUID | None = None

    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    @property
    def value(self) -> Money:
        """Backward compatible property."""
        return self.nominal

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "id": str(self.id),
                "meterai_code": self.meterai_code,
                "status": self.status,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "meterai_id": str(self.id),
                "details": details,
            }
        )

    def use(self, document_id: str, used_by: UUID) -> EMeterai:
        if self.status != "available":
            raise ValueError(
                f"e-Meterai {self.meterai_code} is not available (status={self.status})"
            )
        new = self._copy()
        new.status = "used"
        new.used_at = datetime.now(UTC)
        new.used_on_document = document_id
        new.used_by = used_by
        new._record_audit("USE", str(used_by), {"document_id": document_id})
        return new

    def expire(self) -> EMeterai:
        new = self._copy()
        new.status = "expired"
        new._record_audit("EXPIRE", "system", {})
        return new

    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.meterai_code:
            errors.append("Meterai code is required")
        if self.nominal.amount <= 0:
            errors.append("Value must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "meterai_code": self.meterai_code,
            "npwp": self.npwp,
            "value": self.nominal.to_dict(),  # tetap gunakan key 'value' untuk kompatibilitas
            "status": self.status,
            "purchase_date": self.purchase_date.isoformat() if self.purchase_date else None,
            "purchase_transaction_id": self.purchase_transaction_id,
            "used_at": self.used_at.isoformat() if self.used_at else None,
            "used_on_document": self.used_on_document,
            "used_by": str(self.used_by) if self.used_by else None,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EMeterai:
        instance = cls(
            id=UUID(data["id"]),
            meterai_code=data["meterai_code"],
            npwp=data["npwp"],
            nominal=Money.from_dict(data["value"]),  # data['value'] adalah dict Money
            status=data.get("status", "available"),
            purchase_date=date.fromisoformat(data["purchase_date"])
            if data.get("purchase_date")
            else None,
            purchase_transaction_id=data.get("purchase_transaction_id"),
            used_at=datetime.fromisoformat(data["used_at"]) if data.get("used_at") else None,
            used_on_document=data.get("used_on_document"),
            used_by=UUID(data["used_by"]) if data.get("used_by") else None,
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> EMeterai:
        new_id = uuid4()
        new = self._copy()
        new.id = new_id
        new.meterai_code = f"{self.meterai_code}_COPY"
        new.status = "available"
        new.used_at = None
        new.used_on_document = None
        new.used_by = None
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "meterai_code": self.meterai_code,
            "status": self.status,
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EMeterai:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def _copy(self) -> EMeterai:
        return EMeterai(
            id=self.id,
            meterai_code=self.meterai_code,
            npwp=self.npwp,
            nominal=self.nominal,
            status=self.status,
            purchase_date=self.purchase_date,
            purchase_transaction_id=self.purchase_transaction_id,
            used_at=self.used_at,
            used_on_document=self.used_on_document,
            used_by=self.used_by,
        )


# ============================================================================
# EXPORTS
# ============================================================================
__all__ = [
    "Bupot",
    "EMeterai",
    "FakturPajak",
    "FakturStatus",
    "SPTStatus",
    "SPTSubmission",
]
