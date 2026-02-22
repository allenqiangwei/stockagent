"""Backtest router — run (with SSE), history, detail.

Auto-selects portfolio engine when strategy has portfolio_config set.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.strategy import Strategy
from api.schemas.backtest import BacktestRunRequest
from api.services.backtest_engine import BacktestService

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


def _resolve_stock_codes(req: BacktestRunRequest, db: Session) -> list[str]:
    """Resolve stock codes from request, falling back to cached stocks."""
    if req.stock_codes:
        return req.stock_codes
    from api.services.data_collector import DataCollector
    return DataCollector(db).get_stocks_with_data(min_rows=60)


def _is_portfolio_mode(strategy_id: int, db: Session) -> bool:
    """Check if strategy has portfolio_config set."""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    return bool(s and s.portfolio_config)


@router.post("/run")
def run_backtest(req: BacktestRunRequest, db: Session = Depends(get_db)):
    """Run a backtest with SSE progress streaming."""
    service = BacktestService(db)
    stock_codes = _resolve_stock_codes(req, db)

    if _is_portfolio_mode(req.strategy_id, db):
        generator = service.run_portfolio_backtest(
            strategy_id=req.strategy_id,
            start_date=req.start_date,
            end_date=req.end_date,
            stock_codes=stock_codes,
        )
    else:
        generator = service.run_backtest(
            strategy_id=req.strategy_id,
            start_date=req.start_date,
            end_date=req.end_date,
            capital_per_trade=req.capital_per_trade,
            stock_codes=stock_codes,
        )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/run/sync")
def run_backtest_sync(req: BacktestRunRequest, db: Session = Depends(get_db)):
    """Run a backtest synchronously (returns full result at once)."""
    service = BacktestService(db)
    stock_codes = _resolve_stock_codes(req, db)

    if _is_portfolio_mode(req.strategy_id, db):
        result = service.run_portfolio_backtest_sync(
            strategy_id=req.strategy_id,
            start_date=req.start_date,
            end_date=req.end_date,
            stock_codes=stock_codes,
        )
    else:
        result = service.run_backtest_sync(
            strategy_id=req.strategy_id,
            start_date=req.start_date,
            end_date=req.end_date,
            capital_per_trade=req.capital_per_trade,
            stock_codes=stock_codes,
        )

    if result is None:
        raise HTTPException(400, "Backtest failed: no data or invalid strategy")
    return result


@router.get("/runs")
def list_runs(
    strategy_id: int = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List backtest run history."""
    service = BacktestService(db)
    return service.get_runs(strategy_id, limit)


@router.get("/runs/{run_id}")
def get_run_detail(run_id: int, db: Session = Depends(get_db)):
    """Get full detail of a backtest run including trades."""
    service = BacktestService(db)
    result = service.get_run_detail(run_id)
    if result is None:
        raise HTTPException(404, "Backtest run not found")
    return result
