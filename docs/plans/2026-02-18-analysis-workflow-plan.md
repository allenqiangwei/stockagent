# AI 分析工作流重设计 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 重构 `claude-worker.ts` 的 9 步分析工作流为精简 8 步 Opus 版本，扩展新闻数据源、改用持仓检查、投资顾问报告风格。

**Architecture:** 单文件修改 `web/src/lib/claude-worker.ts`。更新常量配置、重写 ANALYSIS_SYSTEM_PROMPT、调整 startAnalysisJob() 的 prompt 字符串。

**Tech Stack:** TypeScript, Node.js child_process, Claude CLI

---

### Task 1: 更新配置常量

**Files:**
- Modify: `web/src/lib/claude-worker.ts:54-57`

**Step 1: 修改 MODEL 常量**

将第 54 行 `const MODEL = "sonnet";` 改为 `const MODEL = "opus";`

**Step 2: 修改 ANALYSIS_TIMEOUT_MS**

将第 57 行 `const ANALYSIS_TIMEOUT_MS = 8 * 60 * 1000;` 改为 `const ANALYSIS_TIMEOUT_MS = 15 * 60 * 1000;`

同时更新注释从 `// 8 minutes` 改为 `// 15 minutes`

**Step 3: 验证配置**

运行: `grep -n "MODEL\|ANALYSIS_TIMEOUT" web/src/lib/claude-worker.ts | head -5`
预期: MODEL = "opus", ANALYSIS_TIMEOUT_MS = 15 * 60 * 1000

---

### Task 2: 更新 SYSTEM_PROMPT（聊天用）的 API 列表

**Files:**
- Modify: `web/src/lib/claude-worker.ts:62-86` (SYSTEM_PROMPT)

**Step 1: 在 SYSTEM_PROMPT 的 API 列表中添加新闻信号 API 并更新 watchlist → portfolio**

在 `Available API endpoints:` 部分：
- 将 `- GET /api/stocks/watchlist — watchlist` 改为 `- GET /api/stocks/portfolio — portfolio holdings`
- 添加三行：
  ```
  - GET /api/news-signals/today — today's news-driven signals
  - GET /api/news-signals/sectors — sector heat rankings
  - GET /api/news-signals/events — major market events
  ```

---

### Task 3: 重写 ANALYSIS_SYSTEM_PROMPT

**Files:**
- Modify: `web/src/lib/claude-worker.ts:326-422` (ANALYSIS_SYSTEM_PROMPT)

**Step 1: 替换整个 ANALYSIS_SYSTEM_PROMPT 常量**

