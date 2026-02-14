# 新闻情绪驱动交易决策系统设计

> 日期: 2026-02-14 | 状态: 已批准

## 目标

用 DeepSeek API 对 AkShare 采集的财经新闻做结构化情绪分析，输出市场情绪分数和事件摘要，作为辅助因子融入现有 `signal_combiner` 的交易信号中。每日盘前+收盘后各分析一次，结果持久化到 DB。个股分析按需触发。

## 方案选择

| 方案 | 描述 | 选择 |
|------|------|------|
| **A: DeepSeek 情绪管道** | 复用已有 DeepSeek + AkShare，改动最小 | **✓ 选中** |
| B: 多 Agent 系统 | 参考 TradingAgents-CN，多 Agent 辩论 | 过度工程化 |
| C: 增强关键词 | 扩充关键词到 200+，纯规则 | 分析质量不够 |

## GitHub 参考项目

| 项目 | Stars | 核心价值 |
|------|-------|---------|
| [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | 17.2k | A股多Agent架构，同技术栈(FastAPI+DeepSeek) |
| [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 18.6k | LoRA微调金融LLM，本地部署参考 |
| [A_Share_investment_Agent](https://github.com/24mlight/A_Share_investment_Agent) | 2.3k | AkShare+FastAPI，Sentiment Agent参考 |
| [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) | 11.5k | LLM每日批量分析管道参考 |

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  现有: AkShare 新闻采集 (news_crawler.py)                     │
│  财联社 + 东方财富 + 新浪 → news_archive 表                    │
└────────────────────┬────────────────────────────────────────┘
                     │ 每日 2 次触发 (08:30 盘前, 15:30 收盘后)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  新增: NewsSentimentEngine (news_sentiment_engine.py)        │
│                                                             │
│  1. 从 news_archive 取最近 N 小时未分析的新闻                  │
│  2. 批量发送到 DeepSeek (每 10 条一批)                        │
│  3. 结构化 JSON 输出: sentiment + events + summary           │
│  4. 存入 news_sentiment_results 表                           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  修改: signal_combiner.py                                    │
│  接入情绪分数 (15% 权重, 已有接口只需调用)                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 数据模型

### 新表: `news_sentiment_results`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | |
| analysis_time | DateTime | 分析时间 |
| period_type | String(20) | "pre_market" / "post_close" |
| news_count | Integer | 本次分析的新闻条数 |
| market_sentiment | Float | -100 ~ +100 |
| confidence | Float | 0 ~ 100 |
| event_tags | JSON | 事件标签列表 |
| key_summary | Text | AI 生成的市场摘要 |
| stock_mentions | JSON | 提到的个股及其情绪 |
| sector_impacts | JSON | 行业影响 |
| raw_response | Text | DeepSeek 原始响应 |

### 新表: `stock_news_sentiment`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | |
| stock_code | String(10) | 股票代码 |
| stock_name | String(50) | 股票名称 |
| analysis_time | DateTime | 分析时间 |
| sentiment | Float | -100 ~ +100 |
| news_count | Integer | 分析的相关新闻数 |
| summary | Text | AI 个股影响分析 |
| valid_until | DateTime | 缓存过期时间 (24h) |

### 修改: `news_archive` 表

新增字段 `sentiment_analyzed` (Boolean, default False) — 标记已被 DeepSeek 分析的新闻。

---

## DeepSeek Prompt

```
你是A股市场分析师。分析以下财经新闻，输出结构化 JSON。

新闻列表:
1. [标题] [来源] [时间]
2. ...

输出格式 (严格 JSON):
{
  "market_sentiment": <-100到+100的整数>,
  "confidence": <0-100>,
  "event_tags": ["标签1", "标签2"],
  "key_summary": "一句话总结",
  "stock_mentions": [
    {"name": "股票名", "sentiment": <-100到+100>, "reason": "原因"}
  ],
  "sector_impacts": [
    {"sector": "行业名", "impact": <-100到+100>, "reason": "原因"}
  ]
}

规则:
- 重大政策(降准/降息/监管)权重最高
- 多条同方向新闻叠加增强信心
- 标题党/重复内容降权
- 无明确方向时 sentiment 接近 0
```

### 批量分析策略

- **批大小**: 10 条新闻/批
- **多批合并**: 加权平均（confidence 越高权重越大）
- **去噪**: 标题相似度 > 0.7 的新闻合并
- **成本**: ~¥0.003/天

---

## 情绪分数 → 信号权重映射

| 市场情绪 | 买入信号影响 | 卖出信号影响 |
|---------|------------|------------|
| > +60 (强乐观) | +15% | -10% |
| +30 ~ +60 | +8% | 不影响 |
| -30 ~ +30 (中性) | 不影响 | 不影响 |
| -60 ~ -30 | -8% | +5% |
| < -60 (强悲观) | -15% | +10% |

---

## 定时调度

| 时间 | 任务 | 分析窗口 |
|------|------|---------|
| 08:30 | `analyze_pre_market()` | 前一日 17:00 ~ 今日 08:30 |
| 15:30 | `analyze_post_close()` | 今日 08:30 ~ 15:30 |

调度方式: 后台线程 + `schedule` 库，不引入 Celery。

容错:
- API 超时/失败 → 重试 2 次，间隔 30 秒
- 全部失败 → 情绪因子缺失时权重归零，信号不受影响
- 新闻为空 → 跳过，情绪分数 = 0

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /api/news/sentiment/latest` | GET | 最新市场情绪分析 |
| `GET /api/news/sentiment/history` | GET | 情绪历史 (?days=30) |
| `POST /api/news/sentiment/analyze` | POST | 手动触发市场情绪分析 |
| `POST /api/news/sentiment/stock/{code}` | POST | 按需个股新闻分析 |

---

## 信号融合改动

`signal_combiner.py` 已有接口，只需在调用处传入：

```python
# daily_signal_generator.py 或 signal_engine.py 中:
latest_sentiment = get_latest_sentiment(db)
if latest_sentiment:
    # 将 -100~+100 映射到 0~100 (combiner 期望的范围)
    score = (latest_sentiment.market_sentiment + 100) / 2
    combiner.combine(..., sentiment_score=score)
```

---

## 前端改动

新闻页顶部新增 "AI 市场情绪" 卡片:
- 情绪分数（大数字 + 颜色渐变）
- 事件标签（badge 列表）
- AI 摘要（一句话）
- 上次分析时间 + 下次分析倒计时

---

## 文件改动汇总

| 操作 | 文件 | 改动 |
|------|------|------|
| 新建 | `api/services/news_sentiment_engine.py` | DeepSeek 调用+prompt+批量分析 |
| 新建 | `api/models/news_sentiment.py` | 2 张新表 SQLAlchemy 模型 |
| 新建 | `api/services/news_scheduler.py` | 定时调度 (盘前/收盘后) |
| 修改 | `api/routers/news.py` | 新增 4 个端点 |
| 修改 | `src/signals/signal_combiner.py` | 接入情绪分数 (~10 行) |
| 修改 | `src/signals/daily_signal_generator.py` | 查询最新情绪传入 combiner |
| 修改 | `api/main.py` | 启动时注册定时任务 |
| 修改 | `web/src/app/news/page.tsx` | 顶部 AI 情绪卡片 |
| 修改 | `web/src/hooks/use-queries.ts` | 新增 sentiment 查询 hook |

**不改动**: `news_crawler.py`(采集不变), `rule_engine.py`(规则不变)
