# AI-Driven Signal Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an AI-driven analysis page where Claude CLI automatically generates daily market reports and users can chat about the market through a web interface.

**Architecture:** FastAPI backend calls `claude -p` via subprocess for both scheduled daily analysis and interactive chat. Reports are stored in SQLite via SQLAlchemy ORM. Frontend is a Next.js page with report viewer and chat widget.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Claude CLI (`claude -p`), Next.js 16, shadcn/ui, TanStack Query

---

### Task 1: SQLAlchemy ORM Models

**Files:**
- Create: `api/models/ai_analyst.py`
- Modify: `api/main.py:360-362` (import new model so tables are created)

**Step 1: Create the model file**

Create `api/models/ai_analyst.py`:

```python
"""AI Analyst ORM models — reports and chat sessions."""

from datetime import datetime

from sqlalchemy import String, Float, Integer, DateTime, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AIReport(Base):
    __tablename__ = "ai_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[str] = mapped_column(String(10), index=True)
    report_type: Mapped[str] = mapped_column(String(20), default="daily_analysis")
    market_regime: Mapped[str] = mapped_column(String(20), nullable=True)
    market_regime_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    recommendations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    strategy_actions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    thinking_process: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_ai_report_date_type", "report_date", "report_type"),
    )


class AIChatSession(Base):
    __tablename__ = "ai_chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    claude_session_id: Mapped[str] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    messages: Mapped[dict] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now,
    )
```

**Step 2: Register model import in `api/main.py`**

In `api/main.py`, inside the `lifespan()` function, after line 362 (`import api.models.news_sentiment`), add:

```python
    import api.models.ai_analyst  # noqa: F401 — register AI analyst tables
```

**Step 3: Verify tables are created**

Run: `cd /Users/allenqiang/stockagent && NO_PROXY=localhost,127.0.0.1 python -c "from api.models.ai_analyst import AIReport, AIChatSession; from api.models.base import engine, Base; Base.metadata.create_all(bind=engine); print('OK: ai_reports + ai_chat_sessions tables created')"`

Expected: `OK: ai_reports + ai_chat_sessions tables created`

---

### Task 2: Claude CLI Runner Service

**Files:**
- Create: `api/services/claude_runner.py`

**Step 1: Create the Claude CLI wrapper service**

Create `api/services/claude_runner.py`:

