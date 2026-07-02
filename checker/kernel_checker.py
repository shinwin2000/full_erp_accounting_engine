#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/kernel_checker.py — Kernel Layer Compliance Checker v10.2
================================================================
Contract‑Based Static Analysis with:
- Abstract method extraction from base classes (MRO within file)
- Configurable base class contracts via YAML (base_class_contracts)
- No inference, no folder fallback — only explicit contracts
- Multi‑metric scoring: Critical, Optional, Singleton, Overall
- Full RCA integration
- Excludes guards/ and immutable_laws/ (handled by separate checkers)

Usage:
    python -m checker.kernel_checker --verbose
    python -m checker.kernel_checker --config kernel_contracts.yaml --verbose
    python -m checker.kernel_checker --discover
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# ---- Project root ----
_THIS_FILE = Path(__file__).resolve()
ROOT = _THIS_FILE.parent.parent if _THIS_FILE.parent.name == "checker" else _THIS_FILE.parent
sys.path.insert(0, str(ROOT))

# ---- RCA Engine ----
try:
    from checker.core.rca import (
        RCAEngine, RCAResult, Severity, Category, ErrorCode,
        get_engine, analyze_exception
    )
    RCA_AVAILABLE = True
except ImportError:
    RCA_AVAILABLE = False
    analyze_exception = None

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---- Color support ----
def _supports_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
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
COLOR = {
    "RED": "\033[91m" if _USE_COLOR else "",
    "GREEN": "\033[92m" if _USE_COLOR else "",
    "YELLOW": "\033[93m" if _USE_COLOR else "",
    "CYAN": "\033[96m" if _USE_COLOR else "",
    "BOLD": "\033[1m" if _USE_COLOR else "",
    "RESET": "\033[0m" if _USE_COLOR else "",
}

# =============================================================================
# CONFIGURATION (defaults)
# =============================================================================
DEFAULT_CONFIG = {
    "excluded_dirs": ["checker", "tests", "migrations", "__pycache__", ".git", "docs", "scripts", "deployment", "monitoring", "reports"],
    "blacklist_filenames": ["__init__.py", "exceptions.py", "base.py", "kernel_exceptions.py"],
    "ignore_filename_patterns": ["_exceptions.py", "base_", "abstract_"],
    "excluded_subdirs": ["guards", "immutable_laws"],
    "singleton_required": False,
    "timeout_seconds": 30,
    "max_workers": 4,
    # base_class_contracts akan diisi dari YAML (jika diberikan)
    "base_class_contracts": {},
}

# =============================================================================
# DATA STRUCTURES
# =============================================================================
@dataclass
class MethodInfo:
    name: str
    is_async: bool = False
    is_classmethod: bool = False
    is_staticmethod: bool = False
    is_abstract: bool = False
    decorators: List[str] = field(default_factory=list)

@dataclass
class ClassInfo:
    name: str
    base_names: List[str]
    methods: Dict[str, MethodInfo]
    decorators: List[str]
    is_abstract: bool = False
    mro: List[str] = field(default_factory=list)

@dataclass
class FileSymbolTable:
    path: str
    classes: Dict[str, ClassInfo]
    all_methods: Set[str]
    module_name: str = ""

@dataclass
class ContractDefinition:
    base_class: str
    required: List[str] = field(default_factory=list)
    optional: List[str] = field(default_factory=list)

@dataclass
class DetectedContract:
    contract_type: str          # nama kontrak (misal "retry_policy")
    class_name: str
    file_path: str
    base_class: str
    required_methods: List[str]
    optional_methods: List[str]
    source: str                 # "abstract" or "config"

@dataclass
class ContractViolation:
    contract_type: str
    class_name: str
    missing_required: List[str]
    missing_optional: List[str]
    file_path: str

@dataclass
class KernelViolation:
    file_path: str
    module_type: str
    severity: str
    message: str
    suggestion: str
    rca_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "file": self.file_path,
            "module": self.module_type,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
        }
        if self.rca_result:
            d["rca"] = self.rca_result
        return d

