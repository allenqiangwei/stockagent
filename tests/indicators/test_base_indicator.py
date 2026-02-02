"""Tests for base indicator class."""

import pytest
import pandas as pd
import numpy as np
from src.indicators.base_indicator import BaseIndicator, IndicatorResult


class TestIndicatorResult:
    """Tests for IndicatorResult dataclass."""

    def test_indicator_result_creation(self):
        """Test IndicatorResult can be created with required fields."""
        result = IndicatorResult(
            name="TEST_IND",
            values=pd.Series([1.0, 2.0, 3.0]),
            params={"period": 10}
        )
        assert result.name == "TEST_IND"
        assert len(result.values) == 3
        assert result.params["period"] == 10

    def test_indicator_result_optional_signal(self):
        """Test IndicatorResult signal field defaults to None."""
        result = IndicatorResult(
            name="TEST_IND",
            values=pd.Series([1.0]),
            params={}
        )
        assert result.signal is None


class ConcreteIndicator(BaseIndicator):
    """Concrete implementation for testing abstract base class."""

    @property
    def name(self) -> str:
        return "CONCRETE"

    @property
    def required_columns(self) -> list[str]:
        return ["close"]

    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        values = df["close"] * 2
        return IndicatorResult(
            name=self.name,
            values=values,
            params=kwargs
        )


class TestBaseIndicator:
    """Tests for BaseIndicator abstract base class."""

    @pytest.fixture
    def sample_df(self):
        """Create sample OHLCV dataframe for testing."""
        return pd.DataFrame({
            "open": [10.0, 11.0, 12.0, 11.5, 13.0],
            "high": [10.5, 11.5, 12.5, 12.0, 13.5],
            "low": [9.5, 10.5, 11.5, 11.0, 12.5],
            "close": [10.2, 11.2, 12.2, 11.8, 13.2],
            "volume": [1000, 1100, 1200, 1050, 1300]
        })

    @pytest.fixture
    def indicator(self):
        """Create concrete indicator instance."""
        return ConcreteIndicator()

    def test_abstract_class_cannot_be_instantiated(self):
        """Test that BaseIndicator cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseIndicator()

    def test_validate_data_success(self, indicator, sample_df):
        """Test validation passes with correct columns."""
        # Should not raise
        indicator.validate_data(sample_df)

    def test_validate_data_missing_column(self, indicator):
        """Test validation fails with missing required column."""
        df = pd.DataFrame({"open": [1.0], "high": [1.1]})
        with pytest.raises(ValueError, match="Missing required columns"):
            indicator.validate_data(df)

    def test_validate_data_empty_dataframe(self, indicator):
        """Test validation fails with empty dataframe."""
        df = pd.DataFrame({"close": []})
        with pytest.raises(ValueError, match="empty"):
            indicator.validate_data(df)

    def test_calculate_returns_result(self, indicator, sample_df):
        """Test calculate returns IndicatorResult."""
        result = indicator.calculate(sample_df)
        assert isinstance(result, IndicatorResult)
        assert result.name == "CONCRETE"
        assert len(result.values) == len(sample_df)

    def test_call_validates_and_calculates(self, indicator, sample_df):
        """Test __call__ validates data before calculating."""
        result = indicator(sample_df)
        assert isinstance(result, IndicatorResult)

    def test_call_fails_with_invalid_data(self, indicator):
        """Test __call__ raises on invalid data."""
        df = pd.DataFrame({"wrong_column": [1.0]})
        with pytest.raises(ValueError):
            indicator(df)