```python
"""Claude CLI runner — calls claude -p as subprocess for AI analysis and chat."""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Project root for Claude to read files from
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)

_ANALYSIS_SYSTEM_PROMPT = """你是A股量化交易系统的AI分析师。你的任务是每天收盘后分析市场并给出操作建议。

## 可用工具

你可以通过 Bash 工具执行 curl 命令访问后端API (所有API前缀 http://127.0.0.1:8050):
- GET  /api/signals/today — 今日信号 (含 alpha_top 推荐)
- GET  /api/market/index-kline/000001.SH?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD — 上证指数K线
- GET  /api/strategies — 策略列表
- GET  /api/backtest/runs?limit=10 — 最近回测结果
- PUT  /api/strategies/{id} — 修改策略 (enabled, exit_config等)
- POST /api/backtest/run/sync — 运行回测验证修改效果

curl 命令需设置环境变量: NO_PROXY=localhost,127.0.0.1

## 分析框架

1. 市场阶段判断: 获取大盘最近数据，判断当前是牛市/熊市/震荡
2. 信号解读: 获取今日信号和Alpha Top推荐，分析每只推荐股票
3. 策略复盘: 查看策略列表和最近回测，评估当前策略组合
4. 自主操作: 如需调整策略(启停/调参)，直接调用API
5. 输出结构化JSON报告

## 输出格式

输出严格 JSON (不要markdown代码块包裹):
{
  "market_regime": "bull|bear|range",
  "market_regime_confidence": 0.0到1.0,
  "summary": "一句话总结今日市场和操作建议",
  "recommendations": [
    {"stock_code": "000001", "stock_name": "平安银行", "action": "buy", "reason": "分析理由", "alpha_score": 85}
  ],
  "strategy_actions": [
    {"action": "disable|enable|modify", "strategy_id": 1, "strategy_name": "...", "reason": "操作理由", "details": {}}
  ],
  "thinking_process": "完整的分析思考过程(中文，详细)"
}"""

_CHAT_SYSTEM_PROMPT = """你是A股量化交易系统的AI助手。用户想和你讨论当前市场情况。

你可以通过 Bash 工具执行 curl 命令查询后端API (http://127.0.0.1:8050):
- GET /api/signals/today — 今日信号
- GET /api/market/index-kline/000001.SH?period=daily&start=YYYY-MM-DD&end=YYYY-MM-DD — 大盘K线
- GET /api/market/quote/{code} — 个股实时行情
- GET /api/strategies — 策略列表

curl 命令需设置: NO_PROXY=localhost,127.0.0.1

用中文回答，简洁专业。如需查数据，先调API再回答。"""


def run_daily_analysis(trade_date: str) -> Optional[dict]:
    """Run Claude CLI for daily market analysis. Returns parsed JSON report or None."""
    from datetime import datetime, timedelta

    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    try:
        dt = datetime.strptime(trade_date, "%Y-%m-%d")
        weekday = weekday_names[dt.weekday()]
    except ValueError:
        weekday = "?"

    # Date range for index data (3 months back)
    start_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")

    prompt = f"""今天是 {trade_date} (星期{weekday})。

请执行每日市场分析:
1. 用 curl 获取今日信号: curl -s http://127.0.0.1:8050/api/signals/today
2. 用 curl 查看大盘走势: curl -s "http://127.0.0.1:8050/api/market/index-kline/000001.SH?period=daily&start={start_date}&end={trade_date}"
3. 对 Alpha Top 推荐股票给出详细分析
4. 用 curl 查看策略列表: curl -s http://127.0.0.1:8050/api/strategies
5. 如果发现策略需要调整，直接调用PUT API修改
6. 输出JSON报告

{"今天是周五，请额外做一次周度深度复盘，评估本周整体表现。" if weekday == "五" else ""}"""

    return _run_claude(prompt, _ANALYSIS_SYSTEM_PROMPT, timeout=300, max_budget=1.0)


def run_chat(message: str, claude_session_id: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Run Claude CLI for chat. Returns (response_text, claude_session_id).

    If claude_session_id is provided, resumes the existing session.
    Returns the new/existing claude_session_id for future resumption.
    """
    cmd = ["claude", "-p", "--output-format", "json"]

    if claude_session_id:
        cmd.extend(["--resume", claude_session_id])
    else:
        cmd.extend([
            "--system-prompt", _CHAT_SYSTEM_PROMPT,
            "--permission-mode", "bypassPermissions",
            "--allowedTools", "Bash Read Glob Grep",
        ])

    cmd.append(message)

    env = {**os.environ, "NO_PROXY": "localhost,127.0.0.1"}

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=_PROJECT_ROOT, env=env,
        )

        if result.returncode != 0:
            logger.warning("Claude chat failed (rc=%d): %s", result.returncode, result.stderr[:500])
            return "抱歉，AI暂时无法响应，请稍后再试。", claude_session_id

        # Parse JSON output to get response text and session_id
        try:
            data = json.loads(result.stdout)
            response_text = data.get("result", result.stdout)
            new_session_id = data.get("session_id", claude_session_id)
            return response_text, new_session_id
        except json.JSONDecodeError:
            # Plain text response
            return result.stdout.strip(), claude_session_id

    except subprocess.TimeoutExpired:
        logger.error("Claude chat timed out")
        return "AI响应超时，请稍后再试。", claude_session_id
    except FileNotFoundError:
        logger.error("Claude CLI not found — is it installed?")
        return "Claude CLI 未安装。请先运行: npm install -g @anthropic-ai/claude-code", claude_session_id


def _run_claude(prompt: str, system_prompt: str, timeout: int = 300, max_budget: float = 1.0) -> Optional[dict]:
    """Run claude -p and return parsed JSON output."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
        "--allowedTools", "Bash Read Glob Grep",
        "--system-prompt", system_prompt,
        "--max-budget-usd", str(max_budget),
        prompt,
    ]

    env = {**os.environ, "NO_PROXY": "localhost,127.0.0.1"}

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=_PROJECT_ROOT, env=env,
        )

        if result.returncode != 0:
            logger.error("Claude CLI failed (rc=%d): %s", result.returncode, result.stderr[:500])
            return None

        # The JSON output format wraps result in {"result": "..."}
        # The actual analysis JSON is inside the result string
        try:
            outer = json.loads(result.stdout)
            result_text = outer.get("result", result.stdout)
        except json.JSONDecodeError:
            result_text = result.stdout

        # Extract JSON from the result text (may have markdown wrapping)
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            return json.loads(json_match.group())

        logger.warning("Could not parse JSON from Claude output: %s", result_text[:200])
        return None

    except subprocess.TimeoutExpired:
        logger.error("Claude CLI timed out after %ds", timeout)
        return None
    except FileNotFoundError:
        logger.error("Claude CLI not found in PATH")
        return None
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude JSON output: %s", e)
        return None
```

