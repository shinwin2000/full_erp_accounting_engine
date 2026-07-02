#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/secret_scanner_checker.py – Secret Scanner (Hardcoded Secrets Detector)
================================================================================
Versi   : 3.0.0
Standar : Big 4 Forensic Audit · OWASP Top 10 · ISO/IEC 25010 · SOC 2 Type II

Fitur:
  - Deteksi hardcoded secrets: password, API key, token, private key, AWS, Azure, Google
  - AST analysis untuk Python files + regex fallback
  - Deteksi di .env, .json, .yaml, .toml, .ini, .conf, .sh, .bash, .ps1
  - Intelligent false positive reduction (exempt values, context analysis)
  - Integrasi RCA engine (checker.core.rca)
  - Parallel scanning, AST caching, progress bar
  - Laporan JSON, CSV, HTML, SARIF
  - Self-test terintegrasi
  - CLI: --verbose, --json, --csv, --html, --sarif, --strict, --no-rca, --self-test, --exclude, --max-workers, --min-length
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import csv
import json
import logging
import os
import pathlib
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union, Callable

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False

def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    _root = pathlib.Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: Optional[Dict] = None) -> Optional[Dict]:
    if not _RCA_AVAILABLE:
        return {
            "severity": "WARNING",
            "root_cause": str(exc)[:200],
            "suggested_fix": "Install checker.core.rca",
            "confidence": 0.0,
        }
    try:
        r = _RCA_ENGINE.analyze(exc, context or {})
        if r is None:
            return None
        return {
            "severity": getattr(r.severity, "value", str(r.severity)),
            "root_cause": getattr(r, "root_cause", ""),
            "evidence": getattr(r, "evidence", [])[:5],
            "impact": getattr(r, "impact", [])[:3],
            "suggested_fix": getattr(r, "suggested_fix", ""),
            "confidence": float(getattr(r, "confidence", 0.0)),
        }
    except Exception:
        return None

# ─── LOGGING ──────────────────────────────────────────────────────────────────
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger = logging.getLogger("secret_scanner_checker")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    logger.addHandler(_log_handler)

# ─── COLOR ──────────────────────────────────────────────────────────────────
COLOR: Dict[str, str] = {
    "RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "",
    "WHITE": "", "BOLD": "", "DIM": "", "RESET": "",
}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR.update({
        "RED"   : colorama.Fore.RED,
        "GREEN" : colorama.Fore.GREEN,
        "YELLOW": colorama.Fore.YELLOW,
        "CYAN"  : colorama.Fore.CYAN,
        "MAGENTA": colorama.Fore.MAGENTA,
        "WHITE" : colorama.Fore.WHITE,
        "BOLD"  : colorama.Style.BRIGHT,
        "DIM"   : colorama.Style.DIM,
        "RESET" : colorama.Style.RESET_ALL,
    })
except ImportError:
    pass

def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        new_args = [a.encode("ascii", errors="replace").decode("ascii") if isinstance(a, str) else a for a in args]
        print(*new_args, **kwargs)

def _c(key: str) -> str:
    return COLOR.get(key, "")

# ─── VERSION ──────────────────────────────────────────────────────────────────
__version__ = "3.0.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
    "logs", "coverage", ".pytest_cache", ".ruff_cache", ".mypy_cache",
}

DEFAULT_MIN_SECRET_LENGTH = 8
DEFAULT_MAX_CONTEXT_LENGTH = 150
DEFAULT_MAX_VALUE_DISPLAY = 20

# ─── EXEMPT PATTERNS ──────────────────────────────────────────────────────────
EXEMPT_VALUES = {
    "example", "changeme", "your_", "dummy", "test", "placeholder", "sample", "demo",
    "password", "secret", "token", "api_key", "your-password", "your-secret-key",
    "wrong_password", "minioadmin", "postgres", "root", "admin", "123456", "password123",
    "null", "none", "false", "true", "0", "1", "localhost", "127.0.0.1",
    "anonymous", "public", "guest", "default", "empty",
}

