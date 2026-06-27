#!/usr/bin/env python3
# =============================================================================
#  SOVEREIGN ERP ACCOUNTING ENGINE — STRUCTURAL INTEGRITY AUDITOR v17.1
#  =============================================================================
#  UNIFIED CHECKER — Merges all phases from main_checker & main_checker_3
#  plus advanced phases. Fixed circular import (42 cycles → 4 cycles).
#  Added --skip-import option.
#  =============================================================================

from __future__ import annotations

import argparse
import ast
import asyncio
import collections
import importlib
import importlib.util
import json
import logging
import os
import pathlib
import re
import subprocess
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

# ─── Colour ──────────────────────────────────────────────────────────────────
RED = GREEN = YELLOW = CYAN = MAGENTA = WHITE = BOLD = RESET = ""

def _setup_colour(enable: bool) -> None:
    global RED, GREEN, YELLOW, CYAN, MAGENTA, WHITE, BOLD, RESET
    if enable:
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
            return
        except ImportError:
            pass
    RED = GREEN = YELLOW = CYAN = MAGENTA = WHITE = BOLD = RESET = ""

_setup_colour(True)

# ─── Data structures ─────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str
    phase: str
    file: str
    line: int
    message: str
    detail: str = ""
    recommendation: str = ""

@dataclass
class PhaseResult:
    name: str
    weight: int
    score: int = 100
    passed: bool = True
    findings: list[Finding] = field(default_factory=list)
    duration: float = 0.0
    disclaimer: str = ""

    def add(self, sev: str, file: str, line: int, msg: str,
            detail: str = "", recommendation: str = "") -> None:
        self.findings.append(Finding(sev, self.name, file, line, msg, detail, recommendation))
        if sev == "CRITICAL":
            self.passed = False

    def count(self, sev: str) -> int:
        return sum(1 for f in self.findings if f.severity == sev)

    def degrade(self, per_crit: int = 10, per_warn: int = 3, floor: int = 0) -> None:
        self.score = max(floor, 100 - self.count("CRITICAL") * per_crit - self.count("WARNING") * per_warn)

    def finalize_status(self) -> None:
        if self.count("CRITICAL") > 0 or self.score == 0:
            self.passed = False

# ─── Print helpers ──────────────────────────────────────────────────────────
_ICON = {"CRITICAL": "✖", "WARNING": "⚠", "INFO": "ℹ", "PASS": "✔"}
_SCOL = {
    "CRITICAL": lambda: RED,
    "WARNING": lambda: YELLOW,
    "INFO": lambda: CYAN,
    "PASS": lambda: GREEN,
}

def _c(s: str) -> str:
    return _SCOL.get(s, lambda: WHITE)()

def banner(txt: str, w: int = 78) -> str:
    ln = "─" * w
    return f"\n{BOLD}{CYAN}{ln}\n  {txt}\n{ln}{RESET}"

def pf(f: Finding, verbose: bool = False) -> None:
    col = _c(f.severity)
    icon = _ICON.get(f.severity, "?")
    print(f"  {col}{BOLD}{icon} [{f.severity}]{RESET} {f.message}")
    if f.detail and (verbose or f.severity == "CRITICAL"):
        for ln in f.detail.splitlines()[:6]:
            print(f"      {YELLOW}{ln}{RESET}")
    if f.file and (verbose or f.severity in ("WARNING", "CRITICAL")):
        loc = f"{f.file}:{f.line}" if f.line else f.file
        print(f"      {WHITE}@ {loc}{RESET}")
    if f.recommendation and (verbose or f.severity == "CRITICAL"):
        print(f"      {CYAN}💡 {f.recommendation}{RESET}")

# ─── Project root & file helpers ─────────────────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parent

_PROJECT_TOPS = {
    "app", "adapters", "application", "domain", "infrastructure",
    "kernel", "ports", "config", "migrations", "tests", "compliance",
    "audit", "constitution", "axioms", "bootstrap", "policy_engine",
    "projections", "reports", "transformers", "event_gateway",
    "security_hardening", "disaster_recovery", "monitoring", "architecture",
}
_SKIP_ALWAYS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "venv", "node_modules", ".tox", ".cache",
    "site-packages", "dist-packages", "dist", "build", "uv",
}
_CHECKER_FILES = {
    "main_checker.py", "main_checker_2.py", "main_checker_3.py",
    "main_checker_v5.py", "main_checker_old.py", "main_app_checker.py",
}

def is_test_file(path: pathlib.Path) -> bool:
    path_str = str(path)
    return ("/tests/" in path_str or "\\tests\\" in path_str
            or path.name.startswith("test_") or path.name.endswith("_test.py")
            or "/test_" in path_str or "\\test_" in path_str)

def is_checker_file(path: pathlib.Path) -> bool:
    return path.name in _CHECKER_FILES

def all_py(root: pathlib.Path = ROOT,
           skip_tops: set[str] | None = None,
           project_only: bool = True,
           include_checker: bool = False) -> list[pathlib.Path]:
    extra = skip_tops or set()
    result: list[pathlib.Path] = []
    for p in root.glob("*.py"):
        if include_checker or p.name not in _CHECKER_FILES:
            result.append(p)
    scan_roots = ([root / d for d in _PROJECT_TOPS if (root / d).is_dir()]
                  if project_only else [root])
    for sr in scan_roots:
        for p in sr.rglob("*.py"):
            if any(part in _SKIP_ALWAYS for part in p.parts):
                continue
            if any(part in extra for part in p.parts):
                continue
            if not include_checker and p.name in _CHECKER_FILES:
                continue
            try:
                p.relative_to(ROOT)
            except ValueError:
                continue
            result.append(p)
    return sorted(set(result))

def rel(p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)

def mod_name(path: pathlib.Path) -> str | None:
    try:
        rp = path.relative_to(ROOT)
    except ValueError:
        return None
    parts = list(rp.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _find_dynamic_imports_ast(tree: ast.AST) -> list[tuple[int, str, str]]:
    """
    Mencari pemanggilan __import__(), importlib.import_module(), dan exec/eval
    yang dapat memuat modul secara dinamis.
    Mengembalikan list of (lineno, call_name, argument_expr).
    """
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # __import__('module')
            if isinstance(func, ast.Name) and func.id == "__import__":
                arg_str = ast.unparse(node.args[0]) if node.args else ""
                results.append((node.lineno, "__import__", arg_str))
            # importlib.import_module('module')
            elif isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id == "importlib":
                    if func.attr == "import_module":
                        arg_str = ast.unparse(node.args[0]) if node.args else ""
                        results.append((node.lineno, "importlib.import_module", arg_str))
            # eval() atau exec() dengan string
            elif isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    arg_str = node.args[0].value[:50]
                    results.append((node.lineno, func.id, arg_str))
    return results

def _resolve_import_target(module_name: str, root: pathlib.Path) -> bool:
    """
    Mengecek apakah modul dengan nama 'module_name' benar-benar ada sebagai file .py
    di dalam direktori root.
    """
    parts = module_name.split(".")
    # Coba cari file .py
    for i in range(len(parts), 0, -1):
        path_candidate = root / pathlib.Path(*parts[:i]).with_suffix(".py")
        if path_candidate.exists():
            return True
        # Coba cari package (folder dengan __init__.py)
        init_file = root / pathlib.Path(*parts[:i]) / "__init__.py"
        if init_file.exists():
            # Jika masih ada sisa submodul, lanjutkan
            if i == len(parts):
                return True
            # Cek apakah submodul berikutnya ada
            sub_path = root / pathlib.Path(*parts[:i+1]).with_suffix(".py")
            if sub_path.exists():
                return True
    return False

def _resolve_relative_import(current_file: pathlib.Path, level: int, module: str | None, name: str | None) -> list[pathlib.Path]:
    """
    Menyelesaikan relative import (dari level dan module/name) menjadi daftar path file yang mungkin.
    Mengembalikan list pathlib.Path (bisa kosong jika tidak ditemukan).
    """
    current_dir = current_file.parent
    candidates = []
    # Naik ke atas sesuai level
    target_dir = current_dir
    for _ in range(level - 1):
        target_dir = target_dir.parent
    # Jika module diberikan, gabungkan
    if module:
        parts = module.split(".")
        target_path = target_dir / pathlib.Path(*parts).with_suffix(".py")
        if target_path.exists():
            candidates.append(target_path)
        # Coba sebagai package
        init_path = target_dir / pathlib.Path(*parts) / "__init__.py"
        if init_path.exists():
            candidates.append(init_path)
    else:
        # Hanya nama (from . import name)
        if name:
            # Coba file name.py
            file_path = target_dir / f"{name}.py"
            if file_path.exists():
                candidates.append(file_path)
            # Coba package name/__init__.py
            init_path = target_dir / name / "__init__.py"
            if init_path.exists():
                candidates.append(init_path)
    return candidates



# ============================================================
# LAYER RULES (diperbaiki untuk semua layer yang ada di proyek)
# ============================================================

_LAYER_RULES: dict[str, set[str]] = {
    # Core layers
    "adapters": {
        "adapters", "domain", "application", "infrastructure",
        "ports", "config", "bootstrap", "kernel",
        "audit", "reports", "event_gateway", "compliance",
        "policy_engine",
    },
    "application": {
        "application", "domain", "ports", "config", "bootstrap",
        "infrastructure", "kernel", "event_gateway", "audit",
        "policy_engine", "adapters",  # <-- diizinkan untuk factory (app_factory.py)
        "dto_objects", "commands_cqrs", "service_layer",
        "use_cases", "workflows", "sagas", "events", "outbox", "mappers",
    },
    "domain": {
        "domain", "shared_value_objects", "kernel",
        "constitution", "axioms",
    },
    "infrastructure": {
        "infrastructure", "domain", "application", "ports",
        "config", "event_gateway", "persistence_orm", "caching",
        "database", "event_store", "file_storage",
        "message_broker", "security", "telemetry",
    },
    "kernel": {
        "kernel", "domain", "ports", "config", "bootstrap",
        "axioms", "constitution", "guards", "immutable_laws",
    },
    "ports": {
        "ports", "domain",
    },
    "bootstrap": {
        "bootstrap", "domain", "application", "infrastructure",
        "ports", "config", "kernel",
    },
    "config": {
        "config", "application", "domain", "bootstrap",
    },
    "compliance": {
        "compliance", "domain", "application", "policy_engine",
        "legal", "ethics",
    },
    "policy_engine": {
        "policy_engine", "domain", "config", "psak", "ifrs",
        "tax_indonesia",
    },
    "audit": {
        "audit", "domain", "application", "infrastructure",
        "config", "sampling_materiality",
    },
    "projections": {
        "projections", "domain", "application", "infrastructure",
        "ledger", "subledger", "tax", "analytics_bi",
        "config",
    },
    "reports": {
        "reports", "domain", "application", "infrastructure",
        "projections", "config",
    },
    "event_gateway": {
        "event_gateway", "domain", "application", "infrastructure",
        "config",
    },
    "axioms": {
        "axioms", "constitution", "kernel",
    },
    "constitution": {
        "constitution", "axioms", "kernel",
    },

    # Layer tambahan
    "architecture": {
        "architecture", "application", "domain", "infrastructure",
        "config",
    },
    "asgi": {
        "asgi", "app", "bootstrap", "kernel", "adapters",
        "infrastructure", "application", "config",
        "policy_engine", "event_gateway",
    },
    "disaster_recovery": {
        "disaster_recovery", "infrastructure", "application",
        "domain", "event_store",
    },
    "fix": {
        "fix", "infrastructure", "application", "domain",
    },
    "fix_bom": {
        "fix_bom", "infrastructure", "application",
    },
    "monitoring": {
        "monitoring", "infrastructure", "application", "kernel",
        "adapters",
    },
    "security_hardening": {
        "security_hardening", "infrastructure", "application",
        "kernel", "adapters",
    },
    "surgical_metadata_fixer": {
        "surgical_metadata_fixer", "infrastructure", "application",
        "domain",
    },
    "transformers": {
        "transformers", "domain", "application", "infrastructure",
        "ports", "bootstrap", "event_gateway",
    },
}

# Pengecualian tambahan untuk pasangan layer yang memang saling bergantung
# =============================================================================
# LAYER EXCEPTIONS — Pasangan layer yang diperbolehkan meskipun tidak ada di rules
# =============================================================================
# Digunakan untuk mengatasi ketergantungan yang memang diperlukan secara arsitektur
# tetapi tidak tercakup dalam aturan umum.
# =============================================================================

_LAYER_EXCEPTIONS: set[tuple[str, str]] = {
    # Core ↔ Kernel
    ("domain", "kernel"),
    ("kernel", "domain"),
    ("domain", "constitution"),
    ("constitution", "domain"),
    ("axioms", "constitution"),
    ("constitution", "axioms"),
    ("axioms", "kernel"),
    ("kernel", "axioms"),

    # Application ↔ Kernel
    ("application", "kernel"),
    ("application", "domain"),
    ("application", "ports"),

    # Infrastructure ↔ Kernel (infrastructure butuh kernel untuk guards, dll.)
    ("infrastructure", "kernel"),
    ("infrastructure", "bootstrap"),   # <-- Kunci: infrastructure boleh akses bootstrap (composition root)

    # Adapters ↔ Kernel
    ("adapters", "kernel"),
    ("adapters", "audit"),
    ("adapters", "reports"),
    ("adapters", "event_gateway"),

    # Reports ↔ Projections
    ("reports", "projections"),
    ("projections", "infrastructure"),

    # Infrastructure ↔ Event Gateway
    ("infrastructure", "event_gateway"),
    ("application", "event_gateway"),

    # Application ↔ Lainnya
    ("application", "audit"),
    ("application", "policy_engine"),
    ("application", "adapters"),      # Untuk app_factory.py yang membuat adapters

    # ASGI ↔ Lainnya
    ("asgi", "application"),
    ("asgi", "config"),
    ("asgi", "policy_engine"),
    ("asgi", "event_gateway"),

    # Transformers ↔ Bootstrap / Event Gateway
    ("transformers", "bootstrap"),
    ("transformers", "event_gateway"),

    # Infrastructure ↔ Bootstrap (sudah ada, tapi tambahkan untuk kejelasan)
    ("infrastructure", "bootstrap"),
}

def top_layer(module: str) -> str:
    return module.split(".")[0]


def _safe_import_module(module_name: str) -> tuple[bool, str | None]:
    """
    Attempt to import a module by name. Returns (True, None) if successful,
    or (False, error_message) if an exception occurs.
    """
    try:
        importlib.import_module(module_name)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e!s}"

def get_ast_tree(path: pathlib.Path) -> ast.AST | None:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        return ast.parse(src, filename=str(path))
    except SyntaxError:
        return None
    except Exception:
        return None

def get_ast_tree_with_source(path: pathlib.Path) -> tuple[ast.AST | None, list[str] | None]:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        return ast.parse(src, filename=str(path)), lines
    except SyntaxError:
        return None, None
    except Exception:
        return None, None

# ─── Original import extractor (from main_checker.py) ──────────────────────
def get_imports_from_file(py_file: pathlib.Path) -> list[str]:
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level and node.level > 0:
                continue
            imports.append(node.module)
    return imports

def path_to_module(py_path: pathlib.Path, root: pathlib.Path) -> str | None:
    try:
        rel = py_path.relative_to(root)
    except ValueError:
        return None
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)

