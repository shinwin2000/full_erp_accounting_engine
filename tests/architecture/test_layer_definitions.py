# tests/architecture/test_layer_definitions.py
"""
Comprehensive tests for architecture/layer_definitions.py.

Covers:
- Layer enum: from_string, is_inner_than, is_outer_than, display_name, to_dict, etc.
- LayerDefinition: allows_dependency, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, matches
- Cache functions: get_layer_for_module, get_layer_for_file, is_allowed_import,
  get_allowed_imports_for_module, validate_layer_consistency, get_all_modules_with_layers,
  reset_cache, get_cache_stats
- Internal: _record_cache_audit (tested via side effects)
"""

from __future__ import annotations

import re

import pytest

from architecture.layer_definitions import (
    Layer,
    LayerDefinition,
    _cache_audit_trail,
    _module_layer_cache,
    _module_layer_cache_by_path,
    get_all_modules_with_layers,
    get_allowed_imports_for_module,
    get_cache_stats,
    get_layer_for_file,
    get_layer_for_module,
    is_allowed_import,
    reset_cache,
    validate_layer_consistency,
)

# ============================================================================
# Tests for Layer Enum
# ============================================================================

class TestLayer:
    def test_members(self):
        assert Layer.FOUNDATION.value == 0
        assert Layer.DOMAIN.value == 1
        assert Layer.APPLICATION.value == 2
        assert Layer.PORTS.value == 3
        assert Layer.ADAPTERS.value == 4
        assert Layer.INFRASTRUCTURE.value == 5
        assert Layer.EVENT_GATEWAY.value == 6
        assert Layer.PROJECTIONS.value == 7
        assert Layer.COMPLIANCE.value == 8
        assert Layer.TESTS.value == 9
        assert Layer.UNKNOWN.value == 99

    def test_display_name(self):
        assert Layer.FOUNDATION.display_name() == "Foundation (Constitution/Axioms/Kernel)"
        assert Layer.DOMAIN.display_name() == "Domain"
        assert Layer.UNKNOWN.display_name() == "Unknown"

    def test_from_string(self):
        assert Layer.from_string("FOUNDATION") == Layer.FOUNDATION
        assert Layer.from_string("domain") is None  # case sensitive
        assert Layer.from_string("NONEXISTENT") is None

    def test_is_inner_than(self):
        assert Layer.FOUNDATION.is_inner_than(Layer.DOMAIN) is True
        assert Layer.DOMAIN.is_inner_than(Layer.FOUNDATION) is False
        assert Layer.DOMAIN.is_inner_than(Layer.DOMAIN) is False  # equal

    def test_is_outer_than(self):
        assert Layer.ADAPTERS.is_outer_than(Layer.DOMAIN) is True
        assert Layer.DOMAIN.is_outer_than(Layer.ADAPTERS) is False
        assert Layer.DOMAIN.is_outer_than(Layer.DOMAIN) is False

    def test_validate(self):
        result = Layer.FOUNDATION.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self):
        d = Layer.FOUNDATION.to_dict()
        assert d["layer"] == "FOUNDATION"
        assert d["value"] == 0

    def test_from_dict(self):
        data = {"layer": "DOMAIN"}
        assert Layer.from_dict(data) == Layer.DOMAIN

    def test_clone(self):
        assert Layer.FOUNDATION.clone() == Layer.FOUNDATION

    def test_snapshot(self):
        snap = Layer.FOUNDATION.snapshot()
        assert snap["layer"] == "FOUNDATION"
        assert "timestamp" in snap

    def test_version(self):
        assert Layer.FOUNDATION.version() == 1

    def test_audit_trail(self):
        trail = Layer.FOUNDATION.audit_trail()
        assert len(trail) == 1
        assert trail[0]["layer"] == "FOUNDATION"

    def test_touch(self):
        touched = Layer.FOUNDATION.touch("user")
        assert touched == Layer.FOUNDATION


# ============================================================================
# Tests for LayerDefinition
# ============================================================================

