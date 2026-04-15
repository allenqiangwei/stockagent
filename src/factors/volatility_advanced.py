"""Advanced volatility factors: Garman-Klass, Rogers-Satchell, Yang-Zhang,
Upside/Downside Vol separation, Vol-of-Vol, Overnight Vol, Intraday Vol."""

import numpy as np
import pandas as pd

from .registry import register_factor


@register_factor(
    name="GARMAN_KLASS",
    label="GK波动率",
    sub_fields=[("GARMAN_KLASS", "GK波动率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"GARMAN_KLASS": (0, 1)},
    category="volatility",
)
def compute_garman_klass(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    log_hl = np.log(df["high"] / df["low"].replace(0, np.nan))
    log_co = np.log(df["close"] / df["open"].replace(0, np.nan))
    gk = 0.5 * log_hl ** 2 - (2 * np.log(2) - 1) * log_co ** 2
    result = np.sqrt(gk.rolling(period).mean().clip(lower=0))
    return pd.DataFrame({f"GARMAN_KLASS{s}": result}, index=df.index)


@register_factor(
    name="ROGERS_SATCHELL",
    label="RS波动率",
    sub_fields=[("ROGERS_SATCHELL", "RS波动率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"ROGERS_SATCHELL": (0, 1)},
    category="volatility",
)
def compute_rogers_satchell(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    h, l, c, o = df["high"], df["low"], df["close"], df["open"]
    rs = (np.log(h / c.replace(0, np.nan)) * np.log(h / o.replace(0, np.nan))
          + np.log(l / c.replace(0, np.nan)) * np.log(l / o.replace(0, np.nan)))
    result = np.sqrt(rs.rolling(period).mean().clip(lower=0))
    return pd.DataFrame({f"ROGERS_SATCHELL{s}": result}, index=df.index)


@register_factor(
    name="YANG_ZHANG",
    label="YZ波动率",
    sub_fields=[("YANG_ZHANG", "YZ波动率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"YANG_ZHANG": (0, 1)},
    category="volatility",
)
def compute_yang_zhang(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    h, l, c, o = df["high"], df["low"], df["close"], df["open"]
    prev_c = c.shift(1)
    # Overnight return
    log_oc = np.log(o / prev_c.replace(0, np.nan))
    # Open-to-close return
    log_co = np.log(c / o.replace(0, np.nan))
    # Rogers-Satchell component
    rs = (np.log(h / c.replace(0, np.nan)) * np.log(h / o.replace(0, np.nan))
          + np.log(l / c.replace(0, np.nan)) * np.log(l / o.replace(0, np.nan)))
    n = period
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    overnight_var = log_oc.rolling(n).var()
    oc_var = log_co.rolling(n).var()
    rs_var = rs.rolling(n).mean()
    yz = overnight_var + k * oc_var + (1 - k) * rs_var.clip(lower=0)
    result = np.sqrt(yz.clip(lower=0))
    return pd.DataFrame({f"YANG_ZHANG{s}": result}, index=df.index)


@register_factor(
    name="VOLSPLIT",
    label="上下行波动率",
    sub_fields=[
        ("VOLSPLIT_up", "上行波动率"),
        ("VOLSPLIT_down", "下行波动率"),
        ("VOLSPLIT_ratio", "上下行比"),
    ],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={
        "VOLSPLIT_up": (0, 0.5),
        "VOLSPLIT_down": (0, 0.5),
        "VOLSPLIT_ratio": (0, 5),
    },
    category="volatility",
)
def compute_volsplit(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    returns = df["close"].pct_change()
    up_ret = returns.where(returns > 0, np.nan)
    down_ret = returns.where(returns <= 0, np.nan)
    up_vol = up_ret.rolling(period, min_periods=1).std().fillna(0)
    down_vol = down_ret.rolling(period, min_periods=1).std().fillna(0)
    ratio = up_vol / (down_vol + 1e-8)
    return pd.DataFrame({
        f"VOLSPLIT_up{s}": up_vol,
        f"VOLSPLIT_down{s}": down_vol,
        f"VOLSPLIT_ratio{s}": ratio,
    }, index=df.index)


@register_factor(
    name="VOL_OF_VOL",
    label="波动率的波动率",
    sub_fields=[("VOL_OF_VOL", "波动率的波动率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"VOL_OF_VOL": (0, 0.5)},
    category="volatility",
)
def compute_vol_of_vol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    returns = df["close"].pct_change()
    short_vol = returns.rolling(5).std()
    vov = short_vol.rolling(period).std().fillna(0)
    return pd.DataFrame({f"VOL_OF_VOL{s}": vov}, index=df.index)


@register_factor(
    name="OVERNIGHT_VOL",
    label="隔夜波动率",
    sub_fields=[("OVERNIGHT_VOL", "隔夜波动率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"OVERNIGHT_VOL": (0, 0.3)},
    category="volatility",
)
def compute_overnight_vol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    overnight_ret = df["open"] / df["close"].shift(1).replace(0, np.nan) - 1
    result = overnight_ret.rolling(period).std().fillna(0)
    return pd.DataFrame({f"OVERNIGHT_VOL{s}": result}, index=df.index)


@register_factor(
    name="INTRADAY_VOL",
    label="日内波动率",
    sub_fields=[("INTRADAY_VOL", "日内波动率")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    field_ranges={"INTRADAY_VOL": (0, 0.3)},
    category="volatility",
)
def compute_intraday_vol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    intraday_ret = df["close"] / df["open"].replace(0, np.nan) - 1
    result = intraday_ret.rolling(period).std().fillna(0)
    return pd.DataFrame({f"INTRADAY_VOL{s}": result}, index=df.index)
