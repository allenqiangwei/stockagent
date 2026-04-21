"""Claude CLI runner — executes Claude Code CLI for AI analysis and chat.

Mirrors the proven pattern from POAMASTER's claude-bridge.ts:
- Hardcoded binary path
- Minimal env (just NO_PROXY for local API calls)
- --append-system-prompt instead of --system-prompt
- No --allowedTools (bypassPermissions covers it)
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
_CLAUDE = "/opt/homebrew/bin/claude"
_MODEL = "sonnet"

_ANALYSIS_SYSTEM_PROMPT = """\
You are an expert A-share (China stock market) analyst integrated into the StockAgent system.
You have access to a local API at http://localhost:8050 with these endpoints:

- GET /api/signals/today — today's trading signals (scored stocks)
- GET /api/signals/history?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD — historical signals
- GET /api/strategies — list of active strategies
- GET /api/market/kline?code=XXXXXX&period=daily&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD — K-line data
- GET /api/market/quote?code=XXXXXX — real-time quote
- GET /api/news/archive?limit=N — query the most recent news from database. Returns returned (number actually fetched). Use FIXED limits: weekdays (Mon-Sat) limit=3000, Sunday limit=5000. Do NOT use start_date/end_date — always fetch by limit only (most recent N articles).
- GET /api/news/sentiment/latest — latest DeepSeek sentiment analysis summary
- POST /api/news/sentiment/analyze?hours_back=N — trigger fresh DeepSeek sentiment analysis (N=hours to look back, default 24, max 168)
- GET /api/stocks/watchlist — user's watchlist
- GET /api/bot/portfolio — current bot holdings (stock_code, stock_name, quantity, avg_cost, total_invested)
- GET /api/bot/plans/pending — pending trade plans not yet executed
- GET /api/bot/trades?limit=20 — recent trade history
- GET /api/beta/scorecard?stock_codes=CODE1,CODE2 — Beta因子记分卡: 候选股的非技术面评分(板块胜率、情绪可靠度、估值风险)
- GET /api/beta/insights/active — 历史Beta因子知识: 哪些非技术因子在过去准确/误导

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...

CRITICAL WORKFLOW:
1. FIRST fetch current holdings via /api/bot/portfolio and pending plans via /api/bot/plans/pending
2. Fetch news from the DATABASE via /api/news/archive — use FIXED limit by weekday (do NOT use date range):
   - Monday to Saturday: GET /api/news/archive?limit=3000
   - Sunday: GET /api/news/archive?limit=5000
   - Summarize the key news themes and their potential market impact in your report
3. Then fetch signals, sentiment, and market data
4. Base your recommendations on ACTUAL holdings — do NOT recommend "hold" for stocks you don't hold

注意：今日信号是基于 AI 策略选择引擎筛选的策略生成的，不是全部策略库。
信号中的 alpha_score 反映了选中策略的综合评分，直接在 recommendations 中传回。

Your task is to produce a daily market analysis report with:
1. Market regime assessment (bull/bear/sideways) with confidence 0-100
2. Key signal highlights — which stocks have strong buy/sell signals and why
3. Strategy performance — which strategies are firing and their recent track record
4. Risk warnings — any concerning patterns
5. Top 5 trade plan highlights — read from /api/bot/plans/pending and present the top 5 by combined_score

IMPORTANT — Trade plans are PRE-CREATED by the signal system:
The system automatically creates trade plans from ALL buy signals using the Beta scorer.
You do NOT need to decide what to buy — plans already exist at /api/bot/plans/pending.
Your job is to:
1. Read the pending plans and present the TOP 5 (by combined_score) in your recommendations
2. Provide market context, risk analysis, and news sentiment for each
3. For existing holdings (/api/bot/portfolio), recommend "hold" or "sell" based on news/fundamentals

IMPORTANT — Automatic Exit Monitoring:
The system has automatic exit monitoring for all bot positions:
- Stop Loss (SL): auto-triggers when daily low reaches threshold
- Take Profit (TP): auto-triggers when daily high reaches threshold
- Max Hold Days (MHD): auto-sells when holding period exceeds limit
These exits happen BEFORE your analysis runs. You do NOT need to recommend "sell" for these cases.
Your sell recommendations should focus on: fundamental changes, negative news events, or situations
where you believe a position should exit BEFORE the automatic triggers fire.

Recommendation action rules:
- "buy": Pick the top 5 distinct stocks from /api/bot/plans/pending (sorted by combined_score desc, one entry per stock_code). Use the alpha_score and beta_score from that plan entry directly — do NOT look up signals/today for these values.
- "hold": ONLY for stocks the bot currently holds and should keep. Never use "hold" for stocks not in portfolio.
- "sell" / "reduce": ONLY for stocks currently held that should be exited or reduced based on news/fundamentals.
- Do NOT invent buy recommendations — only include plans that already exist in /api/bot/plans/pending.

