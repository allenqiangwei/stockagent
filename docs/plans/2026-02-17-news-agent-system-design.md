# 新闻驱动多智能体决策系统 设计文档

## 目标

构建一套基于新闻的多智能体协作系统，从新闻中提取结构化事件，分析板块热度和轮动趋势，生成独立的新闻驱动买卖信号。系统每日运行两次（盘前 08:00 + 晚间 18:00），产出与技术信号并行的"新闻信号"。

## 架构

```
新闻采集层 (已有, 每10分钟)
    ↓
┌─────────────────────────────────────────────────────┐
│             新闻情报多智能体系统 (新建)                  │
│                                                       │
│  [Agent 1: 事件分类师]  ← DeepSeek (批量，低成本)       │
│    新闻 → 事件类型 + 影响等级 + 关联个股/板块             │
│                                                       │
│  [Agent 2: 板块分析师]  ← DeepSeek                     │
│    事件 → 板块热度排名 + 轮动趋势 + 板块内龙头           │
│                                                       │
│  [Agent 3: 个股猎手]    ← DeepSeek                     │
│    事件+板块 → 受益/受损个股 + 买卖信号 + 置信度         │
│                                                       │
│  [Agent 4: 决策合成师]  ← Claude CLI                   │
│    汇总3个Agent → 最终新闻信号列表 + 板块报告            │
│                                                       │
└──────────────┬──────────────────────────────────────┘
               ↓
         news_signals 表 (新建)
               ↓
    信号页面独立展示 "新闻驱动" 标签
```

## 运行时间

| 时段 | 时间 | 分析窗口 | 用途 |
|------|------|---------|------|
| 盘前 | 08:00 | 前一日 15:30 → 当日 08:00 (~16.5h) | 指导当日开盘操作 |
| 晚间 | 18:00 | 当日 08:00 → 18:00 (~10h) | 复盘+次日预判 |

## 数据模型

### 新增表 1: `news_events` — 结构化事件

```sql
CREATE TABLE news_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER,                      -- FK to news_archive.id (nullable, may span multiple news)
    event_type TEXT NOT NULL,             -- 事件类型 (见下方枚举)
    impact_level TEXT NOT NULL,           -- "high" | "medium" | "low"
    impact_direction TEXT NOT NULL,       -- "positive" | "negative" | "neutral"
    affected_codes JSON DEFAULT '[]',     -- 关联股票代码 ["600519", "000858"]
    affected_sectors JSON DEFAULT '[]',   -- 关联板块 ["白酒", "AI概念"]
    summary TEXT NOT NULL,                -- 事件摘要 (1-2句)
    source_titles JSON DEFAULT '[]',      -- 来源新闻标题列表
    analysis_run_id INTEGER,              -- FK to agent_run_log.id
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_news_events_type ON news_events(event_type, created_at);
CREATE INDEX idx_news_events_date ON news_events(created_at);
```

事件类型枚举：
- `policy_positive` / `policy_negative` — 政策利好/利空
- `earnings_positive` / `earnings_negative` — 业绩利好/利空
- `capital_flow` — 资金面变化 (降准降息/外资流入流出)
- `industry_change` — 行业变化 (技术突破/产能变化)
- `market_sentiment` — 市场情绪 (机构观点/分析师评级)
- `breaking_event` — 突发事件
- `corporate_action` — 公司治理 (高管变动/回购增持)
- `concept_hype` — 概念题材炒作

### 新增表 2: `sector_heat` — 板块热度快照

```sql
CREATE TABLE sector_heat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_time TIMESTAMP NOT NULL,
    sector_name TEXT NOT NULL,
    sector_type TEXT NOT NULL,            -- "concept" | "industry"
    heat_score REAL NOT NULL,             -- -100 ~ +100
    news_count INTEGER DEFAULT 0,         -- 本轮涉及新闻数
    trend TEXT DEFAULT 'flat',            -- "rising" | "falling" | "flat"
    top_stocks JSON DEFAULT '[]',         -- 板块内推荐股票 [{code, name, reason}]
    event_summary TEXT DEFAULT '',        -- 驱动事件摘要
    analysis_run_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sector_heat_time ON sector_heat(snapshot_time DESC);
CREATE INDEX idx_sector_heat_name ON sector_heat(sector_name, snapshot_time);
```

