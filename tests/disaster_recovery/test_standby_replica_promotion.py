# test_standby_replica_promotion.py
# Comprehensive tests for disaster_recovery/standby_replica_promotion.py
# Covers all classes, methods, edge cases, and exceptions.

import json
import subprocess
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from disaster_recovery.standby_replica_promotion import (
    FailoverReason,
    FailoverResult,
    PromotionStatus,
    ReplicaInfo,
    ReplicaRole,
    StandbyReplicaPromoter,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def primary_host():
    return "db-primary.internal"


@pytest.fixture
def standby_hosts():
    return ["db-standby-1.internal", "db-standby-2.internal"]


@pytest.fixture
def promoter(primary_host, standby_hosts):
    # Create promoter with auto_failover disabled to avoid threads
    with patch("disaster_recovery.standby_replica_promotion.threading.Thread"):
        promoter = StandbyReplicaPromoter(
            primary_host=primary_host,
            primary_port=5432,
            standby_hosts=standby_hosts,
            standby_port=5432,
            db_user="replicator",
            db_password="pass",
            db_name="postgres",
            db_type="postgresql",
            dns_update_enabled=False,
            dns_record_name="db-primary.internal",
            dns_zone_id="ZONE123",
            health_check_interval_seconds=1,
            replication_lag_threshold_seconds=60,
            max_promotion_attempts=2,
            promotion_timeout_seconds=30,
            auto_failover_enabled=False,
        )
        return promoter


@pytest.fixture
def replica_info():
    return ReplicaInfo(
        host="db-standby-1.internal",
        port=5432,
        role=ReplicaRole.STANDBY,
        replication_lag_seconds=2.5,
        last_applied_lsn="0/1A2B3C",
        is_healthy=True,
        last_heartbeat=datetime.now(UTC),
    )


@pytest.fixture
def failover_result():
    return FailoverResult(
        failover_id="fid-123",
        reason=FailoverReason.MANUAL,
        old_primary="db-primary.internal",
        new_primary="db-standby-1.internal",
        promoted_standby="db-standby-1.internal",
        status=PromotionStatus.SUCCESS,
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC),
        duration_seconds=5.2,
        dns_updated=True,
        error_message=None,
        replication_lag_at_failover=1.5,
    )


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_replica_role(self):
        assert ReplicaRole.PRIMARY.value == "primary"
        assert ReplicaRole.STANDBY.value == "standby"
        assert ReplicaRole.PRIMARY.display_name() == "Primary"
        assert ReplicaRole.STANDBY.display_name() == "Standby"

    def test_failover_reason(self):
        assert FailoverReason.MANUAL.value == "manual"
        assert FailoverReason.PRIMARY_DOWN.value == "primary_down"
        assert FailoverReason.MANUAL.display_name() == "Manual"
        assert FailoverReason.PRIMARY_DOWN.display_name() == "Primary Down"

    def test_promotion_status(self):
        assert PromotionStatus.PENDING.value == "pending"
        assert PromotionStatus.SUCCESS.value == "success"
        assert PromotionStatus.PENDING.display_name() == "Menunggu"
        assert PromotionStatus.SUCCESS.display_name() == "Berhasil"


