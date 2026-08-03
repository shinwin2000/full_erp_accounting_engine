#!/usr/bin/env python3
"""
Runtime Verification Checker - Ultimate Enterprise Edition v4.8 (Production Grade)
==================================================================================
Perbaikan berdasarkan audit v4.7:
- Resolver $ref dengan cache dan deteksi circular reference
- Generator payload adaptif: dukung minItems, oneOf, anyOf, enum, example, nested, ambil entity valid
- Endpoint discovery rekursif untuk include_router bertingkat
- Scanner AST lebih baik: tangkap await, async with, return await
- BusinessRuleLoader dukung oneOf, anyOf, not, if-then-else
- Race checker gunakan payload generator yang valid
- Business flow cleanup dukung POST cancel, reverse, archive
- Rollback checker bandingkan set id bukan count
- Token refresh dengan asyncio.Event untuk efisiensi
- Health check configurable dengan fallback
- HTML report lazy loading untuk response body panjang
- Data integrity ignore list configurable
- Database consistency pagination scan atau sampling acak
- Entity ensure filter status aktif
- Path regex dukung {path:path}
- CLI tambahan email, password, health path
"""

import ast
import asyncio
import csv
import hashlib
import html as html_module
import io
import json
import logging
import os
import re
import sys
import time
import traceback
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp

try:
    from checker.core.rca import RootCauseAnalyzer
except ImportError:
    RootCauseAnalyzer = None

# ============================================
# Simple LRU Cache
# ============================================
class LRUCache:
    def __init__(self, max_size=1000):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

# ============================================
# Rate Limiter
# ============================================
class RateLimiter:
    def __init__(self, rate_per_second: float):
        self.rate = rate_per_second
        self.tokens = rate_per_second
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        if self.rate <= 0:
            return
        async with self.lock:
            now = time.monotonic()
            elapsed = min(now - self.last_update, 1.0)
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_update = now
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                now = time.monotonic()
                elapsed = min(now - self.last_update, 1.0)
                self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
                self.last_update = now
                self.tokens -= 1
            else:
                self.tokens -= 1

# ============================================
# Configuration
# ============================================
@dataclass
class CheckerConfig:
    BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")
    FRONTEND_PATH: str = os.getenv("FRONTEND_PATH", "./erp_frontend")
    BACKEND_SOURCE_PATH: str = os.getenv("BACKEND_SOURCE_PATH", "")

    LOGIN_ENDPOINT: str = "/api/v1/auth/login"
    LOGIN_CREDENTIALS: dict = field(default_factory=dict)

    MAX_CONCURRENT: int = int(os.getenv("MAX_CONCURRENT", "10"))
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY: float = float(os.getenv("RETRY_DELAY", "2.0"))
    RETRY_BACKOFF_MULTIPLIER: float = float(os.getenv("RETRY_BACKOFF", "2.0"))
    RATE_LIMIT_RPS: float = float(os.getenv("RATE_LIMIT_RPS", "0"))

    SCAN_PYSIDE6: bool = os.getenv("SCAN_PYSIDE6", "true").lower() == "true"
    PYSIDE6_FILE_PATTERNS: list[str] = field(default_factory=lambda: ["*.py", "*.pyw", "*.ui"])
    PYSIDE6_EXCLUDE_DIRS: list[str] = field(default_factory=lambda: [
        "__pycache__", ".git", "venv", "env", "node_modules", "dist", "build"
    ])

    ENABLE_SYNC_DETECTION: bool = os.getenv("ENABLE_SYNC_DETECTION", "true").lower() == "true"
    ENABLE_DATA_INTEGRITY: bool = os.getenv("ENABLE_DATA_INTEGRITY", "true").lower() == "true"
    ENABLE_BUSINESS_LOGIC: bool = os.getenv("ENABLE_BUSINESS_LOGIC", "true").lower() == "true"
    ENABLE_GUI_ANALYSIS: bool = os.getenv("ENABLE_GUI_ANALYSIS", "true").lower() == "true"
    ENABLE_BUSINESS_FLOWS: bool = os.getenv("ENABLE_BUSINESS_FLOWS", "true").lower() == "true"
    ENABLE_RACE_CONDITION: bool = os.getenv("ENABLE_RACE_CONDITION", "true").lower() == "true"
    ENABLE_TRANSACTION_ROLLBACK: bool = os.getenv("ENABLE_TRANSACTION_ROLLBACK", "true").lower() == "true"
    ENABLE_DB_CONSISTENCY: bool = os.getenv("ENABLE_DB_CONSISTENCY", "true").lower() == "true"
    ENABLE_KAFKA_CHECK: bool = os.getenv("ENABLE_KAFKA_CHECK", "false").lower() == "true"
    ENABLE_REDIS_CHECK: bool = os.getenv("ENABLE_REDIS_CHECK", "false").lower() == "true"
    ENABLE_CELERY_CHECK: bool = os.getenv("ENABLE_CELERY_CHECK", "false").lower() == "true"
    ENABLE_SCHEDULER_CHECK: bool = os.getenv("ENABLE_SCHEDULER_CHECK", "false").lower() == "true"
    ENABLE_RUNTIME_EXCEPTION_COLLECTOR: bool = os.getenv("ENABLE_RUNTIME_EXCEPTION_COLLECTOR", "true").lower() == "true"
    ENABLE_N1_DETECTOR: bool = os.getenv("ENABLE_N1_DETECTOR", "true").lower() == "true"
    ENABLE_LEAK_DETECTION: bool = os.getenv("ENABLE_LEAK_DETECTION", "false").lower() == "true"
    PROCESS_DEBUG_ENDPOINT: str = os.getenv("PROCESS_DEBUG_ENDPOINT", "/debug/process")
    HEALTH_ENDPOINT: str = os.getenv("HEALTH_ENDPOINT", "/health")

    KAFKA_MONITOR_ENDPOINT: str = os.getenv("KAFKA_MONITOR_ENDPOINT", "")
    REDIS_MONITOR_ENDPOINT: str = os.getenv("REDIS_MONITOR_ENDPOINT", "")
    CELERY_MONITOR_ENDPOINT: str = os.getenv("CELERY_MONITOR_ENDPOINT", "")
    SCHEDULER_MONITOR_ENDPOINT: str = os.getenv("SCHEDULER_MONITOR_ENDPOINT", "")

    BUSINESS_FLOWS_JSON: str | None = None
    DB_CONSISTENCY_RELATIONS: str | None = None

    OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", "checker_reports")).resolve()

    EXCLUDE_PATHS: list[str] = field(default_factory=lambda: [
        "/docs", "/redoc", "/openapi.json", "/health", "/metrics",
        "/favicon.ico", "/static", "/assets"
    ])

    BUSINESS_RULES: dict[str, dict] = field(default_factory=lambda: {
        "default": {
            "invoice_total": {"min": 0, "max": 1000000000},
            "quantity": {"min": 0, "max": 999999},
            "price": {"min": 0, "max": 999999999},
            "discount": {"min": 0, "max": 100},
            "tax_rate": {"min": 0, "max": 100},
            "salary": {"min": 0, "max": 99999999}
        }
    })

    # Data integrity ignore fields: tambahkan field yang sering berubah otomatis
    DATA_INTEGRITY_IGNORE_FIELDS: list[str] = field(default_factory=lambda: [
        "timestamp", "created_at", "updated_at", "etag", "version", "revision",
        "last_login", "sync_token", "last_modified", "lock_version", "row_version",
        "sequence_number", "document_no", "posting_no", "running_no", "change_log"
    ])

    def __post_init__(self):
        # Credentials bisa dari env atau argumen CLI (akan di set oleh checker)
        if not self.LOGIN_CREDENTIALS:
            email = os.getenv("TEST_EMAIL")
            password = os.getenv("TEST_PASSWORD")
            if email and password:
                self.LOGIN_CREDENTIALS = {"email": email, "password": password}
            else:
                raise ValueError("TEST_EMAIL and TEST_PASSWORD must be set or pass via CLI.")
        if self.SCAN_PYSIDE6 and not Path(self.FRONTEND_PATH).exists():
            logging.warning(f"Frontend path not found: {self.FRONTEND_PATH}")
            self.SCAN_PYSIDE6 = False

    @property
    def business_flows(self) -> list[dict]:
        if self.BUSINESS_FLOWS_JSON:
            try:
                return json.loads(self.BUSINESS_FLOWS_JSON)
            except:
                pass
        return [
            {
                "name": "Create Invoice → Approve → Posting",
                "steps": [
                    {"method": "POST", "path": "/api/v1/invoices", "body": {"customer_id": "$customer_id", "items": [{"product_id": "$product_id", "quantity": 5, "price": 1000}]}, "save": "invoice"},
                    {"method": "POST", "path": "/api/v1/approvals", "body": {"document_type": "invoice", "document_id": "$invoice.id", "action": "approve"}, "save": "approval"},
                    {"method": "POST", "path": "/api/v1/journal-entries/posting", "body": {"document_type": "invoice", "document_id": "$invoice.id"}, "save": "journal"}
                ],
                "cleanup": [
                    {"method": "POST", "path": "/api/v1/journal-entries/$journal.id/cancel"},
                    {"method": "DELETE", "path": "/api/v1/approvals/$approval.id"},
                    {"method": "DELETE", "path": "/api/v1/invoices/$invoice.id"},
                ]
            }
        ]

    @property
    def race_concurrency_levels(self) -> list[int]:
        levels = os.getenv("RACE_CONCURRENCY_LEVELS", "10,25,50")
        try:
            return [int(x) for x in levels.split(",") if x.isdigit()]
        except:
            return [10]

# ============================================
# Data Models (tetap sama)
# ============================================
@dataclass
class PySide6ApiCall:
    file_path: str; line_number: int; function_name: str; class_name: str
    url: str; method: str; params: dict | None = None; body: dict | None = None
    headers: dict | None = None; response_handler: str | None = None
    error_handler: str | None = None; is_async: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    def to_dict(self): return asdict(self)

@dataclass
class SyncIssue:
    issue_type: str; frontend_file: str; frontend_line: int
    api_call: PySide6ApiCall; backend_endpoint: dict | None = None
    expected_method: str | None = None; actual_method: str | None = None
    severity: str = "HIGH"; description: str = ""; root_cause: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    def to_dict(self):
        d = asdict(self); d['api_call'] = self.api_call.to_dict(); return d

@dataclass
class GuiFlowIssue:
    issue_type: str; file_path: str; line_number: int; widget_name: str
    signal_name: str; slot_name: str; description: str
    severity: str = "INFO"
    root_cause: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    def to_dict(self): return asdict(self)

@dataclass
class BusinessRuleViolation:
    rule_name: str; endpoint: str; field: str; value: Any
    expected_range: Any; description: str; severity: str = "HIGH"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

