#!/usr/bin/env python3
"""
Module: unit_of_work_port.py
Layer: Ports (Primary)
Responsibility: Port untuk Unit of Work (ACID semantics).
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)
T = TypeVar("T")


class IsolationLevel(Enum):
    READ_UNCOMMITTED = "read_uncommitted"
    READ_COMMITTED = "read_committed"
    REPEATABLE_READ = "repeatable_read"
    SERIALIZABLE = "serializable"


class TransactionStatus(Enum):
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class DeadlockError(Exception):
    pass


# ==================== PORT (INTERFACE) ====================

class UnitOfWorkPort(abc.ABC):
    """Port untuk Unit of Work."""

    @abc.abstractmethod
    async def __aenter__(self) -> UnitOfWorkPort:
        """Enter transaction context."""
        ...

    @abc.abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit transaction context."""
        ...

    @abc.abstractmethod
    async def commit(self) -> None:
        """Commit semua perubahan."""
        ...

    @abc.abstractmethod
    async def rollback(self) -> None:
        """Rollback semua perubahan."""
        ...

    @abc.abstractmethod
    async def savepoint(self, name: str | None = None) -> str:
        """Buat savepoint."""
        ...

    @abc.abstractmethod
    async def rollback_to_savepoint(self, name: str) -> bool:
        """Rollback ke savepoint."""
        ...

    @abc.abstractmethod
    async def release_savepoint(self, name: str) -> bool:
        """Release savepoint."""
        ...

    @abc.abstractmethod
    def register_repository(self, name: str, repository: Any) -> None:
        """Daftarkan repository."""
        ...

    @abc.abstractmethod
    def get_repository(self, name: str) -> Any:
        """Ambil repository."""
        ...

    @abc.abstractmethod
    def add_before_commit_hook(self, hook: Callable[[], Awaitable[bool]]) -> None:
        """Hook sebelum commit."""
        ...

    @abc.abstractmethod
    def add_after_commit_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Hook setelah commit."""
        ...

    @abc.abstractmethod
    def add_after_rollback_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Hook setelah rollback."""
        ...

    @abc.abstractmethod
    async def flush(self) -> None:
        """Flush perubahan tanpa commit."""
        ...

    @abc.abstractmethod
    async def execute_raw_sql(self, statement: str, params: dict[str, Any] | None = None) -> Any:
        """Eksekusi raw SQL (simulasi)."""
        ...

    @abc.abstractmethod
    async def is_active(self) -> bool:
        """Apakah transaksi aktif?"""
        ...

    @abc.abstractmethod
    async def get_transaction_id(self) -> UUID:
        """Dapatkan ID transaksi."""
        ...

    @abc.abstractmethod
    async def get_isolation_level(self) -> str:
        """Dapatkan tingkat isolasi."""
        ...

    @asynccontextmanager
    @abc.abstractmethod
    async def transaction(self):
        """Async context manager untuk explicit transaction block."""
        ...


# ==================== IMPLEMENTASI IN-MEMORY ====================