**Step 2: Verify module imports cleanly**

Run: `cd /Users/allenqiang/stockagent && python -c "from api.services.claude_runner import run_daily_analysis, run_chat; print('OK')"`

Expected: `OK`

---

### Task 3: AI Scheduler (integrate into SignalScheduler)

**Files:**
- Modify: `api/services/signal_scheduler.py:96-128` (add AI analysis step to `_do_refresh`)

**Step 1: Add AI analysis step to `_do_refresh()`**

In `api/services/signal_scheduler.py`, after the existing signal generation (line 122 `self._last_run_date = trade_date`), add the AI analysis call:

```python
                # Step 3: AI Analysis
                self._run_ai_analysis(trade_date, db)
```

Then add the new method after `_sync_daily_prices()`:

```python
    def _run_ai_analysis(self, trade_date: str, db):
        """Run Claude CLI daily analysis and store report."""
        try:
            from api.services.claude_runner import run_daily_analysis
            from api.models.ai_analyst import AIReport

            logger.info("Starting AI daily analysis for %s...", trade_date)
            report = run_daily_analysis(trade_date)

            if report:
                ai_report = AIReport(
                    report_date=trade_date,
                    report_type="daily_analysis",
                    market_regime=report.get("market_regime"),
                    market_regime_confidence=report.get("market_regime_confidence"),
                    recommendations=report.get("recommendations"),
                    strategy_actions=report.get("strategy_actions"),
                    thinking_process=report.get("thinking_process", ""),
                    summary=report.get("summary", ""),
                )
                db.add(ai_report)
                db.commit()
                logger.info("AI analysis report saved for %s", trade_date)
            else:
                logger.warning("AI analysis returned no result for %s", trade_date)
        except Exception as e:
            logger.error("AI analysis failed (non-fatal): %s", e)
```

**Step 2: Verify the scheduler module still loads**

Run: `cd /Users/allenqiang/stockagent && python -c "from api.services.signal_scheduler import SignalScheduler; print('OK')"`

Expected: `OK`

---

### Task 4: Pydantic Schemas for AI API

**Files:**
- Create: `api/schemas/ai_analyst.py`

**Step 1: Create schemas**

Create `api/schemas/ai_analyst.py`:

```python
"""AI Analyst Pydantic schemas — request/response models."""

from typing import Optional
from pydantic import BaseModel


class AIReportResponse(BaseModel):
    id: int
    report_date: str
    report_type: str
    market_regime: Optional[str] = None
    market_regime_confidence: Optional[float] = None
    recommendations: Optional[list[dict]] = None
    strategy_actions: Optional[list[dict]] = None
    thinking_process: str = ""
    summary: str = ""
    created_at: str

    model_config = {"from_attributes": True}


class AIReportListItem(BaseModel):
    id: int
    report_date: str
    report_type: str
    market_regime: Optional[str] = None
    summary: str = ""
    created_at: str

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class ChatSessionResponse(BaseModel):
    id: int
    session_id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
```

**Step 2: Verify import**

Run: `cd /Users/allenqiang/stockagent && python -c "from api.schemas.ai_analyst import AIReportResponse, ChatRequest, ChatResponse; print('OK')"`

Expected: `OK`

---

### Task 5: AI Router (Reports + Chat API)

**Files:**
- Create: `api/routers/ai_analyst.py`
- Modify: `api/main.py:20-21` (add import)
- Modify: `api/main.py:428-435` (register router)

**Step 1: Create the AI router**

Create `api/routers/ai_analyst.py`:

```python
"""AI Analyst router — reports, chat, manual trigger."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.ai_analyst import AIReport, AIChatSession
from api.schemas.ai_analyst import (
    AIReportResponse,
    AIReportListItem,
    ChatRequest,
    ChatResponse,
    ChatSessionResponse,
)

router = APIRouter(prefix="/api/ai", tags=["ai-analyst"])


# ── Reports ────────────────────────────────────

@router.get("/reports", response_model=list[AIReportListItem])
def list_reports(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List recent AI analysis reports (newest first)."""
    rows = (
        db.query(AIReport)
        .order_by(AIReport.report_date.desc(), AIReport.id.desc())
        .limit(limit)
        .all()
    )
    return [
        AIReportListItem(
            id=r.id,
            report_date=r.report_date,
            report_type=r.report_type,
            market_regime=r.market_regime,
            summary=r.summary,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.get("/reports/{report_id}", response_model=AIReportResponse)
def get_report(report_id: int, db: Session = Depends(get_db)):
    """Get a single AI report by ID."""
    r = db.query(AIReport).get(report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return AIReportResponse(
        id=r.id,
        report_date=r.report_date,
        report_type=r.report_type,
        market_regime=r.market_regime,
        market_regime_confidence=r.market_regime_confidence,
        recommendations=r.recommendations,
        strategy_actions=r.strategy_actions,
        thinking_process=r.thinking_process,
        summary=r.summary,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


@router.get("/reports/date/{date}")
def get_report_by_date(date: str, db: Session = Depends(get_db)):
    """Get AI report for a specific date."""
    r = (
        db.query(AIReport)
        .filter(AIReport.report_date == date)
        .order_by(AIReport.id.desc())
        .first()
    )
    if not r:
        raise HTTPException(404, "No report for this date")
    return AIReportResponse(
        id=r.id,
        report_date=r.report_date,
        report_type=r.report_type,
        market_regime=r.market_regime,
        market_regime_confidence=r.market_regime_confidence,
        recommendations=r.recommendations,
        strategy_actions=r.strategy_actions,
        thinking_process=r.thinking_process,
        summary=r.summary,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


@router.get("/reports/dates")
def list_report_dates(
    limit: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Return list of dates that have reports (for calendar highlighting)."""
    from sqlalchemy import distinct
    rows = (
        db.query(distinct(AIReport.report_date))
        .order_by(AIReport.report_date.desc())
        .limit(limit)
        .all()
    )
    return {"dates": [r[0] for r in rows]}


@router.post("/analyze")
def trigger_analysis(
    date: str = Query("", description="YYYY-MM-DD, default today"),
    db: Session = Depends(get_db),
):
    """Manually trigger AI analysis for a date."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    from api.services.claude_runner import run_daily_analysis

    report = run_daily_analysis(date)
    if not report:
        raise HTTPException(500, "AI analysis produced no output")

    ai_report = AIReport(
        report_date=date,
        report_type="daily_analysis",
        market_regime=report.get("market_regime"),
        market_regime_confidence=report.get("market_regime_confidence"),
        recommendations=report.get("recommendations"),
        strategy_actions=report.get("strategy_actions"),
        thinking_process=report.get("thinking_process", ""),
        summary=report.get("summary", ""),
    )
    db.add(ai_report)
    db.commit()
    db.refresh(ai_report)

    return {"id": ai_report.id, "report_date": date, "summary": ai_report.summary}


# ── Chat ───────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """Send a message to Claude AI and get a response."""
    from api.services.claude_runner import run_chat

    # Find or create session
    session = None
    if req.session_id:
        session = db.query(AIChatSession).filter_by(session_id=req.session_id).first()

    claude_sid = session.claude_session_id if session else None

    response_text, new_claude_sid = run_chat(req.message, claude_sid)

    now = datetime.now()
    if not session:
        session = AIChatSession(
            session_id=str(uuid.uuid4()),
            claude_session_id=new_claude_sid,
            title=req.message[:50],
            messages=[],
            created_at=now,
            updated_at=now,
        )
        db.add(session)

    # Update session
    msgs = session.messages or []
    msgs.append({"role": "user", "content": req.message, "timestamp": now.isoformat()})
    msgs.append({"role": "assistant", "content": response_text, "timestamp": now.isoformat()})
    session.messages = msgs
    session.claude_session_id = new_claude_sid
    session.updated_at = now
    db.commit()

    return ChatResponse(response=response_text, session_id=session.session_id)


@router.get("/chat/sessions", response_model=list[ChatSessionResponse])
def list_chat_sessions(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List recent chat sessions."""
    rows = (
        db.query(AIChatSession)
        .order_by(AIChatSession.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        ChatSessionResponse(
            id=r.id,
            session_id=r.session_id,
            title=r.title,
            message_count=len(r.messages) if r.messages else 0,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in rows
    ]


@router.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str, db: Session = Depends(get_db)):
    """Get full chat history for a session."""
    session = db.query(AIChatSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "session_id": session.session_id,
        "title": session.title,
        "messages": session.messages or [],
    }
```