@dataclass
class TestResult:
    endpoint: str; method: str; status_code: int; success: bool; duration_ms: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    error_type: str | None = None; error_message: str | None = None
    traceback: str | None = None; file: str | None = None; line: int | None = None
    function: str | None = None; root_cause: str | None = None
    error_category: str | None = None; severity: str | None = None
    request_body: dict | None = None; response_body: dict | None = None
    request_headers: dict | None = None; response_headers: dict | None = None
    dependency_errors: list[str] = field(default_factory=list)
    retry_count: int = 0
    api_calls: list[PySide6ApiCall] = field(default_factory=list)
    sync_issues: list[SyncIssue] = field(default_factory=list)
    gui_issues: list[GuiFlowIssue] = field(default_factory=list)
    business_violations: list[BusinessRuleViolation] = field(default_factory=list)
    data_hash: str | None = None; data_integrity_ok: bool = True
    runtime_exception: str | None = None; runtime_file: str | None = None
    runtime_line: int | None = None; runtime_function: str | None = None
    n1_detected: bool = False; n1_query_count: int | None = None

    def to_dict(self):
        data = asdict(self)
        data['api_calls'] = [c.to_dict() for c in self.api_calls]
        data['sync_issues'] = [i.to_dict() for i in self.sync_issues]
        data['gui_issues'] = [i.to_dict() for i in self.gui_issues]
        data['business_violations'] = [asdict(i) for i in self.business_violations]
        return data

    def to_csv_row(self):
        return {
            "endpoint": self.endpoint,
            "method": self.method,
            "status": self.status_code,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "error_type": self.error_type or "",
            "error_category": self.error_category or "",
            "severity": self.severity or "",
            "file": self.file or "",
            "line": self.line or "",
            "function": self.function or "",
            "root_cause": self.root_cause or "",
            "retry_count": self.retry_count,
            "api_calls_found": len(self.api_calls),
            "sync_issues": len(self.sync_issues),
            "gui_issues": len(self.gui_issues),
            "business_violations": len(self.business_violations),
            "data_integrity": self.data_integrity_ok,
            "runtime_exception": self.runtime_exception or "",
            "n1_detected": self.n1_detected,
            "timestamp": self.timestamp
        }

@dataclass
class BusinessFlowResult:
    flow_name: str; success: bool; steps_executed: int; total_steps: int
    error_step: int | None = None; error_message: str | None = None
    duration_ms: float = 0.0; context: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

@dataclass
class RaceConditionResult:
    endpoint: str; method: str; concurrent_requests: int
    success_count: int; failure_count: int
    duplicate_errors: bool; deadlock_errors: bool
    avg_response_ms: float; max_response_ms: float
    inconsistencies: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

@dataclass
class HealthReport:
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    total_endpoints: int = 0; tested_endpoints: int = 0
    successful: int = 0; failed: int = 0; retried: int = 0
    status_codes: dict[int, int] = field(default_factory=dict)
    error_categories: dict[str, int] = field(default_factory=dict)
    total_api_calls_found: int = 0
    sync_issues: list[SyncIssue] = field(default_factory=list); sync_issues_count: int = 0
    gui_issues: list[GuiFlowIssue] = field(default_factory=list); gui_issues_count: int = 0
    business_violations: list[BusinessRuleViolation] = field(default_factory=list)
    business_violations_count: int = 0
    endpoints_used_by_frontend: set[str] = field(default_factory=set)
    endpoints_not_used: set[str] = field(default_factory=set)
    frontend_calls_to_missing_endpoints: list[PySide6ApiCall] = field(default_factory=list)
    data_integrity_errors: int = 0
    critical_modules: list[str] = field(default_factory=list)
    results: list[TestResult] = field(default_factory=list)
    avg_duration_ms: float = 0.0; max_duration_ms: float = 0.0; min_duration_ms: float = 0.0; p95_duration_ms: float = 0.0
    backend_score: float = 0.0; sync_score: float = 100.0; gui_score: float = 100.0
    coverage_score: float = 100.0; overall_score: float = 0.0
    business_flows: list[BusinessFlowResult] = field(default_factory=list)
    race_condition_results: list[RaceConditionResult] = field(default_factory=list)
    transaction_rollback_results: list[dict] = field(default_factory=list)
    db_consistency_issues: list[str] = field(default_factory=list)
    kafka_status: dict | None = None; redis_status: dict | None = None
    celery_status: dict | None = None; scheduler_status: dict | None = None
    runtime_exception_count: int = 0; n1_detected_count: int = 0
    memory_leak_detected: bool = False; thread_leak_detected: bool = False

    def calculate_statistics(self, critical_endpoints: set[str] = None):
        if not critical_endpoints:
            critical_endpoints = set()
        if self.results:
            durations = [r.duration_ms for r in self.results if r.duration_ms > 0]
            if durations:
                self.avg_duration_ms = sum(durations) / len(durations)
                self.max_duration_ms = max(durations)
                self.min_duration_ms = min(durations)
                s = sorted(durations)
                self.p95_duration_ms = s[min(int(len(s)*0.95), len(s)-1)]
        critical_fail = sum(1 for r in self.results if not r.success and r.endpoint in critical_endpoints)
        success_rate = self.successful / self.tested_endpoints if self.tested_endpoints else 0
        self.backend_score = max(0, min(100, success_rate*100 - len(self.error_categories)*2 - critical_fail*5))
        self.sync_score = max(0, 100 - self.sync_issues_count*3)
        self.gui_score = max(0, 100 - self.gui_issues_count*0.5)
        total = len(self.endpoints_used_by_frontend) + len(self.endpoints_not_used)
        self.coverage_score = (len(self.endpoints_used_by_frontend)/total*100) if total else 0
        flow_fail = sum(1 for f in self.business_flows if not f.success)
        race_fail = sum(1 for r in self.race_condition_results if r.failure_count>0)
        flow_score = max(0, 100 - flow_fail*15)
        race_score = max(0, 100 - race_fail*10)
        self.overall_score = (self.backend_score*0.4 + self.sync_score*0.2 + self.gui_score*0.1 +
                              self.coverage_score*0.1 + flow_score*0.1 + race_score*0.1)

# ============================================
# Error Analyzer (tambahan untuk token refresh)
# ============================================
class ErrorAnalyzer:
    def __init__(self):
        self.rca = RootCauseAnalyzer() if RootCauseAnalyzer else None

    def classify_error(self, error: Exception, status_code: int = 0, context: str = "") -> str:
        error_str = str(error).lower()
        error_type = error.__class__.__name__

        status_map = {
            500: "HTTP_500_INTERNAL_ERROR", 502: "HTTP_502_BAD_GATEWAY",
            503: "HTTP_503_SERVICE_UNAVAILABLE", 504: "HTTP_504_GATEWAY_TIMEOUT",
            401: "HTTP_401_UNAUTHORIZED", 403: "HTTP_403_FORBIDDEN",
            422: "HTTP_422_VALIDATION_ERROR", 404: "HTTP_404_NOT_FOUND",
            409: "HTTP_409_CONFLICT", 429: "HTTP_429_RATE_LIMITED",
            400: "HTTP_400_BAD_REQUEST", 408: "HTTP_408_REQUEST_TIMEOUT",
            501: "HTTP_501_NOT_IMPLEMENTED", 505: "HTTP_505_VERSION_NOT_SUPPORTED"
        }
        if status_code in status_map:
            return status_map[status_code]

        if "CancelledError" in error_type:
            return "ASYNCIO_CANCELLED"
        if "Timeout" in error_type or "timeout" in error_str:
            return "TIMEOUT_ERROR"
        if "ConnectionError" in error_type or "ConnectionRefused" in error_type:
            return "NETWORK_CONNECTION_ERROR"
        if "ServerDisconnectedError" in error_type:
            return "NETWORK_CONNECTION_ERROR"
        if "ClientOSError" in error_type:
            return "NETWORK_CONNECTION_ERROR"
        if "ConnectionResetError" in error_type:
            return "NETWORK_CONNECTION_ERROR"
        if "SSL" in error_type or "ssl" in error_str:
            return "SSL_ERROR"
        if "DNS" in error_type or "getaddrinfo" in error_str:
            return "DNS_ERROR"
        if "HTTP" in error_type and "2" in error_str:
            return "HTTP2_ERROR"
        if "JSONDecodeError" in error_type:
            return "JSON_DECODE_ERROR"
        if "Unicode" in error_type:
            return "UNICODE_ERROR"
        if "MemoryError" in error_type:
            return "MEMORY_ERROR"
        if "RecursionError" in error_type:
            return "RECURSION_ERROR"
        if "BrokenPipeError" in error_type:
            return "BROKEN_PIPE_ERROR"
        if "FileNotFound" in error_type:
            return "FILE_NOT_FOUND"
        if "Permission" in error_type:
            return "PERMISSION_ERROR"
        if "IntegrityError" in error_type:
            return "SQL_INTEGRITY_ERROR"
        if "OperationalError" in error_type:
            return "SQL_OPERATIONAL_ERROR"
        if "ProgrammingError" in error_type:
            return "SQL_PROGRAMMING_ERROR"
        if "sqlalchemy" in error_str or "psycopg" in error_str:
            return "SQL_DATABASE_ERROR"
        if "redis" in error_str or "RedisError" in error_type:
            return "REDIS_ERROR"
        if "kafka" in error_str or "KafkaError" in error_type:
            return "KAFKA_ERROR"
        if "minio" in error_str or "S3Error" in error_type:
            return "MINIO_ERROR"
        if "ValidationError" in error_type or "pydantic" in error_type.lower():
            return "VALIDATION_ERROR"
        if "DependencyNotFound" in error_type or "Container" in error_type or "injection" in error_str:
            return "DEPENDENCY_ERROR"
        if "QWidget" in error_type or "QApplication" in error_type:
            return "GUI_ERROR"
        if "KeyError" in error_type:
            return "PYTHON_KEY_ERROR"
        if "ValueError" in error_type:
            return "PYTHON_VALUE_ERROR"
        if "TypeError" in error_type:
            return "PYTHON_TYPE_ERROR"
        if "AttributeError" in error_type:
            return "PYTHON_ATTRIBUTE_ERROR"
        if "IndexError" in error_type:
            return "PYTHON_INDEX_ERROR"
        if "RuntimeError" in error_type:
            return "PYTHON_RUNTIME_ERROR"
        if "NameError" in error_type:
            return "PYTHON_NAME_ERROR"
        if "OSError" in error_type:
            return "SYSTEM_OS_ERROR"
        return "UNKNOWN_ERROR"

    def is_transient(self, result: 'TestResult') -> bool:
        if result.status_code in [408, 502, 503, 504]:
            return True
        if "TIMEOUT" in (result.error_category or ""):
            return True
        if "NETWORK_CONNECTION" in (result.error_category or ""):
            return True
        if result.error_type and any(t in result.error_type for t in [
            "Timeout", "ServerDisconnected", "ClientOSError", "ConnectionReset"
        ]):
            return True
        return False

    def extract_traceback_info(self, tb_text: str) -> tuple[str | None, int | None, str | None]:
        if not tb_text:
            return None, None, None
        frames = re.findall(r'File "([^"]+)", line (\d+), in (\w+)', tb_text)
        if frames:
            for file_path, line_no, func_name in reversed(frames):
                if "site-packages" not in file_path and "lib/python" not in file_path:
                    return file_path, int(line_no), func_name
            file_path, line_no, func_name = frames[-1]
            return file_path, int(line_no), func_name
        return None, None, None

    def extract_root_cause(self, tb_text: str, error_msg: str) -> str:
        if self.rca:
            return self.rca.extract_root_cause(tb_text, error_msg)
        if tb_text:
            for line in reversed(tb_text.strip().split("\n")):
                if "Error:" in line or "Exception:" in line:
                    return line.strip()
        return error_msg[:500] if error_msg else "Unknown"

    def parse_runtime_exception_from_body(self, body: dict) -> dict | None:
        if not isinstance(body, dict):
            return None
        detail = body.get("detail")
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                msg = first.get("msg", "")
                if "Error" in msg or "Exception" in msg:
                    return {"exception": msg, "file": None, "line": None, "function": None, "traceback": str(detail)}
        if "title" in body and "status" in body:
            return {"exception": body.get("title"), "file": body.get("file"), "line": body.get("line"), "function": body.get("function"), "traceback": body.get("detail")}
        for key in ["exception", "error_type", "error", "type", "exc_type"]:
            exc = body.get(key)
            if exc:
                return {
                    "exception": exc,
                    "file": body.get("file") or body.get("filename"),
                    "line": body.get("line") or body.get("lineno"),
                    "function": body.get("function") or body.get("func"),
                    "traceback": body.get("traceback") or body.get("stack") or body.get("trace")
                }
        if isinstance(detail, str):
            m = re.search(r"([A-Za-z]+Error).+File \"([^\"]+)\", line (\d+), in (\w+)", detail)
            if m:
                return {"exception": m.group(1), "file": m.group(2), "line": int(m.group(3)), "function": m.group(4), "traceback": detail}
        return None

    def detect_n1(self, response_body, response_headers) -> tuple[bool, int | None]:
        if response_headers and "X-Query-Count" in response_headers:
            cnt = int(response_headers["X-Query-Count"])
            if isinstance(response_body, list) and cnt > len(response_body) * 2:
                return True, cnt
        if response_headers and "X-N1-Warning" in response_headers:
            return True, None
        return False, None

    def check_memory_leak(self, before, after):
        if not before or not after:
            return False
        rss_before = before.get("rss", 0)
        rss_after = after.get("rss", 0)
        return rss_before > 0 and rss_after > rss_before * 1.1 and (rss_after - rss_before) > 10*1024*1024

    def check_thread_leak(self, before, after):
        if not before or not after:
            return False
        tb = before.get("threads", 0)
        ta = after.get("threads", 0)
        return ta > tb + 5

    def get_severity(self, category, status_code=0):
        if status_code == 500: return "CRITICAL"
        if status_code in [502, 503, 504]: return "HIGH"
        if status_code == 401: return "LOW"
        if status_code == 403: return "MEDIUM"
        if status_code == 429: return "MEDIUM"
        if "DEPENDENCY" in category or "SQL_DATABASE" in category: return "CRITICAL"
        if "REDIS" in category or "KAFKA" in category: return "HIGH"
        return "MEDIUM"

    def parse_dependency_error(self, msg):
        if not msg: return []
        deps = []
        for pat in [r'([A-Za-z]+Service)', r'([A-Za-z]+Repository)', r'([A-Za-z]+Manager)', r'([A-Za-z]+Client)']:
            deps.extend(re.findall(pat, msg))
        return list(set(deps))[:10]

    def compute_data_hash(self, data: dict, exclude_keys: list[str] = None) -> str:
        if not data:
            return ""
        if exclude_keys is None:
            exclude_keys = ["timestamp", "created_at", "updated_at", "etag", "version", "revision",
                            "last_login", "sync_token", "last_modified", "lock_version", "row_version"]
        clean = {k: v for k, v in data.items() if k not in exclude_keys}
        try:
            return hashlib.sha256(json.dumps(clean, sort_keys=True, default=str).encode()).hexdigest()
        except:
            return ""