@dataclass
class KernelModuleInfo:
    file_path: str
    contract_type: str
    class_name: str
    base_class: str
    required_methods: List[str]
    optional_methods: List[str]
    missing_required: List[str]
    missing_optional: List[str]
    has_singleton: bool = False
    source: str = ""
    violations: List[KernelViolation] = field(default_factory=list)

# =============================================================================
# AST ANALYZER
# =============================================================================
class ASTAnalyzer:
    @staticmethod
    def analyze(file_path: Path, content: str) -> Optional[FileSymbolTable]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return None

        classes = {}
        all_methods = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_info = ASTAnalyzer._analyze_class(node)
                classes[class_info.name] = class_info
                all_methods.update(class_info.methods.keys())

        return FileSymbolTable(
            path=str(file_path),
            classes=classes,
            all_methods=all_methods,
            module_name=file_path.stem,
        )

    @staticmethod
    def _analyze_class(node: ast.ClassDef) -> ClassInfo:
        name = node.name
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)
        decorators = []
        for dec in node.decorator_list:
            dec_name = None
            if isinstance(dec, ast.Name):
                dec_name = dec.id
            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                dec_name = dec.func.id
            elif isinstance(dec, ast.Attribute):
                dec_name = dec.attr
            if dec_name:
                decorators.append(dec_name)

        methods = {}
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_info = ASTAnalyzer._analyze_method(item)
                methods[item.name] = method_info
        is_abstract = any(m.is_abstract for m in methods.values())
        return ClassInfo(name=name, base_names=base_names, methods=methods,
                         decorators=decorators, is_abstract=is_abstract)

    @staticmethod
    def _analyze_method(node: ast.FunctionDef) -> MethodInfo:
        is_async = isinstance(node, ast.AsyncFunctionDef)
        is_classmethod = is_staticmethod = is_abstract = False
        decorators = []
        for dec in node.decorator_list:
            dec_name = None
            if isinstance(dec, ast.Name):
                dec_name = dec.id
            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                dec_name = dec.func.id
            elif isinstance(dec, ast.Attribute):
                dec_name = dec.attr
            if dec_name:
                decorators.append(dec_name)
                if dec_name == "classmethod":
                    is_classmethod = True
                elif dec_name == "staticmethod":
                    is_staticmethod = True
                elif dec_name == "abstractmethod":
                    is_abstract = True
        return MethodInfo(
            name=node.name,
            is_async=is_async,
            is_classmethod=is_classmethod,
            is_staticmethod=is_staticmethod,
            is_abstract=is_abstract,
            decorators=decorators,
        )

# =============================================================================
# SYMBOL RESOLVER (MRO) – within file
# =============================================================================
class SymbolResolver:
    @staticmethod
    def resolve_mro(symbol_table: FileSymbolTable) -> FileSymbolTable:
        classes = symbol_table.classes
        for class_name, class_info in classes.items():
            mro = SymbolResolver._compute_mro(class_name, classes)
            class_info.mro = mro
        return symbol_table

    @staticmethod
    def _compute_mro(class_name: str, classes: Dict[str, ClassInfo]) -> List[str]:
        visited = set()
        result = []
        def dfs(name):
            if name in visited:
                return
            visited.add(name)
            cls = classes.get(name)
            if cls:
                for base in cls.base_names:
                    if base in classes:
                        dfs(base)
                result.append(name)
        dfs(class_name)
        return result

    @staticmethod
    def get_all_base_classes(class_info: ClassInfo, symbol_table: FileSymbolTable) -> List[ClassInfo]:
        """Get all base classes in the inheritance chain (within file)."""
        bases = []
        for base_name in class_info.mro:
            if base_name != class_info.name:
                base_class = symbol_table.classes.get(base_name)
                if base_class:
                    bases.append(base_class)
        return bases

