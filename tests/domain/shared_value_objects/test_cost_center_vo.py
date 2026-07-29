# tests/domain/shared_value_objects/test_cost_center_vo.py
"""
Comprehensive unit tests for domain/shared_value_objects/cost_center_vo.py.
Covers all public methods, edge cases, exceptions, factory methods,
business logic, serialization, dunder methods, and helper functions.
"""

import pytest

from domain.shared_value_objects.cost_center_vo import (
    CostCenterError,
    CostCenterVO,
    InvalidCostCenterCodeError,
    build_cost_center_hierarchy,
    flatten_hierarchy,
)

# ============================================================================
# Exception tests
# ============================================================================

class TestExceptions:
    def test_cost_center_error(self):
        with pytest.raises(CostCenterError):
            raise CostCenterError("test")

    def test_invalid_cost_center_code_error(self):
        with pytest.raises(InvalidCostCenterCodeError):
            raise InvalidCostCenterCodeError("test")


# ============================================================================
# CostCenterVO construction and validation
# ============================================================================

class TestCostCenterVOConstruction:
    def test_construction_valid_root(self):
        cc = CostCenterVO(code="1000", name="Corporate")
        assert cc.code == "1000"
        assert cc.name == "Corporate"
        assert cc.description is None
        assert cc.parent_code is None
        assert cc.is_active is True
        assert cc.level == 0
        assert cc.full_path == "1000"
        assert cc.is_root is True

    def test_construction_valid_child(self):
        cc = CostCenterVO(
            code="1010",
            name="IT Department",
            description="Information Technology",
            parent_code="1000",
            is_active=True,
            level=1,
        )
        assert cc.code == "1010"
        assert cc.parent_code == "1000"
        assert cc.full_path == "1000/1010"
        assert cc.level == 1
        assert cc.is_root is False

    def test_construction_trims_and_normalizes(self):
        cc = CostCenterVO(code=" 1010 ", name="  IT Dept  ", description="  Desc  ")
        assert cc.code == "1010"
        assert cc.name == "IT Dept"
        assert cc.description == "Desc"

    def test_construction_empty_description_ignored(self):
        cc = CostCenterVO(code="1000", name="Test", description="")
        assert cc.description is None

    def test_construction_desc_too_long_raises(self):
        with pytest.raises(CostCenterError, match="not exceed 500 characters"):
            CostCenterVO(code="1000", name="Test", description="a" * 501)

    def test_construction_invalid_code_empty(self):
        with pytest.raises(InvalidCostCenterCodeError, match="non-empty string"):
            CostCenterVO(code="", name="Test")

    def test_construction_invalid_code_short(self):
        with pytest.raises(InvalidCostCenterCodeError, match="at least 2 characters"):
            CostCenterVO(code="A", name="Test")

    def test_construction_invalid_code_long(self):
        with pytest.raises(InvalidCostCenterCodeError, match="not exceed 20 characters"):
            CostCenterVO(code="a" * 21, name="Test")

    def test_construction_invalid_code_chars(self):
        with pytest.raises(InvalidCostCenterCodeError, match="only contain letters, numbers, dots, underscores, and hyphens"):
            CostCenterVO(code="1000$", name="Test")

    def test_construction_invalid_name_empty(self):
        with pytest.raises(CostCenterError, match="non-empty string"):
            CostCenterVO(code="1000", name="")

    def test_construction_invalid_name_short(self):
        with pytest.raises(CostCenterError, match="at least 2 characters"):
            CostCenterVO(code="1000", name="A")

    def test_construction_invalid_name_long(self):
        with pytest.raises(CostCenterError, match="not exceed 100 characters"):
            CostCenterVO(code="1000", name="a" * 101)

    def test_construction_parent_code_same_as_code_raises(self):
        with pytest.raises(CostCenterError, match="cannot be its own parent"):
            CostCenterVO(code="1000", name="Test", parent_code="1000")

    def test_construction_parent_code_invalid_format_raises(self):
        with pytest.raises(InvalidCostCenterCodeError):
            CostCenterVO(code="1000", name="Test", parent_code="$")

    def test_construction_level_negative_raises(self):
        with pytest.raises(CostCenterError, match="Level cannot be negative"):
            CostCenterVO(code="1000", name="Test", level=-1)

    def test_construction_level_too_high_raises(self):
        with pytest.raises(CostCenterError, match="exceeds maximum depth"):
            CostCenterVO(code="1000", name="Test", level=21)

    # ---- __post_init__ also validates description is stripped if not None ----
    def test_construction_description_none_ok(self):
        cc = CostCenterVO(code="1000", name="Test", description=None)
        assert cc.description is None


