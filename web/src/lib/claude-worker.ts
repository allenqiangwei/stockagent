/**
 * Claude CLI background worker — fire-and-forget pattern.
 *
 * Runs Claude CLI as a child process with `--output-format stream-json`,
 * parses real-time events for progress, stores results in memory.
 * Uses globalThis to survive Next.js HMR reloads.
 */

import { spawn, type ChildProcess } from "child_process";

// ── Types ────────────────────────────────────────────

export type JobStatus = "processing" | "completed" | "error";

export interface MessageJob {
  id: string;
  status: JobStatus;
  progress: string;
  content: string;
  errorMessage: string;
  sessionId: string | null;
  createdAt: number;
}

interface SessionState {
  claudeSessionId: string | null;
  updatedAt: number;
}

// ── globalThis-safe stores (survive HMR) ─────────────

const GLOBAL_KEY_JOBS = "__claude_job_store__";
const GLOBAL_KEY_SESSIONS = "__claude_session_store__";

function getJobStore(): Map<string, MessageJob> {
  const g = globalThis as Record<string, unknown>;
  if (!g[GLOBAL_KEY_JOBS]) {
    g[GLOBAL_KEY_JOBS] = new Map<string, MessageJob>();
  }
  return g[GLOBAL_KEY_JOBS] as Map<string, MessageJob>;
}

function getSessionStore(): Map<string, SessionState> {
  const g = globalThis as Record<string, unknown>;
  if (!g[GLOBAL_KEY_SESSIONS]) {
    g[GLOBAL_KEY_SESSIONS] = new Map<string, SessionState>();
  }
  return g[GLOBAL_KEY_SESSIONS] as Map<string, SessionState>;
}

// ── Config ───────────────────────────────────────────

const CLAUDE_BIN = "/opt/homebrew/bin/claude";
const MODEL = "opus";
const MAX_TURNS = "30";
const JOB_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
const ANALYSIS_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes (Opus is slower but more thorough)
const REVIEW_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes for review jobs
const JOB_EXPIRE_MS = 30 * 60 * 1000; // 30 minutes
const PROJECT_ROOT = process.cwd();
const FASTAPI_BASE = "http://localhost:8050";

// ── JSON parsing helpers (shared) ────────────────────

/** Extract JSON string from text (fence block or brace matching) */
function extractJsonStr(text: string): string | null {
  const fenceMatch = text.match(/```(?:json)?\s*\n([\s\S]*?)```/);
  if (fenceMatch) return fenceMatch[1].trim();
  const firstBrace = text.indexOf("{");
  const lastBrace = text.lastIndexOf("}");
  if (firstBrace !== -1 && lastBrace > firstBrace) return text.slice(firstBrace, lastBrace + 1);
  return null;
}

/** Repair common JSON issues (unescaped quotes in string values) */
function repairJson(jsonStr: string): string {
  return jsonStr.replace(
    /("(?:thinking_process|summary|reason|review_thinking|lessons_learned|content)"\s*:\s*")([\s\S]*?)("(?:\s*[,}]))/g,
    (_match, prefix: string, content: string, suffix: string) => {
      const fixed = content.replace(/(?<!\\)"/g, '\\"');
      return prefix + fixed + suffix;
    }
  );
}

/** Try parsing JSON with optional repair */
function tryParse(jsonStr: string): Record<string, unknown> | null {
  try { return JSON.parse(jsonStr); } catch { /* ignore */ }
  try { return JSON.parse(repairJson(jsonStr)); } catch { /* ignore */ }
  return null;
}

