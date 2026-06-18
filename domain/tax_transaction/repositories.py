#!/usr/bin/env python3
"""
Module: repositories.py
Layer: Domain / Tax Transaction
Responsibility: Repository interfaces for tax aggregates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from .aggregate_root import Bupot, EMeterai, FakturPajak, SPTSubmission
from .value_objects import NPWPVO, MasaPajak


class FakturPajakRepository(ABC):
    @abstractmethod
    async def add(self, faktur: FakturPajak) -> None:
        pass

    @abstractmethod
    async def save(self, faktur: FakturPajak) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, faktur_id: UUID) -> FakturPajak | None:
        pass

    @abstractmethod
    async def get_by_nomor(self, nomor: str) -> FakturPajak | None:
        pass

    @abstractmethod
    async def get_by_npwp(self, npwp: NPWPVO, masa: MasaPajak) -> list[FakturPajak]:
        pass

    @abstractmethod
    async def delete(self, faktur_id: UUID) -> bool:
        pass

    @abstractmethod
    async def exists(self, nomor: str) -> bool:
        pass

    @abstractmethod
    async def count_by_masa(self, masa: MasaPajak) -> int:
        pass

    @abstractmethod
    async def lock(self, faktur_id: UUID) -> bool:
        pass

    @abstractmethod
    async def unlock(self, faktur_id: UUID) -> bool:
        pass


class SPTRepository(ABC):
    @abstractmethod
    async def add(self, spt: SPTSubmission) -> None:
        pass

    @abstractmethod
    async def save(self, spt: SPTSubmission) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, spt_id: UUID) -> SPTSubmission | None:
        pass

    @abstractmethod
    async def get_by_masa(self, masa: MasaPajak) -> list[SPTSubmission]:
        pass

    @abstractmethod
    async def delete(self, spt_id: UUID) -> bool:
        pass

    @abstractmethod
    async def exists(self, masa: MasaPajak, jenis: str) -> bool:
        pass


class BupotRepository(ABC):
    @abstractmethod
    async def add(self, bupot: Bupot) -> None:
        pass

    @abstractmethod
    async def save(self, bupot: Bupot) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, bupot_id: UUID) -> Bupot | None:
        pass

    @abstractmethod
    async def get_by_npwp_pemotong(self, npwp: NPWPVO, masa: MasaPajak) -> list[Bupot]:
        pass

    @abstractmethod
    async def delete(self, bupot_id: UUID) -> bool:
        pass


class EMeteraiRepository(ABC):
    @abstractmethod
    async def add(self, meterai: EMeterai) -> None:
        pass

    @abstractmethod
    async def save(self, meterai: EMeterai) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, meterai_id: UUID) -> EMeterai | None:
        pass

    @abstractmethod
    async def get_by_nomor_seri(self, nomor_seri: str) -> EMeterai | None:
        pass

    @abstractmethod
    async def delete(self, meterai_id: UUID) -> bool:
        pass
