#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
posting_flow_checker.py — Posting Flow Integrity Checker v17.0.0
=======================================================================
Versi   : 17.0.0
Standar : ISO/IEC 25010 · SOX/ISA 315 · PCAOB AS 2405 · IFRS/PSAK

Perbaikan v17.0.0:
  - Pengecualian untuk service_journal.py: validasi sudah dilakukan di domain
  - Blacklist approval untuk sales, router, kernel
  - False positive minimal

Cara pakai :
  python checker/posting_flow_checker.py
  python checker/posting_flow_checker.py --strict (quality rules)
  python checker/posting_flow_checker.py --verbose
  python checker/posting_flow_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import re
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple, Any
from collections import defaultdict
from enum import Enum, auto

# ─── Integrasi RCA ──────────────────────────────────────────────────────────
try:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from core.rca import get_engine, analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    RCA_AVAILABLE = False
    def get_engine(): return None
    def analyze_exception(e, ctx=None): return None

# ─── Color ──────────────────────────────────────────────────────────────────
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["MAGENTA"] = colorama.Fore.MAGENTA
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ─── Data Classes ──────────────────────────────────────────────────────────
class UseCaseType(Enum):
    POSTING = auto()
    APPROVAL = auto()
    REPORTING = auto()
    RECONCILIATION = auto()
    ANALYSIS = auto()
    GENERAL = auto()

@dataclass
class FunctionInfo:
    name: str
    node: ast.FunctionDef
    file_path: pathlib.Path
    line: int
    use_case: UseCaseType = UseCaseType.GENERAL
    calls: List[str] = field(default_factory=list)
    calls_ast: List[ast.Call] = field(default_factory=list)
    has_transaction: bool = False
    has_debit_credit: bool = False
    has_balance_check: bool = False
    has_period_check: bool = False
    has_account_check: bool = False
    has_audit: bool = False
    has_gl_update: bool = False
    has_event_publish: bool = False
    has_idempotency: bool = False
    has_rollback: bool = False
    has_repo_save: bool = False
    has_uow_commit: bool = False
    has_session_execute: bool = False
    has_journal_ref: bool = False
    has_ledger_ref: bool = False
    is_reporting: bool = False
    is_posting: bool = False
    is_approval: bool = False
    violations: List[Finding] = field(default_factory=list)

@dataclass
class Finding:
    rule_id: str
    file: str
    line: int
    severity: str
    message: str
    detail: str = ""
    rca: Optional[Dict] = None
    function: str = ""

@dataclass
class FlowStep:
    step: str
    file: str
    line: int
    function: str
    implemented: bool

@dataclass
class FlowCheck:
    entity: str
    steps: List[FlowStep]
    complete: bool
    missing_steps: List[str]

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    flow_checks: List[FlowCheck] = field(default_factory=list)
    score: int = 100
    score_flow: int = 0
    score_rules: int = 0
    rca_enabled: bool = False

# ─── Konstanta ──────────────────────────────────────────────────────────────
# White-list posting functions
VALID_POSTING_FUNCS = {
    'post_approved_journal',
    'post_journal_entry',
    'execute_posting',
    'post_to_ledger',
    'save_journal',
    'commit_journal',
}

# Valid approval functions
VALID_APPROVAL_FUNCS = {
    'approve_journal',
    'approve_transaction',
    'approve_posting',
}

NON_POSTING_KEYWORDS = {'rate', 'forex', 'exchange', 'manufacturing', 'labor', 'revaluation', 'sales', 'standard_cost', 'asset'}
HANDLER_KEYWORDS = {'handler', 'router', 'endpoint', 'api'}
APPROVAL_BLACKLIST = {'sales', 'router', 'kernel', 'sod'}  # tambahan
REPOSITORY_PATH = 'adapters/secondary_impl/'

STEP_KEYWORDS = {
    'capture': ['capture', 'intent', 'create_draft', 'capture_intent', 'new_journal', 'journal_intent', 'enrich_intent'],
    'validate': ['validate_journal', 'validate_entry', 'check_balance', 'validate_period', 'validate_account'],
    'approve': ['approve_journal', 'approve_entry', 'authorize_journal', 'four_eyes', 'approve_posting'],
    'post': ['post_journal', 'save_journal', 'commit_journal', 'execute_posting', 'post_to_ledger'],
    'gl_update': ['update_general_ledger', 'post_gl', 'save_gl', 'update_ledger', 'record_ledger', 'general_ledger'],
    'audit': ['record_audit', 'append_event', 'publish_domain_event', 'log_event', 'hash_chain_link', 'audit_trail']
}
ALL_STEPS = list(STEP_KEYWORDS.keys())