**Step 2: Register the router in `api/main.py`**

In `api/main.py`, add import at line 20-21 area:

```python
from api.routers import market, stocks, strategies, signals, backtest, news, config, ai_lab, ai_analyst
```

And add the router registration after line 435:

```python
app.include_router(ai_analyst.router)
```

**Step 3: Verify API starts and new routes are registered**

Run: `cd /Users/allenqiang/stockagent && python -c "from api.routers.ai_analyst import router; print('Routes:', [r.path for r in router.routes]); print('OK')"`

Expected: Routes list containing `/reports`, `/chat`, etc., followed by `OK`

---

### Task 6: Frontend TypeScript Types + API Client

**Files:**
- Modify: `web/src/types/index.ts` (add AI types at the end)
- Modify: `web/src/lib/api.ts` (add AI API module)
- Modify: `web/src/hooks/use-queries.ts` (add AI query hooks)

**Step 1: Add TypeScript types**

Append to `web/src/types/index.ts`:

```typescript
// ── AI Analyst ──────────────────────────────────
export interface AIReportListItem {
  id: number;
  report_date: string;
  report_type: string;
  market_regime: string | null;
  summary: string;
  created_at: string;
}

export interface AIReport {
  id: number;
  report_date: string;
  report_type: string;
  market_regime: string | null;
  market_regime_confidence: number | null;
  recommendations: { stock_code: string; stock_name: string; action: string; reason: string; alpha_score: number }[] | null;
  strategy_actions: { action: string; strategy_id: number; strategy_name: string; reason: string; details: Record<string, unknown> }[] | null;
  thinking_process: string;
  summary: string;
  created_at: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export interface ChatSessionListItem {
  id: number;
  session_id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}
```

**Step 2: Add API client functions**

Append to `web/src/lib/api.ts` (before the closing of the file):

```typescript
// ── AI Analyst ───────────────────────────────────────
import type { AIReportListItem, AIReport, ChatSessionListItem, ChatMessage } from "@/types";

export const ai = {
  reports: (limit = 30) =>
    request<AIReportListItem[]>(`/ai/reports?limit=${limit}`),
  report: (id: number) =>
    request<AIReport>(`/ai/reports/${id}`),
  reportByDate: (date: string) =>
    request<AIReport>(`/ai/reports/date/${date}`),
  reportDates: (limit = 90) =>
    request<{ dates: string[] }>(`/ai/reports/dates?limit=${limit}`),
  triggerAnalysis: (date = "") =>
    post<{ id: number; report_date: string; summary: string }>(
      `/ai/analyze?date=${date}`, {}
    ),
  chat: (message: string, sessionId?: string) =>
    post<{ response: string; session_id: string }>(
      "/ai/chat",
      { message, session_id: sessionId || null }
    ),
  chatSessions: (limit = 20) =>
    request<ChatSessionListItem[]>(`/ai/chat/sessions?limit=${limit}`),
  chatHistory: (sessionId: string) =>
    request<{ session_id: string; title: string; messages: ChatMessage[] }>(
      `/ai/chat/sessions/${sessionId}`
    ),
};
```

**Step 3: Add TanStack Query hooks**

Append to `web/src/hooks/use-queries.ts`:

```typescript
// ── AI Analyst ───────────────────────────────────
import { ai } from "@/lib/api";

export function useAIReports(limit = 30) {
  return useQuery({
    queryKey: ["ai-reports", limit],
    queryFn: () => ai.reports(limit),
  });
}

export function useAIReport(id: number) {
  return useQuery({
    queryKey: ["ai-report", id],
    queryFn: () => ai.report(id),
    enabled: !!id,
  });
}

export function useAIReportByDate(date: string) {
  return useQuery({
    queryKey: ["ai-report-date", date],
    queryFn: () => ai.reportByDate(date),
    enabled: !!date,
    retry: false,
  });
}

export function useAIReportDates() {
  return useQuery({
    queryKey: ["ai-report-dates"],
    queryFn: () => ai.reportDates(),
  });
}

export function useAIChatSessions() {
  return useQuery({
    queryKey: ["ai-chat-sessions"],
    queryFn: () => ai.chatSessions(),
  });
}

export function useAIChatHistory(sessionId: string) {
  return useQuery({
    queryKey: ["ai-chat-history", sessionId],
    queryFn: () => ai.chatHistory(sessionId),
    enabled: !!sessionId,
  });
}

export function useAIChatMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { message: string; sessionId?: string }) =>
      ai.chat(data.message, data.sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-chat-sessions"] });
    },
  });
}

export function useTriggerAIAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (date?: string) => ai.triggerAnalysis(date),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-reports"] });
      qc.invalidateQueries({ queryKey: ["ai-report-dates"] });
    },
  });
}
```

**Step 4: Verify TypeScript compiles**

Run: `cd /Users/allenqiang/stockagent/web && npx tsc --noEmit 2>&1 | head -20`

Expected: No errors (or only pre-existing ones)

---

### Task 7: Frontend AI Page — Report Viewer

**Files:**
- Create: `web/src/app/ai/page.tsx`
- Modify: `web/src/components/nav-bar.tsx:26-36` (add AI nav item)

**Step 1: Add AI nav item**

In `web/src/components/nav-bar.tsx`, add to the `navItems` array (after lab, before strategies):

```typescript
  { href: "/ai", label: "AI分析", icon: BrainCircuit },
```

Note: `BrainCircuit` is already imported at line 23.