# =============================================================================
# CONTRACT DETECTOR (Abstract + Config)
# =============================================================================
class ContractDetector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_class_contracts = config.get("base_class_contracts", {})

    def detect(self, symbol_table: FileSymbolTable, file_path: Path) -> List[DetectedContract]:
        detected = []
        rel_path = str(file_path.relative_to(ROOT)).replace('\\', '/')

        for class_name, class_info in symbol_table.classes.items():
            # 1. Check base classes within file for abstract methods
            base_classes = SymbolResolver.get_all_base_classes(class_info, symbol_table)
            for base_class in base_classes:
                required = []
                optional = []
                for m_name, m_info in base_class.methods.items():
                    if m_info.is_abstract:
                        required.append(m_name)
                    else:
                        optional.append(m_name)
                if required:
                    # Determine contract type from base class name
                    contract_type = self._base_to_contract_type(base_class.name)
                    detected.append(DetectedContract(
                        contract_type=contract_type or class_info.name.lower(),
                        class_name=class_name,
                        file_path=rel_path,
                        base_class=base_class.name,
                        required_methods=required,
                        optional_methods=optional,
                        source="abstract",
                    ))
                    break  # use the first base class with abstract methods

            # 2. If no abstract methods found, check configurable contracts
            if not any(d.class_name == class_name for d in detected):
                for base_name in class_info.mro:
                    if base_name in self.base_class_contracts:
                        contract_def = self.base_class_contracts[base_name]
                        contract_type = self._base_to_contract_type(base_name)
                        detected.append(DetectedContract(
                            contract_type=contract_type or class_info.name.lower(),
                            class_name=class_name,
                            file_path=rel_path,
                            base_class=base_name,
                            required_methods=contract_def.get("required", []),
                            optional_methods=contract_def.get("optional", []),
                            source="config",
                        ))
                        break
        return detected

    def _base_to_contract_type(self, base_name: str) -> str:
        """Convert BaseXxx to xxx (e.g., BaseRetryPolicy -> retry_policy)."""
        for prefix in ["Base", "Abstract", "I"]:
            if base_name.startswith(prefix):
                name = base_name[len(prefix):]
                import re
                name = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
                return name
        return base_name.lower()

# =============================================================================
# CONTRACT VALIDATOR
# =============================================================================
class ContractValidator:
    def validate(self, symbol_table: FileSymbolTable, contract: DetectedContract) -> ContractViolation:
        class_info = symbol_table.classes.get(contract.class_name)
        if not class_info:
            return ContractViolation(
                contract_type=contract.contract_type,
                class_name=contract.class_name,
                missing_required=[],
                missing_optional=[],
                file_path=contract.file_path,
            )

        # Collect all methods from class and its MRO
        all_methods = set()
        for base_name in class_info.mro:
            base_class = symbol_table.classes.get(base_name)
            if base_class:
                all_methods.update(base_class.methods.keys())

        missing_required = [r for r in contract.required_methods if r not in all_methods]
        missing_optional = [o for o in contract.optional_methods if o not in all_methods]

        return ContractViolation(
            contract_type=contract.contract_type,
            class_name=contract.class_name,
            missing_required=missing_required,
            missing_optional=missing_optional,
            file_path=contract.file_path,
        )

# =============================================================================
# RCA INTEGRATION
# =============================================================================
class RCAIntegration:
    def __init__(self):
        self.enabled = RCA_AVAILABLE

    def analyze(self, msg: str, severity: str, file_path: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled or analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"KERNEL_{severity}: {msg} (file: {file_path})")
            result = analyze_exception(exc, context=context)
            if result:
                return result.to_dict()
        except Exception as e:
            logger.error(f"RCA analysis failed: {e}")
        return {
            "root_cause": msg,
            "suggested_fix": "Review implementation against contract.",
            "confidence": 0.5,
            "evidence": [f"Missing methods in {file_path}"],
        }

