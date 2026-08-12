#!/usr/bin/env python3
"""
Module: orm_migration_sync_checker.py
Layer: Tooling / Static Analysis
Responsibility: Memeriksa kesesuaian antara model ORM SQLAlchemy dan migration Alembic.
Mendeteksi kolom yang ada di ORM tetapi tidak ada di migration, dan sebaliknya.
"""

from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import inspect

PROJECT_ROOT = Path(__file__).resolve().parent
ORM_BASE = "infrastructure/persistence_orm"
MIGRATIONS_DIR = "migrations/versions"


@dataclass
class ColumnInfo:
    name: str
    type: str | None = None
    nullable: bool | None = None
    primary_key: bool = False
    server_default: str | None = None


@dataclass
class TableSchema:
    columns: dict[str, ColumnInfo] = field(default_factory=dict)
    # opsional: indeks, constraints, dll.


@dataclass
class TableDiff:
    table: str
    missing_in_orm: list[str]  # kolom ada di migration tapi tidak di ORM
    missing_in_migration: list[str]  # kolom ada di ORM tapi tidak di migration
    type_mismatch: list[tuple[str, str, str]]  # (kolom, tipe_orm, tipe_migration)


def get_orm_tables() -> dict[str, TableSchema]:
    """Memuat semua model ORM dan mengembalikan skema tabel (nama tabel -> kolom)."""
    orm_path = PROJECT_ROOT / ORM_BASE
    schemas: dict[str, TableSchema] = {}

    # Daftar semua file *table.py
    for filepath in orm_path.glob("*table.py"):
        module_name = f"infrastructure.persistence_orm.{filepath.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            print(f"[WARN] Gagal import {module_name}: {e}")
            continue

        for attr_name in dir(module):
            cls = getattr(module, attr_name)
            if not isinstance(cls, type):
                continue
            # Cek apakah class adalah model SQLAlchemy (punya __tablename__)
            if not hasattr(cls, "__tablename__"):
                continue
            # Cek apakah class adalah subclass dari Base (indikasi ORM model)
            if not hasattr(cls, "__table__"):
                continue

            table_name = getattr(cls, "__tablename__", None)
            if not table_name:
                continue

            schema = TableSchema()
            try:
                mapper = inspect(cls)
                for col in mapper.columns:
                    col_info = ColumnInfo(
                        name=col.name,
                        type=str(col.type),
                        nullable=col.nullable,
                        primary_key=col.primary_key,
                        server_default=str(col.server_default) if col.server_default else None,
                    )
                    schema.columns[col.name] = col_info
            except Exception as e:
                print(f"[WARN] Gagal inspect {cls.__name__}: {e}")
                continue

            schemas[table_name] = schema

    return schemas


