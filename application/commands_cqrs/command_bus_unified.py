# command_bus_unified.py - Hardened version with BaseCommand (fix P56)
# Ganti seluruh isi file dengan kode di bawah

#!/usr/bin/env python3

"""
Module: command_bus_unified.py

Layer: 5 - Application / Commands CQRS

Responsibility:
    Unified command bus untuk CQRS pattern. Command bus ini bertanggung jawab
    menerima command, melakukan validasi awal, routing ke handler yang sesuai,
    dan mengeksekusi command dengan audit trail. Mendukung synchronous execution,
    transactional outbox untuk event, dan idempotency.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from uuid import UUID, uuid4

# Command related imports
from application.commands_cqrs.command_handler_registry import (
    CommandHandlerRegistry,
    command_handler_registry,
)
from application.commands_cqrs.command_result_envelope import CommandResult
from application.commands_cqrs.command_validator import CommandValidator, get_command_validator
from kernel.audit_hook_injector import AuditHookInjector
from kernel.context_holder import ContextHolder

# Kernel imports
from kernel.sealed_gate import SealedGate, get_sealed_gate
from kernel.transactional_executor import TransactionalExecutor

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


# === 1. CACHE PORT IMPLEMENTATION ===


class CachePort:
    """Abstraksi untuk cache (Redis) dengan implementasi lengkap."""

    def __init__(self, redis_client: Any = None, fallback_memory: bool = True):
        self._redis = redis_client
        self._memory_cache: dict[str, tuple[Any, float]] = {}
        self._fallback_memory = fallback_memory

    async def exists(self, key: str) -> bool:
        if self._redis:
            try:
                return await self._redis.exists(key)
            except Exception:
                pass
        if self._fallback_memory:
            return key in self._memory_cache and self._memory_cache[key][1] > time.time()
        return False

    async def get(self, key: str) -> str | None:
        if self._redis:
            try:
                value = await self._redis.get(key)
                if value:
                    return value
            except Exception:
                pass
        if self._fallback_memory and key in self._memory_cache:
            value, expiry = self._memory_cache[key]
            if expiry > time.time():
                return value
            del self._memory_cache[key]
        return None

    async def setex(self, key: str, ttl: int, value: str) -> None:
        if self._redis:
            try:
                await self._redis.setex(key, ttl, value)
                return
            except Exception:
                pass
        if self._fallback_memory:
            self._memory_cache[key] = (value, time.time() + ttl)

    async def delete(self, key: str) -> None:
        if self._redis:
            try:
                await self._redis.delete(key)
            except Exception:
                pass
        if self._fallback_memory:
            self._memory_cache.pop(key, None)

    async def clear(self) -> None:
        if self._redis:
            try:
                await self._redis.flushdb()
            except Exception:
                pass
        if self._fallback_memory:
            self._memory_cache.clear()


class MetricsPort:
    """Abstraksi untuk metrics (Prometheus) dengan implementasi lengkap."""

    def __init__(self):
        self._commands_dispatched: dict[str, int] = {}
        self._commands_failed: dict[str, dict[str, int]] = {}
        self._command_latencies: list[float] = []
        self._max_latency_samples = 10000

    def inc_commands_dispatched(self, command_type: str) -> None:
        self._commands_dispatched[command_type] = self._commands_dispatched.get(command_type, 0) + 1

    def inc_commands_failed(self, command_type: str, reason: str) -> None:
        if command_type not in self._commands_failed:
            self._commands_failed[command_type] = {}
        self._commands_failed[command_type][reason] = (
            self._commands_failed[command_type].get(reason, 0) + 1
        )

    def observe_command_latency(self, latency_seconds: float) -> None:
        self._command_latencies.append(latency_seconds)
        if len(self._command_latencies) > self._max_latency_samples:
            self._command_latencies = self._command_latencies[-self._max_latency_samples :]

    def get_stats(self) -> dict[str, Any]:
        avg_latency = (
            sum(self._command_latencies) / len(self._command_latencies)
            if self._command_latencies
            else 0
        )
        return {
            "commands_dispatched": self._commands_dispatched,
            "commands_failed": self._commands_failed,
            "total_dispatched": sum(self._commands_dispatched.values()),
            "total_failed": sum(
                sum(reason_counts.values()) for reason_counts in self._commands_failed.values()
            ),
            "avg_latency_seconds": avg_latency,
            "p95_latency_seconds": self._calculate_percentile(95),
            "p99_latency_seconds": self._calculate_percentile(99),
        }

    def _calculate_percentile(self, percentile: int) -> float:
        if not self._command_latencies:
            return 0.0
        sorted_latencies = sorted(self._command_latencies)
        index = int(len(sorted_latencies) * percentile / 100)
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]


class TracerPort:
    """Abstraksi untuk tracing (OpenTelemetry) dengan implementasi lengkap."""

    def __init__(self):
        self._spans: list[Span] = []

    def start_span(self, name: str) -> Span:
        span = Span(name)
        self._spans.append(span)
        return span

    def get_spans(self) -> list[Span]:
        return self._spans.copy()


class Span:
    """Span implementation for tracing."""

    def __init__(self, name: str):
        self.name = name
        self.start_time = time.time()
        self.end_time: float | None = None
        self.attributes: dict[str, Any] = {}
        self.status: str = "OK"
        self.status_description: str = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.end()

    def end(self):
        self.end_time = time.time()

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_status(self, status: Any, description: str = "") -> None:
        self.status = str(status)
        self.status_description = description

    def get_duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000


# === 2. BASE COMMAND CLASS (renamed from Command) ===


class BaseCommand(Generic[T]):
    """
    Base class untuk semua command.
    Setiap command minimal harus memiliki command_id dan command_type.
    """

    __slots__ = (
        "_result",
        "command_id",
        "command_type",
        "correlation_id",
        "idempotency_key",
        "metadata",
        "occurred_at",
        "source_ip",
        "tenant_id",
        "user_agent",
        "user_id",
    )

    def __init__(
        self,
        command_type: str,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        tenant_id: UUID | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.command_id = uuid4()
        self.command_type = command_type
        self.occurred_at = datetime.now(UTC)
        self.user_id = user_id
        self.correlation_id = correlation_id or str(uuid4())
        self.idempotency_key = idempotency_key or str(uuid4())
        self.tenant_id = tenant_id
        self.source_ip = source_ip
        self.user_agent = user_agent
        self.metadata = metadata or {}
        self._result: CommandResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Konversi command ke dictionary untuk logging/audit.
        Manual construction to avoid __slots__ conflict with __dict__.
        """
        return {
            "command_id": str(self.command_id),
            "command_type": self.command_type,
            "occurred_at": self.occurred_at.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "source_ip": self.source_ip,
            "user_agent": self.user_agent,
            "metadata": self.metadata,
        }

    def set_result(self, result: CommandResult) -> None:
        """Set the command result for audit purposes."""
        self._result = result

    def get_result(self) -> CommandResult | None:
        """Get the command result."""
        return self._result

    def __repr__(self) -> str:
        return f"BaseCommand({self.command_type}, id={self.command_id})"


