# test_threat_detection_anomaly_login.py
# Comprehensive tests for security_hardening/threat_detection_anomaly_login.py
# All datetime.now() calls are mocked to avoid flaky tests.

import json
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from security_hardening.threat_detection_anomaly_login import (
    AnomalyAlert,
    AnomalyLoginDetector,
    AnomalySeverity,
    AnomalyType,
    LoginAttempt,
)

# ============================================================================
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime():
    """Mock datetime.now and datetime.utcnow to fixed values."""
    with patch("security_hardening.threat_detection_anomaly_login.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def detector():
    """Create a detector with default settings (low thresholds for testing)."""
    return AnomalyLoginDetector(
        max_failures_per_minute=2,
        max_failures_per_hour=5,
        max_failures_per_day=10,
        max_success_per_minute=10,
        max_attempts_per_window=3,
        velocity_window_seconds=30,
        allowed_countries=["ID", "SG"],
        blacklisted_ips=["1.2.3.4"],
        whitelisted_users=["admin", "trusted"],
        max_travel_speed_kmh=100.0,
        enable_impossible_travel=True,
        enable_geo_fencing=True,
    )


@pytest.fixture
def sample_login_attempt():
    return LoginAttempt(
        user_id="alice",
        timestamp=FIXED_NOW,
        source_ip="192.168.1.1",
        user_agent="Mozilla/5.0",
        success=False,
        country="ID",
        city="Jakarta",
        device_fingerprint="fp-123",
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestAnomalyType:
    def test_members(self):
        assert AnomalyType.BRUTE_FORCE.value == "brute_force"
        assert AnomalyType.UNUSUAL_LOCATION.value == "unusual_location"
        assert AnomalyType.UNUSUAL_DEVICE.value == "unusual_device"
        assert AnomalyType.UNUSUAL_TIME.value == "unusual_time"
        assert AnomalyType.HIGH_VELOCITY.value == "high_velocity"
        assert AnomalyType.BLACKLISTED_IP.value == "blacklisted_ip"
        assert AnomalyType.IMPOSSIBLE_TRAVEL.value == "impossible_travel"
        assert AnomalyType.CREDENTIAL_STUFFING.value == "credential_stuffing"
        assert AnomalyType.TOR_EXIT_NODE.value == "tor_exit_node"
        assert AnomalyType.DATACENTER_IP.value == "datacenter_ip"

    def test_display_name(self):
        assert AnomalyType.BRUTE_FORCE.display_name() == "Brute Force"
        assert AnomalyType.UNUSUAL_LOCATION.display_name() == "Lokasi Tidak Biasa"


class TestAnomalySeverity:
    def test_members(self):
        assert AnomalySeverity.LOW.value == "low"
        assert AnomalySeverity.MEDIUM.value == "medium"
        assert AnomalySeverity.HIGH.value == "high"
        assert AnomalySeverity.CRITICAL.value == "critical"

    def test_display_name(self):
        assert AnomalySeverity.LOW.display_name() == "Rendah"
        assert AnomalySeverity.CRITICAL.display_name() == "Kritis"


# ============================================================================
# Tests for LoginAttempt
# ============================================================================

class TestLoginAttempt:
    def test_construction_valid(self, sample_login_attempt):
        assert sample_login_attempt.user_id == "alice"
        assert sample_login_attempt.source_ip == "192.168.1.1"
        assert sample_login_attempt.success is False
        assert sample_login_attempt._version == 1
        assert len(sample_login_attempt._snapshots) == 1

    def test_validation_missing_user_id(self):
        with pytest.raises(ValueError, match="user_id is required"):
            LoginAttempt(
                user_id="",
                timestamp=FIXED_NOW,
                source_ip="1.1.1.1",
                user_agent="test",
                success=True,
            )

    def test_validation_missing_source_ip(self):
        with pytest.raises(ValueError, match="source_ip is required"):
            LoginAttempt(
                user_id="u",
                timestamp=FIXED_NOW,
                source_ip="",
                user_agent="test",
                success=True,
            )

    def test_validate(self, sample_login_attempt):
        result = sample_login_attempt.validate()
        assert result["is_valid"] is True

    def test_to_dict(self, sample_login_attempt):
        d = sample_login_attempt.to_dict()
        assert d["user_id"] == "alice"
        assert d["source_ip"] == "192.168.1.1"
        assert d["success"] is False
        assert d["version"] == 1
        assert "attempt_id" in d

    def test_from_dict(self, sample_login_attempt):
        d = sample_login_attempt.to_dict()
        restored = LoginAttempt.from_dict(d)
        assert restored.user_id == sample_login_attempt.user_id
        assert restored.source_ip == sample_login_attempt.source_ip
        assert restored.success == sample_login_attempt.success
        assert restored.timestamp == sample_login_attempt.timestamp

    def test_clone(self, sample_login_attempt):
        cloned = sample_login_attempt.clone()
        assert cloned is not sample_login_attempt
        assert cloned.user_id == sample_login_attempt.user_id
        assert cloned._version == sample_login_attempt._version + 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_login_attempt):
        snap = sample_login_attempt.snapshot()
        assert snap["version"] == 1
        assert snap["user_id"] == "alice"
        assert snap["success"] is False

    def test_version(self, sample_login_attempt):
        assert sample_login_attempt.version() == 1

    def test_audit_trail(self, sample_login_attempt):
        sample_login_attempt.touch("tester")
        trail = sample_login_attempt.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"

    def test_touch(self, sample_login_attempt):
        old_version = sample_login_attempt._version
        touched = sample_login_attempt.touch("tester")
        assert touched._version == old_version + 1


# ============================================================================
# Tests for AnomalyAlert
# ============================================================================

class TestAnomalyAlert:
    def test_construction_valid(self):
        alert = AnomalyAlert(
            alert_id=str(uuid4()),
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.CRITICAL,
            description="Brute force detected",
            timestamp=FIXED_NOW,
            evidence={"failures": 5},
        )
        assert alert.anomaly_type == AnomalyType.BRUTE_FORCE
        assert alert.severity == AnomalySeverity.CRITICAL
        assert alert.acknowledged is False
        assert alert._version == 1

    def test_validation_missing_alert_id(self):
        with pytest.raises(ValueError, match="alert_id is required"):
            AnomalyAlert(
                alert_id="",
                user_id="u",
                anomaly_type=AnomalyType.BRUTE_FORCE,
                severity=AnomalySeverity.LOW,
                description="test",
                timestamp=FIXED_NOW,
            )

    def test_validation_missing_user_id(self):
        with pytest.raises(ValueError, match="user_id is required"):
            AnomalyAlert(
                alert_id="a",
                user_id="",
                anomaly_type=AnomalyType.BRUTE_FORCE,
                severity=AnomalySeverity.LOW,
                description="test",
                timestamp=FIXED_NOW,
            )

    def test_validation_invalid_anomaly_type(self):
        with pytest.raises(ValueError, match="invalid anomaly_type"):
            AnomalyAlert(
                alert_id="a",
                user_id="u",
                anomaly_type="invalid",  # type: ignore
                severity=AnomalySeverity.LOW,
                description="test",
                timestamp=FIXED_NOW,
            )

    def test_validate(self):
        alert = AnomalyAlert(
            alert_id="a",
            user_id="u",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.LOW,
            description="test",
            timestamp=FIXED_NOW,
        )
        result = alert.validate()
        assert result["is_valid"] is True

    def test_to_dict(self):
        alert = AnomalyAlert(
            alert_id="a123",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.HIGH,
            description="Brute force",
            timestamp=FIXED_NOW,
            evidence={"count": 10},
            acknowledged=True,
            acknowledged_by="admin",
        )
        d = alert.to_dict()
        assert d["alert_id"] == "a123"
        assert d["severity"] == "high"
        assert d["acknowledged"] is True
        assert d["acknowledged_by"] == "admin"

    def test_from_dict(self):
        data = {
            "alert_id": "a123",
            "user_id": "alice",
            "anomaly_type": "brute_force",
            "severity": "critical",
            "description": "test",
            "timestamp": FIXED_NOW.isoformat(),
            "evidence": {"count": 5},
            "acknowledged": False,
            "acknowledged_by": None,
            "version": 2,
        }
        alert = AnomalyAlert.from_dict(data)
        assert alert.alert_id == "a123"
        assert alert.anomaly_type == AnomalyType.BRUTE_FORCE
        assert alert.severity == AnomalySeverity.CRITICAL
        assert alert._version == 2

    def test_clone(self):
        alert = AnomalyAlert(
            alert_id="a123",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.HIGH,
            description="test",
            timestamp=FIXED_NOW,
            evidence={"key": "value"},
        )
        cloned = alert.clone()
        assert cloned.alert_id != alert.alert_id
        assert cloned.user_id == alert.user_id
        assert cloned.anomaly_type == alert.anomaly_type
        assert cloned.acknowledged is False
        assert cloned._version == alert._version + 1

    def test_audit_trail_and_touch(self):
        alert = AnomalyAlert(
            alert_id="a",
            user_id="u",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.LOW,
            description="test",
            timestamp=FIXED_NOW,
        )
        alert.touch("tester")
        trail = alert.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for AnomalyLoginDetector - Helper Methods
# ============================================================================

class TestAnomalyLoginDetectorHelpers:
    def test_get_location_with_geoip(self, detector):
        # Mock geoip reader
        mock_reader = MagicMock()
        mock_response = MagicMock()
        mock_response.country.iso_code = "ID"
        mock_response.city.name = "Jakarta"
        mock_response.location.latitude = -6.2
        mock_response.location.longitude = 106.8
        mock_reader.city.return_value = mock_response
        detector._geoip_reader = mock_reader

        country, city, lat, lon = detector._get_location("8.8.8.8")
        assert country == "ID"
        assert city == "Jakarta"
        assert lat == -6.2
        assert lon == 106.8

    def test_get_location_no_geoip(self, detector):
        detector._geoip_reader = None
        country, city, lat, lon = detector._get_location("8.8.8.8")
        assert country is None
        assert city is None
        assert lat is None
        assert lon is None

    def test_get_location_geoip_exception(self, detector):
        mock_reader = MagicMock()
        mock_reader.city.side_effect = Exception("GeoIP error")
        detector._geoip_reader = mock_reader
        country, _city, _lat, _lon = detector._get_location("8.8.8.8")
        assert country is None

    def test_is_tor_exit_node(self, detector):
        detector.tor_exit_nodes = {"1.2.3.4", "5.6.7.8"}
        assert detector._is_tor_exit_node("1.2.3.4") is True
        assert detector._is_tor_exit_node("9.9.9.9") is False

    def test_is_datacenter_ip(self, detector):
        detector.datacenter_ranges = ["192.168.", "10.0."]
        assert detector._is_datacenter_ip("192.168.1.1") is True
        assert detector._is_datacenter_ip("10.0.0.1") is True
        assert detector._is_datacenter_ip("8.8.8.8") is False

    def test_clean_old_attempts(self, detector):
        # Add attempts both old and new
        now = FIXED_NOW
        old_time = now - timedelta(days=2)
        new_time = now - timedelta(hours=1)

        old_attempt = LoginAttempt(
            user_id="alice",
            timestamp=old_time,
            source_ip="1.1.1.1",
            user_agent="test",
            success=False,
        )
        new_attempt = LoginAttempt(
            user_id="alice",
            timestamp=new_time,
            source_ip="2.2.2.2",
            user_agent="test",
            success=False,
        )
        detector._attempts = [old_attempt, new_attempt]
        detector._user_failures["alice"] = [old_time, new_time]
        detector._user_locations["alice"] = [(old_time, "1.1.1.1", 0.0, 0.0)]

        detector._clean_old_attempts()
        assert len(detector._attempts) == 1
        assert detector._attempts[0].timestamp == new_time
        assert len(detector._user_failures["alice"]) == 1
        assert detector._user_failures["alice"][0] == new_time
        assert len(detector._user_locations["alice"]) == 1


# ============================================================================
# Tests for AnomalyLoginDetector - Record Attempt
# ============================================================================

class TestAnomalyLoginDetectorRecord:
    def test_record_attempt_success(self, detector):
        detector.record_attempt("alice", "8.8.8.8", "Mozilla/5.0", True, "fp-123")
        assert len(detector._attempts) == 1
        assert len(detector._user_success["alice"]) == 1
        # Location should be recorded if geoip not available, but no location data
        # We can't test location because geoip is not available in tests

    def test_record_attempt_failure(self, detector):
        detector.record_attempt("bob", "1.1.1.1", "Chrome", False)
        assert len(detector._attempts) == 1
        assert len(detector._user_failures["bob"]) == 1

    def test_record_attempt_with_geoip(self, detector):
        # Mock geoip
        mock_reader = MagicMock()
        mock_response = MagicMock()
        mock_response.country.iso_code = "SG"
        mock_response.city.name = "Singapore"
        mock_response.location.latitude = 1.3
        mock_response.location.longitude = 103.8
        mock_reader.city.return_value = mock_response
        detector._geoip_reader = mock_reader

        detector.record_attempt("alice", "8.8.8.8", "Mozilla", True)
        attempt = detector._attempts[0]
        assert attempt.country == "SG"
        assert attempt.city == "Singapore"


# ============================================================================
# Tests for AnomalyLoginDetector - Detection Rules
# ============================================================================

class TestAnomalyLoginDetectorDetection:
    def test_detect_brute_force_minute(self, detector):
        # Add 3 failures in 1 minute (threshold is 2)
        now = FIXED_NOW
        for i in range(3):
            detector._user_failures["alice"].append(now - timedelta(seconds=i*10))

        alert = detector._detect_brute_force("alice")
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.BRUTE_FORCE
        assert alert.severity == AnomalySeverity.CRITICAL
        assert "3 failures in last minute" in alert.description

    def test_detect_brute_force_hour(self, detector):
        # Add 6 failures in last hour (threshold is 5)
        now = FIXED_NOW
        for i in range(6):
            detector._user_failures["alice"].append(now - timedelta(minutes=i*5))

        alert = detector._detect_brute_force("alice")
        assert alert is not None
        assert "6 failures in last hour" in alert.description
        assert alert.severity == AnomalySeverity.HIGH

    def test_detect_brute_force_day(self, detector):
        # Add 11 failures in last day (threshold is 10)
        now = FIXED_NOW
        for i in range(11):
            detector._user_failures["alice"].append(now - timedelta(hours=i*2))

        alert = detector._detect_brute_force("alice")
        assert alert is not None
        assert "11 failures in last 24 hours" in alert.description

    def test_detect_brute_force_no_alert(self, detector):
        detector._user_failures["alice"].append(FIXED_NOW - timedelta(seconds=5))
        alert = detector._detect_brute_force("alice")
        assert alert is None

    def test_detect_high_velocity(self, detector):
        # Add 4 attempts in 30 seconds (threshold is 3)
        now = FIXED_NOW
        for i in range(4):
            detector._attempts.append(
                LoginAttempt(
                    user_id="alice",
                    timestamp=now - timedelta(seconds=i*5),
                    source_ip="1.1.1.1",
                    user_agent="test",
                    success=False,
                )
            )
        alert = detector._detect_high_velocity("alice")
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.HIGH_VELOCITY
        assert "4 attempts in 30s" in alert.description

    def test_detect_high_velocity_no_alert(self, detector):
        detector._attempts.append(
            LoginAttempt(
                user_id="alice",
                timestamp=FIXED_NOW - timedelta(seconds=5),
                source_ip="1.1.1.1",
                user_agent="test",
                success=False,
            )
        )
        alert = detector._detect_high_velocity("alice")
        assert alert is None

    def test_detect_unusual_location_allowed(self, detector):
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.1.1.1",
            user_agent="test",
            success=False,
            country="ID",
        )
        alert = detector._detect_unusual_location(attempt)
        assert alert is None

    def test_detect_unusual_location_not_allowed(self, detector):
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.1.1.1",
            user_agent="test",
            success=False,
            country="US",
        )
        alert = detector._detect_unusual_location(attempt)
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.UNUSUAL_LOCATION
        assert "US" in alert.description

    def test_detect_unusual_location_geo_disabled(self, detector):
        detector.enable_geo_fencing = False
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.1.1.1",
            user_agent="test",
            success=False,
            country="US",
        )
        alert = detector._detect_unusual_location(attempt)
        assert alert is None

    def test_detect_unusual_device_unknown_agent(self, detector):
        detector.known_user_agents = {"Chrome", "Firefox"}
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.1.1.1",
            user_agent="Edge",
            success=False,
        )
        alert = detector._detect_unusual_device(attempt)
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.UNUSUAL_DEVICE
        assert "unknown user agent" in alert.description

    def test_detect_unusual_device_unknown_fingerprint(self, detector):
        detector.known_devices = {"fp-123", "fp-456"}
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.1.1.1",
            user_agent="Chrome",
            success=False,
            device_fingerprint="fp-789",
        )
        alert = detector._detect_unusual_device(attempt)
        assert alert is not None
        assert "unrecognized device" in alert.description

    def test_detect_unusual_device_no_alert(self, detector):
        detector.known_user_agents = {"Chrome"}
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.1.1.1",
            user_agent="Chrome",
            success=False,
        )
        alert = detector._detect_unusual_device(attempt)
        assert alert is None

    def test_detect_unusual_time(self, detector):
        # 3 AM is unusual
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW.replace(hour=3, minute=0),
            source_ip="1.1.1.1",
            user_agent="test",
            success=False,
        )
        alert = detector._detect_unusual_time(attempt)
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.UNUSUAL_TIME
        assert "3:00" in alert.description

    def test_detect_unusual_time_normal(self, detector):
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW.replace(hour=10, minute=0),
            source_ip="1.1.1.1",
            user_agent="test",
            success=False,
        )
        alert = detector._detect_unusual_time(attempt)
        assert alert is None

    def test_detect_blacklisted_ip(self, detector):
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.2.3.4",
            user_agent="test",
            success=False,
        )
        alert = detector._detect_blacklisted_ip(attempt)
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.BLACKLISTED_IP

    def test_detect_blacklisted_ip_no_alert(self, detector):
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="8.8.8.8",
            user_agent="test",
            success=False,
        )
        alert = detector._detect_blacklisted_ip(attempt)
        assert alert is None

    def test_detect_tor_exit_node(self, detector):
        detector.tor_exit_nodes = {"5.5.5.5"}
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="5.5.5.5",
            user_agent="test",
            success=False,
        )
        alert = detector._detect_tor_exit_node(attempt)
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.TOR_EXIT_NODE

    def test_detect_datacenter_ip(self, detector):
        detector.datacenter_ranges = ["192.168."]
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="192.168.1.1",
            user_agent="test",
            success=False,
        )
        alert = detector._detect_datacenter_ip(attempt)
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.DATACENTER_IP

    def test_detect_impossible_travel(self, detector):
        # Previous location: Jakarta (-6.2, 106.8), now: Tokyo (35.7, 139.7)
        # Distance ~ 5800 km, time diff 0.5 hours => speed ~ 11600 km/h -> impossible
        now = FIXED_NOW
        detector._user_locations["alice"].append(
            (now - timedelta(minutes=30), "1.1.1.1", -6.2, 106.8)
        )
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=now,
            source_ip="2.2.2.2",
            user_agent="test",
            success=False,
            country="JP",
            city="Tokyo",
            lat=35.7,
            lon=139.7,
        )
        alert = detector._detect_impossible_travel(attempt)
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.IMPOSSIBLE_TRAVEL
        assert "Impossible travel" in alert.description

    def test_detect_impossible_travel_no_alert(self, detector):
        # Previous location: Jakarta, now: Bandung (~150 km, > 1 hour) -> speed ~ 150 km/h < threshold
        now = FIXED_NOW
        detector._user_locations["alice"].append(
            (now - timedelta(hours=2), "1.1.1.1", -6.2, 106.8)
        )
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=now,
            source_ip="2.2.2.2",
            user_agent="test",
            success=False,
            lat=-7.8,
            lon=107.6,
        )
        alert = detector._detect_impossible_travel(attempt)
        assert alert is None

    def test_detect_impossible_travel_not_enough_previous(self, detector):
        detector._user_locations["alice"].append((FIXED_NOW, "1.1.1.1", -6.2, 106.8))
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW + timedelta(minutes=5),
            source_ip="2.2.2.2",
            user_agent="test",
            success=False,
            lat=35.7,
            lon=139.7,
        )
        alert = detector._detect_impossible_travel(attempt)
        # Only one previous location, so no alert
        assert alert is None


