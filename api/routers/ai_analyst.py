"""AI Analyst router — daily reports and chat sessions."""

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.ai_analyst import AIReport, AIChatSession
from api.schemas.ai_analyst import (
    AIReportResponse,
    AIReportListItem,
    AIReportSaveRequest,
    ChatRequest,
    ChatResponse,
    ChatSessionResponse,
)

router = APIRouter(prefix="/api/ai", tags=["ai-analyst"])


# ── Reports ──────────────────────────────────────

@router.get("/reports", response_model=list[AIReportListItem])
def list_reports(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List recent AI analysis reports, ordered by date descending."""
    rows = (
        db.query(AIReport)
        .order_by(AIReport.report_date.desc())
        .limit(limit)
        .all()
    )
    return [
        AIReportListItem(
            id=r.id,
            report_date=r.report_date,
            report_type=r.report_type,
            market_regime=r.market_regime,
            summary=r.summary or "",
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.get("/reports/dates")
def list_report_dates(db: Session = Depends(get_db)):
    """List distinct dates that have reports (for calendar widget)."""
    rows = (
        db.query(AIReport.report_date)
        .distinct()
        .order_by(AIReport.report_date.desc())
        .all()
    )
    return {"dates": [r[0] for r in rows]}


@router.get("/reports/date/{date_str}", response_model=AIReportResponse)
def get_report_by_date(date_str: str, db: Session = Depends(get_db)):
    """Get a report by its date string (YYYY-MM-DD)."""
    report = (
        db.query(AIReport)
        .filter(AIReport.report_date == date_str)
        .first()
    )
    if not report:
        raise HTTPException(404, f"No report found for date {date_str}")
    return _report_to_response(report)


@router.post("/reports/save")
def save_report(body: AIReportSaveRequest, db: Session = Depends(get_db)):
    """Save an AI analysis report (called by Next.js worker after analysis completes)."""
    report = AIReport(
        report_date=body.report_date,
        report_type=body.report_type,
        market_regime=body.market_regime,
        market_regime_confidence=body.market_regime_confidence,
        recommendations=body.recommendations,
        strategy_actions=body.strategy_actions,
        thinking_process=body.thinking_process,
        summary=body.summary,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # Auto-execute bot trades from recommendations
    bot_trades_result = []
    if body.recommendations:
        from api.services.bot_trading_engine import execute_bot_trades
        try:
            bot_trades_result = execute_bot_trades(
                db, report.id, body.report_date, body.recommendations
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Bot trade execution failed: %s", e)

    return {
        "id": report.id,
        "report_date": report.report_date,
        "summary": report.summary,
        "bot_trades": bot_trades_result,
    }


@router.get("/reports/{report_id}", response_model=AIReportResponse)
def get_report(report_id: int, db: Session = Depends(get_db)):
    """Get a single report by ID."""
    report = db.query(AIReport).get(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return _report_to_response(report)


def _report_to_response(report: AIReport) -> AIReportResponse:
    """Convert an AIReport ORM instance to the response schema."""
    return AIReportResponse(
        id=report.id,
        report_date=report.report_date,
        report_type=report.report_type,
        market_regime=report.market_regime,
        market_regime_confidence=report.market_regime_confidence,
        recommendations=report.recommendations,
        strategy_actions=report.strategy_actions,
        thinking_process=report.thinking_process or "",
        summary=report.summary or "",
        created_at=report.created_at.isoformat() if report.created_at else "",
    )


@router.post("/analyze")
def trigger_analysis(
    report_date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
    db: Session = Depends(get_db),
):
    """Manually trigger AI daily analysis for a given date."""
    from api.services.claude_runner import run_daily_analysis

    target_date = report_date or date.today().isoformat()

    result = run_daily_analysis(target_date)

    if result is None:
        raise HTTPException(500, "AI analysis failed — check server logs for details")

    # Save to DB
    report = AIReport(
        report_date=target_date,
        report_type=result.get("report_type", "daily"),
        market_regime=result.get("market_regime"),
        market_regime_confidence=result.get("market_regime_confidence"),
        recommendations=result.get("recommendations"),
        strategy_actions=result.get("strategy_actions"),
        thinking_process=result.get("thinking_process", ""),
        summary=result.get("summary", ""),
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {
        "id": report.id,
        "report_date": report.report_date,
        "summary": report.summary,
    }


# ── Chat ─────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """Send a message to the AI analyst. Creates or continues a chat session."""
    from api.services.claude_runner import run_chat

    session = None
    claude_session_id = None

    # Look up existing session if session_id provided
    if body.session_id:
        session = (
            db.query(AIChatSession)
            .filter(AIChatSession.session_id == body.session_id)
            .first()
        )
        if session:
            claude_session_id = session.claude_session_id

    # Call Claude — returns (response_text, claude_session_id)
    response_text, new_claude_session_id = run_chat(
        message=body.message,
        claude_session_id=claude_session_id,
    )

    if session:
        # Append to existing session
        messages = session.messages if session.messages else []
        messages.append({"role": "user", "content": body.message})
        messages.append({"role": "assistant", "content": response_text})
        session.messages = messages
        session.claude_session_id = new_claude_session_id
        db.commit()
        db.refresh(session)
        session_id = session.session_id
    else:
        # Create new session
        session_id = body.session_id or str(uuid.uuid4())
        messages = [
            {"role": "user", "content": body.message},
            {"role": "assistant", "content": response_text},
        ]
        session = AIChatSession(
            session_id=session_id,
            claude_session_id=new_claude_session_id,
            title=body.message[:50],
            messages=messages,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    return ChatResponse(
        session_id=session_id,
        response=response_text,
    )


@router.get("/chat/sessions", response_model=list[ChatSessionResponse])
def list_chat_sessions(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List recent chat sessions with message counts."""
    rows = (
        db.query(AIChatSession)
        .order_by(AIChatSession.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        ChatSessionResponse(
            id=s.id,
            session_id=s.session_id,
            title=s.title,
            message_count=len(s.messages) if s.messages else 0,
            created_at=s.created_at.isoformat() if s.created_at else "",
            updated_at=s.updated_at.isoformat() if s.updated_at else "",
        )
        for s in rows
    ]


@router.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str, db: Session = Depends(get_db)):
    """Get full chat history for a session."""
    session = (
        db.query(AIChatSession)
        .filter(AIChatSession.session_id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Chat session not found")
    return {
        "session_id": session.session_id,
        "title": session.title,
        "messages": session.messages if session.messages else [],
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "updated_at": session.updated_at.isoformat() if session.updated_at else "",
    }
