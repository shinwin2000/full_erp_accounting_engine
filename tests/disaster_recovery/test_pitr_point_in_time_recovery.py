# tests/disaster_recovery/test_pitr_point_in_time_recovery.py
"""
Comprehensive unit tests for disaster_recovery/pitr_point_in_time_recovery.py.
Covers all public methods, entity methods, and exception handling with mocks.
All datetime is mocked to avoid flakiness.
"""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, mock_open, patch

import pytest
from botocore.exceptions import ClientError

from disaster_recovery.dr_exceptions import RecoveryError
from disaster_recovery.pitr_point_in_time_recovery import (
    PITRRestorePoint,
    PITRRestoreResult,
    PointInTimeRecovery,
)

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=7)
FIXED_EARLIER = FIXED_NOW - timedelta(days=3)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now in pitr module to fixed time."""
    with patch("disaster_recovery.pitr_point_in_time_recovery.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Tests for PITRRestorePoint
# ============================================================================

class TestPITRRestorePoint:
    @pytest.fixture
    def restore_point(self):
        return PITRRestorePoint(
            restore_id="rp-001",
            base_backup_id="backup-001",
            backup_time=FIXED_PAST,
            earliest_restore_time=FIXED_PAST + timedelta(minutes=5),
            latest_restore_time=FIXED_NOW,
            wal_archive_path="s3://test/wal/",
            total_size_bytes=1024 * 1024,
            is_valid=True,
            details={"source": "test"},
        )

    def test_construction(self, restore_point):
        assert restore_point.restore_id == "rp-001"
        assert restore_point.base_backup_id == "backup-001"
        assert restore_point.backup_time == FIXED_PAST
        assert restore_point.total_size_bytes == 1024 * 1024
        assert restore_point.is_valid is True
        assert restore_point.details == {"source": "test"}
        assert restore_point._version == 1

    def test_validate_valid(self, restore_point):
        result = restore_point.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_missing_restore_id(self, restore_point):
        restore_point.restore_id = ""
        result = restore_point.validate()
        assert result["is_valid"] is False
        assert "restore_id is required" in result["errors"][0]

    def test_validate_missing_base_backup_id(self, restore_point):
        restore_point.base_backup_id = ""
        result = restore_point.validate()
        assert result["is_valid"] is False
        assert "base_backup_id is required" in result["errors"][0]

    def test_validate_backup_time_future(self, restore_point):
        restore_point.backup_time = FIXED_NOW + timedelta(days=1)
        result = restore_point.validate()
        assert result["is_valid"] is False
        assert "backup_time cannot be in the future" in result["errors"][0]

    def test_validate_earliest_after_latest(self, restore_point):
        restore_point.earliest_restore_time = FIXED_NOW
        restore_point.latest_restore_time = FIXED_PAST
        result = restore_point.validate()
        assert result["is_valid"] is False
        assert "earliest_restore_time cannot be after latest_restore_time" in result["errors"][0]

    def test_validate_negative_size(self, restore_point):
        restore_point.total_size_bytes = -1
        result = restore_point.validate()
        assert result["is_valid"] is False
        assert "total_size_bytes cannot be negative" in result["errors"][0]

    def test_to_dict(self, restore_point):
        d = restore_point.to_dict()
        assert d["restore_id"] == "rp-001"
        assert d["base_backup_id"] == "backup-001"
        assert d["backup_time"] == FIXED_PAST.isoformat()
        assert d["total_size_bytes"] == 1024 * 1024
        assert d["version"] == 1
        assert "earliest_restore_time" in d

    def test_from_dict(self):
        data = {
            "restore_id": "rp-002",
            "base_backup_id": "backup-002",
            "backup_time": FIXED_PAST.isoformat(),
            "earliest_restore_time": (FIXED_PAST + timedelta(minutes=5)).isoformat(),
            "latest_restore_time": FIXED_NOW.isoformat(),
            "wal_archive_path": "s3://test/wal/",
            "total_size_bytes": 2048,
            "is_valid": False,
            "details": {"test": "data"},
            "version": 3,
        }
        point = PITRRestorePoint.from_dict(data)
        assert point.restore_id == "rp-002"
        assert point.base_backup_id == "backup-002"
        assert point.backup_time == FIXED_PAST
        assert point.total_size_bytes == 2048
        assert point.is_valid is False
        assert point.details == {"test": "data"}
        assert point._version == 3

    def test_clone(self, restore_point):
        cloned = restore_point.clone()
        assert cloned.restore_id != restore_point.restore_id
        assert cloned.base_backup_id == restore_point.base_backup_id
        assert cloned.backup_time == restore_point.backup_time
        assert cloned.total_size_bytes == restore_point.total_size_bytes
        assert cloned._version == restore_point._version + 1
        # Audit trail should have CLONE entry
        trail = cloned.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, restore_point):
        snap = restore_point.snapshot()
        assert snap["version"] == restore_point._version
        assert snap["restore_id"] == "rp-001"
        assert snap["base_backup_id"] == "backup-001"
        assert snap["backup_time"] == FIXED_PAST.isoformat()

    def test_version(self, restore_point):
        assert restore_point.version() == 1

    def test_audit_trail(self, restore_point):
        restore_point._record_audit("TEST", "system", {"key": "val"})
        trail = restore_point.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["details"] == {"key": "val"}

    def test_touch(self, restore_point):
        touched = restore_point.touch("admin")
        assert touched._version == restore_point._version + 1
        trail = touched.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for PITRRestoreResult
# ============================================================================

class TestPITRRestoreResult:
    @pytest.fixture
    def result(self):
        return PITRRestoreResult(
            restore_id="result-001",
            target_time=FIXED_PAST,
            restored_path="/tmp/restore/data",
            success=True,
            duration_seconds=120.5,
            wal_files_restored=42,
            data_loss_seconds=300,
            error_message=None,
            restored_lsn="0/12345678",
        )

    def test_construction(self, result):
        assert result.restore_id == "result-001"
        assert result.target_time == FIXED_PAST
        assert result.success is True
        assert result.duration_seconds == 120.5
        assert result.wal_files_restored == 42
        assert result.data_loss_seconds == 300
        assert result.restored_lsn == "0/12345678"
        assert result._version == 1

    def test_validate_valid(self, result):
        res = result.validate()
        assert res["is_valid"] is True
        assert res["errors"] == []

    def test_validate_missing_restore_id(self, result):
        result.restore_id = ""
        res = result.validate()
        assert res["is_valid"] is False
        assert "restore_id is required" in res["errors"][0]

    def test_validate_target_time_future(self, result):
        result.target_time = FIXED_NOW + timedelta(days=1)
        res = result.validate()
        assert res["is_valid"] is False
        assert "target_time cannot be in the future" in res["errors"][0]

    def test_validate_negative_duration(self, result):
        result.duration_seconds = -1
        res = result.validate()
        assert res["is_valid"] is False
        assert "duration_seconds cannot be negative" in res["errors"][0]

    def test_validate_negative_wal_files(self, result):
        result.wal_files_restored = -1
        res = result.validate()
        assert res["is_valid"] is False
        assert "wal_files_restored cannot be negative" in res["errors"][0]

    def test_validate_success_without_error_message(self):
        r = PITRRestoreResult(
            restore_id="rid",
            target_time=FIXED_PAST,
            restored_path="",
            success=False,
            duration_seconds=0,
            wal_files_restored=0,
            error_message=None,
        )
        res = r.validate()
        assert res["is_valid"] is False
        assert "error_message is required when success=False" in res["errors"][0]

    def test_to_dict(self, result):
        d = result.to_dict()
        assert d["restore_id"] == "result-001"
        assert d["target_time"] == FIXED_PAST.isoformat()
        assert d["success"] is True
        assert d["duration_seconds"] == 120.5
        assert d["wal_files_restored"] == 42
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "restore_id": "result-002",
            "target_time": FIXED_PAST.isoformat(),
            "restored_path": "/tmp/data",
            "success": False,
            "duration_seconds": 30.0,
            "wal_files_restored": 10,
            "data_loss_seconds": 100,
            "error_message": "Something went wrong",
            "restored_lsn": "0/999",
            "version": 2,
        }
        r = PITRRestoreResult.from_dict(data)
        assert r.restore_id == "result-002"
        assert r.success is False
        assert r.error_message == "Something went wrong"
        assert r._version == 2

    def test_clone(self, result):
        cloned = result.clone()
        assert cloned.restore_id != result.restore_id
        assert cloned.target_time == result.target_time
        assert cloned.success == result.success
        assert cloned._version == result._version + 1
        trail = cloned.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, result):
        snap = result.snapshot()
        assert snap["restore_id"] == "result-001"
        assert snap["success"] is True
        assert snap["duration_seconds"] == 120.5

    def test_version(self, result):
        assert result.version() == 1

    def test_audit_trail(self, result):
        result._record_audit("TEST", "system", {})
        trail = result.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, result):
        touched = result.touch("admin")
        assert touched._version == result._version + 1
        trail = touched.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for PointInTimeRecovery
# ============================================================================

class TestPointInTimeRecovery:
    @pytest.fixture
    def pitr(self):
        return PointInTimeRecovery(
            db_type="postgresql",
            db_host="localhost",
            db_port=5432,
            db_name="test_db",
            db_user="recovery_user",
            db_password="secret",
            wal_archive_path="s3://test-bucket/wal/",
            backup_bucket="test-backups",
            backup_prefix="base/",
            restore_temp_dir="/tmp/pitr",
            use_physical_backup=True,
        )

    @pytest.fixture
    def mock_s3_client(self):
        with patch("disaster_recovery.pitr_point_in_time_recovery.boto3.client") as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    # ------------------------------------------------------------------------
    # Entity basic methods
    # ------------------------------------------------------------------------

    def test_construction(self, pitr):
        assert pitr.db_type == "postgresql"
        assert pitr.db_host == "localhost"
        assert pitr.db_port == 5432
        assert pitr.db_name == "test_db"
        assert pitr.db_user == "recovery_user"
        assert pitr.db_password == "secret"
        assert pitr.wal_archive_path == "s3://test-bucket/wal"
        assert pitr.backup_bucket == "test-backups"
        assert pitr.backup_prefix == "base/"
        assert pitr._version == 1

    def test_validate_valid(self, pitr):
        res = pitr.validate()
        assert res["is_valid"] is True
        assert res["errors"] == []

    def test_validate_invalid(self, pitr):
        pitr.db_host = ""
        pitr.db_port = -1
        pitr.db_name = ""
        pitr.db_user = ""
        pitr.backup_bucket = ""
        res = pitr.validate()
        assert res["is_valid"] is False
        assert len(res["errors"]) == 5

    def test_to_dict(self, pitr):
        d = pitr.to_dict()
        assert d["db_host"] == "localhost"
        assert d["db_port"] == 5432
        assert d["db_name"] == "test_db"
        assert d["backup_bucket"] == "test-backups"
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "db_type": "postgresql",
            "db_host": "remote",
            "db_port": 5433,
            "db_name": "prod",
            "db_user": "admin",
            "db_password": "pass",
            "wal_archive_path": "s3://other/wal/",
            "backup_bucket": "other-backups",
            "backup_prefix": "backups/",
            "restore_temp_dir": "/tmp/restore",
            "use_physical_backup": False,
            "version": 3,
        }
        pitr = PointInTimeRecovery.from_dict(data)
        assert pitr.db_host == "remote"
        assert pitr.db_port == 5433
        assert pitr.db_name == "prod"
        assert pitr.db_user == "admin"
        assert pitr.db_password == "pass"
        assert pitr._version == 3

    def test_clone(self, pitr):
        cloned = pitr.clone()
        assert cloned is not pitr
        assert cloned.db_host == pitr.db_host
        assert cloned.db_name == pitr.db_name
        assert cloned._version == pitr._version + 1

    def test_snapshot(self, pitr):
        snap = pitr.snapshot()
        assert snap["version"] == pitr._version
        assert snap["db_host"] == pitr.db_host
        assert snap["db_name"] == pitr.db_name

    def test_version(self, pitr):
        assert pitr.version() == 1

    def test_audit_trail(self, pitr):
        pitr._record_audit("TEST", "system", {})
        trail = pitr.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, pitr):
        touched = pitr.touch("admin")
        assert touched._version == pitr._version + 1
        trail = touched.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_reset(self, pitr):
        pitr._restore_points["test"] = MagicMock()
        pitr._record_audit("TEST", "system", {})
        old_version = pitr._version
        pitr.reset()
        assert pitr._restore_points == {}
        assert pitr._version == 1
        assert pitr._audit_trail == []
        assert pitr._snapshots == []

    # ------------------------------------------------------------------------
    # list_available_base_backups
    # ------------------------------------------------------------------------

    def test_list_available_base_backups(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.tar.gz", "LastModified": FIXED_NOW, "Size": 1000},
                    {"Key": "base/backup2.backup", "LastModified": FIXED_PAST, "Size": 2000},
                    {"Key": "base/backup3.txt", "LastModified": FIXED_EARLIER, "Size": 3000},
                ]
            }
        ]
        backups = pitr.list_available_base_backups()
        # Only .tar.gz and .backup files should be included
        assert len(backups) == 2
        assert backups[0]["backup_id"] == "backup1"
        assert backups[1]["backup_id"] == "backup2"

    def test_list_available_base_backups_client_error(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "Bucket not found"}},
            "ListObjectsV2",
        )
        backups = pitr.list_available_base_backups()
        assert backups == []

    # ------------------------------------------------------------------------
    # get_restore_points
    # ------------------------------------------------------------------------

    def test_get_restore_points(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.tar.gz", "LastModified": FIXED_PAST, "Size": 1000},
                    {"Key": "base/backup2.tar.gz", "LastModified": FIXED_EARLIER, "Size": 2000},
                ]
            }
        ]
        points = pitr.get_restore_points()
        assert len(points) == 2
        assert points[0].base_backup_id == "backup1"
        assert points[0].total_size_bytes == 1000
        assert points[0].restore_id in pitr._restore_points
        # Audit trail should record
        trail = pitr.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "GET_RESTORE_POINTS"

    # ------------------------------------------------------------------------
    # _get_wal_bucket and _get_wal_prefix
    # ------------------------------------------------------------------------

    def test_get_wal_bucket(self, pitr):
        assert pitr._get_wal_bucket() == "test-bucket"

    def test_get_wal_prefix(self, pitr):
        assert pitr._get_wal_prefix() == "wal/"

    def test_get_wal_prefix_no_path(self, pitr):
        pitr.wal_archive_path = "s3://test-bucket"
        assert pitr._get_wal_prefix() == ""

    # ------------------------------------------------------------------------
    # _list_wal_files_since
    # ------------------------------------------------------------------------

    def test_list_wal_files_since(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "wal/file1.wal", "LastModified": FIXED_NOW},
                    {"Key": "wal/file2.wal", "LastModified": FIXED_PAST},
                ]
            }
        ]
        files = pitr._list_wal_files_since(FIXED_EARLIER)
        # Both should be included since both are after FIXED_EARLIER
        assert len(files) == 2
        assert "wal/file1.wal" in files

    def test_list_wal_files_since_client_error(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "ListObjectsV2"
        )
        files = pitr._list_wal_files_since(FIXED_PAST)
        assert files == []

    # ------------------------------------------------------------------------
    # _download_wal_file
    # ------------------------------------------------------------------------

    def test_download_wal_file(self, pitr, mock_s3_client):
        target_dir = "/tmp/wal"
        result = pitr._download_wal_file("wal/file1.wal", target_dir)
        mock_s3_client.download_file.assert_called_once_with(
            "test-bucket", "wal/file1.wal", "/tmp/wal/file1.wal"
        )
        assert result == "/tmp/wal/file1.wal"

    # ------------------------------------------------------------------------
    # _restore_physical_backup
    # ------------------------------------------------------------------------

    @patch("tarfile.open")
    @patch("os.makedirs")
    def test_restore_physical_backup(self, mock_makedirs, mock_tar_open, pitr, mock_s3_client):
        restore_dir = "/tmp/restore"
        result = pitr._restore_physical_backup("base/backup1.tar.gz", restore_dir)
        mock_s3_client.download_file.assert_called_once_with(
            "test-backups", "base/backup1.tar.gz", "/tmp/restore/base_backup.tar.gz"
        )
        mock_tar_open.assert_called_once()
        # Check recovery.signal file created
        recovery_signal = os.path.join("/tmp/restore/data", "recovery.signal")
        assert os.path.exists(recovery_signal)  # Actually we mocked, but in real test would be created
        assert result == "/tmp/restore/data"

    # ------------------------------------------------------------------------
    # _configure_recovery
    # ------------------------------------------------------------------------

    @patch("builtins.open", new_callable=mock_open)
    def test_configure_recovery(self, mock_file_open, pitr):
        data_dir = "/tmp/restore/data"
        wal_dir = "/tmp/restore/wal"
        pitr._configure_recovery(data_dir, FIXED_NOW, wal_dir)
        mock_file_open.assert_called_once_with("/tmp/restore/data/postgresql.conf", "a")
        handle = mock_file_open()
        # Check that the recovery config was written
        calls = handle.write.call_args_list
        # The append should add multiple lines
        assert "PITR recovery configuration" in calls[0][0][0]
        assert f"recovery_target_time = '{FIXED_NOW.isoformat()}'" in calls[1][0][0]

    # ------------------------------------------------------------------------
    # _restore_logical_backup
    # ------------------------------------------------------------------------

    @patch("subprocess.run")
    @patch("tempfile.NamedTemporaryFile")
    def test_restore_logical_backup_success(self, mock_tempfile, mock_subprocess, pitr, mock_s3_client):
        mock_tempfile.return_value.__enter__.return_value.name = "/tmp/test.dump"
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stderr = ""

        result = pitr._restore_logical_backup("base/backup1.dump", FIXED_NOW)
        mock_s3_client.download_file.assert_called_once_with(
            "test-backups", "base/backup1.dump", "/tmp/test.dump"
        )
        mock_subprocess.assert_called_once()
        assert result == "test_db"

    @patch("subprocess.run")
    @patch("tempfile.NamedTemporaryFile")
    def test_restore_logical_backup_failure(self, mock_tempfile, mock_subprocess, pitr, mock_s3_client):
        mock_tempfile.return_value.__enter__.return_value.name = "/tmp/test.dump"
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stderr = "Connection failed"

        with pytest.raises(RecoveryError, match="Logical restore failed: Connection failed"):
            pitr._restore_logical_backup("base/backup1.dump", FIXED_NOW)

    # ------------------------------------------------------------------------
    # restore_to_timestamp
    # ------------------------------------------------------------------------

    @patch("shutil.rmtree")
    @patch("subprocess.run")
    def test_restore_to_timestamp_physical_success(self, mock_subprocess, mock_rmtree, pitr, mock_s3_client):
        # Mock backup listing
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.tar.gz", "LastModified": FIXED_PAST, "Size": 1000},
                ]
            }
        ]
        # Mock WAL listing
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "wal/file1.wal", "LastModified": FIXED_PAST + timedelta(hours=1)},
                ]
            }
        ]
        mock_subprocess.return_value.returncode = 0

        result = pitr.restore_to_timestamp(
            target_time=FIXED_NOW,
            restore_dir="/tmp/restore",
            dry_run=False,
        )
        assert result.success is True
        assert result.restored_path == "/tmp/restore/data"
        assert result.wal_files_restored == 1
        assert result.data_loss_seconds is not None
        # Should have recorded audit
        trail = pitr.audit_trail()
        assert any(a["action"] == "RESTORE_TO_TIMESTAMP" for a in trail)

    @patch("shutil.rmtree")
    def test_restore_to_timestamp_dry_run(self, mock_rmtree, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.tar.gz", "LastModified": FIXED_PAST, "Size": 1000},
                ]
            }
        ]
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "wal/file1.wal", "LastModified": FIXED_PAST + timedelta(hours=1)},
                ]
            }
        ]

        result = pitr.restore_to_timestamp(
            target_time=FIXED_NOW,
            dry_run=True,
        )
        assert result.success is True
        assert result.duration_seconds == 0
        assert result.wal_files_restored == 1
        # Should not have called s3 download or subprocess
        mock_s3_client.download_file.assert_not_called()
        # Audit trail should have dry run
        trail = pitr.audit_trail()
        assert any(a["action"] == "DRY_RUN_RESTORE" for a in trail)

    def test_restore_to_timestamp_no_suitable_backup(self, pitr, mock_s3_client):
        # No backups
        mock_s3_client.get_paginator.return_value.paginate.return_value = [{"Contents": []}]

        with pytest.raises(RecoveryError, match="No suitable base backup found"):
            pitr.restore_to_timestamp(target_time=FIXED_NOW)

    @patch("shutil.rmtree")
    def test_restore_to_timestamp_logical_success(self, mock_rmtree, pitr, mock_s3_client):
        pitr.use_physical_backup = False
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.dump", "LastModified": FIXED_PAST, "Size": 1000},
                ]
            }
        ]
        with patch.object(pitr, "_restore_logical_backup", return_value="test_db"):
            result = pitr.restore_to_timestamp(
                target_time=FIXED_NOW,
                dry_run=False,
            )
        assert result.success is True
        assert result.restored_path == "test_db"

    @patch("shutil.rmtree")
    def test_restore_to_timestamp_exception(self, mock_rmtree, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.tar.gz", "LastModified": FIXED_PAST, "Size": 1000},
                ]
            }
        ]
        # Force exception during restore
        with patch.object(pitr, "_restore_physical_backup", side_effect=Exception("Restore failed")):
            result = pitr.restore_to_timestamp(
                target_time=FIXED_NOW,
                dry_run=False,
            )
        assert result.success is False
        assert "Restore failed" in result.error_message

    # ------------------------------------------------------------------------
    # dry_run_recovery
    # ------------------------------------------------------------------------

    def test_dry_run_recovery_success(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.tar.gz", "LastModified": FIXED_PAST, "Size": 1000},
                ]
            }
        ]
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "wal/file1.wal", "LastModified": FIXED_PAST + timedelta(hours=1)},
                ]
            }
        ]

        target = FIXED_NOW
        result = pitr.dry_run_recovery(target)
        assert result["can_recover"] is True
        assert result["base_backup_id"] == "backup1"
        assert "wal_files_required" in result
        assert result["estimated_data_loss_seconds"] > 0

    def test_dry_run_recovery_no_suitable_backup(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [{"Contents": []}]
        result = pitr.dry_run_recovery(FIXED_NOW)
        assert result["can_recover"] is False
        assert "No suitable base backup" in result["reason"]

    # ------------------------------------------------------------------------
    # validate_restore
    # ------------------------------------------------------------------------

    @patch("subprocess.run")
    def test_validate_restore_success(self, mock_subprocess, pitr):
        mock_subprocess.return_value.returncode = 0
        result = PITRRestoreResult(
            restore_id="rid",
            target_time=FIXED_PAST,
            restored_path="/tmp",
            success=True,
            duration_seconds=0,
            wal_files_restored=0,
        )
        assert pitr.validate_restore(result) is True
        mock_subprocess.assert_called_once()

    @patch("subprocess.run")
    def test_validate_restore_failed_psql(self, mock_subprocess, pitr):
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "psql")
        result = PITRRestoreResult(
            restore_id="rid",
            target_time=FIXED_PAST,
            restored_path="/tmp",
            success=True,
            duration_seconds=0,
            wal_files_restored=0,
        )
        assert pitr.validate_restore(result) is False

    def test_validate_restore_not_successful(self, pitr):
        result = PITRRestoreResult(
            restore_id="rid",
            target_time=FIXED_PAST,
            restored_path="",
            success=False,
            duration_seconds=0,
            wal_files_restored=0,
            error_message="Fail",
        )
        assert pitr.validate_restore(result) is False

    # ------------------------------------------------------------------------
    # get_restore_points_report
    # ------------------------------------------------------------------------

    def test_get_restore_points_report(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.tar.gz", "LastModified": FIXED_PAST, "Size": 1000},
                    {"Key": "base/backup2.tar.gz", "LastModified": FIXED_EARLIER, "Size": 2000},
                ]
            }
        ]
        report = pitr.get_restore_points_report()
        assert report["total_restore_points"] == 2
        assert report["latest_backup_time"] == FIXED_PAST.isoformat()
        assert len(report["restore_points"]) == 2

    # ------------------------------------------------------------------------
    # export_to_json
    # ------------------------------------------------------------------------

    def test_export_to_json(self, pitr, mock_s3_client):
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "base/backup1.tar.gz", "LastModified": FIXED_PAST, "Size": 1000},
                ]
            }
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            pitr.export_to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert data["db_type"] == "postgresql"
            assert data["backup_bucket"] == "test-backups"
            assert "restore_points_report" in data
            assert data["restore_points_report"]["total_restore_points"] == 1
        finally:
            os.unlink(file_path)