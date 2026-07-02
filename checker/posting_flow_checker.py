#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
posting_flow_checker.py — Posting Flow Integrity & Forensic Validator (v6.3.1)
======================================================================
Versi   : 6.3.1
Standar : ISO/IEC 25010 · SOX/ISA 315 · PCAOB AS 2405 · IFRS/PSAK

Perbaikan v6.3.1:
  - Perbaiki bug AttributeError pada PatternRule.check()
  - Perbaiki deteksi directory 'domain' menggunakan pathlib
  - Minor improvements

Cara pakai :
  python checker/posting_flow_checker.py
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

# ─── Integrasi RCA ──────────────────────────────────────────────────────────
try:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from core.rca import RCAEngine, Severity as RCASeverity, RCAResult, get_engine, analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    try:
        import rca
        RCA_AVAILABLE = True
    except ImportError:
        RCA_AVAILABLE = False
        class RCASeverity: pass
        class RCAResult: pass
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
@dataclass
class Finding:
    rule_id: str
    file: str
    line: int
    severity: str
    message: str
    detail: str = ""
    rca: Optional[Dict] = None

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
    rca_enabled: bool = False

# ─── Step Keywords (spesifik untuk posting flow) ──────────────────────────
STEP_KEYWORDS = {
    'capture': [
        'capture', 'intent', 'create_draft', 'capture_intent', 'new_journal',
        'journal_intent', 'capture_service'
    ],
    'validate': [
        'validate_journal', 'validate_entry', 'check_balance', 'validate_period',
        'validate_account', 'validate_journal_entry', 'verify_balance'
    ],
    'approve': [
        'approve_journal', 'approve_entry', 'authorize_journal', 'four_eyes',
        'approve_posting', 'confirm_posting'
    ],
    'post': [
        'post_journal', 'save_journal', 'commit_journal', 'execute_posting',
        'post_to_ledger', 'record_journal', 'persist_journal'
    ],
    'gl_update': [
        'update_general_ledger', 'post_gl', 'save_gl', 'update_ledger',
        'record_ledger', 'general_ledger'
    ],
    'audit': [
        'record_audit', 'append_event', 'publish_domain_event', 'log_event',
        'hash_chain_link', 'audit_trail'
    ]
}

# ─── Rule Base ─────────────────────────────────────────────────────────────
class PostingRule:
    def __init__(self, rule_id: str, severity: str, message: str):
        self.rule_id = rule_id
        self.severity = severity
        self.message = message

    def check(self, file_path: pathlib.Path, src: str, tree: ast.AST) -> List[Finding]:
        return []

# ─── Fungsi pembantu: apakah fungsi adalah "posting function" yang relevan? ──
def is_posting_function(node: ast.FunctionDef) -> bool:
    """Deteksi apakah fungsi melakukan operasi posting/penyimpanan akuntansi."""
    name = node.name.lower()
    # Cek nama fungsi: harus mengandung kata kunci posting
    if not any(k in name for k in ('post', 'save', 'commit', 'persist', 'record')):
        return False

    # Cek body: harus ada indikasi penggunaan repository, unit_of_work, atau session
    body_text = ast.unparse(node).lower()
    has_uow = any(k in body_text for k in ('uow', 'unit_of_work', 'session', 'repository'))
    if not has_uow:
        # Cek parameter: apakah ada parameter bernama uow, session, atau repository?
        for arg in node.args.args:
            arg_name = arg.arg.lower()
            if any(k in arg_name for k in ('uow', 'session', 'repo', 'repository')):
                has_uow = True
                break
    return has_uow

