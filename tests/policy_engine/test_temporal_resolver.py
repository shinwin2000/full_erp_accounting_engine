# tests/policy_engine/test_temporal_resolver.py
"""
Comprehensive unit tests for policy_engine/temporal_resolver.py.
Covers all methods, edge cases, exception paths, and singleton behavior.
Uses mocking to isolate dependencies.
"""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

from policy_engine.policy_exceptions import TemporalResolutionError
from policy_engine.temporal_resolver import TemporalResolver, get_temporal_resolver

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_policy_set():
    """Create a mock PolicySet with given effective dates."""
    def _create_policy(policy_id, eff_from, eff_to=None, domain="tax", version=1):
        mock = MagicMock()
        mock.id = policy_id
        mock.domain = domain
        mock.version = version
        mock.effective_from = eff_from
        mock.effective_to = eff_to
        return mock
    return _create_policy


@pytest.fixture
def mock_loader(mock_policy_set):
    """Create a mock policy loader with predefined policies."""
    loader = MagicMock()
    # Define some policies
    policies = [
        mock_policy_set("pol1", datetime(2020, 1, 1, tzinfo=UTC), datetime(2021, 12, 31, tzinfo=UTC), "tax"),
        mock_policy_set("pol2", datetime(2022, 1, 1, tzinfo=UTC), datetime(2023, 12, 31, tzinfo=UTC), "tax"),
        mock_policy_set("pol3", datetime(2024, 1, 1, tzinfo=UTC), None, "tax"),
        mock_policy_set("pol4", datetime(2020, 6, 1, tzinfo=UTC), None, "accounting"),
    ]
    loader.get_policies_by_domain = MagicMock(side_effect=lambda domain, jurisdiction=None: [p for p in policies if p.domain == domain])
    loader.get_policy_set = MagicMock(side_effect=lambda pid: next((p for p in policies if p.id == pid), None))
    return loader


@pytest.fixture
def resolver(mock_loader):
    """Create a TemporalResolver with mocked loader."""
    with patch("policy_engine.temporal_resolver.get_policy_loader", return_value=mock_loader):
        # Reset singleton instance to force new creation
        TemporalResolver._instance = None
        resolver = TemporalResolver()
        resolver._timeline_cache = {}  # ensure empty
        yield resolver
        # Cleanup
        TemporalResolver._instance = None


# ============================================================================
# SINGLETON AND CONSTRUCTION TESTS
# ============================================================================

class TestSingleton:
    def test_singleton_behavior(self):
        """TemporalResolver should be a singleton."""
        with patch("policy_engine.temporal_resolver.get_policy_loader") as mock_loader:
            mock_loader.return_value = MagicMock()
            resolver1 = TemporalResolver()
            resolver2 = TemporalResolver()
            assert resolver1 is resolver2
            # Cleanup
            TemporalResolver._instance = None

    def test_initialization_only_once(self):
        """__init__ should only run once."""
        with patch("policy_engine.temporal_resolver.get_policy_loader") as mock_loader:
            mock_loader.return_value = MagicMock()
            resolver = TemporalResolver()
            # Reset mock to check __init__ not called again
            mock_loader.reset_mock()
            resolver2 = TemporalResolver()
            assert resolver is resolver2
            # __init__ not called again
            mock_loader.assert_not_called()
            TemporalResolver._instance = None


# ============================================================================
# _BUILD_TIMELINE TESTS
# ============================================================================

