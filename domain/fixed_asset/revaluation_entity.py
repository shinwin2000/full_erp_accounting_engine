#!/usr/bin/env python3
"""
Module: revaluation_entity.py

Layer: Domain / Fixed Asset

Responsibility:
    Entity for asset revaluation (revaluasi aset tetap).

    Records changes in asset value to fair value, including increases (surplus)
    and decreases (deficit). Revaluation affects net book value and creates
    revaluation surplus in equity.

Business rules:
    - Revaluation can only be applied to active assets (not disposed).
    - New value must be positive.
    - Revaluation amount = new_value - old_value (positive for increase).
    - Revaluation surplus (increase) goes to equity reserve.
    - Revaluation deficit (decrease) is recognized as impairment loss.
    - Revaluation requires approval (DRAFT -> APPROVED -> POSTED).
    - Posted revaluations cannot be modified.
    - Each revaluation creates a new asset entity with updated cost/NBV.
    - Version increments on every change (optimistic locking).

Dependencies:
    - Python standard library (uuid, datetime, decimal, logging, re)
    - domain.fixed_asset.asset_entity (FixedAsset) for TYPE_CHECKING

Audit:
    Every revaluation should be logged; domain events emitted separately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from domain.fixed_asset.asset_entity import FixedAsset

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class RevaluationType(Enum):
    """Type of revaluation: increase or decrease."""

    INCREASE = "increase"  # Peningkatan nilai (surplus)
    DECREASE = "decrease"  # Penurunan nilai (deficit)

    def display_name(self) -> str:
        names = {
            RevaluationType.INCREASE: "Peningkatan Nilai",
            RevaluationType.DECREASE: "Penurunan Nilai",
        }
        return names.get(self, self.value)

    def is_increase(self) -> bool:
        return self == RevaluationType.INCREASE

    def is_decrease(self) -> bool:
        return self == RevaluationType.DECREASE

    @classmethod
    def from_amount(cls, old_value: Decimal, new_value: Decimal) -> RevaluationType:
        """Determine revaluation type from old and new values."""
        if new_value > old_value:
            return RevaluationType.INCREASE
        elif new_value < old_value:
            return RevaluationType.DECREASE
        else:
            raise ValueError("No change in value, cannot create revaluation")


class RevaluationMethod(Enum):
    """Method used for revaluation."""

    FAIR_VALUE = "fair_value"  # Nilai wajar berdasarkan pasar
    INDEXATION = "indexation"  # Indeksasi (inflasi)
    APPRAISAL = "appraisal"  # Penilaian independen oleh appraisal firm
    MANAGEMENT = "management"  # Estimasi manajemen

    def display_name(self) -> str:
        names = {
            RevaluationMethod.FAIR_VALUE: "Nilai Wajar",
            RevaluationMethod.INDEXATION: "Indeksasi",
            RevaluationMethod.APPRAISAL: "Penilaian Independen",
            RevaluationMethod.MANAGEMENT: "Estimasi Manajemen",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> RevaluationMethod | None:
        for m in cls:
            if m.value == value.lower():
                return m
        return None


class RevaluationStatus(Enum):
    """Status of revaluation process."""

    DRAFT = "draft"  # Draft, belum diajukan
    APPROVED = "approved"  # Disetujui
    POSTED = "posted"  # Diposting ke buku besar (final)
    CANCELLED = "cancelled"  # Dibatalkan

    def can_edit(self) -> bool:
        return self == RevaluationStatus.DRAFT

    def can_approve(self) -> bool:
        return self == RevaluationStatus.DRAFT

    def can_post(self) -> bool:
        return self == RevaluationStatus.APPROVED

    def can_cancel(self) -> bool:
        return self in (RevaluationStatus.DRAFT, RevaluationStatus.APPROVED)

    def display_name(self) -> str:
        names = {
            RevaluationStatus.DRAFT: "Draft",
            RevaluationStatus.APPROVED: "Disetujui",
            RevaluationStatus.POSTED: "Diposting",
            RevaluationStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> RevaluationStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class RevaluationError(ValueError):
    """Base exception for revaluation errors."""

    pass


class InvalidRevaluationValueError(RevaluationError):
    """Raised when revaluation value is invalid."""

    pass


class InvalidStatusTransitionError(RevaluationError):
    """Raised when status transition is not allowed."""

    pass


class RevaluationAlreadyPostedError(RevaluationError):
    """Raised when trying to modify a posted revaluation."""

    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_revaluation_date(date_val: date) -> None:
    """Validate revaluation date (cannot be in future)."""
    if date_val > date.today():
        raise InvalidRevaluationValueError(f"Revaluation date {date_val} cannot be in the future")


def _validate_values(old_value: Decimal, new_value: Decimal) -> tuple[Decimal, Decimal]:
    """Validate old and new values (positive)."""
    if not isinstance(old_value, Decimal):
        try:
            old_value = Decimal(str(old_value))
        except Exception:
            raise InvalidRevaluationValueError(f"Invalid old_value type: {type(old_value)}")
    if not isinstance(new_value, Decimal):
        try:
            new_value = Decimal(str(new_value))
        except Exception:
            raise InvalidRevaluationValueError(f"Invalid new_value type: {type(new_value)}")
    if old_value <= 0:
        raise InvalidRevaluationValueError(f"Old value must be positive: {old_value}")
    if new_value <= 0:
        raise InvalidRevaluationValueError(f"New value must be positive: {new_value}")
    if new_value == old_value:
        raise InvalidRevaluationValueError("New value must be different from old value")
    # Round to 2 decimal places
    old_rounded = old_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    new_rounded = new_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return old_rounded, new_rounded


def _validate_currency(currency: str) -> str:
    """Validate currency code."""
    if not currency or not isinstance(currency, str):
        raise RevaluationError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise RevaluationError(f"Currency code must be exactly 3 characters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise RevaluationError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


def _validate_appraisal_firm(firm: str | None) -> str | None:
    """Validate appraisal firm name."""
    if firm is None:
        return None
    cleaned = firm.strip()
    if len(cleaned) > 200:
        raise RevaluationError("Appraisal firm name must not exceed 200 characters")
    return cleaned if cleaned else None


def _validate_report_number(number: str | None) -> str | None:
    """Validate appraisal report number."""
    if number is None:
        return None
    cleaned = number.strip()
    if len(cleaned) > 50:
        raise RevaluationError("Report number must not exceed 50 characters")
    return cleaned if cleaned else None


# ============================================================================
# Entity: RevaluationEntity
# ============================================================================


@dataclass
class RevaluationEntity:
    """
    Entity for asset revaluation.

    This entity is mutable (dataclass) but changes create new instances
    with incremented version for optimistic locking.

    Attributes:
        revaluation_id: Unique identifier
        asset_id: Asset being revalued
        asset_code: Asset code
        asset_name: Asset name
        revaluation_date: Date of revaluation
        old_value: Net book value before revaluation
        new_value: Fair value after revaluation
        revaluation_type: INCREASE or DECREASE
        revaluation_method: Method used
        revaluation_amount: Change amount (positive for increase)
        status: Current status
        appraisal_firm: Name of appraisal firm (if applicable)
        appraisal_report_number: Report reference number
        approved_by, approved_at: Approval info
        posted_by, posted_at: Posting info
        cancelled_by, cancelled_at, cancel_reason: Cancellation info
        notes: Additional notes
        created_by, created_at, updated_by, updated_at, version
    """

    # ========== Mandatory Fields ==========
    revaluation_id: UUID
    asset_id: UUID
    asset_code: str
    asset_name: str
    revaluation_date: date
    old_value: Decimal
    new_value: Decimal
    revaluation_type: RevaluationType
    revaluation_method: RevaluationMethod
    revaluation_amount: Decimal
    status: RevaluationStatus

    # ========== Optional Fields ==========
    appraisal_firm: str | None = None
    appraisal_report_number: str | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    posted_by: UUID | None = None
    posted_at: datetime | None = None
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
        """Validate revaluation data."""
        # Validate asset_code
        if not self.asset_code or len(self.asset_code.strip()) < 2:
            raise RevaluationError("Asset code must be at least 2 characters")
        object.__setattr__(self, "asset_code", self.asset_code.strip())

        # Validate asset_name
        if not self.asset_name or len(self.asset_name.strip()) < 2:
            raise RevaluationError("Asset name must be at least 2 characters")
        object.__setattr__(self, "asset_name", self.asset_name.strip())

        # Validate revaluation_date
        _validate_revaluation_date(self.revaluation_date)

        # Validate values
        old_val, new_val = _validate_values(self.old_value, self.new_value)
        if old_val != self.old_value:
            object.__setattr__(self, "old_value", old_val)
        if new_val != self.new_value:
            object.__setattr__(self, "new_value", new_val)

        # Validate revaluation_type consistency
        expected_type = RevaluationType.from_amount(self.old_value, self.new_value)
        if self.revaluation_type != expected_type:
            raise RevaluationError(
                f"Revaluation type mismatch: expected {expected_type.value}, got {self.revaluation_type.value}"
            )

        # Validate revaluation_amount = new_value - old_value
        expected_amount = self.new_value - self.old_value
        if abs(self.revaluation_amount - expected_amount) > Decimal("0.01"):
            raise RevaluationError(
                f"Revaluation amount mismatch: expected {expected_amount}, got {self.revaluation_amount}"
            )

        # Validate revaluation_method
        if not isinstance(self.revaluation_method, RevaluationMethod):
            raise RevaluationError(f"Invalid revaluation_method: {self.revaluation_method}")

        # Validate status
        if not isinstance(self.status, RevaluationStatus):
            raise RevaluationError(f"Invalid status: {self.status}")

        # Validate appraisal fields
        cleaned_firm = _validate_appraisal_firm(self.appraisal_firm)
        if cleaned_firm != self.appraisal_firm:
            object.__setattr__(self, "appraisal_firm", cleaned_firm)
        cleaned_report = _validate_report_number(self.appraisal_report_number)
        if cleaned_report != self.appraisal_report_number:
            object.__setattr__(self, "appraisal_report_number", cleaned_report)

        # Validate status consistency
        if self.status == RevaluationStatus.APPROVED and not self.approved_by:
            raise RevaluationError("Approved revaluation must have approved_by")
        if self.status == RevaluationStatus.POSTED and not self.posted_by:
            raise RevaluationError("Posted revaluation must have posted_by")
        if self.status == RevaluationStatus.CANCELLED and not self.cancelled_by:
            raise RevaluationError("Cancelled revaluation must have cancelled_by")

        # Validate timestamps UTC
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        if self.posted_at and self.posted_at.tzinfo is None:
            object.__setattr__(self, "posted_at", self.posted_at.replace(tzinfo=UTC))
        if self.cancelled_at and self.cancelled_at.tzinfo is None:
            object.__setattr__(self, "cancelled_at", self.cancelled_at.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

        # Validate version
        if self.version < 1:
            raise RevaluationError("Version must be >= 1")

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_increase(self) -> bool:
        return self.revaluation_type == RevaluationType.INCREASE

    @property
    def is_decrease(self) -> bool:
        return self.revaluation_type == RevaluationType.DECREASE

    @property
    def is_draft(self) -> bool:
        return self.status == RevaluationStatus.DRAFT

    @property
    def is_approved(self) -> bool:
        return self.status == RevaluationStatus.APPROVED

    @property
    def is_posted(self) -> bool:
        return self.status == RevaluationStatus.POSTED

    @property
    def is_cancelled(self) -> bool:
        return self.status == RevaluationStatus.CANCELLED

    @property
    def can_edit(self) -> bool:
        return self.status.can_edit()

    @property
    def can_approve(self) -> bool:
        return self.status.can_approve()

    @property
    def can_post(self) -> bool:
        return self.status.can_post()

    @property
    def can_cancel(self) -> bool:
        return self.status.can_cancel()

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        asset_id: UUID,
        asset_code: str,
        asset_name: str,
        old_value: Decimal,
        new_value: Decimal,
        revaluation_method: RevaluationMethod,
        revaluation_date: date | None = None,
        appraisal_firm: str | None = None,
        appraisal_report_number: str | None = None,
        notes: str = "",
        created_by: UUID | None = None,
        revaluation_id: UUID | None = None,
    ) -> RevaluationEntity:
        """Create a new revaluation entity in DRAFT status."""
        if revaluation_date is None:
            revaluation_date = date.today()
        _validate_revaluation_date(revaluation_date)
        old_rounded, new_rounded = _validate_values(old_value, new_value)
        revaluation_type = RevaluationType.from_amount(old_rounded, new_rounded)
        revaluation_amount = new_rounded - old_rounded
        now = datetime.now(UTC)
        created_by_uuid = created_by or uuid4()
        return cls(
            revaluation_id=revaluation_id or uuid4(),
            asset_id=asset_id,
            asset_code=asset_code,
            asset_name=asset_name,
            revaluation_date=revaluation_date,
            old_value=old_rounded,
            new_value=new_rounded,
            revaluation_type=revaluation_type,
            revaluation_method=revaluation_method,
            revaluation_amount=revaluation_amount,
            status=RevaluationStatus.DRAFT,
            appraisal_firm=appraisal_firm,
            appraisal_report_number=appraisal_report_number,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by_uuid,
            updated_by=created_by_uuid,
            version=1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RevaluationEntity:
        """Reconstruct from dictionary."""
        revaluation_method = RevaluationMethod.from_string(data["revaluation_method"])
        if revaluation_method is None:
            raise RevaluationError(f"Invalid revaluation_method: {data['revaluation_method']}")
        status = RevaluationStatus.from_string(data["status"])
        if status is None:
            raise RevaluationError(f"Invalid status: {data['status']}")
        revaluation_type = (
            RevaluationType(data["revaluation_type"]) if "revaluation_type" in data else None
        )

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

        revaluation_date = parse_date("revaluation_date")
        if revaluation_date is None:
            raise RevaluationError("revaluation_date is required")

        return cls(
            revaluation_id=UUID(data["revaluation_id"])
            if isinstance(data["revaluation_id"], str)
            else data["revaluation_id"],
            asset_id=UUID(data["asset_id"])
            if isinstance(data["asset_id"], str)
            else data["asset_id"],
            asset_code=data["asset_code"],
            asset_name=data["asset_name"],
            revaluation_date=revaluation_date,
            old_value=Decimal(str(data["old_value"])),
            new_value=Decimal(str(data["new_value"])),
            revaluation_type=revaluation_type
            or RevaluationType.from_amount(
                Decimal(str(data["old_value"])), Decimal(str(data["new_value"]))
            ),
            revaluation_method=revaluation_method,
            revaluation_amount=Decimal(str(data.get("revaluation_amount", 0))),
            status=status,
            appraisal_firm=data.get("appraisal_firm"),
            appraisal_report_number=data.get("appraisal_report_number"),
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            approved_at=parse_datetime("approved_at"),
            posted_by=UUID(data["posted_by"]) if data.get("posted_by") else None,
            posted_at=parse_datetime("posted_at"),
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

    def approve(self, approved_by: UUID) -> RevaluationEntity:
        """Approve the revaluation."""
        if not self.can_approve:
            raise InvalidStatusTransitionError(
                f"Cannot approve revaluation in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return RevaluationEntity(
            revaluation_id=self.revaluation_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            revaluation_date=self.revaluation_date,
            old_value=self.old_value,
            new_value=self.new_value,
            revaluation_type=self.revaluation_type,
            revaluation_method=self.revaluation_method,
            revaluation_amount=self.revaluation_amount,
            status=RevaluationStatus.APPROVED,
            appraisal_firm=self.appraisal_firm,
            appraisal_report_number=self.appraisal_report_number,
            approved_by=approved_by,
            approved_at=now,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
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

    def post(self, posted_by: UUID) -> RevaluationEntity:
        """Post the revaluation (finalize, update asset NBV)."""
        if not self.can_post:
            raise InvalidStatusTransitionError(
                f"Cannot post revaluation in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return RevaluationEntity(
            revaluation_id=self.revaluation_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            revaluation_date=self.revaluation_date,
            old_value=self.old_value,
            new_value=self.new_value,
            revaluation_type=self.revaluation_type,
            revaluation_method=self.revaluation_method,
            revaluation_amount=self.revaluation_amount,
            status=RevaluationStatus.POSTED,
            appraisal_firm=self.appraisal_firm,
            appraisal_report_number=self.appraisal_report_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=posted_by,
            posted_at=now,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=posted_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: UUID, reason: str) -> RevaluationEntity:
        """Cancel the revaluation."""
        if not self.can_cancel:
            raise InvalidStatusTransitionError(
                f"Cannot cancel revaluation in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return RevaluationEntity(
            revaluation_id=self.revaluation_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            revaluation_date=self.revaluation_date,
            old_value=self.old_value,
            new_value=self.new_value,
            revaluation_type=self.revaluation_type,
            revaluation_method=self.revaluation_method,
            revaluation_amount=self.revaluation_amount,
            status=RevaluationStatus.CANCELLED,
            appraisal_firm=self.appraisal_firm,
            appraisal_report_number=self.appraisal_report_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            cancelled_by=cancelled_by,
            cancelled_at=now,
            cancel_reason=reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=cancelled_by,
            version=self.version + 1,
        )

    def update_notes(self, new_notes: str, updated_by: UUID) -> RevaluationEntity:
        """Update notes (only allowed in DRAFT)."""
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit revaluation in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return RevaluationEntity(
            revaluation_id=self.revaluation_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            revaluation_date=self.revaluation_date,
            old_value=self.old_value,
            new_value=self.new_value,
            revaluation_type=self.revaluation_type,
            revaluation_method=self.revaluation_method,
            revaluation_amount=self.revaluation_amount,
            status=self.status,
            appraisal_firm=self.appraisal_firm,
            appraisal_report_number=self.appraisal_report_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            notes=new_notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_appraisal_info(
        self,
        firm: str | None,
        report_number: str | None,
        updated_by: UUID,
    ) -> RevaluationEntity:
        """Update appraisal firm and report number (only allowed in DRAFT)."""
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit revaluation in status {self.status.value}"
            )
        cleaned_firm = _validate_appraisal_firm(firm)
        cleaned_report = _validate_report_number(report_number)
        now = datetime.now(UTC)
        return RevaluationEntity(
            revaluation_id=self.revaluation_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            revaluation_date=self.revaluation_date,
            old_value=self.old_value,
            new_value=self.new_value,
            revaluation_type=self.revaluation_type,
            revaluation_method=self.revaluation_method,
            revaluation_amount=self.revaluation_amount,
            status=self.status,
            appraisal_firm=cleaned_firm,
            appraisal_report_number=cleaned_report,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
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

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "revaluation_id": str(self.revaluation_id),
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "revaluation_date": self.revaluation_date.isoformat(),
            "old_value": str(self.old_value),
            "new_value": str(self.new_value),
            "revaluation_type": self.revaluation_type.value,
            "revaluation_type_display": self.revaluation_type.display_name(),
            "revaluation_method": self.revaluation_method.value,
            "revaluation_method_display": self.revaluation_method.display_name(),
            "revaluation_amount": str(self.revaluation_amount),
            "status": self.status.value,
            "status_display": self.status.display_name(),
            "appraisal_firm": self.appraisal_firm,
            "appraisal_report_number": self.appraisal_report_number,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "posted_by": str(self.posted_by) if self.posted_by else None,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "cancelled_by": str(self.cancelled_by) if self.cancelled_by else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_by": str(self.updated_by),
            "version": self.version,
            "can_approve": self.can_approve,
            "can_post": self.can_post,
            "can_cancel": self.can_cancel,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "revaluation_id": self.revaluation_id,
            "asset_id": self.asset_id,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "revaluation_date": self.revaluation_date,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "revaluation_type": self.revaluation_type.value,
            "revaluation_method": self.revaluation_method.value,
            "revaluation_amount": self.revaluation_amount,
            "status": self.status.value,
            "appraisal_firm": self.appraisal_firm,
            "appraisal_report_number": self.appraisal_report_number,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "posted_by": self.posted_by,
            "posted_at": self.posted_at,
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
        return f"Revaluation({self.asset_code}, {self.revaluation_type.value}: {self.revaluation_amount})"

    def __repr__(self) -> str:
        return f"RevaluationEntity(asset={self.asset_code}, status={self.status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RevaluationEntity):
            return False
        return self.revaluation_id == other.revaluation_id

    def __hash__(self) -> int:
        return hash(self.revaluation_id)


# ============================================================================
# Type Aliases for Compatibility
# ============================================================================

AssetRevaluation = RevaluationEntity
Revaluation = RevaluationEntity  # added for repository compatibility


# ============================================================================
# Repository Protocol
# ============================================================================


class RevaluationRepository:
    """Repository protocol for RevaluationEntity."""

    async def get_by_id(
        self, revaluation_id: UUID, legal_entity_id: UUID
    ) -> RevaluationEntity | None:
        raise NotImplementedError

    async def get_by_asset(self, asset_id: UUID, legal_entity_id: UUID) -> list[RevaluationEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
    ) -> list[RevaluationEntity]:
        raise NotImplementedError

    async def get_by_status(
        self,
        legal_entity_id: UUID,
        status: RevaluationStatus,
    ) -> list[RevaluationEntity]:
        raise NotImplementedError

    async def get_latest_for_asset(
        self, asset_id: UUID, legal_entity_id: UUID
    ) -> RevaluationEntity | None:
        """Get the most recent revaluation for an asset."""
        raise NotImplementedError

    async def save(self, revaluation: RevaluationEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, revaluation_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_revaluation_surplus(asset: FixedAsset, new_value: Decimal) -> Decimal:
    """
    Calculate the revaluation surplus (increase in equity) after revaluation.
    """
    old_nbv = asset.net_book_value
    return max(Decimal("0"), new_value - old_nbv)


def calculate_revaluation_deficit(asset: FixedAsset, new_value: Decimal) -> Decimal:
    """
    Calculate the revaluation deficit (decrease in value) after revaluation.
    """
    old_nbv = asset.net_book_value
    return max(Decimal("0"), old_nbv - new_value)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AssetRevaluation",
    "InvalidRevaluationValueError",
    "InvalidStatusTransitionError",
    "Revaluation",
    "RevaluationAlreadyPostedError",
    "RevaluationEntity",
    "RevaluationError",
    "RevaluationMethod",
    "RevaluationRepository",
    "RevaluationStatus",
    "RevaluationType",
    "calculate_revaluation_deficit",
    "calculate_revaluation_surplus",
]
