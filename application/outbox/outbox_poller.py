# outbox_poller.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: outbox_poller.py

Layer: 5 - Application / Events / Outbox

Responsibility:
    Poller untuk transactional outbox pattern. Poller ini bertanggung jawab
    mengambil event dari outbox table secara periodik dan memicu publish
    melalui relay service.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from application.outbox.outbox_exceptions import (
    OutboxPollerStoppedError,
)

if TYPE_CHECKING:
    from application.outbox.outbox_relay_service import OutboxRelayService

logger = logging.getLogger(__name__)


# ============================================================================
# PROTOCOLS
# ============================================================================


class DatabaseLockPort(Protocol):
    """Abstraksi untuk database advisory lock."""

    async def try_lock(self, lock_name: str, timeout_seconds: int) -> bool:
        """Try to acquire lock. Returns True if acquired."""
        ...

    async def unlock(self, lock_name: str) -> None:
        """Release lock."""
        ...

    async def extend_lock(self, lock_name: str, timeout_seconds: int) -> bool:
        """Extend lock timeout. Returns True if successful."""
        ...

    async def is_locked(self, lock_name: str) -> bool:
        """Check if lock is held."""
        ...


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass(kw_only=True)
class OutboxPollerConfig:
    """Konfigurasi untuk OutboxPoller."""

    poll_interval_seconds: float = 1.0
    use_advisory_lock: bool = True
    lock_timeout_seconds: int = 30
    lock_name: str = "outbox_poller_lock"
    batch_size: int = 100
    max_concurrent_batches: int = 1
    health_check_interval_seconds: float = 60.0
    max_retry_count: int = 3
    retry_delay_seconds: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "poll_interval_seconds": self.poll_interval_seconds,
            "use_advisory_lock": self.use_advisory_lock,
            "lock_timeout_seconds": self.lock_timeout_seconds,
            "lock_name": self.lock_name,
            "batch_size": self.batch_size,
            "max_concurrent_batches": self.max_concurrent_batches,
            "health_check_interval_seconds": self.health_check_interval_seconds,
            "max_retry_count": self.max_retry_count,
            "retry_delay_seconds": self.retry_delay_seconds,
        }


# ============================================================================
# SIMPLE MEMORY LOCK (FALLBACK)
# ============================================================================


class MemoryLockPort:
    """Simple in-memory lock for testing/fallback."""

    def __init__(self):
        self._locks: dict[str, bool] = {}
        self._lock_times: dict[str, float] = {}

    async def try_lock(self, lock_name: str, timeout_seconds: int) -> bool:
        if self._locks.get(lock_name):
            if time.time() - self._lock_times.get(lock_name, 0) < timeout_seconds:
                return False
            # Lock expired
            self._locks[lock_name] = False
        self._locks[lock_name] = True
        self._lock_times[lock_name] = time.time()
        return True

    async def unlock(self, lock_name: str) -> None:
        self._locks[lock_name] = False
        self._lock_times.pop(lock_name, None)

    async def extend_lock(self, lock_name: str, timeout_seconds: int) -> bool:
        if self._locks.get(lock_name):
            self._lock_times[lock_name] = time.time()
            return True
        return False

    async def is_locked(self, lock_name: str) -> bool:
        return self._locks.get(lock_name, False)


# ============================================================================
# OUTBOX POLLER
# ============================================================================


