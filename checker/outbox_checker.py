#!/usr/bin/env python3
"""
checker/outbox_checker.py
==========================
Sovereign ERP System — Outbox Pattern Compliance & Forensic Checker v14.2
Fixes: OUT-014 now detects default=OutboxStatus.PENDING.value (attribute references).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# =============================================================================
# ROOT PATH
# =============================================================================
_THIS_FILE = Path(__file__).resolve()
if _THIS_FILE.parent.name == "checker":
    ROOT = _THIS_FILE.parent.parent
else:
    ROOT = _THIS_FILE.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =============================================================================
# COLOR SUPPORT
# =============================================================================
def _supports_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    import platform
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                return True
        except Exception:
            return False
    return True

_USE_COLOR = _supports_ansi()
COLOR: dict[str, str] = {
    "RED": "\033[91m" if _USE_COLOR else "",
    "GREEN": "\033[92m" if _USE_COLOR else "",
    "YELLOW": "\033[93m" if _USE_COLOR else "",
    "CYAN": "\033[96m" if _USE_COLOR else "",
    "BOLD": "\033[1m" if _USE_COLOR else "",
    "DIM": "\033[2m" if _USE_COLOR else "",
    "RESET": "\033[0m" if _USE_COLOR else "",
}

# =============================================================================
# RCA INTEGRATION
# =============================================================================
_RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

try:
    _checker_core = ROOT / "checker" / "core"
    if str(_checker_core) not in sys.path:
        sys.path.insert(0, str(_checker_core))

    from rca import analyze_exception, get_engine
    _rca_engine = get_engine()
    _analyze_exception = analyze_exception
    _RCA_AVAILABLE = True
except ImportError:
    try:
        _this_dir = _THIS_FILE.parent
        if str(_this_dir) not in sys.path:
            sys.path.insert(0, str(_this_dir))
        from rca import analyze_exception
        _analyze_exception = analyze_exception
        _RCA_AVAILABLE = True
    except ImportError:
        pass

# =============================================================================
# CONFIGURATION
# =============================================================================
EXCLUDED_DIRS = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
}

OUTBOX_ENTITY_KEYWORDS = {"Outbox", "OutboxEvent", "OutboxMessage", "OutboxRecord"}
OUTBOX_REPO_KEYWORDS = {"OutboxRepository", "OutboxStore"}
OUTBOX_PUBLISHER_KEYWORDS = {"OutboxPublisher", "OutboxProcessor", "OutboxRelay", "OutboxPoller"}
OUTBOX_CONSUMER_KEYWORDS = {"OutboxConsumer", "OutboxHandler"}
OUTBOX_DEADLETTER_KEYWORDS = {"DeadLetter", "DLQ", "DeadLetterQueue"}

# --- FLEXIBLE PATTERN SETS ---
REQUIRED_FIELDS = {"id", "event_type", "payload", "status"}

TIMESTAMP_ALIASES = {"created_at", "occurred_at", "event_time", "timestamp", "raised_at", "created_on", "created"}
PAYLOAD_ALIASES = {"payload", "payload_json", "data", "event_data", "message", "content"}

IDEMPOTENCY_ALIASES = {
    "idempotency_key", "event_uuid", "event_hash", "event_checksum",
    "message_id", "dedup_key", "aggregate_version", "unique_transaction_id",
    "uuid", "guid", "external_id",
    "event_id", "event_guid", "hash", "payload_hash",
    "request_id", "correlation_id", "trace_id"
}

EVENT_ID_ALIASES = {"event_id", "event_uuid", "event_uid", "message_uuid", "event_guid"}
AGGREGATE_ID_ALIASES = {"aggregate_id", "aggregate_uuid", "root_id", "entity_id"}

MAIN_METHOD_NAMES = {
    "publish", "process", "poll", "run", "start", "loop",
    "execute", "tick", "process_batch", "run_forever",
    "worker", "consume", "relay", "dispatch", "handle_events",
    "_run_loop", "_process_events", "poll_forever"
}

# --- Keyword sets (untuk fallback string-based) ---
TRANSACTION_KEYWORDS = {
    "transaction", "uow", "unit_of_work", "begin", "commit", "rollback",
    "@transactional", "@atomic", "with_for_update",
    "self._uow", "self.uow", "container.uow", "session.begin",
    "async with session", "get_async_session"
}

RETRY_KEYWORDS = {
    "retry", "tenacity", "backoff", "RetryPolicy", "retry_policy",
    "max_attempts", "max_retries", "attempt +=", "retry_count",
    "retry_delay_seconds", "_retry_policy"
}

LOCK_KEYWORDS = {
    "select_for_update", "with_for_update", "for_update", "skip_locked",
    "nowait", "redis.lock", "distributed_lock", "Lock",
    "advisory_lock", "asyncio.Lock", "threading.Lock", "Semaphore", "Lease",
    "setnx", "expire", "_acquire_lock", "_release_lock", "_renew_lock",
    "try_lock", "unlock", "extend_lock"
}

DEAD_LETTER_KEYWORDS = {
    "dead", "dlq", "dead_letter", "dead_letter_queue",
    "DEAD_LETTER", "mark_dead_letter", "OUTBOX_STATUS_DEAD_LETTER",
    "_mark_as_failed", "_mark_as_dead_letter"
}

METRICS_KEYWORDS = {
    "counter", "histogram", "gauge", "meter", "metrics", "telemetry", "opentelemetry",
    "MeterProvider", "create_counter", "create_histogram", "ObservableGauge", "Meter",
    "prometheus", "Counter", "Histogram", "Gauge"
}

HEALTH_KEYWORDS = {"health", "ready", "liveness", "readiness", "health_check"}
LOGGING_KEYWORDS = {"logging", "logger", "structlog", "audit_logger", "telemetry", "get_logger"}
CIRCUIT_KEYWORDS = {"circuit", "circuit_breaker"}
RATE_LIMIT_KEYWORDS = {"rate_limit", "throttle"}
TIMEOUT_KEYWORDS = {"timeout", "asyncio.timeout"}
BACKOFF_KEYWORDS = {"backoff", "exponential"}
SHUTDOWN_KEYWORDS = {"shutdown", "stop", "close"}
BATCH_KEYWORDS = {"batch", "limit", "batch_size"}
ORDERING_KEYWORDS = {"order_by", "asc", "desc", "created_at"}
ASYNC_KEYWORDS = {"async", "await"}
SCHEMA_KEYWORDS = {"schema", "validate", "pydantic", "validator", "ValidationError", "BaseModel"}
RECONNECT_KEYWORDS = {"reconnect", "auto_reconnect"}

BROKER_KEYWORDS = {
    "broker", "kafka", "rabbit", "message_bus", "mq", "pulsar",
    "BrokerPort", "EventBus", "MessagePublisher", "Dispatcher", "Mediator",
    "KafkaProducer", "RabbitMQ", "PulsarClient",
    "KafkaProducerWrapper", "send_event", "producer", "publisher", "MessageBrokerPort",
    "get_kafka_producer", "_get_producer"
}

ERROR_CLASS_KEYWORDS = {"temporary", "permanent", "retryable", "fatal", "transient"}

MIXIN_FIELDS = {
    "TimestampMixin": {"created_at", "updated_at"},
    "SoftDeleteMixin": {"deleted_at"},
}

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class OutboxViolation:
    rule_id: str
    file_path: str
    component_name: str
    severity: str
    message: str
    suggestion: str
    line: int = 0
    rca_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "rule_id": self.rule_id,
            "file": self.file_path,
            "component": self.component_name,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "line": self.line,
        }
        if self.rca_result:
            d["rca"] = self.rca_result
        return d


@dataclass
class OutboxInfo:
    file_path: str
    component_name: str
    component_type: str
    fields: set[str] = field(default_factory=set)
    methods: set[str] = field(default_factory=set)
    has_transaction: bool = False
    has_retry: bool = False
    has_idempotency: bool = False
    has_dead_letter: bool = False
    has_monitoring: bool = False
    has_health: bool = False
    has_logging: bool = False
    has_lock: bool = False
    has_batch: bool = False
    has_ordering: bool = False
    has_shutdown: bool = False
    has_async: bool = False
    has_schema_validation: bool = False
    has_circuit_breaker: bool = False
    has_rate_limit: bool = False
    has_timeout: bool = False
    has_backoff: bool = False
    has_max_retries: bool = False
    has_error_classification: bool = False
    has_auto_reconnect: bool = False
    has_broker_integration: bool = False
    violations: list[OutboxViolation] = field(default_factory=list)


@dataclass
class CheckerResult:
    components: list[OutboxInfo]
    total_components: int
    total_violations: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int
    score: float
    rca_enabled: bool
    elapsed_seconds: float


# =============================================================================
# CHECKER CLASS
# =============================================================================

class OutboxChecker:
    def __init__(self, root_dir: Path, enable_rca: bool = True):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self.components: list[OutboxInfo] = []

    # -------------------------------------------------------------------------
    # File & AST Utilities
    # -------------------------------------------------------------------------
    def _get_python_files(self) -> list[Path]:
        py_files = []
        scan_dirs = ["infrastructure", "application", "adapters", "domain", "kernel", "bootstrap"]
        for dir_name in scan_dirs:
            base = self.root_dir / dir_name
            if not base.exists():
                continue
            for p in base.rglob("*.py"):
                if any(part in EXCLUDED_DIRS for part in p.parts):
                    continue
                if p.name.startswith(("test_", "conftest", "__init__")):
                    continue
                py_files.append(p)
        return py_files

    def _get_fields_and_methods(self, node: ast.ClassDef) -> tuple[set[str], set[str]]:
        fields, methods = set(), set()
        for item in node.body:
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            fields.add(target.id)
                else:
                    if isinstance(item.target, ast.Name):
                        fields.add(item.target.id)
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.add(item.name)
        return fields, methods

    def _get_base_classes(self, node: ast.ClassDef) -> list[str]:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        return bases

    def _has_mixin_field(self, node: ast.ClassDef, field: str) -> bool:
        bases = self._get_base_classes(node)
        for base in bases:
            if base in MIXIN_FIELDS and field in MIXIN_FIELDS[base]:
                return True
        return False

    # --- IMPROVED: check default values including Column() arguments ---
    def _has_default_value(self, node: ast.ClassDef, field: str, default: Any) -> bool:
        default_str = str(default).lower()
        for item in node.body:
            # AnnAssign: field: SomeType = value
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == field:
                if item.value:
                    try:
                        val = ast.unparse(item.value).lower()
                        # Check if default string appears in the representation
                        if default_str in val or val == default_str or val == f'"{default_str}"' or val == f"'{default_str}'":
                            return True
                    except Exception:
                        pass
            # Assign: field = something
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == field:
                        if isinstance(item.value, ast.Call):
                            for kw in item.value.keywords:
                                if kw.arg in ("default", "server_default"):
                                    try:
                                        val = ast.unparse(kw.value).lower()
                                        if default_str in val or val == default_str or val == f'"{default_str}"' or val == f"'{default_str}'":
                                            return True
                                    except Exception:
                                        pass
                        elif isinstance(item.value, ast.Constant):
                            if str(item.value.value).lower() == default_str:
                                return True
        return False

    # --- IMPROVED: detect if Column uses Enum type ---
    def _is_enum_column(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if not isinstance(node.func, ast.Name) or node.func.id != "Column":
            return False
        if node.args:
            type_node = node.args[0]
            type_str = ast.unparse(type_node).lower()
            if "enum" in type_str:
                return True
            if isinstance(type_node, ast.Name) and "enum" in type_node.id.lower():
                return True
        return False

    def _generate_rca(self, rule_id: str, msg: str, severity: str) -> dict[str, Any] | None:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {msg}")
            result = _analyze_exception(exc, {"rule_id": rule_id, "severity": severity})
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": msg, "suggested_fix": "Periksa implementasi Outbox."}

    # -------------------------------------------------------------------------
    # v14.0: Deep AST Detection - lebih akurat
    # -------------------------------------------------------------------------
    def _scan_ast_for_keywords(self, node: ast.AST, keywords: set[str]) -> bool:
        """Full AST traversal dengan string-based scanning."""
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for alias in sub.names:
                    if any(kw in alias.name.lower() for kw in keywords):
                        return True
            if isinstance(sub, ast.ImportFrom):
                if sub.module:
                    if any(kw in sub.module.lower() for kw in keywords):
                        return True
                for alias in sub.names:
                    if any(kw in alias.name.lower() for kw in keywords):
                        return True
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                val_lower = sub.value.lower()
                if any(kw in val_lower for kw in keywords):
                    return True
            if isinstance(sub, ast.Attribute):
                if any(kw in sub.attr.lower() for kw in keywords):
                    return True
            if isinstance(sub, ast.Name):
                if any(kw in sub.id.lower() for kw in keywords):
                    return True
            if isinstance(sub, ast.Call):
                call_str = ast.unparse(sub.func).lower()
                if any(kw in call_str for kw in keywords):
                    return True
                for arg in sub.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if any(kw in arg.value.lower() for kw in keywords):
                            return True
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    target_str = ast.unparse(target).lower()
                    if any(kw in target_str for kw in keywords):
                        return True
                val_str = ast.unparse(sub.value).lower()
                if any(kw in val_str for kw in keywords):
                    return True
            if isinstance(sub, (ast.With, ast.AsyncWith)):
                for item in sub.items:
                    ctx_str = ast.unparse(item.context_expr).lower()
                    if any(kw in ctx_str for kw in keywords):
                        return True
                    if isinstance(item.context_expr, ast.Call):
                        call_str = ast.unparse(item.context_expr.func).lower()
                        if any(kw in call_str for kw in keywords):
                            return True
        return False

    def _has_feature_full_ast(self, node: ast.ClassDef, keywords: set[str]) -> bool:
        return self._scan_ast_for_keywords(node, keywords)

    # --- v14.0: AST-based detection yang lebih dalam ---

    def _has_transaction(self, node: ast.ClassDef) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.AsyncWith):
                for item in sub.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Call):
                        func = ctx.func
                        if isinstance(func, ast.Name) and func.id == "get_async_session":
                            return True
                    if isinstance(ctx, ast.Attribute):
                        if ctx.attr == "begin":
                            obj = ctx.value
                            if isinstance(obj, ast.Name) and obj.id in ("session", "uow", "_uow"):
                                return True
            if isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Name) and func.id == "get_async_session":
                    return True
                if isinstance(func, ast.Attribute):
                    if func.attr == "begin":
                        obj = func.value
                        if isinstance(obj, ast.Name) and obj.id in ("session", "uow", "_uow"):
                            return True
            if isinstance(sub, ast.Assign):
                val_str = ast.unparse(sub.value).lower()
                if "uow" in val_str or "unit_of_work" in val_str:
                    return True
        return self._scan_ast_for_keywords(node, TRANSACTION_KEYWORDS)

    def _has_retry(self, node: ast.ClassDef) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if isinstance(target, ast.Name):
                        if target.id in ("retry_delay_seconds", "max_retries", "max_attempts"):
                            return True
                val_str = ast.unparse(sub.value).lower()
                if "retry_delay_seconds" in val_str or "max_retries" in val_str:
                    return True
            if isinstance(sub, ast.Dict):
                for key in sub.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        if "retry_delay_seconds" in key.value.lower():
                            return True
        return self._scan_ast_for_keywords(node, RETRY_KEYWORDS)

    def _has_lock(self, node: ast.ClassDef) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Attribute):
                    if func.attr in ("setnx", "expire", "try_lock", "extend_lock"):
                        return True
                if isinstance(func, ast.Name) and func.id == "setnx":
                    return True
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if isinstance(target, ast.Name):
                        if target.id in ("_acquire_lock", "_release_lock", "_renew_lock"):
                            return True
        return self._scan_ast_for_keywords(node, LOCK_KEYWORDS)

    def _has_dead_letter(self, node: ast.ClassDef) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if isinstance(target, ast.Name):
                        if "OUTBOX_STATUS_DEAD_LETTER" in target.id:
                            return True
                val_str = ast.unparse(sub.value).lower()
                if "dead_letter" in val_str:
                    return True
            if isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Attribute):
                    if func.attr in ("_mark_as_failed", "_mark_as_dead_letter", "mark_dead_letter"):
                        return True
        return self._scan_ast_for_keywords(node, DEAD_LETTER_KEYWORDS)

    def _has_broker_api(self, node: ast.ClassDef) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom):
                if sub.module and "kafka_producer_wrapper" in sub.module.lower():
                    for alias in sub.names:
                        if any(kw in alias.name.lower() for kw in ("kafkaproducerwrapper", "get_kafka_producer")):
                            return True
            if isinstance(sub, ast.Import):
                for alias in sub.names:
                    if "kafka_producer_wrapper" in alias.name.lower():
                        return True
            if isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Name) and func.id in ("get_kafka_producer", "get_producer"):
                    return True
                if isinstance(func, ast.Attribute) and func.attr in ("_get_producer", "send_event"):
                    return True
        return self._scan_ast_for_keywords(node, BROKER_KEYWORDS)

    def _has_ordering(self, node: ast.ClassDef) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Attribute) and func.attr in ("order_by", "asc", "desc"):
                    return True
                if isinstance(func, ast.Name) and func.id in ("order_by", "asc", "desc"):
                    return True
        return self._scan_ast_for_keywords(node, ORDERING_KEYWORDS)

    def _has_batch(self, node: ast.ClassDef) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if isinstance(target, ast.Name):
                        if target.id in ("batch_size", "limit"):
                            return True
                val_str = ast.unparse(sub.value).lower()
                if "batch_size" in val_str or "limit" in val_str:
                    return True
            if isinstance(sub, ast.Dict):
                for key in sub.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        if "batch_size" in key.value.lower() or "limit" in key.value.lower():
                            return True
        return self._scan_ast_for_keywords(node, BATCH_KEYWORDS)

    def _has_idempotency(self, node: ast.ClassDef) -> bool:
        fields, _ = self._get_fields_and_methods(node)
        if any(f in fields for f in IDEMPOTENCY_ALIASES):
            return True
        for sub in ast.walk(node):
            if isinstance(sub, ast.Dict):
                for key in sub.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        if any(kw in key.value.lower() for kw in ("idempotency", "dedup")):
                            return True
        return self._scan_ast_for_keywords(node, IDEMPOTENCY_ALIASES)

    def _has_main_method(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in MAIN_METHOD_NAMES:
                    return True
                has_loop = any(isinstance(n, (ast.While, ast.For)) for n in ast.walk(item))
                if has_loop:
                    for n in ast.walk(item):
                        if isinstance(n, ast.Call):
                            call_str = ast.unparse(n.func).lower()
                            if any(kw in call_str for kw in ("fetch", "poll", "select", "get_pending", "get_unprocessed", "find_pending")):
                                return True
        return False

    def _has_health(self, node: ast.ClassDef) -> bool:
        return self._has_feature_full_ast(node, HEALTH_KEYWORDS)

    def _has_metrics(self, node: ast.ClassDef) -> bool:
        return self._has_feature_full_ast(node, METRICS_KEYWORDS)

    def _has_logging(self, node: ast.ClassDef) -> bool:
        return self._has_feature_full_ast(node, LOGGING_KEYWORDS)

    def _has_feature(self, node: ast.ClassDef, keywords: set[str]) -> bool:
        return self._has_feature_full_ast(node, keywords)

    # -------------------------------------------------------------------------
    # Component Detection
    # -------------------------------------------------------------------------
    def _is_outbox_component(self, node: ast.ClassDef, file_path: Path) -> tuple[bool, str]:
        name = node.name
        file_path_str = str(file_path).lower()

        if name.endswith(("Error", "Exception", "Config", "Port", "Interface", "Protocol")):
            return False, ""
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in ("Exception", "BaseException", "Enum"):
                return False, ""
            if isinstance(base, ast.Attribute) and base.attr in ("Exception", "BaseException", "Enum"):
                return False, ""

        if "Outbox" not in name and "outbox" not in file_path_str:
            return False, ""

        if any(kw in name for kw in ("Checkpoint", "Metrics", "Partition", "RelayMetrics", "KafkaPartition")):
            return False, ""

        if any(kw in name for kw in OUTBOX_DEADLETTER_KEYWORDS):
            return True, "deadletter"
        if any(kw in name for kw in OUTBOX_PUBLISHER_KEYWORDS):
            return True, "publisher"
        if any(kw in name for kw in OUTBOX_CONSUMER_KEYWORDS):
            return True, "consumer"
        if any(kw in name for kw in OUTBOX_REPO_KEYWORDS):
            return True, "repository"

        if name.endswith("Table"):
            fields, _ = self._get_fields_and_methods(node)
            has_tablename = any(
                isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in item.targets)
                for item in node.body
            )
            required_count = len(fields.intersection(REQUIRED_FIELDS))
            if has_tablename or required_count >= 3:
                return True, "entity"
            return False, ""

        fields, _ = self._get_fields_and_methods(node)
        required_count = len(fields.intersection(REQUIRED_FIELDS))
        if required_count >= 3:
            return True, "entity"

        return False, ""

    # -------------------------------------------------------------------------
    # Entity Checker (v14.2 - fixed OUT-014)
    # -------------------------------------------------------------------------
    def _check_entity(self, node: ast.ClassDef, file_path: Path) -> OutboxInfo:
        name = node.name
        fields, methods = self._get_fields_and_methods(node)
        violations = []
        rel_path = str(file_path.relative_to(self.root_dir))

        missing = REQUIRED_FIELDS - fields
        for f in list(missing):
            if self._has_mixin_field(node, f):
                missing.remove(f)
        if missing:
            violations.append(OutboxViolation(
                rule_id="OUT-002",
                file_path=rel_path,
                component_name=name,
                severity="CRITICAL",
                message=f"Entity '{name}' kehilangan field wajib: {', '.join(missing)}",
                suggestion="Tambahkan field: " + ", ".join(missing),
                line=node.lineno,
                rca_result=self._generate_rca("OUT-002", f"Missing required: {missing}", "CRITICAL"),
            ))

        if not any(f in fields for f in IDEMPOTENCY_ALIASES):
            violations.append(OutboxViolation(
                rule_id="OUT-008",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message=f"Entity '{name}' tidak memiliki field idempotency (idempotency_key/event_uuid/message_id/dedup_key/uuid/guid/event_id/hash/payload_hash/request_id/correlation_id/trace_id).",
                suggestion="Tambahkan salah satu field untuk deduplikasi.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-008", "Missing idempotency field", "MEDIUM"),
            ))

        has_timestamp = any(f in fields for f in TIMESTAMP_ALIASES) or self._has_mixin_field(node, "created_at")
        if not has_timestamp:
            violations.append(OutboxViolation(
                rule_id="OUT-002b",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message=f"Entity '{name}' tidak memiliki timestamp (created_at/occurred_at/event_time/timestamp/created) atau inheritance dari TimestampMixin.",
                suggestion="Tambahkan timestamp untuk polling & monitoring.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-002b", "Missing timestamp", "MEDIUM"),
            ))

        if not any(f in fields for f in EVENT_ID_ALIASES):
            violations.append(OutboxViolation(
                rule_id="OUT-003",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message=f"Entity '{name}' tidak memiliki event_id (event_id/event_uuid/event_uid/event_guid).",
                suggestion="Tambahkan event_id sebagai unique identifier per event.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-003", "Missing event_id", "MEDIUM"),
            ))

        if "retry_count" not in fields:
            violations.append(OutboxViolation(
                rule_id="OUT-006",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message=f"Entity '{name}' tidak memiliki 'retry_count'.",
                suggestion="Tambahkan retry_count untuk mendukung retry mechanism.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-006", "Missing retry_count", "MEDIUM"),
            ))

        # --- OUT-013: status enum ---
        status_is_enum = False
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "status":
                if item.value and isinstance(item.value, ast.Call) and self._is_enum_column(item.value):
                    status_is_enum = True
                    break
                if item.annotation:
                    ann_str = ast.unparse(item.annotation).lower()
                    if any(kw in ann_str for kw in ("enum", "saenum", "choice", "literal", "strenum", "mapped")):
                        status_is_enum = True
                        break
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "status":
                        if isinstance(item.value, ast.Call) and self._is_enum_column(item.value):
                            status_is_enum = True
                            break
                if status_is_enum:
                    break
        if "status" in fields and not status_is_enum:
            has_check = False
            for item in node.body:
                if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__table_args__" for t in item.targets):
                    val_str = ast.unparse(item.value).lower()
                    if "check" in val_str and "status" in val_str:
                        has_check = True
                        break
            if not has_check:
                violations.append(OutboxViolation(
                    rule_id="OUT-013",
                    file_path=rel_path,
                    component_name=name,
                    severity="MEDIUM",
                    message=f"Entity '{name}' memiliki field 'status' tapi bukan Enum/SAEnum/Mapped[Status]/ChoiceType/Literal/StrEnum, dan tidak ada CheckConstraint.",
                    suggestion="Gunakan Enum, SAEnum, ChoiceType, Literal, atau StrEnum untuk status.",
                    line=node.lineno,
                    rca_result=self._generate_rca("OUT-013", "Status not recognized enum type", "MEDIUM"),
                ))

        # --- OUT-014: status default (FIXED in v14.2) ---
        if "status" in fields:
            has_default_status = self._has_default_value(node, "status", "pending") or self._has_default_value(node, "status", "PENDING")
            if not has_default_status:
                violations.append(OutboxViolation(
                    rule_id="OUT-014",
                    file_path=rel_path,
                    component_name=name,
                    severity="LOW",
                    message=f"Entity '{name}' status tidak default 'pending'/'PENDING'.",
                    suggestion="Set default status = pending atau PENDING.",
                    line=node.lineno,
                    rca_result=self._generate_rca("OUT-014", "Missing default status", "LOW"),
                ))

        # --- OUT-015: retry_count default ---
        if "retry_count" in fields:
            has_default_retry = self._has_default_value(node, "retry_count", 0) or self._has_default_value(node, "retry_count", "0")
            if not has_default_retry:
                violations.append(OutboxViolation(
                    rule_id="OUT-015",
                    file_path=rel_path,
                    component_name=name,
                    severity="LOW",
                    message=f"Entity '{name}' retry_count tidak default 0.",
                    suggestion="Set default retry_count = 0.",
                    line=node.lineno,
                    rca_result=self._generate_rca("OUT-015", "Missing default retry_count", "LOW"),
                ))

        # --- OUT-016: payload type ---
        if "payload" in fields:
            is_valid = False
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "payload":
                    if item.annotation:
                        ann = ast.unparse(item.annotation).lower()
                        if any(t in ann for t in ("json", "dict", "mapping", "jsonb", "largebinary", "mapped", "mutabledict", "pydantic", "bytes", "text")):
                            is_valid = True
                            break
                    if item.value and isinstance(item.value, ast.Call):
                        try:
                            type_str = ast.unparse(item.value.args[0]).lower()
                            if any(t in type_str for t in ("json", "jsonb", "text", "dict", "mapping")):
                                is_valid = True
                                break
                        except Exception:
                            pass
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "payload":
                            if isinstance(item.value, ast.Call):
                                try:
                                    type_str = ast.unparse(item.value.args[0]).lower()
                                    if any(t in type_str for t in ("json", "jsonb", "text", "dict", "mapping")):
                                        is_valid = True
                                        break
                                except Exception:
                                    pass
            if not is_valid:
                violations.append(OutboxViolation(
                    rule_id="OUT-016",
                    file_path=rel_path,
                    component_name=name,
                    severity="LOW",
                    message=f"Entity '{name}' payload tidak dikenali sebagai JSON/dict/JSONB/Mapped/MutableDict/Pydantic/bytes/Text.",
                    suggestion="Gunakan JSONField, Mapped[dict], Pydantic model, atau Text.",
                    line=node.lineno,
                    rca_result=self._generate_rca("OUT-016", "Payload type not recognized", "LOW"),
                ))

        # LOW: aggregate_id, processed_at, last_error, version, indexes, NOT NULL
        if not any(f in fields for f in AGGREGATE_ID_ALIASES):
            violations.append(OutboxViolation(
                rule_id="OUT-004",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message=f"Entity '{name}' tidak memiliki aggregate_id (aggregate_id/aggregate_uuid/root_id).",
                suggestion="Tambahkan aggregate_id untuk traceability.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-004", "Missing aggregate_id", "LOW"),
            ))

        if "processed_at" not in fields:
            violations.append(OutboxViolation(
                rule_id="OUT-005",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message=f"Entity '{name}' tidak memiliki 'processed_at'.",
                suggestion="Tambahkan processed_at untuk mencatat waktu pemrosesan.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-005", "Missing processed_at", "LOW"),
            ))

        if "last_error" not in fields:
            violations.append(OutboxViolation(
                rule_id="OUT-007",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message=f"Entity '{name}' tidak memiliki 'last_error'.",
                suggestion="Tambahkan last_error untuk debugging.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-007", "Missing last_error", "LOW"),
            ))

        if "version" not in fields:
            violations.append(OutboxViolation(
                rule_id="OUT-010",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message=f"Entity '{name}' tidak memiliki 'version'.",
                suggestion="Tambahkan version untuk optimistic locking.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-010", "Missing version", "LOW"),
            ))

        # INFO: priority, scheduled_at, correlation_id
        for f, label in [("priority", "priority"), ("scheduled_at", "scheduled_at"), ("correlation_id", "correlation_id")]:
            if f not in fields:
                violations.append(OutboxViolation(
                    rule_id=f"OUT-{ {'priority':'011','scheduled_at':'012','correlation_id':'009'}[f] }",
                    file_path=rel_path,
                    component_name=name,
                    severity="INFO",
                    message=f"Entity '{name}' tidak memiliki '{f}'.",
                    suggestion=f"Tambahkan {f} ({label}).",
                    line=node.lineno,
                    rca_result=self._generate_rca(f"OUT-{ {'priority':'011','scheduled_at':'012','correlation_id':'009'}[f] }", f"Missing {f}", "INFO"),
                ))

        # LOW: indexes, NOT NULL
        has_indexes = any(
            isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("__table_args__", "Meta") for t in item.targets)
            for item in node.body
        )
        if not has_indexes:
            violations.append(OutboxViolation(
                rule_id="OUT-017",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message=f"Entity '{name}' tidak memiliki indeks (__table_args__).",
                suggestion="Tambahkan indeks pada (status, created_at) untuk polling.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-017", "Missing indexes", "LOW"),
            ))

        has_not_null = any(
            isinstance(item, ast.AnnAssign) and any(kw in ast.unparse(item.annotation).lower() for kw in ("nullable=false", "not null"))
            for item in node.body
        )
        if not has_not_null and missing:
            violations.append(OutboxViolation(
                rule_id="OUT-018",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message=f"Entity '{name}' tidak memiliki NOT NULL constraints.",
                suggestion="Tambahkan nullable=False atau NOT NULL.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-018", "Missing NOT NULL", "LOW"),
            ))

        return OutboxInfo(
            file_path=rel_path,
            component_name=name,
            component_type="entity",
            fields=fields,
            methods=methods,
            violations=violations,
        )

    # -------------------------------------------------------------------------
    # Publisher Checker (v14.0)
    # -------------------------------------------------------------------------
    def _check_publisher(self, node: ast.ClassDef, file_path: Path) -> OutboxInfo:
        name = node.name
        fields, methods = self._get_fields_and_methods(node)
        violations = []
        rel_path = str(file_path.relative_to(self.root_dir))

        if not self._has_main_method(node):
            violations.append(OutboxViolation(
                rule_id="OUT-026",
                file_path=rel_path,
                component_name=name,
                severity="CRITICAL",
                message=f"Publisher '{name}' tidak memiliki metode utama (publish/process/poll/run/start/loop/execute/worker/consume/relay/dispatch) ATAU loop dengan fetch event.",
                suggestion="Tambahkan metode utama atau loop yang mengambil pending events.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-026", "Missing main method", "CRITICAL"),
            ))

        if not self._has_retry(node):
            violations.append(OutboxViolation(
                rule_id="OUT-021",
                file_path=rel_path,
                component_name=name,
                severity="HIGH",
                message="Tidak ditemukan retry mechanism (tenacity/backoff/RetryPolicy/max_attempts/retry_delay_seconds/max_retries/retry_policy).",
                suggestion="Implementasikan retry dengan backoff atau max_attempts.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-021", "Missing retry", "HIGH"),
            ))

        if not self._has_idempotency(node):
            violations.append(OutboxViolation(
                rule_id="OUT-022",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message="Tidak ditemukan idempotency (idempotency_key/event_uuid/message_id/dedup_key/event_id/hash/payload_hash/request_id/correlation_id/trace_id) di field atau headers.",
                suggestion="Gunakan field idempotency untuk deduplikasi.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-022", "Missing idempotency", "MEDIUM"),
            ))

        if not self._has_transaction(node):
            violations.append(OutboxViolation(
                rule_id="OUT-020",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message="Tidak ditemukan transaction (UoW/session.begin/@transactional/@atomic/self.uow/container.uow/async with session/get_async_session).",
                suggestion="Gunakan UnitOfWork, session.begin(), atau @transactional untuk atomic operations.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-020", "Missing transaction", "MEDIUM"),
            ))

        if not self._has_dead_letter(node):
            violations.append(OutboxViolation(
                rule_id="OUT-041",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message="Tidak ditemukan Dead Letter Queue integration (dead_letter/dlq/DEAD_LETTER status/mark_dead_letter/OUTBOX_STATUS_DEAD_LETTER/_mark_as_failed).",
                suggestion="Kirim event gagal permanent ke DLQ.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-041", "No DLQ", "MEDIUM"),
            ))

        if not self._has_feature(node, BACKOFF_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-038",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message="Tidak ditemukan exponential backoff (backoff/exponential/retry_delay_seconds/list of delays).",
                suggestion="Gunakan backoff atau exponential untuk retry.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-038", "No backoff", "MEDIUM"),
            ))

        if not self._has_feature(node, TIMEOUT_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-037",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message="Tidak ditemukan timeout per event (timeout/asyncio.timeout).",
                suggestion="Tambahkan timeout untuk menghindari hung processing.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-037", "Missing timeout", "MEDIUM"),
            ))

        if not self._has_feature(node, {"max_retry", "max_retries", "max_attempts"}):
            violations.append(OutboxViolation(
                rule_id="OUT-039",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message="Tidak ditemukan configurable max_retries.",
                suggestion="Tambahkan parameter max_retries.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-039", "No max_retries", "MEDIUM"),
            ))

        if not self._has_lock(node):
            violations.append(OutboxViolation(
                rule_id="OUT-030",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan pessimistic locking (select_for_update/with_for_update/redis.lock/advisory_lock/distributed_lock/asyncio.Lock/Semaphore/Lease/setnx/expire/_acquire_lock/try_lock).",
                suggestion="Gunakan lock untuk mencegah duplicate processing.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-030", "Missing lock", "LOW"),
            ))

        if not self._has_broker_api(node):
            violations.append(OutboxViolation(
                rule_id="OUT-042",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan Broker API / MessagePublisher / Dispatcher / Mediator (KafkaProducerWrapper/Kafka/RabbitMQ/Pulsar/EventBus/BrokerPort/producer/publisher/send_event/get_kafka_producer/MessageBrokerPort).",
                suggestion="Integrasikan dengan message broker API (KafkaProducerWrapper, RabbitMQ, PulsarClient, atau BrokerPort).",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-042", "Broker API not found", "LOW"),
            ))

        if not self._has_batch(node):
            violations.append(OutboxViolation(
                rule_id="OUT-028",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan batch processing (batch_size/limit).",
                suggestion="Tambahkan parameter limit atau batch_size.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-028", "No batch", "LOW"),
            ))

        if not self._has_ordering(node):
            violations.append(OutboxViolation(
                rule_id="OUT-029",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan ordering (order_by/asc/desc/created_at).",
                suggestion="Tambahkan order_by(created_at.asc()) untuk FIFO.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-029", "Missing ordering", "LOW"),
            ))

        if not self._has_feature(node, SHUTDOWN_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-031",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan graceful shutdown (stop/shutdown/close).",
                suggestion="Tambahkan shutdown() atau stop().",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-031", "No shutdown", "LOW"),
            ))

        if not self._has_health(node):
            violations.append(OutboxViolation(
                rule_id="OUT-032",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan health check (health/ready/liveness/readiness/health_check).",
                suggestion="Tambahkan health_check() atau readiness/liveness.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-032", "No health", "LOW"),
            ))

        if not self._has_metrics(node):
            violations.append(OutboxViolation(
                rule_id="OUT-033",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan metrics collection (Counter/Histogram/Gauge/MeterProvider/Meter/OpenTelemetry/prometheus).",
                suggestion="Tambahkan Counter, Histogram, Gauge, atau OpenTelemetry metrics.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-033", "No metrics", "LOW"),
            ))

        if not self._has_logging(node):
            violations.append(OutboxViolation(
                rule_id="OUT-034",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan logging (get_logger/logger/logging/structlog/audit_logger).",
                suggestion="Tambahkan logging untuk setiap publish attempt.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-034", "No logging", "LOW"),
            ))

        if not self._has_feature(node, ASYNC_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-044",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan async processing.",
                suggestion="Gunakan async/await atau background thread.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-044", "No async", "LOW"),
            ))

        if not self._has_feature(node, SCHEMA_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-045",
                file_path=rel_path,
                component_name=name,
                severity="LOW",
                message="Tidak ditemukan payload validation (schema/validate/pydantic/ValidationError/BaseModel).",
                suggestion="Validasi payload schema sebelum publish.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-045", "No schema validation", "LOW"),
            ))

        if not self._has_feature(node, CIRCUIT_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-035",
                file_path=rel_path,
                component_name=name,
                severity="INFO",
                message="Tidak ditemukan circuit breaker.",
                suggestion="Implementasikan circuit breaker untuk cascade failure.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-035", "No circuit breaker", "INFO"),
            ))

        if not self._has_feature(node, RATE_LIMIT_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-036",
                file_path=rel_path,
                component_name=name,
                severity="INFO",
                message="Tidak ditemukan rate limiting.",
                suggestion="Tambahkan rate limit untuk mencegah overload.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-036", "No rate limit", "INFO"),
            ))

        if not self._has_feature(node, ERROR_CLASS_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-040",
                file_path=rel_path,
                component_name=name,
                severity="INFO",
                message="Tidak ditemukan error classification (temporary/permanent/retryable).",
                suggestion="Bedakan temporary vs permanent error.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-040", "No error classification", "INFO"),
            ))

        if not self._has_feature(node, RECONNECT_KEYWORDS):
            violations.append(OutboxViolation(
                rule_id="OUT-043",
                file_path=rel_path,
                component_name=name,
                severity="INFO",
                message="Tidak ditemukan auto-reconnect mechanism.",
                suggestion="Implementasikan auto-reconnect untuk broker.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-043", "No auto-reconnect", "INFO"),
            ))

        return OutboxInfo(
            file_path=rel_path,
            component_name=name,
            component_type="publisher",
            fields=fields,
            methods=methods,
            has_transaction=self._has_transaction(node),
            has_retry=self._has_retry(node),
            has_idempotency=self._has_idempotency(node),
            has_dead_letter=self._has_dead_letter(node),
            has_monitoring=self._has_metrics(node),
            has_health=self._has_health(node),
            has_logging=self._has_logging(node),
            has_lock=self._has_lock(node),
            has_batch=self._has_batch(node),
            has_ordering=self._has_ordering(node),
            has_shutdown=self._has_feature(node, SHUTDOWN_KEYWORDS),
            has_async=self._has_feature(node, ASYNC_KEYWORDS),
            has_schema_validation=self._has_feature(node, SCHEMA_KEYWORDS),
            has_circuit_breaker=self._has_feature(node, CIRCUIT_KEYWORDS),
            has_rate_limit=self._has_feature(node, RATE_LIMIT_KEYWORDS),
            has_timeout=self._has_feature(node, TIMEOUT_KEYWORDS),
            has_backoff=self._has_feature(node, BACKOFF_KEYWORDS),
            has_max_retries=self._has_feature(node, {"max_retry", "max_retries", "max_attempts"}),
            has_error_classification=self._has_feature(node, ERROR_CLASS_KEYWORDS),
            has_auto_reconnect=self._has_feature(node, RECONNECT_KEYWORDS),
            has_broker_integration=self._has_broker_api(node),
            violations=violations,
        )

    # -------------------------------------------------------------------------
    # Consumer Checker
    # -------------------------------------------------------------------------
    def _check_consumer(self, node: ast.ClassDef, file_path: Path) -> OutboxInfo:
        name = node.name
        fields, methods = self._get_fields_and_methods(node)
        violations = []
        rel_path = str(file_path.relative_to(self.root_dir))

        if "handle" not in methods and "on_event" not in methods and "consume" not in methods:
            violations.append(OutboxViolation(
                rule_id="OUT-046",
                file_path=rel_path,
                component_name=name,
                severity="CRITICAL",
                message=f"Consumer '{name}' tidak memiliki 'handle' atau 'on_event' atau 'consume'.",
                suggestion="Tambahkan handle(event) untuk memproses event.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-046", "Missing handle", "CRITICAL"),
            ))

        if not self._has_idempotency(node):
            violations.append(OutboxViolation(
                rule_id="OUT-047",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message=f"Consumer '{name}' tidak memiliki idempotency.",
                suggestion="Implementasikan idempotency untuk mencegah duplikasi.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-047", "No idempotency", "MEDIUM"),
            ))

        if not self._has_feature(node, {"try", "except"}):
            violations.append(OutboxViolation(
                rule_id="OUT-048",
                file_path=rel_path,
                component_name=name,
                severity="MEDIUM",
                message=f"Consumer '{name}' tidak memiliki error handling.",
                suggestion="Tambahkan try/except untuk menangani kegagalan.",
                line=node.lineno,
                rca_result=self._generate_rca("OUT-048", "No error handling", "MEDIUM"),
            ))

        return OutboxInfo(
            file_path=rel_path,
            component_name=name,
            component_type="consumer",
            fields=fields,
            methods=methods,
            has_idempotency=self._has_idempotency(node),
            violations=violations,
        )

    # -------------------------------------------------------------------------
    # Main Scan
    # -------------------------------------------------------------------------
    def scan(self) -> list[OutboxInfo]:
        self.components = []
        for file_path in self._get_python_files():
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(file_path))
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                is_outbox, comp_type = self._is_outbox_component(node, file_path)
                if not is_outbox:
                    continue

                if comp_type == "entity":
                    info = self._check_entity(node, file_path)
                elif comp_type == "publisher":
                    info = self._check_publisher(node, file_path)
                elif comp_type == "consumer":
                    info = self._check_consumer(node, file_path)
                else:
                    fields, methods = self._get_fields_and_methods(node)
                    rel_path = str(file_path.relative_to(self.root_dir))
                    info = OutboxInfo(
                        file_path=rel_path,
                        component_name=node.name,
                        component_type=comp_type,
                        fields=fields,
                        methods=methods,
                        violations=[]
                    )

                if info:
                    self.components.append(info)

        return self.components


# =============================================================================
# REPORTING (v14.2)
# =============================================================================

def generate_report(components: list[OutboxInfo]) -> CheckerResult:
    total = len(components)
    total_violations = 0
    critical = high = medium = low = info = 0

    for comp in components:
        total_violations += len(comp.violations)
        for v in comp.violations:
            if v.severity == "CRITICAL":
                critical += 1
            elif v.severity == "HIGH":
                high += 1
            elif v.severity == "MEDIUM":
                medium += 1
            elif v.severity == "LOW":
                low += 1
            else:
                info += 1

    score = 100.0
    score -= critical * 15.0
    score -= high * 6.0
    score -= medium * 2.0
    score -= low * 0.5
    score = max(0.0, min(100.0, score))

    return CheckerResult(
        components=components,
        total_components=total,
        total_violations=total_violations,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        info_count=info,
        score=score,
        rca_enabled=_RCA_AVAILABLE,
        elapsed_seconds=0.0,
    )


def print_report(result: CheckerResult, verbose: bool = False) -> None:
    c = COLOR
    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║     OUTBOX PATTERN COMPLIANCE & FORENSIC CHECKER v14.2     ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print("\n  📋 Aturan Outbox (v14.2 – fixed OUT-014 default detection):")
    print("    ✅ AST-based: get_async_session, self.uow, session.begin")
    print("    ✅ AST-based: Column(Enum) detection for status")
    print("    ✅ AST-based: default= and server_default= detection (including attribute refs)")
    print("    ✅ Scoring: CRITICAL=-15, HIGH=-6, MEDIUM=-2, LOW=-0.5, INFO=0")

    print(f"\n  {c['CYAN']}Total Outbox Components Ditemukan: {result.total_components}{c['RESET']}")
    print(f"  Total Violations: {result.total_violations}")
    print(f"    {c['RED']}CRITICAL: {result.critical_count}{c['RESET']}")
    print(f"    {c['YELLOW']}HIGH: {result.high_count}{c['RESET']}")
    print(f"    {c['CYAN']}MEDIUM: {result.medium_count}{c['RESET']}")
    print(f"    {c['DIM']}LOW: {result.low_count}{c['RESET']}")
    print(f"    {c['DIM']}INFO: {result.info_count}{c['RESET']}")

    score_color = c["GREEN"] if result.score >= 80 else c["YELLOW"] if result.score >= 50 else c["RED"]
    print(f"\n  📈 Skor Kepatuhan: {score_color}{c['BOLD']}{result.score:.1f}/100{c['RESET']}")
    print(f"  RCA Engine: {'✅ Aktif' if result.rca_enabled else '⚠️ Tidak tersedia'}")

    if result.components:
        print(f"\n{c['CYAN']}─── DAFTAR KOMPONEN ───{c['RESET']}")
        for comp in result.components:
            if comp.violations:
                status = f"{c['RED']}✖ {len(comp.violations)} violations{c['RESET']}"
            else:
                status = f"{c['GREEN']}✓ Compliant{c['RESET']}"
            print(f"  {comp.component_name} ({comp.component_type}) @ {comp.file_path} {status}")

    all_violations = []
    for comp in result.components:
        all_violations.extend(comp.violations)

    if all_violations:
        print(f"\n{c['RED']}─── VIOLATIONS (sample) ───{c['RESET']}")
        for v in all_violations[:30]:
            sev_color = c["RED"] if v.severity in ("CRITICAL", "HIGH") else c["YELLOW"] if v.severity == "MEDIUM" else c["CYAN"]
            print(f"\n  {sev_color}[{v.rule_id}] {v.severity}{c['RESET']} {v.message}")
            print(f"    💡 {v.suggestion}")
            if verbose and v.rca_result:
                if v.rca_result.get("root_cause"):
                    print(f"    🔍 RCA: {v.rca_result['root_cause'][:150]}")
                if v.rca_result.get("suggested_fix"):
                    print(f"    🔧 Fix: {v.rca_result['suggested_fix'][:150]}")
        if len(all_violations) > 30:
            print(f"  ... and {len(all_violations)-30} more violations (use --json for full list)")


def save_json(result: CheckerResult, filepath: str) -> None:
    try:
        out = Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "score": result.score,
            "rca_enabled": result.rca_enabled,
            "total_components": result.total_components,
            "total_violations": result.total_violations,
            "severity_counts": {
                "critical": result.critical_count,
                "high": result.high_count,
                "medium": result.medium_count,
                "low": result.low_count,
                "info": result.info_count,
            },
            "components": [
                {
                    "name": comp.component_name,
                    "type": comp.component_type,
                    "file": comp.file_path,
                    "fields": list(comp.fields),
                    "methods": list(comp.methods),
                    "has_transaction": comp.has_transaction,
                    "has_retry": comp.has_retry,
                    "has_idempotency": comp.has_idempotency,
                    "has_dead_letter": comp.has_dead_letter,
                    "has_monitoring": comp.has_monitoring,
                    "violations": [v.to_dict() for v in comp.violations],
                }
                for comp in result.components
            ],
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{COLOR['GREEN']}✅ JSON exported to {out.resolve()}{COLOR['RESET']}")
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to write JSON: {e}{COLOR['RESET']}")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Outbox Pattern Compliance & Forensic Checker v14.2 (fix OUT-014)"
    )
    parser.add_argument("--json", metavar="FILE", help="Export report to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show RCA details")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    args = parser.parse_args()

    global _RCA_AVAILABLE, _analyze_exception
    if args.no_rca:
        _RCA_AVAILABLE = False
        _analyze_exception = None

    start = time.monotonic()
    checker = OutboxChecker(ROOT, enable_rca=not args.no_rca)
    components = checker.scan()
    elapsed = time.monotonic() - start

    result = generate_report(components)
    result.elapsed_seconds = elapsed

    print_report(result, verbose=args.verbose)

    if args.json:
        save_json(result, args.json)

    print(f"\n ⏱️ Audit Duration: {elapsed:.3f} seconds")

    has_critical = result.critical_count > 0
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()
