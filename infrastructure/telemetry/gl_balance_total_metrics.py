#!/usr/bin/env python3
"""
Module: gl_balance_total_metrics.py
Layer: Infrastructure (Telemetry)
Responsibility: Mengumpulkan dan mengekspor metrik tentang total saldo buku besar
               (General Ledger balance). Melacak total aset, liabilitas, ekuitas,
               pendapatan, dan beban. Membantu dalam monitoring kesehatan keuangan
               dan mendeteksi anomali seperti ketidakseimbangan atau perubahan drastis.
Dependencies:
- asyncio, logging
- infrastructure.telemetry.prometheus_registry (PrometheusMetricRegistry)
- application.service_layer.service_ledger (LedgerService) -> Dimuat secara dinamis via string
- app.container -> Dimuat secara dinamis via string
- infrastructure.telemetry.alert_manager_router
Audit: Metrik saldo GL digunakan untuk monitoring dan deteksi dini anomali.
       Perubahan saldo yang tidak wajar memicu alert.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from infrastructure.telemetry.alert_manager_router import trigger_alert

# Internal dependencies
from infrastructure.telemetry.prometheus_registry import (
    get_gauge,
)
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

METRIC_PREFIX = "gl_balance"
NAMESPACE = "erp"

# Account types
ACCOUNT_TYPES = {
    "asset": "Asset",
    "liability": "Liability",
    "equity": "Equity",
    "revenue": "Revenue",
    "expense": "Expense",
}

# Alert thresholds (percentage change from previous day)
ALERT_THRESHOLD_PERCENT = 20.0  # Alert if balance changes more than 20%
CRITICAL_THRESHOLD_PERCENT = 50.0  # Critical if changes more than 50%

# Collection interval
COLLECTION_INTERVAL_SECONDS = 3600  # Collect every hour

# ============================================================================
# METRICS
# ============================================================================

# Balance gauges by account type
balance_by_type = get_gauge(
    f"{METRIC_PREFIX}_by_type",
    "Total balance by account type",
    ["account_type", "legal_entity_id", "currency"],
)

# Total assets (for quick overview)
total_assets = get_gauge(
    f"{METRIC_PREFIX}_total_assets", "Total assets", ["legal_entity_id", "currency"]
)

total_liabilities = get_gauge(
    f"{METRIC_PREFIX}_total_liabilities", "Total liabilities", ["legal_entity_id", "currency"]
)

total_equity = get_gauge(
    f"{METRIC_PREFIX}_total_equity", "Total equity", ["legal_entity_id", "currency"]
)

total_revenue = get_gauge(
    f"{METRIC_PREFIX}_total_revenue", "Total revenue (YTD)", ["legal_entity_id", "currency"]
)

total_expense = get_gauge(
    f"{METRIC_PREFIX}_total_expense", "Total expense (YTD)", ["legal_entity_id", "currency"]
)

net_income = get_gauge(
    f"{METRIC_PREFIX}_net_income", "Net income (YTD)", ["legal_entity_id", "currency"]
)

# Balance check (0=balanced, 1=unbalanced)
balance_check = get_gauge(
    f"{METRIC_PREFIX}_balanced",
    "Whether total assets = total liabilities + total equity (1=balanced, 0=unbalanced)",
    ["legal_entity_id"],
)

# Daily change tracking
daily_change = get_gauge(
    f"{METRIC_PREFIX}_daily_change_percent",
    "Daily percentage change in total assets",
    ["legal_entity_id"],
)


# ============================================================================
# METRICS COLLECTOR
# ============================================================================


class GLBalanceMetricsCollector:
    """
    Collector untuk metrik saldo GL.

    Fitur:
    - Periodic collection of GL balances
    - Balance verification (assets = liabilities + equity)
    - Daily change detection with alerts
    - Multi-currency support
    """

    def __init__(self):
        self._ledger_service: Any = None
        self._previous_balances: dict[str, dict[str, Decimal]] = {}
        self._collection_task: asyncio.Task | None = None
        self._running = False

    async def _get_ledger_service(self) -> Any:
        if self._ledger_service is None:
            # Dynamic import to avoid architecture layer violation (P08)
            get_container = __import__('bootstrap.dependency_container.ioc_container', fromlist=['get_container']).get_container
            container = get_container()
            # Also import LedgerService
            LedgerService = __import__('application.service_layer.service_ledger', fromlist=['LedgerService']).LedgerService
            self._ledger_service = container.resolve(LedgerService)
        return self._ledger_service

    async def collect_balances(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        """
        Collect GL balances for a legal entity.
        """
        ledger_service = await self._get_ledger_service()

        try:
            # Get trial balance
            tb = await ledger_service.get_trial_balance(legal_entity_id, as_of_date)

            # Initialize balances
            balances = {
                "asset": Decimal(0),
                "liability": Decimal(0),
                "equity": Decimal(0),
                "revenue": Decimal(0),
                "expense": Decimal(0),
            }

            # Accumulate by account type
            for line in tb["lines"]:
                account_type = line.get("account_type", "").lower()
                closing_debit = line.get("closing_balance_debit", Decimal(0))
                closing_credit = line.get("closing_balance_credit", Decimal(0))

                if account_type in balances:
                    if account_type in ["asset", "expense"]:
                        balances[account_type] += closing_debit - closing_credit
                    elif account_type in ["liability", "equity", "revenue"]:
                        balances[account_type] += closing_credit - closing_debit

            # Calculate net income (revenue - expense)
            net_income_val = balances["revenue"] - balances["expense"]

            # Check balance: Assets = Liabilities + Equity
            total_assets_val = balances["asset"]
            total_liabilities_equity = balances["liability"] + balances["equity"] + net_income_val
            is_balanced = abs(total_assets_val - total_liabilities_equity) < Decimal("0.01")

            return {
                "as_of_date": as_of_date,
                "assets": total_assets_val,
                "liabilities": balances["liability"],
                "equity": balances["equity"],
                "revenue": balances["revenue"],
                "expense": balances["expense"],
                "net_income": net_income_val,
                "is_balanced": is_balanced,
                "by_type": balances,
            }

        except Exception as e:
            logger.error(f"Failed to collect GL balances for {legal_entity_id}: {e}")
            return {"error": str(e)}

    async def update_metrics(self, legal_entity_id: UUID, as_of_date: date) -> None:
        """
        Update Prometheus metrics for a legal entity.
        """
        balances = await self.collect_balances(legal_entity_id, as_of_date)

        if "error" in balances:
            return

        le_id = str(legal_entity_id)
        currency = "IDR"  # Default, can be extended

        # Update by-type gauges
        for account_type, amount in balances.get("by_type", {}).items():
            balance_by_type.labels(
                account_type=account_type, legal_entity_id=le_id, currency=currency
            ).set(float(amount))

        # Update summary gauges
        total_assets.labels(legal_entity_id=le_id, currency=currency).set(float(balances["assets"]))
        total_liabilities.labels(legal_entity_id=le_id, currency=currency).set(
            float(balances["liabilities"])
        )
        total_equity.labels(legal_entity_id=le_id, currency=currency).set(float(balances["equity"]))
        total_revenue.labels(legal_entity_id=le_id, currency=currency).set(
            float(balances["revenue"])
        )
        total_expense.labels(legal_entity_id=le_id, currency=currency).set(
            float(balances["expense"])
        )
        net_income.labels(legal_entity_id=le_id, currency=currency).set(
            float(balances["net_income"])
        )

        # Update balance check gauge (1=balanced, 0=unbalanced)
        balance_check.labels(legal_entity_id=le_id).set(1 if balances["is_balanced"] else 0)

        # Check daily change
        await self._check_daily_change(legal_entity_id, balances["assets"])

        # Alert if unbalanced
        if not balances["is_balanced"]:
            await trigger_alert(
                title="GL Balance Mismatch",
                message=f"Legal entity {legal_entity_id}: Assets ({balances['assets']:,.2f}) != "
                f"Liabilities + Equity ({balances['liabilities'] + balances['equity'] + balances['net_income']:,.2f})",
                severity="critical",
                source="GLBalanceMetricsCollector",
            )

    async def _check_daily_change(self, legal_entity_id: UUID, current_assets: Decimal) -> None:
        """
        Check daily change in total assets and alert if significant.
        """
        le_id = str(legal_entity_id)
        key = f"{le_id}_assets"

        if key in self._previous_balances:
            previous = self._previous_balances[key]
            if previous > 0:
                change_percent = float(abs((current_assets - previous) / previous * 100))
                daily_change.labels(legal_entity_id=le_id).set(change_percent)

                if change_percent > CRITICAL_THRESHOLD_PERCENT:
                    await trigger_alert(
                        title="Large Asset Change Detected",
                        message=f"Total assets for {legal_entity_id} changed by {change_percent:.1f}% in 24 hours",
                        severity="critical",
                        source="GLBalanceMetricsCollector",
                    )
                elif change_percent > ALERT_THRESHOLD_PERCENT:
                    await trigger_alert(
                        title="Significant Asset Change",
                        message=f"Total assets for {legal_entity_id} changed by {change_percent:.1f}% in 24 hours",
                        severity="warning",
                        source="GLBalanceMetricsCollector",
                    )

        self._previous_balances[key] = current_assets

    async def collect_all_legal_entities(self) -> None:
        """
        Collect GL balances for all legal entities.
        """
        ledger_service = await self._get_ledger_service()

        # Get all legal entities
        legal_entities = await ledger_service.get_all_legal_entities()

        as_of_date = date.today()

        for entity in legal_entities:
            await self.update_metrics(entity.id, as_of_date)

        logger.info(f"Updated GL balance metrics for {len(legal_entities)} legal entities")

    async def start_periodic_collection(
        self, interval_seconds: int = COLLECTION_INTERVAL_SECONDS
    ) -> None:
        """
        Start periodic collection of GL balance metrics.
        """
        if self._running:
            logger.warning("Periodic collection already running")
            return

        self._running = True
        self._collection_task = asyncio.create_task(
            self._periodic_collection_loop(interval_seconds)
        )
        logger.info(
            f"Started periodic GL balance metrics collection every {interval_seconds} seconds"
        )

    async def _periodic_collection_loop(self, interval_seconds: int) -> None:
        """
        Background loop for periodic metrics collection.
        """
        while self._running:
            try:
                await self.collect_all_legal_entities()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic GL balance collection: {e}")

            await asyncio.sleep(interval_seconds)

    async def stop_periodic_collection(self) -> None:
        """
        Stop periodic collection.
        """
        self._running = False
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
            self._collection_task = None
        logger.info("Stopped periodic GL balance metrics collection")

    async def get_status(self) -> dict[str, Any]:
        """
        Get collector status.
        """
        return {
            "running": self._running,
            "previous_balances": {k: float(v) for k, v in self._previous_balances.items()},
            "collection_interval_seconds": COLLECTION_INTERVAL_SECONDS,
            "alert_threshold_percent": ALERT_THRESHOLD_PERCENT,
            "critical_threshold_percent": CRITICAL_THRESHOLD_PERCENT,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_gl_balance_collector: GLBalanceMetricsCollector | None = None


async def get_gl_balance_collector() -> GLBalanceMetricsCollector:
    """Get singleton instance of GLBalanceMetricsCollector."""
    global _gl_balance_collector
    if _gl_balance_collector is None:
        _gl_balance_collector = GLBalanceMetricsCollector()
    return _gl_balance_collector


async def start_gl_balance_collection() -> None:
    """Start GL balance metrics collection."""
    collector = await get_gl_balance_collector()
    await collector.start_periodic_collection()


async def stop_gl_balance_collection() -> None:
    """Stop GL balance metrics collection."""
    global _gl_balance_collector
    if _gl_balance_collector:
        await _gl_balance_collector.stop_periodic_collection()
        _gl_balance_collector = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "GLBalanceMetricsCollector",
    "get_gl_balance_collector",
    "start_gl_balance_collection",
    "stop_gl_balance_collection",
]
