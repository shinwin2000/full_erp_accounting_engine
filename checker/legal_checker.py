#!/usr/bin/env python3
"""
checker/legal_checker.py
========================
Static checker untuk modul-modul di compliance/legal/.

Memeriksa:
- Keberadaan setiap file .py (kecuali __init__.py dan __pycache__)
- Apakah modul memiliki setidaknya satu definisi (kelas/fungsi/konstanta)
- Memberikan warning jika ekspektasi (berdasarkan nama modul) tidak terpenuhi
- Memastikan modul diimpor di __init__.py

Integrasi dengan RCA engine untuk pelaporan otomatis.

Usage:
    python -m checker.legal_checker --verbose
    python -m checker.legal_checker --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

# ---- Project root ----
_THIS_FILE = Path(__file__).resolve()
ROOT = _THIS_FILE.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

# ---- Ekspektasi berdasarkan nama file (tanpa .py) ----
# Disesuaikan dengan definisi aktual yang ditemukan di setiap modul
MODULE_EXPECTATIONS = {
    "authority_hierarchy": [
        "AuthorityHierarchy",
    ],
    "binding_precedence_resolver": [
        "BindingPrecedenceResolver",
    ],
    "compliance_scope_determiner": [
        "ComplianceScopeDeterminer",
        "determine_scope",
    ],
    "coretax_legal_basis_catalog": [
        "CoretaxLegalBasisCatalog",
        "get_basis",
    ],
    "jurisdiction_definition": [
        "JurisdictionDefinition",
        "get_jurisdiction",
    ],
    "legal_exceptions": [
        "LegalError",
        "LegalExceptionRegistry",
        "to_dict",
        "RegulatoryFilingError",
        "OverrideNotAllowedError",
    ],
    "legal_obligation_calendar": [
        "LegalObligationCalendar",
    ],
    "legal_opinion_document_store": [
        "LegalOpinionDocumentStore",
    ],
    "legal_override_with_citation": [
        "LegalOverrideWithCitation",
    ],
    "legal_risk_assessment_engine": [
        "LegalRiskAssessmentEngine",
    ],
    "litigation_case_linker": [
        "LitigationCaseLinker",
    ],
    "regulatory_body_registry": [
        "RegulatoryBodyRegistry",
    ],
    "regulatory_filing_tracker": [
        "RegulatoryFilingTracker",
    ],
    "sanction_list_checker": [
        "SanctionListChecker",
    ],
    "sovereignty_boundary_guard": [
        "SovereigntyBoundaryGuard",
    ],
}


class LegalChecker:
    def __init__(self, legal_path: Path | None = None):
        if legal_path is None:
            legal_path = ROOT / "compliance" / "legal"
        self.legal_path = Path(legal_path)
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.infos: list[dict[str, Any]] = []
        self.modules_found: set[str] = set()
        self.init_imports: dict[str, set[str]] = {}  # module -> imported names

    def check_all(self) -> dict[str, Any]:
        if not self.legal_path.exists():
            self.errors.append({
                "file": str(self.legal_path),
                "error": "Folder compliance/legal/ tidak ditemukan"
            })
            return self._result()

        py_files = {}
        for py_file in self.legal_path.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            if py_file.name.startswith("__") and py_file.name.endswith("__"):
                continue
            module_name = py_file.stem
            self.modules_found.add(module_name)
            py_files[module_name] = py_file

        for module_name, py_file in py_files.items():
            self._check_module(module_name, py_file)

        self._check_init()

        for module in self.modules_found:
            if module not in self.init_imports:
                self.warnings.append({
                    "module": module,
                    "warning": f"Modul {module} tidak diimpor di __init__.py"
                })

        return self._result()

    def _check_module(self, module_name: str, py_file: Path):
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(py_file))
        except Exception as e:
            self.errors.append({
                "module": module_name,
                "file": str(py_file),
                "error": f"Parse error: {e}"
            })
            return

        definitions = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) or isinstance(node, ast.FunctionDef):
                definitions.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        definitions.add(target.id)

        if not definitions:
            self.errors.append({
                "module": module_name,
                "error": "Modul tidak memiliki definisi (kelas/fungsi/konstanta) sama sekali"
            })
            return

        expected = MODULE_EXPECTATIONS.get(module_name, [])
        if not expected:
            self.infos.append({
                "module": module_name,
                "info": "Modul ini tidak memiliki ekspektasi terdaftar, tetapi memiliki definisi"
            })
            return

        found = [name for name in expected if name in definitions]
        if not found:
            self.warnings.append({
                "module": module_name,
                "warning": f"Tidak ditemukan satupun dari ekspektasi: {', '.join(expected)}. "
                           f"Definisi yang ditemukan: {', '.join(list(definitions)[:5])}"
            })
        else:
            missing = [name for name in expected if name not in definitions]
            if missing:
                self.warnings.append({
                    "module": module_name,
                    "warning": f"Tidak ditemukan: {', '.join(missing)} (ditemukan: {', '.join(found)})"
                })

    def _check_init(self):
        init_file = self.legal_path / "__init__.py"
        if not init_file.exists():
            self.warnings.append({
                "file": str(init_file),
                "warning": "__init__.py tidak ditemukan"
            })
            return

        try:
            content = init_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(init_file))
        except Exception as e:
            self.errors.append({
                "file": str(init_file),
                "error": f"Parse error: {e}"
            })
            return

        # Kumpulkan impor modul lokal
        imports: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    # relative import
                    if node.module is None:
                        # from . import xxx
                        for alias in node.names:
                            module_name = alias.name
                            if module_name in self.modules_found:
                                imports.setdefault(module_name, set()).add(alias.name)
                    else:
                        parts = [p for p in node.module.split('.') if p]
                        if parts:
                            module_name = parts[-1]
                            if module_name in self.modules_found:
                                for alias in node.names:
                                    imports.setdefault(module_name, set()).add(alias.name)
                else:
                    # absolute import: from compliance.legal.xxx import ...
                    module_parts = node.module.split('.')
                    if module_parts[0] == 'compliance' and len(module_parts) >= 3 and module_parts[1] == 'legal':
                        module_name = module_parts[2]
                        if module_name in self.modules_found:
                            for alias in node.names:
                                imports.setdefault(module_name, set()).add(alias.name)

        self.init_imports = imports

        # Tidak memeriksa __all__ agar tidak terlalu banyak warning

    def _result(self) -> dict[str, Any]:
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "infos": self.infos,
            "summary": {
                "modules_found": len(self.modules_found),
                "errors_count": len(self.errors),
                "warnings_count": len(self.warnings),
                "passed": len(self.errors) == 0,
            }
        }


def check_legal(legal_path: Path | None = None) -> dict[str, Any]:
    checker = LegalChecker(legal_path)
    return checker.check_all()


# ==================== INTEGRASI DENGAN RCA ====================

def integrate_with_rca(engine=None):
    try:
        from checker.core.rca import Category, ErrorCode, RCAResult, RCARule, Severity, get_engine
    except ImportError:
        print("⚠️ RCA engine tidak ditemukan, integrasi dilewati")
        return None

    class StaticLegalRule(RCARule):
        def __init__(self):
            super().__init__(priority=194, category=Category.DDD, name="StaticLegalRule")
            self._checker = LegalChecker()

        def match(self, exc, frames, context) -> bool:
            return "Legal" in type(exc).__name__ or "legal" in str(exc).lower()

        def analyze(self, exc, frames, context) -> RCAResult | None:
            result = self._checker.check_all()
            if result["errors"]:
                error_msgs = [f"{e.get('module','')}: {e.get('error','')}" for e in result["errors"]]
                return RCAResult(
                    severity=Severity.FATAL,
                    category=Category.DDD,
                    error_code=ErrorCode.ERP_VALIDATION,
                    root_cause="Pelanggaran legal terdeteksi secara statis: " + "; ".join(error_msgs[:3]),
                    evidence=error_msgs,
                    impact=["Kepatuhan legal sistem tidak terpenuhi."],
                    suggested_fix="Periksa compliance/legal/ dan pastikan semua komponen terdefinisi dengan benar.",
                    raw_error=str(exc),
                    confidence=0.90
                )
            return None

    if engine is None:
        engine = get_engine()
    engine.register_rule(StaticLegalRule())
    return engine


# ==================== REPORTING ====================

def print_report(result: dict[str, Any], verbose: bool = False):
    c = COLOR
    summary = result["summary"]
    errors = result["errors"]
    warnings = result["warnings"]
    infos = result["infos"]

    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║         LEGAL STATIC CHECKER — v1.1                  ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print(f"\n  📁 Legal Path: {ROOT / 'compliance' / 'legal'}")
    print(f"  📄 Modules Found: {summary['modules_found']}")
    print(f"  ✅ Errors: {summary['errors_count']}")
    print(f"  ⚠️  Warnings: {summary['warnings_count']}")
    print(f"  🏆 Overall Status: {'✅ PASS' if summary['passed'] else '❌ FAIL'}")

    if errors:
        print(f"\n{c['RED']}─── ERRORS ───{c['RESET']}")
        for e in errors:
            file_or_mod = e.get("file") or e.get("module") or "unknown"
            print(f"  {c['RED']}✗{c['RESET']} {file_or_mod}: {e.get('error', '')}")
    if warnings:
        print(f"\n{c['YELLOW']}─── WARNINGS ───{c['RESET']}")
        for w in warnings:
            file_or_mod = w.get("file") or w.get("module") or "unknown"
            print(f"  {c['YELLOW']}⚠{c['RESET']} {file_or_mod}: {w.get('warning', '')}")
    if verbose and infos:
        print(f"\n{c['CYAN']}─── INFO ───{c['RESET']}")
        for info in infos:
            file_or_mod = info.get("module") or "unknown"
            print(f"  {c['CYAN']}ℹ{c['RESET']} {file_or_mod}: {info.get('info', '')}")


def save_json(result: dict[str, Any], path: str):
    Path(path).write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"{COLOR['GREEN']}✅ JSON exported to {path}{COLOR['RESET']}")


def main():
    parser = argparse.ArgumentParser(description="Legal Static Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan info tambahan")
    parser.add_argument("--json", type=str, help="Export hasil ke JSON")
    args = parser.parse_args()

    result = check_legal()
    if args.json:
        save_json(result, args.json)
    else:
        print_report(result, args.verbose)

    sys.exit(0 if result["summary"]["passed"] else 1)


if __name__ == "__main__":
    main()
