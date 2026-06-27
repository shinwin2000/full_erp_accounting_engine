#!/usr/bin/env python3
"""
duplicate_enum_checker.py - Duplicate Enum Detector
===================================================
Mendeteksi duplikasi enum di seluruh proyek berdasarkan:
1. Nama enum yang sama persis (di modul berbeda)
2. Nilai enum yang sama (values)
3. Struktur enum yang mirip (member names)

Cara pakai:
  python duplicate_enum_checker.py
  python duplicate_enum_checker.py --verbose
  python duplicate_enum_checker.py --json report.json
  python duplicate_enum_checker.py --exclude tests,migrations
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from collections import defaultdict
from dataclasses import dataclass, field

# Warna
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

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

@dataclass
class EnumMember:
    name: str
    value: str

@dataclass
class EnumInfo:
    name: str
    module: str
    file_path: str
    lineno: int
    members: list[EnumMember]
    base_type: str  # 'Enum', 'IntEnum', 'StrEnum', 'class'

@dataclass
class DuplicateGroup:
    group_key: str
    enums: list[tuple[str, str, int]]  # (file_path, module, line)
    duplicate_type: str  # 'exact_name', 'same_values', 'similar_structure'
    similarity_score: float

@dataclass
class Report:
    duplicate_groups: list[DuplicateGroup] = field(default_factory=list)
    score: int = 100

def extract_enum_info(file_path: pathlib.Path, module: str) -> list[EnumInfo]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    enums = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if this class inherits from enum.Enum or similar
        is_enum = False
        base_type = "class"
        for base in node.bases:
            base_name = ast.unparse(base).lower()
            if 'enum' in base_name or 'intenum' in base_name or 'strenum' in base_name:
                is_enum = True
                base_type = base_name.split('.')[-1] if '.' in base_name else base_name
                break

        # Also check for class with only constant assignments (no methods)
        if not is_enum:
            has_method = False
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    has_method = True
                    break
            if not has_method and len(node.body) > 0:
                # Check if all items are assignments of constants
                all_constants = True
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                # Constant name should be uppercase
                                if not target.id.isupper():
                                    all_constants = False
                                    break
                        else:
                            continue
                        break
                    elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        all_constants = False
                        break
                if all_constants:
                    is_enum = True
                    base_type = "class"  # treat as pseudo-enum

        if not is_enum:
            continue

        # Extract members
        members = []
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        # Get value
                        if isinstance(item.value, ast.Constant):
                            value = str(item.value.value)
                        elif isinstance(item.value, ast.Name):
                            value = item.value.id
                        elif isinstance(item.value, ast.Attribute):
                            value = ast.unparse(item.value)
                        else:
                            value = ast.unparse(item.value)
                        members.append(EnumMember(name=target.id, value=value))
            # Also handle tuple assignment? skip for simplicity

        if members:
            enums.append(EnumInfo(
                name=node.name,
                module=module,
                file_path=str(file_path),
                lineno=node.lineno,
                members=members,
                base_type=base_type
            ))
    return enums

def compute_enum_similarity(e1: EnumInfo, e2: EnumInfo) -> float:
    """Compute similarity between two enums based on member names and values."""
    m1_names = {m.name for m in e1.members}
    m2_names = {m.name for m in e2.members}
    m1_values = {m.value for m in e1.members}
    m2_values = {m.value for m in e2.members}

    # Jaccard on names
    name_union = m1_names | m2_names
    name_jaccard = len(m1_names & m2_names) / len(name_union) if name_union else 0.0

    # Jaccard on values
    val_union = m1_values | m2_values
    val_jaccard = len(m1_values & m2_values) / len(val_union) if val_union else 0.0

    # Weighted average: 0.5 name + 0.5 value
    score = 0.5 * name_jaccard + 0.5 * val_jaccard
    return round(score, 2)

def find_duplicate_enums(enum_list: list[EnumInfo], threshold: float = 0.8) -> list[DuplicateGroup]:
    groups = []
    used = set()
    n = len(enum_list)

    # First, group by exact name
    name_map = defaultdict(list)
    for idx, enum in enumerate(enum_list):
        name_map[enum.name].append(idx)

    for name, indices in name_map.items():
        if len(indices) > 1:
            group = DuplicateGroup(
                group_key=f"name:{name}",
                enums=[(enum_list[i].file_path, enum_list[i].module, enum_list[i].lineno) for i in indices],
                duplicate_type="exact_name",
                similarity_score=1.0
            )
            groups.append(group)
            for i in indices:
                used.add(i)

    # Then, find structurally similar enums (different names but similar members)
    remaining = [i for i in range(n) if i not in used]
    for i in range(len(remaining)):
        if remaining[i] in used:
            continue
        e1 = enum_list[remaining[i]]
        dup_locs = [(e1.file_path, e1.module, e1.lineno)]
        for j in range(i+1, len(remaining)):
            if remaining[j] in used:
                continue
            e2 = enum_list[remaining[j]]
            sim = compute_enum_similarity(e1, e2)
            if sim >= threshold:
                used.add(remaining[j])
                dup_locs.append((e2.file_path, e2.module, e2.lineno))
        if len(dup_locs) > 1:
            groups.append(DuplicateGroup(
                group_key=f"similar:{e1.name}->{','.join([enum_list[i].name for i in range(len(enum_list)) if i in used and i != remaining[i]])}",
                enums=dup_locs,
                duplicate_type="similar_structure",
                similarity_score=sim
            ))
            used.add(remaining[i])

    return groups

def scan_project(exclude_dirs: list[str] = None) -> Report:
    if exclude_dirs is None:
        exclude_dirs = ['.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests']
    exclude_set = set(exclude_dirs)

    all_enums = []
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in py_file.parts):
            continue
        if py_file.name.startswith("duplicate_enum_checker"):
            continue
        rel = py_file.relative_to(PROJECT_ROOT)
        module = str(rel.with_suffix("")).replace("/", ".")
        enums = extract_enum_info(py_file, module)
        all_enums.extend(enums)

    groups = find_duplicate_enums(all_enums, threshold=0.8)

    # Score: each duplicate group reduces score by 10 points
    score = max(0, 100 - len(groups) * 10)
    return Report(duplicate_groups=groups, score=score)

def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}DUPLICATE ENUM CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total duplicate groups: {len(report.duplicate_groups)}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.duplicate_groups:
        print(f"\n{c['YELLOW']}Duplicate Enums:{c['RESET']}")
        for group in report.duplicate_groups:
            print(f"\n  [{group.duplicate_type}] {group.group_key} (similarity: {group.similarity_score:.2f})")
            for file_path, module, line in group.enums:
                print(f"    - {file_path}:{line}  (module: {module})")
            if verbose and group.duplicate_type == "similar_structure":
                # Show members? Could be too verbose
                pass
    else:
        print(f"\n{c['GREEN']}✅ No duplicate enums detected.{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {
        "duplicate_groups": [
            {
                "group_key": g.group_key,
                "duplicate_type": g.duplicate_type,
                "similarity_score": g.similarity_score,
                "enums": [{"file": f, "module": m, "line": l} for f, m, l in g.enums]
            }
            for g in report.duplicate_groups
        ],
        "score": report.score
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

def main():
    parser = argparse.ArgumentParser(description="Duplicate Enum Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,tests",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    report = scan_project(exclude_dirs)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    sys.exit(0 if len(report.duplicate_groups) == 0 else 1)

if __name__ == "__main__":
    main()
