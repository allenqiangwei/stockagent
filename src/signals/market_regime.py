"""市场状态检测与自适应权重

根据指数级别的技术指标（ADX、ATR、MA）和市场宽度，
判断当前市场状态并动态调整策略权重。
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import talib

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MarketRegime:
    """市场状态

    Attributes:
        regime: 市场状态分类
        confidence: 判断置信度 (0-1)
        trend_strength: 趋势强度 (0-1), ADX/100
        volatility: 相对波动率 (0-1)
        breadth: 市场宽度 (0-1), 上涨家数/总数
        swing_weight: 推荐波段策略权重
        trend_weight: 推荐趋势策略权重
    """
    regime: str  # "trending_bull", "trending_bear", "ranging", "volatile"
    confidence: float
    trend_strength: float
    volatility: float
    breadth: float
    swing_weight: float
    trend_weight: float

    @property
    def regime_label(self) -> str:
        labels = {
            "trending_bull": "趋势上涨",
            "trending_bear": "趋势下跌",
            "ranging": "震荡整理",
            "volatile": "高波动",
        }
        return labels.get(self.regime, self.regime)


class MarketRegimeDetector:
    """市场状态检测器

    基于指数历史数据和市场宽度，判断当前市场处于什么状态，
    并据此推荐 swing/trend 策略权重。
    """

    def __init__(
        self,
        adx_period: int = 14,
        atr_period: int = 14,
        ma_short: int = 5,
        ma_long: int = 20,
    ):
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.ma_short = ma_short
        self.ma_long = ma_long

    def detect(
        self,
        index_df: Optional[pd.DataFrame] = None,
        breadth_ratio: Optional[float] = None,
    ) -> MarketRegime:
        """检测市场状态

        Args:
            index_df: 指数历史数据 DataFrame (需包含 high/low/close 列, 至少30行)
            breadth_ratio: 市场宽度 (上涨家数/总数, 0-1)

        Returns:
            MarketRegime 对象
        """
        trend_strength = 0.5
        volatility = 0.5
        breadth = breadth_ratio if breadth_ratio is not None else 0.5
        ma_bullish = True

        if index_df is not None and len(index_df) >= 30:
            trend_strength, volatility, ma_bullish = self._calc_indicators(index_df)

        # 判断市场状态
        regime, confidence = self._classify(trend_strength, volatility, breadth, ma_bullish)

        # 计算自适应权重
        swing_w, trend_w = self._calc_weights(trend_strength, volatility)

        return MarketRegime(
            regime=regime,
            confidence=confidence,
            trend_strength=trend_strength,
            volatility=volatility,
            breadth=breadth,
            swing_weight=swing_w,
            trend_weight=trend_w,
        )

    def _calc_indicators(self, df: pd.DataFrame) -> tuple:
        """从指数数据计算趋势强度和波动率

        Returns:
            (trend_strength: 0-1, volatility: 0-1, ma_bullish: bool)
        """
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)

        # ADX: 趋势强度 (0-100)
        adx = talib.ADX(high, low, close, timeperiod=self.adx_period)
        latest_adx = adx[-1] if not np.isnan(adx[-1]) else 25.0
        trend_strength = min(latest_adx / 100.0, 1.0)

        # ATR / close: 相对波动率
        atr = talib.ATR(high, low, close, timeperiod=self.atr_period)
        latest_atr = atr[-1] if not np.isnan(atr[-1]) else 0.0
        latest_close = close[-1]
        raw_vol = latest_atr / latest_close if latest_close > 0 else 0.0
        # 典型 A 股日 ATR/close 在 0.01~0.05 之间，归一化到 0-1
        volatility = min(raw_vol / 0.04, 1.0)

        # MA 趋势方向
        ma_short = talib.SMA(close, timeperiod=self.ma_short)
        ma_long = talib.SMA(close, timeperiod=self.ma_long)
        ma_bullish = bool(ma_short[-1] > ma_long[-1]) if not (np.isnan(ma_short[-1]) or np.isnan(ma_long[-1])) else True

        return trend_strength, volatility, ma_bullish

    def _classify(
        self,
        trend_strength: float,
        volatility: float,
        breadth: float,
        ma_bullish: bool,
    ) -> tuple:
        """分类市场状态

        Returns:
            (regime: str, confidence: float)
        """
        # 高波动且趋势弱 → volatile
        if volatility > 0.7 and trend_strength < 0.3:
            return "volatile", min(volatility, 0.9)

        # 强趋势 (ADX > 25 即 trend_strength > 0.25)
        if trend_strength > 0.25:
            if ma_bullish and breadth > 0.45:
                conf = min(trend_strength + breadth * 0.2, 0.95)
                return "trending_bull", conf
            elif not ma_bullish and breadth < 0.55:
                conf = min(trend_strength + (1 - breadth) * 0.2, 0.95)
                return "trending_bear", conf

        # 其余情况 → ranging
        conf = 1.0 - trend_strength  # 趋势越弱，震荡置信度越高
        return "ranging", min(conf, 0.9)

    @staticmethod
    def _calc_weights(trend_strength: float, volatility: float) -> tuple:
        """计算自适应权重

        Args:
            trend_strength: 趋势强度 (0-1)
            volatility: 波动率 (0-1)

        Returns:
            (swing_weight, trend_weight)
        """
        base = 0.30

        # 趋势强度调整: ADX高 → trend权重高 (±0.15)
        trend_adj = (trend_strength - 0.5) * 0.30

        # 波动率调整: 高波动 → swing权重高 (±0.05)
        vol_adj = (volatility - 0.5) * 0.10

        raw_swing = base - trend_adj + vol_adj
        raw_trend = base + trend_adj - vol_adj

        # 钳制到合理范围
        raw_swing = max(0.15, min(0.50, raw_swing))
        raw_trend = max(0.15, min(0.50, raw_trend))

        # 归一化，核心策略总占比 = 0.60（留空间给 ml + sentiment）
        total = raw_swing + raw_trend
        swing_weight = round(raw_swing / total * 0.60, 4)
        trend_weight = round(raw_trend / total * 0.60, 4)

        return swing_weight, trend_weight
