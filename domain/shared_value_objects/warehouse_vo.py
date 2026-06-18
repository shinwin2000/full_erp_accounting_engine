#!/usr/bin/env python3
"""
Module: warehouse_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for warehouse/storage location. Immutable.
    Represents a physical or logical warehouse where inventory is stored.
    Includes code, name, location, address, contact info, manager, and status.
    Also provides a simple wrapper `WarehouseCode` for type-safe references.

Business rules:
    - Warehouse code must be unique (enforced by repository).
    - Code must be 2-20 characters, alphanumeric plus underscore and hyphen.
    - Name must be at least 2 characters, max 100.
    - Optional fields: location, address, phone, manager_name.
    - Only active warehouses can be used in inventory transactions.
    - Immutable: changes create new instances.
    - WarehouseCode is a separate value object for referencing warehouse by code.

Dependencies:
    - Python standard library (dataclass, re, typing)

Audit:
    Pure value object; no I/O. Caller may log warehouse changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ============================================================================
# Custom Exceptions
# ============================================================================


class WarehouseError(ValueError):
    """Base exception for warehouse validation errors."""

    pass


class InvalidWarehouseCodeError(WarehouseError):
    """Raised when warehouse code format is invalid."""

    pass


class InvalidWarehouseNameError(WarehouseError):
    """Raised when warehouse name format is invalid."""

    pass


# ============================================================================
# Value Object: WarehouseVO
# ============================================================================


@dataclass(frozen=True)
class WarehouseVO:
    """
    Immutable value object representing a warehouse/storage location.

    Attributes:
        code: Unique warehouse code (e.g., 'WH01', 'JKT-MAIN', 'SGP')
        name: Warehouse name (e.g., 'Jakarta Main Warehouse')
        location: General location description (city/region)
        address: Full street address
        phone: Contact phone number
        manager_name: Name of warehouse manager
        is_active: Whether this warehouse is active for transactions
        metadata: Optional additional key-value pairs

    Examples:
        >>> wh = WarehouseVO.create('WH01', 'Jakarta Main Warehouse')
        >>> wh.is_active
        True
        >>> wh.deactivate()
        WarehouseVO('WH01', 'Jakarta Main Warehouse', active=False)
        >>> wh.to_dict()
        {'code': 'WH01', 'name': 'Jakarta Main Warehouse', ...}
    """

    code: str
    name: str
    location: str | None = None
    address: str | None = None
    phone: str | None = None
    manager_name: str | None = None
    is_active: bool = True
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate and normalize warehouse data."""
        # Validate code
        code_clean = self._validate_code(self.code)
        object.__setattr__(self, "code", code_clean)

        # Validate name
        name_clean = self._validate_name(self.name)
        object.__setattr__(self, "name", name_clean)

        # Validate optional fields
        if self.location is not None:
            loc_clean = self.location.strip()
            if len(loc_clean) > 100:
                raise WarehouseError("Location must not exceed 100 characters")
            object.__setattr__(self, "location", loc_clean if loc_clean else None)

        if self.address is not None:
            addr_clean = self.address.strip()
            if len(addr_clean) > 500:
                raise WarehouseError("Address must not exceed 500 characters")
            object.__setattr__(self, "address", addr_clean if addr_clean else None)

        if self.phone is not None:
            phone_clean = self.phone.strip()
            if len(phone_clean) > 30:
                raise WarehouseError("Phone number must not exceed 30 characters")
            object.__setattr__(self, "phone", phone_clean if phone_clean else None)

        if self.manager_name is not None:
            mgr_clean = self.manager_name.strip()
            if len(mgr_clean) > 100:
                raise WarehouseError("Manager name must not exceed 100 characters")
            object.__setattr__(self, "manager_name", mgr_clean if mgr_clean else None)

        # Validate metadata
        if self.metadata is not None and not isinstance(self.metadata, dict):
            raise WarehouseError("Metadata must be a dictionary or None")

    @classmethod
    def _validate_code(cls, code: str) -> str:
        """Validate warehouse code format."""
        if not code or not isinstance(code, str):
            raise InvalidWarehouseCodeError("Warehouse code must be a non-empty string")
        cleaned = code.strip()
        if len(cleaned) < 2:
            raise InvalidWarehouseCodeError("Warehouse code must be at least 2 characters")
        if len(cleaned) > 20:
            raise InvalidWarehouseCodeError("Warehouse code must not exceed 20 characters")
        if not re.match(r"^[A-Za-z0-9_-]+$", cleaned):
            raise InvalidWarehouseCodeError(
                "Warehouse code can only contain letters, numbers, hyphens, and underscores"
            )
        return cleaned

    @classmethod
    def _validate_name(cls, name: str) -> str:
        """Validate warehouse name."""
        if not name or not isinstance(name, str):
            raise InvalidWarehouseNameError("Warehouse name must be a non-empty string")
        cleaned = name.strip()
        if len(cleaned) < 2:
            raise InvalidWarehouseNameError("Warehouse name must be at least 2 characters")
        if len(cleaned) > 100:
            raise InvalidWarehouseNameError("Warehouse name must not exceed 100 characters")
        return cleaned

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        code: str,
        name: str,
        location: str | None = None,
        address: str | None = None,
        phone: str | None = None,
        manager_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WarehouseVO:
        """Create a new active warehouse."""
        return cls(
            code=code,
            name=name,
            location=location,
            address=address,
            phone=phone,
            manager_name=manager_name,
            is_active=True,
            metadata=metadata,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WarehouseVO:
        """Reconstruct from dictionary (e.g., from JSON)."""
        return cls(
            code=data["code"],
            name=data["name"],
            location=data.get("location"),
            address=data.get("address"),
            phone=data.get("phone"),
            manager_name=data.get("manager_name"),
            is_active=data.get("is_active", True),
            metadata=data.get("metadata"),
        )

    @classmethod
    def from_db_record(cls, record: dict[str, Any]) -> WarehouseVO:
        """Reconstruct from database record."""
        return cls(
            code=record["code"],
            name=record["name"],
            location=record.get("location"),
            address=record.get("address"),
            phone=record.get("phone"),
            manager_name=record.get("manager_name"),
            is_active=record.get("is_active", True),
            metadata=record.get("metadata"),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Return formatted display name (code - name)."""
        return f"{self.code} - {self.name}"

    @property
    def has_contact(self) -> bool:
        """Check if warehouse has contact information."""
        return self.phone is not None or self.manager_name is not None

    # ------------------------------------------------------------------------
    # Business logic (immutable transformations)
    # ------------------------------------------------------------------------

    def deactivate(self) -> WarehouseVO:
        """Return a new warehouse with is_active=False."""
        if not self.is_active:
            return self
        return WarehouseVO(
            code=self.code,
            name=self.name,
            location=self.location,
            address=self.address,
            phone=self.phone,
            manager_name=self.manager_name,
            is_active=False,
            metadata=self.metadata,
        )

    def activate(self) -> WarehouseVO:
        """Return a new warehouse with is_active=True."""
        if self.is_active:
            return self
        return WarehouseVO(
            code=self.code,
            name=self.name,
            location=self.location,
            address=self.address,
            phone=self.phone,
            manager_name=self.manager_name,
            is_active=True,
            metadata=self.metadata,
        )

    def rename(self, new_name: str) -> WarehouseVO:
        """Return a new warehouse with updated name."""
        return WarehouseVO(
            code=self.code,
            name=new_name,
            location=self.location,
            address=self.address,
            phone=self.phone,
            manager_name=self.manager_name,
            is_active=self.is_active,
            metadata=self.metadata,
        )

    def relocate(self, new_location: str | None) -> WarehouseVO:
        """Return a new warehouse with updated location."""
        return WarehouseVO(
            code=self.code,
            name=self.name,
            location=new_location,
            address=self.address,
            phone=self.phone,
            manager_name=self.manager_name,
            is_active=self.is_active,
            metadata=self.metadata,
        )

    def update_address(self, new_address: str | None) -> WarehouseVO:
        """Return a new warehouse with updated address."""
        return WarehouseVO(
            code=self.code,
            name=self.name,
            location=self.location,
            address=new_address,
            phone=self.phone,
            manager_name=self.manager_name,
            is_active=self.is_active,
            metadata=self.metadata,
        )

    def update_contact(self, phone: str | None, manager_name: str | None) -> WarehouseVO:
        """Return a new warehouse with updated contact information."""
        return WarehouseVO(
            code=self.code,
            name=self.name,
            location=self.location,
            address=self.address,
            phone=phone,
            manager_name=manager_name,
            is_active=self.is_active,
            metadata=self.metadata,
        )

    def with_metadata(self, metadata: dict[str, Any] | None) -> WarehouseVO:
        """Return a new warehouse with updated metadata."""
        return WarehouseVO(
            code=self.code,
            name=self.name,
            location=self.location,
            address=self.address,
            phone=self.phone,
            manager_name=self.manager_name,
            is_active=self.is_active,
            metadata=metadata,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self, include_metadata: bool = True) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "code": self.code,
            "name": self.name,
            "display_name": self.display_name,
            "location": self.location,
            "address": self.address,
            "phone": self.phone,
            "manager_name": self.manager_name,
            "is_active": self.is_active,
            "has_contact": self.has_contact,
        }
        if include_metadata and self.metadata:
            result["metadata"] = self.metadata
        return result

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "code": self.code,
            "name": self.name,
            "location": self.location,
            "address": self.address,
            "phone": self.phone,
            "manager_name": self.manager_name,
            "is_active": self.is_active,
            "metadata": self.metadata,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.display_name

    def __repr__(self) -> str:
        return f"WarehouseVO('{self.code}', '{self.name}', active={self.is_active})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WarehouseVO):
            return False
        return self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)

    def __lt__(self, other: WarehouseVO) -> bool:
        """Order by code."""
        return self.code < other.code


# ============================================================================
# Value Object: WarehouseCode (Simple Wrapper)
# ============================================================================


@dataclass(frozen=True)
class WarehouseCode:
    """
    Simple immutable wrapper for warehouse code used as a reference.
    Provides type safety and validation.

    Attributes:
        value: Warehouse code string

    Examples:
        >>> code = WarehouseCode("WH01")
        >>> str(code)
        'WH01'
        >>> code.to_dict()
        {'warehouse_code': 'WH01'}
    """

    value: str

    def __post_init__(self) -> None:
        """Validate warehouse code."""
        if not self.value or not isinstance(self.value, str):
            raise InvalidWarehouseCodeError("Warehouse code must be a non-empty string")
        cleaned = self.value.strip()
        if len(cleaned) < 2:
            raise InvalidWarehouseCodeError("Warehouse code must be at least 2 characters")
        if len(cleaned) > 20:
            raise InvalidWarehouseCodeError("Warehouse code must not exceed 20 characters")
        if not re.match(r"^[A-Za-z0-9_-]+$", cleaned):
            raise InvalidWarehouseCodeError(
                "Warehouse code can only contain letters, numbers, hyphens, and underscores"
            )
        object.__setattr__(self, "value", cleaned)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"WarehouseCode('{self.value}')"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WarehouseCode):
            return False
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

    def to_dict(self) -> dict[str, str]:
        """Convert to dict."""
        return {"warehouse_code": self.value}

    @classmethod
    def from_string(cls, code: str) -> WarehouseCode:
        """Factory method from string."""
        return cls(code)


# ============================================================================
# Type alias for compatibility
# ============================================================================

WarehouseCodeVO = WarehouseCode


# ============================================================================
# Helper Functions
# ============================================================================


def filter_active_warehouses(warehouses: list[WarehouseVO]) -> list[WarehouseVO]:
    """Return only active warehouses."""
    return [w for w in warehouses if w.is_active]


def find_warehouse_by_code(warehouses: list[WarehouseVO], code: str) -> WarehouseVO | None:
    """Find warehouse by code in a list."""
    for w in warehouses:
        if w.code == code:
            return w
    return None


def warehouse_code_list(warehouses: list[WarehouseVO]) -> list[str]:
    """Extract list of warehouse codes."""
    return [w.code for w in warehouses]


def validate_warehouse_code_unique(code: str, existing_codes: list[str]) -> bool:
    """Helper to check code uniqueness (for service layer)."""
    return code not in existing_codes


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "InvalidWarehouseCodeError",
    "InvalidWarehouseNameError",
    "WarehouseCode",
    "WarehouseCodeVO",
    "WarehouseError",
    "WarehouseVO",
    "filter_active_warehouses",
    "find_warehouse_by_code",
    "validate_warehouse_code_unique",
    "warehouse_code_list",
]
