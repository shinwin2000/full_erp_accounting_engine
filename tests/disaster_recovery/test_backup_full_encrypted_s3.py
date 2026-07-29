# tests/disaster_recovery/test_backup_full_encrypted_s3.py
# Comprehensive tests for backup_full_encrypted_s3.py

import gzip
import hashlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, mock_open, patch

import pytest
from botocore.exceptions import ClientError
from cryptography.fernet import Fernet

from disaster_recovery.backup_full_encrypted_s3 import (
    BACKUP_RETENTION_DAYS_DEFAULT,
    COMPRESSION_LEVEL_DEFAULT,
    BackupError,
    BackupMetadata,
    BackupStatus,
    EncryptionMethod,
    S3EncryptedBackup,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_backup_metadata():
    return BackupMetadata(
        backup_id="backup_20260101_120000",
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        database_size_bytes=1024 * 1024,
        compressed_size_bytes=512 * 1024,
        encrypted_size_bytes=512 * 1024,
        checksum="abc123",
        encryption_method=EncryptionMethod.AWS_KMS,
        encryption_key_id="kms-key-123",
        s3_bucket="my-bucket",
        s3_key="backups/backup_20260101_120000.enc",
        status=BackupStatus.SUCCESS,
        duration_seconds=10.5,
        db_version="PostgreSQL 14.5",
        hostname="server01",
    )


@pytest.fixture
def s3_backup_instance():
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_kms = MagicMock()
        mock_boto.side_effect = lambda service, **kwargs: mock_s3 if service == "s3" else mock_kms
        instance = S3EncryptedBackup(
            s3_bucket="my-bucket",
            s3_prefix="backups/",
            region="ap-southeast-1",
            kms_key_id="kms-key-123",
            db_type="postgresql",
            db_host="localhost",
            db_port=5432,
            db_name="erp_db",
            db_user="backup_user",
            db_password="secret",
            encryption_method=EncryptionMethod.AWS_KMS,
        )
        instance.s3_client = mock_s3
        instance.kms_client = mock_kms
        return instance


# ============================================================================
# Tests for BackupStatus and EncryptionMethod enums
# ============================================================================

class TestEnums:
    def test_backup_status_display_name(self):
        assert BackupStatus.PENDING.display_name() == "Menunggu"
        assert BackupStatus.RUNNING.display_name() == "Berjalan"
        assert BackupStatus.SUCCESS.display_name() == "Berhasil"
        assert BackupStatus.FAILED.display_name() == "Gagal"
        assert BackupStatus.PARTIAL.display_name() == "Sebagian"

    def test_encryption_method_display_name(self):
        assert EncryptionMethod.NONE.display_name() == "Tidak dienkripsi"
        assert EncryptionMethod.AWS_KMS.display_name() == "AWS KMS"
        assert EncryptionMethod.LOCAL_AES.display_name() == "AES-256 Lokal"
        assert EncryptionMethod.FERNET.display_name() == "Fernet"


# ============================================================================
# Tests for BackupMetadata
# ============================================================================

class TestBackupMetadata:
    def test_validate_valid(self, sample_backup_metadata):
        result = sample_backup_metadata.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_backup_id(self, sample_backup_metadata):
        sample_backup_metadata.backup_id = ""
        result = sample_backup_metadata.validate()
        assert result["is_valid"] is False
        assert "backup_id is required" in result["errors"]

    def test_validate_negative_size(self, sample_backup_metadata):
        sample_backup_metadata.database_size_bytes = -1
        result = sample_backup_metadata.validate()
        assert result["is_valid"] is False
        assert "database_size_bytes cannot be negative" in result["errors"]

    def test_validate_invalid_encryption_method(self, sample_backup_metadata):
        sample_backup_metadata.encryption_method = "invalid"  # type: ignore
        result = sample_backup_metadata.validate()
        assert result["is_valid"] is False
        assert "invalid encryption_method" in result["errors"]

    def test_to_dict(self, sample_backup_metadata):
        d = sample_backup_metadata.to_dict()
        assert d["backup_id"] == "backup_20260101_120000"
        assert d["timestamp"] == "2026-01-01T12:00:00+00:00"
        assert d["encryption_method"] == "aws_kms"
        assert d["status"] == "success"
        assert d["version"] == 1

    def test_from_dict(self, sample_backup_metadata):
        d = sample_backup_metadata.to_dict()
        new = BackupMetadata.from_dict(d)
        assert new.backup_id == sample_backup_metadata.backup_id
        assert new.timestamp == sample_backup_metadata.timestamp
        assert new.encryption_method == sample_backup_metadata.encryption_method
        assert new.status == sample_backup_metadata.status

    def test_clone(self, sample_backup_metadata):
        cloned = sample_backup_metadata.clone()
        assert cloned.backup_id != sample_backup_metadata.backup_id
        assert cloned.status == BackupStatus.PENDING
        assert cloned._version == sample_backup_metadata._version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_backup_metadata):
        snap = sample_backup_metadata.snapshot()
        assert snap["backup_id"] == sample_backup_metadata.backup_id
        assert snap["status"] == "success"
        assert "timestamp" in snap

    def test_version(self, sample_backup_metadata):
        assert sample_backup_metadata.version() == 1

    def test_audit_trail(self, sample_backup_metadata):
        sample_backup_metadata._record_audit("TEST", "user", {"key": "value"})
        trail = sample_backup_metadata.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, sample_backup_metadata):
        old_version = sample_backup_metadata._version
        sample_backup_metadata.touch("admin")
        assert sample_backup_metadata._version == old_version + 1
        assert sample_backup_metadata._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for S3EncryptedBackup (core)
