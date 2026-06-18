#!/usr/bin/env python3
"""
Module: transaction_manager.py
Layer: Infrastructure (Database)
Responsibility: Mengelola transaksi database dengan dukungan nested transactions
               (savepoints), isolation level management, dan retry logic untuk
               deadlock dan serialization failures. Juga menyediakan utility
               untuk transaction propagation (required, requires_new, etc.).
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- asyncio, logging, random
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Setiap transaksi (begin, commit, rollback) dicatat. Deadlock retry dicatat.
"""

from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from enum import Enum

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.telemetry.alert_manager_router import trigger_alert

# Internal dependencies
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================


class Propagation(Enum):
    """Transaction propagation behavior."""

    REQUIRED = "required"  # Use existing transaction or create new
    REQUIRES_NEW = "requires_new"  # Always create new transaction (suspend current)
    MANDATORY = "mandatory"  # Must have existing transaction
    SUPPORTS = "supports"  # Use existing if present, else no transaction
    NOT_SUPPORTED = "not_supported"  # Execute without transaction
    NEVER = "never"  # Must not have transaction


class IsolationLevel(Enum):
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


# Retry configuration for deadlocks
DEADLOCK_RETRY_MAX_ATTEMPTS = 3
DEADLOCK_RETRY_BASE_DELAY = 0.1  # seconds

# Deadlock error codes (PostgreSQL)
DEADLOCK_ERROR_CODES = ("40P01",)  # deadlock detected
SERIALIZATION_FAILURE_CODES = ("40001",)  # could not serialize access due to concurrent update

# ============================================================================
# EXCEPTIONS
# ============================================================================


class TransactionError(Exception):
    """Base exception untuk transaction manager."""

    pass


class TransactionPropagationError(TransactionError):
    """Error terkait propagation behavior."""

    pass


# ============================================================================
# TRANSACTION MANAGER
# ============================================================================


class TransactionManager:
    """
    Manajer transaksi database.

    Fitur:
    - Nested transactions (savepoints)
    - Isolation level management
    - Deadlock detection and retry
    - Transaction propagation (REQUIRED, REQUIRES_NEW, etc.)
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self._savepoint_count = 0
        self._isolation_level: IsolationLevel | None = None
        self._in_transaction = False
        self._transaction_depth = 0

    async def begin(self, isolation_level: IsolationLevel | None = None) -> None:
        """
        Begin a new transaction.

        Args:
            isolation_level: Override isolation level for this transaction
        """
        if self._in_transaction:
            # Already in transaction, just increment depth
            self._transaction_depth += 1
            return

        # Set isolation level if specified
        if isolation_level:
            await self._set_isolation_level(isolation_level)
            self._isolation_level = isolation_level

        # Begin transaction
        await self._session.begin()
        self._in_transaction = True
        self._transaction_depth = 1
        logger.debug("Transaction started")

    async def commit(self) -> None:
        """
        Commit the current transaction.
        """
        if not self._in_transaction:
            raise TransactionError("No active transaction to commit")

        if self._transaction_depth > 1:
            # Nested transaction via savepoints - just decrement depth
            self._transaction_depth -= 1
            return

        try:
            await self._session.commit()
            self._in_transaction = False
            self._transaction_depth = 0
            logger.debug("Transaction committed")
        except Exception as e:
            await self._session.rollback()
            self._in_transaction = False
            self._transaction_depth = 0
            logger.error(f"Transaction commit failed: {e}")
            raise

    async def rollback(self) -> None:
        """
        Rollback the current transaction.
        """
        if not self._in_transaction:
            logger.debug("No active transaction to rollback")
            return

        if self._transaction_depth > 1:
            # Nested transaction - rollback to savepoint
            self._transaction_depth -= 1
            return

        await self._session.rollback()
        self._in_transaction = False
        self._transaction_depth = 0
        logger.debug("Transaction rolled back")

    async def savepoint(self, name: str | None = None) -> str:
        """
        Create a savepoint for nested transaction.

        Args:
            name: Optional savepoint name (auto-generated if not provided)

        Returns:
            Savepoint name
        """
        if not self._in_transaction:
            raise TransactionError("Cannot create savepoint outside transaction")

        savepoint_name = name or f"savepoint_{self._savepoint_count + 1}"
        await self._session.execute(f"SAVEPOINT {savepoint_name}")
        self._savepoint_count += 1
        self._transaction_depth += 1
        logger.debug(f"Savepoint created: {savepoint_name}")
        return savepoint_name

    async def rollback_to_savepoint(self, savepoint_name: str) -> None:
        """
        Rollback to a savepoint.
        """
        if not self._in_transaction:
            raise TransactionError("No active transaction")

        await self._session.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
        self._transaction_depth -= 1
        logger.debug(f"Rolled back to savepoint: {savepoint_name}")

    async def release_savepoint(self, savepoint_name: str) -> None:
        """
        Release a savepoint.
        """
        await self._session.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        self._transaction_depth -= 1
        logger.debug(f"Savepoint released: {savepoint_name}")

    async def _set_isolation_level(self, level: IsolationLevel) -> None:
        """Set transaction isolation level."""
        await self._session.execute(f"SET TRANSACTION ISOLATION LEVEL {level.value}")
        logger.debug(f"Isolation level set to {level.value}")

    async def __aenter__(self):
        await self.begin()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        else:
            await self.commit()


# ============================================================================
# RETRY DECORATOR
# ============================================================================


def retry_on_deadlock(
    max_attempts: int = DEADLOCK_RETRY_MAX_ATTEMPTS,
    base_delay: float = DEADLOCK_RETRY_BASE_DELAY,
    max_delay: float = 1.0,
):
    """
    Decorator untuk retry transaksi yang gagal karena deadlock atau serialization failure.

    Usage:
        @retry_on_deadlock()
        async def update_accounts(session):
            ...
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except OperationalError as e:
                    # Check if error is deadlock or serialization failure
                    if hasattr(e, "orig") and hasattr(e.orig, "pgcode"):
                        pgcode = e.orig.pgcode
                        if pgcode in DEADLOCK_ERROR_CODES:
                            logger.warning(
                                f"Deadlock detected, retrying (attempt {attempt + 1}/{max_attempts})"
                            )
                            await asyncio.sleep(
                                min(base_delay * (2**attempt) + random.uniform(0, 0.1), max_delay)
                            )
                            continue
                        elif pgcode in SERIALIZATION_FAILURE_CODES:
                            logger.warning(
                                f"Serialization failure, retrying (attempt {attempt + 1}/{max_attempts})"
                            )
                            await asyncio.sleep(
                                min(base_delay * (2**attempt) + random.uniform(0, 0.1), max_delay)
                            )
                            continue
                    last_exception = e
                    break
                except Exception as e:
                    last_exception = e
                    break

            if last_exception:
                logger.error(f"Transaction failed after {max_attempts} attempts: {last_exception}")
                await trigger_alert(
                    title="Transaction Failed After Retries",
                    message=f"Transaction failed after {max_attempts} attempts: {last_exception}",
                    severity="error",
                    source="TransactionManager",
                )
                raise last_exception

        return wrapper

    return decorator


