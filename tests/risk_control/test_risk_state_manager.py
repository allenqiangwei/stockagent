"""Tests for risk state manager."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.risk_control.risk_state_manager import (
    RiskState,
    RiskStateManager,
    MarketCondition
)


class TestRiskState:
    """Tests for RiskState enum."""

    def test_risk_state_values(self):
        """Test risk state enum values."""
        assert RiskState.RISK_OFF == 1
        assert RiskState.NEUTRAL == 2
        assert RiskState.RISK_ON == 3

    def test_risk_state_position_multiplier(self):
        """Test position multiplier for each state."""
        assert RiskState.RISK_OFF.position_multiplier == 0.0
        assert RiskState.NEUTRAL.position_multiplier == 0.5
        assert RiskState.RISK_ON.position_multiplier == 1.0

    def test_risk_state_allows_new_positions(self):
        """Test whether state allows opening new positions."""
        assert not RiskState.RISK_OFF.allows_new_positions
        assert RiskState.NEUTRAL.allows_new_positions
        assert RiskState.RISK_ON.allows_new_positions


class TestMarketCondition:
    """Tests for MarketCondition dataclass."""

    def test_market_condition_creation(self):
        """Test MarketCondition can be created."""
        condition = MarketCondition(
            index_trend_score=60.0,
            sentiment_score=55.0,
            money_flow_score=50.0,
            volatility_score=40.0
        )
        assert condition.index_trend_score == 60.0
        assert condition.sentiment_score == 55.0

    def test_market_condition_composite_score(self):
        """Test composite score calculation."""
        condition = MarketCondition(
            index_trend_score=80.0,
            sentiment_score=60.0,
            money_flow_score=70.0,
            volatility_score=50.0
        )
        # Default weights: trend 40%, sentiment 25%, money_flow 20%, volatility 15%
        expected = 80*0.4 + 60*0.25 + 70*0.2 + 50*0.15
        assert condition.composite_score == expected


class TestRiskStateManager:
    """Tests for RiskStateManager."""

    def test_manager_initialization(self):
        """Test manager initializes with NEUTRAL state."""
        manager = RiskStateManager()
        assert manager.current_state == RiskState.NEUTRAL

    def test_manager_custom_thresholds(self):
        """Test custom threshold configuration."""
        manager = RiskStateManager(
            risk_on_threshold=70.0,
            risk_off_threshold=30.0
        )
        assert manager.risk_on_threshold == 70.0
        assert manager.risk_off_threshold == 30.0

    def test_high_score_triggers_risk_on(self):
        """Test high composite score leads to RISK_ON."""
        manager = RiskStateManager(confirmation_days=1)

        # Strong bullish condition
        condition = MarketCondition(
            index_trend_score=80.0,
            sentiment_score=75.0,
            money_flow_score=70.0,
            volatility_score=60.0
        )

        manager.update("2024-01-15", condition)
        assert manager.current_state == RiskState.RISK_ON

    def test_low_score_triggers_risk_off(self):
        """Test low composite score leads to RISK_OFF."""
        manager = RiskStateManager(confirmation_days=1)

        # Strong bearish condition
        condition = MarketCondition(
            index_trend_score=20.0,
            sentiment_score=25.0,
            money_flow_score=30.0,
            volatility_score=80.0  # High volatility is bearish
        )

        manager.update("2024-01-15", condition)
        assert manager.current_state == RiskState.RISK_OFF

    def test_medium_score_triggers_neutral(self):
        """Test medium composite score leads to NEUTRAL."""
        manager = RiskStateManager(confirmation_days=1)

        # Mixed condition
        condition = MarketCondition(
            index_trend_score=50.0,
            sentiment_score=50.0,
            money_flow_score=50.0,
            volatility_score=50.0
        )

        manager.update("2024-01-15", condition)
        assert manager.current_state == RiskState.NEUTRAL

    def test_two_day_confirmation(self):
        """Test state change requires 2-day confirmation."""
        manager = RiskStateManager(confirmation_days=2)

        # Start neutral
        assert manager.current_state == RiskState.NEUTRAL

        # Day 1: bullish signal
        bullish = MarketCondition(
            index_trend_score=80.0,
            sentiment_score=75.0,
            money_flow_score=70.0,
            volatility_score=40.0
        )
        manager.update("2024-01-15", bullish)

        # Should still be NEUTRAL (waiting for confirmation)
        assert manager.current_state == RiskState.NEUTRAL

        # Day 2: bullish signal again
        manager.update("2024-01-16", bullish)

        # Now should be RISK_ON
        assert manager.current_state == RiskState.RISK_ON

    def test_confirmation_resets_on_conflicting_signal(self):
        """Test confirmation counter resets if signal changes."""
        # Use high rapid_change_threshold to test normal confirmation logic
        manager = RiskStateManager(confirmation_days=2, rapid_change_threshold=100.0)

        bullish = MarketCondition(
            index_trend_score=80.0,
            sentiment_score=75.0,
            money_flow_score=70.0,
            volatility_score=40.0
        )
        bearish = MarketCondition(
            index_trend_score=20.0,
            sentiment_score=25.0,
            money_flow_score=30.0,
            volatility_score=80.0
        )

        # Day 1: bullish
        manager.update("2024-01-15", bullish)
        assert manager.current_state == RiskState.NEUTRAL

        # Day 2: bearish (conflicting) - resets confirmation counter
        manager.update("2024-01-16", bearish)
        assert manager.current_state == RiskState.NEUTRAL

        # Day 3: bearish again - now confirms
        manager.update("2024-01-17", bearish)
        # Now should switch to RISK_OFF
        assert manager.current_state == RiskState.RISK_OFF

    def test_get_state_history(self):
        """Test retrieving state history."""
        manager = RiskStateManager(confirmation_days=1)

        condition = MarketCondition(
            index_trend_score=80.0,
            sentiment_score=75.0,
            money_flow_score=70.0,
            volatility_score=40.0
        )

        manager.update("2024-01-15", condition)
        manager.update("2024-01-16", condition)

        history = manager.get_state_history()
        assert len(history) >= 2

    def test_rapid_market_deterioration_override(self):
        """Test rapid deterioration bypasses confirmation."""
        manager = RiskStateManager(
            confirmation_days=2,
            rapid_change_threshold=30.0
        )

        # Start with good conditions
        good = MarketCondition(
            index_trend_score=70.0,
            sentiment_score=70.0,
            money_flow_score=70.0,
            volatility_score=30.0
        )
        manager.update("2024-01-15", good)
        manager.update("2024-01-16", good)  # Confirm RISK_ON

        # Sudden crash (score drops > 30 points)
        crash = MarketCondition(
            index_trend_score=20.0,
            sentiment_score=25.0,
            money_flow_score=20.0,
            volatility_score=90.0
        )
        manager.update("2024-01-17", crash)

        # Should immediately go to RISK_OFF despite confirmation_days=2
        assert manager.current_state == RiskState.RISK_OFF

    def test_volatility_inverted_for_scoring(self):
        """Test high volatility reduces composite score."""
        # High volatility = bad for market
        high_vol = MarketCondition(
            index_trend_score=50.0,
            sentiment_score=50.0,
            money_flow_score=50.0,
            volatility_score=90.0  # High volatility
        )

        low_vol = MarketCondition(
            index_trend_score=50.0,
            sentiment_score=50.0,
            money_flow_score=50.0,
            volatility_score=10.0  # Low volatility
        )

        # High volatility should result in lower composite
        assert high_vol.composite_score < low_vol.composite_score
