"""规则引擎：基于条件+动作模式的信号评估，支持指标参数化"""

import logging
from typing import List, Dict, Any, Tuple, Optional, Set
import pandas as pd

logger = logging.getLogger(__name__)


# ── 指标分组定义 ──────────────────────────────────────────

INDICATOR_GROUPS = {
    "RSI": {
        "label": "RSI",
        "sub_fields": [
            ("RSI", "RSI"),
        ],
        "params": {"period": {"label": "周期", "default": 14, "type": "int"}},
    },
    "MACD": {
        "label": "MACD",
        "sub_fields": [
            ("MACD", "MACD线"),
            ("MACD_signal", "MACD信号线"),
            ("MACD_hist", "MACD柱状图"),
        ],
        "params": {
            "fast": {"label": "快线周期", "default": 12, "type": "int"},
            "slow": {"label": "慢线周期", "default": 26, "type": "int"},
            "signal": {"label": "信号线周期", "default": 9, "type": "int"},
        },
    },
    "KDJ": {
        "label": "KDJ",
        "sub_fields": [
            ("KDJ_K", "KDJ-K值"),
            ("KDJ_D", "KDJ-D值"),
            ("KDJ_J", "KDJ-J值"),
        ],
        "params": {
            "fastk": {"label": "K线周期", "default": 9, "type": "int"},
            "slowk": {"label": "K线平滑", "default": 3, "type": "int"},
            "slowd": {"label": "D线平滑", "default": 3, "type": "int"},
        },
    },
    "MA": {
        "label": "MA均线",
        "sub_fields": [
            ("MA", "MA均线"),
        ],
        "params": {"period": {"label": "周期", "default": 20, "type": "int"}},
    },
    "EMA": {
        "label": "EMA均线",
        "sub_fields": [
            ("EMA", "EMA均线"),
        ],
        "params": {"period": {"label": "周期", "default": 12, "type": "int"}},
    },
    "ADX": {
        "label": "ADX趋势",
        "sub_fields": [
            ("ADX", "ADX"),
            ("ADX_plus_di", "+DI"),
            ("ADX_minus_di", "-DI"),
        ],
        "params": {"period": {"label": "周期", "default": 14, "type": "int"}},
    },
    "OBV": {
        "label": "OBV能量潮",
        "sub_fields": [
            ("OBV", "OBV能量潮"),
        ],
        "params": {},
    },
    "ATR": {
        "label": "ATR波幅",
        "sub_fields": [
            ("ATR", "ATR波幅"),
        ],
        "params": {"period": {"label": "周期", "default": 14, "type": "int"}},
    },
    "PRICE": {
        "label": "价格",
        "sub_fields": [
            ("close", "收盘价"),
            ("open", "开盘价"),
            ("high", "最高价"),
            ("low", "最低价"),
        ],
        "params": {},
    },
}

OPERATORS = [
    (">", "大于"),
    ("<", "小于"),
    (">=", "大于等于"),
    ("<=", "小于等于"),
]


# ── 默认参数 & 向后兼容 ──────────────────────────────────

def get_default_params(field: str) -> Dict[str, Any]:
    """获取指标字段的默认参数（用于旧规则兼容）"""
    group = get_field_group(field)
    if not group:
        return {}
    group_def = INDICATOR_GROUPS[group]
    return {k: v["default"] for k, v in group_def["params"].items()}


def get_field_group(field: str) -> Optional[str]:
    """查找字段所属的指标分组"""
    for group_name, group_def in INDICATOR_GROUPS.items():
        for sub_field, _ in group_def["sub_fields"]:
            if sub_field == field:
                return group_name
    return None


def get_field_label(field: str) -> str:
    """获取字段的中文标签"""
    for group_def in INDICATOR_GROUPS.values():
        for sub_field, label in group_def["sub_fields"]:
            if sub_field == field:
                return label
    return field


# ── 列名映射：(field, params) → DataFrame 实际列名 ──────

