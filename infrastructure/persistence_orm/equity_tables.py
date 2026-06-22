"""
Module: equity_tables.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM models untuk Equity.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import UUID as SQLUUID, Column, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.persistence_orm.base_model import Base


class CapitalContributionTable(Base):
    __tablename__ = "capital_contribution"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    contribution_number = Column(String(50), nullable=False, unique=True)
    contribution_date = Column(Date, nullable=False)
    shareholder_id = Column(SQLUUID(as_uuid=True), nullable=True)
    shareholder_name = Column(String(200), nullable=False)
    contribution_type = Column(String(20), nullable=False)
    amount = Column(Numeric(19, 4), nullable=False)
    currency = Column(String(3), server_default="IDR")
    notes = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(SQLUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")


class DividendDeclarationTable(Base):
    __tablename__ = "dividend_declaration"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    declaration_number = Column(String(50), nullable=False, unique=True)
    declaration_date = Column(Date, nullable=False)
    record_date = Column(Date, nullable=False)
    payment_date = Column(Date, nullable=False)
    dividend_type = Column(String(20), nullable=False)
    total_amount = Column(Numeric(19, 4), nullable=False)
    dividend_per_share = Column(Numeric(19, 4), nullable=False)
    currency = Column(String(3), server_default="IDR")
    status = Column(String(20), nullable=False, server_default="proposed")
    notes = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(SQLUUID(as_uuid=True), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")


class RetainedEarningsHistoryTable(Base):
    __tablename__ = "retained_earnings_history"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    period = Column(String(7), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    beginning_balance = Column(Numeric(19, 4), nullable=False)
    net_income = Column(Numeric(19, 4), nullable=False)
    dividends = Column(Numeric(19, 4), server_default="0")
    ending_balance = Column(Numeric(19, 4), nullable=False)
    currency = Column(String(3), server_default="IDR")
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")