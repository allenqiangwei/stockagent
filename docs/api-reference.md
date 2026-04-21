# StockAgent API 接口文档

Base URL: `http://{host}:8050`

---

## 自选股 & 持仓 (stocks)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stocks` | 搜索/列出股票（分页） |
| POST | `/api/stocks/sync` | 从远程 API 同步 A 股股票列表 |
| POST | `/api/stocks/sync-boards` | 同步行业+概念板块（每日限一次） |
| GET | `/api/stocks/watchlist` | 获取自选股列表（含最新价格和涨跌幅） |
| POST | `/api/stocks/watchlist` | 添加自选股 `{"stock_code": "300027"}` |
| DELETE | `/api/stocks/watchlist/{code}` | 删除自选股 |
| GET | `/api/stocks/portfolio` | 获取手动组合持仓（含最新价和浮盈） |
| POST | `/api/stocks/portfolio` | 添加/更新手动组合持仓 |
| DELETE | `/api/stocks/portfolio/{code}` | 删除手动组合持仓 |

## AI 交易持仓 (bot-trading)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/bot/portfolio` | AI 交易当前持仓（含最新价、浮盈、策略、SL/TP/MHD） |
| GET | `/api/bot/summary` | AI 交易总览（总投入、市值、盈亏统计） |
| GET | `/api/bot/trades?stock_code=X` | 交易记录（买卖明细，可按股票过滤） |
| GET | `/api/bot/trades/{code}/timeline` | 单只股票完整交易时间线 |
| GET | `/api/bot/plans?status=pending` | 交易计划列表（含 confidence 分数，按置信度排序） |
| GET | `/api/bot/plans/pending` | 待执行计划（按置信度降序） |
| GET | `/api/bot/reviews?limit=50` | 已完结独立交易记录（含策略ID、退出原因、PnL） |
| PUT | `/api/bot/reviews/{id}/update` | 更新复盘内容 |
| GET | `/api/bot/diary/{YYYY-MM-DD}` | 指定日期的完整交易日记 |

## TDX 行情数据 (tdx)

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/tdx/quotes` | 实时行情（盘中实时，盘后为收盘价，含五档买卖盘） | `codes=300027,600519` (最多50) |
| GET | `/api/tdx/klines` | 个股K线（多频率，默认前复权） | `code, start, end, freq=d/5m/15m/30m/60m/w/m, adjust=qfq/none` |
| GET | `/api/tdx/index/klines` | 指数日线 | `code=000001.SH, start, end` |
| GET | `/api/tdx/minute` | 分时数据（逐分钟价格+成交量） | `code, date=YYYYMMDD(空=当天)` |
| GET | `/api/tdx/transactions` | 逐笔成交明细（buyorsell: 0=买,1=卖,2=集合竞价） | `code, date, offset=0, limit=100` |
| GET | `/api/tdx/finance` | 财务简要（总资产/净资产/营收/净利润/每股净资产/股东人数等） | `code` |
| GET | `/api/tdx/company` | 公司资料详情（文本） | `code, category=公司概况/财务分析/龙虎榜单/...` |
| GET | `/api/tdx/company/categories` | 公司资料可用分类列表 | `code` |
| GET | `/api/tdx/xdxr` | 除权除息信息（分红/送股/配股历史） | `code` |
| GET | `/api/tdx/boards/industry` | 行业板块分类 `{行业名: [股票代码]}` | 无 |
| GET | `/api/tdx/boards/concept` | 概念板块分类 `{概念名: [股票代码]}` | 无 |
| GET | `/api/tdx/stocks` | 全部 A 股股票列表 | 无 |

## 行情 & 指标 (market)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/market/quote/{code}` | 获取股票最新报价 |
| GET | `/api/market/kline/{code}` | 获取股票 K 线数据 |
| GET | `/api/market/indicators/{code}` | 获取计算后的技术指标值 |
| GET | `/api/market/index-kline/{code}` | 获取指数 K 线（含周度市场状态标签） |
| GET | `/api/market/index-list` | 可用指数代码和名称列表 |
| GET | `/api/market/trading-day` | 查询某日是否交易日，返回前/后交易日 |

## 信号 (signals)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/signals/today?date=YYYY-MM-DD` | 获取某日信号（默认今天，无信号自动回溯） |
| GET | `/api/signals/meta` | 信号元数据（最新生成时间、调度信息） |
| GET | `/api/signals/history?page=1&size=20` | 分页信号历史（可按股票/日期过滤） |
| POST | `/api/signals/generate` | 手动触发信号生成 |
| POST | `/api/signals/generate-stream` | 信号生成（SSE 进度流） |

