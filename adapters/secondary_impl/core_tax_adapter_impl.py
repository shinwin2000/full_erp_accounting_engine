#!/usr/bin/env python3
"""
Module: core_tax_adapter_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi CoreTaxPort - stub untuk DI container.
"""

from __future__ import annotations

from typing import Any
from ports.primary.core_tax_port import CoreTaxPort


class CoretaxAuthorityAdapter(CoreTaxPort):
    """
    Stub adapter untuk Core Tax API.
    Konstruktor menerima config opsional (default None).
    """
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def calculate_tax(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "tax_amount": 0.0,
            "tax_base": data.get("amount", 0),
            "status": "stub",
            "message": "CoreTax stub implementation"
        }

    async def validate_tax_id(self, tax_id: str) -> bool:
        return True

    async def get_tax_rate(self, tax_code: str, date: str) -> float:
        return 0.11


# Alias yang digunakan oleh ioc_container.py
CoreTaxImpl = CoretaxAuthorityAdapter

__all__ = ["CoretaxAuthorityAdapter", "CoreTaxImpl"]