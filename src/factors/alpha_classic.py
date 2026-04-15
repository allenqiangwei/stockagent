"""Classic alpha factors from WorldQuant Alpha101/191 and volume-price dynamics."""

import numpy as np
import pandas as pd

from .registry import register_factor


# ── Alpha101-inspired ───────────────────────────────────────


@register_factor(
    name="CORR_VOL_RET",
    label="量价开盘相关",
    sub_fields=[("CORR_VOL_RET", "量价开盘相关")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"CORR_VOL_RET": (-1, 1)},
    category="alpha_classic",
)
def compute_corr_vol_ret(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    result = df["open"].rolling(period).corr(df["volume"]).fillna(0)
    return pd.DataFrame({f"CORR_VOL_RET{s}": result}, index=df.index)


@register_factor(
    name="RANK_REVERSAL",
    label="排名反转",
    sub_fields=[("RANK_REVERSAL", "排名反转")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"RANK_REVERSAL": (-1, 1)},
    category="alpha_classic",
)
def compute_rank_reversal(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    ts_rank = df["close"].rolling(period).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False,
    )
    result = ts_rank.diff().fillna(0)
    return pd.DataFrame({f"RANK_REVERSAL{s}": result}, index=df.index)


@register_factor(
    name="DECAY_LINEAR_RET",
    label="衰减加权收益",
    sub_fields=[("DECAY_LINEAR_RET", "衰减加权收益")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"DECAY_LINEAR_RET": (-0.5, 0.5)},
    category="alpha_classic",
)
def compute_decay_linear_ret(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    returns = df["close"].pct_change()
    weights = np.arange(1, period + 1, dtype=float)
    weights = weights / weights.sum()

    def _decay(x):
        return np.dot(x, weights)

    result = returns.rolling(period).apply(_decay, raw=True).fillna(0)
    return pd.DataFrame({f"DECAY_LINEAR_RET{s}": result}, index=df.index)


@register_factor(
    name="COVARIANCE_VP",
    label="量价协方差",
    sub_fields=[("COVARIANCE_VP", "量价协方差")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"COVARIANCE_VP": (-1e8, 1e8)},
    category="alpha_classic",
)
def compute_covariance_vp(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    result = df["volume"].rolling(period).cov(df["close"]).fillna(0)
    return pd.DataFrame({f"COVARIANCE_VP{s}": result}, index=df.index)


@register_factor(
    name="INTRADAY_INTENSITY",
    label="日内强度",
    sub_fields=[("INTRADAY_INTENSITY", "日内强度")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"INTRADAY_INTENSITY": (-1e8, 1e8)},
    category="alpha_classic",
)
def compute_intraday_intensity(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    hl_range = df["high"] - df["low"] + 1e-8
    ii = (2 * df["close"] - df["high"] - df["low"]) / hl_range * df["volume"]
    result = ii.rolling(period).mean().fillna(0)
    return pd.DataFrame({f"INTRADAY_INTENSITY{s}": result}, index=df.index)


@register_factor(
    name="MONEY_FLOW_VOL",
    label="资金流量",
    sub_fields=[("MONEY_FLOW_VOL", "资金流量")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"MONEY_FLOW_VOL": (-1e9, 1e9)},
    category="alpha_classic",
)
def compute_money_flow_vol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    hl_range = df["high"] - df["low"] + 1e-8
    mfv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range * df["volume"]
    result = mfv.rolling(period).sum().fillna(0)
    return pd.DataFrame({f"MONEY_FLOW_VOL{s}": result}, index=df.index)


@register_factor(
    name="RETURN_CONSISTENCY",
    label="收益稳定性",
    sub_fields=[("RETURN_CONSISTENCY", "收益稳定性")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"RETURN_CONSISTENCY": (-1, 1)},
    category="alpha_classic",
)
def compute_return_consistency(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    returns = df["close"].pct_change()
    lagged = returns.shift(1)

    def _rank_corr(x):
        # x is a 2*period array: first half = lagged, second half = current
        half = len(x) // 2
        a, b = x[:half], x[half:]
        mask = ~(np.isnan(a) | np.isnan(b))
        if mask.sum() < 3:
            return 0.0
        ra = pd.Series(a[mask]).rank().values
        rb = pd.Series(b[mask]).rank().values
        return np.corrcoef(ra, rb)[0, 1] if len(ra) > 1 else 0.0

    combined = pd.concat([lagged, returns], axis=0)
    # Use rolling corr between returns and lagged returns as a simpler approach
    result = returns.rolling(period).corr(lagged).fillna(0)
    return pd.DataFrame({f"RETURN_CONSISTENCY{s}": result}, index=df.index)


@register_factor(
    name="HIGH_LOW_POSITION",
    label="日内收盘位置",
    sub_fields=[("HIGH_LOW_POSITION", "日内收盘位置")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"HIGH_LOW_POSITION": (0, 1)},
    category="alpha_classic",
)
def compute_high_low_position(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    hl_pos = (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-8)
    result = hl_pos.rolling(period).mean().fillna(0)
    return pd.DataFrame({f"HIGH_LOW_POSITION{s}": result}, index=df.index)


# ── Volume-Price Dynamics ───────────────────────────────────


@register_factor(
    name="OBV_SLOPE",
    label="OBV趋势斜率",
    sub_fields=[("OBV_SLOPE", "OBV趋势斜率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"OBV_SLOPE": (-1e7, 1e7)},
    category="alpha_classic",
)
def compute_obv_slope(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    # Compute OBV
    sign = np.sign(df["close"].diff())
    obv = (sign * df["volume"]).cumsum()

    # Linear regression slope over rolling window
    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    def _slope(y):
        y_mean = np.mean(y)
        return np.sum((x - x_mean) * (y - y_mean)) / x_var

    result = obv.rolling(period).apply(_slope, raw=True).fillna(0)
    return pd.DataFrame({f"OBV_SLOPE{s}": result}, index=df.index)


@register_factor(
    name="VOLUME_RATIO",
    label="量比",
    sub_fields=[("VOLUME_RATIO", "量比")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"VOLUME_RATIO": (0, 10)},
    category="alpha_classic",
)
def compute_volume_ratio(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    is_up = df["close"].diff() > 0
    up_vol = (df["volume"] * is_up).rolling(period).sum()
    down_vol = (df["volume"] * ~is_up).rolling(period).sum()
    result = (up_vol / (down_vol + 1e-8)).fillna(0)
    return pd.DataFrame({f"VOLUME_RATIO{s}": result}, index=df.index)


@register_factor(
    name="PV_FIT",
    label="量价拟合度",
    sub_fields=[("PV_FIT", "量价拟合度")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"PV_FIT": (0, 1)},
    category="alpha_classic",
)
def compute_pv_fit(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"

    def _r_squared(args):
        # args is close values; we pair with corresponding volume via index
        n = len(args)
        x = np.arange(n, dtype=float)
        y = args
        if np.std(y) == 0:
            return 0.0
        corr = np.corrcoef(x, y)[0, 1]
        return corr ** 2 if not np.isnan(corr) else 0.0

    # R² of close vs volume: use rolling corr then square
    r = df["close"].rolling(period).corr(df["volume"])
    result = (r ** 2).fillna(0)
    return pd.DataFrame({f"PV_FIT{s}": result}, index=df.index)


@register_factor(
    name="VOLUME_SURPRISE",
    label="成交量异常度",
    sub_fields=[("VOLUME_SURPRISE", "成交量异常度")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"VOLUME_SURPRISE": (0, 10)},
    category="alpha_classic",
)
def compute_volume_surprise(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    vol_ma = df["volume"].rolling(period).mean()
    result = (df["volume"] / (vol_ma + 1e-8)).fillna(0)
    return pd.DataFrame({f"VOLUME_SURPRISE{s}": result}, index=df.index)


@register_factor(
    name="NET_FLOW_RATIO",
    label="净流入比率",
    sub_fields=[("NET_FLOW_RATIO", "净流入比率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"NET_FLOW_RATIO": (-1, 1)},
    category="alpha_classic",
)
def compute_net_flow_ratio(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    sign = np.where(df["close"] > df["open"], 1, -1)
    amount = df["volume"] * df["close"]
    signed_amount = sign * amount
    net = pd.Series(signed_amount, index=df.index).rolling(period).sum()
    total = amount.rolling(period).sum()
    result = (net / (total + 1e-8)).fillna(0)
    return pd.DataFrame({f"NET_FLOW_RATIO{s}": result}, index=df.index)


@register_factor(
    name="PRICE_IMPACT",
    label="价格冲击",
    sub_fields=[("PRICE_IMPACT", "价格冲击")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"PRICE_IMPACT": (0, 1)},
    category="alpha_classic",
)
def compute_price_impact(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    abs_ret = df["close"].pct_change().abs()
    log_vol = np.log(df["volume"] + 1)
    impact = abs_ret / (log_vol + 1e-8)
    result = impact.rolling(period).mean().fillna(0)
    return pd.DataFrame({f"PRICE_IMPACT{s}": result}, index=df.index)
