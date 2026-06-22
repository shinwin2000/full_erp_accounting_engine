#!/usr/bin/env python3
"""
Module: sqlalchemy_core_tax_port_impl.py
Adapter for CoreTaxPort (re‑export of CoretaxAuthorityAdapter)
"""

from adapters.secondary_impl.tax_authority_coretax_impl import CoretaxAuthorityAdapter as SQLAlchemyCoreTaxAdapter

__all__ = ["SQLAlchemyCoreTaxAdapter"]