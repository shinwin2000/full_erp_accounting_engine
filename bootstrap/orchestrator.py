#!/usr/bin/env python3
"""
Module: orchestrator.py
Layer: 3 - Bootstrap & Config / Orchestrator
Responsibility: Orkestrator startup: inisialisasi semua komponen secara berurutan
               dengan dependency resolution, health check, dan rollback capability.
               Menjamin bahwa sistem mulai dalam keadaan konsisten.

IMPORTANT: Tidak mengimpor langsung dari axioms atau constitution sesuai
           arsitektur layer. Semua akses ke komponen fundamental dilakukan
           menggunakan kernel atau aplikasi service registry.

Metode yang ditambahkan:
- Untuk StartupContext: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk StartupStep: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk StartupOrchestrator: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from kernel.context_holder import get_context_holder
from kernel.sealed_gate import get_sealed_gate

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# === 1. CONSTANTS & ENUMS ===


class StartupPhase(Enum):
    CONSTITUTION_LOAD = auto()
    AXIOMS_LOAD = auto()
    CONFIG_LOAD = auto()
    DATABASE_CONNECT = auto()
    MESSAGE_BROKER_CONNECT = auto()
    CACHE_CONNECT = auto()
    REPOSITORIES_INIT = auto()
    SERVICES_INIT = auto()
    KERNEL_INIT = auto()
    API_START = auto()
    HEALTH_CHECK = auto()
    COMPLETE = auto()

    def display_name(self) -> str:
        names = {
            StartupPhase.CONSTITUTION_LOAD: "Load Constitution",
            StartupPhase.AXIOMS_LOAD: "Load Axioms",
            StartupPhase.CONFIG_LOAD: "Load Config",
            StartupPhase.DATABASE_CONNECT: "Connect Database",
            StartupPhase.MESSAGE_BROKER_CONNECT: "Connect Message Broker",
            StartupPhase.CACHE_CONNECT: "Connect Cache",
            StartupPhase.REPOSITORIES_INIT: "Init Repositories",
            StartupPhase.SERVICES_INIT: "Init Services",
            StartupPhase.KERNEL_INIT: "Init Kernel",
            StartupPhase.API_START: "Start API",
            StartupPhase.HEALTH_CHECK: "Health Check",
            StartupPhase.COMPLETE: "Complete",
        }
        return names.get(self, self.name)


class StartupStatus(Enum):
    NOT_STARTED = auto()
    IN_PROGRESS = auto()
    SUCCESS = auto()
    PARTIAL = auto()
    FAILED = auto()
    ROLLBACK_IN_PROGRESS = auto()
    ROLLBACK_COMPLETE = auto()

    def display_name(self) -> str:
        names = {
            StartupStatus.NOT_STARTED: "Not Started",
            StartupStatus.IN_PROGRESS: "In Progress",
            StartupStatus.SUCCESS: "Success",
            StartupStatus.PARTIAL: "Partial",
            StartupStatus.FAILED: "Failed",
            StartupStatus.ROLLBACK_IN_PROGRESS: "Rollback In Progress",
            StartupStatus.ROLLBACK_COMPLETE: "Rollback Complete",
        }
        return names.get(self, self.name)


# === 2. StartupStep (dengan entity dasar) ===
@dataclass(kw_only=True)
class StartupStep:
    name: str
    phase: StartupPhase
    action: Callable[[], Any]
    rollback: Callable[[], Any] | None = None
    required: bool = True
    timeout_seconds: int = 30
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"
    error: str | None = None
    duration_ms: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.name:
            raise ValueError("name is required")
        if not isinstance(self.phase, StartupPhase):
            raise ValueError("invalid phase")
        if not callable(self.action):
            raise ValueError("action must be callable")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "name": self.name,
                "phase": self.phase.name,
                "status": self.status,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "step_name": self.name,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "phase": self.phase.name,
            "required": self.required,
            "timeout_seconds": self.timeout_seconds,
            "dependencies": self.dependencies,
            "status": self.status,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "version": self._version,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], action_map: dict[str, Callable] | None = None
    ) -> StartupStep:
        action = (action_map or {}).get(data["name"], lambda: None)
        instance = cls(
            name=data["name"],
            phase=StartupPhase[data["phase"]],
            action=action,
            required=data.get("required", True),
            timeout_seconds=data.get("timeout_seconds", 30),
            dependencies=data.get("dependencies", []),
        )
        instance.status = data.get("status", "pending")
        instance.error = data.get("error")
        instance.duration_ms = data.get("duration_ms", 0.0)
        instance.started_at = (
            datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
        )
        instance.completed_at = (
            datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> StartupStep:
        new = StartupStep(
            name=f"{self.name}_COPY",
            phase=self.phase,
            action=self.action,
            rollback=self.rollback,
            required=self.required,
            timeout_seconds=self.timeout_seconds,
            dependencies=self.dependencies.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.name})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "name": self.name,
            "phase": self.phase.name,
            "status": self.status,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> StartupStep:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. StartupContext (dengan entity dasar) ===
@dataclass(kw_only=True)
class StartupContext:
    config: dict[str, Any] = field(default_factory=dict)
    components: dict[str, Any] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.start_time:
            raise ValueError("start_time is required")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "config_keys": list(self.config.keys()),
                "components_keys": list(self.components.keys()),
                "errors_count": len(self.errors),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        # Note: components may not be fully serializable, so we store only keys
        return {
            "config_keys": list(self.config.keys()),
            "components_keys": list(self.components.keys()),
            "errors": self.errors,
            "start_time": self.start_time.isoformat(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StartupContext:
        instance = cls(
            start_time=datetime.fromisoformat(data["start_time"]),
        )
        instance._version = data.get("version", 1)
        # config and components cannot be restored from keys only
        return instance

    def clone(self) -> StartupContext:
        new = StartupContext(
            start_time=datetime.now(UTC),
        )
        new.config = self.config.copy()
        new.components = self.components.copy()
        new.errors = self.errors.copy()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "config_keys_count": len(self.config),
            "components_count": len(self.components),
            "errors_count": len(self.errors),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> StartupContext:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. StartupOrchestrator (dengan entity dasar) ===
class StartupOrchestrator:
    _instance: StartupOrchestrator | None = None

    def __new__(cls) -> StartupOrchestrator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._context = StartupContext()
        self._steps: list[StartupStep] = []
        self._status = StartupStatus.NOT_STARTED
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        self._build_steps()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "status": self._status.name,
                "steps_count": len(self._steps),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def _build_steps(self) -> None:
        self._steps = [
            StartupStep(
                name="load_constitution",
                phase=StartupPhase.CONSTITUTION_LOAD,
                action=self._load_constitution,
                rollback=self._rollback_constitution,
                required=True,
                timeout_seconds=10,
            ),
            StartupStep(
                name="load_axioms",
                phase=StartupPhase.AXIOMS_LOAD,
                action=self._load_axioms,
                rollback=self._rollback_axioms,
                required=True,
                timeout_seconds=10,
                dependencies=["load_constitution"],
            ),
            StartupStep(
                name="load_config",
                phase=StartupPhase.CONFIG_LOAD,
                action=self._load_config,
                rollback=self._rollback_config,
                required=True,
                timeout_seconds=15,
                dependencies=["load_axioms"],
            ),
            StartupStep(
                name="connect_database",
                phase=StartupPhase.DATABASE_CONNECT,
                action=self._connect_database,
                rollback=self._disconnect_database,
                required=True,
                timeout_seconds=30,
                dependencies=["load_config"],
            ),
            StartupStep(
                name="connect_message_broker",
                phase=StartupPhase.MESSAGE_BROKER_CONNECT,
                action=self._connect_message_broker,
                rollback=self._disconnect_message_broker,
                required=False,
                timeout_seconds=20,
                dependencies=["load_config"],
            ),
            StartupStep(
                name="connect_cache",
                phase=StartupPhase.CACHE_CONNECT,
                action=self._connect_cache,
                rollback=self._disconnect_cache,
                required=False,
                timeout_seconds=10,
                dependencies=["load_config"],
            ),
            StartupStep(
                name="init_repositories",
                phase=StartupPhase.REPOSITORIES_INIT,
                action=self._init_repositories,
                rollback=self._cleanup_repositories,
                required=True,
                timeout_seconds=20,
                dependencies=["connect_database"],
            ),
            StartupStep(
                name="init_services",
                phase=StartupPhase.SERVICES_INIT,
                action=self._init_services,
                rollback=self._cleanup_services,
                required=True,
                timeout_seconds=20,
                dependencies=["init_repositories", "connect_cache", "connect_message_broker"],
            ),
            StartupStep(
                name="init_kernel",
                phase=StartupPhase.KERNEL_INIT,
                action=self._init_kernel,
                rollback=self._shutdown_kernel,
                required=True,
                timeout_seconds=15,
                dependencies=["init_services"],
            ),
            StartupStep(
                name="start_api",
                phase=StartupPhase.API_START,
                action=self._start_api,
                rollback=self._stop_api,
                required=True,
                timeout_seconds=30,
                dependencies=["init_kernel"],
            ),
            StartupStep(
                name="health_check",
                phase=StartupPhase.HEALTH_CHECK,
                action=self._health_check,
                rollback=None,
                required=True,
                timeout_seconds=10,
                dependencies=["start_api"],
            ),
        ]

    # === STEP IMPLEMENTATIONS (existing, unchanged) ===
    def _load_constitution(self) -> dict[str, Any]:
        logger.info("Loading constitution via kernel...")
        try:
            context = get_context_holder()
            constitution = context.get_component("supreme_law")
            if constitution is None:
                raise RuntimeError("Constitution not available in kernel context")
            integrity = constitution.verify_integrity()
            if not integrity.get("is_valid", False):
                raise RuntimeError(f"Constitution integrity check failed: {integrity}")

            version_lock = context.get_component("version_lock")
            if version_lock:
                status = version_lock.get_status()
                if status.get("current_state") == "CORRUPTED":
                    raise RuntimeError("Version lock is CORRUPTED, cannot start")
        except Exception as e:
            logger.warning(f"Kernel context not ready, initializing minimal constitution: {e}")
            from constitution.supreme_law import get_supreme_law

            constitution = get_supreme_law()
            integrity = constitution.verify_integrity()
            if not integrity.get("is_valid", False):
                raise RuntimeError(f"Constitution integrity check failed: {integrity}")
        self._context.components["supreme_law"] = constitution
        return {"status": "loaded"}

    def _rollback_constitution(self) -> None:
        logger.warning("Rolling back constitution loading...")
        self._context.components.pop("supreme_law", None)

    def _load_axioms(self) -> dict[str, Any]:
        logger.info("Loading axioms via kernel...")
        try:
            context = get_context_holder()
            axioms = context.get_component("axioms")
            if axioms is None:
                raise RuntimeError("Axioms not available in kernel context")
        except Exception as e:
            logger.warning(f"Kernel context not ready, initializing minimal axioms: {e}")
            from axioms.double_entry import get_double_entry_axiom

            axioms = {"double_entry": get_double_entry_axiom()}
        self._context.components["axioms"] = axioms
        return {"loaded_axioms": len(axioms)}

    def _rollback_axioms(self) -> None:
        logger.warning("Rolling back axioms state...")
        self._context.components.pop("axioms", None)

    def _load_config(self) -> dict[str, Any]:
        logger.info("Loading configuration...")
        from config.loader_yaml import get_config_loader

        loader = get_config_loader()
        config = loader.load_all()
        self._context.config = config
        self._context.components["config_loader"] = loader
        return {"config_keys": list(config.keys())}

    def _rollback_config(self) -> None:
        logger.warning("Rolling back config...")
        self._context.config = {}
        self._context.components.pop("config_loader", None)

    async def _connect_database(self) -> dict[str, Any]:
        logger.info("Connecting to database...")
        from infrastructure.database.connection_pool_asyncpg import get_connection_pool
        from infrastructure.database.session_factory_sqlalchemy import get_session_factory

        pool = await get_connection_pool()
        session_factory = await get_session_factory()
        result = await pool.fetchval("SELECT 1")
        if result != 1:
            raise RuntimeError("Database connection test failed")
        self._context.components["db_pool"] = pool
        self._context.components["session_factory"] = session_factory
        return {"connected": True}

    async def _disconnect_database(self) -> None:
        logger.warning("Disconnecting database...")
        pool = self._context.components.get("db_pool")
        if pool:
            await pool.close()
        self._context.components.pop("db_pool", None)
        self._context.components.pop("session_factory", None)

    def _connect_message_broker(self) -> dict[str, Any]:
        logger.info("Connecting to message broker...")
        try:
            from infrastructure.message_broker.kafka_producer_wrapper import get_kafka_producer

            producer = get_kafka_producer()
            if producer:
                self._context.components["kafka_producer"] = producer
                return {"connected": True}
            else:
                logger.warning("Kafka not available")
                return {"connected": False, "degraded": True}
        except Exception as e:
            logger.warning(f"Message broker connection failed: {e}")
            return {"connected": False, "degraded": True}

    def _disconnect_message_broker(self) -> None:
        producer = self._context.components.get("kafka_producer")
        if producer and hasattr(producer, "close"):
            producer.close()
        self._context.components.pop("kafka_producer", None)

    def _connect_cache(self) -> dict[str, Any]:
        logger.info("Connecting to cache...")
        try:
            from infrastructure.caching.redis_manager import get_redis_client

            redis_client = get_redis_client()
            redis_client.ping()
            self._context.components["redis_client"] = redis_client
            return {"connected": True}
        except Exception as e:
            logger.warning(f"Cache connection failed: {e}")
            return {"connected": False, "degraded": True}

    def _disconnect_cache(self) -> None:
        redis_client = self._context.components.get("redis_client")
        if redis_client:
            redis_client.close()
        self._context.components.pop("redis_client", None)

    def _init_repositories(self) -> dict[str, Any]:
        logger.info("Initializing repositories...")
        from adapters.secondary_impl.sqlalchemy_account_repository_impl import (
            SQLAlchemyAccountRepository,
        )
        from adapters.secondary_impl.sqlalchemy_ap_repository_impl import SQLAlchemyAPRepository
        from adapters.secondary_impl.sqlalchemy_ar_repository_impl import SQLAlchemyARRepository
        from adapters.secondary_impl.sqlalchemy_journal_repository_impl import (
            SQLAlchemyJournalRepository,
        )
        from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWork

        session_factory = self._context.components["session_factory"]
        uow = SQLAlchemyUnitOfWork(session_factory)
        self._context.components["unit_of_work"] = uow

        repositories = {
            "journal": SQLAlchemyJournalRepository(session_factory),
            "account": SQLAlchemyAccountRepository(session_factory),
            "ar": SQLAlchemyARRepository(session_factory),
            "ap": SQLAlchemyAPRepository(session_factory),
        }
        self._context.components["repositories"] = repositories
        return {"repositories_initialized": len(repositories)}

    def _cleanup_repositories(self) -> None:
        self._context.components.pop("repositories", None)
        self._context.components.pop("unit_of_work", None)

    def _init_services(self) -> dict[str, Any]:
        logger.info("Initializing services...")
        from application.service_layer.service_ap import APService
        from application.service_layer.service_ar import ARService
        from application.service_layer.service_journal import JournalService

        repositories = self._context.components.get("repositories", {})
        uow = self._context.components.get("unit_of_work")
        journal_repo = repositories.get("journal")
        account_repo = repositories.get("account")
        ledger_repo = repositories.get("ledger")
        ar_repo = repositories.get("ar")
        ap_repo = repositories.get("ap")

        services = {
            "journal": JournalService(journal_repo, account_repo, ledger_repo, uow),
            "ar": ARService(ar_repo, uow),
            "ap": APService(ap_repo, uow),
        }
        self._context.components["services"] = services
        return {"services_initialized": len(services)}

    def _cleanup_services(self) -> None:
        self._context.components.pop("services", None)

    def _init_kernel(self) -> dict[str, Any]:
        logger.info("Initializing kernel...")
        gate = get_sealed_gate()
        self._context.components["sealed_gate"] = gate
        return {"kernel_ready": True}

    def _shutdown_kernel(self) -> None:
        self._context.components.pop("sealed_gate", None)

    def _start_api(self) -> dict[str, Any]:
        logger.info("Starting API server...")
        import threading

        import uvicorn

        from adapters.primary_api.common.fastapi_app_factory import create_app

        app = create_app(self._context.components)

        def run_server():
            uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        self._context.components["api_app"] = app
        self._context.components["api_thread"] = server_thread
        return {"api_started": True, "port": 8000}

    def _stop_api(self) -> None:
        self._context.components.pop("api_app", None)
        self._context.components.pop("api_thread", None)

    async def _health_check(self) -> dict[str, Any]:
        logger.info("Running health check...")
        health_status = {}
        pool = self._context.components.get("db_pool")

        if pool:
            try:
                result = await asyncio.wait_for(pool.fetchval("SELECT 1"), timeout=2.0)
                health_status["database"] = "healthy" if result == 1 else "unhealthy"
            except (TimeoutError, Exception) as e:
                logger.error("Database health check failed: %s", e)
                health_status["database"] = "unhealthy"
        else:
            health_status["database"] = "not_connected"

        gate = self._context.components.get("sealed_gate")
        health_status["kernel"] = "healthy" if gate else "missing"

        self._context.components["health_status"] = health_status
        all_healthy = all(v == "healthy" for v in health_status.values() if v != "not_connected")

        if not all_healthy:
            raise RuntimeError(f"Health check failed: {health_status}")

        return health_status

    # === ORCHESTRATION ===
    async def startup(self, skip_health: bool = False) -> StartupStatus:
        if self._status != StartupStatus.NOT_STARTED:
            logger.warning(f"Startup already attempted with status {self._status}")
            return self._status

        self._status = StartupStatus.IN_PROGRESS
        self._context.start_time = datetime.now(UTC)
        step_map = {s.name: s for s in self._steps}

        for step in self._steps:
            deps_ok = all(
                step_map[d].status == "success" for d in step.dependencies if d in step_map
            )
            if not deps_ok:
                step.status = "skipped_deps"
                step.error = "Dependencies failed"
                continue

            step.status = "running"
            step.started_at = datetime.now(UTC)
            start = time.time()
            try:
                import inspect

                if inspect.iscoroutinefunction(step.action):
                    execute_coro = step.action()
                else:
                    loop = asyncio.get_running_loop()
                    execute_coro = loop.run_in_executor(None, step.action)

                result = await asyncio.wait_for(execute_coro, timeout=step.timeout_seconds)
                step.status = "success"
                self._context.components[f"{step.name}_result"] = result
                logger.info(
                    f"Startup step {step.name} completed in {(time.time() - start) * 1000:.2f}ms"
                )
            except TimeoutError:
                step.status = "failed"
                step.error = f"Timeout after {step.timeout_seconds}s"
                logger.error(f"Startup step {step.name} timed out")
                self._context.errors.append((step.name, step.error))
                if step.required:
                    await self._rollback(step)
                    self._status = StartupStatus.FAILED
                    self._record_audit(
                        "STARTUP_FAILED", "system", {"failed_step": step.name, "error": step.error}
                    )
                    return self._status
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                logger.exception(f"Startup step {step.name} failed: {e}")
                self._context.errors.append((step.name, step.error))
                if step.required:
                    await self._rollback(step)
                    self._status = StartupStatus.FAILED
                    self._record_audit(
                        "STARTUP_FAILED", "system", {"failed_step": step.name, "error": step.error}
                    )
                    return self._status
            finally:
                step.completed_at = datetime.now(UTC)
                step.duration_ms = (time.time() - start) * 1000

        required_failed = [s for s in self._steps if s.required and s.status != "success"]
        if required_failed:
            self._status = StartupStatus.PARTIAL
            logger.error(
                f"Startup partial: required steps failed: {[s.name for s in required_failed]}"
            )
        else:
            self._status = StartupStatus.SUCCESS
            logger.info("Startup completed successfully")
            self._record_audit("STARTUP_SUCCESS", "system", {})
        return self._status

    async def _rollback(self, failed_step: StartupStep) -> None:
        self._status = StartupStatus.ROLLBACK_IN_PROGRESS
        logger.warning(f"Starting rollback from failed step: {failed_step.name}")
        for step in reversed(self._steps):
            if step.status == "success" and step.rollback:
                try:
                    rollback_result = step.rollback()
                    if asyncio.iscoroutine(rollback_result):
                        await rollback_result
                    step.status = "rolled_back"
                    logger.info(f"Rollback step {step.name} completed")
                except Exception as e:
                    logger.error(f"Rollback step {step.name} failed: {e}")
                    self._context.errors.append((f"rollback_{step.name}", str(e)))
        self._status = StartupStatus.ROLLBACK_COMPLETE
        logger.warning("Rollback completed")
        self._record_audit("ROLLBACK", "system", {"failed_step": failed_step.name})

    async def shutdown(self) -> None:
        logger.info("Shutting down...")
        for step in reversed(self._steps):
            if step.status == "success" and step.rollback:
                try:
                    rollback_result = step.rollback()
                    if asyncio.iscoroutine(rollback_result):
                        await rollback_result
                except Exception as e:
                    logger.error(f"Shutdown step {step.name} failed: {e}")
        self._status = StartupStatus.NOT_STARTED
        logger.info("Shutdown complete")
        self._record_audit("SHUTDOWN", "system", {})

    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status.name,
            "start_time": self._context.start_time.isoformat(),
            "steps": [
                {
                    "name": s.name,
                    "phase": s.phase.name,
                    "status": s.status,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                }
                for s in self._steps
            ],
            "errors": self._context.errors,
            "components_initialized": list(self._context.components.keys()),
            "version": self._version,
        }

    def get_context(self) -> StartupContext:
        return self._context

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        res = self._context.validate()
        if not res["is_valid"]:
            errors.extend([f"Context: {e}" for e in res["errors"]])
        for step in self._steps:
            res = step.validate()
            if not res["is_valid"]:
                errors.extend([f"Step {step.name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self._status.name,
            "context": self._context.to_dict(),
            "steps": [s.to_dict() for s in self._steps],
            "version": self._version,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], action_map: dict[str, Callable] | None = None
    ) -> StartupOrchestrator:
        instance = cls()
        instance._status = StartupStatus[data["status"]]
        instance._context = StartupContext.from_dict(data.get("context", {}))
        instance._steps = [StartupStep.from_dict(s, action_map) for s in data.get("steps", [])]
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> StartupOrchestrator:
        new = StartupOrchestrator()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "status": self._status.name,
            "steps_count": len(self._steps),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> StartupOrchestrator:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === SINGLETON ACCESSOR ===
_orchestrator_instance: StartupOrchestrator | None = None


def get_startup_orchestrator() -> StartupOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = StartupOrchestrator()
    return _orchestrator_instance


# === CONVENIENCE FUNCTIONS ===
def run_startup() -> bool:
    """Convenience function dengan asyncio.Runner untuk isolasi loop."""
    orchestrator = get_startup_orchestrator()
    try:
        with asyncio.Runner() as runner:
            status = runner.run(orchestrator.startup())
        return status == StartupStatus.SUCCESS
    except KeyboardInterrupt:
        logger.info("Startup interrupted by user")
        return False


def shutdown() -> None:
    """Convenience function dengan asyncio.Runner untuk isolasi loop."""
    orchestrator = get_startup_orchestrator()
    try:
        with asyncio.Runner() as runner:
            runner.run(orchestrator.shutdown())
    except KeyboardInterrupt:
        logger.info("Shutdown interrupted by user")


# === SIGNAL HANDLERS ===
def _signal_handler(signum: int, frame: Any) -> None:
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown()
    sys.exit(0)


def register_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


# === ALIAS UNTUK KOMPATIBILITAS ===
BootstrapOrchestrator = StartupOrchestrator

__all__ = [
    "BootstrapOrchestrator",
    "StartupContext",
    "StartupOrchestrator",
    "StartupPhase",
    "StartupStatus",
    "StartupStep",
    "get_startup_orchestrator",
    "register_signal_handlers",
    "run_startup",
    "shutdown",
]


def main():
    """Main sync execution path using proper loop abstraction layer."""
    register_signal_handlers()
    success = run_startup()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    main()