Update the `navItems` array — insert between the lab entry and strategies entry. Move the existing `BrainCircuit` import from lab to be shared (it's already imported).

Actually, lab already uses `BrainCircuit`. Change lab's icon to `FlaskConical` (already imported) and give AI the `BrainCircuit`. Wait — `FlaskConical` is already used by backtest. Use `Sparkles` for AI instead. Import it:

Add `Sparkles` to the lucide import, then:

```typescript
  { href: "/ai", label: "AI分析", icon: Sparkles },
```

**Step 2: Create the AI page**

Create `web/src/app/ai/page.tsx`:

```tsx
"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sparkles,
  Calendar,
  TrendingUp,
  TrendingDown,
  Minus,
  ChevronDown,
  ChevronUp,
  Loader2,
  Send,
  MessageSquare,
  Plus,
  RefreshCw,
} from "lucide-react";
import {
  useAIReports,
  useAIReportByDate,
  useAIReportDates,
  useAIChatSessions,
  useAIChatHistory,
  useAIChatMutation,
  useTriggerAIAnalysis,
} from "@/hooks/use-queries";
import type { AIReport, ChatMessage } from "@/types";

// ── Regime helpers ──────────────────────────────
function regimeLabel(r: string | null) {
  if (r === "bull") return "牛市";
  if (r === "bear") return "熊市";
  if (r === "range") return "震荡";
  return "未知";
}

function regimeBadge(r: string | null, conf: number | null) {
  const label = regimeLabel(r);
  const pct = conf ? `${(conf * 100).toFixed(0)}%` : "";
  if (r === "bull")
    return <Badge className="bg-green-600/20 text-green-400 border-green-600/30">{label} {pct}</Badge>;
  if (r === "bear")
    return <Badge className="bg-red-600/20 text-red-400 border-red-600/30">{label} {pct}</Badge>;
  return <Badge className="bg-yellow-600/20 text-yellow-400 border-yellow-600/30">{label} {pct}</Badge>;
}

// ── Report Viewer ───────────────────────────────
function ReportViewer({ report }: { report: AIReport }) {
  const [showThinking, setShowThinking] = useState(false);

  return (
    <div className="space-y-4">
      {/* Summary + Regime */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center gap-3 mb-3">
            <Sparkles className="h-5 w-5 text-violet-400" />
            <span className="text-lg font-medium">AI 每日分析</span>
            <span className="text-sm text-muted-foreground">{report.report_date}</span>
            {regimeBadge(report.market_regime, report.market_regime_confidence)}
          </div>
          <p className="text-sm">{report.summary}</p>
        </CardContent>
      </Card>

      {/* Recommendations */}
      {report.recommendations && report.recommendations.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">推荐股票</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {report.recommendations.map((rec, i) => (
                <div key={i} className="flex items-start gap-3 p-2 rounded-md bg-muted/30">
                  <Badge variant="outline" className="shrink-0 mt-0.5">
                    {rec.action === "buy" ? "买入" : rec.action}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-muted-foreground">{rec.stock_code}</span>
                      <span className="text-sm font-medium">{rec.stock_name}</span>
                      {rec.alpha_score > 0 && (
                        <span className="text-xs text-amber-400">Alpha {rec.alpha_score}</span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{rec.reason}</p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Strategy Actions */}
      {report.strategy_actions && report.strategy_actions.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">策略操作记录</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {report.strategy_actions.map((sa, i) => (
                <div key={i} className="flex items-start gap-2 text-sm">
                  <Badge
                    className={
                      sa.action === "disable"
                        ? "bg-red-600/20 text-red-400"
                        : sa.action === "enable"
                        ? "bg-green-600/20 text-green-400"
                        : "bg-blue-600/20 text-blue-400"
                    }
                  >
                    {sa.action}
                  </Badge>
                  <div>
                    <span className="font-medium">{sa.strategy_name}</span>
                    <p className="text-xs text-muted-foreground">{sa.reason}</p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Thinking Process (collapsible) */}
      {report.thinking_process && (
        <Card>
          <CardHeader className="pb-2 cursor-pointer" onClick={() => setShowThinking(!showThinking)}>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              思考过程
              {showThinking ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </CardTitle>
          </CardHeader>
          {showThinking && (
            <CardContent>
              <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-sans leading-relaxed">
                {report.thinking_process}
              </pre>
            </CardContent>
          )}
        </Card>
      )}
    </div>
  );
}

// ── Chat Widget ─────────────────────────────────
function ChatWidget() {
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const chatMutation = useAIChatMutation();

  const handleSend = () => {
    if (!input.trim() || chatMutation.isPending) return;
    const userMsg: ChatMessage = {
      role: "user",
      content: input,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    const currentInput = input;
    setInput("");

    chatMutation.mutate(
      { message: currentInput, sessionId: sessionId || undefined },
      {
        onSuccess: (data) => {
          setSessionId(data.session_id);
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: data.response, timestamp: new Date().toISOString() },
          ]);
        },
        onError: () => {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: "抱歉，AI暂时无法响应。", timestamp: new Date().toISOString() },
          ]);
        },
      }
    );
  };

  const handleNewChat = () => {
    setSessionId(null);
    setMessages([]);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40">
        <MessageSquare className="h-4 w-4 text-violet-400" />
        <span className="text-sm font-medium">AI 对话</span>
        <Button variant="ghost" size="sm" className="ml-auto h-7 px-2" onClick={handleNewChat}>
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ScrollArea className="flex-1 p-3">
        <div className="space-y-3">
          {messages.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-8">
              和 AI 聊聊当下的市场吧
            </p>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`text-sm ${
                msg.role === "user"
                  ? "ml-8 bg-violet-600/20 rounded-lg p-2"
                  : "mr-4 bg-muted/50 rounded-lg p-2"
              }`}
            >
              <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed">{msg.content}</pre>
            </div>
          ))}
          {chatMutation.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground mr-4">
              <Loader2 className="h-3 w-3 animate-spin" />
              AI 思考中...
            </div>
          )}
        </div>
      </ScrollArea>

      <div className="border-t border-border/40 p-2 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
          placeholder="输入消息..."
          className="flex-1 bg-muted/30 border border-border/40 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
          disabled={chatMutation.isPending}
        />
        <Button
          size="sm"
          className="px-3"
          onClick={handleSend}
          disabled={!input.trim() || chatMutation.isPending}
        >
          <Send className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

// ── Main Page ───────────────────────────────────
export default function AIPage() {
  const { data: reports, isLoading: reportsLoading } = useAIReports();
  const { data: datesData } = useAIReportDates();
  const triggerMutation = useTriggerAIAnalysis();

  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const { data: selectedReport, isLoading: reportLoading } = useAIReportByDate(
    selectedDate || ""
  );

  // Auto-select latest report date
  const latestDate = reports?.[0]?.report_date;
  const activeDate = selectedDate || latestDate || "";

  const reportDates = new Set(datesData?.dates ?? []);

  return (
    <div className="flex h-[calc(100vh-3rem)]">
      {/* Left: Date list */}
      <div className="w-56 border-r border-border/40 flex flex-col">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40">
          <Calendar className="h-4 w-4" />
          <span className="text-sm font-medium">分析报告</span>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto h-7 px-2"
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending}
          >
            {triggerMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
        <ScrollArea className="flex-1">
          {reportsLoading ? (
            <div className="p-4 text-center text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mx-auto" />
            </div>
          ) : !reports?.length ? (
            <div className="p-4 text-center text-xs text-muted-foreground">
              暂无报告。点击刷新按钮手动触发AI分析。
            </div>
          ) : (
            <div className="py-1">
              {reports.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setSelectedDate(r.report_date)}
                  className={`w-full text-left px-3 py-2 text-sm transition-colors hover:bg-accent/50 ${
                    activeDate === r.report_date ? "bg-accent text-accent-foreground" : ""
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">{r.report_date}</span>
                    {r.market_regime && (
                      <span className={`text-[10px] ${
                        r.market_regime === "bull" ? "text-green-400" :
                        r.market_regime === "bear" ? "text-red-400" : "text-yellow-400"
                      }`}>
                        {regimeLabel(r.market_regime)}
                      </span>
                    )}
                  </div>
                  {r.summary && (
                    <p className="text-xs text-muted-foreground truncate mt-0.5">
                      {r.summary}
                    </p>
                  )}
                </button>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>

      {/* Center: Report viewer */}
      <div className="flex-1 overflow-auto p-4">
        {reportLoading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : selectedReport ? (
          <ReportViewer report={selectedReport} />
        ) : (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
            <Sparkles className="h-10 w-10 opacity-30" />
            <p className="text-sm">选择左侧日期查看报告，或点击刷新按钮触发分析</p>
          </div>
        )}
      </div>

      {/* Right: Chat */}
      <div className="w-80 border-l border-border/40">
        <ChatWidget />
      </div>
    </div>
  );
}
```

**Step 3: Verify frontend compiles**

Run: `cd /Users/allenqiang/stockagent/web && npx tsc --noEmit 2>&1 | head -20`

Expected: No new errors

---

### Task 8: Integration Verification

**Files:** (no new files — verification only)

**Step 1: Verify backend starts and AI routes are accessible**

Run: `cd /Users/allenqiang/stockagent && python -c "
from api.main import app
routes = [r.path for r in app.routes if hasattr(r, 'path') and '/ai/' in r.path]
print('AI routes:', routes)
assert any('/ai/reports' in r for r in routes), 'Missing /ai/reports route'
assert any('/ai/chat' in r for r in routes), 'Missing /ai/chat route'
print('ALL OK')
"`

