"""
Module: umkm_journal_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM model untuk UMKM simplified journal.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text

from infrastructure.persistence_orm.base_model import Base


class UmkmJournalTable(Base):
    __tablename__ = "umkm_journal"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    journal_number = Column(String(50), nullable=False, unique=True)
    journal_date = Column(Date, nullable=False)
    description = Column(Text, nullable=False)
    debit_account_code = Column(String(20), nullable=False)
    debit_account_name = Column(String(200), nullable=False)
    debit_amount = Column(Numeric(19, 4), nullable=False)
    credit_account_code = Column(String(20), nullable=False)
    credit_account_name = Column(String(200), nullable=False)
    credit_amount = Column(Numeric(19, 4), nullable=False)
    tax_id = Column(SQLUUID(as_uuid=True), nullable=True)
    attachment_url = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, server_default="draft")
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(SQLUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, server_default="now()")
    updated_at = Column(DateTime, server_default="now()")
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=True)
    version = Column(Integer, server_default="1")
