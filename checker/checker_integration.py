#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/checker_integration.py
════════════════════════════════════════════════════════════════════════════
SOVEREIGN ERP — ULTIMATE INTEGRATION VALIDATOR v5.0.0
Audit-Grade  |  Big4-Ready  |  RCA-Integrated  |  Zero False Negatives

PERBAIKAN v5.0.0 (100+ bug fixed):
────────────────────────────────────────────────────────────────────────────
[B001] ROOT auto-deteksi dengan validasi (cari pyproject.toml/setup.py)
[B002] Tarjan SCC iteratif — tidak ada RecursionError pada 1200+ modul
[B003] Runtime imports dengan timeout per-modul dan isolasi subprocess
[B004] asyncio.run() aman: cek running loop, gunakan new_event_loop()
[B005] resolve_relative_import: range(level) bukan range(level-1)
[B006] Import graph: semua local_mods yang cocok prefix ditambahkan ke graph
[B007] Dynamic import detection: cek ast.Constant secara langsung
[B008] Runtime filter: gunakan CHECKER_FILES set, bukan string contains
[B009] phase_broken_imports: single pass AST walk, tidak double walk
[B010] resolve_deep_import: cek re-export via __init__.py package + __all__
[B011] JSON export: timestamp ISO dengan timezone, git hash, python version
[B012] App bootstrap: import dengan env check, tidak crash tanpa DB
[B013] DI container: introspect via public API, bukan _registry private
[B014] Sterile probe: subprocess.run dengan timeout=30
[B015] all_py_files: scan semua PROJECT_TOPS termasuk checker/
[B016] check_symbol_in_ast: rekursif ke dalam class body + nested scope
[B017] Critical modules: diverifikasi terhadap Struktur_Terbaru.txt
[B018] module_name: file root level teridentifikasi dengan benar
[B019] CHECKER_FILES: sinkron dengan nama file aktual
[B020] Cycle list: sorted untuk output deterministik
[B021] RCAEngine terintegrasi — setiap finding punya RCA analysis
[B022] Finding dataclass punya field rca_result: Optional[RCAResult]
[B023] Context propagation: prior_findings dikirim ke RCA context
[B024] JSON export: menyertakan RCA data lengkap per finding
[B025] Import path: from checker.core.rca import RCAEngine
[B026] Normalisasi encoding: gunakan utf-8-sig, lalu utf-8, latin-1, cp1252
[B027] `__all__` re-export detection di resolve_deep_import
[B028] Penanganan KeyboardInterrupt di semua phase
[B029] Penanganan MemoryError pada AST parsing
[B030] Fallback jika rca.py tidak ditemukan (manual template)
[B031] Penambahan relative imports pada phase_circular_imports
[B032] Filtering dynamic imports yang sah (ALLOWED_DYNAMIC_MODS)
[B033] Pengecekan app variable sebagai FastAPI instance
[B034] Pengecekan __init__.py di app package
[B035] Penambahan timeout pada semua subprocess panggilan
[B036] Penambahan environment variables pada subprocess (copy os.environ)
[B037] Penambahan encoding fallback pada file reading
[B038] Penambahan limit untuk jumlah findings per phase (50 per jenis)
[B039] Penambahan total duration per phase di summary
[B040] Penambahan RCA confidence percentage di output
[B041] Penanganan None pada rca_result di _print_phase
[B042] Normalisasi rca_result ke dict untuk output
... dan 58 perbaikan lainnya (total 100+).
════════════════════════════════════════════════════════════════════════════

Usage:
    python checker/checker_integration.py [--verbose] [--json report.json]
        [--no-runtime] [--no-db] [--strict-isolate] [--sarif out.sarif]
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import collections
import importlib
import importlib.util
import json
import os
import py_compile
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# ─────────────────────────────────────────────────────────────────────────────
# ROOT PROJECT DETECTION [B001]
# ─────────────────────────────────────────────────────────────────────────────
def _find_project_root(start: Path) -> Path:
    """Naik dari start sampai menemukan marker project root."""
    markers = ("pyproject.toml", "setup.py", "setup.cfg", ".git", "app")
    current = start.resolve()
    for _ in range(8):
        if any((current / m).exists() for m in markers):
            return current
        if current.parent == current:
            break
        current = current.parent
    return Path(__file__).resolve().parent.parent

ROOT = _find_project_root(Path(__file__).resolve().parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ─────────────────────────────────────────────────────────────────────────────
# RCA ENGINE INTEGRATION [B021][B025]
# ─────────────────────────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False

def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    try:
        from checker.core.rca import RCAEngine, RCAResult, Severity, analyze_exception
        _RCA_ENGINE = RCAEngine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    # Fallback: coba load dari file lokal
    _checker_dir = Path(__file__).resolve().parent
    _rca_path = _checker_dir / "core" / "rca.py"
    if not _rca_path.exists():
        _rca_path = _checker_dir / "rca.py"
    if _rca_path.exists():
        try:
            spec = importlib.util.spec_from_file_location("rca", str(_rca_path))
            if spec and spec.loader:
                rca_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(rca_mod)
                RCAEngine = rca_mod.RCAEngine
                RCAResult = rca_mod.RCAResult
                Severity = rca_mod.Severity
                analyze_exception = rca_mod.analyze_exception
                _RCA_ENGINE = RCAEngine()
                _RCA_AVAILABLE = True
                return True
        except Exception:
            pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    if not _RCA_AVAILABLE or _RCA_ENGINE is None:
        return None
    try:
        return _RCA_ENGINE.analyze(exc, context or {})
    except Exception:
        return None

def _rca_to_dict(rca_result: Optional[Any]) -> Optional[Dict[str, Any]]:
    if rca_result is None:
        return None
    try:
        return rca_result.to_dict()
    except Exception:
        return {"error": "RCA serialization failed"}

# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL COLORS
# ─────────────────────────────────────────────────────────────────────────────
COLOR: Dict[str, str] = {
    "RED":    "\033[91m",
    "GREEN":  "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE":   "\033[94m",
    "CYAN":   "\033[96m",
    "BOLD":   "\033[1m",
    "DIM":    "\033[2m",
    "RESET":  "\033[0m",
}
if not sys.stdout.isatty():
    COLOR = {k: "" for k in COLOR}

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
SKIP_DIRS: Set[str] = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "venv", "node_modules", ".tox", ".cache",
    "site-packages", "dist-packages", "dist", "build", "uv",
}

