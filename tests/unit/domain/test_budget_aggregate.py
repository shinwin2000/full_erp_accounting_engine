#!/usr/bin/env python3
"""
Module: test_budget_aggregate.py
Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Budget aggregate root.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.budget.aggregate_root import Budget, BudgetAggregate, BudgetLine, BudgetStatus


class TestBudgetAggregate:
    @pytest.fixture
    def budget_lines(self):
        return [
            BudgetLine(
                account_id=uuid4(),
                account_code="701",
                amount=Decimal("1000000000"),
                period="2025-01",
            ),
            BudgetLine(
                account_id=uuid4(),
                account_code="701",
                amount=Decimal("1200000000"),
                period="2025-02",
            ),
        ]

    @pytest.fixture
    def budget(self, budget_lines):
        return Budget(
            id=uuid4(),
            legal_entity_id=uuid4(),
            name="Budget 2025",
            year=2025,
            status=BudgetStatus.DRAFT,
            lines=budget_lines,
            created_by=uuid4(),
            created_at=date.today(),
        )

    def test_create_budget(self, budget):
        agg = BudgetAggregate.create(budget, uuid4())
        assert agg.budget.id == budget.id
        assert agg.version == 1

    def test_approve_budget(self, budget):
        agg = BudgetAggregate.create(budget, uuid4())
        agg.approve(uuid4())
        assert agg.budget.status == BudgetStatus.APPROVED

    def test_record_actual(self, budget):
        agg = BudgetAggregate.create(budget, uuid4())
        agg.record_actual(account="701", period="2025-01", amount=Decimal("950000000"))
        assert agg.budget.lines[0].actual_amount == Decimal("950000000")
        assert agg.budget.lines[0].variance == Decimal("-50000000")  # unfavorable

    def test_variance_percentage(self, budget):
        agg = BudgetAggregate.create(budget, uuid4())
        agg.record_actual("701", "2025-01", Decimal("1100000000"))
        variance_pct = (
            (agg.budget.lines[0].actual_amount - agg.budget.lines[0].amount)
            / agg.budget.lines[0].amount
            * 100
        )
        assert variance_pct == Decimal("10")