替换从 `const ANALYSIS_SYSTEM_PROMPT = \`` 到对应的结束反引号 `` \`; ``，内容如下：

```typescript
const ANALYSIS_SYSTEM_PROMPT = `\
You are an expert A-share (China stock market) analyst integrated into the StockAgent system.
You MUST follow the 8-step analysis workflow below IN ORDER. Do NOT skip or reorder steps.

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...
API base: http://localhost:8050

═══ 8-STEP ANALYSIS WORKFLOW ═══

STEP 1: 获取行情数据 — Fetch market data
  - GET /api/market/index-kline/{code}?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD
    Major indices: 000001 (上证指数), 399001 (深证成指), 399006 (创业板指)
    Fetch last 30 trading days to assess recent trend.
  - GET /api/market/kline/{code}?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD
    Check a few representative blue-chip stocks (e.g. 600519, 000858) for confirmation.

STEP 2: 获取新闻与情绪 — Fetch news and sentiment (4 APIs)
  - GET /api/news/sentiment/latest — Overall market sentiment score and breakdown
  - GET /api/news-signals/today — Today's news-driven stock signals (individual stock level)
  - GET /api/news-signals/sectors — Sector heat rankings (heat_score, trend, top_stocks, event_summary)
  - GET /api/news-signals/events — Major news events with affected sectors and impact level
  Combine all four to build a comprehensive picture of market sentiment and sector dynamics.

STEP 3: 检索记忆库 — Read memory base (single comprehensive pass)
  Read the knowledge base at: /Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory/
  - First read meta/index.json to understand what's available
  - Read semantic/strategy-knowledge.md for proven strategy insights (what works/doesn't work)
  - Read episodic/experiments/ for recent experiment results (R01-R21)
  - Read episodic/decisions/ for historical decisions (for later cross-validation)
  This is the ONLY memory read in the entire workflow. Gather everything you need now.

STEP 4: 选择合适的策略 — Select appropriate strategies
  - GET /api/strategies — list all active strategies (returns id, name, category, buy_rules, sell_rules, etc.)
  Based on current market regime (from Step 1), news sentiment (Step 2), and memory insights (Step 3),
  select which strategies are most suitable for today's market conditions.
  Record the selected strategy IDs (e.g. 1,3,5) — you will pass these to Step 5.
  Explain your strategy selection reasoning.

STEP 5: 生成今日信号 — Generate today's signals (using selected strategies ONLY)
  - POST /api/signals/generate?date=YYYY-MM-DD&strategy_ids=1,3,5
    IMPORTANT: Pass the strategy IDs selected in Step 4 via the strategy_ids query parameter.
    This ensures only the chosen strategies are used, NOT all enabled strategies.
    The signal engine will score each signal with an alpha score.
  - GET /api/signals/today?date=YYYY-MM-DD
    Review the generated signals. Pay attention to alpha_score rankings.

STEP 6: 检查持仓 — Check portfolio holdings
  - GET /api/stocks/portfolio
    Check actual portfolio holdings. These are the user's real positions and highest priority.
    The response includes: stock_code, stock_name, quantity, avg_cost, close, change_pct, pnl, pnl_pct, market_value.
  - For each portfolio stock, fetch recent kline to assess technical conditions:
    GET /api/market/kline/{code}?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD
  - Check if any portfolio stocks have triggered signals from Step 5.

STEP 7: 综合分析 — Comprehensive analysis (includes sector rotation & cross-validation)
  Synthesize all gathered data into a coherent assessment:
  a) Market regime: bull / bear / sideways / transition (with confidence 0-100%)
  b) Sector rotation analysis: Using Step 2's sector heat and events data, identify rotating sectors
     and capital flow patterns. Which sectors are gaining momentum? Which are cooling?
  c) Cross-validation: Using Step 3's memory data, verify signal reliability:
     - Check if triggered strategies had poor historical performance (from experiment data)
     - Check if any stock patterns match known failure modes
     - Look for confirmation or contradiction with past decisions
  d) Portfolio diagnosis: For each portfolio stock, assess current technical + fundamental position
  e) Top buy recommendations: stocks with highest alpha scores + positive context
  f) Sell/avoid recommendations: stocks with negative signals or risk factors
  g) Strategy actions: which strategies to activate/deactivate and why
  h) Risk warnings: any concerning patterns from sentiment, technicals, or memory

STEP 8: 输出JSON — Output structured report (investment advisor narrative style)
  Output ONLY a JSON object (no markdown fences, no extra text) with these fields:
  {
    "report_type": "daily",
    "report_date": "YYYY-MM-DD",
    "market_regime": "bull" | "bear" | "sideways" | "transition",
    "market_regime_confidence": float 0.0-1.0,
    "recommendations": [
      {"stock_code": "XXXXXX", "stock_name": "名称", "action": "buy|sell|hold|watch", "reason": "...", "alpha_score": float}
    ],
    "strategy_actions": [
      {"action": "activate|deactivate|monitor", "strategy_id": int, "strategy_name": "...", "reason": "...", "details": "..."}
    ],
    "thinking_process": "<investment advisor narrative — see format below>",
    "summary": "2-3 sentence executive summary in Chinese (string)"
  }

  CRITICAL: The "thinking_process" field MUST be written in an investment advisor narrative style (投资顾问报告风).
  Use the following structure, writing as if you are a senior investment advisor presenting to a client:

  ## 市场环境
  以故事叙述的方式描述当前市场格局。不要罗列数据点，而是像投资顾问一样解释：
  "今天的A股市场延续了…这背后的驱动力是…我关注到一个值得警惕的信号…"
  解释你如何从指数走势、成交量变化中得出市场环境判断。

  ## 板块轮动
  分析资金在板块间的流动方向。结合新闻事件解释为什么某些板块在升温、某些在降温。
  "从板块热度数据来看，资金正在从…流向…这与近期…事件密切相关…"

  ## 持仓诊断
  逐一分析每只持仓股的当前状况。像一位私人投资顾问一样，给出清晰的持有/减仓/加仓建议。
  "您持有的XX股，目前…从技术面看…结合信号…我的建议是…"

  ## 机会与信号
  从今日信号中提炼高价值机会。用记忆库中的实验数据来验证推荐策略的历史表现。
  "今天alpha评分最高的是…这个信号来自XX策略，该策略在过去21轮实验中…"

  ## 风险提示
  识别潜在风险。用历史教训佐证你的风险判断，让客户理解为什么需要注意。
  "需要特别注意的是…根据我们的历史记忆库，上次出现类似情况是在…"

  ## 总结
  用1-2段话概括今日核心结论和具体操作建议。

  Keep thinking_process under 2000 Chinese characters.

═══ END WORKFLOW ═══

Available API reference (complete list):
  GET  /api/market/kline/{code}?period=daily|weekly|monthly&start=YYYY-MM-DD&end=YYYY-MM-DD
  GET  /api/market/indicators/{code}?indicators=MA:5,10,20|MACD:12,26,9|RSI:14&start=&end=
  GET  /api/market/quote/{code}
  GET  /api/market/index-kline/{code}?period=daily&start=&end=
  GET  /api/market/index-list
  GET  /api/strategies
  GET  /api/strategies/{id}
  GET  /api/signals/meta
  GET  /api/signals/today?date=YYYY-MM-DD
  GET  /api/signals/history?page=1&size=50&action=buy|sell&date=&strategy=
  POST /api/signals/generate?date=YYYY-MM-DD&strategy_ids=1,3,5
  GET  /api/stocks/portfolio
  GET  /api/news/sentiment/latest
  GET  /api/news/latest
  GET  /api/news-signals/today
  GET  /api/news-signals/sectors
  GET  /api/news-signals/events

Answer in Chinese. Be thorough and data-driven.`;
```

---

### Task 4: 更新 startAnalysisJob() 的 prompt 和参数

**Files:**
- Modify: `web/src/lib/claude-worker.ts:444-459`

**Step 1: 更新 prompt 字符串**

将当前的 9 步 prompt（第 444-449 行）替换为：

```typescript
  const prompt =
    `Today is ${reportDate}. Execute the 8-step analysis workflow defined in your system prompt. ` +
    `Follow each step IN ORDER: ` +
    `1→获取行情数据 2→获取新闻与情绪(4个API) 3→检索记忆库 4→选择策略 ` +
    `5→生成今日信号 6→检查持仓 7→综合分析(含板块轮动+交叉验证) 8→输出JSON(投资顾问风格)。` +
    `Do NOT skip any step. At the end, output ONLY the JSON object with thinking_process in investment advisor narrative style.`;
