"""Risk state management with confirmation logic."""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class RiskState(IntEnum):
    """Market risk state classification.

    - RISK_OFF: High risk, no new positions, reduce exposure
    - NEUTRAL: Moderate risk, reduced position sizes
    - RISK_ON: Low risk, full position sizes allowed
    """
    RISK_OFF = 1
    NEUTRAL = 2
    RISK_ON = 3

    @property
    def position_multiplier(self) -> float:
        """Get position size multiplier for this state."""
        multipliers = {
            RiskState.RISK_OFF: 0.0,
            RiskState.NEUTRAL: 0.5,
            RiskState.RISK_ON: 1.0
        }
        return multipliers[self]

    @property
    def allows_new_positions(self) -> bool:
        """Check if state allows opening new positions."""
        return self != RiskState.RISK_OFF


@dataclass
class MarketCondition:
    """Market condition metrics for risk assessment.

    All scores are 0-100 where higher is more bullish,
    except volatility_score where higher means more volatile (bearish).

    Attributes:
        index_trend_score: Major index trend strength (0-100)
        sentiment_score: News/social sentiment score (0-100)
        money_flow_score: Net money flow score (0-100)
        volatility_score: Market volatility level (0-100, inverted)
    """
    index_trend_score: float
    sentiment_score: float
    money_flow_score: float
    volatility_score: float

    # Default weights for composite calculation
    _weights: dict = field(default_factory=lambda: {
        "index_trend": 0.40,
        "sentiment": 0.25,
        "money_flow": 0.20,
        "volatility": 0.15
    })

    @property
    def composite_score(self) -> float:
        """Calculate weighted composite risk score.

        Returns:
            Score 0-100 where higher is more bullish/risk-on
        """
        # Invert volatility (high volatility = low score)
        inverted_volatility = 100 - self.volatility_score

        return (
            self.index_trend_score * self._weights["index_trend"] +
            self.sentiment_score * self._weights["sentiment"] +
            self.money_flow_score * self._weights["money_flow"] +
            inverted_volatility * self._weights["volatility"]
        )


@dataclass
class StateHistoryEntry:
    """Entry in state history."""
    date: str
    state: RiskState
    composite_score: float
    condition: MarketCondition


class RiskStateManager:
    """Manages market risk state with confirmation logic.

    State transitions require N consecutive days of signals
    in the same direction (confirmation_days parameter),
    unless there's a rapid market deterioration.

    State Thresholds (default):
    - composite_score >= 60: RISK_ON signal
    - composite_score <= 40: RISK_OFF signal
    - 40 < composite_score < 60: NEUTRAL signal

    Usage:
        manager = RiskStateManager(confirmation_days=2)
        manager.update("2024-01-15", market_condition)
        current_state = manager.current_state
        multiplier = current_state.position_multiplier
    """

    def __init__(
        self,
        confirmation_days: int = 2,
        risk_on_threshold: float = 60.0,
        risk_off_threshold: float = 40.0,
        rapid_change_threshold: float = 30.0
    ):
        """Initialize risk state manager.

        Args:
            confirmation_days: Days of consistent signal before state change
            risk_on_threshold: Composite score threshold for RISK_ON
            risk_off_threshold: Composite score threshold for RISK_OFF
            rapid_change_threshold: Score drop that bypasses confirmation
        """
        self.confirmation_days = confirmation_days
        self.risk_on_threshold = risk_on_threshold
        self.risk_off_threshold = risk_off_threshold
        self.rapid_change_threshold = rapid_change_threshold

        # Current state
        self._current_state = RiskState.NEUTRAL
        self._pending_state: Optional[RiskState] = None
        self._confirmation_count = 0
        self._last_composite_score: Optional[float] = None

        # History
        self._history: list[StateHistoryEntry] = []

    @property
    def current_state(self) -> RiskState:
        """Get current risk state."""
        return self._current_state

    def update(self, date: str, condition: MarketCondition) -> RiskState:
        """Update risk state based on market condition.

        Args:
            date: Date string (YYYY-MM-DD or YYYYMMDD)
            condition: Current market condition metrics

        Returns:
            Updated RiskState
        """
        composite = condition.composite_score
        signal_state = self._score_to_signal(composite)

        # Check for rapid deterioration (bypass confirmation)
        if self._last_composite_score is not None:
            score_drop = self._last_composite_score - composite
            if score_drop >= self.rapid_change_threshold:
                # Immediate switch to RISK_OFF
                self._current_state = RiskState.RISK_OFF
                self._pending_state = None
                self._confirmation_count = 0
                self._record_history(date, condition, composite)
                self._last_composite_score = composite
                return self._current_state

        # Normal confirmation logic
        if signal_state == self._current_state:
            # Signal matches current state, reset pending
            self._pending_state = None
            self._confirmation_count = 0
        elif signal_state == self._pending_state:
            # Signal matches pending state, increment confirmation
            self._confirmation_count += 1
            if self._confirmation_count >= self.confirmation_days:
                # Confirmed, switch state
                self._current_state = signal_state
                self._pending_state = None
                self._confirmation_count = 0
        else:
            # New pending state
            self._pending_state = signal_state
            self._confirmation_count = 1
            if self.confirmation_days == 1:
                # No confirmation needed
                self._current_state = signal_state
                self._pending_state = None
                self._confirmation_count = 0

        self._record_history(date, condition, composite)
        self._last_composite_score = composite

        return self._current_state

    def _score_to_signal(self, composite_score: float) -> RiskState:
        """Convert composite score to signal state.

        Args:
            composite_score: Weighted market score (0-100)

        Returns:
            Signaled RiskState
        """
        if composite_score >= self.risk_on_threshold:
            return RiskState.RISK_ON
        elif composite_score <= self.risk_off_threshold:
            return RiskState.RISK_OFF
        else:
            return RiskState.NEUTRAL

    def _record_history(
        self,
        date: str,
        condition: MarketCondition,
        composite: float
    ) -> None:
        """Record state history entry."""
        entry = StateHistoryEntry(
            date=date,
            state=self._current_state,
            composite_score=composite,
            condition=condition
        )
        self._history.append(entry)

    def get_state_history(
        self,
        last_n: Optional[int] = None
    ) -> list[StateHistoryEntry]:
        """Get state history entries.

        Args:
            last_n: Return only last N entries (default: all)

        Returns:
            List of StateHistoryEntry
        """
        if last_n is None:
            return self._history.copy()
        return self._history[-last_n:]

    def reset(self) -> None:
        """Reset manager to initial state."""
        self._current_state = RiskState.NEUTRAL
        self._pending_state = None
        self._confirmation_count = 0
        self._last_composite_score = None
        self._history.clear()
