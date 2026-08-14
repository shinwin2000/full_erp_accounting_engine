"""
core/formatting.py
===================
Helper format angka/tanggal ala akuntansi Indonesia (Rp, tanggal lokal)
dan util kecil untuk menampilkan data API secara human-readable di tabel.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

_MONTHS_ID = [
    "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
]


def format_money(value: Any, currency: str = "IDR") -> str:
    if value is None or value == "":
        return "-"
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    sign = "-" if dec < 0 else ""
    dec = abs(dec)
    text = f"{dec:,.2f}".rstrip("0").rstrip(".") if dec == dec.to_integral_value() else f"{dec:,.2f}"
    if dec == dec.to_integral_value():
        text = f"{int(dec):,}"
    symbol = {"IDR": "Rp", "USD": "$", "EUR": "€"}.get(currency, currency + " ")
    return f"{sign}{symbol} {text}"


def _to_local(value: datetime) -> datetime:
    """FIX BUG ("waktu log tidak pas"): backend selalu menyimpan & mengirim
    waktu dalam UTC (datetime.utcnow()/datetime.now(UTC) di service_iam.py),
    tapi sebelumnya format_date()/format_datetime() di sini langsung
    strftime() nilai UTC itu apa adanya - ditampilkan seolah-olah sudah jam
    lokal. Akibatnya jam yang tampil di UI selalu tertinggal ~7 jam dari
    waktu asli WIB, dan kadang tanggalnya ikut mundur 1 hari untuk kejadian
    dini hari WIB. Sekarang dikonversi eksplisit ke zona waktu lokal
    komputer user sebelum ditampilkan. Kalau value naive (tidak ada info
    zona sama sekali), dianggap UTC dulu (sesuai konvensi backend) baru
    dikonversi - supaya tidak salah diasumsikan "sudah lokal" oleh Python."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone()


def format_date(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value[:10]
    if isinstance(value, datetime):
        value = _to_local(value)
        return f"{value.day:02d} {_MONTHS_ID[value.month]} {value.year}"
    return str(value)


def format_datetime(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = _to_local(value)
        return f"{value.day:02d} {_MONTHS_ID[value.month]} {value.year} {value.strftime('%H:%M')}"
    return str(value)


def humanize_key(key: str) -> str:
    text = key.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def status_color(status_value: str) -> str:
    s = (status_value or "").lower()
    mapping = {
        "draft": "#9CA3AF",
        "pending": "#F59E0B",
        "submitted": "#3B82F6",
        "validated": "#3B82F6",
        "approved": "#10B981",
        "posted": "#059669",
        "active": "#10B981",
        "rejected": "#EF4444",
        "cancelled": "#EF4444",
        "void": "#EF4444",
        "reversed": "#F97316",
        "locked": "#6B7280",
        "closed": "#6B7280",
        "error": "#DC2626",
        "inactive": "#9CA3AF",
    }
    for key, color in mapping.items():
        if key in s:
            return color
    return "#6B7280"


def extract_list(payload: Any) -> list[dict[str, Any]]:
    """Backend mengembalikan bentuk beragam: list langsung, {"items": [...]},
    {"data": [...]}, {"results": [...]}. Normalisasi ke list of dict."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "records", "accounts", "content"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
        # single object -> bungkus jadi list 1 item bila terlihat seperti record
        if "id" in payload:
            return [payload]
    return []


def extract_total(payload: Any, fallback: int) -> int:
    if isinstance(payload, dict):
        for key in ("total", "total_count", "count", "total_items"):
            if key in payload:
                try:
                    return int(payload[key])
                except (TypeError, ValueError):
                    pass
    return fallback


_camel_re = re.compile(r"(?<!^)(?=[A-Z])")