# =============================================================================
# MAIN CHECKER ENGINE
# =============================================================================
class KernelChecker:
    def __init__(self, root_dir: Path, config: Optional[Dict[str, Any]] = None):
        self.root_dir = root_dir
        self.config = DEFAULT_CONFIG.copy()
        if config:
            self.config.update(config)
        self.rca = RCAIntegration()
        self._results: List[KernelModuleInfo] = []

    def _should_ignore_file(self, file_path: Path) -> bool:
        name = file_path.name
        for pattern in self.config.get("ignore_filename_patterns", []):
            if pattern in name:
                return True
        return False

    def _should_exclude_file(self, file_path: Path) -> bool:
        rel = str(file_path.relative_to(self.root_dir)).replace('\\', '/')
        for subdir in self.config.get("excluded_subdirs", []):
            if f"/{subdir}/" in rel or rel.startswith(f"{subdir}/"):
                return True
        return False

    def _get_files(self) -> List[Path]:
        kernel_dir = self.root_dir / "kernel"
        files = []
        dirs_to_scan = [kernel_dir]
        for base_dir in dirs_to_scan:
            for p in base_dir.rglob("*.py"):
                if self._should_exclude_file(p):
                    continue
                if self._should_ignore_file(p):
                    continue
                rel = str(p.relative_to(self.root_dir)).replace('\\', '/')
                if any(part in self.config["excluded_dirs"] for part in p.parts):
                    continue
                if p.name.startswith(("test_", "conftest")):
                    continue
                if p.name in self.config["blacklist_filenames"]:
                    continue
                files.append(p)
        return files

    def _has_singleton(self, tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if "_instance" in node.targets[0].id or "_singleton" in node.targets[0].id:
                    return True
            if isinstance(node, ast.FunctionDef) and node.name in {"get_instance", "get_singleton", "get_default"}:
                return True
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__new__":
                        return True
        return False

    def scan_file(self, file_path: Path, discover: bool = False) -> Optional[KernelModuleInfo]:
        content = None
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                content = file_path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            logger.error(f"Cannot decode {file_path}")
            return None

        symbol_table = ASTAnalyzer.analyze(file_path, content)
        if not symbol_table or not symbol_table.classes:
            return None

        symbol_table = SymbolResolver.resolve_mro(symbol_table)

        detector = ContractDetector(self.config)
        detected_contracts = detector.detect(symbol_table, file_path)

        if not detected_contracts:
            return None

        rel_path = str(file_path.relative_to(self.root_dir)).replace('\\', '/')
        modules_info: List[KernelModuleInfo] = []

        if discover:
            print(f"\n📄 {rel_path}")
            for dc in detected_contracts:
                print(f"  └─ Class: {dc.class_name} -> Base: {dc.base_class} (contract: {dc.contract_type})")
                if dc.required_methods:
                    print(f"     Required: {', '.join(dc.required_methods)}")
                if dc.optional_methods:
                    print(f"     Optional: {', '.join(dc.optional_methods)}")

        for contract in detected_contracts:
            validator = ContractValidator()
            violation = validator.validate(symbol_table, contract)

            has_singleton = self._has_singleton(ast.parse(content))
            singleton_required = self.config.get("singleton_required", False)

            violations_list: List[KernelViolation] = []

            if violation.missing_required:
                msg = f"Modul '{contract.contract_type}' kehilangan method kritis: {', '.join(violation.missing_required)}"
                rca = self.rca.analyze(msg, "CRITICAL", rel_path, {
                    "contract_type": contract.contract_type,
                    "base_class": contract.base_class,
                    "class_name": contract.class_name,
                    "source": contract.source,
                })
                violations_list.append(KernelViolation(
                    file_path=rel_path,
                    module_type=contract.contract_type,
                    severity="CRITICAL",
                    message=msg,
                    suggestion=f"Implementasikan method: {', '.join(violation.missing_required)}",
                    rca_result=rca,
                ))

            if violation.missing_optional and not violation.missing_required:
                msg = f"Modul '{contract.contract_type}' kehilangan method opsional: {', '.join(violation.missing_optional)}"
                rca = self.rca.analyze(msg, "MEDIUM", rel_path, {
                    "contract_type": contract.contract_type,
                    "base_class": contract.base_class,
                    "class_name": contract.class_name,
                    "source": contract.source,
                })
                violations_list.append(KernelViolation(
                    file_path=rel_path,
                    module_type=contract.contract_type,
                    severity="MEDIUM",
                    message=msg,
                    suggestion=f"Pertimbangkan method: {', '.join(violation.missing_optional)} (opsional)",
                    rca_result=rca,
                ))

            if singleton_required and not has_singleton:
                violations_list.append(KernelViolation(
                    file_path=rel_path,
                    module_type=contract.contract_type,
                    severity="LOW",
                    message=f"Modul '{contract.contract_type}' tidak memiliki singleton pattern.",
                    suggestion="Tambahkan _instance class variable dan get_instance() method.",
                    rca_result=None,
                ))

            modules_info.append(KernelModuleInfo(
                file_path=rel_path,
                contract_type=contract.contract_type,
                class_name=contract.class_name,
                base_class=contract.base_class,
                required_methods=contract.required_methods,
                optional_methods=contract.optional_methods,
                missing_required=violation.missing_required,
                missing_optional=violation.missing_optional,
                has_singleton=has_singleton,
                source=contract.source,
                violations=violations_list,
            ))

        return modules_info[0] if modules_info else None

    def scan(self, discover: bool = False) -> List[KernelModuleInfo]:
        files = self._get_files()
        self._results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.get("max_workers", 4)) as executor:
            future_to_file = {executor.submit(self.scan_file, f, discover): f for f in files}
            for future in concurrent.futures.as_completed(future_to_file):
                result = future.result()
                if result:
                    self._results.append(result)
        return self._results

