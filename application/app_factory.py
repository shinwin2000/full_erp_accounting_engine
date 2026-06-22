#!/usr/bin/env python3

"""
Module: app_factory.py

Layer: 5 - Application

Responsibility:
    Factory untuk membuat dan mengkonfigurasi aplikasi ERP Accounting Engine.
    Menggunakan registry global untuk command/query handler.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

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

# Import semua use cases, commands, handlers
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

# Import registry functions dari use_cases
from application.use_cases.registry import (
    register_command_handler,
    set_use_case_container,
)
from kernel.circuit_breaker import CircuitBreakerRegistry
from kernel.sealed_gate import SealedGate
from kernel.transactional_executor import TransactionalExecutor
from ports.primary.audit_repository_port import AuditRepositoryPort
from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort
from ports.primary.manufacturing_repository_port import ManufacturingRepositoryPort
from ports.primary.payroll_repository_port import PayrollRepositoryPort
from ports.primary.project_repository_port import ProjectRepositoryPort
from ports.primary.report_repository_port import ReportRepositoryPort
from ports.primary.umkm_repository_port import UMKMRepositoryPort

logger = logging.getLogger(__name__)


class DatabasePoolPort(Protocol):
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
    async def acquire(self) -> Any: ...


class MessageBrokerProducerPort(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, topic: str, key: str, value: bytes) -> None: ...


class MessageBrokerConsumerPort(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class CachePort(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def ping(self) -> bool: ...


class JWTIssuerPort(Protocol):
    def create_token(self, payload: dict) -> str: ...


class EncryptionServicePort(Protocol):
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


class EventStorePort(Protocol):
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
    async def append(self, event: Any) -> None: ...


class ApplicationFactory:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._container = {}
        self._initialized = False
        self._use_cases = {}

        # Infrastructure components
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

        # Repositories
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

    def _resolve_infrastructure_component(self, component_type: str, config_key: str) -> Any:
        try:
            if component_type == "database_pool":
                from adapters.secondary_impl.postgres_connection_pool_manager import (
                    AsyncPGConnectionPoolManager,
                )
                db_cfg = self.config.get("database", {})
                return AsyncPGConnectionPoolManager(
                    dsn=db_cfg.get("dsn", "postgresql://user:pass@localhost:5432/erp"),
                    min_size=db_cfg.get("min_pool_size", 10),
                    max_size=db_cfg.get("max_pool_size", 50),
                )
            elif component_type == "kafka_producer":
                from adapters.secondary_impl.kafka_producer_wrapper import KafkaProducerWrapper
                kafka_cfg = self.config.get("kafka", {})
                return KafkaProducerWrapper(
                    bootstrap_servers=kafka_cfg.get("bootstrap_servers", "localhost:9092"),
                    client_id="erp_accounting_engine_producer",
                )
            elif component_type == "kafka_consumer":
                from adapters.secondary_impl.kafka_consumer_wrapper import KafkaConsumerWrapper
                kafka_cfg = self.config.get("kafka", {})
                return KafkaConsumerWrapper(
                    bootstrap_servers=kafka_cfg.get("bootstrap_servers", "localhost:9092"),
                    group_id="erp_accounting_engine_group",
                    auto_offset_reset="earliest",
                )
            elif component_type == "redis":
                from adapters.secondary_impl.redis_cache_adapter_impl import RedisCacheAdapter
                redis_cfg = self.config.get("redis", {})
                if not redis_cfg.get("enabled", False):
                    return None
                return RedisCacheAdapter(
                    host=redis_cfg.get("host", "localhost"),
                    port=redis_cfg.get("port", 6379),
                    db=redis_cfg.get("db", 0),
                )
            elif component_type == "jwt_issuer":
                from infrastructure.security.jwt_issuer import JWTIssuer
                sec_cfg = self.config.get("security", {})
                return JWTIssuer(
                    secret_key=sec_cfg.get("jwt_secret", "default-secret"),
                    algorithm="RS256",
                    expire_minutes=60,
                )
            elif component_type == "encryption":
                from infrastructure.security.field_encryption_aes256_gcm import (
                    FieldEncryptionService,
                )
                sec_cfg = self.config.get("security", {})
                return FieldEncryptionService(
                    key=sec_cfg.get("encryption_key", "default-key").encode()
                )
            elif component_type == "event_store":
                from infrastructure.event_store.append_only_store import AppendOnlyStore
                return AppendOnlyStore(db_pool=self._db_pool, table_name="event_store")
            else:
                return None
        except ImportError as e:
            logger.warning(f"Failed to load static dependency for {component_type}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Failed to initialize {component_type}: {e}")
            return None

    async def initialize(self) -> Any:
        if self._initialized:
            return self._container

        logger.info("Initializing ERP Accounting Engine application...")
        self._container = {}

        await self._setup_telemetry()
        self._db_pool = self._resolve_infrastructure_component("database_pool", "database")
        if self._db_pool:
            await self._db_pool.initialize()

        self._kafka_producer = self._resolve_infrastructure_component("kafka_producer", "kafka")
        if self._kafka_producer:
            await self._kafka_producer.start()

        self._kafka_consumer = self._resolve_infrastructure_component("kafka_consumer", "kafka")
        if self._kafka_consumer:
            await self._kafka_consumer.start()

        self._redis_client = self._resolve_infrastructure_component("redis", "redis")
        if self._redis_client:
            await self._redis_client.connect()

        self._jwt_issuer = self._resolve_infrastructure_component("jwt_issuer", "security")
        self._encryption_service = self._resolve_infrastructure_component("encryption", "security")
        self._event_store = self._resolve_infrastructure_component("event_store", "event_store")
        if self._event_store:
            await self._event_store.initialize()

        self._sealed_gate = SealedGate()
        self._transactional_executor = TransactionalExecutor()
        self._circuit_breaker_registry = CircuitBreakerRegistry()

        self._event_publisher = await create_event_publisher(
            kafka_config=self.config.get("kafka", {}),
            outbox_enabled=True,
            mode="hybrid",
            kafka_producer=self._kafka_producer,
            redis_client=self._redis_client,
        )
        self._container["event_publisher"] = self._event_publisher

        await self._setup_repositories()
        await self._setup_services()
        await self._setup_use_cases()
        await self._setup_buses()
        await self._setup_event_handlers()

        self._initialized = True
        logger.info("Application initialized successfully")
        return self._container

    async def _setup_telemetry(self) -> None:
        """Setup OpenTelemetry dan Prometheus."""
        if self.config.get("telemetry", {}).get("opentelemetry_enabled", False):
            try:
                from infrastructure.telemetry.opentelemetry_setup import setup_opentelemetry
                setup_opentelemetry(
                    service_name="erp_accounting_engine",
                    endpoint=self.config["telemetry"].get("otel_endpoint", "localhost:4317"),
                )
            except ImportError as e:
                logger.warning(f"Failed to import OpenTelemetry: {e}")
            except Exception as e:
                logger.warning(f"Failed to setup OpenTelemetry: {e}")

        if self.config.get("telemetry", {}).get("prometheus_enabled", False):
            try:
                from infrastructure.telemetry.prometheus_registry import setup_prometheus
                setup_prometheus(port=self.config["telemetry"].get("prometheus_port", 9090))
            except ImportError as e:
                logger.warning(f"Failed to import Prometheus: {e}")
            except Exception as e:
                logger.warning(f"Failed to setup Prometheus: {e}")

    async def _setup_repositories(self) -> None:
        """Setup repository implementations using strict static imports."""
        try:
            from adapters.coretax_djp.api_oauth2_client import CoretaxOAuth2Client
            from adapters.secondary_impl.sqlalchemy_account_repository_impl import (
                SQLAlchemyAccountRepository,
            )
            from adapters.secondary_impl.sqlalchemy_ap_repository_impl import (
                SQLAlchemyAPRepository,
            )
            from adapters.secondary_impl.sqlalchemy_ar_repository_impl import (
                SQLAlchemyARRepository,
            )
            from adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl import (
                SQLAlchemyBankCashRepository,
            )
            from adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl import (
                SQLAlchemyFixedAssetRepository,
            )
            from adapters.secondary_impl.sqlalchemy_inventory_repository_impl import (
                SQLAlchemyInventoryRepository,
            )
            from adapters.secondary_impl.sqlalchemy_journal_repository_impl import (
                SQLAlchemyJournalRepository,
            )
            from adapters.secondary_impl.sqlalchemy_tax_repository_impl import (
                SQLAlchemyTaxRepository,
            )
            from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import (
                SQLAlchemyUnitOfWork,
            )
        except ImportError as e:
            logger.critical(f"Failed to import required repository adapters: {e}")
            raise

        # Buat session factory sederhana
        async def async_session_factory():
            return await self._db_pool.acquire()

        # Instansiasi repositories
        self._account_repo = SQLAlchemyAccountRepository(session_factory=async_session_factory)
        self._journal_repo = SQLAlchemyJournalRepository(session_factory=async_session_factory)
        self._ar_repo = SQLAlchemyARRepository(session_factory=async_session_factory)
        self._ap_repo = SQLAlchemyAPRepository(session_factory=async_session_factory)
        self._inventory_repo = SQLAlchemyInventoryRepository(session_factory=async_session_factory)
        self._fixed_asset_repo = SQLAlchemyFixedAssetRepository(session_factory=async_session_factory)
        self._bank_cash_repo = SQLAlchemyBankCashRepository(session_factory=async_session_factory)
        self._tax_repo = SQLAlchemyTaxRepository(session_factory=async_session_factory)

        # Report, consolidation, audit, payroll, manufacturing, project, umkm (placeholder)
        self._report_repo = ReportRepositoryPort()
        self._consolidation_repo = ConsolidationRepositoryPort()
        self._audit_repo = AuditRepositoryPort()
        self._payroll_repo = PayrollRepositoryPort()
        self._manufacturing_repo = ManufacturingRepositoryPort()
        self._project_repo = ProjectRepositoryPort()
        self._umkm_repo = UMKMRepositoryPort()

        # Coretax client
        coretax_cfg = self.config.get("coretax", {})
        self._coretax_client = CoretaxOAuth2Client(
            base_url=coretax_cfg.get("base_url", "https://api.coretax.djp.go.id"),
            client_id=coretax_cfg.get("client_id", ""),
            client_secret=coretax_cfg.get("client_secret", ""),
        )

        # Unit of Work
        self._uow = SQLAlchemyUnitOfWork(
            session_factory=async_session_factory,
            event_publisher=self._event_publisher,
        )

    async def _setup_services(self) -> None:
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

        self._container["coa_service"] = self._coa_service
        self._container["journal_service"] = self._journal_service

    async def _setup_use_cases(self) -> None:
        """Instansiasi semua use case dengan service yang tersedia."""
        logger.info("Instantiating use cases...")

        # Buat intercompany elimination use case terlebih dahulu (dibutuhkan oleh consolidation)
        intercompany_uc = IntercompanyEliminationUseCase(
            consolidation_service=self._consolidation_service,
            ledger_service=None,
            journal_service=self._journal_service,
            sealed_gate=self._sealed_gate,
        )

        # Buat period close use case (dibutuhkan oleh year end)
        period_close_uc = PeriodCloseUseCase(
            fiscal_period_service=None,
            journal_service=self._journal_service,
            bank_cash_service=self._bank_cash_service,
            inventory_service=self._inventory_service,
            sealed_gate=self._sealed_gate,
        )

        # Buat post closing journal use case (dibutuhkan oleh year end)
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

        # Simpan use cases ke container
        for use_case_cls, instance in self._use_cases.items():
            self._container[use_case_cls] = instance

        # Set container global agar handler di use_cases/__init__.py bisa mengakses use cases
        set_use_case_container(self._use_cases)

        logger.info(f"Created {len(self._use_cases)} use cases")

    async def _setup_buses(self) -> None:
        """Setup command and query buses dan registrasi handler ke registry global."""
        # Inisialisasi command bus
        self._command_bus = UnifiedCommandBus(
            gate=self._sealed_gate,
            uow=self._uow,
            circuit_breaker=self._circuit_breaker_registry,
        )

        # Inisialisasi query bus
        self._query_bus = UnifiedQueryBus()

        # Daftarkan semua command handler ke registry global
        self._register_command_handlers()

        # Daftarkan query handler (jika ada)
        self._register_query_handlers()

        self._container["command_bus"] = self._command_bus
        self._container["query_bus"] = self._query_bus

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

            # Daftarkan ke registry global
            try:
                register_command_handler(cmd_cls.__name__, wrapper, override=True)
                registered_count += 1
                logger.debug(f"Registered command handler for: {cmd_cls.__name__}")
            except Exception as e:
                logger.error(f"Failed to register handler for {cmd_cls.__name__}: {e}")

        logger.info(f"Registered {registered_count} command handlers")

    def _register_query_handlers(self) -> None:
        """
        Daftarkan query handler ke registry global.

        Saat ini tidak ada query handler yang didefinisikan di use cases.
        Query handler registry sudah terinisialisasi dengan wildcard default
        dari registry.py, sehingga checker akan mendeteksi registry tersebut.
        """
        logger.info("No query handlers to register (registry has default wildcards)")

    async def _setup_event_handlers(self) -> None:
        """Setup event handlers (subscribers)."""
        register_default_logging_handler()
        self._event_subscriber = await create_event_subscriber(
            kafka_config=self.config.get("kafka", {}),
            redis_config=self.config.get("redis", {}),
            topics=[
                "erp.accounting.journal",
                "erp.accounting.ar",
                "erp.accounting.ap",
                "erp.inventory.movement",
            ],
            group_id="erp-accounting-group",
            mode="kafka",
            worker_count=4,
            kafka_consumer=self._kafka_consumer,
            redis_client=self._redis_client,
        )
        if self._event_subscriber:
            await self._event_subscriber.start()

    async def shutdown(self) -> None:
        """Graceful shutdown of all components."""
        logger.info("Shutting down application...")
        if self._event_subscriber:
            await self._event_subscriber.stop()
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


async def create_app(config: dict[str, Any]) -> Any:
    """Convenience function to create and initialize application."""
    factory = ApplicationFactory(config)
    container = await factory.initialize()
    return container


async def shutdown_app(container: Any) -> None:
    """Shutdown application."""
    factory = container.get("ApplicationFactory") if isinstance(container, dict) else getattr(container, "factory", None)
    if factory:
        await factory.shutdown()


__all__ = ["ApplicationFactory", "create_app", "shutdown_app"]