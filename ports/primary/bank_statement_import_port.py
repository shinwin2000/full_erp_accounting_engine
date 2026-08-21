#!/usr/bin/env python3
"""
Module: bank_statement_import_port.py
Layer: Ports (Primary)
Responsibility: Port untuk import laporan bank (MT940, CAMT, CSV).
"""

from __future__ import annotations

import abc
import asyncio
import csv
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ==================== ENUMS & DOMAIN MODELS ====================

class StatementFormat(Enum):
    MT940 = "mt940"
    CAMT_053 = "camt_053"
    CAMT_054 = "camt_054"
    CSV_BCA = "csv_bca"
    CSV_MANDIRI = "csv_mandiri"
    CSV_BNI = "csv_bni"
    CSV_BRI = "csv_bri"
    CSV_GENERIC = "csv_generic"


class ImportStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class StatementTransaction:
    id: UUID
    transaction_date: date
    amount: Decimal
    currency: str
    description: str
    reference_number: str
    counterparty_name: str | None
    counterparty_account: str | None
    transaction_type: str  # CREDIT, DEBIT
    statement_balance: Decimal | None
    unique_id: str
    original_data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "transaction_date": self.transaction_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "description": self.description,
            "reference_number": self.reference_number,
            "counterparty_name": self.counterparty_name,
            "counterparty_account": self.counterparty_account,
            "transaction_type": self.transaction_type,
            "statement_balance": str(self.statement_balance) if self.statement_balance else None,
            "unique_id": self.unique_id,
        }


@dataclass
class BankStatementImport:
    id: UUID
    bank_account_id: UUID
    file_name: str
    file_hash: str
    statement_date: date
    statement_balance: Decimal
    statement_balance_date: date
    format: StatementFormat
    status: ImportStatus
    total_transactions: int
    imported_transactions: int
    duplicate_transactions: int
    failed_transactions: int
    errors: list[str]
    created_at: datetime
    created_by: UUID
    completed_at: datetime | None = None


# ==================== PORT (INTERFACE) ====================

class BankStatementImportPort(abc.ABC):
    """Port untuk bank statement import service."""

    @abc.abstractmethod
    async def parse_and_import(
        self,
        file_content: str,
        file_name: str,
        bank_account_id: UUID,
        user_id: UUID,
        statement_date: date | None = None,
        override_format: StatementFormat | None = None,
    ) -> BankStatementImport:
        """Parse file dan import transaksi ke sistem."""
        ...

    @abc.abstractmethod
    async def get_import_status(self, import_id: UUID) -> BankStatementImport | None:
        """Dapatkan status import."""
        ...

    @abc.abstractmethod
    async def get_imported_transactions(self, import_id: UUID) -> list[StatementTransaction]:
        """Ambil transaksi hasil import."""
        ...

    @abc.abstractmethod
    async def get_all_imports(
        self, bank_account_id: UUID | None = None
    ) -> list[BankStatementImport]:
        """Daftar semua import (opsional filter bank_account)."""
        ...

    @abc.abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Ambil audit log."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check."""
        ...


# ==================== IMPLEMENTASI IN-MEMORY ====================

