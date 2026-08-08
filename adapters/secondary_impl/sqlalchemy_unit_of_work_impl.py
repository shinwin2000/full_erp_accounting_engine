#!/usr/bin/env python3
"""
Module: sqlalchemy_unit_of_work_impl.py
Layer: Adapters (Secondary Implementation)

Responsibility:
    Implementasi konkret dari UnitOfWorkPort menggunakan SQLAlchemy.
    Semua import dilakukan secara lazy untuk menghindari kegagalan startup.
    Menggunakan session.begin() langsung (tanpa TransactionManager eksternal).
    Penanganan error pada close session dan commit/rollback.

    Perbaikan (v2):
    - __aexit__: commit otomatis jika tidak ada exception
    - commit() dan rollback() menggunakan _transaction object dengan benar
    - Menambahkan properti session yang mengembalikan session aktif
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncContextManager
from uuid import uuid4

from sqlalchemy import text as sa_text

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================

class UnitOfWorkError(Exception):
    pass

class UnitOfWorkCommitError(UnitOfWorkError):
    pass

class UnitOfWorkRollbackError(UnitOfWorkError):
    pass


# ============================================================================
# KELAS UTAMA
# ============================================================================

class SQLAlchemyUnitOfWork:
    """
    Unit of Work dengan SQLAlchemy async session.
    Implementasi lazy import untuk semua dependensi.
    """

    __slots__ = (
        "_after_commit_hooks",
        "_after_rollback_hooks",
        "_before_commit_hooks",
        "_change_log",
        "_event_collector",
        "_initialized_repos",
        "_is_active",
        "_is_period_closing",
        "_repositories",
        "_savepoint_depth",
        "_session",
        "_session_factory",
        "_transaction",
        "_transaction_id",
    )

    def __init__(
        self,
        session_factory: Any = None,  # async_sessionmaker | None
        is_period_closing: bool = False,
    ):
        self._session_factory = session_factory
        self._session: Any = None          # AsyncSession
        self._transaction: Any = None      # AsyncSessionTransaction
        self._repositories: dict[str, Any] = {}
        self._event_collector: list = []
        self._savepoint_depth: int = 0
        self._is_period_closing = is_period_closing
        self._before_commit_hooks: list[Callable] = []
        self._after_commit_hooks: list[Callable] = []
        self._after_rollback_hooks: list[Callable] = []
        self._change_log: list[dict[str, Any]] = []
        self._transaction_id: str | None = None
        self._is_active: bool = False
        self._initialized_repos: bool = False

    # ------------------------------------------------------------------------
    # LAZY REPOSITORY INITIALIZATION
    # ------------------------------------------------------------------------

    def _ensure_repositories_initialized(self) -> None:
        """Inisialisasi repository hanya sekali dan hanya jika dibutuhkan."""
        if self._initialized_repos:
            return

        try:
            adapters = importlib.import_module("adapters.secondary_impl")

            account_cls = getattr(adapters, "SQLAlchemyAccountRepository", None)
            ap_cls = getattr(adapters, "SQLAlchemyAPRepository", None)
            ar_cls = getattr(adapters, "SQLAlchemyARRepository", None)
            bank_cls = getattr(adapters, "SQLAlchemyBankCashRepository", None)
            fixed_cls = getattr(adapters, "SQLAlchemyFixedAssetRepository", None)
            iam_cls = getattr(adapters, "SQLAlchemyIAMUserRepository", None)
            inv_cls = getattr(adapters, "SQLAlchemyInventoryRepository", None)
            journal_cls = getattr(adapters, "SQLAlchemyJournalRepository", None)
            ledger_cls = getattr(adapters, "SQLAlchemyLedgerRepository", None)
            legal_cls = getattr(adapters, "SQLAlchemyLegalEntityRepository", None)
            outbox_cls = getattr(adapters, "SQLAlchemyOutboxRepository", None)
            setting_cls = getattr(adapters, "SQLAlchemySystemSettingRepository", None)
            tax_cls = getattr(adapters, "SQLAlchemyTaxRepository", None)

            self._repositories["account"] = account_cls() if account_cls else None
            self._repositories["ap"] = ap_cls() if ap_cls else None
            self._repositories["ar"] = ar_cls() if ar_cls else None
            self._repositories["bank_cash"] = bank_cls() if bank_cls else None
            self._repositories["fixed_asset"] = fixed_cls() if fixed_cls else None
            self._repositories["iam_user"] = iam_cls() if iam_cls else None
            self._repositories["inventory"] = inv_cls() if inv_cls else None
            self._repositories["journal"] = journal_cls() if journal_cls else None
            self._repositories["ledger"] = ledger_cls() if ledger_cls else None
            self._repositories["legal_entity"] = legal_cls() if legal_cls else None
            self._repositories["outbox"] = outbox_cls() if outbox_cls else None
            self._repositories["system_setting"] = setting_cls() if setting_cls else None
            self._repositories["tax"] = tax_cls() if tax_cls else None

            self._initialized_repos = True
        except ImportError as e:
            raise UnitOfWorkError(f"Failed to import repository adapters: {e}") from e

    @staticmethod
    def _assign_session(repo: Any, session: Any) -> None:
        """
        Attach `session` ke satu repository, dengan urutan prioritas yang
        aman terhadap 3 gaya repository yang ada di proyek ini:

        1. Repository dengan method `set_session(session)` eksplisit
           (mis. SQLAlchemyIAMUserRepository) -- dipakai kalau ada, karena
           ini kontrak paling eksplisit dan tidak beresiko memicu efek
           samping apa pun.
        2. Repository dengan atribut instance biasa `_session` (bukan
           property) -- langsung timpa nilainya.
        3. Repository dengan `session` sebagai property YANG PUNYA SETTER
           (`@session.setter`) -- baru di-assign lewat `repo.session = ...`.

        PERBAIKAN BUG (root cause "Session not set" yang tadinya
        menjatuhkan SEMUA service yang lewat `async with self._uow:`,
        termasuk COAService dan CustomerService):

        Versi lama pakai `hasattr(repo, "session")` di level INSTANCE
        untuk mendeteksi apakah `session` bisa di-assign. `hasattr()`
        bekerja dengan cara memanggil getter properti tsb -- dan getter
        `session` di sejumlah repository (mis. SQLAlchemyIAMUserRepository)
        sengaja `raise` exception kustom (bukan AttributeError) kalau
        session belum pernah di-set (desain fail-fast yang benar untuk
        pemakaian LANGSUNG). Karena `hasattr()` cuma menahan AttributeError,
        exception itu bocor dan menjatuhkan seluruh proses attach session
        untuk SEMUA repository lain juga.

        Percobaan fix pertama (cek `hasattr(type(repo), "session")` di
        level class supaya tidak memicu getter) berhasil menghindari
        exception itu, tapi memunculkan bug KEDUA: pada repository yang
        `session`-nya property READ-ONLY (hanya ada getter, setter
        sebenarnya lewat method terpisah `set_session()`), baris
        `repo.session = ...` tetap gagal dengan
        `AttributeError: property 'session' has no setter`.

        Fix final di bawah ini menangani ketiga pola sekaligus, dan selalu
        mengecek keberadaan `set_session()` / property setter TANPA pernah
        memanggil getter `session` sama sekali -- baik lewat `hasattr()`
        biasa (aman untuk method, karena method bukan property jadi tidak
        ada getter yang terpicu) maupun lewat inspeksi `property.fset`
        di level class (juga tidak memanggil getter).
        """
        if hasattr(repo, "set_session"):
            repo.set_session(session)
            return
        if hasattr(repo, "_session"):
            repo._session = session
            return
        prop = getattr(type(repo), "session", None)
        if isinstance(prop, property) and prop.fset is not None:
            repo.session = session

    def _attach_session_to_repositories(self) -> None:
        """Set session pada setiap repository yang sudah diinisialisasi."""
        for repo in self._repositories.values():
            if repo is None:
                continue
            self._assign_session(repo, self._session)

    # ------------------------------------------------------------------------
    # LAZY SESSION FACTORY
    # ------------------------------------------------------------------------

    async def _get_session_factory(self) -> Any:
        """Mendapatkan async_sessionmaker secara lazy."""
        if self._session_factory is not None:
            return self._session_factory

        try:
            session_module = importlib.import_module(
                "infrastructure.database.session_factory_sqlalchemy"
            )
            getter = getattr(session_module, "get_async_session_factory", None)
            if getter is None:
                raise UnitOfWorkError(
                    "get_async_session_factory not found in session_factory_sqlalchemy"
                )
            self._session_factory = await getter()
            return self._session_factory
        except ImportError as e:
            raise UnitOfWorkError(
                f"Could not import session_factory_sqlalchemy: {e}"
            ) from e
        except Exception as e:
            raise UnitOfWorkError(
                f"Failed to get async session factory: {e}"
            ) from e

    # ------------------------------------------------------------------------
    # CONTEXT MANAGER ENTRY / EXIT (diperbaiki)
    # ------------------------------------------------------------------------

    async def __aenter__(self) -> SQLAlchemyUnitOfWork:
        if self._session_factory is None:
            self._session_factory = await self._get_session_factory()

        self._session = self._session_factory()

        if self._is_period_closing:
            await self._session.execute(sa_text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"), {})
            try:
                from infrastructure.telemetry.structured_json_logging import get_logger
                log = get_logger(__name__)
                log.info("UoW using SERIALIZABLE isolation for period closing")
            except ImportError:
                pass

        # Memulai transaksi dengan benar: ambil context manager dan masuk ke dalamnya
        self._transaction = await self._session.begin().__aenter__()

        self._ensure_repositories_initialized()
        self._attach_session_to_repositories()
        self._transaction_id = str(uuid4())
        self._is_active = True

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        try:
            # Jika ada exception dan transaksi masih aktif, rollback
            if exc_type is not None and self._transaction is not None:
                await self._transaction.rollback()
                self._transaction = None
                # Jalankan after_rollback hooks
                for hook in self._after_rollback_hooks:
                    if callable(hook):
                        if hasattr(hook, "__await__"):
                            await hook()
                        else:
                            hook()
                self._is_active = False
            elif exc_type is None and self._transaction is not None:
                # Tidak ada exception, commit transaksi
                await self._transaction.commit()
                self._transaction = None
                # Publish events
                await self._publish_events()
                # Jalankan after_commit hooks
                for hook in self._after_commit_hooks:
                    if callable(hook):
                        if hasattr(hook, "__await__"):
                            await hook()
                        else:
                            hook()
                self._is_active = False
        except Exception as e:
            logger.error(f"Error during transaction completion: {e}")
            # Coba rollback jika masih ada transaksi
            if self._transaction is not None:
                try:
                    await self._transaction.rollback()
                except Exception as rollback_e:
                    logger.debug(f"Rollback error during cleanup: {rollback_e}")
                self._transaction = None
            raise UnitOfWorkCommitError(f"Transaction commit/rollback failed: {e}") from e
        finally:
            if self._session:
                try:
                    await self._session.close()
                except Exception as e:
                    logger.debug(f"Error closing session: {e}")
            self._session = None
            self._is_active = False

    # ------------------------------------------------------------------------
    # METODE UNIT OF WORK PORT (diperbaiki)
    # ------------------------------------------------------------------------

    async def begin(self, isolation_level: str = "READ_COMMITTED") -> None:
        """Memulai transaksi secara eksplisit."""
        if self._session is None:
            if self._session_factory is None:
                self._session_factory = await self._get_session_factory()
            self._session = self._session_factory()
            # Mulai transaksi
            self._transaction = await self._session.begin().__aenter__()
            self._ensure_repositories_initialized()
            self._attach_session_to_repositories()
            self._transaction_id = str(uuid4())
            self._is_active = True
        else:
            # Sudah ada transaksi, abaikan
            pass

    async def begin_read_only(self) -> None:
        """Memulai transaksi read-only."""
        await self.begin(isolation_level="READ COMMITTED")
        if self._session:
            await self._session.execute(sa_text("SET TRANSACTION READ ONLY"), {})

    async def commit(self) -> None:
        if not self._session or not self._transaction:
            raise UnitOfWorkError("UoW not started or transaction not active")

        try:
            # Before hooks
            for hook in self._before_commit_hooks:
                if callable(hook):
                    if hasattr(hook, "__await__"):
                        await hook()
                    else:
                        hook()

            await self._session.flush()
            await self._transaction.commit()
            self._transaction = None
            await self._publish_events()

            # After hooks
            for hook in self._after_commit_hooks:
                if callable(hook):
                    if hasattr(hook, "__await__"):
                        await hook()
                    else:
                        hook()

            self._is_active = False
        except Exception as e:
            await self.rollback()
            raise UnitOfWorkCommitError(f"Commit failed: {e}") from e

    async def rollback(self) -> None:
        if not self._transaction:
            return
        try:
            await self._transaction.rollback()
            self._transaction = None
            for hook in self._after_rollback_hooks:
                if callable(hook):
                    if hasattr(hook, "__await__"):
                        await hook()
                    else:
                        hook()
            self._is_active = False
        except Exception as e:
            raise UnitOfWorkRollbackError(f"Rollback failed: {e}") from e
        finally:
            self._event_collector.clear()

    async def flush(self) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.flush()

    async def execute_raw_sql(self, statement: str, params: dict[str, Any] | None = None) -> Any:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        return await self._session.execute(sa_text(statement), params or {})

    # ------------------------------------------------------------------------
    # SAVEPOINT
    # ------------------------------------------------------------------------

    async def create_savepoint(self, name: str) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(sa_text("SAVEPOINT " + name), {})

    async def rollback_to_savepoint(self, name: str) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(sa_text("ROLLBACK TO SAVEPOINT " + name), {})

    async def release_savepoint(self, name: str) -> None:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self._session.execute(sa_text("RELEASE SAVEPOINT " + name), {})
        self._savepoint_depth -= 1

    @asynccontextmanager
    async def savepoint(self, name: str) -> AsyncContextManager:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        await self.create_savepoint(name)
        try:
            yield
            await self.release_savepoint(name)
        except Exception:
            await self.rollback_to_savepoint(name)
            raise

    @asynccontextmanager
    async def transaction(self) -> AsyncContextManager:
        if not self._session:
            raise UnitOfWorkError("UoW not started")
        sp_name = f"sp_{uuid4().hex[:8]}"
        async with self.savepoint(sp_name):
            yield

    # ------------------------------------------------------------------------
    # HOOKS
    # ------------------------------------------------------------------------

    def add_before_commit_hook(self, hook: Callable) -> None:
        if callable(hook):
            self._before_commit_hooks.append(hook)

    def add_after_commit_hook(self, hook: Callable) -> None:
        if callable(hook):
            self._after_commit_hooks.append(hook)

    def add_after_rollback_hook(self, hook: Callable) -> None:
        if callable(hook):
            self._after_rollback_hooks.append(hook)

    # ------------------------------------------------------------------------
    # TRANSACTION INFO
    # ------------------------------------------------------------------------

    async def get_transaction_id(self) -> str | None:
        return self._transaction_id

    async def get_isolation_level(self) -> str:
        if not self._session:
            return "UNKNOWN"
        try:
            result = await self._session.execute(sa_text("SHOW transaction_isolation"), {})
            return result.scalar()
        except Exception:
            return "READ_COMMITTED"

    async def is_active(self) -> bool:
        return self._is_active and self._session is not None and self._transaction is not None

    # ------------------------------------------------------------------------
    # CHANGE LOGGING
    # ------------------------------------------------------------------------

    def record_change(self, entity: Any, change_type: str) -> None:
        self._change_log.append({
            "entity": str(entity),
            "change_type": change_type,
            "timestamp": datetime.utcnow().isoformat(),
        })
        if len(self._change_log) > 1000:
            self._change_log = self._change_log[-500:]

    # ------------------------------------------------------------------------
    # REPOSITORY MANAGEMENT
    # ------------------------------------------------------------------------

    def register_repository(self, name: str, repository: Any) -> None:
        # Pakai helper yang sama dengan _attach_session_to_repositories()
        # supaya perilakunya konsisten di semua titik attach session.
        self._repositories[name] = repository
        if self._session:
            self._assign_session(repository, self._session)

    def get_repository(self, name: str) -> Any:
        if name not in self._repositories:
            raise KeyError(f"Repository '{name}' not registered")
        return self._repositories[name]

    def add_event(self, event: Any) -> None:
        self._event_collector.append(event)

    async def _publish_events(self) -> None:
        if not self._event_collector:
            return

        outbox_repo = self.get_repository("outbox")
        if outbox_repo is None:
            return

        for event in self._event_collector:
            if hasattr(outbox_repo, "save_event"):
                await outbox_repo.save_event(event)
            # else: fallback

        self._event_collector.clear()

    # ------------------------------------------------------------------------
    # RepositoryProvider interface (convenience)
    # ------------------------------------------------------------------------

    def journals(self): return self.get_repository("journal")
    def ledger_entries(self): return self.get_repository("ledger")
    def accounts(self): return self.get_repository("account")
    def ar_invoices(self): return self.get_repository("ar")
    def ap_invoices(self): return self.get_repository("ap")
    def inventory(self): return self.get_repository("inventory")
    def fixed_assets(self): return self.get_repository("fixed_asset")
    def bank_cash(self): return self.get_repository("bank_cash")
    def tax(self): return self.get_repository("tax")
    def legal_entities(self): return self.get_repository("legal_entity")
    def iam_users(self): return self.get_repository("iam_user")
    def system_settings(self): return self.get_repository("system_setting")

    @property
    def session(self):
        """Mengembalikan session async yang aktif."""
        if self._session is None:
            raise UnitOfWorkError("UoW not started")
        return self._session


# ============================================================================
# FACTORY
# ============================================================================

class SQLAlchemyUnitOfWorkFactory:
    def __init__(self, session_factory: Any = None):
        self._session_factory = session_factory

    def create(self, is_period_closing: bool = False) -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(
            session_factory=self._session_factory,
            is_period_closing=is_period_closing,
        )

    @asynccontextmanager
    async def transactional(self, is_period_closing: bool = False):
        uow = self.create(is_period_closing)
        async with uow:
            yield uow


# ============================================================================
# SINGLETON
# ============================================================================

_uow_factory: SQLAlchemyUnitOfWorkFactory | None = None

def get_uow_factory() -> SQLAlchemyUnitOfWorkFactory:
    global _uow_factory
    if _uow_factory is None:
        _uow_factory = SQLAlchemyUnitOfWorkFactory()
    return _uow_factory

async def get_uow() -> SQLAlchemyUnitOfWork:
    factory = get_uow_factory()
    uow = factory.create()
    async with uow:
        return uow


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SQLAlchemyUnitOfWorkImpl = SQLAlchemyUnitOfWork
SqlAlchemyUnitOfWork = SQLAlchemyUnitOfWork

__all__ = [
    "SQLAlchemyUnitOfWork",
    "SQLAlchemyUnitOfWorkFactory",
    "SQLAlchemyUnitOfWorkImpl",
    "SqlAlchemyUnitOfWork",
    "UnitOfWorkCommitError",
    "UnitOfWorkError",
    "UnitOfWorkRollbackError",
    "get_uow",
    "get_uow_factory",
]
