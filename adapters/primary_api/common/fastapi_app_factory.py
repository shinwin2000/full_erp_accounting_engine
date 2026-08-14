#!/usr/bin/env python3
"""
Module: app_factory.py
Layer: 5 - Application

Responsibility:
    Factory untuk membuat dan mengkonfigurasi aplikasi ERP Accounting Engine.
    Menggunakan repository konkret yang sudah diimplementasikan.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import os
import urllib.parse
from pathlib import Path
from typing import Any

import aiofiles  # <-- Tambahan untuk async file I/O
import yaml

logger = logging.getLogger(__name__)


def _import_class(module_name: str, class_names: list[str]) -> Any | None:
    """Mencoba mengimpor kelas dari modul dengan beberapa kemungkinan nama."""
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        logger.warning(f"Module {module_name} not found: {e}")
        return None

    for name in class_names:
        cls = getattr(module, name, None)
        if cls is not None:
            logger.info(f"Imported {name} from {module_name}")
            return cls
    logger.warning(f"None of {class_names} found in {module_name}")
    return None


def _make_stub(port_cls):
    """Membuat stub untuk abstract base class (fallback)."""
    def _not_implemented(self, *args, **kwargs):
        raise NotImplementedError(f"{port_cls.__name__} belum diimplementasikan.")
    abstract_methods = getattr(port_cls, "__abstractmethods__", frozenset())
    namespace = dict.fromkeys(abstract_methods, _not_implemented)
    stub_cls = type(f"_Stub{port_cls.__name__}", (port_cls,), namespace)
    return stub_cls()


def _make_generic_stub(port_name):
    """Membuat generic stub jika port tidak ditemukan."""
    class DummyStub:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                raise NotImplementedError(f"{port_name} belum punya implementasi konkret.")
            return method
    return DummyStub()


class ApplicationFactory:
    """Factory untuk membuat aplikasi dengan dependency injection."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._initialized = False
        self._container: dict[str, Any] = {}

        # Komponen
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
        self._ledger_repo = None
        self._report_repo = None
        self._consolidation_repo = None
        self._audit_repo = None
        self._payroll_repo = None
        self._manufacturing_repo = None
        self._project_repo = None
        self._umkm_repo = None
        self._employee_repo = None
        self._customer_repo = None
        self._supplier_repo = None
        self._legal_entity_repo = None

        self._coretax_client = None
        self._uow = None
        self._event_publisher = None
        self._event_subscriber = None

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

        self._command_bus = None
        self._query_bus = None

    async def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return self._container

        logger.info("Initializing ERP Accounting Engine application...")

        # ========== LAZY IMPORTS ==========
        from adapters.coretax_djp.api_oauth2_client import CoretaxOAuth2Client
        from adapters.secondary_impl.kafka_consumer_wrapper import KafkaConsumerWrapper
        from adapters.secondary_impl.kafka_producer_wrapper import KafkaProducerWrapper
        from adapters.secondary_impl.postgres_connection_pool_manager import (
            AsyncPGConnectionPoolManager,
        )
        from adapters.secondary_impl.redis_cache_adapter_impl import RedisCacheAdapter
        from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWork
        from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
        from application.commands_cqrs.query_bus_unified import UnifiedQueryBus
        from application.events.handler_registry import register_default_logging_handler
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

        # ========== 1. Database ==========
        db_cfg = self.config.get("database", {})
        dsn = db_cfg.get("dsn")
        if not dsn:
            raise ValueError("Database DSN is required")
        self._db_pool = AsyncPGConnectionPoolManager(
            dsn=dsn,
            min_size=db_cfg.get("min_pool_size", 10),
            max_size=db_cfg.get("max_pool_size", 50),
        )
        await self._db_pool.initialize()
        logger.info("Database pool initialized")

        # ========== 2. Kafka ==========
        kafka_cfg = self.config.get("kafka", {})
        kafka_bootstrap = kafka_cfg.get("bootstrap_servers") or os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
        if kafka_bootstrap:
            try:
                self._kafka_producer = KafkaProducerWrapper(
                    bootstrap_servers=kafka_bootstrap,
                    client_id="erp_accounting_engine_producer",
                )
                await self._kafka_producer.start()
                logger.info("Kafka producer started")

                self._kafka_consumer = KafkaConsumerWrapper(
                    bootstrap_servers=kafka_bootstrap,
                    group_id="erp_accounting_engine_group",
                    auto_offset_reset="earliest",
                )
                await self._kafka_consumer.start()
                logger.info("Kafka consumer started")
            except Exception as e:
                logger.warning(f"Kafka initialization failed: {e}. Running in degraded mode.")
                if self._kafka_producer is not None:
                    with contextlib.suppress(Exception):
                        await self._kafka_producer.stop()
                    self._kafka_producer = None
                self._kafka_consumer = None
        else:
            logger.info("Kafka bootstrap servers not configured. Running without Kafka.")

        # ========== 3. Redis ==========
        redis_cfg = self.config.get("redis", {})
        redis_url = redis_cfg.get("url") or os.environ.get("REDIS_URL")
        if redis_url:
            try:
                # Parse URL
                parsed = urllib.parse.urlparse(redis_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 6379
                db = int(parsed.path[1:]) if parsed.path and parsed.path[1:].isdigit() else 0
                password = parsed.password or None
                self._redis_client = RedisCacheAdapter(
                    host=host,
                    port=port,
                    db=db,
                    password=password,
                )
                await self._redis_client.connect()
                logger.info("Redis connected")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Running without Redis.")
                self._redis_client = None
        else:
            logger.info("Redis not configured. Running without Redis.")

        # ========== 4. Security ==========
        # Load JWT config dari file YAML secara async
        try:
            jwt_config_path = Path("config_files/security_tls_jwt_mfa.yaml")
            if jwt_config_path.exists():
                # ===== PERBAIKAN: Baca file secara async dengan aiofiles =====
                async with aiofiles.open(jwt_config_path, encoding="utf-8") as f:
                    content = await f.read()
                # Parse YAML di thread pool (blocking)
                raw_config = await asyncio.to_thread(yaml.safe_load, content)
                # Coba dengan config_path
                try:
                    self._jwt_issuer = JWTIssuer(config_path=str(jwt_config_path))
                    logger.info("JWTIssuer initialized with config_path")
                except TypeError:
                    # Coba dengan dict
                    jwt_dict = raw_config.get("jwt_config") or raw_config.get("jwt")
                    if jwt_dict:
                        self._jwt_issuer = JWTIssuer(**jwt_dict)
                        logger.info("JWTIssuer initialized with config dict")
                    else:
                        raise ValueError("No jwt or jwt_config key found in YAML")
            else:
                raise FileNotFoundError("security_tls_jwt_mfa.yaml not found")
        except Exception as e:
            logger.warning(f"Failed to load JWT config: {e}. Using fallback dummy JWTIssuer.")
            # Dummy fallback (hanya untuk development)
            class DefaultJWTIssuer:
                def __init__(self):
                    self.algorithm = "HS256"
                    self.access_expire_minutes = 60
                    self.refresh_expire_days = 30
                    self.issuer = "erp-accounting-engine"
                    self.audience = "erp-api"
                    self.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-12345")
                async def create_access_token(self, *args, **kwargs):
                    return "dummy_access_token"
                async def create_refresh_token(self, *args, **kwargs):
                    return "dummy_refresh_token"
                async def create_token_pair(self, *args, **kwargs):
                    return {"access_token": "dummy", "refresh_token": "dummy"}
            self._jwt_issuer = DefaultJWTIssuer()
            logger.info("Using fallback dummy JWTIssuer for development (NOT FOR PRODUCTION)")

        # Encryption service
        enc_key = self.config.get("security", {}).get("encryption", {}).get("master_key") or os.environ.get("ENCRYPTION_MASTER_KEY")
        if enc_key and not os.environ.get("CONFIG_ENCRYPTION_KEY"):
            os.environ["CONFIG_ENCRYPTION_KEY"] = enc_key
        self._encryption_service = FieldEncryptionService()
        logger.info("Security components initialized")

        # ========== 5. Event Store ==========
        self._event_store = AppendOnlyStore()
        await self._event_store.initialize()
        logger.info("Event store initialized")

        # ========== 6. Kernel ==========
        self._sealed_gate = SealedGate()
        self._transactional_executor = TransactionalExecutor()
        self._circuit_breaker_registry = CircuitBreakerRegistry()
        logger.info("Kernel components initialized")

        # ========== 7. Event Publisher ==========
        # Event publisher disabled (outbox-only mode)
        self._event_publisher = None
        logger.info("Event publisher disabled (outbox-only mode)")

        # ========== 8. Repositories ==========
        def _get_repo_class(module_name: str, class_names: list[str], stub_port=None):
            cls = _import_class(module_name, class_names)
            if cls is not None:
                return cls()
            if stub_port is not None:
                try:
                    port_cls = _import_class(stub_port[0], stub_port[1])
                    if port_cls is not None:
                        return _make_stub(port_cls)
                except Exception:
                    pass
            logger.warning(f"Using generic stub for {module_name}")
            return _make_generic_stub(module_name)

        self._account_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_account_repository_impl",
            ["SQLAlchemyAccountRepository"]
        )
        self._journal_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_journal_repository_impl",
            ["SQLAlchemyJournalRepository"]
        )
        self._ar_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_ar_repository_impl",
            ["SQLAlchemyARRepository"]
        )
        self._ap_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_ap_repository_impl",
            ["SQLAlchemyAPRepository"]
        )
        self._inventory_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_inventory_repository_impl",
            ["SQLAlchemyInventoryRepository"]
        )
        self._fixed_asset_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl",
            ["SQLAlchemyFixedAssetRepository"]
        )
        self._bank_cash_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl",
            ["SQLAlchemyBankCashRepository"]
        )
        self._tax_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_tax_repository_impl",
            ["SQLAlchemyTaxRepository"]
        )
        self._ledger_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_ledger_repository_impl",
            ["SQLAlchemyLedgerRepository"]
        )
        self._report_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_report_repository_impl",
            ["SQLAlchemyReportRepository"]
        )
        self._consolidation_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_consolidation_repository_impl",
            ["SQLAlchemyConsolidationRepository"]
        )
        self._audit_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_audit_repository",
            ["SQLAlchemyAuditRepository"]
        )
        self._payroll_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_payroll_repository_impl",
            ["SQLAlchemyPayrollRepository"]
        )
        self._manufacturing_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_manufacturing_repository_impl",
            ["SQLAlchemyManufacturingRepository"]
        )
        self._project_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_project_repository_impl",
            ["SQLAlchemyProjectRepository"]
        )
        self._umkm_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_umkm_repository_impl",
            ["SQLAlchemyUMKMRepository"]
        )
        self._employee_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_employee_repository_impl",
            ["SQLAlchemyEmployeeRepository"]
        )
        self._customer_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_customer_repository_impl",
            ["SQLAlchemyCustomerRepository"]
        )
        self._supplier_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_supplier_repository_impl",
            ["SQLAlchemySupplierRepository"]
        )
        self._legal_entity_repo = _get_repo_class(
            "adapters.secondary_impl.sqlalchemy_legal_entity_repository_impl",
            ["SQLAlchemyLegalEntityRepository"]
        )

        logger.info("All repositories initialized")

        # Coretax client
        coretax_cfg = self.config.get("coretax", {})
        _coretax_env_map = {
            "production": "production",
            "prod": "production",
            "sandbox": "sandbox",
            "staging": "sandbox",
            "development": "sandbox",
            "dev": "sandbox",
            "local": "mock",
            "test": "mock",
            "testing": "mock",
        }
        _raw_app_env = os.environ.get("APP_ENV", "development").lower()
        _coretax_env = _coretax_env_map.get(_raw_app_env, "sandbox")
        self._coretax_client = CoretaxOAuth2Client(
            env=_coretax_env,
            config={"coretax_djp": coretax_cfg},
        )
        logger.info("Coretax client initialized")

        # ========== 9. Unit of Work ==========
        self._uow = SQLAlchemyUnitOfWork()
        logger.info("Unit of Work initialized")

        # ========== 10. Services ==========
        self._coa_service = COAService(
            account_repository=self._account_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._journal_service = JournalService(
            journal_repo=self._journal_repo,
            ledger_repo=self._ledger_repo,
            account_repo=self._account_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._ar_service = ARService(
            ar_repo=self._ar_repo,
            customer_repo=self._customer_repo,
            ledger_repo=self._ledger_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._ap_service = APService(
            ap_repo=self._ap_repo,
            supplier_repo=self._supplier_repo,
            ledger_repo=self._ledger_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._inventory_service = InventoryService(
            inv_repo=self._inventory_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
            ledger_repo=self._ledger_repo,
            valuation_method=self.config.get("inventory", {}).get("valuation_method", "FIFO"),
        )
        self._fixed_asset_service = FixedAssetService(
            asset_repo=self._fixed_asset_repo,
            ledger_repo=self._ledger_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._bank_cash_service = BankCashService(
            bank_repo=self._bank_cash_repo,
            ledger_repo=self._ledger_repo,
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
            legal_entity_repo=self._legal_entity_repo,
            ledger_repo=self._ledger_repo,
            uow=self._uow,
            event_publisher=self._event_publisher,
        )
        self._audit_service = AuditService(
            event_store=self._event_store,
            audit_repo=self._audit_repo,
        )
        self._payroll_service = PayrollService(
            payroll_repo=self._payroll_repo,
            employee_repo=self._employee_repo,
            ledger_repo=self._ledger_repo,
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
            ledger_repo=self._ledger_repo,
            employee_repo=self._employee_repo,
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

        # ========== 11. Command & Query buses ==========
        self._command_bus = UnifiedCommandBus()
        self._query_bus = UnifiedQueryBus()
        logger.info("Buses initialized")

        # ========== 12. Event Subscriber ==========
        if self._kafka_consumer and self._redis_client:
            try:
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
            except Exception as e:
                logger.warning(f"Event subscriber failed: {e}. Continuing without subscriber.")
                self._event_subscriber = None
        else:
            logger.info("Event subscriber not started (Kafka or Redis not available)")

        register_default_logging_handler()

        # ========== Populate container ==========
        self._container.update(
            {
                "db_pool": self._db_pool,
                "kafka_producer": self._kafka_producer,
                "kafka_consumer": self._kafka_consumer,
                "redis_client": self._redis_client,
                "jwt_issuer": self._jwt_issuer,
                "encryption_service": self._encryption_service,
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
    if container.get("kafka_producer"):
        await container["kafka_producer"].stop()
    logger.info("Shutdown via container completed")
