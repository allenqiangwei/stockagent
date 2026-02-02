"""Risk controller that integrates all risk management components."""

from dataclasses import dataclass
from typing import Optional

from .risk_state_manager import RiskStateManager, RiskState, MarketCondition
from .position_calculator import PositionCalculator, PortfolioConstraints
from .stop_loss_manager import StopLossManager, StopLossResult, Position


@dataclass
class TradingRecommendation:
    """Trading recommendation with risk context.

    Attributes:
        stock_code: Stock identifier
        action: "BUY", "SELL", or "HOLD"
        position_pct: Position as percentage of portfolio
        position_value: Position in currency units
        signal_score: Original signal score
        risk_state: Current market risk state
        reason: Human-readable explanation
    """
    stock_code: str
    action: str
    position_pct: float
    position_value: float
    signal_score: float
    risk_state: RiskState
    reason: str


@dataclass
class PortfolioStatus:
    """Current portfolio status summary.

    Attributes:
        total_value: Total portfolio value
        cash_value: Available cash
        invested_value: Value in positions
        invested_pct: Percentage invested
        risk_state: Current market risk state
        positions_count: Number of open positions
        stop_alerts: List of positions near or at stop loss
    """
    total_value: float
    cash_value: float
    invested_value: float
    invested_pct: float
    risk_state: RiskState
    positions_count: int
    stop_alerts: list[StopLossResult]


class RiskController:
    """Unified risk management interface.

    Integrates risk state management, position sizing, and stop loss
    management into a single facade for trading decisions.

    Usage:
        controller = RiskController()

        # Update market state daily
        controller.update_market_state("2024-01-15", market_condition)

        # Get buy recommendations
        recommendations = controller.generate_buy_recommendations(
            signals=signals,
            portfolio_value=100000.0
        )

        # Check existing positions for stop losses
        sell_recs = controller.get_sell_recommendations(positions, atrs)
    """

    def __init__(
        self,
        constraints: Optional[PortfolioConstraints] = None,
        fixed_stop_pct: float = 0.05,
        atr_multiplier: float = 2.0,
        risk_on_threshold: float = 60.0,
        risk_off_threshold: float = 40.0,
        confirmation_days: int = 2
    ):
        """Initialize risk controller.

        Args:
            constraints: Portfolio constraints for position sizing
            fixed_stop_pct: Fixed stop loss percentage
            atr_multiplier: ATR multiplier for trailing stop
            risk_on_threshold: Score threshold for RISK_ON state
            risk_off_threshold: Score threshold for RISK_OFF state
            confirmation_days: Days to confirm state change
        """
        self.risk_state_manager = RiskStateManager(
            risk_on_threshold=risk_on_threshold,
            risk_off_threshold=risk_off_threshold,
            confirmation_days=confirmation_days
        )
        self.position_calculator = PositionCalculator(
            constraints=constraints
        )
        self.stop_loss_manager = StopLossManager(
            fixed_stop_pct=fixed_stop_pct,
            atr_multiplier=atr_multiplier
        )

    @property
    def current_risk_state(self) -> RiskState:
        """Get current market risk state."""
        return self.risk_state_manager.current_state

    def update_market_state(
        self,
        date: str,
        condition: MarketCondition
    ) -> RiskState:
        """Update market condition and risk state.

        Args:
            date: Date string (YYYY-MM-DD)
            condition: Current market condition metrics

        Returns:
            Updated risk state
        """
        self.risk_state_manager.update(date, condition)
        return self.current_risk_state

    def generate_buy_recommendations(
        self,
        signals: list[dict],
        portfolio_value: float,
        min_signal_score: float = 60.0
    ) -> list[TradingRecommendation]:
        """Generate buy recommendations based on signals and risk state.

        Args:
            signals: List of dicts with stock_code, signal_score, atr_pct
            portfolio_value: Total portfolio value
            min_signal_score: Minimum score to include

        Returns:
            List of TradingRecommendation for buys
        """
        position_recs = self.position_calculator.calculate_portfolio_allocation(
            signals=signals,
            portfolio_value=portfolio_value,
            risk_state=self.current_risk_state,
            min_signal_score=min_signal_score
        )

        recommendations = []
        for pos_rec in position_recs:
            rec = TradingRecommendation(
                stock_code=pos_rec.stock_code,
                action="BUY",
                position_pct=pos_rec.position_pct,
                position_value=pos_rec.position_value,
                signal_score=pos_rec.signal_score,
                risk_state=self.current_risk_state,
                reason=pos_rec.reason
            )
            recommendations.append(rec)

        return recommendations

    def check_stop_losses(
        self,
        positions: list[Position],
        atrs: dict[str, float]
    ) -> list[StopLossResult]:
        """Check stop loss conditions for all positions.

        Args:
            positions: List of current positions
            atrs: Dict mapping stock_code to ATR value

        Returns:
            List of StopLossResult for each position
        """
        return self.stop_loss_manager.check_batch(positions, atrs)

    def get_sell_recommendations(
        self,
        positions: list[Position],
        atrs: dict[str, float]
    ) -> list[TradingRecommendation]:
        """Generate sell recommendations based on stop losses.

        Args:
            positions: List of current positions
            atrs: Dict mapping stock_code to ATR value

        Returns:
            List of TradingRecommendation for sells
        """
        stop_results = self.check_stop_losses(positions, atrs)

        recommendations = []
        for result in stop_results:
            if result.should_stop:
                rec = TradingRecommendation(
                    stock_code=result.stock_code,
                    action="SELL",
                    position_pct=0.0,
                    position_value=0.0,
                    signal_score=0.0,
                    risk_state=self.current_risk_state,
                    reason=result.reason
                )
                recommendations.append(rec)

        return recommendations

    def update_position_tracking(
        self,
        positions: list[Position]
    ) -> None:
        """Update position tracking (highest prices for trailing stops).

        Args:
            positions: List of positions to update (modified in place)
        """
        for pos in positions:
            self.stop_loss_manager.update_position(pos)

    def get_portfolio_status(
        self,
        positions: list[Position],
        atrs: dict[str, float],
        total_portfolio_value: float
    ) -> PortfolioStatus:
        """Get comprehensive portfolio status.

        Args:
            positions: List of current positions
            atrs: Dict mapping stock_code to ATR value
            total_portfolio_value: Total portfolio value

        Returns:
            PortfolioStatus with summary information
        """
        # Calculate invested value
        invested_value = sum(
            pos.current_price * pos.quantity
            for pos in positions
        )
        cash_value = total_portfolio_value - invested_value
        invested_pct = invested_value / total_portfolio_value if total_portfolio_value > 0 else 0.0

        # Check for stop alerts
        stop_results = self.check_stop_losses(positions, atrs)
        stop_alerts = [r for r in stop_results if r.should_stop]

        return PortfolioStatus(
            total_value=total_portfolio_value,
            cash_value=cash_value,
            invested_value=invested_value,
            invested_pct=invested_pct,
            risk_state=self.current_risk_state,
            positions_count=len(positions),
            stop_alerts=stop_alerts
        )

