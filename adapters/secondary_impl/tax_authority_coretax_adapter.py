#!/usr/bin/env python3
"""
Adapter: Tax Authority Coretax
Layer: Adapters (Secondary Implementation)

Adapter untuk komunikasi dengan Coretax DJP.
Menggunakan implementasi coretax_authority_adapter_impl yang sudah ada.
"""
from __future__ import annotations

# FIXED: Import class name yang benar (CoretaxAuthorityAdapter)
from adapters.secondary_impl.coretax_authority_adapter_impl import CoretaxAuthorityAdapter


class TaxAuthorityCoretaxAdapter(CoretaxAuthorityAdapter):
    """
    Adapter Coretax dengan nama yang sesuai port.
    """
    pass


__all__ = ["TaxAuthorityCoretaxAdapter"]
