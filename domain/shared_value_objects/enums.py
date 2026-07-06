#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: enums.py
Layer: Domain / Shared Value Objects

Canonical definitions for enums used across the system.
"""

from enum import Enum


class TransactionType(Enum):
    """
    Canonical TransactionType enum - combines all definitions from various modules.
    Values are preserved according to original files.
    """
    # ===== from fastapi_bank_cash_router.py =====
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    BANK_CHARGE = "bank_charge"
    INTEREST = "interest"
    ADJUSTMENT = "adjustment"
    REFUND = "refund"
    CORRECTION = "correction"

    # ===== from fastapi_tax_coretax_router.py =====
    SALES = "sales"
    PURCHASE = "purchase"
    SALARY = "salary"
    DIVIDEND = "dividend"
    ROYALTY = "royalty"
    SERVICE = "service"
    RENT = "rent"
    IMPORT = "import"
    EXPORT = "export"
    CONSTRUCTION = "construction"

    # ===== from aml_risk_scorer.py =====
    TRANSFER = "transfer"
    PAYMENT = "payment"
    TRADE = "trade"
    CROSS_BORDER = "cross_border"

    # ===== from legal_risk_assessment_engine.py =====
    CROSS_BORDER_PAYMENT = "cross_border_payment"
    DOMESTIC_PAYMENT = "domestic_payment"
    INVESTMENT = "investment"
    LOAN = "loan"
    MERGER_ACQUISITION = "merger_acquisition"
    REAL_ESTATE = "real_estate"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    EMPLOYMENT = "employment"
    TAX_PLANNING = "tax_planning"
    POLITICAL_CONTRIBUTION = "political_contribution"
    OTHER = "other"

    # ===== from bank_transaction_entity.py =====
    FEE = "fee"
    CHEQUE = "cheque"

    # ===== from intercompany_transaction.py =====
    SALE = "sale"
    REPAYMENT = "repayment"

    # ===== from simplified_journal_entity.py =====
    INCOME = "income"
    EXPENSE = "expense"

    # ===== from psak_07_related_party.py (values in Indonesian) =====
    PURCHASE_ID = "pembelian"      # Indonesian
    SALE_ID = "penjualan"          # Indonesian
    LOAN_ID = "pinjaman"           # Indonesian
    GUARANTEE = "jaminan"          # Indonesian
    DIVIDEND_ID = "dividen"        # Indonesian
    SERVICE_ID = "jasa"            # Indonesian
    OTHER_ID = "lainnya"           # Indonesian

    # ===== from bank_cash_repository_port.py =====
    CHECK = "check"
    ELECTRONIC = "electronic"