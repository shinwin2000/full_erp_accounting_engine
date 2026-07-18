#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ENTERPRISE AUDIT CHECKER v1.5.3 - REAL SCANNING WITH RCA
==========================================================
Perbaikan:
- test_transactions_outside_period: adaptif terhadap tipe data kolom
  (cek tipe fiscal_period di general_ledger, cari kolom di fiscal_period
   dengan tipe yang sama, gunakan cast jika perlu)
- Semua tes menggunakan query SQL aktual, tidak ada mock.
- Integrasi dengan RCA Engine untuk analisis error.
"""

import os
import sys
import time
import json
import logging
import asyncio
import importlib
import inspect
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

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
    from core.rca import get_engine, analyze_exception, RCAResult
    RCA_AVAILABLE = True
    logger.info("✅ RCA Engine terintegrasi (dari core)")
except ImportError as e:
    logger.warning(f"RCA Engine tidak tersedia: {e}")
except Exception as e:
    logger.warning(f"Gagal menginisialisasi RCA Engine: {e}")

# ----------------------------------------------------------------------
# Enum untuk level keparahan
# ----------------------------------------------------------------------
class AuditSeverity(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    PASS = "PASS"


# ----------------------------------------------------------------------
# Data class untuk hasil
# ----------------------------------------------------------------------
@dataclass
class AuditResult:
    name: str
    category: str
    passed: bool
    duration: float = 0.0
    severity: AuditSeverity = AuditSeverity.INFO
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    suggested_fix: Optional[str] = None
    rca: Optional[Dict[str, Any]] = None
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "passed": self.passed,
            "duration_seconds": round(self.duration, 3),
            "severity": self.severity.value,
            "details": self.details,
            "error": self.error,
            "suggested_fix": self.suggested_fix,
            "rca": self.rca,
            "evidence": self.evidence[:10],
        }


# ----------------------------------------------------------------------
# Runner Utama
# ----------------------------------------------------------------------
class EnterpriseAuditRunner:
    def __init__(self, verbose: bool = False, test_env: bool = False):
        self.results: List[AuditResult] = []
        self.verbose = verbose
        self.test_env = test_env
        self.project_root = Path.cwd()
        self._session_factory = None
        self._is_async = False
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._rca_engine = get_engine() if RCA_AVAILABLE else None
        self._table_schemas: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # Utilitas Database
    # ------------------------------------------------------------------
    def _get_session_factory(self):
        if self._session_factory:
            return self._session_factory

        search_modules = [
            "infrastructure.database.session_factory_sqlalchemy",
            "infrastructure.database",
            "database.session_factory",
            "db.session_factory",
            "infrastructure.db",
            "core.db",
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

    async def _run_sql(self, query: str, params: dict = None) -> List[Dict]:
        """Eksekusi SQL dan kembalikan hasil sebagai list of dict."""
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
        except Exception as e:
            # Biarkan caller yang handle
            raise
        finally:
            if session:
                if hasattr(session, "aclose"):
                    await session.aclose()
                elif hasattr(session, "close"):
                    session.close()
            # Tutup generator async
            if session_obj and inspect.isasyncgen(session_obj):
                try:
                    await session_obj.aclose()
                except:
                    pass
        return []

    async def _table_exists(self, table_name: str) -> bool:
        """Cek apakah tabel ada di schema public."""
        try:
            rows = await self._run_sql("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :name
            """, {"name": table_name})
            return len(rows) > 0
        except:
            return False

    async def _get_table_schema(self, table_name: str) -> List[str]:
        """Dapatkan daftar kolom dari tabel."""
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

    async def _get_column_type(self, table_name: str, column_name: str) -> Optional[str]:
        """Dapatkan tipe data kolom."""
        try:
            rows = await self._run_sql("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table AND column_name = :col
            """, {"table": table_name, "col": column_name})
            if rows:
                return rows[0].get('data_type')
        except:
            pass
        return None

    def _add_result(self, name, category, passed, details=None, error=None,
                    duration=0.0, severity=AuditSeverity.INFO, suggested_fix=None,
                    evidence=None, exc=None):
        err_msg = error or (str(exc) if exc else None)
        rca = None
        if exc and self._rca_engine and RCA_AVAILABLE:
            try:
                rca_result = self._rca_engine.analyze(exc)
                if rca_result:
                    rca = {
                        "root_cause": rca_result.root_cause,
                        "suggested_fix": rca_result.suggested_fix,
                        "confidence": rca_result.confidence,
                    }
            except:
                pass

        result = AuditResult(
            name=name,
            category=category,
            passed=passed,
            duration=duration,
            severity=severity,
            details=details or {},
            error=err_msg,
            suggested_fix=suggested_fix,
            rca=rca,
            evidence=evidence or [],
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
    # TEST 1: TRIAL BALANCE (Debit = Credit)
    # ================================================================
    async def test_trial_balance(self):
        start = time.perf_counter()
        name = "Trial Balance (Debit = Credit)"
        category = "ACCOUNTING"

        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True,
                    details={"note": "Tabel general_ledger tidak ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            cols = await self._get_table_schema("general_ledger")
            debit_col = 'debit' if 'debit' in cols else None
            credit_col = 'credit' if 'credit' in cols else None
            if not debit_col or not credit_col:
                self._add_result(name, category, True,
                    details={"note": "Tidak ada kolom debit/credit"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            query = f"SELECT {debit_col} as debit, {credit_col} as credit FROM general_ledger WHERE {debit_col} IS NOT NULL OR {credit_col} IS NOT NULL"
            rows = await self._run_sql(query)

            if not rows:
                self._add_result(name, category, True,
                    details={"note": "Tidak ada data transaksi"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            total_debit = sum(float(r.get('debit', 0) or 0) for r in rows)
            total_credit = sum(float(r.get('credit', 0) or 0) for r in rows)
            diff = abs(total_debit - total_credit)

            details = {
                "total_debit": round(total_debit, 2),
                "total_credit": round(total_credit, 2),
                "difference": round(diff, 2),
                "records_checked": len(rows),
            }

            if diff > 0.01:
                self._add_result(name, category, False,
                    error=f"Trial Balance tidak balance: Debit {total_debit:.2f} != Credit {total_credit:.2f} (Selisih {diff:.2f})",
                    details=details,
                    severity=AuditSeverity.CRITICAL,
                    suggested_fix="Periksa proses posting jurnal, pastikan tidak ada entry yang tidak balance.",
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details=details,
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 2: DUPLICATE JOURNAL NUMBERS
    # ================================================================
    async def test_duplicate_journal_numbers(self):
        start = time.perf_counter()
        name = "Duplicate Journal Numbers"
        category = "DATA_INTEGRITY"

        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True,
                    details={"note": "Tabel general_ledger tidak ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            cols = await self._get_table_schema("general_ledger")
            if 'journal_number' not in cols:
                self._add_result(name, category, True,
                    details={"note": "Tidak ada kolom journal_number"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            query = """
                SELECT journal_number, COUNT(*) as cnt
                FROM general_ledger
                WHERE journal_number IS NOT NULL
                GROUP BY journal_number
                HAVING COUNT(*) > 1
                LIMIT 20
            """
            rows = await self._run_sql(query)

            details = {
                "duplicate_count": len(rows),
                "sample": rows[:5]
            }

            if rows:
                self._add_result(name, category, False,
                    error=f"Ditemukan {len(rows)} nomor jurnal duplikat",
                    details=details,
                    severity=AuditSeverity.ERROR,
                    suggested_fix="Periksa sequence generator dan validasi nomor dokumen.",
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details=details,
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 3: INVALID ACCOUNT REFERENCES (FK Integrity)
    # ================================================================
    async def test_invalid_account_references(self):
        start = time.perf_counter()
        name = "Invalid Account References (FK Integrity)"
        category = "DATA_INTEGRITY"

        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True,
                    details={"note": "Tabel general_ledger tidak ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            gl_cols = await self._get_table_schema("general_ledger")
            if 'account_code' not in gl_cols:
                self._add_result(name, category, True,
                    details={"note": "general_ledger tidak memiliki kolom account_code"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            if not await self._table_exists("account"):
                self._add_result(name, category, True,
                    details={"note": "Tabel account tidak ditemukan, tidak bisa cek referensi"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            acc_cols = await self._get_table_schema("account")
            key_col = None
            for col in ['code', 'account_code', 'id']:
                if col in acc_cols:
                    key_col = col
                    break

            if not key_col:
                self._add_result(name, category, True,
                    details={"note": "Tidak dapat menemukan kolom kunci di tabel account"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            query = f"""
                SELECT DISTINCT account_code
                FROM general_ledger
                WHERE account_code IS NOT NULL
                AND account_code NOT IN (SELECT {key_col} FROM account WHERE {key_col} IS NOT NULL)
                LIMIT 100
            """
            rows = await self._run_sql(query)

            details = {
                "invalid_accounts_found": len(rows),
                "sample": [r.get('account_code') for r in rows[:10]]
            }

            if rows:
                self._add_result(name, category, False,
                    error=f"Ditemukan {len(rows)} account_code yang tidak ada di master account",
                    details=details,
                    severity=AuditSeverity.CRITICAL,
                    suggested_fix="Perbaiki referensi account_code di general_ledger atau tambahkan ke tabel account.",
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details=details,
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 4: SUBLEDGER VS GL RECONCILIATION
    # ================================================================
    async def test_subledger_reconciliation(self):
        start = time.perf_counter()
        name = "Subledger vs GL Reconciliation"
        category = "ACCOUNTING"

        try:
            subledger_tables = ['ar_subledger', 'ap_subledger', 'invoice_subledger']
            found = []
            for tbl in subledger_tables:
                if await self._table_exists(tbl):
                    found.append(tbl)

            if not found:
                self._add_result(name, category, True,
                    details={"note": "Tidak ada tabel subledger yang ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            if 'ar_subledger' in found:
                rows = await self._run_sql("""
                    SELECT
                        (SELECT COALESCE(SUM(outstanding_balance), 0) FROM ar_subledger) as ar_sub,
                        (SELECT COALESCE(SUM(debit - credit), 0) FROM general_ledger WHERE account_code = '1-1100') as ar_gl
                """)
                if rows:
                    sub = float(rows[0].get('ar_sub', 0))
                    gl = float(rows[0].get('ar_gl', 0))
                    diff = abs(sub - gl)
                    if diff > 0.01:
                        self._add_result(name, category, False,
                            error=f"AR Subledger ({sub:.2f}) != GL AR ({gl:.2f})",
                            details={"difference": diff},
                            severity=AuditSeverity.CRITICAL,
                            suggested_fix="Periksa sinkronisasi AR subledger ke GL.",
                            duration=time.perf_counter() - start)
                        return

            if 'ap_subledger' in found:
                rows = await self._run_sql("""
                    SELECT
                        (SELECT COALESCE(SUM(outstanding_balance), 0) FROM ap_subledger) as ap_sub,
                        (SELECT COALESCE(SUM(debit - credit), 0) FROM general_ledger WHERE account_code = '2-2100') as ap_gl
                """)
                if rows:
                    sub = float(rows[0].get('ap_sub', 0))
                    gl = float(rows[0].get('ap_gl', 0))
                    diff = abs(sub - gl)
                    if diff > 0.01:
                        self._add_result(name, category, False,
                            error=f"AP Subledger ({sub:.2f}) != GL AP ({gl:.2f})",
                            details={"difference": diff},
                            severity=AuditSeverity.CRITICAL,
                            suggested_fix="Periksa sinkronisasi AP subledger ke GL.",
                            duration=time.perf_counter() - start)
                        return

            self._add_result(name, category, True,
                details={"checked": found},
                duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 5: NEGATIVE STOCK / INVENTORY
    # ================================================================
    async def test_negative_stock(self):
        start = time.perf_counter()
        name = "Negative Stock / Inventory"
        category = "DATA_INTEGRITY"

        try:
            inv_tables = ['inventory', 'stock', 'item_balance', 'product_stock']
            found = None
            for tbl in inv_tables:
                if await self._table_exists(tbl):
                    found = tbl
                    break

            if not found:
                self._add_result(name, category, True,
                    details={"note": "Tidak ada tabel inventory yang ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            cols = await self._get_table_schema(found)
            qty_col = None
            for col in ['quantity', 'qty', 'stock', 'balance']:
                if col in cols:
                    qty_col = col
                    break

            if not qty_col:
                self._add_result(name, category, True,
                    details={"note": f"Tabel {found} tidak memiliki kolom quantity"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            query = f"SELECT * FROM {found} WHERE {qty_col} < 0 LIMIT 20"
            rows = await self._run_sql(query)

            if rows:
                self._add_result(name, category, False,
                    error=f"Ditemukan {len(rows)} record dengan stock negatif",
                    details={"sample": rows},
                    severity=AuditSeverity.ERROR,
                    suggested_fix="Periksa transaksi inventory dan pastikan tidak ada pengeluaran melebihi stok.",
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details={"checked": found},
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 6: TRANSACTIONS OUTSIDE FISCAL PERIOD (ADAPTIF v1.5.3)
    # ================================================================
    async def test_transactions_outside_period(self):
        start = time.perf_counter()
        name = "Transactions Outside Fiscal Period"
        category = "BUSINESS_RULE"

        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True,
                    details={"note": "Tabel general_ledger tidak ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            gl_cols = await self._get_table_schema("general_ledger")
            if 'fiscal_period' not in gl_cols:
                self._add_result(name, category, True,
                    details={"note": "general_ledger tidak memiliki kolom fiscal_period"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            if not await self._table_exists("fiscal_period"):
                self._add_result(name, category, True,
                    details={"note": "Tabel fiscal_period tidak ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            gl_period_type = await self._get_column_type("general_ledger", "fiscal_period")
            if not gl_period_type:
                self._add_result(name, category, True,
                    details={"note": "Tidak dapat menentukan tipe fiscal_period"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            fp_cols = await self._get_table_schema("fiscal_period")
            candidates = ['period_code', 'code', 'period_number', 'id']
            matched_col = None
            for col in candidates:
                if col in fp_cols:
                    col_type = await self._get_column_type("fiscal_period", col)
                    if col_type and col_type.lower() == gl_period_type.lower():
                        matched_col = col
                        break

            if not matched_col:
                if 'id' in fp_cols:
                    matched_col = "id::text"
                elif 'period_code' in fp_cols:
                    matched_col = "period_code::text"
                elif 'code' in fp_cols:
                    matched_col = "code::text"
                elif 'period_number' in fp_cols:
                    matched_col = "period_number::text"
                else:
                    self._add_result(name, category, True,
                        details={"note": "Tidak ada kolom referensi yang kompatibel di fiscal_period"},
                        severity=AuditSeverity.WARNING,
                        duration=time.perf_counter() - start)
                    return

            query = f"""
                SELECT DISTINCT fiscal_period
                FROM general_ledger
                WHERE fiscal_period IS NOT NULL
                AND fiscal_period NOT IN (SELECT {matched_col} FROM fiscal_period WHERE {matched_col} IS NOT NULL)
                LIMIT 20
            """
            rows = await self._run_sql(query)

            if rows:
                self._add_result(name, category, False,
                    error=f"Ditemukan {len(rows)} transaksi dengan fiscal_period yang tidak valid",
                    details={"sample": [r.get('fiscal_period') for r in rows]},
                    severity=AuditSeverity.ERROR,
                    suggested_fix="Periksa referensi fiscal_period di general_ledger dan pastikan period valid.",
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details={"status": "Semua periode valid"},
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 7: OPTIMISTIC LOCK VERSION CONSISTENCY
    # ================================================================
    async def test_optimistic_lock_consistency(self):
        start = time.perf_counter()
        name = "Optimistic Lock Version Consistency"
        category = "CONCURRENCY"

        try:
            tables = ['general_ledger', 'account', 'journal', 'invoices', 'purchase_orders']
            found_version = None
            for tbl in tables:
                if await self._table_exists(tbl):
                    cols = await self._get_table_schema(tbl)
                    if 'version' in cols:
                        found_version = (tbl, cols)
                        break

            if not found_version:
                self._add_result(name, category, True,
                    details={"note": "Tidak ada tabel utama yang memiliki kolom version"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            table_name, cols = found_version
            query = f"SELECT id, version FROM {table_name} WHERE version IS NOT NULL ORDER BY id LIMIT 100"
            rows = await self._run_sql(query)

            if rows:
                invalid = [r for r in rows if int(r.get('version', 0)) <= 0]
                if invalid:
                    self._add_result(name, category, False,
                        error=f"Ditemukan {len(invalid)} record dengan version <= 0",
                        details={"sample": invalid[:5]},
                        severity=AuditSeverity.ERROR,
                        suggested_fix="Version harus dimulai dari 1 dan increment untuk setiap update.",
                        duration=time.perf_counter() - start)
                    return

                self._add_result(name, category, True,
                    details={"table": table_name, "checked": len(rows)},
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details={"table": table_name, "note": "Tidak ada data"},
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 8: AUDIT TRAIL INTEGRITY (Immutability)
    # ================================================================
    async def test_audit_trail_integrity(self):
        start = time.perf_counter()
        name = "Audit Trail Integrity (Immutability)"
        category = "SECURITY"

        try:
            audit_tables = ['audit_trail', 'audit_log', 'event_log']
            found = None
            for tbl in audit_tables:
                if await self._table_exists(tbl):
                    found = tbl
                    break

            if not found:
                self._add_result(name, category, True,
                    details={"note": "Tidak ada tabel audit trail yang ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            cols = await self._get_table_schema(found)
            if 'hash' not in cols or 'previous_hash' not in cols:
                self._add_result(name, category, True,
                    details={"note": f"Tabel {found} tidak memiliki kolom hash/previous_hash"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            query = f"""
                SELECT id, hash, previous_hash, created_at
                FROM {found}
                WHERE hash IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 100
            """
            rows = await self._run_sql(query)

            if len(rows) < 2:
                self._add_result(name, category, True,
                    details={"note": "Data audit kurang dari 2 record, tidak bisa cek rantai"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            rows_rev = list(reversed(rows))
            broken = False
            for i in range(1, len(rows_rev)):
                prev = rows_rev[i-1]
                curr = rows_rev[i]
                if prev.get('hash') and curr.get('previous_hash'):
                    if prev['hash'] != curr['previous_hash']:
                        broken = True
                        break

            if broken:
                self._add_result(name, category, False,
                    error="Rantai hash audit trail terputus! Ada indikasi modifikasi data.",
                    details={"records_checked": len(rows)},
                    severity=AuditSeverity.CRITICAL,
                    suggested_fix="Investigasi segera! Ada indikasi data diubah tanpa izin.",
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details={"records_checked": len(rows), "status": "INTACT"},
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 9: ORPHANED RECORDS (Journal tanpa periode)
    # ================================================================
    async def test_orphaned_records(self):
        start = time.perf_counter()
        name = "Orphaned Records (Journal tanpa periode)"
        category = "DATA_INTEGRITY"

        try:
            if not await self._table_exists("general_ledger"):
                self._add_result(name, category, True,
                    details={"note": "Tabel general_ledger tidak ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            cols = await self._get_table_schema("general_ledger")
            if 'journal_id' not in cols:
                self._add_result(name, category, True,
                    details={"note": "general_ledger tidak memiliki kolom journal_id"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            if not await self._table_exists("journal"):
                self._add_result(name, category, True,
                    details={"note": "Tabel journal tidak ditemukan"},
                    severity=AuditSeverity.WARNING,
                    duration=time.perf_counter() - start)
                return

            query = """
                SELECT DISTINCT journal_id
                FROM general_ledger
                WHERE journal_id IS NOT NULL
                AND journal_id NOT IN (SELECT id FROM journal)
                LIMIT 20
            """
            rows = await self._run_sql(query)

            if rows:
                self._add_result(name, category, False,
                    error=f"Ditemukan {len(rows)} journal_id orphan di general_ledger",
                    details={"sample": [r.get('journal_id') for r in rows]},
                    severity=AuditSeverity.ERROR,
                    suggested_fix="Perbaiki referensi journal_id di general_ledger atau tambahkan journal yang hilang.",
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details={"status": "Tidak ada orphaned record"},
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # TEST 10: DUPLICATE MASTER DATA (Account, Customer, etc.)
    # ================================================================
    async def test_duplicate_master_data(self):
        start = time.perf_counter()
        name = "Duplicate Master Data (Account, Customer, dll.)"
        category = "DATA_INTEGRITY"

        try:
            duplicates_found = []
            if await self._table_exists("account"):
                cols = await self._get_table_schema("account")
                code_col = None
                for col in ['code', 'account_code', 'name']:
                    if col in cols:
                        code_col = col
                        break
                if code_col:
                    query = f"""
                        SELECT {code_col}, COUNT(*) as cnt
                        FROM account
                        GROUP BY {code_col}
                        HAVING COUNT(*) > 1
                        LIMIT 10
                    """
                    rows = await self._run_sql(query)
                    if rows:
                        duplicates_found.append({
                            "table": "account",
                            "field": code_col,
                            "count": len(rows),
                            "sample": rows[:3]
                        })

            if await self._table_exists("customer"):
                cols = await self._get_table_schema("customer")
                code_col = None
                for col in ['customer_code', 'code', 'email']:
                    if col in cols:
                        code_col = col
                        break
                if code_col:
                    query = f"""
                        SELECT {code_col}, COUNT(*) as cnt
                        FROM customer
                        GROUP BY {code_col}
                        HAVING COUNT(*) > 1
                        LIMIT 10
                    """
                    rows = await self._run_sql(query)
                    if rows:
                        duplicates_found.append({
                            "table": "customer",
                            "field": code_col,
                            "count": len(rows),
                            "sample": rows[:3]
                        })

            if await self._table_exists("supplier"):
                cols = await self._get_table_schema("supplier")
                code_col = None
                for col in ['supplier_code', 'code', 'email']:
                    if col in cols:
                        code_col = col
                        break
                if code_col:
                    query = f"""
                        SELECT {code_col}, COUNT(*) as cnt
                        FROM supplier
                        GROUP BY {code_col}
                        HAVING COUNT(*) > 1
                        LIMIT 10
                    """
                    rows = await self._run_sql(query)
                    if rows:
                        duplicates_found.append({
                            "table": "supplier",
                            "field": code_col,
                            "count": len(rows),
                            "sample": rows[:3]
                        })

            if duplicates_found:
                self._add_result(name, category, False,
                    error=f"Ditemukan duplikasi data master di {len(duplicates_found)} tabel",
                    details={"duplicates": duplicates_found},
                    severity=AuditSeverity.ERROR,
                    suggested_fix="Tambahkan unique constraint atau validasi sebelum insert.",
                    duration=time.perf_counter() - start)
            else:
                self._add_result(name, category, True,
                    details={"status": "Tidak ada duplikasi yang ditemukan"},
                    duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(name, category, False,
                error=str(e), exc=e,
                severity=AuditSeverity.ERROR,
                duration=time.perf_counter() - start)

    # ================================================================
    # CLEANUP
    # ================================================================
    async def _cleanup_async(self):
        try:
            factory = self._get_session_factory()
            if factory:
                engine = None
                if hasattr(factory, 'bind'):
                    engine = factory.bind
                elif hasattr(factory, '_engine'):
                    engine = factory._engine
                elif hasattr(factory, 'engine'):
                    engine = factory.engine
                if engine and hasattr(engine, 'dispose'):
                    if hasattr(engine, '_async_engine') and hasattr(engine._async_engine, 'dispose'):
                        await engine._async_engine.dispose()
                    elif hasattr(engine, 'sync_engine') and hasattr(engine.sync_engine, 'dispose'):
                        engine.sync_engine.dispose()
                    elif hasattr(engine, 'dispose'):
                        engine.dispose()
        except:
            pass

    # ================================================================
    # RUN ALL TESTS
    # ================================================================
    async def run_all_async(self):
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

    def run_all(self):
        logger.info("=" * 70)
        logger.info("🔍 ENTERPRISE AUDIT CHECKER v1.5.3 - REAL SCANNING WITH RCA")
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
            logger.critical("❌ STATUS: DATA INTEGRITY ISSUES DETECTED — DO NOT DEPLOY! 🛑")
        else:
            logger.info("✅ STATUS: ALL DATA INTEGRITY CHECKS PASSED — READY FOR AUDIT! 🚀")

        logger.info("=" * 70)

        report = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "version": "1.5.3",
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


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Enterprise Audit Checker v1.5.3")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed tracebacks")
    parser.add_argument("--test-env", action="store_true", help="Test environment flag")
    args = parser.parse_args()

    runner = EnterpriseAuditRunner(verbose=args.verbose, test_env=args.test_env)
    runner.run_all()


if __name__ == "__main__":
    main()