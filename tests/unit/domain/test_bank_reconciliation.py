#!/usr/bin/env python3

"""
Module: test_bank_reconciliation.py

Unit tests untuk bank reconciliation engine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.bank_reconciliation_engine import (
    BankReconciliationEngine,
    ReconciliationStatus,
)
from domain.bank_cash.bank_transaction_entity import (
    BankTransaction,
    TransactionStatus,
    TransactionType,
)


def adapt_transaction(tx: BankTransaction):
    tx.transaction_id = tx.id
    if not hasattr(tx, "is_credit"):

        def is_credit(t):
            return t.transaction_type == TransactionType.DEPOSIT

            tx.is_credit = is_credit.__get__(tx)
            return tx

            class TestBankReconciliation:
                """Test suite untuk bank reconciliation."""

                @pytest.fixture
                def reconciliation_engine(self) -> BankReconciliationEngine:
                    return BankReconciliationEngine(
                        tolerance=Decimal("0.01"), date_tolerance_days=3
                    )

                    @pytest.fixture
                    def sample_system_transactions(self) -> list[BankTransaction]:
                        transactions = [
                            BankTransaction(
                                id=uuid4(),
                                legal_entity_id=uuid4(),
                                bank_account_id=uuid4(),
                                transaction_date=datetime(2025, 3, 1, tzinfo=UTC),
                                amount=Decimal("1000000"),
                                transaction_type=TransactionType.DEPOSIT,
                                description="Setoran tunai",
                                reference_number="REF001",
                                counterparty_name="Customer A",
                                counterparty_account=None,
                                status=TransactionStatus.COMPLETED,
                                is_reconciled=False,
                                created_by=uuid4(),
                                created_at=datetime.now(UTC),
                                reconciled_at=None,
                            ),
                            BankTransaction(
                                id=uuid4(),
                                legal_entity_id=uuid4(),
                                bank_account_id=uuid4(),
                                transaction_date=datetime(2025, 3, 2, tzinfo=UTC),
                                amount=Decimal("500000"),
                                transaction_type=TransactionType.WITHDRAWAL,
                                description="Tarik tunai",
                                reference_number="REF002",
                                counterparty_name=None,
                                counterparty_account=None,
                                status=TransactionStatus.COMPLETED,
                                is_reconciled=False,
                                created_by=uuid4(),
                                created_at=datetime.now(UTC),
                                reconciled_at=None,
                            ),
                            BankTransaction(
                                id=uuid4(),
                                legal_entity_id=uuid4(),
                                bank_account_id=uuid4(),
                                transaction_date=datetime(2025, 3, 5, tzinfo=UTC),
                                amount=Decimal("2000000"),
                                transaction_type=TransactionType.DEPOSIT,
                                description="Transfer masuk",
                                reference_number="REF003",
                                counterparty_name="Customer B",
                                counterparty_account=None,
                                status=TransactionStatus.COMPLETED,
                                is_reconciled=False,
                                created_by=uuid4(),
                                created_at=datetime.now(UTC),
                                reconciled_at=None,
                            ),
                        ]
                        return [adapt_transaction(tx) for tx in transactions]

                        @pytest.fixture
                        def sample_statement_transactions(self) -> list[dict]:
                            # Menggunakan amount bertanda: positif untuk deposit, negatif untuk withdrawal
                            return [
                                {
                                    "reference_number": "REF001",
                                    "amount": Decimal("1000000"),
                                    "date": datetime(2025, 3, 1, tzinfo=UTC),
                                    "description": "Setoran",
                                },
                                {
                                    "reference_number": "REF002",
                                    "amount": Decimal("-500000"),
                                    "date": datetime(2025, 3, 2, tzinfo=UTC),
                                    "description": "Tarik",
                                },
                                {
                                    "reference_number": "REF003",
                                    "amount": Decimal("2000000"),
                                    "date": datetime(2025, 3, 5, tzinfo=UTC),
                                    "description": "Transfer",
                                },
                            ]

                            def test_exact_match_all_transactions(
                                self,
                                reconciliation_engine,
                                sample_system_transactions,
                                sample_statement_transactions,
                            ):
                                account_id = uuid4()
                                # statement_balance = 1.000.000 - 500.000 + 2.000.000 = 2.500.000
                                result = reconciliation_engine.reconcile(
                                    account_id=account_id,
                                    book_transactions=sample_system_transactions,
                                    statement_balance=Decimal("2500000"),
                                    statement_date=datetime(2025, 3, 6, tzinfo=UTC),
                                    statement_transactions=sample_statement_transactions,
                                    reconciled_by="tester",
                                )
                                assert len(result.matched_items) == 3
                                assert len(result.book_only_items) == 0
                                assert len(result.bank_only_items) == 0
                                assert result.status == ReconciliationStatus.BALANCED

                                def test_partial_match_with_difference(
                                    self, reconciliation_engine, sample_system_transactions
                                ):
                                    account_id = uuid4()
                                    stmt_tx = [
                                        {
                                            "reference_number": "REF001",
                                            "amount": Decimal("1000000"),
                                            "date": datetime(2025, 3, 1, tzinfo=UTC),
                                            "description": "Setoran",
                                        },
                                        {
                                            "reference_number": "REF002",
                                            "amount": Decimal("-500000"),
                                            "date": datetime(2025, 3, 2, tzinfo=UTC),
                                            "description": "Tarik",
                                        },
                                    ]
                                    stmt_balance = Decimal("500000")  # 1.000.000 - 500.000
                                    result = reconciliation_engine.reconcile(
                                        account_id=account_id,
                                        book_transactions=sample_system_transactions,
                                        statement_balance=stmt_balance,
                                        statement_date=datetime(2025, 3, 2, tzinfo=UTC),
                                        statement_transactions=stmt_tx,
                                        reconciled_by="tester",
                                    )
                                    # Harus ada 2 matched, 1 book-only (REF003)
                                    assert len(result.matched_items) == 2
                                    assert len(result.book_only_items) == 1
                                    assert len(result.bank_only_items) == 0
                                    assert result.status == ReconciliationStatus.MISMATCH

                                    def test_no_match_at_all(
                                        self, reconciliation_engine, sample_system_transactions
                                    ):
                                        account_id = uuid4()
                                        stmt_tx = [
                                            {
                                                "reference_number": "UNMATCHED",
                                                "amount": Decimal("999999"),
                                                "date": datetime(2025, 3, 10, tzinfo=UTC),
                                                "description": "Unknown",
                                            }
                                        ]
                                        stmt_balance = Decimal("999999")
                                        result = reconciliation_engine.reconcile(
                                            account_id=account_id,
                                            book_transactions=sample_system_transactions,
                                            statement_balance=stmt_balance,
                                            statement_date=datetime(2025, 3, 10, tzinfo=UTC),
                                            statement_transactions=stmt_tx,
                                            reconciled_by="tester",
                                        )
                                        assert len(result.matched_items) == 0
                                        assert len(result.book_only_items) == 3
                                        assert len(result.bank_only_items) == 1
                                        assert result.status == ReconciliationStatus.MISMATCH

                                        def test_match_by_amount_and_date_within_3_days(
                                            self, reconciliation_engine
                                        ):
                                            account_id = uuid4()
                                            system_tx = BankTransaction(
                                                id=uuid4(),
                                                legal_entity_id=uuid4(),
                                                bank_account_id=account_id,
                                                transaction_date=datetime(2025, 3, 5, tzinfo=UTC),
                                                amount=Decimal("1000000"),
                                                transaction_type=TransactionType.DEPOSIT,
                                                description="Deposit",
                                                reference_number="SYS001",
                                                counterparty_name=None,
                                                counterparty_account=None,
                                                status=TransactionStatus.COMPLETED,
                                                is_reconciled=False,
                                                created_by=uuid4(),
                                                created_at=datetime.now(UTC),
                                                reconciled_at=None,
                                            )
                                            system_tx = adapt_transaction(system_tx)
                                            stmt_tx = [
                                                {
                                                    "reference_number": "STMT001",
                                                    "amount": Decimal("1000000"),
                                                    "date": datetime(2025, 3, 6, tzinfo=UTC),
                                                    "description": "Deposit",
                                                }
                                            ]
                                            result = reconciliation_engine.reconcile(
                                                account_id=account_id,
                                                book_transactions=[system_tx],
                                                statement_balance=Decimal("1000000"),
                                                statement_date=datetime(2025, 3, 6, tzinfo=UTC),
                                                statement_transactions=stmt_tx,
                                                reconciled_by="tester",
                                            )
                                            assert len(result.matched_items) == 1
                                            assert result.status == ReconciliationStatus.BALANCED

                                            def test_no_match_if_date_outside_window(
                                                self, reconciliation_engine
                                            ):
                                                account_id = uuid4()
                                                system_tx = BankTransaction(
                                                    id=uuid4(),
                                                    legal_entity_id=uuid4(),
                                                    bank_account_id=account_id,
                                                    transaction_date=datetime(
                                                        2025, 3, 1, tzinfo=UTC
                                                    ),
                                                    amount=Decimal("1000000"),
                                                    transaction_type=TransactionType.DEPOSIT,
                                                    description="Deposit",
                                                    reference_number="SYS001",
                                                    counterparty_name=None,
                                                    counterparty_account=None,
                                                    status=TransactionStatus.COMPLETED,
                                                    is_reconciled=False,
                                                    created_by=uuid4(),
                                                    created_at=datetime.now(UTC),
                                                    reconciled_at=None,
                                                )
                                                system_tx = adapt_transaction(system_tx)
                                                stmt_tx = [
                                                    {
                                                        "reference_number": "STMT001",
                                                        "amount": Decimal("1000000"),
                                                        "date": datetime(2025, 3, 10, tzinfo=UTC),
                                                        "description": "Deposit",
                                                    }
                                                ]
                                                result = reconciliation_engine.reconcile(
                                                    account_id=account_id,
                                                    book_transactions=[system_tx],
                                                    statement_balance=Decimal("1000000"),
                                                    statement_date=datetime(
                                                        2025, 3, 10, tzinfo=UTC
                                                    ),
                                                    statement_transactions=stmt_tx,
                                                    reconciled_by="tester",
                                                )
                                                # Tidak ada match karena tanggal di luar window
                                                assert len(result.matched_items) == 0
                                                # Namun karena jumlah book_only dan bank_only sama, difference = 0 -> BALANCED
                                                assert (
                                                    result.status == ReconciliationStatus.BALANCED
                                                )

                                                def test_match_with_reference_exact_match(
                                                    self, reconciliation_engine
                                                ):
                                                    account_id = uuid4()
                                                    system_tx = BankTransaction(
                                                        id=uuid4(),
                                                        legal_entity_id=uuid4(),
                                                        bank_account_id=account_id,
                                                        transaction_date=datetime(
                                                            2025, 3, 5, tzinfo=UTC
                                                        ),
                                                        amount=Decimal("1000000"),
                                                        transaction_type=TransactionType.DEPOSIT,
                                                        description="Deposit",
                                                        reference_number="REF123",
                                                        counterparty_name=None,
                                                        counterparty_account=None,
                                                        status=TransactionStatus.COMPLETED,
                                                        is_reconciled=False,
                                                        created_by=uuid4(),
                                                        created_at=datetime.now(UTC),
                                                        reconciled_at=None,
                                                    )
                                                    system_tx = adapt_transaction(system_tx)
                                                    stmt_tx = [
                                                        {
                                                            "reference_number": "REF123",
                                                            "amount": Decimal("1000000"),
                                                            "date": datetime(
                                                                2025, 3, 5, tzinfo=UTC
                                                            ),
                                                            "description": "Deposit",
                                                        }
                                                    ]
                                                    result = reconciliation_engine.reconcile(
                                                        account_id=account_id,
                                                        book_transactions=[system_tx],
                                                        statement_balance=Decimal("1000000"),
                                                        statement_date=datetime(
                                                            2025, 3, 5, tzinfo=UTC
                                                        ),
                                                        statement_transactions=stmt_tx,
                                                        reconciled_by="tester",
                                                    )
                                                    assert len(result.matched_items) == 1
                                                    assert (
                                                        result.status
                                                        == ReconciliationStatus.BALANCED
                                                    )

                                                    def test_adjustment_needed_flag(
                                                        self, reconciliation_engine
                                                    ):
                                                        """Test: Perlu adjustment jika perbedaan melebihi tolerance."""
                                                        account_id = uuid4()
                                                        # Buat transaksi sistem yang tidak match dengan statement
                                                        system_tx = BankTransaction(
                                                            id=uuid4(),
                                                            legal_entity_id=uuid4(),
                                                            bank_account_id=account_id,
                                                            transaction_date=datetime(
                                                                2025, 3, 5, tzinfo=UTC
                                                            ),
                                                            amount=Decimal("1000000"),
                                                            transaction_type=TransactionType.DEPOSIT,
                                                            description="Deposit",
                                                            reference_number="SYS001",
                                                            counterparty_name=None,
                                                            counterparty_account=None,
                                                            status=TransactionStatus.COMPLETED,
                                                            is_reconciled=False,
                                                            created_by=uuid4(),
                                                            created_at=datetime.now(UTC),
                                                            reconciled_at=None,
                                                        )
                                                        system_tx = adapt_transaction(system_tx)
                                                        # Statement kosong, sehingga bank_only = [], book_only = [system_tx]
                                                        # book_balance = 1.000.000, reconciled_balance = book_balance - book_only = 0
                                                        # statement_balance = 0 -> difference = 0, status BALANCED.
                                                        # Untuk menghasilkan mismatch, kita perlu statement_balance yang tidak nol.
                                                        # Misal statement_balance = 500.000, tanpa statement transaksi.
                                                        # Maka book_balance = 1.000.000, reconciled_balance = 0, difference = -500.000 -> mismatch
                                                        stmt_tx = []
                                                        stmt_balance = Decimal("500000")
                                                        result = reconciliation_engine.reconcile(
                                                            account_id=account_id,
                                                            book_transactions=[system_tx],
                                                            statement_balance=stmt_balance,
                                                            statement_date=datetime(
                                                                2025, 3, 5, tzinfo=UTC
                                                            ),
                                                            statement_transactions=stmt_tx,
                                                            reconciled_by="tester",
                                                        )
                                                        assert (
                                                            result.status
                                                            == ReconciliationStatus.MISMATCH
                                                        )
                                                        adj = reconciliation_engine.generate_adjustment_entry(
                                                            result
                                                        )
                                                        assert adj is not None
                                                        assert (
                                                            "Bank reconciliation adjustment"
                                                            in adj["description"]
                                                        )

                                                        def test_no_adjustment_needed_if_difference_zero(
                                                            self,
                                                            reconciliation_engine,
                                                            sample_system_transactions,
                                                            sample_statement_transactions,
                                                        ):
                                                            account_id = uuid4()
                                                            result = reconciliation_engine.reconcile(
                                                                account_id=account_id,
                                                                book_transactions=sample_system_transactions,
                                                                statement_balance=Decimal(
                                                                    "2500000"
                                                                ),
                                                                statement_date=datetime(
                                                                    2025, 3, 6, tzinfo=UTC
                                                                ),
                                                                statement_transactions=sample_statement_transactions,
                                                                reconciled_by="tester",
                                                            )
                                                            assert (
                                                                result.status
                                                                == ReconciliationStatus.BALANCED
                                                            )
                                                            assert (
                                                                reconciliation_engine.generate_adjustment_entry(
                                                                    result
                                                                )
                                                                is None
                                                            )

                                                            def test_custom_match_threshold(
                                                                self, reconciliation_engine
                                                            ):
                                                                """Test: Tolerance amount untuk matching (via reference match)."""
                                                                account_id = uuid4()
                                                                system_tx = BankTransaction(
                                                                    id=uuid4(),
                                                                    legal_entity_id=uuid4(),
                                                                    bank_account_id=account_id,
                                                                    transaction_date=datetime(
                                                                        2025, 3, 5, tzinfo=UTC
                                                                    ),
                                                                    amount=Decimal("1000000"),
                                                                    transaction_type=TransactionType.DEPOSIT,
                                                                    description="Deposit",
                                                                    reference_number="REF123",  # Reference SAMA dengan statement
                                                                    counterparty_name=None,
                                                                    counterparty_account=None,
                                                                    status=TransactionStatus.COMPLETED,
                                                                    is_reconciled=False,
                                                                    created_by=uuid4(),
                                                                    created_at=datetime.now(UTC),
                                                                    reconciled_at=None,
                                                                )
                                                                system_tx = adapt_transaction(
                                                                    system_tx
                                                                )

                                                                # Statement amount berbeda 0.5, reference sama
                                                                stmt_tx = [
                                                                    {
                                                                        "reference_number": "REF123",  # SAMA
                                                                        "amount": Decimal(
                                                                            "1000000.5"
                                                                        ),
                                                                        "date": datetime(
                                                                            2025, 3, 5, tzinfo=UTC
                                                                        ),
                                                                        "description": "Deposit",
                                                                    }
                                                                ]

                                                                # Default tolerance 0.01 -> tidak match (selisih 0.5 > 0.01)
                                                                result = reconciliation_engine.reconcile(
                                                                    account_id=account_id,
                                                                    book_transactions=[system_tx],
                                                                    statement_balance=Decimal(
                                                                        "1000000.5"
                                                                    ),
                                                                    statement_date=datetime(
                                                                        2025, 3, 5, tzinfo=UTC
                                                                    ),
                                                                    statement_transactions=stmt_tx,
                                                                    reconciled_by="tester",
                                                                )
                                                                assert (
                                                                    len(result.matched_items) == 0
                                                                )

                                                                # Engine dengan tolerance 1.0 -> selisih 0.5 <= 1.0, harus match
                                                                engine2 = BankReconciliationEngine(
                                                                    tolerance=Decimal("1.0")
                                                                )
                                                                result2 = engine2.reconcile(
                                                                    account_id=account_id,
                                                                    book_transactions=[system_tx],
                                                                    statement_balance=Decimal(
                                                                        "1000000.5"
                                                                    ),
                                                                    statement_date=datetime(
                                                                        2025, 3, 5, tzinfo=UTC
                                                                    ),
                                                                    statement_transactions=stmt_tx,
                                                                    reconciled_by="tester",
                                                                )
                                                                assert (
                                                                    len(result2.matched_items) == 1
                                                                )
                                                                assert (
                                                                    result2.status
                                                                    == ReconciliationStatus.BALANCED
                                                                )

                                                                if __name__ == "__main__":
                                                                    pytest.main([__file__])
