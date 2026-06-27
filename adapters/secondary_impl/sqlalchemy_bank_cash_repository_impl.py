#!/usr/bin/env python3
"""
Module: sqlalchemy_bank_cash_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Bank & Cash Management menggunakan
               SQLAlchemy ORM. Menyediakan operasi CRUD untuk bank account,
               cash book, petty cash fund, bank transactions, bank reconciliation,
               dan cash flow tracking. Mendukung multiple currency, soft delete,
               dan optimistic locking untuk bank account master.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.bank_cash.bank_aggregate_root import (
    BankAccountAggregate,
    BankAccountStatus,
    BankReconciliation,
    BankTransaction,
    BankTransactionType,
)
from domain.bank_cash.cash_aggregate_root import CashBookAggregate, PettyCashFund

# Value objects
from domain.shared_value_objects.money_vo import Money

# Infrastructure ORM
from infrastructure.persistence_orm.bank_account_table import BankAccountTable
from infrastructure.persistence_orm.bank_reconciliation_table import BankReconciliationTable
from infrastructure.persistence_orm.bank_transaction_table import BankTransactionTable
from infrastructure.persistence_orm.cash_book_table import CashBookTable
from infrastructure.persistence_orm.petty_cash_fund_table import PettyCashFundTable

# Ports
from ports.primary.bank_cash_repository_port import BankAccountRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CURRENCY = "IDR"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class BankCashRepositoryError(Exception):
    """Base exception untuk repository bank & cash."""
    pass


class DuplicateAccountNumberError(BankCashRepositoryError):
    """Nomor rekening sudah ada."""
    pass


class BankAccountNotFoundError(BankCashRepositoryError):
    """Rekening bank tidak ditemukan."""
    pass


class CashBookNotFoundError(BankCashRepositoryError):
    """Cash book tidak ditemukan."""
    pass


class InsufficientBalanceError(BankCashRepositoryError):
    """Saldo tidak mencukupi untuk transaksi."""
    pass


class ReconciliationNotFoundError(BankCashRepositoryError):
    """Rekonsiliasi tidak ditemukan."""
    pass


class OptimisticLockError(BankCashRepositoryError):
    """Version mismatch saat update."""
    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyBankAccountRepository(BankAccountRepositoryPort):
    """
    Implementasi repository Bank & Cash dengan SQLAlchemy.
    Mengimplementasi BankAccountRepositoryPort.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = None
        if session is not None:
            if hasattr(session, "session"):
                self._session = session.session
            else:
                self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise BankCashRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER MAPPING METHODS - BANK ACCOUNT
    # ========================================================================

    def _to_domain_bank_account(self, table: BankAccountTable) -> BankAccountAggregate:
        status_map = {
            "active": BankAccountStatus.ACTIVE,
            "inactive": BankAccountStatus.INACTIVE,
            "suspended": BankAccountStatus.SUSPENDED,
            "closed": BankAccountStatus.CLOSED,
        }

        return BankAccountAggregate(
            id=table.id,
            account_number=table.account_number,
            bank_name=table.bank_name,
            bank_code=table.bank_code,
            account_name=table.account_name,
            currency_code=table.currency_code,
            account_type=table.account_type,
            current_balance=Money(amount=table.current_balance, currency=table.currency_code),
            available_balance=Money(amount=table.available_balance, currency=table.currency_code),
            gl_account_id=table.gl_account_id,
            is_active=table.is_active,
            is_default=table.is_default,
            status=status_map.get(table.status, BankAccountStatus.ACTIVE),
            opening_balance=Money(amount=table.opening_balance, currency=table.currency_code),
            opening_balance_date=table.opening_balance_date,
            last_reconciliation_date=table.last_reconciliation_date,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
            legal_entity_id=table.legal_entity_id,
        )

    async def _to_orm_bank_account(self, aggregate: BankAccountAggregate) -> BankAccountTable:
        status_str = (
            aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        )

        return BankAccountTable(
            id=aggregate.id,
            account_number=aggregate.account_number,
            bank_name=aggregate.bank_name,
            bank_code=aggregate.bank_code,
            account_name=aggregate.account_name,
            currency_code=aggregate.currency_code,
            account_type=aggregate.account_type,
            current_balance=aggregate.current_balance.amount,
            available_balance=aggregate.available_balance.amount,
            gl_account_id=aggregate.gl_account_id,
            is_active=aggregate.is_active,
            is_default=aggregate.is_default,
            status=status_str,
            opening_balance=aggregate.opening_balance.amount,
            opening_balance_date=aggregate.opening_balance_date,
            last_reconciliation_date=aggregate.last_reconciliation_date,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
        )

    # ========================================================================
    # HELPER MAPPING METHODS - BANK TRANSACTION
    # ========================================================================

    def _to_domain_transaction(self, table: BankTransactionTable) -> BankTransaction:
        type_map = {
            "deposit": BankTransactionType.DEPOSIT,
            "withdrawal": BankTransactionType.WITHDRAWAL,
            "transfer_in": BankTransactionType.TRANSFER_IN,
            "transfer_out": BankTransactionType.TRANSFER_OUT,
            "bank_charge": BankTransactionType.BANK_CHARGE,
            "interest": BankTransactionType.INTEREST,
        }

        return BankTransaction(
            id=table.id,
            transaction_number=table.transaction_number,
            bank_account_id=table.bank_account_id,
            transaction_date=table.transaction_date,
            transaction_type=type_map.get(table.transaction_type, BankTransactionType.DEPOSIT),
            amount=Money(amount=table.amount, currency=table.currency_code),
            description=table.description,
            reference_number=table.reference_number,
            counterparty_account=table.counterparty_account,
            counterparty_name=table.counterparty_name,
            journal_id=table.journal_id,
            status=table.status,
            is_reconciled=table.is_reconciled,
            reconciliation_id=table.reconciliation_id,
            created_at=table.created_at,
            created_by=table.created_by,
        )

    async def _to_orm_transaction(self, transaction: BankTransaction) -> BankTransactionTable:
        type_str = (
            transaction.transaction_type.value
            if hasattr(transaction.transaction_type, "value")
            else str(transaction.transaction_type)
        )

        return BankTransactionTable(
            id=transaction.id,
            transaction_number=transaction.transaction_number,
            bank_account_id=transaction.bank_account_id,
            transaction_date=transaction.transaction_date,
            transaction_type=type_str,
            amount=transaction.amount.amount,
            currency_code=transaction.amount.currency,
            description=transaction.description,
            reference_number=transaction.reference_number,
            counterparty_account=transaction.counterparty_account,
            counterparty_name=transaction.counterparty_name,
            journal_id=transaction.journal_id,
            status=transaction.status,
            is_reconciled=transaction.is_reconciled,
            reconciliation_id=transaction.reconciliation_id,
            created_at=transaction.created_at,
            created_by=transaction.created_by,
        )

    # ========================================================================
    # HELPER MAPPING METHODS - CASH BOOK
    # ========================================================================

    def _to_domain_cash_book(self, table: CashBookTable) -> CashBookAggregate:
        return CashBookAggregate(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            currency_code=table.currency_code,
            current_balance=Money(amount=table.current_balance, currency=table.currency_code),
            opening_balance=Money(amount=table.opening_balance, currency=table.currency_code),
            opening_balance_date=table.opening_balance_date,
            gl_cash_account_id=table.gl_cash_account_id,
            gl_bank_account_id=table.gl_bank_account_id,
            last_updated=table.last_updated,
            created_at=table.created_at,
            created_by=table.created_by,
            version=table.version,
        )

    # ========================================================================
    # BANK ACCOUNT METHODS (Implementasi Internal)
    # ========================================================================

    async def add_bank_account(self, account: BankAccountAggregate) -> None:
        try:
            exists = await self.exists_by_account_number(
                account.account_number, account.legal_entity_id
            )
            if exists:
                raise DuplicateAccountNumberError(
                    f"Account number {account.account_number} already exists"
                )

            table = await self._to_orm_bank_account(account)
            self.session.add(table)
            await self.session.flush()
            logger.info("Bank account added: %s - %s", account.account_number, account.bank_name)

        except DuplicateAccountNumberError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add bank account: {e}") from e

    async def get_bank_account_by_id(self, account_id: UUID) -> BankAccountAggregate | None:
        try:
            stmt = select(BankAccountTable).where(
                BankAccountTable.id == account_id, BankAccountTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_bank_account(table)

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get bank account: {e}") from e

    async def get_bank_account_by_number(
        self, account_number: str, legal_entity_id: UUID
    ) -> BankAccountAggregate | None:
        try:
            stmt = select(BankAccountTable).where(
                BankAccountTable.account_number == account_number,
                BankAccountTable.legal_entity_id == legal_entity_id,
                BankAccountTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_bank_account(table)

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get bank account: {e}") from e

    async def update_bank_account(self, account: BankAccountAggregate) -> None:
        try:
            stmt = select(BankAccountTable.version).where(BankAccountTable.id == account.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()

            if current_version is None:
                raise BankAccountNotFoundError(f"Bank account {account.id} not found")

            if current_version != account.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {account.version}, got {current_version}"
                )

            table = await self._to_orm_bank_account(account)
            table.version = account.version + 1
            table.updated_at = datetime.utcnow()

            await self.session.merge(table)
            await self.session.flush()
            logger.info("Bank account updated: %s", account.account_number)

        except (OptimisticLockError, BankAccountNotFoundError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update bank account: {e}") from e

    async def delete_bank_account(self, account_id: UUID) -> bool:
        try:
            stmt = (
                update(BankAccountTable)
                .where(BankAccountTable.id == account_id)
                .values(deleted_at=datetime.utcnow(), is_active=False, status="closed")
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount > 0

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to delete bank account: {e}") from e

    async def list_bank_accounts(
        self, legal_entity_id: UUID, is_active: bool | None = True
    ) -> list[BankAccountAggregate]:
        try:
            conditions = [
                BankAccountTable.legal_entity_id == legal_entity_id,
                BankAccountTable.deleted_at.is_(None),
            ]
            if is_active is not None:
                conditions.append(BankAccountTable.is_active == is_active)

            stmt = (
                select(BankAccountTable)
                .where(and_(*conditions))
                .order_by(BankAccountTable.account_number)
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_bank_account(table) for table in tables]

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to list bank accounts: {e}") from e

    async def update_bank_balance(
        self, account_id: UUID, new_balance: Decimal, new_available_balance: Decimal, version: int
    ) -> None:
        try:
            stmt = (
                update(BankAccountTable)
                .where(BankAccountTable.id == account_id, BankAccountTable.version == version)
                .values(
                    current_balance=new_balance,
                    available_balance=new_available_balance,
                    version=version + 1,
                    updated_at=datetime.utcnow(),
                )
            )
            result = await self.session.execute(stmt)

            if result.rowcount == 0:
                raise OptimisticLockError(f"Failed to update balance for account {account_id}")

            await self.session.flush()

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update balance: {e}") from e

    async def exists_by_account_number(self, account_number: str, legal_entity_id: UUID) -> bool:
        try:
            stmt = (
                select(func.count())
                .select_from(BankAccountTable)
                .where(
                    BankAccountTable.account_number == account_number,
                    BankAccountTable.legal_entity_id == legal_entity_id,
                    BankAccountTable.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to check account number: {e}") from e

    # ========================================================================
    # BANK TRANSACTION METHODS (Implementasi Internal)
    # ========================================================================

    async def add_bank_transaction(self, transaction: BankTransaction) -> None:
        try:
            table = await self._to_orm_transaction(transaction)
            self.session.add(table)
            await self.session.flush()
            logger.info("Bank transaction added: %s", transaction.transaction_number)

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add bank transaction: {e}") from e

    async def get_bank_transaction_by_id(self, transaction_id: UUID) -> BankTransaction | None:
        try:
            stmt = select(BankTransactionTable).where(BankTransactionTable.id == transaction_id)
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_transaction(table)

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get transaction: {e}") from e

    async def get_bank_transactions_by_account(
        self,
        bank_account_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        is_reconciled: bool | None = None,
        limit: int = 100,
    ) -> list[BankTransaction]:
        try:
            conditions = [BankTransactionTable.bank_account_id == bank_account_id]
            if start_date:
                conditions.append(BankTransactionTable.transaction_date >= start_date)
            if end_date:
                conditions.append(BankTransactionTable.transaction_date <= end_date)
            if is_reconciled is not None:
                conditions.append(BankTransactionTable.is_reconciled == is_reconciled)

            stmt = (
                select(BankTransactionTable)
                .where(and_(*conditions))
                .order_by(BankTransactionTable.transaction_date)
                .limit(limit)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_transaction(table) for table in tables]

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get transactions: {e}") from e

    async def get_balance_before_date(self, bank_account_id: UUID, as_of_date: date) -> Decimal:
        try:
            stmt = select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                BankTransactionTable.transaction_type.in_(
                                    ["deposit", "transfer_in"]
                                ),
                                BankTransactionTable.amount,
                            ),
                            else_=-BankTransactionTable.amount,
                        )
                    ),
                    0,
                )
            ).where(
                BankTransactionTable.bank_account_id == bank_account_id,
                BankTransactionTable.transaction_date < as_of_date,
                BankTransactionTable.status == "posted",
            )

            result = await self.session.execute(stmt)
            balance = result.scalar() or 0

            account_stmt = select(BankAccountTable.opening_balance).where(
                BankAccountTable.id == bank_account_id
            )
            account_result = await self.session.execute(account_stmt)
            opening_balance = account_result.scalar() or 0

            return Decimal(str(opening_balance)) + Decimal(str(balance))

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get balance: {e}") from e

    async def mark_transaction_as_reconciled(
        self, transaction_id: UUID, reconciliation_id: UUID
    ) -> None:
        try:
            stmt = (
                update(BankTransactionTable)
                .where(BankTransactionTable.id == transaction_id)
                .values(
                    is_reconciled=True,
                    reconciliation_id=reconciliation_id,
                    updated_at=datetime.utcnow(),
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to mark transaction: {e}") from e

    # ========================================================================
    # BANK RECONCILIATION METHODS (Implementasi Internal)
    # ========================================================================

    async def add_reconciliation(self, reconciliation: BankReconciliation) -> UUID:
        try:
            table = BankReconciliationTable(
                id=reconciliation.id,
                bank_account_id=reconciliation.bank_account_id,
                statement_date=reconciliation.statement_date,
                book_balance=reconciliation.book_balance.amount,
                statement_balance=reconciliation.statement_balance.amount,
                difference=reconciliation.difference.amount,
                matched_count=reconciliation.matched_count,
                unmatched_book=reconciliation.unmatched_book,
                unmatched_statement=reconciliation.unmatched_statement,
                adjustment_journal_id=reconciliation.adjustment_journal_id,
                status=reconciliation.status,
                created_by=reconciliation.created_by,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()

            stmt = (
                update(BankAccountTable)
                .where(BankAccountTable.id == reconciliation.bank_account_id)
                .values(
                    last_reconciliation_date=reconciliation.statement_date,
                    available_balance=reconciliation.statement_balance.amount,
                    updated_at=datetime.utcnow(),
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()

            logger.info("Bank reconciliation added for account %s", reconciliation.bank_account_id)
            return reconciliation.id

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add reconciliation: {e}") from e

    async def get_reconciliation_history(
        self, bank_account_id: UUID, limit: int = 12
    ) -> list[BankReconciliation]:
        try:
            stmt = (
                select(BankReconciliationTable)
                .where(BankReconciliationTable.bank_account_id == bank_account_id)
                .order_by(BankReconciliationTable.statement_date.desc())
                .limit(limit)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            reconciliations = []
            for table in tables:
                reconciliations.append(
                    BankReconciliation(
                        id=table.id,
                        bank_account_id=table.bank_account_id,
                        statement_date=table.statement_date,
                        book_balance=Money(amount=table.book_balance, currency=DEFAULT_CURRENCY),
                        statement_balance=Money(
                            amount=table.statement_balance, currency=DEFAULT_CURRENCY
                        ),
                        difference=Money(amount=table.difference, currency=DEFAULT_CURRENCY),
                        matched_count=table.matched_count,
                        unmatched_book=table.unmatched_book,
                        unmatched_statement=table.unmatched_statement,
                        adjustment_journal_id=table.adjustment_journal_id,
                        status=table.status,
                        created_by=table.created_by,
                        created_at=table.created_at,
                    )
                )

            return reconciliations

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get history: {e}") from e

    # ========================================================================
    # CASH BOOK METHODS (Implementasi Internal)
    # ========================================================================

    async def add_cash_book(self, cash_book: CashBookAggregate) -> UUID:
        try:
            table = CashBookTable(
                id=cash_book.id,
                legal_entity_id=cash_book.legal_entity_id,
                currency_code=cash_book.currency_code,
                current_balance=cash_book.current_balance.amount,
                opening_balance=cash_book.opening_balance.amount,
                opening_balance_date=cash_book.opening_balance_date,
                gl_cash_account_id=cash_book.gl_cash_account_id,
                gl_bank_account_id=cash_book.gl_bank_account_id,
                last_updated=datetime.utcnow(),
                created_at=datetime.utcnow(),
                created_by=cash_book.created_by,
                version=1,
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Cash book added for legal entity %s", cash_book.legal_entity_id)
            return cash_book.id

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add cash book: {e}") from e

    async def get_cash_book(
        self, legal_entity_id: UUID, currency_code: str = DEFAULT_CURRENCY
    ) -> CashBookAggregate | None:
        try:
            stmt = select(CashBookTable).where(
                CashBookTable.legal_entity_id == legal_entity_id,
                CashBookTable.currency_code == currency_code,
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_cash_book(table)

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get cash book: {e}") from e

    async def update_cash_balance(
        self, cash_book_id: UUID, new_balance: Decimal, version: int
    ) -> None:
        try:
            stmt = (
                update(CashBookTable)
                .where(CashBookTable.id == cash_book_id, CashBookTable.version == version)
                .values(
                    current_balance=new_balance, version=version + 1, last_updated=datetime.utcnow()
                )
            )
            result = await self.session.execute(stmt)

            if result.rowcount == 0:
                raise OptimisticLockError(f"Failed to update cash balance for {cash_book_id}")

            await self.session.flush()

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update cash balance: {e}") from e

    # ========================================================================
    # PETTY CASH FUND METHODS (Implementasi Internal)
    # ========================================================================

    async def add_petty_cash_fund(self, fund: PettyCashFund) -> UUID:
        try:
            table = PettyCashFundTable(
                id=fund.id,
                fund_name=fund.fund_name,
                legal_entity_id=fund.legal_entity_id,
                currency_code=fund.currency_code,
                current_balance=fund.current_balance.amount,
                initial_amount=fund.initial_amount.amount,
                custodian_id=fund.custodian_id,
                gl_account_id=fund.gl_account_id,
                reimbursement_threshold=fund.reimbursement_threshold.amount,
                fund_location=fund.fund_location,
                status=fund.status,
                created_at=datetime.utcnow(),
                created_by=fund.created_by,
                version=1,
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Petty cash fund added: %s", fund.fund_name)
            return fund.id

        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to add petty cash fund: {e}") from e

    async def get_petty_cash_funds(self, legal_entity_id: UUID) -> list[PettyCashFund]:
        try:
            stmt = select(PettyCashFundTable).where(
                PettyCashFundTable.legal_entity_id == legal_entity_id
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            funds = []
            for table in tables:
                funds.append(
                    PettyCashFund(
                        id=table.id,
                        fund_name=table.fund_name,
                        legal_entity_id=table.legal_entity_id,
                        currency_code=table.currency_code,
                        current_balance=Money(
                            amount=table.current_balance, currency=table.currency_code
                        ),
                        initial_amount=Money(
                            amount=table.initial_amount, currency=table.currency_code
                        ),
                        custodian_id=table.custodian_id,
                        gl_account_id=table.gl_account_id,
                        reimbursement_threshold=Money(
                            amount=table.reimbursement_threshold, currency=table.currency_code
                        ),
                        fund_location=table.fund_location,
                        status=table.status,
                        created_by=table.created_by,
                        created_at=table.created_at,
                        version=table.version,
                    )
                )

            return funds

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to get petty cash funds: {e}") from e

    async def update_petty_cash_balance(
        self, fund_id: UUID, new_balance: Decimal, version: int
    ) -> None:
        try:
            stmt = (
                update(PettyCashFundTable)
                .where(PettyCashFundTable.id == fund_id, PettyCashFundTable.version == version)
                .values(
                    current_balance=new_balance, version=version + 1, updated_at=datetime.utcnow()
                )
            )
            result = await self.session.execute(stmt)

            if result.rowcount == 0:
                raise OptimisticLockError(f"Failed to update petty cash balance for {fund_id}")

            await self.session.flush()

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise BankCashRepositoryError(f"Failed to update balance: {e}") from e

    # ========================================================================
    # GENERATE TRANSACTION NUMBER
    # ========================================================================

    async def get_next_transaction_number(self, prefix: str = "TRX", year: int = None) -> str:
        if year is None:
            year = date.today().year

        try:
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = (
                select(BankTransactionTable.transaction_number)
                .where(BankTransactionTable.transaction_number.like(pattern))
                .order_by(BankTransactionTable.transaction_number.desc())
                .limit(1)
            )

            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()

            if last_number:
                seq = int(last_number.split("-")[-1]) + 1
            else:
                seq = 1

            return f"{prefix}-{year}-{seq:06d}"

        except Exception as e:
            raise BankCashRepositoryError(f"Failed to generate number: {e}") from e

    # ========================================================================
    # FORWARDING METHODS UNTUK BANKACCOUNTREPOSITORYPORT (INTERFACE)
    # ========================================================================

    async def add(self, bank_account: BankAccountAggregate) -> None:
        """Forward ke add_bank_account."""
        await self.add_bank_account(bank_account)

    async def get_by_id(self, account_id: UUID) -> BankAccountAggregate | None:
        """Forward ke get_bank_account_by_id."""
        return await self.get_bank_account_by_id(account_id)

    async def get_by_account_number(self, account_number: str, bank_code: str) -> BankAccountAggregate | None:
        """Forward ke get_bank_account_by_number dengan bank_code."""
        try:
            stmt = select(BankAccountTable).where(
                BankAccountTable.account_number == account_number,
                BankAccountTable.bank_code == bank_code,
                BankAccountTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_bank_account(table)
        except Exception as e:
            logger.error("Failed to get bank account by number: %s", e)
            return None

    async def update(self, bank_account: BankAccountAggregate) -> None:
        """Forward ke update_bank_account."""
        await self.update_bank_account(bank_account)

    async def delete(self, account_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Forward ke delete_bank_account."""
        return await self.delete_bank_account(account_id)

    async def find_by_legal_entity(self, legal_entity_id: UUID) -> list[BankAccountAggregate]:
        """Forward ke list_bank_accounts."""
        return await self.list_bank_accounts(legal_entity_id)

    async def get_balance(self, bank_account_id: UUID, as_of_date: date) -> Decimal:
        """Forward ke get_balance_before_date."""
        return await self.get_balance_before_date(bank_account_id, as_of_date)

    async def record_transaction(self, transaction: BankTransaction) -> None:
        """Forward ke add_bank_transaction."""
        await self.add_bank_transaction(transaction)

    async def get_transactions(
        self, bank_account_id: UUID, start_date: date, end_date: date
    ) -> list[BankTransaction]:
        """Forward ke get_bank_transactions_by_account."""
        return await self.get_bank_transactions_by_account(
            bank_account_id, start_date, end_date, limit=1000
        )

    async def reconcile(
        self,
        bank_account_id: UUID,
        statement_date: date,
        statement_balance: Decimal,
        user_id: UUID,
        journal_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Forward ke add_reconciliation dengan return dict."""
        reconciliation = BankReconciliation(
            id=uuid4(),
            bank_account_id=bank_account_id,
            statement_date=statement_date,
            book_balance=Money(amount=Decimal(0), currency=DEFAULT_CURRENCY),
            statement_balance=Money(amount=statement_balance, currency=DEFAULT_CURRENCY),
            difference=Money(amount=Decimal(0), currency=DEFAULT_CURRENCY),
            matched_count=0,
            unmatched_book=[],
            unmatched_statement=[],
            adjustment_journal_id=journal_id,
            status="completed",
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        reconciliation_id = await self.add_reconciliation(reconciliation)
        return {
            "account_id": str(bank_account_id),
            "statement_date": statement_date.isoformat(),
            "statement_balance": float(statement_balance),
            "system_balance": 0.0,
            "difference": 0.0,
            "transactions_reconciled": 0,
            "reconciliation_id": str(reconciliation_id),
        }

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Get statistics untuk bank account."""
        accounts = await self.list_bank_accounts(legal_entity_id)
        total_balance = sum(acc.current_balance.amount for acc in accounts)
        return {
            "total_accounts": len(accounts),
            "total_balance": float(total_balance),
            "active_accounts": sum(1 for acc in accounts if acc.is_active),
            "by_currency": {},
            "by_type": {},
        }


# ============================================================================
# ALIAS FOR BACKWARD COMPATIBILITY
# ============================================================================

SQLAlchemyBankCashRepository = SQLAlchemyBankAccountRepository
SqlAlchemyBankCashRepository = SQLAlchemyBankAccountRepository


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BankAccountNotFoundError",
    "BankCashRepositoryError",
    "CashBookNotFoundError",
    "DuplicateAccountNumberError",
    "InsufficientBalanceError",
    "OptimisticLockError",
    "ReconciliationNotFoundError",
    "SQLAlchemyBankAccountRepository",
    "SQLAlchemyBankCashRepository",
    "SqlAlchemyBankCashRepository",
]