class InMemoryUnitOfWork(UnitOfWorkPort):
    """
    In-memory Unit of Work dengan ACID semantics.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(
        self,
        isolation_level: IsolationLevel = IsolationLevel.READ_COMMITTED,
        auto_commit: bool = False,
        retry_on_deadlock: int = 3,
    ):
        self._repositories: dict[str, Any] = {}
        self._after_commit_hooks: list[Callable[[], Awaitable[None]]] = []
        self._after_rollback_hooks: list[Callable[[], Awaitable[None]]] = []
        self._before_commit_hooks: list[Callable[[], Awaitable[bool]]] = []
        self._savepoints: list[dict[str, Any]] = []
        self._status: TransactionStatus = TransactionStatus.ACTIVE
        self._isolation_level = isolation_level
        self._auto_commit = auto_commit
        self._retry_on_deadlock = retry_on_deadlock
        self._deadlock_detector = DeadlockDetector()
        self._audit_log: list[dict[str, Any]] = []
        self._session_data: dict[str, Any] = {}
        self._change_set: dict[str, list[Any]] = {}
        self._transaction_id: UUID = uuid4()
        self._start_time: datetime | None = None
        self._commit_time: datetime | None = None
        self._rollback_time: datetime | None = None
        self._nesting_level = 0

    async def _log_audit(self, action: str, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "transaction_id": str(self._transaction_id),
            "action": action,
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"UOW AUDIT: {action} (tx={self._transaction_id})")

    async def _execute_with_retry(self, func: Callable[[], Awaitable[None]]) -> None:
        for attempt in range(self._retry_on_deadlock + 1):
            try:
                await func()
                return
            except DeadlockError:
                if attempt >= self._retry_on_deadlock:
                    raise
                wait = 0.1 * (2**attempt)
                logger.warning(f"Deadlock detected, retrying in {wait}s (attempt {attempt + 1})")
                await asyncio.sleep(wait)

    async def __aenter__(self) -> UnitOfWorkPort:
        self._start_time = datetime.now(UTC)
        self._status = TransactionStatus.ACTIVE
        self._transaction_id = uuid4()
        self._change_set.clear()
        await self._log_audit("BEGIN", {"isolation": self._isolation_level.value})
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.rollback()
            await self._log_audit("EXIT_WITH_ERROR", {"error": str(exc_val)})
        elif self._auto_commit and self._status == TransactionStatus.ACTIVE:
            await self.commit()
        await self._log_audit("EXIT", {"status": self._status.value})

    async def commit(self) -> None:
        if self._status != TransactionStatus.ACTIVE:
            raise ValueError(f"Cannot commit in status {self._status.value}")

        for hook in self._before_commit_hooks:
            try:
                should_continue = await hook()
                if not should_continue:
                    await self.rollback()
                    raise RuntimeError("Before-commit hook aborted transaction")
            except Exception as e:
                await self.rollback()
                raise RuntimeError(f"Before-commit hook failed: {e}")

        try:
            for repo_name, repo in self._repositories.items():
                if hasattr(repo, "_commit"):
                    await repo._commit()
            self._status = TransactionStatus.COMMITTED
            self._commit_time = datetime.now(UTC)
            await self._log_audit(
                "COMMIT",
                {
                    "duration_ms": (self._commit_time - self._start_time).total_seconds() * 1000
                    if self._start_time
                    else 0,
                    "changes": self._get_change_summary(),
                },
            )
        except Exception as e:
            self._status = TransactionStatus.FAILED
            await self._log_audit("COMMIT_FAILED", {"error": str(e)})
            raise

        for hook in self._after_commit_hooks:
            try:
                await hook()
            except Exception as e:
                logger.error(f"After-commit hook failed: {e}")

    async def rollback(self) -> None:
        if self._status not in (TransactionStatus.ACTIVE, TransactionStatus.FAILED):
            return
        for repo_name, repo in self._repositories.items():
            if hasattr(repo, "_rollback"):
                await repo._rollback()
        self._status = TransactionStatus.ROLLED_BACK
        self._rollback_time = datetime.now(UTC)
        self._change_set.clear()
        await self._log_audit(
            "ROLLBACK",
            {
                "duration_ms": (self._rollback_time - self._start_time).total_seconds() * 1000
                if self._start_time
                else 0,
            },
        )
        for hook in self._after_rollback_hooks:
            try:
                await hook()
            except Exception as e:
                logger.error(f"After-rollback hook failed: {e}")

    async def savepoint(self, name: str | None = None) -> str:
        if self._status != TransactionStatus.ACTIVE:
            raise ValueError("Cannot create savepoint in non-active transaction")
        savepoint_id = name or f"sp_{len(self._savepoints)}"
        snapshot = {
            "name": savepoint_id,
            "change_set_snapshot": {k: list(v) for k, v in self._change_set.items()},
            "repositories_snapshot": {},
        }
        for repo_name, repo in self._repositories.items():
            if hasattr(repo, "_savepoint"):
                snapshot["repositories_snapshot"][repo_name] = await repo._savepoint()
        self._savepoints.append(snapshot)
        await self._log_audit("SAVEPOINT", {"name": savepoint_id, "nesting_level": len(self._savepoints)})
        return savepoint_id

    async def rollback_to_savepoint(self, name: str) -> bool:
        for idx, sp in enumerate(self._savepoints):
            if sp["name"] == name:
                self._change_set = sp["change_set_snapshot"]
                for repo_name, repo in self._repositories.items():
                    if hasattr(repo, "_rollback_to_savepoint") and repo_name in sp["repositories_snapshot"]:
                        await repo._rollback_to_savepoint(sp["repositories_snapshot"][repo_name])
                self._savepoints = self._savepoints[:idx]
                await self._log_audit("ROLLBACK_TO_SAVEPOINT", {"name": name})
                return True
        return False

    async def release_savepoint(self, name: str) -> bool:
        for idx, sp in enumerate(self._savepoints):
            if sp["name"] == name:
                self._savepoints = self._savepoints[:idx] + self._savepoints[idx + 1:]
                await self._log_audit("RELEASE_SAVEPOINT", {"name": name})
                return True
        return False

    def register_repository(self, name: str, repository: Any) -> None:
        self._repositories[name] = repository
        if hasattr(repository, "_set_uow"):
            repository._set_uow(self)
        logger.debug(f"Repository '{name}' registered in UoW {self._transaction_id}")

    def get_repository(self, name: str) -> Any:
        if name not in self._repositories:
            raise KeyError(f"Repository '{name}' not registered")
        return self._repositories[name]

    def add_before_commit_hook(self, hook: Callable[[], Awaitable[bool]]) -> None:
        self._before_commit_hooks.append(hook)

    def add_after_commit_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._after_commit_hooks.append(hook)

    def add_after_rollback_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._after_rollback_hooks.append(hook)

    def _get_change_summary(self) -> dict[str, int]:
        return {repo: len(changes) for repo, changes in self._change_set.items()}

    def record_change(self, repository_name: str, change: Any) -> None:
        if repository_name not in self._change_set:
            self._change_set[repository_name] = []
        self._change_set[repository_name].append(change)

    async def _acquire_lock(self, lock_id: str, timeout: float = 5.0) -> bool:
        return await self._deadlock_detector.acquire_lock(self._transaction_id, lock_id, timeout)

    async def _release_lock(self, lock_id: str) -> None:
        await self._deadlock_detector.release_lock(self._transaction_id, lock_id)

    async def flush(self) -> None:
        if self._status != TransactionStatus.ACTIVE:
            raise ValueError("Cannot flush in non-active transaction")
        for repo_name, repo in self._repositories.items():
            if hasattr(repo, "_flush"):
                await repo._flush()
        await self._log_audit("FLUSH", {})

    async def execute_raw_sql(self, statement: str, params: dict[str, Any] | None = None) -> Any:
        await self._log_audit("RAW_SQL", {"statement": statement[:100], "params": str(params)[:100]})
        logger.warning(f"Raw SQL executed in in-memory UoW (simulated): {statement[:100]}")
        return None

    async def is_active(self) -> bool:
        return self._status == TransactionStatus.ACTIVE

    async def get_transaction_id(self) -> UUID:
        return self._transaction_id

    async def get_isolation_level(self) -> str:
        return self._isolation_level.value

    @asynccontextmanager
    async def transaction(self):
        await self.__aenter__()
        try:
            yield self
            if self._auto_commit:
                await self.commit()
        except Exception:
            await self.rollback()
            raise
        finally:
            await self.__aexit__(None, None, None)


class DeadlockDetector:
    def __init__(self):
        self._locks: dict[str, UUID | None] = {}
        self._waiting: dict[UUID, list[str]] = {}
        self._lock = asyncio.Lock()

    async def acquire_lock(self, tx_id: UUID, lock_id: str, timeout: float) -> bool:
        start = time.time()
        while True:
            async with self._lock:
                current_holder = self._locks.get(lock_id)
                if current_holder is None:
                    self._locks[lock_id] = tx_id
                    return True
                if current_holder == tx_id:
                    return True
                if self._detect_cycle(tx_id, lock_id):
                    raise DeadlockError(f"Deadlock detected for lock {lock_id}")
                if tx_id not in self._waiting:
                    self._waiting[tx_id] = []
                if lock_id not in self._waiting[tx_id]:
                    self._waiting[tx_id].append(lock_id)
            if time.time() - start > timeout:
                return False
            await asyncio.sleep(0.01)

    async def release_lock(self, tx_id: UUID, lock_id: str) -> None:
        async with self._lock:
            if self._locks.get(lock_id) == tx_id:
                del self._locks[lock_id]
            if tx_id in self._waiting:
                self._waiting[tx_id] = [lid for lid in self._waiting[tx_id] if lid != lock_id]
                if not self._waiting[tx_id]:
                    del self._waiting[tx_id]

    def _detect_cycle(self, tx_id: UUID, lock_id: str) -> bool:
        holder = self._locks.get(lock_id)
        if holder is None:
            return False
        waiting_locks = self._waiting.get(holder, [])
        for wl in waiting_locks:
            if self._locks.get(wl) == tx_id:
                return True
        return False


# ==================== PROVIDER (untuk backward compatibility) ====================

class RepositoryProvider:
    def __init__(
        self,
        journals=None,
        ledger_entries=None,
        accounts=None,
        ar_invoices=None,
        ap_invoices=None,
        inventory=None,
        fixed_assets=None,
        bank_accounts=None,
        cash_books=None,
        legal_entities=None,
        employees=None,
        customers=None,
        suppliers=None,
        iam_users=None,
        system_settings=None,
        tax_transactions=None,
    ):
        self._journals = journals
        self._ledger_entries = ledger_entries
        self._accounts = accounts
        self._ar_invoices = ar_invoices
        self._ap_invoices = ap_invoices
        self._inventory = inventory
        self._fixed_assets = fixed_assets
        self._bank_accounts = bank_accounts
        self._cash_books = cash_books
        self._legal_entities = legal_entities
        self._employees = employees
        self._customers = customers
        self._suppliers = suppliers
        self._iam_users = iam_users
        self._system_settings = system_settings
        self._tax_transactions = tax_transactions

    def journals(self):
        return self._journals

    def ledger_entries(self):
        return self._ledger_entries

    def accounts(self):
        return self._accounts

    def ar_invoices(self):
        return self._ar_invoices

    def ap_invoices(self):
        return self._ap_invoices

    def inventory(self):
        return self._inventory

    def fixed_assets(self):
        return self._fixed_assets

    def bank_accounts(self):
        return self._bank_accounts

    def cash_books(self):
        return self._cash_books

    def legal_entities(self):
        return self._legal_entities

    def employees(self):
        return self._employees

    def customers(self):
        return self._customers

    def suppliers(self):
        return self._suppliers

    def iam_users(self):
        return self._iam_users

    def system_settings(self):
        return self._system_settings

    def tax_transactions(self):
        return self._tax_transactions


_uow_instance: UnitOfWorkPort | None = None


def get_uow() -> UnitOfWorkPort:
    global _uow_instance
    if _uow_instance is None:
        _uow_instance = InMemoryUnitOfWork()
    return _uow_instance


async def create_uow_with_provider(provider: RepositoryProvider) -> UnitOfWorkPort:
    uow = InMemoryUnitOfWork()
    if provider.journals() is not None:
        uow.register_repository("journals", provider.journals())
    if provider.ledger_entries() is not None:
        uow.register_repository("ledger_entries", provider.ledger_entries())
    if provider.accounts() is not None:
        uow.register_repository("accounts", provider.accounts())
    if provider.ar_invoices() is not None:
        uow.register_repository("ar_invoices", provider.ar_invoices())
    if provider.ap_invoices() is not None:
        uow.register_repository("ap_invoices", provider.ap_invoices())
    if provider.inventory() is not None:
        uow.register_repository("inventory", provider.inventory())
    if provider.fixed_assets() is not None:
        uow.register_repository("fixed_assets", provider.fixed_assets())
    if provider.bank_accounts() is not None:
        uow.register_repository("bank_accounts", provider.bank_accounts())
    if provider.cash_books() is not None:
        uow.register_repository("cash_books", provider.cash_books())
    if provider.legal_entities() is not None:
        uow.register_repository("legal_entities", provider.legal_entities())
    if provider.employees() is not None:
        uow.register_repository("employees", provider.employees())
    if provider.customers() is not None:
        uow.register_repository("customers", provider.customers())
    if provider.suppliers() is not None:
        uow.register_repository("suppliers", provider.suppliers())
    if provider.iam_users() is not None:
        uow.register_repository("iam_users", provider.iam_users())
    if provider.system_settings() is not None:
        uow.register_repository("system_settings", provider.system_settings())
    if provider.tax_transactions() is not None:
        uow.register_repository("tax_transactions", provider.tax_transactions())
    return uow


async def get_uow_statistics() -> dict[str, Any]:
    uow = get_uow()
    return {
        "status": uow._status.value if uow else "not_initialized",
        "repositories_registered": len(uow._repositories) if uow else 0,
        "savepoints_count": len(uow._savepoints) if uow else 0,
        "audit_log_size": len(uow._audit_log) if uow else 0,
        "transaction_id": str(uow._transaction_id) if uow else None,
    }


__all__ = [
    "DeadlockError",
    "InMemoryUnitOfWork",
    "IsolationLevel",
    "RepositoryProvider",
    "TransactionStatus",
    "UnitOfWorkPort",
    "create_uow_with_provider",
    "get_uow",
    "get_uow_statistics",
]