# ============================================================================
# Tests for _validate_code (implicitly tested via construction)
# ============================================================================

# We also test the class method directly for coverage:
class TestValidateCode:
    def test_validate_code_valid(self):
        assert CostCenterVO._validate_code("1000") == "1000"
        assert CostCenterVO._validate_code("  ABC-123.45_ ") == "ABC-123.45_"
        assert CostCenterVO._validate_code("IT-DEPT") == "IT-DEPT"

    def test_validate_code_empty(self):
        with pytest.raises(InvalidCostCenterCodeError):
            CostCenterVO._validate_code("")
        with pytest.raises(InvalidCostCenterCodeError):
            CostCenterVO._validate_code("   ")

    def test_validate_code_too_short(self):
        with pytest.raises(InvalidCostCenterCodeError, match="at least 2 characters"):
            CostCenterVO._validate_code("A")

    def test_validate_code_too_long(self):
        with pytest.raises(InvalidCostCenterCodeError, match="not exceed 20 characters"):
            CostCenterVO._validate_code("a" * 21)

    def test_validate_code_invalid_chars(self):
        with pytest.raises(InvalidCostCenterCodeError, match="only contain letters"):
            CostCenterVO._validate_code("1000@")

    def test_validate_code_none_raises(self):
        with pytest.raises(InvalidCostCenterCodeError, match="non-empty string"):
            CostCenterVO._validate_code(None)  # type: ignore


# ============================================================================
# _compute_full_path (implicitly tested)
# ============================================================================

class TestFullPath:
    def test_full_path_root(self):
        cc = CostCenterVO(code="1000", name="Root")
        assert cc.full_path == "1000"
        assert cc._compute_full_path() == "1000"

    def test_full_path_child(self):
        cc = CostCenterVO(code="1010", name="Child", parent_code="1000")
        assert cc.full_path == "1000/1010"
        assert cc._compute_full_path() == "1000/1010"


# ============================================================================
# Factory methods
# ============================================================================

class TestFactoryMethods:
    def test_create_root(self):
        cc = CostCenterVO.create_root("2000", "Finance", "Finance department")
        assert cc.code == "2000"
        assert cc.name == "Finance"
        assert cc.description == "Finance department"
        assert cc.parent_code is None
        assert cc.level == 0
        assert cc.is_active is True

    def test_create_child(self):
        cc = CostCenterVO.create_child("2010", "Accounting", "2000", "Accounting dept", level=2)
        assert cc.code == "2010"
        assert cc.name == "Accounting"
        assert cc.parent_code == "2000"
        assert cc.level == 2
        assert cc.description == "Accounting dept"

    def test_from_dict(self):
        data = {
            "code": "3000",
            "name": "Sales",
            "description": "Sales department",
            "parent_code": "1000",
            "is_active": False,
            "level": 2,
        }
        cc = CostCenterVO.from_dict(data)
        assert cc.code == "3000"
        assert cc.name == "Sales"
        assert cc.description == "Sales department"
        assert cc.parent_code == "1000"
        assert cc.is_active is False
        assert cc.level == 2

    def test_from_dict_missing_optional_fields(self):
        data = {"code": "4000", "name": "Marketing"}
        cc = CostCenterVO.from_dict(data)
        assert cc.code == "4000"
        assert cc.name == "Marketing"
        assert cc.description is None
        assert cc.parent_code is None
        assert cc.is_active is True
        assert cc.level == 0


# ============================================================================
# Properties
# ============================================================================

class TestProperties:
    def test_is_root(self):
        root = CostCenterVO(code="1000", name="Root")
        assert root.is_root is True
        child = CostCenterVO(code="1010", name="Child", parent_code="1000")
        assert child.is_root is False

    def test_is_leaf(self):
        cc = CostCenterVO(code="1000", name="Test")
        # Always returns True in this value object
        assert cc.is_leaf is True


# ============================================================================
# Business logic methods (immutable transformations)
# ============================================================================

