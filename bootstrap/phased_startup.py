#!/usr/bin/env python3
"""
Module: phased_startup.py
Layer: 3 - Bootstrap & Config
Responsibility: Startup bertahap (phased startup) yang memungkinkan sistem
               untuk mulai dalam mode terbatas (degraded) jika komponen non-kritis
               gagal. Mendukung graceful degradation dan dapat melanjutkan ke
               fase berikutnya setelah komponen kritis siap.

Metode yang ditambahkan:
- Untuk PhaseResult: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PhasedStartupContext: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PhasedStartupManager: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any

from bootstrap.orchestrator import (
    StartupPhase,
    get_startup_orchestrator,
)

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class PhasedStartupLevel(Enum):
    LEVEL_0_CORE = 0
    LEVEL_1_BASIC = 1
    LEVEL_2_FULL = 2
    LEVEL_3_ALL = 3

    def display_name(self) -> str:
        names = {
            PhasedStartupLevel.LEVEL_0_CORE: "Core Only",
            PhasedStartupLevel.LEVEL_1_BASIC: "Basic",
            PhasedStartupLevel.LEVEL_2_FULL: "Full",
            PhasedStartupLevel.LEVEL_3_ALL: "All Components",
        }
        return names.get(self, self.name)


class StartupStage(Enum):
    INITIALIZING = auto()
    CORE_LOADING = auto()
    CORE_READY = auto()
    BASIC_LOADING = auto()
    BASIC_READY = auto()
    FULL_LOADING = auto()
    FULL_READY = auto()
    ALL_LOADING = auto()
    COMPLETE = auto()
    DEGRADED = auto()
    FAILED = auto()

    def display_name(self) -> str:
        names = {
            StartupStage.INITIALIZING: "Initializing",
            StartupStage.CORE_LOADING: "Loading Core",
            StartupStage.CORE_READY: "Core Ready",
            StartupStage.BASIC_LOADING: "Loading Basic",
            StartupStage.BASIC_READY: "Basic Ready",
            StartupStage.FULL_LOADING: "Loading Full",
            StartupStage.FULL_READY: "Full Ready",
            StartupStage.ALL_LOADING: "Loading All",
            StartupStage.COMPLETE: "Complete",
            StartupStage.DEGRADED: "Degraded",
            StartupStage.FAILED: "Failed",
        }
        return names.get(self, self.name)


class PhaseError(Exception):
    """Error during phased startup."""

    pass


# === 2. PhaseResult (dengan entity dasar) ===
@dataclass(kw_only=True)
class PhaseResult:
    phase: StartupPhase
    level: PhasedStartupLevel
    success: bool
    duration_ms: float
    error: str | None = None
    degraded_mode: bool = False
    missing_components: list[str] = field(default_factory=list)

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not isinstance(self.phase, StartupPhase):
            raise ValueError("invalid phase")
        if not isinstance(self.level, PhasedStartupLevel):
            raise ValueError("invalid level")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "phase": self.phase.name,
                "level": self.level.name,
                "success": self.success,
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
                "phase": self.phase.name,
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
            "phase": self.phase.name,
            "level": self.level.name,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "degraded_mode": self.degraded_mode,
            "missing_components": self.missing_components,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseResult:
        instance = cls(
            phase=StartupPhase[data["phase"]],
            level=PhasedStartupLevel[data["level"]],
            success=data["success"],
            duration_ms=data["duration_ms"],
            error=data.get("error"),
            degraded_mode=data.get("degraded_mode", False),
            missing_components=data.get("missing_components", []),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PhaseResult:
        new = PhaseResult(
            phase=self.phase,
            level=self.level,
            success=self.success,
            duration_ms=self.duration_ms,
            error=self.error,
            degraded_mode=self.degraded_mode,
            missing_components=self.missing_components.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source_phase": self.phase.name})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "phase": self.phase.name,
            "level": self.level.name,
            "success": self.success,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PhaseResult:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. PhasedStartupContext (dengan entity dasar) ===
@dataclass(kw_only=True)
class PhasedStartupContext:
    current_level: PhasedStartupLevel = PhasedStartupLevel.LEVEL_0_CORE
    current_stage: StartupStage = StartupStage.INITIALIZING
    phase_results: list[PhaseResult] = field(default_factory=list)
    degraded_components: set[str] = field(default_factory=set)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not isinstance(self.current_level, PhasedStartupLevel):
            raise ValueError("invalid current_level")
        if not isinstance(self.current_stage, StartupStage):
            raise ValueError("invalid current_stage")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "current_level": self.current_level.name,
                "current_stage": self.current_stage.name,
                "phase_results_count": len(self.phase_results),
                "degraded_components_count": len(self.degraded_components),
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
        for r in self.phase_results:
            res = r.validate()
            if not res["is_valid"]:
                errors.extend([f"PhaseResult {r.phase.name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_level": self.current_level.name,
            "current_stage": self.current_stage.name,
            "phase_results": [r.to_dict() for r in self.phase_results],
            "degraded_components": list(self.degraded_components),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhasedStartupContext:
        instance = cls(
            current_level=PhasedStartupLevel[data["current_level"]],
            current_stage=StartupStage[data["current_stage"]],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
        )
        instance.phase_results = [PhaseResult.from_dict(r) for r in data.get("phase_results", [])]
        instance.degraded_components = set(data.get("degraded_components", []))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PhasedStartupContext:
        new = PhasedStartupContext(
            started_at=datetime.now(UTC),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "current_level": self.current_level.name,
            "current_stage": self.current_stage.name,
            "phase_results_count": len(self.phase_results),
            "degraded_components_count": len(self.degraded_components),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PhasedStartupContext:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. PhasedStartupManager (dengan entity dasar) ===
class PhasedStartupManager:
    _instance: PhasedStartupManager | None = None

    def __new__(cls) -> PhasedStartupManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._context = PhasedStartupContext()
        self._orchestrator = get_startup_orchestrator()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "current_level": self._context.current_level.name,
                "current_stage": self._context.current_stage.name,
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

    async def startup_to_level(
        self,
        target_level: PhasedStartupLevel = PhasedStartupLevel.LEVEL_3_ALL,
        allow_degraded: bool = True,
        timeout_seconds: int = 120,
    ) -> tuple[PhasedStartupLevel, StartupStage]:
        self._context.current_stage = StartupStage.INITIALIZING
        start_time = time.time()

        try:
            if target_level.value >= PhasedStartupLevel.LEVEL_0_CORE.value:
                result = await self._phase_core_loading()
                self._context.phase_results.append(result)
                if not result.success:
                    self._context.current_stage = StartupStage.FAILED
                    self._record_audit(
                        "STARTUP_TO_LEVEL_FAILED", "system", {"target_level": target_level.name}
                    )
                    return self._context.current_level, self._context.current_stage
                self._context.current_level = PhasedStartupLevel.LEVEL_0_CORE
                self._context.current_stage = StartupStage.CORE_READY

            if target_level.value >= PhasedStartupLevel.LEVEL_1_BASIC.value:
                if time.time() - start_time > timeout_seconds:
                    raise TimeoutError(f"Startup timeout after {timeout_seconds}s")
                result = await self._phase_basic_loading(allow_degraded)
                self._context.phase_results.append(result)
                if result.success:
                    self._context.current_level = PhasedStartupLevel.LEVEL_1_BASIC
                    self._context.current_stage = StartupStage.BASIC_READY
                elif not allow_degraded:
                    self._context.current_stage = StartupStage.FAILED
                    self._record_audit(
                        "STARTUP_TO_LEVEL_FAILED", "system", {"target_level": target_level.name}
                    )
                    return self._context.current_level, self._context.current_stage
                else:
                    self._context.current_stage = StartupStage.DEGRADED
                    self._context.degraded_components.update(result.missing_components)

            if target_level.value >= PhasedStartupLevel.LEVEL_2_FULL.value:
                if time.time() - start_time > timeout_seconds:
                    raise TimeoutError(f"Startup timeout after {timeout_seconds}s")
                result = await self._phase_full_loading(allow_degraded)
                self._context.phase_results.append(result)
                if result.success:
                    self._context.current_level = PhasedStartupLevel.LEVEL_2_FULL
                    self._context.current_stage = StartupStage.FULL_READY
                elif not allow_degraded:
                    self._context.current_stage = StartupStage.FAILED
                    self._record_audit(
                        "STARTUP_TO_LEVEL_FAILED", "system", {"target_level": target_level.name}
                    )
                    return self._context.current_level, self._context.current_stage
                else:
                    self._context.current_stage = StartupStage.DEGRADED
                    self._context.degraded_components.update(result.missing_components)

            if target_level.value >= PhasedStartupLevel.LEVEL_3_ALL.value:
                if time.time() - start_time > timeout_seconds:
                    raise TimeoutError(f"Startup timeout after {timeout_seconds}s")
                result = await self._phase_all_loading(allow_degraded)
                self._context.phase_results.append(result)
                if result.success:
                    self._context.current_level = PhasedStartupLevel.LEVEL_3_ALL
                    self._context.current_stage = StartupStage.COMPLETE
                elif not allow_degraded:
                    self._context.current_stage = StartupStage.FAILED
                else:
                    self._context.current_stage = StartupStage.DEGRADED
                    self._context.degraded_components.update(result.missing_components)

            self._context.completed_at = datetime.now(UTC)
            self._record_audit(
                "STARTUP_TO_LEVEL_SUCCESS",
                "system",
                {"target_level": target_level.name, "allow_degraded": allow_degraded},
            )

        except Exception as e:
            logger.exception(f"Phased startup failed: {e}")
            self._context.current_stage = StartupStage.FAILED
            self._record_audit("STARTUP_TO_LEVEL_EXCEPTION", "system", {"error": str(e)})

        return self._context.current_level, self._context.current_stage

    async def _phase_core_loading(self) -> PhaseResult:
        logger.info("Phase 0: Loading core components...")
        start = time.time()
        try:
            self._orchestrator._load_constitution()
            self._orchestrator._load_axioms()
            self._orchestrator._init_kernel()
            duration = (time.time() - start) * 1000
            logger.info(f"Core components loaded in {duration:.2f}ms")
            return PhaseResult(
                phase=StartupPhase.CONSTITUTION_LOAD,
                level=PhasedStartupLevel.LEVEL_0_CORE,
                success=True,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.error(f"Core loading failed: {e}")
            return PhaseResult(
                phase=StartupPhase.CONSTITUTION_LOAD,
                level=PhasedStartupLevel.LEVEL_0_CORE,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _phase_basic_loading(self, allow_degraded: bool) -> PhaseResult:
        logger.info("Phase 1: Loading basic components...")
        start = time.time()
        missing = []
        try:
            self._orchestrator._load_config()
            try:
                await self._orchestrator._connect_database()
            except Exception as e:
                logger.error(f"Database connection failed: {e}")
                if not allow_degraded:
                    raise
                missing.append("database")
            if "database" not in missing:
                try:
                    self._orchestrator._init_repositories()
                except Exception as e:
                    logger.error(f"Repository initialization failed: {e}")
                    if not allow_degraded:
                        raise
                    missing.append("repositories")
            duration = (time.time() - start) * 1000
            success = len(missing) == 0
            return PhaseResult(
                phase=StartupPhase.DATABASE_CONNECT,
                level=PhasedStartupLevel.LEVEL_1_BASIC,
                success=success,
                duration_ms=duration,
                degraded_mode=len(missing) > 0,
                missing_components=missing,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return PhaseResult(
                phase=StartupPhase.DATABASE_CONNECT,
                level=PhasedStartupLevel.LEVEL_1_BASIC,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _phase_full_loading(self, allow_degraded: bool) -> PhaseResult:
        logger.info("Phase 2: Loading full components...")
        start = time.time()
        missing = []
        try:
            if "repositories" not in self._context.degraded_components:
                try:
                    self._orchestrator._init_services()
                except Exception as e:
                    logger.error(f"Service initialization failed: {e}")
                    if not allow_degraded:
                        raise
                    missing.append("services")
            try:
                self._orchestrator._start_api()
            except Exception as e:
                logger.error(f"API start failed: {e}")
                if not allow_degraded:
                    raise
                missing.append("api")
            duration = (time.time() - start) * 1000
            success = len(missing) == 0
            return PhaseResult(
                phase=StartupPhase.SERVICES_INIT,
                level=PhasedStartupLevel.LEVEL_2_FULL,
                success=success,
                duration_ms=duration,
                degraded_mode=len(missing) > 0,
                missing_components=missing,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return PhaseResult(
                phase=StartupPhase.SERVICES_INIT,
                level=PhasedStartupLevel.LEVEL_2_FULL,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _phase_all_loading(self, allow_degraded: bool) -> PhaseResult:
        logger.info("Phase 3: Loading all components...")
        start = time.time()
        missing = []
        try:
            try:
                self._orchestrator._connect_message_broker()
            except Exception as e:
                logger.warning(f"Message broker connection failed: {e}")
                missing.append("message_broker")
            try:
                self._orchestrator._connect_cache()
            except Exception as e:
                logger.warning(f"Cache connection failed: {e}")
                missing.append("cache")
            try:
                self._orchestrator._health_check()
            except Exception as e:
                logger.warning(f"Health check failed: {e}")
                missing.append("health_check")
            duration = (time.time() - start) * 1000
            success = len(missing) == 0
            return PhaseResult(
                phase=StartupPhase.HEALTH_CHECK,
                level=PhasedStartupLevel.LEVEL_3_ALL,
                success=success,
                duration_ms=duration,
                degraded_mode=len(missing) > 0,
                missing_components=missing,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return PhaseResult(
                phase=StartupPhase.HEALTH_CHECK,
                level=PhasedStartupLevel.LEVEL_3_ALL,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def upgrade_to_level(self, new_level: PhasedStartupLevel) -> tuple[bool, str]:
        if new_level.value <= self._context.current_level.value:
            return True, f"Already at level {self._context.current_level.name}"
        target_level, _stage = await self.startup_to_level(
            target_level=new_level,
            allow_degraded=True,
            timeout_seconds=60,
        )
        if target_level.value >= new_level.value:
            self._record_audit(
                "UPGRADE_TO_LEVEL", "system", {"new_level": new_level.name, "success": True}
            )
            return True, f"Upgraded to {target_level.name}"
        else:
            self._record_audit(
                "UPGRADE_TO_LEVEL", "system", {"new_level": new_level.name, "success": False}
            )
            return (
                False,
                f"Failed to upgrade to {new_level.name}, current level {target_level.name}",
            )

    def get_current_capabilities(self) -> dict[str, bool]:
        level = self._context.current_level
        degraded = self._context.current_stage == StartupStage.DEGRADED
        return {
            "can_read": level.value >= PhasedStartupLevel.LEVEL_0_CORE.value,
            "can_write": level.value >= PhasedStartupLevel.LEVEL_1_BASIC.value,
            "can_post_journal": level.value >= PhasedStartupLevel.LEVEL_2_FULL.value,
            "can_generate_reports": level.value >= PhasedStartupLevel.LEVEL_2_FULL.value,
            "can_use_api": level.value >= PhasedStartupLevel.LEVEL_2_FULL.value,
            "can_use_messaging": level.value >= PhasedStartupLevel.LEVEL_3_ALL.value,
            "can_use_cache": level.value >= PhasedStartupLevel.LEVEL_3_ALL.value,
            "is_degraded": degraded,
        }

    def get_status(self) -> dict[str, Any]:
        return {
            "current_level": self._context.current_level.name,
            "current_stage": self._context.current_stage.name,
            "started_at": self._context.started_at.isoformat(),
            "completed_at": self._context.completed_at.isoformat()
            if self._context.completed_at
            else None,
            "degraded_components": list(self._context.degraded_components),
            "phases": [
                {
                    "phase": r.phase.name,
                    "level": r.level.name,
                    "success": r.success,
                    "duration_ms": r.duration_ms,
                    "degraded_mode": r.degraded_mode,
                    "missing": r.missing_components,
                    "error": r.error,
                }
                for r in self._context.phase_results
            ],
            "capabilities": self.get_current_capabilities(),
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        res = self._context.validate()
        if not res["is_valid"]:
            errors.extend([f"Context: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self._context.to_dict(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhasedStartupManager:
        instance = cls()
        instance._context = PhasedStartupContext.from_dict(data.get("context", {}))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PhasedStartupManager:
        new = PhasedStartupManager()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "current_level": self._context.current_level.name,
            "current_stage": self._context.current_stage.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PhasedStartupManager:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._context = PhasedStartupContext()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# === SINGLETON ACCESSOR ===
_phased_startup_manager_instance: PhasedStartupManager | None = None


def get_phased_startup_manager() -> PhasedStartupManager:
    global _phased_startup_manager_instance
    if _phased_startup_manager_instance is None:
        _phased_startup_manager_instance = PhasedStartupManager()
    return _phased_startup_manager_instance


# === CONVENIENCE FUNCTIONS ===
async def startup_core_only() -> bool:
    manager = get_phased_startup_manager()
    _level, stage = await manager.startup_to_level(PhasedStartupLevel.LEVEL_0_CORE)
    return stage not in (StartupStage.FAILED, StartupStage.INITIALIZING)


async def startup_basic_only() -> bool:
    manager = get_phased_startup_manager()
    _level, stage = await manager.startup_to_level(PhasedStartupLevel.LEVEL_1_BASIC)
    return stage not in (StartupStage.FAILED, StartupStage.INITIALIZING)


async def startup_full() -> bool:
    manager = get_phased_startup_manager()
    _level, stage = await manager.startup_to_level(PhasedStartupLevel.LEVEL_2_FULL)
    return stage not in (StartupStage.FAILED, StartupStage.INITIALIZING)


async def startup_all() -> bool:
    manager = get_phased_startup_manager()
    _level, stage = await manager.startup_to_level(
        PhasedStartupLevel.LEVEL_3_ALL, allow_degraded=True
    )
    return stage != StartupStage.FAILED


# === ALIAS UNTUK KOMPATIBILITAS ===
PhasedStartup = PhasedStartupManager


# === EXPORTS ===
__all__ = [
    "PhaseError",
    "PhaseResult",
    "PhasedStartup",
    "PhasedStartupContext",
    "PhasedStartupLevel",
    "PhasedStartupManager",
    "StartupStage",
    "get_phased_startup_manager",
    "startup_all",
    "startup_basic_only",
    "startup_core_only",
    "startup_full",
]
