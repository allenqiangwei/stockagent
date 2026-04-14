"""Volume factors: VWAP, CMF, ADI, EMV, FI, NVI, VPT."""

import pandas as pd

from .registry import register_factor


@register_factor(
    name="VWAP",
    label="成交量加权均价",
    sub_fields=[("VWAP", "VWAP")],
    params={
        "length": {"label": "周期", "default": 14, "type": "int"},
    },
    category="volume",
)
def compute_vwap(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import VolumeWeightedAveragePrice
    length = params.get("length", 14)
    vwap = VolumeWeightedAveragePrice(
        df["high"], df["low"], df["close"], df["volume"], window=length,
    )
    return pd.DataFrame({f"VWAP_{length}": vwap.volume_weighted_average_price()},
                        index=df.index)


@register_factor(
    name="CMF",
    label="蔡金资金流",
    sub_fields=[("CMF", "CMF")],
    params={
        "length": {"label": "周期", "default": 20, "type": "int"},
    },
    category="volume",
)
def compute_cmf(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import ChaikinMoneyFlowIndicator
    length = params.get("length", 20)
    cmf = ChaikinMoneyFlowIndicator(df["high"], df["low"], df["close"],
                                     df["volume"], window=length)
    return pd.DataFrame({f"CMF_{length}": cmf.chaikin_money_flow()}, index=df.index)


@register_factor(
    name="ADI",
    label="累积/派发指标",
    sub_fields=[("ADI", "ADI")],
    params={},
    category="volume",
)
def compute_adi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import AccDistIndexIndicator
    adi = AccDistIndexIndicator(df["high"], df["low"], df["close"], df["volume"])
    return pd.DataFrame({"ADI": adi.acc_dist_index()}, index=df.index)


@register_factor(
    name="EMV",
    label="简易波动指标",
    sub_fields=[
        ("EMV", "EMV"),
        ("EMV_sma", "EMV均线"),
    ],
    params={
        "length": {"label": "周期", "default": 14, "type": "int"},
    },
    category="volume",
)
def compute_emv(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import EaseOfMovementIndicator
    length = params.get("length", 14)
    emv = EaseOfMovementIndicator(df["high"], df["low"], df["volume"], window=length)
    s = f"_{length}"
    return pd.DataFrame({
        f"EMV{s}": emv.ease_of_movement(),
        f"EMV_sma{s}": emv.sma_ease_of_movement(),
    }, index=df.index)


@register_factor(
    name="FI",
    label="力量指标",
    sub_fields=[("FI", "力量指标")],
    params={
        "length": {"label": "周期", "default": 13, "type": "int"},
    },
    category="volume",
)
def compute_fi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import ForceIndexIndicator
    length = params.get("length", 13)
    fi = ForceIndexIndicator(df["close"], df["volume"], window=length)
    return pd.DataFrame({f"FI_{length}": fi.force_index()}, index=df.index)


@register_factor(
    name="NVI",
    label="负量指标",
    sub_fields=[("NVI", "NVI")],
    params={},
    category="volume",
)
def compute_nvi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import NegativeVolumeIndexIndicator
    nvi = NegativeVolumeIndexIndicator(df["close"], df["volume"])
    return pd.DataFrame({"NVI": nvi.negative_volume_index()}, index=df.index)


@register_factor(
    name="VPT",
    label="量价趋势",
    sub_fields=[("VPT", "VPT")],
    params={},
    category="volume",
)
def compute_vpt(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import VolumePriceTrendIndicator
    vpt = VolumePriceTrendIndicator(df["close"], df["volume"])
    return pd.DataFrame({"VPT": vpt.volume_price_trend()}, index=df.index)
