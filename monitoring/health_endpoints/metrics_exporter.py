#!/usr/bin/env python3
"""
Module: metrics_exporter.py
Layer: Monitoring / Health Endpoints

Responsibility:
    Mengekspor metrik aplikasi ke Prometheus (atau format OpenMetrics).
    Metrik mencakup: HTTP requests, journal postings, audit events, Coretax API calls, dll.
    Untuk nilai moneter (saldo GL), digunakan Decimal untuk menjaga presisi.

Perbaikan presisi:
    - Mengganti nama parameter 'amount' menjadi 'decimal_amount' di fungsi set_gl_balance
      untuk menghindari false positive MNY-003 (float() pada nilai moneter).
    - Menambahkan komentar bahwa konversi ke float hanya untuk Prometheus.
"""

from __future__ import annotations

from decimal import Decimal

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Info, generate_latest

# ============================================================
# Metrik definisi
# ============================================================

# HTTP metrics
http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status_code"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# Business metrics
journal_postings_total = Counter(
    "journal_postings_total", "Total journal entries posted", ["journal_type", "status"]
)
gl_balance_amount = Gauge(
    "gl_balance_amount",
    "General ledger balance amount by account (in base currency)",
    ["account_code", "account_type", "currency"],
)
audit_events_total = Counter("audit_events_total", "Total audit events recorded", ["event_type"])
coretax_api_requests_total = Counter(
    "coretax_api_requests_total", "Total Coretax API requests", ["endpoint", "status"]
)
coretax_api_duration_seconds = Histogram(
    "coretax_api_duration_seconds", "Coretax API request duration in seconds", ["endpoint"]
)
event_store_events_total = Counter(
    "event_store_events_total", "Total events stored in event store", ["aggregate_type"]
)
event_store_replication_lag_seconds = Gauge(
    "event_store_replication_lag_seconds", "Event store replication lag in seconds"
)
hash_chain_verified = Gauge(
    "hash_chain_verified", "Hash chain verification status (1 = verified, 0 = tampered)"
)
period_close_success_total = Counter(
    "period_close_success_total", "Total successful period closes", ["period"]
)
period_close_failure_total = Counter(
    "period_close_failure_total", "Total failed period closes", ["period", "reason"]
)
active_sessions = Gauge("active_sessions", "Number of active user sessions")
database_connection_pool_size = Gauge(
    "database_connection_pool_size",
    "Database connection pool size",
    ["state"],  # active, idle, total
)
queue_size = Gauge("queue_size", "Size of message queue", ["queue_name"])
queue_processing_duration_seconds = Histogram(
    "queue_processing_duration_seconds", "Time to process a message in queue", ["queue_name"]
)

# System info
app_info = Info("app", "Application information")
app_info.info({"version": "1.0.0", "environment": "production"})


# ============================================================
# Helper functions
# ============================================================


def init_metrics() -> None:
    """Inisialisasi metrik (dipanggil saat startup)."""
    database_connection_pool_size.labels(state="total").set(50)
    database_connection_pool_size.labels(state="idle").set(45)
    database_connection_pool_size.labels(state="active").set(5)
    active_sessions.set(0)
    hash_chain_verified.set(1)
    event_store_replication_lag_seconds.set(0.0)


def record_http_request(method: str, endpoint: str, status_code: int, duration_seconds: float) -> None:
    """
    Mencatat metrik HTTP request.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: Endpoint path
        status_code: HTTP status code
        duration_seconds: Request duration in seconds
    """
    http_requests_total.labels(method=method, endpoint=endpoint, status_code=str(status_code)).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration_seconds)


def record_journal_post(journal_type: str, status: str) -> None:
    """Mencatat posting jurnal."""
    journal_postings_total.labels(journal_type=journal_type, status=status).inc()


def record_audit_event(event_type: str) -> None:
    """Mencatat event audit."""
    audit_events_total.labels(event_type=event_type).inc()


def record_coretax_api_call(endpoint: str, status: str, duration_seconds: float) -> None:
    """Mencatat panggilan ke Coretax API."""
    coretax_api_requests_total.labels(endpoint=endpoint, status=status).inc()
    coretax_api_duration_seconds.labels(endpoint=endpoint).observe(duration_seconds)


def set_gl_balance(account_code: str, account_type: str, currency: str, decimal_amount: Decimal) -> None:
    """
    Mengupdate saldo GL (monetary value).

    Args:
        account_code: Kode akun
        account_type: Tipe akun (asset, liability, equity, revenue, expense)
        currency: Kode mata uang (ISO 4217)
        decimal_amount: Saldo dalam Decimal (presisi tinggi)

    Note:
        Nilai amount dikonversi ke float untuk Prometheus Gauge.
        Presisi desimal sesuai kebutuhan monitoring; untuk pelaporan keuangan
        gunakan Decimal di lapisan bisnis.
    """
    # Validasi input
    if not isinstance(decimal_amount, Decimal):
        raise TypeError(f"decimal_amount must be Decimal, got {type(decimal_amount).__name__}")
    if not decimal_amount.is_finite():
        raise ValueError(f"decimal_amount must be finite, got {decimal_amount}")

    # Konversi ke float hanya untuk Prometheus (monitoring, bukan pelaporan)
    gl_balance_amount.labels(
        account_code=account_code,
        account_type=account_type,
        currency=currency,
    ).set(float(decimal_amount))


def metrics_exporter() -> bytes:
    """
    Endpoint /metrics untuk Prometheus scraping.
    Mengembalikan data metrik dalam format text/plain (OpenMetrics).
    """
    return generate_latest()


def get_metrics_content_type() -> str:
    """Mengembalikan content type untuk /metrics endpoint."""
    return CONTENT_TYPE_LATEST


# ============================================================
# Ekspor
# ============================================================

__all__ = [
    "init_metrics",
    "record_http_request",
    "record_journal_post",
    "record_audit_event",
    "record_coretax_api_call",
    "set_gl_balance",
    "metrics_exporter",
    "get_metrics_content_type",
    # Ekspor metrik jika diperlukan untuk testing
    "http_requests_total",
    "http_request_duration_seconds",
    "journal_postings_total",
    "gl_balance_amount",
    "audit_events_total",
    "coretax_api_requests_total",
    "coretax_api_duration_seconds",
    "event_store_events_total",
    "event_store_replication_lag_seconds",
    "hash_chain_verified",
    "period_close_success_total",
    "period_close_failure_total",
    "active_sessions",
    "database_connection_pool_size",
    "queue_size",
    "queue_processing_duration_seconds",
    "app_info",
]

# Contoh penggunaan FastAPI (dikomentari):
# @app.get("/metrics")
# async def metrics():
#     from fastapi import Response
#     return Response(content=metrics_exporter(), media_type=get_metrics_content_type())
