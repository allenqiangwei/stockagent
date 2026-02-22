# AI 策略实验室设计文档

> 日期: 2026-02-10
> 状态: 设计完成，待实现

## 1. 概述

AI 策略实验室是一个自动化策略研究平台，利用 DeepSeek AI 搜索、生成、回测交易策略。用户选择一个策略主题或粘贴策略描述，系统自动生成 5-10 个策略变体，逐个在全 A 股上运行 3 年回测，按收益/回撤比评分排序，用户可一键采纳优秀策略到正式策略库。

## 2. 设计决策

| 决策项 | 选择 | 说明 |
|--------|------|------|
| AI 引擎 | DeepSeek API | OpenAI 兼容格式 + JSON mode，模型 `deepseek-chat` |
| 策略来源 | 模板 + 自定义 | 数据库存储的模板库（预置 15 个）+ 用户粘贴策略描述 |
| 运行模式 | 手动触发 | 用户在页面点击"开始实验"，SSE 实时进度 |
| 评分标准 | 风控优先 | `score = total_return_pct / max(abs(max_drawdown_pct), 1.0)` |
| 结果展示 | 排行榜模式 | 表格排序 + 展开详情 + 一键采纳 |
| 回测范围 | 全部 A 股 | ~5000 只，单策略回测约 30-60 分钟 |
| 指标补充 | 动态适配 | pandas_ta 130+ 指标，自动注册到 rule engine |

## 3. 数据模型

### 3.1 StrategyTemplate（策略模板）

```
id              int, PK       自增
name            str           模板名，如 "RSI超卖反弹"
category        str           分类: "均线" / "震荡" / "趋势" / "量价" / "组合"
description     text          策略逻辑的自然语言描述（发送给 DeepSeek 的种子）
is_builtin      bool          是否系统预置（预置不可删除，可编辑）
created_at      datetime      创建时间
```

### 3.2 Experiment（实验记录）

```
id              int, PK       自增
theme           str           实验主题，如 "RSI超卖反弹"
source_type     str           "template" / "custom"
source_text     text          原始输入（模板描述 或 用户粘贴的策略描述）
status          str           "pending" / "generating" / "backtesting" / "done" / "failed"
strategy_count  int           本次生成的策略数量
created_at      datetime      创建时间
```

### 3.3 ExperimentStrategy（实验策略 + 回测结果）

```
id                  int, PK       自增
experiment_id       int, FK       所属实验
name                str           AI 生成的策略名（如 "RSI反弹_激进版"）
description         str           AI 生成的策略说明
buy_conditions      JSON          买入条件列表（和 Strategy 格式一致）
sell_conditions     JSON          卖出条件列表
exit_config         JSON          {stop_loss_pct, take_profit_pct, max_hold_days}
status              str           "pending" / "backtesting" / "done" / "failed"
error_message       str           失败原因（如 "不支持的指标: XXX"）
total_trades        int           总交易次数
win_rate            float         胜率 %
total_return_pct    float         总收益率 %
max_drawdown_pct    float         最大回撤 %
avg_hold_days       float         平均持仓天数
avg_pnl_pct         float         平均单笔盈亏 %
score               float         综合评分（收益/回撤比）
backtest_run_id     int, FK       关联的 BacktestRun（复用现有回测记录）
promoted            bool          是否已采纳到正式策略库
promoted_strategy_id int          采纳后对应的 Strategy.id
created_at          datetime      创建时间
```

## 4. 动态指标系统

### 4.1 问题

当前系统支持 9 种指标（RSI、MACD、KDJ、MA、EMA、ADX、OBV、ATR、PRICE）。
网上策略经常用到布林带(BOLL)、CCI、WR、SAR 等未支持的指标。

### 4.2 方案

利用 `pandas_ta` 库（内置 130+ 指标）构建动态适配层：

```
DeepSeek 生成策略引用 "BOLL" 指标
    ↓
验证阶段: "BOLL" 不在 INDICATOR_GROUPS 中
    ↓
查询 pandas_ta: df.ta.bbands() ✓ 存在
    ↓
动态注册: sub_fields、params、列名映射
    ↓
计算指标 → 正常回测
```

### 4.3 指标注册表（indicator_registry.py）

预置映射表（覆盖 20+ 常用指标）：

```python
INDICATOR_REGISTRY = {
    # 已有指标
    "RSI":   {"func": "rsi",    "sub_fields": [("RSI", "RSI")], "params": {"length": 14}},
    "MACD":  {"func": "macd",   "sub_fields": [...], "params": {"fast": 12, "slow": 26, "signal": 9}},
    ...
    # 新增动态指标
    "BOLL":  {"func": "bbands", "sub_fields": [("BBL", "下轨"), ("BBM", "中轨"), ("BBU", "上轨")], "params": {"length": 20, "std": 2.0}},
    "CCI":   {"func": "cci",    "sub_fields": [("CCI", "CCI")], "params": {"length": 14}},
    "WR":    {"func": "willr",  "sub_fields": [("WILLR", "威廉指标")], "params": {"length": 14}},
    "SAR":   {"func": "psar",   "sub_fields": [("PSARl", "多头SAR"), ("PSARs", "空头SAR")], "params": {}},
    "STOCHRSI": {"func": "stochrsi", ...},
    "ROC":   {"func": "roc", ...},
    "MFI":   {"func": "mfi", ...},
    "TRIX":  {"func": "trix", ...},
    ...
}
```

