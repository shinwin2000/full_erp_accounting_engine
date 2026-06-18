#!/usr/bin/env python3
# =============================================================================
#  SOVEREIGN ERP ACCOUNTING ENGINE — STRUCTURAL INTEGRITY AUDITOR v11.5
#  =============================================================================
#  FIXES (v11.5):
#    1. P09: pencarian adapter diperluas ke seluruh adapters/ dan pencocokan
#       menggunakan substring (case-insensitive) agar sesuai dengan struktur
#       folder proyek (sqlalchemy_*_impl, coretax_*, bank_*_adapter, dsb).
#    2. P09: tidak lagi hanya terbatas pada adapters/secondary_impl.
#    3. Semua WARNING/CRITICAL selalu menampilkan file:line.
#    4. Tidak ada false positive dari checker sendiri.
# =============================================================================

from __future__ import annotations

import argparse
import ast
import collections
import importlib
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

# ─── Colour ──────────────────────────────────────────────────────────────────
RED = GREEN = YELLOW = CYAN = MAGENTA = WHITE = BOLD = RESET = ""


def _setup_colour(enable: bool) -> None:
    global RED, GREEN, YELLOW, CYAN, MAGENTA, WHITE, BOLD, RESET
    if enable:
        try:
            import colorama

            colorama.init(autoreset=True)
            RED = colorama.Fore.RED
            GREEN = colorama.Fore.GREEN
            YELLOW = colorama.Fore.YELLOW
            CYAN = colorama.Fore.CYAN
            MAGENTA = colorama.Fore.MAGENTA
            WHITE = colorama.Fore.WHITE
            BOLD = colorama.Style.BRIGHT
            RESET = colorama.Style.RESET_ALL
            return
        except ImportError:
            pass
    RED = GREEN = YELLOW = CYAN = MAGENTA = WHITE = BOLD = RESET = ""


_setup_colour(True)


# ─── Data structures ─────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str
    phase: str
    file: str
    line: int
    message: str
    detail: str = ""


@dataclass
class PhaseResult:
    name: str
    weight: int
    score: int = 100
    passed: bool = True
    findings: list[Finding] = field(default_factory=list)
    duration: float = 0.0
    disclaimer: str = ""

    def add(self, sev: str, file: str, line: int, msg: str, detail: str = "") -> None:
        self.findings.append(Finding(sev, self.name, file, line, msg, detail))
        if sev == "CRITICAL":
            self.passed = False

    def count(self, sev: str) -> int:
        return sum(1 for f in self.findings if f.severity == sev)

    def degrade(self, per_crit: int = 10, per_warn: int = 3, floor: int = 0) -> None:
        self.score = max(
            floor, 100 - self.count("CRITICAL") * per_crit - self.count("WARNING") * per_warn
        )

    def finalize_status(self) -> None:
        if self.count("CRITICAL") > 0 or self.score == 0:
            self.passed = False


# ─── Print helpers ──────────────────────────────────────────────────────────
_ICON = {"CRITICAL": "✖", "WARNING": "⚠", "INFO": "ℹ", "PASS": "✔"}
_SCOL = {
    "CRITICAL": lambda: RED,
    "WARNING": lambda: YELLOW,
    "INFO": lambda: CYAN,
    "PASS": lambda: GREEN,
}


def _c(s: str) -> str:
    return _SCOL.get(s, lambda: WHITE)()


def banner(txt: str, w: int = 78) -> str:
    ln = "─" * w
    return f"\n{BOLD}{CYAN}{ln}\n  {txt}\n{ln}{RESET}"


def pf(f: Finding, verbose: bool = False) -> None:
    col = _c(f.severity)
    icon = _ICON.get(f.severity, "?")
    print(f"  {col}{BOLD}{icon} [{f.severity}]{RESET} {f.message}")
    if f.detail and (verbose or f.severity == "CRITICAL"):
        for ln in f.detail.splitlines()[:6]:
            print(f"      {YELLOW}{ln}{RESET}")
    # Always show file:line for WARNING and CRITICAL (even if not verbose)
    if f.file and (verbose or f.severity in ("WARNING", "CRITICAL")):
        loc = f"{f.file}:{f.line}" if f.line else f.file
        print(f"      {WHITE}@ {loc}{RESET}")


# ─── Project root & file helpers ─────────────────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parent

_PROJECT_TOPS = {
    "app",
    "adapters",
    "application",
    "domain",
    "infrastructure",
    "kernel",
    "ports",
    "config",
    "migrations",
    "tests",
    "compliance",
    "audit",
    "constitution",
    "axioms",
    "bootstrap",
    "policy_engine",
    "projections",
    "reports",
    "transformers",
    "event_gateway",
    "security_hardening",
    "disaster_recovery",
    "monitoring",
    "architecture",
}
_SKIP_ALWAYS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".cache",
    "site-packages",
    "dist-packages",
    "dist",
    "build",
    "uv",
}
_CHECKER_FILES = {
    "main_checker.py",
    "main_checker_2.py",
    "main_checker_3.py",
    "main_checker_v5.py",
    "main_checker_old.py",
    "main_app_checker.py",
}


def is_test_file(path: pathlib.Path) -> bool:
    path_str = str(path)
    return (
        "/tests/" in path_str
        or "\\tests\\" in path_str
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
        or "/test_" in path_str
        or "\\test_" in path_str
    )


def is_checker_file(path: pathlib.Path) -> bool:
    return path.name in _CHECKER_FILES


def all_py(
    root: pathlib.Path = ROOT,
    skip_tops: set[str] | None = None,
    project_only: bool = True,
    include_checker: bool = False,
) -> list[pathlib.Path]:
    extra = skip_tops or set()
    result: list[pathlib.Path] = []
    for p in root.glob("*.py"):
        if include_checker or p.name not in _CHECKER_FILES:
            result.append(p)
    scan_roots = (
        [root / d for d in _PROJECT_TOPS if (root / d).is_dir()] if project_only else [root]
    )
    for sr in scan_roots:
        for p in sr.rglob("*.py"):
            if any(part in _SKIP_ALWAYS for part in p.parts):
                continue
            if any(part in extra for part in p.parts):
                continue
            if not include_checker and p.name in _CHECKER_FILES:
                continue
            try:
                p.relative_to(ROOT)
            except ValueError:
                continue
            result.append(p)
    return sorted(set(result))


