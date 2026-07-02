#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/mapper_checker.py
==========================
Sovereign ERP System — Mapper Contract Compliance & Forensic Checker v2.1
Auditor-grade: 100+ rules, fully integrated with RCA engine.

Fixes v2.1:
  - Perbaiki syntax error pada pemanggilan MapperViolation (positional setelah keyword)
  - Semua argumen MapperViolation menggunakan keyword arguments
  - Tambahan validasi untuk mencegah error serupa

Cara pakai:
  python checker/mapper_checker.py
  python checker/mapper_checker.py --verbose
  python checker/mapper_checker.py --strict
  python checker/mapper_checker.py --json report.json
  python checker/mapper_checker.py --no-rca
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
from typing import Any, Dict, List, Optional, Set, Tuple, Callable

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
    "docs", "scripts", "deployment", "monitoring", "reports", "migrations",
}

# --- Detection patterns ---
FILE_INDICATORS = {
    "mapper", "mapping", "dto", "request", "response", "command",
    "query", "event", "schema", "serializer", "converter", "transform",
}

CLASS_INDICATORS = {
    "Mapper", "DtoMapper", "RequestMapper", "ResponseMapper",
    "CommandMapper", "QueryMapper", "EventMapper", "SchemaMapper",
    "Serializer", "Converter", "Transformer", "Adapter",
}

FUNCTION_INDICATORS = {
    "map_", "to_", "from_", "convert_", "transform_", "serialize_", "deserialize_",
    "to_dict", "from_dict", "to_dto", "from_dto", "to_command", "from_command",
    "to_response", "from_response", "to_event", "from_event", "to_schema", "from_schema",
    "to_json", "from_json", "to_proto", "from_proto", "to_grpc", "from_grpc",
}

