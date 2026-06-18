#!/usr/bin/env python3
"""
Adapter: Timestamp Notary
Layer: Adapters (Secondary Implementation)

Adapter untuk timestamp notary menggunakan RFC3161.
Menggunakan implementasi rfc3161_timestamp_adapter yang sudah ada.
"""
from __future__ import annotations

from adapters.secondary_impl.rfc3161_timestamp_adapter import RFC3161TimestampAdapter


# Ekspor sebagai TimestampNotaryAdapter
class TimestampNotaryAdapter(RFC3161TimestampAdapter):
    """
    Adapter timestamp notary dengan nama yang sesuai port.
    """
    pass

__all__ = ["TimestampNotaryAdapter"]
