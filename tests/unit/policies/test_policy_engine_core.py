#!/usr/bin/env python3
"""
Module: test_policy_engine_core.py
Layer: Tests / Unit / Policies

Responsibility:
    Unit tests untuk core policy engine (loader, interpreter, resolver).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from policy_engine.cache_engine import PolicyCacheEngine
from policy_engine.conflict_resolver import ConflictResolver
from policy_engine.interpreter import PolicyInterpreter
from policy_engine.jurisdiction_resolver import JurisdictionResolver
from policy_engine.loader_yaml import PolicyLoader
from policy_engine.temporal_resolver import TemporalResolver
from policy_engine.version_manager import PolicyVersionManager


class TestPolicyLoader:
    """Loader kebijakan dari YAML."""

    def test_load_policy_from_file(self, tmp_path):
        yaml_content = """
        policy_id: TAX_PPH21_2025
        effective_date: 2025-01-01
        rules:
          - condition: "gross_monthly > 10000000"
            action: "apply_rate 0.02"
        """
        file_path = tmp_path / "policy.yaml"
        file_path.write_text(yaml_content)
        loader = PolicyLoader()
        policy = loader.load(file_path)
        assert policy.policy_id == "TAX_PPH21_2025"
        assert len(policy.rules) == 1

    def test_load_policy_invalid_yaml(self, tmp_path):
        file_path = tmp_path / "invalid.yaml"
        file_path.write_text("invalid: : yaml")
        loader = PolicyLoader()
        with pytest.raises(ValueError, match="YAML"):
            loader.load(file_path)


class TestPolicyInterpreter:
    """Interpreter kebijakan."""

    def test_evaluate_condition_true(self):
        interpreter = PolicyInterpreter()
        context = {"gross_monthly": Decimal("15000000")}
        result = interpreter.evaluate_condition("gross_monthly > 10000000", context)
        assert result is True

    def test_evaluate_condition_false(self):
        interpreter = PolicyInterpreter()
        context = {"gross_monthly": Decimal("5000000")}
        result = interpreter.evaluate_condition("gross_monthly > 10000000", context)
        assert result is False

    def test_execute_action(self):
        interpreter = PolicyInterpreter()
        context = {}
        result = interpreter.execute_action("apply_rate 0.02", context)
        assert result["rate"] == Decimal("0.02")


class TestJurisdictionResolver:
    """Resolver yurisdiksi pajak."""

    def test_resolve_jurisdiction_by_npwp(self):
        resolver = JurisdictionResolver()
        jurisdiction = resolver.resolve(npwp="123456789012345")
        assert jurisdiction.country == "Indonesia"
        assert jurisdiction.tax_regime == "general"

    def test_resolve_jurisdiction_fallback(self):
        resolver = JurisdictionResolver()
        jurisdiction = resolver.resolve(npwp=None, address="Singapore")
        assert jurisdiction.country == "Singapore"


class TestTemporalResolver:
    """Resolver temporal untuk kebijakan berdasar waktu."""

    def test_get_effective_policy_at_date(self):
        resolver = TemporalResolver()
        policies = [
            {"id": "P1", "effective_date": date(2024, 1, 1), "end_date": date(2024, 12, 31)},
            {"id": "P2", "effective_date": date(2025, 1, 1), "end_date": None},
        ]
        effective = resolver.get_effective_policy(policies, as_of=date(2024, 6, 1))
        assert effective["id"] == "P1"
        effective2 = resolver.get_effective_policy(policies, as_of=date(2025, 3, 1))
        assert effective2["id"] == "P2"


class TestPolicyVersionManager:
    """Manajemen versi kebijakan."""

    def test_version_increment(self):
        manager = PolicyVersionManager()
        current = manager.get_version("POLICY_001")
        assert current == 1
        new_version = manager.increment_version("POLICY_001")
        assert new_version == 2

    def test_version_rollback(self):
        manager = PolicyVersionManager()
        manager.increment_version("POLICY_001")
        manager.rollback("POLICY_001")
        assert manager.get_version("POLICY_001") == 1


class TestPolicyCacheEngine:
    """Cache engine untuk kebijakan."""

    def test_cache_get_set(self):
        cache = PolicyCacheEngine()
        cache.set("key1", {"value": 100})
        cached = cache.get("key1")
        assert cached["value"] == 100

    def test_cache_expiry(self):
        cache = PolicyCacheEngine(default_ttl=0.1)
        cache.set("temp", "data")
        import time

        time.sleep(0.2)
        assert cache.get("temp") is None


class TestConflictResolver:
    """Resolver konflik antar kebijakan."""

    def test_resolve_highest_priority_wins(self):
        resolver = ConflictResolver()
        policies = [
            {"id": "P1", "priority": 1, "rule": "tax_rate=0.11"},
            {"id": "P2", "priority": 2, "rule": "tax_rate=0.10"},
        ]
        resolved = resolver.resolve(policies)
        assert resolved["rule"] == "tax_rate=0.10"  # priority 2 wins

    def test_resolve_most_specific_wins(self):
        resolver = ConflictResolver()
        policies = [
            {"id": "P1", "specificity": 1, "rule": "general"},
            {"id": "P2", "specificity": 3, "rule": "specific"},
        ]
        resolved = resolver.resolve(policies, method="specificity")
        assert resolved["rule"] == "specific"