# =============================================================================
# REPORTING
# =============================================================================
def print_report(modules: List[KernelModuleInfo], verbose: bool = False, show_rca: bool = True):
    c = COLOR
    total = len(modules)

    critical_ok = 0
    critical_total = 0
    optional_ok = 0
    optional_total = 0
    singleton_ok = 0
    singleton_total = 0

    for mod in modules:
        if mod.missing_required:
            critical_total += 1
        else:
            critical_ok += 1
        if mod.missing_required:
            pass
        else:
            optional_total += 1
            if not mod.missing_optional:
                optional_ok += 1
        singleton_total += 1
        if mod.has_singleton:
            singleton_ok += 1

    critical_score = (critical_ok / total * 100) if total else 100.0
    optional_score = (optional_ok / optional_total * 100) if optional_total else 100.0
    singleton_score = (singleton_ok / singleton_total * 100) if singleton_total else 100.0
    overall_score = (critical_score * 0.6 + optional_score * 0.3 + singleton_score * 0.1)

    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║         KERNEL LAYER COMPLIANCE REPORT — v10.2          ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print("  📋 Contract Detection Method:")
    print("    • Multi-level inheritance resolution within same file")
    print("    • Abstract methods extracted from base classes")
    print("    • Configurable base class contracts (YAML)")
    print("    • No inference, no folder fallback")

    print(f"\n  Total Core Kernel Modules (with explicit contracts): {total}")
    print(f"  RCA Engine: {'✅ Aktif' if RCA_AVAILABLE else '⚠️ Tidak tersedia'}")
    print(f"  ⚠️  Note: guards/ and immutable_laws/ are NOT scanned here (use separate checkers)")

    print(f"\n  📊 COMPLIANCE SCORES:")
    print(f"    🔴 Critical (required methods): {critical_score:.1f}% ({critical_ok}/{total})")
    print(f"    🟡 Optional (extra methods):   {optional_score:.1f}% ({optional_ok}/{optional_total} when critical OK)")
    print(f"    🔵 Singleton pattern:          {singleton_score:.1f}% ({singleton_ok}/{singleton_total})")
    print(f"    {c['BOLD']}⭐ Overall Kernel Score:        {overall_score:.1f}/100{c['RESET']}")

    violators = [m for m in modules if m.violations]
    if violators:
        print(f"\n{c['RED']}─── VIOLATIONS ───{c['RESET']}")
        for mod in violators:
            print(f"\n  {c['YELLOW']}{mod.contract_type}{c['RESET']} @ {mod.file_path} [inherits: {mod.base_class}, src: {mod.source}]")
            for v in mod.violations:
                sev_color = c["RED"] if v.severity in ("CRITICAL", "HIGH") else c["YELLOW"]
                print(f"    {sev_color}[{v.severity}]{c['RESET']} {v.message}")
                print(f"      💡 {v.suggestion}")
                if verbose and show_rca and v.rca_result:
                    rca = v.rca_result
                    if rca.get("root_cause"):
                        print(f"      🔍 RCA Root Cause: {rca['root_cause']}")
                    if rca.get("suggested_fix"):
                        print(f"      🔧 RCA Fix: {rca['suggested_fix']}")
                    if rca.get("evidence"):
                        for ev in rca["evidence"][:3]:
                            print(f"      📎 Evidence: {ev}")
    else:
        print(f"\n{c['GREEN']}✅ Semua kernel modules compliant!{c['RESET']}")