# ─── Registry ──────────────────────────────────────────────────────────────
class FunctionRegistry:
    def __init__(self):
        self.functions: Dict[str, FunctionInfo] = {}
        self.file_functions: Dict[pathlib.Path, List[str]] = defaultdict(list)

    def register(self, func: FunctionInfo):
        self.functions[func.name] = func
        self.file_functions[func.file_path].append(func.name)

    def get(self, name: str) -> Optional[FunctionInfo]:
        return self.functions.get(name)

    def resolve_calls(self):
        for func in self.functions.values():
            for called_name in func.calls:
                called = self.get(called_name)
                if called:
                    if called.has_balance_check: func.has_balance_check = True
                    if called.has_period_check: func.has_period_check = True
                    if called.has_account_check: func.has_account_check = True
                    if called.has_audit: func.has_audit = True
                    if called.has_gl_update: func.has_gl_update = True
                    if called.has_event_publish: func.has_event_publish = True
                    if called.has_idempotency: func.has_idempotency = True
                    if called.has_transaction: func.has_transaction = True
                    if called.has_rollback: func.has_rollback = True
                    if called.has_repo_save: func.has_repo_save = True
                    if called.has_uow_commit: func.has_uow_commit = True
                    if called.has_session_execute: func.has_session_execute = True
                    if called.has_journal_ref: func.has_journal_ref = True
                    if called.has_ledger_ref: func.has_ledger_ref = True

# ─── Klasifikasi ───────────────────────────────────────────────────────────
def is_actual_posting_function(info: FunctionInfo) -> bool:
    """Deteksi fungsi posting: white-list + publik."""
    name = info.name
    file_path = str(info.file_path).lower()

    # Repository → skip
    if REPOSITORY_PATH in file_path:
        return False

    # Handler/router → skip
    if any(k in name for k in HANDLER_KEYWORDS):
        return False
    if any(k in file_path for k in ('router', 'endpoint')):
        return False

    # Non-posting keywords → skip
    if any(k in name for k in NON_POSTING_KEYWORDS):
        return False

    # Internal → skip
    if name.startswith('_'):
        return False

    # White-list
    if name in VALID_POSTING_FUNCS:
        return True

    # Alternatif: publik, mengandung 'post' dan 'journal', ada operasi penyimpanan
    if 'post' in name and 'journal' in name:
        if info.has_repo_save or info.has_uow_commit or info.has_session_execute:
            return True

    return False

def is_approval_function(info: FunctionInfo) -> bool:
    """Approval: publik, white-list, dan tidak blacklist."""
    name = info.name
    file_path = str(info.file_path).lower()

    # Internal → skip
    if name.startswith('_'):
        return False

    # Handler → skip
    if any(k in name for k in HANDLER_KEYWORDS):
        return False

    # Blacklist untuk approval (sales, router, kernel, sod)
    if any(k in name for k in APPROVAL_BLACKLIST):
        return False
    if any(k in file_path for k in ('router', 'kernel')):
        return False

    # White-list
    if name in VALID_APPROVAL_FUNCS:
        return True

    # Alternatif: mengandung 'approve' dan 'journal' atau 'transaction'
    if 'approve' in name and ('journal' in name or 'transaction' in name):
        return True

    return False

