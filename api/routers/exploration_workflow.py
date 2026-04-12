"""Exploration Workflow REST API — control the automated strategy exploration engine."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.services.exploration_engine import ExplorationEngine

router = APIRouter(prefix="/api/exploration-workflow", tags=["exploration-workflow"])

_engine = ExplorationEngine()


@router.post("/start")
def start_exploration(
    rounds: int = Query(1, ge=1, le=100),
    experiments_per_round: int = Query(50, ge=5, le=200),
    source_strategy_id: int = Query(116987),
):
    """Start exploration workflow in background."""
    return _engine.start(rounds, experiments_per_round, source_strategy_id)


@router.post("/stop")
def stop_exploration():
    """Request graceful stop after current round."""
    return _engine.stop()


@router.get("/status")
def get_status():
    """Get real-time workflow status."""
    return _engine.get_status()


@router.get("/history")
def get_history(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Get recent exploration round history."""
    from api.models.ai_lab import ExplorationRound
    rounds = (
        db.query(ExplorationRound)
        .order_by(ExplorationRound.round_number.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "round_number": r.round_number, "mode": r.mode,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "total_experiments": r.total_experiments,
            "total_strategies": r.total_strategies,
            "std_a_count": r.std_a_count,
            "best_strategy_score": r.best_strategy_score,
            "summary": r.summary,
            "memory_synced": r.memory_synced,
        }
        for r in rounds
    ]