# -------------------- Tests for ReplicaInfo --------------------
class TestReplicaInfo:
    def test_construction(self, replica_info):
        assert replica_info.host == "db-standby-1.internal"
        assert replica_info.port == 5432
        assert replica_info.role == ReplicaRole.STANDBY
        assert replica_info.replication_lag_seconds == 2.5
        assert replica_info.is_healthy is True
        assert replica_info._version == 1
        assert len(replica_info._snapshots) == 1

    def test_validate_valid(self, replica_info):
        result = replica_info.validate()
        assert result["is_valid"] is True

    def test_validate_invalid(self):
        info = ReplicaInfo(
            host="",
            port=0,
            role="invalid",  # Will fail because role is enum but we need to pass enum
            replication_lag_seconds=-1,
            is_healthy=True,
        )
        # Actually ReplicaInfo expects ReplicaRole enum; if we pass string, it will still be accepted as a value?
        # The dataclass doesn't validate enum types in __post_init__, only in validate method.
        # So we construct with a valid role enum.
        info = ReplicaInfo(
            host="",
            port=0,
            role=ReplicaRole.STANDBY,
            replication_lag_seconds=-1,
            is_healthy=True,
        )
        result = info.validate()
        assert result["is_valid"] is False
        errors = result["errors"]
        assert any("host is required" in e for e in errors)
        assert any("port must be positive" in e for e in errors)
        assert any("replication_lag_seconds cannot be negative" in e for e in errors)

    def test_to_dict(self, replica_info):
        d = replica_info.to_dict()
        assert d["host"] == "db-standby-1.internal"
        assert d["port"] == 5432
        assert d["role"] == "standby"
        assert d["replication_lag_seconds"] == 2.5
        assert d["last_applied_lsn"] == "0/1A2B3C"
        assert d["is_healthy"] is True
        assert d["last_heartbeat"] is not None
        assert d["version"] == 1

    def test_from_dict(self, replica_info):
        d = replica_info.to_dict()
        restored = ReplicaInfo.from_dict(d)
        assert restored.host == replica_info.host
        assert restored.port == replica_info.port
        assert restored.role == replica_info.role
        assert restored.replication_lag_seconds == replica_info.replication_lag_seconds
        assert restored.last_applied_lsn == replica_info.last_applied_lsn
        assert restored.is_healthy == replica_info.is_healthy
        # last_heartbeat roundtrip via isoformat
        assert restored.last_heartbeat == replica_info.last_heartbeat
        assert restored._version == replica_info._version

    def test_clone(self, replica_info):
        cloned = replica_info.clone()
        assert cloned.host == replica_info.host
        assert cloned.port == replica_info.port
        assert cloned.role == replica_info.role
        assert cloned._version == replica_info._version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, replica_info):
        snap = replica_info.snapshot()
        assert snap["version"] == replica_info._version
        assert snap["host"] == replica_info.host
        assert snap["role"] == "standby"
        assert snap["is_healthy"] is True
        assert "timestamp" in snap

    def test_version(self, replica_info):
        assert replica_info.version() == replica_info._version

    def test_audit_trail(self, replica_info):
        replica_info.touch("tester")
        trail = replica_info.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"

    def test_touch(self, replica_info):
        old_version = replica_info._version
        touched = replica_info.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1


# -------------------- Tests for FailoverResult --------------------
class TestFailoverResult:
    def test_construction(self, failover_result):
        assert failover_result.failover_id == "fid-123"
        assert failover_result.status == PromotionStatus.SUCCESS
        assert failover_result.duration_seconds == 5.2
        assert failover_result._version == 1
        assert len(failover_result._snapshots) == 1

    def test_validate_valid(self, failover_result):
        result = failover_result.validate()
        assert result["is_valid"] is True

    def test_validate_invalid(self):
        # missing fields
        result = FailoverResult(
            failover_id="",
            reason=FailoverReason.MANUAL,
            old_primary="",
            new_primary="",
            promoted_standby="",
            status=PromotionStatus.FAILED,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            duration_seconds=-1,
            dns_updated=False,
            error_message="error",
            replication_lag_at_failover=-1,
        )
        validation = result.validate()
        assert validation["is_valid"] is False
        errors = validation["errors"]
        # check at least some errors
        assert any("failover_id is required" in e for e in errors)
        assert any("old_primary is required" in e for e in errors)
        assert any("duration_seconds cannot be negative" in e for e in errors)
        assert any("replication_lag_at_failover cannot be negative" in e for e in errors)

    def test_to_dict(self, failover_result):
        d = failover_result.to_dict()
        assert d["failover_id"] == "fid-123"
        assert d["reason"] == "manual"
        assert d["status"] == "success"
        assert d["duration_seconds"] == 5.2
        assert d["dns_updated"] is True
        assert d["error_message"] is None
        assert d["version"] == 1

    def test_from_dict(self, failover_result):
        d = failover_result.to_dict()
        restored = FailoverResult.from_dict(d)
        assert restored.failover_id == failover_result.failover_id
        assert restored.reason == failover_result.reason
        assert restored.old_primary == failover_result.old_primary
        assert restored.new_primary == failover_result.new_primary
        assert restored.status == failover_result.status
        assert restored.duration_seconds == failover_result.duration_seconds
        assert restored.dns_updated == failover_result.dns_updated
        assert restored.error_message == failover_result.error_message
        assert restored.replication_lag_at_failover == failover_result.replication_lag_at_failover
        assert restored._version == failover_result._version

    def test_clone(self, failover_result):
        cloned = failover_result.clone()
        assert cloned.failover_id != failover_result.failover_id
        assert cloned.reason == failover_result.reason
        assert cloned.old_primary == failover_result.old_primary
        assert cloned.new_primary == failover_result.new_primary
        assert cloned._version == failover_result._version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, failover_result):
        snap = failover_result.snapshot()
        assert snap["version"] == failover_result._version
        assert snap["failover_id"] == "fid-123"
        assert snap["status"] == "success"
        assert snap["old_primary"] == "db-primary.internal"
        assert snap["new_primary"] == "db-standby-1.internal"
        assert "timestamp" in snap

    def test_version(self, failover_result):
        assert failover_result.version() == failover_result._version

    def test_audit_trail(self, failover_result):
        failover_result.touch("tester")
        trail = failover_result.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, failover_result):
        old_version = failover_result._version
        touched = failover_result.touch("tester")
        assert touched._version == old_version + 1


