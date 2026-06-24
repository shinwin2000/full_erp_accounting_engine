#!/usr/bin/env python3
"""
Module: ar_debit_note_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: ORM model for AR Debit Note.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ARDebitNoteTable(Base):
    __tablename__ = "ar_debit_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    debit_note_number = Column(String(50), nullable=False, unique=True)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("ar_invoices.id"), nullable=False)
    debit_note_date = Column(DateTime(timezone=True), nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="IDR")
    reason = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by = Column(UUID(as_uuid=True), nullable=True)

    def __repr__(self):
        return f"<ARDebitNoteTable {self.debit_note_number}>"