def save_json(modules: List[KernelModuleInfo], path: str, include_rca: bool = True):
    try:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "10.2",
            "total_modules": len(modules),
            "compliant": [m.file_path for m in modules if not m.violations],
            "violations": [
                v.to_dict() for m in modules for v in m.violations
                if include_rca or not v.rca_result
            ],
            "scores": {
                "critical": {
                    "ok": sum(1 for m in modules if not m.missing_required),
                    "total": len(modules),
                    "percentage": (sum(1 for m in modules if not m.missing_required) / len(modules) * 100) if modules else 100
                },
                "optional": {
                    "ok": sum(1 for m in modules if not m.missing_required and not m.missing_optional),
                    "total": sum(1 for m in modules if not m.missing_required),
                    "percentage": (sum(1 for m in modules if not m.missing_required and not m.missing_optional) / max(1, sum(1 for m in modules if not m.missing_required)) * 100)
                },
                "singleton": {
                    "ok": sum(1 for m in modules if m.has_singleton),
                    "total": len(modules),
                    "percentage": (sum(1 for m in modules if m.has_singleton) / len(modules) * 100) if modules else 100
                },
                "overall": (sum(1 for m in modules if not m.missing_required) / len(modules) * 60 +
                            (sum(1 for m in modules if not m.missing_required and not m.missing_optional) / max(1, sum(1 for m in modules if not m.missing_required)) * 30) +
                            (sum(1 for m in modules if m.has_singleton) / len(modules) * 10)) if modules else 100
            },
            "note": "Contract detection: inheritance from base classes with abstract methods or configurable contracts.",
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"{COLOR['GREEN']}✅ JSON exported to {out.resolve()}{COLOR['RESET']}")
    except Exception as e:
        print(f"{COLOR['RED']}❌ JSON export failed: {e}{COLOR['RESET']}")

# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Kernel Layer Compliance Checker v10.2 (Contract‑Based)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--config", type=str, help="Path to YAML config file (optional)")
    parser.add_argument("--json", type=str, help="Export violations to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed RCA output")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--severity", choices=["CRITICAL", "HIGH", "MEDIUM", "LOW"], 
                        default=None, help="Minimum severity to report")
    parser.add_argument("--discover", action="store_true", help="Show all detected contracts (dry-run)")
    args = parser.parse_args()

    if args.no_rca:
        global RCA_AVAILABLE, analyze_exception
        RCA_AVAILABLE = False
        analyze_exception = None

    config = None
    if args.config:
        try:
            import yaml
            with open(args.config, "r") as f:
                config = yaml.safe_load(f)
        except ImportError:
            logger.warning("PyYAML not installed; config file ignored")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

    if config is None:
        config = DEFAULT_CONFIG.copy()

    checker = KernelChecker(ROOT, config)
    start = time.monotonic()
    modules = checker.scan(discover=args.discover)
    elapsed = time.monotonic() - start

    if args.discover:
        print("\n✅ Discovery complete. To run with contracts, remove --discover.")
        return

    if args.severity:
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        min_level = severity_order[args.severity]
        for mod in modules:
            mod.violations = [v for v in mod.violations if severity_order.get(v.severity, 99) <= min_level]

    print_report(modules, args.verbose, show_rca=not args.no_rca)
    if args.json:
        save_json(modules, args.json, include_rca=not args.no_rca)

    print(f"\n ⏱️ Audit Duration: {elapsed:.2f}s (workers={args.workers})")

    has_error = any(v.severity != "INFO" for m in modules for v in m.violations)
    sys.exit(1 if has_error else 0)

if __name__ == "__main__":
    main()