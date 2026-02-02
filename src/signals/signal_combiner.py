"""Signal combiner for multi-strategy weighted signals."""

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .base_signal import SignalLevel, score_to_signal_level
from .swing_strategy import SwingStrategy
from .trend_strategy import TrendStrategy


@dataclass
class CombinedSignal:
    """Combined signal from multiple strategies.

    Attributes:
        stock_code: Stock identifier
        trade_date: Date of the signal
        final_score: Weighted combined score (0-100)
        signal_level: Final signal classification
        swing_score: Score from swing strategy
        trend_score: Score from trend strategy
        ml_score: Score from ML model (optional)
        reasons: List of reasons from contributing strategies
    """
    stock_code: str
    trade_date: str
    final_score: float
    signal_level: SignalLevel
    swing_score: float
    trend_score: float
    ml_score: Optional[float]
    reasons: list[str] = field(default_factory=list)


class SignalCombiner:
    """Combines signals from multiple strategies with configurable weights.

    Default weights:
    - Swing strategy: 35%
    - Trend strategy: 35%
    - ML model: 30%

    When ML score is not provided, swing and trend weights are
    normalized to sum to 100%.

    Usage:
        combiner = SignalCombiner()
        signal = combiner.combine(df, "000001.SZ", "2024-01-15")

        # With ML score
        signal = combiner.combine(df, "000001.SZ", "2024-01-15", ml_score=75.0)

        # Batch processing
        signals = combiner.combine_batch(stock_data_dict, "2024-01-15")
    """

    def __init__(
        self,
        swing_weight: float = 0.35,
        trend_weight: float = 0.35,
        ml_weight: float = 0.30
    ):
        """Initialize signal combiner.

        Args:
            swing_weight: Weight for swing strategy (default: 0.35)
            trend_weight: Weight for trend strategy (default: 0.35)
            ml_weight: Weight for ML model (default: 0.30)
        """
        self.swing_weight = swing_weight
        self.trend_weight = trend_weight
        self.ml_weight = ml_weight

        # Initialize strategies
        self._swing_strategy = SwingStrategy()
        self._trend_strategy = TrendStrategy()

    def combine(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str,
        ml_score: Optional[float] = None
    ) -> CombinedSignal:
        """Combine signals from all strategies.

        Args:
            df: DataFrame with OHLCV and indicator columns
            stock_code: Stock identifier
            trade_date: Date for the signal
            ml_score: Optional ML model score (0-100)

        Returns:
            CombinedSignal with weighted final score
        """
        # Get individual strategy signals
        swing_result = self._swing_strategy(df, stock_code, trade_date)
        trend_result = self._trend_strategy(df, stock_code, trade_date)

        swing_score = swing_result.score
        trend_score = trend_result.score

        # Calculate weighted combination
        if ml_score is not None:
            # Use all three weights
            final_score = (
                swing_score * self.swing_weight +
                trend_score * self.trend_weight +
                ml_score * self.ml_weight
            )
        else:
            # Normalize swing and trend weights
            total_weight = self.swing_weight + self.trend_weight
            normalized_swing = self.swing_weight / total_weight
            normalized_trend = self.trend_weight / total_weight

            final_score = (
                swing_score * normalized_swing +
                trend_score * normalized_trend
            )

        # Collect reasons from significant signals
        reasons = []
        if swing_result.reason and swing_result.signal_level != SignalLevel.HOLD:
            reasons.append(f"[波段] {swing_result.reason}")
        if trend_result.reason and trend_result.signal_level != SignalLevel.HOLD:
            reasons.append(f"[趋势] {trend_result.reason}")

        return CombinedSignal(
            stock_code=stock_code,
            trade_date=trade_date,
            final_score=final_score,
            signal_level=score_to_signal_level(final_score),
            swing_score=swing_score,
            trend_score=trend_score,
            ml_score=ml_score,
            reasons=reasons
        )

    def combine_batch(
        self,
        stock_data: dict[str, pd.DataFrame],
        trade_date: str,
        ml_scores: Optional[dict[str, float]] = None
    ) -> list[CombinedSignal]:
        """Combine signals for multiple stocks.

        Args:
            stock_data: Dict mapping stock_code to DataFrame
            trade_date: Date for the signals
            ml_scores: Optional dict mapping stock_code to ML score

        Returns:
            List of CombinedSignal for each stock
        """
        ml_scores = ml_scores or {}
        results = []

        for stock_code, df in stock_data.items():
            ml_score = ml_scores.get(stock_code)
            signal = self.combine(df, stock_code, trade_date, ml_score)
            results.append(signal)

        return results