const SYSTEM_PROMPT = `\
You are an expert A-share (China stock market) analyst assistant in the StockAgent system.
You can access local APIs at http://localhost:8050 to answer questions about stocks, signals, and strategies.

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...

Available API endpoints:
- GET /api/market/trading-day?date=YYYY-MM-DD — trading calendar (is_trading_day, prev/next)
- GET /api/signals/today — today's signals
- GET /api/signals/history?start_date=&end_date= — historical signals
- GET /api/strategies — active strategies
- GET /api/market/kline?code=&period=daily&start_date=&end_date= — K-line data
- GET /api/market/quote?code= — real-time quote
- GET /api/news/sentiment/latest — news sentiment
- GET /api/news-signals/today — today's news-driven signals
- GET /api/news-signals/sectors — sector heat rankings
- GET /api/news-signals/events — major market events
- GET /api/stocks/portfolio — portfolio holdings
- GET /api/stocks/search?keyword= — search stocks

Knowledge Base:
You have access to a structured memory system with experiment results, strategy insights, and architectural decisions.
When answering questions about strategies, experiments, or historical decisions, consult the memory files at:
/Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory/
- Read meta/index.json first to find relevant notes by tags
- Key knowledge: semantic/strategy-knowledge.md (what works/doesn't work)
- Experiment details: episodic/experiments/ (R01-R21 results)

Answer in Chinese. Be concise but thorough. Use data from the APIs to support your analysis.`;

// ── Progress mapping ─────────────────────────────────

function mapProgress(event: Record<string, unknown>): string | null {
  const type = event.type as string | undefined;

  if (type === "assistant" && event.subtype === "tool_use") {
    const name = (event.tool_name as string) || "";
    if (name.toLowerCase().includes("bash") || name.toLowerCase().includes("command")) {
      return "正在执行命令...";
    }
    if (name.toLowerCase().includes("read") || name.toLowerCase().includes("file")) {
      return "正在读取文件...";
    }
    if (name.toLowerCase().includes("grep") || name.toLowerCase().includes("search") || name.toLowerCase().includes("glob")) {
      return "正在搜索...";
    }
    if (name.toLowerCase().includes("web") || name.toLowerCase().includes("fetch")) {
      return "正在获取数据...";
    }
    return `正在使用工具 ${name}...`;
  }

  if (type === "assistant" && event.subtype === "text") {
    return "正在生成回复...";
  }

  if (type === "result") {
    return null; // handled separately
  }

  return null;
}

// ── Expired job cleanup ──────────────────────────────

function cleanupExpiredJobs() {
  const store = getJobStore();
  const now = Date.now();
  for (const [id, job] of store) {
    if (now - job.createdAt > JOB_EXPIRE_MS) {
      store.delete(id);
    }
  }
}

// ── Core ─────────────────────────────────────────────

export function getJob(messageId: string): MessageJob | undefined {
  return getJobStore().get(messageId);
}

export function getOrCreateSession(sessionId: string): SessionState {
  const store = getSessionStore();
  let session = store.get(sessionId);
  if (!session) {
    session = { claudeSessionId: null, updatedAt: Date.now() };
    store.set(sessionId, session);
  }
  return session;
}