class TestBuildTimeline:
    def test_build_timeline_caches(self, resolver, mock_loader):
        """_build_timeline should cache results by domain and jurisdiction."""
        domain = "tax"
        jurisdiction = None
        # First call
        timeline1 = resolver._build_timeline(domain, jurisdiction)
        # Second call should return same list (cached)
        timeline2 = resolver._build_timeline(domain, jurisdiction)
        assert timeline1 is timeline2
        mock_loader.get_policies_by_domain.assert_called_once_with(domain, jurisdiction=jurisdiction)

    def test_build_timeline_different_jurisdiction(self, resolver, mock_loader):
        """_build_timeline should use different cache keys for different jurisdictions."""
        resolver._build_timeline("tax", "US")
        resolver._build_timeline("tax", "ID")
        assert mock_loader.get_policies_by_domain.call_count == 2
        mock_loader.get_policies_by_domain.assert_any_call("tax", jurisdiction="US")
        mock_loader.get_policies_by_domain.assert_any_call("tax", jurisdiction="ID")

    def test_build_timeline_sorts_by_effective_from(self, resolver, mock_policy_set):
        """_build_timeline should sort policies by effective_from ascending."""
        loader = MagicMock()
        policies = [
            mock_policy_set("p1", datetime(2022, 1, 1, tzinfo=UTC)),
            mock_policy_set("p2", datetime(2020, 1, 1, tzinfo=UTC)),
            mock_policy_set("p3", datetime(2021, 1, 1, tzinfo=UTC)),
        ]
        loader.get_policies_by_domain = MagicMock(return_value=policies)
        with patch("policy_engine.temporal_resolver.get_policy_loader", return_value=loader):
            resolver = TemporalResolver()
            timeline = resolver._build_timeline("tax")
            assert [p.id for p in timeline] == ["p2", "p3", "p1"]
            TemporalResolver._instance = None


# ============================================================================
# GET_POLICY_AT_DATE TESTS
# ============================================================================

class TestGetPolicyAtDate:
    def test_get_policy_at_date_exact_match(self, resolver):
        """Should return policy whose effective_from <= target_date <= effective_to."""
        target = datetime(2022, 6, 1, tzinfo=UTC)
        policy = resolver.get_policy_at_date("tax", target)
        assert policy is not None
        assert policy.id == "pol2"

    def test_get_policy_at_date_before_first(self, resolver):
        """Should return None if no policy active at that time."""
        target = datetime(2019, 12, 31, tzinfo=UTC)
        policy = resolver.get_policy_at_date("tax", target)
        assert policy is None

    def test_get_policy_at_date_after_last(self, resolver):
        """Should return the last policy with no effective_to (infinite)."""
        target = datetime(2025, 1, 1, tzinfo=UTC)
        policy = resolver.get_policy_at_date("tax", target)
        assert policy is not None
        assert policy.id == "pol3"

    def test_get_policy_at_date_different_domain(self, resolver):
        """Should return policy for the correct domain."""
        target = datetime(2020, 7, 1, tzinfo=UTC)
        policy = resolver.get_policy_at_date("accounting", target)
        assert policy is not None
        assert policy.id == "pol4"

    def test_get_policy_at_date_no_policy_domain(self, resolver):
        """Should return None if domain has no policies."""
        target = datetime(2020, 1, 1, tzinfo=UTC)
        policy = resolver.get_policy_at_date("nonexistent", target)
        assert policy is None

    def test_get_policy_at_date_with_jurisdiction(self, resolver, mock_loader):
        """Should pass jurisdiction to loader and build timeline accordingly."""
        # We need to mock get_policies_by_domain to return different for jurisdiction
        # Already using the mock_loader from fixture; we'll just check that it's called with jurisdiction.
        target = datetime(2020, 1, 1, tzinfo=UTC)
        resolver.get_policy_at_date("tax", target, jurisdiction="US")
        mock_loader.get_policies_by_domain.assert_called_with("tax", jurisdiction="US")


# ============================================================================
# GET_POLICY_AT_DATE_STRICT TESTS
# ============================================================================

