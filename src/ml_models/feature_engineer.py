"""Feature engineering for ML model training."""

from typing import Optional

import pandas as pd
import numpy as np


class FeatureEngineer:
    """Creates ML features from OHLCV and indicator data.

    Features are organized into categories:
    - Price features: returns, price position vs MAs
    - Momentum features: RSI, MACD, KDJ normalized
    - Trend features: MA crossovers, ADX, DI
    - Volatility features: ATR, historical volatility
    - Volume features: volume ratios, OBV slope

    All features are designed to be stationary and normalized
    for better ML model performance.

    Usage:
        fe = FeatureEngineer()
        features_df = fe.create_features(df_with_indicators)
    """

    # Feature name constants
    FEATURE_NAMES = [
        # Price features
        "return_1d", "return_5d", "return_10d", "return_20d",
        "price_vs_ma5", "price_vs_ma10", "price_vs_ma20",
        # Momentum features
        "rsi_normalized", "macd_normalized", "macd_hist_normalized",
        "kdj_diff", "kdj_j_normalized",
        # Trend features
        "ma_cross", "ema_cross", "adx_strength", "di_diff",
        # Volatility features
        "atr_normalized", "volatility_5d", "volatility_20d",
        # Volume features
        "volume_ratio", "obv_slope"
    ]

    def __init__(
        self,
        return_periods: Optional[list[int]] = None,
        volatility_period: int = 5
    ):
        """Initialize feature engineer.

        Args:
            return_periods: Periods for return calculation (default: [1,5,10,20])
            volatility_period: Period for volatility calculation (default: 5)
        """
        self.return_periods = return_periods or [1, 5, 10, 20]
        self.volatility_period = volatility_period

    def get_feature_names(self) -> list[str]:
        """Get list of feature names.

        Returns:
            List of feature column names
        """
        names = []
        for period in self.return_periods:
            names.append(f"return_{period}d")
        names.extend([
            "price_vs_ma5", "price_vs_ma10", "price_vs_ma20",
            "rsi_normalized", "macd_normalized", "macd_hist_normalized",
            "kdj_diff", "kdj_j_normalized",
            "ma_cross", "ema_cross", "adx_strength", "di_diff",
            "atr_normalized", f"volatility_{self.volatility_period}d", "volatility_20d",
            "volume_ratio", "obv_slope"
        ])
        return names

    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create ML features from indicator data.

        Args:
            df: DataFrame with OHLCV and indicator columns

        Returns:
            DataFrame with feature columns
        """
        features = pd.DataFrame(index=df.index)

        # Price features
        self._add_price_features(df, features)

        # Momentum features
        self._add_momentum_features(df, features)

        # Trend features
        self._add_trend_features(df, features)

        # Volatility features
        self._add_volatility_features(df, features)

        # Volume features
        self._add_volume_features(df, features)

        return features

    def create_features_batch(
        self,
        stock_data: dict[str, pd.DataFrame]
    ) -> dict[str, pd.DataFrame]:
        """Create features for multiple stocks.

        Args:
            stock_data: Dict mapping stock_code to DataFrame

        Returns:
            Dict mapping stock_code to features DataFrame
        """
        return {
            code: self.create_features(df)
            for code, df in stock_data.items()
        }

    def _add_price_features(
        self,
        df: pd.DataFrame,
        features: pd.DataFrame
    ) -> None:
        """Add price-based features."""
        close = df["close"]

        # Returns at different horizons
        for period in self.return_periods:
            features[f"return_{period}d"] = close.pct_change(period) * 100

        # Price position relative to MAs (percentage)
        if "MA_5" in df.columns:
            features["price_vs_ma5"] = (close - df["MA_5"]) / df["MA_5"] * 100
        if "MA_10" in df.columns:
            features["price_vs_ma10"] = (close - df["MA_10"]) / df["MA_10"] * 100
        if "MA_20" in df.columns:
            features["price_vs_ma20"] = (close - df["MA_20"]) / df["MA_20"] * 100

    def _add_momentum_features(
        self,
        df: pd.DataFrame,
        features: pd.DataFrame
    ) -> None:
        """Add momentum-based features."""
        # RSI: normalize to [-1, 1] range (50 -> 0)
        if "RSI" in df.columns:
            features["rsi_normalized"] = (df["RSI"] - 50) / 50

        # MACD: normalize by ATR or price
        if "MACD" in df.columns:
            # Normalize by close price percentage
            features["macd_normalized"] = df["MACD"] / df["close"] * 100

        if "MACD_hist" in df.columns:
            features["macd_hist_normalized"] = df["MACD_hist"] / df["close"] * 100

        # KDJ: K-D difference and J normalized
        if "KDJ_K" in df.columns and "KDJ_D" in df.columns:
            features["kdj_diff"] = (df["KDJ_K"] - df["KDJ_D"]) / 100

        if "KDJ_J" in df.columns:
            # J can exceed 0-100, normalize to roughly [-1, 1]
            features["kdj_j_normalized"] = (df["KDJ_J"] - 50) / 100

    def _add_trend_features(
        self,
        df: pd.DataFrame,
        features: pd.DataFrame
    ) -> None:
        """Add trend-based features."""
        # MA crossover: short MA vs long MA (percentage diff)
        if "MA_5" in df.columns and "MA_20" in df.columns:
            features["ma_cross"] = (df["MA_5"] - df["MA_20"]) / df["MA_20"] * 100

        # EMA crossover
        if "EMA_12" in df.columns and "EMA_26" in df.columns:
            features["ema_cross"] = (df["EMA_12"] - df["EMA_26"]) / df["EMA_26"] * 100

        # ADX strength: normalize to [0, 1]
        if "ADX" in df.columns:
            features["adx_strength"] = df["ADX"] / 100

        # DI difference: +DI - -DI, normalized
        if "ADX_plus_di" in df.columns and "ADX_minus_di" in df.columns:
            features["di_diff"] = (df["ADX_plus_di"] - df["ADX_minus_di"]) / 100

    def _add_volatility_features(
        self,
        df: pd.DataFrame,
        features: pd.DataFrame
    ) -> None:
        """Add volatility-based features."""
        close = df["close"]

        # ATR as percentage of price
        if "ATR" in df.columns:
            features["atr_normalized"] = df["ATR"] / close * 100

        # Historical volatility (standard deviation of returns)
        returns = close.pct_change()
        features[f"volatility_{self.volatility_period}d"] = (
            returns.rolling(self.volatility_period).std() * np.sqrt(252) * 100
        )
        features["volatility_20d"] = (
            returns.rolling(20).std() * np.sqrt(252) * 100
        )

    def _add_volume_features(
        self,
        df: pd.DataFrame,
        features: pd.DataFrame
    ) -> None:
        """Add volume-based features."""
        if "volume" in df.columns:
            volume = df["volume"]
            # Volume ratio vs 20-day average
            vol_ma = volume.rolling(20).mean()
            features["volume_ratio"] = volume / vol_ma

        # OBV slope (rate of change)
        if "OBV" in df.columns:
            obv = df["OBV"]
            # 5-day OBV change normalized by volume
            obv_change = obv.diff(5)
            vol_avg = df.get("volume", pd.Series(1, index=df.index)).rolling(5).mean()
            features["obv_slope"] = obv_change / (vol_avg + 1)  # +1 to avoid division by zero