# ============================================================================
# Tests for AnomalyLoginDetector - Main Analysis Methods
# ============================================================================

class TestAnomalyLoginDetectorAnalysis:
    def test_analyze_attempt_with_record(self, detector, sample_login_attempt):
        alerts = detector.analyze_attempt(sample_login_attempt, record=True)
        # Should have at least one alert (country not allowed? Actually ID is allowed, so maybe none)
        # We'll use a bad country to trigger alert
        bad_attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.1.1.1",
            user_agent="test",
            success=False,
            country="US",
        )
        alerts = detector.analyze_attempt(bad_attempt, record=True)
        assert len(alerts) >= 1
        assert any(a.anomaly_type == AnomalyType.UNUSUAL_LOCATION for a in alerts)
        # Check that attempt was recorded
        assert len(detector._attempts) >= 1

    def test_analyze_attempt_without_record(self, detector, sample_login_attempt):
        detector.analyze_attempt(sample_login_attempt, record=False)
        # Should not record
        assert len(detector._attempts) == 0

    def test_analyze_attempt_whitelisted_user(self, detector, sample_login_attempt):
        detector.whitelisted_users = {"alice"}
        alerts = detector.analyze_attempt(sample_login_attempt, record=True)
        assert len(alerts) == 0

    def test_pre_login_check_brute_force(self, detector):
        # Add failures to trigger brute force
        for i in range(3):
            detector._user_failures["alice"].append(FIXED_NOW - timedelta(seconds=i*10))
        alert = detector.pre_login_check("alice", "1.1.1.1", "test")
        assert alert is not None
        assert alert.anomaly_type == AnomalyType.BRUTE_FORCE

    def test_pre_login_check_no_alert(self, detector):
        alert = detector.pre_login_check("alice", "1.1.1.1", "test")
        assert alert is None

    def test_post_login_check(self, detector):
        alerts = detector.post_login_check("alice", "1.2.3.4", "test", False)
        # Blacklisted IP
        assert len(alerts) >= 1
        assert any(a.anomaly_type == AnomalyType.BLACKLISTED_IP for a in alerts)


