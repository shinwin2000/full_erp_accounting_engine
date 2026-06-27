"""
Module: projection_read_models.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM models untuk projection/read model tables.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
)

from infrastructure.persistence_orm.base_model import Base


class ProjectionGLTable(Base):
    __tablename__ = "projection_gl_ledger"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    account_id = Column(SQLUUID(as_uuid=True), nullable=False)
    account_code = Column(String(20), nullable=False)
    account_name = Column(String(200), nullable=False)
    posting_date = Column(Date, nullable=False)
    period = Column(String(7), nullable=False)
    debit_amount = Column(Numeric(19, 4), server_default="0")
    credit_amount = Column(Numeric(19, 4), server_default="0")
    balance = Column(Numeric(19, 4), nullable=False)
    journal_id = Column(SQLUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, server_default="now()")


class ProjectionTrialBalanceTable(Base):
    __tablename__ = "projection_trial_balance"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    account_id = Column(SQLUUID(as_uuid=True), nullable=False)
    account_code = Column(String(20), nullable=False)
    account_name = Column(String(200), nullable=False)
    account_type = Column(String(30), nullable=False)
    period = Column(String(7), nullable=False)
    opening_debit = Column(Numeric(19, 4), server_default="0")
    opening_credit = Column(Numeric(19, 4), server_default="0")
    movement_debit = Column(Numeric(19, 4), server_default="0")
    movement_credit = Column(Numeric(19, 4), server_default="0")
    closing_debit = Column(Numeric(19, 4), server_default="0")
    closing_credit = Column(Numeric(19, 4), server_default="0")
    created_at = Column(DateTime, server_default="now()")


class ProjectionARAgingTable(Base):
    __tablename__ = "projection_ar_aging"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    customer_id = Column(SQLUUID(as_uuid=True), nullable=False)
    customer_name = Column(String(200), nullable=False)
    invoice_id = Column(SQLUUID(as_uuid=True), nullable=False)
    invoice_number = Column(String(50), nullable=False)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(Numeric(19, 4), nullable=False)
    outstanding_amount = Column(Numeric(19, 4), nullable=False)
    days_overdue = Column(Integer, server_default="0")
    aging_bucket = Column(String(20), nullable=False)
    currency = Column(String(3), server_default="IDR")
    created_at = Column(DateTime, server_default="now()")


class ProjectionAPAgingTable(Base):
    __tablename__ = "projection_ap_aging"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    vendor_id = Column(SQLUUID(as_uuid=True), nullable=False)
    vendor_name = Column(String(200), nullable=False)
    invoice_id = Column(SQLUUID(as_uuid=True), nullable=False)
    invoice_number = Column(String(50), nullable=False)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(Numeric(19, 4), nullable=False)
    outstanding_amount = Column(Numeric(19, 4), nullable=False)
    days_overdue = Column(Integer, server_default="0")
    aging_bucket = Column(String(20), nullable=False)
    currency = Column(String(3), server_default="IDR")
    created_at = Column(DateTime, server_default="now()")


class ProjectionPPNSettlementTable(Base):
    __tablename__ = "projection_ppn_settlement"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    period = Column(String(7), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    output_ppn = Column(Numeric(19, 4), server_default="0")
    input_ppn = Column(Numeric(19, 4), server_default="0")
    net_ppn = Column(Numeric(19, 4), server_default="0")
    status = Column(String(20), server_default="pending")
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")


class ProjectionPPHSummaryTable(Base):
    __tablename__ = "projection_pph_summary"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    period = Column(String(7), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    pph_type = Column(String(10), nullable=False)
    gross_amount = Column(Numeric(19, 4), server_default="0")
    tax_amount = Column(Numeric(19, 4), server_default="0")
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")


class ProjectionCoretaxDashboardTable(Base):
    __tablename__ = "projection_coretax_dashboard"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    period = Column(String(7), nullable=False)
    total_faktur_keluaran = Column(Integer, server_default="0")
    total_faktur_masukan = Column(Integer, server_default="0")
    total_ppn_keluaran = Column(Numeric(19, 4), server_default="0")
    total_ppn_masukan = Column(Numeric(19, 4), server_default="0")
    total_bupot = Column(Integer, server_default="0")
    total_pph = Column(Numeric(19, 4), server_default="0")
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")


class ProjectionTrend12MonthTable(Base):
    __tablename__ = "projection_trend_12month"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    metric_type = Column(String(50), nullable=False)
    period = Column(String(7), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    amount = Column(Numeric(19, 4), nullable=False)
    previous_period_amount = Column(Numeric(19, 4), nullable=True)
    growth_percent = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, server_default="now()")


class ProjectionVarianceAnalysisTable(Base):
    __tablename__ = "projection_variance_analysis"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    account_id = Column(SQLUUID(as_uuid=True), nullable=False)
    account_code = Column(String(20), nullable=False)
    period = Column(String(7), nullable=False)
    budget_amount = Column(Numeric(19, 4), nullable=False)
    actual_amount = Column(Numeric(19, 4), nullable=False)
    variance_amount = Column(Numeric(19, 4), nullable=False)
    variance_percent = Column(Numeric(10, 2), nullable=True)
    variance_type = Column(String(20), nullable=False)
    created_at = Column(DateTime, server_default="now()")


class ProjectionProfitabilitySegmentTable(Base):
    __tablename__ = "projection_profitability_segment"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    segment_type = Column(String(30), nullable=False)
    segment_id = Column(SQLUUID(as_uuid=True), nullable=False)
    segment_name = Column(String(200), nullable=False)
    period = Column(String(7), nullable=False)
    revenue = Column(Numeric(19, 4), server_default="0")
    cost = Column(Numeric(19, 4), server_default="0")
    profit = Column(Numeric(19, 4), server_default="0")
    profit_margin = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, server_default="now()")


class ProjectionFinancialRatiosTable(Base):
    __tablename__ = "projection_financial_ratios"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    period = Column(String(7), nullable=False)
    ratio_type = Column(String(50), nullable=False)
    ratio_value = Column(Numeric(19, 4), nullable=False)
    numerator = Column(Numeric(19, 4), nullable=True)
    denominator = Column(Numeric(19, 4), nullable=True)
    benchmark = Column(Numeric(19, 4), nullable=True)
    created_at = Column(DateTime, server_default="now()")


class ProjectionKpiAlerterTable(Base):
    __tablename__ = "projection_kpi_alerter"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    kpi_name = Column(String(100), nullable=False)
    current_value = Column(Numeric(19, 4), nullable=False)
    threshold_value = Column(Numeric(19, 4), nullable=False)
    threshold_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    alert_message = Column(String(500), nullable=True)
    created_at = Column(DateTime, server_default="now()")
    resolved_at = Column(DateTime, nullable=True)
