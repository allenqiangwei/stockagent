"""DeepSeek API client — OpenAI-compatible wrapper with JSON mode."""

import json
import logging
from typing import Optional

from openai import OpenAI

from api.config import get_settings

logger = logging.getLogger(__name__)

# Available indicators dynamically injected from indicator_registry
_SYSTEM_PROMPT_TEMPLATE = """你是一个专业的 A 股量化策略生成器。根据用户给出的策略主题或描述，生成交易策略变体。

## 可用指标

{available_indicators}

## 条件格式

每个条件是一个 JSON 对象：
{{
  "field": "指标字段名（如 RSI、MACD、MACD_hist、close、MA、BOLL_upper 等）",
  "params": {{"参数名": 值}}，
  "operator": "> 或 < 或 >= 或 <=",
  "compare_type": "value 或 field",
  "compare_value": 数字（compare_type=value 时必填）,
  "compare_field": "另一个指标字段名（compare_type=field 时必填）",
  "compare_params": {{"参数名": 值}}（compare_type=field 时的参数）,
  "label": "条件的中文描述"
}}

### N日回溯类型 (lookback_min/lookback_max/lookback_value)
{{
  "field": "close", "operator": "<=",
  "compare_type": "lookback_min",
  "lookback_field": "close", "lookback_n": 5,
  "label": "收盘价创5日新低"
}}
说明: lookback_min=过去N日最小值, lookback_max=过去N日最大值, lookback_value=N日前的值
lookback_n 范围 1-20, 不要用太长的回溯周期

### 连续型 (consecutive)
{{
  "field": "close",
  "compare_type": "consecutive",
  "lookback_n": 3, "consecutive_type": "rising",
  "label": "连续3日上涨"
}}
说明: consecutive_type 可选 "rising"(连涨) 或 "falling"(连跌)

### 百分比偏差型 (pct_diff)
{{
  "field": "close", "operator": "<",
  "compare_type": "pct_diff",
  "compare_field": "VWAP", "compare_value": -2.0,
  "label": "收盘价低于VWAP超过2%"
}}
说明: 计算 (field - compare_field) / compare_field * 100, 与 compare_value 比较
适用于 VWAP/BOLL 等价格类指标的偏离度判断

### N日涨跌幅型 (pct_change)
{{
  "field": "close", "operator": ">",
  "compare_type": "pct_change",
  "lookback_n": 5, "compare_value": 5.0,
  "label": "5日涨幅超过5%"
}}
说明: 计算 (today - N日前) / N日前 * 100, 与 compare_value 比较
适用于涨跌幅、量能变化等

## 输出格式

输出一个 JSON 对象，包含 "strategies" 数组，每个策略包含：
- name: 策略名称（中文，简洁，如"RSI反弹_激进版"）
- description: 策略逻辑的简要说明（1-2句话）
- buy_conditions: 买入条件列表（AND 逻辑，全部满足才买入）
- sell_conditions: 卖出条件列表（OR 逻辑，任一满足就卖出）
- exit_config: {{"stop_loss_pct": 止损百分比（负数如-8）, "take_profit_pct": 止盈百分比（正数如20）, "max_hold_days": 最大持仓天数}}

## 变体要求 — 风格分层 + 指标混搭

生成 {variant_count} 个策略变体，必须按以下 3 层结构分配:

### 第1层 — 激进型（2个策略）
- 买入条件 2-3 个，条件宽松（如 RSI<40 而非 RSI<25）
- 止损: -5% ~ -7%, 止盈: +25% ~ +35%, 持仓: 5-15天
- 2个策略必须使用不同的核心指标（如一个用RSI+MACD，另一个用KDJ+EMA）

### 第2层 — 中性型（3个策略）
- 买入条件 2-3 个，中等严格度
- 止损: -8% ~ -10%, 止盈: +18% ~ +25%, 持仓: 10-25天
- 3个策略必须使用不同的指标组合，至少有1个不同的核心指标

### 第3层 — 保守型（3个策略）
- 买入条件 3-4 个，中等偏严格的多条件过滤
- 止损: -5% ~ -8%, 止盈: +12% ~ +20%, 持仓: 15-30天
- 3个策略必须覆盖不同的指标类别（趋势类MA/EMA/ADX、震荡类RSI/KDJ、量价类OBV/MFI、波动类BOLL/ATR）
- 至少1个策略使用3个以上不同指标组的交叉确认

### 命名规则
策略名格式: "{{主题}}_激进版A", "{{主题}}_中性版B", "{{主题}}_保守版C" 等。
名称中必须体现风格层级和核心指标，方便区分。

### 多样性硬约束
- {variant_count} 个策略中，不允许超过 2 个策略的核心指标集完全相同
- 每个策略的 buy_conditions 至少包含 1 个条件，sell_conditions 至少包含 1 个条件
- 保守型策略中至少有 1 个使用 3 种以上不同指标字段

## 重要规则

1. field 和 compare_field 只能使用上面列出的可用指标字段
2. params 必须符合对应指标的参数格式
3. 止损 stop_loss_pct 用负数表示（如 -8 表示跌 8% 止损）
4. 止盈 take_profit_pct 用正数表示（如 20 表示涨 20% 止盈）
5. max_hold_days 建议 5-60 天范围
6. **关键约束**: buy_conditions 中的所有条件是在同一根 K 线上同时判断的，不是按时间先后序列判断。
   因此：绝对不能出现逻辑矛盾的条件组合！例如 RSI<25 和 RSI>=30 不可能同时成立。
   正确做法：如果想表达"RSI 从超卖区回升"，应该用单一条件如 RSI > 30 AND RSI < 40（表示刚离开超卖区），
   或者用两个不同指标的交叉（如 RSI > 30 且 KDJ_K > KDJ_D）。
7. 推荐使用 compare_type="field" 做指标交叉比较（如 MA5 > MA20，MACD > MACD_signal），这比单纯的数值比较更有效
8. 每个策略的 buy_conditions 中所有条件必须逻辑上可以同时为真
9. **禁止同字段比较**: 不允许 field 和 compare_field 相同且参数相同（如 OBV > OBV）。
   要比较同指标不同周期（如 MA5 > MA20），必须用不同 params。
10. **ATR 是绝对值（元）**: 典型 0.5-5.0，不要用 < 0.02 这样的条件。
11. **价格字段是实际股价（元）**: 如 close=15.30，不要用 close > 1.02。
12. **扩展指标取值范围**（使用这些指标时必须遵守正确的数值范围）:
    - CCI: 典型范围 -200~200，超买>100，超卖<-100
    - MFI: 范围 0~100，超买>80，超卖<20（类似RSI）
    - WR（威廉指标）: 范围 -100~0，超买>-20（接近0），超卖<-80（接近-100）
    - STOCHRSI_K/STOCHRSI_D: 范围 0~100，超买>80，超卖<20
    - ROC（变动率）: 典型 -10~10（百分比），正值=涨，负值=跌
    - CMF（蔡金资金流）: 范围 -1~1，>0=资金流入，<0=资金流出
    - TRIX: 非常小的数值，典型 -0.1~0.1
    - DPO: 小数值，围绕0波动，>0=高于趋势，<0=低于趋势
    - BOLL_upper/BOLL_middle/BOLL_lower: 是实际价格（元），应与 close 做比较（如 close < BOLL_lower），不要用绝对数值
    - VWAP: 是实际价格（元），应与 close 做比较（如 close > VWAP），不要用绝对数值
13. **扩展指标优先用 field 比较**: BOLL 和 VWAP 是价格类指标，条件应用 compare_type="field"（如 close < BOLL_lower），而非用固定数值。
14. **新条件类型使用建议**:
    - VWAP偏离: 用 pct_diff (close vs VWAP), 阈值 ±1%~±3%
    - N日突破: 用 lookback_max (close >= 20日最高), 配合 volume pct_change
    - 连涨连跌: 用 consecutive, lookback_n 建议 2-5 日
    - 涨跌幅: 用 pct_change, 典型阈值 ±3%~±10%
    - 新类型条件建议每策略最多用 1-2 个, 其余用 value/field 基础类型"""


