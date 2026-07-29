#!/usr/bin/env python3
"""
Comprehensive tests for disaster_recovery/dr_rto_rpo_verification_test.py
Covers all methods with proper mocking and edge cases.
"""

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from disaster_recovery.dr_rto_rpo_verification_test import (
    DRMetrics,
    RTO_RPO_VerificationTest,
    TestScenario,
    TestSchedule,
    TestStatus,
)

# ============================================================================
# Prevent pytest from collecting these imported classes as test classes
# ============================================================================
TestSchedule.__test__ = False
TestScenario.__test__ = False
TestStatus.__test__ = False


# -------------------- Fixtures --------------------
@pytest.fixture
def fixed_datetime():
    """Fixed datetime for reproducible tests."""
    return datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def sample_dr_metrics(fixed_datetime):
    return DRMetrics(
        test_id="test-123",
        scenario=TestScenario.DATABASE_FAILOVER,
        start_time=fixed_datetime,
        end_time=fixed_datetime + timedelta(seconds=10),
        rto_actual_seconds=Decimal("8.5"),
        rpo_actual_seconds=Decimal("3.2"),
        rto_target_seconds=Decimal("10"),
        rpo_target_seconds=Decimal("5"),
        rto_met=True,
        rpo_met=True,
        status=TestStatus.SUCCESS,
        data_loss_bytes=1024,
        transaction_loss_count=5,
        data_loss_percentage=Decimal("0.5"),
        failure_timestamp=fixed_datetime,
        recovery_timestamp=fixed_datetime + timedelta(seconds=10),
        details={"note": "ok"},
        error_message=None,
    )


@pytest.fixture
def sample_test_schedule(fixed_datetime):
    return TestSchedule(
        schedule_id="schedule-1",
        scenario=TestScenario.DATABASE_FAILOVER,
        interval_seconds=3600,
        next_run=fixed_datetime + timedelta(hours=1),
        last_run=fixed_datetime,
        enabled=True,
        notification_webhook="https://webhook.example.com",
    )


@pytest.fixture
def mock_time(monkeypatch):
    """Mock time.time and time.sleep."""
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    monkeypatch.setattr(time, "sleep", lambda x: None)


@pytest.fixture
def mock_datetime(monkeypatch, fixed_datetime):
    """Mock datetime.utcnow to return fixed time."""
    class MockDateTime:
        @classmethod
        def utcnow(cls):
            return fixed_datetime
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_datetime
            return fixed_datetime.replace(tzinfo=tz)
        @classmethod
        def fromisoformat(cls, iso):
            return datetime.fromisoformat(iso)
    monkeypatch.setattr("disaster_recovery.dr_rto_rpo_verification_test.datetime", MockDateTime)
    return MockDateTime


@pytest.fixture
def mock_requests(monkeypatch):
    """Mock requests.post."""
    mock_post = MagicMock()
    monkeypatch.setattr("disaster_recovery.dr_rto_rpo_verification_test.requests", MagicMock(post=mock_post))
    return mock_post


@pytest.fixture
def mock_thread(monkeypatch):
    """Mock threading.Thread to execute target immediately (or not) for control."""
    def mock_thread_init(self, *args, **kwargs):
        self._target = kwargs.get("target")
        self._args = kwargs.get("args", ())
        self._kwargs = kwargs.get("kwargs", {})
        self.daemon = kwargs.get("daemon", False)
        self._started = False

    def mock_thread_start(self):
        self._started = True
        # Execute synchronously for test control
        if self._target:
            self._target(*self._args, **self._kwargs)

    def mock_thread_join(self, timeout=None):
        pass

    monkeypatch.setattr(threading.Thread, "__init__", mock_thread_init)
    monkeypatch.setattr(threading.Thread, "start", mock_thread_start)
    monkeypatch.setattr(threading.Thread, "join", mock_thread_join)
    monkeypatch.setattr(threading.Thread, "is_alive", lambda self: not self._started)


@pytest.fixture
def rto_rpo_tester(mock_datetime, mock_time):
    """Create an instance with mocked time."""
    tester = RTO_RPO_VerificationTest(rto_target_seconds=10, rpo_target_seconds=5, max_test_duration_seconds=30, enable_prometheus=False)
    return tester