def resolve_column_name(field: str, params: Optional[Dict[str, Any]] = None) -> str:
    """将规则中的 (field, params) 映射到 DataFrame 的实际列名

    映射规则：
      - PRICE (close/open/high/low): 直接返回，无后缀
      - OBV: 直接返回
      - RSI: RSI_{period}
      - MA: MA_{period}
      - EMA: EMA_{period}
      - ADX/ADX_plus_di/ADX_minus_di: ADX_{period} / ADX_plus_di_{period} / ...
      - ATR: ATR_{period}
      - MACD/MACD_signal/MACD_hist: MACD_{fast}_{slow}_{signal} / ...
      - KDJ_K/KDJ_D/KDJ_J: KDJ_K_{fastk}_{slowk}_{slowd} / ...
      - Extended indicators (BOLL, CCI, WR, etc.): delegated to indicator_registry
    """
    # Try extended indicator registry first (handles BOLL, CCI, ICHIMOKU, AROON, etc.)
    try:
        from api.services.indicator_registry import resolve_extended_column
        result = resolve_extended_column(field, params)
        if result:
            return result
    except ImportError:
        pass

    group = get_field_group(field)
    if not group:
        return field

    # 无参数的指标直接返回
    if group in ("PRICE", "OBV"):
        return field

    # 补全默认参数
    effective_params = get_default_params(field)
    if params:
        effective_params.update(params)

    if group == "RSI":
        return f"RSI_{effective_params['period']}"
    elif group == "MA":
        return f"MA_{effective_params['period']}"
    elif group == "EMA":
        return f"EMA_{effective_params['period']}"
    elif group == "ATR":
        return f"ATR_{effective_params['period']}"
    elif group == "ADX":
        p = effective_params["period"]
        if field == "ADX":
            return f"ADX_{p}"
        elif field == "ADX_plus_di":
            return f"ADX_plus_di_{p}"
        elif field == "ADX_minus_di":
            return f"ADX_minus_di_{p}"
    elif group == "MACD":
        f_, s_, sig_ = effective_params["fast"], effective_params["slow"], effective_params["signal"]
        suffix = f"_{f_}_{s_}_{sig_}"
        if field == "MACD":
            return f"MACD{suffix}"
        elif field == "MACD_signal":
            return f"MACD_signal{suffix}"
        elif field == "MACD_hist":
            return f"MACD_hist{suffix}"
    elif group == "KDJ":
        fk, sk, sd = effective_params["fastk"], effective_params["slowk"], effective_params["slowd"]
        suffix = f"_{fk}_{sk}_{sd}"
        if field == "KDJ_K":
            return f"KDJ_K{suffix}"
        elif field == "KDJ_D":
            return f"KDJ_D{suffix}"
        elif field == "KDJ_J":
            return f"KDJ_J{suffix}"

    return field


# ── 从规则中提取所需指标参数 ──────────────────────────────