### 4.4 通用计算适配器

在 `indicator_calculator.py` 中新增：

```python
def _compute_dynamic(self, df, indicator_name, params):
    """通过 pandas_ta 动态计算指标"""
    func = getattr(df.ta, REGISTRY[indicator_name]["func"])
    result = func(**params)
    # 自动提取列名，注册到 rule engine
    return result
```

### 4.5 边界处理

1. pandas_ta 支持 → 自动计算
2. pandas_ta 不支持 → 调 DeepSeek 用已有指标改写条件
3. 改写失败 → 标记策略 `status="failed"`，`error_message="不支持的指标: XXX"`

## 5. DeepSeek 交互设计

### 5.1 配置

```yaml
# config/config.yaml
deepseek:
  api_key: "sk-xxx"
  base_url: "https://api.deepseek.com/v1"
  model: "deepseek-chat"
```

### 5.2 客户端封装

OpenAI 兼容格式，使用 `openai` Python SDK：

```python
from openai import OpenAI

client = OpenAI(
    api_key=config.deepseek.api_key,
    base_url=config.deepseek.base_url,
)

response = client.chat.completions.create(
    model=config.deepseek.model,
    messages=[...],
    response_format={"type": "json_object"},
)
```

### 5.3 System Prompt 核心内容

```
你是一个量化策略生成器。根据用户给出的策略主题或描述，
生成 5-10 个策略变体，输出为 JSON 数组。

可用指标: RSI, MACD, KDJ, MA, EMA, ADX, OBV, ATR, PRICE,
         BOLL, CCI, WR, SAR, STOCHRSI, ROC, MFI, TRIX, ...
         （完整列表从 indicator_registry 动态注入）

可用操作符: >, <, >=, <=
比较类型: value（固定数值）, field（和另一个指标比较）

每个策略必须包含:
- name: 策略名称
- description: 策略逻辑说明
- buy_conditions: [{field, params, operator, compare_type, compare_value/compare_field, compare_params, label}]
- sell_conditions: [同上]
- exit_config: {stop_loss_pct, take_profit_pct, max_hold_days}

变体要求:
- 参数差异化（如 RSI 阈值分别用 20/25/30）
- 条件组合差异化（单指标 vs 多指标组合）
- 风格差异化（激进/稳健/保守的止损止盈配置）
```

### 5.4 两种触发场景

| 场景 | User Prompt | 预期输出 |
|------|-------------|----------|
| 模板主题 | "生成 RSI 超卖反弹 类策略的变体" | 5-10 个 RSI 相关策略 |
| 用户粘贴 | "当5日均线上穿20日均线，且RSI>50..." | 解析为结构化条件 + 3-5 个变体 |

### 5.5 条件验证与自动修正

AI 返回 JSON 后的校验流程：
1. 检查 `field` 是否在 indicator_registry 中
2. 不在 → 查 pandas_ta 是否支持 → 自动注册
3. 仍不支持 → 调 DeepSeek 改写条件
4. 改写失败 → 标记 failed
5. 检查 params 格式、operator 合法性
6. 检查 compare_type/compare_value/compare_field 完整性

## 6. 实验流程与 SSE 进度

### 6.1 完整生命周期

```
① 用户点击"开始实验"
   ↓
② status = "generating" — 调用 DeepSeek 生成策略
   SSE: {"type": "generating", "message": "正在用 AI 生成策略变体..."}
   ↓
③ 解析 + 验证 AI 返回的 JSON，创建 ExperimentStrategy 记录
   SSE: {"type": "strategies_ready", "count": 8, "strategies": [...名称列表]}
   ↓
④ status = "backtesting" — 逐个策略运行 3 年全 A 股回测
   对每个策略:
     SSE: {"type": "backtest_start", "index": 1, "total": 8, "name": "RSI反弹_激进版"}
     SSE: {"type": "backtest_progress", "index": 1, "pct": 45.2, "stock": "贵州茅台"}
     SSE: {"type": "backtest_done", "index": 1, "score": 2.8, "return": 35.2, "drawdown": 12.6}
   ↓
⑤ 全部完成 → status = "done"
   SSE: {"type": "experiment_done", "best_score": 3.1, "best_name": "RSI+MACD_稳健版"}
```

### 6.2 断点续传

每个 ExperimentStrategy 独立记录状态。服务重启后：
- 已完成策略结果不丢失
- 未完成标记为 "pending" 可手动重跑
- 前端重新打开能看到已有结果

### 6.3 耗时预估

- AI 生成: ~10 秒
- 单策略全 A 股 3 年回测: ~30-60 分钟
- 8 个策略总计: ~4-8 小时

## 7. API 接口

