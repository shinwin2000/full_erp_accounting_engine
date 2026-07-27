# tests/policy_engine/test_conflict_resolver.py
# Comprehensive tests for policy_engine/conflict_resolver.py

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from policy_engine.conflict_resolver import (
    Conflict,
    ConflictDetector,
    ConflictResolver,
    ConflictSeverity,
    ConflictType,
    ResolutionStrategy,
    get_conflict_resolver,
)
from policy_engine.policy_exceptions import PolicyConflictError


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_policy_set():
    """Create a mock PolicySet."""
    policy = MagicMock()
    policy.id = "policy_1"
    policy.name = "Policy 1"
    policy.domain = "tax"
    policy.version = 1
    policy.effective_from = datetime(2025, 1, 1, tzinfo=UTC)
    policy.effective_to = None
    policy.jurisdiction = "ID"
    policy.metadata = {"priority": 10}
    policy.rules = []
    return policy


@pytest.fixture
def sample_policy_set_2():
    policy = MagicMock()
    policy.id = "policy_2"
    policy.name = "Policy 2"
    policy.domain = "tax"
    policy.version = 2
    policy.effective_from = datetime(2025, 6, 1, tzinfo=UTC)
    policy.effective_to = None
    policy.jurisdiction = "ID-JKT"
    policy.metadata = {"priority": 20}
    policy.rules = []
    return policy


@pytest.fixture
def sample_policies(sample_policy_set, sample_policy_set_2):
    return [sample_policy_set, sample_policy_set_2]


@pytest.fixture
def sample_rule():
    rule = MagicMock()
    rule.id = "rule_1"
    rule.name = "Rule 1"
    rule.condition = "amount > 1000"
    rule.action = "approve"
    rule.enabled = True
    rule.priority = 5
    return rule


@pytest.fixture
def sample_rule_2():
    rule = MagicMock()
    rule.id = "rule_2"
    rule.name = "Rule 2"
    rule.condition = "amount > 1000"
    rule.action = "reject"
    rule.enabled = True
    rule.priority = 5
    return rule


@pytest.fixture
def sample_conflict():
    return Conflict(
        conflict_id="conflict_1",
        conflict_type=ConflictType.DUPLICATE_CONDITION,
        severity=ConflictSeverity.HIGH,
        description="Test conflict",
        policy_ids=["policy_1", "policy_2"],
        rule_ids=["rule_1", "rule_2"],
        details={"condition": "amount > 1000", "actions": ["approve", "reject"]},
    )


@pytest.fixture
def resolver():
    # Reset singleton for clean tests
    import policy_engine.conflict_resolver as module
    module._conflict_resolver_instance = None
    return get_conflict_resolver()


# ============================================================================
# Tests for Enums
# ============================================================================

class TestConflictType:
    def test_members_exist(self):
        assert hasattr(ConflictType, 'DUPLICATE_CONDITION')
        assert hasattr(ConflictType, 'CONTRADICTORY_ACTION')
        assert hasattr(ConflictType, 'CIRCULAR_DEPENDENCY')
        assert hasattr(ConflictType, 'PRIORITY_AMBIGUITY')
        assert hasattr(ConflictType, 'VERSION_CONFLICT')
        assert hasattr(ConflictType, 'JURISDICTION_OVERLAP')
        assert hasattr(ConflictType, 'TEMPORAL_OVERLAP')

    def test_member_is_instance(self):
        assert isinstance(ConflictType.DUPLICATE_CONDITION, ConflictType)


class TestResolutionStrategy:
    def test_members_exist(self):
        assert hasattr(ResolutionStrategy, 'HIGHEST_PRIORITY')
        assert hasattr(ResolutionStrategy, 'LATEST_VERSION')
        assert hasattr(ResolutionStrategy, 'MOST_SPECIFIC')
        assert hasattr(ResolutionStrategy, 'MANUAL_OVERRIDE')
        assert hasattr(ResolutionStrategy, 'MERGE_ACTIONS')
        assert hasattr(ResolutionStrategy, 'HIGHEST_SEVERITY')
        assert hasattr(ResolutionStrategy, 'NEWEST_EFFECTIVE')
        assert hasattr(ResolutionStrategy, 'CUSTOM')

    def test_member_is_instance(self):
        assert isinstance(ResolutionStrategy.HIGHEST_PRIORITY, ResolutionStrategy)


