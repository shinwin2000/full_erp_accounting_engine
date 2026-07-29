# test_orchestrator.py
# Comprehensive tests for bootstrap/orchestrator.py

import asyncio
import os
import signal
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bootstrap.orchestrator import (
    StartupContext,
    StartupOrchestrator,
    StartupPhase,
    StartupStatus,
    StartupStep,
    get_health,
    get_startup_orchestrator,
    main,
    register_signal_handlers,
    run_startup,
    shutdown,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def mock_step_action():
    return MagicMock(return_value={"status": "ok"})


@pytest.fixture
def mock_step_rollback():
    return MagicMock()


@pytest.fixture
def startup_step(mock_step_action, mock_step_rollback):
    return StartupStep(
        name="test_step",
        phase=StartupPhase.CONFIG_LOAD,
        action=mock_step_action,
        rollback=mock_step_rollback,
        required=True,
        timeout_seconds=5,
        dependencies=["dep1"],
    )


@pytest.fixture
def startup_context():
    return StartupContext(
        config={"key": "value"},
        components={"comp": "data"},
        errors=[("err1", "msg1")],
        start_time=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def orchestrator():
    # Reset singleton before each test
    StartupOrchestrator._instance = None
    with patch("bootstrap.orchestrator.logger") as mock_logger:
        orch = StartupOrchestrator()
        # Clear any existing components to start fresh
        orch._context.components.clear()
        orch._context.config.clear()
        orch._steps = []
        yield orch


# -------------------- Tests for StartupPhase Enum --------------------
class TestStartupPhase:
    def test_members(self):
        assert StartupPhase.CONSTITUTION_LOAD is not None
        assert StartupPhase.AXIOMS_LOAD is not None
        assert StartupPhase.COMPLETE is not None

    def test_display_name(self):
        assert StartupPhase.CONSTITUTION_LOAD.display_name() == "Load Constitution"
        assert StartupPhase.COMPLETE.display_name() == "Complete"


# -------------------- Tests for StartupStatus Enum --------------------
class TestStartupStatus:
    def test_members(self):
        assert StartupStatus.NOT_STARTED is not None
        assert StartupStatus.SUCCESS is not None
        assert StartupStatus.FAILED is not None

    def test_display_name(self):
        assert StartupStatus.NOT_STARTED.display_name() == "Not Started"
        assert StartupStatus.SUCCESS.display_name() == "Success"


# -------------------- Tests for StartupStep --------------------
class TestStartupStep:
    def test_construction_valid(self, startup_step):
        assert startup_step.name == "test_step"
        assert startup_step.phase == StartupPhase.CONFIG_LOAD
        assert startup_step.required is True
        assert startup_step.timeout_seconds == 5
        assert startup_step.dependencies == ["dep1"]
        assert startup_step.status == "pending"
        assert startup_step._version == 1
        assert len(startup_step._snapshots) == 1

    def test_validation_name_required(self):
        with pytest.raises(ValueError, match="name is required"):
            StartupStep(name="", phase=StartupPhase.COMPLETE, action=lambda: None)

    def test_validation_invalid_phase(self):
        with pytest.raises(ValueError, match="invalid phase"):
            StartupStep(name="test", phase="INVALID", action=lambda: None)

    def test_validation_action_not_callable(self):
        with pytest.raises(ValueError, match="action must be callable"):
            StartupStep(name="test", phase=StartupPhase.COMPLETE, action="not_callable")

    def test_validation_timeout_positive(self):
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            StartupStep(name="test", phase=StartupPhase.COMPLETE, action=lambda: None, timeout_seconds=0)

    def test_validate_valid(self, startup_step):
        result = startup_step.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, startup_step):
        d = startup_step.to_dict()
        assert d["name"] == "test_step"
        assert d["phase"] == "CONFIG_LOAD"
        assert d["required"] is True
        assert d["timeout_seconds"] == 5
        assert d["dependencies"] == ["dep1"]
        assert d["status"] == "pending"
        assert d["error"] is None
        assert d["duration_ms"] == 0.0
        assert d["started_at"] is None
        assert d["completed_at"] is None
        assert d["version"] == 1

    def test_from_dict(self, startup_step):
        d = startup_step.to_dict()
        action_map = {"test_step": lambda: "mocked"}
        restored = StartupStep.from_dict(d, action_map)
        assert restored.name == "test_step"
        assert restored.phase == StartupPhase.CONFIG_LOAD
        assert restored.required is True
        assert restored.timeout_seconds == 5
        assert restored.dependencies == ["dep1"]
        assert restored.status == "pending"
        assert restored._version == 1
        # action should be the mocked one
        assert restored.action() == "mocked"

    def test_from_dict_without_action_map(self, startup_step):
        d = startup_step.to_dict()
        # action_map is None, action becomes a no-op lambda
        restored = StartupStep.from_dict(d)
        assert restored.action is not None
        # calling it should not raise
        restored.action()

    def test_clone(self, startup_step):
        cloned = startup_step.clone()
        assert cloned.name == "test_step_COPY"
        assert cloned.phase == startup_step.phase
        assert cloned.required == startup_step.required
        assert cloned.timeout_seconds == startup_step.timeout_seconds
        assert cloned.dependencies == startup_step.dependencies
        assert cloned._version == startup_step._version + 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, startup_step):
        snap = startup_step.snapshot()
        assert snap["version"] == 1
        assert snap["name"] == "test_step"
        assert snap["phase"] == "CONFIG_LOAD"
        assert snap["status"] == "pending"
        assert "timestamp" in snap

    def test_version(self, startup_step):
        assert startup_step.version() == 1

    def test_audit_trail(self, startup_step):
        startup_step.touch("tester")
        trail = startup_step.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"

    def test_touch(self, startup_step):
        old_version = startup_step._version
        touched = startup_step.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1