# ============================================
# OpenAPI Utility: resolver with cache and circular detection
# ============================================
class OpenAPIResolver:
    def __init__(self, spec):
        self.spec = spec
        self.cache = {}
        self.visited = set()

    def resolve(self, obj):
        return self._resolve(obj, self.spec)

    def _resolve(self, obj, root):
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref = obj["$ref"]
                if ref in self.visited:
                    # circular reference, return empty dict to avoid recursion
                    return {}
                self.visited.add(ref)
                if ref in self.cache:
                    self.visited.remove(ref)
                    return self.cache[ref]
                parts = ref.split("/")
                cur = root
                for part in parts:
                    if part == "#": continue
                    cur = cur.get(part, {})
                resolved = self._resolve(cur, root)
                self.cache[ref] = resolved
                self.visited.remove(ref)
                return resolved
            return {k: self._resolve(v, root) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve(v, root) for v in obj]
        return obj

# ============================================
# Enhanced BusinessRuleLoader: dukung oneOf, anyOf, if-then-else
# ============================================
class BusinessRuleLoader:
    def __init__(self, config, spec=None):
        self.config = config
        self.rules = config.BUSINESS_RULES.copy()
        self.spec = spec
        self.resolver = OpenAPIResolver(spec) if spec else None

    async def load_from_openapi(self, session):
        if not self.spec:
            try:
                async with session.get(f"{self.config.BASE_URL}/openapi.json") as resp:
                    if resp.status == 200:
                        self.spec = await resp.json()
                        self.resolver = OpenAPIResolver(self.spec)
            except: pass
        if self.spec:
            self._extract_rules_from_schema()

    def _extract_rules_from_schema(self):
        if not self.spec:
            return
        spec = self.resolver.resolve(self.spec) if self.resolver else self.spec
        for path, methods in spec.get("paths", {}).items():
            for method, det in methods.items():
                if method.lower() not in ["post", "put", "patch"]:
                    continue
                request_body = det.get("requestBody", {})
                for content_type in ["application/json", "multipart/form-data", "application/x-www-form-urlencoded"]:
                    content = request_body.get("content", {}).get(content_type, {})
                    schema = content.get("schema", {})
                    if not schema:
                        continue
                    # resolve allOf, oneOf, anyOf
                    merged_props = self._merge_schema_properties(schema)
                    if merged_props:
                        rules_for_path = self.rules.setdefault(path, {})
                        for prop_name, prop in merged_props.items():
                            rule = {}
                            if "minimum" in prop: rule["min"] = prop["minimum"]
                            if "maximum" in prop: rule["max"] = prop["maximum"]
                            if "enum" in prop: rule["enum"] = prop["enum"]
                            if "minLength" in prop: rule["minLength"] = prop["minLength"]
                            if "maxLength" in prop: rule["maxLength"] = prop["maxLength"]
                            if "pattern" in prop: rule["pattern"] = prop["pattern"]
                            if "format" in prop: rule["format"] = prop["format"]
                            if "minItems" in prop: rule["minItems"] = prop["minItems"]
                            if "maxItems" in prop: rule["maxItems"] = prop["maxItems"]
                            if "uniqueItems" in prop: rule["uniqueItems"] = prop["uniqueItems"]
                            if rule: rules_for_path[prop_name] = rule
        # merge hardcoded
        for path, rules in self.config.BUSINESS_RULES.items():
            if path not in self.rules:
                self.rules[path] = rules
            else:
                self.rules[path].update(rules)

    def _merge_schema_properties(self, schema):
        """Resolve allOf, oneOf, anyOf, if-then-else (sederhana)"""
        if "allOf" in schema:
            merged = {}
            for sub in schema["allOf"]:
                sub_props = self._merge_schema_properties(sub)
                merged.update(sub_props)
            return merged
        if "oneOf" in schema or "anyOf" in schema:
            # Ambil gabungan dari semua opsi (union)
            combined = {}
            options = schema.get("oneOf", []) or schema.get("anyOf", [])
            for opt in options:
                opt_props = self._merge_schema_properties(opt)
                combined.update(opt_props)
            return combined
        if "if" in schema and "then" in schema:
            # ambil properti dari then saja (kondisi diabaikan untuk rule)
            return self._merge_schema_properties(schema["then"])
        if "properties" in schema:
            return schema["properties"]
        return {}

# ============================================
# Enhanced Payload Generator (adaptif, ambil entity valid)
# ============================================
class PayloadGenerator:
    def __init__(self, executor, session, spec):
        self.executor = executor
        self.session = session
        self.spec = spec
        self.resolver = OpenAPIResolver(spec) if spec else None
        self.entity_cache = {}  # path -> list of ids

    async def generate(self, path, method):
        """Generate valid request body berdasarkan OpenAPI schema."""
        if not self.spec:
            return {}
        spec = self.resolver.resolve(self.spec) if self.resolver else self.spec
        paths = spec.get("paths", {})
        endpoint_spec = paths.get(path)
        if not endpoint_spec:
            return {}
        method_spec = endpoint_spec.get(method.lower())
        if not method_spec:
            return {}
        request_body = method_spec.get("requestBody", {})
        content = request_body.get("content", {}).get("application/json", {})
        schema = content.get("schema", {})
        if not schema:
            return {}
        # resolve allOf, oneOf, anyOf
        merged_props = self._merge_schema(schema)
        required = schema.get("required", [])
        # Generate berdasarkan properti
        body = {}
        for prop_name, prop in merged_props.items():
            body[prop_name] = await self._generate_value(prop, prop_name, required)
        # Pastikan required fields ada
        for req in required:
            if req not in body:
                body[req] = await self._generate_value(merged_props.get(req, {}), req, required)
        return body

    def _merge_schema(self, schema):
        merged = {}
        if "allOf" in schema:
            for sub in schema["allOf"]:
                sub_merged = self._merge_schema(sub)
                merged.update(sub_merged)
            return merged
        if "oneOf" in schema or "anyOf" in schema:
            options = schema.get("oneOf", []) or schema.get("anyOf", [])
            for opt in options:
                opt_merged = self._merge_schema(opt)
                merged.update(opt_merged)
            return merged
        if "if" in schema and "then" in schema:
            return self._merge_schema(schema["then"])
        if "properties" in schema:
            return schema["properties"]
        return merged

    async def _generate_value(self, prop, name, required_fields):
        # Jika ada example, gunakan
        if "example" in prop:
            return prop["example"]
        if "default" in prop:
            return prop["default"]
        prop_type = prop.get("type", "string")
        # Jika ini adalah foreign key (nama berakhir _id atau _ids), coba ambil dari entity
        if name.endswith("_id") and prop_type == "integer":
            entity_path = f"/api/v1/{name[:-3]}s"  # misal customer_id -> /api/v1/customers
            # coba ambil id yang valid
            valid_id = await self._get_valid_entity_id(entity_path)
            if valid_id:
                return valid_id
            return 1  # fallback
        # Array
        if prop_type == "array":
            items = prop.get("items", {})
            min_items = prop.get("minItems", 0)
            max_items = prop.get("maxItems", 10)
            count = min_items if min_items > 0 else (max_items if max_items < 10 else 1)
            arr = []
            for _ in range(count):
                arr.append(await self._generate_value(items, name+"_item", []))
            return arr
        if prop_type == "object":
            # generate nested
            nested = {}
            for sub_name, sub_prop in prop.get("properties", {}).items():
                nested[sub_name] = await self._generate_value(sub_prop, sub_name, [])
            return nested
        if prop_type == "integer":
            return prop.get("minimum", 1)
        if prop_type == "number":
            return prop.get("minimum", 1.0)
        if prop_type == "boolean":
            return True
        if prop_type == "string":
            if "format" in prop:
                if prop["format"] == "email":
                    return "test@example.com"
                if prop["format"] == "date":
                    return "2023-01-01"
                if prop["format"] == "uri":
                    return "http://example.com"
                if prop["format"] == "uuid":
                    return str(uuid.uuid4())
            if "enum" in prop:
                return prop["enum"][0]
            if "pattern" in prop:
                # coba generate sederhana
                return "test_value"
            return "test"
        return None

    async def _get_valid_entity_id(self, entity_path):
        if self.entity_cache.get(entity_path):
            return self.entity_cache[entity_path][0]
        headers = self.executor._auth_headers()
        try:
            # coba get dengan filter limit 5
            url = f"{self.executor.base_url}{entity_path}?limit=5&status=active"
            async with self.session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        ids = [item.get("id") for item in data if item.get("id")]
                    elif isinstance(data, dict):
                        items = data.get("items", [])
                        ids = [item.get("id") for item in items if item.get("id")]
                    else:
                        ids = []
                    if ids:
                        self.entity_cache[entity_path] = ids
                        return ids[0]
        except: pass
        return None

