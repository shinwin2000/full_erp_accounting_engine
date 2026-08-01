#!/usr/bin/env python3
"""Hardened Security Checker v1.0.0 for Python/ERP projects.

Static security gate for:
1) input validation, 2) injection/output safety, 3) authentication/
   authorization, 4) cryptography, 5) error/info leakage, 6) dependencies,
7) least privilege, plus secrets, uploads, session/CORS/rate-limit/config.

Static findings are evidence, not proof of exploitability. The score is
advisory; CRITICAL findings and excessive HIGH findings block the gate.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
SEV_PENALTY = {"CRITICAL": 25.0, "HIGH": 10.0, "MEDIUM": 3.0, "LOW": 1.0, "INFO": 0.0}
IGNORED_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox", "node_modules", "dist", "build", "coverage", "htmlcov", ".idea", ".vscode", "site-packages"}
TEST_MARKERS = {"test", "tests", "testing"}
PY_EXTENSIONS = {".py", ".pyi"}

SECRET_LITERAL_RE = re.compile(r'''(?ix)\b(?:password|passwd|secret|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?token|client[_-]?secret|private[_-]?key)\b\s*(?::|==?)\s*["']([^"']{6,})["']''')
AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
SQL_FMT_RE = re.compile(r"(?i)\b(select|insert|update|delete|merge|where|from)\b.*(?:%\(|\{\w+\}|\bf[\"'])")
SECRET_WORD_RE = re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token|authorization|cookie)\b")
WEAK_HASHES = {"md5", "sha1", "md4"}
AUTH_NAMES = {"login_required", "requires_auth", "require_auth", "jwt_required", "permission_required", "roles_required", "requires_permission", "authorize", "require_role", "require_permission"}
ROUTE_NAMES = {"get", "post", "put", "patch", "delete", "options", "head", "route", "api_route", "websocket"}
SECURITY_SENSITIVE_NAMES = {"login", "authenticate", "authorize", "approve", "post", "reverse", "delete", "close", "reopen", "payment", "transfer", "withdraw", "admin", "grant", "revoke", "impersonate", "reset_password", "change_password"}
RATE_LIMIT_NAMES = {"limiter", "rate_limit", "ratelimit", "throttle", "slowapi", "limits"}
UNSAFE_DESERIALIZATION = {("pickle", "load"), ("pickle", "loads"), ("dill", "load"), ("dill", "loads"), ("yaml", "load"), ("yaml", "unsafe_load"), ("yaml", "full_load"), ("marshal", "loads")}


@dataclass
class Finding:
    finding_id: str
    severity: str
    category: str
    title: str
    message: str
    file: str = ""
    line: int = 0
    column: int = 0
    symbol: str = ""
    evidence: str = ""
    remediation: str = ""
    scanner: str = "custom-ast"
    confidence: str = "HIGH"
    cwe: str = ""
    owasp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanStats:
    files_scanned: int = 0
    python_files: int = 0
    config_files: int = 0
    syntax_errors: int = 0
    external_scanner_errors: int = 0
    findings: int = 0
    generated_at: str = ""


@dataclass
class ScanReport:
    version: str
    project_root: str
    score: float
    verdict: str
    exit_code: int
    counts: dict[str, int]
    findings: list[Finding]
    stats: ScanStats
    external_scanners: dict[str, Any]
    gate: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["findings"] = [asdict(f) for f in self.findings]
        return d


def configure_utf8() -> None:
    if os.name == "nt":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


configure_utf8()


def relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def is_test_file(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return bool(parts & TEST_MARKERS) or path.name.startswith("test_")


MAX_SCAN_BYTES = 2 * 1024 * 1024  # skip files bigger than this for text scanning
BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin", ".o", ".a",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3", ".mp3", ".mp4", ".avi", ".mov", ".mkv",
    ".woff", ".woff2", ".ttf", ".eot", ".otf", ".class", ".jar",
    ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt",
}


def iter_files(root: Path, extra_ignored: set[str] | None = None) -> Iterable[Path]:
    # Walk with os.walk so we can prune ignored directories BEFORE descending
    # into them (root.rglob("*") would still traverse huge dirs like
    # node_modules/.venv/.git fully before filtering, which is what made
    # scans of real projects extremely slow or appear to hang). We also
    # explicitly avoid following symlinks to prevent infinite loops from
    # circular symlinks.
    ignored = IGNORED_DIRS | extra_ignored if extra_ignored else IGNORED_DIRS
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in ignored]
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            yield p


def node_text(source: str, node: ast.AST) -> str:
    if not isinstance(source, str) or not source:
        return ""
    try:
        return ast.get_source_segment(source, node) or ""
    except Exception:
        return ""


def split_lines_no_ff(source: str) -> list[str]:
    """Same line-splitting semantics as ast._splitlines_no_ff, computed once."""
    lines: list[str] = []
    start = 0
    n = len(source)
    i = 0
    while i < n:
        c = source[i]
        if c == "\r":
            if i + 1 < n and source[i + 1] == "\n":
                i += 1
            lines.append(source[start:i + 1])
            start = i + 1
        elif c == "\n":
            lines.append(source[start:i + 1])
            start = i + 1
        i += 1
    if start < n:
        lines.append(source[start:])
    return lines


def source_segment_from_lines(lines: list[str], node: ast.AST) -> str:
    """Equivalent of ast.get_source_segment but reuses pre-split lines instead
    of re-scanning the whole source on every call (that repeated re-scan is
    what made scanning large real-world files extremely slow)."""
    try:
        if getattr(node, "end_lineno", None) is None or getattr(node, "end_col_offset", None) is None:
            return ""
        lineno = node.lineno - 1
        end_lineno = node.end_lineno - 1
        col_offset = node.col_offset
        end_col_offset = node.end_col_offset
    except AttributeError:
        return ""

    if lineno < 0 or end_lineno < 0 or end_lineno >= len(lines):
        return ""

    try:
        if end_lineno == lineno:
            return lines[lineno].encode()[col_offset:end_col_offset].decode(errors="replace")
        first = lines[lineno].encode()[col_offset:].decode(errors="replace")
        last = lines[end_lineno].encode()[:end_col_offset].decode(errors="replace")
        middle = lines[lineno + 1:end_lineno]
        return "".join([first, *middle, last])
    except Exception:
        return ""


def call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        parts = []
        cur: ast.AST = f
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def decorator_name(dec: ast.AST) -> str:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def has_auth_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    names = {decorator_name(d).lower() for d in node.decorator_list}
    if names & {x.lower() for x in AUTH_NAMES}:
        return True
    return any("auth" in n or "permission" in n or "role" in n or "authoriz" in n for n in names)


def route_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, list[str]]:
    found, methods = False, []
    for d in node.decorator_list:
        if not isinstance(d, ast.Call):
            continue
        n = decorator_name(d)
        if n in ROUTE_NAMES:
            found = True
            if n not in {"route", "api_route"}:
                methods.append(n.upper())
            for kw in d.keywords:
                if kw.arg == "methods":
                    try:
                        v = ast.literal_eval(kw.value)
                        if isinstance(v, (list, tuple)):
                            methods += [str(x).upper() for x in v]
                    except Exception:
                        pass
    return found, sorted(set(methods))


def contains_sensitive_name(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in SECURITY_SENSITIVE_NAMES)


def looks_like_input(name: str) -> bool:
    low = name.lower()
    return any(x in low for x in ("request", "payload", "data", "body", "params", "query", "form", "file", "upload", "raw"))


def dedupe(findings: list[Finding]) -> list[Finding]:
    seen = set()
    out = []
    for f in findings:
        key = hashlib.sha256(
            json.dumps(
                {
                    "s": f.severity,
                    "c": f.category,
                    "t": f.title,
                    "f": f.file,
                    "l": f.line,
                    "y": f.symbol,
                    "e": f.evidence,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


class HardenedSecurityScanner:
    def __init__(
        self,
        root: str | Path,
        *,
        include_tests: bool = True,
        max_high: int = 0,
        run_external: bool = True,
        progress: bool = True,
        jobs: int = 1,
        exclude_dirs: set[str] | None = None,
    ):
        self.root = Path(root).resolve()
        self.include_tests = include_tests
        self.max_high = max(0, max_high)
        self.run_external = run_external
        self.progress = progress
        self.jobs = jobs
        self.exclude_dirs = exclude_dirs or set()
        self.inventory: list[Path] = []
        self.findings: list[Finding] = []
        self.stats = ScanStats(generated_at=datetime.now(UTC).isoformat())
        self.external: dict[str, Any] = {}

    def add(
        self,
        *,
        severity: str,
        category: str,
        title: str,
        message: str,
        path: Path | None = None,
        line: int = 0,
        column: int = 0,
        symbol: str = "",
        evidence: str = "",
        remediation: str = "",
        scanner: str = "custom-ast",
        confidence: str = "HIGH",
        cwe: str = "",
        owasp: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.findings.append(
            Finding(
                f"HSC-{len(self.findings)+1:05d}",
                severity,
                category,
                title,
                message,
                relpath(path, self.root) if path else "",
                line,
                column,
                symbol,
                evidence[:1000],
                remediation,
                scanner,
                confidence,
                cwe,
                owasp,
                metadata or {},
            )
        )

    def scan(self) -> ScanReport:
        started = time.perf_counter()

        # Collect files
        all_files = list(iter_files(self.root, self.exclude_dirs))
        if not self.include_tests:
            all_files = [p for p in all_files if not is_test_file(p)]
        self.inventory = all_files
        total = len(all_files)
        if self.progress:
            print(f"[HSC] Inventory: {total} files", flush=True)

        # Separate Python and non-Python
        py_files = [p for p in all_files if p.suffix in PY_EXTENSIONS]
        other_files = [p for p in all_files if p.suffix not in PY_EXTENSIONS]

        # Process Python files in parallel if jobs > 1
        findings_all: list[Finding] = []
        stats_combined = ScanStats(generated_at=self.stats.generated_at)

        if py_files:
            if self.jobs > 1:
                # Use multiprocessing
                num_workers = min(self.jobs, len(py_files))
                chunk_size = max(1, len(py_files) // num_workers)
                chunks = [py_files[i:i+chunk_size] for i in range(0, len(py_files), chunk_size)]
                args = [(chunk, self.root, self.include_tests) for chunk in chunks]

                if self.progress:
                    print(f"[HSC] Starting {len(chunks)} worker processes...", flush=True)

                try:
                    # Ensure multiprocessing uses spawn on Windows
                    if os.name == "nt":
                        mp.set_start_method("spawn", force=True)
                    with mp.Pool(processes=num_workers) as pool:
                        results = pool.map(scan_py_files_worker, args)
                except Exception as e:
                    if self.progress:
                        print(f"[HSC] Multiprocessing error: {e}, falling back to serial", flush=True)
                    results = []
                    # Fallback: process serially
                    for chunk in chunks:
                        findings_chunk, stats_chunk = scan_py_files_worker((chunk, self.root, self.include_tests))
                        results.append((findings_chunk, stats_chunk))
            else:
                # Serial processing (in-process, with periodic progress output
                # so a large scan doesn't look stuck).
                if self.progress:
                    print(f"[HSC] Processing {len(py_files)} Python files serially...", flush=True)
                findings_chunk: list[Finding] = []
                stats_chunk = ScanStats()
                report_every = 100
                for i, p in enumerate(py_files, 1):
                    try:
                        self.scan_file(p)
                    except Exception:
                        self.stats.syntax_errors += 1
                    if self.progress and (i % report_every == 0 or i == len(py_files)):
                        print(f"[HSC]   ...{i}/{len(py_files)} python files scanned", flush=True)
                findings_chunk = self.findings
                self.findings = []
                stats_chunk.files_scanned = len(py_files)
                stats_chunk.python_files = len(py_files)
                stats_chunk.findings = len(findings_chunk)
                results = [(findings_chunk, stats_chunk)]

            # Collect results
            for findings_chunk, stats_chunk in results:
                findings_all.extend(findings_chunk)
                stats_combined.files_scanned += stats_chunk.files_scanned
                stats_combined.python_files += stats_chunk.python_files
                stats_combined.syntax_errors += stats_chunk.syntax_errors
                stats_combined.findings += stats_chunk.findings

        # Process non-Python files (regex only) serially
        for p in other_files:
            self._scan_non_py_file(p)

        # Merge findings and stats
        self.findings = findings_all
        self.stats.files_scanned = stats_combined.files_scanned + len(other_files)
        self.stats.python_files = stats_combined.python_files
        self.stats.syntax_errors = stats_combined.syntax_errors
        self.stats.findings = len(self.findings)

        if self.progress:
            print("[HSC] Source scan complete; scanning project configuration...", flush=True)

        # Configuration and git scans (serial)
        self.scan_configs()
        self.scan_git()

        if self.progress:
            print("[HSC] Static scan complete; running external scanners..." if self.run_external else "[HSC] Static scan complete; external scanners disabled.", flush=True)
        if self.run_external:
            self.run_bandit()
            self.run_pip_audit()

        self.findings = sorted(dedupe(self.findings), key=lambda f: (SEVERITIES.index(f.severity), f.category, f.file, f.line, f.title))
        self.stats.findings = len(self.findings)

        if self.progress:
            print(f"[HSC] Finished in {time.perf_counter()-started:.1f}s", flush=True)

        return self.build_report()

    def _scan_non_py_file(self, path: Path) -> None:
        """Process non-Python files with regex only."""
        if path.suffix.lower() in BINARY_EXTENSIONS:
            return
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                return
        except OSError:
            return
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                source = path.read_text(encoding="utf-8-sig")
            except Exception:
                return
        except Exception:
            return
        self.scan_text(path, source)

    def scan_file(self, path: Path) -> None:
        """Scan a single Python file (used in worker)."""
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                return
        except OSError:
            return
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                source = path.read_text(encoding="utf-8-sig")
            except Exception:
                return
        except Exception:
            return

        self.scan_text(path, source)
        if path.suffix not in PY_EXTENSIONS:
            return

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as e:
            self.stats.syntax_errors += 1
            self.add(
                severity="HIGH",
                category="CONFIGURATION",
                title="Python source does not parse",
                message="Syntax errors prevent reliable security analysis.",
                path=path,
                line=e.lineno or 0,
                column=e.offset or 0,
                evidence=str(e),
                remediation="Fix syntax errors before merge.",
                confidence="CONFIRMED",
            )
            return

        try:
            ASTVisitor(self, path, source).visit(tree)
        except Exception as e:
            self.stats.syntax_errors += 1
            self.add(
                severity="HIGH",
                category="CONFIGURATION",
                title="AST visitor error",
                message=f"Error during AST analysis: {str(e)[:200]}",
                path=path,
                line=0,
                evidence=str(e)[:500],
                remediation="Check for malformed or overly complex Python code.",
                confidence="CONFIRMED",
            )

    def scan_text(self, path: Path, source: str) -> None:
        in_test = is_test_file(path)
        # Cheap heuristic to skip matches that live inside comment lines
        # (e.g. "# example: api_key = ...") so documentation/explanatory
        # text isn't reported as an actual hardcoded secret. Regex scanning
        # can't distinguish code from comments the way an AST can, so we
        # approximate with "line, once stripped, starts with #" — good
        # enough for Python/YAML/TOML/shell-style comments, and harmless
        # for formats that don't use '#' (it just won't match anything).
        text_lines = source.split("\n")

        def _in_comment(match_start: int) -> bool:
            idx = source.count("\n", 0, match_start)
            if 0 <= idx < len(text_lines):
                return text_lines[idx].lstrip().startswith("#")
            return False

        # Hardcoded secrets (generic "token = '...'" / "password == '...'"
        # pattern). The AST-based equivalent check (visit_Compare) already
        # skips test files entirely for this same pattern — apply the same
        # rule here so test fixtures with obviously fake values don't flood
        # the report as CRITICAL findings.
        if not in_test:
            for m in SECRET_LITERAL_RE.finditer(source):
                if _in_comment(m.start()):
                    continue
                self.add(
                    severity="CRITICAL",
                    category="SECRETS",
                    title="Possible hardcoded secret",
                    message="Credential-like literal found in source/configuration.",
                    path=path,
                    line=source.count("\n", 0, m.start()) + 1,
                    evidence=m.group(0),
                    remediation="Remove, rotate and store secrets in a secret manager or deployment secret store.",
                    scanner="regex",
                    confidence="MEDIUM",
                    cwe="CWE-798",
                    owasp="A05:2021",
                )

        # Specific secret patterns (actual key/token material: AWS keys,
        # GitHub tokens, JWTs, PEM private keys). Unlike the generic literal
        # pattern above, real key material in a test file is still worth
        # surfacing (it may be a leaked real key, or just bad hygiene to fix
        # later) — so we keep reporting it there, just at a lower severity
        # than in production code so it doesn't block the gate on its own.
        for rgx, title in (
            (AWS_KEY_RE, "Possible AWS access key"),
            (GITHUB_TOKEN_RE, "Possible GitHub token"),
            (JWT_RE, "Possible hardcoded JWT/token"),
            (PRIVATE_KEY_RE, "Private key material found"),
        ):
            for m in rgx.finditer(source):
                if _in_comment(m.start()):
                    continue
                self.add(
                    severity="MEDIUM" if in_test else "CRITICAL",
                    category="SECRETS",
                    title=title,
                    message="Credential or key material appears in repository content."
                    + (" (found in a test file; verify it is not a real, reused credential.)" if in_test else ""),
                    path=path,
                    line=source.count("\n", 0, m.start()) + 1,
                    evidence=m.group(0)[:200],
                    remediation="Remove from source control and rotate the credential/key.",
                    scanner="regex",
                    confidence="MEDIUM" if in_test else "HIGH",
                    cwe="CWE-798",
                    owasp="A05:2021",
                )

        # Configuration anti-patterns

        config_checks = [
            (
                re.compile(r"(?im)\bDEBUG\s*=\s*(True|1|['\"]true['\"])"),
                "Debug mode enabled",
                "HIGH",
                "CONFIGURATION",
                "Disable debug mode in production.",
            ),
            (
                re.compile(r"(?im)allow_origins\s*=\s*\[\s*['\"]\*['\"]\s*\]"),
                "Wildcard CORS origin",
                "HIGH",
                "CORS",
                "Allowlist exact trusted origins.",
            ),
            (
                re.compile(r"(?im)\bverify\s*=\s*False\b"),
                "TLS verification disabled",
                "HIGH",
                "CRYPTOGRAPHY",
                "Keep certificate verification enabled.",
            ),
        ]
        for rgx, title, sev, cat, remediation in config_checks:
            for m in rgx.finditer(source):
                self.add(
                    severity=sev,
                    category=cat,
                    title=title,
                    message=f"Potential insecure setting: {m.group(0)}",
                    path=path,
                    line=source.count("\n", 0, m.start()) + 1,
                    evidence=m.group(0),
                    remediation=remediation,
                    scanner="regex",
                    confidence="MEDIUM",
                    owasp="A05:2021" if cat != "CRYPTOGRAPHY" else "A02:2021",
                )

    def scan_configs(self) -> None:
        inventory = self.inventory or list(iter_files(self.root, self.exclude_dirs))

        # requirements.txt checks
        for p in inventory:
            if not p.name.startswith("requirements") or p.suffix != ".txt":
                continue
            if any(part in IGNORED_DIRS for part in p.relative_to(self.root).parts):
                continue
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                s = line.strip()
                if not s or s.startswith("#") or s.startswith("-"):
                    continue
                if "git+" in s or "http://" in s or "https://" in s:
                    self.add(
                        severity="MEDIUM",
                        category="DEPENDENCIES",
                        title="Dependency uses URL/VCS source",
                        message="Dependency is not represented as a normal immutable package pin.",
                        path=p,
                        line=i,
                        evidence=s,
                        remediation="Prefer reviewed package indexes and pinned/locked dependencies.",
                        confidence="HIGH",
                        cwe="CWE-829",
                        owasp="A06:2021",
                    )
                elif "==" not in s:
                    self.add(
                        severity="LOW",
                        category="DEPENDENCIES",
                        title="Dependency is not exactly pinned",
                        message="Range/unpinned dependency can change between builds.",
                        path=p,
                        line=i,
                        evidence=s,
                        remediation="Pin production dependencies or commit an auditable lock/constraints file.",
                        confidence="HIGH",
                        cwe="CWE-1104",
                        owasp="A06:2021",
                    )

        # Dockerfile checks
        for p in inventory:
            if not (p.name == "Dockerfile" or p.name.startswith("Dockerfile.")):
                continue
            if any(part in IGNORED_DIRS for part in p.relative_to(self.root).parts):
                continue
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            has_user = False
            for i, line in enumerate(lines, 1):
                s = line.strip()
                if re.match(r"(?i)^USER\s+", s):
                    has_user = True
                if re.match(r"(?i)^USER\s+root\b", s):
                    self.add(
                        severity="HIGH",
                        category="LEAST_PRIVILEGE",
                        title="Container runs as root",
                        message="Dockerfile explicitly uses root.",
                        path=p,
                        line=i,
                        evidence=s,
                        remediation="Create and use a dedicated non-root runtime user.",
                        confidence="HIGH",
                        cwe="CWE-250",
                        owasp="A05:2021",
                    )
            if not has_user:
                self.add(
                    severity="MEDIUM",
                    category="LEAST_PRIVILEGE",
                    title="Dockerfile has no USER instruction",
                    message="Runtime identity is not explicitly constrained to non-root.",
                    path=p,
                    remediation="Add a dedicated USER instruction for the application runtime.",
                    confidence="MEDIUM",
                    cwe="CWE-250",
                    owasp="A05:2021",
                )

        # docker-compose checks
        for compose_file in (
            self.root / "docker-compose.yml",
            self.root / "docker-compose.yaml",
            self.root / "compose.yml",
            self.root / "compose.yaml",
        ):
            if not compose_file.exists():
                continue
            try:
                t = compose_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if re.search(r"(?im)^\s*privileged\s*:\s*true\b", t):
                self.add(
                    severity="CRITICAL",
                    category="LEAST_PRIVILEGE",
                    title="Privileged container enabled",
                    message="Compose grants privileged mode.",
                    path=compose_file,
                    remediation="Remove privileged mode unless explicitly required and reviewed.",
                    confidence="HIGH",
                    cwe="CWE-250",
                )
            if re.search(r"(?im)^\s*user\s*:\s*['\"]?root\b", t):
                self.add(
                    severity="HIGH",
                    category="LEAST_PRIVILEGE",
                    title="Compose service runs as root",
                    message="A compose service uses root.",
                    path=compose_file,
                    remediation="Use a dedicated non-root uid/gid.",
                    confidence="HIGH",
                    cwe="CWE-250",
                )

        # Environment files
        for p in inventory:
            if not p.name.startswith(".env"):
                continue
            if p.name == ".env.example" or any(part in IGNORED_DIRS for part in p.relative_to(self.root).parts):
                continue
            self.add(
                severity="MEDIUM",
                category="SECRETS",
                title="Environment file exists in repository tree",
                message="Environment files commonly contain secrets.",
                path=p,
                remediation="Keep real environment secrets outside source control; commit only sanitized examples.",
                confidence="MEDIUM",
                cwe="CWE-540",
            )

        # GitHub Actions CI
        ci = self.root / ".github" / "workflows"
        if ci.exists():
            for p in ci.glob("*.y*ml"):
                try:
                    t = p.read_text(encoding="utf-8")
                except Exception:
                    continue
                if re.search(r"(?i)permissions:\s*write-all", t):
                    self.add(
                        severity="HIGH",
                        category="LEAST_PRIVILEGE",
                        title="CI workflow requests write-all permissions",
                        message="Workflow token permissions are overly broad.",
                        path=p,
                        remediation="Set least-privilege permissions per job.",
                        confidence="HIGH",
                        cwe="CWE-250",
                    )
                if "actions/checkout@" in t and "persist-credentials: false" not in t:
                    self.add(
                        severity="LOW",
                        category="LEAST_PRIVILEGE",
                        title="Checkout credentials are not explicitly disabled",
                        message="Git credentials may persist in the runner workspace.",
                        path=p,
                        remediation="Use persist-credentials: false unless later git auth is required.",
                        confidence="LOW",
                    )

    def scan_git(self) -> None:
        gi = self.root / ".gitignore"
        if not gi.exists():
            self.add(
                severity="MEDIUM",
                category="SECRETS",
                title="No .gitignore found",
                message="Local secrets/artifacts may be committed accidentally.",
                path=self.root,
                remediation="Create a reviewed .gitignore for secrets, caches and local artifacts.",
                confidence="MEDIUM",
                cwe="CWE-530",
            )

        git = shutil.which("git")
        if not git or not (self.root / ".git").exists():
            return

        try:
            p = subprocess.run(
                [git, "-C", str(self.root), "ls-files"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except Exception:
            return

        if p.returncode != 0:
            return

        for item in p.stdout.splitlines():
            n = Path(item).name.lower()
            if n in {".env", ".env.local", ".env.production"}:
                self.add(
                    severity="CRITICAL",
                    category="SECRETS",
                    title="Sensitive environment file is tracked by git",
                    message=f"Git tracks {item}.",
                    path=self.root / item,
                    remediation="Remove it from source control and rotate exposed secrets.",
                    confidence="CONFIRMED",
                    cwe="CWE-312",
                    owasp="A05:2021",
                )
            elif n.endswith((".pem", ".key")):
                self.add(
                    severity="HIGH",
                    category="SECRETS",
                    title="Key material is tracked by git",
                    message=f"Git tracks {item}.",
                    path=self.root / item,
                    remediation="Move key material to managed secret storage.",
                    confidence="HIGH",
                    cwe="CWE-540",
                )

    def run_bandit(self) -> None:
        exe = shutil.which("bandit")
        if not exe:
            self.external["bandit"] = {"status": "NOT_INSTALLED"}
            return

        # Keep bandit's own traversal consistent with ours: skip the same
        # ignored/user-excluded directories, both for correctness (don't
        # report on code the user explicitly excluded, e.g. --exclude
        # checker) and for speed (bandit -r otherwise walks node_modules/
        # .venv/etc. itself too, which is part of why it was timing out).
        skip_names = IGNORED_DIRS | self.exclude_dirs
        exclude_paths = ",".join(str(self.root / name) for name in sorted(skip_names))

        out = self.root / ".hsc_bandit.json"
        try:
            # DITAMBAHKAN FLAG -s B101 UNTUK MENGABAIKAN assert_used
            p = subprocess.run(
                [exe, "-r", str(self.root), "-f", "json", "-o", str(out), "-x", exclude_paths, "-s", "B101"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.stats.external_scanner_errors += 1
            self.external["bandit"] = {"status": "TIMEOUT"}
            return
        except Exception as e:
            self.stats.external_scanner_errors += 1
            self.external["bandit"] = {"status": "ERROR", "error": str(e)}
            return

        data = {}
        if out.exists():
            try:
                data = json.loads(out.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            try:
                out.unlink()
            except Exception:
                pass

        results = data.get("results", []) if isinstance(data, dict) else []
        self.external["bandit"] = {
            "status": "PASS" if p.returncode == 0 else "FINDINGS",
            "returncode": p.returncode,
            "results": len(results),
        }

        for r in results:
            sev = str(r.get("issue_severity", "MEDIUM")).upper()
            if sev not in {"HIGH", "MEDIUM", "LOW"}:
                sev = "MEDIUM"
            self.add(
                severity=sev,
                category="CONFIGURATION",
                title=f"Bandit {r.get('test_id','finding')}",
                message=str(r.get("issue_text", "Bandit finding")),
                path=self.root / r.get("filename", ""),
                line=int(r.get("line_number", 0) or 0),
                evidence=str(r.get("code", "")),
                remediation="Review the Bandit finding; baseline only verified false positives.",
                scanner="bandit",
                confidence="HIGH",
                cwe=str((r.get("issue_cwe") or {}).get("id", "")),
            )

    def run_pip_audit(self) -> None:
        exe = shutil.which("pip-audit")
        if not exe:
            self.external["pip-audit"] = {"status": "NOT_INSTALLED"}
            return

        try:
            p = subprocess.run(
                [exe, "--format", "json"],
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.stats.external_scanner_errors += 1
            self.external["pip-audit"] = {"status": "TIMEOUT"}
            return
        except Exception as e:
            self.stats.external_scanner_errors += 1
            self.external["pip-audit"] = {"status": "ERROR", "error": str(e)}
            return

        try:
            data = json.loads(p.stdout) if p.stdout.strip() else []
        except json.JSONDecodeError:
            data = []

        deps = data if isinstance(data, list) else data.get("dependencies", []) if isinstance(data, dict) else []
        vuln_count = 0
        for dep in deps:
            for vuln in dep.get("vulns", []) or []:
                vuln_count += 1
                pkg = dep.get("name", "unknown")
                vid = vuln.get("id", "UNKNOWN")
                self.add(
                    severity="HIGH",
                    category="DEPENDENCIES",
                    title=f"Known vulnerable dependency: {pkg}",
                    message=f"Advisory {vid} reported by pip-audit.",
                    evidence=json.dumps(vuln)[:1000],
                    remediation="Upgrade to a fixed version or document a temporary exception with compensating controls.",
                    scanner="pip-audit",
                    confidence="CONFIRMED",
                    cwe="CWE-1104",
                    owasp="A06:2021",
                    metadata={"package": pkg, "advisory": vid},
                )

        self.external["pip-audit"] = {
            "status": "PASS" if p.returncode == 0 else "FINDINGS",
            "returncode": p.returncode,
            "vulnerabilities": vuln_count,
        }

    def build_report(self) -> ScanReport:
        c = Counter(f.severity for f in self.findings)
        for s in SEVERITIES:
            c.setdefault(s, 0)

        score = max(0.0, 100.0 - sum(SEV_PENALTY[f.severity] for f in self.findings))
        critical, high = c["CRITICAL"], c["HIGH"]

        if critical:
            verdict, code, reason = "FAIL", 1, f"{critical} CRITICAL finding(s)"
        elif high > self.max_high:
            verdict, code, reason = "FAIL", 1, f"{high} HIGH finding(s) > allowed {self.max_high}"
        elif self.stats.syntax_errors:
            verdict, code, reason = "FAIL", 1, f"{self.stats.syntax_errors} syntax error(s)"
        else:
            verdict, code, reason = "PASS", 0, "No blocking security findings"

        return ScanReport(
            VERSION,
            str(self.root),
            round(score, 1),
            verdict,
            code,
            {s: int(c[s]) for s in SEVERITIES},
            self.findings,
            self.stats,
            self.external,
            {
                "critical": critical,
                "high": high,
                "allowed_high": self.max_high,
                "syntax_errors": self.stats.syntax_errors,
                "passes": verdict == "PASS",
                "reason": reason,
                "score_is_advisory": True,
            },
        )


class ASTVisitor(ast.NodeVisitor):
    def __init__(self, scanner: HardenedSecurityScanner, path: Path, source: str):
        self.s = scanner
        self.path = path
        self.source = source if isinstance(source, str) else ""
        self.scope: list[str] = []
        self.functions: list[str] = []
        self.route = False
        self._node_text_cache: dict[int, str] = {}
        # Split the source into lines ONCE per file. ast.get_source_segment
        # re-scans the entire source from the start on every call, which is
        # fine for occasional use but catastrophically slow when called once
        # per AST node (thousands of times) on large real-world files.
        self._lines: list[str] = split_lines_no_ff(self.source) if self.source else []

    def _get_text(self, node: ast.AST) -> str:
        if not self.source:
            return ""
        key = id(node)
        if key not in self._node_text_cache:
            self._node_text_cache[key] = source_segment_from_lines(self._lines, node)
        return self._node_text_cache[key]

    def symbol(self) -> str:
        return "::".join([*self.scope, *self.functions])

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.visit_func(node)
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.visit_func(node)
        return None

    def visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.functions.append(node.name)
        found, methods = route_info(node)
        old = self.route
        self.route = found or old

        self.check_route(node, methods)
        self.check_input(node)
        self.check_auth(node)
        self.check_rate(node)
        self.check_upload(node)

        self.generic_visit(node)

        self.route = old
        self.functions.pop()

    def check_route(self, node: ast.FunctionDef | ast.AsyncFunctionDef, methods: list[str]) -> None:
        if not self.route:
            return
        if contains_sensitive_name(node.name) and not has_auth_decorator(node):
            self.s.add(
                severity="HIGH",
                category="AUTHORIZATION",
                title="Sensitive route has no visible auth/authz guard",
                message=f"Route '{node.name}' has no recognizable authorization decorator.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                remediation="Enforce explicit authentication and authorization/policy checks at the endpoint or trusted middleware boundary.",
                confidence="MEDIUM",
                cwe="CWE-862",
                owasp="A01:2021",
            )

    def check_input(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not self.route:
            return
        names = [a.arg for a in [*node.args.args, *node.args.kwonlyargs] if looks_like_input(a.arg)]
        if not names:
            return

        text = self._get_text(node).lower()
        ok = any(
            k in text
            for k in (
                "pydantic",
                "basemodel",
                "model_validate",
                "validator",
                "validate",
                "constr(",
                "min_length=",
                "max_length=",
                "pattern=",
            )
        )
        if not ok:
            self.s.add(
                severity="MEDIUM",
                category="INPUT_VALIDATION",
                title="Route input lacks visible validation",
                message=f"Input-like parameters {names} have no clear validation evidence.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                remediation="Use typed schemas and explicit allowlist validation for type, size, range and format.",
                confidence="MEDIUM",
                cwe="CWE-20",
                owasp="A03:2021",
            )

    def check_auth(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not contains_sensitive_name(node.name) or has_auth_decorator(node):
            return
        if node.name.startswith("_") and not self.route:
            return

        text = self._get_text(node).lower()
        if not any(
            k in text
            for k in (
                "permission",
                "authorize",
                "authorization",
                "role",
                "current_user",
                "principal",
                "security_context",
                "require_",
            )
        ):
            self.s.add(
                severity="MEDIUM",
                category="AUTHORIZATION",
                title="Sensitive operation lacks visible authorization evidence",
                message=f"Operation '{node.name}' has no recognizable permission/role check.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                remediation="Make the authorization policy boundary explicit and test allow/deny cases.",
                confidence="LOW",
                cwe="CWE-862",
                owasp="A01:2021",
            )

    def check_rate(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.name.lower() not in {"login", "authenticate", "token", "refresh_token", "password_reset"}:
            return
        text = self._get_text(node).lower()
        if not any(k in text for k in RATE_LIMIT_NAMES):
            self.s.add(
                severity="MEDIUM",
                category="RATE_LIMITING",
                title="Authentication-sensitive operation lacks visible rate limiting",
                message=f"Operation '{node.name}' has no recognizable throttle/rate-limit evidence.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                remediation="Apply server-side rate limiting/backoff and monitor repeated failures.",
                confidence="MEDIUM",
                cwe="CWE-307",
                owasp="A07:2021",
            )

    def check_upload(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        n = node.name.lower()
        if not any(k in n for k in ("upload", "attachment", "evidence", "document")):
            return

        text = self._get_text(node).lower()
        if not any(k in text for k in ("max_size", "content_length", "file_size", "size_limit")):
            self.s.add(
                severity="MEDIUM",
                category="FILE_UPLOAD",
                title="Upload path lacks visible size limit",
                message=f"Function '{node.name}' has no recognizable file-size restriction.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                remediation="Enforce a server-side maximum upload size.",
                confidence="LOW",
                cwe="CWE-400",
            )

        if not any(k in text for k in ("content_type", "mimetype", "allowed_extensions", "allowlist", "extension")):
            self.s.add(
                severity="MEDIUM",
                category="FILE_UPLOAD",
                title="Upload path lacks visible type allowlist",
                message=f"Function '{node.name}' has no recognizable type/extension allowlist.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                remediation="Allowlist file types and verify content; do not trust client filenames alone.",
                confidence="LOW",
                cwe="CWE-434",
            )

        if not any(k in text for k in ("secure_filename", "safe_join", "path.resolve", "resolve()", "basename")):
            self.s.add(
                severity="HIGH",
                category="FILE_UPLOAD",
                title="Upload path lacks visible safe-path handling",
                message=f"Function '{node.name}' has no recognizable traversal defense.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                remediation="Generate server-side filenames and canonicalize paths under a fixed storage root.",
                confidence="MEDIUM",
                cwe="CWE-22",
                owasp="A03:2021",
            )

    def visit_Call(self, node: ast.Call) -> Any:
        name = call_name(node)
        low = name.lower()
        base = low.split(".")[-1]
        text = self._get_text(node)

        # Dynamic code execution — only flag the actual Python builtins
        # eval()/exec() (bare name calls). Many libraries expose unrelated
        # methods with the same short name (e.g. Qt's QDialog.exec()/
        # QApplication.exec(), redis-py's client.eval() for the Redis EVAL
        # command) — those are not Python code execution and would
        # otherwise flood the report with false positives.
        if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
            self.s.add(
                severity="CRITICAL",
                category="INJECTION",
                title=f"Dynamic code execution: {base}",
                message="eval/exec can execute attacker-controlled Python code.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                evidence=text,
                remediation="Remove dynamic code execution; use explicit dispatch/allowlists.",
                confidence="HIGH",
                cwe="CWE-95",
                owasp="A03:2021",
            )

        # Command execution
        if base in {"system", "popen"} or low in {
            "subprocess.run",
            "subprocess.popen",
            "subprocess.check_output",
            "subprocess.check_call",
        }:
            shell_false = any(
                k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is False
                for k in node.keywords
            )
            sev = (
                "CRITICAL"
                if any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)
                else "HIGH"
            )
            if not shell_false and not self._all_literal_args(node):
                sev = "HIGH"
            self.s.add(
                severity=sev,
                category="INJECTION",
                title=f"Dangerous command execution: {name}",
                message="External process execution expands command-injection attack surface.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                evidence=text,
                remediation="Prefer argument arrays and shell=False; validate/allowlist command arguments.",
                confidence="HIGH",
                cwe="CWE-78",
                owasp="A03:2021",
            )

        # SQL injection via execute/executemany
        if base in {"execute", "executemany"} and node.args:
            q = self._get_text(node.args[0])
            if isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)) or SQL_FMT_RE.search(q or ""):
                self.s.add(
                    severity="CRITICAL",
                    category="INJECTION",
                    title="Potential dynamic SQL construction",
                    message="SQL-like text appears to use interpolation/concatenation before execute.",
                    path=self.path,
                    line=node.lineno,
                    symbol=self.symbol(),
                    evidence=q,
                    remediation="Use parameterized queries/bound parameters or safe ORM APIs.",
                    confidence="HIGH",
                    cwe="CWE-89",
                    owasp="A03:2021",
                )

        # Unsafe deserialization
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            mod, attr = node.func.value.id.lower(), node.func.attr.lower()
            if (mod, attr) in UNSAFE_DESERIALIZATION:
                sev = "CRITICAL" if mod in {"pickle", "dill", "marshal"} else "HIGH"
                self.s.add(
                    severity=sev,
                    category="UNSAFE_DESERIALIZATION",
                    title=f"Unsafe deserialization API: {mod}.{attr}",
                    message="Deserialization can instantiate or execute attacker-controlled content.",
                    path=self.path,
                    line=node.lineno,
                    symbol=self.symbol(),
                    evidence=text,
                    remediation="Use safe schema-validated formats/loaders.",
                    confidence="HIGH",
                    cwe="CWE-502",
                    owasp="A08:2021",
                )

            if mod == "hashlib" and attr in WEAK_HASHES:
                self.s.add(
                    severity="HIGH",
                    category="CRYPTOGRAPHY",
                    title=f"Weak cryptographic hash: {attr}",
                    message=f"{attr.upper()} is unsuitable for modern password/security primitives.",
                    path=self.path,
                    line=node.lineno,
                    symbol=self.symbol(),
                    evidence=text,
                    remediation="Use SHA-256/SHA-3 for integrity or Argon2id/bcrypt/scrypt for passwords as appropriate.",
                    confidence="HIGH",
                    cwe="CWE-328",
                    owasp="A02:2021",
                )

        # JWT signature verification disabled
        if low.endswith("jwt.decode"):
            for kw in node.keywords:
                if kw.arg == "options" and re.search(
                    r"verify[_-]?signature\s*[:=]\s*False",
                    self._get_text(kw.value) or "",
                    re.I,
                ):
                    self.s.add(
                        severity="CRITICAL",
                        category="AUTHENTICATION",
                        title="JWT signature verification disabled",
                        message="JWT decode options appear to disable signature verification.",
                        path=self.path,
                        line=node.lineno,
                        symbol=self.symbol(),
                        evidence=self._get_text(kw.value),
                        remediation="Require signature verification and an explicit approved algorithm/key policy.",
                        confidence="HIGH",
                        cwe="CWE-347",
                        owasp="A07:2021",
                    )

        # Logging of secrets
        if low.startswith(("logger.", "logging.")) and SECRET_WORD_RE.search(text or ""):
            self.s.add(
                severity="HIGH",
                category="SECRETS",
                title="Potential secret/token logging",
                message="Sensitive field names appear in a logging call.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                evidence=text,
                remediation="Redact passwords, tokens, authorization headers and secrets before logging.",
                confidence="MEDIUM",
                cwe="CWE-532",
                owasp="A09:2021",
            )

        # SSRF from dynamic URLs
        if low in {
            "requests.get",
            "requests.post",
            "requests.request",
            "httpx.get",
            "httpx.post",
            "httpx.request",
        } and node.args and not isinstance(node.args[0], ast.Constant):
            self.s.add(
                severity="HIGH",
                category="INJECTION",
                title="Potential SSRF from dynamic outbound URL",
                message="HTTP destination is derived from a dynamic expression.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                evidence=text,
                remediation="Allowlist outbound destinations and reject unapproved private/internal targets.",
                confidence="LOW",
                cwe="CWE-918",
                owasp="A10:2021",
            )

        # TLS verification disabled
        if low.endswith(("requests.get", "requests.post", "requests.request")) and any(
            k.arg == "verify" and isinstance(k.value, ast.Constant) and k.value.value is False
            for k in node.keywords
        ):
            self.s.add(
                severity="HIGH",
                category="CRYPTOGRAPHY",
                title="TLS certificate verification disabled",
                message="HTTP client disables certificate verification.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                evidence=text,
                remediation="Enable TLS verification and use a trusted CA chain.",
                confidence="HIGH",
                cwe="CWE-295",
                owasp="A02:2021",
            )

        self.generic_visit(node)

    def _all_literal_args(self, node: ast.Call) -> bool:
        return all(isinstance(a, ast.Constant) for a in node.args)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Any:
        for n in ast.walk(node):
            if isinstance(n, ast.Return):
                t = self._get_text(n)
                if re.search(r"\bstr\s*\(", t or ""):
                    self.s.add(
                        severity="MEDIUM",
                        category="ERROR_HANDLING",
                        title="Exception detail may be exposed",
                        message="Exception text appears to be returned to caller.",
                        path=self.path,
                        line=n.lineno,
                        symbol=self.symbol(),
                        evidence=t,
                        remediation="Log detailed diagnostics server-side and return generic external errors.",
                        confidence="HIGH",
                        cwe="CWE-209",
                        owasp="A05:2021",
                    )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if node.attr == "random" and isinstance(node.value, ast.Name) and node.value.id == "random" and self.functions:
            if any(x in self.functions[-1].lower() for x in ("token", "secret", "password", "key", "nonce", "otp")):
                self.s.add(
                    severity="HIGH",
                    category="CRYPTOGRAPHY",
                    title="Non-cryptographic random source in security-sensitive code",
                    message="random module is not intended for secrets/tokens/keys.",
                    path=self.path,
                    line=node.lineno,
                    symbol=self.symbol(),
                    evidence=self._get_text(node),
                    remediation="Use the secrets module or an approved CSPRNG primitive.",
                    confidence="HIGH",
                    cwe="CWE-338",
                    owasp="A02:2021",
                )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> Any:
        t = self._get_text(node)
        if not is_test_file(self.path) and SECRET_LITERAL_RE.search(t or ""):
            self.s.add(
                severity="HIGH",
                category="SECRETS",
                title="Credential-like literal comparison",
                message="Code compares credential-like data against an embedded literal.",
                path=self.path,
                line=node.lineno,
                symbol=self.symbol(),
                evidence=t,
                remediation="Use a password verifier or managed secret, not a hardcoded credential.",
                confidence="MEDIUM",
                cwe="CWE-798",
                owasp="A07:2021",
            )
        self.generic_visit(node)


# Worker function for multiprocessing (must be at module level)
def scan_py_files_worker(args: tuple[list[Path], Path, bool]) -> tuple[list[Finding], ScanStats]:
    """Worker function to scan a chunk of Python files."""
    files, root, include_tests = args
    scanner = HardenedSecurityScanner(root, include_tests=include_tests, run_external=False, progress=False, jobs=1)
    findings = []
    stats = ScanStats()
    for p in files:
        try:
            scanner.scan_file(p)
        except Exception:
            stats.syntax_errors += 1
    findings.extend(scanner.findings)
    stats.files_scanned = len(files)
    stats.python_files = len(files)
    stats.findings = len(findings)
    return findings, stats


def print_report(r: ScanReport, limit: int, min_severity: str | None = None, scanner_filter: str | None = None) -> None:
    print("=" * 86)
    print(f"  HARDENED SECURITY CHECKER v{r.version}")
    print("=" * 86)
    print(f"Project root : {r.project_root}")
    print(f"Files scanned: {r.stats.files_scanned}")
    print(f"Findings     : {r.stats.findings}")
    print(f"\nSECURITY SCORE : {r.score:.1f}/100 (ADVISORY)")
    print(f"SECURITY GATE  : {r.verdict}")
    print(f"  CRITICAL={r.counts['CRITICAL']} HIGH={r.counts['HIGH']} MEDIUM={r.counts['MEDIUM']} LOW={r.counts['LOW']} INFO={r.counts['INFO']}")
    print(f"  Gate reason: {r.gate['reason']}")

    # --- Where are the findings coming from? A spike from one scanner (e.g.
    # bandit suddenly finishing and reporting thousands of LOW findings) is
    # obvious at a glance here instead of having to scroll a huge list. ---
    scanner_counts = Counter(f.scanner for f in r.findings)
    if scanner_counts:
        print("\n─── BY SCANNER ───")
        for name, cnt in scanner_counts.most_common():
            print(f"  {name:<12} {cnt}")

    # --- Counts per severity+category, busiest first, so you know where to
    # start triaging without reading every single finding. ---
    cat_counts = Counter((f.severity, f.category) for f in r.findings)
    if cat_counts:
        print("\n─── BY SEVERITY / CATEGORY ───")
        for (sev, cat), cnt in sorted(cat_counts.items(), key=lambda kv: (SEVERITIES.index(kv[0][0]), -kv[1])):
            print(f"  {sev:<8} {cat:<22} {cnt}")

    # --- Files with the most findings — useful for spotting one hot-spot
    # file dominating the count, vs. genuinely widespread issues. ---
    file_counts = Counter(f.file for f in r.findings if f.file)
    if file_counts:
        print("\n─── TOP FILES BY FINDING COUNT ───")
        for fname, cnt in file_counts.most_common(15):
            print(f"  {cnt:>6}  {fname}")

    # Display-only filters: narrow the "TOP FINDINGS" listing below without
    # touching stored counts, the gate verdict, or the JSON export — those
    # always reflect the complete, unfiltered result.
    shown = r.findings
    if min_severity:
        floor = SEVERITIES.index(min_severity)
        shown = [f for f in shown if SEVERITIES.index(f.severity) <= floor]
    if scanner_filter:
        shown = [f for f in shown if f.scanner == scanner_filter]

    filter_note = ""
    if min_severity or scanner_filter:
        bits = []
        if min_severity:
            bits.append(f"severity<={min_severity}")
        if scanner_filter:
            bits.append(f"scanner={scanner_filter}")
        filter_note = f" (filtered: {', '.join(bits)}; {len(shown)}/{len(r.findings)} findings match)"

    print(f"\n─── TOP FINDINGS ───{filter_note}")
    for i, f in enumerate(shown[:limit], 1):
        loc = f"{f.file}:{f.line}" if f.file else "<project>"
        print(f"[{i:03}] {f.severity:<8} {f.category:<20} {loc}")
        print(f"      {f.title}")
        print(f"      {f.message}")
        if f.symbol:
            print(f"      Symbol: {f.symbol}")
        if f.evidence:
            print(f"      Evidence: {f.evidence[:300]}")
        if f.remediation:
            print(f"      Fix: {f.remediation}")
    if len(shown) > limit:
        print(f"\n... {len(shown)-limit} additional matching finding(s) not shown.")
    if r.external_scanners:
        print("\n─── EXTERNAL SCANNERS ───")
        for k, v in r.external_scanners.items():
            print(f"  {k}: {v.get('status', 'UNKNOWN')}")
    print("=" * 86)
    print(f"VERDICT: {r.verdict}")
    print("=" * 86)


def self_test() -> int:
    ok = bad = 0

    def check(name, cond):
        nonlocal ok, bad
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if cond:
            ok += 1
        else:
            bad += 1

    with tempfile.TemporaryDirectory(prefix="hsc_") as td:
        root = Path(td)
        (root / "app.py").write_text(
            '''\nimport hashlib, pickle, subprocess\nfrom fastapi import FastAPI\napp=FastAPI()\n@app.post("/login")\ndef login(request, password):\n    if password == "supersecret123": return {"ok": True}\n    return {"ok": False}\ndef bad(x): return eval(x)\ndef deser(x): return pickle.loads(x)\ndef shell(x): return subprocess.run(x, shell=True)\ndef weak(x): return hashlib.md5(x.encode()).hexdigest()\ndef leak():\n    try: raise ValueError("internal")\n    except Exception as exc: return str(exc)\n''',
            encoding="utf-8",
        )
        (root / "requirements.txt").write_text("fastapi>=1\nrequests==2.0\n", encoding="utf-8")
        (root / "Dockerfile").write_text("FROM python:3\nCMD [\"python\",\"app.py\"]\n", encoding="utf-8")

        r = HardenedSecurityScanner(root, run_external=False, jobs=1).scan()
        titles = {f.title.lower() for f in r.findings}

        check("eval detected", any("eval" in t for t in titles))
        check("pickle detected", any("deserialization" in t for t in titles))
        check("shell detected", any("command execution" in t for t in titles))
        check("weak hash detected", any("weak cryptographic" in t for t in titles))
        check("secret detected", any("hardcoded secret" in t or "credential-like literal" in t for t in titles))
        check("unpinned dependency detected", any("not exactly pinned" in t for t in titles))
        check("docker user finding", any("no user instruction" in t for t in titles))
        check("gate blocks critical", r.verdict == "FAIL")
        check("json serializable", isinstance(json.dumps(r.to_json()), str))

    print(f"\nSelf-test: {ok} passed, {bad} failed")
    return 0 if bad == 0 else 1


def build_parser():
    p = argparse.ArgumentParser(description="Hardened Security Checker for Python/ERP projects")
    p.add_argument("--root", default=".")
    p.add_argument("--version", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--exclude-tests", action="store_true")
    p.add_argument("--no-external", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--max-high", type=int, default=0)
    p.add_argument("--json", dest="json_path")
    p.add_argument("--findings", type=int, default=50)
    p.add_argument("--fail-on-medium", action="store_true")
    p.add_argument("--jobs", type=int, default=1, help="Number of parallel processes (default 1, recommended for Windows)")
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Directory name(s) to exclude from the scan, in addition to the built-in "
             "ignore list (.git, .venv, node_modules, etc). Comma-separated and/or "
             "repeatable, e.g. --exclude checker or --exclude checker,scripts. "
             "Matches by directory name at any depth, and is also passed to bandit.",
    )
    p.add_argument(
        "--min-severity",
        choices=SEVERITIES,
        default=None,
        help="Only list findings at or above this severity in the TOP FINDINGS "
             "section (e.g. --min-severity HIGH shows CRITICAL+HIGH only). Does "
             "NOT affect the score, gate verdict, or the JSON export — those "
             "always reflect every finding. Use this to cut through noise (e.g. "
             "a large volume of LOW findings from bandit) when triaging in the "
             "terminal.",
    )
    p.add_argument(
        "--scanner",
        choices=("custom-ast", "regex", "bandit", "pip-audit"),
        default=None,
        help="Only list findings from this scanner in the TOP FINDINGS section "
             "(same display-only scope as --min-severity). Useful to isolate, "
             "for example, only bandit's findings or only this tool's own "
             "AST-based findings.",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8()
    args = build_parser().parse_args(argv)

    if args.version:
        print(f"hardened_security_checker v{VERSION}")
        return 0

    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"ERROR: root does not exist: {root}", file=sys.stderr)
        return 2

    jobs = max(1, args.jobs)
    exclude_dirs: set[str] = set()
    for item in args.exclude:
        for part in item.split(","):
            part = part.strip().strip("/\\")
            if part:
                exclude_dirs.add(part)

    r = HardenedSecurityScanner(
        root,
        include_tests=not args.exclude_tests,
        max_high=args.max_high,
        run_external=not args.no_external,
        progress=not args.quiet,
        jobs=jobs,
        exclude_dirs=exclude_dirs,
    ).scan()

    if args.fail_on_medium and r.counts["MEDIUM"]:
        r.verdict = "FAIL"
        r.exit_code = 1
        r.gate["passes"] = False
        r.gate["reason"] = f"{r.counts['MEDIUM']} MEDIUM finding(s) with --fail-on-medium"

    print_report(r, max(0, args.findings), min_severity=args.min_severity, scanner_filter=args.scanner)

    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON report: {out}")

    return r.exit_code


if __name__ == "__main__":
    raise SystemExit(main())