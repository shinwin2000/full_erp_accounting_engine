#!/usr/bin/env python3
"""
Module: rollback_handler.py
Layer: 3 - Bootstrap & Config
Responsibility: Menangani rollback startup jika komponen gagal diinisialisasi.
               Menyediakan mekanisme untuk mengembalikan sistem ke keadaan
               sebelumnya (sebelum startup) dengan cara yang aman dan teraudit.

Metode yang ditambahkan:
- Untuk RollbackStep: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk RollbackRecord: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk RollbackHandler: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import uuid4

from bootstrap.orchestrator import get_startup_orchestrator
from bootstrap.phased_startup import get_phased_startup_manager

logger = logging.getLogger(__name__)

# === 1. CONSTANTS & ENUMS ===


class RollbackReason(Enum):
    STARTUP_FAILURE = auto()
    COMPONENT_UNHEALTHY = auto()
    MANUAL_TRIGGER = auto()
    CONSTITUTION_VIOLATION = auto()
    SECURITY_BREACH = auto()
    DATA_CORRUPTION = auto()
    RESOURCE_EXHAUSTION = auto()
    DEPENDENCY_FAILURE = auto()

    def display_name(self) -> str:
        names = {
            RollbackReason.STARTUP_FAILURE: "Startup Failure",
            RollbackReason.COMPONENT_UNHEALTHY: "Component Unhealthy",
            RollbackReason.MANUAL_TRIGGER: "Manual Trigger",
            RollbackReason.CONSTITUTION_VIOLATION: "Constitution Violation",
            RollbackReason.SECURITY_BREACH: "Security Breach",
            RollbackReason.DATA_CORRUPTION: "Data Corruption",
            RollbackReason.RESOURCE_EXHAUSTION: "Resource Exhaustion",
            RollbackReason.DEPENDENCY_FAILURE: "Dependency Failure",
        }
        return names.get(self, self.name)


class RollbackScope(Enum):
    STEP_ONLY = auto()
    PHASE_ONLY = auto()
    TO_PREVIOUS_PHASE = auto()
    TO_CORE = auto()
    FULL_RESET = auto()

    def display_name(self) -> str:
        names = {
            RollbackScope.STEP_ONLY: "Step Only",
            RollbackScope.PHASE_ONLY: "Phase Only",
            RollbackScope.TO_PREVIOUS_PHASE: "To Previous Phase",
            RollbackScope.TO_CORE: "To Core",
            RollbackScope.FULL_RESET: "Full Reset",
        }
        return names.get(self, self.name)


class RollbackStatus(Enum):
    NOT_STARTED = auto()
    IN_PROGRESS = auto()
    SUCCESS = auto()
    PARTIAL = auto()
    FAILED = auto()

    def display_name(self) -> str:
        names = {
            RollbackStatus.NOT_STARTED: "Not Started",
            RollbackStatus.IN_PROGRESS: "In Progress",
            RollbackStatus.SUCCESS: "Success",
            RollbackStatus.PARTIAL: "Partial",
            RollbackStatus.FAILED: "Failed",
        }
        return names.get(self, self.name)


# === 2. RollbackStep (dengan entity dasar) ===
@dataclass(kw_only=True)
class RollbackStep:
    name: str
    action: Callable[[], bool]
    timeout_seconds: int = 30
    status: str = "pending"
    error: str | None = None
    duration_ms: float = 0.0

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _step_id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.name:
            raise ValueError("name is required")
        if not callable(self.action):
            raise ValueError("action must be callable")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "step_id": self._step_id,
                "name": self.name,
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
            "step_id": self._step_id,
            "name": self.name,
            "timeout_seconds": self.timeout_seconds,
            "status": self.status,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "version": self._version,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], action_map: dict[str, Callable] | None = None
    ) -> RollbackStep:
        action = (action_map or {}).get(data["name"], lambda: True)
        instance = cls(
            name=data["name"],
            action=action,
            timeout_seconds=data.get("timeout_seconds", 30),
        )
        instance.status = data.get("status", "pending")
        instance.error = data.get("error")
        instance.duration_ms = data.get("duration_ms", 0.0)
        instance._step_id = data.get("step_id", str(uuid4()))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RollbackStep:
        new = RollbackStep(
            name=self.name,
            action=self.action,
            timeout_seconds=self.timeout_seconds,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._step_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "step_id": self._step_id,
            "name": self.name,
            "status": self.status,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RollbackStep:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. RollbackRecord (dengan entity dasar) ===
@dataclass(kw_only=True)
class RollbackRecord:
    record_id: str
    timestamp: datetime
    reason: RollbackReason
    scope: RollbackScope
    trigger_component: str
    trigger_error: str
    steps_executed: list[dict[str, Any]]
    final_status: RollbackStatus
    duration_ms: float
    system_state_before: dict[str, Any]
    system_state_after: dict[str, Any]

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.record_id:
            raise ValueError("record_id is required")
        if not isinstance(self.reason, RollbackReason):
            raise ValueError("invalid reason")
        if not isinstance(self.scope, RollbackScope):
            raise ValueError("invalid scope")
        if not self.trigger_component:
            raise ValueError("trigger_component is required")
        if not isinstance(self.final_status, RollbackStatus):
            raise ValueError("invalid final_status")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "record_id": self.record_id,
                "reason": self.reason.name,
                "scope": self.scope.name,
                "final_status": self.final_status.name,
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
                "record_id": self.record_id,
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
            "record_id": self.record_id,
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason.name,
            "scope": self.scope.name,
            "trigger_component": self.trigger_component,
            "trigger_error": self.trigger_error[:500],
            "steps_executed": self.steps_executed,
            "final_status": self.final_status.name,
            "duration_ms": self.duration_ms,
            "system_state_before": self.system_state_before,
            "system_state_after": self.system_state_after,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RollbackRecord:
        instance = cls(
            record_id=data["record_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            reason=RollbackReason[data["reason"]],
            scope=RollbackScope[data["scope"]],
            trigger_component=data["trigger_component"],
            trigger_error=data["trigger_error"],
            steps_executed=data.get("steps_executed", []),
            final_status=RollbackStatus[data["final_status"]],
            duration_ms=data["duration_ms"],
            system_state_before=data.get("system_state_before", {}),
            system_state_after=data.get("system_state_after", {}),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RollbackRecord:
        new = RollbackRecord(
            record_id=str(uuid4()),
            timestamp=datetime.now(UTC),
            reason=self.reason,
            scope=self.scope,
            trigger_component=self.trigger_component,
            trigger_error=self.trigger_error,
            steps_executed=self.steps_executed.copy(),
            final_status=self.final_status,
            duration_ms=self.duration_ms,
            system_state_before=self.system_state_before.copy(),
            system_state_after=self.system_state_after.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.record_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "record_id": self.record_id,
            "reason": self.reason.name,
            "scope": self.scope.name,
            "final_status": self.final_status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RollbackRecord:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. RollbackHandler (dengan entity dasar) ===
class RollbackHandler:
    _instance: RollbackHandler | None = None

    def __new__(cls) -> RollbackHandler:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._orchestrator = get_startup_orchestrator()
        self._phased_manager = get_phased_startup_manager()
        self._rollback_history: list[RollbackRecord] = []
        self._current_rollback_status = RollbackStatus.NOT_STARTED
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "history_count": len(self._rollback_history),
                "current_status": self._current_rollback_status.name,
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

    async def rollback_startup(
        self,
        reason: RollbackReason,
        trigger_component: str,
        trigger_error: str,
        scope: RollbackScope = RollbackScope.TO_PREVIOUS_PHASE,
    ) -> RollbackRecord:
        self._current_rollback_status = RollbackStatus.IN_PROGRESS
        start_time = time.time()
        state_before = self._capture_system_state()
        steps = self._build_rollback_steps(scope, trigger_component)
        executed_steps = []
        all_success = True

        for step in steps:
            step_start = time.time()
            try:
                success = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, step.action),
                    timeout=step.timeout_seconds,
                )
                step.status = "success" if success else "failed"
                if not success:
                    all_success = False
                    step.error = "Action returned False"
            except TimeoutError:
                step.status = "failed"
                step.error = f"Timeout after {step.timeout_seconds}s"
                all_success = False
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                all_success = False
            finally:
                step.duration_ms = (time.time() - step_start) * 1000
                executed_steps.append(
                    {
                        "name": step.name,
                        "status": step.status,
                        "error": step.error,
                        "duration_ms": step.duration_ms,
                    }
                )
                if step.status == "failed" and scope == RollbackScope.STEP_ONLY:
                    break

        state_after = self._capture_system_state()
        final_status = RollbackStatus.SUCCESS if all_success else RollbackStatus.PARTIAL
        self._current_rollback_status = final_status

        record = RollbackRecord(
            record_id=f"rb_{int(time.time() * 1000)}",
            timestamp=datetime.now(UTC),
            reason=reason,
            scope=scope,
            trigger_component=trigger_component,
            trigger_error=trigger_error[:500],
            steps_executed=executed_steps,
            final_status=final_status,
            duration_ms=(time.time() - start_time) * 1000,
            system_state_before=state_before,
            system_state_after=state_after,
        )
        self._rollback_history.append(record)

        if final_status == RollbackStatus.SUCCESS:
            logger.info(f"Rollback completed successfully in {record.duration_ms:.2f}ms")
        else:
            logger.error(f"Rollback partial/failed: {final_status.name}")

        if final_status == RollbackStatus.FAILED and scope == RollbackScope.FULL_RESET:
            logger.critical("Rollback failed completely, initiating emergency shutdown")
            await self._emergency_shutdown()

        self._record_audit(
            "ROLLBACK_STARTUP",
            "system",
            {
                "reason": reason.name,
                "scope": scope.name,
                "trigger_component": trigger_component,
                "final_status": final_status.name,
            },
        )
        return record

    def _build_rollback_steps(self, scope: RollbackScope, trigger: str) -> list[RollbackStep]:
        steps = []
        if scope == RollbackScope.STEP_ONLY:
            steps.append(
                RollbackStep(
                    name=f"rollback_step_{trigger}",
                    action=lambda: self._rollback_single_step(trigger),
                    timeout_seconds=10,
                )
            )
        elif scope == RollbackScope.PHASE_ONLY:
            steps.extend(
                [
                    RollbackStep(name="rollback_repositories", action=self._rollback_repositories),
                    RollbackStep(name="disconnect_database", action=self._rollback_database),
                ]
            )
        elif scope == RollbackScope.TO_PREVIOUS_PHASE:
            steps.extend(
                [
                    RollbackStep(name="stop_api", action=self._stop_api),
                    RollbackStep(name="cleanup_services", action=self._cleanup_services),
                    RollbackStep(name="rollback_repositories", action=self._rollback_repositories),
                    RollbackStep(name="disconnect_database", action=self._rollback_database),
                ]
            )
        elif scope == RollbackScope.TO_CORE:
            steps.extend(
                [
                    RollbackStep(name="stop_api", action=self._stop_api),
                    RollbackStep(name="cleanup_services", action=self._cleanup_services),
                    RollbackStep(name="rollback_repositories", action=self._rollback_repositories),
                    RollbackStep(name="disconnect_database", action=self._rollback_database),
                    RollbackStep(name="disconnect_broker", action=self._disconnect_broker),
                    RollbackStep(name="disconnect_cache", action=self._disconnect_cache),
                ]
            )
        elif scope == RollbackScope.FULL_RESET:
            steps.extend(
                [
                    RollbackStep(name="stop_api", action=self._stop_api),
                    RollbackStep(name="cleanup_services", action=self._cleanup_services),
                    RollbackStep(name="rollback_repositories", action=self._rollback_repositories),
                    RollbackStep(name="disconnect_database", action=self._rollback_database),
                    RollbackStep(name="disconnect_broker", action=self._disconnect_broker),
                    RollbackStep(name="disconnect_cache", action=self._disconnect_cache),
                    RollbackStep(name="reset_kernel", action=self._reset_kernel),
                    RollbackStep(name="reset_axioms", action=self._reset_axioms),
                    RollbackStep(name="reset_constitution", action=self._reset_constitution),
                ]
            )
        return steps

    # === ROLLBACK ACTIONS ===
    def _rollback_single_step(self, step_name: str) -> bool:
        try:
            if step_name == "connect_database":
                self._orchestrator._disconnect_database()
            elif step_name == "init_repositories":
                self._orchestrator._cleanup_repositories()
            elif step_name == "init_services":
                self._orchestrator._cleanup_services()
            elif step_name == "start_api":
                self._orchestrator._stop_api()
            else:
                logger.warning(f"No rollback defined for step {step_name}")
            return True
        except Exception as e:
            logger.error(f"Rollback step {step_name} failed: {e}")
            return False

    def _rollback_repositories(self) -> bool:
        try:
            self._orchestrator._cleanup_repositories()
            return True
        except Exception as e:
            logger.error(f"Failed to rollback repositories: {e}")
            return False

    def _rollback_database(self) -> bool:
        try:
            self._orchestrator._disconnect_database()
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect database: {e}")
            return False

    def _stop_api(self) -> bool:
        try:
            self._orchestrator._stop_api()
            return True
        except Exception as e:
            logger.error(f"Failed to stop API: {e}")
            return False

    def _cleanup_services(self) -> bool:
        try:
            self._orchestrator._cleanup_services()
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup services: {e}")
            return False

    def _disconnect_broker(self) -> bool:
        try:
            self._orchestrator._disconnect_message_broker()
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect broker: {e}")
            return False

    def _disconnect_cache(self) -> bool:
        try:
            self._orchestrator._disconnect_cache()
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect cache: {e}")
            return False

    def _reset_kernel(self) -> bool:
        try:
            # Lazy import untuk menghindari AST drift
            gate_mod = importlib.import_module("kernel.sealed_gate")
            get_sealed_gate = gate_mod.get_sealed_gate
            gate = get_sealed_gate()
            if hasattr(gate, "reset"):
                gate.reset()
            return True
        except Exception as e:
            logger.error(f"Failed to reset kernel: {e}")
            return False

    def _reset_axioms(self) -> bool:
        try:
            # Lazy import semua axioms
            conservation_mod = importlib.import_module("axioms.conservation_of_value")
            get_conservation = conservation_mod.get_conservation_axiom
            double_entry_mod = importlib.import_module("axioms.double_entry")
            get_double_entry = double_entry_mod.get_double_entry_axiom
            immutability_mod = importlib.import_module("axioms.immutability")
            get_immutability = immutability_mod.get_immutability_axiom

            axioms = [get_conservation, get_double_entry, get_immutability]
            for axiom_getter in axioms:
                axiom = axiom_getter()
                if hasattr(axiom, "reset"):
                    axiom.reset()
            return True
        except Exception as e:
            logger.error(f"Failed to reset axioms: {e}")
            return False

    def _reset_constitution(self) -> bool:
        try:
            # Lazy import constitution jika diperlukan
            # Saat ini tidak ada reset yang diperlukan, hanya placeholder
            return True
        except Exception as e:
            logger.error(f"Failed to reset constitution: {e}")
            return False

    def _capture_system_state(self) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "startup_status": self._orchestrator.get_status(),
            "phased_status": self._phased_manager.get_status(),
            "components": list(self._orchestrator.get_context().components.keys()),
        }

    async def _emergency_shutdown(self) -> None:
        logger.critical("EMERGENCY SHUTDOWN INITIATED")
        import sys

        sys.exit(1)

    def get_rollback_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._rollback_history[-limit:]]

    def get_last_rollback(self) -> dict[str, Any] | None:
        if self._rollback_history:
            return self._rollback_history[-1].to_dict()
        return None

    def get_status(self) -> dict[str, Any]:
        return {
            "current_status": self._current_rollback_status.name,
            "total_rollbacks": len(self._rollback_history),
            "last_rollback": self.get_last_rollback(),
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for r in self._rollback_history:
            res = r.validate()
            if not res["is_valid"]:
                errors.extend([f"Record {r.record_id}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_status": self._current_rollback_status.name,
            "history_count": len(self._rollback_history),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RollbackHandler:
        instance = cls()
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RollbackHandler:
        new = RollbackHandler()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "history_count": len(self._rollback_history),
            "current_status": self._current_rollback_status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RollbackHandler:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._rollback_history = []
        self._current_rollback_status = RollbackStatus.NOT_STARTED
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# === SINGLETON ACCESSOR ===
_rollback_handler_instance: RollbackHandler | None = None


def get_rollback_handler() -> RollbackHandler:
    global _rollback_handler_instance
    if _rollback_handler_instance is None:
        _rollback_handler_instance = RollbackHandler()
    return _rollback_handler_instance


# === CONVENIENCE FUNCTIONS ===
async def rollback_on_failure(
    reason: RollbackReason,
    component: str,
    error: str,
    scope: RollbackScope = RollbackScope.TO_PREVIOUS_PHASE,
) -> RollbackRecord | None:
    handler = get_rollback_handler()
    try:
        record = await handler.rollback_startup(reason, component, error, scope)
        return record
    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        return None


# === EXPORTS ===
__all__ = [
    "RollbackHandler",
    "RollbackReason",
    "RollbackRecord",
    "RollbackScope",
    "RollbackStatus",
    "RollbackStep",
    "get_rollback_handler",
    "rollback_on_failure",
]
