# tests/e2e/test_bank_reconciliation_full.py
#!/usr/bin/env python3
"""
E2E: Bank Reconciliation Full Flow (Real Domain Engine)
Menguji rekonsiliasi bank tanpa mock, menggunakan domain engine asli.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.bank_reconciliation_engine import BankReconciliationEngine
from domain.bank_cash.bank_transaction_entity import TransactionStatus, TransactionType


class SimpleBankTransaction:
    """Wrapper sederhana untuk transaksi buku yang kompatibel dengan engine."""

    def __init__(self, tx_id, amount, tx_datetime, tx_type, ref, description):
        self.transaction_id = tx_id
        self.amount = amount
        self.transaction_date = tx_datetime
        self.transaction_type = tx_type
        self.reference_number = ref
        self.description = description
        self.status = TransactionStatus.COMPLETED

        def is_credit(self):
            """Return True jika transaksi menambah saldo (deposit/transfer in)."""
            return self.transaction_type in (TransactionType.DEPOSIT, TransactionType.TRANSFER_IN)

            def test_bank_reconciliation_full_flow():
                # 1. Transaksi buku (internal) yang terjadi dalam periode rekonsiliasi
                book_transactions = [
                    SimpleBankTransaction(
                        tx_id=uuid4(),
                        amount=Decimal("1000000"),
                        tx_datetime=datetime(2025, 1, 2, 0, 0, 0),
                        tx_type=TransactionType.WITHDRAWAL,
                        ref="FEE-001",
                        description="Bank fee",
                    ),
                    SimpleBankTransaction(
                        tx_id=uuid4(),
                        amount=Decimal("5000000"),
                        tx_datetime=datetime(2025, 1, 3, 0, 0, 0),
                        tx_type=TransactionType.DEPOSIT,
                        ref="DEP-001",
                        description="Customer deposit",
                    ),
                ]

                # 2. Transaksi statement bank (MT940) yang sama persis
                statement_transactions = [
                    {
                        "reference_number": "FEE-001",
                        "amount": Decimal("1000000"),
                        "date": datetime(2025, 1, 2, 0, 0, 0),
                        "description": "Bank fee",
                    },
                    {
                        "reference_number": "DEP-001",
                        "amount": Decimal("5000000"),
                        "date": datetime(2025, 1, 3, 0, 0, 0),
                        "description": "Customer deposit",
                    },
                ]

                # 3. Lakukan rekonsiliasi
                #    Catatan: Karena engine tidak menyertakan saldo awal, statement_balance harus sama dengan
                #    jumlah bersih dari transaksi yang diberikan (deposit - withdrawal = 4.000.000).
                engine = BankReconciliationEngine(tolerance=Decimal("0.01"), date_tolerance_days=3)
                result = engine.reconcile(
                    account_id=uuid4(),
                    book_transactions=book_transactions,
                    statement_balance=Decimal("4000000"),
                    statement_date=datetime(2025, 1, 3, 23, 59, 59),
                    statement_transactions=statement_transactions,
                    reconciled_by="system",
                )

                # 4. Verifikasi bahwa rekonsiliasi balanced
                assert result.status.value == "balanced", (
                    f"Expected 'balanced', got {result.status.value}"
                )
                assert abs(result.difference) <= Decimal("0.01")
                assert len(result.matched_items) == 2  # Kedua transaksi match
                assert len(result.book_only_items) == 0
                assert len(result.bank_only_items) == 0

                # 5. Karena balanced, tidak ada jurnal penyesuaian
                adjustment = engine.generate_adjustment_entry(result)
                assert adjustment is None

                print("E2E test passed successfully!")

                if __name__ == "__main__":
                    pytest.main([__file__])