# ============================================================================

class TestS3EncryptedBackup:
    def test_init_with_defaults(self):
        with patch("boto3.client") as mock_boto:
            instance = S3EncryptedBackup(
                s3_bucket="my-bucket",
                db_name="erp_db",
                db_user="backup_user",
            )
            assert instance.s3_bucket == "my-bucket"
            assert instance.s3_prefix == "backups/"
            assert instance.region == "ap-southeast-1"
            assert instance.db_type == "postgresql"
            assert instance.encryption_method == EncryptionMethod.AWS_KMS
            assert instance.use_sse is True
            assert instance.retention_days == BACKUP_RETENTION_DAYS_DEFAULT
            assert instance.compression_level == COMPRESSION_LEVEL_DEFAULT

    def test_init_local_aes_creates_master_key(self):
        with patch("boto3.client"), patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = False
            with patch("builtins.open", mock_open()) as mock_file:
                with patch("os.chmod") as mock_chmod:
                    instance = S3EncryptedBackup(
                        s3_bucket="my-bucket",
                        db_name="erp_db",
                        db_user="backup_user",
                        encryption_method=EncryptionMethod.LOCAL_AES,
                    )
                    assert instance._master_key is not None
                    mock_file.assert_called()
                    mock_chmod.assert_called()

    def test_init_local_aes_loads_existing_key(self):
        with patch("boto3.client"), patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True
            with patch("builtins.open", mock_open(read_data=b"mykey1234567890")):
                instance = S3EncryptedBackup(
                    s3_bucket="my-bucket",
                    db_name="erp_db",
                    db_user="backup_user",
                    encryption_method=EncryptionMethod.LOCAL_AES,
                )
                assert instance._master_key == b"mykey1234567890"

    def test_validate_valid(self, s3_backup_instance):
        result = s3_backup_instance.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_bucket(self, s3_backup_instance):
        s3_backup_instance.s3_bucket = ""
        result = s3_backup_instance.validate()
        assert result["is_valid"] is False
        assert "s3_bucket is required" in result["errors"]

    def test_validate_negative_retention(self, s3_backup_instance):
        s3_backup_instance.retention_days = -1
        result = s3_backup_instance.validate()
        assert result["is_valid"] is False
        assert "retention_days must be positive" in result["errors"]

    def test_validate_invalid_compression(self, s3_backup_instance):
        s3_backup_instance.compression_level = 10
        result = s3_backup_instance.validate()
        assert result["is_valid"] is False
        assert "compression_level must be between 0 and 9" in result["errors"]

    def test_to_dict(self, s3_backup_instance):
        d = s3_backup_instance.to_dict()
        assert d["s3_bucket"] == "my-bucket"
        assert d["db_name"] == "erp_db"
        assert d["encryption_method"] == "aws_kms"
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "s3_bucket": "my-bucket",
            "s3_prefix": "custom/",
            "region": "us-east-1",
            "kms_key_id": "kms-456",
            "db_type": "mysql",
            "db_host": "db.example.com",
            "db_port": 3306,
            "db_name": "myapp",
            "db_user": "admin",
            "retention_days": 60,
            "compression_level": 9,
            "encryption_method": "local_aes",
            "parallel_uploads": 3,
            "enable_encryption": False,
            "version": 5,
        }
        with patch("boto3.client"):
            instance = S3EncryptedBackup.from_dict(data)
        assert instance.s3_bucket == "my-bucket"
        assert instance.s3_prefix == "custom/"
        assert instance.region == "us-east-1"
        assert instance.kms_key_id == "kms-456"
        assert instance.db_type == "mysql"
        assert instance.db_host == "db.example.com"
        assert instance.db_port == 3306
        assert instance.db_name == "myapp"
        assert instance.db_user == "admin"
        assert instance.retention_days == 60
        assert instance.compression_level == 9
        assert instance.encryption_method == EncryptionMethod.LOCAL_AES
        assert instance.parallel_uploads == 3
        assert instance.enable_encryption is False
        assert instance._version == 5

    def test_clone(self, s3_backup_instance):
        cloned = s3_backup_instance.clone()
        assert cloned.s3_bucket == s3_backup_instance.s3_bucket
        assert cloned.db_name == s3_backup_instance.db_name
        assert cloned._version == s3_backup_instance._version + 1
        assert cloned is not s3_backup_instance

    def test_snapshot(self, s3_backup_instance):
        snap = s3_backup_instance.snapshot()
        assert snap["s3_bucket"] == "my-bucket"
        assert snap["db_name"] == "erp_db"
        assert "timestamp" in snap

    def test_version(self, s3_backup_instance):
        assert s3_backup_instance.version() == 1

    def test_audit_trail(self, s3_backup_instance):
        s3_backup_instance._record_audit("TEST", "user", {"key": "value"})
        trail = s3_backup_instance.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, s3_backup_instance):
        old_version = s3_backup_instance._version
        s3_backup_instance.touch("admin")
        assert s3_backup_instance._version == old_version + 1
        assert s3_backup_instance._audit_trail[-1]["action"] == "TOUCH"

    def test_reset(self, s3_backup_instance):
        s3_backup_instance._version = 10
        s3_backup_instance._record_audit("OLD", "user", {})
        s3_backup_instance.reset()
        assert s3_backup_instance._version == 1
        assert len(s3_backup_instance._audit_trail) == 1
        assert s3_backup_instance._audit_trail[0]["action"] == "RESET"

    # --- Private method tests ---

    def test_get_db_dump_command_postgresql(self, s3_backup_instance):
        cmd = s3_backup_instance._get_db_dump_command("/tmp/dump.dump")
        assert cmd[0] == "pg_dump"
        assert "--host=localhost" in cmd
        assert "--port=5432" in cmd
        assert "--username=backup_user" in cmd
        assert "--dbname=erp_db" in cmd
        assert "--file=/tmp/dump.dump" in cmd

    def test_get_db_dump_command_mysql(self, s3_backup_instance):
        s3_backup_instance.db_type = "mysql"
        s3_backup_instance.db_port = 3306
        cmd = s3_backup_instance._get_db_dump_command("/tmp/dump.sql")
        assert cmd[0] == "mysqldump"
        assert "--host=localhost" in cmd
        assert "--port=3306" in cmd
        assert "--user=backup_user" in cmd
        assert "--databases=erp_db" in cmd
        assert "--result-file=/tmp/dump.sql" in cmd

    def test_get_db_dump_command_unsupported_raises(self, s3_backup_instance):
        s3_backup_instance.db_type = "oracle"
        with pytest.raises(BackupError, match="Unsupported database type"):
            s3_backup_instance._get_db_dump_command("/tmp/dump.dump")

    def test_get_db_version_postgresql_success(self, s3_backup_instance):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="PostgreSQL 14.5 on x86_64-pc-linux-gnu\n",
                stderr=""
            )
            version = s3_backup_instance._get_db_version()
            assert version == "PostgreSQL 14.5 on x86_64-pc-linux-gnu"

    def test_get_db_version_postgresql_failure(self, s3_backup_instance):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            version = s3_backup_instance._get_db_version()
            assert version == "unknown"

    def test_get_db_version_mysql_success(self, s3_backup_instance):
        s3_backup_instance.db_type = "mysql"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="VERSION()\n8.0.35\n",
                stderr=""
            )
            version = s3_backup_instance._get_db_version()
            assert version == "8.0.35"

    def test_compress_file(self, s3_backup_instance, tmp_path):
        input_file = tmp_path / "input.dat"
        input_file.write_bytes(b"hello world" * 1000)
        output_file = tmp_path / "output.gz"
        s3_backup_instance._compress_file(str(input_file), str(output_file))
        assert output_file.exists()
        with gzip.open(output_file, "rb") as f:
            content = f.read()
        assert content == b"hello world" * 1000

    def test_calculate_checksum(self, s3_backup_instance, tmp_path):
        file_path = tmp_path / "data.bin"
        content = b"test data" * 100
        file_path.write_bytes(content)
        checksum = s3_backup_instance._calculate_checksum(str(file_path))
        expected = hashlib.sha256(content).hexdigest()
        assert checksum == expected

    def test_get_file_size(self, s3_backup_instance, tmp_path):
        file_path = tmp_path / "data.bin"
        file_path.write_bytes(b"x" * 1024)
        size = s3_backup_instance._get_file_size(str(file_path))
        assert size == 1024
        # non-existent file
        size = s3_backup_instance._get_file_size("/nonexistent")
        assert size == 0

    def test_encrypt_file_no_encryption(self, s3_backup_instance, tmp_path):
        s3_backup_instance.enable_encryption = False
        input_file = tmp_path / "input.dat"
        input_file.write_bytes(b"secret data")
        output_file = tmp_path / "output.dat"
        key_id = s3_backup_instance._encrypt_file(str(input_file), str(output_file))
        assert key_id == "none"
        assert output_file.read_bytes() == b"secret data"

    def test_encrypt_file_aws_kms(self, s3_backup_instance, tmp_path):
        s3_backup_instance.encryption_method = EncryptionMethod.AWS_KMS
        s3_backup_instance.kms_key_id = "kms-123"
        s3_backup_instance.kms_client.encrypt.return_value = {
            "CiphertextBlob": b"encrypted_data"
        }
        input_file = tmp_path / "input.dat"
        input_file.write_bytes(b"secret")
        output_file = tmp_path / "output.enc"
        key_id = s3_backup_instance._encrypt_file(str(input_file), str(output_file))
        assert key_id == "kms-123"
        assert output_file.read_bytes() == b"encrypted_data"
        s3_backup_instance.kms_client.encrypt.assert_called_once()

    def test_encrypt_file_aws_kms_failure(self, s3_backup_instance, tmp_path):
        s3_backup_instance.encryption_method = EncryptionMethod.AWS_KMS
        s3_backup_instance.kms_key_id = "kms-123"
        s3_backup_instance.kms_client.encrypt.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "encrypt"
        )
        input_file = tmp_path / "input.dat"
        input_file.write_bytes(b"secret")
        output_file = tmp_path / "output.enc"
        with pytest.raises(BackupError, match="KMS encryption failed"):
            s3_backup_instance._encrypt_file(str(input_file), str(output_file))

    def test_encrypt_file_local_aes(self, s3_backup_instance, tmp_path):
        s3_backup_instance.encryption_method = EncryptionMethod.LOCAL_AES
        s3_backup_instance._master_key = Fernet.generate_key()
        input_file = tmp_path / "input.dat"
        input_file.write_bytes(b"secret data" * 10)
        output_file = tmp_path / "output.enc"
        key_id = s3_backup_instance._encrypt_file(str(input_file), str(output_file))
        assert key_id == "local-aes"
        assert output_file.exists()
        # Should be longer because of salt+iv+ciphertext
        assert output_file.stat().st_size > len(b"secret data" * 10)

    def test_encrypt_file_fernet(self, s3_backup_instance, tmp_path):
        s3_backup_instance.encryption_method = EncryptionMethod.FERNET
        s3_backup_instance._master_key = Fernet.generate_key()
        input_file = tmp_path / "input.dat"
        input_file.write_bytes(b"fernet data")
        output_file = tmp_path / "output.enc"
        key_id = s3_backup_instance._encrypt_file(str(input_file), str(output_file))
        assert key_id == "fernet"
        # Decrypt to verify
        fernet = Fernet(s3_backup_instance._master_key)
        decrypted = fernet.decrypt(output_file.read_bytes())
        assert decrypted == b"fernet data"

    def test_upload_to_s3(self, s3_backup_instance, tmp_path):
        file_path = tmp_path / "upload.dat"
        file_path.write_bytes(b"data")
        s3_key = "backups/test.enc"
        metadata = {"key": "value"}
        s3_backup_instance._upload_to_s3(str(file_path), s3_key, metadata)
        s3_backup_instance.s3_client.upload_file.assert_called_once_with(
            str(file_path), "my-bucket", s3_key,
            ExtraArgs={"Metadata": metadata, "ServerSideEncryption": "AES256"}
        )

    def test_upload_to_s3_with_kms_sse(self, s3_backup_instance, tmp_path):
        s3_backup_instance.use_sse = True
        s3_backup_instance.kms_key_id = "kms-123"
        file_path = tmp_path / "upload.dat"
        file_path.write_bytes(b"data")
        s3_key = "backups/test.enc"
        metadata = {"key": "value"}
        s3_backup_instance._upload_to_s3(str(file_path), s3_key, metadata)
        extra_args = {
            "Metadata": metadata,
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": "kms-123"
        }
        s3_backup_instance.s3_client.upload_file.assert_called_once_with(
            str(file_path), "my-bucket", s3_key, ExtraArgs=extra_args
        )

    def test_upload_to_s3_failure(self, s3_backup_instance, tmp_path):
        s3_backup_instance.s3_client.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "upload"
        )
        file_path = tmp_path / "upload.dat"
        file_path.write_bytes(b"data")
        with pytest.raises(BackupError, match="Failed to upload to S3"):
            s3_backup_instance._upload_to_s3(str(file_path), "key", {})

    def test_delete_old_backups(self, s3_backup_instance):
        # Mock S3 list and delete
        old_date = datetime(2025, 1, 1, 0, 0, 0)
        new_date = datetime.utcnow()
        s3_backup_instance.s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "old1", "LastModified": old_date},
                    {"Key": "old2", "LastModified": old_date},
                    {"Key": "new", "LastModified": new_date},
                ]
            }
        ]
        deleted = s3_backup_instance._delete_old_backups()
        assert deleted == 2
        assert s3_backup_instance.s3_client.delete_object.call_count == 2

    def test_delete_old_backups_error_logs(self, s3_backup_instance, caplog):
        s3_backup_instance.s3_client.get_paginator.side_effect = ClientError(
            {"Error": {"Code": "InternalError"}}, "list"
        )
        deleted = s3_backup_instance._delete_old_backups()
        assert deleted == 0
        assert "Cleanup failed" in caplog.text

    # --- create_backup integration (with mocks) ---

    @patch("subprocess.run")
    @patch("tempfile.NamedTemporaryFile")
    def test_create_backup_success_aws_kms(self, mock_temp, mock_run, s3_backup_instance):
        # Setup mocks
        mock_temp.return_value.__enter__.return_value.name = "/tmp/dump.dump"
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        with patch.object(s3_backup_instance, "_get_db_version", return_value="PostgreSQL 14.5"):
            with patch.object(s3_backup_instance, "_get_file_size", return_value=1024):
                with patch.object(s3_backup_instance, "_compress_file") as mock_compress:
                    with patch.object(s3_backup_instance, "_encrypt_file", return_value="kms-123"):
                        with patch.object(s3_backup_instance, "_calculate_checksum", return_value="checksum"):
                            with patch.object(s3_backup_instance, "_upload_to_s3") as mock_upload:
                                with patch.object(s3_backup_instance, "_delete_old_backups", return_value=1):
                                    metadata = s3_backup_instance.create_backup("backup_test")
        assert metadata.backup_id == "backup_test"
        assert metadata.status == BackupStatus.SUCCESS
        assert metadata.checksum == "checksum"
        mock_upload.assert_called_once()
        assert metadata.duration_seconds >= 0

    def test_create_backup_dump_failure(self, s3_backup_instance):
        with patch("tempfile.NamedTemporaryFile") as mock_temp:
            mock_temp.return_value.__enter__.return_value.name = "/tmp/dump.dump"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="dump error")
                with pytest.raises(BackupError, match="Database dump failed"):
                    s3_backup_instance.create_backup()

    def test_create_backup_encryption_failure(self, s3_backup_instance):
        with patch("tempfile.NamedTemporaryFile") as mock_temp:
            mock_temp.return_value.__enter__.return_value.name = "/tmp/dump.dump"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                with patch.object(s3_backup_instance, "_get_file_size", return_value=1024):
                    with patch.object(s3_backup_instance, "_compress_file"):
                        with patch.object(s3_backup_instance, "_encrypt_file", side_effect=Exception("encrypt error")):
                            with pytest.raises(BackupError, match="encrypt error"):
                                s3_backup_instance.create_backup()

    # --- restore_backup tests ---

    def test_restore_backup_invalid_status(self, s3_backup_instance, sample_backup_metadata):
        sample_backup_metadata.status = BackupStatus.FAILED
        with pytest.raises(BackupError, match="Cannot restore from failed backup"):
            s3_backup_instance.restore_backup(sample_backup_metadata, "/tmp")

    def test_restore_backup_success_aws_kms(self, s3_backup_instance, sample_backup_metadata, tmp_path):
        sample_backup_metadata.encryption_method = EncryptionMethod.AWS_KMS
        s3_backup_instance.kms_key_id = "kms-123"
        s3_backup_instance.s3_client.download_file = MagicMock()
        s3_backup_instance.kms_client.decrypt = MagicMock(
            return_value={"Plaintext": b"decrypted_data"}
        )
        with patch("gzip.open") as mock_gzip:
            mock_gzip.return_value.__enter__.return_value = MagicMock()
            with patch("shutil.copyfileobj") as mock_copy:
                result = s3_backup_instance.restore_backup(sample_backup_metadata, str(tmp_path))
        s3_backup_instance.s3_client.download_file.assert_called_once()
        s3_backup_instance.kms_client.decrypt.assert_called_once()
        assert result.endswith(".dump")

    def test_restore_backup_success_local_aes(self, s3_backup_instance, sample_backup_metadata, tmp_path):
        sample_backup_metadata.encryption_method = EncryptionMethod.LOCAL_AES
        s3_backup_instance._master_key = Fernet.generate_key()
        s3_backup_instance.s3_client.download_file = MagicMock()
        with patch("builtins.open", mock_open(read_data=b"data")) as mock_file:
            with patch("gzip.open") as mock_gzip:
                mock_gzip.return_value.__enter__.return_value = MagicMock()
                with patch("shutil.copyfileobj"):
                    result = s3_backup_instance.restore_backup(sample_backup_metadata, str(tmp_path))
        assert result.endswith(".dump")

    def test_restore_backup_success_fernet(self, s3_backup_instance, sample_backup_metadata, tmp_path):
        sample_backup_metadata.encryption_method = EncryptionMethod.FERNET
        fernet_key = Fernet.generate_key()
        s3_backup_instance._master_key = fernet_key
        fernet = Fernet(fernet_key)
        encrypted = fernet.encrypt(b"test data")
        s3_backup_instance.s3_client.download_file = MagicMock()
        with patch("builtins.open", mock_open(read_data=encrypted)):
            with patch("gzip.open") as mock_gzip:
                mock_gzip.return_value.__enter__.return_value = MagicMock()
                with patch("shutil.copyfileobj"):
                    result = s3_backup_instance.restore_backup(sample_backup_metadata, str(tmp_path))
        assert result.endswith(".dump")

    def test_restore_backup_no_encryption(self, s3_backup_instance, sample_backup_metadata, tmp_path):
        sample_backup_metadata.encryption_method = EncryptionMethod.NONE
        s3_backup_instance.enable_encryption = False
        s3_backup_instance.s3_client.download_file = MagicMock()
        with patch("builtins.open", mock_open(read_data=b"data")):
            with patch("gzip.open") as mock_gzip:
                mock_gzip.return_value.__enter__.return_value = MagicMock()
                with patch("shutil.copyfileobj"):
                    result = s3_backup_instance.restore_backup(sample_backup_metadata, str(tmp_path))
        assert result.endswith(".dump")