# -------------------- Tests for StartupContext --------------------
class TestStartupContext:
    def test_construction_valid(self, startup_context):
        assert startup_context.config == {"key": "value"}
        assert startup_context.components == {"comp": "data"}
        assert startup_context.errors == [("err1", "msg1")]
        assert startup_context.start_time == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert startup_context._version == 1
        assert len(startup_context._snapshots) == 1

    def test_validation_start_time_required(self):
        with pytest.raises(ValueError, match="start_time is required"):
            StartupContext(start_time=None)

    def test_validate_valid(self, startup_context):
        result = startup_context.validate()
        assert result["is_valid"] is True

    def test_to_dict(self, startup_context):
        d = startup_context.to_dict()
        assert d["config_keys"] == ["key"]
        assert d["components_keys"] == ["comp"]
        assert d["errors"] == [("err1", "msg1")]
        assert d["start_time"] == "2025-01-01T00:00:00+00:00"
        assert d["version"] == 1

    def test_from_dict(self, startup_context):
        d = startup_context.to_dict()
        restored = StartupContext.from_dict(d)
        assert restored.start_time == startup_context.start_time
        assert restored._version == startup_context._version
        # config and components are not restored from dict (only keys, not values)
        assert restored.config == {}
        assert restored.components == {}

    def test_clone(self, startup_context):
        cloned = startup_context.clone()
        assert cloned.config == startup_context.config
        assert cloned.components == startup_context.components
        assert cloned.errors == startup_context.errors
        assert cloned._version == startup_context._version + 1
        assert cloned.start_time != startup_context.start_time
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, startup_context):
        snap = startup_context.snapshot()
        assert snap["version"] == 1
        assert snap["config_keys_count"] == 1
        assert snap["components_count"] == 1
        assert snap["errors_count"] == 1
        assert "timestamp" in snap

    def test_version(self, startup_context):
        assert startup_context.version() == 1

    def test_audit_trail(self, startup_context):
        startup_context.touch("tester")
        trail = startup_context.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, startup_context):
        old_version = startup_context._version
        touched = startup_context.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1


