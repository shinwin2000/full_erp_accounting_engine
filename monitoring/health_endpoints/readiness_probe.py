#!/usr/bin/env python3
"""
Module: readiness_probe.py
Layer: Monitoring / Health Endpoints

Responsibility:
    Menyediakan endpoint /ready untuk mengecek apakah aplikasi siap menerima traffic.
    Memeriksa dependencies: database, cache (Redis), message broker (Kafka), event store, dll.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any


class DependencyStatus(Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class DependencyCheck:
    def __init__(self, name: str, check_func: Callable[[], bool], timeout_seconds: float = 5.0):
        self.name = name
        self.check_func = check_func
        self.timeout = timeout_seconds
        self.last_status = DependencyStatus.UNKNOWN
        self.last_check_time: datetime | None = None
        self.error_message: str | None = None

    def run(self) -> DependencyStatus:
        """Jalankan pengecekan dependency."""
        start = time.time()
        try:
            result = self.check_func()
            elapsed = time.time() - start
            self.last_check_time = datetime.utcnow()
            if result:
                self.last_status = DependencyStatus.UP
                self.error_message = None
            else:
                self.last_status = DependencyStatus.DOWN
                self.error_message = "Check returned False"
            return self.last_status
        except Exception as e:
            elapsed = time.time() - start
            self.last_status = DependencyStatus.DOWN
            self.error_message = str(e)
            return self.last_status


class ReadinessProbe:
    """
    Readiness probe untuk mengecek dependencies aplikasi.
    """

    def __init__(self):
        self._checks: list[DependencyCheck] = []
        self._init_default_checks()

    def _init_default_checks(self):
        """Inisialisasi pengecekan default untuk ERP Accounting Engine."""
        # Database PostgreSQL
        self.add_check(
            DependencyCheck(
                name="postgresql",
                check_func=self._check_postgresql,
            )
        )
        # Redis cache
        self.add_check(
            DependencyCheck(
                name="redis",
                check_func=self._check_redis,
            )
        )
        # Kafka message broker
        self.add_check(
            DependencyCheck(
                name="kafka",
                check_func=self._check_kafka,
            )
        )
        # Event Store (DynamoDB / custom)
        self.add_check(
            DependencyCheck(
                name="event_store",
                check_func=self._check_event_store,
            )
        )
        # Coretax API (opsional)
        self.add_check(
            DependencyCheck(
                name="coretax_api",
                check_func=self._check_coretax_api,
            )
        )

    def add_check(self, check: DependencyCheck) -> None:
        """Tambahkan dependency check kustom."""
        self._checks.append(check)

    def _check_postgresql(self) -> bool:
        """Cek koneksi ke PostgreSQL."""
        try:
            # Simulasi: di real implementation, gunakan sqlalchemy engine
            # engine = get_db_engine()
            # with engine.connect() as conn:
            #     conn.execute("SELECT 1")
            import random

            return random.choice([True, False])  # Simulasi, replace dengan kode nyata
        except Exception:
            return False

    def _check_redis(self) -> bool:
        """Cek koneksi ke Redis."""
        try:
            # Simulasi: di real implementation, gunakan redis client
            # r = redis.Redis(...)
            # r.ping()
            import random

            return random.choice([True, False])
        except Exception:
            return False

    def _check_kafka(self) -> bool:
        """Cek koneksi ke Kafka."""
        try:
            # Simulasi: di real implementation, gunakan kafka client
            # from kafka import KafkaProducer
            # producer = KafkaProducer(bootstrap_servers='...')
            # producer.partitions_for('test')
            import random

            return random.choice([True, False])
        except Exception:
            return False

    def _check_event_store(self) -> bool:
        """Cek koneksi ke Event Store (DynamoDB atau S3)."""
        try:
            import random

            return random.choice([True, False])
        except Exception:
            return False

    def _check_coretax_api(self) -> bool:
        """Cek kesehatan Coretax DJP API (opsional)."""
        try:
            import requests

            resp = requests.get("https://api.coretax.djp.go.id/v1/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    def run_all_checks(self) -> dict[str, Any]:
        """Jalankan semua pengecekan dan kembalikan hasil."""
        results = {}
        all_up = True
        any_down = False
        for check in self._checks:
            status = check.run()
            results[check.name] = {
                "status": status.value,
                "error": check.error_message,
                "last_check": check.last_check_time.isoformat() if check.last_check_time else None,
            }
            if status == DependencyStatus.DOWN:
                all_up = False
                any_down = True
            elif status == DependencyStatus.DEGRADED:
                all_up = False

        overall = "ready" if all_up else "not_ready"
        return {
            "status": overall,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "dependencies": results,
            "all_dependencies_up": all_up,
            "has_failure": any_down,
        }

    def is_ready(self) -> bool:
        """Quick check: apakah semua dependencies UP."""
        results = self.run_all_checks()
        return results["all_dependencies_up"]


# Singleton instance
_default_probe = ReadinessProbe()


def readiness_probe() -> dict[str, Any]:
    """Endpoint /ready untuk FastAPI/Flask."""
    return _default_probe.run_all_checks()


def is_ready() -> bool:
    """Cepat cek apakah aplikasi siap menerima traffic."""
    return _default_probe.is_ready()
