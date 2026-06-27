#!/usr/bin/env python3
"""
duplicate_class_checker.py - Duplicate Class Detector
=====================================================
Mendeteksi duplikasi class di seluruh proyek berdasarkan:
1. Nama class yang sama persis (di modul berbeda)
2. Kemiripan struktural (method signatures, attributes)

Cara pakai:
  python duplicate_class_checker.py
  python duplicate_class_checker.py --verbose
  python duplicate_class_checker.py --json report.json
  python duplicate_class_checker.py --exclude tests,migrations
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
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
class MethodInfo:
    name: str
    params: list[str]
    is_async: bool
    lineno: int

@dataclass
class ClassInfo:
    name: str
    module: str
    file_path: str
    lineno: int
    methods: list[MethodInfo]
    bases: list[str]   # nama base class
    has_init: bool

@dataclass
class DuplicateGroup:
    class_name: str
    locations: list[tuple[str, int]]  # (file_path, line)
    similarity_score: float  # 1.0 = identik

@dataclass
class Report:
    duplicate_groups: list[DuplicateGroup] = field(default_factory=list)
    score: int = 100

def extract_class_info(file_path: pathlib.Path, module: str) -> list[ClassInfo]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = []
            has_init = False
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    params = [arg.arg for arg in item.args.args if arg.arg not in ('self', 'cls')]
                    methods.append(MethodInfo(
                        name=item.name,
                        params=params,
                        is_async=isinstance(item, ast.AsyncFunctionDef),
                        lineno=item.lineno
                    ))
                    if item.name == "__init__":
                        has_init = True
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
                else:
                    bases.append(ast.unparse(base))
            classes.append(ClassInfo(
                name=node.name,
                module=module,
                file_path=str(file_path),
                lineno=node.lineno,
                methods=methods,
                bases=bases,
                has_init=has_init
            ))
    return classes

def compute_similarity(c1: ClassInfo, c2: ClassInfo) -> float:
    """Compute similarity between two classes based on methods and bases."""
    # If names are same, score high
    if c1.name == c2.name:
        return 1.0
    # Otherwise check structural similarity
    # Method signatures: compare method names and parameter counts
    m1 = {m.name: len(m.params) for m in c1.methods}
    m2 = {m.name: len(m.params) for m in c2.methods}
    common_methods = set(m1.keys()) & set(m2.keys())
    if not common_methods:
        # No common methods, but check bases
        if set(c1.bases) & set(c2.bases):
            return 0.3
        return 0.0
    # Jaccard similarity on method names
    union = set(m1.keys()) | set(m2.keys())
    jaccard = len(common_methods) / len(union) if union else 0.0
    # Parameter match for common methods
    param_match = 0.0
    for m in common_methods:
        if m1[m] == m2[m]:
            param_match += 1
    param_ratio = param_match / len(common_methods) if common_methods else 0.0
    # Combined score: 0.6 * jaccard + 0.4 * param_ratio
    score = 0.6 * jaccard + 0.4 * param_ratio
    # Bonus if bases similar
    base_overlap = len(set(c1.bases) & set(c2.bases))
    if base_overlap > 0:
        score = min(1.0, score + 0.1)
    return round(score, 2)

def find_duplicates(class_list: list[ClassInfo], threshold: float = 0.8) -> list[DuplicateGroup]:
    groups = []
    used = set()
    n = len(class_list)
    for i in range(n):
        if i in used:
            continue
        c1 = class_list[i]
        dup_locs = [(c1.file_path, c1.lineno)]
        for j in range(i+1, n):
            if j in used:
                continue
            c2 = class_list[j]
            # Check exact name duplicate OR high similarity
            if c1.name == c2.name:
                used.add(j)
                dup_locs.append((c2.file_path, c2.lineno))
            else:
                sim = compute_similarity(c1, c2)
                if sim >= threshold:
                    used.add(j)
                    dup_locs.append((c2.file_path, c2.lineno))
        if len(dup_locs) > 1:
            groups.append(DuplicateGroup(
                class_name=c1.name,
                locations=dup_locs,
                similarity_score=1.0 if c1.name in [class_list[i].name for i in used] else 0.8
            ))
    return groups

def scan_project(exclude_dirs: list[str] = None) -> Report:
    if exclude_dirs is None:
        exclude_dirs = ['.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests']
    exclude_set = set(exclude_dirs)

    all_classes = []
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in py_file.parts):
            continue
        if py_file.name.startswith("duplicate_class_checker"):
            continue
        # Build module name
        rel = py_file.relative_to(PROJECT_ROOT)
        module = str(rel.with_suffix("")).replace("/", ".")
        classes = extract_class_info(py_file, module)
        all_classes.extend(classes)

    # Find duplicate groups
    groups = find_duplicates(all_classes, threshold=0.8)

    # Score: each duplicate group reduces score by 10 points
    score = max(0, 100 - len(groups) * 10)
    return Report(duplicate_groups=groups, score=score)

def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}DUPLICATE CLASS CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total duplicate groups: {len(report.duplicate_groups)}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.duplicate_groups:
        print(f"\n{c['YELLOW']}Duplicate Classes:{c['RESET']}")
        for group in report.duplicate_groups:
            print(f"\n  Class: {group.class_name} (similarity: {group.similarity_score:.2f})")
            for file_path, line in group.locations:
                print(f"    - {file_path}:{line}")
            if verbose:
                # Show methods or bases? Too much detail, skip
                pass
    else:
        print(f"\n{c['GREEN']}✅ No duplicate classes detected.{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {
        "duplicate_groups": [
            {
                "class_name": g.class_name,
                "locations": [{"file": f, "line": l} for f, l in g.locations],
                "similarity_score": g.similarity_score
            }
            for g in report.duplicate_groups
        ],
        "score": report.score
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

def main():
    parser = argparse.ArgumentParser(description="Duplicate Class Checker")
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
