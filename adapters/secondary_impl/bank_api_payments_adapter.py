#!/usr/bin/env python3
"""
Module: bank_api_payments_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Melakukan pembayaran melalui API bank (misal, BCA, Mandiri).
                Mendukung transfer online, pembayaran tagihan, dan pengecekan status.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

# Import port yang sesuai
from ports.primary.bank_payment_port import BankPaymentPort

logger = logging.getLogger(__name__)


class BankAPIPaymentsAdapter(BankPaymentPort):
    """
    Adapter untuk API pembayaran bank.
    Stub untuk development, tidak melakukan call nyata.
    """

    def __init__(
        self, base_url: str = "https://mock-bank-api.example.com", api_key: str | None = None
    ):
        self.base_url = base_url
        self.api_key = api_key
        logger.info("BankAPIPaymentsAdapter initialized with base_url=%s", base_url)

    async def transfer(
        self, from_account: str, to_account: str, amount: Decimal, currency: str = "IDR"
    ) -> dict[str, Any]:
        """Lakukan transfer antar rekening."""
        logger.info("Transfer %s %s from %s to %s", amount, currency, from_account, to_account)
        return {
            "success": True,
            "transaction_id": str(UUID(int=123456)),
            "status": "PROCESSED",
            "message": "Transfer successful (mock)",
        }

    async def check_status(self, transaction_id: str) -> dict[str, Any]:
        """Cek status transaksi."""
        logger.info("Checking status of transaction %s", transaction_id)
        return {"status": "SUCCESS", "transaction_id": transaction_id}

    async def get_balance(self, account_number: str) -> Decimal:
        """Dapatkan saldo rekening."""
        logger.info("Getting balance for account %s", account_number)
        return Decimal("1000000000")  # mock