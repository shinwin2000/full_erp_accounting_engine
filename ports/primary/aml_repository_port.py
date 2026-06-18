#!/usr/bin/env python3
"""
Module: aml_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port for AML (Anti-Money Laundering) repository operations.

Defines the contract for:
- Storing and retrieving AML screening results
- Transaction monitoring records
- Sanctions list checks
- Suspicious transaction reports (STR)
- Customer risk scoring
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID


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


class AMLRepositoryPort(abc.ABC):
    """Port for AML data persistence."""

    # --------------------------------------------------------------------
    # Transaction Screening
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_screening_result(self, record: AMLTransactionRecord) -> None:
        """Save an AML screening result for a transaction."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_screening_result(self, transaction_id: UUID) -> AMLTransactionRecord | None:
        """Get screening result by transaction ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_screened_transactions(
        self, legal_entity_id: UUID, from_date: date, to_date: date, result: str | None = None
    ) -> list[AMLTransactionRecord]:
        """List screened transactions within a date range, optionally filtered by result."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Sanctions Lists
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_sanctions_hit(self, hit: AMLSanctionsHit) -> None:
        """Save a sanctions list hit."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_sanctions_hits_for_transaction(
        self, transaction_id: UUID
    ) -> list[AMLSanctionsHit]:
        """Get all sanctions hits for a transaction."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Suspicious Transaction Reports (STR)
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_str(self, report: SuspiciousTransactionReport) -> None:
        """Save a suspicious transaction report."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_str_by_number(self, report_number: str) -> SuspiciousTransactionReport | None:
        """Get STR by report number."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_strs_by_entity(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[SuspiciousTransactionReport]:
        """List STRs for a legal entity within a date range."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Customer Risk Scoring
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_risk_score(self, risk_score: AMLRiskScore) -> None:
        """Save a customer risk score."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_current_risk_score(self, customer_id: UUID) -> AMLRiskScore | None:
        """Get the current (most recent non-expired) risk score for a customer."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_high_risk_customers(self, legal_entity_id: UUID) -> list[AMLRiskScore]:
        """List customers with HIGH or VERY_HIGH risk scores."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Watchlist Management
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def add_to_watchlist(self, entity_name: str, reason: str, added_by: UUID) -> None:
        """Add an entity to the internal watchlist."""
        raise NotImplementedError

    @abc.abstractmethod
    async def is_on_watchlist(self, entity_name: str) -> bool:
        """Check if an entity is on the internal watchlist."""
        raise NotImplementedError


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


__all__ = [
    "AMLRepositoryPort",
    "AMLRepositoryPortProtocol",
    "AMLRiskScore",
    "AMLSanctionsHit",
    "AMLTransactionRecord",
    "SuspiciousTransactionReport",
]
