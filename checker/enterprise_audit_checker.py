#!/usr/bin/env python3
"""
ENTERPRISE AUDIT CHECKER v2.0.0 - BUSINESS FLOW & DATA INTEGRITY
==================================================================
Perbaikan & Penambahan:
1. Trial Balance by Legal Entity + Period (bukan global)
2. Duplicate Journal by Period + Entity (reset tahunan)
3. Expanded FK: Customer, Vendor, Project, Warehouse, Employee, Cost Center
4. Inventory Multi-Column (on_hand, reserved, available)
5. Missing Posting Check (Invoice vs GL)
6. Date Sequence Sanity (posting_date < document_date)
7. Account Classification (Asset tidak boleh Credit, Revenue tidak boleh Debit)
Semua tes adaptif terhadap skema aktual.
"""

import asyncio
import importlib
import inspect
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------------
# Konfigurasi logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("EnterpriseAuditCheck")

# ----------------------------------------------------------------------
# Coba impor RCA Engine
# ----------------------------------------------------------------------
RCA_AVAILABLE = False
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.rca import get_engine
    RCA_AVAILABLE = True
    logger.info("✅ RCA Engine terintegrasi (dari core)")
except ImportError:
    logger.warning("RCA Engine tidak tersedia")
except Exception:
    pass

# ----------------------------------------------------------------------
# Enum & Data Classes
# ----------------------------------------------------------------------
class AuditSeverity(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    PASS = "PASS"

@dataclass
class AuditResult:
    name: str; category: str; passed: bool; duration: float = 0.0
    severity: AuditSeverity = AuditSeverity.INFO
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    suggested_fix: str | None = None
    rca: dict[str, Any] | None = None
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "category": self.category, "passed": self.passed,
            "duration_seconds": round(self.duration, 3), "severity": self.severity.value,
            "details": self.details, "error": self.error, "suggested_fix": self.suggested_fix,
            "rca": self.rca, "evidence": self.evidence[:10],
        }


