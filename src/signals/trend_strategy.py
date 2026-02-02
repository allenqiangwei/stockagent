"""Trend following strategy based on moving averages and ADX."""

import pandas as pd

from .base_signal import BaseStrategy, SignalResult, SignalLevel, score_to_signal_level


class TrendStrategy(BaseStrategy):
    """Trend following strategy using MA crossovers and ADX.

    This strategy identifies and follows established trends by combining:
    - MA crossovers (short MA vs long MA)
    - ADX trend strength filtering
    - EMA alignment and price position
    - Directional indicator (+DI/-DI) for trend direction

    Signal Logic:
    - Short MA > Long MA -> bullish
    - Price > EMA12 > EMA26 -> bullish alignment
    - ADX > 25 with +DI > -DI -> strong uptrend
    - ADX > 25 with -DI > +DI -> strong downtrend

    Best for: Trending markets, breakouts
    Holding period: 10-30 days
    """

    def __init__(
        self,
        ma_weight: float = 0.35,
        adx_weight: float = 0.35,
        ema_weight: float = 0.30,
        adx_threshold: float = 25.0
    ):
        """Initialize trend strategy.

        Args:
            ma_weight: Weight for MA crossover signal (default: 0.35)
            adx_weight: Weight for ADX/DI signal (default: 0.35)
            ema_weight: Weight for EMA alignment signal (default: 0.30)
            adx_threshold: ADX level for trend confirmation (default: 25)
        """
        self.ma_weight = ma_weight
        self.adx_weight = adx_weight
        self.ema_weight = ema_weight
        self.adx_threshold = adx_threshold

    @property
    def name(self) -> str:
        return "TREND"

    def generate_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str
    ) -> SignalResult:
        """Generate trend following signal.

        Args:
            df: DataFrame with MA_5, MA_20, EMA_12, EMA_26, ADX,
                ADX_plus_di, ADX_minus_di columns
            stock_code: Stock identifier
            trade_date: Signal date

        Returns:
            SignalResult with trend following signal
        """
        # Get latest values
        latest = df.iloc[-1]

        # Calculate component scores (0-100 scale)
        ma_score = self._calculate_ma_score(
            latest["close"],
            latest["MA_5"],
            latest["MA_20"]
        )
        adx_score = self._calculate_adx_score(
            latest["ADX"],
            latest["ADX_plus_di"],
            latest["ADX_minus_di"]
        )
        ema_score = self._calculate_ema_score(
            latest["close"],
            latest["EMA_12"],
            latest["EMA_26"]
        )

        # Weighted combination
        total_score = (
            ma_score * self.ma_weight +
            adx_score * self.adx_weight +
            ema_score * self.ema_weight
        )

        # ADX strength modifier - amplify signals in strong trends
        if latest["ADX"] > self.adx_threshold:
            # Amplify deviation from neutral
            deviation = total_score - 50
            amplification = 1 + (latest["ADX"] - self.adx_threshold) / 50
            total_score = 50 + deviation * amplification
            total_score = max(0, min(100, total_score))

        # Build reason string
        reasons = []
        if ma_score > 60:
            reasons.append("MA金叉(短期MA在长期MA之上)")
        elif ma_score < 40:
            reasons.append("MA死叉(短期MA在长期MA之下)")

        if latest["ADX"] > self.adx_threshold:
            if latest["ADX_plus_di"] > latest["ADX_minus_di"]:
                reasons.append(f"强势上涨趋势(ADX={latest['ADX']:.1f})")
            else:
                reasons.append(f"强势下跌趋势(ADX={latest['ADX']:.1f})")
        else:
            reasons.append(f"趋势较弱(ADX={latest['ADX']:.1f})")

        if ema_score > 60:
            reasons.append("价格在EMA之上")
        elif ema_score < 40:
            reasons.append("价格在EMA之下")

        reason = "; ".join(reasons) if reasons else "趋势中性"

        return SignalResult(
            strategy_name=self.name,
            stock_code=stock_code,
            signal_level=score_to_signal_level(total_score),
            score=total_score,
            trade_date=trade_date,
            reason=reason,
            metadata={
                "ma_score": ma_score,
                "adx_score": adx_score,
                "ema_score": ema_score,
                "adx": latest["ADX"],
                "plus_di": latest["ADX_plus_di"],
                "minus_di": latest["ADX_minus_di"]
            }
        )

    def _calculate_ma_score(
        self,
        close: float,
        ma_short: float,
        ma_long: float
    ) -> float:
        """Calculate MA crossover contribution to signal score.

        Short MA above long MA -> bullish
        Price position relative to MAs adds confirmation

        Args:
            close: Current close price
            ma_short: Short-term MA value
            ma_long: Long-term MA value

        Returns:
            Score 0-100
        """
        # MA relationship
        ma_diff_pct = (ma_short - ma_long) / ma_long * 100

        # Map percentage diff to score
        # +5% diff -> score 80, -5% diff -> score 20
        base_score = 50 + ma_diff_pct * 6
        base_score = max(0, min(100, base_score))

        # Price position modifier
        price_vs_short = (close - ma_short) / ma_short * 100
        modifier = price_vs_short * 2  # +2% above MA -> +4 points
        modifier = max(-10, min(10, modifier))

        return max(0, min(100, base_score + modifier))

    def _calculate_adx_score(
        self,
        adx: float,
        plus_di: float,
        minus_di: float
    ) -> float:
        """Calculate ADX/DI contribution to signal score.

        +DI > -DI -> bullish direction
        ADX strength amplifies the direction signal

        Args:
            adx: ADX value (trend strength)
            plus_di: +DI value (bullish pressure)
            minus_di: -DI value (bearish pressure)

        Returns:
            Score 0-100
        """
        # Direction from DI difference
        di_diff = plus_di - minus_di

        # Base score from DI difference
        # +20 DI diff -> score 70, -20 DI diff -> score 30
        base_score = 50 + di_diff

        # Weak trend (low ADX) -> push towards neutral
        if adx < self.adx_threshold:
            weakness_factor = adx / self.adx_threshold
            base_score = 50 + (base_score - 50) * weakness_factor

        return max(0, min(100, base_score))

    def _calculate_ema_score(
        self,
        close: float,
        ema_12: float,
        ema_26: float
    ) -> float:
        """Calculate EMA alignment contribution to signal score.

        Price > EMA12 > EMA26 -> bullish alignment
        Price < EMA12 < EMA26 -> bearish alignment

        Args:
            close: Current close price
            ema_12: 12-period EMA
            ema_26: 26-period EMA

        Returns:
            Score 0-100
        """
        # EMA relationship
        ema_bullish = ema_12 > ema_26
        ema_diff_pct = abs(ema_12 - ema_26) / ema_26 * 100

        # Price position
        price_above_ema12 = close > ema_12
        price_above_ema26 = close > ema_26

        # Scoring
        if ema_bullish and price_above_ema12 and price_above_ema26:
            # Full bullish alignment
            return 70 + min(30, ema_diff_pct * 5)
        elif not ema_bullish and not price_above_ema12 and not price_above_ema26:
            # Full bearish alignment
            return 30 - min(30, ema_diff_pct * 5)
        elif price_above_ema12 and price_above_ema26:
            # Price bullish, EMAs mixed
            return 60
        elif not price_above_ema12 and not price_above_ema26:
            # Price bearish, EMAs mixed
            return 40
        else:
            # Mixed signals
            return 50