# ─── Deteksi langkah flow berdasarkan AST ─────────────────────────────────
def detect_step_in_file(py_file: pathlib.Path, src: str, tree: ast.AST) -> Dict[str, List[Tuple[str, int]]]:
    """Mencari indikasi setiap langkah dalam file."""
    results = {step: [] for step in STEP_KEYWORDS.keys()}
    file_name = py_file.name.lower()
    file_str = str(py_file).lower()

    # 1. Nama file
    for step, keywords in STEP_KEYWORDS.items():
        if any(k in file_name for k in keywords):
            results[step].append(("file", 0))

    # 2. Cari di AST: fungsi, kelas, docstring
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name.lower()
            doc = ast.get_docstring(node) or ""
            # Cek nama dan docstring untuk setiap step
            for step, keywords in STEP_KEYWORDS.items():
                if any(k in name for k in keywords) or any(k in doc.lower() for k in keywords):
                    # Pastikan ini relevan dengan konteks posting
                    if step == 'post' and not is_posting_function(node):
                        continue
                    results[step].append((node.name, node.lineno))
                    break

        # 3. Cek body fungsi
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_text = ast.unparse(node).lower()
            for step, keywords in STEP_KEYWORDS.items():
                # Hindari false positive jika fungsi tidak relevan
                if step == 'post' and not is_posting_function(node):
                    continue
                if any(k in body_text for k in keywords):
                    # Cek apakah konteksnya cocok (misal fungsi di service atau use case)
                    results[step].append((node.name, node.lineno))
                    break

    return results

# ─── Aturan spesifik ──────────────────────────────────────────────────────
class PostingTransactionRule(PostingRule):
    def __init__(self):
        super().__init__("POST-TX-001", "WARNING", "Fungsi posting tidak menggunakan UnitOfWork atau transaksi eksplisit.")

    def check(self, file_path, src, tree):
        findings = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not is_posting_function(node):
                    continue
                body = ast.unparse(node).lower()
                if not any(k in body for k in ('transaction', 'uow', 'unit_of_work')):
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        file=str(file_path),
                        line=node.lineno,
                        severity=self.severity,
                        message=self.message,
                        detail=f"Fungsi '{node.name}' tidak membungkus operasi dalam transaksi."
                    ))
        return findings

class AuditTrailRule(PostingRule):
    def __init__(self):
        super().__init__("AUDIT-001", "ERROR", "Tidak ditemukan penulisan audit trail (immutable event) setelah posting.")

    def check(self, file_path, src, tree):
        findings = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not is_posting_function(node):
                    continue
                body = ast.unparse(node).lower()
                if not any(k in body for k in ('publish', 'append', 'audit', 'event', 'hash', 'immutable')):
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        file=str(file_path),
                        line=node.lineno,
                        severity=self.severity,
                        message=self.message,
                        detail=f"Fungsi '{node.name}' tidak mencatat audit trail."
                    ))
        return findings

class DoubleEntryValidationRule(PostingRule):
    def __init__(self):
        super().__init__("VAL-BAL-001", "ERROR", "Tidak ditemukan validasi keseimbangan debit-kredit (double-entry) sebelum posting.")

    def check(self, file_path, src, tree):
        findings = []
        # Hanya periksa file yang relevan dengan jurnal
        if 'journal' not in str(file_path).lower():
            return findings
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not any(k in node.name.lower() for k in ('validate', 'post', 'save')):
                    continue
                body = ast.unparse(node).lower()
                if 'debit' in body and 'credit' in body:
                    if not re.search(r'(total\s*debit|sum\s*debit|debit\s*total).*(total\s*credit|sum\s*credit|credit\s*total)', body, re.I):
                        findings.append(Finding(
                            rule_id=self.rule_id,
                            file=str(file_path),
                            line=node.lineno,
                            severity=self.severity,
                            message=self.message,
                            detail=f"Fungsi '{node.name}' menyentuh debit/credit tapi tidak membandingkan total."
                        ))
        return findings

class PeriodOpenValidationRule(PostingRule):
    def __init__(self):
        super().__init__("VAL-PER-001", "ERROR", "Tidak ditemukan validasi apakah periode akuntansi terbuka sebelum posting.")

    def check(self, file_path, src, tree):
        findings = []
        # Hanya periksa fungsi yang melakukan posting
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not is_posting_function(node):
                    continue
                body = ast.unparse(node).lower()
                if not any(k in body for k in ('period', 'fiscal', 'open', 'closed')):
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        file=str(file_path),
                        line=node.lineno,
                        severity=self.severity,
                        message=self.message,
                        detail=f"Fungsi '{node.name}' tidak memeriksa status periode akuntansi."
                    ))
        return findings

