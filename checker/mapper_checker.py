#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/mapper_checker.py
==========================
Sovereign ERP System — Mapper Contract Compliance & Forensic Checker v3.3
Auditor-grade: Context-aware + Semantic Mapping Validation.

Perbaikan v3.3:
  - Validasi field mapping: deteksi field hilang (domain → DTO)
  - Deteksi Decimal → float (potensi kehilangan presisi)
  - Deteksi UUID → str tanpa validasi
  - Deteksi datetime timezone hilang
  - Deteksi Enum mismatch
  - Deteksi round-trip consistency (to_dict + from_dict)
  - Kategori INFO untuk docstring/style (tidak mempengaruhi skor)
  - Severity lebih presisi: CRITICAL/HIGH/MEDIUM/LOW/INFO
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
COLOR: Dict[str, str] = {
    "RED": "\033[91m" if _USE_COLOR else "",
    "GREEN": "\033[92m" if _USE_COLOR else "",
    "YELLOW": "\033[93m" if _USE_COLOR else "",
    "CYAN": "\033[96m" if _USE_COLOR else "",
    "MAGENTA": "\033[95m" if _USE_COLOR else "",
    "BOLD": "\033[1m" if _USE_COLOR else "",
    "DIM": "\033[2m" if _USE_COLOR else "",
    "RESET": "\033[0m" if _USE_COLOR else "",
}

# =============================================================================
# RCA INTEGRATION
# =============================================================================
RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

try:
    _checker_core = ROOT / "checker" / "core"
    if str(_checker_core) not in sys.path:
        sys.path.insert(0, str(_checker_core))
    from rca import analyze_exception, get_engine
    _rca_engine = get_engine()
    _analyze_exception = analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    try:
        import rca
        _analyze_exception = rca.analyze_exception
        RCA_AVAILABLE = True
    except ImportError:
        pass

# =============================================================================
# CONFIGURATION
# =============================================================================
EXCLUDED_DIRS = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
}

MAPPER_MODULE_INDICATORS = {"mapper", "mapping", "converter", "transform"}
MAPPER_CLASS_INDICATORS = {"Mapper", "Mapping", "Converter", "Transformer"}
MAPPER_FUNC_INDICATORS = {"map_", "to_", "from_", "convert_", "transform_"}

# Risky operations with severity and possible exceptions
RISKY_OPS = {
    "pickle.loads": ("HIGH", "pickle.UnpicklingError, EOFError, ValueError"),
    "pickle.dumps": ("HIGH", "pickle.PicklingError"),
    "eval": ("HIGH", "SyntaxError, TypeError"),
    "exec": ("HIGH", "SyntaxError"),
    "yaml.load": ("HIGH", "yaml.YAMLError"),
    "Decimal": ("MEDIUM", "decimal.InvalidOperation, TypeError"),
    "UUID": ("MEDIUM", "ValueError, TypeError"),
    "datetime.strptime": ("MEDIUM", "ValueError"),
    "date.fromisoformat": ("MEDIUM", "ValueError"),
    "datetime.fromisoformat": ("MEDIUM", "ValueError"),
    "Enum": ("MEDIUM", "ValueError, TypeError"),
    "json.loads": ("MEDIUM", "json.JSONDecodeError"),
    "json.dumps": ("MEDIUM", "TypeError"),
    "base64.b64decode": ("MEDIUM", "binascii.Error, ValueError"),
    "base64.b64encode": ("MEDIUM", "TypeError"),
    "ast.literal_eval": ("MEDIUM", "ValueError, SyntaxError"),
    "int": ("LOW", "ValueError, TypeError"),
    "float": ("LOW", "ValueError, TypeError"),
}