def parse_migration_file(filepath: Path) -> list[tuple[str, str, dict[str, Any]]]:
    """
    Parse file migration, return list operasi dengan format:
    ('create_table', table_name, {'col1': ColumnInfo, ...})
    ('add_column', table_name, {'col_name': ColumnInfo})
    ('drop_column', table_name, 'col_name')
    ('alter_column', table_name, 'col_name', new_info)
    """
    operations = []
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"[ERROR] SyntaxError di {filepath}: {e}")
        return operations

    # Cari panggilan op.create_table, op.add_column, op.drop_column, op.alter_column
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # op.create_table
        if isinstance(node.func, ast.Attribute) and node.func.attr == "create_table":
            # arg pertama adalah nama tabel (string literal)
            if not node.args:
                continue
            table_name_node = node.args[0]
            if isinstance(table_name_node, ast.Constant) and isinstance(table_name_node.value, str):
                table_name = table_name_node.value
                columns = {}
                # arg selanjutnya adalah kolom-kolom (sa.Column(...))
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "Column":
                        col_info = parse_column_call(arg)
                        if col_info:
                            columns[col_info.name] = col_info
                operations.append(("create_table", table_name, columns))
        # op.add_column
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "add_column":
            if len(node.args) >= 2:
                table_name_node = node.args[0]
                col_node = node.args[1]
                if isinstance(table_name_node, ast.Constant) and isinstance(table_name_node.value, str):
                    table_name = table_name_node.value
                    if isinstance(col_node, ast.Call) and isinstance(col_node.func, ast.Attribute) and col_node.func.attr == "Column":
                        col_info = parse_column_call(col_node)
                        if col_info:
                            operations.append(("add_column", table_name, {col_info.name: col_info}))
        # op.drop_column
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "drop_column":
            if len(node.args) >= 2:
                table_name_node = node.args[0]
                col_name_node = node.args[1]
                if isinstance(table_name_node, ast.Constant) and isinstance(table_name_node.value, str):
                    table_name = table_name_node.value
                    if isinstance(col_name_node, ast.Constant) and isinstance(col_name_node.value, str):
                        operations.append(("drop_column", table_name, col_name_node.value))
        # op.alter_column (sederhana, hanya detect)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "alter_column":
            if len(node.args) >= 2:
                table_name_node = node.args[0]
                col_name_node = node.args[1]
                if isinstance(table_name_node, ast.Constant) and isinstance(table_name_node.value, str):
                    table_name = table_name_node.value
                    if isinstance(col_name_node, ast.Constant) and isinstance(col_name_node.value, str):
                        # cari keyword arguments untuk tipe, nullable, dll.
                        new_info = {}
                        for kw in node.keywords:
                            if kw.arg == "type" and isinstance(kw.value, ast.Call):
                                # type expression, ambil nama tipe
                                if isinstance(kw.value.func, ast.Attribute):
                                    type_name = kw.value.func.attr
                                elif isinstance(kw.value.func, ast.Name):
                                    type_name = kw.value.func.id
                                else:
                                    type_name = str(kw.value)
                                new_info["type"] = type_name
                            elif kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
                                new_info["nullable"] = kw.value.value
                        operations.append(("alter_column", table_name, col_name_node.value, new_info))

    return operations


def parse_column_call(node: ast.Call) -> ColumnInfo | None:
    """Parsing ast.Call untuk sa.Column(...)"""
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "Column":
        return None
    # arg pertama: nama kolom (string)
    if not node.args:
        return None
    name_node = node.args[0]
    if not isinstance(name_node, ast.Constant) or not isinstance(name_node.value, str):
        return None
    name = name_node.value

    # tipe (arg kedua)
    type_str = "unknown"
    if len(node.args) >= 2:
        type_node = node.args[1]
        if isinstance(type_node, ast.Attribute):
            type_str = type_node.attr
        elif isinstance(type_node, ast.Name):
            type_str = type_node.id
        else:
            type_str = str(type_node)

    nullable = True
    primary_key = False
    server_default = None

    for kw in node.keywords:
        if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
            nullable = kw.value.value
        elif kw.arg == "primary_key" and isinstance(kw.value, ast.Constant):
            primary_key = kw.value.value
        elif kw.arg == "server_default" and isinstance(kw.value, ast.Constant):
            server_default = str(kw.value.value)

    return ColumnInfo(name=name, type=type_str, nullable=nullable, primary_key=primary_key, server_default=server_default)


