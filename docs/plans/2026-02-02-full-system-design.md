# A股量化交易系统 - 完整设计文档

**日期**: 2026-02-02
**版本**: 2.0
**作者**: Allen Qiang

---

## 目录

1. [系统概述](#1-系统概述)
2. [核心决策汇总](#2-核心决策汇总)
3. [第一阶段：数据层](#3-第一阶段数据层)
4. [第二阶段：策略层](#4-第二阶段策略层)
5. [第三阶段：风控层](#5-第三阶段风控层)
6. [第四阶段：回测层+应用层](#6-第四阶段回测层应用层)
7. [项目结构](#7-项目结构)
8. [技术栈](#8-技术栈)
9. [开发路线图](#9-开发路线图)

---

## 1. 系统概述

### 1.1 目标

设计并开发一套基于A股市场的股票交易辅助系统：

- **年化收益率**: >100%（资金翻倍）
- **最大回撤**: <30%
- **使用场景**: 自用工具，辅助交易决策

### 1.2 核心策略

- **波段交易**: 捕捉中短期价格波动
- **趋势跟踪**: 跟随中长期趋势
- **AI增强**: XGBoost模型评估信号有效性

### 1.3 系统架构

```
┌─────────────────────────────────────────┐
│        应用层 (Application Layer)        │
│  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ Scheduler│  │Dashboard │  │  CLI   │ │
│  └──────────┘  └──────────┘  └────────┘ │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│        回测层 (Backtest Layer)          │
│  ┌──────────────┐  ┌─────────────────┐  │
│  │BacktestEngine│  │PerformanceAnalyzer│
│  └──────────────┘  └─────────────────┘  │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│         风控层 (Risk Layer)             │
│  ┌──────────┐ ┌──────────┐ ┌─────────┐  │
│  │RiskEngine│ │ Position │ │StopLoss │  │
│  └──────────┘ └──────────┘ └─────────┘  │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│       策略层 (Strategy Layer)           │
│  ┌──────────┐ ┌────────┐ ┌───────────┐  │
│  │Indicators│ │Signals │ │ ML Models │  │
│  └──────────┘ └────────┘ └───────────┘  │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│         数据层 (Data Layer)             │
│  ┌──────────┐ ┌────────┐ ┌───────────┐  │
│  │Collector │ │Storage │ │ Pipeline  │  │
│  └──────────┘ └────────┘ └───────────┘  │
└─────────────────────────────────────────┘
```

---

## 2. 核心决策汇总

| 阶段 | 决策点 | 选择 | 理由 |
|------|--------|------|------|
| **数据层** | 股票池规模 | 全市场3000+只 | 不错过任何机会 |
| | 信号生成时机 | 当晚19:00-22:00 | 充足决策时间 |
| | 新闻分析 | 简单规则法 | 快速实现，易于调试 |
| | 数据存储 | Parquet + SQLite | 性能与简单性平衡 |
| **策略层** | 技术指标库 | TA-Lib | 性能最优 |
| | 信号生成粒度 | 全量计算 | 简单直接 |
| | XGBoost目标 | 多分类5档 | 信号更精细 |
| | 参数管理 | 策略类封装+配置文件 | 便于测试和优化 |
| **风控层** | Risk状态切换 | 滞后确认(连续2天) | 避免噪音干扰 |
| | 仓位分配 | 信号强度+波动率调整 | 平衡收益和风险 |
| | 止损机制 | 混合方式 | 固定止损+ATR跟踪+阶梯止盈 |
| **应用层** | 回测引擎 | 混合方式 | 向量化+事件驱动 |
| | Web框架 | Streamlit | 快速出MVP |

---

## 3. 第一阶段：数据层

### 3.1 模块结构

```
src/
├── data_collector/               # 数据采集
│   ├── base_collector.py        # 采集器抽象基类
│   ├── tushare_collector.py     # TuShare采集器（主）
│   ├── akshare_collector.py     # AkShare采集器（备用）
│   ├── collector_manager.py     # 多源管理器（容灾切换）
│   └── news_crawler.py          # 新闻爬虫
│
├── data_storage/                 # 数据存储
│   ├── database.py              # SQLite数据库管理
│   └── parquet_storage.py       # Parquet文件存储
│
├── data_pipeline/                # 数据管道
│   └── daily_updater.py         # 每日更新器
│
└── utils/                        # 工具模块
    ├── config.py                # 配置加载器
    └── logger.py                # 日志工具
```

### 3.2 数据采集

**多源策略**:
- 主数据源: TuShare（付费）
- 备用源: AkShare、Baostock
- 容灾: 主源失败自动切换

**采集内容**:
- 日线K线数据（3000+股票）
- 指数数据（上证、深证、创业板等）
- 资金流数据（主力净流入）
- 基本面数据（PE、PB、市值）
- 财经新闻（前20条标题）

**采集器基类设计**:
```python
class BaseCollector(ABC):
    """数据采集器抽象基类"""

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _retry(self, func, *args, **kwargs):
        """带重试的函数调用"""
        # 自动重试机制
        pass

    @abstractmethod
    def _fetch_stock_list(self) -> pd.DataFrame:
        pass

    @abstractmethod
    def _fetch_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        pass
```

### 3.3 数据存储

**混合存储方案**:

```
data/
├── market_data/               # Parquet文件（历史K线）
│   ├── daily/
│   │   ├── 2023.parquet
│   │   ├── 2024.parquet
│   │   └── 2025.parquet
│   ├── index/
│   └── money_flow/
└── business.db               # SQLite（业务数据）
    ├── stock_list            # 股票列表
    ├── data_update_log       # 更新日志
    ├── news_sentiment        # 新闻情绪
    ├── signals               # 交易信号
    ├── positions             # 持仓记录
    └── trades                # 交易记录
```

### 3.4 新闻情绪分析

**简单规则法**:
```python
POSITIVE_KEYWORDS = ["大涨", "涨停", "突破", "新高", "利好", ...]
NEGATIVE_KEYWORDS = ["暴跌", "跌停", "崩盘", "恐慌", "监管", ...]

def analyze_sentiment(text: str) -> float:
    """返回0-100情绪分数，50为中性"""
    score = 50
    score += positive_count * 8
    score -= negative_count * 10
    return max(0, min(100, score))
```

---

## 4. 第二阶段：策略层

### 4.1 模块结构

```
src/
├── indicators/                   # 技术指标（基于TA-Lib）
│   ├── base_indicator.py        # 指标基类
│   ├── trend_indicators.py      # MA/EMA/MACD/ADX
│   ├── momentum_indicators.py   # RSI/KDJ
│   ├── volume_indicators.py     # OBV/VWAP
│   └── indicator_calculator.py  # 批量计算器
│
├── signals/                      # 信号生成
│   ├── base_signal.py           # 信号基类（5档评分）
│   ├── swing_trading.py         # 波段交易策略
│   ├── trend_following.py       # 趋势跟踪策略
│   ├── signal_combiner.py       # 信号组合器
│   └── daily_signal_generator.py # 每日信号生成器
│
└── ml_models/                    # 机器学习
    ├── feature_engineering.py   # 特征工程
    ├── model_trainer.py         # 模型训练
    └── model_predictor.py       # 模型预测
```

### 4.2 信号等级定义

```python
class SignalLevel(IntEnum):
    STRONG_BUY = 5    # 强买 (80-100分)
    WEAK_BUY = 4      # 弱买 (60-80分)
    HOLD = 3          # 持有 (40-60分)
    WEAK_SELL = 2     # 弱卖 (20-40分)
    STRONG_SELL = 1   # 强卖 (0-20分)
```

### 4.3 波段交易策略

**买入条件**（满足越多，分数越高）:
1. 收盘价 > MA20 (+20分)
2. MACD金叉 (+25分)
3. 成交量 > 5日均量×1.5 (+15分)
4. 收盘价在当日区间上半部 (+10分)
5. RSI在30-70之间 (+10分)

**卖出条件**（相反逻辑）

### 4.4 趋势跟踪策略

**买入条件**:
1. 收盘价 > MA60 (+20分)
2. ADX > 25（趋势明确）(+20分)
3. ADX > 40（强趋势）(+15分)
4. +DI > -DI（上升趋势）(+15分)
5. MA20 > MA60（均线多头）(+10分)

### 4.5 XGBoost模型

**多分类5档**:
- 标签0: 强卖（未来5日收益 < -5%）
- 标签1: 弱卖（-5% ~ -2%）
- 标签2: 持有（-2% ~ +2%）
- 标签3: 弱买（+2% ~ +5%）
- 标签4: 强买（> +5%）

**特征分组**:
- 价格特征: 5/20/60日涨幅、价格vs均线
- 量价特征: 量比、换手率、成交额排名
- 动量特征: RSI、MACD、ADX、KDJ
- 基本面: PE/PB百分位、市值
- 市场特征: 大盘涨跌、北向资金

**ML评分计算**:
```python
ml_score = (prob_strong_buy * 100 + prob_weak_buy * 75
          + prob_hold * 50 + prob_weak_sell * 25
          + prob_strong_sell * 0)
```

### 4.6 信号组合

**权重分配**:
- 波段策略: 35%
- 趋势策略: 35%
- ML评分: 30%

**最终信号**:
```python
combined_score = (swing_score * 0.35 + trend_score * 0.35 + ml_score * 0.30)
```

---

## 5. 第三阶段：风控层

### 5.1 模块结构

```
src/
├── risk_engine/                  # 风控引擎
│   ├── risk_status.py           # 风险状态管理
│   ├── market_analyzer.py       # 市场状态分析
│   └── risk_calculator.py       # 综合风险评分
│
├── position_manager/             # 仓位管理
│   ├── position_sizer.py        # 仓位计算器
│   ├── portfolio.py             # 组合管理
│   └── allocation.py            # 仓位分配算法
│
└── stop_loss/                    # 止损管理
    ├── stop_loss_tracker.py     # 止损跟踪器
    └── trailing_stop.py         # 移动止损
```

### 5.2 风险状态定义

```python
class RiskLevel(Enum):
    RISK_ON = "risk_on"      # 积极进攻
    NEUTRAL = "neutral"       # 中性观望
    RISK_OFF = "risk_off"    # 防御模式
```

**三维度评分**（每维度0-100）:

1. **新闻情绪评分**
   - 爬取财经新闻标题
   - 关键词匹配计算情绪分

2. **指数趋势评分**
   - 上证>60日均线 +30分
   - 5日涨幅>2% +20分
   - ADX>25 +30分

3. **资金流评分**
   - 北向资金净流入>50亿 +40分
   - 主力净流入占比>60% +30分

**状态判断**:
- 平均分 ≥ 70 → **Risk-on**
- 平均分 40-69 → **Neutral**
- 平均分 < 40 → **Risk-off**

### 5.3 状态切换（滞后确认）

```python
class RiskStatusManager:
    CONFIRM_DAYS = 2  # 需要连续2天确认

    def update(self, new_score, trade_date):
        suggested_level = self._score_to_level(new_score)

        if suggested_level != current_level:
            if pending_days >= CONFIRM_DAYS:
                # 确认切换
                return switch_status()
            else:
                # 继续等待确认
                return update_pending()
```

### 5.4 仓位管理

**配置参数**:
```python
@dataclass
class PositionConfig:
    total_capital: float           # 总资金
    max_position_pct: float = 0.60 # 最大总仓位 60%
    max_single_pct: float = 0.25   # 单股最大仓位 25%
    min_single_pct: float = 0.05   # 单股最小仓位 5%
    max_holdings: int = 10         # 最大持股数量
```

**仓位分配算法**（信号强度+波动率调整）:
```python
# 信号强度权重
score_weight = score / sum(scores)

# 波动率调整因子（ATR越大，因子越小）
vol_factor = median(atr) / atr

# 最终权重
final_weight = score_weight * vol_factor
```

**风险状态调整**:
| 状态 | 总仓位 | 持股数量 | 备注 |
|------|--------|----------|------|
| Risk-on | 60% | 6-10只 | 按信号加权分配 |
| Neutral | 30-40% | 4-6只 | 只买强信号(>80分) |
| Risk-off | 0% | - | 不开新仓，执行止损 |

### 5.5 止损机制（混合方式）

**三种止损取最高值**:

1. **固定止损**: `成本价 × 95%`（亏5%卖出）

2. **ATR跟踪止损**: `最高价 - 2×ATR`

3. **阶梯止盈止损**:
   | 盈利比例 | 止损线 |
   |---------|--------|
   | 10% | 成本价+5% |
   | 20% | 成本价+12% |
   | 30% | 成本价+20% |
   | 50% | 成本价+35% |

```python
stop_price = max(fixed_stop, atr_stop, tier_stop)
```

---

## 6. 第四阶段：回测层+应用层

### 6.1 模块结构

```
src/
├── backtest_engine/              # 回测引擎
│   ├── backtest_runner.py       # 回测主引擎
│   ├── order_simulator.py       # 订单模拟器
│   ├── portfolio_tracker.py     # 组合跟踪器
│   └── performance_analyzer.py  # 绩效分析
│
├── scheduler/                    # 定时调度
│   ├── task_scheduler.py        # 任务调度器
│   └── daily_jobs.py            # 每日任务
│
└── dashboard/                    # Streamlit仪表盘
    ├── app.py                   # 主入口
    ├── pages/
    │   ├── home.py              # 今日信号
    │   ├── portfolio.py         # 持仓管理
    │   ├── backtest.py          # 回测结果
    │   ├── risk.py              # 风险监控
    │   └── settings.py          # 系统设置
    └── components/
        ├── signal_table.py
        ├── kline_chart.py
        └── metrics_card.py
```

### 6.2 回测引擎（混合方式）

**Phase 1: 向量化预计算**（快）
- 加载全部历史数据
- 批量计算所有技术指标
- 批量生成所有日期的信号

**Phase 2: 事件驱动模拟**（准）
```python
for trade_date in trade_dates:
    # 1. 更新持仓价格
    portfolio.update_prices(prices)

    # 2. 检查止损
    stop_orders = check_stop_loss(portfolio)

    # 3. 获取当日信号和风险状态
    signals = all_signals[trade_date]
    risk_status = all_risk_status[trade_date]

    # 4. 生成调仓订单
    rebalance_orders = generate_orders(portfolio, signals, risk_status)

    # 5. 模拟成交（含滑点、手续费）
    execute_orders(portfolio, orders, prices)

    # 6. 记录每日快照
    portfolio.record_daily_snapshot(trade_date)
```

**订单模拟规则**:
- 成交价: T+1日开盘价
- 滑点: 0.5%
- 手续费: 万三
- 涨跌停: 不成交

### 6.3 绩效指标

```python
@dataclass
class PerformanceMetrics:
    # 收益指标
    total_return: float           # 总收益率
    annual_return: float          # 年化收益率
    monthly_returns: List[float]  # 月度收益率

    # 风险指标
    max_drawdown: float           # 最大回撤
    max_drawdown_duration: int    # 最大回撤持续天数
    volatility: float             # 年化波动率

    # 风险调整收益
    sharpe_ratio: float           # 夏普比率
    sortino_ratio: float          # 索提诺比率
    calmar_ratio: float           # 卡玛比率

    # 交易统计
    total_trades: int             # 总交易次数
    win_rate: float               # 胜率
    profit_factor: float          # 盈亏比
    avg_holding_days: float       # 平均持仓天数
```

### 6.4 定时任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 15:30 | 数据采集 | 行情、指数、资金流 |
| 16:00 | 新闻采集 | 财经新闻+情绪分析 |
| 19:00 | 信号生成 | 全市场信号计算 |
| 周六10:00 | 周度回测 | 更新策略绩效 |
| 22:00 | 数据备份 | SQLite+Parquet |

### 6.5 Streamlit仪表盘

**5个页面**:

1. **📊 今日信号**
   - 风险状态、市场情绪
   - 买入信号列表（评分≥60）
   - 卖出信号列表
   - K线图查看

2. **💼 持仓管理**
   - 组合摘要（总资产、收益率、仓位）
   - 当前持仓详情
   - 止损价显示
   - 历史交易记录

3. **📈 回测结果**
   - 权益曲线图
   - 回撤曲线
   - 月度收益热力图
   - 绩效指标卡片

4. **⚠️ 风险监控**
   - 风险状态大字显示
   - 三维度评分详情
   - 最新新闻列表
   - 风险历史趋势

5. **⚙️ 系统设置**
   - 参数配置
   - 手动触发任务
   - 日志查看

---

## 7. 项目结构

```
stockagent/
├── config/
│   ├── config.yaml.example      # 配置模板
│   └── news_keywords.json       # 新闻关键词库
│
├── data/
│   ├── market_data/             # Parquet数据
│   │   ├── daily/
│   │   ├── index/
│   │   └── money_flow/
│   ├── business.db              # SQLite数据库
│   └── backups/
│
├── src/
│   ├── __init__.py
│   ├── main.py                  # CLI入口
│   │
│   ├── utils/
│   │   ├── config.py
│   │   └── logger.py
│   │
│   ├── data_collector/
│   │   ├── base_collector.py
│   │   ├── tushare_collector.py
│   │   ├── akshare_collector.py
│   │   ├── collector_manager.py
│   │   └── news_crawler.py
│   │
│   ├── data_storage/
│   │   ├── database.py
│   │   └── parquet_storage.py
│   │
│   ├── data_pipeline/
│   │   └── daily_updater.py
│   │
│   ├── indicators/
│   │   ├── base_indicator.py
│   │   ├── trend_indicators.py
│   │   ├── momentum_indicators.py
│   │   ├── volume_indicators.py
│   │   └── indicator_calculator.py
│   │
│   ├── signals/
│   │   ├── base_signal.py
│   │   ├── swing_trading.py
│   │   ├── trend_following.py
│   │   ├── signal_combiner.py
│   │   └── daily_signal_generator.py
│   │
│   ├── ml_models/
│   │   ├── feature_engineering.py
│   │   ├── model_trainer.py
│   │   ├── model_predictor.py
│   │   └── models/
│   │
│   ├── risk_engine/
│   │   ├── risk_status.py
│   │   ├── market_analyzer.py
│   │   └── risk_calculator.py
│   │
│   ├── position_manager/
│   │   ├── position_sizer.py
│   │   ├── portfolio.py
│   │   └── allocation.py
│   │
│   ├── stop_loss/
│   │   ├── stop_loss_tracker.py
│   │   └── trailing_stop.py
│   │
│   ├── backtest_engine/
│   │   ├── backtest_runner.py
│   │   ├── order_simulator.py
│   │   ├── portfolio_tracker.py
│   │   └── performance_analyzer.py
│   │
│   └── scheduler/
│       ├── task_scheduler.py
│       └── daily_jobs.py
│
├── dashboard/
│   ├── app.py
│   ├── pages/
│   │   ├── home.py
│   │   ├── portfolio.py
│   │   ├── backtest.py
│   │   ├── risk.py
│   │   └── settings.py
│   └── components/
│       ├── signal_table.py
│       ├── kline_chart.py
│       └── metrics_card.py
│
├── tests/
│   ├── test_config.py
│   ├── test_database.py
│   ├── test_parquet_storage.py
│   ├── test_collectors.py
│   ├── test_indicators.py
│   ├── test_signals.py
│   ├── test_risk_engine.py
│   ├── test_position_manager.py
│   ├── test_stop_loss.py
│   └── test_backtest.py
│
├── notebooks/                    # 研究用Jupyter笔记本
│   ├── exploratory_analysis.ipynb
│   └── model_training.ipynb
│
├── docs/
│   └── plans/
│       ├── 2026-02-02-astock-trading-system-design.md
│       ├── 2026-02-02-phase1-data-layer.md
│       └── 2026-02-02-full-system-design.md
│
├── logs/
├── requirements.txt
├── run.py                        # 启动脚本
└── README.md
```

---

## 8. 技术栈

```yaml
数据处理:
  - pandas >= 2.0.0
  - numpy >= 1.24.0
  - pyarrow >= 14.0.0       # Parquet读写

数据源:
  - tushare >= 1.2.89       # 主数据源
  - akshare >= 1.12.0       # 备用数据源
  - baostock >= 0.8.8       # 备用数据源
  - requests >= 2.31.0      # HTTP请求
  - beautifulsoup4 >= 4.12.0 # 新闻爬虫

技术分析:
  - TA-Lib                  # 技术指标（需要brew install ta-lib）

机器学习:
  - xgboost >= 2.0.0
  - scikit-learn >= 1.3.0

数据库:
  - sqlite3                 # 内置

任务调度:
  - APScheduler >= 3.10.0

Web界面:
  - streamlit >= 1.29.0
  - plotly >= 5.18.0

工具:
  - pyyaml >= 6.0.0
  - loguru >= 0.7.0
  - pytest >= 7.4.0
```

---

## 9. 开发路线图

### 阶段1: 数据基础（2-3周）

- [ ] 项目初始化（目录结构、依赖）
- [ ] 配置加载器和日志工具
- [ ] SQLite数据库Schema
- [ ] Parquet存储管理器
- [ ] TuShare采集器
- [ ] AkShare采集器（备用）
- [ ] 采集器管理器（多源切换）
- [ ] 新闻爬虫和情绪分析
- [ ] 每日更新Pipeline
- [ ] CLI主入口

**交付物**: 可运行的数据采集系统，能获取全市场数据

### 阶段2: 策略引擎（3-4周）

- [ ] 技术指标模块（基于TA-Lib）
- [ ] 波段交易信号
- [ ] 趋势跟踪信号
- [ ] 特征工程
- [ ] XGBoost模型训练
- [ ] 模型预测器
- [ ] 信号组合器
- [ ] 每日信号生成器

**交付物**: 能生成全市场每日信号

### 阶段3: 风控系统（2-3周）

- [ ] 风险状态管理器
- [ ] 市场状态分析
- [ ] 仓位计算器
- [ ] 组合管理器
- [ ] 止损跟踪器
- [ ] 移动止损实现

**交付物**: 完整的风控和仓位管理系统

### 阶段4: 回测和应用（3-4周）

- [ ] 回测主引擎
- [ ] 订单模拟器
- [ ] 组合跟踪器
- [ ] 绩效分析器
- [ ] 定时调度器
- [ ] Streamlit仪表盘（5页面）
- [ ] 系统集成测试
- [ ] 部署到Mac Studio

**交付物**: 完整可用的量化交易辅助系统

### 总计: 10-14周（2.5-3.5个月）

---

## 10. 成功指标

### 系统稳定性

- [ ] 数据采集成功率 > 99%
- [ ] 信号生成准时率 > 95%
- [ ] 系统可用性 > 99.5%

### 策略性能（6个月后评估）

**最低目标**:
- 年化收益率 > 50%
- 最大回撤 < 20%
- 夏普比率 > 1.5

**终极目标**:
- 年化收益率 > 100%
- 最大回撤 < 30%
- 夏普比率 > 2.0

---

## 附录: 后续优化方向

1. **策略增强**
   - 加入更多策略（套利、事件驱动）
   - 深度学习模型（LSTM）
   - 策略参数自动优化

2. **数据增强**
   - Level-2行情数据
   - 社交媒体舆情
   - 财报深度分析

3. **系统增强**
   - 分钟级信号（日内交易）
   - React + Lightweight Charts重构前端
   - 移动端App

4. **自动化增强**
   - 模型自动重训练
   - 自动止盈止损执行
   - 异常告警（微信/邮件）
