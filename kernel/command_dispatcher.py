#!/usr/bin/env python3
"""
Module: command_dispatcher.py
Layer: 4 - Kernel / Command Dispatcher
Responsibility: Mendistribusikan command ke handler yang sesuai.
               Mendukung synchronous dan asynchronous dispatch,
               priority queue, load balancing, dan retry logic.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_queue_size(), get_dispatch_history(), get_statistics(), set_strategy(), clear_queue()
- start_workers(), stop_workers()
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any

from kernel.command_envelope import CommandEnvelope, CommandStatus
from kernel.command_handler_registry import HandlerNotFoundError, get_handler_registry

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===
class DispatchPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class DispatchStrategy(Enum):
    DIRECT = auto()
    QUEUE = auto()
    PRIORITY_QUEUE = auto()
    ROUND_ROBIN = auto()


@dataclass(order=True)
class QueuedCommand:
    priority: int
    sequence: int
    envelope: CommandEnvelope = field(compare=False)
    created_at: float = field(default_factory=time.time)


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseCommandDispatcher(ABC):
    """
    Base contract for Command Dispatcher.
    Semua method yang wajib diimplementasikan oleh subclass.
    """

    @abstractmethod
    def start_workers(self, worker_count: int = 4) -> None:
        """Start background worker tasks."""
        pass

    @abstractmethod
    async def stop_workers(self, timeout: float = 10.0) -> None:
        """Stop all workers gracefully."""
        pass

    @abstractmethod
    async def dispatch(
        self,
        envelope: CommandEnvelope,
        priority: DispatchPriority = DispatchPriority.NORMAL,
        strategy: DispatchStrategy | None = None,
    ) -> CommandEnvelope:
        """Dispatch a command envelope."""
        pass

    @abstractmethod
    def clear_queue(self) -> int:
        """Clear all pending commands from the queue."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about dispatcher."""
        pass


