"""Price action factors: MOM, RSTR, PPOS, KBAR."""

import numpy as np
import pandas as pd

from .registry import register_factor


@register_factor(
    name="MOM",
    label="动量",
    sub_fields=[("MOM", "动量%")],
    params={"period": {"label": "回看周期", "default": 20, "type": "int"}},
    field_ranges={"MOM": (-100, 500)},
    category="price_action",
)
def compute_mom(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    shifted = df["close"].shift(period)
    mom = (df["close"] - shifted) / shifted.replace(0, np.nan) * 100
    return pd.DataFrame({f"MOM_{period}": mom}, index=df.index)


@register_factor(
    name="RSTR",
    label="相对强弱",
    sub_fields=[
        ("RSTR", "N日收益率%"),
        ("RSTR_weighted", "加权动量"),
    ],
    params={
        "period": {"label": "回看周期", "default": 20, "type": "int"},
    },
    field_ranges={
        "RSTR": (-50, 100),
        "RSTR_weighted": (-10, 10),
    },
    category="price_action",
)
def compute_rstr(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    shifted = df["close"].shift(period)
    rstr = (df["close"] - shifted) / shifted.replace(0, np.nan) * 100
    # Weighted momentum: linearly decaying weights [period, period-1, ..., 1]
    daily_ret = df["close"].pct_change()
    weights = np.arange(1, period + 1, dtype=float)  # [1, 2, ..., N]
    weight_sum = weights.sum()

    def _weighted_mean(x):
        if len(x) < period:
            return np.nan
        valid = x.values
        if np.any(np.isnan(valid)):
            return np.nan
        return np.dot(valid, weights) / weight_sum

    weighted = daily_ret.rolling(period).apply(_weighted_mean, raw=False)
    return pd.DataFrame({
        f"RSTR{s}": rstr,
        f"RSTR_weighted{s}": weighted,
    }, index=df.index)


@register_factor(
    name="PPOS",
    label="价格位置",
    sub_fields=[
        ("PPOS_close_pos", "收盘价位置(0-1)"),
        ("PPOS_high_dist", "距N日高点%"),
        ("PPOS_low_dist", "距N日低点%"),
        ("PPOS_drawdown", "N日最大回撤%"),
        ("PPOS_consec_dir", "连涨/跌天数"),
    ],
    params={
        "period": {"label": "回看周期", "default": 20, "type": "int"},
    },
    field_ranges={
        "PPOS_close_pos": (0, 1),
        "PPOS_high_dist": (-50, 0),
        "PPOS_low_dist": (0, 200),
        "PPOS_drawdown": (-50, 0),
        "PPOS_consec_dir": (-15, 15),
    },
    category="price_action",
)
def compute_ppos(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    roll_min_low = df["low"].rolling(period).min()
    roll_max_high = df["high"].rolling(period).max()
    hilo_range = (roll_max_high - roll_min_low).replace(0, np.nan)
    close_pos = (df["close"] - roll_min_low) / hilo_range
    high_dist = (df["close"] / roll_max_high.replace(0, np.nan) - 1) * 100
    low_dist = (df["close"] / roll_min_low.replace(0, np.nan) - 1) * 100
    roll_max_close = df["close"].rolling(period).max()
    drawdown = (df["close"] / roll_max_close.replace(0, np.nan) - 1) * 100
    # Consecutive direction: positive = up days, negative = down days
    change = df["close"].diff()
    direction = np.sign(change)
    consec = pd.Series(0, index=df.index, dtype=float)
    prev = 0.0
    for i in range(len(direction)):
        d = direction.iloc[i]
        if np.isnan(d) or d == 0:
            prev = 0.0
        elif d > 0:
            prev = max(prev, 0) + 1
        else:
            prev = min(prev, 0) - 1
        consec.iloc[i] = prev
    return pd.DataFrame({
        f"PPOS_close_pos{s}": close_pos,
        f"PPOS_high_dist{s}": high_dist,
        f"PPOS_low_dist{s}": low_dist,
        f"PPOS_drawdown{s}": drawdown,
        f"PPOS_consec_dir{s}": consec,
    }, index=df.index)


@register_factor(
    name="KBAR",
    label="K线形态",
    sub_fields=[
        ("KBAR_upper_shadow", "上影线比率"),
        ("KBAR_lower_shadow", "下影线比率"),
        ("KBAR_body_ratio", "实体比率"),
        ("KBAR_amplitude", "振幅"),
        ("KBAR_overnight_ret", "隔夜收益率%"),
        ("KBAR_intraday_ret", "日内收益率%"),
    ],
    params={},
    field_ranges={
        "KBAR_upper_shadow": (0, 1),
        "KBAR_lower_shadow": (0, 1),
        "KBAR_body_ratio": (0, 1),
        "KBAR_amplitude": (0, 0.3),
        "KBAR_overnight_ret": (-15, 15),
        "KBAR_intraday_ret": (-15, 15),
    },
    category="price_action",
)
def compute_kbar(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    bar_range = (df["high"] - df["low"]).replace(0, np.nan)
    body_top = df[["open", "close"]].max(axis=1)
    body_bot = df[["open", "close"]].min(axis=1)
    upper_shadow = (df["high"] - body_top) / bar_range
    lower_shadow = (body_bot - df["low"]) / bar_range
    body_ratio = (body_top - body_bot) / bar_range
    amplitude = (df["high"] - df["low"]) / df["close"].replace(0, np.nan)
    prev_close = df["close"].shift(1)
    overnight_ret = (df["open"] - prev_close) / prev_close.replace(0, np.nan) * 100
    intraday_ret = (df["close"] - df["open"]) / df["open"].replace(0, np.nan) * 100
    return pd.DataFrame({
        "KBAR_upper_shadow": upper_shadow,
        "KBAR_lower_shadow": lower_shadow,
        "KBAR_body_ratio": body_ratio,
        "KBAR_amplitude": amplitude,
        "KBAR_overnight_ret": overnight_ret,
        "KBAR_intraday_ret": intraday_ret,
    }, index=df.index)