### 新增表 3: `news_signals` — 新闻驱动交易信号

```sql
CREATE TABLE news_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,              -- YYYY-MM-DD
    stock_code TEXT NOT NULL,
    stock_name TEXT DEFAULT '',
    action TEXT NOT NULL,                  -- "buy" | "sell" | "watch"
    signal_source TEXT NOT NULL,           -- "news_event" | "sector_rotation" | "sentiment_shift"
    confidence REAL DEFAULT 0.0,           -- 0-100
    reason TEXT NOT NULL,
    related_event_ids JSON DEFAULT '[]',   -- FK list to news_events.id
    sector_name TEXT DEFAULT '',           -- 关联板块
    analysis_run_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_news_signals_date ON news_signals(trade_date DESC);
CREATE INDEX idx_news_signals_code ON news_signals(stock_code, trade_date);
CREATE UNIQUE INDEX uq_news_signal ON news_signals(trade_date, stock_code, signal_source);
```

### 新增表 4: `agent_run_log` — 智能体运行记录

```sql
CREATE TABLE agent_run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time TIMESTAMP NOT NULL,
    period_type TEXT NOT NULL,             -- "pre_market" | "evening"
    agent_name TEXT NOT NULL,              -- "event_classifier" | "sector_analyst" | "stock_hunter" | "decision_synthesizer"
    input_news_count INTEGER DEFAULT 0,
    output_summary TEXT DEFAULT '',
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    duration_ms INTEGER DEFAULT 0,
    status TEXT DEFAULT 'completed',       -- "completed" | "error"
    error_message TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Agent 详细设计

### Agent 1: 事件分类师 (EventClassifier)

**LLM**: DeepSeek
**输入**: 最近 N 小时的未分析新闻 (从 `news_archive`)
**输出**: `news_events` 记录

**Prompt 结构**:
```
你是A股市场事件分析专家。将以下新闻分类为结构化事件。

新闻列表 (JSON):
[{title, content, source, publish_time}, ...]

任务:
1. 合并相同事件的多条报道
2. 为每个事件分类: event_type, impact_level, impact_direction
3. 识别受影响的股票代码和板块名称
4. 写一句话事件摘要

输出 JSON:
[{
  "event_type": "policy_positive",
  "impact_level": "high",
  "impact_direction": "positive",
  "affected_codes": ["600519"],
  "affected_sectors": ["白酒", "消费"],
  "summary": "国务院发布促消费政策...",
  "source_titles": ["标题1", "标题2"]
}, ...]
```

**批处理**: 每50条新闻一批，多批结果合并去重。

### Agent 2: 板块分析师 (SectorAnalyst)

**LLM**: DeepSeek
**输入**: Agent 1 的事件列表 + 概念板块映射 (从 `stock_concepts`)
**输出**: `sector_heat` 记录

**Prompt 结构**:
```
你是A股板块轮动分析专家。基于以下事件评估板块热度。

事件列表: [...]
可用板块: [板块名: 成分股数量, ...]

任务:
1. 评估每个涉及板块的热度 (-100~+100)
2. 判断趋势: rising/falling/flat (对比最近3日)
3. 在热门板块中推荐龙头股
4. 总结驱动事件

输出 JSON:
[{
  "sector_name": "AI概念",
  "sector_type": "concept",
  "heat_score": 75,
  "trend": "rising",
  "top_stocks": [{"code": "000977", "name": "浪潮信息", "reason": "AI算力龙头"}],
  "event_summary": "两会政策提及AI发展..."
}, ...]
```

### Agent 3: 个股猎手 (StockHunter)

**LLM**: DeepSeek
**输入**: 事件列表 + 板块热度 + 用户自选股
**输出**: `news_signals` 记录

**Prompt 结构**:
```
你是A股个股筛选专家。基于事件和板块分析，生成新闻驱动买卖信号。

事件摘要: [...]
板块热度 TOP10: [...]
用户自选股: [...]

规则:
- 仅输出置信度 > 60 的信号
- buy: 重大利好事件 + 板块趋势向上 + 个股位置合理
- sell: 重大利空事件 + 板块降温 + 风险因素
- watch: 中等利好但需要确认