# === ALIAS UNTUK KOMPATIBILITAS ===
# P49 dan berbagai file workflow mengimpor 'Command' (tanpa Base)
# Kita buat alias agar import tetap berfungsi
Command = BaseCommand


# === 3. COMMAND BUS EXCEPTIONS ===


class CommandBusError(Exception):
    """Base exception untuk command bus."""

    pass


class CommandNotFoundError(CommandBusError):
    """Tidak ada handler terdaftar untuk command type."""

    pass


class CommandValidationError(CommandBusError):
    """Command gagal validasi."""

    pass


class CommandExecutionError(CommandBusError):
    """Error saat eksekusi command handler."""

    pass


class DuplicateCommandError(CommandBusError):
    """Command dengan idempotency key yang sama sudah pernah dieksekusi."""

    pass


class CommandTimeoutError(CommandBusError):
    """Command execution timeout."""

    pass


class CommandBusClosedError(CommandBusError):
    """Command bus is closed."""

    pass


# === 4. MIDDLEWARE PROTOCOL ===


class Middleware:
    """Protocol untuk middleware pipeline."""

    def __init__(self, name: str | None = None):
        self.name = name or self.__class__.__name__

    async def process(
        self,
        command: BaseCommand,
        handler: Callable[[BaseCommand], Awaitable[CommandResult]],
        context: dict[str, Any],
    ) -> CommandResult:
        """Process command dengan middleware. Panggil handler jika middleware ingin melanjutkan."""
        return await handler(command)


