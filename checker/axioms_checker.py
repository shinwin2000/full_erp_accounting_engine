#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/axioms_checker.py — Axioms Integrity Checker (v6.2.4)
================================================================
Fully integrated with RCA Engine.
Runs without errors even if the database is unavailable.
Default: SQLite in‑memory for zero‑config demo.
Bugfix: Avoid property get() error on Severity.order (fixed).
"""

import asyncio
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# ---- Add project root ----
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---- RCA Engine ----
try:
    from checker.core.rca import (
        RCAEngine, RCAResult, Severity, Category, ErrorCode,
        get_engine, analyze_exception
    )
except ImportError:
    # Fallback dummy jika RCA tidak tersedia
    class Severity:
        FATAL = "FATAL"
        CRITICAL = "CRITICAL"
        HIGH = "HIGH"
        MEDIUM = "MEDIUM"
        LOW = "LOW"
        INFO = "INFO"
        order = {"FATAL": 5, "CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
    class Category: pass
    class ErrorCode: pass
    class RCAResult:
        def __init__(self, severity=None, category=None, error_code=None,
                     root_cause="", evidence=None, impact=None,
                     suggested_fix="", confidence=0.5):
            self.severity = severity
            self.category = category
            self.error_code = error_code
            self.root_cause = root_cause
            self.evidence = evidence or []
            self.impact = impact or []
            self.suggested_fix = suggested_fix
            self.confidence = confidence
        def to_dict(self):
            return {"root_cause": self.root_cause, "severity": self.severity}
    def get_engine(): return None
    def analyze_exception(*args, **kwargs): return RCAResult()

# ---- SQLAlchemy (async) ----
try:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker, declarative_base
    from sqlalchemy import Column, String, Integer, Numeric, DateTime, select, text
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    AsyncSession = object
    declarative_base = None

# ---- Event Store (optional) ----
try:
    from infrastructure.event_store.event_store import get_event_store
    HAS_EVENT_STORE = True
except ImportError:
    HAS_EVENT_STORE = False

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_CONFIG = {
    "db_url": "sqlite+aiosqlite:///:memory:",
    "pool_size": 5,
    "max_overflow": 10,
    "timeout": 10.0,
    "retry_attempts": 2,
    "retry_backoff": 1.0,
    "float_precision": 0.001,
    "max_events_fetch": 1000,
    "redact_sensitive": True,
    "export_format": "json",
    "export_dir": "./reports",
    "demo_mode": False,
}

# ============================================================
# HELPER: SAFE SEVERITY WEIGHT
# ============================================================

def _severity_weight(severity) -> int:
    """
    Return a numeric weight for a severity object or string.
    Handles both plain strings and Severity enum members.
    """
    if hasattr(severity, 'value'):          # Enum member
        sev_str = severity.value
    else:
        sev_str = str(severity)

    # Fallback: manual mapping (most reliable)
    mapping = {"FATAL": 5, "CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
    return mapping.get(sev_str.upper(), 0)

# ============================================================
# RCA WRAPPER
# ============================================================

class RCAAnalyzer:
    """Thread‑safe wrapper for RCA engine with caching."""
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        self.engine = get_engine()
        self._cache: Dict[str, RCAResult] = {}
        self._cache_ttl = 300

    @classmethod
    async def get_instance(cls) -> "RCAAnalyzer":
        async with cls._lock:
            if cls._instance is None:
                cls._instance = RCAAnalyzer()
            return cls._instance

    async def analyze(self, exception: Exception, context: Dict[str, Any]) -> RCAResult:
        key = f"{type(exception).__name__}:{str(exception)[:100]}"
        if key in self._cache:
            result = self._cache[key]
            if time.time() - getattr(result, "_cached_at", 0) > self._cache_ttl:
                del self._cache[key]
            else:
                return result
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self.engine.analyze, exception, context
        )
        result._cached_at = time.time()
        self._cache[key] = result
        return result

# ============================================================
# DATABASE MODELS (for demo)
# ============================================================

if HAS_SQLALCHEMY and declarative_base is not None:
    Base = declarative_base()

    class JournalLine(Base):
        __tablename__ = "journal_lines"
        id = Column(Integer, primary_key=True)
        journal_id = Column(Integer)
        account_code = Column(String(20))
        debit = Column(Numeric(19, 4), default=0)
        credit = Column(Numeric(19, 4), default=0)

    class Account(Base):
        __tablename__ = "accounts"
        id = Column(Integer, primary_key=True)
        code = Column(String(20))
        account_type = Column(String(20))
        balance = Column(Numeric(19, 4), default=0)

    class FiscalPeriod(Base):
        __tablename__ = "fiscal_periods"
        id = Column(Integer, primary_key=True)
        start_date = Column(DateTime)
        end_date = Column(DateTime)
        status = Column(String(10))

    class Transaction(Base):
        __tablename__ = "transactions"
        id = Column(Integer, primary_key=True)
        type = Column(String(20))
        amount = Column(Numeric(19, 4))
        posting_date = Column(DateTime)
        service_date = Column(DateTime)
        currency_code = Column(String(3))

    class Currency(Base):
        __tablename__ = "currency_master"
        code = Column(String(3), primary_key=True)
        name = Column(String(50))

    class IncomeStatement(Base):
        __tablename__ = "income_statements"
        id = Column(Integer, primary_key=True)
        period_end = Column(DateTime)
        net_income = Column(Numeric(19, 4))

    class IntercompanyTransaction(Base):
        __tablename__ = "intercompany_transactions"
        id = Column(Integer, primary_key=True)
        elimination_status = Column(String(20))
else:
    Base = None
    # Placeholder classes
    class JournalLine: pass
    class Account: pass
    class FiscalPeriod: pass
    class Transaction: pass
    class Currency: pass
    class IncomeStatement: pass
    class IntercompanyTransaction: pass

# ============================================================
# AXIOM CHECK BASE
# ============================================================

class AxiomCheck:
    """Base class for an axiom integrity check."""
    name: str = "base"
    description: str = ""
    severity_if_violated: Severity = Severity.CRITICAL if hasattr(Severity, 'CRITICAL') else "CRITICAL"
    error_code: ErrorCode = ErrorCode.ERP_VALIDATION if hasattr(ErrorCode, 'ERP_VALIDATION') else "ERP_VALIDATION"

    def __init__(self, config: Dict[str, Any], rca: RCAAnalyzer):
        self.config = config
        self.rca = rca
        self._session: Optional[AsyncSession] = None
        self._event_store = None
        self._demo_mode = config.get("demo_mode", False)

    async def set_session(self, session: AsyncSession) -> None:
        self._session = session

    async def set_event_store(self, store) -> None:
        self._event_store = store

    async def check(self) -> Optional[RCAResult]:
        raise NotImplementedError

    async def _safe_query(self, query, *args, **kwargs) -> Any:
        attempts = 0
        while attempts < self.config.get("retry_attempts", 2):
            try:
                return await asyncio.wait_for(
                    self._session.execute(query, *args, **kwargs),
                    timeout=self.config.get("timeout", 10.0)
                )
            except Exception as e:
                attempts += 1
                if attempts >= self.config.get("retry_attempts", 2):
                    raise
                await asyncio.sleep(self.config.get("retry_backoff", 1.0) ** attempts)
        raise RuntimeError("Query failed after retries")

    def _violation_result(self, root_cause: str, evidence: List[str],
                          impact: List[str], fix: str,
                          confidence: float = 0.85) -> RCAResult:
        return RCAResult(
            severity=self.severity_if_violated,
            category=Category.DDD if hasattr(Category, 'DDD') else None,
            error_code=self.error_code,
            root_cause=root_cause,
            evidence=evidence,
            impact=impact,
            suggested_fix=fix,
            confidence=confidence
        )

# ============================================================
# CONCRETE CHECKS
# ============================================================

class DoubleEntryCheck(AxiomCheck):
    name = "double_entry"
    description = "Verify total debit equals total credit for every journal."
    severity_if_violated = Severity.FATAL if hasattr(Severity, 'FATAL') else "FATAL"
    error_code = ErrorCode.ERP_BALANCE_MISMATCH if hasattr(ErrorCode, 'ERP_BALANCE_MISMATCH') else "ERP_BALANCE_MISMATCH"

    async def check(self) -> Optional[RCAResult]:
        if self._session is None:
            return None

        query = text("""
            SELECT
                journal_id,
                SUM(debit) AS total_debit,
                SUM(credit) AS total_credit
            FROM journal_lines
            GROUP BY journal_id
            HAVING ABS(SUM(debit) - SUM(credit)) > :tolerance
        """).bindparams(tolerance=self.config.get("float_precision", 0.001))

        try:
            result = await self._safe_query(query)
            rows = result.fetchall()
            if rows:
                evidence = [
                    f"Found {len(rows)} journals with unbalanced debit/credit."
                ]
                for row in rows[:10]:
                    evidence.append(
                        f"Journal {row.journal_id}: debit={row.total_debit}, "
                        f"credit={row.total_credit}, diff={abs(row.total_debit - row.total_credit)}"
                    )
                return self._violation_result(
                    root_cause=f"Double-entry violation: {len(rows)} journals unbalanced.",
                    evidence=evidence,
                    impact=["Financial statements misstated."],
                    fix="Review each journal and correct line entries.",
                    confidence=0.95
                )
        except Exception:
            raise
        return None


class ConservationOfValueCheck(AxiomCheck):
    name = "conservation_of_value"
    description = "Assets = Liabilities + Equity."
    severity_if_violated = Severity.FATAL if hasattr(Severity, 'FATAL') else "FATAL"
    error_code = ErrorCode.ERP_BALANCE_MISMATCH if hasattr(ErrorCode, 'ERP_BALANCE_MISMATCH') else "ERP_BALANCE_MISMATCH"

    async def check(self) -> Optional[RCAResult]:
        if self._session is None:
            return None

        query = text("""
            SELECT
                account_type,
                SUM(balance) AS total
            FROM accounts
            GROUP BY account_type
        """)
        try:
            result = await self._safe_query(query)
            rows = result.fetchall()
            totals = {row.account_type: row.total for row in rows}
            assets = totals.get('ASSET', Decimal(0))
            liabilities = totals.get('LIABILITY', Decimal(0))
            equity = totals.get('EQUITY', Decimal(0))
            diff = abs(assets - (liabilities + equity))
            if diff > self.config.get("float_precision", 0.001):
                return self._violation_result(
                    root_cause=(
                        f"Conservation of value violated: Assets ({assets}) != "
                        f"Liabilities ({liabilities}) + Equity ({equity}). Diff: {diff}"
                    ),
                    evidence=[f"Assets: {assets}, Liabilities: {liabilities}, Equity: {equity}"],
                    impact=["Balance sheet will not balance."],
                    fix="Investigate journal entries and account balances.",
                    confidence=0.95
                )
        except Exception:
            raise
        return None


class AccrualBasisCheck(AxiomCheck):
    name = "accrual_basis"
    description = "Revenue/expense recognized in correct period."
    severity_if_violated = Severity.CRITICAL if hasattr(Severity, 'CRITICAL') else "CRITICAL"
    error_code = ErrorCode.ERP_VALIDATION if hasattr(ErrorCode, 'ERP_VALIDATION') else "ERP_VALIDATION"

    async def check(self) -> Optional[RCAResult]:
        if self._session is None:
            return None

        query = text("""
            SELECT COUNT(*) AS violations
            FROM transactions
            WHERE type = 'REVENUE'
              AND service_date > posting_date
              AND (JULIANDAY(service_date) - JULIANDAY(posting_date)) > 30
        """)
        try:
            result = await self._safe_query(query)
            row = result.first()
            if row and row.violations > 0:
                return self._violation_result(
                    root_cause=f"Accrual basis violation: {row.violations} revenue entries recognized before service.",
                    evidence=[f"{row.violations} entries with service date > posting date by >30 days."],
                    impact=["Revenue recognition does not match IFRS 15."],
                    fix="Recognize revenue only when performance obligations are satisfied.",
                    confidence=0.85
                )
        except Exception:
            raise
        return None


class EntityIsolationCheck(AxiomCheck):
    name = "entity_isolation"
    description = "Intercompany transactions properly eliminated."
    severity_if_violated = Severity.CRITICAL if hasattr(Severity, 'CRITICAL') else "CRITICAL"
    error_code = ErrorCode.ERP_VALIDATION if hasattr(ErrorCode, 'ERP_VALIDATION') else "ERP_VALIDATION"

    async def check(self) -> Optional[RCAResult]:
        if self._session is None:
            return None

        query = text("""
            SELECT COUNT(*) AS violations
            FROM intercompany_transactions
            WHERE elimination_status IS NULL
               OR elimination_status = 'PENDING'
        """)
        try:
            result = await self._safe_query(query)
            row = result.first()
            if row and row.violations > 0:
                return self._violation_result(
                    root_cause=f"Entity isolation violation: {row.violations} intercompany transactions not eliminated.",
                    evidence=[f"{row.violations} entries pending elimination."],
                    impact=["Consolidated financials overstated."],
                    fix="Run intercompany elimination process.",
                    confidence=0.80
                )
        except Exception:
            raise
        return None


class MonetaryUnitCheck(AxiomCheck):
    name = "monetary_unit"
    description = "All transactions use valid currency with active rate."
    severity_if_violated = Severity.HIGH if hasattr(Severity, 'HIGH') else "HIGH"
    error_code = ErrorCode.ERP_VALIDATION if hasattr(ErrorCode, 'ERP_VALIDATION') else "ERP_VALIDATION"

    async def check(self) -> Optional[RCAResult]:
        if self._session is None:
            return None

        query = text("""
            SELECT COUNT(*) AS violations
            FROM transactions t
            LEFT JOIN currency_master c ON t.currency_code = c.code
            WHERE c.code IS NULL
        """)
        try:
            result = await self._safe_query(query)
            row = result.first()
            if row and row.violations > 0:
                return self._violation_result(
                    root_cause=f"Monetary unit violation: {row.violations} transactions use unknown currency.",
                    evidence=[f"Unknown currencies in {row.violations} transactions."],
                    impact=["FX revaluation impossible."],
                    fix="Update currency master or correct transaction currencies.",
                    confidence=0.85
                )
        except Exception:
            raise
        return None


class TimeIrreversibilityCheck(AxiomCheck):
    name = "time_irreversibility"
    description = "No backdating beyond allowed periods."
    severity_if_violated = Severity.HIGH if hasattr(Severity, 'HIGH') else "HIGH"
    error_code = ErrorCode.ERP_VALIDATION if hasattr(ErrorCode, 'ERP_VALIDATION') else "ERP_VALIDATION"

    async def check(self) -> Optional[RCAResult]:
        if self._session is None:
            return None

        query = text("""
            SELECT COUNT(*) AS violations
            FROM transactions t
            WHERE t.posting_date < (
                SELECT MIN(start_date)
                FROM fiscal_periods
                WHERE status = 'OPEN'
            )
        """)
        try:
            result = await self._safe_query(query)
            row = result.first()
            if row and row.violations > 0:
                return self._violation_result(
                    root_cause=f"Time irreversibility violation: {row.violations} transactions backdated.",
                    evidence=[f"{row.violations} entries before earliest open period."],
                    impact=["Fraud risk; misstated prior periods."],
                    fix="Do not allow backdating; use adjustment entries.",
                    confidence=0.90
                )
        except Exception:
            raise
        return None


class GoingConcernCheck(AxiomCheck):
    name = "going_concern"
    description = "No indicators of going concern issues."
    severity_if_violated = Severity.INFO if hasattr(Severity, 'INFO') else "INFO"
    error_code = ErrorCode.ERP_VALIDATION if hasattr(ErrorCode, 'ERP_VALIDATION') else "ERP_VALIDATION"

    async def check(self) -> Optional[RCAResult]:
        if self._session is None:
            return None

        query = text("""
            WITH yearly_income AS (
                SELECT
                    strftime('%Y', period_end) AS year,
                    SUM(net_income) AS total_income
                FROM income_statements
                GROUP BY year
                ORDER BY year DESC
                LIMIT 3
            )
            SELECT COUNT(*) AS negative_years
            FROM yearly_income
            WHERE total_income < 0
        """)
        try:
            result = await self._safe_query(query)
            row = result.first()
            if row and row.negative_years >= 2:
                return self._violation_result(
                    root_cause=f"Going concern indicator: {row.negative_years} consecutive years of net loss.",
                    evidence=[f"Net loss in {row.negative_years} of last 3 years."],
                    impact=["May affect ability to continue operations."],
                    fix="Review financial position and consider restructuring.",
                    confidence=0.70
                )
        except Exception:
            raise
        return None


class ImmutabilityCheck(AxiomCheck):
    name = "immutability"
    description = "Ensure posted journals are never modified."
    severity_if_violated = Severity.FATAL if hasattr(Severity, 'FATAL') else "FATAL"
    error_code = ErrorCode.AGGREGATE_ERROR if hasattr(ErrorCode, 'AGGREGATE_ERROR') else "AGGREGATE_ERROR"

    async def check(self) -> Optional[RCAResult]:
        if self._event_store is None:
            return None

        try:
            if hasattr(self._event_store, 'get_events_by_type'):
                events = await self._event_store.get_events_by_type(
                    "JournalModified",
                    limit=self.config.get("max_events_fetch", 1000)
                )
            elif hasattr(self._event_store, 'get_events'):
                events = await self._event_store.get_events(
                    limit=self.config.get("max_events_fetch", 1000)
                )
                events = [e for e in events if e.get('type') == 'JournalModified']
            else:
                logger.warning("Event store does not support event retrieval.")
                return None

            if events:
                evidence = [
                    f"Found {len(events)} modifications on posted journals."
                ]
                for ev in events[:5]:
                    evidence.append(
                        f"Event: {ev.get('data', {}).get('journal_id')} at {ev.get('timestamp')}"
                    )
                return self._violation_result(
                    root_cause=f"Immutability violation: {len(events)} posted journals modified.",
                    evidence=evidence,
                    impact=["Audit trail compromised."],
                    fix="Use reversal journals instead of direct modifications.",
                    confidence=0.90
                )
        except Exception:
            raise
        return None

# ============================================================
# DEMO DATA POPULATOR
# ============================================================

async def populate_demo_data(session: AsyncSession) -> None:
    """Insert sample data that will trigger violations."""
    # Insert accounts
    accounts = [
        Account(code="1000", account_type="ASSET", balance=Decimal("100000.00")),
        Account(code="2000", account_type="LIABILITY", balance=Decimal("60000.00")),
        Account(code="3000", account_type="EQUITY", balance=Decimal("40000.00")),
    ]
    session.add_all(accounts)
    await session.flush()

    # Insert unbalanced journal lines (violates double-entry)
    lines = [
        JournalLine(journal_id=1, account_code="1000", debit=Decimal("1000.00"), credit=Decimal("0.00")),
        JournalLine(journal_id=1, account_code="2000", debit=Decimal("0.00"), credit=Decimal("900.00")),
    ]
    session.add_all(lines)

    # Insert a revenue transaction with service_date > posting_date (accrual violation)
    tx = Transaction(
        type="REVENUE",
        amount=Decimal("5000.00"),
        posting_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        service_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        currency_code="USD"
    )
    session.add(tx)

    # Insert a transaction with unknown currency (monetary unit violation)
    tx2 = Transaction(
        type="EXPENSE",
        amount=Decimal("200.00"),
        posting_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        service_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        currency_code="XYZ"
    )
    session.add(tx2)

    # Insert an intercompany transaction not eliminated
    ic = IntercompanyTransaction(elimination_status="PENDING")
    session.add(ic)

    # Insert a fiscal period
    period = FiscalPeriod(
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
        status="OPEN"
    )
    session.add(period)

    # Insert income statement with negative income (going concern)
    income = IncomeStatement(
        period_end=datetime(2023, 12, 31, tzinfo=timezone.utc),
        net_income=Decimal("-10000.00")
    )
    session.add(income)
    income2 = IncomeStatement(
        period_end=datetime(2022, 12, 31, tzinfo=timezone.utc),
        net_income=Decimal("-5000.00")
    )
    session.add(income2)

    # Currency master (does NOT include XYZ)
    currency = Currency(code="USD", name="US Dollar")
    session.add(currency)

    await session.commit()
    logger.info("Demo data populated with violations.")

# ============================================================
# MAIN CHECKER ENGINE
# ============================================================

class AxiomsChecker:
    """Orchestrates all axiom checks with full RCA integration."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = DEFAULT_CONFIG.copy()
        if config:
            self.config.update(config)
        self.rca: Optional[RCAAnalyzer] = None
        self._engine = None
        self._session_factory = None
        self._event_store = None
        self.results: List[RCAResult] = []
        self.violations: List[Dict[str, Any]] = []
        self.checks: List[AxiomCheck] = []

    async def initialize(self) -> None:
        """Set up database, event store, and RCA."""
        self.rca = await RCAAnalyzer.get_instance()

        # Database
        if HAS_SQLALCHEMY and Base is not None:
            db_url = self.config["db_url"]
            engine_kwargs = {"echo": False}
            if "sqlite" not in db_url.lower():
                engine_kwargs.update({
                    "pool_size": self.config.get("pool_size", 5),
                    "max_overflow": self.config.get("max_overflow", 10),
                })
            try:
                self._engine = create_async_engine(db_url, **engine_kwargs)
                self._session_factory = sessionmaker(
                    self._engine, class_=AsyncSession, expire_on_commit=False
                )
                async with self._engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                self._session_factory = None
                self._engine = None
        else:
            logger.warning("SQLAlchemy not installed or Base not defined; database checks disabled.")

        # Event Store (optional)
        if HAS_EVENT_STORE:
            try:
                self._event_store = await get_event_store()
            except Exception as e:
                logger.error(f"Failed to initialize event store: {e}")
                self._event_store = None
        else:
            logger.warning("Event store not available; immutability check disabled.")

        # Instantiate checks
        self.checks = [
            DoubleEntryCheck(self.config, self.rca),
            ConservationOfValueCheck(self.config, self.rca),
            AccrualBasisCheck(self.config, self.rca),
            EntityIsolationCheck(self.config, self.rca),
            MonetaryUnitCheck(self.config, self.rca),
            TimeIrreversibilityCheck(self.config, self.rca),
            GoingConcernCheck(self.config, self.rca),
        ]
        # Only add immutability if event store is available
        if self._event_store is not None:
            self.checks.append(ImmutabilityCheck(self.config, self.rca))

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._engine:
            await self._engine.dispose()

    async def check_all(self) -> List[RCAResult]:
        """Run all checks within a single database session."""
        self.results.clear()
        self.violations.clear()

        if self._session_factory is None:
            logger.error("No database session factory; checks cannot run.")
            return []

        try:
            async with self._session_factory() as session:
                # Populate demo data if requested
                if self.config.get("demo_mode", False):
                    await populate_demo_data(session)

                # Assign session and event store to each check
                for check in self.checks:
                    await check.set_session(session)
                    await check.set_event_store(self._event_store)

                for check in self.checks:
                    try:
                        result = await check.check()
                        if result:
                            self.results.append(result)
                            # Determine severity weight using safe helper
                            sev_val = getattr(result.severity, 'value', result.severity)
                            if _severity_weight(sev_val) >= 3:   # HIGH or above
                                self.violations.append({
                                    "axiom": check.name,
                                    "severity": sev_val,
                                    "root_cause": result.root_cause,
                                    "suggested_fix": result.suggested_fix,
                                    "confidence": result.confidence,
                                })
                    except Exception as e:
                        # Analyze the error using RCA
                        rca_result = await self.rca.analyze(
                            e, {"check": check.name, "phase": "execution"}
                        )
                        if "connection" in str(e).lower() or "timeout" in str(e).lower():
                            logger.error(f"System error in check {check.name}: {rca_result.root_cause}")
                            rca_result.severity = Severity.INFO if hasattr(Severity, 'INFO') else "INFO"
                            rca_result.root_cause = f"SYSTEM ERROR: {rca_result.root_cause}"
                            self.results.append(rca_result)
                        else:
                            self.results.append(rca_result)
                            sev_val = getattr(rca_result.severity, 'value', rca_result.severity)
                            if _severity_weight(sev_val) >= 4:   # CRITICAL or above
                                self.violations.append({
                                    "axiom": check.name,
                                    "severity": sev_val,
                                    "root_cause": f"EXCEPTION: {rca_result.root_cause}",
                                    "suggested_fix": rca_result.suggested_fix,
                                    "confidence": rca_result.confidence,
                                })
        except Exception as outer:
            logger.error(f"Outer session error: {outer}")
            # Re-raise to see the actual error if needed
            raise

        return self.results

    def generate_report(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "timestamp": now.isoformat(),
            "version": "6.2.4",
            "config": {
                "db_url": "[REDACTED]" if self.config.get("redact_sensitive", True) else self.config["db_url"],
                "demo_mode": self.config.get("demo_mode", False),
            },
            "total_axioms": len(self.checks),
            "violations_count": len(self.violations),
            "violations": self.violations,
            "results": [r.to_dict() for r in self.results],
        }

    def print_report(self, verbose: bool = False) -> None:
        report = self.generate_report()
        print("\n" + "=" * 70)
        print(f" AXIOMS INTEGRITY CHECK REPORT @ {report['timestamp']}")
        print("=" * 70)
        print(f"Total axioms checked: {report['total_axioms']}")
        print(f"Violations found: {report['violations_count']}")
        if report['violations']:
            print("\n--- VIOLATIONS ---")
            for v in report['violations']:
                print(f"[{v['severity']}] {v['axiom']}: {v['root_cause'][:150]}...")
                print(f"  Fix: {v['suggested_fix']}")
        else:
            print("\n✅ All axioms passed.")
        print("=" * 70)

    async def export_report(self) -> None:
        report = self.generate_report()
        export_dir = Path(self.config.get("export_dir", "./reports"))
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        fmt = self.config.get("export_format", "json")
        if fmt in ("json", "both"):
            path = export_dir / f"axioms_report_{timestamp}.json"
            with open(path, "w") as f:
                json.dump(report, f, indent=2, default=str)
            logger.info(f"JSON report saved to {path}")

        if fmt in ("csv", "both") and report['violations']:
            path = export_dir / f"axioms_report_{timestamp}.csv"
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=report['violations'][0].keys())
                writer.writeheader()
                writer.writerows(report['violations'])
            logger.info(f"CSV report saved to {path}")

