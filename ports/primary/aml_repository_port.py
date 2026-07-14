#!/usr/bin/env python3
"""
Module: aml_repository_port.py
Layer: Ports / Primary
Responsibility:
    - Mendefinisikan antarmuka (port) untuk repository AML.
    - Menyediakan implementasi in-memory untuk testing/fallback.

Defines the contract for:
- Storing and retrieving AML screening results
- Transaction monitoring records
- Sanctions list checks
- Suspicious transaction reports (STR)
- Customer risk scoring
"""

from __future__ import annotations

import abc
import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

# ==================== DOMAIN ENTITIES ====================

class AMLTransactionRecord:
    """Represents a transaction screened for AML."""

    def __init__(
        self,
        id: UUID,
        legal_entity_id: UUID,
        transaction_id: UUID,
        transaction_type: str,
        amount: Decimal,
        currency: str,
        counterparty_name: str,
        counterparty_country: str,
        transaction_date: date,
        screening_result: str,  # PASS, FLAG, BLOCK
        risk_score: Decimal,
        flags: list[str],
        screened_at: datetime,
        screened_by: UUID | None = None,
    ):
        self.id = id
        self.legal_entity_id = legal_entity_id
        self.transaction_id = transaction_id
        self.transaction_type = transaction_type
        self.amount = amount
        self.currency = currency
        self.counterparty_name = counterparty_name
        self.counterparty_country = counterparty_country
        self.transaction_date = transaction_date
        self.screening_result = screening_result
        self.risk_score = risk_score
        self.flags = flags
        self.screened_at = screened_at
        self.screened_by = screened_by


class AMLSanctionsHit:
    """Represents a sanctions list hit."""

    def __init__(
        self,
        id: UUID,
        transaction_id: UUID,
        sanctions_list_name: str,
        matched_name: str,
        match_score: Decimal,
        hit_date: datetime,
    ):
        self.id = id
        self.transaction_id = transaction_id
        self.sanctions_list_name = sanctions_list_name
        self.matched_name = matched_name
        self.match_score = match_score
        self.hit_date = hit_date


class SuspiciousTransactionReport:
    """Represents a suspicious transaction report (STR) to authorities."""

    def __init__(
        self,
        id: UUID,
        legal_entity_id: UUID,
        transaction_id: UUID,
        report_number: str,
        reason: str,
        risk_level: str,
        filed_at: datetime,
        filed_by: UUID,
        status: str = "SUBMITTED",
    ):
        self.id = id
        self.legal_entity_id = legal_entity_id
        self.transaction_id = transaction_id
        self.report_number = report_number
        self.reason = reason
        self.risk_level = risk_level
        self.filed_at = filed_at
        self.filed_by = filed_by
        self.status = status


class AMLRiskScore:
    """Customer risk score."""

    def __init__(
        self,
        id: UUID,
        legal_entity_id: UUID,
        customer_id: UUID,
        risk_score: Decimal,
        risk_category: str,  # LOW, MEDIUM, HIGH, VERY_HIGH
        calculated_at: datetime,
        expiration_date: date,
        factors: dict[str, Any],
    ):
        self.id = id
        self.legal_entity_id = legal_entity_id
        self.customer_id = customer_id
        self.risk_score = risk_score
        self.risk_category = risk_category
        self.calculated_at = calculated_at
        self.expiration_date = expiration_date
        self.factors = factors


# ==================== PORT (INTERFACE) ====================

