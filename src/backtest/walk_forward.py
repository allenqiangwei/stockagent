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

    # Walk-Forward Efficiency (WFE): annualized_test / annualized_train
    # >50% = robust (Pardo standard), >80% = excellent
    wfe_pct: float = 0.0

    # Overfit ratio: annualized_train / annualized_test (inverse of WFE)
    # <2.0 = acceptable, >3.0 = likely overfit
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
    precomputed: Optional[Dict[str, Any]] = None,
    regime_map: Optional[Dict[str, str]] = None,
) -> WalkForwardResult:
    """Run walk-forward validation on a strategy.

    For each window, runs the SAME strategy on train and test periods separately.
    Aggregates test-period results for out-of-sample performance.

    If precomputed is provided (from PortfolioBacktestEngine.prepare_data()),
    uses the fast run_with_prepared() path — indicators computed once.
    Otherwise falls back to engine.run() per window (slower).
    """
    from src.backtest.portfolio_engine import PortfolioBacktestEngine

    windows = generate_windows(start_date, end_date, train_years, test_months, step_months)
    strategy_name = strategy.get("name", "unknown")
    exit_config = strategy.get("exit_config", {})

    if not windows:
        return WalkForwardResult(strategy_name=strategy_name)

    logger.info("Walk-forward: %d rounds for %s (%s ~ %s)", len(windows), strategy_name, start_date, end_date)

    use_fast_path = precomputed is not None and precomputed.get("prepared")

    for i, w in enumerate(windows):
        if progress_callback:
            progress_callback(i + 1, len(windows), f"Round {w.round_num}: test {w.test_start}~{w.test_end}")

        if use_fast_path:
            # Fast path: reuse precomputed indicators, just slice date range
            engine = PortfolioBacktestEngine()
            train_pre = _slice_precomputed(precomputed, w.train_start, w.train_end)
            if train_pre and train_pre.get("sorted_dates"):
                try:
                    w.train_result = engine.run_with_prepared(
                        strategy_name=strategy_name,
                        exit_config=exit_config,
                        precomputed=train_pre,
                        regime_map=regime_map,
                    )
                except Exception as e:
                    logger.warning("Walk-forward train round %d failed: %s", w.round_num, e)

            test_pre = _slice_precomputed(precomputed, w.test_start, w.test_end)
            if test_pre and test_pre.get("sorted_dates"):
                try:
                    w.test_result = engine.run_with_prepared(
                        strategy_name=strategy_name,
                        exit_config=exit_config,
                        precomputed=test_pre,
                        regime_map=regime_map,
                    )
                except Exception as e:
                    logger.warning("Walk-forward test round %d failed: %s", w.round_num, e)
        else:
            # Slow path: full engine.run() per window
            engine = PortfolioBacktestEngine()
            train_data = _filter_stock_data(stock_data, w.train_start, w.train_end)
            if train_data:
                try:
                    w.train_result = engine.run(strategy, train_data, index_data=index_data)
                except Exception as e:
                    logger.warning("Walk-forward train round %d failed: %s", w.round_num, e)

            test_data = _filter_stock_data(stock_data, w.test_start, w.test_end)
            if test_data:
                try:
                    w.test_result = engine.run(strategy, test_data, index_data=index_data)
                except Exception as e:
                    logger.warning("Walk-forward test round %d failed: %s", w.round_num, e)

    # Aggregate results
    return _aggregate_results(strategy_name, windows, train_years, test_months)


def _slice_precomputed(
    precomputed: Dict[str, Any],
    start_date: str,
    end_date: str,
) -> Dict[str, Any]:
    """Slice precomputed data to a date range without recomputing indicators.

    buy_signal_map / sell_signal_map are {stock_code: np.array} where the array
    is aligned row-by-row with that stock's prepared DataFrame.  We must slice
    the arrays using the same row mask we use for the DataFrame.
    """
    import numpy as np

    sorted_dates = precomputed.get("sorted_dates", [])
    filtered_dates = [d for d in sorted_dates if start_date <= d <= end_date]

    if not filtered_dates:
        return {}

    date_set = set(filtered_dates)
    orig_buy_map = precomputed.get("buy_signal_map", {})
    orig_sell_map = precomputed.get("sell_signal_map", {})

    prepared = {}
    stock_date_idx: Dict[str, Dict[str, int]] = {}
    buy_signal_map = {}
    sell_signal_map = {}

    for code, df in precomputed.get("prepared", {}).items():
        if "date" not in df.columns:
            continue

        # Boolean mask for rows in the date window
        mask = df["date"].isin(date_set).values
        sliced = df[mask].reset_index(drop=True)

        if len(sliced) < 10:
            continue

        prepared[code] = sliced

        # Rebuild date→row index
        dates = sliced["date"].tolist()
        stock_date_idx[code] = {d: i for i, d in enumerate(dates)}

        # Slice signal arrays with the same mask
        if code in orig_buy_map:
            buy_signal_map[code] = orig_buy_map[code][mask]
        if code in orig_sell_map:
            sell_signal_map[code] = orig_sell_map[code][mask]

    if not prepared:
        return {}

    return {
        "prepared": prepared,
        "sorted_dates": filtered_dates,
        "stock_date_idx": stock_date_idx,
        "buy_signal_map": buy_signal_map,
        "sell_signal_map": sell_signal_map,
    }


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


def _aggregate_results(
    strategy_name: str,
    windows: List[WalkForwardWindow],
    train_years: float = 2.0,
    test_months: int = 6,
) -> WalkForwardResult:
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

    # ── Walk-Forward Efficiency (WFE) ──
    # Annualize returns before comparing: train=2yr, test=6mo have different durations.
    # WFE = annualized_test / annualized_train (Pardo standard, threshold ≥ 50%)
    # overfit_ratio = annualized_train / annualized_test (inverse, threshold ≤ 2.0)
    train_years_len = train_years
    test_months_len = test_months

    def _annualize(pct_return: float, period_months: float) -> float:
        """Annualize a percentage return. E.g. 17% over 6 months → ~36.9%/year."""
        if period_months <= 0 or pct_return <= -100:
            return 0.0
        growth = 1 + pct_return / 100
        if growth <= 0:
            return -100.0
        years = period_months / 12
        return (growth ** (1 / years) - 1) * 100

    ann_train = _annualize(result.train_avg_return, train_years_len * 12)
    ann_test = _annualize(result.test_avg_return, test_months_len)

    if ann_train > 0 and ann_test > 0:
        result.wfe_pct = round(ann_test / ann_train * 100, 1)
        result.overfit_ratio = round(ann_train / ann_test, 2)
    elif ann_train > 0 and ann_test <= 0:
        result.wfe_pct = 0.0
        result.overfit_ratio = 99.0
    else:
        result.wfe_pct = 0.0
        result.overfit_ratio = 0.0

    logger.info(
        "Walk-forward WFE: train_avg=%.1f%% (ann=%.1f%%), test_avg=%.1f%% (ann=%.1f%%) → "
        "WFE=%.1f%%, overfit=%.2fx, consistency=%.0f%%",
        result.train_avg_return, ann_train, result.test_avg_return, ann_test,
        result.wfe_pct, result.overfit_ratio, result.consistency_pct,
    )

    return result
