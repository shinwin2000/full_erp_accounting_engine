# tests/policy_engine/test_jurisdiction_resolver.py
"""
Comprehensive unit tests for policy_engine/jurisdiction_resolver.py.
Covers all public methods, exceptions, and edge cases with mocked dependencies.
"""

import json
import tempfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from policy_engine.jurisdiction_resolver import (
    DEFAULT_COUNTRY,
    DEFAULT_GLOBAL_JURISDICTION,
    JurisdictionHierarchy,
    JurisdictionNode,
    JurisdictionResolver,
    get_jurisdiction_resolver,
)
from policy_engine.policy_exceptions import JurisdictionResolutionError


# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("policy_engine.jurisdiction_resolver.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Tests for JurisdictionNode
# ============================================================================

class TestJurisdictionNode:
    def test_construction(self):
        node = JurisdictionNode(
            code="ID",
            name="Indonesia",
            parent_code="GLOBAL",
            level=1,
            metadata={"key": "value"},
        )
        assert node.code == "ID"
        assert node.name == "Indonesia"
        assert node.parent_code == "GLOBAL"
        assert node.level == 1
        assert node.metadata == {"key": "value"}

    def test_is_descendant_of(self):
        hierarchy = JurisdictionHierarchy()
        node_id = JurisdictionNode("ID-JKT-PST", "Jakarta Pusat", parent_code="ID-JKT", level=3)
        # We need a hierarchy to check
        # Use a mock hierarchy
        mock_hierarchy = MagicMock()
        mock_hierarchy.is_descendant.return_value = True
        assert node_id.is_descendant_of(JurisdictionNode("ID-JKT", "Jakarta"), mock_hierarchy) is True
        mock_hierarchy.is_descendant.assert_called_once_with("ID-JKT-PST", "ID-JKT")
        # Test false
        mock_hierarchy.is_descendant.return_value = False
        assert node_id.is_descendant_of(JurisdictionNode("ID-JBT", "Jawa Barat"), mock_hierarchy) is False


# ============================================================================
# Tests for JurisdictionHierarchy
# ============================================================================

