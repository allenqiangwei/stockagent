"""Stop loss management with multiple stop types."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StopType(Enum):
    """Type of stop loss triggered."""
    NONE = "none"
    FIXED = "fixed"
    TRAILING = "trailing"
    PROFIT_LOCK = "profit_lock"


@dataclass
class Position:
    """Represents a stock position for stop loss tracking.

    Attributes:
        stock_code: Stock identifier
        entry_price: Price at which position was opened
        current_price: Current market price
        quantity: Number of shares held
        entry_date: Date position was opened
        highest_price: Highest price since entry (for trailing stop)
    """
    stock_code: str
    entry_price: float
    current_price: float
    quantity: int
    entry_date: str
    highest_price: Optional[float] = None

    def __post_init__(self):
        if self.highest_price is None:
            self.highest_price = max(self.entry_price, self.current_price)

    @property
    def pnl_pct(self) -> float:
        """Calculate P&L as percentage."""
        return (self.current_price - self.entry_price) / self.entry_price * 100

    @property
    def pnl_value(self) -> float:
        """Calculate P&L in currency units."""
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def highest_gain_pct(self) -> float:
        """Calculate highest gain reached as percentage."""
        return (self.highest_price - self.entry_price) / self.entry_price * 100


@dataclass
class StopLossResult:
    """Result of stop loss check.

    Attributes:
        stock_code: Stock identifier
        should_stop: Whether stop loss was triggered
        stop_type: Type of stop that triggered
        stop_price: Price level that triggered the stop
        current_price: Current market price
        reason: Human-readable explanation
    """
    stock_code: str
    should_stop: bool
    stop_type: StopType
    stop_price: float
    current_price: float
    reason: str


class StopLossManager:
    """Manages stop loss logic with hybrid approach.

    Stop Types:
    1. Fixed Stop: Hard stop at -X% from entry (default: -5%)
    2. Trailing Stop: Stop at highest price - N*ATR (default: 2x ATR)
    3. Profit Lock: Tiered stops that lock in profits

    Profit Lock Tiers:
    - Gain reaches 10% -> Lock 5% profit (stop at entry + 5%)
    - Gain reaches 20% -> Lock 10% profit (stop at entry + 10%)
    - Gain reaches 30% -> Lock 20% profit (stop at entry + 20%)

    The most restrictive (highest) stop price is always used.

    Usage:
        manager = StopLossManager()
        result = manager.check_stop_loss(position, atr=0.5)
        if result.should_stop:
            # Execute stop loss order
    """

    # Default profit lock tiers: (gain_threshold, lock_profit)
    DEFAULT_PROFIT_TIERS = [
        (0.30, 0.20),  # 30% gain -> lock 20%
        (0.20, 0.10),  # 20% gain -> lock 10%
        (0.10, 0.05),  # 10% gain -> lock 5%
    ]

    def __init__(
        self,
        fixed_stop_pct: float = 0.05,
        atr_multiplier: float = 2.0,
        profit_tiers: Optional[list[tuple[float, float]]] = None
    ):
        """Initialize stop loss manager.

        Args:
            fixed_stop_pct: Fixed stop loss percentage (default: 5%)
            atr_multiplier: Multiplier for ATR trailing stop (default: 2)
            profit_tiers: Custom profit lock tiers
        """
        self.fixed_stop_pct = fixed_stop_pct
        self.atr_multiplier = atr_multiplier
        self.profit_tiers = profit_tiers or self.DEFAULT_PROFIT_TIERS

    def check_stop_loss(
        self,
        position: Position,
        atr: float
    ) -> StopLossResult:
        """Check if stop loss should be triggered.

        Args:
            position: Current position details
            atr: Current ATR value in price units

        Returns:
            StopLossResult indicating if stop triggered and why
        """
        stops = self.calculate_stop_prices(position, atr)

        # Find the most restrictive (highest) stop price
        active_stop_type = StopType.NONE
        active_stop_price = 0.0

        for stop_type, stop_price in [
            (StopType.FIXED, stops["fixed"]),
            (StopType.TRAILING, stops["trailing"]),
            (StopType.PROFIT_LOCK, stops["profit_lock"])
        ]:
            if stop_price is not None and stop_price > active_stop_price:
                active_stop_price = stop_price
                active_stop_type = stop_type

        # Check if current price is below the active stop
        should_stop = position.current_price < active_stop_price

        # Build reason
        if should_stop:
            if active_stop_type == StopType.FIXED:
                reason = f"Price {position.current_price:.2f} below fixed stop {active_stop_price:.2f} (-{self.fixed_stop_pct*100:.0f}%)"
            elif active_stop_type == StopType.TRAILING:
                reason = f"Price {position.current_price:.2f} below trailing stop {active_stop_price:.2f} (from high {position.highest_price:.2f})"
            elif active_stop_type == StopType.PROFIT_LOCK:
                reason = f"Price {position.current_price:.2f} below profit lock {active_stop_price:.2f} (locking gains)"
            else:
                reason = "Unknown stop type"
        else:
            reason = f"No stop triggered. Active stop: {active_stop_type.value} at {active_stop_price:.2f}"
            active_stop_type = StopType.NONE

        return StopLossResult(
            stock_code=position.stock_code,
            should_stop=should_stop,
            stop_type=active_stop_type if should_stop else StopType.NONE,
            stop_price=active_stop_price,
            current_price=position.current_price,
            reason=reason
        )

    def calculate_stop_prices(
        self,
        position: Position,
        atr: float
    ) -> dict[str, Optional[float]]:
        """Calculate all stop price levels.

        Args:
            position: Current position
            atr: Current ATR value

        Returns:
            Dict with stop prices for each type
        """
        # 1. Fixed stop: entry price * (1 - fixed_pct)
        fixed_stop = position.entry_price * (1 - self.fixed_stop_pct)

        # 2. Trailing stop: highest price - (atr * multiplier)
        trailing_stop = position.highest_price - (atr * self.atr_multiplier)

        # 3. Profit lock: based on highest gain reached
        profit_lock_stop = self._calculate_profit_lock(position)

        return {
            "fixed": fixed_stop,
            "trailing": trailing_stop,
            "profit_lock": profit_lock_stop
        }

    def _calculate_profit_lock(self, position: Position) -> Optional[float]:
        """Calculate profit lock stop price based on highest gain.

        Args:
            position: Current position

        Returns:
            Stop price for profit lock, or None if no tier reached
        """
        highest_gain_pct = position.highest_gain_pct / 100  # Convert to decimal

        # Find applicable tier (tiers are sorted high to low)
        for gain_threshold, lock_profit in self.profit_tiers:
            if highest_gain_pct >= gain_threshold:
                # Lock this profit level
                return position.entry_price * (1 + lock_profit)

        return None

    def update_position(self, position: Position) -> None:
        """Update position's highest price if current is higher.

        Args:
            position: Position to update (modified in place)
        """
        if position.current_price > position.highest_price:
            position.highest_price = position.current_price

    def check_batch(
        self,
        positions: list[Position],
        atrs: dict[str, float]
    ) -> list[StopLossResult]:
        """Check stop loss for multiple positions.

        Args:
            positions: List of positions to check
            atrs: Dict mapping stock_code to ATR value

        Returns:
            List of StopLossResult for each position
        """
        results = []
        for pos in positions:
            atr = atrs.get(pos.stock_code, pos.entry_price * 0.02)  # Default 2% ATR
            result = self.check_stop_loss(pos, atr)
            results.append(result)
        return results