class TestLayerDefinition:
    def test_construction(self):
        ld = LayerDefinition(
            layer=Layer.DOMAIN,
            module_patterns=[r"^domain/"],
            allowed_dependencies=[Layer.FOUNDATION],
            description="Test",
        )
        assert ld.layer == Layer.DOMAIN
        assert ld.module_patterns == [r"^domain/"]
        assert ld.allowed_dependencies == [Layer.FOUNDATION]
        assert ld.description == "Test"
        assert len(ld._compiled_patterns) == 1
        assert isinstance(ld._compiled_patterns[0], re.Pattern)

    def test_matches(self):
        ld = LayerDefinition(
            layer=Layer.DOMAIN,
            module_patterns=[r"^domain/", r"^some_module/"],
            allowed_dependencies=[],
        )
        assert ld.matches("domain/inventory/aggregate.py") is True
        assert ld.matches("some_module/thing.py") is True
        assert ld.matches("other/thing.py") is False

    def test_allows_dependency(self):
        ld = LayerDefinition(
            layer=Layer.APPLICATION,
            module_patterns=[r"^application/"],
            allowed_dependencies=[Layer.DOMAIN, Layer.FOUNDATION],
        )
        assert ld.allows_dependency(Layer.DOMAIN) is True
        assert ld.allows_dependency(Layer.FOUNDATION) is True
        assert ld.allows_dependency(Layer.ADAPTERS) is False

    def test_validate(self):
        ld = LayerDefinition(
            layer=Layer.DOMAIN,
            module_patterns=[r"^domain/", r"[invalid"],  # invalid regex
            allowed_dependencies=[Layer.FOUNDATION],
        )
        result = ld.validate()
        assert result["is_valid"] is False
        assert any("Invalid regex pattern" in err for err in result["errors"])

    def test_to_dict_and_from_dict(self):
        ld = LayerDefinition(
            layer=Layer.APPLICATION,
            module_patterns=[r"^application/"],
            allowed_dependencies=[Layer.DOMAIN, Layer.FOUNDATION],
            description="App layer",
        )
        d = ld.to_dict()
        assert d["layer"] == "APPLICATION"
        assert d["module_patterns"] == [r"^application/"]
        assert d["allowed_dependencies"] == ["DOMAIN", "FOUNDATION"]
        assert d["description"] == "App layer"
        assert "def_id" in d
        assert "version" in d

        restored = LayerDefinition.from_dict(d)
        assert restored.layer == Layer.APPLICATION
        assert restored.module_patterns == [r"^application/"]
        assert restored.allowed_dependencies == [Layer.DOMAIN, Layer.FOUNDATION]
        assert restored.description == "App layer"
        assert restored._def_id == d["def_id"]
        assert restored._version == d["version"]

    def test_clone(self):
        ld = LayerDefinition(
            layer=Layer.DOMAIN,
            module_patterns=[r"^domain/"],
            allowed_dependencies=[Layer.FOUNDATION],
            description="Original",
        )
        clone = ld.clone()
        assert clone.layer == ld.layer
        assert clone.module_patterns == ld.module_patterns
        assert clone.allowed_dependencies == ld.allowed_dependencies
        assert clone.description == ld.description
        assert clone._def_id != ld._def_id
        assert clone._version == ld._version + 1
        # Audit trail should have CLONE entry
        assert any(entry["action"] == "CLONE" for entry in clone.audit_trail())

    def test_snapshot(self):
        ld = LayerDefinition(
            layer=Layer.INFRASTRUCTURE,
            module_patterns=[r"^infrastructure/"],
            allowed_dependencies=[],
        )
        snap = ld.snapshot()
        assert snap["layer"] == "INFRASTRUCTURE"
        assert snap["patterns_count"] == 1
        assert "timestamp" in snap

    def test_version(self):
        ld = LayerDefinition(
            layer=Layer.DOMAIN,
            module_patterns=[r"^domain/"],
            allowed_dependencies=[],
        )
        assert ld.version() == 1
        ld.touch("user")
        assert ld.version() == 2

    def test_audit_trail(self):
        ld = LayerDefinition(
            layer=Layer.DOMAIN,
            module_patterns=[r"^domain/"],
            allowed_dependencies=[],
        )
        ld.touch("user1")
        ld.touch("user2")
        trail = ld.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "user1"
        assert trail[1]["action"] == "TOUCH"
        assert trail[1]["performed_by"] == "user2"

    def test_touch(self):
        ld = LayerDefinition(
            layer=Layer.DOMAIN,
            module_patterns=[r"^domain/"],
            allowed_dependencies=[],
        )
        old_version = ld._version
        touched = ld.touch("toucher")
        assert touched._version == old_version + 1
        assert any(entry["action"] == "TOUCH" for entry in touched.audit_trail())


# ============================================================================
# Tests for Cache Functions
# ============================================================================