Expected: Lists AI routes and prints `ALL OK`

**Step 2: Verify Claude CLI is callable**

Run: `claude --version`

Expected: Version string (e.g., `2.1.37 (Claude Code)`)

**Step 3: Verify frontend builds without errors**

Run: `cd /Users/allenqiang/stockagent/web && npx tsc --noEmit 2>&1 | tail -5`

Expected: No errors or only pre-existing ones

---

## Summary of All Tasks

| Task | Description | Files |
|------|-------------|-------|
| 1 | SQLAlchemy ORM models (AIReport, AIChatSession) | `api/models/ai_analyst.py`, `api/main.py` |
| 2 | Claude CLI runner service | `api/services/claude_runner.py` |
| 3 | Integrate AI analysis into signal scheduler | `api/services/signal_scheduler.py` |
| 4 | Pydantic schemas for AI API | `api/schemas/ai_analyst.py` |
| 5 | FastAPI router (reports + chat endpoints) | `api/routers/ai_analyst.py`, `api/main.py` |
| 6 | Frontend types, API client, query hooks | `web/src/types/index.ts`, `web/src/lib/api.ts`, `web/src/hooks/use-queries.ts` |
| 7 | Frontend AI page (report viewer + chat widget) | `web/src/app/ai/page.tsx`, `web/src/components/nav-bar.tsx` |
| 8 | Integration verification | (verification only) |
