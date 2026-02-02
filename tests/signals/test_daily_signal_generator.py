"""Tests for daily signal generator."""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, patch
from src.signals.daily_signal_generator import DailySignalGenerator, DailySignalReport


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data."""
    np.random.seed(42)
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.DataFrame({
        "trade_date": dates.strftime("%Y%m%d"),
        "open": close - np.random.rand(n),
        "high": close + np.random.rand(n) * 2,
        "low": close - np.random.rand(n) * 2,
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float)
    })


@pytest.fixture
def mock_storage():
    """Create mock parquet storage."""
    storage = Mock()
    return storage


class TestDailySignalReport:
    """Tests for DailySignalReport dataclass."""

    def test_report_creation(self):
        """Test report can be created."""
        report = DailySignalReport(
            trade_date="2024-01-15",
            total_stocks=100,
            buy_signals=10,
            sell_signals=5,
            hold_signals=85,
            top_buy_signals=[],
            top_sell_signals=[]
        )
        assert report.trade_date == "2024-01-15"
        assert report.total_stocks == 100


class TestDailySignalGenerator:
    """Tests for DailySignalGenerator."""

    def test_generator_initialization(self, mock_storage):
        """Test generator initializes correctly."""
        generator = DailySignalGenerator(storage=mock_storage)
        assert generator is not None

    def test_calculate_indicators(self, sample_ohlcv):
        """Test indicator calculation."""
        generator = DailySignalGenerator(storage=Mock())
        df_with_indicators = generator._calculate_indicators(sample_ohlcv)

        # Should have indicator columns
        assert "RSI" in df_with_indicators.columns
        assert "MACD" in df_with_indicators.columns
        assert "MA_5" in df_with_indicators.columns
        assert "ADX" in df_with_indicators.columns

    def test_generate_signal_for_stock(self, sample_ohlcv):
        """Test signal generation for a single stock."""
        generator = DailySignalGenerator(storage=Mock())

        # First calculate indicators (as _process_stock would do)
        df_with_indicators = generator._calculate_indicators(sample_ohlcv)

        signal = generator._generate_signal_for_stock(
            df_with_indicators,
            stock_code="000001.SZ",
            trade_date="2024-04-10"
        )

        assert signal is not None
        assert signal.stock_code == "000001.SZ"
        assert 0 <= signal.final_score <= 100

    def test_generate_signals_batch(self, sample_ohlcv, mock_storage):
        """Test batch signal generation."""
        # Setup mock to return data for multiple stocks
        mock_storage.load_daily.return_value = sample_ohlcv

        generator = DailySignalGenerator(storage=mock_storage)
        stock_codes = ["000001.SZ", "000002.SZ", "600000.SH"]

        signals = generator.generate_signals(
            stock_codes=stock_codes,
            trade_date="2024-04-10"
        )

        assert len(signals) == 3
        assert all(s.stock_code in stock_codes for s in signals)

    def test_generate_report(self, sample_ohlcv, mock_storage):
        """Test report generation."""
        mock_storage.load_daily.return_value = sample_ohlcv

        generator = DailySignalGenerator(storage=mock_storage)
        stock_codes = ["000001.SZ", "000002.SZ", "600000.SH"]

        report = generator.generate_report(
            stock_codes=stock_codes,
            trade_date="2024-04-10"
        )

        assert isinstance(report, DailySignalReport)
        assert report.trade_date == "2024-04-10"
        assert report.total_stocks == 3

    def test_signals_sorted_by_score(self, sample_ohlcv, mock_storage):
        """Test signals are sorted by score descending."""
        mock_storage.load_daily.return_value = sample_ohlcv

        generator = DailySignalGenerator(storage=mock_storage)
        stock_codes = ["000001.SZ", "000002.SZ", "600000.SH"]

        signals = generator.generate_signals(
            stock_codes=stock_codes,
            trade_date="2024-04-10"
        )

        # Should be sorted by final_score descending
        scores = [s.final_score for s in signals]
        assert scores == sorted(scores, reverse=True)

    def test_top_signals_in_report(self, sample_ohlcv, mock_storage):
        """Test report includes top buy and sell signals."""
        mock_storage.load_daily.return_value = sample_ohlcv

        generator = DailySignalGenerator(storage=mock_storage)
        stock_codes = [f"00000{i}.SZ" for i in range(10)]

        report = generator.generate_report(
            stock_codes=stock_codes,
            trade_date="2024-04-10",
            top_n=5
        )

        # Should have at most top_n signals in each list
        assert len(report.top_buy_signals) <= 5
        assert len(report.top_sell_signals) <= 5

    def test_handles_missing_data_gracefully(self, mock_storage):
        """Test generator handles missing stock data."""
        # Return empty DataFrame for missing stock
        mock_storage.load_daily.return_value = pd.DataFrame()

        generator = DailySignalGenerator(storage=mock_storage)
        signals = generator.generate_signals(
            stock_codes=["MISSING.SZ"],
            trade_date="2024-04-10"
        )

        # Should return empty list, not crash
        assert signals == []

    def test_handles_insufficient_data(self, mock_storage):
        """Test generator handles stocks with insufficient history."""
        # Return only 10 rows (not enough for indicators)
        short_df = pd.DataFrame({
            "trade_date": ["20240401"] * 10,
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.5] * 10,
            "volume": [1000.0] * 10
        })
        mock_storage.load_daily.return_value = short_df

        generator = DailySignalGenerator(storage=mock_storage)
        signals = generator.generate_signals(
            stock_codes=["SHORT.SZ"],
            trade_date="2024-04-10"
        )

        # Should skip stocks with insufficient data
        assert len(signals) == 0

    def test_with_ml_model(self, sample_ohlcv, mock_storage):
        """Test signal generation with ML model."""
        mock_storage.load_daily.return_value = sample_ohlcv

        # Create mock ML model
        mock_model = Mock()
        mock_model.predict.return_value = np.array([75.0])

        generator = DailySignalGenerator(
            storage=mock_storage,
            ml_model=mock_model
        )

        signals = generator.generate_signals(
            stock_codes=["000001.SZ"],
            trade_date="2024-04-10"
        )

        assert len(signals) == 1
        assert signals[0].ml_score is not None

    def test_lookback_days_parameter(self, sample_ohlcv, mock_storage):
        """Test lookback_days parameter is passed to storage."""
        mock_storage.load_daily.return_value = sample_ohlcv

        generator = DailySignalGenerator(
            storage=mock_storage,
            lookback_days=120
        )

        generator.generate_signals(
            stock_codes=["000001.SZ"],
            trade_date="2024-04-10"
        )

        # Verify storage was called with date range
        mock_storage.load_daily.assert_called()
