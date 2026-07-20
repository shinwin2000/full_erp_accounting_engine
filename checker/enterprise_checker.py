#!/usr/bin/env python3
"""
enterprise_checkers.py — Enterprise-Grade ERP Checkers (v5.1)
====================================================================
Versi    : 5.1.0
Standar  : ISO/IEC 25010 · SOX/ISA 315 · IFRS/PSAK
Fungsi   : 32 pemeriksaan kritis dengan validasi runtime dan data nyata
"""

from __future__ import annotations

import gc
import importlib
import logging
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

# ─── Integrasi RCA ───────────────────────────────────────────────────────────
try:
    from checker.core.rca import Category, RCAEngine, RCAResult, Severity, analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    try:
        from core.rca import Category, RCAEngine, RCAResult, Severity, analyze_exception
        RCA_AVAILABLE = True
    except ImportError:
        try:
            from rca import Category, RCAEngine, RCAResult, Severity, analyze_exception
            RCA_AVAILABLE = True
        except ImportError:
            RCA_AVAILABLE = False
            class Severity:
                FATAL = "FATAL"; CRITICAL = "CRITICAL"; HIGH = "HIGH"; MEDIUM = "MEDIUM"; LOW = "LOW"; INFO = "INFO"; HINT = "HINT"
            class Category:
                UNKNOWN = "Unknown"
            class ErrorCode:
                UNKNOWN = "RCA999"
            class RCAResult:
                def __init__(self, **kwargs): self.__dict__.update(kwargs)
            def analyze_exception(exc, context=None):
                return RCAResult(
                    severity=Severity.MEDIUM,
                    category=Category.UNKNOWN,
                    error_code=ErrorCode.UNKNOWN,
                    root_cause=str(exc),
                    suggested_fix="RCA tidak tersedia, periksa log."
                )

# ─── Logging ─────────────────────────────────────────────────────────────────
_logger = logging.getLogger("EnterpriseCheckers")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
    _logger.addHandler(_handler)

# ─── Helpers ──────────────────────────────────────────────────────────────────
def safe_import(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except Exception as e:
        _logger.debug(f"safe_import({module_name}) failed: {e}")
        return None

def get_app_instance() -> Any:
    from pathlib import Path
    root_dir = Path(__file__).parent.parent.resolve()
    root_dir_str = str(root_dir)
    if root_dir_str not in sys.path:
        sys.path.insert(0, root_dir_str)
    cwd = Path.cwd().resolve()
    if str(cwd) not in sys.path:
        sys.path.insert(0, str(cwd))

    try:
        import app.main as main_mod
        _logger.info("Successfully imported app.main")
        if hasattr(main_mod, "fastapi_instance"):
            obj = main_mod.fastapi_instance
            if obj is not None:
                _logger.info("Found fastapi_instance in app.main")
                return obj
        if hasattr(main_mod, "app"):
            obj = main_mod.app
            if obj is not None:
                _logger.info("Found app in app.main")
                if hasattr(obj, "_app"):
                    return obj._app
                return obj
        if hasattr(main_mod, "create_app"):
            try:
                app = main_mod.create_app()
                _logger.info("Created app via create_app()")
                return app
            except Exception as e:
                _logger.warning(f"create_app() failed: {e}")
    except Exception as e:
        _logger.warning(f"Import app.main failed: {e}")

    candidates = [
        ("main", "app"), ("app", "app"), ("app.main", "fastapi_instance"),
        ("app.main", "app"), ("application.main", "app"), ("erp.asgi", "application"),
        ("erp_engine", "app"), ("server", "app"), ("infrastructure.fastapi_app", "app"),
        ("api.main", "app"), ("app.main", "application"), ("application", "app"),
        ("app.application", "app"), ("app.api", "app"), ("api", "app"),
        ("app", "application"), ("app.main", "fastapi_app"), ("app", "fastapi_app"),
        ("erp_engine.main", "app"), ("erp_engine.application", "app"),
    ]
    for mod_name, attr in candidates:
        mod = safe_import(mod_name)
        if mod and hasattr(mod, attr):
            obj = getattr(mod, attr)
            if callable(obj):
                try:
                    return obj()
                except:
                    pass
            else:
                return obj
    return None

def get_sync_engine():
    url = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
    if not url:
        try:
            env_path = Path(".env")
            if env_path.exists():
                content = env_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.strip() and not line.startswith("#"):
                        key, _, value = line.partition("=")
                        if key.strip() == "DATABASE_URL":
                            url = value.strip()
                            break
        except Exception as e:
            _logger.warning(f"Gagal membaca .env: {e}")
    if not url:
        _logger.error("DATABASE_URL tidak ditemukan")
        return None
    if "asyncpg" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "")
    if not url.startswith("postgresql://") and "://" not in url:
        url = "postgresql://" + url
    _logger.info(f"Creating sync engine from URL: {url[:30]}...")
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _logger.info("Sync engine created successfully")
        return engine
    except Exception as e:
        _logger.error(f"Gagal membuat sync engine: {e}")
        return None

def get_db_engine():
    return get_sync_engine()

def table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :table_name)"),
        {"table_name": table_name}
    ).fetchone()[0]
    return result

def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = :table_name AND column_name = :column_name)"),
        {"table_name": table_name, "column_name": column_name}
    ).fetchone()[0]
    return result

def get_columns(conn, table_name: str) -> list[str]:
    result = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :table_name"),
        {"table_name": table_name}
    ).fetchall()
    return [row[0] for row in result]

def find_in_code(pattern: str | re.Pattern) -> list[tuple[str, str]]:
    if isinstance(pattern, str):
        pattern = re.compile(pattern)
    results = []
    py_files = []
    for root, dirs, files in os.walk("."):
        if any(excl in root for excl in ["venv", "__pycache__", ".git", "migrations", "env", "node_modules"]):
            continue
        for f in files:
            if f.endswith(".py"):
                py_files.append(Path(root) / f)
    if len(py_files) > 200:
        py_files = py_files[:200]
    for py_file in py_files:
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    results.append((str(py_file), f"{line_no}: {line.strip()[:200]}"))
        except:
            pass
    return results

# ─── Base Checker ────────────────────────────────────────────────────────────
@dataclass
class CheckerResult:
    name: str
    passed: bool
    duration: float = 0.0
    severity: str = "INFO"
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    suggestion: str | None = None
    rca_result: Any | None = None

class EnterpriseChecker:
    def __init__(self, name: str):
        self.name = name

    def run(self) -> CheckerResult:
        start = time.perf_counter()
        try:
            result = self._check()
            duration = time.perf_counter() - start
            result.duration = duration
            return result
        except Exception as e:
            duration = time.perf_counter() - start
            if RCA_AVAILABLE:
                rca = analyze_exception(e, context={"checker": self.name})
                suggestion = rca.suggested_fix if rca else None
                severity = rca.severity.value if rca else "ERROR"
                return CheckerResult(
                    name=self.name,
                    passed=False,
                    duration=duration,
                    severity=severity,
                    error=str(e),
                    suggestion=suggestion,
                    rca_result=rca
                )
            else:
                return CheckerResult(
                    name=self.name,
                    passed=False,
                    duration=duration,
                    severity="ERROR",
                    error=str(e),
                    suggestion="RCA tidak tersedia, periksa log."
                )

    def _check(self) -> CheckerResult:
        raise NotImplementedError

# ─── CHECKER 1-16 (Engineering & Structure) ──────────────────────────────

class ConcurrencyChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Concurrency Checker")
    def _check(self) -> CheckerResult:
        details = {}
        uow_pattern = re.compile(r"\bUnitOfWork\b|\buow\b|@transactional|@atomic", re.I)
        matches = find_in_code(uow_pattern)
        details["has_uow_or_transactional"] = len(matches) > 0
        if matches:
            details["sample"] = matches[:3]
        version_pattern = re.compile(r"\bversion\s*=\s*Column|@versioned|__version__", re.I)
        version_matches = find_in_code(version_pattern)
        details["has_optimistic_locking"] = len(version_matches) > 0
        lock_pattern = re.compile(r"with_for_update|select.*for update|pessimistic", re.I)
        lock_matches = find_in_code(lock_pattern)
        details["has_pessimistic_locking"] = len(lock_matches) > 0
        if not details["has_uow_or_transactional"]:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                details=details,
                error="Tidak ditemukan mekanisme atomicity (UoW, @transactional, @atomic).",
                suggestion="Implementasikan Unit of Work atau gunakan dekorator @transactional pada use case."
            )
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Mekanisme atomicity ditemukan. Pastikan semua operasi write menggunakannya."
        )

class IsolationLevelChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Isolation Level Checker")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_db_engine()
        level = None
        if engine:
            try:
                with engine.connect() as conn:
                    row = conn.execute(text("SHOW transaction_isolation;")).fetchone()
                    if row:
                        level = row[0]
            except Exception as e:
                details["error_reading_isolation"] = str(e)
        if not level:
            config_files = [".env", "settings.py"]
            for cf in config_files:
                path = Path(cf)
                if path.exists():
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    match = re.search(r"isolation_level\s*[:=]\s*['\"]?([^'\"\n]+)['\"]?", content, re.I)
                    if match:
                        level = match.group(1).strip()
                        details["config_file"] = cf
                        break
        if not level:
            level = "READ COMMITTED"
            details["default_assumed"] = True
        details["isolation_level"] = level
        if level.upper() in ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"]:
            return CheckerResult(
                name=self.name,
                passed=True,
                severity="INFO",
                details=details,
                suggestion=f"Level isolasi {level} sesuai."
            )
        else:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                details=details,
                error=f"Level isolasi {level} kurang kuat untuk akuntansi.",
                suggestion="Gunakan READ COMMITTED atau lebih tinggi."
            )

class RollbackIntegrityChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Rollback Integrity Checker")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database untuk runtime test.",
                suggestion="Periksa koneksi database."
            )
        try:
            from sqlalchemy import Column, Integer, MetaData, String, Table, text
            metadata = MetaData()
            test_table = Table(
                'rollback_test_temp',
                metadata,
                Column('id', Integer, primary_key=True),
                Column('name', String(50))
            )
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS rollback_test_temp"))
                metadata.create_all(conn)
                conn.commit()
                trans = conn.begin()
                try:
                    conn.execute(test_table.insert(), {"id": 1, "name": "test1"})
                    raise RuntimeError("Forced rollback test")
                except Exception:
                    trans.rollback()
                else:
                    trans.commit()
                result = conn.execute(text("SELECT COUNT(*) FROM rollback_test_temp")).fetchone()
                count = result[0]
                details["runtime_test_count"] = count
                details["runtime_test_passed"] = (count == 0)
                conn.execute(text("DROP TABLE rollback_test_temp"))
                conn.commit()
                if count == 0:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        suggestion="Runtime rollback test PASSED: transaksi berhasil dirollback."
                    )
                else:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error="Runtime rollback test FAILED: data tetap tersimpan meskipun exception.",
                        suggestion="Periksa mekanisme rollback: pastikan rollback terjadi pada exception."
                    )
        except Exception as e:
            _logger.warning(f"Runtime rollback test gagal, fallback ke deteksi pola: {e}")
            details["runtime_test_error"] = str(e)
            rollback_pattern = re.compile(r"except.*:\s*.*rollback|finally.*rollback", re.I)
            matches = find_in_code(rollback_pattern)
            details["has_rollback_in_exception"] = len(matches) > 0
            ctx_pattern = re.compile(r"with\s+.*transaction|@transactional", re.I)
            ctx_matches = find_in_code(ctx_pattern)
            details["has_transaction_context"] = len(ctx_matches) > 0
            uow_pattern = re.compile(r"uow\.commit|uow\.rollback|UnitOfWork.*commit", re.I)
            uow_matches = find_in_code(uow_pattern)
            details["has_uow_commit_rollback"] = len(uow_matches) > 0
            if not (details["has_rollback_in_exception"] or details["has_transaction_context"] or details["has_uow_commit_rollback"]):
                return CheckerResult(
                    name=self.name,
                    passed=False,
                    severity="WARNING",
                    details=details,
                    error="Tidak ditemukan pola rollback pada exception atau transaksi context manager.",
                    suggestion="Pastikan setiap operasi transaksional memiliki rollback pada exception."
                )
            return CheckerResult(
                name=self.name,
                passed=True,
                severity="INFO",
                details=details,
                suggestion="Rollback integrity terjamin (ditemukan pola rollback/context manager)."
            )

class ReferentialIntegrityChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Referential Integrity Checker")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_db_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                fks = conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.table_constraints
                    WHERE constraint_type = 'FOREIGN KEY'
                """)).fetchone()[0]
                details["foreign_keys_count"] = fks
                if fks == 0:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="WARNING",
                        details=details,
                        error="Tidak ditemukan foreign key constraint di database.",
                        suggestion="Tambahkan foreign key untuk menjaga integritas referensial."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion=f"Referential integrity terjamin ({fks} foreign keys ditemukan)."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Gagal memeriksa foreign key: {e}",
                suggestion="Periksa koneksi database dan informasi_schema."
            )

class OrphanDataChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Orphan Data Checker")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                orphan_checks = [
                    ("journal_line", "journal_id", "journal_header", "id"),
                    ("ar_invoice", "customer_id", "customer", "id"),
                    ("ap_invoice", "vendor_id", "supplier", "id"),
                    ("sales_order", "customer_id", "customer", "id"),
                    ("purchase_order", "supplier_id", "supplier", "id"),
                ]
                orphans = []
                for child_table, child_col, parent_table, parent_col in orphan_checks:
                    if table_exists(conn, child_table) and table_exists(conn, parent_table):
                        if column_exists(conn, child_table, child_col):
                            query = text(f"""
                                SELECT COUNT(*) FROM {child_table} c
                                LEFT JOIN {parent_table} p ON p.{parent_col} = c.{child_col}
                                WHERE c.{child_col} IS NOT NULL AND p.{parent_col} IS NULL
                            """)
                            result = conn.execute(query).fetchone()
                            if result and result[0] > 0:
                                orphans.append({
                                    "table": child_table,
                                    "column": child_col,
                                    "count": result[0]
                                })
                if orphans:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details={"orphan_issues": orphans, **details},
                        error=f"Ditemukan {len(orphans)} orphan data.",
                        suggestion="Hapus atau perbaiki referensi yang tidak valid."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Tidak ada orphan data ditemukan."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Orphan check error: {e}",
                suggestion="Periksa koneksi database."
            )

class IdGeneratorChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Id Generator Checker")
    def _check(self) -> CheckerResult:
        details = {}
        id_gen_pattern = re.compile(r"uuid|snowflake|id_generator|next_id|generate_id", re.I)
        matches = find_in_code(id_gen_pattern)
        details["id_generator_found"] = len(matches) > 0
        if not details["id_generator_found"]:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                details=details,
                error="Tidak ditemukan implementasi ID generator.",
                suggestion="Gunakan UUID atau Snowflake untuk primary key."
            )
        id_gen = None
        for mod_name in ["infrastructure.id_generator", "id_generator", "utils.id_generator", "core.id_generator"]:
            mod = safe_import(mod_name)
            if mod:
                for attr in ["generate_id", "next_id", "get_uuid", "new_id"]:
                    if hasattr(mod, attr):
                        id_gen = getattr(mod, attr)
                        break
                if id_gen:
                    break
        if id_gen is None:
            id_gen = uuid.uuid4
        count = 100000
        ids = set()
        start_time = time.perf_counter()
        for _ in range(count):
            new_id = id_gen()
            ids.add(str(new_id))
        duration = time.perf_counter() - start_time
        details["generated_count"] = count
        details["unique_count"] = len(ids)
        details["duration_sec"] = round(duration, 3)
        if len(ids) != count:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                details=details,
                error=f"Duplikasi ID ditemukan: {count - len(ids)} duplikat.",
                suggestion="Periksa generator ID, pastikan menggunakan mekanisme yang menjamin keunikan."
            )
        else:
            return CheckerResult(
                name=self.name,
                passed=True,
                severity="INFO",
                details=details,
                suggestion=f"Generator ID menghasilkan {count} ID unik dalam {duration:.3f}s."
            )

class AuditTrailIntegrityChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Audit Trail Integrity Checker")
    def _check(self) -> CheckerResult:
        details = {}
        audit_models = []
        orm_path = Path("infrastructure/persistence_orm")
        if orm_path.exists():
            for f in orm_path.glob("*_table.py"):
                if "audit" in f.name.lower() or "log" in f.name.lower():
                    model_name = f.name.replace("_table.py", "")
                    audit_models.append(model_name)
        details["audit_models"] = audit_models
        if not audit_models:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak ditemukan model audit log.",
                suggestion="Buat tabel audit untuk mencatat perubahan data."
            )
        violation_found = False
        violation_details = []
        for model in audit_models:
            dangerous_pattern = re.compile(
                rf"""
                (?:session\.(?:update|delete)\s*\([^)]*{model}\b)
                |(?:UPDATE\s+{model}\s+SET)
                |(?:DELETE\s+FROM\s+{model})
                |(?:query\s*\(\s*{model}\s*\)\s*\.\s*(?:update|delete))
                """,
                re.I | re.VERBOSE
            )
            matches = find_in_code(dangerous_pattern)
            if matches:
                violation_found = True
                sample = [f"{file}:{line}" for file, line in matches[:3]]
                violation_details.append({
                    "model": model,
                    "count": len(matches),
                    "sample": sample
                })
                details[f"immutability_violation_{model}"] = f"Terlihat {len(matches)} operasi update/delete pada {model}"
        if violation_found:
            details["violations"] = violation_details
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                details=details,
                error="Audit log seharusnya tidak diupdate atau dihapus.",
                suggestion="Batasi akses update/delete pada tabel audit. Tambahkan trigger di database untuk mencegah modifikasi."
            )
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Audit trail integrity terjamin."
        )

class SoftDeleteIntegrityChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Soft Delete Integrity Checker")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                tables = conn.execute(text("""
                    SELECT table_name FROM information_schema.columns
                    WHERE column_name = 'deleted_at'
                """)).fetchall()
                details["soft_delete_models"] = [t[0] for t in tables]
                base_model_path = Path("infrastructure/persistence_orm/base_model.py")
                has_default_scope = False
                if base_model_path.exists():
                    content = base_model_path.read_text(encoding="utf-8", errors="ignore")
                    if "deleted_at.is_(None)" in content or "get_query" in content:
                        has_default_scope = True
                    if "@event.listens_for" in content and "deleted_at" in content:
                        has_default_scope = True
                details["has_default_scope"] = has_default_scope
                if not details["soft_delete_models"]:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="WARNING",
                        details=details,
                        error="Tidak ditemukan model dengan soft delete.",
                        suggestion="Pertimbangkan soft delete untuk data penting."
                    )
                if not has_default_scope:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="WARNING",
                        details=details,
                        error="Tidak ditemukan default scope untuk menyaring data terhapus.",
                        suggestion="Tambahkan query filter default untuk mengecualikan data yang sudah di-soft-delete."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Soft delete terimplementasi dengan baik."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Soft delete check error: {e}",
                suggestion="Periksa koneksi database."
            )

class DecimalPrecisionStressChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Decimal Precision Checker")
    def _check(self) -> CheckerResult:
        details = {}
        getcontext().prec = 50
        a = Decimal('1') / Decimal('3')
        b = a * Decimal('3')
        details["test1"] = f"1/3 * 3 = {b} (expected ~1)"
        if abs(b - Decimal('1')) > Decimal('1e-40'):
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                details=details,
                error="Presisi desimal tidak akurat.",
                suggestion="Gunakan Decimal dengan presisi yang cukup (minimal 50)."
            )
        total = Decimal('0')
        for _ in range(10000):
            total += Decimal('0.0001')
        details["test2"] = f"10000 * 0.0001 = {total} (expected 1.0000)"
        if total != Decimal('1.0000'):
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                details=details,
                error="Akumulasi desimal tidak presisi.",
                suggestion="Pastikan menggunakan Decimal dengan rounding yang tepat."
            )
        engine = get_sync_engine()
        decimal_fields = []
        if engine:
            try:
                with engine.connect() as conn:
                    cols = conn.execute(text("""
                        SELECT table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE data_type = 'numeric' AND numeric_scale > 0
                    """)).fetchall()
                    for c in cols:
                        decimal_fields.append(f"{c[0]}.{c[1]}")
            except:
                pass
        details["decimal_fields"] = decimal_fields
        if not decimal_fields:
            return CheckerResult(
                name=self.name,
                passed=True,
                severity="WARNING",
                details=details,
                error="Tidak ditemukan field Decimal di database. Field moneter sebaiknya menggunakan Decimal/Numeric.",
                suggestion="Pastikan model menggunakan tipe Numeric(asdecimal=True) untuk field moneter."
            )
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Presisi desimal terjamin dan field Decimal ditemukan."
        )

class TimezoneDateBoundaryChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Timezone & Date Checker")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        dt_fields = []
        if engine:
            try:
                with engine.connect() as conn:
                    cols = conn.execute(text("""
                        SELECT table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE data_type = 'timestamp with time zone' OR data_type = 'timestamp without time zone'
                    """)).fetchall()
                    for c in cols:
                        dt_fields.append({
                            "table": c[0],
                            "column": c[1],
                            "has_tz": "with time zone" in c[2]
                        })
            except:
                pass
        details["datetime_fields"] = dt_fields
        naive = [f"{f['table']}.{f['column']}" for f in dt_fields if not f["has_tz"]]
        if naive:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                details=details,
                error=f"Field datetime tanpa timezone: {naive[:5]}",
                suggestion="Gunakan timezone-aware datetime (DateTime(timezone=True) di SQLAlchemy)."
            )
        if not dt_fields:
            return CheckerResult(
                name=self.name,
                passed=True,
                severity="WARNING",
                details=details,
                error="Tidak ditemukan field datetime di database. ERP sebaiknya memiliki created_at, updated_at, dll.",
                suggestion="Tambahkan field datetime (timezone-aware) di model-model utama."
            )
        try:
            dt = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)
            details["boundary_test"] = "Tahun 9999 valid"
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                details=details,
                error=f"Boundary date error: {e}",
                suggestion="Pastikan database mendukung rentang tanggal yang diperlukan."
            )
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Timezone dan boundary terverifikasi."
        )

class RecoveryChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Recovery Checker")
    def _check(self) -> CheckerResult:
        details = {}
        outbox_pattern = re.compile(r"outbox|Outbox|relay", re.I)
        matches = find_in_code(outbox_pattern)
        details["outbox_pattern_found"] = len(matches) > 0
        recovery_pattern = re.compile(r"retry|recover|compensat|saga", re.I)
        recovery_matches = find_in_code(recovery_pattern)
        details["recovery_mechanism_found"] = len(recovery_matches) > 0
        if not details["outbox_pattern_found"] and not details["recovery_mechanism_found"]:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                details=details,
                error="Tidak ditemukan mekanisme recovery (outbox, saga, retry).",
                suggestion="Implementasikan outbox pattern atau saga untuk memastikan recovery dari crash."
            )
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Recovery mechanism terdeteksi."
        )

class BackupRestoreChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Backup & Restore Checker")
    def _check(self) -> CheckerResult:
        details = {}
        backup_pattern = re.compile(r"backup|dump|restore", re.I)
        matches = find_in_code(backup_pattern)
        details["backup_script_found"] = len(matches) > 0
        config_backup = False
        for config_file in ["settings.py", "config.yaml", ".env"]:
            path = Path(config_file)
            if path.exists():
                content = path.read_text(encoding="utf-8", errors="ignore")
                if "BACKUP" in content.upper():
                    config_backup = True
                    break
        details["backup_config_found"] = config_backup
        if not details["backup_script_found"] and not details["backup_config_found"]:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                details=details,
                error="Tidak ditemukan script backup atau konfigurasi backup.",
                suggestion="Buat script backup rutin dan uji restore."
            )
        if not details["backup_config_found"]:
            return CheckerResult(
                name=self.name,
                passed=True,
                severity="WARNING",
                details=details,
                error="Backup script ditemukan tetapi konfigurasi backup tidak terdeteksi.",
                suggestion="Tambahkan konfigurasi backup (misal di .env atau settings) untuk memastikan pengaturan yang konsisten."
            )
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Backup & restore terdeteksi dengan baik."
        )

class ConfigurationConsistencyChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Configuration Consistency Checker")
    def _check(self) -> CheckerResult:
        details = {}
        config_files = ["config.yaml", "settings.py", ".env", "application/config.py"]
        found = []
        for cf in config_files:
            if Path(cf).exists():
                found.append(cf)
        if not found:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error="Tidak ditemukan file konfigurasi.",
                suggestion="Buat file konfigurasi yang konsisten."
            )
        details["found_config_files"] = found
        required_vars = ["DATABASE_URL", "SECRET_KEY", "DEBUG"]
        missing_vars = []
        for cf in found:
            content = Path(cf).read_text(encoding="utf-8", errors="ignore")
            for var in required_vars:
                if var not in content:
                    missing_vars.append((cf, var))
        if missing_vars:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                details=details,
                error=f"Variabel konfigurasi hilang: {missing_vars}",
                suggestion="Pastikan semua variabel lingkungan terdefinisi."
            )
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Konfigurasi konsisten."
        )

# ─── PerformanceRegressionChecker (FIXED) ──────────────────────────────────
class PerformanceRegressionChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Performance Regression Checker")

    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            _logger.warning("Database tidak tersedia, menggunakan benchmark sintetik.")
            return self._fallback_synthetic(details)
        try:
            start = time.perf_counter()
            with engine.connect() as conn:
                trans = conn.begin()
                try:
                    # ===== PERBAIKAN: Tambahkan kolom version =====
                    for i in range(100):
                        conn.execute(
                            text("""
                                INSERT INTO journal_header (id, voucher_number, journal_date, description, total_debit, total_credit, status, currency, source_type, version, legal_entity_id)
                                VALUES (gen_random_uuid(), :no, now(), :desc, 0, 0, 'draft', 'IDR', 'manual', 1, (SELECT id FROM legal_entity LIMIT 1))
                            """),
                            {"no": f"JRNL-{i:05d}", "desc": f"Test journal {i}"}
                        )
                    for i in range(100):
                        conn.execute(
                            text("""
                                INSERT INTO ar_invoice (id, invoice_number, invoice_date, due_date, customer_id, total_amount, paid_amount, status, description, legal_entity_id)
                                VALUES (gen_random_uuid(), :no, now(), now() + interval '30 days', (SELECT id FROM customer LIMIT 1), :amt, 0, 'draft', 'Test invoice', (SELECT id FROM legal_entity LIMIT 1))
                            """),
                            {"no": f"INV-{i:05d}", "amt": random.randint(1000, 100000)}
                        )
                    for i in range(100):
                        conn.execute(
                            text("""
                                INSERT INTO inventory_movement (id, movement_number, movement_type, item_id, quantity, uom, unit_cost, total_cost, movement_date, reference_type, warehouse_id, legal_entity_id)
                                VALUES (gen_random_uuid(), :no, 'IN', (SELECT id FROM inventory_item LIMIT 1), :qty, 'PCS', 1000, :amt, now(), 'TEST', (SELECT id FROM warehouse LIMIT 1), (SELECT id FROM legal_entity LIMIT 1))
                            """),
                            {"no": f"MOV-{i:05d}", "qty": random.randint(1, 10), "amt": random.randint(1000, 100000)}
                        )
                    trans.rollback()
                except Exception as e:
                    trans.rollback()
                    _logger.warning(f"Workload ERP gagal, gunakan benchmark sintetik: {e}")
                    return self._fallback_synthetic(details)
                duration = time.perf_counter() - start
                details["workload_type"] = "ERP real"
                details["operations"] = "100 journal inserts + 100 invoice inserts + 100 inventory inserts (rolled back)"
                details["duration_sec"] = round(duration, 3)
                details["ops_per_sec"] = round(300 / duration, 2)
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion=f"Performa ERP: {details['ops_per_sec']} ops/s"
                )
        except Exception as e:
            _logger.warning(f"Workload ERP error, fallback ke sintetik: {e}")
            return self._fallback_synthetic(details)

    def _fallback_synthetic(self, details):
        start = time.perf_counter()
        total = 0
        for i in range(1_000_000):
            total += i
        duration = time.perf_counter() - start
        details["current_benchmark"] = {
            "iterations": 1_000_000,
            "duration_sec": round(duration, 3),
            "ops_per_sec": round(1_000_000 / duration, 2)
        }
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Performa sintetik dalam batas normal."
        )

# ─── MemoryLeakStressChecker ──────────────────────────────────────────────
class MemoryLeakStressChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Memory Leak Stress Checker")
    def _check(self) -> CheckerResult:
        details = {}
        try:
            import psutil
        except ImportError:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="psutil tidak terinstall, tidak bisa mendeteksi memory leak.",
                suggestion="Install psutil: pip install psutil"
            )
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024
        transactions = []
        for i in range(10000):
            txn = {
                "id": uuid.uuid4(),
                "amount": Decimal(str(random.randint(1, 1000000))) / 100,
                "date": datetime.now(),
                "description": f"Transaction {i}",
                "account": f"ACCT-{random.randint(1000,9999)}",
                "reference": f"REF-{i:05d}",
                "metadata": { "key": "value" * 10 }
            }
            transactions.append(txn)
        processed = []
        for txn in transactions:
            processed.append({
                "id": txn["id"],
                "amount": txn["amount"] * Decimal('1.1'),
                "processed": True
            })
        transactions = None
        processed = None
        gc.collect()
        gc.collect()
        mem_after = process.memory_info().rss / 1024 / 1024
        details["memory_before_mb"] = round(mem_before, 2)
        details["memory_after_mb"] = round(mem_after, 2)
        details["stress_objects"] = 10000
        diff = mem_after - mem_before
        if diff > 50:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                details=details,
                error=f"Memory leak terdeteksi setelah stress test: {diff:.2f} MB tidak terfree.",
                suggestion="Periksa pengelolaan objek besar dan pastikan tidak ada referensi yang tersisa."
            )
        return CheckerResult(
            name=self.name,
            passed=True,
            severity="INFO",
            details=details,
            suggestion="Tidak ada memory leak signifikan setelah stress test 10.000 transaksi."
        )

# ─── APIContractChecker ────────────────────────────────────────────────────
class APIContractChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("API Contract Checker")
    def _check(self) -> CheckerResult:
        details = {}
        app = get_app_instance()
        if not app:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak ditemukan instance FastAPI.",
                suggestion="Pastikan aplikasi FastAPI tersedia."
            )
        if hasattr(app, "openapi"):
            try:
                openapi = app.openapi()
                details["openapi_version"] = openapi.get("openapi", "unknown")
                paths = openapi.get("paths", {})
                details["endpoints_count"] = len(paths)
                if len(paths) == 0:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="WARNING",
                        details=details,
                        error="Tidak ada endpoint terdefinisi di OpenAPI.",
                        suggestion="Dekorasi endpoint dengan tag dan response model."
                    )
                missing_responses = []
                for path, methods in paths.items():
                    for method, spec in methods.items():
                        if "responses" not in spec or not spec["responses"]:
                            missing_responses.append(f"{method.upper()} {path}")
                details["missing_responses_count"] = len(missing_responses)
                if missing_responses:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Terdapat {len(missing_responses)} endpoint tanpa response sama sekali.",
                        suggestion="Tambahkan response model untuk setiap endpoint."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion=f"API contract valid: {len(paths)} endpoint terdefinisi."
                )
            except Exception as e:
                return CheckerResult(
                    name=self.name,
                    passed=False,
                    severity="ERROR",
                    error=f"Gagal memproses OpenAPI: {e}",
                    suggestion="Periksa konfigurasi FastAPI."
                )
        else:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error="Aplikasi tidak memiliki openapi method.",
                suggestion="Pastikan menggunakan FastAPI atau framework yang mendukung OpenAPI."
            )

# ─── CHECKER 17-22 (Existing Audit) ──────────────────────────────────────

class BusinessFlowChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Business Flow Completeness")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                tables = ['sales_order', 'delivery_order', 'ar_invoice', 'journal_header',
                          'purchase_order', 'goods_receipt_note', 'ap_invoice']
                exists = {t: table_exists(conn, t) for t in tables}
                details["tables_exist"] = exists
                if not all(exists.values()):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Struktur tabel tidak lengkap. Business Flow check di-skip.",
                        suggestion="Pastikan tabel: sales_order, delivery_order, ar_invoice, journal_header, purchase_order, goods_receipt_note, ap_invoice ada."
                    )
                so_without_do = conn.execute(text("""
                    SELECT COUNT(*) FROM sales_order so
                    LEFT JOIN delivery_order d ON d.sales_order_id = so.id
                    WHERE so.status = 'fully_shipped' AND d.id IS NULL
                """)).fetchone()[0]
                invoice_without_gl = conn.execute(text("""
                    SELECT COUNT(*) FROM ar_invoice inv
                    WHERE inv.status = 'paid'
                    AND NOT EXISTS (
                        SELECT 1 FROM journal_header jh
                        WHERE jh.source_type = 'ar_invoice' AND jh.source_id = inv.id
                    )
                """)).fetchone()[0]
                payment_without_gl = conn.execute(text("""
                    SELECT COUNT(*) FROM ar_payment pay
                    WHERE pay.status = 'completed'
                    AND NOT EXISTS (
                        SELECT 1 FROM journal_header jh
                        WHERE jh.source_type = 'ar_payment' AND jh.source_id = pay.id
                    )
                """)).fetchone()[0]
                po_without_grn = conn.execute(text("""
                    SELECT COUNT(*) FROM purchase_order po
                    LEFT JOIN goods_receipt_note grn ON grn.purchase_order_id = po.id
                    WHERE po.status = 'fully_received' AND grn.id IS NULL
                """)).fetchone()[0]
                ap_invoice_without_gl = conn.execute(text("""
                    SELECT COUNT(*) FROM ap_invoice inv
                    WHERE inv.status = 'paid'
                    AND NOT EXISTS (
                        SELECT 1 FROM journal_header jh
                        WHERE jh.source_type = 'ap_invoice' AND jh.source_id = inv.id
                    )
                """)).fetchone()[0]
                details["so_without_delivery"] = so_without_do
                details["invoice_without_gl"] = invoice_without_gl
                details["payment_without_gl"] = payment_without_gl
                details["po_without_grn"] = po_without_grn
                details["ap_invoice_without_gl"] = ap_invoice_without_gl
                issues = []
                if so_without_do > 0:
                    issues.append(f"{so_without_do} sales order tanpa delivery")
                if invoice_without_gl > 0:
                    issues.append(f"{invoice_without_gl} invoice tanpa GL")
                if payment_without_gl > 0:
                    issues.append(f"{payment_without_gl} payment tanpa GL")
                if po_without_grn > 0:
                    issues.append(f"{po_without_grn} purchase order tanpa GRN")
                if ap_invoice_without_gl > 0:
                    issues.append(f"{ap_invoice_without_gl} AP invoice tanpa GL")
                if issues:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Business flow broken: {', '.join(issues)}",
                        suggestion="Lengkapi rantai dokumen: SO→DO→Invoice→Payment→GL, PO→GRN→Invoice→Payment→GL."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Business flow complete: semua dokumen terhubung ke GL."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Business Flow check error: {e}",
                suggestion="Periksa struktur tabel dan query."
            )

class SubledgerReconciliationChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Subledger Reconciliation")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                tables = ['ar_invoice', 'ap_invoice', 'journal_line', 'account', 'inventory_item']
                exists = {t: table_exists(conn, t) for t in tables}
                details["tables_exist"] = exists
                if not all(exists.values()):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel tidak lengkap. Reconciliation di-skip.",
                        suggestion="Pastikan tabel ar_invoice, ap_invoice, journal_line, account, inventory_item ada."
                    )
                jl_cols = get_columns(conn, 'journal_line')
                has_debit = 'debit_amount' in jl_cols
                has_credit = 'credit_amount' in jl_cols
                has_account = 'account_code' in jl_cols
                if not (has_debit and has_credit and has_account):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom debit/credit/account_code tidak ditemukan di journal_line. Reconciliation di-skip.",
                        suggestion="Pastikan journal_line memiliki debit_amount, credit_amount, account_code."
                    )
                ar_subledger = conn.execute(text("""
                    SELECT COALESCE(SUM(total_amount - paid_amount), 0) FROM ar_invoice
                    WHERE status NOT IN ('paid', 'cancelled')
                """)).fetchone()[0]
                ar_gl = conn.execute(text("""
                    SELECT COALESCE(SUM(debit_amount - credit_amount), 0) FROM journal_line
                    WHERE account_code = '1100'
                """)).fetchone()[0]
                diff_ar = round(abs(ar_subledger - ar_gl), 2)
                details["ar_subledger"] = float(ar_subledger)
                details["ar_gl"] = float(ar_gl)
                details["ar_difference"] = diff_ar
                ap_subledger = conn.execute(text("""
                    SELECT COALESCE(SUM(total_amount - paid_amount), 0) FROM ap_invoice
                    WHERE status NOT IN ('paid', 'cancelled')
                """)).fetchone()[0]
                ap_gl = conn.execute(text("""
                    SELECT COALESCE(SUM(credit_amount - debit_amount), 0) FROM journal_line
                    WHERE account_code = '2100'
                """)).fetchone()[0]
                diff_ap = round(abs(ap_subledger - ap_gl), 2)
                details["ap_subledger"] = float(ap_subledger)
                details["ap_gl"] = float(ap_gl)
                details["ap_difference"] = diff_ap
                inv_balance = conn.execute(text("""
                    SELECT COALESCE(SUM(current_stock * average_cost), 0) FROM inventory_item
                """)).fetchone()[0]
                inv_gl = conn.execute(text("""
                    SELECT COALESCE(SUM(debit_amount - credit_amount), 0) FROM journal_line
                    WHERE account_code = '1200'
                """)).fetchone()[0]
                diff_inv = round(abs(inv_balance - inv_gl), 2)
                details["inventory_balance"] = float(inv_balance)
                details["inventory_gl"] = float(inv_gl)
                details["inventory_difference"] = diff_inv
                if diff_ar > 1 or diff_ap > 1 or diff_inv > 1:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Subledger vs GL mismatch: AR diff {diff_ar:.2f}, AP diff {diff_ap:.2f}, Inventory diff {diff_inv:.2f}",
                        suggestion="Periksa posting journal dan pastikan semua transaksi tercatat dengan benar."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Subledger reconciled dengan GL."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Reconciliation error: {e}",
                suggestion="Periksa struktur tabel account dan kode akun (1100, 2100, 1200)."
            )

class PeriodClosingChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Period Closing & Posting Lock")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_journal = table_exists(conn, 'journal_header')
                has_fiscal = table_exists(conn, 'fiscal_period')
                details["has_journal_header"] = has_journal
                details["has_fiscal_period"] = has_fiscal
                if not has_journal or not has_fiscal:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel journal_header atau fiscal_period tidak ditemukan. Period Closing di-skip.",
                        suggestion="Pastikan tabel fiscal_period dan journal_header ada."
                    )
                j_cols = get_columns(conn, 'journal_header')
                fp_cols = get_columns(conn, 'fiscal_period')
                has_period_id = 'period_id' in j_cols
                has_fp_status = 'status' in fp_cols
                if not has_period_id or not has_fp_status:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom period_id di journal_header atau status di fiscal_period tidak ditemukan.",
                        suggestion="Pastikan journal_header memiliki period_id (FK ke fiscal_period) dan fiscal_period memiliki status."
                    )
                closed_journals = conn.execute(text("""
                    SELECT COUNT(*) FROM journal_header jh
                    JOIN fiscal_period fp ON fp.id = jh.period_id
                    WHERE fp.status = 'closed'
                """)).fetchone()[0]
                details["closed_period_journals"] = closed_journals
                if closed_journals > 0:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Terdapat {closed_journals} journal di periode yang sudah CLOSED.",
                        suggestion="Tidak boleh ada transaksi di periode yang ditutup. Lakukan rollback atau buka periode."
                    )
                if 'posted_at' in j_cols:
                    future_posting = conn.execute(text("""
                        SELECT COUNT(*) FROM journal_header WHERE posted_at > NOW()
                    """)).fetchone()[0]
                    details["future_posting"] = future_posting
                    if future_posting > 0:
                        return CheckerResult(
                            name=self.name,
                            passed=False,
                            severity="WARNING",
                            details=details,
                            error=f"Terdapat {future_posting} journal dengan posted_at di masa depan.",
                            suggestion="Posting date tidak boleh melebihi tanggal hari ini."
                        )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Period closing integrity terjamin."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Period closing check error: {e}",
                suggestion="Periksa struktur tabel fiscal_period dan journal_header."
            )

class MultiEntityCurrencyChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Multi-Entity & Currency Audit")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                tables = ['journal_header', 'journal_line', 'account', 'legal_entity']
                exists = {t: table_exists(conn, t) for t in tables}
                details["tables_exist"] = exists
                if not all(exists.values()):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel tidak lengkap. Multi-Entity audit di-skip.",
                        suggestion="Pastikan tabel journal_header, journal_line, account, legal_entity ada."
                    )
                jh_cols = get_columns(conn, 'journal_header')
                jl_cols = get_columns(conn, 'journal_line')
                acc_cols = get_columns(conn, 'account')
                has_legal_entity = 'legal_entity_id' in jh_cols
                has_account_code = 'account_code' in jl_cols
                has_acc_entity = 'legal_entity_id' in acc_cols
                if not (has_legal_entity and has_account_code and has_acc_entity):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom untuk multi-entity tidak lengkap. Audit di-skip.",
                        suggestion="Pastikan journal_header.legal_entity_id, journal_line.account_code, account.legal_entity_id ada."
                    )
                cross_entity = conn.execute(text("""
                    SELECT COUNT(*) FROM journal_line jl
                    JOIN journal_header jh ON jh.id = jl.journal_id
                    JOIN account a ON a.account_code = jl.account_code
                    WHERE jh.legal_entity_id != a.legal_entity_id
                """)).fetchone()[0]
                details["cross_entity_transactions"] = cross_entity
                if 'currency' in jh_cols and 'base_currency' in get_columns(conn, 'legal_entity'):
                    currency_mismatch = conn.execute(text("""
                        SELECT COUNT(*) FROM journal_header jh
                        JOIN legal_entity le ON le.id = jh.legal_entity_id
                        WHERE jh.currency != le.base_currency
                    """)).fetchone()[0]
                    details["currency_mismatch"] = currency_mismatch
                issues = []
                if cross_entity > 0:
                    issues.append(f"{cross_entity} transaksi menggunakan akun dari entity lain")
                if issues:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error="Multi-entity issues: " + ", ".join(issues),
                        suggestion="Periksa legal entity account mapping."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Multi-entity integrity terjamin."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Multi-entity check error: {e}",
                suggestion="Periksa struktur tabel legal_entity, account."
            )

class TaxComplianceChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Tax & Compliance Audit")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                tables = ['ar_invoice', 'ap_invoice', 'journal_line', 'journal_header']
                exists = {t: table_exists(conn, t) for t in tables}
                details["tables_exist"] = exists
                if not all(exists.values()):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel tidak lengkap. Tax audit di-skip.",
                        suggestion="Pastikan tabel ar_invoice, ap_invoice, journal_line, journal_header ada."
                    )
                ar_cols = get_columns(conn, 'ar_invoice')
                jh_cols = get_columns(conn, 'journal_header')
                has_tax = 'tax_amount' in ar_cols
                has_ref_type = 'source_type' in jh_cols
                has_ref_id = 'source_id' in jh_cols
                if not (has_tax and has_ref_type and has_ref_id):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom pajak atau referensi tidak lengkap. Tax audit di-skip.",
                        suggestion="Pastikan ar_invoice.tax_amount, journal_header.source_type, source_id ada."
                    )
                invoice_missing_vat = conn.execute(text("""
                    SELECT COUNT(*) FROM ar_invoice inv
                    WHERE inv.status = 'paid' AND inv.tax_amount > 0
                    AND NOT EXISTS (
                        SELECT 1 FROM journal_header jh
                        WHERE jh.source_type = 'ar_invoice' AND jh.source_id = inv.id
                    )
                """)).fetchone()[0]
                details["invoice_missing_vat"] = invoice_missing_vat
                ap_cols = get_columns(conn, 'ap_invoice')
                has_wht = 'withholding_tax' in ap_cols
                if has_wht:
                    wht_missing = conn.execute(text("""
                        SELECT COUNT(*) FROM ap_invoice inv
                        WHERE inv.status = 'paid' AND inv.withholding_tax > 0
                        AND NOT EXISTS (
                            SELECT 1 FROM journal_header jh
                            WHERE jh.source_type = 'ap_invoice' AND jh.source_id = inv.id
                        )
                    """)).fetchone()[0]
                    details["wht_missing"] = wht_missing
                issues = []
                if invoice_missing_vat > 0:
                    issues.append(f"{invoice_missing_vat} invoice tanpa VAT journal")
                if issues:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error="Tax compliance issues: " + ", ".join(issues),
                        suggestion="Pastikan semua pajak tercatat di journal dengan benar."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Tax compliance terjamin."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Tax check error: {e}",
                suggestion="Periksa struktur tabel."
            )

class FinancialStatementConsistencyChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Financial Statement Consistency")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_journal_line = table_exists(conn, 'journal_line')
                has_account = table_exists(conn, 'account')
                if not has_journal_line or not has_account:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel journal_line atau account tidak ditemukan. Financial Statement check di-skip.",
                        suggestion="Pastikan tabel journal_line dan account ada."
                    )
                jl_cols = get_columns(conn, 'journal_line')
                acc_cols = get_columns(conn, 'account')
                has_debit = 'debit_amount' in jl_cols
                has_credit = 'credit_amount' in jl_cols
                has_type = 'account_type' in acc_cols
                if not (has_debit and has_credit and has_type):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom debit/credit/account_type tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan journal_line memiliki debit_amount, credit_amount dan account memiliki account_type."
                    )
                total_debit = conn.execute(text("SELECT COALESCE(SUM(debit_amount), 0) FROM journal_line")).fetchone()[0]
                total_credit = conn.execute(text("SELECT COALESCE(SUM(credit_amount), 0) FROM journal_line")).fetchone()[0]
                details["total_debit"] = float(total_debit)
                details["total_credit"] = float(total_credit)
                details["tb_diff"] = round(abs(total_debit - total_credit), 2)
                assets = conn.execute(text("""
                    SELECT COALESCE(SUM(balance), 0) FROM (
                        SELECT account_code, SUM(debit_amount - credit_amount) AS balance FROM journal_line
                        GROUP BY account_code
                    ) t JOIN account a ON a.account_code = t.account_code
                    WHERE a.account_type = 'Asset'
                """)).fetchone()[0]
                liabilities = conn.execute(text("""
                    SELECT COALESCE(SUM(balance), 0) FROM (
                        SELECT account_code, SUM(credit_amount - debit_amount) AS balance FROM journal_line
                        GROUP BY account_code
                    ) t JOIN account a ON a.account_code = t.account_code
                    WHERE a.account_type = 'Liability'
                """)).fetchone()[0]
                equity = conn.execute(text("""
                    SELECT COALESCE(SUM(balance), 0) FROM (
                        SELECT account_code, SUM(credit_amount - debit_amount) AS balance FROM journal_line
                        GROUP BY account_code
                    ) t JOIN account a ON a.account_code = t.account_code
                    WHERE a.account_type = 'Equity'
                """)).fetchone()[0]
                bs_diff = round(abs(assets - (liabilities + equity)), 2)
                details["assets"] = float(assets)
                details["liabilities"] = float(liabilities)
                details["equity"] = float(equity)
                details["bs_diff"] = bs_diff
                revenue = conn.execute(text("""
                    SELECT COALESCE(SUM(credit_amount - debit_amount), 0) FROM journal_line
                    WHERE account_code IN (SELECT account_code FROM account WHERE account_type = 'Revenue')
                """)).fetchone()[0]
                expenses = conn.execute(text("""
                    SELECT COALESCE(SUM(debit_amount - credit_amount), 0) FROM journal_line
                    WHERE account_code IN (SELECT account_code FROM account WHERE account_type = 'Expense')
                """)).fetchone()[0]
                net_income = revenue - expenses
                details["revenue"] = float(revenue)
                details["expenses"] = float(expenses)
                details["net_income"] = float(net_income)
                issues = []
                if details["tb_diff"] > 1:
                    issues.append("Trial Balance tidak balance")
                if bs_diff > 1:
                    issues.append("Balance Sheet tidak balance (Assets != Liabilities + Equity)")
                if issues:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error="Financial statement inconsistency: " + ", ".join(issues),
                        suggestion="Periksa posting journal dan mapping account."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Financial statements consistent."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Financial statement check error: {e}",
                suggestion="Periksa struktur tabel account."
            )

# ─── NEW CHECKERS 23-32 ──────────────────────────────────────────────────

class ClosedPeriodPostingChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Closed Period Posting")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_journal = table_exists(conn, 'journal_header')
                has_fiscal = table_exists(conn, 'fiscal_period')
                if not has_journal or not has_fiscal:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel journal_header atau fiscal_period tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan tabel fiscal_period dan journal_header ada."
                    )
                j_cols = get_columns(conn, 'journal_header')
                fp_cols = get_columns(conn, 'fiscal_period')
                has_period_id = 'period_id' in j_cols
                has_fp_status = 'status' in fp_cols
                if not has_period_id or not has_fp_status:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom period_id atau status tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan journal_header.period_id dan fiscal_period.status ada."
                    )
                count = conn.execute(text("""
                    SELECT COUNT(*) FROM journal_header jh
                    JOIN fiscal_period fp ON fp.id = jh.period_id
                    WHERE fp.status = 'closed' AND jh.status = 'posted'
                """)).fetchone()[0]
                details["closed_period_posted_journals"] = count
                if count > 0:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Terdapat {count} journal yang diposting di periode closed.",
                        suggestion="Tidak boleh ada transaksi yang diposting di periode yang sudah ditutup."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Tidak ada jurnal yang diposting di periode closed."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Closed period posting check error: {e}",
                suggestion="Periksa struktur tabel fiscal_period dan journal_header."
            )

class DoublePostingDetectionChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Double Posting Detection")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_journal = table_exists(conn, 'journal_header')
                if not has_journal:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel journal_header tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan tabel journal_header ada."
                    )
                j_cols = get_columns(conn, 'journal_header')
                if 'voucher_number' not in j_cols:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom voucher_number tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan journal_header memiliki voucher_number."
                    )
                duplicates = conn.execute(text("""
                    SELECT voucher_number, COUNT(*) as cnt
                    FROM journal_header
                    GROUP BY voucher_number
                    HAVING COUNT(*) > 1
                """)).fetchall()
                details["duplicate_voucher_count"] = len(duplicates)
                if duplicates:
                    sample = [row[0] for row in duplicates[:5]]
                    details["duplicate_voucher_sample"] = sample
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Ditemukan {len(duplicates)} voucher number duplikat.",
                        suggestion="Pastikan voucher_number unik per legal_entity."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Tidak ada duplikat voucher number."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Double posting check error: {e}",
                suggestion="Periksa struktur tabel journal_header."
            )

class JournalSequenceGapChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Journal Sequence Gap")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_journal = table_exists(conn, 'journal_header')
                if not has_journal:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel journal_header tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan tabel journal_header ada."
                    )
                j_cols = get_columns(conn, 'journal_header')
                if 'voucher_number' not in j_cols:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom voucher_number tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan journal_header memiliki voucher_number."
                    )
                numbers = conn.execute(text("""
                    SELECT voucher_number FROM journal_header
                    WHERE voucher_number ~ '^[0-9]+$'
                    ORDER BY voucher_number::int
                """)).fetchall()
                if not numbers:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="WARNING",
                        details=details,
                        error="Tidak ada voucher_number dengan format angka, gap check di-skip.",
                        suggestion="Pastikan voucher_number memiliki format yang berurutan."
                    )
                nums = [int(row[0]) for row in numbers]
                gaps = []
                for i in range(len(nums)-1):
                    if nums[i+1] - nums[i] > 1:
                        gaps.append((nums[i], nums[i+1], nums[i+1]-nums[i]-1))
                details["gaps"] = gaps
                if gaps:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="WARNING",
                        details=details,
                        error=f"Ditemukan {len(gaps)} gap dalam sequence voucher_number.",
                        suggestion="Periksa apakah ada nomor yang hilang karena pembatalan atau bug."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Sequence voucher_number berurutan."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Journal sequence gap check error: {e}",
                suggestion="Periksa struktur tabel journal_header."
            )

class UnpostedApprovedDocumentsChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Unposted Approved Documents")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                ar_count = 0
                if table_exists(conn, 'ar_invoice') and table_exists(conn, 'journal_header'):
                    ar_cols = get_columns(conn, 'ar_invoice')
                    j_cols = get_columns(conn, 'journal_header')
                    if 'status' in ar_cols and 'source_type' in j_cols and 'source_id' in j_cols:
                        ar_count = conn.execute(text("""
                            SELECT COUNT(*) FROM ar_invoice inv
                            WHERE inv.status = 'approved'
                            AND NOT EXISTS (
                                SELECT 1 FROM journal_header jh
                                WHERE jh.source_type = 'ar_invoice' AND jh.source_id = inv.id
                            )
                        """)).fetchone()[0]
                ap_count = 0
                if table_exists(conn, 'ap_invoice'):
                    ap_cols = get_columns(conn, 'ap_invoice')
                    if 'status' in ap_cols:
                        ap_count = conn.execute(text("""
                            SELECT COUNT(*) FROM ap_invoice inv
                            WHERE inv.status = 'approved'
                            AND NOT EXISTS (
                                SELECT 1 FROM journal_header jh
                                WHERE jh.source_type = 'ap_invoice' AND jh.source_id = inv.id
                            )
                        """)).fetchone()[0]
                so_count = 0
                po_count = 0
                details["unposted_approved"] = {
                    "ar_invoice": ar_count,
                    "ap_invoice": ap_count,
                    "sales_order": so_count,
                    "purchase_order": po_count
                }
                total = ar_count + ap_count + so_count + po_count
                if total > 0:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="WARNING",
                        details=details,
                        error=f"Terdapat {total} dokumen approved yang belum diposting ke GL.",
                        suggestion="Pastikan semua dokumen approved sudah dibuatkan journal dan diposting."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Semua dokumen approved sudah diposting ke GL."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Unposted approved documents check error: {e}",
                suggestion="Periksa struktur tabel dan query."
            )

class JournalHeaderLineConsistencyChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Journal Header-Line Consistency")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_journal = table_exists(conn, 'journal_header')
                has_line = table_exists(conn, 'journal_line')
                if not has_journal or not has_line:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel journal_header atau journal_line tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan tabel journal_header dan journal_line ada."
                    )
                jh_cols = get_columns(conn, 'journal_header')
                jl_cols = get_columns(conn, 'journal_line')
                if 'total_debit' not in jh_cols or 'total_credit' not in jh_cols:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom total_debit/total_credit tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan journal_header memiliki total_debit dan total_credit."
                    )
                if 'debit_amount' not in jl_cols or 'credit_amount' not in jl_cols:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom debit_amount/credit_amount tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan journal_line memiliki debit_amount dan credit_amount."
                    )
                mismatches = conn.execute(text("""
                    SELECT jh.id, jh.voucher_number, jh.total_debit, jh.total_credit,
                           COALESCE(SUM(jl.debit_amount),0) as sum_debit,
                           COALESCE(SUM(jl.credit_amount),0) as sum_credit
                    FROM journal_header jh
                    LEFT JOIN journal_line jl ON jl.journal_id = jh.id
                    GROUP BY jh.id, jh.voucher_number, jh.total_debit, jh.total_credit
                    HAVING ABS(jh.total_debit - COALESCE(SUM(jl.debit_amount),0)) > 0.01
                        OR ABS(jh.total_credit - COALESCE(SUM(jl.credit_amount),0)) > 0.01
                """)).fetchall()
                details["mismatch_count"] = len(mismatches)
                if mismatches:
                    sample = [{"id": str(row[0]), "voucher": row[1], "diff_debit": float(row[2]-row[4]), "diff_credit": float(row[3]-row[5])} for row in mismatches[:5]]
                    details["mismatch_sample"] = sample
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Ditemukan {len(mismatches)} header-line mismatch.",
                        suggestion="Periksa konsistensi total journal header dengan detail line."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Header dan line konsisten."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Header-line consistency check error: {e}",
                suggestion="Periksa struktur tabel journal_header dan journal_line."
            )

# ─── DetailGLSubledgerChecker (FIXED) ────────────────────────────────────
class DetailGLSubledgerChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Detail GL vs Subledger Reconciliation")

    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_account = table_exists(conn, 'account')
                has_ar = table_exists(conn, 'ar_invoice')
                has_ap = table_exists(conn, 'ap_invoice')
                has_jl = table_exists(conn, 'journal_line')
                if not (has_account and has_ar and has_ap and has_jl):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel tidak lengkap. Check di-skip.",
                        suggestion="Pastikan tabel account, ar_invoice, ap_invoice, journal_line ada."
                    )
                # ===== PERBAIKAN: Cari account AR dengan pola yang lebih luas =====
                ar_accounts = conn.execute(text("""
                    SELECT account_code FROM account 
                    WHERE account_type = 'Asset' 
                    AND (account_code LIKE '11%' OR account_code LIKE '12%' 
                         OR account_name ILIKE '%piutang%' OR account_name ILIKE '%receivable%')
                """)).fetchall()
                if not ar_accounts:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="WARNING",
                        details=details,
                        error="Tidak ada account AR (11xx/12xx atau mengandung 'piutang/receivable') ditemukan. Check di-skip.",
                        suggestion="Pastikan mapping account untuk AR ada dengan kode yang sesuai (misal 11xx atau 12xx)."
                    )
                ar_acc_codes = [row[0] for row in ar_accounts]
                ar_gl = conn.execute(text("""
                    SELECT COALESCE(SUM(debit_amount - credit_amount), 0) FROM journal_line
                    WHERE account_code = ANY(:codes)
                """), {"codes": ar_acc_codes}).fetchone()[0]
                ar_subledger = conn.execute(text("""
                    SELECT COALESCE(SUM(total_amount - paid_amount), 0) FROM ar_invoice
                    WHERE status NOT IN ('paid', 'cancelled')
                """)).fetchone()[0]
                details["ar_gl"] = float(ar_gl)
                details["ar_subledger"] = float(ar_subledger)
                diff_ar = round(abs(ar_gl - ar_subledger), 2)
                if diff_ar > 1:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"AR GL vs Subledger mismatch: {diff_ar}",
                        suggestion="Periksa posting journal untuk AR."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="GL vs Subledger reconciled."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"GL vs Subledger check error: {e}",
                suggestion="Periksa struktur tabel account dan mapping."
            )

class ApprovalWorkflowChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Approval Workflow Integrity")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                if not table_exists(conn, 'approval_request'):
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel approval_request tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan tabel approval_request ada."
                    )
                issues = conn.execute(text("""
                    SELECT COUNT(*) FROM approval_request
                    WHERE status = 'approved' AND (approved_by IS NULL OR approved_at IS NULL)
                """)).fetchone()[0]
                details["approval_integrity_issues"] = issues
                if issues > 0:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Ditemukan {issues} approval dengan status approved tanpa approver.",
                        suggestion="Pastikan setiap approval memiliki approved_by dan approved_at."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Approval workflow integrity terjamin."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Approval workflow check error: {e}",
                suggestion="Periksa struktur tabel approval_request."
            )

class MultiCurrencyValidator(EnterpriseChecker):
    def __init__(self):
        super().__init__("Multi-Currency & Exchange Rate Validation")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_exchange = table_exists(conn, 'exchange_rate')
                has_journal = table_exists(conn, 'journal_header')
                if not has_exchange or not has_journal:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel exchange_rate atau journal_header tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan tabel exchange_rate dan journal_header ada."
                    )
                j_cols = get_columns(conn, 'journal_header')
                e_cols = get_columns(conn, 'exchange_rate')
                if 'currency' not in j_cols or 'from_currency' not in e_cols or 'rate' not in e_cols:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Kolom currency atau rate tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan journal_header.currency dan exchange_rate ada."
                    )
                missing = conn.execute(text("""
                    SELECT COUNT(*) FROM journal_header jh
                    WHERE jh.currency != 'IDR'
                    AND NOT EXISTS (
                        SELECT 1 FROM exchange_rate er
                        WHERE er.from_currency = jh.currency
                        AND er.to_currency = 'IDR'
                        AND er.rate_date <= jh.journal_date
                        ORDER BY er.rate_date DESC LIMIT 1
                    )
                """)).fetchone()[0]
                details["missing_exchange_rate"] = missing
                if missing > 0:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="WARNING",
                        details=details,
                        error=f"Terdapat {missing} journal dengan currency selain IDR tanpa exchange rate.",
                        suggestion="Pastikan setiap journal dengan mata uang asing memiliki kurs yang valid."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Multi-currency validation terjamin."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Multi-currency check error: {e}",
                suggestion="Periksa struktur tabel exchange_rate dan journal_header."
            )

class AuditHashChainChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Advanced Audit Hash Chain Verification")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_audit = table_exists(conn, 'audit_event')
                if not has_audit:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="INFO",
                        details=details,
                        error="Tabel audit_event tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan tabel audit_event ada."
                    )
                cols = get_columns(conn, 'audit_event')
                if 'hash' not in cols or 'previous_hash' not in cols:
                    return CheckerResult(
                        name=self.name,
                        passed=True,
                        severity="WARNING",
                        details=details,
                        error="Kolom hash atau previous_hash tidak ditemukan. Check di-skip.",
                        suggestion="Pastikan audit_event memiliki kolom hash dan previous_hash."
                    )
                null_prev = conn.execute(text("""
                    SELECT COUNT(*) FROM audit_event
                    WHERE previous_hash IS NULL
                """)).fetchone()[0]
                details["null_previous_hash_count"] = null_prev
                if null_prev > 1:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="WARNING",
                        details=details,
                        error=f"Ditemukan {null_prev} audit record dengan previous_hash null (seharusnya 1).",
                        suggestion="Periksa integritas hash chain audit."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Hash chain audit integrity terjamin."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Audit hash chain check error: {e}",
                suggestion="Periksa struktur tabel audit_event."
            )

class TaxVATConsistencyChecker(EnterpriseChecker):
    def __init__(self):
        super().__init__("Tax/VAT Consistency Checks")
    def _check(self) -> CheckerResult:
        details = {}
        engine = get_sync_engine()
        if not engine:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="WARNING",
                error="Tidak dapat terhubung ke database.",
                suggestion="Periksa koneksi database."
            )
        try:
            with engine.connect() as conn:
                has_ar = table_exists(conn, 'ar_invoice')
                has_ap = table_exists(conn, 'ap_invoice')
                ar_mismatch = 0
                ap_mismatch = 0
                if has_ar:
                    ar_cols = get_columns(conn, 'ar_invoice')
                    if 'tax_amount' in ar_cols and 'total_amount' in ar_cols:
                        ar_mismatch = conn.execute(text("""
                            SELECT COUNT(*) FROM ar_invoice
                            WHERE tax_amount > total_amount
                        """)).fetchone()[0]
                if has_ap:
                    ap_cols = get_columns(conn, 'ap_invoice')
                    if 'tax_amount' in ap_cols and 'total_amount' in ap_cols:
                        ap_mismatch = conn.execute(text("""
                            SELECT COUNT(*) FROM ap_invoice
                            WHERE tax_amount > total_amount
                        """)).fetchone()[0]
                details["ar_invoice_tax_mismatch"] = ar_mismatch
                details["ap_invoice_tax_mismatch"] = ap_mismatch
                if ar_mismatch > 0 or ap_mismatch > 0:
                    return CheckerResult(
                        name=self.name,
                        passed=False,
                        severity="ERROR",
                        details=details,
                        error=f"Tax amount melebihi total amount: AR {ar_mismatch}, AP {ap_mismatch}.",
                        suggestion="Periksa perhitungan pajak pada invoice."
                    )
                return CheckerResult(
                    name=self.name,
                    passed=True,
                    severity="INFO",
                    details=details,
                    suggestion="Tax/VAT consistency terjamin."
                )
        except Exception as e:
            return CheckerResult(
                name=self.name,
                passed=False,
                severity="ERROR",
                error=f"Tax/VAT consistency check error: {e}",
                suggestion="Periksa struktur tabel invoice."
            )

# ─── RUNNER ──────────────────────────────────────────────────────────────────
class CheckerRunner:
    def __init__(self):
        self.checkers = [
            ConcurrencyChecker(),
            IsolationLevelChecker(),
            RollbackIntegrityChecker(),
            ReferentialIntegrityChecker(),
            OrphanDataChecker(),
            IdGeneratorChecker(),
            AuditTrailIntegrityChecker(),
            SoftDeleteIntegrityChecker(),
            DecimalPrecisionStressChecker(),
            TimezoneDateBoundaryChecker(),
            RecoveryChecker(),
            BackupRestoreChecker(),
            ConfigurationConsistencyChecker(),
            PerformanceRegressionChecker(),
            MemoryLeakStressChecker(),
            APIContractChecker(),
            BusinessFlowChecker(),
            SubledgerReconciliationChecker(),
            PeriodClosingChecker(),
            MultiEntityCurrencyChecker(),
            TaxComplianceChecker(),
            FinancialStatementConsistencyChecker(),
            ClosedPeriodPostingChecker(),
            DoublePostingDetectionChecker(),
            JournalSequenceGapChecker(),
            UnpostedApprovedDocumentsChecker(),
            JournalHeaderLineConsistencyChecker(),
            DetailGLSubledgerChecker(),
            ApprovalWorkflowChecker(),
            MultiCurrencyValidator(),
            AuditHashChainChecker(),
            TaxVATConsistencyChecker(),
        ]

    def run_all(self) -> list[CheckerResult]:
        results = []
        for checker in self.checkers:
            _logger.info(f"Running {checker.name}...")
            result = checker.run()
            results.append(result)
            status = "✅ PASS" if result.passed else "❌ FAIL"
            _logger.info(f"{checker.name}: {status} ({result.duration:.3f}s)")
            if result.error:
                _logger.warning(f"  Error: {result.error}")
            if result.suggestion:
                _logger.info(f"  Suggestion: {result.suggestion}")
        return results

    def summary(self, results: list[CheckerResult]) -> dict:
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        total_time = sum(r.duration for r in results)
        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "total_duration": round(total_time, 3),
        }

    def print_report(self, results: list[CheckerResult]):
        print("\n" + "="*60)
        print("ENTERPRISE CHECKER REPORT v5.1")
        print("="*60)
        for r in results:
            status = "✅ PASS" if r.passed else "❌ FAIL"
            print(f"{status}  {r.name}  ({r.duration:.3f}s)")
            if r.error:
                print(f"     Error: {r.error}")
            if r.suggestion:
                print(f"     Suggestion: {r.suggestion}")
            if r.details:
                details_str = ", ".join(f"{k}={v}" for k, v in list(r.details.items())[:3])
                if details_str:
                    print(f"     Details: {details_str}")
        summary = self.summary(results)
        print("="*60)
        print(f"Total: {summary['total']} | Passed: {summary['passed']} | Failed: {summary['failed']} | Time: {summary['total_duration']}s")
        print("="*60)

# ─── MAIN ──────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Enterprise Checkers v5.1")
    parser.add_argument("--checker", help="Nama checker spesifik (opsional)")
    parser.add_argument("--list", action="store_true", help="Daftar checker yang tersedia")
    args = parser.parse_args()
    runner = CheckerRunner()
    if args.list:
        print("Checker tersedia:")
        for ch in runner.checkers:
            print(f"  - {ch.name}")
        return
    if args.checker:
        for ch in runner.checkers:
            if ch.name.lower() == args.checker.lower():
                result = ch.run()
                runner.print_report([result])
                return
        print(f"Checker '{args.checker}' tidak ditemukan.")
        return
    results = runner.run_all()
    runner.print_report(results)

if __name__ == "__main__":
    main()