### 7.1 实验接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/lab/experiments | 发起实验 {theme, source_type, source_text} |
| GET  | /api/lab/experiments | 实验列表（分页） |
| GET  | /api/lab/experiments/{id} | 实验详情 + 策略排行榜 |
| GET  | /api/lab/experiments/{id}/stream | SSE 进度流 |
| POST | /api/lab/strategies/{id}/promote | 采纳策略到正式库 |

### 7.2 模板接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET    | /api/lab/templates | 模板列表（含分类筛选） |
| POST   | /api/lab/templates | 新建模板 |
| PUT    | /api/lab/templates/{id} | 编辑模板 |
| DELETE | /api/lab/templates/{id} | 删除模板（is_builtin 拒绝） |

## 8. 前端页面

### 8.1 页面结构

路径: `/lab`，三个 Tab：

1. **发起实验** — 模板选择（按分类筛选）+ 自定义描述输入 + 开始按钮
2. **实验历史** — 实验列表 → 点击展开策略排行榜 → 展开详情 → 采纳按钮
3. **模板管理** — 模板 CRUD 列表 + 编辑弹窗

### 8.2 排行榜表格列

| 列 | 说明 |
|----|------|
| # | 排名 |
| 策略名 | AI 生成的名称 |
| 收益率 | total_return_pct |
| 回撤 | max_drawdown_pct |
| 胜率 | win_rate |
| 交易次数 | total_trades |
| 平均持仓 | avg_hold_days |
| 评分 | score (收益/回撤比) |
| 操作 | [采纳] / [已采纳] |

点击行展开：买卖条件详情、交易明细表、equity curve 图表。

### 8.3 进度展示

回测进行中显示：
- 总进度条（N/M 个策略）
- 当前策略名 + 单策略进度（股票扫描进度）
- 已完成策略的实时评分列表

## 9. 内置策略模板

预置 15 个经典策略，分 5 类：

### 均线类
1. **均线金叉突破** — MA5 上穿 MA20，价格站上 MA60
2. **EMA 趋势跟踪** — EMA12 > EMA26 且价格收于 EMA12 上方
3. **多均线共振** — MA5 > MA10 > MA20 > MA60 多头排列

### 震荡类
4. **RSI 超卖反弹** — RSI < 30 后回升至 35 以上
5. **KDJ 金叉** — KDJ_J < 20 且 K 线上穿 D 线
6. **RSI + KDJ 共振** — RSI < 30 同时 KDJ_J < 20

### 趋势类
7. **MACD 金叉** — MACD 线上穿信号线，柱状图由负转正
8. **ADX 强趋势** — ADX > 25 且 +DI > -DI
9. **MACD + ADX 趋势确认** — MACD 金叉同时 ADX > 20

### 量价类
10. **放量突破** — 价格突破 MA20 且 OBV 创新高
11. **缩量回调** — 价格回踩 MA20 附近，ATR 收窄

### 组合类
12. **均线 + RSI** — MA5 > MA20 且 RSI 在 40-70 区间
13. **MACD + RSI 双确认** — MACD 金叉且 RSI > 50
14. **三指标共振** — MA 多头 + MACD 金叉 + RSI > 50
15. **全指标综合** — 5 个以上指标同时满足

## 10. 文件清单

### 新建文件

| 文件 | 说明 |
|------|------|
| api/models/ai_lab.py | Experiment、ExperimentStrategy、StrategyTemplate ORM |
| api/schemas/ai_lab.py | Pydantic 请求/响应 schema |
| api/services/deepseek_client.py | DeepSeek API 封装 |
| api/services/ai_lab_engine.py | 实验编排引擎 |
| api/services/indicator_registry.py | 动态指标注册表 |
| api/routers/ai_lab.py | REST + SSE 接口 |
| web/src/app/lab/page.tsx | 实验室主页 |
| web/src/app/api/lab/experiments/[id]/stream/route.ts | SSE 代理 |

### 修改文件

| 文件 | 说明 |
|------|------|
| config/config.yaml | 新增 deepseek 配置段 |
| api/main.py | 注册 ai_lab router、初始化预置模板 |
| api/config.py | 解析 deepseek 配置 |
| src/indicators/indicator_calculator.py | 增加 _compute_dynamic() 通用适配 |
| src/signals/rule_engine.py | INDICATOR_GROUPS 支持动态扩展 |
| web/src/lib/api.ts | 新增 lab API 函数 |
| web/src/hooks/use-queries.ts | 新增 lab 相关 hooks |
| web/src/types/index.ts | 新增 lab 相关类型 |
| web/src/components/layout/sidebar.tsx | 导航栏新增"实验室"入口 |

## 11. 实现顺序

1. **Phase 1: 基础设施** — config、deepseek_client、indicator_registry、数据模型
2. **Phase 2: 后端核心** — ai_lab_engine（AI 生成 + 验证 + 回测编排）、router
3. **Phase 3: 前端页面** — lab page 三个 tab、SSE 进度、排行榜
4. **Phase 4: 模板库** — 预置 15 个模板、模板管理 CRUD
5. **Phase 5: 联调测试** — 端到端跑通一个完整实验