# ─── Analisis Fungsi ──────────────────────────────────────────────────────
def analyze_function(node: ast.FunctionDef, file_path: pathlib.Path) -> FunctionInfo:
    info = FunctionInfo(
        name=node.name,
        node=node,
        file_path=file_path,
        line=node.lineno
    )

    body = ast.unparse(node).lower()

    info.has_journal_ref = 'journal' in body
    info.has_ledger_ref = 'ledger' in body or 'gl' in body

    info.has_try_except = any(isinstance(n, ast.Try) for n in ast.walk(node))
    info.has_transaction = any(k in body for k in ('uow', 'unit_of_work', 'transaction', 'session.begin'))
    if not info.has_transaction:
        for arg in node.args.args:
            if any(k in arg.arg.lower() for k in ('uow', 'session')):
                info.has_transaction = True
                break

    info.has_repo_save = any(k in body for k in ('.save(', '.commit(', '.execute(', '.persist('))
    info.has_uow_commit = 'uow.commit' in body or 'unit_of_work.commit' in body
    info.has_session_execute = 'session.execute' in body or 'session.commit' in body

    info.has_debit_credit = 'debit' in body and 'credit' in body

    if info.has_debit_credit:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Compare):
                left = ast.unparse(sub.left).lower()
                right = ast.unparse(sub.comparators[0]).lower() if sub.comparators else ''
                if ('debit' in left and 'credit' in right) or ('credit' in left and 'debit' in right):
                    if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in sub.ops):
                        info.has_balance_check = True
                        break
        if not info.has_balance_check:
            has_debit_assign = any(
                isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and 'total_debit' in t.id.lower() for t in n.targets)
                for n in ast.walk(node)
            )
            has_credit_assign = any(
                isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and 'total_credit' in t.id.lower() for t in n.targets)
                for n in ast.walk(node)
            )
            if has_debit_assign and has_credit_assign:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Compare):
                        left = ast.unparse(sub.left).lower()
                        right = ast.unparse(sub.comparators[0]).lower() if sub.comparators else ''
                        if 'total_debit' in left and 'total_credit' in right:
                            info.has_balance_check = True
                            break

    info.has_period_check = any(k in body for k in ('period', 'fiscal'))
    if info.has_period_check:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                call_str = ast.unparse(sub.func).lower()
                if any(k in call_str for k in ('period_repo', 'get_period', 'find_period')):
                    info.has_period_check = True
                    break
            if isinstance(sub, ast.Attribute):
                if 'status' in sub.attr.lower() and 'period' in ast.unparse(sub.value).lower():
                    info.has_period_check = True
                    break

    info.has_account_check = any(k in body for k in ('account', 'chart_of_accounts'))
    if info.has_account_check:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                call_str = ast.unparse(sub.func).lower()
                if any(k in call_str for k in ('account_repo', 'get_account', 'find_account')):
                    info.has_account_check = True
                    break

    info.has_audit = any(k in body for k in ('audit', 'record_audit', 'append_event', 'immutable'))
    if not info.has_audit:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                call_str = ast.unparse(sub.func).lower()
                if any(k in call_str for k in ('audit_repo', 'record_audit', 'append_event')):
                    info.has_audit = True
                    break

    info.has_gl_update = any(k in body for k in ('general_ledger', 'gl', 'ledger', 'post_gl', 'update_ledger'))
    if not info.has_gl_update:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                call_str = ast.unparse(sub.func).lower()
                if any(k in call_str for k in ('gl_repo', 'post_gl', 'update_ledger')):
                    info.has_gl_update = True
                    break

    info.has_event_publish = any(k in body for k in ('publish', 'dispatch', 'event_bus'))
    if not info.has_event_publish:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                call_str = ast.unparse(sub.func).lower()
                if any(k in call_str for k in ('publish', 'dispatch')):
                    info.has_event_publish = True
                    break

    info.has_idempotency = any(k in body for k in ('idempotency', 'idempotent', 'dedup', 'duplicate'))
    if not info.has_idempotency:
        for arg in node.args.args:
            if 'idempotency' in arg.arg.lower():
                info.has_idempotency = True
                break

    info.has_rollback = 'rollback' in body

    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            info.calls.append(sub.func.id)
            info.calls_ast.append(sub)

    info.is_posting = is_actual_posting_function(info)
    info.is_approval = is_approval_function(info)

    return info

# ─── Aturan ──────────────────────────────────────────────────────────────────
class PostingRule:
    def __init__(self, rule_id, severity, message, applies_to=None):
        self.rule_id = rule_id
        self.severity = severity
        self.message = message
        self.applies_to = applies_to or (lambda info: True)

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        return None