## 新闻 & 情绪 (news)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/news/latest` | 最新新闻列表 + 情绪概览 |
| GET | `/api/news/stats` | 新闻统计（总量、各来源分布） |
| GET | `/api/news/archive?keyword=X&start_date=Y&end_date=Z` | 历史新闻查询（关键字搜索标题和内容） |
| GET | `/api/news/related/{code}` | 个股相关新闻（按名称、行业、概念匹配） |
| GET | `/api/news/sentiment/latest` | 最新市场情绪分析结果 |
| GET | `/api/news/sentiment/history?days=7` | 情绪历史走势 |
| POST | `/api/news/sentiment/analyze` | 手动触发市场情绪分析 |
| POST | `/api/news/sentiment/stock/{code}` | 手动触发个股情绪分析（缓存24h） |

## 新闻信号 (news-signals)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/news-signals/today?date=YYYY-MM-DD` | 当日新闻驱动信号 |
| GET | `/api/news-signals/history` | 分页新闻信号历史 |
| GET | `/api/news-signals/sectors` | 板块热度排名 |
| GET | `/api/news-signals/events` | 新闻事件列表 |
| POST | `/api/news-signals/analyze` | 手动触发新闻分析 |
| GET | `/api/news-signals/analyze/poll?job_id=X` | 轮询分析进度 |
| GET | `/api/news-signals/runs` | 分析运行日志 |

## 置信度 & Beta 因子 (beta-factor)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/beta/confidence/model` | 当前 Confidence 模型状态（版本、AUC、Brier、系数） |
| POST | `/api/beta/confidence/train` | 手动触发 Confidence 模型重训练 |
| GET | `/api/beta/confidence/predict?alpha=X&gamma=Y&...` | 预测单个信号的置信度分数 |
| GET | `/api/beta/signal-grader/calibration` | 信号分级校准报告（bin 级胜率） |
| POST | `/api/beta/signal-grader/calibrate` | 手动触发信号分级重校准 |
| GET | `/api/beta/signal-grader/grade?alpha=X&gamma=Y` | 查询单个信号的分级 |
| GET | `/api/beta/snapshots?stock_code=X` | Beta 因子快照列表 |
| GET | `/api/beta/reviews` | Beta 因子复盘列表 |
| GET | `/api/beta/tracks` | Beta 每日追踪记录 |
| GET | `/api/beta/insights/active` | 可用 Beta 洞察（用于 AI 分析） |
| POST | `/api/beta/insights/aggregate` | 手动触发 Beta 洞察聚合 |
| GET | `/api/beta/model/status` | Beta XGBoost 模型状态 |
| POST | `/api/beta/model/train` | 手动触发 XGBoost 模型训练 |
| GET | `/api/beta/plans/ranked?plan_date=X` | Beta 评分排名的交易计划 |
| GET | `/api/beta/scorecard?codes=X,Y` | 候选股票的 Beta 记分卡 |

## AI 分析 (ai-analyst)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ai/scheduler-status` | 数据同步调度器状态（运行中/上次/下次运行时间） |
| POST | `/api/ai/sync-data?trade_date=YYYY-MM-DD` | 手动触发数据同步（日线+交易执行+信号生成） |
| GET | `/api/ai/reports` | AI 分析报告列表 |
| GET | `/api/ai/reports/{id}` | 单篇报告详情 |
| GET | `/api/ai/reports/date/{YYYY-MM-DD}` | 按日期获取报告 |
| GET | `/api/ai/reports/dates` | 有报告的日期列表（用于日历） |
| GET | `/api/ai/reports/{id}/pdf` | 下载报告 PDF |
| POST | `/api/ai/reports/save` | 保存 AI 分析报告 |
| DELETE | `/api/ai/reports/{id}` | 删除报告 |
| POST | `/api/ai/analyze?date=YYYY-MM-DD` | 手动触发 AI 日报分析 |
| POST | `/api/ai/chat` | AI 分析师对话 |
| GET | `/api/ai/chat/sessions` | 对话历史列表 |
| GET | `/api/ai/chat/sessions/{id}` | 单个对话的完整历史 |

