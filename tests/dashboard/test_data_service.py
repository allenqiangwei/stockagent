"""Tests for dashboard data service."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.dashboard.data_service import (
    DashboardDataService,
    MarketOverview,
    SignalSummary,
    PositionSummary,
    RiskStatusSummary
)


class TestMarketOverview:
    """Tests for MarketOverview dataclass."""

    def test_market_overview_creation(self):
        """Test market overview can be created."""
        overview = MarketOverview(
            date="2024-01-15",
            risk_state="RISK_ON",
            risk_score=72.5,
            index_name="上证指数",
            index_value=3150.25,
            index_change_pct=1.25,
            advance_count=2500,
            decline_count=1800,
            market_breadth=0.58
        )
        assert overview.risk_state == "RISK_ON"
        assert overview.market_breadth == 0.58


class TestSignalSummary:
    """Tests for SignalSummary dataclass."""

    def test_signal_summary_creation(self):
        """Test signal summary can be created."""
        summary = SignalSummary(
            stock_code="000001.SZ",
            stock_name="平安银行",
            signal_type="STRONG_BUY",
            signal_score=85.0,
            recommended_position_pct=0.15,
            recommended_value=15000.0,
            atr_pct=2.5,
            reason="Strong momentum and trend alignment"
        )
        assert summary.signal_type == "STRONG_BUY"
        assert summary.signal_score == 85.0


class TestPositionSummary:
    """Tests for PositionSummary dataclass."""

    def test_position_summary_creation(self):
        """Test position summary can be created."""
        summary = PositionSummary(
            stock_code="000001.SZ",
            stock_name="平安银行",
            entry_price=10.0,
            current_price=11.0,
            quantity=1000,
            position_value=11000.0,
            pnl_value=1000.0,
            pnl_pct=10.0,
            stop_price=9.5,
            stop_type="trailing",
            days_held=5
        )
        assert summary.pnl_pct == 10.0
        assert summary.stop_type == "trailing"


class TestRiskStatusSummary:
    """Tests for RiskStatusSummary dataclass."""

    def test_risk_status_creation(self):
        """Test risk status can be created."""
        status = RiskStatusSummary(
            current_state="RISK_ON",
            state_since="2024-01-10",
            days_in_state=5,
            composite_score=72.5,
            index_trend_score=75.0,
            sentiment_score=68.0,
            money_flow_score=70.0,
            volatility_score=35.0,
            position_multiplier=1.0,
            allows_new_positions=True
        )
        assert status.current_state == "RISK_ON"
        assert status.allows_new_positions


class TestDashboardDataService:
    """Tests for DashboardDataService."""

    @pytest.fixture
    def service(self):
        """Create data service for testing."""
        return DashboardDataService()

    def test_service_initialization(self, service):
        """Test service initializes correctly."""
        assert service is not None

    def test_get_market_overview_structure(self, service):
        """Test market overview returns correct structure."""
        # Create mock data
        index_data = pd.DataFrame({
            "trade_date": ["20240115", "20240114"],
            "close": [3150.25, 3111.32],
            "pct_chg": [1.25, -0.5]
        })

        overview = service.get_market_overview(
            index_data=index_data,
            risk_state="RISK_ON",
            risk_score=72.5,
            advance_count=2500,
            decline_count=1800
        )

        assert isinstance(overview, MarketOverview)
        assert overview.index_value == 3150.25
        assert overview.index_change_pct == 1.25
        assert overview.market_breadth == pytest.approx(2500 / (2500 + 1800), rel=0.01)

    def test_get_signal_summaries(self, service):
        """Test getting signal summaries."""
        signals = [
            {
                "stock_code": "000001.SZ",
                "stock_name": "平安银行",
                "signal_type": "STRONG_BUY",
                "signal_score": 85.0,
                "position_pct": 0.15,
                "position_value": 15000.0,
                "atr_pct": 2.5,
                "reason": "Strong signal"
            },
            {
                "stock_code": "000002.SZ",
                "stock_name": "万科A",
                "signal_type": "WEAK_BUY",
                "signal_score": 65.0,
                "position_pct": 0.08,
                "position_value": 8000.0,
                "atr_pct": 3.0,
                "reason": "Moderate signal"
            }
        ]

        summaries = service.get_signal_summaries(signals)

        assert len(summaries) == 2
        assert summaries[0].stock_code == "000001.SZ"
        assert summaries[0].signal_type == "STRONG_BUY"

    def test_get_position_summaries(self, service):
        """Test getting position summaries."""
        positions = [
            {
                "stock_code": "000001.SZ",
                "stock_name": "平安银行",
                "entry_price": 10.0,
                "current_price": 11.0,
                "quantity": 1000,
                "entry_date": "2024-01-10",
                "highest_price": 11.5
            }
        ]
        stop_results = [
            {
                "stock_code": "000001.SZ",
                "stop_price": 10.5,
                "stop_type": "trailing"
            }
        ]
        current_date = "2024-01-15"

        summaries = service.get_position_summaries(
            positions=positions,
            stop_results=stop_results,
            current_date=current_date
        )

        assert len(summaries) == 1
        assert summaries[0].pnl_pct == 10.0  # (11-10)/10 * 100
        assert summaries[0].pnl_value == 1000.0  # (11-10) * 1000
        assert summaries[0].days_held == 5

    def test_get_risk_status_summary(self, service):
        """Test getting risk status summary."""
        risk_state = "RISK_ON"
        market_condition = {
            "index_trend_score": 75.0,
            "sentiment_score": 68.0,
            "money_flow_score": 70.0,
            "volatility_score": 35.0,
            "composite_score": 72.5
        }
        state_history = [
            {"date": "2024-01-10", "state": "RISK_ON"},
            {"date": "2024-01-09", "state": "NEUTRAL"},
        ]
        current_date = "2024-01-15"

        summary = service.get_risk_status_summary(
            risk_state=risk_state,
            market_condition=market_condition,
            state_history=state_history,
            current_date=current_date
        )

        assert summary.current_state == "RISK_ON"
        assert summary.days_in_state == 5
        assert summary.composite_score == 72.5
        assert summary.allows_new_positions

    def test_format_signals_for_table(self, service):
        """Test formatting signals for display table."""
        signals = [
            SignalSummary(
                stock_code="000001.SZ",
                stock_name="平安银行",
                signal_type="STRONG_BUY",
                signal_score=85.0,
                recommended_position_pct=0.15,
                recommended_value=15000.0,
                atr_pct=2.5,
                reason="Strong signal"
            )
        ]

        df = service.format_signals_for_table(signals)

        assert isinstance(df, pd.DataFrame)
        assert "代码" in df.columns
        assert "名称" in df.columns
        assert "信号" in df.columns
        assert len(df) == 1

    def test_format_positions_for_table(self, service):
        """Test formatting positions for display table."""
        positions = [
            PositionSummary(
                stock_code="000001.SZ",
                stock_name="平安银行",
                entry_price=10.0,
                current_price=11.0,
                quantity=1000,
                position_value=11000.0,
                pnl_value=1000.0,
                pnl_pct=10.0,
                stop_price=9.5,
                stop_type="trailing",
                days_held=5
            )
        ]

        df = service.format_positions_for_table(positions)

        assert isinstance(df, pd.DataFrame)
        assert "代码" in df.columns
        assert "盈亏%" in df.columns
        assert len(df) == 1

    def test_calculate_portfolio_metrics(self, service):
        """Test calculating portfolio-level metrics."""
        positions = [
            PositionSummary(
                stock_code="000001.SZ",
                stock_name="平安银行",
                entry_price=10.0,
                current_price=11.0,
                quantity=1000,
                position_value=11000.0,
                pnl_value=1000.0,
                pnl_pct=10.0,
                stop_price=9.5,
                stop_type="trailing",
                days_held=5
            ),
            PositionSummary(
                stock_code="000002.SZ",
                stock_name="万科A",
                entry_price=20.0,
                current_price=19.0,
                quantity=500,
                position_value=9500.0,
                pnl_value=-500.0,
                pnl_pct=-5.0,
                stop_price=18.0,
                stop_type="fixed",
                days_held=3
            )
        ]
        total_portfolio_value = 100000.0

        metrics = service.calculate_portfolio_metrics(positions, total_portfolio_value)

        assert metrics["total_invested"] == 20500.0
        assert metrics["total_pnl"] == 500.0
        assert metrics["invested_pct"] == pytest.approx(0.205, rel=0.01)
        assert metrics["position_count"] == 2
        assert metrics["winning_count"] == 1
        assert metrics["losing_count"] == 1

