# tests/projections/analytics_bi/test_kpi_threshold_alerter.py
# Comprehensive tests for projections/analytics_bi/kpi_threshold_alerter.py

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projections.analytics_bi.kpi_threshold_alerter import (
    KPIAlertHistoryTable,
    KPIThresholdAlerter,
    KPIThresholdError,
    get_kpi_alerter,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.begin = AsyncMock()
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    factory = AsyncMock()
    factory.get_session = AsyncMock(return_value=mock_session)
    return factory


@pytest.fixture
def mock_income_statement():
    proj = AsyncMock()
    return proj


@pytest.fixture
def mock_balance_sheet():
    proj = AsyncMock()
    return proj


@pytest.fixture
def mock_cash_flow():
    proj = AsyncMock()
    proj.compute_full_cash_flow = AsyncMock(return_value={"operating_cash_flow": Decimal("5000000")})
    return proj


@pytest.fixture
def mock_ratios_calc():
    calc = AsyncMock()
    calc.calculate_ratios = AsyncMock(return_value={
        "ratios": {
            "revenue": Decimal("1000000000"),
            "net_income": Decimal("150000000"),
            "gross_margin": Decimal("0.30"),
            "net_margin": Decimal("0.15"),
            "roa": Decimal("0.10"),
            "roe": Decimal("0.14"),
            "current_ratio": Decimal("2.0"),
            "quick_ratio": Decimal("1.5"),
            "debt_to_equity": Decimal("0.8"),
            "debt_to_assets": Decimal("0.4"),
            "inventory_turnover": Decimal("6.0"),
            "receivables_turnover": Decimal("10.0"),
        }
    })
    return calc


@pytest.fixture
def alerter(mock_session_factory, mock_income_statement, mock_balance_sheet,
            mock_cash_flow, mock_ratios_calc):
    with patch("projections.analytics_bi.kpi_threshold_alerter.get_session_factory",
               return_value=mock_session_factory):
        with patch("projections.analytics_bi.kpi_threshold_alerter.get_income_statement_projection",
                   return_value=mock_income_statement):
            with patch("projections.analytics_bi.kpi_threshold_alerter.get_balance_sheet_snapshot",
                       return_value=mock_balance_sheet):
                with patch("projections.analytics_bi.kpi_threshold_alerter.get_cash_flow_projection",
                           return_value=mock_cash_flow):
                    with patch("projections.analytics_bi.kpi_threshold_alerter.get_financial_ratios_calculator",
                               return_value=mock_ratios_calc):
                        alerter = KPIThresholdAlerter()
                        # Inject mocks directly for easier testing
                        alerter._session_factory = mock_session_factory
                        alerter._income_statement = mock_income_statement
                        alerter._balance_sheet = mock_balance_sheet
                        alerter._cash_flow = mock_cash_flow
                        alerter._ratios_calc = mock_ratios_calc
                        yield alerter


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestKPIThresholdError:
    def test_raise(self):
        with pytest.raises(KPIThresholdError):
            raise KPIThresholdError("test")


# ============================================================================
# Tests for KPIThresholdAlerter
# ============================================================================

class TestKPIThresholdAlerter:
    def test_constructor_loads_config(self):
        with patch("projections.analytics_bi.kpi_threshold_alerter.KPIThresholdAlerter._get_load_yaml_config") as mock_load:
            mock_load.return_value.return_value = {"kpi_thresholds": {}}
            KPIThresholdAlerter("dummy.yaml")
            mock_load.assert_called_once()

    def test_get_load_yaml_config(self):
        # Test lazy import returns callable
        func = KPIThresholdAlerter._get_load_yaml_config()
        assert callable(func)

    def test_load_thresholds_with_config(self):
        config = {
            "kpi_thresholds": {
                "le1": {
                    "revenue": {"warning": "100", "critical": "50"},
                    "net_income": {"warning": "200", "critical": "100"},
                }
            }
        }
        with patch.object(KPIThresholdAlerter, "_load_config", return_value=config):
            alerter = KPIThresholdAlerter()
            thresholds = alerter._load_thresholds()
            assert "le1" in thresholds
            assert thresholds["le1"]["revenue"]["warning"] == Decimal("100")
            assert thresholds["le1"]["revenue"]["critical"] == Decimal("50")
            assert thresholds["le1"]["net_income"]["warning"] == Decimal("200")

    def test_load_thresholds_with_invalid_value_falls_back_to_default(self):
        config = {
            "kpi_thresholds": {
                "le1": {
                    "revenue": {"warning": "invalid", "critical": "50"},
                }
            }
        }
        with patch.object(KPIThresholdAlerter, "_load_config", return_value=config):
            alerter = KPIThresholdAlerter()
            thresholds = alerter._load_thresholds()
            # Should fall back to default for revenue because invalid
            assert thresholds["le1"]["revenue"]["warning"] == DEFAULT_THRESHOLDS["revenue"]["warning"]

    def test_load_thresholds_empty_config_uses_defaults(self):
        with patch.object(KPIThresholdAlerter, "_load_config", return_value={}):
            alerter = KPIThresholdAlerter()
            thresholds = alerter._load_thresholds()
            assert thresholds == {}

    def test_get_threshold_for_kpi_entity_specific(self, alerter):
        # Set entity-specific threshold
        le_id_str = str(uuid4())
        alerter._thresholds[le_id_str] = {
            "revenue": {"warning": Decimal("200"), "critical": Decimal("100")}
        }
        threshold = alerter._get_threshold_for_kpi(le_id_str, "revenue")
        assert threshold["warning"] == Decimal("200")
        assert threshold["critical"] == Decimal("100")

    def test_get_threshold_for_kpi_default(self, alerter):
        le_id_str = str(uuid4())
        threshold = alerter._get_threshold_for_kpi(le_id_str, "revenue")
        # Should return default threshold
        assert threshold == DEFAULT_THRESHOLDS["revenue"]

    def test_get_threshold_for_kpi_not_found(self, alerter):
        le_id_str = str(uuid4())
        threshold = alerter._get_threshold_for_kpi(le_id_str, "nonexistent")
        assert threshold is None

    def test_is_threshold_violated_higher_is_better_warning(self):
        # Direction higher_is_better, current below warning but above critical -> warning
        threshold = {"warning": Decimal("100"), "critical": Decimal("50")}
        violated, severity = KPIThresholdAlerter._is_threshold_violated(
            Decimal("75"), threshold, "higher_is_better"
        )
        assert violated is True
        assert severity == "warning"

    def test_is_threshold_violated_higher_is_better_critical(self):
        threshold = {"warning": Decimal("100"), "critical": Decimal("50")}
        violated, severity = KPIThresholdAlerter._is_threshold_violated(
            Decimal("40"), threshold, "higher_is_better"
        )
        assert violated is True
        assert severity == "critical"

    def test_is_threshold_violated_higher_is_better_ok(self):
        threshold = {"warning": Decimal("100"), "critical": Decimal("50")}
        violated, severity = KPIThresholdAlerter._is_threshold_violated(
            Decimal("120"), threshold, "higher_is_better"
        )
        assert violated is False
        assert severity is None

    def test_is_threshold_violated_lower_is_better_warning(self):
        threshold = {"warning": Decimal("100"), "critical": Decimal("50")}
        violated, _severity = KPIThresholdAlerter._is_threshold_violated(
            Decimal("75"), threshold, "lower_is_better"
        )
        assert violated is False  # 75 <= 100, not above warning? Wait lower_is_better: warning at 100 means value >= 100 triggers warning. But 75 is less than 100, so OK.
        # Let's test with value above warning
        violated2, severity2 = KPIThresholdAlerter._is_threshold_violated(
            Decimal("120"), threshold, "lower_is_better"
        )
        assert violated2 is True
        assert severity2 == "warning"

    def test_is_threshold_violated_lower_is_better_critical(self):
        threshold = {"warning": Decimal("100"), "critical": Decimal("150")}
        violated, severity = KPIThresholdAlerter._is_threshold_violated(
            Decimal("160"), threshold, "lower_is_better"
        )
        assert violated is True
        assert severity == "critical"

    def test_is_threshold_violated_threshold_none(self):
        violated, severity = KPIThresholdAlerter._is_threshold_violated(
            Decimal("10"), None, "higher_is_better"
        )
        assert violated is False
        assert severity is None

    @pytest.mark.asyncio
    async def test_get_current_kpi_values(self, alerter, mock_ratios_calc, mock_cash_flow):
        le_id = uuid4()
        period_id = uuid4()
        values = await alerter.get_current_kpi_values(le_id, period_id)
        # Should include all KPI types
        assert "revenue" in values
        assert "net_income" in values
        assert "operating_cash_flow" in values
        assert "period_close_days" in values
        assert values["period_close_days"] == Decimal(0)
        assert values["operating_cash_flow"] == Decimal("5000000")
        # Check that ratios were used
        mock_ratios_calc.calculate_ratios.assert_called_once_with(le_id, period_id)

    @pytest.mark.asyncio
    async def test_check_and_alert_no_violations(self, alerter, mock_ratios_calc):
        # Set thresholds high enough so no violation
        le_id = uuid4()
        period_id = uuid4()
        with patch("projections.analytics_bi.kpi_threshold_alerter.trigger_alert") as mock_alert:
            alerts = await alerter.check_and_alert(le_id, period_id)
            assert alerts == []
            mock_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_alert_with_violation(self, alerter, mock_ratios_calc):
        # Set low threshold for revenue to trigger
        le_id = uuid4()
        period_id = uuid4()
        str(le_id)
        await alerter.update_thresholds(le_id, "revenue", Decimal("100"), Decimal("50"))
        # Mock ratios to return revenue 75 -> warning
        mock_ratios_calc.calculate_ratios = AsyncMock(return_value={
            "ratios": {"revenue": Decimal("75")}
        })
        with patch("projections.analytics_bi.kpi_threshold_alerter.trigger_alert") as mock_alert:
            with patch.object(alerter, "_save_alert_history") as mock_save:
                alerts = await alerter.check_and_alert(le_id, period_id)
                assert len(alerts) == 1
                assert alerts[0]["kpi"] == "revenue"
                assert alerts[0]["severity"] == "warning"
                assert alerts[0]["current_value"] == Decimal("75")
                mock_alert.assert_called_once()
                mock_save.assert_called_once_with(le_id, period_id, alerts)

    @pytest.mark.asyncio
    async def test_check_and_alert_with_cooldown(self, alerter, mock_ratios_calc):
        # Trigger alert, then check again immediately -> should not re-alert due to cooldown
        le_id = uuid4()
        period_id = uuid4()
        str(le_id)
        await alerter.update_thresholds(le_id, "revenue", Decimal("100"), Decimal("50"))
        mock_ratios_calc.calculate_ratios = AsyncMock(return_value={
            "ratios": {"revenue": Decimal("75")}
        })
        with patch("projections.analytics_bi.kpi_threshold_alerter.trigger_alert") as mock_alert:
            with patch.object(alerter, "_save_alert_history") as mock_save:
                # First call triggers
                alerts1 = await alerter.check_and_alert(le_id, period_id)
                assert len(alerts1) == 1
                mock_alert.assert_called_once()
                mock_save.assert_called_once()
                # Second call immediately after should not trigger due to cooldown
                mock_alert.reset_mock()
                mock_save.reset_mock()
                alerts2 = await alerter.check_and_alert(le_id, period_id)
                assert len(alerts2) == 0
                mock_alert.assert_not_called()
                mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_alert_history(self, alerter, mock_session, mock_session_factory):
        le_id = uuid4()
        period_id = uuid4()
        alerts = [
            {
                "kpi": "revenue",
                "current_value": Decimal("75"),
                "severity": "warning",
                "threshold": {"warning": Decimal("100"), "critical": Decimal("50")},
            }
        ]
        await alerter._save_alert_history(le_id, period_id, alerts)
        # Check session execute was called with insert
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_alert_history(self, alerter, mock_session):
        le_id = uuid4()
        # Mock query result
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = [
            MagicMock(
                kpi_name="revenue",
                current_value=Decimal("75"),
                severity="warning",
                threshold_warning=Decimal("100"),
                threshold_critical=Decimal("50"),
                triggered_at=datetime.now(UTC),
            )
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)
        history = await alerter.get_alert_history(le_id, limit=10)
        assert len(history) == 1
        assert history[0]["kpi_name"] == "revenue"

    @pytest.mark.asyncio
    async def test_update_thresholds(self, alerter):
        le_id = uuid4()
        le_id_str = str(le_id)
        await alerter.update_thresholds(le_id, "revenue", Decimal("80"), Decimal("40"))
        assert le_id_str in alerter._thresholds
        assert alerter._thresholds[le_id_str]["revenue"]["warning"] == Decimal("80")
        assert alerter._thresholds[le_id_str]["revenue"]["critical"] == Decimal("40")

    @pytest.mark.asyncio
    async def test_start_periodic_check(self, alerter):
        le_id = uuid4()
        period_id = uuid4()
        # Mock asyncio.sleep and check_and_alert to avoid long wait
        with patch("asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with patch.object(alerter, "check_and_alert") as mock_check:
                mock_check.return_value = []
                await alerter.start_periodic_check(le_id, period_id)
                # Ensure it started running
                assert alerter._running is True
                assert alerter._check_task is not None
                # Stop to clean up
                await alerter.stop_periodic_check()
                # During the stop, the loop cancels the task.

    @pytest.mark.asyncio
    async def test_stop_periodic_check_when_running(self, alerter):
        # Start then stop
        le_id = uuid4()
        period_id = uuid4()
        with patch("asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with patch.object(alerter, "check_and_alert") as mock_check:
                mock_check.return_value = []
                await alerter.start_periodic_check(le_id, period_id)
                assert alerter._running is True
                await alerter.stop_periodic_check()
                assert alerter._running is False
                assert alerter._check_task is None

    @pytest.mark.asyncio
    async def test_stop_periodic_check_not_running(self, alerter):
        await alerter.stop_periodic_check()
        # Should not raise

    @pytest.mark.asyncio
    async def test_run_manual_check(self, alerter):
        le_id = uuid4()
        period_id = uuid4()
        with patch.object(alerter, "check_and_alert") as mock_check:
            mock_check.return_value = [{"kpi": "revenue", "severity": "warning"}]
            result = await alerter.run_manual_check(le_id, period_id)
            assert result == [{"kpi": "revenue", "severity": "warning"}]
            mock_check.assert_called_once_with(le_id, period_id)


# ============================================================================
# Tests for ORM Model KPIAlertHistoryTable
# ============================================================================

class TestKPIAlertHistoryTable:
    def test_tablename_defined(self):
        assert hasattr(KPIAlertHistoryTable, "__tablename__")
        assert isinstance(KPIAlertHistoryTable.__tablename__, str)
        assert len(KPIAlertHistoryTable.__tablename__) > 0

    def test_instantiation(self):
        instance = KPIAlertHistoryTable(
            id=uuid4(),
            legal_entity_id=uuid4(),
            period_id=uuid4(),
            kpi_name="revenue",
            current_value=Decimal("100"),
            severity="warning",
            threshold_warning=Decimal("80"),
            threshold_critical=Decimal("50"),
            triggered_at=datetime.now(UTC),
        )
        assert isinstance(instance, KPIAlertHistoryTable)
        assert instance.kpi_name == "revenue"


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

@pytest.mark.asyncio
async def test_get_kpi_alerter():
    a1 = await get_kpi_alerter()
    a2 = await get_kpi_alerter()
    assert a1 is a2
    assert isinstance(a1, KPIThresholdAlerter)