## AI 实验室 (ai-lab)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/lab/experiments` | 实验列表 |
| POST | `/api/lab/experiments` | 创建实验（SSE 进度流） |
| GET | `/api/lab/experiments/{id}` | 实验详情 |
| PUT | `/api/lab/experiments/{id}` | 更新实验状态 |
| DELETE | `/api/lab/experiments/{id}` | 删除实验及相关数据 |
| POST | `/api/lab/experiments/{id}/retry` | 重试实验中 pending 的策略 |
| GET | `/api/lab/experiments/{id}/stream` | 重连实验的 SSE 流 |
| POST | `/api/lab/experiments/combo` | 从已提升策略创建 Combo 实验 |
| POST | `/api/lab/experiments/retry-pending` | 重试所有卡住的实验 |
| POST | `/api/lab/strategies/{id}/promote` | 提升实验策略到正式策略库 |
| POST | `/api/lab/strategies/{id}/clone-backtest` | 克隆策略（改退出参数）并回测 |
| POST | `/api/lab/strategies/{id}/batch-clone-backtest` | 批量克隆+回测（N 种退出参数） |
| POST | `/api/lab/strategies/{id}/grid-search` | 参数网格搜索（SL/TP/MHD 组合） |
| GET | `/api/lab/strategies/{id}/grid-results` | 网格搜索结果 |
| GET | `/api/lab/regimes?start=X&end=Y` | 市场状态标签查询 |
| GET | `/api/lab/templates` | 实验模板列表 |
| POST | `/api/lab/templates` | 创建模板 |
| PUT | `/api/lab/templates/{id}` | 更新模板 |
| DELETE | `/api/lab/templates/{id}` | 删除模板 |
| GET | `/api/lab/exploration-rounds` | 探索轮次列表 |
| POST | `/api/lab/exploration-rounds` | 创建探索轮次 |
| GET | `/api/lab/exploration-rounds/{id}` | 轮次详情 |
| PUT | `/api/lab/exploration-rounds/{id}` | 更新轮次 |

## 探索工作流 (exploration-workflow)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/exploration-workflow/start` | 启动后台探索工作流 |
| GET | `/api/exploration-workflow/status` | 实时工作流状态 |
| POST | `/api/exploration-workflow/stop` | 请求在当前轮次后停止 |
| GET | `/api/exploration-workflow/history` | 探索轮次历史 |

## 策略库 (strategies)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/strategies?category=X` | 策略列表（可按分类过滤） |
| POST | `/api/strategies` | 创建策略 |
| GET | `/api/strategies/{id}` | 策略详情 |
| PUT | `/api/strategies/{id}` | 更新策略 |
| DELETE | `/api/strategies/{id}` | 删除策略 |
| POST | `/api/strategies/{id}/clone` | 克隆策略（可覆盖参数） |
| POST | `/api/strategies/{id}/unarchive` | 恢复已归档策略 |
| GET | `/api/strategies/families` | 按信号指纹分组的策略家族列表 |
| GET | `/api/strategies/families/{fingerprint}` | 某家族内所有策略（含已归档） |
| GET | `/api/strategies/indicator-groups` | 指标元数据（前端规则编辑器用） |
| GET | `/api/strategies/pool/status` | 策略池综合状态 |
| POST | `/api/strategies/pool/rebalance` | 策略池再平衡（按骨架配额） |
| POST | `/api/strategies/pool/deduplicate` | 去重（归档高相关策略） |
| POST | `/api/strategies/cleanup` | 清理低质量策略 |
| POST | `/api/strategies/combo` | 创建 Combo 组合策略 |

## 回测 (backtest)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backtest/run` | 启动回测（SSE 进度流） |
| POST | `/api/backtest/run/sync` | 同步回测（直接返回结果） |
| GET | `/api/backtest/runs` | 回测记录列表 |
| GET | `/api/backtest/runs/{id}` | 回测详情（含交易记录） |

## 记忆 (memory)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory/entries` | 记忆条目列表（可过滤） |
| POST | `/api/memory/entries` | 创建记忆条目 |
| GET | `/api/memory/entries/{id}` | 记忆详情 |
| PUT | `/api/memory/entries/{id}` | 更新记忆 |
| DELETE | `/api/memory/entries/{id}` | 软删除记忆 |
| GET | `/api/memory/search?q=X&tags=Y` | 按关键字/标签搜索记忆 |
| POST | `/api/memory/auto-extract/{round_id}` | 从探索轮次自动提取记忆 |

## 任务 (jobs)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs?status=X&type=Y` | 任务列表（可过滤） |
| GET | `/api/jobs/{id}` | 任务详情 |
| POST | `/api/jobs/{id}/cancel` | 取消任务 |
| GET | `/api/jobs/{id}/events` | 任务事件列表（分页） |
| GET | `/api/jobs/{id}/stream` | 任务事件 SSE 流 |

## 认证 (auth)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/keys` | 列出所有 API Key（不返回原始密钥） |
| POST | `/api/auth/keys` | 创建 API Key（原始密钥仅显示一次） |
| DELETE | `/api/auth/keys/{id}` | 吊销 API Key |
| GET | `/api/auth/audit-log` | 审计日志 |

## 系统 (ops / config)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/ops/overview` | 系统总览（<200ms） |
| GET | `/api/config` | 当前配置（token 已脱敏） |
| PUT | `/api/config` | 更新配置 |
| GET | `/api/artifacts` | 工件列表 |
| GET | `/api/artifacts/{id}` | 工件详情 |
