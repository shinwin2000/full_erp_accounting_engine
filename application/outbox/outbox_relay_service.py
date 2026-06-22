#!/usr/bin/env python3
"""
Module: outbox_relay_service.py
Layer: Application / Outbox
Responsibility: Service untuk memproses dan mengirim pesan outbox ke message broker.
"""

from __future__ import annotationsimport asyncioimport contextlibimport loggingimport timefrom dataclasses import dataclassfrom datetime import datetimefrom enum import Enumfrom typing import Any, Protocolfrom application.outbox.outbox_exceptions import (    OutboxConfigurationError,    OutboxPublishFatalError,    OutboxPublishRetryableError,    OutboxRelayStoppedError,)logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class OutboxRecordStatus(str, Enum):
    """Status record outbox."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


# ============================================================================
# PROTOCOLS (PORTS)
# ============================================================================

class OutboxRepositoryPort(Protocol):
    """Port untuk outbox repository."""

    async def get_pending_events(
        self, limit: int, lock_timeout_seconds: int
    ) -> list[dict[str, Any]]:
        """Get pending events with row lock."""
        ...

    async def mark_as_processing(self, record_id: int) -> bool:
        """Mark record as processing."""
        ...

    async def mark_as_published(self, record_id: int, kafka_offset: int | None = None) -> None:
        """Mark record as published."""
        ...

    async def mark_as_failed(
        self, record_id: int, error_message: str, retry_count: int
    ) -> None:
        """Mark record as failed, increment retry count."""
        ...

    async def mark_as_dead_letter(self, record_id: int, error_message: str) -> None:
        """Move record to dead letter queue."""
        ...

    async def delete_processed_records(self, older_than_hours: int = 168) -> int:
        """Delete records that were successfully published."""
        ...


class MessageBrokerPort(Protocol):
    """Port untuk message broker (Kafka)."""

    async def send(
        self, topic: str, key: str, value: str, headers: dict[str, str] | None = None
    ) -> None:
        """Send message to broker."""
        ...

    async def start(self) -> None:
        """Start broker connection."""
        ...

    async def stop(self) -> None:
        """Stop broker connection."""
        ...

    async def health_check(self) -> bool:
        """Check broker health."""
        ...


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(kw_only=True)
class OutboxRelayConfig:
    """Konfigurasi untuk OutboxRelayService."""
    batch_size: int = 100
    poll_interval_seconds: float = 1.0
    max_retries: int = 3
    retry_delay_seconds: float = 5.0
    lock_timeout_seconds: int = 30
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 60.0
    enable_circuit_breaker: bool = True
    dead_letter_topic: str = "erp.dead_letter_events"
    default_topic: str = "erp.accounting.general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "poll_interval_seconds": self.poll_interval_seconds,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "lock_timeout_seconds": self.lock_timeout_seconds,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "circuit_breaker_recovery_timeout": self.circuit_breaker_recovery_timeout,
            "enable_circuit_breaker": self.enable_circuit_breaker,
            "dead_letter_topic": self.dead_letter_topic,
            "default_topic": self.default_topic,
        }


# ============================================================================
# CIRCUIT BREAKER
# ============================================================================

class CircuitBreaker:
    """Simple circuit breaker untuk outbox publisher."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_failure_time: float | None = None
        self._state: str = "closed"  # closed, open, half-open

    @property
    def state(self) -> str:
        self._check_recovery()
        return self._state

    def _check_recovery(self) -> None:
        if self._state == "open" and self._last_failure_time:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = "half-open"
                logger.info(f"Circuit breaker '{self.name}' transitioned to half-open")

    def record_success(self) -> None:
        if self._state == "half-open":
            self._state = "closed"
            self._failures = 0
            logger.info(f"Circuit breaker '{self.name}' closed after success")
        else:
            self._failures = max(0, self._failures - 1)

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.time()

        if self._failures >= self.failure_threshold and self._state != "open":
            self._state = "open"
            logger.warning(
                f"Circuit breaker '{self.name}' opened after {self._failures} failures"
            )

    def can_execute(self) -> bool:
        return self.state != "open"

    def get_stats(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "failures": self._failures,
            "threshold": self.failure_threshold,
            "last_failure_time": self._last_failure_time,
        }


# ============================================================================
# RETRY POLICY
# ============================================================================

def exponential_backoff(attempt: int, base_delay: float = 0.5, max_delay: float = 10.0) -> float:
    """Calculate exponential backoff delay."""
    return min(base_delay * (2 ** attempt), max_delay)