class InMemoryBankStatementImport(BankStatementImportPort):
    """
    In-memory bank statement import service.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self):
        self._imports: dict[UUID, BankStatementImport] = {}
        self._imported_transactions: dict[UUID, list[StatementTransaction]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def _log_audit(
        self, action: str, import_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "import_id": str(import_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"STATEMENT IMPORT AUDIT: {action} on {import_id} by {user_id}")

    async def _compute_file_hash(self, file_content: str) -> str:
        return hashlib.sha256(file_content.encode("utf-8")).hexdigest()

    async def _detect_format(self, file_content: str, file_name: str) -> StatementFormat:
        if file_name.lower().endswith(".mt940") or ":20:" in file_content[:500]:
            return StatementFormat.MT940
        if file_name.lower().endswith(".camt") or "<Document" in file_content[:500]:
            return StatementFormat.CAMT_053
        if "BCA" in file_content[:200] or "bca" in file_name.lower():
            return StatementFormat.CSV_BCA
        if "Mandiri" in file_content[:200] or "mandiri" in file_name.lower():
            return StatementFormat.CSV_MANDIRI
        if "BNI" in file_content[:200] or "bni" in file_name.lower():
            return StatementFormat.CSV_BNI
        if "BRI" in file_content[:200] or "bri" in file_name.lower():
            return StatementFormat.CSV_BRI
        return StatementFormat.CSV_GENERIC

    async def parse_mt940(self, file_content: str) -> list[StatementTransaction]:
        transactions: list[StatementTransaction] = []
        lines = file_content.splitlines()
        current_tx: dict[str, str] = {}
        for line in lines:
            if line.startswith(":61:"):
                if current_tx:
                    tx = await self._build_mt940_transaction(current_tx)
                    if tx:
                        transactions.append(tx)
                current_tx = {"raw_61": line[4:].strip()}
            elif line.startswith(":86:"):
                current_tx["description"] = line[4:].strip()
            elif current_tx and not line.startswith(":"):
                current_tx.setdefault("description", "")
                current_tx["description"] += " " + line.strip()
        if current_tx:
            tx = await self._build_mt940_transaction(current_tx)
            if tx:
                transactions.append(tx)
        return transactions

    async def _build_mt940_transaction(self, data: dict[str, str]) -> StatementTransaction | None:
        raw = data.get("raw_61", "")
        match = re.match(r"(\d{6})(C|D)(\d+(?:,\d{0,2})?)", raw)
        if not match:
            return None
        date_str, sign, amount_str = match.groups()
        try:
            txn_date = datetime.strptime(date_str, "%y%m%d").date()
        except ValueError:
            logger.error("Failed to parse MT940 date '%s' from raw string: %s", date_str, raw)
            return None
        try:
            amount = Decimal(amount_str.replace(",", "."))
        except Exception as e:
            logger.error("Failed to parse amount from string '%s': %s", amount_str, e)
            return None
        if sign == "D":
            amount = -amount
        description = data.get("description", "No description")
        unique_id = hashlib.sha256(f"{txn_date.isoformat()}{amount}{description[:50]}".encode()).hexdigest()
        return StatementTransaction(
            id=uuid4(),
            transaction_date=txn_date,
            amount=abs(amount),
            currency="IDR",
            description=description[:200],
            reference_number=raw[:20],
            counterparty_name=None,
            counterparty_account=None,
            transaction_type="CREDIT" if amount > 0 else "DEBIT",
            statement_balance=None,
            unique_id=unique_id,
            original_data={"raw": raw, "description": description},
        )

    async def parse_camt(self, file_content: str) -> list[StatementTransaction]:
        transactions: list[StatementTransaction] = []
        entries = re.findall(r"<Ntry>(.*?)</Ntry>", file_content, re.DOTALL)
        for entry in entries:
            amt_match = re.search(r"<Amt[^>]*>(\d+(?:\.\d{1,2})?)</Amt>", entry)
            date_match = re.search(r"<BookgDt><Dt>(\d{4}-\d{2}-\d{2})</Dt>", entry)
            desc_match = re.search(r"<NtryDtls><TxDtls><Refs><MndtId>([^<]+)</MndtId>", entry)
            if not amt_match or not date_match:
                continue
            amount = Decimal(amt_match.group(1))
            txn_date = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
            description = desc_match.group(1) if desc_match else "CAMT transaction"
            unique_id = hashlib.sha256(f"{txn_date}{amount}{description}".encode()).hexdigest()
            transactions.append(
                StatementTransaction(
                    id=uuid4(),
                    transaction_date=txn_date,
                    amount=abs(amount),
                    currency="IDR",
                    description=description[:200],
                    reference_number=hashlib.md5(entry[:100].encode()).hexdigest()[:16],
                    counterparty_name=None,
                    counterparty_account=None,
                    transaction_type="CREDIT" if amount > 0 else "DEBIT",
                    statement_balance=None,
                    unique_id=unique_id,
                    original_data={"xml_snippet": entry[:200]},
                )
            )
        return transactions

    async def parse_csv(self, file_content: str, bank_format: str) -> list[StatementTransaction]:
        reader = csv.reader(file_content.splitlines())
        headers = next(reader, None)
        if not headers:
            return []
        transactions: list[StatementTransaction] = []
        for row in reader:
            if not row or len(row) < 3:
                continue
            try:
                if bank_format == "BCA":
                    txn_date = datetime.strptime(row[0].strip(), "%d/%m/%Y").date()
                    description = row[1].strip()
                    debit = Decimal(row[2].replace(",", "")) if row[2] else Decimal(0)
                    credit = Decimal(row[3].replace(",", "")) if row[3] else Decimal(0)
                    amount = credit if credit > 0 else -debit
                    tx_type = "CREDIT" if credit > 0 else "DEBIT"
                elif bank_format == "MANDIRI":
                    txn_date = datetime.strptime(row[0].strip(), "%d/%m/%Y").date()
                    description = row[1].strip()
                    nominal = Decimal(row[2].replace(",", ""))
                    dbcr = row[3].strip().upper()
                    amount = nominal if dbcr == "CR" else -nominal
                    tx_type = "CREDIT" if dbcr == "CR" else "DEBIT"
                else:
                    txn_date = datetime.strptime(row[0].strip(), "%Y-%m-%d").date()
                    description = row[1].strip()
                    amount = Decimal(row[2].replace(",", ""))
                    tx_type = "CREDIT" if amount > 0 else "DEBIT"
                    amount = abs(amount)
                unique_id = hashlib.sha256(f"{txn_date}{amount}{description}{tx_type}".encode()).hexdigest()
                transactions.append(
                    StatementTransaction(
                        id=uuid4(),
                        transaction_date=txn_date,
                        amount=abs(amount),
                        currency="IDR",
                        description=description[:200],
                        reference_number=f"ROW{len(transactions) + 1}",
                        counterparty_name=None,
                        counterparty_account=None,
                        transaction_type=tx_type,
                        statement_balance=None,
                        unique_id=unique_id,
                        original_data={"row": row},
                    )
                )
            except Exception as e:
                logger.warning(f"CSV parse error: {e}")
        return transactions

    async def parse_and_import(
        self,
        file_content: str,
        file_name: str,
        bank_account_id: UUID,
        user_id: UUID,
        statement_date: date | None = None,
        override_format: StatementFormat | None = None,
    ) -> BankStatementImport:
        fmt = override_format if override_format else await self._detect_format(file_content, file_name)
        if fmt == StatementFormat.MT940:
            transactions = await self.parse_mt940(file_content)
        elif fmt in (StatementFormat.CAMT_053, StatementFormat.CAMT_054):
            transactions = await self.parse_camt(file_content)
        else:
            bank_code = fmt.value.replace("csv_", "").upper()
            transactions = await self.parse_csv(file_content, bank_code)

        import_id = uuid4()
        file_hash = await self._compute_file_hash(file_content)
        stmt_date = statement_date or date.today()
        import_record = BankStatementImport(
            id=import_id,
            bank_account_id=bank_account_id,
            file_name=file_name,
            file_hash=file_hash,
            statement_date=stmt_date,
            statement_balance=Decimal(0),
            statement_balance_date=stmt_date,
            format=fmt,
            status=ImportStatus.PROCESSING,
            total_transactions=len(transactions),
            imported_transactions=0,
            duplicate_transactions=0,
            failed_transactions=0,
            errors=[],
            created_at=datetime.now(UTC),
            created_by=user_id,
        )
        async with self._lock:
            self._imports[import_id] = import_record
            self._imported_transactions[import_id] = []

        imported_tx = []
        duplicate_count = 0
        for tx in transactions:
            is_duplicate = False
            for existing_import in self._imports.values():
                if existing_import.id != import_id:
                    existing_txs = self._imported_transactions.get(existing_import.id, [])
                    for extx in existing_txs:
                        if extx.unique_id == tx.unique_id:
                            is_duplicate = True
                            break
                if is_duplicate:
                    break
            if is_duplicate:
                duplicate_count += 1
                continue
            imported_tx.append(tx)

        self._imported_transactions[import_id] = imported_tx
        import_record.imported_transactions = len(imported_tx)
        import_record.duplicate_transactions = duplicate_count
        import_record.status = ImportStatus.SUCCESS
        import_record.completed_at = datetime.now(UTC)

        await self._log_audit(
            "IMPORT",
            import_id,
            user_id,
            {
                "format": fmt.value,
                "total": len(transactions),
                "imported": len(imported_tx),
                "duplicates": duplicate_count,
            },
        )
        return import_record

    async def get_import_status(self, import_id: UUID) -> BankStatementImport | None:
        return self._imports.get(import_id)

    async def get_imported_transactions(self, import_id: UUID) -> list[StatementTransaction]:
        return self._imported_transactions.get(import_id, [])

    async def get_all_imports(
        self, bank_account_id: UUID | None = None
    ) -> list[BankStatementImport]:
        imports = list(self._imports.values())
        if bank_account_id:
            imports = [imp for imp in imports if imp.bank_account_id == bank_account_id]
        return sorted(imports, key=lambda x: x.created_at, reverse=True)

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_imports": len(self._imports),
            "total_transactions_imported": sum(len(txs) for txs in self._imported_transactions.values()),
            "audit_log_size": len(self._audit_log),
        }


__all__ = [
    "BankStatementImport",
    "BankStatementImportPort",
    "ImportStatus",
    "InMemoryBankStatementImport",
    "StatementFormat",
    "StatementTransaction",
]