# ============================================================================
# Tests for AnomalyLoginDetector - Alert Management
# ============================================================================

class TestAnomalyLoginDetectorAlertManagement:
    def test_get_unacknowledged_alerts(self, detector):
        alert1 = AnomalyAlert(
            alert_id="a1",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.HIGH,
            description="test",
            timestamp=FIXED_NOW,
        )
        alert2 = AnomalyAlert(
            alert_id="a2",
            user_id="alice",
            anomaly_type=AnomalyType.UNUSUAL_LOCATION,
            severity=AnomalySeverity.MEDIUM,
            description="test",
            timestamp=FIXED_NOW,
            acknowledged=True,
            acknowledged_by="admin",
        )
        detector._alerts = [alert1, alert2]
        unack = detector.get_unacknowledged_alerts()
        assert len(unack) == 1
        assert unack[0].alert_id == "a1"

    def test_acknowledge_alert(self, detector):
        alert = AnomalyAlert(
            alert_id="a1",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.HIGH,
            description="test",
            timestamp=FIXED_NOW,
        )
        detector._alerts = [alert]
        result = detector.acknowledge_alert("a1", "admin")
        assert result is True
        assert alert.acknowledged is True
        assert alert.acknowledged_by == "admin"

    def test_acknowledge_alert_already_acknowledged(self, detector):
        alert = AnomalyAlert(
            alert_id="a1",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.HIGH,
            description="test",
            timestamp=FIXED_NOW,
            acknowledged=True,
        )
        detector._alerts = [alert]
        result = detector.acknowledge_alert("a1", "admin")
        assert result is False

    def test_acknowledge_alert_not_found(self, detector):
        result = detector.acknowledge_alert("nonexistent", "admin")
        assert result is False

    def test_get_alerts_for_user(self, detector):
        alert1 = AnomalyAlert(
            alert_id="a1",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.HIGH,
            description="test",
            timestamp=FIXED_NOW,
        )
        alert2 = AnomalyAlert(
            alert_id="a2",
            user_id="bob",
            anomaly_type=AnomalyType.UNUSUAL_LOCATION,
            severity=AnomalySeverity.MEDIUM,
            description="test",
            timestamp=FIXED_NOW,
        )
        detector._alerts = [alert1, alert2]
        alice_alerts = detector.get_alerts_for_user("alice")
        assert len(alice_alerts) == 1
        assert alice_alerts[0].alert_id == "a1"