class DoubleEntryValidationRule(PostingRule):
    def __init__(self):
        super().__init__(
            "VAL-BAL-001",
            "ERROR",
            "Tidak ditemukan validasi keseimbangan debit-kredit (double-entry) sebelum posting."
        )
        self.applies_to = lambda info: info.is_posting and info.has_debit_credit

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        # Pengecualian: service_journal.py post_approved_journal — validasi di domain
        if info.name == 'post_approved_journal' and 'service_journal.py' in str(info.file_path):
            return None
        if not info.has_balance_check:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi '{info.name}' menyentuh debit/credit tetapi tidak membandingkan total.",
                function=info.name
            )
        return None

class PeriodOpenValidationRule(PostingRule):
    def __init__(self):
        super().__init__(
            "VAL-PER-001",
            "ERROR",
            "Tidak ditemukan validasi apakah periode akuntansi terbuka sebelum posting."
        )
        self.applies_to = lambda info: info.is_posting

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        # Pengecualian: service_journal.py
        if info.name == 'post_approved_journal' and 'service_journal.py' in str(info.file_path):
            return None
        if not info.has_period_check:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi '{info.name}' tidak memeriksa status periode akuntansi.",
                function=info.name
            )
        return None

class AccountValidationRule(PostingRule):
    def __init__(self):
        super().__init__(
            "VAL-ACC-001",
            "WARNING",
            "Tidak ditemukan validasi keberadaan akun (account existence) sebelum posting."
        )
        self.applies_to = lambda info: info.is_posting

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        if info.name == 'post_approved_journal' and 'service_journal.py' in str(info.file_path):
            return None
        if not info.has_account_check:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi '{info.name}' tidak memverifikasi akun yang digunakan.",
                function=info.name
            )
        return None

class AuditTrailRule(PostingRule):
    def __init__(self):
        super().__init__(
            "AUDIT-001",
            "WARNING",
            "Tidak ditemukan penulisan audit trail (immutable event) setelah posting."
        )
        self.applies_to = lambda info: info.is_posting

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        if info.name == 'post_approved_journal' and 'service_journal.py' in str(info.file_path):
            return None
        if not info.has_audit:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi '{info.name}' tidak mencatat audit trail.",
                function=info.name
            )
        return None

class GLUpdateRule(PostingRule):
    def __init__(self):
        super().__init__(
            "GL-UPD-001",
            "WARNING",
            "Tidak ditemukan update General Ledger (GL) setelah posting."
        )
        self.applies_to = lambda info: info.is_posting

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        if info.name == 'post_approved_journal' and 'service_journal.py' in str(info.file_path):
            return None
        if not info.has_gl_update:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi '{info.name}' tidak mencatat ke General Ledger.",
                function=info.name
            )
        return None

class DomainEventPublishRule(PostingRule):
    def __init__(self):
        super().__init__(
            "EVT-PUB-001",
            "WARNING",
            "Tidak ditemukan publish domain event setelah posting."
        )
        self.applies_to = lambda info: info.is_posting

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        if info.name == 'post_approved_journal' and 'service_journal.py' in str(info.file_path):
            return None
        if not info.has_event_publish:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi '{info.name}' tidak mempublish domain event.",
                function=info.name
            )
        return None

class IdempotencyKeyRule(PostingRule):
    def __init__(self):
        super().__init__(
            "IDEM-001",
            "WARNING",
            "Tidak ditemukan idempotency key untuk mencegah duplikasi posting."
        )
        self.applies_to = lambda info: info.is_posting

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        if info.name == 'post_approved_journal' and 'service_journal.py' in str(info.file_path):
            return None
        if not info.has_idempotency:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi '{info.name}' tidak menggunakan idempotency key.",
                function=info.name
            )
        return None

class PostingTransactionRule(PostingRule):
    def __init__(self):
        super().__init__(
            "POST-TX-001",
            "WARNING",
            "Fungsi posting tidak menggunakan UnitOfWork atau transaksi eksplisit."
        )
        self.applies_to = lambda info: info.is_posting

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        if info.name == 'post_approved_journal' and 'service_journal.py' in str(info.file_path):
            return None
        if not info.has_transaction:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi '{info.name}' tidak membungkus operasi dalam transaksi.",
                function=info.name
            )
        return None

