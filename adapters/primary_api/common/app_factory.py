#!/usr/bin/env python3
"""
Module: app_factory.py
Layer: 5 - Application

Responsibility:
    Factory untuk membuat dan mengkonfigurasi aplikasi ERP Accounting Engine.
    Implementasi infrastruktur di-import secara lazy di dalam `initialize()` 
    untuk menghindari module parsing error pada saat bootstrap.
"""

from __future__ import annotations

import logging
from typing import Any

from ports.primary.audit_repository_port import AuditRepositoryPort
from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort
from ports.primary.manufacturing_repository_port import ManufacturingRepositoryPort
from ports.primary.payroll_repository_port import PayrollRepositoryPort
from ports.primary.project_repository_port import ProjectRepositoryPort
from ports.primary.report_repository_port import ReportRepositoryPort
from ports.primary.umkm_repository_port import UMKMRepositoryPort

logger = logging.getLogger(__name__)


class ApplicationFactory:
    """Factory untuk membuat aplikasi dengan dependency injection."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._initialized = False
        self._container: dict[str, Any] = {}

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
        self._event_subscriber = None
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
        self._command_bus = None
        self._query_bus = None

    async def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return self._container

        logger.info("Initializing ERP Accounting Engine application...")

        # LAZY IMPORTS: Dipindahkan ke sini agar tidak ter-scan saat load modul
        from adapters.coretax_djp.api_oauth2_client import CoretaxOAuth2Client
        from adapters.secondary_impl.kafka_consumer_wrapper import KafkaConsumerWrapper
        from adapters.secondary_impl.kafka_producer_wrapper import KafkaProducerWrapper
        from adapters.secondary_impl.postgres_connection_pool_manager import AsyncPGConnectionPoolManager
        from adapters.secondary_impl.redis_cache_adapter_impl import RedisCacheAdapter
        from adapters.secondary_impl.sqlalchemy_account_repository_impl import SQLAlchemyAccountRepository
        from adapters.secondary_impl.sqlalchemy_ap_repository_impl import SQLAlchemyAPRepository
        from adapters.secondary_impl.sqlalchemy_ar_repository_impl import SQLAlchemyARRepository
        from adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl import SQLAlchemyBankCashRepository
        from adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl import SQLAlchemyFixedAssetRepository
        from adapters.secondary_impl.sqlalchemy_inventory_repository_impl import SQLAlchemyInventoryRepository
        from adapters.secondary_impl.sqlalchemy_journal_repository_impl import SQLAlchemyJournalRepository
        from adapters.secondary_impl.sqlalchemy_tax_repository_impl import SQLAlchemyTaxRepository
        from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWork
        
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
        
        from infrastructure.event_store.append_only_store import AppendOnlyStore
        from infrastructure.security.field_encryption_aes256_gcm import FieldEncryptionService
        from infrastructure.security.jwt_issuer import JWTIssuer
        from kernel.circuit_breaker import CircuitBreakerRegistry
        from kernel.sealed_gate import SealedGate
        from kernel.transactional_executor import TransactionalExecutor

        # 1. Database pool
        db_cfg = self.config.get("database", {})
        self._db_pool = AsyncPGConnectionPoolManager(
            dsn=db_cfg["dsn"],
            min_size=db_cfg.get("min_pool_size", 10),
            max_size=db_cfg.get("max_pool_size", 50),
        )
        await self._db_pool.initialize()
        logger.info("Database pool initialized")

        # 2. Kafka producer & consumer
        kafka_cfg = self.config.get("kafka", {})
        self._kafka_producer = KafkaProducerWrapper(
            bootstrap_servers=kafka_cfg["bootstrap_servers"],
            client_id="erp_accounting_engine_producer",
        )
        await self._kafka_producer.start()
        logger.info("Kafka producer started")

        self._kafka_consumer = KafkaConsumerWrapper(
            bootstrap_servers=kafka_cfg["bootstrap_servers"],
            group_id="erp_accounting_engine_group",
            auto_offset_reset="earliest",
        )
        await self._kafka_consumer.start()
        logger.info("Kafka consumer started")

        # 3. Redis
        redis_cfg = self.config.get("redis", {})
        self._redis_client = RedisCacheAdapter(
            host=redis_cfg["host"],
            port=redis_cfg["port"],
            db=redis_cfg.get("db", 0),
        )
        await self._redis_client.connect()
        logger.info("Redis connected")

        # 4. Security components
        sec_cfg = self.config.get("security", {})
        self._jwt_issuer = JWTIssuer(
            secret_key=sec_cfg["jwt_secret"],
            algorithm="RS256",
            expire_minutes=60,
        )
        self._encryption_service = FieldEncryptionService(key=sec_cfg["encryption_key"].encode())
        logger.info("Security components initialized")

        # 5. Event store
        self._event_store = AppendOnlyStore(db_pool=self._db_pool, table_name="event_store")
        await self._event_store.initialize()
        logger.info("Event store initialized")

        # 6. Kernel components
        self._sealed_gate = SealedGate()
        self._transactional_executor = TransactionalExecutor()
        self._circuit_breaker_registry = CircuitBreakerRegistry()
        logger.info("Kernel components initialized")

        # 7. Event publisher
        self._event_publisher = await create_event_publisher(
            kafka_config=kafka_cfg,
            outbox_enabled=True,
            mode="hybrid",
            kafka_producer=self._kafka_producer,
            redis_client=self._redis_client,
        )
        logger.info("Event publisher created")

        # 8. Repositories
        async def session_factory():
            return await self._db_pool.acquire()

        self._account_repo = SQLAlchemyAccountRepository(session_factory=session_factory)
        self._journal_repo = SQLAlchemyJournalRepository(session_factory=session_factory)
        self._ar_repo = SQLAlchemyARRepository(session_factory=session_factory)
        self._ap_repo = SQLAlchemyAPRepository(session_factory=session_factory)
        self._inventory_repo = SQLAlchemyInventoryRepository(session_factory=session_factory)
        self._fixed_asset_repo = SQLAlchemyFixedAssetRepository(session_factory=session_factory)
        self._bank_cash_repo = SQLAlchemyBankCashRepository(session_factory=session_factory)
        self._tax_repo = SQLAlchemyTaxRepository(session_factory=session_factory)

        self._report_repo = ReportRepositoryPort()
        self._consolidation_repo = ConsolidationRepositoryPort()
        self._audit_repo = AuditRepositoryPort()
        self._payroll_repo = PayrollRepositoryPort()
        self._manufacturing_repo = ManufacturingRepositoryPort()
        self._project_repo = ProjectRepositoryPort()
        self._umkm_repo = UMKMRepositoryPort()

        coretax_cfg = self.config.get("coretax", {})
        self._coretax_client = CoretaxOAuth2Client(
            base_url=coretax_cfg["base_url"],
            client_id=coretax_cfg["client_id"],
            client_secret=coretax_cfg["client_secret"],
        )
        logger.info("Repositories initialized")

        # 9. Unit of Work
        self._uow = SQLAlchemyUnitOfWork(
            session_factory=session_factory,
            event_publisher=self._event_publisher,
        )

        # 10. Services
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
        logger.info("Services initialized")

        # 11. Command & Query buses
        self._command_bus = UnifiedCommandBus(
            gate=self._sealed_gate,
            uow=self._uow,
            circuit_breaker=self._circuit_breaker_registry,
        )
        self._query_bus = UnifiedQueryBus()
        logger.info("Buses initialized")

        # 12. Event subscriber
        self._event_subscriber = await create_event_subscriber(
            kafka_config=kafka_cfg,
            redis_config=redis_cfg,
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
        await self._event_subscriber.start()
        logger.info("Event subscriber started")

        # Register default logging handler
        register_default_logging_handler()

        # Populate container
        self._container.update(
            {
                "db_pool": self._db_pool,
                "kafka_producer": self._kafka_producer,
                "kafka_consumer": self._kafka_consumer,
                "redis_client": self._redis_client,
                "event_publisher": self._event_publisher,
                "event_subscriber": self._event_subscriber,
                "command_bus": self._command_bus,
                "query_bus": self._query_bus,
                "coa_service": self._coa_service,
                "journal_service": self._journal_service,
                "ar_service": self._ar_service,
                "ap_service": self._ap_service,
                "inventory_service": self._inventory_service,
                "fixed_asset_service": self._fixed_asset_service,
                "bank_cash_service": self._bank_cash_service,
                "tax_service": self._tax_service,
                "report_service": self._report_service,
                "consolidation_service": self._consolidation_service,
                "audit_service": self._audit_service,
                "payroll_service": self._payroll_service,
                "manufacturing_service": self._manufacturing_service,
                "project_service": self._project_service,
                "umkm_service": self._umkm_service,
                "coretax_service": self._coretax_service,
            }
        )

        self._initialized = True
        logger.info("Application fully initialized and ready")
        return self._container

    async def shutdown(self) -> None:
        logger.info("Shutting down application...")
        if self._event_subscriber:
            await self._event_subscriber.stop()
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self._redis_client:
            await self._redis_client.disconnect()
        if self._event_store:
            await self._event_store.close()
        if self._db_pool:
            await self._db_pool.close()
        logger.info("Application shutdown complete")


async def create_app(config: dict[str, Any]) -> dict[str, Any]:
    factory = ApplicationFactory(config)
    return await factory.initialize()


async def shutdown_app(container: dict[str, Any]) -> None:
    if "db_pool" in container:
        await container["db_pool"].close()
    if "kafka_producer" in container:
        await container["kafka_producer"].stop()
    logger.info("Shutdown via container completed")