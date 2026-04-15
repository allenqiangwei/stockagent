"""Advanced trend/momentum and pattern recognition factors."""

import numpy as np
import pandas as pd

from .registry import register_factor


# ── Trend / Momentum ───────────────────────────────────────


@register_factor(
    name="TREND_STRENGTH",
    label="趋势强度",
    sub_fields=[("TREND_STRENGTH", "趋势强度")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"TREND_STRENGTH": (0, 10)},
    category="trend_advanced",
)
def compute_trend_strength(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    ma = df["close"].rolling(period).mean()
    # ATR
    prev_c = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_c).abs(),
        (df["low"] - prev_c).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    result = ((df["close"] - ma).abs() / (atr + 1e-8)).fillna(0)
    return pd.DataFrame({f"TREND_STRENGTH{s}": result}, index=df.index)


@register_factor(
    name="TREND_QUALITY",
    label="趋势质量",
    sub_fields=[("TREND_QUALITY", "趋势质量")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"TREND_QUALITY": (-1, 1)},
    category="trend_advanced",
)
def compute_trend_quality(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    net_move = df["close"] - df["close"].shift(period)
    daily_abs = df["close"].diff().abs()
    path_length = daily_abs.rolling(period).sum()
    result = (net_move / (path_length + 1e-8)).fillna(0)
    return pd.DataFrame({f"TREND_QUALITY{s}": result}, index=df.index)


@register_factor(
    name="EFFICIENCY_RATIO",
    label="效率比率",
    sub_fields=[("EFFICIENCY_RATIO", "效率比率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"EFFICIENCY_RATIO": (0, 1)},
    category="trend_advanced",
)
def compute_efficiency_ratio(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    direction = (df["close"] - df["close"].shift(period)).abs()
    volatility = df["close"].diff().abs().rolling(period).sum()
    result = (direction / (volatility + 1e-8)).fillna(0)
    return pd.DataFrame({f"EFFICIENCY_RATIO{s}": result}, index=df.index)


@register_factor(
    name="ACCELERATION",
    label="动量加速度",
    sub_fields=[("ACCELERATION", "动量加速度")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"ACCELERATION": (-50, 50)},
    category="trend_advanced",
)
def compute_acceleration(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    short = max(period // 4, 1)
    mom_short = df["close"].pct_change(short) * 100
    mom_long = df["close"].pct_change(period) * 100
    result = (mom_short - mom_long).fillna(0)
    return pd.DataFrame({f"ACCELERATION{s}": result}, index=df.index)


@register_factor(
    name="HURST",
    label="Hurst指数",
    sub_fields=[("HURST", "Hurst指数")],
    params={"period": {"label": "周期", "default": 100, "type": "int"}},
    field_ranges={"HURST": (0, 1)},
    category="trend_advanced",
)
def compute_hurst(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 100)
    s = f"_{period}"
    returns = df["close"].pct_change()

    def _rs_hurst(x):
        """Simplified R/S Hurst exponent."""
        x = x[~np.isnan(x)]
        n = len(x)
        if n < 20:
            return 0.5
        max_k = min(n // 2, 50)
        if max_k < 4:
            return 0.5
        # Use a few sub-period lengths
        sizes = []
        rs_values = []
        for k in [max_k // 4, max_k // 2, max_k]:
            if k < 2:
                continue
            num_chunks = n // k
            if num_chunks < 1:
                continue
            rs_list = []
            for i in range(num_chunks):
                chunk = x[i * k:(i + 1) * k]
                mean_c = np.mean(chunk)
                deviate = np.cumsum(chunk - mean_c)
                r = np.max(deviate) - np.min(deviate)
                s_val = np.std(chunk, ddof=1)
                if s_val > 1e-10:
                    rs_list.append(r / s_val)
            if rs_list:
                sizes.append(np.log(k))
                rs_values.append(np.log(np.mean(rs_list)))
        if len(sizes) < 2:
            return 0.5
        # Linear regression slope = Hurst exponent
        slope = np.polyfit(sizes, rs_values, 1)[0]
        return np.clip(slope, 0, 1)

    result = returns.rolling(period).apply(_rs_hurst, raw=True).fillna(0.5)
    return pd.DataFrame({f"HURST{s}": result}, index=df.index)


@register_factor(
    name="CONSECUTIVE_STRENGTH",
    label="连续强度",
    sub_fields=[("CONSECUTIVE_STRENGTH", "连续强度")],
    params={},
    field_ranges={"CONSECUTIVE_STRENGTH": (-50, 50)},
    category="trend_advanced",
)
def compute_consecutive_strength(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    returns = df["close"].pct_change()
    is_up = returns > 0

    # Build streak: consecutive days * cumulative return
    streak_days = pd.Series(0.0, index=df.index)
    cum_ret = pd.Series(0.0, index=df.index)

    prev_up = None
    count = 0
    acc = 0.0
    for i in range(len(df)):
        if pd.isna(returns.iloc[i]):
            streak_days.iloc[i] = 0
            cum_ret.iloc[i] = 0
            prev_up = None
            count = 0
            acc = 0.0
            continue
        cur_up = bool(is_up.iloc[i])
        r = returns.iloc[i]
        if prev_up is None or cur_up != prev_up:
            count = 1
            acc = r * 100
        else:
            count += 1
            acc += r * 100
        streak_days.iloc[i] = count if cur_up else -count
        cum_ret.iloc[i] = acc
        prev_up = cur_up

    result = streak_days * cum_ret.abs()
    # Positive for up-streaks, negative for down-streaks
    result = np.where(streak_days >= 0, streak_days.abs() * cum_ret, streak_days.abs() * cum_ret)
    return pd.DataFrame({"CONSECUTIVE_STRENGTH": pd.Series(result, index=df.index).fillna(0)},
                        index=df.index)


@register_factor(
    name="TRUE_RANGE_PCT",
    label="真实波幅%",
    sub_fields=[("TRUE_RANGE_PCT", "真实波幅%")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"TRUE_RANGE_PCT": (0, 20)},
    category="trend_advanced",
)
def compute_true_range_pct(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    prev_c = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_c).abs(),
        (df["low"] - prev_c).abs(),
    ], axis=1).max(axis=1)
    tr_pct = tr / (df["close"] + 1e-8) * 100
    result = tr_pct.rolling(period).mean().fillna(0)
    return pd.DataFrame({f"TRUE_RANGE_PCT{s}": result}, index=df.index)


# ── Pattern Recognition ────────────────────────────────────


@register_factor(
    name="GAP_SIZE",
    label="跳空幅度%",
    sub_fields=[("GAP_SIZE", "跳空幅度%")],
    params={},
    field_ranges={"GAP_SIZE": (-10, 10)},
    category="pattern",
)
def compute_gap_size(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    prev_c = df["close"].shift(1)
    result = ((df["open"] - prev_c) / (prev_c + 1e-8) * 100).fillna(0)
    return pd.DataFrame({"GAP_SIZE": result}, index=df.index)


@register_factor(
    name="RANGE_EXPANSION",
    label="波幅扩张",
    sub_fields=[("RANGE_EXPANSION", "波幅扩张")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"RANGE_EXPANSION": (0, 5)},
    category="pattern",
)
def compute_range_expansion(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    cur_range = df["high"] - df["low"]
    prev_range = cur_range.shift(1)
    expansion = cur_range / (prev_range + 1e-8)
    result = expansion.rolling(period).mean().fillna(0)
    return pd.DataFrame({f"RANGE_EXPANSION{s}": result}, index=df.index)


@register_factor(
    name="SPREAD_PROXY",
    label="价差代理%",
    sub_fields=[("SPREAD_PROXY", "价差代理%")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"SPREAD_PROXY": (0, 20)},
    category="pattern",
)
def compute_spread_proxy(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    spread = 2 * (df["high"] - df["low"]) / (df["high"] + df["low"] + 1e-8) * 100
    result = spread.rolling(period).mean().fillna(0)
    return pd.DataFrame({f"SPREAD_PROXY{s}": result}, index=df.index)


@register_factor(
    name="N_DAY_BREAKOUT",
    label="N日突破%",
    sub_fields=[("N_DAY_BREAKOUT", "N日突破%")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"N_DAY_BREAKOUT": (-30, 10)},
    category="pattern",
)
def compute_n_day_breakout(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    rolling_high = df["high"].rolling(period).max()
    result = ((df["close"] - rolling_high) / (df["close"] + 1e-8) * 100).fillna(0)
    return pd.DataFrame({f"N_DAY_BREAKOUT{s}": result}, index=df.index)


@register_factor(
    name="PRICE_CHANNEL_POS",
    label="价格通道位置",
    sub_fields=[("PRICE_CHANNEL_POS", "价格通道位置")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"PRICE_CHANNEL_POS": (0, 1)},
    category="pattern",
)
def compute_price_channel_pos(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    rolling_high = df["high"].rolling(period).max()
    rolling_low = df["low"].rolling(period).min()
    result = ((df["close"] - rolling_low) / (rolling_high - rolling_low + 1e-8)).fillna(0)
    return pd.DataFrame({f"PRICE_CHANNEL_POS{s}": result}, index=df.index)