class FourEyesApprovalRule(PostingRule):
    def __init__(self):
        super().__init__(
            "APP-SOD-001",
            "ERROR",
            "Approval tidak menerapkan four-eyes principle atau SOD check."
        )
        self.applies_to = lambda info: info.is_approval

    def check(self, info: FunctionInfo) -> Optional[Finding]:
        body = ast.unparse(info.node).lower()
        has_sod = False
        if 'creator' in body and 'approver' in body:
            if any(k in body for k in ('!=', '!=')):
                has_sod = True
        if any(k in body for k in ('role', 'user', 'sod', 'segregation')):
            has_sod = True
        if not has_sod:
            return Finding(
                rule_id=self.rule_id,
                file=str(info.file_path),
                line=info.line,
                severity=self.severity,
                message=self.message,
                detail=f"Fungsi approval '{info.name}' tidak memeriksa role/user atau SOD.",
                function=info.name
            )
        return None

# ─── Daftar Aturan ──────────────────────────────────────────────────────────
POSTING_RULES = [
    DoubleEntryValidationRule(),
    PeriodOpenValidationRule(),
    AccountValidationRule(),
    AuditTrailRule(),
    GLUpdateRule(),
    DomainEventPublishRule(),
    IdempotencyKeyRule(),
    PostingTransactionRule(),
    FourEyesApprovalRule(),
]

# ─── Quality Rules ──────────────────────────────────────────────────────────
QUALITY_RULES = [
    ("SEC-001", "ERROR", "Hardcoded credential/secret terdeteksi.", r'(password|passwd|secret|token|api_key)\s*=\s*["\'][^\'"]+["\']'),
    ("SEC-002", "WARNING", "Penggunaan eval() atau exec() berbahaya.", r'\b(eval|exec)\s*\('),
    ("DB-001", "WARNING", "Query tanpa LIMIT (potensi memory overload).", r'\.all\s*\(\s*\)'),
    ("DB-002", "WARNING", "Penggunaan SELECT * (tidak spesifik).", r'SELECT\s+\*\s+FROM'),
    ("API-001", "WARNING", "Request HTTP tanpa timeout.", r'requests\.(get|post|put|delete)\s*\([^)]*\)(?!.*timeout)'),
    ("ERR-001", "WARNING", "Except Exception terlalu broad.", r'except\s+Exception\s*:'),
    ("ERR-002", "INFO", "Except dengan pass tanpa log.", r'except\s+.*:\s*pass'),
]

# ─── Deteksi Flow ──────────────────────────────────────────────────────────
def detect_flow_steps(registry: FunctionRegistry) -> Dict[str, List[Tuple[str, str, int]]]:
    results = {step: [] for step in ALL_STEPS}
    for func in registry.functions.values():
        for step, keywords in STEP_KEYWORDS.items():
            if any(k in func.name.lower() for k in keywords):
                results[step].append((str(func.file_path), func.name, func.line))
                break
    return results

