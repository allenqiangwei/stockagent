# P3 组合策略 — 信号投票/加权系统设计

> 日期: 2026-02-15 | 优先级: P3 | 状态: 设计中

## 1. 问题

当前系统中每个策略独立运行。18个Standard A策略的信号互不关联:
- **误信号多**: 单策略在震荡市仅4%盈利率
- **无法利用多策略共识**: 多个策略同时发出买入信号通常比单策略信号更可靠
- **现有`_evaluate_stock()`已在做简单聚合**: 任一策略触发就算"买入",但没有投票门槛

## 2. 核心设计

### 2.1 信号投票机制

在回测和实时信号生成中增加"组合策略"类型。一个组合策略包含:
- **成员策略列表** (member_strategy_ids): 引用已有的promoted策略
- **投票门槛** (vote_threshold): 如"至少3/5个策略同意才买入"
- **加权模式** (weight_mode):
  - `equal`: 每个成员1票 (多数投票)
  - `score_weighted`: 按策略score加权, 加权和 >= threshold 才触发
  - `regime_weighted`: 按当前市场阶段动态调整权重(牛市策略在牛市权重更高)

### 2.2 数据模型

在 `strategies` 表新增字段(利用已有的 `portfolio_config` JSON字段):

```python
# portfolio_config 结构 (当 category == "combo" 时):
{
    "type": "combo",
    "member_ids": [12, 15, 18, 23, 27],  # 成员策略ID
    "vote_threshold": 3,       # 至少N个策略同意 (equal模式)
    "weight_mode": "equal",    # equal | score_weighted | regime_weighted
    "score_threshold": 2.5,    # score_weighted模式下的阈值
    "sell_mode": "any",        # any: 任一策略卖出即卖 | majority: 多数卖出才卖
}
```

无需新建表。复用 `Strategy` 表,`category="combo"`,`buy_conditions/sell_conditions` 留空(由成员策略提供)。

### 2.3 回测引擎集成

在 `PortfolioBacktestEngine.run()` 中:

**当前流程** (单策略):
```
for each day:
  for each stock:
    evaluate_conditions(buy_conditions, df) → buy/not
```

**新流程** (组合策略):
```
for each day:
  for each stock:
    votes = 0
    for member_strategy in combo.members:
      if evaluate_conditions(member.buy_conditions, df):
        votes += member.weight
    if votes >= combo.threshold:
      → buy signal
```

关键: 指标只需计算一次。所有成员策略的 `collect_indicator_params()` 合并后统一计算,然后对同一个 `full_df` 评估每个成员的条件。

### 2.4 实时信号集成

`SignalEngine._evaluate_stock()` 需要识别组合策略:
- 普通策略: 走现有逻辑
- 组合策略 (`portfolio_config.type == "combo"`): 加载成员策略,逐个评估,投票决定

### 2.5 AI Lab 集成

新增实验类型 `source_type="combo"`:
- 不调用DeepSeek生成策略
- 用户选择N个已有策略做成员
- 自动生成多种投票配置的变体(2/3, 3/5, 4/5等)
- 每个变体独立回测

## 3. 实现步骤

### Step 1: 后端核心 — 组合策略数据结构

- 在 `api/schemas/strategy.py` 中新增 `ComboConfig` Pydantic model
- 在 `api/routers/strategies.py` 中新增 `POST /api/strategies/combo` endpoint
- 组合策略保存时验证: 所有member_ids存在且enabled

### Step 2: 回测引擎 — 组合策略支持

- `PortfolioBacktestEngine.run()` 检测 combo 策略
- 合并所有成员策略的indicator params做统一计算
- 每日对每只股票评估所有成员策略,按投票逻辑决定买入/卖出
- Exit config使用组合策略自身的 exit_config (统一止损止盈)

### Step 3: 信号引擎 — 实时信号

- `SignalEngine._evaluate_stock()` 识别 combo 策略
- 组合策略的信号显示哪些成员策略投了赞成票

### Step 4: AI Lab — 组合实验

- `POST /api/lab/experiments` 支持 `source_type="combo"`
- 自动从已有Standard A策略中组合
- 生成变体: 不同投票门槛、不同成员子集

### Step 5: 前端

- 策略页面新增"组合策略"创建入口
- 选择成员策略 + 配置投票参数
- 信号页面显示组合策略的投票详情

## 4. 预期效果

基于实验数据的推理:
- **震荡市过滤**: 多数投票可过滤掉震荡市的假信号(震荡市很少多策略同时触发)
- **牛市放大**: 牛市中多策略共振,信号更强
- **回撤控制**: 多数投票机制天然降低误入概率,降低最大回撤
- **Top 3策略投票(3/3)预期**: 收益可能略低于最佳单策略,但回撤大幅降低,score提升

## 5. 风险

- **计算量**: 5个成员策略 × 5000只股票 = 25000次条件评估/天。每次评估很快(~1ms),总计约25s,可接受。
- **过度过滤**: 投票门槛太高可能导致零交易。需要实验找最优门槛。
- **成员策略相关性**: 如果5个成员策略都基于KDJ,投票等于单策略。需要选择互补的成员。