class AMLRepositoryPort(abc.ABC):
    """Port for AML data persistence."""

    # --------------------------------------------------------------------
    # Transaction Screening
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_screening_result(self, record: AMLTransactionRecord) -> None:
        """Save an AML screening result for a transaction."""
        ...

    @abc.abstractmethod
    async def get_screening_result(self, transaction_id: UUID) -> AMLTransactionRecord | None:
        """Get screening result by transaction ID."""
        ...

    @abc.abstractmethod
    async def list_screened_transactions(
        self, legal_entity_id: UUID, from_date: date, to_date: date, result: str | None = None
    ) -> list[AMLTransactionRecord]:
        """List screened transactions within a date range, optionally filtered by result."""
        ...

    # --------------------------------------------------------------------
    # Sanctions Lists
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_sanctions_hit(self, hit: AMLSanctionsHit) -> None:
        """Save a sanctions list hit."""
        ...

    @abc.abstractmethod
    async def get_sanctions_hits_for_transaction(
        self, transaction_id: UUID
    ) -> list[AMLSanctionsHit]:
        """Get all sanctions hits for a transaction."""
        ...

    # --------------------------------------------------------------------
    # Suspicious Transaction Reports (STR)
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_str(self, report: SuspiciousTransactionReport) -> None:
        """Save a suspicious transaction report."""
        ...

    @abc.abstractmethod
    async def get_str_by_number(self, report_number: str) -> SuspiciousTransactionReport | None:
        """Get STR by report number."""
        ...

    @abc.abstractmethod
    async def list_strs_by_entity(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[SuspiciousTransactionReport]:
        """List STRs for a legal entity within a date range."""
        ...

    # --------------------------------------------------------------------
    # Customer Risk Scoring
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_risk_score(self, risk_score: AMLRiskScore) -> None:
        """Save a customer risk score."""
        ...

    @abc.abstractmethod
    async def get_current_risk_score(self, customer_id: UUID) -> AMLRiskScore | None:
        """Get the current (most recent non-expired) risk score for a customer."""
        ...

    @abc.abstractmethod
    async def list_high_risk_customers(self, legal_entity_id: UUID) -> list[AMLRiskScore]:
        """List customers with HIGH or VERY_HIGH risk scores."""
        ...

    # --------------------------------------------------------------------
    # Watchlist Management
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def add_to_watchlist(self, entity_name: str, reason: str, added_by: UUID) -> None:
        """Add an entity to the internal watchlist."""
        ...

    @abc.abstractmethod
    async def is_on_watchlist(self, entity_name: str) -> bool:
        """Check if an entity is on the internal watchlist."""
        ...


class AMLRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""
    async def save_screening_result(self, record: AMLTransactionRecord) -> None: ...
    async def get_screening_result(self, transaction_id: UUID) -> AMLTransactionRecord | None: ...
    async def list_screened_transactions(
        self, legal_entity_id: UUID, from_date: date, to_date: date, result: str | None = None
    ) -> list[AMLTransactionRecord]: ...
    async def save_sanctions_hit(self, hit: AMLSanctionsHit) -> None: ...
    async def get_sanctions_hits_for_transaction(
        self, transaction_id: UUID
    ) -> list[AMLSanctionsHit]: ...
    async def save_str(self, report: SuspiciousTransactionReport) -> None: ...
    async def get_str_by_number(self, report_number: str) -> SuspiciousTransactionReport | None: ...
    async def list_strs_by_entity(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[SuspiciousTransactionReport]: ...
    async def save_risk_score(self, risk_score: AMLRiskScore) -> None: ...
    async def get_current_risk_score(self, customer_id: UUID) -> AMLRiskScore | None: ...
    async def list_high_risk_customers(self, legal_entity_id: UUID) -> list[AMLRiskScore]: ...
    async def add_to_watchlist(self, entity_name: str, reason: str, added_by: UUID) -> None: ...
    async def is_on_watchlist(self, entity_name: str) -> bool: ...


# ==================== IMPLEMENTASI IN-MEMORY (FALLBACK/TESTING) ====================

class InMemoryAMLRepository(AMLRepositoryPort):
    """
    Implementasi in-memory untuk repository AML.
    Kelas ini TIDAK akan didaftarkan oleh container karena mengandung kata "InMemory".
    """

    def __init__(self):
        self._screening_records: dict[UUID, AMLTransactionRecord] = {}
        self._sanctions_hits: list[AMLSanctionsHit] = []
        self._strs: dict[str, SuspiciousTransactionReport] = {}
        self._risk_scores: list[AMLRiskScore] = []
        self._watchlist: set[str] = set()
        self._lock = asyncio.Lock()

    # --------------------------------------------------------------------
    # Transaction Screening
    # --------------------------------------------------------------------
    async def save_screening_result(self, record: AMLTransactionRecord) -> None:
        async with self._lock:
            self._screening_records[record.transaction_id] = record

    async def get_screening_result(self, transaction_id: UUID) -> AMLTransactionRecord | None:
        async with self._lock:
            return self._screening_records.get(transaction_id)

    async def list_screened_transactions(
        self, legal_entity_id: UUID, from_date: date, to_date: date, result: str | None = None
    ) -> list[AMLTransactionRecord]:
        async with self._lock:
            result_list = []
            for record in self._screening_records.values():
                if record.legal_entity_id != legal_entity_id:
                    continue
                if not (from_date <= record.transaction_date <= to_date):
                    continue
                if result and record.screening_result != result:
                    continue
                result_list.append(record)
            return result_list

    # --------------------------------------------------------------------
    # Sanctions Lists
    # --------------------------------------------------------------------
    async def save_sanctions_hit(self, hit: AMLSanctionsHit) -> None:
        async with self._lock:
            self._sanctions_hits.append(hit)

    async def get_sanctions_hits_for_transaction(
        self, transaction_id: UUID
    ) -> list[AMLSanctionsHit]:
        async with self._lock:
            return [h for h in self._sanctions_hits if h.transaction_id == transaction_id]

    # --------------------------------------------------------------------
    # Suspicious Transaction Reports (STR)
    # --------------------------------------------------------------------
    async def save_str(self, report: SuspiciousTransactionReport) -> None:
        async with self._lock:
            self._strs[report.report_number] = report

    async def get_str_by_number(self, report_number: str) -> SuspiciousTransactionReport | None:
        async with self._lock:
            return self._strs.get(report_number)

    async def list_strs_by_entity(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[SuspiciousTransactionReport]:
        async with self._lock:
            result = []
            for report in self._strs.values():
                if report.legal_entity_id != legal_entity_id:
                    continue
                if not (from_date <= report.filed_at.date() <= to_date):
                    continue
                result.append(report)
            return result

    # --------------------------------------------------------------------
    # Customer Risk Scoring
    # --------------------------------------------------------------------
    async def save_risk_score(self, risk_score: AMLRiskScore) -> None:
        async with self._lock:
            self._risk_scores.append(risk_score)

    async def get_current_risk_score(self, customer_id: UUID) -> AMLRiskScore | None:
        async with self._lock:
            scores = [s for s in self._risk_scores if s.customer_id == customer_id]
            if not scores:
                return None
            now = datetime.now().date()
            valid = [s for s in scores if s.expiration_date >= now]
            if not valid:
                return None
            valid.sort(key=lambda x: x.calculated_at, reverse=True)
            return valid[0]

    async def list_high_risk_customers(self, legal_entity_id: UUID) -> list[AMLRiskScore]:
        async with self._lock:
            result = []
            now = datetime.now().date()
            for score in self._risk_scores:
                if score.legal_entity_id != legal_entity_id:
                    continue
                if score.expiration_date < now:
                    continue
                if score.risk_category in ("HIGH", "VERY_HIGH"):
                    result.append(score)
            return result

    # --------------------------------------------------------------------
    # Watchlist Management
    # --------------------------------------------------------------------
    async def add_to_watchlist(self, entity_name: str, reason: str, added_by: UUID) -> None:
        async with self._lock:
            self._watchlist.add(entity_name.lower())

    async def is_on_watchlist(self, entity_name: str) -> bool:
        async with self._lock:
            return entity_name.lower() in self._watchlist


# ==================== EXPORTS ====================

__all__ = [
    "AMLRepositoryPort",
    "AMLRepositoryPortProtocol",
    "AMLRiskScore",
    "AMLSanctionsHit",
    "AMLTransactionRecord",
    "InMemoryAMLRepository",
    "SuspiciousTransactionReport",
]
