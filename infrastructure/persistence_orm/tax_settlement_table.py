"""
Module: tax_settlement_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM models untuk Tax settlement.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text

from infrastructure.persistence_orm.base_model import Base


class PpnSettlementTable(Base):
    __tablename__ = "ppn_settlement"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    period = Column(String(7), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    output_ppn = Column(Numeric(19, 4), server_default="0")
    input_ppn = Column(Numeric(19, 4), server_default="0")
    net_ppn = Column(Numeric(19, 4), server_default="0")
    ppn_paid = Column(Numeric(19, 4), server_default="0")
    ppn_due = Column(Numeric(19, 4), server_default="0")
    status = Column(String(20), nullable=False, server_default="pending")
    settlement_date = Column(Date, nullable=True)
    ntpn = Column(String(16), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)


class PphWithholdingSummaryTable(Base):
    __tablename__ = "pph_withholding_summary"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    period = Column(String(7), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    pph_type = Column(String(10), nullable=False)
    gross_amount = Column(Numeric(19, 4), server_default="0")
    tax_amount = Column(Numeric(19, 4), server_default="0")
    tax_paid = Column(Numeric(19, 4), server_default="0")
    tax_due = Column(Numeric(19, 4), server_default="0")
    status = Column(String(20), nullable=False, server_default="pending")
    settlement_date = Column(Date, nullable=True)
    ntpn = Column(String(16), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