class TestBusinessMethods:
    def test_deactivate(self):
        cc = CostCenterVO(code="1000", name="Test", is_active=True)
        deactivated = cc.deactivate()
        assert deactivated is not cc
        assert deactivated.is_active is False
        assert deactivated.code == cc.code
        assert deactivated.name == cc.name
        # If already inactive, returns self
        cc2 = CostCenterVO(code="1001", name="Test2", is_active=False)
        result = cc2.deactivate()
        assert result is cc2

    def test_activate(self):
        cc = CostCenterVO(code="1000", name="Test", is_active=False)
        activated = cc.activate()
        assert activated is not cc
        assert activated.is_active is True
        # If already active, returns self
        cc2 = CostCenterVO(code="1001", name="Test2", is_active=True)
        result = cc2.activate()
        assert result is cc2

    def test_rename(self):
        cc = CostCenterVO(code="1000", name="Old")
        renamed = cc.rename("New Name")
        assert renamed is not cc
        assert renamed.name == "New Name"
        assert renamed.code == cc.code
        # Check that invalid name is validated in new instance
        with pytest.raises(CostCenterError, match="at least 2 characters"):
            cc.rename("A")

    def test_change_description(self):
        cc = CostCenterVO(code="1000", name="Test", description="Old")
        changed = cc.change_description("New Desc")
        assert changed.description == "New Desc"
        assert changed is not cc
        # Remove description
        changed2 = cc.change_description(None)
        assert changed2.description is None
        # Too long raises
        with pytest.raises(CostCenterError, match="not exceed 500 characters"):
            cc.change_description("a" * 501)

    def test_reparent(self):
        cc = CostCenterVO(code="1010", name="Child", parent_code="1000", level=1)
        reparented = cc.reparent("2000", 2)
        assert reparented.parent_code == "2000"
        assert reparented.level == 2
        assert reparented.full_path == "2000/1010"
        # Self parent raises
        with pytest.raises(CostCenterError, match="cannot be its own parent"):
            cc.reparent("1010", 1)

    def test_is_descendant_of(self):
        root = CostCenterVO(code="1000", name="Root")
        child = CostCenterVO(code="1010", name="Child", parent_code="1000")
        grandchild = CostCenterVO(code="1011", name="Grandchild", parent_code="1010")
        # Grandchild is descendant of 1000 and 1010
        assert grandchild.is_descendant_of("1000") is True
        assert grandchild.is_descendant_of("1010") is True
        assert grandchild.is_descendant_of("1011") is True  # self
        assert grandchild.is_descendant_of("999") is False
        # Child is descendant of 1000
        assert child.is_descendant_of("1000") is True
        assert child.is_descendant_of("1010") is True  # self
        assert child.is_descendant_of("1001") is False
        # Root is descendant of itself
        assert root.is_descendant_of("1000") is True
        assert root.is_descendant_of("999") is False
        # Empty ancestor returns False
        assert child.is_descendant_of("") is False

    def test_matches_code_pattern(self):
        cc = CostCenterVO(code="FIN-001", name="Finance")
        assert cc.matches_code_pattern("FIN*") is True
        assert cc.matches_code_pattern("FIN-???") is True
        assert cc.matches_code_pattern("FIN-??") is False
        assert cc.matches_code_pattern("ACC*") is False
        assert cc.matches_code_pattern("FIN-00*") is True
        assert cc.matches_code_pattern("*001") is True
        # Empty pattern matches nothing? Actually re.fullmatch with empty pattern matches empty string, so false.
        assert cc.matches_code_pattern("") is False


# ============================================================================
# Serialization
# ============================================================================

class TestSerialization:
    def test_to_dict(self):
        cc = CostCenterVO(
            code="1000",
            name="Corporate",
            description="HQ",
            parent_code=None,
            is_active=True,
            level=0,
        )
        d = cc.to_dict()
        assert d["code"] == "1000"
        assert d["name"] == "Corporate"
        assert d["description"] == "HQ"
        assert d["parent_code"] is None
        assert d["is_active"] is True
        assert d["level"] == 0
        assert d["full_path"] == "1000"
        assert d["is_root"] is True

    def test_to_db_record(self):
        cc = CostCenterVO(
            code="1010",
            name="IT",
            description="IT Dept",
            parent_code="1000",
            is_active=False,
            level=1,
        )
        db = cc.to_db_record()
        assert db["code"] == "1010"
        assert db["name"] == "IT"
        assert db["description"] == "IT Dept"
        assert db["parent_code"] == "1000"
        assert db["is_active"] is False
        assert db["level"] == 1


# ============================================================================
# Dunder methods
# ============================================================================

