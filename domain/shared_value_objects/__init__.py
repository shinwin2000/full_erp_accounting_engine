#!/usr/bin/env python3
"""
Shared Value Objects Package

This package contains immutable value objects used across multiple domains.
All value objects are frozen dataclasses with validation and business logic.
"""

from domain.shared_value_objects.accounting_period_vo import (
    AccountingPeriod,
    AccountingPeriodVO,
    PeriodStatus,
    PeriodType,
)
from domain.shared_value_objects.cost_center_vo import CostCenterVO
from domain.shared_value_objects.currency_vo import Currency, CurrencyCode, CurrencyVO
from domain.shared_value_objects.date_range_vo import DateRangeVO
from domain.shared_value_objects.department_vo import DepartmentVO
from domain.shared_value_objects.document_number_vo import (
    DocumentNumber,
    DocumentNumberVO,
    DocumentType,
)
from domain.shared_value_objects.exchange_rate_vo import ExchangeRateVO
from domain.shared_value_objects.fiscal_year_vo import FiscalYearType, FiscalYearVO
from domain.shared_value_objects.hash_chain_link_vo import HashChainLinkVO
from domain.shared_value_objects.idempotency_key_vo import IdempotencyKeyVO
from domain.shared_value_objects.money_vo import Money
from domain.shared_value_objects.percentage_vo import Percentage, PercentageVO
from domain.shared_value_objects.quantity_vo import Quantity, QuantityVO, UnitOfMeasure
from domain.shared_value_objects.signature_vo import SignatureVO
from domain.shared_value_objects.tax_rate_vo import TaxRateVO, TaxType
from domain.shared_value_objects.warehouse_vo import WarehouseCode, WarehouseCodeVO, WarehouseVO

__all__ = [
    # Accounting Period
    "AccountingPeriodVO",
    "PeriodStatus",
    "PeriodType",
    "AccountingPeriod",
    # Cost Center
    "CostCenterVO",
    # Currency
    "CurrencyVO",
    "CurrencyCode",
    "Currency",
    # Date Range
    "DateRangeVO",
    # Department
    "DepartmentVO",
    # Document Number
    "DocumentNumberVO",
    "DocumentType",
    "DocumentNumber",
    # Exchange Rate
    "ExchangeRateVO",
    # Fiscal Year
    "FiscalYearVO",
    "FiscalYearType",
    # Hash Chain
    "HashChainLinkVO",
    # Idempotency Key
    "IdempotencyKeyVO",
    # Money
    "Money",
    # Percentage
    "PercentageVO",
    "Percentage",
    # Quantity
    "QuantityVO",
    "UnitOfMeasure",
    "Quantity",
    # Signature
    "SignatureVO",
    # Tax Rate
    "TaxRateVO",
    "TaxType",
    # Warehouse
    "WarehouseVO",
    "WarehouseCode",
    "WarehouseCodeVO",
]
