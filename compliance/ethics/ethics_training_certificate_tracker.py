#!/usr/bin/env python3
"""
Module: ethics_training_certificate_tracker.py
Layer: Compliance / Ethics

Responsibility:
    Pelacakan sertifikat pelatihan etika untuk karyawan, manajemen, dan dewan.
    Mendukung pencatatan penyelesaian pelatihan, expiry date, notifikasi kadaluwarsa,
    pengingat pelatihan ulang, dan laporan kepatuhan pelatihan etik.

Dependencies:
    - datetime, uuid, enum, typing, hashlib, json, logging, threading

Audit:
    Setiap penambahan, pembaruan, atau pencabutan sertifikat dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class TrainingType(Enum):
    CODE_OF_CONDUCT = "code_of_conduct"
    ANTI_BRIBERY = "anti_bribery"
    CONFLICT_OF_INTEREST = "conflict_of_interest"
    DATA_PRIVACY = "data_privacy"
    INSIDER_TRADING = "insider_trading"
    WHISTLEBLOWER = "whistleblower"
    FINANCIAL_ETHICS = "financial_ethics"
    LEADERSHIP_ETHICS = "leadership_ethics"


class TrainingStatus(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    PENDING_RENEWAL = "pending_renewal"


# ============================================================================
# Data Classes
# ============================================================================
class TrainingCertificate:
    def __init__(
        self,
        certificate_id: UUID,
        employee_id: UUID,
        employee_name: str,
        training_type: TrainingType,
        training_name: str,
        completion_date: date,
        expiry_date: date | None,
        score: int,
        provider: str,
        certificate_url: str | None = None,
        status: TrainingStatus = TrainingStatus.ACTIVE,
        verified_by: UUID | None = None,
    ):
        self.id = certificate_id
        self.employee_id = employee_id
        self.employee_name = employee_name
        self.training_type = training_type
        self.training_name = training_name
        self.completion_date = completion_date
        self.expiry_date = expiry_date
        self.score = score
        self.provider = provider
        self.certificate_url = certificate_url
        self.status = status
        self.verified_by = verified_by
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "certificate_id": str(self.id),
            "employee_id": str(self.employee_id),
            "training_type": self.training_type.value,
            "completion_date": self.completion_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "status": self.status.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def is_valid(self, reference_date: date | None = None) -> bool:
        ref = reference_date or date.today()
        return self.status == TrainingStatus.ACTIVE and (
            self.expiry_date is None or self.expiry_date >= ref
        )

    def renew(
        self,
        new_completion_date: date,
        new_expiry_date: date | None,
        new_score: int,
        renewed_by: UUID,
    ) -> None:
        old_hash = self._hash
        self.completion_date = new_completion_date
        self.expiry_date = new_expiry_date
        self.score = new_score
        self.status = TrainingStatus.ACTIVE
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Certificate {self.id} renewed. Old hash: {old_hash}, new hash: {self._hash}")

    def revoke(self, revoked_by: UUID, reason: str) -> None:
        self.status = TrainingStatus.REVOKED
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.warning(f"Certificate {self.id} revoked by {revoked_by}: {reason}")

    def to_dict(self) -> dict:
        return {
            "certificate_id": str(self.id),
            "employee_id": str(self.employee_id),
            "employee_name": self.employee_name,
            "training_type": self.training_type.value,
            "training_name": self.training_name,
            "completion_date": self.completion_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "score": self.score,
            "provider": self.provider,
            "status": self.status.value,
            "verified_by": str(self.verified_by) if self.verified_by else None,
            "hash": self._hash,
        }


# ============================================================================
# EthicsTrainingCertificateTracker Core
# ============================================================================
class EthicsTrainingCertificateTracker:
    """
    Tracker untuk sertifikat pelatihan etika.
    """

    def __init__(self, enable_expiry_monitor: bool = True, expiry_check_interval_hours: int = 24):
        self._certificates: dict[UUID, TrainingCertificate] = {}
        self._employee_certs: dict[UUID, list[UUID]] = {}  # employee_id -> list of cert ids
        self._enable_monitor = enable_expiry_monitor
        self._monitor_thread: threading.Thread | None = None
        self._expiry_callbacks: list[Callable[[TrainingCertificate], None]] = []
        if enable_expiry_monitor:
            self._start_monitor(expiry_check_interval_hours)

    def _start_monitor(self, interval_hours: int) -> None:
        def monitor():
            while self._enable_monitor:
                self._check_expired_certificates()
                time.sleep(interval_hours * 3600)

        self._monitor_thread = threading.Thread(target=monitor, daemon=True)
        self._monitor_thread.start()

    def register_expiry_callback(self, callback: Callable[[TrainingCertificate], None]) -> None:
        self._expiry_callbacks.append(callback)

    def _check_expired_certificates(self) -> None:
        today = date.today()
        for cert in self._certificates.values():
            if (
                cert.status == TrainingStatus.ACTIVE
                and cert.expiry_date
                and cert.expiry_date < today
            ):
                cert.status = TrainingStatus.EXPIRED
                cert._hash = cert._compute_hash()
                logger.info(f"Certificate {cert.id} for employee {cert.employee_id} expired")
                for cb in self._expiry_callbacks:
                    try:
                        cb(cert)
                    except Exception as e:
                        logger.error(f"Expiry callback failed: {e}")

    def add_certificate(
        self,
        employee_id: UUID,
        employee_name: str,
        training_type: TrainingType,
        training_name: str,
        completion_date: date,
        expiry_date: date | None,
        score: int,
        provider: str,
        certificate_url: str | None = None,
        verified_by: UUID | None = None,
    ) -> UUID:
        cert_id = uuid4()
        cert = TrainingCertificate(
            certificate_id=cert_id,
            employee_id=employee_id,
            employee_name=employee_name,
            training_type=training_type,
            training_name=training_name,
            completion_date=completion_date,
            expiry_date=expiry_date,
            score=score,
            provider=provider,
            certificate_url=certificate_url,
            verified_by=verified_by,
        )
        self._certificates[cert_id] = cert
        if employee_id not in self._employee_certs:
            self._employee_certs[employee_id] = []
        self._employee_certs[employee_id].append(cert_id)
        logger.info(f"Certificate {cert_id} added for {employee_name} ({training_type.value})")
        return cert_id

    def get_certificate(self, certificate_id: UUID) -> TrainingCertificate | None:
        return self._certificates.get(certificate_id)

    def get_employee_certificates(self, employee_id: UUID) -> list[TrainingCertificate]:
        cert_ids = self._employee_certs.get(employee_id, [])
        return [self._certificates[cid] for cid in cert_ids if cid in self._certificates]

    def get_valid_certificates(
        self, employee_id: UUID, training_type: TrainingType | None = None
    ) -> list[TrainingCertificate]:
        certs = self.get_employee_certificates(employee_id)
        valid = [c for c in certs if c.is_valid()]
        if training_type:
            valid = [c for c in valid if c.training_type == training_type]
        return valid

    def has_required_training(self, employee_id: UUID, required_training: TrainingType) -> bool:
        valid = self.get_valid_certificates(employee_id, required_training)
        return len(valid) > 0

    def get_expiring_soon(self, days_threshold: int = 30) -> list[TrainingCertificate]:
        today = date.today()
        threshold = today + timedelta(days=days_threshold)
        return [
            c
            for c in self._certificates.values()
            if c.status == TrainingStatus.ACTIVE
            and c.expiry_date
            and today <= c.expiry_date <= threshold
        ]

    def get_expired(self) -> list[TrainingCertificate]:
        today = date.today()
        return [
            c
            for c in self._certificates.values()
            if c.status == TrainingStatus.ACTIVE and c.expiry_date and c.expiry_date < today
        ]

    def renew_certificate(
        self,
        certificate_id: UUID,
        new_completion_date: date,
        new_expiry_date: date | None,
        new_score: int,
        renewed_by: UUID,
    ) -> bool:
        cert = self.get_certificate(certificate_id)
        if not cert:
            return False
        cert.renew(new_completion_date, new_expiry_date, new_score, renewed_by)
        return True

    def revoke_certificate(self, certificate_id: UUID, revoked_by: UUID, reason: str) -> bool:
        cert = self.get_certificate(certificate_id)
        if not cert:
            return False
        cert.revoke(revoked_by, reason)
        return True

    def get_employee_compliance_summary(
        self, employee_id: UUID, required_trainings: list[TrainingType]
    ) -> dict:
        valid = self.get_valid_certificates(employee_id)
        missing = [t for t in required_trainings if not self.has_required_training(employee_id, t)]
        return {
            "employee_id": str(employee_id),
            "completed_count": len(valid),
            "missing_trainings": [t.value for t in missing],
            "compliant": len(missing) == 0,
            "expiring_soon": [
                c.to_dict() for c in self.get_expiring_soon() if c.employee_id == employee_id
            ],
        }

    def generate_report(self) -> dict:
        total_certs = len(self._certificates)
        active = len([c for c in self._certificates.values() if c.status == TrainingStatus.ACTIVE])
        expired = len(self.get_expired())
        expiring_soon = len(self.get_expiring_soon())
        by_type = {
            t.value: len([c for c in self._certificates.values() if c.training_type == t])
            for t in TrainingType
        }
        unique_employees = len(self._employee_certs)
        return {
            "total_certificates": total_certs,
            "active_certificates": active,
            "expired_certificates": expired,
            "expiring_soon": expiring_soon,
            "by_training_type": by_type,
            "employees_trained": unique_employees,
            "generated_at": datetime.utcnow().isoformat(),
        }

    def to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "certificates": [c.to_dict() for c in self._certificates.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    tracker = EthicsTrainingCertificateTracker(enable_expiry_monitor=False)
    emp_id = uuid4()
    cert_id = tracker.add_certificate(
        employee_id=emp_id,
        employee_name="Jane Smith",
        training_type=TrainingType.CODE_OF_CONDUCT,
        training_name="Code of Conduct 2025",
        completion_date=date(2025, 1, 15),
        expiry_date=date(2026, 1, 15),
        score=95,
        provider="Ethics Training Inc.",
        certificate_url="s3://certs/jane_code.pdf",
    )
    print(f"Added certificate: {cert_id}")
    print(f"Valid: {tracker.has_required_training(emp_id, TrainingType.CODE_OF_CONDUCT)}")
    print(f"Expiring soon: {len(tracker.get_expiring_soon(30))}")
    tracker.to_json("ethics_training.json")
