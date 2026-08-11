#!/usr/bin/env python3
"""
Module: threat_detection_anomaly_login.py
Layer: Security Hardening

Responsibility:
    Deteksi anomali pada aktivitas login: brute force, login dari lokasi tidak biasa,
    perangkat asing, waktu tidak normal, kecepatan login, dan pola mencurigakan lainnya.
    Mendukung threshold yang dapat dikonfigurasi, blacklist IP, whitelist user,
    notifikasi real-time, dan integrasi dengan SIEM.

Metode yang ditambahkan:
- Untuk LoginAttempt: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk AnomalyAlert: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk AnomalyLoginDetector: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Optional GeoIP
try:
    import geoip2.database

    HAS_GEOIP = True
except ImportError:
    HAS_GEOIP = False


# ============================================================================
# Enums
# ============================================================================
class AnomalyType(Enum):
    BRUTE_FORCE = "brute_force"
    UNUSUAL_LOCATION = "unusual_location"
    UNUSUAL_DEVICE = "unusual_device"
    UNUSUAL_TIME = "unusual_time"
    HIGH_VELOCITY = "high_velocity"
    BLACKLISTED_IP = "blacklisted_ip"
    IMPOSSIBLE_TRAVEL = "impossible_travel"
    CREDENTIAL_STUFFING = "credential_stuffing"
    TOR_EXIT_NODE = "tor_exit_node"
    DATACENTER_IP = "datacenter_ip"

    def display_name(self) -> str:
        names = {
            AnomalyType.BRUTE_FORCE: "Brute Force",
            AnomalyType.UNUSUAL_LOCATION: "Lokasi Tidak Biasa",
            AnomalyType.UNUSUAL_DEVICE: "Perangkat Tidak Biasa",
            AnomalyType.UNUSUAL_TIME: "Waktu Tidak Biasa",
            AnomalyType.HIGH_VELOCITY: "Kecepatan Tinggi",
            AnomalyType.BLACKLISTED_IP: "IP Blacklist",
            AnomalyType.IMPOSSIBLE_TRAVEL: "Perjalanan Tidak Mungkin",
            AnomalyType.CREDENTIAL_STUFFING: "Credential Stuffing",
            AnomalyType.TOR_EXIT_NODE: "Tor Exit Node",
            AnomalyType.DATACENTER_IP: "IP Datacenter",
        }
        return names.get(self, self.value)


class AnomalySeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def display_name(self) -> str:
        names = {
            AnomalySeverity.LOW: "Rendah",
            AnomalySeverity.MEDIUM: "Sedang",
            AnomalySeverity.HIGH: "Tinggi",
            AnomalySeverity.CRITICAL: "Kritis",
        }
        return names.get(self, self.value)


# ============================================================================
# LoginAttempt (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class LoginAttempt:
    user_id: str
    timestamp: datetime
    source_ip: str
    user_agent: str
    success: bool
    country: str | None = None
    city: str | None = None
    device_fingerprint: str | None = None
    lat: float | None = None
    lon: float | None = None

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _attempt_id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.source_ip:
            raise ValueError("source_ip is required")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "attempt_id": self._attempt_id,
                "user_id": self.user_id,
                "success": self.success,
                "timestamp": self.timestamp.isoformat(),
                "timestamp_now": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "attempt_id": self._attempt_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self._attempt_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat(),
            "source_ip": self.source_ip,
            "user_agent": self.user_agent,
            "success": self.success,
            "country": self.country,
            "city": self.city,
            "device_fingerprint": self.device_fingerprint,
            "lat": self.lat,
            "lon": self.lon,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoginAttempt:
        instance = cls(
            user_id=data["user_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source_ip=data["source_ip"],
            user_agent=data["user_agent"],
            success=data["success"],
            country=data.get("country"),
            city=data.get("city"),
            device_fingerprint=data.get("device_fingerprint"),
            lat=data.get("lat"),
            lon=data.get("lon"),
        )
        instance._version = data.get("version", 1)
        instance._attempt_id = data.get("attempt_id", str(uuid4()))
        return instance

    def clone(self) -> LoginAttempt:
        new = LoginAttempt(
            user_id=self.user_id,
            timestamp=datetime.now(UTC),
            source_ip=self.source_ip,
            user_agent=self.user_agent,
            success=self.success,
            country=self.country,
            city=self.city,
            device_fingerprint=self.device_fingerprint,
            lat=self.lat,
            lon=self.lon,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._attempt_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "attempt_id": self._attempt_id,
            "user_id": self.user_id,
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> LoginAttempt:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# AnomalyAlert (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class AnomalyAlert:
    alert_id: str
    user_id: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    description: str
    timestamp: datetime
    evidence: dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    acknowledged_by: str | None = None

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.alert_id:
            raise ValueError("alert_id is required")
        if not self.user_id:
            raise ValueError("user_id is required")
        if not isinstance(self.anomaly_type, AnomalyType):
            raise ValueError("invalid anomaly_type")
        if not isinstance(self.severity, AnomalySeverity):
            raise ValueError("invalid severity")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "alert_id": self.alert_id,
                "user_id": self.user_id,
                "anomaly_type": self.anomaly_type.value,
                "severity": self.severity.value,
                "acknowledged": self.acknowledged,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "alert_id": self.alert_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "user_id": self.user_id,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
            "evidence": self.evidence,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnomalyAlert:
        instance = cls(
            alert_id=data["alert_id"],
            user_id=data["user_id"],
            anomaly_type=AnomalyType(data["anomaly_type"]),
            severity=AnomalySeverity(data["severity"]),
            description=data["description"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            evidence=data.get("evidence", {}),
            acknowledged=data.get("acknowledged", False),
            acknowledged_by=data.get("acknowledged_by"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> AnomalyAlert:
        new = AnomalyAlert(
            alert_id=str(uuid4()),
            user_id=self.user_id,
            anomaly_type=self.anomaly_type,
            severity=self.severity,
            description=self.description,
            timestamp=datetime.now(UTC),
            evidence=self.evidence.copy(),
            acknowledged=False,
            acknowledged_by=None,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.alert_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "alert_id": self.alert_id,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity.value,
            "acknowledged": self.acknowledged,
            "timestamp": self.timestamp.isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AnomalyAlert:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# AnomalyLoginDetector Core (dengan entity dasar)
# ============================================================================
class AnomalyLoginDetector:
    """
    Detektor anomali login dengan multiple detection rules.
    """

    def __init__(
        self,
        max_failures_per_minute: int = 5,
        max_failures_per_hour: int = 20,
        max_failures_per_day: int = 50,
        max_success_per_minute: int = 10,
        known_ips: list[str] | None = None,
        known_user_agents: list[str] | None = None,
        known_devices: list[str] | None = None,
        enable_geo_fencing: bool = True,
        allowed_countries: list[str] | None = None,
        blacklisted_ips: list[str] | None = None,
        whitelisted_users: list[str] | None = None,
        velocity_window_seconds: int = 60,
        max_login_attempts_per_window: int = 20,
        enable_impossible_travel: bool = True,
        max_travel_speed_kmh: float = 900.0,
        tor_exit_node_list: list[str] | None = None,
        datacenter_ip_ranges: list[str] | None = None,
    ):
        self.max_failures_per_minute = max_failures_per_minute
        self.max_failures_per_hour = max_failures_per_hour
        self.max_failures_per_day = max_failures_per_day
        self.max_success_per_minute = max_success_per_minute
        self.velocity_window = velocity_window_seconds
        self.max_attempts_per_window = max_login_attempts_per_window
        self.enable_geo_fencing = enable_geo_fencing
        self.enable_impossible_travel = enable_impossible_travel
        self.max_travel_speed_kmh = max_travel_speed_kmh

        self.known_ips = set(known_ips or [])
        self.known_user_agents = set(known_user_agents or [])
        self.known_devices = set(known_devices or [])
        self.allowed_countries = set(allowed_countries or ["ID"])
        self.blacklisted_ips = set(blacklisted_ips or [])
        self.whitelisted_users = set(whitelisted_users or [])
        self.tor_exit_nodes = set(tor_exit_node_list or [])
        self.datacenter_ranges = datacenter_ip_ranges or []

        self._attempts: list[LoginAttempt] = []
        self._user_failures: dict[str, list[datetime]] = defaultdict(list)
        self._user_success: dict[str, list[datetime]] = defaultdict(list)
        self._user_locations: dict[str, list[tuple[datetime, str, float, float]]] = defaultdict(
            list
        )
        self._alerts: list[AnomalyAlert] = []
        self._lock = threading.RLock()
        self._geoip_reader: Any | None = None

        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

        if self.enable_geo_fencing and HAS_GEOIP:
            try:
                self._geoip_reader = geoip2.database.Reader("/usr/share/GeoIP/GeoLite2-City.mmdb")
            except Exception as e:
                logger.warning("GeoIP database not loaded: %s", e)

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "alerts_count": len(self._alerts),
                "attempts_count": len(self._attempts),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ------------------------------------------------------------------------
    # IP Geolocation
    # ------------------------------------------------------------------------
    def _get_location(self, ip: str) -> tuple[str | None, str | None, float | None, float | None]:
        if not self._geoip_reader:
            return None, None, None, None
        try:
            response = self._geoip_reader.city(ip)
            country = response.country.iso_code
            city = response.city.name
            lat = response.location.latitude
            lon = response.location.longitude
            return country, city, lat, lon
        except Exception:
            return None, None, None, None

    def _is_tor_exit_node(self, ip: str) -> bool:
        return ip in self.tor_exit_nodes

    def _is_datacenter_ip(self, ip: str) -> bool:
        return any(ip.startswith(prefix) for prefix in self.datacenter_ranges)

    # ------------------------------------------------------------------------
    # Attempt Recording
    # ------------------------------------------------------------------------
    def _clean_old_attempts(self):
        cutoff = datetime.now(UTC) - timedelta(days=1)
        with self._lock:
            self._attempts = [a for a in self._attempts if a.timestamp > cutoff]
            for user_id in list(self._user_failures.keys()):
                self._user_failures[user_id] = [
                    t for t in self._user_failures[user_id] if t > cutoff
                ]
            for user_id in list(self._user_success.keys()):
                self._user_success[user_id] = [t for t in self._user_success[user_id] if t > cutoff]
            for user_id in list(self._user_locations.keys()):
                self._user_locations[user_id] = [
                    loc for loc in self._user_locations[user_id] if loc[0] > cutoff
                ]

    def record_attempt(
        self,
        user_id: str,
        source_ip: str,
        user_agent: str,
        success: bool,
        device_fingerprint: str | None = None,
    ) -> None:
        country, city, lat, lon = self._get_location(source_ip)
        attempt = LoginAttempt(
            user_id=user_id,
            timestamp=datetime.now(UTC),
            source_ip=source_ip,
            user_agent=user_agent,
            success=success,
            country=country,
            city=city,
            device_fingerprint=device_fingerprint,
            lat=lat,
            lon=lon,
        )
        with self._lock:
            self._attempts.append(attempt)
            if success:
                self._user_success[user_id].append(attempt.timestamp)
                if lat and lon:
                    self._user_locations[user_id].append((attempt.timestamp, source_ip, lat, lon))
            else:
                self._user_failures[user_id].append(attempt.timestamp)
        self._clean_old_attempts()
        self._record_audit("RECORD_ATTEMPT", user_id, {"success": success, "ip": source_ip})

    # ------------------------------------------------------------------------
    # Detection Rules
    # ------------------------------------------------------------------------
    def _detect_brute_force(self, user_id: str) -> AnomalyAlert | None:
        now = datetime.now(UTC)
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)

        with self._lock:
            minute_failures = sum(1 for t in self._user_failures.get(user_id, []) if t > minute_ago)
            hour_failures = sum(1 for t in self._user_failures.get(user_id, []) if t > hour_ago)
            day_failures = sum(1 for t in self._user_failures.get(user_id, []) if t > day_ago)

        reason = None
        if minute_failures >= self.max_failures_per_minute:
            reason = f"{minute_failures} failures in last minute"
        elif hour_failures >= self.max_failures_per_hour:
            reason = f"{hour_failures} failures in last hour"
        elif day_failures >= self.max_failures_per_day:
            reason = f"{day_failures} failures in last 24 hours"

        if reason:
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=user_id,
                anomaly_type=AnomalyType.BRUTE_FORCE,
                severity=AnomalySeverity.CRITICAL
                if minute_failures >= self.max_failures_per_minute
                else AnomalySeverity.HIGH,
                description=f"Brute force detected: {reason}",
                timestamp=datetime.now(UTC),
                evidence={
                    "failure_counts": {
                        "minute": minute_failures,
                        "hour": hour_failures,
                        "day": day_failures,
                    }
                },
            )
        return None

    def _detect_high_velocity(self, user_id: str) -> AnomalyAlert | None:
        now = datetime.now(UTC)
        window_start = now - timedelta(seconds=self.velocity_window)
        with self._lock:
            total_attempts = sum(
                1 for a in self._attempts if a.user_id == user_id and a.timestamp > window_start
            )
        if total_attempts >= self.max_attempts_per_window:
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=user_id,
                anomaly_type=AnomalyType.HIGH_VELOCITY,
                severity=AnomalySeverity.HIGH,
                description=f"High login velocity: {total_attempts} attempts in {self.velocity_window}s",
                timestamp=datetime.now(UTC),
                evidence={"attempts": total_attempts, "window_seconds": self.velocity_window},
            )
        return None

    def _detect_unusual_location(self, attempt: LoginAttempt) -> AnomalyAlert | None:
        if not self.enable_geo_fencing or not attempt.country:
            return None
        if attempt.country not in self.allowed_countries:
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=attempt.user_id,
                anomaly_type=AnomalyType.UNUSUAL_LOCATION,
                severity=AnomalySeverity.MEDIUM,
                description=f"Login from unusual country: {attempt.country} (IP: {attempt.source_ip})",
                timestamp=datetime.now(UTC),
                evidence={"country": attempt.country, "ip": attempt.source_ip},
            )
        return None

    def _detect_unusual_device(self, attempt: LoginAttempt) -> AnomalyAlert | None:
        if self.known_user_agents and attempt.user_agent not in self.known_user_agents:
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=attempt.user_id,
                anomaly_type=AnomalyType.UNUSUAL_DEVICE,
                severity=AnomalySeverity.LOW,
                description=f"Login from unknown user agent: {attempt.user_agent[:50]}",
                timestamp=datetime.now(UTC),
                evidence={"user_agent": attempt.user_agent},
            )
        if (
            attempt.device_fingerprint
            and self.known_devices
            and attempt.device_fingerprint not in self.known_devices
        ):
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=attempt.user_id,
                anomaly_type=AnomalyType.UNUSUAL_DEVICE,
                severity=AnomalySeverity.MEDIUM,
                description="Login from unrecognized device",
                timestamp=datetime.now(UTC),
                evidence={"fingerprint": attempt.device_fingerprint},
            )
        return None

    def _detect_unusual_time(self, attempt: LoginAttempt) -> AnomalyAlert | None:
        hour = attempt.timestamp.hour
        if hour < 4 or hour > 22:
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=attempt.user_id,
                anomaly_type=AnomalyType.UNUSUAL_TIME,
                severity=AnomalySeverity.LOW,
                description=f"Login outside normal hours: {hour}:00",
                timestamp=datetime.now(UTC),
                evidence={"hour": hour},
            )
        return None

    def _detect_blacklisted_ip(self, attempt: LoginAttempt) -> AnomalyAlert | None:
        if attempt.source_ip in self.blacklisted_ips:
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=attempt.user_id,
                anomaly_type=AnomalyType.BLACKLISTED_IP,
                severity=AnomalySeverity.HIGH,
                description=f"Login from blacklisted IP: {attempt.source_ip}",
                timestamp=datetime.now(UTC),
                evidence={"ip": attempt.source_ip},
            )
        return None

    def _detect_tor_exit_node(self, attempt: LoginAttempt) -> AnomalyAlert | None:
        if self._is_tor_exit_node(attempt.source_ip):
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=attempt.user_id,
                anomaly_type=AnomalyType.TOR_EXIT_NODE,
                severity=AnomalySeverity.MEDIUM,
                description=f"Login from Tor exit node: {attempt.source_ip}",
                timestamp=datetime.now(UTC),
                evidence={"ip": attempt.source_ip},
            )
        return None

    def _detect_datacenter_ip(self, attempt: LoginAttempt) -> AnomalyAlert | None:
        if self._is_datacenter_ip(attempt.source_ip):
            return AnomalyAlert(
                alert_id=str(uuid4()),
                user_id=attempt.user_id,
                anomaly_type=AnomalyType.DATACENTER_IP,
                severity=AnomalySeverity.LOW,
                description=f"Login from datacenter IP: {attempt.source_ip}",
                timestamp=datetime.now(UTC),
                evidence={"ip": attempt.source_ip},
            )
        return None

    def _detect_impossible_travel(self, attempt: LoginAttempt) -> AnomalyAlert | None:
        if not self.enable_impossible_travel or attempt.lat is None:
            return None
        with self._lock:
            previous = self._user_locations.get(attempt.user_id, [])
        if len(previous) < 2:
            return None
        last = previous[-2]
        last_time, last_ip, last_lat, last_lon = last
        if last_lat is None or last_lon is None:
            return None
        time_diff = (attempt.timestamp - last_time).total_seconds() / 3600
        if time_diff < 0.5:
            from math import atan2, cos, radians, sin, sqrt

            R = 6371
            lat1, lon1 = radians(last_lat), radians(last_lon)
            lat2, lon2 = radians(attempt.lat), radians(attempt.lon)
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))
            distance = R * c
            speed = distance / time_diff if time_diff > 0 else float("inf")
            if speed > self.max_travel_speed_kmh:
                return AnomalyAlert(
                    alert_id=str(uuid4()),
                    user_id=attempt.user_id,
                    anomaly_type=AnomalyType.IMPOSSIBLE_TRAVEL,
                    severity=AnomalySeverity.CRITICAL,
                    description=f"Impossible travel detected: {distance:.0f} km in {time_diff:.1f} hours (speed {speed:.0f} km/h)",
                    timestamp=datetime.now(UTC),
                    evidence={
                        "distance_km": distance,
                        "time_hours": time_diff,
                        "speed_kmh": speed,
                        "from_ip": last_ip,
                        "to_ip": attempt.source_ip,
                    },
                )
        return None

    # ------------------------------------------------------------------------
    # Main Analysis
    # ------------------------------------------------------------------------
    def analyze_attempt(self, attempt: LoginAttempt, record: bool = True) -> list[AnomalyAlert]:
        if record:
            self.record_attempt(
                attempt.user_id,
                attempt.source_ip,
                attempt.user_agent,
                attempt.success,
                attempt.device_fingerprint,
            )
        alerts = []
        if attempt.user_id in self.whitelisted_users:
            return alerts
        if not attempt.success:
            brute = self._detect_brute_force(attempt.user_id)
            if brute:
                alerts.append(brute)
            velocity = self._detect_high_velocity(attempt.user_id)
            if velocity:
                alerts.append(velocity)
        loc = self._detect_unusual_location(attempt)
        if loc:
            alerts.append(loc)
        device = self._detect_unusual_device(attempt)
        if device:
            alerts.append(device)
        time_anom = self._detect_unusual_time(attempt)
        if time_anom:
            alerts.append(time_anom)
        black = self._detect_blacklisted_ip(attempt)
        if black:
            alerts.append(black)
        tor = self._detect_tor_exit_node(attempt)
        if tor:
            alerts.append(tor)
        dc = self._detect_datacenter_ip(attempt)
        if dc:
            alerts.append(dc)
        travel = self._detect_impossible_travel(attempt)
        if travel:
            alerts.append(travel)
        with self._lock:
            self._alerts.extend(alerts)
        self._record_audit("ANALYZE_ATTEMPT", attempt.user_id, {"alert_count": len(alerts)})
        return alerts

    def pre_login_check(self, user_id: str, source_ip: str, user_agent: str) -> AnomalyAlert | None:
        # Only brute force pre-check makes sense before actual login
        return self._detect_brute_force(user_id)

    def post_login_check(
        self, user_id: str, source_ip: str, user_agent: str, success: bool
    ) -> list[AnomalyAlert]:
        attempt = LoginAttempt(
            user_id=user_id,
            timestamp=datetime.now(UTC),
            source_ip=source_ip,
            user_agent=user_agent,
            success=success,
        )
        return self.analyze_attempt(attempt, record=True)

    # ------------------------------------------------------------------------
    # Alert Management
    # ------------------------------------------------------------------------
    def get_unacknowledged_alerts(self) -> list[AnomalyAlert]:
        with self._lock:
            return [a for a in self._alerts if not a.acknowledged]

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id and not alert.acknowledged:
                    alert.acknowledged = True
                    alert.acknowledged_by = acknowledged_by
                    self._record_audit("ACKNOWLEDGE_ALERT", acknowledged_by, {"alert_id": alert_id})
                    return True
        return False

    def get_alerts_for_user(self, user_id: str) -> list[AnomalyAlert]:
        with self._lock:
            return [a for a in self._alerts if a.user_id == user_id]

    # ------------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        with self._lock:
            total_alerts = len(self._alerts)
            unacknowledged = len(self.get_unacknowledged_alerts())
            by_type = defaultdict(int)
            for a in self._alerts:
                by_type[a.anomaly_type.value] += 1
            by_user = defaultdict(int)
            for a in self._alerts:
                by_user[a.user_id] += 1
            return {
                "total_alerts": total_alerts,
                "unacknowledged": unacknowledged,
                "by_anomaly_type": dict(by_type),
                "top_users": sorted(by_user.items(), key=lambda x: x[1], reverse=True)[:10],
                "recent_alerts": [a.to_dict() for a in self._alerts[-20:]],
                "version": self._version,
            }

    def export_to_json(self, file_path: str) -> None:
        data = self.generate_report()
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_attempts": len(self._attempts),
                "total_alerts": len(self._alerts),
                "unacknowledged_alerts": len(self.get_unacknowledged_alerts()),
                "unique_users": len({a.user_id for a in self._alerts}),
                "version": self._version,
            }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.max_failures_per_minute <= 0:
            errors.append("max_failures_per_minute must be positive")
        if self.max_failures_per_hour <= 0:
            errors.append("max_failures_per_hour must be positive")
        if self.max_failures_per_day <= 0:
            errors.append("max_failures_per_day must be positive")
        if self.velocity_window <= 0:
            errors.append("velocity_window_seconds must be positive")
        if self.max_attempts_per_window <= 0:
            errors.append("max_login_attempts_per_window must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_failures_per_minute": self.max_failures_per_minute,
            "max_failures_per_hour": self.max_failures_per_hour,
            "max_failures_per_day": self.max_failures_per_day,
            "max_success_per_minute": self.max_success_per_minute,
            "velocity_window_seconds": self.velocity_window,
            "max_attempts_per_window": self.max_attempts_per_window,
            "enable_geo_fencing": self.enable_geo_fencing,
            "enable_impossible_travel": self.enable_impossible_travel,
            "max_travel_speed_kmh": self.max_travel_speed_kmh,
            "allowed_countries": list(self.allowed_countries),
            "blacklisted_ips": list(self.blacklisted_ips),
            "whitelisted_users": list(self.whitelisted_users),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnomalyLoginDetector:
        instance = cls(
            max_failures_per_minute=data.get("max_failures_per_minute", 5),
            max_failures_per_hour=data.get("max_failures_per_hour", 20),
            max_failures_per_day=data.get("max_failures_per_day", 50),
            max_success_per_minute=data.get("max_success_per_minute", 10),
            known_ips=data.get("known_ips"),
            known_user_agents=data.get("known_user_agents"),
            known_devices=data.get("known_devices"),
            enable_geo_fencing=data.get("enable_geo_fencing", True),
            allowed_countries=data.get("allowed_countries"),
            blacklisted_ips=data.get("blacklisted_ips"),
            whitelisted_users=data.get("whitelisted_users"),
            velocity_window_seconds=data.get("velocity_window_seconds", 60),
            max_login_attempts_per_window=data.get("max_login_attempts_per_window", 20),
            enable_impossible_travel=data.get("enable_impossible_travel", True),
            max_travel_speed_kmh=data.get("max_travel_speed_kmh", 900.0),
            tor_exit_node_list=data.get("tor_exit_node_list"),
            datacenter_ip_ranges=data.get("datacenter_ip_ranges"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> AnomalyLoginDetector:
        new = AnomalyLoginDetector(
            max_failures_per_minute=self.max_failures_per_minute,
            max_failures_per_hour=self.max_failures_per_hour,
            max_failures_per_day=self.max_failures_per_day,
            max_success_per_minute=self.max_success_per_minute,
            known_ips=list(self.known_ips),
            known_user_agents=list(self.known_user_agents),
            known_devices=list(self.known_devices),
            enable_geo_fencing=self.enable_geo_fencing,
            allowed_countries=list(self.allowed_countries),
            blacklisted_ips=list(self.blacklisted_ips),
            whitelisted_users=list(self.whitelisted_users),
            velocity_window_seconds=self.velocity_window,
            max_login_attempts_per_window=self.max_attempts_per_window,
            enable_impossible_travel=self.enable_impossible_travel,
            max_travel_speed_kmh=self.max_travel_speed_kmh,
            tor_exit_node_list=list(self.tor_exit_nodes),
            datacenter_ip_ranges=self.datacenter_ranges.copy(),
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "total_alerts": len(self._alerts),
            "total_attempts": len(self._attempts),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AnomalyLoginDetector:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        with self._lock:
            self._attempts = []
            self._user_failures.clear()
            self._user_success.clear()
            self._user_locations.clear()
            self._alerts = []
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    detector = AnomalyLoginDetector(
        max_failures_per_minute=3,
        max_failures_per_hour=10,
        max_attempts_per_window=5,
        velocity_window_seconds=30,
        allowed_countries=["ID", "SG"],
        blacklisted_ips=["1.2.3.4"],
    )

    for _i in range(6):
        attempts = detector.post_login_check("alice", "192.168.1.1", "Mozilla/5.0", False)
        for a in attempts:
            print(f"Alert: {a.description} (severity: {a.severity.value})")

    attempts = detector.post_login_check("alice", "8.8.8.8", "Mozilla/5.0", True)
    for a in attempts:
        print(f"Alert: {a.description} (severity: {a.severity.value})")

    print("\nReport:")
    print(json.dumps(detector.generate_report(), indent=2))
    detector.export_to_json("anomaly_login_report.json")
