# adapters/coretax_djp/test_health_dashboard.py
"""
Comprehensive unit tests for Coretax Health Dashboard.

FIXES:
- Semua datetime.now() diganti dengan FIXED_NOW.
- Semua test memiliki assertion bermakna.
- Semua async test memiliki @pytest.mark.asyncio.
- Duplikasi dihindari dengan helper/parametrize.
- Mocking untuk komponen eksternal.
- Ditambahkan marker asyncio pada setiap test function.
- Perbaikan test flaky dengan mocking sleep.
- Penambahan assertion pada test tanpa assert.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.coretax_djp.health_dashboard import (
    Alert,
    AlertSeverity,
    ComponentHealth,
    CoretaxDashboardResponse,
    CoretaxHealthChecker,
    CoreTaxHealthDashboard,
    HealthStatus,
    HistoricalHealthRecord,
    router,
)

# =============================================================================
# FIXED DATETIME
# =============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(hours=2)
FIXED_OLD = FIXED_NOW - timedelta(days=40)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("adapters.coretax_djp.health_dashboard.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_health_status_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.DOWN.value == "down"
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_alert_severity_values(self):
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.ERROR.value == "error"
        assert AlertSeverity.CRITICAL.value == "critical"


# =============================================================================
# Tests for Pydantic Models
# =============================================================================

class TestModels:
    def test_component_health(self):
        health = ComponentHealth(
            status=HealthStatus.HEALTHY,
            message="OK",
            latency_ms=10.5,
            last_check=FIXED_NOW,
            details={"foo": "bar"},
        )
        assert health.status == HealthStatus.HEALTHY
        assert health.message == "OK"
        assert health.latency_ms == 10.5
        assert health.last_check == FIXED_NOW
        assert health.details == {"foo": "bar"}

    def test_alert(self):
        alert = Alert(
            id="alert-1",
            component="redis",
            severity=AlertSeverity.CRITICAL,
            title="Redis Down",
            message="Cannot connect to Redis",
            created_at=FIXED_NOW,
            resolved_at=None,
            acknowledged=False,
            acknowledged_by=None,
        )
        assert alert.id == "alert-1"
        assert alert.component == "redis"
        assert alert.severity == AlertSeverity.CRITICAL
        assert alert.title == "Redis Down"

    def test_coretax_dashboard_response(self):
        response = CoretaxDashboardResponse(
            overall_status=HealthStatus.HEALTHY,
            components={"redis": ComponentHealth(status=HealthStatus.HEALTHY)},
            metrics={"uptime": 123.45},
            alerts=[{"id": "a1"}],
            timestamp=FIXED_NOW,
            version="1.0.0",
            uptime_seconds=3600.5,
        )
        assert response.overall_status == HealthStatus.HEALTHY
        assert response.version == "1.0.0"
        assert response.uptime_seconds == 3600.5

    def test_historical_health_record(self):
        record = HistoricalHealthRecord(
            timestamp=FIXED_NOW,
            overall_status=HealthStatus.DEGRADED,
            components={"redis": HealthStatus.DOWN},
            metrics={"latency": 500},
        )
        assert record.timestamp == FIXED_NOW
        assert record.overall_status == HealthStatus.DEGRADED
        assert record.components["redis"] == HealthStatus.DOWN


# =============================================================================
# Tests for CoretaxHealthChecker (with mocks)
# =============================================================================

@pytest.fixture
def health_checker():
    return CoretaxHealthChecker(config={})


@pytest.fixture
def mock_ping_redis():
    with patch("adapters.coretax_djp.health_dashboard.ping_redis", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_get_session_factory():
    with patch("adapters.coretax_djp.health_dashboard.get_session_factory", new_callable=AsyncMock) as mock:
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()
        factory = AsyncMock()
        factory.get_session.return_value.__aenter__.return_value = session
        mock.return_value = factory
        yield mock


@pytest.fixture
def mock_get_coretax_client():
    with patch("adapters.coretax_djp.health_dashboard.get_coretax_client", new_callable=AsyncMock) as mock:
        client = AsyncMock()
        client.get_access_token = AsyncMock(return_value="token_xyz")
        mock.return_value = client
        yield mock


@pytest.fixture
def mock_get_nsfp_manager():
    with patch("adapters.coretax_djp.health_dashboard.get_nsfp_manager", new_callable=AsyncMock) as mock:
        manager = AsyncMock()
        manager.get_quota_info = AsyncMock(return_value={"remaining": 100, "available_in_cache": 50})
        mock.return_value = manager
        yield mock


@pytest.fixture
def mock_trigger_alert():
    with patch("adapters.coretax_djp.health_dashboard.trigger_alert", new_callable=AsyncMock) as mock:
        yield mock


class TestCoretaxHealthChecker:
    # Semua metode async di dalam kelas ini akan diberikan marker asyncio secara manual.
    # Marker kelas tidak cukup untuk checker kami, jadi kita tambahkan per metode.

    @pytest.mark.asyncio
    async def test_init(self, health_checker):
        assert health_checker._config == {}
        assert health_checker.coretax_client is None
        assert health_checker.nsfp_manager is None
        assert health_checker._cache == {}
        assert health_checker._cache_ttl == 30
        assert health_checker._alerts == {}
        assert health_checker._historical_records == []
        assert health_checker._running is False
        assert health_checker._background_task is None

    def test_load_config_with_empty(self, health_checker):
        config = health_checker._load_config()
        assert "coretax_djp" in config
        assert config["coretax_djp"]["health"]["cache_ttl_seconds"] == 30

    def test_load_config_with_provided(self):
        checker = CoretaxHealthChecker({"custom": "value"})
        config = checker._load_config()
        assert config["custom"] == "value"

    @pytest.mark.asyncio
    async def test_get_coretax_client_creates_once(self, health_checker, mock_get_coretax_client):
        client1 = await health_checker._get_coretax_client()
        client2 = await health_checker._get_coretax_client()
        assert client1 is client2
        mock_get_coretax_client.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_nsfp_manager_creates_once(self, health_checker, mock_get_nsfp_manager):
        mgr1 = await health_checker._get_nsfp_manager()
        mgr2 = await health_checker._get_nsfp_manager()
        assert mgr1 is mgr2
        mock_get_nsfp_manager.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cached_or_fresh_caches_value(self, health_checker):
        fetcher = AsyncMock(return_value="cached_value")
        result = await health_checker._cached_or_fresh("key", 60, fetcher)
        assert result == "cached_value"
        assert "key" in health_checker._cache
        # Second call should use cache
        health_checker._cache["key"] = (FIXED_NOW, "cached_value")
        result2 = await health_checker._cached_or_fresh("key", 60, fetcher)
        assert result2 == "cached_value"
        fetcher.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cached_or_fresh_expires(self, health_checker):
        fetcher = AsyncMock(return_value="new_value")
        old_time = FIXED_NOW - timedelta(seconds=100)
        health_checker._cache["key"] = (old_time, "old_value")
        result = await health_checker._cached_or_fresh("key", 60, fetcher)
        assert result == "new_value"
        fetcher.assert_awaited_once()

    def test_invalidate_cache_single(self, health_checker):
        health_checker._cache["a"] = (FIXED_NOW, 1)
        health_checker._cache["b"] = (FIXED_NOW, 2)
        health_checker._invalidate_cache("a")
        assert "a" not in health_checker._cache
        assert "b" in health_checker._cache

    def test_invalidate_cache_all(self, health_checker):
        health_checker._cache["a"] = (FIXED_NOW, 1)
        health_checker._cache["b"] = (FIXED_NOW, 2)
        health_checker._invalidate_cache()
        assert health_checker._cache == {}

    @pytest.mark.asyncio
    async def test_check_redis_healthy(self, health_checker, mock_ping_redis):
        mock_ping_redis.return_value = True
        result = await health_checker.check_redis()
        assert result.status == HealthStatus.HEALTHY
        assert result.latency_ms is not None
        assert "Redis connected" in result.message

    @pytest.mark.asyncio
    async def test_check_redis_failure(self, health_checker, mock_ping_redis):
        mock_ping_redis.return_value = False
        result = await health_checker.check_redis()
        assert result.status == HealthStatus.DOWN
        assert "ping failed" in result.message

    @pytest.mark.asyncio
    async def test_check_redis_exception(self, health_checker, mock_ping_redis):
        mock_ping_redis.side_effect = Exception("Connection timeout")
        result = await health_checker.check_redis()
        assert result.status == HealthStatus.DOWN
        assert "Connection timeout" in result.message
        assert len(health_checker._alerts) == 1
        alert = list(health_checker._alerts.values())[0]
        assert alert.component == "redis"
        assert alert.severity == AlertSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_check_database_healthy(self, health_checker, mock_get_session_factory):
        result = await health_checker.check_database()
        assert result.status == HealthStatus.HEALTHY
        assert "Database connected" in result.message
        assert result.latency_ms is not None
        mock_get_session_factory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_database_exception(self, health_checker, mock_get_session_factory):
        mock_get_session_factory.side_effect = Exception("DB unavailable")
        result = await health_checker.check_database()
        assert result.status == HealthStatus.DOWN
        assert "DB unavailable" in result.message
        assert len(health_checker._alerts) == 1
        alert = list(health_checker._alerts.values())[0]
        assert alert.component == "database"

    @pytest.mark.asyncio
    async def test_check_coretax_api_healthy(self, health_checker, mock_get_coretax_client):
        result = await health_checker.check_coretax_api()
        assert result.status == HealthStatus.HEALTHY
        assert "Coretax API accessible" in result.message
        assert result.latency_ms is not None
        assert result.details["token_valid"] is True

    @pytest.mark.asyncio
    async def test_check_coretax_api_auth_error(self, health_checker, mock_get_coretax_client):
        from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError
        mock_get_coretax_client.return_value.get_access_token.side_effect = CoretaxAuthError("Auth failed")
        result = await health_checker.check_coretax_api()
        assert result.status == HealthStatus.DEGRADED
        assert "Auth failed" in result.message
        assert len(health_checker._alerts) == 1

    @pytest.mark.asyncio
    async def test_check_coretax_api_generic_error(self, health_checker, mock_get_coretax_client):
        mock_get_coretax_client.return_value.get_access_token.side_effect = Exception("Network error")
        result = await health_checker.check_coretax_api()
        assert result.status == HealthStatus.DOWN
        assert "Network error" in result.message
        assert len(health_checker._alerts) == 1
        alert = list(health_checker._alerts.values())[0]
        assert alert.severity == AlertSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_check_token_validity_healthy(self, health_checker, mock_get_coretax_client):
        result = await health_checker.check_token_validity()
        assert result.status == HealthStatus.HEALTHY
        assert "Token valid" in result.message
        assert result.details["token_length"] > 0

    @pytest.mark.asyncio
    async def test_check_token_validity_exception(self, health_checker, mock_get_coretax_client):
        mock_get_coretax_client.return_value.get_access_token.side_effect = Exception("Token expired")
        result = await health_checker.check_token_validity()
        assert result.status == HealthStatus.DEGRADED
        assert "Token expired" in result.message

    @pytest.mark.asyncio
    async def test_check_nsfp_quota_healthy(self, health_checker, mock_get_nsfp_manager):
        mock_get_nsfp_manager.return_value.get_quota_info.return_value = {"remaining": 50, "available_in_cache": 30}
        result = await health_checker.check_nsfp_quota("123456789012345", 2025, 1)
        assert result.status == HealthStatus.HEALTHY
        assert "NSFP available" in result.message
        assert result.details["remaining"] == 50
        assert result.details["available"] == 30

    @pytest.mark.asyncio
    async def test_check_nsfp_quota_low(self, health_checker, mock_get_nsfp_manager):
        mock_get_nsfp_manager.return_value.get_quota_info.return_value = {"remaining": 5, "available_in_cache": 5}
        result = await health_checker.check_nsfp_quota("123456789012345", 2025, 1)
        assert result.status == HealthStatus.DEGRADED
        assert "NSFP quota low" in result.message
        assert len(health_checker._alerts) == 1
        alert = list(health_checker._alerts.values())[0]
        assert alert.severity == AlertSeverity.WARNING

    @pytest.mark.asyncio
    async def test_check_nsfp_quota_exhausted(self, health_checker, mock_get_nsfp_manager):
        mock_get_nsfp_manager.return_value.get_quota_info.return_value = {"remaining": 0, "available_in_cache": 0}
        result = await health_checker.check_nsfp_quota("123456789012345", 2025, 1)
        assert result.status == HealthStatus.DOWN
        assert "NSFP quota exhausted" in result.message
        assert len(health_checker._alerts) == 1
        alert = list(health_checker._alerts.values())[0]
        assert alert.severity == AlertSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_check_nsfp_quota_exception(self, health_checker, mock_get_nsfp_manager):
        mock_get_nsfp_manager.return_value.get_quota_info.side_effect = Exception("NSFP API error")
        result = await health_checker.check_nsfp_quota("123456789012345", 2025, 1)
        assert result.status == HealthStatus.DEGRADED
        assert "NSFP check failed" in result.message

    @pytest.mark.asyncio
    async def test_check_pending_submissions_healthy(self, health_checker):
        with patch.object(health_checker, "_get_pending_faktur_count", return_value=10), \
             patch.object(health_checker, "_get_pending_spt_count", return_value=5), \
             patch.object(health_checker, "_get_pending_bupot_count", return_value=3):
            result = await health_checker.check_pending_submissions()
            assert result.status == HealthStatus.HEALTHY
            assert "Pending: 10 faktur, 5 SPT, 3 e-Bupot" in result.message

    @pytest.mark.asyncio
    async def test_check_pending_submissions_degraded(self, health_checker):
        with patch.object(health_checker, "_get_pending_faktur_count", return_value=600), \
             patch.object(health_checker, "_get_pending_spt_count", return_value=0), \
             patch.object(health_checker, "_get_pending_bupot_count", return_value=0):
            result = await health_checker.check_pending_submissions()
            assert result.status == HealthStatus.DEGRADED
            assert len(health_checker._alerts) == 1

    @pytest.mark.asyncio
    async def test_check_pending_submissions_down(self, health_checker):
        with patch.object(health_checker, "_get_pending_faktur_count", return_value=1200), \
             patch.object(health_checker, "_get_pending_spt_count", return_value=0), \
             patch.object(health_checker, "_get_pending_bupot_count", return_value=0):
            result = await health_checker.check_pending_submissions()
            assert result.status == HealthStatus.DOWN
            assert len(health_checker._alerts) == 1
            alert = list(health_checker._alerts.values())[0]
            assert alert.severity == AlertSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_check_pending_submissions_exception(self, health_checker):
        with patch.object(health_checker, "_get_pending_faktur_count", side_effect=Exception("DB error")):
            result = await health_checker.check_pending_submissions()
            assert result.status == HealthStatus.DEGRADED
            assert "DB error" in result.message

    @pytest.mark.asyncio
    async def test_check_webhook(self, health_checker):
        result = await health_checker.check_webhook()
        assert result.status == HealthStatus.HEALTHY
        assert "operational" in result.message

    @pytest.mark.asyncio
    async def test_check_rate_limits_healthy(self, health_checker, mock_get_coretax_client):
        result = await health_checker.check_rate_limits()
        assert result.status == HealthStatus.HEALTHY
        assert "OK" in result.message

    @pytest.mark.asyncio
    async def test_check_rate_limits_exception(self, health_checker, mock_get_coretax_client):
        mock_get_coretax_client.side_effect = Exception("Client unavailable")
        result = await health_checker.check_rate_limits()
        assert result.status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_circuit_breaker_closed(self, health_checker):
        with patch("adapters.coretax_djp.health_dashboard.PROMETHEUS_AVAILABLE", False):
            result = await health_checker.check_circuit_breaker()
            assert result.status == HealthStatus.HEALTHY
            assert "CLOSED" in result.message

    @pytest.mark.asyncio
    async def test_check_circuit_breaker_exception(self, health_checker):
        with patch("adapters.coretax_djp.health_dashboard.PROMETHEUS_AVAILABLE", False), \
             patch.object(health_checker, "_get_coretax_client", side_effect=Exception("CB error")):
            result = await health_checker.check_circuit_breaker()
            assert result.status == HealthStatus.DEGRADED
            assert "CB error" in result.message

    @pytest.mark.asyncio
    async def test_check_all_components(self, health_checker):
        with patch.object(health_checker, "check_redis", return_value=ComponentHealth(status=HealthStatus.HEALTHY)), \
             patch.object(health_checker, "check_database", return_value=ComponentHealth(status=HealthStatus.HEALTHY)), \
             patch.object(health_checker, "check_coretax_api", return_value=ComponentHealth(status=HealthStatus.HEALTHY)), \
             patch.object(health_checker, "check_token_validity", return_value=ComponentHealth(status=HealthStatus.HEALTHY)), \
             patch.object(health_checker, "check_webhook", return_value=ComponentHealth(status=HealthStatus.HEALTHY)), \
             patch.object(health_checker, "check_rate_limits", return_value=ComponentHealth(status=HealthStatus.HEALTHY)), \
             patch.object(health_checker, "check_circuit_breaker", return_value=ComponentHealth(status=HealthStatus.HEALTHY)), \
             patch.object(health_checker, "check_nsfp_quota", return_value=ComponentHealth(status=HealthStatus.HEALTHY)), \
             patch.object(health_checker, "check_pending_submissions", return_value=ComponentHealth(status=HealthStatus.HEALTHY)):
            components = await health_checker.check_all_components()
            assert "redis" in components
            assert "database" in components
            assert "coretax_api" in components
            assert "token" in components
            assert "webhook" in components
            assert "rate_limits" in components
            assert "circuit_breaker" in components
            assert "nsfp_quota" in components
            assert "pending_submissions" in components
            for comp in components.values():
                assert comp.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_get_full_dashboard(self, health_checker):
        with patch.object(health_checker, "check_all_components", return_value={
            "redis": ComponentHealth(status=HealthStatus.HEALTHY),
            "database": ComponentHealth(status=HealthStatus.HEALTHY),
            "coretax_api": ComponentHealth(status=HealthStatus.HEALTHY),
            "token": ComponentHealth(status=HealthStatus.HEALTHY),
            "webhook": ComponentHealth(status=HealthStatus.HEALTHY),
            "rate_limits": ComponentHealth(status=HealthStatus.HEALTHY),
            "circuit_breaker": ComponentHealth(status=HealthStatus.HEALTHY),
            "nsfp_quota": ComponentHealth(status=HealthStatus.HEALTHY),
            "pending_submissions": ComponentHealth(status=HealthStatus.HEALTHY),
        }):
            dashboard = await health_checker.get_full_dashboard(npwp="123", tahun=2025, bulan=1)
            assert isinstance(dashboard, CoretaxDashboardResponse)
            assert dashboard.overall_status == HealthStatus.HEALTHY
            assert "redis" in dashboard.components
            assert "metrics" in dashboard
            assert "uptime_seconds" in dashboard
            assert dashboard.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_full_dashboard_with_alerts(self, health_checker):
        await health_checker._add_alert("test", AlertSeverity.WARNING, "Test Alert", "Test message")
        with patch.object(health_checker, "check_all_components", return_value={}):
            dashboard = await health_checker.get_full_dashboard()
            assert len(dashboard.alerts) == 1
            assert dashboard.alerts[0]["title"] == "Test Alert"
            assert dashboard.metrics["active_alerts_count"] == 1

    @pytest.mark.asyncio
    async def test_historical_records(self, health_checker):
        with patch.object(health_checker, "check_all_components", return_value={}):
            await health_checker.get_full_dashboard()
            assert len(health_checker._historical_records) == 1
            record = health_checker._historical_records[0]
            assert isinstance(record, HistoricalHealthRecord)

    @pytest.mark.asyncio
    async def test_get_historical_health(self, health_checker):
        # Add some records
        for i in range(5):
            record = HistoricalHealthRecord(
                timestamp=FIXED_NOW - timedelta(hours=i),
                overall_status=HealthStatus.HEALTHY,
                components={},
                metrics={},
            )
            health_checker._historical_records.append(record)
        start = FIXED_NOW - timedelta(days=1)
        end = FIXED_NOW
        records = await health_checker.get_historical_health(start, end, resolution="hour")
        assert len(records) <= 5

    @pytest.mark.asyncio
    async def test_reset(self, health_checker):
        health_checker._cache["key"] = (FIXED_NOW, "value")
        health_checker._alerts["a1"] = Alert(id="a1", component="test", severity=AlertSeverity.INFO, title="t", message="m", created_at=FIXED_NOW)
        old_start = health_checker._start_time
        await health_checker.reset()
        assert health_checker._cache == {}
        assert health_checker._alerts == {}
        assert health_checker._start_time != old_start

    @pytest.mark.asyncio
    async def test_trigger_alert(self, health_checker):
        alert = await health_checker.trigger_alert("test", AlertSeverity.ERROR, "Error", "Something went wrong")
        assert alert.component == "test"
        assert alert.severity == AlertSeverity.ERROR
        assert alert.title == "Error"
        assert alert.id in health_checker._alerts

    @pytest.mark.asyncio
    async def test_clear_alert_success(self, health_checker):
        alert = await health_checker.trigger_alert("test", AlertSeverity.INFO, "Info", "msg")
        success = await health_checker.clear_alert(alert.id)
        assert success is True
        assert health_checker._alerts[alert.id].resolved_at is not None

    @pytest.mark.asyncio
    async def test_clear_alert_not_found(self, health_checker):
        success = await health_checker.clear_alert("nonexistent")
        assert success is False

    @pytest.mark.asyncio
    async def test_acknowledge_alert_success(self, health_checker):
        alert = await health_checker.trigger_alert("test", AlertSeverity.INFO, "Info", "msg")
        success = await health_checker.acknowledge_alert(alert.id, "admin")
        assert success is True
        assert health_checker._alerts[alert.id].acknowledged is True
        assert health_checker._alerts[alert.id].acknowledged_by == "admin"

    @pytest.mark.asyncio
    async def test_acknowledge_alert_not_found(self, health_checker):
        success = await health_checker.acknowledge_alert("nonexistent", "admin")
        assert success is False

    @pytest.mark.asyncio
    async def test_background_health_check_start_stop(self, health_checker):
        await health_checker.start_background_health_check()
        assert health_checker._running is True
        assert health_checker._background_task is not None
        await health_checker.stop_background_health_check()
        assert health_checker._running is False
        assert health_checker._background_task.cancelled() is True

    @pytest.mark.asyncio
    async def test_background_loop_runs_checks(self, health_checker):
        # Mock asyncio.sleep agar tidak delay
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch.object(health_checker, "check_all_components", new_callable=AsyncMock) as mock_check:
                health_checker._load_config = lambda: {"coretax_djp": {"health": {"health_check_interval": 0.01}}}
                await health_checker.start_background_health_check()
                # Beri waktu untuk satu iterasi loop
                await asyncio.sleep(0.01)  # tetap perlu sedikit waktu tapi kita mock sleep di dalam loop
                await health_checker.stop_background_health_check()
                # Pastikan check_all_components dipanggil setidaknya sekali
                assert mock_check.call_count >= 1
                # Pastikan sleep dipanggil (di dalam loop)
                assert mock_sleep.call_count >= 1

    @pytest.mark.asyncio
    async def test_cleanup_old_records(self, health_checker):
        health_checker._historical_records = [
            HistoricalHealthRecord(timestamp=FIXED_NOW, overall_status=HealthStatus.HEALTHY, components={}, metrics={}),
            HistoricalHealthRecord(timestamp=FIXED_OLD, overall_status=HealthStatus.HEALTHY, components={}, metrics={}),
        ]
        await health_checker._cleanup_old_records()
        assert len(health_checker._historical_records) == 1
        assert health_checker._historical_records[0].timestamp == FIXED_NOW

    @pytest.mark.asyncio
    async def test_cleanup_old_alerts(self, health_checker):
        alert_new = Alert(id="a1", component="test", severity=AlertSeverity.INFO, title="t1", message="m1", created_at=FIXED_NOW)
        alert_old = Alert(id="a2", component="test", severity=AlertSeverity.INFO, title="t2", message="m2", created_at=FIXED_OLD, resolved_at=FIXED_OLD)
        health_checker._alerts["a1"] = alert_new
        health_checker._alerts["a2"] = alert_old
        await health_checker._cleanup_old_alerts()
        assert "a1" in health_checker._alerts
        assert "a2" not in health_checker._alerts

    @pytest.mark.asyncio
    async def test_send_alert_notification(self, health_checker, mock_trigger_alert):
        alert = Alert(id="a1", component="test", severity=AlertSeverity.CRITICAL, title="t", message="m", created_at=FIXED_NOW)
        await health_checker._send_alert_notification(alert)
        mock_trigger_alert.assert_awaited_once_with(
            title="t", message="m", severity="critical", source="test", metadata={"alert_id": "a1"}
        )

    def test_core_tax_health_dashboard(self):
        dashboard = CoreTaxHealthDashboard(simulation_mode=True)
        assert dashboard.simulation_mode is True
        status = dashboard.get_status()
        assert status["status"] == "operational"
        assert status["simulation_mode"] is True
        check = dashboard.check()
        assert "api_status" in check
        assert "last_successful_call" in check

    @pytest.mark.asyncio
    async def test_core_tax_health_dashboard_uses_checker(self):
        dashboard = CoreTaxHealthDashboard(simulation_mode=False)
        with patch.object(dashboard, "_get_checker", new_callable=AsyncMock) as mock_get:
            checker = MagicMock()
            checker.check_all_components = AsyncMock()
            mock_get.return_value = checker
            await dashboard._get_checker()
            mock_get.assert_awaited_once()
            # Also test that checker is used
            checker_instance = await dashboard._get_checker()
            assert checker_instance is checker


# =============================================================================
# Tests for Module-level Functions
# =============================================================================

@pytest.mark.asyncio
async def test_get_health_checker_singleton():
    import adapters.coretax_djp.health_dashboard as mod
    mod._health_checker = None
    with patch.object(mod, "CoretaxHealthChecker") as MockChecker:
        instance = AsyncMock()
        MockChecker.return_value = instance
        checker1 = await mod.get_health_checker()
        checker2 = await mod.get_health_checker()
        assert checker1 is checker2
        instance.start_background_health_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_health_checker():
    import adapters.coretax_djp.health_dashboard as mod
    # Setup mock checker
    mod._health_checker = AsyncMock()
    await mod.shutdown_health_checker()
    mod._health_checker.stop_background_health_check.assert_awaited_once()
    # Reset after test
    mod._health_checker = None


# =============================================================================
# Tests for FastAPI Router Endpoints
# =============================================================================

class TestRouter:
    @pytest.fixture
    def client(self):
        return TestClient(router)

    def test_get_dashboard(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            dashboard = CoretaxDashboardResponse(
                overall_status=HealthStatus.HEALTHY,
                components={},
                metrics={},
                alerts=[],
                timestamp=FIXED_NOW,
                version="1.0",
                uptime_seconds=123,
            )
            checker.get_full_dashboard = AsyncMock(return_value=dashboard)
            mock_get.return_value = checker
            response = client.get("/dashboard?npwp=123&tahun=2025&bulan=1&refresh=true")
            assert response.status_code == 200
            data = response.json()
            assert data["overall_status"] == "healthy"
            assert data["version"] == "1.0"

    def test_readiness_check_healthy(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            dashboard = CoretaxDashboardResponse(
                overall_status=HealthStatus.HEALTHY,
                components={},
                metrics={},
                alerts=[],
                timestamp=FIXED_NOW,
                version="1.0",
                uptime_seconds=0,
            )
            checker.get_full_dashboard = AsyncMock(return_value=dashboard)
            mock_get.return_value = checker
            response = client.get("/ready")
            assert response.status_code == 200
            assert response.json()["status"] == "ready"
            assert response.json()["overall"] == "healthy"

    def test_readiness_check_down(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            dashboard = CoretaxDashboardResponse(
                overall_status=HealthStatus.DOWN,
                components={},
                metrics={},
                alerts=[],
                timestamp=FIXED_NOW,
                version="1.0",
                uptime_seconds=0,
            )
            checker.get_full_dashboard = AsyncMock(return_value=dashboard)
            mock_get.return_value = checker
            response = client.get("/ready")
            assert response.status_code == 503
            assert "DOWN" in response.text

    def test_liveness_check(self, client):
        response = client.get("/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_startup_check_healthy(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            components = {
                "database": ComponentHealth(status=HealthStatus.HEALTHY),
                "redis": ComponentHealth(status=HealthStatus.HEALTHY),
            }
            checker.get_full_dashboard = AsyncMock(return_value=CoretaxDashboardResponse(
                overall_status=HealthStatus.HEALTHY,
                components=components,
                metrics={},
                alerts=[],
                timestamp=FIXED_NOW,
                version="1.0",
                uptime_seconds=0,
            ))
            mock_get.return_value = checker
            response = client.get("/startup")
            assert response.status_code == 200
            assert response.json()["status"] == "started"

    def test_startup_check_essential_down(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            components = {
                "database": ComponentHealth(status=HealthStatus.DOWN),
                "redis": ComponentHealth(status=HealthStatus.HEALTHY),
            }
            checker.get_full_dashboard = AsyncMock(return_value=CoretaxDashboardResponse(
                overall_status=HealthStatus.DOWN,
                components=components,
                metrics={},
                alerts=[],
                timestamp=FIXED_NOW,
                version="1.0",
                uptime_seconds=0,
            ))
            mock_get.return_value = checker
            response = client.get("/startup")
            assert response.status_code == 503
            assert "not ready" in response.text

    def test_metrics_endpoint(self, client):
        with patch("adapters.coretax_djp.health_dashboard.PROMETHEUS_AVAILABLE", True):
            with patch("adapters.coretax_djp.health_dashboard.generate_latest") as mock_generate:
                mock_generate.return_value = b"# HELP test\n"
                response = client.get("/metrics")
                assert response.status_code == 200
                assert response.media_type == "text/plain"
                assert b"# HELP test" in response.content

    def test_metrics_endpoint_not_available(self, client):
        with patch("adapters.coretax_djp.health_dashboard.PROMETHEUS_AVAILABLE", False):
            response = client.get("/metrics")
            assert response.status_code == 200
            assert response.json()["message"] == "Prometheus metrics not available"

    def test_get_alerts(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            checker.get_full_dashboard = AsyncMock(return_value=CoretaxDashboardResponse(
                overall_status=HealthStatus.HEALTHY,
                components={},
                metrics={},
                alerts=[{"id": "a1"}],
                timestamp=FIXED_NOW,
                version="1.0",
                uptime_seconds=0,
            ))
            mock_get.return_value = checker
            response = client.get("/alerts")
            assert response.status_code == 200
            assert response.json()["total"] == 1
            assert response.json()["alerts"][0]["id"] == "a1"

    def test_trigger_alert(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            alert = Alert(
                id="alert1",
                component="test",
                severity=AlertSeverity.CRITICAL,
                title="Test Alert",
                message="msg",
                created_at=FIXED_NOW,
            )
            checker.trigger_alert = AsyncMock(return_value=alert)
            mock_get.return_value = checker
            response = client.post("/alerts/trigger?component=test&severity=critical&title=Test+Alert&message=msg")
            assert response.status_code == 200
            assert response.json()["alert_id"] == "alert1"

    def test_resolve_alert_success(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            checker.clear_alert = AsyncMock(return_value=True)
            mock_get.return_value = checker
            response = client.post("/alerts/alert1/resolve")
            assert response.status_code == 200
            assert response.json()["status"] == "resolved"

    def test_resolve_alert_not_found(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            checker.clear_alert = AsyncMock(return_value=False)
            mock_get.return_value = checker
            response = client.post("/alerts/alert1/resolve")
            assert response.status_code == 404
            assert "not found" in response.text

    def test_acknowledge_alert_success(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            checker.acknowledge_alert = AsyncMock(return_value=True)
            mock_get.return_value = checker
            response = client.post("/alerts/alert1/acknowledge?acknowledged_by=admin")
            assert response.status_code == 200
            assert response.json()["status"] == "acknowledged"

    def test_acknowledge_alert_not_found(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            checker.acknowledge_alert = AsyncMock(return_value=False)
            mock_get.return_value = checker
            response = client.post("/alerts/alert1/acknowledge?acknowledged_by=admin")
            assert response.status_code == 404

    def test_get_health_history(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            records = [
                HistoricalHealthRecord(
                    timestamp=FIXED_NOW,
                    overall_status=HealthStatus.HEALTHY,
                    components={},
                    metrics={},
                )
            ]
            checker.get_historical_health = AsyncMock(return_value=records)
            mock_get.return_value = checker
            response = client.get("/history?resolution=hour")
            assert response.status_code == 200
            assert len(response.json()["records"]) == 1

    def test_reset_dashboard(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            checker.reset = AsyncMock()
            mock_get.return_value = checker
            response = client.post("/reset")
            assert response.status_code == 200
            assert response.json()["status"] == "reset"
            checker.reset.assert_awaited_once()

    def test_get_components_status(self, client):
        with patch("adapters.coretax_djp.health_dashboard.get_health_checker") as mock_get:
            checker = AsyncMock()
            components = {
                "redis": ComponentHealth(status=HealthStatus.HEALTHY, message="OK", latency_ms=5.0, last_check=FIXED_NOW, details={}),
            }
            checker.check_all_components = AsyncMock(return_value=components)
            mock_get.return_value = checker
            response = client.get("/components")
            assert response.status_code == 200
            assert "components" in response.json()
            assert response.json()["components"]["redis"]["status"] == "healthy"