# ============================================================================
# Tests for AnomalyLoginDetector - Reporting
# ============================================================================

class TestAnomalyLoginDetectorReporting:
    def test_generate_report(self, detector):
        # Add some alerts
        alert1 = AnomalyAlert(
            alert_id="a1",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.CRITICAL,
            description="test",
            timestamp=FIXED_NOW,
        )
        alert2 = AnomalyAlert(
            alert_id="a2",
            user_id="alice",
            anomaly_type=AnomalyType.UNUSUAL_LOCATION,
            severity=AnomalySeverity.MEDIUM,
            description="test",
            timestamp=FIXED_NOW,
        )
        alert3 = AnomalyAlert(
            alert_id="a3",
            user_id="bob",
            anomaly_type=AnomalyType.BLACKLISTED_IP,
            severity=AnomalySeverity.HIGH,
            description="test",
            timestamp=FIXED_NOW,
        )
        detector._alerts = [alert1, alert2, alert3]
        report = detector.generate_report()
        assert report["total_alerts"] == 3
        assert report["unacknowledged"] == 3
        assert report["by_anomaly_type"]["brute_force"] == 1
        assert report["by_anomaly_type"]["unusual_location"] == 1
        assert report["by_anomaly_type"]["blacklisted_ip"] == 1
        assert report["top_users"][0][0] == "alice"
        assert report["top_users"][0][1] == 2
        assert len(report["recent_alerts"]) == 3
        assert "version" in report

    def test_export_to_json(self, detector):
        # Add an alert
        alert = AnomalyAlert(
            alert_id="a1",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.HIGH,
            description="test",
            timestamp=FIXED_NOW,
        )
        detector._alerts = [alert]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            file_path = tmp.name
        try:
            detector.export_to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert data["total_alerts"] == 1
            assert data["by_anomaly_type"]["brute_force"] == 1
        finally:
            import os
            os.unlink(file_path)

    def test_get_statistics(self, detector):
        # Add some alerts and attempts
        alert = AnomalyAlert(
            alert_id="a1",
            user_id="alice",
            anomaly_type=AnomalyType.BRUTE_FORCE,
            severity=AnomalySeverity.HIGH,
            description="test",
            timestamp=FIXED_NOW,
        )
        detector._alerts = [alert]
        attempt = LoginAttempt(
            user_id="alice",
            timestamp=FIXED_NOW,
            source_ip="1.1.1.1",
            user_agent="test",
            success=False,
        )
        detector._attempts = [attempt]
        stats = detector.get_statistics()
        assert stats["total_attempts"] == 1
        assert stats["total_alerts"] == 1
        assert stats["unacknowledged_alerts"] == 1
        assert stats["unique_users"] == 1
        assert stats["version"] == 1