class TestJurisdictionHierarchy:
    @pytest.fixture
    def hierarchy(self):
        return JurisdictionHierarchy()

    def test_singleton(self):
        h1 = JurisdictionHierarchy()
        h2 = JurisdictionHierarchy()
        assert h1 is h2

    def test_initialization_contains_defaults(self, hierarchy):
        assert hierarchy.get_node("GLOBAL") is not None
        assert hierarchy.get_node("ID") is not None
        assert hierarchy.get_node("SG") is not None
        assert hierarchy.get_node("ID-JKT") is not None
        assert hierarchy.get_node("ID-JKT-PST") is not None
        assert hierarchy.get_node("IND-MANUFACTURING") is not None

    def test_add_node_new(self, hierarchy):
        node = JurisdictionNode("TEST", "Test", parent_code="GLOBAL", level=1)
        hierarchy.add_node(node)
        assert hierarchy.get_node("TEST") is node
        assert "TEST" in hierarchy._children["GLOBAL"]

    def test_add_node_duplicate_skip(self, hierarchy, caplog):
        node = JurisdictionNode("ID", "Indonesia", parent_code="GLOBAL", level=1)
        with caplog.at_level("WARNING"):
            hierarchy.add_node(node)
        assert "already exists" in caplog.text

    def test_get_node(self, hierarchy):
        assert hierarchy.get_node("ID") is not None
        assert hierarchy.get_node("NONEXISTENT") is None

    def test_get_parent(self, hierarchy):
        parent = hierarchy.get_parent("ID-JKT")
        assert parent is not None
        assert parent.code == "ID"
        # No parent for root
        assert hierarchy.get_parent("GLOBAL") is None

    def test_get_ancestors(self, hierarchy):
        ancestors = hierarchy.get_ancestors("ID-JKT-PST")
        assert len(ancestors) >= 2
        assert ancestors[0].code == "ID-JKT"
        assert ancestors[1].code == "ID"
        # include_self
        ancestors_with_self = hierarchy.get_ancestors("ID-JKT-PST", include_self=True)
        assert ancestors_with_self[0].code == "ID-JKT-PST"

    def test_get_descendants(self, hierarchy):
        # Descendants of ID
        descendants = hierarchy.get_descendants("ID")
        assert "ID-JKT" in [d.code for d in descendants]
        assert "ID-JKT-PST" in [d.code for d in descendants]
        assert "ID-JBT" in [d.code for d in descendants]
        # include_self
        descendants_self = hierarchy.get_descendants("ID", include_self=True)
        assert descendants_self[0].code == "ID"

    def test_get_children(self, hierarchy):
        children = hierarchy.get_children("ID")
        child_codes = [c.code for c in children]
        assert "ID-JKT" in child_codes
        assert "ID-JBT" in child_codes
        assert "IND-MANUFACTURING" not in child_codes  # it's under GLOBAL

    def test_is_descendant(self, hierarchy):
        assert hierarchy.is_descendant("ID-JKT-PST", "ID") is True
        assert hierarchy.is_descendant("ID-JKT-PST", "GLOBAL") is True
        assert hierarchy.is_descendant("ID-JKT", "ID-JKT-PST") is False
        assert hierarchy.is_descendant("ID-JKT-PST", "ID-JKT-PST") is True

    def test_get_level(self, hierarchy):
        assert hierarchy.get_level("GLOBAL") == 0
        assert hierarchy.get_level("ID") == 1
        assert hierarchy.get_level("ID-JKT") == 2
        assert hierarchy.get_level("ID-JKT-PST") == 3
        assert hierarchy.get_level("IND-MANUFACTURING") == 4
        assert hierarchy.get_level("NONEXISTENT") == -1

    def test_get_all_codes(self, hierarchy):
        codes = hierarchy.get_all_codes()
        assert "GLOBAL" in codes
        assert "ID" in codes
        assert len(codes) > 10

    def test_get_root(self, hierarchy):
        root = hierarchy.get_root()
        assert root is not None
        assert root.code == "GLOBAL"

    def test_export_to_json(self, hierarchy):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            hierarchy.export_to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert "nodes" in data
            assert "GLOBAL" in data["nodes"]
            assert data["nodes"]["GLOBAL"]["name"] == "Global"
        finally:
            import os
            os.remove(file_path)

    def test_import_from_json(self, hierarchy):
        data = {
            "nodes": {
                "CUSTOM": {"name": "Custom", "parent": "GLOBAL", "level": 1, "metadata": {}}
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            file_path = f.name
        try:
            hierarchy.import_from_json(file_path)
            assert hierarchy.get_node("CUSTOM") is not None
            assert hierarchy.get_node("CUSTOM").name == "Custom"
        finally:
            import os
            os.remove(file_path)


# ============================================================================
# Tests for JurisdictionResolver
# ============================================================================

class TestJurisdictionResolver:
    @pytest.fixture
    def mock_loader(self):
        loader = MagicMock()
        # Mock policies
        policy1 = MagicMock()
        policy1.id = "p1"
        policy1.jurisdiction = "ID-JKT"
        policy2 = MagicMock()
        policy2.id = "p2"
        policy2.jurisdiction = "ID"
        # get_policies_by_domain returns list for given jurisdiction
        def get_policies_by_domain(domain, as_of, jurisdiction):
            if jurisdiction == "ID-JKT":
                return [policy1]
            elif jurisdiction == "ID":
                return [policy2]
            elif jurisdiction == "GLOBAL":
                return []
            return []
        loader.get_policies_by_domain.side_effect = get_policies_by_domain
        loader.get_all_jurisdictions.return_value = ["ID-JKT", "ID", "GLOBAL"]
        return loader

    @pytest.fixture
    def resolver(self, mock_loader):
        with patch("policy_engine.jurisdiction_resolver.get_policy_loader", return_value=mock_loader):
            resolver = JurisdictionResolver()
            resolver._loader = mock_loader
            # Override hierarchy to avoid side effects
            # We'll keep default hierarchy
            return resolver

    def test_singleton(self):
        r1 = JurisdictionResolver()
        r2 = JurisdictionResolver()
        assert r1 is r2

    def test_resolve_policies(self, resolver):
        # Resolve for ID-JKT
        policies = resolver.resolve_policies("tax", "ID-JKT", FIXED_NOW)
        # Should get policy1 (ID-JKT) and policy2 (ID) because ancestors include ID
        # No GLOBAL policy
        assert len(policies) == 2
        assert policies[0].id == "p1"  # most specific first? In resolve_policies, it uses _get_relevant_jurisdictions which returns [entity, ancestors, GLOBAL], then extends.
        # Actually it just appends in that order, so order is [ID-JKT, ID, GLOBAL], but then unique.
        # So first is ID-JKT.
        policy_ids = [p.id for p in policies]
        assert "p1" in policy_ids
        assert "p2" in policy_ids

        # Cache
        policies2 = resolver.resolve_policies("tax", "ID-JKT", FIXED_NOW)
        assert policies2 == policies
        # Different domain or date should not use cache
        policies3 = resolver.resolve_policies("other", "ID-JKT", FIXED_NOW)
        # get_policies_by_domain called with domain="other" should return empty? Our mock returns [] for other.
        # It will call the mock with domain="other", but our mock doesn't handle that, so returns [].
        assert len(policies3) == 0

    def test_resolve_policies_global_fallback(self, resolver):
        # If no specific policy, should fallback to GLOBAL if any policy exists.
        # Modify mock to return global policy
        global_policy = MagicMock()
        global_policy.id = "global"
        global_policy.jurisdiction = "GLOBAL"
        resolver._loader.get_policies_by_domain.side_effect = lambda domain, as_of, jurisdiction: (
            [global_policy] if jurisdiction == "GLOBAL" else []
        )
        policies = resolver.resolve_policies("tax", "ID-JKT", FIXED_NOW)
        assert len(policies) == 1
        assert policies[0].id == "global"

    def test_get_relevant_jurisdictions(self, resolver):
        jurisdictions = resolver._get_relevant_jurisdictions("ID-JKT-PST")
        # Expected: ID-JKT-PST, ID-JKT, ID, GLOBAL
        assert jurisdictions == ["ID-JKT-PST", "ID-JKT", "ID", "GLOBAL"]
        # For root
        jurisdictions2 = resolver._get_relevant_jurisdictions("GLOBAL")
        assert jurisdictions2 == ["GLOBAL"]

    def test_get_primary_policy(self, resolver):
        # Should return the most specific policy
        primary = resolver.get_primary_policy("tax", "ID-JKT", FIXED_NOW)
        # Most specific is ID-JKT (level 2) vs ID (level 1)
        assert primary is not None
        assert primary.id == "p1"  # from mock
        # If no policies, return None
        resolver._loader.get_policies_by_domain.return_value = []
        primary2 = resolver.get_primary_policy("tax", "ID-JKT", FIXED_NOW)
        assert primary2 is None

    def test_get_applicable_jurisdictions(self, resolver):
        jurisdictions = resolver.get_applicable_jurisdictions("tax", FIXED_NOW)
        # Our mock returns ID-JKT and ID as having policies, GLOBAL empty
        assert set(jurisdictions) == {"ID-JKT", "ID"}

    def test_validate_jurisdiction(self, resolver):
        assert resolver.validate_jurisdiction("ID") is True
        assert resolver.validate_jurisdiction("NONEXISTENT") is False

    def test_resolve_jurisdiction_for_entity(self, resolver):
        # Simple country
        assert resolver.resolve_jurisdiction_for_entity("ID") == "ID"
        # With region and city
        assert resolver.resolve_jurisdiction_for_entity("ID", "JKT", "PST") == "ID-JKT-PST"
        # With industry
        assert resolver.resolve_jurisdiction_for_entity("ID", "JBT", "BDG", "MANUFACTURING") == "ID-JBT-BDG-MANUFACTURING"
        # Case handling: should uppercase
        assert resolver.resolve_jurisdiction_for_entity("id", "jkt", "pst") == "ID-JKT-PST"

    def test_get_jurisdiction_info(self, resolver):
        info = resolver.get_jurisdiction_info("ID-JKT")
        assert info["code"] == "ID-JKT"
        assert info["name"] == "DKI Jakarta"
        assert info["parent_code"] == "ID"
        assert info["level"] == 2
        assert "ancestors" in info
        assert "descendants" in info
        with pytest.raises(JurisdictionResolutionError, match="Jurisdiction not found"):
            resolver.get_jurisdiction_info("NONEXISTENT")

    def test_add_jurisdiction(self, resolver):
        # Add new
        resolver.add_jurisdiction("TEST", "Test", "GLOBAL", level=1)
        assert resolver.validate_jurisdiction("TEST") is True
        # Add with invalid parent
        with pytest.raises(JurisdictionResolutionError, match="Parent jurisdiction not found"):
            resolver.add_jurisdiction("BAD", "Bad", "NONEXISTENT")

    def test_is_jurisdiction_active(self, resolver):
        # Uses loader to check any policies
        resolver._loader.get_policies_by_domain.return_value = [MagicMock()]
        assert resolver.is_jurisdiction_active("ID-JKT") is True
        resolver._loader.get_policies_by_domain.return_value = []
        assert resolver.is_jurisdiction_active("ID-JKT") is False

    def test_clear_cache(self, resolver):
        resolver._resolution_cache["key"] = "value"
        resolver.clear_cache()
        assert resolver._resolution_cache == {}

    def test_record_resolution(self, resolver):
        policy = MagicMock()
        policy.id = "p1"
        resolver._record_resolution("tax", "ID-JKT", [policy])
        history = resolver.get_resolution_history()
        assert len(history) == 1
        assert history[0]["domain"] == "tax"
        assert history[0]["jurisdiction"] == "ID-JKT"
        assert history[0]["policy_count"] == 1
        assert history[0]["policy_ids"] == ["p1"]

    def test_get_resolution_history_limit(self, resolver):
        # Add more than limit
        for i in range(150):
            policy = MagicMock()
            policy.id = f"p{i}"
            resolver._record_resolution("tax", "ID", [policy])
        history = resolver.get_resolution_history(limit=100)
        assert len(history) == 100

    def test_generate_report(self, resolver):
        report = resolver.generate_report()
        assert "total_jurisdictions" in report
        assert "hierarchy" in report
        assert "cache_size" in report
        assert "resolution_history_count" in report

    def test_export_to_json(self, resolver):
        resolver._record_resolution("tax", "ID-JKT", [])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            resolver.export_to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert "report" in data
            assert "history" in data
            assert "hierarchy" in data
        finally:
            import os
            os.remove(file_path)

    def test_get_jurisdiction_level(self, resolver):
        assert resolver.get_jurisdiction_level("ID") == 1
        assert resolver.get_jurisdiction_level("NONEXISTENT") == -1

    def test_is_parent(self, resolver):
        assert resolver.is_parent("ID", "ID-JKT") is True
        assert resolver.is_parent("ID-JKT", "ID") is False

    # ---- Test compatibility method resolve ----
    def test_resolve_method(self, resolver):
        # NPWP prefix 123 -> Indonesia
        result = resolver.resolve(npwp="123456789012345")
        assert result.country == "Indonesia"
        assert result.tax_regime == "general"
        # NPWP prefix 456 -> Indonesia
        result2 = resolver.resolve(npwp="456789012345")
        assert result2.country == "Indonesia"
        # Other prefix -> Indonesia default? The method only checks 123/456; else Indonesia general.
        result3 = resolver.resolve(npwp="999")
        assert result3.country == "Indonesia"
        # Address with Singapore -> Singapore foreign
        result4 = resolver.resolve(address="123 Singapore Road")
        assert result4.country == "Singapore"
        assert result4.tax_regime == "foreign"
        # Address without Singapore -> Indonesia (default)
        result5 = resolver.resolve(address="Jakarta")
        assert result5.country == "Indonesia"

    # ---- Test with real hierarchy interaction (integration-ish) ----
    def test_resolve_policies_with_real_hierarchy(self):
        # We need a real hierarchy to test
        # But we need to mock the loader to avoid external dependencies.
        with patch("policy_engine.jurisdiction_resolver.get_policy_loader") as mock_loader:
            loader = MagicMock()
            # Define policies for some jurisdictions
            policy_jkt = MagicMock()
            policy_jkt.id = "jkt"
            policy_jkt.jurisdiction = "ID-JKT"
            policy_id = MagicMock()
            policy_id.id = "id"
            policy_id.jurisdiction = "ID"
            def get_policies(domain, as_of, jurisdiction):
                if jurisdiction == "ID-JKT":
                    return [policy_jkt]
                elif jurisdiction == "ID":
                    return [policy_id]
                else:
                    return []
            loader.get_policies_by_domain.side_effect = get_policies
            mock_loader.return_value = loader

            resolver = JurisdictionResolver()
            # Use real hierarchy
            policies = resolver.resolve_policies("tax", "ID-JKT-PST", FIXED_NOW)
            # Should get ID-JKT and ID (both ancestors)
            assert len(policies) == 2
            policy_ids = [p.id for p in policies]
            assert "jkt" in policy_ids
            assert "id" in policy_ids

    # ---- Edge case: no ancestors for root ----
    def test_resolve_policies_root(self, resolver):
        # For GLOBAL, only GLOBAL policies
        global_policy = MagicMock()
        global_policy.id = "global"
        resolver._loader.get_policies_by_domain.side_effect = lambda domain, as_of, jurisdiction: (
            [global_policy] if jurisdiction == "GLOBAL" else []
        )
        policies = resolver.resolve_policies("tax", "GLOBAL", FIXED_NOW)
        assert len(policies) == 1
        assert policies[0].id == "global"

    # ---- Test caching invalidation ----
    def test_cache_invalidation_on_add_jurisdiction(self, resolver):
        resolver._resolution_cache["key"] = "value"
        resolver.add_jurisdiction("TEST", "Test", "GLOBAL")
        assert resolver._resolution_cache == {}  # cleared

    # ---- Test history trimming ----
    def test_history_trimming(self, resolver):
        for i in range(1200):
            resolver._record_resolution("tax", "ID", [MagicMock()])
        assert len(resolver._history) == 500  # max 500