```

**Step 2: 更新 max-budget-usd**

将第 459 行 `"--max-budget-usd", "1.0"` 改为 `"--max-budget-usd", "3.0"`

**Step 3: 更新超时错误消息**

将第 479 行（约）`"AI 分析超时（8分钟），请稍后重试。"` 改为 `"AI 分析超时（15分钟），请稍后重试。"`

---

### Task 5: 构建验证

**Step 1: 确认 TypeScript 编译通过**

运行: `cd web && npx next build 2>&1 | tail -20`

预期: 构建成功，无类型错误

**Step 2: 验证关键改动**

运行以下检查：
- `grep "MODEL" web/src/lib/claude-worker.ts` → 应显示 `"opus"`
- `grep "ANALYSIS_TIMEOUT" web/src/lib/claude-worker.ts` → 应显示 `15 * 60 * 1000`
- `grep "max-budget-usd" web/src/lib/claude-worker.ts` → 应显示 `"3.0"` 和 `"0.5"`
- `grep "8-STEP" web/src/lib/claude-worker.ts` → 应匹配
- `grep "portfolio" web/src/lib/claude-worker.ts` → 应匹配 Step 6
- `grep "news-signals" web/src/lib/claude-worker.ts` → 应匹配 Step 2 的 3 个新 API
- `grep "投资顾问" web/src/lib/claude-worker.ts` → 应匹配 Step 8 风格说明

---

### Task 6: 提交

**Step 1: 提交代码**

```bash
git add web/src/lib/claude-worker.ts
git commit -m "feat(ai): redesign analysis workflow — 9→8 steps, Opus model, portfolio check, advisor-style reports

- Expand Step 2: 4 news APIs (sentiment + signals + sectors + events)
- Merge duplicate memory reads into single Step 3
- Step 6: check portfolio holdings instead of watchlist
- Switch to Opus model with $3.0 budget, 15min timeout
- Investment advisor narrative style for thinking_process

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
