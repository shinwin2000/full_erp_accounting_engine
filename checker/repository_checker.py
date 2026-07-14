#!/usr/bin/env python3
"""
Sovereign ERP System — Repository Contract Checker
====================================================
Versi   : 7.1.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Changelog v7.1.0:
  FIX-61  _is_likely_implementation_file: izinkan file di folder ports/
          sehingga implementasi konkret seperti InMemoryFileStorage dan
          InMemoryNotification dapat ditemukan oleh checker.
  FIX-62  scan_repositories: tambahkan ports/primary dan ports/secondary
          ke default_impl_dirs agar file port di-scan untuk implementasi.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import logging
import math
import os
import pathlib
import re
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ─── RCA INTEGRATION ─────────────────────────────────────────────────────────
_RCA_ENGINE  = None
_RCA_AVAILABLE = False


def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    _candidates = [
        lambda: __import__("checker.core.rca", fromlist=["get_engine"]),
        lambda: __import__("rca"),
    ]
    _root = pathlib.Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    for loader in _candidates:
        try:
            mod = loader()
            _RCA_ENGINE    = mod.get_engine()
            _RCA_AVAILABLE = True
            return True
        except Exception:
            continue
    return False


_init_rca()


def _rca_analyze(exc: Exception, context: dict | None = None) -> dict | None:
    if not _RCA_AVAILABLE or _RCA_ENGINE is None:
        return {
            "severity"     : "WARNING",
            "root_cause"   : str(exc)[:200],
            "suggested_fix": "Install checker/core/rca.py for full RCA",
            "confidence"   : 0.0,
        }
    try:
        r = _RCA_ENGINE.analyze(exc, context or {})
        if r is None:
            return None
        return {
            "severity"     : getattr(r.severity, "value", str(r.severity)),
            "error_code"   : getattr(r.error_code, "value", str(getattr(r, "error_code", ""))),
            "root_cause"   : getattr(r, "root_cause", ""),
            "evidence"     : getattr(r, "evidence", [])[:5],
            "impact"       : getattr(r, "impact", [])[:3],
            "suggested_fix": getattr(r, "suggested_fix", ""),
            "confidence"   : float(getattr(r, "confidence", 0.0)),
        }
    except Exception:
        return None


# ─── LOGGING ─────────────────────────────────────────────────────────────────
logger = logging.getLogger("repository_checker")
logger.setLevel(logging.WARNING)
logger.propagate = False
if not logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_h)

# ─── COLOR ───────────────────────────────────────────────────────────────────
_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR", "") == ""
    and os.environ.get("TERM", "") != "dumb"
)
_COLORS = {
    "RED": "\033[91m", "GREEN": "\033[92m", "YELLOW": "\033[93m",
    "BLUE": "\033[94m", "CYAN": "\033[96m", "MAGENTA": "\033[95m",
    "BOLD": "\033[1m",  "DIM": "\033[2m",   "RESET": "\033[0m",
}


def _c(k: str) -> str:
    return _COLORS.get(k, "") if _COLOR else ""


def _safe_print(*args, **kwargs) -> None:
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [
            a.encode("ascii", errors="replace").decode("ascii") if isinstance(a, str) else a
            for a in args
        ]
        print(*safe_args, **kwargs)


# ─── VERSION ─────────────────────────────────────────────────────────────────
__version__ = "7.1.0"
_DEFAULT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ═════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

EXCLUDED_DIRS: frozenset[str] = frozenset({
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    ".venv", "venv", "node_modules", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", ".tox", "build", "dist",
})

_INFRA_PURE_TECH_PREFIXES: frozenset[str] = frozenset({
    "redis", "kafka", "s3", "glacier", "minio",
    "smtp", "slack", "whatsapp", "pagerduty",
    "hsm", "hashicorp", "memcached", "elasticsearch",
    "rabbitmq", "sqs", "sendgrid", "mailgun", "pkcs",
    "asyncpg", "pgbouncer",
    "bank",
})

_INFRA_ANYWHERE_KW: frozenset[str] = frozenset({
    "kafka", "glacier", "minio", "slack", "pagerduty",
    "hashicorp", "hsm", "elasticsearch", "rabbitmq", "mt940",
})

_INFRA_STRUCTURAL_SIGNALS: frozenset[str] = frozenset({
    "appendonly", "snapshotstore", "eventstore", "appendonlystore",
    "deadletter", "coldstore", "coldstorage",
})

_DOMAIN_MIN4: frozenset[str] = frozenset({
    "customer", "supplier", "vendor", "taxtransaction", "taxation",
    "account", "journal", "ledger", "invoice", "payment", "receipt",
    "employee", "payroll", "salary", "inventory", "warehouse", "stock",
    "budget", "forecast", "project", "task", "fixedasset",
    "intangibleasset", "goodwill", "forex", "currency", "exchange",
    "hedge", "consolidation", "intercompany", "legalentity", "company",
    "purchaseorder", "salesorder", "goodsreceipt", "workorder",
    "manufacturing", "report", "trialbalance", "cashflow",
    "balancesheet", "incomestatement", "generalledger", "bankaccount",
    "cashbook", "bankstatement", "umkm", "outbox", "systemsetting",
    "fiscalperiod", "approval", "auditevent", "notification", "coretax",
    "unitofwork", "timestampnotary", "hashchain", "saga", "sales",
    "subledger", "faktur", "intangible", "aml", "iam", "spt",
    "file", "storage", "event", "publisher", "aging", "bucket", "snapshot", "projection",
    "query", "handler", "uow",
    "valuation",
    "sagastore", "sagastate",
    "statement", "import",
})

INFRASTRUCTURE_KEYWORDS: frozenset[str] = _INFRA_ANYWHERE_KW | _INFRA_PURE_TECH_PREFIXES
DOMAIN_OVERRIDE_KEYWORDS: frozenset[str] = _DOMAIN_MIN4

IFACE_SUFFIXES: tuple[str, ...] = (
    "RepositoryPortProtocol",
    "PortProtocol",
    "RepositoryPort",
    "Repository",
    "Port",
    "Protocol",
    "Store",
    "Cache",
    "Interface",
    "Abstract",
)

IMPL_TECH_PREFIXES: tuple[str, ...] = (
    "SQLAlchemy",
    "Postgres", "AsyncPG", "PG",
    "InMemory", "Memory",
    "Hashicorp",
    "S3", "MinIO", "Glacier",
    "Redis",
    "Kafka", "RabbitMQ",
    "Email", "SMTP", "SendGrid",
    "Slack", "WhatsApp", "Telegram",
    "PagerDuty",
    "HSM", "PKCS",
    "Async", "Sync",
    "Mock", "Fake", "Stub",
    "Local", "Remote",
)

IMPL_SUFFIXES: tuple[str, ...] = (
    "PortImpl", "Adapter", "Impl", "Repository", "Store", "Cache",
    "Channel", "Handler", "Projection", "Service", "Gateway", "Manager",
)

COSMETIC_PARAM_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"keyword", "name_fragment"}),
    frozenset({"keyword", "search_term"}),
    frozenset({"keyword", "query"}),
    frozenset({"entity_id", "id"}),
    frozenset({"po_id", "purchase_order_id"}),
    frozenset({"csv_content", "csv_data"}),
    frozenset({"plain_password", "password"}),
    frozenset({"tax_id", "tax_id_number"}),
    frozenset({"parent_entity_id", "parent_company_id"}),
    frozenset({"session_token", "token"}),
    frozenset({"session_id", "token"}),
    frozenset({"file_uri", "key"}),
    frozenset({"expiration_seconds", "expires_in"}),
    frozenset({"operation", "method"}),
    frozenset({"interval_hours", "interval_seconds"}),
    frozenset({"new_content", "data"}),
    frozenset({"uploaded_by", "metadata"}),
    frozenset({"limit", "max_results"}),
    frozenset({"offset", "skip"}),
    frozenset({"data", "tax_data"}),
    frozenset({"report_id", "output_id"}),
    frozenset({"report_type", "definition_id"}),
    frozenset({"params", "parameters"}),
    frozenset({"transaction_number", "so_number"}),
    frozenset({"transaction_number", "po_number"}),
    frozenset({"transaction_number", "doc_number"}),
})

SEMANTIC_MISMATCH_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"user_id", "submitted_by"}),
    frozenset({"user_id", "created_by"}),
    frozenset({"user_id", "approved_by"}),
    frozenset({"user_id", "reversed_by"}),
    frozenset({"user_id", "disputed_by"}),
    frozenset({"approver_id", "approved_by"}),
    frozenset({"start_date", "from_date"}),
    frozenset({"end_date", "to_date"}),
    frozenset({"role_code", "role_id"}),
    frozenset({"expires_in_hours", "session_timeout_hours"}),
    frozenset({"actor_id", "created_by"}),
    frozenset({"user_id_actor", "actor_id"}),
    frozenset({"as_of_date", "cutoff_date"}),
    frozenset({"resign_date", "resignation_date"}),
    frozenset({"start_date", "month"}),
    frozenset({"end_date", "year"}),
    frozenset({"emp_status", "status"}),
    frozenset({"department_id", "department"}),
    frozenset({"rotation_days", "interval_days"}),
    frozenset({"old_version", "new_wrapping_key_id"}),
    frozenset({"prev_hash", "algorithm"}),
    frozenset({"user_id", "reason"}),
})

_BARE_GENERIC_TYPES: frozenset[str] = frozenset({"list", "dict", "set", "tuple", "sequence"})

COMPATIBLE_TYPE_SUFFIXES: tuple[str, ...] = (
    "Aggregate", "AggregateRoot", "Entity", "Model", "Table",
    "ORM", "Row", "DTO", "Dto", "Record", "Document", "Schema",
)

GRADE_THRESHOLDS = [
    (97, "AAA", "GREEN"),
    (90, "AA",  "GREEN"),
    (85, "A",   "GREEN"),
    (75, "B",   "YELLOW"),
    (65, "C",   "YELLOW"),
    (50, "D",   "RED"),
    (0,  "F",   "RED"),
]

ALLOWED_DUPLICATE_NAMES: frozenset[str] = frozenset({
    "ExchangeRateCreateSchema", "ExchangeRateUpdateSchema", "ExchangeRateResponseSchema",
    "CurrencyConversionRequestSchema", "CurrencyConversionResponseSchema",
    "BatchConversionRequestSchema", "BatchConversionResponseSchema",
    "HistoricalRateResponseSchema",
    "ConsolidationGroupCreateSchema", "ConsolidationGroupResponseSchema",
    "AccountBalanceHistorySchema", "AccountBalanceResponseSchema",
    "SPTRepositoryPort", "_FallbackSPTRepository",
    "DomainEvent", "DomainEventType",
    "_FallbackJournalRepository", "_FallbackTransactionRepository", "_FallbackUserRepository",
})

# ═════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class MethodInfo:
    name:               str
    required_count:     int
    kwonly_count:       int
    total_count:        int
    is_async:           bool
    is_abstract:        bool
    is_property:        bool
    is_static:          bool
    lineno:             int
    param_names:        list[str]       = field(default_factory=list)
    param_defaults:     dict[str, str]  = field(default_factory=dict)
    return_annotation:  str             = ""
    raises_annotations: list[str]       = field(default_factory=list)
    docstring:          str             = ""


@dataclass
class InterfaceInfo:
    name:             str
    file_path:        str
    module:           str
    methods:          dict[str, MethodInfo]
    base_name:        str
    has_abc:          bool = False
    is_protocol_dup:  bool = False
    is_self_implemented: bool = False


@dataclass
class ImplementationInfo:
    name:              str
    file_path:         str
    module:            str
    methods:           dict[str, MethodInfo]
    is_infrastructure: bool       = False
    base_name:         str        = ""
    extra_methods:     list[str]  = field(default_factory=list)
    declared_bases:    list[str]  = field(default_factory=list)


@dataclass
class Violation:
    severity:       str
    interface:      str
    implementation: str
    message:        str
    detail:         str         = ""
    rule_id:        str         = ""
    fix_snippet:    str         = ""
    rca:            dict | None = None


@dataclass
class DuplicateEntry:
    name:             str
    kind:             str
    definition_files: list[str]
    recommendation:   str = ""


@dataclass
class ScoreBreakdown:
    coverage_score:          float
    coverage_grade:          str
    coverage_color:          str
    quality_score:           float
    quality_grade:           str
    quality_color:           str
    matched_count:           int
    total_interfaces:        int
    countable_interfaces:    int
    error_free_matched:      int
    avg_error_per_matched:   float
    avg_warning_per_matched: float
    interpretation:          str


@dataclass
class CheckerResult:
    interfaces:            list[InterfaceInfo]
    implementations:       list[ImplementationInfo]
    infrastructure_impls:  list[str]
    matched:               list[tuple[str, str]]
    unmatched_interfaces:  list[str]
    unmatched_impls:       list[str]
    violations:            list[Violation]
    total_errors:          int
    total_warnings:        int
    total_infos:           int
    score_breakdown:       ScoreBreakdown
    duplicates:            list[DuplicateEntry]
    audit_timestamp:       str
    elapsed_seconds:       float
    strict_types:          bool
    rca_results:           list[dict[str, Any]] = field(default_factory=list)


# ═════════════════════════════════════════════════════════════════════════════
#  AST UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

_AST_CACHE: dict[str, tuple[ast.AST | None, str | None]] = {}
_CACHE_LOCK = threading.Lock()


def _read_source(py_file: pathlib.Path) -> str | None:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            raw = py_file.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            return raw.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError, OSError):
            continue
    try:
        return py_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _get_ast(py_file: pathlib.Path) -> tuple[ast.AST | None, str | None]:
    key = str(py_file.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    src = _read_source(py_file)
    if src is None:
        result = (None, "Cannot read file")
    else:
        try:
            tree   = ast.parse(src, filename=str(py_file))
            result = (tree, None)
        except SyntaxError as e:
            result = (None, f"SyntaxError at {e.lineno}: {e.msg}")
        except Exception as e:
            result = (None, f"{type(e).__name__}: {e}")
    with _CACHE_LOCK:
        _AST_CACHE[key] = result
    return result


def _ann(node: ast.expr | None) -> str:
    if node is None:
        return ""
    if hasattr(ast, "unparse"):
        try:
            return ast.unparse(node)
        except Exception:
            pass
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_ann(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return f"{_ann(node.value)}[{_ann(node.slice)}]"
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.BinOp):
        return f"{_ann(node.left)} | {_ann(node.right)}"
    if isinstance(node, ast.Tuple):
        return "(" + ", ".join(_ann(e) for e in node.elts) + ")"
    return type(node).__name__


def _default_str(node: ast.expr | None) -> str:
    if node is None:
        return "None"
    if hasattr(ast, "unparse"):
        try:
            return ast.unparse(node)
        except Exception:
            pass
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return "?"


def _normalize_return_type(t: str) -> str:
    if not t:
        return ""
    t = t.strip()
    t = re.sub(r'\bList\b', 'list', t)
    t = re.sub(r'\bDict\b', 'dict', t)
    t = re.sub(r'\bTuple\b', 'tuple', t)
    t = re.sub(r'\bSet\b', 'set', t)
    t = re.sub(r'\bSequence\b', 'list', t)
    t = re.sub(r'\bIterable\b', 'list', t)
    t = re.sub(r'Optional\[([^\]]+)\]', r'\1 | None', t)
    t = re.sub(r'\s+', '', t)
    return t


def _extract_base_type(t: str) -> str:
    t = t.strip()
    t = re.sub(r'\s*\|\s*None\s*$', '', t)
    t = re.sub(r'^Optional\[(.+)\]$', r'\1', t)
    m = re.match(r'^\w+\[(.+)\]$', t)
    if m:
        return _extract_base_type(m.group(1).split(',')[0].strip())
    return t


def _types_compatible(iface_type: str, impl_type: str) -> bool:
    ni = _normalize_return_type(iface_type)
    nm = _normalize_return_type(impl_type)
    if ni == nm:
        return True
    ni_stripped = re.sub(r'\s*\|\s*None\s*$', '', ni).strip().lower()
    nm_stripped = re.sub(r'\s*\|\s*None\s*$', '', nm).strip().lower()
    if ni_stripped == 'any':
        return True
    if nm_stripped == 'any':
        return True
    def _inner_type_lower(t: str) -> str:
        import re as _re
        m = _re.match(r'^\w+\[(.+)\]$', t.strip())
        return m.group(1).lower() if m else ''
    inner_i = _inner_type_lower(ni_stripped)
    inner_m = _inner_type_lower(nm_stripped)
    if inner_i == 'any' and inner_m:
        return True
    if inner_m == 'any' and inner_i:
        return True
    bi = _extract_base_type(ni).lower()
    bm = _extract_base_type(nm).lower()
    if bi in _BARE_GENERIC_TYPES and bm in _BARE_GENERIC_TYPES:
        if bi == bm or bi.startswith(bm) or bm.startswith(bi):
            return True
    if nm in _BARE_GENERIC_TYPES and ni.startswith(nm + "["):
        return True
    if ni in _BARE_GENERIC_TYPES and nm.startswith(ni + "["):
        return True
    base_i = _extract_base_type(iface_type)
    base_m = _extract_base_type(impl_type)
    if base_i == base_m:
        return True
    for suffix in COMPATIBLE_TYPE_SUFFIXES:
        if base_m == base_i + suffix or base_i == base_m + suffix:
            return True
    return False


def _type_mismatch_is_real(iface_type: str, impl_type: str) -> bool:
    SEMANTICALLY_COMPATIBLE: frozenset[frozenset[str]] = frozenset({
        frozenset({"BinaryIO", "bytes"}),
        frozenset({"IO[bytes]", "bytes"}),
        frozenset({"None", "bool"}),
        frozenset({"int", "Decimal"}),
        frozenset({"dict[str,Any]", "dict"}),
        frozenset({"dict[str,Any]", "KeyMetadata"}),
        frozenset({"dict[str,Any]", "list[dict]"}),
        frozenset({"dict[str,any]", "list[dict]"}),
        frozenset({"None", "Any"}),
        frozenset({"None", "dict[str,Any]"}),
    })
    ni = _normalize_return_type(iface_type).lower()
    nm = _normalize_return_type(impl_type).lower()
    pair = frozenset({ni, nm})
    for compat_pair in SEMANTICALLY_COMPATIBLE:
        norm_compat = frozenset(x.lower() for x in compat_pair)
        if pair == norm_compat:
            return False
    return not _types_compatible(iface_type, impl_type)


def _get_decorators(func_node: Any) -> set[str]:
    names: set[str] = set()
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name):
            names.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.add(dec.attr)
    return names


def _get_class_bases(node: ast.ClassDef) -> list[str]:
    result = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            result.append(base.id)
        elif isinstance(base, ast.Attribute):
            result.append(base.attr)
        else:
            try:
                result.append(ast.unparse(base))
            except Exception:
                pass
    return result


def extract_methods_from_class(
    tree: ast.AST,
    class_name: str,
) -> dict[str, MethodInfo]:
    methods: dict[str, MethodInfo] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            mname = item.name
            if mname == "__init__":
                continue
            if mname.startswith("_") and not (mname.startswith("__") and mname.endswith("__")):
                continue
            decs       = _get_decorators(item)
            is_prop    = "property" in decs
            is_abs     = "abstractmethod" in decs
            is_static  = "staticmethod" in decs
            is_async   = isinstance(item, ast.AsyncFunctionDef)

            args = item.args
            pos_args = args.args
            offset   = 1 if (pos_args and pos_args[0].arg in ("self", "cls")) else 0
            pos_args = pos_args[offset:]
            n_pos    = len(pos_args)
            n_defs   = len(args.defaults)
            required = max(0, n_pos - n_defs)

            param_names = [a.arg for a in pos_args]
            defs_aligned = [None] * (n_pos - n_defs) + list(args.defaults)
            param_defaults: dict[str, str] = {
                a.arg: _default_str(defs_aligned[i])
                for i, a in enumerate(pos_args)
                if defs_aligned[i] is not None
            }

            return_ann = _ann(item.returns)
            docstring  = ""
            if (item.body
                    and isinstance(item.body[0], ast.Expr)
                    and isinstance(item.body[0].value, ast.Constant)
                    and isinstance(item.body[0].value.value, str)):
                docstring = item.body[0].value.value

            raises = _extract_raises_from_docstring(docstring)

            methods[mname] = MethodInfo(
                name=mname,
                required_count=required,
                kwonly_count=len(args.kwonlyargs),
                total_count=n_pos,
                is_async=is_async,
                is_abstract=is_abs,
                is_property=is_prop,
                is_static=is_static,
                lineno=item.lineno,
                param_names=param_names,
                param_defaults=param_defaults,
                return_annotation=return_ann,
                raises_annotations=raises,
                docstring=docstring,
            )
        break
    return methods


def _extract_raises_from_docstring(docstring: str) -> list[str]:
    raises = []
    for line in docstring.splitlines():
        m = re.match(r'(?:Raises?|:raises?)\s*[:\s]\s*(\w+)', line.strip(), re.I)
        if m:
            raises.append(m.group(1))
    return raises


def _class_has_abc_base(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in ("ABC", "Protocol"):
            return True
        if isinstance(base, ast.Attribute) and base.attr in ("ABC", "Protocol"):
            return True
    return False


def _should_exclude_path(path: pathlib.Path, root: pathlib.Path, extra: set[str]) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    for part in rel.parts[:-1]:
        if part in EXCLUDED_DIRS or part in extra:
            return True
    return False


def _token_similarity(a: str, b: str) -> float:
    def tokenize(s: str) -> set[str]:
        s2 = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
        s2 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s2)
        parts = re.split(r'[_\s]+', s2.lower())
        tokens: set[str] = set()
        for p in parts:
            if len(p) > 1:
                tokens.add(p)
        return tokens - {"", "id", "by", "at", "get", "set"}

    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ═════════════════════════════════════════════════════════════════════════════
#  NORMALIZATION
# ═════════════════════════════════════════════════════════════════════════════

def normalize_interface(name: str) -> str:
    n = name
    changed = True
    while changed:
        changed = False
        for suffix in IFACE_SUFFIXES:
            if n.endswith(suffix) and len(n) > len(suffix):
                n = n[:-len(suffix)]
                changed = True
                break
    return n.lower().strip()


def normalize_impl(name: str) -> str:
    n = name
    best_prefix = ""
    for prefix in sorted(IMPL_TECH_PREFIXES, key=len, reverse=True):
        if n.startswith(prefix) and len(n) > len(prefix):
            best_prefix = prefix
            break
    if best_prefix:
        n = n[len(best_prefix):]

    changed = True
    while changed:
        changed = False
        for suffix in IMPL_SUFFIXES:
            if n.endswith(suffix) and len(n) > len(suffix):
                n = n[:-len(suffix)]
                changed = True
                break
    return n.lower().strip()


# ═════════════════════════════════════════════════════════════════════════════
#  INFRASTRUCTURE DETECTION
# ═════════════════════════════════════════════════════════════════════════════

def _is_infrastructure(name: str, file_path: str) -> bool:
    nl = name.lower().replace("_", "")
    if any(sig in nl for sig in _INFRA_STRUCTURAL_SIGNALS):
        return True

    if name == "SagaStateStoreAdapter":
        return True

    for tech in sorted(_INFRA_PURE_TECH_PREFIXES, key=len, reverse=True):
        tn = tech.replace("_", "")
        if nl.startswith(tn) and len(nl) > len(tn):
            remainder = nl[len(tn):]
            has_domain = any(dk in remainder for dk in _DOMAIN_MIN4 if len(dk) >= 4)
            return not has_domain

    if nl.startswith("postgres") and len(nl) > 8:
        remainder = nl[8:]
        has_domain = any(dk in remainder for dk in _DOMAIN_MIN4 if len(dk) >= 4)
        return not has_domain

    if nl.startswith("s3") and len(nl) > 2:
        return True

    for kw in _INFRA_ANYWHERE_KW:
        if kw.replace("_", "") in nl:
            has_domain = any(dk in nl for dk in _DOMAIN_MIN4 if len(dk) >= 4)
            return not has_domain

    return False


# ═════════════════════════════════════════════════════════════════════════════
#  SCANNERS
# ═════════════════════════════════════════════════════════════════════════════

def scan_interfaces(
    ports_dir: pathlib.Path,
    root: pathlib.Path,
    extra_excludes: set[str],
    progress: Callable | None = None,
) -> list[InterfaceInfo]:
    INTERFACE_REPO_KEYWORDS: set[str] = {
        "repository", "store", "cache", "repo", "port", "protocol",
        "publisher", "consumer", "notary", "hashchain", "saga",
        "handler", "projection", "query",
    }
    results: list[InterfaceInfo] = []
    seen_names: set[str] = set()

    if not ports_dir.exists():
        logger.warning("Interface directory not found: %s", ports_dir)
        return results

    files = sorted(ports_dir.rglob("*.py"))
    for idx, py_file in enumerate(files):
        if progress:
            progress(idx + 1, len(files))
        if py_file.name == "__init__.py":
            continue
        if _should_exclude_path(py_file, root, extra_excludes):
            continue
        tree, err = _get_ast(py_file)
        if err or tree is None:
            continue

        try:
            rel    = py_file.relative_to(root)
        except ValueError:
            rel    = py_file
        module = str(rel.with_suffix("")).replace(os.sep, ".")

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            cname = node.name
            if cname in seen_names:
                continue
            if not any(cname.endswith(s) for s in ("Port", "Protocol", "PortProtocol")):
                continue
            if not any(kw in cname.lower() for kw in INTERFACE_REPO_KEYWORDS):
                continue
            methods = extract_methods_from_class(tree, cname)
            if not methods:
                continue

            base_name = normalize_interface(cname)
            has_abc   = _class_has_abc_base(node)

            is_self_impl = False
            if not has_abc:
                has_concrete = any(not m.is_abstract for m in methods.values())
                if has_concrete:
                    is_self_impl = True

            results.append(InterfaceInfo(
                name=cname,
                file_path=str(py_file),
                module=module,
                methods=methods,
                base_name=base_name,
                has_abc=has_abc,
                is_protocol_dup=False,
                is_self_implemented=is_self_impl,
            ))
            seen_names.add(cname)

    port_variant_bases: set[str] = {
        i.base_name for i in results
        if i.name.endswith("Port") and not i.name.endswith("PortProtocol")
    }
    for iface in results:
        if iface.name.endswith("PortProtocol") or (
            iface.name.endswith("Protocol") and not iface.name.endswith("PortProtocol")
        ):
            if iface.base_name in port_variant_bases:
                iface.is_protocol_dup = True

    return results


def _is_likely_implementation_file(file_path: pathlib.Path) -> bool:
    # FIX-61: Izinkan file di folder ports/ (termasuk _port.py) untuk di-scan,
    # karena di dalam folder ports/primary terdapat implementasi konkret
    # seperti InMemoryFileStorage, InMemoryNotification.
    parent = file_path.parent.name.lower()
    if parent in ("primary", "secondary") and "ports" in str(file_path.parent.parent).lower():
        return True
    stem = file_path.stem.lower()
    if stem.endswith("_port"):
        return False
    if stem.endswith("_interface") or stem.endswith("_protocol"):
        return False
    keywords = ("adapter", "impl", "repository", "store", "cache")
    return any(kw in stem for kw in keywords)


def _is_likely_implementation_class(class_name: str) -> bool:
    name_lower = class_name.lower()
    keywords = ("adapter", "impl", "repository", "store", "cache", "port", "handler", "projection")
    return any(kw in name_lower for kw in keywords) or name_lower.endswith("impl")


def scan_implementations(
    impl_dirs: list[pathlib.Path],
    root: pathlib.Path,
    extra_excludes: set[str],
    progress: Callable | None = None,
) -> list[ImplementationInfo]:
    results: list[ImplementationInfo] = []
    seen_names: set[str] = set()

    for impls_dir in impl_dirs:
        if not impls_dir.exists():
            logger.warning("Implementation directory not found: %s", impls_dir)
            continue

        files = sorted(impls_dir.rglob("*.py"))
        for idx, py_file in enumerate(files):
            if progress:
                progress(idx + 1, len(files))
            if py_file.name == "__init__.py":
                continue
            if _should_exclude_path(py_file, root, extra_excludes):
                continue

            if not _is_likely_implementation_file(py_file):
                continue

            tree, err = _get_ast(py_file)
            if err or tree is None:
                continue

            try:
                rel    = py_file.relative_to(root)
            except ValueError:
                rel    = py_file
            module = str(rel.with_suffix("")).replace(os.sep, ".")

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                cname = node.name
                if cname in seen_names:
                    continue

                if cname.endswith(("PortProtocol", "Protocol")):
                    continue
                if cname.endswith("Port") and not cname.endswith("PortImpl"):
                    has_impl_signal = any(
                        sig in cname for sig in ("Impl", "Adapter", "SQLAlchemy", "InMemory",
                                                   "Postgres", "Redis", "Kafka")
                    )
                    if not has_impl_signal:
                        continue

                methods = extract_methods_from_class(tree, cname)
                if not methods:
                    continue

                is_infra = _is_infrastructure(cname, str(py_file))
                bases     = _get_class_bases(node)
                base_name = normalize_impl(cname)

                if not _is_likely_implementation_class(cname):
                    has_port_base = any(b.endswith(("Port", "Protocol", "Interface")) for b in bases)
                    if not has_port_base:
                        continue

                results.append(ImplementationInfo(
                    name=cname,
                    file_path=str(py_file),
                    module=module,
                    methods=methods,
                    is_infrastructure=is_infra,
                    base_name=base_name,
                    extra_methods=[],
                    declared_bases=bases,
                ))
                seen_names.add(cname)

    return results


def scan_self_implemented_ports(
    interfaces: list[InterfaceInfo],
) -> list[ImplementationInfo]:
    impls: list[ImplementationInfo] = []
    for iface in interfaces:
        if iface.is_self_implemented and not iface.is_protocol_dup:
            impl = ImplementationInfo(
                name=iface.name,
                file_path=iface.file_path,
                module=iface.module,
                methods=iface.methods,
                is_infrastructure=False,
                base_name=iface.base_name,
                extra_methods=[],
                declared_bases=[],
            )
            impls.append(impl)
    return impls


# ═════════════════════════════════════════════════════════════════════════════
#  DUPLICATE CHECKER
# ═════════════════════════════════════════════════════════════════════════════

_DUPLICATE_PATTERNS: dict[str, list[str]] = {
    "interface":      ["Port", "Protocol", "PortProtocol"],
    "implementation": ["Repository", "Adapter", "Impl", "Store"],
    "dto":            ["DTO", "Dto", "Request", "Response", "Schema"],
    "entity":         ["Entity", "Aggregate", "AggregateRoot"],
    "value_object":   ["ValueObject", "VO"],
    "enum":           ["Status", "Type", "Category"],
    "event":          ["Event", "DomainEvent"],
    "command":        ["Command", "Cmd"],
    "query":          ["Query"],
    "service":        ["Service", "DomainService"],
}


def _file_is_mostly_imports(src: str) -> bool:
    lines = [ln.strip() for ln in src.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        return False
    n_import = sum(1 for ln in lines if ln.startswith("import ") or ln.startswith("from "))
    return (n_import / len(lines)) > 0.65 and len(lines) < 60


def _is_substantive_class_body(node: ast.ClassDef) -> bool:
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign)):
            return True
    return False


def scan_duplicates(
    root: pathlib.Path,
    extra_excludes: set[str],
    scope_dirs: list[pathlib.Path] | None = None,
) -> list[DuplicateEntry]:
    seen: dict[str, list[str]] = {}
    search_dirs = scope_dirs if scope_dirs else [root]
    visited: set[pathlib.Path] = set()

    for base_dir in search_dirs:
        if not base_dir.exists():
            continue
        for py_file in sorted(base_dir.rglob("*.py")):
            if py_file in visited:
                continue
            visited.add(py_file)
            if _should_exclude_path(py_file, root, extra_excludes):
                continue
            if py_file.name == "__init__.py":
                continue
            src = _read_source(py_file)
            if src is None:
                continue
            if _file_is_mostly_imports(src):
                continue
            tree, err = _get_ast(py_file)
            if err or tree is None:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not _is_substantive_class_body(node):
                    continue
                cname = node.name

                if cname in ALLOWED_DUPLICATE_NAMES:
                    continue

                kind = "unknown"
                for k, patterns in _DUPLICATE_PATTERNS.items():
                    if any(cname.endswith(p) for p in patterns):
                        kind = k
                        break
                if kind == "unknown":
                    continue

                key = f"{kind}::{cname}"
                seen.setdefault(key, []).append(str(py_file))

    duplicates: list[DuplicateEntry] = []
    for key, locations in seen.items():
        unique_files = sorted(set(locations))
        if len(unique_files) < 2:
            continue
        kind, name = key.split("::", 1)
        rec = _duplicate_recommendation(name, kind, unique_files)
        duplicates.append(DuplicateEntry(
            name=name, kind=kind, definition_files=unique_files, recommendation=rec,
        ))
    return sorted(duplicates, key=lambda d: (-len(d.definition_files), d.name))


def _duplicate_recommendation(name: str, kind: str, files: list[str]) -> str:
    has_domain   = any("/domain/" in f or "\\domain\\" in f for f in files)
    has_adapter  = any("/adapters/" in f or "\\adapters\\" in f for f in files)
    has_port     = any("/ports/" in f or "\\ports\\" in f for f in files)
    has_router   = any("router" in f.lower() for f in files)
    has_compliance = any("/compliance/" in f or "\\compliance\\" in f for f in files)

    if kind == "enum":
        if has_domain and (has_adapter or has_router):
            return (
                f"Pindahkan '{name}' ke domain layer sebagai canonical definition. "
                f"Import dari domain di semua file lain. "
                f"Hapus definisi di adapters/router."
            )
        if has_compliance and has_adapter:
            return f"Gunakan satu canonical '{name}' di shared_value_objects/enums.py."
        return f"Buat satu canonical '{name}' di shared_value_objects/ dan import dari sana."
    if kind == "dto":
        if has_router:
            return (
                f"'{name}' didefinisikan di beberapa router. "
                f"Pindahkan ke application/dto_objects/{name.lower()}.py dan import."
            )
        return f"Sentralisasikan '{name}' di application/dto_objects/."
    if kind == "interface":
        return (
            f"Port/Protocol '{name}' duplikat — pertimbangkan hanya pakai "
            f"ABC version atau Protocol version, bukan keduanya."
        )
    return f"Deduplikasi '{name}' — pilih satu lokasi canonical dan import dari sana."


# ═════════════════════════════════════════════════════════════════════════════
#  MATCHING
# ═════════════════════════════════════════════════════════════════════════════

def match_interface_to_impl(
    interface: InterfaceInfo,
    repo_impls: list[ImplementationInfo],
) -> ImplementationInfo | None:
    base_iface    = interface.base_name
    iface_name_lc = interface.name.lower()
    candidates: list[tuple[float, ImplementationInfo]] = []

    for impl in repo_impls:
        if impl.is_infrastructure:
            continue

        score = 0.0

        if impl.name == interface.name or (base_iface and impl.base_name and base_iface == impl.base_name):
            score = 1.0
        elif base_iface and impl.base_name:
            sim = _token_similarity(base_iface, impl.base_name)
            if sim >= 0.35:
                score = max(score, sim)

        for base in impl.declared_bases:
            if base == interface.name:
                score = max(score, 1.0)
                break
            if interface.name.endswith(base) or base.endswith(interface.name):
                score = max(score, 0.95)
                break

        if iface_name_lc in impl.file_path.lower().replace("\\", "/"):
            score = max(score, score + 0.25)

        impl_file_stem = pathlib.Path(impl.file_path).stem.lower().replace("_", "")
        if base_iface and base_iface in impl_file_stem:
            score = max(score, score + 0.15)

        if base_iface and base_iface in impl.name.lower():
            score = max(score, 0.8)

        if score > 0.35:
            candidates.append((score, impl))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x[0], x[1].name))
    best_score, best_impl = candidates[0]
    logger.debug(
        "Match: %s → %s (score=%.2f)", interface.name, best_impl.name, best_score
    )
    return best_impl


# ═════════════════════════════════════════════════════════════════════════════
#  COMPARE METHODS
# ═════════════════════════════════════════════════════════════════════════════

def _classify_param_mismatch(iface_name: str, impl_name: str) -> tuple[str, str]:
    pair = frozenset({iface_name, impl_name})
    if pair in COSMETIC_PARAM_PAIRS:
        return "INFO", "CHK-005b"
    if pair in SEMANTIC_MISMATCH_PAIRS:
        return "WARNING", "CHK-005c"
    return "WARNING", "CHK-005c"


def _fix_snippet_for_param_mismatch(
    iface: InterfaceInfo,
    method_name: str,
    mdef: MethodInfo,
    im: MethodInfo,
) -> str:
    params_str = ", ".join(f"{p}" for p in mdef.param_names)
    return (
        f"# Fix: sesuaikan signature impl dengan port\n"
        f"# File: {iface.file_path} (port definition)\n"
        f"def {method_name}(self, {params_str}): ..."
    )


def compare_methods(
    interface: InterfaceInfo,
    impl: ImplementationInfo,
    strict_types: bool = False,
) -> list[Violation]:
    violations: list[Violation] = []
    impl_set  = set(impl.methods.keys())

    for mname, mdef in interface.methods.items():
        if mname not in impl_set:
            violations.append(Violation(
                severity="ERROR",
                interface=interface.name,
                implementation=impl.name,
                message=f"Method '{mname}' missing in implementation",
                detail=f"Defined at {interface.file_path}:{mdef.lineno}",
                rule_id="CHK-001",
                fix_snippet=(
                    f"# Add to {impl.name}:\n"
                    f"def {mname}(self, {', '.join(mdef.param_names)})"
                    f"{' -> ' + mdef.return_annotation if mdef.return_annotation else ''}:\n"
                    f"    raise NotImplementedError"
                ),
            ))
            continue

        im = impl.methods[mname]

        if mdef.is_abstract and im.is_static:
            violations.append(Violation(
                severity="ERROR",
                interface=interface.name,
                implementation=impl.name,
                message=f"Decorator mismatch for '{mname}': @abstractmethod vs @staticmethod",
                detail="Implementation uses @staticmethod but interface expects instance method",
                rule_id="CHK-011",
            ))

        if mdef.is_async != im.is_async:
            violations.append(Violation(
                severity="ERROR",
                interface=interface.name,
                implementation=impl.name,
                message=f"Async/sync mismatch for '{mname}'",
                detail=(
                    f"Interface: {'async' if mdef.is_async else 'sync'} | "
                    f"Impl: {'async' if im.is_async else 'sync'}"
                ),
                rule_id="CHK-007",
                fix_snippet=(
                    f"# Change impl to {'async def' if mdef.is_async else 'def'} {mname}(self, ...)"
                ),
            ))

        if mdef.return_annotation and im.return_annotation:
            ni = _normalize_return_type(mdef.return_annotation)
            nm = _normalize_return_type(im.return_annotation)
            if ni != nm:
                iface_bare = _extract_base_type(ni).lower()
                impl_bare  = _extract_base_type(nm).lower()
                is_bare_generic_case = (
                    (nm in _BARE_GENERIC_TYPES and ni.startswith(nm + "["))
                    or (ni in _BARE_GENERIC_TYPES and nm.startswith(ni + "["))
                    or (iface_bare in _BARE_GENERIC_TYPES and impl_bare in _BARE_GENERIC_TYPES
                        and iface_bare == impl_bare)
                )
                if is_bare_generic_case:
                    violations.append(Violation(
                        severity="INFO",
                        interface=interface.name,
                        implementation=impl.name,
                        message=f"Return type: impl uses bare generic for '{mname}' (acceptable)",
                        detail=f"Interface: {mdef.return_annotation} | Impl: {im.return_annotation}",
                        rule_id="CHK-006b",
                    ))
                elif _type_mismatch_is_real(mdef.return_annotation, im.return_annotation):
                    sev = "ERROR" if strict_types else "WARNING"
                    note = (
                        "" if strict_types
                        else " [AST-only; use --strict-types for ERROR]"
                    )
                    violations.append(Violation(
                        severity=sev,
                        interface=interface.name,
                        implementation=impl.name,
                        message=f"Return type mismatch for '{mname}'" + note,
                        detail=(
                            f"Interface: {mdef.return_annotation} | "
                            f"Impl: {im.return_annotation}"
                        ),
                        rule_id="CHK-006",
                        fix_snippet=(
                            f"# Fix: change impl return type\n"
                            f"def {mname}(self, ...) -> {mdef.return_annotation}: ..."
                        ),
                    ))

        if mdef.required_count != im.required_count:
            violations.append(Violation(
                severity="WARNING",
                interface=interface.name,
                implementation=impl.name,
                message=f"Required param count mismatch for '{mname}'",
                detail=(
                    f"Interface: {mdef.required_count} | Impl: {im.required_count}"
                ),
                rule_id="CHK-002",
                fix_snippet=_fix_snippet_for_param_mismatch(interface, mname, mdef, im),
            ))

        if mdef.kwonly_count != im.kwonly_count:
            violations.append(Violation(
                severity="WARNING",
                interface=interface.name,
                implementation=impl.name,
                message=f"Keyword-only param count mismatch for '{mname}'",
                detail=f"Interface: {mdef.kwonly_count} | Impl: {im.kwonly_count}",
                rule_id="CHK-003",
            ))

        if (mdef.param_names and im.param_names
                and len(mdef.param_names) == len(im.param_names)):
            mismatched = [
                (i, a, b)
                for i, (a, b) in enumerate(zip(mdef.param_names, im.param_names))
                if a != b
            ]
            if mismatched:
                iface_name_set = set(mdef.param_names)
                impl_name_set  = set(im.param_names)

                if iface_name_set == impl_name_set:
                    violations.append(Violation(
                        severity="ERROR",
                        interface=interface.name,
                        implementation=impl.name,
                        message=f"Parameter ORDER mismatch for '{mname}' — arguments swapped",
                        detail=" | ".join(
                            f"pos{i}: iface='{a}' impl='{b}'" for i, a, b in mismatched
                        ),
                        rule_id="CHK-005a",
                        fix_snippet=_fix_snippet_for_param_mismatch(interface, mname, mdef, im),
                    ))
                else:
                    warn_pairs: list[tuple[int, str, str]] = []
                    info_pairs: list[tuple[int, str, str]] = []
                    for i, a, b in mismatched:
                        sev, _ = _classify_param_mismatch(a, b)
                        (info_pairs if sev == "INFO" else warn_pairs).append((i, a, b))

                    if warn_pairs:
                        violations.append(Violation(
                            severity="WARNING",
                            interface=interface.name,
                            implementation=impl.name,
                            message=f"Parameter NAME mismatch (semantic) for '{mname}'",
                            detail=" | ".join(
                                f"pos{i}: iface='{a}' impl='{b}'" for i, a, b in warn_pairs
                            ),
                            rule_id="CHK-005c",
                            fix_snippet=_fix_snippet_for_param_mismatch(interface, mname, mdef, im),
                        ))
                    if info_pairs:
                        violations.append(Violation(
                            severity="INFO",
                            interface=interface.name,
                            implementation=impl.name,
                            message=f"Parameter NAME mismatch (cosmetic) for '{mname}'",
                            detail=" | ".join(
                                f"pos{i}: iface='{a}' impl='{b}'" for i, a, b in info_pairs
                            ),
                            rule_id="CHK-005b",
                        ))

        for pname, idef in mdef.param_defaults.items():
            if pname in im.param_defaults and idef != im.param_defaults[pname]:
                violations.append(Violation(
                    severity="WARNING",
                    interface=interface.name,
                    implementation=impl.name,
                    message=f"Default value mismatch for '{mname}.{pname}'",
                    detail=(
                        f"Interface: {idef} | Impl: {im.param_defaults[pname]}"
                    ),
                    rule_id="CHK-009",
                    fix_snippet=(
                        f"# Fix: align default value in impl\n"
                        f"# '{pname}' should default to {idef}"
                    ),
                ))

        if mdef.raises_annotations and im.raises_annotations:
            extra = set(im.raises_annotations) - set(mdef.raises_annotations)
            if extra:
                violations.append(Violation(
                    severity="WARNING",
                    interface=interface.name,
                    implementation=impl.name,
                    message=f"Exception contract mismatch for '{mname}'",
                    detail=f"Impl raises {sorted(extra)} not documented in interface",
                    rule_id="CHK-008",
                ))

    impl.extra_methods = sorted(set(impl.methods.keys()) - set(interface.methods.keys()))
    return violations


# ═════════════════════════════════════════════════════════════════════════════
#  EXCLUDED IMPLEMENTATION
# ═════════════════════════════════════════════════════════════════════════════

def _is_excluded_impl(name: str) -> bool:
    if name.startswith("_"):
        return True
    excluded_suffixes = (
        "Response", "DTO", "Request", "Schema", "Table",
        "Helper", "Validator", "Factory", "Export",
        "Builder", "Generator", "Processor", "Manager", "Integrator",
        "Client", "Logger", "Handler", "Receiver", "Verifier",
        "HealthChecker", "Dashboard", "Scheduler", "CircuitBreaker",
        "Exception", "Dummy", "Fallback", "Event", "Audit",
        "Record", "Entity", "ValueObject"
    )
    if any(name.endswith(s) for s in excluded_suffixes):
        return True
    if name.endswith(("Keluaran", "Masukan", "Tahunan", "Masa")):
        return True
    tech_prefixes = ("WhatsApp", "Kafka", "S3", "Glacier", "MinIO")
    if any(name.startswith(p) for p in tech_prefixes):
        return True
    return False


# ═════════════════════════════════════════════════════════════════════════════
#  SCORING
# ═════════════════════════════════════════════════════════════════════════════

def _compute_score(
    interfaces: list[InterfaceInfo],
    matched_pairs: list[tuple[str, str]],
    violations: list[Violation],
) -> ScoreBreakdown:
    countable = [i for i in interfaces if not i.is_protocol_dup]
    total_ifaces    = len(interfaces)
    countable_count = len(countable)
    matched_count   = len(matched_pairs)

    countable_names = {i.name for i in countable}
    matched_countable = sum(1 for i, _ in matched_pairs if i in countable_names)

    coverage = (matched_countable / countable_count * 100) if countable_count > 0 else 100.0
    coverage = round(min(coverage, 100.0), 1)

    cov_grade, cov_color = "F", "RED"
    for threshold, g, col in GRADE_THRESHOLDS:
        if coverage >= threshold:
            cov_grade, cov_color = g, col
            break

    if matched_count == 0:
        quality, error_free, avg_err, avg_warn = 0.0, 0, 0.0, 0.0
    else:
        matched_names = {i for i, _ in matched_pairs}
        relevant = [v for v in violations if v.interface in matched_names]
        err_by: dict[str, int]  = {}
        warn_by: dict[str, int] = {}
        for v in relevant:
            if v.severity == "ERROR":
                err_by[v.interface]  = err_by.get(v.interface, 0) + 1
            elif v.severity == "WARNING":
                warn_by[v.interface] = warn_by.get(v.interface, 0) + 1

        total_err  = sum(err_by.values())
        total_warn = sum(warn_by.values())
        avg_err    = total_err  / matched_count
        avg_warn   = total_warn / matched_count
        error_free = sum(1 for i, _ in matched_pairs if err_by.get(i, 0) == 0)

        quality = 100.0 * math.exp(-0.8 * avg_err) * math.exp(-0.3 * avg_warn)
        quality = round(min(100.0, max(0.0, quality)), 1)

    qual_grade, qual_color = "F", "RED"
    for threshold, g, col in GRADE_THRESHOLDS:
        if quality >= threshold:
            qual_grade, qual_color = g, col
            break

    if coverage >= 95 and quality >= 90:
        interpretation = "Excellent — complete coverage, clean contracts. Ready for external audit."
    elif coverage >= 88 and quality >= 75:
        interpretation = "Good — most contracts fulfilled with acceptable quality."
    elif coverage < 70:
        interpretation = (
            f"Coverage {coverage}% — prioritize implementing missing interfaces. "
            f"See [UNMATCHED] section."
        )
    elif quality < 50:
        interpretation = (
            f"Coverage {coverage}% but quality {quality}% — "
            f"many signature mismatches need fixing."
        )
    else:
        interpretation = (
            f"Coverage {coverage}%, Quality {quality}% — "
            f"review violations in detail."
        )

    return ScoreBreakdown(
        coverage_score=coverage,
        coverage_grade=cov_grade,
        coverage_color=cov_color,
        quality_score=quality,
        quality_grade=qual_grade,
        quality_color=qual_color,
        matched_count=matched_count,
        total_interfaces=total_ifaces,
        countable_interfaces=countable_count,
        error_free_matched=error_free,
        avg_error_per_matched=round(avg_err, 2),
        avg_warning_per_matched=round(avg_warn, 2),
        interpretation=interpretation,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ═════════════════════════════════════════════════════════════════════════════

def scan_repositories(
    root: pathlib.Path,
    ports_dir: pathlib.Path | None  = None,
    ports_secondary_dir: pathlib.Path | None = None,
    impls_dir: pathlib.Path | None  = None,
    run_rca: bool        = True,
    run_dup: bool        = True,
    dup_full_scan: bool  = True,
    strict_types: bool   = False,
    max_workers: int     = 4,
    extra_excludes: set[str] | None = None,
    progress_callback: Callable | None = None,
) -> CheckerResult:
    t_start        = time.monotonic()
    extra_excludes = extra_excludes or set()

    eff_ports      = ports_dir or (root / "ports" / "primary")
    eff_ports_sec  = ports_secondary_dir if ports_secondary_dir is not None else (root / "ports" / "secondary")

    # FIX-62: Tambahkan ports/primary dan ports/secondary ke default_impl_dirs
    # agar InMemoryFileStorage dan implementasi konkret lainnya yang berada di ports
    # dapat ditemukan oleh checker.
    default_impl_dirs = [
        root / "adapters" / "secondary_impl",
        root / "ports" / "primary",
        root / "ports" / "secondary",
    ]
    if impls_dir:
        eff_impl_dirs = [impls_dir]
    else:
        eff_impl_dirs = default_impl_dirs

    interfaces = scan_interfaces(eff_ports, root, extra_excludes, progress_callback)
    if eff_ports_sec.exists():
        sec_ifaces = scan_interfaces(eff_ports_sec, root, extra_excludes, progress_callback)
        existing_names = {i.name for i in interfaces}
        interfaces.extend(i for i in sec_ifaces if i.name not in existing_names)

    all_impls    = scan_implementations(eff_impl_dirs, root, extra_excludes, progress_callback)
    self_impls   = scan_self_implemented_ports(interfaces)
    all_impls.extend(self_impls)

    repo_impls   = [i for i in all_impls if not i.is_infrastructure]
    repo_impls   = [i for i in repo_impls if not _is_excluded_impl(i.name)]
    infra_names  = [i.name for i in all_impls if i.is_infrastructure]

    matched_pairs:       list[tuple[str, str]] = []
    matched_iface_names: set[str]              = set()
    all_violations:      list[Violation]       = []

    for iface in interfaces:
        if iface.name in matched_iface_names:
            continue
        if iface.is_protocol_dup:
            continue
        impl = match_interface_to_impl(iface, repo_impls)
        if impl:
            matched_pairs.append((iface.name, impl.name))
            matched_iface_names.add(iface.name)
            all_violations.extend(compare_methods(iface, impl, strict_types=strict_types))

    unmatched_ifaces = [
        i.name for i in interfaces
        if i.name not in matched_iface_names and not i.is_protocol_dup
    ]

    used_impl_names = {impl_name for _, impl_name in matched_pairs}
    unmatched_impls = [
        i.name for i in repo_impls
        if i.name not in used_impl_names
        and not i.name.endswith(("Port", "Protocol", "Interface", "ABC"))
        and not _is_excluded_impl(i.name)
    ]

    total_errors   = sum(1 for v in all_violations if v.severity == "ERROR")
    total_warnings = sum(1 for v in all_violations if v.severity == "WARNING")
    total_infos    = sum(1 for v in all_violations if v.severity == "INFO")

    if run_rca:
        for v in all_violations:
            if v.severity in ("ERROR", "WARNING"):
                try:
                    exc = RuntimeError(
                        f"[{v.rule_id}] {v.interface}↔{v.implementation}: {v.message}"
                    )
                    r = _rca_analyze(exc, {
                        "rule_id"       : v.rule_id,
                        "interface"     : v.interface,
                        "implementation": v.implementation,
                        "detail"        : v.detail,
                        "severity"      : v.severity,
                    })
                    if r:
                        v.rca = r
                except Exception:
                    pass

    sb = _compute_score(interfaces, matched_pairs, all_violations)

    duplicates: list[DuplicateEntry] = []
    if run_dup:
        scope = [root] if dup_full_scan else [
            d for d in [eff_ports, eff_impl_dirs[0], root / "domain", root / "application"]
            if d.exists()
        ]
        duplicates = scan_duplicates(root, extra_excludes, scope_dirs=scope)

    rca_results: list[dict[str, Any]] = []
    if run_rca:
        for v in [x for x in all_violations if x.severity == "ERROR"][:30]:
            if v.rca:
                rca_results.append({
                    "violation"     : v.message,
                    "interface"     : v.interface,
                    "implementation": v.implementation,
                    "rule_id"       : v.rule_id,
                    **v.rca,
                })

    return CheckerResult(
        interfaces=interfaces,
        implementations=repo_impls,
        infrastructure_impls=infra_names,
        matched=matched_pairs,
        unmatched_interfaces=unmatched_ifaces,
        unmatched_impls=unmatched_impls,
        violations=all_violations,
        total_errors=total_errors,
        total_warnings=total_warnings,
        total_infos=total_infos,
        score_breakdown=sb,
        duplicates=duplicates,
        audit_timestamp=datetime.datetime.utcnow().isoformat() + "Z",
        elapsed_seconds=round(time.monotonic() - t_start, 3),
        strict_types=strict_types,
        rca_results=rca_results,
    )



# ═════════════════════════════════════════════════════════════════════════════
#  REPORT
# ═════════════════════════════════════════════════════════════════════════════

def print_report(
    data: CheckerResult,
    verbose: bool        = False,
    limit: int           = 50,
    show_fix_snippets: bool = False,
) -> None:
    W    = 72
    SEP  = "=" * W
    TSEP = "─" * W
    sb   = data.score_breakdown

    _safe_print(f"\n{_c('CYAN')}{SEP}{_c('RESET')}")
    _safe_print(f"{_c('BOLD')}{_c('CYAN')}  REPOSITORY CONTRACT CHECKER REPORT v{__version__}{_c('RESET')}")
    _safe_print(f"{_c('CYAN')}{SEP}{_c('RESET')}")
    _safe_print(
        f"\n  {_c('DIM')}Methodology: AST-only static analysis. No runtime execution.{_c('RESET')}\n"
        f"  {_c('DIM')}CHK-006 (incompatible types) = WARNING in default mode, ERROR in --strict-types.{_c('RESET')}\n"
        f"  {_c('DIM')}CHK-006b (bare generic list vs list[X]) = INFO only — not a real bug.{_c('RESET')}"
    )

    _safe_print(f"\n  Audit timestamp             : {data.audit_timestamp}")
    _safe_print(f"  Elapsed                     : {data.elapsed_seconds:.3f}s")
    _safe_print(f"  RCA Engine                  : {'Active' if _RCA_AVAILABLE else 'Not available'}")
    _safe_print(f"  Mode                        : {'STRICT (--strict-types)' if data.strict_types else 'Default'}")
    _safe_print()
    _safe_print(f"  Interfaces found            : {len(data.interfaces):>5}")
    _safe_print(f"  Countable interfaces        : {sb.countable_interfaces:>5}  (excl. PortProtocol dups)")
    _safe_print(f"  Repository implementations  : {len(data.implementations):>5}")
    _safe_print(f"  Infrastructure impls (skip) : {len(data.infrastructure_impls):>5}")
    _safe_print(f"  Matched pairs               : {len(data.matched):>5}")
    _safe_print(f"  Unmatched interfaces        : {len(data.unmatched_interfaces):>5}")
    _safe_print(f"  Unmatched implementations   : {len(data.unmatched_impls):>5}")
    _safe_print(f"  Duplicate class names found : {len(data.duplicates):>5}")
    _safe_print()
    _safe_print(f"  Contract Errors             : {_c('RED')}{data.total_errors:>5}{_c('RESET')}")
    _safe_print(f"  Contract Warnings           : {_c('YELLOW')}{data.total_warnings:>5}{_c('RESET')}")
    _safe_print(f"  Contract Infos (cosmetic)   : {_c('DIM')}{data.total_infos:>5}{_c('RESET')}")

    _safe_print(f"\n{_c('CYAN')}{TSEP}{_c('RESET')}")
    _safe_print("  SCORE — TWO SEPARATE DIMENSIONS (not combined)")
    _safe_print(f"{_c('CYAN')}{TSEP}{_c('RESET')}")
    _safe_print(f"  {_c('BOLD')}(1) COVERAGE SCORE{_c('RESET')} — completeness of interface implementation")
    _safe_print(
        f"      {_c(sb.coverage_color)}{_c('BOLD')}{sb.coverage_score:.1f}/100 "
        f"[{sb.coverage_grade}]{_c('RESET')}   "
        f"({sb.matched_count}/{sb.countable_interfaces} countable matched)"
    )
    _safe_print(f"\n  {_c('BOLD')}(2) QUALITY SCORE{_c('RESET')} — contract cleanliness from matched pairs")
    _safe_print(
        f"      {_c(sb.quality_color)}{_c('BOLD')}{sb.quality_score:.1f}/100 "
        f"[{sb.quality_grade}]{_c('RESET')}   "
        f"(avg {sb.avg_error_per_matched} err & {sb.avg_warning_per_matched} warn per match)"
    )
    _safe_print(f"      Error-free matched pairs: {sb.error_free_matched}/{sb.matched_count}")
    _safe_print(f"\n  {sb.interpretation}")

    if data.matched:
        _safe_print(f"\n{_c('GREEN')}[OK] Matched pairs ({len(data.matched)}):{_c('RESET')}")
        for iface, impl in data.matched[:limit]:
            _safe_print(f"    {iface}  <-->  {impl}")
        if len(data.matched) > limit:
            _safe_print(f"    ... and {len(data.matched) - limit} more.")

    if data.unmatched_interfaces:
        _safe_print(
            f"\n{_c('RED')}[UNMATCHED] Interfaces without implementation "
            f"({len(data.unmatched_interfaces)}):{_c('RESET')}"
        )
        for n in data.unmatched_interfaces[:limit]:
            _safe_print(f"    {_c('RED')}- {n}{_c('RESET')}")
        if len(data.unmatched_interfaces) > limit:
            _safe_print(f"    ... and {len(data.unmatched_interfaces) - limit} more.")

    if data.unmatched_impls:
        _safe_print(
            f"\n{_c('YELLOW')}[WARN] Implementations without matched interface "
            f"({len(data.unmatched_impls)}):{_c('RESET')}"
        )
        for n in data.unmatched_impls[:limit]:
            _safe_print(f"    - {n}")

    if data.duplicates:
        _safe_print(
            f"\n{_c('MAGENTA')}[DUP-001] Duplicate class names "
            f"({len(data.duplicates)}):{_c('RESET')}"
        )
        for dup in data.duplicates[:limit]:
            _safe_print(
                f"    {_c('MAGENTA')}{dup.name}{_c('RESET')} "
                f"({dup.kind}) — {len(dup.definition_files)} definitions"
            )
            if verbose:
                for loc in dup.definition_files:
                    _safe_print(f"      → {loc}")
                if dup.recommendation:
                    _safe_print(f"      💡 {_c('CYAN')}{dup.recommendation}{_c('RESET')}")
        if len(data.duplicates) > limit:
            _safe_print(f"    ... and {len(data.duplicates) - limit} more.")

    errors = [v for v in data.violations if v.severity == "ERROR"]
    if errors:
        _safe_print(f"\n{_c('RED')}[ERRORS] ({len(errors)}):{_c('RESET')}")
        for v in errors[:limit]:
            _safe_print(f"  {_c('RED')}[{v.rule_id}]{_c('RESET')} {v.message}")
            _safe_print(f"       Interface : {v.interface}")
            _safe_print(f"       Impl      : {v.implementation}")
            if v.detail:
                _safe_print(f"       Detail    : {v.detail}")
            if v.rca:
                _safe_print(f"       RCA       : {v.rca.get('root_cause', '')[:120]}")
                if verbose and v.rca.get("suggested_fix"):
                    _safe_print(f"       Fix       : {v.rca['suggested_fix'][:120]}")
            if show_fix_snippets and v.fix_snippet:
                _safe_print("       Snippet   :")
                for ln in v.fix_snippet.splitlines():
                    _safe_print(f"         {_c('DIM')}{ln}{_c('RESET')}")
        if len(errors) > limit:
            _safe_print(f"  ... and {len(errors) - limit} more.")

    warnings = [v for v in data.violations if v.severity == "WARNING"]
    if warnings:
        _safe_print(
            f"\n{_c('YELLOW')}[WARNINGS] ({len(warnings)})"
            f"{'  (showing all — use --verbose for details)' if not verbose else ''}:{_c('RESET')}"
        )
        show_limit = limit if verbose else min(10, limit)
        for v in warnings[:show_limit]:
            _safe_print(f"  {_c('YELLOW')}[{v.rule_id}]{_c('RESET')} {v.message}")
            _safe_print(f"       Interface : {v.interface}")
            _safe_print(f"       Impl      : {v.implementation}")
            if v.detail:
                _safe_print(f"       Detail    : {v.detail}")
            if verbose and v.rca:
                _safe_print(f"       RCA       : {v.rca.get('root_cause', '')[:120]}")
            if show_fix_snippets and v.fix_snippet:
                _safe_print("       Snippet   :")
                for ln in v.fix_snippet.splitlines():
                    _safe_print(f"         {_c('DIM')}{ln}{_c('RESET')}")
        if len(warnings) > show_limit:
            _safe_print(f"  ... and {len(warnings) - show_limit} more.")

    if data.rca_results and verbose:
        _safe_print(f"\n{_c('CYAN')}[RCA] Root Cause Analysis ({len(data.rca_results)}):{_c('RESET')}")
        for r in data.rca_results[:20]:
            _safe_print(f"  [{r.get('error_code','?')}] {r.get('violation','')[:100]}")
            _safe_print(f"    Root cause : {r.get('root_cause','')[:120]}")
            _safe_print(f"    Confidence : {r.get('confidence',0):.0%}")

    _safe_print(f"\n{_c('CYAN')}{TSEP}{_c('RESET')}")
    _safe_print(
        f"  Errors: {_c('RED')}{data.total_errors}{_c('RESET')}  "
        f"Warnings: {_c('YELLOW')}{data.total_warnings}{_c('RESET')}  "
        f"Coverage: {_c(sb.coverage_color)}{_c('BOLD')}{sb.coverage_score:.1f}%{_c('RESET')}  "
        f"Quality: {_c(sb.quality_color)}{_c('BOLD')}{sb.quality_score:.1f}%{_c('RESET')}"
    )
    if data.total_errors == 0 and len(data.unmatched_interfaces) == 0:
        _safe_print(f"\n  {_c('GREEN')}[PASS] All contracts fulfilled.{_c('RESET')}")
    elif data.total_errors == 0:
        _safe_print(
            f"\n  {_c('YELLOW')}[PARTIAL PASS] No errors in matched pairs, "
            f"but {len(data.unmatched_interfaces)} interfaces unmatched.{_c('RESET')}"
        )
    else:
        _safe_print(f"\n  {_c('RED')}[FAIL] Fix {data.total_errors} errors before merge.{_c('RESET')}")


# ═════════════════════════════════════════════════════════════════════════════
#  JSON EXPORT
# ═════════════════════════════════════════════════════════════════════════════

def save_json(data: CheckerResult, filepath: str) -> bool:
    sb = data.score_breakdown
    payload: dict[str, Any] = {
        "checker_version" : __version__,
        "audit_timestamp" : data.audit_timestamp,
        "elapsed_seconds" : data.elapsed_seconds,
        "strict_types_mode": data.strict_types,
        "rca_available"   : _RCA_AVAILABLE,
        "methodology"     : (
            "AST-only static analysis. No runtime execution, no type resolution. "
            "CHK-006 is heuristic — use mypy/pyright for authoritative type checking. "
            "CHK-006b (bare generic) is INFO only, not a real mismatch."
        ),
        "score": {
            "coverage_score"         : sb.coverage_score,
            "coverage_grade"         : sb.coverage_grade,
            "quality_score"          : sb.quality_score,
            "quality_grade"          : sb.quality_grade,
            "matched_count"          : sb.matched_count,
            "total_interfaces"       : sb.total_interfaces,
            "countable_interfaces"   : sb.countable_interfaces,
            "error_free_matched"     : sb.error_free_matched,
            "avg_error_per_matched"  : sb.avg_error_per_matched,
            "avg_warning_per_matched": sb.avg_warning_per_matched,
            "interpretation"         : sb.interpretation,
        },
        "summary": {
            "total_interfaces"    : len(data.interfaces),
            "total_repo_impls"    : len(data.implementations),
            "infrastructure_impls": data.infrastructure_impls,
            "matched_count"       : len(data.matched),
            "unmatched_interfaces": data.unmatched_interfaces,
            "unmatched_impls"     : data.unmatched_impls,
            "total_errors"        : data.total_errors,
            "total_warnings"      : data.total_warnings,
            "total_infos"         : data.total_infos,
            "total_duplicates"    : len(data.duplicates),
        },
        "matched_pairs": [{"interface": i, "implementation": m} for i, m in data.matched],
        "violations": {
            "errors": [
                {
                    "rule_id": v.rule_id, "interface": v.interface,
                    "implementation": v.implementation, "message": v.message,
                    "detail": v.detail, "fix_snippet": v.fix_snippet, "rca": v.rca,
                }
                for v in data.violations if v.severity == "ERROR"
            ],
            "warnings": [
                {
                    "rule_id": v.rule_id, "interface": v.interface,
                    "implementation": v.implementation, "message": v.message,
                    "detail": v.detail, "fix_snippet": v.fix_snippet, "rca": v.rca,
                }
                for v in data.violations if v.severity == "WARNING"
            ],
            "infos": [
                {
                    "rule_id": v.rule_id, "interface": v.interface,
                    "implementation": v.implementation, "message": v.message,
                    "detail": v.detail,
                }
                for v in data.violations if v.severity == "INFO"
            ],
        },
        "duplicates": [
            {
                "name": d.name, "kind": d.kind,
                "definition_files": d.definition_files,
                "recommendation"  : d.recommendation,
            }
            for d in data.duplicates
        ],
        "rca_results": data.rca_results,
    }
    try:
        out = pathlib.Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        _safe_print(f"{_c('GREEN')}[OK] Report exported → {filepath}{_c('RESET')}")
        return True
    except (OSError, PermissionError, TypeError) as e:
        _safe_print(f"{_c('RED')}[ERROR] Export failed: {e}{_c('RESET')}")
        return False


# ═════════════════════════════════════════════════════════════════════════════
#  SELF-TEST
# ═════════════════════════════════════════════════════════════════════════════

def _run_self_test() -> bool:
    failures: list[str] = []

    def check(name: str, got: Any, expected: Any) -> None:
        if got != expected:
            failures.append(f"FAIL [{name}]: got={got!r} expected={expected!r}")
        else:
            _safe_print(f"  {_c('GREEN')}✅ {name}{_c('RESET')}")

    _safe_print(f"\n{_c('CYAN')}[SELF-TEST] Repository Checker v{__version__}{_c('RESET')}\n")

    check("norm_impl_notification_channel",
          normalize_impl("SQLAlchemyNotificationChannelAdapter"), "notification")
    check("norm_impl_unitofwork",
          normalize_impl("SQLAlchemyUnitOfWork"), "unitofwork")
    check("norm_iface_unitofwork",
          normalize_interface("UnitOfWorkPort"), "unitofwork")
    check("norm_impl_bank_statement",
          normalize_impl("BankStatementImportAdapter"), "bankstatementimport")
    check("norm_iface_bank_statement",
          normalize_interface("BankStatementImportPort"), "bankstatementimport")
    check("excluded_impl_response", _is_excluded_impl("NSFPResponse"), True)
    check("excluded_impl_dto", _is_excluded_impl("AssetDTO"), True)
    check("excluded_impl_table", _is_excluded_impl("EmployeeTable"), True)
    check("excluded_impl_helper", _is_excluded_impl("PasswordHelper"), True)
    check("excluded_impl_factory", _is_excluded_impl("SQLAlchemyUnitOfWorkFactory"), True)
    check("excluded_impl_builder", _is_excluded_impl("SPTMasaPPH21Builder"), True)
    check("excluded_impl_generator", _is_excluded_impl("FakturKeluaranGenerator"), True)
    check("excluded_impl_fallback", _is_excluded_impl("_FallbackSPTRepository"), True)
    check("not_excluded_adapter", _is_excluded_impl("SQLAlchemyNotificationChannelAdapter"), False)

    check("FIX-51: BankStatementImportAdapter norm",
          normalize_impl("BankStatementImportAdapter"), "bankstatementimport")
    check("FIX-51: BankStatementImportPort norm",
          normalize_interface("BankStatementImportPort"), "bankstatementimport")

    check("FIX-52: AccountRepositoryPort impl-norm (Port suffix NOT stripped)",
          normalize_impl("AccountRepositoryPort"), "accountrepositoryport")
    check("FIX-52: AccountRepositoryPort iface-norm",
          normalize_interface("AccountRepositoryPort"), "account")
    check("FIX-52: APRepositoryPort impl-norm != iface-norm",
          normalize_impl("APRepositoryPort") == normalize_interface("APRepositoryPort"), False)
    check("FIX-52: JournalRepositoryPort no self-match",
          normalize_impl("JournalRepositoryPort") == normalize_interface("JournalRepositoryPort"), False)
    check("FIX-52: FileStoragePort no self-match",
          normalize_impl("FileStoragePort") == normalize_interface("FileStoragePort"), False)
    check("FIX-52: NotificationPort no self-match",
          normalize_impl("NotificationPort") == normalize_interface("NotificationPort"), False)

    check("FIX-52: SQLAlchemyAccountRepository norm",
          normalize_impl("SQLAlchemyAccountRepository"), "account")
    check("FIX-52: SQLAlchemyJournalRepository norm",
          normalize_impl("SQLAlchemyJournalRepository"), "journal")
    check("FIX-52: SQLAlchemyAPRepository norm",
          normalize_impl("SQLAlchemyAPRepository"), "ap")
    check("FIX-52: SQLAlchemyEmployeeRepository norm",
          normalize_impl("SQLAlchemyEmployeeRepository"), "employee")

    check("FIX-52: Port not in IMPL_SUFFIXES",
          any(s == "Port" for s in IMPL_SUFFIXES), False)

    import pathlib as _pl
    check("FIX-53: account_repository_port.py is NOT impl file",
          _is_likely_implementation_file(_pl.Path("account_repository_port.py")), False)
    check("FIX-53: cache_port.py is NOT impl file",
          _is_likely_implementation_file(_pl.Path("cache_port.py")), False)
    check("FIX-53: notification_port.py is NOT impl file",
          _is_likely_implementation_file(_pl.Path("notification_port.py")), False)
    check("FIX-53: sqlalchemy_account_repository_impl.py IS impl file",
          _is_likely_implementation_file(_pl.Path("sqlalchemy_account_repository_impl.py")), True)
    check("FIX-53: bank_statement_import_adapter.py IS impl file",
          _is_likely_implementation_file(_pl.Path("bank_statement_import_adapter.py")), True)
    check("FIX-53: aging_report_repository_adapter.py IS impl file",
          _is_likely_implementation_file(_pl.Path("aging_report_repository_adapter.py")), True)

    # FIX-61: file di ports/primary dianggap impl file
    check("FIX-61: file_storage_port.py di ports/primary IS impl file",
          _is_likely_implementation_file(_pl.Path("ports/primary/file_storage_port.py")), True)
    check("FIX-61: notification_port.py di ports/primary IS impl file",
          _is_likely_implementation_file(_pl.Path("ports/primary/notification_port.py")), True)

    check("FIX-55: BankStatementImportAdapter not excluded",
          _is_excluded_impl("BankStatementImportAdapter"), False)

    check("FIX-57: Any|None compatible with SalesOrderEntity|None",
          _types_compatible("Any | None", "SalesOrderEntity | None"), True)
    check("FIX-57: list[Any] compatible with list[SalesOrderEntity]",
          _types_compatible("list[Any]", "list[SalesOrderEntity]"), True)
    check("FIX-57: Any compatible with dict[str, Any]",
          _types_compatible("Any", "dict[str, Any]"), True)
    check("FIX-57: dict[str,Any] vs list[dict] NOT a real mismatch (aging compat)",
          _type_mismatch_is_real("dict[str, Any]", "list[dict]"), False)
    check("FIX-57: bytes vs bool IS still a real mismatch",
          _type_mismatch_is_real("bytes", "bool"), True)

    check("FIX-59: report_id/output_id is INFO",
          _classify_param_mismatch("report_id", "output_id")[0], "INFO")
    check("FIX-59: report_type/definition_id is INFO",
          _classify_param_mismatch("report_type", "definition_id")[0], "INFO")
    check("FIX-59: params/parameters is INFO",
          _classify_param_mismatch("params", "parameters")[0], "INFO")
    check("FIX-59: transaction_number/so_number is INFO",
          _classify_param_mismatch("transaction_number", "so_number")[0], "INFO")
    check("FIX-59: user_id/submitted_by is WARNING (semantic)",
          _classify_param_mismatch("user_id", "submitted_by")[0], "WARNING")

    if failures:
        _safe_print(f"\n  {_c('RED')}FAILURES:{_c('RESET')}")
        for f_msg in failures:
            _safe_print(f"  {_c('RED')}{f_msg}{_c('RESET')}")
        _safe_print(f"\n  {_c('RED')}[FAIL] {len(failures)} test(s) failed.{_c('RESET')}")
        return False

    _safe_print(f"\n  {_c('GREEN')}[PASS] All self-tests passed.{_c('RESET')}")
    return True


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="repository_checker",
        description=f"Repository Contract Checker v{__version__} — Big 4 / SOX/ISA 315",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python checker/repository_checker.py\n"
            "  python checker/repository_checker.py --verbose --fix-suggestions\n"
            "  python checker/repository_checker.py --json report.json --format both\n"
            "  python checker/repository_checker.py --strict-types\n"
            "  python checker/repository_checker.py --self-test\n"
        ),
    )
    p.add_argument("--root",               metavar="DIR", default=None)
    p.add_argument("--ports-dir",          metavar="DIR", default=None)
    p.add_argument("--ports-secondary",    metavar="DIR", default=None)
    p.add_argument("--impls-dir",          metavar="DIR", default=None)
    p.add_argument("--verbose",  "-v",     action="store_true")
    p.add_argument("--json",               metavar="FILE")
    p.add_argument("--format",             choices=["text", "json", "both"], default="text")
    p.add_argument("--limit",              type=int, default=50)
    p.add_argument("--no-rca",             action="store_true")
    p.add_argument("--no-dup",             action="store_true")
    p.add_argument("--dup-scope-limited",  action="store_true")
    p.add_argument("--strict-types",       action="store_true")
    p.add_argument("--fix-suggestions",    action="store_true")
    p.add_argument("--dry-run",            action="store_true")
    p.add_argument("--self-test",          action="store_true")
    p.add_argument("--debug",              action="store_true")
    p.add_argument("--exclude",            default="", metavar="DIRS", help="Comma-separated extra dirs to exclude")
    p.add_argument("--max-workers",        type=int, default=4)
    p.add_argument("--no-progress",        action="store_true")
    p.add_argument("--version",            action="version", version=f"%(prog)s {__version__}")
    return p


def main() -> None:
    args = _build_parser().parse_args()

    if args.self_test:
        sys.exit(0 if _run_self_test() else 1)

    if args.debug:
        logger.setLevel(logging.DEBUG)

    root = pathlib.Path(args.root).resolve() if args.root else _DEFAULT_ROOT
    if not root.exists():
        _safe_print(f"{_c('RED')}[ERROR] Root not found: {root}{_c('RESET')}")
        sys.exit(2)

    extra_excludes: set[str] = set(args.exclude.split(",")) if args.exclude else set()

    _pb_lock = threading.Lock()
    _pb_current = [0]
    _pb_total   = [0]

    def _progress(current: int, total_: int) -> None:
        with _pb_lock:
            _pb_current[0] = current
            _pb_total[0]   = total_
        if args.no_progress or not sys.stdout.isatty():
            return
        pct = (current / total_ * 100) if total_ > 0 else 0
        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        _safe_print(f"\r  [{bar}] {current}/{total_} ({pct:.1f}%)", end="", flush=True)
        if current >= total_:
            _safe_print()

    try:
        data = scan_repositories(
            root=root,
            ports_dir=(pathlib.Path(args.ports_dir).resolve() if args.ports_dir else None),
            ports_secondary_dir=(pathlib.Path(args.ports_secondary).resolve() if args.ports_secondary else None),
            impls_dir=(pathlib.Path(args.impls_dir).resolve() if args.impls_dir else None),
            run_rca=not args.no_rca,
            run_dup=not args.no_dup,
            dup_full_scan=not args.dup_scope_limited,
            strict_types=args.strict_types,
            max_workers=args.max_workers,
            extra_excludes=extra_excludes,
            progress_callback=_progress,
        )
    except KeyboardInterrupt:
        _safe_print(f"\n{_c('YELLOW')}Interrupted.{_c('RESET')}")
        sys.exit(130)

    if args.format in ("text", "both"):
        print_report(
            data,
            verbose=args.verbose,
            limit=args.limit,
            show_fix_snippets=args.fix_suggestions,
        )

    if not args.dry_run:
        target = args.json
        if args.format in ("json", "both") and not target:
            target = "repository_checker_report.json"
        if target:
            save_json(data, target)
    else:
        _safe_print(f"\n{_c('YELLOW')}[DRY-RUN] No files written.{_c('RESET')}")

    _safe_print(f"\n  Audit time: {data.elapsed_seconds:.3f}s")

    if data.total_errors > 0:
        sys.exit(1)
    elif data.total_warnings > 0 or len(data.unmatched_interfaces) > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
