"""Daily signal generator for batch stock analysis."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol

import pandas as pd
import numpy as np

from ..indicators import IndicatorCalculator, IndicatorConfig
from ..ml_models import FeatureEngineer
from .signal_combiner import SignalCombiner, CombinedSignal
from .base_signal import SignalLevel


class StorageProtocol(Protocol):
    """Protocol for data storage interface."""

    def load_daily(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Load daily OHLCV data for a stock."""
        ...


class MLModelProtocol(Protocol):
    """Protocol for ML model interface."""

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict scores from features."""
        ...


@dataclass
class DailySignalReport:
    """Summary report for daily signal generation.

    Attributes:
        trade_date: Date of the signals
        total_stocks: Number of stocks analyzed
        buy_signals: Count of buy signals (WEAK_BUY + STRONG_BUY)
        sell_signals: Count of sell signals (WEAK_SELL + STRONG_SELL)
        hold_signals: Count of hold signals
        top_buy_signals: Top N buy signals sorted by score
        top_sell_signals: Top N sell signals sorted by score (ascending)
    """
    trade_date: str
    total_stocks: int
    buy_signals: int
    sell_signals: int
    hold_signals: int
    top_buy_signals: list[CombinedSignal] = field(default_factory=list)
    top_sell_signals: list[CombinedSignal] = field(default_factory=list)


class DailySignalGenerator:
    """Orchestrates daily signal generation for all stocks.

    Workflow:
    1. Load historical data for each stock
    2. Calculate technical indicators
    3. Generate signals from strategies
    4. Optionally enhance with ML predictions
    5. Return ranked and sorted signals

    Usage:
        generator = DailySignalGenerator(storage=parquet_storage)
        signals = generator.generate_signals(
            stock_codes=["000001.SZ", "000002.SZ"],
            trade_date="2024-04-10"
        )

        # Or generate a summary report
        report = generator.generate_report(stock_codes, trade_date)
    """

    # Minimum data points needed for indicator calculation
    MIN_DATA_POINTS = 60

    def __init__(
        self,
        storage: StorageProtocol,
        ml_model: Optional[MLModelProtocol] = None,
        lookback_days: int = 100,
        indicator_config: Optional[IndicatorConfig] = None
    ):
        """Initialize daily signal generator.

        Args:
            storage: Data storage interface for loading OHLCV data
            ml_model: Optional trained ML model for score enhancement
            lookback_days: Days of history to load for indicators
            indicator_config: Custom indicator configuration
        """
        self.storage = storage
        self.ml_model = ml_model
        self.lookback_days = lookback_days

        # Initialize components
        self.indicator_calculator = IndicatorCalculator(
            config=indicator_config or IndicatorConfig()
        )
        self.signal_combiner = SignalCombiner()
        self.feature_engineer = FeatureEngineer() if ml_model else None

    def generate_signals(
        self,
        stock_codes: list[str],
        trade_date: str
    ) -> list[CombinedSignal]:
        """Generate signals for multiple stocks.

        Args:
            stock_codes: List of stock codes to analyze
            trade_date: Date for signal generation (YYYYMMDD or YYYY-MM-DD)

        Returns:
            List of CombinedSignal sorted by final_score descending
        """
        signals = []

        for stock_code in stock_codes:
            try:
                signal = self._process_stock(stock_code, trade_date)
                if signal:
                    signals.append(signal)
            except Exception:
                # Skip stocks that fail processing
                continue

        # Sort by score descending (best buy signals first)
        signals.sort(key=lambda s: s.final_score, reverse=True)

        return signals

    def generate_report(
        self,
        stock_codes: list[str],
        trade_date: str,
        top_n: int = 10
    ) -> DailySignalReport:
        """Generate summary report for daily signals.

        Args:
            stock_codes: List of stock codes to analyze
            trade_date: Date for signal generation
            top_n: Number of top signals to include in report

        Returns:
            DailySignalReport with summary statistics
        """
        signals = self.generate_signals(stock_codes, trade_date)

        # Count by signal type
        buy_signals = [s for s in signals if s.signal_level.is_bullish()]
        sell_signals = [s for s in signals if s.signal_level.is_bearish()]
        hold_signals = [
            s for s in signals
            if s.signal_level == SignalLevel.HOLD
        ]

        # Top signals
        top_buy = buy_signals[:top_n]
        top_sell = sorted(sell_signals, key=lambda s: s.final_score)[:top_n]

        return DailySignalReport(
            trade_date=trade_date,
            total_stocks=len(signals),
            buy_signals=len(buy_signals),
            sell_signals=len(sell_signals),
            hold_signals=len(hold_signals),
            top_buy_signals=top_buy,
            top_sell_signals=top_sell
        )

    def _process_stock(
        self,
        stock_code: str,
        trade_date: str
    ) -> Optional[CombinedSignal]:
        """Process a single stock and generate signal.

        Args:
            stock_code: Stock code
            trade_date: Date for signal

        Returns:
            CombinedSignal or None if processing fails
        """
        # Load data
        df = self._load_stock_data(stock_code, trade_date)
        if df is None or len(df) < self.MIN_DATA_POINTS:
            return None

        # Calculate indicators
        df_with_indicators = self._calculate_indicators(df)

        # Get ML score if model available
        ml_score = None
        if self.ml_model and self.feature_engineer:
            ml_score = self._get_ml_score(df_with_indicators)

        # Generate combined signal
        return self._generate_signal_for_stock(
            df_with_indicators,
            stock_code,
            trade_date,
            ml_score
        )

    def _load_stock_data(
        self,
        stock_code: str,
        trade_date: str
    ) -> Optional[pd.DataFrame]:
        """Load historical data for a stock.

        Args:
            stock_code: Stock code
            trade_date: End date for data

        Returns:
            DataFrame with OHLCV data or None if not available
        """
        # Calculate start date based on lookback
        try:
            # Handle different date formats
            if "-" in trade_date:
                end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
            else:
                end_dt = datetime.strptime(trade_date, "%Y%m%d")

            start_dt = end_dt - timedelta(days=self.lookback_days * 1.5)
            start_date = start_dt.strftime("%Y%m%d")
            end_date = end_dt.strftime("%Y%m%d")

            df = self.storage.load_daily(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date
            )

            if df.empty:
                return None

            return df

        except Exception:
            return None

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all technical indicators.

        Args:
            df: OHLCV DataFrame

        Returns:
            DataFrame with added indicator columns
        """
        indicators = self.indicator_calculator.calculate_all(df)
        return pd.concat([df, indicators], axis=1)

    def _get_ml_score(self, df: pd.DataFrame) -> Optional[float]:
        """Get ML model prediction score.

        Args:
            df: DataFrame with OHLCV and indicators

        Returns:
            ML score (0-100) or None if prediction fails
        """
        try:
            features = self.feature_engineer.create_features(df)
            # Get features for last row only
            last_features = features.iloc[[-1]].dropna(axis=1)

            if last_features.empty:
                return None

            scores = self.ml_model.predict(last_features)
            return float(scores[0])

        except Exception:
            return None

    def _generate_signal_for_stock(
        self,
        df: pd.DataFrame,
        stock_code: str,
        trade_date: str,
        ml_score: Optional[float] = None
    ) -> CombinedSignal:
        """Generate combined signal for a stock.

        Args:
            df: DataFrame with OHLCV and indicators
            stock_code: Stock code
            trade_date: Signal date
            ml_score: Optional ML model score

        Returns:
            CombinedSignal
        """
        return self.signal_combiner.combine(
            df=df,
            stock_code=stock_code,
            trade_date=trade_date,
            ml_score=ml_score
        )
