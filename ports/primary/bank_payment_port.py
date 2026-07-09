#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Port: BankPaymentPort
Layer: Ports (Primary)
Responsibility: Antarmuka untuk pembayaran melalui API bank.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any


class BankPaymentPort(ABC):
    """Port untuk melakukan pembayaran melalui bank."""

    @abstractmethod
    async def transfer(
        self,
        from_account: str,
        to_account: str,
        amount: Decimal,
        currency: str = "IDR",
    ) -> dict[str, Any]:
        """Lakukan transfer antar rekening."""
        pass

    @abstractmethod
    async def check_status(self, transaction_id: str) -> dict[str, Any]:
        """Cek status transaksi."""
        pass

    @abstractmethod
    async def get_balance(self, account_number: str) -> Decimal:
        """Dapatkan saldo rekening."""
        pass