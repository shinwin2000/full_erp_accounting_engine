#!/usr/bin/env python3
"""
Module: column_reference_checker.py
Layer: Tooling / Static Analysis (dijalankan manual atau lewat master_checker.py)

Responsibility:
    Scan semua adapter repository impl (*_repository_impl.py, sqlalchemy_*.py)
    di bawah suatu direktori, cari SEMUA pemakaian `<ORMTableClass>.<attribute>`
    (mis. `IAMPermissionTable.deleted_at`), lalu cross-check apakah `attribute`
    itu BENERAN ada di class ORM aslinya (kolom mapped, relationship, atau
    atribut/property Python biasa) dengan cara literally import class-nya dan
    introspeksi lewat SQLAlchemy `inspect()`.

    Ini menangkap kelas bug yang baru saja terjadi berkali-kali di modul IAM:
    - IAMRepositoryPort.update_role() dipanggil dengan kwargs yang gak match
      signature real implementasinya (dicek terpisah, checker ini fokus ke
      atribut kolom ORM, bukan signature method — lihat CATATAN di bawah)
    - `values={"updated_by": ...}` ke tabel yang gak punya kolom itu
    - `.where(SomeTable.deleted_at.is_(None))` ke tabel yang gak di-mixin
      SoftDeleteMixin

    SEMUA bug ini SEBELUMNYA baru ketahuan pas endpoint benar-benar dipanggil
    di runtime (500 Internal Server Error). Checker ini nangkep sebelum itu,
    lewat static AST scan + real import (bukan regex tebak-tebakan).

CATATAN — yang TIDAK dicek checker ini (di luar scope, kelas bug beda):
    - Mismatch parameter/kwargs pada pemanggilan METHOD (mis. bug #1 di sesi
      hari ini: service.update_role(role_id=..., ...) vs real signature
      update_role(self, role: RoleEntity)). Itu soal call-signature Python
      biasa, bukan soal kolom ORM — kalau mau dicek juga, itu scope checker
      terpisah (bisa dibuatkan lain waktu: signature-mismatch checker pakai
      inspect.signature() dibandingkan ke semua actual call site).
    - Query yang sepenuhnya dinamis / attribute access lewat getattr(table, name)
      (jarang dipakai di codebase ini, tapi kalau ada, checker berbasis AST
      statis begini gak akan nangkep itu).

Usage (dijalankan dari root project, mis. E:\\full_erp_accounting_engine):
    python column_reference_checker.py
    python column_reference_checker.py --path adapters/secondary_impl
    python column_reference_checker.py --file adapters/secondary_impl/sqlalchemy_iam_user_repository_impl.py
    python column_reference_checker.py --verbose

Exit code: 0 kalau bersih, 1 kalau ada mismatch (bisa dipakai di CI / pre-commit).
"""

from __future__ import annotations

import argparse
import ast
import importlib
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Atribut Python bawaan / dunder / hal yang wajar tidak dianggap "kolom ORM"
# jadi tidak perlu divalidasi walau namanya nempel di belakang identifier *Table.
_IGNORED_ATTRS = {
    "metadata", "registry", "__table__", "__tablename__", "__mapper__",
}


@dataclass
class AttrRef:
    class_name: str
    attr_name: str
    lineno: int
    col: int


