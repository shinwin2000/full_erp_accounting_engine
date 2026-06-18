#!/usr/bin/env python3
"""
Module: litigation_case_linker.py
Layer: Compliance / Legal

Responsibility:
    Menghubungkan kasus litigasi dengan transaksi keuangan atau entitas terkait.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID


class LitigationCase:
    def __init__(
        self,
        case_id: UUID,
        case_number: str,
        court: str,
        plaintiff: str,
        defendant: str,
        filing_date: date,
        status: str,
        subject: str,
        amount_in_controversy: float | None = None,
    ):
        self.id = case_id
        self.case_number = case_number
        self.court = court
        self.plaintiff = plaintiff
        self.defendant = defendant
        self.filing_date = filing_date
        self.status = status
        self.subject = subject
        self.amount = amount_in_controversy
        self.linked_transactions: list[UUID] = []


class LitigationCaseLinker:
    def __init__(self):
        self._cases: dict[UUID, LitigationCase] = {}

    def add_case(self, case: LitigationCase) -> UUID:
        self._cases[case.id] = case
        return case.id

    def link_transaction(self, case_id: UUID, transaction_id: UUID) -> bool:
        case = self._cases.get(case_id)
        if case:
            if transaction_id not in case.linked_transactions:
                case.linked_transactions.append(transaction_id)
            return True
        return False

    def get_cases_for_transaction(self, transaction_id: UUID) -> list[LitigationCase]:
        return [c for c in self._cases.values() if transaction_id in c.linked_transactions]

    def get_case(self, case_id: UUID) -> LitigationCase | None:
        return self._cases.get(case_id)