class TestGetPolicyAtDateStrict:
    def test_strict_returns_policy(self, resolver):
        """Should return policy if found."""
        target = datetime(2022, 6, 1, tzinfo=UTC)
        policy = resolver.get_policy_at_date_strict("tax", target)
        assert policy.id == "pol2"

    def test_strict_raises_if_not_found(self, resolver):
        """Should raise TemporalResolutionError if no policy found."""
        target = datetime(2019, 12, 31, tzinfo=UTC)
        with pytest.raises(TemporalResolutionError) as exc_info:
            resolver.get_policy_at_date_strict("tax", target)
        assert "No active policy" in str(exc_info.value)
        assert "2019-12-31" in str(exc_info.value)


# ============================================================================
# GET_POLICY_EFFECTIVE_RANGE TESTS
# ============================================================================

class TestGetPolicyEffectiveRange:
    def test_returns_range_for_existing_policy(self, resolver):
        """Should return (effective_from, effective_to) for existing policy."""
        eff_from, eff_to = resolver.get_policy_effective_range("pol2")
        assert eff_from == datetime(2022, 1, 1, tzinfo=UTC)
        assert eff_to == datetime(2023, 12, 31, tzinfo=UTC)

    def test_returns_infinite_to_for_policy_without_end(self, resolver):
        """Should return None for effective_to if policy has no end."""
        eff_from, eff_to = resolver.get_policy_effective_range("pol3")
        assert eff_from == datetime(2024, 1, 1, tzinfo=UTC)
        assert eff_to is None

    def test_raises_for_nonexistent_policy(self, resolver):
        """Should raise TemporalResolutionError if policy not found."""
        with pytest.raises(TemporalResolutionError) as exc_info:
            resolver.get_policy_effective_range("unknown")
        assert "Policy unknown not found" in str(exc_info.value)


# ============================================================================
# GET_POLICY_TIMELINE TESTS
# ============================================================================

class TestGetPolicyTimeline:
    def test_returns_timeline_for_domain(self, resolver):
        """Should return list of dicts with policy timeline info."""
        timeline = resolver.get_policy_timeline("tax")
        assert len(timeline) == 3
        assert timeline[0]["policy_id"] == "pol1"
        assert timeline[0]["effective_from"] == "2020-01-01T00:00:00+00:00"
        assert timeline[0]["effective_to"] == "2021-12-31T00:00:00+00:00"
        assert timeline[0]["domain"] == "tax"
        assert timeline[1]["policy_id"] == "pol2"
        assert timeline[2]["policy_id"] == "pol3"
        assert timeline[2]["effective_to"] is None

    def test_returns_empty_for_no_policies(self, resolver):
        """Should return empty list for domain with no policies."""
        timeline = resolver.get_policy_timeline("nonexistent")
        assert timeline == []


# ============================================================================
# IS_POLICY_ACTIVE_AT TESTS
# ============================================================================

class TestIsPolicyActiveAt:
    def test_active_between_dates(self, resolver):
        """Should return True if policy active at target date."""
        target = datetime(2022, 6, 1, tzinfo=UTC)
        assert resolver.is_policy_active_at("pol2", target) is True

    def test_active_on_start_date(self, resolver):
        """Should return True on effective_from date."""
        target = datetime(2022, 1, 1, tzinfo=UTC)
        assert resolver.is_policy_active_at("pol2", target) is True

    def test_active_on_end_date(self, resolver):
        """Should return True on effective_to date."""
        target = datetime(2023, 12, 31, tzinfo=UTC)
        assert resolver.is_policy_active_at("pol2", target) is True

    def test_inactive_before_start(self, resolver):
        """Should return False before effective_from."""
        target = datetime(2021, 12, 31, tzinfo=UTC)
        assert resolver.is_policy_active_at("pol2", target) is False

    def test_inactive_after_end(self, resolver):
        """Should return False after effective_to."""
        target = datetime(2024, 1, 1, tzinfo=UTC)
        assert resolver.is_policy_active_at("pol2", target) is False

    def test_policy_not_found(self, resolver):
        """Should return False if policy_id not found."""
        assert resolver.is_policy_active_at("unknown", datetime.now(UTC)) is False

    def test_active_with_no_end(self, resolver):
        """Should return True for policy with no effective_to even in far future."""
        target = datetime(2099, 1, 1, tzinfo=UTC)
        assert resolver.is_policy_active_at("pol3", target) is True


