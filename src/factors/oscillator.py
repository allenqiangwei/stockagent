"""Oscillator factors: ROC, WR, MFI, STOCHRSI, STOCH, AO, KAMA, PPO, PVO, TSI, ULTOSC."""

import pandas as pd

from .registry import register_factor


@register_factor(
    name="ROC",
    label="变动率",
    sub_fields=[("ROC", "变动率")],
    params={
        "length": {"label": "周期", "default": 12, "type": "int"},
    },
    category="oscillator",
)
def compute_roc(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import ROCIndicator
    length = params.get("length", 12)
    roc = ROCIndicator(df["close"], window=length)
    return pd.DataFrame({f"ROC_{length}": roc.roc()}, index=df.index)


@register_factor(
    name="WR",
    label="威廉指标",
    sub_fields=[("WR", "威廉指标")],
    params={
        "length": {"label": "周期", "default": 14, "type": "int"},
    },
    field_ranges={"WR": (-100, 0)},
    category="oscillator",
)
def compute_wr(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import WilliamsRIndicator
    length = params.get("length", 14)
    wr = WilliamsRIndicator(df["high"], df["low"], df["close"], lbp=length)
    return pd.DataFrame({f"WR_{length}": wr.williams_r()}, index=df.index)


@register_factor(
    name="MFI",
    label="资金流量指标",
    sub_fields=[("MFI", "MFI")],
    params={
        "length": {"label": "周期", "default": 14, "type": "int"},
    },
    field_ranges={"MFI": (0, 100)},
    category="oscillator",
)
def compute_mfi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import MFIIndicator
    length = params.get("length", 14)
    mfi = MFIIndicator(df["high"], df["low"], df["close"], df["volume"], window=length)
    return pd.DataFrame({f"MFI_{length}": mfi.money_flow_index()}, index=df.index)


@register_factor(
    name="STOCHRSI",
    label="随机RSI",
    sub_fields=[
        ("STOCHRSI_K", "StochRSI_K"),
        ("STOCHRSI_D", "StochRSI_D"),
    ],
    params={
        "length": {"label": "RSI周期", "default": 14, "type": "int"},
        "smooth_k": {"label": "K平滑", "default": 3, "type": "int"},
        "smooth_d": {"label": "D平滑", "default": 3, "type": "int"},
    },
    field_ranges={
        "STOCHRSI_K": (0, 100),
        "STOCHRSI_D": (0, 100),
    },
    category="oscillator",
)
def compute_stochrsi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import StochRSIIndicator
    length = params.get("length", 14)
    smooth_k = params.get("smooth_k", 3)
    smooth_d = params.get("smooth_d", 3)
    sr = StochRSIIndicator(df["close"], window=length,
                           smooth1=smooth_k, smooth2=smooth_d)
    s = f"_{length}_{smooth_k}_{smooth_d}"
    return pd.DataFrame({
        f"STOCHRSI_K{s}": sr.stochrsi_k(),
        f"STOCHRSI_D{s}": sr.stochrsi_d(),
    }, index=df.index)


@register_factor(
    name="STOCH",
    label="随机震荡指标",
    sub_fields=[
        ("STOCH_K", "Stoch_K"),
        ("STOCH_D", "Stoch_D"),
    ],
    params={
        "length": {"label": "周期", "default": 14, "type": "int"},
        "smooth": {"label": "平滑", "default": 3, "type": "int"},
    },
    field_ranges={
        "STOCH_K": (0, 100),
        "STOCH_D": (0, 100),
    },
    category="oscillator",
)
def compute_stoch(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import StochasticOscillator
    length = params.get("length", 14)
    smooth = params.get("smooth", 3)
    so = StochasticOscillator(df["high"], df["low"], df["close"],
                              window=length, smooth_window=smooth)
    s = f"_{length}_{smooth}"
    return pd.DataFrame({
        f"STOCH_K{s}": so.stoch(),
        f"STOCH_D{s}": so.stoch_signal(),
    }, index=df.index)


@register_factor(
    name="AO",
    label="动量震荡器",
    sub_fields=[("AO", "AO")],
    params={
        "fast": {"label": "快周期", "default": 5, "type": "int"},
        "slow": {"label": "慢周期", "default": 34, "type": "int"},
    },
    category="oscillator",
)
def compute_ao(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import AwesomeOscillatorIndicator
    fast = params.get("fast", 5)
    slow = params.get("slow", 34)
    ao = AwesomeOscillatorIndicator(df["high"], df["low"],
                                    window1=fast, window2=slow)
    s = f"_{fast}_{slow}"
    return pd.DataFrame({f"AO{s}": ao.awesome_oscillator()}, index=df.index)


@register_factor(
    name="KAMA",
    label="考夫曼自适应均线",
    sub_fields=[("KAMA", "KAMA")],
    params={
        "length": {"label": "周期", "default": 10, "type": "int"},
    },
    category="oscillator",
)
def compute_kama(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import KAMAIndicator
    length = params.get("length", 10)
    kama = KAMAIndicator(df["close"], window=length)
    return pd.DataFrame({f"KAMA_{length}": kama.kama()}, index=df.index)


@register_factor(
    name="PPO",
    label="价格震荡百分比",
    sub_fields=[
        ("PPO", "PPO"),
        ("PPO_signal", "PPO信号线"),
        ("PPO_hist", "PPO柱线"),
    ],
    params={
        "fast": {"label": "快周期", "default": 12, "type": "int"},
        "slow": {"label": "慢周期", "default": 26, "type": "int"},
        "signal": {"label": "信号周期", "default": 9, "type": "int"},
    },
    category="oscillator",
)
def compute_ppo(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import PercentagePriceOscillator
    fast = params.get("fast", 12)
    slow = params.get("slow", 26)
    signal = params.get("signal", 9)
    ppo = PercentagePriceOscillator(df["close"], window_fast=fast,
                                    window_slow=slow, window_sign=signal)
    s = f"_{fast}_{slow}_{signal}"
    return pd.DataFrame({
        f"PPO{s}": ppo.ppo(),
        f"PPO_signal{s}": ppo.ppo_signal(),
        f"PPO_hist{s}": ppo.ppo_hist(),
    }, index=df.index)


@register_factor(
    name="PVO",
    label="成交量震荡百分比",
    sub_fields=[
        ("PVO", "PVO"),
        ("PVO_signal", "PVO信号线"),
        ("PVO_hist", "PVO柱线"),
    ],
    params={
        "fast": {"label": "快周期", "default": 12, "type": "int"},
        "slow": {"label": "慢周期", "default": 26, "type": "int"},
        "signal": {"label": "信号周期", "default": 9, "type": "int"},
    },
    category="oscillator",
)
def compute_pvo(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import PercentageVolumeOscillator
    fast = params.get("fast", 12)
    slow = params.get("slow", 26)
    signal = params.get("signal", 9)
    pvo = PercentageVolumeOscillator(df["volume"], window_fast=fast,
                                     window_slow=slow, window_sign=signal)
    s = f"_{fast}_{slow}_{signal}"
    return pd.DataFrame({
        f"PVO{s}": pvo.pvo(),
        f"PVO_signal{s}": pvo.pvo_signal(),
        f"PVO_hist{s}": pvo.pvo_hist(),
    }, index=df.index)


@register_factor(
    name="TSI",
    label="真实强度指数",
    sub_fields=[("TSI", "TSI")],
    params={
        "fast": {"label": "快周期", "default": 13, "type": "int"},
        "slow": {"label": "慢周期", "default": 25, "type": "int"},
    },
    category="oscillator",
)
def compute_tsi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import TSIIndicator
    fast = params.get("fast", 13)
    slow = params.get("slow", 25)
    tsi = TSIIndicator(df["close"], window_fast=fast, window_slow=slow)
    s = f"_{fast}_{slow}"
    return pd.DataFrame({f"TSI{s}": tsi.tsi()}, index=df.index)


@register_factor(
    name="ULTOSC",
    label="终极震荡指标",
    sub_fields=[("ULTOSC", "终极震荡")],
    params={
        "w1": {"label": "短周期", "default": 7, "type": "int"},
        "w2": {"label": "中周期", "default": 14, "type": "int"},
        "w3": {"label": "长周期", "default": 28, "type": "int"},
    },
    field_ranges={"ULTOSC": (0, 100)},
    category="oscillator",
)
def compute_ultosc(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import UltimateOscillator
    w1 = params.get("w1", 7)
    w2 = params.get("w2", 14)
    w3 = params.get("w3", 28)
    uo = UltimateOscillator(df["high"], df["low"], df["close"],
                            window1=w1, window2=w2, window3=w3)
    s = f"_{w1}_{w2}_{w3}"
    return pd.DataFrame({f"ULTOSC{s}": uo.ultimate_oscillator()}, index=df.index)