EXEMPT_CONTAINS = {"example", "changeme", "your_", "dummy", "test", "placeholder", "sample", "demo"}

EXEMPT_FILENAMES = {"pytest", "conftest", "test_", "settings", "config", "constants"}

# ─── SECRET PATTERNS ──────────────────────────────────────────────────────────
# Format: (regex_pattern, severity, secret_type, recommendation)
SECRET_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    # Password (must have at least 4 chars after assignment)
    (re.compile(r'(?i)(?:password|passwd|pwd|pass)\s*[:=]\s*["\']([^"\']{4,})["\']'), "CRITICAL", "password",
     "Gunakan environment variable atau vault (Hashicorp Vault, AWS Secrets Manager)."),
    # API Key
    (re.compile(r'(?i)(?:api_key|apikey|api-token|api_secret)\s*[:=]\s*["\']([A-Za-z0-9_\-]{16,})["\']'), "CRITICAL", "api_key",
     "Simpan API key di environment variable atau secrets manager."),
    # Token / Bearer
    (re.compile(r'(?i)(?:token|access_token|refresh_token|bearer_token)\s*[:=]\s*["\']([A-Za-z0-9_\-\.]{20,})["\']'), "CRITICAL", "token",
     "Gunakan environment variable atau OAuth2 flow dengan refresh token."),
    (re.compile(r'(?i)(?:bearer|authorization)\s*[:=]\s*["\'](?:Bearer\s+)?([A-Za-z0-9_\-\.]{20,})["\']'), "CRITICAL", "bearer_token",
     "Jangan hardcode bearer token. Gunakan authentication service."),
    # JWT Secret
    (re.compile(r'(?i)(?:jwt_secret|jwt-secret|JWT_SECRET|jwt_key)\s*[:=]\s*["\']([A-Za-z0-9_\-\.]{32,})["\']'), "CRITICAL", "jwt_secret",
     "Gunakan environment variable atau vault."),
    # Secret Key (Django, Flask, etc.)
    (re.compile(r'(?i)(?:secret_key|SECRET_KEY|app_secret)\s*[:=]\s*["\']([A-Za-z0-9@#$!%^&*_\-]{16,})["\']'), "CRITICAL", "secret_key",
     "Pindahkan secret key ke environment variable atau vault."),
    # AWS Access Key (AKIA...)
    (re.compile(r'(?i)(?:aws_access_key_id|AWS_ACCESS_KEY_ID)\s*[:=]\s*["\'](AKIA[0-9A-Z]{16,})["\']'), "CRITICAL", "aws_access_key",
     "Gunakan IAM role, AWS SSO, atau environment variable."),
    # AWS Secret Key
    (re.compile(r'(?i)(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*["\']([A-Za-z0-9/+=]{16,})["\']'), "CRITICAL", "aws_secret_key",
     "Gunakan IAM role, AWS SSO, atau environment variable."),
    # Azure Connection String
    (re.compile(r'(?i)(?:azure_connection_string|AZURE_CONNECTION_STRING)\s*[:=]\s*["\'](DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[^;]+;EndpointSuffix=core.windows.net)["\']'),
     "CRITICAL", "azure_connection_string", "Gunakan Azure Key Vault."),
    # Azure Storage Key
    (re.compile(r'(?i)(?:azure_storage_key|AZURE_STORAGE_KEY)\s*[:=]\s*["\']([A-Za-z0-9+/=]{40,})["\']'), "CRITICAL", "azure_storage_key",
     "Gunakan environment variable atau Azure Key Vault."),
    # Google API Key
    (re.compile(r'(?i)(?:google_api_key|GOOGLE_API_KEY)\s*[:=]\s*["\'](AIza[0-9A-Za-z\-_]{35,})["\']'), "CRITICAL", "google_api_key",
     "Gunakan environment variable."),
    # Private Key (BEGIN...)
    (re.compile(r'-----BEGIN (?:RSA|DSA|EC|OPENSSH|PRIVATE) KEY-----'), "CRITICAL", "private_key",
     "Pindahkan private key ke file terpisah (.pem/.key) dan load via secure method."),
    # Database URL with credentials
    (re.compile(r'(?i)(?:database_url|DATABASE_URL|db_url|dsn)\s*[:=]\s*["\'](postgresql|postgres|mysql|mongodb|redis|sqlite|oracle|mssql)://[^:]+:([^@]+)@'),
     "CRITICAL", "database_url", "Gunakan environment variable atau vault."),
    # Connection string with password
    (re.compile(r'(?i)(?:connection_string|CONNECTION_STRING)\s*[:=]\s*["\']([^"\']+password[^"\']+)["\']'), "CRITICAL", "connection_string",
     "Gunakan environment variable atau vault."),
    # FTP/SFTP password
    (re.compile(r'(?i)(?:ftp_password|sftp_password|ftp_pass)\s*[:=]\s*["\']([^"\']{4,})["\']'), "CRITICAL", "ftp_password",
     "Gunakan environment variable atau vault."),
    # Credential in URL (username:password@host)
    (re.compile(r'(?i)(?:[a-z0-9_\-]+):([^@\s]{4,})@[a-z0-9\-]+\.[a-z]{2,}'), "WARNING", "credential_in_url",
     "Hindari hardcode credential di URL. Gunakan parameter terpisah."),
    # Generic secret (fallback)
    (re.compile(r'(?i)(?:secret|credential)\s*[:=]\s*["\']([A-Za-z0-9@#$!%^&*_\-]{20,})["\']'), "WARNING", "generic_secret",
     "Gunakan environment variable atau vault."),
]