class OutboxPoller:
    """
    Poller untuk menjalankan OutboxRelayService secara periodik.
    Semua dependency diberikan melalui constructor.
    """

    def __init__(
        self,
        relay_service: OutboxRelayService,
        db_lock: DatabaseLockPort | None = None,
        config: OutboxPollerConfig | None = None,
    ):
        """
        Args:
            relay_service: Instance OutboxRelayService yang akan dipanggil.
            db_lock: Implementasi lock database (optional, fallback ke memory lock).
            config: Konfigurasi poller (optional).
        """
        self._relay = relay_service
        self._db_lock = db_lock or MemoryLockPort()
        self._config = config or OutboxPollerConfig()
        self._running = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._lock_acquired = False
        self._stats = {
            "poll_count": 0,
            "lock_acquisitions": 0,
            "lock_failures": 0,
            "last_poll_at": None,
            "last_lock_acquired_at": None,
            "last_error": None,
            "last_error_time": None,
        }

        logger.info(
            f"OutboxPoller initialized: interval={self._config.poll_interval_seconds}s, "
            f"use_lock={self._config.use_advisory_lock}, batch_size={self._config.batch_size}"
        )

    async def start(self) -> None:
        """Start the poller background loop."""
        if self._running:
            logger.warning("OutboxPoller already running")
            return

        self._running = True
        self._stop_event.clear()

        # Start relay service first
        await self._relay.start()

        # Start poller task
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("OutboxPoller started")

    async def stop(self, timeout: float = 30.0) -> None:
        """Stop the poller and clean up."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=timeout)
            except TimeoutError:
                logger.warning(f"Stop timeout after {timeout}s, cancelling")
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

        await self._release_lock()
        await self._relay.stop(timeout=timeout)
        logger.info("OutboxPoller stopped")

    async def _poll_loop(self) -> None:
        """Main poller loop."""
        last_health_check = time.time()
        consecutive_errors = 0

        while self._running:
            try:
                # Wait for next poll interval or stop signal
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._config.poll_interval_seconds
                    )
                    break
                except TimeoutError:
                    pass

                # Health check periodically
                now = time.time()
                if now - last_health_check >= self._config.health_check_interval_seconds:
                    await self._health_check()
                    last_health_check = now

                # Acquire lock if needed
                if self._config.use_advisory_lock:
                    acquired = await self._acquire_lock()
                    if not acquired:
                        logger.debug("Another poller has lock, skipping")
                        continue

                # Process outbox records
                self._stats["poll_count"] += 1
                self._stats["last_poll_at"] = datetime.now().isoformat()

                try:
                    # Process batch via relay service
                    processed_count = await self._relay.process_batch(self._config.batch_size)

                    if processed_count > 0:
                        logger.info(f"Processed {processed_count} outbox records")
                        consecutive_errors = 0
                    else:
                        # No records to process, just continue
                        pass

                except OutboxPublishRetryableError as e:
                    consecutive_errors += 1
                    self._stats["last_error"] = str(e)
                    self._stats["last_error_time"] = datetime.now().isoformat()
                    logger.warning(f"Retryable error during batch processing: {e}")

                    if consecutive_errors >= self._config.max_retry_count:
                        logger.error(
                            f"Max retry count reached ({self._config.max_retry_count}), backing off"
                        )
                        await asyncio.sleep(self._config.retry_delay_seconds)
                        consecutive_errors = 0
                    else:
                        await asyncio.sleep(1)

                except Exception as e:
                    consecutive_errors += 1
                    self._stats["last_error"] = str(e)
                    self._stats["last_error_time"] = datetime.now().isoformat()
                    logger.exception(f"Error in poller loop: {e}")

                    if consecutive_errors >= self._config.max_retry_count:
                        await asyncio.sleep(self._config.retry_delay_seconds)
                        consecutive_errors = 0

            except OutboxPollerStoppedError:
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Unexpected error in poller loop: {e}")
                await asyncio.sleep(1)
            finally:
                if self._config.use_advisory_lock and self._lock_acquired:
                    await self._release_lock()

    async def _acquire_lock(self) -> bool:
        """Acquire advisory lock."""
        try:
            # Try to extend existing lock first
            if self._lock_acquired:
                extended = await self._db_lock.extend_lock(
                    self._config.lock_name, self._config.lock_timeout_seconds
                )
                if extended:
                    return True
                # Lock expired, need to re-acquire
                await self._release_lock()

            acquired = await self._db_lock.try_lock(
                self._config.lock_name, self._config.lock_timeout_seconds
            )

            if acquired:
                self._lock_acquired = True
                self._stats["lock_acquisitions"] += 1
                self._stats["last_lock_acquired_at"] = datetime.now().isoformat()
                logger.debug(f"Lock acquired: {self._config.lock_name}")
            else:
                self._stats["lock_failures"] += 1

            return acquired
        except Exception as e:
            logger.error(f"Error acquiring lock: {e}")
            self._stats["lock_failures"] += 1
            return False

    async def _release_lock(self) -> None:
        """Release advisory lock."""
        if not self._lock_acquired:
            return

        try:
            await self._db_lock.unlock(self._config.lock_name)
            self._lock_acquired = False
            logger.debug(f"Lock released: {self._config.lock_name}")
        except Exception as e:
            logger.error(f"Error releasing lock: {e}")

    async def _health_check(self) -> None:
        """Perform health check."""
        try:
            # Check if relay service is healthy
            relay_health = await self._relay.health_check()

            # Check lock status
            if self._config.use_advisory_lock:
                locked = await self._db_lock.is_locked(self._config.lock_name)
                if locked != self._lock_acquired:
                    logger.warning(
                        f"Lock status mismatch: expected {self._lock_acquired}, got {locked}"
                    )

            logger.debug(f"Health check passed: relay_health={relay_health}")

        except Exception as e:
            logger.error(f"Health check failed: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Get poller statistics."""
        return {
            **self._stats,
            "running": self._running,
            "lock_acquired": self._lock_acquired,
            "relay_stats": self._relay.get_stats(),
            "config": self._config.to_dict(),
        }

    async def trigger_immediate_poll(self) -> int:
        """Trigger an immediate poll (for testing or manual trigger)."""
        logger.info("Manual trigger: immediate poll requested")

        if self._config.use_advisory_lock:
            acquired = await self._acquire_lock()
            if not acquired:
                logger.warning("Cannot acquire lock for immediate poll")
                return 0

        try:
            processed = await self._relay.process_batch(self._config.batch_size)
            logger.info(f"Manual poll processed {processed} records")
            return processed
        finally:
            if self._config.use_advisory_lock and self._lock_acquired:
                await self._release_lock()


# ============================================================================
# SIMPLE POLLER FUNCTION (NO LOCK, FOR TESTING)
# ============================================================================


async def run_outbox_poller_simple(
    relay_service: OutboxRelayService,
    poll_interval: float = 1.0,
    stop_event: asyncio.Event | None = None,
    batch_size: int = 100,
) -> None:
    """
    Simple poller function yang menjalankan relay service tanpa lock.
    """
    await relay_service.start()

    try:
        while True:
            if stop_event and stop_event.is_set():
                break

            try:
                processed = await relay_service.process_batch(batch_size)
                if processed > 0:
                    logger.debug(f"Processed {processed} outbox records")
            except Exception as e:
                logger.exception(f"Error processing batch: {e}")

            await asyncio.sleep(poll_interval)
    finally:
        await relay_service.stop()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DatabaseLockPort",
    "MemoryLockPort",
    "OutboxPoller",
    "OutboxPollerConfig",
    "run_outbox_poller_simple",
]