# -------------------- Tests for StartupOrchestrator --------------------
class TestStartupOrchestrator:
    def test_singleton(self):
        o1 = StartupOrchestrator()
        o2 = StartupOrchestrator()
        assert o1 is o2

    def test_initialization(self, orchestrator):
        assert isinstance(orchestrator._context, StartupContext)
        assert orchestrator._status == StartupStatus.NOT_STARTED
        assert orchestrator._version == 1
        # _steps should be built by _build_steps
        assert len(orchestrator._steps) > 0

    def test_build_steps(self, orchestrator):
        # _build_steps is called in __init__
        steps = orchestrator._steps
        assert len(steps) == 11  # as defined in _build_steps
        step_names = [s.name for s in steps]
        expected = [
            "load_constitution", "load_axioms", "load_config",
            "connect_database", "connect_message_broker", "connect_cache",
            "init_repositories", "init_services", "init_kernel",
            "start_api", "health_check"
        ]
        assert step_names == expected

    # ---- _load_constitution ----
    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_load_constitution_success(self, mock_import, orchestrator):
        mock_supreme = MagicMock()
        mock_supreme.get_supreme_law.return_value = MagicMock()
        mock_supreme.get_supreme_law.return_value.verify_integrity.return_value = {"is_valid": True, "version": "1.0"}
        mock_import.return_value = mock_supreme

        result = orchestrator._load_constitution()
        assert result["status"] == "loaded"
        assert result["version"] == "1.0"
        assert "supreme_law" in orchestrator._context.components

    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_load_constitution_failure(self, mock_import, orchestrator):
        mock_import.side_effect = ImportError("module not found")
        with pytest.raises(RuntimeError, match="Failed to load constitution"):
            orchestrator._load_constitution()

    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_load_constitution_integrity_fail(self, mock_import, orchestrator):
        mock_supreme = MagicMock()
        mock_supreme.get_supreme_law.return_value = MagicMock()
        mock_supreme.get_supreme_law.return_value.verify_integrity.return_value = {"is_valid": False}
        mock_import.return_value = mock_supreme
        with pytest.raises(RuntimeError, match="Constitution integrity check failed"):
            orchestrator._load_constitution()

    # ---- _rollback_constitution ----
    def test_rollback_constitution(self, orchestrator):
        orchestrator._context.components["supreme_law"] = "something"
        orchestrator._rollback_constitution()
        assert "supreme_law" not in orchestrator._context.components

    # ---- _load_axioms ----
    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_load_axioms_success(self, mock_import, orchestrator):
        mock_axioms = MagicMock()
        mock_axioms.get_double_entry_axiom.return_value = "axiom_obj"
        mock_import.return_value = mock_axioms
        result = orchestrator._load_axioms()
        assert result["loaded_axioms"] == 1
        assert "axioms" in orchestrator._context.components
        assert orchestrator._context.components["axioms"]["double_entry"] == "axiom_obj"

    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_load_axioms_failure(self, mock_import, orchestrator):
        mock_import.side_effect = ImportError("no module")
        with pytest.raises(RuntimeError, match="Failed to load axioms"):
            orchestrator._load_axioms()

    # ---- _rollback_axioms ----
    def test_rollback_axioms(self, orchestrator):
        orchestrator._context.components["axioms"] = {"double_entry": "obj"}
        orchestrator._rollback_axioms()
        assert "axioms" not in orchestrator._context.components

    # ---- _load_config ----
    @patch("bootstrap.orchestrator.importlib.import_module")
    @patch.dict(os.environ, {"ENVIRONMENT": "production"})
    def test_load_config_success(self, mock_import, orchestrator):
        mock_manager = MagicMock()
        mock_manager.load_all.return_value = {"database": {}, "app": {"environment": "production"}}
        mock_manager.get_metadata.return_value = {"file_count": 2, "load_time_ms": 10.5}
        mock_import.return_value.get_config_manager.return_value = mock_manager
        result = orchestrator._load_config()
        assert result["environment"] == "production"
        assert result["file_count"] == 2
        assert result["load_time_ms"] == 10.5
        assert orchestrator._context.components["config_manager"] == mock_manager
        assert orchestrator._context.config == {"database": {}, "app": {"environment": "production"}}

    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_load_config_missing_required_section(self, mock_import, orchestrator):
        mock_manager = MagicMock()
        mock_manager.load_all.return_value = {}  # missing database
        mock_import.return_value.get_config_manager.return_value = mock_manager
        with pytest.raises(RuntimeError, match="Missing required section 'database'"):
            orchestrator._load_config()

    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_load_config_module_missing(self, mock_import, orchestrator):
        mock_import.side_effect = ImportError("no manager")
        with pytest.raises(RuntimeError, match="config.manager is required"):
            orchestrator._load_config()

    # ---- _rollback_config ----
    def test_rollback_config(self, orchestrator):
        orchestrator._context.config = {"key": "value"}
        orchestrator._context.components["config_manager"] = "manager"
        orchestrator._rollback_config()
        assert orchestrator._context.config == {}
        assert "config_manager" not in orchestrator._context.components

    # ---- _connect_database ----
    @pytest.mark.asyncio
    @patch("bootstrap.orchestrator.importlib.import_module")
    async def test_connect_database_success(self, mock_import, orchestrator):
        orchestrator._context.components["config_manager"] = MagicMock()
        orchestrator._context.components["config_manager"].get_section.return_value = {"url": "postgresql://user:pass@localhost/db"}

        mock_pool_mod = MagicMock()
        mock_pool_mod.get_connection_pool = AsyncMock(return_value=MagicMock())
        mock_pool_mod.get_session_factory = AsyncMock(return_value=MagicMock())

        mock_import.side_effect = [mock_pool_mod, MagicMock()]  # pool_mod, session_mod

        # Mock the pool's fetchval
        pool = MagicMock()
        pool.fetchval = AsyncMock(return_value=1)
        mock_pool_mod.get_connection_pool.return_value = pool

        result = await orchestrator._connect_database()
        assert result["connected"] is True
        assert "db_pool" in orchestrator._context.components
        assert "session_factory" in orchestrator._context.components

    @pytest.mark.asyncio
    @patch("bootstrap.orchestrator.importlib.import_module")
    async def test_connect_database_failure(self, mock_import, orchestrator):
        orchestrator._context.components["config_manager"] = MagicMock()
        orchestrator._context.components["config_manager"].get_section.return_value = {"url": "postgresql://..."}
        mock_import.side_effect = ImportError("no pool")
        with pytest.raises(RuntimeError, match="Database connection failed"):
            await orchestrator._connect_database()

    @pytest.mark.asyncio
    async def test_disconnect_database(self, orchestrator):
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()
        orchestrator._context.components["db_pool"] = mock_pool
        orchestrator._context.components["session_factory"] = "factory"
        await orchestrator._disconnect_database()
        mock_pool.close.assert_called_once()
        assert "db_pool" not in orchestrator._context.components
        assert "session_factory" not in orchestrator._context.components

    # ---- _connect_message_broker ----
    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_connect_message_broker_success(self, mock_import, orchestrator):
        orchestrator._context.components["config_manager"] = MagicMock()
        orchestrator._context.components["config_manager"].get_section.return_value = {"bootstrap_servers": "localhost:9092"}
        mock_kafka = MagicMock()
        mock_kafka.get_kafka_producer.return_value = MagicMock(bootstrap_servers="localhost:9092")
        mock_import.return_value = mock_kafka
        result = orchestrator._connect_message_broker()
        assert result["connected"] is True
        assert result["broker"] == "localhost:9092"
        assert "kafka_producer" in orchestrator._context.components

    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_connect_message_broker_degraded(self, mock_import, orchestrator):
        mock_import.side_effect = ImportError("no kafka")
        result = orchestrator._connect_message_broker()
        assert result["connected"] is False
        assert result["degraded"] is True
        assert "kafka_producer" not in orchestrator._context.components

    # ---- _disconnect_message_broker ----
    def test_disconnect_message_broker(self, orchestrator):
        mock_producer = MagicMock()
        mock_producer.close = MagicMock()
        orchestrator._context.components["kafka_producer"] = mock_producer
        orchestrator._disconnect_message_broker()
        mock_producer.close.assert_called_once()
        assert "kafka_producer" not in orchestrator._context.components

    # ---- _connect_cache ----
    @pytest.mark.asyncio
    @patch("bootstrap.orchestrator.importlib.import_module")
    async def test_connect_cache_success(self, mock_import, orchestrator):
        orchestrator._context.components["config_manager"] = MagicMock()
        orchestrator._context.components["config_manager"].get_section.return_value = {"host": "localhost", "port": 6379}
        mock_redis = MagicMock()
        mock_redis.get_redis_client = AsyncMock(return_value=MagicMock(ping=AsyncMock()))
        mock_import.return_value = mock_redis
        result = await orchestrator._connect_cache()
        assert result["connected"] is True
        assert result["host"] == "localhost"
        assert result["port"] == 6379
        assert "redis_client" in orchestrator._context.components

    @pytest.mark.asyncio
    @patch("bootstrap.orchestrator.importlib.import_module")
    async def test_connect_cache_degraded(self, mock_import, orchestrator):
        mock_redis = MagicMock()
        mock_redis.get_redis_client = AsyncMock(side_effect=Exception("connection refused"))
        mock_import.return_value = mock_redis
        orchestrator._context.components["config_manager"] = MagicMock()
        orchestrator._context.components["config_manager"].get_section.return_value = {}
        result = await orchestrator._connect_cache()
        assert result["connected"] is False
        assert result["degraded"] is True

    @pytest.mark.asyncio
    async def test_disconnect_cache(self, orchestrator):
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        orchestrator._context.components["redis_client"] = mock_client
        await orchestrator._disconnect_cache()
        mock_client.aclose.assert_called_once()
        assert "redis_client" not in orchestrator._context.components

    # ---- _init_repositories ----
    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_init_repositories_success(self, mock_import, orchestrator):
        session_factory = MagicMock()
        orchestrator._context.components["session_factory"] = session_factory

        # Mock unit of work
        mock_uow_mod = MagicMock()
        mock_uow_mod.SQLAlchemyUnitOfWork = MagicMock(return_value="uow")
        mock_import.return_value = mock_uow_mod

        # Mock repositories
        def repo_factory(module_path, class_name, repo_name):
            return MagicMock()

        with patch.object(orchestrator, "_init_repositories", wraps=orchestrator._init_repositories) as wrapped:
            # Override the repo imports to return mocks
            with patch("bootstrap.orchestrator.importlib.import_module") as mock_import_repo:
                mock_import_repo.return_value = MagicMock()
                # We'll just let the actual method run, but it will try to import real modules - we need to mock them all.
                # To simplify, we'll mock the init_repo function or skip this complex test.
                # We'll test the method indirectly via startup flow later.

        # Since this is complex, we'll test a simplified version or just ensure it doesn't raise
        # We'll mock the actual imports to return dummy classes.
        with patch("bootstrap.orchestrator.importlib.import_module") as mock_import_all:
            # Mock the unit of work module
            mock_uow = MagicMock()
            mock_uow.SQLAlchemyUnitOfWork = MagicMock(return_value="uow")
            # Mock the repository modules
            mock_repo_classes = {
                "adapters.secondary_impl.sqlalchemy_journal_repository_impl": "SQLAlchemyJournalRepository",
                "adapters.secondary_impl.sqlalchemy_account_repository_impl": "SQLAlchemyAccountRepository",
                "adapters.secondary_impl.sqlalchemy_ar_repository_impl": "SQLAlchemyARRepository",
                "adapters.secondary_impl.sqlalchemy_ap_repository_impl": "SQLAlchemyAPRepository",
                "adapters.secondary_impl.sqlalchemy_ledger_repository_impl": "SQLAlchemyLedgerRepository",
            }
            def side_effect(module_name):
                if module_name == "adapters.secondary_impl.sqlalchemy_unit_of_work_impl":
                    return mock_uow
                mod = MagicMock()
                if module_name in mock_repo_classes:
                    setattr(mod, mock_repo_classes[module_name], MagicMock(return_value=MagicMock()))
                return mod
            mock_import_all.side_effect = side_effect

            result = orchestrator._init_repositories()
            assert result["repositories_initialized"] == 5
            assert "repositories" in orchestrator._context.components
            assert "unit_of_work" in orchestrator._context.components
            repos = orchestrator._context.components["repositories"]
            assert set(repos.keys()) == {"journal", "account", "ar", "ap", "ledger"}

    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_init_repositories_missing_session_factory(self, mock_import, orchestrator):
        with pytest.raises(RuntimeError, match="Session factory not available"):
            orchestrator._init_repositories()

    # ---- _cleanup_repositories ----
    def test_cleanup_repositories(self, orchestrator):
        orchestrator._context.components["repositories"] = "repos"
        orchestrator._context.components["unit_of_work"] = "uow"
        orchestrator._cleanup_repositories()
        assert "repositories" not in orchestrator._context.components
        assert "unit_of_work" not in orchestrator._context.components

    # ---- _init_services ----
    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_init_services_success(self, mock_import, orchestrator):
        # Setup repositories and uow
        repositories = {
            "journal": MagicMock(),
            "account": MagicMock(),
            "ledger": MagicMock(),
            "ar": MagicMock(),
            "ap": MagicMock(),
        }
        orchestrator._context.components["repositories"] = repositories
        orchestrator._context.components["unit_of_work"] = "uow"

        mock_services = MagicMock()
        mock_services.APService = MagicMock(return_value="ap_service")
        mock_services.ARService = MagicMock(return_value="ar_service")
        mock_services.JournalService = MagicMock(return_value="journal_service")

        def side_effect(module_name):
            if module_name == "application.service_layer.service_ap" or module_name == "application.service_layer.service_ar" or module_name == "application.service_layer.service_journal":
                return mock_services
            return MagicMock()

        mock_import.side_effect = side_effect

        result = orchestrator._init_services()
        assert result["services_initialized"] == 3
        assert "services" in orchestrator._context.components
        services = orchestrator._context.components["services"]
        assert set(services.keys()) == {"journal", "ar", "ap"}

    def test_init_services_missing_repos(self, orchestrator):
        with pytest.raises(RuntimeError, match="Repositories or UOW not available"):
            orchestrator._init_services()

    # ---- _cleanup_services ----
    def test_cleanup_services(self, orchestrator):
        orchestrator._context.components["services"] = {"journal": "service"}
        orchestrator._cleanup_services()
        assert "services" not in orchestrator._context.components

    # ---- _init_kernel ----
    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_init_kernel_success(self, mock_import, orchestrator):
        mock_gate = MagicMock()
        mock_gate.get_sealed_gate.return_value = MagicMock(is_sealed=lambda: True)
        mock_import.return_value = mock_gate
        result = orchestrator._init_kernel()
        assert result["kernel_ready"] is True
        assert result["sealed"] is True
        assert "sealed_gate" in orchestrator._context.components

    @patch("bootstrap.orchestrator.importlib.import_module")
    def test_init_kernel_failure(self, mock_import, orchestrator):
        mock_import.side_effect = ImportError("no gate")
        with pytest.raises(RuntimeError, match="Kernel initialization failed"):
            orchestrator._init_kernel()

    # ---- _shutdown_kernel ----
    def test_shutdown_kernel(self, orchestrator):
        orchestrator._context.components["sealed_gate"] = "gate"
        orchestrator._shutdown_kernel()
        assert "sealed_gate" not in orchestrator._context.components

    # ---- _start_api ----
    @pytest.mark.asyncio
    @patch("bootstrap.orchestrator.uvicorn")
    @patch("bootstrap.orchestrator.importlib.import_module")
    @patch("bootstrap.orchestrator.threading.Thread")
    async def test_start_api_success(self, mock_thread, mock_import, mock_uvicorn, orchestrator):
        # Setup context
        orchestrator._context.components["config_manager"] = MagicMock()
        orchestrator._context.config = {
            "database": {"host": "localhost"},
            "security": {"jwt_secret": "secret"},
            "kafka": {"bootstrap_servers": "localhost"},
            "redis": {"host": "localhost"},
        }

        # Mock the app factory
        mock_app_mod = MagicMock()
        mock_app_mod.create_app.return_value = {"router": MagicMock()}
        mock_import.return_value = mock_app_mod

        # Mock threading
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        result = await orchestrator._start_api()
        assert result["api_started"] is True
        assert result["port"] == 8000
        assert "api_app" in orchestrator._context.components
        assert "api_thread" in orchestrator._context.components
        mock_thread_instance.start.assert_called_once()

    @pytest.mark.asyncio
    @patch("bootstrap.orchestrator.importlib.import_module")
    async def test_start_api_failure(self, mock_import, orchestrator):
        orchestrator._context.components["config_manager"] = MagicMock()
        orchestrator._context.config = {"database": {}}
        mock_import.side_effect = Exception("factory error")
        with pytest.raises(RuntimeError, match="Unable to create API app"):
            await orchestrator._start_api()

    # ---- _stop_api ----
    def test_stop_api(self, orchestrator):
        container = MagicMock()
        container.shutdown = MagicMock()
        orchestrator._context.components["app_container"] = container
        orchestrator._context.components["api_app"] = "app"
        orchestrator._context.components["api_thread"] = "thread"
        orchestrator._stop_api()
        container.shutdown.assert_called_once()
        assert "api_app" not in orchestrator._context.components
        assert "api_thread" not in orchestrator._context.components

    # ---- _health_check ----
    @pytest.mark.asyncio
    async def test_health_check_success(self, orchestrator):
        # Setup components for healthy state
        pool = MagicMock()
        pool.fetchval = AsyncMock(return_value=1)
        orchestrator._context.components["db_pool"] = pool

        gate = MagicMock()
        gate.is_sealed = lambda: True
        orchestrator._context.components["sealed_gate"] = gate

        redis = AsyncMock()
        redis.ping = AsyncMock()
        orchestrator._context.components["redis_client"] = redis

        producer = MagicMock()
        producer.bootstrap_servers = "localhost"
        orchestrator._context.components["kafka_producer"] = producer

        orchestrator._context.components["repositories"] = {"journal": "repo"}
        orchestrator._context.components["services"] = {"journal": "service"}

        # Mock KeyManager
        with patch("bootstrap.orchestrator.importlib.import_module") as mock_import:
            mock_km = MagicMock()
            mock_km.get_key_manager.return_value = MagicMock()
            mock_km.get_key_manager.return_value.list_keys.return_value = [{"key_id": "test"}]
            mock_km.get_key_manager.return_value.get_current_key_id.return_value = "test"
            mock_import.return_value = mock_km

            with patch("shutil.disk_usage") as mock_disk:
                mock_disk.return_value = MagicMock(free=50*1024**3, total=100*1024**3)
                health = await orchestrator._health_check()
                assert health["overall"] == "healthy"
                assert "checks" in health
                assert health["checks"]["database"]["status"] == "healthy"
                assert health["checks"]["kernel"]["status"] == "healthy"
                assert health["checks"]["cache"]["status"] == "healthy"
                assert health["checks"]["broker"]["status"] == "healthy"
                assert health["checks"]["encryption"]["status"] == "healthy"
                assert health["checks"]["repositories"]["status"] == "healthy"
                assert health["checks"]["services"]["status"] == "healthy"
                assert health["checks"]["disk"]["status"] == "healthy"
                assert "errors" not in health
                assert "warnings" not in health

    @pytest.mark.asyncio
    async def test_health_check_db_failure(self, orchestrator):
        pool = MagicMock()
        pool.fetchval = AsyncMock(side_effect=Exception("db down"))
        orchestrator._context.components["db_pool"] = pool
        gate = MagicMock(is_sealed=lambda: True)
        orchestrator._context.components["sealed_gate"] = gate
        orchestrator._context.components["repositories"] = {}
        orchestrator._context.components["services"] = {}
        with patch("bootstrap.orchestrator.importlib.import_module") as mock_import:
            mock_km = MagicMock()
            mock_km.get_key_manager.return_value = MagicMock()
            mock_km.get_key_manager.return_value.list_keys.return_value = [{"key_id": "test"}]
            mock_import.return_value = mock_km
            with patch("shutil.disk_usage") as mock_disk:
                mock_disk.return_value = MagicMock(free=50*1024**3, total=100*1024**3)
                with pytest.raises(RuntimeError, match="Health check failed"):
                    await orchestrator._health_check()

    # ---- startup ----
    @pytest.mark.asyncio
    async def test_startup_success(self, orchestrator):
        # We need to mock each step's action to succeed
        # Since _build_steps creates real steps with real actions, we'll replace them with mocks
        for step in orchestrator._steps:
            step.action = AsyncMock(return_value={"ok": True})
            step.rollback = MagicMock()
            step.timeout_seconds = 1

        status = await orchestrator.startup()
        assert status == StartupStatus.SUCCESS
        assert orchestrator._status == StartupStatus.SUCCESS
        # Check that steps were executed
        for step in orchestrator._steps:
            assert step.status == "success"
            assert step.duration_ms > 0

    @pytest.mark.asyncio
    async def test_startup_step_failure_required(self, orchestrator):
        # Make the first required step fail
        for i, step in enumerate(orchestrator._steps):
            if i == 0:
                step.action = AsyncMock(side_effect=Exception("step failed"))
            else:
                step.action = AsyncMock(return_value={"ok": True})
        status = await orchestrator.startup()
        assert status == StartupStatus.FAILED
        assert orchestrator._status == StartupStatus.FAILED
        # Check that rollback was triggered
        assert orchestrator._status == StartupStatus.ROLLBACK_COMPLETE

    @pytest.mark.asyncio
    async def test_startup_step_timeout(self, orchestrator):
        step = orchestrator._steps[0]
        step.action = AsyncMock(side_effect=asyncio.TimeoutError)
        step.timeout_seconds = 1
        status = await orchestrator.startup()
        assert status == StartupStatus.FAILED
        assert step.status == "failed"
        assert "Timeout" in step.error

    @pytest.mark.asyncio
    async def test_startup_already_started(self, orchestrator):
        orchestrator._status = StartupStatus.IN_PROGRESS
        status = await orchestrator.startup()
        assert status == StartupStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_startup_skip_health(self, orchestrator):
        # Mock steps to succeed, but skip the health check step
        for step in orchestrator._steps:
            if step.name == "health_check":
                step.action = AsyncMock(return_value={"ok": True})
            else:
                step.action = AsyncMock(return_value={"ok": True})
        status = await orchestrator.startup(skip_health=True)
        assert status == StartupStatus.SUCCESS

    # ---- shutdown ----
    @pytest.mark.asyncio
    async def test_shutdown(self, orchestrator):
        for step in orchestrator._steps:
            step.status = "success"
            step.rollback = AsyncMock()
        await orchestrator.shutdown()
        # Check rollback called for each step
        for step in orchestrator._steps:
            step.rollback.assert_called_once()
        assert orchestrator._status == StartupStatus.NOT_STARTED

    # ---- get_status ----
    def test_get_status(self, orchestrator):
        orchestrator._context.start_time = datetime(2025, 1, 1, tzinfo=UTC)
        orchestrator._status = StartupStatus.IN_PROGRESS
        status = orchestrator.get_status()
        assert status["status"] == "IN_PROGRESS"
        assert status["start_time"] == "2025-01-01T00:00:00+00:00"
        assert len(status["steps"]) == len(orchestrator._steps)
        assert status["errors"] == []
        assert "components_initialized" in status
        assert status["version"] == 1

    # ---- get_context ----
    def test_get_context(self, orchestrator):
        context = orchestrator.get_context()
        assert isinstance(context, StartupContext)

    # ---- get_health_status ----
    def test_get_health_status(self, orchestrator):
        health = {"overall": "healthy"}
        orchestrator._context.components["health_status"] = health
        assert orchestrator.get_health_status() == health

    # ---- validate ----
    def test_validate(self, orchestrator):
        result = orchestrator.validate()
        assert result["is_valid"] is True
        # Corrupt a step
        orchestrator._steps[0].name = ""
        result = orchestrator.validate()
        assert result["is_valid"] is False

    # ---- to_dict ----
    def test_to_dict(self, orchestrator):
        d = orchestrator.to_dict()
        assert d["status"] == "NOT_STARTED"
        assert "context" in d
        assert "steps" in d
        assert d["version"] == 1

    # ---- from_dict ----
    def test_from_dict(self, orchestrator):
        data = orchestrator.to_dict()
        action_map = {}
        restored = StartupOrchestrator.from_dict(data, action_map)
        assert restored._status == orchestrator._status
        assert restored._version == orchestrator._version
        assert len(restored._steps) == len(orchestrator._steps)

    # ---- clone ----
    def test_clone(self, orchestrator):
        cloned = orchestrator.clone()
        assert cloned._version == orchestrator._version + 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    # ---- snapshot ----
    def test_snapshot(self, orchestrator):
        snap = orchestrator.snapshot()
        assert snap["version"] == 1
        assert snap["status"] == "NOT_STARTED"
        assert snap["steps_count"] == len(orchestrator._steps)
        assert "timestamp" in snap

    # ---- version ----
    def test_version(self, orchestrator):
        assert orchestrator.version() == 1

    # ---- audit_trail ----
    def test_audit_trail(self, orchestrator):
        orchestrator._record_audit("TEST", "user", {})
        trail = orchestrator.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    # ---- touch ----
    def test_touch(self, orchestrator):
        old_version = orchestrator._version
        touched = orchestrator.touch("tester")
        assert touched._version == old_version + 1
        assert touched._audit_trail[0]["action"] == "TOUCH"