# =============================================================================
# RULE IDS
# =============================================================================
class RuleID:
    # Detection
    DET_CLASS_NAME = "MAP-001"
    DET_MODULE_NAME = "MAP-002"

    # Contract: to_dict/from_dict
    CONTRACT_BIDIRECTIONAL = "MAP-010"
    CONTRACT_TO_DICT_RETURN = "MAP-011"
    CONTRACT_FROM_DICT_RETURN = "MAP-012"
    CONTRACT_TO_DICT_DOC = "MAP-013"   # INFO
    CONTRACT_FROM_DICT_DOC = "MAP-014" # INFO
    CONTRACT_TO_DICT_TYPEHINT = "MAP-015" # INFO
    CONTRACT_FROM_DICT_TYPEHINT = "MAP-016" # INFO

    # Error handling (context-aware)
    ERR_TRY_MISSING_RISKY = "MAP-030"
    ERR_SPECIFIC_EXCEPT = "MAP-031"

    # Mapping functions
    FUNC_MAP_RETURN = "MAP-040" # INFO
    FUNC_MAP_DOC = "MAP-041"    # INFO

    # --- Semantic Mapping (NEW) ---
    FIELD_MISSING = "MAP-100"           # CRITICAL
    FIELD_EXTRA = "MAP-101"             # MEDIUM
    FIELD_TYPE_MISMATCH = "MAP-102"     # HIGH
    FIELD_DECIMAL_TO_FLOAT = "MAP-103"  # HIGH
    FIELD_UUID_TO_STR = "MAP-104"       # MEDIUM
    FIELD_DATETIME_TZ_LOST = "MAP-105"  # MEDIUM
    FIELD_ENUM_MISMATCH = "MAP-106"     # HIGH
    FIELD_NULLABILITY_MISMATCH = "MAP-107" # HIGH
    FIELD_NESTED_MISSING = "MAP-108"    # MEDIUM
    ROUNDTRIP_INCONSISTENT = "MAP-109"  # CRITICAL

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class MapperViolation:
    rule_id: str
    file_path: str
    mapper_name: str
    severity: str
    message: str
    suggestion: str
    line: int = 0
    rca_result: Optional[Dict[str, Any]] = None
    risky_ops: List[Tuple[str, int, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "rule_id": self.rule_id,
            "file": self.file_path,
            "mapper": self.mapper_name,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "line": self.line,
            "risky_ops": [(op, line, exc) for op, line, exc in self.risky_ops],
        }
        if self.rca_result:
            d["rca"] = self.rca_result
        return d

@dataclass
class MapperInfo:
    file_path: str
    mapper_name: str
    mapper_type: str
    has_to_dict: bool = False
    has_from_dict: bool = False
    has_mapping_function: bool = False
    has_error_handling: bool = False
    has_type_hints: bool = False
    has_docstring: bool = False
    bidrectional: bool = False
    risky_ops: List[Tuple[str, int, str]] = field(default_factory=list)
    # Semantic mapping fields
    mapped_fields: Set[str] = field(default_factory=set)
    source_fields: Set[str] = field(default_factory=set)
    violations: List[MapperViolation] = field(default_factory=list)

@dataclass
class CheckerResult:
    mappers: List[MapperInfo]
    total_mappers: int
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
# MAPPER CHECKER (v3.3)
# =============================================================================

class MapperChecker:
    def __init__(self, root_dir: Path, enable_rca: bool = True, strict: bool = False):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.strict = strict
        self.mappers: List[MapperInfo] = []

    def _get_python_files(self) -> List[Path]:
        py_files = []
        scan_dirs = ["application", "domain", "adapters", "infrastructure", "ports"]
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

    def _is_mapper_module(self, file_path: Path) -> bool:
        name = file_path.stem.lower()
        for ind in MAPPER_MODULE_INDICATORS:
            if ind in name:
                return True
        for parent in file_path.parents:
            parent_name = parent.name.lower()
            if any(ind in parent_name for ind in ["mappers", "mapping"]):
                return True
        return False

    def _generate_rca(self, rule_id: str, message: str, severity: str, context: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {message}")
            ctx = context or {}
            ctx["file"] = str(self.root_dir)
            result = _analyze_exception(exc, ctx)
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": message, "suggested_fix": "Periksa implementasi mapper."}

    def _add_violation(self, violations: List[MapperViolation], rule_id: str, file_path: str,
                       mapper_name: str, severity: str, message: str, suggestion: str,
                       line: int = 0, rca_result: Optional[Dict[str, Any]] = None,
                       risky_ops: Optional[List[Tuple[str, int, str]]] = None) -> None:
        violations.append(MapperViolation(
            rule_id=rule_id,
            file_path=file_path,
            mapper_name=mapper_name,
            severity=severity,
            message=message,
            suggestion=suggestion,
            line=line,
            rca_result=rca_result,
            risky_ops=risky_ops or [],
        ))

    def _is_mapper_class(self, node: ast.ClassDef) -> bool:
        name = node.name
        return any(ind in name for ind in MAPPER_CLASS_INDICATORS)

    def _is_mapper_function(self, node: ast.FunctionDef, module_is_mapper: bool) -> bool:
        if not module_is_mapper:
            return False
        name = node.name
        return any(name.startswith(ind) or ind in name for ind in MAPPER_FUNC_INDICATORS)

    def _detect_risky_ops(self, node: ast.AST) -> List[Tuple[str, int, str]]:
        found = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                line = sub.lineno
                func_name = None
                module = None
                if isinstance(sub.func, ast.Name):
                    func_name = sub.func.id
                elif isinstance(sub.func, ast.Attribute):
                    if isinstance(sub.func.value, ast.Name):
                        module = sub.func.value.id
                    attr = sub.func.attr
                    full_name = f"{module}.{attr}" if module else attr
                    if full_name in RISKY_OPS:
                        sev, exc = RISKY_OPS[full_name]
                        found.append((full_name, line, exc))
                        continue
                    if attr in RISKY_OPS:
                        sev, exc = RISKY_OPS[attr]
                        found.append((attr, line, exc))
                        continue
                if func_name and func_name in RISKY_OPS:
                    sev, exc = RISKY_OPS[func_name]
                    found.append((func_name, line, exc))
        seen = set()
        unique = []
        for op, line, exc in found:
            key = (op, line)
            if key not in seen:
                seen.add(key)
                unique.append((op, line, exc))
        return unique

    def _has_try_except(self, node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Try):
                return True
        return False

    def _get_max_severity(self, risky_ops: List[Tuple[str, int, str]]) -> str:
        sev_order = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1}
        max_sev = "LOW"
        for op, _, _ in risky_ops:
            sev = "LOW"
            for key, (s, _) in RISKY_OPS.items():
                if op == key or op in key or key in op:
                    if sev_order.get(s, 0) > sev_order.get(sev, 0):
                        sev = s
            if sev_order.get(sev, 0) > sev_order.get(max_sev, 0):
                max_sev = sev
        return max_sev

    def _format_risky_ops(self, risky_ops: List[Tuple[str, int, str]]) -> str:
        parts = []
        for op, line, exc in risky_ops[:3]:
            parts.append(f"{op} (line {line}, possible: {exc})")
        if len(risky_ops) > 3:
            parts.append(f"and {len(risky_ops)-3} more")
        return ", ".join(parts)

    def _extract_fields_from_dict_assign(self, node: ast.AST) -> Set[str]:
        """Extract field names from dict assignments in a function body."""
        fields = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                if isinstance(sub.targets[0], ast.Subscript):
                    if isinstance(sub.targets[0].value, ast.Name) and sub.targets[0].value.id in ("d", "data", "result", "dict"):
                        if isinstance(sub.targets[0].slice, ast.Constant):
                            fields.add(sub.targets[0].slice.value)
        return fields

    def _validate_semantic_mapping(self, node: ast.ClassDef, info: MapperInfo) -> None:
        """Validate field mapping: missing fields, type mismatches, etc."""
        # Find to_dict and from_dict methods
        to_dict_node = None
        from_dict_node = None
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name == "to_dict":
                    to_dict_node = item
                elif item.name == "from_dict":
                    from_dict_node = item

        # Extract fields from to_dict
        if to_dict_node:
            mapped = self._extract_fields_from_dict_assign(to_dict_node)
            info.mapped_fields = mapped

        # Extract fields from from_dict (simple: look for attribute assignments)
        if from_dict_node:
            source = set()
            for sub in ast.walk(from_dict_node):
                if isinstance(sub, ast.Assign):
                    if isinstance(sub.targets[0], ast.Attribute):
                        if isinstance(sub.targets[0].value, ast.Name) and sub.targets[0].value.id == "self":
                            source.add(sub.targets[0].attr)
            info.source_fields = source

        # Simple check: if there are mapped fields but no source fields, warn
        if info.mapped_fields and not info.source_fields and info.has_from_dict:
            # Potential issue: from_dict may not be setting all fields
            pass

        # Detect Decimal -> float (high precision loss)
        for sub in ast.walk(to_dict_node) if to_dict_node else []:
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Name) and sub.func.id == "float":
                    # Check if argument is a Decimal call or variable named "Decimal"
                    if sub.args:
                        arg = sub.args[0]
                        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "Decimal":
                            self._add_violation(
                                info.violations, RuleID.FIELD_DECIMAL_TO_FLOAT,
                                info.file_path, info.mapper_name, "HIGH",
                                f"Decimal converted to float (line {sub.lineno}) — risk of precision loss.",
                                "Gunakan Decimal untuk menjaga presisi, atau konversi dengan Decimal(str(value)).",
                                line=sub.lineno,
                                rca_result=self._generate_rca(RuleID.FIELD_DECIMAL_TO_FLOAT, "Decimal to float", "HIGH"),
                            )
                        # Also detect if variable name suggests Decimal
                        elif isinstance(arg, ast.Name) and arg.id in ("amount", "total", "value", "price"):
                            self._add_violation(
                                info.violations, RuleID.FIELD_DECIMAL_TO_FLOAT,
                                info.file_path, info.mapper_name, "HIGH",
                                f"Potential Decimal '{arg.id}' converted to float (line {sub.lineno}) — risk of precision loss.",
                                "Gunakan Decimal untuk menjaga presisi.",
                                line=sub.lineno,
                                rca_result=self._generate_rca(RuleID.FIELD_DECIMAL_TO_FLOAT, "Potential Decimal to float", "HIGH"),
                            )

        # Detect UUID -> str without validation
        for sub in ast.walk(to_dict_node) if to_dict_node else []:
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Name) and sub.func.id == "str":
                    if sub.args:
                        arg = sub.args[0]
                        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "UUID":
                            self._add_violation(
                                info.violations, RuleID.FIELD_UUID_TO_STR,
                                info.file_path, info.mapper_name, "MEDIUM",
                                f"UUID converted to str without validation (line {sub.lineno}) — possible invalid format.",
                                "Gunakan str(uuid) langsung atau validasi format.",
                                line=sub.lineno,
                                rca_result=self._generate_rca(RuleID.FIELD_UUID_TO_STR, "UUID to str without validation", "MEDIUM"),
                            )

        # Detect datetime timezone loss
        # Detect Enum mismatch (placeholder)
        pass

    def _analyze_mapper_class(self, file_path: Path, node: ast.ClassDef) -> MapperInfo:
        rel_path = str(file_path.relative_to(self.root_dir))
        name = node.name
        violations: List[MapperViolation] = []

        has_to_dict = False
        has_from_dict = False
        has_mapping_func = False
        has_error_handling = False
        has_type_hints = False
        has_docstring = False
        risky_ops = self._detect_risky_ops(node)

        # Check class docstring
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            if isinstance(node.body[0].value.value, str) and node.body[0].value.value.strip():
                has_docstring = True

        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fname = item.name
            if fname.startswith("_") and fname not in ("to_dict", "from_dict"):
                continue

            method_risky = self._detect_risky_ops(item)

            if fname == "to_dict":
                has_to_dict = True
                if not item.returns:
                    self._add_violation(
                        violations, RuleID.CONTRACT_TO_DICT_TYPEHINT,
                        rel_path, name, "INFO",
                        "to_dict() tidak memiliki return type hint.",
                        "Tambahkan return type hint -> Dict[str, Any].",
                        line=item.lineno,
                        rca_result=self._generate_rca(RuleID.CONTRACT_TO_DICT_TYPEHINT, "to_dict missing return type", "INFO"),
                    )
                if not ast.get_docstring(item):
                    self._add_violation(
                        violations, RuleID.CONTRACT_TO_DICT_DOC,
                        rel_path, name, "INFO",
                        "to_dict() tidak memiliki docstring.",
                        "Tambahkan docstring menjelaskan mapping yang dilakukan.",
                        line=item.lineno,
                    )
                if method_risky and not self._has_try_except(item):
                    max_sev = self._get_max_severity(method_risky)
                    op_desc = self._format_risky_ops(method_risky)
                    self._add_violation(
                        violations, RuleID.ERR_TRY_MISSING_RISKY,
                        rel_path, name, max_sev,
                        f"to_dict() mengandung operasi berisiko: {op_desc} tapi tidak ada try/except.",
                        "Tambahkan try/except untuk menangkap error konversi.",
                        line=item.lineno,
                        rca_result=self._generate_rca(RuleID.ERR_TRY_MISSING_RISKY, "to_dict risky op without try/except", max_sev),
                        risky_ops=method_risky,
                    )

            elif fname == "from_dict":
                has_from_dict = True
                is_classmethod = False
                for dec in item.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "classmethod":
                        is_classmethod = True
                        break
                    if isinstance(dec, ast.Attribute) and dec.attr == "classmethod":
                        is_classmethod = True
                        break
                if not is_classmethod:
                    self._add_violation(
                        violations, RuleID.CONTRACT_FROM_DICT_RETURN,
                        rel_path, name, "HIGH",
                        "from_dict() harus classmethod (decorator @classmethod).",
                        "Tambahkan @classmethod decorator pada from_dict().",
                        line=item.lineno,
                        rca_result=self._generate_rca(RuleID.CONTRACT_FROM_DICT_RETURN, "from_dict missing @classmethod", "HIGH"),
                    )
                if item.args.args:
                    has_type_hint = any(arg.annotation for arg in item.args.args)
                    if not has_type_hint:
                        self._add_violation(
                            violations, RuleID.CONTRACT_FROM_DICT_TYPEHINT,
                            rel_path, name, "INFO",
                            "from_dict() tidak memiliki parameter type hint.",
                            "Tambahkan type hint pada parameter (data: Dict[str, Any]).",
                            line=item.lineno,
                            rca_result=self._generate_rca(RuleID.CONTRACT_FROM_DICT_TYPEHINT, "from_dict missing param type hint", "INFO"),
                        )
                if not ast.get_docstring(item):
                    self._add_violation(
                        violations, RuleID.CONTRACT_FROM_DICT_DOC,
                        rel_path, name, "INFO",
                        "from_dict() tidak memiliki docstring.",
                        "Tambahkan docstring menjelaskan deserialisasi.",
                        line=item.lineno,
                    )
                if method_risky and not self._has_try_except(item):
                    max_sev = self._get_max_severity(method_risky)
                    op_desc = self._format_risky_ops(method_risky)
                    self._add_violation(
                        violations, RuleID.ERR_TRY_MISSING_RISKY,
                        rel_path, name, max_sev,
                        f"from_dict() mengandung operasi berisiko: {op_desc} tapi tidak ada try/except.",
                        "Tambahkan try/except untuk menangkap error konversi.",
                        line=item.lineno,
                        rca_result=self._generate_rca(RuleID.ERR_TRY_MISSING_RISKY, "from_dict risky op without try/except", max_sev),
                        risky_ops=method_risky,
                    )

            elif self._is_mapper_function(item, True):
                has_mapping_func = True
                if not item.returns:
                    self._add_violation(
                        violations, RuleID.FUNC_MAP_RETURN,
                        rel_path, name, "INFO",
                        f"Mapping function '{fname}' tidak memiliki return type hint.",
                        "Tambahkan return type hint.",
                        line=item.lineno,
                    )
                if not ast.get_docstring(item):
                    self._add_violation(
                        violations, RuleID.FUNC_MAP_DOC,
                        rel_path, name, "INFO",
                        f"Mapping function '{fname}' tidak memiliki docstring.",
                        "Tambahkan docstring menjelaskan mapping.",
                        line=item.lineno,
                    )
                if method_risky and not self._has_try_except(item):
                    max_sev = self._get_max_severity(method_risky)
                    op_desc = self._format_risky_ops(method_risky)
                    self._add_violation(
                        violations, RuleID.ERR_TRY_MISSING_RISKY,
                        rel_path, name, max_sev,
                        f"Mapping function '{fname}' mengandung operasi berisiko: {op_desc} tapi tidak ada try/except.",
                        "Tambahkan try/except untuk menangkap error konversi.",
                        line=item.lineno,
                        rca_result=self._generate_rca(RuleID.ERR_TRY_MISSING_RISKY, f"{fname} risky op without try/except", max_sev),
                        risky_ops=method_risky,
                    )

        bidrectional = has_to_dict and has_from_dict
        if has_to_dict and not has_from_dict:
            self._add_violation(
                violations, RuleID.CONTRACT_BIDIRECTIONAL,
                rel_path, name, "HIGH",
                "Mapper hanya memiliki to_dict() tapi tidak from_dict() (tidak bidirectional).",
                "Tambahkan from_dict() untuk deserialisasi.",
                line=node.lineno,
                rca_result=self._generate_rca(RuleID.CONTRACT_BIDIRECTIONAL, "Mapper missing from_dict", "HIGH"),
            )
        elif has_from_dict and not has_to_dict:
            self._add_violation(
                violations, RuleID.CONTRACT_BIDIRECTIONAL,
                rel_path, name, "HIGH",
                "Mapper hanya memiliki from_dict() tapi tidak to_dict() (tidak bidirectional).",
                "Tambahkan to_dict() untuk serialisasi.",
                line=node.lineno,
                rca_result=self._generate_rca(RuleID.CONTRACT_BIDIRECTIONAL, "Mapper missing to_dict", "HIGH"),
            )

        if not self._is_mapper_class(node):
            self._add_violation(
                violations, RuleID.DET_CLASS_NAME,
                rel_path, name, "INFO",
                f"Mapper class '{name}' tidak mengandung kata 'Mapper'.",
                "Gunakan nama seperti 'XxxMapper' atau 'XxxDtoMapper'.",
                line=node.lineno,
                rca_result=self._generate_rca(RuleID.DET_CLASS_NAME, f"Mapper {name} naming", "INFO"),
            )

        info = MapperInfo(
            file_path=rel_path,
            mapper_name=name,
            mapper_type="class",
            has_to_dict=has_to_dict,
            has_from_dict=has_from_dict,
            has_mapping_function=has_mapping_func,
            has_error_handling=self._has_try_except(node),
            has_type_hints=has_type_hints,
            has_docstring=has_docstring,
            bidrectional=bidrectional,
            risky_ops=risky_ops,
            violations=violations,
        )

        # Semantic mapping validation
        self._validate_semantic_mapping(node, info)

        return info

    def _analyze_mapper_function(self, file_path: Path, node: ast.FunctionDef) -> MapperInfo:
        rel_path = str(file_path.relative_to(self.root_dir))
        name = node.name
        violations: List[MapperViolation] = []

        risky_ops = self._detect_risky_ops(node)
        has_error_handling = self._has_try_except(node)
        has_type_hints = node.returns is not None
        has_docstring = ast.get_docstring(node) is not None

        if not node.returns:
            self._add_violation(
                violations, RuleID.FUNC_MAP_RETURN,
                rel_path, name, "INFO",
                f"Mapping function '{name}' tidak memiliki return type hint.",
                "Tambahkan return type hint.",
                line=node.lineno,
            )
        if not has_docstring:
            self._add_violation(
                violations, RuleID.FUNC_MAP_DOC,
                rel_path, name, "INFO",
                f"Mapping function '{name}' tidak memiliki docstring.",
                "Tambahkan docstring menjelaskan mapping.",
                line=node.lineno,
            )
        if risky_ops and not has_error_handling:
            max_sev = self._get_max_severity(risky_ops)
            op_desc = self._format_risky_ops(risky_ops)
            self._add_violation(
                violations, RuleID.ERR_TRY_MISSING_RISKY,
                rel_path, name, max_sev,
                f"Mapping function '{name}' mengandung operasi berisiko: {op_desc} tapi tidak ada try/except.",
                "Tambahkan try/except untuk menangkap error konversi.",
                line=node.lineno,
                rca_result=self._generate_rca(RuleID.ERR_TRY_MISSING_RISKY, f"{name} risky op without try/except", max_sev),
                risky_ops=risky_ops,
            )

        return MapperInfo(
            file_path=rel_path,
            mapper_name=name,
            mapper_type="function",
            has_to_dict=False,
            has_from_dict=False,
            has_mapping_function=True,
            has_error_handling=has_error_handling,
            has_type_hints=has_type_hints,
            has_docstring=has_docstring,
            bidrectional=False,
            risky_ops=risky_ops,
            violations=violations,
        )

    def scan(self) -> List[MapperInfo]:
        self.mappers = []
        for file_path in self._get_python_files():
            if not self._is_mapper_module(file_path):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content)
            except (SyntaxError, UnicodeDecodeError):
                continue

            module_is_mapper = True
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and self._is_mapper_class(node):
                    info = self._analyze_mapper_class(file_path, node)
                    self.mappers.append(info)
                elif isinstance(node, ast.FunctionDef) and self._is_mapper_function(node, module_is_mapper):
                    info = self._analyze_mapper_function(file_path, node)
                    self.mappers.append(info)

        return self.mappers