class LoggingMiddleware(Middleware):
    """Middleware untuk logging command dispatch."""

    def __init__(self, log_payload: bool = True, log_result: bool = False):
        super().__init__("LoggingMiddleware")
        self._log_payload = log_payload
        self._log_result = log_result

    async def process(
        self,
        command: BaseCommand,
        handler: Callable[[BaseCommand], Awaitable[CommandResult]],
        context: dict[str, Any],
    ) -> CommandResult:
        log_data = {
            "command_id": str(command.command_id),
            "command_type": command.command_type,
            "correlation_id": command.correlation_id,
            "user_id": str(command.user_id) if command.user_id else None,
        }
        if self._log_payload:
            log_data["payload"] = command.to_dict()

        logger.info(f"Dispatching command: {command.command_type}", extra=log_data)
        start_time = time.perf_counter()

        try:
            result = await handler(command)
            latency_ms = (time.perf_counter() - start_time) * 1000

            log_result_data = {
                "command_id": str(command.command_id),
                "status": result.status.value if result.status else "unknown",
                "duration_ms": latency_ms,
            }
            if self._log_result and result.data:
                log_result_data["result"] = result.data

            logger.info(
                f"Command {command.command_type} completed in {latency_ms:.2f}ms",
                extra=log_result_data,
            )
            return result
        except Exception as e:
            logger.exception(f"Command {command.command_type} failed: {e}")
            raise


class AuditMiddleware(Middleware):
    """Middleware untuk audit trail."""

    def __init__(self, audit_hook: AuditHookInjector | None = None):
        super().__init__("AuditMiddleware")
        self._audit_hook = audit_hook or AuditHookInjector()

    async def process(
        self,
        command: BaseCommand,
        handler: Callable[[BaseCommand], Awaitable[CommandResult]],
        context: dict[str, Any],
    ) -> CommandResult:
        # Catat command mulai
        start_time = time.perf_counter()
        self._audit_hook.record_command_start(command)

        try:
            result = await handler(command)
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._audit_hook.record_command_end(command, result, duration_ms)
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._audit_hook.record_command_error(command, e, duration_ms)
            raise


class IdempotencyMiddleware(Middleware):
    """Middleware untuk idempotency check."""

    def __init__(self, cache: CachePort | None = None, ttl_seconds: int = 86400 * 7):
        super().__init__("IdempotencyMiddleware")
        self._cache = cache or CachePort()
        self._ttl = ttl_seconds

    async def process(
        self,
        command: BaseCommand,
        handler: Callable[[BaseCommand], Awaitable[CommandResult]],
        context: dict[str, Any],
    ) -> CommandResult:
        if not command.idempotency_key:
            return await handler(command)

        key = f"cmd:idempotency:{command.idempotency_key}"

        # Cek apakah sudah pernah diproses
        exists = await self._cache.exists(key)
        if exists:
            # Ambil hasil yang tersimpan
            cached_result = await self._cache.get(key)
            if cached_result:
                logger.info(f"Duplicate command detected: {command.idempotency_key}")
                try:
                    result = CommandResult.from_json(cached_result)
                    command.set_result(result)
                    return result
                except Exception as e:
                    logger.warning(f"Failed to deserialize cached result: {e}")
                    raise DuplicateCommandError(
                        f"Command with key {command.idempotency_key} already processed"
                    )
            else:
                raise DuplicateCommandError(
                    f"Command with key {command.idempotency_key} already processed"
                )

        # Eksekusi command
        result = await handler(command)
        command.set_result(result)

        # Simpan hasil untuk idempotency (hanya jika sukses)
        if result.is_success():
            await self._cache.setex(key, self._ttl, result.to_json())

        return result


class TransactionMiddleware(Middleware):
    """Middleware untuk transactional execution."""

    def __init__(self, transactional_executor: TransactionalExecutor | None = None):
        super().__init__("TransactionMiddleware")
        self._executor = transactional_executor or TransactionalExecutor()

    async def process(
        self,
        command: BaseCommand,
        handler: Callable[[BaseCommand], Awaitable[CommandResult]],
        context: dict[str, Any],
    ) -> CommandResult:
        # Wrap handler dalam transaksi
        async def _transactional_handler():
            return await handler(command)

        return await self._executor.execute(_transactional_handler)