# ============================================================================
# Tests for AnomalyLoginDetector - Entity Methods
# ============================================================================

class TestAnomalyLoginDetectorEntity:
    def test_validate(self, detector):
        result = detector.validate()
        assert result["is_valid"] is True

        detector.max_failures_per_minute = 0
        result = detector.validate()
        assert result["is_valid"] is False
        assert "max_failures_per_minute must be positive" in result["errors"]

        detector.max_failures_per_minute = 5
        detector.velocity_window = 0
        result = detector.validate()
        assert result["is_valid"] is False
        assert "velocity_window_seconds must be positive" in result["errors"]

    def test_to_dict(self, detector):
        d = detector.to_dict()
        assert d["max_failures_per_minute"] == 2
        assert d["enable_geo_fencing"] is True
        assert d["allowed_countries"] == ["ID", "SG"]
        assert d["blacklisted_ips"] == ["1.2.3.4"]
        assert d["whitelisted_users"] == ["admin", "trusted"]
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "max_failures_per_minute": 10,
            "max_failures_per_hour": 30,
            "max_failures_per_day": 100,
            "max_success_per_minute": 20,
            "known_ips": ["1.1.1.1"],
            "known_user_agents": ["Chrome"],
            "known_devices": ["fp-1"],
            "enable_geo_fencing": False,
            "allowed_countries": ["ID"],
            "blacklisted_ips": ["2.2.2.2"],
            "whitelisted_users": ["admin"],
            "velocity_window_seconds": 120,
            "max_login_attempts_per_window": 10,
            "enable_impossible_travel": False,
            "max_travel_speed_kmh": 500.0,
            "tor_exit_node_list": ["3.3.3.3"],
            "datacenter_ip_ranges": ["10.0."],
            "version": 5,
        }
        detector = AnomalyLoginDetector.from_dict(data)
        assert detector.max_failures_per_minute == 10
        assert detector.enable_geo_fencing is False
        assert detector.allowed_countries == {"ID"}
        assert detector.blacklisted_ips == {"2.2.2.2"}
        assert detector.whitelisted_users == {"admin"}
        assert detector.tor_exit_nodes == {"3.3.3.3"}
        assert detector._version == 5

    def test_clone(self, detector):
        cloned = detector.clone()
        assert cloned is not detector
        assert cloned.max_failures_per_minute == detector.max_failures_per_minute
        assert cloned.allowed_countries == detector.allowed_countries
        assert cloned._version == detector._version + 1

    def test_snapshot(self, detector):
        detector._alerts = ["mock"]  # just to have some count
        snap = detector.snapshot()
        assert snap["version"] == 1
        assert snap["total_alerts"] == 1
        assert snap["total_attempts"] == 0
        assert "timestamp" in snap

    def test_version(self, detector):
        assert detector.version() == 1

    def test_audit_trail(self, detector):
        detector._record_audit("TEST", "user", {"foo": "bar"})
        trail = detector.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "user"

    def test_touch(self, detector):
        old_version = detector._version
        touched = detector.touch("tester")
        assert touched._version == old_version + 1
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    def test_reset(self, detector):
        detector._attempts = ["mock"]
        detector._alerts = ["mock"]
        detector._user_failures["alice"] = ["mock"]
        detector._version = 5
        detector.reset()
        assert detector._attempts == []
        assert detector._alerts == []
        assert detector._user_failures == {}
        assert detector._version == 1
        assert detector._audit_trail == []
        trail = detector.audit_trail()
        assert any(entry["action"] == "RESET" for entry in trail)


# ============================================================================
# Integration test for full flow
# ============================================================================

class TestIntegration:
    def test_full_login_flow(self, detector):
        # Simulate multiple failed logins leading to brute force alert
        for _i in range(3):
            detector.post_login_check("alice", "192.168.1.1", "Mozilla", False)
        # Should have a brute force alert
        brute_alerts = [a for a in detector._alerts if a.anomaly_type == AnomalyType.BRUTE_FORCE]
        assert len(brute_alerts) == 1

        # Then a successful login from unusual location (US)
        detector.post_login_check("alice", "8.8.8.8", "Mozilla", True)
        # Should have unusual location alert (US not allowed)
        loc_alerts = [a for a in detector._alerts if a.anomaly_type == AnomalyType.UNUSUAL_LOCATION]
        assert len(loc_alerts) >= 1

        # Acknowledge alerts
        for alert in detector.get_unacknowledged_alerts():
            detector.acknowledge_alert(alert.alert_id, "security_admin")

        # Check unacknowledged
        assert len(detector.get_unacknowledged_alerts()) == 0

        # Generate report
        report = detector.generate_report()
        assert report["total_alerts"] >= 2
        assert report["unacknowledged"] == 0
