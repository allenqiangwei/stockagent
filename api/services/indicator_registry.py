"""Dynamic indicator registry — maps indicator names to ta library calculations.

Extends the existing 9 built-in indicators (RSI, MACD, KDJ, MA, EMA, ADX, OBV, ATR, PRICE)
with 33 additional indicators from the `ta` library, providing 41+ indicator groups
and 80+ individual fields for strategy generation.

The registry provides:
1. Indicator metadata (sub_fields, params, labels) for the rule engine
2. Calculation functions that produce named DataFrame columns
3. Dynamic registration into INDICATOR_GROUPS for condition validation
"""

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ── Extended indicator definitions ────────────────────────
# Each entry defines: label, sub_fields, params.
# Column naming convention: {field}_{param1}_{param2}_...
# Params with no entries → column name = field name (no suffix).

EXTENDED_INDICATORS: dict[str, dict[str, Any]] = {

    # ── Volatility ────────────────────────────────────────

    "BOLL": {
        "label": "布林带",
        "sub_fields": [
            ("BOLL_upper", "布林上轨"),
            ("BOLL_middle", "布林中轨"),
            ("BOLL_lower", "布林下轨"),
            ("BOLL_pband", "布林%B"),
            ("BOLL_wband", "布林带宽"),
        ],
        "params": {
            "length": {"label": "周期", "default": 20, "type": "int"},
            "std": {"label": "标准差倍数", "default": 2.0, "type": "float"},
        },
    },
    "DONCHIAN": {
        "label": "唐奇安通道",
        "sub_fields": [
            ("DONCHIAN_upper", "唐奇安上轨"),
            ("DONCHIAN_lower", "唐奇安下轨"),
            ("DONCHIAN_middle", "唐奇安中轨"),
        ],
        "params": {
            "length": {"label": "周期", "default": 20, "type": "int"},
        },
    },
    "KELTNER": {
        "label": "肯特纳通道",
        "sub_fields": [
            ("KELTNER_upper", "肯特纳上轨"),
            ("KELTNER_lower", "肯特纳下轨"),
            ("KELTNER_middle", "肯特纳中轨"),
        ],
        "params": {
            "length": {"label": "周期", "default": 20, "type": "int"},
            "length_atr": {"label": "ATR周期", "default": 10, "type": "int"},
        },
    },
    "ULCER": {
        "label": "溃疡指数",
        "sub_fields": [("ULCER", "溃疡指数")],
        "params": {
            "length": {"label": "周期", "default": 14, "type": "int"},
        },
    },

    # ── Trend ─────────────────────────────────────────────

    "CCI": {
        "label": "CCI顺势指标",
        "sub_fields": [("CCI", "CCI")],
        "params": {
            "length": {"label": "周期", "default": 14, "type": "int"},
        },
    },
    "AROON": {
        "label": "阿隆指标",
        "sub_fields": [
            ("AROON_up", "阿隆上升"),
            ("AROON_down", "阿隆下降"),
            ("AROON_osc", "阿隆振荡"),
        ],
        "params": {
            "length": {"label": "周期", "default": 25, "type": "int"},
        },
    },
    "ICHIMOKU": {
        "label": "一目均衡表",
        "sub_fields": [
            ("ICHIMOKU_conv", "转换线"),
            ("ICHIMOKU_base", "基准线"),
            ("ICHIMOKU_a", "先行带A"),
            ("ICHIMOKU_b", "先行带B"),
        ],
        "params": {
            "window1": {"label": "转换周期", "default": 9, "type": "int"},
            "window2": {"label": "基准周期", "default": 26, "type": "int"},
            "window3": {"label": "先行带B周期", "default": 52, "type": "int"},
        },
    },
    "KST": {
        "label": "确然指标",
        "sub_fields": [
            ("KST", "KST"),
            ("KST_sig", "KST信号线"),
            ("KST_diff", "KST差值"),
        ],
        "params": {
            "nsig": {"label": "信号周期", "default": 9, "type": "int"},
        },
    },
    "MASS": {
        "label": "梅斯线",
        "sub_fields": [("MASS", "梅斯线")],
        "params": {
            "fast": {"label": "快周期", "default": 9, "type": "int"},
            "slow": {"label": "慢周期", "default": 25, "type": "int"},
        },
    },
    "PSAR": {
        "label": "抛物线SAR",
        "sub_fields": [("PSAR", "SAR值")],
        "params": {
            "step": {"label": "加速因子", "default": 0.02, "type": "float"},
            "max_step": {"label": "最大加速", "default": 0.2, "type": "float"},
        },
    },
    "STC": {
        "label": "Schaff趋势周期",
        "sub_fields": [("STC", "STC")],
        "params": {
            "fast": {"label": "快周期", "default": 23, "type": "int"},
            "slow": {"label": "慢周期", "default": 50, "type": "int"},
            "cycle": {"label": "周期", "default": 10, "type": "int"},
        },
    },
    "VORTEX": {
        "label": "涡旋指标",
        "sub_fields": [
            ("VORTEX_pos", "VI+"),
            ("VORTEX_neg", "VI-"),
            ("VORTEX_diff", "涡旋差值"),
        ],
        "params": {
            "length": {"label": "周期", "default": 14, "type": "int"},
        },
    },
    "WMA": {
        "label": "加权移动均线",
        "sub_fields": [("WMA", "WMA")],
        "params": {
            "length": {"label": "周期", "default": 9, "type": "int"},
        },
    },
    "TRIX": {
        "label": "三重指数平滑",
        "sub_fields": [("TRIX", "TRIX")],
        "params": {
            "length": {"label": "周期", "default": 15, "type": "int"},
        },
    },
    "DPO": {
        "label": "去趋势价格震荡",
        "sub_fields": [("DPO", "DPO")],
        "params": {
            "length": {"label": "周期", "default": 20, "type": "int"},
        },
    },

    # ── Momentum ──────────────────────────────────────────

    "ROC": {
        "label": "变动率",
        "sub_fields": [("ROC", "变动率")],
        "params": {
            "length": {"label": "周期", "default": 12, "type": "int"},
        },
    },
    "WR": {
        "label": "威廉指标",
        "sub_fields": [("WR", "威廉指标")],
        "params": {
            "length": {"label": "周期", "default": 14, "type": "int"},
        },
    },
    "MFI": {
        "label": "资金流量指标",
        "sub_fields": [("MFI", "MFI")],
        "params": {
            "length": {"label": "周期", "default": 14, "type": "int"},
        },
    },
    "STOCHRSI": {
        "label": "随机RSI",
        "sub_fields": [
            ("STOCHRSI_K", "StochRSI_K"),
            ("STOCHRSI_D", "StochRSI_D"),
        ],
        "params": {
            "length": {"label": "RSI周期", "default": 14, "type": "int"},
            "smooth_k": {"label": "K平滑", "default": 3, "type": "int"},
            "smooth_d": {"label": "D平滑", "default": 3, "type": "int"},
        },
    },
    "STOCH": {
        "label": "随机震荡指标",
        "sub_fields": [
            ("STOCH_K", "Stoch_K"),
            ("STOCH_D", "Stoch_D"),
        ],
        "params": {
            "length": {"label": "周期", "default": 14, "type": "int"},
            "smooth": {"label": "平滑", "default": 3, "type": "int"},
        },
    },
    "AO": {
        "label": "动量震荡器",
        "sub_fields": [("AO", "AO")],
        "params": {
            "fast": {"label": "快周期", "default": 5, "type": "int"},
            "slow": {"label": "慢周期", "default": 34, "type": "int"},
        },
    },
    "KAMA": {
        "label": "考夫曼自适应均线",
        "sub_fields": [("KAMA", "KAMA")],
        "params": {
            "length": {"label": "周期", "default": 10, "type": "int"},
        },
    },
    "PPO": {
        "label": "价格震荡百分比",
        "sub_fields": [
            ("PPO", "PPO"),
            ("PPO_signal", "PPO信号线"),
            ("PPO_hist", "PPO柱线"),
        ],
        "params": {
            "fast": {"label": "快周期", "default": 12, "type": "int"},
            "slow": {"label": "慢周期", "default": 26, "type": "int"},
            "signal": {"label": "信号周期", "default": 9, "type": "int"},
        },
    },
    "PVO": {
        "label": "成交量震荡百分比",
        "sub_fields": [
            ("PVO", "PVO"),
            ("PVO_signal", "PVO信号线"),
            ("PVO_hist", "PVO柱线"),
        ],
        "params": {
            "fast": {"label": "快周期", "default": 12, "type": "int"},
            "slow": {"label": "慢周期", "default": 26, "type": "int"},
            "signal": {"label": "信号周期", "default": 9, "type": "int"},
        },
    },
    "TSI": {
        "label": "真实强度指数",
        "sub_fields": [("TSI", "TSI")],
        "params": {
            "fast": {"label": "快周期", "default": 13, "type": "int"},
            "slow": {"label": "慢周期", "default": 25, "type": "int"},
        },
    },
    "ULTOSC": {
        "label": "终极震荡指标",
        "sub_fields": [("ULTOSC", "终极震荡")],
        "params": {
            "w1": {"label": "短周期", "default": 7, "type": "int"},
            "w2": {"label": "中周期", "default": 14, "type": "int"},
            "w3": {"label": "长周期", "default": 28, "type": "int"},
        },
    },

    # ── Volume ────────────────────────────────────────────

    "VWAP": {
        "label": "成交量加权均价",
        "sub_fields": [("VWAP", "VWAP")],
        "params": {
            "length": {"label": "周期", "default": 14, "type": "int"},
        },
    },
    "CMF": {
        "label": "蔡金资金流",
        "sub_fields": [("CMF", "CMF")],
        "params": {
            "length": {"label": "周期", "default": 20, "type": "int"},
        },
    },
    "ADI": {
        "label": "累积/派发指标",
        "sub_fields": [("ADI", "ADI")],
        "params": {},
    },
    "EMV": {
        "label": "简易波动指标",
        "sub_fields": [
            ("EMV", "EMV"),
            ("EMV_sma", "EMV均线"),
        ],
        "params": {
            "length": {"label": "周期", "default": 14, "type": "int"},
        },
    },
    "FI": {
        "label": "力量指标",
        "sub_fields": [("FI", "力量指标")],
        "params": {
            "length": {"label": "周期", "default": 13, "type": "int"},
        },
    },
    "NVI": {
        "label": "负量指标",
        "sub_fields": [("NVI", "NVI")],
        "params": {},
    },
    "VPT": {
        "label": "量价趋势",
        "sub_fields": [("VPT", "VPT")],
        "params": {},
    },

    # ── Sentiment (exogenous — not computed from OHLCV) ────
    "NEWS_SENTIMENT": {
        "label": "新闻情绪",
        "sub_fields": [
            ("NEWS_SENTIMENT_3D", "3日新闻情绪"),
            ("NEWS_SENTIMENT_7D", "7日新闻情绪"),
        ],
        "params": {},
    },

    # ── Quantitative Factors ─────────────────────────────────

    "MOM": {
        "label": "动量",
        "sub_fields": [("MOM", "动量%")],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
    "REALVOL": {
        "label": "已实现波动率",
        "sub_fields": [
            ("REALVOL", "波动率%"),
            ("REALVOL_skew", "收益偏度"),
            ("REALVOL_kurt", "收益峰度"),
            ("REALVOL_downside", "下行波动率%"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
    "KBAR": {
        "label": "K线形态",
        "sub_fields": [
            ("KBAR_upper_shadow", "上影线比率"),
            ("KBAR_lower_shadow", "下影线比率"),
            ("KBAR_body_ratio", "实体比率"),
            ("KBAR_amplitude", "振幅"),
            ("KBAR_overnight_ret", "隔夜收益率%"),
            ("KBAR_intraday_ret", "日内收益率%"),
        ],
        "params": {},
    },
    "PVOL": {
        "label": "量价关系",
        "sub_fields": [
            ("PVOL_corr", "量价相关性"),
            ("PVOL_amount_conc", "成交额集中度"),
            ("PVOL_vwap_bias", "VWAP偏离度%"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
    "LIQ": {
        "label": "流动性",
        "sub_fields": [
            ("LIQ_amihud", "Amihud非流动性"),
            ("LIQ_turnover_vol", "换手波动率"),
            ("LIQ_log_amount", "对数成交额"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
    "PPOS": {
        "label": "价格位置",
        "sub_fields": [
            ("PPOS_close_pos", "收盘价位置(0-1)"),
            ("PPOS_high_dist", "距N日高点%"),
            ("PPOS_low_dist", "距N日低点%"),
            ("PPOS_drawdown", "N日最大回撤%"),
            ("PPOS_consec_dir", "连涨/跌天数"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
    "RSTR": {
        "label": "相对强弱",
        "sub_fields": [
            ("RSTR", "N日收益率%"),
            ("RSTR_weighted", "加权动量"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 20, "type": "int"},
        },
    },
    "AMPVOL": {
        "label": "振幅波动",
        "sub_fields": [
            ("AMPVOL_std", "振幅标准差"),
            ("AMPVOL_parkinson", "Parkinson波动率"),
        ],
        "params": {
            "period": {"label": "回看周期", "default": 5, "type": "int"},
        },
    },
}


# ── Compute functions ─────────────────────────────────────
# Each function takes (df, params) and returns pd.DataFrame with named columns.
# Column names MUST match the pattern: {sub_field}_{param_suffix}


def _make_suffix(params: dict, keys: list[str]) -> str:
    """Build column suffix from param values. E.g., keys=["length"] → "_14"."""
    if not keys:
        return ""
    return "_" + "_".join(str(params[k]) for k in keys)


# ── Volatility ──

def _compute_boll(df: pd.DataFrame, params: dict) -> pd.DataFrame:
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


def _compute_donchian(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volatility import DonchianChannel
    length = params.get("length", 20)
    dc = DonchianChannel(df["high"], df["low"], df["close"], window=length)
    s = f"_{length}"
    return pd.DataFrame({
        f"DONCHIAN_upper{s}": dc.donchian_channel_hband(),
        f"DONCHIAN_lower{s}": dc.donchian_channel_lband(),
        f"DONCHIAN_middle{s}": dc.donchian_channel_mband(),
    }, index=df.index)


def _compute_keltner(df: pd.DataFrame, params: dict) -> pd.DataFrame:
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


def _compute_ulcer(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volatility import UlcerIndex
    length = params.get("length", 14)
    ui = UlcerIndex(df["close"], window=length)
    return pd.DataFrame({f"ULCER_{length}": ui.ulcer_index()}, index=df.index)


# ── Trend ──

def _compute_cci(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import CCIIndicator
    length = params.get("length", 14)
    cci = CCIIndicator(df["high"], df["low"], df["close"], window=length)
    return pd.DataFrame({f"CCI_{length}": cci.cci()}, index=df.index)


def _compute_aroon(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import AroonIndicator
    length = params.get("length", 25)
    ar = AroonIndicator(df["high"], df["low"], window=length)
    s = f"_{length}"
    return pd.DataFrame({
        f"AROON_up{s}": ar.aroon_up(),
        f"AROON_down{s}": ar.aroon_down(),
        f"AROON_osc{s}": ar.aroon_indicator(),
    }, index=df.index)


def _compute_ichimoku(df: pd.DataFrame, params: dict) -> pd.DataFrame:
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


def _compute_kst(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import KSTIndicator
    nsig = params.get("nsig", 9)
    kst = KSTIndicator(df["close"], nsig=nsig)
    s = f"_{nsig}"
    return pd.DataFrame({
        f"KST{s}": kst.kst(),
        f"KST_sig{s}": kst.kst_sig(),
        f"KST_diff{s}": kst.kst_diff(),
    }, index=df.index)


def _compute_mass(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import MassIndex
    fast = params.get("fast", 9)
    slow = params.get("slow", 25)
    mi = MassIndex(df["high"], df["low"], window_fast=fast, window_slow=slow)
    s = f"_{fast}_{slow}"
    return pd.DataFrame({f"MASS{s}": mi.mass_index()}, index=df.index)


def _compute_psar(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import PSARIndicator
    step = params.get("step", 0.02)
    max_step = params.get("max_step", 0.2)
    psar = PSARIndicator(df["high"], df["low"], df["close"],
                         step=step, max_step=max_step)
    s = f"_{step}_{max_step}"
    return pd.DataFrame({f"PSAR{s}": psar.psar()}, index=df.index)


def _compute_stc(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import STCIndicator
    fast = params.get("fast", 23)
    slow = params.get("slow", 50)
    cycle = params.get("cycle", 10)
    stc = STCIndicator(df["close"], window_fast=fast, window_slow=slow, cycle=cycle)
    s = f"_{fast}_{slow}_{cycle}"
    return pd.DataFrame({f"STC{s}": stc.stc()}, index=df.index)


def _compute_vortex(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import VortexIndicator
    length = params.get("length", 14)
    vi = VortexIndicator(df["high"], df["low"], df["close"], window=length)
    s = f"_{length}"
    return pd.DataFrame({
        f"VORTEX_pos{s}": vi.vortex_indicator_pos(),
        f"VORTEX_neg{s}": vi.vortex_indicator_neg(),
        f"VORTEX_diff{s}": vi.vortex_indicator_diff(),
    }, index=df.index)


def _compute_wma(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import WMAIndicator
    length = params.get("length", 9)
    wma = WMAIndicator(df["close"], window=length)
    return pd.DataFrame({f"WMA_{length}": wma.wma()}, index=df.index)


def _compute_trix(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import TRIXIndicator
    length = params.get("length", 15)
    trix = TRIXIndicator(df["close"], window=length)
    return pd.DataFrame({f"TRIX_{length}": trix.trix()}, index=df.index)


def _compute_dpo(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.trend import DPOIndicator
    length = params.get("length", 20)
    dpo = DPOIndicator(df["close"], window=length)
    return pd.DataFrame({f"DPO_{length}": dpo.dpo()}, index=df.index)


# ── Momentum ──

def _compute_roc(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import ROCIndicator
    length = params.get("length", 12)
    roc = ROCIndicator(df["close"], window=length)
    return pd.DataFrame({f"ROC_{length}": roc.roc()}, index=df.index)


def _compute_wr(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import WilliamsRIndicator
    length = params.get("length", 14)
    wr = WilliamsRIndicator(df["high"], df["low"], df["close"], lbp=length)
    return pd.DataFrame({f"WR_{length}": wr.williams_r()}, index=df.index)


def _compute_mfi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import MFIIndicator
    length = params.get("length", 14)
    mfi = MFIIndicator(df["high"], df["low"], df["close"], df["volume"], window=length)
    return pd.DataFrame({f"MFI_{length}": mfi.money_flow_index()}, index=df.index)


def _compute_stochrsi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
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


def _compute_stoch(df: pd.DataFrame, params: dict) -> pd.DataFrame:
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


def _compute_ao(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import AwesomeOscillatorIndicator
    fast = params.get("fast", 5)
    slow = params.get("slow", 34)
    ao = AwesomeOscillatorIndicator(df["high"], df["low"],
                                    window1=fast, window2=slow)
    s = f"_{fast}_{slow}"
    return pd.DataFrame({f"AO{s}": ao.awesome_oscillator()}, index=df.index)


def _compute_kama(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import KAMAIndicator
    length = params.get("length", 10)
    kama = KAMAIndicator(df["close"], window=length)
    return pd.DataFrame({f"KAMA_{length}": kama.kama()}, index=df.index)


def _compute_ppo(df: pd.DataFrame, params: dict) -> pd.DataFrame:
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


def _compute_pvo(df: pd.DataFrame, params: dict) -> pd.DataFrame:
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


def _compute_tsi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import TSIIndicator
    fast = params.get("fast", 13)
    slow = params.get("slow", 25)
    tsi = TSIIndicator(df["close"], window_fast=fast, window_slow=slow)
    s = f"_{fast}_{slow}"
    return pd.DataFrame({f"TSI{s}": tsi.tsi()}, index=df.index)


def _compute_ultosc(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.momentum import UltimateOscillator
    w1 = params.get("w1", 7)
    w2 = params.get("w2", 14)
    w3 = params.get("w3", 28)
    uo = UltimateOscillator(df["high"], df["low"], df["close"],
                            window1=w1, window2=w2, window3=w3)
    s = f"_{w1}_{w2}_{w3}"
    return pd.DataFrame({f"ULTOSC{s}": uo.ultimate_oscillator()}, index=df.index)


# ── Volume ──

def _compute_vwap(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import VolumeWeightedAveragePrice
    length = params.get("length", 14)
    vwap = VolumeWeightedAveragePrice(
        df["high"], df["low"], df["close"], df["volume"], window=length,
    )
    return pd.DataFrame({f"VWAP_{length}": vwap.volume_weighted_average_price()},
                        index=df.index)


def _compute_cmf(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import ChaikinMoneyFlowIndicator
    length = params.get("length", 20)
    cmf = ChaikinMoneyFlowIndicator(df["high"], df["low"], df["close"],
                                     df["volume"], window=length)
    return pd.DataFrame({f"CMF_{length}": cmf.chaikin_money_flow()}, index=df.index)


def _compute_adi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import AccDistIndexIndicator
    adi = AccDistIndexIndicator(df["high"], df["low"], df["close"], df["volume"])
    return pd.DataFrame({"ADI": adi.acc_dist_index()}, index=df.index)


def _compute_emv(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import EaseOfMovementIndicator
    length = params.get("length", 14)
    emv = EaseOfMovementIndicator(df["high"], df["low"], df["volume"], window=length)
    s = f"_{length}"
    return pd.DataFrame({
        f"EMV{s}": emv.ease_of_movement(),
        f"EMV_sma{s}": emv.sma_ease_of_movement(),
    }, index=df.index)


def _compute_fi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import ForceIndexIndicator
    length = params.get("length", 13)
    fi = ForceIndexIndicator(df["close"], df["volume"], window=length)
    return pd.DataFrame({f"FI_{length}": fi.force_index()}, index=df.index)


def _compute_nvi(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import NegativeVolumeIndexIndicator
    nvi = NegativeVolumeIndexIndicator(df["close"], df["volume"])
    return pd.DataFrame({"NVI": nvi.negative_volume_index()}, index=df.index)


def _compute_vpt(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    from ta.volume import VolumePriceTrendIndicator
    vpt = VolumePriceTrendIndicator(df["close"], df["volume"])
    return pd.DataFrame({"VPT": vpt.volume_price_trend()}, index=df.index)


# ── Sentiment (placeholder — actual values injected by signal_engine) ──

def _compute_news_sentiment(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
    return pd.DataFrame({
        "NEWS_SENTIMENT_3D": pd.Series(np.nan, index=df.index),
        "NEWS_SENTIMENT_7D": pd.Series(np.nan, index=df.index),
    })


# ── Quantitative Factors ──

def _compute_mom(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
    period = params.get("period", 20)
    shifted = df["close"].shift(period)
    mom = (df["close"] - shifted) / shifted.replace(0, np.nan) * 100
    return pd.DataFrame({f"MOM_{period}": mom}, index=df.index)


def _compute_realvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
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


def _compute_kbar(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
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


def _compute_pvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
    period = params.get("period", 20)
    s = f"_{period}"
    returns = df["close"].pct_change()
    corr = returns.rolling(period).corr(df["volume"])
    amount_max = df["amount"].rolling(period).max()
    amount_sum = df["amount"].rolling(period).sum().replace(0, np.nan)
    amount_conc = amount_max / amount_sum
    vwap_amount_sum = df["amount"].rolling(period).sum()
    vwap_volume_sum = df["volume"].rolling(period).sum().replace(0, np.nan)
    vwap = vwap_amount_sum / vwap_volume_sum
    vwap_bias = (df["close"] - vwap) / vwap.replace(0, np.nan) * 100
    return pd.DataFrame({
        f"PVOL_corr{s}": corr,
        f"PVOL_amount_conc{s}": amount_conc,
        f"PVOL_vwap_bias{s}": vwap_bias,
    }, index=df.index)


def _compute_liq(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
    period = params.get("period", 20)
    s = f"_{period}"
    returns = df["close"].pct_change()
    illiq = returns.abs() / df["amount"].replace(0, np.nan)
    amihud = illiq.rolling(period).mean() * 1e9
    vol_mean = df["volume"].rolling(period).mean().replace(0, np.nan)
    vol_std = df["volume"].rolling(period).std()
    turnover_vol = vol_std / vol_mean
    log_amount = np.log1p(df["amount"].rolling(period).mean())
    return pd.DataFrame({
        f"LIQ_amihud{s}": amihud,
        f"LIQ_turnover_vol{s}": turnover_vol,
        f"LIQ_log_amount{s}": log_amount,
    }, index=df.index)


def _compute_ppos(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
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


def _compute_rstr(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
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


def _compute_ampvol(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    import numpy as np
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


# ── Compute function map ──────────────────────────────────

_COMPUTE_FUNCTIONS: dict[str, callable] = {
    # Volatility
    "BOLL": _compute_boll,
    "DONCHIAN": _compute_donchian,
    "KELTNER": _compute_keltner,
    "ULCER": _compute_ulcer,
    # Trend
    "CCI": _compute_cci,
    "AROON": _compute_aroon,
    "ICHIMOKU": _compute_ichimoku,
    "KST": _compute_kst,
    "MASS": _compute_mass,
    "PSAR": _compute_psar,
    "STC": _compute_stc,
    "VORTEX": _compute_vortex,
    "WMA": _compute_wma,
    "TRIX": _compute_trix,
    "DPO": _compute_dpo,
    # Momentum
    "ROC": _compute_roc,
    "WR": _compute_wr,
    "MFI": _compute_mfi,
    "STOCHRSI": _compute_stochrsi,
    "STOCH": _compute_stoch,
    "AO": _compute_ao,
    "KAMA": _compute_kama,
    "PPO": _compute_ppo,
    "PVO": _compute_pvo,
    "TSI": _compute_tsi,
    "ULTOSC": _compute_ultosc,
    # Volume
    "VWAP": _compute_vwap,
    "CMF": _compute_cmf,
    "ADI": _compute_adi,
    "EMV": _compute_emv,
    "FI": _compute_fi,
    "NVI": _compute_nvi,
    "VPT": _compute_vpt,
    # Sentiment
    "NEWS_SENTIMENT": _compute_news_sentiment,
    # Quantitative Factors
    "MOM": _compute_mom,
    "REALVOL": _compute_realvol,
    "KBAR": _compute_kbar,
    "PVOL": _compute_pvol,
    "LIQ": _compute_liq,
    "PPOS": _compute_ppos,
    "RSTR": _compute_rstr,
    "AMPVOL": _compute_ampvol,
}


# ── Column name resolution for extended indicators ────────

def resolve_extended_column(field: str, params: dict | None = None) -> str | None:
    """Resolve an extended indicator field + params to a DataFrame column name.

    Uses a generic approach: builds suffix from all param values in definition order.
    Returns None if not an extended indicator.
    """
    group = get_extended_field_group(field)
    if group is None:
        return None

    meta = EXTENDED_INDICATORS[group]
    if not meta["params"]:
        # No params → column name is just the field name (ADI, NVI, VPT)
        return field

    defaults = {k: v["default"] for k, v in meta["params"].items()}
    effective = dict(defaults)
    if params:
        effective.update(params)

    # Build suffix from all param values in definition order
    suffix = "_" + "_".join(str(effective[k]) for k in meta["params"])
    return f"{field}{suffix}"


def get_extended_field_group(field: str) -> str | None:
    """Find the extended indicator group for a given field name."""
    for group_name, meta in EXTENDED_INDICATORS.items():
        for sub_field, _ in meta["sub_fields"]:
            if sub_field == field:
                return group_name
    return None


def compute_extended_indicator(
    df: pd.DataFrame, group: str, params: dict | None = None,
) -> pd.DataFrame:
    """Compute an extended indicator and return its columns as a DataFrame."""
    if group not in _COMPUTE_FUNCTIONS:
        raise ValueError(f"No compute function for extended indicator: {group}")

    meta = EXTENDED_INDICATORS[group]
    defaults = {k: v["default"] for k, v in meta["params"].items()}
    effective = dict(defaults)
    if params:
        effective.update(params)

    return _COMPUTE_FUNCTIONS[group](df, effective)


def is_extended_indicator(field: str) -> bool:
    """Check if a field belongs to an extended indicator."""
    return get_extended_field_group(field) is not None


def get_all_fields() -> list[str]:
    """Get all available field names (built-in + extended)."""
    from src.signals.rule_engine import INDICATOR_GROUPS

    fields = []
    for group_def in INDICATOR_GROUPS.values():
        for sub_field, _ in group_def["sub_fields"]:
            fields.append(sub_field)
    for meta in EXTENDED_INDICATORS.values():
        for sub_field, _ in meta["sub_fields"]:
            fields.append(sub_field)
    return fields


def get_all_indicator_docs() -> str:
    """Build a documentation string of all indicators for AI prompts."""
    from src.signals.rule_engine import INDICATOR_GROUPS

    lines = []
    seen = set()

    # Built-in indicators (may include already-registered extended ones)
    for group_name, group_def in INDICATOR_GROUPS.items():
        seen.add(group_name)
        fields_str = ", ".join(f'"{sf}"' for sf, _ in group_def["sub_fields"])
        params_str = ", ".join(
            f'{k}(默认{v["default"]})'
            for k, v in group_def["params"].items()
        ) if group_def["params"] else "无参数"
        lines.append(f"- **{group_def['label']}** ({group_name}): 字段=[{fields_str}], 参数=[{params_str}]")

    # Extended indicators not yet registered into INDICATOR_GROUPS
    for group_name, meta in EXTENDED_INDICATORS.items():
        if group_name in seen:
            continue
        fields_str = ", ".join(f'"{sf}"' for sf, _ in meta["sub_fields"])
        params_str = ", ".join(
            f'{k}(默认{v["default"]})'
            for k, v in meta["params"].items()
        ) if meta["params"] else "无参数"
        lines.append(f"- **{meta['label']}** ({group_name}): 字段=[{fields_str}], 参数=[{params_str}]")

    # Multi-timeframe support
    lines.append("")
    lines.append("## 多周期指标 (Multi-Timeframe)")
    lines.append("以上所有指标均可加 W_ (周线) 或 M_ (月线) 前缀，在更大周期上计算后向前填充到日线。")
    lines.append("- 周线指标: 字段名前加 `W_`，如 `W_RSI`(周线RSI)、`W_EMA`(周线EMA)、`W_ATR`(周线ATR)")
    lines.append("- 月线指标: 字段名前加 `M_`，如 `M_RSI`(月线RSI)、`M_EMA`(月线EMA)")
    lines.append("- 参数格式与日线完全相同，如 {\"field\": \"W_RSI\", \"params\": {\"period\": 14}, ...}")
    lines.append("- 可与日线指标混合使用，实现多周期过滤（如：日线RSI超卖 + 周线趋势向上）")
    lines.append("- 周线OHLCV也可直接引用: W_close, W_high, W_low, W_open")
    lines.append("- 注意: 周线指标需要约70个交易日预热, 月线需要更长, 建议优先使用周线")

    # News sentiment
    lines.append("")
    lines.append("## 新闻情绪指标 (News Sentiment)")
    lines.append("基于个股关联新闻的滚动情绪评分，取值 [-1.0, +1.0]（+1全正面, -1全负面, 0中性/无新闻）")
    lines.append("- `NEWS_SENTIMENT_3D`: 近3日新闻情绪")
    lines.append("- `NEWS_SENTIMENT_7D`: 近7日新闻情绪")
    lines.append("- 无参数，无需 W_/M_ 前缀")
    lines.append("- 仅在实盘信号生成时有效，回测中默认为NaN（条件不触发）")
    lines.append("- 示例: {\"field\": \"NEWS_SENTIMENT_3D\", \"operator\": \">\", \"compare_type\": \"value\", \"compare_value\": 0.3}")

    return "\n".join(lines)


def register_extended_indicators():
    """Register all extended indicators into the rule engine's INDICATOR_GROUPS.

    Call this at startup so validate_rule() and resolve_column_name() work
    for extended indicators too.
    """
    from src.signals.rule_engine import INDICATOR_GROUPS

    for group_name, meta in EXTENDED_INDICATORS.items():
        if group_name not in INDICATOR_GROUPS:
            INDICATOR_GROUPS[group_name] = meta
            logger.info("Registered extended indicator: %s", group_name)
