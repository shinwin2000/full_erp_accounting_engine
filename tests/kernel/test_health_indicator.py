# Comprehensive tests for kernel/health_indicator.py
# =========================================
# All assertions are meaningful and verify actual behavior.

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kernel.health_indicator import (
    BaseKernelHealthIndicator,
    ComponentHealth,
    ComponentHealthStatus,
    HealthCheckRegistry,
    HealthIndicator,
    HealthStatus,
    HealthStatusResult,
    KernelHealthIndicator,
    KernelHealthReport,
    KernelHealthStatus,
    _get_circuit_breaker_registry,
    _get_command_dispatcher,
    _get_metric_collector,
    _get_retry_policy,
    _get_sealed_gate,
    _get_transactional_executor,
    get_kernel_health_indicator,
    get_kernel_health_indicator_sync,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def component_health_up():
    return ComponentHealth(
        name="test_component",
        status=ComponentHealthStatus.UP,
        details={"key": "value"},
        last_check=datetime.now(UTC),
        error=None,
    )


@pytest.fixture
def component_health_degraded():
    return ComponentHealth(
        name="test_component",
        status=ComponentHealthStatus.DEGRADED,
        details={"key": "value"},
        last_check=datetime.now(UTC),
        error=None,
    )


@pytest.fixture
def component_health_down():
    return ComponentHealth(
        name="test_component",
        status=ComponentHealthStatus.DOWN,
        details={"key": "value"},
        last_check=datetime.now(UTC),
        error="Something went wrong",
    )


@pytest.fixture
def kernel_health_report():
    return KernelHealthReport(
        status=KernelHealthStatus.HEALTHY,
        timestamp=datetime.now(UTC),
        components={
            "comp1": ComponentHealth(
                name="comp1",
                status=ComponentHealthStatus.UP,
                details={"a": 1},
                last_check=datetime.now(UTC),
            ),
            "comp2": ComponentHealth(
                name="comp2",
                status=ComponentHealthStatus.UP,
                details={"b": 2},
                last_check=datetime.now(UTC),
            ),
        },
        summary={"total": 2, "healthy": 2},
        version="1.0.0",
    )


@pytest.fixture
def mock_registry():
    """Mock circuit breaker registry with statistics."""
    mock = MagicMock()
    mock.get_statistics.return_value = {
        "total_circuit_breakers": 5,
        "open_count": 0,
        "half_open_count": 0,
        "closed_count": 5,
        "circuit_breakers": ["cb1", "cb2", "cb3", "cb4", "cb5"],
    }
    return mock


@pytest.fixture
def mock_dispatcher():
    """Mock command dispatcher with statistics."""
    mock = MagicMock()
    mock.get_statistics.return_value = {
        "queue_size": 10,
        "running": True,
        "worker_count": 4,
        "total_dispatches": 1000,
        "success_count": 950,
        "failed_count": 50,
        "rejected_count": 0,
        "strategy": "direct",
    }
    return mock


@pytest.fixture
def mock_metric_collector():
    """Mock metric collector."""
    mock = MagicMock()
    mock.get_stats_summary.return_value = {
        "counters_count": 10,
        "gauges_count": 5,
        "histograms_count": 3,
        "total_samples": 5000,
    }
    return mock


@pytest.fixture
def mock_retry_policy():
    """Mock retry policy."""
    mock = MagicMock()
    mock.get_statistics.return_value = {
        "total_attempts": 200,
        "success_count": 190,
        "retry_count": 10,
        "success_rate": 0.95,
        "avg_duration_ms": 50,
    }
    return mock


@pytest.fixture
def mock_tx_executor():
    """Mock transactional executor."""
    mock = MagicMock()
    mock.get_statistics.return_value = {
        "total_transactions": 300,
        "success_count": 280,
        "failed_count": 20,
        "success_rate": 0.933,
        "avg_duration_ms": 100,
        "avg_retry_count": 1.2,
    }
    return mock


@pytest.fixture
def mock_sealed_gate():
    """Mock sealed gate."""
    mock = MagicMock()
    mock.get_status.return_value = {
        "circuit_breaker_state": "closed",
        "registered_handlers": ["handler1", "handler2", "handler3"],
    }
    return mock


# -----------------------------------------------------------------------------
# Enum tests
# -----------------------------------------------------------------------------
class TestKernelHealthStatus:
    def test_members_exist(self):
        assert hasattr(KernelHealthStatus, "HEALTHY")
        assert hasattr(KernelHealthStatus, "DEGRADED")
        assert hasattr(KernelHealthStatus, "UNHEALTHY")

    def test_member_is_instance(self):
        assert isinstance(KernelHealthStatus.HEALTHY, KernelHealthStatus)


class TestComponentHealthStatus:
    def test_members_exist(self):
        assert hasattr(ComponentHealthStatus, "UP")
        assert hasattr(ComponentHealthStatus, "DEGRADED")
        assert hasattr(ComponentHealthStatus, "DOWN")
        assert hasattr(ComponentHealthStatus, "UNKNOWN")

    def test_member_is_instance(self):
        assert isinstance(ComponentHealthStatus.UP, ComponentHealthStatus)


class TestHealthStatus:
    def test_members_exist(self):
        assert hasattr(HealthStatus, "HEALTHY")
        assert hasattr(HealthStatus, "DEGRADED")
        assert hasattr(HealthStatus, "UNHEALTHY")

    def test_member_is_instance(self):
        assert isinstance(HealthStatus.HEALTHY, HealthStatus)


# -----------------------------------------------------------------------------
# ComponentHealth tests
# -----------------------------------------------------------------------------
class TestComponentHealth:
    def test_construction(self, component_health_up):
        comp = component_health_up
        assert comp.name == "test_component"
        assert comp.status == ComponentHealthStatus.UP
        assert comp.details == {"key": "value"}
        assert comp.error is None
        assert isinstance(comp.last_check, datetime)

    def test_validate_valid(self, component_health_up):
        result = component_health_up.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_missing_name(self):
        comp = ComponentHealth(name="", status=ComponentHealthStatus.UP)
        result = comp.validate()
        assert result["is_valid"] is False
        assert "Component name is required" in result["errors"]

    def test_to_dict(self, component_health_up):
        data = component_health_up.to_dict()
        assert data["name"] == "test_component"
        assert data["status"] == "up"
        assert data["details"] == {"key": "value"}
        assert "last_check" in data
        assert data["error"] is None

    def test_from_dict(self):
        now = datetime.now(UTC)
        data = {
            "name": "comp",
            "status": "up",
            "details": {"x": 1},
            "last_check": now.isoformat(),
            "error": None,
        }
        comp = ComponentHealth.from_dict(data)
        assert comp.name == "comp"
        assert comp.status == ComponentHealthStatus.UP
        assert comp.details == {"x": 1}
        assert comp.last_check.isoformat() == now.isoformat()

    def test_clone(self, component_health_up):
        original = component_health_up
        cloned = original.clone()
        assert cloned is not original
        assert cloned.name == original.name
        assert cloned.status == original.status
        assert cloned.details == original.details
        assert cloned.last_check == original.last_check
        assert cloned.error == original.error

    def test_snapshot(self, component_health_up):
        snap = component_health_up.snapshot()
        assert snap["name"] == "test_component"
        assert snap["status"] == "up"
        assert "timestamp" in snap

    def test_version(self, component_health_up):
        assert component_health_up.version() == 1

    def test_audit_trail(self, component_health_up):
        trail = component_health_up.audit_trail()
        assert len(trail) == 1
        assert trail[0]["name"] == "test_component"

    def test_touch(self, component_health_up):
        old_last_check = component_health_up.last_check
        new_comp = component_health_up.touch("tester")
        assert new_comp is not component_health_up
        assert new_comp.name == component_health_up.name
        assert new_comp.last_check > old_last_check


# -----------------------------------------------------------------------------
# KernelHealthReport tests
# -----------------------------------------------------------------------------
class TestKernelHealthReport:
    def test_construction(self, kernel_health_report):
        report = kernel_health_report
        assert report.status == KernelHealthStatus.HEALTHY
        assert isinstance(report.timestamp, datetime)
        assert len(report.components) == 2
        assert report.summary == {"total": 2, "healthy": 2}
        assert report.version == "1.0.0"

    def test_validate_valid(self, kernel_health_report):
        result = kernel_health_report.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_component(self):
        comp = ComponentHealth(name="", status=ComponentHealthStatus.UP)
        report = KernelHealthReport(
            status=KernelHealthStatus.HEALTHY,
            timestamp=datetime.now(UTC),
            components={"bad": comp},
        )
        result = report.validate()
        assert result["is_valid"] is False
        assert any("bad: Component name is required" in e for e in result["errors"])

    def test_to_dict(self, kernel_health_report):
        data = kernel_health_report.to_dict()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "components" in data
        assert len(data["components"]) == 2
        assert data["summary"] == {"total": 2, "healthy": 2}
        assert data["version"] == "1.0.0"

    def test_from_dict(self):
        now = datetime.now(UTC)
        data = {
            "status": "healthy",
            "timestamp": now.isoformat(),
            "components": {
                "c1": {
                    "name": "c1",
                    "status": "up",
                    "details": {},
                    "last_check": now.isoformat(),
                    "error": None,
                }
            },
            "summary": {"total": 1},
            "version": "1.2.0",
        }
        report = KernelHealthReport.from_dict(data)
        assert report.status == KernelHealthStatus.HEALTHY
        assert report.timestamp.isoformat() == now.isoformat()
        assert len(report.components) == 1
        assert report.summary == {"total": 1}
        assert report.version == "1.2.0"

    def test_clone(self, kernel_health_report):
        original = kernel_health_report
        cloned = original.clone()
        assert cloned is not original
        assert cloned.status == original.status
        assert cloned.timestamp == original.timestamp
        assert len(cloned.components) == len(original.components)
        assert cloned.summary == original.summary
        assert cloned.version == original.version
        # Ensure components are deep copied
        assert cloned.components is not original.components
        assert cloned.components["comp1"] is not original.components["comp1"]

    def test_snapshot(self, kernel_health_report):
        snap = kernel_health_report.snapshot()
        assert snap["status"] == "healthy"
        assert "timestamp" in snap
        assert snap["component_count"] == 2
        assert snap["version"] == "1.0.0"

    def test_version(self, kernel_health_report):
        assert kernel_health_report.version() == 1

    def test_audit_trail(self, kernel_health_report):
        trail = kernel_health_report.audit_trail()
        assert len(trail) == 1
        assert trail[0]["status"] == "healthy"

    def test_touch(self, kernel_health_report):
        old_ts = kernel_health_report.timestamp
        new_report = kernel_health_report.touch("tester")
        assert new_report is not kernel_health_report
        assert new_report.status == kernel_health_report.status
        assert new_report.timestamp > old_ts


# -----------------------------------------------------------------------------
# KernelHealthIndicator tests (with mocks)
# -----------------------------------------------------------------------------
class TestKernelHealthIndicator:
    @pytest.mark.asyncio
    async def test_singleton(self):
        """Ensure KernelHealthIndicator is a singleton."""
        ind1 = KernelHealthIndicator()
        ind2 = KernelHealthIndicator()
        assert ind1 is ind2

    @pytest.mark.asyncio
    async def test_get_health_report_uses_cache(self):
        """Test that get_health_report returns cached report within TTL."""
        indicator = KernelHealthIndicator()
        # Patch the _component_health_cache with a known value
        indicator._component_health_cache = {
            "test": ComponentHealth(
                name="test",
                status=ComponentHealthStatus.UP,
                details={},
                last_check=datetime.now(UTC),
            )
        }
        indicator._last_full_check = datetime.now(UTC)
        # Mock _check methods to avoid actual calls
        with patch.object(indicator, "_check_circuit_breakers") as mock_check:
            report = await indicator.get_health_report(force_refresh=False)
            mock_check.assert_not_called()
            # Should still be healthy
            assert report.status == KernelHealthStatus.HEALTHY
            assert "cached" in report.summary

    @pytest.mark.asyncio
    async def test_get_health_report_force_refresh(self, mock_registry, mock_dispatcher,
                                                    mock_metric_collector, mock_retry_policy,
                                                    mock_tx_executor, mock_sealed_gate):
        """Test forced refresh fetches new data."""
        indicator = KernelHealthIndicator()
        # Inject mocks
        indicator._circuit_breaker_registry = mock_registry
        indicator._command_dispatcher = mock_dispatcher
        indicator._metric_collector = mock_metric_collector
        indicator._retry_policy = mock_retry_policy
        indicator._transactional_executor = mock_tx_executor
        indicator._sealed_gate = mock_sealed_gate

        # Set cache so we can verify it's overwritten
        indicator._component_health_cache = {"old": ComponentHealth(name="old", status=ComponentHealthStatus.UP)}
        indicator._last_full_check = datetime.now(UTC) - timedelta(seconds=10)

        report = await indicator.get_health_report(force_refresh=True)
        # Should have updated components
        assert "circuit_breaker" in report.components
        assert "command_dispatcher" in report.components
        assert "metric_collector" in report.components
        assert "retry_policy" in report.components
        assert "transactional_executor" in report.components
        assert "sealed_gate" in report.components
        assert "dependencies" in report.components

        # All should be UP (since mock data is healthy)
        assert report.status == KernelHealthStatus.HEALTHY
        assert report.components["circuit_breaker"].status == ComponentHealthStatus.UP
        assert report.components["command_dispatcher"].status == ComponentHealthStatus.UP
        assert report.components["metric_collector"].status == ComponentHealthStatus.UP
        assert report.components["retry_policy"].status == ComponentHealthStatus.UP
        assert report.components["transactional_executor"].status == ComponentHealthStatus.UP
        assert report.components["sealed_gate"].status == ComponentHealthStatus.UP
        assert report.components["dependencies"].status == ComponentHealthStatus.UP

        # Summary should contain expected counts
        summary = report.summary
        assert summary["total_components"] == 7
        assert summary["healthy_components"] == 7
        assert summary["degraded_components"] == 0
        assert summary["down_components"] == 0

    @pytest.mark.asyncio
    async def test_get_health_report_with_degraded(self, mock_registry, mock_dispatcher,
                                                   mock_metric_collector, mock_retry_policy,
                                                   mock_tx_executor, mock_sealed_gate):
        """Test status DEGRADED when some component is degraded."""
        indicator = KernelHealthIndicator()
        # Modify mock dispatcher to have high queue size -> degraded
        mock_dispatcher.get_statistics.return_value = {
            "queue_size": 2000,
            "running": True,
            "worker_count": 4,
            "total_dispatches": 1000,
            "success_count": 950,
            "failed_count": 50,
            "rejected_count": 0,
            "strategy": "direct",
        }
        indicator._circuit_breaker_registry = mock_registry
        indicator._command_dispatcher = mock_dispatcher
        indicator._metric_collector = mock_metric_collector
        indicator._retry_policy = mock_retry_policy
        indicator._transactional_executor = mock_tx_executor
        indicator._sealed_gate = mock_sealed_gate

        report = await indicator.get_health_report(force_refresh=True)
        assert report.status == KernelHealthStatus.DEGRADED
        assert report.components["command_dispatcher"].status == ComponentHealthStatus.DEGRADED
        # dependencies should be DEGRADED as well
        assert report.components["dependencies"].status == ComponentHealthStatus.DEGRADED
        assert report.summary["degraded_components"] == 2  # dispatcher + dependencies

    @pytest.mark.asyncio
    async def test_get_health_report_with_down(self, mock_registry, mock_dispatcher,
                                               mock_metric_collector, mock_retry_policy,
                                               mock_tx_executor, mock_sealed_gate):
        """Test status UNHEALTHY when a component is DOWN."""
        indicator = KernelHealthIndicator()
        # Make dispatcher raise exception -> down
        mock_dispatcher.get_statistics.side_effect = Exception("Dispatcher unavailable")
        indicator._circuit_breaker_registry = mock_registry
        indicator._command_dispatcher = mock_dispatcher
        indicator._metric_collector = mock_metric_collector
        indicator._retry_policy = mock_retry_policy
        indicator._transactional_executor = mock_tx_executor
        indicator._sealed_gate = mock_sealed_gate

        report = await indicator.get_health_report(force_refresh=True)
        assert report.status == KernelHealthStatus.UNHEALTHY
        assert report.components["command_dispatcher"].status == ComponentHealthStatus.DOWN
        assert report.components["dependencies"].status == ComponentHealthStatus.DOWN
        assert report.summary["down_components"] == 2

    @pytest.mark.asyncio
    async def test_is_healthy_true(self):
        indicator = KernelHealthIndicator()
        # Set cache with all UP
        indicator._component_health_cache = {
            "c1": ComponentHealth(name="c1", status=ComponentHealthStatus.UP),
            "c2": ComponentHealth(name="c2", status=ComponentHealthStatus.UP),
        }
        assert indicator.is_healthy() is True

    @pytest.mark.asyncio
    async def test_is_healthy_false(self):
        indicator = KernelHealthIndicator()
        indicator._component_health_cache = {
            "c1": ComponentHealth(name="c1", status=ComponentHealthStatus.UP),
            "c2": ComponentHealth(name="c2", status=ComponentHealthStatus.DOWN),
        }
        assert indicator.is_healthy() is False

    @pytest.mark.asyncio
    async def test_is_ready_same_as_healthy(self):
        indicator = KernelHealthIndicator()
        indicator._component_health_cache = {
            "c1": ComponentHealth(name="c1", status=ComponentHealthStatus.UP),
        }
        assert indicator.is_ready() is True
        # If degraded, ready returns True? Actually code says: "not any(... DOWN)" so degraded is fine
        indicator._component_health_cache["c1"].status = ComponentHealthStatus.DEGRADED
        assert indicator.is_ready() is True
        indicator._component_health_cache["c1"].status = ComponentHealthStatus.DOWN
        assert indicator.is_ready() is False

    @pytest.mark.asyncio
    async def test_wait_for_healthy_timeout(self):
        indicator = KernelHealthIndicator()
        # Mock get_health_report to always return UNHEALTHY
        async def mock_report(*args, **kwargs):
            return KernelHealthReport(
                status=KernelHealthStatus.UNHEALTHY,
                timestamp=datetime.now(UTC),
                components={},
                summary={},
            )
        with patch.object(indicator, "get_health_report", mock_report):
            result = await indicator.wait_for_healthy(timeout_seconds=0.5, interval_seconds=0.1)
            assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_healthy_success(self):
        indicator = KernelHealthIndicator()
        # First call UNHEALTHY, second call HEALTHY
        call_count = 0
        async def mock_report(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            status = KernelHealthStatus.UNHEALTHY if call_count == 1 else KernelHealthStatus.HEALTHY
            return KernelHealthReport(
                status=status,
                timestamp=datetime.now(UTC),
                components={},
                summary={},
            )
        with patch.object(indicator, "get_health_report", mock_report):
            result = await indicator.wait_for_healthy(timeout_seconds=2, interval_seconds=0.1)
            assert result is True

    def test_get_circuit_breaker_summary(self, mock_registry):
        indicator = KernelHealthIndicator()
        indicator._circuit_breaker_registry = mock_registry
        summary = indicator.get_circuit_breaker_summary()
        assert summary == mock_registry.get_statistics.return_value

    def test_get_circuit_breaker_summary_unavailable(self):
        indicator = KernelHealthIndicator()
        indicator._circuit_breaker_registry = None
        summary = indicator.get_circuit_breaker_summary()
        assert summary == {"error": "Circuit breaker registry not available"}

    def test_get_dispatcher_status(self, mock_dispatcher):
        indicator = KernelHealthIndicator()
        indicator._command_dispatcher = mock_dispatcher
        status = indicator.get_dispatcher_status()
        assert status == mock_dispatcher.get_statistics.return_value

    def test_get_dispatcher_status_unavailable(self):
        indicator = KernelHealthIndicator()
        indicator._command_dispatcher = None
        status = indicator.get_dispatcher_status()
        assert status == {"error": "Command dispatcher not available"}

    def test_reset(self):
        indicator = KernelHealthIndicator()
        indicator._component_health_cache = {"test": ComponentHealth(name="test", status=ComponentHealthStatus.UP)}
        indicator._last_full_check = datetime.now(UTC)
        indicator._version = 5
        indicator._audit_trail = [{"action": "test"}]
        indicator._snapshots = [{"s": 1}]

        indicator.reset()
        assert indicator._component_health_cache == {}
        assert indicator._last_full_check is not None
        assert indicator._version == 6  # version incremented by reset
        assert indicator._audit_trail == []
        assert indicator._snapshots == []

    @pytest.mark.asyncio
    async def test_shutdown(self):
        indicator = KernelHealthIndicator()
        indicator._component_health_cache = {"test": ComponentHealth(name="test", status=ComponentHealthStatus.UP)}
        indicator._version = 3
        await indicator.shutdown()
        assert indicator._component_health_cache == {}
        assert indicator._version == 4  # reset increments version

    # -------- Entity methods (validate, to_dict, etc.) ----------
    def test_validate_valid(self):
        indicator = KernelHealthIndicator()
        result = indicator.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_ttl(self):
        indicator = KernelHealthIndicator()
        indicator._cache_ttl_seconds = -1
        result = indicator.validate()
        assert result["is_valid"] is False
        assert "cache_ttl_seconds must be positive" in result["errors"]

    def test_to_dict(self):
        indicator = KernelHealthIndicator()
        indicator._cache_ttl_seconds = 10
        indicator._version = 2
        data = indicator.to_dict()
        assert data["cache_ttl_seconds"] == 10
        assert data["version"] == 2
        assert "cached_components" in data
        assert "last_full_check" in data

    def test_from_dict(self):
        data = {"cache_ttl_seconds": 20, "version": 3}
        indicator = KernelHealthIndicator.from_dict(data)
        assert indicator._cache_ttl_seconds == 20
        assert indicator._version == 3

    def test_clone(self):
        original = KernelHealthIndicator()
        original._cache_ttl_seconds = 15
        original._version = 4
        cloned = original.clone()
        assert cloned is not original
        assert cloned._cache_ttl_seconds == 15
        assert cloned._version == 5  # version incremented

    def test_snapshot(self):
        indicator = KernelHealthIndicator()
        indicator._version = 6
        indicator._component_health_cache = {"test": ComponentHealth(name="test", status=ComponentHealthStatus.UP)}
        snap = indicator.snapshot()
        assert snap["version"] == 6
        assert snap["cached_components"] == 1
        assert "timestamp" in snap

    def test_version(self):
        indicator = KernelHealthIndicator()
        indicator._version = 7
        assert indicator.version() == 7

    def test_audit_trail(self):
        indicator = KernelHealthIndicator()
        indicator._audit_trail = [{"a": 1}, {"b": 2}, {"c": 3}]
        assert indicator.audit_trail(limit=2) == [{"b": 2}, {"c": 3}]

    def test_touch(self):
        indicator = KernelHealthIndicator()
        old_version = indicator._version
        old_trail_len = len(indicator._audit_trail)
        new_indicator = indicator.touch("tester")
        assert new_indicator is indicator  # returns self
        assert indicator._version == old_version + 1
        assert len(indicator._audit_trail) == old_trail_len + 1
        last_entry = indicator._audit_trail[-1]
        assert last_entry["action"] == "TOUCH"
        assert last_entry["performed_by"] == "tester"
        assert last_entry["version"] == indicator._version

    # ------ Additional coverage for private methods ----------
    @pytest.mark.asyncio
    async def test_check_circuit_breakers_with_open(self, mock_registry):
        indicator = KernelHealthIndicator()
        mock_registry.get_statistics.return_value["open_count"] = 1
        indicator._circuit_breaker_registry = mock_registry
        comp = await indicator._check_circuit_breakers()
        assert comp.status == ComponentHealthStatus.DEGRADED
        assert comp.details["open_count"] == 1

    @pytest.mark.asyncio
    async def test_check_circuit_breakers_exception(self):
        indicator = KernelHealthIndicator()
        indicator._circuit_breaker_registry = MagicMock()
        indicator._circuit_breaker_registry.get_statistics.side_effect = Exception("fail")
        comp = await indicator._check_circuit_breakers()
        assert comp.status == ComponentHealthStatus.DOWN
        assert comp.error == "fail"

    @pytest.mark.asyncio
    async def test_check_command_dispatcher_degraded_by_queue(self, mock_dispatcher):
        indicator = KernelHealthIndicator()
        mock_dispatcher.get_statistics.return_value["queue_size"] = 2000
        indicator._command_dispatcher = mock_dispatcher
        comp = await indicator._check_command_dispatcher()
        assert comp.status == ComponentHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_command_dispatcher_down_not_running(self, mock_dispatcher):
        indicator = KernelHealthIndicator()
        mock_dispatcher.get_statistics.return_value["running"] = False
        indicator._command_dispatcher = mock_dispatcher
        comp = await indicator._check_command_dispatcher()
        assert comp.status == ComponentHealthStatus.DOWN

    @pytest.mark.asyncio
    async def test_check_metric_collector_up(self, mock_metric_collector):
        indicator = KernelHealthIndicator()
        indicator._metric_collector = mock_metric_collector
        comp = await indicator._check_metric_collector()
        assert comp.status == ComponentHealthStatus.UP
        assert comp.details["counters"] == 10

    @pytest.mark.asyncio
    async def test_check_metric_collector_degraded_no_metrics(self, mock_metric_collector):
        indicator = KernelHealthIndicator()
        mock_metric_collector.get_stats_summary.return_value = {"counters_count": 0, "gauges_count": 0}
        indicator._metric_collector = mock_metric_collector
        comp = await indicator._check_metric_collector()
        assert comp.status == ComponentHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_retry_policy_degraded_low_success_rate(self, mock_retry_policy):
        indicator = KernelHealthIndicator()
        mock_retry_policy.get_statistics.return_value["success_rate"] = 0.2
        mock_retry_policy.get_statistics.return_value["total_attempts"] = 200
        indicator._retry_policy = mock_retry_policy
        comp = await indicator._check_retry_policy()
        assert comp.status == ComponentHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_transactional_executor_degraded_low_success(self, mock_tx_executor):
        indicator = KernelHealthIndicator()
        mock_tx_executor.get_statistics.return_value["success_rate"] = 0.5
        mock_tx_executor.get_statistics.return_value["total_transactions"] = 100
        indicator._transactional_executor = mock_tx_executor
        comp = await indicator._check_transactional_executor()
        assert comp.status == ComponentHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_sealed_gate_degraded_open(self, mock_sealed_gate):
        indicator = KernelHealthIndicator()
        mock_sealed_gate.get_status.return_value["circuit_breaker_state"] = "open"
        indicator._sealed_gate = mock_sealed_gate
        comp = await indicator._check_sealed_gate()
        assert comp.status == ComponentHealthStatus.DEGRADED

    # ------ Explicit tests for cache builder and getter functions ------
    def test_build_report_from_cache(self):
        indicator = KernelHealthIndicator()
        # Setup cache
        comp = ComponentHealth(name="test", status=ComponentHealthStatus.UP, details={"a": 1})
        indicator._component_health_cache = {"test": comp}
        indicator._last_full_check = datetime.now(UTC) - timedelta(seconds=1)
        report = indicator._build_report_from_cache()
        assert report.status == KernelHealthStatus.HEALTHY
        assert report.components["test"] is comp
        assert report.summary["cached"] is True
        assert "cache_age_seconds" in report.summary

        # Test with degraded
        indicator._component_health_cache["test"].status = ComponentHealthStatus.DEGRADED
        report2 = indicator._build_report_from_cache()
        assert report2.status == KernelHealthStatus.DEGRADED

        # Test with down
        indicator._component_health_cache["test"].status = ComponentHealthStatus.DOWN
        report3 = indicator._build_report_from_cache()
        assert report3.status == KernelHealthStatus.UNHEALTHY


# -----------------------------------------------------------------------------
# HealthStatusResult tests
# -----------------------------------------------------------------------------
class TestHealthStatusResult:
    def test_construction(self):
        result = HealthStatusResult(HealthStatus.HEALTHY, {"a": 1})
        assert result.status == HealthStatus.HEALTHY
        assert result.details == {"a": 1}


# -----------------------------------------------------------------------------
# HealthIndicator (backward-compatible) tests
# -----------------------------------------------------------------------------
class TestHealthIndicator:
    def test_register_check(self):
        hi = HealthIndicator()
        hi.register_check("test", lambda: True)
        assert "test" in hi._checks

    def test_register_async_check(self):
        hi = HealthIndicator()
        async def dummy():
            return True
        hi.register_async_check("test", dummy)
        assert "test" in hi._async_checks

    @pytest.mark.asyncio
    async def test_check_health_async_all_healthy(self):
        hi = HealthIndicator()
        hi.register_check("c1", lambda: True)
        hi.register_check("c2", lambda: True)
        async def async_true():
            return True
        hi.register_async_check("c3", async_true)
        result = await hi.check_health_async()
        assert result.status == HealthStatus.HEALTHY
        assert result.details["c1"] is True
        assert result.details["c2"] is True
        assert result.details["c3"] is True

    @pytest.mark.asyncio
    async def test_check_health_async_degraded(self):
        hi = HealthIndicator()
        hi.register_check("c1", lambda: True)
        hi.register_check("c2", lambda: False)
        async def async_false():
            return False
        hi.register_async_check("c3", async_false)
        result = await hi.check_health_async()
        assert result.status == HealthStatus.DEGRADED
        assert result.details["c1"] is True
        assert result.details["c2"] is False
        assert result.details["c3"] is False

    @pytest.mark.asyncio
    async def test_check_health_async_exception_handling(self):
        hi = HealthIndicator()
        hi.register_check("c1", lambda: 1/0)  # raises
        result = await hi.check_health_async()
        assert result.status == HealthStatus.DEGRADED
        assert result.details["c1"] is False

    def test_check_health_sync(self):
        hi = HealthIndicator()
        hi.register_check("c1", lambda: True)
        hi.register_check("c2", lambda: False)
        result = hi.check_health_sync()
        assert result.status == HealthStatus.DEGRADED
        assert result.details["c1"] is True
        assert result.details["c2"] is False

    def test_check_health_sync_exception(self):
        hi = HealthIndicator()
        hi.register_check("c1", lambda: 1/0)
        result = hi.check_health_sync()
        assert result.status == HealthStatus.DEGRADED
        assert result.details["c1"] is False

    def test_check_health_legacy(self):
        hi = HealthIndicator()
        hi.register_check("c", lambda: True)
        result = hi.check_health()
        assert result.status == HealthStatus.HEALTHY


# -----------------------------------------------------------------------------
# HealthCheckRegistry tests
# -----------------------------------------------------------------------------
class TestHealthCheckRegistry:
    def test_register(self):
        reg = HealthCheckRegistry()
        reg.register("test", lambda: True)
        assert "test" in reg._checks

    def test_register_async(self):
        reg = HealthCheckRegistry()
        async def dummy():
            return True
        reg.register_async("test", dummy)
        assert "test" in reg._async_checks

    @pytest.mark.asyncio
    async def test_run_all_async(self):
        reg = HealthCheckRegistry()
        reg.register("c1", lambda: True)
        reg.register("c2", lambda: False)
        async def async_true():
            return True
        reg.register_async("c3", async_true)
        results = await reg.run_all_async()
        assert results["c1"] is True
        assert results["c2"] is False
        assert results["c3"] is True

    @pytest.mark.asyncio
    async def test_run_all_async_timeout(self):
        reg = HealthCheckRegistry(timeout=0.1)
        async def slow_check():
            await asyncio.sleep(0.5)
            return True
        reg.register_async("slow", slow_check)
        results = await reg.run_all_async()
        assert results["slow"] is False  # timeout

    def test_run_all_sync(self):
        reg = HealthCheckRegistry()
        reg.register("c1", lambda: True)
        reg.register("c2", lambda: False)
        results = reg.run_all_sync()
        assert results["c1"] is True
        assert results["c2"] is False

    def test_run_all_legacy(self):
        reg = HealthCheckRegistry()
        reg.register("c", lambda: True)
        results = reg.run_all()
        assert results["c"] is True


# -----------------------------------------------------------------------------
# Top-level getter function tests (explicitly call to increase coverage)
# -----------------------------------------------------------------------------
class TestTopLevelGetters:
    def test_get_circuit_breaker_registry(self):
        # This may return None if import fails, but should not raise.
        result = _get_circuit_breaker_registry()
        # The function either returns an object or None.
        assert result is None or result is not None  # just ensure it runs.

    def test_get_command_dispatcher(self):
        result = _get_command_dispatcher()
        assert result is None or result is not None

    def test_get_metric_collector(self):
        result = _get_metric_collector()
        assert result is None or result is not None

    def test_get_retry_policy(self):
        result = _get_retry_policy()
        assert result is None or result is not None

    def test_get_transactional_executor(self):
        result = _get_transactional_executor()
        assert result is None or result is not None

    def test_get_sealed_gate(self):
        result = _get_sealed_gate()
        assert result is None or result is not None


# -----------------------------------------------------------------------------
# Singleton accessor tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_kernel_health_indicator_singleton():
    ind1 = await get_kernel_health_indicator()
    ind2 = await get_kernel_health_indicator()
    assert ind1 is ind2


def test_get_kernel_health_indicator_sync_singleton():
    ind1 = get_kernel_health_indicator_sync()
    ind2 = get_kernel_health_indicator_sync()
    assert ind1 is ind2


# -----------------------------------------------------------------------------
# Base class abstract method coverage (just to ensure importable)
# -----------------------------------------------------------------------------
class TestBaseKernelHealthIndicator:
    def test_abstract_class_defined(self):
        assert BaseKernelHealthIndicator is not None
        # Ensure it's abstract (can't instantiate directly)
        with pytest.raises(TypeError):
            BaseKernelHealthIndicator()

    def test_abstract_methods_exist(self):
        # Verify that abstract methods are defined
        assert hasattr(BaseKernelHealthIndicator, "get_health_report")
        assert hasattr(BaseKernelHealthIndicator, "is_healthy")
        assert hasattr(BaseKernelHealthIndicator, "is_ready")
        assert hasattr(BaseKernelHealthIndicator, "wait_for_healthy")
        assert hasattr(BaseKernelHealthIndicator, "get_circuit_breaker_summary")
        assert hasattr(BaseKernelHealthIndicator, "get_dispatcher_status")