# -------------------- Tests for Module-level Functions --------------------
def test_get_startup_orchestrator():
    o1 = get_startup_orchestrator()
    o2 = get_startup_orchestrator()
    assert o1 is o2


@patch("bootstrap.orchestrator.get_startup_orchestrator")
@patch("bootstrap.orchestrator.asyncio.Runner")
def test_run_startup_success(mock_runner, mock_get_orch):
    mock_orch = MagicMock()
    mock_orch.startup.return_value = StartupStatus.SUCCESS
    mock_get_orch.return_value = mock_orch

    mock_runner_instance = MagicMock()
    mock_runner_instance.run.return_value = StartupStatus.SUCCESS
    mock_runner.return_value = mock_runner_instance

    result = run_startup()
    assert result is True
    mock_runner_instance.run.assert_called_once()


@patch("bootstrap.orchestrator.get_startup_orchestrator")
@patch("bootstrap.orchestrator.asyncio.Runner")
def test_run_startup_failure(mock_runner, mock_get_orch):
    mock_orch = MagicMock()
    mock_orch.startup.return_value = StartupStatus.FAILED
    mock_get_orch.return_value = mock_orch

    mock_runner_instance = MagicMock()
    mock_runner_instance.run.return_value = StartupStatus.FAILED
    mock_runner.return_value = mock_runner_instance

    result = run_startup()
    assert result is False