class TestConflictSeverity:
    def test_members_exist(self):
        assert hasattr(ConflictSeverity, 'LOW')
        assert hasattr(ConflictSeverity, 'MEDIUM')
        assert hasattr(ConflictSeverity, 'HIGH')
        assert hasattr(ConflictSeverity, 'CRITICAL')

    def test_member_is_instance(self):
        assert isinstance(ConflictSeverity.LOW, ConflictSeverity)


# ============================================================================
# Tests for Conflict
# ============================================================================

class TestConflict:
    def test_construction(self, sample_conflict):
        assert sample_conflict.conflict_id == "conflict_1"
        assert sample_conflict.conflict_type == ConflictType.DUPLICATE_CONDITION
        assert sample_conflict.severity == ConflictSeverity.HIGH
        assert sample_conflict.resolved is False
        assert sample_conflict.detected_at is not None

    def test_to_dict(self, sample_conflict):
        d = sample_conflict.to_dict()
        assert d["conflict_id"] == "conflict_1"
        assert d["type"] == "duplicate_condition"
        assert d["severity"] == "high"
        assert d["description"] == "Test conflict"
        assert d["policy_ids"] == ["policy_1", "policy_2"]
        assert d["rule_ids"] == ["rule_1", "rule_2"]
        assert d["resolved"] is False
        assert "detected_at" in d

    def test_resolve(self, sample_conflict):
        sample_conflict.resolve(
            strategy=ResolutionStrategy.HIGHEST_PRIORITY,
            result="policy_1",
            resolved_by="admin"
        )
        assert sample_conflict.resolved is True
        assert sample_conflict.resolution_strategy == ResolutionStrategy.HIGHEST_PRIORITY
        assert sample_conflict.resolution_result == "policy_1"
        assert sample_conflict.resolved_by == "admin"
        assert sample_conflict.resolved_at is not None


# ============================================================================
# Tests for ConflictDetector
# ============================================================================

