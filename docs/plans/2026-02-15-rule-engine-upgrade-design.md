# 规则引擎升级设计 (P4)

> 日期: 2026-02-15 | 状态: 已批准

## 背景

156场实验、1199个策略的数据显示三个核心瓶颈：
1. **31% 策略 invalid** — 条件矛盾/不可达，浪费回测资源
2. **无法表达时序条件** — "N日新低"、"连续上涨"等策略类型被锁死
3. **无法表达偏差条件** — "偏离VWAP超2%"、"N日涨幅"等派生计算不支持

## 方案选择

选定 **方案B: 扩展规则引擎条件类型**。保持 JSON 规则结构，新增 compare_type 选项，向后完全兼容。不做 DSL 表达式引擎（YAGNI）。

## 实现顺序

① 条件可达性预检 → ② N日回溯条件 → ③ 百分比偏差条件

---

## 一、条件可达性预检

### 新函数

`check_reachability(conditions: list[dict]) -> tuple[bool, str | None]`，位于 `src/signals/rule_engine.py`。

### 检测规则

**1. 范围矛盾检测** — 同一字段（解析后的列名）的上下界无交集：
- `RSI > 70 AND RSI < 25` → 不可达
- `KDJ_K > 80 AND KDJ_K < 90` → 可达

**2. 同字段同方向冗余** — 标记 warning 但不阻止：
- `RSI > 30 AND RSI > 50` → 冗余（等价于 RSI > 50）

**3. 已知范围校验** — 对有界指标做边界检查：
```python
FIELD_RANGES = {
    "RSI": (0, 100),
    "KDJ_K": (0, 100), "KDJ_D": (0, 100), "KDJ_J": (-20, 120),
    "STOCHRSI_K": (0, 100), "STOCHRSI_D": (0, 100),
    "BOLL_pband": (0, 1),
    "ADX": (0, 100),
}
```
- `RSI > 120` → 不可达（超出量程）

**4. 买卖条件互斥检测** — warning 级别：
- 买入 `RSI < 30` + 卖出 `RSI < 25` → 卖出比买入更严格

### 调用时机

- `ai_lab_engine.py`：DeepSeek 生成策略后、回测前
- `validate_rule()`：增加单条规则的范围校验

---

## 二、N日回溯条件

### 新增 compare_type

**`lookback_min` / `lookback_max`** — N日极值：
```json
{
  "field": "close", "operator": "<=",
  "compare_type": "lookback_min",
  "lookback_field": "close", "lookback_n": 5,
  "label": "收盘价创5日新低"
}
```

**`lookback_value`** — N日前的值：
```json
{
  "field": "close", "operator": ">",
  "compare_type": "lookback_value",
  "lookback_field": "close", "lookback_n": 1,
  "label": "今日收盘高于昨日"
}
```

**`consecutive`** — 连续N日满足：
```json
{
  "field": "close", "operator": ">",
  "compare_type": "consecutive",
  "lookback_n": 3, "consecutive_type": "rising",
  "label": "连续3日上涨"
}
```

### 签名变更

```python
def _evaluate_single_rule(rule, row, df_slice=None):
```

`df_slice` 默认 None，旧条件类型不使用它。`evaluate_conditions()` 传入 `df_slice=indicator_df`。

---

## 三、百分比偏差条件

### 新增 compare_type

**`pct_diff`** — 两字段百分比偏差：
```json
{
  "field": "close", "operator": "<",
  "compare_type": "pct_diff",
  "compare_field": "VWAP", "compare_value": -2.0,
  "label": "收盘价低于VWAP超过2%"
}
```
语义: `(close - VWAP) / VWAP * 100 < -2.0`

**`pct_change`** — N日涨跌幅：
```json
{
  "field": "close", "operator": ">",
  "compare_type": "pct_change",
  "lookback_n": 5, "compare_value": 5.0,
  "label": "5日涨幅超过5%"
}
```
语义: `(close - close[5日前]) / close[5日前] * 100 > 5.0`

### 解锁的实验方向

| 方向 | 之前 | 升级后 |
|------|------|--------|
| VWAP均值回归 | 已弃 | `pct_diff` close vs VWAP |
| BOLL带宽收窄 | 已弃 | `pct_change` on BOLL_wband |
| 连续缩量/放量 | 无法表达 | `pct_change` on volume |
| N日突破 | 无法表达 | `lookback_max` + `pct_diff` |

---

## 四、集成与兼容

### validate_rule() 增强

```python
VALID_COMPARE_TYPES = {"value", "field", "lookback_min", "lookback_max",
                        "lookback_value", "consecutive", "pct_diff", "pct_change"}
```

### collect_indicator_params() 增强

收集 `lookback_field` 的指标参数（如果存在且不同于 field）。

### DeepSeek Prompt 更新

扩展 JSON schema 示例，展示新 compare_type 用例，强调 lookback_n 范围 1-20。

### 改动文件

| 文件 | 改动 |
|------|------|
| `src/signals/rule_engine.py` | 新 compare_type、check_reachability()、validate 增强、collect 增强 |
| `api/services/deepseek_client.py` | Prompt: 新条件类型说明+示例 |
| `api/services/ai_lab_engine.py` | 回测前调用 check_reachability() |

### 向后兼容

- 所有现有规则行为不变
- `_evaluate_single_rule` 新参数 `df_slice=None`
- 1199 个策略的 JSON 格式完全兼容

### 不做

- DSL/表达式引擎 — YAGNI
- 前端编辑器升级 — 后续迭代
- crossover 检测 — `lookback_value(n=1)` + field 已可表达