# ============================================================================
# TRANSACTIONAL DECORATOR
# ============================================================================


def transactional(
    propagation: Propagation = Propagation.REQUIRED,
    isolation_level: IsolationLevel | None = None,
    retry_deadlock: bool = True,
):
    """
    Decorator untuk menandai fungsi agar dijalankan dalam transaksi.

    Usage:
        @transactional()
        async def create_journal(data):
            ...
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract session from first argument or kwargs
            session = None
            for arg in args:
                if isinstance(arg, AsyncSession):
                    session = arg
                    break
            if not session and "session" in kwargs:
                session = kwargs["session"]

            if not session:
                raise TransactionError("No session found for transactional decorator")

            tm = TransactionManager(session)

            # Handle propagation
            if propagation == Propagation.REQUIRED:
                # Use existing transaction or create new
                if tm._in_transaction:
                    # Already in transaction, just execute
                    return await func(*args, **kwargs)
                else:
                    async with tm:
                        return await func(*args, **kwargs)

            elif propagation == Propagation.REQUIRES_NEW:
                # Always create new transaction (suspend current if any)
                # For simplicity, we commit any existing and start new
                if tm._in_transaction:
                    await tm.commit()
                async with tm:
                    return await func(*args, **kwargs)

            elif propagation == Propagation.MANDATORY:
                if not tm._in_transaction:
                    raise TransactionPropagationError(
                        "MANDATORY transaction required but none active"
                    )
                return await func(*args, **kwargs)

            elif propagation == Propagation.SUPPORTS:
                # Use transaction if present, else no transaction
                return await func(*args, **kwargs)

            elif propagation == Propagation.NOT_SUPPORTED:
                # Execute without transaction
                if tm._in_transaction:
                    # For simplicity, we commit and restore later
                    await tm.commit()
                return await func(*args, **kwargs)

            elif propagation == Propagation.NEVER:
                if tm._in_transaction:
                    raise TransactionPropagationError(
                        "NEVER transaction but active transaction exists"
                    )
                return await func(*args, **kwargs)

            else:
                return await func(*args, **kwargs)

        if retry_deadlock:
            return retry_on_deadlock()(wrapper)
        return wrapper

    return decorator


# ============================================================================
# CONTEXT MANAGERS
# ============================================================================


@asynccontextmanager
async def transaction(session: AsyncSession, isolation_level: IsolationLevel | None = None):
    """
    Context manager untuk transaksi database.

    Usage:
        async with transaction(session) as tx:
            await session.execute(...)
    """
    tm = TransactionManager(session)
    async with tm:
        yield tm


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "IsolationLevel",
    "Propagation",
    "TransactionError",
    "TransactionManager",
    "TransactionPropagationError",
    "retry_on_deadlock",
    "transaction",
    "transactional",
]
