# 市场阶段分类集成设计

> 日期: 2026-02-12 | 状态: 已实施

## 目标

用上证指数历史数据预计算每周的市场阶段标签（trending_bull / trending_bear / ranging / volatile），在回测中按日期查表匹配，统计策略在不同阶段的表现。第一阶段只做统计，不影响交易逻辑。

## 设计决策

- **数据源**: 上证指数 (000001) 日线数据
- **粒度**: 按自然周划分
- **检测器**: 复用现有 `MarketRegimeDetector`（ADX + ATR + MA + 宽度）
- **集成方式**: 统计分类，不影响买卖决策
- **额外字段**: 每周指数收益率，用于对比策略是否跑赢大盘

## Step 1: 数据层

### 1a. DB 模型 — `api/models/market_regime.py` (NEW)

```python
class MarketRegimeLabel(Base):
    __tablename__ = "market_regimes"
    week_start = Column(Date, primary_key=True)  # 周一
    week_end = Column(Date)                       # 周五
    regime = Column(String(20))                   # trending_bull/bear/ranging/volatile
    confidence = Column(Float)
    trend_strength = Column(Float)
    volatility = Column(Float)
    breadth = Column(Float)
    index_return_pct = Column(Float)              # 本周上证涨跌幅
```

### 1b. 计算服务 — `api/services/regime_service.py` (NEW)

- `compute_weekly_regimes(start_date, end_date) -> list[dict]`
  - 获取上证指数日线 → 按自然周分组 → 每周用截至周末的近30日数据检测 → 计算周收益率
- `ensure_regimes(start_date, end_date)`
  - 检查 DB 已有范围，只补算缺失周
- `get_regime_map(start_date, end_date) -> Dict[str, str]`
  - 返回 {date_str: regime} 映射（每日查其所属周的regime）
- `get_regime_summary(start_date, end_date) -> dict`
  - 返回各阶段周数统计 + 指数总收益

### 1c. 上证指数数据获取

复用 `DataCollector`，需确保能获取指数数据。现有 AkShare `stock_zh_index_daily_em` 支持。

## Step 2: 回测引擎集成

### 2a. `PortfolioBacktestResult` 扩展

新增字段:
```python
regime_stats: dict = field(default_factory=dict)  # {regime: {weeks, trades, win_rate, return_pct}}
index_return_pct: float = 0.0                     # 同期上证涨跌幅
```

### 2b. `PortfolioBacktestEngine.run()` 修改

- 新增可选参数 `regime_map: Dict[str, str] | None`
- Day-by-day 循环中，每笔 Trade 额外记录 `regime` 字段（买入日所属的阶段）
- `_build_result()` 中按 regime 分组统计

### 2c. Trade 扩展

`Trade` dataclass 新增 `regime: str = ""`

## Step 3: AI Lab 集成

### 3a. `ai_lab_engine.py` 修改

- `run_experiment()` 开始时调用 `ensure_regimes(start_date, end_date)`
- `_run_single_backtest()` 加载 regime_map 传给引擎
- 结果的 `regime_stats` 存入 `ExperimentStrategy` 新字段

### 3b. `ExperimentStrategy` 模型扩展

新增: `regime_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)`

### 3c. `BacktestRun` 模型扩展

新增: `regime_stats` (JSON), `index_return_pct` (Float)

## Step 4: 前端展示

### 4a. 实验详情中的策略展开区

新增"市场阶段分析"卡片:
- 4行表格: 阶段标签(彩色) | 周数 | 交易数 | 胜率 | 收益率
- trending_bull=绿, trending_bear=红, ranging=灰, volatile=橙
- 底行: 上证同期收益作参照

### 4b. 回测详情页

同样展示 regime_stats 表格（如果有数据）

## Step 5: API 端点

- `GET /api/regimes?start_date=&end_date=` — 查询时间段的阶段分布
- `POST /api/regimes/compute` — 触发计算（或由回测自动触发）

## 文件清单

| # | 文件 | 操作 |
|---|------|------|
| 1 | `api/models/market_regime.py` | NEW — DB模型 |
| 2 | `api/services/regime_service.py` | NEW — 计算+查询服务 |
| 3 | `src/backtest/engine.py` | 修改 — Trade加regime字段 |
| 4 | `src/backtest/portfolio_engine.py` | 修改 — 接收regime_map, 统计regime_stats |
| 5 | `api/services/ai_lab_engine.py` | 修改 — 集成regime |
| 6 | `api/models/ai_lab.py` | 修改 — ExperimentStrategy加regime_stats |
| 7 | `api/models/backtest.py` | 修改 — BacktestRun加regime_stats |
| 8 | `api/main.py` | 修改 — 新表migration |
| 9 | `web/src/app/lab/page.tsx` | 修改 — 策略详情展示regime表格 |
| 10 | `web/src/app/backtest/page.tsx` | 修改 — 回测详情展示regime表格 |
| 11 | `web/src/types/index.ts` | 修改 — 类型扩展 |

## 构建顺序

1. Step 1 (数据层) → 可独立测试
2. Step 2 (引擎集成) → 依赖 Step 1
3. Step 3 (AI Lab) → 依赖 Step 2
4. Step 4-5 (前端+API) → 依赖 Step 3