# -------------------- Tests for DRMetrics --------------------
class TestDRMetrics:
    def test_construction(self, fixed_datetime):
        metrics = DRMetrics(
            test_id="test-1",
            scenario=TestScenario.DATABASE_FAILOVER,
            start_time=fixed_datetime,
            end_time=fixed_datetime + timedelta(seconds=5),
            rto_actual_seconds=Decimal("4.5"),
            rpo_actual_seconds=Decimal("1.2"),
            rto_target_seconds=Decimal("5"),
            rpo_target_seconds=Decimal("2"),
            rto_met=True,
            rpo_met=True,
            status=TestStatus.SUCCESS,
        )
        assert metrics.test_id == "test-1"
        assert metrics._version == 1
        assert len(metrics._snapshots) == 1
        snap = metrics._snapshots[0]
        assert snap["test_id"] == "test-1"
        assert snap["status"] == "success"

    def test_is_compliant(self, sample_dr_metrics):
        assert sample_dr_metrics.is_compliant() is True
        non_comp = DRMetrics(
            test_id="x", scenario=TestScenario.DATABASE_FAILOVER,
            start_time=datetime.now(UTC), end_time=datetime.now(UTC),
            rto_actual_seconds=Decimal("15"), rpo_actual_seconds=Decimal("1"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=False, rpo_met=True, status=TestStatus.SUCCESS,
        )
        assert non_comp.is_compliant() is False
        fail = DRMetrics(
            test_id="x", scenario=TestScenario.DATABASE_FAILOVER,
            start_time=datetime.now(UTC), end_time=datetime.now(UTC),
            rto_actual_seconds=Decimal("5"), rpo_actual_seconds=Decimal("1"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=True, rpo_met=True, status=TestStatus.FAILED,
        )
        assert fail.is_compliant() is False

    def test_to_dict(self, sample_dr_metrics):
        d = sample_dr_metrics.to_dict()
        assert d["test_id"] == "test-123"
        assert d["scenario"] == "database_failover"
        assert d["rto_actual_seconds"] == 8.5
        assert d["rpo_actual_seconds"] == 3.2
        assert d["rto_target_seconds"] == 10.0
        assert d["rpo_target_seconds"] == 5.0
        assert d["rto_met"] is True
        assert d["rpo_met"] is True
        assert d["status"] == "success"
        assert d["data_loss_percentage"] == 0.5
        assert d["version"] == 1

    def test_from_dict(self, sample_dr_metrics):
        d = sample_dr_metrics.to_dict()
        restored = DRMetrics.from_dict(d)
        assert restored.test_id == sample_dr_metrics.test_id
        assert restored.scenario == sample_dr_metrics.scenario
        assert restored.rto_actual_seconds == sample_dr_metrics.rto_actual_seconds
        assert restored.rpo_actual_seconds == sample_dr_metrics.rpo_actual_seconds
        assert restored.rto_target_seconds == sample_dr_metrics.rto_target_seconds
        assert restored.rpo_target_seconds == sample_dr_metrics.rpo_target_seconds
        assert restored.rto_met == sample_dr_metrics.rto_met
        assert restored.rpo_met == sample_dr_metrics.rpo_met
        assert restored.status == sample_dr_metrics.status
        assert restored._version == sample_dr_metrics._version

    def test_from_dict_missing_fields(self, sample_dr_metrics):
        d = sample_dr_metrics.to_dict()
        del d["data_loss_bytes"]
        del d["transaction_loss_count"]
        del d["data_loss_percentage"]
        del d["failure_timestamp"]
        del d["recovery_timestamp"]
        restored = DRMetrics.from_dict(d)
        assert restored.data_loss_bytes is None
        assert restored.transaction_loss_count is None
        assert restored.data_loss_percentage is None
        assert restored.failure_timestamp is None
        assert restored.recovery_timestamp is None

    def test_clone(self, sample_dr_metrics):
        cloned = sample_dr_metrics.clone()
        assert cloned.test_id != sample_dr_metrics.test_id
        assert cloned.scenario == sample_dr_metrics.scenario
        assert cloned.rto_actual_seconds == sample_dr_metrics.rto_actual_seconds
        assert cloned.rpo_actual_seconds == sample_dr_metrics.rpo_actual_seconds
        assert cloned._version == sample_dr_metrics._version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"
        assert cloned.details == sample_dr_metrics.details

    def test_snapshot(self, sample_dr_metrics):
        snap = sample_dr_metrics.snapshot()
        assert snap["version"] == sample_dr_metrics._version
        assert snap["test_id"] == "test-123"
        assert snap["scenario"] == "database_failover"
        assert snap["status"] == "success"
        assert snap["rto_met"] is True
        assert snap["rpo_met"] is True
        assert "timestamp" in snap

    def test_version(self, sample_dr_metrics):
        assert sample_dr_metrics.version() == sample_dr_metrics._version

    def test_audit_trail(self, sample_dr_metrics):
        sample_dr_metrics.touch("tester")
        trail = sample_dr_metrics.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"

    def test_touch(self, sample_dr_metrics):
        old_version = sample_dr_metrics._version
        touched = sample_dr_metrics.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1

    def test_to_prometheus_metrics_when_enabled(self, sample_dr_metrics):
        with patch("disaster_recovery.dr_rto_rpo_verification_test.HAS_PROMETHEUS", True):
            with patch("disaster_recovery.dr_rto_rpo_verification_test.Gauge") as mock_gauge:
                mock_gauge_instance = MagicMock()
                mock_gauge.return_value = mock_gauge_instance
                sample_dr_metrics.to_prometheus_metrics()
                assert mock_gauge.call_count == 2
                mock_gauge_instance.labels.assert_any_call(scenario="database_failover", test_id="test-123")

    def test_to_prometheus_metrics_disabled(self, sample_dr_metrics):
        with patch("disaster_recovery.dr_rto_rpo_verification_test.HAS_PROMETHEUS", False):
            sample_dr_metrics.to_prometheus_metrics()  # should not raise


# -------------------- Tests for TestSchedule --------------------
class TestTestSchedule:
    def test_construction(self, fixed_datetime):
        schedule = TestSchedule(
            schedule_id="s1",
            scenario=TestScenario.BACKUP_RESTORE,
            interval_seconds=600,
            next_run=fixed_datetime,
        )
        assert schedule.schedule_id == "s1"
        assert schedule._version == 1
        assert len(schedule._snapshots) == 1

    def test_validate_valid(self, sample_test_schedule):
        result = sample_test_schedule.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_empty_schedule_id(self):
        sched = TestSchedule(
            schedule_id="",
            scenario=TestScenario.DATABASE_FAILOVER,
            interval_seconds=10,
            next_run=datetime.now(UTC),
        )
        result = sched.validate()
        assert result["is_valid"] is False
        assert "schedule_id is required" in result["errors"]

    def test_validate_invalid_negative_interval(self):
        sched = TestSchedule(
            schedule_id="s1",
            scenario=TestScenario.DATABASE_FAILOVER,
            interval_seconds=-1,
            next_run=datetime.now(UTC),
        )
        result = sched.validate()
        assert result["is_valid"] is False
        assert "interval_seconds must be positive" in result["errors"]

    def test_to_dict(self, sample_test_schedule):
        d = sample_test_schedule.to_dict()
        assert d["schedule_id"] == "schedule-1"
        assert d["scenario"] == "database_failover"
        assert d["interval_seconds"] == 3600
        assert "next_run" in d
        assert "last_run" in d
        assert d["enabled"] is True
        assert d["notification_webhook"] == "https://webhook.example.com"
        assert d["version"] == 1

    def test_from_dict(self, sample_test_schedule):
        d = sample_test_schedule.to_dict()
        restored = TestSchedule.from_dict(d)
        assert restored.schedule_id == sample_test_schedule.schedule_id
        assert restored.scenario == sample_test_schedule.scenario
        assert restored.interval_seconds == sample_test_schedule.interval_seconds
        assert restored.enabled == sample_test_schedule.enabled
        assert restored.notification_webhook == sample_test_schedule.notification_webhook
        assert restored._version == sample_test_schedule._version

    def test_from_dict_with_last_result(self, sample_test_schedule, sample_dr_metrics):
        d = sample_test_schedule.to_dict()
        d["last_result"] = sample_dr_metrics.to_dict()
        restored = TestSchedule.from_dict(d)
        assert restored.last_result is not None
        assert restored.last_result.test_id == sample_dr_metrics.test_id

    def test_clone(self, sample_test_schedule):
        cloned = sample_test_schedule.clone()
        assert cloned.schedule_id != sample_test_schedule.schedule_id
        assert cloned.scenario == sample_test_schedule.scenario
        assert cloned.interval_seconds == sample_test_schedule.interval_seconds
        assert cloned._version == sample_test_schedule._version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_test_schedule):
        snap = sample_test_schedule.snapshot()
        assert snap["version"] == sample_test_schedule._version
        assert snap["schedule_id"] == "schedule-1"
        assert snap["scenario"] == "database_failover"
        assert snap["enabled"] is True
        assert "timestamp" in snap

    def test_version(self, sample_test_schedule):
        assert sample_test_schedule.version() == sample_test_schedule._version

    def test_audit_trail(self, sample_test_schedule):
        sample_test_schedule.touch("tester")
        trail = sample_test_schedule.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, sample_test_schedule):
        old_version = sample_test_schedule._version
        touched = sample_test_schedule.touch("tester")
        assert touched._version == old_version + 1