# ============================================================================
# GET_NEXT_POLICY_CHANGE TESTS
# ============================================================================

class TestGetNextPolicyChange:
    def test_next_change_exists(self, resolver):
        """Should return the next policy change after the given date."""
        after = datetime(2021, 6, 1, tzinfo=UTC)
        change = resolver.get_next_policy_change("tax", after)
        assert change is not None
        assert change["policy_id"] == "pol2"
        assert change["effective_from"] == "2022-01-01T00:00:00+00:00"
        assert change["version"] == 1

    def test_next_change_after_last(self, resolver):
        """Should return None if no changes after date."""
        after = datetime(2025, 1, 1, tzinfo=UTC)
        change = resolver.get_next_policy_change("tax", after)
        assert change is None

    def test_next_change_exactly_at_date(self, resolver):
        """Should return change if effective_from > after_date (strictly greater)."""
        after = datetime(2022, 1, 1, tzinfo=UTC)
        change = resolver.get_next_policy_change("tax", after)
        # The next change is pol3 at 2024-01-01
        assert change is not None
        assert change["policy_id"] == "pol3"

    def test_next_change_no_policies(self, resolver):
        """Should return None for domain with no policies."""
        change = resolver.get_next_policy_change("nonexistent", datetime.now(UTC))
        assert change is None


# ============================================================================
# GET_CHANGES_BETWEEN TESTS
# ============================================================================

class TestGetChangesBetween:
    def test_changes_within_range(self, resolver):
        """Should return all policy changes between from_date and to_date."""
        from_date = datetime(2021, 1, 1, tzinfo=UTC)
        to_date = datetime(2023, 12, 31, tzinfo=UTC)
        changes = resolver.get_changes_between("tax", from_date, to_date)
        # pol2 at 2022-01-01, pol3 at 2024-01-01 is outside (to_date 2023-12-31)
        assert len(changes) == 1
        assert changes[0]["policy_id"] == "pol2"

    def test_changes_excluding_boundaries(self, resolver):
        """Should include changes on from_date and to_date if effective_from equals."""
        from_date = datetime(2022, 1, 1, tzinfo=UTC)
        to_date = datetime(2024, 1, 1, tzinfo=UTC)
        changes = resolver.get_changes_between("tax", from_date, to_date)
        # pol2 and pol3 both included
        assert len(changes) == 2
        assert [c["policy_id"] for c in changes] == ["pol2", "pol3"]

    def test_changes_empty_range(self, resolver):
        """Should return empty if no changes in range."""
        from_date = datetime(2019, 1, 1, tzinfo=UTC)
        to_date = datetime(2019, 12, 31, tzinfo=UTC)
        changes = resolver.get_changes_between("tax", from_date, to_date)
        assert changes == []

    def test_changes_no_policies(self, resolver):
        """Should return empty for domain with no policies."""
        changes = resolver.get_changes_between("nonexistent", datetime.now(UTC), datetime.now(UTC))
        assert changes == []


# ============================================================================
# CLEAR_CACHE TESTS
# ============================================================================

class TestClearCache:
    def test_clear_cache(self, resolver):
        """clear_cache should empty the timeline cache."""
        resolver._build_timeline("tax")
        assert len(resolver._timeline_cache) == 1
        resolver.clear_cache()
        assert len(resolver._timeline_cache) == 0


# ============================================================================
# GET_REQUIREMENTS_SUMMARY TESTS
# ============================================================================

class TestGetRequirementsSummary:
    def test_returns_summary(self, resolver):
        """Should return a dict with summary info."""
        summary = resolver.get_requirements_summary()
        assert "timezone" in summary
        assert summary["timezone"] == "UTC"
        assert "supported_date_formats" in summary
        assert "default_effective_start" in summary
        assert "infinite_effective_end" in summary


