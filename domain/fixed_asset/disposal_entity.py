#!/usr/bin/env python3
"""
Module: disposal_entity.py

Layer: Domain / Fixed Asset

Responsibility:
    Entity for asset disposal (pelepasan aset tetap).

    Records the disposal of a fixed asset through sale, scrap, donation,
    trade-in, theft, or loss. Tracks proceeds, gain/loss calculation,
    and status transitions (DRAFT -> APPROVED -> COMPLETED -> CANCELLED).

Business rules:
    - Disposal can only be created for active assets (not already disposed).
    - Proceeds cannot be negative.
    - Disposal date cannot be in the future or before acquisition date.
    - Gain/loss = proceeds - NBV at disposal.
    - Status transitions: DRAFT -> APPROVED -> COMPLETED, or CANCELLED from DRAFT/APPROVED.
    - Completed disposals cannot be modified or cancelled.
    - Version increments on every change (optimistic locking).

Dependencies:
    - Python standard library (uuid, datetime, decimal, logging, re)
    - domain.fixed_asset.asset_entity (FixedAsset) for TYPE_CHECKING

Audit:
    Every disposal should be logged; domain events emitted separately.
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


class DisposalType(Enum):
    """Type of asset disposal."""

    SALE = "sale"  # Penjualan
    SCRAP = "scrap"  # Besi tua / dimusnahkan
    DONATION = "donation"  # Donasi
    TRADE_IN = "trade_in"  # Tukar tambah
    LOSS = "loss"  # Hilang
    THEFT = "theft"  # Pencurian

    def display_name(self) -> str:
        names = {
            DisposalType.SALE: "Penjualan",
            DisposalType.SCRAP: "Besi Tua",
            DisposalType.DONATION: "Donasi",
            DisposalType.TRADE_IN: "Tukar Tambah",
            DisposalType.LOSS: "Hilang",
            DisposalType.THEFT: "Pencurian",
        }
        return names.get(self, self.value)

    def requires_approval(self) -> bool:
        """Does this disposal type require higher-level approval?"""
        return self in (DisposalType.SALE, DisposalType.TRADE_IN, DisposalType.DONATION)

    def has_proceeds(self) -> bool:
        """Does this disposal type typically have proceeds?"""
        return self in (DisposalType.SALE, DisposalType.TRADE_IN)

    @classmethod
    def from_string(cls, value: str) -> DisposalType | None:
        for t in cls:
            if t.value == value.lower():
                return t
        return None


class DisposalStatus(Enum):
    """Status of disposal process."""

    DRAFT = "draft"  # Draft, belum diajukan
    APPROVED = "approved"  # Disetujui
    COMPLETED = "completed"  # Selesai (aset telah dihapus dari buku)
    CANCELLED = "cancelled"  # Dibatalkan

    def can_edit(self) -> bool:
        return self == DisposalStatus.DRAFT

    def can_approve(self) -> bool:
        return self == DisposalStatus.DRAFT

    def can_complete(self) -> bool:
        return self == DisposalStatus.APPROVED

    def can_cancel(self) -> bool:
        return self in (DisposalStatus.DRAFT, DisposalStatus.APPROVED)

    def display_name(self) -> str:
        names = {
            DisposalStatus.DRAFT: "Draft",
            DisposalStatus.APPROVED: "Disetujui",
            DisposalStatus.COMPLETED: "Selesai",
            DisposalStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> DisposalStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class DisposalError(ValueError):
    """Base exception for disposal errors."""

    pass


class InvalidDisposalDateError(DisposalError):
    """Raised when disposal date is invalid."""

    pass


class InvalidProceedsError(DisposalError):
    """Raised when proceeds are invalid."""

    pass


class AssetAlreadyDisposedError(DisposalError):
    """Raised when trying to dispose an already disposed asset."""

    pass


class InvalidStatusTransitionError(DisposalError):
    """Raised when status transition is not allowed."""

    pass


class DisposalAlreadyCompletedError(DisposalError):
    """Raised when trying to modify a completed disposal."""

    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_disposal_date(disposal_date: date, acquisition_date: date) -> None:
    """Validate disposal date (not future, not before acquisition)."""
    if disposal_date > date.today():
        raise InvalidDisposalDateError(f"Disposal date {disposal_date} cannot be in the future")
    if disposal_date < acquisition_date:
        raise InvalidDisposalDateError(
            f"Disposal date {disposal_date} cannot be before acquisition date {acquisition_date}"
        )


def _validate_proceeds(proceeds: Decimal) -> Decimal:
    """Validate proceeds (non-negative)."""
    if not isinstance(proceeds, Decimal):
        try:
            proceeds = Decimal(str(proceeds))
        except Exception:
            raise InvalidProceedsError(f"Invalid proceeds type: {type(proceeds)}")
    if proceeds < 0:
        raise InvalidProceedsError(f"Proceeds cannot be negative: {proceeds}")
    return proceeds.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_nbv(nbv: Decimal) -> Decimal:
    """Validate NBV (non-negative)."""
    if not isinstance(nbv, Decimal):
        try:
            nbv = Decimal(str(nbv))
        except Exception:
            raise DisposalError(f"Invalid NBV type: {type(nbv)}")
    if nbv < 0:
        raise DisposalError(f"NBV cannot be negative: {nbv}")
    return nbv.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _calculate_gain_loss(proceeds: Decimal, nbv: Decimal) -> Decimal:
    """Calculate gain (positive) or loss (negative)."""
    return proceeds - nbv


def _validate_gain_loss(gain_loss: Decimal, proceeds: Decimal, nbv: Decimal) -> Decimal:
    """Validate gain/loss matches proceeds - nbv."""
    expected = proceeds - nbv
    if abs(gain_loss - expected) > Decimal("0.01"):
        raise DisposalError(f"Gain/loss mismatch: expected {expected}, got {gain_loss}")
    return gain_loss.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_currency(currency: str) -> str:
    """Validate currency code."""
    if not currency or not isinstance(currency, str):
        raise DisposalError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise DisposalError(f"Currency code must be exactly 3 characters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise DisposalError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


def _validate_customer_name(name: str | None) -> str | None:
    """Validate customer name."""
    if name is None:
        return None
    cleaned = name.strip()
    if len(cleaned) > 200:
        raise DisposalError("Customer name must not exceed 200 characters")
    return cleaned if cleaned else None


def _validate_invoice_number(inv: str | None) -> str | None:
    """Validate invoice number."""
    if inv is None:
        return None
    cleaned = inv.strip()
    if len(cleaned) > 50:
        raise DisposalError("Invoice number must not exceed 50 characters")
    return cleaned if cleaned else None


def _validate_reason(reason: str) -> str:
    """Validate reason (not empty for certain disposal types)."""
    cleaned = reason.strip()
    if len(cleaned) > 500:
        raise DisposalError("Reason must not exceed 500 characters")
    return cleaned


def _validate_asset_code(code: str) -> str:
    """Validate asset code format."""
    if not code or not isinstance(code, str):
        raise DisposalError("Asset code must be a non-empty string")
    cleaned = code.strip()
    if len(cleaned) < 2:
        raise DisposalError("Asset code must be at least 2 characters")
    if len(cleaned) > 30:
        raise DisposalError("Asset code must not exceed 30 characters")
    return cleaned


def _validate_asset_name(name: str) -> str:
    """Validate asset name."""
    if not name or not isinstance(name, str):
        raise DisposalError("Asset name must be a non-empty string")
    cleaned = name.strip()
    if len(cleaned) < 2:
        raise DisposalError("Asset name must be at least 2 characters")
    if len(cleaned) > 200:
        raise DisposalError("Asset name must not exceed 200 characters")
    return cleaned


# ============================================================================
# Entity: DisposalEntity
# ============================================================================


@dataclass
class DisposalEntity:
    """
    Entity for asset disposal.

    This entity is mutable (dataclass) but changes create new instances
    with incremented version for optimistic locking.

    Attributes:
        disposal_id: Unique identifier
        asset_id: Asset being disposed
        asset_code: Asset code
        asset_name: Asset name
        disposal_date: Date of disposal
        disposal_type: Type of disposal
        proceeds: Amount received from disposal (0 for scrap/donation)
        nbv_at_disposal: Net book value at disposal date
        gain_loss: Gain (positive) or loss (negative)
        currency: Currency code
        status: Current status
        customer_id: Optional customer ID (for sale)
        customer_name: Optional customer name
        invoice_number: Optional invoice reference
        approved_by, approved_at: Approval info
        completed_by, completed_at: Completion info
        cancelled_by, cancelled_at, cancel_reason: Cancellation info
        reason: Reason for disposal
        notes: Additional notes
        created_by, created_at, updated_by, updated_at, version
    """

    # ========== Mandatory Fields ==========
    disposal_id: UUID
    asset_id: UUID
    asset_code: str
    asset_name: str
    disposal_date: date
    disposal_type: DisposalType
    proceeds: Decimal
    nbv_at_disposal: Decimal
    gain_loss: Decimal
    currency: str
    status: DisposalStatus

    # ========== Optional Fields ==========
    customer_id: UUID | None = None
    customer_name: str | None = None
    invoice_number: str | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    completed_by: UUID | None = None
    completed_at: datetime | None = None
    cancelled_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
    reason: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=uuid4)
    updated_by: UUID = field(default_factory=uuid4)
    version: int = 1

    def __post_init__(self) -> None:
        """Validate disposal data."""
        # Validate asset_code
        normalized_code = _validate_asset_code(self.asset_code)
        if normalized_code != self.asset_code:
            object.__setattr__(self, "asset_code", normalized_code)

        # Validate asset_name
        normalized_name = _validate_asset_name(self.asset_name)
        if normalized_name != self.asset_name:
            object.__setattr__(self, "asset_name", normalized_name)

        # Validate disposal_type
        if not isinstance(self.disposal_type, DisposalType):
            raise DisposalError(f"Invalid disposal_type: {self.disposal_type}")

        # Validate status
        if not isinstance(self.status, DisposalStatus):
            raise DisposalError(f"Invalid status: {self.status}")

        # Disposal date validation requires acquisition date - skip here, done in factory
        # We'll validate later when asset is provided

        # Validate proceeds
        normalized_proceeds = _validate_proceeds(self.proceeds)
        if normalized_proceeds != self.proceeds:
            object.__setattr__(self, "proceeds", normalized_proceeds)

        # Validate NBV
        normalized_nbv = _validate_nbv(self.nbv_at_disposal)
        if normalized_nbv != self.nbv_at_disposal:
            object.__setattr__(self, "nbv_at_disposal", normalized_nbv)

        # Validate gain/loss
        normalized_gain = _validate_gain_loss(self.gain_loss, self.proceeds, self.nbv_at_disposal)
        if normalized_gain != self.gain_loss:
            object.__setattr__(self, "gain_loss", normalized_gain)

        # Validate currency
        normalized_currency = _validate_currency(self.currency)
        if normalized_currency != self.currency:
            object.__setattr__(self, "currency", normalized_currency)

        # Validate customer fields
        cleaned_customer = _validate_customer_name(self.customer_name)
        if cleaned_customer != self.customer_name:
            object.__setattr__(self, "customer_name", cleaned_customer)
        cleaned_invoice = _validate_invoice_number(self.invoice_number)
        if cleaned_invoice != self.invoice_number:
            object.__setattr__(self, "invoice_number", cleaned_invoice)
        cleaned_reason = _validate_reason(self.reason)
        if cleaned_reason != self.reason:
            object.__setattr__(self, "reason", cleaned_reason)

        # Validate status consistency
        if self.status == DisposalStatus.APPROVED and not self.approved_by:
            raise DisposalError("Approved disposal must have approved_by")
        if self.status == DisposalStatus.COMPLETED and not self.completed_by:
            raise DisposalError("Completed disposal must have completed_by")
        if self.status == DisposalStatus.CANCELLED and not self.cancelled_by:
            raise DisposalError("Cancelled disposal must have cancelled_by")

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
            raise DisposalError("Version must be >= 1")

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_draft(self) -> bool:
        return self.status == DisposalStatus.DRAFT

    @property
    def is_approved(self) -> bool:
        return self.status == DisposalStatus.APPROVED

    @property
    def is_completed(self) -> bool:
        return self.status == DisposalStatus.COMPLETED

    @property
    def is_cancelled(self) -> bool:
        return self.status == DisposalStatus.CANCELLED

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
    def is_gain(self) -> bool:
        return self.gain_loss > 0

    @property
    def is_loss(self) -> bool:
        return self.gain_loss < 0

    @property
    def is_break_even(self) -> bool:
        return abs(self.gain_loss) <= Decimal("0.01")

    @property
    def disposal_amount_display(self) -> str:
        """Display proceeds with currency."""
        return f"{self.currency} {self.proceeds:,.2f}"

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create_sale(
        cls,
        asset: FixedAsset,
        disposal_date: date,
        proceeds: Decimal,
        created_by: UUID,
        customer_id: UUID | None = None,
        customer_name: str | None = None,
        invoice_number: str | None = None,
        reason: str = "",
        notes: str = "",
        disposal_id: UUID | None = None,
    ) -> DisposalEntity:
        """Create a sale disposal."""
        # Validate asset not already disposed
        if asset.is_disposed:
            raise AssetAlreadyDisposedError(f"Asset {asset.asset_code} is already disposed")
        _validate_disposal_date(disposal_date, asset.acquisition_date)
        normalized_proceeds = _validate_proceeds(proceeds)
        nbv = asset.net_book_value
        gain_loss = _calculate_gain_loss(normalized_proceeds, nbv)
        now = datetime.now(UTC)
        return cls(
            disposal_id=disposal_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            disposal_date=disposal_date,
            disposal_type=DisposalType.SALE,
            proceeds=normalized_proceeds,
            nbv_at_disposal=nbv,
            gain_loss=gain_loss,
            currency=asset.currency,
            status=DisposalStatus.DRAFT,
            customer_id=customer_id,
            customer_name=customer_name,
            invoice_number=invoice_number,
            reason=reason,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_scrap(
        cls,
        asset: FixedAsset,
        disposal_date: date,
        created_by: UUID,
        reason: str = "",
        notes: str = "",
        disposal_id: UUID | None = None,
    ) -> DisposalEntity:
        """Create a scrap disposal (zero proceeds)."""
        if asset.is_disposed:
            raise AssetAlreadyDisposedError(f"Asset {asset.asset_code} is already disposed")
        _validate_disposal_date(disposal_date, asset.acquisition_date)
        nbv = asset.net_book_value
        gain_loss = -nbv  # Loss equal to NBV
        now = datetime.now(UTC)
        return cls(
            disposal_id=disposal_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            disposal_date=disposal_date,
            disposal_type=DisposalType.SCRAP,
            proceeds=Decimal("0"),
            nbv_at_disposal=nbv,
            gain_loss=gain_loss,
            currency=asset.currency,
            status=DisposalStatus.DRAFT,
            reason=reason,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_donation(
        cls,
        asset: FixedAsset,
        disposal_date: date,
        created_by: UUID,
        recipient_name: str | None = None,
        reason: str = "",
        notes: str = "",
        disposal_id: UUID | None = None,
    ) -> DisposalEntity:
        """Create a donation disposal (zero proceeds)."""
        if asset.is_disposed:
            raise AssetAlreadyDisposedError(f"Asset {asset.asset_code} is already disposed")
        _validate_disposal_date(disposal_date, asset.acquisition_date)
        nbv = asset.net_book_value
        gain_loss = -nbv
        now = datetime.now(UTC)
        return cls(
            disposal_id=disposal_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            disposal_date=disposal_date,
            disposal_type=DisposalType.DONATION,
            proceeds=Decimal("0"),
            nbv_at_disposal=nbv,
            gain_loss=gain_loss,
            currency=asset.currency,
            status=DisposalStatus.DRAFT,
            customer_name=recipient_name,
            reason=reason,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_trade_in(
        cls,
        asset: FixedAsset,
        disposal_date: date,
        trade_in_value: Decimal,
        created_by: UUID,
        new_asset_id: UUID | None = None,
        reason: str = "",
        notes: str = "",
        disposal_id: UUID | None = None,
    ) -> DisposalEntity:
        """Create a trade-in disposal."""
        if asset.is_disposed:
            raise AssetAlreadyDisposedError(f"Asset {asset.asset_code} is already disposed")
        _validate_disposal_date(disposal_date, asset.acquisition_date)
        normalized_value = _validate_proceeds(trade_in_value)
        nbv = asset.net_book_value
        gain_loss = normalized_value - nbv
        now = datetime.now(UTC)
        return cls(
            disposal_id=disposal_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            disposal_date=disposal_date,
            disposal_type=DisposalType.TRADE_IN,
            proceeds=normalized_value,
            nbv_at_disposal=nbv,
            gain_loss=gain_loss,
            currency=asset.currency,
            status=DisposalStatus.DRAFT,
            reason=reason,
            notes=notes + (f" New asset ID: {new_asset_id}" if new_asset_id else ""),
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_loss(
        cls,
        asset: FixedAsset,
        disposal_date: date,
        created_by: UUID,
        reason: str = "",
        notes: str = "",
        disposal_id: UUID | None = None,
    ) -> DisposalEntity:
        """Create a loss disposal (asset lost, zero proceeds)."""
        if asset.is_disposed:
            raise AssetAlreadyDisposedError(f"Asset {asset.asset_code} is already disposed")
        _validate_disposal_date(disposal_date, asset.acquisition_date)
        nbv = asset.net_book_value
        gain_loss = -nbv
        now = datetime.now(UTC)
        return cls(
            disposal_id=disposal_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            disposal_date=disposal_date,
            disposal_type=DisposalType.LOSS,
            proceeds=Decimal("0"),
            nbv_at_disposal=nbv,
            gain_loss=gain_loss,
            currency=asset.currency,
            status=DisposalStatus.DRAFT,
            reason=reason,
            notes=notes,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_theft(
        cls,
        asset: FixedAsset,
        disposal_date: date,
        created_by: UUID,
        police_report_number: str | None = None,
        reason: str = "",
        notes: str = "",
        disposal_id: UUID | None = None,
    ) -> DisposalEntity:
        """Create a theft disposal (zero proceeds, may have insurance claim)."""
        if asset.is_disposed:
            raise AssetAlreadyDisposedError(f"Asset {asset.asset_code} is already disposed")
        _validate_disposal_date(disposal_date, asset.acquisition_date)
        nbv = asset.net_book_value
        gain_loss = -nbv
        now = datetime.now(UTC)
        notes_with_report = notes
        if police_report_number:
            notes_with_report = f"Police report: {police_report_number}\n{notes}"
        return cls(
            disposal_id=disposal_id or uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            disposal_date=disposal_date,
            disposal_type=DisposalType.THEFT,
            proceeds=Decimal("0"),
            nbv_at_disposal=nbv,
            gain_loss=gain_loss,
            currency=asset.currency,
            status=DisposalStatus.DRAFT,
            reason=reason,
            notes=notes_with_report,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DisposalEntity:
        """Reconstruct from dictionary."""
        disposal_type = DisposalType.from_string(data["disposal_type"])
        if disposal_type is None:
            raise DisposalError(f"Invalid disposal_type: {data['disposal_type']}")
        status = DisposalStatus.from_string(data["status"])
        if status is None:
            raise DisposalError(f"Invalid status: {data['status']}")

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
            disposal_id=UUID(data["disposal_id"])
            if isinstance(data["disposal_id"], str)
            else data["disposal_id"],
            asset_id=UUID(data["asset_id"])
            if isinstance(data["asset_id"], str)
            else data["asset_id"],
            asset_code=data["asset_code"],
            asset_name=data["asset_name"],
            disposal_date=parse_date("disposal_date"),
            disposal_type=disposal_type,
            proceeds=Decimal(str(data["proceeds"])),
            nbv_at_disposal=Decimal(str(data["nbv_at_disposal"])),
            gain_loss=Decimal(str(data["gain_loss"])),
            currency=data.get("currency", "IDR"),
            status=status,
            customer_id=UUID(data["customer_id"]) if data.get("customer_id") else None,
            customer_name=data.get("customer_name"),
            invoice_number=data.get("invoice_number"),
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            approved_at=parse_datetime("approved_at"),
            completed_by=UUID(data["completed_by"]) if data.get("completed_by") else None,
            completed_at=parse_datetime("completed_at"),
            cancelled_by=UUID(data["cancelled_by"]) if data.get("cancelled_by") else None,
            cancelled_at=parse_datetime("cancelled_at"),
            cancel_reason=data.get("cancel_reason", ""),
            reason=data.get("reason", ""),
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

    def approve(self, approved_by: UUID) -> DisposalEntity:
        """Approve the disposal."""
        if not self.can_approve:
            raise InvalidStatusTransitionError(
                f"Cannot approve disposal in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return DisposalEntity(
            disposal_id=self.disposal_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            disposal_date=self.disposal_date,
            disposal_type=self.disposal_type,
            proceeds=self.proceeds,
            nbv_at_disposal=self.nbv_at_disposal,
            gain_loss=self.gain_loss,
            currency=self.currency,
            status=DisposalStatus.APPROVED,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            invoice_number=self.invoice_number,
            approved_by=approved_by,
            approved_at=now,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=approved_by,
            version=self.version + 1,
        )

    def complete(self, completed_by: UUID) -> DisposalEntity:
        """Complete the disposal (asset is removed from books)."""
        if not self.can_complete:
            raise InvalidStatusTransitionError(
                f"Cannot complete disposal in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return DisposalEntity(
            disposal_id=self.disposal_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            disposal_date=self.disposal_date,
            disposal_type=self.disposal_type,
            proceeds=self.proceeds,
            nbv_at_disposal=self.nbv_at_disposal,
            gain_loss=self.gain_loss,
            currency=self.currency,
            status=DisposalStatus.COMPLETED,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            invoice_number=self.invoice_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=completed_by,
            completed_at=now,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=completed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: UUID, reason: str) -> DisposalEntity:
        """Cancel the disposal."""
        if not self.can_cancel:
            raise InvalidStatusTransitionError(
                f"Cannot cancel disposal in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return DisposalEntity(
            disposal_id=self.disposal_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            disposal_date=self.disposal_date,
            disposal_type=self.disposal_type,
            proceeds=self.proceeds,
            nbv_at_disposal=self.nbv_at_disposal,
            gain_loss=self.gain_loss,
            currency=self.currency,
            status=DisposalStatus.CANCELLED,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            invoice_number=self.invoice_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=cancelled_by,
            cancelled_at=now,
            cancel_reason=reason,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=cancelled_by,
            version=self.version + 1,
        )

    def update_reason(self, new_reason: str, updated_by: UUID) -> DisposalEntity:
        """Update reason (only allowed in DRAFT)."""
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit disposal in status {self.status.value}"
            )
        cleaned_reason = _validate_reason(new_reason)
        now = datetime.now(UTC)
        return DisposalEntity(
            disposal_id=self.disposal_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            disposal_date=self.disposal_date,
            disposal_type=self.disposal_type,
            proceeds=self.proceeds,
            nbv_at_disposal=self.nbv_at_disposal,
            gain_loss=self.gain_loss,
            currency=self.currency,
            status=self.status,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            invoice_number=self.invoice_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            reason=cleaned_reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_notes(self, new_notes: str, updated_by: UUID) -> DisposalEntity:
        """Update notes (only allowed in DRAFT)."""
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit disposal in status {self.status.value}"
            )
        now = datetime.now(UTC)
        return DisposalEntity(
            disposal_id=self.disposal_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            disposal_date=self.disposal_date,
            disposal_type=self.disposal_type,
            proceeds=self.proceeds,
            nbv_at_disposal=self.nbv_at_disposal,
            gain_loss=self.gain_loss,
            currency=self.currency,
            status=self.status,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            invoice_number=self.invoice_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            reason=self.reason,
            notes=new_notes,
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
            "disposal_id": str(self.disposal_id),
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "disposal_date": self.disposal_date.isoformat(),
            "disposal_type": self.disposal_type.value,
            "disposal_type_display": self.disposal_type.display_name(),
            "proceeds": str(self.proceeds),
            "nbv_at_disposal": str(self.nbv_at_disposal),
            "gain_loss": str(self.gain_loss),
            "is_gain": self.is_gain,
            "is_loss": self.is_loss,
            "is_break_even": self.is_break_even,
            "currency": self.currency,
            "status": self.status.value,
            "status_display": self.status.display_name(),
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "customer_name": self.customer_name,
            "invoice_number": self.invoice_number,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "completed_by": str(self.completed_by) if self.completed_by else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cancelled_by": str(self.cancelled_by) if self.cancelled_by else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "reason": self.reason,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_by": str(self.updated_by),
            "version": self.version,
            "can_approve": self.can_approve,
            "can_complete": self.can_complete,
            "can_cancel": self.can_cancel,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "disposal_id": self.disposal_id,
            "asset_id": self.asset_id,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "disposal_date": self.disposal_date,
            "disposal_type": self.disposal_type.value,
            "proceeds": self.proceeds,
            "nbv_at_disposal": self.nbv_at_disposal,
            "gain_loss": self.gain_loss,
            "currency": self.currency,
            "status": self.status.value,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "invoice_number": self.invoice_number,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "completed_by": self.completed_by,
            "completed_at": self.completed_at,
            "cancelled_by": self.cancelled_by,
            "cancelled_at": self.cancelled_at,
            "cancel_reason": self.cancel_reason,
            "reason": self.reason,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
        }

    # ==================== TAMBAHAN METHOD ENTITY DASAR UNTUK DisposalEntity ====================

    def create(self, created_by: UUID) -> DisposalEntity:
        """Record disposal creation."""
        if not hasattr(self, "_audit_trail"):
            object.__setattr__(self, "_audit_trail", [])
        entry = {
            "action": "CREATE",
            "performed_by": str(created_by),
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "disposal_id": str(self.disposal_id),
            "details": {"asset_code": self.asset_code, "disposal_type": self.disposal_type.value},
        }
        self._audit_trail.append(entry)
        return self

    def update(self, updated_by: UUID, **kwargs) -> DisposalEntity:
        """Update disposal attributes (only allowed in DRAFT)."""
        if not self.can_edit:
            raise InvalidStatusTransitionError(
                f"Cannot edit disposal in status {self.status.value}"
            )
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("disposal_id", "created_at", "created_by", "version"):
                data[key] = value
        new_disposal = self.from_dict(data)
        new_disposal._record_audit("UPDATE", str(updated_by), {"changes": kwargs})
        return new_disposal

    def delete(self, deleted_by: UUID, reason: str | None = None) -> DisposalEntity:
        """Delete disposal (cancel)."""
        return self.cancel(deleted_by, reason or "Deleted by user")

    def restore(self, restored_by: UUID) -> DisposalEntity:
        """Restore a cancelled disposal to DRAFT."""
        if self.status != DisposalStatus.CANCELLED:
            raise InvalidStatusTransitionError(
                f"Cannot restore disposal in status {self.status.value}"
            )
        now = datetime.now(UTC)
        new_disposal = DisposalEntity(
            disposal_id=self.disposal_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            disposal_date=self.disposal_date,
            disposal_type=self.disposal_type,
            proceeds=self.proceeds,
            nbv_at_disposal=self.nbv_at_disposal,
            gain_loss=self.gain_loss,
            currency=self.currency,
            status=DisposalStatus.DRAFT,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            invoice_number=self.invoice_number,
            approved_by=None,
            approved_at=None,
            completed_by=None,
            completed_at=None,
            cancelled_by=None,
            cancelled_at=None,
            cancel_reason="",
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=restored_by,
            version=self.version + 1,
        )
        new_disposal._record_audit("RESTORE", str(restored_by), {})
        return new_disposal

    def activate(self, activated_by: UUID) -> DisposalEntity:
        """Activate (approve) disposal."""
        return self.approve(activated_by)

    def deactivate(self, deactivated_by: UUID, reason: str | None = None) -> DisposalEntity:
        """Deactivate (cancel) disposal."""
        return self.cancel(deactivated_by, reason or "Deactivated by user")

    def lock(self, locked_by: UUID, reason: str) -> DisposalEntity:
        """Lock disposal (prevent modifications)."""
        now = datetime.now(UTC)
        metadata = getattr(self, "metadata", {}) or {}
        metadata["locked_by"] = str(locked_by)
        metadata["locked_at"] = now.isoformat()
        metadata["lock_reason"] = reason
        new_disposal = self._copy()
        new_disposal.metadata = metadata
        new_disposal.updated_at = now
        new_disposal.updated_by = locked_by
        new_disposal.version = self.version + 1
        new_disposal._record_audit("LOCK", str(locked_by), {"reason": reason})
        return new_disposal

    def unlock(self, unlocked_by: UUID) -> DisposalEntity:
        """Unlock disposal."""
        now = datetime.now(UTC)
        metadata = getattr(self, "metadata", {}) or {}
        metadata.pop("locked_by", None)
        metadata.pop("locked_at", None)
        metadata.pop("lock_reason", None)
        new_disposal = self._copy()
        new_disposal.metadata = metadata
        new_disposal.updated_at = now
        new_disposal.updated_by = unlocked_by
        new_disposal.version = self.version + 1
        new_disposal._record_audit("UNLOCK", str(unlocked_by), {})
        return new_disposal

    def validate(self) -> dict[str, Any]:
        """Validate disposal."""
        errors = []
        try:
            self.__post_init__()
        except DisposalError as e:
            errors.append(str(e))
        if self.disposal_date > date.today():
            errors.append(f"Disposal date {self.disposal_date} cannot be in the future")
        if self.proceeds < 0:
            errors.append(f"Proceeds cannot be negative: {self.proceeds}")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "disposal_id": str(self.disposal_id),
            "version": self.version,
        }

    def clone(self) -> DisposalEntity:
        """Clone disposal."""
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = DisposalEntity(
            disposal_id=new_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            disposal_date=self.disposal_date,
            disposal_type=self.disposal_type,
            proceeds=self.proceeds,
            nbv_at_disposal=self.nbv_at_disposal,
            gain_loss=self.gain_loss,
            currency=self.currency,
            status=DisposalStatus.DRAFT,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            invoice_number=self.invoice_number,
            reason=self.reason,
            notes=f"Cloned from {self.disposal_id}",
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            updated_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", str(self.created_by), {"source": str(self.disposal_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        """Get snapshot."""
        return {
            "version": self.version,
            "disposal_id": str(self.disposal_id),
            "asset_code": self.asset_code,
            "disposal_type": self.disposal_type.value,
            "gain_loss": str(self.gain_loss),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return getattr(self, "_audit_trail", [])[-limit:]

    def touch(self, touched_by: UUID) -> DisposalEntity:
        """Touch disposal."""
        now = datetime.now(UTC)
        new_disposal = self._copy()
        new_disposal.updated_at = now
        new_disposal.updated_by = touched_by
        new_disposal.version = self.version + 1
        new_disposal._record_audit("TOUCH", str(touched_by), {})
        return new_disposal

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        if not hasattr(self, "_audit_trail"):
            object.__setattr__(self, "_audit_trail", [])
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "disposal_id": str(self.disposal_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _copy(self) -> DisposalEntity:
        return DisposalEntity(
            disposal_id=self.disposal_id,
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            disposal_date=self.disposal_date,
            disposal_type=self.disposal_type,
            proceeds=self.proceeds,
            nbv_at_disposal=self.nbv_at_disposal,
            gain_loss=self.gain_loss,
            currency=self.currency,
            status=self.status,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            invoice_number=self.invoice_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            reason=self.reason,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            updated_by=self.updated_by,
            version=self.version,
        )

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return (
            f"Disposal({self.asset_code}, {self.disposal_type.value}: gain/loss={self.gain_loss})"
        )

    def __repr__(self) -> str:
        return f"DisposalEntity(asset={self.asset_code}, status={self.status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DisposalEntity):
            return False
        return self.disposal_id == other.disposal_id

    def __hash__(self) -> int:
        return hash(self.disposal_id)


# ============================================================================
# Type Aliases for Compatibility
# ============================================================================

AssetDisposal = DisposalEntity
Disposal = DisposalEntity  # added for repository compatibility


# ============================================================================
# Repository Protocol
# ============================================================================


class DisposalRepository:
    """Repository protocol for DisposalEntity."""

    async def get_by_id(self, disposal_id: UUID, legal_entity_id: UUID) -> DisposalEntity | None:
        raise NotImplementedError

    async def get_by_asset(self, asset_id: UUID, legal_entity_id: UUID) -> DisposalEntity | None:
        raise NotImplementedError

    async def get_by_date_range(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
    ) -> list[DisposalEntity]:
        raise NotImplementedError

    async def get_by_status(
        self,
        legal_entity_id: UUID,
        status: DisposalStatus,
    ) -> list[DisposalEntity]:
        raise NotImplementedError

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[DisposalEntity]:
        """Get all disposals pending approval (DRAFT status)."""
        return await self.get_by_status(legal_entity_id, DisposalStatus.DRAFT)

    async def save(self, disposal: DisposalEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, disposal_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_gain_loss_on_disposal(proceeds: Decimal, nbv: Decimal) -> Decimal:
    """Calculate gain (positive) or loss (negative) on disposal."""
    return proceeds - nbv


def is_disposal_allowed(asset: FixedAsset) -> tuple[bool, str]:
    """Check if an asset can be disposed."""
    if asset.is_disposed:
        return False, "Asset is already disposed"
    if asset.status == AssetStatus.UNDER_CONSTRUCTION:
        return False, "Assets under construction cannot be disposed"
    return True, ""


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AssetAlreadyDisposedError",
    "AssetDisposal",
    "Disposal",  # added for repository compatibility
    "DisposalAlreadyCompletedError",
    "DisposalEntity",
    "DisposalError",
    "DisposalRepository",
    "DisposalStatus",
    "DisposalType",
    "InvalidDisposalDateError",
    "InvalidProceedsError",
    "InvalidStatusTransitionError",
    "calculate_gain_loss_on_disposal",
    "is_disposal_allowed",
]
