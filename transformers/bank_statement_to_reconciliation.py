#!/usr/bin/env python3
"""
Module: bank_statement_to_reconciliation.py
Layer: Transformers
Responsibility: Mentransformasi event dari bank statement import atau webhook
               bank menjadi command untuk melakukan bank reconciliation.

Metode yang ditambahkan:
- BaseTransformer dengan entity dasar: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk StatementParser, BankTransactionMatcher, BankStatementToReconciliationTransformer.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
from application.service_layer.service_bank_cash import BankCashService
from application.use_cases.bank_reconciliation import BankReconciliationUseCase
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.bank_cash_repository_port import BankCashRepositoryPort

if TYPE_CHECKING:
    from event_gateway.event_gate_singleton import EventEnvelope

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================
DEFAULT_CURRENCY = "IDR"
AMOUNT_TOLERANCE = Decimal("1000")
MATCH_LOOKBACK_DAYS = 30
MATCH_FUZZY_REFERENCE = True

HANDLED_EVENT_TYPES = [
    "BankStatementUploaded",
    "BankStatementParsed",
    "MT940Parsed",
    "CAMTParsed",
    "CSVBatchParsed",
    "BankWebhookReceived",
    "DailyBankReconciliationTrigger",
]

FORMAT_MT940 = "mt940"
FORMAT_CAMT = "camt"
FORMAT_CSV_BCA = "csv_bca"
FORMAT_CSV_MANDIRI = "csv_mandiri"
FORMAT_CSV_BNI = "csv_bni"
FORMAT_CSV_BRI = "csv_bri"
FORMAT_JSON_WEBHOOK = "json_webhook"


# ============================================================================
# BaseTransformer
# ============================================================================
class BaseTransformer:
    def __init__(self, name: str):
        self.name = name
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._transformer_id = str(uuid4())

    def _take_snapshot(self):
        import datetime
        self._snapshots.append(
            {
                "version": self._version,
                "transformer_id": self._transformer_id,
                "name": self.name,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        import datetime
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "version": self._version,
                "transformer_id": self._transformer_id,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"transformer_id": self._transformer_id, "name": self.name, "version": self._version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseTransformer:
        instance = cls(data["name"])
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> BaseTransformer:
        new = self.__class__(self.name)
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        import datetime
        return {
            "version": self._version,
            "transformer_id": self._transformer_id,
            "name": self.name,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BaseTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# EXCEPTIONS
# ============================================================================
class BankStatementToReconciliationError(Exception):
    pass


class BankAccountNotFoundError(BankStatementToReconciliationError):
    pass


class StatementParsingError(BankStatementToReconciliationError):
    pass


class ReconciliationFailedError(BankStatementToReconciliationError):
    pass


# ============================================================================
# StatementParser (dengan entity dasar)
# ============================================================================
class StatementParser(BaseTransformer):
    def __init__(self):
        super().__init__("StatementParser")
        self._parsers = {
            FORMAT_MT940: self._parse_mt940,
            FORMAT_CAMT: self._parse_camt,
            FORMAT_CSV_BCA: self._parse_csv_bca,
            FORMAT_CSV_MANDIRI: self._parse_csv_mandiri,
            FORMAT_CSV_BNI: self._parse_csv_bni,
            FORMAT_CSV_BRI: self._parse_csv_bri,
        }

    async def parse(
        self, content: str, format_type: str, bank_account_number: str
    ) -> list[dict[str, Any]]:
        parser = self._parsers.get(format_type)
        if not parser:
            raise StatementParsingError(f"Unsupported format: {format_type}")
        try:
            transactions = await parser(content, bank_account_number)
            logger.info(f"Parsed {len(transactions)} transactions from {format_type} statement")
            return transactions
        except Exception as e:
            raise StatementParsingError(f"Failed to parse {format_type} statement: {e}") from e

    async def _parse_mt940(self, content: str, bank_account_number: str) -> list[dict[str, Any]]:
        transactions = []
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith(":61:"):
                parts = line[4:].split("N")
                date_part = parts[0][:12]
                ref_part = parts[1] if len(parts) > 1 else ""
                trans_date_str = date_part[:6]
                try:
                    trans_date = datetime.strptime(trans_date_str, "%y%m%d").date()
                except ValueError:
                    trans_date = datetime.now().date()
                amount_part = date_part[12:]
                if amount_part.startswith("D"):
                    amount = -Decimal(amount_part[1:].replace(",", "."))
                    trans_type = "withdrawal"
                elif amount_part.startswith("C"):
                    amount = Decimal(amount_part[1:].replace(",", "."))
                    trans_type = "deposit"
                else:
                    amount = Decimal(amount_part.replace(",", "."))
                    trans_type = "deposit"
                transactions.append(
                    {
                        "transaction_date": trans_date,
                        "amount": abs(amount),
                        "type": trans_type,
                        "reference": ref_part[:50],
                        "description": f"MT940 transaction - {ref_part[:50]}",
                    }
                )
            elif line.startswith(":86:"):
                if transactions:
                    transactions[-1]["description"] = line[4:].strip()[:200]
        return transactions

    async def _parse_camt(self, content: str, bank_account_number: str) -> list[dict[str, Any]]:
        import re
        transactions = []
        pattern = r"<TxDtls>.*?<Amt>([^<]+)</Amt>.*?<BookgDt>([^<]+)</BookgDt>.*?</TxDtls>"
        matches = re.findall(pattern, content, re.DOTALL)
        for match in matches:
            amount_str, date_str = match
            amount = Decimal(amount_str.replace(",", "."))
            try:
                trans_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                trans_date = datetime.now().date()
            transactions.append(
                {
                    "transaction_date": trans_date,
                    "amount": abs(amount),
                    "type": "deposit" if amount > 0 else "withdrawal",
                    "reference": "",
                    "description": "CAMT transaction",
                }
            )
        return transactions

    async def _parse_csv_bca(self, content: str, bank_account_number: str) -> list[dict[str, Any]]:
        import csv
        from io import StringIO
        transactions = []
        reader = csv.DictReader(StringIO(content))
        for row in reader:
            try:
                date_str = row.get("Date", "").strip()
                trans_date = (
                    datetime.strptime(date_str, "%d/%m/%Y").date()
                    if date_str
                    else datetime.now().date()
                )
                amount_str = row.get("Amount", "0").replace(",", "").strip()
                amount = Decimal(amount_str) if amount_str else Decimal(0)
                trans_type = "withdrawal" if amount < 0 else "deposit"
                description = row.get("Description", "")[:200]
                transactions.append(
                    {
                        "transaction_date": trans_date,
                        "amount": abs(amount),
                        "type": trans_type,
                        "reference": row.get("Reference", "")[:50],
                        "description": description,
                    }
                )
            except Exception:
                continue
        return transactions

    async def _parse_csv_mandiri(
        self, content: str, bank_account_number: str
    ) -> list[dict[str, Any]]:
        import csv
        from io import StringIO
        transactions = []
        reader = csv.reader(StringIO(content))
        for row in reader:
            if len(row) < 4:
                continue
            try:
                date_str = row[0].strip()
                trans_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                description = row[1] if len(row) > 1 else ""
                debit_str = row[2].replace(",", "").strip() if len(row) > 2 else "0"
                credit_str = row[3].replace(",", "").strip() if len(row) > 3 else "0"
                if debit_str and debit_str != "0":
                    amount = Decimal(debit_str)
                    trans_type = "withdrawal"
                elif credit_str and credit_str != "0":
                    amount = Decimal(credit_str)
                    trans_type = "deposit"
                else:
                    continue
                transactions.append(
                    {
                        "transaction_date": trans_date,
                        "amount": abs(amount),
                        "type": trans_type,
                        "reference": row[4] if len(row) > 4 else "",
                        "description": description[:200],
                    }
                )
            except Exception:
                continue
        return transactions

    async def _parse_csv_bni(self, content: str, bank_account_number: str) -> list[dict[str, Any]]:
        return await self._parse_csv_mandiri(content, bank_account_number)

    async def _parse_csv_bri(self, content: str, bank_account_number: str) -> list[dict[str, Any]]:
        return await self._parse_csv_mandiri(content, bank_account_number)

    def validate(self) -> dict[str, Any]:
        errors = []
        for fmt, parser in self._parsers.items():
            if not callable(parser):
                errors.append(f"Parser for {fmt} is not callable")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["supported_formats"] = list(self._parsers.keys())
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StatementParser:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> StatementParser:
        new = StatementParser()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["supported_formats"] = list(self._parsers.keys())
        return snap


# ============================================================================
# BankTransactionMatcher (dengan entity dasar)
# ============================================================================
class BankTransactionMatcher(BaseTransformer):
    def __init__(self, amount_tolerance: Decimal = AMOUNT_TOLERANCE):
        super().__init__("BankTransactionMatcher")
        self.amount_tolerance = amount_tolerance

    async def match_transactions(
        self, statement_transactions: list[dict], book_transactions: list[dict]
    ) -> tuple[list, list, list]:
        matched = []
        unmatched_statement = []
        available_book = list(book_transactions)
        for stmt_tx in statement_transactions:
            matched_book = None
            best_match_idx = -1
            best_score = 0
            for idx, book_tx in enumerate(available_book):
                score = await self._calculate_match_score(stmt_tx, book_tx)
                if score > 0.8 and score > best_score:
                    best_score = score
                    best_match_idx = idx
                    matched_book = book_tx
            if best_match_idx >= 0:
                matched.append(
                    {"statement": stmt_tx, "book": matched_book, "match_score": best_score}
                )
                available_book.pop(best_match_idx)
            else:
                unmatched_statement.append(stmt_tx)
        return matched, unmatched_statement, available_book

    async def _calculate_match_score(self, stmt_tx: dict, book_tx: dict) -> float:
        score = 0.0
        amount_diff = abs(stmt_tx["amount"] - book_tx["amount"])
        if amount_diff <= self.amount_tolerance:
            score += 0.4
        else:
            ratio = max(0, 1 - (amount_diff / book_tx["amount"]))
            score += 0.4 * float(ratio)
        date_diff = abs((stmt_tx["transaction_date"] - book_tx["transaction_date"]).days)
        if date_diff == 0:
            score += 0.3
        elif date_diff <= 3:
            score += 0.2
        elif date_diff <= 7:
            score += 0.1
        stmt_ref = stmt_tx.get("reference", "").lower()
        book_ref = book_tx.get("reference_number", "").lower()
        if stmt_ref and book_ref:
            if stmt_ref == book_ref:
                score += 0.2
            elif stmt_ref in book_ref or book_ref in stmt_ref:
                score += 0.15
            elif stmt_ref[:8] == book_ref[:8]:
                score += 0.1
        stmt_desc = stmt_tx.get("description", "").lower()
        book_desc = book_tx.get("description", "").lower()
        if stmt_desc and book_desc:
            stmt_words = set(re.findall(r"\w+", stmt_desc))
            book_words = set(re.findall(r"\w+", book_desc))
            if stmt_words and book_words:
                overlap = len(stmt_words & book_words)
                total = len(stmt_words | book_words)
                if total > 0:
                    score += 0.1 * (overlap / total)
        return score

    def validate(self) -> dict[str, Any]:
        errors = []
        if self.amount_tolerance <= 0:
            errors.append("amount_tolerance must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["amount_tolerance"] = str(self.amount_tolerance)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BankTransactionMatcher:
        instance = cls(amount_tolerance=Decimal(data.get("amount_tolerance", "1000")))
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        return instance

    def clone(self) -> BankTransactionMatcher:
        new = BankTransactionMatcher(self.amount_tolerance)
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["amount_tolerance"] = str(self.amount_tolerance)
        return snap


# ============================================================================
# BankStatementToReconciliationTransformer (dengan entity dasar)
# ============================================================================
class BankStatementToReconciliationTransformer(BaseTransformer):
    def __init__(
        self,
        command_bus: UnifiedCommandBus,
        bank_cash_service: BankCashService,
        reconciliation_use_case: BankReconciliationUseCase,
        bank_repo: BankCashRepositoryPort,
    ):
        super().__init__("BankStatementToReconciliationTransformer")
        self._command_bus = command_bus
        self._bank_cash_service = bank_cash_service
        self._reconciliation_use_case = reconciliation_use_case
        self._bank_repo = bank_repo
        self._parser = StatementParser()
        self._matcher = BankTransactionMatcher()
        self._processed_events: set = set()

    async def transform(self, envelope: EventEnvelope) -> None:
        event_type = envelope.event_type
        event_id = str(envelope.id)
        event_payload = envelope.payload

        if event_id in self._processed_events:
            logger.debug(f"Event {event_id} already processed, skipping")
            return
        if event_type not in HANDLED_EVENT_TYPES:
            logger.debug(f"Event type {event_type} not handled")
            return

        logger.info(f"Transforming event {event_type} to reconciliation command")
        try:
            if event_type in ("BankStatementUploaded", "BankStatementParsed"):
                await self._handle_statement_upload(event_payload, envelope)
            elif event_type in ("MT940Parsed", "CAMTParsed", "CSVBatchParsed"):
                await self._handle_parsed_statement(event_payload, envelope, event_type)
            elif event_type == "BankWebhookReceived":
                await self._handle_bank_webhook(event_payload, envelope)
            elif event_type == "DailyBankReconciliationTrigger":
                await self._handle_daily_reconciliation(event_payload, envelope)
            self._processed_events.add(event_id)
        except Exception as e:
            logger.exception(f"Failed to transform event {event_id}: {e}")
            await trigger_alert(
                title="Bank Statement Reconciliation Failed",
                message=f"Event: {event_type}, Error: {str(e)[:200]}",
                severity="error",
                source="BankStatementToReconciliationTransformer",
            )
            raise

    async def _handle_statement_upload(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        bank_account_id = UUID(payload.get("bank_account_id"))
        file_content = payload.get("file_content", "")
        file_format = payload.get("format", FORMAT_MT940)
        statement_date = self._parse_date(payload.get("statement_date")) or datetime.now().date()
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        bank_account = await self._bank_repo.get_bank_account_by_id(bank_account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {bank_account_id} not found")
        statement_transactions = await self._parser.parse(
            file_content, file_format, bank_account.account_number
        )
        if not statement_transactions:
            logger.warning(
                f"No transactions parsed from statement for {bank_account.account_number}"
            )
            return
        end_date = statement_date
        start_date = end_date - timedelta(days=MATCH_LOOKBACK_DAYS)
        book_transactions = await self._bank_repo.get_bank_transactions_by_account(
            bank_account_id, start_date, end_date, is_reconciled=False
        )
        book_tx_list = [
            {
                "id": tx.id,
                "amount": tx.amount.amount,
                "transaction_date": tx.transaction_date,
                "reference_number": tx.reference_number,
                "description": tx.description,
                "type": tx.transaction_type.value
                if hasattr(tx.transaction_type, "value")
                else str(tx.transaction_type),
            }
            for tx in book_transactions
        ]
        matched, unmatched_statement, unmatched_book = await self._matcher.match_transactions(
            statement_transactions, book_tx_list
        )
        ending_balance = bank_account.current_balance.amount
        await self._reconciliation_use_case.reconcile(
            legal_entity_id=legal_entity_id,
            bank_account_id=bank_account_id,
            statement_date=statement_date,
            ending_balance=ending_balance,
            statement_transactions=statement_transactions,
            reconciled_by=UUID(payload.get("uploaded_by")) if payload.get("uploaded_by") else None,
        )
        logger.info(
            f"Bank reconciliation completed for {bank_account.account_number}: matched={len(matched)}, unmatched_statement={len(unmatched_statement)}, unmatched_book={len(unmatched_book)}"
        )
        if len(unmatched_statement) > 10 or len(unmatched_book) > 10:
            await trigger_alert(
                title="High Number of Unmatched Bank Transactions",
                message=f"Bank {bank_account.account_number}: {len(unmatched_statement)} statement tx, {len(unmatched_book)} book tx unmatched",
                severity="warning",
                source="BankStatementToReconciliationTransformer",
            )

    async def _handle_parsed_statement(
        self, payload: dict[str, Any], envelope: EventEnvelope, event_type: str
    ) -> None:
        bank_account_id = UUID(payload.get("bank_account_id"))
        statement_transactions = payload.get("transactions", [])
        statement_date = self._parse_date(payload.get("statement_date")) or datetime.now().date()
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        if not statement_transactions:
            logger.warning(f"No transactions in parsed statement for {bank_account_id}")
            return
        bank_account = await self._bank_repo.get_bank_account_by_id(bank_account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {bank_account_id} not found")
        end_date = statement_date
        start_date = end_date - timedelta(days=MATCH_LOOKBACK_DAYS)
        book_transactions = await self._bank_repo.get_bank_transactions_by_account(
            bank_account_id, start_date, end_date, is_reconciled=False
        )
        book_tx_list = [
            {
                "id": tx.id,
                "amount": tx.amount.amount,
                "transaction_date": tx.transaction_date,
                "reference_number": tx.reference_number,
                "description": tx.description,
            }
            for tx in book_transactions
        ]
        _matched, _unmatched_statement, _unmatched_book = await self._matcher.match_transactions(
            statement_transactions, book_tx_list
        )
        await self._reconciliation_use_case.reconcile(
            legal_entity_id=legal_entity_id,
            bank_account_id=bank_account_id,
            statement_date=statement_date,
            ending_balance=bank_account.current_balance.amount,
            statement_transactions=statement_transactions,
            reconciled_by=UUID(payload.get("processed_by"))
            if payload.get("processed_by")
            else None,
        )
        logger.info("Parsed statement reconciliation completed")

    async def _handle_bank_webhook(self, payload: dict[str, Any], envelope: EventEnvelope) -> None:
        bank_account_number = payload.get("account_number")
        amount = Decimal(str(payload.get("amount", 0)))
        transaction_date = (
            self._parse_date(payload.get("transaction_date")) or datetime.now().date()
        )
        reference = payload.get("reference", "")
        description = payload.get("description", "")
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        bank_account = await self._bank_repo.get_bank_account_by_number(
            bank_account_number, legal_entity_id
        )
        if not bank_account:
            logger.warning(f"Bank account {bank_account_number} not found for webhook")
            return
        await self._command_bus.dispatch(
            {
                "type": "bank.transaction.record",
                "data": {
                    "bank_account_id": str(bank_account.id),
                    "transaction_date": transaction_date.isoformat(),
                    "amount": float(amount),
                    "description": description,
                    "reference_number": reference,
                    "status": "pending_reconciliation",
                    "legal_entity_id": str(legal_entity_id),
                },
            }
        )
        logger.info(f"Bank webhook transaction recorded: {reference} for {amount}")

    async def _handle_daily_reconciliation(
        self, payload: dict[str, Any], envelope: EventEnvelope
    ) -> None:
        as_of_date = self._parse_date(payload.get("as_of_date")) or datetime.now().date()
        legal_entity_id = (
            UUID(payload.get("legal_entity_id"))
            if payload.get("legal_entity_id")
            else envelope.metadata.get("legal_entity_id")
        )
        bank_accounts = await self._bank_repo.list_bank_accounts(legal_entity_id)
        results = []
        for account in bank_accounts:
            try:
                result = await self._reconciliation_use_case.reconcile_auto(
                    legal_entity_id=legal_entity_id,
                    bank_account_id=account.id,
                    as_of_date=as_of_date,
                )
                results.append(
                    {"account_number": account.account_number, "status": result.get("status")}
                )
            except Exception as e:
                logger.error(f"Daily reconciliation failed for {account.account_number}: {e}")
                results.append(
                    {"account_number": account.account_number, "status": "failed", "error": str(e)}
                )
        logger.info(f"Daily reconciliation completed for {len(results)} accounts")

    def _parse_date(self, date_value: Any) -> date | None:
        if date_value is None:
            return None
        if isinstance(date_value, date):
            return date_value
        if isinstance(date_value, str):
            try:
                return datetime.fromisoformat(date_value).date()
            except ValueError:
                try:
                    return datetime.strptime(date_value, "%Y-%m-%d").date()
                except ValueError:
                    return None
        return None

    async def reset(self) -> None:
        self._processed_events.clear()
        self._version += 1
        logger.info("BankStatementToReconciliationTransformer reset")

    def validate(self) -> dict[str, Any]:
        errors = []
        if self._parser is None:
            errors.append("Parser not initialized")
        if self._matcher is None:
            errors.append("Matcher not initialized")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["processed_events_count"] = len(self._processed_events)
        data["parser"] = self._parser.to_dict()
        data["matcher"] = self._matcher.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BankStatementToReconciliationTransformer:
        instance = cls.__new__(cls)
        instance._version = data.get("version", 1)
        instance._transformer_id = data.get("transformer_id", str(uuid4()))
        instance._command_bus = None
        instance._bank_cash_service = None
        instance._reconciliation_use_case = None
        instance._bank_repo = None
        instance._parser = StatementParser()
        instance._matcher = BankTransactionMatcher()
        instance._processed_events = set()
        return instance

    def clone(self) -> BankStatementToReconciliationTransformer:
        new = BankStatementToReconciliationTransformer(
            command_bus=self._command_bus,
            bank_cash_service=self._bank_cash_service,
            reconciliation_use_case=self._reconciliation_use_case,
            bank_repo=self._bank_repo,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._transformer_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["processed_events_count"] = len(self._processed_events)
        return snap

    def touch(self, touched_by: str) -> BankStatementToReconciliationTransformer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# TRANSFORMER FACTORY & EVENT HANDLER
# ============================================================================
_bank_statement_transformer: BankStatementToReconciliationTransformer | None = None


async def get_bank_statement_transformer() -> BankStatementToReconciliationTransformer:
    global _bank_statement_transformer
    if _bank_statement_transformer is None:
        from bootstrap.dependency_container.ioc_container import get_container

        container = get_container()
        command_bus = container.resolve(UnifiedCommandBus)
        bank_cash_service = container.resolve(BankCashService)
        reconciliation_use_case = container.resolve(BankReconciliationUseCase)
        bank_repo = container.resolve(BankCashRepositoryPort)
        _bank_statement_transformer = BankStatementToReconciliationTransformer(
            command_bus=command_bus,
            bank_cash_service=bank_cash_service,
            reconciliation_use_case=reconciliation_use_case,
            bank_repo=bank_repo,
        )
    return _bank_statement_transformer


async def handle_bank_statement_event(envelope: EventEnvelope) -> None:
    transformer = await get_bank_statement_transformer()
    await transformer.transform(envelope)


__all__ = [
    "BankAccountNotFoundError",
    "BankStatementToReconciliationError",
    "BankStatementToReconciliationTransformer",
    "ReconciliationFailedError",
    "StatementParsingError",
    "get_bank_statement_transformer",
    "handle_bank_statement_event",
]