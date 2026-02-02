"""Tests for risk controller integration."""

import pytest
from src.risk_control.risk_controller import (
    RiskController,
    TradingRecommendation,
    PortfolioStatus
)
from src.risk_control.risk_state_manager import RiskState, MarketCondition
from src.risk_control.position_calculator import PortfolioConstraints
from src.risk_control.stop_loss_manager import Position, StopType


class TestTradingRecommendation:
    """Tests for TradingRecommendation dataclass."""

    def test_recommendation_creation(self):
        """Test trading recommendation can be created."""
        rec = TradingRecommendation(
            stock_code="000001.SZ",
            action="BUY",
            position_pct=0.15,
            position_value=15000.0,
            signal_score=75.0,
            risk_state=RiskState.RISK_ON,
            reason="Strong signal in RISK_ON market"
        )
        assert rec.stock_code == "000001.SZ"
        assert rec.action == "BUY"
        assert rec.position_pct == 0.15


class TestPortfolioStatus:
    """Tests for PortfolioStatus dataclass."""

    def test_status_creation(self):
        """Test portfolio status can be created."""
        status = PortfolioStatus(
            total_value=100000.0,
            cash_value=40000.0,
            invested_value=60000.0,
            invested_pct=0.60,
            risk_state=RiskState.RISK_ON,
            positions_count=3,
            stop_alerts=[]
        )
        assert status.total_value == 100000.0
        assert status.invested_pct == 0.60


