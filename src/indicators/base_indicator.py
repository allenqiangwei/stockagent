"""Base class for all technical indicators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any

import pandas as pd
import numpy as np


@dataclass
class IndicatorResult:
    """Container for indicator calculation results.

    Attributes:
        name: Indicator identifier (e.g., 'MA_20', 'MACD')
        values: Calculated indicator values as pandas Series
        params: Parameters used for calculation
        signal: Optional signal interpretation (-1, 0, 1 for sell/hold/buy)
    """
    name: str
    values: pd.Series
    params: dict = field(default_factory=dict)
    signal: Optional[pd.Series] = None


class BaseIndicator(ABC):
    """Abstract base class for all technical indicators.

    Subclasses must implement:
        - name: Property returning indicator name
        - required_columns: Property returning list of required DataFrame columns
        - calculate: Method performing the actual calculation

    Usage:
        indicator = ConcreteIndicator()
        result = indicator(df)  # Validates and calculates
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return indicator name."""
        pass

    @property
    @abstractmethod
    def required_columns(self) -> list[str]:
        """Return list of required DataFrame columns."""
        pass

    @abstractmethod
    def calculate(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Calculate indicator values.

        Args:
            df: OHLCV DataFrame with required columns
            **kwargs: Additional calculation parameters

        Returns:
            IndicatorResult with calculated values
        """
        pass

    def validate_data(self, df: pd.DataFrame) -> None:
        """Validate input DataFrame has required columns and is not empty.

        Args:
            df: Input DataFrame to validate

        Raises:
            ValueError: If DataFrame is empty or missing required columns
        """
        if df.empty:
            raise ValueError("DataFrame is empty")

        missing = set(self.required_columns) - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

    def __call__(self, df: pd.DataFrame, **kwargs) -> IndicatorResult:
        """Validate data and calculate indicator.

        Args:
            df: OHLCV DataFrame
            **kwargs: Calculation parameters

        Returns:
            IndicatorResult with calculated values
        """
        self.validate_data(df)
        return self.calculate(df, **kwargs)