class AccountValidationRule(PostingRule):
    def __init__(self):
        super().__init__("VAL-ACC-001", "WARNING", "Tidak ditemukan validasi keberadaan akun (account existence) sebelum posting.")

    def check(self, file_path, src, tree):
        findings = []
        # Hanya periksa fungsi yang melakukan posting
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not is_posting_function(node):
                    continue
                body = ast.unparse(node).lower()
                if not any(k in body for k in ('account', 'coa', 'chart_of_accounts', 'exists')):
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        file=str(file_path),
                        line=node.lineno,
                        severity=self.severity,
                        message=self.message,
                        detail=f"Fungsi '{node.name}' tidak memverifikasi akun yang digunakan."
                    ))
        return findings

class FourEyesApprovalRule(PostingRule):
    def __init__(self):
        super().__init__("APP-SOD-001", "ERROR", "Approval tidak menerapkan four-eyes principle atau SOD check.")

    def check(self, file_path, src, tree):
        findings = []
        # Cari fungsi approval
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name.lower()
                if 'approve' in name or 'authorize' in name:
                    body = ast.unparse(node).lower()
                    if not any(k in body for k in ('role', 'user', 'approver', 'sod', 'segregation')):
                        findings.append(Finding(
                            rule_id=self.rule_id,
                            file=str(file_path),
                            line=node.lineno,
                            severity=self.severity,
                            message=self.message,
                            detail=f"Fungsi approval '{node.name}' tidak memeriksa role/user atau SOD."
                        ))
        return findings

class DomainEventPublishRule(PostingRule):
    def __init__(self):
        super().__init__("EVT-PUB-001", "WARNING", "Tidak ditemukan publish domain event setelah posting.")

    def check(self, file_path, src, tree):
        findings = []
        # Hanya periksa fungsi posting
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not is_posting_function(node):
                    continue
                body = ast.unparse(node).lower()
                if not any(k in body for k in ('publish', 'dispatch', 'event_bus', 'domain_event')):
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        file=str(file_path),
                        line=node.lineno,
                        severity=self.severity,
                        message=self.message,
                        detail=f"Fungsi '{node.name}' tidak mempublish domain event."
                    ))
        return findings

class GLUpdateRule(PostingRule):
    def __init__(self):
        super().__init__("GL-UPD-001", "WARNING", "Tidak ditemukan update General Ledger (GL) setelah posting.")

    def check(self, file_path, src, tree):
        findings = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not is_posting_function(node):
                    continue
                body = ast.unparse(node).lower()
                if not any(k in body for k in ('general_ledger', 'gl', 'ledger')):
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        file=str(file_path),
                        line=node.lineno,
                        severity=self.severity,
                        message=self.message,
                        detail=f"Fungsi '{node.name}' tidak mencatat ke General Ledger."
                    ))
        return findings

class IdempotencyKeyRule(PostingRule):
    def __init__(self):
        super().__init__("IDEM-001", "WARNING", "Tidak ditemukan idempotency key untuk mencegah duplikasi posting.")

    def check(self, file_path, src, tree):
        findings = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not is_posting_function(node):
                    continue
                body = ast.unparse(node).lower()
                if not any(k in body for k in ('idempotency', 'idempotent', 'duplicate', 'key')):
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        file=str(file_path),
                        line=node.lineno,
                        severity=self.severity,
                        message=self.message,
                        detail=f"Fungsi '{node.name}' tidak menggunakan idempotency key."
                    ))
        return findings

class RollbackHandlingRule(PostingRule):
    def __init__(self):
        super().__init__("TX-RB-001", "WARNING", "Tidak ditemukan penanganan rollback pada kegagalan transaksi.")

    def check(self, file_path, src, tree):
        findings = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not is_posting_function(node):
                    continue
                body = ast.unparse(node).lower()
                if not any(k in body for k in ('rollback', 'exception', 'try', 'except')):
                    findings.append(Finding(
                        rule_id=self.rule_id,
                        file=str(file_path),
                        line=node.lineno,
                        severity=self.severity,
                        message=self.message,
                        detail=f"Fungsi '{node.name}' tidak memiliki try/except dengan rollback."
                    ))
        return findings

