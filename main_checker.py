#!/usr/bin/env python3
"""
main_checker.py
===============
ERP Accounting Engine — Health Check & Validation Tool (Hardened)
Bank-Grade Accounting System | DDD + CQRS + Event Sourcing + Hexagonal

Cara menjalankan:
  python main_checker.py                      # Jalankan server (development) dengan pre-check ringan
  python main_checker.py --check              # Health check: import + env + struktur
  python main_checker.py --full-check         # Full check: semua termasuk koneksi infrastruktur
  python main_checker.py --deep-check         # Deep check: syntax + circular + import SEMUA modul + semua fase
  python main_checker.py --check --verbose    # Tampilkan detail tiap import
  python main_checker.py --check --traceback  # Tampilkan traceback penuh jika error
  python main_checker.py --check --quiet      # Hanya tampilkan error (sembunyikan sukses)
  python main_checker.py --scan-all           # Auto-discover & scan SEMUA modul .py di project
  python main_checker.py --syntax-check       # Cek syntax error semua file .py (tanpa import)
  python main_checker.py --circular-check     # Deteksi circular imports
  python main_checker.py --force              # Paksa start meskipun error non-kritis
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import argparse
import ast
import asyncio
import logging
import os
import sys
import textwrap
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

# -----------------------------------------------------------------------------
# PROJECT ROOT & PATH SETUP
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# -----------------------------------------------------------------------------
# LOGGING CONFIGURATION (clean & minimal)
# -----------------------------------------------------------------------------
class CleanFormatter(logging.Formatter):
    """Formatter sederhana tanpa timestamp dan nama logger untuk output checker."""
    def format(self, record):
        return f"{record.levelname}: {record.getMessage()}"

def configure_logging(verbose: bool = False, quiet: bool = False):
    """Atur logging global: hanya error/warning, dan format bersih."""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Level root: ERROR jika quiet, WARNING jika tidak verbose, DEBUG jika verbose
    if verbose:
        root_logger.setLevel(logging.DEBUG)
    elif quiet:
        root_logger.setLevel(logging.ERROR)
    else:
        root_logger.setLevel(logging.WARNING)

    # Handler console dengan format bersih
    console = logging.StreamHandler(sys.stdout)
    if verbose:
        console.setLevel(logging.DEBUG)
    else:
        console.setLevel(logging.WARNING)
    console.setFormatter(CleanFormatter())
    root_logger.addHandler(console)

    # File handler tetap simpan semua error (tanpa format bersih)
    file_handler = logging.FileHandler(LOG_DIR / "error.log", encoding="utf-8")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s"))
    root_logger.addHandler(file_handler)

    # Matikan logger bawaan yang berisik
    for name in [
        "alembic", "prometheus_client", "urllib3", "asyncio",
        "pydantic", "kafka", "opentelemetry", "sqlalchemy.engine",
        "sqlalchemy.pool", "passlib", "multipart", "aiokafka",
        "infrastructure", "application", "adapters", "domain",
        "kernel", "config", "policy_engine", "compliance", "audit",
        "projections", "reports", "event_gateway", "bootstrap",
        "constitution", "axioms"
    ]:
        logger = logging.getLogger(name)
        logger.setLevel(logging.ERROR if not verbose else logging.DEBUG)
        logger.propagate = True

# Panggil konfigurasi awal (akan di-override sesuai argumen)
configure_logging(verbose=False, quiet=False)

# -----------------------------------------------------------------------------
# KONSTANTA
# -----------------------------------------------------------------------------
APP_NAME = "ERP Accounting Engine"
APP_VERSION = "1.0.0"
BANNER = f"""
╔══════════════════════════════════════════════════════════════╗
║          ERP ACCOUNTING ENGINE  v{APP_VERSION}                       ║
║  Bank-Grade · DDD · CQRS · Event Sourcing · Hexagonal        ║
║  PSAK / IFRS · Coretax DJP · SOX · OJK                       ║
╚══════════════════════════════════════════════════════════════╝
"""

EXCLUDED_DIRS: set[str] = {
    "__pycache__", ".git", ".venv", "venv", "env", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".eggs", "logs", "docs", "config_files",
    "deployment/ansible/inventory", "deployment/terraform",
    "deployment/helm/erp-accounting-engine/templates",
    "monitoring/grafana/dashboards", "monitoring/grafana/datasources",
    "monitoring/jaeger", "monitoring/loki", "monitoring/prometheus",
    "tests/fixtures", "migrations/versions/__pycache__",
    "migrations/__pycache__", "app/__pycache__",
}

DEFAULT_PACKAGE_DIRS: list[str] = [
    "constitution", "axioms", "bootstrap", "config", "kernel", "domain",
    "policy_engine", "compliance", "application", "ports", "adapters",
    "infrastructure", "audit", "projections", "reports", "event_gateway",
    "architecture", "deployment/scripts", "disaster_recovery",
    "security_hardening", "transformers", "tests", "app",
]

# -----------------------------------------------------------------------------
# CRITICAL_MODULES — DAFTAR LENGKAP (diperbaiki: pindahkan DI ke bootstrap)
# -----------------------------------------------------------------------------
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
    # ─── Dependency Container (BARU: pindah ke bootstrap) ───
    #("Bootstrap · DI · IoCContainer", "app.container"),
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
    # Entri lama untuk DI sudah dihapus dan diganti dengan yang baru di atas
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

# -----------------------------------------------------------------------------
# ENVIRONMENT & CRITICAL PATHS
# -----------------------------------------------------------------------------
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
    "constitution/supreme_law.py",
    "constitution/constitutional_invariants.py",
    "axioms/double_entry.py",
    "axioms/immutability.py",
    "axioms/conservation_of_value.py",
    "bootstrap/orchestrator.py",
    "config/loader_yaml.py",
    "config_files/application.yaml",
    "kernel/sealed_gate.py",
    "kernel/validation_pipeline.py",
    "kernel/guards/balance_checker.py",
    "kernel/guards/async_guards/fraud_pattern_detector.py",
    "kernel/immutable_laws/immutability_enforcer.py",
    "kernel/immutable_laws/gl_supremacy_enforcer.py",
    "domain/journal/aggregate_root.py",
    "domain/journal/invariants.py",
    "domain/reality/economic_event_immutable.py",
    "domain/intent/capture_service.py",
    "domain/causality/causal_chain_builder.py",
    "domain/shared_value_objects/money_vo.py",
    "domain/shared_value_objects/accounting_period_vo.py",
    "policy_engine/loader_yaml.py",
    "policy_engine/psak/psak_72_revenue.py",
    "policy_engine/psak/psak_73_leases.py",
    "policy_engine/ifrs/ifrs_15_revenue.py",
    "policy_engine/tax_indonesia/ppn_calculator.py",
    "policy_engine/tax_indonesia/pph_21_calculator.py",
    "compliance/psak_checker.py",
    "compliance/ifrs_checker.py",
    "compliance/legal/jurisdiction_definition.py",
    "compliance/ethics/error_classifier_psak25.py",
    "adapters/primary_api/common/app_factory.py",
    "application/use_cases/post_journal_entry.py",
    "application/use_cases/period_close.py",
    "application/commands_cqrs/command_bus_unified.py",
    "application/commands_cqrs/query_bus_unified.py",
    "application/sagas/procurement_saga.py",
    "application/sagas/payroll_saga.py",
    "application/sagas/coretax_submission_saga.py",
    "application/outbox/outbox_relay_service.py",
    "ports/primary/journal_repository_port.py",
    "ports/primary/unit_of_work_port.py",
    "ports/primary/event_publisher_port.py",
    "adapters/primary_api/common/fastapi_app_factory.py",
    "adapters/primary_api/v1/fastapi_journal_router.py",
    "adapters/coretax_djp/api_oauth2_client.py",
    "adapters/secondary_impl/sqlalchemy_journal_repository_impl.py",
    "infrastructure/database/session_factory_sqlalchemy.py",
    "infrastructure/database/transaction_manager.py",
    "infrastructure/event_store/append_only_store.py",
    "infrastructure/event_store/hash_chain_builder.py",
    "infrastructure/caching/redis_manager.py",
    "infrastructure/security/jwt_issuer.py",
    "infrastructure/security/rbac_enforcer_unified.py",
    "infrastructure/telemetry/prometheus_registry.py",
    "infrastructure/telemetry/opentelemetry_setup.py",
    "infrastructure/message_broker/kafka_producer_wrapper.py",
    "audit/event_writer_immutable.py",
    "audit/hash_chain_builder.py",
    "audit/forensic_replayer.py",
    "projections/ledger/general_ledger_table.py",
    "projections/ledger/trial_balance_cube.py",
    "event_gateway/event_gate_singleton.py",
    "event_gateway/event_deduplicator_idempotency.py",
    "asgi.py",
]

# -----------------------------------------------------------------------------
# DATA STRUCTURES
# -----------------------------------------------------------------------------
class CheckResult(NamedTuple):
    label: str
    module: str
    ok: bool
    error: str | None
    file: str | None = None
    line: int | None = None
    col: int | None = None
    error_type: str = "unknown"
    code_snippet: str | None = None


@dataclass
class SyntaxCheckResult:
    path: str
    ok: bool
    error: str | None = None
    line: int | None = None
    col: int | None = None
    code_snippet: str | None = None


@dataclass
class CircularImportResult:
    cycle: list[str]
    modules: list[str]


@dataclass
class ValidationSummary:
    import_errors: int = 0
    env_missing: int = 0
    path_missing: int = 0
    dep_missing: int = 0
    syntax_errors: int = 0
    circular_cycles: int = 0
    config_errors: list[str] = field(default_factory=list)
    infra_errors: list[str] = field(default_factory=list)
    orm_errors: list[str] = field(default_factory=list)
    asgi_ok: bool = False
    force_mode: bool = False
    import_details: list[CheckResult] = field(default_factory=list)
    syntax_details: list[SyntaxCheckResult] = field(default_factory=list)
    circular_details: list[CircularImportResult] = field(default_factory=list)

    @property
    def total_errors(self) -> int:
        return (
            self.import_errors + self.env_missing + self.path_missing +
            self.dep_missing + len(self.config_errors) + len(self.infra_errors) +
            self.syntax_errors + self.circular_cycles + len(self.orm_errors) +
            (0 if self.asgi_ok else 1)
        )

    @property
    def can_start(self) -> bool:
        critical = (
            self.import_errors > 0 or self.env_missing > 0 or
            len(self.config_errors) > 0 or not self.asgi_ok or
            self.syntax_errors > 0 or len(self.orm_errors) > 0
        )
        return self.force_mode if critical else True

# -----------------------------------------------------------------------------
# UTILITIES (ditingkatkan)
# -----------------------------------------------------------------------------
def _make_relative(file_path: str) -> str:
    try:
        return str(Path(file_path).relative_to(PROJECT_ROOT))
    except ValueError:
        return file_path


def _extract_error_context(exc: BaseException) -> tuple[str | None, int | None, int | None, str | None]:
    tb = exc.__traceback__
    if tb is None:
        return None, None, None, None
    while tb.tb_next:
        tb = tb.tb_next
    frame = tb.tb_frame
    filename = frame.f_code.co_filename
    lineno = tb.tb_lineno
    code_snippet = None
    try:
        with open(filename, encoding="utf-8") as f:
            lines = f.readlines()
            if 1 <= lineno <= len(lines):
                code_snippet = lines[lineno - 1].rstrip()
    except Exception:
        pass
    return filename, lineno, None, code_snippet


def classify_error(exc: BaseException) -> str:
    if isinstance(exc, SyntaxError):
        return "syntax"
    if isinstance(exc, ImportError):
        msg = str(exc).lower()
        if "circular" in msg or "partially initialized" in msg:
            return "circular"
        if "no module named" in msg:
            return "missing"
        return "import"
    return type(exc).__name__


def path_to_module(py_path: Path, root: Path) -> str | None:
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


def should_exclude_path(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    for part in rel.parts:
        if part in EXCLUDED_DIRS:
            return True
        if part.startswith("__pycache__") or part.startswith(".pytest_cache") or part.startswith(".mypy_cache") or part.startswith(".ruff_cache"):
            return True
    return False


def discover_all_python_modules(root: Path) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for py_file in root.glob("*.py"):
        if should_exclude_path(py_file, root):
            continue
        module = path_to_module(py_file, root)
        if module and module not in seen:
            seen.add(module)
            label = module.replace(".", " · ").replace("_", " ").title()
            results.append((label, module))
    for py_file in root.rglob("*.py"):
        if should_exclude_path(py_file, root):
            continue
        if py_file.parent == root:
            continue
        module = path_to_module(py_file, root)
        if module and module not in seen:
            seen.add(module)
            label = module.replace(".", " · ").replace("_", " ").title()
            results.append((label, module))
    return results


def get_imports_from_file(py_file: Path) -> list[str]:
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


# -----------------------------------------------------------------------------
# PHASE 0: SYNTAX CHECK
# -----------------------------------------------------------------------------
def run_syntax_check(
    root: Path,
    verbose: bool = False,
    quiet: bool = False,
) -> tuple[list[SyntaxCheckResult], int]:
    print("\n" + "─" * 64)
    print("  PHASE 0 — Syntax Check (AST scan seluruh file .py)")
    print("─" * 64)

    results: list[SyntaxCheckResult] = []
    errors = 0
    total = 0

    def check_file(py_file: Path) -> None:
        nonlocal total, errors
        if should_exclude_path(py_file, root):
            return
        total += 1
        rel = _make_relative(str(py_file))
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            ast.parse(source, filename=str(py_file))
            results.append(SyntaxCheckResult(path=str(py_file), ok=True))
            if verbose and not quiet:
                print(f"  ✅  {rel}")
        except SyntaxError as exc:
            errors += 1
            code_snippet = exc.text.rstrip() if exc.text else None
            results.append(
                SyntaxCheckResult(
                    path=str(py_file), ok=False,
                    error=exc.msg, line=exc.lineno, col=exc.offset,
                    code_snippet=code_snippet,
                )
            )
            print(f"  ❌  {rel}")
            print(f"       └─ SyntaxError: {exc.msg}")
            if exc.lineno:
                print(f"          📍 Baris {exc.lineno}, Kolom {exc.offset or '?'}")
            if code_snippet:
                print(f"          📝 Kode:  {code_snippet}")
                if exc.offset:
                    pointer = " " * (exc.offset - 1) + "^"
                    print(f"                  {pointer}")
        except Exception as exc:
            errors += 1
            results.append(SyntaxCheckResult(path=str(py_file), ok=False, error=str(exc)))
            print(f"  ❌  {rel}")
            print(f"       └─ {type(exc).__name__}: {exc}")

    for py_file in root.glob("*.py"):
        check_file(py_file)
    for py_file in root.rglob("*.py"):
        if py_file.parent == root:
            continue
        check_file(py_file)

    ok_count = total - errors
    print(f"\n  Hasil: {ok_count}/{total} file syntax OK | {errors} file bermasalah")
    if errors == 0:
        print("  ✅  Semua file .py syntax valid.")
    return results, errors


# -----------------------------------------------------------------------------
# PHASE 0b: CIRCULAR IMPORT
# -----------------------------------------------------------------------------
def run_circular_import_check(
    root: Path,
    verbose: bool = False,
    quiet: bool = False,
) -> tuple[list[CircularImportResult], int]:
    print("\n" + "─" * 64)
    print("  PHASE 0c — Circular Import Detection (static analysis)")
    print("─" * 64)

    import_graph: dict[str, set[str]] = defaultdict(set)
    module_files: dict[str, Path] = {}

    for py_file in root.rglob("*.py"):
        if should_exclude_path(py_file, root):
            continue
        module = path_to_module(py_file, root)
        if not module:
            continue
        module_files[module] = py_file
        imported = get_imports_from_file(py_file)
        for imp in imported:
            for known in module_files:
                if imp == known or imp.startswith(known + "."):
                    import_graph[module].add(imp)
                    break

    cycles: list[CircularImportResult] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in import_graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycle = [*path[cycle_start:], neighbor]
                cycle_key = " → ".join(sorted(cycle[:-1]))
                if not any(" → ".join(sorted(c.cycle[:-1])) == cycle_key for c in cycles):
                    cycles.append(CircularImportResult(cycle=cycle, modules=list(cycle)))
        path.pop()
        rec_stack.discard(node)

    all_modules = list(module_files.keys())
    for mod in all_modules:
        if mod not in visited:
            dfs(mod, [])

    if cycles:
        print(f"\n  ❌ Ditemukan {len(cycles)} circular import:\n")
        for i, result in enumerate(cycles, 1):
            chain = " → ".join(result.cycle)
            print(f"  [{i}] 🔄 {chain}")
    else:
        print(f"\n  ✅  Tidak ada circular import di {len(all_modules)} modul yang di-scan.")

    return cycles, len(cycles)


# -----------------------------------------------------------------------------
# PHASE 1: IMPORT SCAN (HARDENED)
# -----------------------------------------------------------------------------
def run_import_scan(
    modules: list[tuple[str, str]] | None = None,
    verbose: bool = False,
    show_traceback: bool = False,
    quiet: bool = False,
    stop_on_first: bool = False,
) -> tuple[list[CheckResult], int]:
    module_list = modules or CRITICAL_MODULES
    results: list[CheckResult] = []
    errors = 0
    failed_bases: set[str] = set()

    print("\n" + "─" * 64)
    print("  PHASE 1 — Import Scan (semua modul, semua error)")
    print("─" * 64)

    current_group = ""

    for label, module_path in module_list:
        group = label.split(" · ")[0] if " · " in label else label
        if group != current_group and verbose and not quiet:
            print(f"\n  ── {group} ──")
            current_group = group

        base_pkg = module_path.split(".")[0]
        parent_failed = any(module_path.startswith(fb + ".") for fb in failed_bases)
        if parent_failed and not verbose:
            continue

        try:
            __import__(module_path)
            results.append(CheckResult(label, module_path, True, None))
            if verbose and not quiet:
                print(f"  ✅  {label:<55}  [{module_path}]")
        except SyntaxError as exc:
            file_path = exc.filename
            line_no = exc.lineno
            col_no = exc.offset
            code_snippet = exc.text.rstrip() if exc.text else None
            err_msg = f"SyntaxError: {exc.msg}"
            results.append(
                CheckResult(label, module_path, False, err_msg,
                            file_path, line_no, col_no, "syntax", code_snippet)
            )
            errors += 1
            failed_bases.add(base_pkg)
            print(f"  ❌  [SYNTAX]   {label}")
            print(f"       └─ {err_msg}")
            if file_path:
                print(f"          📄 File: {_make_relative(file_path)}")
            if line_no:
                print(f"          📍 Baris: {line_no}")
            if code_snippet:
                print(f"          📝 Kode:  {code_snippet}")
                if col_no:
                    pointer = " " * (col_no - 1) + "^"
                    print(f"                  {pointer}")
            if show_traceback:
                traceback.print_exc()

        except ImportError as exc:
            file_path, line_no, col_no, code_snippet = _extract_error_context(exc)
            err_msg = str(exc)
            err_type = classify_error(exc)
            label_tag = {"circular": "[CIRCULAR]", "missing": "[MISSING]"}.get(err_type, "[IMPORT]")
            results.append(
                CheckResult(label, module_path, False, err_msg,
                            file_path, line_no, col_no, err_type, code_snippet)
            )
            errors += 1
            if err_type != "missing":
                failed_bases.add(base_pkg)
            print(f"  ❌  {label_tag:<12} {label}")
            print(f"       └─ {type(exc).__name__}: {err_msg}")
            if file_path:
                print(f"          📄 File: {_make_relative(file_path)}")
            if line_no:
                print(f"          📍 Baris: {line_no}")
            if code_snippet:
                print(f"          📝 Kode:  {code_snippet}")
            if show_traceback:
                traceback.print_exc()

        except Exception as exc:
            file_path, line_no, col_no, code_snippet = _extract_error_context(exc)
            err_type = classify_error(exc)
            err_msg = f"{type(exc).__name__}: {exc}"
            results.append(
                CheckResult(label, module_path, False, err_msg,
                            file_path, line_no, col_no, err_type, code_snippet)
            )
            errors += 1
            failed_bases.add(base_pkg)
            print(f"  ❌  [{err_type.upper()}]  {label}")
            print(f"       └─ {err_msg}")
            if file_path:
                print(f"          📄 File: {_make_relative(file_path)}")
            if line_no:
                print(f"          📍 Baris: {line_no}")
            if code_snippet:
                print(f"          📝 Kode:  {code_snippet}")
            if show_traceback:
                traceback.print_exc()

        if stop_on_first and errors > 0:
            print("\n  ⚠️  Stop-on-first-error aktif. Menghentikan scan.")
            break

    ok_count = len(results) - errors
    print(f"\n  Hasil: {ok_count}/{len(results)} modul berhasil diimport | {errors} error")
    if errors > 0:
        type_counts: dict[str, int] = defaultdict(int)
        for r in results:
            if not r.ok:
                type_counts[r.error_type] += 1
        breakdown = ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items()))
        print(f"  Error breakdown: {breakdown}")

    return results, errors


# -----------------------------------------------------------------------------
# PHASE 1b: AUTO-DISCOVERY
# -----------------------------------------------------------------------------
def run_auto_discovery_scan(
    verbose: bool = False,
    show_traceback: bool = False,
    quiet: bool = False,
) -> tuple[list[CheckResult], int]:
    print("\n" + "─" * 64)
    print("  PHASE 1b — Auto-Discovery Scan (semua file .py)")
    print("─" * 64)

    all_discovered = discover_all_python_modules(PROJECT_ROOT)
    critical_modules_set = {m for _, m in CRITICAL_MODULES}
    new_modules = [(l, m) for l, m in all_discovered if m not in critical_modules_set]

    print(f"  Ditemukan {len(all_discovered)} modul total")
    print(f"  {len(new_modules)} modul baru (belum di CRITICAL_MODULES)")
    print("  Scan dimulai...\n")

    return run_import_scan(
        modules=new_modules,
        verbose=verbose,
        show_traceback=show_traceback,
        quiet=quiet,
    )


# -----------------------------------------------------------------------------
# PHASE 2: ENVIRONMENT
# -----------------------------------------------------------------------------
def run_env_check(quiet: bool = False) -> int:
    print("\n" + "─" * 64)
    print("  PHASE 2 — Environment Variables")
    print("─" * 64)
    missing = 0

    print("\n  [WAJIB]")
    for var, example in REQUIRED_ENV_VARS:
        val = os.environ.get(var)
        if val:
            masked = val[:4] + "****" if len(val) > 4 else "****"
            if not quiet:
                print(f"  ✅  {var:<32}  = {masked}")
        else:
            print(f"  ❌  {var:<32}  — TIDAK ADA  (contoh: {example})")
            missing += 1

    print("\n  [OPSIONAL]")
    for var, example in OPTIONAL_ENV_VARS:
        val = os.environ.get(var)
        if val:
            masked = val[:4] + "****" if len(val) > 4 else "****"
            if not quiet:
                print(f"  ✅  {var:<32}  = {masked}")
        else:
            if not quiet:
                print(f"  ⚠️   {var:<32}  — tidak di-set  (contoh: {example})")

    if missing:
        print(f"\n  ❌  {missing} environment variable WAJIB belum di-set!")
    else:
        print(f"\n  ✅  Semua {len(REQUIRED_ENV_VARS)} env var wajib sudah di-set.")
    return missing


# -----------------------------------------------------------------------------
# PHASE 3: STRUCTURE
# -----------------------------------------------------------------------------
def run_structure_check(quiet: bool = False) -> int:
    print("\n" + "─" * 64)
    print("  PHASE 3 — Struktur Folder & File Kritis")
    print("─" * 64)
    missing = 0

    for rel_path in CRITICAL_PATHS:
        full_path = PROJECT_ROOT / rel_path
        if full_path.exists():
            if not quiet:
                print(f"  ✅  {rel_path}")
        else:
            print(f"  ❌  {rel_path}  — TIDAK ADA")
            missing += 1

    print("\n  [Cek __init__.py package kritis]")
    init_missing = 0
    for pkg_dir in DEFAULT_PACKAGE_DIRS:
        pkg_path = PROJECT_ROOT / pkg_dir
        if not pkg_path.exists():
            continue
        has_py = any(pkg_path.rglob("*.py"))
        if has_py and not (pkg_path / "__init__.py").exists():
            print(f"  ⚠️   __init__.py tidak ada di: {pkg_dir}")
            init_missing += 1

    if init_missing > 0:
        print(f"\n  ⚠️  {init_missing} folder kekurangan __init__.py (import akan gagal)")
    else:
        print("  ✅  Semua folder Python package memiliki __init__.py")

    if missing:
        print(f"\n  ❌  {missing} file/folder kritis TIDAK ADA.")
    else:
        print(f"\n  ✅  Semua {len(CRITICAL_PATHS)} path kritis ditemukan.")
    return missing


# -----------------------------------------------------------------------------
# PHASE 4: DEPENDENCIES
# -----------------------------------------------------------------------------
def run_dependency_check(quiet: bool = False) -> int:
    print("\n" + "─" * 64)
    print("  PHASE 4 — Dependency Python")
    print("─" * 64)
    packages = [
        ("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("sqlalchemy", "sqlalchemy"),
        ("alembic", "alembic"), ("asyncpg", "asyncpg"), ("psycopg2", "psycopg2"),
        ("pydantic", "pydantic"), ("redis", "redis"), ("kafka-python", "kafka"),
        ("python-jose", "jose"), ("cryptography", "cryptography"),
        ("prometheus-client", "prometheus_client"), ("opentelemetry-sdk", "opentelemetry"),
        ("pyyaml", "yaml"), ("structlog", "structlog"), ("httpx", "httpx"),
        ("passlib", "passlib"), ("python-multipart", "multipart"), ("orjson", "orjson"),
        ("aiofiles", "aiofiles"), ("celery", "celery"),
    ]
    missing = 0
    for pkg_name, import_name in packages:
        try:
            mod = __import__(import_name, fromlist=["__version__"])
            version = getattr(mod, "__version__", "?")
            if not quiet:
                print(f"  ✅  {pkg_name:<28}  v{version}")
        except ImportError:
            print(f"  ❌  {pkg_name:<28}  — TIDAK TERINSTALL (pip install {pkg_name})")
            missing += 1
    if missing:
        print(f"\n  ❌  {missing} package belum terinstall.")
    else:
        print(f"\n  ✅  Semua {len(packages)} dependency Python tersedia.")
    return missing


# -----------------------------------------------------------------------------
# PHASE 5: CONFIG YAML
# -----------------------------------------------------------------------------
def validate_configuration(show_traceback: bool, quiet: bool = False) -> list[str]:
    print("\n" + "─" * 64)
    print("  PHASE 5 — Validasi Konfigurasi YAML")
    print("─" * 64)
    errors: list[str] = []
    config_path = PROJECT_ROOT / "config_files" / "application.yaml"
    if not config_path.exists():
        msg = f"File konfigurasi utama tidak ditemukan: {config_path}"
        errors.append(msg)
        print(f"  ❌  {msg}")
        return errors
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            errors.append(f"Konfigurasi kosong: {config_path}")
        required_sections = ["database", "security", "redis", "application"]
        for section in required_sections:
            if data and section not in data:
                errors.append(f"Konfigurasi tidak memiliki section '{section}'")
    except ImportError:
        errors.append("PyYAML tidak terinstall")
    except Exception as e:
        errors.append(f"Error membaca {config_path}: {type(e).__name__}: {e}")
        if show_traceback:
            traceback.print_exc()

    other_yamls = [
        "config_files/constitution_invariants.yaml",
        "config_files/psak_standards_adopted.yaml",
        "config_files/coretax_djp_api_config.yaml",
    ]
    for yml_path in other_yamls:
        full = PROJECT_ROOT / yml_path
        if not full.exists():
            if not quiet:
                print(f"  ⚠️   {yml_path}  — tidak ditemukan (opsional)")
            continue
        try:
            import yaml
            with open(full, encoding="utf-8") as f:
                yaml.safe_load(f)
            if not quiet:
                print(f"  ✅  {yml_path}")
        except Exception as e:
            errors.append(f"YAML error {yml_path}: {e}")
            print(f"  ❌  {yml_path}: {e}")

    if not errors:
        print("\n  ✅  Semua konfigurasi YAML valid.")
    else:
        print(f"\n  ❌  {len(errors)} masalah konfigurasi ditemukan.")
        for err in errors:
            print(f"     • {err}")
    return errors


# -----------------------------------------------------------------------------
# PHASE 6: INFRASTRUCTURE (async)
# -----------------------------------------------------------------------------
async def check_database_connection() -> str | None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return "DATABASE_URL tidak diset"
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
        return f"Koneksi database gagal: {type(e).__name__}: {e}"


async def check_redis_connection() -> str | None:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return "REDIS_URL tidak diset"
    try:
        import redis.asyncio as redis_async
        r = redis_async.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        return None
    except ImportError:
        return "Modul redis tidak terinstall"
    except Exception as e:
        return f"Koneksi Redis gagal: {type(e).__name__}: {e}"


async def check_kafka_connection() -> str | None:
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
        return "Modul kafka-python tidak terinstall"
    except Exception as e:
        return f"Koneksi Kafka gagal: {type(e).__name__}: {e}"


async def run_infrastructure_checks(show_traceback: bool, quiet: bool = False) -> list[str]:
    errors: list[str] = []
    print("\n" + "─" * 64)
    print("  PHASE 6 — Koneksi Infrastruktur (DB · Redis · Kafka)")
    print("─" * 64)

    checks = [
        ("Database (PostgreSQL)", check_database_connection, True),
        ("Redis", check_redis_connection, True),
        ("Kafka", check_kafka_connection, False),
    ]

    for name, check_fn, is_critical in checks:
        print(f"  Memeriksa {name}... ", end="", flush=True)
        err = await check_fn()
        if err:
            tag = "❌ GAGAL (KRITIS)" if is_critical else "⚠️  GAGAL (opsional)"
            print(tag)
            print(f"       └─ {err}")
            errors.append(f"{name}: {err}")
        else:
            print("✅ OK")

    if not errors:
        print("\n  ✅  Semua koneksi infrastruktur berhasil.")
    return errors


# -----------------------------------------------------------------------------
# PHASE 7: ASGI
# -----------------------------------------------------------------------------
def validate_asgi_app(show_traceback: bool, quiet: bool = False) -> tuple[bool, list[str]]:
    print("\n" + "─" * 64)
    print("  PHASE 7 — Validasi ASGI App (asgi:app)")
    print("─" * 64)
    errors: list[str] = []
    try:
        asgi_module = __import__("asgi", fromlist=["app"])
        if not hasattr(asgi_module, "app"):
            err = "Modul asgi.py tidak memiliki atribut 'app'"
            errors.append(err)
            print(f"  ❌  {err}")
            return False, errors
        app = asgi_module.app
        app_type = type(app).__name__
        if not quiet:
            print(f"  ✅  asgi.py loaded — app type: {app_type}")
        return True, errors
    except SyntaxError as exc:
        err = f"SyntaxError di asgi.py: {exc.msg} (baris {exc.lineno})"
        errors.append(err)
        print(f"  ❌  {err}")
        if exc.text:
            print(f"       📝 Kode: {exc.text.rstrip()}")
        return False, errors
    except Exception as exc:
        file_path, line_no, _, code_snippet = _extract_error_context(exc)
        err = f"Error load asgi.py — {type(exc).__name__}: {exc}"
        errors.append(err)
        print(f"  ❌  {err}")
        if file_path:
            print(f"       📄 File: {_make_relative(file_path)}")
        if line_no:
            print(f"       📍 Baris: {line_no}")
        if code_snippet:
            print(f"       📝 Kode: {code_snippet}")
        if show_traceback:
            traceback.print_exc()
        return False, errors


# -----------------------------------------------------------------------------
# PHASE 8: ORM MAPPER VALIDATION (FIXED)
# -----------------------------------------------------------------------------
def validate_orm_mappers(show_traceback: bool, quiet: bool = False) -> list[str]:
    """Coba inisialisasi semua mapper SQLAlchemy untuk mendeteksi error mapping seperti NoForeignKeysError."""
    import asyncio
    import traceback

    from sqlalchemy import select

    print("\n" + "─" * 64)
    print("  PHASE 8 — Validasi ORM Mapper (SQLAlchemy)")
    print("─" * 64)
    errors: list[str] = []

    # Definisikan fungsi internal asinkron untuk menguji AsyncSession
    async def _test_async_mapping():
        from infrastructure.database.session_factory_sqlalchemy import get_session_factory_sync
        from infrastructure.persistence_orm import OutboxMessageTable

        # Dapatkan factory object, lalu ambil session maker
        factory = get_session_factory_sync()
        session_maker = factory.get_session_factory()
        if session_maker is None:
            raise Exception("Session factory not available")

        # WAJIB gunakan 'async with' karena session_maker menghasilkan AsyncSession
        async with session_maker() as session:
            # Gunakan syntax select standar SQLAlchemy 2.0 untuk AsyncSession
            stmt = select(OutboxMessageTable).limit(1)
            await session.execute(stmt)

    try:
        # Jalankan coroutine asinkron di dalam runner checker yang sinkron
        asyncio.run(_test_async_mapping())
        print("  ✅  Mapper SQLAlchemy berhasil diinisialisasi — tidak ada error relasi.")
    except ImportError as e:
        err = f"Gagal import ORM: {e}"
        errors.append(err)
        print(f"  ❌  {err}")
    except Exception as e:
        err = f"Error inisialisasi mapper: {type(e).__name__}: {e}"
        errors.append(err)
        print(f"  ❌  {err}")
        if show_traceback:
            traceback.print_exc()
        # Coba deteksi error NoForeignKeysError
        if "NoForeignKeysError" in str(e) or "Could not determine join condition" in str(e):
            print("     💡 Kemungkinan ada relasi ForeignKey yang hilang pada model SQLAlchemy.")
            print("     Periksa definisi relationship dan pastikan ada ForeignKey yang sesuai.")

    if not errors:
        print("\n  ✅  Semua mapper ORM valid.")
    else:
        print(f"\n  ❌  {len(errors)} masalah ORM ditemukan.")
        for err in errors:
            print(f"     • {err}")
    return errors

# -----------------------------------------------------------------------------
# SUMMARY & REPORT
# -----------------------------------------------------------------------------
def print_summary(summary: ValidationSummary, quiet: bool = False) -> None:
    print("\n" + "═" * 64)
    print("  RINGKASAN VALIDASI")
    print("═" * 64)

    rows = [
        ("Syntax Check", summary.syntax_errors),
        ("Circular Imports", summary.circular_cycles),
        ("Import Scan", summary.import_errors),
        ("Environment Vars", summary.env_missing),
        ("Struktur Folder", summary.path_missing),
        ("Dependency Python", summary.dep_missing),
        ("Konfigurasi YAML", len(summary.config_errors)),
        ("Infrastruktur", len(summary.infra_errors)),
        ("ORM Mapper", len(summary.orm_errors)),
        ("ASGI App", 0 if summary.asgi_ok else 1),
    ]
    for label, count in rows:
        if count == 0:
            status = "✅ OK"
        else:
            status = f"❌ {count} error"
        if not quiet or count > 0:
            print(f"  {label:<24}  {status}")

    total = summary.total_errors
    print("\n" + "─" * 64)

    # Detail errors
    if summary.import_details:
        failed = [r for r in summary.import_details if not r.ok]
        if failed:
            by_type: dict[str, list[CheckResult]] = defaultdict(list)
            for r in failed:
                by_type[r.error_type].append(r)
            print("\n  ─── Detail Import Errors ───")
            for err_type, items in sorted(by_type.items()):
                print(f"\n  [{err_type.upper()}] ({len(items)} modul)")
                for r in items:
                    print(f"    ❌  {r.label}")
                    if r.error:
                        print(f"         └─ {r.error}")
                    if r.file:
                        rel = _make_relative(r.file)
                        print(f"            📄 {rel}", end="")
                        if r.line:
                            print(f"  :{r.line}")
                        else:
                            print()
                    if r.code_snippet:
                        print(f"            📝 {r.code_snippet}")

    if summary.syntax_details:
        failed = [r for r in summary.syntax_details if not r.ok]
        if failed:
            print("\n  ─── Detail Syntax Errors ───")
            for r in failed:
                rel = _make_relative(r.path)
                print(f"    ❌  {rel}")
                if r.error:
                    msg = f"SyntaxError: {r.error}"
                    if r.line:
                        msg += f" (baris {r.line})"
                    print(f"         └─ {msg}")
                if r.code_snippet:
                    print(f"            📝 {r.code_snippet}")

    if summary.circular_details:
        print("\n  ─── Detail Circular Imports ───")
        for result in summary.circular_details:
            print(f"    🔄  {' → '.join(result.cycle)}")

    if summary.config_errors:
        print("\n  ─── Detail Error Konfigurasi ───")
        for err in summary.config_errors:
            print(f"    • {err}")

    if summary.infra_errors:
        print("\n  ─── Detail Error Infrastruktur ───")
        for err in summary.infra_errors:
            print(f"    • {err}")

    if summary.orm_errors:
        print("\n  ─── Detail Error ORM Mapper ───")
        for err in summary.orm_errors:
            print(f"    • {err}")

    print("\n" + "─" * 64)
    if total == 0:
        print("  ✅  SISTEM SIAP — Tidak ada error ditemukan.")
    else:
        critical = (
            summary.import_errors > 0 or summary.env_missing > 0 or
            len(summary.config_errors) > 0 or not summary.asgi_ok or
            summary.syntax_errors > 0 or len(summary.orm_errors) > 0
        )
        if critical and summary.force_mode:
            print(f"  ⚠️   {total} masalah ditemukan, --force aktif — tetap mencoba start.")
        elif critical:
            print(f"  ❌  {total} masalah KRITIS ditemukan. Server TIDAK akan start.")
            print("      Perbaiki error di atas terlebih dahulu.")
        else:
            print(f"  ⚠️   {total} masalah non-kritis. Gunakan --force untuk tetap start.")
    print("═" * 64)


def _save_error_report(summary: ValidationSummary) -> None:
    report_path = LOG_DIR / "check_errors.log"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("ERP Accounting Engine — Error Report (Hardened)\n")
        f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 64 + "\n\n")

        if summary.syntax_errors > 0:
            f.write(f"SYNTAX ERRORS ({summary.syntax_errors})\n")
            f.write("-" * 40 + "\n")
            for r in summary.syntax_details:
                if not r.ok:
                    f.write(f"  {r.path}\n")
                    if r.error:
                        f.write(f"    {r.error}")
                        if r.line:
                            f.write(f" (baris {r.line})")
                        f.write("\n")
                    if r.code_snippet:
                        f.write(f"    Kode: {r.code_snippet}\n")
            f.write("\n")

        if summary.circular_cycles > 0:
            f.write(f"CIRCULAR IMPORTS ({summary.circular_cycles})\n")
            f.write("-" * 40 + "\n")
            for c in summary.circular_details:
                f.write(f"  {' → '.join(c.cycle)}\n")
            f.write("\n")

        if summary.import_errors > 0:
            f.write(f"IMPORT ERRORS ({summary.import_errors})\n")
            f.write("-" * 40 + "\n")
            for r in summary.import_details:
                if not r.ok:
                    f.write(f"  [{r.error_type.upper()}] {r.label}\n")
                    if r.error:
                        f.write(f"    {r.error}\n")
                    if r.file:
                        f.write(f"    File: {r.file}")
                        if r.line:
                            f.write(f":{r.line}")
                        f.write("\n")
                    if r.code_snippet:
                        f.write(f"    Kode: {r.code_snippet}\n")
            f.write("\n")

        if summary.config_errors:
            f.write("CONFIG ERRORS\n")
            f.write("-" * 40 + "\n")
            for e in summary.config_errors:
                f.write(f"  {e}\n")
            f.write("\n")

        if summary.infra_errors:
            f.write("INFRA ERRORS\n")
            f.write("-" * 40 + "\n")
            for e in summary.infra_errors:
                f.write(f"  {e}\n")
            f.write("\n")

        if summary.orm_errors:
            f.write("ORM MAPPER ERRORS\n")
            f.write("-" * 40 + "\n")
            for e in summary.orm_errors:
                f.write(f"  {e}\n")


# -----------------------------------------------------------------------------
# SERVER STARTUP
# -----------------------------------------------------------------------------
def start_server(
    host: str,
    port: int,
    reload: bool,
    workers: int,
    log_level: str,
    show_traceback: bool,
    force: bool,
) -> None:
    try:
        import uvicorn
    except ImportError:
        logging.error("uvicorn tidak terinstall. Jalankan: pip install 'uvicorn[standard]'")
        sys.exit(1)

    print(BANNER)
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

    # Matikan logging dari uvicorn yang berlebihan (akses log tetap)
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(logging.ERROR if log_level.lower() != "debug" else logging.DEBUG)
    uvicorn_logger.propagate = True

    uvicorn_config: dict[str, Any] = {
        "app": "asgi:app",
        "host": host,
        "port": port,
        "log_level": log_level,
        "access_log": True,
    }
    if reload:
        uvicorn_config["reload"] = True
        uvicorn_config["reload_dirs"] = [str(PROJECT_ROOT)]
    elif workers > 1:
        uvicorn_config["workers"] = workers

    logging.info(f"Memulai {APP_NAME} v{APP_VERSION} ...")
    try:
        uvicorn.run(**uvicorn_config)
    except KeyboardInterrupt:
        logging.info("Server dihentikan oleh user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logging.error(f"❌ Server gagal: {type(e).__name__}: {e}")
        fp, ln, _, _ = _extract_error_context(e)
        if fp:
            logging.error(f"   📄 File: {_make_relative(fp)}")
        if ln:
            logging.error(f"   📍 Baris: {ln}")
        if show_traceback:
            traceback.print_exc()
        else:
            logging.error("   Gunakan --traceback untuk detail lengkap.")
        sys.exit(1)


# -----------------------------------------------------------------------------
# GLOBAL EXCEPTION HANDLER
# -----------------------------------------------------------------------------
def global_exception_handler(exc_type, exc_value, exc_traceback):
    logging.critical("❌ Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
    with open(LOG_DIR / "crash.log", "a", encoding="utf-8") as f:
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)


sys.excepthook = global_exception_handler


# -----------------------------------------------------------------------------
# CLI PARSER
# -----------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main_checker.py",
        description=textwrap.dedent(f"{APP_NAME} v{APP_VERSION}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="Health check (import + env + struktur).")
    parser.add_argument("--full-check", action="store_true", help="Full check termasuk koneksi DB/Redis/Kafka.")
    parser.add_argument("--deep-check", action="store_true", help="Deep check: syntax + circular + import SEMUA modul + semua fase.")
    parser.add_argument("--scan-all", action="store_true", help="Auto-discover & scan SEMUA modul .py (termasuk yang belum terdaftar).")
    parser.add_argument("--syntax-check", action="store_true", help="Cek syntax error semua file .py (tanpa import).")
    parser.add_argument("--circular-check", action="store_true", help="Deteksi circular imports dengan static analysis.")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail tiap modul (termasuk yang sukses).")
    parser.add_argument("--quiet", action="store_true", help="Hanya tampilkan error, sembunyikan sukses.")
    parser.add_argument("--traceback", action="store_true", help="Tampilkan traceback penuh untuk setiap error.")
    parser.add_argument("--skip-import", action="store_true", help="Lewati import scan (Phase 1).")
    parser.add_argument("--no-stop", action="store_true", help="Lanjutkan scan bahkan setelah error (default: lanjut semua).")
    parser.add_argument("--force", action="store_true", help="Paksa start server meskipun ada error non-kritis.")
    parser.add_argument("--host", default="127.0.0.1", help="Host bind server (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port server (default: 8000)")
    parser.add_argument("--workers", type=int, default=1, help="Jumlah worker uvicorn (default: 1)")
    parser.add_argument("--reload", action="store_true", help="Aktifkan auto-reload (development only)")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error", "critical"],
                        help="Level log uvicorn (default: info)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} v{APP_VERSION}")
    return parser


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    t_start = time.monotonic()

    # Set logging sesuai argumen
    configure_logging(verbose=args.verbose, quiet=args.quiet)

    summary = ValidationSummary(force_mode=args.force)

    is_check_mode = (
        args.check or args.full_check or args.deep_check or
        args.scan_all or args.syntax_check or args.circular_check
    )

    if is_check_mode:
        print(BANNER)
        mode_label = (
            "DEEP CHECK" if args.deep_check else
            "FULL CHECK" if args.full_check else
            "AUTO-DISCOVERY SCAN" if args.scan_all else
            "SYNTAX CHECK" if args.syntax_check else
            "CIRCULAR IMPORT CHECK" if args.circular_check else
            "HEALTH CHECK"
        )
        print(f"  MODE: {mode_label}  |  Project Root: {PROJECT_ROOT}")
        print()

        # PHASE 0
        if args.syntax_check or args.check or args.full_check or args.deep_check or args.scan_all:
            syntax_results, syntax_errors = run_syntax_check(PROJECT_ROOT, verbose=args.verbose, quiet=args.quiet)
            summary.syntax_errors = syntax_errors
            summary.syntax_details = syntax_results

        # PHASE 0c
        if args.circular_check or args.full_check or args.deep_check or args.scan_all:
            circular_results, circular_count = run_circular_import_check(PROJECT_ROOT, verbose=args.verbose, quiet=args.quiet)
            summary.circular_cycles = circular_count
            summary.circular_details = circular_results

        # PHASE 1
        if not args.skip_import and not args.syntax_check and not args.circular_check:
            if args.scan_all or args.deep_check:
                all_results, all_errors = run_import_scan(
                    modules=CRITICAL_MODULES,
                    verbose=args.verbose,
                    show_traceback=args.traceback,
                    quiet=args.quiet,
                )
                summary.import_errors = all_errors
                summary.import_details = all_results
                new_results, new_errors = run_auto_discovery_scan(
                    verbose=args.verbose,
                    show_traceback=args.traceback,
                    quiet=args.quiet,
                )
                summary.import_errors += new_errors
                summary.import_details += new_results
            else:
                import_results, import_errors = run_import_scan(
                    verbose=args.verbose,
                    show_traceback=args.traceback,
                    quiet=args.quiet,
                )
                summary.import_errors = import_errors
                summary.import_details = import_results
        elif args.skip_import:
            print("\n  [Import Scan] DILEWATI (--skip-import)")

        # PHASE 2–8 (jika bukan hanya syntax/circular)
        if not args.syntax_check and not args.circular_check:
            summary.env_missing = run_env_check(quiet=args.quiet)
            summary.path_missing = run_structure_check(quiet=args.quiet)
            summary.dep_missing = run_dependency_check(quiet=args.quiet)
            summary.config_errors = validate_configuration(show_traceback=args.traceback, quiet=args.quiet)

            if args.full_check or args.deep_check:
                summary.infra_errors = asyncio.run(
                    run_infrastructure_checks(show_traceback=args.traceback, quiet=args.quiet)
                )
            else:
                print("\n  [Infrastruktur] DILEWATI (gunakan --full-check atau --deep-check)")

            # ORM Mapper selalu di-check (kecuali --skip-import atau hanya syntax/circular)
            if not args.skip_import:
                summary.orm_errors = validate_orm_mappers(show_traceback=args.traceback, quiet=args.quiet)
            else:
                print("\n  [ORM Mapper] DILEWATI (--skip-import)")

            asgi_ok, _ = validate_asgi_app(show_traceback=args.traceback, quiet=args.quiet)
            summary.asgi_ok = asgi_ok

        # SUMMARY
        print_summary(summary, quiet=args.quiet)
        elapsed = time.monotonic() - t_start
        print(f"\n  ⏱️  Waktu check: {elapsed:.2f} detik")

        if summary.total_errors > 0:
            _save_error_report(summary)
            print("  📋  Error report disimpan di: logs/check_errors.log")

        sys.exit(0 if summary.total_errors == 0 else 1)

    # NORMAL MODE: Start Server
    print(BANNER)
    print("  Menjalankan pre-check sebelum start server ...\n")

    if not args.skip_import:
        import_results, import_errors = run_import_scan(
            verbose=False, show_traceback=args.traceback, quiet=args.quiet
        )
        summary.import_errors = import_errors
        summary.import_details = import_results
        if import_errors:
            logging.error(f"{import_errors} modul gagal diimport.")

    summary.env_missing = run_env_check(quiet=args.quiet)
    summary.config_errors = validate_configuration(show_traceback=args.traceback, quiet=args.quiet)
    # Check ORM mapper sebelum start
    summary.orm_errors = validate_orm_mappers(show_traceback=args.traceback, quiet=args.quiet)
    asgi_ok, _ = validate_asgi_app(show_traceback=args.traceback, quiet=args.quiet)
    summary.asgi_ok = asgi_ok

    if not summary.can_start:
        print_summary(summary, quiet=args.quiet)
        logging.error("❌ Server tidak dapat dimulai karena error kritis.")
        sys.exit(1)

    if summary.total_errors > 0 and not args.force:
        print_summary(summary, quiet=args.quiet)
        logging.warning("Ada peringatan non-kritis, server tetap dilanjutkan.")

    start_server(
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level=args.log_level,
        show_traceback=args.traceback,
        force=args.force,
    )


if __name__ == "__main__":
    main()