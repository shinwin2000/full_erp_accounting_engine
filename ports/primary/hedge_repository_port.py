#!/usr/bin/env python3
"""
Module: hedge_repository_port.py
Layer: Ports / Primary
Responsibility: Port for hedge repository.
"""

from __future__ import annotations

import abc
from typing import Any, Protocol
from uuid import UUID

from domain.hedge.aggregate_root import HedgeRelationship, HedgeStatus
from domain.hedge.hedge_instrument import HedgeInstrument
from domain.hedge.hedged_item import HedgedItem


class HedgeRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def save_hedge(self, hedge: HedgeRelationship) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_hedge_by_id(self, hedge_id: UUID) -> HedgeRelationship | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_hedge_number(self, legal_entity_id: UUID) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_hedges_by_entity(
        self, legal_entity_id: UUID, status: HedgeStatus | None = None
    ) -> list[HedgeRelationship]:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_hedge_instrument(self, instrument_id: UUID) -> HedgeInstrument | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_hedged_item(self, item_id: UUID) -> HedgedItem | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def save_effectiveness_test(self, test_result: dict[str, Any], user_id: UUID) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def save_hedge_adjustment(self, adjustment: dict[str, Any], user_id: UUID) -> None:
        raise NotImplementedError


class HedgeRepositoryPortProtocol(Protocol):
    async def save_hedge(self, hedge: HedgeRelationship) -> None: ...
    async def get_hedge_by_id(self, hedge_id: UUID) -> HedgeRelationship | None: ...
    async def get_last_hedge_number(self, legal_entity_id: UUID) -> str | None: ...
    async def list_hedges_by_entity(
        self, legal_entity_id: UUID, status: HedgeStatus | None = None
    ) -> list[HedgeRelationship]: ...
    async def get_hedge_instrument(self, instrument_id: UUID) -> HedgeInstrument | None: ...
    async def get_hedged_item(self, item_id: UUID) -> HedgedItem | None: ...
    async def save_effectiveness_test(self, test_result: dict[str, Any], user_id: UUID) -> None: ...
    async def save_hedge_adjustment(self, adjustment: dict[str, Any], user_id: UUID) -> None: ...


__all__ = [
    "HedgeRepositoryPort",
    "HedgeRepositoryPortProtocol",
]