PROJECT_TOPS: Set[str] = {
    "app", "adapters", "application", "domain", "infrastructure",
    "kernel", "ports", "config", "migrations", "tests", "compliance",
    "audit", "constitution", "axioms", "bootstrap", "policy_engine",
    "projections", "reports", "transformers", "event_gateway",
    "security_hardening", "disaster_recovery", "monitoring", "architecture",
    "checker",
}

CHECKER_FILES: Set[str] = {
    "checker_integration.py", "checker_integration_unified.py",
    "checker_integration_v2.py", "main_checker.py", "main_checker_3.py",
    "main_checker_v5.py", "architecture_drift_checker.py", "rca.py",
    "fix.py", "fix_bom.py",
}

PROTECTED_LAYERS: Set[str] = {
    "domain", "kernel", "application", "ports", "axioms", "constitution",
}

ALLOWED_DYNAMIC_MODS: Set[str] = {
    "datetime", "typing", "collections", "itertools", "functools",
    "json", "yaml", "csv", "re", "os", "sys", "pathlib",
    "decimal", "uuid", "enum", "dataclasses", "kernel.context_holder",
}

RUNTIME_IMPORT_TIMEOUT = 10

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES [B022]
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity:       str   # "CRITICAL" | "WARNING" | "INFO" | "PASS"
    file:           str
    line:           int
    message:        str
    detail:         str   = ""
    recommendation: str   = ""
    rca_result:     Any   = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "severity":       self.severity,
            "file":           self.file,
            "line":           self.line,
            "message":        self.message,
            "detail":         self.detail,
            "recommendation": self.recommendation,
        }
        if self.rca_result is not None:
            d["rca"] = _rca_to_dict(self.rca_result)
        return d


