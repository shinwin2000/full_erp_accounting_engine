#!/usr/bin/env python3
"""
Module: tax_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port (abstract interface) for tax-related repository operations.

Defines the contract for storing and retrieving tax data:
- Faktur Pajak Keluaran (output tax invoices)
- Faktur Pajak Masukan (input tax invoices)
- SPT Masa PPN, PPh 21, PPh 23
- SPT Tahunan Badan
- e-Bupot records
- NSFP ranges
- Submission logs

Dependencies:
- Python standard library (abc, UUID, datetime, decimal)
- domain.value objects (NPWP, NTPN, MasaPajak, TahunPajak)

Audit: This is a port, no direct audit logging here.
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID


# Value object stubs (actual implementation in domain.shared_value_objects)
class NPWP:
    def __init__(self, value: str):
        self.value = value


class NTPN:
    def __init__(self, value: str):
        self.value = value


class MasaPajak:
    def __init__(self, bulan: int, tahun: int):
        self.bulan = bulan
        self.tahun = tahun


class TahunPajak:
    def __init__(self, tahun: int):
        self.tahun = tahun


class TaxRepositoryPort(abc.ABC):
    """
    Port for tax data persistence.
    All methods must be implemented by concrete adapters.
    """

    # --------------------------------------------------------------------
    # Faktur Pajak Keluaran (Output Tax Invoices)
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_faktur_keluaran(self, faktur: Any) -> None:
        """Save or update a faktur pajak keluaran."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_faktur_keluaran(self, faktur_id: UUID) -> Any | None:
        """Retrieve a faktur keluaran by its ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_faktur_keluaran_by_npwp(
        self,
        npwp: str,
        from_date: date | None = None,
        to_date: date | None = None,
        status: str | None = None,
    ) -> list[Any]:
        """List faktur keluaran for a taxpayer."""
        raise NotImplementedError

    @abc.abstractmethod
    async def count_faktur_by_status(self, legal_entity_id: UUID, status: str) -> int:
        """Count faktur with given status."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Faktur Pajak Masukan (Input Tax Invoices)
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_faktur_masukan(self, faktur: Any) -> None:
        """Save or update a faktur pajak masukan."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_faktur_masukan(self, faktur_id: UUID) -> Any | None:
        """Retrieve a faktur masukan by ID."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_faktur_masukan_by_npwp(
        self, npwp: str, masa_pajak: str | None = None
    ) -> list[Any]:
        """List faktur masukan for a taxpayer, optionally by period."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # e-Bupot (PPh 23/26)
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_bukti_potong(self, bukti: Any) -> None:
        """Save e-Bupot record."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_bukti_potong(self, bukti_id: UUID) -> Any | None:
        """Retrieve e-Bupot by ID."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # SPT Masa PPN
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_spt_ppn(self, spt: Any) -> None:
        """Save SPT Masa PPN record."""
        raise NotImplementedError

    @abc.abstractmethod
    async def count_spt_by_status(self, legal_entity_id: UUID, status: str, spt_type: str) -> int:
        """Count SPT by status and type."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # SPT Masa PPh 21
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_spt_pph21(self, spt: Any) -> None:
        """Save SPT Masa PPh 21 record."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # SPT Tahunan Badan
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_spt_tahunan(self, spt: Any) -> None:
        """Save SPT Tahunan Badan record."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # NSFP Management
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_nsfp_range(
        self, legal_entity_id: UUID, start: str, end: str, requested_at: datetime
    ) -> None:
        """Save a new NSFP range."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_current_nsfp_range(self, legal_entity_id: UUID) -> Any | None:
        """Get current NSFP range (with start, end, current)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_nsfp_current(self, legal_entity_id: UUID, current: str) -> None:
        """Update the current NSFP pointer."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Submission Logs
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def get_last_submission_date(self, legal_entity_id: UUID) -> datetime | None:
        """Get timestamp of last successful submission to Coretax."""
        raise NotImplementedError

    @abc.abstractmethod
    async def save_submission_log(self, log: Any) -> None:
        """Save submission log entry."""
        raise NotImplementedError


class TaxRepositoryPortProtocol(Protocol):
    """Protocol version for structural subtyping."""

    async def save_faktur_keluaran(self, faktur: Any) -> None: ...
    async def get_faktur_keluaran(self, faktur_id: UUID) -> Any | None: ...
    async def list_faktur_keluaran_by_npwp(
        self,
        npwp: str,
        from_date: date | None = None,
        to_date: date | None = None,
        status: str | None = None,
    ) -> list[Any]: ...
    async def count_faktur_by_status(self, legal_entity_id: UUID, status: str) -> int: ...
    async def save_faktur_masukan(self, faktur: Any) -> None: ...
    async def get_faktur_masukan(self, faktur_id: UUID) -> Any | None: ...
    async def list_faktur_masukan_by_npwp(
        self, npwp: str, masa_pajak: str | None = None
    ) -> list[Any]: ...
    async def save_bukti_potong(self, bukti: Any) -> None: ...
    async def get_bukti_potong(self, bukti_id: UUID) -> Any | None: ...
    async def save_spt_ppn(self, spt: Any) -> None: ...
    async def count_spt_by_status(
        self, legal_entity_id: UUID, status: str, spt_type: str
    ) -> int: ...
    async def save_spt_pph21(self, spt: Any) -> None: ...
    async def save_spt_tahunan(self, spt: Any) -> None: ...
    async def save_nsfp_range(
        self, legal_entity_id: UUID, start: str, end: str, requested_at: datetime
    ) -> None: ...
    async def get_current_nsfp_range(self, legal_entity_id: UUID) -> Any | None: ...
    async def update_nsfp_current(self, legal_entity_id: UUID, current: str) -> None: ...
    async def get_last_submission_date(self, legal_entity_id: UUID) -> datetime | None: ...
    async def save_submission_log(self, log: Any) -> None: ...


__all__ = [
    "TaxRepositoryPort",
    "TaxRepositoryPortProtocol",
]