class TestDunderMethods:
    def test_str(self):
        cc = CostCenterVO(code="1000", name="Corporate")
        assert str(cc) == "1000 - Corporate"

    def test_repr(self):
        cc = CostCenterVO(code="1000", name="Corporate", is_active=True)
        assert repr(cc) == "CostCenterVO('1000', 'Corporate', active=True)"
        cc2 = CostCenterVO(code="1001", name="Inactive", is_active=False)
        assert repr(cc2) == "CostCenterVO('1001', 'Inactive', active=False)"

    def test_eq(self):
        cc1 = CostCenterVO(code="1000", name="Corporate")
        cc2 = CostCenterVO(code="1000", name="Different")  # Same code
        cc3 = CostCenterVO(code="1001", name="Other")
        assert cc1 == cc2
        assert cc1 != cc3
        assert cc1 != "not a cost center"

    def test_hash(self):
        cc1 = CostCenterVO(code="1000", name="Corporate")
        cc2 = CostCenterVO(code="1000", name="Different")
        cc3 = CostCenterVO(code="1001", name="Other")
        assert hash(cc1) == hash(cc2)
        assert hash(cc1) != hash(cc3)

    def test_lt(self):
        cc1 = CostCenterVO(code="1000", name="A")
        cc2 = CostCenterVO(code="1010", name="B")
        assert cc1 < cc2
        assert cc2 > cc1
        # Comparing with other type? __lt__ expects CostCenterVO.
        with pytest.raises(TypeError):
            cc1 < "string"


# ============================================================================
# Helper functions
# ============================================================================

class TestHelperFunctions:
    def test_build_cost_center_hierarchy(self):
        roots = [
            CostCenterVO.create_root("1000", "Corp"),
            CostCenterVO.create_root("2000", "Finance"),
        ]
        child1 = CostCenterVO.create_child("1010", "IT", "1000")
        child2 = CostCenterVO.create_child("1020", "HR", "1000")
        child3 = CostCenterVO.create_child("2010", "Accounting", "2000")
        cost_centers = roots + [child1, child2, child3]
        hierarchy = build_cost_center_hierarchy(cost_centers)

        # Check root children
        assert hierarchy[None] == sorted([CostCenterVO.create_root("1000", "Corp"), CostCenterVO.create_root("2000", "Finance")], key=lambda x: x.code)
        assert hierarchy["1000"] == [child1, child2]  # sorted by code (1010, 1020)
        assert hierarchy["2000"] == [child3]
        # No children for leaf nodes
        assert hierarchy.get("1010") is None  # not present
        # Parent with no children not in keys

    def test_build_cost_center_hierarchy_empty(self):
        hierarchy = build_cost_center_hierarchy([])
        assert hierarchy == {}

    def test_flatten_hierarchy(self):
        cost_centers = [
            CostCenterVO.create_root("1000", "Corp"),
            CostCenterVO.create_child("1010", "IT", "1000"),
            CostCenterVO.create_root("2000", "Finance"),
            CostCenterVO.create_child("2010", "Accounting", "2000"),
        ]
        paths = flatten_hierarchy(cost_centers)
        expected = sorted(["1000", "1000/1010", "2000", "2000/2010"])
        assert paths == expected

    def test_flatten_hierarchy_empty(self):
        assert flatten_hierarchy([]) == []


# ============================================================================
# Integration: factory + reparent + descendant check
# ============================================================================

class TestIntegration:
    def test_full_flow(self):
        root = CostCenterVO.create_root("1000", "Corporate")
        child = CostCenterVO.create_child("1010", "IT", "1000")
        grandchild = CostCenterVO.create_child("1011", "DevOps", "1010", level=2)

        # Check paths
        assert root.full_path == "1000"
        assert child.full_path == "1000/1010"
        assert grandchild.full_path == "1010/1011"

        # Check descendant
        assert grandchild.is_descendant_of("1000") is True
        assert grandchild.is_descendant_of("1010") is True
        assert grandchild.is_descendant_of("1011") is True

        # Deactivate grandchild
        deactivated = grandchild.deactivate()
        assert deactivated.is_active is False
        # Reactivate
        reactivated = deactivated.activate()
        assert reactivated.is_active is True

        # Rename
        renamed = reactivated.rename("DevOps Team")
        assert renamed.name == "DevOps Team"

        # Reparent
        reparented = renamed.reparent("2000", 2)
        assert reparented.parent_code == "2000"
        assert reparented.full_path == "2000/1011"
        assert reparented.is_descendant_of("2000") is True
