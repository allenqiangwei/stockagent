"""Trend factors: CCI, AROON, ICHIMOKU, KST, MASS, PSAR, STC, VORTEX, WMA, TRIX, DPO."""

import pandas as pd

from .registry import register_factor


@register_factor(
    name="CCI",
    label="CCI顺势指标",
    sub_fields=[("CCI", "CCI")],
    params={
        "length": {"label": "周期", "default": 14, "type": "int"},
    },
    field_ranges={"CCI": (-500, 500)},
    category="trend",
)
def compute_cci(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import CCIIndicator
    length = params.get("length", 14)
    cci = CCIIndicator(df["high"], df["low"], df["close"], window=length)
    return pd.DataFrame({f"CCI_{length}": cci.cci()}, index=df.index)


@register_factor(
    name="AROON",
    label="阿隆指标",
    sub_fields=[
        ("AROON_up", "阿隆上升"),
        ("AROON_down", "阿隆下降"),
        ("AROON_osc", "阿隆振荡"),
    ],
    params={
        "length": {"label": "周期", "default": 25, "type": "int"},
    },
    category="trend",
)
def compute_aroon(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import AroonIndicator
    length = params.get("length", 25)
    ar = AroonIndicator(df["high"], df["low"], window=length)
    s = f"_{length}"
    return pd.DataFrame({
        f"AROON_up{s}": ar.aroon_up(),
        f"AROON_down{s}": ar.aroon_down(),
        f"AROON_osc{s}": ar.aroon_indicator(),
    }, index=df.index)


@register_factor(
    name="ICHIMOKU",
    label="一目均衡表",
    sub_fields=[
        ("ICHIMOKU_conv", "转换线"),
        ("ICHIMOKU_base", "基准线"),
        ("ICHIMOKU_a", "先行带A"),
        ("ICHIMOKU_b", "先行带B"),
    ],
    params={
        "window1": {"label": "转换周期", "default": 9, "type": "int"},
        "window2": {"label": "基准周期", "default": 26, "type": "int"},
        "window3": {"label": "先行带B周期", "default": 52, "type": "int"},
    },
    category="trend",
)
def compute_ichimoku(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import IchimokuIndicator
    w1 = params.get("window1", 9)
    w2 = params.get("window2", 26)
    w3 = params.get("window3", 52)
    ich = IchimokuIndicator(df["high"], df["low"], window1=w1, window2=w2, window3=w3)
    s = f"_{w1}_{w2}_{w3}"
    return pd.DataFrame({
        f"ICHIMOKU_conv{s}": ich.ichimoku_conversion_line(),
        f"ICHIMOKU_base{s}": ich.ichimoku_base_line(),
        f"ICHIMOKU_a{s}": ich.ichimoku_a(),
        f"ICHIMOKU_b{s}": ich.ichimoku_b(),
    }, index=df.index)


@register_factor(
    name="KST",
    label="确然指标",
    sub_fields=[
        ("KST", "KST"),
        ("KST_sig", "KST信号线"),
        ("KST_diff", "KST差值"),
    ],
    params={
        "nsig": {"label": "信号周期", "default": 9, "type": "int"},
    },
    category="trend",
)
def compute_kst(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import KSTIndicator
    nsig = params.get("nsig", 9)
    kst = KSTIndicator(df["close"], nsig=nsig)
    s = f"_{nsig}"
    return pd.DataFrame({
        f"KST{s}": kst.kst(),
        f"KST_sig{s}": kst.kst_sig(),
        f"KST_diff{s}": kst.kst_diff(),
    }, index=df.index)


@register_factor(
    name="MASS",
    label="梅斯线",
    sub_fields=[("MASS", "梅斯线")],
    params={
        "fast": {"label": "快周期", "default": 9, "type": "int"},
        "slow": {"label": "慢周期", "default": 25, "type": "int"},
    },
    category="trend",
)
def compute_mass(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import MassIndex
    fast = params.get("fast", 9)
    slow = params.get("slow", 25)
    mi = MassIndex(df["high"], df["low"], window_fast=fast, window_slow=slow)
    s = f"_{fast}_{slow}"
    return pd.DataFrame({f"MASS{s}": mi.mass_index()}, index=df.index)


@register_factor(
    name="PSAR",
    label="抛物线SAR",
    sub_fields=[("PSAR", "SAR值")],
    params={
        "step": {"label": "加速因子", "default": 0.02, "type": "float"},
        "max_step": {"label": "最大加速", "default": 0.2, "type": "float"},
    },
    category="trend",
)
def compute_psar(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import PSARIndicator
    step = params.get("step", 0.02)
    max_step = params.get("max_step", 0.2)
    psar = PSARIndicator(df["high"], df["low"], df["close"],
                         step=step, max_step=max_step)
    s = f"_{step}_{max_step}"
    return pd.DataFrame({f"PSAR{s}": psar.psar()}, index=df.index)


@register_factor(
    name="STC",
    label="Schaff趋势周期",
    sub_fields=[("STC", "STC")],
    params={
        "fast": {"label": "快周期", "default": 23, "type": "int"},
        "slow": {"label": "慢周期", "default": 50, "type": "int"},
        "cycle": {"label": "周期", "default": 10, "type": "int"},
    },
    category="trend",
)
def compute_stc(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import STCIndicator
    fast = params.get("fast", 23)
    slow = params.get("slow", 50)
    cycle = params.get("cycle", 10)
    stc = STCIndicator(df["close"], window_fast=fast, window_slow=slow, cycle=cycle)
    s = f"_{fast}_{slow}_{cycle}"
    return pd.DataFrame({f"STC{s}": stc.stc()}, index=df.index)


@register_factor(
    name="VORTEX",
    label="涡旋指标",
    sub_fields=[
        ("VORTEX_pos", "VI+"),
        ("VORTEX_neg", "VI-"),
        ("VORTEX_diff", "涡旋差值"),
    ],
    params={
        "length": {"label": "周期", "default": 14, "type": "int"},
    },
    category="trend",
)
def compute_vortex(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import VortexIndicator
    length = params.get("length", 14)
    vi = VortexIndicator(df["high"], df["low"], df["close"], window=length)
    s = f"_{length}"
    return pd.DataFrame({
        f"VORTEX_pos{s}": vi.vortex_indicator_pos(),
        f"VORTEX_neg{s}": vi.vortex_indicator_neg(),
        f"VORTEX_diff{s}": vi.vortex_indicator_diff(),
    }, index=df.index)


@register_factor(
    name="WMA",
    label="加权移动均线",
    sub_fields=[("WMA", "WMA")],
    params={
        "length": {"label": "周期", "default": 9, "type": "int"},
    },
    category="trend",
)
def compute_wma(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import WMAIndicator
    length = params.get("length", 9)
    wma = WMAIndicator(df["close"], window=length)
    return pd.DataFrame({f"WMA_{length}": wma.wma()}, index=df.index)


@register_factor(
    name="TRIX",
    label="三重指数平滑",
    sub_fields=[("TRIX", "TRIX")],
    params={
        "length": {"label": "周期", "default": 15, "type": "int"},
    },
    category="trend",
)
def compute_trix(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import TRIXIndicator
    length = params.get("length", 15)
    trix = TRIXIndicator(df["close"], window=length)
    return pd.DataFrame({f"TRIX_{length}": trix.trix()}, index=df.index)


@register_factor(
    name="DPO",
    label="去趋势价格震荡",
    sub_fields=[("DPO", "DPO")],
    params={
        "length": {"label": "周期", "default": 20, "type": "int"},
    },
    category="trend",
)
def compute_dpo(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import DPOIndicator
    length = params.get("length", 20)
    dpo = DPOIndicator(df["close"], window=length)
    return pd.DataFrame({f"DPO_{length}": dpo.dpo()}, index=df.index)
