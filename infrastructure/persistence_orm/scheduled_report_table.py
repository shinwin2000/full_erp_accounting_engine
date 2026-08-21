"""
Module: scheduled_report_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: ORM model untuk konfigurasi jadwal laporan otomatis
    (POST/GET/PUT/DELETE /api/v1/reports/schedule di fastapi_report_router.py).

CATATAN ARSITEKTUR: sengaja dibuat sebagai tabel BARU, terpisah dari
`report_schedule` (report_schedule_table.py) yang sudah ada. Tabel lama itu
dirancang di sekitar `cron_expression` + `definition_id` (FK NOT NULL ke
report_definition) untuk mesin eksekusi APScheduler
(ReportScheduler.add_job/load_jobs_from_db). Router butuh model konfigurasi
yang berbeda total (schedule_frequency/schedule_time/day_of_week/
day_of_month terpisah, tanpa definition_id, dengan recipient & delivery
method) - memaksakan skema lama akan butuh migrasi besar & berisiko
mengganggu mesin eksekusi cron yang sudah ada. Dua sistem ini independen;
`report_schedule` tetap ada untuk keperluannya sendiri.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import UUID as SQLUUID
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text

from infrastructure.persistence_orm.base_model import Base


class ScheduledReportTable(Base):
    __tablename__ = "scheduled_report"

    id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(SQLUUID(as_uuid=True), nullable=False)
    schedule_name = Column(String(200), nullable=False)
    report_type = Column(String(40), nullable=False)
    schedule_frequency = Column(String(20), nullable=False)
    schedule_time = Column(String(5), nullable=True)  # "HH:MM"
    schedule_day_of_week = Column(Integer, nullable=True)
    schedule_day_of_month = Column(Integer, nullable=True)
    report_format = Column(String(10), nullable=False, default="pdf")
    parameters = Column(JSON, nullable=False, default=dict)
    recipient_emails = Column(JSON, nullable=False, default=list)
    recipient_whatsapps = Column(JSON, nullable=False, default=list)
    delivery_methods = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    created_by = Column(SQLUUID(as_uuid=True), nullable=False)
    updated_by = Column(SQLUUID(as_uuid=True), nullable=True)
    created_by_name = Column(String(200), nullable=True)
    version = Column(Integer, nullable=False, default=1)


__all__ = ["ScheduledReportTable"]