class TimeoutMiddleware(Middleware):
    """Middleware untuk command timeout."""

    def __init__(self, default_timeout_seconds: float = 60.0):
        super().__init__("TimeoutMiddleware")
        self._default_timeout = default_timeout_seconds

    async def process(
        self,
        command: BaseCommand,
        handler: Callable[[BaseCommand], Awaitable[CommandResult]],
        context: dict[str, Any],
    ) -> CommandResult:
        timeout = command.metadata.get("timeout_seconds", self._default_timeout)

        try:
            return await asyncio.wait_for(handler(command), timeout=timeout)
        except TimeoutError:
            raise CommandTimeoutError(f"Command {command.command_type} timed out after {timeout}s")


class RetryMiddleware(Middleware):
    """Middleware untuk retry failed commands."""

    def __init__(
        self,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ):
        super().__init__("RetryMiddleware")
        self._max_retries = max_retries
        self._retry_delay = retry_delay_seconds
        self._retryable_exceptions = retryable_exceptions

    async def process(
        self,
        command: BaseCommand,
        handler: Callable[[BaseCommand], Awaitable[CommandResult]],
        context: dict[str, Any],
    ) -> CommandResult:
        last_exception = None

        for attempt in range(self._max_retries + 1):
            try:
                return await handler(command)
            except self._retryable_exceptions as e:
                last_exception = e
                if attempt < self._max_retries:
                    delay = self._retry_delay * (attempt + 1)
                    logger.warning(
                        f"Command {command.command_type} failed (attempt {attempt + 1}/{self._max_retries + 1}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Command {command.command_type} failed after {self._max_retries + 1} attempts"
                    )

        raise CommandExecutionError(f"Command failed after retries: {last_exception}")


class RateLimitMiddleware(Middleware):
    """Middleware untuk rate limiting."""

    def __init__(
        self,
        cache: CachePort | None = None,
        max_requests_per_minute: int = 100,
        per_user: bool = True,
    ):
        super().__init__("RateLimitMiddleware")
        self._cache = cache or CachePort()
        self._max_requests = max_requests_per_minute
        self._per_user = per_user

    async def process(
        self,
        command: BaseCommand,
        handler: Callable[[BaseCommand], Awaitable[CommandResult]],
        context: dict[str, Any],
    ) -> CommandResult:
        # Determine rate limit key
        if self._per_user and command.user_id:
            key = f"ratelimit:user:{command.user_id}:{command.command_type}"
        else:
            key = f"ratelimit:command:{command.command_type}"

        # Get current count
        current = await self._cache.get(key)
        count = int(current) if current else 0

        if count >= self._max_requests:
            raise CommandExecutionError(
                f"Rate limit exceeded for {command.command_type}. Max {self._max_requests} per minute"
            )

        # Increment counter
        await self._cache.setex(key, 60, str(count + 1))

        return await handler(command)


# === 5. UNIFIED COMMAND BUS ===