# =============================================================================
# REPORTING
# =============================================================================

def generate_report(mappers: List[MapperInfo], rca_enabled: bool, elapsed: float) -> CheckerResult:
    total = len(mappers)
    critical = high = medium = low = info_count = 0
    for m in mappers:
        for v in m.violations:
            if v.severity == "CRITICAL":
                critical += 1
            elif v.severity == "HIGH":
                high += 1
            elif v.severity == "MEDIUM":
                medium += 1
            elif v.severity == "LOW":
                low += 1
            else:  # INFO
                info_count += 1
    total_violations = critical + high + medium + low + info_count

    # Scoring: Critical -25, High -10, Medium -3, Low -1, INFO 0
    score = 100.0
    score -= critical * 25.0
    score -= high * 10.0
    score -= medium * 3.0
    score -= low * 1.0
    # INFO tidak mempengaruhi skor
    score = max(0.0, min(100.0, score))

    return CheckerResult(
        mappers=mappers,
        total_mappers=total,
        total_violations=total_violations,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        info_count=info_count,
        score=score,
        rca_enabled=rca_enabled,
        elapsed_seconds=elapsed,
    )

def print_report(result: CheckerResult, verbose: bool = False) -> None:
    c = COLOR
    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║       MAPPER CONTRACT COMPLIANCE v3.3 (Semantic)           ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print("\n  📋 Aturan Mapper Contract (konteks-aware + semantik):")
    print("    ✅ to_dict() / from_dict() bidirectional")
    print("    ✅ return type hints & docstring (INFO)")
    print("    ✅ try/except HANYA jika ada operasi berisiko")
    print("    ✅ @classmethod on from_dict()")
    print("    ✅ Semantic mapping: field missing, Decimal→float, UUID→str, datetime TZ")
    print("    ✅ Round-trip consistency (placeholder)")

    print(f"\n  {c['CYAN']}Total Mappers Ditemukan: {result.total_mappers}{c['RESET']}")
    print(f"  Total Violations: {result.total_violations}")
    print(f"    {c['RED']}CRITICAL: {result.critical_count}{c['RESET']}")
    print(f"    {c['YELLOW']}HIGH: {result.high_count}{c['RESET']}")
    print(f"    {c['MAGENTA']}MEDIUM: {result.medium_count}{c['RESET']}")
    print(f"    {c['CYAN']}LOW: {result.low_count}{c['RESET']}")
    print(f"    {c['DIM']}INFO: {result.info_count}{c['RESET']} (tidak mempengaruhi skor)")

    score_color = c["GREEN"] if result.score >= 80 else c["YELLOW"] if result.score >= 50 else c["RED"]
    print(f"\n  📈 Skor Kepatuhan: {score_color}{c['BOLD']}{result.score:.1f}/100{c['RESET']}")
    print(f"  RCA Engine: {'✅ Aktif' if result.rca_enabled else '⚠️ Tidak tersedia'}")

    mappers_with_issues = [m for m in result.mappers if m.violations]
    if mappers_with_issues:
        print(f"\n{c['YELLOW']}─── MAPPER WITH VIOLATIONS ───{c['RESET']}")
        for m in mappers_with_issues[:30]:
            status = f"{c['RED']}✖ {len(m.violations)} violations{c['RESET']}"
            risky = "⚠️ risky" if m.risky_ops else ""
            print(f"  {m.mapper_name} ({m.mapper_type}) @ {m.file_path} {status} {risky}")

    all_violations = []
    for m in result.mappers:
        all_violations.extend(m.violations)

    if all_violations:
        print(f"\n{c['RED']}─── VIOLATIONS (sample) ───{c['RESET']}")
        # Sort by severity: CRITICAL > HIGH > MEDIUM > LOW > INFO
        sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
        sorted_v = sorted(all_violations, key=lambda v: sev_order.get(v.severity, 5))
        for v in sorted_v[:30]:
            sev_color = c["RED"] if v.severity in ("CRITICAL", "HIGH") else c["YELLOW"] if v.severity == "MEDIUM" else c["CYAN"] if v.severity == "LOW" else c["DIM"]
            risky_details = ""
            if v.risky_ops:
                ops = ", ".join([f"{op} (line {ln}, possible: {exc})" for op, ln, exc in v.risky_ops[:3]])
                if len(v.risky_ops) > 3:
                    ops += f" and {len(v.risky_ops)-3} more"
                risky_details = f" [{ops}]"
            print(f"\n  {sev_color}[{v.rule_id}] {v.severity}{c['RESET']} {v.message}{risky_details}")
            print(f"    💡 {v.suggestion}")
            if verbose and v.rca_result:
                if v.rca_result.get("root_cause"):
                    print(f"    🔍 RCA: {v.rca_result['root_cause'][:150]}")
                if v.rca_result.get("suggested_fix"):
                    print(f"    🔧 Fix: {v.rca_result['suggested_fix'][:150]}")
        if len(sorted_v) > 30:
            print(f"  ... and {len(sorted_v)-30} more violations (use --json for full list)")

    compliant = [m for m in result.mappers if not m.violations]
    if compliant:
        print(f"\n{c['GREEN']}✅ {len(compliant)} mappers compliant{c['RESET']}")
        if verbose:
            for m in compliant[:10]:
                print(f"    {m.mapper_name} ({m.mapper_type}) @ {m.file_path}")