# ============================================
# Enhanced Endpoint Discovery (rekursif include_router)
# ============================================
class EnhancedEndpointDiscovery:
    def __init__(self, base_url, config):
        self.base_url = base_url.rstrip("/")
        self.config = config
        self.endpoints = []
        self.auth_required_paths = set()

    async def discover(self, session):
        try:
            async with session.get(f"{self.base_url}/openapi.json", timeout=aiohttp.ClientTimeout(10)) as resp:
                if resp.status == 200:
                    spec = await resp.json()
                    resolver = OpenAPIResolver(spec)
                    spec = resolver.resolve(spec)
                    self._parse_openapi(spec)
                else:
                    await self._fallback(session)
        except Exception:
            await self._fallback(session)

        if self.config.BACKEND_SOURCE_PATH and not self.endpoints:
            self._scan_router_files_recursive()

        self.endpoints = [e for e in self.endpoints if not any(e["path"].startswith(ex) for ex in self.config.EXCLUDE_PATHS)]
        return self.endpoints

    def _parse_openapi(self, spec):
        for path, methods in spec.get("paths", {}).items():
            if not isinstance(methods, dict): continue
            for method, det in methods.items():
                if method.lower() not in ["get", "post", "put", "patch", "delete"]: continue
                ep = {"path": path, "method": method.upper(), "auth_required": bool(det.get("security", []))}
                self.endpoints.append(ep)
                if ep["auth_required"]:
                    self.auth_required_paths.add(path)

    async def _fallback(self, session):
        for path, method in [
            ("/api/v1/auth/login", "POST"), ("/api/v1/auth/me", "GET"),
            ("/api/v1/users", "GET"), ("/api/v1/users", "POST"),
            ("/api/v1/invoices", "GET"), ("/api/v1/invoices", "POST"),
            ("/api/v1/inventory", "GET"), ("/api/v1/inventory", "POST"),
            ("/api/v1/journal-entries", "GET"), ("/api/v1/journal-entries", "POST"),
            ("/api/v1/approvals", "GET"), ("/api/v1/approvals", "POST"),
        ]:
            self.endpoints.append({"path": path, "method": method, "auth_required": True})

    def _scan_router_files_recursive(self):
        """Scan AST untuk include_router bertingkat dengan akumulasi prefix."""
        root = Path(self.config.BACKEND_SOURCE_PATH)
        # Kumpulkan semua variabel global per file
        file_globals = {}
        for py_file in root.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                globs = {}
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                                globs[target.id] = node.value.value
                if globs:
                    file_globals[py_file] = globs
            except: pass

        # Kumpulkan router prefix dari setiap file
        router_prefixes = {}  # file -> {"router_var": prefix, "router_obj": ...}
        for py_file in root.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "APIRouter":
                        prefix = None
                        for kw in node.keywords:
                            if kw.arg == "prefix":
                                if isinstance(kw.value, ast.Constant):
                                    prefix = kw.value.value
                                elif isinstance(kw.value, ast.Name):
                                    val = file_globals.get(py_file, {}).get(kw.value.id)
                                    if val:
                                        prefix = val
                        if prefix:
                            router_prefixes[py_file] = prefix
            except: pass

        # Fungsi rekursif untuk melacak include_router
        def collect_routes(file_path, current_prefix=""):
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "include_router":
                        # cari argumen router
                        router_arg = None
                        prefix_kw = None
                        for arg in node.args:
                            if isinstance(arg, ast.Name):
                                router_arg = arg.id
                        for kw in node.keywords:
                            if kw.arg == "prefix":
                                if isinstance(kw.value, ast.Constant):
                                    prefix_kw = kw.value.value
                                elif isinstance(kw.value, ast.Name):
                                    val = file_globals.get(file_path, {}).get(kw.value.id)
                                    if val:
                                        prefix_kw = val
                        if router_arg:
                            # cari file yang mendefinisikan router_var
                            for py_file2 in root.rglob("*.py"):
                                if py_file2 == file_path:
                                    continue
                                try:
                                    content2 = py_file2.read_text(encoding="utf-8")
                                    tree2 = ast.parse(content2)
                                    for node2 in ast.walk(tree2):
                                        if isinstance(node2, ast.Assign):
                                            for target in node2.targets:
                                                if isinstance(target, ast.Name) and target.id == router_arg:
                                                    # kita temukan router object, cari prefix
                                                    sub_prefix = router_prefixes.get(py_file2, "")
                                                    new_prefix = (current_prefix or "") + (prefix_kw or "") + sub_prefix
                                                    # rekur
                                                    collect_routes(py_file2, new_prefix)
                                except: pass
            except: pass

            # Ekstrak route dari file ini dengan prefix saat ini
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        for deco in node.decorator_list:
                            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute) and deco.func.attr in ["get","post","put","patch","delete"]:
                                if deco.args and isinstance(deco.args[0], ast.Constant):
                                    sub_path = deco.args[0].value
                                    full_path = (current_prefix.rstrip("/") + sub_path) if current_prefix else sub_path
                                    self.endpoints.append({"path": full_path, "method": deco.func.attr.upper(), "auth_required": True})
            except: pass

        # Mulai dari main file (biasanya main.py atau app.py)
        main_files = list(root.glob("main.py")) + list(root.glob("app.py"))
        if not main_files:
            # cari file yang mengandung app = FastAPI()
            for py_file in root.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    if "FastAPI()" in content or "APIRouter()" in content:
                        main_files.append(py_file)
                except: pass
        if main_files:
            for main_file in main_files:
                collect_routes(main_file, "")
        else:
            # fallback: scan semua file dengan prefix kosong
            for py_file in root.rglob("*.py"):
                collect_routes(py_file, "")

