#!/usr/bin/env python3
"""
🛡️ S+ GRADE DATABASE INTEGRITY & RUNTIME INTROSPECTION AUDITOR (v13) 🛡️
======================================================================
- Fix: import select dari sqlalchemy di live DB test
- Fix: pengecekan DATABASE_URL sebelum --apply
- Instruksi manual apply lebih jelas
"""

from __future__ import annotations

import ast
import enum
import importlib
import inspect
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path

# ============================================================
# Pastikan checker/core bisa diimport
# ============================================================
ROOT = Path(__file__).resolve().parent.parent
CHECKER_CORE = ROOT / "checker" / "core"
if str(CHECKER_CORE) not in sys.path:
    sys.path.insert(0, str(CHECKER_CORE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from rca import Category, ErrorCode, RCAEngine, RCAResult, Severity, analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    try:
        from checker.core.rca import (
            Category,
            ErrorCode,
            RCAEngine,
            RCAResult,
            Severity,
            analyze_exception,
        )
        RCA_AVAILABLE = True
    except ImportError:
        RCA_AVAILABLE = False
        RCAEngine = None
        Severity = None
        RCAResult = None
        Category = None
        ErrorCode = None
        print("WARNING: RCAEngine not found. RCA analysis disabled.", file=sys.stderr)

# ============================================================
# Warna terminal
# ============================================================
try:
    import colorama
    colorama.init(autoreset=True)
    RED = colorama.Fore.RED
    GREEN = colorama.Fore.GREEN
    YELLOW = colorama.Fore.YELLOW
    CYAN = colorama.Fore.CYAN
    MAGENTA = colorama.Fore.MAGENTA
    WHITE = colorama.Fore.WHITE
    BOLD = colorama.Style.BRIGHT
    RESET = colorama.Style.RESET_ALL
except ImportError:
    RED = GREEN = YELLOW = CYAN = MAGENTA = WHITE = BOLD = RESET = ""

# ============================================================
# Konfigurasi jalur
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT = PROJECT_ROOT
INFRA_ORM_DIR = ROOT / "infrastructure" / "persistence_orm"
MIGRATIONS_VERSIONS_DIR = ROOT / "migrations" / "versions"
ALEMBIC_INI = ROOT / "alembic.ini"

def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)

def banner(txt: str, w: int = 78) -> str:
    ln = "─" * w
    return f"\n{BOLD}{CYAN}{ln}\n  {txt}\n{ln}{RESET}"

# ============================================================
# IGNORE LIST
# ============================================================
IGNORE_TABLES = {
    "iam_login_attempt",
    "iam_user_legal_entity",
    "outbox_relay_metrics",
    "outbox_kafka_partition_checkpoint",
    "hedging_relationship",
    "derivative_instrument",
    "fair_value_hierarchy",
    "ledger_entry_partitioned",
    "journal_line_partitioned",
    "outbox_relay_checkpoint",
    "outbox_dead_letter",
    "integrity_check_result",
    "aggregate_snapshot",
    "purchase_order_lines",
    "sales_order_lines",
    "delivery_order_lines",
    "coretax_webhook_inbound",
    "coretax_audit_log",
    "payroll_payslip",
    "umkm_business_profile",
    "bank_reconciliation",
    "coretax_spt_electronic",
    "asset_category",
    "stock_opname_lines",
    "ledger_entry_",
    "journal_line_",
}

# ============================================================
# 1. ALEMBIC GRAPH INTROSPECTION
# ============================================================
def audit_alembic_graph() -> tuple[list[str], list[str], list[str]]:
    heads: list[str] = []
    errors: list[str] = []
    revisions_log: list[str] = []

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        if not ALEMBIC_INI.exists():
            errors.append(f"alembic.ini tidak ditemukan di {ALEMBIC_INI}")
            return heads, errors, revisions_log

        cfg = Config(str(ALEMBIC_INI))
        script_dir = ScriptDirectory.from_config(cfg)

        heads = script_dir.get_heads()
        for rev in script_dir.walk_revisions():
            revisions_log.append(f"Revision: {rev.revision} (Parent: {rev.down_revision})")

    except Exception as e:
        errors.append(f"Alembic introspection error: {e}\n{traceback.format_exc()}")

    return heads, errors, revisions_log

# ============================================================
# 2. IMPORT ORM MODULES
# ============================================================
def import_all_orm_modules() -> list[str]:
    errors: list[str] = []

    if not INFRA_ORM_DIR.exists():
        errors.append(f"Directory not found: {INFRA_ORM_DIR}")
        return errors

    for py_file in INFRA_ORM_DIR.glob("*.py"):
        if py_file.name.startswith("_") or py_file.name in {"base_model.py", "unit_of_work.py"}:
            continue

        mod_name = f"infrastructure.persistence_orm.{py_file.stem}"
        try:
            importlib.import_module(mod_name)
        except Exception:
            errors.append(f"Failed to import {mod_name}:\n{traceback.format_exc()}")

    return errors

# ============================================================
# 3. ENUM AUDIT
# ============================================================
def audit_runtime_and_ast_enums() -> list[str]:
    violations: list[str] = []

    try:
        import sqlalchemy
    except ImportError:
        return ["sqlalchemy not installed, enum audit skipped"]

    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("infrastructure.persistence_orm"):
            module = sys.modules[mod_name]
            if not module:
                continue
            try:
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if obj.__module__ == mod_name:
                        if issubclass(obj, sqlalchemy.types.Enum) and obj is not sqlalchemy.types.Enum:
                            violations.append(
                                f"Class '{name}' in {mod_name} inherits sqlalchemy.Enum directly, "
                                "should use Python enum.Enum and map via sa.Enum(PythonEnumClass)."
                            )
            except Exception:
                violations.append(f"Runtime inspection failed for {mod_name}:\n{traceback.format_exc()}")

    if INFRA_ORM_DIR.exists():
        for py_file in INFRA_ORM_DIR.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        for base in node.bases:
                            if isinstance(base, ast.Name) and base.id == "Enum":
                                pass
            except Exception as e:
                violations.append(f"AST parsing error in {py_file.name}: {e}")

    return violations

# ============================================================
# 4. ALEMBIC TABLE EXTRACTOR (AST)
# ============================================================
class AlembicTableExtractor(ast.NodeVisitor):
    def __init__(self):
        self.detected_tables: set[str] = set()
        self.create_table_re = re.compile(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(["\']?)(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)\1',
            re.IGNORECASE
        )

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == 'op':
                if node.func.attr == 'create_table':
                    if node.args and isinstance(node.args[0], ast.Constant):
                        self.detected_tables.add(str(node.args[0].value))
                elif node.func.attr == 'execute':
                    if node.args:
                        arg = node.args[0]
                        sql_text = None
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            sql_text = arg.value
                        elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
                            sql_text = self._concatenate_strings(arg)
                        if sql_text:
                            self._extract_tables_from_sql(sql_text)
        self.generic_visit(node)

    def _concatenate_strings(self, node: ast.BinOp) -> str | None:
        left = None
        right = None
        if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            left = node.left.value
        elif isinstance(node.left, ast.BinOp):
            left = self._concatenate_strings(node.left)
        else:
            return None

        if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            right = node.right.value
        elif isinstance(node.right, ast.BinOp):
            right = self._concatenate_strings(node.right)
        else:
            return None

        if left is not None and right is not None:
            return left + right
        return None

    def _extract_tables_from_sql(self, sql: str) -> None:
        for match in self.create_table_re.finditer(sql):
            table_name = match.group('table')
            if table_name:
                self.detected_tables.add(table_name)

# ============================================================
# 5. RCA KUSTOM
# ============================================================
def create_custom_rca_result(errors: list[str]) -> RCAResult | None:
    if not RCA_AVAILABLE or not errors:
        return None

    table_errors = [e for e in errors if "Table '" in e and "not in migrations" in e]
    if table_errors:
        table_names = [re.search(r"Table '([^']+)'", e).group(1) for e in table_errors if re.search(r"Table '([^']+)'", e)]
        tables_str = ", ".join(table_names[:5])
        root_cause = f"Tabel berikut terdefinisi di ORM tetapi tidak ada di migrasi: {tables_str}. Ini menyebabkan skema database tidak sinkron dengan model."
        suggested_fix = (
            "Jalankan 'alembic revision --autogenerate -m \"add missing tables\"' untuk membuat migration otomatis, "
            "atau gunakan opsi --fix pada auditor ini untuk membuat draft migration, lalu jalankan 'alembic upgrade head'."
        )
        evidence = table_errors[:5]

        return RCAResult(
            severity=Severity.HIGH if len(table_errors) > 1 else Severity.MEDIUM,
            category=Category.DATABASE,
            error_code=ErrorCode.DB_CONNECTION_FAIL,
            root_cause=root_cause,
            evidence=evidence,
            impact=["Aplikasi akan gagal saat mengakses tabel yang hilang."],
            suggested_fix=suggested_fix,
            confidence=0.9,
        )

    combined = "\n".join(errors[:3])
    return RCAResult(
        severity=Severity.HIGH,
        category=Category.UNKNOWN,
        error_code=ErrorCode.UNKNOWN,
        root_cause=f"ORM/Migration integrity issues: {combined[:200]}",
        evidence=errors[:5],
        suggested_fix="Periksa error detail dan sesuaikan migration.",
        confidence=0.7,
    )

def generate_rca_report(errors: list[str]) -> str:
    if not RCA_AVAILABLE:
        return "RCA not available."

    result = create_custom_rca_result(errors)
    if not result:
        return "RCA analysis returned no result."

    lines = [
        f"  {CYAN}Severity: {result.severity.value}{RESET}",
        f"  {CYAN}Root Cause: {result.root_cause[:300]}{RESET}",
    ]
    if result.suggested_fix:
        lines.append(f"  {CYAN}Suggested Fix: {result.suggested_fix[:300]}{RESET}")
    if result.evidence:
        lines.append(f"  {CYAN}Evidence: {result.evidence[0][:200]}{RESET}")
    return "\n".join(lines)

# ============================================================
# 6. DRAFT MIGRATION DAN EKSEKUSI
# ============================================================
def get_alembic_head() -> str | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        if not ALEMBIC_INI.exists():
            return None
        cfg = Config(str(ALEMBIC_INI))
        script_dir = ScriptDirectory.from_config(cfg)
        heads = script_dir.get_heads()
        return heads[0] if heads else None
    except Exception:
        return None

def generate_revision_id() -> str:
    return uuid.uuid4().hex[:12]

def get_column_type_string(col) -> str:
    from sqlalchemy import types
    if isinstance(col.type, types.Integer):
        return "sa.Integer()"
    elif isinstance(col.type, types.BigInteger):
        return "sa.BigInteger()"
    elif isinstance(col.type, types.String):
        length = col.type.length
        return f"sa.String({length})" if length else "sa.String()"
    elif isinstance(col.type, types.Text):
        return "sa.Text()"
    elif isinstance(col.type, types.DateTime):
        return "sa.DateTime()"
    elif isinstance(col.type, types.Date):
        return "sa.Date()"
    elif isinstance(col.type, types.Time):
        return "sa.Time()"
    elif isinstance(col.type, types.Boolean):
        return "sa.Boolean()"
    elif isinstance(col.type, types.Float):
        return "sa.Float()"
    elif isinstance(col.type, types.Numeric):
        precision = getattr(col.type, 'precision', None)
        scale = getattr(col.type, 'scale', None)
        if precision and scale:
            return f"sa.Numeric({precision}, {scale})"
        elif precision:
            return f"sa.Numeric({precision})"
        return "sa.Numeric()"
    elif isinstance(col.type, types.JSON):
        return "sa.JSON()"
    elif isinstance(col.type, types.Enum):
        return "sa.String(50)"
    else:
        return "sa.String(255)"

def create_intelligent_migration_draft(tables: list[str], metadata) -> str:
    if not tables:
        return ""

    head = get_alembic_head()
    revision_id = generate_revision_id()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        '"""auto_fix_missing_tables',
        '',
        f'Revision ID: {revision_id}',
        f'Revises: {head if head else "None"}',
        f'Create Date: {timestamp}',
        '"""',
        'from alembic import op',
        'import sqlalchemy as sa',
        '',
        '# revision identifiers, used by Alembic.',
        f"revision = '{revision_id}'",
        f"down_revision = {head!r}",
        "depends_on = None",
        '',
        "def upgrade():",
    ]

    for table_name in tables:
        if metadata is not None and table_name in metadata.tables:
            table = metadata.tables[table_name]
            lines.append(f"    op.create_table('{table_name}',")
            for col in table.columns:
                col_name = col.name
                col_type = get_column_type_string(col)
                nullable = "nullable=False" if not col.nullable else "nullable=True"
                lines.append(f"        sa.Column('{col_name}', {col_type}, {nullable}),")
            pk_cols = [c.name for c in table.primary_key.columns] if table.primary_key else []
            if pk_cols:
                pk_str = ", ".join(f"'{c}'" for c in pk_cols)
                lines.append(f"        sa.PrimaryKeyConstraint({pk_str}),")
            else:
                lines.append("        sa.PrimaryKeyConstraint('id'),")
            lines.append("    )")
        else:
            lines.append(f"    op.create_table('{table_name}',")
            lines.append("        sa.Column('id', sa.Integer(), nullable=False),")
            lines.append("        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),")
            lines.append("        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),")
            lines.append("        sa.PrimaryKeyConstraint('id'),")
            lines.append("    )")
        lines.append("")

    lines.append("def downgrade():")
    for table_name in tables:
        lines.append(f"    op.drop_table('{table_name}')")

    return "\n".join(lines)

def run_alembic_upgrade(verbose: bool = False) -> tuple[bool, str]:
    """Jalankan alembic upgrade head dan kembalikan (success, output)."""
    if not ALEMBIC_INI.exists():
        return False, "alembic.ini not found"
    cmd = ["alembic", "upgrade", "head"]
    env = os.environ.copy()
    env["ALEMBIC_CONFIG"] = str(ALEMBIC_INI)
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60, env=env)
        output = result.stdout + result.stderr
        if result.returncode == 0:
            return True, output
        else:
            return False, output
    except Exception as e:
        return False, str(e)

# ============================================================
# 7. MAIN AUDITOR
# ============================================================
def main(enable_rca: bool = True, auto_fix: bool = False, apply: bool = False, verbose: bool = False) -> int:
    print(banner("🛡️ S+ GRADE DATABASE INTEGRITY & RUNTIME INTROSPECTION AUDITOR (v13)"))
    print(f"  Project Root   : {ROOT}")
    print(f"  Python Runtime : {sys.version.split()[0]}")
    try:
        import sqlalchemy
        print(f"  SQLAlchemy v   : {sqlalchemy.__version__}")
    except ImportError:
        print(f"  {RED}SQLAlchemy not installed.{RESET}")
    print()

    # Hapus draft lama
    if MIGRATIONS_VERSIONS_DIR.exists():
        for old_file in MIGRATIONS_VERSIONS_DIR.glob("auto_fix_*.py"):
            try:
                old_file.unlink()
                print(f"  {YELLOW}⚠ Removed old draft file: {old_file.name}{RESET}")
            except Exception:
                pass

    critical_failures: list[str] = []
    warnings: list[str] = []

    # ---- Phase 1: Alembic Graph ----
    print("Executing Phase 1: Native Alembic Graph Introspection...")
    heads, graph_errors, revisions_log = audit_alembic_graph()

    if graph_errors:
        critical_failures.extend(graph_errors)
        for err in graph_errors:
            first_line = err.split('\n')[0]
            print(f"  {RED}✖ {first_line}{RESET}")
            if verbose:
                print(f"  {RED}{err}{RESET}")
        heads = []

    if len(heads) > 1:
        err = f"Multiple migration heads: {', '.join(heads)}"
        critical_failures.append(err)
        print(f"  {RED}✖ {err}{RESET}")
        print(f"     {YELLOW}💡 Run 'alembic merge heads' to resolve.{RESET}")
    elif len(heads) == 1:
        print(f"  {GREEN}✔ Single head: {heads[0]}{RESET}")
    else:
        if not graph_errors:
            print(f"  {YELLOW}⚠ No migration heads found.{RESET}")

    # ---- Phase 2: Import ORM ----
    print("\nExecuting Phase 2: Mass ORM Dynamic Module Ingestion...")
    import_errors = import_all_orm_modules()
    if import_errors:
        for err in import_errors:
            critical_failures.append(err)
            if verbose:
                print(f"  {RED}✖ {err}{RESET}")
            else:
                print(f"  {RED}✖ {err.split(chr(10))[0]}{RESET}")
        print(f"  {RED}✖ {len(import_errors)} import errors.{RESET}")
    else:
        print(f"  {GREEN}✔ All ORM modules loaded successfully.{RESET}")

    # ---- Phase 3: Metadata ----
    print("\nExecuting Phase 3: Metadata Extraction...")
    metadata = None
    orm_tables: set[str] = set()
    try:
        base_module = importlib.import_module("infrastructure.persistence_orm.base_model")
        Base = getattr(base_module, "Base", None)
        if Base is None:
            critical_failures.append("Base class missing from infrastructure.persistence_orm.base_model")
        else:
            metadata = Base.metadata
            orm_tables = set(metadata.tables.keys())
            print(f"  {GREEN}✔ Metadata loaded: {len(orm_tables)} tables.{RESET}")
    except Exception as e:
        err = f"Metadata extraction failed: {e}\n{traceback.format_exc()}"
        critical_failures.append(err)
        if verbose:
            print(f"  {RED}✖ {err}{RESET}")
        else:
            print(f"  {RED}✖ {err.split(chr(10))[0]}{RESET}")

    # ---- Phase 4: AST Migration ----
    print("\nExecuting Phase 4: AST Migration Table Extraction...")
    migration_tables: set[str] = set()
    if not MIGRATIONS_VERSIONS_DIR.exists():
        critical_failures.append(f"Directory missing: {MIGRATIONS_VERSIONS_DIR}")
        print(f"  {RED}✖ migrations/versions not found.{RESET}")
    else:
        for old_file in MIGRATIONS_VERSIONS_DIR.glob("auto_fix_*.py"):
            try:
                old_file.unlink()
            except Exception:
                pass
        for py_file in MIGRATIONS_VERSIONS_DIR.glob("*.py"):
            if py_file.name == "__init__.py" or py_file.name.startswith("auto_fix_"):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(py_file))
                extractor = AlembicTableExtractor()
                extractor.visit(tree)
                migration_tables.update(extractor.detected_tables)
            except Exception:
                err = f"AST parsing failed for {py_file.name}:\n{traceback.format_exc()}"
                critical_failures.append(err)
                if verbose:
                    print(f"  {RED}✖ {err}{RESET}")
                else:
                    print(f"  {RED}✖ {err.split(chr(10))[0]}{RESET}")
        print(f"  {GREEN}✔ Extracted {len(migration_tables)} tables from migrations.{RESET}")

    # ---- Phase 5: Schema alignment ----
    missing_tables: list[str] = []
    if metadata is not None:
        print("\nExecuting Phase 5: Schema Alignment (ORM vs Migrations)...")
        filtered_orm = orm_tables - IGNORE_TABLES
        filtered_mig = migration_tables - IGNORE_TABLES
        only_orm = filtered_orm - filtered_mig
        only_mig = filtered_mig - filtered_orm

        if only_orm:
            missing_tables = sorted(only_orm)
            for t in missing_tables:
                err = f"Table '{t}' in ORM but not in migrations."
                critical_failures.append(err)
                print(f"  {RED}✖ {err}{RESET}")
        if only_mig:
            for t in sorted(only_mig):
                warn = f"Table '{t}' in migrations but not in ORM."
                warnings.append(warn)
                print(f"  {YELLOW}⚠ {warn}{RESET}")
        if not only_orm and not only_mig:
            print(f"  {GREEN}✔ Perfect sync: {len(filtered_orm)} tables match.{RESET}")

    # ---- Phase 6: Enum ----
    print("\nExecuting Phase 6: Enum Safety Audit...")
    enum_violations = audit_runtime_and_ast_enums()
    if metadata is not None:
        try:
            import sqlalchemy
            for table_name, table in metadata.tables.items():
                for col in table.columns:
                    if isinstance(col.type, sqlalchemy.Enum):
                        if col.type.enum_class is None:
                            enum_violations.append(
                                f"Column '{table_name}.{col.name}' uses raw sa.Enum without Python enum binding."
                            )
                        elif not issubclass(col.type.enum_class, enum.Enum):
                            enum_violations.append(
                                f"Column '{table_name}.{col.name}' has class '{col.type.enum_class.__name__}' not derived from enum.Enum."
                            )
        except Exception as e:
            enum_violations.append(f"Enum check error: {e}")
    if enum_violations:
        for v in enum_violations:
            critical_failures.append(v)
            print(f"  {RED}✖ {v}{RESET}")
    else:
        print(f"  {GREEN}✔ No enum violations found.{RESET}")

    # ---- Phase 7: Constraints ----
    if metadata is not None:
        print("\nExecuting Phase 7: Constraint Auditing...")
        for table_name, table in metadata.tables.items():
            if not table.primary_key:
                err = f"Table '{table_name}' has no primary key."
                critical_failures.append(err)
                print(f"  {RED}✖ {err}{RESET}")
        fk_count = 0
        for table_name, table in metadata.tables.items():
            for fk in table.foreign_keys:
                fk_count += 1
                try:
                    target_table = fk.column.table.name
                    if target_table not in metadata.tables:
                        err = f"FK {table_name}.{fk.parent.name} references '{target_table}' not in metadata."
                        critical_failures.append(err)
                        print(f"  {RED}✖ {err}{RESET}")
                except Exception:
                    target_fullname = getattr(fk, 'target_fullname', '')
                    parts = target_fullname.split('.')
                    table_candidate = parts[-2] if len(parts) >= 3 else (parts[0] if parts else '')
                    if table_candidate not in metadata.tables:
                        err = f"FK resolution failed for {table_name} -> {target_fullname}"
                        critical_failures.append(err)
                        print(f"  {RED}✖ {err}{RESET}")
        print(f"  {GREEN}✔ Checked {fk_count} foreign keys.{RESET}")

    # ---- Phase 8: Dry-run ----
    print("\nExecuting Phase 8: Alembic Dry-Run...")
    if ALEMBIC_INI.exists():
        cmd = ["alembic", "upgrade", "head", "--sql"]
        env = os.environ.copy()
        env["ALEMBIC_CONFIG"] = str(ALEMBIC_INI)
        try:
            result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=30, env=env)
            if result.returncode != 0:
                err = f"Alembic dry-run failed: {result.stderr.strip() or result.stdout.strip()}"
                critical_failures.append(err)
                print(f"  {RED}✖ {err}{RESET}")
            else:
                print(f"  {GREEN}✔ Alembic dry-run SQL generation succeeded.{RESET}")
        except Exception as e:
            err = f"Alembic execution exception: {e}"
            critical_failures.append(err)
            print(f"  {RED}✖ {err}{RESET}")
    else:
        print(f"  {YELLOW}⚠ alembic.ini not found, skipping dry-run.{RESET}")

    # ---- Phase 9: Live DB Test (fix: import select) ----
    db_url = os.environ.get("DATABASE_URL")
    if db_url and metadata is not None:
        print("\nExecuting Phase 9: Live Database Test...")
        try:
            from sqlalchemy import create_engine, select  # <-- FIX: import select
            if "+asyncpg" in db_url:
                db_url = db_url.replace("+asyncpg", "")
            engine = create_engine(db_url, pool_size=1, pool_pre_ping=True)
            tables_list = list(metadata.tables.values())
            if tables_list:
                target = tables_list[0]
                with engine.connect() as conn:
                    conn.execute(select(target).limit(1))
                print(f"  {GREEN}✔ Live DB connection & query test passed.{RESET}")
        except Exception as e:
            err = f"Live DB test failed: {e}\n{traceback.format_exc()}"
            critical_failures.append(err)
            if verbose:
                print(f"  {RED}✖ {err}{RESET}")
            else:
                print(f"  {RED}✖ {err.split(chr(10))[0]}{RESET}")
    else:
        if db_url:
            print(f"  {YELLOW}⚠ DATABASE_URL set but metadata missing, skipping live test.{RESET}")
        else:
            print(f"  {YELLOW}⚠ DATABASE_URL not set, skipping live test.{RESET}")

    # ---- RCA ----
    if enable_rca and RCA_AVAILABLE and critical_failures:
        print("\nExecuting RCA Root Cause Analysis...")
        print(generate_rca_report(critical_failures))

    # ---- Auto-fix ----
    draft_created = False
    if auto_fix and missing_tables:
        print(f"\n{YELLOW}Generating intelligent draft migration for missing tables: {', '.join(missing_tables)}{RESET}")
        draft = create_intelligent_migration_draft(missing_tables, metadata)
        revision_id = generate_revision_id()
        draft_path = ROOT / "migrations" / "versions" / f"auto_fix_{revision_id}.py"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(draft, encoding="utf-8")
        print(f"  {GREEN}✔ Draft migration written to {draft_path}{RESET}")
        draft_created = True

        # Cek DATABASE_URL sebelum apply
        if apply:
            db_url = os.environ.get("DATABASE_URL")
            if not db_url:
                print(f"  {RED}✖ DATABASE_URL not set. Cannot apply migration.{RESET}")
                print(f"  {YELLOW}💡 Set DATABASE_URL environment variable or run manually: alembic upgrade head{RESET}")
            else:
                print(f"\n{YELLOW}Applying migration with 'alembic upgrade head'...{RESET}")
                success, output = run_alembic_upgrade(verbose)
                if success:
                    print(f"  {GREEN}✔ Migration applied successfully.{RESET}")
                    try:
                        draft_path.unlink()
                        print(f"  {GREEN}✔ Draft file removed.{RESET}")
                    except Exception:
                        pass
                else:
                    print(f"  {RED}✖ Migration failed:{RESET}\n{output}")
                    critical_failures.append(f"Alembic upgrade failed: {output}")
        else:
            print(f"  {YELLOW}⚠ Draft created. To apply, run: alembic upgrade head{RESET}")

    # ---- Final Report ----
    print(banner("SYSTEM AUDIT FINAL REPORT"))
    print(f"  Critical Failures : {len(critical_failures)}")
    print(f"  Warnings          : {len(warnings)}")

    if critical_failures:
        print(f"\n{RED}{BOLD}✖ AUDIT FAILED — {len(critical_failures)} critical issues found.{RESET}\n")
        if not verbose:
            print(f"{RED}Run with --verbose to see full tracebacks.{RESET}")
        print(f"{RED}Detailed errors:{RESET}")
        for idx, fail in enumerate(critical_failures, 1):
            print(f"\n[{idx}] ───────────────────────────────────")
            print(f"{RED}{fail}{RESET}")
        return 2
    else:
        print(f"\n{GREEN}{BOLD}🎉 ALL CHECKS PASSED — 100% integrity verified.{RESET}\n")
        return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Database & ORM Integrity Auditor")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    parser.add_argument("--fix", action="store_true", help="Generate draft migration for missing tables")
    parser.add_argument("--apply", action="store_true", help="Apply migration automatically after generating draft")
    parser.add_argument("--verbose", action="store_true", help="Show full tracebacks")
    args = parser.parse_args()

    enable_rca = not args.no_rca
    sys.exit(main(enable_rca=enable_rca, auto_fix=args.fix, apply=args.apply, verbose=args.verbose))
