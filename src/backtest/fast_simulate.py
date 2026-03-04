"""Numba JIT-compiled trade simulation for backtest acceleration.

Compiles the inner trade loop (buy/sell/position management) to machine code.
Uses pure numpy arrays — no Python dicts or objects inside the hot loop.
"""

import numpy as np

try:
    import numba
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False


# ── Sell reason codes ──
SELL_STOP_LOSS = 0
SELL_TAKE_PROFIT = 1
SELL_MAX_HOLD = 2
SELL_STRATEGY_EXIT = 3
SELL_END_OF_BACKTEST = 4

# ── Trade output column indices ──
# trades_out shape: (max_trades, 9)
# [stock_idx, buy_day_idx, sell_day_idx, buy_price, sell_price,
#  pnl_pct, hold_days, sell_reason, shares]
T_STOCK = 0
T_BUY_DAY = 1
T_SELL_DAY = 2
T_BUY_PRICE = 3
T_SELL_PRICE = 4
T_PNL_PCT = 5
T_HOLD_DAYS = 6
T_SELL_REASON = 7
T_SHARES = 8

# ── Position array column indices ──
# positions shape: (max_positions, 5)
# [stock_idx, buy_price, buy_day_idx, shares, hold_days]
P_STOCK = 0
P_BUY_PRICE = 1
P_BUY_DAY = 2
P_SHARES = 3
P_HOLD_DAYS = 4