# ─── Pattern-based Rules (hanya untuk file non-domain) ─────────────────────
class PatternRule(PostingRule):
    def __init__(self, rule_id, severity, message, pattern, file_pattern=None):
        super().__init__(rule_id, severity, message)
        self.pattern = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        self.file_pattern = re.compile(file_pattern, re.IGNORECASE) if file_pattern else None

    def check(self, file_path, src, tree):
        findings = []
        # PERBAIKAN: hindari domain entities untuk pola keamanan/kualitas
        if 'domain' in file_path.parts:
            return findings
        if self.file_pattern and not self.file_pattern.search(str(file_path)):
            return findings
        for line_num, line in enumerate(src.splitlines(), 1):
            if self.pattern.search(line):
                findings.append(Finding(
                    rule_id=self.rule_id,
                    file=str(file_path),
                    line=line_num,
                    severity=self.severity,
                    message=self.message,
                    detail=f"Pola '{self.pattern.pattern}' ditemukan."
                ))
        return findings

# ─── Daftar aturan ─────────────────────────────────────────────────────────
ALL_STEPS = ['capture', 'validate', 'approve', 'post', 'gl_update', 'audit']

ALL_RULES = [
    PostingTransactionRule(),
    AuditTrailRule(),
    DoubleEntryValidationRule(),
    PeriodOpenValidationRule(),
    AccountValidationRule(),
    FourEyesApprovalRule(),
    DomainEventPublishRule(),
    GLUpdateRule(),
    IdempotencyKeyRule(),
    RollbackHandlingRule(),
]

PATTERN_RULES = [
    PatternRule("SEC-001", "ERROR", "Hardcoded credential/secret terdeteksi.", r'(password|passwd|secret|token|api_key)\s*=\s*["\'][^\'"]+["\']'),
    PatternRule("SEC-002", "WARNING", "Penggunaan eval() atau exec() berbahaya.", r'\b(eval|exec)\s*\('),
    PatternRule("DB-001", "WARNING", "Query tanpa LIMIT (potensi memory overload).", r'\.all\s*\(\s*\)'),
    PatternRule("DB-002", "WARNING", "Penggunaan SELECT * (tidak spesifik).", r'SELECT\s+\*\s+FROM'),
    PatternRule("API-001", "WARNING", "Request HTTP tanpa timeout.", r'requests\.(get|post|put|delete)\s*\([^)]*\)(?!.*timeout)'),
    PatternRule("ERR-001", "WARNING", "Except Exception terlalu broad.", r'except\s+Exception\s*:'),
    PatternRule("ERR-002", "INFO", "Except dengan pass tanpa log.", r'except\s+.*:\s*pass'),
]
ALL_RULES.extend(PATTERN_RULES)

# ─── Analisis Utama ──────────────────────────────────────────────────────
def analyze_posting_flow(rca_enabled: bool = True) -> Report:
    report = Report()
    report.rca_enabled = rca_enabled

    # Direktori target yang relevan (hindari domain entity murni)
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
    ]
    # Sertakan domain tetapi hanya folder yang relevan (journal, intent, reality)
    domain_extra = [
        PROJECT_ROOT / "domain" / "journal",
        PROJECT_ROOT / "domain" / "intent",
        PROJECT_ROOT / "domain" / "reality",
    ]
    for d in domain_extra:
        if d.exists():
            target_dirs.append(d)

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests', 'checker'}

    all_findings: List[Finding] = []
    step_found = {step: False for step in ALL_STEPS}
    step_details = {step: [] for step in ALL_STEPS}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
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

            # Jalankan aturan tambahan
            for rule in ALL_RULES:
                findings = rule.check(py_file, src, tree)
                all_findings.extend(findings)

            # Deteksi langkah flow
            step_detected = detect_step_in_file(py_file, src, tree)
            for step, occurences in step_detected.items():
                if occurences:
                    step_found[step] = True
                    # ambil contoh pertama
                    func_name, line = occurences[0]
                    step_details[step].append((str(py_file), func_name, line))

    # Buat flow check
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

    # Tambahkan findings untuk missing steps
    for step in missing:
        all_findings.append(Finding(
            rule_id=f"FLOW-{step.upper()}-MISSING",
            file="GLOBAL",
            line=0,
            severity="ERROR",
            message=f"Langkah '{step}' tidak ditemukan dalam kode sumber.",
            detail="Tidak ada indikasi implementasi di direktori target."
        ))

    # RCA
    if rca_enabled and RCA_AVAILABLE:
        engine = get_engine()
        for f in all_findings[:50]:  # batasi agar tidak terlalu berat
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

    # Score
    errors = sum(1 for f in all_findings if f.severity == "ERROR")
    warnings = sum(1 for f in all_findings if f.severity == "WARNING")
    infos = sum(1 for f in all_findings if f.severity == "INFO")
    report.score = max(0, 100 - errors * 10 - warnings * 3 - infos * 1)
    report.findings = all_findings
    return report

