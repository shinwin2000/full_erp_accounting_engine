#!/usr/bin/env python3
"""
Module: department_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for organizational department. Immutable.
    Represents a department with code, name, cost center association,
    manager, and active status. Used for reporting, cost allocation,
    and organizational structure.

Business rules:
    - Code must be unique across the legal entity (enforced by repository).
    - Code must be 2-20 characters, alphanumeric plus underscore and hyphen.
    - Department can be associated with at most one cost center.
    - Only active departments can be used in transactions.
    - Department names must be unique per legal entity (optional, enforced by service).
    - Immutable: changes create new instances.

Dependencies:
    - Python standard library (dataclass, re, typing)

Audit:
    Pure value object; no I/O. Caller may log changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ============================================================================
# Custom Exceptions
# ============================================================================


class DepartmentError(ValueError):
    """Base exception for department validation errors."""

    pass


class InvalidDepartmentCodeError(DepartmentError):
    """Raised when department code format is invalid."""

    pass


class InvalidDepartmentNameError(DepartmentError):
    """Raised when department name format is invalid."""

    pass


# ============================================================================
# Value Object: DepartmentVO
# ============================================================================


@dataclass(frozen=True)
class DepartmentVO:
    """
    Immutable value object representing an organizational department.

    Attributes:
        code: Unique department code (e.g., 'FIN', 'IT-DEV', 'HR_REC')
        name: Full department name (e.g., 'Finance & Accounting')
        description: Optional longer description
        cost_center_code: Associated cost center code (optional, many-to-one)
        manager_name: Name of department manager
        manager_email: Optional email of manager
        is_active: Whether the department is active
        level: Organizational level (0 = top-level, 1 = sub-department, etc.)

    Examples:
        >>> fin = DepartmentVO.create_root('FIN', 'Finance')
        >>> fin.to_dict()
        {'code': 'FIN', 'name': 'Finance', 'is_active': True}
        >>> fin.deactivate()
        DepartmentVO('FIN', 'Finance', active=False)
    """

    code: str
    name: str
    description: str | None = None
    cost_center_code: str | None = None
    manager_name: str | None = None
    manager_email: str | None = None
    is_active: bool = True
    level: int = 0
    _full_path: str = ""  # Internal cache (parent info not stored here)

    def __post_init__(self) -> None:
        """Validate and normalize department data."""
        # Validate code
        code_clean = self._validate_code(self.code)
        object.__setattr__(self, "code", code_clean)

        # Validate name
        name_clean = self._validate_name(self.name)
        object.__setattr__(self, "name", name_clean)

        # Validate description
        if self.description is not None:
            desc_clean = self.description.strip()
            if len(desc_clean) > 500:
                raise DepartmentError("Description must not exceed 500 characters")
            object.__setattr__(self, "description", desc_clean if desc_clean else None)

        # Validate cost_center_code if present
        if self.cost_center_code is not None:
            cc_clean = self.cost_center_code.strip()
            if not cc_clean:
                object.__setattr__(self, "cost_center_code", None)
            else:
                if len(cc_clean) < 2:
                    raise DepartmentError("Cost center code must be at least 2 characters")
                if len(cc_clean) > 20:
                    raise DepartmentError("Cost center code must not exceed 20 characters")
                object.__setattr__(self, "cost_center_code", cc_clean)

        # Validate manager_name
        if self.manager_name is not None:
            mgr_clean = self.manager_name.strip()
            if len(mgr_clean) > 100:
                raise DepartmentError("Manager name must not exceed 100 characters")
            object.__setattr__(self, "manager_name", mgr_clean if mgr_clean else None)

        # Validate manager_email
        if self.manager_email is not None:
            email_clean = self.manager_email.strip()
            if email_clean:
                if not self._validate_email(email_clean):
                    raise DepartmentError(f"Invalid email format: {email_clean}")
                object.__setattr__(self, "manager_email", email_clean)
            else:
                object.__setattr__(self, "manager_email", None)

        # Validate level
        if self.level < 0:
            raise DepartmentError("Level cannot be negative")
        if self.level > 10:
            raise DepartmentError("Department level exceeds maximum of 10")

        # Compute full path (simplified - actual hierarchy requires parent code)
        # Since department may have a parent relationship, we store parent separately.
        # Here we just set a placeholder; full path should be computed by service.
        object.__setattr__(self, "_full_path", self.code)

    @classmethod
    def _validate_code(cls, code: str) -> str:
        """Validate department code format."""
        if not code or not isinstance(code, str):
            raise InvalidDepartmentCodeError("Department code must be a non-empty string")
        cleaned = code.strip()
        if len(cleaned) < 2:
            raise InvalidDepartmentCodeError("Department code must be at least 2 characters")
        if len(cleaned) > 20:
            raise InvalidDepartmentCodeError("Department code must not exceed 20 characters")
        if not re.match(r"^[A-Za-z0-9_-]+$", cleaned):
            raise InvalidDepartmentCodeError(
                "Department code can only contain letters, numbers, hyphens, and underscores"
            )
        return cleaned

    @classmethod
    def _validate_name(cls, name: str) -> str:
        """Validate department name."""
        if not name or not isinstance(name, str):
            raise InvalidDepartmentNameError("Department name must be a non-empty string")
        cleaned = name.strip()
        if len(cleaned) < 2:
            raise InvalidDepartmentNameError("Department name must be at least 2 characters")
        if len(cleaned) > 100:
            raise InvalidDepartmentNameError("Department name must not exceed 100 characters")
        return cleaned

    @staticmethod
    def _validate_email(email: str) -> bool:
        """Basic email format validation."""
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(pattern, email) is not None

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def create_root(
        cls,
        code: str,
        name: str,
        description: str | None = None,
        manager_name: str | None = None,
        manager_email: str | None = None,
    ) -> DepartmentVO:
        """Create a top-level department (level 0)."""
        return cls(
            code=code,
            name=name,
            description=description,
            cost_center_code=None,
            manager_name=manager_name,
            manager_email=manager_email,
            is_active=True,
            level=0,
        )

    @classmethod
    def create_sub_department(
        cls,
        code: str,
        name: str,
        level: int,
        description: str | None = None,
        cost_center_code: str | None = None,
        manager_name: str | None = None,
        manager_email: str | None = None,
    ) -> DepartmentVO:
        """Create a sub-department with specified level."""
        return cls(
            code=code,
            name=name,
            description=description,
            cost_center_code=cost_center_code,
            manager_name=manager_name,
            manager_email=manager_email,
            is_active=True,
            level=level,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DepartmentVO:
        """Reconstruct from dictionary (e.g., from JSON)."""
        return cls(
            code=data["code"],
            name=data["name"],
            description=data.get("description"),
            cost_center_code=data.get("cost_center_code"),
            manager_name=data.get("manager_name"),
            manager_email=data.get("manager_email"),
            is_active=data.get("is_active", True),
            level=data.get("level", 0),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def full_path(self) -> str:
        """
        Return hierarchical path (e.g., 'CORP/FIN/ACC').
        This requires parent relationship which is not stored in this VO.
        Returns just the code as fallback; caller should compute full path.
        """
        return self._full_path

    @property
    def has_cost_center(self) -> bool:
        """Check if department is associated with a cost center."""
        return self.cost_center_code is not None

    @property
    def has_manager(self) -> bool:
        """Check if department has a manager assigned."""
        return self.manager_name is not None

    # ------------------------------------------------------------------------
    # Business logic (immutable transformations)
    # ------------------------------------------------------------------------

    def deactivate(self) -> DepartmentVO:
        """Return a new department with is_active=False."""
        if not self.is_active:
            return self
        return DepartmentVO(
            code=self.code,
            name=self.name,
            description=self.description,
            cost_center_code=self.cost_center_code,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=False,
            level=self.level,
        )

    def activate(self) -> DepartmentVO:
        """Return a new department with is_active=True."""
        if self.is_active:
            return self
        return DepartmentVO(
            code=self.code,
            name=self.name,
            description=self.description,
            cost_center_code=self.cost_center_code,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=True,
            level=self.level,
        )

    def rename(self, new_name: str) -> DepartmentVO:
        """Return a new department with updated name."""
        return DepartmentVO(
            code=self.code,
            name=new_name,
            description=self.description,
            cost_center_code=self.cost_center_code,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=self.is_active,
            level=self.level,
        )

    def change_description(self, new_description: str | None) -> DepartmentVO:
        """Return a new department with updated description."""
        return DepartmentVO(
            code=self.code,
            name=self.name,
            description=new_description,
            cost_center_code=self.cost_center_code,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=self.is_active,
            level=self.level,
        )

    def assign_cost_center(self, cost_center_code: str) -> DepartmentVO:
        """Return a new department with cost center assigned."""
        return DepartmentVO(
            code=self.code,
            name=self.name,
            description=self.description,
            cost_center_code=cost_center_code,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=self.is_active,
            level=self.level,
        )

    def remove_cost_center(self) -> DepartmentVO:
        """Return a new department with cost center unassigned."""
        return DepartmentVO(
            code=self.code,
            name=self.name,
            description=self.description,
            cost_center_code=None,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=self.is_active,
            level=self.level,
        )

    def change_manager(
        self, new_manager_name: str, new_manager_email: str | None = None
    ) -> DepartmentVO:
        """Return a new department with changed manager."""
        return DepartmentVO(
            code=self.code,
            name=self.name,
            description=self.description,
            cost_center_code=self.cost_center_code,
            manager_name=new_manager_name,
            manager_email=new_manager_email,
            is_active=self.is_active,
            level=self.level,
        )

    def promote(self) -> DepartmentVO:
        """Decrease level by 1 (promote in hierarchy). Level cannot go below 0."""
        new_level = max(0, self.level - 1)
        return DepartmentVO(
            code=self.code,
            name=self.name,
            description=self.description,
            cost_center_code=self.cost_center_code,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=self.is_active,
            level=new_level,
        )

    def demote(self) -> DepartmentVO:
        """Increase level by 1 (demote in hierarchy). Level cannot exceed 10."""
        new_level = min(10, self.level + 1)
        return DepartmentVO(
            code=self.code,
            name=self.name,
            description=self.description,
            cost_center_code=self.cost_center_code,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=self.is_active,
            level=new_level,
        )

    def with_full_path(self, full_path: str) -> DepartmentVO:
        """Return a new department with a custom full path (for hierarchy)."""
        obj = DepartmentVO(
            code=self.code,
            name=self.name,
            description=self.description,
            cost_center_code=self.cost_center_code,
            manager_name=self.manager_name,
            manager_email=self.manager_email,
            is_active=self.is_active,
            level=self.level,
        )
        object.__setattr__(obj, "_full_path", full_path)
        return obj

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "cost_center_code": self.cost_center_code,
            "manager_name": self.manager_name,
            "manager_email": self.manager_email,
            "is_active": self.is_active,
            "level": self.level,
            "full_path": self.full_path,
            "has_cost_center": self.has_cost_center,
            "has_manager": self.has_manager,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to format suitable for database insertion/update."""
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "cost_center_code": self.cost_center_code,
            "manager_name": self.manager_name,
            "manager_email": self.manager_email,
            "is_active": self.is_active,
            "level": self.level,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    def __repr__(self) -> str:
        return f"DepartmentVO('{self.code}', '{self.name}', active={self.is_active})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DepartmentVO):
            return False
        return self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)

    def __lt__(self, other: DepartmentVO) -> bool:
        """Order by code."""
        return self.code < other.code