class TestConflictDetector:
    def test_detect_duplicate_conditions(self, sample_policy_set, sample_policy_set_2,
                                          sample_rule, sample_rule_2):
        # Set up rules
        sample_policy_set.rules = [sample_rule]
        sample_policy_set_2.rules = [sample_rule_2]
        policies = [sample_policy_set, sample_policy_set_2]

        conflicts = ConflictDetector.detect_duplicate_conditions(policies)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.DUPLICATE_CONDITION
        assert "Duplicate condition" in conflicts[0].description
        assert conflicts[0].policy_ids == ["policy_1", "policy_2"]
        assert conflicts[0].rule_ids == ["rule_1", "rule_2"]

    def test_detect_duplicate_conditions_no_conflict(self, sample_policy_set, sample_rule):
        sample_policy_set.rules = [sample_rule]
        policies = [sample_policy_set]
        conflicts = ConflictDetector.detect_duplicate_conditions(policies)
        assert len(conflicts) == 0

    def test_detect_duplicate_conditions_disabled_rule(self, sample_policy_set, sample_policy_set_2,
                                                       sample_rule, sample_rule_2):
        sample_rule.enabled = False  # disabled
        sample_policy_set.rules = [sample_rule]
        sample_policy_set_2.rules = [sample_rule_2]
        policies = [sample_policy_set, sample_policy_set_2]
        conflicts = ConflictDetector.detect_duplicate_conditions(policies)
        # Only rule_2 is enabled, so no conflict
        assert len(conflicts) == 0

    def test_detect_priority_ambiguity(self, sample_policy_set, sample_policy_set_2):
        # Both have same priority (10)
        sample_policy_set.metadata = {"priority": 10}
        sample_policy_set_2.metadata = {"priority": 10}
        policies = [sample_policy_set, sample_policy_set_2]

        conflicts = ConflictDetector.detect_priority_ambiguity(policies)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.PRIORITY_AMBIGUITY
        assert "same priority" in conflicts[0].description
        assert conflicts[0].policy_ids == ["policy_1", "policy_2"]

    def test_detect_priority_ambiguity_different_priority(self, sample_policy_set, sample_policy_set_2):
        sample_policy_set.metadata = {"priority": 10}
        sample_policy_set_2.metadata = {"priority": 20}
        policies = [sample_policy_set, sample_policy_set_2]
        conflicts = ConflictDetector.detect_priority_ambiguity(policies)
        assert len(conflicts) == 0

    def test_detect_temporal_overlap(self, sample_policy_set, sample_policy_set_2):
        # Both effective from Jan and Jun 2025, no end date -> overlap
        policies = [sample_policy_set, sample_policy_set_2]
        conflicts = ConflictDetector.detect_temporal_overlap(policies)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.TEMPORAL_OVERLAP
        assert "Temporal overlap" in conflicts[0].description

    def test_detect_temporal_overlap_no_overlap(self, sample_policy_set, sample_policy_set_2):
        sample_policy_set.effective_to = datetime(2025, 5, 31, tzinfo=UTC)
        sample_policy_set_2.effective_from = datetime(2025, 6, 1, tzinfo=UTC)
        policies = [sample_policy_set, sample_policy_set_2]
        conflicts = ConflictDetector.detect_temporal_overlap(policies)
        assert len(conflicts) == 0

    def test_detect_jurisdiction_overlap(self, sample_policy_set, sample_policy_set_2):
        # ID and ID-JKT overlap
        policies = [sample_policy_set, sample_policy_set_2]
        conflicts = ConflictDetector.detect_jurisdiction_overlap(policies)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.JURISDICTION_OVERLAP
        assert "Jurisdiction overlap" in conflicts[0].description

    def test_detect_jurisdiction_overlap_no_overlap(self, sample_policy_set, sample_policy_set_2):
        sample_policy_set.jurisdiction = "ID"
        sample_policy_set_2.jurisdiction = "SG"  # Singapore, no overlap
        policies = [sample_policy_set, sample_policy_set_2]
        conflicts = ConflictDetector.detect_jurisdiction_overlap(policies)
        assert len(conflicts) == 0

    def test_detect_all(self, sample_policy_set, sample_policy_set_2,
                        sample_rule, sample_rule_2):
        sample_policy_set.rules = [sample_rule]
        sample_policy_set_2.rules = [sample_rule_2]
        sample_policy_set.metadata = {"priority": 10}
        sample_policy_set_2.metadata = {"priority": 10}
        policies = [sample_policy_set, sample_policy_set_2]

        conflicts = ConflictDetector.detect_all(policies)
        # Should detect duplicate condition, priority ambiguity, temporal overlap, jurisdiction overlap
        # At least 3 types
        assert len(conflicts) >= 3
        conflict_types = {c.conflict_type for c in conflicts}
        assert ConflictType.DUPLICATE_CONDITION in conflict_types
        assert ConflictType.PRIORITY_AMBIGUITY in conflict_types
        assert ConflictType.TEMPORAL_OVERLAP in conflict_types
        assert ConflictType.JURISDICTION_OVERLAP in conflict_types

    # ---- Direct call to detect_all to ensure coverage detection ----
    def test_detect_all_direct(self, sample_policy_set, sample_policy_set_2,
                               sample_rule, sample_rule_2):
        sample_policy_set.rules = [sample_rule]
        sample_policy_set_2.rules = [sample_rule_2]
        sample_policy_set.metadata = {"priority": 10}
        sample_policy_set_2.metadata = {"priority": 10}
        policies = [sample_policy_set, sample_policy_set_2]
        conflicts = ConflictDetector.detect_all(policies)
        assert len(conflicts) > 0


# ============================================================================
# Tests for ConflictResolver
# ============================================================================