def _define_simulate_exits():
    """Create the numba-jitted simulate_exits function.

    Wrapped in a factory so the module can import even without numba.
    """
    if not HAS_NUMBA:
        return None

    @numba.njit(cache=True)
    def simulate_exits(
        buy_signals,       # (n_stocks, n_days) bool
        sell_signals,      # (n_stocks, n_days) bool — strategy exit signals
        close_prices,      # (n_stocks, n_days) float64
        high_prices,       # (n_stocks, n_days) float64
        low_prices,        # (n_stocks, n_days) float64
        stock_valid,       # (n_stocks, n_days) bool — True if stock has data on that day
        stop_loss_pct,     # float, e.g. -8.0 (NEGATIVE)
        take_profit_pct,   # float, e.g. 1.0
        max_hold_days,     # int, e.g. 18 (0 = disabled)
        max_positions,     # int, e.g. 10
        initial_capital,   # float, e.g. 100000
        max_position_pct,  # float, e.g. 30.0
    ):
        """Numba-compiled trade simulation.

        Returns:
            trades_out: (max_trades, 9) float64 — completed trades
            equity_curve: (n_days,) float64 — daily portfolio value
            n_trades: int — number of completed trades
        """
        n_stocks, n_days = buy_signals.shape
        max_trades = n_days * 2  # generous pre-allocation

        # Pre-allocate outputs
        trades_out = np.zeros((max_trades, 9), dtype=np.float64)
        equity_curve = np.zeros(n_days, dtype=np.float64)
        n_trades = 0

        # Position tracking: (max_positions, 5) — [stock_idx, buy_price, buy_day, shares, hold_days]
        positions = np.zeros((max_positions, 5), dtype=np.float64)
        n_active = 0
        # Track which stocks are held to prevent double-buying
        held_stocks = np.zeros(n_stocks, dtype=numba.boolean)

        cash = initial_capital

        for day in range(1, n_days):  # skip day 0

            # ── Phase 1: Check sells for existing positions ──
            sells_to_execute = np.zeros(max_positions, dtype=numba.boolean)
            sell_reasons = np.zeros(max_positions, dtype=np.int64)
            sell_prices = np.zeros(max_positions, dtype=np.float64)

            for p in range(n_active):
                si = int(positions[p, P_STOCK])
                if not stock_valid[si, day]:
                    positions[p, P_HOLD_DAYS] += 1
                    continue

                positions[p, P_HOLD_DAYS] += 1
                bp = positions[p, P_BUY_PRICE]
                c = close_prices[si, day]
                lo = low_prices[si, day]
                hi = high_prices[si, day]
                reason = -1
                sp = c  # default sell price

                # 1) Stop loss
                if stop_loss_pct != 0.0:
                    sl_threshold = bp * (1.0 + stop_loss_pct / 100.0)
                    if lo <= sl_threshold:
                        reason = SELL_STOP_LOSS
                        sp = min(sl_threshold, c)

                # 2) Take profit
                if reason < 0 and take_profit_pct != 0.0:
                    tp_threshold = bp * (1.0 + take_profit_pct / 100.0)
                    if hi >= tp_threshold:
                        reason = SELL_TAKE_PROFIT
                        sp = max(tp_threshold, c)

                # 3) Max hold days
                if reason < 0 and max_hold_days > 0:
                    if int(positions[p, P_HOLD_DAYS]) >= max_hold_days:
                        reason = SELL_MAX_HOLD
                        sp = c

                # 4) Strategy exit signal
                if reason < 0 and sell_signals[si, day]:
                    reason = SELL_STRATEGY_EXIT
                    sp = c

                if reason >= 0:
                    sells_to_execute[p] = True
                    sell_reasons[p] = reason
                    sell_prices[p] = sp

            # Execute sells in reverse order to avoid index shifting issues
            for p in range(n_active - 1, -1, -1):
                if not sells_to_execute[p]:
                    continue
                si = int(positions[p, P_STOCK])
                bp = positions[p, P_BUY_PRICE]
                sp = sell_prices[p]
                shares = positions[p, P_SHARES]
                hd = int(positions[p, P_HOLD_DAYS])

                pnl_pct = (sp - bp) / bp * 100.0
                cash += shares * sp

                if n_trades < max_trades:
                    trades_out[n_trades, T_STOCK] = si
                    trades_out[n_trades, T_BUY_DAY] = positions[p, P_BUY_DAY]
                    trades_out[n_trades, T_SELL_DAY] = day
                    trades_out[n_trades, T_BUY_PRICE] = bp
                    trades_out[n_trades, T_SELL_PRICE] = sp
                    trades_out[n_trades, T_PNL_PCT] = pnl_pct
                    trades_out[n_trades, T_HOLD_DAYS] = hd
                    trades_out[n_trades, T_SELL_REASON] = sell_reasons[p]
                    trades_out[n_trades, T_SHARES] = shares
                    n_trades += 1

                held_stocks[si] = False

                # Remove position: swap with last active
                n_active -= 1
                if p < n_active:
                    positions[p, :] = positions[n_active, :]
                    sells_to_execute[p] = sells_to_execute[n_active]
                    sell_reasons[p] = sell_reasons[n_active]
                    sell_prices[p] = sell_prices[n_active]

            # ── Phase 2: Scan for buys ──
            open_slots = max_positions - n_active
            if open_slots > 0:
                # Calculate current portfolio equity
                portfolio_equity = cash
                for p in range(n_active):
                    si = int(positions[p, P_STOCK])
                    if stock_valid[si, day]:
                        portfolio_equity += positions[p, P_SHARES] * close_prices[si, day]
                    else:
                        portfolio_equity += positions[p, P_SHARES] * positions[p, P_BUY_PRICE]

                # Collect buy candidates
                n_candidates = 0
                candidate_indices = np.zeros(n_stocks, dtype=np.int64)
                candidate_prices = np.zeros(n_stocks, dtype=np.float64)

                for si in range(n_stocks):
                    if held_stocks[si]:
                        continue
                    if not stock_valid[si, day]:
                        continue
                    if buy_signals[si, day]:
                        c = close_prices[si, day]
                        if c > 0:
                            candidate_indices[n_candidates] = si
                            candidate_prices[n_candidates] = c
                            n_candidates += 1

                # Buy top candidates (up to open_slots)
                n_to_buy = min(n_candidates, open_slots)
                for i in range(n_to_buy):
                    si = candidate_indices[i]
                    c = candidate_prices[i]

                    target_value = portfolio_equity / max_positions
                    max_value = portfolio_equity * max_position_pct / 100.0
                    position_value = min(target_value, max_value, cash)

                    if position_value < c:
                        continue  # Not enough cash for even 1 share

                    shares = np.floor(position_value / c / 100.0) * 100.0
                    if shares < 100:
                        continue

                    cost = shares * c
                    if cost > cash:
                        continue

                    cash -= cost
                    positions[n_active, P_STOCK] = si
                    positions[n_active, P_BUY_PRICE] = c
                    positions[n_active, P_BUY_DAY] = day
                    positions[n_active, P_SHARES] = shares
                    positions[n_active, P_HOLD_DAYS] = 0
                    n_active += 1
                    held_stocks[si] = True

            # ── Phase 3: Record equity ──
            equity = cash
            for p in range(n_active):
                si = int(positions[p, P_STOCK])
                if stock_valid[si, day]:
                    equity += positions[p, P_SHARES] * close_prices[si, day]
                else:
                    equity += positions[p, P_SHARES] * positions[p, P_BUY_PRICE]
            equity_curve[day] = equity

        # ── End-of-backtest: force-sell remaining positions ──
        last_day = n_days - 1
        for p in range(n_active):
            si = int(positions[p, P_STOCK])
            if stock_valid[si, last_day]:
                sp = close_prices[si, last_day]
            else:
                sp = positions[p, P_BUY_PRICE]
            bp = positions[p, P_BUY_PRICE]
            pnl_pct = (sp - bp) / bp * 100.0
            cash += positions[p, P_SHARES] * sp

            if n_trades < max_trades:
                trades_out[n_trades, T_STOCK] = si
                trades_out[n_trades, T_BUY_DAY] = positions[p, P_BUY_DAY]
                trades_out[n_trades, T_SELL_DAY] = last_day
                trades_out[n_trades, T_BUY_PRICE] = bp
                trades_out[n_trades, T_SELL_PRICE] = sp
                trades_out[n_trades, T_PNL_PCT] = pnl_pct
                trades_out[n_trades, T_HOLD_DAYS] = int(positions[p, P_HOLD_DAYS])
                trades_out[n_trades, T_SELL_REASON] = SELL_END_OF_BACKTEST
                trades_out[n_trades, T_SHARES] = positions[p, P_SHARES]
                n_trades += 1

        equity_curve[0] = initial_capital

        return trades_out[:n_trades], equity_curve, n_trades

    return simulate_exits


