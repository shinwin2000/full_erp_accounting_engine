#!/usr/bin/env python3
"""
Adapter: Bank Statement Import
Layer: Adapters (Secondary Implementation)

Implementasi nyata untuk mengimpor laporan bank.
Menggunakan port BankStatementImportPort dan menambahkan
persistensi ke database serta audit logging.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from infrastructure.database.session_factory_sqlalchemy import get_async_session
from infrastructure.persistence_orm.bank_reconciliation_table import BankReconciliationTable
from infrastructure.persistence_orm.bank_transaction_table import BankTransactionTable
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.bank_statement_import_port import (
    BankStatementImport,
    BankStatementImportPort,
    ImportStatus,
    StatementFormat,
)

logger = get_logger(__name__)

class BankStatementImportAdapter(BankStatementImportPort):
    """
    Adapter untuk import laporan bank dengan persistensi ke database.
    Menggunakan BankStatementImportPort sebagai basis.
    """
    def __init__(self):
        super().__init__()
        self._session = None

    async def _get_session(self):
        if self._session is None:
            self._session = await get_async_session()
        return self._session

    async def parse_and_import(
        self,
        file_content: str,
        file_name: str,
        bank_account_id: UUID,
        user_id: UUID,
        statement_date: date | None = None,
        override_format: StatementFormat | None = None,
    ) -> BankStatementImport:
        # Panggil implementasi parent (in-memory) untuk parsing dan deduplikasi
        import_record = await super().parse_and_import(
            file_content, file_name, bank_account_id, user_id,
            statement_date, override_format
        )

        # Simpan hasil import ke database (real code)
        session = await self._get_session()
        try:
            # Simpan rekonsiliasi
            recon = BankReconciliationTable(
                id=import_record.id,
                bank_account_id=bank_account_id,
                statement_date=import_record.statement_date,
                ending_balance=import_record.statement_balance,
                status=import_record.status.value,
                created_by=user_id,
                created_at=import_record.created_at,
                completed_at=import_record.completed_at,
            )
            session.add(recon)

            # Simpan transaksi yang berhasil diimport
            for tx in self._imported_transactions.get(import_record.id, []):
                tx_table = BankTransactionTable(
                    id=tx.id,
                    bank_account_id=bank_account_id,
                    transaction_date=tx.transaction_date,
                    amount=tx.amount,
                    currency=tx.currency,
                    description=tx.description,
                    reference_number=tx.reference_number,
                    counterparty_name=tx.counterparty_name,
                    counterparty_account=tx.counterparty_account,
                    transaction_type=tx.transaction_type,
                    statement_balance=tx.statement_balance,
                    unique_id=tx.unique_id,
                    import_id=import_record.id,
                )
                session.add(tx_table)

            await session.commit()
            logger.info(
                f"Bank statement import persisted: {import_record.id} "
                f"({import_record.imported_transactions} transactions)"
            )
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to persist bank statement import: {e}")
            import_record.status = ImportStatus.FAILED
            import_record.errors.append(str(e))
            # Re-raise after logging
            raise

        return import_record

    async def health_check(self) -> dict[str, Any]:
        health = await super().health_check()
        health["adapter_type"] = "sqlalchemy"
        return health

__all__ = ["BankStatementImportAdapter"]