def collect_indicator_params(
    all_rules: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    """从一组规则中收集所有需要计算的指标参数组合

    Returns:
        {
            "rsi": [{"period": 14}, {"period": 7}],
            "macd": [{"fast": 12, "slow": 26, "signal": 9}],
            "ma": [{"period": 5}, {"period": 20}],
            ...
        }
    """
    seen: Dict[str, Set[str]] = {}  # group -> set of param fingerprints
    result: Dict[str, List[Dict[str, Any]]] = {}

    def _add_to_result(field_name, field_params):
        """将一个 (field, params) 加入收集结果"""
        grp = get_field_group(field_name)
        if grp and grp in ("PRICE",):
            return
        if grp and grp == "OBV":
            # OBV handled separately below
            return
        if grp:
            # Core indicator — use core defaults
            eff = get_default_params(field_name)
        else:
            # Try extended indicator registry
            from api.services.indicator_registry import (
                get_extended_field_group,
                EXTENDED_INDICATORS,
            )
            ext_grp = get_extended_field_group(field_name)
            if not ext_grp:
                return  # Unknown field, skip
            grp = ext_grp
            # Get defaults from extended indicator metadata
            meta = EXTENDED_INDICATORS[ext_grp]
            eff = {k: v["default"] for k, v in meta["params"].items()}
        if field_params:
            eff.update(field_params)
        k = grp.lower()
        fp = str(sorted(eff.items()))
        if k not in seen:
            seen[k] = set()
            result[k] = []
        if fp not in seen[k]:
            seen[k].add(fp)
            result[k].append(eff)

    for rule in all_rules:
        # 收集主字段
        _add_to_result(rule.get("field", ""), rule.get("params"))

        # 收集比较字段（无论主字段是什么类型）
        if rule.get("compare_type") == "field":
            _add_to_result(
                rule.get("compare_field", ""),
                rule.get("compare_params")
            )

        # 收集 lookback 字段
        if rule.get("lookback_field"):
            _add_to_result(
                rule.get("lookback_field", ""),
                rule.get("lookback_params", rule.get("params"))
            )

    # OBV 无参数但始终需要计算（如果有规则引用）
    for rule in all_rules:
        field = rule.get("field", "")
        if get_field_group(field) == "OBV" and "obv" not in result:
            result["obv"] = [{}]
        cf = rule.get("compare_field", "")
        if get_field_group(cf) == "OBV" and "obv" not in result:
            result["obv"] = [{}]

    return result


# ── 规则评估 ──────────────────────────────────────────────

def evaluate_rules(
    rules: List[Dict[str, Any]],
    indicator_df: pd.DataFrame,
    base_score: float = 50.0,
) -> Tuple[float, List[str]]:
    """评估一组规则，返回得分和触发原因

    规则中可带 params 字段指定指标参数，
    系统会将 (field, params) 映射到 DataFrame 的实际列名。
    """
    if indicator_df.empty:
        return base_score, []

    latest = indicator_df.iloc[-1]
    total_score = base_score
    reasons = []

    for rule in rules:
        triggered = _evaluate_single_rule(rule, latest, df_slice=indicator_df)
        if triggered:
            total_score += rule.get("score", 0)
            label = rule.get("label", "")
            if label:
                reasons.append(label)

    final_score = max(0.0, min(100.0, total_score))
    return final_score, reasons


def _evaluate_single_rule(
    rule: Dict[str, Any], row: pd.Series, df_slice: Optional[pd.DataFrame] = None
) -> bool:
    """评估单条规则是否被触发

    Args:
        rule: 规则字典
        row: 当前行（最新数据点）
        df_slice: 截止到当前行的完整 DataFrame（lookback 类型条件需要）
    """
    field = rule.get("field", "")
    operator = rule.get("operator", ">")
    compare_type = rule.get("compare_type", "value")
    params = rule.get("params")

    # 将 field+params 映射到实际列名
    col_name = resolve_column_name(field, params)

    # ── consecutive 类型：不需要 left_val，直接看序列 ──
    if compare_type == "consecutive":
        return _evaluate_consecutive(rule, col_name, df_slice)

    # 获取左值
    if col_name not in row.index:
        logger.debug("Column '%s' not found for field='%s' params=%s", col_name, field, params)
        return False
    left_val = row[col_name]
    if pd.isna(left_val):
        return False

    # 获取右值
    if compare_type == "field":
        compare_field = rule.get("compare_field", "")
        compare_params = rule.get("compare_params")
        compare_col = resolve_column_name(compare_field, compare_params)
        if compare_col not in row.index:
            logger.debug("Compare column '%s' not found for compare_field='%s' params=%s", compare_col, compare_field, compare_params)
            return False
        right_val = row[compare_col]
        if pd.isna(right_val):
            return False
    elif compare_type in ("lookback_min", "lookback_max"):
        right_val = _get_lookback_extreme(rule, col_name, df_slice, compare_type)
        if right_val is None:
            return False
    elif compare_type == "lookback_value":
        right_val = _get_lookback_value(rule, df_slice)
        if right_val is None:
            return False
    elif compare_type == "pct_diff":
        return _evaluate_pct_diff(rule, row, left_val, operator)
    elif compare_type == "pct_change":
        return _evaluate_pct_change(rule, col_name, df_slice, left_val, operator)
    else:
        right_val = rule.get("compare_value", 0)

    try:
        left_val = float(left_val)
        right_val = float(right_val)
    except (ValueError, TypeError):
        return False

    return _compare(left_val, operator, right_val)


def _compare(left: float, operator: str, right: float) -> bool:
    """Apply comparison operator."""
    if operator == ">":
        return left > right
    elif operator == "<":
        return left < right
    elif operator == ">=":
        return left >= right
    elif operator == "<=":
        return left <= right
    return False


def _get_lookback_extreme(
    rule: Dict[str, Any], col_name: str, df_slice: Optional[pd.DataFrame], mode: str
) -> Optional[float]:
    """Get MIN or MAX of a field over the last N days (excluding today)."""
    if df_slice is None:
        return None
    n = rule.get("lookback_n", 5)
    lookback_field = rule.get("lookback_field", rule.get("field", ""))
    lookback_params = rule.get("lookback_params", rule.get("params"))
    lookback_col = resolve_column_name(lookback_field, lookback_params)
    if lookback_col not in df_slice.columns:
        return None
    if len(df_slice) < n + 1:
        return None
    window = df_slice[lookback_col].iloc[-(n + 1):-1]
    if window.isna().all():
        return None
    if mode == "lookback_min":
        return float(window.min())
    else:
        return float(window.max())


def _get_lookback_value(
    rule: Dict[str, Any], df_slice: Optional[pd.DataFrame]
) -> Optional[float]:
    """Get value of lookback_field from N days ago."""
    if df_slice is None:
        return None
    n = rule.get("lookback_n", 1)
    lookback_field = rule.get("lookback_field", rule.get("field", ""))
    lookback_params = rule.get("lookback_params", rule.get("params"))
    lookback_col = resolve_column_name(lookback_field, lookback_params)
    if lookback_col not in df_slice.columns:
        return None
    if len(df_slice) < n + 1:
        return None
    val = df_slice[lookback_col].iloc[-(n + 1)]
    if pd.isna(val):
        return None
    return float(val)


def _evaluate_consecutive(
    rule: Dict[str, Any], col_name: str, df_slice: Optional[pd.DataFrame]
) -> bool:
    """Check if field has been consecutively rising/falling for N days."""
    if df_slice is None:
        return False
    n = rule.get("lookback_n", 3)
    consecutive_type = rule.get("consecutive_type", "rising")
    if col_name not in df_slice.columns:
        return False
    if len(df_slice) < n + 1:
        return False
    values = df_slice[col_name].iloc[-(n + 1):].values
    if any(pd.isna(v) for v in values):
        return False
    for i in range(1, len(values)):
        if consecutive_type == "rising" and values[i] <= values[i - 1]:
            return False
        elif consecutive_type == "falling" and values[i] >= values[i - 1]:
            return False
    return True


def _evaluate_pct_diff(
    rule: Dict[str, Any], row: pd.Series, left_val: float, operator: str
) -> bool:
    """Evaluate percentage difference: (field - compare_field) / compare_field * 100."""
    compare_field = rule.get("compare_field", "")
    compare_params = rule.get("compare_params")
    compare_col = resolve_column_name(compare_field, compare_params)
    if compare_col not in row.index:
        return False
    base_val = row[compare_col]
    if pd.isna(base_val):
        return False
    try:
        base_val = float(base_val)
        left_val = float(left_val)
    except (ValueError, TypeError):
        return False
    if base_val == 0:
        return False
    pct = (left_val - base_val) / base_val * 100
    threshold = float(rule.get("compare_value", 0))
    return _compare(pct, operator, threshold)


def _evaluate_pct_change(
    rule: Dict[str, Any],
    col_name: str,
    df_slice: Optional[pd.DataFrame],
    left_val: float,
    operator: str,
) -> bool:
    """Evaluate N-day percentage change: (today - N_days_ago) / N_days_ago * 100."""
    if df_slice is None:
        return False
    n = rule.get("lookback_n", 1)
    if len(df_slice) < n + 1:
        return False
    if col_name not in df_slice.columns:
        return False
    past_val = df_slice[col_name].iloc[-(n + 1)]
    if pd.isna(past_val):
        return False
    try:
        past_val = float(past_val)
        left_val = float(left_val)
    except (ValueError, TypeError):
        return False
    if past_val == 0:
        return False
    pct = (left_val - past_val) / past_val * 100
    threshold = float(rule.get("compare_value", 0))
    return _compare(pct, operator, threshold)


# ── 条件评估（买入/卖出触发） ─────────────────────────────

def evaluate_conditions(
    conditions: List[Dict[str, Any]],
    indicator_df: pd.DataFrame,
    mode: str = "AND",
) -> Tuple[bool, List[str]]:
    """评估一组条件是否满足（用于买入/卖出触发判定）

    与 evaluate_rules 的区别：
    - evaluate_rules: 累加分数，返回 (score, reasons)
    - evaluate_conditions: 返回布尔结果 (triggered, triggered_labels)

    Args:
        conditions: 条件列表（格式同 rules，但不需要 score 字段）
        indicator_df: 带指标列的 DataFrame
        mode: "AND"=全部满足才触发, "OR"=任一满足就触发

    Returns:
        (triggered, triggered_labels)
    """
    if not conditions or indicator_df.empty:
        return False, []

    latest = indicator_df.iloc[-1]
    triggered_labels = []

    if mode == "AND":
        for cond in conditions:
            if _evaluate_single_rule(cond, latest, df_slice=indicator_df):
                label = cond.get("label", "")
                if label:
                    triggered_labels.append(label)
            else:
                # AND 模式：任一条件不满足 → 整体不触发
                return False, []
        return True, triggered_labels

    else:  # OR
        for cond in conditions:
            if _evaluate_single_rule(cond, latest, df_slice=indicator_df):
                label = cond.get("label", "")
                if label:
                    triggered_labels.append(label)
        # OR 模式：有任一触发就算触发
        return len(triggered_labels) > 0, triggered_labels


# ── 已知指标取值范围 ─────────────────────────────────────
FIELD_RANGES: Dict[str, Tuple[float, float]] = {
    "RSI": (0, 100),
    "KDJ_K": (0, 100),
    "KDJ_D": (0, 100),
    "KDJ_J": (-20, 120),
    "STOCHRSI_K": (0, 100),
    "STOCHRSI_D": (0, 100),
    "BOLL_pband": (0, 1),
    "ADX": (0, 100),
    "ADX_plus_di": (0, 100),
    "ADX_minus_di": (0, 100),
    "MFI": (0, 100),
    "WR": (-100, 0),
    "CCI": (-500, 500),
    "ULTOSC": (0, 100),
    "STOCH_K": (0, 100),
    "STOCH_D": (0, 100),
}


def _get_field_range(field: str) -> Optional[Tuple[float, float]]:
    """Get known value range for a field, checking base name if parametrized.

    Tries progressively shorter prefixes to handle multi-part field names:
    BOLL_pband_20_2.0 -> BOLL_pband_20 -> BOLL_pband -> BOLL
    """
    if field in FIELD_RANGES:
        return FIELD_RANGES[field]
    # Try progressively shorter prefixes (strip trailing _param segments)
    parts = field.split("_")
    for i in range(len(parts) - 1, 0, -1):
        prefix = "_".join(parts[:i])
        if prefix in FIELD_RANGES:
            return FIELD_RANGES[prefix]
    return None


def check_reachability(
    conditions: List[Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    """Check if a set of AND-combined conditions can ever be simultaneously true.

    Returns (True, None) if reachable, (False, reason_string) if contradictory.
    Only checks compare_type="value" conditions — field comparisons are skipped.
    """
    if not conditions:
        return True, None

    # Collect per-column bounds: col_name -> {"lower": float, "upper": float}
    bounds: Dict[str, Dict[str, float]] = {}

    for cond in conditions:
        compare_type = cond.get("compare_type", "value")
        if compare_type != "value":
            continue  # Skip field/lookback/pct comparisons

        field = cond.get("field", "")
        params = cond.get("params")
        col_name = resolve_column_name(field, params)
        operator = cond.get("operator", ">")

        try:
            val = float(cond.get("compare_value", 0))
        except (ValueError, TypeError):
            continue

        if col_name not in bounds:
            bounds[col_name] = {"lower": float("-inf"), "upper": float("inf")}

        b = bounds[col_name]
        if operator in (">", ">="):
            b["lower"] = max(b["lower"], val)
        elif operator in ("<", "<="):
            b["upper"] = min(b["upper"], val)

    # Check 1: Range contradiction — lower > upper means impossible
    # Note: lower == upper is valid for single-point ranges (>= X AND <= X)
    for col_name, b in bounds.items():
        if b["lower"] > b["upper"]:
            return False, f"条件矛盾: {col_name} 要求同时 >{b['lower']} 且 <{b['upper']}"

    # Check 2: Out-of-range for bounded indicators
    for col_name, b in bounds.items():
        field_range = _get_field_range(col_name)
        if not field_range:
            continue
        range_min, range_max = field_range

        # Lower bound exceeds indicator max → impossible
        if b["lower"] != float("-inf") and b["lower"] >= range_max:
            return False, f"不可达: {col_name} >{b['lower']} 超出取值范围上限{range_max}"
        # Upper bound below indicator min → impossible
        if b["upper"] != float("inf") and b["upper"] <= range_min:
            return False, f"不可达: {col_name} <{b['upper']} 低于取值范围下限{range_min}"

    return True, None


# ── 验证 & 格式化 ─────────────────────────────────────────

def validate_rule(rule: Dict[str, Any]) -> Optional[str]:
    """验证规则是否合法"""
    from api.services.indicator_registry import get_extended_field_group

    field = rule.get("field", "")
    group = get_field_group(field)
    if not group and not get_extended_field_group(field):
        return f"未知指标字段: {field}"

    operator = rule.get("operator", "")
    if operator not in [op[0] for op in OPERATORS]:
        return f"未知运算符: {operator}"

    VALID_COMPARE_TYPES = {
        "value", "field",
        "lookback_min", "lookback_max", "lookback_value", "consecutive",
        "pct_diff", "pct_change",
    }

    compare_type = rule.get("compare_type", "value")
    if compare_type not in VALID_COMPARE_TYPES:
        return f"未知比较类型: {compare_type}"

    if compare_type == "field":
        cf = rule.get("compare_field", "")
        if not get_field_group(cf) and not get_extended_field_group(cf):
            return f"未知比较字段: {cf}"
    elif compare_type == "value":
        try:
            float(rule.get("compare_value", 0))
        except (ValueError, TypeError):
            return "比较值必须是数字"
    elif compare_type in ("lookback_min", "lookback_max", "lookback_value", "consecutive"):
        n = rule.get("lookback_n")
        if not isinstance(n, int) or n < 1 or n > 60:
            return f"lookback_n 必须是 1-60 的整数（当前: {n}）"
        if compare_type == "consecutive":
            ct = rule.get("consecutive_type", "")
            if ct not in ("rising", "falling"):
                return f"consecutive_type 必须是 rising 或 falling（当前: {ct}）"
    elif compare_type in ("pct_diff", "pct_change"):
        try:
            float(rule.get("compare_value", 0))
        except (ValueError, TypeError):
            return "比较值必须是数字"
        if compare_type == "pct_diff":
            cf = rule.get("compare_field", "")
            if not cf:
                return "pct_diff 类型必须指定 compare_field"
        if compare_type == "pct_change":
            n = rule.get("lookback_n")
            if not isinstance(n, int) or n < 1 or n > 60:
                return f"lookback_n 必须是 1-60 的整数（当前: {n}）"

    score = rule.get("score", 0)
    try:
        s = float(score)
        if abs(s) > 50:
            return f"单条规则得分不建议超过 ±50（当前: {s}）"
    except (ValueError, TypeError):
        return "得分必须是数字"

    return None


def _format_field_with_params(field: str, params: Optional[Dict[str, Any]] = None) -> str:
    """格式化字段名（带参数）"""
    label = get_field_label(field)
    group = get_field_group(field)
    if not group or not params:
        return label

    group_def = INDICATOR_GROUPS[group]
    if not group_def["params"]:
        return label

    # 检查是否全部是默认值
    defaults = {k: v["default"] for k, v in group_def["params"].items()}
    effective = dict(defaults)
    effective.update(params)

    if effective == defaults:
        return label

    # 只有非默认参数时才显示
    if group in ("RSI", "MA", "EMA", "ATR", "ADX"):
        return f"{label}({effective.get('period', '?')})"
    elif group == "MACD":
        return f"{label}({effective['fast']},{effective['slow']},{effective['signal']})"
    elif group == "KDJ":
        return f"{label}({effective['fastk']},{effective['slowk']},{effective['slowd']})"

    return label


def format_rule_display(rule: Dict[str, Any]) -> str:
    """将规则格式化为人类可读的字符串"""
    field = rule.get("field", "?")
    operator = rule.get("operator", "?")
    compare_type = rule.get("compare_type", "value")
    score = rule.get("score", 0)
    params = rule.get("params")

    field_label = _format_field_with_params(field, params)

    if compare_type == "field":
        compare_field = rule.get("compare_field", "?")
        compare_params = rule.get("compare_params")
        compare_label = _format_field_with_params(compare_field, compare_params)
        condition = f"{field_label} {operator} {compare_label}"
    else:
        compare_value = rule.get("compare_value", 0)
        condition = f"{field_label} {operator} {compare_value}"

    direction = "看涨" if score > 0 else "看跌" if score < 0 else "中性"
    return f"当 {condition} → {score:+d}分 ({direction})"
