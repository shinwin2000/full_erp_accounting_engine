#!/usr/bin/env python3
"""
Module: slo_reporter_monthly.py
Layer: Monitoring / Health Endpoints

Responsibility:
    Menghitung SLO (Service Level Objectives) bulanan berdasarkan metrik yang dikumpulkan.
    Menghasilkan laporan yang dapat dikirim ke email atau disimpan sebagai file.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any


class SLOMetric(Enum):
    AVAILABILITY = "availability"
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"


@dataclass
class SLOReport:
    period: str  # YYYY-MM
    metric_name: str
    target_value: Decimal
    actual_value: Decimal
    met: bool
    details: dict[str, Any]

    __slots__ = ("actual_value", "details", "met", "metric_name", "period", "target_value")

    def __post_init__(self) -> None:
        """Validasi bahwa nilai tidak negatif (opsional untuk metrik)."""
        if self.target_value < Decimal(0):
            raise ValueError("target_value cannot be negative")
        if self.actual_value < Decimal(0):
            raise ValueError("actual_value cannot be negative")


class SLOReporter:
    """
    Monthly SLO reporter untuk ERP Accounting Engine.
    Menghitung persentase ketersediaan, error rate, latency p99, dll.
    """

    __slots__ = ("_reports", "period")

    def __init__(self, period: str | None = None) -> None:
        self.period = period or datetime.now(UTC).strftime("%Y-%m")
        self._reports: list[SLOReport] = []

    def _get_month_start_end(self) -> tuple[datetime, datetime]:
        """Mendapatkan start dan end datetime untuk periode bulan."""
        year, month = map(int, self.period.split("-"))
        start = datetime(year, month, 1, 0, 0, 0, tzinfo=UTC)
        if month == 12:
            end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=UTC) - timedelta(seconds=1)
        else:
            end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=UTC) - timedelta(seconds=1)
        return start, end

    def _query_metric_from_prometheus(self, query: str) -> float:
        """
        Query metrik dari Prometheus (simulasi).
        Di real implementation, gunakan requests ke Prometheus API.
        """
        # Simulasi nilai untuk demo
        if "up" in query:
            return random.uniform(99.5, 100.0)
        if "duration" in query:
            return random.uniform(0.05, 0.3)
        if "error" in query:
            return random.uniform(0.1, 0.5)
        return random.uniform(80, 100)

    def calculate_availability(self) -> SLOReport:
        """Hitung availability (uptime) API selama sebulan."""
        uptime_percent = self._query_metric_from_prometheus("avg_over_time(up[30d]) * 100")
        target = Decimal("99.9")
        report = SLOReport(
            period=self.period,
            metric_name="availability",
            target_value=target,
            actual_value=Decimal(str(uptime_percent)),
            met=Decimal(str(uptime_percent)) >= target,
            details={"target": f"{target}%", "description": "API uptime"},
        )
        self._reports.append(report)
        return report

    def calculate_latency_p99(self) -> SLOReport:
        """Hitung latency p99 untuk HTTP requests."""
        p99_latency = self._query_metric_from_prometheus("p99_latency")
        target = Decimal("0.5")  # 500ms
        report = SLOReport(
            period=self.period,
            metric_name="latency_p99",
            target_value=target,
            actual_value=Decimal(str(p99_latency)),
            met=Decimal(str(p99_latency)) <= target,
            details={"unit": "seconds", "target": f"{target}s"},
        )
        self._reports.append(report)
        return report

    def calculate_error_rate(self) -> SLOReport:
        """Hitung error rate (status 5xx) API."""
        error_rate = self._query_metric_from_prometheus("error_rate")
        target = Decimal("0.1")  # 0.1%
        report = SLOReport(
            period=self.period,
            metric_name="error_rate",
            target_value=target,
            actual_value=Decimal(str(error_rate)),
            met=Decimal(str(error_rate)) <= target,
            details={"unit": "%", "target": f"{target}%"},
        )
        self._reports.append(report)
        return report

    def calculate_coretax_success_rate(self) -> SLOReport:
        """Hitung success rate Coretax API."""
        success_rate = self._query_metric_from_prometheus("coretax_success_rate")
        target = Decimal("99.5")
        report = SLOReport(
            period=self.period,
            metric_name="coretax_api_success_rate",
            target_value=target,
            actual_value=Decimal(str(success_rate)),
            met=Decimal(str(success_rate)) >= target,
            details={"unit": "%", "target": f"{target}%"},
        )
        self._reports.append(report)
        return report

    def calculate_journal_posting_throughput(self) -> SLOReport:
        """Hitung throughput journal posting per second."""
        throughput = self._query_metric_from_prometheus("journal_postings_rate")
        target = Decimal("100")  # 100 postings per second
        report = SLOReport(
            period=self.period,
            metric_name="journal_posting_throughput",
            target_value=target,
            actual_value=Decimal(str(throughput)),
            met=Decimal(str(throughput)) >= target,
            details={"unit": "postings/sec", "target": f"{target} postings/sec"},
        )
        self._reports.append(report)
        return report

    def generate_all_reports(self) -> list[SLOReport]:
        """Generate semua SLO report."""
        self.calculate_availability()
        self.calculate_latency_p99()
        self.calculate_error_rate()
        self.calculate_coretax_success_rate()
        self.calculate_journal_posting_throughput()
        return self._reports

    def generate_summary(self) -> dict[str, Any]:
        """Generate ringkasan SLO compliance."""
        if not self._reports:
            self.generate_all_reports()
        total_metrics = len(self._reports)
        met_count = sum(1 for r in self._reports if r.met)
        overall_compliant = (met_count / total_metrics) >= 0.9  # 90% of SLOs met

        return {
            "period": self.period,
            "total_slo_metrics": total_metrics,
            "slo_met_count": met_count,
            "slo_met_percentage": round(met_count / total_metrics * 100, 2),
            "overall_compliant": overall_compliant,
            "reports": [
                {
                    "metric": r.metric_name,
                    "target": float(r.target_value),
                    "actual": float(r.actual_value),
                    "met": r.met,
                    "details": r.details,
                }
                for r in self._reports
            ],
        }

    def to_json(self) -> str:
        """Mengembalikan laporan sebagai JSON string."""
        summary = self.generate_summary()
        return json.dumps(summary, indent=2, default=str)

    def send_report_via_email(self, recipients: list[str]) -> None:
        """Kirim laporan SLO via email (simulasi)."""
        print(f"Sending SLO report for {self.period} to {recipients}")
        print(self.to_json())

    def save_to_file(self, filepath: str) -> None:
        """Simpan laporan ke file."""
        with open(filepath, "w") as f:
            f.write(self.to_json())


# Contoh penggunaan:
# reporter = SLOReporter("2026-05")
# reporter.generate_all_reports()
# reporter.save_to_file("/var/log/slo_report_2026-05.json")