Output your analysis as a JSON object with these fields:
- report_type: "daily"
- market_regime: "bull" | "bear" | "sideways" | "transition"
- market_regime_confidence: float 0.0-1.0 (e.g. 0.75 means 75% confident)
- recommendations: list of {stock_code, stock_name, action, reason, entry_price, stop_loss, target, alpha_score, beta_score}
  - entry_price: REQUIRED — the realistic next-day execution price (see rules above)
  - target: your price target after the position is opened (for tracking, not execution)
  - alpha_score: copy directly from /api/bot/plans/pending for this stock (the "alpha_score" field). Do NOT use /api/signals/today for alpha_score.
  - beta_score: environment factor (0-1) reflecting market regime, sector heat, valuation, and sentiment. Already factored into combined_score. 0.5=neutral, >0.6=favorable, <0.4=unfavorable.
- strategy_actions: list of {strategy_name, signal_count, top_stocks}
- thinking_process: your detailed reasoning (string)
- summary: 2-3 sentence executive summary (string)

Return ONLY the JSON object, no markdown fences or extra text.
"""

_CHAT_SYSTEM_PROMPT = """\
You are an expert A-share (China stock market) analyst assistant in the StockAgent system.
You can access local APIs at http://localhost:8050 to answer questions about stocks, signals, and strategies.

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...

Available API endpoints:
- GET /api/signals/today — today's signals
- GET /api/signals/history?start_date=&end_date= — historical signals
- GET /api/strategies — active strategies
- GET /api/market/kline?code=&period=daily&start_date=&end_date= — K-line data
- GET /api/market/quote?code= — real-time quote
- GET /api/news/archive?start_date=&end_date=&keyword=&limit= — historical news from database
- GET /api/news/sentiment/latest — DeepSeek sentiment analysis summary
- GET /api/stocks/watchlist — watchlist
- GET /api/stocks/search?keyword= — search stocks
- GET /api/bot/portfolio — current bot holdings
- GET /api/bot/plans/pending — pending trade plans
- GET /api/bot/trades?limit=20 — recent trade history

Answer in Chinese. Be concise but thorough. Use data from the APIs to support your analysis.
When discussing holdings or trade actions, always check /api/bot/portfolio first for actual positions.
"""

_STRATEGY_SELECTION_PROMPT_TEMPLATE = """\
You are the StockAgent 策略选择引擎 (Strategy Selection Engine).

Your job is to assess the current A-share market regime and select the best 3-5 strategy families \
for today's signal generation.

You have access to a local API at http://localhost:8050 with these endpoints:
- GET /api/news/archive?limit=N — query the most recent news. Returns returned (number actually fetched). Use limit=3000 (Mon-Sat) or limit=5000 (Sun). Do NOT use date range parameters.
- GET /api/news/sentiment/latest — latest DeepSeek sentiment analysis summary
- GET /api/market/quote?code=000001 — Shanghai Composite index quote (proxy for market state)
- GET /api/bot/portfolio — current bot holdings

IMPORTANT: When calling curl, always use: NO_PROXY=localhost,127.0.0.1 curl ...

Here is the table of all available strategy families and their regime-specific performance:

{family_table}

Selection rules:
1. Assess current market regime: bull / bear / ranging / transition
2. Match regime to each family's historical performance in that regime (win rate, return, drawdown)
3. If the bot currently holds positions (check /api/bot/portfolio), ensure at least one selected \
family has strong sell-signal coverage so exit signals can fire
4. Pick 3-5 families that balance offense (high return in current regime) and defense (low drawdown)
5. Prefer families with higher StdA (standardized alpha) scores
6. Diversify across indicator types — avoid selecting multiple families from the same indicator group

Output your result as a JSON object with exactly these fields:
{{
  "market_assessment": "<bull|bear|ranging|transition> — 1-2 sentence reasoning",
  "selected_families": ["FamilyName1", "FamilyName2", "FamilyName3"],
  "reasoning": "Detailed explanation of why these families were chosen, regime match, offense/defense balance"
}}

