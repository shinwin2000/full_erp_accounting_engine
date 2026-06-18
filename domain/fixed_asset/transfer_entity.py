#!/usr/bin/env python3
"""
Module: transfer_entity.py

Layer: Domain / Fixed Asset

Responsibility:
    Entity for asset transfer (perpindahan aset tetap).

    Records the movement of a fixed asset between departments, locations,
    cost centers, or custodians within the same legal entity.
    Transfer does not change the asset's value, only its assignment.

Business rules:
    - Transfer can only be created for active assets (not disposed).
    - Transfer date cannot be in the future or before acquisition date.
    - Source and destination must be different.
    - Status transitions: DRAFT -> APPROVED -> COMPLETED, or CANCELLED from DRAFT/APPROVED.
    - Completed transfers cannot be modified or cancelled.
    - Version increments on every change (optimistic locking).

Dependencies:
    - Python standard library (uuid, datetime, decimal, logging, re)
    - domain.fixed_asset.asset_entity (FixedAsset) for TYPE_CHECKING

Audit:
    Every transfer should be logged; domain events emitted separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from domain.fixed_asset.asset_entity import FixedAsset

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class TransferType(Enum):
    """Type of asset transfer."""

    DEPARTMENT = "department"  # Antar departemen
    LOCATION = "location"  # Antar lokasi fisik
    COST_CENTER = "cost_center"  # Antar pusat biaya
    CUSTODIAN = "custodian"  # Antar penanggung jawab

    def display_name(self) -> str:
        names = {
            TransferType.DEPARTMENT: "Transfer Departemen",
            TransferType.LOCATION: "Transfer Lokasi",
            TransferType.COST_CENTER: "Transfer Pusat Biaya",
            TransferType.CUSTODIAN: "Transfer Penanggung Jawab",
        }
        return names.get(self, self.value)

    def requires_approval(self) -> bool:
        """Does this transfer type require approval?"""
        return self in (TransferType.DEPARTMENT, TransferType.COST_CENTER)

    @classmethod
    def from_string(cls, value: str) -> TransferType | None:
        for t in cls:
            if t.value == value.lower():
                return t
        return None


class TransferStatus(Enum):
    """Status of transfer process."""

    DRAFT = "draft"  # Draft, belum diajukan
    APPROVED = "approved"  # Disetujui
    COMPLETED = "completed"  # Selesai (aset telah dipindahkan)
    CANCELLED = "cancelled"  # Dibatalkan

    def can_edit(self) -> bool:
        return self == TransferStatus.DRAFT

    def can_approve(self) -> bool:
        return self == TransferStatus.DRAFT

    def can_complete(self) -> bool:
        return self == TransferStatus.APPROVED

    def can_cancel(self) -> bool:
        return self in (TransferStatus.DRAFT, TransferStatus.APPROVED)

    def display_name(self) -> str:
        names = {
            TransferStatus.DRAFT: "Draft",
            TransferStatus.APPROVED: "Disetujui",
            TransferStatus.COMPLETED: "Selesai",
            TransferStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> TransferStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class TransferError(ValueError):
    """Base exception for transfer errors."""

    pass


class InvalidTransferDateError(TransferError):
    """Raised when transfer date is invalid."""

    pass


class SameSourceDestinationError(TransferError):
    """Raised when source and destination are the same."""

    pass


class AssetNotTransferableError(TransferError):
    """Raised when asset cannot be transferred."""

    pass


class InvalidStatusTransitionError(TransferError):
    """Raised when status transition is not allowed."""

    pass


class TransferAlreadyCompletedError(TransferError):
    """Raised when trying to modify a completed transfer."""

    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_transfer_date(transfer_date: date, acquisition_date: date) -> None:
    """Validate transfer date (not future, not before acquisition)."""
    if transfer_date > date.today():
        raise InvalidTransferDateError(f"Transfer date {transfer_date} cannot be in the future")
    if transfer_date < acquisition_date:
        raise InvalidTransferDateError(
            f"Transfer date {transfer_date} cannot be before acquisition date {acquisition_date}"
        )


def _validate_source_destination(source: str, destination: str) -> None:
    """Validate source and destination are different."""
    if source == destination:
        raise SameSourceDestinationError("Source and destination cannot be the same")


def _validate_string_field(
    value: str, field_name: str, min_len: int = 1, max_len: int = 200
) -> str:
    """Validate string field (non-empty, length bounds)."""
    if not value or not isinstance(value, str):
        raise TransferError(f"{field_name} must be a non-empty string")
    cleaned = value.strip()
    if len(cleaned) < min_len:
        raise TransferError(f"{field_name} must be at least {min_len} characters")
    if len(cleaned) > max_len:
        raise TransferError(f"{field_name} must not exceed {max_len} characters")
    return cleaned


def _validate_reason(reason: str) -> str:
    """Validate reason (max 500 chars)."""
    cleaned = reason.strip() if reason else ""
    if len(cleaned) > 500:
        raise TransferError("Reason must not exceed 500 characters")
    return cleaned


def _validate_notes(notes: str) -> str:
    """Validate notes (max 1000 chars)."""
    cleaned = notes.strip() if notes else ""
    if len(cleaned) > 1000:
        raise TransferError("Notes must not exceed 1000 characters")
    return cleaned


def _validate_asset_code(code: str) -> str:
    """Validate asset code format."""
    if not code or not isinstance(code, str):
        raise TransferError("Asset code must be a non-empty string")
    cleaned = code.strip()
    if len(cleaned) < 2:
        raise TransferError("Asset code must be at least 2 characters")
    if len(cleaned) > 30:
        raise TransferError("Asset code must not exceed 30 characters")
    return cleaned


def _validate_asset_name(name: str) -> str:
    """Validate asset name."""
    if not name or not isinstance(name, str):
        raise TransferError("Asset name must be a non-empty string")
    cleaned = name.strip()
    if len(cleaned) < 2:
        raise TransferError("Asset name must be at least 2 characters")
    if len(cleaned) > 200:
        raise TransferError("Asset name must not exceed 200 characters")
    return cleaned


def _validate_asset_transferable(asset: FixedAsset) -> None:
    """Check if asset can be transferred."""
    if asset.is_disposed:
        raise AssetNotTransferableError(
            f"Asset {asset.asset_code} is already disposed and cannot be transferred"
        )
    if not asset.status.can_transfer():
        raise AssetNotTransferableError(
            f"Asset {asset.asset_code} is in status {asset.status.display_name()} and cannot be transferred"
        )


# ============================================================================
# Entity: TransferEntity
# ============================================================================


@dataclass
class TransferEntity:
    """
    Entity for asset transfer.

    This entity is mutable (dataclass) but changes create new instances
    with incremented version for optimistic locking.

    Attributes:
        transfer_id: Unique identifier
        asset_id: Asset being transferred
        asset_code: Asset code
        asset_name: Asset name
        transfer_date: Date of transfer
        transfer_type: Type of transfer
        source: Source value (department, location, cost center, custodian)
        destination: Destination value
        status: Current status
        reason: Reason for transfer
        approved_by, approved_at: Approval info
        completed_by, completed_at: Completion info
        cancelled_by, cancelled_at, cancel_reason: Cancellation info
        notes: Additional notes
        created_by, created_at, updated_by, updated_at, version
    """

    # ========== Mandatory Fields ==========
    transfer_id: UUID
    asset_id: UUID
    asset_code: str
    asset_name: str
    transfer_date: date
    transfer_type: TransferType
    source: str
    destination: str
    status: TransferStatus

    # ========== Optional Fields ==========
    reason: str = ""
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    completed_by: UUID | None = None
    completed_at: datetime | None = None
    cancelled_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=uuid4)
    updated_by: UUID = field(default_factory=uuid4)
    version: int = 1

    def __post_init__(self) -> None:
        """Validate transfer data."""
        # Validate asset_code
        normalized_code = _validate_asset_code(self.asset_code)
        if normalized_code != self.asset_code:
            object.__setattr__(self, "asset_code", normalized_code)

        # Validate asset_name
        normalized_name = _validate_asset_name(self.asset_name)
        if normalized_name != self.asset_name:
            object.__setattr__(self, "asset_name", normalized_name)

        # Validate transfer_type
        if not isinstance(self.transfer_type, TransferType):
            raise TransferError(f"Invalid transfer_type: {self.transfer_type}")

        # Validate status
        if not isinstance(self.status, TransferStatus):
            raise TransferError(f"Invalid status: {self.status}")

        # Validate source and destination
        if self.source is None or not isinstance(self.source, str):
            raise TransferError("Source must be a non-empty string")
        src_clean = self.source.strip()
        if len(src_clean) < 1:
            raise TransferError("Source cannot be empty")
        if len(src_clean) > 200:
            raise TransferError("Source must not exceed 200 characters")
        object.__setattr__(self, "source", src_clean)

        if self.destination is None or not isinstance(self.destination, str):
            raise TransferError("Destination must be a non-empty string")
        dst_clean = self.destination.strip()
        if len(dst_clean) < 1:
            raise TransferError("Destination cannot be empty")
        if len(dst_clean) > 200:
            raise TransferError("Destination must not exceed 200 characters")
        object.__setattr__(self, "destination", dst_clean)

        # Validate source != destination
        _validate_source_destination(self.source, self.destination)

        # Validate reason
        cleaned_reason = _validate_reason(self.reason)
        if cleaned_reason != self.reason:
            object.__setattr__(self, "reason", cleaned_reason)

        # Validate notes
        cleaned_notes = _validate_notes(self.notes)
        if cleaned_notes != self.notes:
            object.__setattr__(self, "notes", cleaned_notes)

        # Validate status consistency
        if self.status == TransferStatus.APPROVED and not self.approved_by:
            raise TransferError("Approved transfer must have approved_by")
        if self.status == TransferStatus.COMPLETED and not self.completed_by:
            raise TransferError("Completed transfer must have completed_by")
        if self.status == TransferStatus.CANCELLED and not self.cancelled_by:
            raise TransferError("Cancelled transfer must have cancelled_by")

        # Validate timestamps UTC
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        if self.completed_at and self.completed_at.tzinfo is None:
            object.__setattr__(self, "completed_at", self.completed_at.replace(tzinfo=UTC))
        if self.cancelled_at and self.cancelled_at.tzinfo is None:
            object.__setattr__(self, "cancelled_at", self.cancelled_at.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

        # Validate version
        if self.version < 1:
            raise TransferError("Version must be >= 1")

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_draft(self) -> bool:
        return self.status == TransferStatus.DRAFT

    @property
    def is_approved(self) -> bool:
        return self.status == TransferStatus.APPROVED

    @property
    def is_completed(self) -> bool:
        return self.status == TransferStatus.COMPLETED

    @property
    def is_cancelled(self) -> bool:
        return self.status == TransferStatus.CANCELLED

    @property
    def can_edit(self) -> bool:
        return self.status.can_edit()

    @property
    def can_approve(self) -> bool:
        return self.status.can_approve()

    @property
    def can_complete(self) -> bool:
        return self.status.can_complete()

    @property
    def can_cancel(self) -> bool:
        return self.status.can_cancel()

    @property
    def display(self) -> str:
        """Simple display string."""
        return f"{self.asset_code}: {self.source} → {self.destination} ({self.transfer_type.display_name()})"

    @property
    def duration_days(self) -> int:
        """Days from creation to completion (or today if not completed)."""
        end_date = self.completed_at.date() if self.completed_at else date.today()
        return (end_date - self.created_at.date()).days

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create_department_transfer(
        cls,
        asset: FixedAsset,
        transfer_date: date,
        source_department: str,
        destination_department: str,
        created_by: UUID,
        reason: str = "",
        notes: str = "",
        transfer_id: UUID | None = None,
    ) -> TransferEntity:
        """Create a department transfer."""
        _validate_asset_transferable(asset)
        _validate_transfer_date(transfer_date, asset.acquisition_date)
        _validate_source_destination(source_department, destination_department)
        now = datetime.now(UTC)
        return cls(
            transfer_id=transfer_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            transfer_date=transfer_date,
            transfer_type=TransferType.DEPARTMENT,
            source=source_department,
            destination=destination_department,
            status=TransferStatus.DRAFT,
            reason=reason,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_location_transfer(
        cls,
        asset: FixedAsset,
        transfer_date: date,
        source_location: str,
        destination_location: str,
        created_by: UUID,
        reason: str = "",
        notes: str = "",
        transfer_id: UUID | None = None,
    ) -> TransferEntity:
        """Create a location transfer."""
        _validate_asset_transferable(asset)
        _validate_transfer_date(transfer_date, asset.acquisition_date)
        _validate_source_destination(source_location, destination_location)
        now = datetime.now(UTC)
        return cls(
            transfer_id=transfer_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            transfer_date=transfer_date,
            transfer_type=TransferType.LOCATION,
            source=source_location,
            destination=destination_location,
            status=TransferStatus.DRAFT,
            reason=reason,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_cost_center_transfer(
        cls,
        asset: FixedAsset,
        transfer_date: date,
        source_cost_center: str,
        destination_cost_center: str,
        created_by: UUID,
        reason: str = "",
        notes: str = "",
        transfer_id: UUID | None = None,
    ) -> TransferEntity:
        """Create a cost center transfer."""
        _validate_asset_transferable(asset)
        _validate_transfer_date(transfer_date, asset.acquisition_date)
        _validate_source_destination(source_cost_center, destination_cost_center)
        now = datetime.now(UTC)
        return cls(
            transfer_id=transfer_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            transfer_date=transfer_date,
            transfer_type=TransferType.COST_CENTER,
            source=source_cost_center,
            destination=destination_cost_center,
            status=TransferStatus.DRAFT,
            reason=reason,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_custodian_transfer(
        cls,
        asset: FixedAsset,
        transfer_date: date,
        source_custodian: str,
        destination_custodian: str,
        created_by: UUID,
        reason: str = "",
        notes: str = "",
        transfer_id: UUID | None = None,
    ) -> TransferEntity:
        """Create a custodian transfer."""
        _validate_asset_transferable(asset)
        _validate_transfer_date(transfer_date, asset.acquisition_date)
        _validate_source_destination(source_custodian, destination_custodian)
        now = datetime.now(UTC)
        return cls(
            transfer_id=transfer_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            transfer_date=transfer_date,
            transfer_type=TransferType.CUSTODIAN,
            source=source_custodian,
            destination=destination_custodian,
            status=TransferStatus.DRAFT,
            reason=reason,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferEntity:
        """Reconstruct from dictionary."""
        transfer_type = TransferType.from_string(data["transfer_type"])
        if transfer_type is None:
            raise TransferError(f"Invalid transfer_type: {data['transfer_type']}")
        status = TransferStatus.from_string(data["status"])
        if status is None:
            raise TransferError(f"Invalid status: {data['status']}")

        def parse_date(key: str) -> date | None:
            val = data.get(key)
            if val is None:
                return None
            if isinstance(val, str):
                return date.fromisoformat(val)
            return val

        def parse_datetime(key: str) -> datetime | None:
            val = data.get(key)
            if val is None:
                return None
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return val

        return cls(
            transfer_id=UUID(data["transfer_id"])
            if isinstance(data["transfer_id"], str)
            else data["transfer_id"],
            asset_id=UUID(data["asset_id"])
            if isinstance(data["asset_id"], str)
            else data["asset_id"],
            asset_code=data["asset_code"],
            asset_name=data["asset_name"],
            transfer_date=parse_date("transfer_date"),
            transfer_type=transfer_type,
            source=data["source"],
            destination=data["destination"],
            status=status,
            reason=data.get("reason", ""),
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            approved_at=parse_datetime("approved_at"),
            completed_by=UUID(data["completed_by"]) if data.get("completed_by") else None,
            completed_at=parse_datetime("completed_at"),
            cancelled_by=UUID(data["cancelled_by"]) if data.get("cancelled_by") else None,
            cancelled_at=parse_datetime("cancelled_at"),
            cancel_reason=data.get("cancel_reason", ""),
            notes=data.get("notes", ""),
            created_at=parse_datetime("created_at") or datetime.now(UTC),
            updated_at=parse_datetime("updated_at") or datetime.now(UTC),
            created_by=UUID(data["created_by"])
            if isinstance(data["created_by"], str)
            else data["created_by"],
            updated_by=UUID(data["updated_by"])
            if isinstance(data["updated_by"], str)
            else data["updated_by"],
            version=data.get("version", 1),
        )

    # ------------------------------------------------------------------------
    # Business Logic (Immutable Transformations)
    # ------------------------------------------------------------------------

    def approve(self, approved_by: UUID) -> TransferEntity:
        """Approve the transfer."""
        if not self.can_approve:
            raise InvalidStatusTransitionError(
                f"Cannot approve transfer in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return TransferEntity(
            transfer_id=self.transfer_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            transfer_date=self.transfer_date,
            transfer_type=self.transfer_type,
            source=self.source,
            destination=self.destination,
            status=TransferStatus.APPROVED,
            reason=self.reason,
            approved_by=approved_by,
            approved_at=now,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=approved_by,
            version=self.version + 1,
        )

    def complete(self, completed_by: UUID) -> TransferEntity:
        """Complete the transfer (asset is moved)."""
        if not self.can_complete:
            raise InvalidStatusTransitionError(
                f"Cannot complete transfer in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return TransferEntity(
            transfer_id=self.transfer_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            transfer_date=self.transfer_date,
            transfer_type=self.transfer_type,
            source=self.source,
            destination=self.destination,
            status=TransferStatus.COMPLETED,
            reason=self.reason,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=completed_by,
            completed_at=now,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=completed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: UUID, reason: str) -> TransferEntity:
        """Cancel the transfer."""
        if not self.can_cancel:
            raise InvalidStatusTransitionError(
                f"Cannot cancel transfer in status {self.status.value}"
            )
        now = datetime.now(UTC)
        cleaned_reason = _validate_reason(reason)
        return TransferEntity(
            transfer_id=self.transfer_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            transfer_date=self.transfer_date,
            transfer_type=self.transfer_type,
            source=self.source,
            destination=self.destination,
            status=TransferStatus.CANCELLED,
            reason=self.reason,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=cancelled_by,
            cancelled_at=now,
            cancel_reason=cleaned_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=cancelled_by,
            version=self.version + 1,
        )

    def update_reason(self, new_reason: str, updated_by: UUID) -> TransferEntity:
        """Update reason (only allowed in DRAFT)."""
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit transfer in status {self.status.value}"
            )
        cleaned_reason = _validate_reason(new_reason)
        now = datetime.now(UTC)
        return TransferEntity(
            transfer_id=self.transfer_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            transfer_date=self.transfer_date,
            transfer_type=self.transfer_type,
            source=self.source,
            destination=self.destination,
            status=self.status,
            reason=cleaned_reason,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_notes(self, new_notes: str, updated_by: UUID) -> TransferEntity:
        """Update notes (only allowed in DRAFT)."""
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit transfer in status {self.status.value}"
            )
        cleaned_notes = _validate_notes(new_notes)
        now = datetime.now(UTC)
        return TransferEntity(
            transfer_id=self.transfer_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            transfer_date=self.transfer_date,
            transfer_type=self.transfer_type,
            source=self.source,
            destination=self.destination,
            status=self.status,
            reason=self.reason,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            notes=cleaned_notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "transfer_id": str(self.transfer_id),
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "transfer_date": self.transfer_date.isoformat(),
            "transfer_type": self.transfer_type.value,
            "transfer_type_display": self.transfer_type.display_name(),
            "source": self.source,
            "destination": self.destination,
            "status": self.status.value,
            "status_display": self.status.display_name(),
            "reason": self.reason,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "completed_by": str(self.completed_by) if self.completed_by else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cancelled_by": str(self.cancelled_by) if self.cancelled_by else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_by": str(self.updated_by),
            "version": self.version,
            "duration_days": self.duration_days,
            "can_approve": self.can_approve,
            "can_complete": self.can_complete,
            "can_cancel": self.can_cancel,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "transfer_id": self.transfer_id,
            "asset_id": self.asset_id,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "transfer_date": self.transfer_date,
            "transfer_type": self.transfer_type.value,
            "source": self.source,
            "destination": self.destination,
            "status": self.status.value,
            "reason": self.reason,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "completed_by": self.completed_by,
            "completed_at": self.completed_at,
            "cancelled_by": self.cancelled_by,
            "cancelled_at": self.cancelled_at,
            "cancel_reason": self.cancel_reason,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
        }

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.display

    def __repr__(self) -> str:
        return f"TransferEntity(asset={self.asset_code}, status={self.status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TransferEntity):
            return False
        return self.transfer_id == other.transfer_id

    def __hash__(self) -> int:
        return hash(self.transfer_id)


# ============================================================================
# Type Alias for Compatibility
# ============================================================================

AssetTransfer = TransferEntity


# ============================================================================
# Repository Protocol
# ============================================================================


class TransferRepository:
    """Repository protocol for TransferEntity."""

    async def get_by_id(self, transfer_id: UUID, legal_entity_id: UUID) -> TransferEntity | None:
        raise NotImplementedError

    async def get_by_asset(self, asset_id: UUID, legal_entity_id: UUID) -> list[TransferEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
    ) -> list[TransferEntity]:
        raise NotImplementedError

    async def get_by_status(
        self,
        legal_entity_id: UUID,
        status: TransferStatus,
    ) -> list[TransferEntity]:
        raise NotImplementedError

    async def get_by_type(
        self,
        legal_entity_id: UUID,
        transfer_type: TransferType,
    ) -> list[TransferEntity]:
        raise NotImplementedError

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[TransferEntity]:
        """Get all transfers pending approval (DRAFT status)."""
        return await self.get_by_status(legal_entity_id, TransferStatus.DRAFT)

    async def save(self, transfer: TransferEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, transfer_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Helper Functions
# ============================================================================


def is_transfer_allowed(asset: FixedAsset) -> tuple[bool, str]:
    """Check if an asset can be transferred."""
    if asset.is_disposed:
        return False, "Asset is already disposed and cannot be transferred"
    if not asset.status.can_transfer():
        return False, f"Asset is in status {asset.status.display_name()} and cannot be transferred"
    return True, ""


def get_transfer_summary(transfers: list[TransferEntity]) -> dict[str, Any]:
    """Get summary statistics for a list of transfers."""
    total = len(transfers)
    by_status = {}
    by_type = {}
    for t in transfers:
        by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
        by_type[t.transfer_type.value] = by_type.get(t.transfer_type.value, 0) + 1
    return {
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
    }


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AssetNotTransferableError",
    "AssetTransfer",
    "InvalidStatusTransitionError",
    "InvalidTransferDateError",
    "SameSourceDestinationError",
    "TransferAlreadyCompletedError",
    "TransferEntity",
    "TransferError",
    "TransferRepository",
    "TransferStatus",
    "TransferType",
    "get_transfer_summary",
    "is_transfer_allowed",
]
