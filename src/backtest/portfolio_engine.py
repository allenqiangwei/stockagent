"""Portfolio backtest engine — single-account simulation with position limits.

Replaces the batch backtest for multi-stock strategies. One capital pool,
limited concurrent positions, time-driven execution, multi-factor ranking
when buy signals exceed available slots.
"""

import math
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

import numpy as np
import pandas as pd

from src.signals.rule_engine import evaluate_conditions, collect_indicator_params
from src.indicators.indicator_calculator import IndicatorCalculator, IndicatorConfig
from src.backtest.engine import Trade

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
    ):
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.position_sizing = position_sizing
        self.max_position_pct = max_position_pct  # max single stock weight %

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
        config = IndicatorConfig.from_collected_params(collected_params)
        calculator = IndicatorCalculator(config)

        # stock_code → full DataFrame (OHLCV + indicators), date-indexed
        prepared: Dict[str, pd.DataFrame] = {}
        total_stocks = len(stock_data)

        for idx, (code, df) in enumerate(stock_data.items(), 1):
            if progress_callback:
                progress_callback(idx, total_stocks, f"计算指标: {code}")

            if df is None or df.empty or len(df) < 2:
                continue

            indicators = calculator.calculate_all(df)
            df_full = pd.concat(
                [df.reset_index(drop=True), indicators.reset_index(drop=True)],
                axis=1,
            )
            if "date" in df_full.columns:
                df_full["date"] = pd.to_datetime(df_full["date"]).dt.strftime("%Y-%m-%d")
            # Debug: log extended indicator columns for first stock
            if idx == 1 and config.extended:
                ext_cols = [c for c in df_full.columns if any(
                    c.startswith(g.upper()) for g in config.extended
                )]
                logger.info(
                    "Portfolio debug: stock=%s, extended_config=%s, ext_cols=%s, total_cols=%d",
                    code, config.extended, ext_cols, len(df_full.columns),
                )
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

        # ── Phase 3: Day-by-day simulation ──
        cash = self.initial_capital
        positions: Dict[str, Position] = {}  # stock_code → Position
        trades: List[Trade] = []
        equity_curve: List[dict] = []
        held_codes: set[str] = set()
        # Signal explosion detection: track candidate counts in early days
        _early_candidate_counts: List[int] = []
        _recent_candidate_counts: List[int] = []  # rolling window for periodic checks
        _EXPLOSION_CHECK_DAYS = 10
        _EXPLOSION_THRESHOLD = 500  # avg candidates/day (early check)
        _PERIODIC_CHECK_INTERVAL = 50  # re-check every N days
        _PERIODIC_THRESHOLD = 300  # avg candidates/day (periodic check)

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

            # ── 3a: Check sells for existing positions ──
            codes_to_sell: List[tuple[str, str]] = []  # (code, reason)

            for code, pos in list(positions.items()):
                if code not in stock_date_idx or current_date not in stock_date_idx[code]:
                    # No data today (halted / missing) — still count the day
                    pos.hold_days += 1
                    continue

                row_idx = stock_date_idx[code][current_date]
                df_stock = prepared[code]
                row = df_stock.iloc[row_idx]
                close = float(row["close"])
                low = float(row.get("low", close))
                high = float(row.get("high", close))
                pos.hold_days += 1

                sell_reason = None
                sell_price_override = None  # use threshold price for SL/TP

                # 1) Stop loss — use intraday low
                if stop_loss_pct is not None:
                    loss_threshold = pos.buy_price * (1 + stop_loss_pct / 100)
                    if low <= loss_threshold:
                        sell_reason = "stop_loss"
                        # Sell at threshold price (simulating stop order)
                        sell_price_override = min(loss_threshold, close)

                # 2) Take profit — use intraday high
                if sell_reason is None and take_profit_pct is not None:
                    profit_threshold = pos.buy_price * (1 + take_profit_pct / 100)
                    if high >= profit_threshold:
                        sell_reason = "take_profit"
                        # Sell at threshold price (simulating limit order)
                        sell_price_override = max(profit_threshold, close)

                # 3) Max hold days
                if sell_reason is None and max_hold_days is not None:
                    if pos.hold_days >= max_hold_days:
                        sell_reason = "max_hold"

                # 4) Strategy sell conditions
                if sell_reason is None:
                    df_slice = df_stock.iloc[: row_idx + 1]
                    if is_combo and member_strategies:
                        # Combo sell: evaluate each member's sell conditions (short-circuit P18)
                        sell_votes = 0
                        for m in member_strategies:
                            m_sell = m.get("sell_conditions", [])
                            if m_sell:
                                triggered, _ = evaluate_conditions(m_sell, df_slice, mode="OR")
                                if triggered:
                                    sell_votes += 1
                            # Short-circuit: stop early when outcome is determined
                            if combo_sell_mode == "any" and sell_votes > 0:
                                break
                            if combo_sell_mode == "majority" and sell_votes > len(member_strategies) / 2:
                                break
                        if combo_sell_mode == "any" and sell_votes > 0:
                            sell_reason = "strategy_exit"
                        elif combo_sell_mode == "majority" and sell_votes > len(member_strategies) / 2:
                            sell_reason = "strategy_exit"
                    elif sell_conditions:
                        triggered, _ = evaluate_conditions(sell_conditions, df_slice, mode="OR")
                        if triggered:
                            sell_reason = "strategy_exit"

                if sell_reason:
                    codes_to_sell.append((code, sell_reason, sell_price_override))

            # Execute sells
            for code, reason, price_override in codes_to_sell:
                pos = positions.pop(code)
                held_codes.discard(code)
                row_idx = stock_date_idx[code][current_date]
                close = float(prepared[code].iloc[row_idx]["close"])
                exec_price = price_override if price_override is not None else close
                pnl_pct = (exec_price - pos.buy_price) / pos.buy_price * 100
                cash += pos.shares * exec_price

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

            # ── 3b: Scan for buy signals on non-held stocks ──
            open_slots = self.max_positions - len(positions)
            has_buy_logic = buy_conditions if not is_combo else member_strategies
            if open_slots > 0 and has_buy_logic:
                candidates: List[tuple[str, float]] = []  # (code, close_price)

                for code, df_stock in prepared.items():
                    if code in held_codes:
                        continue
                    if current_date not in stock_date_idx.get(code, {}):
                        continue

                    row_idx = stock_date_idx[code][current_date]
                    if row_idx < 1:
                        continue  # Need at least 1 prior day

                    df_slice = df_stock.iloc[: row_idx + 1]

                    if is_combo and member_strategies:
                        # Combo buy: vote across member strategies (short-circuit P18)
                        buy_votes = 0
                        weighted_score = 0.0
                        for m in member_strategies:
                            m_buy = m.get("buy_conditions", [])
                            if m_buy:
                                triggered, _ = evaluate_conditions(m_buy, df_slice, mode="AND")
                                if triggered:
                                    buy_votes += 1
                                    weighted_score += m.get("weight", 1.0)
                            # Short-circuit once threshold met
                            if combo_weight_mode == "equal" and buy_votes >= combo_vote_threshold:
                                break
                            if combo_weight_mode != "equal" and weighted_score >= combo_score_threshold:
                                break

                        if combo_weight_mode == "equal":
                            buy_signal = buy_votes >= combo_vote_threshold
                        else:  # score_weighted
                            buy_signal = weighted_score >= combo_score_threshold
                    else:
                        triggered, _ = evaluate_conditions(buy_conditions, df_slice, mode="AND")
                        buy_signal = triggered

                    if buy_signal:
                        close = float(df_stock.iloc[row_idx]["close"])
                        if close > 0:
                            candidates.append((code, close))

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

                # ── 3d: Buy top-N to fill slots ──
                portfolio_equity = cash + sum(
                    pos.shares * (
                        float(prepared[c].iloc[stock_date_idx[c][current_date]]["close"])
                        if current_date in stock_date_idx.get(c, {})
                        else pos.buy_price
                    )
                    for c, pos in positions.items()
                )

                for code, close in candidates[:open_slots]:
                    # Position size = equity / max_positions, capped by max_position_pct
                    target_value = portfolio_equity / self.max_positions
                    max_value = portfolio_equity * self.max_position_pct / 100
                    target_value = min(target_value, max_value)
                    shares = math.floor(target_value / close)
                    if shares <= 0:
                        continue
                    cost = shares * close
                    if cost > cash:
                        # Try with remaining cash
                        shares = math.floor(cash / close)
                        if shares <= 0:
                            continue
                        cost = shares * close

                    cash -= cost
                    positions[code] = Position(
                        stock_code=code,
                        buy_date=current_date,
                        buy_price=close,
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
                    # No data today (halted/suspended) — use buy price as fallback
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

            pnl_pct = (close - pos.buy_price) / pos.buy_price * 100
            cash += pos.shares * close

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
