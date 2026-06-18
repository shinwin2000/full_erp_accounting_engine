#!/usr/bin/env python3
"""
Module: asset_group_entity.py

Layer: Domain / Fixed Asset

Responsibility:
    Entity for asset groups (kelompok aset tetap).

    Manages grouping of fixed assets by category, department, location,
    or custom criteria for reporting, analysis, and depreciation aggregation.

Business rules:
    - Group code must be unique across legal entity.
    - Group name must be at least 2 characters.
    - Group type must be one of: category, department, location, custom.
    - Parent group (if provided) must exist.
    - No cycles allowed in group hierarchy.
    - Groups can have multiple children.
    - Soft delete via is_active flag.
    - Version increments on every change (optimistic locking).

Dependencies:
    - Python standard library (uuid, datetime, logging, re)
    - domain.fixed_asset.asset_entity (FixedAsset, AssetCategory)

Audit:
    Every state change should be logged; domain events emitted separately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from domain.fixed_asset.asset_entity import FixedAsset

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class AssetGroupType(Enum):
    """Type of asset group."""

    CATEGORY = "category"  # Group by asset category (building, machine, etc.)
    DEPARTMENT = "department"  # Group by department
    LOCATION = "location"  # Group by physical location
    CUSTOM = "custom"  # Custom grouping
    COST_CENTER = "cost_center"  # Group by cost center

    def display_name(self) -> str:
        names = {
            AssetGroupType.CATEGORY: "Kategori Aset",
            AssetGroupType.DEPARTMENT: "Departemen",
            AssetGroupType.LOCATION: "Lokasi",
            AssetGroupType.CUSTOM: "Kustom",
            AssetGroupType.COST_CENTER: "Pusat Biaya",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> AssetGroupType | None:
        for t in cls:
            if t.value == value.lower():
                return t
        return None


class AssetGroupStatus(Enum):
    """Status of asset group."""

    ACTIVE = "active"  # Active, can be used
    INACTIVE = "inactive"  # Inactive, not used
    ARCHIVED = "archived"  # Archived, read-only

    def is_usable(self) -> bool:
        return self == AssetGroupStatus.ACTIVE

    def display_name(self) -> str:
        names = {
            AssetGroupStatus.ACTIVE: "Aktif",
            AssetGroupStatus.INACTIVE: "Tidak Aktif",
            AssetGroupStatus.ARCHIVED: "Diarsipkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> AssetGroupStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class AssetGroupError(ValueError):
    """Base exception for asset group errors."""

    pass


class InvalidGroupCodeError(AssetGroupError):
    """Raised when group code format is invalid."""

    pass


class DuplicateGroupCodeError(AssetGroupError):
    """Raised when group code already exists."""

    pass


class ParentGroupNotFoundError(AssetGroupError):
    """Raised when parent group does not exist."""

    pass


class CycleDetectedError(AssetGroupError):
    """Raised when moving group would create a cycle."""

    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_group_code(code: str) -> str:
    """Validate asset group code format."""
    if not code or not isinstance(code, str):
        raise InvalidGroupCodeError("Group code must be a non-empty string")
    cleaned = code.strip()
    if len(cleaned) < 2:
        raise InvalidGroupCodeError("Group code must be at least 2 characters")
    if len(cleaned) > 30:
        raise InvalidGroupCodeError("Group code must not exceed 30 characters")
    if not re.match(r"^[A-Za-z0-9\-_/]+$", cleaned):
        raise InvalidGroupCodeError(
            "Group code can only contain letters, numbers, hyphens, underscores, and slashes"
        )
    return cleaned


def _validate_group_name(name: str) -> str:
    """Validate asset group name."""
    if not name or not isinstance(name, str):
        raise AssetGroupError("Group name must be a non-empty string")
    cleaned = name.strip()
    if len(cleaned) < 2:
        raise AssetGroupError("Group name must be at least 2 characters")
    if len(cleaned) > 100:
        raise AssetGroupError("Group name must not exceed 100 characters")
    return cleaned


def _validate_group_type(group_type: AssetGroupType) -> None:
    """Validate group type."""
    if not isinstance(group_type, AssetGroupType):
        raise AssetGroupError(f"Invalid group_type: {group_type}")


def _validate_status(status: AssetGroupStatus) -> None:
    """Validate status."""
    if not isinstance(status, AssetGroupStatus):
        raise AssetGroupError(f"Invalid status: {status}")


def _validate_description(desc: str | None) -> str | None:
    """Clean description."""
    if desc is None:
        return None
    cleaned = desc.strip()
    if len(cleaned) > 500:
        raise AssetGroupError("Description must not exceed 500 characters")
    return cleaned if cleaned else None


def _detect_cycle(
    group_id: UUID,
    new_parent_id: UUID | None,
    get_parent_func: callable,
) -> bool:
    """Detect if moving group to new_parent would create a cycle."""
    if new_parent_id is None:
        return False
    # Traverse up from new_parent
    current = new_parent_id
    visited = set()
    while current is not None and current not in visited:
        if current == group_id:
            return True
        visited.add(current)
        current = get_parent_func(current)
    return False


# ============================================================================
# Entity: AssetGroupEntity
# ============================================================================


@dataclass
class AssetGroupEntity:
    """
    Entity for asset group.

    This entity is mutable (dataclass) but changes create new instances
    with incremented version for optimistic locking.

    Attributes:
        group_id: Unique identifier
        legal_entity_id: Legal entity owning this group
        group_code: Unique group code
        group_name: Group name
        group_type: Type of group
        parent_group_id: Optional parent group ID
        description: Optional description
        status: Current status
        created_at, updated_at, created_by, updated_by, version
    """

    # ========== Mandatory Fields ==========
    group_id: UUID
    legal_entity_id: UUID
    group_code: str
    group_name: str
    group_type: AssetGroupType
    status: AssetGroupStatus

    # ========== Optional Fields ==========
    parent_group_id: UUID | None = None
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate asset group data."""
        # Validate group_code
        normalized_code = _validate_group_code(self.group_code)
        if normalized_code != self.group_code:
            object.__setattr__(self, "group_code", normalized_code)

        # Validate group_name
        normalized_name = _validate_group_name(self.group_name)
        if normalized_name != self.group_name:
            object.__setattr__(self, "group_name", normalized_name)

        # Validate group_type
        _validate_group_type(self.group_type)

        # Validate status
        _validate_status(self.status)

        # Validate description
        normalized_desc = _validate_description(self.description)
        if normalized_desc != self.description:
            object.__setattr__(self, "description", normalized_desc)

        # Validate parent_group_id not self
        if self.parent_group_id == self.group_id:
            raise AssetGroupError("Group cannot be its own parent")

        # Validate timestamps UTC
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

        # Validate version
        if self.version < 1:
            raise AssetGroupError("Version must be >= 1")

        # Validate status consistency
        if self.status == AssetGroupStatus.ARCHIVED and self.parent_group_id:
            # Archived groups cannot have parent? Not strictly enforced
            pass

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        legal_entity_id: UUID,
        group_code: str,
        group_name: str,
        group_type: AssetGroupType,
        parent_group_id: UUID | None = None,
        description: str | None = None,
        created_by: str = "system",
        group_id: UUID | None = None,
    ) -> AssetGroupEntity:
        """Create a new asset group with ACTIVE status."""
        now = datetime.now(UTC)
        return cls(
            group_id=group_id or uuid4(),
            legal_entity_id=legal_entity_id,
            group_code=group_code,
            group_name=group_name,
            group_type=group_type,
            status=AssetGroupStatus.ACTIVE,
            parent_group_id=parent_group_id,
            description=description,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
        )

    @classmethod
    def create_category_group(
        cls,
        legal_entity_id: UUID,
        group_code: str,
        group_name: str,
        parent_group_id: UUID | None = None,
        description: str | None = None,
        created_by: str = "system",
    ) -> AssetGroupEntity:
        """Create a category-based asset group."""
        return cls.create(
            legal_entity_id=legal_entity_id,
            group_code=group_code,
            group_name=group_name,
            group_type=AssetGroupType.CATEGORY,
            parent_group_id=parent_group_id,
            description=description,
            created_by=created_by,
        )

    @classmethod
    def create_department_group(
        cls,
        legal_entity_id: UUID,
        group_code: str,
        group_name: str,
        parent_group_id: UUID | None = None,
        description: str | None = None,
        created_by: str = "system",
    ) -> AssetGroupEntity:
        """Create a department-based asset group."""
        return cls.create(
            legal_entity_id=legal_entity_id,
            group_code=group_code,
            group_name=group_name,
            group_type=AssetGroupType.DEPARTMENT,
            parent_group_id=parent_group_id,
            description=description,
            created_by=created_by,
        )

    @classmethod
    def create_location_group(
        cls,
        legal_entity_id: UUID,
        group_code: str,
        group_name: str,
        parent_group_id: UUID | None = None,
        description: str | None = None,
        created_by: str = "system",
    ) -> AssetGroupEntity:
        """Create a location-based asset group."""
        return cls.create(
            legal_entity_id=legal_entity_id,
            group_code=group_code,
            group_name=group_name,
            group_type=AssetGroupType.LOCATION,
            parent_group_id=parent_group_id,
            description=description,
            created_by=created_by,
        )

    @classmethod
    def create_cost_center_group(
        cls,
        legal_entity_id: UUID,
        group_code: str,
        group_name: str,
        parent_group_id: UUID | None = None,
        description: str | None = None,
        created_by: str = "system",
    ) -> AssetGroupEntity:
        """Create a cost center-based asset group."""
        return cls.create(
            legal_entity_id=legal_entity_id,
            group_code=group_code,
            group_name=group_name,
            group_type=AssetGroupType.COST_CENTER,
            parent_group_id=parent_group_id,
            description=description,
            created_by=created_by,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetGroupEntity:
        """Reconstruct from dictionary."""
        group_type = AssetGroupType.from_string(data["group_type"])
        if group_type is None:
            raise AssetGroupError(f"Invalid group_type: {data['group_type']}")
        status = AssetGroupStatus.from_string(data.get("status", "active"))
        if status is None:
            status = AssetGroupStatus.ACTIVE

        def parse_datetime(key: str) -> datetime:
            val = data.get(key)
            if val is None:
                return datetime.now(UTC)
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return val

        return cls(
            group_id=UUID(data["group_id"])
            if isinstance(data["group_id"], str)
            else data["group_id"],
            legal_entity_id=UUID(data["legal_entity_id"])
            if isinstance(data["legal_entity_id"], str)
            else data["legal_entity_id"],
            group_code=data["group_code"],
            group_name=data["group_name"],
            group_type=group_type,
            status=status,
            parent_group_id=UUID(data["parent_group_id"]) if data.get("parent_group_id") else None,
            description=data.get("description"),
            created_at=parse_datetime("created_at"),
            updated_at=parse_datetime("updated_at"),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status == AssetGroupStatus.ACTIVE

    @property
    def is_inactive(self) -> bool:
        return self.status == AssetGroupStatus.INACTIVE

    @property
    def is_archived(self) -> bool:
        return self.status == AssetGroupStatus.ARCHIVED

    @property
    def is_root(self) -> bool:
        return self.parent_group_id is None

    @property
    def display_name(self) -> str:
        return f"{self.group_code} - {self.group_name}"

    # ------------------------------------------------------------------------
    # Business Logic (Immutable Transformations)
    # ------------------------------------------------------------------------

    def rename(self, new_name: str, updated_by: str) -> AssetGroupEntity:
        """Rename the group."""
        normalized_name = _validate_group_name(new_name)
        now = datetime.now(UTC)
        return AssetGroupEntity(
            group_id=self.group_id,
            legal_entity_id=self.legal_entity_id,
            group_code=self.group_code,
            group_name=normalized_name,
            group_type=self.group_type,
            status=self.status,
            parent_group_id=self.parent_group_id,
            description=self.description,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_description(self, new_description: str | None, updated_by: str) -> AssetGroupEntity:
        """Update group description."""
        normalized_desc = _validate_description(new_description)
        now = datetime.now(UTC)
        return AssetGroupEntity(
            group_id=self.group_id,
            legal_entity_id=self.legal_entity_id,
            group_code=self.group_code,
            group_name=self.group_name,
            group_type=self.group_type,
            status=self.status,
            parent_group_id=self.parent_group_id,
            description=normalized_desc,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def change_parent(
        self, new_parent_id: UUID | None, updated_by: str, get_parent_func: callable | None = None
    ) -> AssetGroupEntity:
        """Change parent group (validates no cycle)."""
        if new_parent_id == self.group_id:
            raise AssetGroupError("Group cannot be its own parent")
        if get_parent_func and _detect_cycle(self.group_id, new_parent_id, get_parent_func):
            raise CycleDetectedError("Changing parent would create a cycle in group hierarchy")
        now = datetime.now(UTC)
        return AssetGroupEntity(
            group_id=self.group_id,
            legal_entity_id=self.legal_entity_id,
            group_code=self.group_code,
            group_name=self.group_name,
            group_type=self.group_type,
            status=self.status,
            parent_group_id=new_parent_id,
            description=self.description,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def activate(self, updated_by: str) -> AssetGroupEntity:
        """Activate the group."""
        if self.status == AssetGroupStatus.ACTIVE:
            return self
        now = datetime.now(UTC)
        return AssetGroupEntity(
            group_id=self.group_id,
            legal_entity_id=self.legal_entity_id,
            group_code=self.group_code,
            group_name=self.group_name,
            group_type=self.group_type,
            status=AssetGroupStatus.ACTIVE,
            parent_group_id=self.parent_group_id,
            description=self.description,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def deactivate(self, updated_by: str) -> AssetGroupEntity:
        """Deactivate the group."""
        if self.status == AssetGroupStatus.INACTIVE:
            return self
        if self.status == AssetGroupStatus.ARCHIVED:
            raise AssetGroupError("Cannot deactivate an archived group")
        now = datetime.now(UTC)
        return AssetGroupEntity(
            group_id=self.group_id,
            legal_entity_id=self.legal_entity_id,
            group_code=self.group_code,
            group_name=self.group_name,
            group_type=self.group_type,
            status=AssetGroupStatus.INACTIVE,
            parent_group_id=self.parent_group_id,
            description=self.description,
            created_at=self.created_at,
            updated_at=now,
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def archive(self, updated_by: str) -> AssetGroupEntity:
        """Archive the group."""
        if self.status == AssetGroupStatus.ARCHIVED:
            return self
        now = datetime.now(UTC)
        return AssetGroupEntity(
            group_id=self.group_id,
            legal_entity_id=self.legal_entity_id,
            group_code=self.group_code,
            group_name=self.group_name,
            group_type=self.group_type,
            status=AssetGroupStatus.ARCHIVED,
            parent_group_id=self.parent_group_id,
            description=self.description,
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
            "group_id": str(self.group_id),
            "legal_entity_id": str(self.legal_entity_id),
            "group_code": self.group_code,
            "group_name": self.group_name,
            "group_type": self.group_type.value,
            "group_type_display": self.group_type.display_name(),
            "status": self.status.value,
            "status_display": self.status.display_name(),
            "parent_group_id": str(self.parent_group_id) if self.parent_group_id else None,
            "description": self.description,
            "is_root": self.is_root,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "group_id": self.group_id,
            "legal_entity_id": self.legal_entity_id,
            "group_code": self.group_code,
            "group_name": self.group_name,
            "group_type": self.group_type.value,
            "status": self.status.value,
            "parent_group_id": self.parent_group_id,
            "description": self.description,
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
        return self.display_name

    def __repr__(self) -> str:
        return f"AssetGroupEntity({self.group_code}, type={self.group_type.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AssetGroupEntity):
            return False
        return self.group_id == other.group_id

    def __hash__(self) -> int:
        return hash(self.group_id)


# ============================================================================
# Value Object: AssetGroupSummary
# ============================================================================


@dataclass(frozen=True)
class AssetGroupSummary:
    """
    Immutable summary of assets in a group.

    Attributes:
        group_id: Group identifier
        group_code: Group code
        group_name: Group name
        asset_count: Number of assets in group
        total_cost: Sum of acquisition costs
        total_accumulated_depreciation: Sum of accumulated depreciation
        total_nbv: Sum of net book values
        currency: Currency code
        asset_type_breakdown: Optional breakdown by asset type
        status_breakdown: Optional breakdown by asset status
    """

    group_id: UUID
    group_code: str
    group_name: str
    asset_count: int
    total_cost: Decimal
    total_accumulated_depreciation: Decimal
    total_nbv: Decimal
    currency: str = "IDR"
    asset_type_breakdown: dict[str, int] | None = None
    status_breakdown: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.total_cost < 0:
            raise ValueError("Total cost cannot be negative")
        if self.total_accumulated_depreciation < 0:
            raise ValueError("Total accumulated depreciation cannot be negative")
        if self.total_nbv < 0:
            raise ValueError("Total NBV cannot be negative")
        if self.asset_count < 0:
            raise ValueError("Asset count cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": str(self.group_id),
            "group_code": self.group_code,
            "group_name": self.group_name,
            "asset_count": self.asset_count,
            "total_cost": str(self.total_cost),
            "total_accumulated_depreciation": str(self.total_accumulated_depreciation),
            "total_nbv": str(self.total_nbv),
            "currency": self.currency,
            "asset_type_breakdown": self.asset_type_breakdown,
            "status_breakdown": self.status_breakdown,
        }

    @classmethod
    def empty(
        cls, group_id: UUID, group_code: str, group_name: str, currency: str = "IDR"
    ) -> AssetGroupSummary:
        """Create an empty summary for a group with no assets."""
        return cls(
            group_id=group_id,
            group_code=group_code,
            group_name=group_name,
            asset_count=0,
            total_cost=Decimal("0"),
            total_accumulated_depreciation=Decimal("0"),
            total_nbv=Decimal("0"),
            currency=currency,
        )

    @classmethod
    def from_assets(
        cls,
        group_id: UUID,
        group_code: str,
        group_name: str,
        assets: list[FixedAsset],
        currency: str = "IDR",
    ) -> AssetGroupSummary:
        """Calculate summary from a list of assets."""
        count = len(assets)
        total_cost = sum(a.acquisition_cost for a in assets)
        total_dep = sum(a.accumulated_depreciation for a in assets)
        total_nbv = sum(a.net_book_value for a in assets)

        # Optional breakdowns
        type_breakdown = {}
        status_breakdown = {}
        for a in assets:
            type_key = a.asset_type.value
            type_breakdown[type_key] = type_breakdown.get(type_key, 0) + 1
            status_key = a.status.value
            status_breakdown[status_key] = status_breakdown.get(status_key, 0) + 1

        return cls(
            group_id=group_id,
            group_code=group_code,
            group_name=group_name,
            asset_count=count,
            total_cost=total_cost,
            total_accumulated_depreciation=total_dep,
            total_nbv=total_nbv,
            currency=currency,
            asset_type_breakdown=type_breakdown,
            status_breakdown=status_breakdown,
        )


# ============================================================================
# Service Layer (Domain Service for Group Operations)
# ============================================================================


class AssetGroupService:
    """
    Domain service for asset group operations.

    Handles business logic that spans multiple groups or requires
    interaction with assets.
    """

    def __init__(self, group_repository: AssetGroupRepository):
        self._group_repo = group_repository

    async def create_group(
        self,
        legal_entity_id: UUID,
        group_code: str,
        group_name: str,
        group_type: AssetGroupType,
        created_by: str,
        parent_group_id: UUID | None = None,
        description: str = "",
    ) -> AssetGroupEntity:
        """Create a new asset group with uniqueness validation."""
        # Check code uniqueness
        existing = await self._group_repo.get_by_code(group_code, legal_entity_id)
        if existing:
            raise DuplicateGroupCodeError(f"Group code '{group_code}' already exists")
        # Check parent exists
        if parent_group_id:
            parent = await self._group_repo.get_by_id(parent_group_id, legal_entity_id)
            if not parent:
                raise ParentGroupNotFoundError(f"Parent group {parent_group_id} not found")
        return AssetGroupEntity.create(
            legal_entity_id=legal_entity_id,
            group_code=group_code,
            group_name=group_name,
            group_type=group_type,
            parent_group_id=parent_group_id,
            description=description,
            created_by=created_by,
        )

    async def get_group_summary(
        self,
        group_id: UUID,
        legal_entity_id: UUID,
        assets: list[FixedAsset],
    ) -> AssetGroupSummary:
        """Calculate summary for a group."""
        group = await self._group_repo.get_by_id(group_id, legal_entity_id)
        group_code = group.group_code if group else ""
        group_name = group.group_name if group else ""
        # Filter assets belonging to this group (by category or other criteria)
        # For simplicity, group_id may match category or location.
        # In real implementation, assets have a group_id field.
        # Here we assume assets have a 'category' field that matches group_code
        group_assets = [a for a in assets if getattr(a, "category", None) == group_code]
        return AssetGroupSummary.from_assets(
            group_id=group_id,
            group_code=group_code,
            group_name=group_name,
            assets=group_assets,
        )

    async def get_hierarchy(
        self,
        legal_entity_id: UUID,
        root_group_id: UUID | None = None,
    ) -> list[AssetGroupEntity]:
        """Get hierarchical list of groups."""
        if root_group_id:
            groups = [await self._group_repo.get_by_id(root_group_id, legal_entity_id)]
            if not groups[0]:
                return []
        else:
            groups = await self._group_repo.get_root_groups(legal_entity_id)
        return groups


# ============================================================================
# Repository Protocol
# ============================================================================


class AssetGroupRepository:
    """Repository protocol for AssetGroupEntity."""

    async def get_by_id(self, group_id: UUID, legal_entity_id: UUID) -> AssetGroupEntity | None:
        raise NotImplementedError

    async def get_by_code(self, group_code: str, legal_entity_id: UUID) -> AssetGroupEntity | None:
        raise NotImplementedError

    async def get_by_type(
        self,
        group_type: AssetGroupType,
        legal_entity_id: UUID,
    ) -> list[AssetGroupEntity]:
        raise NotImplementedError

    async def get_children(
        self,
        parent_group_id: UUID,
        legal_entity_id: UUID,
    ) -> list[AssetGroupEntity]:
        raise NotImplementedError

    async def get_root_groups(self, legal_entity_id: UUID) -> list[AssetGroupEntity]:
        """Get all groups with no parent."""
        raise NotImplementedError

    async def get_active_groups(self, legal_entity_id: UUID) -> list[AssetGroupEntity]:
        """Get all active groups."""
        raise NotImplementedError

    async def save(self, group: AssetGroupEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, group_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Type Alias for Compatibility
# ============================================================================

AssetGroup = AssetGroupEntity


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AssetGroup",
    "AssetGroupEntity",
    "AssetGroupError",
    "AssetGroupRepository",
    "AssetGroupService",
    "AssetGroupStatus",
    "AssetGroupSummary",
    "AssetGroupType",
    "CycleDetectedError",
    "DuplicateGroupCodeError",
    "InvalidGroupCodeError",
    "ParentGroupNotFoundError",
]
