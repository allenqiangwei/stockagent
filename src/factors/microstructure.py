"""Price microstructure factors: liquidity, impact, information asymmetry."""

import numpy as np
import pandas as pd

from .registry import register_factor


@register_factor(
    name="ILLIQ",
    label="非流动性",
    sub_fields=[("ILLIQ", "非流动性")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"ILLIQ": (0, 1)},
    category="microstructure",
)
def compute_illiq(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    abs_ret = df["close"].pct_change().abs()
    amount = df["volume"] * df["close"]  # proxy for turnover amount
    illiq = abs_ret / (amount + 1)
    result = illiq.rolling(period).mean().fillna(0)
    return pd.DataFrame({f"ILLIQ{s}": result}, index=df.index)


@register_factor(
    name="KYLE_LAMBDA",
    label="价格冲击系数",
    sub_fields=[("KYLE_LAMBDA", "价格冲击系数")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"KYLE_LAMBDA": (0, 0.001)},
    category="microstructure",
)
def compute_kyle_lambda(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    abs_ret = df["close"].pct_change().abs()
    sign = np.where(df["close"] > df["open"], 1, -1)
    signed_vol = sign * df["volume"]

    def _slope(y):
        """Regress abs_ret on signed_vol, return slope."""
        n = len(y)
        half = n // 2
        x = y[:half]  # signed_vol
        yy = y[half:]  # abs_ret
        mask = ~(np.isnan(x) | np.isnan(yy))
        if mask.sum() < 3:
            return 0.0
        x_m, yy_m = x[mask], yy[mask]
        x_mean = np.mean(x_m)
        x_var = np.sum((x_m - x_mean) ** 2)
        if x_var < 1e-15:
            return 0.0
        return np.sum((x_m - x_mean) * (yy_m - np.mean(yy_m))) / x_var

    # Rolling regression using combined series
    sv = pd.Series(signed_vol, index=df.index).astype(float)
    combined = pd.concat([sv, abs_ret], axis=0).reset_index(drop=True)

    # Simpler approach: use rolling cov / var
    cov_xy = abs_ret.rolling(period).cov(sv)
    var_x = sv.rolling(period).var()
    result = (cov_xy / (var_x + 1e-15)).clip(lower=0).fillna(0)
    return pd.DataFrame({f"KYLE_LAMBDA{s}": result}, index=df.index)


@register_factor(
    name="PIN_PROXY",
    label="知情交易概率",
    sub_fields=[("PIN_PROXY", "知情交易概率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"PIN_PROXY": (0, 1)},
    category="microstructure",
)
def compute_pin_proxy(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    is_buy = df["close"] > df["open"]
    buy_vol = df["volume"].where(is_buy, 0)
    sell_vol = df["volume"].where(~is_buy, 0)
    buy_sum = buy_vol.rolling(period).sum()
    sell_sum = sell_vol.rolling(period).sum()
    result = ((buy_sum - sell_sum).abs() / (buy_sum + sell_sum + 1e-8)).fillna(0)
    return pd.DataFrame({f"PIN_PROXY{s}": result}, index=df.index)


@register_factor(
    name="SPREAD_EST",
    label="价差估计",
    sub_fields=[("SPREAD_EST", "价差估计")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"SPREAD_EST": (0, 0.1)},
    category="microstructure",
)
def compute_spread_est(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Corwin-Schultz spread estimator from high/low prices."""
    period = params.get("period", 20)
    s = f"_{period}"
    log_hl = np.log(df["high"] / df["low"].replace(0, np.nan))
    log_hl_sq = log_hl ** 2

    # Two-day high-low
    high_2d = pd.concat([df["high"], df["high"].shift(1)], axis=1).max(axis=1)
    low_2d = pd.concat([df["low"], df["low"].shift(1)], axis=1).min(axis=1)
    log_hl2 = np.log(high_2d / low_2d.replace(0, np.nan))
    log_hl2_sq = log_hl2 ** 2

    beta = log_hl_sq + log_hl_sq.shift(1)
    gamma = log_hl2_sq

    k2 = 8.0 / np.pi
    sqrt2 = np.sqrt(2)

    beta_roll = beta.rolling(period).mean()
    gamma_roll = gamma.rolling(period).mean()

    alpha = (np.sqrt(2 * beta_roll) - np.sqrt(beta_roll)) / (3 - 2 * sqrt2) \
            - np.sqrt(gamma_roll / (3 - 2 * sqrt2))
    alpha = alpha.clip(lower=0)

    spread = (2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))).fillna(0).clip(lower=0)
    return pd.DataFrame({f"SPREAD_EST{s}": spread}, index=df.index)


@register_factor(
    name="AMIHUD_RATIO",
    label="Amihud比率",
    sub_fields=[("AMIHUD_RATIO", "Amihud比率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"AMIHUD_RATIO": (0, 0.5)},
    category="microstructure",
)
def compute_amihud_ratio(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    abs_ret = df["close"].pct_change().abs()
    log_amount = np.log(df["volume"] * df["close"] + 1)
    ratio = abs_ret / (log_amount + 1e-8)
    result = ratio.rolling(period).mean().fillna(0)
    return pd.DataFrame({f"AMIHUD_RATIO{s}": result}, index=df.index)


@register_factor(
    name="VOLUME_CLOCK",
    label="成交量时间集中度",
    sub_fields=[("VOLUME_CLOCK", "成交量时间集中度")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"VOLUME_CLOCK": (0, 1)},
    category="microstructure",
)
def compute_volume_clock(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    half = period // 2

    def _concentration(x):
        """Fraction of total volume in first half of window."""
        total = np.sum(x)
        if total < 1e-8:
            return 0.5
        return np.sum(x[:half]) / total

    result = df["volume"].rolling(period).apply(_concentration, raw=True).fillna(0.5)
    return pd.DataFrame({f"VOLUME_CLOCK{s}": result}, index=df.index)
