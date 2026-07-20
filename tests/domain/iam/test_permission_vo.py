# tests/domain/iam/test_permission_vo.py
"""
Comprehensive tests for domain/iam/permission_vo.py.
Covers all methods, exceptions, and includes negative path tests.

FIXES:
- All enum tests with parametrize.
- All PermissionVO factory methods, matches, properties, validation.
- All PermissionUtils methods.
- All exceptions tested with pytest.raises.
- No external dependencies (pure domain).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from domain.iam.permission_vo import (
    ActionType,
    InvalidPermissionFormatError,
    PermissionError,
    PermissionUtils,
    PermissionVO,
    ResourceType,
)


# ============================================================================
# TESTS FOR RESOURCE TYPE ENUM
# ============================================================================

class TestResourceType:
    def test_members(self):
        expected = [
            "JOURNAL", "ACCOUNT", "INVOICE", "PAYMENT", "CUSTOMER", "SUPPLIER",
            "EMPLOYEE", "FIXED_ASSET", "INTANGIBLE_ASSET", "INVENTORY", "TAX",
            "PERIOD", "REPORT", "USER", "ROLE", "PERMISSION", "SYSTEM_CONFIG",
            "AUDIT", "LEGAL_ENTITY", "BUDGET", "FOREX", "CONSOLIDATION",
            "HEDGE", "GOODWILL", "MANUFACTURING", "PAYROLL", "PROJECT",
            "BANK_CASH", "ALL",
        ]
        for name in expected:
            assert hasattr(ResourceType, name)

    @pytest.mark.parametrize("resource,expected_display", [
        (ResourceType.JOURNAL, "Jurnal"),
        (ResourceType.ACCOUNT, "Akun"),
        (ResourceType.INVOICE, "Faktur"),
        (ResourceType.PAYMENT, "Pembayaran"),
        (ResourceType.ALL, "Semua Resource"),
        (ResourceType.EMPLOYEE, "Karyawan"),
    ])
    def test_display_name(self, resource, expected_display):
        assert resource.display_name() == expected_display

    @pytest.mark.parametrize("input_str,expected", [
        ("journal", ResourceType.JOURNAL),
        ("account", ResourceType.ACCOUNT),
        ("*", ResourceType.ALL),
        ("INVOICE", ResourceType.INVOICE),  # case insensitive? from_string lowercases
        ("unknown", None),
    ])
    def test_from_string(self, input_str, expected):
        result = ResourceType.from_string(input_str)
        assert result == expected

    @pytest.mark.parametrize("self_resource,other_resource,expected", [
        (ResourceType.ALL, ResourceType.JOURNAL, True),
        (ResourceType.JOURNAL, ResourceType.JOURNAL, True),
        (ResourceType.JOURNAL, ResourceType.ACCOUNT, False),
        (ResourceType.ALL, ResourceType.ALL, True),
    ])
    def test_matches(self, self_resource, other_resource, expected):
        assert self_resource.matches(other_resource) == expected


# ============================================================================
# TESTS FOR ACTION TYPE ENUM
# ============================================================================

class TestActionType:
    def test_members(self):
        expected = [
            "CREATE", "READ", "UPDATE", "DELETE", "APPROVE", "REJECT",
            "POST", "REVERSE", "EXPORT", "IMPORT", "EXECUTE", "CLOSE",
            "REOPEN", "LOCK", "UNLOCK", "ARCHIVE", "UNARCHIVE", "TRANSFER",
            "ADJUST", "RECONCILE", "DEPRECIATE", "REVALUE", "IMPAIR", "ALL",
        ]
        for name in expected:
            assert hasattr(ActionType, name)

    @pytest.mark.parametrize("action,expected_display", [
        (ActionType.CREATE, "Buat"),
        (ActionType.READ, "Baca"),
        (ActionType.UPDATE, "Ubah"),
        (ActionType.DELETE, "Hapus"),
        (ActionType.APPROVE, "Setujui"),
        (ActionType.REJECT, "Tolak"),
        (ActionType.ALL, "Semua Aksi"),
    ])
    def test_display_name(self, action, expected_display):
        assert action.display_name() == expected_display

    @pytest.mark.parametrize("input_str,expected", [
        ("create", ActionType.CREATE),
        ("read", ActionType.READ),
        ("*", ActionType.ALL),
        ("UPDATE", ActionType.UPDATE),
        ("unknown", None),
    ])
    def test_from_string(self, input_str, expected):
        result = ActionType.from_string(input_str)
        assert result == expected

    @pytest.mark.parametrize("self_action,other_action,expected", [
        (ActionType.ALL, ActionType.CREATE, True),
        (ActionType.CREATE, ActionType.CREATE, True),
        (ActionType.CREATE, ActionType.READ, False),
        (ActionType.ALL, ActionType.ALL, True),
    ])
    def test_matches(self, self_action, other_action, expected):
        assert self_action.matches(other_action) == expected


# ============================================================================
# TESTS FOR EXCEPTIONS
# ============================================================================

class TestExceptions:
    def test_permission_error(self):
        with pytest.raises(PermissionError, match="test"):
            raise PermissionError("test")

    def test_invalid_permission_format_error(self):
        with pytest.raises(InvalidPermissionFormatError, match="invalid"):
            raise InvalidPermissionFormatError("invalid")


# ============================================================================
# TESTS FOR PERMISSION VO
# ============================================================================

class TestPermissionVO:
    # ------------------------------------------------------------------------
    # Construction and normalization
    # ------------------------------------------------------------------------

    def test_constructor_with_enums(self):
        perm = PermissionVO(resource=ResourceType.JOURNAL, action=ActionType.CREATE)
        assert perm.resource == ResourceType.JOURNAL
        assert perm.action == ActionType.CREATE
        assert perm.description == ""
        assert perm.metadata == {}

    def test_constructor_with_strings(self):
        perm = PermissionVO(resource="journal", action="create", description="desc", metadata={"k": "v"})
        assert perm.resource == ResourceType.JOURNAL  # normalized
        assert perm.action == ActionType.CREATE
        assert perm.description == "desc"
        assert perm.metadata == {"k": "v"}

    def test_constructor_with_custom_string(self):
        perm = PermissionVO(resource="custom_resource", action="custom_action")
        assert perm.resource == "custom_resource"
        assert perm.action == "custom_action"

    def test_constructor_with_wildcard_strings(self):
        perm = PermissionVO(resource="*", action="*")
        assert perm.resource == "*"
        assert perm.action == "*"

    def test_constructor_invalid_resource_raises(self):
        with pytest.raises(InvalidPermissionFormatError, match="Invalid resource format"):
            PermissionVO(resource="Invalid Resource", action="read")

    def test_constructor_invalid_action_raises(self):
        with pytest.raises(InvalidPermissionFormatError, match="Invalid action format"):
            PermissionVO(resource="journal", action="Invalid Action")

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @pytest.mark.parametrize("perm_str,expected_resource,expected_action", [
        ("journal:create", ResourceType.JOURNAL, ActionType.CREATE),
        ("report:export", ResourceType.REPORT, ActionType.EXPORT),
        ("*:*", "*", "*"),
        ("custom:action", "custom", "action"),
    ])
    def test_from_string(self, perm_str, expected_resource, expected_action):
        perm = PermissionVO.from_string(perm_str)
        assert perm.resource == expected_resource
        assert perm.action == expected_action

    def test_from_string_with_description(self):
        perm = PermissionVO.from_string("journal:read", "Read journal")
        assert perm.description == "Read journal"

    def test_from_string_invalid_format_raises(self):
        with pytest.raises(InvalidPermissionFormatError, match="Expected 'resource:action'"):
            PermissionVO.from_string("invalid_format")

    def test_from_string_missing_action(self):
        with pytest.raises(InvalidPermissionFormatError):
            PermissionVO.from_string("journal:")

    def test_from_string_empty(self):
        with pytest.raises(InvalidPermissionFormatError):
            PermissionVO.from_string("")

    def test_from_resource_action_with_enums(self):
        perm = PermissionVO.from_resource_action(ResourceType.INVOICE, ActionType.APPROVE)
        assert perm.resource == ResourceType.INVOICE
        assert perm.action == ActionType.APPROVE

    def test_from_resource_action_with_strings(self):
        perm = PermissionVO.from_resource_action("payment", "execute")
        assert perm.resource == ResourceType.PAYMENT
        assert perm.action == ActionType.EXECUTE

    def test_super_admin(self):
        perm = PermissionVO.super_admin()
        assert perm.resource == "*"
        assert perm.action == "*"
        assert perm.description == "Super Administrator - Full Access"

    def test_from_dict(self):
        data = {"resource": "journal", "action": "create", "description": "desc"}
        perm = PermissionVO.from_dict(data)
        assert perm.resource == ResourceType.JOURNAL
        assert perm.action == ActionType.CREATE
        assert perm.description == "desc"

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    def test_resource_value(self):
        perm = PermissionVO.from_string("journal:create")
        assert perm.resource_value == "journal"
        perm = PermissionVO(resource="custom", action="action")
        assert perm.resource_value == "custom"

    def test_action_value(self):
        perm = PermissionVO.from_string("journal:create")
        assert perm.action_value == "create"
        perm = PermissionVO(resource="custom", action="action")
        assert perm.action_value == "action"

    def test_is_wildcard(self):
        assert PermissionVO.from_string("*:*").is_wildcard is True
        assert PermissionVO.from_string("journal:*").is_wildcard is False
        assert PermissionVO.from_string("*:create").is_wildcard is False

    def test_is_resource_wildcard(self):
        assert PermissionVO.from_string("*:create").is_resource_wildcard is True
        assert PermissionVO.from_string("journal:create").is_resource_wildcard is False

    def test_is_action_wildcard(self):
        assert PermissionVO.from_string("journal:*").is_action_wildcard is True
        assert PermissionVO.from_string("journal:create").is_action_wildcard is False

    def test_to_string(self):
        perm = PermissionVO.from_string("journal:create")
        assert perm.to_string == "journal:create"
        perm = PermissionVO.from_string("*:*")
        assert perm.to_string == "*:*"

    # ------------------------------------------------------------------------
    # Matching methods
    # ------------------------------------------------------------------------

    @pytest.mark.parametrize("perm_a,perm_b,expected", [
        # Wildcard resource and action
        ("*:*", "journal:create", True),
        ("*:*", "*:*", True),
        # Wildcard resource
        ("journal:*", "journal:create", True),
        ("journal:*", "journal:delete", True),
        ("journal:*", "account:create", False),
        # Wildcard action
        ("*:create", "journal:create", True),
        ("*:create", "account:create", True),
        ("*:create", "journal:read", False),
        # Exact match
        ("journal:create", "journal:create", True),
        ("journal:create", "journal:read", False),
        ("journal:create", "account:create", False),
        # Custom strings
        ("custom:action", "custom:action", True),
        ("custom:action", "custom:other", False),
    ])
    def test_matches(self, perm_a, perm_b, expected):
        perm1 = PermissionVO.from_string(perm_a)
        perm2 = PermissionVO.from_string(perm_b)
        assert perm1.matches(perm2) == expected

    @pytest.mark.parametrize("perm_str,other_str,expected", [
        ("journal:*", "journal:create", True),
        ("journal:*", "account:create", False),
        ("*:*", "anything:anything", True),
    ])
    def test_matches_string(self, perm_str, other_str, expected):
        perm = PermissionVO.from_string(perm_str)
        assert perm.matches_string(other_str) == expected

    def test_matches_string_invalid_returns_false(self):
        perm = PermissionVO.from_string("journal:create")
        assert perm.matches_string("invalid") is False

    @pytest.mark.parametrize("perm_str,resource_str,expected", [
        ("journal:*", "journal", True),
        ("journal:*", "account", False),
        ("*:*", "anything", True),
        ("custom:action", "custom", True),
        ("custom:action", "other", False),
    ])
    def test_matches_resource(self, perm_str, resource_str, expected):
        perm = PermissionVO.from_string(perm_str)
        # test with string
        assert perm.matches_resource(resource_str) == expected
        # test with enum if possible
        res_enum = ResourceType.from_string(resource_str)
        if res_enum:
            assert perm.matches_resource(res_enum) == expected

    @pytest.mark.parametrize("perm_str,action_str,expected", [
        ("*:create", "create", True),
        ("*:create", "read", False),
        ("journal:*", "create", True),  # wildcard action matches any
        ("journal:create", "create", True),
        ("journal:create", "read", False),
        ("*:*", "anything", True),
    ])
    def test_matches_action(self, perm_str, action_str, expected):
        perm = PermissionVO.from_string(perm_str)
        # test with string
        assert perm.matches_action(action_str) == expected
        # test with enum if possible
        act_enum = ActionType.from_string(action_str)
        if act_enum:
            assert perm.matches_action(act_enum) == expected

    # ------------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------------

    @pytest.mark.parametrize("perm_str,expected", [
        ("journal:create", True),
        ("*:*", True),
        ("custom:action", True),  # valid custom
        ("invalid", False),
        ("journal:", False),
        (":create", False),
        ("", False),
    ])
    def test_validate_format(self, perm_str, expected):
        assert PermissionVO.validate_format(perm_str) == expected

    def test_validate_list(self):
        perms = ["journal:create", "valid:action", "invalid", "journal:"]
        is_valid, invalid = PermissionVO.validate_list(perms)
        assert is_valid is False
        assert invalid == ["invalid", "journal:"]

    def test_validate_list_all_valid(self):
        perms = ["journal:create", "account:read"]
        is_valid, invalid = PermissionVO.validate_list(perms)
        assert is_valid is True
        assert invalid == []

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def test_to_dict(self):
        perm = PermissionVO.from_string("journal:create", "Create journal")
        d = perm.to_dict()
        assert d["resource"] == "journal"
        assert d["action"] == "create"
        assert d["permission"] == "journal:create"
        assert d["description"] == "Create journal"
        assert d["is_wildcard"] is False
        assert d["metadata"] == {}

        perm = PermissionVO.super_admin()
        d = perm.to_dict()
        assert d["is_wildcard"] is True

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def test_str(self):
        perm = PermissionVO.from_string("journal:create")
        assert str(perm) == "journal:create"

    def test_repr(self):
        perm = PermissionVO.from_string("journal:create")
        assert repr(perm) == "PermissionVO(journal:create)"

    def test_equality(self):
        p1 = PermissionVO.from_string("journal:create")
        p2 = PermissionVO.from_string("journal:create")
        p3 = PermissionVO.from_string("journal:read")
        assert p1 == p2
        assert p1 != p3
        assert p1 != "string"

    def test_hash(self):
        p1 = PermissionVO.from_string("journal:create")
        p2 = PermissionVO.from_string("journal:create")
        assert hash(p1) == hash(p2)

    def test_lt(self):
        p1 = PermissionVO.from_string("account:create")
        p2 = PermissionVO.from_string("journal:create")
        assert p1 < p2  # "account:create" < "journal:create"

    # ------------------------------------------------------------------------
    # Cache behavior
    # ------------------------------------------------------------------------

    def test_cache_used(self):
        # Clear cache first
        PermissionVO._cache.clear()
        p1 = PermissionVO.from_string("journal:create")
        p2 = PermissionVO.from_string("journal:create")
        assert p1 is p2  # same object from cache

        p3 = PermissionVO.from_resource_action(ResourceType.JOURNAL, ActionType.CREATE)
        assert p1 is p3

        # Different permission
        p4 = PermissionVO.from_string("journal:read")
        assert p1 is not p4


# ============================================================================
# TESTS FOR PERMISSION UTILS
# ============================================================================

class TestPermissionUtils:
    def test_get_default_permissions_for_role(self):
        # Known roles
        super_admin = PermissionUtils.get_default_permissions_for_role("super_admin")
        assert super_admin == {"*:*"}

        admin = PermissionUtils.get_default_permissions_for_role("admin")
        assert "user:*" in admin
        assert "role:*" in admin
        assert "system_config:*" in admin

        user = PermissionUtils.get_default_permissions_for_role("user")
        assert "journal:create" in user
        assert "journal:read" in user
        assert "report:read" in user

        # Unknown role returns empty set
        unknown = PermissionUtils.get_default_permissions_for_role("unknown")
        assert unknown == set()

    def test_parse_permission_set(self):
        perm_set = {"journal:create", "invalid_format", "account:read"}
        result = PermissionUtils.parse_permission_set(perm_set)
        # Should have 2 valid ones
        assert len(result) == 2
        strings = {p.to_string for p in result}
        assert "journal:create" in strings
        assert "account:read" in strings
        assert "invalid_format" not in strings

    def test_parse_permission_set_empty(self):
        result = PermissionUtils.parse_permission_set(set())
        assert result == set()

    def test_format_permission_set(self):
        perms = {
            PermissionVO.from_string("journal:create"),
            PermissionVO.from_string("account:read"),
        }
        result = PermissionUtils.format_permission_set(perms)
        assert result == {"journal:create", "account:read"}

    def test_format_permission_set_empty(self):
        result = PermissionUtils.format_permission_set(set())
        assert result == set()

    # ------------------------------------------------------------------------
    # has_permission
    # ------------------------------------------------------------------------

    @pytest.mark.parametrize("user_perms,required,expected", [
        # Super admin has everything
        ({"*:*"}, "journal:create", True),
        # Wildcard resource
        ({"journal:*"}, "journal:create", True),
        ({"journal:*"}, "journal:delete", True),
        ({"journal:*"}, "account:create", False),
        # Wildcard action
        ({"*:create"}, "journal:create", True),
        ({"*:create"}, "account:create", True),
        ({"*:create"}, "journal:read", False),
        # Exact match
        ({"journal:create"}, "journal:create", True),
        ({"journal:create"}, "journal:read", False),
        # Multiple permissions
        ({"journal:create", "account:read"}, "journal:create", True),
        ({"journal:create", "account:read"}, "payment:execute", False),
        # Permission that covers another (wildcard covers)
        ({"*:*"}, "journal:create", True),
        ({"journal:*"}, "journal:create", True),
    ])
    def test_has_permission(self, user_perms, required, expected):
        user_perms_set = {PermissionVO.from_string(p) for p in user_perms}
        required_perm = PermissionVO.from_string(required)
        result = PermissionUtils.has_permission(user_perms_set, required_perm)
        assert result == expected

    def test_has_permission_empty(self):
        result = PermissionUtils.has_permission(set(), PermissionVO.from_string("journal:create"))
        assert result is False

    # ------------------------------------------------------------------------
    # get_permissions_by_resource
    # ------------------------------------------------------------------------

    def test_get_permissions_by_resource(self):
        perms = {
            PermissionVO.from_string("journal:create"),
            PermissionVO.from_string("journal:read"),
            PermissionVO.from_string("account:create"),
            PermissionVO.from_string("*:delete"),  # resource wildcard
        }
        result = PermissionUtils.get_permissions_by_resource(perms, ResourceType.JOURNAL)
        # Should get journal:create, journal:read, and the resource wildcard
        expected_strings = {"journal:create", "journal:read", "*:delete"}
        result_strings = {p.to_string for p in result}
        assert result_strings == expected_strings

        # with string
        result2 = PermissionUtils.get_permissions_by_resource(perms, "account")
        expected2 = {"account:create", "*:delete"}
        result2_strings = {p.to_string for p in result2}
        assert result2_strings == expected2

    def test_get_permissions_by_resource_empty(self):
        result = PermissionUtils.get_permissions_by_resource(set(), "journal")
        assert result == []

    # ------------------------------------------------------------------------
    # get_permissions_by_action
    # ------------------------------------------------------------------------

    def test_get_permissions_by_action(self):
        perms = {
            PermissionVO.from_string("journal:create"),
            PermissionVO.from_string("account:create"),
            PermissionVO.from_string("journal:read"),
            PermissionVO.from_string("journal:*"),  # action wildcard
        }
        result = PermissionUtils.get_permissions_by_action(perms, ActionType.CREATE)
        expected_strings = {"journal:create", "account:create", "journal:*"}
        result_strings = {p.to_string for p in result}
        assert result_strings == expected_strings

        # with string
        result2 = PermissionUtils.get_permissions_by_action(perms, "read")
        expected2 = {"journal:read", "journal:*"}
        result2_strings = {p.to_string for p in result2}
        assert result2_strings == expected2

    # ------------------------------------------------------------------------
    # merge_permissions
    # ------------------------------------------------------------------------

    def test_merge_permissions(self):
        set1 = {
            PermissionVO.from_string("journal:create"),
            PermissionVO.from_string("journal:read"),
        }
        set2 = {
            PermissionVO.from_string("journal:*"),  # covers journal:create and journal:read
            PermissionVO.from_string("account:create"),
        }
        merged = PermissionUtils.merge_permissions(set1, set2)
        # journal:create and journal:read should be covered by journal:*, so they are omitted
        # But we still have journal:* and account:create
        expected_strings = {"journal:*", "account:create"}
        result_strings = {p.to_string for p in merged}
        assert result_strings == expected_strings

    def test_merge_permissions_no_overlap(self):
        set1 = {PermissionVO.from_string("journal:create")}
        set2 = {PermissionVO.from_string("account:read")}
        merged = PermissionUtils.merge_permissions(set1, set2)
        result_strings = {p.to_string for p in merged}
        assert result_strings == {"journal:create", "account:read"}

    def test_merge_permissions_with_super_admin(self):
        set1 = {PermissionVO.super_admin()}
        set2 = {PermissionVO.from_string("journal:create")}
        merged = PermissionUtils.merge_permissions(set1, set2)
        # Super admin covers everything, so only super admin remains
        result_strings = {p.to_string for p in merged}
        assert result_strings == {"*:*"}