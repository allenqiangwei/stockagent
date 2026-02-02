"""Position sizing calculator with volatility adjustment."""

from dataclasses import dataclass
from typing import Optional

from .risk_state_manager import RiskState


@dataclass
class PortfolioConstraints:
    """Portfolio-level position constraints.

    Attributes:
        max_position_pct: Maximum position size per stock (default: 25%)
        target_total_pct: Target total portfolio allocation (default: 60%)
        max_stocks: Maximum number of stocks to hold (default: 10)
        min_position_pct: Minimum position size (default: 5%)
    """
    max_position_pct: float = 0.25
    target_total_pct: float = 0.60
    max_stocks: int = 10
    min_position_pct: float = 0.05


@dataclass
class PositionRecommendation:
    """Position size recommendation for a stock.

    Attributes:
        stock_code: Stock identifier
        position_pct: Recommended position as percentage of portfolio
        position_value: Recommended position in currency units
        signal_score: Original signal score (0-100)
        volatility_adjustment: Multiplier from volatility (0-1)
        risk_state_adjustment: Multiplier from risk state (0-1)
        reason: Human-readable explanation
    """
    stock_code: str
    position_pct: float
    position_value: float
    signal_score: float
    volatility_adjustment: float
    risk_state_adjustment: float
    reason: str


class PositionCalculator:
    """Calculates position sizes based on signal strength and volatility.

    Position sizing formula:
    1. Base size from signal score: (score - 50) / 50 * base_allocation
    2. Volatility adjustment: scale down for high ATR stocks
    3. Risk state adjustment: multiply by state multiplier
    4. Apply constraints: cap at max, enforce minimum

    Usage:
        calculator = PositionCalculator()
        rec = calculator.calculate_position(
            stock_code="000001.SZ",
            signal_score=80.0,
            atr_pct=2.5,
            portfolio_value=100000.0,
            risk_state=RiskState.RISK_ON
        )
    """

    # Target ATR for position sizing (2% is considered normal)
    TARGET_ATR_PCT = 2.0

    # Base allocation for a perfect signal (100 score)
    BASE_ALLOCATION = 0.20

    def __init__(
        self,
        constraints: Optional[PortfolioConstraints] = None
    ):
        """Initialize position calculator.

        Args:
            constraints: Portfolio constraints (default: PortfolioConstraints())
        """
        self.constraints = constraints or PortfolioConstraints()

    def calculate_position(
        self,
        stock_code: str,
        signal_score: float,
        atr_pct: float,
        portfolio_value: float,
        risk_state: RiskState
    ) -> PositionRecommendation:
        """Calculate position size for a single stock.

        Args:
            stock_code: Stock identifier
            signal_score: Signal strength (0-100, >50 is bullish)
            atr_pct: Average True Range as percentage of price
            portfolio_value: Total portfolio value
            risk_state: Current market risk state

        Returns:
            PositionRecommendation with calculated size
        """
        # Check if we can open new positions
        if not risk_state.allows_new_positions:
            return PositionRecommendation(
                stock_code=stock_code,
                position_pct=0.0,
                position_value=0.0,
                signal_score=signal_score,
                volatility_adjustment=0.0,
                risk_state_adjustment=0.0,
                reason="RISK_OFF: No new positions allowed"
            )

        # 1. Base size from signal strength
        # Score 50 -> 0%, Score 100 -> BASE_ALLOCATION
        signal_factor = max(0, (signal_score - 50) / 50)
        base_size = signal_factor * self.BASE_ALLOCATION

        # 2. Volatility adjustment
        # High ATR -> smaller position, Low ATR -> larger position
        vol_adjustment = min(1.0, self.TARGET_ATR_PCT / max(0.5, atr_pct))

        # 3. Risk state adjustment
        risk_adjustment = risk_state.position_multiplier

        # 4. Calculate final position
        position_pct = base_size * vol_adjustment * risk_adjustment

        # 5. Apply constraints
        position_pct = min(position_pct, self.constraints.max_position_pct)

        # Round to reasonable precision
        position_pct = round(position_pct, 4)
        position_value = round(position_pct * portfolio_value, 2)

        # Build reason
        reasons = []
        if signal_score >= 80:
            reasons.append(f"Strong signal ({signal_score:.0f})")
        elif signal_score >= 60:
            reasons.append(f"Moderate signal ({signal_score:.0f})")
        else:
            reasons.append(f"Weak signal ({signal_score:.0f})")

        if vol_adjustment < 0.8:
            reasons.append(f"high volatility (ATR {atr_pct:.1f}%)")
        elif vol_adjustment > 1.0:
            reasons.append(f"low volatility (ATR {atr_pct:.1f}%)")

        if risk_state == RiskState.NEUTRAL:
            reasons.append("reduced for NEUTRAL market")

        return PositionRecommendation(
            stock_code=stock_code,
            position_pct=position_pct,
            position_value=position_value,
            signal_score=signal_score,
            volatility_adjustment=vol_adjustment,
            risk_state_adjustment=risk_adjustment,
            reason="; ".join(reasons)
        )

    def calculate_portfolio_allocation(
        self,
        signals: list[dict],
        portfolio_value: float,
        risk_state: RiskState,
        min_signal_score: float = 60.0
    ) -> list[PositionRecommendation]:
        """Calculate positions for multiple stocks respecting portfolio constraints.

        Args:
            signals: List of dicts with stock_code, signal_score, atr_pct
            portfolio_value: Total portfolio value
            risk_state: Current market risk state
            min_signal_score: Minimum score to include (default: 60)

        Returns:
            List of PositionRecommendation sorted by signal score
        """
        # Filter by minimum score
        valid_signals = [
            s for s in signals
            if s["signal_score"] >= min_signal_score
        ]

        # Sort by signal score descending
        valid_signals.sort(key=lambda x: x["signal_score"], reverse=True)

        # Limit to max stocks
        valid_signals = valid_signals[:self.constraints.max_stocks]

        # Calculate individual positions
        recommendations = []
        total_pct = 0.0

        for signal in valid_signals:
            # Check if we still have room
            remaining_pct = self.constraints.target_total_pct - total_pct
            if remaining_pct <= 0:
                break

            rec = self.calculate_position(
                stock_code=signal["stock_code"],
                signal_score=signal["signal_score"],
                atr_pct=signal["atr_pct"],
                portfolio_value=portfolio_value,
                risk_state=risk_state
            )

            # Cap at remaining allocation
            if rec.position_pct > remaining_pct:
                rec = PositionRecommendation(
                    stock_code=rec.stock_code,
                    position_pct=remaining_pct,
                    position_value=remaining_pct * portfolio_value,
                    signal_score=rec.signal_score,
                    volatility_adjustment=rec.volatility_adjustment,
                    risk_state_adjustment=rec.risk_state_adjustment,
                    reason=rec.reason + "; capped by portfolio limit"
                )

            # Skip positions below minimum
            if rec.position_pct >= self.constraints.min_position_pct:
                recommendations.append(rec)
                total_pct += rec.position_pct

        return recommendations
