# 量化工作台 — 统一回测/实验/策略管理前端

## 目标

将 `/backtest`、`/lab`、`/strategies` 三个页面合并为一个统一的 `/lab` 仪表盘页面。以策略池总览为中心，下钻到实验/回测详情。删除旧的 `/backtest` 和 `/strategies` 页面。

## 布局设计

### 顶部：策略池总览卡片

一排 KPI 卡片，一目了然：

```
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ 活跃策略     │ │ 策略家族     │ │ 总回测次数   │ │ 池平均 Score │ │ 最佳 Return  │
│    159      │ │    34       │ │   18,343    │ │   0.83      │ │   8340%     │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

数据来源：`GET /api/strategies/pool/status`

### 中间：Tab 导航

```
[策略池] [实验] [回测] [探索历史]
```

### Tab 1: 策略池

按家族分组的策略列表。每个家族是一个可展开的卡片：

```
ATR+RSI (150/150 满) avg_score=0.84 best_return=8340%
  ├─ RSI_47_67_ATR_0165_TP1_MHD2_SL30   score=0.85  ret=8340%  [champion]
  ├─ RSI_47_67_ATR_0165_TP1.5_MHD2_SL30 score=0.84  ret=7849%
  └─ ... (148 more)

ATR+MACD+RSI (85/150) avg_score=0.82
  └─ ...
```

功能：
- 按 avg_score 或策略数排序
- 展开看家族内策略列表
- 点击策略 → 右侧显示详情（买卖条件、回测指标、资金曲线）
- 操作：归档、克隆、运行回测

数据来源：`GET /api/strategies/families`，`GET /api/strategies/{id}`

### Tab 2: 实验

最近实验列表 + 发起新实验。

```
┌──────────────────────────────────────────────┐
│ [+ 发起实验]  [重试卡住的]                      │
├──────────────────────────────────────────────┤
│ #12457 RSI+ATR网格搜索  ✅完成  36策略 12 StdA+ │
│ #12456 三指标共振SL扫描  ✅完成  90策略 76 StdA+ │
│ #12455 KAMA+W_RSI探索   🔄进行中  24/50        │
│ ...                                          │
└──────────────────────────────────────────────┘
```

点击实验 → 展开显示：
- 实验策略列表（按 score 排序）
- 每条策略的关键指标：score, return, win_rate, drawdown, trades
- 操作：提升到策略池、克隆回测、查看详情

数据来源：`GET /api/lab/experiments`，`GET /api/lab/experiments/{id}`

### Tab 3: 回测

回测结果查看器，核心可视化区：

```
┌────────────────────────────────────────────────┐
│ 策略: RSI_47_67_ATR_0165_TP1_MHD2              │
│ 区间: 2020-01-01 ~ 2025-12-31                  │
├────────────────────────────────────────────────┤
│                                                │
│  📈 资金曲线 (equity curve)                     │
│  ════════════════════════════════════════       │
│  蓝线=策略, 灰线=上证指数(benchmark)             │
│                                                │
├────────────────────────────────────────────────┤
│  指标卡片:                                      │
│  收益率 +3241%  │ 最大回撤 12.3% │ 胜率 63.2%   │
│  Sharpe 2.14   │ Calmar 8.7    │ 超额 +2890%  │
├────────────────────────────────────────────────┤
│  交易列表 (可排序/筛选):                         │
│  日期      股票    买入   卖出   收益   持有天数   │
│  2025-03-05 000001 10.2  11.5  +12.7% 3天      │
│  ...                                           │
├────────────────────────────────────────────────┤
│  退出原因分布:                                   │
│  ██████████ 止盈 45%                            │
│  ████████   策略退出 35%                         │
│  ████       超期 15%                            │
│  ██         止损 5%                             │
└────────────────────────────────────────────────┘
```

功能：
- 选择策略 → 查看最新回测结果
- 资金曲线图（ECharts/Recharts）+ 基准对比线
- 交易列表（可按收益/日期/退出原因排序）
- 退出原因饼图/柱图
- 市场环境分析（regime_stats）
- 手动发起回测

数据来源：`GET /api/backtest/runs/{id}`，`POST /api/backtest/run`

### Tab 4: 探索历史

探索轮次列表，每轮的统计。

```
R1199: 38 exp, 348 strats, 118 StdA+, best score 0.8777
R1198: 42 exp, 310 strats, 93 StdA+
...
```

数据来源：`GET /api/lab/exploration-rounds`

## 关键图表组件

### 资金曲线图（新建）

`web/src/components/charts/equity-curve-chart.tsx`

已有一个基础版本（被 backtest page 引用），需要增强：
- 双线：策略线（蓝）+ 基准线（灰）
- 回撤区域着色（红色半透明）
- Hover 显示日期/净值/回撤
- 响应式

### 退出原因图（新建）

`web/src/components/charts/exit-reason-chart.tsx`

水平柱状图或饼图，显示 sell_reason 分布。

## 技术选型

- 图表：使用 Recharts（Next.js 生态常用，已在项目 package.json 中或可快速加入）
- 布局：shadcn/ui Card + Tabs + Table + Badge
- 数据获取：现有 use-queries.ts hooks

## 文件结构

```
web/src/app/lab/page.tsx                      # 统一工作台主页面（替换现有）
web/src/components/quant/
├── pool-overview.tsx                          # 策略池 KPI 卡片
├── strategy-families.tsx                      # 策略家族列表
├── experiment-list.tsx                        # 实验列表
├── backtest-viewer.tsx                        # 回测结果查看器
├── equity-curve.tsx                           # 资金曲线图表
├── exit-reason-chart.tsx                      # 退出原因分布图
└── exploration-rounds.tsx                     # 探索历史列表
```

删除：
- `web/src/app/backtest/page.tsx`
- `web/src/app/strategies/page.tsx`

修改 nav-bar：
- `/backtest` 和 `/strategies` 导航项移除
- `/lab` 改名为"量化工作台"

## API 依赖

所有需要的 API 已经存在：
- `GET /api/strategies/pool/status` — 池总览
- `GET /api/strategies/families` — 家族列表
- `GET /api/strategies/{id}` — 策略详情
- `GET /api/lab/experiments` — 实验列表
- `GET /api/lab/experiments/{id}` — 实验详情
- `GET /api/lab/exploration-rounds` — 探索历史
- `GET /api/backtest/runs` — 回测列表
- `GET /api/backtest/runs/{id}` — 回测详情（含 equity_curve + trades）
- `POST /api/backtest/run` — 发起回测
- `POST /api/lab/experiments` — 发起实验
