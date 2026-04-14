"""Walk-Forward validation for backtest strategies.

Splits the backtest period into rolling train/test windows:
- Train: N years of historical data for strategy optimization
- Test: M months of unseen data to validate

Example with 2020-2025 data, train=2yr, test=6mo:
  Round 1: train 2020-01 ~ 2021-12, test 2022-01 ~ 2022-06
  Round 2: train 2020-07 ~ 2022-06, test 2022-07 ~ 2022-12
  Round 3: train 2021-01 ~ 2022-12, test 2023-01 ~ 2023-06
  ...
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import date, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardWindow:
    """One train/test window."""
    round_num: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_result: Optional[Any] = None  # PortfolioBacktestResult
    test_result: Optional[Any] = None   # PortfolioBacktestResult


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward validation result."""
    strategy_name: str
    total_rounds: int = 0

    # Aggregated test-period metrics (this is the "true" out-of-sample performance)
    test_avg_return: float = 0.0
    test_avg_win_rate: float = 0.0
    test_avg_sharpe: float = 0.0
    test_avg_max_dd: float = 0.0
    test_total_trades: int = 0

    # Aggregated train-period metrics (for comparison)
    train_avg_return: float = 0.0
    train_avg_win_rate: float = 0.0

    # Overfit ratio: train_return / test_return — >2x suggests overfitting
    overfit_ratio: float = 0.0

    # Consistency: how many test rounds were profitable
    profitable_rounds: int = 0
    consistency_pct: float = 0.0  # profitable_rounds / total_rounds * 100

    windows: List[WalkForwardWindow] = field(default_factory=list)


def generate_windows(
    start_date: str,
    end_date: str,
    train_years: float = 2.0,
    test_months: int = 6,
    step_months: int = 6,
) -> List[WalkForwardWindow]:
    """Generate rolling train/test windows.

    Args:
        start_date: Overall start (YYYY-MM-DD)
        end_date: Overall end (YYYY-MM-DD)
        train_years: Training window length in years
        test_months: Test window length in months
        step_months: How far to advance between rounds

    Returns:
        List of WalkForwardWindow with dates filled in
    """
    d_start = date.fromisoformat(start_date)
    d_end = date.fromisoformat(end_date)
    train_days = int(train_years * 365)
    test_days = test_months * 30
    step_days = step_months * 30

    windows = []
    round_num = 1
    current_train_start = d_start

    while True:
        train_end = current_train_start + timedelta(days=train_days)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_days)

        if test_end > d_end:
            break

        windows.append(WalkForwardWindow(
            round_num=round_num,
            train_start=current_train_start.isoformat(),
            train_end=train_end.isoformat(),
            test_start=test_start.isoformat(),
            test_end=test_end.isoformat(),
        ))

        round_num += 1
        current_train_start += timedelta(days=step_days)

    return windows


def run_walk_forward(
    strategy: Dict[str, Any],
    stock_data: Dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
    train_years: float = 2.0,
    test_months: int = 6,
    step_months: int = 6,
    index_data: Optional[pd.DataFrame] = None,
    progress_callback=None,
) -> WalkForwardResult:
    """Run walk-forward validation on a strategy.

    For each window, runs the SAME strategy on train and test periods separately.
    Aggregates test-period results for out-of-sample performance.
    """
    from src.backtest.portfolio_engine import PortfolioBacktestEngine

    windows = generate_windows(start_date, end_date, train_years, test_months, step_months)
    strategy_name = strategy.get("name", "unknown")

    if not windows:
        return WalkForwardResult(strategy_name=strategy_name)

    logger.info("Walk-forward: %d rounds for %s (%s ~ %s)", len(windows), strategy_name, start_date, end_date)

    for i, w in enumerate(windows):
        if progress_callback:
            progress_callback(i + 1, len(windows), f"Round {w.round_num}: test {w.test_start}~{w.test_end}")

        engine = PortfolioBacktestEngine()

        # Filter stock_data to train period
        train_data = _filter_stock_data(stock_data, w.train_start, w.train_end)
        if train_data:
            try:
                w.train_result = engine.run(strategy, train_data, index_data=index_data)
            except Exception as e:
                logger.warning("Walk-forward train round %d failed: %s", w.round_num, e)

        # Filter stock_data to test period
        test_data = _filter_stock_data(stock_data, w.test_start, w.test_end)
        if test_data:
            try:
                w.test_result = engine.run(strategy, test_data, index_data=index_data)
            except Exception as e:
                logger.warning("Walk-forward test round %d failed: %s", w.round_num, e)

    # Aggregate results
    return _aggregate_results(strategy_name, windows)


def _filter_stock_data(
    stock_data: Dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
) -> Dict[str, pd.DataFrame]:
    """Filter each stock's DataFrame to the given date range."""
    result = {}
    for code, df in stock_data.items():
        if "date" not in df.columns:
            continue
        filtered = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
        if len(filtered) >= 20:  # Need minimum data for indicators
            result[code] = filtered.reset_index(drop=True)
    return result


def _aggregate_results(strategy_name: str, windows: List[WalkForwardWindow]) -> WalkForwardResult:
    """Aggregate test-period results across all rounds."""
    result = WalkForwardResult(
        strategy_name=strategy_name,
        total_rounds=len(windows),
        windows=windows,
    )

    test_returns = []
    test_win_rates = []
    test_sharpes = []
    test_max_dds = []
    train_returns = []
    train_win_rates = []
    total_test_trades = 0
    profitable = 0

    for w in windows:
        if w.test_result:
            test_returns.append(w.test_result.total_return_pct)
            test_win_rates.append(w.test_result.win_rate)
            test_sharpes.append(w.test_result.sharpe_ratio)
            test_max_dds.append(w.test_result.max_drawdown_pct)
            total_test_trades += w.test_result.total_trades
            if w.test_result.total_return_pct > 0:
                profitable += 1

        if w.train_result:
            train_returns.append(w.train_result.total_return_pct)
            train_win_rates.append(w.train_result.win_rate)

    if test_returns:
        result.test_avg_return = round(sum(test_returns) / len(test_returns), 2)
        result.test_avg_win_rate = round(sum(test_win_rates) / len(test_win_rates), 2)
        result.test_avg_sharpe = round(sum(test_sharpes) / len(test_sharpes), 2)
        result.test_avg_max_dd = round(sum(test_max_dds) / len(test_max_dds), 2)
        result.test_total_trades = total_test_trades
        result.profitable_rounds = profitable
        result.consistency_pct = round(profitable / len(windows) * 100, 1)

    if train_returns:
        result.train_avg_return = round(sum(train_returns) / len(train_returns), 2)
        result.train_avg_win_rate = round(sum(train_win_rates) / len(train_win_rates), 2)

    # Overfit ratio
    if result.test_avg_return != 0:
        result.overfit_ratio = round(result.train_avg_return / result.test_avg_return, 2) if result.test_avg_return > 0 else 99.0
    elif result.train_avg_return > 0:
        result.overfit_ratio = 99.0  # train positive, test zero/negative = severe overfit

    return result