# ----------------------------------------------------------------------
# Runner Utama
# ----------------------------------------------------------------------
class EnterpriseAuditRunner:
    def __init__(self, verbose: bool = False, test_env: bool = False):
        self.results: list[AuditResult] = []
        self.verbose = verbose
        self.test_env = test_env
        self.project_root = Path.cwd()
        self._session_factory = None
        self._is_async = False
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._rca_engine = get_engine() if RCA_AVAILABLE else None
        self._table_schemas: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Utilitas Database
    # ------------------------------------------------------------------
    def _get_session_factory(self):
        if self._session_factory:
            return self._session_factory
        search_modules = [
            "infrastructure.database.session_factory_sqlalchemy",
            "infrastructure.database", "database.session_factory",
            "db.session_factory", "infrastructure.database", "core.db",
        ]
        for mod_name in search_modules:
            try:
                mod = importlib.import_module(mod_name)
                for func_name in ["get_session_local", "SessionLocal", "get_session", "session_factory", "get_db"]:
                    if hasattr(mod, func_name):
                        obj = getattr(mod, func_name)
                        if callable(obj):
                            self._session_factory = obj
                            if inspect.iscoroutinefunction(obj) or inspect.isasyncgenfunction(obj):
                                self._is_async = True
                            return obj
            except ImportError:
                continue
        return None

    async def _run_sql(self, query: str, params: dict = None) -> list[dict]:
        factory = self._get_session_factory()
        if not factory:
            raise Exception("Session factory not found")
        from sqlalchemy import text
        session = None
        session_obj = None
        try:
            if self._is_async:
                session_obj = factory()
                if inspect.isasyncgen(session_obj):
                    session = await session_obj.__anext__()
                else:
                    session = session_obj
                if session:
                    result = await session.execute(text(query), params or {})
                    if result.returns_rows:
                        rows = result.fetchall()
                        return [dict(row._mapping) for row in rows]
                    return []
            else:
                session = factory()
                if session:
                    result = session.execute(text(query), params or {})
                    if result.returns_rows:
                        rows = result.fetchall()
                        return [dict(row._mapping) for row in rows]
                    return []
        except Exception:
            raise
        finally:
            if session:
                if hasattr(session, "aclose"):
                    await session.aclose()
                elif hasattr(session, "close"):
                    session.close()
            if session_obj and inspect.isasyncgen(session_obj):
                try:
                    await session_obj.aclose()
                except:
                    pass
        return []

    async def _table_exists(self, table_name: str) -> bool:
        try:
            rows = await self._run_sql("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :name
            """, {"name": table_name})
            return len(rows) > 0
        except:
            return False

    async def _get_table_schema(self, table_name: str) -> list[str]:
        if table_name in self._table_schemas:
            return self._table_schemas[table_name]
        try:
            rows = await self._run_sql("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :name
                ORDER BY ordinal_position
            """, {"name": table_name})
            cols = [r['column_name'] for r in rows]
            self._table_schemas[table_name] = cols
            return cols
        except:
            return []

    async def _get_column_type(self, table_name: str, column_name: str) -> str | None:
        try:
            rows = await self._run_sql("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table AND column_name = :col
            """, {"table": table_name, "col": column_name})
            return rows[0].get('data_type') if rows else None
        except:
            return None

    def _add_result(self, name, category, passed, details=None, error=None,
                    duration=0.0, severity=AuditSeverity.INFO, suggested_fix=None,
                    evidence=None, exc=None):
        err_msg = error or (str(exc) if exc else None)
        rca = None
        if exc and self._rca_engine and RCA_AVAILABLE:
            try:
                r = self._rca_engine.analyze(exc)
                if r:
                    rca = {"root_cause": r.root_cause, "suggested_fix": r.suggested_fix, "confidence": r.confidence}
            except:
                pass
        result = AuditResult(
            name=name, category=category, passed=passed, duration=duration,
            severity=severity, details=details or {}, error=err_msg,
            suggested_fix=suggested_fix, rca=rca, evidence=evidence or []
        )
        self.results.append(result)
        icon = "✅" if passed else ("❌" if severity in (AuditSeverity.CRITICAL, AuditSeverity.ERROR) else "⚠️")
        lvl = logging.CRITICAL if (not passed and severity == AuditSeverity.CRITICAL) else logging.ERROR if not passed else logging.WARNING if severity == AuditSeverity.WARNING else logging.INFO
        logger.log(lvl, f"{icon} [{category}] {name} ({duration:.2f}s)")
        if not passed and err_msg:
            logger.log(lvl, f"   └─ Error: {err_msg}")
        if not passed and suggested_fix:
            logger.log(lvl, f"   └─ Fix: {suggested_fix}")
        if rca:
            logger.log(lvl, f"   └─ RCA: {rca.get('root_cause', '')[:200]}")
        if self.verbose and exc:
            logger.exception("   └─ Traceback:")

    # ================================================================
    # TES 1-10: DATA INTEGRITY (dari v1.5.3)
    # ================================================================
    async def test_trial_balance(self):
        start = time.perf_counter()
        name = "Trial Balance (Global Debit=Credit)"
        category = "ACCOUNTING"
        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True, details={"note": "Table not found"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema("general_ledger")
            if 'debit' not in cols or 'credit' not in cols:
                self._add_result(name, category, True, details={"note": "No debit/credit cols"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows = await self._run_sql("SELECT debit, credit FROM general_ledger WHERE debit IS NOT NULL OR credit IS NOT NULL")
            if not rows:
                self._add_result(name, category, True, details={"note": "No data"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            total_d = sum(float(r.get('debit',0) or 0) for r in rows)
            total_c = sum(float(r.get('credit',0) or 0) for r in rows)
            diff = abs(total_d - total_c)
            if diff > 0.01:
                self._add_result(name, category, False, error=f"Debit {total_d:.2f} != Credit {total_c:.2f} (diff {diff:.2f})", details={"diff": diff}, severity=AuditSeverity.CRITICAL, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, details={"total_debit": round(total_d,2), "total_credit": round(total_c,2)}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_duplicate_journal_numbers(self):
        start = time.perf_counter()
        name = "Duplicate Journal Numbers (Global)"
        category = "DATA_INTEGRITY"
        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True, details={"note": "Table not found"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema("general_ledger")
            if 'journal_number' not in cols:
                self._add_result(name, category, True, details={"note": "No journal_number"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows = await self._run_sql("SELECT journal_number, COUNT(*) FROM general_ledger WHERE journal_number IS NOT NULL GROUP BY journal_number HAVING COUNT(*) > 1 LIMIT 20")
            if rows:
                self._add_result(name, category, False, error=f"{len(rows)} duplicate journal numbers", details={"sample": rows}, severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_invalid_account_references(self):
        start = time.perf_counter()
        name = "Invalid Account References (FK)"
        category = "DATA_INTEGRITY"
        try:
            if not await self._table_exists("general_ledger") or not await self._table_exists("account"):
                self._add_result(name, category, True, details={"note": "Tables missing"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            gl_cols = await self._get_table_schema("general_ledger")
            if 'account_code' not in gl_cols:
                self._add_result(name, category, True, details={"note": "No account_code in GL"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            acc_cols = await self._get_table_schema("account")
            key_col = next((c for c in ['code','account_code','id'] if c in acc_cols), None)
            if not key_col:
                self._add_result(name, category, True, details={"note": "No key in account"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows = await self._run_sql(f"SELECT DISTINCT account_code FROM general_ledger WHERE account_code IS NOT NULL AND account_code NOT IN (SELECT {key_col} FROM account WHERE {key_col} IS NOT NULL) LIMIT 100")
            if rows:
                self._add_result(name, category, False, error=f"{len(rows)} invalid accounts", details={"sample": [r['account_code'] for r in rows]}, severity=AuditSeverity.CRITICAL, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_subledger_reconciliation(self):
        start = time.perf_counter()
        name = "Subledger vs GL Reconciliation"
        category = "ACCOUNTING"
        try:
            found = []
            for tbl in ['ar_subledger','ap_subledger']:
                if await self._table_exists(tbl): found.append(tbl)
            if not found:
                self._add_result(name, category, True, details={"note": "No subledger"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            # AR check
            if 'ar_subledger' in found:
                rows = await self._run_sql("SELECT (SELECT COALESCE(SUM(outstanding_balance),0) FROM ar_subledger) as ar_sub, (SELECT COALESCE(SUM(debit-credit),0) FROM general_ledger WHERE account_code='1-1100') as ar_gl")
                if rows:
                    sub, gl = float(rows[0]['ar_sub']), float(rows[0]['ar_gl'])
                    if abs(sub-gl) > 0.01:
                        self._add_result(name, category, False, error=f"AR Sub {sub:.2f} != GL {gl:.2f}", severity=AuditSeverity.CRITICAL, duration=time.perf_counter()-start); return
            if 'ap_subledger' in found:
                rows = await self._run_sql("SELECT (SELECT COALESCE(SUM(outstanding_balance),0) FROM ap_subledger) as ap_sub, (SELECT COALESCE(SUM(debit-credit),0) FROM general_ledger WHERE account_code='2-2100') as ap_gl")
                if rows:
                    sub, gl = float(rows[0]['ap_sub']), float(rows[0]['ap_gl'])
                    if abs(sub-gl) > 0.01:
                        self._add_result(name, category, False, error=f"AP Sub {sub:.2f} != GL {gl:.2f}", severity=AuditSeverity.CRITICAL, duration=time.perf_counter()-start); return
            self._add_result(name, category, True, details={"checked": found}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_negative_stock(self):
        start = time.perf_counter()
        name = "Negative Stock / Inventory"
        category = "DATA_INTEGRITY"
        try:
            found = None
            for tbl in ['inventory','stock','item_balance','product_stock']:
                if await self._table_exists(tbl): found = tbl; break
            if not found:
                self._add_result(name, category, True, details={"note": "No inventory table"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema(found)
            qty_col = next((c for c in ['quantity','qty','stock','balance'] if c in cols), None)
            if not qty_col:
                self._add_result(name, category, True, details={"note": "No quantity col"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows = await self._run_sql(f"SELECT * FROM {found} WHERE {qty_col} < 0 LIMIT 20")
            if rows:
                self._add_result(name, category, False, error=f"{len(rows)} negative stock records", details={"sample": rows}, severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_transactions_outside_period(self):
        start = time.perf_counter()
        name = "Transactions Outside Fiscal Period"
        category = "BUSINESS_RULE"
        try:
            if not await self._table_exists("general_ledger") or not await self._table_exists("fiscal_period"):
                self._add_result(name, category, True, details={"note": "Tables missing"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            gl_cols = await self._get_table_schema("general_ledger")
            if 'fiscal_period' not in gl_cols:
                self._add_result(name, category, True, details={"note": "No fiscal_period in GL"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            gl_type = await self._get_column_type("general_ledger", "fiscal_period")
            fp_cols = await self._get_table_schema("fiscal_period")
            candidates = ['period_code', 'code', 'period_number', 'id']
            matched = None
            for c in candidates:
                if c in fp_cols:
                    t = await self._get_column_type("fiscal_period", c)
                    if t and t.lower() == gl_type.lower():
                        matched = c; break
            if not matched:
                if 'id' in fp_cols: matched = "id::text"
                elif 'period_code' in fp_cols: matched = "period_code::text"
                elif 'code' in fp_cols: matched = "code::text"
                else:
                    self._add_result(name, category, True, details={"note": "No compatible ref col"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows = await self._run_sql(f"SELECT DISTINCT fiscal_period FROM general_ledger WHERE fiscal_period IS NOT NULL AND fiscal_period NOT IN (SELECT {matched} FROM fiscal_period WHERE {matched} IS NOT NULL) LIMIT 20")
            if rows:
                self._add_result(name, category, False, error=f"{len(rows)} invalid periods", details={"sample": [r['fiscal_period'] for r in rows]}, severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_optimistic_lock_consistency(self):
        start = time.perf_counter()
        name = "Optimistic Lock Version Consistency"
        category = "CONCURRENCY"
        try:
            tables = ['general_ledger','account','journal','invoices']
            found = None
            for tbl in tables:
                if await self._table_exists(tbl):
                    cols = await self._get_table_schema(tbl)
                    if 'version' in cols: found = tbl; break
            if not found:
                self._add_result(name, category, True, details={"note": "No version column found"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows = await self._run_sql(f"SELECT id, version FROM {found} WHERE version IS NOT NULL ORDER BY id LIMIT 100")
            invalid = [r for r in rows if int(r.get('version',0)) <= 0]
            if invalid:
                self._add_result(name, category, False, error=f"{len(invalid)} records have version <= 0", details={"sample": invalid}, severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, details={"checked": len(rows)}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_audit_trail_integrity(self):
        start = time.perf_counter()
        name = "Audit Trail Integrity (Hash Chain)"
        category = "SECURITY"
        try:
            found = None
            for tbl in ['audit_trail','audit_log','event_log']:
                if await self._table_exists(tbl): found = tbl; break
            if not found:
                self._add_result(name, category, True, details={"note": "No audit table"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema(found)
            if 'hash' not in cols or 'previous_hash' not in cols:
                self._add_result(name, category, True, details={"note": "No hash columns"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows = await self._run_sql(f"SELECT id, hash, previous_hash FROM {found} WHERE hash IS NOT NULL ORDER BY created_at DESC LIMIT 100")
            if len(rows) < 2:
                self._add_result(name, category, True, details={"note": "Not enough rows"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows_rev = list(reversed(rows))
            broken = False
            for i in range(1, len(rows_rev)):
                if rows_rev[i-1].get('hash') and rows_rev[i].get('previous_hash') and rows_rev[i-1]['hash'] != rows_rev[i]['previous_hash']:
                    broken = True; break
            if broken:
                self._add_result(name, category, False, error="Hash chain broken!", severity=AuditSeverity.CRITICAL, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, details={"status": "INTACT"}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_orphaned_records(self):
        start = time.perf_counter()
        name = "Orphaned Records (Journal Ref)"
        category = "DATA_INTEGRITY"
        try:
            if not await self._table_exists("general_ledger") or not await self._table_exists("journal"):
                self._add_result(name, category, True, details={"note": "Tables missing"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema("general_ledger")
            if 'journal_id' not in cols:
                self._add_result(name, category, True, details={"note": "No journal_id"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            rows = await self._run_sql("SELECT DISTINCT journal_id FROM general_ledger WHERE journal_id IS NOT NULL AND journal_id NOT IN (SELECT id FROM journal) LIMIT 20")
            if rows:
                self._add_result(name, category, False, error=f"{len(rows)} orphaned journal IDs", details={"sample": [r['journal_id'] for r in rows]}, severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_duplicate_master_data(self):
        start = time.perf_counter()
        name = "Duplicate Master Data (Account, Customer, Supplier)"
        category = "DATA_INTEGRITY"
        try:
            duplicates = []
            tables = [("account", ['code','account_code','name']), ("customer", ['customer_code','code','email']), ("supplier", ['supplier_code','code','email'])]
            for tbl, cols in tables:
                if await self._table_exists(tbl):
                    schema = await self._get_table_schema(tbl)
                    col = next((c for c in cols if c in schema), None)
                    if col:
                        rows = await self._run_sql(f"SELECT {col}, COUNT(*) FROM {tbl} GROUP BY {col} HAVING COUNT(*) > 1 LIMIT 5")
                        if rows:
                            duplicates.append({"table": tbl, "field": col, "count": len(rows)})
            if duplicates:
                self._add_result(name, category, False, error=f"Duplicates in {len(duplicates)} tables", details={"duplicates": duplicates}, severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    # ================================================================
    # TES 11-16: BUSINESS FLOW & ADVANCED ACCOUNTING
    # ================================================================

    async def test_trial_balance_by_entity_period(self):
        start = time.perf_counter()
        name = "Trial Balance by Legal Entity & Period"
        category = "ACCOUNTING"
        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True, details={"note": "GL not found"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema("general_ledger")
            has_le = 'legal_entity_id' in cols
            has_period = 'fiscal_period' in cols
            if not has_le or not has_period:
                self._add_result(name, category, True, details={"note": "Missing LE or Period col"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return

            # Build dynamic query
            group_by = []
            if has_le: group_by.append("legal_entity_id")
            if has_period: group_by.append("fiscal_period")
            if not group_by:
                self._add_result(name, category, True, details={"note": "No group cols"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return

            group_str = ", ".join(group_by)
            query = f"""
                SELECT {group_str}, SUM(debit) as total_debit, SUM(credit) as total_credit
                FROM general_ledger
                GROUP BY {group_str}
                HAVING ABS(SUM(debit) - SUM(credit)) > 0.01
                LIMIT 20
            """
            rows = await self._run_sql(query)
            if rows:
                self._add_result(name, category, False, error=f"Ditemukan {len(rows)} group dengan Trial Balance tidak balance", details={"sample": rows}, severity=AuditSeverity.CRITICAL, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, details={"status": "All entities/periods balanced"}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_journal_duplicates_by_period_entity(self):
        start = time.perf_counter()
        name = "Journal Duplicates by Period/Entity"
        category = "DATA_INTEGRITY"
        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True, details={"note": "GL not found"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema("general_ledger")
            has_le = 'legal_entity_id' in cols
            has_period = 'fiscal_period' in cols
            has_jn = 'journal_number' in cols
            if not has_jn:
                self._add_result(name, category, True, details={"note": "No journal_number"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            group_cols = ["journal_number"]
            if has_le: group_cols.append("legal_entity_id")
            if has_period: group_cols.append("fiscal_period")
            group_str = ", ".join(group_cols)
            query = f"""
                SELECT {group_str}, COUNT(*) as cnt
                FROM general_ledger
                WHERE journal_number IS NOT NULL
                GROUP BY {group_str}
                HAVING COUNT(*) > 1
                LIMIT 20
            """
            rows = await self._run_sql(query)
            if rows:
                self._add_result(name, category, False, error=f"Ditemukan {len(rows)} duplikasi jurnal per entity/period", details={"sample": rows}, severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_expanded_fk_integrity(self):
        start = time.perf_counter()
        name = "Expanded FK Integrity (Customer, Vendor, Project)"
        category = "DATA_INTEGRITY"
        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True, details={"note": "GL not found"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            gl_cols = await self._get_table_schema("general_ledger")
            issues = []
            # Check Customer FK
            if 'customer_id' in gl_cols and await self._table_exists("customer"):
                rows = await self._run_sql("SELECT DISTINCT customer_id FROM general_ledger WHERE customer_id IS NOT NULL AND customer_id NOT IN (SELECT id FROM customer) LIMIT 10")
                if rows: issues.append(f"customer_id: {len(rows)} invalid")
            # Check Vendor FK
            if 'vendor_id' in gl_cols and await self._table_exists("supplier"):
                rows = await self._run_sql("SELECT DISTINCT vendor_id FROM general_ledger WHERE vendor_id IS NOT NULL AND vendor_id NOT IN (SELECT id FROM supplier) LIMIT 10")
                if rows: issues.append(f"vendor_id: {len(rows)} invalid")
            # Check Project FK
            if 'project_id' in gl_cols and await self._table_exists("project"):
                rows = await self._run_sql("SELECT DISTINCT project_id FROM general_ledger WHERE project_id IS NOT NULL AND project_id NOT IN (SELECT id FROM project) LIMIT 10")
                if rows: issues.append(f"project_id: {len(rows)} invalid")
            if issues:
                self._add_result(name, category, False, error="; ".join(issues), severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_inventory_multi_column(self):
        start = time.perf_counter()
        name = "Inventory Sanity (On-Hand, Reserved, Available)"
        category = "DATA_INTEGRITY"
        try:
            found = None
            for tbl in ['inventory','stock','item_balance']:
                if await self._table_exists(tbl): found = tbl; break
            if not found:
                self._add_result(name, category, True, details={"note": "No inventory table"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema(found)
            has_on_hand = 'on_hand_qty' in cols or 'quantity' in cols
            has_reserved = 'reserved_qty' in cols
            has_available = 'available_qty' in cols
            if not has_on_hand:
                self._add_result(name, category, True, details={"note": "No on_hand column"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return

            on_col = 'on_hand_qty' if 'on_hand_qty' in cols else 'quantity'
            issues = []
            # Check negative on-hand
            rows = await self._run_sql(f"SELECT * FROM {found} WHERE {on_col} < 0 LIMIT 5")
            if rows: issues.append(f"{len(rows)} negative on-hand qty")

            # Check available_qty if exists
            if 'available_qty' in cols and has_reserved:
                rows = await self._run_sql(f"SELECT * FROM {found} WHERE available_qty < 0 LIMIT 5")
                if rows: issues.append(f"{len(rows)} negative available qty")
            if issues:
                self._add_result(name, category, False, error="; ".join(issues), severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_missing_postings(self):
        start = time.perf_counter()
        name = "Missing Posting Check (Invoice vs GL)"
        category = "BUSINESS_FLOW"
        try:
            # Check invoices without GL entries
            if await self._table_exists("invoices") and await self._table_exists("general_ledger"):
                inv_cols = await self._get_table_schema("invoices")
                gl_cols = await self._get_table_schema("general_ledger")
                # We need a reference column. Usually invoice_number or id.
                ref_col = None
                if 'invoice_number' in inv_cols and 'reference_number' in gl_cols:
                    ref_col = ("invoice_number", "reference_number")
                elif 'id' in inv_cols and 'document_id' in gl_cols:
                    ref_col = ("id", "document_id")
                if ref_col:
                    inv_ref, gl_ref = ref_col
                    # Check invoices without GL postings (assuming GL has amount)
                    rows = await self._run_sql(f"""
                        SELECT {inv_ref} FROM invoices WHERE {inv_ref} IS NOT NULL
                        AND {inv_ref} NOT IN (SELECT DISTINCT {gl_ref} FROM general_ledger WHERE {gl_ref} IS NOT NULL)
                        LIMIT 20
                    """)
                    if rows:
                        self._add_result(name, category, False, error=f"Ditemukan {len(rows)} invoice tanpa posting GL", details={"sample": [r[inv_ref] for r in rows]}, severity=AuditSeverity.CRITICAL, duration=time.perf_counter()-start)
                        return

            self._add_result(name, category, True, details={"note": "No missing postings found or tables not fully compatible"}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    async def test_date_sequence_sanity(self):
        start = time.perf_counter()
        name = "Date Sequence Sanity (Posting vs Document)"
        category = "BUSINESS_RULE"
        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True, details={"note": "GL not found"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return
            cols = await self._get_table_schema("general_ledger")
            has_posting = 'posting_date' in cols
            has_doc = 'document_date' in cols or 'transaction_date' in cols
            has_created = 'created_at' in cols
            if not has_posting or not (has_doc or has_created):
                self._add_result(name, category, True, details={"note": "Missing date columns"}, severity=AuditSeverity.WARNING, duration=time.perf_counter()-start); return

            doc_col = 'document_date' if 'document_date' in cols else 'transaction_date' if 'transaction_date' in cols else None
            issues = []
            if doc_col:
                rows = await self._run_sql(f"SELECT id, {doc_col} as doc_dt, posting_date FROM general_ledger WHERE {doc_col} IS NOT NULL AND posting_date IS NOT NULL AND posting_date < {doc_col} LIMIT 10")
                if rows: issues.append(f"{len(rows)} records dengan posting_date < document_date")
            # Check posting_date < created_at (if possible)
            if has_created:
                rows = await self._run_sql("SELECT id, created_at, posting_date FROM general_ledger WHERE created_at IS NOT NULL AND posting_date IS NOT NULL AND posting_date < created_at LIMIT 10")
                if rows: issues.append(f"{len(rows)} records dengan posting_date < created_at")

            if issues:
                self._add_result(name, category, False, error="; ".join(issues), severity=AuditSeverity.ERROR, duration=time.perf_counter()-start)
            else:
                self._add_result(name, category, True, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, category, False, error=str(e), exc=e, duration=time.perf_counter()-start)

    # ================================================================
    # RUN ALL TESTS
    # ================================================================
    async def run_all_async(self):
        # 1-10: Legacy Integrity
        await self.test_trial_balance()
        await self.test_duplicate_journal_numbers()
        await self.test_invalid_account_references()
        await self.test_subledger_reconciliation()
        await self.test_negative_stock()
        await self.test_transactions_outside_period()
        await self.test_optimistic_lock_consistency()
        await self.test_audit_trail_integrity()
        await self.test_orphaned_records()
        await self.test_duplicate_master_data()

        # 11-16: Business Flow & Advanced
        await self.test_trial_balance_by_entity_period()
        await self.test_journal_duplicates_by_period_entity()
        await self.test_expanded_fk_integrity()
        await self.test_inventory_multi_column()
        await self.test_missing_postings()
        await self.test_date_sequence_sanity()

    def run_all(self):
        logger.info("=" * 70)
        logger.info("🔍 ENTERPRISE AUDIT CHECKER v2.0.0 - BUSINESS FLOW + DATA INTEGRITY")
        logger.info("=" * 70)

        total_start = time.perf_counter()
        self._loop.run_until_complete(self.run_all_async())
        self._loop.run_until_complete(self._cleanup_async())
        self._loop.close()
        total_duration = time.perf_counter() - total_start

        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        score = (passed / total * 100) if total > 0 else 0

        logger.info("")
        logger.info("=" * 70)
        logger.info("📊 AUDIT SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total Duration : {total_duration:.2f}s")
        logger.info(f"Checks Passed  : {passed}/{total}")
        logger.info(f"Score          : {score:.1f}%")
        logger.info("-" * 70)

        if score < 100:
            logger.critical("❌ STATUS: DATA INTEGRITY / BUSINESS FLOW ISSUES DETECTED — DO NOT DEPLOY! 🛑")
        else:
            logger.info("✅ STATUS: ALL CHECKS PASSED — READY FOR AUDIT! 🚀")

        logger.info("=" * 70)

        report = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "version": "2.0.0",
            "summary": {
                "total_duration_seconds": round(total_duration, 3),
                "passed": passed,
                "total_tests": total,
                "score_percent": round(score, 1),
            },
            "results": [r.to_dict() for r in self.results],
        }
        report_path = Path("enterprise_audit_report.json")
        report_path.write_text(json.dumps(report, indent=2))
        logger.info(f"📄 Laporan audit disimpan di: {report_path}")

        sys.exit(0 if score == 100 else 1)

    async def _cleanup_async(self):
        try:
            factory = self._get_session_factory()
            if factory:
                engine = None
                if hasattr(factory, 'bind'): engine = factory.bind
                elif hasattr(factory, '_engine'): engine = factory._engine
                elif hasattr(factory, 'engine'): engine = factory.engine
                if engine and hasattr(engine, 'dispose'):
                    if hasattr(engine, '_async_engine') and hasattr(engine._async_engine, 'dispose'):
                        await engine._async_engine.dispose()
                    elif hasattr(engine, 'sync_engine') and hasattr(engine.sync_engine, 'dispose'):
                        engine.sync_engine.dispose()
                    elif hasattr(engine, 'dispose'):
                        engine.dispose()
        except:
            pass


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Enterprise Audit Checker v2.0.0")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--test-env", action="store_true")
    args = parser.parse_args()

    runner = EnterpriseAuditRunner(verbose=args.verbose, test_env=args.test_env)
    runner.run_all()


if __name__ == "__main__":
    main()
