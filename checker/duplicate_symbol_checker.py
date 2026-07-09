#!/usr/bin/env python3
"""
duplicate_symbol_checker.py - Advanced Duplicate Symbol Detector (Final)
=======================================================================
Mendeteksi duplikasi simbol (class, enum, dataclass, dto, dll.) dengan
filter ketat untuk menghindari false positive. Dilengkapi heuristik risiko
untuk membedakan duplikasi yang berbahaya vs yang tidak.

Cara pakai:
  python checker/duplicate_symbol_checker.py
  python checker/duplicate_symbol_checker.py --min-risk MEDIUM
  python checker/duplicate_symbol_checker.py --min-risk HIGH --json report.json
  python checker/duplicate_symbol_checker.py --list-files   # Tampilkan semua file yang discan
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Set, List, Dict, Tuple

# ============================================================
# Warna terminal
# ============================================================
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["MAGENTA"] = colorama.Fore.MAGENTA
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ============================================================
# Tipe simbol
# ============================================================
class SymbolType(str, Enum):
    CLASS = "class"
    ENUM = "enum"
    DATACLASS = "dataclass"
    DTO = "dto"
    TYPEDICT = "typedict"
    PROTOCOL = "protocol"
    EXCEPTION = "exception"
    CONSTANT = "constant"

# ============================================================
# Struktur data
# ============================================================
@dataclass
class MethodInfo:
    name: str
    params: list[str]
    is_async: bool
    lineno: int

@dataclass
class FieldInfo:
    name: str
    type_hint: Optional[str]
    has_default: bool
    lineno: int

@dataclass
class EnumMember:
    name: str
    value: str

@dataclass
class SymbolInfo:
    name: str
    symbol_type: SymbolType
    module: str
    file_path: str
    lineno: int
    fields: list[FieldInfo] = field(default_factory=list)
    methods: list[MethodInfo] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    enum_members: list[EnumMember] = field(default_factory=list)
    is_dataclass: bool = False
    is_pydantic: bool = False
    has_business_methods: bool = False
    value: Optional[str] = None

# ============================================================
# Kelompok duplikat
# ============================================================
@dataclass
class DuplicateGroup:
    symbol_type: SymbolType
    group_key: str
    locations: list[tuple[str, int, str]]
    similarity_score: float
    duplicate_type: str
    risk_severity: str = "LOW"
    risk_explanation: str = ""

@dataclass
class Report:
    duplicate_groups: list[DuplicateGroup] = field(default_factory=list)
    score: int = 100
    summary: dict[str, int] = field(default_factory=dict)
    scanned_files: int = 0
    files_with_symbols: int = 0
    total_symbols: int = 0
    scanned_directories: list[str] = field(default_factory=list)

# ============================================================
# Ekstraksi simbol (sama seperti sebelumnya)
# ============================================================
def extract_symbols_from_file(file_path: pathlib.Path, module: str) -> list[SymbolInfo]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    symbols: list[SymbolInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            sym = _extract_class_symbol(node, module, file_path)
            if sym:
                symbols.append(sym)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    value = None
                    if isinstance(node.value, ast.Constant):
                        value = str(node.value.value)
                    elif isinstance(node.value, ast.Name):
                        value = node.value.id
                    else:
                        value = ast.unparse(node.value)
                    symbols.append(SymbolInfo(
                        name=target.id,
                        symbol_type=SymbolType.CONSTANT,
                        module=module,
                        file_path=str(file_path),
                        lineno=node.lineno,
                        value=value
                    ))
    return symbols

def _extract_class_symbol(node: ast.ClassDef, module: str, file_path: pathlib.Path) -> Optional[SymbolInfo]:
    symbol_type = SymbolType.CLASS
    is_dataclass = False
    is_pydantic = False
    is_enum = False
    is_typeddict = False
    is_protocol = False
    is_exception = False
    bases: list[str] = []

    for base in node.bases:
        base_name = ast.unparse(base).lower()
        bases.append(ast.unparse(base))
        if 'enum' in base_name or base_name in ('enum', 'intenum', 'strenum'):
            is_enum = True
        if 'basemodel' in base_name or 'pydanticmodel' in base_name:
            is_pydantic = True
        if 'typeddict' in base_name:
            is_typeddict = True
        if 'protocol' in base_name:
            is_protocol = True
        if 'exception' in base_name:
            is_exception = True

    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "dataclass":
            is_dataclass = True
        elif isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == "dataclass":
            is_dataclass = True

    methods: list[MethodInfo] = []
    has_business_methods = False
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = [arg.arg for arg in item.args.args if arg.arg not in ('self', 'cls')]
            methods.append(MethodInfo(
                name=item.name,
                params=params,
                is_async=isinstance(item, ast.AsyncFunctionDef),
                lineno=item.lineno
            ))
            if item.name not in ("__init__", "__post_init__", "__repr__", "__eq__", "__hash__", "__str__"):
                has_business_methods = True

    fields: list[FieldInfo] = []
    for item in node.body:
        if isinstance(item, ast.AnnAssign):
            if isinstance(item.target, ast.Name):
                fname = item.target.id
                type_hint = ast.unparse(item.annotation) if item.annotation else None
                fields.append(FieldInfo(
                    name=fname,
                    type_hint=type_hint,
                    has_default=item.value is not None,
                    lineno=item.lineno
                ))
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    fname = target.id
                    type_hint = None
                    if hasattr(item, 'annotation') and item.annotation:
                        type_hint = ast.unparse(item.annotation)
                    fields.append(FieldInfo(
                        name=fname,
                        type_hint=type_hint,
                        has_default=item.value is not None,
                        lineno=item.lineno
                    ))

    if is_enum:
        symbol_type = SymbolType.ENUM
    elif is_typeddict:
        symbol_type = SymbolType.TYPEDICT
    elif is_protocol:
        symbol_type = SymbolType.PROTOCOL
    elif is_exception:
        symbol_type = SymbolType.EXCEPTION
    elif is_dataclass or is_pydantic:
        symbol_type = SymbolType.DATACLASS
    else:
        if not has_business_methods and fields:
            symbol_type = SymbolType.DTO
        else:
            symbol_type = SymbolType.CLASS

    enum_members: list[EnumMember] = []
    if symbol_type == SymbolType.ENUM:
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        value = ""
                        if isinstance(item.value, ast.Constant):
                            value = str(item.value.value)
                        elif isinstance(item.value, ast.Name):
                            value = item.value.id
                        elif isinstance(item.value, ast.Attribute):
                            value = ast.unparse(item.value)
                        else:
                            value = ast.unparse(item.value)
                        enum_members.append(EnumMember(name=target.id, value=value))

    return SymbolInfo(
        name=node.name,
        symbol_type=symbol_type,
        module=module,
        file_path=str(file_path),
        lineno=node.lineno,
        fields=fields,
        methods=methods,
        bases=bases,
        enum_members=enum_members,
        is_dataclass=is_dataclass,
        is_pydantic=is_pydantic,
        has_business_methods=has_business_methods,
    )

# ============================================================
# Fungsi similarity yang lebih detail
# ============================================================
def compute_similarity(s1: SymbolInfo, s2: SymbolInfo) -> float:
    if s1.symbol_type != s2.symbol_type:
        return 0.0

    if s1.symbol_type == SymbolType.CLASS:
        return _similarity_class(s1, s2)
    elif s1.symbol_type in (SymbolType.DATACLASS, SymbolType.DTO, SymbolType.TYPEDICT):
        return _similarity_dto(s1, s2)
    elif s1.symbol_type == SymbolType.ENUM:
        return _similarity_enum(s1, s2)
    elif s1.symbol_type == SymbolType.CONSTANT:
        return _similarity_constant(s1, s2)
    else:
        return _similarity_class(s1, s2)

def _similarity_class(c1: SymbolInfo, c2: SymbolInfo) -> float:
    m1 = {m.name: len(m.params) for m in c1.methods}
    m2 = {m.name: len(m.params) for m in c2.methods}
    common_methods = set(m1.keys()) & set(m2.keys())
    if not common_methods:
        if set(c1.bases) & set(c2.bases):
            return 0.3
        return 0.0
    union_methods = set(m1.keys()) | set(m2.keys())
    jaccard = len(common_methods) / len(union_methods) if union_methods else 0.0
    param_match = sum(1 for m in common_methods if m1[m] == m2[m])
    param_ratio = param_match / len(common_methods) if common_methods else 0.0
    score = 0.6 * jaccard + 0.4 * param_ratio
    if set(c1.bases) & set(c2.bases):
        score = min(1.0, score + 0.1)
    return round(score, 2)

def _similarity_dto(d1: SymbolInfo, d2: SymbolInfo) -> float:
    f1 = {f.name: f.type_hint for f in d1.fields}
    f2 = {f.name: f.type_hint for f in d2.fields}
    if not f1 and not f2:
        return 0.0
    common = set(f1.keys()) & set(f2.keys())
    if not common:
        return 0.0
    union = set(f1.keys()) | set(f2.keys())
    name_sim = len(common) / len(union)
    type_match = sum(1 for name in common if f1.get(name) == f2.get(name))
    type_ratio = type_match / len(common) if common else 0.0
    score = 0.5 * name_sim + 0.3 * type_ratio
    if set(d1.bases) & set(d2.bases):
        score += 0.1
    if d1.has_business_methods or d2.has_business_methods:
        score -= 0.05
    return round(min(1.0, max(0.0, score)), 2)

def _similarity_enum(e1: SymbolInfo, e2: SymbolInfo) -> float:
    m1_names = {m.name for m in e1.enum_members}
    m2_names = {m.name for m in e2.enum_members}
    m1_vals = {m.value for m in e1.enum_members}
    m2_vals = {m.value for m in e2.enum_members}
    name_union = m1_names | m2_names
    name_jaccard = len(m1_names & m2_names) / len(name_union) if name_union else 0.0
    val_union = m1_vals | m2_vals
    val_jaccard = len(m1_vals & m2_vals) / len(val_union) if val_union else 0.0
    score = 0.5 * name_jaccard + 0.5 * val_jaccard
    return round(score, 2)

def _similarity_constant(c1: SymbolInfo, c2: SymbolInfo) -> float:
    if c1.value is not None and c2.value is not None:
        return 1.0 if c1.value == c2.value else 0.0
    return 0.0

# ============================================================
# Daftar white-list
# ============================================================
DEFAULT_IGNORE_NAMES = {
    "PROJECT_ROOT", "COLOR", "ROOT", "T", "EXCLUDED_DIRS", "VERSION",
    "METRIC_PREFIX", "COLLECTION_INTERVAL_SECONDS", "DEFAULT_CONFIG",
    "GENESIS_HASH", "DEFAULT_BATCH_SIZE", "DEFAULT_OUTPUT_DIR",
    "DEFAULT_KEY_LENGTH", "SALT_LENGTH", "ENV_VAR_PATTERN",
    "DEFAULT_MAX_RETRIES", "DEFAULT_RETRY_DELAY_SECONDS",
    "_RCA_ENGINE", "_RCA_AVAILABLE", "RCA_AVAILABLE",
    "SKIP_DIRS", "_THIS_FILE", "_USE_COLOR", "_CACHE_LOCK",
}

IGNORE_PATTERNS = [
    r"^_Fallback.*", r"^_LAZY_.*", r"^_COLOR$", r"^_LOGGER$",
    r"^CACHE_TTL_.*", r"^DEFAULT_.*", r"^HEALTH_.*", r"^ALERT_.*",
    r"^OUTBOX_.*", r"^BACKUP_.*", r"^ARCHIVE_.*", r"^RETENTION_.*",
    r"^SPT_.*", r"^CORETAX_.*", r"^NPWP.*", r"^NTPN.*", r"^NSFP.*",
    r"^TAX_.*", r"^PPH_.*", r"^PPN_.*", r"^BUCKETS$", r"^BATCH_SIZE$",
    r"^PROJECTION_NAME$", r"^SLO_.*", r"^NAMESPACE$", r"^PKP.*",
    r"^MAGIC_.*",
]

def should_ignore_symbol(name: str, symbol_type: SymbolType, ignore_set: Set[str]) -> bool:
    if symbol_type == SymbolType.CONSTANT:
        return True
    if name in ignore_set:
        return True
    for pat in IGNORE_PATTERNS:
        if re.match(pat, name):
            return True
    return False

# ============================================================
# Deteksi duplikat dengan penentuan risiko yang lebih baik
# ============================================================
def find_duplicates(
    symbols: list[SymbolInfo],
    threshold: float = 0.8,
    ignore_constants: bool = True,
    ignore_names: Set[str] = None,
    min_occurrences: int = 3,
) -> list[DuplicateGroup]:
    if ignore_names is None:
        ignore_names = DEFAULT_IGNORE_NAMES

    filtered = []
    for sym in symbols:
        if ignore_constants and sym.symbol_type == SymbolType.CONSTANT:
            continue
        if should_ignore_symbol(sym.name, sym.symbol_type, ignore_names):
            continue
        filtered.append(sym)

    name_map = defaultdict(list)
    for idx, sym in enumerate(filtered):
        name_map[(sym.symbol_type, sym.name)].append(idx)

    groups = []
    used = set()

    # 1. Exact name duplicates
    for (sym_type, name), indices in name_map.items():
        if len(indices) >= min_occurrences:
            locs = [(filtered[i].file_path, filtered[i].lineno, filtered[i].module) for i in indices]
            groups.append(DuplicateGroup(
                symbol_type=sym_type,
                group_key=f"name:{name}",
                locations=locs,
                similarity_score=1.0,
                duplicate_type="exact_name",
                risk_severity="LOW",
                risk_explanation="Muncul di banyak file - mungkin disengaja atau perlu difaktorkan."
            ))
            for i in indices:
                used.add(i)

    # 2. Structural duplicates
    remaining = [i for i in range(len(filtered)) if i not in used]
    for i in range(len(remaining)):
        if remaining[i] in used:
            continue
        s1 = filtered[remaining[i]]
        dup_locs = [(s1.file_path, s1.lineno, s1.module)]
        for j in range(i+1, len(remaining)):
            if remaining[j] in used:
                continue
            s2 = filtered[remaining[j]]
            if s1.symbol_type != s2.symbol_type:
                continue
            sim = compute_similarity(s1, s2)
            if sim >= threshold:
                used.add(remaining[j])
                dup_locs.append((s2.file_path, s2.lineno, s2.module))
        if len(dup_locs) > 1:
            # ----- Tentukan risiko berdasarkan similarity dan tipe -----
            risk_sev = "LOW"
            risk_exp = "Struktural mirip, periksa apakah seharusnya di-shared."

            if s1.symbol_type == SymbolType.ENUM:
                if s1.enum_members == s2.enum_members:
                    risk_sev = "HIGH"
                    risk_exp = "Enum identik, harus di-shared."
                elif sim >= 0.85:
                    risk_sev = "MEDIUM"
                    risk_exp = "Enum mirip, periksa apakah anggota perlu disatukan."

            elif s1.symbol_type in (SymbolType.CLASS, SymbolType.DATACLASS, SymbolType.DTO):
                f1 = {(f.name, f.type_hint) for f in s1.fields}
                f2 = {(f.name, f.type_hint) for f in s2.fields}
                if f1 == f2 and len(f1) > 0:
                    risk_sev = "HIGH"
                    risk_exp = "Field identik (nama & tipe), class harus di-shared."
                elif sim >= 0.9:
                    risk_sev = "MEDIUM"
                    risk_exp = "Sebagian besar field sama, periksa kemungkinan duplikasi."

            elif s1.symbol_type == SymbolType.EXCEPTION:
                if set(s1.bases) == set(s2.bases) and sim >= 0.8:
                    risk_sev = "MEDIUM"
                    risk_exp = "Exception dengan base class sama, pertimbangkan untuk menyatukan."

            elif s1.symbol_type == SymbolType.PROTOCOL:
                if sim >= 0.9:
                    risk_sev = "MEDIUM"
                    risk_exp = "Protocol sangat mirip, periksa apakah bisa di-shared."

            groups.append(DuplicateGroup(
                symbol_type=s1.symbol_type,
                group_key=f"structural:{s1.symbol_type}:{s1.name}",
                locations=dup_locs,
                similarity_score=sim,
                duplicate_type="structural",
                risk_severity=risk_sev,
                risk_explanation=risk_exp,
            ))
            used.add(remaining[i])

    return groups

# ============================================================
# Scan proyek
# ============================================================
def scan_project(
    exclude_dirs: Optional[list[str]] = None,
    ignore_constants: bool = True,
    ignore_names: Set[str] = None,
    min_occurrences: int = 3,
) -> Report:
    if exclude_dirs is None:
        exclude_dirs = [
            '.venv', 'venv', '__pycache__', '.git', 'node_modules',
            'dist', 'build', 'migrations', 'deployment', 'docs', 'tests',
            'checker'
        ]
    exclude_set = set(exclude_dirs)

    all_symbols: list[SymbolInfo] = []
    scanned_files = 0
    files_with_symbols = 0

    # Kumpulkan direktori yang discan
    scanned_dirs = set()
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in py_file.parts):
            continue
        if py_file.name.startswith("duplicate_symbol_checker"):
            continue
        scanned_files += 1
        rel = py_file.relative_to(PROJECT_ROOT)
        scanned_dirs.add(str(rel.parent))
        module = str(rel.with_suffix("")).replace("/", ".")
        syms = extract_symbols_from_file(py_file, module)
        all_symbols.extend(syms)
        if syms:
            files_with_symbols += 1

    groups = find_duplicates(
        all_symbols,
        threshold=0.8,
        ignore_constants=ignore_constants,
        ignore_names=ignore_names,
        min_occurrences=min_occurrences,
    )

    summary = defaultdict(int)
    for g in groups:
        summary[g.symbol_type] += 1

    # Hitung score: Hanya HIGH dan MEDIUM yang mengurangi score
    score = 100
    for g in groups:
        if g.risk_severity == "HIGH":
            score -= 20
        elif g.risk_severity == "MEDIUM":
            score -= 10
        # LOW tidak mengurangi
    score = max(0, score)

    return Report(
        duplicate_groups=groups,
        score=score,
        summary=dict(summary),
        scanned_files=scanned_files,
        files_with_symbols=files_with_symbols,
        total_symbols=len(all_symbols),
        scanned_directories=sorted(scanned_dirs)
    )

# ============================================================
# Output
# ============================================================
def print_report(report: Report, verbose: bool = False, min_risk: str = "LOW", list_files: bool = False):
    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    min_level = risk_order.get(min_risk.upper(), 0)
    filtered = [g for g in report.duplicate_groups if risk_order.get(g.risk_severity, 0) >= min_level]

    c = COLOR
    print(f"\n{c['MAGENTA']}{'='*80}{c['RESET']}")
    print(f"{c['MAGENTA']}DUPLICATE SYMBOL CHECKER (RCA-ENHANCED){c['RESET']}")
    print(f"{c['MAGENTA']}{'='*80}{c['RESET']}")

    # ==================== SUMMARY STATISTICS ====================
    print(f"\n  {c['CYAN']}📊 SUMMARY STATISTICS{c['RESET']}")
    print(f"  {'-'*60}")
    print(f"     Files Scanned          : {c['CYAN']}{report.scanned_files}{c['RESET']}")
    print(f"     Files with Symbols     : {c['CYAN']}{report.files_with_symbols}{c['RESET']}")
    print(f"     Total Symbols Found    : {c['CYAN']}{report.total_symbols}{c['RESET']}")
    print(f"     Duplicate Groups (all) : {c['YELLOW']}{len(report.duplicate_groups)}{c['RESET']}")
    print(f"     Groups >= {min_risk}    : {c['YELLOW']}{len(filtered)}{c['RESET']}")
    score_color = c['GREEN'] if report.score >= 80 else c['YELLOW'] if report.score >= 50 else c['RED']
    print(f"     Compliance Score       : {score_color}{report.score}/100{c['RESET']}")

    if report.summary:
        print(f"\n  {c['CYAN']}📋 BREAKDOWN BY SYMBOL TYPE{c['RESET']}")
        print(f"  {'-'*60}")
        for typ, cnt in report.summary.items():
            print(f"     {typ.value}: {cnt}")

    # ==================== SCANNED DIRECTORIES ====================
    print(f"\n  {c['CYAN']}📁 DIRECTORIES SCANNED{c['RESET']}")
    print(f"  {'-'*60}")
    for d in report.scanned_directories[:20]:
        print(f"     - {d}")
    if len(report.scanned_directories) > 20:
        print(f"     ... dan {len(report.scanned_directories)-20} direktori lainnya.")

    if list_files:
        # Kumpulkan file yang memiliki simbol (kita tidak simpan daftar file, tapi kita bisa estimasi dari groups)
        files_with_duplicates = set()
        for g in filtered:
            for f, _, _ in g.locations:
                files_with_duplicates.add(f)
        if files_with_duplicates:
            print(f"\n  {c['CYAN']}📄 FILES WITH DUPLICATES (sample 20){c['RESET']}")
            print(f"  {'-'*60}")
            for f in sorted(files_with_duplicates)[:20]:
                print(f"     - {pathlib.Path(f).relative_to(PROJECT_ROOT)}")
            if len(files_with_duplicates) > 20:
                print(f"     ... dan {len(files_with_duplicates)-20} file lainnya.")

    # ==================== DUPLICATE GROUPS ====================
    if filtered:
        print(f"\n  {c['CYAN']}🔍 DUPLICATE SYMBOLS (Risk >= {min_risk}){c['RESET']}")
        print(f"  {'-'*60}")

        groups_by_type = defaultdict(list)
        for g in filtered:
            groups_by_type[g.symbol_type].append(g)

        for typ, grps in groups_by_type.items():
            print(f"\n  {c['YELLOW']}--- {typ.value.upper()} ({len(grps)} groups) ---{c['RESET']}")
            for group in grps:
                sev_color = c['GREEN'] if group.risk_severity == "LOW" else c['YELLOW'] if group.risk_severity == "MEDIUM" else c['RED']
                print(f"\n    {sev_color}[{group.risk_severity}]{c['RESET']} {group.duplicate_type} ({group.similarity_score:.2f})")
                print(f"      → {group.risk_explanation}")
                for file_path, line, module in group.locations:
                    rel = pathlib.Path(file_path).relative_to(PROJECT_ROOT)
                    print(f"        - {rel}:{line}  ({module})")
    else:
        print(f"\n  {c['GREEN']}✅ No duplicate symbols detected with risk >= {min_risk}.{c['RESET']}")

    print(f"\n{c['MAGENTA']}{'='*80}{c['RESET']}\n")

def save_json(report: Report, filepath: str, min_risk: str = "LOW"):
    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    min_level = risk_order.get(min_risk.upper(), 0)
    filtered = [g for g in report.duplicate_groups if risk_order.get(g.risk_severity, 0) >= min_level]

    data = {
        "metadata": {
            "scanned_files": report.scanned_files,
            "files_with_symbols": report.files_with_symbols,
            "total_symbols": report.total_symbols,
            "score": report.score,
            "scanned_directories": report.scanned_directories,
        },
        "summary": report.summary,
        "duplicate_groups": [
            {
                "type": g.symbol_type.value,
                "group_key": g.group_key,
                "duplicate_type": g.duplicate_type,
                "similarity_score": g.similarity_score,
                "risk_severity": g.risk_severity,
                "risk_explanation": g.risk_explanation,
                "locations": [{"file": f, "line": l, "module": m} for f, l, m in g.locations]
            }
            for g in filtered
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{COLOR['CYAN']}JSON saved to {filepath}{COLOR['RESET']}")

# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Advanced Duplicate Symbol Checker with RCA integration"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan ke JSON")
    parser.add_argument(
        "--exclude",
        default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,tests,checker",
        help="Folder yang diabaikan (pisahkan dengan koma)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.8,
        help="Ambang batas kemiripan (0.0-1.0, default 0.8)"
    )
    parser.add_argument(
        "--ignore-constants", action="store_true", default=True,
        help="Abaikan semua konstanta (default: True)"
    )
    parser.add_argument(
        "--no-ignore-constants", dest="ignore_constants", action="store_false",
        help="Jangan abaikan konstanta"
    )
    parser.add_argument(
        "--min-occurrences", type=int, default=3,
        help="Minimal jumlah kemunculan untuk dianggap duplikat (default 3)"
    )
    parser.add_argument(
        "--ignore-names", type=str, default="",
        help="Tambahkan nama simbol yang diabaikan (dipisahkan koma)"
    )
    parser.add_argument(
        "--min-risk", type=str, default="MEDIUM",
        choices=["LOW", "MEDIUM", "HIGH"],
        help="Tampilkan hanya duplikasi dengan risiko minimal ini (default: MEDIUM)"
    )
    parser.add_argument(
        "--ignore-patterns", type=str, default="",
        help="Tambahkan pola regex untuk mengabaikan nama (dipisahkan koma)"
    )
    parser.add_argument(
        "--list-files", "-l", action="store_true",
        help="Tampilkan daftar file yang memiliki duplikat (hanya untuk mode --min-risk)"
    )
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    ignore_names = set(DEFAULT_IGNORE_NAMES)
    if args.ignore_names:
        ignore_names.update([n.strip() for n in args.ignore_names.split(",") if n.strip()])

    if args.ignore_patterns:
        extra_patterns = [p.strip() for p in args.ignore_patterns.split(",") if p.strip()]
        IGNORE_PATTERNS.extend(extra_patterns)

    report = scan_project(
        exclude_dirs=exclude_dirs,
        ignore_constants=args.ignore_constants,
        ignore_names=ignore_names,
        min_occurrences=args.min_occurrences,
    )

    print_report(report, args.verbose, args.min_risk, args.list_files)
    if args.json:
        save_json(report, args.json, args.min_risk)

    high_risk = any(g.risk_severity == "HIGH" for g in report.duplicate_groups)
    sys.exit(0 if not high_risk else 1)

if __name__ == "__main__":
    main()