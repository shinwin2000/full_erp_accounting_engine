#!/usr/bin/env python3
"""
Module: app_factory.py

Layer: 5 - Application

Responsibility:
    Factory untuk merakit aplikasi ERP Accounting Engine.
    Menerima semua dependensi infrastruktur dari Bootstrap melalui container,
    dan hanya bertanggung jawab untuk menyusun service layer, use cases,
    serta command/query buses.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

# Hanya import dari layer yang diizinkan: application, kernel, ports
from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
from application.commands_cqrs.query_bus_unified import UnifiedQueryBus
from application.events.handler_registry import register_default_logging_handler
from application.events.publisher_application import create_event_publisher
from application.events.subscriber_application import create_event_subscriber
from application.service_layer.service_ap import APService
from application.service_layer.service_ar import ARService
from application.service_layer.service_audit import AuditService
from application.service_layer.service_bank_cash import BankCashService
from application.service_layer.service_coa import COAService
from application.service_layer.service_consolidation import ConsolidationService
from application.service_layer.service_coretax import CoretaxService
from application.service_layer.service_fixed_asset import FixedAssetService
from application.service_layer.service_inventory import InventoryService
from application.service_layer.service_journal import JournalService
from application.service_layer.service_manufacturing import ManufacturingService
from application.service_layer.service_payroll import PayrollService
from application.service_layer.service_project import ProjectService
from application.service_layer.service_report import ReportService
from application.service_layer.service_tax import TaxService
from application.service_layer.service_umkm import UMKMService

# Import semua use cases, commands, dan handlers
from application.use_cases import (
    AMLScreeningCommand,
    AMLScreeningUseCase,
    APPaymentRunCommand,
    APPaymentRunUseCase,
    ApproveJournalCommand,
    ApproveJournalUseCase,
    ARCollectionWorkflowCommand,
    ARCollectionWorkflowUseCase,
    BankReconciliationCommand,
    BankReconciliationUseCase,
    BudgetVsActualCommand,
    BudgetVsActualUseCase,
    COGSCalculationCommand,
    COGSCalculationUseCase,
    ConsolidationGroupReportCommand,
    ConsolidationGroupReportUseCase,
    CoretaxBulkSubmissionCommand,
    CoretaxBulkSubmissionUseCase,
    DepreciationMonthlyRunCommand,
    DepreciationMonthlyRunUseCase,
    DisasterRecoveryReplayCommand,
    DisasterRecoveryReplayUseCase,
    FinancialStatementGenerationCommand,
    FinancialStatementGenerationUseCase,
    FiscalReconciliationCommand,
    FiscalReconciliationUseCase,
    ForexRevaluationCommand,
    ForexRevaluationUseCase,
    HedgeAccountingCommand,
    HedgeAccountingUseCase,
    HPPManufacturingCloseCommand,
    HPPManufacturingCloseUseCase,
    ImpairmentTestingCommand,
    ImpairmentTestingUseCase,
    IntercompanyEliminationCommand,
    IntercompanyEliminationUseCase,
    PayrollMonthlyRunCommand,
    PayrollMonthlyRunUseCase,
    PeriodCloseCommand,
    PeriodCloseUseCase,
    PeriodReopenWithAuditCommand,
    PeriodReopenWithAuditUseCase,
    PostAdjustingJournalCommand,
    PostAdjustingJournalUseCase,
    PostClosingJournalCommand,
    PostClosingJournalUseCase,
    PostJournalEntryCommand,
    PostJournalEntryUseCase,
    ReverseJournalCommand,
    ReverseJournalUseCase,
    StockOpnameCycleCommand,
    StockOpnameCycleUseCase,
    TaxFilingSubmissionCommand,
    TaxFilingSubmissionUseCase,
    YearEndClosingCommand,
    YearEndClosingUseCase,
    aml_screening_handler,
    ap_payment_run_handler,
    approve_journal_handler,
    ar_collection_workflow_handler,
    bank_reconciliation_handler,
    budget_vs_actual_handler,
    cogs_calculation_handler,
    consolidation_group_report_handler,
    coretax_bulk_submission_handler,
    depreciation_monthly_run_handler,
    disaster_recovery_replay_handler,
    financial_statement_generation_handler,
    fiscal_reconciliation_handler,
    forex_revaluation_handler,
    hedge_accounting_handler,
    hpp_manufacturing_close_handler,
    impairment_testing_handler,
    intercompany_elimination_handler,
    payroll_monthly_run_handler,
    period_close_handler,
    period_reopen_handler,
    post_adjusting_journal_handler,
    post_closing_journal_handler,
    post_journal_entry_handler,
    reverse_journal_handler,
    stock_opname_cycle_handler,
    tax_filing_submission_handler,
    year_end_closing_handler,
)
from application.use_cases.registry import (
    register_command_handler,
    set_use_case_container,
)
from kernel.circuit_breaker import CircuitBreakerRegistry
from kernel.sealed_gate import SealedGate
from kernel.transactional_executor import TransactionalExecutor

logger = logging.getLogger(__name__)


# ============================================================================
# Container Protocol (interface untuk dependency injection)
# ============================================================================
class ContainerProtocol(Protocol):
    """Interface minimal untuk container dependency injection."""
    def resolve(self, name: str, default: Any = None) -> Any:
        ...
    def get_registered_types(self) -> list[str]:
        ...
    def register_instance(self, key: str, instance: Any) -> None:
        ...
    def register_singleton(self, key: str, cls: type) -> None:
        ...


# Dummy container untuk fallback (jika tidak ada container diberikan)
class DummyContainer:
    def __init__(self):
        self._registry: dict[str, Any] = {}

    def resolve(self, name: str, default: Any = None) -> Any:
        return self._registry.get(name, default)

    def get_registered_types(self) -> list[str]:
        return list(self._registry.keys())

    def register_instance(self, key: str, instance: Any) -> None:
        self._registry[key] = instance

    def register_singleton(self, key: str, cls: type) -> None:
        self._registry[key] = cls()


# ============================================================================
# Application Factory
# ============================================================================
class ApplicationFactory:
    """
    Factory untuk merakit aplikasi.

    Semua dependensi infrastruktur (db pool, kafka, redis, dll.) harus diberikan
    melalui parameter container pada __init__. Container ini biasanya disediakan
    oleh lapisan Bootstrap.
    """

    def __init__(
        self,
        config: dict[str, Any],
        container: ContainerProtocol | None = None,
    ):
        """
        Args:
            config: Konfigurasi aplikasi (database, kafka, redis, dll.).
            container: Container dependency yang sudah berisi implementasi
                       dari semua port yang dibutuhkan. WAJIB diberikan.
        """
        self.config = config
        self._container_internal = {}  # dictionary internal untuk menyimpan komponen yang dirakit
        self._initialized = False
        self._use_cases = {}

        # Container harus diberikan; jika None, gunakan dummy container
        if container is not None:
            self._di_container = container
        else:
            self._di_container = DummyContainer()
            logger.warning("No container provided, using dummy container (some features may fail)")

        # Komponen infrastruktur (diambil dari container)
        self._db_pool = None
        self._kafka_producer = None
        self._kafka_consumer = None
        self._redis_client = None
        self._jwt_issuer = None
        self._encryption_service = None
        self._event_store = None
        self._sealed_gate = None
        self._transactional_executor = None
        self._circuit_breaker_registry = None

        # Repositories (dari container)
        self._account_repo = None
        self._journal_repo = None
        self._ar_repo = None
        self._ap_repo = None
        self._inventory_repo = None
        self._fixed_asset_repo = None
        self._bank_cash_repo = None
        self._tax_repo = None
        self._report_repo = None
        self._consolidation_repo = None
        self._audit_repo = None
        self._payroll_repo = None
        self._manufacturing_repo = None
        self._project_repo = None
        self._umkm_repo = None
        self._coretax_client = None
        self._uow = None
        self._event_publisher = None

        # Services
        self._coa_service = None
        self._journal_service = None
        self._ar_service = None
        self._ap_service = None
        self._inventory_service = None
        self._fixed_asset_service = None
        self._bank_cash_service = None
        self._tax_service = None
        self._report_service = None
        self._consolidation_service = None
        self._audit_service = None
        self._payroll_service = None
        self._manufacturing_service = None
        self._project_service = None
        self._umkm_service = None
        self._coretax_service = None

        # Buses
        self._command_bus = None
        self._query_bus = None
        self._event_subscriber = None

    async def initialize(self) -> dict[str, Any]:
        """Inisialisasi aplikasi: rakit semua komponen."""
        if self._initialized:
            return self._container_internal

        logger.info("Initializing ERP Accounting Engine application...")
        self._container_internal = {}

        # Ambil komponen infrastruktur dari container
        self._resolve_infrastructure()

        # Buat event publisher (menggunakan kafka_producer dan redis dari container)
        self._event_publisher = await self._create_event_publisher()
        self._container_internal["event_publisher"] = self._event_publisher

        # Ambil repositories dari container (sudah terdaftar di bootstrap)
        self._resolve_repositories()

        # Setup service layer
        self._setup_services()

        # Setup use cases
        self._setup_use_cases()

        # Setup buses dan registrasi handler
        self._setup_buses()

        # Setup event handlers (subscribers)
        await self._setup_event_handlers()

        self._initialized = True
        logger.info("Application initialized successfully")
        return self._container_internal

    def _resolve_infrastructure(self) -> None:
        """Ambil komponen infrastruktur dari container."""
        def resolve(name: str, default=None):
            return self._di_container.resolve(name) if hasattr(self._di_container, 'resolve') else default

        self._db_pool = resolve("database_pool")
        self._kafka_producer = resolve("kafka_producer")
        self._kafka_consumer = resolve("kafka_consumer")
        self._redis_client = resolve("redis_client")
        self._jwt_issuer = resolve("jwt_issuer")
        self._encryption_service = resolve("encryption_service")
        self._event_store = resolve("event_store")

        # Kernel components
        self._sealed_gate = SealedGate()
        self._transactional_executor = TransactionalExecutor()
        self._circuit_breaker_registry = CircuitBreakerRegistry()

        # Simpan di container internal untuk akses nanti
        self._container_internal["db_pool"] = self._db_pool
        self._container_internal["kafka_producer"] = self._kafka_producer
        self._container_internal["redis_client"] = self._redis_client
        self._container_internal["sealed_gate"] = self._sealed_gate
        self._container_internal["circuit_breaker_registry"] = self._circuit_breaker_registry

    async def _create_event_publisher(self):
        """Buat event publisher dengan komponen dari container."""
        outbox_repo = self._di_container.resolve("outbox_repository") if hasattr(self._di_container, 'resolve') else None

        return await create_event_publisher(
            message_broker=self._kafka_producer,
            outbox=outbox_repo,
            cache=self._redis_client,
            mode=self.config.get("event_publisher", {}).get("mode", "hybrid"),
            enable_circuit_breaker=True,
            enable_idempotency=True,
            max_retries=3,
            retry_delay_seconds=0.5,
        )

    def _resolve_repositories(self) -> None:
        """Ambil repository implementations dari container."""
        def resolve(name: str, default=None):
            return self._di_container.resolve(name) if hasattr(self._di_container, 'resolve') else default

        self._account_repo = resolve("account_repository")
        self._journal_repo = resolve("journal_repository")
        self._ar_repo = resolve("ar_repository")
        self._ap_repo = resolve("ap_repository")
        self._inventory_repo = resolve("inventory_repository")
        self._fixed_asset_repo = resolve("fixed_asset_repository")
        self._bank_cash_repo = resolve("bank_cash_repository")
        self._tax_repo = resolve("tax_repository")
        self._report_repo = resolve("report_repository")
        self._consolidation_repo = resolve("consolidation_repository")
        self._audit_repo = resolve("audit_repository")
        self._payroll_repo = resolve("payroll_repository")
        self._manufacturing_repo = resolve("manufacturing_repository")
        self._project_repo = resolve("project_repository")
        self._umkm_repo = resolve("umkm_repository")
        self._coretax_client = resolve("coretax_client")
        self._uow = resolve("unit_of_work")

        if self._uow is None:
            logger.warning("Unit of Work not found in container, using fallback")

    def _setup_services(self) -> None:
        """Setup service layer components."""
        self._coa_service = COAService(
            account_repository=self._account_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._journal_service = JournalService(
            journal_repo=self._journal_repo,
            ledger_repo=None,
            account_repo=self._account_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._ar_service = ARService(
            ar_repo=self._ar_repo,
            customer_repo=None,
            ledger_repo=None,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._ap_service = APService(
            ap_repo=self._ap_repo,
            supplier_repo=None,
            ledger_repo=None,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._inventory_service = InventoryService(
            inv_repo=self._inventory_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
            ledger_repo=None,
            valuation_method=self.config.get("inventory", {}).get("valuation_method", "FIFO"),
        )
        self._fixed_asset_service = FixedAssetService(
            asset_repo=self._fixed_asset_repo,
            ledger_repo=None,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._bank_cash_service = BankCashService(
            bank_repo=self._bank_cash_repo,
            ledger_repo=None,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._tax_service = TaxService(
            tax_repo=self._tax_repo,
            coretax_client=self._coretax_client,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._report_service = ReportService()
        self._consolidation_service = ConsolidationService(
            consolidation_repo=self._consolidation_repo,
            legal_entity_repo=None,
            ledger_repo=None,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._audit_service = AuditService(
            event_store=self._event_store,
            audit_repo=self._audit_repo,
        )
        self._payroll_service = PayrollService(
            payroll_repo=self._payroll_repo,
            employee_repo=None,
            ledger_repo=None,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._manufacturing_service = ManufacturingService(
            manufacturing_repo=self._manufacturing_repo,
            inventory_repo=self._inventory_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._project_service = ProjectService(
            project_repo=self._project_repo,
            ledger_repo=None,
            employee_repo=None,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._umkm_service = UMKMService(
            umkm_repo=self._umkm_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._coretax_service = CoretaxService(
            coretax_client=self._coretax_client,
            tax_repo=self._tax_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )

        # Simpan di container internal
        self._container_internal["coa_service"] = self._coa_service
        self._container_internal["journal_service"] = self._journal_service
        self._container_internal["ar_service"] = self._ar_service
        self._container_internal["ap_service"] = self._ap_service
        self._container_internal["inventory_service"] = self._inventory_service
        self._container_internal["fixed_asset_service"] = self._fixed_asset_service
        self._container_internal["bank_cash_service"] = self._bank_cash_service
        self._container_internal["tax_service"] = self._tax_service
        self._container_internal["report_service"] = self._report_service
        self._container_internal["consolidation_service"] = self._consolidation_service
        self._container_internal["audit_service"] = self._audit_service
        self._container_internal["payroll_service"] = self._payroll_service
        self._container_internal["manufacturing_service"] = self._manufacturing_service
        self._container_internal["project_service"] = self._project_service
        self._container_internal["umkm_service"] = self._umkm_service
        self._container_internal["coretax_service"] = self._coretax_service

    def _setup_use_cases(self) -> None:
        """Instansiasi semua use case dengan service yang tersedia."""
        logger.info("Instantiating use cases...")

        # Use cases yang membutuhkan dependensi silang
        intercompany_uc = IntercompanyEliminationUseCase(
            consolidation_service=self._consolidation_service,
            ledger_service=None,
            journal_service=self._journal_service,
            sealed_gate=self._sealed_gate,
        )

        period_close_uc = PeriodCloseUseCase(
            fiscal_period_service=None,
            journal_service=self._journal_service,
            bank_cash_service=self._bank_cash_service,
            inventory_service=self._inventory_service,
            sealed_gate=self._sealed_gate,
        )

        post_closing_uc = PostClosingJournalUseCase(
            journal_service=self._journal_service,
            fiscal_period_service=None,
            coa_service=self._coa_service,
            ledger_repo=None,
            sealed_gate=self._sealed_gate,
        )

        self._use_cases = {
            AMLScreeningUseCase: AMLScreeningUseCase(
                aml_repo=None,
                audit_service=self._audit_service,
                iam_service=None,
                sealed_gate=self._sealed_gate,
            ),
            APPaymentRunUseCase: APPaymentRunUseCase(
                ap_service=self._ap_service,
                bank_cash_service=self._bank_cash_service,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            ApproveJournalUseCase: ApproveJournalUseCase(
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            ARCollectionWorkflowUseCase: ARCollectionWorkflowUseCase(
                ar_service=self._ar_service,
                bank_cash_service=self._bank_cash_service,
                sealed_gate=self._sealed_gate,
            ),
            BankReconciliationUseCase: BankReconciliationUseCase(
                bank_cash_service=self._bank_cash_service,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            BudgetVsActualUseCase: BudgetVsActualUseCase(
                budget_service=None,
                ledger_service=None,
                report_service=self._report_service,
                sealed_gate=self._sealed_gate,
            ),
            COGSCalculationUseCase: COGSCalculationUseCase(
                inventory_service=self._inventory_service,
                journal_service=self._journal_service,
                manufacturing_service=self._manufacturing_service,
                sealed_gate=self._sealed_gate,
            ),
            ConsolidationGroupReportUseCase: ConsolidationGroupReportUseCase(
                consolidation_service=self._consolidation_service,
                report_service=self._report_service,
                ledger_service=None,
                intercompany_elimination_uc=intercompany_uc,
                sealed_gate=self._sealed_gate,
            ),
            CoretaxBulkSubmissionUseCase: CoretaxBulkSubmissionUseCase(
                coretax_service=self._coretax_service,
                tax_service=self._tax_service,
                sealed_gate=self._sealed_gate,
            ),
            DepreciationMonthlyRunUseCase: DepreciationMonthlyRunUseCase(
                fixed_asset_service=self._fixed_asset_service,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            DisasterRecoveryReplayUseCase: DisasterRecoveryReplayUseCase(
                event_store=self._event_store,
                tamper_scanner=None,
                event_publisher=self._event_publisher,
            ),
            FinancialStatementGenerationUseCase: FinancialStatementGenerationUseCase(
                report_service=self._report_service,
                coa_service=self._coa_service,
                consolidation_service=self._consolidation_service,
                sealed_gate=self._sealed_gate,
            ),
            FiscalReconciliationUseCase: FiscalReconciliationUseCase(
                tax_service=self._tax_service,
                ledger_service=None,
                report_service=self._report_service,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            ForexRevaluationUseCase: ForexRevaluationUseCase(
                forex_service=None,
                ledger_service=None,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            HedgeAccountingUseCase: HedgeAccountingUseCase(
                hedge_service=None,
                ledger_service=None,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            HPPManufacturingCloseUseCase: HPPManufacturingCloseUseCase(
                manufacturing_service=self._manufacturing_service,
                inventory_service=self._inventory_service,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            ImpairmentTestingUseCase: ImpairmentTestingUseCase(
                fixed_asset_service=self._fixed_asset_service,
                intangible_asset_service=None,
                goodwill_service=None,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            IntercompanyEliminationUseCase: intercompany_uc,
            PayrollMonthlyRunUseCase: PayrollMonthlyRunUseCase(
                payroll_service=self._payroll_service,
                journal_service=self._journal_service,
                bank_cash_service=self._bank_cash_service,
                sealed_gate=self._sealed_gate,
            ),
            PeriodCloseUseCase: period_close_uc,
            PeriodReopenWithAuditUseCase: PeriodReopenWithAuditUseCase(
                fiscal_period_service=None,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            PostAdjustingJournalUseCase: PostAdjustingJournalUseCase(
                journal_service=self._journal_service,
                fiscal_period_service=None,
                sealed_gate=self._sealed_gate,
            ),
            PostClosingJournalUseCase: post_closing_uc,
            PostJournalEntryUseCase: PostJournalEntryUseCase(
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
                audit_hook=None,
            ),
            ReverseJournalUseCase: ReverseJournalUseCase(
                journal_service=self._journal_service,
                fiscal_period_service=None,
                sealed_gate=self._sealed_gate,
            ),
            StockOpnameCycleUseCase: StockOpnameCycleUseCase(
                inventory_service=self._inventory_service,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
            TaxFilingSubmissionUseCase: TaxFilingSubmissionUseCase(
                coretax_service=self._coretax_service,
                tax_service=self._tax_service,
                sealed_gate=self._sealed_gate,
            ),
            YearEndClosingUseCase: YearEndClosingUseCase(
                period_close_uc=period_close_uc,
                post_closing_uc=post_closing_uc,
                fiscal_period_service=None,
                tax_service=self._tax_service,
                fixed_asset_service=self._fixed_asset_service,
                journal_service=self._journal_service,
                sealed_gate=self._sealed_gate,
            ),
        }

        # Simpan use cases ke container internal
        for use_case_cls, instance in self._use_cases.items():
            self._container_internal[use_case_cls] = instance

        # Set container global agar handler di use_cases/__init__.py bisa mengakses use cases
        set_use_case_container(self._use_cases)

        logger.info(f"Created {len(self._use_cases)} use cases")

    def _setup_buses(self) -> None:
        """Setup command and query buses dan registrasi handler ke registry global."""
        self._command_bus = UnifiedCommandBus(
            gate=self._sealed_gate,
            uow=self._uow,
            circuit_breaker=self._circuit_breaker_registry,
        )

        self._query_bus = UnifiedQueryBus()

        self._register_command_handlers()
        self._register_query_handlers()

        self._container_internal["command_bus"] = self._command_bus
        self._container_internal["query_bus"] = self._query_bus

    def _register_command_handlers(self) -> None:
        """Daftarkan semua command handler ke registry global."""
        command_map = [
            (AMLScreeningCommand, aml_screening_handler, AMLScreeningUseCase),
            (APPaymentRunCommand, ap_payment_run_handler, APPaymentRunUseCase),
            (ApproveJournalCommand, approve_journal_handler, ApproveJournalUseCase),
            (ARCollectionWorkflowCommand, ar_collection_workflow_handler, ARCollectionWorkflowUseCase),
            (BankReconciliationCommand, bank_reconciliation_handler, BankReconciliationUseCase),
            (BudgetVsActualCommand, budget_vs_actual_handler, BudgetVsActualUseCase),
            (COGSCalculationCommand, cogs_calculation_handler, COGSCalculationUseCase),
            (ConsolidationGroupReportCommand, consolidation_group_report_handler, ConsolidationGroupReportUseCase),
            (CoretaxBulkSubmissionCommand, coretax_bulk_submission_handler, CoretaxBulkSubmissionUseCase),
            (DepreciationMonthlyRunCommand, depreciation_monthly_run_handler, DepreciationMonthlyRunUseCase),
            (DisasterRecoveryReplayCommand, disaster_recovery_replay_handler, DisasterRecoveryReplayUseCase),
            (FinancialStatementGenerationCommand, financial_statement_generation_handler, FinancialStatementGenerationUseCase),
            (FiscalReconciliationCommand, fiscal_reconciliation_handler, FiscalReconciliationUseCase),
            (ForexRevaluationCommand, forex_revaluation_handler, ForexRevaluationUseCase),
            (HedgeAccountingCommand, hedge_accounting_handler, HedgeAccountingUseCase),
            (HPPManufacturingCloseCommand, hpp_manufacturing_close_handler, HPPManufacturingCloseUseCase),
            (ImpairmentTestingCommand, impairment_testing_handler, ImpairmentTestingUseCase),
            (IntercompanyEliminationCommand, intercompany_elimination_handler, IntercompanyEliminationUseCase),
            (PayrollMonthlyRunCommand, payroll_monthly_run_handler, PayrollMonthlyRunUseCase),
            (PeriodCloseCommand, period_close_handler, PeriodCloseUseCase),
            (PeriodReopenWithAuditCommand, period_reopen_handler, PeriodReopenWithAuditUseCase),
            (PostAdjustingJournalCommand, post_adjusting_journal_handler, PostAdjustingJournalUseCase),
            (PostClosingJournalCommand, post_closing_journal_handler, PostClosingJournalUseCase),
            (PostJournalEntryCommand, post_journal_entry_handler, PostJournalEntryUseCase),
            (ReverseJournalCommand, reverse_journal_handler, ReverseJournalUseCase),
            (StockOpnameCycleCommand, stock_opname_cycle_handler, StockOpnameCycleUseCase),
            (TaxFilingSubmissionCommand, tax_filing_submission_handler, TaxFilingSubmissionUseCase),
            (YearEndClosingCommand, year_end_closing_handler, YearEndClosingUseCase),
        ]

        registered_count = 0
        for cmd_cls, handler, use_case_cls in command_map:
            use_case = self._use_cases.get(use_case_cls)
            if use_case is None:
                logger.warning(
                    f"Use case instance not found for {use_case_cls.__name__}, "
                    f"skipping handler for {cmd_cls.__name__}"
                )
                continue

            # Buat wrapper yang memanggil handler dengan command dan use_case
            async def wrapper(cmd, uc=use_case, h=handler):
                return await h(cmd, uc)

            try:
                register_command_handler(cmd_cls.__name__, wrapper, override=True)
                registered_count += 1
                logger.debug(f"Registered command handler for: {cmd_cls.__name__}")
            except Exception as e:
                logger.error(f"Failed to register handler for {cmd_cls.__name__}: {e}")

        logger.info(f"Registered {registered_count} command handlers")

    def _register_query_handlers(self) -> None:
        """Daftarkan query handler jika ada."""
        logger.info("No query handlers to register (registry has default wildcards)")

    async def _setup_event_handlers(self) -> None:
        """Setup event handlers (subscribers)."""
        # Registrasi default logging handler (tidak bergantung infrastruktur)
        register_default_logging_handler()

        # Buat event subscriber hanya jika kafka_consumer tersedia
        if self._kafka_consumer is not None:
            dead_letter_store = self._di_container.resolve("dead_letter_store") if hasattr(self._di_container, 'resolve') else None
            metrics = self._di_container.resolve("metrics_reporter") if hasattr(self._di_container, 'resolve') else None

            self._event_subscriber = await create_event_subscriber(
                kafka_consumer=self._kafka_consumer,
                redis_client=self._redis_client,
                dead_letter_store=dead_letter_store,
                metrics=metrics,
                topics=self.config.get("kafka", {}).get("topics", [
                    "erp.accounting.journal",
                    "erp.accounting.ar",
                    "erp.accounting.ap",
                    "erp.inventory.movement",
                ]),
                group_id=self.config.get("kafka", {}).get("group_id", "erp-accounting-group"),
                mode=self.config.get("event_subscriber", {}).get("mode", "kafka"),
                worker_count=self.config.get("event_subscriber", {}).get("worker_count", 4),
            )
            if self._event_subscriber:
                await self._event_subscriber.start()
                self._container_internal["event_subscriber"] = self._event_subscriber

    async def shutdown(self) -> None:
        """Graceful shutdown of all components."""
        logger.info("Shutting down application...")
        if self._event_subscriber:
            await self._event_subscriber.stop()
        if self._event_publisher:
            # publisher mungkin memiliki resources yang perlu ditutup
            pass
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self._redis_client:
            await self._redis_client.disconnect()
        if self._db_pool:
            await self._db_pool.close()
        if self._event_store:
            await self._event_store.close()
        logger.info("Application shutdown complete")


async def create_app(
    config: dict[str, Any],
    container: ContainerProtocol | None = None,
) -> dict[str, Any]:
    """
    Convenience function untuk membuat dan menginisialisasi aplikasi.

    Args:
        config: Konfigurasi aplikasi.
        container: Container dependency (wajib diberikan, karena application tidak boleh
                   mengimpor bootstrap secara langsung).

    Returns:
        Dictionary berisi semua komponen yang terdaftar.
    """
    factory = ApplicationFactory(config, container)
    return await factory.initialize()


async def shutdown_app(container: dict[str, Any]) -> None:
    """
    Shutdown aplikasi.

    Args:
        container: Dictionary hasil dari create_app().
    """
    # Cari factory di dalam container
    factory = container.get("ApplicationFactory")
    if factory is None:
        # Mungkin factory tidak disimpan, coba cari dengan nama kelas
        for key, val in container.items():
            if isinstance(val, ApplicationFactory):
                factory = val
                break
    if factory:
        await factory.shutdown()


__all__ = ["ApplicationFactory", "create_app", "shutdown_app"]
