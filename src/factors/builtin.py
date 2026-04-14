"""Builtin indicators registered as factors: MA, EMA, RSI, MACD, KDJ, ADX, OBV, ATR, VOLUME_MA.

These 9 indicators are also computed by the legacy IndicatorCalculator in
src/indicators/indicator_calculator.py. Registering them here makes the factor
registry the single source of truth for metadata (sub_fields, params, field_ranges).
"""

import pandas as pd

from .registry import register_factor


# ── MA ────────────────────────────────────────────────────

@register_factor(
    name="MA",
    label="MA均线",
    sub_fields=[("MA", "MA均线")],
    params={"period": {"label": "周期", "default": 20, "type": "int"}},
    category="builtin",
)
def compute_ma(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import talib
    period = int(params.get("period", 20))
    close = df["close"].values.astype(float)
    values = talib.SMA(close, timeperiod=period)
    col = f"MA_{period}"
    return pd.DataFrame({col: values}, index=df.index)


# ── EMA ───────────────────────────────────────────────────

@register_factor(
    name="EMA",
    label="EMA均线",
    sub_fields=[("EMA", "EMA均线")],
    params={"period": {"label": "周期", "default": 12, "type": "int"}},
    category="builtin",
)
def compute_ema(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import talib
    period = int(params.get("period", 12))
    close = df["close"].values.astype(float)
    values = talib.EMA(close, timeperiod=period)
    col = f"EMA_{period}"
    return pd.DataFrame({col: values}, index=df.index)


# ── RSI ───────────────────────────────────────────────────

@register_factor(
    name="RSI",
    label="RSI相对强弱",
    sub_fields=[("RSI", "RSI")],
    params={"period": {"label": "周期", "default": 14, "type": "int"}},
    field_ranges={"RSI": (0, 100)},
    category="builtin",
)
def compute_rsi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import talib
    period = int(params.get("period", 14))
    close = df["close"].values.astype(float)
    rsi = talib.RSI(close, timeperiod=period)
    col = f"RSI_{period}"
    return pd.DataFrame({col: rsi}, index=df.index)


# ── MACD ──────────────────────────────────────────────────

@register_factor(
    name="MACD",
    label="MACD",
    sub_fields=[
        ("MACD", "MACD线"),
        ("MACD_signal", "MACD信号线"),
        ("MACD_hist", "MACD柱状图"),
    ],
    params={
        "fast": {"label": "快线周期", "default": 12, "type": "int"},
        "slow": {"label": "慢线周期", "default": 26, "type": "int"},
        "signal": {"label": "信号线周期", "default": 9, "type": "int"},
    },
    category="builtin",
)
def compute_macd(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import talib
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    signal = int(params.get("signal", 9))
    close = df["close"].values.astype(float)
    macd, macd_signal, macd_hist = talib.MACD(
        close, fastperiod=fast, slowperiod=slow, signalperiod=signal
    )
    suffix = f"_{fast}_{slow}_{signal}"
    return pd.DataFrame({
        f"MACD{suffix}": macd,
        f"MACD_signal{suffix}": macd_signal,
        f"MACD_hist{suffix}": macd_hist,
    }, index=df.index)


# ── KDJ ───────────────────────────────────────────────────

@register_factor(
    name="KDJ",
    label="KDJ",
    sub_fields=[
        ("KDJ_K", "KDJ-K值"),
        ("KDJ_D", "KDJ-D值"),
        ("KDJ_J", "KDJ-J值"),
    ],
    params={
        "fastk": {"label": "K线周期", "default": 9, "type": "int"},
        "slowk": {"label": "K线平滑", "default": 3, "type": "int"},
        "slowd": {"label": "D线平滑", "default": 3, "type": "int"},
    },
    field_ranges={
        "KDJ_K": (0, 100),
        "KDJ_D": (0, 100),
        "KDJ_J": (-20, 120),
    },
    category="builtin",
)
def compute_kdj(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import talib
    fastk = int(params.get("fastk", 9))
    slowk = int(params.get("slowk", 3))
    slowd = int(params.get("slowd", 3))
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    k, d = talib.STOCH(
        high, low, close,
        fastk_period=fastk,
        slowk_period=slowk, slowk_matype=0,
        slowd_period=slowd, slowd_matype=0,
    )
    import numpy as np
    k_s = pd.Series(k, index=df.index)
    d_s = pd.Series(d, index=df.index)
    j_s = 3 * k_s - 2 * d_s
    suffix = f"_{fastk}_{slowk}_{slowd}"
    return pd.DataFrame({
        f"KDJ_K{suffix}": k_s,
        f"KDJ_D{suffix}": d_s,
        f"KDJ_J{suffix}": j_s,
    }, index=df.index)


# ── ADX ───────────────────────────────────────────────────

@register_factor(
    name="ADX",
    label="ADX趋势",
    sub_fields=[
        ("ADX", "ADX"),
        ("ADX_plus_di", "+DI"),
        ("ADX_minus_di", "-DI"),
    ],
    params={"period": {"label": "周期", "default": 14, "type": "int"}},
    field_ranges={
        "ADX": (0, 100),
        "ADX_plus_di": (0, 100),
        "ADX_minus_di": (0, 100),
    },
    category="builtin",
)
def compute_adx(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import talib
    period = int(params.get("period", 14))
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    adx = talib.ADX(high, low, close, timeperiod=period)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=period)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=period)
    return pd.DataFrame({
        f"ADX_{period}": adx,
        f"ADX_plus_di_{period}": plus_di,
        f"ADX_minus_di_{period}": minus_di,
    }, index=df.index)


# ── OBV ───────────────────────────────────────────────────

@register_factor(
    name="OBV",
    label="OBV能量潮",
    sub_fields=[("OBV", "OBV能量潮")],
    params={},
    category="builtin",
)
def compute_obv(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import talib
    close = df["close"].values.astype(float)
    volume = df["volume"].values.astype(float)
    obv = talib.OBV(close, volume)
    return pd.DataFrame({"OBV": obv}, index=df.index)


# ── ATR ───────────────────────────────────────────────────

@register_factor(
    name="ATR",
    label="ATR波幅",
    sub_fields=[("ATR", "ATR波幅")],
    params={"period": {"label": "周期", "default": 14, "type": "int"}},
    category="builtin",
)
def compute_atr(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import talib
    period = int(params.get("period", 14))
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    atr = talib.ATR(high, low, close, timeperiod=period)
    col = f"ATR_{period}"
    return pd.DataFrame({col: atr}, index=df.index)


# ── VOLUME_MA ─────────────────────────────────────────────

@register_factor(
    name="VOLUME_MA",
    label="成交量均线",
    sub_fields=[("volume_ma", "成交量均线")],
    params={"period": {"label": "周期", "default": 5, "type": "int"}},
    category="builtin",
)
def compute_volume_ma(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    period = int(params.get("period", 5))
    if "volume" not in df.columns:
        import numpy as np
        return pd.DataFrame(
            {f"volume_ma_{period}": pd.Series(np.nan, index=df.index)},
            index=df.index,
        )
    vol_ma = df["volume"].rolling(window=period, min_periods=period).mean()
    col = f"volume_ma_{period}"
    return pd.DataFrame({col: vol_ma}, index=df.index)