class TestConflictResolver:
    def test_singleton(self):
        r1 = get_conflict_resolver()
        r2 = get_conflict_resolver()
        assert r1 is r2

    def test_detect_conflicts(self, resolver, sample_policies, sample_rule, sample_rule_2):
        sample_policies[0].rules = [sample_rule]
        sample_policies[1].rules = [sample_rule_2]
        sample_policies[0].metadata = {"priority": 10}
        sample_policies[1].metadata = {"priority": 10}

        conflicts = resolver.detect_conflicts(sample_policies)
        assert len(conflicts) >= 3
        assert len(resolver.get_all_conflicts()) >= 3
        assert len(resolver.get_unresolved_conflicts()) >= 3

    def test_get_unresolved_conflicts(self, resolver, sample_conflict):
        resolver._conflicts = [sample_conflict]
        unresolved = resolver.get_unresolved_conflicts()
        assert len(unresolved) == 1
        assert unresolved[0] is sample_conflict

    def test_get_all_conflicts(self, resolver, sample_conflict):
        resolver._conflicts = [sample_conflict]
        all_conflicts = resolver.get_all_conflicts()
        assert len(all_conflicts) == 1

    def test_clear_conflicts(self, resolver, sample_conflict):
        resolver._conflicts = [sample_conflict]
        resolver.clear_conflicts()
        assert len(resolver._conflicts) == 0

    def test_resolve_conflict_highest_priority(self, resolver, sample_conflict,
                                               sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.metadata = {"priority": 10}
        sample_policy_set_2.metadata = {"priority": 20}

        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.HIGHEST_PRIORITY,
            policies_map,
            resolver_id="test"
        )
        assert result == "policy_2"  # higher priority
        assert sample_conflict.resolved is True
        assert sample_conflict.resolution_strategy == ResolutionStrategy.HIGHEST_PRIORITY

    def test_resolve_conflict_latest_version(self, resolver, sample_conflict,
                                             sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.version = 1
        sample_policy_set_2.version = 3

        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.LATEST_VERSION,
            policies_map,
            resolver_id="test"
        )
        assert result == "policy_2"  # newer version

    def test_resolve_conflict_most_specific(self, resolver, sample_conflict,
                                            sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.jurisdiction = "ID"
        sample_policy_set_2.jurisdiction = "ID-JKT-SBY"  # more specific

        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.MOST_SPECIFIC,
            policies_map,
            resolver_id="test"
        )
        assert result == "policy_2"  # more specific

    def test_resolve_conflict_newest_effective(self, resolver, sample_conflict,
                                               sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.effective_from = datetime(2025, 1, 1, tzinfo=UTC)
        sample_policy_set_2.effective_from = datetime(2025, 6, 1, tzinfo=UTC)

        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.NEWEST_EFFECTIVE,
            policies_map,
            resolver_id="test"
        )
        assert result == "policy_2"

    def test_resolve_conflict_manual_override(self, resolver, sample_conflict,
                                              sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.MANUAL_OVERRIDE,
            policies_map,
            manual_policy_id="policy_1",
            resolver_id="admin"
        )
        assert result == "policy_1"
        assert sample_conflict.resolution_strategy == ResolutionStrategy.MANUAL_OVERRIDE
        assert sample_conflict.resolved_by == "admin"

    def test_resolve_conflict_manual_override_without_policy_raises(self, resolver, sample_conflict):
        with pytest.raises(PolicyConflictError, match="Manual override required"):
            resolver.resolve_conflict(
                sample_conflict,
                ResolutionStrategy.MANUAL_OVERRIDE,
                policies_map={},
                resolver_id="test"
            )

    def test_resolve_conflict_merge_actions(self, resolver, sample_conflict):
        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.MERGE_ACTIONS,
            resolver_id="test"
        )
        assert result == "MERGED"

    def test_resolve_conflict_custom_resolver(self, resolver, sample_conflict):
        def custom_resolver(conflict: Conflict) -> str:
            return "custom_result"

        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.CUSTOM,
            custom_resolver=custom_resolver,
            resolver_id="test"
        )
        assert result == "custom_result"

    def test_resolve_conflict_custom_resolver_registered(self, resolver, sample_conflict):
        def registered_resolver(conflict: Conflict) -> str:
            return "registered_result"

        resolver.register_custom_resolver("duplicate_condition", registered_resolver)
        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.CUSTOM,
            resolver_id="test"
        )
        assert result == "registered_result"

    def test_resolve_conflict_already_resolved(self, resolver, sample_conflict):
        sample_conflict.resolved = True
        result = resolver.resolve_conflict(
            sample_conflict,
            ResolutionStrategy.HIGHEST_PRIORITY,
            resolver_id="test"
        )
        assert result is None

    def test_resolve_all(self, resolver, sample_conflict, sample_policy_set, sample_policy_set_2):
        # Create another conflict
        conflict2 = Conflict(
            conflict_id="conflict_2",
            conflict_type=ConflictType.PRIORITY_AMBIGUITY,
            severity=ConflictSeverity.MEDIUM,
            description="Test conflict 2",
            policy_ids=["policy_1"],
        )
        resolver._conflicts = [sample_conflict, conflict2]

        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.metadata = {"priority": 10}
        sample_policy_set_2.metadata = {"priority": 20}

        results = resolver.resolve_all(ResolutionStrategy.HIGHEST_PRIORITY, policies_map, "test")
        assert len(results) == 2
        # Both should be resolved
        assert sample_conflict.resolved is True
        assert conflict2.resolved is True
        # Check results
        assert results[0][1] == "policy_2"
        # Conflict2 only has one policy, so it will return that
        assert results[1][1] == "policy_1"

    def test_get_resolution_history(self, resolver, sample_conflict):
        resolver._resolved_history = [sample_conflict]
        history = resolver.get_resolution_history()
        assert len(history) == 1
        assert history[0] is sample_conflict

    def test_get_conflicts_by_type(self, resolver, sample_conflict):
        conflict2 = Conflict(
            conflict_id="conflict_2",
            conflict_type=ConflictType.PRIORITY_AMBIGUITY,
            severity=ConflictSeverity.MEDIUM,
            description="Test conflict 2",
        )
        resolver._conflicts = [sample_conflict, conflict2]

        dup = resolver.get_conflicts_by_type(ConflictType.DUPLICATE_CONDITION)
        assert len(dup) == 1
        assert dup[0] is sample_conflict

        pri = resolver.get_conflicts_by_type(ConflictType.PRIORITY_AMBIGUITY)
        assert len(pri) == 1
        assert pri[0] is conflict2

        no_match = resolver.get_conflicts_by_type(ConflictType.TEMPORAL_OVERLAP)
        assert len(no_match) == 0

    def test_generate_report(self, resolver, sample_conflict):
        conflict2 = Conflict(
            conflict_id="conflict_2",
            conflict_type=ConflictType.PRIORITY_AMBIGUITY,
            severity=ConflictSeverity.MEDIUM,
            description="Test conflict 2",
            resolved=True,
            resolution_strategy=ResolutionStrategy.HIGHEST_PRIORITY,
            resolution_result="policy_1",
        )
        resolver._conflicts = [sample_conflict, conflict2]
        resolver._resolved_history = [conflict2]

        report = resolver.generate_report()
        assert report["total_conflicts"] == 2
        assert report["resolved"] == 1
        assert report["unresolved"] == 1
        assert "by_type" in report
        assert report["by_type"]["duplicate_condition"] == 1
        assert report["by_type"]["priority_ambiguity"] == 1
        assert len(report["recent_resolutions"]) == 1

    def test_export_to_json(self, resolver, sample_conflict, tmp_path):
        resolver._conflicts = [sample_conflict]
        file_path = tmp_path / "conflicts.json"
        resolver.export_to_json(str(file_path))
        assert file_path.exists()
        data = json.loads(file_path.read_text())
        assert "report" in data
        assert "conflicts" in data
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["conflict_id"] == "conflict_1"

    # ------------------------------------------------------------------------
    # Direct calls to private methods to ensure coverage detection
    # ------------------------------------------------------------------------

    def test_resolve_highest_priority_direct(self, resolver, sample_conflict,
                                             sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.metadata = {"priority": 10}
        sample_policy_set_2.metadata = {"priority": 30}
        result = resolver._resolve_highest_priority(sample_conflict, policies_map)
        assert result == "policy_2"

    def test_resolve_latest_version_direct(self, resolver, sample_conflict,
                                           sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.version = 2
        sample_policy_set_2.version = 5
        result = resolver._resolve_latest_version(sample_conflict, policies_map)
        assert result == "policy_2"

    def test_resolve_most_specific_direct(self, resolver, sample_conflict,
                                          sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.jurisdiction = "ID"
        sample_policy_set_2.jurisdiction = "ID-JKT-SBY"
        result = resolver._resolve_most_specific(sample_conflict, policies_map)
        assert result == "policy_2"

    def test_resolve_newest_effective_direct(self, resolver, sample_conflict,
                                             sample_policy_set, sample_policy_set_2):
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.effective_from = datetime(2025, 1, 1, tzinfo=UTC)
        sample_policy_set_2.effective_from = datetime(2025, 6, 1, tzinfo=UTC)
        result = resolver._resolve_newest_effective(sample_conflict, policies_map)
        assert result == "policy_2"

    def test_resolve_merge_actions_direct(self, resolver, sample_conflict):
        result = resolver._resolve_merge_actions(sample_conflict, None)
        assert result == "MERGED"

    def test_register_custom_resolver_direct(self, resolver):
        def dummy_resolver(conflict: Conflict) -> str:
            return "dummy"
        resolver.register_custom_resolver("test_type", dummy_resolver)
        assert "test_type" in resolver._custom_resolvers
        assert resolver._custom_resolvers["test_type"] is dummy_resolver

    def test_resolve_all_direct(self, resolver, sample_conflict, sample_policy_set, sample_policy_set_2):
        conflict2 = Conflict(
            conflict_id="conflict_2",
            conflict_type=ConflictType.PRIORITY_AMBIGUITY,
            severity=ConflictSeverity.MEDIUM,
            description="Test conflict 2",
            policy_ids=["policy_1"],
        )
        resolver._conflicts = [sample_conflict, conflict2]
        policies_map = {
            "policy_1": sample_policy_set,
            "policy_2": sample_policy_set_2,
        }
        sample_policy_set.metadata = {"priority": 10}
        sample_policy_set_2.metadata = {"priority": 20}
        results = resolver.resolve_all(ResolutionStrategy.HIGHEST_PRIORITY, policies_map, "test")
        assert len(results) == 2
        assert results[0][1] == "policy_2"
        assert results[1][1] == "policy_1"

    def test_get_conflicts_by_type_direct(self, resolver, sample_conflict):
        conflict2 = Conflict(
            conflict_id="conflict_2",
            conflict_type=ConflictType.PRIORITY_AMBIGUITY,
            severity=ConflictSeverity.MEDIUM,
            description="Test conflict 2",
        )
        resolver._conflicts = [sample_conflict, conflict2]
        dup = resolver.get_conflicts_by_type(ConflictType.DUPLICATE_CONDITION)
        assert len(dup) == 1
        pri = resolver.get_conflicts_by_type(ConflictType.PRIORITY_AMBIGUITY)
        assert len(pri) == 1


# ============================================================================
# Tests for compatibility method `resolve`
# ============================================================================

class TestCompatibilityResolve:
    def test_resolve_priority(self, resolver):
        policies = [
            {"id": "p1", "priority": 1, "specificity": 5},
            {"id": "p2", "priority": 3, "specificity": 2},
        ]
        result = resolver.resolve(policies, method="priority")
        assert result["id"] == "p2"  # higher priority

    def test_resolve_specificity(self, resolver):
        policies = [
            {"id": "p1", "priority": 1, "specificity": 5},
            {"id": "p2", "priority": 3, "specificity": 10},
        ]
        result = resolver.resolve(policies, method="specificity")
        assert result["id"] == "p2"  # higher specificity

    def test_resolve_default(self, resolver):
        policies = [
            {"id": "p1", "priority": 1},
            {"id": "p2", "priority": 3},
        ]
        result = resolver.resolve(policies, method="unknown")
        assert result["id"] == "p1"  # first policy

    def test_resolve_empty(self, resolver):
        result = resolver.resolve([])
        assert result == {}