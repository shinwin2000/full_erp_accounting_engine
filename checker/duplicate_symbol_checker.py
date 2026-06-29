#!/usr/bin/env python3
"""
duplicate_symbol_checker.py - Advanced Duplicate Symbol Detector
================================================================
Mendeteksi duplikasi berbagai simbol penting di seluruh proyek:

  - Class
  - Enum
  - Dataclass
  - DTO (Data Transfer Object)
  - TypedDict
  - Protocol
  - Exception (custom exception)
  - Constant (module-level constants)

Deteksi dilakukan berdasarkan:
  1. Nama simbol yang sama persis (di modul berbeda)
  2. Kemiripan struktural (field, method signature, enum values)

Cara pakai:
  python duplicate_symbol_checker.py
  python duplicate_symbol_checker.py --verbose
  python duplicate_symbol_checker.py --json report.json
  python duplicate_symbol_checker.py --exclude tests,migrations
  python duplicate_symbol_checker.py --threshold 0.8
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Set, List, Tuple, Dict

# ============================================================
# Warna untuk output terminal
# ============================================================
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
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
    TYPEDICT = "typeddict"
    PROTOCOL = "protocol"
    EXCEPTION = "exception"
    CONSTANT = "constant"


# ============================================================
# Struktur data untuk setiap simbol
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
    # Fields depending on type
    fields: list[FieldInfo] = field(default_factory=list)      # dataclass, DTO, TypedDict
    methods: list[MethodInfo] = field(default_factory=list)    # class
    bases: list[str] = field(default_factory=list)             # class inheritance
    enum_members: list[EnumMember] = field(default_factory=list)  # enum
    is_dataclass: bool = False
    is_pydantic: bool = False
    has_business_methods: bool = False
    # Extra
    value: Optional[str] = None   # for constants


# ============================================================
# Kelompok duplikat
# ============================================================
@dataclass
class DuplicateGroup:
    symbol_type: SymbolType
    group_key: str                     # e.g., name or structural pattern
    locations: list[tuple[str, int, str]]  # (file_path, lineno, module)
    similarity_score: float
    duplicate_type: str                # 'exact_name' or 'structural'


@dataclass
class Report:
    duplicate_groups: list[DuplicateGroup] = field(default_factory=list)
    score: int = 100
    summary: dict[str, int] = field(default_factory=dict)  # type -> count


# ============================================================
# Ekstraksi simbol dari file
# ============================================================
def extract_symbols_from_file(
    file_path: pathlib.Path, module: str
) -> list[SymbolInfo]:
    """Parse file dan ekstrak semua simbol yang relevan."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    symbols: list[SymbolInfo] = []

    # Pertama, kumpulkan semua class definitions
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            sym = _extract_class_symbol(node, module, file_path)
            if sym:
                symbols.append(sym)

    # Kedua, kumpulkan konstanta tingkat modul (upper-case assignments)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    # constant
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
                elif isinstance(target, ast.Attribute):
                    # skip class-level attributes
                    pass

    return symbols