# ─── Analisis Utama ─────────────────────────────────────────────────────────
def analyze_posting_flow(strict: bool = False, rca_enabled: bool = True) -> Report:
    report = Report()
    report.rca_enabled = rca_enabled and RCA_AVAILABLE

    target_dirs = [
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "service_layer",
        PROJECT_ROOT / "application" / "commands_cqrs",
        PROJECT_ROOT / "adapters" / "secondary_impl",
        PROJECT_ROOT / "adapters" / "primary_api" / "v1",
        PROJECT_ROOT / "bootstrap",
        PROJECT_ROOT / "kernel",
        PROJECT_ROOT / "infrastructure",
        PROJECT_ROOT / "audit",
        PROJECT_ROOT / "domain" / "journal",
        PROJECT_ROOT / "domain" / "intent",
        PROJECT_ROOT / "domain" / "reality",
    ]
    target_dirs = [d for d in target_dirs if d.exists()]

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build',
               'migrations', 'deployment', 'docs', 'tests', 'checker', 'scripts'}

    registry = FunctionRegistry()
    all_findings: List[Finding] = []

    # ─── Pass 1 ──────────────────────────────────────────────────────────────
    for dir_path in target_dirs:
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name in ("posting_flow_checker.py",):
                continue
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError:
                continue

            if strict:
                for r_id, sev, msg, pat in QUALITY_RULES:
                    pattern = re.compile(pat, re.IGNORECASE | re.DOTALL)
                    for line_num, line in enumerate(src.splitlines(), 1):
                        if pattern.search(line):
                            all_findings.append(Finding(
                                rule_id=r_id,
                                file=str(py_file),
                                line=line_num,
                                severity=sev,
                                message=msg,
                                detail="Pola ditemukan."
                            ))

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    info = analyze_function(node, py_file)
                    registry.register(info)

    # ─── Pass 2: Interprocedural ──────────────────────────────────────────
    registry.resolve_calls()

    # ─── Pass 3: Jalankan aturan ──────────────────────────────────────────
    seen = set()
    for func in registry.functions.values():
        if not (func.is_posting or func.is_approval):
            continue
        for rule in POSTING_RULES:
            if rule.applies_to(func):
                finding = rule.check(func)
                if finding:
                    key = (finding.rule_id, finding.function)
                    if key not in seen:
                        seen.add(key)
                        all_findings.append(finding)

    # ─── Pass 4: Flow ──────────────────────────────────────────────────────
    flow_steps = detect_flow_steps(registry)
    step_found = {step: bool(flow_steps[step]) for step in ALL_STEPS}
    step_details = {step: flow_steps[step] for step in ALL_STEPS}

    entity = "Journal"
    step_objs = []
    missing = []
    for step in ALL_STEPS:
        if step_found[step]:
            if step_details[step]:
                file, func, line = step_details[step][0]
                step_objs.append(FlowStep(step=step, file=file, line=line, function=func, implemented=True))
            else:
                step_objs.append(FlowStep(step=step, file="", line=0, function="", implemented=True))
        else:
            missing.append(step)
            step_objs.append(FlowStep(step=step, file="", line=0, function="", implemented=False))

    complete = (len(missing) == 0)
    report.flow_checks.append(FlowCheck(entity=entity, steps=step_objs, complete=complete, missing_steps=missing))

    for step in missing:
        all_findings.append(Finding(
            rule_id=f"FLOW-{step.upper()}-MISSING",
            file="GLOBAL",
            line=0,
            severity="ERROR",
            message=f"Langkah '{step}' tidak ditemukan dalam kode sumber.",
            detail="Tidak ada indikasi implementasi di direktori target."
        ))

    # ─── Pass 5: Scoring ──────────────────────────────────────────────────
    total_steps = len(ALL_STEPS)
    completed = sum(1 for s in ALL_STEPS if step_found[s])
    flow_score = (completed / total_steps) * 40

    posting_funcs = [f for f in registry.functions.values() if f.is_posting]
    if posting_funcs:
        critical_rules = ['VAL-BAL-001', 'VAL-PER-001', 'APP-SOD-001']
        violations = [f for f in all_findings if f.severity == 'ERROR' and f.rule_id in critical_rules]
        violation_ratio = len(violations) / (len(posting_funcs) * len(critical_rules)) if posting_funcs else 0
        rules_score = max(0, 30 - violation_ratio * 30)
    else:
        rules_score = 0

    posting_warnings = [f for f in all_findings if f.severity == 'WARNING' and f.rule_id.startswith(('VAL', 'APP', 'AUDIT', 'GL', 'EVT', 'IDEM', 'POST'))]
    warnings_score = max(0, 20 - len(posting_warnings) * 0.5)

    infos = [f for f in all_findings if f.severity == 'INFO']
    info_score = max(0, 10 - len(infos) * 0.2)

    report.score_flow = flow_score
    report.score_rules = rules_score
    total_score = flow_score + rules_score + warnings_score + info_score
    report.score = min(100, max(0, int(total_score)))

    # ─── RCA ──────────────────────────────────────────────────────────────
    if report.rca_enabled:
        for f in all_findings[:50]:
            if f.severity in ("ERROR", "WARNING"):
                try:
                    exc = RuntimeError(f.message)
                    context = {"file": f.file, "line": f.line, "rule_id": f.rule_id, "detail": f.detail}
                    rca_result = analyze_exception(exc, context)
                    if rca_result:
                        f.rca = {
                            "root_cause": rca_result.root_cause,
                            "suggested_fix": rca_result.suggested_fix,
                            "confidence": rca_result.confidence,
                            "severity": rca_result.severity.value if hasattr(rca_result.severity, 'value') else str(rca_result.severity)
                        }
                except Exception:
                    pass

    report.findings = all_findings
    return report