class UnifiedCommandBus:
    """
    Unified command bus untuk CQRS.
    Mengintegrasikan registry handler, validator, middleware pipeline.
    """

    def __init__(
        self,
        handler_registry: CommandHandlerRegistry | None = None,
        validator: CommandValidator | None = None,
        sealed_gate: SealedGate | None = None,
        middlewares: list[Middleware] | None = None,
        enable_idempotency: bool = True,
        enable_retry: bool = True,
        enable_timeout: bool = True,
        enable_rate_limit: bool = False,
        cache: CachePort | None = None,
        metrics: MetricsPort | None = None,
        tracer: TracerPort | None = None,
        default_timeout_seconds: float = 60.0,
        max_retries: int = 3,
    ):
        self._registry = handler_registry or command_handler_registry
        self._validator = validator or get_command_validator()
        self._sealed_gate = sealed_gate or get_sealed_gate()
        self._enable_idempotency = enable_idempotency
        self._enable_retry = enable_retry
        self._enable_timeout = enable_timeout
        self._enable_rate_limit = enable_rate_limit
        self._cache = cache or CachePort()
        self._metrics = metrics or MetricsPort()
        self._tracer = tracer or TracerPort()
        self._default_timeout = default_timeout_seconds
        self._max_retries = max_retries
        self._is_closed = False

        # Setup middleware pipeline
        self._middlewares: list[Middleware] = []
        self._build_middleware_pipeline(middlewares)

        # Stats
        self._stats = {
            "total_dispatched": 0,
            "total_succeeded": 0,
            "total_failed": 0,
            "total_duplicate": 0,
            "last_error": None,
            "started_at": datetime.now(UTC).isoformat(),
        }

        # Event subscribers
        self._event_subscribers: list[Callable[[BaseCommand, CommandResult], None]] = []

        logger.info(
            "UnifiedCommandBus initialized",
            extra={
                "middlewares": [m.name for m in self._middlewares],
                "idempotency": enable_idempotency,
                "retry": enable_retry,
                "timeout": enable_timeout,
                "rate_limit": enable_rate_limit,
            },
        )

    def _build_middleware_pipeline(self, custom_middlewares: list[Middleware] | None) -> None:
        """Build the middleware pipeline with proper ordering."""
        middlewares = []

        # Rate limit middleware (earliest)
        if self._enable_rate_limit:
            middlewares.append(RateLimitMiddleware(self._cache))

        # Idempotency middleware
        if self._enable_idempotency:
            middlewares.append(IdempotencyMiddleware(self._cache))

        # Timeout middleware
        if self._enable_timeout:
            middlewares.append(TimeoutMiddleware(self._default_timeout))

        # Retry middleware
        if self._enable_retry:
            middlewares.append(RetryMiddleware(self._max_retries))

        # Logging middleware
        middlewares.append(LoggingMiddleware())

        # Audit middleware
        middlewares.append(AuditMiddleware())

        # Transaction middleware (innermost)
        middlewares.append(TransactionMiddleware())

        # Add custom middlewares at appropriate positions
        if custom_middlewares:
            # Custom middlewares go before transaction but after other middleware
            # Insert at position before transaction
            insert_pos = len(middlewares) - 1
            for i, mw in enumerate(reversed(custom_middlewares)):
                middlewares.insert(insert_pos, mw)

        self._middlewares = middlewares

    async def dispatch(self, command: BaseCommand) -> CommandResult:
        """
        Dispatch command ke handler yang sesuai.
        Melewati pipeline middleware.
        """
        if self._is_closed:
            raise CommandBusClosedError("Command bus is closed")

        start_time = time.perf_counter()
        self._metrics.inc_commands_dispatched(command.command_type)
        self._stats["total_dispatched"] += 1

        # Set context
        ContextHolder.set("command_id", str(command.command_id))
        ContextHolder.set("correlation_id", command.correlation_id)
        ContextHolder.set("user_id", str(command.user_id) if command.user_id else None)
        ContextHolder.set("tenant_id", str(command.tenant_id) if command.tenant_id else None)

        span = self._tracer.start_span(f"command_{command.command_type}")
        span.set_attribute("command.type", command.command_type)
        span.set_attribute("command.id", str(command.command_id))
        span.set_attribute("correlation.id", command.correlation_id)

        try:
            # Validasi command
            validation_result = await self._validator.validate_async(command)
            if not validation_result.is_valid:
                self._stats["total_failed"] += 1
                self._metrics.inc_commands_failed(command.command_type, "validation")
                span.set_status("ERROR", "validation_failed")
                return CommandResult.failure(
                    command_id=command.command_id,
                    error=f"Command validation failed: {', '.join(validation_result.errors)}",
                    error_code="VALIDATION_ERROR",
                    metadata={"validation_errors": validation_result.errors},
                )

            # Dapatkan handler
            handler = self._registry.get_handler(command.command_type)
            if not handler:
                self._stats["total_failed"] += 1
                self._metrics.inc_commands_failed(command.command_type, "not_found")
                span.set_status("ERROR", "handler_not_found")
                raise CommandNotFoundError(
                    f"No handler registered for command type: {command.command_type}"
                )

            # Build middleware chain
            async def final_handler(cmd: BaseCommand) -> CommandResult:
                # Execute through sealed gate
                result = await self._sealed_gate.execute(
                    command_type=cmd.command_type,
                    command_id=cmd.command_id,
                    handler=lambda: handler(cmd),
                )
                cmd.set_result(result)
                return result

            # Apply middlewares in reverse order
            current = final_handler
            for middleware in reversed(self._middlewares):

                def make_handler(mw, next_handler):
                    async def wrapped(cmd):
                        return await mw.process(cmd, next_handler, {})

                    return wrapped

                current = make_handler(middleware, current)

            # Execute pipeline
            result = await current(command)
            command.set_result(result)

            # Update metrics
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.observe_command_latency(latency_ms / 1000)

            if result.is_success():
                self._stats["total_succeeded"] += 1
            elif result.is_duplicate():
                self._stats["total_duplicate"] += 1
                self._stats["total_succeeded"] += 1
            else:
                self._stats["total_failed"] += 1
                self._stats["last_error"] = result.error
                self._metrics.inc_commands_failed(
                    command.command_type, result.error_code or "unknown"
                )

            span.set_status("OK")

            # Notify subscribers
            await self._notify_subscribers(command, result)

            return result

        except CommandValidationError as e:
            self._stats["total_failed"] += 1
            self._metrics.inc_commands_failed(command.command_type, "validation")
            span.set_status("ERROR", str(e))
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="VALIDATION_ERROR"
            )
        except CommandNotFoundError as e:
            self._stats["total_failed"] += 1
            self._metrics.inc_commands_failed(command.command_type, "not_found")
            span.set_status("ERROR", str(e))
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="COMMAND_NOT_FOUND"
            )
        except DuplicateCommandError as e:
            self._stats["total_duplicate"] += 1
            self._stats["total_succeeded"] += 1
            span.set_status("OK", "duplicate")
            return CommandResult.duplicate(command_id=command.command_id, message=str(e))
        except CommandTimeoutError as e:
            self._stats["total_failed"] += 1
            self._metrics.inc_commands_failed(command.command_type, "timeout")
            span.set_status("ERROR", "timeout")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="TIMEOUT_ERROR"
            )
        except Exception as e:
            self._stats["total_failed"] += 1
            self._stats["last_error"] = str(e)
            self._metrics.inc_commands_failed(command.command_type, "unhandled")
            span.set_status("ERROR", str(e))
            logger.exception(f"Unhandled error dispatching command {command.command_type}: {e}")
            return CommandResult.failure(
                command_id=command.command_id,
                error=f"Internal error: {e!s}",
                error_code="INTERNAL_ERROR",
            )
        finally:
            span.end()
            ContextHolder.clear()

    def register_handler(
        self, command_type: str, handler: Callable[[BaseCommand], Awaitable[CommandResult]]
    ) -> None:
        """Register command handler."""
        self._registry.register_handler(command_type, handler)

    def register_middleware(self, middleware: Middleware, position: int | None = None) -> None:
        """Register middleware pada posisi tertentu."""
        if position is None:
            self._middlewares.append(middleware)
        else:
            self._middlewares.insert(position, middleware)
        logger.info(f"Registered middleware: {middleware.name}")

    def subscribe(self, callback: Callable[[BaseCommand, CommandResult], None]) -> None:
        """Subscribe to command execution events."""
        self._event_subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[BaseCommand, CommandResult], None]) -> None:
        """Unsubscribe from command execution events."""
        if callback in self._event_subscribers:
            self._event_subscribers.remove(callback)

    async def _notify_subscribers(self, command: BaseCommand, result: CommandResult) -> None:
        """Notify all subscribers of command execution."""
        for subscriber in self._event_subscribers:
            try:
                if asyncio.iscoroutinefunction(subscriber):
                    await subscriber(command, result)
                else:
                    subscriber(command, result)
            except Exception as e:
                logger.warning(f"Subscriber callback failed: {e}")

    def close(self) -> None:
        """Close the command bus."""
        self._is_closed = True
        logger.info("UnifiedCommandBus closed")

    async def flush(self) -> None:
        """Flush any pending operations."""
        # Clear caches if needed
        pass

    def get_stats(self) -> dict[str, Any]:
        """Dapatkan statistik command bus."""
        uptime_seconds = (
            datetime.now(UTC) - datetime.fromisoformat(self._stats["started_at"])
        ).total_seconds()

        return {
            **self._stats,
            "uptime_seconds": uptime_seconds,
            "is_closed": self._is_closed,
            "registered_commands": self._registry.list_command_types(),
            "middlewares": [m.name for m in self._middlewares],
            "metrics": self._metrics.get_stats(),
            "subscribers_count": len(self._event_subscribers),
        }

    def health_check(self) -> dict[str, Any]:
        """Perform health check."""
        return {
            "status": "healthy" if not self._is_closed else "closed",
            "is_closed": self._is_closed,
            "total_dispatched": self._stats["total_dispatched"],
            "total_failed": self._stats["total_failed"],
            "success_rate": (
                (self._stats["total_succeeded"] / self._stats["total_dispatched"] * 100)
                if self._stats["total_dispatched"] > 0
                else 100
            ),
        }