def rel(p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def mod_name(path: pathlib.Path) -> str | None:
    try:
        rp = path.relative_to(ROOT)
    except ValueError:
        return None
    parts = list(rp.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def top_layer(module: str) -> str:
    return module.split(".")[0]


def get_ast_tree(path: pathlib.Path) -> ast.AST | None:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        return ast.parse(src, filename=str(path))
    except SyntaxError:
        return None
    except Exception:
        return None


def get_ast_tree_with_source(path: pathlib.Path) -> tuple[ast.AST | None, list[str] | None]:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        return ast.parse(src, filename=str(path)), lines
    except SyntaxError:
        return None, None
    except Exception:
        return None, None


def _static_imports_ast(tree: ast.AST) -> list[tuple[str, int]]:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.append((a.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.append((node.module, node.lineno))
    return imports


# =============================================================================
# P00 — Environment & Python
# =============================================================================
REQUIRED_PYTHON = (3, 10)


def p00_environment() -> PhaseResult:
    pr = PhaseResult("P00 Environment & Python", weight=2)
    pr.disclaimer = "Verifies Python version and critical package presence only."
    t0 = time.monotonic()
    ver = sys.version_info[:2]
    if ver < REQUIRED_PYTHON:
        pr.add(
            "CRITICAL",
            "python",
            0,
            f"Python {ver[0]}.{ver[1]} — need ≥ {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}",
        )
    else:
        pr.add("PASS", "python", 0, f"Python {ver[0]}.{ver[1]}.{sys.version_info[2]}")
    critical_pkgs = ["fastapi", "sqlalchemy", "alembic", "pydantic"]
    missing = []
    for pkg in critical_pkgs:
        nm = pkg.replace("-", "_")
        if importlib.util.find_spec(nm) is None and importlib.util.find_spec(pkg) is None:
            missing.append(pkg)
    if missing:
        for pkg in missing:
            pr.add("CRITICAL", "requirements.txt", 0, f"Missing critical package: {pkg}")
    else:
        pr.add("PASS", "requirements.txt", 0, "Critical packages present")
    pr.degrade(per_crit=15, per_warn=5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P01 — Folder Structure
# =============================================================================
REQUIRED_DIRS = [
    "app",
    "adapters",
    "application",
    "domain",
    "infrastructure",
    "kernel",
    "ports",
    "config",
    "migrations",
    "tests",
    "compliance",
    "audit",
    "constitution",
    "axioms",
    "bootstrap",
    "policy_engine",
]


def p01_structure() -> PhaseResult:
    pr = PhaseResult("P01 Folder Structure", weight=1)
    pr.disclaimer = "Verifies directory existence only."
    t0 = time.monotonic()
    miss_d = [d for d in REQUIRED_DIRS if not (ROOT / d).is_dir()]
    for d in miss_d:
        pr.add("CRITICAL", d, 0, f"Required directory missing: {d}/")
    if not miss_d:
        pr.add("PASS", ".", 0, f"All {len(REQUIRED_DIRS)} directories present")
    else:
        pr.add("INFO", ".", 0, f"Missing {len(miss_d)} directories")
    pr.degrade(per_crit=20, per_warn=5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P02 — Syntax Validation
# =============================================================================
def p02_syntax() -> PhaseResult:
    pr = PhaseResult("P02 Syntax Validation", weight=2)
    pr.disclaimer = "Verifies files can be parsed by AST. Does NOT verify semantic correctness."
    t0 = time.monotonic()
    files = all_py(include_checker=True)
    errors = 0
    for path in files:
        try:
            raw = path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            ast.parse(raw, filename=str(path))
        except SyntaxError as e:
            errors += 1
            pr.add("CRITICAL", rel(path), e.lineno or 0, f"SyntaxError: {e.msg}")
        except Exception as e:
            errors += 1
            pr.add("CRITICAL", rel(path), 0, f"ParseError: {type(e).__name__}: {str(e)[:80]}")
    if not errors:
        pr.add("PASS", ".", 0, f"All {len(files)} files parse cleanly")
    pr.score = max(0, 100 - errors * 5)
    if errors:
        pr.passed = False
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P03 — Self-Audit
# =============================================================================
def p03_self_audit() -> PhaseResult:
    pr = PhaseResult("P03 Self-Audit", weight=3)
    pr.disclaimer = "Verifies checker has no syntax errors and phase registry is consistent."
    t0 = time.monotonic()
    checker_path = ROOT / "main_checker_2.py"
    if not checker_path.exists():
        pr.add("CRITICAL", "main_checker_2.py", 0, "Checker file not found")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tree, lines = get_ast_tree_with_source(checker_path)
    if tree is None:
        pr.add("CRITICAL", "main_checker_2.py", 0, "Checker has syntax errors")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    # Check for hardcoded secrets in checker (excluding test patterns)
    secret_patterns = [
        (
            r'(?i)password\s*=\s*["\'](?!bcrypt|argon|sha|example|changeme)[A-Za-z0-9@#$!%^&*]{8,}["\']',
            "CRITICAL",
        ),
        (r'(?i)secret.*?=\s*["\'][A-Za-z0-9@#$!%^&*_\-]{16,}["\']', "CRITICAL"),
    ]
    if lines:
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for pattern, sev in secret_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    pr.add(
                        sev,
                        "main_checker_2.py",
                        lineno,
                        "Hardcoded secret in checker",
                        detail=line[:100],
                    )
    phase_functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("p") and len(node.name) >= 3:
            phase_functions.append(node.name)
    if pr.count("CRITICAL") == 0:
        pr.add(
            "PASS",
            "main_checker_2.py",
            0,
            f"Checker self-audit passed: {len(phase_functions)} phases found",
        )
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P04 — Circular Imports (Static only)
# =============================================================================
def p04_circular() -> PhaseResult:
    pr = PhaseResult("P04 Circular Imports", weight=2)
    pr.disclaimer = "Analyzes static import graph only. Dynamic imports not analyzed."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    m2f: dict[str, pathlib.Path] = {mod_name(f): f for f in files if mod_name(f)}
    graph: dict[str, set[str]] = collections.defaultdict(set)
    for mod, path in m2f.items():
        tree = get_ast_tree(path)
        if tree:
            for imp, _ in _static_imports_ast(tree):
                if imp in m2f:
                    graph[mod].add(imp)
                else:
                    for local in m2f:
                        if local.startswith(imp + ".") or local == imp:
                            graph[mod].add(local)
    # Tarjan's algorithm
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[set[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack[node] = True
        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif on_stack.get(neighbor, False):
                lowlink[node] = min(lowlink[node], indices[neighbor])
        if lowlink[node] == indices[node]:
            scc: set[str] = set()
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.add(w)
                if w == node:
                    break
            if len(scc) > 1:
                sccs.append(scc)

    for node in graph:
        if node not in indices:
            strongconnect(node)
    cycles_found = 0
    for scc in sccs:
        if len(scc) >= 2:
            cycles_found += 1
            if cycles_found <= 20:
                cycle_list = list(scc)
                pr.add(
                    "WARNING",
                    rel(m2f.get(cycle_list[0], pathlib.Path("?"))),
                    0,
                    f"Static circular import cycle: {' → '.join(cycle_list[:5])}",
                )
    if cycles_found == 0:
        pr.add("PASS", ".", 0, f"No static circular imports among {len(m2f)} modules")
    else:
        pr.add("INFO", ".", 0, f"Found {cycles_found} static cycle(s)")
    pr.degrade(per_crit=10, per_warn=2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P05 — Static Import Scan
# =============================================================================
def p05_static_imports() -> PhaseResult:
    pr = PhaseResult("P05 Static Import Scan", weight=2)
    pr.disclaimer = "Counts static imports only. Does NOT verify runtime import correctness."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    total_imports = 0
    for path in files:
        tree = get_ast_tree(path)
        if tree:
            imports = _static_imports_ast(tree)
            total_imports += len(imports)
    pr.add("PASS", ".", 0, f"Found {total_imports} static imports across {len(files)} files")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P06 — Dynamic Import Audit
# =============================================================================
_PROTECTED_LAYERS = {"domain", "kernel", "axioms", "constitution", "ports"}


def _find_dynamic_imports_ast(tree: ast.AST) -> list[tuple[int, str, str]]:
    res = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
            ):
                if node.args:
                    expr = ast.unparse(node.args[0])
                    res.append((node.lineno, "importlib.import_module", expr))
            elif isinstance(node.func, ast.Name) and node.func.id == "__import__":
                if node.args:
                    expr = ast.unparse(node.args[0])
                    res.append((node.lineno, "__import__", expr))
    return res


def p06_dynamic_imports() -> PhaseResult:
    pr = PhaseResult("P06 Dynamic Import Audit", weight=2)
    pr.disclaimer = (
        "Flags dynamic import patterns. Plugin architectures may legitimately use dynamic imports."
    )
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    dangerous_count = 0
    for path in files:
        tree = get_ast_tree(path)
        if tree is None:
            continue
        hits = _find_dynamic_imports_ast(tree)
        if not hits:
            continue
        rp = rel(path)
        mod = mod_name(path)
        layer = top_layer(mod) if mod else "unknown"
        if layer in _PROTECTED_LAYERS:
            for lineno, call, expr in hits[:3]:
                dangerous_count += 1
                pr.add(
                    "WARNING",
                    rp,
                    lineno,
                    f"Dynamic import in protected layer '{layer}': {call}({expr})",
                )
    if dangerous_count == 0:
        pr.add("PASS", ".", 0, "No dynamic imports in protected layers")
    pr.degrade(per_crit=10, per_warn=2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P07 — Broken Import Scan
# =============================================================================
def _resolve_import_target(imp: str, root: pathlib.Path) -> list[pathlib.Path]:
    candidates = []
    direct = root / imp.replace(".", "/")
    candidates.append(direct.with_suffix(".py"))
    candidates.append(direct / "__init__.py")
    parts = imp.split(".")
    for i in range(len(parts)):
        pkg_path = root / "/".join(parts[: i + 1])
        candidates.append(pkg_path / "__init__.py")
    return [c for c in candidates if c.exists()]


def p07_broken_imports() -> PhaseResult:
    pr = PhaseResult("P07 Broken Import Scan", weight=3)
    pr.disclaimer = (
        "Verifies imported modules exist as files. Does NOT verify runtime importability."
    )
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    local_mods: set[str] = {mod_name(f) for f in files if mod_name(f)}
    local_tops: set[str] = {m.split(".")[0] for m in local_mods}
    broken_imports = []
    for path in files:
        tree = get_ast_tree(path)
        if tree is None:
            continue
        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in local_tops and alias.name not in local_mods:
                        if not _resolve_import_target(alias.name, ROOT):
                            broken_imports.append((rp, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top = node.module.split(".")[0]
                if top in local_tops and node.module not in local_mods:
                    if not _resolve_import_target(node.module, ROOT):
                        broken_imports.append((rp, node.lineno, node.module))
    for rp, lineno, imp in broken_imports[:25]:
        pr.add("WARNING", rp, lineno, f"Broken local import reference: {imp}")
    if not broken_imports:
        pr.add("PASS", ".", 0, "No broken local import references found")
    else:
        pr.add("INFO", ".", 0, f"Found {len(broken_imports)} broken import reference(s)")
    pr.score = max(0, 100 - len(broken_imports) * 3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P08 — Architecture Layers (WARNING for violations)
# =============================================================================
_LAYER_RULES: dict[str, set[str]] = {
    "domain": {"domain"},
    "axioms": {"axioms", "constitution"},
    "constitution": {"constitution", "domain", "axioms"},
    "kernel": {"kernel", "domain", "axioms", "constitution", "ports", "config"},
    "ports": {"ports", "domain"},
    "application": {"application", "domain", "kernel", "ports", "axioms", "constitution"},
    "adapters": {"adapters", "application", "domain", "kernel", "ports", "infrastructure"},
    "infrastructure": {"infrastructure", "domain", "ports", "kernel", "config"},
    "bootstrap": set(),
    "config": {"config", "bootstrap"},
    "app": set(),
}
_LAYER_EXCEPTIONS: set[tuple[str, str]] = {("domain", "kernel")}


def p08_architecture() -> PhaseResult:
    pr = PhaseResult("P08 Architecture Layers", weight=3)
    pr.disclaimer = "Heuristic check based on layer naming. May have false positives."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    violations = []
    exempt_layers = {"bootstrap", "app", "deployment", "scripts"}
    for path in files:
        mod = mod_name(path)
        if not mod:
            continue
        tree = get_ast_tree(path)
        if tree is None:
            continue
        layer = top_layer(mod)
        if layer in exempt_layers:
            continue
        allowed = _LAYER_RULES.get(layer)
        if allowed is None:
            continue
        for imp, lineno in _static_imports_ast(tree):
            imp_layer = top_layer(imp)
            if imp_layer and imp_layer in _LAYER_RULES and imp_layer not in allowed:
                if (layer, imp_layer) not in _LAYER_EXCEPTIONS:
                    violations.append((rel(path), lineno, layer, imp_layer, imp))
    for file, lineno, layer, imp_layer, imp in violations[:30]:
        pr.add(
            "WARNING",
            file,
            lineno,
            f"Potential layer violation: {layer} → {imp_layer} imports '{imp}'",
        )
    if len(violations) <= 10:
        pr.add("PASS", ".", 0, f"Layer violations within tolerance: {len(violations)}")
    else:
        pr.add(
            "WARNING",
            ".",
            0,
            f"Found {len(violations)} potential layer violations (first 30 shown)",
        )
    pr.score = max(0, 100 - min(len(violations), 30) * 2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P09 — Port-Adapter Pairing (diperbaiki untuk struktur folder)
# =============================================================================
def p09_port_adapter() -> PhaseResult:
    pr = PhaseResult("P09 Port-Adapter Pairing", weight=2)
    pr.disclaimer = "Verifies naming convention only. Does NOT verify runtime binding."
    t0 = time.monotonic()

    ports_dir = ROOT / "ports" / "primary"
    adapters_root = ROOT / "adapters"

    if not ports_dir.exists() or not adapters_root.exists():
        pr.add("INFO", ".", 0, "ports/primary or adapters/ not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Kumpulkan semua file Python di bawah adapters/ (rekursif), kecuali __init__.py
    adapter_files = set()
    for py_file in adapters_root.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        if "__pycache__" in py_file.parts:
            continue
        adapter_files.add(py_file.stem)

    port_files = {f.stem for f in ports_dir.glob("*.py") if f.stem != "__init__"}

    paired = 0
    unpaired_ports = []

    for port in sorted(port_files):
        # Ambil nama dasar port dengan menghilangkan akhiran umum
        base = port
        for suffix in ["_repository_port", "_port", "_repository"]:
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break

        # Cari adapter yang mengandung base (case-insensitive)
        found = False
        for astem in adapter_files:
            if base.lower() in astem.lower():
                found = True
                break

        if found:
            paired += 1
        else:
            unpaired_ports.append(port)

    # Laporkan port yang tidak memiliki adapter (WARNING)
    for port in unpaired_ports[:10]:
        pr.add("WARNING", f"ports/primary/{port}.py", 0, f"No adapter found for port: {port}")

    total = len(port_files)
    cov = int(paired / total * 100) if total else 0
    if cov >= 80:
        pr.add("PASS", ".", 0, f"Port-adapter naming coverage: {paired}/{total} = {cov}%")
    else:
        pr.add("WARNING", ".", 0, f"Port-adapter coverage low: {paired}/{total} = {cov}%")

    pr.score = cov
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P10 — API Route Completeness
# =============================================================================
DOMAIN_ROUTERS = [
    "fastapi_coa_router",
    "fastapi_journal_router",
    "fastapi_ledger_router",
    "fastapi_ap_router",
    "fastapi_ar_router",
    "fastapi_bank_cash_router",
    "fastapi_inventory_router",
    "fastapi_fixed_asset_router",
    "fastapi_tax_coretax_router",
    "fastapi_iam_router",
]


def p10_routes() -> PhaseResult:
    pr = PhaseResult("P10 API Route Completeness", weight=1)
    pr.disclaimer = "Verifies router files exist. Does NOT verify route implementation."
    t0 = time.monotonic()
    v1 = ROOT / "adapters" / "primary_api" / "v1"
    if not v1.exists():
        pr.add("WARNING", "adapters/primary_api/v1", 0, "v1 router directory not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    present = {f.stem for f in v1.glob("*.py") if f.stem != "__init__"}
    missing = [r for r in DOMAIN_ROUTERS if r not in present]
    for r in missing:
        pr.add("INFO", "adapters/primary_api/v1", 0, f"Missing router file: {r}.py")
    if len(missing) <= 2:
        pr.add("PASS", "adapters/primary_api/v1", 0, f"Router files: {len(present)} present")
    else:
        pr.add("WARNING", "adapters/primary_api/v1", 0, f"Missing {len(missing)} router files")
    pr.score = max(0, 100 - len(missing) * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P11 — YAML Validation
# =============================================================================
def p11_yaml() -> PhaseResult:
    pr = PhaseResult("P11 YAML Validation", weight=1)
    pr.disclaimer = "Verifies YAML syntax only. Does NOT verify semantic correctness."
    t0 = time.monotonic()
    try:
        import yaml as _yaml
    except ImportError:
        pr.add("INFO", ".", 0, "PyYAML not installed — skipping YAML validation")
        pr.score = 70
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    yfiles = []
    for d in ["config_files", "monitoring", "deployment"]:
        dp = ROOT / d
        if dp.exists():
            yfiles.extend(dp.rglob("*.yaml"))
            yfiles.extend(dp.rglob("*.yml"))
    yfiles.extend(ROOT.glob("*.yaml"))
    yfiles.extend(ROOT.glob("*.yml"))
    errors = 0
    checked = 0
    for yf in sorted(set(yfiles)):
        try:
            with open(yf, encoding="utf-8") as fh:
                list(_yaml.safe_load_all(fh))
            checked += 1
        except _yaml.YAMLError as e:
            errors += 1
            pr.add("WARNING", rel(yf), 0, f"YAML syntax error: {str(e)[:80]}")
    if errors == 0:
        pr.add("PASS", ".", 0, f"All {checked} YAML files have valid syntax")
    pr.score = max(0, 100 - errors * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P12 — ASGI Load
# =============================================================================
def p12_asgi() -> PhaseResult:
    pr = PhaseResult("P12 ASGI Load", weight=1)
    pr.disclaimer = "Verifies ASGI app pattern exists. Does NOT verify runtime correctness."
    t0 = time.monotonic()
    main_py = ROOT / "app" / "main.py"
    if not main_py.exists():
        pr.add("WARNING", "app/main.py", 0, "app/main.py not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tree = get_ast_tree(main_py)
    has_app = False
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ("app", "application"):
                        has_app = True
            elif isinstance(node, ast.FunctionDef) and node.name in ("get_app", "create_app"):
                has_app = True
    if has_app:
        pr.add("PASS", "app/main.py", 0, "ASGI app pattern found")
    else:
        pr.add("INFO", "app/main.py", 0, "ASGI app pattern not clearly found")
    pr.score = 100 if has_app else 70
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P13 — Migration Chain
# =============================================================================
def p13_migrations() -> PhaseResult:
    pr = PhaseResult("P13 Migration Chain", weight=2)
    pr.disclaimer = (
        "Verifies revision graph consistency. Multiple heads or orphans block alembic upgrade."
    )
    t0 = time.monotonic()
    vdir = ROOT / "migrations" / "versions"
    if not vdir.exists():
        pr.add("INFO", "migrations/versions", 0, "versions directory not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    mfiles = [f for f in sorted(vdir.glob("*.py")) if f.name != "__init__.py"]
    revs: dict[str, str] = {}  # revision -> down_revision
    file_by_rev: dict[str, pathlib.Path] = {}
    for mf in mfiles:
        src = mf.read_text(encoding="utf-8", errors="replace")
        rm = re.search(r'^revision\s*=\s*["\'](\w+)["\']', src, re.M)
        if not rm:
            rm = re.search(r'^revision\s*:\s*[^=]+\s*=\s*["\'](\w+)["\']', src, re.M)
        dm = re.search(r'^down_revision\s*=\s*["\']?(\w+|None)["\']?', src, re.M)
        if not dm:
            dm = re.search(r'^down_revision\s*:\s*[^=]+\s*=\s*["\']?(\w+|None)["\']?', src, re.M)
        if rm:
            rev = rm.group(1)
            down = dm.group(1) if dm and dm.group(1) != "None" else ""
            revs[rev] = down
            file_by_rev[rev] = mf
    all_rev = set(revs)
    all_down = {v for v in revs.values() if v}
    orphans = all_down - all_rev
    heads = all_rev - all_down

    for o in orphans:
        for rev, down in revs.items():
            if down == o:
                pr.add(
                    "CRITICAL",
                    rel(file_by_rev.get(rev, vdir / "unknown")),
                    0,
                    f"Orphan down_revision '{o}' — file {rev} refers to missing revision",
                )
                break
    if len(heads) > 1:
        pr.add(
            "CRITICAL",
            "migrations/versions",
            0,
            f"Multiple heads ({len(heads)}) — run: alembic merge heads",
        )
        for h in heads:
            pr.add("INFO", rel(file_by_rev.get(h, vdir / "unknown")), 0, f"Head revision: {h}")

    if not orphans and len(heads) <= 1:
        pr.add("PASS", "migrations/versions", 0, f"Revision chain intact: {len(mfiles)} migrations")
    else:
        pr.add(
            "INFO",
            "migrations/versions",
            0,
            f"Status: {len(mfiles)} files, {len(heads)} heads, {len(orphans)} orphans",
        )
    pr.score = max(0, 100 - len(orphans) * 20 - max(0, len(heads) - 1) * 25)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P14 — Code Quality (ubah INFO menjadi WARNING)
# =============================================================================
def p14_quality() -> PhaseResult:
    pr = PhaseResult("P14 Code Quality", weight=1)
    pr.disclaimer = (
        "Detects common anti-patterns. Does NOT measure maintainability comprehensively."
    )
    t0 = time.monotonic()
    files = all_py(include_checker=True, skip_tops={"tests", "migrations"})
    issues = []

    # Regex untuk marker yang ingin dicari
    marker_pattern = re.compile(r"\b(TODO|FIXME|HACK)\b", re.IGNORECASE)

    for path in files:
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue

        rp = rel(path)

        # 1. Analisis AST (Bare except & Wildcard import)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append((rp, node.lineno, "Bare except clause"))
            elif isinstance(node, ast.ImportFrom):
                if node.names and any(n.name == "*" for n in node.names):
                    issues.append((rp, node.lineno, "Wildcard import"))

        # 2. Analisis Baris Kode (TODO/FIXME/HACK)
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()

            # Abaikan jika baris kosong atau komentar
            if not stripped or stripped.startswith("#"):
                # PENGECUALIAN: Abaikan jika baris ini mengandung marker penanda checker
                # Agar main_checker tidak mendeteksi dirinya sendiri
                if "NOCheck" in line or "meta-check-ignore" in line:
                    continue
                continue

            # Jika baris kode (bukan komentar) mengandung marker, catat sebagai issue
            if marker_pattern.search(line):
                issues.append((rp, lineno, "TODO/FIXME/HACK marker"))

    # Menampilkan hingga 30 issue pertama
    for rp, lineno, msg in issues[:30]:
        pr.add("WARNING", rp, lineno, msg)

    # Kalkulasi hasil
    if len(issues) <= 20:
        pr.add("PASS", ".", 0, f"Code quality issues: {len(issues)}")
    else:
        pr.add("WARNING", ".", 0, f"Found {len(issues)} code quality issues")

    pr.score = max(0, 100 - len(issues))
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P15 — Security Scan (skip checker files)
# =============================================================================
_SEC_PATTERNS = [
    (r"pickle\.loads?\s*\(", "WARNING", "pickle.load() — unsafe deserialization"),
    (r"yaml\.load\s*\([^)]*\)", "WARNING", "yaml.load() — use safe_load()"),
    (r"\bverify\s*=\s*False\b", "WARNING", "SSL verify=False"),
    (r"os\.system\s*\(", "WARNING", "os.system() — use subprocess"),
    (r"DEBUG\s*=\s*True\b", "INFO", "DEBUG=True — ensure not in production"),
]


def p15_security() -> PhaseResult:
    pr = PhaseResult("P15 Security Scan", weight=4)
    pr.disclaimer = "Pattern-based detection. May have false positives and false negatives."
    t0 = time.monotonic()
    files = all_py(include_checker=True, skip_tops={"tests", "docs"})
    for path in files:
        # Skip checker files to avoid false positives from the checker's own test patterns
        if is_checker_file(path):
            continue
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue
        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                    pr.add("CRITICAL", rp, node.lineno, f"{node.func.id}() — code execution")
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for pattern, sev, msg in _SEC_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    pr.add(sev, rp, lineno, msg, detail=line[:100])
                    break
    if pr.count("CRITICAL") == 0:
        pr.add("PASS", ".", 0, "No critical security patterns found")
    pr.degrade(per_crit=15, per_warn=2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P16 — Dependency Audit
# =============================================================================
def p16_dependency_audit() -> PhaseResult:
    pr = PhaseResult("P16 Dependency Audit", weight=2)
    pr.disclaimer = "Checks version constraints against known vulnerable ranges."
    t0 = time.monotonic()
    req_file = ROOT / "requirements.txt"
    if not req_file.exists():
        pr.add("INFO", "requirements.txt", 0, "requirements.txt not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    known_vulnerable = {
        "cryptography": ["<3.4"],
        "requests": ["<2.31"],
        "urllib3": ["<1.26.18"],
        "jinja2": ["<3.1.2"],
        "sqlalchemy": ["<1.4.46"],
    }
    with open(req_file, encoding="utf-8") as f:
        content = f.read()
        for pkg, vuln_versions in known_vulnerable.items():
            for vuln in vuln_versions:
                if pkg in content and vuln in content:
                    pr.add("WARNING", "requirements.txt", 0, f"Package '{pkg}' uses {vuln}")
    if pr.count("WARNING") == 0:
        pr.add("PASS", "requirements.txt", 0, "No known vulnerable version constraints")
    pr.score = max(60, 100 - pr.count("WARNING") * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P17 — Secret Scanning (Context-aware) — skip checker
# =============================================================================
def p17_secret_scanning() -> PhaseResult:
    pr = PhaseResult("P17 Secret Scanning (Context-Aware)", weight=3)
    pr.disclaimer = "Context-aware pattern matching. Ignores test files and status constants."
    t0 = time.monotonic()
    files = all_py(include_checker=True)
    exempt_patterns = [
        "example",
        "changeme",
        "your_",
        "dummy",
        "test",
        "placeholder",
        "wrong_password",
        "minioadmin",
    ]
    exempt_status_constants = ["FAILURE_WRONG_PASSWORD", "ERROR_", "STATUS_", "SUCCESS_"]
    secrets_found = 0
    env_file = ROOT / ".env"
    if env_file.exists():
        env_lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno, line in enumerate(env_lines, 1):
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                if len(val.strip()) > 8 and val.strip() not in ["", "null", "None"]:
                    if any(
                        secret_word in key.lower()
                        for secret_word in ["password", "secret", "key", "token"]
                    ) and not any(ex in val.lower() for ex in exempt_patterns):
                        secrets_found += 1
                        pr.add("WARNING", str(env_file), lineno, f"Secret in .env: {key}=***")
    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rp = rel(path)
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            is_status_constant = any(const in line for const in exempt_status_constants)
            if is_status_constant:
                continue
            if re.search(
                r'(?i)(password|passwd|pwd)\s*=\s*["\']([^"\']{8,})["\']', line, re.IGNORECASE
            ):
                match = re.search(r'=\s*["\']([^"\']+)["\']', line)
                if match:
                    value = match.group(1)
                    if not any(ex in value.lower() for ex in exempt_patterns):
                        secrets_found += 1
                        pr.add(
                            "CRITICAL", rp, lineno, "Potential hardcoded secret", detail=line[:100]
                        )
            if re.search(
                r'(?i)secret[_\-]?key\s*=\s*["\']([A-Za-z0-9@#$!%^&*_\-]{8,})["\']',
                line,
                re.IGNORECASE,
            ):
                match = re.search(r'=\s*["\']([^"\']+)["\']', line)
                if match:
                    value = match.group(1)
                    if not any(ex in value.lower() for ex in exempt_patterns):
                        secrets_found += 1
                        pr.add(
                            "CRITICAL", rp, lineno, "Potential hardcoded secret", detail=line[:100]
                        )
    if secrets_found == 0:
        pr.add("PASS", ".", 0, "No hardcoded secret patterns found in production code")
    else:
        pr.add("INFO", ".", 0, f"Found {secrets_found} potential secret(s) in production code")
    pr.score = max(0, 100 - secrets_found * 10)
    if secrets_found > 0:
        pr.passed = False
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P18 — Hardcoded Credentials — skip checker
# =============================================================================
def p18_hardcoded_credentials() -> PhaseResult:
    pr = PhaseResult("P18 Hardcoded Credentials", weight=2)
    pr.disclaimer = "Pattern-based detection for database credentials."
    t0 = time.monotonic()
    files = all_py(include_checker=True)
    creds_found = 0
    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rp = rel(path)
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            if re.search(r'(?i)DB_PASSWORD\s*=\s*["\']([^"\']{4,})["\']', line, re.IGNORECASE):
                creds_found += 1
                pr.add("WARNING", rp, lineno, "DB_PASSWORD hardcoded", detail=line[:100])
            if re.search(
                r'(?i)DATABASE_URL\s*=\s*["\']postgresql://[^:]+:([^@]+)@', line, re.IGNORECASE
            ):
                creds_found += 1
                pr.add("WARNING", rp, lineno, "Database URL with password", detail=line[:100])
    if creds_found == 0:
        pr.add("PASS", ".", 0, "No hardcoded credential patterns found")
    pr.score = max(0, 100 - creds_found * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P19 — Logging Security — skip checker
# =============================================================================
def p19_logging_security() -> PhaseResult:
    pr = PhaseResult("P19 Logging Security", weight=2)
    pr.disclaimer = "Pattern-based detection of sensitive data in logs."
    t0 = time.monotonic()
    files = all_py(include_checker=True)
    sensitive_patterns = [
        (r"logger\.\w+\(.*password", "Logging password field"),
        (r"logger\.\w+\(.*secret", "Logging secret field"),
        (r"logger\.\w+\(.*token", "Logging token field"),
    ]
    issues = []
    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rp = rel(path)
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for pattern, msg in sensitive_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append((rp, lineno, msg))
                    break
    for rp, lineno, msg in issues[:20]:
        pr.add("WARNING", rp, lineno, msg, detail="Review logging of sensitive data")
    if not issues:
        pr.add("PASS", ".", 0, "No sensitive data logging patterns detected")
    pr.score = max(70, 100 - len(issues) * 3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P20 — SQL Injection (AST f-string detection) — skip checker
# =============================================================================
def p20_sql_injection() -> PhaseResult:
    pr = PhaseResult("P20 SQL Injection (AST)", weight=3)
    pr.disclaimer = "Detects f-strings containing SQL keywords. May have false positives."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations"})
    issues = []
    for path in files:
        if is_checker_file(path):
            continue
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue
        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                node_str = ast.unparse(node)
                sql_keywords = [
                    "SELECT",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "FROM",
                    "WHERE",
                    "CREATE",
                    "DROP",
                    "ALTER",
                ]
                if any(kw in node_str.upper() for kw in sql_keywords):
                    for value in node.values:
                        if isinstance(value, ast.FormattedValue):
                            issues.append((rp, node.lineno, "f-string SQL with interpolation"))
                            break
    for rp, lineno, msg in issues[:30]:
        pr.add("WARNING", rp, lineno, msg, detail="Possible SQL injection risk")
    if not issues:
        pr.add("PASS", ".", 0, "No f-string SQL injection patterns detected")
    else:
        pr.add("INFO", ".", 0, f"Found {len(issues)} potential SQL injection pattern(s)")
    pr.score = max(0, 100 - len(issues) * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P21 — ORM Enum Inheritance
# =============================================================================
def p21_orm_enums() -> PhaseResult:
    pr = PhaseResult("P21 ORM Enum Inheritance", weight=1)
    pr.disclaimer = "Detects SQLAlchemy.Enum inheritance instead of enum.Enum."
    t0 = time.monotonic()
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("INFO", "infrastructure/persistence_orm", 0, "ORM dir not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    bad = 0
    for path in sorted(orm_dir.glob("*.py")):
        tree = get_ast_tree(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if (
                        isinstance(base, ast.Attribute)
                        and isinstance(base.value, ast.Name)
                        and base.value.id == "sqlalchemy"
                        and base.attr == "Enum"
                    ):
                        bad += 1
                        pr.add(
                            "WARNING",
                            rel(path),
                            node.lineno,
                            f"'{node.name}' inherits sqlalchemy.Enum",
                        )
    if not bad:
        pr.add("PASS", "infrastructure/persistence_orm", 0, "No ORM Enum issues found")
    pr.score = max(0, 100 - bad * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P22 — Async Correctness (ubah INFO menjadi WARNING)
# =============================================================================
def p22_async_correctness() -> PhaseResult:
    pr = PhaseResult("P22 Async Correctness", weight=2)
    pr.disclaimer = "Detects common anti-patterns only."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    issues = []
    for path in files:
        tree = get_ast_tree(path)
        if tree is None:
            continue
        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "asyncio"
                    and node.func.attr == "run"
                ):
                    issues.append((rp, node.lineno, "asyncio.run() in module"))
                if isinstance(node.func, ast.Attribute) and node.func.attr == "run_until_complete":
                    issues.append((rp, node.lineno, "run_until_complete()"))
    # Ubah INFO -> WARNING agar selalu tampil
    for rp, lineno, msg in issues[:20]:
        pr.add("WARNING", rp, lineno, msg)
    if not issues:
        pr.add("PASS", ".", 0, "No common async anti-patterns detected")
    pr.score = max(80, 100 - len(issues) * 2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P23 — Kernel Guards
# =============================================================================
def p23_kernel_guards() -> PhaseResult:
    pr = PhaseResult("P23 Kernel Guards", weight=1)
    pr.disclaimer = "Verifies guard files exist. Does NOT verify guard logic."
    t0 = time.monotonic()
    guards_dir = ROOT / "kernel" / "guards"
    required_guards = ["period_lock.py", "balance_checker.py", "authority_matrix.py"]
    if not guards_dir.exists():
        pr.add("INFO", "kernel/guards", 0, "Guards directory not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    present = {f.name for f in guards_dir.glob("*.py")}
    for guard in required_guards:
        if guard not in present:
            pr.add("INFO", "kernel/guards", 0, f"Guard file not found: {guard}")
    if all(g in present for g in required_guards):
        pr.add("PASS", "kernel/guards", 0, "Required guard files present")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P24 — Double-Entry Pattern
# =============================================================================
def p24_double_entry_pattern() -> PhaseResult:
    pr = PhaseResult("P24 Double-Entry Pattern", weight=3)
    pr.disclaimer = "Verifies double-entry pattern exists. Does NOT verify debit=credit at runtime."
    t0 = time.monotonic()
    de_file = ROOT / "axioms" / "double_entry.py"
    if not de_file.exists():
        pr.add("CRITICAL", "axioms/double_entry.py", 0, "double_entry.py not found")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tree = get_ast_tree(de_file)
    if tree is None:
        pr.add("WARNING", "axioms/double_entry.py", 0, "Cannot parse file")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    has_debit_credit = False
    has_balance_check = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_text = ast.unparse(node)
            if "debit" in func_text.lower() and "credit" in func_text.lower():
                has_debit_credit = True
            if "balance" in func_text.lower() or "assert_balanced" in node.name.lower():
                has_balance_check = True
    if has_debit_credit and has_balance_check:
        pr.add("PASS", "axioms/double_entry.py", 0, "Double-entry pattern found")
    else:
        pr.add("WARNING", "axioms/double_entry.py", 0, "Double-entry pattern incomplete")
    pr.degrade(per_crit=20, per_warn=5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P25 — Journal Lifecycle Pattern
# =============================================================================
def p25_journal_lifecycle() -> PhaseResult:
    pr = PhaseResult("P25 Journal Lifecycle Pattern", weight=2)
    pr.disclaimer = "Verifies state machine pattern exists."
    t0 = time.monotonic()
    sm_file = ROOT / "domain" / "journal" / "state_machine.py"
    if not sm_file.exists():
        pr.add("WARNING", "domain/journal/state_machine.py", 0, "State machine not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    src = sm_file.read_text(encoding="utf-8", errors="replace")
    states = ["DRAFT", "POSTED", "REVERSED"]
    found_states = [s for s in states if s in src]
    if len(found_states) == len(states):
        pr.add("PASS", "domain/journal/state_machine.py", 0, "Journal lifecycle pattern found")
    else:
        pr.add(
            "WARNING",
            "domain/journal/state_machine.py",
            0,
            f"Missing states: {set(states) - set(found_states)}",
        )
    pr.degrade(per_crit=15, per_warn=3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P26 — Fiscal Period Pattern
# =============================================================================
def p26_fiscal_period() -> PhaseResult:
    pr = PhaseResult("P26 Fiscal Period Pattern", weight=2)
    pr.disclaimer = "Verifies open/close/lock methods exist."
    t0 = time.monotonic()
    fp_file = ROOT / "domain" / "fiscal_period" / "aggregate_root.py"
    if not fp_file.exists():
        pr.add("INFO", "domain/fiscal_period/aggregate_root.py", 0, "Not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    src = fp_file.read_text(encoding="utf-8", errors="replace")
    ops = {"open": False, "close": False, "lock": False}
    for op in ops:
        if op in src.lower():
            ops[op] = True
    missing_ops = [op for op, found in ops.items() if not found]
    if not missing_ops:
        pr.add(
            "PASS",
            "domain/fiscal_period/aggregate_root.py",
            0,
            "Fiscal period open/close/lock pattern found",
        )
    else:
        pr.add(
            "WARNING",
            "domain/fiscal_period/aggregate_root.py",
            0,
            f"Missing methods: {missing_ops}",
        )
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P27 — Immutable Audit Pattern
# =============================================================================
def p27_immutable_audit() -> PhaseResult:
    pr = PhaseResult("P27 Immutable Audit Pattern", weight=2)
    pr.disclaimer = "Verifies append-only pattern."
    t0 = time.monotonic()
    ew_file = ROOT / "audit" / "event_writer_immutable.py"
    if not ew_file.exists():
        pr.add("WARNING", "audit/event_writer_immutable.py", 0, "Not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tree = get_ast_tree(ew_file)
    if tree is None:
        pr.add("WARNING", "audit/event_writer_immutable.py", 0, "Cannot parse")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    dangerous = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
            x in node.name.lower() for x in ("update", "delete", "modify", "edit", "overwrite")
        ):
            dangerous.append(node.name)
    if dangerous:
        pr.add(
            "WARNING", "audit/event_writer_immutable.py", 0, f"Mutation methods found: {dangerous}"
        )
    else:
        pr.add("PASS", "audit/event_writer_immutable.py", 0, "Append-only pattern confirmed")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P28 — Monetary Decimal Pattern
# =============================================================================
_MONETARY_FIELDS = [
    "amount",
    "debit",
    "credit",
    "price",
    "cost",
    "tax",
    "total",
    "balance",
    "value",
]


def p28_monetary_decimal() -> PhaseResult:
    pr = PhaseResult("P28 Monetary Decimal Pattern", weight=3)
    pr.disclaimer = "Detects float usage for monetary fields. Does NOT verify Decimal correctness."
    t0 = time.monotonic()
    domain_files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    violations = []
    for path in domain_files:
        if is_test_file(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rp = rel(path)
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for field in _MONETARY_FIELDS:
                if re.search(rf"{field}\s*:\s*float\b", line, re.IGNORECASE):
                    violations.append((rp, lineno, "WARNING", f"float type hint for {field}"))
                if re.search(rf"{field}\s*=\s*float\s*\(", line, re.IGNORECASE):
                    violations.append((rp, lineno, "WARNING", f"float() call for {field}"))
    for rp, lineno, sev, msg in violations[:30]:
        pr.add(sev, rp, lineno, msg, detail="Use Decimal for monetary values")
    if not violations:
        pr.add("PASS", ".", 0, "No float monetary field patterns found")
    else:
        pr.add("INFO", ".", 0, f"Found {len(violations)} float monetary usage(s)")
    pr.score = max(0, 100 - len(violations) * 3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P29 — ACID Pattern
# =============================================================================
def p29_acid_pattern() -> PhaseResult:
    pr = PhaseResult("P29 ACID Pattern", weight=2)
    pr.disclaimer = "Verifies Unit of Work pattern exists. Does NOT verify ACID at runtime."
    t0 = time.monotonic()
    uow_file = ROOT / "ports" / "primary" / "unit_of_work_port.py"
    if not uow_file.exists():
        pr.add("WARNING", "ports/primary/unit_of_work_port.py", 0, "UoW port not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    src = uow_file.read_text(encoding="utf-8", errors="replace")
    has_commit = "commit" in src
    has_rollback = "rollback" in src
    if has_commit and has_rollback:
        pr.add("PASS", "ports/primary/unit_of_work_port.py", 0, "Unit of Work pattern found")
    else:
        missing = []
        if not has_commit:
            missing.append("commit")
        if not has_rollback:
            missing.append("rollback")
        pr.add("WARNING", "ports/primary/unit_of_work_port.py", 0, f"Missing: {missing}")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P30 — Constitution Isolation
# =============================================================================
def p30_constitution_isolation() -> PhaseResult:
    pr = PhaseResult("P30 Constitution Isolation", weight=1)
    pr.disclaimer = "Static import check only."
    t0 = time.monotonic()
    domain_dir = ROOT / "domain"
    if not domain_dir.exists():
        pr.add("INFO", "domain/", 0, "Domain directory not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    violations = []
    for path in domain_dir.rglob("*.py"):
        src = path.read_text(encoding="utf-8", errors="replace")
        if "from constitution" in src or "import constitution" in src:
            violations.append(rel(path))
    for vf in violations[:5]:
        pr.add("INFO", vf, 0, "Domain imports constitution (may violate purity)")
    if not violations:
        pr.add("PASS", "domain/", 0, "No direct constitution imports in domain")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P31 — ORM Primary Key Pattern
# =============================================================================
def p31_orm_primary_keys() -> PhaseResult:
    pr = PhaseResult("P31 ORM Primary Key Pattern", weight=1)
    pr.disclaimer = "Verifies primary_key declaration exists."
    t0 = time.monotonic()
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("INFO", "infrastructure/persistence_orm", 0, "ORM dir not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    no_pk = 0
    for orm_file in orm_dir.glob("*_table.py"):
        src = orm_file.read_text(encoding="utf-8", errors="replace")
        if not any(x in src for x in ("primary_key=True", "PrimaryKeyConstraint")):
            no_pk += 1
            pr.add("INFO", rel(orm_file), 0, "No primary_key declaration found")
    if no_pk == 0:
        pr.add("PASS", "infrastructure/persistence_orm", 0, "Primary key declarations found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P32 — Referential Integrity Pattern
# =============================================================================
def p32_referential_integrity() -> PhaseResult:
    pr = PhaseResult("P32 Referential Integrity Pattern", weight=1)
    pr.disclaimer = "Verifies ForeignKey declarations exist."
    t0 = time.monotonic()
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("INFO", "infrastructure/persistence_orm", 0, "ORM dir not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    fk_pattern = r"ForeignKey\s*\("
    fk_count = 0
    for orm_file in orm_dir.glob("*.py"):
        src = orm_file.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(fk_pattern, src, re.IGNORECASE)
        fk_count += len(matches)
    if fk_count > 0:
        pr.add(
            "PASS", "infrastructure/persistence_orm", 0, f"Found {fk_count} ForeignKey declarations"
        )
    else:
        pr.add("INFO", "infrastructure/persistence_orm", 0, "No ForeignKey declarations found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P33 — Concurrency Pattern
# =============================================================================
def p33_concurrency_pattern() -> PhaseResult:
    pr = PhaseResult("P33 Concurrency Pattern", weight=1)
    pr.disclaimer = "Detects version field patterns. Does NOT verify concurrency safety."
    t0 = time.monotonic()
    version_patterns = ["version", "optimistic_lock", "row_version"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        for pattern in version_patterns:
            if pattern in src.lower():
                found = True
                pr.add("PASS", rel(path), 0, f"Version field pattern: {pattern}")
                break
        if found:
            break
    if not found:
        pr.add("INFO", ".", 0, "No optimistic locking pattern detected")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P34 — COGS Pattern
# =============================================================================
def p34_cogs_pattern() -> PhaseResult:
    pr = PhaseResult("P34 COGS Pattern", weight=2)
    pr.disclaimer = "Verifies COGS calculation pattern exists."
    t0 = time.monotonic()
    cogs_patterns = ["cogs", "cost_of_goods_sold", "hpp"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        for pattern in cogs_patterns:
            if pattern in src.lower():
                if any(x in src.lower() for x in ["beginning", "purchase", "ending"]):
                    found = True
                    pr.add("PASS", rel(path), 0, f"COGS calculation pattern: {pattern}")
                    break
        if found:
            break
    if not found:
        pr.add("INFO", ".", 0, "COGS calculation pattern not clearly found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P35 — Tax Calculation Pattern
# =============================================================================
def p35_tax_pattern() -> PhaseResult:
    pr = PhaseResult("P35 Tax Calculation Pattern", weight=2)
    pr.disclaimer = "Verifies tax calculator files exist."
    t0 = time.monotonic()
    tax_dir = ROOT / "policy_engine" / "tax_indonesia"
    if not tax_dir.exists():
        pr.add("INFO", "policy_engine/tax_indonesia", 0, "Tax directory not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tax_calculators = [
        "ppn_calculator",
        "pph_21_calculator",
        "pph_23_calculator",
        "pph_badan_calculator",
    ]
    found = [c for c in tax_calculators if (tax_dir / f"{c}.py").exists()]
    if len(found) >= 3:
        pr.add("PASS", "policy_engine/tax_indonesia", 0, f"Tax calculators found: {len(found)}")
    else:
        pr.add("INFO", "policy_engine/tax_indonesia", 0, f"Only {len(found)} tax calculators found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P36 — Depreciation Pattern
# =============================================================================
def p36_depreciation_pattern() -> PhaseResult:
    pr = PhaseResult("P36 Depreciation Pattern", weight=2)
    pr.disclaimer = "Verifies depreciation method patterns exist."
    t0 = time.monotonic()
    dep_patterns = ["depreciation", "straight_line", "declining_balance"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        if any(p in src.lower() for p in dep_patterns):
            found = True
            pr.add("PASS", rel(path), 0, "Depreciation calculation pattern found")
            break
    if not found:
        pr.add("INFO", ".", 0, "Depreciation pattern not clearly found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P37 — Inventory Valuation Pattern
# =============================================================================
def p37_inventory_valuation() -> PhaseResult:
    pr = PhaseResult("P37 Inventory Valuation Pattern", weight=2)
    pr.disclaimer = "Verifies valuation method patterns exist."
    t0 = time.monotonic()
    inv_dir = ROOT / "domain" / "inventory"
    if not inv_dir.exists():
        pr.add("INFO", "domain/inventory", 0, "Inventory directory not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    valuation_methods = ["fifo", "weighted_average", "moving_average"]
    found = []
    for inv_file in inv_dir.glob("*.py"):
        src = inv_file.read_text(encoding="utf-8", errors="replace")
        for method in valuation_methods:
            if method in src.lower():
                found.append(method)
                pr.add("PASS", rel(inv_file), 0, f"Valuation method: {method}")
    if not found:
        pr.add("INFO", "domain/inventory", 0, "No inventory valuation pattern found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P38 — Fiscal Closing Pattern
# =============================================================================
def p38_fiscal_closing() -> PhaseResult:
    pr = PhaseResult("P38 Fiscal Closing Pattern", weight=2)
    pr.disclaimer = "Verifies closing procedure pattern exists."
    t0 = time.monotonic()
    closing_patterns = ["period_close", "year_end", "fiscal_closing"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        for pattern in closing_patterns:
            if pattern in src.lower():
                found = True
                pr.add("PASS", rel(path), 0, f"Fiscal closing pattern: {pattern}")
                break
        if found:
            break
    if not found:
        pr.add("INFO", ".", 0, "Fiscal closing pattern not clearly found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P39 — Retained Earnings Pattern
# =============================================================================
def p39_retained_earnings() -> PhaseResult:
    pr = PhaseResult("P39 Retained Earnings Pattern", weight=2)
    pr.disclaimer = "Verifies retained earnings pattern exists."
    t0 = time.monotonic()
    re_patterns = ["retained_earnings", "retainedearning"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        for pattern in re_patterns:
            if pattern in src.lower():
                found = True
                pr.add("PASS", rel(path), 0, f"Retained earnings pattern: {pattern}")
                break
        if found:
            break
    if not found:
        pr.add("INFO", ".", 0, "Retained earnings pattern not clearly found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P40 — Pytest Suite
# =============================================================================
def p40_pytest(quick: bool = False) -> PhaseResult:
    pr = PhaseResult("P40 Pytest Suite", weight=3)
    pr.disclaimer = "Collects test counts via pytest --collect-only. Does NOT verify test quality."
    t0 = time.monotonic()
    if quick:
        pr.add("INFO", ".", 0, "Pytest skipped (--quick)")
        pr.score = -1
        pr.finalize_status()
        pr.duration = 0.0
        return pr

    test_path = ROOT / "tests"
    if not test_path.exists():
        pr.add("WARNING", "tests/", 0, "tests directory not found")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        "--collect-only",
        "-q",
        "--no-header",
        "--disable-warnings",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(ROOT))
        output = result.stdout + result.stderr
        patterns = [
            r"collected\s+(\d+)\s+items?",
            r"collected\s+(\d+)\s+tests?",
            r"(\d+)\s+tests? collected",
            r"collected\s+(\d+)",
        ]
        test_count = 0
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                test_count = int(match.group(1))
                break
        if test_count == 0:
            summary_match = re.search(r"===+\s+(\d+)\s+passed", output)
            if summary_match:
                test_count = int(summary_match.group(1))
                skipped_match = re.search(r"(\d+)\s+skipped", output)
                if skipped_match:
                    test_count += int(skipped_match.group(1))

        if test_count > 0:
            pr.add("PASS", "tests/", 0, f"Found {test_count} tests via pytest collection")
            # Score based on test count: up to 100 for 1000 tests
            pr.score = min(100, test_count // 10)
        else:
            if result.returncode == 0 or "passed" in output:
                pr.add("WARNING", "tests/", 0, "Tests exist but count could not be determined")
                pr.score = 50
            else:
                pr.add("WARNING", "tests/", 0, "No tests collected or pytest collection failed")
                pr.score = 0
    except subprocess.TimeoutExpired:
        pr.add("WARNING", "tests/", 0, "Pytest collection timed out after 60s")
        pr.score = 30
    except Exception as e:
        pr.add("WARNING", "tests/", 0, f"Pytest collection error: {type(e).__name__}")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P41 — Compliance Structure
# =============================================================================
_COMPLIANCE_FILES = [
    "policy_engine/psak/psak_aggregator.py",
    "policy_engine/ifrs/ifrs_aggregator.py",
    "compliance/psak_checker.py",
    "compliance/ifrs_checker.py",
]


def p41_compliance_structure() -> PhaseResult:
    pr = PhaseResult("P41 Compliance Structure", weight=2)
    pr.disclaimer = "Verifies compliance files exist."
    t0 = time.monotonic()
    found = 0
    for file_path in _COMPLIANCE_FILES:
        if (ROOT / file_path).exists():
            found += 1
    if found == len(_COMPLIANCE_FILES):
        pr.add("PASS", ".", 0, f"All {found} compliance files found")
    else:
        pr.add("INFO", ".", 0, f"Compliance files: {found}/{len(_COMPLIANCE_FILES)}")
    pr.score = int(found / len(_COMPLIANCE_FILES) * 100) if _COMPLIANCE_FILES else 0
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# P42 — Schema Consistency
# =============================================================================
def p42_schema_consistency() -> PhaseResult:
    pr = PhaseResult("P42 Schema Consistency", weight=3)
    pr.disclaimer = "Compares ORM table definitions with migration create_table statements."
    t0 = time.monotonic()
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    alembic_dir = ROOT / "migrations" / "versions"
    if not orm_dir.exists() or not alembic_dir.exists():
        pr.add("INFO", ".", 0, "ORM or migrations directory not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    orm_tables = set()
    for orm_file in orm_dir.glob("*_table.py"):
        src = orm_file.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r'__tablename__\s*=\s*["\']([^"\']+)["\']', src)
        orm_tables.update(matches)
    migration_tables = set()
    for mig_file in alembic_dir.glob("*.py"):
        src = mig_file.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r'create_table\s*\(\s*["\']([^"\']+)["\']', src, re.IGNORECASE)
        migration_tables.update(matches)
        create_pattern = r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\`]?(\w+)["\`]?'
        execute_matches = re.findall(create_pattern, src, re.IGNORECASE)
        migration_tables.update(execute_matches)
    only_in_orm = orm_tables - migration_tables
    for table in list(only_in_orm)[:10]:
        pr.add(
            "WARNING",
            "infrastructure/persistence_orm",
            0,
            f"Table '{table}' in ORM but not in migrations",
        )
    if not only_in_orm:
        pr.add("PASS", ".", 0, "ORM and migration table definitions consistent")
    else:
        pr.add("WARNING", ".", 0, f"Found {len(only_in_orm)} table(s) in ORM not in migrations")
    pr.score = max(0, 100 - len(only_in_orm) * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


# =============================================================================
# HARD FAIL RULES
# =============================================================================
def check_hard_fail(results: list[PhaseResult]) -> list[str]:
    reasons: list[str] = []
    for pr in results:
        for f in pr.findings:
            if f.severity != "CRITICAL":
                continue
            msg = f.message.lower()
            if "orphan" in msg or "multiple heads" in msg:
                reasons.append(f"[{pr.name}] {f.message[:80]} @ {f.file}")
            if "hardcoded secret" in msg:
                reasons.append(f"[{pr.name}] {f.message[:80]} @ {f.file}")
            if "double_entry.py not found" in msg:
                reasons.append(f"[{pr.name}] {f.message[:80]}")
    return list(dict.fromkeys(reasons))


# =============================================================================
# SCORING ENGINE
# =============================================================================
_GRADES = [
    (97, "S — SOVEREIGN (Structurally Excellent)"),
    (90, "A — EXCELLENT (Well-structured)"),
    (85, "B — GOOD (Minor structural issues)"),
    (75, "C — ACCEPTABLE (Structural improvements needed)"),
    (60, "D — NEEDS WORK (Major structural gaps)"),
    (0, "F — NOT DEPLOYABLE"),
]


def grade(score: int) -> str:
    for threshold, label in _GRADES:
        if score >= threshold:
            return label
    return "F — NOT DEPLOYABLE"


def grade_col(score: int) -> str:
    if score >= 85:
        return GREEN
    if score >= 60:
        return YELLOW
    return RED


def weighted_score(results: list[PhaseResult]) -> tuple[int, int]:
    tw = ws = 0
    for pr in results:
        if pr.score == -1:
            continue
        tw += pr.weight
        ws += pr.score * pr.weight
    base = int(ws / tw) if tw else 0
    crits = sum(pr.count("CRITICAL") for pr in results)
    penalty = min(crits * 3, 30)
    return base, max(0, base - penalty)


# =============================================================================
# PHASE REGISTRY
# =============================================================================
_ALL_PHASES: list[tuple[str, Any, bool]] = [
    ("environment", p00_environment, False),
    ("structure", p01_structure, False),
    ("syntax", p02_syntax, False),
    ("self_audit", p03_self_audit, False),
    ("circular", p04_circular, False),
    ("static_imports", p05_static_imports, False),
    ("dynamic", p06_dynamic_imports, False),
    ("broken_imports", p07_broken_imports, False),
    ("architecture", p08_architecture, False),
    ("port_adapter", p09_port_adapter, False),
    ("routes", p10_routes, False),
    ("yaml", p11_yaml, False),
    ("asgi", p12_asgi, False),
    ("migrations", p13_migrations, False),
    ("quality", p14_quality, False),
    ("security", p15_security, False),
    ("dependency", p16_dependency_audit, False),
    ("secrets", p17_secret_scanning, False),
    ("credentials", p18_hardcoded_credentials, False),
    ("logging_security", p19_logging_security, False),
    ("sql_injection", p20_sql_injection, False),
    ("orm_enums", p21_orm_enums, False),
    ("async", p22_async_correctness, False),
    ("kernel_guards", p23_kernel_guards, False),
    ("double_entry", p24_double_entry_pattern, False),
    ("journal_lifecycle", p25_journal_lifecycle, False),
    ("fiscal_period", p26_fiscal_period, False),
    ("immutable_audit", p27_immutable_audit, False),
    ("monetary_decimal", p28_monetary_decimal, False),
    ("acid_pattern", p29_acid_pattern, False),
    ("constitution_isolation", p30_constitution_isolation, False),
    ("orm_primary_keys", p31_orm_primary_keys, False),
    ("referential_integrity", p32_referential_integrity, False),
    ("concurrency_pattern", p33_concurrency_pattern, False),
    ("cogs_pattern", p34_cogs_pattern, False),
    ("tax_pattern", p35_tax_pattern, False),
    ("depreciation_pattern", p36_depreciation_pattern, False),
    ("inventory_valuation", p37_inventory_valuation, False),
    ("fiscal_closing", p38_fiscal_closing, False),
    ("retained_earnings", p39_retained_earnings, False),
    ("pytest", p40_pytest, True),
    ("compliance", p41_compliance_structure, False),
    ("schema_consistency", p42_schema_consistency, False),
]


# =============================================================================
# RUNNER
# =============================================================================
def _print_phase(pr: PhaseResult, verbose: bool) -> None:
    if pr.score == -1:
        sc_str = f"{CYAN}SKIP{RESET}"
    else:
        col = grade_col(pr.score)
        sc_str = f"{col}{pr.score:3d}/100{RESET}"
    if pr.count("CRITICAL") > 0 or pr.score == 0:
        status_str = f"{RED}✖ FAIL{RESET}"
    elif pr.score < 70:
        status_str = f"{YELLOW}⚠ WARN{RESET}"
    else:
        status_str = f"{GREEN}✔ PASS{RESET}"
    print(f"\n{BOLD}[{pr.name}]{RESET}  {status_str}  {sc_str}  ({pr.duration:.1f}s)")
    if pr.disclaimer and verbose:
        print(f"  {CYAN}ℹ {pr.disclaimer}{RESET}")
    shown_pass = False
    for f in pr.findings:
        if f.severity == "CRITICAL":
            pf(f, verbose=True)  # Always show full detail for CRITICAL
        elif f.severity == "WARNING":
            pf(f, verbose=verbose)  # Will show file+line always (see pf function)
        elif f.severity in ("INFO", "PASS") and verbose:
            pf(f, verbose=False)
        elif f.severity == "PASS" and not verbose and not shown_pass:
            print(f"  {GREEN}✔ {f.message}{RESET}")
            shown_pass = True


def run(phase_filter: str | None, quick: bool, verbose: bool, json_out: str | None) -> int:
    print(banner("SOVEREIGN ERP — STRUCTURAL INTEGRITY AUDITOR v11.5 (CLEAR OUTPUT)"))
    print(f"  Root   : {ROOT}")
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  Mode   : {'QUICK' if quick else 'FULL AUDIT'}")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n  {YELLOW}NOTE: This auditor verifies CODE STRUCTURE only.{RESET}")
    print(f"  {YELLOW}      It does NOT prove runtime correctness or financial accuracy.{RESET}")
    results: list[PhaseResult] = []
    g_t0 = time.monotonic()
    for key, fn, takes_quick in _ALL_PHASES:
        if phase_filter and key != phase_filter:
            continue
        print(f"\n{CYAN}▶ {key.upper()}{RESET}")
        try:
            pr = fn(quick=quick) if takes_quick else fn()
        except Exception as e:
            pr = PhaseResult(f"CRASH:{key}", weight=5, score=0, passed=False)
            pr.add("CRITICAL", "checker_internal", 0, f"Phase crashed: {type(e).__name__}")
            pr.detail = traceback.format_exc()
            pr.finalize_status()
        results.append(pr)
        _print_phase(pr, verbose)
    base, adj = weighted_score(results)
    hard_fails = check_hard_fail(results)
    total_crits = sum(pr.count("CRITICAL") for pr in results)
    total_warns = sum(pr.count("WARNING") for pr in results)
    elapsed = time.monotonic() - g_t0
    if hard_fails:
        adj = min(adj, 59)
    print(banner("STRUCTURAL AUDIT REPORT"))
    W = 50
    filled = int(W * adj / 100)
    bc = grade_col(adj)
    bar = f"{bc}{'█' * filled}{'░' * (W - filled)}{RESET}"
    print(f"\n  Score  : {bc}{BOLD}{adj}/100{RESET}  (base {base} − {base - adj} penalty)")
    print(f"  Grade  : {bc}{BOLD}{grade(adj)}{RESET}")
    print(f"  [{bar}]")
    print()
    print(f"  Critical findings : {RED}{BOLD}{total_crits}{RESET}")
    print(f"  Warnings          : {YELLOW}{total_warns}{RESET}")
    print(f"  Duration          : {elapsed:.1f}s")
    if hard_fails:
        print(f"\n  {RED}{BOLD}⛔ HARD FAIL — Grade forced to F:{RESET}")
        for reason in hard_fails[:5]:
            print(f"    {RED}✖{RESET} {reason}")
    print()
    if hard_fails:
        code = 2
        print(f"  {RED}{BOLD}✖ NOT DEPLOYABLE — Resolve hard fails{RESET}")
    elif adj >= 85 and total_crits == 0:
        code = 0
        print(f"  {GREEN}{BOLD}✔ STRUCTURALLY READY — {adj}/100  [{grade(adj)}]{RESET}")
    elif adj >= 60:
        code = 1
        print(f"  {YELLOW}{BOLD}⚠ STRUCTURAL ISSUES — {adj}/100  [{grade(adj)}]{RESET}")
    else:
        code = 2
        print(f"  {RED}{BOLD}✖ NOT DEPLOYABLE — {adj}/100  [{grade(adj)}]{RESET}")
    if json_out:
        report = {
            "checker_version": "11.5",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "score": adj,
            "grade": grade(adj),
            "criticals": total_crits,
            "warnings": total_warns,
            "hard_fails": hard_fails,
            "duration_seconds": round(elapsed, 2),
        }
        try:
            pathlib.Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"\n  {CYAN}JSON → {json_out}{RESET}")
        except Exception as ex:
            print(f"\n  {RED}JSON save failed: {ex}{RESET}")
    return code


def main() -> None:
    phase_keys = [k for k, _, _ in _ALL_PHASES]
    ap = argparse.ArgumentParser(
        description="Sovereign ERP — Structural Integrity Auditor v11.5 (Clear Output)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(f"""
        Phases: {", ".join(phase_keys[:10])}... (total {len(phase_keys)} phases)

        PASS/FAIL Rules:
          - PASS: score >= 70 AND no CRITICAL findings
          - WARN: score < 70 but no CRITICAL (needs improvement)
          - FAIL: ANY CRITICAL exists OR score == 0

        This auditor verifies CODE STRUCTURE only.
        It does NOT prove runtime correctness or financial accuracy.
        """),
    )
    ap.add_argument("--quick", action="store_true", help="Skip pytest")
    ap.add_argument("--phase", choices=phase_keys, metavar="PHASE", help="Run single phase")
    ap.add_argument("--verbose", action="store_true", help="All findings including disclaimers")
    ap.add_argument("--json", metavar="FILE", help="Save JSON report")
    ap.add_argument("--no-color", action="store_true", help="Disable colour")
    args = ap.parse_args()
    if args.no_color:
        _setup_colour(False)
    sys.exit(
        run(phase_filter=args.phase, quick=args.quick, verbose=args.verbose, json_out=args.json)
    )


if __name__ == "__main__":
    main()