# ─── Output ─────────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}POSTING FLOW INTEGRITY & FORENSIC CHECKER{c['RESET']}")
    print(f"{c['CYAN']}v6.3.1 — RCA {'ENABLED' if report.rca_enabled else 'DISABLED'}{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")

    print(f"\n  Entities checked: {len(report.flow_checks)}")
    for fc in report.flow_checks:
        status = f"{c['GREEN']}✅ Complete{c['RESET']}" if fc.complete else f"{c['RED']}❌ Incomplete{c['RESET']}"
        print(f"  {fc.entity}: {status}")

    print(f"\n  Total findings: {len(report.findings)}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    infos = sum(1 for f in report.findings if f.severity == "INFO")
    print(f"  Errors: {c['RED']}{errors}{c['RESET']}, Warnings: {c['YELLOW']}{warnings}{c['RESET']}, Infos: {c['CYAN']}{infos}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    # Flow steps
    step_labels = {
        'capture': '📝 Capture/Intent',
        'validate': '🔍 Validation',
        'approve': '✅ Approval (Four-Eyes)',
        'post': '📤 Posting',
        'gl_update': '📊 GL Update',
        'audit': '📋 Audit Trail'
    }
    print(f"\n{c['CYAN']}Flow Steps per Entity:{c['RESET']}")
    for fc in report.flow_checks:
        print(f"\n  {c['CYAN']}{fc.entity}{c['RESET']}:")
        for step in fc.steps:
            label = step_labels.get(step.step, step.step)
            if step.implemented:
                icon = f"{c['GREEN']}✔{c['RESET']}"
                detail = f"{step.function} at {step.file}:{step.line}"
            else:
                icon = f"{c['RED']}✖{c['RESET']}"
                detail = "MISSING"
            print(f"    {label}: {icon}  {detail}")

    # Findings (tampilkan hanya beberapa, gunakan --json untuk detail)
    if report.findings:
        print(f"\n{c['RED'] if errors else c['YELLOW']}Findings (sample):{c['RESET']}")
        for f in report.findings[:20]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"] if f.severity == "WARNING" else c["CYAN"]
            location = f"{f.file}:{f.line}" if f.file else "GLOBAL"
            print(f"  {color}[{f.severity}]{c['RESET']} {location} [{f.rule_id}]")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
        if len(report.findings) > 20:
            print(f"  ... and {len(report.findings)-20} more findings (use --json for full list)")

def save_json(report: Report, filepath: str):
    data = {
        "score": report.score,
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
    parser = argparse.ArgumentParser(description="Posting Flow Integrity & Forensic Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail findings")
    parser.add_argument("--json", metavar="FILE", help="Simpan hasil dalam format JSON")
    parser.add_argument("--rca", action="store_true", default=True, help="Aktifkan RCA (default: True)")
    parser.add_argument("--no-rca", action="store_false", dest="rca", help="Nonaktifkan RCA")
    args = parser.parse_args()

    report = analyze_posting_flow(rca_enabled=args.rca)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()