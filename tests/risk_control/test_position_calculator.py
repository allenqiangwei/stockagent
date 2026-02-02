"""Tests for position calculator."""

import pytest
import pandas as pd
import numpy as np
from src.risk_control.position_calculator import (
    PositionCalculator,
    PositionRecommendation,
    PortfolioConstraints
)
from src.risk_control.risk_state_manager import RiskState


class TestPortfolioConstraints:
    """Tests for PortfolioConstraints dataclass."""

    def test_default_constraints(self):
        """Test default constraint values."""
        constraints = PortfolioConstraints()
        assert constraints.max_position_pct == 0.25
        assert constraints.target_total_pct == 0.60
        assert constraints.max_stocks == 10
        assert constraints.min_position_pct == 0.05

    def test_custom_constraints(self):
        """Test custom constraint values."""
        constraints = PortfolioConstraints(
            max_position_pct=0.20,
            target_total_pct=0.50
        )
        assert constraints.max_position_pct == 0.20
        assert constraints.target_total_pct == 0.50


class TestPositionRecommendation:
    """Tests for PositionRecommendation dataclass."""

    def test_recommendation_creation(self):
        """Test recommendation can be created."""
        rec = PositionRecommendation(
            stock_code="000001.SZ",
            position_pct=0.15,
            position_value=15000.0,
            signal_score=75.0,
            volatility_adjustment=0.9,
            risk_state_adjustment=1.0,
            reason="Strong buy signal with moderate volatility"
        )
        assert rec.stock_code == "000001.SZ"
        assert rec.position_pct == 0.15


class TestPositionCalculator:
    """Tests for PositionCalculator."""

    @pytest.fixture
    def calculator(self):
        """Create calculator with default settings."""
        return PositionCalculator()

    def test_calculator_initialization(self, calculator):
        """Test calculator initializes correctly."""
        assert calculator is not None
        assert calculator.constraints is not None

    def test_calculate_single_position(self, calculator):
        """Test calculating position for single stock."""
        rec = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=80.0,
            atr_pct=2.0,  # 2% ATR
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        assert isinstance(rec, PositionRecommendation)
        assert rec.stock_code == "000001.SZ"
        assert 0 < rec.position_pct <= 0.25  # Max position constraint

    def test_strong_signal_larger_position(self, calculator):
        """Test stronger signal results in larger position."""
        strong = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=90.0,
            atr_pct=2.0,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        weak = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=60.0,
            atr_pct=2.0,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        assert strong.position_pct > weak.position_pct

    def test_high_volatility_smaller_position(self, calculator):
        """Test higher volatility results in smaller position."""
        low_vol = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=75.0,
            atr_pct=1.0,  # 1% ATR - low volatility
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        high_vol = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=75.0,
            atr_pct=5.0,  # 5% ATR - high volatility
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        assert low_vol.position_pct > high_vol.position_pct

    def test_risk_off_zero_position(self, calculator):
        """Test RISK_OFF state results in zero new position."""
        rec = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=90.0,
            atr_pct=2.0,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_OFF
        )

        assert rec.position_pct == 0.0
        assert rec.position_value == 0.0

    def test_neutral_reduced_position(self, calculator):
        """Test NEUTRAL state reduces position by 50%."""
        risk_on = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=80.0,
            atr_pct=2.0,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        neutral = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=80.0,
            atr_pct=2.0,
            portfolio_value=100000.0,
            risk_state=RiskState.NEUTRAL
        )

        assert neutral.position_pct == pytest.approx(risk_on.position_pct * 0.5, rel=0.01)

    def test_position_capped_at_max(self, calculator):
        """Test position is capped at max_position_pct."""
        rec = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=100.0,  # Maximum signal
            atr_pct=0.5,  # Very low volatility
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        assert rec.position_pct <= calculator.constraints.max_position_pct

    def test_position_value_matches_pct(self, calculator):
        """Test position value equals pct * portfolio value."""
        portfolio_value = 100000.0
        rec = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=75.0,
            atr_pct=2.0,
            portfolio_value=portfolio_value,
            risk_state=RiskState.RISK_ON
        )

        expected_value = rec.position_pct * portfolio_value
        assert rec.position_value == pytest.approx(expected_value, rel=0.01)

    def test_calculate_portfolio_allocation(self, calculator):
        """Test calculating positions for multiple stocks."""
        signals = [
            {"stock_code": "000001.SZ", "signal_score": 85.0, "atr_pct": 2.0},
            {"stock_code": "000002.SZ", "signal_score": 75.0, "atr_pct": 2.5},
            {"stock_code": "600000.SH", "signal_score": 80.0, "atr_pct": 1.5},
        ]

        recommendations = calculator.calculate_portfolio_allocation(
            signals=signals,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        assert len(recommendations) == 3
        # Total should not exceed target
        total_pct = sum(r.position_pct for r in recommendations)
        assert total_pct <= calculator.constraints.target_total_pct

    def test_portfolio_allocation_respects_max_stocks(self):
        """Test portfolio limits number of stocks."""
        constraints = PortfolioConstraints(max_stocks=2)
        calculator = PositionCalculator(constraints=constraints)

        signals = [
            {"stock_code": "000001.SZ", "signal_score": 85.0, "atr_pct": 2.0},
            {"stock_code": "000002.SZ", "signal_score": 80.0, "atr_pct": 2.0},
            {"stock_code": "000003.SZ", "signal_score": 75.0, "atr_pct": 2.0},
        ]

        recommendations = calculator.calculate_portfolio_allocation(
            signals=signals,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        assert len(recommendations) <= 2

    def test_portfolio_sorted_by_signal_strength(self):
        """Test portfolio recommendations sorted by signal score."""
        calculator = PositionCalculator()

        signals = [
            {"stock_code": "000003.SZ", "signal_score": 70.0, "atr_pct": 2.0},
            {"stock_code": "000001.SZ", "signal_score": 90.0, "atr_pct": 2.0},
            {"stock_code": "000002.SZ", "signal_score": 80.0, "atr_pct": 2.0},
        ]

        recommendations = calculator.calculate_portfolio_allocation(
            signals=signals,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )

        # Should be sorted by signal score descending
        scores = [r.signal_score for r in recommendations]
        assert scores == sorted(scores, reverse=True)

    def test_weak_signals_excluded(self, calculator):
        """Test signals below threshold are excluded."""
        signals = [
            {"stock_code": "000001.SZ", "signal_score": 80.0, "atr_pct": 2.0},
            {"stock_code": "000002.SZ", "signal_score": 55.0, "atr_pct": 2.0},  # Below 60
        ]

        recommendations = calculator.calculate_portfolio_allocation(
            signals=signals,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON,
            min_signal_score=60.0
        )

        assert len(recommendations) == 1
        assert recommendations[0].stock_code == "000001.SZ"
