"""Volatility factors: BOLL, DONCHIAN, KELTNER, ULCER, REALVOL, AMPVOL."""

import numpy as np
import pandas as pd

from .registry import register_factor


@register_factor(
    name="BOLL",
    label="布林带",
    sub_fields=[
        ("BOLL_upper", "布林上轨"),
        ("BOLL_middle", "布林中轨"),
        ("BOLL_lower", "布林下轨"),
        ("BOLL_pband", "布林%B"),
        ("BOLL_wband", "布林带宽"),
    ],
    params={
        "length": {"label": "周期", "default": 20, "type": "int"},
        "std": {"label": "标准差倍数", "default": 2.0, "type": "float"},
    },
    field_ranges={"BOLL_pband": (0, 1)},
    category="volatility",
)
def compute_boll(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volatility import BollingerBands
    length = params.get("length", 20)
    std = params.get("std", 2.0)
    bb = BollingerBands(df["close"], window=length, window_dev=std)
    s = f"_{length}_{std}"
    return pd.DataFrame({
        f"BOLL_upper{s}": bb.bollinger_hband(),
        f"BOLL_middle{s}": bb.bollinger_mavg(),
        f"BOLL_lower{s}": bb.bollinger_lband(),
        f"BOLL_pband{s}": bb.bollinger_pband(),
        f"BOLL_wband{s}": bb.bollinger_wband(),
    }, index=df.index)


@register_factor(
    name="DONCHIAN",
    label="唐奇安通道",
    sub_fields=[
        ("DONCHIAN_upper", "唐奇安上轨"),
        ("DONCHIAN_lower", "唐奇安下轨"),
        ("DONCHIAN_middle", "唐奇安中轨"),
    ],
    params={
        "length": {"label": "周期", "default": 20, "type": "int"},
    },
    category="volatility",
)
def compute_donchian(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volatility import DonchianChannel
    length = params.get("length", 20)
    dc = DonchianChannel(df["high"], df["low"], df["close"], window=length)
    s = f"_{length}"
    return pd.DataFrame({
        f"DONCHIAN_upper{s}": dc.donchian_channel_hband(),
        f"DONCHIAN_lower{s}": dc.donchian_channel_lband(),
        f"DONCHIAN_middle{s}": dc.donchian_channel_mband(),
    }, index=df.index)


@register_factor(
    name="KELTNER",
    label="肯特纳通道",
    sub_fields=[
        ("KELTNER_upper", "肯特纳上轨"),
        ("KELTNER_lower", "肯特纳下轨"),
        ("KELTNER_middle", "肯特纳中轨"),
    ],
    params={
        "length": {"label": "周期", "default": 20, "type": "int"},
        "length_atr": {"label": "ATR周期", "default": 10, "type": "int"},
    },
    category="volatility",
)
def compute_keltner(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volatility import KeltnerChannel
    length = params.get("length", 20)
    length_atr = params.get("length_atr", 10)
    kc = KeltnerChannel(df["high"], df["low"], df["close"],
                        window=length, window_atr=length_atr)
    s = f"_{length}_{length_atr}"
    return pd.DataFrame({
        f"KELTNER_upper{s}": kc.keltner_channel_hband(),
        f"KELTNER_lower{s}": kc.keltner_channel_lband(),
        f"KELTNER_middle{s}": kc.keltner_channel_mband(),
    }, index=df.index)


@register_factor(
    name="ULCER",
    label="溃疡指数",
    sub_fields=[("ULCER", "溃疡指数")],
    params={
        "length": {"label": "周期", "default": 14, "type": "int"},
    },
    category="volatility",
)
def compute_ulcer(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volatility import UlcerIndex
    length = params.get("length", 14)
    ui = UlcerIndex(df["close"], window=length)
    return pd.DataFrame({f"ULCER_{length}": ui.ulcer_index()}, index=df.index)


@register_factor(
    name="REALVOL",
    label="已实现波动率",
    sub_fields=[
        ("REALVOL", "波动率%"),
        ("REALVOL_skew", "收益偏度"),
        ("REALVOL_kurt", "收益峰度"),
        ("REALVOL_downside", "下行波动率%"),
    ],
    params={
        "period": {"label": "回看周期", "default": 20, "type": "int"},
    },
    field_ranges={
        "REALVOL": (0, 30),
        "REALVOL_skew": (-5, 5),
        "REALVOL_kurt": (-5, 30),
        "REALVOL_downside": (0, 30),
    },
    category="volatility",
)
def compute_realvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 20)
    returns = df["close"].pct_change()
    s = f"_{period}"
    vol = returns.rolling(period).std() * 100
    skew = returns.rolling(period).skew()
    kurt = returns.rolling(period).kurt()
    # Downside vol: only negative returns, replace positive with NaN
    neg_returns = returns.where(returns < 0, np.nan)
    downside = neg_returns.rolling(period, min_periods=1).std() * 100
    return pd.DataFrame({
        f"REALVOL{s}": vol,
        f"REALVOL_skew{s}": skew,
        f"REALVOL_kurt{s}": kurt,
        f"REALVOL_downside{s}": downside,
    }, index=df.index)


@register_factor(
    name="AMPVOL",
    label="振幅波动",
    sub_fields=[
        ("AMPVOL_std", "振幅标准差"),
        ("AMPVOL_parkinson", "Parkinson波动率"),
    ],
    params={
        "period": {"label": "回看周期", "default": 5, "type": "int"},
    },
    field_ranges={
        "AMPVOL_std": (0, 0.2),
        "AMPVOL_parkinson": (0, 20),
    },
    category="volatility",
)
def compute_ampvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = params.get("period", 5)
    s = f"_{period}"
    amplitude = (df["high"] - df["low"]) / df["close"].replace(0, np.nan)
    amp_std = amplitude.rolling(period).std()
    log_hl = np.log(df["high"] / df["low"].replace(0, np.nan))
    parkinson = np.sqrt(
        (log_hl ** 2).rolling(period).mean() / (4 * np.log(2))
    ) * 100
    return pd.DataFrame({
        f"AMPVOL_std{s}": amp_std,
        f"AMPVOL_parkinson{s}": parkinson,
    }, index=df.index)