# === 6. SIMPLE COMMAND BUS FOR TESTS ===


class CommandBus:
    """
    Simple synchronous command bus for unit tests.
    Supports register_handler by command class, dispatch, set_validator.
    """

    def __init__(self):
        self._handlers: dict[type, Any] = {}
        self._validator: CommandValidator | None = None
        self._middlewares: list[Callable] = []
        self._stats = {"dispatched": 0, "succeeded": 0, "failed": 0}

    def register_handler(self, command_class: type, handler: Any) -> None:
        """Register a handler for a command class."""
        self._handlers[command_class] = handler

    def set_validator(self, validator: CommandValidator) -> None:
        """Set a command validator."""
        self._validator = validator

    def add_middleware(self, middleware: Callable) -> None:
        """Add middleware to the pipeline."""
        self._middlewares.append(middleware)

    def dispatch(self, command: Any) -> CommandResult:
        """
        Dispatch a command to its handler synchronously.
        Returns a CommandResult.
        """
        self._stats["dispatched"] += 1

        # Validation
        if self._validator:
            is_valid = self._validator.validate(command)
            if not is_valid:
                self._stats["failed"] += 1
                return CommandResult.failure(
                    command_id=getattr(command, "command_id", None),
                    error="Validation failed",
                    error_code="VALIDATION_ERROR",
                )

        handler = self._handlers.get(type(command))
        if not handler:
            self._stats["failed"] += 1
            return CommandResult.failure(
                command_id=getattr(command, "command_id", None),
                error=f"No handler registered for {type(command).__name__}",
                error_code="HANDLER_NOT_FOUND",
            )

        # Build handler with middlewares
        result = None
        current_handler = handler

        # Apply middlewares in order
        for middleware in reversed(self._middlewares):

            def make_handler(mw, next_handler):
                def wrapped(cmd):
                    return mw(cmd, next_handler)

                return wrapped

            current_handler = make_handler(middleware, current_handler)

        try:
            # Execute with middleware chain
            if callable(current_handler):
                result = current_handler(command)
            else:
                result = current_handler.handle(command)

            self._stats["succeeded"] += 1
            return result
        except Exception as e:
            self._stats["failed"] += 1
            return CommandResult.failure(
                command_id=getattr(command, "command_id", None),
                error=str(e),
                error_code="HANDLER_ERROR",
            )

    def get_stats(self) -> dict[str, int]:
        """Get command bus statistics."""
        return self._stats.copy()


