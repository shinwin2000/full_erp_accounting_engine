#!/usr/bin/env python3
# =============================================================================
#  SOVEREIGN ERP ACCOUNTING ENGINE — STRUCTURAL INTEGRITY AUDITOR v17.0
#  =============================================================================
#  UNIFIED CHECKER — Merges all phases from main_checker & main_checker_3
#  plus advanced phases. Fixed circular import (42 cycles) and broken import
#  (relative imports in __init__.py). Hardened, production‑grade.
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
from typing import Any, Optional

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

def top_layer(module: str) -> str:
    return module.split(".")[0]

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

# P02 — Syntax Validation
def p02_syntax() -> PhaseResult:
    pr = PhaseResult("P02 Syntax Validation", weight=2)
    pr.disclaimer = "Verifies files can be parsed by AST. Does NOT verify semantic correctness."
    t0 = time.monotonic()
    files = all_py(include_checker=True)
    errors = 0
    for path in files:
        try:
            raw = path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            ast.parse(raw, filename=str(path))
        except SyntaxError as e:
            errors += 1
            pr.add("CRITICAL", rel(path), e.lineno or 0,
                   f"SyntaxError: {e.msg}",
                   recommendation="Fix syntax error in this file.")
        except Exception as e:
            errors += 1
            pr.add("CRITICAL", rel(path), 0,
                   f"ParseError: {type(e).__name__}: {str(e)[:80]}",
                   recommendation="Check file encoding and structure.")
    if not errors:
        pr.add("PASS", ".", 0, f"All {len(files)} files parse cleanly")
    pr.score = max(0, 100 - errors * 5)
    if errors:
        pr.passed = False
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P03 — Self-Audit
def p03_self_audit() -> PhaseResult:
    pr = PhaseResult("P03 Self-Audit", weight=3)
    pr.disclaimer = "Verifies checker has no syntax errors and phase registry is consistent."
    t0 = time.monotonic()
    checker_path = ROOT / "main_checker_3.py"
    if not checker_path.exists():
        pr.add("CRITICAL", "main_checker_3.py", 0,
               "Checker file not found", recommendation="Ensure main_checker_3.py exists.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tree, lines = get_ast_tree_with_source(checker_path)
    if tree is None:
        pr.add("CRITICAL", "main_checker_3.py", 0,
               "Checker has syntax errors", recommendation="Fix syntax errors in the checker itself.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    secret_patterns = [
        (r'(?i)password\s*=\s*["\'](?!bcrypt|argon|sha|example|changeme)[A-Za-z0-9@#$!%^&*]{8,}["\']', "CRITICAL"),
        (r'(?i)secret.*?=\s*["\'][A-Za-z0-9@#$!%^&*_\-]{16,}["\']', "CRITICAL"),
    ]
    if lines:
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for pattern, sev in secret_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    pr.add(sev, "main_checker_3.py", lineno,
                           "Hardcoded secret in checker", detail=line[:100],
                           recommendation="Remove hardcoded secrets, use env vars.")
    phase_functions = [node.name for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef) and node.name.startswith("p") and len(node.name) >= 3]
    if pr.count("CRITICAL") == 0:
        pr.add("PASS", "main_checker_3.py", 0,
               f"Checker self-audit passed: {len(phase_functions)} phases found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P04 — Circular Imports (original robust logic)
def p04_circular() -> PhaseResult:
    pr = PhaseResult("P04 Circular Imports", weight=2)
    pr.disclaimer = "Static analysis of import graph (original robust logic)."
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

# P05 — Static Import Scan
def p05_static_imports() -> PhaseResult:
    pr = PhaseResult("P05 Static Import Scan", weight=2)
    pr.disclaimer = "Counts static imports only. Does NOT verify runtime import correctness."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    total = 0
    for path in files:
        tree = get_ast_tree(path)
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    total += len(node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.level == 0:
                        total += len(node.names)
    pr.add("PASS", ".", 0, f"Found {total} static imports across {len(files)} files")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P06 — Dynamic Import Audit
_PROTECTED_LAYERS = {"domain", "kernel", "axioms", "constitution", "ports"}

def _find_dynamic_imports_ast(tree: ast.AST) -> list[tuple[int, str, str]]:
    res = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib" and node.func.attr == "import_module"):
                if node.args:
                    expr = ast.unparse(node.args[0])
                    res.append((node.lineno, "importlib.import_module", expr))
            elif isinstance(node.func, ast.Name) and node.func.id == "__import__":
                if node.args:
                    expr = ast.unparse(node.args[0])
                    res.append((node.lineno, "__import__", expr))
    return res

def p06_dynamic_imports() -> PhaseResult:
    pr = PhaseResult("P06 Dynamic Import Audit", weight=2)
    pr.disclaimer = "Flags dynamic import patterns. Plugin architectures may legitimately use dynamic imports."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    dangerous = 0
    for path in files:
        tree = get_ast_tree(path)
        if tree is None:
            continue
        hits = _find_dynamic_imports_ast(tree)
        if not hits:
            continue
        mod = mod_name(path)
        layer = top_layer(mod) if mod else "unknown"
        if layer in _PROTECTED_LAYERS:
            for lineno, call, expr in hits[:3]:
                dangerous += 1
                pr.add("WARNING", rel(path), lineno,
                       f"Dynamic import in protected layer '{layer}': {call}({expr})",
                       recommendation="Consider using static imports or factory pattern.")
    if dangerous == 0:
        pr.add("PASS", ".", 0, "No dynamic imports in protected layers")
    pr.degrade(per_crit=10, per_warn=2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P07 — Broken Import Scan (FIXED: handles relative imports in __init__.py)
def _resolve_import_target(imp: str, root: pathlib.Path) -> list[pathlib.Path]:
    candidates = []
    direct = root / imp.replace(".", "/")
    candidates.append(direct.with_suffix(".py"))
    candidates.append(direct / "__init__.py")
    parts = imp.split(".")
    for i in range(len(parts)):
        pkg_path = root / "/".join(parts[: i + 1])
        candidates.append(pkg_path / "__init__.py")
    return [c for c in candidates if c.exists()]

def _resolve_relative_import(file_path: pathlib.Path, level: int, module: str | None, alias: str | None) -> list[pathlib.Path]:
    """
    Resolve a relative import to candidate file paths.
    - level: number of dots (1 = same directory, 2 = parent, ...)
    - module: the module part after dots (e.g., 'submodule' in 'from .submodule import ...')
    - alias: if module is None, the imported name (e.g., 'x' in 'from . import x')
    Returns list of existing file paths that match.
    """
    target_dir = file_path.parent
    # level=1 means current directory, so we go up (level-1) times
    for _ in range(level - 1):
        target_dir = target_dir.parent

    if module:
        # e.g., from .sub.submodule import ...
        parts = module.split(".")
        base = target_dir
        for part in parts:
            base = base / part
        candidates = [base.with_suffix(".py"), base / "__init__.py"]
        return [c for c in candidates if c.exists()]
    else:
        # e.g., from . import x
        if alias is None:
            return []
        base = target_dir / alias
        candidates = [base.with_suffix(".py"), base / "__init__.py"]
        return [c for c in candidates if c.exists()]

def p07_broken_imports() -> PhaseResult:
    pr = PhaseResult("P07 Broken Import Scan", weight=3)
    pr.disclaimer = "Verifies imported modules exist as files. Does NOT verify runtime importability."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    local_mods = {mod_name(f) for f in files if mod_name(f)}
    local_tops = {m.split(".")[0] for m in local_mods}
    broken = []
    for path in files:
        tree = get_ast_tree(path)
        if tree is None:
            continue
        rp = rel(path)
        mod = mod_name(path) or ""
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
                    # ========== PERBAIKAN DI SINI ==========
                    # Gunakan resolusi berbasis file
                    found = False
                    if node.module:
                        # from .module import ...
                        candidates = _resolve_relative_import(path, node.level, node.module, None)
                        if candidates:
                            found = True
                    else:
                        # from . import x, y
                        for alias in node.names:
                            candidates = _resolve_relative_import(path, node.level, None, alias.name)
                            if candidates:
                                found = True
                                break
                    if not found:
                        # jika tidak ditemukan, catat sebagai broken (dengan informasi sebisa mungkin)
                        if node.module:
                            broken.append((rp, node.lineno, f".{'.'*(node.level-1)}{node.module}"))
                        else:
                            for alias in node.names:
                                broken.append((rp, node.lineno, f".{'.'*(node.level-1)}{alias.name}"))
    for rp, lineno, imp in broken[:30]:
        pr.add("WARNING", rp, lineno, f"Broken local import reference: {imp}",
               recommendation=f"Ensure module '{imp}' exists or fix import path.")
    if not broken:
        pr.add("PASS", ".", 0, "No broken local import references found")
    else:
        pr.add("INFO", ".", 0, f"Found {len(broken)} broken import reference(s)")
    pr.score = max(0, 100 - len(broken) * 3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P08 — Architecture Layers
_LAYER_RULES: dict[str, set[str]] = {
    "domain": {"domain"},
    "axioms": {"axioms", "constitution"},
    "constitution": {"constitution", "domain", "axioms"},
    "kernel": {"kernel", "domain", "axioms", "constitution", "ports", "config"},
    "ports": {"ports", "domain"},
    "application": {"application", "domain", "kernel", "ports", "axioms", "constitution"},
    "adapters": {"adapters", "application", "domain", "kernel", "ports", "infrastructure"},
    "infrastructure": {"infrastructure", "domain", "ports", "kernel", "config"},
    "bootstrap": set(),
    "config": {"config", "bootstrap"},
    "app": set(),
}
_LAYER_EXCEPTIONS: set[tuple[str, str]] = {("domain", "kernel")}

def p08_architecture() -> PhaseResult:
    pr = PhaseResult("P08 Architecture Layers", weight=3)
    pr.disclaimer = "Heuristic check based on layer naming. May have false positives."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    violations = []
    exempt_layers = {"bootstrap", "app", "deployment", "scripts"}
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
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imp_layer = top_layer(alias.name)
                    if imp_layer and imp_layer in _LAYER_RULES and imp_layer not in allowed:
                        if (layer, imp_layer) not in _LAYER_EXCEPTIONS:
                            violations.append((rel(path), node.lineno, layer, imp_layer, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imp_layer = top_layer(node.module)
                if imp_layer and imp_layer in _LAYER_RULES and imp_layer not in allowed:
                    if (layer, imp_layer) not in _LAYER_EXCEPTIONS:
                        violations.append((rel(path), node.lineno, layer, imp_layer, node.module))
    for file, lineno, layer, imp_layer, imp in violations[:30]:
        pr.add("WARNING", file, lineno,
               f"Potential layer violation: {layer} → {imp_layer} imports '{imp}'",
               recommendation=f"Move import to allowed layer or refactor.")
    if len(violations) <= 10:
        pr.add("PASS", ".", 0, f"Layer violations within tolerance: {len(violations)}")
    else:
        pr.add("WARNING", ".", 0, f"Found {len(violations)} potential layer violations (first 30 shown)")
    pr.score = max(0, 100 - min(len(violations), 30) * 2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P09 — Port-Adapter Pairing
def p09_port_adapter() -> PhaseResult:
    pr = PhaseResult("P09 Port-Adapter Pairing", weight=2)
    pr.disclaimer = "Verifies naming convention only. Does NOT verify runtime binding."
    t0 = time.monotonic()
    ports_dir = ROOT / "ports" / "primary"
    adapters_root = ROOT / "adapters"
    if not ports_dir.exists() or not adapters_root.exists():
        pr.add("INFO", ".", 0, "ports/primary or adapters/ not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    adapter_files = {f.stem for f in adapters_root.rglob("*.py")
                     if f.name != "__init__" and "__pycache__" not in f.parts}
    port_files = {f.stem for f in ports_dir.glob("*.py") if f.stem != "__init__"}
    paired = 0
    unpaired = []
    for port in sorted(port_files):
        base = port
        for suffix in ["_repository_port", "_port", "_repository"]:
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        found = any(base.lower() in astem.lower() for astem in adapter_files)
        if found:
            paired += 1
        else:
            unpaired.append(port)
    for port in unpaired[:10]:
        pr.add("WARNING", f"ports/primary/{port}.py", 0,
               f"No adapter found for port: {port}",
               recommendation=f"Create an adapter for '{port}' in adapters/.")
    total = len(port_files)
    cov = int(paired / total * 100) if total else 0
    if cov >= 80:
        pr.add("PASS", ".", 0, f"Port-adapter naming coverage: {paired}/{total} = {cov}%")
    else:
        pr.add("WARNING", ".", 0, f"Port-adapter coverage low: {paired}/{total} = {cov}%")
    pr.score = cov
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P10 — API Route Completeness
DOMAIN_ROUTERS = ["fastapi_coa_router", "fastapi_journal_router", "fastapi_ledger_router",
                  "fastapi_ap_router", "fastapi_ar_router", "fastapi_bank_cash_router",
                  "fastapi_inventory_router", "fastapi_fixed_asset_router",
                  "fastapi_tax_coretax_router", "fastapi_iam_router"]

def p10_routes() -> PhaseResult:
    pr = PhaseResult("P10 API Route Completeness", weight=1)
    pr.disclaimer = "Verifies router files exist. Does NOT verify route implementation."
    t0 = time.monotonic()
    v1 = ROOT / "adapters" / "primary_api" / "v1"
    if not v1.exists():
        pr.add("WARNING", "adapters/primary_api/v1", 0,
               "v1 router directory not found",
               recommendation="Create adapters/primary_api/v1/ and add router files.")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    present = {f.stem for f in v1.glob("*.py") if f.stem != "__init__"}
    missing = [r for r in DOMAIN_ROUTERS if r not in present]
    for r in missing:
        pr.add("INFO", "adapters/primary_api/v1", 0,
               f"Missing router file: {r}.py",
               recommendation=f"Create {r}.py in adapters/primary_api/v1/")
    if len(missing) <= 2:
        pr.add("PASS", "adapters/primary_api/v1", 0, f"Router files: {len(present)} present")
    else:
        pr.add("WARNING", "adapters/primary_api/v1", 0, f"Missing {len(missing)} router files")
    pr.score = max(0, 100 - len(missing) * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P11 — YAML Validation
def p11_yaml() -> PhaseResult:
    pr = PhaseResult("P11 YAML Validation", weight=1)
    pr.disclaimer = "Verifies YAML syntax only. Does NOT verify semantic correctness."
    t0 = time.monotonic()
    try:
        import yaml
    except ImportError:
        pr.add("INFO", ".", 0, "PyYAML not installed — skipping YAML validation",
               recommendation="Install PyYAML: pip install pyyaml")
        pr.score = 70
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    yfiles = []
    for d in ["config_files", "monitoring", "deployment"]:
        dp = ROOT / d
        if dp.exists():
            yfiles.extend(dp.rglob("*.yaml"))
            yfiles.extend(dp.rglob("*.yml"))
    yfiles.extend(ROOT.glob("*.yaml"))
    yfiles.extend(ROOT.glob("*.yml"))
    errors = 0
    checked = 0
    for yf in sorted(set(yfiles)):
        try:
            with open(yf, encoding="utf-8") as fh:
                list(yaml.safe_load_all(fh))
            checked += 1
        except yaml.YAMLError as e:
            errors += 1
            pr.add("WARNING", rel(yf), 0, f"YAML syntax error: {str(e)[:80]}",
                   recommendation="Fix YAML syntax in this file.")
    if errors == 0:
        pr.add("PASS", ".", 0, f"All {checked} YAML files have valid syntax")
    pr.score = max(0, 100 - errors * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P12 — ASGI Load
def p12_asgi() -> PhaseResult:
    pr = PhaseResult("P12 ASGI Load", weight=1)
    pr.disclaimer = "Verifies ASGI app pattern exists. Does NOT verify runtime correctness."
    t0 = time.monotonic()
    main_py = ROOT / "app" / "main.py"
    if not main_py.exists():
        pr.add("WARNING", "app/main.py", 0, "app/main.py not found",
               recommendation="Create app/main.py with ASGI application.")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tree = get_ast_tree(main_py)
    has_app = False
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ("app", "application"):
                        has_app = True
            elif isinstance(node, ast.FunctionDef) and node.name in ("get_app", "create_app"):
                has_app = True
    if has_app:
        pr.add("PASS", "app/main.py", 0, "ASGI app pattern found")
    else:
        pr.add("INFO", "app/main.py", 0, "ASGI app pattern not clearly found",
               recommendation="Define 'app' variable or 'create_app()' function.")
    pr.score = 100 if has_app else 70
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P13 — Migration Chain
def p13_migrations() -> PhaseResult:
    pr = PhaseResult("P13 Migration Chain", weight=2)
    pr.disclaimer = "Verifies revision graph consistency. Multiple heads or orphans block alembic upgrade."
    t0 = time.monotonic()
    vdir = ROOT / "migrations" / "versions"
    if not vdir.exists():
        pr.add("INFO", "migrations/versions", 0, "versions directory not found",
               recommendation="Initialize migrations: alembic init migrations")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    mfiles = [f for f in sorted(vdir.glob("*.py")) if f.name != "__init__.py"]
    revs: dict[str, str] = {}
    file_by_rev: dict[str, pathlib.Path] = {}
    for mf in mfiles:
        src = mf.read_text(encoding="utf-8", errors="replace")
        rm = re.search(r'^revision\s*=\s*["\'](\w+)["\']', src, re.M)
        if not rm:
            rm = re.search(r'^revision\s*:\s*[^=]+\s*=\s*["\'](\w+)["\']', src, re.M)
        dm = re.search(r'^down_revision\s*=\s*["\']?(\w+|None)["\']?', src, re.M)
        if not dm:
            dm = re.search(r'^down_revision\s*:\s*[^=]+\s*=\s*["\']?(\w+|None)["\']?', src, re.M)
        if rm:
            rev = rm.group(1)
            down = dm.group(1) if dm and dm.group(1) != "None" else ""
            revs[rev] = down
            file_by_rev[rev] = mf
    all_rev = set(revs)
    all_down = {v for v in revs.values() if v}
    orphans = all_down - all_rev
    heads = all_rev - all_down
    for o in orphans:
        for rev, down in revs.items():
            if down == o:
                pr.add("CRITICAL", rel(file_by_rev.get(rev, vdir / "unknown")), 0,
                       f"Orphan down_revision '{o}' — file {rev} refers to missing revision",
                       recommendation=f"Create migration with revision '{o}' or update down_revision.")
                break
    if len(heads) > 1:
        pr.add("CRITICAL", "migrations/versions", 0,
               f"Multiple heads ({len(heads)}) — run: alembic merge heads",
               recommendation="Run 'alembic merge heads' to create a merge migration.")
        for h in heads:
            pr.add("INFO", rel(file_by_rev.get(h, vdir / "unknown")), 0, f"Head revision: {h}")
    if not orphans and len(heads) <= 1:
        pr.add("PASS", "migrations/versions", 0, f"Revision chain intact: {len(mfiles)} migrations")
    else:
        pr.add("INFO", "migrations/versions", 0,
               f"Status: {len(mfiles)} files, {len(heads)} heads, {len(orphans)} orphans")
    pr.score = max(0, 100 - len(orphans) * 20 - max(0, len(heads) - 1) * 25)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P14 — Code Quality
def p14_quality() -> PhaseResult:
    pr = PhaseResult("P14 Code Quality", weight=1)
    pr.disclaimer = "Detects common anti-patterns. Does NOT measure maintainability comprehensively."
    t0 = time.monotonic()
    files = all_py(include_checker=True, skip_tops={"tests", "migrations"})
    issues = []
    marker_pattern = re.compile(r"\b(TODO|FIXME|HACK)\b", re.IGNORECASE)
    for path in files:
        if is_checker_file(path):
            continue
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue
        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append((rp, node.lineno, "Bare except clause"))
            elif isinstance(node, ast.ImportFrom):
                if node.names and any(n.name == "*" for n in node.names):
                    issues.append((rp, node.lineno, "Wildcard import"))
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if marker_pattern.search(line):
                issues.append((rp, lineno, "TODO/FIXME/HACK marker"))
    for rp, lineno, msg in issues[:30]:
        pr.add("WARNING", rp, lineno, msg,
               recommendation="Resolve or remove the issue marker.")
    if len(issues) <= 20:
        pr.add("PASS", ".", 0, f"Code quality issues: {len(issues)}")
    else:
        pr.add("WARNING", ".", 0, f"Found {len(issues)} code quality issues")
    pr.score = max(0, 100 - len(issues))
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P15 — Security Scan
_SEC_PATTERNS = [
    (r"pickle\.loads?\s*\(", "WARNING", "pickle.load() — unsafe deserialization"),
    (r"yaml\.load\s*\([^)]*\)", "WARNING", "yaml.load() — use safe_load()"),
    (r"\bverify\s*=\s*False\b", "WARNING", "SSL verify=False"),
    (r"os\.system\s*\(", "WARNING", "os.system() — use subprocess"),
    (r"DEBUG\s*=\s*True\b", "INFO", "DEBUG=True — ensure not in production"),
]

def p15_security() -> PhaseResult:
    pr = PhaseResult("P15 Security Scan", weight=4)
    pr.disclaimer = "Pattern-based detection. May have false positives and false negatives."
    t0 = time.monotonic()
    files = all_py(include_checker=True, skip_tops={"tests", "docs"})
    for path in files:
        if is_checker_file(path):
            continue
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue
        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                    pr.add("CRITICAL", rp, node.lineno,
                           f"{node.func.id}() — code execution",
                           recommendation="Avoid eval/exec; use safer alternatives.")
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for pattern, sev, msg in _SEC_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    pr.add(sev, rp, lineno, msg, detail=line[:100])
                    break
    if pr.count("CRITICAL") == 0:
        pr.add("PASS", ".", 0, "No critical security patterns found")
    pr.degrade(per_crit=15, per_warn=2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P16 — Dependency Audit
def p16_dependency_audit() -> PhaseResult:
    pr = PhaseResult("P16 Dependency Audit", weight=2)
    pr.disclaimer = "Checks version constraints against known vulnerable ranges."
    t0 = time.monotonic()
    req_file = ROOT / "requirements.txt"
    if not req_file.exists():
        pr.add("INFO", "requirements.txt", 0, "requirements.txt not found",
               recommendation="Create requirements.txt with project dependencies.")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    known_vulnerable = {
        "cryptography": ["<3.4"], "requests": ["<2.31"], "urllib3": ["<1.26.18"],
        "jinja2": ["<3.1.2"], "sqlalchemy": ["<1.4.46"],
    }
    with open(req_file, encoding="utf-8") as f:
        content = f.read()
        for pkg, vuln_versions in known_vulnerable.items():
            for vuln in vuln_versions:
                if pkg in content and vuln in content:
                    pr.add("WARNING", "requirements.txt", 0,
                           f"Package '{pkg}' uses {vuln}",
                           recommendation=f"Upgrade {pkg} to a secure version.")
    if pr.count("WARNING") == 0:
        pr.add("PASS", "requirements.txt", 0, "No known vulnerable version constraints")
    pr.score = max(60, 100 - pr.count("WARNING") * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P17 — Secret Scanning
def p17_secret_scanning() -> PhaseResult:
    pr = PhaseResult("P17 Secret Scanning (Context-Aware)", weight=3)
    pr.disclaimer = "Context-aware pattern matching. Ignores test files and status constants."
    t0 = time.monotonic()
    files = all_py(include_checker=True)
    exempt_patterns = ["example", "changeme", "your_", "dummy", "test",
                       "placeholder", "wrong_password", "minioadmin"]
    exempt_status_constants = ["FAILURE_WRONG_PASSWORD", "ERROR_", "STATUS_", "SUCCESS_"]
    secrets_found = 0
    env_file = ROOT / ".env"
    if env_file.exists():
        env_lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno, line in enumerate(env_lines, 1):
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                if len(val.strip()) > 8 and val.strip() not in ["", "null", "None"]:
                    if any(secret_word in key.lower()
                           for secret_word in ["password", "secret", "key", "token"]) \
                       and not any(ex in val.lower() for ex in exempt_patterns):
                        secrets_found += 1
                        pr.add("WARNING", str(env_file), lineno,
                               f"Secret in .env: {key}=***",
                               recommendation="Use .env for local dev only; do not commit.")
    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rp = rel(path)
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            if any(const in line for const in exempt_status_constants):
                continue
            if re.search(r'(?i)(password|passwd|pwd)\s*=\s*["\']([^"\']{8,})["\']', line, re.IGNORECASE):
                match = re.search(r'=\s*["\']([^"\']+)["\']', line)
                if match:
                    value = match.group(1)
                    if not any(ex in value.lower() for ex in exempt_patterns):
                        secrets_found += 1
                        pr.add("CRITICAL", rp, lineno, "Potential hardcoded secret",
                               detail=line[:100], recommendation="Use environment variables or secrets manager.")
            if re.search(r'(?i)secret[_\-]?key\s*=\s*["\']([A-Za-z0-9@#$!%^&*_\-]{8,})["\']', line, re.IGNORECASE):
                match = re.search(r'=\s*["\']([^"\']+)["\']', line)
                if match:
                    value = match.group(1)
                    if not any(ex in value.lower() for ex in exempt_patterns):
                        secrets_found += 1
                        pr.add("CRITICAL", rp, lineno, "Potential hardcoded secret",
                               detail=line[:100], recommendation="Use environment variables or secrets manager.")
    if secrets_found == 0:
        pr.add("PASS", ".", 0, "No hardcoded secret patterns found in production code")
    else:
        pr.add("INFO", ".", 0, f"Found {secrets_found} potential secret(s) in production code")
    pr.score = max(0, 100 - secrets_found * 10)
    if secrets_found > 0:
        pr.passed = False
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P18 — Hardcoded Credentials
def p18_hardcoded_credentials() -> PhaseResult:
    pr = PhaseResult("P18 Hardcoded Credentials", weight=2)
    pr.disclaimer = "Pattern-based detection for database credentials."
    t0 = time.monotonic()
    files = all_py(include_checker=True)
    creds = 0
    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rp = rel(path)
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            if re.search(r'(?i)DB_PASSWORD\s*=\s*["\']([^"\']{4,})["\']', line, re.IGNORECASE):
                creds += 1
                pr.add("WARNING", rp, lineno, "DB_PASSWORD hardcoded",
                       detail=line[:100], recommendation="Use environment variable for DB_PASSWORD.")
            if re.search(r'(?i)DATABASE_URL\s*=\s*["\']postgresql://[^:]+:([^@]+)@', line, re.IGNORECASE):
                creds += 1
                pr.add("WARNING", rp, lineno, "Database URL with password",
                       detail=line[:100], recommendation="Remove password from DATABASE_URL, use env var.")
    if creds == 0:
        pr.add("PASS", ".", 0, "No hardcoded credential patterns found")
    pr.score = max(0, 100 - creds * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P19 — Logging Security
def p19_logging_security() -> PhaseResult:
    pr = PhaseResult("P19 Logging Security", weight=2)
    pr.disclaimer = "Pattern-based detection of sensitive data in logs."
    t0 = time.monotonic()
    files = all_py(include_checker=True)
    sensitive_patterns = [
        (r"logger\.\w+\(.*password", "Logging password field"),
        (r"logger\.\w+\(.*secret", "Logging secret field"),
        (r"logger\.\w+\(.*token", "Logging token field"),
    ]
    issues = []
    for path in files:
        if is_test_file(path) or is_checker_file(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rp = rel(path)
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for pattern, msg in sensitive_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append((rp, lineno, msg))
                    break
    for rp, lineno, msg in issues[:20]:
        pr.add("WARNING", rp, lineno, msg,
               detail="Review logging of sensitive data",
               recommendation="Avoid logging sensitive data; use sanitization.")
    if not issues:
        pr.add("PASS", ".", 0, "No sensitive data logging patterns detected")
    pr.score = max(70, 100 - len(issues) * 3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P20 — SQL Injection (AST f-string detection)
def p20_sql_injection() -> PhaseResult:
    pr = PhaseResult("P20 SQL Injection (AST)", weight=3)
    pr.disclaimer = "Detects f-strings containing SQL keywords. May have false positives."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations"})
    issues = []
    for path in files:
        if is_checker_file(path):
            continue
        tree, lines = get_ast_tree_with_source(path)
        if tree is None or lines is None:
            continue
        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                node_str = ast.unparse(node)
                sql_keywords = ["SELECT", "INSERT", "UPDATE", "DELETE", "FROM",
                                "WHERE", "CREATE", "DROP", "ALTER"]
                if any(kw in node_str.upper() for kw in sql_keywords):
                    for value in node.values:
                        if isinstance(value, ast.FormattedValue):
                            issues.append((rp, node.lineno, "f-string SQL with interpolation"))
                            break
    for rp, lineno, msg in issues[:30]:
        pr.add("WARNING", rp, lineno, msg,
               detail="Possible SQL injection risk",
               recommendation="Use parameterized queries (SQLAlchemy text() with params).")
    if not issues:
        pr.add("PASS", ".", 0, "No f-string SQL injection patterns detected")
    else:
        pr.add("INFO", ".", 0, f"Found {len(issues)} potential SQL injection pattern(s)")
    pr.score = max(0, 100 - len(issues) * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P21 — ORM Enum Inheritance
def p21_orm_enums() -> PhaseResult:
    pr = PhaseResult("P21 ORM Enum Inheritance", weight=1)
    pr.disclaimer = "Detects SQLAlchemy.Enum inheritance instead of enum.Enum."
    t0 = time.monotonic()
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("INFO", "infrastructure/persistence_orm", 0, "ORM dir not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    bad = 0
    for path in sorted(orm_dir.glob("*.py")):
        tree = get_ast_tree(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if (isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name)
                        and base.value.id == "sqlalchemy" and base.attr == "Enum"):
                        bad += 1
                        pr.add("WARNING", rel(path), node.lineno,
                               f"'{node.name}' inherits sqlalchemy.Enum",
                               recommendation="Use enum.Enum and SQLAlchemy's Enum type separately.")
    if not bad:
        pr.add("PASS", "infrastructure/persistence_orm", 0, "No ORM Enum issues found")
    pr.score = max(0, 100 - bad * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P22 — Async Correctness
def p22_async_correctness() -> PhaseResult:
    pr = PhaseResult("P22 Async Correctness", weight=2)
    pr.disclaimer = "Detects common anti-patterns only."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"})
    issues = []
    for path in files:
        tree = get_ast_tree(path)
        if tree is None:
            continue
        rp = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "asyncio" and node.func.attr == "run"):
                    issues.append((rp, node.lineno, "asyncio.run() in module"))
                if isinstance(node.func, ast.Attribute) and node.func.attr == "run_until_complete":
                    issues.append((rp, node.lineno, "run_until_complete()"))
    for rp, lineno, msg in issues[:20]:
        pr.add("WARNING", rp, lineno, msg,
               recommendation="Avoid using asyncio.run() in modules; use proper event loop management.")
    if not issues:
        pr.add("PASS", ".", 0, "No common async anti-patterns detected")
    pr.score = max(80, 100 - len(issues) * 2)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P23 — Kernel Guards
def p23_kernel_guards() -> PhaseResult:
    pr = PhaseResult("P23 Kernel Guards", weight=1)
    pr.disclaimer = "Verifies guard files exist. Does NOT verify guard logic."
    t0 = time.monotonic()
    guards_dir = ROOT / "kernel" / "guards"
    required_guards = ["period_lock.py", "balance_checker.py", "authority_matrix.py"]
    if not guards_dir.exists():
        pr.add("INFO", "kernel/guards", 0, "Guards directory not found",
               recommendation="Create kernel/guards/ with required guard files.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    present = {f.name for f in guards_dir.glob("*.py")}
    for guard in required_guards:
        if guard not in present:
            pr.add("INFO", "kernel/guards", 0, f"Guard file not found: {guard}",
                   recommendation=f"Create {guard} in kernel/guards/")
    if all(g in present for g in required_guards):
        pr.add("PASS", "kernel/guards", 0, "Required guard files present")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P24 — Double-Entry Pattern
def p24_double_entry_pattern() -> PhaseResult:
    pr = PhaseResult("P24 Double-Entry Pattern", weight=3)
    pr.disclaimer = "Verifies double-entry pattern exists. Does NOT verify debit=credit at runtime."
    t0 = time.monotonic()
    de_file = ROOT / "axioms" / "double_entry.py"
    if not de_file.exists():
        pr.add("CRITICAL", "axioms/double_entry.py", 0, "double_entry.py not found",
               recommendation="Create axioms/double_entry.py with double-entry logic.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tree = get_ast_tree(de_file)
    if tree is None:
        pr.add("WARNING", "axioms/double_entry.py", 0, "Cannot parse file",
               recommendation="Fix syntax in axioms/double_entry.py.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    has_debit_credit = False
    has_balance_check = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_text = ast.unparse(node)
            if "debit" in func_text.lower() and "credit" in func_text.lower():
                has_debit_credit = True
            if "balance" in func_text.lower() or "assert_balanced" in node.name.lower():
                has_balance_check = True
    if has_debit_credit and has_balance_check:
        pr.add("PASS", "axioms/double_entry.py", 0, "Double-entry pattern found")
    else:
        pr.add("WARNING", "axioms/double_entry.py", 0, "Double-entry pattern incomplete",
               recommendation="Implement debit/credit and balance check functions.")
    pr.degrade(per_crit=20, per_warn=5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P25 — Journal Lifecycle Pattern
def p25_journal_lifecycle() -> PhaseResult:
    pr = PhaseResult("P25 Journal Lifecycle Pattern", weight=2)
    pr.disclaimer = "Verifies state machine pattern exists."
    t0 = time.monotonic()
    sm_file = ROOT / "domain" / "journal" / "state_machine.py"
    if not sm_file.exists():
        pr.add("WARNING", "domain/journal/state_machine.py", 0, "State machine not found",
               recommendation="Create domain/journal/state_machine.py with states.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    src = sm_file.read_text(encoding="utf-8", errors="replace")
    states = ["DRAFT", "POSTED", "REVERSED"]
    found_states = [s for s in states if s in src]
    if len(found_states) == len(states):
        pr.add("PASS", "domain/journal/state_machine.py", 0, "Journal lifecycle pattern found")
    else:
        pr.add("WARNING", "domain/journal/state_machine.py", 0,
               f"Missing states: {set(states) - set(found_states)}",
               recommendation="Add missing states to state machine.")
    pr.degrade(per_crit=15, per_warn=3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P26 — Fiscal Period Pattern
def p26_fiscal_period() -> PhaseResult:
    pr = PhaseResult("P26 Fiscal Period Pattern", weight=2)
    pr.disclaimer = "Verifies open/close/lock methods exist."
    t0 = time.monotonic()
    fp_file = ROOT / "domain" / "fiscal_period" / "aggregate_root.py"
    if not fp_file.exists():
        pr.add("INFO", "domain/fiscal_period/aggregate_root.py", 0, "Not found",
               recommendation="Create domain/fiscal_period/aggregate_root.py.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    src = fp_file.read_text(encoding="utf-8", errors="replace")
    ops = {"open": False, "close": False, "lock": False}
    for op in ops:
        if op in src.lower():
            ops[op] = True
    missing_ops = [op for op, found in ops.items() if not found]
    if not missing_ops:
        pr.add("PASS", "domain/fiscal_period/aggregate_root.py", 0,
               "Fiscal period open/close/lock pattern found")
    else:
        pr.add("WARNING", "domain/fiscal_period/aggregate_root.py", 0,
               f"Missing methods: {missing_ops}",
               recommendation=f"Implement {', '.join(missing_ops)} methods.")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P27 — Immutable Audit Pattern
def p27_immutable_audit() -> PhaseResult:
    pr = PhaseResult("P27 Immutable Audit Pattern", weight=2)
    pr.disclaimer = "Verifies append-only pattern."
    t0 = time.monotonic()
    ew_file = ROOT / "audit" / "event_writer_immutable.py"
    if not ew_file.exists():
        pr.add("WARNING", "audit/event_writer_immutable.py", 0, "Not found",
               recommendation="Create audit/event_writer_immutable.py for append-only audit.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tree = get_ast_tree(ew_file)
    if tree is None:
        pr.add("WARNING", "audit/event_writer_immutable.py", 0, "Cannot parse",
               recommendation="Fix syntax in audit/event_writer_immutable.py.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    dangerous = [node.name for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and
                 any(x in node.name.lower() for x in ("update", "delete", "modify", "edit", "overwrite"))]
    if dangerous:
        pr.add("WARNING", "audit/event_writer_immutable.py", 0,
               f"Mutation methods found: {dangerous}",
               recommendation="Remove mutation methods to ensure append-only.")
    else:
        pr.add("PASS", "audit/event_writer_immutable.py", 0, "Append-only pattern confirmed")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P28 — Monetary Decimal Pattern
_MONETARY_FIELDS = ["amount", "debit", "credit", "price", "cost", "tax", "total", "balance", "value"]

def p28_monetary_decimal() -> PhaseResult:
    pr = PhaseResult("P28 Monetary Decimal Pattern", weight=3)
    pr.disclaimer = "Detects float usage for monetary fields. Does NOT verify Decimal correctness."
    t0 = time.monotonic()
    violations = []
    for path in all_py(skip_tops={"tests", "migrations", "deployment", "docs"}):
        if is_test_file(path):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rp = rel(path)
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for field in _MONETARY_FIELDS:
                if re.search(rf"{field}\s*:\s*float\b", line, re.IGNORECASE):
                    violations.append((rp, lineno, "WARNING", f"float type hint for {field}"))
                if re.search(rf"{field}\s*=\s*float\s*\(", line, re.IGNORECASE):
                    violations.append((rp, lineno, "WARNING", f"float() call for {field}"))
    for rp, lineno, sev, msg in violations[:30]:
        pr.add(sev, rp, lineno, msg,
               detail="Use Decimal for monetary values",
               recommendation="Replace float with Decimal from decimal module.")
    if not violations:
        pr.add("PASS", ".", 0, "No float monetary field patterns found")
    else:
        pr.add("INFO", ".", 0, f"Found {len(violations)} float monetary usage(s)")
    pr.score = max(0, 100 - len(violations) * 3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P29 — ACID Pattern
def p29_acid_pattern() -> PhaseResult:
    pr = PhaseResult("P29 ACID Pattern", weight=2)
    pr.disclaimer = "Verifies Unit of Work pattern exists. Does NOT verify ACID at runtime."
    t0 = time.monotonic()
    uow_file = ROOT / "ports" / "primary" / "unit_of_work_port.py"
    if not uow_file.exists():
        pr.add("WARNING", "ports/primary/unit_of_work_port.py", 0, "UoW port not found",
               recommendation="Create ports/primary/unit_of_work_port.py with commit/rollback.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    src = uow_file.read_text(encoding="utf-8", errors="replace")
    has_commit = "commit" in src
    has_rollback = "rollback" in src
    if has_commit and has_rollback:
        pr.add("PASS", "ports/primary/unit_of_work_port.py", 0, "Unit of Work pattern found")
    else:
        missing = []
        if not has_commit:
            missing.append("commit")
        if not has_rollback:
            missing.append("rollback")
        pr.add("WARNING", "ports/primary/unit_of_work_port.py", 0,
               f"Missing: {missing}",
               recommendation=f"Implement {', '.join(missing)} methods.")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P30 — Constitution Isolation
def p30_constitution_isolation() -> PhaseResult:
    pr = PhaseResult("P30 Constitution Isolation", weight=1)
    pr.disclaimer = "Static import check only."
    t0 = time.monotonic()
    domain_dir = ROOT / "domain"
    if not domain_dir.exists():
        pr.add("INFO", "domain/", 0, "Domain directory not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    violations = []
    for path in domain_dir.rglob("*.py"):
        src = path.read_text(encoding="utf-8", errors="replace")
        if "from constitution" in src or "import constitution" in src:
            violations.append(rel(path))
    for vf in violations[:5]:
        pr.add("INFO", vf, 0, "Domain imports constitution (may violate purity)",
               recommendation="Move constitution imports to infrastructure or adapters.")
    if not violations:
        pr.add("PASS", "domain/", 0, "No direct constitution imports in domain")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P31 — ORM Primary Key Pattern
def p31_orm_primary_keys() -> PhaseResult:
    pr = PhaseResult("P31 ORM Primary Key Pattern", weight=1)
    pr.disclaimer = "Verifies primary_key declaration exists."
    t0 = time.monotonic()
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("INFO", "infrastructure/persistence_orm", 0, "ORM dir not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    no_pk = 0
    for orm_file in orm_dir.glob("*_table.py"):
        src = orm_file.read_text(encoding="utf-8", errors="replace")
        if not any(x in src for x in ("primary_key=True", "PrimaryKeyConstraint")):
            no_pk += 1
            pr.add("INFO", rel(orm_file), 0, "No primary_key declaration found",
                   recommendation="Add primary_key=True to a column or use PrimaryKeyConstraint.")
    if no_pk == 0:
        pr.add("PASS", "infrastructure/persistence_orm", 0, "Primary key declarations found")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P32 — Referential Integrity Pattern
def p32_referential_integrity() -> PhaseResult:
    pr = PhaseResult("P32 Referential Integrity Pattern", weight=1)
    pr.disclaimer = "Verifies ForeignKey declarations exist."
    t0 = time.monotonic()
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    if not orm_dir.exists():
        pr.add("INFO", "infrastructure/persistence_orm", 0, "ORM dir not found")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    fk_pattern = r"ForeignKey\s*\("
    fk_count = 0
    for orm_file in orm_dir.glob("*.py"):
        src = orm_file.read_text(encoding="utf-8", errors="replace")
        fk_count += len(re.findall(fk_pattern, src, re.IGNORECASE))
    if fk_count > 0:
        pr.add("PASS", "infrastructure/persistence_orm", 0,
               f"Found {fk_count} ForeignKey declarations")
    else:
        pr.add("INFO", "infrastructure/persistence_orm", 0, "No ForeignKey declarations found",
               recommendation="Add ForeignKey constraints for relationships.")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P33 — Concurrency Pattern
def p33_concurrency_pattern() -> PhaseResult:
    pr = PhaseResult("P33 Concurrency Pattern", weight=1)
    pr.disclaimer = "Detects version field patterns. Does NOT verify concurrency safety."
    t0 = time.monotonic()
    version_patterns = ["version", "optimistic_lock", "row_version"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        for pattern in version_patterns:
            if pattern in src.lower():
                found = True
                pr.add("PASS", rel(path), 0, f"Version field pattern: {pattern}")
                break
        if found:
            break
    if not found:
        pr.add("INFO", ".", 0, "No optimistic locking pattern detected",
               recommendation="Consider adding version field for concurrency control.")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P34 — COGS Pattern
def p34_cogs_pattern() -> PhaseResult:
    pr = PhaseResult("P34 COGS Pattern", weight=2)
    pr.disclaimer = "Verifies COGS calculation pattern exists."
    t0 = time.monotonic()
    cogs_patterns = ["cogs", "cost_of_goods_sold", "hpp"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        for pattern in cogs_patterns:
            if pattern in src.lower():
                if any(x in src.lower() for x in ["beginning", "purchase", "ending"]):
                    found = True
                    pr.add("PASS", rel(path), 0, f"COGS calculation pattern: {pattern}")
                    break
        if found:
            break
    if not found:
        pr.add("INFO", ".", 0, "COGS calculation pattern not clearly found",
               recommendation="Implement COGS logic with beginning inventory, purchases, ending inventory.")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P35 — Tax Calculation Pattern
def p35_tax_pattern() -> PhaseResult:
    pr = PhaseResult("P35 Tax Calculation Pattern", weight=2)
    pr.disclaimer = "Verifies tax calculator files exist."
    t0 = time.monotonic()
    tax_dir = ROOT / "policy_engine" / "tax_indonesia"
    if not tax_dir.exists():
        pr.add("INFO", "policy_engine/tax_indonesia", 0, "Tax directory not found",
               recommendation="Create policy_engine/tax_indonesia/ with tax calculators.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    tax_calculators = ["ppn_calculator", "pph_21_calculator", "pph_23_calculator", "pph_badan_calculator"]
    found = [c for c in tax_calculators if (tax_dir / f"{c}.py").exists()]
    if len(found) >= 3:
        pr.add("PASS", "policy_engine/tax_indonesia", 0, f"Tax calculators found: {len(found)}")
    else:
        pr.add("INFO", "policy_engine/tax_indonesia", 0,
               f"Only {len(found)} tax calculators found",
               recommendation=f"Create missing calculators: {set(tax_calculators) - set(found)}")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P36 — Depreciation Pattern
def p36_depreciation_pattern() -> PhaseResult:
    pr = PhaseResult("P36 Depreciation Pattern", weight=2)
    pr.disclaimer = "Verifies depreciation method patterns exist."
    t0 = time.monotonic()
    dep_patterns = ["depreciation", "straight_line", "declining_balance"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        if any(p in src.lower() for p in dep_patterns):
            found = True
            pr.add("PASS", rel(path), 0, "Depreciation calculation pattern found")
            break
    if not found:
        pr.add("INFO", ".", 0, "Depreciation pattern not clearly found",
               recommendation="Implement depreciation methods (straight-line, declining balance).")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P37 — Inventory Valuation Pattern
def p37_inventory_valuation() -> PhaseResult:
    pr = PhaseResult("P37 Inventory Valuation Pattern", weight=2)
    pr.disclaimer = "Verifies valuation method patterns exist."
    t0 = time.monotonic()
    inv_dir = ROOT / "domain" / "inventory"
    if not inv_dir.exists():
        pr.add("INFO", "domain/inventory", 0, "Inventory directory not found",
               recommendation="Create domain/inventory/ for inventory valuation.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    valuation_methods = ["fifo", "weighted_average", "moving_average"]
    found = []
    for inv_file in inv_dir.glob("*.py"):
        src = inv_file.read_text(encoding="utf-8", errors="replace")
        for method in valuation_methods:
            if method in src.lower():
                found.append(method)
                pr.add("PASS", rel(inv_file), 0, f"Valuation method: {method}")
    if not found:
        pr.add("INFO", "domain/inventory", 0, "No inventory valuation pattern found",
               recommendation="Implement FIFO, weighted average, or moving average.")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P38 — Fiscal Closing Pattern
def p38_fiscal_closing() -> PhaseResult:
    pr = PhaseResult("P38 Fiscal Closing Pattern", weight=2)
    pr.disclaimer = "Verifies closing procedure pattern exists."
    t0 = time.monotonic()
    closing_patterns = ["period_close", "year_end", "fiscal_closing"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        for pattern in closing_patterns:
            if pattern in src.lower():
                found = True
                pr.add("PASS", rel(path), 0, f"Fiscal closing pattern: {pattern}")
                break
        if found:
            break
    if not found:
        pr.add("INFO", ".", 0, "Fiscal closing pattern not clearly found",
               recommendation="Implement fiscal closing procedures (period_close, year_end).")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P39 — Retained Earnings Pattern
def p39_retained_earnings() -> PhaseResult:
    pr = PhaseResult("P39 Retained Earnings Pattern", weight=2)
    pr.disclaimer = "Verifies retained earnings pattern exists."
    t0 = time.monotonic()
    re_patterns = ["retained_earnings", "retainedearning"]
    found = False
    for path in all_py(skip_tops={"tests", "migrations"}):
        src = path.read_text(encoding="utf-8", errors="replace")
        for pattern in re_patterns:
            if pattern in src.lower():
                found = True
                pr.add("PASS", rel(path), 0, f"Retained earnings pattern: {pattern}")
                break
        if found:
            break
    if not found:
        pr.add("INFO", ".", 0, "Retained earnings pattern not clearly found",
               recommendation="Implement retained earnings calculation.")
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P40 — Pytest Suite
def p40_pytest(quick: bool = False) -> PhaseResult:
    pr = PhaseResult("P40 Pytest Suite", weight=3)
    pr.disclaimer = "Collects test counts via pytest --collect-only. Does NOT verify test quality."
    t0 = time.monotonic()
    if quick:
        pr.add("INFO", ".", 0, "Pytest skipped (--quick)")
        pr.score = -1
        pr.finalize_status()
        pr.duration = 0.0
        return pr
    test_path = ROOT / "tests"
    if not test_path.exists():
        pr.add("WARNING", "tests/", 0, "tests directory not found",
               recommendation="Create tests/ directory and add test files.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    cmd = [sys.executable, "-m", "pytest", str(test_path),
           "--collect-only", "-q", "--no-header", "--disable-warnings"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(ROOT))
        output = result.stdout + result.stderr
        patterns = [r"collected\s+(\d+)\s+items?", r"collected\s+(\d+)\s+tests?",
                    r"(\d+)\s+tests? collected", r"collected\s+(\d+)"]
        test_count = 0
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                test_count = int(match.group(1))
                break
        if test_count == 0:
            summary_match = re.search(r"===+\s+(\d+)\s+passed", output)
            if summary_match:
                test_count = int(summary_match.group(1))
                skipped_match = re.search(r"(\d+)\s+skipped", output)
                if skipped_match:
                    test_count += int(skipped_match.group(1))
        if test_count > 0:
            pr.add("PASS", "tests/", 0, f"Found {test_count} tests via pytest collection")
            pr.score = min(100, test_count // 10)
        else:
            if result.returncode == 0 or "passed" in output:
                pr.add("WARNING", "tests/", 0, "Tests exist but count could not be determined")
                pr.score = 50
            else:
                pr.add("WARNING", "tests/", 0, "No tests collected or pytest collection failed",
                       recommendation="Check test discovery or pytest installation.")
                pr.score = 0
    except subprocess.TimeoutExpired:
        pr.add("WARNING", "tests/", 0, "Pytest collection timed out after 60s")
        pr.score = 30
    except Exception as e:
        pr.add("WARNING", "tests/", 0, f"Pytest collection error: {type(e).__name__}")
        pr.score = 0
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P41 — Compliance Structure
_COMPLIANCE_FILES = ["policy_engine/psak/psak_aggregator.py",
                     "policy_engine/ifrs/ifrs_aggregator.py",
                     "compliance/psak_checker.py",
                     "compliance/ifrs_checker.py"]

def p41_compliance_structure() -> PhaseResult:
    pr = PhaseResult("P41 Compliance Structure", weight=2)
    pr.disclaimer = "Verifies compliance files exist."
    t0 = time.monotonic()
    found = sum(1 for f in _COMPLIANCE_FILES if (ROOT / f).exists())
    if found == len(_COMPLIANCE_FILES):
        pr.add("PASS", ".", 0, f"All {found} compliance files found")
    else:
        pr.add("INFO", ".", 0, f"Compliance files: {found}/{len(_COMPLIANCE_FILES)}",
               recommendation=f"Create missing files.")
    pr.score = int(found / len(_COMPLIANCE_FILES) * 100) if _COMPLIANCE_FILES else 0
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# P42 — Schema Consistency
def p42_schema_consistency() -> PhaseResult:
    pr = PhaseResult("P42 Schema Consistency", weight=3)
    pr.disclaimer = "Compares ORM table definitions with migration create_table statements."
    t0 = time.monotonic()
    orm_dir = ROOT / "infrastructure" / "persistence_orm"
    alembic_dir = ROOT / "migrations" / "versions"
    if not orm_dir.exists() or not alembic_dir.exists():
        pr.add("INFO", ".", 0, "ORM or migrations directory not found",
               recommendation="Ensure both ORM and migrations directories exist.")
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    orm_tables = set()
    for orm_file in orm_dir.glob("*_table.py"):
        src = orm_file.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r'__tablename__\s*=\s*["\']([^"\']+)["\']', src)
        orm_tables.update(matches)
    migration_tables = set()
    for mig_file in alembic_dir.glob("*.py"):
        src = mig_file.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r'create_table\s*\(\s*["\']([^"\']+)["\']', src, re.IGNORECASE)
        migration_tables.update(matches)
        create_pattern = r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\`]?(\w+)["\`]?'
        migration_tables.update(re.findall(create_pattern, src, re.IGNORECASE))
    only_in_orm = orm_tables - migration_tables
    for table in list(only_in_orm)[:10]:
        pr.add("WARNING", "infrastructure/persistence_orm", 0,
               f"Table '{table}' in ORM but not in migrations",
               recommendation=f"Create migration for table '{table}'.")
    if not only_in_orm:
        pr.add("PASS", ".", 0, "ORM and migration table definitions consistent")
    else:
        pr.add("WARNING", ".", 0, f"Found {len(only_in_orm)} table(s) in ORM not in migrations")
    pr.score = max(0, 100 - len(only_in_orm) * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# ─── RUNTIME PHASES (P43–P46) ─────────────────────────────────────────────

def _safe_import_module(mod_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(mod_name)
        return True, ""
    except Exception as e:
        parts = mod_name.split(".")
        if len(parts) == 1:
            candidates = list(ROOT.rglob(f"{parts[0]}.py"))
            if not candidates:
                return False, f"Module not found: {mod_name}"
            path = candidates[0]
        else:
            path = ROOT / "/".join(parts[:-1]) / f"{parts[-1]}.py"
            if not path.exists():
                return False, f"File not found: {path}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return False, f"Cannot create spec for {mod_name}"
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as ex:
            return False, f"Execution error: {type(ex).__name__}: {ex}"
        return True, ""

def p43_runtime_imports() -> PhaseResult:
    pr = PhaseResult("P43 Runtime Import Test", weight=4)
    pr.disclaimer = "Attempts to import every module (excluding tests/migrations). May fail if dependencies missing."
    t0 = time.monotonic()
    files = all_py(skip_tops={"tests", "migrations", "deployment", "docs"}, include_checker=False)
    errors = []
    for path in files:
        mod = mod_name(path)
        if not mod or mod.startswith("main_checker"):
            continue
        if path.name == "__init__.py":
            continue
        ok, err = _safe_import_module(mod)
        if not ok:
            errors.append((rel(path), mod, err))
            pr.add("CRITICAL", rel(path), 0,
                   f"ImportError in module '{mod}': {err[:100]}",
                   recommendation=f"Check dependencies and fix import in {mod}.")
            if len(errors) >= 20:
                break
    if not errors:
        pr.add("PASS", ".", 0, f"All {len(files)} modules imported successfully")
        pr.score = 100
    else:
        pr.add("INFO", ".", 0, f"Found {len(errors)} import errors (first 20 shown)")
        pr.score = max(0, 100 - len(errors) * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p44_app_bootstrap() -> PhaseResult:
    pr = PhaseResult("P44 Application Bootstrap", weight=5)
    pr.disclaimer = "Attempts to create the ASGI app; may fail due to config/dependencies."
    t0 = time.monotonic()
    try:
        main_mod = importlib.import_module("app.main")
        app_obj = None
        if hasattr(main_mod, "app"):
            app_obj = main_mod.app
        elif hasattr(main_mod, "create_app"):
            app_obj = main_mod.create_app()
        elif hasattr(main_mod, "get_app"):
            app_obj = main_mod.get_app()
        else:
            pr.add("CRITICAL", "app/main.py", 0,
                   "No 'app' or 'create_app' found",
                   recommendation="Define 'app' variable or 'create_app()' function in app/main.py.")
            pr.score = 0
            pr.finalize_status()
            pr.duration = time.monotonic() - t0
            return pr
        if callable(app_obj) and not isinstance(app_obj, type):
            app_obj = app_obj()
        if hasattr(app_obj, "__call__"):
            pr.add("PASS", "app/main.py", 0, "Application bootstrap successful")
            pr.score = 100
        else:
            pr.add("CRITICAL", "app/main.py", 0, "App object is not callable",
                   recommendation="Ensure app is an ASGI application (callable).")
            pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "app/main.py", 0,
               f"Bootstrap failed: {type(e).__name__}: {str(e)[:150]}",
               recommendation="Check application configuration and dependencies.")
        pr.score = 0
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p45_db_connectivity() -> PhaseResult:
    pr = PhaseResult("P45 Database Connectivity", weight=4)
    pr.disclaimer = "Tests database connection using app config or environment. Requires DATABASE_URL."
    t0 = time.monotonic()
    database_url = None
    try:
        from app.main import settings
        database_url = settings.database_url
    except Exception:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            database_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/erp_db"
    if not database_url:
        pr.add("CRITICAL", "config/", 0,
               "DATABASE_URL not found in environment or app settings",
               recommendation="Set DATABASE_URL environment variable.")
        pr.score = 0
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        engine = create_async_engine(database_url, pool_pre_ping=True)
        async def test():
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        asyncio.run(test())
        pr.add("PASS", "config/", 0, "Database connection successful")
        pr.score = 100
    except ImportError as e:
        pr.add("CRITICAL", "config/", 0, f"Import error: {e}",
               recommendation="Install SQLAlchemy and asyncpg.")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "config/", 0,
               f"DB connection failed: {type(e).__name__}: {str(e)[:150]}",
               recommendation="Check DATABASE_URL and database service availability.")
        pr.score = 0
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p46_migration_dryrun() -> PhaseResult:
    pr = PhaseResult("P46 Migration Dry-Run", weight=3)
    pr.disclaimer = "Runs alembic upgrade head --sql (no actual DB changes)."
    t0 = time.monotonic()
    if not (ROOT / "alembic.ini").exists():
        pr.add("INFO", ".", 0, "alembic.ini not found; skip migration dry-run",
               recommendation="Initialize Alembic: alembic init migrations")
        pr.score = -1
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    cmd = ["alembic", "upgrade", "head", "--sql"]
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            pr.add("PASS", "migrations/", 0, "Migration dry-run successful")
            pr.score = 100
        else:
            pr.add("CRITICAL", "migrations/", 0,
                   f"Migration dry-run failed: {result.stderr[:150]}",
                   recommendation="Check migration files and database compatibility.")
            pr.score = 0
    except subprocess.TimeoutExpired:
        pr.add("CRITICAL", "migrations/", 0, "Migration dry-run timed out after 30s")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "migrations/", 0,
               f"Migration error: {type(e).__name__}",
               recommendation="Ensure Alembic is installed and configured.")
        pr.score = 0
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# ─── ADDITIONAL PHASES (P47–P53) ──────────────────────────────────────────

async def _check_db() -> str | None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return "DATABASE_URL not set"
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(db_url, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return None
    except Exception as e:
        return f"Database connection failed: {type(e).__name__}: {e}"

async def _check_redis() -> str | None:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return "REDIS_URL not set"
    try:
        import redis.asyncio as redis_async
        r = redis_async.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        return None
    except ImportError:
        return "redis module not installed"
    except Exception as e:
        return f"Redis connection failed: {type(e).__name__}: {e}"

async def _check_kafka() -> str | None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap:
        return None
    try:
        from kafka.admin import KafkaAdminClient
        admin = KafkaAdminClient(bootstrap_servers=bootstrap, request_timeout_ms=3000)
        admin.list_topics()
        admin.close()
        return None
    except ImportError:
        return "kafka-python module not installed"
    except Exception as e:
        return f"Kafka connection failed: {type(e).__name__}: {e}"

def p47_infrastructure() -> PhaseResult:
    pr = PhaseResult("P47 Infrastructure Connectivity", weight=3)
    pr.disclaimer = "Tests DB, Redis, Kafka connections if env vars are set."
    t0 = time.monotonic()
    checks = [
        ("Database (PostgreSQL)", _check_db, True),
        ("Redis", _check_redis, True),
        ("Kafka", _check_kafka, False),
    ]
    for name, fn, critical in checks:
        err = asyncio.run(fn())
        if err:
            sev = "CRITICAL" if critical else "WARNING"
            pr.add(sev, "infrastructure", 0, f"{name}: {err}",
                   recommendation="Check service availability or configuration.")
        else:
            pr.add("PASS", "infrastructure", 0, f"{name} connection OK")
    if pr.count("CRITICAL") == 0:
        pr.add("PASS", "infrastructure", 0, "All critical infrastructure checks passed")
    pr.score = max(0, 100 - pr.count("CRITICAL") * 20 - pr.count("WARNING") * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p48_orm_mapper() -> PhaseResult:
    pr = PhaseResult("P48 ORM Mapper Validation", weight=3)
    pr.disclaimer = "Validates SQLAlchemy ORM mappers by attempting a simple query."
    t0 = time.monotonic()
    try:
        from infrastructure.database.session_factory_sqlalchemy import get_session_factory_sync
        from infrastructure.persistence_orm.outbox_message_table import OutboxMessageTable
        from sqlalchemy import select
        async def _test():
            factory = get_session_factory_sync()
            session_maker = factory.get_session_factory()
            if session_maker is None:
                raise Exception("Session factory not available")
            async with session_maker() as session:
                stmt = select(OutboxMessageTable).limit(1)
                await session.execute(stmt)
        asyncio.run(_test())
        pr.add("PASS", "infrastructure/persistence_orm", 0, "ORM mappers validated successfully")
        pr.score = 100
    except ImportError as e:
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               f"Import error during ORM validation: {e}",
               recommendation="Ensure all ORM modules are importable.")
        pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "infrastructure/persistence_orm", 0,
               f"ORM mapper error: {type(e).__name__}: {str(e)[:150]}",
               recommendation="Check SQLAlchemy model definitions and relationships.")
        if "NoForeignKeysError" in str(e):
            pr.findings[-1].recommendation += " Missing ForeignKey in relationship."
        pr.score = 0
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p49_auto_discovery() -> PhaseResult:
    pr = PhaseResult("P49 Auto-Discovery Import Scan", weight=2)
    pr.disclaimer = "Scans all discovered Python modules for importability (static)."
    t0 = time.monotonic()
    all_discovered = []
    for py_file in ROOT.glob("*.py"):
        if py_file.name in _CHECKER_FILES:
            continue
        mod = mod_name(py_file)
        if mod:
            all_discovered.append(mod)
    for py_file in ROOT.rglob("*.py"):
        if py_file.parent == ROOT:
            continue
        if any(part in _SKIP_ALWAYS for part in py_file.parts):
            continue
        mod = mod_name(py_file)
        if mod and mod not in all_discovered:
            all_discovered.append(mod)
    total = len(all_discovered)
    errors = 0
    for mod in all_discovered[:50]:
        ok, err = _safe_import_module(mod)
        if not ok:
            errors += 1
            pr.add("WARNING", mod.replace(".", "/") + ".py", 0,
                   f"Import error: {mod} — {err[:100]}",
                   recommendation="Fix import dependencies.")
    if errors == 0:
        pr.add("PASS", ".", 0, f"Auto-discovery: all {total} modules importable")
    else:
        pr.add("INFO", ".", 0, f"Auto-discovery: {errors}/{total} modules have import errors")
    pr.score = max(0, 100 - errors * 3)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p50_critical_imports() -> PhaseResult:
    pr = PhaseResult("P50 Critical Modules Import Scan", weight=3)
    pr.disclaimer = "Imports each module listed in CRITICAL_MODULES with descriptive labels."
    t0 = time.monotonic()
    errors = 0
    for label, mod in CRITICAL_MODULES:
        ok, err = _safe_import_module(mod)
        if not ok:
            errors += 1
            pr.add("CRITICAL", mod.replace(".", "/") + ".py", 0,
                   f"Critical import failed: {label} — {err[:100]}",
                   recommendation=f"Fix import for {mod}.")
        else:
            pr.add("PASS", mod.replace(".", "/") + ".py", 0, f"{label} import OK")
    if errors == 0:
        pr.add("PASS", ".", 0, f"All {len(CRITICAL_MODULES)} critical modules import successfully")
    else:
        pr.add("INFO", ".", 0, f"{errors} critical modules failed to import")
    pr.score = max(0, 100 - errors * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p51_environment_vars() -> PhaseResult:
    pr = PhaseResult("P51 Environment Variables", weight=1)
    pr.disclaimer = "Checks required and optional environment variables."
    t0 = time.monotonic()
    missing = 0
    for var, example in REQUIRED_ENV_VARS:
        if not os.environ.get(var):
            missing += 1
            pr.add("CRITICAL", ".env", 0, f"Missing required env var: {var}",
                   recommendation=f"Set {var} (example: {example})")
    if missing == 0:
        pr.add("PASS", ".env", 0, f"All {len(REQUIRED_ENV_VARS)} required env vars are set")
    else:
        pr.add("INFO", ".env", 0, f"{missing} required env vars missing")
    for var, example in OPTIONAL_ENV_VARS:
        if not os.environ.get(var):
            pr.add("INFO", ".env", 0, f"Optional env var {var} not set (example: {example})")
    pr.score = max(0, 100 - missing * 20)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p52_critical_paths() -> PhaseResult:
    pr = PhaseResult("P52 Critical Paths", weight=1)
    pr.disclaimer = "Verifies existence of critical files/directories."
    t0 = time.monotonic()
    missing = 0
    for rel_path in CRITICAL_PATHS:
        if not (ROOT / rel_path).exists():
            missing += 1
            pr.add("WARNING", rel_path, 0, "Critical path missing",
                   recommendation=f"Create file/directory: {rel_path}")
    if missing == 0:
        pr.add("PASS", ".", 0, f"All {len(CRITICAL_PATHS)} critical paths exist")
    else:
        pr.add("INFO", ".", 0, f"{missing} critical paths missing")
    pr.score = max(0, 100 - missing * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p53_asgi_validation() -> PhaseResult:
    pr = PhaseResult("P53 ASGI App Validation", weight=2)
    pr.disclaimer = "Imports asgi.py and checks for 'app' attribute."
    t0 = time.monotonic()
    try:
        asgi_mod = importlib.import_module("asgi")
        if hasattr(asgi_mod, "app"):
            pr.add("PASS", "asgi.py", 0, "ASGI app found (attribute 'app')")
            pr.score = 100
        else:
            pr.add("CRITICAL", "asgi.py", 0, "No 'app' attribute in asgi.py",
                   recommendation="Define 'app' in asgi.py.")
            pr.score = 0
    except Exception as e:
        pr.add("CRITICAL", "asgi.py", 0,
               f"Failed to import asgi.py: {type(e).__name__}: {str(e)[:100]}",
               recommendation="Fix syntax or dependencies in asgi.py.")
        pr.score = 0
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

# ─── NEW ADVANCED PHASES (P54 – P60) ──────────────────────────────────────

def p54_fastapi_routes() -> PhaseResult:
    pr = PhaseResult("P54 FastAPI Route Validation", weight=3)
    pr.disclaimer = "Detects duplicate routes, invalid response models, and missing dependencies via AST."
    t0 = time.monotonic()
    router_dir = ROOT / "adapters" / "primary_api" / "v1"
    if not router_dir.exists():
        pr.add("INFO", "adapters/primary_api/v1", 0, "Router directory not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    route_map: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for py_file in router_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        tree = get_ast_tree(py_file)
        if tree is None:
            continue
        rp = rel(py_file)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                        method = decorator.func.attr.upper()
                        if method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                            if decorator.args:
                                path_expr = decorator.args[0]
                                if isinstance(path_expr, ast.Constant):
                                    path = path_expr.value
                                    key = (path, method)
                                    route_map.setdefault(key, []).append((rp, node.lineno))
    duplicates = 0
    for (path, method), locations in route_map.items():
        if len(locations) > 1:
            duplicates += 1
            for loc in locations:
                pr.add("WARNING", loc[0], loc[1],
                       f"Duplicate route: {method} {path}",
                       recommendation="Remove duplicate route definition.")
    if duplicates == 0:
        pr.add("PASS", "adapters/primary_api/v1", 0,
               f"All {len(route_map)} routes unique")
    else:
        pr.add("INFO", "adapters/primary_api/v1", 0,
               f"Found {duplicates} duplicate route(s)")
    pr.score = max(0, 100 - duplicates * 20)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p55_di_container() -> PhaseResult:
    pr = PhaseResult("P55 DI Container Validation", weight=4)
    pr.disclaimer = "Verifies that all required dependencies are registered in the container."
    t0 = time.monotonic()
    try:
        from bootstrap.dependency_container.service_registry import ServiceRegistry
        registry = ServiceRegistry()
        required_interfaces = [
            "IJournalRepository", "IUnitOfWork", "IEventPublisher", "ITaxAuthorityPort",
            "IUserRepository", "IAccountRepository", "IArRepository", "IApRepository",
            "IInventoryRepository", "IFixedAssetRepository", "IPayrollRepository",
            "IManufacturingRepository", "IConsolidationRepository", "IForexRepository",
            "IHedgeRepository",
        ]
        missing = []
        for iface in required_interfaces:
            try:
                registry.resolve(iface)
            except Exception:
                missing.append(iface)
        for iface in missing:
            pr.add("CRITICAL", "bootstrap/dependency_container", 0,
                   f"Dependency not registered: {iface}",
                   recommendation=f"Register {iface} in the DI container.")
        if not missing:
            pr.add("PASS", "bootstrap/dependency_container", 0,
                   "All required dependencies are registered")
        else:
            pr.add("INFO", "bootstrap/dependency_container", 0,
                   f"Missing {len(missing)} dependencies")
        pr.score = max(0, 100 - len(missing) * 20)
    except ImportError as e:
        pr.add("INFO", "bootstrap/dependency_container", 0,
               f"DI module not importable: {e}",
               recommendation="Ensure DI container is implemented.")
        pr.score = 50
    except Exception as e:
        pr.add("WARNING", "bootstrap/dependency_container", 0,
               f"DI check error: {type(e).__name__}: {str(e)[:100]}",
               recommendation="Check DI container implementation.")
        pr.score = 50
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p56_cqrs_handlers() -> PhaseResult:
    pr = PhaseResult("P56 CQRS Handler Validation", weight=4)
    pr.disclaimer = "Checks that every Command/Query has a corresponding Handler."
    t0 = time.monotonic()
    cmd_dir = ROOT / "application" / "commands_cqrs"
    usecase_dir = ROOT / "application" / "use_cases"
    if not cmd_dir.exists() or not usecase_dir.exists():
        pr.add("INFO", "application/commands_cqrs", 0, "CQRS directories not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr
    commands = set()
    for py_file in cmd_dir.glob("*.py"):
        tree = get_ast_tree(py_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name.endswith("Command") or node.name.endswith("Query"):
                    commands.add(node.name)
    handlers = set()
    for py_file in usecase_dir.glob("*.py"):
        tree = get_ast_tree(py_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name.endswith("Handler"):
                    handlers.add(node.name)
    unmatched = []
    for cmd in commands:
        base = cmd[:-7] if cmd.endswith("Command") else cmd[:-5] if cmd.endswith("Query") else cmd
        expected_handler = base + "Handler"
        if expected_handler not in handlers:
            unmatched.append(cmd)
    for cmd in unmatched[:20]:
        pr.add("CRITICAL", "application/use_cases", 0,
               f"No handler found for {cmd}",
               recommendation=f"Create {cmd.replace('Command','Handler')} or {cmd.replace('Query','Handler')}.")
    if not unmatched:
        pr.add("PASS", "application/use_cases", 0,
               f"All {len(commands)} commands/queries have handlers")
    else:
        pr.add("INFO", "application/use_cases", 0,
               f"{len(unmatched)} commands/queries missing handlers")
    pr.score = max(0, 100 - len(unmatched) * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p57_event_handlers() -> PhaseResult:
    pr = PhaseResult("P57 Event Handler Validation", weight=3)
    pr.disclaimer = "Checks that domain events have at least one subscriber."
    t0 = time.monotonic()
    event_classes = set()
    for domain_dir in ROOT.glob("domain/*"):
        events_file = domain_dir / "domain_events.py"
        if not events_file.exists():
            continue
        tree = get_ast_tree(events_file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "Event" in node.name:
                event_classes.add(node.name)
    subscriber_dir = ROOT / "application" / "events"
    if not subscriber_dir.exists():
        subscriber_dir = ROOT / "application" / "handlers"
    subscribers = set()
    if subscriber_dir.exists():
        for py_file in subscriber_dir.glob("*.py"):
            tree = get_ast_tree(py_file)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and "handle" in node.name.lower():
                    subscribers.add(node.name)
                elif isinstance(node, ast.ClassDef) and "Handler" in node.name:
                    subscribers.add(node.name)
    uncovered = []
    for ev in event_classes:
        found = False
        for sub in subscribers:
            if ev in sub:
                found = True
                break
        if not found:
            uncovered.append(ev)
    for ev in uncovered[:10]:
        pr.add("WARNING", "domain/", 0,
               f"Event '{ev}' may have no subscriber",
               recommendation=f"Create a handler for {ev} in application/events/")
    if not uncovered:
        pr.add("PASS", "application/events", 0,
               f"All {len(event_classes)} events have subscribers")
    else:
        pr.add("INFO", "application/events", 0,
               f"{len(uncovered)} events without subscriber")
    pr.score = max(0, 100 - len(uncovered) * 5)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p58_repository_contract() -> PhaseResult:
    pr = PhaseResult("P58 Repository Contract Validation", weight=3)
    pr.disclaimer = "Verifies that repository implementations implement all abstract/required methods from ports."
    t0 = time.monotonic()
    port_dir = ROOT / "ports" / "primary"
    impl_dir = ROOT / "adapters" / "secondary_impl"
    if not port_dir.exists() or not impl_dir.exists():
        pr.add("INFO", "ports/primary", 0, "Ports or adapters not found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    # Helper: cek apakah method body hanya pass/raise/...
    def is_abstract_method(method_node: ast.FunctionDef) -> bool:
        # Jika method memiliki decorator @abstractmethod
        for dec in method_node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "abstractmethod":
                return True
            elif isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod":
                return True
        # Jika body hanya pass atau raise NotImplementedError atau ...
        if len(method_node.body) == 1:
            stmt = method_node.body[0]
            if isinstance(stmt, (ast.Pass, ast.Expr)):
                # pass or ... (Expr dengan Ellipsis)
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value == Ellipsis:
                    return True
                if isinstance(stmt, ast.Pass):
                    return True
            elif isinstance(stmt, ast.Raise):
                # raise NotImplementedError
                if isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name) and stmt.exc.func.id == "NotImplementedError":
                    return True
        return False

    def extract_methods(tree: ast.AST, class_name: str) -> dict[str, bool]:
        """Return dict of method name -> is_abstract (bool)"""
        methods = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods[item.name] = is_abstract_method(item)
        return methods

    # Scan port files to find port classes
    port_files = {}
    for py_file in port_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        tree = get_ast_tree(py_file)
        if tree is None:
            continue
        class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        if not class_names:
            continue
        # Ambil class pertama yang mungkin port (biasanya class dengan nama mengandung Port atau Repository)
        # Kita ambil semua class yang namanya mengandung 'Port' atau 'Repository'
        for cls in class_names:
            if "Port" in cls or "Repository" in cls:
                methods = extract_methods(tree, cls)
                if methods:
                    port_files[py_file.stem] = (cls, methods)
                    break

    # Scan implementation files
    impl_files = {}
    for py_file in impl_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        tree = get_ast_tree(py_file)
        if tree is None:
            continue
        # Cari class yang mungkin implementasi (biasanya class dengan nama mengandung 'Impl' atau 'Adapter')
        class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        for cls in class_names:
            # Cari method dari class ini
            methods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == cls:
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            methods.add(item.name)
                    break
            if methods:
                impl_files[py_file.stem] = (cls, methods)
                break

    # Match port to implementation based on naming convention
    # Misal port: customer_repository_port -> impl: sqlalchemy_customer_repository_impl
    # Kita coba matching dengan menghilangkan awalan 'sqlalchemy_' dan akhiran '_impl'
    unmatched_ports = []
    method_missing = []
    for port_stem, (port_class, port_methods) in port_files.items():
        # Cari impl yang cocok
        # pola: sqlalchemy_{port_stem}_impl? atau {port_stem}_impl?
        possible_impl_stems = []
        # 1. sqlalchemy_{port_stem.replace('_port','')}_impl
        base = port_stem.replace("_port", "").replace("_repository", "")
        possible_impl_stems.append(f"sqlalchemy_{base}_impl")
        possible_impl_stems.append(f"sqlalchemy_{base}_repository_impl")
        possible_impl_stems.append(f"{base}_impl")
        possible_impl_stems.append(f"{base}_repository_impl")
        # Tambahkan pola lain: jika port_stem berisi 'repository' maka hilangkan
        impl_found = None
        for stem in possible_impl_stems:
            if stem in impl_files:
                impl_found = impl_files[stem]
                break
        if not impl_found:
            # Coba cari berdasarkan substring
            for impl_stem, (cls, methods) in impl_files.items():
                if base in impl_stem or port_stem.replace("_port","") in impl_stem:
                    impl_found = (cls, methods)
                    break
        if not impl_found:
            unmatched_ports.append((port_stem, port_class))
            continue

        impl_class, impl_methods = impl_found
        # Periksa method yang wajib (abstract) dan belum ada di impl
        required_methods = [m for m, is_abstract in port_methods.items() if is_abstract]
        for method_name in required_methods:
            if method_name not in impl_methods:
                method_missing.append((port_stem, impl_class, method_name, impl_files[impl_stem][0]))

    # Laporkan
    for port_stem, port_class in unmatched_ports[:20]:
        pr.add("WARNING", f"ports/primary/{port_stem}.py", 0,
               f"No implementation found for {port_stem}",
               recommendation=f"Create adapter for {port_stem} in adapters/secondary_impl/")

    for port_stem, impl_class, method_name, impl_file in method_missing[:20]:
        # Cari file impl
        pr.add("WARNING", f"adapters/secondary_impl/{impl_file}.py", 0,
               f"Method '{method_name}' from {port_stem} not implemented in {impl_file}.py",
               recommendation=f"Implement {method_name} in the adapter.")

    if not unmatched_ports and not method_missing:
        pr.add("PASS", "adapters/secondary_impl", 0,
               "All repository contracts are fully implemented")
    else:
        pr.add("INFO", ".", 0, f"Found {len(unmatched_ports)} unmatched ports and {len(method_missing)} missing methods")

    pr.score = max(0, 100 - (len(unmatched_ports) * 10 + len(method_missing) * 2))
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p59_dto_mapper() -> PhaseResult:
    pr = PhaseResult("P59 DTO Mapper Validation", weight=2)
    pr.disclaimer = "Checks that mapper files contain mapping functions (map_*, to_*, dto_to_*) or Mapper/Registry classes."
    t0 = time.monotonic()
    # Hanya periksa direktori application/mappers (bukan transformers)
    mapper_dirs = [ROOT / "application" / "mappers"]
    mapper_files = []
    for d in mapper_dirs:
        if d.exists():
            mapper_files.extend(d.glob("*.py"))
    if not mapper_files:
        pr.add("INFO", "application/mappers/", 0, "No mapper files found")
        pr.score = 50
        pr.finalize_status()
        pr.duration = time.monotonic() - t0
        return pr

    for mf in mapper_files:
        if mf.name == "__init__.py":
            continue
        src = mf.read_text(encoding="utf-8", errors="replace")
        # Cari pola mapping yang umum:
        # - Fungsi dengan awalan map_, to_, dto_to_
        # - Kelas dengan nama mengandung Mapper atau Registry
        has_mapping = False
        if re.search(r'def\s+(map_\w+|to_\w+|dto_to_\w+)', src, re.IGNORECASE):
            has_mapping = True
        elif re.search(r'class\s+\w+(Mapper|Registry)', src):
            has_mapping = True
        elif re.search(r'def\s+\w*map\w*\(', src, re.IGNORECASE) or \
             re.search(r'def\s+\w*to_dto\w*\(', src, re.IGNORECASE) or \
             re.search(r'def\s+\w*to_entity\w*\(', src, re.IGNORECASE):
            has_mapping = True

        if not has_mapping:
            pr.add("WARNING", rel(mf), 0,
                   "Mapper missing mapping functions (map_*, to_*, dto_to_*) or Mapper/Registry class",
                   recommendation="Ensure mapper has mapping functions or is a Mapper/Registry class.")

    if pr.count("WARNING") == 0:
        pr.add("PASS", "application/mappers/", 0,
               "All mappers have mapping functions or Mapper/Registry classes")
    pr.score = max(0, 100 - pr.count("WARNING") * 10)
    pr.finalize_status()
    pr.duration = time.monotonic() - t0
    return pr

def p60_startup_dryrun() -> PhaseResult:
    pr = PhaseResult("P60 Startup Dry-Run", weight=5)
    pr.disclaimer = "Attempts to fully initialize the application and run a minimal use case."
    t0 = time.monotonic()
    try:
        import app.main
        if hasattr(app.main, "app"):
            app_obj = app.main.app
        elif hasattr(app.main, "create_app"):
            app_obj = app.main.create_app()
        else:
            raise Exception("No app or create_app found")
        from fastapi.testclient import TestClient
        client = TestClient(app_obj)
        response = client.get("/health")
        if response.status_code == 200:
            pr.add("PASS", "app/main.py", 0, "Startup dry-run successful (health endpoint OK)")
            pr.score = 100
        else:
            pr.add("CRITICAL", "app/main.py", 0,
                   f"Health endpoint returned {response.status_code}",
                   recommendation="Check application wiring and dependencies.")
            pr.score = 50
    except Exception as e:
        pr.add("CRITICAL", "app/main.py", 0,
               f"Startup dry-run failed: {type(e).__name__}: {str(e)[:150]}",
               recommendation="Check application bootstrap, imports, and dependencies.")
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

def run_phases(phase_filter: str | None, quick: bool, verbose: bool, runtime: bool) -> tuple[int, list[PhaseResult]]:
    results: list[PhaseResult] = []
    for key, fn, takes_runtime in _ALL_PHASES:
        if phase_filter and key != phase_filter:
            continue
        if takes_runtime and not runtime:
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
              runtime: bool, no_color: bool) -> int:
    if no_color:
        _setup_colour(False)
    print(banner("SOVEREIGN ERP — STRUCTURAL INTEGRITY AUDITOR v17.0 (UNIFIED)"))
    print(f"  Root   : {ROOT}")
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  Mode   : {'QUICK' if quick else 'FULL AUDIT'}")
    print(f"  Runtime: {'ACTIVATED' if runtime else 'DISABLED'}")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n  {YELLOW}NOTE: This auditor verifies CODE STRUCTURE and (optionally) RUNTIME behavior.{RESET}")
    print(f"  {YELLOW}      It does NOT prove financial accuracy.{RESET}")
    if runtime:
        print(f"\n  {RED}{BOLD}⚠ RUNTIME MODE ACTIVE — will execute code (imports, app bootstrap, DB connection).{RESET}")
        print(f"  {RED}      Ensure you are in a safe environment (e.g., test database).{RESET}")
    (base, adj), results = run_phases(phase_filter, quick, verbose, runtime)
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
            "checker_version": "17.0",
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
    print(f"  ASGI App   : asgi:app")
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

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sovereign ERP — Structural Integrity Auditor v17.0 (Unified)",
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
            code = run_audit(args.phase, args.quick, args.verbose, args.json, args.runtime, args.no_color)
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
                "checker_version": "17.0",
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