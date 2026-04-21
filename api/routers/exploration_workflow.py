"""Exploration Workflow REST API — control the automated strategy exploration engine."""

import json
import logging
import threading

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.services.exploration_engine import ExplorationEngine, _CHECKPOINT_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exploration-workflow", tags=["exploration-workflow"])

_engine = ExplorationEngine()


# ── Auto-Cron: check every N minutes, start exploration if idle ──

class _ExplorationCron:
    """Periodic scheduler that auto-starts exploration rounds when engine is idle."""

    def __init__(self, engine: ExplorationEngine):
        self._engine = engine
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.interval_minutes = 15
        self.rounds_per_trigger = 1
        self.experiments_per_round = 50
        self.source_strategy_id = 116987

    def start(self, interval_minutes: int = 15):
        if self._running:
            return {"status": "already_running", "interval": self.interval_minutes}
        self.interval_minutes = interval_minutes
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Exploration cron started (interval=%dmin)", self.interval_minutes)
        return {"status": "started", "interval": self.interval_minutes}

    def stop(self):
        if not self._running:
            return {"status": "not_running"}
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Exploration cron stopped")
        return {"status": "stopped"}

    def get_status(self) -> dict:
        return {
            "enabled": self._running,
            "interval_minutes": self.interval_minutes,
            "rounds_per_trigger": self.rounds_per_trigger,
            "experiments_per_round": self.experiments_per_round,
            "source_strategy_id": self.source_strategy_id,
        }

    def _loop(self):
        while self._running and not self._stop_event.is_set():
            try:
                engine_status = self._engine.get_status()
                state = engine_status.get("state", "idle")

                if state == "idle":
                    logger.info("Cron: engine idle, starting exploration round")
                    self._engine.start(
                        self.rounds_per_trigger,
                        self.experiments_per_round,
                        self.source_strategy_id,
                    )
                else:
                    logger.debug("Cron: engine busy (state=%s), skipping", state)
            except Exception as e:
                logger.error("Cron check error: %s", e)

            self._stop_event.wait(self.interval_minutes * 60)


_cron = _ExplorationCron(_engine)


@router.post("/start")
def start_exploration(
    rounds: int = Query(1, ge=1, le=100),
    experiments_per_round: int = Query(50, ge=5, le=200),
    source_strategy_id: int = Query(116987),
):
    """Start exploration workflow in background."""
    return _engine.start(rounds, experiments_per_round, source_strategy_id)


@router.post("/resume")
def resume_exploration():
    """Resume from last checkpoint if available."""
    return _engine.start()  # start() auto-detects checkpoint


@router.post("/stop")
def stop_exploration():
    """Request graceful stop after current round."""
    return _engine.stop()


@router.get("/status")
def get_status():
    """Get real-time workflow status."""
    status = _engine.get_status()
    # Add checkpoint info
    if _CHECKPOINT_PATH.exists():
        try:
            cp = json.loads(_CHECKPOINT_PATH.read_text(encoding="utf-8"))
            status["checkpoint"] = {
                "exists": True,
                "round": cp.get("round_number"),
                "step": cp.get("current_step"),
                "updated_at": cp.get("updated_at"),
            }
        except Exception:
            status["checkpoint"] = {"exists": True, "error": "unreadable"}
    else:
        status["checkpoint"] = {"exists": False}

    # Add cron info
    status["cron"] = _cron.get_status()
    return status


# ── Cron endpoints ──

@router.post("/cron/start")
def start_cron(interval_minutes: int = Query(15, ge=5, le=120)):
    """Start auto-cron: checks every N minutes, starts exploration if idle."""
    return _cron.start(interval_minutes)


@router.post("/cron/stop")
def stop_cron():
    """Stop auto-cron."""
    return _cron.stop()


@router.get("/cron/status")
def cron_status():
    """Get cron status."""
    return _cron.get_status()


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