def build_target_schema(migration_files: list[Path]) -> dict[str, TableSchema]:
    """Proses semua migration secara berurutan dan bangun skema database akhir."""
    schema: dict[str, TableSchema] = {}
    for filepath in sorted(migration_files):
        ops = parse_migration_file(filepath)
        for op in ops:
            op_type = op[0]
            if op_type == "create_table":
                table_name = op[1]
                columns = op[2]  # dict {name: ColumnInfo}
                if table_name not in schema:
                    schema[table_name] = TableSchema(columns=columns)
                else:
                    # Jika tabel sudah ada (misalnya karena migration sebelumnya), kita merge
                    existing = schema[table_name]
                    for col_name, col_info in columns.items():
                        existing.columns[col_name] = col_info
            elif op_type == "add_column":
                table_name = op[1]
                columns = op[2]
                if table_name not in schema:
                    schema[table_name] = TableSchema(columns={})
                for col_name, col_info in columns.items():
                    schema[table_name].columns[col_name] = col_info
            elif op_type == "drop_column":
                table_name = op[1]
                col_name = op[2]
                if table_name in schema and col_name in schema[table_name].columns:
                    del schema[table_name].columns[col_name]
            elif op_type == "alter_column":
                table_name = op[1]
                col_name = op[2]
                new_info = op[3]
                if table_name in schema and col_name in schema[table_name].columns:
                    col = schema[table_name].columns[col_name]
                    if "type" in new_info:
                        col.type = new_info["type"]
                    if "nullable" in new_info:
                        col.nullable = new_info["nullable"]
    return schema


def compare_schemas(orm_schemas: dict[str, TableSchema], migration_schemas: dict[str, TableSchema]) -> list[TableDiff]:
    diffs: list[TableDiff] = []
    all_tables = set(orm_schemas.keys()) | set(migration_schemas.keys())

    for table in all_tables:
        orm_cols = set(orm_schemas.get(table, TableSchema()).columns.keys())
        mig_cols = set(migration_schemas.get(table, TableSchema()).columns.keys())

        missing_in_orm = mig_cols - orm_cols
        missing_in_migration = orm_cols - mig_cols

        # Type mismatch hanya untuk kolom yang ada di kedua sisi
        type_mismatch = []
        common_cols = orm_cols & mig_cols
        for col in common_cols:
            orm_type = orm_schemas[table].columns[col].type
            mig_type = migration_schemas[table].columns[col].type
            if orm_type != mig_type:
                type_mismatch.append((col, orm_type, mig_type))

        if missing_in_orm or missing_in_migration or type_mismatch:
            diffs.append(TableDiff(
                table=table,
                missing_in_orm=list(missing_in_orm),
                missing_in_migration=list(missing_in_migration),
                type_mismatch=type_mismatch
            ))

    return diffs


def main():
    # 1. Ambil skema ORM
    print("Memuat skema ORM...")
    orm_schemas = get_orm_tables()
    print(f"ORM: {len(orm_schemas)} tabel ditemukan.")

    # 2. Ambil file migration
    mig_dir = PROJECT_ROOT / MIGRATIONS_DIR
    if not mig_dir.exists():
        print(f"[ERROR] Direktori migration '{mig_dir}' tidak ditemukan.")
        sys.exit(2)

    migration_files = list(mig_dir.glob("*.py"))
    if not migration_files:
        print("[WARN] Tidak ada file migration ditemukan.")
        sys.exit(0)

    print(f"Migration: {len(migration_files)} file ditemukan.")

    # 3. Bangun skema target dari migration
    print("Memproses migration...")
    migration_schemas = build_target_schema(migration_files)

    # 4. Bandingkan
    diffs = compare_schemas(orm_schemas, migration_schemas)

    # 5. Laporan
    if not diffs:
        print("\n✅ Selamat! Semua tabel dan kolom sinkron antara ORM dan migration.")
        sys.exit(0)

    print("\n❌ Ditemukan ketidaksesuaian:")
    for diff in diffs:
        print(f"\n--- Tabel: {diff.table} ---")
        if diff.missing_in_orm:
            print(f"  Kolom di migration TAPI TIDAK di ORM: {', '.join(diff.missing_in_orm)}")
        if diff.missing_in_migration:
            print(f"  Kolom di ORM TAPI TIDAK di migration: {', '.join(diff.missing_in_migration)}")
        if diff.type_mismatch:
            for col, orm_type, mig_type in diff.type_mismatch:
                print(f"  Tipe berbeda untuk kolom '{col}': ORM={orm_type}, Migration={mig_type}")

    sys.exit(1)


if __name__ == "__main__":
    main()