class RetryPolicy:
    """Retry policy untuk outbox publishing."""

    def __init__(self, max_attempts: int = 3, base_delay: float = 0.5, max_delay: float = 10.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._attempts = 0

    @property
    def attempts(self) -> int:
        return self._attempts

    async def execute(self, func, *args, **kwargs):
        """Execute function with retry."""
        last_error = None
        for attempt in range(self.max_attempts):
            self._attempts = attempt + 1
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_attempts - 1:
                    delay = exponential_backoff(attempt, self.base_delay, self.max_delay)
                    logger.warning(
                        f"Attempt {attempt + 1} failed, retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
        raise last_error


# ============================================================================
# OUTBOX RELAY SERVICE
# ============================================================================

class OutboxRelayService:
    """
    Service untuk mengambil pesan outbox dari database dan mengirimkannya ke Kafka.
    """

    def __init__(
        self,
        outbox_repository: OutboxRepositoryPort,
        message_broker: MessageBrokerPort,
        config: OutboxRelayConfig | None = None,
    ):
        """
        Args:
            outbox_repository: Repository untuk outbox records.
            message_broker: Message broker untuk publish event.
            config: Konfigurasi relay service.
        """
        if outbox_repository is None:
            raise OutboxConfigurationError("outbox_repository is required")
        if message_broker is None:
            raise OutboxConfigurationError("message_broker is required")

        self._repository = outbox_repository
        self._broker = message_broker
        self._config = config or OutboxRelayConfig()
        self._running = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        # Circuit breaker
        self._circuit_breaker = CircuitBreaker(
            name="outbox_publisher",
            failure_threshold=self._config.circuit_breaker_threshold,
            recovery_timeout=self._config.circuit_breaker_recovery_timeout,
        ) if self._config.enable_circuit_breaker else None

        # Retry policy
        self._retry_policy = RetryPolicy(
            max_attempts=self._config.max_retries,
            base_delay=self._config.retry_delay_seconds,
        )

        # Statistics
        self._stats = {
            "processed": 0,
            "published": 0,
            "failed": 0,
            "dead_letter": 0,
            "last_error": None,
            "last_error_time": None,
            "started_at": None,
            "circuit_breaker_stats": None,
        }

        logger.info(f"OutboxRelayService initialized: batch_size={self._config.batch_size}")

    async def start(self) -> None:
        """Start the relay service."""
        if self._running:
            logger.warning("OutboxRelayService already running")
            return

        self._running = True
        self._stop_event.clear()
        self._stats["started_at"] = datetime.now().isoformat()

        # Start message broker
        await self._broker.start()

        # Start relay loop
        self._task = asyncio.create_task(self._relay_loop())
        logger.info("OutboxRelayService started")

    async def stop(self, timeout: float = 30.0) -> None:
        """Stop the relay service."""
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

        await self._broker.stop()
        logger.info("OutboxRelayService stopped")

    async def _relay_loop(self) -> None:
        """Main relay loop."""
        while self._running:
            try:
                # Wait for next poll interval or stop event
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._config.poll_interval_seconds
                    )
                    break
                except TimeoutError:
                    pass

                # Process batch
                if self._circuit_breaker and not self._circuit_breaker.can_execute():
                    logger.warning("Circuit breaker open, skipping batch processing")
                    await asyncio.sleep(5)
                    continue

                await self._process_batch()

            except OutboxRelayStoppedError:
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Unexpected error in relay loop: {e}")
                await asyncio.sleep(1)

    async def _process_batch(self) -> None:
        """Internal wrapper to call process_batch with default batch size."""
        await self.process_batch(self._config.batch_size)

    async def process_batch(self, batch_size: int | None = None) -> int:
        """
        Process a single batch of outbox records.
        
        Args:
            batch_size: Number of records to process (overrides config)
            
        Returns:
            Number of records processed
        """
        if not self._running:
            raise OutboxRelayStoppedError("Relay service is stopped")

        size = batch_size or self._config.batch_size

        try:
            # Get pending events � menggunakan positional arguments, bukan keyword
            records = await self._repository.get_pending_events(
                size, self._config.lock_timeout_seconds
            )

            if not records:
                return 0

            processed = 0

            for record in records:
                try:
                    # Mark as processing
                    await self._repository.mark_as_processing(record["id"])

                    # Publish to broker with retry
                    await self._retry_policy.execute(
                        self._publish_record, record
                    )

                    # Mark as published
                    await self._repository.mark_as_published(record["id"])

                    self._stats["published"] += 1
                    processed += 1

                    if self._circuit_breaker:
                        self._circuit_breaker.record_success()

                except OutboxPublishRetryableError as e:
                    # Retryable error - will be retried in next batch
                    logger.warning(f"Retryable error for record {record['id']}: {e}")
                    self._stats["failed"] += 1

                    if self._circuit_breaker:
                        self._circuit_breaker.record_failure()

                    # Increment retry count
                    retry_count = record.get("retry_count", 0) + 1
                    if retry_count >= self._config.max_retries:
                        # Move to dead letter
                        await self._repository.mark_as_dead_letter(
                            record["id"], str(e)
                        )
                        self._stats["dead_letter"] += 1
                        logger.error(f"Record {record['id']} moved to dead letter after {retry_count} retries")
                    else:
                        await self._repository.mark_as_failed(
                            record["id"], str(e), retry_count
                        )

                except Exception as e:
                    # Fatal error
                    logger.error(f"Fatal error for record {record['id']}: {e}")
                    await self._repository.mark_as_dead_letter(record["id"], str(e))
                    self._stats["failed"] += 1
                    self._stats["dead_letter"] += 1

                    if self._circuit_breaker:
                        self._circuit_breaker.record_failure()

            self._stats["processed"] += processed

            # Clean up old records periodically
            if self._stats["processed"] % 100 == 0:
                deleted = await self._repository.delete_processed_records()
                if deleted > 0:
                    logger.info(f"Deleted {deleted} old processed records")

            return processed

        except Exception as e:
            self._stats["last_error"] = str(e)
            self._stats["last_error_time"] = datetime.now().isoformat()
            logger.exception(f"Error processing batch: {e}")
            raise

    async def _publish_record(self, record: dict[str, Any]) -> None:
        """Publish a single record to message broker."""
        try:
            # Determine topic
            topic = record.get("topic", self._config.default_topic)

            # Parse headers
            headers = {
                "event_type": record["event_type"],
                "correlation_id": record["correlation_id"],
                "content-type": "application/json",
            }
            if record.get("idempotency_key"):
                headers["idempotency_key"] = record["idempotency_key"]

            # Send to broker
            await self._broker.send(
                topic=topic,
                key=str(record["event_id"]),
                value=record["payload"],
                headers=headers,
            )

            logger.debug(f"Published record {record['id']} to topic {topic}")

        except Exception as e:
            if self._is_retryable_error(e):
                raise OutboxPublishRetryableError(str(e)) from e
            else:
                raise OutboxPublishFatalError(str(e)) from e

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if error is retryable."""
        retryable_exceptions = (
            ConnectionError,
            TimeoutError,
            ConnectionRefusedError,
            ConnectionResetError,
        )
        return isinstance(error, retryable_exceptions) or "timeout" in str(error).lower()

    async def health_check(self) -> dict[str, Any]:
        """Perform health check."""
        try:
            broker_healthy = await self._broker.health_check()

            return {
                "healthy": broker_healthy and self._running,
                "running": self._running,
                "broker_healthy": broker_healthy,
                "circuit_breaker_state": self._circuit_breaker.state if self._circuit_breaker else "disabled",
            }
        except Exception as e:
            return {
                "healthy": False,
                "running": self._running,
                "error": str(e),
            }

    def get_stats(self) -> dict[str, Any]:
        """Get relay service statistics."""
        if self._circuit_breaker:
            self._stats["circuit_breaker_stats"] = self._circuit_breaker.get_stats()

        return {**self._stats, "config": self._config.to_dict()}

    async def trigger_immediate_batch(self) -> int:
        """Trigger an immediate batch processing (for testing)."""
        return await self.process_batch()


# ============================================================================
# SINGLETON INSTANCE & HELPER FUNCTIONS
# ============================================================================

_relay_service_instance: OutboxRelayService | None = None


def get_relay_service() -> OutboxRelayService | None:
    """Get the global outbox relay service instance."""
    return _relay_service_instance


def create_relay_service(
    outbox_repository: OutboxRepositoryPort,
    message_broker: MessageBrokerPort,
    config: OutboxRelayConfig | None = None,
) -> OutboxRelayService:
    """
    Create and set the global outbox relay service instance.
    
    Args:
        outbox_repository: Repository for outbox records.
        message_broker: Message broker for publishing events.
        config: Configuration for the relay service.
        
    Returns:
        The created OutboxRelayService instance.
    """
    global _relay_service_instance
    _relay_service_instance = OutboxRelayService(
        outbox_repository=outbox_repository,
        message_broker=message_broker,
        config=config,
    )
    return _relay_service_instance


async def start_relay(
    outbox_repository: OutboxRepositoryPort,
    message_broker: MessageBrokerPort,
    config: OutboxRelayConfig | None = None,
) -> OutboxRelayService:
    """
    Create, start, and return the global outbox relay service.
    
    This is a convenience function used by the ASGI application.
    
    Args:
        outbox_repository: Repository for outbox records.
        message_broker: Message broker for publishing events.
        config: Configuration for the relay service.
        
    Returns:
        The started OutboxRelayService instance.
    """
    service = create_relay_service(outbox_repository, message_broker, config)
    await service.start()
    logger.info("Outbox relay service started via start_relay()")
    return service


async def stop_relay() -> None:
    """Stop the global outbox relay service if running."""
    global _relay_service_instance
    if _relay_service_instance:
        await _relay_service_instance.stop()
        _relay_service_instance = None
        logger.info("Outbox relay service stopped via stop_relay()")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "MessageBrokerPort",    "OutboxRecordStatus",    "OutboxRelayConfig",    "OutboxRelayService",    "OutboxRepositoryPort",    "create_relay_service",    "get_relay_service",    "start_relay",    "stop_relay",
]