class TestRiskController:
    """Tests for RiskController."""

    @pytest.fixture
    def controller(self):
        """Create controller with default settings."""
        return RiskController()

    @pytest.fixture
    def bullish_condition(self):
        """Create bullish market condition."""
        return MarketCondition(
            index_trend_score=80.0,
            sentiment_score=75.0,
            money_flow_score=70.0,
            volatility_score=40.0
        )

    @pytest.fixture
    def bearish_condition(self):
        """Create bearish market condition."""
        return MarketCondition(
            index_trend_score=20.0,
            sentiment_score=25.0,
            money_flow_score=30.0,
            volatility_score=80.0
        )

    def test_controller_initialization(self, controller):
        """Test controller initializes correctly."""
        assert controller is not None
        assert controller.risk_state_manager is not None
        assert controller.position_calculator is not None
        assert controller.stop_loss_manager is not None

    def test_controller_custom_constraints(self):
        """Test custom constraints configuration."""
        constraints = PortfolioConstraints(
            max_position_pct=0.20,
            target_total_pct=0.50
        )
        controller = RiskController(constraints=constraints)
        assert controller.position_calculator.constraints.max_position_pct == 0.20

    def test_update_market_state(self, controller, bullish_condition):
        """Test market state update."""
        controller.update_market_state("2024-01-15", bullish_condition)
        assert controller.current_risk_state in [RiskState.RISK_ON, RiskState.NEUTRAL]

    def test_get_current_risk_state(self, controller):
        """Test getting current risk state."""
        state = controller.current_risk_state
        assert isinstance(state, RiskState)

    def test_generate_buy_recommendations_risk_on(self, controller, bullish_condition):
        """Test buy recommendations in RISK_ON state."""
        # Update to RISK_ON state
        controller.update_market_state("2024-01-15", bullish_condition)

        signals = [
            {"stock_code": "000001.SZ", "signal_score": 85.0, "atr_pct": 2.0},
            {"stock_code": "000002.SZ", "signal_score": 75.0, "atr_pct": 2.5},
        ]

        recommendations = controller.generate_buy_recommendations(
            signals=signals,
            portfolio_value=100000.0
        )

        assert len(recommendations) > 0
        for rec in recommendations:
            assert rec.action == "BUY"
            assert rec.position_pct > 0

    def test_generate_buy_recommendations_risk_off(self, bearish_condition):
        """Test buy recommendations in RISK_OFF state."""
        # Use confirmation_days=1 for immediate state change
        controller = RiskController(confirmation_days=1)

        # Update to RISK_OFF state
        controller.update_market_state("2024-01-15", bearish_condition)

        signals = [
            {"stock_code": "000001.SZ", "signal_score": 85.0, "atr_pct": 2.0},
        ]

        recommendations = controller.generate_buy_recommendations(
            signals=signals,
            portfolio_value=100000.0
        )

        # In RISK_OFF, should either have no recommendations or all zero positions
        for rec in recommendations:
            assert rec.position_pct == 0.0

    def test_check_stop_losses(self, controller):
        """Test stop loss checking for positions."""
        positions = [
            Position("000001.SZ", 10.0, 9.4, 1000, "2024-01-15"),  # Should stop
            Position("000002.SZ", 10.0, 10.5, 1000, "2024-01-15", highest_price=10.5),  # OK
        ]
        atrs = {"000001.SZ": 0.3, "000002.SZ": 0.3}

        results = controller.check_stop_losses(positions, atrs)

        assert len(results) == 2
        assert results[0].should_stop  # First position should stop
        assert not results[1].should_stop  # Second position OK

    def test_get_sell_recommendations(self, controller):
        """Test generating sell recommendations from stop losses."""
        positions = [
            Position("000001.SZ", 10.0, 9.4, 1000, "2024-01-15"),  # Should stop
            Position("000002.SZ", 10.0, 10.5, 1000, "2024-01-15", highest_price=10.5),  # OK
        ]
        atrs = {"000001.SZ": 0.3, "000002.SZ": 0.3}

        sell_recs = controller.get_sell_recommendations(positions, atrs)

        # Only positions that hit stop loss should have sell recommendations
        assert len(sell_recs) == 1
        assert sell_recs[0].stock_code == "000001.SZ"
        assert sell_recs[0].action == "SELL"

    def test_update_position_tracking(self, controller):
        """Test position tracking updates highest prices."""
        positions = [
            Position("000001.SZ", 10.0, 12.0, 1000, "2024-01-15", highest_price=11.0),
        ]

        controller.update_position_tracking(positions)

        # Highest price should be updated to current
        assert positions[0].highest_price == 12.0

    def test_get_portfolio_status(self, controller, bullish_condition):
        """Test getting full portfolio status."""
        controller.update_market_state("2024-01-15", bullish_condition)

        positions = [
            Position("000001.SZ", 10.0, 11.0, 1000, "2024-01-15"),  # Value: 11000
            Position("000002.SZ", 20.0, 22.0, 500, "2024-01-15"),   # Value: 11000
        ]
        atrs = {"000001.SZ": 0.3, "000002.SZ": 0.4}

        status = controller.get_portfolio_status(
            positions=positions,
            atrs=atrs,
            total_portfolio_value=100000.0
        )

        assert status.total_value == 100000.0
        assert status.positions_count == 2
        assert status.invested_value == 22000.0  # 11000 + 11000
        assert isinstance(status.risk_state, RiskState)

    def test_full_workflow(self, controller, bullish_condition):
        """Test complete trading workflow."""
        # 1. Update market state
        controller.update_market_state("2024-01-15", bullish_condition)

        # 2. Generate buy recommendations
        signals = [
            {"stock_code": "000001.SZ", "signal_score": 80.0, "atr_pct": 2.0},
        ]
        buy_recs = controller.generate_buy_recommendations(
            signals=signals,
            portfolio_value=100000.0
        )

        assert len(buy_recs) > 0

        # 3. Simulate position opened
        positions = [
            Position("000001.SZ", 10.0, 10.5, 1000, "2024-01-15"),
        ]

        # 4. Update tracking
        controller.update_position_tracking(positions)

        # 5. Check stop losses
        results = controller.check_stop_losses(positions, {"000001.SZ": 0.3})

        # Position is profitable, no stop triggered
        assert not results[0].should_stop

    def test_risk_state_affects_position_size(self, controller, bullish_condition, bearish_condition):
        """Test that risk state affects position sizing."""
        signals = [{"stock_code": "000001.SZ", "signal_score": 80.0, "atr_pct": 2.0}]

        # RISK_ON: full position
        controller.update_market_state("2024-01-15", bullish_condition)
        risk_on_recs = controller.generate_buy_recommendations(signals, 100000.0)

        # Reset and try NEUTRAL
        controller = RiskController()
        neutral_condition = MarketCondition(
            index_trend_score=50.0,
            sentiment_score=50.0,
            money_flow_score=50.0,
            volatility_score=50.0
        )
        controller.update_market_state("2024-01-15", neutral_condition)
        neutral_recs = controller.generate_buy_recommendations(signals, 100000.0)

        # NEUTRAL should have smaller or zero position
        if len(risk_on_recs) > 0 and len(neutral_recs) > 0:
            assert neutral_recs[0].position_pct <= risk_on_recs[0].position_pct

