"""Swing trading strategy based on momentum indicators."""

import pandas as pd

from .base_signal import BaseStrategy, SignalResult, SignalLevel, score_to_signal_level


class SwingStrategy(BaseStrategy):
    """Swing trading strategy using RSI, KDJ, and MACD.

    This strategy identifies short-term reversal points by combining:
    - RSI overbought/oversold levels (reversal zones)
    - KDJ crossovers (momentum shifts)
    - MACD histogram direction (trend confirmation)

    Signal Logic:
    - RSI < 30 (oversold) -> bullish points
    - RSI > 70 (overbought) -> bearish points
    - KDJ K > D -> bullish points
    - KDJ K < D -> bearish points
    - MACD histogram > 0 -> bullish points
    - MACD histogram < 0 -> bearish points

    Best for: Ranging markets, mean-reversion plays
    Holding period: 3-10 days
    """

    def __init__(
        self,
        rsi_weight: float = 0.35,
        kdj_weight: float = 0.35,
        macd_weight: float = 0.30,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0
    ):
        """Initialize swing strategy.

        Args:
            rsi_weight: Weight for RSI signal (default: 0.35)
            kdj_weight: Weight for KDJ signal (default: 0.35)
            macd_weight: Weight for MACD signal (default: 0.30)
            rsi_oversold: RSI level considered oversold (default: 30)
            rsi_overbought: RSI level considered overbought (default: 70)
        """
        self.rsi_weight = rsi_weight
        self.kdj_weight = kdj_weight
        self.macd_weight = macd_weight
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    @property
    def name(self) -> str:
        return "SWING"

    def generate_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str
    ) -> SignalResult:
        """Generate swing trading signal.

        Args:
            df: DataFrame with RSI, KDJ_K, KDJ_D, KDJ_J, MACD_hist columns
            stock_code: Stock identifier
            trade_date: Signal date

        Returns:
            SignalResult with swing trading signal
        """
        # Get latest values
        latest = df.iloc[-1]

        # Calculate component scores (0-100 scale)
        rsi_score = self._calculate_rsi_score(latest["RSI"])
        kdj_score = self._calculate_kdj_score(
            latest["KDJ_K"],
            latest["KDJ_D"],
            latest["KDJ_J"]
        )
        macd_score = self._calculate_macd_score(latest["MACD_hist"])

        # Weighted combination
        total_score = (
            rsi_score * self.rsi_weight +
            kdj_score * self.kdj_weight +
            macd_score * self.macd_weight
        )

        # Build reason string
        reasons = []
        if rsi_score > 60:
            reasons.append(f"RSI超卖反弹({latest['RSI']:.1f})")
        elif rsi_score < 40:
            reasons.append(f"RSI超买回调({latest['RSI']:.1f})")

        if kdj_score > 60:
            reasons.append("KDJ金叉")
        elif kdj_score < 40:
            reasons.append("KDJ死叉")

        if macd_score > 60:
            reasons.append("MACD柱状线向上")
        elif macd_score < 40:
            reasons.append("MACD柱状线向下")

        reason = "; ".join(reasons) if reasons else "信号中性"

        return SignalResult(
            strategy_name=self.name,
            stock_code=stock_code,
            signal_level=score_to_signal_level(total_score),
            score=total_score,
            trade_date=trade_date,
            reason=reason,
            metadata={
                "rsi_score": rsi_score,
                "kdj_score": kdj_score,
                "macd_score": macd_score,
                "rsi": latest["RSI"],
                "kdj_k": latest["KDJ_K"],
                "kdj_d": latest["KDJ_D"],
                "macd_hist": latest["MACD_hist"]
            }
        )

    def _calculate_rsi_score(self, rsi: float) -> float:
        """Calculate RSI contribution to signal score.

        Oversold (RSI < 30) -> high score (bullish reversal expected)
        Overbought (RSI > 70) -> low score (bearish reversal expected)
        Neutral (30-70) -> maps to 40-60 score range

        Args:
            rsi: Current RSI value

        Returns:
            Score 0-100
        """
        if rsi <= self.rsi_oversold:
            # Oversold: more oversold = higher score
            # RSI 0 -> score 100, RSI 30 -> score 70
            return 100 - (rsi / self.rsi_oversold) * 30
        elif rsi >= self.rsi_overbought:
            # Overbought: more overbought = lower score
            # RSI 70 -> score 30, RSI 100 -> score 0
            excess = rsi - self.rsi_overbought
            return max(0, 30 - excess)
        else:
            # Neutral zone: linear mapping from 30-70 RSI to 40-60 score
            normalized = (rsi - self.rsi_oversold) / (self.rsi_overbought - self.rsi_oversold)
            return 60 - normalized * 20  # 60 at RSI 30, 40 at RSI 70

    def _calculate_kdj_score(self, k: float, d: float, j: float) -> float:
        """Calculate KDJ contribution to signal score.

        K > D (golden cross tendency) -> bullish
        K < D (death cross tendency) -> bearish
        J extremes amplify the signal

        Args:
            k: KDJ K value
            d: KDJ D value
            j: KDJ J value

        Returns:
            Score 0-100
        """
        # Base score from K-D difference
        diff = k - d
        # Map diff (-40 to +40 typical range) to score
        base_score = 50 + diff * 0.5  # diff of +20 -> score 60

        # J extremes as amplifier
        if j > 100:
            # Overbought J, reduce score
            base_score -= (j - 100) * 0.2
        elif j < 0:
            # Oversold J, increase score
            base_score += abs(j) * 0.2

        return max(0, min(100, base_score))

    def _calculate_macd_score(self, histogram: float) -> float:
        """Calculate MACD histogram contribution to signal score.

        Positive histogram -> bullish momentum
        Negative histogram -> bearish momentum

        Args:
            histogram: MACD histogram value

        Returns:
            Score 0-100
        """
        # Map histogram to score
        # Typical range -2 to +2, map to 0-100
        score = 50 + histogram * 25
        return max(0, min(100, score))