# === 7. SINGLETON INSTANCE ===

_command_bus_instance: UnifiedCommandBus | None = None


def get_command_bus() -> UnifiedCommandBus:
    """Get singleton instance of UnifiedCommandBus."""
    global _command_bus_instance
    if _command_bus_instance is None:
        _command_bus_instance = UnifiedCommandBus()
    return _command_bus_instance


async def dispatch_command(command: BaseCommand) -> CommandResult:
    """Convenience function to dispatch command using singleton bus."""
    return await get_command_bus().dispatch(command)


def reset_command_bus() -> None:
    """Reset the command bus singleton (for testing)."""
    global _command_bus_instance
    if _command_bus_instance:
        _command_bus_instance.close()
    _command_bus_instance = None


# === 8. EXPORTS ===

__all__ = [
    "AuditMiddleware",
    "BaseCommand",
    "CachePort",
    "Command",
    "CommandBus",
    "CommandBusClosedError",
    "CommandBusError",
    "CommandExecutionError",
    "CommandNotFoundError",
    "CommandTimeoutError",
    "CommandValidationError",
    "DuplicateCommandError",
    "IdempotencyMiddleware",
    "LoggingMiddleware",
    "MetricsPort",
    "Middleware",
    "RateLimitMiddleware",
    "RetryMiddleware",
    "TimeoutMiddleware",
    "TracerPort",
    "TransactionMiddleware",
    "UnifiedCommandBus",
    "dispatch_command",
    "get_command_bus",
    "reset_command_bus",
]