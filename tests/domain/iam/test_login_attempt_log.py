# test_login_attempt_log.py
# ===========================
# Comprehensive tests for domain/iam/login_attempt_log.py.
# Covers enums, value objects, LoginAttemptLog entity, and LoginAttemptRepository.

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.iam.login_attempt_log import (
    DeviceFingerprint,
    LocationInfo,
    LoginAttemptError,
    LoginAttemptLog,
    LoginAttemptRepository,
    LoginAttemptSource,
    LoginResult,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_location() -> LocationInfo:
    return LocationInfo(
        country="Indonesia",
        city="Jakarta",
        region="Java",
        latitude=-6.2,
        longitude=106.8,
    )


@pytest.fixture
def sample_device() -> DeviceFingerprint:
    return DeviceFingerprint(
        user_agent="Mozilla/5.0",
        accept_language="id-ID",
        screen_resolution="1920x1080",
        timezone_offset=420,
        platform="Windows",
    )


@pytest.fixture
def success_log(sample_location, sample_device) -> LoginAttemptLog:
    return LoginAttemptLog.record_success(
        user_id=uuid4(),
        username="alice",
        ip_address="192.168.1.1",
        source=LoginAttemptSource.WEB,
        location=sample_location,
        device_fingerprint=sample_device,
        session_id=uuid4(),
        correlation_id="corr-123",
    )


@pytest.fixture
def failure_log() -> LoginAttemptLog:
    return LoginAttemptLog.record_failure(
        username="bob",
        result=LoginResult.FAILURE_WRONG_PASSWORD,
        ip_address="10.0.0.1",
        source=LoginAttemptSource.MOBILE,
        user_id=uuid4(),
        failure_reason="Invalid password",
        correlation_id="corr-456",
    )


@pytest.fixture
def repository() -> LoginAttemptRepository:
    """Clear repository storage before each test."""
    LoginAttemptRepository._storage.clear()
    return LoginAttemptRepository


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestLoginResult:
    def test_members_exist(self):
        assert hasattr(LoginResult, "SUCCESS")
        assert hasattr(LoginResult, "FAILURE_WRONG_PASSWORD")
        assert hasattr(LoginResult, "FAILURE_USER_NOT_FOUND")
        assert hasattr(LoginResult, "FAILURE_ACCOUNT_LOCKED")
        assert hasattr(LoginResult, "FAILURE_ACCOUNT_INACTIVE")
        assert hasattr(LoginResult, "FAILURE_TOO_MANY_ATTEMPTS")
        assert hasattr(LoginResult, "FAILURE_INVALID_TOKEN")
        assert hasattr(LoginResult, "FAILURE_EXPIRED_TOKEN")
        assert hasattr(LoginResult, "FAILURE_IP_BLOCKED")
        assert hasattr(LoginResult, "FAILURE_MFA_REQUIRED")
        assert hasattr(LoginResult, "FAILURE_MFA_INVALID")
        assert hasattr(LoginResult, "FAILURE_SUSPECTED_FRAUD")

    def test_member_is_instance(self):
        assert isinstance(LoginResult.SUCCESS, LoginResult)

    def test_is_success(self):
        assert LoginResult.SUCCESS.is_success() is True
        assert LoginResult.FAILURE_WRONG_PASSWORD.is_success() is False

    def test_is_failure(self):
        assert LoginResult.FAILURE_WRONG_PASSWORD.is_failure() is True
        assert LoginResult.SUCCESS.is_failure() is False

    def test_display_name(self):
        assert LoginResult.SUCCESS.display_name() == "Berhasil"
        assert LoginResult.FAILURE_WRONG_PASSWORD.display_name() == "Salah"
        assert LoginResult.FAILURE_USER_NOT_FOUND.display_name() == "User Tidak Ditemukan"
        assert LoginResult.FAILURE_ACCOUNT_LOCKED.display_name() == "Akun Terkunci"
        assert LoginResult.FAILURE_ACCOUNT_INACTIVE.display_name() == "Akun Tidak Aktif"
        assert LoginResult.FAILURE_TOO_MANY_ATTEMPTS.display_name() == "Terlalu Banyak Percobaan"
        assert LoginResult.FAILURE_INVALID_TOKEN.display_name() == "Token Tidak Valid"
        assert LoginResult.FAILURE_EXPIRED_TOKEN.display_name() == "Token Kadaluarsa"
        assert LoginResult.FAILURE_IP_BLOCKED.display_name() == "IP Diblokir"
        assert LoginResult.FAILURE_MFA_REQUIRED.display_name() == "MFA Diperlukan"
        assert LoginResult.FAILURE_MFA_INVALID.display_name() == "MFA Tidak Valid"
        assert LoginResult.FAILURE_SUSPECTED_FRAUD.display_name() == "Terdeteksi Fraud"

    def test_from_string(self):
        assert LoginResult.from_string("success") == LoginResult.SUCCESS
        assert LoginResult.from_string("wrong_password") == LoginResult.FAILURE_WRONG_PASSWORD
        assert LoginResult.from_string("INVALID") is None


class TestLoginAttemptSource:
    def test_members_exist(self):
        assert hasattr(LoginAttemptSource, "WEB")
        assert hasattr(LoginAttemptSource, "MOBILE")
        assert hasattr(LoginAttemptSource, "API")
        assert hasattr(LoginAttemptSource, "CLI")
        assert hasattr(LoginAttemptSource, "UNKNOWN")

    def test_member_is_instance(self):
        assert isinstance(LoginAttemptSource.WEB, LoginAttemptSource)

    def test_display_name(self):
        assert LoginAttemptSource.WEB.display_name() == "Web Browser"
        assert LoginAttemptSource.MOBILE.display_name() == "Mobile App"
        assert LoginAttemptSource.API.display_name() == "API Client"
        assert LoginAttemptSource.CLI.display_name() == "Command Line"
        assert LoginAttemptSource.UNKNOWN.display_name() == "Unknown"


# ----------------------------------------------------------------------
# LoginAttemptError
# ----------------------------------------------------------------------
class TestLoginAttemptError:
    def test_construction(self):
        err = LoginAttemptError("Test error")
        assert isinstance(err, ValueError)
        assert str(err) == "Test error"


# ----------------------------------------------------------------------
# LocationInfo
# ----------------------------------------------------------------------
class TestLocationInfo:
    def test_construction(self):
        loc = LocationInfo(
            country="ID",
            city="Jakarta",
            region="Java",
            latitude=-6.2,
            longitude=106.8,
        )
        assert loc.country == "ID"
        assert loc.city == "Jakarta"
        assert loc.region == "Java"
        assert loc.latitude == -6.2
        assert loc.longitude == 106.8

    def test_to_dict(self):
        loc = LocationInfo(country="US", city="NY", latitude=40.7, longitude=-74.0)
        d = loc.to_dict()
        assert d["country"] == "US"
        assert d["city"] == "NY"
        assert d["latitude"] == 40.7
        assert d["longitude"] == -74.0

    def test_from_dict(self):
        data = {
            "country": "UK",
            "city": "London",
            "region": "England",
            "latitude": 51.5,
            "longitude": -0.1,
        }
        loc = LocationInfo.from_dict(data)
        assert loc.country == "UK"
        assert loc.city == "London"
        assert loc.region == "England"
        assert loc.latitude == 51.5
        assert loc.longitude == -0.1


# ----------------------------------------------------------------------
# DeviceFingerprint
# ----------------------------------------------------------------------
class TestDeviceFingerprint:
    def test_construction(self):
        device = DeviceFingerprint(
            user_agent="Mozilla/5.0",
            accept_language="id-ID",
            screen_resolution="1920x1080",
            timezone_offset=420,
            platform="Windows",
        )
        assert device.user_agent == "Mozilla/5.0"
        assert device.accept_language == "id-ID"
        assert device.screen_resolution == "1920x1080"
        assert device.timezone_offset == 420
        assert device.platform == "Windows"

    def test_to_dict_truncates_user_agent(self):
        long_ua = "x" * 600
        device = DeviceFingerprint(user_agent=long_ua)
        d = device.to_dict()
        assert len(d["user_agent"]) == 500

    def test_to_dict(self):
        device = DeviceFingerprint(
            user_agent="Chrome",
            accept_language="en-US",
            screen_resolution="1024x768",
            timezone_offset=-240,
            platform="Linux",
        )
        d = device.to_dict()
        assert d["user_agent"] == "Chrome"
        assert d["accept_language"] == "en-US"
        assert d["screen_resolution"] == "1024x768"
        assert d["timezone_offset"] == -240
        assert d["platform"] == "Linux"

    def test_from_dict(self):
        data = {
            "user_agent": "Firefox",
            "accept_language": "fr-FR",
            "screen_resolution": "1280x720",
            "timezone_offset": 60,
            "platform": "Mac",
        }
        device = DeviceFingerprint.from_dict(data)
        assert device.user_agent == "Firefox"
        assert device.accept_language == "fr-FR"
        assert device.screen_resolution == "1280x720"
        assert device.timezone_offset == 60
        assert device.platform == "Mac"


# ----------------------------------------------------------------------
# LoginAttemptLog
# ----------------------------------------------------------------------
class TestLoginAttemptLog:
    def test_record_success(self, sample_location, sample_device):
        user_id = uuid4()
        session_id = uuid4()
        log = LoginAttemptLog.record_success(
            user_id=user_id,
            username="alice",
            ip_address="192.168.1.1",
            source=LoginAttemptSource.WEB,
            location=sample_location,
            device_fingerprint=sample_device,
            session_id=session_id,
            correlation_id="corr-123",
        )
        assert log.log_id is not None
        assert log.user_id == user_id
        assert log.username == "alice"
        assert log.result == LoginResult.SUCCESS
        assert log.ip_address == "192.168.1.1"
        assert log.source == LoginAttemptSource.WEB
        assert log.timestamp is not None
        assert log.timestamp.tzinfo == UTC
        assert log.location == sample_location
        assert log.device_fingerprint == sample_device
        assert log.session_id == session_id
        assert log.correlation_id == "corr-123"
        assert log.failure_reason is None
        assert log.metadata == {}

    def test_record_failure(self):
        user_id = uuid4()
        log = LoginAttemptLog.record_failure(
            username="bob",
            result=LoginResult.FAILURE_ACCOUNT_LOCKED,
            ip_address="10.0.0.1",
            source=LoginAttemptSource.API,
            user_id=user_id,
            failure_reason="Account locked due to multiple failures",
            correlation_id="corr-456",
        )
        assert log.log_id is not None
        assert log.user_id == user_id
        assert log.username == "bob"
        assert log.result == LoginResult.FAILURE_ACCOUNT_LOCKED
        assert log.ip_address == "10.0.0.1"
        assert log.source == LoginAttemptSource.API
        assert log.failure_reason == "Account locked due to multiple failures"
        assert log.correlation_id == "corr-456"
        assert log.location == LocationInfo()
        assert log.device_fingerprint == DeviceFingerprint()

    def test_from_dict(self, success_log):
        d = success_log.to_dict()
        reconstructed = LoginAttemptLog.from_dict(d)
        assert reconstructed.log_id == success_log.log_id
        assert reconstructed.user_id == success_log.user_id
        assert reconstructed.username == success_log.username
        assert reconstructed.result == success_log.result
        assert reconstructed.ip_address == success_log.ip_address
        assert reconstructed.source == success_log.source
        assert reconstructed.timestamp == success_log.timestamp
        assert reconstructed.location.country == success_log.location.country
        assert reconstructed.device_fingerprint.user_agent == success_log.device_fingerprint.user_agent
        assert reconstructed.session_id == success_log.session_id
        assert reconstructed.correlation_id == success_log.correlation_id

    def test_from_dict_missing_fields_uses_defaults(self):
        data = {
            "log_id": str(uuid4()),
            "username": "test",
            "result": "success",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        log = LoginAttemptLog.from_dict(data)
        assert log.user_id is None
        assert log.ip_address is None
        assert log.source == LoginAttemptSource.UNKNOWN
        assert log.location == LocationInfo()
        assert log.device_fingerprint == DeviceFingerprint()

    def test_validate_valid(self, success_log):
        result = success_log.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_empty_username(self):
        with pytest.raises(LoginAttemptError, match="Username must be non-empty"):
            LoginAttemptLog(
                log_id=uuid4(),
                user_id=None,
                username="",
                result=LoginResult.SUCCESS,
                ip_address=None,
                source=LoginAttemptSource.WEB,
                timestamp=datetime.now(UTC),
            )

    def test_validate_invalid_result(self):
        with pytest.raises(LoginAttemptError, match="Invalid result"):
            LoginAttemptLog(
                log_id=uuid4(),
                user_id=None,
                username="test",
                result="invalid",  # type: ignore
                ip_address=None,
                source=LoginAttemptSource.WEB,
                timestamp=datetime.now(UTC),
            )

    def test_validate_invalid_source(self):
        with pytest.raises(LoginAttemptError, match="Invalid source"):
            LoginAttemptLog(
                log_id=uuid4(),
                user_id=None,
                username="test",
                result=LoginResult.SUCCESS,
                ip_address=None,
                source="web",  # type: ignore
                timestamp=datetime.now(UTC),
            )

    def test_is_success_and_is_failure(self, success_log, failure_log):
        assert success_log.is_success() is True
        assert success_log.is_failure() is False
        assert failure_log.is_success() is False
        assert failure_log.is_failure() is True

    def test_is_high_risk(self):
        # Normal failure is not high risk
        log1 = LoginAttemptLog.record_failure(
            username="user",
            result=LoginResult.FAILURE_WRONG_PASSWORD,
        )
        assert log1.is_high_risk() is False

        # High risk results
        log2 = LoginAttemptLog.record_failure(
            username="user",
            result=LoginResult.FAILURE_TOO_MANY_ATTEMPTS,
        )
        assert log2.is_high_risk() is True

        log3 = LoginAttemptLog.record_failure(
            username="user",
            result=LoginResult.FAILURE_SUSPECTED_FRAUD,
        )
        assert log3.is_high_risk() is True

        log4 = LoginAttemptLog.record_failure(
            username="user",
            result=LoginResult.FAILURE_IP_BLOCKED,
        )
        assert log4.is_high_risk() is True

    def test_age_methods(self, success_log):
        # Patch datetime to return a fixed time
        fixed_now = datetime(2025, 1, 20, 12, 0, tzinfo=UTC)
        with patch("domain.iam.login_attempt_log.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.utc = UTC
            # Set timestamp to 1 hour ago
            log = LoginAttemptLog.record_success(
                user_id=uuid4(),
                username="alice",
                timestamp=datetime(2025, 1, 20, 11, 0, tzinfo=UTC),  # but record_success doesn't accept timestamp
                # We'll manually create
            )
            # Instead, we'll construct directly
            log = LoginAttemptLog(
                log_id=uuid4(),
                user_id=uuid4(),
                username="alice",
                result=LoginResult.SUCCESS,
                ip_address=None,
                source=LoginAttemptSource.WEB,
                timestamp=datetime(2025, 1, 20, 11, 0, tzinfo=UTC),
            )
            # Now with fixed now at 2025-01-20 12:00, age should be 3600 seconds
            assert log.get_age_seconds() == 3600
            assert log.get_age_minutes() == 60
            assert log.get_age_hours() == 1
            assert log.get_age_days() == 0

    def test_to_dict(self, success_log):
        d = success_log.to_dict()
        assert d["log_id"] == str(success_log.log_id)
        assert d["user_id"] == str(success_log.user_id)
        assert d["username"] == success_log.username
        assert d["result"] == "success"
        assert d["ip_address"] == success_log.ip_address
        assert d["source"] == "web"
        assert d["timestamp"] == success_log.timestamp.isoformat()
        assert d["timestamp_iso"] == success_log.timestamp.isoformat()
        assert d["timestamp_unix"] == int(success_log.timestamp.timestamp())
        assert d["failure_reason"] is None
        assert d["session_id"] == str(success_log.session_id)
        assert d["correlation_id"] == success_log.correlation_id
        assert d["metadata"] == {}
        assert d["is_success"] is True
        assert d["is_failure"] is False
        assert "location" in d
        assert "device_fingerprint" in d

    def test_to_dict_without_location_and_fingerprint(self, success_log):
        d = success_log.to_dict(include_location=False, include_fingerprint=False)
        assert "location" not in d
        assert "device_fingerprint" not in d

    def test_clone(self, success_log):
        cloned = success_log.clone()
        assert cloned.log_id != success_log.log_id
        assert cloned.user_id == success_log.user_id
        assert cloned.username == success_log.username
        assert cloned.result == success_log.result
        assert cloned.ip_address == success_log.ip_address
        assert cloned.source == success_log.source
        assert cloned.timestamp == success_log.timestamp
        assert cloned.location == success_log.location
        assert cloned.device_fingerprint == success_log.device_fingerprint
        assert cloned.session_id == success_log.session_id
        assert cloned.correlation_id == success_log.correlation_id
        assert cloned.metadata == success_log.metadata
        # Audit trail should have CLONE entry
        trail = cloned.audit_trail(limit=1)
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, success_log):
        snap = success_log.snapshot()
        assert snap["log_id"] == str(success_log.log_id)
        assert snap["username"] == success_log.username
        assert snap["result"] == "success"
        assert snap["timestamp"] == success_log.timestamp.isoformat()
        assert "timestamp_ms" in snap

    def test_version(self, success_log):
        assert success_log.version() == 1

    def test_audit_trail(self, success_log):
        # Initially should have one CREATE entry from __post_init__?
        # Actually, __post_init__ does not record audit. The audit is recorded by create/update methods.
        # So initially it should be empty.
        trail = success_log.audit_trail()
        # After some operations
        log = success_log.create("system")
        trail = log.audit_trail(limit=1)
        assert trail[0]["action"] == "CREATE"

    def test_entity_methods_create_update_delete_restore(self, success_log):
        # Create
        log = success_log.create("creator")
        trail = log.audit_trail(limit=1)
        assert trail[0]["action"] == "CREATE"

        # Update (immutable? Actually update returns new instance)
        updated = log.update("updater", ip_address="1.2.3.4")
        assert updated.ip_address == "1.2.3.4"
        trail = updated.audit_trail(limit=1)
        assert trail[0]["action"] == "UPDATE"

        # Delete
        deleted = updated.delete("deleter", "test")
        trail = deleted.audit_trail(limit=1)
        assert trail[0]["action"] == "DELETE"

        # Restore
        restored = deleted.restore("restorer")
        trail = restored.audit_trail(limit=1)
        assert trail[0]["action"] == "RESTORE"

        # Activate
        activated = restored.activate("activator")
        trail = activated.audit_trail(limit=1)
        assert trail[0]["action"] == "ACTIVATE"

        # Deactivate
        deactivated = activated.deactivate("deactivator", "reason")
        trail = deactivated.audit_trail(limit=1)
        assert trail[0]["action"] == "DEACTIVATE"

    def test_lock_unlock(self, success_log):
        # Lock
        locked = success_log.lock("locker", "fraud review")
        assert locked.metadata.get("locked_by") == "locker"
        assert locked.metadata.get("lock_reason") == "fraud review"
        assert "locked_at" in locked.metadata
        trail = locked.audit_trail(limit=1)
        assert trail[0]["action"] == "LOCK"

        # Unlock
        unlocked = locked.unlock("unlocker")
        assert "locked_by" not in unlocked.metadata
        assert "lock_reason" not in unlocked.metadata
        assert "locked_at" not in unlocked.metadata
        trail = unlocked.audit_trail(limit=1)
        assert trail[0]["action"] == "UNLOCK"

    def test_touch(self, success_log):
        touched = success_log.touch("toucher")
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"


# ----------------------------------------------------------------------
# LoginAttemptRepository
# ----------------------------------------------------------------------
class TestLoginAttemptRepository:
    @pytest.fixture(autouse=True)
    def clear_storage(self):
        LoginAttemptRepository._storage.clear()
        yield
        LoginAttemptRepository._storage.clear()

    @pytest.mark.asyncio
    async def test_save_and_get_by_user(self, success_log, failure_log):
        await LoginAttemptRepository.save(success_log)
        await LoginAttemptRepository.save(failure_log)

        user_id = success_log.user_id
        logs = await LoginAttemptRepository.get_by_user(user_id)
        assert len(logs) == 1
        assert logs[0].log_id == success_log.log_id

        # With limit
        logs2 = await LoginAttemptRepository.get_by_user(user_id, limit=0)
        assert len(logs2) == 0

    @pytest.mark.asyncio
    async def test_save_many(self, success_log, failure_log):
        await LoginAttemptRepository.save_many([success_log, failure_log])
        logs = await LoginAttemptRepository.get_recent_attempts()
        assert len(logs) == 2

    @pytest.mark.asyncio
    async def test_get_by_username(self, success_log, failure_log):
        await LoginAttemptRepository.save_many([success_log, failure_log])
        logs = await LoginAttemptRepository.get_by_username("alice")
        assert len(logs) == 1
        assert logs[0].log_id == success_log.log_id

        logs2 = await LoginAttemptRepository.get_by_username("bob")
        assert len(logs2) == 1
        assert logs2[0].log_id == failure_log.log_id

    @pytest.mark.asyncio
    async def test_get_by_ip(self, success_log, failure_log):
        await LoginAttemptRepository.save_many([success_log, failure_log])
        logs = await LoginAttemptRepository.get_by_ip("192.168.1.1")
        assert len(logs) == 1
        assert logs[0].log_id == success_log.log_id

        # IP not found
        logs2 = await LoginAttemptRepository.get_by_ip("0.0.0.0")
        assert len(logs2) == 0

    @pytest.mark.asyncio
    async def test_get_failed_attempts(self, success_log, failure_log):
        await LoginAttemptRepository.save_many([success_log, failure_log])
        user_id = failure_log.user_id
        since = datetime.now(UTC) - timedelta(days=1)
        count = await LoginAttemptRepository.get_failed_attempts(user_id, since)
        assert count == 1

        # Success user has no failures
        success_user = success_log.user_id
        count2 = await LoginAttemptRepository.get_failed_attempts(success_user, since)
        assert count2 == 0

    @pytest.mark.asyncio
    async def test_get_recent_attempts(self, success_log, failure_log):
        # Need to ensure different timestamps
        with patch("domain.iam.login_attempt_log.datetime") as mock_dt:
            mock_dt.now.side_effect = [
                datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 11, 0, tzinfo=UTC),
            ]
            mock_dt.utc = UTC
            log1 = LoginAttemptLog.record_success(user_id=uuid4(), username="a", ip_address=None)
            log2 = LoginAttemptLog.record_success(user_id=uuid4(), username="b", ip_address=None)
            # Override storage and save manually, but record_success already appended? No, we won't use the repository; we'll manually add to storage.
            LoginAttemptRepository._storage.clear()
            LoginAttemptRepository._storage.append(log1)
            LoginAttemptRepository._storage.append(log2)
            recent = await LoginAttemptRepository.get_recent_attempts(limit=1)
            assert len(recent) == 1
            # Should be the latest (log2) because sorted by timestamp desc
            assert recent[0].username == "b"

    @pytest.mark.asyncio
    async def test_get_by_result(self, success_log, failure_log):
        await LoginAttemptRepository.save_many([success_log, failure_log])
        logs = await LoginAttemptRepository.get_by_result(LoginResult.SUCCESS)
        assert len(logs) == 1
        assert logs[0].log_id == success_log.log_id

        logs2 = await LoginAttemptRepository.get_by_result(LoginResult.FAILURE_WRONG_PASSWORD)
        assert len(logs2) == 1
        assert logs2[0].log_id == failure_log.log_id

        # Non-existent result
        logs3 = await LoginAttemptRepository.get_by_result(LoginResult.FAILURE_ACCOUNT_LOCKED)
        assert len(logs3) == 0

    @pytest.mark.asyncio
    async def test_get_by_date_range(self, success_log, failure_log):
        # Set explicit timestamps
        log1 = LoginAttemptLog(
            log_id=uuid4(),
            user_id=uuid4(),
            username="a",
            result=LoginResult.SUCCESS,
            ip_address=None,
            source=LoginAttemptSource.WEB,
            timestamp=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        log2 = LoginAttemptLog(
            log_id=uuid4(),
            user_id=uuid4(),
            username="b",
            result=LoginResult.SUCCESS,
            ip_address=None,
            source=LoginAttemptSource.WEB,
            timestamp=datetime(2025, 1, 2, 10, 0, tzinfo=UTC),
        )
        LoginAttemptRepository._storage.extend([log1, log2])
        start = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 1, 23, 59, tzinfo=UTC)
        logs = await LoginAttemptRepository.get_by_date_range(start, end)
        assert len(logs) == 1
        assert logs[0].log_id == log1.log_id

    @pytest.mark.asyncio
    async def test_count_by_user(self, success_log, failure_log):
        await LoginAttemptRepository.save_many([success_log, failure_log])
        count = await LoginAttemptRepository.count_by_user(success_log.user_id)
        assert count == 1
        count2 = await LoginAttemptRepository.count_by_user(failure_log.user_id)
        assert count2 == 1

        # With from_date
        since = datetime.now(UTC) - timedelta(days=1)
        count3 = await LoginAttemptRepository.count_by_user(success_log.user_id, from_date=since)
        assert count3 == 1  # assuming timestamp is recent

    @pytest.mark.asyncio
    async def test_count_failures_by_user(self, success_log, failure_log):
        await LoginAttemptRepository.save_many([success_log, failure_log])
        since = datetime.now(UTC) - timedelta(days=1)
        count = await LoginAttemptRepository.count_failures_by_user(failure_log.user_id, since)
        assert count == 1
        count2 = await LoginAttemptRepository.count_failures_by_user(success_log.user_id, since)
        assert count2 == 0

    @pytest.mark.asyncio
    async def test_count_by_ip(self, success_log, failure_log):
        await LoginAttemptRepository.save_many([success_log, failure_log])
        since = datetime.now(UTC) - timedelta(days=1)
        count = await LoginAttemptRepository.count_by_ip("192.168.1.1", since)
        assert count == 1
        count2 = await LoginAttemptRepository.count_by_ip("10.0.0.1", since)
        assert count2 == 1
        count3 = await LoginAttemptRepository.count_by_ip("0.0.0.0", since)
        assert count3 == 0

    @pytest.mark.asyncio
    async def test_clear(self, success_log):
        await LoginAttemptRepository.save(success_log)
        assert len(LoginAttemptRepository._storage) == 1
        await LoginAttemptRepository.clear()
        assert len(LoginAttemptRepository._storage) == 0

    @pytest.mark.asyncio
    async def test_clear_older_than(self, success_log):
        # Create old and new logs
        old = LoginAttemptLog(
            log_id=uuid4(),
            user_id=uuid4(),
            username="old",
            result=LoginResult.SUCCESS,
            ip_address=None,
            source=LoginAttemptSource.WEB,
            timestamp=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        )
        new = LoginAttemptLog(
            log_id=uuid4(),
            user_id=uuid4(),
            username="new",
            result=LoginResult.SUCCESS,
            ip_address=None,
            source=LoginAttemptSource.WEB,
            timestamp=datetime.now(UTC),
        )
        LoginAttemptRepository._storage.extend([old, new])
        deleted = await LoginAttemptRepository.clear_older_than(days=10)  # delete older than 10 days
        assert deleted == 1
        remaining = await LoginAttemptRepository.get_recent_attempts()
        assert len(remaining) == 1
        assert remaining[0].username == "new"