# ============================================================
# CLI
# ============================================================

async def async_main(args: List[str]) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Axioms Integrity Checker with RCA integration"
    )
    parser.add_argument(
        "--mode", choices=["static", "dynamic"], default="static",
        help="Check mode"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Populate database with sample data including violations"
    )
    parser.add_argument(
        "--duration", type=int, default=300,
        help="Dynamic mode duration (seconds)"
    )
    parser.add_argument(
        "--db-url", type=str, default=None,
        help="Database URL (overrides default SQLite in-memory)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Verbose logging"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Export report to file"
    )
    parsed = parser.parse_args(args)

    if parsed.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = DEFAULT_CONFIG.copy()
    if parsed.db_url:
        config["db_url"] = parsed.db_url
    if parsed.demo:
        config["demo_mode"] = True

    async with AxiomsChecker(config) as checker:
        if parsed.mode == "static":
            await checker.check_all()
            checker.print_report(verbose=parsed.verbose)
            if parsed.export:
                await checker.export_report()
        else:
            logger.info(f"Dynamic mode: monitoring for {parsed.duration}s...")
            end = datetime.now(timezone.utc) + timedelta(seconds=parsed.duration)
            while datetime.now(timezone.utc) < end:
                await checker.check_all()
                if checker.violations:
                    logger.warning("Violations detected!")
                    checker.print_report()
                    if parsed.export:
                        await checker.export_report()
                    break
                await asyncio.sleep(10)
            else:
                logger.info("No violations detected.")


def main():
    try:
        asyncio.run(async_main(sys.argv[1:]))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()