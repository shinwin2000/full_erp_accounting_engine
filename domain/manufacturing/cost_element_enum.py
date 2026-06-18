#!/usr/bin/env python3
"""
Module: cost_element_enum.py
Layer: 6 - Domain / Manufacturing
Responsibility: Cost element enumeration: material, labor, overhead.

Defines cost element types used to classify manufacturing costs.

Dependencies:
- Python standard library (enum)

Audit: Each usage of cost element is recorded.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

# ============================================================================
# Cost Element Enum
# ============================================================================


class CostElement(Enum):
    """
    Manufacturing cost elements.

    Business context:
    Classifies costs in production into:
    - MATERIAL: Direct raw materials
    - LABOR: Direct labor
    - OVERHEAD: Factory overhead (indirect)
    - SUBCONTRACT: Subcontracted services
    - OTHER: Other costs
    """

    MATERIAL = "material"
    LABOR = "labor"
    OVERHEAD = "overhead"
    SUBCONTRACT = "subcontract"
    OTHER = "other"

    @property
    def is_direct_cost(self) -> bool:
        """Return True if this is a direct cost (material or labor)."""
        return self in (CostElement.MATERIAL, CostElement.LABOR)

    @property
    def is_indirect_cost(self) -> bool:
        """Return True if this is an indirect cost."""
        return self in (CostElement.OVERHEAD, CostElement.SUBCONTRACT, CostElement.OTHER)

    @classmethod
    def from_string(cls, value: str) -> CostElement | None:
        """Convert string to CostElement, case-insensitive."""
        value_lower = value.lower()
        for member in cls:
            if member.value == value_lower or member.name.lower() == value_lower:
                return member
        return None

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "name": self.name,
            "value": self.value,
            "is_direct_cost": self.is_direct_cost,
            "is_indirect_cost": self.is_indirect_cost,
        }


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CostElement",
]
