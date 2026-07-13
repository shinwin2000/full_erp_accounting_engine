#!/usr/bin/env python3
"""
checker/constitution_checker.py
================================
Static checker for constitution/ modules.
Verifies that each module exists, is imported in __init__.py, and exports
the expected classes/functions via __all__.

Usage:
    python -m checker.constitution_checker --verbose
    python -m checker.constitution_checker --json report.json
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

# ---- Expectations: key = filename (without .py), value = list of expected class/function/const names ----
# Only need at least ONE match per module
MODULE_EXPECTATIONS = {
    "supreme_law": ["SupremeLaw", "get_supreme_law"],
    "forbidden_states": ["ForbiddenStatesService", "get_forbidden_states_service"],  # FORBIDDEN_STATES optional
    "enforcement_engine": ["EnforcementEngine", "get_enforcement_engine"],  # enforce optional
    "amendment_protocol": ["AmendmentProtocol", "get_amendment_protocol"],  # propose_amendment optional
    "sovereignty_declaration": ["SovereigntyDeclaration", "get_sovereignty_guardian"],  # get_sovereignty_declaration optional
    "version_lock": ["VersionLock", "get_version_lock_service"],  # get_version_lock, lock_version, unlock_version optional
    "constitutional_invariants": ["ConstitutionalInvariants"],  # get_constitutional_invariants, get_invariants optional
    "constitution_exceptions": ["ConstitutionException", "ConstitutionExceptionFactory"],
}


class ConstitutionChecker:
    def __init__(self, constitution_path: Path | None = None):
        if constitution_path is None:
            constitution_path = ROOT / "constitution"
        self.constitution_path = Path(constitution_path)
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.infos: list[dict[str, Any]] = []
        self.modules_found: set[str] = set()
        self.module_imports: dict[str, set[str]] = {}  # module -> set of imported names from __init__

    def check_all(self) -> dict[str, Any]:
        if not self.constitution_path.exists():
            self.errors.append({"file": str(self.constitution_path), "error": "Folder constitution tidak ditemukan"})
            return self._result()

        # Kumpulkan semua file .py (kecuali __init__.py)
        py_files = {}
        for py_file in self.constitution_path.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            module_name = py_file.stem
            self.modules_found.add(module_name)
            py_files[module_name] = py_file

        # Periksa setiap modul
        for module_name, py_file in py_files.items():
            self._check_module(module_name, py_file)

        # Periksa __init__.py
        self._check_init()

        # Setelah __init__ diperiksa, periksa apakah semua modul diimpor
        for module in self.modules_found:
            if module not in self.module_imports:
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
            self.errors.append({"module": module_name, "file": str(py_file), "error": f"Parse error: {e}"})
            return

        # Kumpulkan semua nama yang didefinisikan (kelas, fungsi, konstanta)
        definitions = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) or isinstance(node, ast.FunctionDef):
                definitions.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        definitions.add(target.id)

        # Periksa apakah ada ekspektasi untuk modul ini
        expected = MODULE_EXPECTATIONS.get(module_name, [])
        if not expected:
            self.infos.append({"module": module_name, "info": "Modul ini tidak memiliki ekspektasi terdaftar"})
            return

        # Cari yang cocok
        found = [name for name in expected if name in definitions]
        if not found:
            self.errors.append({
                "module": module_name,
                "error": f"Tidak ditemukan satupun dari: {', '.join(expected)}"
            })
        else:
            missing = [name for name in expected if name not in definitions]
            if missing:
                self.warnings.append({
                    "module": module_name,
                    "warning": f"Tidak ditemukan: {', '.join(missing)} (ditemukan: {', '.join(found)})"
                })

    def _check_init(self):
        init_file = self.constitution_path / "__init__.py"
        if not init_file.exists():
            self.warnings.append({"file": str(init_file), "warning": "__init__.py tidak ditemukan"})
            return

        try:
            content = init_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(init_file))
        except Exception as e:
            self.errors.append({"file": str(init_file), "error": f"Parse error: {e}"})
            return

        # 1. Kumpulkan impor dari modul lokal (baik absolute maupun relative)
        imports: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                module_parts = node.module.split('.')
                # Cek apakah import dari constitution (absolute) atau relative (diawali titik)
                if module_parts[0] == 'constitution':
                    # from constitution.xxx import ...
                    if len(module_parts) >= 2:
                        module_name = module_parts[1]
                    else:
                        continue
                elif node.module.startswith('.'):
                    # relative import: .xxx atau ..xxx
                    parts = [p for p in node.module.split('.') if p]
                    if parts:
                        module_name = parts[-1]
                    else:
                        continue
                else:
                    # Bukan import dari constitution, lewati
                    continue

                if module_name in self.modules_found:
                    for alias in node.names:
                        imports.setdefault(module_name, set()).add(alias.name)

        self.module_imports = imports

        # 2. Cari __all__
        all_list = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List):
                            all_list = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
                        break
        if all_list is None:
            self.warnings.append({"file": str(init_file), "warning": "__all__ tidak didefinisikan"})
            return

        # 3. Periksa ekspor dari setiap modul yang diimpor
        for module, imported_names in imports.items():
            expected = MODULE_EXPECTATIONS.get(module, [])
            if not expected:
                continue
            # Setidaknya satu dari expected harus ada di __all__
            exported = [name for name in expected if name in all_list]
            if not exported:
                self.errors.append({
                    "file": str(init_file),
                    "error": f"Tidak ada ekspektasi dari modul {module} yang diekspor di __all__ (expected: {', '.join(expected)})"
                })
            else:
                missing = [name for name in expected if name not in all_list]
                if missing:
                    self.warnings.append({
                        "file": str(init_file),
                        "warning": f"Beberapa ekspektasi dari modul {module} tidak diekspor di __all__: {', '.join(missing)}"
                    })

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


def check_constitution(constitution_path: Path | None = None) -> dict[str, Any]:
    checker = ConstitutionChecker(constitution_path)
    return checker.check_all()


def integrate_with_rca(engine=None):
    """Integrasi dengan RCA engine."""
    from checker.core.rca import Category, ErrorCode, RCAResult, RCARule, Severity, get_engine

    class StaticConstitutionRule(RCARule):
        def __init__(self):
            super().__init__(priority=196, category=Category.DDD, name="StaticConstitutionRule")
            self._checker = ConstitutionChecker()

        def match(self, exc, frames, context) -> bool:
            return "Constitution" in type(exc).__name__ or "constitution" in str(exc).lower()

        def analyze(self, exc, frames, context) -> RCAResult | None:
            result = self._checker.check_all()
            if result["errors"]:
                error_msgs = [f"{e.get('module','')}: {e.get('error','')}" for e in result["errors"]]
                return RCAResult(
                    severity=Severity.FATAL,
                    category=Category.DDD,
                    error_code=ErrorCode.ERP_VALIDATION,
                    root_cause="Pelanggaran konstitusi terdeteksi secara statis: " + "; ".join(error_msgs[:3]),
                    evidence=error_msgs,
                    impact=["Konstitusi sistem tidak terpenuhi."],
                    suggested_fix="Periksa constitution/ dan pastikan semua komponen terdefinisi dengan benar.",
                    raw_error=str(exc),
                    confidence=0.95
                )
            return None

    if engine is None:
        engine = get_engine()
    engine.register_rule(StaticConstitutionRule())
    return engine


def print_report(result: dict[str, Any], verbose: bool = False):
    c = COLOR
    summary = result["summary"]
    errors = result["errors"]
    warnings = result["warnings"]
    infos = result["infos"]

    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║         CONSTITUTION STATIC CHECKER — v3.0            ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print(f"\n  📁 Constitution Path: {ROOT / 'constitution'}")
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
    parser = argparse.ArgumentParser(description="Constitution Static Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan info tambahan")
    parser.add_argument("--json", type=str, help="Export hasil ke JSON")
    args = parser.parse_args()

    result = check_constitution()
    if args.json:
        save_json(result, args.json)
    else:
        print_report(result, args.verbose)

    sys.exit(0 if result["summary"]["passed"] else 1)


if __name__ == "__main__":
    main()
