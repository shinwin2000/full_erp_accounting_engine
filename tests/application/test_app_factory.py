#!/usr/bin/env python3
"""
tests/application/test_app_factory.py
Comprehensive tests for application/app_factory.py
Covers: ContainerProtocol, DummyContainer, ApplicationFactory (including private methods),
create_app, shutdown_app with proper mocking.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.app_factory import (
    ApplicationFactory,
    ContainerProtocol,
    DummyContainer,
    create_app,
    shutdown_app,
)

# ============================================================================
# Tests for ContainerProtocol
# ============================================================================

class TestContainerProtocol:
    def test_class_defined(self):
        assert ContainerProtocol is not None
        # ContainerProtocol is a Protocol (which is a class)
        assert isinstance(ContainerProtocol, type)


# ============================================================================
# Tests for DummyContainer
# ============================================================================

class TestDummyContainer:
    def test_construction(self):
        container = DummyContainer()
        assert container._registry == {}

    def test_resolve_exists(self):
        container = DummyContainer()
        container._registry["key"] = "value"
        result = container.resolve("key")
        assert result == "value"

    def test_resolve_not_exists_with_default(self):
        container = DummyContainer()
        default = object()
        result = container.resolve("non_existent", default)
        assert result is default

    def test_resolve_not_exists_without_default(self):
        container = DummyContainer()
        result = container.resolve("non_existent")
        assert result is None

    def test_get_registered_types(self):
        container = DummyContainer()
        container._registry = {"a": 1, "b": 2}
        result = container.get_registered_types()
        assert result == ["a", "b"]  # order may vary

    def test_register_instance(self):
        container = DummyContainer()
        obj = object()
        result = container.register_instance("test_key", obj)
        assert result is True
        assert container._registry["test_key"] is obj

    def test_register_singleton(self):
        container = DummyContainer()
        class MyClass:
            pass
        result = container.register_singleton("singleton_key", MyClass)
        assert result is True
        instance1 = container._registry["singleton_key"]
        instance2 = container._registry["singleton_key"]
        assert instance1 is instance2
        assert isinstance(instance1, MyClass)


# ============================================================================
# Tests for ApplicationFactory
# ============================================================================

class TestApplicationFactory:
    @pytest.fixture
    def dummy_container(self):
        return DummyContainer()

    @pytest.fixture
    def factory(self, dummy_container):
        return ApplicationFactory(config={"test": "value"}, container=dummy_container)

    # ---- Construction ----
    def test_construction_with_container(self, dummy_container):
        factory = ApplicationFactory(config={"env": "prod"}, container=dummy_container)
        assert factory.config == {"env": "prod"}
        assert factory._di_container is dummy_container
        assert factory._initialized is False

    def test_construction_without_container(self):
        factory = ApplicationFactory(config={"env": "prod"})
        assert factory._di_container is not None
        assert isinstance(factory._di_container, DummyContainer)

    # ---- _resolve_infrastructure ----
    def test_resolve_infrastructure_success(self, factory):
        container = factory._di_container
        container.register_instance("database_pool", "db_pool")
        container.register_instance("kafka_producer", "kafka_prod")
        container.register_instance("kafka_consumer", "kafka_cons")
        container.register_instance("redis_client", "redis")
        container.register_instance("jwt_issuer", "jwt")
        container.register_instance("encryption_service", "encrypt")
        container.register_instance("event_store", "event_store")

        factory._resolve_infrastructure()

        assert factory._db_pool == "db_pool"
        assert factory._kafka_producer == "kafka_prod"
        assert factory._kafka_consumer == "kafka_cons"
        assert factory._redis_client == "redis"
        assert factory._jwt_issuer == "jwt"
        assert factory._encryption_service == "encrypt"
        assert factory._event_store == "event_store"
        assert factory._sealed_gate is not None
        assert factory._transactional_executor is not None
        assert factory._circuit_breaker_registry is not None

        # Check container_internal
        assert factory._container_internal["db_pool"] == "db_pool"
        assert factory._container_internal["kafka_producer"] == "kafka_prod"
        assert factory._container_internal["redis_client"] == "redis"
        assert "sealed_gate" in factory._container_internal

    def test_resolve_infrastructure_with_missing(self, factory):
        # No dependencies registered, should not raise
        factory._resolve_infrastructure()
        assert factory._db_pool is None
        assert factory._kafka_producer is None
        assert factory._kafka_consumer is None
        assert factory._redis_client is None
        assert factory._jwt_issuer is None
        assert factory._encryption_service is None
        assert factory._event_store is None
        assert factory._sealed_gate is not None

    # ---- _create_event_publisher ----
    @pytest.mark.asyncio
    async def test_create_event_publisher_success(self, factory):
        factory._kafka_producer = "kafka"
        factory._redis_client = "redis"
        mock_outbox = MagicMock()
        factory._di_container.register_instance("outbox_repository", mock_outbox)

        with patch("application.app_factory.create_event_publisher") as mock_create:
            mock_create.return_value = "publisher"
            result = await factory._create_event_publisher()
            assert result == "publisher"
            mock_create.assert_called_once_with(
                message_broker="kafka",
                outbox=mock_outbox,
                cache="redis",
                mode=factory.config.get("event_publisher", {}).get("mode", "hybrid"),
                enable_circuit_breaker=True,
                enable_idempotency=True,
                max_retries=3,
                retry_delay_seconds=0.5,
            )

    @pytest.mark.asyncio
    async def test_create_event_publisher_no_outbox(self, factory):
        factory._kafka_producer = "kafka"
        factory._redis_client = "redis"
        # outbox_repository not registered
        with patch("application.app_factory.create_event_publisher") as mock_create:
            mock_create.return_value = "publisher"
            result = await factory._create_event_publisher()
            assert result == "publisher"
            # outbox should be None
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["outbox"] is None

    # ---- _resolve_repositories ----
    def test_resolve_repositories(self, factory):
        mock_repo = MagicMock()
        factory._di_container.register_instance("account_repository", mock_repo)
        factory._di_container.register_instance("journal_repository", "journal_repo")
        factory._di_container.register_instance("ar_repository", "ar_repo")
        factory._di_container.register_instance("ap_repository", "ap_repo")
        factory._di_container.register_instance("inventory_repository", "inv_repo")
        factory._di_container.register_instance("fixed_asset_repository", "fa_repo")
        factory._di_container.register_instance("bank_cash_repository", "bc_repo")
        factory._di_container.register_instance("tax_repository", "tax_repo")
        factory._di_container.register_instance("report_repository", "report_repo")
        factory._di_container.register_instance("consolidation_repository", "consol_repo")
        factory._di_container.register_instance("audit_repository", "audit_repo")
        factory._di_container.register_instance("payroll_repository", "payroll_repo")
        factory._di_container.register_instance("manufacturing_repository", "mfg_repo")
        factory._di_container.register_instance("project_repository", "project_repo")
        factory._di_container.register_instance("umkm_repository", "umkm_repo")
        factory._di_container.register_instance("coretax_client", "coretax")
        factory._di_container.register_instance("unit_of_work", "uow")

        factory._resolve_repositories()

        assert factory._account_repo == mock_repo
        assert factory._journal_repo == "journal_repo"
        assert factory._ar_repo == "ar_repo"
        assert factory._ap_repo == "ap_repo"
        assert factory._inventory_repo == "inv_repo"
        assert factory._fixed_asset_repo == "fa_repo"
        assert factory._bank_cash_repo == "bc_repo"
        assert factory._tax_repo == "tax_repo"
        assert factory._report_repo == "report_repo"
        assert factory._consolidation_repo == "consol_repo"
        assert factory._audit_repo == "audit_repo"
        assert factory._payroll_repo == "payroll_repo"
        assert factory._manufacturing_repo == "mfg_repo"
        assert factory._project_repo == "project_repo"
        assert factory._umkm_repo == "umkm_repo"
        assert factory._coretax_client == "coretax"
        assert factory._uow == "uow"

    def test_resolve_repositories_missing(self, factory):
        # No repositories registered, should not raise
        factory._resolve_repositories()
        assert factory._account_repo is None
        assert factory._journal_repo is None
        assert factory._uow is None

    # ---- _setup_services ----
    def test_setup_services(self, factory):
        # Set up required dependencies
        factory._account_repo = MagicMock()
        factory._journal_repo = MagicMock()
        factory._ar_repo = MagicMock()
        factory._ap_repo = MagicMock()
        factory._inventory_repo = MagicMock()
        factory._fixed_asset_repo = MagicMock()
        factory._bank_cash_repo = MagicMock()
        factory._tax_repo = MagicMock()
        factory._report_repo = MagicMock()
        factory._consolidation_repo = MagicMock()
        factory._audit_repo = MagicMock()
        factory._payroll_repo = MagicMock()
        factory._manufacturing_repo = MagicMock()
        factory._project_repo = MagicMock()
        factory._umkm_repo = MagicMock()
        factory._coretax_client = MagicMock()
        factory._uow = MagicMock()
        factory._event_publisher = MagicMock()
        factory._sealed_gate = MagicMock()

        with patch.multiple(
            "application.app_factory",
            COAService=MagicMock,
            JournalService=MagicMock,
            ARService=MagicMock,
            APService=MagicMock,
            InventoryService=MagicMock,
            FixedAssetService=MagicMock,
            BankCashService=MagicMock,
            TaxService=MagicMock,
            ReportService=MagicMock,
            ConsolidationService=MagicMock,
            AuditService=MagicMock,
            PayrollService=MagicMock,
            ManufacturingService=MagicMock,
            ProjectService=MagicMock,
            UMKMService=MagicMock,
            CoretaxService=MagicMock,
        ) as mocks:
            # Call setup_services
            factory._setup_services()

            # Check that each service was instantiated
            assert mocks["COAService"].called
            assert mocks["JournalService"].called
            assert mocks["ARService"].called
            assert mocks["APService"].called
            assert mocks["InventoryService"].called
            assert mocks["FixedAssetService"].called
            assert mocks["BankCashService"].called
            assert mocks["TaxService"].called
            assert mocks["ReportService"].called
            assert mocks["ConsolidationService"].called
            assert mocks["AuditService"].called
            assert mocks["PayrollService"].called
            assert mocks["ManufacturingService"].called
            assert mocks["ProjectService"].called
            assert mocks["UMKMService"].called
            assert mocks["CoretaxService"].called

            # Check container_internal
            assert "coa_service" in factory._container_internal
            assert "journal_service" in factory._container_internal
            assert "ar_service" in factory._container_internal
            assert "ap_service" in factory._container_internal
            assert "inventory_service" in factory._container_internal
            assert "fixed_asset_service" in factory._container_internal
            assert "bank_cash_service" in factory._container_internal
            assert "tax_service" in factory._container_internal
            assert "report_service" in factory._container_internal
            assert "consolidation_service" in factory._container_internal
            assert "audit_service" in factory._container_internal
            assert "payroll_service" in factory._container_internal
            assert "manufacturing_service" in factory._container_internal
            assert "project_service" in factory._container_internal
            assert "umkm_service" in factory._container_internal
            assert "coretax_service" in factory._container_internal

    # ---- _setup_use_cases ----
    def test_setup_use_cases(self, factory):
        # Set up required dependencies
        factory._sealed_gate = MagicMock()
        factory._journal_service = MagicMock()
        factory._bank_cash_service = MagicMock()
        factory._inventory_service = MagicMock()
        factory._ar_service = MagicMock()
        factory._ap_service = MagicMock()
        factory._report_service = MagicMock()
        factory._consolidation_service = MagicMock()
        factory._tax_service = MagicMock()
        factory._coretax_service = MagicMock()
        factory._manufacturing_service = MagicMock()
        factory._fixed_asset_service = MagicMock()
        factory._payroll_service = MagicMock()
        factory._coa_service = MagicMock()
        factory._audit_service = MagicMock()
        factory._event_store = MagicMock()
        factory._event_publisher = MagicMock()
        factory._uow = MagicMock()

        with patch("application.app_factory.set_use_case_container") as mock_set_container:
            factory._setup_use_cases()

            # Check that use cases were created
            assert len(factory._use_cases) > 0
            assert "IntercompanyEliminationUseCase" in str(factory._use_cases)
            # Check container_internal
            assert "IntercompanyEliminationUseCase" in str(factory._container_internal)
            # Check set_use_case_container called
            mock_set_container.assert_called_once_with(factory._use_cases)

    # ---- _setup_buses ----
    def test_setup_buses(self, factory):
        factory._sealed_gate = MagicMock()
        factory._uow = MagicMock()
        factory._circuit_breaker_registry = MagicMock()

        with patch("application.app_factory.UnifiedCommandBus") as mock_cmd_bus, \
             patch("application.app_factory.UnifiedQueryBus") as mock_query_bus, \
             patch.object(factory, "_register_command_handlers") as mock_reg_cmd, \
             patch.object(factory, "_register_query_handlers") as mock_reg_query:

            factory._setup_buses()

            mock_cmd_bus.assert_called_once_with(
                gate=factory._sealed_gate,
                uow=factory._uow,
                circuit_breaker=factory._circuit_breaker_registry,
            )
            mock_query_bus.assert_called_once()
            mock_reg_cmd.assert_called_once()
            mock_reg_query.assert_called_once()

            assert factory._command_bus is not None
            assert factory._query_bus is not None
            assert factory._container_internal["command_bus"] == factory._command_bus
            assert factory._container_internal["query_bus"] == factory._query_bus

    # ---- _register_command_handlers ----
    def test_register_command_handlers(self, factory):
        # Setup mock use cases
        factory._use_cases = {
            object(): MagicMock(),
        }
        # We need to mock the imports from use_cases
        with patch("application.app_factory.register_command_handler") as mock_register:
            factory._register_command_handlers()
            # The actual number depends on how many handlers are registered
            # We'll just check that register_command_handler was called at least once
            assert mock_register.call_count > 0

    # ---- _register_query_handlers ----
    def test_register_query_handlers(self, factory, caplog):
        with caplog.at_level("INFO"):
            factory._register_query_handlers()
            assert "No query handlers to register" in caplog.text

    # ---- initialize ----
    @pytest.mark.asyncio
    async def test_initialize_calls_all_setup_methods(self, factory):
        with patch.object(factory, "_resolve_infrastructure") as mock_infra, \
             patch.object(factory, "_create_event_publisher") as mock_pub, \
             patch.object(factory, "_resolve_repositories") as mock_repos, \
             patch.object(factory, "_setup_services") as mock_services, \
             patch.object(factory, "_setup_use_cases") as mock_use_cases, \
             patch.object(factory, "_setup_buses") as mock_buses, \
             patch.object(factory, "_setup_event_handlers") as mock_events:

            mock_pub.return_value = "publisher"
            result = await factory.initialize()

            mock_infra.assert_called_once()
            mock_pub.assert_called_once()
            mock_repos.assert_called_once()
            mock_services.assert_called_once()
            mock_use_cases.assert_called_once()
            mock_buses.assert_called_once()
            mock_events.assert_called_once()

            assert factory._initialized is True
            assert factory._event_publisher == "publisher"
            assert result == factory._container_internal

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, factory):
        factory._initialized = True
        mock_infra = MagicMock()
        with patch.object(factory, "_resolve_infrastructure", mock_infra):
            result = await factory.initialize()
            mock_infra.assert_not_called()
            assert result == factory._container_internal

    # ---- _setup_event_handlers ----
    @pytest.mark.asyncio
    async def test_setup_event_handlers_with_consumer(self, factory):
        factory._kafka_consumer = AsyncMock()
        factory._redis_client = MagicMock()
        factory.config = {"kafka": {"topics": ["topic1"], "group_id": "group"}}
        with patch("application.app_factory.register_default_logging_handler") as mock_reg, \
             patch("application.app_factory.create_event_subscriber") as mock_create:
            mock_subscriber = AsyncMock()
            mock_subscriber.start = AsyncMock()
            mock_create.return_value = mock_subscriber

            await factory._setup_event_handlers()

            mock_reg.assert_called_once()
            mock_create.assert_called_once()
            mock_subscriber.start.assert_awaited_once()
            assert factory._event_subscriber == mock_subscriber
            assert "event_subscriber" in factory._container_internal

    @pytest.mark.asyncio
    async def test_setup_event_handlers_without_consumer(self, factory):
        factory._kafka_consumer = None
        with patch("application.app_factory.register_default_logging_handler") as mock_reg, \
             patch("application.app_factory.create_event_subscriber") as mock_create:
            await factory._setup_event_handlers()
            mock_reg.assert_called_once()
            mock_create.assert_not_called()
            assert factory._event_subscriber is None

    # ---- shutdown ----
    @pytest.mark.asyncio
    async def test_shutdown(self, factory):
        factory._event_subscriber = AsyncMock()
        factory._event_subscriber.stop = AsyncMock()
        factory._event_publisher = AsyncMock()
        factory._kafka_producer = AsyncMock()
        factory._kafka_producer.stop = AsyncMock()
        factory._kafka_consumer = AsyncMock()
        factory._kafka_consumer.stop = AsyncMock()
        factory._redis_client = AsyncMock()
        factory._redis_client.disconnect = AsyncMock()
        factory._db_pool = AsyncMock()
        factory._db_pool.close = AsyncMock()
        factory._event_store = AsyncMock()
        factory._event_store.close = AsyncMock()

        await factory.shutdown()

        factory._event_subscriber.stop.assert_awaited_once()
        factory._kafka_producer.stop.assert_awaited_once()
        factory._kafka_consumer.stop.assert_awaited_once()
        factory._redis_client.disconnect.assert_awaited_once()
        factory._db_pool.close.assert_awaited_once()
        factory._event_store.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_no_resources(self, factory):
        factory._event_subscriber = None
        factory._event_publisher = None
        factory._kafka_producer = None
        factory._kafka_consumer = None
        factory._redis_client = None
        factory._db_pool = None
        factory._event_store = None
        # Should not raise
        await factory.shutdown()


# ============================================================================
# Tests for create_app and shutdown_app
# ============================================================================

@pytest.mark.asyncio
async def test_create_app():
    container = DummyContainer()
    config = {"env": "test"}
    with patch("application.app_factory.ApplicationFactory") as mock_factory:
        mock_instance = MagicMock()
        mock_instance.initialize = AsyncMock(return_value={"initialized": True})
        mock_factory.return_value = mock_instance

        result = await create_app(config, container)

        mock_factory.assert_called_once_with(config, container)
        mock_instance.initialize.assert_awaited_once()
        assert result == {"initialized": True}


@pytest.mark.asyncio
async def test_shutdown_app_with_factory_in_container():
    factory = MagicMock()
    factory.shutdown = AsyncMock()
    container = {"ApplicationFactory": factory}
    result = await shutdown_app(container)
    factory.shutdown.assert_awaited_once()
    assert result is True


@pytest.mark.asyncio
async def test_shutdown_app_with_factory_as_value():
    factory = MagicMock()
    factory.shutdown = AsyncMock()
    container = {"some_key": factory}  # factory not in "ApplicationFactory"
    result = await shutdown_app(container)
    factory.shutdown.assert_awaited_once()
    assert result is True


@pytest.mark.asyncio
async def test_shutdown_app_no_factory():
    container = {}
    result = await shutdown_app(container)
    assert result is True
