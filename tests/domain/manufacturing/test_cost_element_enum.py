# test_cost_element_enum.py
# ==========================
# Comprehensive tests for domain/manufacturing/cost_element_enum.py.
# Covers all enum members, properties, and methods.

import pytest

from domain.manufacturing.cost_element_enum import CostElement


class TestCostElement:
    """Tests for the CostElement enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(CostElement, "MATERIAL")
        assert hasattr(CostElement, "LABOR")
        assert hasattr(CostElement, "OVERHEAD")
        assert hasattr(CostElement, "SUBCONTRACT")
        assert hasattr(CostElement, "OTHER")

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(CostElement.MATERIAL, CostElement)
        assert isinstance(CostElement.LABOR, CostElement)
        assert isinstance(CostElement.OVERHEAD, CostElement)
        assert isinstance(CostElement.SUBCONTRACT, CostElement)
        assert isinstance(CostElement.OTHER, CostElement)

    def test_member_values(self):
        """Check that each member has the correct value."""
        assert CostElement.MATERIAL.value == "material"
        assert CostElement.LABOR.value == "labor"
        assert CostElement.OVERHEAD.value == "overhead"
        assert CostElement.SUBCONTRACT.value == "subcontract"
        assert CostElement.OTHER.value == "other"

    # ---- is_direct_cost ----
    def test_is_direct_cost(self):
        """Test is_direct_cost property."""
        assert CostElement.MATERIAL.is_direct_cost is True
        assert CostElement.LABOR.is_direct_cost is True
        assert CostElement.OVERHEAD.is_direct_cost is False
        assert CostElement.SUBCONTRACT.is_direct_cost is False
        assert CostElement.OTHER.is_direct_cost is False

    # ---- is_indirect_cost ----
    def test_is_indirect_cost(self):
        """Test is_indirect_cost property."""
        assert CostElement.MATERIAL.is_indirect_cost is False
        assert CostElement.LABOR.is_indirect_cost is False
        assert CostElement.OVERHEAD.is_indirect_cost is True
        assert CostElement.SUBCONTRACT.is_indirect_cost is True
        assert CostElement.OTHER.is_indirect_cost is True

    # ---- from_string ----
    def test_from_string_by_value(self):
        """Test from_string using value strings."""
        assert CostElement.from_string("material") == CostElement.MATERIAL
        assert CostElement.from_string("labor") == CostElement.LABOR
        assert CostElement.from_string("overhead") == CostElement.OVERHEAD
        assert CostElement.from_string("subcontract") == CostElement.SUBCONTRACT
        assert CostElement.from_string("other") == CostElement.OTHER

    def test_from_string_by_name(self):
        """Test from_string using enum name strings (case-insensitive)."""
        assert CostElement.from_string("MATERIAL") == CostElement.MATERIAL
        assert CostElement.from_string("LABOR") == CostElement.LABOR
        assert CostElement.from_string("OVERHEAD") == CostElement.OVERHEAD
        assert CostElement.from_string("SUBCONTRACT") == CostElement.SUBCONTRACT
        assert CostElement.from_string("OTHER") == CostElement.OTHER

    def test_from_string_case_insensitive(self):
        """Test case-insensitivity of from_string."""
        assert CostElement.from_string("Material") == CostElement.MATERIAL
        assert CostElement.from_string("LaBoR") == CostElement.LABOR
        assert CostElement.from_string("OverHead") == CostElement.OVERHEAD
        assert CostElement.from_string("SubContract") == CostElement.SUBCONTRACT
        assert CostElement.from_string("OtHeR") == CostElement.OTHER

    def test_from_string_invalid_returns_none(self):
        """Test from_string returns None for invalid strings."""
        assert CostElement.from_string("invalid") is None
        assert CostElement.from_string("") is None
        assert CostElement.from_string("MATERIALS") is None

    # ---- to_dict ----
    def test_to_dict(self):
        """Test to_dict method for each member."""
        for member in CostElement:
            d = member.to_dict()
            assert d["name"] == member.name
            assert d["value"] == member.value
            assert d["is_direct_cost"] == member.is_direct_cost
            assert d["is_indirect_cost"] == member.is_indirect_cost

    def test_to_dict_for_material(self):
        """Test to_dict specifically for MATERIAL."""
        d = CostElement.MATERIAL.to_dict()
        assert d == {
            "name": "MATERIAL",
            "value": "material",
            "is_direct_cost": True,
            "is_indirect_cost": False,
        }

    def test_to_dict_for_overhead(self):
        """Test to_dict specifically for OVERHEAD."""
        d = CostElement.OVERHEAD.to_dict()
        assert d == {
            "name": "OVERHEAD",
            "value": "overhead",
            "is_direct_cost": False,
            "is_indirect_cost": True,
        }