# === 2. COMMAND DISPATCHER ===
class CommandDispatcher(BaseCommandDispatcher):
    _instance: CommandDispatcher | None = None
    _lock = threading.Lock()

    def __new__(cls) -> CommandDispatcher:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._registry = get_handler_registry()
        self._queue: list[QueuedCommand] = []
        self._queue_lock = threading.Lock()
        self._sequence = 0
        self._workers: list[asyncio.Task] = []
        self._worker_count = 4
        self._running = False
        self._dispatch_history: list[dict[str, Any]] = []
        self._max_history = 1000
        self._strategy = DispatchStrategy.PRIORITY_QUEUE
        self._reject_when_queue_full = True
        self._max_queue_size = 10000
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    def start_workers(self, worker_count: int = 4) -> None:
        if self._running:
            logger.warning("Workers already running")
            return
        self._running = True
        self._worker_count = worker_count

        async def worker(worker_id: int):
            logger.info(f"Command worker {worker_id} started")
            while self._running:
                command = await self._dequeue()
                if command is None:
                    await asyncio.sleep(0.1)
                    continue
                try:
                    await self._execute_queued_command(command)
                except Exception as e:
                    logger.error(f"Worker {worker_id} failed to execute command: {e}")
            logger.info(f"Command worker {worker_id} stopped")

        loop = asyncio.get_event_loop()
        for i in range(worker_count):
            task = loop.create_task(worker(i))
            self._workers.append(task)
        logger.info(f"Started {worker_count} command workers")

    async def stop_workers(self, timeout: float = 10.0) -> None:
        self._running = False
        if self._workers:
            _done, pending = await asyncio.wait(
                self._workers, timeout=timeout, return_when=asyncio.ALL_COMPLETED
            )
            for task in pending:
                task.cancel()
        self._workers.clear()
        logger.info("Command workers stopped")

    async def dispatch(
        self,
        envelope: CommandEnvelope,
        priority: DispatchPriority = DispatchPriority.NORMAL,
        strategy: DispatchStrategy | None = None,
    ) -> CommandEnvelope:
        strat = strategy or self._strategy
        if strat == DispatchStrategy.DIRECT:
            return await self._dispatch_direct(envelope)
        elif strat in (DispatchStrategy.QUEUE, DispatchStrategy.PRIORITY_QUEUE):
            if self._reject_when_queue_full and self.get_queue_size() >= self._max_queue_size:
                envelope.status = CommandStatus.REJECTED
                envelope.error = "Command queue is full"
                self._record_dispatch(envelope, "REJECTED_FULL_QUEUE")
                return envelope
            await self._enqueue(envelope, priority)
            return envelope
        elif strat == DispatchStrategy.ROUND_ROBIN:
            await self._enqueue(envelope, priority)
            return envelope
        else:
            return await self._dispatch_direct(envelope)

    async def _dispatch_direct(self, envelope: CommandEnvelope) -> CommandEnvelope:
        start_time = time.time()
        try:
            handler = self._registry.get_handler(envelope.command_type)
            if asyncio.iscoroutinefunction(handler):
                result = await handler(envelope.command_data)
            else:
                result = handler(envelope.command_data)
            envelope.status = CommandStatus.SUCCESS
            envelope.result = result
        except HandlerNotFoundError:
            envelope.status = CommandStatus.REJECTED
            envelope.error = f"No handler for {envelope.command_type}"
            raise
        except Exception as e:
            envelope.status = CommandStatus.FAILED
            envelope.error = str(e)
            raise
        finally:
            envelope.execution_time_ms = (time.time() - start_time) * 1000
        self._record_dispatch(envelope, "DIRECT")
        return envelope

    async def _enqueue(self, envelope: CommandEnvelope, priority: DispatchPriority) -> None:
        with self._queue_lock:
            self._sequence += 1
            queued = QueuedCommand(
                priority=priority.value, sequence=self._sequence, envelope=envelope
            )
            heapq.heappush(self._queue, queued)
        self._record_dispatch(envelope, f"QUEUE_{priority.name}")

    async def _dequeue(self) -> QueuedCommand | None:
        with self._queue_lock:
            if not self._queue:
                return None
            return heapq.heappop(self._queue)

    async def _execute_queued_command(self, queued: QueuedCommand) -> None:
        envelope = queued.envelope
        start_time = time.time()
        try:
            handler = self._registry.get_handler(envelope.command_type)
            if asyncio.iscoroutinefunction(handler):
                result = await handler(envelope.command_data)
            else:
                result = handler(envelope.command_data)
            envelope.status = CommandStatus.SUCCESS
            envelope.result = result
        except HandlerNotFoundError:
            envelope.status = CommandStatus.REJECTED
            envelope.error = f"No handler for {envelope.command_type}"
        except Exception as e:
            envelope.status = CommandStatus.FAILED
            envelope.error = str(e)
            logger.error(f"Queued command {envelope.command_id} failed: {e}")
        envelope.execution_time_ms = (time.time() - start_time) * 1000
        self._record_dispatch(envelope, "QUEUE_EXECUTED")

    def _record_dispatch(self, envelope: CommandEnvelope, method: str) -> None:
        record = {
            "command_id": str(envelope.command_id),
            "command_type": envelope.command_type,
            "method": method,
            "status": envelope.status.name if envelope.status else "UNKNOWN",
            "timestamp": datetime.now(UTC).isoformat(),
            "execution_time_ms": envelope.execution_time_ms,
            "error": envelope.error[:200] if envelope.error else None,
        }
        self._dispatch_history.append(record)
        if len(self._dispatch_history) > self._max_history:
            self._dispatch_history = self._dispatch_history[-self._max_history :]

    def get_queue_size(self) -> int:
        with self._queue_lock:
            return len(self._queue)

    def get_dispatch_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._dispatch_history[-limit:]

    def get_statistics(self) -> dict[str, Any]:
        with self._queue_lock:
            queue_size = len(self._queue)
        success_count = len([d for d in self._dispatch_history if d.get("status") == "SUCCESS"])
        failed_count = len([d for d in self._dispatch_history if d.get("status") == "FAILED"])
        rejected_count = len([d for d in self._dispatch_history if d.get("status") == "REJECTED"])
        by_command_type = {}
        for d in self._dispatch_history:
            ct = d.get("command_type", "unknown")
            by_command_type[ct] = by_command_type.get(ct, 0) + 1
        return {
            "queue_size": queue_size,
            "worker_count": self._worker_count,
            "running": self._running,
            "strategy": self._strategy.name,
            "max_queue_size": self._max_queue_size,
            "total_dispatches": len(self._dispatch_history),
            "success_count": success_count,
            "failed_count": failed_count,
            "rejected_count": rejected_count,
            "by_command_type": by_command_type,
        }

    def set_strategy(self, strategy: DispatchStrategy) -> None:
        self._strategy = strategy
        logger.info(f"Dispatch strategy set to {strategy.name}")

    def set_max_queue_size(self, max_size: int) -> None:
        self._max_queue_size = max_size

    def set_reject_when_queue_full(self, reject: bool) -> None:
        self._reject_when_queue_full = reject

    def clear_queue(self) -> int:
        with self._queue_lock:
            count = len(self._queue)
            self._queue.clear()
            self._sequence = 0
        logger.warning(f"Cleared {count} commands from queue")
        return count

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._max_queue_size <= 0:
            errors.append("max_queue_size must be positive")
        if self._worker_count < 0:
            errors.append("worker_count cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_count": self._worker_count,
            "running": self._running,
            "strategy": self._strategy.name,
            "max_queue_size": self._max_queue_size,
            "reject_when_queue_full": self._reject_when_queue_full,
            "total_dispatches": len(self._dispatch_history),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandDispatcher:
        instance = cls()
        instance._worker_count = data.get("worker_count", 4)
        instance._running = data.get("running", False)
        instance._strategy = DispatchStrategy[data.get("strategy", "PRIORITY_QUEUE")]
        instance._max_queue_size = data.get("max_queue_size", 10000)
        instance._reject_when_queue_full = data.get("reject_when_queue_full", True)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> CommandDispatcher:
        new_instance = CommandDispatcher()
        new_instance._worker_count = self._worker_count
        new_instance._strategy = self._strategy
        new_instance._max_queue_size = self._max_queue_size
        new_instance._reject_when_queue_full = self._reject_when_queue_full
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "queue_size": self.get_queue_size(),
            "running": self._running,
            "worker_count": self._worker_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CommandDispatcher:
        self._version += 1
        self._audit_trail.append(
            {
                "action": "TOUCH",
                "performed_by": touched_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
            }
        )
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def reset(self) -> None:
        with self._queue_lock:
            self._queue.clear()
        self._dispatch_history = []
        self._sequence = 0
        self._running = False
        if self._workers:
            for task in self._workers:
                task.cancel()
            self._workers.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []


# === 3. SINGLETON ACCESSOR ===
_command_dispatcher_instance: CommandDispatcher | None = None


def get_command_dispatcher() -> CommandDispatcher:
    global _command_dispatcher_instance
    if _command_dispatcher_instance is None:
        _command_dispatcher_instance = CommandDispatcher()
    return _command_dispatcher_instance


__all__ = [
    "CommandDispatcher",
    "DispatchPriority",
    "DispatchStrategy",
    "QueuedCommand",
    "get_command_dispatcher",
]
