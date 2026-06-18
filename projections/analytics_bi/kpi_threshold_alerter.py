#!/usr/bin/env python3
"""
Module: kpi_threshold_alerter.py
Layer: Projections (Analytics BI)
Responsibility: Memonitor Key Performance Indicators (KPI) dan mengirim alert
               ketika nilai KPI melewati threshold yang ditentukan (warning atau critical).
               Mendukung berbagai jenis KPI: financial (revenue, profit margin, cash flow),
               operational (inventory turnover, collection period), dan compliance
               (tax filing due, period close SLA). Alert dapat dikirim ke berbagai channel.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- projections.ledger.income_statement_period
- projections.ledger.balance_sheet_snapshot
- projections.ledger.cash_flow_indirect
- projections.analytics_bi.financial_ratios_calculator
- infrastructure.telemetry.alert_manager_router
- config.loader_yaml
Audit: Setiap KPI yang melewati threshold dicatat. Alert yang dikirim juga dicatat.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Index, Numeric, String, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import declarative_base

from config.loader_yaml import load_yaml_config
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from projections.analytics_bi.financial_ratios_calculator import (
    FinancialRatiosCalculator,
    get_financial_ratios_calculator,
)
from projections.ledger.balance_sheet_snapshot import (
    BalanceSheetSnapshot,
    get_balance_sheet_snapshot,
)
from projections.ledger.cash_flow_indirect import CashFlowIndirect, get_cash_flow_projection
from projections.ledger.income_statement_period import (
    IncomeStatementPeriod,
    get_income_statement_projection,
)

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "kpi_threshold_alerter"

# KPI definitions
KPI_TYPES = {
    "revenue": {"category": "financial", "direction": "higher_is_better", "unit": "currency"},
    "net_income": {"category": "financial", "direction": "higher_is_better", "unit": "currency"},
    "gross_margin": {
        "category": "profitability",
        "direction": "higher_is_better",
        "unit": "percentage",
    },
    "net_margin": {
        "category": "profitability",
        "direction": "higher_is_better",
        "unit": "percentage",
    },
    "roa": {"category": "profitability", "direction": "higher_is_better", "unit": "percentage"},
    "roe": {"category": "profitability", "direction": "higher_is_better", "unit": "percentage"},
    "current_ratio": {"category": "liquidity", "direction": "higher_is_better", "unit": "ratio"},
    "quick_ratio": {"category": "liquidity", "direction": "higher_is_better", "unit": "ratio"},
    "debt_to_equity": {"category": "solvency", "direction": "lower_is_better", "unit": "ratio"},
    "debt_to_assets": {"category": "solvency", "direction": "lower_is_better", "unit": "ratio"},
    "inventory_turnover": {
        "category": "efficiency",
        "direction": "higher_is_better",
        "unit": "turnover",
    },
    "receivables_turnover": {
        "category": "efficiency",
        "direction": "higher_is_better",
        "unit": "turnover",
    },
    "operating_cash_flow": {
        "category": "cash_flow",
        "direction": "higher_is_better",
        "unit": "currency",
    },
    "period_close_days": {"category": "compliance", "direction": "lower_is_better", "unit": "days"},
    "bank_reconciliation_days": {
        "category": "compliance",
        "direction": "lower_is_better",
        "unit": "days",
    },
}

# Severity levels
ALERT_SEVERITY_WARNING = "warning"
ALERT_SEVERITY_CRITICAL = "critical"

# Default thresholds (dapat di-override dari config)
DEFAULT_THRESHOLDS = {
    "revenue": {"warning": Decimal("1000000000"), "critical": Decimal("500000000")},
    "net_income": {"warning": Decimal("100000000"), "critical": Decimal("50000000")},
    "gross_margin": {"warning": Decimal("0.25"), "critical": Decimal("0.20")},
    "net_margin": {"warning": Decimal("0.10"), "critical": Decimal("0.05")},
    "roa": {"warning": Decimal("0.08"), "critical": Decimal("0.04")},
    "roe": {"warning": Decimal("0.12"), "critical": Decimal("0.06")},
    "current_ratio": {"warning": Decimal("1.5"), "critical": Decimal("1.0")},
    "quick_ratio": {"warning": Decimal("1.0"), "critical": Decimal("0.5")},
    "debt_to_equity": {"warning": Decimal("1.0"), "critical": Decimal("1.5")},
    "debt_to_assets": {"warning": Decimal("0.5"), "critical": Decimal("0.6")},
    "inventory_turnover": {"warning": Decimal("4.0"), "critical": Decimal("2.0")},
    "receivables_turnover": {"warning": Decimal("8.0"), "critical": Decimal("5.0")},
    "operating_cash_flow": {"warning": Decimal("0"), "critical": Decimal("-100000000")},
    "period_close_days": {"warning": Decimal("15"), "critical": Decimal("30")},
    "bank_reconciliation_days": {"warning": Decimal("15"), "critical": Decimal("30")},
}

# Check interval (seconds)
CHECK_INTERVAL_SECONDS = 86400  # Daily

# ============================================================================
# EXCEPTIONS
# ============================================================================


class KPIThresholdError(Exception):
    """Base exception untuk KPI threshold alerter."""
    pass


# ============================================================================
# KPI THRESHOLD ALERTER
# ============================================================================


class KPIThresholdAlerter:
    """
    Alerter untuk KPI yang melewati threshold.

    Fitur:
    - Monitor KPI secara periodik
    - Bandingkan dengan threshold (warning dan critical)
    - Kirim alert ketika threshold terlampaui
    - Support custom thresholds per legal entity dan per KPI
    - History alert untuk tracking
    - Cooldown untuk menghindari alert berulang
    """

    __slots__ = (
        "_alert_cooldown",
        "_balance_sheet",
        "_cash_flow",
        "_check_task",
        "_cooldown_seconds",
        "_income_statement",
        "_ratios_calc",
        "_running",
        "_session_factory",
        "_thresholds",
        "config",
    )

    def __init__(self, config_path: str = "config_files/kpi_config.yaml") -> None:
        self.config = self._load_config(config_path)
        self._thresholds = self._load_thresholds()
        self._session_factory = None
        self._income_statement: IncomeStatementPeriod | None = None
        self._balance_sheet: BalanceSheetSnapshot | None = None
        self._cash_flow: CashFlowIndirect | None = None
        self._ratios_calc: FinancialRatiosCalculator | None = None
        self._alert_cooldown: dict[str, datetime] = {}
        self._cooldown_seconds = 86400  # Max 1 alert per KPI per day
        self._check_task: asyncio.Task | None = None
        self._running = False

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception:
            return {}

    def _load_thresholds(self) -> dict[str, dict[str, dict[str, Decimal]]]:
        """
        Memuat thresholds dari config, fallback ke default.
        Format: {"legal_entity_id": {"kpi_name": {"warning": Decimal, "critical": Decimal}}}
        Semua nilai dikonversi ke Decimal.
        """
        raw_thresholds = self.config.get("kpi_thresholds", {})
        result: dict[str, dict[str, dict[str, Decimal]]] = {}
        for le_id, le_thresholds in raw_thresholds.items():
            result[le_id] = {}
            for kpi, values in le_thresholds.items():
                try:
                    result[le_id][kpi] = {
                        "warning": Decimal(str(values.get("warning", 0))),
                        "critical": Decimal(str(values.get("critical", 0))),
                    }
                except (TypeError, ValueError) as e:
                    logger.warning(f"Invalid threshold for {le_id}:{kpi}: {e}, using defaults")
                    if kpi in DEFAULT_THRESHOLDS:
                        result[le_id][kpi] = DEFAULT_THRESHOLDS[kpi].copy()
        return result

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _get_income_statement(self) -> IncomeStatementPeriod:
        if self._income_statement is None:
            self._income_statement = await get_income_statement_projection()
        return self._income_statement

    async def _get_balance_sheet(self) -> BalanceSheetSnapshot:
        if self._balance_sheet is None:
            self._balance_sheet = await get_balance_sheet_snapshot()
        return self._balance_sheet

    async def _get_cash_flow(self) -> CashFlowIndirect:
        if self._cash_flow is None:
            self._cash_flow = await get_cash_flow_projection()
        return self._cash_flow

    async def _get_ratios_calc(self) -> FinancialRatiosCalculator:
        if self._ratios_calc is None:
            self._ratios_calc = await get_financial_ratios_calculator()
        return self._ratios_calc

    def _get_threshold_for_kpi(self, legal_entity_id: str, kpi_name: str) -> dict[str, Decimal] | None:
        """
        Mendapatkan threshold untuk KPI tertentu.
        Returns: {"warning": Decimal, "critical": Decimal} or None if not defined.
        """
        # Check legal entity specific
        if legal_entity_id in self._thresholds and kpi_name in self._thresholds[legal_entity_id]:
            return self._thresholds[legal_entity_id][kpi_name]
        # Use default
        if kpi_name in DEFAULT_THRESHOLDS:
            return DEFAULT_THRESHOLDS[kpi_name]
        return None

    def _is_threshold_violated(
        self, current_value: Decimal, threshold: dict[str, Decimal], direction: str
    ) -> tuple[bool, str | None]:
        """
        Memeriksa apakah threshold dilanggar.
        Returns: (violated, severity) where severity is "warning" or "critical".
        """
        if threshold is None:
            return False, None

        warning_val = threshold.get("warning", Decimal(0))
        critical_val = threshold.get("critical", Decimal(0))

        if direction == "higher_is_better":
            if current_value <= critical_val:
                return True, ALERT_SEVERITY_CRITICAL
            elif current_value <= warning_val:
                return True, ALERT_SEVERITY_WARNING
        else:  # lower_is_better
            if current_value >= critical_val:
                return True, ALERT_SEVERITY_CRITICAL
            elif current_value >= warning_val:
                return True, ALERT_SEVERITY_WARNING

        return False, None

    async def get_current_kpi_values(
        self, legal_entity_id: UUID, period_id: UUID
    ) -> dict[str, Decimal]:
        """
        Mengumpulkan nilai KPI terkini untuk legal entity dan periode.
        """
        ratios_data = await self._get_ratios_calc().calculate_ratios(legal_entity_id, period_id)
        ratios = ratios_data.get("ratios", {})

        # Get period close days (from period close SLA monitor) - placeholder
        period_close_days = Decimal(0)
        # Get bank reconciliation days (from bank reconciliation status) - placeholder
        bank_reconciliation_days = Decimal(0)

        # Map ratios to KPI names
        kpi_values = {}
        for kpi_name in KPI_TYPES:
            if kpi_name in ratios and ratios[kpi_name] is not None:
                kpi_values[kpi_name] = Decimal(str(ratios[kpi_name]))
            elif kpi_name == "period_close_days":
                kpi_values[kpi_name] = period_close_days
            elif kpi_name == "bank_reconciliation_days":
                kpi_values[kpi_name] = bank_reconciliation_days
            elif kpi_name == "operating_cash_flow":
                # Get from cash flow projection
                cf = await self._get_cash_flow().compute_full_cash_flow(legal_entity_id, period_id)
                kpi_values[kpi_name] = Decimal(str(cf.get("operating_cash_flow", 0)))

        return kpi_values

    async def check_and_alert(self, legal_entity_id: UUID, period_id: UUID) -> list[dict]:
        """
        Memeriksa KPI dan mengirim alert jika threshold dilanggar.

        Returns:
            List of alerts triggered.
        """
        le_id_str = str(legal_entity_id)
        kpi_values = await self.get_current_kpi_values(legal_entity_id, period_id)
        alerts = []

        for kpi_name, current_value in kpi_values.items():
            threshold = self._get_threshold_for_kpi(le_id_str, kpi_name)
            if threshold is None:
                continue

            direction = KPI_TYPES.get(kpi_name, {}).get("direction", "higher_is_better")
            violated, severity = self._is_threshold_violated(current_value, threshold, direction)

            if violated:
                # Check cooldown
                cooldown_key = f"{le_id_str}:{kpi_name}:{severity}"
                last_alert = self._alert_cooldown.get(cooldown_key)
                if (
                    last_alert
                    and (datetime.now(UTC) - last_alert).total_seconds() < self._cooldown_seconds
                ):
                    continue

                # Build alert message
                direction_text = "below" if direction == "higher_is_better" else "above"
                alert_message = (
                    f"KPI {kpi_name} is {current_value:.2f} "
                    f"{direction_text} threshold ({severity} level). "
                    f"Threshold: warning={threshold['warning']}, critical={threshold['critical']}"
                )

                # Send alert (using string representation for serialization)
                await trigger_alert(
                    title=f"KPI Alert: {kpi_name} ({severity})",
                    message=alert_message,
                    severity=severity,
                    source="KPIThresholdAlerter",
                    metadata={
                        "legal_entity_id": le_id_str,
                        "kpi": kpi_name,
                        "current_value": str(current_value),
                        "warning_threshold": str(threshold["warning"]),
                        "critical_threshold": str(threshold["critical"]),
                        "severity": severity,
                    },
                )

                self._alert_cooldown[cooldown_key] = datetime.now(UTC)

                alerts.append(
                    {
                        "kpi": kpi_name,
                        "current_value": current_value,
                        "severity": severity,
                        "threshold": threshold,
                    }
                )

        # Save alert history to database
        if alerts:
            await self._save_alert_history(legal_entity_id, period_id, alerts)

        return alerts

    async def _save_alert_history(
        self, legal_entity_id: UUID, period_id: UUID, alerts: list[dict]
    ) -> None:
        """Menyimpan history alert ke tabel materialized."""
        async with await self._get_session() as session, session.begin():
            for alert in alerts:
                stmt = insert(KPIAlertHistoryTable).values(
                    id=uuid4(),
                    legal_entity_id=legal_entity_id,
                    period_id=period_id,
                    kpi_name=alert["kpi"],
                    current_value=alert["current_value"],
                    severity=alert["severity"],
                    threshold_warning=alert["threshold"]["warning"],
                    threshold_critical=alert["threshold"]["critical"],
                    triggered_at=datetime.now(UTC),
                )
                await session.execute(stmt)
            await session.commit()

    async def get_alert_history(self, legal_entity_id: UUID, limit: int = 50) -> list[dict]:
        """
        Mendapatkan history alert untuk legal entity.
        """
        async with await self._get_session() as session:
            stmt = (
                select(KPIAlertHistoryTable)
                .where(KPIAlertHistoryTable.legal_entity_id == legal_entity_id)
                .order_by(KPIAlertHistoryTable.triggered_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "kpi_name": row.kpi_name,
                    "current_value": row.current_value,  # Decimal
                    "severity": row.severity,
                    "threshold_warning": row.threshold_warning,  # Decimal
                    "threshold_critical": row.threshold_critical,  # Decimal
                    "triggered_at": row.triggered_at.isoformat(),
                }
                for row in rows
            ]

    async def update_thresholds(
        self, legal_entity_id: UUID, kpi_name: str, warning_value: Decimal, critical_value: Decimal
    ) -> None:
        """
        Memperbarui thresholds untuk KPI tertentu.

        Args:
            legal_entity_id: UUID legal entity.
            kpi_name: Nama KPI.
            warning_value: Nilai threshold warning (Decimal).
            critical_value: Nilai threshold critical (Decimal).
        """
        # Validate that warning is not less than critical for lower_is_better? Not enforced.
        le_id_str = str(legal_entity_id)
        if le_id_str not in self._thresholds:
            self._thresholds[le_id_str] = {}
        self._thresholds[le_id_str][kpi_name] = {
            "warning": warning_value,
            "critical": critical_value,
        }
        logger.info(
            f"Thresholds updated for {le_id_str}: {kpi_name} "
            f"warning={warning_value}, critical={critical_value}"
        )

    async def start_periodic_check(self, legal_entity_id: UUID, period_id: UUID) -> None:
        """
        Memulai periodic check KPI (scheduler).
        """
        if self._running:
            logger.warning("KPI alerter already running")
            return

        self._running = True

        async def _check_loop():
            while self._running:
                try:
                    await self.check_and_alert(legal_entity_id, period_id)
                    await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"KPI check error: {e}")
                    await asyncio.sleep(60)

        self._check_task = asyncio.create_task(_check_loop())
        logger.info(f"KPI threshold alerter started for legal entity {legal_entity_id}")

    async def stop_periodic_check(self) -> None:
        """Menghentikan periodic check."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None
        logger.info("KPI threshold alerter stopped")

    async def run_manual_check(self, legal_entity_id: UUID, period_id: UUID) -> list[dict]:
        """
        Menjalankan check manual (on-demand).
        """
        return await self.check_and_alert(legal_entity_id, period_id)


# ============================================================================
# ORM MODEL (tambahan)
# ============================================================================

Base = declarative_base()


class KPIAlertHistoryTable(Base):
    __tablename__ = "kpi_alert_history"
    __table_args__ = (
        Index("idx_kpi_alert_legal_entity", "legal_entity_id"),
        Index("idx_kpi_alert_triggered", "triggered_at"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_id = Column(PGUUID(as_uuid=True), nullable=False)
    kpi_name = Column(String(50), nullable=False)
    current_value = Column(Numeric(20, 2), nullable=False)
    severity = Column(String(20), nullable=False)
    threshold_warning = Column(Numeric(20, 2), nullable=False)
    threshold_critical = Column(Numeric(20, 2), nullable=False)
    triggered_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_kpi_alerter: KPIThresholdAlerter | None = None


async def get_kpi_alerter() -> KPIThresholdAlerter:
    """Get singleton instance of KPIThresholdAlerter."""
    global _kpi_alerter
    if _kpi_alerter is None:
        _kpi_alerter = KPIThresholdAlerter()
    return _kpi_alerter


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["KPIThresholdAlerter", "KPIThresholdError", "get_kpi_alerter"]