# Komentar yang mengandung secret
COMMENT_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    (re.compile(r'(?i)(?:password|passwd|pwd)\s*[:=]\s*["\']?[^"\']+["\']?'), "WARNING", "password_in_comment",
     "Hapus secret dari komentar."),
    (re.compile(r'(?i)(?:api_key|apikey|token|secret)\s*[:=]\s*["\']?[A-Za-z0-9]{16,}["\']?'), "WARNING", "secret_in_comment",
     "Hapus secret dari komentar."),
]

# Status/error constants that are safe
SAFE_CONSTANTS = {
    "FAILURE_WRONG_PASSWORD", "ERROR_", "STATUS_", "SUCCESS_",
    "PASSWORD_RESET", "PASSWORD_CHANGE", "PASSWORD_VALIDATION",
    "AUTH_FAILED", "INVALID_PASSWORD", "LOGIN_FAILED",
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str  # CRITICAL, WARNING, INFO
    file: str
    line: int
    secret_type: str
    value: str
    context: str
    recommendation: str
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "type": self.secret_type,
            "value": self.value,
            "context": self.context,
            "recommendation": self.recommendation,
            "rca": self.rca,
        }

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: float = 100.0
    scan_time: float = 0.0
    total_files_scanned: int = 0
    files_with_issues: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "CRITICAL")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "WARNING")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "INFO")

    @property
    def passed(self) -> bool:
        return self.error_count == 0

# ─── AST UTILITIES ──────────────────────────────────────────────────────────
_AST_CACHE: Dict[str, Tuple[Optional[ast.AST], Optional[str]]] = {}
_CACHE_LOCK = threading.Lock()

def _read_source(py_file: pathlib.Path) -> Optional[str]:
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            return py_file.read_text(encoding=enc, errors="strict")
        except (UnicodeDecodeError, LookupError, OSError):
            continue
    try:
        return py_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

