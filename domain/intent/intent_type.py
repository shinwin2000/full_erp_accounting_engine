#!/usr/bin/env python3
"""
Module: intent_type.py
Layer: 5 - Reality, Intent, Causality / Intent
Responsibility: Definisi tipe-tipe intent yang dapat ditangkap.
"""

from __future__ import annotations

from enum import Enum, auto


class IntentType(Enum):
    CREATE_JOURNAL = auto()
    CREATE_INVOICE = auto()
    CREATE_PAYMENT = auto()
    CREATE_PURCHASE_ORDER = auto()
    CREATE_SALES_ORDER = auto()
    RECORD_CASH_RECEIPT = auto()
    RECORD_CASH_DISBURSEMENT = auto()
    ADJUST_INVENTORY = auto()
    DISPOSE_ASSET = auto()
    CLOSE_PERIOD = auto()
    APPROVE_TRANSACTION = auto()
    REJECT_TRANSACTION = auto()

    @classmethod
    def from_string(cls, value: str) -> IntentType:
        try:
            return cls[value.upper()]
        except KeyError:
            raise ValueError(f"Unknown IntentType: {value}")


__all__ = ["IntentType"]
