#!/usr/bin/env python3
"""
Module: cost_center_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for cost center. Immutable.
    Represents a cost center with hierarchical structure, active status,
    and full path resolution. Used for cost allocation and reporting.

Business rules:
    - Code must be unique across the legal entity (enforced by repository).
    - Code must be 2-20 characters, alphanumeric plus dot, underscore, hyphen.
    - Parent code must exist (validated by service layer).
    - Only active cost centers can be used in transactions.
    - Hierarchical path format: parent/code (e.g., "1000/1010").
    - Level is automatically derived from parent (0 for root).
    - Immutable: changes create new instances.

Dependencies:
    - Python standard library (dataclass, re, typing)

Audit:
    Each creation/modification may be logged by caller. This value object
    is pure and does not perform I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ============================================================================
# Custom Exceptions
# ============================================================================


class CostCenterError(ValueError):
    """Base exception for cost center validation errors."""

    pass


class InvalidCostCenterCodeError(CostCenterError):
    """Raised when cost center code format is invalid."""

    pass


# ============================================================================
# Value Object: CostCenterVO
# ============================================================================


@dataclass(frozen=True)
class CostCenterVO:
    """
    Immutable value object representing a cost center.

    Attributes:
        code: Unique identifier (e.g., "1000", "IT-DEV", "FIN.001")
        name: Descriptive name (e.g., "Information Technology")
        description: Optional longer description
        parent_code: Code of parent cost center (None for root)
        is_active: Whether this cost center can be used
        level: Hierarchical depth (0 for root, 1 for child, etc.)
        full_path: Cached full path (calculated on creation)

    Examples:
        >>> root = CostCenterVO.create_root("1000", "Corporate")
        >>> child = CostCenterVO.create_child("1010", "IT Department", "1000")
        >>> child.full_path
        '1000/1010'
        >>> child.level
        1
        >>> child.deactivate()
        CostCenterVO(1010, ... is_active=False)
    """

    code: str
    name: str
    description: str | None = None
    parent_code: str | None = None
    is_active: bool = True
    level: int = 0
    _full_path: str = ""  # Internal cache, not part of equality

    def __post_init__(self) -> None:
        """Validate and normalize cost center data."""
        # Validate code
        code_clean = self._validate_code(self.code)
        object.__setattr__(self, "code", code_clean)

        # Validate name
        if not self.name or not isinstance(self.name, str):
            raise CostCenterError("Cost center name must be a non-empty string")
        name_clean = self.name.strip()
        if len(name_clean) < 2:
            raise CostCenterError("Cost center name must be at least 2 characters")
        if len(name_clean) > 100:
            raise CostCenterError("Cost center name must not exceed 100 characters")
        object.__setattr__(self, "name", name_clean)

        # Validate description if present
        if self.description is not None:
            desc_clean = self.description.strip()
            if len(desc_clean) > 500:
                raise CostCenterError("Description must not exceed 500 characters")
            object.__setattr__(self, "description", desc_clean if desc_clean else None)

        # Validate parent_code if present
        if self.parent_code is not None:
            parent_clean = self._validate_code(self.parent_code)
            if parent_clean == self.code:
                raise CostCenterError("Cost center cannot be its own parent")
            object.__setattr__(self, "parent_code", parent_clean)
        else:
            object.__setattr__(self, "parent_code", None)

        # Validate level
        if self.level < 0:
            raise CostCenterError("Level cannot be negative")
        if self.level > 20:
            raise CostCenterError("Level exceeds maximum depth of 20")

        # Compute and cache full path
        path = self._compute_full_path()
        object.__setattr__(self, "_full_path", path)

    @classmethod
    def _validate_code(cls, code: str) -> str:
        """Validate cost center code format."""
        if not code or not isinstance(code, str):
            raise InvalidCostCenterCodeError("Cost center code must be a non-empty string")
        cleaned = code.strip()
        if len(cleaned) < 2:
            raise InvalidCostCenterCodeError("Cost center code must be at least 2 characters")
        if len(cleaned) > 20:
            raise InvalidCostCenterCodeError("Cost center code must not exceed 20 characters")
        # Allowed: alphanumeric, dot, underscore, hyphen
        if not re.match(r"^[A-Za-z0-9._-]+$", cleaned):
            raise InvalidCostCenterCodeError(
                "Cost center code can only contain letters, numbers, dots, underscores, and hyphens"
            )
        return cleaned

    def _compute_full_path(self) -> str:
        """Compute hierarchical path (parent/code)."""
        if self.parent_code:
            return f"{self.parent_code}/{self.code}"
        return self.code

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def create_root(cls, code: str, name: str, description: str | None = None) -> CostCenterVO:
        """Create a root cost center (no parent)."""
        return cls(
            code=code,
            name=name,
            description=description,
            parent_code=None,
            is_active=True,
            level=0,
        )

    @classmethod
    def create_child(
        cls, code: str, name: str, parent_code: str, description: str | None = None, level: int = 1
    ) -> CostCenterVO:
        """Create a child cost center under a parent."""
        return cls(
            code=code,
            name=name,
            description=description,
            parent_code=parent_code,
            is_active=True,
            level=level,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostCenterVO:
        """Reconstruct from dictionary (e.g., from JSON)."""
        return cls(
            code=data["code"],
            name=data["name"],
            description=data.get("description"),
            parent_code=data.get("parent_code"),
            is_active=data.get("is_active", True),
            level=data.get("level", 0),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def full_path(self) -> str:
        """Return hierarchical path (e.g., '1000/1010')."""
        return self._full_path

    @property
    def is_root(self) -> bool:
        """True if this cost center has no parent."""
        return self.parent_code is None

    @property
    def is_leaf(self) -> bool:
        """
        Indicates if this cost center can have children.
        In this value object, we don't know children; this property
        is informational and always returns False unless overridden.
        For actual hierarchy, use repository to check children.
        """
        return True  # Leaf by default; real check requires database

    # ------------------------------------------------------------------------
    # Business logic (immutable transformations)
    # ------------------------------------------------------------------------

    def deactivate(self) -> CostCenterVO:
        """Return a new cost center with is_active=False."""
        if not self.is_active:
            return self
        return CostCenterVO(
            code=self.code,
            name=self.name,
            description=self.description,
            parent_code=self.parent_code,
            is_active=False,
            level=self.level,
        )

    def activate(self) -> CostCenterVO:
        """Return a new cost center with is_active=True."""
        if self.is_active:
            return self
        return CostCenterVO(
            code=self.code,
            name=self.name,
            description=self.description,
            parent_code=self.parent_code,
            is_active=True,
            level=self.level,
        )

    def rename(self, new_name: str) -> CostCenterVO:
        """Return a new cost center with updated name."""
        return CostCenterVO(
            code=self.code,
            name=new_name,
            description=self.description,
            parent_code=self.parent_code,
            is_active=self.is_active,
            level=self.level,
        )

    def change_description(self, new_description: str | None) -> CostCenterVO:
        """Return a new cost center with updated description."""
        return CostCenterVO(
            code=self.code,
            name=self.name,
            description=new_description,
            parent_code=self.parent_code,
            is_active=self.is_active,
            level=self.level,
        )

    def reparent(self, new_parent_code: str | None, new_level: int) -> CostCenterVO:
        """
        Change the parent of this cost center.
        Note: new_level must be computed by the caller based on parent's level.
        """
        if new_parent_code == self.code:
            raise CostCenterError("Cost center cannot be its own parent")
        return CostCenterVO(
            code=self.code,
            name=self.name,
            description=self.description,
            parent_code=new_parent_code,
            is_active=self.is_active,
            level=new_level,
        )

    def is_descendant_of(self, ancestor_code: str) -> bool:
        """
        Check if this cost center is a descendant of the given ancestor.
        This is a simple check based on path prefix; for deep validation,
        the caller should load the full hierarchy.
        """
        if not ancestor_code:
            return False
        # Check if full_path starts with ancestor_code/
        return self.full_path.startswith(f"{ancestor_code}/") or self.full_path == ancestor_code

    def matches_code_pattern(self, pattern: str) -> bool:
        """
        Check if code matches a glob-like pattern (e.g., "10*", "FIN??").
        Supports * (any sequence) and ? (single character).
        """
        regex_pattern = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
        return re.fullmatch(regex_pattern, self.code) is not None

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "parent_code": self.parent_code,
            "is_active": self.is_active,
            "level": self.level,
            "full_path": self.full_path,
            "is_root": self.is_root,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to format suitable for database insertion/update."""
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "parent_code": self.parent_code,
            "is_active": self.is_active,
            "level": self.level,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    def __repr__(self) -> str:
        return f"CostCenterVO('{self.code}', '{self.name}', active={self.is_active})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CostCenterVO):
            return False
        return self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)

    def __lt__(self, other: CostCenterVO) -> bool:
        """Order by code."""
        return self.code < other.code


# ============================================================================
# Helper Functions
# ============================================================================


def build_cost_center_hierarchy(cost_centers: list[CostCenterVO]) -> dict[str, list[CostCenterVO]]:
    """
    Build a hierarchy mapping from parent_code to list of children.
    Returns a dictionary where keys are parent codes (None for roots) and values are lists.
    """
    hierarchy: dict[str | None, list[CostCenterVO]] = {}
    for cc in cost_centers:
        parent = cc.parent_code
        if parent not in hierarchy:
            hierarchy[parent] = []
        hierarchy[parent].append(cc)
    # Sort children by code for consistency
    for parent in hierarchy:
        hierarchy[parent].sort()
    return hierarchy


def flatten_hierarchy(cost_centers: list[CostCenterVO]) -> list[str]:
    """Return sorted list of full paths for all cost centers."""
    return sorted([cc.full_path for cc in cost_centers])


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CostCenterError",
    "CostCenterVO",
    "InvalidCostCenterCodeError",
    "build_cost_center_hierarchy",
    "flatten_hierarchy",
]
