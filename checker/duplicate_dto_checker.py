#!/usr/bin/env python3
"""
duplicate_dto_checker.py - Duplicate DTO Detector
==================================================
Mendeteksi duplikasi Data Transfer Objects (DTO) di seluruh proyek.

DTO patterns yang dideteksi:
- Python dataclass (@dataclass)
- Pydantic BaseModel
- Class dengan atribut data-only (tanpa method bisnis)

Cara pakai:
  python duplicate_dto_checker.py
  python duplicate_dto_checker.py --verbose
  python duplicate_dto_checker.py --json report.json
  python duplicate_dto_checker.py --exclude tests,migrations
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
class FieldInfo:
    name: str
    type_hint: str | None
    has_default: bool
    lineno: int

@dataclass
class DTOInfo:
    name: str
    module: str
    file_path: str
    lineno: int
    is_dataclass: bool
    is_pydantic: bool
    is_typed_dict: bool
    fields: list[FieldInfo]
    bases: list[str]
    has_methods: bool  # True jika ada method selain __init__

@dataclass
class DuplicateDTOGroup:
    pattern_name: str
    fields: list[str]  # field names
    locations: list[tuple[str, int, str]]  # (file_path, line, class_name)
    similarity_score: float

@dataclass
class Report:
    dto_count: int
    duplicate_groups: list[DuplicateDTOGroup] = field(default_factory=list)
    score: int = 100

def is_dto_class(cls: ast.ClassDef) -> bool:
    """Check if class is a DTO based on decorators and structure."""
    # Check decorators
    has_dataclass_decorator = False
    has_pydantic_decorator = False
    is_dataclass_base = False
    is_pydantic_base = False

    for decorator in cls.decorator_list:
        if isinstance(decorator, ast.Name):
            if decorator.id == "dataclass":
                has_dataclass_decorator = True
            elif decorator.id == "BaseModel" or decorator.id == "PydanticModel":
                pass  # handled via bases
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name) and decorator.func.id == "dataclass":
                has_dataclass_decorator = True

    # Check base classes
    for base in cls.bases:
        if isinstance(base, ast.Name):
            if base.id in ("BaseModel", "PydanticModel"):
                is_pydantic_base = True
            elif base.id in ("TypedDict", "Dict"):
                pass  # handled separately
        elif isinstance(base, ast.Attribute):
            if base.attr in ("BaseModel", "PydanticModel"):
                is_pydantic_base = True

    # Check if it's a TypedDict (usually defined with assignment)
    is_typed_dict = False
    for item in cls.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.annotation, ast.Subscript):
            # Check for TypedDict syntax
            if isinstance(item.annotation.value, ast.Name) and item.annotation.value.id == "TypedDict":
                is_typed_dict = True

    # Count non-special methods
    method_count = 0
    for item in cls.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name not in ("__init__", "__post_init__", "__repr__", "__eq__", "__hash__"):
                method_count += 1

    # A DTO should have:
    # - dataclass decorator OR pydantic base OR TypedDict
    # - at least one field
    # - few or no business methods
    has_fields = False
    for item in cls.body:
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            has_fields = True
            break

    is_dto = False
    if has_dataclass_decorator or is_pydantic_base or is_typed_dict or (method_count == 0 and has_fields):
        is_dto = True

    return is_dto

def extract_dto_info(file_path: pathlib.Path, module: str) -> list[DTOInfo]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    dtos = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if not is_dto_class(node):
                continue

            # Check decorators
            has_dataclass = False
            has_pydantic = False
            is_typed_dict = False
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
                    has_dataclass = True
                elif isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Name) and decorator.func.id == "dataclass":
                        has_dataclass = True

            for base in node.bases:
                if isinstance(base, ast.Name) and base.id in ("BaseModel", "PydanticModel"):
                    has_pydantic = True
                elif isinstance(base, ast.Subscript):
                    if isinstance(base.value, ast.Name) and base.value.id == "TypedDict":
                        is_typed_dict = True

            # Extract fields
            fields = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign):
                    field_name = ""
                    if isinstance(item.target, ast.Name):
                        field_name = item.target.id
                    type_hint = ast.unparse(item.annotation) if item.annotation else None
                    has_default = item.value is not None
                    fields.append(FieldInfo(
                        name=field_name,
                        type_hint=type_hint,
                        has_default=has_default,
                        lineno=item.lineno
                    ))
                elif isinstance(item, ast.Assign):
                    # For TypedDict or class attributes
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            field_name = target.id
                            # Try to get type from annotation if any
                            type_hint = None
                            if hasattr(item, 'annotation') and item.annotation:
                                type_hint = ast.unparse(item.annotation)
                            fields.append(FieldInfo(
                                name=field_name,
                                type_hint=type_hint,
                                has_default=item.value is not None,
                                lineno=item.lineno
                            ))
                        elif isinstance(target, ast.Attribute):
                            # Skip class variables like __tablename__
                            pass

            # Check for business methods
            has_methods = False
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name not in ("__init__", "__post_init__", "__repr__", "__eq__", "__hash__", "__str__"):
                        has_methods = True
                        break

            bases = []
            for base in node.bases:
                bases.append(ast.unparse(base))

            dtos.append(DTOInfo(
                name=node.name,
                module=module,
                file_path=str(file_path),
                lineno=node.lineno,
                is_dataclass=has_dataclass,
                is_pydantic=has_pydantic,
                is_typed_dict=is_typed_dict,
                fields=fields,
                bases=bases,
                has_methods=has_methods
            ))
    return dtos

def compute_dto_similarity(dto1: DTOInfo, dto2: DTOInfo) -> float:
    """Compute similarity between two DTOs based on field names and types."""
    # Extract field names
    f1 = {f.name: f.type_hint for f in dto1.fields}
    f2 = {f.name: f.type_hint for f in dto2.fields}

    if not f1 and not f2:
        return 0.0

    common_names = set(f1.keys()) & set(f2.keys())
    if not common_names:
        return 0.0

    # Jaccard similarity on field names
    union = set(f1.keys()) | set(f2.keys())
    name_similarity = len(common_names) / len(union) if union else 0.0

    # Type match for common fields
    type_match = 0.0
    for name in common_names:
        if f1.get(name) == f2.get(name):
            type_match += 1
    type_ratio = type_match / len(common_names) if common_names else 0.0

    # Combined score: 0.5 name + 0.3 type + 0.2 base
    score = 0.5 * name_similarity + 0.3 * type_ratio

    # Bonus if bases are same
    if set(dto1.bases) & set(dto2.bases):
        score += 0.1

    # Penalty if dto has business methods
    if dto1.has_methods or dto2.has_methods:
        score -= 0.05

    return round(min(1.0, max(0.0, score)), 2)

def find_duplicate_dtos(dtos: list[DTOInfo], threshold: float = 0.7) -> list[DuplicateDTOGroup]:
    groups = []
    used = set()
    n = len(dtos)

    for i in range(n):
        if i in used:
            continue
        d1 = dtos[i]
        dup_locs = [(d1.file_path, d1.lineno, d1.name)]
        field_names = [f.name for f in d1.fields]

        for j in range(i+1, n):
            if j in used:
                continue
            d2 = dtos[j]
            sim = compute_dto_similarity(d1, d2)
            if sim >= threshold:
                used.add(j)
                dup_locs.append((d2.file_path, d2.lineno, d2.name))
                # Merge field names
                for f in d2.fields:
                    if f.name not in field_names:
                        field_names.append(f.name)

        if len(dup_locs) > 1:
            groups.append(DuplicateDTOGroup(
                pattern_name=d1.name,
                fields=field_names[:10],  # limit fields
                locations=dup_locs,
                similarity_score=sim
            ))

    return groups

def scan_project(exclude_dirs: list[str] = None) -> Report:
    if exclude_dirs is None:
        exclude_dirs = ['.venv', 'venv', '__pycache__', '.git', 'node_modules',
                       'dist', 'build', 'migrations', 'deployment', 'docs', 'tests']
    exclude_set = set(exclude_dirs)

    all_dtos = []
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in py_file.parts):
            continue
        if py_file.name.startswith("duplicate_dto_checker"):
            continue
        # Build module name
        rel = py_file.relative_to(PROJECT_ROOT)
        module = str(rel.with_suffix("")).replace("/", ".")
        dtos = extract_dto_info(py_file, module)
        all_dtos.extend(dtos)

    # Find duplicate groups
    groups = find_duplicate_dtos(all_dtos, threshold=0.7)

    # Score: each duplicate group reduces score by 8 points
    score = max(0, 100 - len(groups) * 8)
    return Report(dto_count=len(all_dtos), duplicate_groups=groups, score=score)

def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}DUPLICATE DTO CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total DTOs found: {report.dto_count}")
    print(f"  Duplicate groups: {len(report.duplicate_groups)}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.duplicate_groups:
        print(f"\n{c['YELLOW']}Duplicate DTO Groups:{c['RESET']}")
        for group in report.duplicate_groups:
            print(f"\n  Pattern: {group.pattern_name} (similarity: {group.similarity_score:.2f})")
            print(f"    Fields: {', '.join(group.fields)}")
            print("    Locations:")
            for file_path, line, class_name in group.locations:
                print(f"      - {file_path}:{line}  [{class_name}]")
    else:
        print(f"\n{c['GREEN']}✅ No duplicate DTOs detected.{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {
        "dto_count": report.dto_count,
        "duplicate_groups": [
            {
                "pattern": g.pattern_name,
                "fields": g.fields,
                "locations": [{"file": f, "line": l, "class": c} for f, l, c in g.locations],
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
    parser = argparse.ArgumentParser(description="Duplicate DTO Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,tests",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    parser.add_argument("--threshold", type=float, default=0.7,
                        help="Threshold kemiripan (0.0-1.0, default: 0.7)")
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    report = scan_project(exclude_dirs)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    sys.exit(0 if len(report.duplicate_groups) == 0 else 1)

if __name__ == "__main__":
    main()