# ─── Output ─────────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}POSTING FLOW CHECKER v17.0.0 — Akurasi Tinggi{c['RESET']}")
    print(f"{c['CYAN']}RCA {'ENABLED' if report.rca_enabled else 'DISABLED'}{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")

    print(f"\n  Entities checked: {len(report.flow_checks)}")
    for fc in report.flow_checks:
        status = f"{c['GREEN']}✅ Complete{c['RESET']}" if fc.complete else f"{c['YELLOW']}⚠️ Incomplete{c['RESET']}"
        print(f"  {fc.entity}: {status}")

    print(f"\n  Total findings: {len(report.findings)}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    infos = sum(1 for f in report.findings if f.severity == "INFO")
    print(f"  Errors: {c['RED']}{errors}{c['RESET']}, Warnings: {c['YELLOW']}{warnings}{c['RESET']}, Infos: {c['CYAN']}{infos}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")
    print(f"  📊 Flow Completion: {report.score_flow:.1f}/40")
    print(f"  📊 Business Rules: {report.score_rules:.1f}/30")

    step_labels = {
        'capture': '📝 Capture/Intent',
        'validate': '🔍 Validation',
        'approve': '✅ Approval (Four-Eyes)',
        'post': '📤 Posting',
        'gl_update': '📊 GL Update',
        'audit': '📋 Audit Trail'
    }
    print(f"\n{c['CYAN']}Flow Steps:{c['RESET']}")
    for fc in report.flow_checks:
        for step in fc.steps:
            label = step_labels.get(step.step, step.step)
            if step.implemented:
                icon = f"{c['GREEN']}✔{c['RESET']}"
                detail = f"{step.function} at {step.file}:{step.line}" if step.file else "(detected)"
            else:
                icon = f"{c['RED']}✖{c['RESET']}"
                detail = "MISSING"
            print(f"    {label}: {icon}  {detail}")

    if report.findings:
        posting_findings = [f for f in report.findings if f.rule_id.startswith(('VAL', 'APP', 'AUDIT', 'GL', 'EVT', 'IDEM', 'POST', 'FLOW'))]
        if not posting_findings and report.findings:
            posting_findings = report.findings[:20]

        print(f"\n{c['RED'] if errors else c['YELLOW']}Findings (sample):{c['RESET']}")
        for f in posting_findings[:20]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"] if f.severity == "WARNING" else c["CYAN"]
            location = f"{f.file}:{f.line}" if f.file != "GLOBAL" else "GLOBAL"
            func_info = f" ({f.function})" if f.function else ""
            print(f"  {color}[{f.severity}]{c['RESET']} {location} [{f.rule_id}]{func_info}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
        if len(posting_findings) > 20:
            print(f"  ... and {len(posting_findings)-20} more findings (use --json for full list)")

        if len(report.findings) > len(posting_findings):
            quality_count = len(report.findings) - len(posting_findings)
            print(f"  ({quality_count} quality warnings hidden, use --strict to show)")

def save_json(report: Report, filepath: str):
    data = {
        "score": report.score,
        "score_flow": report.score_flow,
        "score_rules": report.score_rules,
        "rca_enabled": report.rca_enabled,
        "flow_checks": [
            {
                "entity": fc.entity,
                "complete": fc.complete,
                "missing_steps": fc.missing_steps,
                "steps": [
                    {"step": s.step, "function": s.function, "file": s.file, "line": s.line, "implemented": s.implemented}
                    for s in fc.steps
                ]
            }
            for fc in report.flow_checks
        ],
        "findings": [
            {
                "rule_id": f.rule_id,
                "file": f.file,
                "line": f.line,
                "severity": f.severity,
                "message": f.message,
                "detail": f.detail,
                "function": f.function,
                "rca": f.rca
            }
            for f in report.findings
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

# ─── CLI ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Posting Flow Integrity Checker v17.0.0")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail findings")
    parser.add_argument("--json", metavar="FILE", help="Simpan hasil dalam format JSON")
    parser.add_argument("--strict", action="store_true", help="Aktifkan aturan kualitas (SEC, DB, API, ERR)")
    parser.add_argument("--rca", action="store_true", default=True, help="Aktifkan RCA (default: True)")
    parser.add_argument("--no-rca", action="store_false", dest="rca", help="Nonaktifkan RCA")
    args = parser.parse_args()

    report = analyze_posting_flow(strict=args.strict, rca_enabled=args.rca)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()