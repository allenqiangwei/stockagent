"""Portfolio backtest engine — single-account simulation with position limits.

Replaces the batch backtest for multi-stock strategies. One capital pool,
limited concurrent positions, time-driven execution, multi-factor ranking
when buy signals exceed available slots.
"""

import math
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

import numpy as np
import pandas as pd

from src.signals.rule_engine import evaluate_conditions, collect_indicator_params
from src.indicators.indicator_calculator import IndicatorCalculator, IndicatorConfig
from src.backtest.engine import Trade, calc_limit_prices
from src.backtest.vectorized_signals import vectorize_conditions

logger = logging.getLogger(__name__)


class SignalExplosionError(Exception):
    """Raised when buy conditions are too loose, generating thousands of signals per day."""
    pass


class BacktestTimeoutError(Exception):
    """Raised when a single strategy backtest exceeds the time limit."""
    pass


@dataclass
class Position:
    """An open position in the portfolio."""
    stock_code: str
    buy_date: str
    buy_price: float
    shares: int
    cost_basis: float  # shares * buy_price
    hold_days: int = 0


@dataclass
class PortfolioBacktestResult:
    """Extended backtest result with portfolio-level metrics."""
    strategy_name: str
    start_date: str
    end_date: str
    backtest_mode: str = "portfolio"
    initial_capital: float = 100000.0
    max_positions: int = 10

    # Basic stats
    total_trades: int = 0
    win_trades: int = 0
    lose_trades: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_days: float = 0.0
    avg_pnl_pct: float = 0.0

    # Advanced metrics
    cagr_pct: float = 0.0
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_loss_ratio: float = 0.0

    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)
    sell_reason_stats: dict = field(default_factory=dict)

    # Market regime analysis (stats only, doesn't affect trading)
    regime_stats: dict = field(default_factory=dict)  # {regime: {trades, wins, win_rate, return_pct}}
    index_return_pct: float = 0.0  # Shanghai Index return over same period

    # Benchmark comparison (filled by caller if index data available)
    benchmark_return: float = 0.0   # 基准(沪深300)收益率 %
    excess_return: float = 0.0      # 超额收益 %