def _extract_class_symbol(
    node: ast.ClassDef, module: str, file_path: pathlib.Path
) -> Optional[SymbolInfo]:
    """Ekstrak simbol dari node class."""
    # Tentukan tipe simbol
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

    # Cek decorator @dataclass
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "dataclass":
            is_dataclass = True
        elif isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == "dataclass":
            is_dataclass = True

    # Kumpulkan method
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

    # Kumpulkan field (untuk dataclass, DTO, TypedDict)
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
            # untuk TypedDict atau atribut kelas
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
                elif isinstance(target, ast.Attribute):
                    # skip __tablename__ etc.
                    pass

    # Tentukan tipe prioritas:
    # Jika enum, prioritas enum
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
        # Cek apakah ini DTO (class dengan hanya field dan sedikit method)
        if not has_business_methods and fields:
            symbol_type = SymbolType.DTO
        else:
            symbol_type = SymbolType.CLASS

    # Untuk enum, ekstrak anggota
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

    # Kumpulkan bases untuk semua tipe
    # Siapkan SymbolInfo
    sym = SymbolInfo(
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
    return sym


# ============================================================
# Fungsi similarity
# ============================================================
def compute_similarity(s1: SymbolInfo, s2: SymbolInfo) -> float:
    """Hitung kemiripan antara dua simbol dengan tipe yang sama."""
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
        # Untuk protocol, exception kita gunakan similarity berbasis bases & methods
        return _similarity_class(s1, s2)


def _similarity_class(c1: SymbolInfo, c2: SymbolInfo) -> float:
    """Kemiripan antara dua class (method signature, bases)."""
    # method names and param counts
    m1 = {m.name: len(m.params) for m in c1.methods}
    m2 = {m.name: len(m.params) for m in c2.methods}
    common = set(m1.keys()) & set(m2.keys())
    if not common:
        # cek bases
        if set(c1.bases) & set(c2.bases):
            return 0.3
        return 0.0
    union = set(m1.keys()) | set(m2.keys())
    jaccard = len(common) / len(union) if union else 0.0
    # parameter match
    param_match = sum(1 for m in common if m1[m] == m2[m])
    param_ratio = param_match / len(common) if common else 0.0
    score = 0.6 * jaccard + 0.4 * param_ratio
    # bonus bases
    if set(c1.bases) & set(c2.bases):
        score = min(1.0, score + 0.1)
    return round(score, 2)


def _similarity_dto(d1: SymbolInfo, d2: SymbolInfo) -> float:
    """Kemiripan DTO/dataclass berdasarkan field."""
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
    """Kemiripan enum berdasarkan member names dan values."""
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
    """Kemiripan konstanta: 1.0 jika nilai sama, 0.0 jika berbeda."""
    if c1.value is not None and c2.value is not None:
        return 1.0 if c1.value == c2.value else 0.0
    return 0.0


# ============================================================
# Deteksi duplikat
# ============================================================
def find_duplicates(
    symbols: list[SymbolInfo], threshold: float = 0.8
) -> list[DuplicateGroup]:
    """Cari grup duplikat berdasarkan exact name dan structural similarity."""
    groups: list[DuplicateGroup] = []
    used = set()
    n = len(symbols)

    # 1. Group by exact name within same symbol type
    name_map = defaultdict(list)
    for idx, sym in enumerate(symbols):
        key = (sym.symbol_type, sym.name)
        name_map[key].append(idx)

    for (sym_type, name), indices in name_map.items():
        if len(indices) > 1:
            locs = [(symbols[i].file_path, symbols[i].lineno, symbols[i].module) for i in indices]
            groups.append(DuplicateGroup(
                symbol_type=sym_type,
                group_key=f"name:{name}",
                locations=locs,
                similarity_score=1.0,
                duplicate_type="exact_name"
            ))
            for i in indices:
                used.add(i)

    # 2. Structural similarity for remaining
    remaining = [i for i in range(n) if i not in used]
    for i in range(len(remaining)):
        if remaining[i] in used:
            continue
        s1 = symbols[remaining[i]]
        dup_locs = [(s1.file_path, s1.lineno, s1.module)]
        for j in range(i+1, len(remaining)):
            if remaining[j] in used:
                continue
            s2 = symbols[remaining[j]]
            # Only compare same type
            if s1.symbol_type != s2.symbol_type:
                continue
            sim = compute_similarity(s1, s2)
            if sim >= threshold:
                used.add(remaining[j])
                dup_locs.append((s2.file_path, s2.lineno, s2.module))
        if len(dup_locs) > 1:
            # group key: type + s1 name + ...
            group_key = f"structural:{s1.symbol_type}:{s1.name}"
            groups.append(DuplicateGroup(
                symbol_type=s1.symbol_type,
                group_key=group_key,
                locations=dup_locs,
                similarity_score=sim,
                duplicate_type="structural"
            ))
            used.add(remaining[i])

    return groups


# ============================================================
# Scanning proyek
# ============================================================
def scan_project(exclude_dirs: Optional[list[str]] = None) -> Report:
    if exclude_dirs is None:
        exclude_dirs = [
            '.venv', 'venv', '__pycache__', '.git', 'node_modules',
            'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'
        ]
    exclude_set = set(exclude_dirs)

    all_symbols: list[SymbolInfo] = []
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in py_file.parts):
            continue
        if py_file.name.startswith("duplicate_symbol_checker"):
            continue
        rel = py_file.relative_to(PROJECT_ROOT)
        module = str(rel.with_suffix("")).replace("/", ".")
        syms = extract_symbols_from_file(py_file, module)
        all_symbols.extend(syms)

    # Temukan duplikat
    groups = find_duplicates(all_symbols, threshold=0.8)

    # Summary per type
    summary = defaultdict(int)
    for g in groups:
        summary[g.symbol_type] += 1

    # Score: setiap grup duplikat mengurangi 10 poin
    score = max(0, 100 - len(groups) * 10)

    return Report(
        duplicate_groups=groups,
        score=score,
        summary=dict(summary)
    )


# ============================================================
# Output
# ============================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}DUPLICATE SYMBOL CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")

    # Summary
    print(f"\n  Total duplicate groups: {len(report.duplicate_groups)}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")
    if report.summary:
        print("\n  Breakdown by type:")
        for typ, cnt in report.summary.items():
            print(f"    {typ.value}: {cnt}")

    if not report.duplicate_groups:
        print(f"\n{c['GREEN']}✅ No duplicate symbols detected.{c['RESET']}")
        return

    print(f"\n{c['YELLOW']}Duplicate Symbols:{c['RESET']}")

    # Group by type for better readability
    groups_by_type = defaultdict(list)
    for g in report.duplicate_groups:
        groups_by_type[g.symbol_type].append(g)

    for typ, grps in groups_by_type.items():
        print(f"\n  {c['CYAN']}--- {typ.value.upper()} ---{c['RESET']}")
        for group in grps:
            dup_label = f"[{group.duplicate_type}]"
            print(f"\n    {dup_label} {group.group_key} (similarity: {group.similarity_score:.2f})")
            for file_path, line, module in group.locations:
                print(f"      - {file_path}:{line}  ({module})")
            if verbose and group.duplicate_type == "structural":
                # Tampilkan detail tambahan? bisa skip
                pass


def save_json(report: Report, filepath: str):
    data = {
        "score": report.score,
        "summary": report.summary,
        "duplicate_groups": [
            {
                "type": g.symbol_type.value,
                "group_key": g.group_key,
                "duplicate_type": g.duplicate_type,
                "similarity_score": g.similarity_score,
                "locations": [{"file": f, "line": l, "module": m} for f, l, m in g.locations]
            }
            for g in report.duplicate_groups
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Advanced Duplicate Symbol Checker"
    )
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan ke JSON")
    parser.add_argument(
        "--exclude",
        default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,tests",
        help="Folder yang diabaikan (pisahkan dengan koma)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.8,
        help="Ambang batas kemiripan (0.0-1.0, default 0.8)"
    )
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    report = scan_project(exclude_dirs)

    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    sys.exit(0 if len(report.duplicate_groups) == 0 else 1)


if __name__ == "__main__":
    main()