export function startClaudeJob(
  messageId: string,
  prompt: string,
  sessionId: string,
): void {
  const jobStore = getJobStore();
  const sessionStore = getSessionStore();

  // Periodic cleanup
  cleanupExpiredJobs();

  // Create job
  const job: MessageJob = {
    id: messageId,
    status: "processing",
    progress: "正在思考...",
    content: "",
    errorMessage: "",
    sessionId,
    createdAt: Date.now(),
  };
  jobStore.set(messageId, job);

  // Get Claude session ID for resume
  const session = getOrCreateSession(sessionId);
  const claudeSessionId = session.claudeSessionId;

  // Build args
  const args = [
    "-p", prompt,
    "--output-format", "stream-json",
    "--verbose",
    "--max-turns", MAX_TURNS,
    "--model", MODEL,
    "--append-system-prompt", SYSTEM_PROMPT,
    "--permission-mode", "bypassPermissions",
    "--max-budget-usd", "0.5",
  ];

  if (claudeSessionId) {
    args.unshift("--resume", claudeSessionId);
  }

  // Spawn process
  let child: ChildProcess;
  try {
    child = spawn(CLAUDE_BIN, args, {
      cwd: PROJECT_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (err) {
    job.status = "error";
    job.errorMessage = "Claude CLI 未安装或不可用。";
    job.progress = "";
    return;
  }

  // Timeout protection
  const timer = setTimeout(() => {
    if (job.status === "processing") {
      job.status = "error";
      job.errorMessage = "AI 响应超时（5分钟），请稍后重试。";
      job.progress = "";
      child.kill("SIGTERM");
    }
  }, JOB_TIMEOUT_MS);

  // Parse stdout (stream-json: one JSON object per line)
  let buffer = "";
  let lastResultText = "";
  let lastSessionId: string | null = null;

  child.stdout?.on("data", (chunk: Buffer) => {
    buffer += chunk.toString();
    const lines = buffer.split("\n");
    buffer = lines.pop() || ""; // keep incomplete line

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      let event: Record<string, unknown>;
      try {
        event = JSON.parse(trimmed);
      } catch {
        continue;
      }

      // Extract progress
      const progress = mapProgress(event);
      if (progress && job.status === "processing") {
        job.progress = progress;
      }

      // Capture session ID from any event
      if (event.session_id && typeof event.session_id === "string") {
        lastSessionId = event.session_id;
      }

      // Capture result
      if (event.type === "result") {
        lastResultText = (event.result as string) || "";
        if (event.session_id && typeof event.session_id === "string") {
          lastSessionId = event.session_id;
        }
        if (event.subtype === "error_max_turns") {
          lastResultText = "抱歉，这个问题比较复杂，达到了回合数限制。请简化问题或拆分成多个小问题。";
        }
      }
    }
  });

  // Capture stderr for error diagnostics
  let stderrBuf = "";
  child.stderr?.on("data", (chunk: Buffer) => {
    stderrBuf += chunk.toString();
  });

  child.on("close", (code) => {
    clearTimeout(timer);

    // Process any remaining buffer
    if (buffer.trim()) {
      try {
        const event = JSON.parse(buffer.trim());
        if (event.type === "result") {
          lastResultText = (event.result as string) || "";
          if (event.session_id) lastSessionId = event.session_id;
        }
      } catch {
        // ignore
      }
    }

    // Update session
    if (lastSessionId) {
      const sess = getOrCreateSession(sessionId);
      sess.claudeSessionId = lastSessionId;
      sess.updatedAt = Date.now();
      sessionStore.set(sessionId, sess);
    }

    if (job.status !== "processing") {
      // Already marked as error (timeout)
      return;
    }

    if (code === 0 && lastResultText) {
      job.status = "completed";
      job.content = lastResultText;
      job.progress = "";
    } else if (lastResultText) {
      // Non-zero exit but we got a result (e.g. max_turns)
      job.status = "completed";
      job.content = lastResultText;
      job.progress = "";
    } else {
      job.status = "error";
      job.errorMessage = stderrBuf
        ? `AI 服务错误: ${stderrBuf.slice(0, 300)}`
        : "AI 服务返回空响应，请重试。";
      job.progress = "";
    }
  });

  child.on("error", (err) => {
    clearTimeout(timer);
    if (job.status === "processing") {
      job.status = "error";
      job.errorMessage = `无法启动 Claude CLI: ${err.message}`;
      job.progress = "";
    }
  });
}

// ── Analysis Job ────────────────────────────────

const ANALYSIS_SYSTEM_PROMPT = `\
You are an expert A-share (China stock market) analyst integrated into the StockAgent system.
You MUST follow the 8-step analysis workflow below IN ORDER. Do NOT skip or reorder steps.

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...
API base: http://localhost:8050

═══ 9-STEP ANALYSIS WORKFLOW ═══

STEP 1: 确认交易日历 — Check trading calendar
  - GET /api/market/trading-day?date=YYYY-MM-DD
    Returns: { date, is_trading_day, prev_trading_day, next_trading_day }
    This tells you whether the report date is a trading day.
    - If is_trading_day=true: use this date for all subsequent API calls.
    - If is_trading_day=false: use prev_trading_day for market data and signals (last available data).
      Mention in your report that today is NOT a trading day, and note when the next trading day is.
    IMPORTANT: Use the correct trading date for all subsequent Steps (kline, signals, etc).

STEP 2: 获取行情数据 — Fetch market data
  - GET /api/market/index-kline/{code}?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD
    Major indices: 000001 (上证指数), 399001 (深证成指), 399006 (创业板指)
    Fetch last 30 trading days to assess recent trend.
  - GET /api/market/kline/{code}?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD
    Check a few representative blue-chip stocks (e.g. 600519, 000858) for confirmation.

STEP 3: 获取新闻与情绪 — Fetch news and sentiment
  You must decide the appropriate scope of news analysis based on market conditions.

  3a) First, get the baseline data:
    - GET /api/news/sentiment/latest — latest sentiment analysis (check news_count and analysis_time)
    - GET /api/news/latest — cached news list (check total_count and fetch_time to see how fresh)

  3b) Then decide your analysis scope. Consider:
    - If it's a normal trading day: the default latest sentiment + today's signals may suffice
    - If it's after a long holiday (e.g. Spring Festival): you need broader coverage — call
      GET /api/news/sentiment/history?days=N to see sentiment trend over the break
    - If market is at a turning point or high volatility: consider more events for context
    - If the latest sentiment analysis is stale (>12 hours old): note this limitation

  3c) Fetch signal data based on your decision:
    - GET /api/news-signals/today — today's news-driven stock signals (count field shows total)
    - GET /api/news-signals/sectors — sector heat rankings (count field shows total)
    - GET /api/news-signals/events?limit=N — major events (default 50, increase to 100-200 if after holiday or high volatility)

  3d) Record and explain your decision:
    - How many news articles were analyzed in total (from news_count/count fields across all APIs)
    - What time range does this cover
    - WHY you chose this scope (e.g. "长假后需要更广覆盖" or "常规交易日，最新情绪分析已足够")
    This explanation will go into the thinking_process.

STEP 4: 检索记忆库 — Read memory base (single comprehensive pass)
  Read the knowledge base at: /Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory/
  - First read meta/index.json to understand what's available
  - Read semantic/strategy-knowledge.md for proven strategy insights (what works/doesn't work)
  - Read episodic/experiments/ for recent experiment results (R01-R21)
  - Read episodic/decisions/ for historical decisions (for later cross-validation)
  This is the ONLY memory read in the entire workflow. Gather everything you need now.

STEP 5: 选择合适的策略 — Select appropriate strategies
  - GET /api/strategies — list all active strategies (returns id, name, category, buy_rules, sell_rules, etc.)
  Based on current market regime (from Step 2), news sentiment (Step 3), and memory insights (Step 4),
  select which strategies are most suitable for today's market conditions.
  Record the selected strategy IDs (e.g. 1,3,5) — you will pass these to Step 6.
  Explain your strategy selection reasoning.

STEP 6: 生成今日信号 — Generate today's signals (using selected strategies ONLY)
  - POST /api/signals/generate?date=YYYY-MM-DD&strategy_ids=1,3,5
    IMPORTANT: Pass the strategy IDs selected in Step 5 via the strategy_ids query parameter.
    Use the trading date determined in Step 1.
    This ensures only the chosen strategies are used, NOT all enabled strategies.
    The signal engine will score each signal with an alpha score.
  - GET /api/signals/today?date=YYYY-MM-DD
    Review the generated signals. Pay attention to alpha_score rankings.

STEP 7: 检查持仓 — Check portfolio holdings (user + bot)
  - GET /api/stocks/portfolio → User's real portfolio (highest priority)
  - GET /api/bot/portfolio → Robot simulated portfolio (auto-traded by AI)
  Both portfolios need diagnosis. Sell/reduce recommendations apply to BOTH.
  The response includes: stock_code, stock_name, quantity, avg_cost, close, change_pct, pnl, pnl_pct, market_value.
  - For each holding (from both portfolios), fetch recent kline:
    GET /api/market/kline/{code}?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD
  - Check if any holdings have triggered signals from Step 6.
  - In recommendations, use "source": "user" or "source": "bot" to indicate which portfolio.

STEP 8: 综合分析 — Comprehensive analysis (includes sector rotation & cross-validation)
  Synthesize all gathered data into a coherent assessment:
  a) Market regime: bull / bear / sideways / transition (with confidence 0-100%)
  b) Sector rotation analysis: Using Step 3's sector heat and events data, identify rotating sectors
     and capital flow patterns. Which sectors are gaining momentum? Which are cooling?
  c) Cross-validation: Using Step 4's memory data, verify signal reliability:
     - Check if triggered strategies had poor historical performance (from experiment data)
     - Check if any stock patterns match known failure modes
     - Look for confirmation or contradiction with past decisions
  d) Portfolio diagnosis: For each portfolio stock, assess current technical + fundamental position
  e) Buy recommendations: ONLY output stocks you genuinely recommend buying. For each buy candidate, determine:
     - target_price: a preset limit-buy price for next trading day (based on support levels, recent lows, or pullback targets — NOT simply today's close)
     - position_pct: recommended position size as % of total portfolio (consider concentration risk, conviction level, and market regime)
     - stop_loss: a stop-loss price level (based on key support breakdown)
     Explain price/position reasoning in thinking_process.
  f) Sell/hold/reduce recommendations: ONLY for portfolio stocks. For each sell/reduce candidate, determine:
     - target_price: a preset limit-sell price for next trading day (based on resistance levels, recent highs, or rebound targets)
     - sell_pct: what % of the holding to sell (e.g. 50% = reduce half, 100% = full exit)
     - stop_loss: a trailing stop or floor price to protect remaining position
     Do NOT include sell signals for stocks the user does not hold.
  g) Strategy actions: which strategies to activate/deactivate and why
  h) Risk warnings: any concerning patterns from sentiment, technicals, or memory

STEP 9: 输出JSON — Output structured report (investment advisor narrative style)
  Output ONLY a JSON object (no markdown fences, no extra text) with these fields:
  {
    "report_type": "daily",
    "report_date": "YYYY-MM-DD",
    "market_regime": "bull" | "bear" | "sideways" | "transition",
    "market_regime_confidence": float 0.0-1.0,
    "recommendations": [
      {
        "stock_code": "XXXXXX", "stock_name": "名称",
        "action": "buy|sell|hold|reduce",
        "reason": "...",
        "alpha_score": float,
        "target_price": float,       // preset limit price for next trading day (buy=limit buy price, sell/reduce=limit sell price)
        "position_pct": float,       // for buy: recommended position % of total portfolio (e.g. 10.0 = 10%)
                                     // for sell/reduce: % of holding to sell (e.g. 50.0 = sell half, 100.0 = full exit)
        "stop_loss": float           // stop-loss price level (buy: below support; sell: trailing stop for remaining)
      }
      // IMPORTANT: "sell", "hold", and "reduce" actions are ONLY for portfolio stocks.
      // "buy" can be any stock with strong signals.
      // Do NOT use "watch" — only output actionable recommendations (buy/sell/hold/reduce).
      // Use "source": "user"|"bot" to indicate which portfolio a sell/hold/reduce applies to.
    ],
    "strategy_actions": [
      {"action": "activate|deactivate|monitor", "strategy_id": int, "strategy_name": "...", "reason": "...", "details": "..."}
    ],
    "thinking_process": "<investment advisor narrative — see format below>",
    "summary": "2-3 sentence executive summary in Chinese. MUST include how many news articles were analyzed (e.g. '本次分析基于XXX条新闻...')"
  }

  CRITICAL: The "thinking_process" field MUST be written in investment advisor narrative style (投资顾问报告风).
  Structure it with these sections, writing as a senior investment advisor presenting to a client:

  ## 数据概览
  说明本次分析的新闻数据范围和选择理由。
  "本次分析覆盖了XX条新闻（时间范围：X月X日至X月X日），选择该范围是因为…"

  ## 市场环境
  以叙述方式描述当前市场格局，解释判断逻辑链条。
  "今天的A股市场延续了…这背后的驱动力是…我关注到一个值得警惕的信号…"

  ## 板块轮动
  分析资金在板块间的流动方向，结合新闻事件解释板块升温/降温的原因。
  "从板块热度数据来看，资金正在从…流向…这与近期…事件密切相关…"

  ## 策略选择
  详细解释为什么选择/激活/停用每个策略，推理链条必须包含：
  1) 当前市场环境如何影响策略适用性（如震荡市不适合趋势策略）
  2) 记忆库中该策略的历史实验表现数据（胜率、收益率、回撤）
  3) 该策略与当前板块热点/情绪的匹配度
  "基于当前震荡格局，我选择了XX策略（实验得分0.825，历史收益+90.5%），因为…同时停用了YY策略，原因是…"

  ## 持仓诊断
  分两部分诊断：
  **用户持仓**: 逐一分析每只持仓股的当前状况...
  **机器人持仓**: 逐一分析 AI 模拟交易的持仓...
  对每只持仓股，给出清晰的持有/减仓/卖出建议，并设定具体价格。
  "您持有的XX股（成本XX元，XX股），当前价XX元，盈亏XX%。从技术面看，上方阻力位在XX元，下方支撑在XX元。
  我的建议是减仓50%，挂单卖出价XX元（基于阻力位），止损设在XX元。"

  ## 机会与信号
  从今日信号中提炼高价值机会，设定买入价和仓位，用记忆库数据验证推荐策略的历史表现。
  "今天alpha评分最高的是XX（评分X.XX），建议以XX元挂单买入（基于支撑位/回调目标），建议仓位XX%。
  这个信号来自XX策略，该策略在过去实验中…止损设在XX元（跌破关键支撑则出局）。"

  ## 风险提示
  识别潜在风险，用历史教训佐证风险判断。
  "需要特别注意的是…根据历史记忆库，上次出现类似情况是在…"

  ## 总结
  1-2段话概括今日核心结论和具体操作建议。

  Keep thinking_process under 3000 Chinese characters.
  IMPORTANT: Inside JSON string values, NEVER use double quotes ("). Use 「」 for emphasis or quoting.
  For example: 这是我们的「安全网」策略 (NOT: 这是我们的"安全网"策略).

═══ END WORKFLOW ═══

Available API reference (complete list):
  GET  /api/market/trading-day?date=YYYY-MM-DD  (trading calendar: is_trading_day, prev/next trading day)
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
  GET  /api/news/sentiment/latest  (latest analysis with news_count)
  GET  /api/news/sentiment/history?days=N  (sentiment trend over N days, default 30)
  GET  /api/news/latest  (cached news list with total_count, fetch_time)
  GET  /api/news-signals/today?date=  (news-driven signals, with count)
  GET  /api/news-signals/sectors?date=  (sector heat, with count)
  GET  /api/news-signals/events?limit=N  (major events, default 50, max 200)
  GET  /api/news-signals/events
  GET  /api/bot/portfolio  (robot simulated portfolio — same format as /api/stocks/portfolio)

Answer in Chinese. Be thorough and data-driven.`;

export function getAnalysisJob(jobId: string): MessageJob | undefined {
  return getJobStore().get(jobId);
}

export function startAnalysisJob(jobId: string, reportDate: string): void {
  const jobStore = getJobStore();

  cleanupExpiredJobs();

  const job: MessageJob = {
    id: jobId,
    status: "processing",
    progress: "正在准备分析...",
    content: "",
    errorMessage: "",
    sessionId: null,
    createdAt: Date.now(),
  };
  jobStore.set(jobId, job);

  const prompt =
    `Today is ${reportDate}. Execute the 9-step analysis workflow defined in your system prompt. ` +
    `Follow each step IN ORDER: ` +
    `1→确认交易日历 2→获取行情数据 3→获取新闻与情绪(4个API) 4→检索记忆库 5→选择策略 ` +
    `6→生成今日信号 7→检查持仓 8→综合分析(含板块轮动+交叉验证) 9→输出JSON(投资顾问风格)。` +
    `IMPORTANT: Start with Step 1 to determine if today is a trading day and use the correct date for all data queries. ` +
    `Do NOT skip any step. At the end, output ONLY the JSON object with thinking_process in investment advisor narrative style.`;

  const args = [
    "-p", prompt,
    "--output-format", "stream-json",
    "--verbose",
    "--max-turns", MAX_TURNS,
    "--model", MODEL,
    "--append-system-prompt", ANALYSIS_SYSTEM_PROMPT,
    "--permission-mode", "bypassPermissions",
    "--max-budget-usd", "3.0",
  ];

  let child: ChildProcess;
  try {
    child = spawn(CLAUDE_BIN, args, {
      cwd: PROJECT_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch {
    job.status = "error";
    job.errorMessage = "Claude CLI 未安装或不可用。";
    job.progress = "";
    return;
  }

  const timer = setTimeout(() => {
    if (job.status === "processing") {
      job.status = "error";
      job.errorMessage = "AI 分析超时（15分钟），请稍后重试。";
      job.progress = "";
      child.kill("SIGTERM");
    }
  }, ANALYSIS_TIMEOUT_MS);

  let buffer = "";
  let lastResultText = "";

  child.stdout?.on("data", (chunk: Buffer) => {
    buffer += chunk.toString();
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      let event: Record<string, unknown>;
      try {
        event = JSON.parse(trimmed);
      } catch {
        continue;
      }

      const progress = mapProgress(event);
      if (progress && job.status === "processing") {
        job.progress = progress;
      }

      if (event.type === "result") {
        lastResultText = (event.result as string) || "";
        if (event.subtype === "error_max_turns") {
          lastResultText = "";
          job.status = "error";
          job.errorMessage = "分析达到回合数限制，请稍后重试。";
          job.progress = "";
        }
      }
    }
  });

  let stderrBuf = "";
  child.stderr?.on("data", (chunk: Buffer) => {
    stderrBuf += chunk.toString();
  });

  child.on("close", async (code) => {
    clearTimeout(timer);

    // Process remaining buffer
    if (buffer.trim()) {
      try {
        const event = JSON.parse(buffer.trim());
        if (event.type === "result") {
          lastResultText = (event.result as string) || "";
        }
      } catch {
        // ignore
      }
    }

    if (job.status !== "processing") return;

    if (!lastResultText) {
      job.status = "error";
      job.errorMessage = stderrBuf
        ? `AI 服务错误: ${stderrBuf.slice(0, 300)}`
        : "AI 分析返回空结果，请重试。";
      job.progress = "";
      return;
    }

    // Parse the result JSON — Claude may wrap it in markdown fences or preamble text
    job.progress = "正在保存报告...";

    let reportData: Record<string, unknown>;
    const jsonStr = extractJsonStr(lastResultText) || lastResultText.trim();
    const parsed = tryParse(jsonStr);

    if (parsed && parsed.report_type) {
      reportData = parsed;
    } else {
      // Fallback: wrap entire text as summary
      reportData = {
        report_type: "daily",
        summary: lastResultText.slice(0, 2000),
        thinking_process: lastResultText,
      };
    }

    reportData.report_date = reportDate;
    if (!reportData.report_type) reportData.report_type = "daily";
    if (!reportData.summary) reportData.summary = "";

    // Save to FastAPI
    try {
      const res = await fetch(`${FASTAPI_BASE}/api/ai/reports/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reportData),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`FastAPI ${res.status}: ${text}`);
      }
      const saved = await res.json() as { id: number; report_date: string };
      job.status = "completed";
      job.content = String(saved.id); // report ID for frontend
      job.progress = "";
    } catch (err) {
      job.status = "error";
      job.errorMessage = `报告保存失败: ${err instanceof Error ? err.message : "未知错误"}`;
      job.progress = "";
    }
  });

  child.on("error", (err) => {
    clearTimeout(timer);
    if (job.status === "processing") {
      job.status = "error";
      job.errorMessage = `无法启动 Claude CLI: ${err.message}`;
      job.progress = "";
    }
  });
}

// ── Review Job ──────────────────────────────────

const REVIEW_SYSTEM_PROMPT = `\
You are an expert A-share investment analyst conducting a post-mortem review of a completed trade.
You MUST analyze the entire buy-sell cycle and extract lessons learned.

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...
API base: http://localhost:8050

Your analysis should cover:
1. 买入时机评估: Was the entry timing good? What signals were correct/missed?
2. 持有期间分析: How did the stock perform during holding? Were there warning signs?
3. 卖出时机评估: Was the exit timing optimal? Should it have been earlier/later?
4. 新闻/事件影响: What news events impacted the trade?
5. 策略有效性: Did the strategy that generated the signal perform as expected?
6. 关键教训: What should be remembered for future similar situations?

Read the memory base at: /Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory/
Check semantic/strategy-knowledge.md for strategy performance data to cross-reference.

Output ONLY a JSON object:
{
  "review_thinking": "详细的复盘分析（中文，投资顾问风格，500-1000字）",
  "lessons_learned": "1-3句话总结关键教训",
  "memory_note": {
    "id": "trade-review-{stock_code}-{date}",
    "tags": ["trade-review", "{stock_code}", "profit|loss", "{strategy-name}"],
    "content": "一段精炼的记忆笔记（100-200字），包含：股票代码、持有天数、盈亏、关键教训"
  }
}

IMPORTANT: Inside JSON string values, NEVER use double quotes ("). Use 「」 for emphasis or quoting.
Answer in Chinese. Be thorough and honest about mistakes.`;

export function startReviewJob(
  reviewId: number,
  stockCode: string,
  stockName: string,
  tradesJson: string,
  pnl: number,
  pnlPct: number,
): string {
  const jobId = `review-${stockCode}-${Date.now()}`;

  const userPrompt = `\
复盘任务: ${stockName} (${stockCode})
盈亏: ¥${pnl.toFixed(2)} (${pnlPct.toFixed(1)}%)

交易记录:
${tradesJson}

请分析这笔完整的买卖周期，输出 JSON 复盘报告。`;

  const args = [
    "--print",
    "-p", userPrompt,
    "--output-format", "text",
    "--model", MODEL,
    "--max-turns", "10",
    "--system-prompt", REVIEW_SYSTEM_PROMPT,
  ];

  const child = spawn(CLAUDE_BIN, args, {
    cwd: "/Users/allenqiang/stockagent",
    env: { ...process.env, NO_PROXY: "localhost,127.0.0.1" },
    stdio: ["ignore", "pipe", "pipe"],
  });

  let output = "";
  child.stdout?.on("data", (chunk: Buffer) => { output += chunk.toString(); });
  child.stderr?.on("data", () => { /* ignore */ });

  // Timeout protection
  const timer = setTimeout(() => {
    child.kill("SIGTERM");
    console.error(`[review ${jobId}] Timed out after 10 minutes`);
  }, REVIEW_TIMEOUT_MS);

  child.on("close", async () => {
    clearTimeout(timer);
    try {
      // Parse the review JSON from Claude output
      const jsonStr = extractJsonStr(output);
      if (!jsonStr) {
        console.error(`[review ${jobId}] No JSON found in output`);
        return;
      }
      const parsed = tryParse(jsonStr);
      if (!parsed) {
        console.error(`[review ${jobId}] Failed to parse JSON`);
        return;
      }

      const reviewThinking = (parsed.review_thinking as string) || "";
      const memoryNote = parsed.memory_note as { id?: string; tags?: string[]; content?: string } | undefined;

      // Update the review record via API
      await fetch(`${FASTAPI_BASE}/api/bot/reviews/${reviewId}/update`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_thinking: reviewThinking,
          memory_note_id: memoryNote?.id || null,
          memory_synced: false,  // Will be set to true after memory file is written
        }),
      });

      // Write memory note if provided
      if (memoryNote?.id && memoryNote?.content) {
        const fs = await import("fs");
        const path = await import("path");

        const memoryDir = "/Users/allenqiang/.claude/projects/-Users-allenqiang-stockagent/memory";
        const tradesDir = path.join(memoryDir, "episodic", "trades");

        // Ensure directory exists
        fs.mkdirSync(tradesDir, { recursive: true });

        const noteFile = path.join(tradesDir, `${memoryNote.id}.md`);
        const noteContent = `---
id: "${memoryNote.id}"
type: episodic
tags: ${JSON.stringify(memoryNote.tags || [])}
created: "${new Date().toISOString().split('T')[0]}"
relevance: high
---

${memoryNote.content}
`;
        fs.writeFileSync(noteFile, noteContent);
        console.log(`[review ${jobId}] Memory note written: ${noteFile}`);

        // Mark as memory synced
        await fetch(`${FASTAPI_BASE}/api/bot/reviews/${reviewId}/update`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ memory_synced: true, memory_note_id: memoryNote.id }),
        });
      }

      console.log(`[review ${jobId}] Review completed for ${stockCode}`);
    } catch (err) {
      console.error(`[review ${jobId}] Error:`, err);
    }
  });

  child.on("error", (err) => {
    clearTimeout(timer);
    console.error(`[review ${jobId}] Spawn error:`, err);
  });

  console.log(`[review ${jobId}] Started review for ${stockCode}`);
  return jobId;
}