# -------------------- Tests for StandbyReplicaPromoter --------------------
class TestStandbyReplicaPromoter:
    def test_construction(self, promoter, primary_host, standby_hosts):
        assert promoter.primary_host == primary_host
        assert promoter.standby_hosts == standby_hosts
        assert promoter.auto_failover_enabled is False
        assert promoter._version == 1
        assert len(promoter._snapshots) == 1
        # replicas initialized
        assert len(promoter._replicas) == len([primary_host, *standby_hosts])
        assert promoter._replicas[primary_host].role == ReplicaRole.PRIMARY
        for host in standby_hosts:
            assert promoter._replicas[host].role == ReplicaRole.STANDBY

    def test_construction_with_auto_failover(self, primary_host, standby_hosts):
        with patch("threading.Thread") as mock_thread:
            promoter = StandbyReplicaPromoter(
                primary_host=primary_host,
                primary_port=5432,
                standby_hosts=standby_hosts,
                auto_failover_enabled=True,
            )
            assert promoter.auto_failover_enabled is True
            mock_thread.assert_called_once()
            # Health monitor thread started
            assert promoter._health_monitor_thread is not None

    def test_init_replicas(self, promoter, primary_host, standby_hosts):
        # Already called in __init__, we can call again
        promoter._init_replicas()
        assert len(promoter._replicas) == 3
        assert promoter._replicas[primary_host].port == promoter.primary_port
        for host in standby_hosts:
            assert promoter._replicas[host].port == promoter.standby_port

    def test_refresh_replica_info(self, promoter):
        # Mock _get_replication_lag to return different values
        with patch.object(promoter, "_get_replication_lag") as mock_lag:
            mock_lag.side_effect = [0.0, 1.5, 2.3]  # primary first, then standbys
            promoter.refresh_replica_info()
            # Check that replicas updated
            for _host, info in promoter._replicas.items():
                assert info.last_heartbeat is not None
                assert info.is_healthy is True
            # Lag for primary should be 0, standbys get 1.5 and 2.3
            primary = promoter._replicas[promoter.primary_host]
            assert primary.replication_lag_seconds == 0.0
            # Check standby lag
            standby_hosts = promoter.standby_hosts
            assert promoter._replicas[standby_hosts[0]].replication_lag_seconds == 1.5
            assert promoter._replicas[standby_hosts[1]].replication_lag_seconds == 2.3

    def test_refresh_replica_info_exception(self, promoter):
        with patch.object(promoter, "_get_replication_lag", side_effect=Exception("DB error")):
            promoter.refresh_replica_info()
            for _host, info in promoter._replicas.items():
                assert info.is_healthy is False
                assert info.replication_lag_seconds == -1.0

    def test_get_replication_lag_postgresql(self, promoter):
        # primary returns 0
        assert promoter._get_replication_lag(promoter.primary_host) == 0.0
        # standby returns random between 0.1 and 5.0
        with patch("random.uniform") as mock_uniform:
            mock_uniform.return_value = 2.7
            lag = promoter._get_replication_lag("standby-host")
            assert lag == 2.7
        # other db_type not postgresql
        promoter.db_type = "mysql"
        assert promoter._get_replication_lag("any") == 0.0

    def test_is_primary_alive_success(self, promoter):
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value = mock_sock
            assert promoter._is_primary_alive() is True
            mock_sock.connect.assert_called_with((promoter.primary_host, promoter.primary_port))
            mock_sock.close.assert_called_once()

    def test_is_primary_alive_failure(self, promoter):
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = Exception("Connection refused")
            mock_socket.return_value = mock_sock
            assert promoter._is_primary_alive() is False

    def test_get_best_standby(self, promoter):
        # Setup some replicas with different lags
        promoter._replicas["standby1"] = ReplicaInfo(
            host="standby1", port=5432, role=ReplicaRole.STANDBY,
            replication_lag_seconds=5.0, is_healthy=True
        )
        promoter._replicas["standby2"] = ReplicaInfo(
            host="standby2", port=5432, role=ReplicaRole.STANDBY,
            replication_lag_seconds=2.0, is_healthy=True
        )
        promoter._replicas["standby3"] = ReplicaInfo(
            host="standby3", port=5432, role=ReplicaRole.STANDBY,
            replication_lag_seconds=10.0, is_healthy=False
        )
        # Refresh should be called inside get_best_standby, but we patch it
        with patch.object(promoter, "refresh_replica_info"):
            best = promoter.get_best_standby()
            # Should be standby2 (lowest lag among healthy)
            assert best == "standby2"

    def test_get_best_standby_no_healthy(self, promoter):
        # No standby healthy
        promoter._replicas["standby1"] = ReplicaInfo(
            host="standby1", port=5432, role=ReplicaRole.STANDBY,
            replication_lag_seconds=5.0, is_healthy=False
        )
        with patch.object(promoter, "refresh_replica_info"):
            best = promoter.get_best_standby()
            assert best is None

    # Promotion commands - we need to mock subprocess
    def test_promote_standby_postgresql_success(self, promoter):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = promoter._promote_standby_postgresql("standby-host")
            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "ssh"
            assert args[1] == "standby-host"
            assert "pg_ctl" in args

    def test_promote_standby_postgresql_failure(self, promoter):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = promoter._promote_standby_postgresql("standby-host")
            assert result is False

    def test_promote_standby_postgresql_timeout(self, promoter):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=30)
            result = promoter._promote_standby_postgresql("standby-host")
            assert result is False

    def test_promote_standby_postgresql_exception(self, promoter):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("generic")
            result = promoter._promote_standby_postgresql("standby-host")
            assert result is False

    def test_promote_standby_mysql(self, promoter):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = promoter._promote_standby_mysql("standby-host")
            assert result is True
            mock_run.assert_called_once()

    def test_promote_standby_mysql_failure(self, promoter):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("mysql error")
            result = promoter._promote_standby_mysql("standby-host")
            assert result is False

    def test_promote_standby_generic(self, promoter):
        # _generic_promote just sleeps and returns True
        with patch("time.sleep") as mock_sleep:
            result = promoter._generic_promote("standby-host")
            assert result is True
            mock_sleep.assert_called_once_with(1)

    def test_promote_standby_postgresql_by_type(self, promoter):
        # db_type = postgresql should call _promote_standby_postgresql
        with patch.object(promoter, "_promote_standby_postgresql", return_value=True) as mock_pg:
            result = promoter.promote_standby("standby-host")
            assert result is True
            mock_pg.assert_called_once_with("standby-host")

    def test_promote_standby_mysql_by_type(self, promoter):
        promoter.db_type = "mysql"
        with patch.object(promoter, "_promote_standby_mysql", return_value=True) as mock_mysql:
            result = promoter.promote_standby("standby-host")
            assert result is True
            mock_mysql.assert_called_once_with("standby-host")

    def test_promote_standby_unsupported_type(self, promoter):
        promoter.db_type = "oracle"
        with patch.object(promoter, "_generic_promote", return_value=True) as mock_generic:
            result = promoter.promote_standby("standby-host")
            assert result is True
            mock_generic.assert_called_once_with("standby-host")

    # DNS Update
    def test_update_dns_route53_disabled(self, promoter):
        promoter.dns_update_enabled = False
        assert promoter._update_dns_route53("new-host") is False

    def test_update_dns_route53_no_boto3(self, promoter):
        promoter.dns_update_enabled = True
        with patch("disaster_recovery.standby_replica_promotion.HAS_BOTO3", False):
            assert promoter._update_dns_route53("new-host") is False

    def test_update_dns_route53_success(self, promoter):
        promoter.dns_update_enabled = True
        promoter.dns_zone_id = "ZONE123"
        with patch("boto3.client") as mock_boto_client:
            mock_route53 = MagicMock()
            mock_route53.change_resource_record_sets.return_value = {
                "ResponseMetadata": {"HTTPStatusCode": 200}
            }
            mock_boto_client.return_value = mock_route53
            result = promoter._update_dns_route53("new-primary")
            assert result is True
            mock_route53.change_resource_record_sets.assert_called_once()

    def test_update_dns_route53_failure(self, promoter):
        promoter.dns_update_enabled = True
        promoter.dns_zone_id = "ZONE123"
        with patch("boto3.client") as mock_boto_client:
            mock_route53 = MagicMock()
            mock_route53.change_resource_record_sets.side_effect = Exception("Route53 error")
            mock_boto_client.return_value = mock_route53
            result = promoter._update_dns_route53("new-primary")
            assert result is False

    # ---- failover ----
    def test_failover_primary_alive_no_force(self, promoter):
        with patch.object(promoter, "_is_primary_alive", return_value=True):
            result = promoter.failover(reason=FailoverReason.MANUAL, force=False)
            assert result.status == PromotionStatus.FAILED
            assert "Primary is still alive" in result.error_message
            assert len(promoter._failover_history) == 1

    def test_failover_primary_alive_with_force(self, promoter):
        # We need to mock get_best_standby and promote_standby to succeed
        with patch.object(promoter, "_is_primary_alive", return_value=True):
            with patch.object(promoter, "get_best_standby", return_value="db-standby-1.internal"):
                with patch.object(promoter, "promote_standby", return_value=True):
                    with patch.object(promoter, "_update_dns_route53", return_value=True):
                        with patch.object(promoter, "_is_host_alive", return_value=True):
                            result = promoter.failover(reason=FailoverReason.MANUAL, force=True)
                            assert result.status == PromotionStatus.SUCCESS
                            assert result.new_primary == "db-standby-1.internal"
                            assert result.promoted_standby == "db-standby-1.internal"
                            assert result.old_primary == promoter.primary_host
                            # Check role updates
                            assert promoter._replicas["db-standby-1.internal"].role == ReplicaRole.PRIMARY
                            assert promoter._replicas[promoter.primary_host].role == ReplicaRole.STANDBY
                            assert len(promoter._failover_history) == 1
                            # DNS updated if enabled (we set dns_update_enabled=True? Actually promoter has False default)
                            # But we mocked _update_dns_route53; we need to check it's called if enabled.
                            # We'll test DNS separately below.

    def test_failover_no_best_standby(self, promoter):
        with patch.object(promoter, "_is_primary_alive", return_value=False):
            with patch.object(promoter, "get_best_standby", return_value=None):
                result = promoter.failover(reason=FailoverReason.PRIMARY_DOWN)
                assert result.status == PromotionStatus.FAILED
                assert "No healthy standby available" in result.error_message
                assert len(promoter._failover_history) == 1

    def test_failover_promotion_fails(self, promoter):
        with patch.object(promoter, "_is_primary_alive", return_value=False):
            with patch.object(promoter, "get_best_standby", return_value="db-standby-1.internal"):
                with patch.object(promoter, "promote_standby", return_value=False):
                    result = promoter.failover(reason=FailoverReason.PRIMARY_DOWN)
                    assert result.status == PromotionStatus.FAILED
                    assert "Failed to promote standby" in result.error_message
                    assert result.promoted_standby == "db-standby-1.internal"
                    assert len(promoter._failover_history) == 1

    def test_failover_specific_standby(self, promoter):
        with patch.object(promoter, "_is_primary_alive", return_value=False):
            with patch.object(promoter, "promote_standby", return_value=True):
                with patch.object(promoter, "_update_dns_route53", return_value=True):
                    with patch.object(promoter, "_is_host_alive", return_value=True):
                        result = promoter.failover(
                            reason=FailoverReason.MANUAL,
                            force=True,
                            specific_standby="db-standby-2.internal"
                        )
                        assert result.status == PromotionStatus.SUCCESS
                        assert result.promoted_standby == "db-standby-2.internal"
                        assert result.new_primary == "db-standby-2.internal"

    def test_failover_dns_update_enabled(self, primary_host, standby_hosts):
        # Create promoter with DNS enabled
        promoter = StandbyReplicaPromoter(
            primary_host=primary_host,
            primary_port=5432,
            standby_hosts=standby_hosts,
            dns_update_enabled=True,
            dns_zone_id="ZONE123",
            dns_record_name="db-primary.internal",
            auto_failover_enabled=False,
        )
        with patch.object(promoter, "_is_primary_alive", return_value=False):
            with patch.object(promoter, "get_best_standby", return_value="db-standby-1.internal"):
                with patch.object(promoter, "promote_standby", return_value=True):
                    with patch.object(promoter, "_update_dns_route53", return_value=True) as mock_dns:
                        with patch.object(promoter, "_is_host_alive", return_value=True):
                            result = promoter.failover(reason=FailoverReason.MANUAL, force=True)
                            assert result.dns_updated is True
                            mock_dns.assert_called_once_with("db-standby-1.internal")

    def test_failover_dns_update_fails(self, promoter):
        # Set dns_update_enabled True for this test
        promoter.dns_update_enabled = True
        with patch.object(promoter, "_is_primary_alive", return_value=False):
            with patch.object(promoter, "get_best_standby", return_value="db-standby-1.internal"):
                with patch.object(promoter, "promote_standby", return_value=True):
                    with patch.object(promoter, "_update_dns_route53", return_value=False) as mock_dns:
                        with patch.object(promoter, "_is_host_alive", return_value=True):
                            result = promoter.failover(reason=FailoverReason.MANUAL, force=True)
                            assert result.status == PromotionStatus.SUCCESS  # Still success even if DNS fails
                            assert result.dns_updated is False
                            mock_dns.assert_called_once_with("db-standby-1.internal")

    # ---- demote old primary ----
    def test_demote_old_primary(self, promoter):
        result = promoter._demote_old_primary("old-host")
        assert result is True  # just logs

    # ---- switchback ----
    def test_switchback_original_healthy(self, promoter):
        # after a failover, current primary is standby1, original primary is old primary
        # We need to set up some state
        promoter._replicas["db-primary.internal"] = ReplicaInfo(
            host="db-primary.internal", port=5432, role=ReplicaRole.STANDBY, is_healthy=True
        )
        promoter._replicas["db-standby-1.internal"] = ReplicaInfo(
            host="db-standby-1.internal", port=5432, role=ReplicaRole.PRIMARY, is_healthy=True
        )
        with patch.object(promoter, "_is_host_alive", return_value=True):
            with patch.object(promoter, "failover") as mock_failover:
                mock_failover.return_value = MagicMock(status=PromotionStatus.SUCCESS)
                result = promoter.switchback()
                mock_failover.assert_called_once_with(
                    reason=FailoverReason.MANUAL, force=True, specific_standby="db-primary.internal"
                )
                assert result.status == PromotionStatus.SUCCESS

    def test_switchback_original_unhealthy(self, promoter):
        with patch.object(promoter, "_is_host_alive", return_value=False):
            result = promoter.switchback(original_primary="db-primary.internal")
            assert result.status == PromotionStatus.FAILED
            assert "Original primary db-primary.internal is not healthy" in result.error_message

    # ---- health monitor ----
    def test_start_health_monitor(self, promoter):
        with patch("threading.Thread") as mock_thread:
            promoter._start_health_monitor()
            mock_thread.assert_called_once()
            # thread target is monitor function
            # We can't easily test the monitor loop without running it, but we can check that _running is set
            assert promoter._running is True

    def test_stop_health_monitor(self, promoter):
        promoter._running = True
        promoter.stop_health_monitor()
        assert promoter._running is False
        trail = promoter.audit_trail()
        assert any(entry["action"] == "STOP_HEALTH_MONITOR" for entry in trail)

    # ---- helpers ----
    def test_is_host_alive_success(self, promoter):
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value = mock_sock
            assert promoter._is_host_alive("some-host") is True

    def test_is_host_alive_failure(self, promoter):
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = Exception("timeout")
            mock_socket.return_value = mock_sock
            assert promoter._is_host_alive("some-host") is False

    def test_get_current_primary(self, promoter):
        # initially primary is self.primary_host
        assert promoter.get_current_primary() == promoter.primary_host
        # after a failover, change role
        promoter._replicas["db-standby-1.internal"].role = ReplicaRole.PRIMARY
        promoter._replicas[promoter.primary_host].role = ReplicaRole.STANDBY
        assert promoter.get_current_primary() == "db-standby-1.internal"

    def test_get_replicas_status(self, promoter):
        with patch.object(promoter, "refresh_replica_info") as mock_refresh:
            status = promoter.get_replicas_status()
            mock_refresh.assert_called_once()
            assert len(status) == len(promoter._replicas)
            for host, _info in promoter._replicas.items():
                assert status[host]["host"] == host

    def test_get_failover_history(self, promoter):
        # add some history
        result1 = MagicMock(to_dict=lambda: {"id": "1"})
        result2 = MagicMock(to_dict=lambda: {"id": "2"})
        promoter._failover_history = [result1, result2]
        history = promoter.get_failover_history()
        assert len(history) == 2
        assert history[0] == {"id": "1"}
        assert history[1] == {"id": "2"}

    # ---- reporting ----
    def test_generate_report(self, promoter):
        promoter._failover_history.append(MagicMock(to_dict=lambda: {"id": "1"}))
        report = promoter.generate_report()
        assert report["primary_host"] == promoter.primary_host
        assert report["standby_hosts"] == promoter.standby_hosts
        assert report["auto_failover_enabled"] is False
        assert "replicas_status" in report
        assert report["failover_history_count"] == 1
        assert report["last_failover"] == {"id": "1"}
        assert report["version"] == 1

    def test_export_to_json(self, promoter, tmp_path):
        file_path = tmp_path / "promotion.json"
        promoter.export_to_json(str(file_path))
        assert file_path.exists()
        with open(file_path) as f:
            data = json.load(f)
        assert "report" in data
        assert "failover_history" in data

    # ---- entity methods for StandbyReplicaPromoter ----
    def test_validate_valid(self, promoter):
        result = promoter.validate()
        assert result["is_valid"] is True

    def test_validate_invalid(self, primary_host):
        with pytest.raises(Exception):  # constructor will raise? Actually constructor doesn't validate
            # We'll create an invalid instance via from_dict or manually then validate
            promoter = StandbyReplicaPromoter(
                primary_host="",
                primary_port=0,
                standby_hosts=[],
            )
            # But constructor will raise? It doesn't validate in __init__, so we can create.
            # Then call validate.
        # Actually we need to create instance without validation; but __init__ doesn't validate,
        # so we can just create with invalid args.
        promoter = StandbyReplicaPromoter(
            primary_host="",
            primary_port=0,
            standby_hosts=[],
        )
        result = promoter.validate()
        assert result["is_valid"] is False
        errors = result["errors"]
        assert any("primary_host is required" in e for e in errors)
        assert any("primary_port must be positive" in e for e in errors)
        assert any("standby_hosts cannot be empty" in e for e in errors)

    def test_to_dict(self, promoter):
        d = promoter.to_dict()
        assert d["primary_host"] == promoter.primary_host
        assert d["primary_port"] == 5432
        assert d["standby_hosts"] == promoter.standby_hosts
        assert d["auto_failover_enabled"] is False
        assert d["version"] == 1

    def test_from_dict(self, promoter):
        d = promoter.to_dict()
        restored = StandbyReplicaPromoter.from_dict(d)
        assert restored.primary_host == promoter.primary_host
        assert restored.primary_port == promoter.primary_port
        assert restored.standby_hosts == promoter.standby_hosts
        assert restored.standby_port == promoter.standby_port
        assert restored.db_user == promoter.db_user
        assert restored.db_type == promoter.db_type
        assert restored.auto_failover_enabled == promoter.auto_failover_enabled
        assert restored._version == promoter._version

    def test_clone(self, promoter):
        cloned = promoter.clone()
        assert cloned.primary_host == promoter.primary_host
        assert cloned.standby_hosts == promoter.standby_hosts
        assert cloned._version == promoter._version + 1
        # check that replicas are not cloned (they are reinitialized)
        assert cloned._replicas != promoter._replicas

    def test_snapshot(self, promoter):
        snap = promoter.snapshot()
        assert snap["version"] == promoter._version
        assert snap["primary_host"] == promoter.primary_host
        assert snap["standby_count"] == len(promoter.standby_hosts)
        assert snap["auto_failover_enabled"] is False
        assert "timestamp" in snap

    def test_version(self, promoter):
        assert promoter.version() == promoter._version

    def test_audit_trail(self, promoter):
        promoter.touch("tester")
        trail = promoter.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"

    def test_touch(self, promoter):
        old_version = promoter._version
        touched = promoter.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1

    def test_reset(self, promoter):
        # Add some history and change replicas
        promoter._failover_history.append(MagicMock())
        promoter._replicas["extra"] = MagicMock()
        promoter.reset()
        assert len(promoter._failover_history) == 0
        assert len(promoter._replicas) == len([promoter.primary_host, *promoter.standby_hosts])
        assert promoter._version == 1  # reset sets version to 1
        assert len(promoter._audit_trail) == 1  # only RESET entry
        assert any(entry["action"] == "RESET" for entry in promoter.audit_trail())
        # health monitor restarted if auto_failover_enabled
        # Since promoter has auto_failover False, not called

    def test_reset_with_auto_failover(self, primary_host, standby_hosts):
        promoter = StandbyReplicaPromoter(
            primary_host=primary_host,
            primary_port=5432,
            standby_hosts=standby_hosts,
            auto_failover_enabled=True,
        )
        # mock _start_health_monitor to avoid thread issues
        with patch.object(promoter, "_start_health_monitor") as mock_start:
            promoter.reset()
            mock_start.assert_called_once()

    # ---- integration-like test for failover flow ----
    def test_failover_full_flow_success(self, promoter):
        # Mock everything
        with patch.object(promoter, "_is_primary_alive", return_value=False):
            with patch.object(promoter, "get_best_standby", return_value="db-standby-1.internal"):
                with patch.object(promoter, "promote_standby", return_value=True):
                    with patch.object(promoter, "_update_dns_route53", return_value=True):
                        with patch.object(promoter, "_is_host_alive", return_value=True):
                            result = promoter.failover(reason=FailoverReason.PRIMARY_DOWN)
                            assert result.status == PromotionStatus.SUCCESS
                            assert result.new_primary == "db-standby-1.internal"
                            assert result.duration_seconds > 0
                            assert result.replication_lag_at_failover >= 0
                            # History added
                            assert len(promoter._failover_history) == 1
                            # Audit trail
                            trail = promoter.audit_trail()
                            assert any("FAILOVER" in entry["action"] for entry in trail)
                            # Roles updated
                            assert promoter._replicas["db-standby-1.internal"].role == ReplicaRole.PRIMARY
                            assert promoter._replicas[promoter.primary_host].role == ReplicaRole.STANDBY

    def test_failover_with_replication_lag_threshold(self, promoter):
        # Not used in current code, but we can test that it's set
        assert promoter.replication_lag_threshold == 60.0

    # ---- test max attempts ----
    def test_failover_retries_promotion(self, promoter):
        promoter.max_attempts = 2
        with patch.object(promoter, "_is_primary_alive", return_value=False):
            with patch.object(promoter, "get_best_standby", return_value="db-standby-1.internal"):
                with patch.object(promoter, "promote_standby", side_effect=[False, True]) as mock_promote:
                    with patch.object(promoter, "_update_dns_route53", return_value=True):
                        with patch.object(promoter, "_is_host_alive", return_value=True):
                            result = promoter.failover(reason=FailoverReason.MANUAL, force=True)
                            assert result.status == PromotionStatus.SUCCESS
                            # promote_standby called twice
                            assert mock_promote.call_count == 2

    def test_failover_retries_exhausted(self, promoter):
        promoter.max_attempts = 2
        with patch.object(promoter, "_is_primary_alive", return_value=False):
            with patch.object(promoter, "get_best_standby", return_value="db-standby-1.internal"):
                with patch.object(promoter, "promote_standby", return_value=False):
                    result = promoter.failover(reason=FailoverReason.MANUAL, force=True)
                    assert result.status == PromotionStatus.FAILED
                    assert "after 2 attempts" in result.error_message