# ============================================
# PySide6 Scanner (tambahan tangkap await, async with, return await)
# ============================================
class PySide6Scanner:
    def __init__(self, frontend_path, config):
        self.frontend_path = Path(frontend_path)
        self.config = config
        self.api_calls = []
        self.gui_issues = []
        self.logger = logging.getLogger(__name__)
        self.module_vars = {}
        self._load_all_globals()

    def _load_all_globals(self):
        for py_file in self.frontend_path.rglob("*.py"):
            if any(excl in str(py_file) for excl in self.config.PYSIDE6_EXCLUDE_DIRS):
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                module = str(py_file.relative_to(self.frontend_path)).replace(os.sep,".").replace(".py","")
                globs = {}
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                                    globs[target.id] = node.value.value
                                elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
                                    left, right = node.value.left, node.value.right
                                    if isinstance(left, ast.Name) and isinstance(right, ast.Constant):
                                        globs[target.id] = ("concat", left.id, right.value)
                                    elif isinstance(left, ast.Constant) and isinstance(right, ast.Name):
                                        globs[target.id] = ("concat", right.id, left.value)
                                elif isinstance(node.value, ast.JoinedStr):
                                    parts = []
                                    for v in node.value.values:
                                        if isinstance(v, ast.Constant):
                                            parts.append(str(v.value))
                                        elif isinstance(v, ast.FormattedValue):
                                            if isinstance(v.value, ast.Name):
                                                parts.append(("var", v.value.id))
                                            else:
                                                parts.append(("expr",))
                                        else:
                                            parts.append(None)
                                    globs[target.id] = ("fstring", parts)
                    elif isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            globs[alias.asname or alias.name] = ("imported", node.module, alias.name)
                self.module_vars[module] = globs
            except Exception:
                pass

    def _resolve_fstring(self, parts, current_module, local_vars, func_name):
        resolved = ""
        for part in parts:
            if isinstance(part, str):
                resolved += part
            elif isinstance(part, tuple) and part[0] == "var":
                var_name = part[1]
                val = self._resolve_var(var_name, current_module, local_vars, func_name)
                if val:
                    resolved += val
                else:
                    return None
            else:
                return None
        return resolved

    def _resolve_var(self, name, current_module, local_vars, func_name):
        val = local_vars.get((func_name, name))
        if isinstance(val, str) and val.startswith(('/', 'http')):
            return val
        mod_globs = self.module_vars.get(current_module, {})
        if name in mod_globs:
            gv = mod_globs[name]
            if isinstance(gv, str):
                return gv
            elif isinstance(gv, tuple) and gv[0] == "concat":
                left_id, right = gv[1], gv[2]
                left_val = self._resolve_var(left_id, current_module, local_vars, func_name) or ""
                return left_val + right
            elif isinstance(gv, tuple) and gv[0] == "fstring":
                return self._resolve_fstring(gv[1], current_module, local_vars, func_name)
            elif isinstance(gv, tuple) and gv[0] == "imported":
                imp_module, imp_name = gv[1], gv[2]
                for mod, globs in self.module_vars.items():
                    if mod.endswith(imp_module) or mod == imp_module:
                        if imp_name in globs:
                            return self._resolve_var(imp_name, mod, local_vars, func_name)
        for mod, globs in self.module_vars.items():
            if name in globs:
                gv = globs[name]
                if isinstance(gv, str):
                    return gv
                elif isinstance(gv, tuple) and gv[0] == "concat":
                    left_id, right = gv[1], gv[2]
                    left_val = self._resolve_var(left_id, mod, local_vars, func_name) or ""
                    return left_val + right
                elif isinstance(gv, tuple) and gv[0] == "fstring":
                    return self._resolve_fstring(gv[1], mod, local_vars, func_name)
        return None

    def scan(self):
        self.logger.info(f"Scanning PySide6 code in: {self.frontend_path}")
        if not self.frontend_path.exists():
            return [], []
        py_files = list(self.frontend_path.rglob("*.py"))
        for file_path in py_files:
            if any(excl in str(file_path) for excl in self.config.PYSIDE6_EXCLUDE_DIRS):
                continue
            try:
                self._scan_file(file_path)
            except Exception as e:
                self.logger.warning(f"Error scanning {file_path}: {e}")
        self.logger.info(f"Found {len(self.api_calls)} API calls, {len(self.gui_issues)} GUI issues")
        return self.api_calls, self.gui_issues

    def _scan_file(self, file_path):
        try:
            content = file_path.read_text(encoding="utf-8")
        except: return
        local_vars: dict[tuple[str, str], str] = {}
        module = str(file_path.relative_to(self.frontend_path)).replace(os.sep,".").replace(".py","")
        try:
            tree = ast.parse(content)
            self._analyze_ast(tree, file_path, content, local_vars, module)
        except SyntaxError:
            self._scan_with_regex(content, file_path)

    def _analyze_ast(self, tree, file_path, content, local_vars, module):
        class_context = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_context = node.name
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                # kumpulkan assign lokal
                for child in ast.walk(node):
                    if isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                if isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                                    local_vars[(func_name, target.id)] = child.value.value
                                elif isinstance(child.value, ast.JoinedStr):
                                    parts = []
                                    all_const = True
                                    for p in child.value.values:
                                        if isinstance(p, ast.Constant):
                                            parts.append(str(p.value))
                                        else:
                                            all_const = False
                                            break
                                    if all_const:
                                        local_vars[(func_name, target.id)] = "".join(parts)
                    # tangkap await client.get(...), return await api.post(...)
                    if isinstance(child, ast.Await):
                        self._analyze_call_node(child.value, file_path, child.lineno, class_context, func_name, content, local_vars, module)
                    if isinstance(child, ast.Return):
                        if isinstance(child.value, ast.Await):
                            self._analyze_call_node(child.value.value, file_path, child.lineno, class_context, func_name, content, local_vars, module)
                    # async with
                    if isinstance(child, ast.AsyncWith):
                        for item in child.items:
                            if isinstance(item.context_expr, ast.Call):
                                self._analyze_call_node(item.context_expr, file_path, item.context_expr.lineno, class_context, func_name, content, local_vars, module)
                    # panggilan langsung
                    if isinstance(child, ast.Call):
                        self._analyze_call_node(child, file_path, child.lineno, class_context, func_name, content, local_vars, module)
            if isinstance(node, ast.Call):
                self._analyze_gui_call(node, file_path, class_context)

    def _analyze_call_node(self, node, file_path, line_no, class_name, func_name, content, local_vars, module):
        func_name_str = ""
        if isinstance(node.func, ast.Attribute):
            func_name_str = node.func.attr
        elif isinstance(node.func, ast.Name):
            func_name_str = node.func.id
        if func_name_str.lower() not in ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']:
            return
        url = None
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.startswith(('/', 'http')):
                    url = arg.value
                    break
            if isinstance(arg, ast.JoinedStr):
                parts = []
                all_const = True
                for p in arg.values:
                    if isinstance(p, ast.Constant):
                        parts.append(str(p.value))
                    else:
                        all_const = False
                        break
                if all_const:
                    url = "".join(parts)
                    if url.startswith(('/', 'http')):
                        break
            if isinstance(arg, ast.Name):
                resolved = self._resolve_var(arg.id, module, local_vars, func_name)
                if resolved:
                    url = resolved
                    break
        if not url:
            lines = content.split('\n')
            if line_no <= len(lines):
                m = re.search(r'(?<![@\w])["\'](/[^"\']+)["\']', lines[line_no-1])
                if m: url = m.group(1)
        if url:
            if not url.startswith(('/', 'http')): url = '/' + url
            self.api_calls.append(PySide6ApiCall(
                file_path=str(file_path), line_number=line_no,
                function_name=func_name, class_name=class_name or "unknown",
                url=url, method=func_name_str.upper(), is_async=isinstance(node, ast.Await)
            ))

    def _analyze_gui_call(self, node, file_path, class_name):
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'connect':
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id[0].islower():
                    self.gui_issues.append(GuiFlowIssue(
                        issue_type="SIGNAL_CONNECT", file_path=str(file_path), line_number=node.lineno,
                        widget_name="unknown", signal_name="", slot_name=arg.id,
                        description=f"Signal connected to {arg.id} (informational)",
                        severity="INFO"
                    ))

    def _scan_with_regex(self, content: str, file_path: Path):
        lines = content.split('\n')
        patterns = [
            r'(?:requests|httpx|aiohttp|session|self\.api|APIClient)\.(get|post|put|patch|delete)\s*\([^)]*["\']([^"\']+)["\']',
            r'(?:client|api)\.(?:request|call)\s*\(\s*["\'](GET|POST|PUT|PATCH|DELETE)["\']\s*,\s*["\']([^"\']+)["\']',
            r'(?:self\.api|api_client|http_client)\s*\.\s*([a-zA-Z_]+)\s*\(\s*["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line_num = content[:match.start()].count('\n') + 1
                method = match.group(1).upper()
                url = match.group(2)
                if url.startswith(('/', 'http')):
                    self.api_calls.append(PySide6ApiCall(
                        file_path=str(file_path), line_number=line_num,
                        function_name="unknown", class_name="unknown",
                        url=url, method=method, is_async='async' in content
                    ))

# ============================================
# Business Flow Runner (cleanup fleksibel + entity status filter)
# ============================================
class BusinessFlowRunner:
    def __init__(self, executor, session):
        self.executor = executor
        self.session = session
        self.base_entities = {
            "customer_id": {"endpoint": "/api/v1/customers", "body": {"name": f"Checker Customer {uuid.uuid4().hex[:6]}", "status": "active"}},
            "supplier_id": {"endpoint": "/api/v1/suppliers", "body": {"name": f"Checker Supplier {uuid.uuid4().hex[:6]}", "status": "active"}},
            "product_id": {"endpoint": "/api/v1/products", "body": {"name": f"Checker Product {uuid.uuid4().hex[:6]}", "price": 100, "status": "active"}},
        }
        self.ids = {}

    async def ensure_entities(self):
        headers = self.executor._auth_headers()
        for key, cfg in self.base_entities.items():
            entity_id = None
            # cari dengan status aktif
            try:
                async with self.session.get(f"{self.executor.base_url}{cfg['endpoint']}?limit=5&status=active", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            items = data
                        elif isinstance(data, dict) and "items" in data:
                            items = data["items"]
                        else:
                            items = []
                        for item in items:
                            if item.get("status") == "active":
                                entity_id = item.get("id")
                                break
            except: pass
            if entity_id is None:
                try:
                    async with self.session.post(f"{self.executor.base_url}{cfg['endpoint']}", json=cfg["body"], headers=headers) as resp:
                        if resp.status in [200, 201]:
                            created = await resp.json()
                            if isinstance(created, dict) and "id" in created:
                                entity_id = created["id"]
                except: pass
            if entity_id is None:
                raise RuntimeError(f"Cannot ensure entity {key}, flow aborted.")
            self.ids[key] = entity_id

    async def run_flows(self, flows):
        try:
            await self.ensure_entities()
        except RuntimeError as e:
            logging.error(e)
            return [BusinessFlowResult(flow_name=flow["name"], success=False, steps_executed=0, total_steps=len(flow.get("steps",[])), error_message=str(e)) for flow in flows]
        results = []
        for flow in flows:
            results.append(await self._run_single_flow(flow))
        return results

    async def _run_single_flow(self, flow):
        context = dict(self.ids)
        steps = flow.get("steps", [])
        total = len(steps)
        executed = 0
        error_step = None
        error_msg = None
        start = time.time()
        headers = self.executor._auth_headers()
        try:
            for i, step in enumerate(steps, 1):
                path = self._resolve_vars(step["path"], context)
                body = self._resolve_vars(step.get("body", {}), context)
                method = step["method"].upper()
                url = f"{self.executor.base_url}{path}"
                if method == "GET":
                    async with self.session.get(url, headers=headers) as resp:
                        if 200 <= resp.status < 300:
                            executed += 1
                            if "save" in step:
                                data = await resp.json()
                                self._save_context(data, step, context)
                        else:
                            error_step = i; error_msg = f"HTTP {resp.status}"; break
                else:
                    async with self.session.request(method, url, json=body, headers=headers) as resp:
                        if 200 <= resp.status < 300:
                            executed += 1
                            if "save" in step:
                                data = await resp.json()
                                self._save_context(data, step, context)
                        else:
                            error_step = i; error_msg = f"HTTP {resp.status}"; break
        except Exception as e:
            error_step = executed + 1
            error_msg = str(e)
        # Cleanup fleksibel: support POST cancel, reverse, archive
        cleanup_steps = flow.get("cleanup", [])
        if not isinstance(cleanup_steps, list):
            cleanup_steps = [cleanup_steps] if cleanup_steps else []
        for step in reversed(cleanup_steps):
            try:
                path = self._resolve_vars(step["path"], context)
                url = f"{self.executor.base_url}{path}"
                method = step["method"].upper()
                if method in ["POST", "PUT", "PATCH"]:
                    async with self.session.request(method, url, json=step.get("body", {}), headers=headers) as _:
                        pass
                else:
                    async with self.session.request(method, url, headers=headers) as _:
                        pass
            except: pass
        duration = (time.time() - start) * 1000
        return BusinessFlowResult(
            flow_name=flow["name"], success=error_step is None,
            steps_executed=executed, total_steps=total,
            error_step=error_step, error_message=error_msg,
            duration_ms=duration, context=context
        )

    def _resolve_vars(self, obj, context):
        if isinstance(obj, str):
            for k, v in context.items():
                if isinstance(v, dict) and "id" in v:
                    obj = obj.replace(f"${k}.id", str(v["id"]))
                else:
                    obj = obj.replace(f"${k}", str(v))
            return obj
        elif isinstance(obj, dict):
            return {k: self._resolve_vars(v, context) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_vars(i, context) for i in obj]
        return obj

    def _save_context(self, data, step, context):
        key = step["save"]
        if isinstance(data, dict) and "id" in data:
            context[key] = data
        elif isinstance(data, list) and data and "id" in data[0]:
            context[key] = data[0]

# ============================================
# Race Condition Checker (gunakan PayloadGenerator)
# ============================================
class RaceConditionChecker:
    def __init__(self, executor, session, spec=None):
        self.executor = executor
        self.session = session
        self.payload_gen = PayloadGenerator(executor, session, spec)

    async def check_race(self, endpoint, concurrent):
        path = endpoint["path"]
        method = endpoint["method"].upper()
        url = f"{self.executor.base_url}{path}"
        headers = self.executor._auth_headers()
        # Generate valid body
        body = await self.payload_gen.generate(path, method)
        created_ids = []

        async def make_request(unique_id):
            request_body = dict(body)
            # sisipkan unique reference jika ada
            if "reference_number" in request_body:
                request_body["reference_number"] = f"RACE-{unique_id}"
            elif "name" in request_body:
                request_body["name"] = f"race_test_{unique_id}"
            elif "code" in request_body:
                request_body["code"] = f"RACE-{unique_id}"
            if method == "GET":
                async with self.session.get(url, headers=headers) as resp:
                    text = await resp.text()
                    return resp.status, text, None
            else:
                async with self.session.request(method, url, json=request_body, headers=headers) as resp:
                    text = await resp.text()
                    data = None
                    try:
                        data = json.loads(text)
                    except: pass
                    return resp.status, text, data

        start = time.time()
        tasks = [asyncio.create_task(make_request(uuid.uuid4().hex[:8])) for _ in range(concurrent)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        duration = (time.time() - start) * 1000
        success = fail = 0
        duplicates = deadlock = False
        ids = []
        inconsistencies = []
        for r in responses:
            if isinstance(r, Exception):
                fail += 1
                if "deadlock" in str(r).lower(): deadlock = True
                continue
            status, text, data = r
            if 200 <= status < 300:
                success += 1
                if data and isinstance(data, dict) and "id" in data:
                    ids.append(data["id"])
                    created_ids.append(data["id"])
            else:
                fail += 1
        if len(ids) > len(set(ids)):
            duplicates = True
            inconsistencies.append("Duplicate IDs detected")
        # Cleanup
        for rid in created_ids:
            try:
                del_url = f"{self.executor.base_url}{path}/{rid}"
                async with self.session.delete(del_url, headers=headers) as _:
                    pass
            except:
                try:
                    del_url = f"{self.executor.base_url}{path}?id={rid}"
                    async with self.session.delete(del_url, headers=headers) as _:
                        pass
                except: pass
        return RaceConditionResult(
            endpoint=path, method=method, concurrent_requests=concurrent,
            success_count=success, failure_count=fail,
            duplicate_errors=duplicates, deadlock_errors=deadlock,
            avg_response_ms=duration/concurrent, max_response_ms=duration,
            inconsistencies=inconsistencies
        )

# ============================================
# Transaction Rollback Checker (bandingkan set id)
# ============================================
class TransactionRollbackChecker:
    def __init__(self, executor, session):
        self.executor = executor
        self.session = session

    async def test_rollback(self):
        results = []
        endpoints_to_test = [
            ("/api/v1/invoices", {"items": []}),
            ("/api/v1/journal-entries", {"amount": 0, "account_id": 1}),
            ("/api/v1/payments", {"invoice_id": 999999, "amount": -10}),
        ]
        headers = self.executor._auth_headers()
        for path, invalid_body in endpoints_to_test:
            try:
                # Ambil set id sebelum
                before_ids = await self._get_ids(path, headers)
                trans_id = None
                async with self.session.post(f"{self.executor.base_url}{path}", json=invalid_body, headers=headers) as resp:
                    if 200 <= resp.status < 300:
                        try:
                            data = await resp.json()
                            if isinstance(data, dict) and "id" in data:
                                trans_id = data["id"]
                        except: pass
                # Ambil set id setelah
                after_ids = await self._get_ids(path, headers)
                # Bandingkan set
                rollback_ok = True
                if trans_id:
                    # Jika trans_id ada, seharusnya tidak ada di after_ids
                    if trans_id in after_ids:
                        rollback_ok = False
                # Juga cek tidak ada tambahan id lain
                new_ids = after_ids - before_ids
                if new_ids:
                    rollback_ok = False
                if rollback_ok:
                    results.append({"test": f"Rollback {path}", "status": "PASS"})
                else:
                    results.append({"test": f"Rollback {path}", "status": "FAIL", "detail": f"Before ids {len(before_ids)}, after {len(after_ids)}, new ids {new_ids}"})
            except Exception as e:
                results.append({"test": f"Rollback {path}", "status": "ERROR", "detail": str(e)})
        return results

    async def _get_ids(self, path, headers):
        ids = set()
        try:
            # Pagination scan untuk ambil semua id (maks 100)
            limit = 100
            offset = 0
            while True:
                async with self.session.get(f"{self.executor.base_url}{path}?limit={limit}&offset={offset}", headers=headers) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    if isinstance(data, list):
                        items = data
                    elif isinstance(data, dict):
                        items = data.get("items", [])
                    else:
                        break
                    for item in items:
                        if "id" in item:
                            ids.add(item["id"])
                    if len(items) < limit:
                        break
                    offset += limit
                    if offset > 500:  # safety
                        break
        except: pass
        return ids

# ============================================
# Database Consistency Checker (pagination scan)
# ============================================
class DatabaseConsistencyChecker:
    def __init__(self, executor, session, config):
        self.executor = executor
        self.session = session
        self.config = config
        self.relations = self._load_relations()

    def _load_relations(self):
        if self.config.DB_CONSISTENCY_RELATIONS:
            try: return json.loads(self.config.DB_CONSISTENCY_RELATIONS)
            except: pass
        return [
            ["invoices", "journal-entries", "document_id", "status", "posted"],
            ["purchase-orders", "inventory_movements", "purchase_order_id", "status", "received"],
        ]

    async def check(self):
        issues = []
        headers = self.executor._auth_headers()
        async def check_relation(rel):
            local = []
            entity1, entity2, fk, *rest = rel
            status_filter = rest[0] if rest else None
            status_val = rest[1] if len(rest) > 1 else None
            try:
                # Scan pagination
                limit = 50
                offset = 0
                while True:
                    url = f"{self.executor.base_url}/api/v1/{entity1}?limit={limit}&offset={offset}"
                    if status_filter:
                        url += f"&{status_filter}={status_val}"
                    async with self.session.get(url, headers=headers) as resp:
                        if resp.status != 200:
                            break
                        data = await resp.json()
                        items = data if isinstance(data, list) else data.get("items", [])
                        for item in items:
                            e1_id = item.get("id")
                            if e1_id:
                                check_url = f"{self.executor.base_url}/api/v1/{entity2}?{fk}={e1_id}"
                                async with self.session.get(check_url, headers=headers) as check_resp:
                                    if check_resp.status == 200:
                                        related = await check_resp.json()
                                        rel_items = related if isinstance(related, list) else related.get("items", [])
                                        if not rel_items:
                                            local.append(f"Missing {entity2} for {entity1} {e1_id} (state: {status_val})")
                        if len(items) < limit:
                            break
                        offset += limit
                        if offset > 500:  # safety
                            break
            except Exception as e:
                local.append(f"Consistency error {entity1}-{entity2}: {e!s}")
            return local
        tasks = [check_relation(rel) for rel in self.relations]
        all_issues = await asyncio.gather(*tasks)
        for sub in all_issues:
            issues.extend(sub)
        return issues

# ============================================
# Infra Checkers (unchanged)
# ============================================
class KafkaChecker:
    async def check(self, session, endpoint):
        if not endpoint: return None
        try:
            async with session.get(endpoint) as resp:
                return await resp.json()
        except: return {"error": "Kafka unreachable"}

class RedisChecker:
    async def check(self, session, endpoint):
        if not endpoint: return None
        try:
            async with session.get(endpoint) as resp:
                return await resp.json()
        except: return {"error": "Redis unreachable"}

class CeleryChecker:
    async def check(self, session, endpoint):
        if not endpoint: return None
        try:
            async with session.get(endpoint) as resp:
                return await resp.json()
        except: return {"error": "Celery unreachable"}

class SchedulerChecker:
    async def check(self, session, endpoint):
        if not endpoint: return None
        try:
            async with session.get(endpoint) as resp:
                return await resp.json()
        except: return {"error": "Scheduler unreachable"}

# ============================================
# Ultimate Runtime Executor (token refresh dengan Event, health configurable)
# ============================================
class UltimateRuntimeExecutor:
    def __init__(self, base_url, config, session, token=None):
        self.base_url = base_url.rstrip("/")
        self.config = config
        self.session = session
        self.token = token
        self.token_version = 0
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT)
        self.rate_limiter = RateLimiter(config.RATE_LIMIT_RPS)
        self.error_analyzer = ErrorAnalyzer()
        self._login_lock = asyncio.Lock()
        self._refresh_event = asyncio.Event()
        self._refresh_in_progress = False
        self.pyside6_scanner = None
        self.api_calls = []
        self.gui_issues = []
        self.backend_endpoints = []
        self.data_integrity_cache = LRUCache(max_size=1000)
        self.data_integrity_ignore = config.DATA_INTEGRITY_IGNORE_FIELDS

    async def initialize(self, frontend_path):
        if self.config.SCAN_PYSIDE6:
            self.pyside6_scanner = PySide6Scanner(frontend_path, self.config)
            self.api_calls, self.gui_issues = self.pyside6_scanner.scan()

    def _auth_headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def login(self):
        async with self._login_lock:
            if self.token and self.token_version > 0:
                # Check token validity
                try:
                    async with self.session.get(f"{self.base_url}/api/v1/auth/me", headers=self._auth_headers()) as resp:
                        if resp.status == 200:
                            return True
                except:
                    pass
            try:
                url = f"{self.base_url}{self.config.LOGIN_ENDPOINT}"
                async with self.session.post(url, json=self.config.LOGIN_CREDENTIALS) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.token = data.get("access_token") or data.get("token")
                        self.token_version += 1
                        self._refresh_event.set()  # notify waiters
                        return bool(self.token)
                return False
            except:
                return False

    async def refresh_token_if_needed(self):
        """Jika token kadaluarsa, lakukan refresh dengan Event agar hanya satu yang melakukan login."""
        if self.token and self.token_version > 0:
            # coba test dengan request ringan ke /auth/me
            try:
                async with self.session.get(f"{self.base_url}/api/v1/auth/me", headers=self._auth_headers()) as resp:
                    if resp.status == 200:
                        return True
            except:
                pass
        # Token invalid, butuh refresh
        if self._refresh_in_progress:
            # Tunggu refresh selesai
            await self._refresh_event.wait()
            return bool(self.token)
        async with self._login_lock:
            if self._refresh_in_progress:
                await self._refresh_event.wait()
                return bool(self.token)
            self._refresh_in_progress = True
            self._refresh_event.clear()
            try:
                success = await self.login()
                self._refresh_in_progress = False
                self._refresh_event.set()
                return success
            except Exception:
                self._refresh_in_progress = False
                self._refresh_event.set()
                return False

    async def test_endpoint_with_retry(self, endpoint):
        last = None
        for attempt in range(self.config.MAX_RETRIES + 1):
            # Jika token expired, refresh
            if not await self.refresh_token_if_needed():
                # gagal refresh
                return TestResult(endpoint=endpoint["path"], method=endpoint["method"], status_code=401,
                                  success=False, duration_ms=0, error_type="AuthError",
                                  error_message="Cannot refresh token", error_category="AUTH_ERROR", severity="CRITICAL")
            result = await self._test_endpoint_once(endpoint)
            result.retry_count = attempt
            if result.success or not self.error_analyzer.is_transient(result):
                return result
            last = result
            if attempt < self.config.MAX_RETRIES:
                delay = self.config.RETRY_DELAY * (self.config.RETRY_BACKOFF_MULTIPLIER ** attempt)
                await asyncio.sleep(delay)
        return last

    async def _test_endpoint_once(self, endpoint):
        path = endpoint["path"]
        method = endpoint["method"].lower()
        url = f"{self.base_url}{path}"
        start = time.time()
        headers = self._auth_headers()
        async def make_request():
            try:
                await self.rate_limiter.acquire()
                async with self.semaphore:
                    timeout = aiohttp.ClientTimeout(total=self.config.REQUEST_TIMEOUT)
                    async with self.session.request(method, url, headers=headers, timeout=timeout) as resp:
                        dur = (time.time() - start) * 1000
                        text = await resp.text()
                        try: body = json.loads(text) if text else {}
                        except: body = {"_raw": text[:500]}
                        return TestResult(endpoint=path, method=method.upper(), status_code=resp.status,
                                          success=200 <= resp.status < 300, duration_ms=dur,
                                          response_body=body, response_headers=dict(resp.headers))
            except TimeoutError:
                return TestResult(endpoint=path, method=method.upper(), status_code=408, success=False,
                                  duration_ms=(time.time()-start)*1000, error_type="TimeoutError",
                                  error_message="Request timeout", error_category="TIMEOUT_ERROR", severity="HIGH")
            except aiohttp.ClientError as e:
                return TestResult(endpoint=path, method=method.upper(), status_code=0, success=False,
                                  duration_ms=(time.time()-start)*1000, error_type=type(e).__name__,
                                  error_message=str(e), error_category="CLIENT_ERROR", severity="HIGH")
            except Exception as e:
                return TestResult(endpoint=path, method=method.upper(), status_code=0, success=False,
                                  duration_ms=(time.time()-start)*1000, error_type=type(e).__name__,
                                  error_message=str(e), error_category="UNKNOWN_ERROR", severity="MEDIUM")
        result = await make_request()
        # Jika 401, refresh via method di atas sudah dilakukan, tapi untuk jaga-jaga
        if result.status_code == 401:
            if await self.refresh_token_if_needed():
                headers = self._auth_headers()
                result = await make_request()
        if self.config.SCAN_PYSIDE6 and self.api_calls:
            result.api_calls = self._find_related_api_calls(endpoint)
        if self.config.ENABLE_SYNC_DETECTION and result.api_calls:
            beps = self._get_backend_endpoints_for_path(path)
            for call in result.api_calls:
                issue = self._detect_sync_issue(call, beps)
                if issue: result.sync_issues.append(issue)
        if self.config.ENABLE_GUI_ANALYSIS:
            result.gui_issues = self.gui_issues
        if not result.success:
            await self._analyze_error(result, result.error_message or str(result.status_code), endpoint)
        if self.config.ENABLE_RUNTIME_EXCEPTION_COLLECTOR and result.response_body:
            exc = self.error_analyzer.parse_runtime_exception_from_body(result.response_body)
            if exc:
                result.runtime_exception = exc["exception"]
                result.runtime_file = exc["file"]; result.runtime_line = exc["line"]
                result.runtime_function = exc["function"]
                result.traceback = exc.get("traceback")
        if self.config.ENABLE_N1_DETECTOR and result.success:
            n1, cnt = self.error_analyzer.detect_n1(result.response_body, result.response_headers)
            result.n1_detected = n1; result.n1_query_count = cnt
        if result.success and self.config.ENABLE_BUSINESS_LOGIC:
            self._check_business_rules(result, endpoint)
        if result.success and self.config.ENABLE_DATA_INTEGRITY and method.upper() == "GET":
            self._check_data_integrity(result, result.response_body, path)
        return result

    async def health_check(self):
        """Gunakan endpoint health yang dikonfigurasi, fallback ke HEAD /."""
        endpoints = [self.config.HEALTH_ENDPOINT, "/", "/health"]
        for ep in endpoints:
            try:
                async with self.session.get(f"{self.base_url}{ep}", timeout=aiohttp.ClientTimeout(5)) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except:
                pass
        return {"status": "unknown"}

    def _path_to_regex(self, path):
        # Support {path:path} yang mengandung slash
        cleaned = re.sub(r"\{(\w+):[^}]+\}", r"{\1}", path)
        escaped = re.escape(cleaned).replace(r"\{", "{").replace(r"\}", "}")
        # Ganti {path} dengan .+ (bisa slash)
        return re.compile("^" + re.sub(r"\{path\}", r".+", escaped) + "/?$")

    # Fungsi lainnya sama seperti sebelumnya (find_related_api_calls, detect_sync_issue, analyze_error, check_business_rules, check_data_integrity)
    def _find_related_api_calls(self, endpoint):
        regex = self._path_to_regex(endpoint["path"])
        return [c for c in self.api_calls if regex.match(c.url.rstrip("/").split("?")[0]) and c.method == endpoint["method"]]

    def _get_backend_endpoints_for_path(self, path):
        return [ep for ep in self.backend_endpoints if ep["path"] == path]

    def _detect_sync_issue(self, call, beps):
        if not beps:
            return SyncIssue(issue_type="MISSING_ENDPOINT", frontend_file=call.file_path,
                             frontend_line=call.line_number, api_call=call, severity="CRITICAL")
        methods = [ep["method"] for ep in beps]
        if call.method not in methods:
            return SyncIssue(issue_type="METHOD_MISMATCH", frontend_file=call.file_path,
                             frontend_line=call.line_number, api_call=call,
                             backend_endpoint=beps[0], expected_method=methods[0],
                             actual_method=call.method, severity="HIGH")
        return None

    async def _analyze_error(self, result, error_context, endpoint):
        if result.traceback:
            f, l, fn = self.error_analyzer.extract_traceback_info(result.traceback)
            result.file = f; result.line = l; result.function = fn
        result.error_category = self.error_analyzer.classify_error(Exception(error_context), result.status_code, error_context)
        result.severity = self.error_analyzer.get_severity(result.error_category, result.status_code)
        result.root_cause = self.error_analyzer.extract_root_cause(result.traceback or "", result.error_message or "")
        if "DEPENDENCY" in result.error_category:
            result.dependency_errors = self.error_analyzer.parse_dependency_error(error_context)

    def _check_business_rules(self, result, endpoint):
        rules = self.config.BUSINESS_RULES
        applicable = rules.get("default", {})
        for prefix, r in rules.items():
            if prefix != "default" and result.endpoint.startswith(prefix):
                applicable = {**applicable, **r}
                break
        self._validate_nested(result.response_body, applicable, result, endpoint)

    def _validate_nested(self, obj, rules, result, endpoint, path_prefix=""):
        if isinstance(obj, dict):
            for field, rule in rules.items():
                if field in obj:
                    val = obj[field]
                    if val is None: continue
                    if "min" in rule:
                        try:
                            if float(val) < float(rule["min"]):
                                result.business_violations.append(BusinessRuleViolation(
                                    rule_name=f"{path_prefix}{field}_min", endpoint=endpoint, field=field,
                                    value=val, expected_range=f">= {rule['min']}",
                                    description=f"Value {val} below minimum"))
                        except: pass
                    if "max" in rule:
                        try:
                            if float(val) > float(rule["max"]):
                                result.business_violations.append(BusinessRuleViolation(
                                    rule_name=f"{path_prefix}{field}_max", endpoint=endpoint, field=field,
                                    value=val, expected_range=f"<= {rule['max']}",
                                    description=f"Value {val} exceeds maximum"))
                        except: pass
                    if "enum" in rule and val not in rule["enum"]:
                        result.business_violations.append(BusinessRuleViolation(
                            rule_name=f"{path_prefix}{field}_enum", endpoint=endpoint, field=field,
                            value=val, expected_range=str(rule["enum"]),
                            description=f"Value {val} not in allowed enum"))
                    if isinstance(val, str):
                        if "minLength" in rule and len(val) < rule["minLength"]:
                            result.business_violations.append(BusinessRuleViolation(
                                rule_name=f"{path_prefix}{field}_minLength", endpoint=endpoint, field=field,
                                value=val, expected_range=f">= {rule['minLength']}",
                                description=f"String length {len(val)} below minimum"))
                        if "maxLength" in rule and len(val) > rule["maxLength"]:
                            result.business_violations.append(BusinessRuleViolation(
                                rule_name=f"{path_prefix}{field}_maxLength", endpoint=endpoint, field=field,
                                value=val, expected_range=f"<= {rule['maxLength']}",
                                description=f"String length {len(val)} exceeds maximum"))
                        if "pattern" in rule:
                            if not re.search(rule["pattern"], val):
                                result.business_violations.append(BusinessRuleViolation(
                                    rule_name=f"{path_prefix}{field}_pattern", endpoint=endpoint, field=field,
                                    value=val, expected_range=f"pattern {rule['pattern']}",
                                    description=f"Value '{val}' does not match pattern"))
                    if "format" in rule and isinstance(val, str):
                        fmt = rule["format"]
                        if fmt == "email" and "@" not in val:
                            result.business_violations.append(BusinessRuleViolation(
                                rule_name=f"{path_prefix}{field}_format", endpoint=endpoint, field=field,
                                value=val, expected_range="email", description="Invalid email format"))
                        elif fmt == "uri" and not val.startswith(("http://", "https://")):
                            result.business_violations.append(BusinessRuleViolation(
                                rule_name=f"{path_prefix}{field}_format", endpoint=endpoint, field=field,
                                value=val, expected_range="uri", description="Invalid URI format"))
            for key, value in obj.items():
                if isinstance(value, dict):
                    self._validate_nested(value, rules, result, endpoint, f"{path_prefix}{key}.")
                elif isinstance(value, list):
                    for item in value:
                        self._validate_nested(item, rules, result, endpoint, f"{path_prefix}{key}[].")
        elif isinstance(obj, list):
            for item in obj:
                self._validate_nested(item, rules, result, endpoint, path_prefix)

    def _check_data_integrity(self, result, response_body, path):
        if not response_body: return
        records = [response_body] if isinstance(response_body, dict) else response_body
        if not isinstance(records, list): records = [records]
        ok = True
        for rec in records:
            if not isinstance(rec, dict): continue
            rec_id = rec.get("id", str(uuid.uuid4()))
            key = f"{path}_{rec_id}"
            current_hash = self.error_analyzer.compute_data_hash(rec, self.data_integrity_ignore)
            cached = self.data_integrity_cache.get(key)
            if cached is not None and cached != current_hash:
                ok = False
                break
            self.data_integrity_cache.put(key, current_hash)
        result.data_integrity_ok = ok

    async def run_tests(self, endpoints):
        self.backend_endpoints = endpoints
        if not self.token:
            if not await self.login():
                logging.error("Login failed")
                return []
        tasks = [self.test_endpoint_with_retry(ep) for ep in endpoints]
        results = []
        for coro in asyncio.as_completed(tasks):
            try:
                results.append(await coro)
            except Exception as e:
                logging.error(f"Unexpected: {e}")
        self.results = results
        return results

# ============================================
# Report Builder (lazy loading body)
# ============================================
class UltimateReportBuilder:
    def __init__(self, report: HealthReport):
        self.report = report

    def build_html(self):
        rows = []
        for r in self.report.results:
            rc = html_module.escape(r.root_cause or "")
            trace_id = f"trace_{uuid.uuid4().hex[:6]}"
            body_id = f"body_{uuid.uuid4().hex[:6]}"
            response_preview = html_module.escape(json.dumps(r.response_body, indent=2, default=str)) if r.response_body else ""
            # Sembunyikan dengan display none, tampilkan via button
            rows.append(f"""<tr class="{"success" if r.success else "error"}">
                <td>{html_module.escape(r.endpoint)}</td>
                <td>{r.method}</td>
                <td>{r.status_code}</td>
                <td>{round(r.duration_ms,1)}ms</td>
                <td>{html_module.escape(r.error_type or "")}</td>
                <td>{html_module.escape(r.severity or "")}</td>
                <td>{'⚠️' if r.sync_issues else '✅'}</td>
                <td>
                    <button onclick="document.getElementById('{trace_id}').style.display='block'">Trace</button>
                    <button onclick="document.getElementById('{body_id}').style.display='block'">Body</button>
                    <div id="{trace_id}" style="display:none;background:#f4f4f4;padding:10px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:200px;overflow:auto;">{rc}</div>
                    <div id="{body_id}" style="display:none;background:#f4f4f4;padding:10px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:300px;overflow:auto;">{response_preview}</div>
                </td>
            </tr>""")
        html = f"""<!DOCTYPE html>
<html><head><title>Health Report v4.8</title>
<style>body{{font-family:Arial;margin:20px}} table{{width:100%;border-collapse:collapse}} th{{background:#667eea;color:white;padding:8px}} td{{padding:6px;border-bottom:1px solid #ddd}} .success{{background:#e8f5e9}} .error{{background:#ffebee}}</style>
</head><body>
<h1>🚀 Health Report v4.8</h1>
<p>Overall Score: <b>{round(self.report.overall_score,1)}</b>/100</p>
<table><thead><tr><th>Endpoint</th><th>Method</th><th>Status</th><th>Duration</th><th>Error</th><th>Severity</th><th>Sync</th><th>Details</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p><small>Generated {html_module.escape(self.report.timestamp)}</small></p>
</body></html>"""
        return html

    def build_json(self):
        return json.dumps({
            "scores": {"overall": round(self.report.overall_score, 1)},
            "results": [r.to_dict() for r in self.report.results],
            "sync_issues": [i.to_dict() for i in self.report.sync_issues],
            "business_flows": [asdict(f) for f in self.report.business_flows],
        }, indent=2, default=str)

    def build_csv(self):
        output = io.StringIO()
        fieldnames = list(TestResult("","",0,True,0).to_csv_row().keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for r in self.report.results:
            row = r.to_csv_row()
            for k, v in row.items():
                if v is None:
                    row[k] = ""
            writer.writerow(row)
        return output.getvalue()

    def build_markdown(self):
        md = f"# Health Report v4.8\n**Overall Score:** {round(self.report.overall_score,1)}/100\n"
        md += "## Sync Issues\n" + "\n".join(f"- {i.issue_type} {i.api_call.url}" for i in self.report.sync_issues) or "None"
        return md

# ============================================
# Ultimate Runtime Checker (integrasi semua)
# ============================================
class UltimateRuntimeChecker:
    def __init__(self, config=None):
        self.config = config or CheckerConfig()
        self.report = HealthReport()
        self.logger = logging.getLogger(__name__)

    async def run(self):
        async with aiohttp.ClientSession() as session:
            # Login awal
            token = None
            try:
                async with session.post(f"{self.config.BASE_URL}{self.config.LOGIN_ENDPOINT}",
                                        json=self.config.LOGIN_CREDENTIALS) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        token = data.get("access_token") or data.get("token")
            except: pass

            executor = UltimateRuntimeExecutor(self.config.BASE_URL, self.config, session, token)

            if self.config.SCAN_PYSIDE6:
                await executor.initialize(self.config.FRONTEND_PATH)

            discovery = EnhancedEndpointDiscovery(self.config.BASE_URL, self.config)
            endpoints = await discovery.discover(session)
            self.report.total_endpoints = len(endpoints)
            critical = {"/api/v1/auth/login", "/api/v1/journal-entries/posting", "/api/v1/invoices", "/api/v1/payments"}

            # Load OpenAPI spec
            spec = {}
            try:
                async with session.get(f"{self.config.BASE_URL}/openapi.json") as resp:
                    if resp.status == 200:
                        spec = await resp.json()
                        resolver = OpenAPIResolver(spec)
                        spec = resolver.resolve(spec)
            except: pass

            # Business rule loader
            rule_loader = BusinessRuleLoader(self.config, spec)
            await rule_loader.load_from_openapi(session)
            self.config.BUSINESS_RULES = rule_loader.rules

            # Frontend mapping
            if self.config.SCAN_PYSIDE6 and executor.api_calls:
                self.report.total_api_calls_found = len(executor.api_calls)
                used = set()
                for ep in endpoints:
                    regex = executor._path_to_regex(ep["path"])
                    if any(regex.match(c.url.rstrip("/").split("?")[0]) for c in executor.api_calls):
                        used.add(ep["path"])
                self.report.endpoints_used_by_frontend = used
                self.report.endpoints_not_used = {ep["path"] for ep in endpoints} - used
                if self.config.ENABLE_GUI_ANALYSIS:
                    self.report.gui_issues = executor.gui_issues
                    self.report.gui_issues_count = len(executor.gui_issues)

            # API tests
            results = await executor.run_tests(endpoints)
            self.report.results = results
            self.report.tested_endpoints = len(results)
            for r in results:
                if r.success: self.report.successful += 1
                else: self.report.failed += 1
                if r.retry_count: self.report.retried += 1
                self.report.status_codes[r.status_code] = self.report.status_codes.get(r.status_code,0)+1
                if r.error_category: self.report.error_categories[r.error_category] = self.report.error_categories.get(r.error_category,0)+1
                if r.sync_issues: self.report.sync_issues.extend(r.sync_issues)
                if r.business_violations: self.report.business_violations.extend(r.business_violations)
                if r.runtime_exception: self.report.runtime_exception_count += 1
                if r.n1_detected: self.report.n1_detected_count += 1
            self.report.sync_issues_count = len(self.report.sync_issues)
            self.report.business_violations_count = len(self.report.business_violations)

            # Business flows
            if self.config.ENABLE_BUSINESS_FLOWS:
                flow_runner = BusinessFlowRunner(executor, session)
                self.report.business_flows = await flow_runner.run_flows(self.config.business_flows)

            # Race conditions
            if self.config.ENABLE_RACE_CONDITION:
                race_checker = RaceConditionChecker(executor, session, spec=spec)
                for ep in [e for e in endpoints if e["method"] in ["POST","PUT","PATCH"]][:2]:
                    for lvl in self.config.race_concurrency_levels:
                        self.report.race_condition_results.append(await race_checker.check_race(ep, lvl))

            # Transaction rollback
            if self.config.ENABLE_TRANSACTION_ROLLBACK:
                rollback_checker = TransactionRollbackChecker(executor, session)
                self.report.transaction_rollback_results = await rollback_checker.test_rollback()

            # DB consistency
            if self.config.ENABLE_DB_CONSISTENCY:
                consistency_checker = DatabaseConsistencyChecker(executor, session, self.config)
                self.report.db_consistency_issues = await consistency_checker.check()

            # Infra
            if self.config.ENABLE_KAFKA_CHECK:
                self.report.kafka_status = await KafkaChecker().check(session, self.config.KAFKA_MONITOR_ENDPOINT)
            if self.config.ENABLE_REDIS_CHECK:
                self.report.redis_status = await RedisChecker().check(session, self.config.REDIS_MONITOR_ENDPOINT)
            if self.config.ENABLE_CELERY_CHECK:
                self.report.celery_status = await CeleryChecker().check(session, self.config.CELERY_MONITOR_ENDPOINT)
            if self.config.ENABLE_SCHEDULER_CHECK:
                self.report.scheduler_status = await SchedulerChecker().check(session, self.config.SCHEDULER_MONITOR_ENDPOINT)

            # Leak detection
            if self.config.ENABLE_LEAK_DETECTION and self.config.PROCESS_DEBUG_ENDPOINT:
                try:
                    async with session.get(f"{self.config.BASE_URL}{self.config.PROCESS_DEBUG_ENDPOINT}") as resp:
                        if resp.status == 200:
                            before = await resp.json()
                            for _ in range(20):
                                await executor.health_check()
                            async with session.get(f"{self.config.BASE_URL}{self.config.PROCESS_DEBUG_ENDPOINT}") as resp2:
                                after = await resp2.json()
                                self.report.memory_leak_detected = executor.error_analyzer.check_memory_leak(before, after)
                                self.report.thread_leak_detected = executor.error_analyzer.check_thread_leak(before, after)
                except: pass

            self.report.calculate_statistics(critical_endpoints=critical)

            builder = UltimateReportBuilder(self.report)
            out = self.config.OUTPUT_DIR
            out.mkdir(parents=True, exist_ok=True)
            (out/"report.html").write_text(builder.build_html(), encoding="utf-8")
            (out/"report.json").write_text(builder.build_json(), encoding="utf-8")
            (out/"report.csv").write_text(builder.build_csv(), encoding="utf-8")
            (out/"report.md").write_text(builder.build_markdown(), encoding="utf-8")
            self._print_summary()
        return self.report

    def _print_summary(self):
        print(f"\n{'='*50}")
        print(f"Overall Score: {self.report.overall_score:.1f}/100")
        print(f"Backend: {self.report.backend_score:.1f}  Sync: {self.report.sync_score:.1f}  GUI: {self.report.gui_score:.1f}")
        print(f"Success: {self.report.successful}, Failed: {self.report.failed}")
        print(f"Sync Issues: {self.report.sync_issues_count}  Runtime Exceptions: {self.report.runtime_exception_count}")
        print(f"Memory Leak: {self.report.memory_leak_detected}, Thread Leak: {self.report.thread_leak_detected}")
        print(f"Reports: {self.config.OUTPUT_DIR}")

# ============================================
# CLI
# ============================================
def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")

async def main():
    setup_logging()
    import argparse
    parser = argparse.ArgumentParser(description="Ultimate Runtime Verification Checker v4.8 Production Grade")
    parser.add_argument("--backend", default=os.getenv("API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--frontend", default=os.getenv("FRONTEND_PATH", "./erp_frontend"))
    parser.add_argument("--backend-src", default=os.getenv("BACKEND_SOURCE_PATH", ""))
    parser.add_argument("--output", default=os.getenv("OUTPUT_DIR", "checker_reports"))
    parser.add_argument("--concurrent", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--rate-limit", type=float, default=0)
    parser.add_argument("--email", default=os.getenv("TEST_EMAIL"))
    parser.add_argument("--password", default=os.getenv("TEST_PASSWORD"))
    parser.add_argument("--health-path", default=os.getenv("HEALTH_ENDPOINT", "/health"))
    parser.add_argument("--no-scan", action="store_true")
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--no-business", action="store_true")
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--no-flows", action="store_true")
    parser.add_argument("--no-race", action="store_true")
    parser.add_argument("--no-rollback", action="store_true")
    parser.add_argument("--no-consistency", action="store_true")
    parser.add_argument("--enable-kafka", action="store_true")
    parser.add_argument("--enable-redis", action="store_true")
    parser.add_argument("--enable-celery", action="store_true")
    parser.add_argument("--enable-scheduler", action="store_true")
    parser.add_argument("--enable-leak", action="store_true")
    parser.add_argument("--debug-endpoint", default=os.getenv("PROCESS_DEBUG_ENDPOINT", "/debug/process"))
    args = parser.parse_args()

    # Siapkan credentials dari CLI jika diberikan
    login_creds = {}
    if args.email and args.password:
        login_creds = {"email": args.email, "password": args.password}
    elif os.getenv("TEST_EMAIL") and os.getenv("TEST_PASSWORD"):
        login_creds = {"email": os.getenv("TEST_EMAIL"), "password": os.getenv("TEST_PASSWORD")}
    else:
        print("\n❌ Error: Please provide --email and --password or set TEST_EMAIL/TEST_PASSWORD environment variables.")
        sys.exit(1)

    try:
        config = CheckerConfig(
            BASE_URL=args.backend,
            FRONTEND_PATH=args.frontend,
            BACKEND_SOURCE_PATH=args.backend_src,
            MAX_CONCURRENT=args.concurrent,
            REQUEST_TIMEOUT=args.timeout,
            MAX_RETRIES=args.retries,
            RATE_LIMIT_RPS=args.rate_limit,
            SCAN_PYSIDE6=not args.no_scan,
            ENABLE_SYNC_DETECTION=not args.no_sync,
            ENABLE_BUSINESS_LOGIC=not args.no_business,
            ENABLE_GUI_ANALYSIS=not args.no_gui,
            ENABLE_BUSINESS_FLOWS=not args.no_flows,
            ENABLE_RACE_CONDITION=not args.no_race,
            ENABLE_TRANSACTION_ROLLBACK=not args.no_rollback,
            ENABLE_DB_CONSISTENCY=not args.no_consistency,
            ENABLE_KAFKA_CHECK=args.enable_kafka,
            ENABLE_REDIS_CHECK=args.enable_redis,
            ENABLE_CELERY_CHECK=args.enable_celery,
            ENABLE_SCHEDULER_CHECK=args.enable_scheduler,
            ENABLE_LEAK_DETECTION=args.enable_leak,
            PROCESS_DEBUG_ENDPOINT=args.debug_endpoint,
            HEALTH_ENDPOINT=args.health_path,
            OUTPUT_DIR=Path(args.output),
            LOGIN_CREDENTIALS=login_creds
        )
    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}")
        sys.exit(1)

    checker = UltimateRuntimeChecker(config)
    report = await checker.run()
    return 0 if report.failed == 0 else 1

if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n⏹️ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        traceback.print_exc()
        sys.exit(1)