# ============================================================================
# GET_EFFECTIVE_POLICY TEST (compatibility method)
# ============================================================================

class TestGetEffectivePolicy:
    def test_get_effective_policy(self, resolver):
        """Test the compatibility method get_effective_policy."""
        policies = [
            {"id": "p1", "effective_date": "2020-01-01", "end_date": "2021-12-31"},
            {"id": "p2", "effective_date": "2022-01-01", "end_date": None},
            {"id": "p3", "effective_date": "2021-06-01", "end_date": "2022-05-31"},
        ]
        as_of = date(2021, 7, 1)
        result = resolver.get_effective_policy(policies, as_of)
        # Should return p3 because it's effective at that date (2021-06-01 <= 2021-07-01 <= 2022-05-31)
        assert result["id"] == "p3"

    def test_get_effective_policy_with_datetime_end(self, resolver):
        """Test when end_date is a datetime."""
        policies = [
            {"id": "p1", "effective_date": date(2020, 1, 1), "end_date": datetime(2021, 12, 31, tzinfo=UTC)},
        ]
        as_of = date(2020, 6, 1)
        result = resolver.get_effective_policy(policies, as_of)
        assert result["id"] == "p1"

    def test_get_effective_policy_no_match(self, resolver):
        """Should return None if no policy applies."""
        policies = [{"id": "p1", "effective_date": "2020-01-01", "end_date": "2020-12-31"}]
        as_of = date(2021, 1, 1)
        result = resolver.get_effective_policy(policies, as_of)
        assert result is None

    def test_get_effective_policy_chooses_newest(self, resolver):
        """Should choose the policy with the latest effective_date among applicable."""
        policies = [
            {"id": "p1", "effective_date": "2020-01-01", "end_date": "2022-12-31"},
            {"id": "p2", "effective_date": "2021-01-01", "end_date": "2022-12-31"},
            {"id": "p3", "effective_date": "2020-06-01", "end_date": "2022-12-31"},
        ]
        as_of = date(2021, 6, 1)
        # All three are applicable; should pick p2 (latest effective_date)
        result = resolver.get_effective_policy(policies, as_of)
        assert result["id"] == "p2"


# ============================================================================
# GET_TEMPORAL_RESOLVER SINGLETON ACCESSOR TESTS
# ============================================================================

class TestGetTemporalResolver:
    def test_get_temporal_resolver_returns_instance(self):
        """get_temporal_resolver should return the singleton instance."""
        with patch("policy_engine.temporal_resolver.TemporalResolver") as MockResolver:
            mock_instance = MagicMock()
            MockResolver.return_value = mock_instance
            resolver = get_temporal_resolver()
            assert resolver is mock_instance

    def test_get_temporal_resolver_creates_once(self):
        """get_temporal_resolver should reuse the same instance."""
        import policy_engine.temporal_resolver as module
        # Reset the global variable
        module._temporal_resolver_instance = None
        with patch("policy_engine.temporal_resolver.TemporalResolver") as MockResolver:
            mock_instance = MagicMock()
            MockResolver.return_value = mock_instance
            resolver1 = get_temporal_resolver()
            resolver2 = get_temporal_resolver()
            assert resolver1 is resolver2
            assert MockResolver.call_count == 1
        module._temporal_resolver_instance = None


# ============================================================================
# INTEGRATION TEST (without mocking loader)
# ============================================================================

class TestIntegration:
    def test_real_loader_integration(self):
        """Test with the actual loader (if policies exist)."""
        # This test may fail if no policies are loaded; we'll skip if no policies.
        # We'll just instantiate and call methods that don't require policies.
        resolver = TemporalResolver()
        # Just check that methods return something sensible.
        summary = resolver.get_requirements_summary()
        assert "timezone" in summary
        # Clear cache
        resolver.clear_cache()
        # Cleanup
        TemporalResolver._instance = None