@patch("bootstrap.orchestrator.get_startup_orchestrator")
@patch("bootstrap.orchestrator.asyncio.Runner")
def test_run_startup_exception(mock_runner, mock_get_orch):
    mock_orch = MagicMock()
    mock_orch.startup.side_effect = Exception("unexpected")
    mock_get_orch.return_value = mock_orch

    mock_runner_instance = MagicMock()
    mock_runner_instance.run.side_effect = Exception("unexpected")
    mock_runner.return_value = mock_runner_instance

    result = run_startup()
    assert result is False


@patch("bootstrap.orchestrator.get_startup_orchestrator")
@patch("bootstrap.orchestrator.asyncio.Runner")
def test_shutdown_function(mock_runner, mock_get_orch):
    mock_orch = MagicMock()
    mock_get_orch.return_value = mock_orch
    mock_runner_instance = MagicMock()
    mock_runner.return_value = mock_runner_instance

    shutdown()
    mock_runner_instance.run.assert_called_once_with(mock_orch.shutdown())


@patch("bootstrap.orchestrator.get_startup_orchestrator")
def test_get_health_function(mock_get_orch):
    mock_orch = MagicMock()
    mock_orch.get_health_status.return_value = {"status": "healthy"}
    mock_get_orch.return_value = mock_orch
    result = get_health()
    assert result == {"status": "healthy"}


