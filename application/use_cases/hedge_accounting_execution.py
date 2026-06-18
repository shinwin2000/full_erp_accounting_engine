#!/usr/bin/env python3

"""
Module: hedge_accounting_execution.py

Layer: 5 - Application / Use Cases

Responsibility:
    Use case untuk akuntansi lindung nilai (hedge accounting) sesuai IFRS 9 / PSAK 71.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from application.commands_cqrs.command_bus_unified import Command, CommandResult
from application.service_layer.service_hedge import HedgeService
from application.service_layer.service_journal import JournalService
from application.service_layer.service_ledger import LedgerService
from kernel.sealed_gate import SealedGate

logger = logging.getLogger(__name__)


class HedgeType(Enum):
    FAIR_VALUE_HEDGE = "fair_value_hedge"
    CASH_FLOW_HEDGE = "cash_flow_hedge"
    NET_INVESTMENT_HEDGE = "net_investment_hedge"


class HedgeStatus(Enum):
    DESIGNATED = "designated"
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"
    DISCONTINUED = "discontinued"


class HedgeAccountingCommand(Command):
    """Command untuk akuntansi lindung nilai."""

    __slots__ = (
        "action",
        "designation_date",
        "discontinuation_reason",
        "effectiveness_threshold_lower",
        "effectiveness_threshold_upper",
        "fair_value_change_hedged_item",
        "fair_value_change_instrument",
        "hedge_id",
        "hedge_type",
        "hedged_item_id",
        "hedging_instrument_id",
        "legal_entity_id",
        "valuation_date",
    )

    def __init__(
        self,
        legal_entity_id: UUID,
        action: str,
        hedge_id: UUID | None = None,
        hedge_type: str | None = None,
        hedged_item_id: UUID | None = None,
        hedging_instrument_id: UUID | None = None,
        designation_date: date | None = None,
        effectiveness_threshold_lower: Decimal = Decimal("80"),
        effectiveness_threshold_upper: Decimal = Decimal("125"),
        valuation_date: date | None = None,
        fair_value_change_hedged_item: Decimal | None = None,
        fair_value_change_instrument: Decimal | None = None,
        discontinuation_reason: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ):
        super().__init__(
            command_type="HedgeAccountingCommand", user_id=user_id, correlation_id=correlation_id
        )
        self.legal_entity_id = legal_entity_id
        self.action = action
        self.hedge_id = hedge_id
        self.hedge_type = hedge_type
        self.hedged_item_id = hedged_item_id
        self.hedging_instrument_id = hedging_instrument_id
        self.designation_date = designation_date
        self.effectiveness_threshold_lower = effectiveness_threshold_lower
        self.effectiveness_threshold_upper = effectiveness_threshold_upper
        self.valuation_date = valuation_date
        self.fair_value_change_hedged_item = fair_value_change_hedged_item
        self.fair_value_change_instrument = fair_value_change_instrument
        self.discontinuation_reason = discontinuation_reason

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "legal_entity_id": str(self.legal_entity_id),
                "action": self.action,
                "hedge_id": str(self.hedge_id) if self.hedge_id else None,
                "hedge_type": self.hedge_type,
                "hedged_item_id": str(self.hedged_item_id) if self.hedged_item_id else None,
                "hedging_instrument_id": str(self.hedging_instrument_id)
                if self.hedging_instrument_id
                else None,
                "designation_date": self.designation_date.isoformat()
                if self.designation_date
                else None,
                "effectiveness_threshold_lower": float(self.effectiveness_threshold_lower),
                "effectiveness_threshold_upper": float(self.effectiveness_threshold_upper),
                "valuation_date": self.valuation_date.isoformat() if self.valuation_date else None,
                "fair_value_change_hedged_item": float(self.fair_value_change_hedged_item)
                if self.fair_value_change_hedged_item
                else None,
                "fair_value_change_instrument": float(self.fair_value_change_instrument)
                if self.fair_value_change_instrument
                else None,
                "discontinuation_reason": self.discontinuation_reason,
            }
        )
        return data


class HedgeRelationship:
    def __init__(
        self,
        hedge_id: UUID,
        hedge_type: HedgeType,
        hedged_item_id: UUID,
        hedging_instrument_id: UUID,
        designation_date: date,
        status: HedgeStatus,
        effectiveness_ratio: Decimal | None = None,
        ineffectiveness_amount: Decimal = Decimal("0"),
    ):
        self.hedge_id = hedge_id
        self.hedge_type = hedge_type
        self.hedged_item_id = hedged_item_id
        self.hedging_instrument_id = hedging_instrument_id
        self.designation_date = designation_date
        self.status = status
        self.effectiveness_ratio = effectiveness_ratio
        self.ineffectiveness_amount = ineffectiveness_amount


class HedgeAccountingResult:
    def __init__(
        self,
        hedge_id: UUID,
        action: str,
        status: str,
        effectiveness_ratio: Decimal | None,
        ineffectiveness_amount: Decimal,
        journal_id: UUID | None,
        message: str,
    ):
        self.hedge_id = hedge_id
        self.action = action
        self.status = status
        self.effectiveness_ratio = effectiveness_ratio
        self.ineffectiveness_amount = ineffectiveness_amount
        self.journal_id = journal_id
        self.message = message


class HedgeAccountingUseCase:
    """
    Use case untuk akuntansi lindung nilai.
    """

    def __init__(
        self,
        hedge_service: HedgeService,
        ledger_service: LedgerService,
        journal_service: JournalService,
        sealed_gate: SealedGate | None = None,
    ):
        self._hedge_service = hedge_service
        self._ledger_service = ledger_service
        self._journal_service = journal_service
        self._sealed_gate = sealed_gate
        self._stats = {"executed": 0, "succeeded": 0, "failed": 0}

    async def execute(self, command: HedgeAccountingCommand) -> CommandResult:
        self._stats["executed"] += 1

        try:
            if command.action == "DESIGNATE":
                result = await self._designate_hedge(command)
            elif command.action == "MEASURE_EFFECTIVENESS":
                result = await self._measure_effectiveness(command)
            elif command.action == "RECORD_FAIR_VALUE":
                result = await self._record_fair_value_changes(command)
            elif command.action == "DISCONTINUE":
                result = await self._discontinue_hedge(command)
            else:
                raise ValueError(f"Unknown action: {command.action}")

            self._stats["succeeded"] += 1
            return CommandResult.success(
                command_id=command.command_id,
                data={
                    "hedge_id": str(result.hedge_id),
                    "action": result.action,
                    "status": result.status,
                    "effectiveness_ratio": float(result.effectiveness_ratio)
                    if result.effectiveness_ratio
                    else None,
                    "ineffectiveness_amount": float(result.ineffectiveness_amount),
                    "journal_id": str(result.journal_id) if result.journal_id else None,
                    "message": result.message,
                },
            )

        except Exception as e:
            self._stats["failed"] += 1
            logger.exception(f"Hedge accounting failed: {e}")
            return CommandResult.failure(
                command_id=command.command_id, error=str(e), error_code="HEDGE_ACCOUNTING_ERROR"
            )

    async def _designate_hedge(self, command: HedgeAccountingCommand) -> HedgeAccountingResult:
        if (
            not command.hedge_type
            or not command.hedged_item_id
            or not command.hedging_instrument_id
        ):
            raise ValueError(
                "Hedge type, hedged item, and hedging instrument required for designation"
            )

        hedge_type = HedgeType(command.hedge_type)
        hedge_id = uuid4()
        await self._hedge_service.designate_hedge(
            hedge_id=hedge_id,
            legal_entity_id=command.legal_entity_id,
            hedge_type=hedge_type,
            hedged_item_id=command.hedged_item_id,
            hedging_instrument_id=command.hedging_instrument_id,
            designation_date=command.designation_date or date.today(),
            effectiveness_threshold_lower=command.effectiveness_threshold_lower,
            effectiveness_threshold_upper=command.effectiveness_threshold_upper,
            user_id=command.user_id,
        )
        return HedgeAccountingResult(
            hedge_id=hedge_id,
            action="DESIGNATE",
            status=HedgeStatus.DESIGNATED.value,
            effectiveness_ratio=None,
            ineffectiveness_amount=Decimal("0"),
            journal_id=None,
            message=f"Hedge {hedge_id} designated successfully",
        )

    async def _measure_effectiveness(
        self, command: HedgeAccountingCommand
    ) -> HedgeAccountingResult:
        if not command.hedge_id:
            raise ValueError("Hedge ID required for effectiveness measurement")

        hedge = await self._hedge_service.get_hedge(command.hedge_id)
        if not hedge:
            raise ValueError(f"Hedge {command.hedge_id} not found")

        if (
            command.fair_value_change_hedged_item is None
            or command.fair_value_change_instrument is None
        ):
            raise ValueError("Fair value changes required for effectiveness calculation")

        abs_hedged = abs(command.fair_value_change_hedged_item)
        if abs_hedged == 0:
            effectiveness = Decimal("100")
        else:
            effectiveness = (
                abs(command.fair_value_change_instrument) / abs_hedged * Decimal("100")
            ).quantize(Decimal("0.01"))

        if (
            command.effectiveness_threshold_lower
            <= effectiveness
            <= command.effectiveness_threshold_upper
        ):
            status = HedgeStatus.EFFECTIVE
            ineffectiveness = abs(
                command.fair_value_change_instrument - command.fair_value_change_hedged_item
            )
            message = f"Hedge is effective (ratio={effectiveness}%)"
        else:
            status = HedgeStatus.INEFFECTIVE
            ineffectiveness = abs(command.fair_value_change_instrument) - abs(
                command.fair_value_change_hedged_item
            )
            message = f"Hedge is ineffective (ratio={effectiveness}%)"

        await self._hedge_service.update_effectiveness(
            hedge_id=command.hedge_id,
            effectiveness_ratio=effectiveness,
            status=status,
            ineffectiveness_amount=ineffectiveness,
            measurement_date=command.valuation_date or date.today(),
        )
        return HedgeAccountingResult(
            hedge_id=command.hedge_id,
            action="MEASURE_EFFECTIVENESS",
            status=status.value,
            effectiveness_ratio=effectiveness,
            ineffectiveness_amount=ineffectiveness,
            journal_id=None,
            message=message,
        )

    async def _record_fair_value_changes(
        self, command: HedgeAccountingCommand
    ) -> HedgeAccountingResult:
        if not command.hedge_id:
            raise ValueError("Hedge ID required")
        if command.fair_value_change_instrument is None:
            raise ValueError("Fair value change of instrument required")

        hedge = await self._hedge_service.get_hedge(command.hedge_id)
        if not hedge:
            raise ValueError(f"Hedge {command.hedge_id} not found")

        journal_id = None
        if hedge.hedge_type == HedgeType.FAIR_VALUE_HEDGE:
            journal_id = await self._record_fair_value_hedge_journal(
                hedge,
                command.fair_value_change_instrument,
                command.fair_value_change_hedged_item or Decimal("0"),
                command.valuation_date or date.today(),
                command.user_id,
                command.correlation_id,
            )
        elif hedge.hedge_type == HedgeType.CASH_FLOW_HEDGE:
            journal_id = await self._record_cash_flow_hedge_journal(
                hedge,
                command.fair_value_change_instrument,
                command.valuation_date or date.today(),
                command.user_id,
                command.correlation_id,
            )

        return HedgeAccountingResult(
            hedge_id=command.hedge_id,
            action="RECORD_FAIR_VALUE",
            status=hedge.status.value,
            effectiveness_ratio=hedge.effectiveness_ratio,
            ineffectiveness_amount=hedge.ineffectiveness_amount,
            journal_id=journal_id,
            message=f"Fair value changes recorded for hedge {command.hedge_id}",
        )

    async def _discontinue_hedge(self, command: HedgeAccountingCommand) -> HedgeAccountingResult:
        if not command.hedge_id:
            raise ValueError("Hedge ID required for discontinuation")
        await self._hedge_service.discontinue_hedge(
            hedge_id=command.hedge_id,
            reason=command.discontinuation_reason or "Voluntary",
            discontinuation_date=command.valuation_date or date.today(),
            user_id=command.user_id,
        )
        return HedgeAccountingResult(
            hedge_id=command.hedge_id,
            action="DISCONTINUE",
            status=HedgeStatus.DISCONTINUED.value,
            effectiveness_ratio=None,
            ineffectiveness_amount=Decimal("0"),
            journal_id=None,
            message=f"Hedge {command.hedge_id} discontinued",
        )

    async def _record_fair_value_hedge_journal(
        self,
        hedge: HedgeRelationship,
        change_instrument: Decimal,
        change_hedged_item: Decimal,
        journal_date: date,
        user_id: UUID,
        correlation_id: str | None,
    ) -> UUID:
        lines = []
        if change_hedged_item != 0:
            lines.append(
                {
                    "account_code": f"hedged_{hedge.hedged_item_id}",
                    "debit": change_hedged_item if change_hedged_item > 0 else Decimal("0"),
                    "credit": -change_hedged_item if change_hedged_item < 0 else Decimal("0"),
                    "description": "Adjustment to hedged item fair value",
                }
            )
        if change_instrument != 0:
            lines.append(
                {
                    "account_code": f"derivative_{hedge.hedging_instrument_id}",
                    "debit": change_instrument if change_instrument > 0 else Decimal("0"),
                    "credit": -change_instrument if change_instrument < 0 else Decimal("0"),
                    "description": "Change in fair value of hedging instrument",
                }
            )
        net = change_instrument - change_hedged_item
        if net != 0:
            gain_loss_account = "4-9500" if net > 0 else "5-8500"
            lines.append(
                {
                    "account_code": gain_loss_account,
                    "debit": net if net < 0 else Decimal("0"),
                    "credit": net if net > 0 else Decimal("0"),
                    "description": "Hedge ineffectiveness recognized in P&L",
                }
            )
        if not lines:
            return None
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=hedge.legal_entity_id,
            journal_date=journal_date,
            period=f"{journal_date.year}-{journal_date.month:02d}",
            description=f"Fair value hedge adjustment for {hedge.hedge_id}",
            lines=lines,
            source_system="hedge_accounting",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    async def _record_cash_flow_hedge_journal(
        self,
        hedge: HedgeRelationship,
        change_instrument: Decimal,
        journal_date: date,
        user_id: UUID,
        correlation_id: str | None,
    ) -> UUID:
        oci_account = "3-5000"
        lines = [
            {
                "account_code": f"derivative_{hedge.hedging_instrument_id}",
                "debit": change_instrument if change_instrument > 0 else Decimal("0"),
                "credit": -change_instrument if change_instrument < 0 else Decimal("0"),
                "description": "Change in fair value of hedging instrument",
            },
            {
                "account_code": oci_account,
                "debit": -change_instrument if change_instrument < 0 else Decimal("0"),
                "credit": change_instrument if change_instrument > 0 else Decimal("0"),
                "description": "Cash flow hedge reserve (OCI)",
            },
        ]
        journal_id = await self._journal_service.post_journal(
            legal_entity_id=hedge.legal_entity_id,
            journal_date=journal_date,
            period=f"{journal_date.year}-{journal_date.month:02d}",
            description=f"Cash flow hedge adjustment for {hedge.hedge_id}",
            lines=lines,
            source_system="hedge_accounting",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return journal_id

    def get_stats(self) -> dict[str, int]:
        return self._stats


# ============================================================================
# Handler dengan dependency injection
# ============================================================================


async def hedge_accounting_handler(
    command: Command, use_case: HedgeAccountingUseCase
) -> CommandResult:
    if not isinstance(command, HedgeAccountingCommand):
        raise TypeError(f"Expected HedgeAccountingCommand, got {type(command)}")
    return await use_case.execute(command)


__all__ = [
    "HedgeAccountingCommand",
    "HedgeAccountingResult",
    "HedgeAccountingUseCase",
    "HedgeRelationship",
    "HedgeStatus",
    "HedgeType",
    "hedge_accounting_handler",
]