# Module-level JIT function (created at import time)
_jit_simulate = _define_simulate_exits()


def prepare_batch_arrays(
    prepared: dict,
    sorted_dates: list,
    stock_date_idx: dict,
    buy_signal_map: dict,
    sell_signal_map: dict,
):
    """Convert Python dicts to numpy arrays for Numba consumption.

    Args:
        prepared: {stock_code: DataFrame} with OHLCV data
        sorted_dates: sorted list of all trading dates
        stock_date_idx: {stock_code: {date: row_idx}}
        buy_signal_map: {stock_code: np.ndarray[bool]} per-stock buy signals
        sell_signal_map: {stock_code: np.ndarray[bool]} per-stock sell signals

    Returns:
        dict with numpy arrays ready for simulate_exits()
    """
    stock_codes = list(prepared.keys())
    n_stocks = len(stock_codes)
    n_days = len(sorted_dates)

    close_prices = np.zeros((n_stocks, n_days), dtype=np.float64)
    high_prices = np.zeros((n_stocks, n_days), dtype=np.float64)
    low_prices = np.zeros((n_stocks, n_days), dtype=np.float64)
    stock_valid = np.zeros((n_stocks, n_days), dtype=bool)
    buy_signals = np.zeros((n_stocks, n_days), dtype=bool)
    sell_signals = np.zeros((n_stocks, n_days), dtype=bool)

    date_to_global_idx = {d: i for i, d in enumerate(sorted_dates)}

    for si, code in enumerate(stock_codes):
        df = prepared[code]
        date_idx = stock_date_idx.get(code, {})
        buy_vec = buy_signal_map.get(code)
        sell_vec = sell_signal_map.get(code)

        for date_str, local_row in date_idx.items():
            global_day = date_to_global_idx.get(date_str)
            if global_day is None:
                continue
            stock_valid[si, global_day] = True
            row = df.iloc[local_row]
            close_prices[si, global_day] = float(row["close"])
            high_prices[si, global_day] = float(row.get("high", row["close"]))
            low_prices[si, global_day] = float(row.get("low", row["close"]))

            if buy_vec is not None and local_row < len(buy_vec):
                buy_signals[si, global_day] = buy_vec[local_row]
            if sell_vec is not None and local_row < len(sell_vec):
                sell_signals[si, global_day] = sell_vec[local_row]

    return {
        "stock_codes": stock_codes,
        "close_prices": close_prices,
        "high_prices": high_prices,
        "low_prices": low_prices,
        "stock_valid": stock_valid,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "sorted_dates": sorted_dates,
    }