@patch("bootstrap.orchestrator.signal.signal")
def test_register_signal_handlers(mock_signal):
    register_signal_handlers()
    # signal.signal called twice: for SIGINT and SIGTERM
    assert mock_signal.call_count == 2


@patch("bootstrap.orchestrator._signal_handler")
@patch("bootstrap.orchestrator.signal.signal")
def test_signal_handler(mock_signal, mock_handler):
    # We need to test the handler indirectly by simulating signal
    # Just ensure the handler function exists and can be called
    from bootstrap.orchestrator import _signal_handler
    with patch("bootstrap.orchestrator.shutdown") as mock_shutdown:
        _signal_handler(signal.SIGINT, None)
        mock_shutdown.assert_called_once()


@patch("bootstrap.orchestrator.register_signal_handlers")
@patch("bootstrap.orchestrator.run_startup")
@patch("bootstrap.orchestrator.sys.exit")
def test_main(mock_exit, mock_run_startup, mock_register):
    mock_run_startup.return_value = True
    main()
    mock_register.assert_called_once()
    mock_run_startup.assert_called_once()
    mock_exit.assert_called_once_with(0)


@patch("bootstrap.orchestrator.register_signal_handlers")
@patch("bootstrap.orchestrator.run_startup")
@patch("bootstrap.orchestrator.sys.exit")
def test_main_failure(mock_exit, mock_run_startup, mock_register):
    mock_run_startup.return_value = False
    main()
    mock_exit.assert_called_once_with(1)


# -------------------- Additional integration-like tests --------------------
@patch("bootstrap.orchestrator.importlib.import_module")
@patch("bootstrap.orchestrator.os.environ")
def test_load_config_environment_fallback(mock_environ, mock_import, orchestrator):
    mock_environ.get.return_value = None
    mock_manager = MagicMock()
    mock_manager.load_all.return_value = {"database": {}}
    mock_manager.get_metadata.return_value = {"file_count": 1, "load_time_ms": 5}
    mock_import.return_value.get_config_manager.return_value = mock_manager
    result = orchestrator._load_config()
    assert result["environment"] == "development"