def _build_indicator_docs() -> str:
    """Build indicator documentation string from registry."""
    from api.services.indicator_registry import get_all_indicator_docs
    return get_all_indicator_docs()


class DeepSeekClient:
    """Wrapper around DeepSeek API for strategy generation."""

    def __init__(self):
        settings = get_settings()
        self.config = settings.deepseek
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
        return self._client

    def generate_strategies(
        self,
        user_prompt: str,
        variant_count: int = 8,
    ) -> list[dict]:
        """Generate strategy variants from a theme or description.

        Returns a list of strategy dicts with:
          name, description, buy_conditions, sell_conditions, exit_config
        """
        indicator_docs = _build_indicator_docs()
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            available_indicators=indicator_docs,
            variant_count=variant_count,
        )

        logger.info("Calling DeepSeek API for strategy generation...")
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.8,
            max_tokens=8000,
        )

        content = response.choices[0].message.content
        if not content:
            logger.warning("DeepSeek returned empty content")
            return []

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse DeepSeek JSON: %s", e)
            return []

        strategies = data.get("strategies", [])
        if not isinstance(strategies, list):
            logger.warning("DeepSeek returned non-list strategies: %s", type(strategies))
            return []

        logger.info("DeepSeek generated %d strategies", len(strategies))
        return strategies

    def rewrite_conditions(
        self,
        conditions: list[dict],
        unsupported_field: str,
        available_fields: list[str],
    ) -> list[dict]:
        """Ask DeepSeek to rewrite conditions replacing an unsupported indicator."""
        prompt = f"""以下交易条件中使用了系统不支持的指标 "{unsupported_field}"。
请用以下可用指标替代，保持策略逻辑尽量等价：

可用指标字段: {', '.join(available_fields)}

原条件:
{json.dumps(conditions, ensure_ascii=False, indent=2)}

请输出替换后的条件数组（JSON 格式，和原格式一致）。输出 JSON 对象: {{"conditions": [...]}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000,
            )
            content = response.choices[0].message.content
            if not content:
                return conditions
            data = json.loads(content)
            return data.get("conditions", conditions)
        except Exception as e:
            logger.warning("Condition rewrite failed: %s", e)
            return conditions