def find_table_attr_refs(tree: ast.AST) -> list[AttrRef]:
    """Cari semua pemakaian `<Identifier ending in 'Table'>.<attr>` di source."""
    refs: list[AttrRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            cls_name = node.value.id
            if cls_name.endswith("Table") and node.attr not in _IGNORED_ATTRS:
                refs.append(AttrRef(cls_name, node.attr, node.lineno, node.col_offset))
    return refs


def collect_imported_table_classes(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """Map local_name -> (module_path, original_name) untuk semua `from X import YTable [as Z]`."""
    imports: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local_name = alias.asname or alias.name
                if local_name.endswith("Table"):
                    imports[local_name] = (node.module, alias.name)
    return imports


def get_real_attrs(module_path: str, class_name: str) -> tuple[set[str] | None, str | None]:
    """Import modulnya beneran, ambil semua attribute name yang valid di class ORM tsb:
    kolom mapped table + relationship + attribute Python biasa (termasuk yang
    datang dari mixin seperti TimestampMixin/SoftDeleteMixin/VersionMixin)."""
    try:
        mod = importlib.import_module(module_path)
    except Exception as e:  # noqa: BLE001 - memang mau nangkep semua import error
        return None, f"gagal import module '{module_path}': {e}"

    cls = getattr(mod, class_name, None)
    if cls is None:
        return None, f"class '{class_name}' tidak ditemukan di module '{module_path}'"

    attrs: set[str] = set()

    table = getattr(cls, "__table__", None)
    if table is not None:
        attrs |= set(table.columns.keys())

    try:
        from sqlalchemy import inspect as sa_inspect
        mapper = sa_inspect(cls)
        attrs |= set(mapper.attrs.keys())
        attrs |= set(mapper.relationships.keys())
        attrs |= set(mapper.column_attrs.keys())
    except Exception:
        # Bukan mapped class SQLAlchemy (atau belum ke-configure) — lanjut
        # pakai fallback attribute scan di bawah saja.
        pass

    for klass in cls.__mro__:
        attrs |= set(vars(klass).keys())

    return attrs, None


def scan_file(filepath: Path, verbose: bool = False) -> tuple[list[str], list[str]]:
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except SyntaxError as e:
        return [], [f"SyntaxError saat parse {filepath}: {e}"]

    imported = collect_imported_table_classes(tree)
    refs = find_table_attr_refs(tree)

    issues: list[str] = []
    cache: dict[tuple[str, str], tuple[set[str] | None, str | None]] = {}

    for ref in refs:
        if ref.class_name not in imported:
            # Bukan class ORM yang di-import di file ini (mis. variabel lokal
            # kebetulan namanya berakhiran 'Table') — skip, hindari false positive.
            continue

        module_path, orig_name = imported[ref.class_name]
        key = (module_path, orig_name)
        if key not in cache:
            cache[key] = get_real_attrs(module_path, orig_name)
        attrs, err = cache[key]

        if err:
            if verbose:
                issues.append(f"{filepath}:{ref.lineno}: [SKIP] tidak bisa verifikasi {ref.class_name} ({err})")
            continue

        if ref.attr_name not in attrs and not ref.attr_name.startswith("_"):
            issues.append(
                f"{filepath}:{ref.lineno}: {ref.class_name}.{ref.attr_name} "
                f"TIDAK ADA di kolom/atribut real class-nya "
                f"({module_path}.{orig_name})"
            )

    return issues, []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", default="adapters/secondary_impl", help="Direktori yang discan (default: adapters/secondary_impl)")
    parser.add_argument("--file", default=None, help="Scan satu file spesifik saja")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan juga class yang gagal diverifikasi (import error, dll)")
    args = parser.parse_args()

    sys.path.insert(0, str(PROJECT_ROOT))

    if args.file:
        files = [Path(args.file)]
    else:
        base = Path(args.path)
        if not base.exists():
            print(f"[ERROR] Direktori '{base}' tidak ditemukan. Jalankan script ini dari root project.")
            sys.exit(2)
        files = sorted(set(base.rglob("*_repository_impl.py")) | set(base.rglob("sqlalchemy_*.py")))

    if not files:
        print(f"[WARN] Tidak ada file yang cocok pola *_repository_impl.py / sqlalchemy_*.py di '{args.path}'.")
        sys.exit(0)

    total_issues = 0
    total_errors = 0
    for f in files:
        try:
            issues, errors = scan_file(f, verbose=args.verbose)
        except Exception:  # noqa: BLE001 - jangan sampai satu file bikin scan berhenti total
            print(f"[FATAL] Gagal scan {f}:")
            traceback.print_exc()
            total_errors += 1
            continue

        for e in errors:
            print(f"[ERROR] {e}")
            total_errors += 1
        for i in issues:
            tag = "[SKIP]" if "[SKIP]" in i else "[MISMATCH]"
            print(i if tag == "[SKIP]" else f"[MISMATCH] {i}")
            if tag == "[MISMATCH]":
                total_issues += 1

    print()
    print(f"Selesai. {len(files)} file discan, {total_issues} potensi bug kolom/atribut ditemukan"
          f"{f', {total_errors} error scan' if total_errors else ''}.")

    sys.exit(1 if (total_issues or total_errors) else 0)


if __name__ == "__main__":
    main()