def run_fast_simulation(
    batch_arrays: dict,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_hold_days: int,
    max_positions: int = 10,
    initial_capital: float = 100000.0,
    max_position_pct: float = 30.0,
):
    """Run Numba JIT trade simulation and convert results back to Python objects.

    Args:
        batch_arrays: output from prepare_batch_arrays()
        stop_loss_pct: stop loss percentage (NEGATIVE, e.g. -8.0)
        take_profit_pct: take profit percentage (e.g. 1.0)
        max_hold_days: max holding days (0 = disabled)

    Returns:
        dict with trades list, equity_curve, and summary stats
    """
    if _jit_simulate is None:
        raise RuntimeError("Numba is not available. Install numba>=0.59.0")

    trades_out, equity_curve, n_trades = _jit_simulate(
        batch_arrays["buy_signals"],
        batch_arrays["sell_signals"],
        batch_arrays["close_prices"],
        batch_arrays["high_prices"],
        batch_arrays["low_prices"],
        batch_arrays["stock_valid"],
        float(stop_loss_pct),
        float(take_profit_pct),
        int(max_hold_days),
        int(max_positions),
        float(initial_capital),
        float(max_position_pct),
    )

    sell_reason_names = {
        SELL_STOP_LOSS: "stop_loss",
        SELL_TAKE_PROFIT: "take_profit",
        SELL_MAX_HOLD: "max_hold",
        SELL_STRATEGY_EXIT: "strategy_exit",
        SELL_END_OF_BACKTEST: "end_of_backtest",
    }

    stock_codes = batch_arrays["stock_codes"]
    sorted_dates = batch_arrays["sorted_dates"]

    trades = []
    for i in range(n_trades):
        row = trades_out[i]
        si = int(row[T_STOCK])
        buy_day = int(row[T_BUY_DAY])
        sell_day = int(row[T_SELL_DAY])
        trades.append({
            "stock_code": stock_codes[si],
            "buy_date": sorted_dates[buy_day] if buy_day < len(sorted_dates) else "",
            "sell_date": sorted_dates[sell_day] if sell_day < len(sorted_dates) else "",
            "buy_price": round(row[T_BUY_PRICE], 4),
            "sell_price": round(row[T_SELL_PRICE], 4),
            "pnl_pct": round(row[T_PNL_PCT], 4),
            "hold_days": int(row[T_HOLD_DAYS]),
            "sell_reason": sell_reason_names.get(int(row[T_SELL_REASON]), "unknown"),
            "shares": int(row[T_SHARES]),
        })

    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "n_trades": n_trades,
    }


def warmup():
    """Pre-compile Numba function with dummy data to avoid first-call latency."""
    if _jit_simulate is None:
        return
    n_stocks, n_days = 2, 10
    _jit_simulate(
        np.zeros((n_stocks, n_days), dtype=bool),
        np.zeros((n_stocks, n_days), dtype=bool),
        np.ones((n_stocks, n_days), dtype=np.float64) * 10.0,
        np.ones((n_stocks, n_days), dtype=np.float64) * 11.0,
        np.ones((n_stocks, n_days), dtype=np.float64) * 9.0,
        np.ones((n_stocks, n_days), dtype=bool),
        -8.0, 1.0, 18, 5, 100000.0, 30.0,
    )