class PortfolioBacktestEngine:
    """Portfolio-level backtest: one capital pool, position limits, daily simulation.

    Usage:
        engine = PortfolioBacktestEngine(
            initial_capital=100000,
            max_positions=10,
            position_sizing="equal_weight",
        )
        result = engine.run(strategy_dict, stock_data, daily_basic_data, rank_config)
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        max_positions: int = 10,
        position_sizing: str = "equal_weight",
        max_position_pct: float = 30.0,
        slippage_pct: float = 0.1,
        commission_pct: float = 0.025,   # 佣金 万2.5 (买卖各收)
        stamp_tax_pct: float = 0.05,     # 印花税 (仅卖出)
        transfer_fee_pct: float = 0.001, # 过户费 (仅卖出)
    ):
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.position_sizing = position_sizing
        self.max_position_pct = max_position_pct  # max single stock weight %
        self.slippage_pct = slippage_pct
        self.commission_pct = commission_pct
        self.stamp_tax_pct = stamp_tax_pct
        self.transfer_fee_pct = transfer_fee_pct
        # Pre-compute total sell fee rate for convenience
        self._sell_fee_rate = (commission_pct + stamp_tax_pct + transfer_fee_pct) / 100
        self._buy_fee_rate = commission_pct / 100

    def run(
        self,
        strategy: Dict[str, Any],
        stock_data: Dict[str, pd.DataFrame],
        daily_basic_data: Optional[Dict[str, pd.DataFrame]] = None,
        rank_config: Optional[dict] = None,
        progress_callback=None,
        regime_map: Optional[Dict[str, str]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> PortfolioBacktestResult:
        """Run portfolio backtest across multiple stocks.

        Supports both single-strategy and combo (ensemble voting) strategies.
        Combo strategies are detected by portfolio_config.type == "combo" and
        require a "member_strategies" list with each member's conditions.

        Args:
            strategy: Strategy dict with buy_conditions, sell_conditions, exit_config.
                      For combo strategies, also include portfolio_config and member_strategies.
            stock_data: {stock_code: DataFrame} with OHLCV data
            daily_basic_data: {date_str: DataFrame} with PE/PB/MV data (optional)
            rank_config: Multi-factor ranking config (optional)
            progress_callback: (current, total, message) -> None
            regime_map: {date_str: regime_str} from regime_service (optional)
            cancel_event: threading.Event set externally to abort this backtest

        Returns:
            PortfolioBacktestResult with trades, equity curve, and metrics
        """
        strategy_name = strategy.get("name", "未知策略")
        exit_config = strategy.get("exit_config", {})

        # ── Detect combo strategy ──
        pf_config = strategy.get("portfolio_config") or {}
        is_combo = pf_config.get("type") == "combo"

        if is_combo:
            member_strategies = strategy.get("member_strategies", [])
            combo_vote_threshold = pf_config.get("vote_threshold", 2)
            combo_weight_mode = pf_config.get("weight_mode", "equal")
            combo_score_threshold = pf_config.get("score_threshold", 2.0)
            combo_sell_mode = pf_config.get("sell_mode", "any")
            # Aggregate all buy/sell conditions from members for indicator computation
            buy_conditions = []
            sell_conditions = []
            for m in member_strategies:
                buy_conditions.extend(m.get("buy_conditions", []))
                sell_conditions.extend(m.get("sell_conditions", []))
        else:
            member_strategies = []
            combo_vote_threshold = 0
            combo_weight_mode = "equal"
            combo_score_threshold = 0
            combo_sell_mode = "any"
            buy_conditions = strategy.get("buy_conditions", [])
            sell_conditions = strategy.get("sell_conditions", [])

        stop_loss_pct = exit_config.get("stop_loss_pct")
        take_profit_pct = exit_config.get("take_profit_pct")
        max_hold_days = exit_config.get("max_hold_days")

        if not stock_data:
            return PortfolioBacktestResult(
                strategy_name=strategy_name,
                start_date="",
                end_date="",
                initial_capital=self.initial_capital,
                max_positions=self.max_positions,
            )

        # ── Phase 1: Pre-compute indicators for ALL stocks ──
        all_rules = buy_conditions + sell_conditions
        collected_params = collect_indicator_params(all_rules)

        # Separate daily / weekly / monthly indicator params
        from src.indicators.multi_timeframe import separate_mtf_params, compute_mtf_indicators
        daily_params, weekly_params, monthly_params = separate_mtf_params(collected_params)

        config = IndicatorConfig.from_collected_params(daily_params)
        calculator = IndicatorCalculator(config)

        weekly_config = IndicatorConfig.from_collected_params(weekly_params) if weekly_params else None
        monthly_config = IndicatorConfig.from_collected_params(monthly_params) if monthly_params else None

        # stock_code → full DataFrame (OHLCV + indicators), date-indexed
        prepared: Dict[str, pd.DataFrame] = {}
        total_stocks = len(stock_data)

        # Parallel indicator computation (pandas releases GIL)
        def _compute_one(args):
            code, df = args
            if df is None or df.empty or len(df) < 2:
                return code, None
            indicators = calculator.calculate_all(df)
            df_full = pd.concat(
                [df.reset_index(drop=True), indicators.reset_index(drop=True)],
                axis=1,
            )
            if "date" in df_full.columns:
                df_full["date"] = pd.to_datetime(df_full["date"]).dt.strftime("%Y-%m-%d")

            # Multi-timeframe indicators
            if weekly_config:
                w_df = compute_mtf_indicators(df, weekly_config, "W")
                if w_df is not None:
                    for col in w_df.columns:
                        df_full[col] = w_df[col].values
            if monthly_config:
                m_df = compute_mtf_indicators(df, monthly_config, "M")
                if m_df is not None:
                    for col in m_df.columns:
                        df_full[col] = m_df[col].values

            return code, df_full

        n_workers = min(8, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            results = pool.map(_compute_one, stock_data.items())
            for idx, (code, df_full) in enumerate(results, 1):
                if progress_callback and idx % 100 == 0:
                    progress_callback(idx, total_stocks, f"计算指标: {code}")
                if df_full is not None:
                    prepared[code] = df_full

        if not prepared:
            return PortfolioBacktestResult(
                strategy_name=strategy_name,
                start_date="",
                end_date="",
                initial_capital=self.initial_capital,
                max_positions=self.max_positions,
            )

        # ── Phase 2: Build sorted list of all trading dates ──
        all_dates: set[str] = set()
        # For each stock, map date → row index for O(1) lookup
        stock_date_idx: Dict[str, Dict[str, int]] = {}

        for code, df in prepared.items():
            dates = df["date"].tolist() if "date" in df.columns else []
            idx_map = {}
            for i, d in enumerate(dates):
                idx_map[d] = i
                all_dates.add(d)
            stock_date_idx[code] = idx_map

        sorted_dates = sorted(all_dates)
        if len(sorted_dates) < 2:
            return PortfolioBacktestResult(
                strategy_name=strategy_name,
                start_date=sorted_dates[0] if sorted_dates else "",
                end_date=sorted_dates[-1] if sorted_dates else "",
                initial_capital=self.initial_capital,
                max_positions=self.max_positions,
            )

        # ── Phase 2b: Pre-compute vectorized buy/sell signals ──
        # For non-combo strategies, replace per-row evaluate_conditions with
        # one-shot vectorized computation. Combo strategies still use per-row.
        buy_signal_map: Dict[str, np.ndarray] = {}
        sell_signal_map: Dict[str, np.ndarray] = {}

        if not is_combo:
            def _vectorize_buy(args):
                code, df_full = args
                return code, vectorize_conditions(buy_conditions, df_full, mode="AND")

            def _vectorize_sell(args):
                code, df_full = args
                if sell_conditions:
                    return code, vectorize_conditions(sell_conditions, df_full, mode="OR")
                return code, np.zeros(len(df_full), dtype=bool)

            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                buy_signal_map = dict(pool.map(_vectorize_buy, prepared.items()))
                sell_signal_map = dict(pool.map(_vectorize_sell, prepared.items()))

            # T+1 信号偏移: signal[T] 的意图在 T+1 执行
            for code in buy_signal_map:
                arr = buy_signal_map[code]
                shifted = np.zeros_like(arr)
                shifted[1:] = arr[:-1]
                buy_signal_map[code] = shifted

            for code in sell_signal_map:
                arr = sell_signal_map[code]
                shifted = np.zeros_like(arr)
                shifted[1:] = arr[:-1]
                sell_signal_map[code] = shifted

            logger.info(
                "Vectorized signals (T+1 shifted): %d stocks, buy_signals=%d total, sell_signals=%d total",
                len(buy_signal_map),
                sum(v.sum() for v in buy_signal_map.values()),
                sum(v.sum() for v in sell_signal_map.values()),
            )

        # ── Phase 3: Day-by-day simulation (T+1 execution model) ──
        # 信号已偏移1天: signal[T+1] = original[T]，以 T+1 开盘价执行。
        # SL/TP 为挂单，日内触发立即执行。Max hold → pending sell。
        cash = self.initial_capital
        positions: Dict[str, Position] = {}  # stock_code → Position
        trades: List[Trade] = []
        equity_curve: List[dict] = []
        held_codes: set[str] = set()
        slippage = self.slippage_pct
        # Max hold pending sells (code → reason), retried on limit-down
        pending_max_hold_sells: Dict[str, str] = {}
        # Combo pending (not vectorized)
        pending_combo_buys: set[str] = set()
        pending_combo_sells: Dict[str, str] = {}
        # Signal explosion detection
        _early_candidate_counts: List[int] = []
        _recent_candidate_counts: List[int] = []
        _EXPLOSION_CHECK_DAYS = 10
        _EXPLOSION_THRESHOLD = 500
        _PERIODIC_CHECK_INTERVAL = 50
        _PERIODIC_THRESHOLD = 300

        for day_idx, current_date in enumerate(sorted_dates):
            # ── Timeout check ──
            if cancel_event is not None and cancel_event.is_set():
                raise BacktestTimeoutError(
                    f"回测超时: 在第{day_idx}天/{len(sorted_dates)}天被取消 "
                    f"(日期 {current_date})"
                )

            if progress_callback and day_idx % 20 == 0:
                progress_callback(
                    day_idx, len(sorted_dates),
                    f"模拟交易: {current_date} ({day_idx}/{len(sorted_dates)})",
                )

            # ── 3a: Execute pending sells + check SL/TP + check signals ──
            codes_to_sell: List[tuple] = []  # (code, reason, price_override)

            for code, pos in list(positions.items()):
                if code not in stock_date_idx or current_date not in stock_date_idx[code]:
                    pos.hold_days += 1
                    continue

                row_idx = stock_date_idx[code][current_date]
                df_stock = prepared[code]
                row = df_stock.iloc[row_idx]

                # Suspension check: volume == 0 means stock is suspended
                volume = float(row.get("volume", 0))
                if volume <= 0:
                    pos.hold_days += 1
                    continue  # Can't trade suspended stock

                open_p = float(row.get("open", row["close"]))
                close = float(row["close"])
                low = float(row.get("low", close))
                high = float(row.get("high", close))
                pos.hold_days += 1

                # Calculate limit prices from previous close
                prev_close_val = close  # fallback
                if row_idx > 0:
                    prev_close_val = float(df_stock.iloc[row_idx - 1]["close"])
                limit_up, limit_down = calc_limit_prices(code, prev_close_val)

                sell_reason = None
                sell_price_override = None

                # ── Priority 0: Execute pending sell at open ──
                if code in pending_max_hold_sells:
                    if open_p >= limit_down:  # Fix#4: >= 允许跌停价成交
                        sell_reason = pending_max_hold_sells.pop(code)
                        sell_price_override = max(open_p * (1 - slippage / 100), limit_down)
                    else:
                        # 跌停，下一天重试
                        continue
                elif code in pending_combo_sells:
                    if open_p >= limit_down:  # Fix#4
                        sell_reason = pending_combo_sells.pop(code)
                        sell_price_override = max(open_p * (1 - slippage / 100), limit_down)
                    else:
                        continue

                # ── Priority 1: Stop loss — intraday, gap-aware ──
                if sell_reason is None and stop_loss_pct is not None:
                    loss_threshold = pos.buy_price * (1 + stop_loss_pct / 100)
                    if open_p <= loss_threshold:
                        # 跳空低开触发止损
                        if open_p >= limit_down:  # Fix#6: 跌停检查
                            sell_reason = "stop_loss"
                            sell_price_override = max(open_p * (1 - slippage / 100), limit_down)
                        else:
                            # 跌停无法成交，转 pending 下一天重试
                            pending_max_hold_sells[code] = "stop_loss"
                    elif low <= loss_threshold:
                        # 日内触发止损
                        sell_reason = "stop_loss"
                        sell_price_override = max(loss_threshold * (1 - slippage / 100), limit_down)

                # ── Priority 2: Take profit — intraday, gap-aware ──
                if sell_reason is None and take_profit_pct is not None and code not in pending_max_hold_sells:
                    profit_threshold = pos.buy_price * (1 + take_profit_pct / 100)
                    if open_p >= profit_threshold:
                        sell_reason = "take_profit"
                        sell_price_override = max(open_p * (1 - slippage / 100), limit_down)  # Fix#5: 卖出不低于跌停
                    elif high >= profit_threshold:
                        sell_reason = "take_profit"
                        sell_price_override = max(profit_threshold * (1 - slippage / 100), limit_down)  # Fix#5

                # ── Priority 3: Strategy exit (shifted signal) → sell at open ──
                if sell_reason is None and code not in pending_max_hold_sells:
                    if is_combo and member_strategies:
                        # Combo sell: evaluate → pending for next day
                        df_slice = df_stock.iloc[: row_idx + 1]
                        sell_votes = 0
                        for m in member_strategies:
                            m_sell = m.get("sell_conditions", [])
                            if m_sell:
                                triggered, _ = evaluate_conditions(m_sell, df_slice, mode="OR")
                                if triggered:
                                    sell_votes += 1
                            if combo_sell_mode == "any" and sell_votes > 0:
                                break
                            if combo_sell_mode == "majority" and sell_votes > len(member_strategies) / 2:
                                break
                        combo_sell_triggered = (
                            (combo_sell_mode == "any" and sell_votes > 0)
                            or (combo_sell_mode == "majority" and sell_votes > len(member_strategies) / 2)
                        )
                        if combo_sell_triggered:
                            pending_combo_sells[code] = "strategy_exit"
                    elif sell_conditions:
                        # Vectorized sell signal (already shifted T+1) → sell at open
                        sell_vec = sell_signal_map.get(code)
                        if sell_vec is not None and row_idx < len(sell_vec) and sell_vec[row_idx]:
                            if open_p >= limit_down:  # Fix#4
                                sell_reason = "strategy_exit"
                                sell_price_override = max(open_p * (1 - slippage / 100), limit_down)
                            else:
                                pending_max_hold_sells[code] = "strategy_exit"  # Fix#7: 跌停重试
                        elif sell_vec is None:
                            df_slice = df_stock.iloc[: row_idx + 1]
                            triggered, _ = evaluate_conditions(sell_conditions, df_slice, mode="OR")
                            if triggered:
                                pending_combo_sells[code] = "strategy_exit"

                # ── Priority 4: Max hold days → pending sell for next day ──
                if sell_reason is None and code not in pending_max_hold_sells:
                    if max_hold_days is not None and pos.hold_days >= max_hold_days:
                        pending_max_hold_sells[code] = "max_hold"

                if sell_reason:
                    codes_to_sell.append((code, sell_reason, sell_price_override))

            # Execute sells
            for code, reason, price_override in codes_to_sell:
                pos = positions.pop(code)
                held_codes.discard(code)
                row_idx = stock_date_idx[code][current_date]
                close = float(prepared[code].iloc[row_idx]["close"])
                exec_price = price_override if price_override is not None else close
                gross_proceeds = pos.shares * exec_price
                sell_fees = gross_proceeds * self._sell_fee_rate
                net_proceeds = gross_proceeds - sell_fees
                cash += net_proceeds

                # PnL reflects actual costs (buy commission + sell fees)
                effective_buy = pos.buy_price * (1 + self._buy_fee_rate)
                effective_sell = exec_price * (1 - self._sell_fee_rate)
                pnl_pct = (effective_sell - effective_buy) / effective_buy * 100

                trades.append(Trade(
                    stock_code=code,
                    strategy_name=strategy_name,
                    buy_date=pos.buy_date,
                    buy_price=pos.buy_price,
                    sell_date=current_date,
                    sell_price=exec_price,
                    sell_reason=reason,
                    pnl_pct=round(pnl_pct, 4),
                    hold_days=pos.hold_days,
                    regime=regime_map.get(pos.buy_date, "") if regime_map else "",
                ))

            # Clean up pending sells for positions that were sold
            for code in list(pending_max_hold_sells):
                if code not in positions:
                    pending_max_hold_sells.pop(code, None)
            for code in list(pending_combo_sells):
                if code not in positions:
                    pending_combo_sells.pop(code, None)

            # ── 3b: Scan for buy signals on non-held stocks ──
            open_slots = self.max_positions - len(positions)
            has_buy_logic = buy_conditions if not is_combo else member_strategies
            if open_slots > 0 and has_buy_logic:
                candidates: List[tuple[str, float]] = []  # (code, buy_price)

                for code, df_stock in prepared.items():
                    if code in held_codes:
                        continue
                    if current_date not in stock_date_idx.get(code, {}):
                        continue

                    row_idx = stock_date_idx[code][current_date]
                    if row_idx < 1:
                        continue

                    if is_combo and member_strategies:
                        # Suspension check: skip if volume == 0
                        volume = float(df_stock.iloc[row_idx].get("volume", 0))
                        if volume <= 0:
                            continue
                        # Combo: check if pending buy from yesterday
                        if code in pending_combo_buys:
                            pending_combo_buys.discard(code)
                            open_p = float(df_stock.iloc[row_idx].get("open", df_stock.iloc[row_idx]["close"]))
                            prev_c = float(df_stock.iloc[row_idx - 1]["close"])
                            lu, _ = calc_limit_prices(code, prev_c)
                            if open_p <= lu:  # Fix#4: <= 允许涨停价成交
                                buy_price = min(open_p * (1 + slippage / 100), lu)
                                if buy_price > 0:
                                    candidates.append((code, buy_price))
                        else:
                            # Evaluate combo buy conditions → set pending for next day
                            df_slice = df_stock.iloc[: row_idx + 1]
                            buy_votes = 0
                            weighted_score = 0.0
                            for m in member_strategies:
                                m_buy = m.get("buy_conditions", [])
                                if m_buy:
                                    triggered, _ = evaluate_conditions(m_buy, df_slice, mode="AND")
                                    if triggered:
                                        buy_votes += 1
                                        weighted_score += m.get("weight", 1.0)
                                if combo_weight_mode == "equal" and buy_votes >= combo_vote_threshold:
                                    break
                                if combo_weight_mode != "equal" and weighted_score >= combo_score_threshold:
                                    break
                            if combo_weight_mode == "equal":
                                combo_buy = buy_votes >= combo_vote_threshold
                            else:
                                combo_buy = weighted_score >= combo_score_threshold
                            if combo_buy:
                                pending_combo_buys.add(code)
                    else:
                        # Vectorized buy signal (already shifted T+1) → buy at open
                        buy_vec = buy_signal_map.get(code)
                        if buy_vec is not None and row_idx < len(buy_vec):
                            buy_signal = bool(buy_vec[row_idx])
                        else:
                            df_slice = df_stock.iloc[: row_idx + 1]
                            triggered, _ = evaluate_conditions(buy_conditions, df_slice, mode="AND")
                            buy_signal = triggered

                        if buy_signal:
                            # Suspension check: skip if volume == 0
                            volume = float(df_stock.iloc[row_idx].get("volume", 0))
                            if volume <= 0:
                                continue
                            open_p = float(df_stock.iloc[row_idx].get("open", df_stock.iloc[row_idx]["close"]))
                            prev_c = float(df_stock.iloc[row_idx - 1]["close"])
                            limit_up, _ = calc_limit_prices(code, prev_c)
                            if open_p <= limit_up:  # Fix#4: <= 允许涨停价成交
                                buy_price = min(open_p * (1 + slippage / 100), limit_up)
                                if buy_price > 0:
                                    candidates.append((code, buy_price))

                # ── Signal explosion early-abort ──
                if day_idx < _EXPLOSION_CHECK_DAYS:
                    _early_candidate_counts.append(len(candidates))
                    if day_idx == _EXPLOSION_CHECK_DAYS - 1:
                        avg_cands = sum(_early_candidate_counts) / len(_early_candidate_counts)
                        if avg_cands > _EXPLOSION_THRESHOLD:
                            raise SignalExplosionError(
                                f"信号爆炸: 前{_EXPLOSION_CHECK_DAYS}天平均{avg_cands:.0f}个买入信号/天"
                                f"(阈值{_EXPLOSION_THRESHOLD}), 买入条件过宽, 终止回测"
                            )

                # ── Periodic signal explosion re-check ──
                if day_idx >= _EXPLOSION_CHECK_DAYS:
                    _recent_candidate_counts.append(len(candidates))
                    if len(_recent_candidate_counts) >= _PERIODIC_CHECK_INTERVAL:
                        avg_recent = sum(_recent_candidate_counts) / len(_recent_candidate_counts)
                        if avg_recent > _PERIODIC_THRESHOLD:
                            raise SignalExplosionError(
                                f"信号爆炸(周期检测): 第{day_idx-_PERIODIC_CHECK_INTERVAL+1}-{day_idx}天"
                                f"平均{avg_recent:.0f}个买入信号/天"
                                f"(阈值{_PERIODIC_THRESHOLD}), 终止回测"
                            )
                        _recent_candidate_counts.clear()

                # ── 3c: Rank candidates by multi-factor score ──
                if len(candidates) > open_slots:
                    candidates = self._rank_candidates(
                        candidates, current_date, prepared,
                        stock_date_idx, daily_basic_data, rank_config,
                    )

                # ── 3d: Buy top-N to fill slots (at open price) ──
                portfolio_equity = cash + sum(
                    pos.shares * (
                        float(prepared[c].iloc[stock_date_idx[c][current_date]]["close"])
                        if current_date in stock_date_idx.get(c, {})
                        else pos.buy_price
                    )
                    for c, pos in positions.items()
                )

                for code, buy_price in candidates[:open_slots]:
                    target_value = portfolio_equity / self.max_positions
                    max_value = portfolio_equity * self.max_position_pct / 100
                    target_value = min(target_value, max_value)
                    shares = math.floor(target_value / buy_price)
                    if shares <= 0:
                        continue
                    cost = shares * buy_price
                    buy_commission = cost * self._buy_fee_rate
                    total_cost = cost + buy_commission
                    if total_cost > cash:
                        shares = math.floor(cash / (buy_price * (1 + self._buy_fee_rate)))
                        if shares <= 0:
                            continue
                        cost = shares * buy_price
                        buy_commission = cost * self._buy_fee_rate
                        total_cost = cost + buy_commission

                    cash -= total_cost
                    positions[code] = Position(
                        stock_code=code,
                        buy_date=current_date,
                        buy_price=buy_price,
                        shares=shares,
                        cost_basis=cost,
                    )
                    held_codes.add(code)
                    open_slots -= 1
                    if open_slots <= 0:
                        break

            # ── 3e: Record daily equity ──
            position_value = 0.0
            for code, pos in positions.items():
                if current_date in stock_date_idx.get(code, {}):
                    row_idx = stock_date_idx[code][current_date]
                    price = float(prepared[code].iloc[row_idx]["close"])
                else:
                    price = pos.buy_price
                position_value += pos.shares * price

            equity = cash + position_value
            equity_curve.append({"date": current_date, "equity": round(equity, 2)})

        # ── Phase 4: Force-close remaining positions at last date ──
        last_date = sorted_dates[-1]
        for code, pos in list(positions.items()):
            if last_date in stock_date_idx.get(code, {}):
                row_idx = stock_date_idx[code][last_date]
                close = float(prepared[code].iloc[row_idx]["close"])
            else:
                # Find last available price
                df_stock = prepared[code]
                close = float(df_stock.iloc[-1]["close"])

            gross_proceeds = pos.shares * close
            sell_fees = gross_proceeds * self._sell_fee_rate
            net_proceeds = gross_proceeds - sell_fees
            cash += net_proceeds

            effective_buy = pos.buy_price * (1 + self._buy_fee_rate)
            effective_sell = close * (1 - self._sell_fee_rate)
            pnl_pct = (effective_sell - effective_buy) / effective_buy * 100

            trades.append(Trade(
                stock_code=code,
                strategy_name=strategy_name,
                buy_date=pos.buy_date,
                buy_price=pos.buy_price,
                sell_date=last_date,
                sell_price=close,
                sell_reason="end_of_backtest",
                pnl_pct=round(pnl_pct, 4),
                hold_days=pos.hold_days,
                regime=regime_map.get(pos.buy_date, "") if regime_map else "",
            ))

        positions.clear()
        held_codes.clear()

        # Update final equity point
        if equity_curve:
            equity_curve[-1]["equity"] = round(cash, 2)

        # ── Phase 5: Build result with metrics ──
        return self._build_result(
            strategy_name=strategy_name,
            trades=trades,
            equity_curve=equity_curve,
            start_date=sorted_dates[0],
            end_date=sorted_dates[-1],
            regime_map=regime_map,
        )

    def prepare_data(
        self,
        strategy: Dict[str, Any],
        stock_data: Dict[str, pd.DataFrame],
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Phase 1+2: Compute indicators and build date index (reusable for batch).

        Returns a dict with prepared DataFrames, date indices, and vectorized signals
        that can be passed to run_with_prepared() multiple times with different exit configs.
        """
        buy_conditions = strategy.get("buy_conditions", [])
        sell_conditions = strategy.get("sell_conditions", [])

        all_rules = buy_conditions + sell_conditions
        collected_params = collect_indicator_params(all_rules)

        # Separate daily / weekly / monthly indicator params
        from src.indicators.multi_timeframe import separate_mtf_params, compute_mtf_indicators
        daily_params, weekly_params, monthly_params = separate_mtf_params(collected_params)

        config = IndicatorConfig.from_collected_params(daily_params)
        calculator = IndicatorCalculator(config)

        # Build configs for multi-timeframe (only if conditions reference W_/M_ fields)
        weekly_config = IndicatorConfig.from_collected_params(weekly_params) if weekly_params else None
        monthly_config = IndicatorConfig.from_collected_params(monthly_params) if monthly_params else None

        # Phase 1: Parallel indicator computation
        prepared: Dict[str, pd.DataFrame] = {}
        total_stocks = len(stock_data)

        def _compute_one(args):
            code, df = args
            if df is None or df.empty or len(df) < 2:
                return code, None
            indicators = calculator.calculate_all(df)
            df_full = pd.concat(
                [df.reset_index(drop=True), indicators.reset_index(drop=True)],
                axis=1,
            )
            if "date" in df_full.columns:
                df_full["date"] = pd.to_datetime(df_full["date"]).dt.strftime("%Y-%m-%d")

            # Multi-timeframe: compute weekly/monthly indicators, forward-fill to daily
            if weekly_config:
                w_df = compute_mtf_indicators(df, weekly_config, "W")
                if w_df is not None:
                    for col in w_df.columns:
                        df_full[col] = w_df[col].values
            if monthly_config:
                m_df = compute_mtf_indicators(df, monthly_config, "M")
                if m_df is not None:
                    for col in m_df.columns:
                        df_full[col] = m_df[col].values

            return code, df_full

        n_workers = min(8, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            results = pool.map(_compute_one, stock_data.items())
            for idx, (code, df_full) in enumerate(results, 1):
                if progress_callback and idx % 100 == 0:
                    progress_callback(idx, total_stocks, f"计算指标: {code}")
                if df_full is not None:
                    prepared[code] = df_full

        if not prepared:
            return {"prepared": {}, "sorted_dates": [], "stock_date_idx": {},
                    "buy_signal_map": {}, "sell_signal_map": {}}

        # Phase 2: Build date index
        all_dates: set[str] = set()
        stock_date_idx: Dict[str, Dict[str, int]] = {}
        for code, df in prepared.items():
            dates = df["date"].tolist() if "date" in df.columns else []
            idx_map = {}
            for i, d in enumerate(dates):
                idx_map[d] = i
                all_dates.add(d)
            stock_date_idx[code] = idx_map

        sorted_dates = sorted(all_dates)

        # Phase 2b: Vectorized signals
        buy_signal_map: Dict[str, np.ndarray] = {}
        sell_signal_map: Dict[str, np.ndarray] = {}

        def _vectorize_buy(args):
            code, df_full = args
            return code, vectorize_conditions(buy_conditions, df_full, mode="AND")

        def _vectorize_sell(args):
            code, df_full = args
            if sell_conditions:
                return code, vectorize_conditions(sell_conditions, df_full, mode="OR")
            return code, np.zeros(len(df_full), dtype=bool)

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            buy_signal_map = dict(pool.map(_vectorize_buy, prepared.items()))
            sell_signal_map = dict(pool.map(_vectorize_sell, prepared.items()))

        # T+1 信号偏移: signal[T] 的意图在 T+1 执行
        for code in buy_signal_map:
            arr = buy_signal_map[code]
            shifted = np.zeros_like(arr)
            shifted[1:] = arr[:-1]
            buy_signal_map[code] = shifted

        for code in sell_signal_map:
            arr = sell_signal_map[code]
            shifted = np.zeros_like(arr)
            shifted[1:] = arr[:-1]
            sell_signal_map[code] = shifted

        return {
            "prepared": prepared,
            "sorted_dates": sorted_dates,
            "stock_date_idx": stock_date_idx,
            "buy_signal_map": buy_signal_map,
            "sell_signal_map": sell_signal_map,
        }

    def run_with_prepared(
        self,
        strategy_name: str,
        exit_config: Dict[str, Any],
        precomputed: Dict[str, Any],
        regime_map: Optional[Dict[str, str]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> "PortfolioBacktestResult":
        """Run Phase 3-5 using pre-computed data from prepare_data().

        This is the fast path for batch clone-backtest: data loading and
        indicator computation are done once, and only the trade simulation
        is repeated for each exit config.
        """
        prepared = precomputed["prepared"]
        sorted_dates = precomputed["sorted_dates"]
        stock_date_idx = precomputed["stock_date_idx"]
        buy_signal_map = precomputed["buy_signal_map"]
        sell_signal_map = precomputed["sell_signal_map"]

        if not prepared or len(sorted_dates) < 2:
            return PortfolioBacktestResult(
                strategy_name=strategy_name,
                start_date=sorted_dates[0] if sorted_dates else "",
                end_date=sorted_dates[-1] if sorted_dates else "",
                initial_capital=self.initial_capital,
                max_positions=self.max_positions,
            )

        stop_loss_pct = exit_config.get("stop_loss_pct")
        take_profit_pct = exit_config.get("take_profit_pct")
        max_hold_days = exit_config.get("max_hold_days")

        # Phase 3: Day-by-day simulation (T+1 execution model)
        # Signals already shifted in prepare_data(): signal[T+1] = original[T]
        # SL/TP are intraday standing orders (gap-aware). Max hold → pending sell.
        cash = self.initial_capital
        positions: Dict[str, Position] = {}
        trades: List[Trade] = []
        equity_curve: List[dict] = []
        held_codes: set[str] = set()
        slippage = self.slippage_pct
        pending_max_hold_sells: Dict[str, str] = {}
        _early_candidate_counts: List[int] = []
        _recent_candidate_counts: List[int] = []
        _EXPLOSION_CHECK_DAYS = 10
        _EXPLOSION_THRESHOLD = 500
        _PERIODIC_CHECK_INTERVAL = 50
        _PERIODIC_THRESHOLD = 300

        for day_idx, current_date in enumerate(sorted_dates):
            if cancel_event is not None and cancel_event.is_set():
                raise BacktestTimeoutError(
                    f"回测超时: 在第{day_idx}天/{len(sorted_dates)}天被取消"
                )

            # ── 3a: Sell logic ──
            codes_to_sell: List[tuple] = []
            for code, pos in list(positions.items()):
                if code not in stock_date_idx or current_date not in stock_date_idx[code]:
                    pos.hold_days += 1
                    continue

                row_idx = stock_date_idx[code][current_date]
                df_stock = prepared[code]
                row = df_stock.iloc[row_idx]

                # Suspension check: volume == 0 means stock is suspended
                volume = float(row.get("volume", 0))
                if volume <= 0:
                    pos.hold_days += 1
                    continue  # Can't trade suspended stock

                open_p = float(row.get("open", row["close"]))
                close = float(row["close"])
                low = float(row.get("low", close))
                high = float(row.get("high", close))
                pos.hold_days += 1

                prev_close_val = close
                if row_idx > 0:
                    prev_close_val = float(df_stock.iloc[row_idx - 1]["close"])
                limit_up, limit_down = calc_limit_prices(code, prev_close_val)

                sell_reason = None
                sell_price_override = None

                # Priority 0: Execute pending sell at open
                if code in pending_max_hold_sells:
                    if open_p >= limit_down:  # Fix#4: >= 允许跌停价成交
                        sell_reason = pending_max_hold_sells.pop(code)
                        sell_price_override = max(open_p * (1 - slippage / 100), limit_down)
                    else:
                        continue  # 跌停，下一天重试

                # Priority 1: Stop loss — intraday, gap-aware
                if sell_reason is None and stop_loss_pct is not None:
                    loss_threshold = pos.buy_price * (1 + stop_loss_pct / 100)
                    if open_p <= loss_threshold:
                        if open_p >= limit_down:  # Fix#6: 跌停检查
                            sell_reason = "stop_loss"
                            sell_price_override = max(open_p * (1 - slippage / 100), limit_down)
                        else:
                            pending_max_hold_sells[code] = "stop_loss"
                    elif low <= loss_threshold:
                        sell_reason = "stop_loss"
                        sell_price_override = max(loss_threshold * (1 - slippage / 100), limit_down)

                # Priority 2: Take profit — intraday, gap-aware
                if sell_reason is None and take_profit_pct is not None and code not in pending_max_hold_sells:
                    profit_threshold = pos.buy_price * (1 + take_profit_pct / 100)
                    if open_p >= profit_threshold:
                        sell_reason = "take_profit"
                        sell_price_override = max(open_p * (1 - slippage / 100), limit_down)  # Fix#5
                    elif high >= profit_threshold:
                        sell_reason = "take_profit"
                        sell_price_override = max(profit_threshold * (1 - slippage / 100), limit_down)  # Fix#5

                # Priority 3: Strategy exit (shifted signal) → sell at open
                if sell_reason is None and code not in pending_max_hold_sells:
                    sell_vec = sell_signal_map.get(code)
                    if sell_vec is not None and row_idx < len(sell_vec) and sell_vec[row_idx]:
                        if open_p >= limit_down:  # Fix#4
                            sell_reason = "strategy_exit"
                            sell_price_override = max(open_p * (1 - slippage / 100), limit_down)
                        else:
                            pending_max_hold_sells[code] = "strategy_exit"  # Fix#7: 跌停重试

                # Priority 4: Max hold → pending sell for next day
                if sell_reason is None and code not in pending_max_hold_sells:
                    if max_hold_days is not None and pos.hold_days >= max_hold_days:
                        pending_max_hold_sells[code] = "max_hold"

                if sell_reason:
                    codes_to_sell.append((code, sell_reason, sell_price_override))

            # Execute sells
            for code, reason, price_override in codes_to_sell:
                pos = positions.pop(code)
                held_codes.discard(code)
                row_idx = stock_date_idx[code][current_date]
                close = float(prepared[code].iloc[row_idx]["close"])
                exec_price = price_override if price_override is not None else close
                gross_proceeds = pos.shares * exec_price
                sell_fees = gross_proceeds * self._sell_fee_rate
                net_proceeds = gross_proceeds - sell_fees
                cash += net_proceeds

                effective_buy = pos.buy_price * (1 + self._buy_fee_rate)
                effective_sell = exec_price * (1 - self._sell_fee_rate)
                pnl_pct = (effective_sell - effective_buy) / effective_buy * 100

                trades.append(Trade(
                    stock_code=code,
                    strategy_name=strategy_name,
                    buy_date=pos.buy_date,
                    buy_price=pos.buy_price,
                    sell_date=current_date,
                    sell_price=exec_price,
                    sell_reason=reason,
                    pnl_pct=round(pnl_pct, 4),
                    hold_days=pos.hold_days,
                    regime=regime_map.get(pos.buy_date, "") if regime_map else "",
                ))

            # Clean up pending sells for positions that were sold
            for code in list(pending_max_hold_sells):
                if code not in positions:
                    pending_max_hold_sells.pop(code, None)

            # ── 3b: Scan for buys (shifted signals → buy at open) ──
            open_slots = self.max_positions - len(positions)
            if open_slots > 0 and buy_signal_map:
                candidates: List[tuple[str, float]] = []
                for code in prepared:
                    if code in held_codes:
                        continue
                    if current_date not in stock_date_idx.get(code, {}):
                        continue
                    row_idx = stock_date_idx[code][current_date]
                    if row_idx < 1:
                        continue
                    buy_vec = buy_signal_map.get(code)
                    if buy_vec is not None and row_idx < len(buy_vec) and buy_vec[row_idx]:
                        df_stock = prepared[code]
                        # Suspension check: skip if volume == 0
                        volume = float(df_stock.iloc[row_idx].get("volume", 0))
                        if volume <= 0:
                            continue
                        open_p = float(df_stock.iloc[row_idx].get("open", df_stock.iloc[row_idx]["close"]))
                        prev_c = float(df_stock.iloc[row_idx - 1]["close"])
                        limit_up, _ = calc_limit_prices(code, prev_c)
                        if open_p <= limit_up:  # Fix#4: <= 允许涨停价成交
                            buy_price = min(open_p * (1 + slippage / 100), limit_up)
                            if buy_price > 0:
                                candidates.append((code, buy_price))

                # Signal explosion detection
                if day_idx < _EXPLOSION_CHECK_DAYS:
                    _early_candidate_counts.append(len(candidates))
                    if day_idx == _EXPLOSION_CHECK_DAYS - 1:
                        avg_cands = sum(_early_candidate_counts) / len(_early_candidate_counts)
                        if avg_cands > _EXPLOSION_THRESHOLD:
                            raise SignalExplosionError(
                                f"信号爆炸: 前{_EXPLOSION_CHECK_DAYS}天平均{avg_cands:.0f}个买入信号/天"
                            )
                if day_idx >= _EXPLOSION_CHECK_DAYS:
                    _recent_candidate_counts.append(len(candidates))
                    if len(_recent_candidate_counts) >= _PERIODIC_CHECK_INTERVAL:
                        avg_recent = sum(_recent_candidate_counts) / len(_recent_candidate_counts)
                        if avg_recent > _PERIODIC_THRESHOLD:
                            raise SignalExplosionError(
                                f"信号爆炸(周期检测): 平均{avg_recent:.0f}个买入信号/天"
                            )
                        _recent_candidate_counts.clear()

                # Rank + buy
                if len(candidates) > open_slots:
                    candidates = self._rank_candidates(
                        candidates, current_date, prepared,
                        stock_date_idx, None, None,
                    )

                portfolio_equity = cash + sum(
                    pos.shares * (
                        float(prepared[c].iloc[stock_date_idx[c][current_date]]["close"])
                        if current_date in stock_date_idx.get(c, {})
                        else pos.buy_price
                    )
                    for c, pos in positions.items()
                )
                for code, buy_price in candidates[:open_slots]:
                    target_value = portfolio_equity / self.max_positions
                    max_value = portfolio_equity * self.max_position_pct / 100
                    target_value = min(target_value, max_value)
                    shares = math.floor(target_value / buy_price)
                    if shares <= 0:
                        continue
                    cost = shares * buy_price
                    buy_commission = cost * self._buy_fee_rate
                    total_cost = cost + buy_commission
                    if total_cost > cash:
                        shares = math.floor(cash / (buy_price * (1 + self._buy_fee_rate)))
                        if shares <= 0:
                            continue
                        cost = shares * buy_price
                        buy_commission = cost * self._buy_fee_rate
                        total_cost = cost + buy_commission
                    cash -= total_cost
                    positions[code] = Position(
                        stock_code=code, buy_date=current_date,
                        buy_price=buy_price, shares=shares, cost_basis=cost,
                    )
                    held_codes.add(code)
                    open_slots -= 1
                    if open_slots <= 0:
                        break

            # ── 3e: Record equity ──
            position_value = sum(
                pos.shares * (
                    float(prepared[c].iloc[stock_date_idx[c][current_date]]["close"])
                    if current_date in stock_date_idx.get(c, {})
                    else pos.buy_price
                )
                for c, pos in positions.items()
            )
            equity_curve.append({"date": current_date, "equity": round(cash + position_value, 2)})

        # Phase 4: Force-close remaining
        last_date = sorted_dates[-1]
        for code, pos in list(positions.items()):
            if last_date in stock_date_idx.get(code, {}):
                row_idx = stock_date_idx[code][last_date]
                close = float(prepared[code].iloc[row_idx]["close"])
            else:
                close = float(prepared[code].iloc[-1]["close"])

            gross_proceeds = pos.shares * close
            sell_fees = gross_proceeds * self._sell_fee_rate
            net_proceeds = gross_proceeds - sell_fees
            cash += net_proceeds

            effective_buy = pos.buy_price * (1 + self._buy_fee_rate)
            effective_sell = close * (1 - self._sell_fee_rate)
            pnl_pct = (effective_sell - effective_buy) / effective_buy * 100

            trades.append(Trade(
                stock_code=code, strategy_name=strategy_name,
                buy_date=pos.buy_date, buy_price=pos.buy_price,
                sell_date=last_date, sell_price=close,
                sell_reason="end_of_backtest", pnl_pct=round(pnl_pct, 4),
                hold_days=pos.hold_days,
                regime=regime_map.get(pos.buy_date, "") if regime_map else "",
            ))
        positions.clear()
        held_codes.clear()
        if equity_curve:
            equity_curve[-1]["equity"] = round(cash, 2)

        return self._build_result(
            strategy_name=strategy_name, trades=trades,
            equity_curve=equity_curve, start_date=sorted_dates[0],
            end_date=sorted_dates[-1], regime_map=regime_map,
        )

    def _rank_candidates(
        self,
        candidates: List[tuple[str, float]],
        current_date: str,
        prepared: Dict[str, pd.DataFrame],
        stock_date_idx: Dict[str, Dict[str, int]],
        daily_basic_data: Optional[Dict[str, pd.DataFrame]],
        rank_config: Optional[dict],
    ) -> List[tuple[str, float]]:
        """Rank buy candidates by multi-factor scoring.

        Each factor: raw values → percentile rank (0..1) among candidates → weighted sum.
        Default (no config): volume descending.
        """
        if not rank_config or not rank_config.get("factors"):
            # Default: sort by volume descending
            def get_volume(item: tuple[str, float]) -> float:
                code = item[0]
                if current_date in stock_date_idx.get(code, {}):
                    idx = stock_date_idx[code][current_date]
                    return float(prepared[code].iloc[idx].get("volume", 0))
                return 0.0
            return sorted(candidates, key=get_volume, reverse=True)

        factors = rank_config["factors"]
        basic_df = daily_basic_data.get(current_date) if daily_basic_data else None

        # Compute composite score for each candidate
        scores: Dict[str, float] = {}
        codes = [c[0] for c in candidates]

        for factor in factors:
            ftype = factor.get("type", "kline")
            ffield = factor.get("field", "volume")
            direction = factor.get("direction", "desc")  # "asc" or "desc"
            weight = factor.get("weight", 1.0)

            raw_values: Dict[str, float] = {}
            for code in codes:
                val = self._get_factor_value(
                    code, current_date, ftype, ffield,
                    factor.get("params"),
                    prepared, stock_date_idx, basic_df,
                )
                if val is not None:
                    raw_values[code] = val

            if not raw_values:
                continue

            # Percentile rank among candidates
            vals = sorted(raw_values.values())
            n = len(vals)
            for code, v in raw_values.items():
                # rank: position in sorted list / total (0..1)
                rank_pos = vals.index(v) / max(n - 1, 1)
                # For "asc" direction: lower values get higher score (rank_pos stays)
                # For "desc" direction: higher values get higher score (invert)
                if direction == "desc":
                    rank_pos = 1.0 - rank_pos
                scores[code] = scores.get(code, 0.0) + rank_pos * weight

        # Sort by score descending (highest score = best candidate)
        return sorted(candidates, key=lambda c: scores.get(c[0], 0.0), reverse=True)

    def _get_factor_value(
        self,
        code: str,
        current_date: str,
        ftype: str,
        ffield: str,
        params: Optional[dict],
        prepared: Dict[str, pd.DataFrame],
        stock_date_idx: Dict[str, Dict[str, int]],
        basic_df: Optional[pd.DataFrame],
    ) -> Optional[float]:
        """Get a single factor value for a stock on a date."""
        if ftype == "kline":
            # Fields: volume, close, amount, etc.
            if current_date not in stock_date_idx.get(code, {}):
                return None
            idx = stock_date_idx[code][current_date]
            row = prepared[code].iloc[idx]
            val = row.get(ffield)
            return float(val) if pd.notna(val) else None

        elif ftype == "indicator":
            # Fields: RSI_14, MACD_hist_12_26_9, etc.
            if current_date not in stock_date_idx.get(code, {}):
                return None
            idx = stock_date_idx[code][current_date]
            row = prepared[code].iloc[idx]

            # Build column name from field + params
            col_name = self._build_indicator_col(ffield, params)
            val = row.get(col_name)
            return float(val) if pd.notna(val) else None

        elif ftype == "basic":
            # Fields: pe, pb, total_mv, circ_mv, turnover_rate
            if basic_df is None:
                return None
            if code not in basic_df.index:
                return None
            val = basic_df.loc[code].get(ffield)
            return float(val) if pd.notna(val) else None

        return None

    @staticmethod
    def _build_indicator_col(field_name: str, params: Optional[dict]) -> str:
        """Build indicator column name matching IndicatorCalculator output.

        Examples: RSI + {period: 14} → RSI_14
                  MACD_hist + {fast: 12, slow: 26, signal: 9} → MACD_hist_12_26_9
        """
        if not params:
            return field_name

        # Standard column naming from IndicatorCalculator
        param_suffix = "_".join(str(v) for v in params.values())
        return f"{field_name}_{param_suffix}"

    def _build_result(
        self,
        strategy_name: str,
        trades: List[Trade],
        equity_curve: List[dict],
        start_date: str,
        end_date: str,
        regime_map: Optional[Dict[str, str]] = None,
    ) -> PortfolioBacktestResult:
        """Compute all metrics from trades and equity curve."""
        total_trades = len(trades)

        if total_trades == 0:
            return PortfolioBacktestResult(
                strategy_name=strategy_name,
                start_date=start_date,
                end_date=end_date,
                initial_capital=self.initial_capital,
                max_positions=self.max_positions,
            )

        # Basic stats
        win_trades = sum(1 for t in trades if t.pnl_pct is not None and t.pnl_pct > 0)
        lose_trades = total_trades - win_trades
        win_rate = (win_trades / total_trades) * 100

        pnl_values = [t.pnl_pct for t in trades if t.pnl_pct is not None]
        avg_pnl_pct = sum(pnl_values) / len(pnl_values) if pnl_values else 0.0

        hold_days_list = [t.hold_days for t in trades]
        avg_hold_days = sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0.0

        # Portfolio-level return from equity curve
        final_equity = equity_curve[-1]["equity"] if equity_curve else self.initial_capital
        total_return_pct = (final_equity - self.initial_capital) / self.initial_capital * 100

        # Max drawdown from equity curve
        max_drawdown_pct = self._calc_max_drawdown(equity_curve)

        # Advanced metrics
        cagr_pct = self._calc_cagr(start_date, end_date, final_equity)
        sharpe_ratio = self._calc_sharpe(equity_curve)
        calmar_ratio = self._calc_calmar(cagr_pct, max_drawdown_pct)
        profit_loss_ratio = self._calc_profit_loss_ratio(trades)

        # Sell reason stats
        sell_reason_stats: Dict[str, int] = {}
        for t in trades:
            reason = t.sell_reason or "unknown"
            sell_reason_stats[reason] = sell_reason_stats.get(reason, 0) + 1

        # Regime stats (aggregate trades by market regime at buy time)
        regime_stats = self._calc_regime_stats(trades) if regime_map else {}
        index_return_pct = self._calc_index_return(regime_map) if regime_map else 0.0

        return PortfolioBacktestResult(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            max_positions=self.max_positions,
            total_trades=total_trades,
            win_trades=win_trades,
            lose_trades=lose_trades,
            win_rate=round(win_rate, 2),
            total_return_pct=round(total_return_pct, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            avg_hold_days=round(avg_hold_days, 1),
            avg_pnl_pct=round(avg_pnl_pct, 2),
            cagr_pct=round(cagr_pct, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            calmar_ratio=round(calmar_ratio, 2),
            profit_loss_ratio=round(profit_loss_ratio, 2),
            trades=trades,
            equity_curve=equity_curve,
            sell_reason_stats=sell_reason_stats,
            regime_stats=regime_stats,
            index_return_pct=round(index_return_pct, 2),
        )

    @staticmethod
    def _calc_regime_stats(trades: List[Trade]) -> dict:
        """Aggregate trade stats by market regime.

        Returns:
            {regime: {trades: N, wins: N, win_rate: %, avg_pnl: %, total_pnl: %}}
        """
        buckets: Dict[str, dict] = {}
        for t in trades:
            r = t.regime or "unknown"
            if r not in buckets:
                buckets[r] = {"trades": 0, "wins": 0, "pnl_sum": 0.0}
            buckets[r]["trades"] += 1
            if t.pnl_pct is not None:
                buckets[r]["pnl_sum"] += t.pnl_pct
                if t.pnl_pct > 0:
                    buckets[r]["wins"] += 1

        result = {}
        for regime, data in buckets.items():
            n = data["trades"]
            result[regime] = {
                "trades": n,
                "wins": data["wins"],
                "win_rate": round(data["wins"] / n * 100, 1) if n > 0 else 0.0,
                "avg_pnl": round(data["pnl_sum"] / n, 2) if n > 0 else 0.0,
                "total_pnl": round(data["pnl_sum"], 2),
            }
        return result

    @staticmethod
    def _calc_index_return(regime_map: Optional[Dict[str, str]]) -> float:
        """Placeholder — actual index return comes from regime_service.get_regime_summary()."""
        return 0.0

    @staticmethod
    def _calc_max_drawdown(equity_curve: List[dict]) -> float:
        """Max drawdown from daily equity curve."""
        if not equity_curve:
            return 0.0

        peak = equity_curve[0]["equity"]
        max_dd = 0.0

        for point in equity_curve:
            eq = point["equity"]
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak * 100
                if dd > max_dd:
                    max_dd = dd

        return max_dd

    def _calc_cagr(self, start_date: str, end_date: str, final_equity: float) -> float:
        """Compound annual growth rate."""
        try:
            start = pd.Timestamp(start_date)
            end = pd.Timestamp(end_date)
            days = (end - start).days
            if days <= 0 or self.initial_capital <= 0:
                return 0.0
            return (pow(final_equity / self.initial_capital, 365.0 / days) - 1) * 100
        except Exception:
            return 0.0

    def _calc_sharpe(self, equity_curve: List[dict], risk_free_rate: float = 0.03) -> float:
        """Annualized Sharpe ratio from daily equity curve."""
        if len(equity_curve) < 2:
            return 0.0

        equities = [p["equity"] for p in equity_curve]
        # Daily returns
        returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                returns.append(equities[i] / equities[i - 1] - 1)

        if not returns:
            return 0.0

        daily_rf = risk_free_rate / 252
        excess = [r - daily_rf for r in returns]
        mean_excess = np.mean(excess)
        std_excess = np.std(excess, ddof=1)

        if std_excess == 0:
            return 0.0

        return float(mean_excess / std_excess * math.sqrt(252))

    @staticmethod
    def _calc_calmar(cagr_pct: float, max_drawdown_pct: float) -> float:
        """Calmar ratio = CAGR / |max_drawdown|."""
        if max_drawdown_pct == 0:
            return 0.0
        return cagr_pct / abs(max_drawdown_pct)

    @staticmethod
    def _calc_profit_loss_ratio(trades: List[Trade]) -> float:
        """Average win PnL / average loss PnL."""
        wins = [t.pnl_pct for t in trades if t.pnl_pct is not None and t.pnl_pct > 0]
        losses = [t.pnl_pct for t in trades if t.pnl_pct is not None and t.pnl_pct < 0]

        if not wins or not losses:
            return 0.0

        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))

        if avg_loss == 0:
            return 0.0

        return avg_win / avg_loss