# ============================================================================
# Helper Functions
# ============================================================================


def build_department_tree(departments: list[DepartmentVO]) -> dict[str, list[DepartmentVO]]:
    """
    Build a tree structure from a flat list of departments.
    This assumes that parent-child relationships are encoded in the code prefix
    or that there is a parent_code field (not present here). For simplicity,
    we return a mapping by level.

    For real hierarchy, departments should have a parent_code field.
    This helper groups departments by level.
    """
    tree: dict[int, list[DepartmentVO]] = {}
    for dept in departments:
        tree.setdefault(dept.level, []).append(dept)
    for level in tree:
        tree[level].sort()
    return tree


def filter_active_departments(departments: list[DepartmentVO]) -> list[DepartmentVO]:
    """Return only active departments."""
    return [d for d in departments if d.is_active]


def get_department_by_code(departments: list[DepartmentVO], code: str) -> DepartmentVO | None:
    """Find department by code in a list."""
    for dept in departments:
        if dept.code == code:
            return dept
    return None


def validate_department_code_unique(code: str, existing_codes: list[str]) -> bool:
    """Helper to check code uniqueness (for service layer use)."""
    return code not in existing_codes


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DepartmentError",
    "DepartmentVO",
    "InvalidDepartmentCodeError",
    "InvalidDepartmentNameError",
    "build_department_tree",
    "filter_active_departments",
    "get_department_by_code",
    "validate_department_code_unique",
]