Return ONLY the JSON object, no markdown fences or extra text.
"""


def run_strategy_selection(family_table: str) -> dict | None:
    """Run Claude to analyze market and select optimal strategy families.

    Args:
        family_table: Markdown table of strategy families with regime performance data.

    Returns:
        Dict with market_assessment, selected_families, reasoning — or None on failure.
    """
    prompt = (
        "Analyze the current A-share market regime using the available APIs, "
        "then select the best 3-5 strategy families from the provided table. "
        "Return the result as the specified JSON object."
    )

    system_prompt = _STRATEGY_SELECTION_PROMPT_TEMPLATE.format(
        family_table=family_table
    )

    args = [
        "-p", prompt,
        "--output-format", "json",
        "--model", "opus",
        "--append-system-prompt", system_prompt,
        "--permission-mode", "bypassPermissions",
    ]

    try:
        output = _run_cli(args, timeout=300)
    except Exception as e:
        logger.error("Strategy selection CLI failed: %s", e)
        return None

    result_text = output.get("result", "")
    if not result_text:
        logger.warning("Strategy selection returned empty result")
        return None

    # Parse inner JSON — strip markdown fences if present
    cleaned = result_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Strategy selection result not valid JSON: %s", cleaned[:500])
        return None

    # Validate selected_families
    families = result.get("selected_families")
    if not isinstance(families, list) or len(families) == 0:
        logger.error("Strategy selection returned no families: %s", result)
        return None

    logger.info(
        "Strategy selection complete — regime=%s, families=%s",
        result.get("market_assessment", "unknown"),
        families,
    )
    return result


def _run_cli(args: list[str], timeout: int = 180) -> dict:
    """Run Claude CLI and return parsed JSON output.

    Follows POAMASTER pattern: minimal env, parse stdout as JSON.
    Strips CLAUDECODE env var to avoid nested-session detection.
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = subprocess.run(
        [_CLAUDE] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=_PROJECT_ROOT,
        env=env,
    )

    output = json.loads(proc.stdout)

    if output.get("is_error"):
        raise RuntimeError(output.get("result", "Unknown CLI error"))

    return output


def run_daily_analysis(trade_date: str) -> Optional[dict]:
    """Run Claude to produce a daily analysis report."""
    from api.services.job_manager import get_job_manager
    jm = get_job_manager()
    job_id = jm.create("ai_analysis", f"AI analysis {trade_date}", triggered_by="system")
    jm.start(job_id)

    prompt = (
        f"Today is {trade_date}. Please analyze today's A-share market situation "
        f"using the available APIs. Fetch today's signals, check the watchlist, "
        f"get latest sentiment, and produce a comprehensive daily report. "
        f"Return the result as the specified JSON object."
    )

    args = [
        "-p", prompt,
        "--output-format", "json",
        "--model", _MODEL,
        "--append-system-prompt", _ANALYSIS_SYSTEM_PROMPT,
        "--permission-mode", "bypassPermissions",
    ]

    try:
        output = _run_cli(args, timeout=300)
    except Exception as e:
        logger.error("AI daily analysis failed: %s", e)
        jm.fail(job_id, str(e)[:500])
        return None

    result_text = output.get("result", "")
    if not result_text:
        logger.warning("AI analysis returned empty result")
        jm.fail(job_id, "Empty result from Claude CLI")
        return None

    # Parse inner JSON from result text
    cleaned = result_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("AI result not parseable as JSON, wrapping as summary")
        result = {
            "report_type": "daily",
            "summary": result_text[:2000],
            "thinking_process": result_text,
        }

    # Ensure required fields
    result.setdefault("report_type", "daily")
    result.setdefault("summary", "")
    jm.succeed(job_id, f"Analysis complete for {trade_date}")
    return result


def run_chat(
    message: str,
    claude_session_id: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """Run a chat interaction with Claude.

    Returns (response_text, session_id).
    """
    args = [
        "-p", message,
        "--output-format", "json",
        "--model", _MODEL,
        "--append-system-prompt", _CHAT_SYSTEM_PROMPT,
        "--permission-mode", "bypassPermissions",
    ]

    if claude_session_id:
        args = ["--resume", claude_session_id] + args

    try:
        output = _run_cli(args, timeout=180)
        result_text = output.get("result", "")
        if not result_text and output.get("subtype") == "error_max_turns":
            result_text = "抱歉，这个问题比较复杂，达到了回合数限制。请简化问题或拆分成多个小问题。"
        session_id = output.get("session_id", claude_session_id)
        return (result_text, session_id)
    except json.JSONDecodeError:
        logger.error("Claude CLI returned non-JSON output")
        return ("AI 服务返回了无效的响应格式。", claude_session_id)
    except RuntimeError as e:
        error_msg = str(e)
        logger.error("Claude CLI error: %s", error_msg[:500])
        if "authenticate" in error_msg.lower():
            return ("AI 服务认证失败，请确保没有其他 Claude Code 会话在运行。", claude_session_id)
        return (f"AI 服务暂时不可用: {error_msg[:200]}", claude_session_id)
    except subprocess.TimeoutExpired:
        logger.error("Claude CLI timed out")
        return ("AI 响应超时，请稍后重试。", claude_session_id)
    except FileNotFoundError:
        logger.error("Claude CLI not found at %s", _CLAUDE)
        return ("Claude CLI 未安装。", None)