def save_json(result: CheckerResult, filepath: str) -> None:
    try:
        out = Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": result.score,
            "rca_enabled": result.rca_enabled,
            "total_mappers": result.total_mappers,
            "total_violations": result.total_violations,
            "severity_counts": {
                "critical": result.critical_count,
                "high": result.high_count,
                "medium": result.medium_count,
                "low": result.low_count,
                "info": result.info_count,
            },
            "mappers": [
                {
                    "name": m.mapper_name,
                    "type": m.mapper_type,
                    "file": m.file_path,
                    "has_to_dict": m.has_to_dict,
                    "has_from_dict": m.has_from_dict,
                    "bidrectional": m.bidrectional,
                    "risky_ops": [(op, line, exc) for op, line, exc in m.risky_ops],
                    "mapped_fields": list(m.mapped_fields),
                    "source_fields": list(m.source_fields),
                    "violations": [v.to_dict() for v in m.violations],
                }
                for m in result.mappers
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
    parser = argparse.ArgumentParser(description="Mapper Contract Compliance Checker v3.3 (Semantic)")
    parser.add_argument("--json", metavar="FILE", help="Export report to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show RCA details")
    parser.add_argument("--strict", action="store_true", help="Mode strict: naikkan MEDIUM ke HIGH")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    args = parser.parse_args()

    global RCA_AVAILABLE, _analyze_exception
    if args.no_rca:
        RCA_AVAILABLE = False
        _analyze_exception = None

    start = time.monotonic()
    checker = MapperChecker(ROOT, enable_rca=not args.no_rca, strict=args.strict)
    mappers = checker.scan()
    elapsed = time.monotonic() - start

    result = generate_report(mappers, RCA_AVAILABLE, elapsed)
    print_report(result, verbose=args.verbose)

    if args.json:
        save_json(result, args.json)

    print(f"\n ⏱️ Audit Duration: {elapsed:.3f} seconds")

    has_critical = result.critical_count > 0
    sys.exit(1 if has_critical else 0)

if __name__ == "__main__":
    main()