class TestCacheFunctions:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Reset cache before each test and clear audit trail for isolation."""
        reset_cache()
        global _cache_audit_trail
        _cache_audit_trail.clear()
        _cache_version = 1
        yield
        reset_cache()

    def test_get_layer_for_module(self):
        # Known module should return correct layer
        layer = get_layer_for_module("domain/inventory/aggregate")
        assert layer == Layer.DOMAIN

        # Unknown module returns None
        layer2 = get_layer_for_module("unknown/module")
        assert layer2 is None

        # Check cache
        assert "domain/inventory/aggregate" in _module_layer_cache
        assert "unknown/module" in _module_layer_cache

    def test_get_layer_for_file(self, tmp_path):
        # Create fake file structure
        root = tmp_path / "project"
        root.mkdir()
        domain_file = root / "domain/inventory/aggregate.py"
        domain_file.parent.mkdir(parents=True)
        domain_file.touch()
        unknown_file = root / "unknown.py"
        unknown_file.touch()

        layer = get_layer_for_file(domain_file, root)
        assert layer == Layer.DOMAIN

        layer2 = get_layer_for_file(unknown_file, root)
        assert layer2 is None

        # Cache check
        assert domain_file in _module_layer_cache_by_path
        assert unknown_file in _module_layer_cache_by_path

    def test_get_layer_for_file_relative_error(self, tmp_path):
        # File outside root should return None
        outside = tmp_path / "outside.py"
        outside.touch()
        root = tmp_path / "project"
        root.mkdir()
        layer = get_layer_for_file(outside, root)
        assert layer is None

    def test_is_allowed_import(self):
        # Same layer -> allowed
        assert is_allowed_import("domain/inventory", "domain/order") is True
        # From inner to outer allowed (e.g., domain -> application is not allowed? Actually domain can only depend on foundation, so domain -> application should be False)
        # Check LAYER_DEFINITIONS: Domain only allows FOUNDATION, so domain -> application false
        assert is_allowed_import("domain/inventory", "application/use_case") is False
        # Application -> Domain is allowed because application depends on domain
        assert is_allowed_import("application/use_case", "domain/inventory") is True
        # Tests always allowed
        assert is_allowed_import("domain/inventory", "tests/test_inventory") is True
        # Unknown module -> False
        assert is_allowed_import("unknown", "domain") is False

    def test_get_allowed_imports_for_module(self):
        allowed = get_allowed_imports_for_module("domain/inventory")
        # Should return patterns from domain itself and its dependencies (foundation)
        # Domain layer's patterns: ^domain/, ^policy_engine/, ^legal/, ^ethics/
        # Plus foundation patterns: ^constitution/, ^axioms/, ^kernel/, ^reality/, ^intent/, ^causality/
        # We'll just check that some are present
        assert any("domain/" in p for p in allowed)
        assert any("kernel/" in p for p in allowed)
        # Should not include application/ or adapters/
        assert not any("application/" in p for p in allowed)
        assert not any("adapters/" in p for p in allowed)

        # Unknown module -> empty list
        assert get_allowed_imports_for_module("nonexistent") == []

    def test_validate_layer_consistency(self):
        issues = validate_layer_consistency()
        # There might be some overlaps in patterns; we just check it runs and returns a list
        assert isinstance(issues, list)
        # At least one overlap may exist, but we don't assert count

    def test_get_all_modules_with_layers(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        # Create a few python files
        (root / "domain").mkdir()
        (root / "domain" / "test.py").touch()
        (root / "application").mkdir()
        (root / "application" / "test.py").touch()
        (root / "unknown").mkdir()
        (root / "unknown" / "test.py").touch()

        results = get_all_modules_with_layers(str(root))
        # Should include the two known modules, unknown module will have None
        modules = [m for m, _ in results]
        assert "domain.test" in modules
        assert "application.test" in modules
        assert "unknown.test" in modules

        # Check layers
        for module, layer in results:
            if module == "domain.test":
                assert layer == Layer.DOMAIN
            elif module == "application.test":
                assert layer == Layer.APPLICATION
            else:
                assert layer is None

    def test_reset_cache(self):
        # Populate cache
        get_layer_for_module("domain/test")
        assert len(_module_layer_cache) > 0
        reset_cache()
        assert len(_module_layer_cache) == 0
        assert len(_module_layer_cache_by_path) == 0
        # Audit trail should have RESET_CACHE entry
        global _cache_audit_trail
        assert any(entry["action"] == "RESET_CACHE" for entry in _cache_audit_trail)

    def test_get_cache_stats(self):
        stats = get_cache_stats()
        assert "cache_version" in stats
        assert "module_cache_size" in stats
        assert "file_cache_size" in stats
        assert "audit_trail_size" in stats

    def test_record_cache_audit(self):
        # We test via side effects from other functions; but we can directly call _record_cache_audit to ensure it works.
        from architecture.layer_definitions import _record_cache_audit
        _record_cache_audit("TEST", {"foo": "bar"})
        global _cache_audit_trail
        assert any(entry["action"] == "TEST" for entry in _cache_audit_trail)
        # Test limit trimming: we can add many entries and check length
        for i in range(1500):
            _record_cache_audit(f"ENTRY_{i}", {})
        # Should be limited to 1000
        assert len(_cache_audit_trail) <= 1000