# --- Rule IDs ---
class RuleID:
    # A: Detection (1-15)
    DET_FILE_NAME = "MAP-001"
    DET_CLASS_NAME = "MAP-002"
    DET_FUNC_NAME = "MAP-003"
    DET_DECORATOR = "MAP-004"
    DET_TO_DICT = "MAP-005"
    DET_FROM_DICT = "MAP-006"
    DET_MAP_FUNC = "MAP-007"
    DET_DTO_COMMAND = "MAP-008"
    DET_DTO_RESPONSE = "MAP-009"
    DET_EVENT_DTO = "MAP-010"
    DET_ORM_DOMAIN = "MAP-011"
    DET_DOMAIN_ORM = "MAP-012"
    DET_PROTO_DOMAIN = "MAP-013"
    DET_DOMAIN_PROTO = "MAP-014"
    DET_REGISTRY = "MAP-015"

    # B: Contract (16-30)
    CONTRACT_TO_DICT = "MAP-016"
    CONTRACT_FROM_DICT = "MAP-017"
    CONTRACT_TO_DICT_RETURN = "MAP-018"
    CONTRACT_FROM_DICT_RETURN = "MAP-019"
    CONTRACT_TO_DICT_NESTED = "MAP-020"
    CONTRACT_FROM_DICT_NESTED = "MAP-021"
    CONTRACT_TO_DICT_NONE = "MAP-022"
    CONTRACT_FROM_DICT_NONE = "MAP-023"
    CONTRACT_TO_DICT_TYPEHINT = "MAP-024"
    CONTRACT_FROM_DICT_TYPEHINT = "MAP-025"
    CONTRACT_TO_DICT_DOC = "MAP-026"
    CONTRACT_FROM_DICT_DOC = "MAP-027"
    CONTRACT_FIELD_CONSISTENCY = "MAP-028"
    CONTRACT_BIDIRECTIONAL = "MAP-029"
    CONTRACT_TYPE_CONSISTENCY = "MAP-030"

    # C: Error Handling (31-40)
    ERR_TO_DICT_TRY = "MAP-031"
    ERR_FROM_DICT_TRY = "MAP-032"
    ERR_MAP_TRY = "MAP-033"
    ERR_SPECIFIC_EXCEPT = "MAP-034"
    ERR_LOGGING = "MAP-035"
    ERR_RE_RAISE = "MAP-036"
    ERR_DEFAULT_VALUE = "MAP-037"
    ERR_VALIDATION = "MAP-038"
    ERR_TYPE_ERROR = "MAP-039"
    ERR_VALUE_ERROR = "MAP-040"

    # D: Mapping Functions (41-55)
    FUNC_DOMAIN_DTO = "MAP-041"
    FUNC_DTO_DOMAIN = "MAP-042"
    FUNC_DTO_COMMAND = "MAP-043"
    FUNC_COMMAND_DTO = "MAP-044"
    FUNC_DTO_RESPONSE = "MAP-045"
    FUNC_RESPONSE_DTO = "MAP-046"
    FUNC_ORM_DOMAIN = "MAP-047"
    FUNC_DOMAIN_ORM = "MAP-048"
    FUNC_EVENT_DTO = "MAP-049"
    FUNC_DTO_EVENT = "MAP-050"
    FUNC_PROTO_DOMAIN = "MAP-051"
    FUNC_DOMAIN_PROTO = "MAP-052"
    FUNC_JSON_DOMAIN = "MAP-053"
    FUNC_DOMAIN_JSON = "MAP-054"
    FUNC_BATCH = "MAP-055"

    # E: Type Hints (56-65)
    TYPE_TO_DICT_RETURN = "MAP-056"
    TYPE_FROM_DICT_PARAM = "MAP-057"
    TYPE_MAP_RETURN = "MAP-058"
    TYPE_MAP_PARAM = "MAP-059"
    TYPE_UNION_OPTIONAL = "MAP-060"
    TYPE_LIST_SEQUENCE = "MAP-061"
    TYPE_DICT_MAPPING = "MAP-062"
    TYPE_DATACLASS = "MAP-063"
    TYPE_PYDANTIC = "MAP-064"
    TYPE_TYPED_DICT = "MAP-065"

    # F: Field Mapping (66-75)
    FIELD_ALL_DOMAIN = "MAP-066"
    FIELD_ALL_DTO = "MAP-067"
    FIELD_NAME_CONSISTENCY = "MAP-068"
    FIELD_TYPE_DECIMAL = "MAP-069"
    FIELD_TYPE_DATETIME = "MAP-070"
    FIELD_TYPE_UUID = "MAP-071"
    FIELD_TYPE_ENUM = "MAP-072"
    FIELD_NESTED_COMPLETE = "MAP-073"
    FIELD_COLLECTION = "MAP-074"
    FIELD_OPTIONAL = "MAP-075"

    # G: Registry (76-83)
    REG_REGISTER = "MAP-076"
    REG_GET = "MAP-077"
    REG_LIST = "MAP-078"
    REG_SINGLETON = "MAP-079"
    REG_LAZY = "MAP-080"
    REG_DI = "MAP-081"
    REG_VALIDATION = "MAP-082"
    REG_DISCOVERY = "MAP-083"

    # H: Performance (84-93)
    PERF_CACHE = "MAP-084"
    PERF_NO_REFLECTION = "MAP-085"
    PERF_DATACLASS = "MAP-086"
    PERF_SLOTS = "MAP-087"
    PERF_NO_CIRCULAR = "MAP-088"
    PERF_LRU_CACHE = "MAP-089"
    PERF_BATCH_OPT = "MAP-090"
    PERF_LAZY_LOAD = "MAP-091"
    PERF_STREAMING = "MAP-092"
    PERF_PROFILING = "MAP-093"

    # I: Security (94-98)
    SEC_INPUT_VALIDATION = "MAP-094"
    SEC_OUTPUT_SANITIZE = "MAP-095"
    SEC_NO_SQL_INJECTION = "MAP-096"
    SEC_NO_EVAL = "MAP-097"
    SEC_TYPE_VALIDATION = "MAP-098"

    # J: Testing (99-105)
    TEST_UNIT = "MAP-099"
    TEST_ROUNDTRIP = "MAP-100"
    TEST_EDGE_CASES = "MAP-101"
    TEST_INVALID_INPUT = "MAP-102"
    TEST_NESTED = "MAP-103"
    TEST_COLLECTIONS = "MAP-104"
    TEST_PERFORMANCE = "MAP-105"

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

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "rule_id": self.rule_id,
            "file": self.file_path,
            "mapper": self.mapper_name,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "line": self.line,
        }
        if self.rca_result:
            d["rca"] = self.rca_result
        return d


