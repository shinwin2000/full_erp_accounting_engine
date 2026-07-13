#!/usr/bin/env python3
"""
Adapter: Bank Statement Import
Layer: Adapters (Secondary Implementation)

Implementasi nyata untuk mengimpor laporan bank.
Menggunakan port BankStatementImportPort dan menambahkan
persistensi ke database serta audit logging.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from infrastructure.database.session_factory_sqlalchemy import get_async_session
from infrastructure.persistence_orm.bank_reconciliation_table import BankReconciliationTable
from infrastructure.persistence_orm.bank_transaction_table import BankTransactionTable
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.bank_statement_import_port import (
    BankStatementImport,
    BankStatementImportPort,
    ImportStatus,
    StatementFormat,
    StatementTransaction,
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
        self._audit_log: list[dict[str, Any]] = []
        self._current_bank_account_id: UUID | None = None  # untuk keperluan parsing

    async def _get_session(self):
        if self._session is None:
            self._session = await get_async_session()
        return self._session

    async def _log_audit(self, action: str, import_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "import_id": str(import_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    def _dict_to_transaction(self, data: dict) -> StatementTransaction:
        """Convert dict to StatementTransaction object."""
        try:
            return StatementTransaction(**data)
        except TypeError:
            from types import SimpleNamespace
            return SimpleNamespace(**data)

    async def parse_and_import(
        self,
        file_content: str,
        file_name: str,
        bank_account_id: UUID,
        user_id: UUID,
        statement_date: date | None = None,
        override_format: StatementFormat | None = None,
    ) -> BankStatementImport:
        # Simpan bank_account_id untuk digunakan di method parse_*
        self._current_bank_account_id = bank_account_id

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
            await self._log_audit("IMPORT", import_record.id, {
                "file_name": file_name,
                "bank_account_id": str(bank_account_id),
                "transactions": import_record.imported_transactions,
            })
            logger.info(
                f"Bank statement import persisted: {import_record.id} "
                f"({import_record.imported_transactions} transactions)"
            )
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to persist bank statement import: {e}")
            import_record.status = ImportStatus.FAILED
            import_record.errors.append(str(e))
            raise

        return import_record

    async def health_check(self) -> dict[str, Any]:
        health = await super().health_check()
        health["adapter_type"] = "sqlalchemy"
        return health

    # ========================================================================
    # METODE PORT (sesuai kontrak)
    # ========================================================================

    async def get_all_imports(
        self,
        bank_account_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BankStatementImport]:
        """
        Ambil semua import dengan jumlah transaksi masing-masing.
        Menggunakan LEFT JOIN + GROUP BY untuk menghindari N+1.
        """
        session = await self._get_session()
        # Satu query dengan LEFT JOIN dan GROUP BY
        stmt = (
            select(
                BankReconciliationTable,
                func.count(BankTransactionTable.id).label("tx_count")
            )
            .outerjoin(
                BankTransactionTable,
                BankTransactionTable.import_id == BankReconciliationTable.id
            )
        )
        if bank_account_id:
            stmt = stmt.where(BankReconciliationTable.bank_account_id == bank_account_id)
        stmt = stmt.group_by(BankReconciliationTable.id)
        stmt = stmt.order_by(BankReconciliationTable.created_at.desc()).offset(offset).limit(limit)
        result = await session.execute(stmt)
        rows = result.all()

        imports = []
        for row in rows:
            recon, tx_count = row  # row is a tuple (BankReconciliationTable, count)
            imp = BankStatementImport(
                id=recon.id,
                bank_account_id=recon.bank_account_id,
                statement_date=recon.statement_date,
                statement_balance=recon.ending_balance,
                imported_transactions=tx_count,
                duplicates_skipped=0,
                errors=[],
                status=ImportStatus(recon.status),
                created_at=recon.created_at,
                completed_at=recon.completed_at,
            )
            imports.append(imp)
        return imports

    async def get_audit_log(
        self,
        import_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        logs = self._audit_log
        if import_id:
            logs = [l for l in logs if l.get("import_id") == str(import_id)]
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def get_import_status(self, import_id: UUID) -> BankStatementImport | None:
        session = await self._get_session()
        stmt = select(BankReconciliationTable).where(BankReconciliationTable.id == import_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        tx_count_stmt = select(func.count()).where(BankTransactionTable.import_id == row.id)
        tx_count = (await session.execute(tx_count_stmt)).scalar() or 0

        return BankStatementImport(
            id=row.id,
            bank_account_id=row.bank_account_id,
            statement_date=row.statement_date,
            statement_balance=row.ending_balance,
            imported_transactions=tx_count,
            duplicates_skipped=0,
            errors=[],
            status=ImportStatus(row.status),
            created_at=row.created_at,
            completed_at=row.completed_at,
        )

    async def get_imported_transactions(
        self,
        import_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StatementTransaction]:
        session = await self._get_session()
        stmt = select(BankTransactionTable).where(
            BankTransactionTable.import_id == import_id
        ).order_by(BankTransactionTable.transaction_date).offset(offset).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        transactions = []
        for row in rows:
            tx_data = {
                "id": row.id,
                "bank_account_id": row.bank_account_id,
                "transaction_date": row.transaction_date,
                "amount": row.amount,
                "currency": row.currency,
                "description": row.description,
                "reference_number": row.reference_number,
                "counterparty_name": row.counterparty_name,
                "counterparty_account": row.counterparty_account,
                "transaction_type": row.transaction_type,
                "statement_balance": row.statement_balance,
                "unique_id": row.unique_id,
                "import_id": row.import_id,
            }
            transactions.append(self._dict_to_transaction(tx_data))
        return transactions

    # --------------------------------------------------------------------
    # METODE PARSING (sesuai kontrak port)
    # --------------------------------------------------------------------

    async def parse_camt(self, file_content: str) -> list[StatementTransaction]:
        """
        Parse CAMT (ISO 20022) format. Hanya menerima file_content.
        """
        # Jika parent memiliki implementasi, gunakan.
        if hasattr(super(), "_parse_camt"):
            raw = await super()._parse_camt(file_content)
            if raw and isinstance(raw[0], dict):
                return [self._dict_to_transaction(item) for item in raw]
            return raw
        logger.info("parse_camt called but not implemented; returning empty list.")
        return []

    async def parse_mt940(self, file_content: str) -> list[StatementTransaction]:
        """
        Parse MT940 (SWIFT) format. Hanya menerima file_content.
        """
        if hasattr(super(), "_parse_mt940"):
            raw = await super()._parse_mt940(file_content)
            if raw and isinstance(raw[0], dict):
                return [self._dict_to_transaction(item) for item in raw]
            return raw
        logger.info("parse_mt940 called but not implemented; returning empty list.")
        return []

    async def parse_csv(self, file_content: str, bank_format: str) -> list[StatementTransaction]:
        """
        Parse CSV format dengan parameter bank_format (sesuai port).
        """
        if hasattr(super(), "_parse_csv"):
            raw = await super()._parse_csv(file_content, bank_format)
            if raw and isinstance(raw[0], dict):
                return [self._dict_to_transaction(item) for item in raw]
            return raw
        logger.info("parse_csv called but not implemented; returning empty list.")
        return []


__all__ = ["BankStatementImportAdapter"]