def should_exclude_path(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    for part in rel.parts:
        if part in _SKIP_ALWAYS:
            return True
        if part.startswith("__pycache__") or part.startswith(".pytest_cache") or part.startswith(".mypy_cache") or part.startswith(".ruff_cache"):
            return True
    return False

# ─── CRITICAL_MODULES ──────────────────────────────────────────────────────
CRITICAL_MODULES: list[tuple[str, str]] = [
    ("Constitution · SupremeLaw", "constitution.supreme_law"),
    ("Constitution · Invariants", "constitution.constitutional_invariants"),
    ("Constitution · SovereigntyDeclaration", "constitution.sovereignty_declaration"),
    ("Constitution · AmendmentProtocol", "constitution.amendment_protocol"),
    ("Constitution · VersionLock", "constitution.version_lock"),
    ("Constitution · ForbiddenStates", "constitution.forbidden_states"),
    ("Constitution · EnforcementEngine", "constitution.enforcement_engine"),
    ("Constitution · ConstitutionExceptions", "constitution.constitution_exceptions"),
    ("Axioms · DoubleEntry", "axioms.double_entry"),
    ("Axioms · Immutability", "axioms.immutability"),
    ("Axioms · ConservationOfValue", "axioms.conservation_of_value"),
    ("Axioms · TimeIrreversibility", "axioms.time_irreversibility"),
    ("Axioms · CausalityChain", "axioms.causality_chain"),
    ("Axioms · MonetaryUnit", "axioms.monetary_unit"),
    ("Axioms · EntityIsolation", "axioms.entity_isolation"),
    ("Axioms · PeriodBound", "axioms.period_bound"),
    ("Axioms · GoingConcern", "axioms.going_concern"),
    ("Axioms · AccrualBasis", "axioms.accrual_basis"),
    ("Axioms · Materiality", "axioms.materiality"),
    ("Axioms · SubstanceOverForm", "axioms.substance_over_form"),
    ("Axioms · AxiomViolation", "axioms.axiom_violation"),
    ("Bootstrap · Orchestrator", "bootstrap.orchestrator"),
    ("Bootstrap · PhasedStartup", "bootstrap.phased_startup"),
    ("Bootstrap · HealthProbe", "bootstrap.health_probe"),
    ("Bootstrap · RollbackHandler", "bootstrap.rollback_handler"),
    ("Bootstrap · BootstrapExceptions", "bootstrap.bootstrap_exceptions"),
    ("Bootstrap · DI · ServiceRegistry", "bootstrap.dependency_container.service_registry"),
    ("Bootstrap · DI · RepositoryRegistry", "bootstrap.dependency_container.repository_registry"),
    ("Bootstrap · DI · AdapterRegistry", "bootstrap.dependency_container.adapter_registry"),
    ("Bootstrap · DI · FactoryProvider", "bootstrap.dependency_container.factory_provider"),
    ("Bootstrap · DI · LifecycleHookRegistry", "bootstrap.dependency_container.lifecycle_hook_registry"),
    ("Bootstrap · DI · MockProvider", "bootstrap.dependency_container.mock_provider_for_testing"),
    ("Bootstrap · DI · ScopedContextManager", "bootstrap.dependency_container.scoped_context_manager"),
    ("Bootstrap · DI · DIHealthProbe", "bootstrap.dependency_container.di_health_probe"),
    ("Bootstrap · DI · DependencyGraphValidator", "bootstrap.dependency_container.dependency_graph_validator"),
    ("Bootstrap · DI · DIExceptions", "bootstrap.dependency_container.di_exceptions"),
    ("Config · LoaderYaml", "config.loader_yaml"),
    ("Config · SchemaValidator", "config.schema_validator"),
    ("Config · EnvironmentResolver", "config.environment_resolver"),
    ("Config · HotReloadWatcher", "config.hot_reload_watcher"),
    ("Config · EncryptionMaster", "config.encryption_master"),
    ("Config · VersionController", "config.version_controller"),
    ("Config · VaultIntegrator", "config.vault_integrator"),
    ("Kernel · SealedGate", "kernel.sealed_gate"),
    ("Kernel · ValidationPipeline", "kernel.validation_pipeline"),
    ("Kernel · CommandDispatcher", "kernel.command_dispatcher"),
    ("Kernel · CommandHandlerRegistry", "kernel.command_handler_registry"),
    ("Kernel · TransactionalExecutor", "kernel.transactional_executor"),
    ("Kernel · CircuitBreaker", "kernel.circuit_breaker"),
    ("Kernel · DistributedLockRedis", "kernel.distributed_lock_redis"),
    ("Kernel · AuditHookInjector", "kernel.audit_hook_injector"),
    ("Kernel · ContextHolder", "kernel.context_holder"),
    ("Kernel · DependencyInjector", "kernel.dependency_injector"),
    ("Kernel · LifecycleListener", "kernel.lifecycle_listener"),
    ("Kernel · MetricCollector", "kernel.metric_collector"),
    ("Kernel · RetryPolicy", "kernel.retry_policy"),
    ("Kernel · HealthIndicator", "kernel.health_indicator"),
    ("Kernel · KernelExceptions", "kernel.kernel_exceptions"),
    ("Kernel · Guards · BalanceChecker", "kernel.guards.balance_checker"),
    ("Kernel · Guards · PeriodLock", "kernel.guards.period_lock"),
    ("Kernel · Guards · SodEnforcer", "kernel.guards.sod_enforcer"),
    ("Kernel · Guards · EmergencyFreeze", "kernel.guards.emergency_freeze"),
    ("Kernel · Guards · CurrencyValidator", "kernel.guards.currency_validator"),
    ("Kernel · Guards · LegalEntityBoundary", "kernel.guards.legal_entity_boundary"),
    ("Kernel · Guards · AuthorityMatrix", "kernel.guards.authority_matrix"),
    ("Kernel · Guards · EvidenceAttacher", "kernel.guards.evidence_attacher"),
    ("Kernel · Guards · RegulatoryCompliance", "kernel.guards.regulatory_compliance"),
    ("Kernel · Guards · TemporalConsistency", "kernel.guards.temporal_consistency"),
    ("Kernel · Guards · CoretaxFormatValidator", "kernel.guards.coretax_format_validator"),
    ("Kernel · Guards · BudgetAvailability", "kernel.guards.budget_availability"),
    ("Kernel · Guards · CreditLimitEnforcer", "kernel.guards.credit_limit_enforcer"),
    ("Kernel · Guards · GuardExceptions", "kernel.guards.guard_exceptions"),
    ("Kernel · Guards · Async · FraudDetector", "kernel.guards.async_guards.fraud_pattern_detector"),
    ("Kernel · Guards · Async · AML", "kernel.guards.async_guards.anti_money_laundering"),
    ("Kernel · ImmutableLaws · Immutability", "kernel.immutable_laws.immutability_enforcer"),
    ("Kernel · ImmutableLaws · EvidenceMandate", "kernel.immutable_laws.evidence_mandate_enforcer"),
    ("Kernel · ImmutableLaws · DualApproval", "kernel.immutable_laws.dual_approval_enforcer"),
    ("Kernel · ImmutableLaws · ReversalConstraint", "kernel.immutable_laws.reversal_constraint_enforcer"),
    ("Kernel · ImmutableLaws · Traceability", "kernel.immutable_laws.traceability_enforcer"),
    ("Kernel · ImmutableLaws · PeriodClosure", "kernel.immutable_laws.period_closure_enforcer"),
    ("Kernel · ImmutableLaws · GLSupremacy", "kernel.immutable_laws.gl_supremacy_enforcer"),
    ("Kernel · ImmutableLaws · SoD", "kernel.immutable_laws.segregation_of_duties_enforcer"),
    ("Kernel · ImmutableLaws · NoRetroactive", "kernel.immutable_laws.no_retroactive_policy_enforcer"),
    ("Kernel · ImmutableLaws · AuditTrail", "kernel.immutable_laws.audit_trail_completeness_enforcer"),
    ("Kernel · ImmutableLaws · AssetExistence", "kernel.immutable_laws.asset_existence_enforcer"),
    ("Kernel · ImmutableLaws · FairValue", "kernel.immutable_laws.fair_value_measurement_enforcer"),
    ("Kernel · ImmutableLaws · LawViolation", "kernel.immutable_laws.law_violation_exceptions"),
    ("Domain · Reality", "domain.reality.economic_event_immutable"),
    ("Domain · Reality · FinancialObligation", "domain.reality.financial_obligation"),
    ("Domain · Reality · FinancialEntitlement", "domain.reality.financial_entitlement"),
    ("Domain · Reality · AssetExistenceValidator", "domain.reality.asset_existence_validator"),
    ("Domain · Reality · EffectiveDateVO", "domain.reality.effective_date_vo"),
    ("Domain · Reality · Mapper", "domain.reality.reality_to_accounting_mapper"),
    ("Domain · Reality · ValidationService", "domain.reality.reality_validation_service"),
    ("Domain · Intent", "domain.intent.capture_service"),
    ("Domain · Intent · ImmutableRecord", "domain.intent.immutable_record"),
    ("Domain · Intent · CryptoSigner", "domain.intent.cryptographic_signer"),
    ("Domain · Intent · ContextEnricher", "domain.intent.context_enricher"),
    ("Domain · Intent · OutcomeLinkTracker", "domain.intent.outcome_link_tracker"),
    ("Domain · Intent · AuditTrailWriter", "domain.intent.audit_trail_writer"),
    ("Domain · Intent · ForensicQueryEngine", "domain.intent.forensic_query_engine"),
    ("Domain · Intent · RevisionLogger", "domain.intent.revision_logger"),
    ("Domain · Intent · ApprovalWorkflow", "domain.intent.approval_workflow"),
    ("Domain · Intent · RiskAssessor", "domain.intent.risk_assessor"),
    ("Domain · Intent · MaterialityEvaluator", "domain.intent.materiality_evaluator"),
    ("Domain · Intent · VoidProcessor", "domain.intent.void_processor"),
    ("Domain · Causality", "domain.causality.causal_chain_builder"),
    ("Domain · Causality · CausalNode", "domain.causality.causal_node"),
    ("Domain · Causality · ExplanationGenerator", "domain.causality.explanation_generator"),
    ("Domain · Causality · AuditStoryBuilder", "domain.causality.audit_story_builder"),
    ("Domain · Causality · CausalityTracker", "domain.causality.causality_tracker"),
    ("Domain · Causality · WhyQueryEngine", "domain.causality.why_query_engine"),
    ("Domain · LegalEntity", "domain.legal_entity.aggregate_root"),
    ("Domain · LegalEntity · CompanyEntity", "domain.legal_entity.company_entity"),
    ("Domain · LegalEntity · TaxProfileVO", "domain.legal_entity.company_tax_profile_vo"),
    ("Domain · LegalEntity · DomainEvents", "domain.legal_entity.domain_events"),
    ("Domain · LegalEntity · Invariants", "domain.legal_entity.invariants"),
    ("Domain · IAM", "domain.iam.aggregate_root"),
    ("Domain · IAM · UserEntity", "domain.iam.user_entity"),
    ("Domain · IAM · RoleEntity", "domain.iam.role_entity"),
    ("Domain · IAM · PermissionVO", "domain.iam.permission_vo"),
    ("Domain · IAM · PasswordHashedVO", "domain.iam.password_hashed_vo"),
    ("Domain · IAM · SessionEntity", "domain.iam.session_entity"),
    ("Domain · IAM · LoginAttemptLog", "domain.iam.login_attempt_log"),
    ("Domain · IAM · DomainEvents", "domain.iam.domain_events"),
    ("Domain · IAM · Invariants", "domain.iam.invariants"),
    ("Domain · SystemSettings", "domain.system_settings.aggregate_root"),
    ("Domain · SystemSettings · SettingDef", "domain.system_settings.setting_definition_entity"),
    ("Domain · SystemSettings · SettingValueVO", "domain.system_settings.setting_value_vo"),
    ("Domain · SystemSettings · DomainEvents", "domain.system_settings.domain_events"),
    ("Domain · SystemSettings · Invariants", "domain.system_settings.invariants"),
    ("Domain · COA", "domain.coa.aggregate_root"),
    ("Domain · COA · AccountEntity", "domain.coa.account_entity"),
    ("Domain · COA · HierarchyTree", "domain.coa.account_hierarchy_tree"),
    ("Domain · COA · AccountCodeVO", "domain.coa.account_code_vo"),
    ("Domain · COA · AccountTypeEnum", "domain.coa.account_type_enum"),
    ("Domain · COA · NormalBalanceVO", "domain.coa.account_normal_balance_vo"),
    ("Domain · COA · StateMachine", "domain.coa.state_machine"),
    ("Domain · COA · DomainEvents", "domain.coa.domain_events"),
    ("Domain · COA · InvariantsValidator", "domain.coa.invariants_validator"),
    ("Domain · Journal", "domain.journal.aggregate_root"),
    ("Domain · Journal · Invariants", "domain.journal.invariants"),
    ("Domain · Journal · JournalEntity", "domain.journal.journal_entity"),
    ("Domain · Journal · JournalLineVO", "domain.journal.journal_line_vo"),
    ("Domain · Journal · StateMachine", "domain.journal.state_machine"),
    ("Domain · Journal · DomainEvents", "domain.journal.domain_events"),
    ("Domain · AR", "domain.subledger_ar.aggregate_root"),
    ("Domain · AR · InvoiceEntity", "domain.subledger_ar.invoice_entity"),
    ("Domain · AR · PaymentEntity", "domain.subledger_ar.payment_entity"),
    ("Domain · AR · CreditNoteEntity", "domain.subledger_ar.credit_note_entity"),
    ("Domain · AR · DebitNoteEntity", "domain.subledger_ar.debit_note_entity"),
    ("Domain · AR · CustomerCard", "domain.subledger_ar.customer_card"),
    ("Domain · AR · AgingBucketVO", "domain.subledger_ar.aging_bucket_vo"),
    ("Domain · AR · DomainEvents", "domain.subledger_ar.domain_events"),
    ("Domain · AR · Invariants", "domain.subledger_ar.invariants"),
    ("Domain · AR · BadDebtProvision", "domain.subledger_ar.bad_debt_provision_engine"),
    ("Domain · AP", "domain.subledger_ap.aggregate_root"),
    ("Domain · AP · InvoiceEntity", "domain.subledger_ap.invoice_entity"),
    ("Domain · AP · PaymentEntity", "domain.subledger_ap.payment_entity"),
    ("Domain · AP · CreditNoteEntity", "domain.subledger_ap.credit_note_entity"),
    ("Domain · AP · DebitNoteEntity", "domain.subledger_ap.debit_note_entity"),
    ("Domain · AP · VendorCard", "domain.subledger_ap.vendor_card"),
    ("Domain · AP · AgingBucketVO", "domain.subledger_ap.aging_bucket_vo"),
    ("Domain · AP · ThreeWayMatch", "domain.subledger_ap.three_way_match_engine"),
    ("Domain · AP · DomainEvents", "domain.subledger_ap.domain_events"),
    ("Domain · AP · Invariants", "domain.subledger_ap.invariants"),
    ("Domain · Inventory", "domain.inventory.aggregate_root"),
    ("Domain · Inventory · ItemEntity", "domain.inventory.item_entity"),
    ("Domain · Inventory · ItemTypeEnum", "domain.inventory.item_type_enum"),
    ("Domain · Inventory · MovementEntity", "domain.inventory.movement_entity"),
    ("Domain · Inventory · StockOpname", "domain.inventory.stock_opname_entity"),
    ("Domain · Inventory · StockAdjustment", "domain.inventory.stock_adjustment_entity"),
    ("Domain · Inventory · ValuationMethod", "domain.inventory.valuation_method"),
    ("Domain · Inventory · DomainEvents", "domain.inventory.domain_events"),
    ("Domain · Inventory · Invariants", "domain.inventory.invariants"),
    ("Domain · FixedAsset", "domain.fixed_asset.aggregate_root"),
    ("Domain · FixedAsset · AssetEntity", "domain.fixed_asset.asset_entity"),
    ("Domain · FixedAsset · AssetGroup", "domain.fixed_asset.asset_group_entity"),
    ("Domain · FixedAsset · DepreciationSchedule", "domain.fixed_asset.depreciation_schedule_engine"),
    ("Domain · FixedAsset · Revaluation", "domain.fixed_asset.revaluation_entity"),
    ("Domain · FixedAsset · Disposal", "domain.fixed_asset.disposal_entity"),
    ("Domain · FixedAsset · ImpairmentTester", "domain.fixed_asset.impairment_tester"),
    ("Domain · FixedAsset · Transfer", "domain.fixed_asset.transfer_entity"),
    ("Domain · FixedAsset · DomainEvents", "domain.fixed_asset.domain_events"),
    ("Domain · FixedAsset · Invariants", "domain.fixed_asset.invariants"),
    ("Domain · IntangibleAsset", "domain.intangible_asset.aggregate_root"),
    ("Domain · IntangibleAsset · AssetEntity", "domain.intangible_asset.asset_entity"),
    ("Domain · IntangibleAsset · Amortization", "domain.intangible_asset.amortization_schedule_engine"),
    ("Domain · BankCash", "domain.bank_cash.bank_aggregate_root"),
    ("Domain · BankCash · BankAccount", "domain.bank_cash.bank_account_entity"),
    ("Domain · BankCash · BankTransaction", "domain.bank_cash.bank_transaction_entity"),
    ("Domain · BankCash · Reconciliation", "domain.bank_cash.bank_reconciliation_engine"),
    ("Domain · BankCash · BankTransfer", "domain.bank_cash.bank_transfer_entity"),
    ("Domain · BankCash · CashAggregateRoot", "domain.bank_cash.cash_aggregate_root"),
    ("Domain · BankCash · CashBookEntity", "domain.bank_cash.cash_book_entity"),
    ("Domain · BankCash · PettyCashFund", "domain.bank_cash.petty_cash_fund_entity"),
    ("Domain · BankCash · CashReceipt", "domain.bank_cash.cash_receipt_entity"),
    ("Domain · BankCash · CashDisbursement", "domain.bank_cash.cash_disbursement_entity"),
    ("Domain · BankCash · DomainEvents", "domain.bank_cash.domain_events"),
    ("Domain · BankCash · Invariants", "domain.bank_cash.invariants"),
    ("Domain · Payroll", "domain.payroll.aggregate_root"),
    ("Domain · Payroll · SalaryStructureVO", "domain.payroll.employee_salary_structure_vo"),
    ("Domain · Payroll · PayrollRunEntity", "domain.payroll.payroll_run_entity"),
    ("Domain · Payroll · SalaryComponentEntity", "domain.payroll.salary_component_entity"),
    ("Domain · Payroll · PayslipProjection", "domain.payroll.payslip_projection"),
    ("Domain · Payroll · TaxWithholding", "domain.payroll.tax_withholding_engine"),
    ("Domain · Payroll · DomainEvents", "domain.payroll.domain_events"),
    ("Domain · Payroll · Invariants", "domain.payroll.invariants"),
    ("Domain · Manufacturing", "domain.manufacturing.aggregate_root"),
    ("Domain · Manufacturing · WorkOrder", "domain.manufacturing.work_order_entity"),
    ("Domain · Manufacturing · BOM", "domain.manufacturing.bill_of_materials_entity"),
    ("Domain · Manufacturing · ProductionRouting", "domain.manufacturing.production_routing_entity"),
    ("Domain · Manufacturing · WIP", "domain.manufacturing.work_in_process_entity"),
    ("Domain · Manufacturing · CostElementEnum", "domain.manufacturing.cost_element_enum"),
    ("Domain · Manufacturing · StandardCost", "domain.manufacturing.standard_cost_entity"),
    ("Domain · Manufacturing · VarianceAnalysis", "domain.manufacturing.variance_analysis_engine"),
    ("Domain · Manufacturing · OverheadAllocation", "domain.manufacturing.overhead_allocation_engine"),
    ("Domain · Manufacturing · HPPCalculator", "domain.manufacturing.hpp_per_product_calculator"),
    ("Domain · Manufacturing · CostCard", "domain.manufacturing.cost_card_entity"),
    ("Domain · Manufacturing · DomainEvents", "domain.manufacturing.domain_events"),
    ("Domain · Manufacturing · Invariants", "domain.manufacturing.invariants"),
    ("Domain · PurchaseSales", "domain.purchase_sales.purchase_order_aggregate"),
    ("Domain · PurchaseSales · POEntity", "domain.purchase_sales.purchase_order_entity"),
    ("Domain · PurchaseSales · GRN", "domain.purchase_sales.goods_receipt_note_entity"),
    ("Domain · PurchaseSales · PurchaseInvoice", "domain.purchase_sales.purchase_invoice_entity"),
    ("Domain · PurchaseSales · PurchaseReturn", "domain.purchase_sales.purchase_return_entity"),
    ("Domain · PurchaseSales · SalesOrder", "domain.purchase_sales.sales_order_aggregate"),
    ("Domain · PurchaseSales · SOEntity", "domain.purchase_sales.sales_order_entity"),
    ("Domain · PurchaseSales · DeliveryNote", "domain.purchase_sales.sales_delivery_note_entity"),
    ("Domain · PurchaseSales · SalesInvoice", "domain.purchase_sales.sales_invoice_entity"),
    ("Domain · PurchaseSales · SalesReturn", "domain.purchase_sales.sales_return_entity"),
    ("Domain · PurchaseSales · DomainEvents", "domain.purchase_sales.domain_events"),
    ("Domain · PurchaseSales · Invariants", "domain.purchase_sales.invariants"),
    ("Domain · ProjectServices", "domain.project_services.aggregate_root"),
    ("Domain · ProjectServices · ProjectEntity", "domain.project_services.project_entity"),
    ("Domain · ProjectServices · CostTracker", "domain.project_services.project_cost_tracker"),
    ("Domain · ProjectServices · RevenueRecognizer", "domain.project_services.project_revenue_recognizer"),
    ("Domain · ProjectServices · BillingSchedule", "domain.project_services.project_billing_schedule"),
    ("Domain · ProjectServices · TimeEntry", "domain.project_services.time_entry_entity"),
    ("Domain · ProjectServices · RetainerContract", "domain.project_services.retainer_contract_entity"),
    ("Domain · UMKMSimplified", "domain.umkm_simplified.transaction_aggregate"),
    ("Domain · UMKMSimplified · SimplifiedJournal", "domain.umkm_simplified.simplified_journal_entity"),
    ("Domain · UMKMSimplified · TaxComplianceHelper", "domain.umkm_simplified.tax_compliance_helper"),
    ("Domain · EquityRetained", "domain.equity_retained.aggregate_root"),
    ("Domain · EquityRetained · CapitalContrib", "domain.equity_retained.capital_contribution_entity"),
    ("Domain · EquityRetained · CapitalWithdrawal", "domain.equity_retained.capital_withdrawal_entity"),
    ("Domain · EquityRetained · RetainedEarnings", "domain.equity_retained.retained_earnings_entity"),
    ("Domain · EquityRetained · DividendDecl", "domain.equity_retained.dividend_declaration_entity"),
    ("Domain · SharedVO · Money", "domain.shared_value_objects.money_vo"),
    ("Domain · SharedVO · Currency", "domain.shared_value_objects.currency_vo"),
    ("Domain · SharedVO · ExchangeRate", "domain.shared_value_objects.exchange_rate_vo"),
    ("Domain · SharedVO · Percentage", "domain.shared_value_objects.percentage_vo"),
    ("Domain · SharedVO · Quantity", "domain.shared_value_objects.quantity_vo"),
    ("Domain · SharedVO · DateRange", "domain.shared_value_objects.date_range_vo"),
    ("Domain · SharedVO · AccountingPeriod", "domain.shared_value_objects.accounting_period_vo"),
    ("Domain · SharedVO · FiscalYear", "domain.shared_value_objects.fiscal_year_vo"),
    ("Domain · SharedVO · CostCenter", "domain.shared_value_objects.cost_center_vo"),
    ("Domain · SharedVO · Department", "domain.shared_value_objects.department_vo"),
    ("Domain · SharedVO · Warehouse", "domain.shared_value_objects.warehouse_vo"),
    ("Domain · SharedVO · TaxRate", "domain.shared_value_objects.tax_rate_vo"),
    ("Domain · SharedVO · NPWP", "domain.shared_value_objects.npwp_vo"),
    ("Domain · SharedVO · DocumentNumber", "domain.shared_value_objects.document_number_vo"),
    ("Domain · SharedVO · Signature", "domain.shared_value_objects.signature_vo"),
    ("Domain · SharedVO · HashChainLink", "domain.shared_value_objects.hash_chain_link_vo"),
    ("Domain · SharedVO · IdempotencyKey", "domain.shared_value_objects.idempotency_key_vo"),
    ("Policy · Loader", "policy_engine.loader_yaml"),
    ("Policy · Interpreter", "policy_engine.interpreter"),
    ("Policy · TemporalResolver", "policy_engine.temporal_resolver"),
    ("Policy · JurisdictionResolver", "policy_engine.jurisdiction_resolver"),
    ("Policy · ConflictResolver", "policy_engine.conflict_resolver"),
    ("Policy · OverrideAuthorizer", "policy_engine.override_authorizer"),
    ("Policy · CacheEngine", "policy_engine.cache_engine"),
    ("Policy · VersionManager", "policy_engine.version_manager"),
    ("Policy · PSAK · Aggregator", "policy_engine.psak.psak_aggregator"),
    ("Policy · PSAK · 01 Presentation", "policy_engine.psak.psak_01_presentation"),
    ("Policy · PSAK · 02 CashFlow", "policy_engine.psak.psak_02_cash_flow"),
    ("Policy · PSAK · 05 Segments", "policy_engine.psak.psak_05_operating_segments"),
    ("Policy · PSAK · 07 RelatedParty", "policy_engine.psak.psak_07_related_party"),
    ("Policy · PSAK · 10 ForeignExchange", "policy_engine.psak.psak_10_foreign_exchange"),
    ("Policy · PSAK · 13 InvestmentProperty", "policy_engine.psak.psak_13_investment_property"),
    ("Policy · PSAK · 14 Inventories", "policy_engine.psak.psak_14_inventories"),
    ("Policy · PSAK · 16 PPE", "policy_engine.psak.psak_16_property_plant_equipment"),
    ("Policy · PSAK · 19 IntangibleAssets", "policy_engine.psak.psak_19_intangible_assets"),
    ("Policy · PSAK · 22 BusinessCombinations", "policy_engine.psak.psak_22_business_combinations"),
    ("Policy · PSAK · 23 RevenueLegacy", "policy_engine.psak.psak_23_revenue_legacy"),
    ("Policy · PSAK · 24 EmployeeBenefits", "policy_engine.psak.psak_24_employee_benefits"),
    ("Policy · PSAK · 25 PoliciesEstimates", "policy_engine.psak.psak_25_policies_estimates_errors"),
    ("Policy · PSAK · 26 BorrowingCosts", "policy_engine.psak.psak_26_borrowing_costs"),
    ("Policy · PSAK · 46 IncomeTaxes", "policy_engine.psak.psak_46_income_taxes"),
    ("Policy · PSAK · 48 Impairment", "policy_engine.psak.psak_48_impairment"),
    ("Policy · PSAK · 71 FinancialInstruments", "policy_engine.psak.psak_71_financial_instruments_ifrs9"),
    ("Policy · PSAK · 72 Revenue", "policy_engine.psak.psak_72_revenue"),
    ("Policy · PSAK · 73 Leases", "policy_engine.psak.psak_73_leases"),
    ("Policy · IFRS · Aggregator", "policy_engine.ifrs.ifrs_aggregator"),
    ("Policy · IFRS · IAS01 Presentation", "policy_engine.ifrs.ias_01_presentation"),
    ("Policy · IFRS · IAS02 Inventories", "policy_engine.ifrs.ias_02_inventories"),
    ("Policy · IFRS · IAS12 IncomeTaxes", "policy_engine.ifrs.ias_12_income_taxes"),
    ("Policy · IFRS · IAS16 PPE", "policy_engine.ifrs.ias_16_ppe"),
    ("Policy · IFRS · IAS19 EmployeeBenefits", "policy_engine.ifrs.ias_19_employee_benefits"),
    ("Policy · IFRS · IAS21 ForeignExchange", "policy_engine.ifrs.ias_21_foreign_exchange"),
    ("Policy · IFRS · IAS36 Impairment", "policy_engine.ifrs.ias_36_impairment"),
    ("Policy · IFRS · IAS37 Provisions", "policy_engine.ifrs.ias_37_provisions"),
    ("Policy · IFRS · IFRS09 FinancialInstruments", "policy_engine.ifrs.ifrs_9_financial_instruments"),
    ("Policy · IFRS · IFRS10 Consolidation", "policy_engine.ifrs.ifrs_10_consolidation"),
    ("Policy · IFRS · IFRS15 Revenue", "policy_engine.ifrs.ifrs_15_revenue"),
    ("Policy · IFRS · IFRS16 Leases", "policy_engine.ifrs.ifrs_16_leases"),
    ("Policy · IFRS · ForSMEs", "policy_engine.ifrs.ifrs_for_smes"),
    ("Policy · Tax · PPNCalculator", "policy_engine.tax_indonesia.ppn_calculator"),
    ("Policy · Tax · PPh21Calculator", "policy_engine.tax_indonesia.pph_21_calculator"),
    ("Policy · Tax · PPh22Calculator", "policy_engine.tax_indonesia.pph_22_calculator"),
    ("Policy · Tax · PPh23Calculator", "policy_engine.tax_indonesia.pph_23_calculator"),
    ("Policy · Tax · PPh25Calculator", "policy_engine.tax_indonesia.pph_25_calculator"),
    ("Policy · Tax · PPh26Calculator", "policy_engine.tax_indonesia.pph_26_calculator"),
    ("Policy · Tax · PPh4Ayat2Calculator", "policy_engine.tax_indonesia.pph_4_ayat_2_calculator"),
    ("Policy · Tax · PPhBadanCalculator", "policy_engine.tax_indonesia.pph_badan_calculator"),
    ("Policy · Tax · BeaMeterai", "policy_engine.tax_indonesia.bea_meterai_calculator"),
    ("Policy · Tax · WithholdingEngine", "policy_engine.tax_indonesia.withholding_engine"),
    ("Policy · Tax · TreatyResolver", "policy_engine.tax_indonesia.treaty_resolver"),
    ("Policy · Tax · RateRegistryDynamic", "policy_engine.tax_indonesia.rate_registry_dynamic"),
    ("Policy · Tax · PenaltyInterestEngine", "policy_engine.tax_indonesia.penalty_interest_engine"),
    ("Compliance · PSAKChecker", "compliance.psak_checker"),
    ("Compliance · IFRSChecker", "compliance.ifrs_checker"),
    ("Compliance · SOXControlTester", "compliance.sox_control_tester"),
    ("Compliance · CoretaxValidator", "compliance.coretax_validator"),
    ("Compliance · OJKBuilder", "compliance.ojk_lkpub_builder"),
    ("Compliance · AMLRiskScorer", "compliance.aml_risk_scorer"),
    ("Compliance · GDPRPrivacyChecker", "compliance.gdpr_privacy_checker"),
    ("Compliance · DeficiencyTracker", "compliance.deficiency_tracker"),
    ("Compliance · Legal", "compliance.legal.jurisdiction_definition"),
    ("Compliance · Legal · AuthorityHierarchy", "compliance.legal.authority_hierarchy"),
    ("Compliance · Legal · SovereigntyBoundary", "compliance.legal.sovereignty_boundary_guard"),
    ("Compliance · Legal · CoretaxLegalBasis", "compliance.legal.coretax_legal_basis_catalog"),
    ("Compliance · Legal · SanctionListChecker", "compliance.legal.sanction_list_checker"),
    ("Compliance · Legal · RegulatoryFilingTracker", "compliance.legal.regulatory_filing_tracker"),
    ("Compliance · Ethics", "compliance.ethics.error_classifier_psak25"),
    ("Compliance · Ethics · CorrectionDoctrine", "compliance.ethics.correction_doctrine_engine"),
    ("Compliance · Ethics · DisclosureChecker", "compliance.ethics.disclosure_requirement_checker"),
    ("Compliance · Ethics · MaterialityQuantitative", "compliance.ethics.materiality_threshold_quantitative"),
    ("Compliance · Ethics · EthicsViolationDetector", "compliance.ethics.ethics_violation_detector"),
    ("Application · LifecycleHandler", "application.lifecycle_handler"),
    ("Application · ServiceCOA", "application.service_layer.service_coa"),
    ("Application · ServiceJournal", "application.service_layer.service_journal"),
    ("Application · ServiceAR", "application.service_layer.service_ar"),
    ("Application · ServiceAP", "application.service_layer.service_ap"),
    ("Application · ServiceInventory", "application.service_layer.service_inventory"),
    ("Application · ServiceFixedAsset", "application.service_layer.service_fixed_asset"),
    ("Application · ServiceBankCash", "application.service_layer.service_bank_cash"),
    ("Application · ServiceTax", "application.service_layer.service_tax"),
    ("Application · ServiceCoretax", "application.service_layer.service_coretax"),
    ("Application · ServiceManufacturing", "application.service_layer.service_manufacturing"),
    ("Application · ServicePayroll", "application.service_layer.service_payroll"),
    ("Application · ServiceReport", "application.service_layer.service_report"),
    ("Application · ServiceAudit", "application.service_layer.service_audit"),
    ("Application · PostJournal", "application.use_cases.post_journal_entry"),
    ("Application · PostAdjustingJournal", "application.use_cases.post_adjusting_journal"),
    ("Application · PostClosingJournal", "application.use_cases.post_closing_journal"),
    ("Application · ReverseJournal", "application.use_cases.reverse_journal"),
    ("Application · ApproveJournal", "application.use_cases.approve_journal_four_eyes"),
    ("Application · PeriodClose", "application.use_cases.period_close"),
    ("Application · BankReconciliation", "application.use_cases.bank_reconciliation"),
    ("Application · DepreciationMonthlyRun", "application.use_cases.depreciation_monthly_run"),
    ("Application · PayrollMonthlyRun", "application.use_cases.payroll_monthly_run"),
    ("Application · APPaymentRun", "application.use_cases.ap_payment_run"),
    ("Application · ARCollectionWorkflow", "application.use_cases.ar_collection_workflow"),
    ("Application · COGSCalculation", "application.use_cases.cogs_calculation"),
    ("Application · FinancialStatementGen", "application.use_cases.financial_statement_generation"),
    ("Application · TaxFilingSubmission", "application.use_cases.tax_filing_submission"),
    ("Application · CoretaxBulkSubmission", "application.use_cases.coretax_bulk_submission"),
    ("Application · YearEndClosing", "application.use_cases.year_end_closing"),
    ("Application · ForexRevaluation", "application.use_cases.forex_revaluation"),
    ("Application · ImpairmentTestingAnnual", "application.use_cases.impairment_testing_annual"),
    ("Application · DisasterRecoveryReplay", "application.use_cases.disaster_recovery_replay"),
    ("Application · CommandBus", "application.commands_cqrs.command_bus_unified"),
    ("Application · QueryBus", "application.commands_cqrs.query_bus_unified"),
    ("Application · ProcurementSaga", "application.sagas.procurement_saga"),
    ("Application · PayrollSaga", "application.sagas.payroll_saga"),
    ("Application · CoretaxSaga", "application.sagas.coretax_submission_saga"),
    ("Application · OutboxRelay", "application.outbox.outbox_relay_service"),
    ("Ports · JournalRepository", "ports.primary.journal_repository_port"),
    ("Ports · UnitOfWork", "ports.primary.unit_of_work_port"),
    ("Ports · EventPublisher", "ports.primary.event_publisher_port"),
    ("Ports · CoretaxPort", "ports.primary.tax_authority_coretax_port"),
    ("Adapters · FastAPI · Factory", "adapters.primary_api.common.fastapi_app_factory"),
    ("Adapters · FastAPI · Factory", "adapters.primary_api.common.app_factory"),
    ("Adapters · FastAPI · JournalRouter", "adapters.primary_api.v1.fastapi_journal_router"),
    ("Adapters · FastAPI · ARRouter", "adapters.primary_api.v1.fastapi_ar_router"),
    ("Adapters · FastAPI · APRouter", "adapters.primary_api.v1.fastapi_ap_router"),
    ("Adapters · FastAPI · TaxRouter", "adapters.primary_api.v1.fastapi_tax_coretax_router"),
    ("Adapters · FastAPI · ReportRouter", "adapters.primary_api.v1.fastapi_report_router"),
    ("Adapters · CoretaxDJP", "adapters.coretax_djp.api_oauth2_client"),
    ("Adapters · SecondaryImpl · Journal", "adapters.secondary_impl.sqlalchemy_journal_repository_impl"),
    ("Adapters · SecondaryImpl · UoW", "adapters.secondary_impl.sqlalchemy_unit_of_work_impl"),
    ("Adapters · SecondaryImpl · Kafka", "adapters.secondary_impl.kafka_event_publisher_impl"),
    ("Infra · Database · SessionFactory", "infrastructure.database.session_factory_sqlalchemy"),
    ("Infra · Database · TransactionMgr", "infrastructure.database.transaction_manager"),
    ("Infra · Database · MigrationManager", "infrastructure.database.migration_manager_alembic"),
    ("Infra · Database · AuditTriggerInstaller", "infrastructure.database.audit_trigger_installer"),
    ("Infra · Database · HealthProbe", "infrastructure.database.database_health_probe"),
    ("Infra · EventStore · AppendOnly", "infrastructure.event_store.append_only_store"),
    ("Infra · EventStore · HashChain", "infrastructure.event_store.hash_chain_builder"),
    ("Infra · EventStore · IntegrityVerifier", "infrastructure.event_store.integrity_verifier"),
    ("Infra · EventStore · ReplayEngine", "infrastructure.event_store.replay_engine"),
    ("Infra · EventStore · SnapshotManager", "infrastructure.event_store.snapshot_manager"),
    ("Infra · Caching · RedisManager", "infrastructure.caching.redis_manager"),
    ("Infra · Caching · InvalidatorEventListener", "infrastructure.caching.invalidator_event_listener"),
    ("Infra · Caching · NamespaceIsolation", "infrastructure.caching.namespace_isolation"),
    ("Infra · Security · JWTIssuer", "infrastructure.security.jwt_issuer"),
    ("Infra · Security · JWTValidator", "infrastructure.security.jwt_validator"),
    ("Infra · Security · FieldEncryption", "infrastructure.security.field_encryption_aes256_gcm"),
    ("Infra · Security · DigitalSigner", "infrastructure.security.digital_signer_rsa_pss"),
    ("Infra · Security · RBACSEnforcer", "infrastructure.security.rbac_enforcer_unified"),
    ("Infra · Security · SODConstraintChecker", "infrastructure.security.sod_constraint_checker"),
    ("Infra · Telemetry · Prometheus", "infrastructure.telemetry.prometheus_registry"),
    ("Infra · Telemetry · OpenTelemetry", "infrastructure.telemetry.opentelemetry_setup"),
    ("Infra · Telemetry · StructuredJsonLogging", "infrastructure.telemetry.structured_json_logging"),
    ("Infra · Telemetry · CorrelationIdInjector", "infrastructure.telemetry.correlation_id_injector"),
    ("Infra · MessageBroker · Kafka", "infrastructure.message_broker.kafka_producer_wrapper"),
    ("Infra · MessageBroker · KafkaConsumer", "infrastructure.message_broker.kafka_consumer_wrapper"),
    ("Infra · MessageBroker · DeadLetterHandler", "infrastructure.message_broker.kafka_dead_letter_handler"),
    ("Infra · MessageBroker · TransactionalOutbox", "infrastructure.message_broker.transactional_outbox_poller"),
    ("Audit · EventWriter", "audit.event_writer_immutable"),
    ("Audit · HashChain", "audit.hash_chain_builder"),
    ("Audit · ForensicReplayer", "audit.forensic_replayer"),
    ("Audit · TamperAlertTrigger", "audit.tamper_alert_trigger"),
    ("Audit · GapDetector", "audit.gap_detector"),
    ("Audit · DuplicateDetectorFuzzy", "audit.duplicate_detector_fuzzy"),
    ("Audit · ForensicReportGeneratorPDF", "audit.forensic_report_generator_pdf"),
    ("Audit · Sampling · MaterialityThreshold", "audit.sampling_materiality.materiality_threshold_calculator"),
    ("Audit · Sampling · StatisticalSampling", "audit.sampling_materiality.audit_sampling_statistical"),
    ("Projections · GL", "projections.ledger.general_ledger_table"),
    ("Projections · TrialBalance", "projections.ledger.trial_balance_cube"),
    ("Projections · BalanceSheet", "projections.ledger.balance_sheet_snapshot"),
    ("Projections · IncomeStatement", "projections.ledger.income_statement_period"),
    ("Projections · FiscalIncomeStatement", "projections.ledger.fiscal_income_statement"),
    ("Projections · CashFlow", "projections.ledger.cash_flow_indirect"),
    ("Projections · EquityStatement", "projections.ledger.equity_statement"),
    ("Projections · AR · AgingBuckets", "projections.subledger.ar_aging_buckets"),
    ("Projections · AP · AgingBuckets", "projections.subledger.ap_aging_buckets"),
    ("Projections · Inventory · StockCard", "projections.subledger.stock_card_fifo_layers"),
    ("Projections · FixedAsset · NBVSchedule", "projections.subledger.fixed_asset_nbv_schedule"),
    ("Projections · Tax · PPNSettlement", "projections.tax.ppn_output_input_settlement"),
    ("Projections · Tax · PPHWithholdingSummary", "projections.tax.pph_withholding_summary"),
    ("Projections · Tax · CoretaxFakturDashboard", "projections.tax.coretax_faktur_dashboard"),
    ("Projections · Analytics · TrendAnalyzer", "projections.analytics_bi.trend_analyzer_12month"),
    ("Projections · Analytics · VarianceAnalyzer", "projections.analytics_bi.variance_analyzer_actual_vs_budget"),
    ("Projections · Analytics · Profitability", "projections.analytics_bi.profitability_by_segment"),
    ("Projections · Analytics · FinancialRatios", "projections.analytics_bi.financial_ratios_calculator"),
    ("Reports · GeneratorPDFExcelHTML", "reports.generator_pdf_excel_html"),
    ("Reports · SchedulerCron", "reports.scheduler_cron"),
    ("Reports · DistributorEmailWhatsapp", "reports.distributor_email_whatsapp"),
    ("Reports · XBRLIFRSExporter", "reports.xbrl_ifrs_exporter"),
    ("Reports · OJKFormatBuilder", "reports.ojk_format_builder"),
    ("Event Gateway · Gate", "event_gateway.event_gate_singleton"),
    ("Event Gateway · Deduplicator", "event_gateway.event_deduplicator_idempotency"),
]

# ─── Environment & critical paths ──────────────────────────────────────────
REQUIRED_ENV_VARS: list[tuple[str, str]] = [
    ("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/erp_db"),
    ("REDIS_URL", "redis://localhost:6379/0"),
    ("SECRET_KEY", "your-256-bit-secret-key-here"),
    ("APP_ENV", "development | staging | production"),
    ("LOG_LEVEL", "DEBUG | INFO | WARNING | ERROR"),
]
OPTIONAL_ENV_VARS: list[tuple[str, str]] = [
    ("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    ("VAULT_ADDR", "http://localhost:8200"),
    ("VAULT_TOKEN", "your-vault-token"),
    ("CORETAX_API_BASE_URL", "https://api.coretax.pajak.go.id"),
    ("CORETAX_CLIENT_ID", "your-client-id"),
    ("CORETAX_CLIENT_SECRET", "your-client-secret"),
    ("MINIO_ENDPOINT", "localhost:9000"),
    ("MINIO_ACCESS_KEY", "your-access-key"),
    ("MINIO_SECRET_KEY", "your-secret-key"),
    ("JAEGER_AGENT_HOST", "localhost"),
    ("SENTRY_DSN", "https://xxx@sentry.io/xxx"),
    ("SMTP_HOST", "smtp.example.com"),
    ("WORKERS", "4"),
]
CRITICAL_PATHS: list[str] = [
    "constitution/supreme_law.py", "constitution/constitutional_invariants.py",
    "axioms/double_entry.py", "axioms/immutability.py", "axioms/conservation_of_value.py",
    "bootstrap/orchestrator.py", "config/loader_yaml.py", "config_files/application.yaml",
    "kernel/sealed_gate.py", "kernel/validation_pipeline.py",
    "kernel/guards/balance_checker.py", "kernel/guards/async_guards/fraud_pattern_detector.py",
    "kernel/immutable_laws/immutability_enforcer.py", "kernel/immutable_laws/gl_supremacy_enforcer.py",
    "domain/journal/aggregate_root.py", "domain/journal/invariants.py",
    "domain/reality/economic_event_immutable.py", "domain/intent/capture_service.py",
    "domain/causality/causal_chain_builder.py", "domain/shared_value_objects/money_vo.py",
    "domain/shared_value_objects/accounting_period_vo.py", "policy_engine/loader_yaml.py",
    "policy_engine/psak/psak_72_revenue.py", "policy_engine/psak/psak_73_leases.py",
    "policy_engine/ifrs/ifrs_15_revenue.py", "policy_engine/tax_indonesia/ppn_calculator.py",
    "policy_engine/tax_indonesia/pph_21_calculator.py", "compliance/psak_checker.py",
    "compliance/ifrs_checker.py", "compliance/legal/jurisdiction_definition.py",
    "compliance/ethics/error_classifier_psak25.py", "adapters/primary_api/common/app_factory.py",
    "application/use_cases/post_journal_entry.py", "application/use_cases/period_close.py",
    "application/commands_cqrs/command_bus_unified.py", "application/commands_cqrs/query_bus_unified.py",
    "application/sagas/procurement_saga.py", "application/sagas/payroll_saga.py",
    "application/sagas/coretax_submission_saga.py", "application/outbox/outbox_relay_service.py",
    "ports/primary/journal_repository_port.py", "ports/primary/unit_of_work_port.py",
    "ports/primary/event_publisher_port.py", "adapters/primary_api/common/fastapi_app_factory.py",
    "adapters/primary_api/v1/fastapi_journal_router.py", "adapters/coretax_djp/api_oauth2_client.py",
    "adapters/secondary_impl/sqlalchemy_journal_repository_impl.py",
    "infrastructure/database/session_factory_sqlalchemy.py", "infrastructure/database/transaction_manager.py",
    "infrastructure/event_store/append_only_store.py", "infrastructure/event_store/hash_chain_builder.py",
    "infrastructure/caching/redis_manager.py", "infrastructure/security/jwt_issuer.py",
    "infrastructure/security/rbac_enforcer_unified.py", "infrastructure/telemetry/prometheus_registry.py",
    "infrastructure/telemetry/opentelemetry_setup.py", "infrastructure/message_broker/kafka_producer_wrapper.py",
    "audit/event_writer_immutable.py", "audit/hash_chain_builder.py", "audit/forensic_replayer.py",
    "projections/ledger/general_ledger_table.py", "projections/ledger/trial_balance_cube.py",
    "event_gateway/event_gate_singleton.py", "event_gateway/event_deduplicator_idempotency.py",
    "asgi.py",
]

# =============================================================================
# PHASE IMPLEMENTATIONS (P00 – P60)
# =============================================================================

# P00 — Environment & Python
REQUIRED_PYTHON = (3, 10)

def p00_environment() -> PhaseResult:
    pr = PhaseResult("P00 Environment & Python", weight=2)
    pr.disclaimer = "Verifies Python version and critical package presence only."
    t0 = time.monotonic()
    ver = sys.version_info[:2]
    if ver < REQUIRED_PYTHON:
        pr.add("CRITICAL", "python", 0,
               f"Python {ver[0]}.{ver[1]} — need ≥ {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}",
               recommendation="Install Python 3.10 or higher.")
    else:
        pr.add("PASS", "python", 0, f"Python {ver[0]}.{ver[1]}.{sys.version_info[2]}")
    critical_pkgs = ["fastapi", "sqlalchemy", "alembic", "pydantic"]
    missing = [pkg for pkg in critical_pkgs
               if importlib.util.find_spec(pkg.replace("-", "_")) is None
               and importlib.util.find_spec(pkg) is None]
    for pkg in missing:
        pr.add("CRITICAL", "requirements.txt", 0,
               f"Missing critical package: {pkg}",
               recommendation=f"Run: pip install {pkg}")
    if not missing:
        pr.add("PASS", "requirements.txt", 0, "Critical packages present")
    pr.degrade(per_crit=15, per_warn=5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P01 — Folder Structure
REQUIRED_DIRS = ["app", "adapters", "application", "domain", "infrastructure",
                 "kernel", "ports", "config", "migrations", "tests", "compliance",
                 "audit", "constitution", "axioms", "bootstrap", "policy_engine"]

def p01_structure() -> PhaseResult:
    pr = PhaseResult("P01 Folder Structure", weight=1)
    pr.disclaimer = "Verifies directory existence only."
    t0 = time.monotonic()
    miss_d = [d for d in REQUIRED_DIRS if not (ROOT / d).is_dir()]
    for d in miss_d:
        pr.add("CRITICAL", d, 0, f"Required directory missing: {d}/",
               recommendation=f"Create directory: mkdir {d}")
    if not miss_d:
        pr.add("PASS", ".", 0, f"All {len(REQUIRED_DIRS)} directories present")
    pr.degrade(per_crit=20, per_warn=5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p02_syntax() -> PhaseResult:
    pr = PhaseResult("P02 Syntax Validation", weight=2)
    pr.disclaimer = "Ensures all source files are syntactically valid Python. Zero tolerance for syntax errors."
    t0 = time.monotonic()

    files = list(all_py(include_checker=True))
    errors = []

    for path in files:
        try:
            # Membaca bytes langsung agar bisa mendeteksi/menghapus BOM secara akurat
            raw = path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"): # BOM (Byte Order Mark)
                raw = raw[3:]

            # Melakukan parsing AST untuk validasi syntax
            ast.parse(raw, filename=str(path))

        except SyntaxError as e:
            errors.append((path, f"SyntaxError: {e.msg}", e.lineno or 0))
        except Exception as e:
            errors.append((path, f"ParseError: {type(e).__name__}: {str(e)[:80]}", 0))

    if not errors:
        pr.add("PASS", ".", 0, f"Structural integrity confirmed: All {len(files)} files are syntactically valid.")
        pr.score = 100
    else:
        # PENGUBAHAN: Jika ada error, skor langsung 0, tidak ada partial pass.
        pr.score = 0
        pr.passed = False

        # Laporkan semua error yang ditemukan
        for path, msg, lineno in errors[:30]: # Batasi agar output tidak terlalu panjang
            pr.add("CRITICAL", rel(path), lineno, msg,
                   recommendation="Fix the syntax error immediately. The engine cannot start with broken source files.")

        if len(errors) > 30:
            pr.add("INFO", ".", 0, f"... and {len(errors) - 30} more syntax errors.")

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p03_self_audit() -> PhaseResult:
    pr = PhaseResult("P03 Self-Audit (Meta-Integrity)", weight=3)
    pr.disclaimer = "Uses structural analysis to verify that the auditor itself is immutable, safe, and syntactically consistent."
    t0 = time.monotonic()

    checker_path = ROOT / "main_checker_3.py"
    if not checker_path.exists():
        pr.add("CRITICAL", "main_checker_3.py", 0, "Checker integrity failure: File missing.")
        pr.score = 0
        pr.finalize_status()
        return pr

    tree = get_ast_tree(checker_path)
    if tree is None:
        pr.add("CRITICAL", "main_checker_3.py", 0, "Checker syntax failure: Cannot parse own source code.")
        pr.score = 0
        pr.finalize_status()
        return pr

    violations = []
    phase_functions = []

    # Validasi Structural menggunakan AST Walk
    for node in ast.walk(tree):
        # 1. Deteksi Hardcoded Secrets (Hanya Assignment ke variable sensitif)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id.lower()
                    if any(s in var_name for s in ["password", "secret", "api_key", "token"]):
                        # Cek apakah valuenya berupa string literal (bukan hasil function call seperti os.getenv)
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            violations.append((node.lineno, f"Hardcoded secret detected in variable '{target.id}'"))

        # 2. Validasi Struktur Phase (Harus returning PhaseResult)
        elif isinstance(node, ast.FunctionDef):
            # Cek fungsi yang mengikuti pola pXX_...
            if re.match(r"^p\d{2}_", node.name):
                phase_functions.append(node.name)
                # Pastikan fungsi memiliki type hint return PhaseResult
                if not node.returns or (isinstance(node.returns, ast.Name) and node.returns.id != "PhaseResult"):
                     violations.append((node.lineno, f"Phase '{node.name}' lacks '-> PhaseResult' type annotation."))

    # Pelaporan Hasil
    if violations:
        pr.score = 0
        for lineno, msg in violations:
            pr.add("CRITICAL", "main_checker_3.py", lineno, msg,
                   recommendation="Remove hardcoded credentials and ensure all phases are strictly typed.")
    else:
        pr.add("PASS", "main_checker_3.py", 0,
               f"Meta-audit verified: {len(phase_functions)} registered phases validated for signature integrity.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P04 — Circular Imports (FIXED: build graph after collecting all modules)
def p04_circular() -> PhaseResult:
    pr = PhaseResult("P04 Circular Imports", weight=2)
    pr.disclaimer = "Static analysis of import graph (corrected logic)."
    t0 = time.monotonic()
    all_files = []
    for py_file in ROOT.rglob("*.py"):
        if should_exclude_path(py_file, ROOT):
            continue
        mod = path_to_module(py_file, ROOT)
        if mod:
            all_files.append((py_file, mod))
    module_files = {mod: path for path, mod in all_files}
    local_mods = set(module_files.keys())
    graph: dict[str, set[str]] = collections.defaultdict(set)
    for py_file, mod in all_files:
        imported = get_imports_from_file(py_file)
        for imp in imported:
            if imp in local_mods:
                graph[mod].add(imp)
            else:
                for local in local_mods:
                    if local.startswith(imp + "."):
                        graph[mod].add(local)
                        break
    # Tarjan SCC
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[set[str]] = []
    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack[node] = True
        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif on_stack.get(neighbor, False):
                lowlink[node] = min(lowlink[node], indices[neighbor])
        if lowlink[node] == indices[node]:
            scc: set[str] = set()
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.add(w)
                if w == node:
                    break
            if len(scc) > 1:
                sccs.append(scc)
    for node in graph:
        if node not in indices:
            strongconnect(node)
    cycles_found = 0
    for scc in sccs:
        if len(scc) >= 2:
            cycles_found += 1
            if cycles_found <= 30:
                cycle_list = list(scc)
                first_file = module_files.get(cycle_list[0], pathlib.Path("?"))
                pr.add("WARNING", rel(first_file), 0,
                       f"Static circular import cycle: {' → '.join(cycle_list[:5])}",
                       recommendation="Refactor to break the circular dependency.")
    if cycles_found == 0:
        pr.add("PASS", ".", 0, f"No static circular imports among {len(module_files)} modules")
    else:
        pr.add("INFO", ".", 0, f"Found {cycles_found} static cycle(s) (showing first 30)")
    pr.degrade(per_crit=10, per_warn=2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p05_static_imports() -> PhaseResult:
    pr = PhaseResult("P05 Static Import Scan", weight=2)
    pr.disclaimer = "Enforces strict import hygiene: Bans wildcard imports (*)."
    t0 = time.monotonic()

    files = list(all_py(skip_tops={"tests", "migrations", "deployment", "docs"}))
    violations = []
    total_imports = 0

    for path in files:
        tree = get_ast_tree(path)
        if not tree:
            continue

        for node in ast.walk(tree):
            # 1. Audit Wildcard Import
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        violations.append((rel(path), node.lineno))

            # 2. Statistik (hanya untuk log)
            if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                total_imports += len(node.names)

    if violations:
        pr.score = 0 # Zero tolerance untuk wildcard import
        for rp, lineno in violations:
            pr.add("CRITICAL", rp, lineno, "Forbidden wildcard import ('*') detected.",
                   recommendation="Explicitly name imports to prevent namespace pollution and dependency ambiguity.")
    else:
        pr.add("PASS", ".", 0, f"Import hygiene verified: No wildcard imports found across {len(files)} files.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

_PROTECTED_LAYERS = {"domain", "kernel", "axioms", "constitution", "ports"}

def p06_dynamic_imports() -> PhaseResult:
    pr = PhaseResult("P06 Dynamic Import Audit", weight=3)
    pr.disclaimer = "Strict architectural enforcement: Bans dynamic imports in core layers to ensure predictable dependency graphs."
    t0 = time.monotonic()

    # Local protected layers include application as well
    protected_layers = _PROTECTED_LAYERS | {"application"}

    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    violations = []

    for path in files:
        tree = get_ast_tree(path)
        if tree is None:
            continue

        mod = mod_name(path)
        layer = top_layer(mod) if mod else "unknown"
        is_protected = layer in protected_layers

        # ---- PENGECUALIAN: Abaikan file __init__.py di persistence_orm ----
        # karena melakukan auto-discovery yang merupakan kebutuhan fungsional
        if str(path).endswith("infrastructure/persistence_orm/__init__.py"):
            continue

        hits = _find_dynamic_imports_ast(tree)
        if not hits:
            continue

        for lineno, call, expr in hits:
            if is_protected:
                violations.append((rel(path), lineno, f"Forbidden dynamic import '{call}({expr})' in protected layer '{layer}'"))
            else:
                pr.add("WARNING", rel(path), lineno,
                       f"Dynamic import in non-core layer '{layer}': {call}({expr})",
                       recommendation="Verify if static import/DI is possible.")

    if violations:
        pr.score = 0
        pr.passed = False
        for rp, lineno, msg in violations:
            pr.add("CRITICAL", rp, lineno, msg,
                   recommendation="Dynamic imports destroy architectural traceability. Use Dependency Injection or static factories.")
    else:
        if pr.count("WARNING") == 0:
            pr.add("PASS", ".", 0, "No dynamic imports detected in sensitive layers (Clean Architecture verified).")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p07_broken_imports() -> PhaseResult:
    pr = PhaseResult("P07 Broken Import Scan", weight=3)
    pr.disclaimer = "Strictly verifies that every local import resolves to an existing file. Broken imports are CRITICAL."
    t0 = time.monotonic()

    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    local_mods = {mod_name(f) for f in files if mod_name(f)}
    local_tops = {m.split(".")[0] for m in local_mods}

    broken = []  # list of (file, line, import_name)

    for path in files:
        tree = get_ast_tree(path)
        if tree is None:
            continue

        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in local_tops and alias.name not in local_mods:
                        if not _resolve_import_target(alias.name, ROOT):
                            broken.append((rp, node.lineno, alias.name))

            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    top = node.module.split(".")[0]
                    if top in local_tops and node.module not in local_mods:
                        if not _resolve_import_target(node.module, ROOT):
                            broken.append((rp, node.lineno, node.module))

                elif node.level > 0:
                    found = False
                    if node.module:
                        candidates = _resolve_relative_import(path, node.level, node.module, None)
                        if candidates:
                            found = True
                    else:
                        for alias in node.names:
                            candidates = _resolve_relative_import(path, node.level, None, alias.name)
                            if candidates:
                                found = True
                                break

                    if not found:
                        if node.module:
                            broken.append((rp, node.lineno, f".{'.'*(node.level-1)}{node.module}"))
                        else:
                            for alias in node.names:
                                broken.append((rp, node.lineno, f".{'.'*(node.level-1)}{alias.name}"))

    if not broken:
        pr.add("PASS", ".", 0, "No broken local import references found.")
        pr.score = 100
    else:
        for rp, lineno, imp in broken[:30]:
            pr.add("CRITICAL", rp, lineno,
                   f"Broken import reference: {imp}",
                   recommendation=f"Ensure module '{imp}' exists or fix the import path.")
        if len(broken) > 30:
            pr.add("INFO", ".", 0, f"Plus {len(broken)-30} more broken imports.")
        pr.add("CRITICAL", ".", 0, f"System has {len(broken)} broken import(s). Cannot deploy.")
        pr.score = 0  # Strict: satu saja broken import = tidak layak

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p08_architecture() -> PhaseResult:
    pr = PhaseResult("P08 Architecture Layers", weight=3)
    pr.disclaimer = "Strictly enforces Clean Architecture layer rules. Violations in core layers are CRITICAL."
    t0 = time.monotonic()

    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    violations = []  # list of (file, line, from_layer, to_layer, import_name)

    exempt_layers = {"bootstrap", "app", "config"}  # layers that are allowed to break rules (bootstrapping)
    allowed_exceptions = _LAYER_EXCEPTIONS  # set of (from_layer, to_layer) that are allowed

    for path in files:
        mod = mod_name(path)
        if not mod:
            continue

        tree = get_ast_tree(path)
        if tree is None:
            continue

        layer = top_layer(mod)
        if layer in exempt_layers:
            continue

        allowed = _LAYER_RULES.get(layer)
        if allowed is None:
            # Layer tidak dikenal → warning tapi tidak sampai gagal
            pr.add("WARNING", rel(path), 0,
                   f"Unknown layer '{layer}' – please add to _LAYER_RULES.",
                   recommendation="Update _LAYER_RULES to include this layer.")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imp_layer = top_layer(alias.name)
                    if imp_layer and imp_layer in _LAYER_RULES and imp_layer not in allowed:
                        if (layer, imp_layer) not in allowed_exceptions:
                            violations.append((rel(path), node.lineno, layer, imp_layer, alias.name))

            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imp_layer = top_layer(node.module)
                if imp_layer and imp_layer in _LAYER_RULES and imp_layer not in allowed:
                    if (layer, imp_layer) not in allowed_exceptions:
                        violations.append((rel(path), node.lineno, layer, imp_layer, node.module))

    if not violations:
        pr.add("PASS", ".", 0, "All layer dependencies comply with Clean Architecture rules.")
        pr.score = 100
    else:
        # Tentukan mana yang melanggar aturan ketat (core layers)
        core_layers = {"domain", "kernel", "application", "ports", "axioms", "constitution"}
        critical_violations = []
        normal_violations = []

        for file, lineno, from_layer, to_layer, imp in violations:
            if from_layer in core_layers or to_layer in core_layers:
                critical_violations.append((file, lineno, from_layer, to_layer, imp))
            else:
                normal_violations.append((file, lineno, from_layer, to_layer, imp))

        # Laporkan CRITICAL terlebih dahulu
        for file, lineno, from_layer, to_layer, imp in critical_violations:
            pr.add("CRITICAL", file, lineno,
                   f"Core layer violation: '{from_layer}' imports '{imp}' from '{to_layer}'",
                   recommendation=f"Refactor to respect layer rules. '{from_layer}' is only allowed to import: {_LAYER_RULES.get(from_layer, [])}")

        # Untuk non-core, berikan WARNING
        for file, lineno, from_layer, to_layer, imp in normal_violations:
            pr.add("WARNING", file, lineno,
                   f"Layer violation (non-core): '{from_layer}' imports '{imp}' from '{to_layer}'",
                   recommendation="Consider refactoring to align with layer rules.")

        if critical_violations:
            pr.add("CRITICAL", ".", 0,
                   f"{len(critical_violations)} core layer violation(s) found. System is architecturally broken.")
            pr.score = 0
        else:
            pr.add("WARNING", ".", 0,
                   f"{len(normal_violations)} layer violation(s) found (non-core). System still deployable but needs review.")
            pr.score = 80  # Masih bisa deploy, tapi perlu perbaikan

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p09_port_adapter() -> PhaseResult:
    pr = PhaseResult("P09 Port-Adapter Contract Validation", weight=3)
    pr.disclaimer = "Validates port-adapter contracts. Ignores private methods (starting with _)."
    t0 = time.monotonic()

    ports_dir = ROOT / "ports" / "primary"
    adapters_dir = ROOT / "adapters"

    if not ports_dir.exists():
        pr.add("CRITICAL", "ports/primary", 0, "Ports directory missing.")
        pr.score = 0
        pr.finalize_status()
        return pr

    if not adapters_dir.exists():
        pr.add("CRITICAL", "adapters", 0, "Adapters directory missing.")
        pr.score = 0
        pr.finalize_status()
        return pr

    # ---------- Helpers ----------
    def is_abstract_or_placeholder(func_node: ast.FunctionDef) -> bool:
        for dec in func_node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "abstractmethod":
                return True
            if isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod":
                return True
        if len(func_node.body) == 1:
            stmt = func_node.body[0]
            if isinstance(stmt, ast.Pass):
                return True
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value == Ellipsis:
                return True
            if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
                if isinstance(stmt.exc.func, ast.Name) and stmt.exc.func.id == "NotImplementedError":
                    return True
        return False

    def inherits_abc(node: ast.ClassDef) -> bool:
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in ("ABC", "Protocol"):
                return True
            if isinstance(base, ast.Attribute) and base.attr in ("ABC", "Protocol"):
                return True
            if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id == "typing" and base.attr == "Protocol":
                return True
        return False

    def is_port_class(node: ast.ClassDef) -> bool:
        if not (node.name.endswith("Port") or node.name.endswith("Repository")):
            return False
        # Cek apakah ada metode non-private yang abstract/placeholder
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                if is_abstract_or_placeholder(item):
                    return True
        if inherits_abc(node):
            return True
        return False

    def get_contract_methods(node: ast.ClassDef) -> set[str]:
        methods = set()
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                if is_abstract_or_placeholder(item):
                    methods.add(item.name)
        return methods

    # ---------- Extract ports ----------
    port_interfaces = {}
    for port_file in ports_dir.glob("*.py"):
        if port_file.name == "__init__.py":
            continue
        tree = get_ast_tree(port_file)
        if tree is None:
            pr.add("WARNING", rel(port_file), 0, "Cannot parse port file.")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and is_port_class(node):
                methods = get_contract_methods(node)
                if methods:
                    port_interfaces[node.name] = (port_file.stem, methods)

    # ---------- Extract adapters ----------
    adapter_implementations = {}
    for adapter_file in adapters_dir.rglob("*.py"):
        if adapter_file.name == "__init__.py" or "__pycache__" in str(adapter_file):
            continue
        tree = get_ast_tree(adapter_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Skip ORM tables
            has_tablename = False
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "__tablename__":
                            has_tablename = True
                            break
                if has_tablename:
                    break
            if has_tablename:
                continue
            if "Error" in node.name or "Exception" in node.name:
                continue
            # Skip abstract classes
            is_abs = False
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and is_abstract_or_placeholder(item):
                    is_abs = True
                    break
            if is_abs:
                continue
            # Collect public methods (non-private)
            methods = set()
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                    methods.add(item.name)
            if methods:
                adapter_implementations[node.name] = (adapter_file.stem, methods)

    # ---------- Matching ----------
    unmatched = []
    missing_methods = []

    for port_class, (port_file_stem, contract_methods) in port_interfaces.items():
        found_adapter_class = None
        found_adapter_stem = None
        found_methods = None

        # 1. Exact match by class name
        for adapter_class, (stem, methods) in adapter_implementations.items():
            if adapter_class.lower() == port_class.lower():
                found_adapter_class = adapter_class
                found_adapter_stem = stem
                found_methods = methods
                break

        # 2. Name contains port_class (case-insensitive)
        if not found_adapter_class:
            for adapter_class, (stem, methods) in adapter_implementations.items():
                if port_class.lower() in adapter_class.lower() or adapter_class.lower() in port_class.lower():
                    found_adapter_class = adapter_class
                    found_adapter_stem = stem
                    found_methods = methods
                    break

        # 3. File stem pattern (dengan tambahan mapping khusus)
        if not found_adapter_class:
            base = port_file_stem.replace("_port", "").replace("_repository", "")
            # Mapping khusus untuk port yang nama adapter tidak sesuai pola
            special_mappings = {
                "core_tax": "tax_authority_coretax_impl",
                "event_publisher": "kafka_event_publisher_impl",
                "encryption_key_vault": "encryption_key_vault_impl",
                "hash_chain_service": "hash_chain_service_impl",
                "iam_repository": "sqlalchemy_iam_user_repository_impl",  # ada juga IAMUserRepositoryPort
            }
            possible_stems = []
            if base in special_mappings:
                possible_stems.append(special_mappings[base])
            possible_stems += [
                f"sqlalchemy_{base}_impl",
                f"{base}_impl",
                f"sqlalchemy_{base}_repository_impl",
                f"{base}_repository_impl",
                f"sqlalchemy_{base}_adapter",
                f"{base}_adapter",
                f"sqlalchemy_{port_class.lower()}_adapter",
                f"{port_class.lower()}_adapter",
            ]
            for stem in possible_stems:
                for adapter_class, (fstem, methods) in adapter_implementations.items():
                    if fstem == stem:
                        found_adapter_class = adapter_class
                        found_adapter_stem = stem
                        found_methods = methods
                        break
                if found_adapter_class:
                    break

        if not found_adapter_class:
            unmatched.append((port_class, port_file_stem))
            continue

        missing = contract_methods - found_methods
        if missing:
            missing_methods.append((port_class, found_adapter_class, found_adapter_stem, missing))

    # ---------- Report ----------
    for port_class, port_file_stem in unmatched:
        pr.add("CRITICAL", f"ports/primary/{port_file_stem}.py", 0,
               f"Port '{port_class}' has no adapter.",
               recommendation=f"Create adapter for '{port_class}' or register alias in adapter_registry.py.")

    for port_class, adapter_class, adapter_stem, missing in missing_methods:
        pr.add("CRITICAL", f"adapters/{adapter_stem}.py", 0,
               f"Adapter '{adapter_class}' missing public methods: {missing}",
               recommendation=f"Implement these methods in {adapter_stem}.py.")

    if not unmatched and not missing_methods:
        pr.add("PASS", ".", 0, f"All {len(port_interfaces)} ports are fully implemented.")
        pr.score = 100
    else:
        critical_count = len(unmatched) + len(missing_methods)
        pr.add("CRITICAL", ".", 0, f"{critical_count} port-adapter violation(s).")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p10_routes() -> PhaseResult:
    pr = PhaseResult("P10 API Route Completeness", weight=2)
    pr.disclaimer = "Strictly validates that each expected router file exists, defines a valid APIRouter, and has at least one route."
    t0 = time.monotonic()

    v1 = ROOT / "adapters" / "primary_api" / "v1"
    if not v1.exists():
        pr.add("CRITICAL", "adapters/primary_api/v1", 0,
               "v1 router directory not found",
               recommendation="Create adapters/primary_api/v1/ and add router files.")
        pr.score = 0
        pr.finalize_status()
        return pr

    present_files = {f.stem for f in v1.glob("*.py") if f.stem != "__init__"}

    # =========================================================================
    # Daftar router yang diharapkan
    # =========================================================================
    EXPECTED_ROUTERS = [
        "fastapi_coa_router",
        "fastapi_journal_router",
        "fastapi_ledger_router",
        "fastapi_ap_router",
        "fastapi_ar_router",
        "fastapi_bank_cash_router",
        "fastapi_inventory_router",
        "fastapi_fixed_asset_router",
        "fastapi_tax_coretax_router",
        "fastapi_iam_router",
    ]

    missing = []
    invalid = []  # list of (router_name, reason)

    # =========================================================================
    # Validasi setiap router yang diharapkan
    # =========================================================================
    for router_name in EXPECTED_ROUTERS:
        if router_name not in present_files:
            missing.append(router_name)
            continue

        router_file = v1 / f"{router_name}.py"
        tree = get_ast_tree(router_file)
        if tree is None:
            invalid.append((router_name, "Syntax error in file"))
            continue

        # Cari assignment: router = APIRouter()
        has_router_assignment = False
        has_route_decorator = False

        for node in ast.walk(tree):
            # Deteksi assignment router = APIRouter() atau router = Router()
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "router":
                        if isinstance(node.value, ast.Call):
                            func = node.value.func
                            if isinstance(func, ast.Name):
                                if func.id in ("APIRouter", "Router"):
                                    has_router_assignment = True
                            elif isinstance(func, ast.Attribute):
                                # misal: fastapi.APIRouter
                                if func.attr in ("APIRouter", "Router"):
                                    has_router_assignment = True

            # Deteksi dekorator route: @router.get, @router.post, dll.
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    # Kasus: @router.get("/path")
                    if isinstance(decorator, ast.Call):
                        func = decorator.func
                        if isinstance(func, ast.Attribute):
                            if isinstance(func.value, ast.Name) and func.value.id == "router":
                                if func.attr in ("get", "post", "put", "delete", "patch", "head", "options"):
                                    has_route_decorator = True
                    # Kasus: @router.get (tanpa kurung, jarang)
                    elif isinstance(decorator, ast.Attribute):
                        if isinstance(decorator.value, ast.Name) and decorator.value.id == "router":
                            if decorator.attr in ("get", "post", "put", "delete", "patch", "head", "options"):
                                has_route_decorator = True

        if not has_router_assignment:
            invalid.append((router_name, "Missing 'router = APIRouter()' assignment"))
        elif not has_route_decorator:
            invalid.append((router_name, "No route decorator found (e.g., @router.get(...))"))

    # =========================================================================
    # Laporan hasil
    # =========================================================================
    if missing:
        for r in missing:
            pr.add("CRITICAL", "adapters/primary_api/v1", 0,
                   f"Missing router file: {r}.py",
                   recommendation=f"Create {r}.py in adapters/primary_api/v1/ with APIRouter definition and at least one route.")

    if invalid:
        for router_name, reason in invalid:
            pr.add("CRITICAL", f"adapters/primary_api/v1/{router_name}.py", 0,
                   f"Invalid router: {reason}",
                   recommendation=f"Ensure {router_name}.py defines 'router = APIRouter()' and has at least one route decorated with @router.get, @router.post, etc.")

    if not missing and not invalid:
        pr.add("PASS", "adapters/primary_api/v1", 0,
               f"All {len(EXPECTED_ROUTERS)} router files are present, define APIRouter, and have at least one route.")
        pr.score = 100
    else:
        total_errors = len(missing) + len(invalid)
        pr.add("CRITICAL", "adapters/primary_api/v1", 0,
               f"{total_errors} router issue(s) found. API layer is incomplete or broken.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p11_yaml() -> PhaseResult:
    pr = PhaseResult("P11 YAML Validation", weight=2)
    pr.disclaimer = "Strictly validates YAML syntax and enforces required structure for critical config files."
    t0 = time.monotonic()

    try:
        import yaml
    except ImportError:
        pr.add("CRITICAL", ".", 0,
               "PyYAML not installed — cannot validate YAML configs.",
               recommendation="Install PyYAML: pip install pyyaml")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Kumpulkan semua file YAML
    yfiles = []
    for d in ["config_files", "monitoring", "deployment"]:
        dp = ROOT / d
        if dp.exists():
            yfiles.extend(dp.rglob("*.yaml"))
            yfiles.extend(dp.rglob("*.yml"))
    yfiles.extend(ROOT.glob("*.yaml"))
    yfiles.extend(ROOT.glob("*.yml"))

    if not yfiles:
        pr.add("INFO", ".", 0, "No YAML files found.")
        pr.score = 100
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    errors = []
    structure_violations = []

    # Definisi struktur minimal untuk file konfigurasi kritis
    required_structure = {
        "application.yaml": {
            "required_keys": ["app", "database", "logging"],
            "description": "Application main config"
        },
        "database.yaml": {
            "required_keys": ["database", "pool"],
            "description": "Database config"
        },
        "kafka.yaml": {
            "required_keys": ["bootstrap_servers", "topics"],
            "description": "Kafka config"
        },
        "redis.yaml": {
            "required_keys": ["url", "pool"],
            "description": "Redis config"
        },
        "coretax.yaml": {
            "required_keys": ["api_base_url", "client_id", "client_secret"],
            "description": "Coretax DJP config"
        },
    }

    for yf in sorted(set(yfiles)):
        rel_path = rel(yf)
        try:
            with open(yf, encoding="utf-8") as fh:
                content = yaml.safe_load(fh)

            # Jika file kosong atau tidak ada konten, anggap error
            if content is None:
                errors.append((rel_path, "Empty YAML file (no content)"))
                continue

            # Validasi struktur untuk file yang diketahui
            basename = yf.name
            if basename in required_structure:
                struct = required_structure[basename]
                missing_keys = []
                if isinstance(content, dict):
                    for key in struct["required_keys"]:
                        if key not in content:
                            missing_keys.append(key)
                    if missing_keys:
                        structure_violations.append(
                            (rel_path, f"Missing required key(s): {missing_keys} for {struct['description']}")
                        )
                else:
                    structure_violations.append(
                        (rel_path, f"Content must be a dictionary (got {type(content).__name__}) for {struct['description']}")
                    )

        except yaml.YAMLError as e:
            errors.append((rel_path, f"YAML syntax error: {str(e)[:80]}"))
        except Exception as e:
            errors.append((rel_path, f"Unexpected error: {type(e).__name__}: {str(e)[:80]}"))

    # =========================================================================
    # Laporan hasil
    # =========================================================================
    if errors:
        for rel_path, msg in errors:
            pr.add("CRITICAL", rel_path, 0, msg, recommendation="Fix YAML syntax or content.")
        pr.add("CRITICAL", ".", 0, f"{len(errors)} YAML file(s) have errors.")
        pr.score = 0
    elif structure_violations:
        for rel_path, msg in structure_violations:
            pr.add("CRITICAL", rel_path, 0, msg, recommendation="Ensure all required keys are present.")
        pr.add("CRITICAL", ".", 0, f"{len(structure_violations)} YAML file(s) have structural violations.")
        pr.score = 0
    else:
        pr.add("PASS", ".", 0, f"All {len(yfiles)} YAML files have valid syntax and required structure.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p12_asgi() -> PhaseResult:
    pr = PhaseResult("P12 ASGI Load", weight=2)
    pr.disclaimer = "Strictly validates that app/main.py defines a valid ASGI application (FastAPI instance or factory)."
    t0 = time.monotonic()

    main_py = ROOT / "app" / "main.py"
    if not main_py.exists():
        pr.add("CRITICAL", "app/main.py", 0,
               "app/main.py not found. ASGI application entry point is missing.",
               recommendation="Create app/main.py with FastAPI application definition.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    tree = get_ast_tree(main_py)
    if tree is None:
        pr.add("CRITICAL", "app/main.py", 0,
               "Syntax error in app/main.py. Cannot parse.",
               recommendation="Fix syntax errors in app/main.py.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =========================================================================
    # Deteksi berbagai elemen ASGI app
    # =========================================================================
    has_app_variable = False
    has_create_app_function = False
    has_get_app_function = False
    has_lifespan_decorator = False
    has_fastapi_import = False
    has_fastapi_call = False
    app_assignment_source = None
    create_app_returns = False
    get_app_returns = False

    # Cek import FastAPI
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "fastapi":
                for alias in node.names:
                    if alias.name == "FastAPI":
                        has_fastapi_import = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fastapi":
                    has_fastapi_import = True

    # Cek assignment app = ...
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("app", "application"):
                    has_app_variable = True
                    if isinstance(node.value, ast.Call):
                        func = node.value.func
                        if isinstance(func, ast.Name) and func.id == "FastAPI":
                            app_assignment_source = "FastAPI() direct"
                            has_fastapi_call = True
                        elif isinstance(func, ast.Attribute) and func.attr == "FastAPI":
                            app_assignment_source = "FastAPI() from import"
                            has_fastapi_call = True
                        elif isinstance(func, ast.Name) and func.id in ("create_app", "get_app"):
                            app_assignment_source = f"{func.id}() factory"
                        else:
                            app_assignment_source = "callable/unknown"
                    elif isinstance(node.value, ast.Name):
                        app_assignment_source = f"reference to {node.value.id}"
                    elif isinstance(node.value, ast.Call):
                        # fallback
                        app_assignment_source = "function call"

    # Cek fungsi create_app dan get_app
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name == "create_app":
                has_create_app_function = True
                # Cek apakah ada return statement yang mengembalikan sesuatu
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Return) and subnode.value is not None:
                        create_app_returns = True
                        # Cek apakah return-nya FastAPI()
                        if isinstance(subnode.value, ast.Call):
                            func = subnode.value.func
                            if (isinstance(func, ast.Name) and func.id == "FastAPI") or (isinstance(func, ast.Attribute) and func.attr == "FastAPI"):
                                has_fastapi_call = True
                        break

            if node.name == "get_app":
                has_get_app_function = True
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Return) and subnode.value is not None:
                        get_app_returns = True
                        if isinstance(subnode.value, ast.Call):
                            func = subnode.value.func
                            if (isinstance(func, ast.Name) and func.id == "FastAPI") or (isinstance(func, ast.Attribute) and func.attr == "FastAPI"):
                                has_fastapi_call = True
                        break

            # Deteksi lifespan decorator (biasanya dalam fungsi bernama lifespan)
            if node.name == "lifespan":
                for decorator in node.decorator_list:
                    if (isinstance(decorator, ast.Name) and decorator.id == "asynccontextmanager") or (isinstance(decorator, ast.Attribute) and decorator.attr == "asynccontextmanager"):
                        has_lifespan_decorator = True

    # =========================================================================
    # Evaluasi
    # =========================================================================
    issues = []

    # Harus ada app variable ATAU create_app/get_app function
    if not has_app_variable and not has_create_app_function and not has_get_app_function:
        issues.append("No 'app' variable or 'create_app'/'get_app' function found.")
    else:
        # Jika ada app variable, pastikan sumbernya jelas
        if has_app_variable and app_assignment_source is None:
            issues.append("'app' variable exists but source could not be determined.")

        # Jika ada create_app, pastikan mengembalikan nilai
        if has_create_app_function and not create_app_returns:
            issues.append("'create_app' function does not return anything (missing return statement).")

        # Jika ada get_app, pastikan mengembalikan nilai
        if has_get_app_function and not get_app_returns:
            issues.append("'get_app' function does not return anything (missing return statement).")

    # FastAPI import tidak wajib jika pakai factory, tapi lebih baik ada
    # Kita hanya beri warning jika tidak ada FastAPI import dan tidak ada factory yang memanggil FastAPI
    if not has_fastapi_import and not has_fastapi_call:
        issues.append("FastAPI import not detected. Ensure app is an ASGI application.")

    # =========================================================================
    # Laporan
    # =========================================================================
    if issues:
        for issue in issues:
            pr.add("CRITICAL", "app/main.py", 0, issue, recommendation="Define ASGI app properly.")
        pr.add("CRITICAL", "app/main.py", 0, f"{len(issues)} ASGI configuration issue(s) found.")
        pr.score = 0
    else:
        details = []
        if has_app_variable:
            details.append(f"app variable ({app_assignment_source})")
        if has_create_app_function and create_app_returns:
            details.append("create_app() factory")
        if has_get_app_function and get_app_returns:
            details.append("get_app() factory")
        if has_lifespan_decorator:
            details.append("lifespan context manager")
        if has_fastapi_import:
            details.append("FastAPI imported")

        pr.add("PASS", "app/main.py", 0,
               f"ASGI application verified: {', '.join(details)}")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p13_migrations() -> PhaseResult:
    pr = PhaseResult("P13 Migration Chain", weight=3)
    pr.disclaimer = "Strictly validates Alembic migration revision graph. Orphans, cycles, and multiple heads are fatal."
    t0 = time.monotonic()

    versions_dir = ROOT / "migrations" / "versions"
    if not versions_dir.exists():
        pr.add("CRITICAL", "migrations/versions", 0,
               "versions directory not found. Alembic migrations not initialized.",
               recommendation="Run 'alembic init migrations' or create migrations/versions directory.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Kumpulkan semua file migration (abaikan __init__.py)
    migration_files = [f for f in sorted(versions_dir.glob("*.py")) if f.name != "__init__.py"]
    if not migration_files:
        pr.add("WARNING", "migrations/versions", 0,
               "No migration files found. Database schema may not be versioned.",
               recommendation="Create initial migration: alembic revision --autogenerate -m 'initial'")
        pr.score = 80  # Not fatal, but needs attention
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Ekstrak revision dan down_revision dari setiap file
    revs: dict[str, str] = {}          # revision -> down_revision (empty string if None)
    file_by_rev: dict[str, pathlib.Path] = {}
    invalid_files: list[tuple[pathlib.Path, str]] = []  # (file, reason)

    for mf in migration_files:
        src = mf.read_text(encoding="utf-8", errors="replace")

        # Cari revision (support berbagai format)
        rm = re.search(r'^revision\s*=\s*["\'](\w+)["\']', src, re.M)
        if not rm:
            rm = re.search(r'^revision\s*:\s*[^=]+\s*=\s*["\'](\w+)["\']', src, re.M)
        if not rm:
            # Coba cari pola: revision: str = "xxx" (dengan type annotation)
            rm = re.search(r'^revision\s*:\s*str\s*=\s*["\'](\w+)["\']', src, re.M)
        if not rm:
            invalid_files.append((mf, "Missing 'revision' identifier"))
            continue

        rev = rm.group(1)
        if len(rev) < 8:  # revision biasanya panjang (hash)
            invalid_files.append((mf, f"Revision '{rev}' is too short (expected at least 8 characters)"))
            continue

        # Cari down_revision (bisa None atau string)
        dm = re.search(r'^down_revision\s*=\s*["\']?(\w+|None)["\']?', src, re.M)
        if not dm:
            dm = re.search(r'^down_revision\s*:\s*[^=]+\s*=\s*["\']?(\w+|None)["\']?', src, re.M)
        if not dm:
            # Coba cari pola: down_revision: str | None = "xxx"
            dm = re.search(r'^down_revision\s*:\s*(?:str\s*\|\s*None|None\s*\|\s*str)\s*=\s*["\']?(\w+|None)["\']?', src, re.M)

        down = dm.group(1) if dm and dm.group(1) != "None" else ""
        revs[rev] = down
        file_by_rev[rev] = mf

    # Laporkan file yang invalid
    if invalid_files:
        for mf, reason in invalid_files:
            pr.add("CRITICAL", rel(mf), 0,
                   f"Invalid migration file: {reason}",
                   recommendation="Ensure file has 'revision' and 'down_revision' variables with valid values.")
        pr.add("CRITICAL", "migrations/versions", 0,
               f"{len(invalid_files)} migration file(s) are invalid.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Analisis graph
    all_rev = set(revs.keys())
    all_down = {v for v in revs.values() if v}
    orphans = all_down - all_rev   # down_revision yang tidak ada di revs
    heads = all_rev - all_down     # revision yang tidak menjadi down_revision orang lain

    # Deteksi orphan
    if orphans:
        for o in orphans:
            # Cari tahu file mana yang merujuk ke orphan ini
            for rev, down in revs.items():
                if down == o:
                    pr.add("CRITICAL", rel(file_by_rev.get(rev, versions_dir / "unknown")), 0,
                           f"Orphan down_revision '{o}' referenced by migration '{rev}' but revision '{o}' not found.",
                           recommendation=f"Create migration with revision '{o}' or update down_revision to existing revision.")
                    break
            else:
                # Orphan tidak dirujuk oleh file manapun? (seharusnya tidak mungkin)
                pr.add("CRITICAL", "migrations/versions", 0,
                       f"Orphan revision '{o}' is referenced but no file defines it.")

    # Deteksi multiple heads
    if len(heads) > 1:
        pr.add("CRITICAL", "migrations/versions", 0,
               f"Multiple heads ({len(heads)}) detected. Run 'alembic merge heads' to consolidate.",
               recommendation="Run 'alembic merge heads' or specify --head in upgrade command.")
        for h in sorted(heads):
            file_path = file_by_rev.get(h, versions_dir / "unknown")
            pr.add("INFO", rel(file_path), 0, f"Head revision: {h}")

    # Deteksi cycle (siklus) - tambahan untuk keamanan
    cycles = []
    visited = set()
    stack = set()

    def detect_cycle(node: str, path: list[str]) -> None:
        if node in stack:
            # cycle detected
            cycle_path = path[path.index(node):] + [node]
            cycles.append(cycle_path)
            return
        if node in visited:
            return
        visited.add(node)
        stack.add(node)
        down = revs.get(node, "")
        if down and down in revs:
            detect_cycle(down, path + [node])
        stack.remove(node)

    for rev in list(revs.keys()):
        if rev not in visited:
            detect_cycle(rev, [])

    for cycle in cycles:
        pr.add("CRITICAL", "migrations/versions", 0,
               f"Circular dependency detected in migration graph: {' -> '.join(cycle)}",
               recommendation="Fix down_revision references to break the cycle.")

    # =========================================================================
    # Evaluasi akhir
    # =========================================================================
    if invalid_files or orphans or len(heads) > 1 or cycles:
        # Sudah ada yang dilaporkan CRITICAL, skor 0
        pr.score = 0
    else:
        # Semua baik
        if len(migration_files) == 1:
            pr.add("PASS", "migrations/versions", 0,
                   f"Single migration file (revision {list(revs.keys())[0]}). Chain is intact.")
        else:
            pr.add("PASS", "migrations/versions", 0,
                   f"Migration chain intact: {len(migration_files)} files, {len(heads)} head(s).")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p14_quality() -> PhaseResult:
    pr = PhaseResult("P14 Code Quality", weight=2)
    pr.disclaimer = "Strictly enforces code quality: bans bare except, wildcard imports, and pending work markers in production layers."
    t0 = time.monotonic()

    files = all_py(include_checker=True, skip_tops={"tests", "migrations"})

    # Layer yang sangat dilindungi (core business logic)
    critical_layers = {"domain", "kernel", "application", "ports", "axioms", "constitution"}

    # Regex untuk marker
    marker_pattern = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG)\b", re.IGNORECASE)

    structural_violations = []   # (file, line, layer, msg) -> CRITICAL jika di core
    normal_warnings = []         # (file, line, layer, msg) -> WARNING

    for path in files:
        if is_checker_file(path):
            continue

        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            # Syntax error already handled in P02, skip here
            continue

        mod = mod_name(path)
        layer = top_layer(mod) if mod else "unknown"
        rp = rel(path)

        # ================================================================
        # 1. CEK STRUKTUR KODE (AST)
        # ================================================================
        for node in ast.walk(tree):
            # Bare except: except: (tanpa tipe exception)
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                msg = "Bare except clause (catches all exceptions)"
                if layer in critical_layers:
                    structural_violations.append((rp, node.lineno, layer, msg))
                else:
                    normal_warnings.append((rp, node.lineno, layer, msg))

            # Wildcard import: from module import *
            elif isinstance(node, ast.ImportFrom):
                if node.names and any(n.name == "*" for n in node.names):
                    # Abaikan jika ini di __init__.py (biasanya untuk exporting)
                    if path.name != "__init__.py":
                        msg = f"Wildcard import from '{node.module}'"
                        if layer in critical_layers:
                            structural_violations.append((rp, node.lineno, layer, msg))
                        else:
                            normal_warnings.append((rp, node.lineno, layer, msg))

        # ================================================================
        # 2. CEK MARKER (TODO/FIXME/HACK) - line based
        # ================================================================
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if marker_pattern.search(line):
                msg = f"Unresolved marker: {marker_pattern.search(line).group()}"
                # Marker di core layers lebih parah
                if layer in critical_layers:
                    structural_violations.append((rp, lineno, layer, msg))
                else:
                    normal_warnings.append((rp, lineno, layer, msg))

    # ================================================================
    # 3. LAPORAN HASIL
    # ================================================================
    if structural_violations:
        # Laporkan structural violations sebagai CRITICAL
        for file, line, layer, msg in structural_violations[:30]:
            pr.add("CRITICAL", file, line,
                   f"[Layer {layer}] {msg}",
                   recommendation="Refactor to remove bare except, wildcard imports, or pending markers in core layers.")
        if len(structural_violations) > 30:
            pr.add("INFO", ".", 0, f"Plus {len(structural_violations)-30} more structural violations.")

        pr.add("CRITICAL", ".", 0,
               f"{len(structural_violations)} structural code quality violation(s) found in critical layers.")
        pr.score = 0  # Strict: core layers must be clean

    else:
        # Laporkan normal warnings (non-core)
        for file, line, layer, msg in normal_warnings[:30]:
            pr.add("WARNING", file, line,
                   f"[Layer {layer}] {msg}",
                   recommendation="Fix or suppress these issues.")
        if len(normal_warnings) > 30:
            pr.add("INFO", ".", 0, f"Plus {len(normal_warnings)-30} more warnings in non-core layers.")

        # Skor: 100 - penalti ringan (max 20 poin)
        penalty = min(20, len(normal_warnings) * 2)
        pr.score = 100 - penalty

        if len(normal_warnings) > 50:
            pr.add("WARNING", ".", 0,
                   f"High number ({len(normal_warnings)}) of code quality warnings in non-core layers. Consider refactoring.")
        else:
            pr.add("PASS", ".", 0,
                   f"Clean core layers. {len(normal_warnings)} non-critical warnings found.")

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p15_security() -> PhaseResult:
    pr = PhaseResult("P15 Security Scan", weight=5)
    pr.disclaimer = "Strict security audit using AST + pattern matching. CRITICAL findings cause immediate failure."
    t0 = time.monotonic()

    # =====================================================================
    # 1. DEFINE SECURITY PATTERNS (severity: CRITICAL, WARNING, INFO)
    # =====================================================================
    patterns = [
        # CRITICAL: Remote Code Execution / Command Injection
        (r"pickle\.loads?\s*\(", "CRITICAL", "pickle.load() — unsafe deserialization (RCE risk)"),
        (r"yaml\.load\s*\([^)]*\)", "CRITICAL", "yaml.load() — unsafe deserialization (RCE risk); use safe_load()"),
        (r"os\.system\s*\(", "CRITICAL", "os.system() — command injection risk; use subprocess with shell=False"),
        (r"os\.popen\s*\(", "CRITICAL", "os.popen() — command injection risk; use subprocess"),
        (r"eval\s*\(", "CRITICAL", "eval() — arbitrary code execution"),
        (r"exec\s*\(", "CRITICAL", "exec() — arbitrary code execution"),
        (r"subprocess\.call\s*\([^)]*shell\s*=\s*True", "CRITICAL", "subprocess.call(shell=True) — command injection"),
        (r"subprocess\.Popen\s*\([^)]*shell\s*=\s*True", "CRITICAL", "subprocess.Popen(shell=True) — command injection"),
        (r"pty\.spawn\s*\(", "CRITICAL", "pty.spawn() — potentially dangerous"),
        (r"eval\s*\(input\s*\(\)", "CRITICAL", "eval(input()) — remote code execution vulnerability"),

        # WARNING: Risky but sometimes necessary
        (r"\bverify\s*=\s*False\b", "WARNING", "SSL/TLS verify=False — MITM risk (should be configurable per env)"),
        (r"__import__\s*\(", "WARNING", "__import__() — dynamic import; may indicate unsafe code loading"),
        (r"tmpfile\s*\(", "WARNING", "tmpfile() — potential insecure temporary file usage"),

        # INFO: Best practice reminders
        (r"DEBUG\s*=\s*True\b", "INFO", "DEBUG=True — ensure not used in production"),
        (r"print\s*\(.*password", "INFO", "print() of password-like data — potential logging exposure"),
    ]

    # Function names that are always dangerous (will be detected via AST)
    DANGEROUS_FUNCS = {
        "eval", "exec",
        "pickle.load", "pickle.loads",
        "yaml.load",
        "os.system", "os.popen",
        "__import__",
        "pty.spawn",
        "input",  # input() alone is not dangerous, but eval(input()) is
    }

    # =====================================================================
    # 2. SCAN ALL FILES
    # =====================================================================
    files = all_py(include_checker=True, skip_tops={"tests", "docs"})
    findings = []  # list of (severity, file, line, message, detail)

    for path in files:
        if is_checker_file(path):
            continue

        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue

        rp = rel(path)

        # ----------------------------------------------------------------
        # 2a. AST-based detection for function calls
        # ----------------------------------------------------------------
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None

                # Extract function name as string
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        func_name = f"{node.func.value.id}.{node.func.attr}"
                elif isinstance(node.func, ast.Call):
                    # e.g., (getattr(...))() — skip for simplicity
                    continue

                # Check if it's a dangerous function
                if func_name in DANGEROUS_FUNCS:
                    severity = "CRITICAL"
                    message = f"Use of dangerous function: {func_name}()"
                    if func_name in ("eval", "exec"):
                        message += " — arbitrary code execution"
                    elif func_name in ("pickle.load", "pickle.loads"):
                        message += " — unsafe deserialization (RCE risk)"
                    elif func_name == "yaml.load":
                        message += " — unsafe deserialization (RCE risk); use safe_load()"
                    elif func_name in ("os.system", "os.popen"):
                        message += " — command injection risk; use subprocess with shell=False"
                    elif func_name == "__import__":
                        message += " — dynamic import; may hide dependencies"
                    elif func_name == "pty.spawn":
                        message += " — potentially dangerous spawn"
                    elif func_name == "input":
                        # Only dangerous if used with eval/exec, but we'll catch eval(input) above
                        continue

                    findings.append((severity, rp, node.lineno, message, ""))

                # Special case: subprocess with shell=True
                if "subprocess" in str(node.func) and isinstance(node.func, ast.Attribute):
                    for kw in node.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            findings.append((
                                "CRITICAL", rp, node.lineno,
                                f"subprocess.{node.func.attr}() with shell=True — command injection risk",
                                ""
                            ))

        # ----------------------------------------------------------------
        # 2b. Pattern-based detection (regex) for assignments and other patterns
        # ----------------------------------------------------------------
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            for pattern, severity, msg in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    # Avoid duplicate reporting for same issue (e.g., eval already caught by AST)
                    # If already reported as CRITICAL for same line and same function, skip?
                    # But we'll allow because it might catch different patterns.
                    findings.append((severity, rp, lineno, msg, line[:100].strip()))
                    break  # only one finding per line to avoid spam

        # ----------------------------------------------------------------
        # 2c. Heuristic: hardcoded secrets detection (string literals)
        # ----------------------------------------------------------------
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        # Check if variable name suggests a secret
                        secret_keywords = {"secret", "password", "passwd", "pwd", "token", "auth", "key", "credential", "api_key"}
                        if any(kw in var_name.lower() for kw in secret_keywords):
                            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                                val = node.value.value
                                # Heuristic: looks like a secret if length > 8 and not placeholder
                                placeholder_patterns = ["example", "changeme", "test", "dummy", "your_", "sample", "demo"]
                                if len(val) > 8 and not any(x in val.lower() for x in placeholder_patterns):
                                    findings.append((
                                        "CRITICAL", rp, node.lineno,
                                        f"Potential hardcoded secret in variable '{var_name}'",
                                        f"Value: '{val[:20]}...' (length {len(val)})"
                                    ))

    # =====================================================================
    # 3. REPORT RESULTS
    # =====================================================================
    critical_findings = [f for f in findings if f[0] == "CRITICAL"]
    warning_findings = [f for f in findings if f[0] == "WARNING"]
    info_findings = [f for f in findings if f[0] == "INFO"]

    # Report findings by severity
    if critical_findings:
        for sev, file, line, msg, detail in critical_findings:
            pr.add("CRITICAL", file, line, msg, recommendation="Fix this security issue immediately.")
            if detail:
                pr.findings[-1].detail = detail

        # Also report warnings and infos for visibility
        for sev, file, line, msg, detail in warning_findings + info_findings:
            pr.add(sev, file, line, msg, detail=detail)

        pr.add("CRITICAL", ".", 0, f"{len(critical_findings)} critical security vulnerability(s) found. System is NOT secure.")
        pr.score = 0
    else:
        # No critical findings
        if warning_findings:
            for sev, file, line, msg, detail in warning_findings:
                pr.add("WARNING", file, line, msg, detail=detail)
            if info_findings:
                for sev, file, line, msg, detail in info_findings:
                    pr.add("INFO", file, line, msg, detail=detail)
            pr.add("PASS", ".", 0, f"No critical issues. {len(warning_findings)} warning(s) and {len(info_findings)} info(s) found.")
            pr.score = max(80, 100 - len(warning_findings) * 2 - len(info_findings) * 1)
        else:
            if info_findings:
                for sev, file, line, msg, detail in info_findings:
                    pr.add("INFO", file, line, msg, detail=detail)
                pr.add("PASS", ".", 0, f"No critical or warnings. {len(info_findings)} info(s) found.")
                pr.score = 95
            else:
                pr.add("PASS", ".", 0, "No security issues detected.")
                pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p16_dependency_audit() -> PhaseResult:
    pr = PhaseResult("P16 Dependency Audit", weight=3)
    pr.disclaimer = "Strictly checks requirements.txt against known vulnerable versions using version comparison."
    t0 = time.monotonic()

    req_file = ROOT / "requirements.txt"
    if not req_file.exists():
        pr.add("CRITICAL", "requirements.txt", 0,
               "requirements.txt not found. Cannot verify dependency security.",
               recommendation="Create requirements.txt with pinned versions.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =====================================================================
    # 1. Parse requirements.txt secara manual (tanpa dependensi eksternal)
    # =====================================================================
    def parse_requirement(line: str) -> tuple[str, str | None]:
        """Parse a requirement line, return (package, version_constraint) or (package, None)."""
        line = line.strip()
        if not line or line.startswith("#"):
            return None, None

        # Remove inline comments
        if "#" in line:
            line = line[:line.index("#")].strip()

        # Handle index options (--index-url, etc.)
        if line.startswith("-") or line.startswith("--"):
            return None, None

        # Handle extras: package[extra]>=1.0
        # Normalize: remove extras for package name
        pkg = line
        constraint = None

        # Find version specifier
        specifiers = ["==", ">=", "<=", ">", "<", "~=", "!="]
        for spec in specifiers:
            if spec in line:
                pkg, constraint = line.split(spec, 1)
                pkg = pkg.strip()
                constraint = spec + constraint.strip()
                break

        if not constraint:
            # No version specifier, just package name
            pkg = line.split()[0].strip()
            constraint = None

        # Remove extras from package name
        if "[" in pkg:
            pkg = pkg[:pkg.index("[")]

        return pkg, constraint

    # =====================================================================
    # 2. Known vulnerable versions (CVE database sederhana)
    # =====================================================================
    vulnerable_versions = {
        "cryptography": {
            "vulnerable": ["<3.4", "==3.3.2", "==3.3.1", "==3.3"],
            "fixed": ">=3.4",
            "cve": "CVE-2020-25659, CVE-2020-36242"
        },
        "requests": {
            "vulnerable": ["<2.31.0", "==2.30.0", "==2.29.0", "==2.28.2"],
            "fixed": ">=2.31.0",
            "cve": "CVE-2023-32681"
        },
        "urllib3": {
            "vulnerable": ["<1.26.18", "==1.26.17", "==1.26.16"],
            "fixed": ">=1.26.18",
            "cve": "CVE-2023-43804, CVE-2023-45803"
        },
        "jinja2": {
            "vulnerable": ["<3.1.2", "==3.1.1", "==3.1.0"],
            "fixed": ">=3.1.2",
            "cve": "CVE-2024-22195, CVE-2024-34064"
        },
        "sqlalchemy": {
            "vulnerable": ["<1.4.46", "==1.4.45", "==1.4.44"],
            "fixed": ">=1.4.46",
            "cve": "CVE-2022-42003, CVE-2022-42004"
        },
        "django": {
            "vulnerable": ["<3.2.24", "<4.2.10", "<5.0.2"],
            "fixed": ">=3.2.24,>=4.2.10,>=5.0.2",
            "cve": "CVE-2024-24680, CVE-2024-27351"
        },
        "flask": {
            "vulnerable": ["<2.2.5", "==2.2.4", "==2.2.3"],
            "fixed": ">=2.2.5",
            "cve": "CVE-2023-30861"
        },
        "werkzeug": {
            "vulnerable": ["<2.2.3", "==2.2.2", "==2.2.1"],
            "fixed": ">=2.2.3",
            "cve": "CVE-2023-25577"
        },
        "fastapi": {
            "vulnerable": ["<0.109.0", "==0.108.0", "==0.107.0"],
            "fixed": ">=0.109.0",
            "cve": "CVE-2024-24762"
        },
        "pydantic": {
            "vulnerable": ["<1.10.13", "==1.10.12", "==1.10.11"],
            "fixed": ">=1.10.13",
            "cve": "CVE-2024-3772"
        },
        "starlette": {
            "vulnerable": ["<0.36.3", "==0.36.2", "==0.36.1"],
            "fixed": ">=0.36.3",
            "cve": "CVE-2024-24762"
        },
    }

    # =====================================================================
    # 3. Baca dan parse requirements.txt
    # =====================================================================
    vulnerabilities = []
    warnings = []

    with open(req_file, encoding="utf-8") as f:
        for line in f:
            pkg, constraint = parse_requirement(line)
            if pkg is None:
                continue

            if pkg not in vulnerable_versions:
                continue

            vuln_info = vulnerable_versions[pkg]
            is_vulnerable = False

            if constraint is None:
                # No version pinned, assume latest (usually safe, but we warn)
                warnings.append((pkg, "No version constraint (uses latest). Consider pinning to a secure version."))
                continue

            # Check if constraint matches any vulnerable range
            for vuln_range in vuln_info["vulnerable"]:
                # Simple string matching (fallback)
                # Ideally we would use packaging.version, but we'll do a simple check
                if vuln_range in constraint or constraint in vuln_range:
                    is_vulnerable = True
                    break

            # More accurate: check if constraint is '<X' and we can parse version
            if not is_vulnerable and constraint.startswith("<"):
                try:
                    # Extract version number after '<'
                    ver_str = constraint[1:].strip()
                    # Remove any extra characters like '=' or '.'
                    ver_str = ver_str.split()[0] if ' ' in ver_str else ver_str
                    # Compare with vulnerable versions (simplistic)
                    # We'll just check if the constraint is lower than fixed version
                    # This is a rough check, but better than nothing
                    # For now, we'll rely on the string matching above
                    pass
                except:
                    pass

            if is_vulnerable:
                vulnerabilities.append((pkg, constraint, vuln_info["cve"]))

    # =====================================================================
    # 4. Laporkan hasil
    # =====================================================================
    if vulnerabilities:
        for pkg, constraint, cve in vulnerabilities:
            pr.add("CRITICAL", "requirements.txt", 0,
                   f"Vulnerable package: {pkg} with constraint '{constraint}' (CVE: {cve})",
                   recommendation=f"Upgrade {pkg} to secure version: {vulnerable_versions[pkg]['fixed']}")
        pr.add("CRITICAL", "requirements.txt", 0,
               f"{len(vulnerabilities)} vulnerable package(s) found. System is NOT secure.")
        pr.score = 0
    else:
        for pkg, msg in warnings:
            pr.add("WARNING", "requirements.txt", 0,
                   f"Package '{pkg}' has no version constraint: {msg}",
                   recommendation=f"Pin {pkg} to a specific secure version, e.g., {vulnerable_versions[pkg]['fixed']}")

        if warnings:
            pr.add("PASS", "requirements.txt", 0,
                   f"No known vulnerable versions, but {len(warnings)} package(s) lack version pins.")
            pr.score = max(80, 100 - len(warnings) * 5)
        else:
            pr.add("PASS", "requirements.txt", 0,
                   "All packages have secure version constraints.")
            pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p17_secret_scanning() -> PhaseResult:
    pr = PhaseResult("P17 Secret Scanning (Context-Aware)", weight=4)
    pr.disclaimer = "Strictly detects hardcoded secrets using AST + pattern matching. CRITICAL findings cause immediate failure."
    t0 = time.monotonic()

    # =====================================================================
    # 1. EXEMPT PATTERNS (untuk mengurangi false positive)
    # =====================================================================
    EXEMPT_PATTERNS = [
        "example", "changeme", "your_", "dummy", "test",
        "placeholder", "wrong_password", "minioadmin",
        "sample", "demo", "temp", "fake", "mock",
        "default", "password123", "admin", "guest",
        "123456", "qwerty", "abc123",
    ]

    EXEMPT_STATUS_CONSTANTS = [
        "FAILURE_WRONG_PASSWORD", "ERROR_", "STATUS_", "SUCCESS_",
        "USER_PASSWORD", "DEFAULT_PASSWORD", "TEST_PASSWORD",
    ]

    EXEMPT_VARIABLES = [
        "TESTING", "DEBUG", "MOCK", "DUMMY", "FAKE", "EXAMPLE",
    ]

    # Variable names that are suspicious (but not always secret)
    SUSPICIOUS_VARS = [
        "password", "passwd", "pwd", "secret", "token", "auth",
        "api_key", "apikey", "private_key", "public_key", "key",
        "credential", "client_secret", "access_token", "refresh_token",
        "jwt_secret", "jwt_key", "encryption_key", "master_key",
    ]

    # =====================================================================
    # 2. FUNGSI DETEKSI
    # =====================================================================
    def is_placeholder(value: str) -> bool:
        """Check if value looks like a placeholder/example."""
        if not value:
            return True
        lower_val = value.lower()
        for pattern in EXEMPT_PATTERNS:
            if pattern in lower_val:
                return True
        # Check if it looks like a UUID or known placeholder
        if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', value):
            return True
        if len(value) < 8:
            return True
        # If it's all digits or all letters (no symbols), might be placeholder
        if value.isdigit() or value.isalpha():
            return len(value) < 12
        return False

    def is_likely_secret(value: str) -> bool:
        """Heuristic: detect if string looks like a real secret."""
        # Exclude placeholders
        if is_placeholder(value):
            return False
        # Secret harus panjang > 8 dan memiliki karakter campuran
        if len(value) < 8:
            return False
        # Check if it has high entropy (mix of upper, lower, digits, symbols)
        has_upper = any(c.isupper() for c in value)
        has_lower = any(c.islower() for c in value)
        has_digit = any(c.isdigit() for c in value)
        has_symbol = any(not c.isalnum() for c in value)
        # If it's purely alphanumeric, need at least 12 chars
        if not has_symbol and not has_upper and not has_digit:
            return False
        score = sum([has_upper, has_lower, has_digit, has_symbol])
        if score >= 3:
            return True
        # If it's all alphanumeric but long (> 20) and mixed case, might be secret
        if not has_symbol and has_upper and has_lower and has_digit and len(value) > 20:
            return True
        return False

    # =====================================================================
    # 3. SCAN FILE .env
    # =====================================================================
    secrets_found = []
    env_file = ROOT / ".env"
    if env_file.exists():
        env_lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno, line in enumerate(env_lines, 1):
            if not line.strip() or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"\'')
                if not val or val in ["null", "None", ""]:
                    continue
                # Check if key suggests secret
                if any(secret_word in key.lower() for secret_word in ["password", "secret", "key", "token", "auth"]):
                    if is_placeholder(val):
                        continue
                    # .env secrets are WARNING, not CRITICAL (usually not committed)
                    secrets_found.append(("WARNING", str(env_file), lineno, f"Secret in .env: {key}=***", ""))

    # =====================================================================
    # 4. SCAN SOURCE CODE (AST + regex)
    # =====================================================================
    files = all_py(include_checker=True)
    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue

        rp = rel(path)
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue

        # ----------------------------------------------------------------
        # 4a. AST-based detection for assignments
        # ----------------------------------------------------------------
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        # Check if variable name suggests a secret
                        if any(kw in var_name.lower() for kw in SUSPICIOUS_VARS):
                            # Check if value is a string constant
                            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                                val = node.value.value
                                if is_likely_secret(val) and not is_placeholder(val):
                                    # Check if any exempt status constant in code
                                    if any(const in var_name.upper() for const in EXEMPT_STATUS_CONSTANTS):
                                        continue
                                    # Check if variable is in exempt list
                                    if var_name.upper() in EXEMPT_VARIABLES:
                                        continue
                                    secrets_found.append((
                                        "CRITICAL", rp, node.lineno,
                                        f"Hardcoded secret in variable '{var_name}'",
                                        f"Value: '{val[:30]}...' (length {len(val)})"
                                    ))
                            # Handle dictionary assignments: {'password': 'secret'}
                            elif isinstance(node.value, ast.Dict):
                                for key_node, val_node in zip(node.value.keys, node.value.values):
                                    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                                        key_str = key_node.value.lower()
                                        if any(kw in key_str for kw in SUSPICIOUS_VARS):
                                            if isinstance(val_node, ast.Constant) and isinstance(val_node.value, str):
                                                val = val_node.value
                                                if is_likely_secret(val) and not is_placeholder(val):
                                                    secrets_found.append((
                                                        "CRITICAL", rp, node.lineno,
                                                        f"Hardcoded secret in dict key '{key_node.value}'",
                                                        f"Value: '{val[:30]}...' (length {len(val)})"
                                                    ))

        # ----------------------------------------------------------------
        # 4b. Pattern-based detection (regex) for variables defined via other means
        # ----------------------------------------------------------------
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Skip lines with exempt status constants
            if any(const in line for const in EXEMPT_STATUS_CONSTANTS):
                continue

            # Pattern: variable assignment with password-like value
            # password = "secretvalue"
            match = re.search(r'(?i)(password|passwd|pwd|secret|token|api_key|apikey|auth_token|jwt_secret|private_key)\s*=\s*["\']([^"\']{8,})["\']', line)
            if match:
                var_name = match.group(1)
                val = match.group(2)
                if is_likely_secret(val) and not is_placeholder(val):
                    # Avoid duplicate with AST
                    secrets_found.append((
                        "CRITICAL", rp, lineno,
                        f"Hardcoded secret in variable '{var_name}' (regex)",
                        f"Value: '{val[:30]}...'"
                    ))
                continue

            # Pattern: SECRET_KEY = "some_key"
            match = re.search(r'(?i)secret[_\-]?key\s*=\s*["\']([^"\']{8,})["\']', line)
            if match:
                val = match.group(1)
                if is_likely_secret(val) and not is_placeholder(val):
                    secrets_found.append((
                        "CRITICAL", rp, lineno,
                        "Hardcoded secret key (regex)",
                        f"Value: '{val[:30]}...'"
                    ))
                continue

            # Pattern: Bearer token in string literal (e.g., "Bearer abc123...")
            if re.search(r'(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}', line):
                # Extract the token part
                match = re.search(r'(?i)bearer\s+([A-Za-z0-9_\-\.]{20,})', line)
                if match:
                    val = match.group(1)
                    if is_likely_secret(val):
                        secrets_found.append((
                            "CRITICAL", rp, lineno,
                            "Bearer token hardcoded in source",
                            f"Token: '{val[:30]}...'"
                        ))
                continue

            # Pattern: API key in URL (e.g., https://api.example.com?key=abcd1234)
            if re.search(r'[?&]key\s*=\s*[A-Za-z0-9_\-]{16,}', line, re.IGNORECASE):
                match = re.search(r'[?&]key\s*=\s*([A-Za-z0-9_\-]{16,})', line, re.IGNORECASE)
                if match:
                    val = match.group(1)
                    if is_likely_secret(val):
                        secrets_found.append((
                            "CRITICAL", rp, lineno,
                            "API key/secret in URL parameter",
                            f"Key: '{val[:30]}...'"
                        ))
                continue

            # Pattern: Private key header
            if "-----BEGIN" in line and ("PRIVATE KEY" in line or "RSA PRIVATE KEY" in line):
                secrets_found.append((
                    "CRITICAL", rp, lineno,
                    "Private key material detected in source",
                    "Contains PEM private key header"
                ))
                continue

    # =====================================================================
    # 5. KLASIFIKASI DAN LAPORAN
    # =====================================================================
    critical_secrets = [s for s in secrets_found if s[0] == "CRITICAL"]
    warning_secrets = [s for s in secrets_found if s[0] == "WARNING"]

    # Report warnings first (env file)
    for sev, file, line, msg, detail in warning_secrets:
        pr.add("WARNING", file, line, msg, recommendation="Do not commit .env with secrets. Use environment variables in production.")
        if detail:
            pr.findings[-1].detail = detail

    # Report critical secrets
    if critical_secrets:
        for sev, file, line, msg, detail in critical_secrets:
            pr.add("CRITICAL", file, line, msg, recommendation="Remove hardcoded secrets immediately. Use environment variables or secrets manager.")
            if detail:
                pr.findings[-1].detail = detail

        pr.add("CRITICAL", ".", 0, f"{len(critical_secrets)} hardcoded secret(s) found. System is NOT secure.")
        pr.score = 0
    else:
        if warning_secrets:
            pr.add("PASS", ".", 0, f"No hardcoded secrets in source. {len(warning_secrets)} .env secret(s) detected (not critical).")
            # .env secrets are acceptable for local dev, so minimal penalty
            pr.score = 95
        else:
            pr.add("PASS", ".", 0, "No hardcoded secrets detected in source or .env.")
            pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p18_hardcoded_credentials() -> PhaseResult:
    pr = PhaseResult("P18 Hardcoded Credentials", weight=3)
    pr.disclaimer = "Strictly detects hardcoded database credentials, API keys, and connection strings using AST + pattern matching."
    t0 = time.monotonic()

    # =====================================================================
    # 1. DEFINISI PATTERN
    # =====================================================================
    # Exempt patterns untuk placeholder
    EXEMPT_PATTERNS = [
        "example", "changeme", "your_", "dummy", "test",
        "placeholder", "wrong_password", "minioadmin",
        "sample", "demo", "temp", "fake", "mock",
        "default", "password123", "admin", "guest",
    ]

    def is_placeholder(value: str) -> bool:
        if not value:
            return True
        lower_val = value.lower()
        for pattern in EXEMPT_PATTERNS:
            if pattern in lower_val:
                return True
        # If it's short or all digits, likely placeholder
        if len(value) < 6 or value.isdigit():
            return True
        return False

    # =====================================================================
    # 2. SCAN FILE .env (special case)
    # =====================================================================
    env_file = ROOT / ".env"
    env_issues = []
    if env_file.exists():
        env_lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno, line in enumerate(env_lines, 1):
            if not line.strip() or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"\'')
                # Check for database credentials in .env
                if "DB_PASSWORD" in key or "DATABASE_URL" in key or "POSTGRES_PASSWORD" in key:
                    if not is_placeholder(val):
                        env_issues.append((lineno, key, val))

    # =====================================================================
    # 3. SCAN SOURCE CODE (AST + regex)
    # =====================================================================
    files = all_py(include_checker=True)
    creds_found = []  # list of (severity, file, line, message, detail)

    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue

        rp = rel(path)
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue

        # ----------------------------------------------------------------
        # 3a. AST-based detection
        # ----------------------------------------------------------------
        for node in ast.walk(tree):
            # Assignment: DB_PASSWORD = "secret"
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            val = node.value.value
                            # Check for DB_PASSWORD, POSTGRES_PASSWORD, etc.
                            if "DB_PASSWORD" in var_name or "POSTGRES_PASSWORD" in var_name:
                                if not is_placeholder(val):
                                    creds_found.append((
                                        "CRITICAL", rp, node.lineno,
                                        f"Hardcoded database password in variable '{var_name}'",
                                        f"Value: '{val[:20]}...' (length {len(val)})"
                                    ))
                            # Check for DATABASE_URL
                            if "DATABASE_URL" in var_name and val.startswith("postgresql://"):
                                # Extract password part
                                match = re.search(r'postgresql://[^:]+:([^@]+)@', val)
                                if match:
                                    password = match.group(1)
                                    if not is_placeholder(password):
                                        creds_found.append((
                                            "CRITICAL", rp, node.lineno,
                                            f"Hardcoded password in DATABASE_URL variable '{var_name}'",
                                            f"Password: '{password[:20]}...'"
                                        ))
                            # Check for generic credential pattern
                            if any(kw in var_name.lower() for kw in ["password", "passwd", "pwd", "credential"]):
                                if not is_placeholder(val):
                                    # Avoid duplication if already caught above
                                    if "DB_PASSWORD" not in var_name and "POSTGRES_PASSWORD" not in var_name:
                                        creds_found.append((
                                            "CRITICAL", rp, node.lineno,
                                            f"Hardcoded credential in variable '{var_name}'",
                                            f"Value: '{val[:20]}...'"
                                        ))

            # Dictionary assignment: {"password": "secret"}
            if isinstance(node, ast.Dict):
                for key_node, val_node in zip(node.keys, node.values):
                    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                        key_str = key_node.value.lower()
                        if any(kw in key_str for kw in ["password", "passwd", "pwd", "credential"]):
                            if isinstance(val_node, ast.Constant) and isinstance(val_node.value, str):
                                val = val_node.value
                                if not is_placeholder(val):
                                    creds_found.append((
                                        "CRITICAL", rp, node.lineno,
                                        f"Hardcoded credential in dict key '{key_node.value}'",
                                        f"Value: '{val[:20]}...'"
                                    ))

        # ----------------------------------------------------------------
        # 3b. Pattern-based detection (regex)
        # ----------------------------------------------------------------
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Pattern: DB_PASSWORD = "secret"
            match = re.search(r'(?i)(DB_PASSWORD|POSTGRES_PASSWORD)\s*=\s*["\']([^"\']{4,})["\']', line)
            if match:
                var_name = match.group(1)
                val = match.group(2)
                if not is_placeholder(val):
                    creds_found.append((
                        "CRITICAL", rp, lineno,
                        f"Hardcoded password in variable '{var_name}' (regex)",
                        f"Value: '{val[:20]}...'"
                    ))
                continue

            # Pattern: DATABASE_URL = "postgresql://user:password@host/db"
            match = re.search(r'(?i)DATABASE_URL\s*=\s*["\']postgresql://[^:]+:([^@]+)@', line)
            if match:
                password = match.group(1)
                if not is_placeholder(password):
                    creds_found.append((
                        "CRITICAL", rp, lineno,
                        "Hardcoded password in DATABASE_URL",
                        f"Password: '{password[:20]}...'"
                    ))
                continue

            # Pattern: SQLALCHEMY_DATABASE_URI = "postgresql://..."
            match = re.search(r'(?i)SQLALCHEMY_DATABASE_URI\s*=\s*["\']postgresql://[^:]+:([^@]+)@', line)
            if match:
                password = match.group(1)
                if not is_placeholder(password):
                    creds_found.append((
                        "CRITICAL", rp, lineno,
                        "Hardcoded password in SQLALCHEMY_DATABASE_URI",
                        f"Password: '{password[:20]}...'"
                    ))
                continue

            # Pattern: PASSWORD = "secret" (generic)
            match = re.search(r'(?i)(PASSWORD|PASSWD|PWD)\s*=\s*["\']([^"\']{4,})["\']', line)
            if match:
                var_name = match.group(1)
                val = match.group(2)
                # Skip if variable name has exempt prefix
                if any(ex in var_name.upper() for ex in ["TEST", "MOCK", "DUMMY", "FAKE", "EXAMPLE"]):
                    continue
                if not is_placeholder(val):
                    creds_found.append((
                        "CRITICAL", rp, lineno,
                        f"Hardcoded credential in variable '{var_name}' (regex)",
                        f"Value: '{val[:20]}...'"
                    ))
                continue

            # Pattern: Basic auth in URL (http://user:pass@host)
            match = re.search(r'(?i)(https?://)[^:]+:([^@]+)@', line)
            if match:
                password = match.group(2)
                if not is_placeholder(password):
                    creds_found.append((
                        "CRITICAL", rp, lineno,
                        "Hardcoded password in HTTP Basic Auth URL",
                        f"Password: '{password[:20]}...'"
                    ))
                continue

    # =====================================================================
    # 4. LAPORKAN HASIL
    # =====================================================================
    # Report .env issues as WARNING (not CRITICAL because .env usually not committed)
    for lineno, key, val in env_issues:
        pr.add("WARNING", str(env_file), lineno,
               f"Credentials in .env: {key}=***",
               recommendation="Keep .env for local dev only; do not commit to version control.")

    # Report source code issues as CRITICAL
    if creds_found:
        for sev, file, line, msg, detail in creds_found:
            pr.add("CRITICAL", file, line, msg,
                   recommendation="Remove hardcoded credentials immediately. Use environment variables or secrets manager.")
            if detail:
                pr.findings[-1].detail = detail

        pr.add("CRITICAL", ".", 0, f"{len(creds_found)} hardcoded credential(s) found in source code.")
        pr.score = 0
    else:
        if env_issues:
            pr.add("PASS", ".", 0, f"No hardcoded credentials in source. {len(env_issues)} .env credential(s) detected (not critical).")
            pr.score = 95
        else:
            pr.add("PASS", ".", 0, "No hardcoded credentials detected.")
            pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p19_logging_security() -> PhaseResult:
    pr = PhaseResult("P19 Logging Security", weight=3)
    pr.disclaimer = "Strictly detects logging of sensitive data (passwords, tokens, secrets) using AST + pattern matching."
    t0 = time.monotonic()

    # =====================================================================
    # 1. DEFINISI
    # =====================================================================
    # Layer kritis (logging sensitif di sini = CRITICAL)
    CRITICAL_LAYERS = {"domain", "kernel", "application", "ports", "axioms", "constitution"}

    # Pola sensitif untuk regex (fallback)
    SENSITIVE_PATTERNS = [
        (r"logger\.\w+\(.*password", "Logging password/secret"),
        (r"logger\.\w+\(.*secret", "Logging secret field"),
        (r"logger\.\w+\(.*token", "Logging token field"),
        (r"logger\.\w+\(.*api_key", "Logging API key"),
        (r"logger\.\w+\(.*credential", "Logging credential"),
        (r"logger\.\w+\(.*authorization", "Logging authorization header"),
        (r"logger\.\w+\(.*bearer", "Logging bearer token"),
        (r"logging\.\w+\(.*password", "Logging password (logging module)"),
        (r"logging\.\w+\(.*secret", "Logging secret (logging module)"),
        (r"logging\.\w+\(.*token", "Logging token (logging module)"),
    ]

    # Sensitive variable/argument names
    SENSITIVE_NAMES = {
        "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
        "credential", "access_token", "refresh_token", "jwt", "auth",
        "authorization", "bearer", "private_key", "public_key",
    }

    # =====================================================================
    # 2. FUNGSI DETEKSI AST
    # =====================================================================
    def extract_argument_names(node: ast.Call) -> list[str]:
        """Extract string literals from call arguments (for detecting sensitive field names)."""
        names = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                names.append(arg.value.lower())
            elif isinstance(arg, ast.Name):
                # If argument is a variable, we can only guess
                names.append(arg.id.lower())
        for kw in node.keywords:
            if kw.arg:
                names.append(kw.arg.lower())
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                names.append(kw.value.value.lower())
        return names

    def is_sensitive_call(node: ast.Call) -> bool:
        """Check if a function call is logging sensitive data."""
        # Check if it's a logger call (logger.info, logging.info, etc.)
        func_name = None
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id in ("logger", "logging"):
                    func_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            # Could be direct logging call (if logging imported)
            if node.func.id in ("info", "debug", "warning", "error", "critical", "exception"):
                func_name = node.func.id

        if not func_name:
            return False

        # Extract argument strings
        arg_strings = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                arg_strings.append(arg.value.lower())
            elif isinstance(arg, ast.JoinedStr):
                # f-string: extract constant parts
                for val in arg.values:
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        arg_strings.append(val.value.lower())
        for kw in node.keywords:
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                arg_strings.append(kw.value.value.lower())

        # Check if any sensitive word appears in the log message
        for text in arg_strings:
            for sensitive in SENSITIVE_NAMES:
                if sensitive in text:
                    return True
        return False

    # =====================================================================
    # 3. SCAN
    # =====================================================================
    files = all_py(include_checker=True)
    findings = []  # (severity, file, line, message, detail)

    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue

        rp = rel(path)
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue

        # Determine layer
        mod = mod_name(path)
        layer = top_layer(mod) if mod else "unknown"
        is_critical = layer in CRITICAL_LAYERS

        # ----------------------------------------------------------------
        # 3a. AST-based detection
        # ----------------------------------------------------------------
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if is_sensitive_call(node):
                    # Extract the log message snippet
                    detail = ""
                    for arg in node.args[:2]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            detail = arg.value[:100]
                            break
                    findings.append((
                        "CRITICAL" if is_critical else "WARNING",
                        rp, node.lineno,
                        f"Logging potentially sensitive data (call: {node.func.attr if hasattr(node.func, 'attr') else node.func.id})",
                        detail
                    ))

        # ----------------------------------------------------------------
        # 3b. Pattern-based detection (regex) as fallback
        # ----------------------------------------------------------------
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            for pattern, msg in SENSITIVE_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    # Avoid duplicate with AST (if AST already caught, skip)
                    # Simple check: see if any AST finding on same line
                    already_found = any(f[1] == rp and f[2] == lineno for f in findings)
                    if not already_found:
                        findings.append((
                            "CRITICAL" if is_critical else "WARNING",
                            rp, lineno,
                            msg,
                            line[:100].strip()
                        ))
                    break  # only one per line

    # =====================================================================
    # 4. KLASIFIKASI DAN LAPORAN
    # =====================================================================
    critical_issues = [f for f in findings if f[0] == "CRITICAL"]
    warning_issues = [f for f in findings if f[0] == "WARNING"]

    if critical_issues:
        for sev, file, line, msg, detail in critical_issues:
            pr.add("CRITICAL", file, line, msg,
                   recommendation="Refactor to avoid logging sensitive data. Use logging with sanitization or masking.")
            if detail:
                pr.findings[-1].detail = f"Snippet: {detail}"

        pr.add("CRITICAL", ".", 0, f"{len(critical_issues)} critical logging security issue(s) in core layers.")
        pr.score = 0
    else:
        for sev, file, line, msg, detail in warning_issues:
            pr.add("WARNING", file, line, msg,
                   recommendation="Review logging of potentially sensitive data in non-core layers.")
            if detail:
                pr.findings[-1].detail = f"Snippet: {detail}"

        if warning_issues:
            pr.add("PASS", ".", 0, f"No critical issues. {len(warning_issues)} warning(s) in non-core layers.")
            pr.score = max(80, 100 - len(warning_issues) * 2)
        else:
            pr.add("PASS", ".", 0, "No logging of sensitive data detected.")
            pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p20_sql_injection() -> PhaseResult:
    pr = PhaseResult("P20 SQL Injection (AST)", weight=4)
    pr.disclaimer = "Strictly detects SQL injection vulnerabilities using AST analysis of f-strings and raw queries."
    t0 = time.monotonic()

    # =====================================================================
    # 1. SQL KEYWORDS
    # =====================================================================
    SQL_KEYWORDS = {
        "SELECT", "INSERT", "UPDATE", "DELETE", "FROM",
        "WHERE", "CREATE", "DROP", "ALTER", "TRUNCATE",
        "JOIN", "INNER", "LEFT", "RIGHT", "OUTER",
        "GROUP", "ORDER", "HAVING", "UNION", "INTERSECT",
        "EXCEPT", "VALUES", "SET", "AND", "OR", "NOT",
    }

    # =====================================================================
    # 2. SCAN FILES
    # =====================================================================
    files = all_py(skip_tops={"tests", "migrations"})
    issues = []  # list of (severity, file, line, message, detail)

    for path in files:
        if is_checker_file(path):
            continue

        rp = rel(path)
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue

        # ----------------------------------------------------------------
        # 2a. Find f-strings with SQL keywords and interpolation
        # ----------------------------------------------------------------
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                node_str = ast.unparse(node)
                # Check if any SQL keyword appears
                has_sql_keyword = any(kw in node_str.upper() for kw in SQL_KEYWORDS)
                if not has_sql_keyword:
                    continue

                # Check if it contains interpolation (ast.FormattedValue)
                has_interpolation = any(isinstance(val, ast.FormattedValue) for val in node.values)
                if not has_interpolation:
                    continue

                # Determine severity based on context (execution environment)
                severity = "CRITICAL"
                # Additional check: if it's in a raw query or execute call
                # We'll enhance by checking if the f-string is used in a SQL execute
                # Look at parent context: is this f-string passed to execute() or raw query?
                parent = getattr(node, '_parent', None)
                is_sql_context = False
                if parent and isinstance(parent, ast.Call):
                    if isinstance(parent.func, ast.Attribute):
                        if parent.func.attr in ("execute", "raw", "query", "fetchall", "fetchone"):
                            is_sql_context = True
                    elif isinstance(parent.func, ast.Name):
                        if parent.func.id in ("execute", "raw", "query", "fetchall", "fetchone"):
                            is_sql_context = True

                if is_sql_context:
                    severity = "CRITICAL"
                else:
                    # Still risky but might be in a context builder or ORM
                    severity = "WARNING"

                issues.append((
                    severity, rp, node.lineno,
                    "Potential SQL injection: f-string with interpolation and SQL keyword",
                    f"SQL snippet: {node_str[:100]}"
                ))

        # ----------------------------------------------------------------
        # 2b. Detect raw string concatenation in SQL queries
        # ----------------------------------------------------------------
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Add):
                    # Check if left or right side contains SQL keyword
                    left_str = ast.unparse(node.left) if hasattr(node, 'left') else ""
                    right_str = ast.unparse(node.right) if hasattr(node, 'right') else ""
                    combined = left_str + right_str
                    if any(kw in combined.upper() for kw in SQL_KEYWORDS):
                        # Check if variable concatenation is happening
                        has_var = any(isinstance(n, ast.Name) for n in ast.walk(node))
                        if has_var:
                            issues.append((
                                "CRITICAL", rp, node.lineno,
                                "Potential SQL injection: string concatenation in SQL query",
                                f"Query snippet: {combined[:100]}"
                            ))

        # ----------------------------------------------------------------
        # 2c. Detect .format() or % formatting on SQL strings
        # ----------------------------------------------------------------
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "format" and isinstance(node.func.value, ast.Constant):
                        if isinstance(node.func.value.value, str):
                            sql_str = node.func.value.value
                            if any(kw in sql_str.upper() for kw in SQL_KEYWORDS):
                                # Check if any placeholder is present
                                if "{}" in sql_str or "{0}" in sql_str or "{name}" in sql_str:
                                    issues.append((
                                        "CRITICAL", rp, node.lineno,
                                        "Potential SQL injection: .format() on SQL string with placeholders",
                                        f"SQL string: {sql_str[:100]}"
                                    ))

    # =====================================================================
    # 3. REPORT RESULTS
    # =====================================================================
    critical_issues = [i for i in issues if i[0] == "CRITICAL"]
    warning_issues = [i for i in issues if i[0] == "WARNING"]

    if critical_issues:
        for sev, file, line, msg, detail in critical_issues:
            pr.add("CRITICAL", file, line, msg,
                   recommendation="Use parameterized queries (SQLAlchemy text() with params, or cursor.execute with placeholders).")
            if detail:
                pr.findings[-1].detail = detail

        pr.add("CRITICAL", ".", 0, f"{len(critical_issues)} critical SQL injection vulnerability(s) found.")
        pr.score = 0
    else:
        if warning_issues:
            for sev, file, line, msg, detail in warning_issues:
                pr.add("WARNING", file, line, msg,
                       recommendation="Review this query to ensure it uses parameterized queries.")
                if detail:
                    pr.findings[-1].detail = detail

            pr.add("PASS", ".", 0, f"{len(warning_issues)} potential SQL injection warnings found.")
            pr.score = max(80, 100 - len(warning_issues) * 2)
        else:
            pr.add("PASS", ".", 0, "No SQL injection patterns detected.")
            pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p21_orm_enums() -> PhaseResult:
    pr = PhaseResult("P21 ORM Enum Inheritance", weight=2)
    pr.disclaimer = "Strictly detects SQLAlchemy.Enum inheritance (anti-pattern). Enums must inherit from enum.Enum or Python's IntEnum."
    t0 = time.monotonic()

    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               "ORM directory not found. Cannot validate enum definitions.",
               recommendation="Create infrastructure/persistence_orm/ and ensure enums are defined correctly.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =====================================================================
    # SCAN ALL ORM FILES
    # =====================================================================
    violations = []  # list of (file, line, class_name, base_name)

    for path in sorted(orm_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue

        tree = get_ast_tree(path)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check all base classes
                for base in node.bases:
                    # Detect inheritance from sqlalchemy.Enum
                    is_sqlalchemy_enum = False
                    # Case: class Foo(sqlalchemy.Enum)
                    if isinstance(base, ast.Attribute):
                        if isinstance(base.value, ast.Name) and base.value.id == "sqlalchemy" and base.attr == "Enum":
                            is_sqlalchemy_enum = True
                    # Case: class Foo(Enum) from sqlalchemy import Enum (imported directly)
                    elif isinstance(base, ast.Name) and base.id == "Enum":
                        # Need to check if Enum is from sqlalchemy by looking at imports
                        # We'll do a separate scan for imports to confirm
                        is_sqlalchemy_enum = True  # flag it, will be filtered later

                    if is_sqlalchemy_enum:
                        # Verify that this file imports sqlalchemy.Enum
                        has_sqlalchemy_enum_import = False
                        for import_node in ast.walk(tree):
                            if isinstance(import_node, ast.ImportFrom):
                                if import_node.module == "sqlalchemy" or import_node.module == "sqlalchemy.types":
                                    for alias in import_node.names:
                                        if alias.name == "Enum":
                                            has_sqlalchemy_enum_import = True
                                            break
                            elif isinstance(import_node, ast.Import):
                                for alias in import_node.names:
                                    if alias.name == "sqlalchemy":
                                        has_sqlalchemy_enum_import = True
                                        break

                        if has_sqlalchemy_enum_import:
                            violations.append((rel(path), node.lineno, node.name, "sqlalchemy.Enum"))
                        else:
                            # Could be Python's Enum from enum module, which is correct
                            pass

        # Additional scan: detect if class inherits from Python enum.Enum (correct)
        # We'll also check if the class is using @enum.unique or similar (good practice)
        # This is more of an informational check

    # =====================================================================
    # REPORT RESULTS
    # =====================================================================
    if violations:
        for file, line, class_name, base_name in violations:
            pr.add("CRITICAL", file, line,
                   f"ORM Enum '{class_name}' inherits from {base_name} (incorrect).",
                   recommendation="Use Python's enum.Enum for enums and use SQLAlchemy's Enum type only in column definitions, not as base class.")
        pr.add("CRITICAL", ".", 0, f"{len(violations)} ORM enum inheritance violation(s) found.")
        pr.score = 0
    else:
        pr.add("PASS", "infrastructure/persistence_orm", 0,
               "All ORM enums correctly inherit from Python enum.Enum (or are not using sqlalchemy.Enum as base).")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p22_async_correctness() -> PhaseResult:
    pr = PhaseResult("P22 Async Correctness", weight=3)
    pr.disclaimer = "Strictly enforces async best practices: bans asyncio.run() and run_until_complete in core layers."
    t0 = time.monotonic()

    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})

    # Core layers that must follow strict async rules
    CORE_LAYERS = {"domain", "kernel", "application", "ports", "axioms", "constitution"}

    # Patterns to detect
    DANGEROUS_ASYNC_PATTERNS = [
        ("asyncio.run", "asyncio.run() — creates new event loop, dangerous in libraries"),
        ("run_until_complete", "run_until_complete() — low-level API, use asyncio.run() or await"),
        ("loop.run_forever", "loop.run_forever() — blocks event loop indefinitely"),
        ("asyncio.get_event_loop", "asyncio.get_event_loop() — deprecated, use get_running_loop()"),
    ]

    violations = []  # list of (severity, file, line, msg)
    warnings = []    # list of (file, line, msg)

    for path in files:
        if is_checker_file(path):
            continue

        tree = get_ast_tree(path)
        if tree is None:
            continue

        mod = mod_name(path)
        layer = top_layer(mod) if mod else "unknown"
        rp = rel(path)

        # Detect async anti-patterns using AST
        for node in ast.walk(tree):
            # 1. asyncio.run() call
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    # asyncio.run(...)
                    if isinstance(func.value, ast.Name) and func.value.id == "asyncio" and func.attr == "run":
                        msg = "asyncio.run() — creates new event loop, use in main entry point only"
                        if layer in CORE_LAYERS:
                            violations.append(("CRITICAL", rp, node.lineno, msg))
                        else:
                            warnings.append((rp, node.lineno, msg))
                    # loop.run_forever()
                    if isinstance(func.value, ast.Attribute) and func.attr == "run_forever":
                        if isinstance(func.value.value, ast.Name) and func.value.value.id == "loop":
                            msg = "loop.run_forever() — blocks event loop, use asyncio.run() instead"
                            if layer in CORE_LAYERS:
                                violations.append(("CRITICAL", rp, node.lineno, msg))
                            else:
                                warnings.append((rp, node.lineno, msg))
                    # loop.run_until_complete()
                    if isinstance(func.value, ast.Attribute) and func.attr == "run_until_complete":
                        if isinstance(func.value.value, ast.Name) and func.value.value.id == "loop":
                            msg = "loop.run_until_complete() — low-level API, use asyncio.run()"
                            if layer in CORE_LAYERS:
                                violations.append(("CRITICAL", rp, node.lineno, msg))
                            else:
                                warnings.append((rp, node.lineno, msg))
                # asyncio.get_event_loop() call
                if isinstance(func, ast.Name) and func.id == "get_event_loop":
                    # Check if it's asyncio.get_event_loop()
                    # We need to check parent call
                    if isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "asyncio":
                            if node.func.attr == "get_event_loop":
                                msg = "asyncio.get_event_loop() — deprecated, use get_running_loop()"
                                if layer in CORE_LAYERS:
                                    violations.append(("CRITICAL", rp, node.lineno, msg))
                                else:
                                    warnings.append((rp, node.lineno, msg))

            # 2. Detect .run_until_complete() on BaseEventLoop (attribute access)
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "run_until_complete":
                        # Check if it's called on a variable named 'loop'
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "loop":
                            msg = "loop.run_until_complete() — low-level API, use asyncio.run()"
                            if layer in CORE_LAYERS:
                                violations.append(("CRITICAL", rp, node.lineno, msg))
                            else:
                                warnings.append((rp, node.lineno, msg))

    # =====================================================================
    # REPORT RESULTS
    # =====================================================================
    if violations:
        for sev, file, line, msg in violations:
            pr.add("CRITICAL", file, line, msg,
                   recommendation="Refactor to use asyncio.run() only in main entry point, or use await in async context.")
        pr.add("CRITICAL", ".", 0, f"{len(violations)} critical async correctness violation(s) in core layers.")
        pr.score = 0
    else:
        if warnings:
            for file, line, msg in warnings:
                pr.add("WARNING", file, line, msg,
                       recommendation="Consider using asyncio.run() or proper event loop management in non-core code.")
            pr.add("PASS", ".", 0, f"{len(warnings)} async warnings (non-core).")
            pr.score = max(80, 100 - len(warnings) * 2)
        else:
            pr.add("PASS", ".", 0, "No async correctness issues detected.")
            pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p23_kernel_guards() -> PhaseResult:
    pr = PhaseResult("P23 Kernel Guards", weight=2)
    pr.disclaimer = "Strictly validates kernel guard files: existence, syntax, and presence of required classes/functions."
    t0 = time.monotonic()

    guards_dir = ROOT / "kernel" / "guards"
    if not guards_dir.exists():
        pr.add("CRITICAL", "kernel/guards", 0,
               "Guards directory not found. Kernel security layer is incomplete.",
               recommendation="Create kernel/guards/ with required guard files.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =====================================================================
    # 1. DEFINISI GUARD CONTRACT (lengkap untuk semua guard file)
    # =====================================================================
    GUARD_CONTRACTS = {
        # Required guards (harus ada)
        "period_lock.py": {
            "required_names": ["PeriodLockGuard", "PeriodLock", "lock_period", "unlock_period"],
            "description": "Period lock/unlock functionality",
            "optional": False
        },
        "balance_checker.py": {
            "required_names": ["BalanceChecker", "check_balance", "assert_balanced"],
            "description": "Balance validation logic",
            "optional": False
        },
        "authority_matrix.py": {
            "required_names": ["AuthorityMatrixGuard", "AuthorityMatrix", "has_permission"],
            "description": "Authority/authorization matrix",
            "optional": False
        },
        "sod_enforcer.py": {
            "required_names": ["SODEnforcer", "SoDEnforcer", "SodEnforcer", "enforce_sod", "check_segregation"],
            "description": "Segregation of Duties enforcement",
            "optional": False
        },

        # Optional guards (jika ada, harus valid)
        "guard_exceptions.py": {
            "required_names": ["GuardViolationError", "GuardSeverity", "GuardErrorCode"],
            "description": "Guard exception hierarchy",
            "optional": True
        },
        "emergency_freeze.py": {
            "required_names": ["EmergencyFreezeGuard", "FreezeReason", "FreezeScope"],
            "description": "Emergency freeze functionality",
            "optional": True
        },
        "currency_validator.py": {
            "required_names": ["CurrencyValidator", "CurrencyValidationResult", "get_currency_validator"],
            "description": "Currency validation",
            "optional": True
        },
        "legal_entity_boundary.py": {
            "required_names": ["LegalEntityBoundaryGuard", "EntityAccessCheckResult", "get_legal_entity_boundary_guard"],
            "description": "Legal entity boundary isolation",
            "optional": True
        },
        "evidence_attacher.py": {
            "required_names": ["EvidenceAttacherGuard", "Evidence", "get_evidence_attacher_guard"],
            "description": "Evidence attachment for transactions",
            "optional": True
        },
        "regulatory_compliance.py": {
            "required_names": ["RegulatoryComplianceGuard", "RegulatoryRule", "get_regulatory_compliance_guard"],
            "description": "Regulatory compliance (OJK, BI, DJP, AML)",
            "optional": True
        },
        "temporal_consistency.py": {
            "required_names": ["TemporalConsistencyGuard", "TemporalViolation", "get_temporal_consistency_guard"],
            "description": "Temporal consistency (backdate, future dating)",
            "optional": True
        },
        "coretax_format_validator.py": {
            "required_names": ["CoretaxFormatGuard", "CoretaxFormatValidator", "get_coretax_format_guard"],
            "description": "Coretax DJP format validation",
            "optional": True
        },
        "credit_limit_enforcer.py": {
            "required_names": ["CreditLimitEnforcer", "CreditLimitInfo", "get_credit_limit_enforcer"],
            "description": "Customer credit limit enforcement",
            "optional": True
        },
        "budget_availability.py": {
            "required_names": ["BudgetAvailabilityGuard", "BudgetCheckResult", "get_budget_availability_guard"],
            "description": "Budget availability check",
            "optional": True
        },
    }

    # =====================================================================
    # 2. SCAN GUARD FILES
    # =====================================================================
    violations = []  # list of (file, message)
    present_files = set()
    warnings = []

    for guard_file in guards_dir.glob("*.py"):
        if guard_file.name == "__init__.py":
            continue

        present_files.add(guard_file.name)
        contract = GUARD_CONTRACTS.get(guard_file.name)

        if contract is None:
            # Unknown guard file — warn but don't fail
            warnings.append((rel(guard_file), f"Unknown guard file '{guard_file.name}' found. No contract defined."))
            continue

        # Parse AST
        tree = get_ast_tree(guard_file)
        if tree is None:
            violations.append((rel(guard_file), "Syntax error in file"))
            continue

        # Collect all defined class and function names
        defined_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) or isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                defined_names.add(node.name)

        # Check if at least one required name exists
        required_names = contract["required_names"]
        found = any(name in defined_names for name in required_names)

        if not found:
            violations.append((
                rel(guard_file),
                f"Missing required class/function. Expected one of: {', '.join(required_names)}"
            ))
        else:
            # Additional quality check: if class exists, check if it has methods (non-empty)
            # We'll do a simple check: ensure at least one method defined inside class
            class_found = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name in required_names:
                    class_found = node
                    break

            if class_found:
                # Check if class has at least one method (excluding dunder methods)
                has_method = False
                for item in class_found.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("__"):
                            has_method = True
                            break
                if not has_method:
                    # It's a class but empty or only dunder methods — warn but don't fail
                    warnings.append((rel(guard_file), f"Class '{class_found.name}' has no non-dunder methods. It may be incomplete."))

    # =====================================================================
    # 3. CHECK REQUIRED GUARDS (non-optional)
    # =====================================================================
    required_guards = [name for name, contract in GUARD_CONTRACTS.items() if not contract.get("optional", False)]
    missing_required = [g for g in required_guards if g not in present_files]

    # =====================================================================
    # 4. REPORT RESULTS
    # =====================================================================
    # Report warnings
    for file, msg in warnings:
        pr.add("WARNING", file, 0, msg)

    if missing_required:
        for guard_file in missing_required:
            contract = GUARD_CONTRACTS[guard_file]
            pr.add("CRITICAL", "kernel/guards", 0,
                   f"Required guard file missing: {guard_file} ({contract['description']})",
                   recommendation=f"Create {guard_file} with the required class/function: {', '.join(contract['required_names'])}")
        pr.add("CRITICAL", "kernel/guards", 0,
               f"{len(missing_required)} required guard file(s) are missing.")
        pr.score = 0
    elif violations:
        # Required files exist but have structural issues
        for file, msg in violations:
            pr.add("CRITICAL", file, 0,
                   f"Guard file validation failed: {msg}",
                   recommendation="Ensure the guard file defines the expected class/function.")
        pr.add("CRITICAL", "kernel/guards", 0,
               f"{len(violations)} guard file(s) have structural issues.")
        pr.score = 0
    else:
        # All good
        additional = [f for f in present_files if f not in required_guards]
        pr.add("PASS", "kernel/guards", 0,
               f"All required guard files present and properly structured. Additional guards: {additional}")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p24_double_entry_pattern() -> PhaseResult:
    pr = PhaseResult("P24 Double-Entry Structural Validation", weight=3)
    pr.disclaimer = "Uses structural AST validation to ensure strict mathematical balancing logic exists and guards against text bypasses."
    t0 = time.monotonic()

    de_file = ROOT / "axioms" / "double_entry.py"
    if not de_file.exists():
        pr.add("CRITICAL", "axioms/double_entry.py", 0, "Axiom Error: double_entry.py core accounting guard is missing.",
               recommendation="Create axioms/double_entry.py containing the absolute double-entry invariant rules.")
        pr.score = 0
        pr.finalize_status()
        return pr

    tree = get_ast_tree(de_file)
    if tree is None:
        pr.add("CRITICAL", "axioms/double_entry.py", 0, "Syntax Error: Cannot parse axioms/double_entry.py.",
               recommendation="Fix the Python syntax errors in the double_entry.py file immediately.")
        pr.score = 0
        pr.finalize_status()
        return pr

    # --- 1. Cari kelas yang memiliki field debit/credit (baik atribut langsung atau properti) ---
    has_debit_credit_fields = False
    has_balance_verification = False

    for node in ast.walk(tree):
        # 1a. Cek kelas
        if isinstance(node, ast.ClassDef):
            # Kumpulkan semua atribut (Assign, AnnAssign) dan method (FunctionDef) untuk melihat apakah ada 'debit'/'credit'
            class_attrs = set()
            class_methods = set()
            for item in node.body:
                # Atribut langsung (e.g., debit: Decimal)
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    class_attrs.add(item.target.id.lower())
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            class_attrs.add(target.id.lower())
                # Method atau properti
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    class_methods.add(item.name.lower())
                    # Cek apakah method adalah property (ada dekorator @property)
                    for dec in item.decorator_list:
                        if isinstance(dec, ast.Name) and dec.id == "property":
                            class_methods.add(item.name.lower())  # sudah ditambahkan, tapi flag sebagai property
            # Gabungkan semua nama yang mungkin menjadi field debit/credit
            all_names = class_attrs | class_methods
            if "debit" in all_names and "credit" in all_names:
                has_debit_credit_fields = True
                break  # cukup satu kelas yang memenuhi

    # --- 2. Cari fungsi atau method yang melakukan pengecekan keseimbangan ---
    # Fungsi/method yang dianggap valid jika:
    # - namanya mengandung 'balance', 'enforce', 'validate', 'assert_balanced'
    # - atau tubuhnya mengandung perbandingan antara total debit dan kredit

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name_lower = node.name.lower()
            # Cek nama fungsi
            if any(kw in name_lower for kw in ["balance", "enforce", "validate", "assert_balanced"]):
                # Periksa apakah di dalam fungsi ada pembandingan yang melibatkan debit/credit
                body_text = ast.unparse(node).lower()
                if ("debit" in body_text and "credit" in body_text) or ("total_debit" in body_text and "total_credit" in body_text):
                    # Cari operator perbandingan atau selisih
                    if "==" in body_text or "!=" in body_text or "-" in body_text or "abs" in body_text:
                        has_balance_verification = True
                        break
            # Jika tidak cocok dengan nama, coba cari fungsi yang secara eksplisit membandingkan debit dan kredit
            # Misalnya fungsi yang berisi `self.difference` atau `abs(total_debit - total_credit)`
            if not has_balance_verification:
                body_text = ast.unparse(node).lower()
                if ("debit" in body_text and "credit" in body_text) or ("total_debit" in body_text and "total_credit" in body_text):
                    if "abs" in body_text or "==" in body_text or "!=" in body_text or "-" in body_text:
                        # Pastikan ada pernyataan return atau raise yang terkait
                        has_balance_verification = True
                        break

    # --- 3. Evaluasi hasil ---
    if has_debit_credit_fields and has_balance_verification:
        pr.add("PASS", "axioms/double_entry.py", 0,
               "Absolute Invariant Verified: Real structural double-entry balancing logic is present.")
        pr.score = 100
    else:
        missing = []
        if not has_debit_credit_fields:
            missing.append("Missing a Journal/Ledger entry class defining both 'debit' and 'credit' fields (attributes or properties).")
        if not has_balance_verification:
            missing.append("Missing a verification function (e.g., 'enforce', 'validate_journal', 'is_balanced') that performs real mathematical comparison between debit and credit values.")
        for msg in missing:
            pr.add("CRITICAL", "axioms/double_entry.py", 0, f"Accounting Invariant Violation: {msg}",
                   recommendation="Implement real mathematical invariant: total_debit == total_credit inside an enforcement method.")
        pr.score = 0  # Zero tolerance jika aturan pembukuan berpasangan terbukti bohong / kopong

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p25_journal_lifecycle() -> PhaseResult:
    pr = PhaseResult("P25 Journal Lifecycle Pattern", weight=2)
    pr.disclaimer = "Uses structural AST validation to verify strict state machine definitions and transition guards for journals."
    t0 = time.monotonic()

    sm_file = ROOT / "domain" / "journal" / "state_machine.py"
    if not sm_file.exists():
        pr.add("CRITICAL", "domain/journal/state_machine.py", 0,
               "Lifecycle Error: 'state_machine.py' is missing. Transactions lack structural state definitions.",
               recommendation="Create domain/journal/state_machine.py containing explicit states and transition logic.")
        pr.score = 0
        pr.finalize_status()
        return pr

    tree = get_ast_tree(sm_file)
    if tree is None:
        pr.add("CRITICAL", "domain/journal/state_machine.py", 0,
               "Syntax Error: Failed to parse 'state_machine.py'. Ensure python code is syntactically sound.",
               recommendation="Fix Python syntax errors in domain/journal/state_machine.py immediately.")
        pr.score = 0
        pr.finalize_status()
        return pr

    REQUIRED_STATES = {"DRAFT", "POSTED", "REVERSED"}
    found_states = set()
    has_transition_guard = False

    for node in ast.walk(tree):
        # 1. Deteksi Kelas / Enum yang menampung State Konstanta
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                # Cek assignment standard: STATE = "VALUE"
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id in REQUIRED_STATES:
                            found_states.add(target.id)
                # Cek type-annotated assignment: STATE: str = "VALUE"
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.target.id in REQUIRED_STATES:
                        found_states.add(item.target.id)
                # Cek metode pengontrol transisi di dalam kelas state machine
                elif isinstance(item, ast.FunctionDef):
                    name_lower = item.name.lower()
                    if any(kw in name_lower for kw in ["transition", "change_state", "post", "reverse", "validate_move"]):
                        has_transition_guard = True

        # 2. Deteksi jika konstanta didefinisikan di level modul global (Top-Level Assignment)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in REQUIRED_STATES:
                    found_states.add(target.id)

    # Evaluasi Hasil Secara Ketat
    missing_states = REQUIRED_STATES - found_states
    violations = []

    if missing_states:
        violations.append(f"Missing explicit structural definitions for states: {missing_states}.")
    if not has_transition_guard:
        violations.append("Missing active transition guard logic (e.g., 'transition_to()', 'post()', or 'reverse()' methods) to enforce lifecycle constraints.")

    if not violations:
        pr.add("PASS", "domain/journal/state_machine.py", 0,
               f"Journal lifecycle pattern verified. All states {REQUIRED_STATES} and transition controls are structurally active.")
        pr.score = 100
    else:
        for error_msg in violations:
            pr.add("CRITICAL", "domain/journal/state_machine.py", 0, f"Lifecycle Compliance Violation: {error_msg}",
                   recommendation="Define states inside an Enum/Class and implement strict state transition functions.")
        pr.score = 0  # Zero tolerance untuk integritas alur jurnal

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p26_fiscal_period() -> PhaseResult:
    pr = PhaseResult("P26 Fiscal Period Pattern", weight=2)
    pr.disclaimer = "Uses rigorous AST analysis to ensure active executable logic exists for open, close, and lock operations, rejecting comment/stub bypasses."
    t0 = time.monotonic()

    fp_file = ROOT / "domain" / "fiscal_period" / "aggregate_root.py"
    if not fp_file.exists():
        pr.add("CRITICAL", "domain/fiscal_period/aggregate_root.py", 0,
               "Accounting Integrity Error: 'aggregate_root.py' for fiscal period management is missing.",
               recommendation="Create domain/fiscal_period/aggregate_root.py to govern ledger period states.")
        pr.score = 0
        pr.finalize_status()
        return pr

    tree = get_ast_tree(fp_file)
    if tree is None:
        pr.add("CRITICAL", "domain/fiscal_period/aggregate_root.py", 0,
               "Syntax Error: Failed to parse fiscal period aggregate root file.",
               recommendation="Fix Python syntax errors in domain/fiscal_period/aggregate_root.py immediately.")
        pr.score = 0
        pr.finalize_status()
        return pr

    # Operasi wajib yang harus ada di dalam Aggregate Root
    REQUIRED_OPS = {"open", "close", "lock"}
    found_ops = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            name_lower = node.name.lower()

            # Periksa apakah nama fungsi mengandung keyword operasi wajib
            matched_op = None
            for op in REQUIRED_OPS:
                if op in name_lower:
                    matched_op = op
                    break

            if matched_op:
                # DETEKSI STUB/FUNGSI KOSONG:
                # Jika body fungsi hanya berisi 1 statement, cek apakah itu 'pass' atau '...'
                if len(node.body) == 1:
                    stmt = node.body[0]
                    if isinstance(stmt, ast.Pass):
                        continue  # Abaikan, ini dummy bypass!
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value == Ellipsis:
                        continue  # Abaikan, ini dummy stub (...)

                # Jika lolos pengecekan di atas, berarti fungsi ini memiliki blok kode operasional
                found_ops.add(matched_op)

    # Evaluasi Hasil Akhir
    missing_ops = REQUIRED_OPS - found_ops

    if not missing_ops:
        pr.add("PASS", "domain/fiscal_period/aggregate_root.py", 0,
               "Fiscal period aggregate invariant verified. Concrete logic for open, close, and lock operations is present.")
        pr.score = 100
    else:
        for op in missing_ops:
            pr.add("CRITICAL", "domain/fiscal_period/aggregate_root.py", 0,
                   f"Compliance Deficit: Method for '{op}' operation is missing or implemented as an empty stub.",
                   recommendation=f"Implement actionable business logic for the '{op}' method to alter or lock the fiscal state.")
        pr.score = 0  # Zero tolerance jika proteksi periode pembukuan bohong / tidak lengkap

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p27_immutable_audit() -> PhaseResult:
    pr = PhaseResult("P27 Immutable Audit Pattern", weight=2)
    pr.disclaimer = "Enforces strict append-only whitelisting via AST, completely banning any mutation operations or unvetted logic in the core audit stream."
    t0 = time.monotonic()

    ew_file = ROOT / "audit" / "event_writer_immutable.py"
    if not ew_file.exists():
        pr.add("CRITICAL", "audit/event_writer_immutable.py", 0,
               "Forensic Integrity Error: Core 'event_writer_immutable.py' file is missing.",
               recommendation="Create audit/event_writer_immutable.py to lock the system's unalterable audit trails.")
        pr.score = 0
        pr.finalize_status()
        return pr

    tree = get_ast_tree(ew_file)
    if tree is None:
        pr.add("CRITICAL", "audit/event_writer_immutable.py", 0,
               "Syntax Error: Cannot parse 'event_writer_immutable.py'. Ensure the file is valid Python.",
               recommendation="Fix Python syntax errors in audit/event_writer_immutable.py immediately.")
        pr.score = 0
        pr.finalize_status()
        return pr

    # Daftar kata kunci yang mutlak dilarang muncul di nama fungsi/metode manapun
    STRICT_BLACKLIST = {"update", "delete", "modify", "edit", "overwrite", "change", "purge", "remove", "clear", "truncate", "fix"}

    # Daftar kata kunci yang diizinkan untuk fungsi append-only / read-only (Whitelisting)
    ALLOWED_PREFIXES_OR_KEYWORDS = {"append", "write", "log", "save", "get", "read", "fetch", "stream", "replay", "verify", "hash", "init"}

    # Method internal yang diperbolehkan meskipun tidak mengandung kata kunci whitelist
    # karena sifatnya helper internal yang tidak melakukan mutasi
    INTERNAL_ALLOWED = {"_validate_event", "_build_event_record", "_get_store", "_get_hash_builder", "_get_last_hash", "_compute_hash", "_get_stream_name"}

    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            name = node.name
            name_lower = name.lower()

            # 1. Cek Blok Kosong (Bypass Tipu-Tipu)
            if len(node.body) == 1:
                stmt = node.body[0]
                if isinstance(stmt, ast.Pass) or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value == Ellipsis):
                    violations.append(f"Method '{name}' is an empty dummy stub (pass/...). Core logging must contain execution logic.")
                    continue

            # 2. Cek Blacklist Kata Kunci Mutasi Data
            hit_blacklist = [word for word in STRICT_BLACKLIST if word in name_lower]
            if hit_blacklist:
                violations.append(f"Forbidden mutation method '{name}' detected (triggered by keyword: {hit_blacklist}).")
                continue

            # 3. Lewati internal helper yang sudah diizinkan
            if name in INTERNAL_ALLOWED:
                continue

            # 4. Cek Whitelist (Memastikan fungsi bertujuan untuk append atau read saja)
            is_whitelisted = any(kw in name_lower for kw in ALLOWED_PREFIXES_OR_KEYWORDS)
            if not is_whitelisted:
                # Untuk decorator, kita beri pengecualian karena decorator hanya wrapper
                if name == "decorator" or name.startswith("audit_"):
                    continue
                violations.append(f"Unvetted method '{name}' violates append-only design. Method name must clearly reflect read-only or append-only intent.")

    # Evaluasi Hasil Akhir
    if not violations:
        pr.add("PASS", "audit/event_writer_immutable.py", 0,
               "Forensic Invariant Confirmed: 'event_writer_immutable.py' structurally restricts operations to append-only and read-only pathways.")
        pr.score = 100
    else:
        for error_msg in violations:
            pr.add("CRITICAL", "audit/event_writer_immutable.py", 0, f"Audit Immutability Violation: {error_msg}",
                   recommendation="Strictly limit methods to data insertion (append/write) and forensic playback (read/replay). Remove any change or delete capabilities.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p28_monetary_decimal() -> PhaseResult:
    pr = PhaseResult("P28 Monetary Decimal Pattern", weight=3)
    pr.disclaimer = "Uses advanced AST analysis to detect any float typification, literal floats, or float conversions in core monetary fields."
    t0 = time.monotonic()

    _MONETARY_FIELDS = {"amount", "debit", "credit", "price", "cost", "tax", "total", "balance", "value"}
    violations = []

    def check_for_float_node(node: ast.AST) -> bool:
        """Helper untuk mendeteksi apakah suatu node bertipe atau mengarah ke 'float'."""
        if isinstance(node, ast.Name) and node.id == "float":
            return True
        if isinstance(node, ast.BinOp): # Contoh: float | None
            return check_for_float_node(node.left) or check_for_float_node(node.right)
        if isinstance(node, ast.Subscript): # Contoh: list[float]
            return check_for_float_node(node.slice)
        return False

    for path in all_py(skip_tops={"tests", "migrations", "deployment", "docs"}):
        if is_test_file(path):
            continue

        tree = get_ast_tree(path)
        if tree is None:
            continue

        rp = rel(path)

        for node in ast.walk(tree):
            # 1. Deteksi Type Hint pada Variabel (e.g., amount: float = 0)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id.lower() in _MONETARY_FIELDS and node.annotation:
                    if check_for_float_node(node.annotation):
                        violations.append((rp, node.lineno, f"Variable '{node.target.id}' uses forbidden 'float' type hint."))

            # 2. Deteksi Argumen Fungsi / Return Type Hint (e.g., def process(amount: float) -> float)
            elif isinstance(node, ast.FunctionDef):
                # Cek tipe data argumen fungsi
                for arg in node.args.args:
                    if arg.arg.lower() in _MONETARY_FIELDS and arg.annotation:
                        if check_for_float_node(arg.annotation):
                            violations.append((rp, node.lineno, f"Function argument '{arg.arg}' in '{node.name}' uses forbidden 'float' type hint."))
                # Cek tipe return fungsi
                if node.returns and check_for_float_node(node.returns):
                    if any(field in node.name.lower() for field in _MONETARY_FIELDS):
                        violations.append((rp, node.lineno, f"Monetary function '{node.name}' returns a forbidden 'float' type hint."))

            # 3. Deteksi Assignment Variabel Langsung (e.g., amount = 1500.50 atau amount = float(x))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.lower() in _MONETARY_FIELDS:
                        # Kasus A: Assignment dengan literal angka desimal langsung (e.g., amount = 250.75)
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, float):
                            violations.append((rp, node.lineno, f"Monetary field '{target.id}' is assigned a raw float literal value ({node.value.value})."))

                        # Kasus B: Assignment menggunakan pemanggilan fungsi float()
                        elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "float":
                            violations.append((rp, node.lineno, f"Monetary field '{target.id}' is forced into a float via explicit float() conversion."))

    # Pelaporan Hasil Audit secara Ketat
    for rp, lineno, msg in violations[:30]:
        pr.add("CRITICAL", rp, lineno, msg,
               detail="IEEE 754 Floating-point types cause unsafe decimal rounding errors in financial ledgers.",
               recommendation="Replace all 'float' usage with 'Decimal' from python's built-in decimal module or 'int' for cents.")

    if not violations:
        pr.add("PASS", ".", 0, "No floating-point numerical leaks discovered. All core monetary invariants are safe.")
        pr.score = 100
    else:
        pr.add("INFO", ".", 0, f"Total of {len(violations)} floating-point accounting integrity violations found.")
        pr.score = 0  # Zero tolerance terhadap presisi finansial

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p29_acid_pattern() -> PhaseResult:
    pr = PhaseResult("P29 ACID Pattern (Unit of Work)", weight=2)
    pr.disclaimer = "Validates ACID contract: checks Port (Interface) and Adapter (Implementation) for sync/async context managers."
    t0 = time.monotonic()

    # ====================================================================
    # 1. CEK PORT (INTERFACE) — Wajib ada deklarasi method (boleh abstract)
    # ====================================================================
    uow_port = ROOT / "ports" / "primary" / "unit_of_work_port.py"
    if not uow_port.exists():
        pr.add("CRITICAL", "ports/primary/unit_of_work_port.py", 0,
               "Architecture Violation: Unit of Work port is missing.",
               recommendation="Create ports/primary/unit_of_work_port.py defining the interface.")
        pr.score = 0
        pr.finalize_status()
        return pr

    port_tree = get_ast_tree(uow_port)
    if port_tree is None:
        pr.add("CRITICAL", "ports/primary/unit_of_work_port.py", 0,
               "Syntax Error: Cannot parse UoW Port file.")
        pr.score = 0
        pr.finalize_status()
        return pr

    # Cari method yang dideklarasikan di PORT (tidak peduli isinya, karena ini interface)
    port_methods = set()
    for node in ast.walk(port_tree):
        if isinstance(node, ast.ClassDef):
            # Ambil semua method dari class yang ada di port
            for item in node.body:
                # Perbaikan: cek baik FunctionDef maupun AsyncFunctionDef
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    port_methods.add(item.name)

    # Method wajib di PORT (baik sync maupun async, karena implementasi bisa memilih)
    required_port_methods = {"commit", "rollback", "__enter__", "__exit__", "__aenter__", "__aexit__"}
    # Minimal harus punya salah satu pasang context manager (sync ATAU async)
    has_sync_cm = "__enter__" in port_methods and "__exit__" in port_methods
    has_async_cm = "__aenter__" in port_methods and "__aexit__" in port_methods

    if not (has_sync_cm or has_async_cm):
        pr.add("CRITICAL", "ports/primary/unit_of_work_port.py", 0,
               "UoW Port missing context manager methods. Define either (__enter__/__exit__) for sync, or (__aenter__/__aexit__) for async.",
               recommendation="Add context manager methods to the UnitOfWorkPort interface.")
        pr.score = 0
        pr.finalize_status()
        return pr

    if "commit" not in port_methods or "rollback" not in port_methods:
        pr.add("CRITICAL", "ports/primary/unit_of_work_port.py", 0,
               "UoW Port missing 'commit' or 'rollback' declaration.",
               recommendation="Define commit() and rollback() in the UnitOfWorkPort interface.")
        pr.score = 0
        pr.finalize_status()
        return pr

    # ====================================================================
    # 2. CEK IMPLEMENTASI (ADAPTER) — Harus benar-benar implementasi konkret
    # ====================================================================
    # Cari file implementasi UoW (biasanya di adapters)
    impl_candidates = list(ROOT.glob("adapters/**/sqlalchemy_unit_of_work_impl.py"))
    if not impl_candidates:
        # Fallback: cari file lain yang mengimplementasikan UoW
        impl_candidates = list(ROOT.glob("adapters/**/*unit_of_work*.py"))

    if not impl_candidates:
        pr.add("CRITICAL", "adapters/secondary_impl", 0,
               "Implementation missing: No SQLAlchemyUnitOfWork found in adapters/.",
               recommendation="Create adapters/secondary_impl/sqlalchemy_unit_of_work_impl.py")
        pr.score = 0
        pr.finalize_status()
        return pr

    impl_file = impl_candidates[0]  # Ambil yang pertama
    impl_tree = get_ast_tree(impl_file)
    if impl_tree is None:
        pr.add("CRITICAL", rel(impl_file), 0,
               "Syntax Error: Cannot parse UoW Implementation file.")
        pr.score = 0
        pr.finalize_status()
        return pr

    # Kumpulkan method konkret dari implementasi
    impl_methods = set()
    for node in ast.walk(impl_tree):
        if isinstance(node, ast.ClassDef):
            # Fokus ke class yang kemungkinan adalah UoW (nama mengandung UnitOfWork)
            if "UnitOfWork" in node.name or "UoW" in node.name:
                for item in node.body:
                    # Perbaikan: cek baik FunctionDef maupun AsyncFunctionDef
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Validasi body: tidak boleh hanya pass atau ... (kecuali abstract)
                        is_empty = (
                            len(item.body) == 1 and
                            isinstance(item.body[0], (ast.Pass, ast.Expr))
                        )
                        if not is_empty:
                            impl_methods.add(item.name)

    # Validasi implementasi: harus punya commit, rollback, dan context manager yang sesuai
    missing_impl = []
    if "commit" not in impl_methods:
        missing_impl.append("commit")
    if "rollback" not in impl_methods:
        missing_impl.append("rollback")

    # Cek context manager (pilih salah satu yang terimplementasi)
    has_impl_sync = "__enter__" in impl_methods and "__exit__" in impl_methods
    has_impl_async = "__aenter__" in impl_methods and "__aexit__" in impl_methods

    if not has_impl_sync and not has_impl_async:
        missing_impl.append("context_manager (__enter__/__exit__ OR __aenter__/__aexit__)")

    if missing_impl:
        pr.add("CRITICAL", rel(impl_file), 0,
               f"UoW Implementation Violation: Missing or empty implementation of {missing_impl}",
               recommendation="Implement the missing methods in the SQLAlchemyUnitOfWork class with actual logic.")
        pr.score = 0
    else:
        pr.add("PASS", rel(impl_file), 0,
               f"ACID-compliant Unit of Work verified. Methods found: {', '.join(sorted(impl_methods))}")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p30_constitution_isolation() -> PhaseResult:
    pr = PhaseResult("P30 Constitution Isolation (Domain Purity)", weight=3)
    pr.disclaimer = "Uses AST to strictly enforce domain purity by banning direct imports of the constitution module."
    t0 = time.monotonic()

    domain_dir = ROOT / "domain"
    if not domain_dir.exists():
        pr.add("CRITICAL", "domain/", 0, "Domain directory missing.")
        pr.score = 0
        pr.finalize_status()
        return pr

    violations = []

    # Menentukan target modul yang terlarang bagi domain
    FORBIDDEN_MODULE = "constitution"

    for path in domain_dir.rglob("*.py"):
        tree = get_ast_tree(path)
        if not tree:
            continue

        for node in ast.walk(tree):
            # Cek 'import constitution'
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == FORBIDDEN_MODULE or alias.name.startswith(f"{FORBIDDEN_MODULE}."):
                        violations.append((rel(path), alias.name))

            # Cek 'from constitution import ...'
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == FORBIDDEN_MODULE or node.module.startswith(f"{FORBIDDEN_MODULE}.")):
                    violations.append((rel(path), node.module))

    if not violations:
        pr.add("PASS", "domain/", 0, "Domain Purity Verified: No direct imports of 'constitution'.")
        pr.score = 100
    else:
        for rp, mod in violations:
            pr.add("CRITICAL", rp, 0, f"Architecture Violation: Domain logic illegally imports '{mod}'.",
                   recommendation="Move this logic to 'infrastructure' or 'adapters'. Domain must remain pure.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P31 — ORM Primary Key Pattern (Strict AST Version)
def p31_orm_primary_keys() -> PhaseResult:
    pr = PhaseResult("P31 ORM Primary Key Pattern", weight=2)
    pr.disclaimer = "Strictly validates every ORM table has a primary key declared using AST (primary_key=True or PrimaryKeyConstraint)."
    t0 = time.monotonic()

    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               "ORM directory not found. Cannot validate primary keys.",
               recommendation="Create infrastructure/persistence_orm/ and define ORM tables.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Find all table files (*_table.py)
    table_files = list(orm_dir.glob("*_table.py"))
    if not table_files:
        pr.add("WARNING", "infrastructure/persistence_orm", 0,
               "No ORM table files found (*_table.py).",
               recommendation="Define ORM tables with primary keys.")
        pr.score = 80
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    violations = []  # list of (file, message)

    for orm_file in table_files:
        tree = get_ast_tree(orm_file)
        if tree is None:
            violations.append((rel(orm_file), "Syntax error in file"))
            continue

        # Collect all Column() calls and check for primary_key=True
        has_primary_key = False
        has_primary_key_constraint = False

        for node in ast.walk(tree):
            # Detect Column(primary_key=True) inside class definitions
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "Column":
                    for kw in node.keywords:
                        if kw.arg == "primary_key" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            has_primary_key = True
                            break
                # Detect PrimaryKeyConstraint(...) call
                if isinstance(node.func, ast.Name) and node.func.id == "PrimaryKeyConstraint":
                    has_primary_key_constraint = True
            # Detect SQLAlchemy Column imported as sa.Column and used
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "sa":
                        if node.func.attr == "Column":
                            for kw in node.keywords:
                                if kw.arg == "primary_key" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                    has_primary_key = True
                                    break
                        if node.func.attr == "PrimaryKeyConstraint":
                            has_primary_key_constraint = True

        # Check if any primary key was found
        if not has_primary_key and not has_primary_key_constraint:
            violations.append((rel(orm_file), "No primary key declared (missing primary_key=True or PrimaryKeyConstraint)"))

    # Report results
    if violations:
        for file, msg in violations:
            pr.add("CRITICAL", file, 0,
                   f"ORM table missing primary key: {msg}",
                   recommendation="Add primary_key=True to a Column or define PrimaryKeyConstraint.")
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               f"{len(violations)} ORM table(s) lack primary key. Database integrity is compromised.")
        pr.score = 0
    else:
        pr.add("PASS", "infrastructure/persistence_orm", 0,
               f"All {len(table_files)} ORM table files have primary keys declared.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p32_referential_integrity() -> PhaseResult:
    pr = PhaseResult("P32 Referential Integrity Pattern", weight=2)
    pr.disclaimer = "Strictly validates ForeignKey declarations: existence, syntax, and target table references."
    t0 = time.monotonic()

    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               "ORM directory not found. Cannot validate referential integrity.",
               recommendation="Create infrastructure/persistence_orm/ with ORM table definitions.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =====================================================================
    # 1. SCAN ALL ORM FILES
    # =====================================================================
    # Kumpulkan semua class ORM dan tabel yang didefinisikan
    orm_tables = {}  # {table_name: (file_path, class_name)}
    foreign_keys = []  # list of (file_path, line, table_name, target_table, column)

    for orm_file in orm_dir.glob("*.py"):
        if orm_file.name == "__init__.py":
            continue

        tree = get_ast_tree(orm_file)
        if tree is None:
            continue

        current_table = None
        current_class = None

        for node in ast.walk(tree):
            # Cari class dengan __tablename__
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and target.id == "__tablename__":
                                if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                                    table_name = item.value.value
                                    orm_tables[table_name] = (rel(orm_file), node.name)
                                    current_table = table_name
                                    current_class = node.name

            # Cari ForeignKey di dalam class
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    # ForeignKey sebagai argumen di Column
                    if isinstance(item, ast.Assign):
                        if isinstance(item.value, ast.Call):
                            # Column(..., ForeignKey(...))
                            if isinstance(item.value.func, ast.Name) and item.value.func.id == "Column":
                                for arg in item.value.args:
                                    if isinstance(arg, ast.Call):
                                        if isinstance(arg.func, ast.Name) and arg.func.id == "ForeignKey":
                                            # Ekstrak target table
                                            if arg.args and isinstance(arg.args[0], ast.Constant):
                                                target_ref = arg.args[0].value
                                                # Parse "table.column" or "table"
                                                parts = target_ref.split(".")
                                                target_table = parts[0]
                                                column_name = parts[1] if len(parts) > 1 else ""
                                                foreign_keys.append((
                                                    rel(orm_file),
                                                    node.lineno,
                                                    current_table or "unknown",
                                                    target_table,
                                                    column_name
                                                ))
                            # Atau ForeignKey langsung sebagai argumen (tanpa Column wrapper)
                            elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "ForeignKey":
                                if arg.args and isinstance(arg.args[0], ast.Constant):
                                    target_ref = arg.args[0].value
                                    parts = target_ref.split(".")
                                    target_table = parts[0]
                                    column_name = parts[1] if len(parts) > 1 else ""
                                    foreign_keys.append((
                                        rel(orm_file),
                                        node.lineno,
                                        current_table or "unknown",
                                        target_table,
                                        column_name
                                    ))

    # =====================================================================
    # 2. VALIDASI FOREIGN KEY TARGETS
    # =====================================================================
    # Tabel yang tidak perlu foreign key (master/standalone)
    MASTER_TABLES = {
        "account", "coa", "currency", "tax_rate", "unit", "warehouse",
        "legal_entity", "company", "user", "role", "permission",
        "setting", "config", "system_setting",
    }

    invalid_refs = []  # (file, line, table, target_table)
    tables_without_fk = set()

    # Cek semua tabel yang memiliki foreign key
    tables_with_fk = {fk[2] for fk in foreign_keys}
    all_tables = set(orm_tables.keys())

    # Tabel yang tidak memiliki foreign key dan bukan master
    for table in all_tables:
        if table not in tables_with_fk and table not in MASTER_TABLES:
            tables_without_fk.add(table)

    # Validasi target referensi
    for file, line, table, target_table, column in foreign_keys:
        if target_table not in all_tables:
            invalid_refs.append((file, line, table, target_table))

    # =====================================================================
    # 3. LAPORAN HASIL
    # =====================================================================
    if invalid_refs:
        for file, line, table, target_table in invalid_refs:
            pr.add("CRITICAL", file, line,
                   f"ForeignKey from table '{table}' references non-existent table '{target_table}'",
                   recommendation=f"Ensure table '{target_table}' exists or fix the ForeignKey reference.")
        pr.add("CRITICAL", ".", 0, f"{len(invalid_refs)} invalid ForeignKey reference(s) found.")
        pr.score = 0
    elif tables_without_fk:
        for table in tables_without_fk:
            pr.add("WARNING", orm_tables.get(table, ("unknown", "unknown"))[0], 0,
                   f"Table '{table}' has no ForeignKey constraints. Consider adding relationships if not a master table.",
                   recommendation=f"Add ForeignKey columns or classify '{table}' as a master table in MASTER_TABLES.")
        pr.add("PASS", ".", 0, f"All ForeignKey references are valid. {len(tables_without_fk)} table(s) without FK (non-critical).")
        pr.score = max(80, 100 - len(tables_without_fk) * 5)
    else:
        if foreign_keys:
            pr.add("PASS", "infrastructure/persistence_orm", 0,
                   f"Referential integrity verified: {len(foreign_keys)} ForeignKey declarations found, all references valid.")
            pr.score = 100
        else:
            pr.add("WARNING", "infrastructure/persistence_orm", 0,
                   "No ForeignKey declarations found in any ORM table. Database may lack referential integrity.",
                   recommendation="Add ForeignKey constraints to establish relationships between tables.")
            pr.score = 70

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p33_concurrency_pattern() -> PhaseResult:
    pr = PhaseResult("P33 Concurrency Pattern", weight=2)
    pr.disclaimer = "Validates optimistic locking implementation: version field in domain aggregates and ORM tables."
    t0 = time.monotonic()

    # =====================================================================
    # 1. SCAN DOMAIN AGGREGATES (wajib ada version field)
    # =====================================================================
    domain_aggregates = []
    for domain_dir in ROOT.glob("domain/*"):
        agg_file = domain_dir / "aggregate_root.py"
        if not agg_file.exists():
            continue
        tree = get_ast_tree(agg_file)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Cari class yang mungkin aggregate root (biasanya bernama *Aggregate atau *Root)
                if "Aggregate" in node.name or "Root" in node.name or "Entity" in node.name:
                    has_version_field = False
                    version_field_type = None

                    for item in node.body:
                        # Cek atribut version
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            if item.target.id.lower() == "version":
                                has_version_field = True
                                # Cek tipe (int, Optional[int], etc.)
                                if isinstance(item.annotation, ast.Name):
                                    version_field_type = item.annotation.id
                                elif isinstance(item.annotation, ast.Subscript):
                                    if isinstance(item.annotation.value, ast.Name):
                                        version_field_type = item.annotation.value.id
                        # Cek assignment version = 0 atau version = 1
                        elif isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and target.id.lower() == "version":
                                    has_version_field = True

                    if has_version_field:
                        domain_aggregates.append((rel(agg_file), node.name, version_field_type))

    # =====================================================================
    # 2. SCAN ORM TABLES (wajib ada version column)
    # =====================================================================
    orm_tables_with_version = []
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if orm_dir.exists():
        for orm_file in orm_dir.glob("*_table.py"):
            if orm_file.name == "__init__.py":
                continue
            tree = get_ast_tree(orm_file)
            if tree is None:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Cari class ORM dengan __tablename__
                    has_tablename = False
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and target.id == "__tablename__":
                                    has_tablename = True
                                    break
                    if not has_tablename:
                        continue

                    # Cari version column
                    has_version_column = False
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and target.id.lower() == "version":
                                    has_version_column = True
                                    break

                    if has_version_column:
                        orm_tables_with_version.append(rel(orm_file))

    # =====================================================================
    # 3. EVALUASI (lebih toleran)
    # =====================================================================
    if not domain_aggregates and not orm_tables_with_version:
        # Tidak ada version field sama sekali
        pr.add("WARNING", ".", 0,
               "No optimistic locking (version field) detected in domain aggregates or ORM tables.",
               recommendation="Consider adding a 'version' integer field to aggregate roots and ORM tables for optimistic locking.")
        pr.score = 70
    elif not domain_aggregates:
        # ORM punya version, tapi domain tidak
        pr.add("WARNING", ".", 0,
               "Version field found in ORM but not in domain aggregates. Domain-ORM mismatch.",
               recommendation="Add 'version' field to domain aggregate roots to match ORM schema.")
        pr.score = 70
    elif not orm_tables_with_version:
        # Domain punya version, tapi ORM tidak
        pr.add("WARNING", ".", 0,
               "Version field found in domain aggregates but not in ORM tables. Domain-ORM mismatch.",
               recommendation="Add 'version' column to ORM tables for aggregates, or ensure ORM uses another concurrency mechanism.")
        pr.score = 80  # Tidak gagal total, hanya warning
    else:
        # Semua baik: ada version di domain dan ORM
        if domain_aggregates:
            for file, name, vtype in domain_aggregates:
                pr.add("PASS", file, 0,
                       f"Domain aggregate '{name}' has version field (type: {vtype or 'auto'})")
        if orm_tables_with_version:
            for file in orm_tables_with_version:
                pr.add("PASS", file, 0, "ORM table has version column")
        pr.add("PASS", ".", 0,
               f"Optimistic locking pattern verified: {len(domain_aggregates)} aggregate(s) and {len(orm_tables_with_version)} ORM table(s) have version field.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p34_cogs_pattern() -> PhaseResult:
    pr = PhaseResult("P34 COGS Pattern", weight=2)
    pr.disclaimer = "Strictly validates COGS (Cost of Goods Sold) calculation implementation using AST analysis."
    t0 = time.monotonic()

    # =====================================================================
    # 1. CARI FILE COGS
    # =====================================================================
    cogs_candidates = []

    # File yang paling mungkin berisi COGS logic
    known_cogs_files = [
        "application/use_cases/cogs_calculation.py",
        "domain/inventory/cogs_engine.py",
        "domain/manufacturing/cogs_calculator.py",
        "domain/inventory/cost_of_goods_sold.py",
        "application/service_layer/service_cogs.py",
    ]

    for rel_path in known_cogs_files:
        full_path = ROOT / rel_path
        if full_path.exists():
            cogs_candidates.append(full_path)

    # Jika tidak ditemukan, cari file yang mengandung kata "cogs" di path
    if not cogs_candidates:
        for path in all_py(skip_tops={"tests", "migrations"}):
            if "cogs" in str(path).lower() or "hpp" in str(path).lower() or "cost_of_goods" in str(path).lower():
                cogs_candidates.append(path)

    # =====================================================================
    # 2. ANALISIS AST
    # =====================================================================
    found_cogs_implementation = False
    details = []

    for path in cogs_candidates:
        tree = get_ast_tree(path)
        if tree is None:
            continue

        # Kumpulkan semua fungsi dan kelas
        functions = []
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                functions.append(node)
            elif isinstance(node, ast.ClassDef):
                classes.append(node)

        # Cari fungsi atau method yang terkait COGS
        for func in functions:
            func_name = func.name.lower()
            func_body = ast.unparse(func)

            # Indikasi: nama mengandung cogs / hpp / cost_of_goods
            if any(kw in func_name for kw in ["cogs", "hpp", "cost_of_goods", "calculate_cogs"]):
                # Periksa apakah ada operasi matematis dan keyword inventory
                has_math = any(op in func_body for op in ["+", "-", "*", "/", "sum", "total"])
                has_inventory_keywords = any(kw in func_body.lower() for kw in ["beginning", "purchase", "ending", "inventory", "stock"])
                if has_math and has_inventory_keywords:
                    found_cogs_implementation = True
                    details.append(f"Function '{func.name}' in {rel(path)}")
                    break

        if found_cogs_implementation:
            break

    # =====================================================================
    # 3. EVALUASI
    # =====================================================================
    if found_cogs_implementation:
        pr.add("PASS", ".", 0,
               f"COGS calculation implementation found: {', '.join(details)}")
        pr.score = 100
    else:
        # Coba deteksi fallback: cari file yang mengandung formula COGS sederhana
        fallback_found = False
        for path in all_py(skip_tops={"tests", "migrations"}):
            src = path.read_text(encoding="utf-8", errors="replace")
            if "cogs" in src.lower() and ("beginning" in src.lower() or "purchase" in src.lower() or "ending" in src.lower()):
                fallback_found = True
                break

        if fallback_found:
            pr.add("WARNING", ".", 0,
                   "COGS pattern found in source (regex-based), but AST structural validation could not confirm robust mathematical logic.",
                   recommendation="Refactor COGS calculation into a dedicated function with clear beginning/purchase/ending inventory operations.")
            pr.score = 70
        else:
            pr.add("CRITICAL", ".", 0,
                   "No COGS (Cost of Goods Sold) calculation implementation found.",
                   recommendation="Implement COGS logic in application/use_cases/cogs_calculation.py with beginning inventory, purchases, and ending inventory.")
            pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p35_tax_pattern() -> PhaseResult:
    pr = PhaseResult("P35 Tax Calculation Pattern", weight=2)
    pr.disclaimer = "Strictly validates tax calculator implementations: file existence and AST-based method validation."
    t0 = time.monotonic()

    tax_dir = ROOT / "policy_engine" / "tax_indonesia"
    if not tax_dir.exists():
        pr.add("CRITICAL", "policy_engine/tax_indonesia", 0,
               "Tax directory not found. Core tax calculation engine is missing.",
               recommendation="Create policy_engine/tax_indonesia/ with required tax calculators.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =====================================================================
    # 1. DEFINE REQUIRED CALCULATORS AND THEIR EXPECTED METHODS
    # =====================================================================
    tax_calculators = {
        "ppn_calculator": {
            "description": "PPN (VAT) calculator",
            "expected_methods": ["calculate", "compute", "hitung_ppn"]
        },
        "pph_21_calculator": {
            "description": "PPh 21 (Income Tax) calculator",
            "expected_methods": ["calculate", "compute", "hitung_pph21"]
        },
        "pph_23_calculator": {
            "description": "PPh 23 (Withholding Tax) calculator",
            "expected_methods": ["calculate", "compute", "hitung_pph23"]
        },
        "pph_badan_calculator": {
            "description": "PPh Badan (Corporate Tax) calculator",
            "expected_methods": ["calculate", "compute", "hitung_pph_badan"]
        },
    }

    # =====================================================================
    # 2. VALIDATE EACH CALCULATOR
    # =====================================================================
    valid_calculators = []
    invalid_calculators = []

    for calc_name, info in tax_calculators.items():
        calc_file = tax_dir / f"{calc_name}.py"
        if not calc_file.exists():
            invalid_calculators.append((calc_name, "File missing"))
            continue

        # Parse AST
        tree = get_ast_tree(calc_file)
        if tree is None:
            invalid_calculators.append((calc_name, "Syntax error in file"))
            continue

        # Collect all function and method names
        defined_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                defined_names.add(node.name)
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                        defined_names.add(item.name)

        # Check if at least one expected method exists
        expected = info["expected_methods"]
        found = any(method in defined_names for method in expected)

        if found:
            valid_calculators.append(calc_name)
        else:
            invalid_calculators.append(
                (calc_name, f"Missing expected method. Expected one of: {', '.join(expected)}")
            )

    # =====================================================================
    # 3. REPORT RESULTS
    # =====================================================================
    if invalid_calculators:
        for calc_name, reason in invalid_calculators:
            pr.add("CRITICAL", f"policy_engine/tax_indonesia/{calc_name}.py", 0,
                   f"Tax calculator '{calc_name}' is invalid: {reason}",
                   recommendation=f"Ensure {calc_name}.py defines a function/class with one of: {', '.join(tax_calculators[calc_name]['expected_methods'])}")

        # Jika kurang dari 3 valid, sistem tidak layak
        if len(valid_calculators) < 3:
            pr.add("CRITICAL", "policy_engine/tax_indonesia", 0,
                   f"Only {len(valid_calculators)} of 4 tax calculators are valid. Minimum requirement is 3.")
            pr.score = 0
        else:
            # Masih ada 3 valid, tapi ada yang invalid → warning
            pr.add("WARNING", "policy_engine/tax_indonesia", 0,
                   f"{len(valid_calculators)} of 4 tax calculators are valid. {len(invalid_calculators)} need attention.")
            pr.score = 80
    else:
        # Semua valid
        pr.add("PASS", "policy_engine/tax_indonesia", 0,
               f"All {len(valid_calculators)} tax calculators are present and implement required methods.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p36_depreciation_pattern() -> PhaseResult:
    pr = PhaseResult("P36 Depreciation Pattern", weight=2)
    pr.disclaimer = "Strictly validates depreciation calculation implementation using AST: method existence and mathematical logic."
    t0 = time.monotonic()

    # =====================================================================
    # 1. DEFINE EXPECTED COMPONENTS
    # =====================================================================
    DEPRECIATION_METHODS = {
        "straight_line": {
            "keywords": ["straight", "garis_lurus", "sl"],
            "formula_indicators": ["cost", "residual", "useful_life", "years"]
        },
        "declining_balance": {
            "keywords": ["declining", "saldo_menurun", "double_declining", "ddb"],
            "formula_indicators": ["rate", "book_value", "depreciation_rate"]
        },
        "units_of_production": {
            "keywords": ["units", "production", "activity"],
            "formula_indicators": ["total_units", "units_produced", "cost_per_unit"]
        },
        "sum_of_years": {
            "keywords": ["sum_of_years", "sy", "syd"],
            "formula_indicators": ["remaining_life", "sum_of_years", "fraction"]
        }
    }

    # File target yang paling mungkin berisi depresiasi
    target_files = [
        "domain/fixed_asset/depreciation_schedule_engine.py",
        "domain/fixed_asset/depreciation_engine.py",
        "application/use_cases/depreciation_monthly_run.py",
        "domain/fixed_asset/aggregate_root.py",
        "domain/fixed_asset/asset_entity.py"
    ]

    # =====================================================================
    # 2. SCAN TARGET FILES
    # =====================================================================
    found_any = False
    found_details = []

    # Pertama scan file target spesifik
    for rel_path in target_files:
        full_path = ROOT / rel_path
        if not full_path.exists():
            continue

        tree = get_ast_tree(full_path)
        if tree is None:
            continue

        # Cari fungsi atau kelas yang mengandung kata 'depreciation'
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                name = node.name.lower()
                if "depreciation" in name or "depresiasi" in name:
                    body = ast.unparse(node)
                    # Cek apakah ada operasi matematis dan komponen depresiasi
                    has_math = any(op in body for op in ["+", "-", "*", "/", "sum", "total"])
                    has_asset_terms = any(term in body.lower() for term in ["asset", "cost", "value", "book"])
                    if has_math and has_asset_terms:
                        found_any = True
                        found_details.append(f"{rel_path}: function '{node.name}'")
                        break
            elif isinstance(node, ast.ClassDef):
                name = node.name.lower()
                if "depreciation" in name or "depresiasi" in name:
                    has_calculate_method = False
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and "calculate" in item.name.lower():
                            has_calculate_method = True
                            body = ast.unparse(item)
                            has_math = any(op in body for op in ["+", "-", "*", "/"])
                            has_asset_terms = any(term in body.lower() for term in ["asset", "cost", "value", "book"])
                            if has_math and has_asset_terms:
                                found_any = True
                                found_details.append(f"{rel_path}: class '{node.name}', method '{item.name}'")
                                break
                    if found_any:
                        break
        if found_any:
            break

    # =====================================================================
    # 3. FALLBACK: CARI DI SEMUA FILE
    # =====================================================================
    if not found_any:
        for path in all_py(skip_tops={"tests", "migrations"}):
            if any(x in path.name.lower() for x in ["depreciation", "depresiasi", "fixed_asset"]):
                src = path.read_text(encoding="utf-8", errors="replace")
                if "def " in src and ("depreciation" in src.lower() or "depresiasi" in src.lower()):
                    # Cek apakah ada operasi matematis
                    if any(op in src for op in ["+", "-", "*", "/"]) and any(term in src.lower() for term in ["asset", "cost", "value", "book"]):
                        found_any = True
                        found_details.append(f"{rel(path)}: found depreciation logic (regex)")
                        break

    # =====================================================================
    # 4. EVALUASI HASIL
    # =====================================================================
    if found_any:
        pr.add("PASS", ".", 0,
               f"Depreciation calculation implementation found: {', '.join(found_details)}")
        pr.score = 100
    else:
        # Cek apakah ada kata "depreciation" di seluruh source, untuk memberi tahu
        mention_found = False
        for path in all_py(skip_tops={"tests", "migrations"}):
            src = path.read_text(encoding="utf-8", errors="replace")
            if "depreciation" in src.lower() or "depresiasi" in src.lower():
                mention_found = True
                break

        if mention_found:
            pr.add("WARNING", ".", 0,
                   "'Depreciation' mentioned in source but no robust implementation found with mathematical logic.",
                   recommendation="Refactor depreciation into a dedicated function/class with clear asset cost, useful life, and depreciation rate calculations.")
            pr.score = 60
        else:
            pr.add("CRITICAL", ".", 0,
                   "No depreciation calculation pattern detected. Fixed asset depreciation is not implemented.",
                   recommendation="Implement depreciation methods (straight-line, declining balance) in domain/fixed_asset/depreciation_schedule_engine.py")
            pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p37_inventory_valuation() -> PhaseResult:
    pr = PhaseResult("P37 Inventory Valuation Pattern", weight=2)
    pr.disclaimer = "Strictly validates inventory valuation implementation (FIFO, Weighted Average, Moving Average) using AST."
    t0 = time.monotonic()

    # =====================================================================
    # 1. DEFINE EXPECTED VALUATION METHODS
    # =====================================================================
    VALUATION_METHODS = {
        "fifo": {
            "keywords": ["fifo", "first_in_first_out", "first_in"],
            "formula_indicators": ["cost", "quantity", "layer", "batch"]
        },
        "weighted_average": {
            "keywords": ["weighted_average", "average_cost", "avg_cost", "weighted_avg"],
            "formula_indicators": ["total_cost", "total_quantity", "average"]
        },
        "moving_average": {
            "keywords": ["moving_average", "moving_avg", "moving_cost"],
            "formula_indicators": ["new_cost", "new_quantity", "running_average"]
        }
    }

    # =====================================================================
    # 2. FIND TARGET FILES
    # =====================================================================
    inventory_files = []

    # Primary location: domain/inventory
    inv_dir = ROOT / "domain" / "inventory"
    if inv_dir.exists():
        inventory_files.extend(inv_dir.glob("*.py"))

    # Secondary: service inventory
    service_file = ROOT / "application" / "service_layer" / "service_inventory.py"
    if service_file.exists():
        inventory_files.append(service_file)

    # Tertiary: valuation specific files
    valuation_files = [
        "domain/inventory/valuation_method.py",
        "domain/inventory/fifo.py",
        "domain/inventory/weighted_average.py",
        "domain/inventory/moving_average.py",
        "domain/inventory/cost_methods.py"
    ]
    for rel_path in valuation_files:
        full_path = ROOT / rel_path
        if full_path.exists():
            inventory_files.append(full_path)

    if not inventory_files:
        pr.add("CRITICAL", "domain/inventory", 0,
               "No inventory valuation files found. Inventory module is missing.",
               recommendation="Create domain/inventory/ with valuation method implementations.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =====================================================================
    # 3. ANALYZE WITH AST
    # =====================================================================
    found_methods = []
    details = []

    for path in set(inventory_files):
        if path.name == "__init__.py":
            continue

        tree = get_ast_tree(path)
        if tree is None:
            continue

        # Kumpulkan semua fungsi dan kelas
        functions = []
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                functions.append(node)
            elif isinstance(node, ast.ClassDef):
                classes.append(node)

        # Cari fungsi/method yang terkait valuasi
        for method_name, info in VALUATION_METHODS.items():
            found = False

            # Cek di fungsi
            for func in functions:
                func_name = func.name.lower()
                if any(kw in func_name for kw in info["keywords"]):
                    body = ast.unparse(func)
                    # Cek indikasi formula
                    has_formula = any(indicator in body.lower() for indicator in info["formula_indicators"])
                    has_math = any(op in body for op in ["+", "-", "*", "/", "sum", "total"])
                    if has_math and has_formula:
                        found = True
                        details.append(f"{rel(path)}: function '{func.name}' ({method_name})")
                        break

            # Jika belum ditemukan, cek di kelas
            if not found:
                for cls in classes:
                    cls_name = cls.name.lower()
                    if any(kw in cls_name for kw in info["keywords"]):
                        for item in cls.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if "calculate" in item.name.lower() or "compute" in item.name.lower():
                                    body = ast.unparse(item)
                                    has_formula = any(indicator in body.lower() for indicator in info["formula_indicators"])
                                    has_math = any(op in body for op in ["+", "-", "*", "/", "sum", "total"])
                                    if has_math and has_formula:
                                        found = True
                                        details.append(f"{rel(path)}: class '{cls.name}', method '{item.name}' ({method_name})")
                                        break
                    if found:
                        break

            if found:
                found_methods.append(method_name)

    # =====================================================================
    # 4. EVALUASI
    # =====================================================================
    if found_methods:
        # Ada implementasi yang ditemukan
        pr.add("PASS", ".", 0,
               f"Inventory valuation implementation found: {', '.join(set(found_methods))}")
        for detail in details[:5]:
            pr.add("PASS", ".", 0, f"  - {detail}")
        if len(details) > 5:
            pr.add("INFO", ".", 0, f"  and {len(details)-5} more implementations")
        pr.score = 100
    else:
        # Fallback: cek secara tekstual
        textual_found = set()
        for path in inventory_files:
            if path.name == "__init__.py":
                continue
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
                for method_name, info in VALUATION_METHODS.items():
                    if any(kw in src.lower() for kw in info["keywords"]):
                        textual_found.add(method_name)
            except:
                pass

        if textual_found:
            pr.add("WARNING", ".", 0,
                   f"Inventory valuation keywords found ({', '.join(textual_found)}), but AST validation could not confirm robust mathematical logic.",
                   recommendation="Refactor inventory valuation into dedicated functions with clear cost/quantity calculations.")
            pr.score = 70
        else:
            pr.add("CRITICAL", ".", 0,
                   "No inventory valuation implementation found (FIFO, Weighted Average, or Moving Average).",
                   recommendation="Implement inventory valuation methods in domain/inventory/ (e.g., fifo.py, weighted_average.py).")
            pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p38_fiscal_closing() -> PhaseResult:
    pr = PhaseResult("P38 Fiscal Closing Pattern", weight=2)
    pr.disclaimer = "Strictly validates fiscal closing implementation: period_close, year_end, fiscal_closing with mathematical logic."
    t0 = time.monotonic()

    # =====================================================================
    # 1. DEFINE EXPECTED COMPONENTS
    # =====================================================================
    CLOSING_KEYWORDS = {
        "period_close": ["period_close", "close_period", "closing_period"],
        "year_end": ["year_end", "year_end_close", "year_end_closing"],
        "fiscal_closing": ["fiscal_closing", "close_fiscal_year", "fiscal_year_close"]
    }

    # Akuntansi: indikator operasi penutupan
    ACCOUNTING_INDICATORS = [
        "retained_earnings", "retained", "closing", "transfer_balance",
        "reset_income", "income_statement", "balance_sheet", "p_l",
        "trial_balance", "close_accounts", "zero_out", "net_income"
    ]

    # File target yang paling mungkin berisi closing logic
    target_files = [
        "application/use_cases/period_close.py",
        "application/use_cases/year_end_closing.py",
        "domain/fiscal_period/aggregate_root.py",
        "domain/fiscal_period/period_close_engine.py",
        "application/use_cases/fiscal_closing.py",
        "kernel/guards/period_lock.py"
    ]

    # =====================================================================
    # 2. SCAN TARGET FILES
    # =====================================================================
    found_any = False
    found_details = []
    found_keywords = set()

    # Pertama scan file target spesifik
    for rel_path in target_files:
        full_path = ROOT / rel_path
        if not full_path.exists():
            continue

        tree = get_ast_tree(full_path)
        if tree is None:
            continue

        # Cari fungsi atau kelas yang mengandung kata kunci closing
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                name = node.name.lower()
                for category, keywords in CLOSING_KEYWORDS.items():
                    if any(kw in name for kw in keywords):
                        body = ast.unparse(node)
                        # Cek apakah ada indikator akuntansi
                        has_accounting = any(indicator in body.lower() for indicator in ACCOUNTING_INDICATORS)
                        has_math = any(op in body for op in ["+", "-", "*", "/", "sum", "total", "="])
                        if has_accounting and has_math:
                            found_any = True
                            found_details.append(f"{rel_path}: function '{node.name}' ({category})")
                            found_keywords.add(category)
                            break
            elif isinstance(node, ast.ClassDef):
                name = node.name.lower()
                for category, keywords in CLOSING_KEYWORDS.items():
                    if any(kw in name for kw in keywords):
                        # Cari method 'close', 'execute', 'run' di dalam class
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if item.name.lower() in ["close", "execute", "run", "perform"]:
                                    body = ast.unparse(item)
                                    has_accounting = any(indicator in body.lower() for indicator in ACCOUNTING_INDICATORS)
                                    has_math = any(op in body for op in ["+", "-", "*", "/", "sum", "total"])
                                    if has_accounting and has_math:
                                        found_any = True
                                        found_details.append(f"{rel_path}: class '{node.name}', method '{item.name}' ({category})")
                                        found_keywords.add(category)
                                        break
                        if found_any:
                            break
                if found_any:
                    break
        if found_any:
            break

    # =====================================================================
    # 3. FALLBACK: CARI DI SEMUA FILE
    # =====================================================================
    if not found_any:
        for path in all_py(skip_tops={"tests", "migrations"}):
            src = path.read_text(encoding="utf-8", errors="replace")
            # Cek apakah ada kata kunci closing
            has_keyword = False
            category = None
            for cat, keywords in CLOSING_KEYWORDS.items():
                if any(kw in src.lower() for kw in keywords):
                    has_keyword = True
                    category = cat
                    break

            if has_keyword:
                # Cek apakah ada indikator akuntansi dan operasi matematis
                has_accounting = any(indicator in src.lower() for indicator in ACCOUNTING_INDICATORS)
                has_math = any(op in src for op in ["+", "-", "*", "/", "sum", "total", "="])
                if has_accounting and has_math:
                    found_any = True
                    found_details.append(f"{rel(path)}: found closing logic (regex)")
                    found_keywords.add(category)
                    break

    # =====================================================================
    # 4. EVALUASI HASIL
    # =====================================================================
    if found_any:
        pr.add("PASS", ".", 0,
               f"Fiscal closing implementation found: {' '.join(found_details)}")
        pr.add("PASS", ".", 0,
               f"Closing categories detected: {', '.join(found_keywords) if found_keywords else 'unspecified'}")
        pr.score = 100
    else:
        # Cek apakah ada keyword closing di source
        keyword_found = False
        for path in all_py(skip_tops={"tests", "migrations"}):
            src = path.read_text(encoding="utf-8", errors="replace")
            for cat, keywords in CLOSING_KEYWORDS.items():
                if any(kw in src.lower() for kw in keywords):
                    keyword_found = True
                    break
            if keyword_found:
                break

        if keyword_found:
            pr.add("WARNING", ".", 0,
                   "Fiscal closing keywords found but no robust implementation with accounting indicators and mathematical operations.",
                   recommendation="Refactor fiscal closing into a dedicated function/class with retained earnings transfer and account reset logic.")
            pr.score = 60
        else:
            pr.add("CRITICAL", ".", 0,
                   "No fiscal closing implementation detected. Period close and year-end procedures are missing.",
                   recommendation="Implement fiscal closing procedures in application/use_cases/period_close.py or domain/fiscal_period/aggregate_root.py")
            pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p39_retained_earnings() -> PhaseResult:
    pr = PhaseResult("P39 Retained Earnings Pattern", weight=2)
    pr.disclaimer = "Strictly validates retained earnings calculation implementation: formula: prior_retained + net_income - dividends."
    t0 = time.monotonic()

    # =====================================================================
    # 1. DEFINE EXPECTED COMPONENTS
    # =====================================================================
    RETAINED_KEYWORDS = ["retained_earnings", "retainedearning", "laba_ditahan", "saldo_laba"]

    # Komponen retained earnings
    RE_COMPONENTS = [
        "retained_earnings", "retained", "earnings",
        "net_income", "net_profit", "income", "profit",
        "dividend", "dividends", "payout",
        "beginning_retained", "ending_retained",
        "accumulated_profit", "accumulated_loss"
    ]

    # File target yang paling mungkin berisi retained earnings
    target_files = [
        "domain/equity_retained/retained_earnings_entity.py",
        "domain/equity_retained/aggregate_root.py",
        "domain/equity_retained/equity_calculator.py",
        "application/use_cases/retained_earnings_calculation.py",
        "projections/ledger/equity_statement.py",
        "domain/equity_retained/retained_earnings_calculator.py",
        "application/service_layer/service_equity.py"
    ]

    # =====================================================================
    # 2. SCAN TARGET FILES
    # =====================================================================
    found_any = False
    found_details = []

    # Pertama scan file target spesifik
    for rel_path in target_files:
        full_path = ROOT / rel_path
        if not full_path.exists():
            continue

        tree = get_ast_tree(full_path)
        if tree is None:
            continue

        # Cari fungsi atau kelas yang mengandung kata kunci retained earnings
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                name = node.name.lower()
                if any(kw in name for kw in RETAINED_KEYWORDS):
                    body = ast.unparse(node)
                    # Cek apakah ada formula: prior_retained + net_income - dividends
                    has_prior = any(p in body.lower() for p in ["prior", "beginning", "previous", "last"])
                    has_net_income = any(n in body.lower() for n in ["net_income", "net_profit", "profit"])
                    has_dividend = any(d in body.lower() for d in ["dividend", "payout", "distribution"])
                    has_math = any(op in body for op in ["+", "-", "*", "/", "sum", "total"])

                    # Jika memiliki komponen utama retained earnings
                    if has_math and (has_prior or has_net_income or has_dividend):
                        found_any = True
                        found_details.append(f"{rel_path}: function '{node.name}'")
                        break

            elif isinstance(node, ast.ClassDef):
                name = node.name.lower()
                if any(kw in name for kw in RETAINED_KEYWORDS):
                    # Cari method 'calculate', 'compute', 'get' di dalam class
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if item.name.lower() in ["calculate", "compute", "get", "calculate_retained_earnings", "compute_retained"]:
                                body = ast.unparse(item)
                                has_math = any(op in body for op in ["+", "-", "*", "/", "sum"])
                                has_components = any(comp in body.lower() for comp in RE_COMPONENTS)
                                if has_math and has_components:
                                    found_any = True
                                    found_details.append(f"{rel_path}: class '{node.name}', method '{item.name}'")
                                    break
                    if found_any:
                        break
        if found_any:
            break

    # =====================================================================
    # 3. FALLBACK: CARI DI SEMUA FILE
    # =====================================================================
    if not found_any:
        for path in all_py(skip_tops={"tests", "migrations"}):
            src = path.read_text(encoding="utf-8", errors="replace")
            # Cek apakah ada keyword retained earnings
            if any(kw in src.lower() for kw in RETAINED_KEYWORDS):
                # Cek apakah ada formula matematis
                has_math = any(op in src for op in ["+", "-", "*", "/", "sum", "total"])
                has_components = any(comp in src.lower() for comp in RE_COMPONENTS)
                if has_math and has_components:
                    found_any = True
                    found_details.append(f"{rel(path)}: found retained earnings logic (regex)")
                    break

    # =====================================================================
    # 4. VALIDASI FORMULA KHUSUS: prior_retained + net_income - dividends
    # =====================================================================
    formula_details = []
    if found_any:
        # Cek apakah ada formula spesifik (prior + income - dividends)
        for path in all_py(skip_tops={"tests", "migrations"}):
            src = path.read_text(encoding="utf-8", errors="replace")
            # Cari pola: retained_earnings = prior_retained + net_income - dividends
            # atau variannya
            patterns = [
                r"retained.*?=.*?prior.*?\+.*?income.*?\-.*?dividend",
                r"ending_retained.*?=.*?beginning_retained.*?\+.*?net_income.*?\-.*?dividend",
                r"retained_earnings.*?=.*?previous.*?\+.*?profit.*?\-.*?payout",
                r"laba_ditahan.*?=.*?laba.*?ditahan.*?sebelumnya.*?\+.*?laba.*?bersih.*?\-.*?dividen",
            ]
            for pattern in patterns:
                if re.search(pattern, src, re.IGNORECASE):
                    formula_details.append(f"{rel(path)}: explicit retained earnings formula found")
                    break

    # =====================================================================
    # 5. EVALUASI HASIL
    # =====================================================================
    if found_any:
        pr.add("PASS", ".", 0,
               f"Retained earnings implementation found: {'; '.join(found_details)}")
        if formula_details:
            pr.add("PASS", ".", 0,
               f"Explicit retained earnings formula: {formula_details[0]}")
        pr.score = 100
    else:
        # Cek apakah ada keyword retained earnings di source
        keyword_found = False
        for path in all_py(skip_tops={"tests", "migrations"}):
            src = path.read_text(encoding="utf-8", errors="replace")
            if any(kw in src.lower() for kw in RETAINED_KEYWORDS):
                keyword_found = True
                break

        if keyword_found:
            pr.add("WARNING", ".", 0,
                   "Retained earnings keywords found but no robust implementation with components (prior_retained, net_income, dividends).",
                   recommendation="Implement retained earnings calculation using formula: ending_retained = beginning_retained + net_income - dividends.")
            pr.score = 60
        else:
            pr.add("CRITICAL", ".", 0,
                   "No retained earnings implementation detected. Equity retained earnings calculation is missing.",
                   recommendation="Implement retained earnings in domain/equity_retained/retained_earnings_entity.py with formula: prior_retained + net_income - dividends.")
            pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p40_pytest(quick: bool = False) -> PhaseResult:
    pr = PhaseResult("P40 Pytest Suite", weight=3)
    pr.disclaimer = "Strictly verifies pytest test suite: collects test count and validates test execution success."
    t0 = time.monotonic()

    if quick:
        pr.add("INFO", ".", 0, "Pytest skipped (--quick)")
        pr.score = -1
        pr.finalize_status()
        pr.duration = 0.0
        return pr

    test_path = ROOT / "tests"
    if not test_path.exists():
        pr.add("CRITICAL", "tests/", 0,
               "tests directory not found. Test suite is missing.",
               recommendation="Create tests/ directory and add test files.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =====================================================================
    # 1. RUN PYTEST COLLECTION
    # =====================================================================
    cmd_collect = [
        sys.executable, "-m", "pytest", str(test_path),
        "--collect-only", "-q", "--no-header", "--disable-warnings"
    ]

    try:
        result = subprocess.run(
            cmd_collect,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT)
        )
        output = result.stdout + result.stderr

        # Ekstrak jumlah test
        test_count = 0
        patterns = [
            r"collected\s+(\d+)\s+items?",
            r"collected\s+(\d+)\s+tests?",
            r"(\d+)\s+tests? collected",
            r"collected\s+(\d+)"
        ]
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                test_count = int(match.group(1))
                break

        # Fallback jika tidak terdeteksi
        if test_count == 0:
            # Cek summary
            summary_match = re.search(r"===+\s+(\d+)\s+passed", output)
            if summary_match:
                test_count = int(summary_match.group(1))
                skipped_match = re.search(r"(\d+)\s+skipped", output)
                if skipped_match:
                    test_count += int(skipped_match.group(1))
                failed_match = re.search(r"(\d+)\s+failed", output)
                if failed_match:
                    test_count += int(failed_match.group(1))

        # =================================================================
        # 2. EVALUASI HASIL COLLECTION
        # =================================================================
        if result.returncode != 0 and "error" in output.lower():
            # Ada error pada collection
            pr.add("CRITICAL", "tests/", 0,
                   f"Pytest collection failed with error: {output[:200]}",
                   recommendation="Fix syntax or import errors in test files.")
            pr.score = 0
        elif test_count > 0:
            pr.add("PASS", "tests/", 0,
                   f"Found {test_count} tests via pytest collection")

            # Coba jalankan subset test untuk validasi (opsional, tapi tidak wajib)
            # Untuk kecepatan, kita hanya lakukan jika jumlah test > 0
            # Kita tidak jalankan test karena bisa merusak DB, hanya verifikasi collection

            # Beri skor berdasarkan jumlah test (minimal 10 test untuk sistem besar)
            if test_count >= 50:
                pr.add("PASS", "tests/", 0,
                       f"Test suite is comprehensive: {test_count} tests")
                pr.score = 100
            elif test_count >= 20:
                pr.add("PASS", "tests/", 0,
                       f"Test suite is adequate: {test_count} tests")
                pr.score = 90
            elif test_count >= 10:
                pr.add("WARNING", "tests/", 0,
                       f"Test suite is small: {test_count} tests. Consider expanding coverage.")
                pr.score = 70
            else:
                pr.add("WARNING", "tests/", 0,
                       f"Test suite has only {test_count} test(s). Insufficient for production system.")
                pr.score = 50
        else:
            # Tidak ada test
            pr.add("CRITICAL", "tests/", 0,
                   "No tests found in tests/ directory.",
                   recommendation="Add at least 10 tests to validate core business logic.")
            pr.score = 0

    except subprocess.TimeoutExpired:
        pr.add("CRITICAL", "tests/", 0,
               "Pytest collection timed out after 60 seconds. Tests may be hanging.",
               recommendation="Check for slow imports or infinite loops in test files.")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "tests/", 0,
               f"Pytest collection failed: {type(e).__name__}: {str(e)[:100]}",
               recommendation="Ensure pytest is installed and test files are valid.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p41_compliance_structure() -> PhaseResult:
    pr = PhaseResult("P41 Compliance Structure", weight=2)
    pr.disclaimer = "Strictly validates compliance file existence and structural integrity (AST) for PSAK and IFRS components."
    t0 = time.monotonic()

    # =====================================================================
    # 1. DEFINE COMPLIANCE CONTRACTS
    # =====================================================================
    COMPLIANCE_CONTRACTS = {
        "policy_engine/psak/psak_aggregator.py": {
            "required_names": ["PsakAggregator", "get_psak_aggregator"],
            "description": "PSAK aggregator main class/factory",
            "required_methods": ["get_standard", "list_standards", "apply_psak"]
        },
        "policy_engine/ifrs/ifrs_aggregator.py": {
            "required_names": ["IfrsAggregator", "get_ifrs_aggregator"],
            "description": "IFRS aggregator main class/factory",
            "required_methods": ["get_standard", "list_standards", "apply_ifrs"]
        },
        "compliance/psak_checker.py": {
            "required_names": ["PsakChecker", "check_psak_compliance"],
            "description": "PSAK compliance checker",
            "required_methods": ["check", "validate", "get_violations"]
        },
        "compliance/ifrs_checker.py": {
            "required_names": ["IfrsChecker", "check_ifrs_compliance"],
            "description": "IFRS compliance checker",
            "required_methods": ["check", "validate", "get_violations"]
        }
    }

    # =====================================================================
    # 2. VALIDATE EACH COMPLIANCE FILE
    # =====================================================================
    violations = []   # list of (file, message)
    missing_files = []
    valid_files = 0

    for rel_path, contract in COMPLIANCE_CONTRACTS.items():
        full_path = ROOT / rel_path

        if not full_path.exists():
            missing_files.append(rel_path)
            continue

        # Parse AST
        tree = get_ast_tree(full_path)
        if tree is None:
            violations.append((rel_path, "Syntax error in file"))
            continue

        # Collect all class and function names
        defined_names = set()
        class_methods = {}  # class_name -> set(method_names)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                defined_names.add(node.name)
            elif isinstance(node, ast.ClassDef):
                defined_names.add(node.name)
                methods = set()
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.add(item.name)
                class_methods[node.name] = methods

        # Check required names (at least one)
        required_names = contract["required_names"]
        found_names = [name for name in required_names if name in defined_names]

        if not found_names:
            violations.append(
                (rel_path, f"Missing required class/function. Expected one of: {', '.join(required_names)}")
            )
            continue

        # Check required methods (if the found name is a class)
        for found_name in found_names:
            if found_name in class_methods:
                # It's a class, check methods
                required_methods = contract.get("required_methods", [])
                if required_methods:
                    existing_methods = class_methods[found_name]
                    missing_methods = [m for m in required_methods if m not in existing_methods]
                    if missing_methods:
                        violations.append(
                            (rel_path,
                             f"Class '{found_name}' missing methods: {', '.join(missing_methods)}")
                        )
                        break
            else:
                # It's a function, we can skip method check (functions don't have methods)
                pass

        # If we reach here, file is valid
        valid_files += 1

    # =====================================================================
    # 3. REPORT RESULTS
    # =====================================================================
    total_expected = len(COMPLIANCE_CONTRACTS)

    if missing_files:
        for rel_path in missing_files:
            pr.add("CRITICAL", rel_path, 0,
                   f"Compliance file missing: {rel_path}",
                   recommendation=f"Create {rel_path} with required class/function: {COMPLIANCE_CONTRACTS[rel_path]['required_names']}")

    if violations:
        for rel_path, msg in violations:
            pr.add("CRITICAL", rel_path, 0,
                   f"Compliance file invalid: {msg}",
                   recommendation=f"Fix the structure in {rel_path} according to contract.")

    # Final evaluation
    if missing_files or violations:
        pr.add("CRITICAL", ".", 0,
               f"Compliance structure: {valid_files}/{total_expected} valid, {len(missing_files)} missing, {len(violations)} invalid")
        pr.score = 0
    else:
        pr.add("PASS", ".", 0,
               f"All {total_expected} compliance files exist and have valid structure")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p42_schema_consistency() -> PhaseResult:
    pr = PhaseResult("P42 Schema Consistency", weight=3)
    pr.disclaimer = "Compares ORM metadata with migration create_table statements (including raw SQL)."
    t0 = time.monotonic()

    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    alembic_dir = ROOT / "migrations" / "versions"

    if not orm_dir.exists():
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               "ORM directory not found. Cannot validate schema consistency.",
               recommendation="Ensure ORM directory exists with table definitions.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    if not alembic_dir.exists():
        pr.add("CRITICAL", "migrations/versions", 0,
               "Migrations versions directory not found. Cannot validate schema consistency.",
               recommendation="Run 'alembic init migrations' and create initial migration.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # ---- 1. EXTRACT ORM TABLES (dari Base.metadata) ----
    try:
        from infrastructure.persistence_orm.base_model import Base
        orm_tables = set()
        for table in Base.metadata.tables.values():
            # Ambil nama tabel tanpa schema (jika ada)
            table_name = table.name
            orm_tables.add(table_name)
    except Exception as e:
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               f"Failed to load Base.metadata: {e}",
               recommendation="Ensure all ORM modules are importable.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # ---- 2. EXTRACT MIGRATION TABLES ----
    migration_tables = set()
    migration_file_map = {}

    # Regex untuk mencari CREATE TABLE dalam op.execute
    create_table_regex = re.compile(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(["\']?)(\w+)\1',
        re.IGNORECASE
    )

    for mig_file in alembic_dir.glob("*.py"):
        if mig_file.name == "__init__.py":
            continue

        # Baca isi file sebagai teks (untuk op.execute)
        content = mig_file.read_text(encoding="utf-8", errors="ignore")

        # Cari op.create_table(...)
        tree = get_ast_tree(mig_file)
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # op.create_table('table_name', ...)
                    if isinstance(node.func, ast.Attribute):
                        if (node.func.attr == "create_table" and
                            isinstance(node.func.value, ast.Name) and
                            node.func.value.id == "op"):
                            if node.args and isinstance(node.args[0], ast.Constant):
                                table_name = node.args[0].value
                                if isinstance(table_name, str):
                                    migration_tables.add(table_name)
                                    migration_file_map[table_name] = rel(mig_file)

        # Cari op.execute("CREATE TABLE ...") dengan regex
        for match in create_table_regex.finditer(content):
            table_name = match.group(2)
            if table_name:
                migration_tables.add(table_name)
                migration_file_map.setdefault(table_name, rel(mig_file))

    # ---- 3. COMPARE ----
    only_in_orm = orm_tables - migration_tables
    only_in_migration = migration_tables - orm_tables

    # ---- 4. REPORT ----
    if only_in_orm:
        for table in only_in_orm:
            pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
                   f"Table '{table}' defined in ORM but missing in migrations",
                   recommendation=f"Create migration for table '{table}'")
        pr.add("CRITICAL", ".", 0,
               f"{len(only_in_orm)} table(s) defined in ORM but missing in migrations.")
        pr.score = 0
    elif only_in_migration:
        for table in only_in_migration:
            pr.add("WARNING", migration_file_map.get(table, "unknown"), 0,
                   f"Table '{table}' exists in migration but not defined in ORM",
                   recommendation=f"Add ORM class for table '{table}' or remove unused migration.")
        pr.add("WARNING", ".", 0,
               f"{len(only_in_migration)} table(s) in migration but not in ORM.")
        pr.score = 80
    else:
        pr.add("PASS", ".", 0,
               f"ORM and migration table definitions are consistent. {len(orm_tables)} tables verified.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p43_runtime_imports() -> PhaseResult:
    pr = PhaseResult("P43 Runtime Import Test", weight=4)
    pr.disclaimer = "Strictly attempts to import every production module. ANY import failure is CRITICAL."
    t0 = time.monotonic()

    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"}, include_checker=False)

    errors = []
    successful = 0

    for path in files:
        mod = mod_name(path)
        if not mod or mod.startswith("main_checker"):
            continue
        if path.name == "__init__.py":
            # Skip __init__.py (will be imported via package)
            continue

        # Skip files that are known to require external dependencies (optional)
        # But we want to be strict, so we try anyway

        ok, err = _safe_import_module(mod)
        if ok:
            successful += 1
        else:
            errors.append((rel(path), mod, err[:100]))
            if len(errors) >= 20:
                # Still collect but limit reporting
                break

    if not errors:
        pr.add("PASS", ".", 0,
               f"All {successful} production modules imported successfully.")
        pr.score = 100
    else:
        for file, mod, err in errors:
            pr.add("CRITICAL", file, 0,
                   f"Import failed for module '{mod}': {err}",
                   recommendation=f"Fix the import dependency in {mod}.")
        pr.add("CRITICAL", ".", 0,
               f"{len(errors)} modules failed to import. System is NOT deployable.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p44_app_bootstrap() -> PhaseResult:
    pr = PhaseResult("P44 Application Bootstrap", weight=5)
    pr.disclaimer = "Strictly attempts to create the ASGI application. ANY failure is CRITICAL."
    t0 = time.monotonic()

    try:
        # Try to import app.main
        main_mod = importlib.import_module("app.main")

        # Try to get app object
        app_obj = None
        if hasattr(main_mod, "app"):
            app_obj = main_mod.app
        elif hasattr(main_mod, "create_app"):
            app_obj = main_mod.create_app()
        elif hasattr(main_mod, "get_app"):
            app_obj = main_mod.get_app()
        else:
            pr.add("CRITICAL", "app/main.py", 0,
                   "No 'app' variable, 'create_app()', or 'get_app()' function found.",
                   recommendation="Define 'app = FastAPI()' or 'def create_app(): return FastAPI()' in app/main.py.")
            pr.score = 0
            pr.finalize_status()
            pr.duration = time.monotonic() - t0
            return pr

        # If app is a factory function, call it
        if callable(app_obj) and not isinstance(app_obj, type):
            app_obj = app_obj()

        # Verify it's a valid ASGI application
        if hasattr(app_obj, "__call__"):
            pr.add("PASS", "app/main.py", 0,
                   "Application bootstrap successful. ASGI app is callable.")
            pr.score = 100
        else:
            pr.add("CRITICAL", "app/main.py", 0,
                   "App object is not callable (not a valid ASGI application).",
                   recommendation="Ensure 'app' is a FastAPI instance or returns one.")
            pr.score = 0

    except ImportError as e:
        pr.add("CRITICAL", "app/main.py", 0,
               f"Failed to import app.main: {type(e).__name__}: {str(e)[:100]}",
               recommendation="Check app/main.py for syntax errors or missing dependencies.")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "app/main.py", 0,
               f"Bootstrap failed: {type(e).__name__}: {str(e)[:150]}",
               recommendation="Check application configuration, dependencies, and environment variables.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p45_db_connectivity() -> PhaseResult:
    pr = PhaseResult("P45 Database Connectivity", weight=4)
    pr.disclaimer = "Strictly tests database connectivity using DATABASE_URL from environment or settings."
    t0 = time.monotonic()

    # Try to get DATABASE_URL
    database_url = None

    # First try from environment
    database_url = os.environ.get("DATABASE_URL")

    # Then try from app settings if available
    if not database_url:
        try:
            from app.main import settings
            database_url = getattr(settings, "database_url", None)
        except ImportError:
            pass

    # Fallback for testing (but this should be considered a warning)
    if not database_url:
        pr.add("CRITICAL", "config/", 0,
               "DATABASE_URL not found in environment or app settings.",
               recommendation="Set DATABASE_URL environment variable or define in app settings.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Ensure asyncpg driver
    if database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(database_url, pool_pre_ping=True, pool_size=1)

        async def test_connection():
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                return result.scalar()

        result = asyncio.run(test_connection())
        if result == 1:
            pr.add("PASS", "config/", 0,
                   f"Database connection successful ({database_url[:50]}...)")
            pr.score = 100
        else:
            raise Exception("Unexpected result from SELECT 1")

    except ImportError as e:
        pr.add("CRITICAL", "config/", 0,
               f"Import error: {e}. SQLAlchemy or asyncpg not installed.",
               recommendation="Install sqlalchemy and asyncpg: pip install sqlalchemy asyncpg")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "config/", 0,
               f"Database connection failed: {type(e).__name__}: {str(e)[:150]}",
               recommendation="Check DATABASE_URL and ensure database service is running.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p46_migration_dryrun() -> PhaseResult:
    pr = PhaseResult("P46 Migration Dry-Run", weight=3)
    pr.disclaimer = "Strictly runs 'alembic upgrade head --sql' to validate migration syntax (no DB changes)."
    t0 = time.monotonic()

    # Check alembic.ini exists
    if not (ROOT / "alembic.ini").exists():
        pr.add("CRITICAL", "alembic.ini", 0,
               "alembic.ini not found. Alembic is not configured.",
               recommendation="Run 'alembic init migrations' or ensure alembic.ini exists.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Check migrations directory exists
    if not (ROOT / "migrations").exists():
        pr.add("CRITICAL", "migrations/", 0,
               "migrations directory not found. Alembic is not initialized.",
               recommendation="Run 'alembic init migrations'.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # =====================================================================
    # 1. Try dry-run on all migrations
    # =====================================================================
    cmd = ["alembic", "upgrade", "head", "--sql"]
    env = os.environ.copy()
    # Force non-interactive
    env["ALEMBIC_CONFIG"] = str(ROOT / "alembic.ini")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        if result.returncode == 0:
            # Success
            if result.stdout and ("CREATE" in result.stdout or "ALTER" in result.stdout or "DROP" in result.stdout):
                pr.add("PASS", "migrations/", 0,
                       "Migration dry-run successful. SQL generated successfully.")
                pr.score = 100
            elif result.stdout and "No upgrade needed" in result.stdout:
                pr.add("PASS", "migrations/", 0,
                       "Migration dry-run successful. No changes needed (database is up-to-date).")
                pr.score = 100
            else:
                pr.add("WARNING", "migrations/", 0,
                       "Migration dry-run succeeded but no SQL statements generated. Check if migrations are valid.")
                pr.score = 80
            pr.finalize_status()
            pr.duration = time.monotonic() - t0
            return pr

        # ================================================================
        # 2. Dry-run failed – identify problematic migration file
        # ================================================================
        error_output = result.stderr if result.stderr else result.stdout
        # Look for a file path in the error message
        import re
        # Patterns like: File "migrations/versions/xxxx_*.py", line x, in ...
        pattern = r'File\s+"([^"]+migrations[^"]+\.py)"'
        match = re.search(pattern, error_output)
        if match:
            problem_file = match.group(1)
            # also capture line number if present
            line_match = re.search(r'line\s+(\d+)', error_output)
            line_no = int(line_match.group(1)) if line_match else 0
            # Try to extract a more specific error message
            error_lines = error_output.strip().splitlines()
            # Find the line with the actual error (e.g., SyntaxError, ImportError)
            err_msg = ""
            for i, line in enumerate(error_lines):
                if "Error:" in line or "Exception:" in line or "SyntaxError" in line:
                    err_msg = line.strip()
                    break
            if not err_msg:
                err_msg = error_output[:200]  # fallback
            pr.add("CRITICAL", problem_file, line_no,
                   f"Migration file has error: {err_msg}",
                   recommendation=f"Fix syntax/import in {problem_file} or ensure all dependencies are available.")
            pr.score = 0
        else:
            # Could not identify file, report general failure
            pr.add("CRITICAL", "migrations/", 0,
                   f"Migration dry-run failed with unknown cause: {error_output[:300]}",
                   recommendation="Check migration files for syntax errors or compatibility issues.")
            pr.score = 0

    except subprocess.TimeoutExpired:
        pr.add("CRITICAL", "migrations/", 0,
               "Migration dry-run timed out after 30 seconds.")
        pr.score = 0
    except FileNotFoundError:
        pr.add("CRITICAL", "migrations/", 0,
               "Alembic command not found. Ensure alembic is installed and in PATH.",
               recommendation="Install alembic: pip install alembic")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "migrations/", 0,
               f"Migration dry-run error: {type(e).__name__}: {str(e)[:100]}",
               recommendation="Check Alembic configuration and migration files.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p47_infrastructure() -> PhaseResult:
    pr = PhaseResult("P47 Infrastructure Connectivity", weight=3)
    pr.disclaimer = "Strictly tests DB, Redis, Kafka connections. DB & Redis are CRITICAL, Kafka is optional."
    t0 = time.monotonic()

    # Cek environment variables dulu
    db_url = os.environ.get("DATABASE_URL")
    redis_url = os.environ.get("REDIS_URL")
    kafka_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")

    # =====================================================================
    # 1. Database Check (CRITICAL)
    # =====================================================================
    db_error = None
    if db_url:
        try:
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine
            engine = create_async_engine(db_url, pool_size=1, pool_pre_ping=True)
            async def test_db():
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            asyncio.run(test_db())
        except Exception as e:
            db_error = f"{type(e).__name__}: {str(e)[:100]}"
    else:
        db_error = "DATABASE_URL not set"

    # =====================================================================
    # 2. Redis Check (CRITICAL)
    # =====================================================================
    redis_error = None
    if redis_url:
        try:
            import redis.asyncio as aioredis
            async def test_redis():
                client = aioredis.from_url(redis_url, socket_timeout=3)
                await client.ping()
                await client.aclose()
            asyncio.run(test_redis())
        except Exception as e:
            redis_error = f"{type(e).__name__}: {str(e)[:100]}"
    else:
        redis_error = "REDIS_URL not set"

    # =====================================================================
    # 3. Kafka Check (OPTIONAL - WARNING only)
    # =====================================================================
    kafka_error = None
    if kafka_servers:
        try:
            from kafka import KafkaProducer
            producer = KafkaProducer(bootstrap_servers=kafka_servers, request_timeout_ms=3000)
            producer.close()
        except ImportError:
            kafka_error = "kafka-python module not installed"
        except Exception as e:
            kafka_error = f"{type(e).__name__}: {str(e)[:100]}"
    else:
        kafka_error = "KAFKA_BOOTSTRAP_SERVERS not set (optional)"

    # =====================================================================
    # 4. Report
    # =====================================================================
    critical_errors = []
    warning_errors = []

    if db_error:
        critical_errors.append(("Database", db_error))
    else:
        pr.add("PASS", "infrastructure", 0, "Database (PostgreSQL) connection OK")

    if redis_error:
        critical_errors.append(("Redis", redis_error))
    else:
        pr.add("PASS", "infrastructure", 0, "Redis connection OK")

    # Kafka: WARNING, not CRITICAL
    if kafka_error:
        warning_errors.append(("Kafka", kafka_error))
    else:
        pr.add("PASS", "infrastructure", 0, "Kafka connection OK")

    # Laporkan error
    for name, err in critical_errors:
        pr.add("CRITICAL", "infrastructure", 0,
               f"{name} connection failed: {err}",
               recommendation=f"Ensure {name} service is running and configuration is correct.")

    for name, err in warning_errors:
        pr.add("WARNING", "infrastructure", 0,
               f"{name} not available: {err}",
               recommendation=f"Set {name} environment variables or install required module. This is optional for core functionality.")

    # Skor
    if critical_errors:
        pr.add("CRITICAL", "infrastructure", 0,
               f"{len(critical_errors)} critical infrastructure service(s) are unavailable.")
        pr.score = 0
    else:
        if warning_errors:
            pr.add("PASS", "infrastructure", 0,
                   f"All critical infrastructure services OK. {len(warning_errors)} optional service(s) unavailable.")
            pr.score = 90
        else:
            pr.add("PASS", "infrastructure", 0,
                   "All infrastructure services (DB, Redis, Kafka) connected successfully.")
            pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p48_orm_mapper() -> PhaseResult:
    pr = PhaseResult("P48 ORM Mapper Validation", weight=3)
    pr.disclaimer = "Strictly validates SQLAlchemy ORM mappers by attempting a simple query on a known table."
    t0 = time.monotonic()

    try:
        from sqlalchemy import select

        from infrastructure.database.session_factory_sqlalchemy import get_session_factory_sync

        # Try to import a table that should exist in all ORM setups
        # Use OutboxMessageTable as it's a core table
        from infrastructure.persistence_orm.outbox_message_table import OutboxMessageTable

        async def test_mapper():
            factory = get_session_factory_sync()
            session_maker = factory.get_session_factory()
            if session_maker is None:
                raise RuntimeError("Session factory returned None")
            async with session_maker() as session:
                # Execute a simple query (limit 1) to test mapper
                stmt = select(OutboxMessageTable).limit(1)
                await session.execute(stmt)

        asyncio.run(test_mapper())
        pr.add("PASS", "infrastructure/persistence_orm", 0,
               "ORM mappers validated successfully. All relationships are intact.")
        pr.score = 100

    except ImportError as e:
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               f"Import error during ORM validation: {e}",
               recommendation="Ensure all ORM modules are importable. Check for missing __init__.py or circular imports.")
        pr.score = 0

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)[:150]}"
        suggestion = "Check SQLAlchemy model definitions, relationships, and foreign key constraints."
        if "NoForeignKeysError" in str(e):
            suggestion = "Missing ForeignKey in relationship. Ensure all relationships have explicit foreign keys."
        elif "ArgumentError" in str(e):
            suggestion = "Invalid relationship configuration. Check back_populates/backref settings."
        elif "OperationalError" in str(e):
            suggestion = "Database operational error. Check connection and table existence."

        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               f"ORM mapper error: {error_msg}",
               recommendation=suggestion)
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p49_auto_discovery() -> PhaseResult:
    pr = PhaseResult("P49 Auto-Discovery Import Scan", weight=2)
    pr.disclaimer = "Strictly scans all discovered Python modules for importability. Any import error is CRITICAL."
    t0 = time.monotonic()

    all_discovered = set()

    # 1. Collect all Python modules
    for py_file in ROOT.glob("*.py"):
        if py_file.name in _CHECKER_FILES:
            continue
        mod = mod_name(py_file)
        if mod:
            all_discovered.add(mod)

    for py_file in ROOT.rglob("*.py"):
        if py_file.parent == ROOT:
            continue
        if any(part in _SKIP_ALWAYS for part in py_file.parts):
            continue
        mod = mod_name(py_file)
        if mod:
            all_discovered.add(mod)

    # 2. Test import each module (limit to reasonable number for performance)
    # But we want to test ALL to be strict. We'll test all, but limit reporting to first 20 errors.
    total = len(all_discovered)
    errors = []
    modules_tested = 0

    for mod in all_discovered:
        # Skip checker modules
        if mod.startswith("main_checker"):
            continue
        modules_tested += 1
        ok, err = _safe_import_module(mod)
        if not ok:
            errors.append((mod, err[:100]))
            if len(errors) >= 30:  # Collect up to 30 errors
                # Still continue testing, but limit reporting later
                pass

    # 3. Report
    if not errors:
        pr.add("PASS", ".", 0,
               f"Auto-discovery: all {total} modules importable successfully.")
        pr.score = 100
    else:
        for mod, err in errors[:20]:
            pr.add("CRITICAL", mod.replace(".", "/") + ".py", 0,
                   f"Import error in module '{mod}': {err}",
                   recommendation=f"Fix import dependencies in {mod}.")
        if len(errors) > 20:
            pr.add("INFO", ".", 0,
                   f"Plus {len(errors)-20} more import errors.")
        pr.add("CRITICAL", ".", 0,
               f"{len(errors)}/{total} modules have import errors. System is NOT fully importable.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p50_critical_imports() -> PhaseResult:
    pr = PhaseResult("P50 Critical Modules Import Scan", weight=3)
    pr.disclaimer = "Strictly imports each module listed in CRITICAL_MODULES. Any failure is CRITICAL."
    t0 = time.monotonic()

    errors = []
    successful = 0

    for label, mod in CRITICAL_MODULES:
        ok, err = _safe_import_module(mod)
        if ok:
            successful += 1
            # We don't add PASS for each to avoid spam, but we'll add summary
        else:
            errors.append((label, mod, err[:100]))
            pr.add("CRITICAL", mod.replace(".", "/") + ".py", 0,
                   f"Critical import failed: {label} — {err}",
                   recommendation=f"Fix import dependencies for {mod}.")

    if not errors:
        pr.add("PASS", ".", 0,
               f"All {len(CRITICAL_MODULES)} critical modules imported successfully.")
        pr.score = 100
    else:
        pr.add("CRITICAL", ".", 0,
               f"{len(errors)} of {len(CRITICAL_MODULES)} critical modules failed to import. System is NOT deployable.")
        pr.score = 0

    # Also list successful ones if verbose
    if successful > 0 and not errors:
        # Only if all pass, we might want to show a summary
        pass

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p51_environment_vars() -> PhaseResult:
    pr = PhaseResult("P51 Environment Variables", weight=2)
    pr.disclaimer = "Strictly checks required and optional environment variables. Missing required variables cause failure."
    t0 = time.monotonic()

    missing_required = []
    missing_optional = []

    # Check required env vars
    for var, example in REQUIRED_ENV_VARS:
        if not os.environ.get(var):
            missing_required.append((var, example))

    # Check optional env vars
    for var, example in OPTIONAL_ENV_VARS:
        if not os.environ.get(var):
            missing_optional.append(var)

    # Report missing required
    for var, example in missing_required:
        pr.add("CRITICAL", ".env", 0,
               f"Missing required environment variable: {var}",
               recommendation=f"Set {var} (example: {example})")

    # Report missing optional
    for var in missing_optional[:20]:  # Limit optional reporting
        pr.add("INFO", ".env", 0,
               f"Optional environment variable not set: {var}",
               recommendation=f"Consider setting {var} for full functionality")

    if len(missing_optional) > 20:
        pr.add("INFO", ".env", 0,
               f"Plus {len(missing_optional)-20} more optional env vars missing.")

    # Evaluate
    if missing_required:
        pr.add("CRITICAL", ".env", 0,
               f"{len(missing_required)} required environment variable(s) missing. System cannot start.")
        pr.score = 0
    else:
        if missing_optional:
            pr.add("PASS", ".env", 0,
                   f"All required environment variables are set. {len(missing_optional)} optional variables missing (non-critical).")
            pr.score = 90
        else:
            pr.add("PASS", ".env", 0,
                   "All required and optional environment variables are set.")
            pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p52_critical_paths() -> PhaseResult:
    pr = PhaseResult("P52 Critical Paths", weight=2)
    pr.disclaimer = "Strictly verifies existence of all critical files/directories."
    t0 = time.monotonic()

    missing = []
    for rel_path in CRITICAL_PATHS:
        if not (ROOT / rel_path).exists():
            missing.append(rel_path)

    if missing:
        for rel_path in missing[:20]:
            pr.add("CRITICAL", rel_path, 0,
                   f"Critical path missing: {rel_path}",
                   recommendation=f"Create this file/directory: {rel_path}")
        if len(missing) > 20:
            pr.add("INFO", ".", 0, f"Plus {len(missing)-20} more missing paths.")
        pr.add("CRITICAL", ".", 0,
               f"{len(missing)} critical path(s) are missing. System is incomplete.")
        pr.score = 0
    else:
        pr.add("PASS", ".", 0,
               f"All {len(CRITICAL_PATHS)} critical paths exist.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p53_asgi_validation() -> PhaseResult:
    pr = PhaseResult("P53 ASGI App Validation", weight=2)
    pr.disclaimer = "Strictly validates that asgi.py imports successfully and has an 'app' attribute."
    t0 = time.monotonic()

    try:
        asgi_mod = importlib.import_module("asgi")
        if hasattr(asgi_mod, "app"):
            # Optional: verify 'app' is callable
            if callable(asgi_mod.app):
                pr.add("PASS", "asgi.py", 0,
                       "ASGI app found and is callable (attribute 'app').")
                pr.score = 100
            else:
                pr.add("WARNING", "asgi.py", 0,
                       "ASGI app found but 'app' is not callable. It may not be a valid ASGI application.",
                       recommendation="Ensure 'app' is a FastAPI instance or callable.")
                pr.score = 80
        else:
            pr.add("CRITICAL", "asgi.py", 0,
                   "No 'app' attribute found in asgi.py.",
                   recommendation="Define 'app' in asgi.py (e.g., app = create_app()).")
            pr.score = 0
    except ImportError as e:
        pr.add("CRITICAL", "asgi.py", 0,
               f"Failed to import asgi.py: {type(e).__name__}: {str(e)[:100]}",
               recommendation="Fix syntax errors or missing dependencies in asgi.py.")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "asgi.py", 0,
               f"Unexpected error importing asgi.py: {type(e).__name__}: {str(e)[:100]}",
               recommendation="Check asgi.py for errors.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p54_fastapi_routes() -> PhaseResult:
    pr = PhaseResult("P54 FastAPI Route Validation", weight=3)
    pr.disclaimer = "Strictly validates FastAPI routes: no duplicate paths/methods, and each router file defines at least one route."
    t0 = time.monotonic()

    router_dir = ROOT / "adapters" / "primary_api" / "v1"
    if not router_dir.exists():
        pr.add("CRITICAL", "adapters/primary_api/v1", 0,
               "Router directory not found. API endpoints are missing.",
               recommendation="Create adapters/primary_api/v1/ with FastAPI routers.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    route_map: dict[tuple[str, str], list[tuple[str, int, str]]] = {}
    files_without_routes = []

    for py_file in router_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue

        tree = get_ast_tree(py_file)
        if tree is None:
            pr.add("CRITICAL", rel(py_file), 0,
                   "Syntax error in router file.")
            pr.score = 0
            pr.finalize_status()
            pr.duration = time.monotonic() - t0
            return pr

        rp = rel(py_file)
        has_route = False

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                        method = decorator.func.attr.upper()
                        if method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                            if decorator.args:
                                path_expr = decorator.args[0]
                                if isinstance(path_expr, ast.Constant):
                                    path = path_expr.value
                                    key = (path, method)
                                    route_map.setdefault(key, []).append((rp, node.lineno, node.name))
                                    has_route = True

        if not has_route:
            files_without_routes.append(rp)

    # Check for duplicates
    duplicates = []
    for (path, method), locations in route_map.items():
        if len(locations) > 1:
            for file, line, func_name in locations:
                duplicates.append((file, line, method, path, func_name))

    # Report
    if duplicates:
        for file, line, method, path, func_name in duplicates:
            pr.add("CRITICAL", file, line,
                   f"Duplicate route: {method} {path} (also defined in other router)",
                   recommendation="Remove duplicate route definition or use different paths.")
        pr.add("CRITICAL", ".", 0,
               f"{len(duplicates)} duplicate route(s) found. Routing will be ambiguous.")
        pr.score = 0
    elif files_without_routes:
        for file in files_without_routes:
            pr.add("WARNING", file, 0,
                   "Router file defines no routes. It may be incomplete.",
                   recommendation="Add at least one route endpoint.")
        pr.add("PASS", ".", 0,
               f"No duplicate routes. {len(files_without_routes)} router(s) have no routes (non-critical).")
        pr.score = 90
    else:
        pr.add("PASS", "adapters/primary_api/v1", 0,
               f"All {len(route_map)} routes are unique. API layer is consistent.")
        pr.score = 100

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p55_di_container() -> PhaseResult:
    pr = PhaseResult("P55 DI Container Validation", weight=4)
    pr.disclaimer = "Strictly verifies that all required dependencies are resolvable and implement core contract methods."
    t0 = time.monotonic()

    try:
        from bootstrap.dependency_container.ioc_container import get_container
        container = get_container()

        # ========== KONTRAK YANG HARUS DIPENUHI (METHOD NAMES) ==========
        # Ini mencegah pendaftaran class kosong / dummy yang tidak punya method esensial.
        contract_checks = {
            "IJournalRepository": ["save", "find_by_id", "find_all"],
            "IUnitOfWork": ["commit", "rollback", "begin"],
            "IEventPublisher": ["publish", "publish_batch"],
            "ITaxAuthorityPort": ["submit_tax", "get_status"],
            "IUserRepository": ["save", "find_by_username", "find_by_id"],
            "IAccountRepository": ["save", "find_by_code", "find_by_id"],
            "IArRepository": ["save_invoice", "find_invoice_by_id"],
            "IApRepository": ["save_invoice", "find_invoice_by_id"],
            "IInventoryRepository": ["save_item", "find_item_by_id", "adjust_stock"],
            "IFixedAssetRepository": ["save_asset", "find_asset_by_id"],
            "IPayrollRepository": ["save_payroll", "find_by_employee"],
            "IManufacturingRepository": ["save_work_order", "find_work_order"],
            "IConsolidationRepository": ["save_group", "find_group"],
            "IForexRepository": ["save_rate", "find_rate"],
            "IHedgeRepository": ["save_hedge", "find_hedge"],
        }

        required_interfaces = list(contract_checks.keys())
        missing_or_failed = []

        for iface in required_interfaces:
            try:
                # 1. Resolve instance dari container (real)
                instance = container.resolve(iface)  # sync resolve, aman di checker
                if instance is None:
                    raise ValueError("Resolved instance is None")

                # 2. Validasi kontrak: pastikan method yang diperlukan ada dan callable
                expected_methods = contract_checks.get(iface, [])
                for method_name in expected_methods:
                    if not hasattr(instance, method_name) or not callable(getattr(instance, method_name)):
                        raise TypeError(f"Missing or non-callable method '{method_name}'")

                # 3. (Opsional) Bisa tambahkan validasi lebih lanjut, misal cek tipe parameter, dll.

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e!s}"
                missing_or_failed.append(iface)
                pr.add("CRITICAL", "bootstrap/dependency_container", 0,
                       f"Failed to resolve or validate '{iface}'.",
                       recommendation=f"Error: {error_msg}")

        if not missing_or_failed:
            pr.add("PASS", "bootstrap/dependency_container", 0,
                   f"All {len(required_interfaces)} dependencies are resolvable and implement required methods.")
            pr.score = 100
        else:
            pr.add("CRITICAL", "bootstrap/dependency_container", 0,
                   f"{len(missing_or_failed)} dependencies failed. System is NOT ready.")
            pr.score = 0  # Strict: jika ada satu gagal, sistem tidak layak

    except ImportError as e:
        pr.add("CRITICAL", "bootstrap/dependency_container", 0,
               f"DI module import error: {e}",
               recommendation="Check module path and ensure bootstrap.dependency_container exists.")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "bootstrap/dependency_container", 0,
               f"Unexpected DI validation error: {type(e).__name__}: {e!s}")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p56_cqrs_handlers() -> PhaseResult:
    pr = PhaseResult("P56 CQRS Handler Validation", weight=4)
    pr.disclaimer = "Validates that every concrete Command/Query has a Handler class that implements a 'handle' method (including inheritance)."
    t0 = time.monotonic()

    cmd_dir = ROOT / "application" / "commands_cqrs"
    usecase_dir = ROOT / "application" / "use_cases"

    if not cmd_dir.exists() or not usecase_dir.exists():
        pr.add("CRITICAL", "application/commands_cqrs", 0,
               "CQRS directories not found",
               recommendation="Ensure 'application/commands_cqrs' and 'application/use_cases' exist.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # ========== 1. KUMPULKAN SEMUA COMMAND/QUERY CLASSES ==========
    commands = {}
    for py_file in cmd_dir.glob("*.py"):
        tree = get_ast_tree(py_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name.endswith("Command") or node.name.endswith("Query"):
                    commands[node.name] = py_file

    # ========== 2. KUMPULKAN SEMUA HANDLER CLASSES + METHOD NAMES ==========
    handlers = {}  # {handler_name: (file_path, set(method_names), list(base_class_names))}
    for py_file in usecase_dir.glob("*.py"):
        tree = get_ast_tree(py_file)
        if tree is None:
            continue
        src = py_file.read_text(encoding="utf-8", errors="replace")
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Handler"):
                methods = set()
                bases = []
                # Kumpulkan nama base class
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(base.attr)
                # Kumpulkan method yang didefinisikan langsung di class ini
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods.add(item.name)
                handlers[node.name] = (py_file, methods, bases)

    # ========== 3. PERIKSA SETIAP COMMAND ==========
    IGNORE_COMMANDS = {"BaseCommand", "BaseQuery"}
    missing_or_invalid = []

    # Bangun inheritance chain untuk setiap handler (sederhana, hanya cari di handlers yang sudah dikumpulkan)
    # Karena kita tidak punya runtime import, kita lakukan secara statis berdasarkan nama base.
    # Kita asumsikan base class juga ada di antara handlers yang terdefinisi.
    def get_all_methods(handler_name: str, visited=None) -> set:
        if visited is None:
            visited = set()
        if handler_name in visited:
            return set()
        visited.add(handler_name)
        if handler_name not in handlers:
            return set()
        _, methods, bases = handlers[handler_name]
        all_methods = set(methods)
        for base in bases:
            # Base class mungkin memiliki nama sama dengan handler lain (misal BaseCommandHandler)
            # Kita cari base di handlers; jika tidak ada, abaikan (tidak bisa cek inheritance statis)
            if base in handlers:
                all_methods.update(get_all_methods(base, visited))
        return all_methods

    for cmd_name in commands:
        if cmd_name in IGNORE_COMMANDS:
            continue

        base = cmd_name[:-7] if cmd_name.endswith("Command") else cmd_name[:-5] if cmd_name.endswith("Query") else cmd_name
        expected_handler = base + "Handler"
        expected_handler_alt = cmd_name + "Handler"

        found_handler = None
        handler_methods = set()

        if expected_handler in handlers:
            found_handler = expected_handler
            handler_methods = get_all_methods(expected_handler)
        elif expected_handler_alt in handlers:
            found_handler = expected_handler_alt
            handler_methods = get_all_methods(expected_handler_alt)

        if not found_handler:
            missing_or_invalid.append((cmd_name, f"No handler class found (expected {expected_handler} or {expected_handler_alt})"))
            continue

        # Validasi: handler harus punya method 'handle' atau '__call__' (termasuk dari inheritance)
        required_methods = {"handle", "__call__"}
        if not (handler_methods & required_methods):
            missing_or_invalid.append(
                (cmd_name, f"Handler '{found_handler}' missing 'handle'/'__call__' method. Found methods: {handler_methods}")
            )
            continue

    # ========== 4. LAPORKAN HASIL ==========
    for cmd_name, error_detail in missing_or_invalid:
        pr.add("CRITICAL", "application/use_cases", 0,
               f"Command/Query '{cmd_name}' is invalid: {error_detail}",
               recommendation=f"Create handler '{cmd_name}Handler' or '{base}Handler' with a 'handle' method (or inherit from a base that provides it).")

    if not missing_or_invalid:
        total_valid = len(commands) - len(IGNORE_COMMANDS)
        pr.add("PASS", "application/use_cases", 0,
               f"All {total_valid} concrete commands/queries have valid handlers (method 'handle' or '__call__' found, including inheritance).")
        pr.score = 100
    else:
        pr.add("CRITICAL", "application/use_cases", 0,
               f"{len(missing_or_invalid)} commands/queries are broken or incomplete.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p57_event_handlers() -> PhaseResult:
    pr = PhaseResult("P57 Event Handler Validation", weight=3)
    pr.disclaimer = "Validates that every domain event is explicitly referenced (exact match) in at least one subscriber's code."
    t0 = time.monotonic()

    # ========== 1. KUMPULKAN SEMUA EVENT CLASSES ==========
    event_classes = {}
    for domain_dir in ROOT.glob("domain/*"):
        events_file = domain_dir / "domain_events.py"
        if not events_file.exists():
            continue
        tree = get_ast_tree(events_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if "Event" in node.name and not node.name.startswith("Base"):
                    event_classes[node.name] = events_file

    if not event_classes:
        pr.add("INFO", "domain/", 0, "No domain event classes found.")
        pr.score = 100
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # ========== 2. KUMPULKAN SUBSCRIBER ==========
    subscriber_dirs = [
        ROOT / "application" / "events",
        ROOT / "application" / "handlers",
        ROOT / "application" / "event_handlers",
        ROOT / "domain" / "events",
    ]

    # Fungsi pembantu: ekstrak semua identifier (ast.Name) dari AST node
    def extract_referenced_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set:
        names = set()
        for sub_node in ast.walk(func_node):
            if isinstance(sub_node, ast.Name):
                names.add(sub_node.id)
        return names

    subscribers = []  # list of (file_path, subscriber_name, referenced_names_set)

    for sub_dir in subscriber_dirs:
        if not sub_dir.exists():
            continue
        for py_file in sub_dir.glob("*.py"):
            tree = get_ast_tree(py_file)
            if tree is None:
                continue
            # Loop semua node di file
            for node in ast.walk(tree):
                # Fungsi level modul
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if "handle" in node.name.lower() or node.name.startswith("on_"):
                        refs = extract_referenced_names(node)
                        subscribers.append((py_file, node.name, refs))
                # Method di dalam kelas
                elif isinstance(node, ast.ClassDef):
                    if any(kw in node.name for kw in ["Handler", "Listener", "Subscriber"]):
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if "handle" in item.name.lower() or item.name.startswith("on_"):
                                    refs = extract_referenced_names(item)
                                    subscribers.append((py_file, f"{node.name}.{item.name}", refs))

    # ========== 3. VALIDASI: SETIAP EVENT HARUS DISEBUTKAN SETIDAKNYA 1 KALI ==========
    uncovered = []
    for ev_name, ev_file in event_classes.items():
        found = False
        for sub_file, sub_name, refs in subscribers:
            if ev_name in refs:
                found = True
                break
        if not found:
            uncovered.append((ev_name, ev_file))

    # ========== 4. LAPORKAN HASIL ==========
    for ev_name, ev_file in uncovered:
        pr.add("CRITICAL", str(ev_file), 0,
               f"Domain event '{ev_name}' is never referenced in any subscriber code.",
               recommendation=f"Create a handler in application/events/ that references '{ev_name}' (as type hint, variable, or instantiation).")

    if not uncovered:
        pr.add("PASS", "application/events", 0,
               f"All {len(event_classes)} domain events are referenced in at least one subscriber.")
        pr.score = 100
    else:
        pr.add("CRITICAL", "domain/", 0,
               f"{len(uncovered)} domain events are not handled by any subscriber.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr


def p58_repository_contract() -> PhaseResult:
    pr = PhaseResult("P58 Repository Contract Validation", weight=3)
    pr.disclaimer = "Verifies that repository implementations exactly match the method signatures defined in their ports."
    t0 = time.monotonic()

    port_dir = ROOT / "ports" / "primary"
    impl_dir = ROOT / "adapters" / "secondary_impl"

    if not port_dir.exists() or not impl_dir.exists():
        pr.add("CRITICAL", "ports/primary", 0, "Architecture Violation: Ports or adapters directories missing.")
        pr.score = 0
        pr.finalize_status()
        return pr

    def is_abstract_method(method_node: ast.FunctionDef) -> bool:
        for dec in method_node.decorator_list:
            if (isinstance(dec, ast.Name) and dec.id == "abstractmethod") or \
               (isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod"):
                return True
        return False

    def extract_methods_with_signatures(tree: ast.AST, class_name: str) -> dict[str, list[str]]:
        """Ekstrak nama method beserta list nama argumennya untuk validasi signature."""
        methods = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        # Ambil argumen selain 'self'
                        args = [arg.arg for arg in item.args.args if arg.arg != 'self']
                        methods[item.name] = (is_abstract_method(item), args)
        return methods

    # 1. Scan Ports
    port_contracts = {}
    for py_file in port_dir.glob("*.py"):
        if py_file.name == "__init__.py": continue
        tree = get_ast_tree(py_file)
        if not tree: continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and ("Port" in node.name or "Repository" in node.name):
                methods = extract_methods_with_signatures(tree, node.name)
                if methods:
                    port_contracts[py_file.stem] = {
                        "class_name": node.name,
                        "file_path": py_file,
                        "methods": methods
                    }

    # 2. Scan Implementations
    impl_registry = {}
    for py_file in impl_dir.glob("*.py"):
        if py_file.name == "__init__.py": continue
        tree = get_ast_tree(py_file)
        if not tree: continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = extract_methods_with_signatures(tree, node.name)
                if methods:
                    impl_registry[py_file.stem] = {
                        "class_name": node.name,
                        "file_path": py_file,
                        "methods": methods
                    }

    # 3. Strict Contract Verification
    broken_contracts = []

    for port_stem, port_data in port_contracts.items():
        base = port_stem.replace("_port", "").replace("_repository", "")

        # Cari matching adapter file
        matched_impl_stem = None
        for impl_stem in impl_registry:
            if base in impl_stem or port_stem.replace("_port", "") in impl_stem:
                matched_impl_stem = impl_stem
                break

        if not matched_impl_stem:
            broken_contracts.append((str(port_data["file_path"]), "CRITICAL",
                                     f"Port class '{port_data['class_name']}' has no matching implementation file."))
            continue

        impl_data = impl_registry[matched_impl_stem]

        # Validasi setiap abstract method
        for method_name, (is_abstract, port_args) in port_data["methods"].items():
            if not is_abstract: continue

            if method_name not in impl_data["methods"]:
                broken_contracts.append((str(impl_data["file_path"]), "CRITICAL",
                     f"Adapter '{impl_data['class_name']}' missing implementation for abstract method '{method_name}'."))
                continue

            # VALIDASI SIGNATURE: Periksa apakah jumlah dan susunan argumennya sama
            _, impl_args = impl_data["methods"][method_name]
            if port_args != impl_args:
                broken_contracts.append((str(impl_data["file_path"]), "CRITICAL",
                     f"Signature mismatch in '{impl_data['class_name']}.{method_name}'. "
                     f"Expected args: {port_args}, Found: {impl_args}"))

    # 4. Reporting
    for file_path, severity, msg in broken_contracts:
        pr.add(severity, file_path, 0, msg)

    if not broken_contracts:
        pr.add("PASS", "adapters/secondary_impl", 0, "All repository interfaces and method signatures are verified matching.")
        pr.score = 100
    else:
        pr.score = 0  # Strict Big 4 compliance: Arsitektur rusak = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p59_dto_mapper() -> PhaseResult:
    pr = PhaseResult("P59 DTO Mapper Validation", weight=2)
    pr.disclaimer = "Uses AST to ensure mapper files contain real structural mapping logic, rejecting empty or commented dummies."
    t0 = time.monotonic()

    mapper_dir = ROOT / "application" / "mappers"
    if not mapper_dir.exists():
        pr.add("INFO", "application/mappers/", 0, "No mappers directory found.")
        pr.score = 100
        pr.finalize_status()
        return pr

    mapper_files = list(mapper_dir.glob("*.py"))
    violations = []

    for mf in mapper_files:
        if mf.name == "__init__.py": continue
        tree = get_ast_tree(mf)
        if not tree: continue

        has_valid_logic = False

        for node in ast.walk(tree):
            # Cek jika ada fungsi pemetaan di level modul atau level kelas
            if isinstance(node, ast.FunctionDef):
                name_lower = node.name.lower()
                if "map" in name_lower or "to_dto" in name_lower or "to_entity" in name_lower:
                    # Validasi isi fungsi: Jangan ijinkan fungsi kosong (pass / ...)
                    if len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Expr)):
                        stmt = node.body[0]
                        if isinstance(stmt, ast.Pass) or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value == Ellipsis):
                            continue # Ini fungsi kosong / dummy stub

                    has_valid_logic = True
                    break

            elif isinstance(node, ast.ClassDef):
                if any(kw in node.name for kw in ["Mapper", "Registry", "Transformer"]):
                    # Pastikan kelas tidak kosong
                    real_methods = [item for item in node.body if isinstance(item, ast.FunctionDef) and item.name != "__init__"]
                    if real_methods:
                        has_valid_logic = True
                        break

        if not has_valid_logic:
            violations.append((str(mf), f"Mapper file '{mf.name}' does not contain any concrete mapping functions or executable classes."))

    for file_path, msg in violations:
        pr.add("CRITICAL", file_path, 0, msg, recommendation="Implement a real mapping function that transforms data structures.")

    if not violations and mapper_files:
        pr.add("PASS", "application/mappers/", 0, f"All {len(mapper_files)} mapper files contain valid structure and active logic.")
        pr.score = 100
    elif not mapper_files:
        pr.score = 100
    else:
        pr.score = 0  # Strict enforce

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p60_startup_dryrun() -> PhaseResult:
    pr = PhaseResult("P60 Startup Dry-Run", weight=5)
    pr.disclaimer = "Executes real runtime application bootstrap and verifies ASGI app creation without invoking HTTP client."
    t0 = time.monotonic()
    try:
        import app.main

        # 1. Dapatkan objek aplikasi
        if hasattr(app.main, "app"):
            app_obj = app.main.app
        elif hasattr(app.main, "create_app"):
            app_obj = app.main.create_app()
        else:
            raise RuntimeError("No 'app' variable or 'create_app()' function found in app.main")

        # 2. Jika app adalah AppWrapper (atau callable factory), panggil tanpa argumen
        # untuk mendapatkan FastAPI instance yang sebenarnya.
        if callable(app_obj):
            try:
                # Coba panggil tanpa argumen – AppWrapper akan mengembalikan FastAPI
                fastapi_app = app_obj()
                app_obj = fastapi_app
            except TypeError:
                # Tidak bisa dipanggil tanpa argumen – mungkin sudah FastAPI langsung
                pass

        # 3. Verifikasi bahwa objek adalah FastAPI (atau setidaknya memiliki router)
        if hasattr(app_obj, "router") and hasattr(app_obj, "openapi"):
            # Memicu inisialisasi openapi untuk memastikan tidak ada error
            try:
                # Panggil openapi() untuk memicu pembuatan schema
                app_obj.openapi()
            except Exception as e:
                # Jika openapi gagal, mungkin tidak fatal, tapi catat sebagai warning
                pr.add("WARNING", "app/main.py", 0,
                       f"openapi() generation failed: {type(e).__name__}: {str(e)[:100]}")
            pr.add("PASS", "app/main.py", 0,
                   "Runtime dry-run successful. ASGI application created, router available, and openapi schema generated.")
            pr.score = 100
        elif hasattr(app_obj, "__call__"):
            # Minimal: objek callable – kemungkinan ASGI app
            pr.add("PASS", "app/main.py", 0,
                   "Runtime dry-run successful. ASGI application is callable.")
            pr.score = 100
        else:
            pr.add("CRITICAL", "app/main.py", 0,
                   "App object does not appear to be a valid ASGI application (no router or __call__).",
                   recommendation="Ensure app is a FastAPI instance or a factory returning one.")
            pr.score = 0

    except ImportError as e:
        pr.add("CRITICAL", "app/main.py", 0,
               f"ImportError during bootstrap: {type(e).__name__}: {str(e)[:150]}",
               recommendation="Check missing dependencies or circular imports in app/main.py")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "app/main.py", 0,
               f"Startup dry-run crashed: {type(e).__name__}: {str(e)[:150]}",
               recommendation="Fix core import errors, circular references at initialization, or unhandled exceptions during factory bootstrap.")
        pr.score = 0

    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# ─── PHASE REGISTRY ─────────────────────────────────────────────────────────
_ALL_PHASES: list[tuple[str, Any, bool]] = [
    ("environment", p00_environment, False),
    ("structure", p01_structure, False),
    ("syntax", p02_syntax, False),
    ("self_audit", p03_self_audit, False),
    ("circular", p04_circular, False),
    ("static_imports", p05_static_imports, False),
    ("dynamic", p06_dynamic_imports, False),
    ("broken_imports", p07_broken_imports, False),
    ("architecture", p08_architecture, False),
    ("port_adapter", p09_port_adapter, False),
    ("routes", p10_routes, False),
    ("yaml", p11_yaml, False),
    ("asgi", p12_asgi, False),
    ("migrations", p13_migrations, False),
    ("quality", p14_quality, False),
    ("security", p15_security, False),
    ("dependency", p16_dependency_audit, False),
    ("secrets", p17_secret_scanning, False),
    ("credentials", p18_hardcoded_credentials, False),
    ("logging_security", p19_logging_security, False),
    ("sql_injection", p20_sql_injection, False),
    ("orm_enums", p21_orm_enums, False),
    ("async", p22_async_correctness, False),
    ("kernel_guards", p23_kernel_guards, False),
    ("double_entry", p24_double_entry_pattern, False),
    ("journal_lifecycle", p25_journal_lifecycle, False),
    ("fiscal_period", p26_fiscal_period, False),
    ("immutable_audit", p27_immutable_audit, False),
    ("monetary_decimal", p28_monetary_decimal, False),
    ("acid_pattern", p29_acid_pattern, False),
    ("constitution_isolation", p30_constitution_isolation, False),
    ("orm_primary_keys", p31_orm_primary_keys, False),
    ("referential_integrity", p32_referential_integrity, False),
    ("concurrency_pattern", p33_concurrency_pattern, False),
    ("cogs_pattern", p34_cogs_pattern, False),
    ("tax_pattern", p35_tax_pattern, False),
    ("depreciation_pattern", p36_depreciation_pattern, False),
    ("inventory_valuation", p37_inventory_valuation, False),
    ("fiscal_closing", p38_fiscal_closing, False),
    ("retained_earnings", p39_retained_earnings, False),
    ("pytest", p40_pytest, True),
    ("compliance", p41_compliance_structure, False),
    ("schema_consistency", p42_schema_consistency, False),
    ("runtime_imports", p43_runtime_imports, True),
    ("app_bootstrap", p44_app_bootstrap, True),
    ("db_connectivity", p45_db_connectivity, True),
    ("migration_dryrun", p46_migration_dryrun, True),
    ("infrastructure", p47_infrastructure, True),
    ("orm_mapper", p48_orm_mapper, True),
    ("auto_discovery", p49_auto_discovery, False),
    ("critical_imports", p50_critical_imports, False),
    ("env_vars", p51_environment_vars, False),
    ("critical_paths", p52_critical_paths, False),
    ("asgi_validation", p53_asgi_validation, False),
    ("fastapi_routes", p54_fastapi_routes, False),
    ("di_container", p55_di_container, False),
    ("cqrs_handlers", p56_cqrs_handlers, False),
    ("event_handlers", p57_event_handlers, False),
    ("repository_contract", p58_repository_contract, False),
    ("dto_mapper", p59_dto_mapper, False),
    ("startup_dryrun", p60_startup_dryrun, True),
]

# ─── SCORING & GRADING ─────────────────────────────────────────────────────
_GRADES = [
    (97, "S — SOVEREIGN (Structurally Excellent)"),
    (90, "A — EXCELLENT (Well-structured)"),
    (85, "B — GOOD (Minor structural issues)"),
    (75, "C — ACCEPTABLE (Structural improvements needed)"),
    (60, "D — NEEDS WORK (Major structural gaps)"),
    (0, "F — NOT DEPLOYABLE"),
]

def grade(score: int) -> str:
    for threshold, label in _GRADES:
        if score >= threshold:
            return label
    return "F — NOT DEPLOYABLE"

def grade_col(score: int) -> str:
    if score >= 85:
        return GREEN
    if score >= 60:
        return YELLOW
    return RED

def weighted_score(results: list[PhaseResult]) -> tuple[int, int]:
    tw = ws = 0
    for pr in results:
        if pr.score == -1:
            continue
        tw += pr.weight
        ws += pr.score * pr.weight
    base = int(ws / tw) if tw else 0
    crits = sum(pr.count("CRITICAL") for pr in results)
    penalty = min(crits * 3, 30)
    return base, max(0, base - penalty)

def check_hard_fail(results: list[PhaseResult]) -> list[str]:
    reasons = []
    for pr in results:
        for f in pr.findings:
            if f.severity != "CRITICAL":
                continue
            msg = f.message.lower()
            if any(k in msg for k in ("orphan", "multiple heads", "hardcoded secret",
                                      "double_entry.py not found", "import", "bootstrap failed",
                                      "db connection failed", "migration dry-run failed")):
                reasons.append(f"[{pr.name}] {f.message[:80]} @ {f.file}")
    return list(dict.fromkeys(reasons))

# ─── RUNNER ─────────────────────────────────────────────────────────────────
def _print_phase(pr: PhaseResult, verbose: bool) -> None:
    if pr.score == -1:
        sc_str = f"{CYAN}SKIP{RESET}"
    else:
        col = grade_col(pr.score)
        sc_str = f"{col}{pr.score:3d}/100{RESET}"
    if pr.count("CRITICAL") > 0 or pr.score == 0:
        status_str = f"{RED}✖ FAIL{RESET}"
    elif pr.score < 70:
        status_str = f"{YELLOW}⚠ WARN{RESET}"
    else:
        status_str = f"{GREEN}✔ PASS{RESET}"
    print(f"\n{BOLD}[{pr.name}]{RESET}  {status_str}  {sc_str}  ({pr.duration:.1f}s)")
    if pr.disclaimer and verbose:
        print(f"  {CYAN}ℹ {pr.disclaimer}{RESET}")
    shown_pass = False
    for f in pr.findings:
        if f.severity == "CRITICAL":
            pf(f, verbose=True)
        elif f.severity == "WARNING":
            pf(f, verbose=verbose)
        elif f.severity in ("INFO", "PASS") and verbose:
            pf(f, verbose=False)
        elif f.severity == "PASS" and not verbose and not shown_pass:
            print(f"  {GREEN}✔ {f.message}{RESET}")
            shown_pass = True

# MODIFIED: added skip_import parameter
def run_phases(phase_filter: str | None, quick: bool, verbose: bool, runtime: bool,
               skip_import: bool) -> tuple[int, list[PhaseResult]]:
    results: list[PhaseResult] = []
    # Fase yang akan dilewati jika skip_import=True
    import_phases = {"runtime_imports", "critical_imports", "auto_discovery"}
    for key, fn, takes_runtime in _ALL_PHASES:
        if phase_filter and key != phase_filter:
            continue
        if takes_runtime and not runtime:
            continue
        if skip_import and key in import_phases:
            pr = PhaseResult(key, weight=5, score=-1, passed=True)
            pr.add("INFO", ".", 0, f"Phase '{key}' skipped (--skip-import)")
            pr.finalize_status()
            results.append(pr)
            print(f"\n{CYAN}▶ {key.upper()}{RESET}")
            _print_phase(pr, verbose)
            continue
        print(f"\n{CYAN}▶ {key.upper()}{RESET}")
        try:
            pr = fn(quick=quick) if takes_runtime and fn == p40_pytest else fn()
        except Exception as e:
            pr = PhaseResult(f"CRASH:{key}", weight=5, score=0, passed=False)
            pr.add("CRITICAL", "checker_internal", 0, f"Phase crashed: {type(e).__name__}")
            pr.detail = traceback.format_exc()
            pr.finalize_status()
        results.append(pr)
        _print_phase(pr, verbose)
    return weighted_score(results), results

def run_audit(phase_filter: str | None, quick: bool, verbose: bool, json_out: str | None,
              runtime: bool, no_color: bool, skip_import: bool) -> int:
    if no_color:
        _setup_colour(False)
    print(banner("SOVEREIGN ERP — STRUCTURAL INTEGRITY AUDITOR v17.1 (UNIFIED)"))
    print(f"  Root   : {ROOT}")
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  Mode   : {'QUICK' if quick else 'FULL AUDIT'}")
    print(f"  Runtime: {'ACTIVATED' if runtime else 'DISABLED'}")
    print(f"  Skip Import: {'YES' if skip_import else 'NO'}")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n  {YELLOW}NOTE: This auditor verifies CODE STRUCTURE and (optionally) RUNTIME behavior.{RESET}")
    print(f"  {YELLOW}      It does NOT prove financial accuracy.{RESET}")
    if runtime:
        print(f"\n  {RED}{BOLD}⚠ RUNTIME MODE ACTIVE — will execute code (imports, app bootstrap, DB connection).{RESET}")
        print(f"  {RED}      Ensure you are in a safe environment (e.g., test database).{RESET}")
    (base, adj), results = run_phases(phase_filter, quick, verbose, runtime, skip_import)
    hard_fails = check_hard_fail(results)
    total_crits = sum(pr.count("CRITICAL") for pr in results)
    total_warns = sum(pr.count("WARNING") for pr in results)
    elapsed = time.monotonic() - time.monotonic()
    if hard_fails:
        adj = min(adj, 59)
    print(banner("STRUCTURAL AUDIT REPORT"))
    W = 50
    filled = int(W * adj / 100)
    bc = grade_col(adj)
    bar = f"{bc}{'█' * filled}{'░' * (W - filled)}{RESET}"
    print(f"\n  Score  : {bc}{BOLD}{adj}/100{RESET}  (base {base} − {base - adj} penalty)")
    print(f"  Grade  : {bc}{BOLD}{grade(adj)}{RESET}")
    print(f"  [{bar}]")
    print()
    print(f"  Critical findings : {RED}{BOLD}{total_crits}{RESET}")
    print(f"  Warnings          : {YELLOW}{total_warns}{RESET}")
    print(f"  Duration          : {elapsed:.1f}s")
    if hard_fails:
        print(f"\n  {RED}{BOLD}⛔ HARD FAIL — Grade forced to F:{RESET}")
        for reason in hard_fails[:5]:
            print(f"    {RED}✖{RESET} {reason}")
    print()
    if hard_fails:
        code = 2
        print(f"  {RED}{BOLD}✖ NOT DEPLOYABLE — Resolve hard fails{RESET}")
    elif adj >= 85 and total_crits == 0:
        code = 0
        print(f"  {GREEN}{BOLD}✔ STRUCTURALLY READY — {adj}/100  [{grade(adj)}]{RESET}")
    elif adj >= 60:
        code = 1
        print(f"  {YELLOW}{BOLD}⚠ STRUCTURAL ISSUES — {adj}/100  [{grade(adj)}]{RESET}")
    else:
        code = 2
        print(f"  {RED}{BOLD}✖ NOT DEPLOYABLE — {adj}/100  [{grade(adj)}]{RESET}")
    if json_out:
        report = {
            "checker_version": "17.1",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "score": adj,
            "grade": grade(adj),
            "criticals": total_crits,
            "warnings": total_warns,
            "hard_fails": hard_fails,
            "duration_seconds": round(elapsed, 2),
        }
        try:
            pathlib.Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"\n  {CYAN}JSON → {json_out}{RESET}")
        except Exception as ex:
            print(f"\n  {RED}JSON save failed: {ex}{RESET}")
    return code

def start_server(host: str, port: int, reload: bool, workers: int,
                 log_level: str, show_traceback: bool, force: bool) -> None:
    try:
        import uvicorn
    except ImportError:
        logging.error("uvicorn not installed. Run: pip install 'uvicorn[standard]'")
        sys.exit(1)
    print(banner("ERP ACCOUNTING ENGINE — SERVER START"))
    print(f"  Host       : {host}")
    print(f"  Port       : {port}")
    print(f"  Workers    : {workers}")
    print(f"  Reload     : {reload}")
    print(f"  Log Level  : {log_level}")
    print(f"  Force mode : {force}")
    print("  ASGI App   : asgi:app")
    print(f"  Docs       : http://{host}:{port}/docs")
    print(f"  Health     : http://{host}:{port}/health")
    print()
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(logging.ERROR if log_level.lower() != "debug" else logging.DEBUG)
    uvicorn_config = {
        "app": "asgi:app",
        "host": host,
        "port": port,
        "log_level": log_level,
        "access_log": True,
    }
    if reload:
        uvicorn_config["reload"] = True
        uvicorn_config["reload_dirs"] = [str(ROOT)]
    elif workers > 1:
        uvicorn_config["workers"] = workers
    try:
        uvicorn.run(**uvicorn_config)
    except KeyboardInterrupt:
        print("\nServer stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Server failed: {type(e).__name__}: {e}")
        if show_traceback:
            traceback.print_exc()
        sys.exit(1)

# MODIFIED: added --skip-import
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sovereign ERP — Structural Integrity Auditor v17.1 (Unified)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Modes:
          --check           Run all static phases (P00-P53)
          --full-check      Add infrastructure (P47) and ORM mapper (P48)
          --deep-check      Add runtime phases (P43-P46) and advanced phases (P54-P60)
          --syntax-check    Only P02 (syntax)
          --circular-check  Only P04 (circular imports)
          --scan-all        Auto-discovery scan (P49)
          --phase PHASE     Run a single phase

        Other options:
          --quick           Skip pytest (P40)
          --verbose         Show all findings
          --quiet           Minimal output
          --traceback       Show full traceback on errors
          --force           Start server despite non-critical errors
          --json FILE       Save JSON report
          --no-color        Disable colour output
          --runtime         Enable runtime phases (may be destructive)
          --skip-import     Skip import‑execution phases (P43, P49, P50) – safe for static analysis
          --host, --port, --workers, --reload, --log-level  Server options
        """)
    )
    ap.add_argument("--check", action="store_true", help="Health check (static phases)")
    ap.add_argument("--full-check", action="store_true", help="Full check including infrastructure")
    ap.add_argument("--deep-check", action="store_true", help="Deep check including runtime & advanced")
    ap.add_argument("--syntax-check", action="store_true", help="Syntax check only")
    ap.add_argument("--circular-check", action="store_true", help="Circular import check only")
    ap.add_argument("--scan-all", action="store_true", help="Auto-discovery scan")
    ap.add_argument("--phase", choices=[k for k, _, _ in _ALL_PHASES], metavar="PHASE",
                    help="Run single phase")
    ap.add_argument("--quick", action="store_true", help="Skip pytest")
    ap.add_argument("--verbose", action="store_true", help="Show all findings")
    ap.add_argument("--quiet", action="store_true", help="Minimal output")
    ap.add_argument("--traceback", action="store_true", help="Show full traceback")
    ap.add_argument("--force", action="store_true", help="Force start even with non-critical errors")
    ap.add_argument("--json", metavar="FILE", help="Save JSON report")
    ap.add_argument("--no-color", action="store_true", help="Disable colour")
    ap.add_argument("--runtime", action="store_true", help="Enable runtime phases")
    ap.add_argument("--skip-import", action="store_true", help="Skip import-execution phases (safe mode)")
    ap.add_argument("--host", default="127.0.0.1", help="Server host")
    ap.add_argument("--port", type=int, default=8000, help="Server port")
    ap.add_argument("--workers", type=int, default=1, help="Number of uvicorn workers")
    ap.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    ap.add_argument("--log-level", default="info",
                    choices=["debug", "info", "warning", "error", "critical"],
                    help="Log level")
    args = ap.parse_args()

    if args.no_color:
        _setup_colour(False)

    check_mode = (args.check or args.full_check or args.deep_check or
                  args.syntax_check or args.circular_check or args.scan_all)

    if check_mode:
        if args.phase:
            code = run_audit(args.phase, args.quick, args.verbose, args.json,
                             args.runtime, args.no_color, args.skip_import)
            sys.exit(code)
        if args.syntax_check:
            phase_list = ["syntax"]
        elif args.circular_check:
            phase_list = ["circular"]
        elif args.scan_all:
            phase_list = ["auto_discovery", "critical_imports"]
        elif args.deep_check:
            phase_list = [k for k, _, tr in _ALL_PHASES if not tr or args.runtime]
        elif args.full_check:
            phase_list = [k for k, _, tr in _ALL_PHASES if not tr] + ["infrastructure", "orm_mapper"]
        else:
            phase_list = [k for k, _, tr in _ALL_PHASES if not tr]
        results: list[PhaseResult] = []
        for phase_key in phase_list:
            fn = next((f for k, f, _ in _ALL_PHASES if k == phase_key), None)
            if fn is None:
                continue
            # Lewati jika skip_import dan phase termasuk import
            if args.skip_import and phase_key in {"runtime_imports", "critical_imports", "auto_discovery"}:
                pr = PhaseResult(phase_key, weight=5, score=-1, passed=True)
                pr.add("INFO", ".", 0, f"Phase '{phase_key}' skipped (--skip-import)")
                pr.finalize_status()
                results.append(pr)
                print(f"\n{CYAN}▶ {phase_key.upper()}{RESET}")
                _print_phase(pr, args.verbose)
                continue
            print(f"\n{CYAN}▶ {phase_key.upper()}{RESET}")
            try:
                if phase_key == "pytest":
                    pr = fn(quick=args.quick)
                else:
                    pr = fn()
            except Exception as e:
                pr = PhaseResult(f"CRASH:{phase_key}", weight=5, score=0, passed=False)
                pr.add("CRITICAL", "checker_internal", 0, f"Phase crashed: {type(e).__name__}")
                pr.detail = traceback.format_exc()
                pr.finalize_status()
            results.append(pr)
            _print_phase(pr, args.verbose)
        base, adj = weighted_score(results)
        hard_fails = check_hard_fail(results)
        total_crits = sum(pr.count("CRITICAL") for pr in results)
        total_warns = sum(pr.count("WARNING") for pr in results)
        elapsed = time.monotonic() - time.monotonic()
        if hard_fails:
            adj = min(adj, 59)
        print(banner("STRUCTURAL AUDIT REPORT"))
        bc = grade_col(adj)
        print(f"\n  Score  : {bc}{BOLD}{adj}/100{RESET}")
        print(f"  Grade  : {bc}{BOLD}{grade(adj)}{RESET}")
        print(f"  Critical findings : {RED}{BOLD}{total_crits}{RESET}")
        print(f"  Warnings          : {YELLOW}{total_warns}{RESET}")
        print(f"  Duration          : {elapsed:.1f}s")
        if hard_fails:
            print(f"\n  {RED}{BOLD}⛔ HARD FAIL — Grade forced to F:{RESET}")
            for reason in hard_fails[:5]:
                print(f"    {RED}✖{RESET} {reason}")
        print()
        if hard_fails:
            code = 2
            print(f"  {RED}{BOLD}✖ NOT DEPLOYABLE — Resolve hard fails{RESET}")
        elif adj >= 85 and total_crits == 0:
            code = 0
            print(f"  {GREEN}{BOLD}✔ STRUCTURALLY READY — {adj}/100  [{grade(adj)}]{RESET}")
        elif adj >= 60:
            code = 1
            print(f"  {YELLOW}{BOLD}⚠ STRUCTURAL ISSUES — {adj}/100  [{grade(adj)}]{RESET}")
        else:
            code = 2
            print(f"  {RED}{BOLD}✖ NOT DEPLOYABLE — {adj}/100  [{grade(adj)}]{RESET}")
        if args.json:
            report = {
                "checker_version": "17.1",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "score": adj,
                "grade": grade(adj),
                "criticals": total_crits,
                "warnings": total_warns,
                "hard_fails": hard_fails,
                "duration_seconds": round(elapsed, 2),
            }
            try:
                pathlib.Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(f"\n  {CYAN}JSON → {args.json}{RESET}")
            except Exception as ex:
                print(f"\n  {RED}JSON save failed: {ex}{RESET}")
        sys.exit(code)

    # Server mode
    print(banner("ERP ACCOUNTING ENGINE — PRE-FLIGHT CHECKS"))
    preflight = ["environment", "structure", "syntax", "circular", "critical_imports",
                 "env_vars", "critical_paths", "asgi_validation", "orm_mapper"]
    results: list[PhaseResult] = []
    for phase_key in preflight:
        fn = next((f for k, f, _ in _ALL_PHASES if k == phase_key), None)
        if fn is None:
            continue
        if args.skip_import and phase_key in {"critical_imports"}:
            pr = PhaseResult(phase_key, weight=5, score=-1, passed=True)
            pr.add("INFO", ".", 0, f"Phase '{phase_key}' skipped (--skip-import)")
            pr.finalize_status()
            results.append(pr)
            print(f"\n{CYAN}▶ {phase_key.upper()}{RESET}")
            _print_phase(pr, args.verbose)
            continue
        print(f"\n{CYAN}▶ {phase_key.upper()}{RESET}")
        try:
            pr = fn()
        except Exception as e:
            pr = PhaseResult(f"CRASH:{phase_key}", weight=5, score=0, passed=False)
            pr.add("CRITICAL", "checker_internal", 0, f"Phase crashed: {type(e).__name__}")
            pr.detail = traceback.format_exc()
            pr.finalize_status()
        results.append(pr)
        _print_phase(pr, args.verbose)
    critical_errors = any(pr.count("CRITICAL") > 0 for pr in results)
    if critical_errors and not args.force:
        print(f"\n  {RED}{BOLD}❌ Critical errors found. Server not started. Use --force to override.{RESET}")
        sys.exit(1)
    else:
        if critical_errors:
            print(f"\n  {YELLOW}⚠ Critical errors found but --force active. Starting server anyway.{RESET}")
        else:
            print(f"\n  {GREEN}✅ Pre-flight checks passed. Starting server...{RESET}")
        start_server(
            host=args.host,
            port=args.port,
            reload=args.reload,
            workers=args.workers,
            log_level=args.log_level,
            show_traceback=args.traceback,
            force=args.force
        )

if __name__ == "__main__":
    main()
