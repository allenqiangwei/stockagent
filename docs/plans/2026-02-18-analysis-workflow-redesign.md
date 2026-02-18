# AI 分析工作流重设计：9步→8步 Opus 升级

## 目标

重构 `claude-worker.ts` 中的 `ANALYSIS_SYSTEM_PROMPT` 和 `startAnalysisJob()`，将 9 步分析工作流精简为 8 步，同时完成四项关键升级：扩展新闻数据源、切换至 Opus 模型、改用持仓检查、投资顾问报告风格。

## 架构

只修改一个文件：`web/src/lib/claude-worker.ts`。系统提示和运行参数调整，无需后端改动。

技术栈：Node.js child_process + Claude CLI + Fire-and-forget polling

---

## 变更矩阵

| 编号 | 变更项 | 当前 | 目标 |
|------|--------|------|------|
| C1 | 新闻数据源 | 仅 `sentiment/latest` 1个API | 4个API: sentiment/latest + news-signals/today + sectors + events |
| C2 | 记忆库检索 | 两次(Step 3 + Step 7)，重复 | 一次(Step 3)，合并交叉验证到综合分析 |
| C3 | 自选股→持仓 | `GET /api/stocks/watchlist` | `GET /api/stocks/portfolio` |
| C4 | 模型 | `sonnet`, budget $1.0 | `opus`, budget $3.0 |
| C5 | 报告风格 | 步骤罗列式 thinking_process | 投资顾问叙事式 thinking_process |
| C6 | 超时 | 8 分钟 | 15 分钟(Opus 更慢) |
| C7 | 步骤数 | 9步 | 8步 |

---

## 新 8 步工作流

### Step 1: 获取行情数据
- `GET /api/market/index-kline/{code}?period=daily&start=&end=` — 三大指数近30日
- `GET /api/market/kline/{code}?period=daily&start=&end=` — 代表性个股

### Step 2: 获取新闻与情绪（扩展）
- `GET /api/news/sentiment/latest` — 整体市场情绪评分
- `GET /api/news-signals/today` — 今日个股新闻驱动信号
- `GET /api/news-signals/sectors` — 板块热度排名（heat_score, trend, top_stocks）
- `GET /api/news-signals/events` — 重大事件及影响板块

### Step 3: 检索记忆库（合并，只做一次）
- 读 `meta/index.json` 定位相关笔记
- 读 `semantic/strategy-knowledge.md` 策略知识
- 读 `episodic/experiments/` 近期实验结果
- 读 `episodic/decisions/` 历史决策（供后续交叉验证用）

### Step 4: 选择合适的策略
- `GET /api/strategies` — 全部启用策略
- 结合行情、情绪、记忆选择策略，记录 IDs

### Step 5: 生成今日信号
- `POST /api/signals/generate?date=&strategy_ids=X,Y,Z`
- `GET /api/signals/today?date=` — 审查生成的信号和 alpha_score

### Step 6: 检查持仓（改为 portfolio）
- `GET /api/stocks/portfolio` — 获取实际持仓
- 对持仓股获取近期 K 线确认技术面
- 检查持仓股是否有信号触发

### Step 7: 综合分析（含板块轮动+交叉验证）
合成所有数据：
- 市场环境判断（bull/bear/sideways/transition + 置信度）
- 板块轮动分析（利用 Step 2 的 sectors + events 数据）
- 交叉验证（利用 Step 3 的记忆数据验证信号可靠性）
- 买入推荐（高 alpha + 正面上下文）
- 卖出/规避推荐
- 策略动作建议
- 风险警告

### Step 8: 输出报告（投资顾问风格）
JSON 格式同前，`thinking_process` 字段改为投资顾问叙事风：

```
## 市场环境
以故事叙述的方式描述当前市场格局，
解释判断逻辑链条...

## 板块轮动
分析资金流向和板块热度变化，
结合新闻事件解释板块轮动逻辑...

## 持仓诊断
逐一分析持仓股的技术面和基本面，
给出持有/减仓/加仓建议和理由...

## 机会发现
从信号中挖掘高 alpha 机会，
用记忆库数据验证策略的历史表现...

## 风险提示
识别潜在风险因素，
用历史教训（记忆库）佐证风险判断...

## 总结
一段话概括今日核心结论和建议...
```

---

## 代码变更清单

### `web/src/lib/claude-worker.ts`

1. **`MODEL` 常量**：`"sonnet"` → `"opus"`
2. **`ANALYSIS_TIMEOUT_MS`**：`8 * 60 * 1000` → `15 * 60 * 1000`
3. **`max-budget-usd`** (分析任务)：`"1.0"` → `"3.0"`
4. **`ANALYSIS_SYSTEM_PROMPT`**：完整重写为 8 步工作流（见上方）
5. **`startAnalysisJob()` prompt 字符串**：更新步骤列表为 8 步
6. **超时错误消息**：`"8分钟"` → `"15分钟"`
7. **API 参考列表**：添加 3 个新闻信号 API，更新 watchlist → portfolio

### 不修改的文件

- 后端 API 路由（所有端点已存在）
- 前端页面组件（报告展示无变化）
- 聊天系统（独立于分析流程）

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| Opus 单次分析成本较高（约 $1-3） | budget 上限 $3.0，日常使用可控 |
| Opus 速度较慢（预估 5-10 分钟） | 超时从 8 分钟延长至 15 分钟 |
| 8 步中工具调用可能超 max_turns=15 | 保持 15 turns，8 步内每步约 1-2 次调用足够 |
| 投资顾问风格可能过长 | 在 prompt 中限制 thinking_process 字数（2000 字以内） |

## 验证

1. 运行分析任务，确认 8 步完整执行
2. 检查返回 JSON 包含所有必要字段
3. 验证 thinking_process 为投资顾问叙事风格
4. 验证 Step 2 调用了 4 个 API
5. 验证 Step 6 调用的是 portfolio 而非 watchlist
6. 确认 Opus 模型被使用（检查 CLI 参数）
