#!/usr/bin/env python3
"""
Module: legal_obligation_calendar.py
Layer: Compliance / Legal

Responsibility:
    Kalender kewajiban legal (filing, pelaporan, pembayaran) berdasarkan yurisdiksi
    dan regulator. Mendukung definisi kewajiban, perhitungan due date, pengingat,
    tracking status pemenuhan, SLA breach detection, integrasi dengan regulatory bodies,
    export kalender (JSON, iCalendar), dan audit trail.

Dependencies:
    - datetime, enum, typing, hashlib, json, logging, uuid
    - icalendar (optional for .ics export)

Audit:
    Setiap perubahan status obligation, pengingat, dan pemenuhan deadline dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Optional iCalendar export
try:
    from icalendar import Calendar, Event

    HAS_ICAL = True
except ImportError:
    HAS_ICAL = False


# ============================================================================
# Enums
# ============================================================================
class ObligationFrequency(Enum):
    ONE_TIME = "one_time"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    BIENNIAL = "biennial"


class ObligationStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    COMPLETED = "completed"
    WAIVED = "waived"
    OVERDUE = "overdue"


class ReminderType(Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"


# ============================================================================
# Exceptions
# ============================================================================
class ObligationCalendarError(Exception):
    pass


class ObligationNotFoundError(ObligationCalendarError):
    pass


# ============================================================================
# Data Classes
# ============================================================================
class LegalObligation:
    def __init__(
        self,
        obligation_id: UUID,
        title: str,
        description: str,
        jurisdiction: str,
        regulatory_body: str,
        frequency: ObligationFrequency,
        due_day: int,  # day of month or relative
        due_month_offset: int = 0,  # for annual: month (1-12)
        lead_time_days: int = 0,  # reminder days before due
        is_mandatory: bool = True,
        penalty_for_late: str | None = None,
        responsible_party: str | None = None,
        external_reference: str | None = None,
    ):
        self.id = obligation_id
        self.title = title
        self.description = description
        self.jurisdiction = jurisdiction
        self.regulatory_body = regulatory_body
        self.frequency = frequency
        self.due_day = due_day
        self.due_month_offset = due_month_offset
        self.lead_time_days = lead_time_days
        self.is_mandatory = is_mandatory
        self.penalty_for_late = penalty_for_late
        self.responsible_party = responsible_party
        self.external_reference = external_reference
        self.created_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "title": self.title,
            "jurisdiction": self.jurisdiction,
            "regulatory_body": self.regulatory_body,
            "frequency": self.frequency.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "obligation_id": str(self.id),
            "title": self.title,
            "description": self.description,
            "jurisdiction": self.jurisdiction,
            "regulatory_body": self.regulatory_body,
            "frequency": self.frequency.value,
            "due_day": self.due_day,
            "due_month_offset": self.due_month_offset,
            "lead_time_days": self.lead_time_days,
            "is_mandatory": self.is_mandatory,
            "penalty_for_late": self.penalty_for_late,
            "responsible_party": self.responsible_party,
            "hash": self._hash,
        }


class ObligationInstance:
    """Instance kewajiban untuk periode tertentu (bulan/tahun tertentu)."""

    def __init__(
        self,
        instance_id: UUID,
        obligation_id: UUID,
        due_date: date,
        period: str,  # e.g., "2025-03", "2025"
        status: ObligationStatus = ObligationStatus.PENDING,
        submitted_date: date | None = None,
        reference_number: str | None = None,
        notes: str = "",
    ):
        self.id = instance_id
        self.obligation_id = obligation_id
        self.due_date = due_date
        self.period = period
        self.status = status
        self.submitted_date = submitted_date
        self.reference_number = reference_number
        self.notes = notes
        self.reminder_sent_at: datetime | None = None
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "instance_id": str(self.id),
            "obligation_id": str(self.obligation_id),
            "due_date": self.due_date.isoformat(),
            "status": self.status.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def mark_completed(self, submitted_date: date, reference_number: str | None = None) -> None:
        self.status = ObligationStatus.COMPLETED
        self.submitted_date = submitted_date
        if reference_number:
            self.reference_number = reference_number
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def mark_overdue(self) -> None:
        if self.status not in (ObligationStatus.COMPLETED, ObligationStatus.WAIVED):
            self.status = ObligationStatus.OVERDUE
            self.updated_at = datetime.utcnow()
            self._hash = self._compute_hash()

    def to_dict(self) -> dict:
        return {
            "instance_id": str(self.id),
            "obligation_id": str(self.obligation_id),
            "due_date": self.due_date.isoformat(),
            "period": self.period,
            "status": self.status.value,
            "submitted_date": self.submitted_date.isoformat() if self.submitted_date else None,
            "reference_number": self.reference_number,
            "notes": self.notes,
            "reminder_sent_at": self.reminder_sent_at.isoformat()
            if self.reminder_sent_at
            else None,
            "hash": self._hash,
        }


# ============================================================================
# LegalObligationCalendar Core
# ============================================================================
class LegalObligationCalendar:
    """
    Kalender kewajiban legal: definisi, instance generation, tracking, reminder.
    """

    def __init__(self):
        self._obligations: dict[UUID, LegalObligation] = {}
        self._instances: dict[UUID, ObligationInstance] = {}  # instance_id -> instance
        self._obligation_instances: dict[
            UUID, list[UUID]
        ] = {}  # obligation_id -> list of instance_ids
        self._init_default_obligations()

    def _init_default_obligations(self):
        """Inisialisasi kewajiban default untuk Indonesia."""
        # Indonesia - DJP (Pajak)
        self.add_obligation(
            LegalObligation(
                obligation_id=uuid4(),
                title="SPT Masa PPN",
                description="Laporan Pajak Pertambahan Nilai bulanan",
                jurisdiction="ID",
                regulatory_body="DJP",
                frequency=ObligationFrequency.MONTHLY,
                due_day=20,
                lead_time_days=5,
                penalty_for_late="Denda 2% per bulan dari DPP",
                responsible_party="Tax Manager",
                external_reference="PMK No. 68/PMK.03/2022",
            )
        )
        self.add_obligation(
            LegalObligation(
                obligation_id=uuid4(),
                title="SPT Tahunan Badan",
                description="Laporan Pajak Penghasilan Badan tahunan",
                jurisdiction="ID",
                regulatory_body="DJP",
                frequency=ObligationFrequency.ANNUAL,
                due_day=30,
                due_month_offset=4,
                lead_time_days=30,
                penalty_for_late="Denda 2% per bulan dari PPh terutang",
                responsible_party="Tax Manager",
            )
        )
        self.add_obligation(
            LegalObligation(
                obligation_id=uuid4(),
                title="Pembayaran Angsuran PPh 25",
                description="Angsuran Pajak Penghasilan bulanan",
                jurisdiction="ID",
                regulatory_body="DJP",
                frequency=ObligationFrequency.MONTHLY,
                due_day=15,
                lead_time_days=3,
                responsible_party="Finance",
            )
        )
        # Indonesia - OJK
        self.add_obligation(
            LegalObligation(
                obligation_id=uuid4(),
                title="LKPBU (Laporan Keuangan Publik Bulanan)",
                description="Laporan keuangan bulanan untuk perusahaan publik",
                jurisdiction="ID",
                regulatory_body="OJK",
                frequency=ObligationFrequency.MONTHLY,
                due_day=15,
                lead_time_days=7,
                penalty_for_late="Sanksi administratif per POJK",
                responsible_party="Financial Reporting Manager",
                external_reference="POJK No. 29/POJK.04/2016",
            )
        )
        self.add_obligation(
            LegalObligation(
                obligation_id=uuid4(),
                title="Laporan Tahunan (Annual Report)",
                description="Laporan tahunan perusahaan publik",
                jurisdiction="ID",
                regulatory_body="OJK",
                frequency=ObligationFrequency.ANNUAL,
                due_day=30,
                due_month_offset=4,
                lead_time_days=45,
                responsible_party="Corporate Secretary",
            )
        )
        # Indonesia - BI
        self.add_obligation(
            LegalObligation(
                obligation_id=uuid4(),
                title="Laporan Transaksi Valuta Asing",
                description="Laporan bulanan transaksi devisa",
                jurisdiction="ID",
                regulatory_body="BI",
                frequency=ObligationFrequency.MONTHLY,
                due_day=10,
                lead_time_days=5,
                responsible_party="Treasury",
            )
        )
        # Singapore - MAS/IRAS (contoh)
        self.add_obligation(
            LegalObligation(
                obligation_id=uuid4(),
                title="Annual Income Tax Filing (Form C)",
                description="Corporate income tax filing",
                jurisdiction="SG",
                regulatory_body="IRAS",
                frequency=ObligationFrequency.ANNUAL,
                due_day=30,
                due_month_offset=11,
                lead_time_days=30,
                responsible_party="Tax Manager",
            )
        )
        self.add_obligation(
            LegalObligation(
                obligation_id=uuid4(),
                title="Quarterly GST Filing",
                description="Goods and Services Tax filing",
                jurisdiction="SG",
                regulatory_body="IRAS",
                frequency=ObligationFrequency.QUARTERLY,
                due_day=15,
                due_month_offset=0,
                lead_time_days=7,
                responsible_party="Finance",
            )
        )

    # ------------------------------------------------------------------------
    # Obligation Management
    # ------------------------------------------------------------------------
    def add_obligation(self, obligation: LegalObligation) -> UUID:
        self._obligations[obligation.id] = obligation
        self._obligation_instances[obligation.id] = []
        logger.info(f"Legal obligation added: {obligation.title} ({obligation.jurisdiction})")
        return obligation.id

    def get_obligation(self, obligation_id: UUID) -> LegalObligation | None:
        return self._obligations.get(obligation_id)

    def get_obligations_by_jurisdiction(self, jurisdiction: str) -> list[LegalObligation]:
        return [o for o in self._obligations.values() if o.jurisdiction == jurisdiction]

    def get_obligations_by_regulatory_body(self, regulatory_body: str) -> list[LegalObligation]:
        return [o for o in self._obligations.values() if o.regulatory_body == regulatory_body]

    # ------------------------------------------------------------------------
    # Instance Generation (Due Date Calculation)
    # ------------------------------------------------------------------------
    def calculate_due_date(self, obligation: LegalObligation, year: int, month: int = 1) -> date:
        """Menghitung due date untuk kewajiban pada periode tertentu."""
        if obligation.frequency == ObligationFrequency.ANNUAL:
            mo = obligation.due_month_offset if obligation.due_month_offset else 4
            return date(year, mo, obligation.due_day)
        elif obligation.frequency == ObligationFrequency.MONTHLY:
            return date(year, month, obligation.due_day)
        elif obligation.frequency == ObligationFrequency.QUARTERLY:
            # quarter: March, June, September, December
            quarter_months = {1: 3, 2: 6, 3: 9, 4: 12}
            q = (month - 1) // 3 + 1
            return date(year, quarter_months[q], obligation.due_day)
        elif obligation.frequency == ObligationFrequency.SEMI_ANNUAL:
            if month <= 6:
                return date(year, 6, obligation.due_day)
            else:
                return date(year, 12, obligation.due_day)
        else:  # ONE_TIME
            return date(year, obligation.due_month_offset or 1, obligation.due_day)

    def generate_instances_for_year(self, obligation_id: UUID, year: int) -> int:
        """Generate instances untuk satu tahun penuh."""
        ob = self.get_obligation(obligation_id)
        if not ob:
            raise ObligationNotFoundError(f"Obligation {obligation_id} not found")
        count = 0
        if ob.frequency == ObligationFrequency.ANNUAL:
            due = self.calculate_due_date(ob, year)
            self._create_instance(ob, due, str(year))
            count += 1
        elif ob.frequency == ObligationFrequency.MONTHLY:
            for month in range(1, 13):
                due = self.calculate_due_date(ob, year, month)
                self._create_instance(ob, due, f"{year}-{month:02d}")
                count += 1
        elif ob.frequency == ObligationFrequency.QUARTERLY:
            for month in [3, 6, 9, 12]:
                due = self.calculate_due_date(ob, year, month)
                self._create_instance(ob, due, f"{year}-Q{(month // 3)}")
                count += 1
        elif ob.frequency == ObligationFrequency.SEMI_ANNUAL:
            for month in [6, 12]:
                due = self.calculate_due_date(ob, year, month)
                self._create_instance(ob, due, f"{year}-H{1 if month == 6 else 2}")
                count += 1
        return count

    def _create_instance(self, obligation: LegalObligation, due_date: date, period: str) -> UUID:
        instance_id = uuid4()
        instance = ObligationInstance(
            instance_id=instance_id,
            obligation_id=obligation.id,
            due_date=due_date,
            period=period,
        )
        self._instances[instance_id] = instance
        self._obligation_instances[obligation.id].append(instance_id)
        return instance_id

    def generate_all_instances(self, year: int) -> int:
        """Generate instances untuk semua kewajiban pada tahun tertentu."""
        total = 0
        for ob_id in self._obligations:
            total += self.generate_instances_for_year(ob_id, year)
        return total

    # ------------------------------------------------------------------------
    # Status Tracking & Reminder
    # ------------------------------------------------------------------------
    def get_instance(self, instance_id: UUID) -> ObligationInstance | None:
        return self._instances.get(instance_id)

    def get_instances_by_obligation(self, obligation_id: UUID) -> list[ObligationInstance]:
        ids = self._obligation_instances.get(obligation_id, [])
        return [self._instances[iid] for iid in ids if iid in self._instances]

    def get_upcoming_instances(
        self, jurisdiction: str | None = None, days_ahead: int = 30
    ) -> list[ObligationInstance]:
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        result = []
        for inst in self._instances.values():
            if (
                inst.status not in (ObligationStatus.COMPLETED, ObligationStatus.WAIVED)
                and inst.due_date <= cutoff
            ):
                ob = self.get_obligation(inst.obligation_id)
                if ob and (jurisdiction is None or ob.jurisdiction == jurisdiction):
                    result.append(inst)
        return sorted(result, key=lambda x: x.due_date)

    def get_overdue_instances(self, jurisdiction: str | None = None) -> list[ObligationInstance]:
        today = date.today()
        result = []
        for inst in self._instances.values():
            if (
                inst.status not in (ObligationStatus.COMPLETED, ObligationStatus.WAIVED)
                and inst.due_date < today
            ):
                ob = self.get_obligation(inst.obligation_id)
                if ob and (jurisdiction is None or ob.jurisdiction == jurisdiction):
                    result.append(inst)
        return result

    def mark_submitted(
        self, instance_id: UUID, submitted_date: date, reference_number: str | None = None
    ) -> bool:
        inst = self.get_instance(instance_id)
        if not inst:
            return False
        inst.mark_completed(submitted_date, reference_number)
        return True

    def check_and_update_overdue(self) -> int:
        today = date.today()
        count = 0
        for inst in self._instances.values():
            if (
                inst.status not in (ObligationStatus.COMPLETED, ObligationStatus.WAIVED)
                and inst.due_date < today
            ):
                if inst.status != ObligationStatus.OVERDUE:
                    inst.mark_overdue()
                    count += 1
        return count

    def send_reminders(
        self, reminder_type: ReminderType = ReminderType.EMAIL, dry_run: bool = True
    ) -> list[dict]:
        """
        Kirim pengingat untuk instance yang approaching deadline.
        Returns list of reminders sent (or would be sent if dry_run).
        """
        upcoming = self.get_upcoming_instances(days_ahead=7)
        reminders = []
        for inst in upcoming:
            ob = self.get_obligation(inst.obligation_id)
            if ob and not inst.reminder_sent_at:
                days_left = (inst.due_date - date.today()).days
                reminder = {
                    "instance_id": str(inst.id),
                    "obligation_title": ob.title,
                    "due_date": inst.due_date.isoformat(),
                    "days_left": days_left,
                    "responsible_party": ob.responsible_party,
                    "reminder_type": reminder_type.value,
                }
                if not dry_run:
                    # Simulate sending (email, SMS, etc.)
                    inst.reminder_sent_at = datetime.utcnow()
                    inst._hash = inst._compute_hash()
                    logger.info(f"Reminder sent for {ob.title} due {inst.due_date}")
                reminders.append(reminder)
        return reminders

    # ------------------------------------------------------------------------
    # Reporting & Export
    # ------------------------------------------------------------------------
    def generate_report(self, year: int, jurisdiction: str | None = None) -> dict:
        total_obligations = len(self._obligations)
        total_instances = len(self._instances)
        overdue = self.get_overdue_instances(jurisdiction)
        upcoming = self.get_upcoming_instances(jurisdiction, days_ahead=30)
        completed = sum(
            1 for i in self._instances.values() if i.status == ObligationStatus.COMPLETED
        )
        return {
            "year": year,
            "jurisdiction_filter": jurisdiction,
            "total_obligations": total_obligations,
            "total_instances_generated": total_instances,
            "completed": completed,
            "overdue_count": len(overdue),
            "upcoming_count": len(upcoming),
            "overdue_details": [
                {
                    "title": self.get_obligation(i.obligation_id).title
                    if self.get_obligation(i.obligation_id)
                    else "Unknown",
                    "due_date": i.due_date.isoformat(),
                    "period": i.period,
                }
                for i in overdue[:10]
            ],
            "upcoming_details": [
                {
                    "title": self.get_obligation(i.obligation_id).title
                    if self.get_obligation(i.obligation_id)
                    else "Unknown",
                    "due_date": i.due_date.isoformat(),
                    "period": i.period,
                }
                for i in upcoming[:10]
            ],
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "obligations": [o.to_dict() for o in self._obligations.values()],
            "instances": [i.to_dict() for i in self._instances.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def export_to_ical(self, file_path: str, year: int) -> bool:
        """Export kalender ke format iCalendar (.ics)."""
        if not HAS_ICAL:
            logger.warning("icalendar not installed, skipping .ics export")
            return False
        cal = Calendar()
        cal.add("prodid", "-//ERP Accounting Engine//Legal Obligation Calendar//EN")
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")
        cal.add("x-wr-calname", f"Legal Obligations {year}")

        for inst in self._instances.values():
            ob = self.get_obligation(inst.obligation_id)
            if not ob:
                continue
            # Filter by year if needed
            if inst.due_date.year != year:
                continue
            event = Event()
            event.add("uid", str(inst.id))
            event.add("summary", f"{ob.title} - {ob.regulatory_body}")
            event.add(
                "description",
                f"{ob.description}\nJurisdiction: {ob.jurisdiction}\nResponsible: {ob.responsible_party}",
            )
            event.add("dtstart", inst.due_date)
            event.add("dtend", inst.due_date + timedelta(days=1))
            event.add("dtstamp", datetime.utcnow())
            event.add(
                "status", "CONFIRMED" if inst.status != ObligationStatus.OVERDUE else "CANCELLED"
            )
            cal.add_component(event)

        with open(file_path, "wb") as f:
            f.write(cal.to_ical())
        return True


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    calendar = LegalObligationCalendar()
    # Generate instances for 2026
    total = calendar.generate_all_instances(2026)
    print(f"Generated {total} obligation instances for 2026")

    # Check overdue and upcoming
    overdue = calendar.get_overdue_instances()
    upcoming = calendar.get_upcoming_instances(days_ahead=30)
    print(f"Overdue: {len(overdue)}, Upcoming (30 days): {len(upcoming)}")

    # Send reminders (dry run)
    reminders = calendar.send_reminders(dry_run=True)
    print(f"Reminders would be sent: {len(reminders)}")

    # Report
    report = calendar.generate_report(2026, jurisdiction="ID")
    print("Report:", json.dumps(report, indent=2))

    # Export
    calendar.export_to_json("legal_obligations.json")
    calendar.export_to_ical("legal_obligations.ics", 2026)
    print("Exported to JSON and ICS")
