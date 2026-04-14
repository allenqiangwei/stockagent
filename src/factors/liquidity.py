"""Liquidity factors: LIQ, PVOL."""

import numpy as np
import pandas as pd

from .registry import register_factor


@register_factor(
    name="LIQ",
    label="流动性",
    sub_fields=[
        ("LIQ_amihud", "Amihud非流动性"),
        ("LIQ_turnover_vol", "换手波动率"),
        ("LIQ_log_amount", "对数成交额"),
    ],
    params={
        "period": {"label": "回看周期", "default": 20, "type": "int"},
    },
    field_ranges={
        "LIQ_amihud": (0, 100),
        "LIQ_turnover_vol": (0, 5),
        "LIQ_log_amount": (0, 30),
    },
    category="liquidity",
)
def compute_liq(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    amount = df["amount"] if "amount" in df.columns else df["close"] * df["volume"]
    returns = df["close"].pct_change()
    illiq = returns.abs() / amount.replace(0, np.nan)
    amihud = illiq.rolling(period).mean() * 1e9
    vol_mean = df["volume"].rolling(period).mean().replace(0, np.nan)
    vol_std = df["volume"].rolling(period).std()
    turnover_vol = vol_std / vol_mean
    log_amount = np.log1p(amount.rolling(period).mean())
    return pd.DataFrame({
        f"LIQ_amihud{s}": amihud,
        f"LIQ_turnover_vol{s}": turnover_vol,
        f"LIQ_log_amount{s}": log_amount,
    }, index=df.index)


@register_factor(
    name="PVOL",
    label="量价关系",
    sub_fields=[
        ("PVOL_corr", "量价相关性"),
        ("PVOL_amount_conc", "成交额集中度"),
        ("PVOL_vwap_bias", "VWAP偏离度%"),
    ],
    params={
        "period": {"label": "回看周期", "default": 20, "type": "int"},
    },
    field_ranges={
        "PVOL_corr": (-1, 1),
        "PVOL_amount_conc": (0, 1),
        "PVOL_vwap_bias": (-20, 20),
    },
    category="liquidity",
)
def compute_pvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    s = f"_{period}"
    amount = df["amount"] if "amount" in df.columns else df["close"] * df["volume"]
    returns = df["close"].pct_change()
    corr = returns.rolling(period).corr(df["volume"])
    amount_max = amount.rolling(period).max()
    amount_sum = amount.rolling(period).sum().replace(0, np.nan)
    amount_conc = amount_max / amount_sum
    vwap_amount_sum = amount.rolling(period).sum()
    vwap_volume_sum = df["volume"].rolling(period).sum().replace(0, np.nan)
    vwap = vwap_amount_sum / vwap_volume_sum
    vwap_bias = (df["close"] - vwap) / vwap.replace(0, np.nan) * 100
    return pd.DataFrame({
        f"PVOL_corr{s}": corr,
        f"PVOL_amount_conc{s}": amount_conc,
        f"PVOL_vwap_bias{s}": vwap_bias,
    }, index=df.index)
