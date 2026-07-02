#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/core/constitution_checker.py
=====================================
Static checker for constitution/ modules.
Verifies:
- SupremeLaw class has verify_integrity() and get_law().
- Forbidden states are defined as constants.
- Enforcement engine has enforce() function.
- Amendment protocol exists.
- Sovereignty declaration is consistent.
- Version lock is present.
- All modules are properly exported.
"""

import ast
import importlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_root = Path(__file__).parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from checker.core.rca import Severity, RCAResult, Category, ErrorCode

__all__ = ["ConstitutionChecker", "check_constitution", "integrate_with_rca"]


class ConstitutionChecker:
    """Static checker untuk constitution/."""

    REQUIRED_MODULES = {
        "supreme_law": {
            "class": "SupremeLaw",
            "methods": ["verify_integrity", "get_law", "get_version"],
        },
        "forbidden_states": {
            "constants": ["FORBIDDEN_STATES"],
        },
        "enforcement_engine": {
            "functions": ["enforce", "check_state"],
        },
        "amendment_protocol": {
            "functions": ["propose_amendment", "ratify_amendment"],
        },
        "sovereignty_declaration": {
            "functions": ["get_sovereignty", "verify_sovereignty"],
        },
        "version_lock": {
            "functions": ["get_status", "lock_version", "unlock_version"],
        },
        "constitutional_invariants": {
            "functions": ["get_invariants", "verify_invariants"],
        },
    }

    def __init__(self, constitution_path: Optional[Path] = None):
        if constitution_path is None:
            constitution_path = _root / "constitution"
        self.constitution_path = Path(constitution_path)
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.module_trees: Dict[str, ast.Module] = {}
        self.module_globals: Dict[str, Set[str]] = {}

    def check_all(self) -> Dict[str, Any]:
        """Jalankan semua pemeriksaan."""
        self._collect_modules()
        self._check_required_modules()
        self._check_supreme_law()
        self._check_forbidden_states()
        self._check_enforcement_engine()
        self._check_amendment_protocol()
        self._check_version_lock()
        self._check_init_exports()
        self._check_circular_imports()
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": {
                "total_modules": len(self.module_trees),
                "errors_count": len(self.errors),
                "warnings_count": len(self.warnings),
                "passed": len(self.errors) == 0,
            }
        }

    def _collect_modules(self):
        if not self.constitution_path.exists():
            self.errors.append({"file": str(self.constitution_path), "error": "Folder constitution tidak ditemukan"})
            return
        for py_file in self.constitution_path.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()
                tree = ast.parse(content, filename=str(py_file))
                module_name = py_file.stem
                self.module_trees[module_name] = tree
                # Kumpulkan semua definisi (fungsi, kelas, konstanta)
                definitions = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        definitions.add(f"func:{node.name}")
                    elif isinstance(node, ast.ClassDef):
                        definitions.add(f"class:{node.name}")
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                definitions.add(f"const:{target.id}")
                self.module_globals[module_name] = definitions
            except Exception as e:
                self.errors.append({"file": str(py_file), "error": f"Parse error: {e}"})

    def _check_required_modules(self):
        """Periksa semua modul yang diharapkan ada."""
        for mod_name, spec in self.REQUIRED_MODULES.items():
            if mod_name not in self.module_trees:
                self.errors.append({
                    "module": mod_name,
                    "error": f"Modul {mod_name} tidak ditemukan di constitution/"
                })
                continue
            definitions = self.module_globals.get(mod_name, set())
            # Periksa class
            if "class" in spec:
                class_name = spec["class"]
                if f"class:{class_name}" not in definitions:
                    self.errors.append({
                        "module": mod_name,
                        "error": f"Class {class_name} tidak ditemukan"
                    })
            # Periksa methods
            if "methods" in spec:
                for method in spec["methods"]:
                    # Method seharusnya ada di class, tapi kita cek di definisi global juga
                    if f"func:{method}" not in definitions and f"class_method:{method}" not in definitions:
                        self.warnings.append({
                            "module": mod_name,
                            "warning": f"Method {method} tidak ditemukan (mungkin di dalam class)"
                        })
            # Periksa konstanta
            if "constants" in spec:
                for const in spec["constants"]:
                    if f"const:{const}" not in definitions:
                        self.errors.append({
                            "module": mod_name,
                            "error": f"Konstanta {const} tidak ditemukan"
                        })
            if "functions" in spec:
                for func in spec["functions"]:
                    if f"func:{func}" not in definitions:
                        self.errors.append({
                            "module": mod_name,
                            "error": f"Fungsi {func} tidak ditemukan"
                        })

    def _check_supreme_law(self):
        """Periksa supreme_law.py lebih detail."""
        if "supreme_law" not in self.module_trees:
            return
        tree = self.module_trees["supreme_law"]
        # Cari class SupremeLaw dan metode verify_integrity
        found_class = False
        found_verify = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SupremeLaw":
                found_class = True
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "verify_integrity":
                        found_verify = True
                        break
        if not found_class:
            self.errors.append({
                "module": "supreme_law",
                "error": "Class SupremeLaw tidak ditemukan"
            })
        elif not found_verify:
            self.errors.append({
                "module": "supreme_law",
                "error": "Method verify_integrity tidak ditemukan di SupremeLaw"
            })

    def _check_forbidden_states(self):
        """Periksa forbidden_states.py memiliki konstanta FORBIDDEN_STATES."""
        if "forbidden_states" not in self.module_trees:
            return
        definitions = self.module_globals.get("forbidden_states", set())
        if "const:FORBIDDEN_STATES" not in definitions:
            self.errors.append({
                "module": "forbidden_states",
                "error": "Konstanta FORBIDDEN_STATES tidak ditemukan"
            })
        else:
            # Coba evaluasi nilai secara statis (jika mungkin)
            # Kita bisa parse AST untuk mengambil nilai
            tree = self.module_trees["forbidden_states"]
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "FORBIDDEN_STATES":
                            if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                                self.warnings.append({
                                    "module": "forbidden_states",
                                    "info": f"FORBIDDEN_STATES berisi {len(node.value.elts)} item"
                                })
                            elif isinstance(node.value, ast.Constant):
                                self.warnings.append({
                                    "module": "forbidden_states",
                                    "info": f"FORBIDDEN_STATES adalah constant: {node.value.value}"
                                })
                            break

    def _check_enforcement_engine(self):
        """Periksa enforcement_engine.py memiliki fungsi enforce dan check_state."""
        if "enforcement_engine" not in self.module_trees:
            return
        definitions = self.module_globals.get("enforcement_engine", set())
        for func in ["enforce", "check_state"]:
            if f"func:{func}" not in definitions:
                self.errors.append({
                    "module": "enforcement_engine",
                    "error": f"Fungsi {func} tidak ditemukan"
                })

    def _check_amendment_protocol(self):
        """Periksa amendment_protocol.py."""
        if "amendment_protocol" not in self.module_trees:
            return
        definitions = self.module_globals.get("amendment_protocol", set())
        for func in ["propose_amendment", "ratify_amendment"]:
            if f"func:{func}" not in definitions:
                self.warnings.append({
                    "module": "amendment_protocol",
                    "warning": f"Fungsi {func} tidak ditemukan (mungkin opsional)"
                })

    def _check_version_lock(self):
        """Periksa version_lock.py."""
        if "version_lock" not in self.module_trees:
            return
        definitions = self.module_globals.get("version_lock", set())
        for func in ["get_status", "lock_version", "unlock_version"]:
            if f"func:{func}" not in definitions:
                self.errors.append({
                    "module": "version_lock",
                    "error": f"Fungsi {func} tidak ditemukan"
                })

    def _check_init_exports(self):
        """Periksa constitution/__init__.py."""
        init_file = self.constitution_path / "__init__.py"
        if not init_file.exists():
            self.errors.append({"file": str(init_file), "error": "__init__.py tidak ditemukan"})
            return
        with open(init_file, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content)
        all_defined = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List):
                            all_defined = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
                        break
        if all_defined is None:
            self.warnings.append({
                "file": str(init_file),
                "warning": "__all__ tidak didefinisikan di __init__.py"
            })
        else:
            # Periksa apakah semua modul penting ada di __all__
            for mod in self.REQUIRED_MODULES.keys():
                if mod not in all_defined:
                    self.errors.append({
                        "file": str(init_file),
                        "error": f"Modul {mod} tidak diekspor di __all__"
                    })

    def _check_circular_imports(self):
        """Periksa circular import antar modul constitution."""
        try:
            import networkx as nx
        except ImportError:
            self.warnings.append({"warning": "networkx not installed, skipping circular import check"})
            return
        G = nx.DiGraph()
        for module, tree in self.module_trees.items():
            G.add_node(module)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imp = alias.name.split(".")[0]
                        if imp in self.module_trees:
                            G.add_edge(module, imp)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module in self.module_trees:
                        G.add_edge(module, node.module)
        try:
            cycles = list(nx.simple_cycles(G))
            if cycles:
                self.errors.append({
                    "error": f"Circular imports detected: {cycles}"
                })
        except Exception as e:
            self.warnings.append({"warning": f"Cycle detection error: {e}"})


def check_constitution(constitution_path: Optional[Path] = None) -> Dict[str, Any]:
    """Fungsi convenience."""
    checker = ConstitutionChecker(constitution_path)
    return checker.check_all()


def integrate_with_rca(engine=None):
    """
    Tambahkan rule statis untuk constitution ke RCA engine.
    """
    from checker.core.rca import get_engine, RCARule, Severity, ErrorCode, Category, RCAResult

    class StaticConstitutionRule(RCARule):
        def __init__(self):
            super().__init__(priority=196, category=Category.DDD, name="StaticConstitutionRule")
            self._checker = ConstitutionChecker()

        def match(self, exc, frames, context) -> bool:
            return "Constitution" in type(exc).__name__ or "constitution" in str(exc).lower()

        def analyze(self, exc, frames, context) -> Optional[RCAResult]:
            result = self._checker.check_all()
            if result["errors"]:
                error_msgs = [f"{e.get('module','')}: {e.get('error','')}" for e in result["errors"]]
                return RCAResult(
                    severity=Severity.FATAL,
                    category=Category.DDD,
                    error_code=ErrorCode.ERP_VALIDATION,
                    root_cause="Pelanggaran konstitusi terdeteksi secara statis: " + "; ".join(error_msgs[:3]),
                    evidence=error_msgs,
                    impact=["Konstitusi sistem tidak terpenuhi, sistem dalam kondisi tidak valid."],
                    suggested_fix="Periksa constitution/ dan pastikan semua komponen terdefinisi dengan benar.",
                    raw_error=str(exc),
                    confidence=0.95
                )
            return None

    if engine is None:
        engine = get_engine()
    engine.register_rule(StaticConstitutionRule())
    return engine


if __name__ == "__main__":
    import json
    result = check_constitution()
    print(json.dumps(result, indent=2))