# -------------------- Tests for RTO_RPO_VerificationTest --------------------
class TestRTO_RPO_VerificationTest:
    def test_construction(self, rto_rpo_tester):
        assert rto_rpo_tester.rto_target == Decimal("10")
        assert rto_rpo_tester.rpo_target == Decimal("5")
        assert rto_rpo_tester.max_duration == Decimal("30")
        assert rto_rpo_tester.enable_prometheus is False
        assert rto_rpo_tester._metrics_history == []
        assert rto_rpo_tester._schedules == {}
        assert rto_rpo_tester._version == 1
        assert len(rto_rpo_tester._snapshots) == 1

    def test_validate_valid(self, rto_rpo_tester):
        result = rto_rpo_tester.validate()
        assert result["is_valid"] is True

    def test_validate_invalid(self):
        tester = RTO_RPO_VerificationTest(rto_target_seconds=-1, rpo_target_seconds=0, max_test_duration_seconds=0)
        result = tester.validate()
        assert result["is_valid"] is False
        errors = result["errors"]
        assert any("rto_target_seconds must be positive" in e for e in errors)
        assert any("rpo_target_seconds must be positive" in e for e in errors)
        assert any("max_test_duration_seconds must be positive" in e for e in errors)

    def test_simulate_failure_success(self, rto_rpo_tester, mock_datetime, mock_time):
        failover_func = MagicMock(return_value="ok")
        with patch("time.time") as mock_time_time:
            mock_time_time.side_effect = [1000.0, 1005.0]
            metrics = rto_rpo_tester.simulate_failure(failover_func, scenario=TestScenario.DATABASE_FAILOVER)
            assert metrics.status == TestStatus.SUCCESS
            assert metrics.rto_actual_seconds == Decimal("5.0")
            assert metrics.rpo_actual_seconds == Decimal("0")
            assert metrics.rto_met is True
            assert metrics.rpo_met is True
            assert metrics.is_compliant() is True
            assert len(rto_rpo_tester._metrics_history) == 1
            trail = rto_rpo_tester.audit_trail()
            assert any(entry["action"] == "SIMULATE_FAILURE" for entry in trail)

    def test_simulate_failure_timeout(self, rto_rpo_tester, mock_datetime, mock_time):
        def slow_func():
            time.sleep(100)
            return "ok"
        with patch("time.time") as mock_time_time:
            mock_time_time.side_effect = [1000.0, 1020.0]
            with patch("threading.Thread.join") as mock_join:
                mock_join.side_effect = None
                with patch("threading.Thread.is_alive") as mock_is_alive:
                    mock_is_alive.return_value = True
                    metrics = rto_rpo_tester.simulate_failure(slow_func, timeout_seconds=30)
                    assert metrics.status == TestStatus.TIMEOUT
                    assert metrics.error_message == "Failover timeout after 30 seconds"
                    assert metrics.rto_met is False

    def test_simulate_failure_exception(self, rto_rpo_tester, mock_datetime, mock_time):
        def failing_func():
            raise ValueError("Something went wrong")
        with patch("time.time") as mock_time_time:
            mock_time_time.side_effect = [1000.0, 1002.0]
            metrics = rto_rpo_tester.simulate_failure(failing_func)
            assert metrics.status == TestStatus.FAILED
            assert "Something went wrong" in metrics.error_message
            assert metrics.rto_met is False

    def test_simulate_failure_with_hooks(self, rto_rpo_tester, mock_datetime, mock_time):
        pre_hook = MagicMock()
        post_hook = MagicMock()
        failover = MagicMock(return_value="ok")
        with patch("time.time") as mock_time_time:
            mock_time_time.side_effect = [1000.0, 1003.0]
            metrics = rto_rpo_tester.simulate_failure(failover, pre_failure_hook=pre_hook, post_recovery_hook=post_hook)
            pre_hook.assert_called_once()
            post_hook.assert_called_once()
            assert metrics.status == TestStatus.SUCCESS

    def test_simulate_failure_prometheus_enabled(self, rto_rpo_tester, mock_datetime, mock_time):
        rto_rpo_tester.enable_prometheus = True
        with patch("disaster_recovery.dr_rto_rpo_verification_test.HAS_PROMETHEUS", True):
            with patch("disaster_recovery.dr_rto_rpo_verification_test.Gauge") as mock_gauge:
                mock_gauge_instance = MagicMock()
                mock_gauge.return_value = mock_gauge_instance
                failover = MagicMock(return_value="ok")
                with patch("time.time") as mock_time_time:
                    mock_time_time.side_effect = [1000.0, 1004.0]
                    metrics = rto_rpo_tester.simulate_failure(failover)
                    mock_gauge.assert_called()

    def test_run_with_timeout_success(self, rto_rpo_tester):
        func = MagicMock(return_value="result")
        result = rto_rpo_tester._run_with_timeout(func, timeout=10)
        assert result == "result"
        func.assert_called_once()

    def test_run_with_timeout_timeout(self, rto_rpo_tester):
        def slow_func():
            time.sleep(100)
            return "ok"
        with patch("threading.Thread.join") as mock_join:
            with patch("threading.Thread.is_alive") as mock_is_alive:
                mock_is_alive.return_value = True
                with pytest.raises(TimeoutError):
                    rto_rpo_tester._run_with_timeout(slow_func, timeout=1)

    def test_run_with_timeout_exception(self, rto_rpo_tester):
        def error_func():
            raise ValueError("bad")
        with patch("threading.Thread.join"):
            with pytest.raises(ValueError, match="bad"):
                rto_rpo_tester._run_with_timeout(error_func, timeout=10)

    def test_get_last_metrics(self, rto_rpo_tester, sample_dr_metrics):
        assert rto_rpo_tester.get_last_metrics() is None
        rto_rpo_tester._metrics_history.append(sample_dr_metrics)
        assert rto_rpo_tester.get_last_metrics() == sample_dr_metrics
        assert rto_rpo_tester.get_last_metrics(TestScenario.DATABASE_FAILOVER) == sample_dr_metrics
        assert rto_rpo_tester.get_last_metrics(TestScenario.BACKUP_RESTORE) is None

    def test_get_test_history(self, rto_rpo_tester, sample_dr_metrics):
        m1 = sample_dr_metrics
        m2 = sample_dr_metrics.clone()
        m2.scenario = TestScenario.BACKUP_RESTORE
        rto_rpo_tester._metrics_history.extend([m1, m2])
        history = rto_rpo_tester.get_test_history(limit=10)
        assert len(history) == 2
        history_db = rto_rpo_tester.get_test_history(scenario=TestScenario.DATABASE_FAILOVER)
        assert len(history_db) == 1
        assert history_db[0].scenario == TestScenario.DATABASE_FAILOVER

    def test_get_compliance_report_no_tests(self, rto_rpo_tester, fixed_datetime):
        with patch("disaster_recovery.dr_rto_rpo_verification_test.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_datetime
            report = rto_rpo_tester.get_compliance_report(period_days=30)
            assert report["status"] == "not_tested"
            assert report["total_tests"] == 0

    def test_get_compliance_report_with_tests(self, rto_rpo_tester, fixed_datetime):
        m1 = DRMetrics(
            test_id="1", scenario=TestScenario.DATABASE_FAILOVER,
            start_time=fixed_datetime - timedelta(days=5),
            end_time=fixed_datetime - timedelta(days=5),
            rto_actual_seconds=Decimal("8"), rpo_actual_seconds=Decimal("3"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=True, rpo_met=True, status=TestStatus.SUCCESS,
        )
        m2 = DRMetrics(
            test_id="2", scenario=TestScenario.BACKUP_RESTORE,
            start_time=fixed_datetime - timedelta(days=10),
            end_time=fixed_datetime - timedelta(days=10),
            rto_actual_seconds=Decimal("15"), rpo_actual_seconds=Decimal("6"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=False, rpo_met=False, status=TestStatus.SUCCESS,
        )
        m3 = DRMetrics(
            test_id="3", scenario=TestScenario.CROSS_REGION_FAILOVER,
            start_time=fixed_datetime - timedelta(days=1),
            end_time=fixed_datetime - timedelta(days=1),
            rto_actual_seconds=Decimal("9"), rpo_actual_seconds=Decimal("4"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=True, rpo_met=True, status=TestStatus.SUCCESS,
        )
        rto_rpo_tester._metrics_history.extend([m1, m2, m3])
        with patch("disaster_recovery.dr_rto_rpo_verification_test.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_datetime
            report = rto_rpo_tester.get_compliance_report(period_days=30)
            assert report["total_tests"] == 3
            assert report["successful_tests"] == 3
            assert report["rto_compliant_count"] == 2
            assert report["rpo_compliant_count"] == 2
            assert report["fully_compliant_count"] == 2
            assert report["overall_compliance_rate"] == 66.67
            assert report["status"] == "partially_compliant"
            assert "avg_rto_seconds" in report
            assert report["rto_target"] == 10.0
            assert report["rpo_target"] == 5.0

    def test_get_compliance_report_all_compliant(self, rto_rpo_tester, fixed_datetime):
        m1 = DRMetrics(
            test_id="1", scenario=TestScenario.DATABASE_FAILOVER,
            start_time=fixed_datetime - timedelta(days=5),
            end_time=fixed_datetime - timedelta(days=5),
            rto_actual_seconds=Decimal("8"), rpo_actual_seconds=Decimal("3"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=True, rpo_met=True, status=TestStatus.SUCCESS,
        )
        m2 = DRMetrics(
            test_id="2", scenario=TestScenario.BACKUP_RESTORE,
            start_time=fixed_datetime - timedelta(days=10),
            end_time=fixed_datetime - timedelta(days=10),
            rto_actual_seconds=Decimal("9"), rpo_actual_seconds=Decimal("4"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=True, rpo_met=True, status=TestStatus.SUCCESS,
        )
        rto_rpo_tester._metrics_history.extend([m1, m2])
        with patch("disaster_recovery.dr_rto_rpo_verification_test.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_datetime
            report = rto_rpo_tester.get_compliance_report(period_days=30)
            assert report["status"] == "compliant"
            assert report["overall_compliance_rate"] == 100.0

    def test_get_compliance_report_old_tests_excluded(self, rto_rpo_tester, fixed_datetime):
        m_old = DRMetrics(
            test_id="old", scenario=TestScenario.DATABASE_FAILOVER,
            start_time=fixed_datetime - timedelta(days=40),
            end_time=fixed_datetime - timedelta(days=40),
            rto_actual_seconds=Decimal("8"), rpo_actual_seconds=Decimal("3"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=True, rpo_met=True, status=TestStatus.SUCCESS,
        )
        rto_rpo_tester._metrics_history.append(m_old)
        with patch("disaster_recovery.dr_rto_rpo_verification_test.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_datetime
            report = rto_rpo_tester.get_compliance_report(period_days=30)
            assert report["total_tests"] == 0
            assert report["status"] == "not_tested"

    def test_get_by_scenario_summary(self, rto_rpo_tester, sample_dr_metrics):
        m1 = sample_dr_metrics
        m2 = sample_dr_metrics.clone()
        m2.test_id = "2"
        m2.scenario = TestScenario.BACKUP_RESTORE
        m2.rto_actual_seconds = Decimal("12")
        m2.rpo_actual_seconds = Decimal("6")
        m2.rto_met = False
        m2.rpo_met = False
        rto_rpo_tester._metrics_history.extend([m1, m2])
        summary = rto_rpo_tester.get_by_scenario_summary()
        assert "database_failover" in summary
        assert "backup_restore" in summary
        db_sum = summary["database_failover"]
        assert db_sum["total_tests"] == 1
        assert db_sum["compliant_tests"] == 1
        assert db_sum["compliance_rate"] == 100.0
        assert db_sum["avg_rto"] == 8.5
        br_sum = summary["backup_restore"]
        assert br_sum["compliant_tests"] == 0
        assert br_sum["compliance_rate"] == 0.0

    def test_add_scheduled_test(self, rto_rpo_tester, mock_requests, mock_thread):
        failover_func = MagicMock(return_value="ok")
        schedule_id = rto_rpo_tester.add_scheduled_test(
            scenario=TestScenario.DATABASE_FAILOVER,
            interval_seconds=60,
            failover_function=failover_func,
            pre_hook=None,
            post_hook=None,
            notification_webhook="https://webhook.com"
        )
        assert schedule_id in rto_rpo_tester._schedules
        schedule = rto_rpo_tester._schedules[schedule_id]
        assert schedule.scenario == TestScenario.DATABASE_FAILOVER
        assert schedule.interval_seconds == 60
        assert schedule.enabled is True
        trail = rto_rpo_tester.audit_trail()
        assert any(entry["action"] == "ADD_SCHEDULED_TEST" for entry in trail)

    def test_start_scheduled_thread(self, rto_rpo_tester, mock_requests, mock_thread, mock_datetime, mock_time):
        schedule_id = "test-sched"
        schedule = TestSchedule(
            schedule_id=schedule_id,
            scenario=TestScenario.DATABASE_FAILOVER,
            interval_seconds=60,
            next_run=datetime.now(UTC),
            enabled=True,
        )
        rto_rpo_tester._schedules[schedule_id] = schedule
        failover_func = MagicMock(return_value="ok")
        with patch.object(rto_rpo_tester, "simulate_failure") as mock_simulate:
            rto_rpo_tester._start_scheduled_thread(schedule_id, failover_func, None, None)
            mock_simulate.assert_called_once()
            assert schedule.last_run is not None

    def test_send_notification(self, rto_rpo_tester, mock_requests, sample_dr_metrics):
        schedule = TestSchedule(
            schedule_id="s1",
            scenario=TestScenario.DATABASE_FAILOVER,
            interval_seconds=60,
            next_run=datetime.now(UTC),
            notification_webhook="https://webhook.com",
        )
        rto_rpo_tester._send_notification(schedule, sample_dr_metrics)
        mock_requests.post.assert_called_once_with(
            "https://webhook.com",
            json={
                "schedule_id": "s1",
                "scenario": "database_failover",
                "rto_met": True,
                "rpo_met": True,
                "rto_actual": 8.5,
                "rpo_actual": 3.2,
                "status": "success",
            },
            timeout=5,
        )

    def test_send_notification_no_webhook(self, rto_rpo_tester, mock_requests, sample_dr_metrics):
        schedule = TestSchedule(
            schedule_id="s1",
            scenario=TestScenario.DATABASE_FAILOVER,
            interval_seconds=60,
            next_run=datetime.now(UTC),
            notification_webhook=None,
        )
        rto_rpo_tester._send_notification(schedule, sample_dr_metrics)
        mock_requests.post.assert_not_called()

    def test_stop_scheduled_test(self, rto_rpo_tester):
        schedule_id = "s1"
        schedule = TestSchedule(
            schedule_id=schedule_id,
            scenario=TestScenario.DATABASE_FAILOVER,
            interval_seconds=60,
            next_run=datetime.now(UTC),
            enabled=True,
        )
        rto_rpo_tester._schedules[schedule_id] = schedule
        assert rto_rpo_tester.stop_scheduled_test(schedule_id) is True
        assert schedule.enabled is False
        trail = rto_rpo_tester.audit_trail()
        assert any(entry["action"] == "STOP_SCHEDULED_TEST" for entry in trail)
        assert rto_rpo_tester.stop_scheduled_test("nonexistent") is False

    def test_export_to_json(self, rto_rpo_tester, sample_dr_metrics, tmp_path):
        rto_rpo_tester._metrics_history.append(sample_dr_metrics)
        file_path = tmp_path / "dr_test_results.json"
        rto_rpo_tester.export_to_json(str(file_path))
        assert file_path.exists()
        with open(file_path) as f:
            data = json.load(f)
        assert data["total_tests"] == 1
        assert data["rto_target"] == 10.0
        assert data["rpo_target"] == 5.0
        assert "history" in data
        assert len(data["history"]) == 1

    def test_reset_history(self, rto_rpo_tester, sample_dr_metrics):
        rto_rpo_tester._metrics_history.append(sample_dr_metrics)
        rto_rpo_tester._last_successful_tx_time = datetime.now(UTC)
        old_version = rto_rpo_tester._version
        rto_rpo_tester.reset_history()
        assert rto_rpo_tester._metrics_history == []
        assert rto_rpo_tester._last_successful_tx_time is None
        assert rto_rpo_tester._version == old_version + 1
        trail = rto_rpo_tester.audit_trail()
        assert any(entry["action"] == "RESET_HISTORY" for entry in trail)

    def test_reset(self, rto_rpo_tester):
        rto_rpo_tester._metrics_history.append(MagicMock())
        rto_rpo_tester._schedules["s1"] = MagicMock()
        rto_rpo_tester.reset()
        assert rto_rpo_tester._metrics_history == []
        assert rto_rpo_tester._schedules == {}
        assert rto_rpo_tester._version == 1
        assert rto_rpo_tester._audit_trail == []
        assert rto_rpo_tester._snapshots == []
        trail = rto_rpo_tester.audit_trail()
        assert any(entry["action"] == "RESET" for entry in trail)

    def test_to_dict(self, rto_rpo_tester):
        d = rto_rpo_tester.to_dict()
        assert d["rto_target_seconds"] == 10.0
        assert d["rpo_target_seconds"] == 5.0
        assert d["max_test_duration_seconds"] == 30.0
        assert d["enable_prometheus"] is False
        assert d["total_tests"] == 0
        assert d["schedules_count"] == 0
        assert d["version"] == 1

    def test_from_dict(self, rto_rpo_tester):
        d = rto_rpo_tester.to_dict()
        restored = RTO_RPO_VerificationTest.from_dict(d)
        assert restored.rto_target == Decimal("10")
        assert restored.rpo_target == Decimal("5")
        assert restored.max_duration == Decimal("30")
        assert restored.enable_prometheus is False
        assert restored._version == 1

    def test_clone(self, rto_rpo_tester):
        cloned = rto_rpo_tester.clone()
        assert cloned.rto_target == rto_rpo_tester.rto_target
        assert cloned.rpo_target == rto_rpo_tester.rpo_target
        assert cloned.max_duration == rto_rpo_tester.max_duration
        assert cloned.enable_prometheus == rto_rpo_tester.enable_prometheus
        assert cloned._version == rto_rpo_tester._version + 1

    def test_snapshot(self, rto_rpo_tester):
        snap = rto_rpo_tester.snapshot()
        assert snap["version"] == rto_rpo_tester._version
        assert snap["rto_target"] == 10.0
        assert snap["rpo_target"] == 5.0
        assert snap["total_tests"] == 0
        assert "timestamp" in snap

    def test_version(self, rto_rpo_tester):
        assert rto_rpo_tester.version() == rto_rpo_tester._version

    def test_audit_trail(self, rto_rpo_tester):
        rto_rpo_tester.touch("tester")
        trail = rto_rpo_tester.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, rto_rpo_tester):
        old_version = rto_rpo_tester._version
        touched = rto_rpo_tester.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1

    def test_simulate_failure_pre_hook_exception(self, rto_rpo_tester, mock_datetime, mock_time):
        pre_hook = MagicMock(side_effect=Exception("pre hook error"))
        failover = MagicMock(return_value="ok")
        with patch("time.time") as mock_time_time:
            mock_time_time.side_effect = [1000.0, 1002.0]
            metrics = rto_rpo_tester.simulate_failure(failover, pre_failure_hook=pre_hook)
            assert metrics.status == TestStatus.SUCCESS

    def test_simulate_failure_post_hook_exception(self, rto_rpo_tester, mock_datetime, mock_time):
        post_hook = MagicMock(side_effect=Exception("post hook error"))
        failover = MagicMock(return_value="ok")
        with patch("time.time") as mock_time_time:
            mock_time_time.side_effect = [1000.0, 1002.0]
            metrics = rto_rpo_tester.simulate_failure(failover, post_recovery_hook=post_hook)
            assert metrics.status == TestStatus.SUCCESS

    def test_simulate_failure_updates_last_tx_time(self, rto_rpo_tester, mock_datetime, mock_time):
        failover = MagicMock(return_value="ok")
        with patch("time.time") as mock_time_time:
            mock_time_time.side_effect = [1000.0, 1002.0]
            metrics = rto_rpo_tester.simulate_failure(failover)
            assert rto_rpo_tester._last_successful_tx_time == metrics.end_time

    def test_simulate_failure_rpo_from_last_tx(self, rto_rpo_tester, mock_datetime, mock_time):
        rto_rpo_tester._last_successful_tx_time = datetime.now(UTC) - timedelta(seconds=2)
        failover = MagicMock(return_value="ok")
        with patch("time.time") as mock_time_time:
            mock_time_time.side_effect = [1000.0, 1001.0]
            metrics = rto_rpo_tester.simulate_failure(failover)
            assert metrics.rpo_actual_seconds > Decimal(0)

    def test_get_compliance_report_with_failures(self, rto_rpo_tester, fixed_datetime):
        m1 = DRMetrics(
            test_id="1", scenario=TestScenario.DATABASE_FAILOVER,
            start_time=fixed_datetime - timedelta(days=1),
            end_time=fixed_datetime - timedelta(days=1),
            rto_actual_seconds=Decimal("12"), rpo_actual_seconds=Decimal("6"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=False, rpo_met=False, status=TestStatus.FAILED,
        )
        m2 = DRMetrics(
            test_id="2", scenario=TestScenario.DATABASE_FAILOVER,
            start_time=fixed_datetime - timedelta(days=2),
            end_time=fixed_datetime - timedelta(days=2),
            rto_actual_seconds=Decimal("8"), rpo_actual_seconds=Decimal("4"),
            rto_target_seconds=Decimal("10"), rpo_target_seconds=Decimal("5"),
            rto_met=True, rpo_met=True, status=TestStatus.SUCCESS,
        )
        rto_rpo_tester._metrics_history.extend([m1, m2])
        with patch("disaster_recovery.dr_rto_rpo_verification_test.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_datetime
            report = rto_rpo_tester.get_compliance_report(period_days=30)
            assert report["total_tests"] == 2
            assert report["successful_tests"] == 1
            assert report["rto_compliant_count"] == 1
            assert report["rpo_compliant_count"] == 1
            assert report["fully_compliant_count"] == 1
            assert report["status"] == "partially_compliant"
