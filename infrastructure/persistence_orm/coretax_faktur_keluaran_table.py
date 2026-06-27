"""
Module: coretax_faktur_keluaran_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM model untuk Coretax Faktur Keluaran.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.persistence_orm.base_model import Base


class CoretaxFakturKeluaranTable(Base):
    __tablename__ = "coretax_faktur_keluaran"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    faktur_number = Column(String(30), nullable=False, unique=True)
    faktur_code = Column(String(3), nullable=False)
    customer_id = Column(SQLUUID(as_uuid=True), nullable=True)
    customer_npwp = Column(String(15), nullable=True)
    customer_name = Column(String(200), nullable=False)
    customer_address = Column(String(500), nullable=True)
    transaction_date = Column(Date, nullable=False)
    dpp_amount = Column(Numeric(19, 4), nullable=False)
    ppn_amount = Column(Numeric(19, 4), nullable=False)
    ppn_rate = Column(Numeric(5, 2), nullable=False)
    ppnbm_amount = Column(Numeric(19, 4), server_default="0")
    masa_pajak = Column(String(7), nullable=False)
    tahun_pajak = Column(String(4), nullable=False)
    nsfp_used = Column(String(20), nullable=True)
    status = Column(String(30), nullable=False, server_default="draft")
    approval_code = Column(String(50), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    submission_date = Column(DateTime, nullable=True)
    approval_date = Column(DateTime, nullable=True)
    voided_at = Column(DateTime, nullable=True)
    response_data = Column(JSONB, nullable=True)
    error_message = Column(String(500), nullable=True)
    hash_link = Column(String(128), nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")
    is_deleted = Column(Integer, server_default="0")