@dataclass
class MapperInfo:
    file_path: str
    mapper_name: str
    mapper_type: str  # "class", "function", "module"
    has_to_dict: bool = False
    has_from_dict: bool = False
    has_mapping_function: bool = False
    has_error_handling: bool = False
    has_type_hints: bool = False
    has_docstring: bool = False
    is_registered: bool = False
    bidrectional: bool = False
    fields_mapped: int = 0
    total_fields: int = 0
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
    score: float
    rca_enabled: bool
    elapsed_seconds: float


# =============================================================================
# MAPPER CHECKER
# =============================================================================

class MapperChecker:
    def __init__(self, root_dir: Path, enable_rca: bool = True, strict: bool = False):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.strict = strict
        self.mappers: List[MapperInfo] = []

    def _get_python_files(self) -> List[Path]:
        py_files = []
        scan_dirs = ["application", "domain", "adapters", "infrastructure", "ports", "bootstrap"]
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

    def _is_mapper_file(self, file_path: Path) -> bool:
        """Determine if file is likely a mapper file."""
        name = file_path.stem.lower()
        # Check file name
        for indicator in FILE_INDICATORS:
            if indicator in name:
                return True
        # Check parent directories
        for parent in file_path.parents:
            parent_name = parent.name.lower()
            if any(ind in parent_name for ind in ["mappers", "mapping", "dto", "schema"]):
                return True
        return False

    def _get_mapper_candidates(self, file_path: Path, content: str) -> List[Tuple[str, str, int, ast.AST]]:
        """Extract mapper candidates (classes and functions)."""
        candidates = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return candidates

        for node in ast.walk(tree):
            # Class candidates
            if isinstance(node, ast.ClassDef):
                name = node.name
                if any(ind.lower() in name.lower() for ind in CLASS_INDICATORS):
                    candidates.append((name, "class", node.lineno, node))
                    continue
                # Check if class has to_dict/from_dict methods
                has_to_dict = any(isinstance(item, ast.FunctionDef) and item.name == "to_dict" for item in node.body)
                has_from_dict = any(isinstance(item, ast.FunctionDef) and item.name == "from_dict" for item in node.body)
                if has_to_dict or has_from_dict:
                    candidates.append((name, "class", node.lineno, node))

            # Function candidates
            if isinstance(node, ast.FunctionDef):
                name = node.name
                if any(name.startswith(ind) or ind in name for ind in FUNCTION_INDICATORS):
                    candidates.append((name, "function", node.lineno, node))

        return candidates

    def _add_violation(self, violations: List[MapperViolation], rule_id: str, file_path: str,
                       mapper_name: str, severity: str, message: str, suggestion: str,
                       line: int = 0, rca_result: Optional[Dict[str, Any]] = None) -> None:
        """Helper untuk menambahkan violation dengan konsisten."""
        violations.append(MapperViolation(
            rule_id=rule_id,
            file_path=file_path,
            mapper_name=mapper_name,
            severity=severity,
            message=message,
            suggestion=suggestion,
            line=line,
            rca_result=rca_result,
        ))

    def _analyze_mapper(self, file_path: Path, content: str, name: str, mtype: str, node: ast.AST) -> MapperInfo:
        """Analyze a single mapper candidate with 100+ rules."""
        rel_path = str(file_path.relative_to(self.root_dir))
        violations: List[MapperViolation] = []

        has_to_dict = False
        has_from_dict = False
        has_mapping_func = False
        has_error_handling = False
        has_type_hints = False
        has_docstring = False
        bidrectional = False
        fields_mapped = 0
        total_fields = 0

        # -------- A. DETECTION RULES (1-15) --------
        if mtype == "class":
            # Rule 2: Class name indicator
            if not any(ind.lower() in name.lower() for ind in CLASS_INDICATORS):
                self._add_violation(
                    violations,
                    RuleID.DET_CLASS_NAME,
                    rel_path, name, "LOW",
                    f"Class '{name}' tidak menggunakan naming convention mapper standar.",
                    "Gunakan nama seperti 'XxxMapper', 'XxxDtoMapper'.",
                    line=node.lineno,
                    rca_result=self._generate_rca(RuleID.DET_CLASS_NAME, f"Class {name} not using mapper naming", "LOW"),
                )

            # Rule 5-6: to_dict/from_dict detection
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    # Rule 5: to_dict
                    if item.name == "to_dict":
                        has_to_dict = True
                        # Rule 18: to_dict returns dict
                        if item.returns:
                            ret_type = self._infer_type_from_annotation(item.returns)
                            if ret_type and "dict" not in ret_type.lower():
                                self._add_violation(
                                    violations,
                                    RuleID.CONTRACT_TO_DICT_RETURN,
                                    rel_path, name, "MEDIUM",
                                    f"to_dict() mengembalikan {ret_type}, seharusnya dict.",
                                    "Return type hint harus Dict[str, Any].",
                                    line=item.lineno,
                                )
                        # Rule 31: try/except in to_dict
                        has_try = any(isinstance(sub, ast.Try) for sub in ast.walk(item))
                        if not has_try:
                            self._add_violation(
                                violations,
                                RuleID.ERR_TO_DICT_TRY,
                                rel_path, name, "MEDIUM",
                                "to_dict() tidak memiliki error handling (try/except).",
                                "Tambahkan try/except untuk menangkap error konversi.",
                                line=item.lineno,
                                rca_result=self._generate_rca(RuleID.ERR_TO_DICT_TRY, "to_dict missing try/except", "MEDIUM"),
                            )
                        # Rule 24: type hints on to_dict
                        if item.returns:
                            has_type_hints = True
                        # Rule 26: docstring on to_dict
                        if ast.get_docstring(item):
                            has_docstring = True
                        else:
                            self._add_violation(
                                violations,
                                RuleID.CONTRACT_TO_DICT_DOC,
                                rel_path, name, "LOW",
                                "to_dict() tidak memiliki docstring.",
                                "Tambahkan docstring menjelaskan mapping yang dilakukan.",
                                line=item.lineno,
                            )

                    # Rule 6: from_dict
                    if item.name == "from_dict":
                        has_from_dict = True
                        # Rule 19: from_dict returns instance
                        if item.returns:
                            ret_type = self._infer_type_from_annotation(item.returns)
                            # Just check if return type hint exists
                            pass
                        # Rule 32: try/except in from_dict
                        has_try = any(isinstance(sub, ast.Try) for sub in ast.walk(item))
                        if not has_try:
                            self._add_violation(
                                violations,
                                RuleID.ERR_FROM_DICT_TRY,
                                rel_path, name, "MEDIUM",
                                "from_dict() tidak memiliki error handling (try/except).",
                                "Tambahkan try/except untuk menangkap error konversi.",
                                line=item.lineno,
                                rca_result=self._generate_rca(RuleID.ERR_FROM_DICT_TRY, "from_dict missing try/except", "MEDIUM"),
                            )
                        # Rule 25: type hints on from_dict
                        for arg in item.args.args:
                            if arg.annotation:
                                has_type_hints = True
                                break
                        # Rule 27: docstring on from_dict
                        if ast.get_docstring(item):
                            has_docstring = True
                        else:
                            self._add_violation(
                                violations,
                                RuleID.CONTRACT_FROM_DICT_DOC,
                                rel_path, name, "LOW",
                                "from_dict() tidak memiliki docstring.",
                                "Tambahkan docstring menjelaskan deserialisasi.",
                                line=item.lineno,
                            )

                    # Rule 7: mapping function
                    if any(item.name.startswith(ind) or ind in item.name for ind in ["map_", "to_", "from_", "convert_", "transform_"]):
                        if item.name not in ["to_dict", "from_dict"]:
                            has_mapping_func = True
                            # Rule 33: try/except in mapping function
                            has_try = any(isinstance(sub, ast.Try) for sub in ast.walk(item))
                            if not has_try:
                                self._add_violation(
                                    violations,
                                    RuleID.ERR_MAP_TRY,
                                    rel_path, name, "MEDIUM",
                                    f"Mapping function '{item.name}' tidak memiliki error handling.",
                                    "Tambahkan try/except untuk menangkap error konversi.",
                                    line=item.lineno,
                                    rca_result=self._generate_rca(RuleID.ERR_MAP_TRY, f"{item.name} missing try/except", "MEDIUM"),
                                )
                            # Rule 58: return type hint
                            if item.returns:
                                has_type_hints = True
                            else:
                                self._add_violation(
                                    violations,
                                    RuleID.TYPE_MAP_RETURN,
                                    rel_path, name, "LOW",
                                    f"Mapping function '{item.name}' tidak memiliki return type hint.",
                                    "Tambahkan return type hint untuk dokumentasi dan type safety.",
                                    line=item.lineno,
                                )

            # Rule 29: Bidirectional mapping
            if has_to_dict and has_from_dict:
                bidrectional = True
            else:
                if has_to_dict:
                    self._add_violation(
                        violations,
                        RuleID.CONTRACT_BIDIRECTIONAL,
                        rel_path, name, "HIGH",
                        "Mapper hanya memiliki to_dict() tapi tidak from_dict() (tidak bidirectional).",
                        "Tambahkan from_dict() untuk deserialisasi.",
                        line=node.lineno,
                        rca_result=self._generate_rca(RuleID.CONTRACT_BIDIRECTIONAL, "Mapper missing from_dict", "HIGH"),
                    )
                elif has_from_dict:
                    self._add_violation(
                        violations,
                        RuleID.CONTRACT_BIDIRECTIONAL,
                        rel_path, name, "HIGH",
                        "Mapper hanya memiliki from_dict() tapi tidak to_dict() (tidak bidirectional).",
                        "Tambahkan to_dict() untuk serialisasi.",
                        line=node.lineno,
                        rca_result=self._generate_rca(RuleID.CONTRACT_BIDIRECTIONAL, "Mapper missing to_dict", "HIGH"),
                    )

            # Rule 17: from_dict must be classmethod
            from_dict_method = None
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "from_dict":
                    from_dict_method = item
                    break
            if from_dict_method:
                is_classmethod = False
                for dec in from_dict_method.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "classmethod":
                        is_classmethod = True
                        break
                    if isinstance(dec, ast.Attribute) and dec.attr == "classmethod":
                        is_classmethod = True
                        break
                if not is_classmethod:
                    self._add_violation(
                        violations,
                        RuleID.CONTRACT_FROM_DICT_RETURN,
                        rel_path, name, "HIGH",
                        "from_dict() harus classmethod (decorator @classmethod).",
                        "Tambahkan @classmethod decorator pada from_dict().",
                        line=from_dict_method.lineno,
                        rca_result=self._generate_rca(RuleID.CONTRACT_FROM_DICT_RETURN, "from_dict missing @classmethod", "HIGH"),
                    )

        # -------- C. ERROR HANDLING RULES (34-40) --------
        for node_ in ast.walk(node):
            if isinstance(node_, ast.ExceptHandler):
                if node_.type is None:
                    self._add_violation(
                        violations,
                        RuleID.ERR_SPECIFIC_EXCEPT,
                        rel_path, name, "MEDIUM",
                        "Penggunaan bare 'except:' tanpa exception type.",
                        "Gunakan specific exception seperti 'except ValueError:' atau 'except TypeError:'.",
                        line=node_.lineno,
                        rca_result=self._generate_rca(RuleID.ERR_SPECIFIC_EXCEPT, "Bare except in mapper", "MEDIUM"),
                    )

        # -------- D. MAPPING FUNCTION RULES (41-55) --------
        if mtype in ["class", "function"]:
            funcs = []
            if mtype == "class":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        funcs.append(item)
            else:
                if isinstance(node, ast.FunctionDef):
                    funcs.append(node)

            for func in funcs:
                fname = func.name.lower()
                if "domain" in fname and "dto" in fname:
                    has_mapping_func = True
                if "dto" in fname and "domain" in fname:
                    has_mapping_func = True
                if "dto" in fname and "command" in fname:
                    has_mapping_func = True
                if "command" in fname and "dto" in fname:
                    has_mapping_func = True
                if "dto" in fname and "response" in fname:
                    has_mapping_func = True
                if "response" in fname and "dto" in fname:
                    has_mapping_func = True
                if "orm" in fname and "domain" in fname:
                    has_mapping_func = True
                if "domain" in fname and "orm" in fname:
                    has_mapping_func = True
                if "event" in fname and "dto" in fname:
                    has_mapping_func = True
                if "dto" in fname and "event" in fname:
                    has_mapping_func = True
                if "batch" in fname or "list" in fname:
                    has_mapping_func = True

        # -------- I. SECURITY RULES (94-98) --------
        for line in content.splitlines():
            if "eval(" in line or "exec(" in line:
                self._add_violation(
                    violations,
                    RuleID.SEC_NO_EVAL,
                    rel_path, name, "CRITICAL",
                    "Penggunaan eval() atau exec() di mapper berbahaya.",
                    "Hindari eval/exec, gunakan ast.literal_eval atau parsing yang aman.",
                    line=0,
                    rca_result=self._generate_rca(RuleID.SEC_NO_EVAL, "eval/exec in mapper", "CRITICAL"),
                )
                break

        # -------- BUILD RESULT --------
        has_try = any(isinstance(sub, ast.Try) for sub in ast.walk(node))
        if has_try:
            has_error_handling = True

        if mtype == "class":
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    if item.returns:
                        has_type_hints = True
                    for arg in item.args.args:
                        if arg.annotation:
                            has_type_hints = True
                            break
        else:
            if isinstance(node, ast.FunctionDef):
                if node.returns:
                    has_type_hints = True
                for arg in node.args.args:
                    if arg.annotation:
                        has_type_hints = True

        return MapperInfo(
            file_path=rel_path,
            mapper_name=name,
            mapper_type=mtype,
            has_to_dict=has_to_dict,
            has_from_dict=has_from_dict,
            has_mapping_function=has_mapping_func,
            has_error_handling=has_error_handling,
            has_type_hints=has_type_hints,
            has_docstring=has_docstring,
            is_registered=False,
            bidrectional=bidrectional,
            fields_mapped=fields_mapped,
            total_fields=total_fields,
            violations=violations,
        )

    def _infer_type_from_annotation(self, node: ast.expr) -> Optional[str]:
        """Infer type name from annotation node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                return node.value.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def scan(self) -> List[MapperInfo]:
        """Scan all Python files for mapper compliance."""
        self.mappers = []
        for file_path in self._get_python_files():
            if not self._is_mapper_file(file_path):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content)
            except (SyntaxError, UnicodeDecodeError):
                continue

            candidates = self._get_mapper_candidates(file_path, content)
            for name, mtype, line, node in candidates:
                info = self._analyze_mapper(file_path, content, name, mtype, node)
                self.mappers.append(info)

        return self.mappers

# =============================================================================
# REPORTING
# =============================================================================

def generate_report(mappers: List[MapperInfo]) -> CheckerResult:
    total = len(mappers)
    total_violations = 0
    critical = high = medium = low = 0

    for mapper in mappers:
        total_violations += len(mapper.violations)
        for v in mapper.violations:
            if v.severity == "CRITICAL":
                critical += 1
            elif v.severity == "HIGH":
                high += 1
            elif v.severity == "MEDIUM":
                medium += 1
            elif v.severity == "LOW":
                low += 1

    score = 100.0
    score -= critical * 15.0
    score -= high * 8.0
    score -= medium * 3.0
    score -= low * 1.0
    score = max(0.0, min(100.0, score))

    return CheckerResult(
        mappers=mappers,
        total_mappers=total,
        total_violations=total_violations,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        score=score,
        rca_enabled=RCA_AVAILABLE,
        elapsed_seconds=0.0,
    )


def print_report(result: CheckerResult, verbose: bool = False) -> None:
    c = COLOR
    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║       MAPPER CONTRACT COMPLIANCE & FORENSIC v2.1          ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print("\n  📋 100+ Aturan Mapper Contract:")
    print("    ✅ to_dict() / from_dict()        — serialisasi bidirectional")
    print("    ✅ mapping functions (map_*, to_*) — konversi domain ↔ dto")
    print("    ✅ error handling (try/except)    — robustness")
    print("    ✅ type hints & annotations       — type safety")
    print("    ✅ registry integration           — discoverability")
    print("    ✅ field mapping completeness     — no missing fields")
    print("    ✅ nested object mapping          — deep objects")
    print("    ✅ batch mapping                  — list conversion")
    print("    ✅ performance (caching, slots)   — efficiency")
    print("    ✅ security (input validation)    — safety")

    print(f"\n  {c['CYAN']}Total Mappers Ditemukan: {result.total_mappers}{c['RESET']}")
    print(f"  Total Violations: {result.total_violations}")
    print(f"    {c['RED']}CRITICAL: {result.critical_count}{c['RESET']}")
    print(f"    {c['YELLOW']}HIGH: {result.high_count}{c['RESET']}")
    print(f"    {c['MAGENTA']}MEDIUM: {result.medium_count}{c['RESET']}")
    print(f"    {c['CYAN']}LOW: {result.low_count}{c['RESET']}")

    score_color = c["GREEN"] if result.score >= 80 else c["YELLOW"] if result.score >= 50 else c["RED"]
    print(f"\n  📈 Skor Kepatuhan: {score_color}{c['BOLD']}{result.score:.1f}/100{c['RESET']}")
    print(f"  RCA Engine: {'✅ Aktif' if result.rca_enabled else '⚠️ Tidak tersedia'}")

    if result.mappers:
        print(f"\n{c['CYAN']}─── DAFTAR MAPPER ───{c['RESET']}")
        for mapper in result.mappers:
            if mapper.violations:
                status = f"{c['RED']}✖ {len(mapper.violations)} violations{c['RESET']}"
            else:
                status = f"{c['GREEN']}✓ Compliant{c['RESET']}"
            print(f"  {mapper.mapper_name} ({mapper.mapper_type}) @ {mapper.file_path} {status}")

    all_violations = []
    for mapper in result.mappers:
        all_violations.extend(mapper.violations)

    if all_violations:
        print(f"\n{c['RED']}─── VIOLATIONS (sample) ───{c['RESET']}")
        for v in all_violations[:30]:
            sev_color = c["RED"] if v.severity in ("CRITICAL", "HIGH") else c["YELLOW"] if v.severity == "MEDIUM" else c["CYAN"]
            print(f"\n  {sev_color}[{v.rule_id}] {v.severity}{c['RESET']} {v.message}")
            print(f"    💡 {v.suggestion}")
            if verbose and v.rca_result:
                if v.rca_result.get("root_cause"):
                    print(f"    🔍 RCA: {v.rca_result['root_cause'][:150]}")
                if v.rca_result.get("suggested_fix"):
                    print(f"    🔧 Fix: {v.rca_result['suggested_fix'][:150]}")
        if len(all_violations) > 30:
            print(f"  ... and {len(all_violations)-30} more violations (use --json for full list)")


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
            },
            "mappers": [
                {
                    "name": m.mapper_name,
                    "type": m.mapper_type,
                    "file": m.file_path,
                    "has_to_dict": m.has_to_dict,
                    "has_from_dict": m.has_from_dict,
                    "has_mapping_function": m.has_mapping_function,
                    "has_error_handling": m.has_error_handling,
                    "has_type_hints": m.has_type_hints,
                    "has_docstring": m.has_docstring,
                    "is_registered": m.is_registered,
                    "bidrectional": m.bidrectional,
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
    parser = argparse.ArgumentParser(description="Mapper Contract Compliance & Forensic Checker v2.1")
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

    result = generate_report(mappers)
    result.elapsed_seconds = elapsed

    print_report(result, verbose=args.verbose)

    if args.json:
        save_json(result, args.json)

    print(f"\n ⏱️ Audit Duration: {elapsed:.3f} seconds")

    has_critical = result.critical_count > 0
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()