输出 JSON:
[{
  "stock_code": "000977",
  "stock_name": "浪潮信息",
  "action": "buy",
  "signal_source": "sector_rotation",
  "confidence": 78,
  "reason": "AI板块持续升温，浪潮信息作为算力龙头直接受益...",
  "sector_name": "AI概念"
}, ...]
```

### Agent 4: 决策合成师 (DecisionSynthesizer)

**LLM**: Claude CLI
**输入**: Agent 1-3 的全部输出
**输出**: 审核后的最终信号 + 板块简报

**职责**:
1. 交叉验证: 检查信号与事件逻辑是否自洽
2. 风险过滤: 剔除矛盾信号或低质量推荐
3. 信号排序: 按置信度和事件重要性排序
4. 生成简报: 2-3 段总结当前新闻面形势

## Pipeline 实现

### 服务层: `api/services/news_agent_engine.py`

```python
class NewsAgentEngine:
    """Orchestrates the 4-agent news analysis pipeline."""

    def run_analysis(self, period_type: str) -> dict:
        """Run full pipeline: classify → sector → stocks → synthesize."""
        # 1. Fetch unanalyzed news
        # 2. Agent 1: Event classification (DeepSeek, batched)
        # 3. Agent 2: Sector heat analysis (DeepSeek)
        # 4. Agent 3: Stock signal generation (DeepSeek)
        # 5. Agent 4: Decision synthesis (Claude CLI)
        # 6. Save all results to DB
        # 7. Return summary
```

### 调度: `api/services/news_agent_scheduler.py`

```python
class NewsAgentScheduler:
    """Schedules news agent pipeline at 08:00 and 18:00."""

    pre_market_hour = 8
    pre_market_minute = 0
    evening_hour = 18
    evening_minute = 0
```

### API 端点: `api/routers/news_signals.py`

```
GET  /api/news-signals/today?date=          — 今日新闻信号
GET  /api/news-signals/history?page=&size=  — 历史新闻信号
GET  /api/news-signals/sectors?date=        — 板块热度排名
GET  /api/news-signals/events?date=         — 事件列表
POST /api/news-signals/analyze              — 手动触发分析
GET  /api/news-signals/analyze/poll?jobId=  — 轮询分析进度
GET  /api/news-signals/runs                 — 运行记录
```

### 前端

**信号页面 (`/signals`)**:
- 新增 "新闻驱动" Tab，与现有 "今日信号" / "历史" 并列
- 新闻信号卡片用独特的颜色/图标区分
- 每张卡片显示: 股票名+代码, action, 置信度, 原因, 来源板块

**新增 "板块热度" 页面 (`/sectors`)**:
- 板块热度排行榜 (横向条形图)
- 点击板块展开: 驱动事件 + 板块内推荐股
- 历史趋势曲线 (过去7天热度变化)

**AI 报告页面 (`/ai`)**:
- 报告新增 "新闻面分析" 章节
- 包含板块轮动摘要和重点事件

## 前置依赖

1. **概念板块数据同步** — `stock_concepts` 表当前为空，需通过 AkShare 同步东财概念板块数据
2. **DeepSeek API** — 已有，复用现有配置
3. **Claude CLI** — 已有，复用 fire-and-forget 模式

## 成本估算

| 环节 | 调用量/天 | 估算日成本 |
|------|----------|-----------|
| 事件分类 (DeepSeek) | 2次 × ~4批 | ~¥0.5 |
| 板块分析 (DeepSeek) | 2次 | ~¥0.2 |
| 个股猎手 (DeepSeek) | 2次 | ~¥0.3 |
| 决策合成 (Claude CLI) | 2次 × ~$0.3 | ~¥4.0 |
| **日合计** | | **~¥5/天** |

## 关键参考项目

- [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) — 多智能体架构参考
- [FinnewsHunter](https://github.com/DemonDamon/FinnewsHunter) — 新闻情报+Alpha因子挖掘
- [ProsusAI/finBERT](https://github.com/ProsusAI/finBERT) — 金融情绪分析基础模型
- [DISC-FinLLM](https://github.com/FudanDISC/DISC-FinLLM) — 中文金融大模型
- [FinBERT-LSTM](https://github.com/xraptorgg/FinBERT-LSTM) — 情绪+价格预测 pipeline
