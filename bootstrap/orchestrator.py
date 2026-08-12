#!/usr/bin/env python3
"""
Module: orchestrator.py
Layer: 3 - Bootstrap & Config / Orchestrator
Responsibility: Orkestrator startup lengkap dengan:
               - Inisialisasi semua komponen secara berurutan
               - Dependency resolution
               - Health check komprehensif (DB, Redis, Kafka, Encryption, Disk, Services)
               - Rollback capability
               - Validasi post-startup
               - Menjamin sistem konsisten dan siap produksi
               - Menggunakan ConfigManager singleton untuk semua konfigurasi
               - Menyediakan endpoint health check di API (/health, /health/ready, /health/live)
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import os
import shutil
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any

# ============================================================
# Tambahkan root proyek ke sys.path
# ============================================================
_root_path = Path(__file__).parent.parent
if str(_root_path) not in sys.path:
    sys.path.insert(0, str(_root_path))

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


# === 2. StartupStep ===
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


# === 3. StartupContext ===
@dataclass(kw_only=True)
class StartupContext:
    config: dict[str, Any] = field(default_factory=dict)
    components: dict[str, Any] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))

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

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
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


# === 4. StartupOrchestrator ===
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
        self._background_tasks: list[asyncio.Task] = []  # track background tasks for shutdown
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
                timeout_seconds=90,
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
                timeout_seconds=120,
                dependencies=["init_kernel"],
            ),
            StartupStep(
                name="health_check",
                phase=StartupPhase.HEALTH_CHECK,
                action=self._health_check,
                rollback=None,
                required=True,
                timeout_seconds=15,
                dependencies=["start_api"],
            ),
        ]

    # ============================================================
    # STEP IMPLEMENTATIONS
    # ============================================================

    def _load_constitution(self) -> dict[str, Any]:
        logger.info("Loading constitution directly from constitution.supreme_law...")
        try:
            supreme_law_mod = importlib.import_module("constitution.supreme_law")
            get_supreme_law = supreme_law_mod.get_supreme_law
            constitution = get_supreme_law()
            if constitution is None:
                raise RuntimeError("get_supreme_law() returned None")
            integrity = constitution.verify_integrity()
            if not integrity.get("is_valid", False):
                raise RuntimeError(f"Constitution integrity check failed: {integrity}")
            self._context.components["supreme_law"] = constitution
            logger.info(f"Constitution loaded and verified successfully (version={integrity.get('version', 'unknown')})")
            return {"status": "loaded", "version": integrity.get("version", "unknown")}
        except Exception as e:
            logger.error(f"Failed to load constitution: {e}")
            raise

    def _rollback_constitution(self) -> None:
        logger.warning("Rolling back constitution loading...")
        self._context.components.pop("supreme_law", None)

    def _load_axioms(self) -> dict[str, Any]:
        logger.info("Loading axioms directly from axioms.double_entry...")
        try:
            double_entry_mod = importlib.import_module("axioms.double_entry")
            get_double_entry = double_entry_mod.get_double_entry_axiom
            axiom = get_double_entry()
            if axiom is None:
                raise RuntimeError("get_double_entry_axiom() returned None")
            self._context.components["axioms"] = {"double_entry": axiom}
            logger.info("Double-entry axiom loaded successfully")
            return {"loaded_axioms": 1}
        except Exception as e:
            logger.error(f"Failed to load axioms: {e}")
            raise

    def _rollback_axioms(self) -> None:
        logger.warning("Rolling back axioms state...")
        self._context.components.pop("axioms", None)

    def _load_config(self) -> dict[str, Any]:
        logger.info("Loading configuration using ConfigManager...")
        try:
            config_manager_mod = importlib.import_module("config.manager")
            get_manager = config_manager_mod.get_config_manager
            manager = get_manager()
            config = manager.load_all()
            if not config:
                raise RuntimeError("Loaded config is empty")
            self._context.components["config_manager"] = manager
            self._context.config = config
            metadata = manager.get_metadata()
            env = os.environ.get("ENVIRONMENT")
            if not env and "environment" in config:
                env = config["environment"]
            if not env and "app" in config and "environment" in config["app"]:
                env = config["app"]["environment"]
            if not env:
                env = "development"
            logger.info(
                f"Config loaded with {len(config)} top-level keys from "
                f"{metadata.get('file_count', 0)} files in {metadata.get('load_time_ms', 0):.2f}ms"
            )
            logger.info(f"Current environment: {env}")
            required_sections = ["database"]
            for section in required_sections:
                if section not in config:
                    raise RuntimeError(f"Missing required section '{section}' in configuration")
            optional_sections = ["kafka", "redis", "cache", "logging"]
            for section in optional_sections:
                if section not in config:
                    logger.info(f"Optional section '{section}' not found in configuration (ok)")
            return {
                "config_keys": list(config.keys()),
                "environment": env,
                "file_count": metadata.get("file_count", 0),
                "load_time_ms": metadata.get("load_time_ms", 0),
            }
        except ImportError as e:
            logger.error(f"ConfigManager module not found: {e}")
            raise RuntimeError("config.manager is required for startup") from e
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise

    def _rollback_config(self) -> None:
        logger.warning("Rolling back config...")
        self._context.config = {}
        self._context.components.pop("config_manager", None)

    async def _connect_database(self) -> dict[str, Any]:
        logger.info("Connecting to database...")
        try:
            config_manager = self._context.components.get("config_manager")
            if config_manager is None:
                raise RuntimeError("ConfigManager not available in context")
            db_config = config_manager.get_section("database")
            if not db_config:
                raise RuntimeError("Database configuration is empty or missing")
            pool_mod = importlib.import_module("infrastructure.database.connection_pool_asyncpg")
            session_mod = importlib.import_module("infrastructure.database.session_factory_sqlalchemy")
            get_pool = pool_mod.get_connection_pool
            get_session = session_mod.get_session_factory
            sig_pool = inspect.signature(get_pool)
            accepts_config_pool = "config" in sig_pool.parameters
            sig_session = inspect.signature(get_session)
            accepts_config_session = "config" in sig_session.parameters
            if inspect.iscoroutinefunction(get_pool):
                if accepts_config_pool:
                    pool = await get_pool(db_config)
                else:
                    pool = await get_pool()
            else:
                if accepts_config_pool:
                    pool = get_pool(db_config)
                else:
                    pool = get_pool()
            if inspect.iscoroutinefunction(get_session):
                if accepts_config_session:
                    session_factory = await get_session(db_config)
                else:
                    session_factory = await get_session()
            else:
                if accepts_config_session:
                    session_factory = get_session(db_config)
                else:
                    session_factory = get_session()
            result = await pool.fetchval("SELECT 1")
            if result != 1:
                raise RuntimeError("Database connection test failed (SELECT 1 returned unexpected)")
            self._context.components["db_pool"] = pool
            self._context.components["session_factory"] = session_factory
            dsn = db_config.get("url") or db_config.get("dsn") or "postgresql://... (hidden)"
            logger.info(f"Database connected successfully: {dsn}")
            return {"connected": True, "dsn": dsn}
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    async def _disconnect_database(self) -> None:
        logger.warning("Disconnecting database...")
        pool = self._context.components.get("db_pool")
        if pool and hasattr(pool, "close"):
            try:
                await pool.close()
                logger.info("Database pool closed")
            except Exception as e:
                logger.warning(f"Error closing database pool: {e}")
        self._context.components.pop("db_pool", None)
        self._context.components.pop("session_factory", None)

    def _connect_message_broker(self) -> dict[str, Any]:
        logger.info("Connecting to message broker...")
        try:
            config_manager = self._context.components.get("config_manager")
            kafka_config = config_manager.get_section("kafka") if config_manager else {}
            kafka_mod = importlib.import_module(
                "infrastructure.message_broker.kafka_producer_wrapper"
            )
            get_producer = kafka_mod.get_kafka_producer
            sig = inspect.signature(get_producer)
            if "config" in sig.parameters:
                producer = get_producer(kafka_config)
            else:
                producer = get_producer()
            if producer:
                bootstrap = None
                if hasattr(producer, "bootstrap_servers"):
                    bootstrap = producer.bootstrap_servers
                elif "bootstrap_servers" in kafka_config:
                    bootstrap = kafka_config["bootstrap_servers"]
                else:
                    bootstrap = "unknown"
                logger.info(f"Kafka producer connected to: {bootstrap}")
                self._context.components["kafka_producer"] = producer
                return {"connected": True, "broker": bootstrap}
            else:
                logger.warning("Kafka producer returned None — degraded mode")
                return {"connected": False, "degraded": True, "reason": "producer_none"}
        except ImportError as e:
            logger.info(f"Kafka module not found: {e} — degraded mode")
            return {"connected": False, "degraded": True, "reason": "module_missing"}
        except Exception as e:
            logger.warning(f"Message broker connection failed: {e} — degraded mode")
            return {"connected": False, "degraded": True, "reason": str(e)}

    def _disconnect_message_broker(self) -> None:
        producer = self._context.components.get("kafka_producer")
        if producer and hasattr(producer, "close"):
            try:
                producer.close()
                logger.info("Kafka producer closed")
            except Exception as e:
                logger.warning(f"Error closing Kafka producer: {e}")
        self._context.components.pop("kafka_producer", None)

    async def _connect_cache(self) -> dict[str, Any]:
        logger.info("Connecting to cache (Redis)...")
        try:
            config_manager = self._context.components.get("config_manager")
            redis_config = config_manager.get_section("redis") or config_manager.get_section("cache") or {}
            redis_mod = importlib.import_module("infrastructure.caching.redis_manager")
            get_redis = redis_mod.get_redis_client
            sig = inspect.signature(get_redis)
            if "config" in sig.parameters:
                if inspect.iscoroutinefunction(get_redis):
                    redis_client = await get_redis(redis_config)
                else:
                    redis_client = get_redis(redis_config)
            else:
                if inspect.iscoroutinefunction(get_redis):
                    redis_client = await get_redis()
                else:
                    redis_client = get_redis()
            if hasattr(redis_client, "ping"):
                await redis_client.ping()
            host = redis_config.get("host", "localhost")
            port = redis_config.get("port", 6379)
            logger.info(f"Redis connected to {host}:{port}")
            self._context.components["redis_client"] = redis_client
            return {"connected": True, "host": host, "port": port}
        except Exception as e:
            logger.warning(f"Cache connection failed: {e} — degraded mode")
            return {"connected": False, "degraded": True, "reason": str(e)}

    async def _disconnect_cache(self) -> None:
        redis_client = self._context.components.get("redis_client")
        if redis_client:
            try:
                if hasattr(redis_client, "aclose"):
                    await redis_client.aclose()
                elif hasattr(redis_client, "close"):
                    if inspect.iscoroutinefunction(redis_client.close):
                        await redis_client.close()
                    else:
                        redis_client.close()
                logger.info("Redis client closed")
            except Exception as e:
                logger.warning(f"Error closing Redis client: {e}")
        self._context.components.pop("redis_client", None)

    def _init_repositories(self) -> dict[str, Any]:
        logger.info("Initializing repositories...")
        session_factory = self._context.components.get("session_factory")
        if session_factory is None:
            raise RuntimeError("Session factory not available, cannot initialize repositories")
        repositories = {}
        uow = None
        try:
            uow_mod = importlib.import_module("adapters.secondary_impl.sqlalchemy_unit_of_work_impl")
            SQLAlchemyUnitOfWork = uow_mod.SQLAlchemyUnitOfWork
            uow = SQLAlchemyUnitOfWork(session_factory)
            self._context.components["unit_of_work"] = uow
            logger.info("UnitOfWork initialized")
        except Exception as e:
            logger.error(f"UnitOfWork initialization failed: {e}")
            raise
        def init_repo(module_path: str, class_name: str, repo_name: str):
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                repo = cls(session_factory)
                logger.debug(f"Repository {repo_name} initialized")
                return repo
            except Exception as e:
                logger.error(f"Failed to init repository {repo_name} ({class_name}): {e}")
                raise
        repositories["journal"] = init_repo(
            "adapters.secondary_impl.sqlalchemy_journal_repository_impl",
            "SQLAlchemyJournalRepository",
            "journal"
        )
        repositories["account"] = init_repo(
            "adapters.secondary_impl.sqlalchemy_account_repository_impl",
            "SQLAlchemyAccountRepository",
            "account"
        )
        repositories["ar"] = init_repo(
            "adapters.secondary_impl.sqlalchemy_ar_repository_impl",
            "SQLAlchemyARRepository",
            "ar"
        )
        repositories["ap"] = init_repo(
            "adapters.secondary_impl.sqlalchemy_ap_repository_impl",
            "SQLAlchemyAPRepository",
            "ap"
        )
        repositories["ledger"] = init_repo(
            "adapters.secondary_impl.sqlalchemy_ledger_repository_impl",
            "SQLAlchemyLedgerRepository",
            "ledger"
        )
        self._context.components["repositories"] = repositories
        logger.info(f"All {len(repositories)} repositories initialized successfully")
        return {"repositories_initialized": len(repositories)}

    def _cleanup_repositories(self) -> None:
        logger.warning("Cleaning up repositories...")
        self._context.components.pop("repositories", None)
        self._context.components.pop("unit_of_work", None)

    def _init_services(self) -> dict[str, Any]:
        logger.info("Initializing services...")
        repositories = self._context.components.get("repositories")
        uow = self._context.components.get("unit_of_work")
        if repositories is None or uow is None:
            raise RuntimeError("Repositories or UOW not available")
        required_repos = ["journal", "account", "ledger", "ar", "ap"]
        for repo_name in required_repos:
            if repo_name not in repositories or repositories[repo_name] is None:
                raise RuntimeError(f"Required repository '{repo_name}' is missing or None")
        services = {}
        try:
            ap_mod = importlib.import_module("application.service_layer.service_ap")
            ar_mod = importlib.import_module("application.service_layer.service_ar")
            journal_mod = importlib.import_module("application.service_layer.service_journal")
            APService = ap_mod.APService
            ARService = ar_mod.ARService
            JournalService = journal_mod.JournalService
            services["journal"] = JournalService(
                repositories["journal"],
                repositories["account"],
                repositories["ledger"],
                uow
            )
            logger.info("JournalService initialized")
            services["ar"] = ARService(repositories["ar"], uow)
            logger.info("ARService initialized")
            services["ap"] = APService(repositories["ap"], uow)
            logger.info("APService initialized")
            self._context.components["services"] = services
            return {"services_initialized": len(services)}
        except Exception as e:
            logger.error(f"Service initialization failed: {e}")
            raise

    def _cleanup_services(self) -> None:
        logger.warning("Cleaning up services...")
        self._context.components.pop("services", None)

    def _init_kernel(self) -> dict[str, Any]:
        logger.info("Initializing kernel...")
        try:
            gate_mod = importlib.import_module("kernel.sealed_gate")
            get_gate = gate_mod.get_sealed_gate
            gate = get_gate()
            if gate is None:
                raise RuntimeError("Sealed gate returned None")
            self._context.components["sealed_gate"] = gate
            is_sealed = gate.is_sealed() if hasattr(gate, "is_sealed") else False
            logger.info(f"Kernel sealed_gate initialized (sealed={is_sealed})")
            return {"kernel_ready": True, "sealed": is_sealed}
        except Exception as e:
            logger.error(f"Kernel initialization failed: {e}")
            raise

    def _shutdown_kernel(self) -> None:
        logger.warning("Shutting down kernel...")
        self._context.components.pop("sealed_gate", None)

    async def _start_api(self) -> dict[str, Any]:
        logger.info("Starting API server...")
        import threading
        try:
            import uvicorn
            from fastapi import FastAPI, Response

            # Dapatkan config manager untuk mengambil config yang sudah dimuat
            config_manager = self._context.components.get("config_manager")
            if config_manager is None:
                raise RuntimeError("ConfigManager not available in context")

            # Persiapkan config untuk factory
            factory_config = self._context.config.copy()

            # ===== 1. Pastikan database config memiliki 'dsn' dengan driver asyncpg =====
            db_cfg = factory_config.get("database", {})
            if "dsn" not in db_cfg:
                if "url" in db_cfg:
                    dsn = db_cfg["url"]
                elif "connection_string" in db_cfg:
                    dsn = db_cfg["connection_string"]
                else:
                    host = db_cfg.get("host", "localhost")
                    port = db_cfg.get("port", 5432)
                    dbname = db_cfg.get("db", "erp_db")
                    user = db_cfg.get("user", "postgres")
                    password = db_cfg.get("password", "")
                    if password:
                        dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
                    else:
                        dsn = f"postgresql://{user}@{host}:{port}/{dbname}"
                db_cfg["dsn"] = dsn

            # Pastikan menggunakan asyncpg
            dsn = db_cfg["dsn"]
            if dsn.startswith("postgresql://") and "+asyncpg" not in dsn:
                dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
                db_cfg["dsn"] = dsn
                logger.info(f"Converted DSN to asyncpg: {dsn.replace('://', '://...')}")
            elif dsn.startswith("postgresql+asyncpg://"):
                logger.info("DSN already using asyncpg driver")
            else:
                # Fallback: force asyncpg
                if "postgresql" in dsn:
                    dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
                    db_cfg["dsn"] = dsn
                    logger.info(f"Forced DSN to asyncpg: {dsn.replace('://', '://...')}")

            factory_config["database"] = db_cfg

            # ===== 2. Pastikan security config ada =====
            sec_cfg = factory_config.get("security", {})
            if "jwt_secret" not in sec_cfg:
                sec_cfg["jwt_secret"] = os.environ.get("JWT_SECRET", "dev_secret_change_me")
                logger.info("Using default JWT secret (set env JWT_SECRET to override)")
            if "encryption_key" not in sec_cfg:
                sec_cfg["encryption_key"] = os.environ.get("ENCRYPTION_KEY", "default_encryption_key_32_bytes!!")
                logger.info("Using default encryption key (set env ENCRYPTION_KEY to override)")
            factory_config["security"] = sec_cfg

            # ===== 3. Pastikan kafka config ada =====
            kafka_cfg = factory_config.get("kafka", {})
            if "bootstrap_servers" not in kafka_cfg:
                kafka_cfg["bootstrap_servers"] = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
                logger.info("Using default Kafka bootstrap servers (set env KAFKA_BOOTSTRAP_SERVERS to override)")
            factory_config["kafka"] = kafka_cfg

            # ===== 4. Pastikan redis config ada =====
            redis_cfg = factory_config.get("redis", {})
            if "host" not in redis_cfg:
                redis_cfg["host"] = os.environ.get("REDIS_HOST", "localhost")
                redis_cfg["port"] = int(os.environ.get("REDIS_PORT", 6379))
                logger.info("Using default Redis config (set env REDIS_HOST/REDIS_PORT to override)")
            factory_config["redis"] = redis_cfg

            # ===== 5. Coretax config opsional =====
            coretax_cfg = factory_config.get("coretax", {})
            if not coretax_cfg:
                coretax_cfg = {
                    "base_url": os.environ.get("CORETAX_BASE_URL", "https://api.coretax.djp.go.id"),
                    "client_id": os.environ.get("CORETAX_CLIENT_ID", "dev_client"),
                    "client_secret": os.environ.get("CORETAX_CLIENT_SECRET", "dev_secret"),
                }
                factory_config["coretax"] = coretax_cfg
                logger.info("Using default Coretax config (set env CORETAX_* to override)")

            # ===== 6. Panggil factory =====
            app_mod = importlib.import_module("adapters.primary_api.common.fastapi_app_factory")
            create_app = app_mod.create_app

            if inspect.iscoroutinefunction(create_app):
                container = await create_app(factory_config)
            else:
                container = create_app(factory_config)

            # Buat FastAPI app
            app = FastAPI(
                title="ERP Accounting Engine",
                description="Enterprise Resource Planning Accounting System",
                version="1.0.0",
            )

            # Tambahkan endpoint health check
            @app.get("/health", tags=["health"])
            async def health_check():
                health = self.get_health_status()
                if health and health.get("overall") == "healthy":
                    return {"status": "healthy", "checks": health.get("checks", {})}
                elif health and health.get("overall") == "degraded":
                    return Response(
                        content=json.dumps({
                            "status": "degraded",
                            "checks": health.get("checks", {}),
                            "warnings": health.get("warnings", [])
                        }),
                        status_code=200,
                        media_type="application/json"
                    )
                else:
                    return Response(
                        content=json.dumps({
                            "status": "unhealthy",
                            "checks": health.get("checks", {}) if health else {},
                            "errors": health.get("errors", []) if health else []
                        }),
                        status_code=503,
                        media_type="application/json"
                    )

            @app.get("/health/ready", tags=["health"])
            async def readiness_check():
                health = self.get_health_status()
                if health and health.get("overall") in ("healthy", "degraded"):
                    return {"ready": True, "status": health.get("overall")}
                else:
                    return Response(
                        content=json.dumps({"ready": False, "status": health.get("overall") if health else "unknown"}),
                        status_code=503,
                        media_type="application/json"
                    )

            @app.get("/health/live", tags=["health"])
            async def liveness_check():
                return {"alive": True, "uptime": str(datetime.now(UTC) - self._context.start_time)}

            # Jika container memiliki router, tambahkan
            if "router" in container:
                app.include_router(container["router"])
            else:
                from fastapi import APIRouter
                api_router = APIRouter(prefix="/api/v1")
                @api_router.get("/ping")
                async def ping():
                    return {"message": "pong"}
                app.include_router(api_router)

            # Simpan container untuk shutdown
            self._context.components["app_container"] = container

            def run_server():
                try:
                    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
                except Exception as e:
                    logger.error(f"Uvicorn server error: {e}")

            server_thread = threading.Thread(target=run_server, daemon=True, name="APIServerThread")
            server_thread.start()
            self._context.components["api_app"] = app
            self._context.components["api_thread"] = server_thread
            logger.info("API server thread started on port 8000")
            return {"api_started": True, "port": 8000}
        except Exception as e:
            logger.error(f"API startup failed: {e}")
            raise RuntimeError(f"Unable to create API app: {e}") from e

    def _stop_api(self) -> None:
        logger.warning("Stopping API server...")
        container = self._context.components.get("app_container")
        if container and hasattr(container, "shutdown"):
            try:
                if inspect.iscoroutinefunction(container.shutdown):
                    # Store task in background tasks list to be awaited during shutdown
                    shutdown_task = asyncio.create_task(container.shutdown())
                    self._background_tasks.append(shutdown_task)
                    logger.info("Application container shutdown task created")
                else:
                    container.shutdown()
                    logger.info("Application container shutdown completed synchronously")
            except Exception as e:
                logger.warning(f"Error during container shutdown: {e}")
        self._context.components.pop("api_app", None)
        self._context.components.pop("api_thread", None)

    async def _health_check(self) -> dict[str, Any]:
        logger.info("Running comprehensive health check...")
        health_status = {
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": {},
            "overall": "healthy"
        }
        warnings = []
        errors = []

        # 1. Database
        pool = self._context.components.get("db_pool")
        if pool is None:
            errors.append("Database pool is None")
            health_status["checks"]["database"] = {"status": "critical", "detail": "not_connected"}
        else:
            try:
                if hasattr(pool, "fetchval"):
                    result = await asyncio.wait_for(pool.fetchval("SELECT 1"), timeout=2.0)
                    status = "healthy" if result == 1 else "unhealthy"
                    health_status["checks"]["database"] = {"status": status, "detail": "query_ok" if status == "healthy" else "query_failed"}
                    if status != "healthy":
                        errors.append("Database query returned unexpected result")
                else:
                    health_status["checks"]["database"] = {"status": "unknown", "detail": "mock_pool"}
                    warnings.append("Database pool is mock, not fully tested")
            except TimeoutError:
                errors.append("Database health check timeout")
                health_status["checks"]["database"] = {"status": "critical", "detail": "timeout"}
            except Exception as e:
                errors.append(f"Database health check failed: {e}")
                health_status["checks"]["database"] = {"status": "critical", "detail": str(e)}

        # 2. Kernel
        gate = self._context.components.get("sealed_gate")
        if gate is None:
            errors.append("Kernel gate is None")
            health_status["checks"]["kernel"] = {"status": "critical", "detail": "missing"}
        else:
            is_sealed = gate.is_sealed() if hasattr(gate, "is_sealed") else False
            health_status["checks"]["kernel"] = {"status": "healthy", "detail": f"sealed={is_sealed}"}

        # 3. Redis
        redis_client = self._context.components.get("redis_client")
        if redis_client:
            try:
                if hasattr(redis_client, "ping"):
                    await redis_client.ping()
                    health_status["checks"]["cache"] = {"status": "healthy", "detail": "ping_ok"}
                else:
                    health_status["checks"]["cache"] = {"status": "unknown", "detail": "no_ping_method"}
                    warnings.append("Redis client has no ping method")
            except Exception as e:
                health_status["checks"]["cache"] = {"status": "degraded", "detail": str(e)}
                warnings.append(f"Redis ping failed: {e}")
        else:
            health_status["checks"]["cache"] = {"status": "not_connected", "detail": "redis_not_configured"}

        # 4. Kafka
        kafka_producer = self._context.components.get("kafka_producer")
        if kafka_producer:
            try:
                bootstrap = getattr(kafka_producer, "bootstrap_servers", "unknown")
                health_status["checks"]["broker"] = {"status": "healthy", "detail": f"connected_to_{bootstrap}"}
            except Exception as e:
                health_status["checks"]["broker"] = {"status": "degraded", "detail": str(e)}
                warnings.append(f"Kafka producer check failed: {e}")
        else:
            health_status["checks"]["broker"] = {"status": "not_connected", "detail": "kafka_not_configured"}

        # 5. Encryption menggunakan KeyManager
        try:
            from infrastructure.security.key_management import get_key_manager
            km = get_key_manager()
            keys = km.list_keys()
            if keys:
                current = km.get_current_key_id()
                detail = f"keys_available({len(keys)}), current={current}"
                if len(keys) == 1 and keys[0]['key_id'] == 'default' and not keys[0].get('metadata', {}).get('source'):
                    warnings.append("Using ephemeral encryption key — NOT SUITABLE FOR PRODUCTION!")
                    detail += " (EPHEMERAL/WARNING)"
                health_status["checks"]["encryption"] = {"status": "healthy", "detail": detail}
            else:
                health_status["checks"]["encryption"] = {"status": "degraded", "detail": "no_keys_found"}
                warnings.append("No encryption keys found — data at risk!")
        except ImportError:
            health_status["checks"]["encryption"] = {"status": "not_available", "detail": "key_management_module_missing"}
            warnings.append("KeyManager module not available")
        except Exception as e:
            health_status["checks"]["encryption"] = {"status": "degraded", "detail": str(e)}
            warnings.append(f"Encryption check error: {e}")

        # 6. Repositories
        repos = self._context.components.get("repositories")
        if repos:
            health_status["checks"]["repositories"] = {
                "status": "healthy",
                "detail": f"{len(repos)} repos: {list(repos.keys())}"
            }
        else:
            errors.append("Repositories not initialized")
            health_status["checks"]["repositories"] = {"status": "critical", "detail": "missing"}

        # 7. Services
        services = self._context.components.get("services")
        if services:
            health_status["checks"]["services"] = {
                "status": "healthy",
                "detail": f"{len(services)} services: {list(services.keys())}"
            }
        else:
            errors.append("Services not initialized")
            health_status["checks"]["services"] = {"status": "critical", "detail": "missing"}

        # 8. Disk
        try:
            usage = shutil.disk_usage(_root_path)
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            free_percent = (usage.free / usage.total) * 100
            health_status["checks"]["disk"] = {
                "status": "healthy" if free_percent > 10 else "degraded",
                "detail": f"free={free_gb:.2f}GB ({free_percent:.1f}%) of {total_gb:.2f}GB"
            }
            if free_percent < 10:
                warnings.append(f"Low disk space: {free_percent:.1f}% free")
        except Exception as e:
            health_status["checks"]["disk"] = {"status": "unknown", "detail": str(e)}
            warnings.append(f"Disk space check failed: {e}")

        # Kesimpulan
        if errors:
            health_status["overall"] = "unhealthy"
            health_status["errors"] = errors
            health_status["warnings"] = warnings
            self._context.components["health_status"] = health_status
            raise RuntimeError(f"Health check failed: {errors}")
        elif warnings:
            health_status["overall"] = "degraded"
            health_status["warnings"] = warnings
            logger.info(f"Health check degraded with warnings (non-critical): {warnings}")
        else:
            health_status["overall"] = "healthy"
            logger.info("Health check passed successfully")

        self._context.components["health_status"] = health_status
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
                logger.warning(f"Step {step.name} skipped due to dependency failure")
                continue
            step.status = "running"
            step.started_at = datetime.now(UTC)
            start = time.time()
            try:
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
            self._log_startup_summary()
        return self._status

    def _log_startup_summary(self) -> None:
        summary = {
            "status": self._status.name,
            "total_duration_ms": sum(s.duration_ms for s in self._steps),
            "steps": {s.name: {"status": s.status, "duration_ms": s.duration_ms} for s in self._steps},
            "components": list(self._context.components.keys()),
        }
        logger.info(f"Startup summary: {summary}")

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
        # Await background tasks first
        if self._background_tasks:
            logger.info(f"Waiting for {len(self._background_tasks)} background tasks to complete...")
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

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

    def get_health_status(self) -> dict[str, Any] | None:
        return self._context.components.get("health_status")

    # === ENTITY DASAR METHODS ===
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
    orchestrator = get_startup_orchestrator()
    try:
        with asyncio.Runner() as runner:
            status = runner.run(orchestrator.startup())
        if status == StartupStatus.SUCCESS:
            logger.info("Startup completed successfully.")
            return True
        else:
            logger.error(f"Startup failed with status: {status}")
            return False
    except KeyboardInterrupt:
        logger.info("Startup interrupted by user")
        return False
    except Exception as e:
        logger.exception(f"Startup failed with unexpected error: {e}")
        return False


def shutdown() -> None:
    orchestrator = get_startup_orchestrator()
    try:
        with asyncio.Runner() as runner:
            runner.run(orchestrator.shutdown())
    except KeyboardInterrupt:
        logger.info("Shutdown interrupted by user")


def get_health() -> dict[str, Any] | None:
    return get_startup_orchestrator().get_health_status()


def _signal_handler(signum: int, frame: Any) -> None:
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown()
    sys.exit(0)


def register_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


# === ALIAS ===
BootstrapOrchestrator = StartupOrchestrator

__all__ = [
    "BootstrapOrchestrator",
    "StartupContext",
    "StartupOrchestrator",
    "StartupPhase",
    "StartupStatus",
    "StartupStep",
    "get_health",
    "get_startup_orchestrator",
    "register_signal_handlers",
    "run_startup",
    "shutdown",
]


def main():
    register_signal_handlers()
    success = run_startup()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    main()