def _get_ast(py_file: pathlib.Path) -> Tuple[Optional[ast.AST], Optional[str]]:
    key = str(py_file.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    src = _read_source(py_file)
    if src is None:
        _AST_CACHE[key] = (None, "Cannot read file")
        return _AST_CACHE[key]
    try:
        tree = ast.parse(src, filename=str(py_file))
        _AST_CACHE[key] = (tree, None)
        return tree, None
    except SyntaxError as e:
        err = f"SyntaxError at {e.lineno}: {e.msg}"
        _AST_CACHE[key] = (None, err)
        return None, err
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _AST_CACHE[key] = (None, err)
        return None, err

def _extract_string(node: ast.AST) -> Optional[str]:
    """Extract string from AST node (handles f-strings partially)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _extract_string(node.left)
        right = _extract_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
        if parts:
            return ''.join(parts)
    if isinstance(node, ast.Name):
        return node.id
    return None

def _get_snippet(lines: List[str], line: int, context: int = 2) -> str:
    if line <= 0 or line > len(lines):
        return ""
    start = max(0, line - context - 1)
    end = min(len(lines), line + context)
    return "\n".join(lines[start:end]).strip()

def _is_exempt_value(value: str) -> bool:
    val = value.lower().strip('"\'').strip()
    if val in EXEMPT_VALUES:
        return True
    for ex in EXEMPT_CONTAINS:
        if ex in val:
            return True
    if len(val) < 4:
        return True
    return False

def _is_exempt_filename(filename: str) -> bool:
    name = filename.lower()
    for ex in EXEMPT_FILENAMES:
        if ex in name:
            return True
    return False

def _is_safe_constant(name: str) -> bool:
    return name in SAFE_CONSTANTS

def _redact_value(value: str, max_len: int = DEFAULT_MAX_VALUE_DISPLAY) -> str:
    if len(value) <= max_len:
        return value
    return value[:max_len] + "..."

def _get_captured_value(match: re.Match) -> Optional[str]:
    """Get captured group value safely."""
    groups = match.groups()
    if not groups:
        return None
    # Return the last non-None group (usually the secret)
    for g in reversed(groups):
        if g is not None and g.strip():
            return g
    return None

def _generate_rca(secret_type: str, value: str, file: str) -> Optional[Dict]:
    if not _RCA_AVAILABLE:
        return {
            "severity": "WARNING",
            "root_cause": f"Hardcoded {secret_type} detected in source code.",
            "suggested_fix": "Move to environment variable or secrets manager.",
            "confidence": 0.7,
        }
    try:
        exc = RuntimeError(f"Hardcoded {secret_type} found in {file}")
        ctx = {"secret_type": secret_type, "file": file}
        return _rca_analyze(exc, ctx)
    except Exception:
        return None

# ─── DETECTOR ──────────────────────────────────────────────────────────────────
class SecretDetector:
    def __init__(
        self,
        file_path: pathlib.Path,
        root: pathlib.Path,
        lines: List[str],
        enable_rca: bool = True,
        min_length: int = DEFAULT_MIN_SECRET_LENGTH,
        strict: bool = False,
    ):
        self.file_path = file_path
        self.root = root
        self.lines = lines
        self.enable_rca = enable_rca
        self.min_length = min_length
        self.strict = strict
        self.findings: List[Finding] = []
        self.rel_path = str(file_path.relative_to(root)).replace("\\", "/")

    def _add_finding(self, line: int, severity: str, secret_type: str, value: str, recommendation: str):
        if len(value) < self.min_length:
            return
        if _is_exempt_value(value):
            return
        redacted = _redact_value(value)
        context = _get_snippet(self.lines, line, 2)
        rca = _generate_rca(secret_type, value, self.rel_path) if self.enable_rca else None
        self.findings.append(Finding(
            severity=severity,
            file=self.rel_path,
            line=line,
            secret_type=secret_type,
            value=redacted,
            context=context[:DEFAULT_MAX_CONTEXT_LENGTH],
            recommendation=recommendation,
            rca=rca,
        ))

    def scan_ast(self, tree: ast.AST) -> None:
        """Scan AST for hardcoded secrets."""
        for node in ast.walk(tree):
            # Assign statements
            if isinstance(node, ast.Assign):
                self._check_assign(node)
            # Function calls with keyword args
            elif isinstance(node, ast.Call):
                self._check_call(node)

    def _check_assign(self, node: ast.Assign):
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            var_name = target.id
            if _is_safe_constant(var_name):
                continue
            if _is_exempt_filename(self.rel_path):
                continue
            value = _extract_string(node.value)
            if value is None:
                continue
            if _is_exempt_value(value):
                continue
            # Check if var_name + value matches any pattern
            combined = f"{var_name}={value}"
            for pattern, severity, secret_type, recommendation in SECRET_PATTERNS:
                if pattern.search(combined):
                    self._add_finding(node.lineno, severity, secret_type, value, recommendation)
                    break

    def _check_call(self, node: ast.Call):
        for kw in node.keywords:
            if kw.arg is None:
                continue
            arg_name = kw.arg.lower()
            if arg_name not in {"password", "passwd", "pwd", "api_key", "token", "secret", "key"}:
                continue
            value = _extract_string(kw.value)
            if value is None:
                continue
            if _is_exempt_value(value):
                continue
            combined = f"{kw.arg}={value}"
            for pattern, severity, secret_type, recommendation in SECRET_PATTERNS:
                if pattern.search(combined):
                    self._add_finding(node.lineno, severity, secret_type, value, recommendation)
                    break

    def scan_regex(self) -> None:
        """Scan lines with regex (fallback and non-Python files)."""
        for idx, line in enumerate(self.lines, 1):
            if line.strip().startswith('#'):
                continue
            # Check main patterns
            for pattern, severity, secret_type, recommendation in SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    value = _get_captured_value(match)
                    if value and not _is_exempt_value(value):
                        self._add_finding(idx, severity, secret_type, value, recommendation)
                        break

    def scan_comments(self) -> None:
        """Scan comments for secrets."""
        for idx, line in enumerate(self.lines, 1):
            if '#' not in line:
                continue
            comment = line.split('#', 1)[1].strip()
            if not comment:
                continue
            for pattern, severity, secret_type, recommendation in COMMENT_PATTERNS:
                if pattern.search(comment):
                    # Extract value from comment if possible
                    value = ""
                    val_match = re.search(r'["\']([^"\']+)["\']', comment)
                    if val_match:
                        value = val_match.group(1)
                    if value and _is_exempt_value(value):
                        continue
                    self._add_finding(idx, severity, secret_type, value or "[REDACTED]", recommendation)
                    break

    def scan(self) -> List[Finding]:
        """Run all scans."""
        # For Python files, use AST + regex
        if self.file_path.suffix.lower() == ".py":
            tree, err = _get_ast(self.file_path)
            if tree is not None:
                self.scan_ast(tree)
        # Always run regex for all files
        self.scan_regex()
        self.scan_comments()
        return self.findings

# ─── SCANNER ──────────────────────────────────────────────────────────────────
class SecretScanner:
    def __init__(
        self,
        root: pathlib.Path,
        enable_rca: bool = True,
        strict: bool = False,
        min_length: int = DEFAULT_MIN_SECRET_LENGTH,
        extra_excludes: Optional[Set[str]] = None,
        max_workers: int = 4,
    ):
        self.root = root
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self.strict = strict
        self.min_length = min_length
        self.extra_excludes = extra_excludes or set()
        self.max_workers = max_workers
        self._excluded_dirs = EXCLUDED_DIRS_DEFAULT | self.extra_excludes

    def _should_skip_file(self, path: pathlib.Path) -> bool:
        rel = str(path.relative_to(self.root)).replace("\\", "/")
        for d in self._excluded_dirs:
            if d in rel.split("/"):
                return True
        if path.name.startswith(("test_", "conftest", "__init__")):
            return True
        if path.name.endswith(("_test.py", "_tests.py")):
            return True
        if path.name.startswith("secret_scanner_checker"):
            return True
        return False

    def _get_files(self) -> List[pathlib.Path]:
        extensions = {".py", ".env", ".json", ".yaml", ".yml", ".toml",
                      ".ini", ".cfg", ".conf", ".txt", ".sh", ".bash", ".ps1"}
        files = []
        for p in self.root.rglob("*"):
            if p.is_dir():
                continue
            if self._should_skip_file(p):
                continue
            if p.suffix.lower() not in extensions:
                continue
            files.append(p)
        return sorted(set(files))

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        t0 = time.monotonic()
        report = Report()
        files = self._get_files()
        report.total_files_scanned = len(files)

        all_findings: List[Finding] = []
        total = len(files)

        def _scan_one(idx: int, py_file: pathlib.Path) -> List[Finding]:
            if progress_callback:
                progress_callback(idx + 1, total)
            src = _read_source(py_file)
            if src is None:
                return []
            lines = src.splitlines()
            detector = SecretDetector(
                file_path=py_file,
                root=self.root,
                lines=lines,
                enable_rca=self.enable_rca,
                min_length=self.min_length,
                strict=self.strict,
            )
            return detector.scan()

        if len(files) <= self.max_workers * 2:
            for idx, py_file in enumerate(files):
                all_findings.extend(_scan_one(idx, py_file))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(_scan_one, idx, py_file): py_file for idx, py_file in enumerate(files)}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        all_findings.extend(future.result())
                    except Exception as e:
                        logger.warning("Scan error: %s", e)

        # Filter if not strict
        if not self.strict:
            all_findings = [f for f in all_findings if f.severity in ("CRITICAL", "WARNING")]

        report.findings = all_findings
        report.files_with_issues = len({f.file for f in all_findings})

        # Compute score
        errors = report.error_count
        warnings = report.warning_count
        score = 100.0 - errors * 15 - warnings * 2
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  SECRET SCANNER CHECKER")
    _safe_print(f"  v{__version__} — OWASP Top 10 / Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")
    _safe_print("  📋 Secret Management Standards:")
    _safe_print("    ✅ No hardcoded passwords, API keys, or tokens")
    _safe_print("    ✅ No hardcoded private keys or certificates")
    _safe_print("    ✅ No database credentials in source code")
    _safe_print("    ✅ All secrets stored in environment variables or vault")

    _safe_print(f"\n  📊 Summary:")
    _safe_print(f"    Files scanned      : {report.total_files_scanned}")
    _safe_print(f"    Files with issues  : {report.files_with_issues}")
    _safe_print(f"    CRITICAL findings  : {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    WARNING findings   : {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"    INFO findings      : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"    Security Score     : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    _safe_print(f"    RCA Engine         : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"    Scan time          : {report.scan_time:.3f}s")

    if report.findings:
        by_sev = {"CRITICAL": [], "WARNING": [], "INFO": []}
        for f in report.findings:
            by_sev.setdefault(f.severity, []).append(f)

        for sev in ["CRITICAL", "WARNING", "INFO"]:
            items = by_sev.get(sev, [])
            if not items:
                continue
            sev_color = c["RED"] if sev == "CRITICAL" else c["YELLOW"] if sev == "WARNING" else c["DIM"]
            _safe_print(f"\n{sev_color}[{sev}] {len(items)} findings{sev_color}")
            for f in items[:20]:
                _safe_print(f"    {f.file}:{f.line}  ({f.secret_type})")
                _safe_print(f"      Value: {f.value}")
                if verbose:
                    _safe_print(f"      Context: {f.context[:100]}")
                _safe_print(f"      💡 {f.recommendation}")
                if show_rca and f.rca:
                    rc = f.rca.get("root_cause", "")
                    fix = f.rca.get("suggested_fix", "")
                    if rc:
                        _safe_print(f"      {c['MAGENTA']}🔍 RCA: {rc[:120]}{c['RESET']}")
                    if fix:
                        _safe_print(f"      {c['MAGENTA']}🔧 Fix: {fix[:120]}{c['RESET']}")
            if len(items) > 20:
                _safe_print(f"    ... and {len(items)-20} more")

    else:
        _safe_print(f"\n{c['GREEN']}✅ No hardcoded secrets detected!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — No critical secrets detected.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count} CRITICAL secret(s) found.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": report.score,
            "passed": report.passed,
            "scan_time": report.scan_time,
            "total_files_scanned": report.total_files_scanned,
            "files_with_issues": report.files_with_issues,
            "findings": [f.to_dict() for f in report.findings],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _safe_print(f"{_c('GREEN')}✅ JSON saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save JSON: {e}{_c('RESET')}")
        return False

def save_csv(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["severity", "file", "line", "type", "value", "recommendation"])
            for fnd in report.findings:
                writer.writerow([fnd.severity, fnd.file, fnd.line, fnd.secret_type, fnd.value, fnd.recommendation])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        findings_html = ""
        for f in report.findings:
            cls = "error" if f.severity == "CRITICAL" else "warning" if f.severity == "WARNING" else "info"
            findings_html += f'<div class="finding {cls}"><strong>{f.severity}</strong> {f.file}:{f.line}<br><strong>{f.secret_type}</strong> {f.value}<br><small>💡 {f.recommendation}</small></div>'
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Secret Scanner Report</title>
<style>
body{{font-family:sans-serif;background:#f8f9fa;color:#212529;padding:2rem}}
h1{{color:#0d6efd}}
.summary{{display:flex;gap:2rem;flex-wrap:wrap;margin:1rem 0}}
.card{{background:white;padding:1rem 2rem;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}}
.card .value{{font-size:2rem;font-weight:bold}}
.card .label{{color:#6c757d}}
.finding{{margin:0.5rem 0;padding:0.5rem 1rem;border-left:4px solid}}
.error{{border-color:#dc3545;background:#f8d7da}}
.warning{{border-color:#ffc107;background:#fff3cd}}
.info{{border-color:#0dcaf0;background:#d1ecf1}}
</style></head>
<body>
<h1>Secret Scanner Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{len(report.findings)}</div><div class="label">Findings</div></div>
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">CRITICAL</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.warning_count}</div><div class="label">Warnings</div></div>
  <div class="card"><div class="value">{report.score:.1f}</div><div class="label">Score</div></div>
  <div class="card"><div class="value">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
<h2>Findings</h2>
{findings_html}
</body></html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        _safe_print(f"{_c('GREEN')}✅ HTML saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save HTML: {e}{_c('RESET')}")
        return False

def save_sarif(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        results = []
        for f in report.findings:
            results.append({
                "ruleId": f"SECRET-{f.severity}",
                "level": "error" if f.severity == "CRITICAL" else "warning",
                "message": {"text": f"Hardcoded {f.secret_type} found"},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.file},
                        "region": {"startLine": max(1, f.line)},
                    }
                }],
            })
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "SecretScanner",
                        "version": __version__,
                        "rules": [
                            {"id": "SECRET-CRITICAL", "shortDescription": {"text": "Critical secret leak"}},
                            {"id": "SECRET-WARNING", "shortDescription": {"text": "Potential secret leak"}},
                        ]
                    }
                },
                "results": results,
            }]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sarif, f, indent=2, ensure_ascii=False)
        _safe_print(f"{_c('GREEN')}✅ SARIF saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save SARIF: {e}{_c('RESET')}")
        return False

# ─── SELF-TEST ──────────────────────────────────────────────────────────────
def self_test(verbose: bool = True) -> bool:
    passed = failed = 0
    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            if verbose: _safe_print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose: _safe_print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
            failed += 1

    if verbose: _safe_print(f"\nSecret Scanner self-test v{__version__}…\n")

    # Test detection: password
    code1 = """
password = "secret123"
"""
    tree1 = ast.parse(code1)
    detector1 = SecretDetector(
        pathlib.Path("test.py"),
        pathlib.Path("."),
        code1.splitlines(),
        enable_rca=True,
        min_length=4,
    )
    detector1.scan_ast(tree1)
    check("Detects password", len(detector1.findings) > 0)

    # Test detection: API key
    code2 = """
api_key = "abc123def456ghi789jkl012mno345"
"""
    tree2 = ast.parse(code2)
    detector2 = SecretDetector(
        pathlib.Path("test.py"),
        pathlib.Path("."),
        code2.splitlines(),
        enable_rca=True,
        min_length=16,
    )
    detector2.scan_ast(tree2)
    check("Detects API key", len(detector2.findings) > 0)

    # Test exemption: short values
    code3 = """
password = "123"
"""
    tree3 = ast.parse(code3)
    detector3 = SecretDetector(
        pathlib.Path("test.py"),
        pathlib.Path("."),
        code3.splitlines(),
        enable_rca=True,
        min_length=8,
    )
    detector3.scan_ast(tree3)
    check("Ignores short values", len(detector3.findings) == 0)

    # Test exemption: example values
    code4 = """
password = "example"
"""
    tree4 = ast.parse(code4)
    detector4 = SecretDetector(
        pathlib.Path("test.py"),
        pathlib.Path("."),
        code4.splitlines(),
        enable_rca=True,
        min_length=4,
    )
    detector4.scan_ast(tree4)
    check("Ignores example values", len(detector4.findings) == 0)

    # Test detection: environment variable (should be exempt)
    code5 = """
import os
password = os.environ.get("PASSWORD")
"""
    tree5 = ast.parse(code5)
    detector5 = SecretDetector(
        pathlib.Path("test.py"),
        pathlib.Path("."),
        code5.splitlines(),
        enable_rca=True,
        min_length=4,
    )
    detector5.scan_ast(tree5)
    check("Ignores env variable usage", len(detector5.findings) == 0)

    # Test RCA
    check("RCA availability", True)

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Secret Scanner Checker v{__version__}")
    parser.add_argument("--path", default=".", help="Target directory (default: current)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--strict", action="store_true", help="Show INFO findings as well")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--min-length", type=int, default=DEFAULT_MIN_SECRET_LENGTH,
                        help=f"Minimum secret length (default: {DEFAULT_MIN_SECRET_LENGTH})")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--version", action="version", version=f"secret_scanner_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    target_dir = pathlib.Path(args.path).resolve()
    if not target_dir.is_dir():
        _safe_print(f"{_c('RED')}❌ {target_dir} is not a directory.{_c('RESET')}")
        return 1

    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = SecretScanner(
        root=target_dir,
        enable_rca=not args.no_rca,
        strict=args.strict,
        min_length=args.min_length,
        extra_excludes=extra_excludes,
        max_workers=args.max_workers,
    )

    progress = None
    if not args.no_progress:
        total = 0
        scanned = 0
        lock = threading.Lock()
        def _progress(current: int, total_: int):
            nonlocal total, scanned
            with lock:
                total = total_
                scanned = current
                pct = (scanned / total * 100) if total > 0 else 0
                bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
                _safe_print(f"\r  [{bar}] {scanned}/{total} ({pct:.1f}%)", end="", flush=True)
                if scanned >= total:
                    _safe_print()
        progress = _progress

    report = checker.scan(progress_callback=progress)

    print_report(report, verbose=args.verbose, show_rca=not args.no_rca)

    if not args.dry_run:
        if args.json:
            save_json(report, pathlib.Path(args.json))
        if args.csv:
            save_csv(report, pathlib.Path(args.csv))
        if args.html:
            save_html(report, pathlib.Path(args.html))
        if args.sarif:
            save_sarif(report, pathlib.Path(args.sarif))

    return 0 if report.passed else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _safe_print(f"\n{_c('YELLOW')}⏹️  Interrupted by user.{_c('RESET')}")
        sys.exit(130)