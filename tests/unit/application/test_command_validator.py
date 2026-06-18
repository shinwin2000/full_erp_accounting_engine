#!/usr/bin/env python3
"""
Unit: Command Validator
Menguji aturan validasi untuk berbagai command (journal, payment, dll).
Menggunakan validator sederhana yang sinkron (tidak async) agar kompatibel dengan test.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


# ============================================================================
# Simple synchronous CommandValidator (untuk keperluan test)
# ============================================================================
class SimpleCommandValidator:
    def __init__(self):
        self._rules: dict[type, list[Callable[[Any], bool]]] = {}

        def add_rule(self, command_type: type, rule: Callable[[Any], bool]) -> None:
            if command_type not in self._rules:
                self._rules[command_type] = []
                self._rules[command_type].append(rule)

                def validate(self, command: Any) -> bool:
                    rules = self._rules.get(type(command), [])
                    for rule in rules:
                        if not rule(command):
                            return False
                            return True

                            # ============================================================================
                            # DTO sederhana untuk test (karena DTO asli mungkin punya validasi sendiri)
                            # ============================================================================
                            class JournalLine:
                                def __init__(
                                    self,
                                    account: str,
                                    debit: Decimal,
                                    credit: Decimal,
                                    amount: Decimal | None = None,
                                ):
                                    self.account = account
                                    self.debit = debit
                                    self.credit = credit
                                    self.amount = amount if amount is not None else debit + credit

                                    class JournalRequest:
                                        def __init__(self, description: str, lines: list[dict]):
                                            self.description = description
                                            self.lines = [JournalLine(**line) for line in lines]

                                            class ApInvoiceRequest:
                                                def __init__(
                                                    self, supplier_id: str, amount: Decimal
                                                ):
                                                    self.supplier_id = supplier_id
                                                    self.amount = amount

                                                    # ============================================================================
                                                    # Fixtures
                                                    # ============================================================================
                                                    @pytest.fixture
                                                    def validator():
                                                        return SimpleCommandValidator()

                                                        # ============================================================================
                                                        # Tests
                                                        # ============================================================================
                                                        def test_journal_command_validation_passes(
                                                            validator,
                                                        ):
                                                            def balance_rule(
                                                                cmd: JournalRequest,
                                                            ) -> bool:
                                                                total_debit = sum(
                                                                    line.debit for line in cmd.lines
                                                                )
                                                                total_credit = sum(
                                                                    line.credit
                                                                    for line in cmd.lines
                                                                )
                                                                return total_debit == total_credit

                                                                validator.add_rule(
                                                                    JournalRequest, balance_rule
                                                                )
                                                                journal = JournalRequest(
                                                                    description="Test",
                                                                    lines=[
                                                                        {
                                                                            "account": "101",
                                                                            "debit": Decimal(
                                                                                "1000000"
                                                                            ),
                                                                            "credit": Decimal("0"),
                                                                        },
                                                                        {
                                                                            "account": "201",
                                                                            "debit": Decimal("0"),
                                                                            "credit": Decimal(
                                                                                "1000000"
                                                                            ),
                                                                        },
                                                                    ],
                                                                )
                                                                assert (
                                                                    validator.validate(journal)
                                                                    is True
                                                                )

                                                                def test_journal_command_validation_fails_imbalance(
                                                                    validator,
                                                                ):
                                                                    def balance_rule(
                                                                        cmd: JournalRequest,
                                                                    ) -> bool:
                                                                        total_debit = sum(
                                                                            line.debit
                                                                            for line in cmd.lines
                                                                        )
                                                                        total_credit = sum(
                                                                            line.credit
                                                                            for line in cmd.lines
                                                                        )
                                                                        return (
                                                                            total_debit
                                                                            == total_credit
                                                                        )

                                                                        validator.add_rule(
                                                                            JournalRequest,
                                                                            balance_rule,
                                                                        )
                                                                        journal = JournalRequest(
                                                                            description="Unbalanced",
                                                                            lines=[
                                                                                {
                                                                                    "account": "101",
                                                                                    "debit": Decimal(
                                                                                        "1000000"
                                                                                    ),
                                                                                    "credit": Decimal(
                                                                                        "0"
                                                                                    ),
                                                                                },
                                                                            ],
                                                                        )
                                                                        assert (
                                                                            validator.validate(
                                                                                journal
                                                                            )
                                                                            is False
                                                                        )

                                                                        def test_ap_invoice_validation(
                                                                            validator,
                                                                        ):
                                                                            def positive_amount(
                                                                                cmd: ApInvoiceRequest,
                                                                            ) -> bool:
                                                                                return (
                                                                                    cmd.amount > 0
                                                                                )

                                                                                validator.add_rule(
                                                                                    ApInvoiceRequest,
                                                                                    positive_amount,
                                                                                )
                                                                                valid = ApInvoiceRequest(
                                                                                    supplier_id="SUP-001",
                                                                                    amount=Decimal(
                                                                                        "5000000"
                                                                                    ),
                                                                                )
                                                                                assert (
                                                                                    validator.validate(
                                                                                        valid
                                                                                    )
                                                                                    is True
                                                                                )

                                                                                invalid = ApInvoiceRequest(
                                                                                    supplier_id="SUP-001",
                                                                                    amount=Decimal(
                                                                                        "-1000"
                                                                                    ),
                                                                                )
                                                                                assert (
                                                                                    validator.validate(
                                                                                        invalid
                                                                                    )
                                                                                    is False
                                                                                )

                                                                                def test_multiple_rules(
                                                                                    validator,
                                                                                ):
                                                                                    validator.add_rule(
                                                                                        JournalRequest,
                                                                                        lambda cmd: len(
                                                                                            cmd.lines
                                                                                        )
                                                                                        >= 2,
                                                                                    )
                                                                                    validator.add_rule(
                                                                                        JournalRequest,
                                                                                        lambda cmd: all(
                                                                                            line.debit
                                                                                            >= 0
                                                                                            and line.credit
                                                                                            >= 0
                                                                                            for line in cmd.lines
                                                                                        ),
                                                                                    )
                                                                                    journal = JournalRequest(
                                                                                        description="Test",
                                                                                        lines=[
                                                                                            {
                                                                                                "account": "101",
                                                                                                "debit": Decimal(
                                                                                                    "1000"
                                                                                                ),
                                                                                                "credit": Decimal(
                                                                                                    "0"
                                                                                                ),
                                                                                            },
                                                                                            {
                                                                                                "account": "201",
                                                                                                "debit": Decimal(
                                                                                                    "0"
                                                                                                ),
                                                                                                "credit": Decimal(
                                                                                                    "1000"
                                                                                                ),
                                                                                            },
                                                                                        ],
                                                                                    )
                                                                                    assert (
                                                                                        validator.validate(
                                                                                            journal
                                                                                        )
                                                                                        is True
                                                                                    )