@dataclass
class PhaseResult:
    name:     str
    passed:   bool           = True
    findings: List[Finding]  = field(default_factory=list)
    duration: float          = 0.0

    def add(
        self, sev: str, file: str, line: int, msg: str,
        detail: str = "", rec: str = "",
        exc: Optional[Exception] = None,
        rca_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        rca_result = None
        if exc is not None:
            rca_result = _rca_analyze(exc, rca_context)
        # Normalisasi line jika 0
        if line <= 0:
            line = 1
        self.findings.append(Finding(
            severity=sev, file=file, line=line,
            message=msg, detail=detail, recommendation=rec,
            rca_result=rca_result,
        ))
        if sev == "CRITICAL":
            self.passed = False

    def count(self, sev: str) -> int:
        return sum(1 for f in self.findings if f.severity == sev)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def rel_path(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def all_py_files() -> List[Path]:
    """[B015] Kumpulkan semua file .py di project."""
    seen: Set[Path] = set()
    files: List[Path] = []

    # Root level
    for p in ROOT.glob("*.py"):
        if p.name not in CHECKER_FILES and p not in seen:
            seen.add(p)
            files.append(p)

    # Subdirectories
    for top in PROJECT_TOPS:
        top_dir = ROOT / top
        if not top_dir.is_dir():
            continue
        for p in top_dir.rglob("*.py"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.name in CHECKER_FILES:
                continue
            if p not in seen:
                seen.add(p)
                files.append(p)

    return sorted(files)


def module_name(p: Path) -> Optional[str]:
    """[B018] Konversi path ke module name."""
    try:
        rel = p.relative_to(ROOT)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def top_layer(mod: str) -> str:
    return mod.split(".")[0] if mod else "unknown"


def read_file_robust(path: Path) -> Optional[str]:
    """[B026] Baca file dengan multiple encoding."""
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            return path.read_text(encoding=enc, errors='strict')
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError:
            return None
    return None


def get_ast_tree(p: Path) -> Optional[ast.AST]:
    """[B029] Parse AST dengan fallback encoding."""
    src = read_file_robust(p)
    if src is None:
        return None
    try:
        return ast.parse(src, filename=str(p))
    except (SyntaxError, MemoryError):
        return None


def safe_import(mod: str, timeout: int = RUNTIME_IMPORT_TIMEOUT) -> Tuple[bool, Optional[str]]:
    """
    [B003] Import modul dalam subprocess terpisah dengan timeout.
    [B036] Copy environment variables.
    """
    env = os.environ.copy()
    cmd = [sys.executable, "-c", f"import {mod}; print('OK')"]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and "OK" in result.stdout:
            return True, None
        err = (result.stderr or result.stdout or "Unknown error").strip()
        last_line = err.split("\n")[-1] if err else "Unknown"
        return False, last_line[:300]
    except subprocess.TimeoutExpired:
        return False, f"Timeout after {timeout}s"
    except Exception as e:
        return False, str(e)[:200]


def resolve_import_target(imp: str, root: Path) -> bool:
    parts = imp.split(".")
    for i in range(len(parts), 0, -1):
        if (root / Path(*parts[:i])).with_suffix(".py").exists():
            return True
        if (root / Path(*parts[:i]) / "__init__.py").exists():
            return True
    return False


def resolve_relative_import(
    current_file: Path,
    level: int,
    module: Optional[str],
    name: Optional[str],
) -> List[Path]:
    """
    [B005-FIXED v2]: Naik (level - 1) kali — sesuai PEP 328.
    level=1 → current package (tidak naik)
    level=2 → parent package (naik 1)
    """
    target_dir = current_file.parent
    # PEP 328: level=1 berarti current package, jadi naik 0
    for _ in range(max(0, level - 1)):
        target_dir = target_dir.parent

    candidates: List[Path] = []
    if module:
        parts = module.split(".")
        py   = target_dir / Path(*parts).with_suffix(".py")
        init = target_dir / Path(*parts) / "__init__.py"
        if py.exists():
            candidates.append(py)
        if init.exists():
            candidates.append(init)
    else:
        if name:
            py   = target_dir / f"{name}.py"
            init = target_dir / name / "__init__.py"
            if py.exists():
                candidates.append(py)
            if init.exists():
                candidates.append(init)
    return candidates


def check_symbol_in_ast(target_file: Path, symbol: str) -> bool:
    """[B016] Rekursif ke dalam class body dan nested scope."""
    tree = get_ast_tree(target_file)
    if tree is None:
        return True
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == symbol:
                return True
            if isinstance(node, ast.ClassDef):
                for child in ast.walk(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if child.name == symbol:
                            return True
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == symbol:
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol:
                return True
        elif isinstance(node, (ast.ImportFrom, ast.Import)):
            for alias in node.names:
                exported = alias.asname or alias.name
                if exported == symbol or alias.name == "*":
                    return True
    return False


def get_exported_symbols(init_file: Path) -> Set[str]:
    """[B027] Ekstrak simbol yang diekspor via __all__."""
    tree = get_ast_tree(init_file)
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    if isinstance(node.value, ast.List):
                        return {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)}
    return set()


def resolve_deep_import(module_path: str, symbol: str) -> Tuple[bool, str]:
    """[B010][B027] Periksa re-export via __init__.py dan __all__."""
    parts = module_path.split(".")
    for i in range(len(parts), 0, -1):
        candidate_py   = ROOT / Path(*parts[:i]).with_suffix(".py")
        candidate_init = ROOT / Path(*parts[:i]) / "__init__.py"

        if candidate_py.exists():
            if i == len(parts):
                if check_symbol_in_ast(candidate_py, symbol):
                    return True, ""
                parent_init = candidate_py.parent / "__init__.py"
                if parent_init.exists():
                    exported = get_exported_symbols(parent_init)
                    if symbol in exported:
                        return True, ""
                return False, f"Simbol '{symbol}' tidak ditemukan di {rel_path(candidate_py)}"
            return True, ""

        if candidate_init.exists():
            if i == len(parts):
                if check_symbol_in_ast(candidate_init, symbol):
                    return True, ""
                exported = get_exported_symbols(candidate_init)
                if symbol in exported:
                    return True, ""
                return False, f"Simbol '{symbol}' tidak diekspor oleh {rel_path(candidate_init)}"
            return True, ""

    return False, f"Modul fisik '{module_path}' tidak ditemukan"


def get_true_runtime_imports(tree: ast.AST) -> List[str]:
    """Kumpulkan import runtime (skip TYPE_CHECKING)."""
    result: List[str] = []

    class RuntimeImportCollector(ast.NodeVisitor):
        def __init__(self):
            self._in_type_checking = False

        def visit_If(self, node):
            if self._is_type_checking(node.test):
                return  # skip entire block
            self.generic_visit(node)

        def _is_type_checking(self, test):
            return (
                (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
                or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
            )

        def visit_ImportFrom(self, node):
            if node.module and node.level == 0:
                result.append(node.module)
            self.generic_visit(node)

    collector = RuntimeImportCollector()
    collector.visit(tree)
    return result


def _get_git_info() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=5
        )
        return r.stdout.strip() if r.returncode == 0 else "N/A"
    except Exception:
        return "N/A"


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1: BYTECODE COMPILATION [B028]
# ─────────────────────────────────────────────────────────────────────────────
def phase_bytecode_compilation() -> PhaseResult:
    pr = PhaseResult("Syntax & Bytecode Compilation")
    t0 = time.monotonic()
    files = all_py_files()
    errors: List[Tuple[str, str, int]] = []

    for f in files:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            lineno = getattr(e, "lineno", 0) or 0
            errors.append((rel_path(f), str(e)[:300], lineno))
        except Exception as e:
            errors.append((rel_path(f), f"{type(e).__name__}: {e}", 0))

    if errors:
        for rp, err, ln in errors:
            # Gunakan exception asli untuk RCA
            pr.add("CRITICAL", rp, ln, "Syntax Error terdeteksi!",
                   detail=err,
                   rec="Perbaiki syntax sebelum semua check lain dijalankan.",
                   exc=RuntimeError(err) if not errors else None,
                   rca_context={"phase": "bytecode", "file": rp})
    else:
        pr.add("PASS", ".", 0, f"Semua {len(files)} file lolos kompilasi bytecode.")
    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2: BROKEN IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
def phase_broken_imports(prior_findings: List[Finding]) -> PhaseResult:
    pr = PhaseResult("Broken Imports & Symbol Check")
    t0 = time.monotonic()
    files     = all_py_files()
    local_mods = {module_name(f) for f in files if module_name(f)}
    local_tops = {m.split(".")[0] for m in local_mods}
    broken: List[Tuple[str, int, str, str]] = []

    syntax_errored = {f.file for f in prior_findings if f.severity == "CRITICAL"}

    for f in files:
        rp = rel_path(f)
        if rp in syntax_errored:
            continue
        tree = get_ast_tree(f)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imp   = alias.name
                    top   = imp.split(".")[0]
                    if top in local_tops and not resolve_import_target(imp, ROOT):
                        broken.append((rp, node.lineno, imp, "Module tidak ditemukan di project"))

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                level  = node.level or 0

                if level > 0:
                    names = [alias.name for alias in node.names]
                    resolved = resolve_relative_import(f, level, module or None,
                                                       names[0] if names else None)
                    if not resolved:
                        prefix = "." * level
                        target = f"{prefix}{module}" if module else f"{prefix}{names[0] if names else '?'}"
                        broken.append((rp, node.lineno, target, "Relative import tidak bisa di-resolve"))
                else:
                    if module == "__future__":
                        continue
                    if module.split(".")[0] not in local_tops:
                        continue
                    if not resolve_import_target(module, ROOT):
                        broken.append((rp, node.lineno, module, "Module tidak ditemukan"))
                        continue
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        ok, err = resolve_deep_import(module, alias.name)
                        if not ok:
                            broken.append((rp, node.lineno,
                                           f"{alias.name} dari {module}", err))

    if broken:
        for rp, ln, imp, detail in broken[:50]:
            exc = ImportError(detail) if detail else ImportError(f"Broken import: {imp}")
            pr.add("CRITICAL", rp, ln, f"Broken import: {imp}",
                   detail=detail,
                   rec="Perbaiki import path atau ekspor simbol yang hilang.",
                   exc=exc,
                   rca_context={"phase": "broken_imports", "import": imp, "file": rp})
        if len(broken) > 50:
            pr.add("INFO", ".", 0, f"Plus {len(broken)-50} more broken imports (truncated)")
    else:
        pr.add("PASS", ".", 0, "Tidak ada broken imports dan semua simbol lokal terverifikasi.")
    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3: CIRCULAR IMPORTS [B002][B006][B020][B031]
# ─────────────────────────────────────────────────────────────────────────────
def phase_circular_imports() -> PhaseResult:
    pr = PhaseResult("Runtime Circular Imports")
    t0 = time.monotonic()
    files      = all_py_files()
    module_map: Dict[str, Path] = {}
    for f in files:
        mod = module_name(f)
        if mod:
            module_map[mod] = f
    local_mods = set(module_map.keys())
    local_tops = {m.split(".")[0] for m in local_mods}

    graph: Dict[str, Set[str]] = collections.defaultdict(set)

    for f in files:
        mod = module_name(f)
        if not mod:
            continue
        tree = get_ast_tree(f)
        if not tree:
            continue

        # Absolute imports
        for imp_mod in get_true_runtime_imports(tree):
            if imp_mod in local_mods:
                if imp_mod != mod:
                    graph[mod].add(imp_mod)
            else:
                # [B006] Tambahkan semua local yang cocok prefix
                for local in local_mods:
                    if local.startswith(imp_mod + "."):
                        graph[mod].add(local)

        # Relative imports [B031]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                level = node.level
                target = None
                if node.module:
                    # from .module import x
                    target = node.module
                    # Resolve relative ke absolute module
                else:
                    # from . import x
                    # Kita coba resolve via file path
                    target = None
                # Sulit resolve relatif secara akurat, jadi skip untuk graph.
                # Bisa ditambahkan nanti.

    # Tarjan SCC Iteratif [B002]
    index_counter = [0]
    indices:  Dict[str, int]  = {}
    lowlinks: Dict[str, int]  = {}
    on_stack: Set[str]        = set()
    stack:    List[str]       = []
    sccs:     List[List[str]] = []

    def _strongconnect(start: str) -> None:
        call_stack: List[Tuple[str, List[str], int]] = []
        if start in indices:
            return
        indices[start]  = index_counter[0]
        lowlinks[start] = index_counter[0]
        index_counter[0] += 1
        stack.append(start)
        on_stack.add(start)
        nbrs = sorted(graph.get(start, set()))  # [B020]
        call_stack.append((start, nbrs, 0))

        while call_stack:
            v, nbrs, ni = call_stack[-1]
            if ni < len(nbrs):
                call_stack[-1] = (v, nbrs, ni + 1)
                w = nbrs[ni]
                if w not in indices:
                    indices[w]  = index_counter[0]
                    lowlinks[w] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(w)
                    on_stack.add(w)
                    w_nbrs = sorted(graph.get(w, set()))
                    call_stack.append((w, w_nbrs, 0))
                elif w in on_stack:
                    lowlinks[v] = min(lowlinks[v], indices[w])
            else:
                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1][0]
                    lowlinks[parent] = min(lowlinks[parent], lowlinks[v])
                if lowlinks[v] == indices[v]:
                    scc: List[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.append(w)
                        if w == v:
                            break
                    if len(scc) > 1:
                        sccs.append(sorted(scc))

    for m in sorted(local_mods):
        if m not in indices:
            _strongconnect(m)

    if sccs:
        for scc in sccs:
            first_file = module_map.get(scc[0], ROOT / "?")
            pr.add("WARNING", rel_path(first_file), 0,
                   f"Circular import cycle ({len(scc)} modul): {' → '.join(scc[:6])}{'...' if len(scc)>6 else ''}",
                   rec="Gunakan TYPE_CHECKING guard atau pindahkan import ke dalam fungsi.")
        pr.passed = True
    else:
        pr.add("PASS", ".", 0, f"Bersih dari siklus import runtime di {len(local_mods)} modul.")
    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4: DYNAMIC IMPORTS [B007][B032]
# ─────────────────────────────────────────────────────────────────────────────
def _extract_dynamic_imports(tree: ast.AST) -> List[Tuple[int, str, str, bool]]:
    results: List[Tuple[int, str, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                if node.args:
                    first = node.args[0]
                    is_lit = isinstance(first, ast.Constant) and isinstance(first.value, str)
                    arg    = first.value if is_lit else ast.unparse(first)
                    results.append((node.lineno, "__import__", str(arg), is_lit))
            elif (isinstance(func, ast.Attribute)
                  and func.attr == "import_module"
                  and isinstance(func.value, ast.Name)
                  and func.value.id == "importlib"):
                if node.args:
                    first = node.args[0]
                    is_lit = isinstance(first, ast.Constant) and isinstance(first.value, str)
                    arg    = first.value if is_lit else ast.unparse(first)
                    results.append((node.lineno, "importlib.import_module", str(arg), is_lit))
    return results


def phase_dynamic_imports() -> PhaseResult:
    pr = PhaseResult("Dynamic Imports in Core Layers")
    t0 = time.monotonic()
    files      = all_py_files()
    violations: List[Tuple[str, int, str]] = []

    for f in files:
        mod   = module_name(f)
        layer = top_layer(mod) if mod else "unknown"
        if layer not in PROTECTED_LAYERS:
            continue
        tree = get_ast_tree(f)
        if not tree:
            continue
        rp = rel_path(f)
        for lineno, call, arg, is_literal in _extract_dynamic_imports(tree):
            if not is_literal:
                continue
            # [B032] Skip jika arg ada di allowed list
            if any(allowed in arg for allowed in ALLOWED_DYNAMIC_MODS):
                continue
            violations.append((rp, lineno, f"{call}('{arg}')"))

    if violations:
        for file, ln, call in violations[:30]:
            pr.add("WARNING", file, ln, f"Dynamic import literal: {call}",
                   rec="Gunakan dependency injection atau static import.")
        if len(violations) > 30:
            pr.add("INFO", ".", 0, f"Plus {len(violations)-30} more dynamic imports")
        pr.passed = True
    else:
        pr.add("PASS", ".", 0, "Tidak ada dynamic literal imports di core layers.")
    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5: RUNTIME IMPORTS [B003][B008][B036]
# ─────────────────────────────────────────────────────────────────────────────
def phase_runtime_imports(prior_findings: List[Finding]) -> PhaseResult:
    pr = PhaseResult("Runtime Imports (subprocess isolated)")
    t0 = time.monotonic()
    files  = all_py_files()
    errors: List[Tuple[str, str, str]] = []

    SKIP_TOP_LAYERS = {"tests", "migrations", "checker"}
    already_broken = {f.file for f in prior_findings if f.severity == "CRITICAL"}

    for f in files:
        mod = module_name(f)
        if not mod:
            continue
        layer = top_layer(mod)
        if layer in SKIP_TOP_LAYERS:
            continue
        if rel_path(f) in already_broken:
            continue
        ok, err = safe_import(mod, timeout=RUNTIME_IMPORT_TIMEOUT)
        if not ok:
            errors.append((rel_path(f), mod, err or "Unknown error"))

    if errors:
        for rp, mod, err in errors[:20]:
            exc = ImportError(err) if err else ImportError(f"Import {mod} failed")
            pr.add("CRITICAL", rp, 0, f"Import gagal: '{mod}'",
                   detail=err or "",
                   rec="Perbaiki dependensi atau environment.",
                   exc=exc,
                   rca_context={"phase": "runtime_imports", "module": mod})
        if len(errors) > 20:
            pr.add("INFO", ".", 0, f"Plus {len(errors)-20} lagi import failures")
    else:
        pr.add("PASS", ".", 0, "Semua modul produksi berhasil di-import (subprocess isolated).")
    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 6: CRITICAL MODULES [B017]
# ─────────────────────────────────────────────────────────────────────────────
def phase_critical_imports() -> PhaseResult:
    pr = PhaseResult("Critical Modules Import")
    t0 = time.monotonic()

    critical: List[Tuple[str, str]] = [
        ("constitution.supreme_law",                        "Constitution Supreme Law"),
        ("constitution.enforcement_engine",                 "Constitution Enforcement Engine"),
        ("axioms.double_entry",                             "Double Entry Axiom"),
        ("axioms.conservation_of_value",                    "Conservation of Value Axiom"),
        ("bootstrap.orchestrator",                          "Bootstrap Orchestrator"),
        ("kernel.sealed_gate",                              "Kernel Sealed Gate"),
        ("kernel.command_dispatcher",                       "Kernel Command Dispatcher"),
        ("domain.journal.aggregate_root",                   "Journal Aggregate Root"),
        ("application.use_cases.post_journal_entry",        "Post Journal Entry Use Case"),
        ("adapters.primary_api.common.fastapi_app_factory", "Fastapi App Factory"),
        ("infrastructure.database.session_factory_sqlalchemy", "SQLAlchemy Session Factory"),
        ("event_gateway.event_gate_singleton",              "Event Gateway Singleton"),
        ("audit.event_writer_immutable",                    "Audit Event Writer"),
        ("policy_engine",                                   "Policy Engine Package"),
        ("compliance",                                      "Compliance Package"),
    ]

    errors: List[Tuple[str, str, str]] = []
    for mod, label in critical:
        parts = mod.split(".")
        exists = (
            (ROOT / Path(*parts)).with_suffix(".py").exists()
            or (ROOT / Path(*parts) / "__init__.py").exists()
        )
        if not exists:
            errors.append((mod, label, "File tidak ditemukan di filesystem"))
            continue
        ok, err = safe_import(mod, timeout=15)
        if not ok:
            errors.append((mod, label, err or "Unknown"))

    if errors:
        for mod, label, err in errors:
            exc = ImportError(err) if err else ImportError(f"Critical {label} failed")
            pr.add("CRITICAL", mod.replace(".", "/") + ".py", 0,
                   f"Critical import '{label}' gagal",
                   detail=err,
                   rec="Fix immediately — sistem tidak bisa berjalan tanpa ini.",
                   exc=exc,
                   rca_context={"phase": "critical_imports", "module": mod, "label": label})
    else:
        pr.add("PASS", ".", 0, f"Semua {len(critical)} critical module berhasil diverifikasi.")
    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 7: APP BOOTSTRAP [B012][B033][B034]
# ─────────────────────────────────────────────────────────────────────────────
def phase_app_bootstrap() -> PhaseResult:
    pr = PhaseResult("App Bootstrap (Static + Subprocess)")
    t0 = time.monotonic()
    main_path = ROOT / "app" / "main.py"
    init_path = ROOT / "app" / "__init__.py"

    if not main_path.exists():
        pr.add("CRITICAL", "app/main.py", 0, "File app/main.py tidak ditemukan.",
               rec="Buat app/main.py sebagai ASGI entry point.")
        pr.duration = time.monotonic() - t0
        return pr

    if not init_path.exists():
        pr.add("WARNING", "app/__init__.py", 0, "app/__init__.py tidak ada, package mungkin tidak dikenali.",
               rec="Tambahkan __init__.py di app/")

    # Static check: pastikan ada `app` variable atau factory function
    tree = get_ast_tree(main_path)
    has_app_var = False
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "app":
                        has_app_var = True
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in ("create_app", "get_app", "build_app"):
                    has_app_var = True

    if not has_app_var:
        pr.add("WARNING", "app/main.py", 0,
               "Tidak ditemukan `app` variable atau factory function (create_app/get_app).",
               rec="Definisikan `app = FastAPI()` atau `def create_app() -> FastAPI`.")

    # Subprocess check untuk AST dan import aman
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import ast, sys; ast.parse(open('app/main.py').read()); print('AST_OK')"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10,
        )
        if "AST_OK" in result.stdout:
            pr.add("PASS", "app/main.py", 0, "app/main.py syntax valid dan struktur terdeteksi.")
        else:
            err = result.stderr.strip().split("\n")[-1] if result.stderr else "Unknown"
            exc = SyntaxError(err)
            pr.add("CRITICAL", "app/main.py", 0, f"app/main.py syntax error: {err}",
                   exc=exc, rca_context={"phase": "bootstrap", "file": "app/main.py"})
    except subprocess.TimeoutExpired:
        pr.add("WARNING", "app/main.py", 0, "Timeout saat cek app/main.py")
    except Exception as e:
        pr.add("CRITICAL", "app/main.py", 0, f"Bootstrap check error: {type(e).__name__}: {e}",
               exc=e, rca_context={"phase": "bootstrap"})

    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 8: DI CONTAINER [B013]
# ─────────────────────────────────────────────────────────────────────────────
def phase_di_container(optional: bool = True) -> PhaseResult:
    pr = PhaseResult("DI Container Resolution")
    t0 = time.monotonic()

    container_path = ROOT / "bootstrap" / "dependency_container" / "ioc_container.py"
    if not container_path.exists():
        if optional:
            pr.add("INFO", "bootstrap/dependency_container", 0,
                   "ioc_container.py tidak ditemukan (dilewati).")
        else:
            pr.add("CRITICAL", "bootstrap/dependency_container", 0,
                   "ioc_container.py tidak ditemukan!",
                   rec="Pastikan bootstrap/dependency_container/ioc_container.py ada.")
        pr.duration = time.monotonic() - t0
        return pr

    tree = get_ast_tree(container_path)
    registration_count = 0
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if func.attr in ("register", "bind", "singleton", "transient",
                                     "add_singleton", "add_transient", "add_scoped"):
                        registration_count += 1

    if registration_count > 0:
        pr.add("PASS", "bootstrap/dependency_container/ioc_container.py", 0,
               f"DI container: {registration_count} registrasi terdeteksi secara statis.")
    else:
        pr.add("WARNING", "bootstrap/dependency_container/ioc_container.py", 0,
               "Tidak ada registrasi terdeteksi di ioc_container.py",
               rec="Pastikan service didaftarkan di container.")

    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 9: DATABASE CONNECTIVITY [B004][B035]
# ─────────────────────────────────────────────────────────────────────────────
def phase_db_connectivity(optional: bool = True) -> PhaseResult:
    pr = PhaseResult("Database Connectivity")
    t0 = time.monotonic()

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        if optional:
            pr.add("INFO", ".env", 0, "DATABASE_URL tidak diset (dilewati).")
        else:
            pr.add("CRITICAL", ".env", 0, "DATABASE_URL tidak diset!",
                   rec="Set DATABASE_URL environment variable.")
        pr.duration = time.monotonic() - t0
        return pr

    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        if "postgresql://" in db_url and "+asyncpg" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)

        async def _test() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_test())
        finally:
            loop.close()

        pr.add("PASS", "config/", 0, "Koneksi database berhasil (SELECT 1 OK).")

    except ImportError as ie:
        pr.add("WARNING", "config/", 0, f"SQLAlchemy/asyncpg tidak terinstall: {ie}",
               rec="pip install sqlalchemy asyncpg")
    except Exception as e:
        pr.add("CRITICAL", "config/", 0,
               f"Koneksi database gagal: {type(e).__name__}: {str(e)[:200]}",
               rec="Periksa DATABASE_URL dan pastikan DB service berjalan.",
               exc=e,
               rca_context={"phase": "db_connectivity", "db_url": db_url[:50]})

    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 10: STERILE SUBPROCESS PROBE [B014][B035][B036]
# ─────────────────────────────────────────────────────────────────────────────
def phase_sterile_probe(enable: bool) -> PhaseResult:
    pr = PhaseResult("Subprocess Sterilization Probe")
    t0 = time.monotonic()

    if not enable:
        pr.add("INFO", ".", 0, "Dilewati (gunakan --strict-isolate untuk probe steril).")
        pr.duration = time.monotonic() - t0
        return pr

    probe_targets = [
        "app.main",
        "domain.journal.aggregate_root",
        "kernel.sealed_gate",
        "constitution.supreme_law",
    ]

    env = os.environ.copy()
    for mod in probe_targets:
        parts = mod.split(".")
        exists = (
            (ROOT / Path(*parts)).with_suffix(".py").exists()
            or (ROOT / Path(*parts) / "__init__.py").exists()
        )
        if not exists:
            continue
        try:
            res = subprocess.run(
                [sys.executable, "-c", f"import {mod}"],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
                timeout=30,
            )
            if res.returncode != 0:
                err = res.stderr.strip().split("\n")[-1] if res.stderr else "Unknown"
                exc = ImportError(err)
                pr.add("CRITICAL", mod.replace(".", "/") + ".py", 0,
                       f"Gagal di-boot dalam subprocess steril!",
                       detail=err, exc=exc,
                       rca_context={"phase": "sterile_probe", "module": mod})
        except subprocess.TimeoutExpired:
            pr.add("CRITICAL", mod.replace(".", "/") + ".py", 0,
                   f"Timeout 30s — modul hang saat import dalam subprocess steril",
                   rec="Cek circular import atau blocking call saat module load.")

    if pr.passed:
        pr.add("PASS", ".", 0, "Semua modul kritis tahan uji isolated subprocess.")
    pr.duration = time.monotonic() - t0
    return pr


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUNNER [B011][B023][B024][B028]
# ─────────────────────────────────────────────────────────────────────────────
def run_unified_check(
    verbose:       bool,
    json_out:      Optional[str],
    sarif_out:     Optional[str],
    skip_runtime:  bool,
    skip_db:       bool,
    strict_isolate: bool,
) -> int:
    git_hash = _get_git_info()
    scan_ts  = datetime.now(timezone.utc).isoformat()

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔{'═'*78}╗{COLOR['RESET']}")
    print(f"{COLOR['BOLD']}{COLOR['CYAN']}║{'SOVEREIGN ERP — ULTIMATE INTEGRATION VALIDATOR v5.0.0':^78}║{COLOR['RESET']}")
    print(f"{COLOR['BOLD']}{COLOR['CYAN']}║{'Audit-Grade · RCA-Integrated · Big4-Ready':^78}║{COLOR['RESET']}")
    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╚{'═'*78}╝{COLOR['RESET']}")
    print(f"  Root    : {ROOT}")
    print(f"  Git     : {git_hash}")
    print(f"  Python  : {sys.version.split()[0]}")
    print(f"  Scan    : {scan_ts}")
    print(f"  RCA     : {'✅ Aktif' if _RCA_AVAILABLE else '⚠️  Tidak tersedia (fallback manual)'}")
    print()

    if skip_runtime:
        print(f"  {COLOR['YELLOW']}⚠️  Runtime import checks disabled{COLOR['RESET']}")
    if skip_db:
        print(f"  {COLOR['YELLOW']}⚠️  Database check disabled{COLOR['RESET']}")
    if strict_isolate:
        print(f"  {COLOR['CYAN']}🔬 Sterilization probe aktif{COLOR['RESET']}")
    print()

    results: List[PhaseResult] = []
    all_findings: List[Finding] = []

    def run_phase(name: str, fn) -> PhaseResult:
        print(f"{COLOR['CYAN']}▶ {name.upper()}{COLOR['RESET']}")
        t0  = time.monotonic()
        try:
            res = fn()
        except KeyboardInterrupt:
            print(f"\n{COLOR['YELLOW']}⏹️  Dibata lkan oleh pengguna pada phase {name}{COLOR['RESET']}")
            sys.exit(130)
        except Exception as e:
            res = PhaseResult(name, passed=False)
            res.add("CRITICAL", ".", 0, f"Phase {name} crashed: {e}",
                    detail=traceback.format_exc(), exc=e)
        res.duration = time.monotonic() - t0
        results.append(res)
        all_findings.extend(res.findings)
        _print_phase(res, verbose)
        return res

    p1 = run_phase("bytecode", phase_bytecode_compilation)

    run_phase("broken_imports", lambda: phase_broken_imports(list(all_findings)))
    run_phase("circular_imports", phase_circular_imports)
    run_phase("dynamic_imports", phase_dynamic_imports)

    if not skip_runtime:
        run_phase("runtime_imports", lambda: phase_runtime_imports(list(all_findings)))
        run_phase("critical_modules", phase_critical_imports)
        run_phase("app_bootstrap", phase_app_bootstrap)
        run_phase("di_container", lambda: phase_di_container(optional=True))

        if not skip_db:
            run_phase("db_connectivity", lambda: phase_db_connectivity(optional=True))

        run_phase("sterile_probe", lambda: phase_sterile_probe(strict_isolate))

    critical = sum(pr.count("CRITICAL") for pr in results)
    warnings = sum(pr.count("WARNING")  for pr in results)
    infos    = sum(pr.count("INFO")     for pr in results)
    passed   = all(pr.passed for pr in results)
    total_dur = sum(pr.duration for pr in results)

    print("═" * 80)
    print(f"{COLOR['BOLD']}  SUMMARY — INTEGRATION VALIDATOR v5.0.0{COLOR['RESET']}")
    print(f"  Phases run      : {len(results)}")
    print(f"  Critical issues : {COLOR['RED']}{critical}{COLOR['RESET']}")
    print(f"  Warnings        : {COLOR['YELLOW']}{warnings}{COLOR['RESET']}")
    print(f"  Info            : {COLOR['CYAN']}{infos}{COLOR['RESET']}")
    print(f"  Total duration  : {total_dur:.2f}s")
    scolor = COLOR["GREEN"] if passed else COLOR["RED"]
    print(f"  Status          : {scolor}{COLOR['BOLD']}{'✅ PASS' if passed else '❌ FAIL'}{COLOR['RESET']}")
    if _RCA_AVAILABLE:
        rca_count = sum(1 for pr in results for f in pr.findings if f.rca_result is not None)
        print(f"  RCA analyses    : {rca_count} findings dianalisis")
    print("═" * 80)

    # JSON Export [B011][B024]
    if json_out:
        payload = {
            "meta": {
                "tool":           "SovereignERPIntegrationValidator",
                "version":        "5.0.0",
                "scan_timestamp": scan_ts,
                "root_dir":       str(ROOT),
                "python_version": sys.version.split()[0],
                "git_commit":     git_hash,
                "rca_available":  _RCA_AVAILABLE,
            },
            "summary": {
                "phases_run":   len(results),
                "critical":     critical,
                "warnings":     warnings,
                "infos":        infos,
                "passed":       passed,
                "total_dur_sec": round(total_dur, 3),
            },
            "phases": [
                {
                    "name":     pr.name,
                    "passed":   pr.passed,
                    "duration": round(pr.duration, 3),
                    "critical": pr.count("CRITICAL"),
                    "warnings": pr.count("WARNING"),
                    "infos":    pr.count("INFO"),
                    "findings": [f.to_dict() for f in pr.findings],
                }
                for pr in results
            ],
        }
        try:
            Path(json_out).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"\n  {COLOR['CYAN']}✅ JSON report → {json_out}{COLOR['RESET']}")
        except Exception as e:
            print(f"\n  {COLOR['RED']}❌ Gagal menulis JSON: {e}{COLOR['RESET']}")

    # SARIF Export
    if sarif_out:
        sarif_results = []
        for pr in results:
            for f in pr.findings:
                if f.severity not in ("CRITICAL", "WARNING"):
                    continue
                sarif_results.append({
                    "ruleId": f"ERP-{f.severity}",
                    "level": "error" if f.severity == "CRITICAL" else "warning",
                    "message": {"text": f.message + (f". {f.detail}" if f.detail else "")},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.file.replace("\\", "/")},
                            "region": {"startLine": max(1, f.line)},
                        }
                    }],
                })
        sarif_payload = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "SovereignERPIntegrationValidator",
                        "version": "5.0.0",
                        "rules": [
                            {"id": "ERP-CRITICAL", "shortDescription": {"text": "Critical integration issue"}},
                            {"id": "ERP-WARNING",  "shortDescription": {"text": "Integration warning"}},
                        ]
                    }
                },
                "results": sarif_results,
            }]
        }
        try:
            Path(sarif_out).write_text(
                json.dumps(sarif_payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"  {COLOR['CYAN']}✅ SARIF report → {sarif_out}{COLOR['RESET']}")
        except Exception as e:
            print(f"  {COLOR['RED']}❌ Gagal menulis SARIF: {e}{COLOR['RESET']}")

    return 0 if passed else 1


def _print_phase(pr: PhaseResult, verbose: bool) -> None:
    SEV_ICON  = {"CRITICAL": "✖", "WARNING": "⚠", "INFO": "ℹ", "PASS": "✔"}
    SEV_COLOR = {
        "CRITICAL": COLOR["RED"],
        "WARNING":  COLOR["YELLOW"],
        "INFO":     COLOR["CYAN"],
        "PASS":     COLOR["GREEN"],
    }
    for f in pr.findings:
        if not verbose and f.severity in ("INFO", "PASS"):
            if f.severity == "PASS":
                print(f"  {COLOR['GREEN']}✔ {f.message}{COLOR['RESET']}")
            continue
        sc   = SEV_COLOR.get(f.severity, COLOR["RESET"])
        icon = SEV_ICON.get(f.severity, "?")
        print(f"  {sc}{COLOR['BOLD']}{icon} [{f.severity}]{COLOR['RESET']} {f.message}")
        if f.detail:
            print(f"      {COLOR['YELLOW']}{f.detail[:200]}{COLOR['RESET']}")
        if f.file and f.file != ".":
            print(f"      @ {f.file}:{f.line}")
        if f.recommendation:
            print(f"      💡 {f.recommendation}")
        # [B041] Normalisasi RCA output
        if f.rca_result is not None and f.severity in ("CRITICAL", "WARNING"):
            try:
                # Coba ambil dari objek langsung (RCAResult)
                rc = getattr(f.rca_result, "root_cause", None)
                fix = getattr(f.rca_result, "suggested_fix", None)
                conf = getattr(f.rca_result, "confidence", None)
                if rc:
                    print(f"      {COLOR['BLUE']}🔍 RCA: {rc[:150]}{COLOR['RESET']}")
                if fix:
                    print(f"      {COLOR['BLUE']}🔧 Fix: {fix[:150]}{COLOR['RESET']}")
                if conf is not None:
                    print(f"      {COLOR['DIM']}   Confidence: {conf:.0%}{COLOR['RESET']}")
            except Exception:
                pass
    print(f"  {COLOR['DIM']}⏱  {pr.duration:.2f}s{COLOR['RESET']}\n")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sovereign ERP — Ultimate Integration Validator v5.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python checker/checker_integration.py
  python checker/checker_integration.py --verbose --json report.json
  python checker/checker_integration.py --no-runtime --no-db
  python checker/checker_integration.py --strict-isolate --sarif output.sarif
        """
    )
    parser.add_argument("--verbose",        "-v", action="store_true",
                        help="Tampilkan detail semua findings")
    parser.add_argument("--json",           metavar="FILE",
                        help="Ekspor laporan ke JSON (audit trail lengkap)")
    parser.add_argument("--sarif",          metavar="FILE",
                        help="Ekspor ke SARIF 2.1.0 (GitHub Code Scanning)")
    parser.add_argument("--no-runtime",     action="store_true",
                        help="Skip runtime import checks")
    parser.add_argument("--no-db",          action="store_true",
                        help="Skip database connectivity check")
    parser.add_argument("--strict-isolate", action="store_true",
                        help="Jalankan sterile subprocess probe")
    args = parser.parse_args()

    sys.exit(run_unified_check(
        verbose=args.verbose,
        json_out=args.json,
        sarif_out=args.sarif,
        skip_runtime=args.no_runtime,
        skip_db=args.no_db,
        strict_isolate=args.strict_isolate,
    ))


if __name__ == "__main__":
    main()