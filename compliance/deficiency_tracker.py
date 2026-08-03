#!/usr/bin/env python3
"""
Module: deficiency_tracker.py
Layer: Compliance

Responsibility:
    Pelacakan kekurangan atau kegagalan kepatuhan (compliance deficiencies).
    Mendukung pembuatan, assignment, status tracking (open, in_progress, under_review,
    remediated, closed, waived), prioritas (low, medium, high, critical),
    remediasi dengan evidence attachment, SLA monitoring (due date), history log,
    dan export report untuk audit committee.

Dependencies:
    - datetime, uuid, enum, typing, json, hashlib, logging
    - optional: requests untuk integrasi ticketing system (Jira, ServiceNow)

Audit:
    Setiap perubahan status deficiency dicatat dengan timestamp dan user.
    Hash integrity untuk setiap deficiency record.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from enum import Enum
from uuid import UUID, uuid4

# Optional integration with external ticketing
try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class DeficiencySeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DeficiencyStatus(Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    UNDER_REVIEW = "under_review"
    REMEDIATED = "remediated"
    CLOSED = "closed"
    WAIVED = "waived"


class DeficiencyCategory(Enum):
    ACCOUNTING_POLICY = "accounting_policy"
    INTERNAL_CONTROL = "internal_control"
    TAX_COMPLIANCE = "tax_compliance"
    DATA_PRIVACY = "data_privacy"
    SECURITY = "security"
    REGULATORY_REPORTING = "regulatory_reporting"
    ETHICS = "ethics"
    AML = "aml"
    SOX = "sox"
    PSAK = "psak"
    IFRS = "ifrs"
    OJK = "ojk"
    CORETAX = "coretax"
    OTHER = "other"


class DeficiencyAction(Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    STATUS_CHANGED = "status_changed"
    DUE_DATE_CHANGED = "due_date_changed"
    REMEDIATION_PLAN_UPDATED = "remediation_plan_updated"
    EVIDENCE_ATTACHED = "evidence_attached"
    COMMENT_ADDED = "comment_added"
    ESCALATED = "escalated"
    SLA_BREACH = "sla_breach"
    CLOSED = "closed"


# ============================================================================
# Exceptions
# ============================================================================
class DeficiencyError(Exception):
    """Base exception untuk deficiency tracker."""

    pass


class DeficiencyNotFoundError(DeficiencyError):
    """Deficiency tidak ditemukan."""

    pass


class InvalidStatusTransitionError(DeficiencyError):
    """Transisi status tidak valid."""

    pass


class EscalationError(DeficiencyError):
    """Error saat eskalasi."""

    pass


# ============================================================================
# Data Classes
# ============================================================================
class DeficiencyHistoryEntry:
    """Entri histori perubahan deficiency."""

    def __init__(
        self,
        action: DeficiencyAction,
        performed_by: UUID,
        timestamp: datetime,
        old_value: str | None = None,
        new_value: str | None = None,
        comment: str | None = None,
    ):
        self.id = uuid4()
        self.action = action
        self.performed_by = performed_by
        self.timestamp = timestamp
        self.old_value = old_value
        self.new_value = new_value
        self.comment = comment

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "action": self.action.value,
            "performed_by": str(self.performed_by),
            "timestamp": self.timestamp.isoformat(),
            "old_value": self.old_value,
            "new_value": self.new_value,
            "comment": self.comment,
        }


class EvidenceAttachment:
    """Lampiran bukti remediasi."""

    def __init__(
        self,
        attachment_id: UUID,
        filename: str,
        file_url: str,
        uploaded_by: UUID,
        uploaded_at: datetime,
        file_hash: str | None = None,
        file_size_bytes: int | None = None,
    ):
        self.id = attachment_id
        self.filename = filename
        self.file_url = file_url
        self.uploaded_by = uploaded_by
        self.uploaded_at = uploaded_at
        self.file_hash = file_hash
        self.file_size_bytes = file_size_bytes

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "filename": self.filename,
            "file_url": self.file_url,
            "uploaded_by": str(self.uploaded_by),
            "uploaded_at": self.uploaded_at.isoformat(),
            "file_hash": self.file_hash,
            "file_size_bytes": self.file_size_bytes,
        }


class Comment:
    """Komentar pada deficiency."""

    def __init__(self, comment_id: UUID, author_id: UUID, content: str, timestamp: datetime):
        self.id = comment_id
        self.author_id = author_id
        self.content = content
        self.timestamp = timestamp

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "author_id": str(self.author_id),
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }


class Deficiency:
    """
    Kekurangan kepatuhan tunggal.
    Memiliki lifecycle status, prioritas, owner, due date, remediasi, evidence.
    """

    def __init__(
        self,
        deficiency_id: UUID,
        title: str,
        description: str,
        category: DeficiencyCategory,
        regulation: str,  # e.g., "PSAK 72", "SOX 404", "GDPR Art. 17"
        severity: DeficiencySeverity,
        discovered_date: date,
        discovered_by: UUID,
        owner_id: UUID | None = None,
        due_date: date | None = None,
        status: DeficiencyStatus = DeficiencyStatus.OPEN,
        remediation_plan: str | None = None,
        root_cause: str | None = None,
        impact_assessment: str | None = None,
        external_ticket_id: str | None = None,
    ):
        self.id = deficiency_id
        self.title = title
        self.description = description
        self.category = category
        self.regulation = regulation
        self.severity = severity
        self.discovered_date = discovered_date
        self.discovered_by = discovered_by
        self.owner_id = owner_id
        self.due_date = due_date
        self.status = status
        self.remediation_plan = remediation_plan
        self.root_cause = root_cause
        self.impact_assessment = impact_assessment
        self.external_ticket_id = external_ticket_id
        self.created_at = datetime.utcnow()
        self.updated_at: datetime | None = None
        self.closed_at: datetime | None = None
        self.history: list[DeficiencyHistoryEntry] = []
        self.attachments: list[EvidenceAttachment] = []
        self.comments: list[Comment] = []
        self.escalation_level: int = 0
        self.sla_breach_notified: bool = False
        self._hash: str | None = None

    def _compute_hash(self) -> str:
        """Hitung hash integrity dari deficiency record."""
        data = {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "regulation": self.regulation,
            "severity": self.severity.value,
            "status": self.status.value,
            "owner_id": str(self.owner_id) if self.owner_id else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "remediation_plan": self.remediation_plan,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def refresh_hash(self) -> str:
        self._hash = self._compute_hash()
        return self._hash

    def add_history_entry(
        self,
        action: DeficiencyAction,
        performed_by: UUID,
        old_value: str | None = None,
        new_value: str | None = None,
        comment: str | None = None,
    ) -> None:
        entry = DeficiencyHistoryEntry(
            action, performed_by, datetime.utcnow(), old_value, new_value, comment
        )
        self.history.append(entry)
        self.updated_at = datetime.utcnow()
        self.refresh_hash()

    def assign_owner(self, owner_id: UUID, assigned_by: UUID) -> None:
        old = str(self.owner_id) if self.owner_id else None
        self.owner_id = owner_id
        self.add_history_entry(DeficiencyAction.ASSIGNED, assigned_by, old, str(owner_id))

    def update_status(
        self, new_status: DeficiencyStatus, changed_by: UUID, comment: str | None = None
    ) -> None:
        if not self._is_valid_transition(self.status, new_status):
            raise InvalidStatusTransitionError(
                f"Cannot transition from {self.status.value} to {new_status.value}"
            )
        old = self.status.value
        self.status = new_status
        self.add_history_entry(
            DeficiencyAction.STATUS_CHANGED, changed_by, old, new_status.value, comment
        )
        if new_status == DeficiencyStatus.CLOSED:
            self.closed_at = datetime.utcnow()

    def _is_valid_transition(self, current: DeficiencyStatus, new: DeficiencyStatus) -> bool:
        """Definisi state machine transisi yang valid."""
        valid = {
            DeficiencyStatus.OPEN: [
                DeficiencyStatus.IN_PROGRESS,
                DeficiencyStatus.WAIVED,
                DeficiencyStatus.CLOSED,
            ],
            DeficiencyStatus.IN_PROGRESS: [
                DeficiencyStatus.UNDER_REVIEW,
                DeficiencyStatus.OPEN,
                DeficiencyStatus.WAIVED,
                DeficiencyStatus.CLOSED,
            ],
            DeficiencyStatus.UNDER_REVIEW: [
                DeficiencyStatus.REMEDIATED,
                DeficiencyStatus.IN_PROGRESS,
                DeficiencyStatus.OPEN,
            ],
            DeficiencyStatus.REMEDIATED: [DeficiencyStatus.CLOSED, DeficiencyStatus.UNDER_REVIEW],
            DeficiencyStatus.CLOSED: [],
            DeficiencyStatus.WAIVED: [DeficiencyStatus.CLOSED],
        }
        return new in valid.get(current, [])

    def set_remediation_plan(self, plan: str, set_by: UUID) -> None:
        old = self.remediation_plan
        self.remediation_plan = plan
        self.add_history_entry(DeficiencyAction.REMEDIATION_PLAN_UPDATED, set_by, old, plan)

    def add_evidence(self, attachment: EvidenceAttachment, added_by: UUID) -> None:
        self.attachments.append(attachment)
        self.add_history_entry(
            DeficiencyAction.EVIDENCE_ATTACHED,
            added_by,
            None,
            attachment.filename,
            f"Attachment: {attachment.filename}",
        )

    def add_comment(self, author_id: UUID, content: str) -> None:
        comment = Comment(uuid4(), author_id, content, datetime.utcnow())
        self.comments.append(comment)
        self.add_history_entry(DeficiencyAction.COMMENT_ADDED, author_id, None, None, content[:100])

    def escalate(self, escalated_by: UUID, reason: str) -> None:
        self.escalation_level += 1
        self.add_history_entry(
            DeficiencyAction.ESCALATED, escalated_by, None, str(self.escalation_level), reason
        )
        if self.escalation_level >= 3:
            self.severity = DeficiencySeverity.CRITICAL
            self.add_history_entry(
                DeficiencyAction.STATUS_CHANGED,
                escalated_by,
                None,
                "severity_critical",
                "Auto-escalated to critical",
            )

    def mark_sla_breach(self, breached_by: UUID) -> None:
        if not self.sla_breach_notified:
            self.sla_breach_notified = True
            self.add_history_entry(
                DeficiencyAction.SLA_BREACH, breached_by, None, None, "Due date missed"
            )

    def to_dict(
        self,
        include_history: bool = False,
        include_attachments: bool = False,
        include_comments: bool = False,
    ) -> dict:
        result = {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "regulation": self.regulation,
            "severity": self.severity.value,
            "discovered_date": self.discovered_date.isoformat(),
            "discovered_by": str(self.discovered_by),
            "owner_id": str(self.owner_id) if self.owner_id else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status.value,
            "remediation_plan": self.remediation_plan,
            "root_cause": self.root_cause,
            "impact_assessment": self.impact_assessment,
            "external_ticket_id": self.external_ticket_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "escalation_level": self.escalation_level,
            "sla_breach_notified": self.sla_breach_notified,
            "hash": self._hash or self.refresh_hash(),
        }
        if include_history:
            result["history"] = [h.to_dict() for h in self.history]
        if include_attachments:
            result["attachments"] = [a.to_dict() for a in self.attachments]
        if include_comments:
            result["comments"] = [c.to_dict() for c in self.comments]
        return result


# ============================================================================
# Deficiency Tracker Core
# ============================================================================
class DeficiencyTracker:
    """
    Tracker untuk deficiency kepatuhan dengan fitur lengkap:
    - CRUD deficiency
    - SLA monitoring (overdue detection)
    - Escalation otomatis
    - Export ke JSON/CSV
    - Integrasi dengan ticketing eksternal (opsional)
    - Dashboard summary
    """

    def __init__(
        self, enable_external_ticketing: bool = False, external_ticket_config: dict | None = None
    ):
        self._deficiencies: dict[UUID, Deficiency] = {}
        self._enable_external = enable_external_ticketing
        self._external_config = external_ticket_config or {}
        self._sla_check_enabled = True

    # ------------------------------------------------------------------------
    # Deficiency Management
    # ------------------------------------------------------------------------
    def add_deficiency(
        self,
        title: str,
        description: str,
        category: DeficiencyCategory,
        regulation: str,
        severity: DeficiencySeverity,
        discovered_by: UUID,
        due_date: date | None = None,
        owner_id: UUID | None = None,
        root_cause: str | None = None,
        impact_assessment: str | None = None,
        external_ticket_id: str | None = None,
    ) -> UUID:
        """Tambah deficiency baru."""
        deficiency_id = uuid4()
        deficiency = Deficiency(
            deficiency_id=deficiency_id,
            title=title,
            description=description,
            category=category,
            regulation=regulation,
            severity=severity,
            discovered_date=date.today(),
            discovered_by=discovered_by,
            owner_id=owner_id,
            due_date=due_date,
            root_cause=root_cause,
            impact_assessment=impact_assessment,
            external_ticket_id=external_ticket_id,
        )
        deficiency.add_history_entry(
            DeficiencyAction.CREATED, discovered_by, None, None, "Deficiency created"
        )
        self._deficiencies[deficiency_id] = deficiency

        # Optional: create external ticket
        if self._enable_external and not external_ticket_id:
            self._create_external_ticket(deficiency)

        # Check SLA on creation
        if due_date and due_date < date.today():
            deficiency.mark_sla_breach(discovered_by)

        logger.info(f"Deficiency created: {deficiency_id} - {title}")
        return deficiency_id

    def get_deficiency(self, deficiency_id: UUID) -> Deficiency | None:
        return self._deficiencies.get(deficiency_id)

    def update_deficiency(self, deficiency_id: UUID, **kwargs) -> None:
        deficiency = self.get_deficiency(deficiency_id)
        if not deficiency:
            raise DeficiencyNotFoundError(f"Deficiency {deficiency_id} not found")

        for key, value in kwargs.items():
            if hasattr(deficiency, key):
                old_value = getattr(deficiency, key)
                setattr(deficiency, key, value)
                deficiency.add_history_entry(
                    DeficiencyAction.COMMENT_ADDED,
                    deficiency.discovered_by,
                    str(old_value) if old_value else None,
                    str(value) if value else None,
                    f"Field {key} updated",
                )
        deficiency.updated_at = datetime.utcnow()
        deficiency.refresh_hash()

    def delete_deficiency(self, deficiency_id: UUID, deleted_by: UUID) -> bool:
        """Soft delete? Di sini kita hanya hapus dari tracker (atau bisa archive)."""
        if deficiency_id in self._deficiencies:
            deficiency = self._deficiencies[deficiency_id]
            deficiency.add_history_entry(
                DeficiencyAction.CLOSED, deleted_by, None, None, "Deficiency deleted"
            )
            del self._deficiencies[deficiency_id]
            return True
        return False

    # ------------------------------------------------------------------------
    # Query & Filter
    # ------------------------------------------------------------------------
    def get_deficiencies(
        self,
        status: list[DeficiencyStatus] | None = None,
        severity: list[DeficiencySeverity] | None = None,
        category: list[DeficiencyCategory] | None = None,
        owner_id: UUID | None = None,
        regulation: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[Deficiency]:
        result = list(self._deficiencies.values())
        if status:
            result = [d for d in result if d.status in status]
        if severity:
            result = [d for d in result if d.severity in severity]
        if category:
            result = [d for d in result if d.category in category]
        if owner_id:
            result = [d for d in result if d.owner_id == owner_id]
        if regulation:
            result = [d for d in result if regulation.lower() in d.regulation.lower()]
        if from_date:
            result = [d for d in result if d.discovered_date >= from_date]
        if to_date:
            result = [d for d in result if d.discovered_date <= to_date]
        return result

    def get_open_deficiencies(self, severity: DeficiencySeverity | None = None) -> list[Deficiency]:
        open_statuses = [
            DeficiencyStatus.OPEN,
            DeficiencyStatus.IN_PROGRESS,
            DeficiencyStatus.UNDER_REVIEW,
        ]
        result = [d for d in self._deficiencies.values() if d.status in open_statuses]
        if severity:
            result = [d for d in result if d.severity == severity]
        return result

    def get_overdue_deficiencies(self, as_of: date | None = None) -> list[Deficiency]:
        today = as_of or date.today()
        open_statuses = [
            DeficiencyStatus.OPEN,
            DeficiencyStatus.IN_PROGRESS,
            DeficiencyStatus.UNDER_REVIEW,
            DeficiencyStatus.REMEDIATED,
        ]
        result = [
            d
            for d in self._deficiencies.values()
            if d.due_date and d.due_date < today and d.status in open_statuses
        ]
        # Mark SLA breach for those not yet notified
        for d in result:
            if not d.sla_breach_notified:
                d.mark_sla_breach(UUID("00000000-0000-0000-0000-000000000000"))
        return result

    def get_by_owner(self, owner_id: UUID) -> list[Deficiency]:
        return [d for d in self._deficiencies.values() if d.owner_id == owner_id]

    def get_by_external_ticket(self, ticket_id: str) -> Deficiency | None:
        for d in self._deficiencies.values():
            if d.external_ticket_id == ticket_id:
                return d
        return None

    # ------------------------------------------------------------------------
    # SLA Monitoring & Escalation
    # ------------------------------------------------------------------------
    def check_all_sla(self) -> int:
        """Periksa semua deficiency untuk overdue, return jumlah yang overdue."""
        overdue = self.get_overdue_deficiencies()
        return len(overdue)

    def auto_escalate(self, escalation_days: int = 7) -> int:
        """Eskalasi otomatis untuk deficiency yang overdue melebihi escalation_days."""
        today = date.today()
        escalated_count = 0
        for d in self.get_overdue_deficiencies():
            if (
                d.due_date
                and (today - d.due_date).days >= escalation_days
                and d.escalation_level < 3
            ):
                d.escalate(
                    UUID("00000000-0000-0000-0000-000000000000"),
                    f"Auto-escalated after {escalation_days} days overdue",
                )
                escalated_count += 1
        return escalated_count

    def get_sla_summary(self) -> dict:
        """Ringkasan SLA compliance."""
        total = len(self._deficiencies)
        if total == 0:
            return {"total": 0}
        overdue = self.get_overdue_deficiencies()
        on_track = [
            d
            for d in self._deficiencies.values()
            if d.due_date
            and d.due_date >= date.today()
            and d.status not in [DeficiencyStatus.CLOSED, DeficiencyStatus.WAIVED]
        ]
        compliance_rate = (len(on_track) / max(len(on_track) + len(overdue), 1)) * 100
        return {
            "total_deficiencies": total,
            "overdue_count": len(overdue),
            "on_track_count": len(on_track),
            "sla_compliance_rate": round(compliance_rate, 2),
            "escalated_count": sum(
                1 for d in self._deficiencies.values() if d.escalation_level > 0
            ),
        }

    # ------------------------------------------------------------------------
    # External Ticketing Integration (Optional)
    # ------------------------------------------------------------------------
    def _create_external_ticket(self, deficiency: Deficiency) -> bool:
        if not HAS_REQUESTS or not self._enable_external:
            return False
        try:
            config = self._external_config
            url = config.get("url")
            api_key = config.get("api_key")
            project = config.get("project", "COMPLIANCE")
            if not url:
                return False
            payload = {
                "summary": f"[Compliance] {deficiency.title}",
                "description": deficiency.description,
                "priority": self._map_severity_to_priority(deficiency.severity),
                "project": project,
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            response = requests.post(
                f"{url}/rest/api/2/issue", json=payload, headers=headers, timeout=10
            )
            if response.status_code == 201:
                ticket_data = response.json()
                deficiency.external_ticket_id = ticket_data.get("key")
                deficiency.add_history_entry(
                    DeficiencyAction.COMMENT_ADDED,
                    deficiency.discovered_by,
                    None,
                    ticket_data.get("key"),
                    "External ticket created",
                )
                return True
        except Exception as e:
            logger.error(f"Failed to create external ticket: {e}")
        return False

    def _map_severity_to_priority(self, severity: DeficiencySeverity) -> str:
        mapping = {
            DeficiencySeverity.LOW: "Low",
            DeficiencySeverity.MEDIUM: "Medium",
            DeficiencySeverity.HIGH: "High",
            DeficiencySeverity.CRITICAL: "Highest",
        }
        return mapping.get(severity, "Medium")

    def sync_external_status(self, deficiency_id: UUID) -> bool:
        """Sinkronisasi status dari external ticketing system (opsional)."""
        if not self._enable_external:
            return False
        deficiency = self.get_deficiency(deficiency_id)
        # Return True only if deficiency exists and has an external ticket id
        return deficiency is not None and deficiency.external_ticket_id is not None

    # ------------------------------------------------------------------------
    # Reporting & Export
    # ------------------------------------------------------------------------
    def generate_summary(self) -> dict:
        total = len(self._deficiencies)
        open_deficiencies = self.get_open_deficiencies()
        overdue = self.get_overdue_deficiencies()
        return {
            "total_deficiencies": total,
            "open_deficiencies": len(open_deficiencies),
            "closed_deficiencies": len(
                [d for d in self._deficiencies.values() if d.status == DeficiencyStatus.CLOSED]
            ),
            "overdue_deficiencies": len(overdue),
            "by_severity": {
                "critical": len(
                    [
                        d
                        for d in self._deficiencies.values()
                        if d.severity == DeficiencySeverity.CRITICAL
                    ]
                ),
                "high": len(
                    [
                        d
                        for d in self._deficiencies.values()
                        if d.severity == DeficiencySeverity.HIGH
                    ]
                ),
                "medium": len(
                    [
                        d
                        for d in self._deficiencies.values()
                        if d.severity == DeficiencySeverity.MEDIUM
                    ]
                ),
                "low": len(
                    [d for d in self._deficiencies.values() if d.severity == DeficiencySeverity.LOW]
                ),
            },
            "by_category": {
                cat.value: len([d for d in self._deficiencies.values() if d.category == cat])
                for cat in DeficiencyCategory
            },
            "by_status": {
                status.value: len([d for d in self._deficiencies.values() if d.status == status])
                for status in DeficiencyStatus
            },
        }

    def export_to_json(self, file_path: str | None = None) -> str:
        """Export semua deficiency ke JSON."""
        data = {
            "export_timestamp": datetime.utcnow().isoformat(),
            "deficiencies": [
                d.to_dict(include_history=True, include_attachments=True, include_comments=True)
                for d in self._deficiencies.values()
            ],
            "summary": self.generate_summary(),
        }
        json_str = json.dumps(data, indent=2, default=str)
        if file_path:
            with open(file_path, "w") as f:
                f.write(json_str)
        return json_str

    def export_to_csv(self, file_path: str) -> None:
        """Export ke CSV untuk analisis di Excel."""
        import csv

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "ID",
                    "Title",
                    "Category",
                    "Regulation",
                    "Severity",
                    "Status",
                    "Discovered Date",
                    "Due Date",
                    "Owner",
                    "Remediation Plan",
                    "Closed Date",
                ]
            )
            for d in self._deficiencies.values():
                writer.writerow(
                    [
                        str(d.id),
                        d.title,
                        d.category.value,
                        d.regulation,
                        d.severity.value,
                        d.status.value,
                        d.discovered_date.isoformat(),
                        d.due_date.isoformat() if d.due_date else "",
                        str(d.owner_id) if d.owner_id else "",
                        d.remediation_plan or "",
                        d.closed_at.isoformat() if d.closed_at else "",
                    ]
                )

    # ------------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------------
    def archive_closed_deficiencies(self, older_than_days: int = 90) -> int:
        """Archive deficiency yang sudah closed lebih dari older_than_days hari."""
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        to_archive = []
        for d in self._deficiencies.values():
            if d.status == DeficiencyStatus.CLOSED and d.closed_at and d.closed_at < cutoff:
                to_archive.append(d.id)
        for did in to_archive:
            del self._deficiencies[did]
        return len(to_archive)

    def get_audit_trail(self, deficiency_id: UUID) -> list[dict]:
        deficiency = self.get_deficiency(deficiency_id)
        if not deficiency:
            return []
        return [h.to_dict() for h in deficiency.history]

    def get_all_audit_trails(self) -> dict[UUID, list[dict]]:
        return {did: [h.to_dict() for h in d.history] for did, d in self._deficiencies.items()}


# ============================================================================
# Demo & Contoh Penggunaan
# ============================================================================
if __name__ == "__main__":
    tracker = DeficiencyTracker()

    # Tambahkan beberapa deficiency
    user_id = UUID("12345678-1234-1234-1234-123456789abc")
    d1_id = tracker.add_deficiency(
        title="PSAK 72 Revenue Recognition Gap",
        description="Contract modifications not properly accounted for variable consideration",
        category=DeficiencyCategory.PSAK,
        regulation="PSAK 72 (IFRS 15)",
        severity=DeficiencySeverity.HIGH,
        discovered_by=user_id,
        due_date=date.today() + timedelta(days=30),
        owner_id=user_id,
        root_cause="Lack of training on variable consideration",
    )
    d2_id = tracker.add_deficiency(
        title="GDPR Data Retention Policy",
        description="No automated deletion of personal data after retention period",
        category=DeficiencyCategory.DATA_PRIVACY,
        regulation="GDPR Article 17",
        severity=DeficiencySeverity.CRITICAL,
        discovered_by=user_id,
        due_date=date.today() - timedelta(days=5),  # sudah overdue
        owner_id=user_id,
    )
    d3_id = tracker.add_deficiency(
        title="SOX Access Control Review",
        description="User access review not performed quarterly",
        category=DeficiencyCategory.SOX,
        regulation="SOX 404",
        severity=DeficiencySeverity.MEDIUM,
        discovered_by=user_id,
        due_date=date.today() + timedelta(days=60),
        owner_id=user_id,
    )

    # Update status deficiency
    d1 = tracker.get_deficiency(d1_id)
    if d1:
        d1.update_status(DeficiencyStatus.IN_PROGRESS, user_id, "Started remediation")
        d1.set_remediation_plan(
            "Train accounting team on PSAK 72 and update contract policy", user_id
        )

    # Cek overdue
    overdue = tracker.get_overdue_deficiencies()
    print(f"Overdue deficiencies: {len(overdue)}")
    for od in overdue:
        print(f"  - {od.title} (due {od.due_date})")

    # Auto escalate
    escalated = tracker.auto_escalate(escalation_days=3)
    print(f"Escalated: {escalated}")

    # Summary
    summary = tracker.generate_summary()
    print("\nSummary:")
    print(json.dumps(summary, indent=2))

    # Export
    tracker.export_to_json("deficiencies_export.json")
    tracker.export_to_csv("deficiencies_export.csv")
    print("Exported to JSON and CSV")
